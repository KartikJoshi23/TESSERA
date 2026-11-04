/** Small pieces shared by every view. */
import { Info, TriangleAlert } from "lucide-react";

export function SyntheticBadge() {
  return (
    <span className="data inline-flex items-center rounded-md border border-inform/40 bg-inform/10 px-2 py-0.5 text-[11px] font-medium tracking-wide text-inform">
      SYNTHETIC
    </span>
  );
}

export function Notice({
  title,
  children,
  tone = "info",
}: {
  title: string;
  children: React.ReactNode;
  tone?: "info" | "caution";
}) {
  const Icon = tone === "caution" ? TriangleAlert : Info;
  const color = tone === "caution" ? "var(--color-challenge)" : "var(--color-inform)";
  return (
    <div className="glass flex gap-3 p-4" role={tone === "caution" ? "alert" : "status"}>
      <Icon size={18} aria-hidden className="mt-0.5 shrink-0" color={color} />
      <div className="min-w-0">
        <p className="font-medium">{title}</p>
        <div className="mt-1 text-sm leading-relaxed text-text-2">{children}</div>
      </div>
    </div>
  );
}

export function ApiOffline({ message }: { message: string }) {
  return (
    <Notice title="The local API is not answering" tone="caution">
      <p>{message}</p>
      <p className="mt-2">
        Start it from the <span className="data">backend</span> folder with{" "}
        <code className="data rounded bg-black/40 px-1.5 py-0.5 text-text">
          uv run tessera-api --fiction
        </code>{" "}
        and reload this page.
      </p>
    </Notice>
  );
}

export function PageTitle({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="max-w-3xl">
      <p className="eyebrow">{eyebrow}</p>
      <h1 className="display mt-2 text-3xl sm:text-4xl">{title}</h1>
      {children && <p className="mt-3 leading-relaxed text-text-2">{children}</p>}
    </header>
  );
}
