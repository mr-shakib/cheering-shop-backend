import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router";

import { useMe } from "@/api/auth";
import { cn } from "@/lib/cn";
import { useSession } from "@/lib/session";

import { PageSpinner } from "../ui/Feedback";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

const DESKTOP = "(min-width: 1024px)";

export function AppLayout() {
  const session = useSession();
  const location = useLocation();
  const me = useMe(!!session);
  const [desktopOpen, setDesktopOpen] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => setMobileOpen(false), [location.pathname]);

  if (!session) {
    const next = location.pathname + location.search;
    return <Navigate to={next === "/" ? "/login" : `/login?next=${encodeURIComponent(next)}`} replace />;
  }
  // The stored token is only trusted once /users/me agrees it is an admin's.
  if (me.isPending) return <PageSpinner />;

  const toggle = () => {
    if (window.matchMedia(DESKTOP).matches) setDesktopOpen((o) => !o);
    else setMobileOpen((o) => !o);
  };

  return (
    <div className="flex min-h-full">
      <div className={cn("sticky top-0 hidden h-screen shrink-0", desktopOpen && "lg:block")}>
        <Sidebar />
      </div>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 animate-fade-in bg-gray-900/40" onClick={() => setMobileOpen(false)} />
          <div className="relative h-full w-fit animate-slide-in">
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenu={toggle} />
        <main className="flex-1 px-4 py-6 sm:px-7 sm:py-7">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
