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
import { fmtMoney, fmtNum } from "./format";
import { SnapshotButton } from "./SnapshotButton";

export const dynamic = "force-dynamic";

async function getPortfolio(): Promise<Portfolio> {
  const res = await authedFetch("/portfolio", {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }

  return res.json();
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

const BROKER_LABELS: Record<string, string> = {
  ibkr: "Interactive Brokers",
  tiger: "Tiger Brokers",
};

function brokerLabel(broker: string): string {
  return BROKER_LABELS[broker] ?? broker;
}

const STATUS_META: Record<BrokerStatus, { label: string; cls: string }> = {
  ok: { label: "Connected", cls: "bg-green-100 text-green-800" },
  auth_error: { label: "Session expired", cls: "bg-red-100 text-red-800" },
  timeout: { label: "Timed out", cls: "bg-amber-100 text-amber-800" },
  unavailable: { label: "Unavailable", cls: "bg-amber-100 text-amber-800" },
  malformed_response: { label: "Unexpected response", cls: "bg-red-100 text-red-800" },
  not_configured: { label: "Not configured", cls: "bg-gray-100 text-gray-600" },
  error: { label: "Error", cls: "bg-red-100 text-red-800" },
};

function StatusBadge({ status }: { status: BrokerStatus }) {
  const meta = STATUS_META[status] ?? STATUS_META.error;
  return (
    <span className={`shrink-0 text-xs font-medium px-2.5 py-1 rounded-full ${meta.cls}`}>
      {meta.label}
    </span>
  );
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
    return <span className="text-gray-400">today&apos;s P&amp;L unavailable</span>;
  }
  const tone = value >= 0 ? "text-green-700" : "text-red-700";
  return (
    <span>
      <span className={tone}>{fmtMoney(value, currency)}</span>{" "}
      <span className="text-gray-400 text-xs">({PNL_SOURCE_LABELS[source]})</span>
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
  return (
    <div className="flex items-start justify-between gap-3 py-2 border-b border-gray-100 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-medium text-gray-800">{p.symbol}</p>
        <p className="text-xs text-gray-400">
          {fmtNum(p.quantity)} @ {fmtMoney(p.average_cost, p.currency)}
          {p.asset_class ? ` · ${p.asset_class}` : ""}
          {quoteLabel ? ` · ${quoteLabel}` : ""}
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-sm text-gray-800">{fmtMoney(p.market_value, p.currency)}</p>
        <p className="text-xs text-gray-400">
          unrealized {fmtMoney(p.unrealized_pnl, p.currency)}
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
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-gray-700">{account.account_ref}</p>
        <p className="text-xs text-gray-400">
          Net liq: {fmtMoney(account.net_liquidation, account.currency ?? "")}
        </p>
      </div>
      <p className="text-xs text-gray-500">
        Today: <TodayPnl value={account.today_pnl} source={account.today_pnl_source} currency={account.currency ?? ""} />
      </p>

      {positions.length > 0 ? (
        <div>{positions.map((p, i) => <PositionRow key={i} p={p} />)}</div>
      ) : (
        <p className="text-xs text-gray-400 italic">No positions.</p>
      )}

      {cash.length > 0 && (
        <div className="pt-1">
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">
            Cash
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {cash.map((c, i) => (
              <span key={i} className="text-xs text-gray-600">
                {fmtMoney(c.amount, c.currency)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function BrokerSection({ broker }: { broker: BrokerResult }) {
  const accounts = broker.accounts;
  const positionsByAccount = (ref: string) =>
    broker.positions.filter((p) => p.account_ref === ref);
  const cashByAccount = (ref: string) =>
    broker.cash.filter((c) => c.account_ref === ref);

  return (
    <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="font-medium text-gray-900">{brokerLabel(broker.broker)}</h2>
          {broker.as_of && (
            <p className="text-xs text-gray-400 mt-0.5">As of {fmtTime(broker.as_of)}</p>
          )}
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
          <p className="text-sm text-gray-400 italic">No accounts returned.</p>
        )
      ) : (
        <p className="text-sm text-gray-500">
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
    <div className="flex items-baseline justify-between gap-3 py-2 border-b border-gray-100 last:border-0">
      <span className="text-sm font-medium text-gray-700">{t.currency}</span>
      <div className="text-right">
        <p className="text-sm text-gray-800">
          {fmtMoney(t.market_value, t.currency)}
          {!t.market_value_complete && (
            <span className="text-amber-600 text-xs ml-1">
              (subtotal — {t.market_value_missing} missing)
            </span>
          )}
        </p>
        <p className="text-xs text-gray-400">
          unrealized {fmtMoney(t.unrealized_pnl, t.currency)}
          {!t.unrealized_pnl_complete && (
            <span className="text-amber-600 ml-1">
              (subtotal — {t.unrealized_pnl_missing} missing)
            </span>
          )}
        </p>
      </div>
    </div>
  );
}

export default async function PortfolioPage() {
  const data = await getPortfolio();

  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <Link href="/" className="text-sm text-gray-400 hover:text-gray-600">
            ← Home
          </Link>
          <div className="flex items-baseline gap-3 mt-2">
            <h1 className="text-2xl font-semibold text-gray-900">Portfolio</h1>
            <span className="text-xs text-gray-400">
              Updated {fmtTime(data.generated_at)}
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-400">
            Read-only. Refresh the page to fetch the latest broker data.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <SnapshotButton />
            <Link
              href="/portfolio/history"
              className="text-sm text-gray-500 hover:text-gray-900"
            >
              History →
            </Link>
          </div>
        </div>

        {data.partial_failure && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
            Some brokers could not be reached. Figures below reflect only the brokers that
            responded successfully.
          </div>
        )}

        {data.totals_by_currency.length > 0 && (
          <section className="bg-white border border-gray-200 rounded-xl p-6">
            <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">
              Totals by currency
            </h2>
            <p className="text-xs text-gray-400 mb-3">
              Grouped per currency across connected brokers. Currencies are never added
              together.
            </p>
            {data.totals_by_currency.map((t) => (
              <TotalRow key={t.currency} t={t} />
            ))}
          </section>
        )}

        {data.brokers.map((b) => (
          <BrokerSection key={b.broker} broker={b} />
        ))}
      </div>
    </main>
  );
}
