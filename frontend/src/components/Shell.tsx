import clsx from "clsx";
import { BarChart3, FilePlus2, FolderOpen, Settings } from "lucide-react";
import type { ComponentType } from "react";
import { NavLink, Outlet } from "react-router-dom";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
}

const MAIN: NavItem[] = [
  { to: "/cases", label: "Cases", icon: FolderOpen },
  { to: "/new", label: "New review", icon: FilePlus2 },
  { to: "/insights", label: "Insights", icon: BarChart3 },
];

const FOOT: NavItem[] = [{ to: "/settings", label: "Settings", icon: Settings }];

function Mark() {
  return (
    <svg viewBox="0 0 32 32" className="h-8 w-8 shrink-0" aria-hidden>
      <rect width="32" height="32" rx="7" fill="#1C3D6E" />
      <path d="M16 6.5 8.5 9.4v6.2c0 4.6 3.1 8.5 7.5 9.9 4.4-1.4 7.5-5.3 7.5-9.9V9.4L16 6.5Z" fill="none"
        stroke="#fff" strokeWidth="2" strokeLinejoin="round" />
      <path d="m12.6 16 2.4 2.4 4.4-4.6" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round"
        strokeLinejoin="round" />
    </svg>
  );
}

function Item({ item }: { item: NavItem }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      className={({ isActive }) => clsx(
        "relative flex h-10 items-center gap-3 rounded px-[0.6875rem] text-sm transition-colors",
        isActive ? "bg-navy-50 font-medium text-navy" : "text-slate hover:bg-canvas hover:text-ink",
      )}
    >
      {({ isActive }) => (
        <>
          {isActive && <span className="absolute -left-2 top-2 h-6 w-[3px] rounded-r bg-navy" aria-hidden />}
          <Icon className="h-[1.125rem] w-[1.125rem] shrink-0" />
          <span className="whitespace-nowrap opacity-0 transition-opacity duration-150 group-hover/nav:opacity-100 group-focus-within/nav:opacity-100">
            {item.label}
          </span>
        </>
      )}
    </NavLink>
  );
}

export default function Shell() {
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-20 focus:top-3 focus:z-50 focus:rounded focus:bg-paper focus:px-3 focus:py-2">
        Skip to content
      </a>

      <nav
        aria-label="Main"
        className="group/nav fixed inset-y-0 left-0 z-40 flex w-16 flex-col border-r border-rule bg-paper px-2 py-3 transition-[width,box-shadow] duration-200 hover:w-56 hover:shadow-[4px_0_24px_-12px_rgba(23,32,51,0.25)] focus-within:w-56"
      >
        <NavLink to="/cases" className="mb-5 flex h-10 items-center gap-3 px-1" aria-label="MandateIQ home">
          <Mark />
          <span className="whitespace-nowrap font-serif text-lg font-semibold text-ink opacity-0 transition-opacity duration-150 group-hover/nav:opacity-100 group-focus-within/nav:opacity-100">
            MandateIQ
          </span>
        </NavLink>

        <div className="flex flex-col gap-1">
          {MAIN.map((item) => <Item key={item.to} item={item} />)}
        </div>

        <div className="mt-auto flex flex-col gap-1">
          {FOOT.map((item) => <Item key={item.to} item={item} />)}
        </div>
      </nav>

      <div className="pl-16">
        <main id="main" className="mx-auto max-w-page px-6 pb-10 pt-9 lg:px-10">
          <Outlet />
        </main>
        <footer className="mx-auto max-w-page px-6 pb-8 text-xs text-mute lg:px-10">
          Educational prototype using synthetic data and illustrative rules. Not investment advice, and not any
          organization's approval process.
        </footer>
      </div>
    </div>
  );
}
