/**
 * The whole interface against the real local API, on the fictional world. Cases here run as
 * RULES-ONLY, which calls no model, so these tests send nothing to any provider.
 */
import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, expect, type Page, test } from "@playwright/test";
import recorded from "../src/lib/__fixtures__/worked-case.json" with { type: "json" };

const API = "http://127.0.0.1:8000";
const ROUTES = ["/", "/intake", "/arena", "/lab", "/governance"];

async function startCase(request: APIRequestContext, id = "S09"): Promise<string> {
  const examples = (await (await request.get(`${API}/api/examples`)).json()) as {
    id: string;
    text: string;
  }[];
  const example = examples.find((item) => item.id === id);
  const started = await request.post(`${API}/api/cases`, {
    data: {
      text: example?.text,
      synthetic: true,
      corpus_item_id: id,
      condition: "RULES-ONLY",
    },
  });
  expect(started.status()).toBe(202);
  return ((await started.json()) as { case_id: string }).case_id;
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  return errors;
}

test.describe("every view", () => {
  for (const route of ROUTES) {
    test(`${route} says what it is, and has no errors`, async ({ page }) => {
      const errors = collectErrors(page);
      await page.goto(route);
      await expect(page.getByTestId("research-badge")).toContainText(
        "INTERNAL RESEARCH PROTOTYPE · synthetic inputs only",
      );
      await expect(page.getByTestId("mode-badge")).toHaveText(/Research-internal|Restricted demo/);
      expect(errors).toEqual([]);
    });

    test(`${route} passes the accessibility checks`, async ({ page }) => {
      await page.goto(route);
      await page.getByTestId("mode-badge").filter({ hasNotText: "…" }).waitFor();
      const { violations } = await new AxeBuilder({ page }).analyze();
      expect(violations.map((item) => `${item.id}: ${item.nodes[0]?.html}`)).toEqual([]);
    });
  }
});

/** Serve the recorded crew case, so these tests see a real crew run without calling a model. */
async function openRecordedCase(page: Page, search = ""): Promise<void> {
  const body = recorded.events
    .map((event) => `id: ${event.seq}\ndata: ${JSON.stringify(event)}\n\n`)
    .join("");
  await page.route("**/api/cases/recorded/events*", (route) =>
    route.fulfill({ contentType: "text/event-stream", body }),
  );
  await page.goto(`/cases/recorded${search}`);
}

test.describe("a recorded crew case", () => {
  test("ends with the gate open and the result it reached", async ({ page }) => {
    await openRecordedCase(page);
    await expect(page.getByTestId("result-tile")).toHaveAttribute("data-result", "CONFLICTS");
    await expect(page.getByTestId("verifier-gate")).toHaveAttribute("data-stance", "open");
    await expect(page.getByRole("button", { name: /^Reconciler:/ })).toBeVisible();
  });

  test("shows the veto: the gate shuts and the proposal is cracked", async ({ page }) => {
    await openRecordedCase(page);
    await page.getByRole("button", { name: "Back to the start" }).click();
    await page.getByRole("button", { name: "Next conflict" }).click();
    await expect(page.getByTestId("conflict-link").first()).toHaveAttribute("data-status", "open");
    for (let press = 0; press < 3; press += 1) {
      await page.getByRole("button", { name: /^Next (conflict|veto)/ }).click();
    }
    await expect(page.getByTestId("verifier-gate")).toHaveAttribute("data-stance", "veto");
    await expect(page.getByTestId("proposal-crack")).toBeVisible();
    await expect(page.getByTestId("gate-G5")).toHaveAttribute("data-passed", "false");
    await expect(page.getByTestId("gate-G4")).toHaveAttribute("data-passed", "true");
    await expect(page.getByRole("status").filter({ hasText: "vetoed" })).toBeAttached();
  });

  test("the Verifier's report can be read in writing", async ({ page }) => {
    await openRecordedCase(page);
    await page.getByRole("button", { name: /^Verifier gate/ }).click();
    await expect(page.getByTestId("verdict")).toHaveCount(2);
    await expect(page.getByTestId("verdict").last()).toContainText("G5 failed");
  });

  test("shows a challenge, its answer, and the conflicts resolved", async ({ page }) => {
    await openRecordedCase(page);
    await page.getByRole("tab", { name: /Messages/ }).click();
    await expect(page.getByTestId("message-row").filter({ hasText: "CHALLENGE" })).toHaveCount(1);
    await page.getByRole("tab", { name: /Conflicts/ }).click();
    await expect(page.getByTestId("conflict-row")).toHaveCount(3);
    await expect(page.getByTestId("conflict-row").first()).toContainText("resolved");
  });

  test("selecting an agent shows that agent's own work", async ({ page }) => {
    await openRecordedCase(page);
    await expect(page.getByTestId("result-tile")).toHaveAttribute("data-result", "CONFLICTS");
    const everyone = await page.getByTestId("finding-row").count();
    expect(everyone).toBeGreaterThan(10);
    await page.getByRole("button", { name: /^VARA:/ }).click();
    await expect(page.getByTestId("finding-row")).not.toHaveCount(everyone);
    await page.getByRole("button", { name: "Show every agent" }).click();
    await expect(page.getByTestId("finding-row")).toHaveCount(everyone);
  });

  test("presenter mode clears the screen and follows the action", async ({ page }) => {
    await openRecordedCase(page, "?replay=1");
    await expect(page.getByTestId("finding-tile").first()).toBeVisible();
    await page.getByRole("button", { name: "Presenter mode" }).click();
    await expect(page.getByRole("region", { name: "Blackboard" })).toHaveCount(0);
    await expect(page.locator("svg.stage")).not.toHaveAttribute("viewBox", "0 0 1000 620");
  });

  test("shows placeholders where values were masked", async ({ page }) => {
    await openRecordedCase(page);
    await page.getByText("The offer, as the models saw it").click();
    await expect(page.getByTitle("Masked: no model ever saw this value").first()).toBeVisible();
    await expect(page.locator("body")).not.toContainText("Lumen Crest");
  });

  test("reports an event it cannot read", async ({ page }) => {
    const body = `data: ${JSON.stringify({ nonsense: true })}\n\n`;
    const end = `data: ${JSON.stringify({ case_id: "broken", type: "case.interrupted" })}\n\n`;
    await page.route("**/api/cases/broken/events*", (route) =>
      route.fulfill({ contentType: "text/event-stream", body: body + end }),
    );
    await page.goto("/cases/broken");
    await expect(page.getByText("Some events could not be read")).toBeVisible();
  });

  test("the result tile opens the dossier", async ({ page, request }) => {
    await page.goto(`/cases/${await startCase(request)}`);
    await page.getByRole("link", { name: /^Open the result: / }).click();
    await expect(page.getByTestId("result-hero")).toBeVisible();
  });
});

test.describe("a case's own views", () => {
  test("the theater passes the accessibility checks", async ({ page, request }) => {
    await page.goto(`/cases/${await startCase(request)}`);
    await expect(page.getByTestId("result-tile")).toHaveAttribute("data-result", "CONFLICTS");
    const { violations } = await new AxeBuilder({ page }).analyze();
    expect(violations.map((item) => `${item.id}: ${item.nodes[0]?.html}`)).toEqual([]);
  });

  test("the dossier passes the accessibility checks", async ({ page, request }) => {
    await page.goto(`/cases/${await startCase(request)}/result`);
    await expect(page.getByTestId("claim").first()).toBeVisible();
    const { violations } = await new AxeBuilder({ page }).analyze();
    expect(violations.map((item) => `${item.id}: ${item.nodes[0]?.html}`)).toEqual([]);
  });

  test("a rules-only case does not claim a model or a crew worked on it", async ({
    page,
    request,
  }) => {
    await page.goto(`/cases/${await startCase(request)}`);
    await expect(page.getByTestId("phase-caption")).toContainText("No model is involved");
    await expect(page.getByRole("button", { name: /^Rules:/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Jurisdiction:/ })).toHaveCount(0);
  });
});

test.describe("intake", () => {
  test("a fictional example runs to a result with evidence", async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto("/intake");
    await page.getByRole("button", { name: "S09", exact: true }).click();
    await expect(page.getByTestId("contact-chips")).toContainText("Website");
    await page.getByRole("radio", { name: /Rules only/ }).check();
    await page.getByRole("button", { name: "Run this case" }).click();

    await expect(page).toHaveURL(/\/cases\/case-/);
    await expect(page.getByTestId("result-tile")).toHaveAttribute("data-result", "CONFLICTS");
    await page.getByRole("link", { name: "Open the result", exact: true }).click();

    const hero = page.getByTestId("result-hero");
    await expect(hero).toHaveAttribute("data-result", "CONFLICTS");
    await expect(hero).toContainText("Conflicts with the official record");
    await expect(page.getByTestId("claim").first()).toBeVisible();
    await expect(page.getByTestId("disclaimer")).toContainText("not legal");
    expect(errors).toEqual([]);
  });

  test("a message of your own needs the attestation", async ({ page }) => {
    await page.goto("/intake");
    await page.getByLabel(/Offer message/).fill("Join falconridge.example for steady returns.");
    await page.getByRole("radio", { name: /Rules only/ }).check();
    const run = page.getByRole("button", { name: "Run this case" });
    await expect(run).toBeDisabled();
    await page.getByRole("checkbox").check();
    await expect(run).toBeEnabled();
  });

  test("warns about what looks like a real person's data", async ({ page }) => {
    await page.goto("/intake");
    await page.getByLabel(/Offer message/).fill("Pay with card 4111 1111 1111 1111 today.");
    await expect(page.getByTestId("pii-warnings")).toContainText("payment card");
  });

  test("leaves real messages out of any example", async ({ request }) => {
    const refused = await request.post(`${API}/api/cases`, {
      data: { text: "A message", synthetic: false, condition: "RULES-ONLY" },
    });
    expect(refused.status()).toBe(422);
  });
});

test.describe("the theater", () => {
  test("opens a finished case at its end", async ({ page, request }) => {
    const id = await startCase(request);
    await page.goto(`/cases/${id}`);
    await expect(page.getByTestId("result-tile")).toHaveAttribute("data-result", "CONFLICTS");
    await expect(page.getByTestId("finding-tile").first()).toBeVisible();
    await expect(page.getByLabel("Position in the case")).toHaveAttribute("value", /\d+/);
  });

  test("replays from the start, and can be paused and stepped", async ({ page, request }) => {
    const id = await startCase(request);
    await page.goto(`/cases/${id}?replay=1`);
    await expect(page.getByTestId("finding-tile").first()).toBeVisible();
    await expect(page.getByTestId("result-tile")).toHaveAttribute("data-result", "");

    await page.getByRole("button", { name: "Pause" }).click();
    const scrubber = page.getByLabel("Position in the case");
    const before = Number(await scrubber.inputValue());
    await page.getByRole("button", { name: "One event forward" }).click();
    await expect(scrubber).toHaveValue(String(before + 1));
    await page.getByRole("button", { name: "One event back" }).click();
    await expect(scrubber).toHaveValue(String(before));

    await page.getByRole("button", { name: "To the end" }).click();
    await expect(page.getByTestId("result-tile")).toHaveAttribute("data-result", "CONFLICTS");
  });

  test("the timeline works from the keyboard", async ({ page, request }) => {
    const id = await startCase(request);
    await page.goto(`/cases/${id}`);
    const scrubber = page.getByLabel("Position in the case");
    await expect(page.getByTestId("result-tile")).toHaveAttribute("data-result", "CONFLICTS");
    await scrubber.focus();
    const end = Number(await scrubber.inputValue());
    await page.keyboard.press("ArrowLeft");
    await expect(scrubber).toHaveValue(String(end - 1));
    await expect(page.getByTestId("result-tile")).toHaveAttribute("data-result", "");
  });

  test("clicking a tile opens its finding in writing", async ({ page, request }) => {
    const id = await startCase(request);
    await page.goto(`/cases/${id}`);
    const tile = page.getByTestId("finding-tile").first();
    const finding = await tile.getAttribute("data-finding");
    await tile.dispatchEvent("click");
    const row = page
      .getByTestId("finding-row")
      .filter({ has: page.getByText(finding ?? "", { exact: true }) });
    await expect(row.getByRole("button")).toHaveAttribute("aria-expanded", "true");
  });

  test("stays still for someone who asks for less motion", async ({ browser, request }) => {
    const id = await startCase(request);
    const context = await browser.newContext({ reducedMotion: "reduce" });
    const page = await context.newPage();
    await page.goto(`http://localhost:3000/cases/${id}?replay=1`);
    await expect(page.getByTestId("finding-tile").first()).toBeVisible();
    await context.close();
  });

  test("says so when a case does not exist", async ({ page }) => {
    await page.goto("/cases/no-such-case");
    await expect(page.getByText("This case could not be opened")).toBeVisible();
  });
});

test.describe("the arena", () => {
  test("puts two cases side by side and compares what they spent", async ({ page, request }) => {
    const a = await startCase(request, "S09");
    const b = await startCase(request, "S01");
    await page.goto(`/arena?a=${a}&b=${b}`);
    await expect(page.getByTestId("arena-result")).toHaveCount(2);
    await expect(page.getByTestId("arena-result").first()).toContainText("Conflicts with");
    await expect(page.getByTestId("arena-result").last()).toContainText("Consistent with");
    await expect(page.getByRole("table", { name: /same measures/ })).toContainText("Tool calls");
    await expect(page.getByTestId("claim-difference")).toContainText("Both");
  });
});

test.describe("the lab", () => {
  test("keeps the two levels of evaluation on separate tabs", async ({ page }) => {
    await page.goto("/lab");
    await page.getByRole("tab", { name: /Entity-level/ }).click();
    await expect(page.getByRole("tabpanel")).toContainText("no results yet");
    await page.getByRole("tab", { name: /Message-level/ }).click();
    await expect(page.getByRole("tabpanel")).toContainText("no results yet");
  });

  test("marks the smoke numbers as development only", async ({ page }) => {
    await page.goto("/lab");
    await page.getByRole("tab", { name: /Development/ }).click();
    await expect(page.getByTestId("smoke-results")).toContainText("Development numbers only");
  });
});

test.describe("the DFSA rules", () => {
  test("every link to the DFSA goes to its homepage", async ({ page, request }) => {
    const id = await startCase(request);
    await page.goto(`/cases/${id}/result`);
    await expect(page.getByTestId("claim").first()).toBeVisible();
    const links = await page
      .locator("a[href]")
      .evaluateAll((items) => items.map((item) => (item as HTMLAnchorElement).href));
    const dfsa = links.filter((link) => new URL(link).hostname.endsWith("dfsa.ae"));
    expect(dfsa.length).toBeGreaterThan(0);
    for (const link of dfsa) expect(new URL(link).pathname).toBe("/");
  });

  test("the governance page states the restriction", async ({ page }) => {
    await page.goto("/governance");
    await expect(page.getByRole("region", { name: "DFSA material" })).toContainText(
      "homepage",
    );
  });

  test("no API response may be cached", async ({ request }) => {
    const response = await request.get(`${API}/api/status`);
    expect(response.headers()["cache-control"]).toBe("no-store");
  });

  test("demo mode shows as such and offers no restricted source", async ({ page }) => {
    await page.route("**/api/status", async (route) => {
      const response = await route.fetch();
      const body = (await response.json()) as { sources: { restricted: boolean }[] };
      await route.fulfill({
        response,
        json: {
          ...body,
          mode: "RESTRICTED_DEMO",
          sources: body.sources.filter((source) => !source.restricted),
        },
      });
    });
    await page.goto("/governance");
    await expect(page.getByTestId("mode-badge")).toHaveText("Restricted demo");
    await expect(page.getByTestId("source-card").first()).toBeVisible();
    await expect(page.getByTestId("source-card").filter({ hasText: "DFSA" })).toHaveCount(0);
  });
});

test.describe("smaller screens", () => {
  for (const [name, width, height] of [
    ["laptop", 1280, 720],
    ["tablet", 820, 1100],
    ["phone", 390, 844],
  ] as const) {
    test(`nothing runs off the side of a ${name}`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      for (const route of ROUTES) {
        await page.goto(route);
        await page.getByTestId("mode-badge").filter({ hasNotText: "…" }).waitFor();
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect([route, overflow]).toEqual([route, 0]);
      }
    });
  }
});

test.describe("when the API is away", () => {
  test("says what to do", async ({ page }) => {
    await page.route("**/api/**", (route) => route.abort());
    await page.goto("/intake");
    await expect(page.getByText("The local API is not answering")).toBeVisible();
    await expect(page.getByTestId("mode-badge")).toHaveText("API offline");
  });
});
