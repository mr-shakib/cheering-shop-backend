import { useState } from "react";

import { useAssignRider, type AdminOrderDetail } from "@/api/orders";
import { useRiders } from "@/api/riders";
import { Button } from "@/components/ui/Button";
import { Avatar } from "@/components/ui/Display";
import { InlineError, Spinner } from "@/components/ui/Feedback";
import { SearchInput } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Overlay";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { useDebounced } from "@/lib/hooks";
import { vehicleLabel } from "@/lib/vocab";

/** The operator override: name a rider, or let dispatch pick the nearest. */
export function AssignRiderDialog({ order, onClose }: { order: AdminOrderDetail; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [onlineOnly, setOnlineOnly] = useState(true);
  const [picked, setPicked] = useState<string | null>(null);
  const debounced = useDebounced(q, 250);
  const riders = useRiders({ q: debounced || undefined, online_only: onlineOnly, status: "ACTIVE", limit: 50 });
  const assign = useAssignRider();
  const toast = useToast();

  const submit = (riderId: string | null) =>
    assign.mutate(
      { id: order.id, riderId },
      {
        onSuccess: (res) => {
          toast(res.message);
          onClose();
        },
      },
    );

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={order.rider ? "Reassign rider" : "Assign rider"}
      description={
        order.rider
          ? `${order.rider.full_name ?? "A rider"} is carrying this order. Choose who takes it instead.`
          : "Nobody has accepted this order yet. Choose a rider, or let the platform pick the nearest one."
      }
      footer={
        <>
          <Button variant="outline" onClick={() => submit(null)} loading={assign.isPending && picked === null} disabled={assign.isPending}>
            Let the platform pick
          </Button>
          <Button onClick={() => picked && submit(picked)} disabled={!picked || assign.isPending} loading={assign.isPending && picked !== null}>
            Assign selected rider
          </Button>
        </>
      }
    >
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput value={q} onChange={setQ} placeholder="Search name or phone" className="sm:max-w-none sm:flex-1" />
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={onlineOnly} onChange={(e) => setOnlineOnly(e.target.checked)} className="accent-brand-500" />
          On shift only
        </label>
      </div>
      <div className="scrollbar-thin mt-3 max-h-80 overflow-y-auto rounded-xl border border-line">
        {riders.isPending ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : riders.data?.items.length ? (
          riders.data.items.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setPicked(r.id)}
              className={cn(
                "flex w-full items-center gap-3 border-b border-line px-4 py-3 text-left last:border-b-0 hover:bg-gray-50",
                picked === r.id && "bg-brand-50 hover:bg-brand-50",
              )}
            >
              <Avatar src={r.avatar_url} name={r.full_name} size={40} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-gray-900">{r.full_name ?? r.phone}</span>
                <span className="block text-xs text-gray-500">
                  {vehicleLabel(r.vehicle_type)} · {r.orders_in_flight} in hand · {r.total_deliveries} delivered
                </span>
              </span>
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-xs font-medium",
                  r.live_status === "ONLINE" ? "bg-green-50 text-green-600" : "bg-orange-50 text-orange-500",
                )}
              >
                {r.live_status === "ONLINE" ? "Online" : "Offline"}
              </span>
            </button>
          ))
        ) : (
          <p className="px-4 py-8 text-center text-sm text-gray-500">
            {onlineOnly ? "No riders on shift match. Untick “On shift only” to see everyone." : "No riders match."}
          </p>
        )}
      </div>
      <div className="mt-3">
        <InlineError error={assign.error} />
      </div>
    </Modal>
  );
}
