/* Rider live tracking: every rider on shift, polled every 12 seconds. A rider
 * who has not reported a position recently is listed without a pin rather
 * than shown at a stale spot (docs/ADMIN-API.md §15). */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import L from "leaflet";
import { MapContainer, Marker, useMap } from "react-leaflet";
import { LocateOff, PhoneCall, X } from "lucide-react";

import { useLiveRiders, type LiveRider } from "@/api/riders";
import { DHAKA, Tiles, pinIcon } from "@/components/map/Map";
import { PageHeader } from "@/components/layout/Page";
import { StatusBadge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { Avatar } from "@/components/ui/Display";
import { EmptyState, ErrorState, Spinner } from "@/components/ui/Feedback";
import { Chips } from "@/components/ui/Tabs";
import { cn } from "@/lib/cn";
import { ago, orderNo } from "@/lib/format";
import { liveRiderStatus, orderStatus, vehicleLabel } from "@/lib/vocab";

import { OrderDrawer } from "../orders/OrderDrawer";

type Filter = "" | "AVAILABLE" | "DELIVERING" | "HEADING_TO_PICKUP";

const tone = (r: LiveRider) => (r.status === "AVAILABLE" ? "green" : r.status === "DELIVERING" ? "brand" : "orange");

function nearestDropoff(r: LiveRider) {
  const d = r.orders.map((o) => o.distance_to_dropoff_km).filter((x): x is number => x != null);
  return d.length ? Math.min(...d) : null;
}

/** Fit every pin once, then follow the selected rider. */
function Camera({ riders, selected }: { riders: LiveRider[]; selected: LiveRider | null }) {
  const map = useMap();
  const fitted = useRef(false);
  useEffect(() => {
    const pts = riders.filter((r) => r.has_live_location).map((r) => [r.latitude!, r.longitude!] as [number, number]);
    if (!fitted.current && pts.length) {
      fitted.current = true;
      map.fitBounds(L.latLngBounds(pts), { padding: [48, 48], maxZoom: 15 });
    }
  }, [riders, map]);
  // Keyed on the selection, not its coordinates: flying on every poll would
  // yank the map away from wherever the operator has panned.
  const target = selected?.has_live_location ? ([selected.latitude!, selected.longitude!] as [number, number]) : null;
  const targetRef = useRef(target);
  targetRef.current = target;
  useEffect(() => {
    if (targetRef.current) map.flyTo(targetRef.current, Math.max(map.getZoom(), 15), { duration: 0.6 });
  }, [selected?.id, map]);
  return null;
}

function RiderCard({ r, onClose, onOpenOrder }: { r: LiveRider; onClose: () => void; onOpenOrder: (id: string) => void }) {
  const km = nearestDropoff(r);
  return (
    <div className="absolute right-4 bottom-4 z-[500] w-[340px] max-w-[calc(100%-2rem)] animate-pop-in rounded-2xl bg-white p-4 shadow-xl">
      <div className="flex items-center gap-3">
        <Avatar src={r.avatar_url} name={r.full_name} size={40} />
        <div className="min-w-0 flex-1">
          <Link to={`/riders/${r.id}`} className="block truncate text-[15px] font-medium text-gray-900 hover:text-brand-500">
            {r.full_name ?? r.phone}
          </Link>
          <p className="truncate text-xs text-gray-500">
            {vehicleLabel(r.vehicle_type)}
            {km != null && ` · ${km.toFixed(1)} km to drop-off`}
          </p>
        </div>
        {r.phone && (
          <a href={`tel:${r.phone}`} className="inline-flex h-8 items-center gap-1.5 rounded-full border border-gray-300 px-3 text-xs font-medium text-gray-800 hover:bg-gray-50">
            <PhoneCall className="size-3.5" /> Call rider
          </a>
        )}
        <button type="button" onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-700">
          <X className="size-4" />
        </button>
      </div>
      {r.orders.length === 0 ? (
        <p className="mt-3 text-sm text-gray-500">Available — not carrying anything.</p>
      ) : (
        r.orders.map((o) => (
          <div key={o.order_id} className="mt-3 border-t border-line pt-3 text-sm">
            <button type="button" onClick={() => onOpenOrder(o.order_id)} className="font-semibold text-gray-900 hover:text-brand-500">
              Order {orderNo(o.order_number)}
            </button>
            <dl className="mt-2 grid grid-cols-[88px_1fr] gap-y-1.5">
              <dt className="text-gray-500">Customer</dt>
              <dd className="text-gray-900">{o.customer_name ?? "—"}</dd>
              <dt className="text-gray-500">Restaurant</dt>
              <dd className="text-gray-900">{o.restaurant_name}</dd>
              <dt className="text-gray-500">Distance</dt>
              <dd className="text-gray-900">{o.distance_to_dropoff_km != null ? `${o.distance_to_dropoff_km.toFixed(1)} km away` : "Unknown"}</dd>
              <dt className="text-gray-500">Status</dt>
              <dd>
                <StatusBadge {...orderStatus(o.status)} />
              </dd>
            </dl>
          </div>
        ))
      )}
      {r.location_updated_at && <p className="mt-3 text-[11px] text-gray-400">Position from {ago(r.location_updated_at)}</p>}
    </div>
  );
}

export function LiveTrackingPage() {
  const [filter, setFilter] = useState<Filter>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [openOrder, setOpenOrder] = useState<string | null>(null);
  const live = useLiveRiders(filter);
  const riders = useMemo(() => live.data ?? [], [live.data]);
  const selected = riders.find((r) => r.id === selectedId) ?? null;
  const onMap = riders.filter((r) => r.has_live_location);

  return (
    <>
      <PageHeader title="Rider live tracking" subtitle={`${riders.length} rider${riders.length === 1 ? "" : "s"} on shift · ${onMap.length} reporting a position`} />
      <div className="grid gap-5 lg:h-[calc(100vh-13.5rem)] lg:min-h-[560px] lg:grid-cols-[370px_minmax(0,1fr)]">
        <Card className="flex min-h-0 flex-col p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">Riders ({riders.length})</h2>
            {live.isFetching && <Spinner className="size-4" />}
          </div>
          <Chips
            className="mt-4"
            items={[
              { key: "" as Filter, label: "All" },
              { key: "AVAILABLE" as Filter, label: "Available" },
              { key: "DELIVERING" as Filter, label: "Delivering" },
              { key: "HEADING_TO_PICKUP" as Filter, label: "Heading to pickup" },
            ]}
            active={filter}
            onChange={setFilter}
          />
          <div className="scrollbar-thin -mx-2 mt-3 min-h-0 flex-1 overflow-y-auto px-2">
            {live.isPending ? (
              <div className="flex justify-center py-8">
                <Spinner />
              </div>
            ) : live.isError ? (
              <ErrorState error={live.error} onRetry={() => live.refetch()} />
            ) : riders.length === 0 ? (
              <EmptyState>No riders are on shift{filter ? " with this status" : ""}.</EmptyState>
            ) : (
              riders.map((r) => {
                const km = nearestDropoff(r);
                return (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => setSelectedId(r.id)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left hover:bg-gray-50",
                      selectedId === r.id && "bg-gray-100 hover:bg-gray-100",
                    )}
                  >
                    <Avatar src={r.avatar_url} name={r.full_name} size={40} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px] text-gray-900">{r.full_name ?? r.phone}</span>
                      <span className="flex items-center gap-1.5 text-xs text-gray-500">
                        <StatusBadge {...liveRiderStatus(r.status)} className="px-2 py-0 text-[11px]" />
                        {!r.has_live_location && (
                          <span className="inline-flex items-center gap-1" title="No recent position">
                            <LocateOff className="size-3" /> no GPS
                          </span>
                        )}
                      </span>
                    </span>
                    {km != null && <span className="shrink-0 text-xs text-gray-600">{km.toFixed(1)} Km</span>}
                  </button>
                );
              })
            )}
          </div>
        </Card>

        <Card className="relative min-h-[480px] overflow-hidden">
          <MapContainer center={DHAKA} zoom={12} className="absolute inset-0 size-full">
            <Tiles />
            <Camera riders={riders} selected={selected} />
            {onMap.map((r) => (
              <Marker
                key={r.id}
                position={[r.latitude!, r.longitude!]}
                icon={pinIcon(tone(r), r.id === selectedId)}
                eventHandlers={{ click: () => setSelectedId(r.id) }}
                title={r.full_name ?? undefined}
              />
            ))}
          </MapContainer>
          {selected && <RiderCard r={selected} onClose={() => setSelectedId(null)} onOpenOrder={setOpenOrder} />}
          <div className="pointer-events-none absolute top-4 left-14 z-[500] flex gap-3 rounded-full bg-white/90 px-3 py-1.5 text-xs text-gray-700 shadow">
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full bg-green-600" /> Available
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full bg-orange-500" /> To pickup
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full bg-brand-500" /> Delivering
            </span>
          </div>
        </Card>
      </div>
      <OrderDrawer orderId={openOrder} onClose={() => setOpenOrder(null)} />
    </>
  );
}
