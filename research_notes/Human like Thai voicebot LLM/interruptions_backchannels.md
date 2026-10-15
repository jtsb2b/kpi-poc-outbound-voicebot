# Interruptions (barge-in), false interruptions, backchannels and resume behaviour for a Thai outbound phone voicebot (LiveKit Agents 1.8.x)

Research date: 2026-10-08. Primary source for LiveKit behaviour is the `livekit-agents@1.8.5` source tag on GitHub (the latest release listed by [releases.sh](https://releases.sh/livekit/livekit-agents-python/highlights)). Line numbers refer to that tag. Docs pages were partly 404 or incomplete, so source code takes precedence where they differ.

## 1. LiveKit Agents 1.8.x interruption options and what they do

### Takeaway
In 1.8.x, interruption settings live under `turn_handling={"interruption": {...}}` (`InterruptionOptions`). The older flat `AgentSession` kwargs (`allow_interruptions`, `min_interruption_duration`, `min_interruption_words`, `false_interruption_timeout` / `agent_false_interruption_timeout`, `resume_false_interruption`, `discard_audio_if_uninterruptible`) still exist but are migrated into it. Defaults: `min_duration=0.5`s, `min_words=0`, `false_interruption_timeout=2.0`s, `resume_false_interruption=True`. A false barge-in now pauses audio rather than discarding it, so it can resume. The "adaptive" ML interruption model runs only on LiveKit Cloud inference, and in self-hosted production it is OFF by default. `min_words` counts every Thai character as a "word", so it is nearly useless for filtering "ค่ะ".

### Cited Findings
**Option structure and defaults (source code, 1.8.5)**
- `InterruptionOptions` fields and defaults: `enabled=True`; `mode: "adaptive" | "vad"` ("Absent means auto-detect"); `discard_audio_if_uninterruptible=True`; `min_duration=0.5` ("Minimum speech length (s) to register as an interruption"); `min_words=0` ("STT only"); `resume_false_interruption=True`; `false_interruption_timeout=2.0` ("Seconds of silence after an interruption before it is classified as false. None disables"); `backchannel_boundary=(1.0, 1.0)` (seconds near the start/end of each agent turn during which overlapping speech that the adaptive detector classifies as a backchannel is suppressed) — [livekit/agents turn.py @1.8.5](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/turn.py)
- `EndpointingOptions` defaults: `mode="fixed"` (or `"dynamic"`), `min_delay=0.5`, `max_delay=3.0`, `alpha=0.9`. With a streaming turn detector the defaults are `min_delay=0.3` and `max_delay=2.5` — [turn.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/turn.py)
- `_migrate_turn_handling()` maps the deprecated kwargs as follows: `allow_interruptions=False` → `interruption.enabled=False`; `min_interruption_duration` → `min_duration`; `min_interruption_words` → `min_words`; `agent_false_interruption_timeout` → `false_interruption_timeout`; `min/max_endpointing_delay` → `endpointing.min_delay/max_delay` — [turn.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/turn.py)
- The docs use the new names (`min_duration`, `min_words`) and give `false_interruption_timeout: 2.0` / `resume_false_interruption: True` as the example. Python uses seconds and Node.js uses milliseconds — [LiveKit docs: turns](https://docs.livekit.io/agents/build/turns/); [LiveKit docs: turn detection configuration](https://docs.livekit.io/agents/build/turn-detection/configuration/)
- `allow_interruptions` is still a per-call option on `say()` / `generate_reply()`. Calling `interrupt()` on an uninterruptible handle raises `RuntimeError` unless `force=True` is passed. `session.interrupt()` stops at the first uninterruptible item in the queue — [LiveKit docs: turns](https://docs.livekit.io/agents/build/turns/)
- `discard_audio_if_uninterruptible` (default True) drops buffered user audio while the agent speaks uninterruptibly — [LiveKit docs: turns](https://docs.livekit.io/agents/build/turns/); [turn.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/turn.py)

**Detection signals**
- With VAD present, VAD triggers the interruption and interim STT transcripts do not. Without VAD, interim transcripts trigger it. A final transcript always interrupts, which catches a barge-in that VAD missed. None of this applies when turn detection is `"manual"` or `"realtime_llm"` — [LiveKit docs: turns](https://docs.livekit.io/agents/build/turns/)
- `_interrupt_by_audio_activity()` checks `min_words` against the current STT transcript using `split_words(text, split_character=True)`, with a TODO comment "better word splitting for multi-language". In `_basic_word.py`, the Thai block `฀-๿` is treated as a non-spaced script where "each character is treated as a separate word if split_character is True" — [agent_activity.py @1.8.5](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_activity.py); [_basic_word.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/tokenize/_basic_word.py)
- `min_duration` is compared against `ev.speech_duration` (the VAD speech duration) — [agent_activity.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_activity.py)

**False interruption / resume mechanics**
- When pausing is possible (`audio_output.can_pause` and `false_interruption_timeout` set), a VAD barge-in does not cancel the speech. The agent instead calls `audio_output.pause()`, sets agent state to `listening`, and arms a false-interruption timer. "A final transcript or a replying turn commit interrupts the paused handle." If neither happens, playback resumes via `audio_output.resume()` — [agent_activity.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_activity.py)
- The docs define a false interruption as "a VAD-triggered barge-in with no transcribed words". Events: `user_interruption_detected` (carries `timestamp` and `probability`) and `agent_false_interruption` — [LiveKit docs: turns](https://docs.livekit.io/agents/build/turns/)
- `AgentFalseInterruptionEvent` has `resumed: bool` ("Whether the false interruption was resumed automatically"). Its `message` and `extra_instructions` fields are deprecated — [events.py @1.8.5](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/events.py)
- v1.5.0 release notes: when the model misdetects an interruption, "playback resumes automatically" — [releases.sh highlights](https://releases.sh/livekit/livekit-agents-python/highlights)

**Adaptive interruption mode/model**
- What it is: an audio-encoder + CNN model that looks at the first few hundred ms of VAD-detected overlapping speech. It uses waveform shape, onset strength/sharpness, duration and prosody (pitch, rhythm) to classify real barge-in vs backchannel or other sounds. It was trained on "hundreds of hours" of human-human one-on-one conversations across many topics and languages, with noise augmentation. The blog post was published 2026-03-19 — [LiveKit blog: Adaptive interruption handling](https://livekit.com/blog/adaptive-interruption-handling)
- Vendor accuracy claims, on a held-out set: 86% precision and 100% recall at 500 ms of overlap speech; rejects 51% of VAD barge-ins; detects true barge-ins faster than VAD in 64% of cases; median 216 ms of audio needed to trigger; inference ≤30 ms. Described as "multilingual" with claimed generalisation to unseen languages. No language list and no per-language or telephony numbers are given — [LiveKit blog](https://livekit.com/blog/adaptive-interruption-handling)
- Availability: Python Agents ≥1.5.0 and TS ≥1.2.0. It runs in LiveKit Cloud data centres at no extra cost for Cloud-deployed agents. Local development gets 40,000 free inference requests per month. The mode is selected via `turn_handling` `interruption.mode` (`"vad"` restores classic behaviour) — [LiveKit blog](https://livekit.com/blog/adaptive-interruption-handling)
- In source, `_resolve_interruption_detection()` returns no detector when: there is no STT (for a cascade), there is no VAD, turn detection is `manual`/`realtime_llm`, interruptions are disabled, or mode is `"vad"`. If mode is unset and the agent is neither hosted on Cloud nor in dev mode, it logs "adaptive interruption is disabled by default in production mode" and falls back to VAD. If the detector hits an unrecoverable error it degrades to VAD-based interruption — [agent_activity.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_activity.py)
- Community: users have asked about a self-hosted or open-weights adaptive model, and no official roadmap was found. An unofficial suggestion is to stay on VAD mode and gate interrupts with your own backchannel classifier — [community.livekit.io: roadmap for self-hosted adaptive](https://community.livekit.io/t/roadmap-for-adaptive-interruption-handling-in-self-hosted-livekit-workers/1172)
- A community thread titled "Adaptive Turn Handling Ignores Single Word Answers" reports a failure mode where short answers are suppressed. Content not read in detail — [community.livekit.io](https://community.livekit.io/t/adaptive-turn-handling-ignores-single-word-answers/1104)
- The turn detector also exposes `backchannel_probability` ("How appropriate it is for the agent to backchannel at this pause"). `on_agent_backchannel_opportunity` exists internally with a TODO to trigger a backchannel phrase, and it is "not surfaced as a public event" — [turn.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/turn.py); [agent_activity.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_activity.py)

**What was actually played**
- `SpeechHandle.interrupted` (property, True once the interrupt future is done), `allow_interruptions` (settable), `interrupt(force=False)`, `wait_for_playout()`, `chat_items` — [speech_handle.py @1.8.5](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/speech_handle.py)
- `PlaybackFinishedEvent` has `playback_position: float` ("How much of the audio was played back"), `interrupted: bool`, and `synchronized_transcript: str | None` ("Transcript synced with playback; may be partial if the audio was interrupted") — [io.py @1.8.5](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/io.py)
- On interruption the agent waits for playout. If its own frames were played, the stored assistant text (`forwarded_text`) is replaced by `synchronized_transcript`. If nothing was played, it becomes `""`. So chat history holds only the heard part — [agent_activity.py ~L3300-3325](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_activity.py)
- For realtime models, LiveKit truncates using `audio_end_ms=int(playback_position*1000)` — [agent_activity.py ~L4568](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_activity.py)
- `use_tts_aligned_transcript` (AgentSession kwarg): "Whether to use TTS-aligned transcript as the input of the transcription_node. Only applies if TTS.capabilities.aligned_transcript is True or streaming is False. When NOT_GIVEN, it's disabled" — [agent_session.py @1.8.5](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_session.py)
- The docs say synchronized transcription is the default, and "if the agent is interrupted, the transcription stops and is truncated to match the spoken output". `sync_transcription=False` disables it — [LiveKit docs: text & transcriptions](https://docs.livekit.io/agents/multimodality/text/)
- `aec_warmup_duration`: "duration in seconds that the agent will ignore user's audio interruptions after the agent starts speaking... to prevent the agent from being interrupted by echo before AEC is ready. Defaults to 3.0, or None for outbound SIP calls" — [agent_session.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_session.py)

### Inferences
- The project is self-hosted (self-hosted Qwen, internal STT). Unless the worker runs on LiveKit Cloud or `mode="adaptive"` is set explicitly with Cloud inference access, production runs in **VAD mode**. In that mode backchannels like "ค่ะ" (~300-500 ms) will pause the bot when `min_duration=0.5` is near their length. Setting `"adaptive"` explicitly while self-hosted means sending audio to LiveKit Cloud inference. That is a data-residency question for an insurance call and is billed beyond dev quota (inference from code; the pricing terms for self-hosted production were not verified).
- Do not rely on `min_words` for Thai. Because of `split_character=True`, "ค่ะ" counts as 3 "words" (ค, ่, ะ), and even `min_words=3` passes it. Thai backchannel filtering needs a custom gate: a lexicon of backchannel tokens matched on the interim or final ASR text, inside a `user_input_transcribed` / `on_user_turn_completed` hook, or by overriding the interruption decision.
- The built-in pause → resume path does roughly what the project's "resume unheard remainder" logic does for short noise. It resumes the *same audio* without any "ต่อนะคะ" bridge. Decide which layer owns resume so you don't get a double resume: either the LiveKit `resume_false_interruption` or the project engine.
- Suggested starting values for a Thai SIP bot, to be tuned on real calls: `min_duration` 0.6–0.8 s while reading facts (backchannel tokens are short), `false_interruption_timeout` 1.0–1.5 s (2.0 s of dead air on a phone feels long), `resume_false_interruption=True`, and a custom Thai backchannel lexicon gate. These are inferences, not vendor recommendations.

### Gaps
- No official list of languages for the adaptive model and no Thai or 8 kHz telephony accuracy figures.
- No official recommended values per use case beyond defaults.
- I did not check whether `can_pause` is True for the SIP audio output path in self-hosted deployments; the pause/resume behaviour depends on it.
- Release dates for 1.6–1.8 and exact version where `turn_handling` replaced flat kwargs were not found (only that 1.8.5 is latest listed).

## 2. Research on backchannels vs turn-taking (incl. Thai)

### Takeaway
Backchannels are well studied as listener tokens cued by speaker prosody: Ward & Tsukahara found a late low-pitch region cues them in English and Japanese. Modern work predicts them frame by frame with Voice Activity Projection (VAP) models. Thai-specific backchannel literature is thin: one Chulalongkorn MA thesis (2015) and work on the polite particles ครับ/ค่ะ. I found no Thai acoustic dataset or classifier.

### Cited Findings
- Skantze, "Turn-taking in Conversational Systems and Human-Robot Interaction: A Review", *Computer Speech & Language* 67 (2021), 101178. A 2025 IWSDS survey treats it as the exhaustive overview of pre-2021 work and covers newer work itself — [IWSDS 2025 survey](https://preview.aclanthology.org/fix-sig-urls/2025.iwsds-1.27.pdf); [Skantze publications](https://kth.se/profile/skantze/publications?l=en)
- Ward & Tsukahara (2000), "Prosodic Features which Cue Back-channel Responses in English and Japanese", *J. Pragmatics*. An important cue in both languages is "a region of low pitch late in an utterance". For English this is ≥110 ms of low pitch, with a backchannel about 700 ms later being well timed — [Ward abstract](https://www.cs.utep.edu/nigel/abstracts/jprag00.html); [Ward backchannel facts](https://www.cs.utep.edu/nigel/bc). Volume is listed as 32 in most sources but 23 on Ward's page; unresolved.
- A later review reports mixed F0 findings across studies, and notes that cue importance can be language-specific — [Frontiers in Communication 2025 PDF](https://public-pages-files-2025.frontiersin.org/journals/communication/articles/10.3389/fcomm.2025.1655049/pdf)
- VAP (Ekstedt & Skantze, Interspeech 2023) is a self-supervised model that predicts the joint future voice activity of both speakers — [ISCA archive](https://www.isca-archive.org/interspeech_2023/ekstedt23b_interspeech.pdf)
- Inoue et al., "Yeah, Un, Oh: Continuous and Real-time Backchannel Prediction with Fine-tuning of VAP" (arXiv 2410.15929; NAACL 2025). It predicts backchannel timing *and type* frame by frame on unbalanced real data, and beats baselines. Feeding the agent's own backchannels back into the model "helps prevent multiple consecutive backchannels" — [arXiv](https://arxiv.org/abs/2410.15929)
- Applying general turn-taking models (VAP) to human-robot interaction is studied in arXiv 2501.08946 (2025) — [arXiv](https://arxiv.org/html/2501.08946v1)
- Thai: Narisra Hasanam (Chulalongkorn MA thesis, 2015) studied the forms, positions and functions of backchannels among equal-status Thai speakers, comparing task-based and daily conversation. I did not read the full text, so the specific tokens are unverified — [CUIR record](https://cuir.car.chula.ac.th/dspace/handle/123456789/51227); [PDF](https://cuir.car.chula.ac.th/dspace/bitstream/123456789/51227/1/5580142422.pdf)
- Prasithrathsint (2019), "Syntactic Distribution and Communicative Function of the /kh/ Polite Particles in Thai", *Journal of Language and Linguistics* 20(1) — [ThaiJO](https://so04.tci-thaijo.org/index.php/joling/article/view/180922)
- Neill (1989, PASAA) covers the Thai particles นะ / ใช่ไหม in narrative as listener-involvement devices — [PASAA](https://digital.car.chula.ac.th/pasaa/vol19/iss1/6)

### Inferences
- In Thai the same tokens (ค่ะ/ครับ/ใช่/อือ) serve both as backchannels *and* as answers to a yes/no confirmation question ("ใช่ค่ะ"). Position, not lexicon, separates them: an overlap mid-utterance is likely a continuer, while a token after the bot's question is an answer. The gate should therefore depend on the bot's state. While reading a fact, treat ค่ะ/ครับ/อือ/อืม/อ๋อ/ใช่ alone as continuers. After a question, never suppress them. This matches the "Adaptive ... ignores single word answers" risk and LiveKit's `backchannel_boundary` end window.
- Long ค่ะ/ครับ sequences in Thai phone calls ("ค่ะ ค่ะ ค่ะ") can exceed 0.5 s. A duration threshold alone will misfire.

### Gaps
- No Thai backchannel corpus, prosodic study or classifier was found. Token frequencies for ค่ะ/ครับ/อือ/อ๋อ/ใช่ as continuers are unknown.
- I did not verify the exact sections of the Skantze review.

## 3. Should the bot produce its own backchannels while the customer gives long feedback?

### Takeaway
Some platforms ship it (Retell's backchannel toggle; LiveKit has an internal, unexposed hook). Research shows timing and quantity matter, and misplaced backchannels are judged inappropriate. On a phone line with a cascade (ASR→LLM→TTS) the risks are high: the bot's own "ค่ะ" can be echoed into the ASR or treated as a turn-take. I found no peer-reviewed study measuring this for voice-only phone bots.

### Cited Findings
- Retell: backchanneling is a dashboard setting (Global Settings → Speech Settings). When enabled, "your AI agent will use acknowledgments during conversations" — [Retell blog (ES)](https://www.retellai.com/es/blog/how-backchanneling-improves-user-experience-in-ai-powered-voice-agents)
- LiveKit 1.8.5 computes `backchannel_probability` but keeps the backchannel opportunity internal ("TODO: consume the backchannel opportunity internally (e.g. trigger a backchannel phrase)") — [agent_activity.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_activity.py)
- Buschmeier & Kopp (2013) varied the quantity, type and timing of artificial-listener backchannels, and had observers press a button when one seemed inappropriate. Placement and quantity affect perceived appropriateness. Embodied agent, not phone — [Univ. Twente record](https://research.utwente.nl/en/publications/perceptual-evaluation-of-backchannel-strategies-for-artificial-li/)
- Inoue et al. found that consecutive self-generated backchannels look unnatural, and fed the agent's own channel back into the model to avoid them — [arXiv 2410.15929](https://arxiv.org/abs/2410.15929)
- Meywirth & Götze (2022): an overhearer study (n=62) on whether a Furhat agent's verbal and non-verbal backchannels convey its state of understanding — [PDF](https://clp.ling.uni-potsdam.de/publications/Meywirth-2022.pdf)

### Inferences
- For a survey's open-ended feedback, a low-rate pre-recorded "ค่ะ" played only at long pauses (e.g., ≥700 ms low-energy gap with the turn detector saying "not end of turn") is plausible. Risks include echo re-entering the ASR transcript, the customer stopping because they think the bot wants the turn, and TTS latency making the backchannel late. A safer default for a PoC is no verbal backchannel during the customer's turn, plus a brief acknowledgement at the *start* of the bot's reply ("ขอบคุณสำหรับความคิดเห็นค่ะ"). Use a pre-cached clip, not live Gemini TTS, if backchannels are added later.
- Bot backchannels should be excluded from the transcript/LLM context and must not count as an agent turn.

### Gaps
- No controlled study found on verbal bot backchannels over PSTN, or in Thai.

## 4. Best practice when interrupted mid-fact: repeat, continue, or ask

### Takeaway
Frameworks agree on one thing: record only what was heard (LiveKit `synchronized_transcript`, OpenAI `conversation.item.truncate`). How to resume is left to the application. Conversation analysis shows that humans recycle turn beginnings after overlap. That supports restarting at the current *sentence/fact boundary* rather than mid-word or replaying the whole monologue.

### Cited Findings
- Schegloff, "Recycled turn beginnings": speakers often repeat or re-say parts of their utterances, specifically at turn beginnings. It is described as a precise repair mechanism in turn-taking — [conversationanalysis.org PDF](https://conversationanalysis.org/mp-files/recycled-turn-beginnings.pdf)
- Schegloff (2000, *Language in Society*) proposes an overlap resolution device (resources, places, interactional logic) for *competitive* overlap. Continuers and terminal overlaps are explicitly excluded, i.e. backchannels are not treated as competitive overlap — [EMCA wiki: Overlap](https://emcawiki.net/Overlap); [Schegloff 2000](https://mail.emcawiki.net/Schegloff2000)
- An applied case study (geopolitical debate) coded 22 overlap resolutions: withdrawal 10, persistence 8, acoustic upgrade 4 — [UIN SGD repository](https://digilib.uinsgd.ac.id/138718/)
- LiveKit 1.8.5 keeps only the played portion in chat history when interrupted — [agent_activity.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_activity.py)

### Inferences
- Recommended policy for policy confirmation (inference):
  1. **Real interruption with content**: answer the customer first. Then resume from the start of the interrupted *fact*, not mid-sentence. A fact read in half does not count as confirmed for compliance purposes. Skip facts already fully heard.
  2. **False interruption / backchannel**: continue from the cut point with a short bridge ("ต่อนะคะ") only if the pause was >~1 s. Otherwise just resume silently.
  3. **Repeated interruptions on the same fact (≥2)**: ask ("ให้ทวนข้อมูลส่วนนี้อีกครั้งไหมคะ") instead of replaying.
  4. Keep facts short, one sentence each, so the resume unit is small. Never replay a whole monologue.
- This fits the project's existing per-segment delivery tracking. `synchronized_transcript` granularity depends on TTS alignment. With Gemini TTS (no word timestamps known), LiveKit estimates sync from the audio duration, so treat the cut point as approximate and snap to the segment boundary.

### Gaps
- No empirical study found comparing repeat vs continue vs ask for interrupted bot speech. No documented human call-centre script guidance was found.
- I did not verify whether Gemini TTS in LiveKit advertises `aligned_transcript`.

## 5. Echo/AEC and noise causing false barge-in on SIP; Krisp/noise cancellation

### Takeaway
On SIP there is no client-side WebRTC AEC, and LiveKit's `aec_warmup_duration` is disabled (None) for outbound SIP by default. Line echo and background noise therefore reach VAD directly. LiveKit's Krisp `BVCTelephony` (tuned for 8 kHz) is the recommended agent-side filter, but it requires LiveKit Cloud media transport. A self-hosted stack needs an alternative such as ai-coustics with its own licence.

### Cited Findings
- `aec_warmup_duration` defaults to 3.0 s, or `None` for outbound SIP calls. During warmup `_interrupt_by_audio_activity` returns early — [agent_session.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_session.py); [agent_activity.py](https://github.com/livekit/agents/blob/livekit-agents%401.8.5/livekit-agents/livekit/agents/voice/agent_activity.py)
- `BVCTelephony()` is optimised for narrow-band 8 kHz telephony audio. `BVC()` on telephony "may produce suboptimal results". The guide shows choosing per participant kind. It runs on agent CPU with "typically less than 10ms" added latency — [LiveKit field guide](https://livekit.com/field-guides/guide/noise-cancellation-agents-sip)
- Use only one enhanced NC stage: don't also enable Krisp on the SIP trunk (`krisp_enabled`) when filtering in the agent. A community thread instead recommends trunk-level Krisp for multi-party calls, which conflicts with the field guide — [field guide](https://livekit.com/field-guides/guide/noise-cancellation-agents-sip); [community thread](https://community.livekit.io/t/best-practice-for-sip-noise-cancellation-in-livekit-cloud/213)
- Enhanced NC is available when using LiveKit Cloud for transport. Staff on the community forum said BVC/NC are cloud-only and pointed self-hosters to ai-coustics. The docs list ai-coustics as supported with your own licence key — [LiveKit docs: enhanced NC](https://docs.livekit.io/transport/media/enhanced-noise-cancellation/); [community: self-hosted NC](https://community.livekit.io/t/questions-on-recording-noise-cancellation-in-self-hosted-livekit-setup/968); [LiveKit blog: noise cancellation](https://livekit.com/blog/noise-cancellation)
- All voice-isolation models incur extra cost. One user hit a "not authenticated" error with BVCTelephony in Node.js — [field guide](https://livekit.com/field-guides/guide/noise-cancellation-agents-sip); [community: voice isolation payment](https://community.livekit.io/t/voice-isolation-system-payment/1657)
- Adaptive interruption was trained with noise augmentation, and LiveKit claims it filters coughs, sighs, typing and music. No numbers were given for telephony — [LiveKit blog](https://livekit.com/blog/adaptive-interruption-handling)
- Retell forum users say interruption behaviour differs between the test agent and live phone calls, and that the default denoise mode does not remove loud background speech — [Retell community](https://community.retellai.com/t/interruption-sensitivity-doesnt-work/358)

### Inferences
- In self-hosted Thai SIP tests, expect false barge-ins from: carrier echo of the bot's own TTS (especially on mobile handsets on speaker), TV/background speech, and "ค่ะ" continuers. Mitigations: VAD activation threshold raised, `min_duration` raised during fact reading, a lexicon gate, and possibly a manual echo guard (e.g., set a custom warmup or ignore VAD in the first ~300 ms of each bot segment). Test on the actual carrier.
- If Krisp is unavailable, compare ai-coustics against plain VAD-threshold tuning before paying for it.

### Gaps
- I found no data on the echo return loss of Thai mobile carriers, or on false barge-in rates with and without BVCTelephony.
- The official noise-cancellation `.md` page returned 404, so I could not confirm the exact Python API for self-hosted ai-coustics.

## 6. How other frameworks handle it

### Takeaway
All mainstream stacks use a combination of (a) a min-speech-duration / min-words threshold, (b) optional backchannel or acknowledgement-phrase lists, and (c) truncating the assistant message to what was played. Vapi and Pipecat expose word-count gates and phrase lists. OpenAI Realtime exposes explicit truncation by `audio_end_ms`. Retell exposes a single 0–1 sensitivity knob plus a backchannel toggle.

### Cited Findings
- **Pipecat**: `MinWordsInterruptionStrategy(min_words=3)` (from `pipecat.audio.interruptions.min_words_interruption_strategy`; must be >0). Speech while the bot talks is buffered, and strategies are evaluated when the user stops speaking. The first True triggers interruption; otherwise "the user speech is discarded". Newer versions have user-turn strategies: `MinWordsUserTurnStartStrategy(min_words, use_interim)`, where min_words applies only while the bot is speaking (one word suffices otherwise) — [Pipecat interruption strategies](https://docs.pipecat.ai/server/utilities/interruption-strategies); [Pipecat user turn strategies](https://docs.pipecat.ai/server/utilities/turn-management/user-turn-strategies); [API reference](https://reference-server.pipecat.ai/en/latest/api/pipecat.turns.user_start.min_words_user_turn_start_strategy.html)
- **OpenAI Realtime**: `conversation.item.truncate` with `item_id`, `content_index` (0), and `audio_end_ms` (inclusive ms). Only assistant items can be truncated, and doing so deletes the server-side text transcript so the model does not keep unheard text. An error is returned if `audio_end_ms` exceeds the audio length. The server confirms with `conversation.item.truncated` — [LangChain mirror of OpenAI types](https://v03.api.js.langchain.com/interfaces/_langchain_openai.OpenAIClient.Beta.Realtime.ConversationItemTruncateEvent.html); [LiveKit JS reference](https://docs.livekit.io/reference/agents-js/interfaces/plugins_agents_plugin_openai.realtime.ConversationItemTruncatedEvent.html). The official OpenAI page returned 403, so this is from mirrors.
- A community report says that after truncation the transcript still contained ~5–10 s of unheard speech, so client-side trimming is advisable — [OpenAI community](https://community.openai.com/t/realtime-api-interruptions-dont-properly-trim-the-transcript/1000703)
- **Vapi** `stopSpeakingPlan`: `numWords` (0 = fastest; raise to 2–3 to avoid "okay"/"right" interrupting), `voiceSeconds` (quick-start 0.2), `backoffSeconds` (default configs 1.0). Recommended general start is numWords 0 / voiceSeconds 0.2 / backoffSeconds 1. A Deepgram Flux example uses numWords 2 with an `acknowledgementPhrases` list (okay, right, uh-huh, yeah…) that does not count as interruptions — [Vapi speech configuration](https://docs.vapi.ai/customization/speech-configuration); [Vapi voice pipeline configuration](https://docs.vapi.ai/customization/voice-pipeline-configuration)
- **Retell**: interruption sensitivity 0–1 (higher = easier to interrupt; 0 reportedly never interrupts, per a forum post), responsiveness 0–1, denoising modes (noise only vs noise + background speech), and a backchannel toggle — [Retell community](https://community.retellai.com/t/agent-interruption/922/2); [Retell blog](https://www.retellai.com/es/blog/how-backchanneling-improves-user-experience-in-ai-powered-voice-agents)
- Vendor (Iqra AI) docs suggest an LLM classifier for short overlapping utterances (noise / backchannel / barge-in), claiming ~300 ms added latency. Not peer-reviewed — [Iqra AI docs](https://www.mintlify.com/abdofallah/IqraAI/building/interruptions)

### Inferences
- The project's lexicon-gate + segment-resume design is the same pattern as Vapi's `acknowledgementPhrases` + numWords and Pipecat's buffered evaluation, adapted for Thai, where word counting fails. An explicit Thai acknowledgement list (ค่ะ, คะ, ครับ, อือ, อืม, อ๋อ, ใช่, โอเค, ได้, เออ, ฮะ, จ้ะ, นะ…) applied *only while the bot is reading* is the closest equivalent.

### Gaps
- I could not fetch the official Retell docs (404) for exact API parameter names (e.g., `interruption_sensitivity`, `enable_backchannel`, `backchannel_frequency`, `backchannel_words`); these names are unverified.
- Vapi `backoffSeconds` semantics were not clearly defined in the retrieved sources.
