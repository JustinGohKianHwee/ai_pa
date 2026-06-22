"use client";

import { usePathname } from "next/navigation";
import { NavRail } from "./NavRail";

// The shell wraps every authed page with the navigation rail. /login is the only
// pre-auth page and renders full-bleed without the rail.
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (pathname === "/login") {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen">
      <NavRail />
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
