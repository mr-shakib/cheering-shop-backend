import { useEffect, useState, type ComponentType } from "react";
import { NavLink, useLocation } from "react-router";
import {
  Bell,
  Bike,
  ChevronDown,
  CircleDollarSign,
  Clapperboard,
  FileText,
  GalleryHorizontalEnd,
  Headset,
  LayoutGrid,
  MapPin,
  Megaphone,
  MessagesSquare,
  Package,
  Settings,
  ShoppingBasket,
  Store,
  Users,
  UsersRound,
} from "lucide-react";

import { cn } from "@/lib/cn";

import { Logo } from "../Logo";

type Icon = ComponentType<{ className?: string }>;

interface Leaf {
  to: string;
  label: string;
  icon?: Icon;
  /** Other path prefixes that belong to this item (detail pages). */
  match?: string[];
}
interface Group {
  label: string;
  icon: Icon;
  children: Leaf[];
}
type Item = Leaf | Group;

const SECTIONS: { title: string; items: Item[] }[] = [
  {
    title: "Main menu",
    items: [
      { to: "/", label: "Overview", icon: LayoutGrid },
      { to: "/orders", label: "Order", icon: Package },
      { to: "/customers", label: "Customers", icon: Users },
      {
        label: "Vendor",
        icon: Store,
        children: [
          { to: "/vendors", label: "Active Vendors" },
          { to: "/vendor-applications", label: "Application" },
          { to: "/vendor-withdrawals", label: "Withdrawal" },
        ],
      },
      {
        label: "Rider",
        icon: Bike,
        children: [
          { to: "/riders", label: "Active Rider" },
          { to: "/rider-applications", label: "Application" },
          { to: "/rider-withdrawals", label: "Withdrawal" },
        ],
      },
      { to: "/products", label: "Product", icon: ShoppingBasket },
      { to: "/categories", label: "Category", icon: FileText },
    ],
  },
  {
    title: "Community",
    items: [
      { to: "/support", label: "Support Ticket", icon: Headset },
      { to: "/live-chat", label: "Live Chat", icon: MessagesSquare },
      { to: "/community", label: "Community", icon: UsersRound },
      { to: "/reels", label: "Reels", icon: Clapperboard },
    ],
  },
  {
    title: "Others",
    items: [
      { to: "/finance", label: "Finance", icon: CircleDollarSign },
      { to: "/advertisements", label: "Advertisement", icon: Megaphone },
      { to: "/banners", label: "App Banners", icon: GalleryHorizontalEnd },
      { to: "/live-tracking", label: "Live Tracking", icon: MapPin },
    ],
  },
  {
    title: "Preferences",
    items: [
      { to: "/notifications", label: "Notification", icon: Bell },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

function isActive(pathname: string, leaf: Leaf) {
  if (leaf.to === "/") return pathname === "/";
  return [leaf.to, ...(leaf.match ?? [])].some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

const rowClass = "flex h-10 w-full items-center gap-3 rounded-lg px-3 text-[15px] transition-colors";

function LeafLink({ leaf, nested, onNavigate }: { leaf: Leaf; nested?: boolean; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const active = isActive(pathname, leaf);
  const Icon = leaf.icon;
  return (
    <NavLink
      to={leaf.to}
      onClick={onNavigate}
      className={cn(
        rowClass,
        nested && "pl-10",
        active ? "bg-brand-100 font-medium text-brand-500" : "text-gray-700 hover:bg-gray-50 hover:text-gray-900",
      )}
      end={leaf.to === "/"}
    >
      {Icon && <Icon className="size-5 shrink-0" />}
      {leaf.label}
    </NavLink>
  );
}

function GroupItem({ group, onNavigate }: { group: Group; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const containsActive = group.children.some((c) => isActive(pathname, c));
  const [open, setOpen] = useState(containsActive);
  useEffect(() => {
    if (containsActive) setOpen(true);
  }, [containsActive]);
  const Icon = group.icon;
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn(rowClass, "text-gray-700 hover:bg-gray-50 hover:text-gray-900")}
      >
        <Icon className="size-5 shrink-0" />
        <span className="flex-1 text-left">{group.label}</span>
        <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="mt-1 space-y-1">
          {group.children.map((c) => (
            <LeafLink key={c.to} leaf={c} nested onNavigate={onNavigate} />
          ))}
        </div>
      )}
    </div>
  );
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <aside className="flex h-full w-[270px] flex-col border-r border-line bg-white">
      <div className="flex h-20 shrink-0 items-center px-6">
        <NavLink to="/" onClick={onNavigate} aria-label="Overview">
          <Logo />
        </NavLink>
      </div>
      <nav className="scrollbar-thin flex-1 overflow-y-auto px-4 pb-6">
        {SECTIONS.map((section) => (
          <div key={section.title} className="mt-3 first:mt-1">
            <p className="px-3 pt-2 pb-2 text-xs font-medium tracking-wide text-gray-600 uppercase">{section.title}</p>
            <div className="space-y-1">
              {section.items.map((item) =>
                "children" in item ? (
                  <GroupItem key={item.label} group={item} onNavigate={onNavigate} />
                ) : (
                  <LeafLink key={item.to} leaf={item} onNavigate={onNavigate} />
                ),
              )}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  );
}
