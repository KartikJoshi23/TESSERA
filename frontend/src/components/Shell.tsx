"use client";

import { Hexagon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useStatus } from "@/lib/hooks";

const LINKS = [
  { href: "/", label: "Console" },
  { href: "/intake", label: "Intake" },
  { href: "/arena", label: "Arena" },
  { href: "/lab", label: "Lab" },
  { href: "/governance", label: "Governance" },
];

const MODE_LABEL: Record<string, string> = {
  RESEARCH_INTERNAL: "Research-internal",
  RESTRICTED_DEMO: "Restricted demo",
};

const RETRY_MS = 5000;

function ModeBadge() {
  const { data, error, reload } = useStatus();
  useEffect(() => {
    if (!error) return;
    const timer = setInterval(reload, RETRY_MS);
    return () => clearInterval(timer);
  }, [error, reload]);
  const label = error ? "API offline" : data ? (MODE_LABEL[data.mode] ?? data.mode) : "…";
  return (
    <span
      data-testid="mode-badge"
      className={`rounded-md border px-2 py-1 text-[11px] font-medium whitespace-nowrap ${
        error ? "border-challenge/50 text-challenge" : "border-line-strong text-text-2"
      }`}
    >
      {label}
    </span>
  );
}

export function Shell() {
  const path = usePathname();
  return (
    <header
      data-print-hide
      className="sticky top-0 z-30 border-b border-line bg-lapis-950/70 backdrop-blur-xl"
    >
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-40 focus:rounded-md focus:bg-lapis-800 focus:px-3 focus:py-2"
      >
        Skip to the content
      </a>
      <div className="mx-auto flex h-14 w-full max-w-[1680px] items-center gap-3 px-4 sm:gap-6 lg:px-6">
        <Link href="/" className="flex items-center gap-2" aria-label="TESSERA console">
          <Hexagon size={20} aria-hidden className="text-cma" strokeWidth={1.75} />
          <span className="display hidden text-[15px] tracking-tight sm:inline">TESSERA</span>
        </Link>
        <nav aria-label="Main" className="flex min-w-0 items-center gap-1 overflow-x-auto">
          {LINKS.map(({ href, label }) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`rounded-md px-2.5 py-1.5 text-sm ${
                  active ? "bg-white/10 text-text" : "text-text-2 hover:text-text"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <span
            data-testid="research-badge"
            className="hidden rounded-md border border-jur/40 bg-jur/10 px-2 py-1 text-[11px] font-semibold tracking-wide whitespace-nowrap text-jur lg:inline"
          >
            INTERNAL RESEARCH PROTOTYPE · synthetic inputs only
          </span>
          <ModeBadge />
        </div>
      </div>
      <p className="border-t border-line px-4 py-1 text-center text-[10px] font-semibold tracking-wide text-jur lg:hidden">
        INTERNAL RESEARCH PROTOTYPE · synthetic inputs only
      </p>
    </header>
  );
}
