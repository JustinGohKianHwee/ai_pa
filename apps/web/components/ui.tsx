import type { ReactNode } from "react";
import Link from "next/link";
import type { Tone } from "@/lib/format";

export function PageContainer({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`mx-auto w-full max-w-5xl px-5 py-8 sm:px-8 ${className}`}>
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-medium tracking-tight text-fg">{title}</h1>
        {subtitle ? <div className="mt-1 text-sm text-muted">{subtitle}</div> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-border bg-surface ${className}`}>
      {children}
    </div>
  );
}

export function Tile({
  title,
  action,
  href,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  href?: string;
  children: ReactNode;
  className?: string;
}) {
  const header =
    title || action ? (
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        {title ? <h2 className="text-sm font-medium text-fg">{title}</h2> : <span />}
        {action ? <div className="text-xs text-muted">{action}</div> : null}
      </div>
    ) : null;

  const body = (
    <>
      {header}
      <div className="p-4">{children}</div>
    </>
  );

  const base = "block rounded-xl border border-border bg-surface";
  if (href) {
    return (
      <Link
        href={href}
        className={`${base} transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${className}`}
      >
        {body}
      </Link>
    );
  }
  return <section className={`${base} ${className}`}>{body}</section>;
}

const toneText: Record<Tone, string> = {
  neutral: "text-muted",
  positive: "text-positive",
  negative: "text-negative",
  warning: "text-warning",
  info: "text-info",
  accent: "text-accent",
};

const toneDot: Record<Tone, string> = {
  neutral: "bg-faint",
  positive: "bg-positive",
  negative: "bg-negative",
  warning: "bg-warning",
  info: "bg-info",
  accent: "bg-accent",
};

export function Badge({
  children,
  tone = "neutral",
  dot = true,
}: {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-raised px-2 py-0.5 text-xs font-medium ${toneText[tone]}`}
    >
      {dot ? <span className={`h-1.5 w-1.5 rounded-full ${toneDot[tone]}`} aria-hidden /> : null}
      {children}
    </span>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-faint">
      {children}
    </h2>
  );
}

export function MetricTile({
  label,
  value,
  sub,
  tone = "neutral",
  href,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  href?: string;
}) {
  const inner = (
    <>
      <p className="text-xs font-medium text-faint">{label}</p>
      <p className="numeric mt-2 text-2xl font-medium text-fg">{value}</p>
      {sub ? <p className={`numeric mt-1 text-xs ${toneText[tone]}`}>{sub}</p> : null}
    </>
  );
  const base = "block rounded-xl border border-border bg-surface p-4";
  if (href) {
    return (
      <Link
        href={href}
        className={`${base} transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent`}
      >
        {inner}
      </Link>
    );
  }
  return <div className={base}>{inner}</div>;
}

export function BentoGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface p-10 text-center text-sm text-muted">
      {children}
    </div>
  );
}
