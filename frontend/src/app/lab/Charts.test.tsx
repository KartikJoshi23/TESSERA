import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { LevelReport, SystemReport } from "@/lib/evaluation";
import { EvaluationCharts } from "./Charts";

afterEach(cleanup);

function system(macroF1: number, requests: number): SystemReport {
  return {
    items: 10,
    failures: 0,
    not_yet_run: 0,
    false_reassurance_rate: 0.1,
    unsupported_conflict_rate: 0.05,
    unsupported_conflict_on_genuine: 0,
    macro_f1: macroF1,
    coverage: 0.8,
    decisive_accuracy: 0.9,
    cost_weighted_error: 0.4,
    compute: { requests_per_case: requests, tokens_per_case: 1000 },
    coordination: { veto_rate: 0.25 },
    confusion: {
      CONSISTENT: { CONSISTENT: 4, CONFLICTS: 1, UNVERIFIED: 0 },
      CONFLICTS: { CONSISTENT: 0, CONFLICTS: 3, UNVERIFIED: 0 },
      UNVERIFIED: { CONSISTENT: 0, CONFLICTS: 0, UNVERIFIED: 2 },
    },
    by_group: { F1: { items: 4, accuracy: 0.75, false_reassurance: 0 } },
    intervals: { false_reassurance_rate: [0, 0.2], macro_f1: [0.5, 0.9] },
  };
}

const level: LevelReport = {
  level: "message",
  items: 10,
  systems: { "SA-BASE": system(0.7, 4.5), "CREW-FULL": system(0.8, 18) },
  registered: [
    {
      name: "H1 false reassurance",
      first: "CREW-FULL",
      second: "SA-BASE",
      metric: "false_reassurance",
      pairs: 10,
      difference: -0.04,
      ci_low: -0.09,
      ci_high: 0.01,
      p_value: 0.25,
    },
    { name: "not run yet", pairs: 0 },
  ],
  secondary: [],
  non_inferiority: { tested: true, holds: true, ci_low: 0.01, margin: 0.02 },
  interaction: { tested: false },
  stability: [],
};

describe("the evaluation charts", () => {
  it("show a comparison with its difference and test", () => {
    render(<EvaluationCharts level={level} />);
    const rows = within(screen.getByTestId("comparisons"));
    expect(rows.getByText("H1 false reassurance")).toBeTruthy();
    expect(rows.getByText(/−0\.040/)).toBeTruthy();
    expect(rows.getByText(/p 0\.250/)).toBeTruthy();
  });

  it("leave out a comparison that has not run", () => {
    render(<EvaluationCharts level={level} />);
    expect(screen.queryByText("not run yet")).toBeNull();
  });

  it("place every system on the frontier", () => {
    render(<EvaluationCharts level={level} />);
    expect(screen.getAllByTestId("frontier-dot")).toHaveLength(2);
  });

  it("show the hypotheses plainly, saying what is not tested", () => {
    render(<EvaluationCharts level={level} />);
    expect(screen.getByText(/Holds: lower bound/)).toBeTruthy();
    expect(screen.getByText("Not tested yet")).toBeTruthy();
  });

  it("show a share for each factor", () => {
    render(<EvaluationCharts level={level} />);
    const table = within(screen.getByTestId("factor-table"));
    expect(table.getAllByText("75")).toHaveLength(2);
  });

  it("open the confusion table on the crew", () => {
    render(<EvaluationCharts level={level} />);
    expect(screen.getByRole<HTMLSelectElement>("combobox").value).toBe("CREW-FULL");
  });

  it("count the cases with no answer next to the scores", () => {
    const failing = { ...system(0.7, 4.5), failures: 3, not_yet_run: 2 };
    render(<EvaluationCharts level={{ ...level, systems: { "SA-BASE": failing } }} />);
    const rows = within(screen.getByTestId("systems")).getAllByRole("row");
    const row = rows[1] as HTMLElement;
    const cells = within(row).getAllByRole("cell");
    expect(cells.slice(1, 3).map((cell) => cell.textContent)).toEqual(["3", "2"]);
    expect(row.textContent).toContain("[0.50, 0.90]");
  });

  it("show repeat runs only once they exist", () => {
    render(
      <EvaluationCharts
        level={{
          ...level,
          stability: [
            { condition: "SA-VER", items: 0 },
            { condition: "CREW-FULL", items: 8, fleiss_kappa: 0.9, flip_rate: 0.125 },
          ],
        }}
      />,
    );
    const rows = screen.getByTestId("stability");
    expect(rows.textContent).toContain("0.900");
    expect(within(rows).getAllByRole("listitem")).toHaveLength(1);
  });

  it("leave out what a level does not have", () => {
    const empty: LevelReport = { ...level, registered: [], systems: {} };
    render(<EvaluationCharts level={empty} />);
    expect(screen.queryByTestId("comparisons")).toBeNull();
    expect(screen.queryByTestId("confusion")).toBeNull();
  });
});
