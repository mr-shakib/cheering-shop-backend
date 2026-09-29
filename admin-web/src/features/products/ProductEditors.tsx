/* Pieces of the product form shared by Edit (drawer) and Add Product. */
import { Plus, Trash2 } from "lucide-react";

import type { AddOn, Variant } from "@/api/catalog";
import { Input } from "@/components/ui/Field";
import { cn } from "@/lib/cn";

export function VariantsEditor({ value, onChange }: { value: Variant[]; onChange: (v: Variant[]) => void }) {
  const update = (i: number, patch: Partial<Variant>) => onChange(value.map((v, j) => (j === i ? { ...v, ...patch } : v)));
  const setDefault = (i: number) => onChange(value.map((v, j) => ({ ...v, is_default: j === i })));
  return (
    <div className="space-y-2">
      {value.length === 0 && <p className="text-sm text-gray-500">No variants: customers pay the base price.</p>}
      {value.map((v, i) => (
        <div key={v.id ?? `new-${i}`} className="flex items-center gap-2">
          <Input
            aria-label="Variant name"
            value={v.name}
            onChange={(e) => update(i, { name: e.target.value })}
            placeholder="Regular"
            className="flex-1"
          />
          <Input
            aria-label="Variant price"
            type="number"
            min={0}
            step="1"
            value={Number.isNaN(v.price) ? "" : v.price}
            onChange={(e) => update(i, { price: e.target.valueAsNumber })}
            className="w-24"
            suffix={<span className="text-xs text-gray-400">৳</span>}
          />
          <button
            type="button"
            onClick={() => setDefault(i)}
            className={cn(
              "h-10 shrink-0 rounded-lg px-2.5 text-xs font-medium",
              v.is_default ? "bg-brand-50 text-brand-500" : "text-gray-500 hover:bg-gray-100",
            )}
            title="Preselected in the app"
          >
            Default
          </button>
          <button
            type="button"
            aria-label="Remove variant"
            onClick={() => onChange(value.filter((_, j) => j !== i))}
            className="flex size-9 shrink-0 items-center justify-center rounded-lg text-gray-400 hover:bg-red-50 hover:text-red-500"
          >
            <Trash2 className="size-4" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() =>
          onChange([...value, { name: "", price: NaN, is_default: value.length === 0, is_available: true, sort_order: value.length }])
        }
        className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-500 hover:underline"
      >
        <Plus className="size-4" /> Add variant
      </button>
    </div>
  );
}

export function AddOnsEditor({ value, onChange }: { value: AddOn[]; onChange: (v: AddOn[]) => void }) {
  const update = (i: number, patch: Partial<AddOn>) => onChange(value.map((v, j) => (j === i ? { ...v, ...patch } : v)));
  return (
    <div className="space-y-2">
      {value.length === 0 && <p className="text-sm text-gray-500">No add-ons.</p>}
      {value.map((a, i) => (
        <div key={a.id ?? `new-${i}`} className="flex items-center gap-2">
          <Input
            aria-label="Add-on name"
            value={a.name}
            onChange={(e) => update(i, { name: e.target.value })}
            placeholder="Extra cheese"
            className="flex-1"
          />
          <Input
            aria-label="Add-on price"
            type="number"
            min={0}
            step="1"
            value={Number.isNaN(a.price) ? "" : a.price}
            onChange={(e) => update(i, { price: e.target.valueAsNumber })}
            className="w-24"
            suffix={<span className="text-xs text-gray-400">৳</span>}
          />
          <Input
            aria-label="Most per item"
            title="Most a customer may pick per item"
            type="number"
            min={1}
            max={20}
            value={a.max_quantity}
            onChange={(e) => update(i, { max_quantity: Math.max(1, Math.min(20, e.target.valueAsNumber || 1)) })}
            className="w-16"
          />
          <button
            type="button"
            aria-label="Remove add-on"
            onClick={() => onChange(value.filter((_, j) => j !== i))}
            className="flex size-9 shrink-0 items-center justify-center rounded-lg text-gray-400 hover:bg-red-50 hover:text-red-500"
          >
            <Trash2 className="size-4" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...value, { name: "", price: NaN, is_available: true, sort_order: value.length, max_quantity: 1 }])}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-500 hover:underline"
      >
        <Plus className="size-4" /> Add add-on
      </button>
    </div>
  );
}

/** Blank rows are dropped; a row with a name but no price is an error. */
export function cleanOptions<T extends { name: string; price: number }>(rows: T[], what: string): T[] {
  const kept = rows.filter((r) => r.name.trim() || !Number.isNaN(r.price));
  for (const r of kept) {
    if (!r.name.trim()) throw new Error(`Every ${what} needs a name.`);
    if (Number.isNaN(r.price) || r.price < 0) throw new Error(`“${r.name}” needs a price.`);
  }
  return kept.map((r, i) => ({ ...r, name: r.name.trim(), sort_order: i }));
}

/** "15" in the form ↔ 0.15 in the API. Empty means "not set at this level". */
export function rateFromPercent(text: string): number | null {
  if (!text.trim()) return null;
  const n = Number(text);
  if (!Number.isFinite(n) || n < 0 || n > 100) throw new Error("Commission must be between 0 and 100%.");
  return Math.round(n * 100) / 10000;
}

export const percentFromRate = (rate: number | null | undefined) =>
  rate === null || rate === undefined ? "" : String(+(rate * 100).toFixed(2));
