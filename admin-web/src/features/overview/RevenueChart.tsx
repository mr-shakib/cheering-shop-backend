import { useId, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useRevenue, type RevenueRange } from "@/api/insights";
import { Card } from "@/components/ui/Card";
import { ErrorState, Spinner } from "@/components/ui/Feedback";
import { Segmented } from "@/components/ui/Tabs";
import { compact, count, money } from "@/lib/format";

const RANGES: { key: RevenueRange; label: string }[] = [
  { key: "7d", label: "7 day" },
  { key: "30d", label: "30 day" },
  { key: "12m", label: "12 Month" },
];

interface TipProps {
  active?: boolean;
  payload?: { payload: { label: string; gmv: number; orders: number } }[];
}

function ChartTip({ active, payload }: TipProps) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 text-xs shadow-lg">
      <p className="font-medium text-gray-900">{p.label}</p>
      <p className="mt-1 text-gray-600">
        Revenue <span className="font-semibold text-gray-900">{money(p.gmv)}</span>
      </p>
      <p className="text-gray-600">
        Delivered orders <span className="font-semibold text-gray-900">{count(p.orders)}</span>
      </p>
    </div>
  );
}

/** Revenue overview — GMV of delivered orders, shared by Overview and Finance. */
export function RevenueChart({ className }: { className?: string }) {
  const [range, setRange] = useState<RevenueRange>("7d");
  const revenue = useRevenue(range);
  const gradientId = useId().replace(/:/g, "");
  const points = revenue.data?.points ?? [];

  return (
    <Card className={className}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Revenue overview</h2>
          {revenue.data && (
            <p className="mt-0.5 text-xs text-gray-500">{money(revenue.data.total_gmv)} from delivered orders</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {revenue.isFetching && <Spinner className="size-4" />}
          <Segmented items={RANGES} active={range} onChange={setRange} />
        </div>
      </div>
      <div className="h-[250px] px-2 pt-4 pb-3">
        {revenue.isError ? (
          <ErrorState error={revenue.error} onRetry={() => revenue.refetch()} className="py-8" />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#e3146e" stopOpacity={0.38} />
                  <stop offset="100%" stopColor="#e3146e" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="#eef1f5" />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11, fill: "#64748b" }}
                interval="preserveStartEnd"
                minTickGap={12}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={44}
                tick={{ fontSize: 11, fill: "#64748b" }}
                tickFormatter={(v: number) => compact(v)}
                allowDecimals={false}
              />
              <Tooltip content={<ChartTip />} cursor={{ stroke: "#fbc9df" }} />
              <Area
                type="monotone"
                dataKey="gmv"
                stroke="#e3146e"
                strokeWidth={2}
                fill={`url(#${gradientId})`}
                activeDot={{ r: 4, fill: "#e3146e", stroke: "#fff", strokeWidth: 2 }}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  );
}
