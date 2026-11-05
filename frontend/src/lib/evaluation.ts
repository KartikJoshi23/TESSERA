/** The report `tessera-eval` writes, as the Lab reads it. Real and synthetic levels stay apart. */

export interface GroupScore {
  items: number;
  accuracy: number | null;
  false_reassurance: number | null;
}

export interface SystemReport {
  items: number;
  failures: number;
  not_yet_run: number;
  false_reassurance_rate: number | null;
  unsupported_conflict_rate: number | null;
  unsupported_conflict_on_genuine: number | null;
  macro_f1: number | null;
  coverage: number | null;
  decisive_accuracy: number | null;
  cost_weighted_error: number | null;
  compute: { requests_per_case: number | null; tokens_per_case: number | null };
  coordination: Record<string, number | null>;
  confusion: Record<string, Record<string, number>>;
  by_group: Record<string, GroupScore>;
  intervals: { false_reassurance_rate: [number, number]; macro_f1: [number, number] };
}

export interface ComparisonReport {
  name: string;
  pairs: number;
  first?: string;
  second?: string;
  metric?: "false_reassurance" | "macro_f1";
  difference?: number;
  ci_low?: number;
  ci_high?: number;
  p_value?: number;
  p_holm?: number;
}

export interface StabilityReport {
  condition: string;
  items: number;
  fleiss_kappa?: number;
  flip_rate?: number;
}

export interface LevelReport {
  level: string;
  items: number;
  systems: Record<string, SystemReport>;
  registered: ComparisonReport[];
  secondary: ComparisonReport[];
  non_inferiority: { tested: boolean; holds?: boolean; ci_low?: number; margin?: number };
  interaction: {
    tested: boolean;
    difference?: number;
    ci_low?: number;
    ci_high?: number;
    focus_items?: number;
    other_items?: number;
  };
  stability: StabilityReport[];
}

export interface EvaluationReport {
  levels: Partial<Record<"entity" | "message", LevelReport>>;
}

/** The order the conditions read in, from no model to the full crew. */
export const SYSTEM_ORDER = [
  "RULES-ONLY",
  "SA-BASE",
  "SA-VER",
  "SA-SC5",
  "SA-MAX",
  "SA-LARGER",
  "CREW-SILO",
  "CREW-SHARE",
  "CREW-FULL",
  "CREW-NV",
];

export function orderedSystems(level: LevelReport): [string, SystemReport][] {
  const rank = (name: string) => {
    const index = SYSTEM_ORDER.indexOf(name);
    return index === -1 ? SYSTEM_ORDER.length : index;
  };
  return Object.entries(level.systems).sort(([a], [b]) => rank(a) - rank(b));
}

/** Every factor or stratum any system was scored on, in reading order. */
export function groupsOf(level: LevelReport): string[] {
  const names = new Set(Object.values(level.systems).flatMap((s) => Object.keys(s.by_group)));
  const number = (name: string) => Number(name.replace(/\D/g, ""));
  return [...names].sort((a, b) => number(a) - number(b));
}

/** The widest number a set of intervals reaches, so a chart can be centred on zero. */
export function reach(comparisons: readonly ComparisonReport[]): number {
  const edges = comparisons.flatMap((c) => [Math.abs(c.ci_low ?? 0), Math.abs(c.ci_high ?? 0)]);
  const widest = Math.max(0.05, ...edges);
  return Math.ceil(widest * 20) / 20;
}

export function shown(value: number | null | undefined, digits = 3): string {
  return value === null || value === undefined ? "–" : value.toFixed(digits);
}

export function bounds(interval: readonly [number, number]): string {
  return `[${shown(interval[0], 2)}, ${shown(interval[1], 2)}]`;
}

export function signed(value: number | undefined): string {
  if (value === undefined) return "–";
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(3)}`;
}
