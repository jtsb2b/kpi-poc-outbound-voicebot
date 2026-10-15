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
| LLM reply understanding and wording (self-hosted OpenThai 2.0 27B on the JTS gateway since 15 Oct 2026, previously Qwen 3.8 Flash; `INTERPRETER=llm`) | done: strict JSON-schema reading in context, rule safety layer, rule fallback on any error/429 |
| Voice: JAI TTS (JTS, ≈0.12 s to first audio, clause-streamed PCM), Thai normaliser; Gemini Live only as an explicit option | done |
| Speech recognition: Soniox real-time (`ASR_PROVIDER=soniox`, default since 15 Oct 2026 while JaiASR is in maintenance) or JaiASR-Flash (`ASR_PROVIDER=jai`); turn-taking (`TurnCollector`), microphone test mode | done; front end with WebRTC echo cancellation, noise suppression, gain control and Silero VAD |
| Approved knowledge base for the LLM (`campaigns/knowledge/*.th.md`, built from the approved scripts and FAQ) | done: fixed prompt prefix (cached by the gateway), guarded so its facts can be used but not stretched |
| LLM-led conversation (`agent.py`, `CONVERSATION_MODE=agent`, default with `INTERPRETER=llm`) | done: the model talks freely from the knowledge base against a checklist; code keeps the disclosures word for word, the facts exact, the results and the close; `scripted` keeps the old reworded-script mode |
| Phone calls over LiveKit Cloud SIP (trunk `ST_NbZaAsMDs5Br`, From 2211 → 02-100-4148, ai-coustics QUAIL_VF_S on the caller's audio as in the inbound bot), shared voice loop with barge-in, `kpi-call` test command, live mode in the UI | built; LiveKit connection verified without dialling; **first live test call pending** |
| Call recording to Tencent COS (`recording.py`: LiveKit egress, room audio as Opus, deleted if the customer objects) | built and tested without COS (LiveKit accepts the egress); **needs the COS settings in `.env`** |
| Docker Compose (`docker-compose.yml`: MongoDB, API, worker, web on http://localhost:8080; see `DEPLOYMENT_HANDOFF.md`) and GitHub Actions CI (lint, types, tests, web build, image builds; no secrets, never dials) | done and run locally; deployment waits for localhost acceptance and a Bangkok-side LiveKit route |

Call audio is recorded to Tencent COS once the `COS_*` settings are set (approved by the PM on 8 Oct 2026): from the answer on, both sides mixed, as `<COS_PREFIX>/<call id>.ogg`. If the customer objects to recording, the file is deleted along with the transcript. The recording notice is part of the approved opening. Transcripts, structured results and call events are stored in MongoDB and expire after `RETENTION_DAYS` (default 30).

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
  voice_session.py  the spoken conversation loop: front end → JaiASR → dialogue → JAI TTS, barge-in, hang-up
  playback.py       streams TTS to the speakers or a LiveKit track; read-ahead of the prepared turn
  telephony.py      LiveKit room + SIP dial (once, never redialled), ringing/hang-up, kpi-call CLI
  mic.py            the same loop on this computer's microphone (kpi-sim chat --mic)
  agent.py          LLM-led conversation: one model turn per reply, checklist + rules kept by code
  soniox_asr.py     Soniox real-time recogniser (same interface as the JaiASR client in asr.py)
  recording.py      call recording: LiveKit egress to Tencent COS; deletion on objection (S3 SigV4)
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

### LLM understanding (OpenThai 2.0)

With `INTERPRETER=llm` and the `LLM_*` values in `.env`, the worker asks the LLM to read each customer reply in
context (the question just asked and the last turns) and return strict JSON. The engine still decides
everything:

- Call-ending signals (do-not-call, objection, wrong person, refusal) and score numbers come from the rule
  parser only.
- Model intents count only when they fit the pending question.
- In free-text answers the model contributes escalation tags only.
- Any timeout, HTTP error or 429 falls back to the rules for that turn and is logged as an `llm_fallback_rules`
  call event.

Conversation repair, which works with or without the LLM, follows what a human operator would do:

- Hedged answers ("มั้งครับ") get one explicit re-check with just the key values. If the customer is still
  unsure, the item is recorded as unclear for staff and the bot moves on.
- "มีครับ" or "อยากสอบถาม" invites the question instead of answering it.
- "ขออีกที" repeats only the item's key values.
- Nonsense or off-topic replies are never taken as a yes; the model can abstain with `unclear`.
- On complaints and low scores the bot briefly reflects the customer's own words back. This is a guarded
  phrase from the LLM: it must be built from the customer's words, contain no numbers, and make no promises.
- **The bot words its own turns** (`responder.py`). The engine decides what happens next and writes a draft
  from approved wording. The LLM then says it the way an experienced agent would: it reacts to what the customer
  just said, answers from the call's fact sheet (policy values plus FAQ) where it can, and words each turn
  freshly. A guard checks every reply, and the approved draft is spoken instead if any check fails:
  - every number, email, web address and policy value stays exactly as in the draft;
  - no number appears that isn't in the draft, the fact sheet or the customer's own words;
  - the recording notice, AI disclosure and free-look stay word for word;
  - questions stay questions, the voice stays female ("ดิฉัน", never "ครับ/ผม/น้อง"), nothing is promised,
    and no limiting claims ("เท่านั้น", "เพียง"…) that aren't in the approved text;
  - no Thai typos (dropped vowel or tone marks), no repeated lines, not much longer than the draft.
  When a disputed fact comes up, the bot takes note and never argues or explains it away.
- **The likely next turn is prepared in advance.** While the bot speaks, the turn that follows a plain "ครับ" is
  worded (and, in voice mode, read aloud into a buffer), so most turns answer with no model wait. Other replies
  take about 1–1.5 s (understanding plus wording).
- Policy facts are read like an operator reads them: one fact per turn as a statement ("…บาทนะคะ"), which the
  customer acknowledges with "ครับ / อืม / อ่าฮะ". Only details the customer must check themselves are asked as
  questions: the beneficiary ("ใช่ไหมคะ") and the e-mail or address ("ถูกต้องไหมคะ"). After a bare "ครับ" the next
  fact follows without a "ค่ะ / รับทราบค่ะ" in front.
- Clear short replies ("ครับ", "ใช่ครับ", "ไม่มีครับ") skip the model, which removes 0.5–3 s of silence on most turns.
- Off-topic questions ("1+1 เท่ากับเท่าไหร่") get a polite "ตอบได้เฉพาะเรื่องกรมธรรม์" and no call-back task. A question
  asked mid-explanation ("รายละเอียดอะไรครับ") is answered by what the bot says next, not parked for a call-back.
- Particles are tidied: คะ on questions, and no ค่ะ on a fact that runs into its check question.
- Turns are never chopped into parts: the customer can cut in at any time (barge-in), and only the unheard rest is resumed.

Measured on 8 Oct 2026: understanding takes about 0.4–0.9 s and 1.3k tokens; wording a turn takes about 0.5–1 s and 1.9k tokens. With preparation that is roughly 4–5k tokens per customer turn, or about 25k tokens/min at real call pace.

The gateway rate-limits at about 60k tokens/min, so keep `LLM_TOKENS_PER_MINUTE` under that.

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

### Speech: JaiASR in, JAI TTS out

**Voice (`jaitts.py`).** JAI TTS (JTS's VoxCPM model, speaker-adapted female voice), streamed as raw
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
  any other English word is said (Excel → เอ็กเซล) or spelled. Gemini Live remains available only with `TTS_PROVIDER=gemini`;
it is never a fallback.

**Recognition (`asr.py`).** JaiASR-Flash-v1.0 over WebSocket: `start` (language Thai, 0.5 s chunks, and a
per-call context of the customer's name, plan, beneficiary and contact details), 16 kHz PCM in 0.1 s
frames, then `partial` / `commit` / `final`. The file endpoint (`transcribe_file`) is for tests.

**Audio front end (`audio.py`).** Every 10 ms of incoming audio goes through LiveKit's WebRTC audio
processing (echo cancellation against what the bot is playing, noise suppression, high-pass filter,
automatic gain control) and then Silero VAD. JaiASR receives the cleaned audio. Measured on 12 Oct 2026 with
JAI TTS speech under loud hiss at real-time pace: speech start detected 0.22 s after it began, end 0.38 s
after it stopped, noise floor −10.8 dB with the speech level kept. For phone calls the same front end sits
behind LiveKit, where LiveKit Cloud's telephony noise cancellation can go in front of it.

**Turn-taking (`TurnCollector`, `mic.py`).**
- A short answer ends at JaiASR's commit (0.5 s of silence). Open answers (feedback, comments,
  discrepancy details, questions) wait 1.2 s more and join the next commit, so a pause mid-thought does not
  cut the customer off.
- 7 s of silence makes the bot check the customer is still there.
- Barge-in: while the bot speaks, sustained speech (VAD over 0.7 s) or recognised words that are more than
  "ครับ / อืม" stop the voice, and only the segments actually heard count as delivered. Allowed with
  `--headphones`, or on speakers with `--aec` (echo cancellation plus a guard that drops anything that is
  just the bot's own words coming back). By default on speakers the microphone is muted while the bot speaks.

Talk to the bot from this computer (needs the JaiASR session to be up):

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
  call-back time…), they stream to JaiASR at real-time pace, and it reports what was heard and how soon
  after the speech the turn was committed.

## Checks

```bash
uv run ruff check src tests && uv run mypy && uv run pytest -q
```

```bash
pnpm --dir apps/web typecheck && pnpm --dir apps/web test && pnpm --dir apps/web build
```

## Key rules

- One call at a time, enforced by a unique MongoDB lock. Every request needs an `Idempotency-Key`. A call is originated at most once. Callbacks are recorded tasks only, with no redial.
- There is no allowlist of test numbers. Any valid Thai number is accepted. Non-Thai numbers are stored in E.164 but refused for dialing until an international dial format is confirmed. Internal extensions need `ALLOW_INTERNAL_EXTENSIONS=true`.
- Live calls will be blocked outside `CALLING_START_HOUR`–`CALLING_END_HOUR` (Asia/Bangkok).
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
