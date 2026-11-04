"use client";

import { ArrowRight, GitCompare, Loader, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiOffline, PageTitle, SyntheticBadge } from "@/components/ui";
import { api, ApiError, type Example, type Preview } from "@/lib/api";
import { useLoad, useStatus } from "@/lib/hooks";
import { CONDITION_LABEL } from "@/lib/vocabulary";

const PREVIEW_DELAY_MS = 250;
const CREW = "CREW-FULL";
const BASELINE = "SA-BASE";
const NO_MODEL = "RULES-ONLY";

const GROUPS: { title: string; conditions: string[] }[] = [
  { title: "Crew", conditions: ["CREW-FULL", "CREW-NV", "CREW-SHARE", "CREW-SILO"] },
  { title: "Single agent", conditions: ["SA-BASE", "SA-VER", "SA-SC5", "SA-MAX", "SA-LARGER"] },
  { title: "No model", conditions: ["RULES-ONLY"] },
];

const KIND_LABEL: Record<string, string> = {
  url: "Link",
  domain: "Website",
  email: "Email",
  phone: "Phone",
  whatsapp: "WhatsApp",
  telegram: "Telegram",
  social_handle: "Handle",
  iban: "IBAN",
  wallet: "Wallet",
  address: "Address",
};

function usePreview(text: string) {
  const [preview, setPreview] = useState<Preview | null>(null);
  useEffect(() => {
    if (!text.trim()) return;
    const abort = new AbortController();
    const timer = setTimeout(() => {
      api
        .preview(text, abort.signal)
        .then(setPreview)
        .catch(() => undefined);
    }, PREVIEW_DELAY_MS);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [text]);
  return text.trim() ? preview : null;
}

function ExamplePicker({
  examples,
  selected,
  onPick,
}: {
  examples: Example[];
  selected: string | null;
  onPick: (example: Example) => void;
}) {
  return (
    <div>
      <p className="eyebrow mb-2">Fictional examples</p>
      <ul className="flex flex-wrap gap-1.5">
        {examples.map((example) => (
          <li key={example.id}>
            <button
              type="button"
              aria-pressed={selected === example.id}
              title={example.text.slice(0, 120)}
              onClick={() => onPick(example)}
              className={`data h-7 cursor-pointer rounded-md border px-2 text-xs ${
                selected === example.id
                  ? "border-inform/60 bg-inform/15 text-inform"
                  : "border-line text-text-2 hover:border-line-strong hover:text-text"
              }`}
            >
              {example.id}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ContactChips({ preview }: { preview: Preview | null }) {
  if (!preview) {
    return <p className="text-sm text-text-3">Contact details appear here as you type.</p>;
  }
  if (preview.contact_points.length === 0) {
    return <p className="text-sm text-text-3">No contact details found yet.</p>;
  }
  return (
    <ul className="flex flex-wrap gap-1.5" data-testid="contact-chips">
      {preview.contact_points.map((point) => (
        <li
          key={`${point.kind}-${point.value}`}
          className="glass-thin flex items-center gap-1.5 rounded-lg! px-2 py-1 text-xs"
        >
          <span className="text-text-3">{KIND_LABEL[point.kind] ?? point.kind}</span>
          <span className="data break-all text-text" dir="auto">
            {point.value}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function Intake() {
  const router = useRouter();
  const status = useStatus();
  const examples = useLoad(api.examples);
  const [text, setText] = useState("");
  const [example, setExample] = useState<Example | null>(null);
  const [condition, setCondition] = useState(CREW);
  const [attested, setAttested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const preview = usePreview(text);

  const modelReady = status.data?.model_ready ?? true;
  const runnable = modelReady || condition === NO_MODEL;
  const synthetic = example !== null || attested;
  const ready = text.trim().length > 0 && synthetic && !busy;

  const pick = (chosen: Example) => {
    setExample(chosen);
    setText(chosen.text);
    setProblem(null);
  };

  const start = async (chosen: string) =>
    api.start({
      text,
      condition: chosen,
      channel: example?.channel,
      corpusItemId: example?.id,
    });

  const run = async (action: () => Promise<string>) => {
    setBusy(true);
    setProblem(null);
    try {
      router.push(await action());
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "The case could not start.");
      setBusy(false);
    }
  };

  const runOne = () =>
    run(async () => `/cases/${encodeURIComponent((await start(condition)).case_id)}`);

  const runBoth = () =>
    run(async () => {
      const [crew, baseline] = await Promise.all([start(CREW), start(BASELINE)]);
      return `/arena?a=${encodeURIComponent(crew.case_id)}&b=${encodeURIComponent(baseline.case_id)}`;
    });

  if (status.error) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10">
        <ApiOffline message={status.error.message} />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 py-6 lg:px-6">
      <PageTitle eyebrow="Intake" title="Give the crew an offer">
        Use a fictional example, or write a synthetic message of your own. Real messages are never
        used.
      </PageTitle>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <section className="glass flex flex-col gap-5 p-5" aria-label="The offer">
          {examples.data && (
            <ExamplePicker examples={examples.data} selected={example?.id ?? null} onPick={pick} />
          )}

          <div className="flex flex-1 flex-col">
            <label htmlFor="offer" className="eyebrow mb-2 flex items-center gap-2">
              Offer message <SyntheticBadge />
            </label>
            <textarea
              id="offer"
              dir="auto"
              className="field min-h-56 flex-1 resize-y p-4 leading-relaxed"
              maxLength={20_000}
              placeholder="Paste or write a clearly synthetic offer. Use .example domains and reserved numbers."
              value={text}
              onChange={(event) => {
                setText(event.target.value);
                setExample(null);
              }}
            />
          </div>

          {preview && preview.warnings.length > 0 && (
            <ul className="flex flex-col gap-1.5" role="alert" data-testid="pii-warnings">
              {preview.warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-2 text-sm text-challenge">
                  <TriangleAlert size={15} aria-hidden className="mt-0.5 shrink-0" />
                  {warning}
                </li>
              ))}
            </ul>
          )}

          <div aria-live="polite">
            <p className="eyebrow mb-2">Contact details found</p>
            <ContactChips preview={preview} />
          </div>
        </section>

        <section className="glass flex flex-col gap-4 p-5" aria-label="How to run it">
          <fieldset className="flex flex-col gap-3">
            <legend className="eyebrow mb-2">System</legend>
            {GROUPS.map((group) => (
              <div key={group.title}>
                <p className="mb-1 text-xs text-text-3">{group.title}</p>
                <div className="flex flex-col gap-1">
                  {group.conditions.map((value) => {
                    const available = modelReady || value === NO_MODEL;
                    const label = CONDITION_LABEL[value];
                    return (
                      <label
                        key={value}
                        className={`flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-1.5 ${
                          condition === value
                            ? "border-cma/50 bg-cma/10"
                            : "border-transparent hover:bg-white/5"
                        } ${available ? "" : "cursor-not-allowed opacity-50"}`}
                      >
                        <input
                          type="radio"
                          name="condition"
                          value={value}
                          disabled={!available}
                          checked={condition === value}
                          onChange={() => setCondition(value)}
                          className="mt-1 accent-[var(--color-cma)]"
                        />
                        <span>
                          <span className="block text-sm font-medium">{label?.name ?? value}</span>
                          {condition === value && (
                            <span className="block text-xs text-text-3">{label?.note}</span>
                          )}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
          </fieldset>

          {status.data && (
            <p className="text-xs text-text-3">
              Model: <span className="data text-text-2">{status.data.model.split("/").at(-1)}</span>
            </p>
          )}
          {!modelReady && <p className="text-sm text-challenge">{status.data?.not_ready_reason}</p>}

          {example ? (
            <p className="text-sm text-text-2">
              <span className="data">{example.id}</span> is a fictional item from the smoke set.
            </p>
          ) : (
            <label className="flex cursor-pointer items-start gap-2.5 text-sm text-text-2">
              <input
                type="checkbox"
                checked={attested}
                onChange={(event) => setAttested(event.target.checked)}
                className="mt-1 accent-[var(--color-cma)]"
              />
              This message is synthetic, and it holds no real person&apos;s details.
            </label>
          )}

          {problem && (
            <p className="text-sm text-challenge" role="alert">
              {problem}
            </p>
          )}

          <div className="flex flex-col gap-2">
            <button
              type="button"
              className="button button-primary h-11!"
              disabled={!ready || !runnable}
              onClick={() => void runOne()}
            >
              {busy ? <Loader size={16} className="animate-spin" aria-hidden /> : null}
              Run this case <ArrowRight size={16} aria-hidden />
            </button>
            <button
              type="button"
              className="button"
              disabled={!ready || !modelReady}
              onClick={() => void runBoth()}
            >
              <GitCompare size={15} aria-hidden /> Crew and single agent, side by side
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
