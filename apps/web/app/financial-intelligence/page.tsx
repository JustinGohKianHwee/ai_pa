import type { CurrencyBlock, FinancialSummary } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge } from "@/components/ui";
import { fmtMoney, fmtNum } from "@/lib/format";

export const dynamic = "force-dynamic";

async function getSummary(): Promise<FinancialSummary | null> {
  try {
    const res = await authedFetch("/financial_intelligence/summary", { cache: "no-store" });
    return res.ok ? ((await res.json()) as FinancialSummary) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

function pct(v: number | null): string {
  return v === null ? "—" : `${(v * 100).toFixed(1)}%`;
}
function money(v: number | null, ccy: string): string {
  return v === null ? "—" : fmtMoney(v, ccy);
}

function Row({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <div>
        <span className="text-sm text-muted">{label}</span>
        {sub ? <span className="ml-2 text-xs text-faint">{sub}</span> : null}
      </div>
      <span className="numeric text-sm font-medium text-fg">{value}</span>
    </div>
  );
}

function CurrencyCard({ b, portfolioAsOf }: { b: CurrencyBlock; portfolioAsOf: string | null }) {
  const c = b.currency;
  const nw = b.net_worth;
  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-faint">{c}</span>
        {!nw.complete && nw.value !== null ? (
          <Badge tone="warning" dot={false}>
            partial — missing {nw.missing.join(", ")}
          </Badge>
        ) : null}
      </div>

      <p className="text-xs font-medium uppercase tracking-wider text-faint mt-3">Net worth</p>
      <p className="numeric mt-1 text-3xl font-medium text-fg">{money(nw.value, c)}</p>

      <div className="mt-4 border-t border-border pt-3">
        <Row label="Liquid cash (non-broker)" value={money(b.liquid_cash, c)} />
        <Row
          label="Invested / broker"
          value={money(b.broker_total, c)}
          sub={portfolioAsOf ? `as of ${portfolioAsOf}` : undefined}
        />
        <Row label="Liabilities" value={money(b.liabilities, c)} />
      </div>

      <div className="mt-3 border-t border-border pt-3">
        <Row label="Monthly income" value={money(b.monthly_income, c)} />
        <Row
          label="Logged monthly expenses"
          value={money(b.monthly_expenses_logged, c)}
          sub="confirmed expense records only"
        />
        <Row label="Logged savings rate" value={pct(b.savings_rate)} sub="from confirmed expenses" />
        <Row label="Investment rate" value={pct(b.investment_rate)} />
        <Row
          label="Cash runway"
          value={b.cash_runway_months === null ? "—" : `${fmtNum(b.cash_runway_months, 1)} mo`}
          sub="vs trailing-3-month logged expenses"
        />
      </div>
    </div>
  );
}

export default async function FinancialIntelligencePage() {
  const data = await getSummary();

  if (data === null) {
    return (
      <PageContainer>
        <PageHeader title="Financial Intelligence" subtitle="Couldn't load" />
        <EmptyState>
          Unavailable right now. If this persists, the database migration (0017) may not be applied
          yet.
        </EmptyState>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="Financial Intelligence"
        subtitle="Deterministic — computed only from your confirmed records and reviewed inputs"
      />

      {!data.has_manual_snapshot ? (
        <EmptyState>
          No financial snapshot yet. Send one to your Telegram bot (e.g. &ldquo;Financial snapshot:
          cash 25000 SGD, salary 8000 SGD monthly, investing 2000 SGD monthly, car loan 12000
          SGD&rdquo;), confirm it, and your net worth, savings rate, and cash runway will appear
          here. Portfolio figures come from your latest portfolio snapshot.
        </EmptyState>
      ) : data.currencies.length === 0 ? (
        <EmptyState>No financial data to summarize yet.</EmptyState>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {data.currencies.map((b) => (
            <CurrencyCard key={b.currency} b={b} portfolioAsOf={data.portfolio_as_of} />
          ))}
        </div>
      )}

      <p className="mt-6 text-xs text-faint">
        All figures are grouped by currency and never added across currencies. Portfolio values are
        as of the last snapshot{data.portfolio_partial ? " (partial — a broker was unavailable)" : ""}.
        &ldquo;Logged&rdquo; expenses reflect confirmed expense records only — not auto-pulled bank
        data. No advice; no estimated numbers.
      </p>
    </PageContainer>
  );
}
