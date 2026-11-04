/**
 * The development comparison in the Lab: counts over 25 fictional cases written by hand. It is here
 * so the system's behaviour can be seen while it is built, and it is not an evaluation result.
 */
export interface SmokeCase {
  case: string;
  gold: string;
  result: string;
  requests: number;
  tokens: number;
  seconds: number;
}

export interface SmokeRun {
  run: string;
  condition: string;
  rate_limited: number;
  cases: SmokeCase[];
}

export interface SmokeRow {
  run: string;
  condition: string;
  cases: SmokeCase[];
  total: number;
  agreed: number;
  /** Said "Consistent" where the hand label did not. The measure this project cares about most. */
  falseReassurance: number;
  /** Said "Could not verify" where the hand label had an answer. */
  overCautious: number;
  requests: number;
  tokens: number;
  seconds: number;
}

export function summarize(run: SmokeRun): SmokeRow {
  const { cases } = run;
  const sum = (key: "requests" | "tokens" | "seconds") =>
    cases.reduce((total, item) => total + item[key], 0);
  return {
    run: run.run,
    condition: run.condition,
    cases,
    total: cases.length,
    agreed: cases.filter((item) => item.result === item.gold).length,
    falseReassurance: cases.filter(
      (item) => item.result === "CONSISTENT" && item.gold !== "CONSISTENT",
    ).length,
    overCautious: cases.filter((item) => item.result === "UNVERIFIED" && item.gold !== "UNVERIFIED")
      .length,
    requests: sum("requests"),
    tokens: sum("tokens"),
    seconds: sum("seconds"),
  };
}
