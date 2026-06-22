import Link from "next/link";
import type {
  AccountSummary,
  BrokerResult,
  BrokerStatus,
  CashBalance,
  CurrencyTotal,
  PnlSource,
  Position,
  Portfolio,
} from "./types";
import { authedFetch } from "@/lib/api";
import { fmtMoney, fmtNum, fmtDateTime, type Tone } from "@/lib/format";
import { PageContainer, PageHeader, Badge, SectionLabel } from "@/components/ui";
import { SnapshotButton } from "./SnapshotButton";

export const dynamic = "force-dynamic";

async function getPortfolio(): Promise<Portfolio> {
  const res = await authedFetch("/portfolio", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

const BROKER_LABELS: Record<string, string> = {
  ibkr: "Interactive Brokers",
  tiger: "Tiger Brokers",
};
function brokerLabel(broker: string): string {
  return BROKER_LABELS[broker] ?? broker;
}

const STATUS_META: Record<BrokerStatus, { label: string; tone: Tone }> = {
  ok: { label: "Connected", tone: "positive" },
  auth_error: { label: "Session expired", tone: "negative" },
  timeout: { label: "Timed out", tone: "warning" },
  unavailable: { label: "Unavailable", tone: "warning" },
  malformed_response: { label: "Unexpected response", tone: "negative" },
  not_configured: { label: "Not configured", tone: "neutral" },
  error: { label: "Error", tone: "negative" },
};

function StatusBadge({ status }: { status: BrokerStatus }) {
  const meta = STATUS_META[status] ?? STATUS_META.error;
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

const PNL_SOURCE_LABELS: Record<PnlSource, string> = {
  broker: "broker-reported",
  calculated: "calculated",
  unavailable: "unavailable",
};

function TodayPnl({
  value,
  source,
  currency,
}: {
  value: number | null;
  source: PnlSource;
  currency: string;
}) {
  if (value === null || source === "unavailable") {
    return <span className="text-faint">today&apos;s P&amp;L unavailable</span>;
  }
  return (
    <span>
      <span className={`numeric ${value >= 0 ? "text-positive" : "text-negative"}`}>
        {fmtMoney(value, currency)}
      </span>{" "}
      <span className="text-xs text-faint">({PNL_SOURCE_LABELS[source]})</span>
    </span>
  );
}

const QUOTE_LABELS: Record<string, string> = {
  live: "live",
  delayed: "delayed",
  stale: "stale",
  unavailable: "no quote",
  unknown: "",
};

function PositionRow({ p }: { p: Position }) {
  const quoteLabel = QUOTE_LABELS[p.quote_status] ?? "";
  const upnlTone =
    p.unrealized_pnl == null ? "text-faint" : p.unrealized_pnl >= 0 ? "text-positive" : "text-negative";
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border py-2.5 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-medium text-fg">{p.symbol}</p>
        <p className="numeric text-xs text-faint">
          {fmtNum(p.quantity)} @ {fmtMoney(p.average_cost, p.currency)}
          {p.asset_class ? ` · ${p.asset_class}` : ""}
          {quoteLabel ? ` · ${quoteLabel}` : ""}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className="numeric text-sm text-fg">{fmtMoney(p.market_value, p.currency)}</p>
        <p className={`numeric text-xs ${upnlTone}`}>
          {fmtMoney(p.unrealized_pnl, p.currency)}
        </p>
      </div>
    </div>
  );
}

function AccountCard({
  account,
  positions,
  cash,
}: {
  account: AccountSummary;
  positions: Position[];
  cash: CashBalance[];
}) {
  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface-raised p-4">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-fg">{account.account_ref}</p>
        <p className="text-xs text-faint">
          Net liq:{" "}
          <span className="numeric text-muted">
            {fmtMoney(account.net_liquidation, account.currency ?? "")}
          </span>
        </p>
      </div>
      <p className="text-xs text-muted">
        Today:{" "}
        <TodayPnl
          value={account.today_pnl}
          source={account.today_pnl_source}
          currency={account.currency ?? ""}
        />
      </p>

      {positions.length > 0 ? (
        <div>
          {positions.map((p, i) => (
            <PositionRow key={i} p={p} />
          ))}
        </div>
      ) : (
        <p className="text-xs italic text-faint">No positions.</p>
      )}

      {cash.length > 0 ? (
        <div className="pt-1">
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-faint">Cash</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {cash.map((c, i) => (
              <span key={i} className="numeric text-xs text-muted">
                {fmtMoney(c.amount, c.currency)}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function BrokerSection({ broker }: { broker: BrokerResult }) {
  const accounts = broker.accounts;
  const positionsByAccount = (ref: string) =>
    broker.positions.filter((p) => p.account_ref === ref);
  const cashByAccount = (ref: string) => broker.cash.filter((c) => c.account_ref === ref);

  return (
    <section className="space-y-4 rounded-xl border border-border bg-surface p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="font-medium text-fg">{brokerLabel(broker.broker)}</h2>
          {broker.as_of ? (
            <p className="mt-0.5 text-xs text-faint">As of {fmtDateTime(broker.as_of)}</p>
          ) : null}
        </div>
        <StatusBadge status={broker.status} />
      </div>

      {broker.status === "ok" ? (
        accounts.length > 0 ? (
          <div className="space-y-3">
            {accounts.map((a, i) => (
              <AccountCard
                key={i}
                account={a}
                positions={positionsByAccount(a.account_ref)}
                cash={cashByAccount(a.account_ref)}
              />
            ))}
          </div>
        ) : (
          <p className="text-sm italic text-faint">No accounts returned.</p>
        )
      ) : (
        <p className="text-sm text-muted">
          {broker.status === "not_configured"
            ? "This broker is not configured. Add its credentials to the backend .env.local."
            : `Could not load data (${broker.error ?? broker.status}). Other brokers are unaffected.`}
        </p>
      )}
    </section>
  );
}

function TotalRow({ t }: { t: CurrencyTotal }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border py-2.5 last:border-0">
      <span className="text-sm font-medium text-fg">{t.currency}</span>
      <div className="text-right">
        <p className="numeric text-sm text-fg">
          {fmtMoney(t.market_value, t.currency)}
          {!t.market_value_complete ? (
            <span className="ml-1 text-xs text-warning">
              (subtotal — {t.market_value_missing} missing)
            </span>
          ) : null}
        </p>
        <p className="numeric text-xs text-faint">
          unrealized {fmtMoney(t.unrealized_pnl, t.currency)}
          {!t.unrealized_pnl_complete ? (
            <span className="ml-1 text-warning">
              (subtotal — {t.unrealized_pnl_missing} missing)
            </span>
          ) : null}
        </p>
      </div>
    </div>
  );
}

export default async function PortfolioPage() {
  const data = await getPortfolio();

  return (
    <PageContainer>
      <PageHeader
        title="Portfolio"
        subtitle={`Read-only · updated ${fmtDateTime(data.generated_at)}`}
        actions={
          <>
            <SnapshotButton />
            <Link
              href="/portfolio/history"
              className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition-colors hover:bg-surface-raised hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              History
            </Link>
          </>
        }
      />

      <div className="space-y-6">
        {data.partial_failure ? (
          <div className="rounded-xl border border-border bg-surface-raised px-4 py-3 text-sm text-warning">
            Some brokers could not be reached. Figures below reflect only the brokers that
            responded successfully.
          </div>
        ) : null}

        {data.totals_by_currency.length > 0 ? (
          <section className="rounded-xl border border-border bg-surface p-6">
            <SectionLabel>Totals by currency</SectionLabel>
            <p className="-mt-2 mb-3 text-xs text-faint">
              Grouped per currency across connected brokers. Currencies are never added together.
            </p>
            {data.totals_by_currency.map((t) => (
              <TotalRow key={t.currency} t={t} />
            ))}
          </section>
        ) : null}

        {data.brokers.map((b) => (
          <BrokerSection key={b.broker} broker={b} />
        ))}
      </div>
    </PageContainer>
  );
}
