export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-SG", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function fmtMoney(n: number | null | undefined, currency: string): string {
  if (n === null || n === undefined) return "—";
  return `${currency} ${fmtNum(n)}`;
}
