# Hybrid flow + LLM phrasing: keeping a deterministic business flow while sounding natural

Scope: architectures and prompt/guardrail patterns where a state machine decides and an LLM interprets replies and (optionally) rephrases bot lines. Target: regulated Thai insurance outbound phone bot (self-hosted Qwen 3.8 Flash, json_schema output, ~0.5 s). Research date: 2026-10-08. Most sources are vendor docs (mechanism descriptions, not independent evidence); quantitative evidence is sparse and flagged.

## 1. Rasa CALM: dialogue understanding + flows + Contextual Response Rephraser + conversation repair

### Takeaway
CALM is the most explicit published version of "LLM understands, deterministic logic decides": the LLM outputs only a small fixed command vocabulary (1-3 commands per turn), flows execute deterministically, and a rephraser is an opt-in, per-response LLM rewrite of templates whose documented risk is meaning drift. Repair cases (correction, cancel, chitchat, cannot-handle, clarify, repeat, skip, silence) are built-in "patterns" (meta-flows) that developers override.

### Cited Findings
- Architecture: the LLM maps conversation to a domain-specific language of commands that advances business logic, which is "deterministically" executed; commands can set slots and push flows but cannot remove or modify existing flows — [Bocklisch et al., Task-Oriented Dialogue with In-Context Learning (arXiv 2402.12234)](https://arxiv.org/html/2402.12234)
- Command set: StartFlow, CancelFlow, SetSlot, (CorrectSlot), ChitChat, KnowledgeAnswer, HumanHandoff, Clarify(flow1, flow2...), Error; output is typically 1-3 commands; the fine-tuned command generator "cannot be used to generate arbitrary text" — [Rasa HF model card](https://huggingface.co/rasa/cmd_gen_llama_3.1_8b_calm_demo); [arXiv 2402.12234](https://arxiv.org/html/2402.12234)
- Rasa warns that if you rename/replace built-in commands it cannot guarantee the same accuracy (they test a fixed command set) — [Rasa command generator docs](https://rasa.com/docs/pro/customize/command-generator)
- Measured result (GPT-4, 71 test conversations, authors' own benchmark): pass rate 95.8% vs 47.9% for an intent-based baseline; corrections 13/13 vs 0/13; negations 3/3 vs 0/3; digressions 9/9 vs 2/9; cancellations 6/6 vs 2/6; disambiguation 3/4 vs 0/4; input validation 3/5 vs 3/5; happy path 24/24 vs 22/24. Limitations stated by authors: relative comparison, no user study, tests paths not lexical variety, GPT-4 only, multilingual untested — [arXiv 2402.12234](https://arxiv.org/html/2402.12234)
- CALM is optimized for smaller fine-tuned models (e.g., Llama 3.1 8B) to reduce latency and inference cost; Rasa publishes 8B and 13B fine-tuned command generators — [Rasa HF model card](https://huggingface.co/rasa/cmd_gen_llama_3.1_8b_calm_demo); [Rasa blog on small-LLM rephrasing](https://rasa.com/blog/contextual-rephrasing-with-small-llms)
- Rephraser mechanism: an LLM rewrites a static template using conversation context; flow logic is unchanged. Prompt inputs: `history`, `current_input`, `suggested_response` — [Rasa rephraser docs](https://rasa.com/docs/reference/primitives/contextual-response-rephraser/)
- Rephraser control: off by default; opt in per response with `metadata: rephrase: True`, or globally `rephrase_all: true` with per-response `rephrase: False` exclusions; per-response custom `rephrase_prompt`; default temperature 0.3 (docs call 2.0 too high); history either summarized (extra LLM call per turn) or transcript mode (`summarize_history: False`, last `max_historical_turns`, default 5) — [Rasa rephraser docs](https://rasa.com/docs/reference/primitives/contextual-response-rephraser/)
- Documented rephraser risks: the LLM "may change a message's meaning" rather than paraphrase; structure (e.g., bullets) can be lost; user text in the prompt enables prompt injection (adversarial testing recommended); slot values are not included in the prompt by default. No built-in fact-check guardrail is documented — [Rasa rephraser docs](https://rasa.com/docs/reference/primitives/contextual-response-rephraser/); the paper likewise says it "may not preserve the exact meaning of the template" — [arXiv 2402.12234](https://arxiv.org/html/2402.12234)
- Small-model rephrasing evaluation (Rasa blog): Llama/Gemma (<15B) vs a proprietary baseline, judged with deepeval GEval correctness; small models comparable on cancellations, context switches, corrections, lag on generalization; small models "significantly better latency". Observed failure: small models add excessive reasoning/elaboration that can shift meaning, more often in long multi-skill conversations with multiple facts. Exact numbers only in charts (not extractable). Rasa says proprietary models are typically too slow for voice — [Rasa blog](https://rasa.com/blog/contextual-rephrasing-with-small-llms)
- Repair patterns and defaults — [Rasa patterns docs](https://rasa.com/docs/reference/primitives/patterns/):
  - `pattern_correction`: user corrects an earlier value -> update slot(s) and confirm with `utter_corrected_previous_input`.
  - `pattern_cancel_flow`: cancel -> run `action_cancel_flow`, announce stopping.
  - `pattern_skip_question`: user tries to skip a collect step -> by default declines and re-asks.
  - `pattern_chitchat`: off-topic -> `utter_cannot_handle` (free-form replies off by default).
  - `pattern_cannot_handle`: command generation fails / unsupported -> asks user to rephrase.
  - `pattern_clarification`: ambiguous between flows -> list up to 3 options, or ask for detail.
  - `pattern_user_silence` (voice): repeat message, then "are you still there?", then hang up.
  - `pattern_repeat_bot_messages`: resends ALL bot messages since the last user message. Docs note this is a poor fit when responses are long/LLM-generated and suggest overriding with a rephrased response whose prompt includes history.
  - `pattern_continue_interrupted`: after a digression, ask whether to resume.
  - Default pattern responses are rephrased automatically unless overridden.
- Known rephraser bug noted in docs: with EnterpriseSearchPolicy the rephraser can overwrite `utter_can_do_something_else` — [Rasa rephraser docs](https://rasa.com/docs/reference/primitives/contextual-response-rephraser/)

### Inferences
- The KPI bot's current design (LLM classifies into intents restricted per pending question) is close to CALM's command generator; the main missing pieces are first-class repair commands (Repeat, Clarify/CannotHandle, Correction, Skip/Hold, "AskQuestion") distinct from answer intents, which would directly fix "มีครับ" (meta "I have a question") being consumed as an answer and nonsense being treated as yes.
- Rasa's own default for "repeat" (replay everything) is exactly the observed ขออีกที problem; their docs recommend overriding it. A per-step "key item" short form is a natural override.
- Rasa ships the rephraser without a fact-preservation verifier; for a regulated domain, opt-in per response (never on disclosures/consent/numbers) plus an added verifier is warranted.

### Gaps
- No published Rasa latency/cost numbers for the rephraser or command generator in voice; blog charts not extractable.
- Default rephraser prompt text not shown on the docs page fetched.
- No evidence on Thai-language performance of CALM components.

## 2. Parlant, Pipecat Flows, LiveKit Agents: how they combine determinism with generation

### Takeaway
Three different control points: Parlant constrains the OUTPUT (strict canned responses, LLM only selects/fills), Pipecat Flows constrains the CONTEXT and TOOLS per node (graph is fixed, LLM speaks within a node), LiveKit separates FIXED SPEECH (`session.say`) from GENERATED speech (`generate_reply`) and structures work into typed AgentTasks. None publish independent hallucination/latency benchmarks.

### Cited Findings
- Parlant canned responses: three modes — fluid (prefer template, fall back to generation), composited (templates only shape style of the LLM's own draft), strict (only approved templates; otherwise a configurable no-match message). Docs recommend strict for high-risk deployments; the most restrictive active mode wins when guidelines/journeys override — [Parlant canned responses](https://www.parlant.io/docs/concepts/customization/canned-responses)
- Parlant selection mechanism: (1) LLM drafts a message from full context, (2) retrieve candidate templates similar to the draft, (3) render candidates with field values, (4) LLM picks best rendered candidate. "Signals" (sample drafts attached to a template) improve retrieval — [Parlant canned responses](https://www.parlant.io/docs/concepts/customization/canned-responses)
- Parlant data guard: a template that references a tool field is never selected unless a successful tool call supplied that field; field types: `std.` (context), `generative.` (LLM-inferred, controlled generation inside a strict template), tool/retriever fields; Jinja2 supported — [Parlant canned responses](https://www.parlant.io/docs/concepts/customization/canned-responses)
- Parlant latency: no numbers; preamble responses (short acknowledgements sent while the full answer is generated, can be canned with a `preamble()` tag) are its answer to perceived latency — [Parlant canned responses](https://www.parlant.io/docs/concepts/customization/canned-responses)
- Parlant guidelines: condition/action pairs, matched per turn (LLM matcher by default; can be regex/embedding/boolean custom matchers), only matched guidelines injected into the prompt; tracks whether an action was applied to avoid repeating it. Documented failure modes: false positives/negatives on predictive conditions, over-literal following, too-vague or too-rigid guidelines, too many always-on guidelines, eager tool calls from false-positive matches — [Parlant guidelines](https://www.parlant.io/docs/concepts/customization/guidelines)
- ARQs (Attentive Reasoning Queries — structured JSON reasoning that re-states critical instructions just before the decision): 90.2% success on 87 scenarios vs 86.1% CoT and 81.5% direct generation; best on guideline re-application and hallucination prevention. Benchmark built by Parlant authors (small, not independent) — [arXiv 2503.03669](https://arxiv.org/pdf/2503.03669)
- Pipecat Flows: conversation as a graph of nodes, each node giving the LLM only that task's prompt and tools, to reduce hallucination/accuracy drop from one large prompt with many tools; transitions via functions (declarative config or programmatic returning next node); `FlowsFunctionSchema` for enum/range constraints; requires a cascaded STT->LLM->TTS pipeline with function calling (speech-to-speech not supported) — [Pipecat Flows guide](https://docs.pipecat.ai/guides/features/pipecat-flows)
- LiveKit: `session.say(text)` speaks fixed text as-is (for scripted lines; can pass pre-synthesized `audio` to skip TTS and cut latency); `generate_reply(instructions=...)` lets the LLM compose; `allow_interruptions=False` for must-finish speech such as legal disclosures; `add_to_chat_ctx` controls whether the line enters model context — [LiveKit audio/speech docs](https://docs.livekit.io/agents/build/audio/)
- LiveKit workflows: Agent (long-lived control), function tools (model-driven), AgentTask (short-lived unit that runs to completion and returns a typed result), TaskGroup (ordered tasks, user may revisit earlier steps, shared context, summarized result), handoffs with explicit context passing. Docs recommend starting with one agent + tools and adding structure only on concrete limits; they do not claim full determinism and recommend tests/evals/simulations — [LiveKit workflows](https://docs.livekit.io/agents/build/workflows/)

### Inferences
- For KPI: regulated lines (identity/recording notice, consent, policy numbers, premiums, disclaimers) map to LiveKit-style `say()` / Parlant-strict — fixed, non-interruptible where legally required, ideally pre-synthesized TTS. Conversational glue (acknowledgement, empathy, clarification, transitions) is the only zone for generation, and Parlant's "composited"/`generative.` field idea suggests generating a short slot inside a fixed template rather than rewriting whole lines.
- Parlant's "template with field only selectable if data present" is a cheap guard worth copying: a template mentioning a premium is unusable unless the premium slot is filled.
- Pipecat's per-node scoped tools is the same idea as KPI's "restrict model intents per pending question", which is supported as a hallucination/over-classification mitigation by these frameworks' design rationale (not by measured data).

### Gaps
- Pipecat details on `pre_actions`/`tts_say`, `respond_immediately`, and context strategies (RESET_WITH_SUMMARY) not retrieved (flow-configs page returned 404).
- No independent latency or accuracy numbers for Parlant strict mode, Pipecat Flows, or LiveKit tasks.

## 3. Dialogue-state + NLG literature: template vs neural/LLM realization; fact-preservation checks

### Takeaway
The classic metric for "did the generator keep the facts" is slot error rate, ERR = (missing + redundant slots) / total slots in the dialogue act. Neural/LLM generators are more fluent than templates but omit or invent slots; best published systems reduce but do not eliminate this, which justifies a deterministic post-check with template fallback.

### Cited Findings
- SC-GPT ERR definition: ERR = (p+q)/M, p missing, q redundant slots, M slots in the dialog act — [SC-GPT, Peng et al. 2020](https://ar5iv.labs.arxiv.org/html/2002.12328)
- SC-GPT (restaurant domain, FewShotWOZ): seen acts BLEU/ERR — SC-LSTM 23.05/40.82, GPT-2 30.43/3.26, SC-GPT 40.28/1.09; unseen acts — SC-LSTM 12.83/51.98, GPT-2 27.92/17.36, SC-GPT 36.69/4.96. Human eval (1-3): SC-GPT informativeness 2.64, naturalness 2.47 vs human 2.92/2.72 — [SC-GPT](https://ar5iv.labs.arxiv.org/html/2002.12328)
- Implication from those numbers: slot errors rise sharply on unseen dialogue acts (1.09% -> 4.96% for the best model) — [SC-GPT](https://ar5iv.labs.arxiv.org/html/2002.12328)
- Template-guided generation (Kale & Rastogi 2020): concatenate simple per-slot templates (possibly ungrammatical) then have a pretrained LM rewrite into natural text; reported to beat strong baselines, be robust out-of-domain, and be more sample-efficient (abstract-level claims; numbers not retrieved) — [arXiv 2004.15006](https://arxiv.org/abs/2004.15006)
- Slot-consistent NLG (Li et al., ACL 2020): treats missing/redundant slots as hallucination; Iterative Rectification Network with slot-consistency reward reduced ERR across strong baselines — [ACL 2020.acl-main.10](https://preview.aclanthology.org/setup/2020.acl-main.10)
- LLM TOD studies: hallucination (ungrounded entities) is the most important error common to all models tested; some errors are prompt-recoverable or fixable in postprocessing (robust parsing, fuzzy matching of slot values) — [Hudeček & Dušek, Are LLMs All You Need for TOD? arXiv 2304.06556](https://arxiv.org/pdf/2304.06556)
- Backend failures (empty results, API errors) lead models to fluent but unsupported confirmations; a Guided-Retry prompt reduced hallucination by 50% (MultiWOZ) and 42% (SGD) but 6-37% residual hallucination remained (SIGDIAL 2026; details from search summary, not full text verified) — [SIGDIAL 2026 paper](https://aclanthology.org/2026.sigdial-1.57.pdf); [presentation](https://2026.sigdial.org/assets/files/presentations/P3.8.pdf)
- Noisy-channel reranking: a wrong dialogue act causes the generator to hallucinate; checking/choosing the act before generation produced faithful responses — [arXiv 2404.15219](https://arxiv.org/pdf/2404.15219)

### Inferences
- Concrete guard for KPI rephrasing: each template declares required literals (policy number, amounts, dates, product name, legal phrase, score scale) and forbidden content (promises, new numbers, "guarantee"/"รับประกัน" style commitments); after generation, check (a) every required literal appears verbatim (after Thai number normalization), (b) no digits/amounts not in the slot set, (c) length cap, (d) no banned phrases; on any failure, speak the template. This is an engineering inference from ERR literature, not a published Thai-specific method.
- Prefer "template + small generated prefix/suffix" (e.g., generated acknowledgement + fixed question) over "rewrite the whole line": ERR literature shows generation errors scale with the number of slots and novelty of the act; keeping facts in fixed text sidesteps the problem.

### Gaps
- No found study measuring LLM rephraser fact-preservation for Thai or for 7-10B open models in voice.
- Full SC-GPT FewShotWOZ overall table (image) and Kale & Rastogi numeric results not extracted.

## 4. Conversation patterns: acknowledgements, empathy, repeats, nonsense/low-confidence, hedges, meta-utterances, corrections, one question per turn, short turns

### Takeaway
Vendor prompting guides converge on: short turns, explicit variety rules (because models copy sample phrases), explicit unclear-audio handling, and separate guardrail sections. Classic spoken-dialogue research gives the confidence-tiered confirmation scheme (reject/re-ask, explicit confirm, implicit confirm) and state-specific rejection thresholds — directly applicable to hedges and nonsense.

### Cited Findings
- OpenAI Realtime prompting guide: add a "Variety" rule to reduce robotic phrasing; the model follows sample phrases very closely (so examples get parroted); short bullets beat long paragraphs; conflicting instructions degrade performance; pin output language to stop switching; replacing "inaudible" with "unintelligible" improved noisy-input handling; recommended sections include Conversation Flow (states, goals, transitions) and Safety & Escalation (e.g., escalate after repeated failures) — [OpenAI Realtime prompting guide](https://developers.openai.com/cookbook/examples/realtime_prompting_guide)
- ElevenLabs guide: dedicated `# Guardrails` section (models attend to it), clear section boundaries prevent "instruction bleed"; tone section covers verbosity and fillers; number/identifier normalization either by TTS normalizer or explicit prompt rules; STT transcripts may arrive in non-standard format — [ElevenLabs prompting guide](https://elevenlabs.io/docs/agents-platform/best-practices/prompting-guide)
- Confirmation strategies: explicit ("..., did I get that right?") vs implicit (embed interpretation in next question); separate non-understanding recovery (sorry, please repeat) from misunderstanding recovery — [Brandeis error-handling lecture](https://www.cs.brandeis.edu/~cs115/CS115_slides/HandlingErrorsInDialogue.pdf)
- Confidence tiers: below rejection threshold -> "sorry?"; middle -> explicit confirmation; high -> implicit confirmation — [Pearl, Robustness in speech interfaces](https://www.ida.liu.se/~arnjo82/chi-ws-02/papers/pearl.doc)
- Fixed global rejection thresholds create non-optimal trade-offs between misunderstandings and false rejections; Bohus & Rudnicky derive error costs from data and set state-specific thresholds — [Bohus & Rudnicky, Interspeech 2005](https://www.isca-archive.org/interspeech_2005/bohus05_interspeech.html); [MSR listing](https://www.microsoft.com/en-us/research/publication/principled-approach-rejection-threshold-optimization-spoken-dialog-systems/)
- Rasa voice silence pattern: repeat, then check presence, then hang up; repeat pattern default replays everything (flagged as poor) — [Rasa patterns](https://rasa.com/docs/reference/primitives/patterns/)
- Rasa skip-question default: decline skip and re-ask (i.e., collect steps are mandatory unless designed otherwise) — [Rasa patterns](https://rasa.com/docs/reference/primitives/patterns/)
- Parlant tracks whether a guideline's action has already been applied, to avoid repeating behavior (relevant to not repeating the same acknowledgement/empathy line) — [Parlant guidelines](https://www.parlant.io/docs/concepts/customization/guidelines)

### Inferences (design proposals for KPI, derived from the above)
- Acknowledgements: keep a small approved pool per dialogue act (neutral / positive / low-score) and pick deterministically with no-repeat-within-N memory; or let the LLM choose a pool index rather than write free text. This gives variety without free generation (OpenAI warns models copy sample phrases, so a pool also avoids every call sounding identical).
- Low score empathy: one short empathetic clause + optional "may I ask why?" from an approved list; prohibit promises of follow-up/compensation unless a business rule actually triggers one (enforce via banned-phrase check).
- Repeat ("ขออีกที"): add a REPEAT command; replay only the current question's short form (author a `short` variant per step), optionally with slower TTS rate; second repeat -> rephrased simpler variant; Rasa explicitly flags full replay as poor.
- Nonsense / off-topic / low ASR confidence: classifier must have an explicit `unclear`/`out_of_scope` label (abstain) that is never mapped to yes; policy: clarify once (re-ask short form), then on second failure move on/mark unanswered or escalate per state-specific thresholds (Bohus-style cost per question: e.g., a consent question deserves a stricter threshold than a satisfaction score).
- Hedged confirmation ("มั้ง", "น่าจะ", "คิดว่า"): classify as a separate `hedged_yes` and route to explicit confirmation for consequential questions (consent, identity) and accept with implicit confirmation for low-stakes ones (confidence-tier scheme).
- Meta-utterances ("มีครับ" to "any questions?" meaning "I have one", "เดี๋ยวนะ", "รอแป๊บ"): add `has_question`, `wait/hold` commands; `has_question` -> "เชิญถามได้เลยค่ะ" and wait; `wait` -> short hold acknowledgement and do not advance or time out quickly.
- Corrections: `correction(slot, value)` command -> update slot, confirm the corrected value (Rasa `pattern_correction`).
- One question per turn / short turns: split monologues into segments with a check-in; keep each bot turn to one ask; this aligns with OpenAI's short-bullets and Rasa's step-per-collect design.

### Gaps
- Bohus & Rudnicky "Sorry, I didn't catch that!" (SIGDIAL 2005) compared non-understanding recovery strategies (incl. MoveOn, AskRepeat, AskRephrase); I recall MoveOn performing well but could not retrieve the paper to verify — treat as unverified.
- No sourced Thai-specific evidence on hedge particles (มั้ง/มั๊ง/น่าจะ) or polite-particle handling in voicebots.
- No measured results on acknowledgement variety vs perceived naturalness.

## 5. Single call (interpret + draft) vs separate calls; caching; latency

### Takeaway
Published frameworks generally split understanding from generation (Rasa: command generator then optional rephraser; Parlant: draft then select), at the cost of extra serial calls. Rasa itself says serial LLM calls make the default setup costly and slow and pushes small fine-tuned models; Parlant and LiveKit mitigate perceived latency with preambles/fixed pre-synthesized audio.

### Cited Findings
- Rasa: the default setup "has high costs and latency because the LLM is called multiple times in series"; smaller models are more cost-efficient; summary-mode history in the rephraser adds an extra LLM call per turn (transcript mode avoids it) — [Rasa blog](https://rasa.com/blog/contextual-rephrasing-with-small-llms); [Rasa rephraser docs](https://rasa.com/docs/reference/primitives/contextual-response-rephraser/)
- Parlant uses draft -> retrieve -> render -> select (multiple steps) and offers preamble responses to cover generation time — [Parlant canned responses](https://www.parlant.io/docs/concepts/customization/canned-responses)
- LiveKit: pre-synthesized audio for frequently repeated fixed phrases skips TTS and cuts latency — [LiveKit audio docs](https://docs.livekit.io/agents/build/audio/)
- ARQ structured-output ordering (put critical checks first in the JSON) improved adherence at slightly higher token cost — [arXiv 2503.03669](https://arxiv.org/pdf/2503.03669); [Parlant explainability docs](https://parlant.io/docs/advanced/explainability)

### Inferences
- For KPI with a ~0.5 s self-hosted model, a single json_schema call can return both interpretation and a short phrasing slot (e.g., `{"command":..., "confidence_band":..., "ack_id": 3, "empathy": bool}`), with field order putting the classification first (ARQ-style). The state machine then validates the command and assembles speech = chosen ack (from pool) + fixed next-step template. This avoids a second serial call and keeps facts in templates.
- If free rephrasing is ever adopted, run it only for non-regulated lines, pre-generate/cached variants offline (reviewed by compliance) rather than per-call generation; at runtime select among approved variants. This converts generation risk into a review problem and removes runtime latency. (Inference; no source measured this.)
- Fixed lines (intro, recording notice, closing) should be cached audio.

### Gaps
- No public measurement comparing single-call vs two-call architectures for voice latency or accuracy.
- No public Qwen-specific latency data for this pattern.

## 6. Handling LLM nondeterminism and over-classification safely

### Takeaway
Verbalized LLM confidence is poorly calibrated and poorly discriminative; LLMs rarely abstain on their own. Safety must come from structure: per-state allowlists of commands, explicit abstain/unclear labels, deterministic rule layers, and state-specific thresholds tuned from labeled data — not from trusting a "confidence" field.

### Cited Findings
- Verbalized confidence clusters at 80-100%; GPT-3/3.5/Vicuna average ECE > 0.377; even GPT-4 had AUROC ~62.7% for separating right from wrong answers — [Xiong et al., arXiv 2306.13063](https://arxiv.org/pdf/2306.13063)
- Prompting + temperature scaling can cut RLHF-LM calibration error by >50% (so verbalized probabilities are usable only after calibration) — [Tian et al., arXiv 2305.14975](https://arxiv.org/pdf/2305.14975v1)
- 2026 preprints: verbal confidence predicts the model's commit/abstain decision better than correctness; logit entropy/probes discriminate correctness better; models almost never abstain even when penalties make abstention optimal (RiskEval) — preprints, not replicated — [arXiv 2606.29490](https://arxiv.org/abs/2606.29490); [search summary of RiskEval / related](https://www.alphaxiv.org/overview/2604.19444)
- Rasa restricts the LLM to a fixed command vocabulary and the flow decides what a SetSlot means in context; renaming commands voids accuracy guarantees — [Rasa command generator docs](https://rasa.com/docs/pro/customize/command-generator)
- Pipecat recommends enum/range schemas (`FlowsFunctionSchema`) per node and scoping tools per node to limit errors — [Pipecat Flows](https://docs.pipecat.ai/guides/features/pipecat-flows)
- Parlant documents eager/false-positive guideline matches as a failure mode and allows deterministic (regex/boolean) matchers instead of LLM matchers — [Parlant guidelines](https://www.parlant.io/docs/concepts/customization/guidelines)
- State-specific rejection thresholds derived from error costs outperform a single fixed threshold — [Bohus & Rudnicky 2005](https://www.isca-archive.org/interspeech_2005/bohus05_interspeech.html)

### Inferences
- KPI's per-question intent restriction is consistent with all frameworks reviewed; extend it with (a) always-available repair commands (repeat, unclear, has_question, wait, correction, opt_out) and (b) a mandatory `unclear` option so the schema never forces a yes/no.
- High-impact intents (do-not-call, complaint escalation, consent withdrawal) should require corroboration: rule/keyword layer (e.g., explicit Thai phrases) OR confirmation turn before acting; complaint-vs-DNC confusion is a classic over-classification that a confirmation question resolves cheaply.
- Use logprobs (if the self-hosted Qwen serving exposes them) or self-consistency (2 samples at temp>0, accept only if agree) rather than a self-reported confidence field; calibrate thresholds on a labeled Thai call set per state.
- Run at temperature 0 with fixed schema for classification to reduce nondeterminism; keep a regression set of real utterances (ถั่วต้ม, มั้งครับ, มีครับ, ขออีกที, complaints) as CI tests.

### Gaps
- No source gives Thai-specific calibration data or Qwen logprob reliability.
- RiskEval citation came via search summary; primary paper URL not verified.
