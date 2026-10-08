"use client";

import { useState } from "react";
import { compact, money } from "./lib";
import { COLORS } from "./ui";

const W = 820;
const H = 280;
const M = { left: 62, right: 16, top: 14, bottom: 30 };
const PLOT_W = W - M.left - M.right;
const PLOT_H = H - M.top - M.bottom;

/** Centre x of band i when the plot is split into n equal bands. */
const bandX = (i: number, n: number) => M.left + ((i + 0.5) * PLOT_W) / Math.max(n, 1);

function niceTicks(min: number, max: number, count = 5): number[] {
  if (min === max) max = min + 1;
  const rough = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(Math.round(v / step) * step);
  return ticks;
}

function useHover(count: number) {
  const [index, setIndex] = useState<number | null>(null);
  const handle = (box: DOMRect, clientX: number) => {
    if (count === 0 || box.width === 0) return;
    const x = ((clientX - box.left) / box.width) * W;
    const i = Math.floor(((x - M.left) / PLOT_W) * count);
    setIndex(Math.min(count - 1, Math.max(0, i)));
  };
  return {
    index,
    props: {
      onMouseMove: (e: React.MouseEvent<HTMLDivElement>) => handle(e.currentTarget.getBoundingClientRect(), e.clientX),
      onTouchMove: (e: React.TouchEvent<HTMLDivElement>) => handle(e.currentTarget.getBoundingClientRect(), e.touches[0].clientX),
      onMouseLeave: () => setIndex(null),
    },
  };
}

function Tooltip({
  index,
  count,
  title,
  rows,
  fmt = money,
}: {
  index: number;
  count: number;
  title: string;
  rows: { name: string; color: string; value: number }[];
  fmt?: (v: number) => string;
}) {
  const leftPct = (bandX(index, count) / W) * 100;
  const flip = index > count * 0.6;
  return (
    <div
      className="pointer-events-none absolute top-2 z-10 min-w-[170px] rounded-lg border border-[#374151] bg-[#0b0b0f]/95 px-3 py-2 text-xs shadow-lg"
      style={{ left: `${leftPct}%`, transform: `translateX(${flip ? "calc(-100% - 12px)" : "12px"})` }}
    >
      <div className="mb-1 font-semibold text-[#e5e7eb]">{title}</div>
      {rows.map((row) => (
        <div key={row.name} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-[#9ca3af]">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: row.color }} />
            {row.name}
          </span>
          <span className="tabular-nums" style={{ color: row.value < 0 ? COLORS.red : COLORS.text }}>
            {fmt(row.value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function XLabels({ labels }: { labels: string[] }) {
  const every = Math.max(1, Math.ceil(labels.length / 8));
  return (
    <>
      {labels.map((label, i) =>
        i % every === 0 ? (
          <text key={i} x={bandX(i, labels.length)} y={H - 8} textAnchor="middle" fontSize="11" fill={COLORS.faint}>
            {label}
          </text>
        ) : null
      )}
    </>
  );
}

function YAxis({ ticks, y, fmt = compact }: { ticks: number[]; y: (v: number) => number; fmt?: (v: number) => string }) {
  return (
    <>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? COLORS.borderStrong : COLORS.border} strokeWidth={t === 0 ? 1.2 : 1} />
          <text x={M.left - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill={COLORS.faint}>
            {fmt(t)}
          </text>
        </g>
      ))}
    </>
  );
}

export type LineSeries = {
  name: string;
  color: string;
  values: number[];
  dashed?: boolean;
  width?: number;
};

export function LineChart({
  labels,
  series,
  reference,
  ariaLabel,
  axisFormat,
  valueFormat,
  includeZero = true,
}: {
  labels: string[];
  series: LineSeries[];
  reference?: { value: number; label: string };
  ariaLabel: string;
  /** Y-axis tick label, default compact dollars. */
  axisFormat?: (v: number) => string;
  /** Tooltip value, default whole dollars. */
  valueFormat?: (v: number) => string;
  includeZero?: boolean;
}) {
  const hover = useHover(labels.length);
  const all = series.flatMap((s) => s.values).concat(reference ? [reference.value] : [], includeZero ? [0] : []);
  const ticks = niceTicks(Math.min(...all), Math.max(...all));
  const lo = ticks[0];
  const hi = ticks[ticks.length - 1];
  const y = (v: number) => M.top + PLOT_H - ((v - lo) / (hi - lo || 1)) * PLOT_H;
  const x = (i: number) => bandX(i, labels.length);

  return (
    <div className="relative" {...hover.props}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label={ariaLabel}>
        <YAxis ticks={ticks} y={y} fmt={axisFormat} />
        {reference && (
          <g>
            <line x1={M.left} x2={W - M.right} y1={y(reference.value)} y2={y(reference.value)} stroke={COLORS.amber} strokeDasharray="5 4" strokeWidth={1.4} />
            <text x={W - M.right - 4} y={y(reference.value) - 5} textAnchor="end" fontSize="11" fill={COLORS.amber}>
              {reference.label}
            </text>
          </g>
        )}
        {series.map((s) => (
          <path
            key={s.name}
            d={s.values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")}
            fill="none"
            stroke={s.color}
            strokeWidth={s.width ?? 2}
            strokeDasharray={s.dashed ? "6 4" : undefined}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
        {hover.index !== null && (
          <g>
            <line x1={x(hover.index)} x2={x(hover.index)} y1={M.top} y2={M.top + PLOT_H} stroke={COLORS.faint} strokeDasharray="3 3" />
            {series.map((s) => (
              <circle key={s.name} cx={x(hover.index!)} cy={y(s.values[hover.index!])} r={4} fill={s.color} stroke={COLORS.bg} strokeWidth={1.5} />
            ))}
          </g>
        )}
        <XLabels labels={labels} />
      </svg>
      {hover.index !== null && (
        <Tooltip
          index={hover.index}
          count={labels.length}
          title={labels[hover.index]}
          rows={series.map((s) => ({ name: s.name, color: s.color, value: s.values[hover.index!] }))}
          fmt={valueFormat}
        />
      )}
    </div>
  );
}

export function FlowChart({
  labels,
  inflows,
  outflows,
  net,
  ariaLabel,
}: {
  labels: string[];
  inflows: number[];
  outflows: number[];
  net: number[];
  ariaLabel: string;
}) {
  const hover = useHover(labels.length);
  const all = [...inflows, ...outflows, ...net, 0];
  const ticks = niceTicks(Math.min(...all), Math.max(...all));
  const lo = ticks[0];
  const hi = ticks[ticks.length - 1];
  const y = (v: number) => M.top + PLOT_H - ((v - lo) / (hi - lo || 1)) * PLOT_H;
  const band = PLOT_W / Math.max(labels.length, 1);
  const x = (i: number) => bandX(i, labels.length);
  const barW = Math.max(4, Math.min(22, band * 0.32));

  return (
    <div className="relative" {...hover.props}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label={ariaLabel}>
        <YAxis ticks={ticks} y={y} />
        {labels.map((_, i) => (
          <g key={i}>
            <rect x={x(i) - barW - 1} y={y(inflows[i])} width={barW} height={Math.max(0, y(0) - y(inflows[i]))} fill={COLORS.green} opacity={hover.index === null || hover.index === i ? 0.9 : 0.45} rx={2} />
            <rect x={x(i) + 1} y={y(outflows[i])} width={barW} height={Math.max(0, y(0) - y(outflows[i]))} fill={COLORS.red} opacity={hover.index === null || hover.index === i ? 0.9 : 0.45} rx={2} />
          </g>
        ))}
        <path
          d={net.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")}
          fill="none"
          stroke={COLORS.blue}
          strokeWidth={2}
          strokeLinejoin="round"
        />
        {net.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r={3} fill={COLORS.blue} stroke={COLORS.bg} strokeWidth={1} />
        ))}
        <XLabels labels={labels} />
      </svg>
      {hover.index !== null && (
        <Tooltip
          index={hover.index}
          count={labels.length}
          title={labels[hover.index]}
          rows={[
            { name: "Cash in", color: COLORS.green, value: inflows[hover.index] },
            { name: "Cash out", color: COLORS.red, value: -outflows[hover.index] },
            { name: "Net", color: COLORS.blue, value: net[hover.index] },
          ]}
        />
      )}
    </div>
  );
}

export function Legend({ items }: { items: { name: string; color: string; dashed?: boolean }[] }) {
  return (
    <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#9ca3af]">
      {items.map((item) => (
        <span key={item.name} className="flex items-center gap-1.5">
          <span
            className="inline-block h-0.5 w-5"
            style={{
              background: item.dashed
                ? `repeating-linear-gradient(90deg, ${item.color} 0 5px, transparent 5px 8px)`
                : item.color,
              height: item.dashed ? 2 : 3,
            }}
          />
          {item.name}
        </span>
      ))}
    </div>
  );
}

export type BarSeries = { name: string; color: string; values: number[] };

/** Stacked columns for non-negative amounts (one column per period). */
export function StackedBars({
  labels,
  series,
  ariaLabel,
}: {
  labels: string[];
  series: BarSeries[];
  ariaLabel: string;
}) {
  const hover = useHover(labels.length);
  const totals = labels.map((_, i) => series.reduce((sum, s) => sum + (s.values[i] || 0), 0));
  const ticks = niceTicks(0, Math.max(...totals, 1));
  const lo = ticks[0];
  const hi = ticks[ticks.length - 1];
  const y = (v: number) => M.top + PLOT_H - ((v - lo) / (hi - lo || 1)) * PLOT_H;
  const band = PLOT_W / Math.max(labels.length, 1);
  const barW = Math.max(6, Math.min(40, band * 0.62));
  const x = (i: number) => bandX(i, labels.length);

  return (
    <div className="relative" {...hover.props}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label={ariaLabel}>
        <YAxis ticks={ticks} y={y} />
        {labels.map((_, i) => {
          let base = 0;
          return (
            <g key={i} opacity={hover.index === null || hover.index === i ? 1 : 0.5}>
              {series.map((s) => {
                const v = s.values[i] || 0;
                const top = y(base + v);
                const rect = <rect key={s.name} x={x(i) - barW / 2} y={top} width={barW} height={Math.max(0, y(base) - top)} fill={s.color} />;
                base += v;
                return rect;
              })}
            </g>
          );
        })}
        <XLabels labels={labels} />
      </svg>
      {hover.index !== null && (
        <Tooltip
          index={hover.index}
          count={labels.length}
          title={labels[hover.index]}
          rows={[
            ...series.map((s) => ({ name: s.name, color: s.color, value: s.values[hover.index!] || 0 })),
            ...(series.length > 1 ? [{ name: "Total", color: COLORS.muted, value: totals[hover.index] }] : []),
          ]}
        />
      )}
    </div>
  );
}

/** Tiny inline trend line for cards. */
export function Sparkline({ values, color = COLORS.blue, label }: { values: number[]; color?: string; label: string }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const w = 120;
  const h = 32;
  const pts = values
    .map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - 3 - ((v - min) / (max - min || 1)) * (h - 6)).toFixed(1)}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-8 w-full" role="img" aria-label={label} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
