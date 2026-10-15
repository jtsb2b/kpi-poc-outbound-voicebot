# Evaluating Human-Likeness and Conversational Quality of a Thai Outbound Insurance Voicebot

Scope: metrics, test methods and tooling usable (a) in the existing text simulator (scripted scenarios + LLM interpreter) before ASR/TTS exist, and (b) on live LiveKit + Thai ASR + Gemini TTS + SIP calls. Research as of 2026-10-08. Source reliability is tagged throughout: [STANDARD] = ITU-T or peer-reviewed or archival academic; [FRAMEWORK DOC] = official open-source framework docs (LiveKit, Pipecat); [VENDOR] = commercial vendor blog/marketing with unpublished data.

## Q1. Quantitative metrics (latency, endpointing, interruption, turn length, repetition, task success, containment, escalation)

### Takeaway
No standards body defines voice-agent latency/interruption targets; the usable numbers come from (i) conversation-analysis research on human turn gaps, (ii) framework telemetry (LiveKit exposes end-of-turn and transcription delay), and (iii) vendor benchmarks that disagree with each other. Use percentile (p50/p90/p95) voice-to-voice latency plus barge-in stop time and false-barge-in rate as the core live-call metrics, and turn length, repetition, slot accuracy and task success as the text-simulator metrics.

### Cited Findings
**Human baseline for turn gaps [STANDARD]**
- Stivers et al. (PNAS 2009), 10 languages: all languages avoid overlap and minimise silence between turns; cross-language differences in mean gap are bounded within about 250 ms of the cross-language mean; the same factors explain response-speed variation in every language; differences are "quantitative only". — [Stivers et al. 2009 abstract via MPI](https://forms.mpi.nl/node/50939); [emcawiki entry](https://emcawiki.net/Stivers-etal2009)
- Full-Duplex-Bench samples human "smooth turn-taking" gaps as < 0.4 s and natural mid-turn pauses as 0.4–1.0 s (from the Candor corpus), i.e. a pause of up to 1 s inside a user turn is normal and must not trigger a bot takeover. — [Full-Duplex-Bench, arXiv 2503.04721](https://arxiv.org/html/2503.04721v3)

**Framework telemetry (what LiveKit actually reports) [FRAMEWORK DOC]**
- LiveKit `end_of_utterance_delay`: time from VAD-detected end of speech to the point the user's turn is considered complete; it includes `transcription_delay` (end of speech to final transcript). Newer docs rename it `end_of_turn_delay`. — [LiveKit JS EOUMetrics reference](https://docs.livekit.io/reference/agents-js/types/agents.metrics.EOUMetrics.html); [LiveKit observability data](https://docs.livekit.io/deploy/observability/data)
- Community report (LiveKit v1.6): most end-of-turn delay was waiting for the STT provider's final transcript (~0.53 s), not the turn detector; a separate PR fixed `transcription_delay` wrongly reading ~0 s with STT-based turn detection — verify SDK version before trusting the numbers. — [LiveKit community thread](https://community.livekit.io/t/eot-value-leads-to-around-30-of-e2e-latency-tried-reducing-min-max-endpointint-in-turn-delay-plugin-but-no-luck/1450); [livekit/agents PR 4396](https://github.com/livekit/agents/pull/4396)
- Another community thread: component totals (ASR+LLM+TTS) < 1 s while speech-end-to-reply was 3–4 s — illustrates why voice-to-voice latency must be measured end-to-end, not summed from components. — [LiveKit community](https://community.livekit.io/t/high-end-to-end-latency-asr-llm-tts-total-1s-but-speech-end-to-reply-takes-3-4s-livekit-agents/1277)
- LiveKit adaptive interruption handling (Python agents v1.5.0+, Node v1.2.0+, LiveKit Cloud): an audio ML model run after VAD that separates backchannels ("uh-huh", "okay") from genuine barge-ins without waiting for a transcript; `backchannel_boundary` default (1.0, 1.0) means VAD-only handling for the first second of agent speech. On a detected false interruption, the agent resumes playback (`resume_false_interruption`, `false_interruption_timeout`, now under `TurnHandlingOptions`). No accuracy numbers are published. — [LiveKit adaptive interruption docs](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/); [LiveKit turn handling options](https://docs.livekit.io/reference/agents/turn-handling-options.md); [v1.5.0 release thread](https://community.livekit.io/t/python-agents-1-5-0-released/619)

**Vendor latency / interruption thresholds [VENDOR — unpublished data, internally inconsistent]**
- Hamming "4-layer framework": Infrastructure (audio, latency, ASR/TTS), Execution (intent, response accuracy, tool calls), User Behavior (interruptions, flow, sentiment), Business Outcome (containment, FCR, escalation). — [Hamming: How to evaluate voice agents 2026](https://hamming.ai/blog/how-to-evaluate-voice-agents-2026)
- Hamming targets in that article: Time to First Audio < 800 ms (VAD endpoint to first TTS byte at the user's device); end-to-end p50 < 1.5 s, p90 < 2.5 s (critical > 3.0 s), p95 < 3.5 s, p99 < 8 s; per-stage STT < 200 ms, LLM TTFT < 400 ms, TTS TTFB < 150 ms, network < 100 ms, turn detection < 400 ms; jitter SD < 100 ms. — [Hamming](https://hamming.ai/blog/how-to-evaluate-voice-agents-2026)
- Hamming's "methodology" page (claims 4M+ calls, 10K+ agents, 2025–26) gives different tiers: TTFW excellent < 300 / good < 500 / acceptable < 800 ms; p50 turn latency < 1600/1800/2000 ms; p90 < 2200/2500/3000 ms; p99 < 3000/3500/4000 ms. — [Hamming methodology](https://hamming.ai/methodology). Contradicted on p99 (8 s vs 4 s) by the evaluation article above.
- Hamming barge-in metrics: detection accuracy > 95%, false-positive (noise stops agent) < 5%, false-negative < 5%, interruption response latency < 200 ms from user speech onset to TTS suppression. — [Hamming](https://hamming.ai/blog/how-to-evaluate-voice-agents-2026)
- Hamming endpointing settings: aggressive 200–300 ms, balanced 400–600 ms, conservative 700–1000 ms silence before finalising. — [Hamming](https://hamming.ai/blog/how-to-evaluate-voice-agents-2026)
- Cekura: measures "interruption overrun" in ms (how long TTS kept playing after user speech began), detects overlaps < 300 ms, judges post-interruption recovery by instruction following and workflow success; claims natural conversation needs voice-to-voice < 1,500 ms and warns an agent averaging 380 ms can still give 5% of callers a 2 s wait. — [Cekura barge-in testing](https://www.cekura.ai/discover/voice-ai-barge-in-testing-asr-latency-tts-overrun); [Cekura metrics blog](https://www.cekura.ai/blogs/voice-ai-evaluation-metrics)

**Task / business metrics [VENDOR]**
- Task Success Rate = successful / attempted, success requires all goals met, no constraint violations, required actions done; target > 85% (critical < 75%); by use case: scheduling > 90%, order taking > 85%, support > 75%, information lookup > 95%. — [Hamming](https://hamming.ai/blog/how-to-evaluate-voice-agents-2026)
- Containment = agent-handled / total calls; target > 70%; "leading contact centers 80%+, most deployments 60–75%, early 40–60%"; pair with satisfaction to avoid trapping frustrated callers. — [Hamming](https://hamming.ai/blog/how-to-evaluate-voice-agents-2026)
- WER target < 10% (clean), < 15% office noise, < 20% street/accents; plus entity accuracy for names, dates, numbers. Reprompt rate (clarifications / turns) < 10%. Sentiment trajectory: > 80% of calls stable or improving. — [Hamming](https://hamming.ai/blog/how-to-evaluate-voice-agents-2026)
- Hamming call analytics also tracks interruption rate, silence gaps, fallback/clarification rate, transfer rate, flow drop-off points. — [Hamming call analytics](https://hamming.ai/blog/call-analytics-voice-agent-testing)
- Cekura conversational-flow metrics include repetition frequency, silence detection, call-termination accuracy, each timestamped. — [Cekura metrics blog](https://www.cekura.ai/blogs/voice-ai-evaluation-metrics)
- Coval voice metric groups: latency (STT/LLM/TTS TTFB, end-to-end turn latency), turn-taking (interruption rate, agent-fails-to-respond, repeated turns), audio quality (natural tone, pause analysis, speech tempo). — [Coval simulations overview](https://docs.coval.dev/concepts/simulations/overview)

### Inferences
- Recommended metric set for this project:
  - Text simulator (pre-ASR/TTS): bot words/characters per turn and estimated speech duration per turn (Thai chars ÷ assumed TTS rate) against the 4–7 s target / 12 s max; % turns > 12 s; question-per-turn count; repetition rate (n-gram overlap with previous bot turns, repeated customer-name mentions); slot accuracy per required field (policy number, consent, callback time, etc.); task success per scenario; escalation-correctness (escalated when it should, not otherwise); LLM-interpreter intent accuracy against scripted ground truth.
  - Live calls: voice-to-voice latency (user VAD end -> first bot audio at the SIP leg) p50/p90/p95; LiveKit end_of_turn_delay and transcription_delay distributions; barge-in stop time (user speech onset -> TTS silenced) p50/p90; false-barge-in rate (bot stopped by noise/backchannel); missed-barge-in rate; bot-takeover-during-user-pause rate (Full-Duplex-Bench TOR on pauses); overlap seconds per call; dead-air > 2 s count; actual TTS seconds per turn.
- Reasonable internal targets synthesised from the above (not a standard): voice-to-voice p50 ≈ 1.0–1.5 s, p90 ≤ 2.5 s; barge-in stop ≤ 200–300 ms; false barge-in ≤ 5%; bot must not take over in 0.4–1.0 s user pauses. Human gaps are much shorter (~sub-0.5 s), so a cascaded ASR-LLM-TTS stack over SIP will remain measurably slower than humans; fillers/backchannel acknowledgements are the usual mitigation.
- Measure latency at the telephony edge (SIP), not inside the agent process, because SIP/PSTN legs add delay that framework metrics omit.

### Gaps
- No ITU-T or other standard sets voice-agent latency/barge-in targets; all thresholds above are vendor claims with unpublished data and vary between pages of the same vendor.
- Exact human mean turn gap figure (often quoted as ~200 ms) was not verified from the Stivers paper text in this session; only the ±250 ms cross-language bound was confirmed.
- No published Thai-specific turn-gap norms or Thai telephone endpointing studies were found.
- Accuracy of LiveKit's adaptive interruption model (false/missed barge-in rates) is not published, and not known for Thai speech.

## Q2. Perceptual evaluation (MOS/CMOS, human-likeness scales, Turing tests, P.800/P.808, questionnaires, sample sizes)

### Takeaway
ITU-T P.800 (lab ACR/MOS) and P.808 (crowdsourced ACR) are the established standards for perceived speech quality, and ~60 votes per condition is an evidence-backed crowdsourcing minimum. For whole-conversation human-likeness there is no standard: SASSI (speech-interface usability) and Godspeed (anthropomorphism/likeability) are the most-cited questionnaires but both have psychometric caveats and neither is validated in Thai.

### Cited Findings
- P.808 crowdsourcing has been validated as highly correlated with lab tests when implemented per the Recommendation (Naderi & Cutler). — [P.808 multilingual SE testing, arXiv 2507.11306](https://arxiv.org/html/2507.11306v2); [Open-source P.808 implementation, arXiv 2005.08138](https://arxiv.org/pdf/2005.08138) [STANDARD/academic]
- The open-source P.808 implementation (Amazon MTurk) quantifies the reliability value of environment tests, gold/trapping questions, rating-pattern checks and headset-usage checks. — [arXiv 2005.08138](https://ar5iv.arxiv.org/html/2005.08138)
- Number of votes: Naderi et al. recommend at least 60 votes per test condition as the compromise between cost, reliability and validity; correlation with lab MOS plateaus around 60 votes; a 95% CI width < 0.3 needs ~115 votes per condition; crowd-vs-lab SRCC 0.89–0.97, RMSE 0.32–0.48 (before mapping). Lowest agreement was a German crowd rating Swiss-German speech — i.e. listener language/dialect match matters. — [Impact of the Number of Votes, arXiv 2003.11300](https://ar5iv.arxiv.org/html/2003.11300) [academic]
- ThaiMOS (from the AudioJudge study): 600 utterances from 11 Thai TTS systems rated by 16 paid raters (DataWow) on 1–5 scales for sound quality, rhythm and pronunciation (not a single naturalness score). — as summarised from [AudioJudge, arXiv 2507.12705](https://arxiv.org/pdf/2507.12705) (details from search snippet; not verified in full text)
- Typhoon 2 (Thai) reports TTS naturalness only via UTMOS (a model predictor, not listeners): Azure 4.06, Seamless 3.71, MMS-TTS 3.71, GCP 3.60, Typhoon2-Audio 3.13, PyThaiTTS 2.79. Notes accent effects in code-switched English. — [Typhoon 2, arXiv 2412.13702](https://arxiv.org/pdf/2412.13702)
- A Thai study (2022) used 16 male + 16 female Thai listeners to rate Siri vs Google Translate Thai speech (3.16 ± 0.77 vs 3.53 ± 0.67). — [Chula ETD record](https://digital.car.chula.ac.th/chulaetd/4643) (from search snippet)
- A 2026 Thai TTS paper notes MOS "requires Thai-specific evaluation infrastructure" and uses other dimensions instead. — [Fixed-Voice Thai TTS, arXiv 2609.03502](https://arxiv.org/pdf/2609.03502) (search snippet)
- SASSI (Hone & Graham, Natural Language Engineering 2000): prototype 50 statements tested on 4 speech applications; published factors System Response Accuracy, Likeability, Cognitive Demand, Annoyance, Habitability, Speed (often summarised as 34 items). Reliability/concurrent validity/sensitivity data were not provided; Weiss et al. (2008) suggested scales may need revision; Hone (2014) called for turning it into a fully validated tool. — [SASSI page, Brunel](https://people.brunel.ac.uk/~csstksh/sassi.html); [Cambridge abstract](https://cambridge.org/core/journals/natural-language-engineering/article/abs/towards-a-tool-for-the-subjective-assessment-of-speech-system-interfaces-sassi/29E49E8449B9E96CDEE2581D0000BA98); [MeasuringU review](https://measuringu.com/voice-interaction/); [Hone 2014](https://www.cs.toronto.edu/dsli2014/submissions/Hone_CHI_workshop_paper-2014.pdf)
- Godspeed Questionnaire Series (Bartneck et al. 2009): anthropomorphism, animacy, likeability, perceived intelligence, perceived safety; 5-point semantic differentials (e.g. fake–natural, machinelike–humanlike). Widely used (>160 citations by 2014); generally consistent reliability except Perceived Safety, but indices correlate strongly with each other; chatbot studies drop embodiment-specific items. Translations exist (e.g. Dutch, Chinese) — no Thai version found. — [Godspeed in HRI scale database](https://hriscaledatabase.psychology.gmu.edu/attitudes/attributes/2024/10/31/Godspeed.html); [Weiss & Bartneck 2015 meta-analysis](https://www.bartneck.de/publications/2015/metaAnalysisGodspeedQuestionnaire/index.html); [Bartneck translations](https://www.bartneck.de/tag/godspeed)
- Talking Turns ran a user study on live spoken dialogue systems in addition to model-based judging. — [Talking Turns, arXiv 2503.01174](https://arxiv.org/pdf/2503.01174)

### Inferences
- Practical design for Gemini TTS Thai voice: P.808-style ACR (1–5) naturalness on isolated bot utterances, ≥ 60 votes per condition (e.g. 15–20 native Thai raters × several utterances), with gold/trap items; CMOS (A/B, −3..+3) when comparing two TTS settings or prompt styles, since paired comparison is more sensitive for small differences.
- For whole-call human-likeness: record live/simulated calls, have native Thai raters (ideally ex-call-center QA staff) rate on (a) adapted Godspeed anthropomorphism + likeability items translated to Thai, (b) a few SASSI items (Likeability, Annoyance, Speed), (c) a Turing-style "human or bot?" forced choice on 20–40 s call excerpts mixed with real human-agent recordings. Report % judged human with CI.
- Rater language must match: the Swiss-German result implies non-Thai or non-native crowd raters would invalidate results.

### Gaps
- I did not fetch the ITU-T P.800 / P.808 / P.800.2 texts themselves; exact clauses (e.g., minimum listener counts in P.800 lab tests, CMOS procedure in P.800 Annex) are not quoted here.
- No validated Thai translation of SASSI or Godspeed was found; no standard human-likeness Turing test protocol for voice agents was found.
- No published study of how many listeners are needed for whole-conversation (vs utterance) naturalness ratings.

## Q3. LLM-as-judge for dialogue naturalness, and simulated-user testing tools

### Takeaway
LLM judges reach roughly human-human agreement on pairwise preference (>80% for strong models) but show position and verbosity biases, and no study found validates them specifically on dialogue naturalness or on Thai. Simulated-user frameworks (LiveKit, Pipecat, Coval, Cekura, Hamming) all combine scripted/persona callers with LLM-judged assertions; framework tools are best for CI regression on behaviour, vendor platforms add audio personas, noise and timing metrics.

### Cited Findings
**LLM judges: reliability and bias**
- Zheng et al. (NeurIPS 2023, MT-Bench/Chatbot Arena): strong judges like GPT-4 reach > 80% agreement with human preferences, the same level as human-human agreement; documented position, verbosity and self-enhancement biases (self-enhancement not conclusively shown). — [NeurIPS 2023 poster](https://nips.cc/virtual/2023/poster/73434) [academic]
- MTalk-Bench (speech-to-speech multi-turn): humans showed almost no position preference, while Gemini-2.5-pro favoured top-positioned responses by ~4.7%; length bias +17.3% for LLM judges vs +12.9% for humans. — [MTalk-Bench, arXiv 2508.18240](https://arxiv.org/pdf/2508.18240) [academic]
- Judge's Verdict: 27 of 54 LLMs reached "Tier 1" (r ≥ 0.80 with humans plus a human-likeness test). — [arXiv 2510.09738](https://arxiv.org/html/2510.09738v1)
- AudioJudge (large audio models as judges): a multi-aspect ensemble (separate lexical, speech-quality, paralinguistic judges) reaches up to 0.91 Spearman with human system rankings; audio concatenation + in-context examples help; significant verbosity and positional biases; robust to acoustic noise. — [AudioJudge, arXiv 2507.12705](https://arxiv.org/abs/2507.12705)
- Full-Duplex-Bench uses GPT-4o as a 0–5 judge of response relevance after interruptions. — [Full-Duplex-Bench](https://arxiv.org/html/2503.04721v3)
- Standard mitigations: evaluate both orderings and keep consistent verdicts; instruct the judge to penalise unneeded length. — [Zheng et al. summary via Manning](https://livebook.manning.com/book/evaluation-and-alignment-the-seminal-papers/chapter-4) (secondary)

**Simulated-user / test tooling**
- LiveKit [FRAMEWORK DOC]: pytest-based tests run an `AgentSession` in text mode, send user input, and assert with `.judge(llm, intent=...)`, check tool calls, and `no_more_events()`. `livekit.agents.evals` provides `JudgeGroup` (run in `on_session_end`, auto-tags the session) with built-in judges such as `task_completion_judge`, `accuracy_judge` (claims must be grounded in function-call outputs; docs suggest it for healthcare, insurance, finance) and `coherence_judge` (no contradictions or abrupt topic jumps). `EvaluationResult` score: pass = 1, maybe = 0.5, fail = 0; `all_passed` treats maybe as fail. A field guide shows an evaluator agent playing the user and recording PASS/FAIL via a function tool (`evals_agent.py`). — [LiveKit evals reference](https://docs.livekit.io/reference/python/livekit/agents/evals/evaluation.html); [livekit.agents.evals](https://docs.livekit.io/reference/python/livekit/agents/evals/index.html); [LiveKit testing overview](https://docs.livekit.io/agents/start/testing.md) (search snippet; direct fetch returned 404); [LiveKit field guide](https://livekit.io/field-guides/guide/testing-agent-with-evaluation-agent)
- A vendor critique notes LiveKit's text-mode judge assertion catches a single bad response but not tone drift over ten turns. — [TestMu AI blog](https://www.testmuai.com/blog/livekit-agent-testing/) [VENDOR]
- Pipecat Evals [FRAMEWORK DOC]: YAML scenarios of user turns + expectations, judged by an LLM on meaning not strings; text mode skips STT/TTS (seconds per test, no audio cost); audio mode synthesises user speech; `-t eval` transport runs the real pipeline over a local WebSocket; exposed as a Python library for pytest/CI. Positioned for development, not production monitoring. — [Pipecat evals overview](https://docs.pipecat.ai/pipecat/evals/overview); [Pipecat evals library](https://docs.pipecat.ai/pipecat/evals/library)
- Coval [VENDOR]: simulated caller personas with configurable voices, background environments, interruption rates and emotional progression; test sets as free-form prompts (generative) or exact transcripts / pre-recorded audio (deterministic regression); custom LLM-judge metrics; re-run a single metric, compare runs, send to human review; CLI for CI. — [Coval simulations](https://docs.coval.dev/concepts/simulations/overview); [Coval onboarding](https://docs.coval.dev/agents/onboarding); [Coval CLI](https://docs.coval.dev/cli)
- Cekura [VENDOR]: 50+ predefined caller personalities incl. "Interrupter" and "Pauser", background noise, interruption frequency; reports mean/P50/P90 latency, time to first audio, interruption overrun, repetition, silence, termination accuracy; integrations for Pipecat, Vapi. — [Cekura voice AI evals](https://www.cekura.ai/blogs/voice-ai-evals); [Cekura Pipecat](https://www.cekura.ai/blogs/test-pipecat-voice-agents); [Cekura Vapi](https://cekura.ai/blogs/from-prompt-to-production-how-to-test-vapi-voice-agents)
- Hamming [VENDOR]: claims sentiment scoring with 85%+ agreement with human raters (no data published). — [Hamming](https://hamming.ai/blog/how-to-evaluate-voice-agents-2026)

### Inferences
- For this project's text simulator: keep deterministic checks (turn length, slot extraction, forbidden phrases, name-repetition count) in code, and use an LLM judge only for subjective items (politeness, empathy, naturalness, coherence), with a written Thai rubric, small integer scale, rationale-before-score, both-order evaluation for pairwise comparisons, and an explicit penalty for long turns (to counter verbosity bias, which directly conflicts with the 4–7 s target).
- Calibrate the judge: have 2–3 Thai QA raters label ~100 simulated conversations; require judge–human agreement (Cohen's kappa or Spearman) comparable to human–human agreement before trusting it; re-check whenever the judge model changes. Avoid using the same model family (Qwen) as both bot and judge to reduce self-enhancement risk.
- Since the stack is LiveKit, the cheapest path is LiveKit pytest tests + `JudgeGroup` (accuracy_judge is relevant to insurance facts) plus a user-simulator agent; Coval/Cekura/Hamming add audio personas and timing, but Thai voice persona support was not verified.

### Gaps
- No study found that measures LLM-judge agreement with humans specifically on spoken-dialogue *naturalness*, or on Thai dialogue.
- Thai-language support (Thai synthetic caller voices, Thai ASR in the simulator) for Coval, Cekura, Hamming and Vapi test suites was not verified.
- Vapi test-suite capabilities were not researched in detail this session.

## Q4. Full-duplex / turn-taking benchmarks and the failure modes they reveal

### Takeaway
Full-Duplex-Bench (v1, v1.5, v2) and Talking Turns show that current voice systems mostly fail on *when* to speak: they take over during user pauses, rarely or wrongly backchannel, interrupt too aggressively, or respond slowly/incoherently after interruptions. These are exactly the behaviours that make a bot sound non-human, and the benchmark metrics can be reused on our own recorded calls.

### Cited Findings
- Full-Duplex-Bench v1 metrics: Takeover (TO = 0 if silent or backchannel, 1 otherwise), Takeover Rate (lower is better for pause handling and backchannel; higher for turn-taking and interruption); backchannel = < 1 s and < 2 words; backchannel frequency; JSD of backchannel timing vs human distribution over 200 ms windows; latency (user end to model start, only when TO = 1); after-interruption GPT-4o relevance score 0–5. English only; behaviours not linked to human preference. — [Full-Duplex-Bench, arXiv 2503.04721](https://arxiv.org/html/2503.04721v3) [academic]
- Results: Moshi takes over in pauses 98% of the time and almost never backchannels (TOR 1.0 in backchannel test) but responds in ~0.27 s; Freeze-Omni misses turn ends (turn-taking TOR 0.336, 0.95 s latency); Gemini Live handles pauses best (pause TOR 0.26–0.31) but turn-taking latency 1.30 s and after-interruption latency 1.18 s; dGSLM after-interruption latency 2.5 s and very low relevance (0.20/5). Fast models often fail to yield; cautious ones are slow. — [Full-Duplex-Bench](https://arxiv.org/html/2503.04721v3)
- v1.5 adds four overlap events (user interruption, user backchannel, user talking to others, background speech) with behaviour labels (RESPOND/RESUME/UNCERTAIN) and stop latency and response latency under overlap. — summary from search results referencing [Full-Duplex-Bench line of work](https://arxiv.org/html/2503.04721v3) (v1.5 paper not fetched)
- v2 (multi-turn) uses an automated examiner that follows up, interrupts and adapts; metrics: turn-taking fluency, instruction following, task competencies (correction handling, entity tracking, safety). — [Full-Duplex-Bench-v2, arXiv 2510.07838](https://arxiv.org/html/2510.07838v1)
- Caveat: papers redefine TOR/latency differently (some count pre-event speech as takeover, yielding negative latency) — numbers not comparable across papers. — search summary of follow-up work e.g. [French Full-Duplex Benchmark, arXiv 2609.10765](https://arxiv.org/pdf/2609.10765)
- Talking Turns (Arora et al., CMU + Apple, ICLR 2025): uses a supervised turn-taking model trained on human-human conversation (Switchboard) as a judge, plus a user study; finds systems fail to judge when to speak up, interrupt too aggressively, and rarely backchannel. — [Talking Turns, arXiv 2503.01174](https://arxiv.org/pdf/2503.01174); [ICLR 2025](https://iclr.cc/virtual/2025/poster/31129)
- Further 2025–26 benchmarks exist (FLEXI, M3-DuplexBench multilingual/multidomain), indicating an active area. — [FLEXI, arXiv 2509.22243](https://arxiv.org/pdf/2509.22243); [M3-DuplexBench, arXiv 2607.29125](https://arxiv.org/pdf/2607.29125) (titles only; contents not reviewed)

### Inferences
- Our cascaded LiveKit stack is half-duplex with barge-in, so the relevant borrowed tests are: (1) pause handling — inject 0.4–1.0 s pauses mid-sentence in Thai test audio and measure bot takeover rate; (2) backchannel robustness — play "ครับ/ค่ะ/อืม/ใช่" while the bot talks and measure false stop rate (should not stop, or should resume); (3) interruption — user barges in ~mid-utterance, measure stop latency and whether the next response addresses the interruption (LLM-judged relevance); (4) multi-turn corrections and entity tracking (e.g., user corrects a callback date) à la v2.
- Thai speakers frequently backchannel with polite particles and "ครับ/ค่ะ" — a VAD-only barge-in policy is likely to over-trigger; LiveKit adaptive interruption or a minimum-words rule should be evaluated specifically on Thai backchannels.

### Gaps
- No full-duplex/turn-taking benchmark covering Thai was found (M3-DuplexBench language list not checked).
- Full-Duplex-Bench v1.5 paper not fetched; its exact metric formulas are from secondary summaries.

## Q5. Thai call-center rubric items (politeness, particles, name repetition, empathy)

### Takeaway
There is little to no peer-reviewed literature on Thai call-center speech norms; rubric items must be built from general Thai pragmatics (polite particles, softening particles, tone of ค่ะ/คะ) plus project acceptance criteria, and validated with the client's own QA scorecards.

### Cited Findings
- ครับ (male) / ค่ะ (female) are basic politeness particles routinely used by service staff; omitting them can sound rude; they are expected with officials, shop staff and older people. — [Verbling](https://www.verbling.com/it/articles/post/thai-polite-and-formal-particles); [ThaiPod101 formal Thai](https://thaipod101.com/lesson/thai-teachers-answer-your-questions-10-how-does-formal-thai-work); [The Thailand Life](https://www.thethailandlife.com/krap-ka) (non-academic learner resources)
- ค่ะ (falling tone) is used for statements; คะ (high/rising tone) for questions — a known TTS/text error point. — [ThaiPod101 honorifics](https://www.thaipod101.com/lesson/thai-teachers-answer-your-questions-18-does-thai-have-honorifics?lp=144)
- Particle "นะ" softens requests and other face-threatening acts (Rutherford 2022, JSEALS). — [DOAJ record](https://doaj.org/article/98cbbf3555f64e0dbce8fe329d8916f4) [academic]
- A Chulalongkorn student project (165 respondents) found frequent misuse of คะ/ค่ะ, especially among under-24s and heavy social-media users — misuse is common enough to be noticed. — [Chula DSpace](https://cuir.car.chula.ac.th/xmlui/handle/123456789/78747?show=full) (non-peer-reviewed)
- ThaiMOS rating dimensions used for Thai TTS: sound quality, rhythm, pronunciation. — [AudioJudge](https://arxiv.org/pdf/2507.12705)

### Inferences
- Proposed rubric (each scored 0–2 by LLM judge and spot-checked by Thai QA staff):
  1. Correct female particle use: ค่ะ on statements, คะ on questions; never ครับ; not appended to every clause (over-use sounds scripted).
  2. Appropriate honorific address (คุณ + first name) used at greeting/verification and sparingly afterwards; flag > 1 name mention per ~3 bot turns as repetitive.
  3. Softening: requests framed with นะคะ / รบกวน / ขออนุญาต; no blunt imperatives.
  4. Empathy/acknowledgement before redirecting when the customer raises a concern (e.g., "เข้าใจค่ะ…"), without stock phrases repeated across turns.
  5. One question per turn; turn ≤ 7 s spoken (≤ 12 s hard cap); no reading of long lists.
  6. No repetition of identical sentences or of information already confirmed; varied acknowledgement tokens.
  7. Register: polite spoken Thai, not written/formal ราชการ register or translated-English syntax; numbers, dates and policy IDs verbalised the Thai way (Buddhist-era year if the client uses it).
  8. Truthful AI disclosure (bot identity "น้องเคพีไอ" as an AI assistant) and recording/consent notice handled per policy.
  9. Graceful handling of refusals, busy customers ("ไม่สะดวก") with an offer to call back rather than pushing.
  10. Correct escalation to a human when requested or when out of scope.
- Validate against the insurer's existing human-agent QA scorecard; the client likely already scores greeting, verification, product disclosure and closing.

### Gaps
- No peer-reviewed study on Thai call-center agent speech norms, Thai customer perception of particle use, or acceptable name-repetition frequency was found; Thai-language databases (ThaiJo) with terms คำลงท้าย, ศูนย์บริการลูกค้า, ความสุภาพ were not searched.
- No Thai regulatory guidance (e.g., OIC rules on telesales of insurance) was researched here; it may impose mandatory script items.
