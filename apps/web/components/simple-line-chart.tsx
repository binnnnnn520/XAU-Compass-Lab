import type { ChartPoint } from "../lib/view-models";

function buildPath(points: { x: number; y: number }[]) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
}

export function SimpleLineChart({
  points,
  color = "#ad7c22",
  title,
}: {
  points: ChartPoint[];
  color?: string;
  title: string;
}) {
  if (points.length === 0) {
    return (
      <div className="callout" data-tone="warning">
        {title} is unavailable because the current REST payload does not contain enough historical points yet.
      </div>
    );
  }

  const width = 640;
  const height = 240;
  const padding = 28;
  const min = Math.min(...points.map((point) => point.value));
  const max = Math.max(...points.map((point) => point.value));
  const span = max - min || 1;

  const scaled = points.map((point, index) => {
    const x = padding + (index * (width - padding * 2)) / Math.max(points.length - 1, 1);
    const y = height - padding - ((point.value - min) / span) * (height - padding * 2);
    return { ...point, x, y };
  });

  const linePath = buildPath(scaled);
  const areaPath = `${linePath} L ${scaled.at(-1)?.x ?? padding} ${height - padding} L ${padding} ${
    height - padding
  } Z`;

  return (
    <figure className="chart">
      <svg className="chart__svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        <path d={areaPath} fill={`${color}25`} />
        <path d={linePath} fill="none" stroke={color} strokeWidth="3" strokeLinejoin="round" />
        {scaled.map((point) => (
          <g key={`${point.label}-${point.value}`}>
            <circle cx={point.x} cy={point.y} r="4.5" fill={color} />
            <title>
              {point.label}: {point.displayValue}
            </title>
          </g>
        ))}
      </svg>
      <figcaption className="chart__footer">
        <span>{points.at(0)?.label}</span>
        <span>{points.at(-1)?.label}</span>
      </figcaption>
    </figure>
  );
}
