# ADR-0004: Free LLM provider (NVIDIA API catalog)

- **Status:** accepted in principle (3 Nov 2026). The exact model IDs are fixed by the Part 2
  probe and recorded here before any test-set run.
- **Context:** The budget is $0. The local GPU (2 GB) cannot run useful models. Paid APIs are out.
- **Decision:**
  - **Provider:** NVIDIA's free API catalog at `https://integrate.api.nvidia.com/v1`, which uses
    the OpenAI request format. Calls go directly through `httpx`, not the `openai` package, so
    the whole request path, with its leak checks, is in our code.
  - **Key:** one key in the local `.env`.
  - **Rate limit:** one shared limiter at 35 requests per minute, below the roughly 40 per minute
    per model that the free tier allows.
  - **No key or account rotation to evade limits.** Ask NVIDIA for an increase if needed.
  - **Primary candidate:** `nvidia/nemotron-3-super-120b-a12b`, with reasoning on through
    `chat_template_kwargs.enable_thinking` and a `reasoning_budget` of 4,096 tokens.
  - **Smaller same-family model** for the capability arm:
    `nvidia/nemotron-3.5-lightning-30b-a3b`.
  - **Different-family model** for synthetic paraphrase: `google/gemma-4-31b-it`.
  - **Every role and alternative** is in `policies/models.yaml`. IDs come from `/v1/models` on
    4 Nov 2026.
- **Probe criteria** (development data only): at least 95% valid tool calls; at least 95%
  schema-valid output after one repair; a context window of at least 128K tokens, read from the
  model card; acceptable latency. `tessera-probe` measures everything except the context window.
- **Consequences:**
  - Open-weight models make the study free for anyone to repeat.
  - Free endpoints may log inputs, which ADR-0003 handles through masking.
  - Throughput is limited by request rate, so the plan uses a request budget.
- **Terms:** the recheck on 4 Nov 2026 found no official terms page that could be read without
  an account, so the terms must be read when the key is created. The design assumes every
  request may be stored, whatever the terms say.
- **Results of the probe:** not run yet. It needs the key, and it must be recorded here before
  any test-set run.
