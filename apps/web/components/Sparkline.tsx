// Lightweight inline sparkline — no chart library. Trend-coloured (green up, red
// down). Decorative, so hidden from assistive tech (the numbers carry the meaning).
export function Sparkline({
  values,
  width = 128,
  height = 36,
  className = "",
}: {
  values: number[];
  width?: number;
  height?: number;
  className?: string;
}) {
  if (!values || values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = width / (values.length - 1);
  const pad = 2;
  const usable = height - pad * 2;

  const points = values
    .map((v, i) => {
      const x = i * step;
      const y = pad + (usable - ((v - min) / range) * usable);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const up = values[values.length - 1] >= values[0];

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      preserveAspectRatio="none"
      aria-hidden
      role="img"
    >
      <polyline
        points={points}
        fill="none"
        stroke={up ? "var(--positive)" : "var(--negative)"}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
