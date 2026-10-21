# kpi-poc-outbound-voicebot

Outbound Thai voicebot POC for KPI (กรุงไทยพานิชประกันภัย), built on the JTS stack. The bot is **น้องเคพีไอ**, a female AI assistant, and it runs two campaigns:

- **PA policy confirmation** (`pa_confirmation`): checks identity and availability, gives the transcript notice, reviews a mock PA เต็มใจ purchase one short unit at a time, delivers the free-look notice, answers FAQ questions and closes. If the customer disputes a field, the bot records a follow-up task. It never changes source data.
- **Accident-service survey** (`accident_survey`): asks Q1–Q4 (1–5) and Q5 (0–10), one question at a time. Low scores trigger a follow-up question about that score. Q3–Q4 can be N/A. Final comments are kept verbatim, and complaint, claim, safety or urgent cases become escalation tasks.

## Status: phone calls (LiveKit SIP) built, first live test next

| Area | State |
|---|---|
| Campaign engine (deterministic state machines, YAML wording) | done |
| Rule-based Thai interpreter (scores, corrections, N/A, stop, callback, wrong person) | done; will run as the safety layer beside the LLM later |
| MongoDB store, single-active-call lock, idempotency, cancel, lease reconciliation | done |
| FastAPI + Swagger (`/docs`), Excel import/export | done |
| Operator UI (React/Vite) | done |
| Text simulator (UI scenarios, `kpi-sim` CLI) | done |
| LLM: Gemini 3.5 Flash-Lite (`LLM_PROVIDER=gemini`, the default since 19 Oct 2026, chosen by the PM for Thai politeness); OpenThai 2.0 on the JTS gateway stays selectable (`LLM_PROVIDER=jts`) | done: leads the conversation from the knowledge base (agent mode); about 1.2–1.6 s per reply measured from Bangkok; approved wording on any error |
| Thai phone politeness and grouped policy reading (research of 19 Oct 2026, `research_notes/Thai politeness and Gemini for voicebot/`) | done: softened questions, polite silence ladder, varied lines; policy read in four topic groups with one confirmation each; recording consent asked, a "no" deletes the audio and keeps the transcript; OIC calling hours (Mon–Sat 08:30–19:00) and a 6-month do-not-call block |
| Voice: Gemini 3.8 Flash-Lite TTS with audio tags, voice Achernar (PM, 19 Oct 2026), Thai normaliser; JAI TTS selectable | done |
| Speech recognition: Soniox real-time `stt-rt-v5` (`ASR_PROVIDER=soniox`, the default since 15 Oct 2026); JaiASR-Flash stays selectable (`ASR_PROVIDER=jai`) while it is in maintenance | done: turn-taking (`TurnCollector`), Silero VAD, ai-coustics noise reduction on calls, microphone test mode |
| Approved knowledge base for the LLM (`campaigns/knowledge/*.th.md`, built from the approved scripts and FAQ) | done: fixed prompt prefix (cached by the gateway), guarded so its facts can be used but not stretched |
| LLM-led conversation (`agent.py`, `CONVERSATION_MODE=agent`, default with `INTERPRETER=llm`) | done: the model talks freely from the knowledge base against a checklist; code keeps the disclosures word for word, the facts exact, the results and the close; `scripted` keeps the old reworded-script mode |
| Phone calls over LiveKit Cloud SIP (trunk `ST_NbZaAsMDs5Br`, From 2211 → 02-100-4148, ai-coustics QUAIL_VF_S on the caller's audio as in the inbound bot), shared voice loop with barge-in, `kpi-call` test command, live mode in the UI | done: live calls tested 14–16 Oct 2026; audio is laggy because LiveKit Cloud routes Bangkok through India (see `DEPLOYMENT_HANDOFF.md`) |
| Call recording to Tencent COS (`recording.py`: recorded by the worker, both sides mixed as Opus/OGG, uploaded at hang-up; nothing kept if the customer declines; a failure is marked on the call) | done; verified against the real bucket |
| Docker Compose (`docker-compose.yml`: MongoDB, API, worker, web on http://localhost:8080; see `DEPLOYMENT_HANDOFF.md`) and GitHub Actions CI (lint, types, tests, web build, image builds; no secrets, never dials) | done and run locally; deployment waits for localhost acceptance and a Bangkok-side LiveKit route |

Call audio is recorded to Tencent COS once the `COS_*` settings are set (approved by the PM on 8 Oct 2026): from the answer on, both sides mixed by the worker itself (the bot's speech where it was actually heard, the customer's audio as it came down the line), encoded as Opus/OGG and uploaded at hang-up to `<COS_PREFIX>/DD-MM-YYYY/<customer>_<campaign>_<HHMMSS>_<call id>.ogg`. A customer who declines gets no audio kept; the transcript stays. A recording that could not be stored is marked `failed` on the call. (LiveKit egress did this until 20 Oct 2026, when the LiveKit Cloud project ran out of egress minutes.) The recording notice is part of the approved opening. Transcripts, structured results and call events are stored in MongoDB and expire after `RETENTION_DAYS` (default 30).

## Layout

```
src/kpi_voicebot/
  campaigns/data/   campaign wording + approval status, mock profiles, simulator scenarios (YAML)
  engine.py         shared opening/identity/availability/notice/callback/stop/silence/interruption logic
  pa_engine.py      Campaign A body
  survey_engine.py  Campaign B body
  thai_parse.py     rule-based Thai reply parsing
  phone.py          0… / 66… / +66… → E.164; national 0… only at the SIP boundary
  store.py          MongoDB persistence
  service.py        call request validation
  worker.py         claims one call at a time and runs it (simulated or live)
  simulator.py      scripted/typed customer replies (kpi-sim)
  voice_session.py  the spoken conversation loop: front end → Soniox (or JaiASR) → dialogue → Gemini TTS (or JAI TTS), barge-in, hang-up
  playback.py       streams TTS to the speakers or a LiveKit track; read-ahead of the prepared turn
  telephony.py      LiveKit room + SIP dial (once, never redialled), ringing/hang-up, kpi-call CLI
  mic.py            the same loop on this computer's microphone (kpi-sim chat --mic)
  agent.py          LLM-led conversation: one model turn per reply, checklist + rules kept by code
  soniox_asr.py     Soniox real-time recogniser (the default; same interface as the JaiASR client in asr.py)
  recording.py      call recording: both sides mixed in the worker, Opus/OGG, upload and delete in COS (S3 SigV4)
  knowledge.py      loads campaigns/knowledge/: approved knowledge the LLM may use (no customer data)
  excel_io.py       import, export (formula-safe), template
  api.py            FastAPI operator API
apps/web/           React + TypeScript + Vite operator UI (pnpm)
tests/              pytest (scenarios, parsing, API/store/worker/Excel)
```

Every wording key carries a status: `poc_approved`, `kpi_source` or `pending_kpi_approval`. The UI shows how many items are still pending KPI approval, and `GET /api/v1/campaigns` lists them.

## Run locally

Prerequisites: Python 3.14 with `uv`, Node 24 with `pnpm`, and MongoDB.

MongoDB note: this Mac's Docker VM kernel (7.0.x linuxkit) is inside the range where MongoDB fails to start, as recorded in the Monomax project. Use a native `mongod` (Homebrew `mongodb-community`) with a project-local data directory for now. The Docker option will be checked in the Docker step.

```bash
cp .env.example .env        # then set OPERATOR_TOKEN to a long random value
uv sync
pnpm --dir apps/web install
```

Start each process in its own terminal:

```bash
mkdir -p .local/mongo && mongod --dbpath .local/mongo --bind_ip 127.0.0.1 --port 27018
```

```bash
uv run kpi-api
```

```bash
uv run kpi-worker
```

```bash
pnpm --dir apps/web dev
```

Open http://127.0.0.1:5173 and log in with `OPERATOR_TOKEN` from `.env`. Pick a campaign, enter a number and name, choose a mock profile or an Excel row, pick a scenario (or type the customer's replies), then press **โทร**. Swagger is at http://127.0.0.1:8000/docs.

To stop, press Ctrl+C in each terminal. Data stays in `.local/mongo`.

### Simulator CLI (no database needed)

```bash
uv run kpi-sim list
```

```bash
uv run kpi-sim run survey_contextual
```

```bash
uv run kpi-sim chat pa-email
```

In chat mode you type as the customer. Commands: `/silence`, `/hangup`, and `/interrupt <n> <text>` (the bot is cut off after `n` segments).

### The LLM conversation (Gemini 3.5 Flash-Lite)

With `INTERPRETER=llm`, the LLM named by `LLM_PROVIDER` leads the call: Gemini 3.5 Flash-Lite by default
(`gemini.py`, minimal thinking, a paid `GOOGLE_API_KEY`), or OpenThai on the JTS gateway (`LLM_PROVIDER=jts`).
It leads the call
(`agent.py`, `CONVERSATION_MODE=agent`, the default). Like a person on the phone, it decides what to say
each turn: it reacts to what the customer said, answers questions from the approved knowledge base
(`campaigns/knowledge/*.th.md`) and the call's own facts, and moves the call along in its own words. It is
given a checklist, not a script: who we are talking to, the recording notice and consent, the policy in
four topic groups (coverage; premium, payment and start date; beneficiary; delivery and e-mail or address)
or the survey questions, the free-look notice, questions, close. Each group is read in one turn and
confirmed with one question; a customer disputing one item has that item noted for staff and the rest of
the group confirmed. If the customer declines the recording, no audio is kept and the call goes on with its
transcript.

One model call per turn returns what to say and what the customer settled. The code keeps only what is not
the model's to change:

- the AI disclosure, the recording notice and the free-look notice are said word for word (a paraphrase is
  replaced with the approved wording);
- no number, condition or limiting claim that the call's facts or the knowledge base do not back
  (a policy sentence must mostly match approved text);
- a female voice ("ดิฉัน", ค่ะ/คะ; a stray ครับ is corrected), no Markdown or links;
- a group counts as confirmed only after the customer heard its values; a plain "ครับ" after a group
  confirms it; a "no" naming an item records that item as disputed; a survey score must be on its scale;
- Thai phone politeness: a stray ครับ or นะค่ะ is corrected, a question asked again must be softened
  (ขอโทษนะคะ / ไม่ทราบว่า…), the same reply is never said twice running, and silence gets a polite
  three-step ladder (polite check by name, then "the line may be unclear", then a face-saving goodbye);
- the call cannot close as completed with items left.

A reply that breaks a rule is sent back once with the reason; if the retry fails too, the approved line
for the next step is said (or, for a question, an honest "ยังไม่มีข้อมูลที่ยืนยันได้" and a call-back task).
The approved statements themselves are said without a model call when the customer just says "ครับ", and the
reply to a plain "ครับ" is prepared while the bot is still speaking.

Measured on 15 Oct 2026 in role-played calls: a reply takes about 1–2 s; the knowledge-base prompt prefix is
cached by the gateway (≈0.2 s). The gateway returns replies only when complete, so speaking before the
reply is finished is not possible yet. A turn never waits more than `LLM_MAX_QUEUE_SECONDS` (0.3 s) for the
client-side budget (`LLM_TOKENS_PER_MINUTE`, off by default); over budget it uses the approved wording.

`CONVERSATION_MODE=scripted` keeps the earlier design: the engine (`engine.py`) decides each turn from the
approved wording and the LLM only rewords it (`responder.py`). With `INTERPRETER=rules` there is no LLM at
all; the simulator scenarios run this way.

Try it from the terminal:

```bash
uv run kpi-sim run survey_contextual --llm
```

```bash
uv run kpi-sim chat pa-email --llm
```

Opt-in live test (uses quota):

```bash
LIVE_LLM=1 uv run pytest tests/test_llm_live.py
```

### Speech: Soniox in, Gemini TTS out

**Voice (`tts.py`).** Gemini 3.8 Flash-Lite TTS (`gemini-3.8-flash-lite-tts`) with the Achernar voice,
chosen by the PM on 19 Oct 2026. Of six female voices auditioned (Achernar, Vindemiatrix, Sulafat, Leda,
Despina, Callirrhoe), all read the Thai test lines word for word; Achernar is Google's softest,
highest-pitched female voice. First audio 0.8-1.1 s. The conversation model may put audio tags in what it
says (`<short pause>`, `<breath>`, `<chuckle>`, at most one or two a turn, never in an apology); the voice
acts on them, transcripts and every check see the words only. The delivery style (`TTS_STYLE`) goes with
each line as `speech_metadata` (written into the text it would be read aloud). A `-live` `TTS_MODEL` uses
Gemini Live instead, which ignores tags.

**JAI TTS (`jaitts.py`, `TTS_PROVIDER=jai`).** JAI TTS (JTS's VoxCPM model, speaker-adapted female voice), streamed as raw
44.1 kHz PCM. Measured on 12 Oct 2026: first audio ≈0.12 s, generation ≈8× faster than real time,
≈13 spoken characters per second at `JAITTS_CFG=2.0` / `JAITTS_TEMPERATURE=0.7`. Each turn is one request
so its intonation runs on like one breath; only text over 500 characters is split (after ค่ะ/คะ/ครับ), with
the next part requested while the current one streams.

**What the voice is given (`tts_text.speakable()`).** A Thai voice cannot read Latin script, so nothing
Latin reaches it:
- Emails are spelled the way an agent reads one back: "somchai.demo@example.com" → "เอส โอ เอ็ม ซี เอช เอ ไอ
  ดอท ดี อี เอ็ม โอ แอท เอ็กแซมเปิล ดอท คอม". Common domains are said as words (จีเมล, ฮอตเมล…).
- Times are said the way Thai people say them: 00.01 น. → เที่ยงคืนหนึ่งนาที, 08.30 → แปดโมงครึ่ง,
  14.00 → บ่ายสองโมง, 19.15 → หนึ่งทุ่มสิบห้านาที.
- Numbers, money, Buddhist-era dates, phone numbers (digit by digit) and web addresses become Thai words;
  any other English word is said (Excel → เอ็กเซล) or spelled.
- House numbers keep their ทับ (99/9 → เก้าสิบเก้าทับเก้า) and postcodes are read digit by digit.
The voice is chosen explicitly; neither is ever a fallback for the other.

**Recognition.** Soniox real-time (`soniox_asr.py`, model `stt-rt-v5`, Thai with English hints) is the
default since 15 Oct 2026, when JaiASR went into maintenance and fine-tuning. Each call passes its own terms
(customer name, plan, beneficiary, e-mail) so they are recognised correctly; Soniox only uses them as hints.
Soniox ends an utterance with its own endpoint detection (`SONIOX_MAX_ENDPOINT_DELAY_MS`, 800 ms by
default). JaiASR-Flash (`asr.py`, `ASR_PROVIDER=jai`) uses the same interface and stays selectable; there is
never a silent fallback from one to the other.

**Audio front end (`audio.py`).**
- On phone calls, as in the inbound voicebot: ai-coustics `QUAIL_VF_S` cleans the caller's audio
  (`PHONE_NOISE_CANCELLATION=ai_coustics`), nothing else is applied on top, and Silero VAD runs with its
  defaults (activation 0.5, 0.55 s of silence ends speech). The earlier stack (Krisp plus WebRTC suppression
  and gain control) clipped speech.
- In the desk test on computer speakers, LiveKit's WebRTC processing (echo cancellation against what the
  bot is playing, noise suppression, gain control) runs before Silero VAD.

**Turn-taking (`TurnCollector`, `voice_session.py`).**
- A short answer ends at the recogniser's end of utterance. Open answers (feedback, comments, discrepancy
  details, questions) wait 1.2 s more and join the next utterance, so a pause mid-thought does not cut the
  customer off.
- 7 s of silence makes the bot check the customer is still there.
- On a phone call the bot greets as soon as the call is answered; a "ฮัลโหล" said over the greeting does not
  stop it and does not count as the answer.
- Barge-in: while the bot speaks, sustained speech (VAD over 0.7 s) or recognised words that are more than
  "ครับ / อืม" stop the voice, and only the segments actually heard count as delivered. In the desk test it is
  allowed with `--headphones`, or on speakers with `--aec` (recognised words only, plus a guard that drops
  the bot's own words coming back); by default the microphone is muted while the bot speaks.

Talk to the bot from this computer (uses the recogniser set by `ASR_PROVIDER`):

```bash
uv run kpi-sim chat pa-email --llm --mic
```

```bash
uv run kpi-sim chat pa-email --llm --mic --aec
```

Other tools:

```bash
uv run kpi-sim chat pa-email --llm --voice
```

```bash
uv run kpi-tts asr-bench
```

```bash
uv run kpi-tts say "ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาทค่ะ"
```

- `chat --voice`: type the customer's replies, hear the bot.
- `asr-bench`: JAI TTS speaks typical customer replies ("ครับ", "อ่าห้ะ", "ถั่วต้ม", a disputed amount, a
  call-back time…), they stream to the configured recogniser at real-time pace, and it reports what was heard and how soon
  after the speech the turn was committed.

## Checks

```bash
uv run ruff check src tests && uv run mypy && uv run pytest -q
```

```bash
pnpm --dir apps/web typecheck && pnpm --dir apps/web test && pnpm --dir apps/web build
```

**Role-play suite (`kpi-roleplay`).** 49 scenarios, PA and survey, each played against the production LLM
settings by a customer that Gemini plays from a persona (or a fixed script for silence): the happy path,
wrong person, a relative, busy with and without a call-back time, refusal, do-not-call, declining or
questioning the recording (before and after the notice), disputes, doubt, repeat requests, questions in and
out of the knowledge, the free-look deadline, "are you a real person", off-topic chat, garbled speech,
English mixed in, silence, score changes, scores in words, out-of-scale scores, two answers at once, no
surveyor, complaints and abuse. Each call is checked for its outcome and result fields, and for the
general rules: no fallback line, nothing said twice running, the name in the introduction and the
introduction once, no "เสียงไม่ค่อยชัด" to a clear customer, no hanging up on a question, sane turn
length and reply time, only scores the customer gave. Transcripts land in `.local/roleplay/`. It calls
Google, so it is manual and never part of CI. The simulated customer sometimes drifts from its script;
read the transcript before blaming the bot.

```bash
uv run kpi-roleplay --repeat 2
```

## Key rules

- One call at a time, enforced by a unique MongoDB lock. Every request needs an `Idempotency-Key`. A call is originated at most once. Callbacks are recorded tasks only, with no redial.
- There is no allowlist of test numbers. Any valid Thai number is accepted. Non-Thai numbers are stored in E.164 but refused for dialing until an international dial format is confirmed. Internal extensions need `ALLOW_INTERNAL_EXTENSIONS=true`.
- Live calls are blocked outside `CALLING_DAYS` `CALLING_START`–`CALLING_END` (Asia/Bangkok; default Monday–Saturday 08:30–19:00, the OIC guideline).
- No policy-specific detail is spoken before the customer confirms their name. A wrong-person answer ends the call without disclosure.
- Interrupted speech is tracked per segment. A fact counts as delivered only once it has been played in full.
- If the customer objects to the transcript notice, the bot ends politely, and the call's transcript and the customer's words are discarded.

## Docker

```bash
docker compose up -d --build --wait
```

DevOps deploys from `docker-compose.yml`; the full contract is in `DEPLOYMENT_HANDOFF.md`. The UI is on http://localhost:8080 (nginx serves the built app and forwards `/api` to the API). The API
and worker share one image and read secrets from `.env` at run time; nothing secret is built into an
image. Live calls stay off unless `.env` enables them. Deploying is only an audio-quality fix if the
server and LiveKit's SIP edge are near the PBX: the LiveKit Cloud project currently routes Bangkok
through India.
