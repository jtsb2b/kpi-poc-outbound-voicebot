# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **JTS presenters/engineers** run the first KPI demonstration. They drive the operator UI, either screen-shared or on a projector, while KPI staff answer calls on their own phones. They also use the UI daily during development to launch simulated or live test calls and inspect results.
- **KPI contact-center staff** (บริษัท กรุงไทยพานิชประกันภัย จำกัด (มหาชน), Contact Center and FNOL Services) try the UI hands-on after a short handover. They enter their own phone number and name, pick a record, place the call, then read the outcome and download Excel.
- **People answering the call** never see the UI. They hear the bot, so the conversation itself is the product experience being evaluated.

## Product Purpose

This is a proof of concept showing that an outbound Thai voicebot can run two KPI contact-center campaigns:

1. **PA policy confirmation:** identity, availability, review of a mock PA เต็มใจ purchase, free-look notice, questions and closing.
2. **Accident-service satisfaction survey:** Q1–Q4 on a 1–5 scale and Q5 on 0–10, with conditional feedback, N/A handling and verbatim final comments.

Success means KPI judges the call to sound like a coherent, natural conversation with an attentive Thai representative who is honestly an AI. Every call must also end with one unambiguous outcome and a reviewable structured result. Passing the scripted workflow alone is not success.

The operator UI is a small control surface: choose campaign → enter phone and name → choose mock profile or Excel row → Call → watch progress → inspect results → download Excel. It is not an analytics dashboard, CRM or admin tool.

## Positioning

The bot runs on Soniox speech recognition (while JTS's JaiASR is in maintenance), Gemini 3.5 Flash-Lite as the conversation LLM (chosen by the PM for Thai politeness; OpenThai 2.0 on the JTS gateway stays selectable) and Gemini 3.8 Flash-Lite TTS's Achernar voice with audio tags (the PM's choice; JTS's JAI TTS stays selectable), over LiveKit SIP. The LLM leads the conversation from an approved knowledge base against a checklist of what the call must cover. Application code keeps the identity gate, the AI disclosure, recording notice and free-look wording, exact facts and numbers, score validation, callbacks, discrepancies, escalation and outcomes. Interrupted speech is tracked so it is never recorded as delivered.

## Operating Context

- **Demo format:** a JTS presenter drives first, then KPI staff use it themselves. The UI must therefore be self-explanatory to a non-technical Thai contact-center user, and legible when projected or screen-shared.
- **Concurrency:** one concurrent call, launched deliberately by a person. There is no bulk or automatic dialing, even when an Excel file has many rows. Callbacks, transfers, complaints and policy corrections are recorded tasks only.
- **Environments:** localhost first, accepted by the JTS operator, then deployment via GitHub Actions to a server that is still to be decided.
- **Telephony:** dedicated LiveKit SIP trunk `ST_NbZaAsMDs5Br` (kpi-voicebot-outbound), caller extension 2211 shown as 02-100-4148, Thai destinations dialled in national `0…` format.
- **Record sources:** results live in MongoDB. Excel is import/export only.

## Capabilities and Constraints

- **Current state:** live calls over LiveKit SIP work end to end (dialling, conversation, results, transcript, recording to Tencent COS), with text and microphone simulators beside them. Remaining before go-live: KPI approval of wording and the knowledge base, a Bangkok-side LiveKit route for call audio quality, and deployment by DevOps.
- **Persona:** the bot is **น้องเคพีไอ**, a female voice (ดิฉัน/ค่ะ/คะ), introduced as "AI ผู้ช่วย". It never claims to be a human employee.
- **Recording:** call audio is recorded to COS cloud storage (PM approval, 8 Oct 2026), alongside transcripts, structured results and events (configurable retention, default 30 days). The opening gives the recording notice. If the customer objects, the bot ends the call politely and the transcript and recording are discarded.
- **Phone numbers:**
  - Any valid Thai number is accepted, mobile or landline, in `0…`, `66…` or `+66…` form.
  - There is no fixed allowlist of test numbers.
  - Non-Thai numbers are stored but not dialable until an international format is confirmed.
- **Calling hours:** live calls only between 08:00 and 20:00 Asia/Bangkok, configurable.
- **Access:** operator access is a single shared token.
- **Wording governance:** every campaign line is tagged `poc_approved`, `kpi_source` or `pending_kpi_approval`. Pending items must never be presented as verified KPI terms.
- **Open decisions:**
  - final KPI-approved script wording;
  - canonical product data (the PLAN 4 vs Plan 1 conflict);
  - the Q5 follow-up threshold (currently 0–8, configurable);
  - the production identity-verification rule;
  - outcome names for KPI;
  - the deployment target;
  - the STT and LLM API contracts.

## Brand Commitments

- The UI may use KPI's website colours and typography and the **official KPI logo** (PM approval, 8 Oct 2026). Until the logo file is in the repo, the navy text wordmark "KPI" stands in.
- The UI is **Thai-first**. English appears only for technical terms (SIP, Excel, IDs).
- The bot persona น้องเคพีไอ and its "AI ผู้ช่วย" introduction are binding for the POC.

## Evidence on Hand

- KPI-supplied scripts and team plan, in `/Users/apiwitnathong/Documents/KPI_outbound docs/`: the call script RTF, the email-scripts PDF, the team plan and workflows PDF, and the PA เต็มใจ coverage image.
- Mock profiles and simulator scenarios are in `src/kpi_voicebot/campaigns/data/`. All values are fictional and labelled MOCK.
- There are no real customer records, testimonials, performance benchmarks, latency figures or KPI approvals yet. None of these may be fabricated.

## Product Principles

1. **Natural conversation is the acceptance bar.** Short spoken Thai turns, context-aware understanding, graceful interruption and honest limits matter more than script completion.
2. **Code decides, the model phrases.** Gates, validation and outcomes stay deterministic and auditable.
3. **Show the truth of every call.** Partial, failed, canceled and interrupted states are shown honestly, and mock data is always labelled.
4. **Deliberate, single, safe calls.** A person starts each call. There is one attempt per request and no automatic redial.
5. **Simple enough to hand over.** A KPI staff member should be able to run a call and read its result without training.

## Accessibility & Inclusion

The UI must be legible and operable by non-technical Thai users, on a laptop and when projected or screen-shared. It uses Thai-capable typography and needs clear labels, keyboard operability and sufficient contrast. No formal standard has been specified by KPI.
