import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Bell, Bike, ChevronDown, Loader2, LogOut, Menu, Package, Search, Settings, Store, User } from "lucide-react";

import { useDashboard, useSearch, type SearchHit } from "@/api/insights";
import { signOut } from "@/api/auth";
import { cn } from "@/lib/cn";
import { useDebounced } from "@/lib/hooks";
import { useSession } from "@/lib/session";

import { Avatar } from "../ui/Display";
import { Popover } from "../ui/Popover";

function GlobalSearch() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const debounced = useDebounced(q.trim(), 250);
  const search = useSearch(debounced);
  const input = useRef<HTMLInputElement>(null);

  const groups: { key: "orders" | "customers" | "vendors" | "riders"; title: string; icon: typeof Package; to: (h: SearchHit) => string }[] = [
    { key: "orders", title: "Orders", icon: Package, to: (h) => `/orders?order=${h.id}` },
    { key: "customers", title: "Customers", icon: User, to: (h) => `/customers/${h.id}` },
    { key: "vendors", title: "Vendors", icon: Store, to: (h) => `/vendors/${h.id}` },
    { key: "riders", title: "Riders", icon: Bike, to: (h) => `/riders/${h.id}` },
  ];

  const go = (to: string) => {
    setOpen(false);
    setQ("");
    input.current?.blur();
    navigate(to);
  };

  const results = search.data;
  const total = results ? groups.reduce((n, g) => n + results[g.key].length, 0) : 0;
  const show = open && debounced.length >= 2;

  return (
    <div className="relative w-full max-w-80">
      <Search className="pointer-events-none absolute top-1/2 left-3.5 size-[18px] -translate-y-1/2 text-gray-500" />
      <input
        ref={input}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setOpen(false);
            input.current?.blur();
          }
          if (e.key === "Enter" && results) {
            const first = groups.find((g) => results[g.key].length);
            if (first) go(first.to(results[first.key][0]));
          }
        }}
        placeholder="Search orders, vendors, riders..."
        className="h-10 w-full rounded-full bg-gray-100 pr-4 pl-10 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:bg-white focus:ring-3 focus:ring-brand-100"
      />
      {show && (
        <div className="absolute top-full right-0 left-0 z-30 mt-2 max-h-[70vh] animate-pop-in overflow-y-auto rounded-xl border border-line bg-white p-2 shadow-xl sm:w-96">
          {search.isFetching && !results ? (
            <div className="flex justify-center py-6">
              <Loader2 className="size-4 animate-spin text-gray-400" />
            </div>
          ) : total === 0 ? (
            <p className="px-3 py-4 text-sm text-gray-500">No matches for “{debounced}”.</p>
          ) : (
            groups.map((g) =>
              results && results[g.key].length ? (
                <div key={g.key} className="py-1">
                  <p className="px-3 py-1 text-[11px] font-semibold tracking-wide text-gray-500 uppercase">{g.title}</p>
                  {results[g.key].map((h) => (
                    <button
                      key={h.id}
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => go(g.to(h))}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-gray-50"
                    >
                      <g.icon className="size-4 shrink-0 text-gray-400" />
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-gray-900">{h.title}</span>
                        {h.subtitle && <span className="block truncate text-xs text-gray-500">{h.subtitle}</span>}
                      </span>
                    </button>
                  ))}
                </div>
              ) : null,
            )
          )}
        </div>
      )}
    </div>
  );
}

/** The bell: what is waiting on an administrator right now. */
function AttentionBell() {
  const { data } = useDashboard();
  const items = data
    ? [
        { n: data.pending_approvals.vendors, label: "vendors awaiting approval", to: "/vendor-applications" },
        { n: data.pending_approvals.riders, label: "rider applications to review", to: "/rider-applications" },
        { n: data.live_orders.awaiting_rider, label: "orders no rider has taken", to: "/orders?awaiting_rider=true" },
        { n: data.support_tickets.open, label: "open support tickets", to: "/support?status=ACTIVE" },
        { n: data.support_tickets.urgent, label: "urgent tickets", to: "/support?priority=URGENT" },
      ].filter((i) => i.n > 0)
    : [];

  return (
    <Popover
      align="right"
      panelClassName="w-80 p-2"
      trigger={({ toggle }) => (
        <button
          type="button"
          onClick={toggle}
          aria-label="Things that need attention"
          className="relative flex size-10 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-800 hover:bg-gray-50"
        >
          <Bell className="size-[18px]" />
          {items.length > 0 && <span className="absolute top-2 right-2.5 size-2 rounded-full bg-red-500 ring-2 ring-white" />}
        </button>
      )}
    >
      {(close) => (
        <div>
          <p className="px-3 pt-1 pb-2 text-sm font-semibold text-gray-900">Needs attention</p>
          {items.length === 0 ? (
            <p className="px-3 pb-3 text-sm text-gray-500">Nothing is waiting on you.</p>
          ) : (
            items.map((i) => (
              <Link
                key={i.label}
                to={i.to}
                onClick={close}
                className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                <span className="flex h-6 min-w-6 items-center justify-center rounded-full bg-brand-50 px-1.5 text-xs font-semibold text-brand-500">
                  {i.n}
                </span>
                {i.label}
              </Link>
            ))
          )}
        </div>
      )}
    </Popover>
  );
}

function ProfileMenu() {
  const session = useSession();
  const navigate = useNavigate();
  const user = session?.user;
  return (
    <Popover
      align="right"
      panelClassName="w-56 p-1.5"
      trigger={({ toggle, open }) => (
        <button type="button" onClick={toggle} className="flex items-center gap-3 rounded-full py-1 pr-1 pl-1 hover:bg-gray-50">
          <Avatar src={user?.avatar_url} name={user?.full_name ?? user?.email} size={40} />
          <span className="hidden text-left sm:block">
            <span className="block max-w-40 truncate text-[15px] font-medium text-gray-900">
              {user?.full_name || user?.email || "Administrator"}
            </span>
            <span className="block text-xs text-gray-500">Administrator</span>
          </span>
          <ChevronDown className={cn("hidden size-4 text-gray-500 transition-transform sm:block", open && "rotate-180")} />
        </button>
      )}
    >
      {(close) => (
        <div>
          <Link
            to="/settings"
            onClick={close}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            <Settings className="size-4" /> Settings
          </Link>
          <button
            type="button"
            onClick={async () => {
              close();
              await signOut();
              navigate("/login", { replace: true });
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-red-600 hover:bg-red-50"
          >
            <LogOut className="size-4" /> Sign out
          </button>
        </div>
      )}
    </Popover>
  );
}

export function Topbar({ onMenu }: { onMenu: () => void }) {
  return (
    <header className="sticky top-0 z-20 flex h-20 shrink-0 items-center gap-4 border-b border-line bg-white/95 px-4 backdrop-blur sm:px-6">
      <button
        type="button"
        onClick={onMenu}
        aria-label="Toggle navigation"
        className="flex size-10 shrink-0 items-center justify-center rounded-lg text-gray-800 hover:bg-gray-100"
      >
        <Menu className="size-6" />
      </button>
      <GlobalSearch />
      <div className="ml-auto flex items-center gap-3 sm:gap-4">
        <AttentionBell />
        <ProfileMenu />
      </div>
    </header>
  );
}
