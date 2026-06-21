import math
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError as PydanticValidationError
from supabase import Client

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.routes.finance import MoneyEventResponse
from app.routes.food import FoodLogResponse
from app.routes.tasks import TaskResponse
from app.security import require_dev_admin_token
from app.services.classifier import _ITEM_TYPE_SCHEMAS

router = APIRouter(prefix="/inbox", tags=["inbox"])

KNOWN_ITEM_TYPES = set(_ITEM_TYPE_SCHEMAS.keys())


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_structured_json(item_type: str, sj: dict) -> tuple[str | None, dict]:
    """
    Validates and normalizes structured_json against the per-type Pydantic schema.

    Returns (None, normalized_dict) on success — normalized_dict includes model defaults
    (e.g. currency="SGD") via model_dump(exclude_none=True) so callers can persist
    the complete canonical form.

    Returns (error_str, original_sj) on validation failure.
    """
    schema = _ITEM_TYPE_SCHEMAS.get(item_type)
    if schema is not None:
        try:
            validated = schema.model_validate(sj)
            return None, validated.model_dump(exclude_none=True)
        except PydanticValidationError as exc:
            return str(exc), sj
    return None, sj


class ReviewedItemResponse(BaseModel):
    id: str
    item_type: str
    review_status: str
    title: Optional[str] = None
    body: Optional[str] = None
    structured_json: dict[str, Any]
    confidence: Optional[float] = None
    reviewed_at: Optional[str] = None
    updated_at: str


class ConfirmTaskResponse(BaseModel):
    """Returned when a task-type item is confirmed: the inbox item plus its new task."""
    inbox_item: ReviewedItemResponse
    task: TaskResponse


class ConfirmFinanceResponse(BaseModel):
    """Returned when a finance expense item is confirmed: the inbox item plus its money_event."""
    inbox_item: ReviewedItemResponse
    money_event: MoneyEventResponse


class ConfirmFoodResponse(BaseModel):
    """Returned when a food-type item is confirmed: the inbox item plus its new food_log."""
    inbox_item: ReviewedItemResponse
    food_log: FoodLogResponse


class EditInboxItemRequest(BaseModel):
    item_type: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    structured_json: Optional[dict[str, Any]] = None


def _fetch_item(client: Client, inbox_id: str) -> Optional[dict]:
    res = client.table("inbox_items").select("*").eq("id", inbox_id).execute()
    return res.data[0] if res.data else None


def _fetch_task(client: Client, inbox_id: str) -> Optional[dict]:
    res = client.table("tasks").select("*").eq("inbox_item_id", inbox_id).execute()
    return res.data[0] if res.data else None


def _recheck_task_confirm(
    client: Client, inbox_id: str, original: dict
) -> ConfirmTaskResponse:
    """
    Resolve the true outcome after a confirm_task_item RPC error (or empty result)
    by re-reading state and comparing against the snapshot we validated pre-call.

    A raised RPC does not tell us whether the transaction committed — the failure
    could be a post-commit transport error, a genuine concurrency conflict, or a
    DB/permission failure that left the row untouched. Decide from observed state:

      1. confirmed + task exists      → the RPC committed → idempotent success (200)
      2. state or updated_at changed  → another writer won the race → 409
      3. unchanged (still pending,
         same updated_at, no task)    → the RPC failed without committing → 503
    """
    try:
        item = _fetch_item(client, inbox_id)
        task = _fetch_task(client, inbox_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    # 1. The transaction committed despite the client-side error.
    if item is not None and task is not None and item["review_status"] == "confirmed":
        return ConfirmTaskResponse(
            inbox_item=ReviewedItemResponse(**item), task=TaskResponse(**task)
        )

    # 2. The row moved away from the snapshot we validated → concurrency conflict.
    if (
        item is None
        or item["review_status"] != original["review_status"]
        or item["updated_at"] != original["updated_at"]
    ):
        raise HTTPException(
            status_code=409, detail="Item was modified concurrently; confirm failed"
        )

    # 3. Unchanged and still pending with no task → the RPC failed without committing.
    raise HTTPException(
        status_code=503, detail="Task confirmation database operation failed"
    )


def _confirm_task(client: Client, inbox_id: str, item: dict) -> ConfirmTaskResponse:
    """
    Phase 8 atomic confirmation for task-type items. Delegates the task insert +
    inbox confirmation to the confirm_task_item RPC so both happen in one
    transaction. Never performs a separate insert + update from Python.
    """
    # Idempotency / legacy handling for already-reviewed items.
    if item["review_status"] == "confirmed":
        try:
            existing = _fetch_task(client, inbox_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database query failed") from exc
        if existing is not None:
            return ConfirmTaskResponse(
                inbox_item=ReviewedItemResponse(**item), task=TaskResponse(**existing)
            )
        # Confirmed before the tasks module existed (Phase 7) → do NOT backfill.
        raise HTTPException(
            status_code=409,
            detail="Item was confirmed before the tasks module existed; backfill is not supported.",
        )

    if item["review_status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot confirm item with review_status='{item['review_status']}'",
        )

    err, _normalized = _validate_structured_json("task", item["structured_json"])
    if err:
        raise HTTPException(status_code=400, detail=f"structured_json invalid: {err}")

    if not (item.get("title") or "").strip():
        raise HTTPException(
            status_code=400,
            detail="A task requires a non-empty title before it can be confirmed.",
        )

    try:
        result = client.rpc(
            "confirm_task_item",
            {"p_inbox_id": inbox_id, "p_expected_updated_at": item["updated_at"]},
        ).execute()
    except Exception:
        # The RPC raised — we can't tell from the exception whether it committed.
        # Re-read state to map to idempotent success / 409 conflict / 503 failure.
        return _recheck_task_confirm(client, inbox_id, item)

    data = result.data
    if not data:
        return _recheck_task_confirm(client, inbox_id, item)

    return ConfirmTaskResponse(
        inbox_item=ReviewedItemResponse(**data["inbox_item"]),
        task=TaskResponse(**data["task"]),
    )


def _fetch_money_event(client: Client, inbox_id: str) -> Optional[dict]:
    res = client.table("money_events").select("*").eq("inbox_item_id", inbox_id).execute()
    return res.data[0] if res.data else None


def _recheck_finance_confirm(
    client: Client, inbox_id: str, original: dict
) -> ConfirmFinanceResponse:
    """
    Finance counterpart of _recheck_task_confirm. After a confirm_finance_item RPC error
    (or empty result), re-read state and compare to the validated snapshot:
      1. confirmed + money_event exists → idempotent success (200)
      2. state or updated_at changed    → concurrency conflict (409)
      3. unchanged pending, no event    → the RPC failed without committing (503)
    """
    try:
        item = _fetch_item(client, inbox_id)
        event = _fetch_money_event(client, inbox_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    if item is not None and event is not None and item["review_status"] == "confirmed":
        return ConfirmFinanceResponse(
            inbox_item=ReviewedItemResponse(**item),
            money_event=MoneyEventResponse(**event),
        )

    if (
        item is None
        or item["review_status"] != original["review_status"]
        or item["updated_at"] != original["updated_at"]
    ):
        raise HTTPException(
            status_code=409, detail="Item was modified concurrently; confirm failed"
        )

    raise HTTPException(
        status_code=503, detail="Finance confirmation database operation failed"
    )


def _confirm_finance(client: Client, inbox_id: str, item: dict) -> ConfirmFinanceResponse:
    """
    Phase 9 atomic confirmation for finance EXPENSE items. Delegates the money_event insert +
    inbox confirmation to the confirm_finance_item RPC so both happen in one transaction.
    Never performs a separate insert + update from Python. Income finance items never reach
    here — the router routes them to the Phase 7 status-only path (no domain record).
    """
    # Idempotency / legacy handling for already-reviewed items.
    if item["review_status"] == "confirmed":
        try:
            existing = _fetch_money_event(client, inbox_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database query failed") from exc
        if existing is not None:
            return ConfirmFinanceResponse(
                inbox_item=ReviewedItemResponse(**item),
                money_event=MoneyEventResponse(**existing),
            )
        # Confirmed before the finance module existed (or an income status-only confirm)
        # → do NOT backfill.
        raise HTTPException(
            status_code=409,
            detail="Item was confirmed before the finance module existed; backfill is not supported.",
        )

    if item["review_status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot confirm item with review_status='{item['review_status']}'",
        )

    err, normalized = _validate_structured_json("finance", item["structured_json"])
    if err:
        raise HTTPException(status_code=400, detail=f"structured_json invalid: {err}")

    _amount = float(normalized.get("amount", 0))
    if not math.isfinite(_amount) or _amount <= 0:
        raise HTTPException(
            status_code=400, detail="A finance amount must be a finite number greater than zero."
        )

    try:
        result = client.rpc(
            "confirm_finance_item",
            {"p_inbox_id": inbox_id, "p_expected_updated_at": item["updated_at"]},
        ).execute()
    except Exception:
        # The RPC raised — re-read state to map to idempotent / 409 / 503.
        return _recheck_finance_confirm(client, inbox_id, item)

    data = result.data
    if not data:
        return _recheck_finance_confirm(client, inbox_id, item)

    return ConfirmFinanceResponse(
        inbox_item=ReviewedItemResponse(**data["inbox_item"]),
        money_event=MoneyEventResponse(**data["money_event"]),
    )


def _fetch_food_log(client: Client, inbox_id: str) -> Optional[dict]:
    res = client.table("food_logs").select("*").eq("inbox_item_id", inbox_id).execute()
    return res.data[0] if res.data else None


def _recheck_food_confirm(
    client: Client, inbox_id: str, original: dict
) -> ConfirmFoodResponse:
    """
    Food counterpart of _recheck_finance_confirm. After a confirm_food_item RPC error
    (or empty result), re-read state and compare to the validated snapshot:
      1. confirmed + food_log exists → idempotent success (200)
      2. state or updated_at changed  → concurrency conflict (409)
      3. unchanged pending, no log    → the RPC failed without committing (503)
    """
    try:
        item = _fetch_item(client, inbox_id)
        food_log = _fetch_food_log(client, inbox_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    if item is not None and food_log is not None and item["review_status"] == "confirmed":
        return ConfirmFoodResponse(
            inbox_item=ReviewedItemResponse(**item),
            food_log=FoodLogResponse(**food_log),
        )

    if (
        item is None
        or item["review_status"] != original["review_status"]
        or item["updated_at"] != original["updated_at"]
    ):
        raise HTTPException(
            status_code=409, detail="Item was modified concurrently; confirm failed"
        )

    raise HTTPException(
        status_code=503, detail="Food confirmation database operation failed"
    )


def _confirm_food(client: Client, inbox_id: str, item: dict) -> ConfirmFoodResponse:
    """
    Phase 11 atomic confirmation for food-type items. Delegates the food_log insert +
    inbox confirmation to the confirm_food_item RPC so both happen in one transaction.
    Never performs a separate insert + update from Python.
    """
    # Idempotency: already confirmed.
    if item["review_status"] == "confirmed":
        try:
            existing = _fetch_food_log(client, inbox_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database query failed") from exc
        if existing is not None:
            return ConfirmFoodResponse(
                inbox_item=ReviewedItemResponse(**item),
                food_log=FoodLogResponse(**existing),
            )
        # Confirmed before the food module existed → do NOT backfill.
        raise HTTPException(
            status_code=409,
            detail="Item was confirmed before the food module existed; backfill is not supported.",
        )

    if item["review_status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot confirm item with review_status='{item['review_status']}'",
        )

    err, normalized = _validate_structured_json("food", item["structured_json"])
    if err:
        raise HTTPException(status_code=400, detail=f"structured_json invalid: {err}")

    if not (normalized.get("description") or "").strip():
        raise HTTPException(
            status_code=400,
            detail="A food log requires a non-empty description before it can be confirmed.",
        )

    try:
        result = client.rpc(
            "confirm_food_item",
            {"p_inbox_id": inbox_id, "p_expected_updated_at": item["updated_at"]},
        ).execute()
    except Exception:
        return _recheck_food_confirm(client, inbox_id, item)

    data = result.data
    if not data:
        return _recheck_food_confirm(client, inbox_id, item)

    return ConfirmFoodResponse(
        inbox_item=ReviewedItemResponse(**data["inbox_item"]),
        food_log=FoodLogResponse(**data["food_log"]),
    )


@router.patch(
    "/{inbox_id}/confirm",
    dependencies=[Depends(require_dev_admin_token)],
    response_model=None,
)
def confirm_inbox_item(
    inbox_id: str,
) -> ReviewedItemResponse | ConfirmTaskResponse | ConfirmFinanceResponse | ConfirmFoodResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = client.table("inbox_items").select("*").eq("id", inbox_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    if not result.data:
        raise HTTPException(status_code=404, detail="Inbox item not found")

    item = result.data[0]

    # Phase 8: task items confirm atomically and create a linked task record.
    if item["item_type"] == "task":
        return _confirm_task(client, inbox_id, item)

    # Phase 9: finance EXPENSE items confirm atomically and create a money_event.
    # Finance income items fall through to the Phase 7 status-only path (no domain record).
    if item["item_type"] == "finance" and item["structured_json"].get("direction") == "expense":
        return _confirm_finance(client, inbox_id, item)

    # Phase 11: food items confirm atomically and create a food_log.
    if item["item_type"] == "food":
        return _confirm_food(client, inbox_id, item)

    # Non-module items keep the Phase 7 status-only confirmation (no domain record).
    if item["review_status"] == "confirmed":
        return ReviewedItemResponse(**item)

    if item["review_status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot confirm item with review_status='{item['review_status']}'",
        )

    if item["item_type"] == "unknown":
        raise HTTPException(
            status_code=400,
            detail="Cannot confirm an item with item_type='unknown'. Edit it to set a valid type first.",
        )

    err, normalized_sj = _validate_structured_json(item["item_type"], item["structured_json"])
    if err:
        raise HTTPException(status_code=400, detail=f"structured_json invalid: {err}")

    try:
        updated = (
            client.table("inbox_items")
            .update({
                "review_status": "confirmed",
                "reviewed_at": _now_utc(),
                "structured_json": normalized_sj,
            })
            .eq("id", inbox_id)
            .eq("review_status", "pending")
            .eq("updated_at", item["updated_at"])
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database update failed") from exc

    if not updated.data:
        # Concurrent edit changed updated_at before we could confirm — refetch to determine outcome.
        try:
            refetch = client.table("inbox_items").select("*").eq("id", inbox_id).execute()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database query failed") from exc

        if not refetch.data:
            raise HTTPException(status_code=404, detail="Inbox item not found")

        current = refetch.data[0]
        if current["review_status"] == "confirmed":
            return ReviewedItemResponse(**current)
        raise HTTPException(
            status_code=409,
            detail="Item was modified concurrently; confirm failed",
        )

    return ReviewedItemResponse(**updated.data[0])


@router.patch("/{inbox_id}/reject", dependencies=[Depends(require_dev_admin_token)])
def reject_inbox_item(inbox_id: str) -> ReviewedItemResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = client.table("inbox_items").select("*").eq("id", inbox_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    if not result.data:
        raise HTTPException(status_code=404, detail="Inbox item not found")

    item = result.data[0]

    if item["review_status"] == "rejected":
        return ReviewedItemResponse(**item)

    if item["review_status"] == "confirmed":
        raise HTTPException(status_code=409, detail="Cannot reject a confirmed item")

    try:
        updated = (
            client.table("inbox_items")
            .update({"review_status": "rejected", "reviewed_at": _now_utc()})
            .eq("id", inbox_id)
            .in_("review_status", ["pending", "needs_manual_classification"])
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database update failed") from exc

    if not updated.data:
        try:
            refetch = client.table("inbox_items").select("*").eq("id", inbox_id).execute()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database query failed") from exc

        if not refetch.data:
            raise HTTPException(status_code=404, detail="Inbox item not found")

        current = refetch.data[0]
        if current["review_status"] == "rejected":
            return ReviewedItemResponse(**current)
        raise HTTPException(
            status_code=409,
            detail="Item was modified concurrently; reject failed",
        )

    return ReviewedItemResponse(**updated.data[0])


@router.patch("/{inbox_id}", dependencies=[Depends(require_dev_admin_token)])
def edit_inbox_item(inbox_id: str, req: EditInboxItemRequest) -> ReviewedItemResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = client.table("inbox_items").select("*").eq("id", inbox_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    if not result.data:
        raise HTTPException(status_code=404, detail="Inbox item not found")

    item = result.data[0]

    if item["review_status"] in ("confirmed", "rejected"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot edit an item with review_status='{item['review_status']}'",
        )

    eff_type: str = req.item_type if req.item_type is not None else item["item_type"]
    eff_sj: dict = req.structured_json if req.structured_json is not None else item["structured_json"]

    if eff_type not in KNOWN_ITEM_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown item_type: '{eff_type}'")

    type_changed = req.item_type is not None and req.item_type != item["item_type"]
    if req.structured_json is not None or type_changed:
        err, normalized_sj = _validate_structured_json(eff_type, eff_sj)
        if err:
            raise HTTPException(
                status_code=400,
                detail=f"structured_json invalid for '{eff_type}': {err}",
            )
        eff_sj = normalized_sj

    if eff_type == "unknown":
        new_status = "needs_manual_classification"
    elif item["review_status"] == "needs_manual_classification":
        new_status = "pending"
    else:
        new_status = item["review_status"]

    patch: dict[str, Any] = {"review_status": new_status}
    if req.item_type is not None:
        patch["item_type"] = eff_type
    if req.title is not None:
        patch["title"] = req.title
    if req.body is not None:
        patch["body"] = req.body
    if req.structured_json is not None:
        patch["structured_json"] = eff_sj

    try:
        updated = (
            client.table("inbox_items")
            .update(patch)
            .eq("id", inbox_id)
            .in_("review_status", ["pending", "needs_manual_classification"])
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database update failed") from exc

    if not updated.data:
        try:
            refetch = client.table("inbox_items").select("*").eq("id", inbox_id).execute()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database query failed") from exc

        if not refetch.data:
            raise HTTPException(status_code=404, detail="Inbox item not found")

        current = refetch.data[0]
        if current["review_status"] in ("confirmed", "rejected"):
            raise HTTPException(
                status_code=409,
                detail="Item was reviewed concurrently; edit failed",
            )
        raise HTTPException(status_code=503, detail="Edit failed unexpectedly")

    return ReviewedItemResponse(**updated.data[0])
