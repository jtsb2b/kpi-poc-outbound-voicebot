# Deployment handoff

This repository contains CI and a complete Docker runtime for the KPI outbound voicebot. It has no
production deployment workflow; DevOps adds the infrastructure-specific automation. Deployment is the
last step, after testing and KPI approval.

## Services

All services are defined in `docker-compose.yml`.

- `kpi-voicebot-web`: the operator web UI (nginx), container port `80`, host port `${WEB_PORT:-8080}`.
  nginx forwards `/api`, `/health` and `/ready` to the API.
- `kpi-voicebot-api`: REST API (FastAPI), container port `8000`, reachable only inside the compose network.
- `kpi-voicebot-worker`: claims one queued call at a time and runs it (simulation, or a live call over
  LiveKit SIP). Same image as the API. No inbound port.
- `kpi-voicebot-mongo`: MongoDB 7 for calls, transcripts, results and imports.

The worker dials out through LiveKit Cloud SIP (trunk `ST_NbZaAsMDs5Br`, extension `2211`, shown as
02-100-4148). It needs outbound internet access to LiveKit Cloud, Soniox, the JTS LLM gateway
(`api.jasgpu.com`), Google's Gemini API (`generativelanguage.googleapis.com`), JAI TTS and Tencent COS. It needs no inbound port.

## Environment contract

Copy `.env.example` to the ignored `.env` (or point `COMPOSE_ENV_FILE` at another file) and supply:

- `OPERATOR_TOKEN`: the bearer token operators sign in with (at least 12 characters).
- LiveKit: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_SIP_OUTBOUND_TRUNK_ID`,
  `SIP_CALLER_NUMBER`, `PUBLIC_CALLER_ID`.
- Speech recognition: `ASR_PROVIDER=soniox` and `SONIOX_API_KEY`.
- LLM: `INTERPRETER=llm`, `LLM_PROVIDER=gemini` with a **paid** `GOOGLE_API_KEY` (calls carry customer
  data; the free tier may use requests to improve Google's products). `LLM_PROVIDER=jts` uses
  `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` instead.
- Voice: `TTS_PROVIDER=gemini` (`TTS_MODEL=gemini-3.8-flash-lite-tts`, `TTS_VOICE=Achernar`, the same `GOOGLE_API_KEY`), or
  `TTS_PROVIDER=jai` with `JAITTS_BASE_URL`, `JAITTS_API_KEY`.
- Recording: `COS_SECRET_ID`, `COS_SECRET_KEY`, `COS_REGION`, `COS_BUCKET` (recording is off unless all four are set).
- `LIVE_CALLS_ENABLED`: `false` until live calling is approved. Simulation works either way.
- Calling hours: `CALLING_START`, `CALLING_END`, `CALLING_DAYS`, `TIMEZONE` (default Monday–Saturday 08:30–19:00 Asia/Bangkok, the OIC guideline).
- Optional: `WEB_PORT`, `RETENTION_DAYS`, `CORS_ORIGINS`.

Secrets reach the API and worker only through the env file at run time. No `.env*` file is copied into
any image, and the web image holds no secret.

## Build and start

```bash
cp .env.example .env
# Fill .env through the approved deployment secret process.
docker compose config
docker compose build
docker compose up -d --wait
docker compose ps
docker compose logs -f kpi-voicebot-worker
```

Health checks:

- Web: `http://127.0.0.1:${WEB_PORT:-8080}/ready` returns `{"status":"ready","mongo":true}`.
- API and MongoDB have container health checks; `docker compose ps` shows them as `healthy`.
- Worker: the log shows `worker … started`, and a simulated call from the UI reaches `ended`.

The production reverse proxy terminates HTTPS and forwards the approved domain to web port `8080`.

## Stopping, persistent state and rollback

- On `docker compose stop` or `down`, the worker stops claiming new calls and finishes a call in
  progress; compose allows two minutes (`stop_grace_period`). Stop during a no-call window anyway.
- MongoDB data lives in the `kpi-voicebot-mongo` volume and the voice cache in `kpi-voicebot-tts-cache`.
  Preserve both across deploys and rollbacks; never run `docker compose down -v` on a deployed host.
- Call recordings are in the COS bucket under `COS_PREFIX`, not on the host: one folder per day
  (`19-10-2026/`), one file per call named after the customer (`สมชาย_ใจดี_pa_confirmation_141530_<call id>.ogg`).
- A rollback restores the last accepted images without deleting `.env` or the volumes.

## Call quality: where to deploy

The LiveKit Cloud project currently routes Bangkok through India (measured 16 Oct 2026: 76–194 ms round
trip, up to 7.6% of audio concealed). Calls sound laggy for that reason, not because of this code.
Deploying the containers elsewhere does not fix it. One of these does:

- LiveKit routes the project, including its SIP edge, through Singapore, or
- LiveKit server and LiveKit SIP are self-hosted in Bangkok next to the PBX (`58.82.170.50`).

## Acceptance

- The web UI and `/ready` return 200 over HTTPS; operators sign in with the operator token.
- A simulated call for each campaign reaches `ended` with a result and transcript.
- With `LIVE_CALLS_ENABLED=true`, a live call to an internal test number: the phone shows 02-100-4148,
  the bot greets at once, and the result, transcript and recording (in COS) appear afterwards.
- A customer who declines the recording: the audio recording is stopped and deleted, the call goes on, and
  the transcript and result are kept (decided by the PM on 19 Oct 2026).
- Live calls are refused outside Monday–Saturday 08:30–19:00 and to a number that asked not to be called
  in the last 6 months.
- No call is ever redialled automatically; busy, no answer and failures are recorded once.
- Logs contain no credentials.
- Offline tests and builds do not establish conversational quality; verify with real calls.
