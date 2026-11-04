# ADR-0004: Free LLM provider (NVIDIA API catalog)

- **Status:** accepted (3 Nov 2026). Models chosen by measurement on 4 Nov 2026, below.
- **Context:** The budget is $0. The local GPU (2 GB) cannot run useful models. Paid APIs are out.
- **Decision:**
  - **Provider:** NVIDIA's free API catalog at `https://integrate.api.nvidia.com/v1`, which uses
    the OpenAI request format. Calls go directly through `httpx`, not the `openai` package, so
    the whole request path, with its leak checks, is in our code.
  - **Key:** one key in the local `.env`.
  - **Rate limit:** one shared limiter at 35 requests per minute, below the roughly 40 per minute
    per model that the free tier allows.
  - **No key or account rotation to evade limits.** Ask NVIDIA for an increase if needed, but do
    not plan on one.
  - **Primary:** `nvidia/nemotron-3.5-super-vl-120b-a12b`, with reasoning on through
    `chat_template_kwargs.enable_thinking`. It reasons by default, and this setting states that
    explicitly so that a change of default cannot alter a run unnoticed.
  - **Smaller same-family model** for the capability arm:
    `nvidia/nemotron-3.5-lightning-30b-a3b`.
  - **Different-family model** for synthetic paraphrase: `mistralai/mistral-large-4-1t-a52b`.
    Part 6 confirms this one.
  - **Every role and alternative** is in `policies/models.yaml`.
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
- **What this account can reach (4 Nov 2026).** The key is for the account, not for a model.
  NVIDIA listed 85 models for it, but listing does not mean a model is served. One short request
  to each candidate, with no retries:

  | Model | Result |
  |---|---|
  | `nvidia/nemotron-3.5-super-vl-120b-a12b` | Answers in 0.3 s |
  | `nvidia/nemotron-3.5-lightning-30b-a3b` | Answers in 0.5 s |
  | `nvidia/nemotron-3-ultra-550b-a55b` | Answers in 1.7 s |
  | `mistralai/mistral-large-4-1t-a52b` | Answers in 2.5 s |
  | `deepseek-ai/deepseek-v4.1-flash` | Answers in 51.5 s |
  | `nvidia/nemotron-3-super-120b-a12b` (the planned primary) | HTTP 404, not found for this account |
  | `moonshotai/kimi-k2.6`, `nvidia/nemotron-nano-3-30b-a3b` | HTTP 404, not found for this account |
  | `google/gemma-4-31b-it`, `openai/gpt-oss-20b`, `z-ai/glm-5.3-flash` | No answer within 90 s |

- **Results of the probe (4 Nov 2026).** 20 tool-calling and 20 structured-output trials per
  model, on fictional text:

  | Model | Valid tool calls | Used the result | Valid JSON, first try | After repair | Median |
  |---|---|---|---|---|---|
  | `nvidia/nemotron-3.5-super-vl-120b-a12b` | 20/20 | 20/20 | 20/20 | 20/20 | 2.0 s |
  | `nvidia/nemotron-3.5-lightning-30b-a3b` | 20/20 | 20/20 | 20/20 | 20/20 | 5.3 s |

  Both pass. For the primary model, the model card's specifications give a context length of
  262,144 tokens (its description says up to 1M), which clears the 128K bar, and its weights are
  public under the OpenMDW License. Run the probe once more before any test-set run: the models
  an account can reach can change.
