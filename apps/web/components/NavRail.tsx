"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Inbox,
  CheckSquare,
  Wallet,
  Apple,
  Dumbbell,
  Calendar,
  ClipboardList,
  History,
  PieChart,
  LogOut,
} from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { logout } from "@/app/logout/actions";

const items = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/tasks", label: "Tasks", icon: CheckSquare },
  { href: "/finance", label: "Finance", icon: Wallet },
  { href: "/food", label: "Food", icon: Apple },
  { href: "/exercise", label: "Exercise", icon: Dumbbell },
  { href: "/calendar", label: "Calendar", icon: Calendar },
  { href: "/review", label: "Review", icon: ClipboardList },
  { href: "/timeline", label: "Timeline", icon: History },
  { href: "/portfolio", label: "Portfolio", icon: PieChart },
];

export function NavRail() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary navigation"
      className="sticky top-0 flex h-screen w-16 shrink-0 flex-col items-center gap-1 border-r border-border bg-surface py-4"
    >
      <Link
        href="/"
        aria-label="Home"
        className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-sm font-medium text-accent-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        J
      </Link>

      <div className="flex flex-1 flex-col items-center gap-1">
        {items.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              title={label}
              aria-label={label}
              aria-current={active ? "page" : undefined}
              className={`relative flex h-10 w-10 items-center justify-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                active
                  ? "bg-surface-raised text-accent"
                  : "text-muted hover:bg-surface-raised hover:text-fg"
              }`}
            >
              {active ? (
                <span
                  className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-accent"
                  aria-hidden
                />
              ) : null}
              <Icon size={20} aria-hidden />
            </Link>
          );
        })}
      </div>

      <div className="flex flex-col items-center gap-1">
        <ThemeToggle />
        <form action={logout}>
          <button
            type="submit"
            title="Sign out"
            aria-label="Sign out"
            className="flex h-9 w-9 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-raised hover:text-negative focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <LogOut size={18} aria-hidden />
          </button>
        </form>
      </div>
    </nav>
  );
}
