/**
 * The three results. Colour, icon and label always appear together, and none of them passes
 * judgement on a firm: each result describes a comparison with the official record.
 */
import { CircleDashed, type LucideIcon, ShieldCheck, Split } from "lucide-react";
import { resultLook } from "@/lib/vocabulary";

export const RESULT_ICON: Record<string, LucideIcon> = {
  CONSISTENT: ShieldCheck,
  CONFLICTS: Split,
  UNVERIFIED: CircleDashed,
};

export function ResultBadge({ result }: { result: string | null | undefined }) {
  const look = resultLook(result);
  if (!look || !result) return <span className="text-sm text-text-3">No result yet</span>;
  const Icon = RESULT_ICON[result] ?? CircleDashed;
  return (
    <span className="inline-flex items-center gap-1.5 text-sm font-medium" style={{ color: look.color }}>
      <Icon size={15} aria-hidden />
      {look.label}
    </span>
  );
}
