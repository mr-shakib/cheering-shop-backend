/* Every enum the API returns, mapped to what the mockups print and the pill
 * colour they use. One place, so a status reads the same on every screen. */

export type Tone = "green" | "orange" | "blue" | "red" | "gray" | "purple" | "pink" | "teal";

export interface Label {
  label: string;
  tone: Tone;
}

const fallback = (value: string | null | undefined): Label => ({
  label: value ? value.charAt(0) + value.slice(1).toLowerCase().replace(/_/g, " ") : "—",
  tone: "gray",
});

function lookup(table: Record<string, Label>) {
  return (value: string | null | undefined): Label => (value && table[value]) || fallback(value);
}

export const orderStatus = lookup({
  PENDING: { label: "Pending", tone: "orange" },
  PREPARING: { label: "Preparing", tone: "orange" },
  READY: { label: "Ready", tone: "purple" },
  PICKED_UP: { label: "On Delivery", tone: "blue" },
  DELIVERED: { label: "Delivered", tone: "green" },
  CANCELLED: { label: "Cancelled", tone: "red" },
});

/** Timeline steps, in order. There is no ACCEPTED status: accepting moves an
 * order straight to PREPARING, so "Accepted" is inferred from PREPARING. */
export const ORDER_STEPS = [
  { key: "PENDING", label: "Placed" },
  { key: "ACCEPTED", label: "Accepted" },
  { key: "PREPARING", label: "Preparing" },
  { key: "READY", label: "Ready" },
  { key: "PICKED_UP", label: "Picked Up" },
  { key: "DELIVERED", label: "Delivered" },
] as const;

export const paymentMethod = (m: string | null | undefined): string =>
  ({ COD: "COD", WALLET: "Wallet", BKASH: "bKash", CARD: "Card", NAGAD: "Nagad", ROCKET: "Rocket", BANK: "Bank" } as Record<
    string,
    string
  >)[m ?? ""] ?? (m ? m.charAt(0) + m.slice(1).toLowerCase() : "—");

export const paymentStatus = lookup({
  PENDING: { label: "Unpaid", tone: "orange" },
  PAID: { label: "Paid", tone: "green" },
  FAILED: { label: "Failed", tone: "red" },
  REFUNDED: { label: "Refunded", tone: "purple" },
});

export const payoutStatus = lookup({
  PROCESSING: { label: "Pending", tone: "orange" },
  COMPLETED: { label: "Paid", tone: "green" },
  FAILED: { label: "Failed", tone: "red" },
});

export const applicationStatus = lookup({
  PENDING: { label: "Pending", tone: "orange" },
  APPROVED: { label: "Approved", tone: "green" },
  REJECTED: { label: "Rejected", tone: "red" },
});

export const productStatus = lookup({
  ACTIVE: { label: "Active", tone: "green" },
  HIDDEN: { label: "Hidden", tone: "gray" },
  UNAVAILABLE: { label: "Sold out", tone: "orange" },
});

export const ticketStatus = lookup({
  OPEN: { label: "Open", tone: "blue" },
  PENDING: { label: "Pending", tone: "orange" },
  RESOLVED: { label: "Resolved", tone: "green" },
  CLOSED: { label: "Closed", tone: "gray" },
});

export const ticketPriority = lookup({
  LOW: { label: "Low", tone: "gray" },
  MEDIUM: { label: "Medium", tone: "orange" },
  HIGH: { label: "High", tone: "red" },
  URGENT: { label: "Urgent", tone: "red" },
});

export const adStatus = lookup({
  SCHEDULED: { label: "Scheduled", tone: "blue" },
  ACTIVE: { label: "Active", tone: "green" },
  PAUSED: { label: "Paused", tone: "orange" },
  ENDED: { label: "Ended", tone: "gray" },
});

export const campaignStatus = lookup({
  SCHEDULED: { label: "Scheduled", tone: "orange" },
  SENT: { label: "Sent", tone: "green" },
  FAILED: { label: "Failed", tone: "red" },
  CANCELLED: { label: "Cancelled", tone: "gray" },
});

export const bannerStatus = lookup({
  LIVE: { label: "Live", tone: "green" },
  SCHEDULED: { label: "Scheduled", tone: "blue" },
  EXPIRED: { label: "Expired", tone: "gray" },
  INACTIVE: { label: "Inactive", tone: "red" },
});

export const invitationStatus = lookup({
  PENDING: { label: "Pending", tone: "orange" },
  ACCEPTED: { label: "Accepted", tone: "green" },
  EXPIRED: { label: "Expired", tone: "gray" },
  REVOKED: { label: "Revoked", tone: "red" },
});

export const liveRiderStatus = lookup({
  AVAILABLE: { label: "Available", tone: "green" },
  HEADING_TO_PICKUP: { label: "Heading to pickup", tone: "orange" },
  DELIVERING: { label: "Delivering", tone: "pink" },
});

export const BUSINESS_TYPES = ["RESTAURANT", "GROCERY", "PHARMACY"] as const;
export type BusinessType = (typeof BUSINESS_TYPES)[number];

export const businessTypeLabel = (t: string | null | undefined): string =>
  ({ RESTAURANT: "Food", GROCERY: "Grocery", PHARMACY: "Medicine" } as Record<string, string>)[t ?? ""] ?? "—";

export const VEHICLE_TYPES = ["CYCLE", "BIKE", "MOTORCYCLE", "SCOOTER", "CAR"] as const;

export const vehicleLabel = (v: string | null | undefined): string =>
  v ? v.charAt(0) + v.slice(1).toLowerCase() : "—";

export const DOCUMENT_LABELS: Record<string, string> = {
  shop_image: "Shop Image",
  owner_nid: "NID",
  nid: "NID",
  nid_front: "NID (front)",
  nid_back: "NID (back)",
  menu_list: "Menu",
  trade_license: "Trade License",
  driving_license: "Driving License",
  license: "Driving License",
  profile_photo: "Profile Photo",
  photo: "Profile Photo",
  bank_statement: "Bank/Mobile Wallet",
  payout_proof: "Bank/Mobile Wallet",
};

export const documentLabel = (kind: string): string =>
  DOCUMENT_LABELS[kind] ?? kind.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
