import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** Small hand-drawn SVG charts for the dashboard: thin marks, hairline grid, a tooltip on hover. */

export interface Series {
  key: string;
  label: string;
  color: string; // a CSS colour, normally var(--series-N)
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    setWidth(Math.floor(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export function dayLabel(iso: string, long = false): string {
  return new Date(`${iso}T12:00:00+07:00`).toLocaleDateString("th-TH", {
    timeZone: "Asia/Bangkok",
    day: "numeric",
    month: "short",
    ...(long ? { weekday: "short" } : {}),
  });
}

/** Every n-th label so the axis never crowds: about one label per 56px. */
function labelEvery(count: number, width: number): number {
  return Math.max(1, Math.ceil(count / Math.max(1, Math.floor(width / 56))));
}

function niceMax(value: number): number {
  if (value <= 4) return 4;
  const step = 10 ** Math.floor(Math.log10(value));
  const nice = [1, 2, 2.5, 5, 10].map((m) => m * step).find((m) => m * 4 >= value) ?? value;
  return nice * 4;
}

/** A column with a 4px rounded data end and a square foot. */
function column(x: number, y: number, w: number, h: number, round: boolean): string {
  const r = round ? Math.min(4, w / 2, h) : 0;
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

export function Legend({ series }: { series: Series[] }) {
  return (
    <ul className="legend">
      {series.map((s) => (
        <li key={s.key}>
          <span className="legend-key" style={{ background: s.color }} />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

/** Beside the hovered mark, inside the chart (the card clips anything outside it). */
function Tip({ x, width, children }: { x: number; width: number; children: ReactNode }) {
  const side = x > width / 2 ? { right: width - x + 14 } : { left: x + 14 };
  return (
    <div className="chart-tip" style={side} role="status">
      {children}
    </div>
  );
}

const PAD = { top: 12, right: 8, bottom: 26, left: 36 };

/** Calls per day, stacked by how the call went. */
export function StackedColumns({
  rows,
  series,
  height = 220,
  ariaLabel,
}: {
  rows: ({ date: string } & Record<string, number | string>)[];
  series: Series[];
  height?: number;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const totals = rows.map((r) => series.reduce((sum, s) => sum + Number(r[s.key] ?? 0), 0));
  const max = niceMax(Math.max(1, ...totals));
  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = height - PAD.top - PAD.bottom;
  const band = rows.length ? plotW / rows.length : 0;
  const barW = Math.max(2, Math.min(24, band * 0.64));
  const y = (v: number) => PAD.top + plotH - (v / max) * plotH;
  const every = labelEvery(rows.length, plotW);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => Math.round(t * max));

  return (
    <div className="chart" ref={ref} onPointerLeave={() => setHover(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="grid" x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} />
              <text className="axis" x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end">
                {t.toLocaleString("th-TH")}
              </text>
            </g>
          ))}
          {rows.map((r, i) => {
            const cx = PAD.left + band * i + band / 2;
            let base = 0;
            const parts = series.filter((s) => Number(r[s.key] ?? 0) > 0);
            return (
              <g key={r.date}>
                {hover === i && <rect className="hover-band" x={cx - band / 2} y={PAD.top} width={band} height={plotH} />}
                {parts.map((s, k) => {
                  const v = Number(r[s.key]);
                  const top = y(base + v);
                  const bottom = y(base);
                  base += v;
                  const h = Math.max(0, bottom - top - (k > 0 ? 2 : 0)); // a 2px surface gap between parts
                  return <path key={s.key} d={column(cx - barW / 2, top, barW, h, k === parts.length - 1)} fill={s.color} />;
                })}
                {i % every === 0 && (
                  <text className="axis" x={cx} y={height - 8} textAnchor="middle">
                    {dayLabel(r.date)}
                  </text>
                )}
                <rect
                  x={cx - band / 2}
                  y={PAD.top}
                  width={band}
                  height={plotH}
                  fill="transparent"
                  onPointerEnter={() => setHover(i)}
                />
              </g>
            );
          })}
        </svg>
      )}
      {hover !== null && rows[hover] && (
        <Tip x={PAD.left + band * hover + band / 2} width={width}>
          <strong>{dayLabel(rows[hover].date, true)}</strong>
          {series.map((s) => (
            <span key={s.key} className="tip-row">
              <span className="legend-key" style={{ background: s.color }} />
              {s.label}
              <b className="num">{Number(rows[hover][s.key] ?? 0).toLocaleString("th-TH")}</b>
            </span>
          ))}
          <span className="tip-row tip-total">
            รวม<b className="num">{totals[hover].toLocaleString("th-TH")}</b>
          </span>
        </Tip>
      )}
    </div>
  );
}

/** One line over days on a fixed scale (the accumulated 1-5 score); days without a value leave a gap. */
export function LineOverDays({
  points,
  min,
  max,
  color,
  height = 220,
  ariaLabel,
  format,
  tip,
}: {
  points: { date: string; value: number | null }[];
  min: number;
  max: number;
  color: string;
  height?: number;
  ariaLabel: string;
  format: (v: number) => string;
  tip: (i: number) => ReactNode;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = height - PAD.top - PAD.bottom;
  const step = points.length > 1 ? plotW / (points.length - 1) : 0;
  const x = (i: number) => PAD.left + (points.length > 1 ? step * i : plotW / 2);
  const y = (v: number) => PAD.top + plotH - ((v - min) / (max - min)) * plotH;
  const every = labelEvery(points.length, plotW);
  const ticks = Array.from({ length: max - min + 1 }, (_, i) => min + i);

  let d = "";
  points.forEach((p, i) => {
    if (p.value === null) return;
    d += `${d && points[i - 1]?.value !== null ? "L" : "M"}${x(i)},${y(p.value)}`;
  });
  const last = points.reduce<number | null>((found, p, i) => (p.value !== null ? i : found), null);

  return (
    <div
      className="chart"
      ref={ref}
      onPointerLeave={() => setHover(null)}
      onPointerMove={(e) => {
        if (!points.length) return;
        const box = e.currentTarget.getBoundingClientRect();
        const i = Math.round((e.clientX - box.left - PAD.left) / (step || 1));
        setHover(Math.min(points.length - 1, Math.max(0, i)));
      }}
    >
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="grid" x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} />
              <text className="axis" x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end">
                {t}
              </text>
            </g>
          ))}
          {points.map((p, i) =>
            i % every === 0 ? (
              <text key={p.date} className="axis" x={x(i)} y={height - 8} textAnchor="middle">
                {dayLabel(p.date)}
              </text>
            ) : null,
          )}
          {hover !== null && <line className="crosshair" x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} />}
          <path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {last !== null && points[last].value !== null && (
            <>
              <circle className="dot" cx={x(last)} cy={y(points[last].value)} r={4.5} fill={color} />
              <text className="end-label" x={x(last) - 8} y={y(points[last].value) - 12} textAnchor="end">
                {format(points[last].value)}
              </text>
            </>
          )}
          {hover !== null && points[hover].value !== null && (
            <circle className="dot" cx={x(hover)} cy={y(points[hover].value)} r={5} fill={color} />
          )}
        </svg>
      )}
      {hover !== null && (
        <Tip x={x(hover)} width={width}>
          {tip(hover)}
        </Tip>
      )}
    </div>
  );
}

/** Horizontal bars in plain HTML: a label, a thin bar and its value. */
export function BarList({
  rows,
  color,
  onSelect,
  selected,
  stacked,
}: {
  rows: { key: string; label: ReactNode; value: number; share: number; display: string; title?: string }[];
  color: string;
  onSelect?: (key: string) => void;
  selected?: string | null;
  /** The label on its own line above the bar, for long labels in a narrow card. */
  stacked?: boolean;
}) {
  return (
    <ul className={`bar-list${stacked ? " stacked" : ""}`}>
      {rows.map((r) => {
        const body = (
          <>
            <span className="bar-label">{r.label}</span>
            <span className="bar-track">
              <span className="bar-fill" style={{ width: `${Math.max(r.share > 0 ? 1.5 : 0, r.share * 100)}%`, background: color }} />
            </span>
            <span className="bar-value num">{r.display}</span>
          </>
        );
        return (
          <li key={r.key} title={r.title}>
            {onSelect ? (
              <button type="button" className="bar-row" aria-pressed={selected === r.key} onClick={() => onSelect(r.key)}>
                {body}
              </button>
            ) : (
              <div className="bar-row">{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
