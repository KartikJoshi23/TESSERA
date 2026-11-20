# ADR-0004: Free LLM provider (NVIDIA API catalog)

- **Status:** accepted (3 Nov 2026). Models chosen by measurement on 4 Nov 2026, below.
- **Context:** The budget is $0. The local GPU (2 GB) cannot run useful models. Paid APIs are out.
- **Decision:**
  - **Provider:** NVIDIA's free API catalog at `https://integrate.api.nvidia.com/v1`, which uses
    the OpenAI request format. Calls go directly through `httpx`, not the `openai` package, so
    the whole request path, with its leak checks, is in our code.
  - **Key:** one key in the local `.env`.
  - **Rate limit:** one shared limiter at 4 requests per minute. The free tier is said to allow
    about 40, but steady no-retry probes on 5 Nov 2026 sustained under 4, whatever the prompt size.
    Sent for six minutes each: 6 a minute, 3.8 passed; 4.5, 3.7; 3.75, 2.9; 3, 2.9. An earlier
    probe of one minute at each pace read about 8, because a first burst of about that size hides
    the sustained rate. Some requests are refused at any pace, so the limiter sits just above what
    passes and retries those.
  - **No key or account rotation to evade limits.** Ask NVIDIA for an increase if needed, but do
    not plan on one.
  - **Primary:** `nvidia/nemotron-3.5-super-vl-120b-a12b`, with reasoning on through
    `chat_template_kwargs.enable_thinking`. It reasons by default, and this setting states that
    explicitly so that a change of default cannot alter a run unnoticed. Every condition uses it.
  - **Smaller same-family model** for the capability arm:
    `nvidia/nemotron-3.5-lightning-30b-a3b`.
  - **Different-family model** for synthetic paraphrase: `google/gemma-4-31b-it`, since
    20 Nov 2026. It replaced `mistralai/mistral-large-4-1t-a52b`; see the section at the end.
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

## Reasoning on or off, measured on 5 Nov 2026

The same fictional development cases, one setting at a time, in one sitting.

| Run | Matched the label | Requests | Refused (HTTP 429) | Output tokens a case |
|---|---|---|---|---|
| Crew, reasoning on | 10 of 11 | 145 | 63 | 28,880 |
| Crew, reasoning off | 10 of 11 | 202 | 160 | 3,596 |
| Single agent, reasoning on | 25 of 25 | 136 | 38 | 19,036 |
| Single agent, reasoning off | 24 of 25 | 226 | 175 | 1,769 |

Reasoning stays on. It is the registered default, it never scored lower, and tokens are not what
this free tier limits. The one exception, in every condition, is that a reply that holds no answer, cut
off at its output limit or not, is repaired with reasoning off, since reasoning that ended without
an answer would only do so again. The crew's one miss with it on was a bug, since fixed: a model's label on an
alert found only by domain. Its one miss with it off came from the Verifier's own reading.

The request gap overstates the case. Most of it came from repeated tool calls, which the runner now
stops for every condition, so it says little about reasoning itself. These are development cases,
and they say nothing about final performance.

## The paraphrase model, changed on 20 Nov 2026

The paraphrase step sat for an hour and three quarters and produced nothing. Mistral had begun to
reason for over 8,000 characters and spend all 2,000 tokens before writing a word, about 150 seconds
a reply. Its reasoning switch, `chat_template_kwargs.enable_thinking`, was ignored, and
`reasoning_effort` was refused with HTTP 400. The registered alternative,
`deepseek-ai/deepseek-v4.1-flash`, reached its end of life on 16 Nov 2026 and returns HTTP 410.

The same paraphrase requests, four each, paced at 4 a minute with the real 360-second timeout:

| Model | Finished | Kept every required string | Kept the service | Time |
|---|---|---|---|---|
| `google/gemma-4-31b-it` | 4 of 4 | 4 of 4 | 4 of 4 | 82 to 107 s, about 40 tokens each |
| `mistralai/mistral-large-4-1t-a52b`, 6,000 tokens | 0 of 4 | - | - | Timed out or dropped at 340 to 360 s |

In single tries, `minimaxai/minimax-m3.1-flash` answered in 9 seconds but changed the look-alike
domain it was told to keep, which changes the right answer, and `z-ai/glm-5.3-flash` did not answer
within 170 seconds.

Gemma is a different family from the model under test, as decision D6 asks, and the plan names it
as an example. It does not reason, so nothing is spent before the text. Most of its time is spent in
the provider's queue, so paraphrases now run four at a time under the shared rate limit.

