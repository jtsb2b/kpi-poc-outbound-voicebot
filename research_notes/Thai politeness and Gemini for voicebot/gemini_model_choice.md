# Gemini model choice for the real-time Thai voicebot LLM

Researched 2026-10-19. Workload: replies of about 30-120 output tokens, prompts of about 5-7k tokens (mostly a static system prompt plus the knowledge base), Thai politeness matters, servers in Bangkok. Reply latency matters most.
No API keys were used and nothing was measured locally. Every figure below comes from published sources, with the date given.

## 1. Current lineup (Gemini API models page, read 2026-10-19)

| Model | Exact ID | Status | Released | Notes |
|---|---|---|---|---|
| Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | **Stable / GA** | 2026-07-21 | Default thinking level is **minimal**. Not deprecated. Vertex retirement is no earlier than 2027-07-21 |
| Gemini 3.6 Flash | `gemini-3.6-flash` | Stable | 2026-07-21 | Default thinking level is medium. **Supports `minimal`** |
| Gemini 3.8 Flash | `gemini-3.8-flash` | Stable (new) | ~Sep 2026 | Lowest thinking level is `low`. **`minimal` returns an error** |
| Gemini 3.1 Flash-Lite | `gemini-3.1-flash-lite` | Stable | 2026-05-07 | Shuts down 2027-05-07. Replacement is 3.5 Flash-Lite |
| Gemini 3 Flash | `gemini-3-flash-preview` | Preview | 2025-12-17 | Legacy |
| Gemini 4 Argon | `gemini-4-argon` | Stable | — | Pro-class. Lowest thinking level is `low`. Not on the free tier. Too slow and expensive for this use |
| Gemini 3.5 Flash / 3.7 Flash | `gemini-3.5-flash`, `gemini-3.7-flash` | Superseded | May / Aug 2026 | The endpoints automatically route to 3.6 Flash and 3.8 Flash respectively |
| Gemini 2.5 Flash / Flash-Lite | `gemini-2.5-flash(-lite)` | Legacy | 2025 | Only accounts that used them recently can call them. Google recommends "3.5 Flash-Lite or 3.8 Flash" for new projects |

**The user's "Gemini 3.5 flash lite":** it exists and is GA. The exact ID is `gemini-3.5-flash-lite`, with no `-preview` suffix and no date suffix.

## 2. Comparison of the candidates

| | **3.5 Flash-Lite** | 3.6 Flash | 3.8 Flash | 3.1 Flash-Lite |
|---|---|---|---|---|
| Lowest thinking level | **minimal (the default)** | minimal | low (no minimal) | (n/a, being retired) |
| Time to first token, independent single-run test (mpgone, July/Oct 2026, free tier) | **0.72 s** | 8.55 s (default medium) | 4.49 s low / 7.71 s medium / 13.3 s high | — |
| Artificial Analysis, 10k input, AI Studio, 72 h median (read 2026-10-19) | 456 tok/s; 7.41 s to first answer token (run as the "reasoning" variant, i.e. thinking was on) | ~220 tok/s; 15.5 s (High) | ~305 tok/s; 13.4 s (High) | — |
| AA Intelligence Index | 22 | 34 (High) | — | — |
| Price per 1M tokens, input / output (standard paid) | $0.30 / $2.50 | $0.75 / $3.75 until 2026-12-31, then **$1.50 / $7.50** | same as 3.6 Flash | $0.25 / $1.50 |
| Cached input per 1M | $0.03 (90% off) | $0.075, then $0.15 | same | $0.025 |
| Priority tier, input / output | $0.54 / $4.50 | $1.35 / $6.75 | same | $0.45 / $2.70 |
| Structured output, function calling, caching | yes / yes / implicit + explicit | yes | yes | yes |
| Live API | no | no | no | no |
| Vertex in asia-southeast1 | listed (locations page), **but the model page omits it** (see section 5) | yes | yes | yes |

How to read the latency numbers: Artificial Analysis benchmarks with thinking turned up (High / "reasoning"), so its first-token figures mostly measure thinking time. They do not show what a voice turn at minimal thinking would see. Its own comparison page puts the closely related **Gemini 3.5 Flash (minimal) at 0.82 s TTFT, ~200 tok/s**, which is in line with the 0.72 s single-run figure for Flash-Lite. With thinking off or minimal, Gemini Flash-class first tokens are sub-second. With it on, they take 4-15 s, which is unusable for voice.

Rough per-turn arithmetic for 3.5 Flash-Lite at minimal thinking: TTFT of ~0.5-0.8 s, then 100 tokens at ~400 tok/s ≈ 0.25 s, so the full reply is ready in about 1 s. TTS can start on the first clause well before that.

## 3. Thinking settings
- Gemini 3.x uses `thinking_level` (`minimal` / `low` / `medium` / `high`). The current docs no longer document `thinking_budget` for 3.x. None of the 3.x Flash models has a documented "off". `minimal` is the floor.
- Thinking tokens are billed as output and count against `max_output_tokens`. If the cap is hit while the model is thinking, the reply can come back empty. **Never set `max_output_tokens` close to the reply length** while thinking is on. At minimal it is near zero, but leave headroom anyway (e.g. 512).
- Vertex warns that minimal thinking "can cause premature tool termination on multi-step tasks." Keep each voice turn to at most one function call, or move multi-step tool chains off the hot path.
- **Breaking change on 3.5 Flash-Lite (Vertex model page, updated 2026-10-16):** custom `temperature`, `top_k` and `top_p` are *ignored*, custom frequency or presence penalties *cause an error*, and a request whose last turn is a `model` turn is *rejected*. Remove any temperature tuning and any assistant-prefill tricks.

## 4. Context caching for the static ~5-7k-token prefix
- Implicit caching is on by default for Gemini 2.5 and later. Put the static system prompt and knowledge base **first and byte-identical** on every turn, and append the per-call variables (customer name, time, transcript) after it. Check hits via the usage field for cached tokens (`total_cached_tokens` / `cached_content_token_count`).
- The minimum prefix size for implicit caching is 4,096 tokens on 3.6 Flash and 3.8 Flash. **The docs give no minimum for 3.5 Flash-Lite** (unverified). A 5-7k prefix should clear any likely threshold.
- Cached tokens cost 10% of the input price on Flash-Lite (80-90% off elsewhere). **Google publishes no latency benefit.** Expect the cost saving and possibly some prefill saving, and measure it.
- Explicit caches exist for 3.x Flash through generateContent (storage $1.00 per 1M tokens per hour on Flash-Lite). The Interactions API does not support them. For one static prompt with steady call volume, implicit caching is enough.

## 5. Deployment from Bangkok
- **Gemini API (AI Studio key):** the simplest option. The paid tier does **not** use prompts or responses to improve products, while the free tier does. **Do not use the free tier with real customer data.** There is no region pinning or data-residency guarantee.
- **Vertex AI**, now branded "Gemini Enterprise Agent Platform" in the docs. Last-updated 2026-10-15/16.
  - Google Cloud's Bangkok region `asia-southeast3` launched 2026-01-21, but **no Gemini models are listed there**. The generative-AI locations page names only Mumbai, Singapore, Hong Kong, Taiwan, Tokyo, Sydney and Seoul in APAC.
  - The locations page lists 3.5 Flash-Lite, 3.6 Flash and 3.8 Flash in `asia-southeast1` (Singapore) and on `global`.
  - **Conflict:** the 3.5 Flash-Lite model page lists availability as `global`, `us`, `eu` and `asia-south1` only, with Standard PayGo on `global`, `us` and `eu`. Check the Cloud console before relying on Singapore.
  - The `global` endpoint gives no residency guarantee and no control over processing location. It does reduce 429 errors.
  - Vertex offers Provisioned Throughput, the Priority tier, CMEK and VPC-SC, and is the better fit if KPI requires PDPA-style controls.
- Network: Bangkok to Singapore is typically about 25-35 ms RTT (general knowledge, not measured here). That is small next to model TTFT. The AI Studio endpoint location is not published (unverified).

## 6. Thai quality and instruction following
- **No published Thai-specific benchmark covers any Gemini 3.x model.** The SEA-HELM leaderboard (2026-09-18) lists open-weights models only. No ThaiExam, Global-MMLU or MMMLU figure exists for 3.5 Flash-Lite. The 3.1 Flash-Lite model card gave MMMLU 88.9% (as of Mar 2026), which is a different model.
- The 3.5 Flash-Lite card (2026-07-21) shows large gains over 3.1 Flash-Lite on agentic and long-context benchmarks, e.g. GDPVal-AA 1140 vs 642 and MRCR-128k 72% vs 60%. The 3.6 Flash card is clearly stronger again (GDPVal 1421, MRCR 92%).
- In practice, Flash-Lite is generally good enough for short, KB-grounded, polite Thai replies, but it is weaker on nuance: register (ค่ะ/คะ), hedging, and following many prompt rules at once. **Run our own Thai eval** with real transcripts, scoring politeness particles, female self-reference (ดิฉัน/หนู/น้องเคพีไอ), no Latin script for JAI TTS, KB faithfulness, and Thai clock reading. Run it on both 3.5 Flash-Lite at minimal and 3.6 Flash at minimal.

## 7. Structured output and function calling
- All candidates support JSON-schema structured output (`response_schema` / `response_json_schema`), which the docs describe as "syntactically correct JSON". Constrained decoding is not stated. Still validate the values.
- Streaming structured output arrives as partial JSON chunks. **For voice, avoid wrapping the spoken reply in JSON.** It delays TTS until the field is parsed. Stream plain text, and put any control signals (end call, hand off, intent) in a function call or a short trailing tag.
- Combining structured output with tools is **Preview** on Gemini 3.

## 8. Gemini Live / native audio (context only)
- `gemini-3.8-live` (Stable) and `gemini-3.8-live-extended-thinking` replace the legacy `gemini-3.1-flash-live-preview`. Pricing: $0.75 text input, $3.00 audio input, $12.00 audio output per 1M tokens (≈ $0.005/min in, $0.018/min out).
- Live does speech-to-speech in "70 languages" (Thai not explicitly confirmed on the page) and supports function calling.
- Using Live would bypass the Soniox STT, JAI TTS and approved-voice pipeline, and the voice identity of น้องเคพีไอ. It is out of scope for this pipeline. Worth a separate spike only if end-to-end latency becomes the blocker.

## 9. Recommendation

**Primary: `gemini-3.5-flash-lite`** (GA), via Vertex AI on `global` or `asia-southeast1` if the console confirms it, or via a paid-tier Gemini API key for the PoC.

```
model:              gemini-3.5-flash-lite
thinking_level:     minimal          # the default; set explicitly
stream:             true             # generateContent streaming / streamGenerateContent
max_output_tokens:  512              # headroom; let the prompt keep replies short
temperature/top_p:  do not set       # ignored on 3.5 Flash-Lite
system_instruction: static prompt + KB, identical bytes every turn (implicit cache)
per-turn vars:      appended after the static prefix
last turn:          must be a user turn (no assistant prefill)
tools:              at most one function call per turn; no JSON-wrapped speech
service tier:       Standard; consider Priority if p95 TTFT is noisy under load
```

**Fallback / quality tier: `gemini-3.6-flash` with `thinking_level: minimal`.** Use it if the Thai eval shows Flash-Lite slipping on politeness or KB faithfulness. Expect a slower TTFT, roughly 0.8-1 s judging by the related 3.5 Flash (minimal) figure. Its price doubles on 2027-01-01 to $1.50 / $7.50.

**Avoid for the live turn:** `gemini-3.8-flash` and `gemini-4-argon`. They cannot go below `low` thinking, which means multi-second TTFT. Avoid `gemini-3.1-flash-lite` and anything marked `-preview` too, because of retirement and stability risk.

Before committing, measure TTFT p50/p95 from the Bangkok host with streaming and a realistic 6k-token cached prefix, comparing AI Studio, Vertex `global` and Vertex `asia-southeast1`.

## Unverified / flagged
- Vertex Singapore availability for 3.5 Flash-Lite: the locations page and the model page disagree.
- The implicit-cache minimum for 3.5 Flash-Lite is not documented. Caching has no published latency effect.
- No published TTFT for 3.5 Flash-Lite at *minimal* from a rigorous benchmark. The 0.72 s figure is a single free-tier run.
- No Thai benchmark exists for any Gemini 3.x model.
- Artificial Analysis mentions a "Gemini 3.7 Flash" successor to 3.6 Flash, but Google's deprecations page routes 3.7 to 3.8 Flash. 3.6 Flash itself has no announced shutdown.

## Sources
- Gemini API models: https://ai.google.dev/gemini-api/docs/models
- 3.5 Flash-Lite page: https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite (updated 2026-07-30)
- 3.8 Flash page: https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash (updated 2026-09-02)
- 3.6 Flash page: https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash
- Thinking: https://ai.google.dev/gemini-api/docs/thinking
- Pricing: https://ai.google.dev/gemini-api/docs/pricing
- Caching: https://ai.google.dev/gemini-api/docs/caching
- Structured output: https://ai.google.dev/gemini-api/docs/structured-output
- Deprecations: https://ai.google.dev/gemini-api/docs/deprecations
- Live API: https://ai.google.dev/gemini-api/docs/live
- Vertex 3.5 Flash-Lite: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite (updated 2026-10-16)
- Vertex locations: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations (updated 2026-10-15)
- Bangkok region launch: https://cloud.google.com/blog/products/infrastructure/google-cloud-launches-new-region-in-bangkok-thailand
- Model cards: https://deepmind.google/models/model-cards/gemini-3-5-flash-lite/ , https://deepmind.google/models/model-cards/gemini-3-6-flash/
- Artificial Analysis: https://artificialanalysis.ai/models/gemini-3-5-flash-lite/providers , https://artificialanalysis.ai/models/gemini-3-6-flash , https://artificialanalysis.ai/models/gemini-3-8-flash/providers , https://artificialanalysis.ai/models/comparisons/gemini-3-5-flash-lite-vs-gemini-3-5-flash-minimal
- Independent TTFT test: https://mpgone.com/gemini-3-6-flash/
- SEA-HELM: https://leaderboard.sea-lion.ai/
