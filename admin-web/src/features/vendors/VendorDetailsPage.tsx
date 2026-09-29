import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { BadgeCheck, EyeOff, MoreVertical, Pencil, Percent, PhoneCall, ShieldOff, Store } from "lucide-react";

import { useSetVendorCommission, useUpdateVendor, useVendor, useVerifyRestaurant, type AdminVendorDetail } from "@/api/vendors";
import { PageHeader } from "@/components/layout/Page";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Avatar, Rating } from "@/components/ui/Display";
import { ErrorState, InlineError, PageSpinner } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Overlay";
import { Popover } from "@/components/ui/Popover";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/lib/api";
import { dateOnly, pct } from "@/lib/format";

import { percentFromRate, rateFromPercent } from "../products/ProductEditors";
import { VendorOrdersTab } from "./VendorOrdersTab";
import { VendorProductsTab } from "./VendorProductsTab";
import { VendorReviewsTab } from "./VendorReviewsTab";
import { VendorStoreInfo } from "./VendorStoreInfo";
import { VendorWithdrawalTab } from "./VendorWithdrawalTab";

type Tab = "store" | "products" | "orders" | "reviews" | "withdrawal";

const TABS: { key: Tab; label: string }[] = [
  { key: "store", label: "Store Info" },
  { key: "products", label: "Products" },
  { key: "orders", label: "Order" },
  { key: "reviews", label: "Review" },
  { key: "withdrawal", label: "Withdrawal" },
];

function CommissionDialog({ vendor, onClose }: { vendor: AdminVendorDetail; onClose: () => void }) {
  const [value, setValue] = useState(percentFromRate(vendor.commission_rate));
  const [error, setError] = useState<unknown>(null);
  const save = useSetVendorCommission();
  const toast = useToast();
  return (
    <Modal
      open
      onClose={onClose}
      title="Vendor commission"
      description="What the platform keeps of each order's item total. It applies to new orders only; a product's or category's own rate still wins over it."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={save.isPending}
            onClick={async () => {
              setError(null);
              try {
                const rate = rateFromPercent(value);
                if (rate === null) throw new Error("Enter a rate.");
                const res = await save.mutateAsync({ id: vendor.id, rate });
                toast(res.message);
                onClose();
              } catch (e) {
                setError(e);
              }
            }}
          >
            Save rate
          </Button>
        </>
      }
    >
      <Field label="Commission (%)">
        {(id) => <Input id={id} type="number" min={0} max={100} step="0.5" value={value} onChange={(e) => setValue(e.target.value)} autoFocus />}
      </Field>
      <div className="mt-3">
        <InlineError error={error} />
      </div>
    </Modal>
  );
}

function VendorHeader({ v }: { v: AdminVendorDetail }) {
  const verify = useVerifyRestaurant();
  const update = useUpdateVendor();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [commissionOpen, setCommissionOpen] = useState(false);

  return (
    <Card className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center">
      {v.logo_url || v.cover_image_url ? (
        <Avatar src={v.logo_url ?? v.cover_image_url} name={v.name} size={108} rounded="lg" />
      ) : (
        <span className="flex size-27 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-500">
          <Store className="size-10" />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-2xl font-semibold text-gray-900">{v.name}</h2>
          {!v.is_verified ? (
            <Badge tone="red">Not approved</Badge>
          ) : (
            <Badge tone={v.status === "OPEN" ? "green" : "gray"} dot>
              {v.status === "OPEN" ? "Open" : "Closed"}
            </Badge>
          )}
          {!v.is_active && <Badge tone="orange">Hidden from discovery</Badge>}
        </div>
        {v.cuisine_types.length > 0 && <p className="mt-1 text-sm text-gray-500">{v.cuisine_types.join(" · ")}</p>}
        <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-600">
          <Rating value={v.rating_avg} className="text-sm" />
          <span>({v.rating_count} review{v.rating_count === 1 ? "" : "s"})</span>
          <span aria-hidden>·</span>
          <span>Member since {dateOnly(v.created_at)}</span>
          <span aria-hidden>·</span>
          <button type="button" onClick={() => setCommissionOpen(true)} className="font-medium text-gray-800 hover:text-brand-500">
            {pct(v.commission_rate)} commission
          </button>
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {v.phone || v.owner.phone ? (
          <a
            href={`tel:${v.phone || v.owner.phone}`}
            className="inline-flex h-12 items-center gap-2 rounded-full bg-brand-500 px-6 text-base font-medium text-white hover:bg-brand-600"
          >
            <PhoneCall className="size-5" /> Contact Vendor
          </a>
        ) : null}
        <Link to={`/vendors/${v.id}/edit`}>
          <Button variant="outline" size="lg" icon={<Pencil className="size-4" />} className="h-12">
            Edit
          </Button>
        </Link>
        <Popover
          align="right"
          panelClassName="w-60 p-1.5"
          trigger={({ toggle }) => (
            <button
              type="button"
              onClick={toggle}
              aria-label="More actions"
              className="flex size-12 items-center justify-center rounded-full border border-gray-300 text-gray-700 hover:bg-gray-50"
            >
              <MoreVertical className="size-5" />
            </button>
          )}
        >
          {(close) => (
            <div className="text-sm">
              <button
                type="button"
                className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-gray-700 hover:bg-gray-50"
                onClick={() => {
                  close();
                  setCommissionOpen(true);
                }}
              >
                <Percent className="size-4" /> Set commission
              </button>
              <button
                type="button"
                className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-gray-700 hover:bg-gray-50"
                onClick={() => {
                  close();
                  update.mutate(
                    { id: v.id, body: { is_active: !v.is_active } },
                    {
                      onSuccess: () => toast(v.is_active ? "Store hidden from discovery" : "Store is discoverable again"),
                      onError: (e) => toast(errorMessage(e), "error"),
                    },
                  );
                }}
              >
                <EyeOff className="size-4" /> {v.is_active ? "Hide from discovery" : "Show in discovery"}
              </button>
              {v.is_verified ? (
                <button
                  type="button"
                  className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-red-600 hover:bg-red-50"
                  onClick={() => {
                    close();
                    confirm({
                      title: `Suspend ${v.name}?`,
                      description:
                        "The store closes and leaves the customer app at once. Its menu, orders and payouts stay intact, and you can approve it again later.",
                      confirmLabel: "Suspend vendor",
                      tone: "danger",
                      onConfirm: () => verify.mutateAsync({ id: v.id, isVerified: false }).then((r) => toast(r.message)),
                    });
                  }}
                >
                  <ShieldOff className="size-4" /> Suspend vendor
                </button>
              ) : (
                <button
                  type="button"
                  className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-green-700 hover:bg-green-50"
                  onClick={() => {
                    close();
                    confirm({
                      title: `Approve ${v.name}?`,
                      description: "Customers can find the store as soon as the vendor opens it.",
                      confirmLabel: "Approve",
                      tone: "success",
                      onConfirm: () => verify.mutateAsync({ id: v.id, isVerified: true }).then((r) => toast(r.message)),
                    });
                  }}
                >
                  <BadgeCheck className="size-4" /> Approve vendor
                </button>
              )}
            </div>
          )}
        </Popover>
      </div>
      {dialog}
      {commissionOpen && <CommissionDialog vendor={v} onClose={() => setCommissionOpen(false)} />}
    </Card>
  );
}

export function VendorDetailsPage() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.key === params.get("tab"))?.key ?? "store") as Tab;
  const vendor = useVendor(id);
  const back = { to: "/vendors", label: "Back to vendors" };

  if (vendor.isPending) return <PageSpinner />;
  if (vendor.isError) {
    return (
      <>
        <PageHeader title="Vendor Details" back={back} />
        <Card>
          <ErrorState error={vendor.error} onRetry={() => vendor.refetch()} />
        </Card>
      </>
    );
  }
  const v = vendor.data;

  return (
    <>
      <PageHeader title="Vendor Details" back={back} />
      <Card className="space-y-5 p-4 sm:p-5">
        <VendorHeader v={v} />
        <Card className="p-4 sm:p-5">
          <Tabs tabs={TABS} active={tab} onChange={(t) => setParams(t === "store" ? {} : { tab: t }, { replace: true })} className="mb-6" />
          {tab === "store" && <VendorStoreInfo v={v} />}
          {tab === "products" && <VendorProductsTab vendor={v} />}
          {tab === "orders" && <VendorOrdersTab vendorId={v.id} />}
          {tab === "reviews" && <VendorReviewsTab vendorId={v.id} />}
          {tab === "withdrawal" && <VendorWithdrawalTab vendorId={v.id} />}
        </Card>
      </Card>
    </>
  );
}
