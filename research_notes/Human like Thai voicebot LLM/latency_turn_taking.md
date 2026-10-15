# End-to-end latency and human-like turn-taking for a cascaded Thai phone voicebot (LiveKit Agents 1.8.x)

Research date: 2026-10-08. LiveKit facts marked **[src 1.8.5]** come from the `livekit/agents` GitHub source at commit `bcdf907` (2026-10-07). There, `livekit-agents/livekit/agents/version.py` reports `__version__ = "1.8.5"`. Source URL: https://github.com/livekit/agents. File paths below are relative to `livekit-agents/livekit/agents/`. Several docs.livekit.io pages returned 404 to the fetcher, so the source code is the primary reference for parameter names and defaults.

---

## 1. How fast must a voice agent respond to feel human? (turn-gap norms, vendor targets, perceptual thresholds)

### Takeaway
In human conversation the modal gap between turns is about 0–200 ms. Language averages differ by up to about 250 ms (Stivers 2009). People can only respond that fast because they predict the end of the other speaker's turn, since producing speech takes 600 ms or more. Cascaded voice-agent practitioners treat **about 800 ms voice-to-voice** as the realistic target, **under 500 ms** as the stretch goal, and **over 1–1.2 s** as clearly broken. On PSTN, gaps above about 800 ms can make the caller think the line has dropped.

### Cited Findings
- Stivers et al. 2009 (PNAS 106(26):10587–10592) studied 10 languages, from traditional indigenous communities to major world languages. All showed avoidance of overlap and minimisation of silence between turns. Cross-language differences in average gap fall within a range of 250 ms from the cross-language mean. — [MPI record](https://forms.mpi.nl/node/50939); [emcawiki summary](https://emcawiki.net/Stivers-etal2009)
  - The search did not confirm the commonly quoted "~200 ms mode" in the abstract. It is widely attributed to this paper's body. Check the full text before quoting it as Stivers' number. Levinson and Torreira (below) give the 200 ms figure explicitly.
- Levinson and Torreira 2015 (Frontiers in Psychology, doi:10.3389/fpsyg.2015.00731): gaps between turns are "of the order of 200 ms", but language production latencies are over 600 ms. Listeners therefore have to predict and plan their response while the other person is still talking. — [Frontiers full text](https://www.frontiersin.org/articles/10.3389/fpsyg.2015.00731/full); [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4464110)
- In Dutch telephone conversations, 45% of turn transitions fall between −250 and +250 ms (De Ruiter et al. 2006, as cited in Frontiers 2017). Naming a picture takes at least 600 ms. — [Frontiers 2017](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2017.00211/pdf)
- Skantze 2021, "Turn-taking in Conversational Systems and Human-Robot Interaction: A Review" (Computer Speech & Language 67) is the standard engineering review. It contrasts silence-threshold endpointing with predictive models. I could not retrieve its specific numbers. — [KTH turn-taking project](https://www.kth.se/sv/tmh/projects/turn-taking-1.1043498)
- Kwindla Hultman Kramer (Daily/Pipecat), AI Engineer World's Fair 2025, recommends aiming for **800 ms voice-to-voice**. He puts human expectation at about 500 ms, varying by language and culture. This is a target, not a measured benchmark. — [AI Engineer talk](https://ai.engineer/talks/pipecat-cloud-enterprise-voice-agents-built-on-open-source)
- Pipecat docs: a typical round trip (transport → STT → LLM → TTS → transport) takes about 500–800 ms in most cases. — [Pipecat docs](https://docs.pipecat.ai/pipecat/)
- Vapi: users start noticing delay around 300 ms, and anything over 0.5 s breaks the rhythm. Vapi's playbook budget is about 1,000 ms total: STT 200, LLM 400, TTS 200, network 200 (vendor). — [Vapi blog](https://vapi.ai/blog/speech-latency); [Vapi playbook](https://vapi.ai/playbook/build)
- Vendor perceptual bands vary. One framework: under 500 ms natural, up to 800 ms acceptable, over 1000 ms broken. Another: under 600 ms near real-time, 600–900 ms noticeable but acceptable, over 1.2 s frustrating. — [Hamming glossary](https://hamming.ai/glossary/latency); [softwareseni](https://www.softwareseni.com/voice-agent-latency-solved-enough-for-production-benchmarks-and-architecture-tradeoffs)
- Callers notice delays above 500 ms. Delays above 800 ms often create the impression that the call has dropped (vendor). — [Coval](https://www.coval.dev/blog/voice-ai-latency)
- An identical-stack test measured Retell at an average 714 ms total latency (third-party test, method unclear). Retell says LLM processing typically takes 200–400 ms of the budget. — [growwstacks](https://growwstacks.com/blog/voice-ai-showdown-vapi-synthflow-retell-latency-test); [Retell](https://www.retellai.com/da/resources/sub-second-latency-voice-assistants-benchmarks)
- VAD/endpointing silence wait adds about 200–800 ms at the front of the pipeline, and benchmarks often leave it out. — [morphllm](https://www.morphllm.com/voice-agent-api)
- ITU-T G.114 (as reported): one-way network delay under 150 ms is essentially transparent, and 400 ms is the planning limit. This covers the network path only. — [Coval summary](https://www.coval.ai/blog/voice-ai-latency)

### Inferences
- In a cascade, the **endpointing wait is the single largest controllable adder**. LiveKit's default `min_delay` of 0.5 s on its own uses most of a "human" gap. A realistic budget for this stack: endpoint 300–500 ms, STT final 100–300 ms, LLM interpretation 350–850 ms (measured), TTS first audio (Gemini, unknown, possibly 500 ms or more), and SIP/PSTN 70–200 ms. That totals roughly 1.3–2.3 s unless stages overlap. So the 800 ms target needs overlap (preemptive LLM), instant cached audio for template lines, and/or an immediate acknowledgement.
- In outbound insurance calls, a slightly longer gap is more acceptable after a substantive customer answer than after a yes/no. The state machine can choose its gap strategy per state.

### Gaps
- No Thai-specific turn-gap corpus measurement was found. Thai is not among Stivers' 10 languages, as far as the abstract shows.
- Skantze 2021 numeric recommendations were not retrieved.

---

## 2. LiveKit Agents 1.8.x turn handling: endpointing, turn detection modes, Thai support, adaptive/dynamic endpointing, interruptions

### Takeaway
In 1.8.x, all turn settings live under `AgentSession(turn_handling={...})`. The old kwargs `min_endpointing_delay` and `max_endpointing_delay` are deprecated. Endpointing defaults to `fixed`, with `min_delay=0.5` and `max_delay=3.0` (or 0.3 and 2.5 with a streaming turn detector). There is a Python-only `dynamic` mode that learns each caller's pause length. **The LiveKit turn-detector models do not support Thai**: neither the HF multilingual card nor the local `v1-mini` language table lists `th`. For Thai, turn detection must therefore be `"vad"` or `"stt"` (your own ASR's endpointing), tuned with `min_delay` and `max_delay`.

### Cited Findings
- **Turn detection modes** [src 1.8.5, `voice/turn.py`]: `TurnDetectionMode = Literal["stt", "vad", "realtime_llm", "manual"] | _TurnDetector | _StreamingTurnDetector`. If you don't set one, the session auto-selects in the order realtime_llm → vad → stt → manual. The docs call the turn detector model (`inference.TurnDetector()`) "the default and recommended mode". They say VAD-only is for "minimal latency or languages the turn detector doesn't cover", and STT endpointing uses the provider's own detection, such as AssemblyAI or Deepgram Flux. — [LiveKit turns docs](https://docs.livekit.io/agents/build/turns/); [source](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/turn.py)
- **EndpointingOptions** [src 1.8.5]: `mode: "fixed" | "dynamic"` (default `"fixed"`), `min_delay` (default **0.5 s**, the minimum silence since last speech before the turn is declared complete), `max_delay` (default **3.0 s**, the ceiling), and `alpha` (default 0.9, the EMA weight for dynamic mode). With a streaming turn detector the defaults are `min_delay=0.3` and `max_delay=2.5`. — [source turn.py](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/turn.py)
- Usage example from the source docstring: `AgentSession(turn_handling={"endpointing": {"min_delay": 0.3}, "interruption": {"enabled": False}, "preemptive_generation": {"preemptive_tts": True}})`. Options can also be overridden per `Agent`, and missing keys inherit from the session. — [source turn.py](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/turn.py)
- **Deprecated** [src 1.8.5, `voice/agent_session.py` ~L381, L1478]: `min_endpointing_delay` and `max_endpointing_delay` are still accepted with a deprecation warning ("Use turn_handling=TurnHandlingOptions(...) instead") and are mapped to `endpointing.min_delay` and `endpointing.max_delay`. — [source agent_session.py](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py)
- **Dynamic ("adaptive") endpointing** [src 1.8.5, `voice/endpointing.py` `DynamicEndpointing`]: `min_delay` is a learned floor, an EMA of the caller's pauses between utterances and of pauses before an immediate interruption (which it treats as a false end-of-turn). `max_delay` is a fixed ceiling. The docs say it is Python-only and "adapts the delay within the min/max range based on session pause statistics." The docs reserve the word "adaptive" for interruption handling. — [source endpointing.py](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/endpointing.py); [LiveKit turns docs](https://docs.livekit.io/agents/build/turns/)
- **Turn detector language support**:
  - HF `livekit/turn-detector` card: the multilingual model supports 14 languages: English, Spanish, French, German, Italian, Portuguese, Dutch, Chinese, Japanese, Korean, Indonesian, Turkish, Russian, Hindi. **Thai is not included.** The model has about 0.1B params, ships as INT8 ONNX `model_q8.onnx`, needs under 500 MB RAM, and is limited to the last 6 turns truncated to 128 tokens. The named release is v0.4.1, and the English-only variant is deprecated. The card advises compute-optimised CPUs and warns that burstable instances can cause inference timeouts. — [HF model card](https://huggingface.co/livekit/turn-detector)
  - In 1.8.5 the new `inference.TurnDetector(version="v1" | "v1-mini")` has a local mini model (`turn-detector-v1-mini`, about 108 MB). Its per-language threshold table `LOCAL_LANGUAGES` contains ar, de, en, es, fr, hi, id, it, ja, ko, nl, pt, tr, zh. There is **no `th`** (Arabic is present, Russian is not). `v1` (cloud) is auto-selected when hosted on LiveKit Cloud or in dev mode, and otherwise `v1-mini` is used. — [source inference/eot/languages.py, detector.py](https://github.com/livekit/agents/tree/main/livekit-agents/livekit/agents/inference/eot)
  - Unsupported language behaviour [src 1.8.5, `voice/audio_recognition.py` ~L1564]: if `turn_detector.supports_language(lang)` is false, it logs "Turn detector does not support language %s" and skips the model. The turn then commits on the endpointing delay alone, so adding the detector for Thai gains nothing.
  - The streaming detector's `TurnDetectionEvent` also exposes `backchannel_probability`, meaning how appropriate a backchannel would be at this pause. `on_agent_backchannel_opportunity` exists but is a TODO no-op in 1.8.5 and is not surfaced publicly. — [source turn.py, agent_activity.py](https://github.com/livekit/agents)
- **InterruptionOptions** [src 1.8.5]: `enabled=True`, `mode: "adaptive" | "vad"` (auto if absent; the docs say adaptive is the default on LiveKit Cloud with most STT providers), `min_duration=0.5` s, `min_words=0` (STT only), `resume_false_interruption=True`, `false_interruption_timeout=2.0` s (None disables), `discard_audio_if_uninterruptible=True`, and `backchannel_boundary=(1.0, 1.0)` s (suppresses adaptive-classified backchannels near the start and end of agent speech). — [source turn.py](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/turn.py); [LiveKit turns docs](https://docs.livekit.io/agents/build/turns/)
- `UserTurnLimitOptions`: `max_words` and `max_duration` (both default None) detect a user talking too long without an agent reply. `AgentSession(user_away_timeout=15.0)` is the default. — [source](https://github.com/livekit/agents)

### Inferences
- **For Thai, use `turn_detection="stt"` if your ASR emits reliable end-of-utterance or final events quickly. Otherwise use `"vad"`** (Silero VAD). Start with `endpointing={"mode": "dynamic", "min_delay": 0.4, "max_delay": 2.0}`. Then tune per state: yes/no confirmation states could use a lower `min_delay` (about 0.3), and open answers (policy numbers, addresses, reasons) a higher one (about 0.7–1.0). Per-`Agent` `turn_handling` overrides make per-state settings possible. These numbers are starting points I'm suggesting, not values from a source.
- Thai sentence-final particles (ครับ/ค่ะ/คะ/นะคะ) are strong lexical end-of-turn cues. A cheap custom `_TurnDetector` (the protocol takes `predict_end_of_turn(chat_ctx) -> float`, `supports_language`, `unlikely_threshold`) could return high probability when the interim transcript ends in a particle. This is speculative, but the protocol is public in `voice/turn.py`.
- `min_words` for interruptions counts words with the framework's WordTokenizer. The basic word tokenizer treats Thai characters as character-based ([source `_basic_word.py`](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/tokenize/_basic_word.py)), so word counts for Thai will not match intuition. Prefer `min_duration`.
- On 8 kHz phone audio with background noise, `false_interruption_timeout` with `resume_false_interruption=True` (the defaults) protects against coughs and "อืม" barge-ins.

### Gaps
- The language list of the cloud `turn-detector-v1` server model is fetched at runtime and could not be inspected. Thai support there is unconfirmed but unlikely. If the agent runs self-hosted rather than on LiveKit Cloud, it will use v1-mini anyway.
- The docs reference page `docs.livekit.io/reference/agents/turn-handling-options` returned 404 to the fetcher. Defaults above come from source, not docs.
- The contract of the custom Thai ASR (interim, final, preflight events, endpointing) is unknown. This decides whether `"stt"` mode and preemptive generation work at all.

---

## 3. LiveKit preemptive generation: mechanism, benefit, caveats with deterministic flows

### Takeaway
Preemptive generation starts the LLM reply on a final or preflight transcript before end-of-turn is confirmed. When the turn commits and nothing changed, the speculative reply is scheduled immediately, which hides LLM latency behind the endpointing wait. It is **on by default** in 1.8.x and runs the LLM only (TTS waits unless `preemptive_tts=True`). It is **thrown away if `on_user_turn_completed` changes chat_ctx or tools**, and every retry costs tokens. For a deterministic state machine it helps only if the interpretation call runs in the path the framework speculates on.

### Cited Findings
- `PreemptiveGenerationOptions` [src 1.8.5]: `enabled=True`, `preemptive_tts=False` ("When False (default), only LLM runs preemptively; TTS starts once the turn is confirmed"), `max_speech_duration=10.0` s (skipped for longer utterances, which "are more likely to change and users may expect slower responses"), and `max_retries=3` per user turn. — [source turn.py](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/turn.py); confirmed for 1.5.4 by [LiveKit community release notes](https://community.livekit.io/t/released-livekit-agents-1-5-3-and-livekit-agents-1-5-4/887)
- Triggers [src 1.8.5, `voice/audio_recognition.py` ~L1262, ~L1316]: it fires on a FINAL_TRANSCRIPT whose text changed (in VAD-based detection mode or after commit) and on every **PREFLIGHT_TRANSCRIPT** event (unless the mode is manual). Each new transcript cancels the previous speculative generation and starts a new one, up to `max_retries`. — [source](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/audio_recognition.py)
- Guard conditions [src 1.8.5, `agent_activity.on_preemptive_generation`]: it skips if the agent is currently speaking (uninterrupted), if scheduling is paused, or if `self.llm` is not an `llm.LLM` instance. It calls `_generate_reply(..., schedule_speech=False)`, which runs the agent's normal `llm_node`/`tts_node` pipeline. — [source agent_activity.py](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_activity.py)
- Reuse conditions [src 1.8.5, ~L2853]: the speculative reply is used only if the transcripts are equivalent, `chat_ctx.is_equivalent(...)` holds after `on_user_turn_completed`, and tools and tool_choice are unchanged. Otherwise it logs "preemptive generation invalidated after `on_user_turn_completed`…". On success it logs "using preemptive generation" with `preemptive_lead_time` (time saved). — [source](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_activity.py); [community thread](https://community.livekit.io/t/livekit-preemptive-generation-not-triggering-with-current-stt-model-missing-preflight-transcript-events/1582)
- The docs say that changing chat context or tools in `on_user_turn_completed` discards and regenerates the reply, increasing token usage, and suggest disabling the feature for long-form dictation or storytelling. — [LiveKit speech docs](https://docs.livekit.io/agents/build/speech/) (via search summary)
- Known issue: STT plugins that don't emit `PREFLIGHT_TRANSCRIPT` (e.g., Speechmatics) never trigger it in preflight mode. — [GitHub issue #4317](https://github.com/livekit/agents/issues/4317)
- A third-party write-up warns that preemptive generation duplicates LLM costs. — [gsdms.csir.co.za blog](https://gsdms.csir.co.za/blog/livekit-agents-preemptive-generation-duplicates)
- Older examples pass `preemptive_generation=True` straight to `AgentSession`, which does not match the 1.8.x `turn_handling` shape. — [futureagi blog](https://futureagi.com/blog/how-to-optimize-livekit-latency-2026/)

### Inferences
- **Deterministic flow pattern:** put the interpretation call plus the state transition plus template selection inside a custom `llm_node` override (yielding the template text). Don't do it in `on_user_turn_completed`. Preemptive generation then speculatively runs interpretation during the endpointing silence. It must be side-effect-free: don't commit state-machine transitions until the speech is actually scheduled or played, because speculative runs can be cancelled up to 3 times per turn. Commit inside the pipeline only when it is confirmed, or make transitions idempotent and keyed by turn.
- **Token budget:** at about 1k tokens per interpretation and up to `max_retries=3` speculative runs per turn, the worst case is about 3–4k tokens per user turn. The 60k tokens/min gateway limit allows about 60 one-shot interpretations/min. With one customer turn about every 10 s per call, that is about 10 concurrent calls with no preemption, and only about 2–3 at worst-case preemption. Set `max_retries` to 1, or disable preemption, unless the budget is raised. (This is arithmetic on the given numbers. The turn rate is an assumption.)
- `preemptive_tts=True` matters most when TTS first-audio is slow, as is likely with interim Gemini TTS. It is only safe if barge-in and discard work correctly. For template lines, cached audio makes it moot.
- Because `on_user_turn_completed` invalidates speculation when it mutates chat_ctx, avoid injecting RAG or state into chat_ctx there. Inject it in `llm_node` instead.

### Gaps
- No public numeric benchmark of preemptive generation savings was found. Measure `preemptive_lead_time` from logs.
- Whether the custom Thai ASR can emit preflight or early finals is unknown.

---

## 4. Streaming LLM → TTS, sentence chunking for first audio, Thai tokenization

### Takeaway
LiveKit's non-streaming-TTS `StreamAdapter` splits text into sentences with **blingfire** by default. The basic tokenizer uses `min_sentence_len=20`, `stream_context_len=10` and splits only on `. ! ? 。！？`. Thai text normally has none of these (sentences are separated by spaces), so a whole Thai reply can arrive at TTS as one "sentence" and delay first audio until the LLM finishes. Pass a custom Thai-aware `sentence_tokenizer`. For this bot, where lines are templates, streaming LLM tokens to TTS matters less than caching.

### Cited Findings
- `tts.StreamAdapter(tts, sentence_tokenizer=...)` defaults to `tokenize.blingfire.SentenceTokenizer(retain_format=True)` [src 1.8.5, `tts/stream_adapter.py` L40], and supports `text_pacing`. — [source](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/tts/stream_adapter.py)
- `tokenize.basic.SentenceTokenizer(language="english", min_sentence_len=20, stream_context_len=10, retain_format=False)`. The rule-based splitter marks sentence ends only at `[.!?。！？]` [src 1.8.5, `tokenize/_basic_sent.py`]. Its abbreviation rules are English-only. — [source](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/tokenize/_basic_sent.py)
- The basic **word** tokenizer handles Thai (U+0E00–U+0E7F) as a character-based script [src `_basic_word.py`]. — [source](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/tokenize/_basic_word.py)
- Streaming LLM tokens into TTS as they are generated can save 300–600 ms without changing any component (vendor claim). — [morphllm](https://www.morphllm.com/voice-agent-api)
- `AgentSession` also exposes `tts_text_transforms` and `use_tts_aligned_transcript` [src 1.8.5]. — [source](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py)

### Inferences
- **Thai chunking recipe:** write a `SentenceTokenizer` subclass that splits on whitespace runs (Thai uses spaces as clause/sentence breaks), on `ๆ`/`ฯ` boundaries, and after polite particles (ครับ ค่ะ คะ นะคะ นะครับ), with a minimum chunk of about 15–25 Thai characters for the first chunk and longer after that. Optionally use PyThaiNLP `sent_tokenize` (crfcut) for non-streaming segmentation. Author template lines with explicit break characters (e.g. a space or a `|` marker that the tokenizer splits on and strips).
- If the LLM ever writes reply text in JSON (combined call), the JSON wrapper defeats sentence streaming unless you parse the `reply` field incrementally. Put the reply field first or last deliberately: last if interpretation must be validated first, first for latency.
- Gemini TTS through the Interactions API is likely not wrapped by `StreamAdapter`. If it is a native streaming TTS, check how the plugin buffers input text.

### Gaps
- No LiveKit-provided Thai sentence tokenizer exists in 1.8.5. Blingfire's behaviour on unpunctuated Thai was not empirically tested here, though it likely returns one segment.
- Gemini Flash TTS time-to-first-audio has no official figure. Forum reports range from under 2 s to 10–20 s depending on key or project, with bursty rather than incremental delivery in one report. — [Google AI forum](https://discuss.ai.google.dev/t/3-1-flash-tts-preview-streaming-latency/176050); [older thread](https://discuss.ai.google.dev/t/gemini-flash-tts-speed-hows-your-experience/85165). Cloud TTS docs list streaming output formats including MULAW and ALAW for Gemini TTS. — [Google Cloud Gemini-TTS docs](https://cloud.google.com/text-to-speech/docs/gemini-tts)

---

## 5. Fillers, backchannels, and "acknowledgement first"

### Takeaway
Peer-reviewed evidence shows that fillers or acknowledgements make delays feel more acceptable, most strongly when delays are long, and that **context-appropriate fillers beat generic ones**. They don't fix overall experience, and some studies find fillers make an agent seem less intelligent. LiveKit 1.8.x has a built-in `with_filler(...)` helper for long tool steps, and `session.say(text, audio=...)` can play pre-recorded audio instantly.

### Cited Findings
- Alexa Prize study (Cohn et al., SIGDIAL 2019, n=5,527 real conversations): fillers and interjections each improved holistic user ratings. A separate external-listener perception test found no positive effect for fillers, so the rater's role matters. — [ACL Anthology W19-5935](https://preview.aclanthology.org/setup/W19-5935)
- 2025 study of LLM-powered virtual agents (latencies 1.5 s, 4.0 s, 6.5 s): over 4 s degrades QoE. Natural fillers improve perceived response time, especially at high delay, but "do not mitigate its broader effects on user experience". Passive wait indicators (sounds, icons) did not help. — [arXiv 2507.22352](https://arxiv.org/pdf/2507.22352)
- VR embodied-agent study (n=24): any filler made response time more acceptable than no filler. Contextualised fillers improved perceived competence, with no effect on likeability. — [arXiv 2508.11781](https://arxiv.org/html/2508.11781v1)
- A 2019 study found voice agents using conversational fillers were perceived as less intelligent (as summarised in the search results; the primary citation was not retrieved). — [search summary; see Crossref 10.1145/3472307.3484181](https://api.crossref.org/works/10.1145%2F3472307.3484181)
- ConvFill ("Thinking While Speaking"), a voice-agent filler approach, got the best subjective latency scores, aligned with time-to-first-response. — [arXiv 2511.07397](https://arxiv.org/pdf/2511.07397)
- LiveKit 1.8.5 `RunContext.with_filler(source, *, delay=0, interval=None, max_steps=None)` is an async context manager. It plays `source` (string or callable step→str/SpeechHandle) after the session has been idle for `delay` s, optionally repeating every `interval` s. It is designed for long-running function-tool steps [src `voice/events.py` L113, `voice/filler_scheduler.py`]. — [source](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/events.py)
- `AgentSession.say(text, *, audio: AsyncIterable[rtc.AudioFrame] = NOT_GIVEN, allow_interruptions=..., add_to_chat_ctx=True)` plays supplied audio frames directly, bypassing TTS [src `voice/agent_session.py` L1540]. — [source](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py)

### Inferences
- **"Ack-first" for this bot:** at end-of-turn, immediately play a cached short acknowledgement (e.g. "ค่ะ", "รับทราบค่ะ", "ขอบคุณค่ะ") chosen by the state, then the templated content once interpretation finishes. Risks:
  1. The ack contradicts the interpretation. For example, "ขอบคุณค่ะ" when the customer actually refused. Use neutral acks only ("ค่ะ", "ค่ะ…").
  2. Repetitiveness. Rotate 3–5 variants per state.
  3. The ack lands mid-pause when the customer wasn't done. This makes premature endpointing worse, so pair it with a slightly longer `min_delay` or play it only when interpretation is still pending after about 300–400 ms.
  4. It is interruptible, so allow interruptions on it.
- Use the filler conditionally (if LLM plus TTS isn't ready within about 400 ms), not unconditionally. The research shows benefit grows with delay and fillers can make the agent seem less intelligent.
- The voice must match. Record or generate the acks with the same Gemini TTS voice and settings so the timbre doesn't jump.

### Gaps
- No Thai-language or phone-call-specific filler study was found.

---

## 6. Pre-synthesising / caching TTS for fixed template lines

### Takeaway
Since bot lines are templates, pre-synthesising them takes TTS out of the critical path entirely. Playback starts in about one audio frame instead of after a cloud TTS round trip, which may take seconds for Gemini Flash TTS per forum reports. Use `session.say(text, audio=frames)`.

### Cited Findings
- `say(..., audio=AsyncIterable[rtc.AudioFrame])` plays pre-rendered audio while still adding `text` to chat context and transcript [src 1.8.5]. — [source](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py)
- Gemini Flash TTS latency is variable and sometimes slow (under 2 s to 10–20 s anecdotally, key-dependent). — [Google AI forum](https://discuss.ai.google.dev/t/3-1-flash-tts-preview-streaming-latency/176050)
- PSTN is G.711 narrowband 8 kHz. Format mismatch forces transcoding. — [Coval](https://www.coval.dev/blog/voice-ai-latency); [Parloa](https://www.parloa.com/knowledge-hub/factors-affecting-latency/)

### Inferences
- Pre-render each fully static line at build time. For lines with slots (names, amounts, dates), split them into static segments plus a dynamic slot. Cache common slot values (numbers 0–9999 in Thai, months, plan names), concatenate the frames, and only call TTS live for rare values such as the customer's name. Even then the name can be pre-synthesised at call setup, since outbound calls know the customer in advance.
- Store the cache at 16 or 24 kHz PCM and let LiveKit resample, or store 8 kHz to match SIP directly. Normalise loudness across segments and trim leading silence (TTS output often has 100–300 ms of lead-in).
- Key the cache by (text, voice, style prompt, model version) so a TTS vendor change invalidates it.

### Gaps
- Prosody continuity when splicing cached segments was not researched. There may be audible seams.

---

## 7. vLLM / Qwen serving: prefix caching, guided decoding, speculative decoding, output length, prompt size

### Takeaway
At batch size 1–few, latency ≈ TTFT (prefill, cut by prefix caching) + output_tokens × TPOT. The biggest levers are: (1) **fewer output tokens**, using short enum-style JSON fields with no rationale text; (2) a **static system prompt and schema first** so the automatic prefix cache hits; (3) xgrammar structured output, whose per-token overhead is negligible on modern vLLM but whose schema compile cost shows up in TTFT, so reuse identical schemas; (4) speculative decoding (EAGLE/MTP), which helps low-QPS latency only when a draft head exists.

### Cited Findings
- Automatic Prefix Caching reuses the KV cache of a shared prefix and reduces **prefill only**, not decode. There is no gain when generation dominates or prefixes don't overlap. It is enabled via `enable_prefix_caching=True` / `--enable-prefix-caching`. — [vLLM APC docs](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html) (the page fetched did not state whether it is on by default in V1. It is widely understood to be on by default in the V1 engine. **Verify on 0.30.**)
- XGrammar: in MLC-LLM, enabling it moved JSON-schema TPOT from 6.2 → 6.3 ms (bs=1) and 9.0 → 9.2 ms (bs=16). On older vLLM it had the best TPOT among the backends tested. — [XGrammar paper arXiv 2411.15100](https://arxiv.org/pdf/2411.15100)
- On vLLM 0.18 (B200), XGrammar, llguidance and regex added negligible overhead over unconstrained decoding. Outlines was about 2× slower because it rebuilt its FSM per prompt over an enum. — [arXiv 2605.08737](https://arxiv.org/pdf/2605.08737)
- JSONSchemaBench (Llama-3.1-8B, A100, bs=1): Outlines about 30–47 ms/token vs about 15–17 ms unconstrained. — [arXiv 2501.10868](https://arxiv.org/pdf/2501.10868)
- An unverified forum-bot answer says xgrammar can add CPU–GPU sync overhead on some consumer GPUs. — [vLLM forum](https://discuss.vllm.ai/t/general-questions-on-structured-output-backend/1444)
- vLLM speculative decoding targets inter-token latency at medium-to-low QPS. Model-based methods (EAGLE, MTP, draft model) give the best latency reduction. N-gram and suffix decoding give modest gains. — [vLLM spec decode docs](https://docs.vllm.ai/en/latest/features/speculative_decoding/)
- EAGLE-3 on Llama-3.1-8B gave about 1.84× on code-refactor but about 0.99× (break-even) on general chat, tracking acceptance length (2.54 vs 1.19). — [Alauda docs](https://docs.alauda.io/ai/2.8/deploy/inference_service/guides/vllm_speculative_decoding.html)
- Qwen3 non-thinking: pass `chat_template_kwargs: {"enable_thinking": false}` per request (via `extra_body` in the OpenAI client), or `--default-chat-template-kwargs` server-wide, with `--reasoning-parser qwen3`. A custom non-thinking chat template hard-blocks thinking. The example sampling for non-thinking is temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.5. Some Qwen3.5/3.6 deployments reportedly ignored the flag, so check the version. — [Qwen vLLM deployment docs](https://qwen15.readthedocs.io/en/latest/deployment/vllm.html); [QwenLM discussion #1300](https://github.com/QwenLM/Qwen3/discussions/1300); [vLLM issue 35574](https://github.com/vllm-project/vllm/issues/35574)
- The LLM stage is typically the largest and most variable (TTFT 350–1000 ms in stitched pipelines; about 60–70% of pipeline latency per one source). — [morphllm](https://www.morphllm.com/voice-agent-api)

### Inferences
- Given the measured 0.35–0.85 s and about 1k tokens per call with 0.14 s TTFB, most of the time is **decode**. Halving output tokens (short keys, enums, no free-text "reason", `max_tokens` sized to the schema, e.g. 64–128) should cut latency roughly proportionally. If ~1k is mostly the prompt, prefix caching takes care of it. Check `usage.prompt_tokens_details.cached_tokens` or vLLM metrics for the prefix-cache hit rate.
- Order the prompt as: [static system instructions] → [static schema/examples] → [per-state instructions] → [dialogue history] → [latest utterance]. Never put timestamps, call IDs or customer names at the top.
- For an interpretation-only classifier, `temperature=0` (greedy) is reasonable and reproducible. The Qwen sampling defaults above target chat, not classification. This is my inference.
- Use one fixed JSON schema object per state (identical bytes) so xgrammar's compiled-grammar cache gets hits.
- Speculative decoding helps only if Qwen 3.8 Flash ships an MTP/EAGLE head. Interpretation JSON has low prompt overlap, so n-gram is unlikely to help. Benchmark it.
- Tokens per minute: also trimming prompt tokens matters for the 60k TPM gateway limit, if the gateway counts prompt tokens (cached or not). That depends on the gateway.

### Gaps
- Qwen 3.8 Flash specifics (MTP head, recommended sampling) were not found. I did not verify that this model name exists in public sources. It is treated as the user's internal model.
- vLLM 0.30 defaults (APC on, default structured-output backend `auto`/xgrammar) were not verified against 0.30 docs.

---

## 8. One combined call (interpret + write reply) vs two calls

### Takeaway
No source benchmarks this directly. From first principles, one structured call saves a full round trip (TTFT plus network, about 150–300 ms on this stack) and duplicated prompt tokens, but it lengthens the output, and the reply text cannot be spoken until the JSON field streams. Since replies are templates chosen deterministically, the best latency option is **one interpretation-only call with minimal output, then a cached template**. Add a free-text reply field only for off-script states, and put it last.

### Cited Findings
- LLM latency is dominated by TTFT plus output length. Streaming tokens to TTS saves 300–600 ms. — [morphllm](https://www.morphllm.com/voice-agent-api)
- APC removes repeated prefill when the same prefix is reused across calls. — [vLLM APC docs](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html)

### Inferences
- Two sequential calls cost about 2×TTFT plus two decodes. One combined call costs 1×TTFT plus one longer decode. The combined call wins whenever free text is actually needed.
- Hybrid: a schema with `{"intent": enum, "slots": {...}, "needs_free_reply": bool, "reply": string|null}`, with `reply` last. The deterministic machine validates intent first and only speaks `reply` if the state allows it. Stream-parse the `reply` field into TTS if it is used.
- Under the 60k TPM limit, a combined call is also cheaper than two calls because the prompt is sent once.

### Gaps
- No published A/B data was found comparing combined and split calls for voice agents.

---

## 9. Telephony (SIP, 8 kHz) latency adders

### Takeaway
SIP/PSTN legs add roughly 50–250 ms one-way per direction depending on carrier and geography, plus jitter buffering (about 40–100 ms) and possible transcoding. Jitter also causes false endpointing: a 100 ms late packet can look like a pause.

### Cited Findings
- Planning figures (vendor, may conflict): one-way domestic PSTN 50–120 ms, international PSTN 100–250 ms, domestic SIP trunk 30–80 ms, WebRTC same-region 20–50 ms. Each PSTN hop adds 10–30 ms, and international routing 100–200 ms. — [Coval](https://www.coval.dev/blog/voice-ai-latency); [Parloa](https://www.parloa.com/knowledge-hub/factors-affecting-latency/)
- Stage budget (vendor): telephony inbound 50–150, STT 50–150, LLM 100–300, TTS 30–100, telephony outbound 20–80, for about 250–780 ms total. — [ConnexCS](https://connexcs.com/blog/ai-voice-agent-platforms-in-2026-why-the-carrier-layer-decides-performance)
- SIP signalling via resellers adds 50–150 ms (Telnyx marketing). — [Telnyx](https://telnyx.com/resources/voice-ai-agents-compared-latency)
- Jitter buffers add 40–100 ms. An initial buffer of 40–60 ms is suggested for AI agents. A late packet can be read by endpointing as a pause and cut off the caller. QoS, fewer hops and nearby media servers help more than tuning. — [Decagon](https://decagon.ai/glossary/what-is-voip-jitter); [Coval](https://www.coval.ai/blog/voice-ai-latency)
- PSTN codec is G.711 at 8 kHz, and transcoding adds latency. — [Coval](https://www.coval.dev/blog/voice-ai-latency)

### Inferences
- Host the LiveKit SIP and agent workers and the vLLM server in-country (Thailand) or as close as possible to the Thai carrier's SBC. A cross-region hop (e.g. to Singapore) adds about 30–50 ms RTT per leg, and Gemini TTS likely lives outside Thailand.
- Feed the ASR 8 kHz audio directly if it was trained on telephony, rather than upsampling.
- Keep VAD thresholds robust to PSTN noise and line echo. Echo of the bot's own voice can trigger false barge-ins, so watch `aec_warmup_duration` and the false-interruption settings [src 1.8.5 `AgentSession`].

### Gaps
- No independent (non-vendor) measurement of Thai PSTN/SIP latency was found.
