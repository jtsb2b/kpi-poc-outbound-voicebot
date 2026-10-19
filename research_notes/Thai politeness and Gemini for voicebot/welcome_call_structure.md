# Welcome call structure: grouping policy items into turns

Research date: 2026-10-19. Scope: how Thai insurers' welcome and confirmation calls present policy details, what voice UX research says about how much to say before asking for confirmation, and a proposed turn plan for the KPI PA confirmation bot (`src/kpi_voicebot/campaigns/knowledge/pa_confirmation.th.md`, step 4).

Problem: today the bot reads one item per turn and waits for "ครับ/ค่ะ" each time, which comes to about 10 confirmation turns. The PM says this sounds unnatural. Human agents summarise a group of related items and then ask once.

---

## 1. Findings

### 1.1 Regulation (OIC)

**OIC notice on telephone sales, B.E. 2552 (life insurance), clause 9.7, "Confirmation Call"** ([PDF](https://oiceservice.oic.or.th/document/Law/file/00159/00159_ed495645b4049b7e42098d711f30c2e6.pdf)). I read the full text. It is the only primary OIC text I could retrieve that spells out what the confirmation call must contain:
- The company must call within 7 days of sending the policy and ask permission to record. Recording runs from consent to the end of the call and is kept for the policy term.
- Required content: 9.7.1 the caller's name; 9.7.2 whether the customer has received the policy; 9.7.3 whether the customer has questions about conditions, coverage or exclusions, explained until they are clear; 9.7.4 whether the customer still wants the insurance, and if so, notice of the free-look right (30 days from receiving the policy, full refund, no deductions, refund within 30 days).
- Clause 9.3 (the sales call itself): ask permission to record, then **ask the customer to confirm that permission a second time**.
- Clause 9.4: the sales call must cover a benefit summary and exclusions, the premium, the insured term, the payment period, the payment method, and a coverage start date chosen by the customer.
- **The regulation does not require reading items one by one.** It specifies content, not turn structure. "Summary of benefits" (สรุปผลประโยชน์) is the regulator's own framing.

**KPI is a non-life insurer.** The rules that actually bind KPI are the OIC notice on issuing and selling non-life policies, B.E. 2563, plus its guidelines (amended up to "ฉบับที่ 4" in 2568) ([OIC e-service law search](https://oiceservice.oic.or.th/lawsearch.php); [board approval news](https://media.thaigov.go.th/uploads/document/142/2020/07/pdf/Doc_20200701101711000000.pdf)). I could not retrieve that text. KPI's own SLA filed with the OIC ([KPI SLA PDF](https://kpi.co.th/wp-content/uploads/2024/12/Service-Level-Agreement-ส่ง-OIC.pdf)) says that under that notice the company must at minimum: tell the customer where their data came from; explain the duty of disclosure; and state the cancellation right and the time until the customer receives the policy or is contacted. **Action: KPI compliance should confirm the exact confirmation-call checklist and the recording-consent wording before go-live.** Specifically, the 2552 rule requires asking consent to record; the bot currently only announces that the call is recorded.

A Tilleke & Gibbins summary of the 2019 OIC rules ([link](https://www.tilleke.com/insights/thailands-oic-issues-new-regulations-providing-insurance-effective-january-1-2019/)) adds four points: telesales scripts must be approved in advance; calls are recorded only with prior consent; the confirmation call must happen within 7 days; and required disclosures include the payment channel, coverage commencement date and insured term.

### 1.2 Real-world welcome/verification call practice

- I found no public Thai insurer welcome-call script. They are internal, OIC-approved documents. Generic guidance across insurers and lenders follows the same arc: greet and verify identity, then confirm **policy and cover, then premium, then beneficiary/nominee**, then explain free-look and claims, then confirm the policy document was received ([edesy welcome-call guide](https://edesy.in/blog/customer-onboarding-welcome-calls-ai-voice-2026)). The guiding rule there is to confirm what the customer *understood*, not just read back what the system holds.
- India's pre-issuance verification call (PIVC, IRDAI) has the same aim: check that what the agent told the customer matches the policy terms, as a mis-selling control ([Perfios](https://perfios.ai/?p=15725), [AuthBridge](https://authbridge.com/?p=55796)).
- In observed Thai call-centre practice (practitioner knowledge, not a citable source), agents bundle items by topic: coverage amounts in one breath, then premium plus payment, then delivery. They close each bundle with an understanding check such as "ตรงตามที่คุณ…ทราบไหมคะ" or "ถูกต้องไหมคะ". The beneficiary and contact details get their own question because errors there cause claim and delivery failures. The PM's instinct matches this.
- A beneficiary check is worth a direct question because circumstances may have changed since the application ([Rework policy-delivery guide](https://resources.rework.com/vi/libraries/financial-services-growth/policy-delivery-service)).

### 1.3 Voice UX guidance on chunk size

| Source | Guidance |
|---|---|
| Google Design, "The Rule of Three also works in conversation design" ([link](https://design.google/library/rule-of-three)) | Speak **no more than three options/items at a time**. Speech is ephemeral and listeners hold it in memory. Jefferson's conversation analysis shows speakers build lists in threes and listeners expect the list to end after the third item, so lists that break this pattern draw interruptions. Split big sets into sequential groups of up to three. (An unpublished student study cited there found two lists of three felt faster than one list of six.) |
| Amazon Alexa Design Guide, "What Alexa says" ([link](https://developer.amazon.com/fr/designing-for-voice/what-alexa-says/)) | **One-breath test** per idea. Start with 2 to 5 items and **group them in sets of 2 to 3**. The first items should take no more than about **20 s** to read. Introduce the list ("what's coming"). Pause about 350 ms between items (400 ms for dense ones). End the prompt right after the question so users don't answer over the prompt. |
| Alexa Haus "Lists" pattern ([link](https://developer.amazon.com/en-US/alexa/alexa-haus/patterns-and-components/patterns-lists)) | Up to about 5 short one-word items. Longer or complex items need fewer per chunk, possibly one at a time. Paginate long lists and say so. |
| Google Assistant conversation design, "Confirmations" ([link](https://developers.google.com/assistant/conversation-design/confirmations?hl=en)) | Implicit confirmation is the common default. Explicit confirmation is rare and reserved for costly or irreversible items, **names and addresses** being the named examples. Expect corrections after both kinds. Support **one-step correction** ("no, it's X"). Let the user change any one parameter by asking only for the new value. **Never restart the flow.** |
| Cowan (2001), "The magical number 4" ([PDF](https://memory.psych.missouri.edu/assets/doc/articles/2001/cowan-bbs-2001.pdf)) | Working-memory capacity is about **4 chunks** (not Miller's 7±2), across auditory and visual material. |
| Commarford, Lewis, Smither & Gentzler (2008), *Human Factors* 50(1):77-89 ([abstract](https://stars.library.ucf.edu/facultybib2000/233)) | In IVR menus, broad (longer) menus beat deep ones (many short steps), especially for low-working-memory users. **Too many tiny turns also costs memory and patience.** This is evidence against one-item-per-turn. |
| Serial-position research on spoken lists (e.g. [Cowan et al. 2004, modality effects](https://memory.psych.missouri.edu/assets/doc/articles/2004/cowan-et-al-jeplmc-2004-modality-effects.pdf)) | Spoken lists get a strong **recency** advantage: the last item is remembered best. Synthetic speech hurts recall of early items more than natural speech does. Implication: put the item most likely to be disputed last, or keep groups short with TTS. |
| Implicit-confirmation error discovery ([ISI study](https://www.isi.edu/results/publications/17917/analysis-of-user-behavior-under-error-conditions-in-spoken-dialogs)) | Users who discover errors through implicit confirmations recover less often and more slowly. **Do not rely on implicit confirmation for items where an error matters.** |
| Cohen, Giangola & Balogh, *Voice User Interface Design* (Nuance, 2004) ([TOC](https://www.oreilly.com/library/view/voice-user-interface/0321185765/ch05.html)) | Classic reference on balancing efficiency and clarity and on error recovery. I did not retrieve the text. |

**Synthesis:** 3 items per group, 4 at most. Each group fits within about 15 to 20 s of TTS, ends in a single question, and is followed by a pause. Numbers are dense in Thai ("หนึ่งแสนบาท", "ห้าร้อยบาทต่อวัน สูงสุดสามสิบวัน"), so treat each amount as one dense item. Ask the question **once, at the end** of the group, never mid-list.

### 1.4 Thai pragmatics that matter here

- In Thai telephone talk, "ครับ/ค่ะ/อืม" is often a **backchannel** (acknowledgement, "I'm listening"), not agreement ([Thai vs American telephone back-channel study](https://www.ideals.illinois.edu/items/81503); [Chula thesis](https://cuir.car.chula.ac.th/dspace/handle/123456789/51227)). Combined with *kreng jai* (reluctance to contradict), a customer may say "ครับ" to a list they did not fully hear. This is exactly the weakness of the current item-by-item design: each "ครับ" is cheap and uninformative.
- Mitigations:
  - Ask a **content-bearing question** at the end of each group ("ตรงตามที่คุณ…ทราบไหมคะ"), so "ใช่ค่ะ/ถูกต้อง/ตรงครับ" carries real meaning.
  - For the beneficiary and email/address, make the question require recognition of the content ("…ใช่ไหมคะ" after the name).
  - Make disagreeing easy and face-saving ("ถ้ามีส่วนไหนไม่ตรง บอกน้องได้เลยนะคะ").
  - Treat hedges ("น่าจะ", "มั้ง", "จำไม่ได้") as unsure, not yes (consistent with the existing re-ask hedge rule).

### 1.5 Call length

- The KPI knowledge base already sets the target at **3 to 5 minutes** (`pa_confirmation.th.md`, "วัตถุประสงค์ของสาย").
- Generic contact-centre benchmarks are about 4 to 8 min for service calls and 5 to 7 min for insurance overall ([Agenttech glossary](https://agenttech.io/glossary/average-handle-time), [Webex AHT guide](https://www.webex.com/us/en/articles/AHT-average-handle-time.html)). These are weak sources, and too short a call can mean disclosures are being rushed.
- Estimate for the grouped design: about 7 bot turns × (8 to 20 s of TTS plus 2 to 4 s of response and latency) gives roughly **2.5 to 3.5 min** for a clean call and 4 to 5 min with one dispute or question. That is within target. The current 10+ single-item turns cost about 1 extra minute of turn-taking overhead alone.

---

## 2. Which items to group vs. confirm one by one

| Item | Treatment | Why |
|---|---|---|
| Plan name, death benefit, medical per accident, daily hospital income | **Group A (coverage)**, one question | Same topic. These are read-only amounts the customer heard at sale. A dispute is rare and is logged, not fixed. |
| Premium (amount + per year/month), payment channel/status, effective date and time | **Group B (money and start)**, one question | All about "what you pay and when cover starts". OIC lists them together (premium, payment method, coverage start). |
| Beneficiary (name + relationship) | **Explicit, alone** | High stakes (claim payout), changes often, and a person's name is the textbook case for explicit confirmation (Google). |
| Delivery channel + period | **Group C**, together with the address/email check | Same topic. |
| Email / postal address | **Explicit** within Group C: read it back and ask "ใช่ไหมคะ" | Explicit-confirmation case (Google: addresses). Wrong contact means a lost policy. Address/email can't be changed on the call, so log a change request. |
| Recording notice | Opening turn, ideally **consent** ("ขออนุญาตบันทึกเสียง…นะคะ") | OIC 2552 cl. 9.3/9.7 requires asking permission. Confirm the non-life wording with KPI compliance. |
| Policy received? / any questions? / still want cover? | Closing turn(s) | OIC 2552 cl. 9.7.2 to 9.7.4. Note: if the policy hasn't been delivered yet (PA telesales flow), skip "received?" and state the delivery period instead (cl. 9.6). |
| Free-look 30-day notice | Closing, as **information** (no yes/no needed beyond "ทราบนะคะ") | Disclosure, not a parameter. |

Order rationale:
- Coverage first, because it is the "what you bought" frame.
- Money second.
- Beneficiary third, as its own beat so it doesn't get lost at the end of a list.
- Delivery and contact last, which leads naturally into "when you receive it, you have 30 days…".
- Within each group, put the **most dispute-prone item last** (recency): the daily-income cap in A, the premium period in B.

---

## 3. Recommended turn plan (example wording, female polite register)

Placeholders are in `{…}`. All amounts and dates go through the existing Thai number and clock readers (no Latin script to JAI TTS). Insert short pauses (around 350 to 400 ms) between items within a group. The LLM leads from the knowledge base. These are **reference phrasings, not locked script** (per the team's conversation-style rule).

**T1: Greeting and identity** (unchanged)
> สวัสดีค่ะ ขอเรียนสายคุณ{ชื่อ นามสกุล} ค่ะ

**T2: Intro, purpose, recording consent, convenience** (one question at the end)
> น้องเคพีไอ ผู้ช่วยเอไอจากกรุงไทยพานิชประกันภัยค่ะ ขอบคุณที่ไว้วางใจทำประกันอุบัติเหตุกับเรานะคะ วันนี้โทรมาทวนรายละเอียดกรมธรรม์สั้นๆ ประมาณสามนาทีค่ะ ระหว่างนี้ขออนุญาตบันทึกเสียงการสนทนาเพื่อคุณภาพการบริการนะคะ สะดวกคุยตอนนี้ไหมคะ

(If KPI compliance requires a separate consent answer, split it: "…ขออนุญาตบันทึกเสียงนะคะ" → answer → "สะดวกคุยไหมคะ". OIC 2552 also asks for a second confirmation of consent during the sales call. Ask KPI whether this applies to the confirmation call.)

**T3: Group A, coverage** (3 to 4 items, about 15 s)
> ขอทวนความคุ้มครองนะคะ คุณ{ชื่อ}ทำแผน{ชื่อแผน} คุ้มครองกรณีเสียชีวิตจากอุบัติเหตุ {จำนวนเงิน} บาท ค่ารักษาพยาบาลครั้งละไม่เกิน {จำนวนเงิน} บาทต่ออุบัติเหตุ และเงินชดเชยรายได้วันละ {จำนวนเงิน} บาท สูงสุด {จำนวนวัน} วันค่ะ ตรงตามที่คุณ{ชื่อ}ทราบไหมคะ

Alternative closers: "ถูกต้องไหมคะ" / "ตรงกับที่ได้คุยไว้ไหมคะ" / "ข้อมูลส่วนนี้ถูกต้องนะคะ" (the last is more implicit; use it only if the customer has been clearly following).

**T4: Group B, premium, payment, start**
> ส่วนเบี้ยประกัน {จำนวนเงิน} บาทต่อ{ปี/เดือน} ชำระผ่าน{ช่องทาง} ซึ่ง{ชำระเรียบร้อยแล้ว/อยู่ระหว่างตัดบัญชี}ค่ะ และความคุ้มครองเริ่มวันที่ {วันที่} เวลา {เวลา}ค่ะ ถูกต้องไหมคะ

(4 facts, but premium + payment status read as one breath. If the TTS runs past about 20 s, move the start date into T3's tail or into its own short implicit line.)

**T5: Beneficiary, explicit**
> ผู้รับผลประโยชน์ในกรมธรรม์คือ คุณ{ชื่อผู้รับประโยชน์} ซึ่งเป็น{ความสัมพันธ์}ของคุณ{ชื่อ} ใช่ไหมคะ

**T6: Group C, delivery and contact, explicit on the address**
> กรมธรรม์จะจัดส่งทาง{อีเมล/ไปรษณีย์} ภายใน {ระยะเวลา} วันทำการค่ะ
> (email) ส่งไปที่อีเมลที่ให้ไว้ตอนสมัคร ขึ้นต้นด้วย {ตัวอักษรแรกๆ อ่านแบบไทย} ลงท้ายด้วย {โดเมน อ่านแบบไทย เช่น จีเมลดอทคอม} ใช่ไหมคะ
> (post) ส่งไปที่ {บ้านเลขที่ … อำเภอ/เขต … จังหวัด …} ใช่ไหมคะ

Email note: reading a full email address aloud via JAI TTS without Latin script is error-prone. Read the first 3 to 4 characters plus the domain (in Thai transliteration) and ask for recognition. If the customer is unsure, log it for a human callback rather than spelling letter by letter.

**T7: Free-look, questions, close** (OIC 9.7.3/9.7.4)
> เมื่อได้รับกรมธรรม์แล้ว หากตรวจสอบแล้วไม่ตรงความต้องการ สามารถแจ้งยกเลิกได้ภายในสามสิบวันนับจากวันที่ได้รับ และได้รับเงินคืนเต็มจำนวนนะคะ มีข้อสงสัยเรื่องความคุ้มครองหรือเงื่อนไขเพิ่มเติมไหมคะ
> → (none) ขอบคุณมากค่ะ หากต้องการติดต่อ โทรศูนย์บริการ ศูนย์สอง หกสองสี่ หนึ่งหนึ่งหนึ่งหนึ่ง ได้ตลอดนะคะ ขอให้มีวันที่ดีค่ะ

Result: about **5 confirmation questions** (A, B, beneficiary, contact, questions) instead of about 10, which is within the "3 per chunk, one question per turn" guidance.

---

## 4. Dispute and repair handling within a group

Principles (Google confirmations guidance, plus KPI's "never assert the system is right" rule):

1. **Barge-in mid-group:** stop TTS immediately and address what the customer said. Afterwards, resume from the **interrupted item**, not from the start of the group.

2. **"ไม่ใช่/ไม่ตรง" without naming the item:** offer the group's items as a short choice (at most three), ordered with the most likely item last:
   > ไม่ตรงส่วนไหนคะ เป็นค่ารักษาพยาบาล เงินชดเชยรายวัน หรือจำนวนเงินกรณีเสียชีวิตคะ

3. **Customer names the item, and maybe the value they believe:**
   - Acknowledge without arguing.
   - Restate the system value **once** so the customer can tell whether they misheard.
   - Log the dispute (item, system value, customer value).
   - **Implicitly re-confirm the rest of the group.**
   - Move on.
   > รับทราบค่ะ ในระบบระบุเงินชดเชยวันละ {จำนวนเงิน} บาท สูงสุด {จำนวนวัน} วัน แต่คุณ{ชื่อ}เข้าใจว่า {ค่าที่ลูกค้าบอก} น้องจดไว้ให้เจ้าหน้าที่ตรวจสอบและติดต่อกลับนะคะ ส่วนความคุ้มครองอื่นที่ทวนไปถูกต้องนะคะ
   - If the customer then says "อ๋อ ถูกแล้ว ฟังผิด", clear the dispute and continue.
   - Never re-read the whole group and ask again (that is the "restart the flow" anti-pattern).

4. **Dispute on more than one item, or "ไม่ตรงเลย":** don't drill item by item. Log the whole group as disputed, reassure, and continue (or, if the customer disputes the sale itself, go to the "still want cover?" branch and the free-look information).
   > ไม่เป็นไรค่ะ น้องจะแจ้งให้เจ้าหน้าที่ตรวจสอบรายละเอียดทั้งหมดและติดต่อกลับนะคะ

5. **"ฟังไม่ทัน/อะไรนะ/ขอฟังอีกที":** re-read **only that group**, slower, with longer pauses. If it is asked a second time, split the group into two halves.

6. **Unsure/hedge ("น่าจะ", "จำไม่ได้"):** re-read the item once. If still unsure, log it as "customer unsure" (not as confirmed or disputed) and move on. This is already in the knowledge base.

7. **Change requests (beneficiary, address, email):** can't be done on the call. Capture the requested new value if offered, log it for a callback, and continue. Don't push back.

8. **Minimal "ครับ/ค่ะ" after a group question:** accept as yes for Groups A and B, because the question asked about correctness. For the beneficiary and contact details, accept "ใช่/ถูก/ครับ" given right after "…ใช่ไหมคะ". If there was a long silence or overlapping speech, re-ask briefly: "ผู้รับผลประโยชน์ คุณ{ชื่อ} ถูกต้องนะคะ".

Logging model implication (for later design): record outcomes per item even when items are asked per group. Each item is confirmed, disputed (with the customer value), unsure, or change-requested. A group "yes" marks all of that group's items as confirmed.

---

## 5. Open questions for KPI / PM

1. What is the exact confirmation-call checklist under the non-life notice B.E. 2563 and its 2568 guidelines? Does recording need explicit consent (and double consent) on the confirmation call, or is notice enough?
2. Has the policy usually been delivered at the time of the call? If yes, add "ได้รับกรมธรรม์แล้วหรือยังคะ" (OIC 2552 cl. 9.7.2 pattern). If no, state the delivery period instead.
3. Is the exclusions summary required on this call? (OIC 2552 cl. 9.4.2 requires it at sale, and cl. 9.7.3 only asks whether the customer has questions.)
4. How much of the email address may be read aloud (privacy, and TTS without Latin script)?
5. Does an OIC-approved script exist that constrains wording? Tilleke notes that scripts must be pre-approved, which may conflict with LLM-led phrasing. If so, approve the group templates above as the script and allow the LLM to paraphrase only around them.

---

## Sources

- OIC notice, telephone sales, B.E. 2552 (full text read): https://oiceservice.oic.or.th/document/Law/file/00159/00159_ed495645b4049b7e42098d711f30c2e6.pdf
- KPI Service Level Agreement filed with the OIC: https://kpi.co.th/wp-content/uploads/2024/12/Service-Level-Agreement-ส่ง-OIC.pdf
- OIC law search (non-life sales notice 2563 and guidelines): https://oiceservice.oic.or.th/lawsearch.php
- Thai government news, OIC board approves 2563 notice: https://media.thaigov.go.th/uploads/document/142/2020/07/pdf/Doc_20200701101711000000.pdf
- Tilleke & Gibbins, OIC regulations effective 1 Jan 2019: https://www.tilleke.com/insights/thailands-oic-issues-new-regulations-providing-insurance-effective-january-1-2019/
- Mitihoon news on OIC telephone-sales rules: https://www.mitihoon.com/2020/04/09/170951/
- Google Design, Rule of Three in conversation design: https://design.google/library/rule-of-three
- Google Assistant conversation design, Confirmations: https://developers.google.com/assistant/conversation-design/confirmations?hl=en
- Amazon Alexa Design Guide, What Alexa says: https://developer.amazon.com/fr/designing-for-voice/what-alexa-says/
- Alexa Haus, Lists pattern: https://developer.amazon.com/en-US/alexa/alexa-haus/patterns-and-components/patterns-lists
- Cowan (2001), The magical number 4: https://memory.psych.missouri.edu/assets/doc/articles/2001/cowan-bbs-2001.pdf
- Commarford et al. (2008), broad vs deep auditory menus: https://stars.library.ucf.edu/facultybib2000/233
- Cowan et al. (2004), modality effects: https://memory.psych.missouri.edu/assets/doc/articles/2004/cowan-et-al-jeplmc-2004-modality-effects.pdf
- User behaviour under error conditions (implicit confirmation recovery): https://www.isi.edu/results/publications/17917/analysis-of-user-behavior-under-error-conditions-in-spoken-dialogs
- Cohen, Giangola & Balogh, Voice User Interface Design: https://www.oreilly.com/library/view/voice-user-interface/0321185765/ch05.html
- Back-channel behaviour in Thai and American telephone conversations: https://www.ideals.illinois.edu/items/81503
- Chula thesis on Thai backchannels: https://cuir.car.chula.ac.th/dspace/handle/123456789/51227
- Welcome call guide (policy, cover, premium, nominee, free-look): https://edesy.in/blog/customer-onboarding-welcome-calls-ai-voice-2026
- Policy delivery and beneficiary check: https://resources.rework.com/vi/libraries/financial-services-growth/policy-delivery-service
- PIVC background: https://perfios.ai/?p=15725 , https://authbridge.com/?p=55796
- AHT benchmarks (weak): https://agenttech.io/glossary/average-handle-time , https://www.webex.com/us/en/articles/AHT-average-handle-time.html
