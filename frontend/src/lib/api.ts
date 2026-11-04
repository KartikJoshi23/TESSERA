/**
 * The local API. Everything from it is checked here, so a view can trust what it receives.
 * This client only ever talks to the machine it runs on (`tessera-api` binds to 127.0.0.1).
 */
import { z } from "zod";

export const API_BASE = process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8000";

export const sourceSchema = z.object({
  source_id: z.string(),
  name: z.string(),
  regulator: z.string(),
  as_of: z.string().nullable(),
  rows: z.number(),
  access_method: z.string(),
  automated_access: z.boolean(),
  deep_links_allowed: z.boolean(),
  restricted: z.boolean(),
  storage: z.string(),
  public_release: z.string(),
});
export type Source = z.infer<typeof sourceSchema>;

export const statusSchema = z.object({
  mode: z.string(),
  model: z.string(),
  model_ready: z.boolean(),
  not_ready_reason: z.string(),
  covered_regulators: z.array(z.string()),
  masked_values: z.number(),
  conditions: z.array(z.string()),
  sources: z.array(sourceSchema),
});
export type Status = z.infer<typeof statusSchema>;

const exampleSchema = z.object({
  id: z.string(),
  channel: z.string().nullable(),
  text: z.string(),
});
export type Example = z.infer<typeof exampleSchema>;

const caseSummarySchema = z.object({
  case_id: z.string(),
  condition: z.string().nullable(),
  result: z.string().nullable(),
  running: z.boolean(),
});
export type CaseSummary = z.infer<typeof caseSummarySchema>;

const previewSchema = z.object({
  contact_points: z.array(z.object({ kind: z.string(), value: z.string(), role: z.string() })),
  warnings: z.array(z.string()),
});
export type Preview = z.infer<typeof previewSchema>;

const startedSchema = z.object({ case_id: z.string(), warnings: z.array(z.string()) });

const chipSchema = z.object({
  evidence_id: z.string(),
  source: z.string(),
  kind: z.string(),
  as_of: z.string().nullable(),
  dated: z.string().nullable(),
  link: z.string().nullable(),
});
export type Chip = z.infer<typeof chipSchema>;

const ruleLine = z.object({ id: z.string(), text: z.string() });

export const reportSchema = z.object({
  result: z.string(),
  wording: z.string(),
  explanation: z.string(),
  hard_conflicts: z.array(ruleLine),
  unverified_reasons: z.array(ruleLine),
  claims: z.array(z.object({ text: z.string(), evidence: z.array(chipSchema) })),
  regulators: z.array(
    z.object({
      regulator: z.string(),
      relevance: z.string(),
      checked: z.boolean(),
      rationale: z.string(),
    }),
  ),
  sources: z.array(z.object({ source: z.string(), as_of: z.string().nullable() })),
  how_to_verify: z.array(z.object({ regulator: z.string(), link: z.string() })),
  disclaimer: z.string(),
  synthetic: z.boolean(),
  case_id: z.string(),
  condition: z.string(),
  mode: z.string(),
});
export type Report = z.infer<typeof reportSchema>;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function call(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError("The local API is not reachable.", 0);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = typeof body?.detail === "string" ? body.detail : response.statusText;
    throw new ApiError(detail, response.status);
  }
  return response.json();
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  status: async () => statusSchema.parse(await call("/api/status")),
  examples: async () => z.array(exampleSchema).parse(await call("/api/examples")),
  cases: async () => z.array(caseSummarySchema).parse(await call("/api/cases")),
  report: async (id: string) =>
    reportSchema.parse(await call(`/api/cases/${encodeURIComponent(id)}/report`)),
  trace: (id: string) => call(`/api/cases/${encodeURIComponent(id)}/trace`),
  preview: async (text: string, signal?: AbortSignal) =>
    previewSchema.parse(await call("/api/preview", { ...post({ text }), signal })),
  start: async (request: {
    text: string;
    condition: string;
    channel?: string | null;
    corpusItemId?: string;
  }) =>
    startedSchema.parse(
      await call(
        "/api/cases",
        post({
          text: request.text,
          synthetic: true,
          condition: request.condition,
          channel: request.channel ?? null,
          corpus_item_id: request.corpusItemId ?? null,
          // The person ticked the attestation for a message they wrote themselves.
          synthetic_attestation: !request.corpusItemId,
        }),
      ),
    ),
};

export const eventsUrl = (id: string): string =>
  `${API_BASE}/api/cases/${encodeURIComponent(id)}/events`;
