"""
Statement import (Phase 22d / 22d-2) — review-first reconciliation.

POST /statements/import parses an uploaded statement (CSV or text-based PDF), stages immutable
rows, and for each row either MATCHES an existing confirmed money_event (currency + amount →
recorded as verified) or IMPORTS it (creates a capture_event + a pending finance inbox_item, which
the user reviews/confirms through the normal pipeline → money_event). Nothing becomes a money_event
without explicit inbox confirmation.

CSV is parsed deterministically. PDF text is structured by gpt-4o-mini (statement_pdf); the LLM
only PROPOSES rows — every row still lands in the inbox for explicit review, so extraction errors
are caught there, never auto-trusted.

GET /statements lists imports; GET /statements/{id} lists that import's rows.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user
from app.services.statement_import import StatementParseError, parse_statement_csv
from app.services.statement_pdf import (
    StatementExtractionError,
    extract_pdf_text,
    extract_rows_from_text,
)

router = APIRouter(prefix="/statements", tags=["statements"])

MAX_STATEMENT_BYTES = 5 * 1024 * 1024


def _is_pdf(filename: Optional[str], raw: bytes) -> bool:
    """PDF if the filename ends in .pdf or the bytes carry the %PDF magic header."""
    if filename and filename.lower().endswith(".pdf"):
        return True
    return raw[:5].startswith(b"%PDF")


class StatementImportResult(BaseModel):
    import_id: str
    row_count: int
    matched_count: int
    imported_count: int


class StatementImportSummary(BaseModel):
    id: str
    source_label: Optional[str] = None
    row_count: int
    matched_count: int
    imported_count: int
    created_at: str


class StatementImportsListResponse(BaseModel):
    items: list[StatementImportSummary]
    total: int


class StatementRowResponse(BaseModel):
    id: str
    occurred_on: Optional[str] = None
    description: Optional[str] = None
    amount: float
    currency: str
    status: str
    matched_money_event_id: Optional[str] = None
    inbox_item_id: Optional[str] = None


class StatementRowsResponse(BaseModel):
    items: list[StatementRowResponse]
    total: int


def _match_money_event(client, owner_id: str, currency: str, amount: float) -> Optional[str]:
    """v1 match: any confirmed expense money_event with the same currency + amount."""
    res = (
        client.table("money_events")
        .select("id")
        .eq("owner_id", owner_id)
        .eq("direction", "expense")
        .eq("currency", currency)
        .eq("amount", amount)
        .limit(1)
        .execute()
    )
    return res.data[0]["id"] if res.data else None


@router.post("/import", response_model=StatementImportResult)
async def import_statement(
    owner_id: str = Depends(require_user),
    file: UploadFile = File(...),
    default_currency: str = Form("SGD"),
) -> StatementImportResult:
    raw = await file.read()
    if len(raw) > MAX_STATEMENT_BYTES:
        raise HTTPException(status_code=413, detail="Statement file too large")

    if _is_pdf(file.filename, raw):
        # PDF → extract text (deterministic) → structure rows via the LLM. The LLM only proposes;
        # every row still goes through the inbox for review.
        try:
            text = extract_pdf_text(raw)
        except StatementParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        try:
            rows = await extract_rows_from_text(text, default_currency)
        except StatementExtractionError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        if not rows:
            raise HTTPException(status_code=422, detail="No expense lines were found in this PDF.")
    else:
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(status_code=422, detail="File must be a UTF-8 CSV or a PDF")
        try:
            rows = parse_statement_csv(content, default_currency)
        except StatementParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        header = (
            client.table("statement_imports")
            .insert({"source_label": file.filename, "row_count": len(rows)})
            .execute()
        )
        import_id = header.data[0]["id"]

        matched_count = 0
        imported_count = 0
        for idx, row in enumerate(rows):
            # raw_descriptor is the verbatim bank line (preserved end-to-end); merchant is the
            # normalized brand when the parser/LLM recognised one, else fall back to the descriptor.
            descriptor = row.get("raw_descriptor") or row.get("merchant")
            merchant = row.get("merchant") or descriptor

            money_event_id = _match_money_event(client, owner_id, row["currency"], row["amount"])
            if money_event_id:
                client.table("statement_rows").insert({
                    "import_id": import_id,
                    "occurred_on": row["occurred_on"],
                    "description": descriptor,
                    "amount": row["amount"],
                    "currency": row["currency"],
                    "status": "matched",
                    "matched_money_event_id": money_event_id,
                }).execute()
                matched_count += 1
                continue

            # Unmatched → create a capture_event + pending finance inbox_item (review pipeline).
            capture = client.table("capture_events").insert({
                "source": "statement_import",
                "source_message_id": f"{import_id}:{idx}",
                "raw_text": descriptor,
                "processing_status": "classified",
                "metadata": {"import_id": import_id, "occurred_on": row["occurred_on"]},
            }).execute()
            capture_id = capture.data[0]["id"]
            inbox = client.table("inbox_items").insert({
                "capture_event_id": capture_id,
                "item_type": "finance",
                "review_status": "pending",
                "title": (merchant or "Statement expense")[:100],
                "body": descriptor or "",
                "structured_json": {
                    "amount": row["amount"],
                    "currency": row["currency"],
                    "direction": "expense",
                    "merchant": merchant,
                    "category": row.get("category"),
                    # The exact bank descriptor is preserved in notes so it survives into the
                    # money_event on confirm (confirm_finance_item copies structured_json->>'notes').
                    "notes": descriptor,
                },
                "confidence": 1.0,
            }).execute()
            inbox_id = inbox.data[0]["id"]
            client.table("statement_rows").insert({
                "import_id": import_id,
                "occurred_on": row["occurred_on"],
                "description": descriptor,
                "amount": row["amount"],
                "currency": row["currency"],
                "status": "imported",
                "inbox_item_id": inbox_id,
            }).execute()
            imported_count += 1

        client.table("statement_imports").update({
            "matched_count": matched_count,
            "imported_count": imported_count,
        }).eq("id", import_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Statement import failed") from exc

    return StatementImportResult(
        import_id=import_id,
        row_count=len(rows),
        matched_count=matched_count,
        imported_count=imported_count,
    )


@router.get("", response_model=StatementImportsListResponse)
def list_imports(owner_id: str = Depends(require_user)) -> StatementImportsListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")
    try:
        result = (
            client.table("statement_imports")
            .select("*")
            .eq("owner_id", owner_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc
    items = [StatementImportSummary(**row) for row in result.data]
    return StatementImportsListResponse(items=items, total=len(items))


@router.get("/{import_id}", response_model=StatementRowsResponse)
def list_rows(import_id: str, owner_id: str = Depends(require_user)) -> StatementRowsResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")
    try:
        result = (
            client.table("statement_rows")
            .select("*")
            .eq("owner_id", owner_id)
            .eq("import_id", import_id)
            .order("created_at", desc=False)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc
    items = [
        StatementRowResponse(
            id=r["id"], occurred_on=r.get("occurred_on"), description=r.get("description"),
            amount=r["amount"], currency=r["currency"], status=r["status"],
            matched_money_event_id=r.get("matched_money_event_id"),
            inbox_item_id=r.get("inbox_item_id"),
        )
        for r in result.data
    ]
    return StatementRowsResponse(items=items, total=len(items))
