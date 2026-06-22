export function fmtNum(n: number | null | undefined, dp = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-SG", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
}

export function fmtMoney(n: number | null | undefined, ccy: string): string {
  if (n === null || n === undefined) return "—";
  return `${ccy} ${fmtNum(n)}`;
}

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Math.round(n).toLocaleString("en-SG");
}

export function fmtSignedMoney(n: number | null | undefined, ccy: string): string {
  if (n === null || n === undefined) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${ccy} ${fmtNum(n)}`;
}

export function fmtDateTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
    ...(timeZone ? { timeZone } : {}),
  });
}

export type Tone = "neutral" | "positive" | "negative" | "warning" | "info" | "accent";

export function pnlTone(n: number | null | undefined): Tone {
  if (n === null || n === undefined || n === 0) return "neutral";
  return n > 0 ? "positive" : "negative";
}
