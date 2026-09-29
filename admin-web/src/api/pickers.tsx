/* Option loaders for the searchable pickers (components/ui/Inputs Picker). */
import { Avatar } from "@/components/ui/Display";
import type { PickerOption } from "@/components/ui/Inputs";
import { apiPage, get } from "@/lib/api";

import type { AdminCategory, AdminProductRow } from "./catalog";
import type { AdminVendorRow } from "./vendors";

/** Browse categories by id. Hidden and pending ones are included: an admin
 * may file a product under a chip before approving it. */
export async function loadCategoryOptions(q: string): Promise<PickerOption[]> {
  const rows = await get<AdminCategory[]>("/admin/categories", { q: q || undefined, limit: 30, sort: "name" });
  return rows.map((c) => ({
    value: c.id,
    label: c.name,
    sub: [c.kind === "STORE" ? "Store" : "Restaurant", !c.is_active ? "hidden" : null, c.is_pending ? "needs review" : null]
      .filter(Boolean)
      .join(" · "),
  }));
}

/** Browse categories by slug: what a banner's CATEGORY action opens. */
export async function loadCategorySlugOptions(q: string): Promise<PickerOption[]> {
  const rows = await get<AdminCategory[]>("/admin/categories", { q: q || undefined, limit: 30, sort: "name" });
  return rows.map((c) => ({ value: c.slug, label: c.name, sub: c.is_active ? c.slug : `${c.slug} · hidden` }));
}

export async function loadRestaurantOptions(q: string): Promise<PickerOption[]> {
  const page = await apiPage<AdminVendorRow>("/admin/vendors", { q: q || undefined, status: "ALL", limit: 30 });
  return page.items.map((v) => ({ value: v.id, label: v.name, sub: v.is_verified ? undefined : "Not approved" }));
}

export async function loadProductOptions(q: string, restaurantId?: string): Promise<PickerOption[]> {
  const page = await apiPage<AdminProductRow>("/admin/products", { q: q || undefined, restaurant_id: restaurantId, limit: 30 });
  return page.items.map((p) => ({
    value: p.id,
    label: p.name,
    sub: restaurantId ? undefined : `${p.restaurant_name} · now in ${p.platform_category?.name ?? p.section_name}`,
    icon: <Avatar src={p.image_url} name={p.name} size={24} rounded="lg" />,
  }));
}
