# ADR-0004: Free LLM provider (NVIDIA API catalog)

- **Status:** accepted in principle (3 Nov 2026). The exact model IDs are fixed by the Part 2
  probe and recorded here before any test-set run.
- **Context:** The budget is $0. The local GPU (2 GB) cannot run useful models. Paid APIs are out.
- **Decision:**
  - **Provider:** NVIDIA's free API catalog at `https://integrate.api.nvidia.com/v1`, which uses
    the OpenAI request format, through a provider-agnostic `LLMClient`.
  - **Key:** one key in the local `.env`.
  - **Rate limit:** one shared limiter at 35 requests per minute, below the roughly 40 per minute
    per model that the free tier allows.
  - **No key or account rotation to evade limits.** Ask NVIDIA for an increase if needed.
  - **Primary candidate:** `nvidia/nemotron-3-super-120b-a12b`.
  - **Smaller same-family model** for the capability arm.
  - **Different-family model** for synthetic paraphrase.
- **Probe criteria** (development data only): at least 95% valid tool calls; at least 95%
  schema-valid output after one repair; a context window of at least 128K tokens; acceptable
  latency.
- **Consequences:**
  - Open-weight models make the study free for anyone to repeat.
  - Free endpoints may log inputs, which ADR-0003 handles through masking.
  - Throughput is limited by request rate, so the plan uses a request budget.
- **Results of the probe (to be filled in, Part 2):** —
