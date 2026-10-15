# Natural spoken Thai for a female contact-center voicebot, and rendering it with Gemini TTS

Research date: 2026-10-08. Scope: (a) Thai spoken and phone conventions for a female agent ("น้องเคพีไอ", AI assistant for Krungthai Panich Insurance), (b) Thai text normalization for TTS, (c) Gemini 3.x Flash TTS controls. Note: about 15 tool calls were used. Linguistics sources were mostly available only as abstracts. Items marked "unsourced / native-speaker knowledge" must be checked by a Thai reviewer before use.

## Q1. Politeness particles, register, pronouns, acknowledgements, softeners, and what sounds robotic

### Takeaway
Female speakers use ค่ะ/คะ/นะคะ as speech-level markers. The Royal Institute (ราชบัณฑิตยสภา) says speech without a final particle can sound ห้วน (curt) and กระด้าง (harsh). Learner guides also warn that putting a particle on every clause sounds stiff. I found no published Thai call-center corpus that measures particle frequency, ดิฉัน vs pronoun-drop, or "คุณลูกค้า" usage. Those recommendations below come from native-speaker practice and are not from a cited source.

### Cited Findings
- McCready (PACLIC 28, 2014) treats Thai as marking speech level directly through sentence-final pragmatic particles. He describes three levels: casual, formal, and a mid level that native speakers do not perceive uniformly. Women use khá and men use khráp. The particles have phonological variants, for example the tone of kha changes with clause type (statement ค่ะ vs question คะ). — [McCready, PACLIC 28](https://waseda.repo.nii.ac.jp/record/29529/files/PACLIC_28_Mccready.pdf)
- The Royal Institute says the final tone or particle (หางเสียง) also reflects the speaker's character, mood and feeling. Without a final particle, speech can sound curt and harsh ("ห้วนและกระด้าง"). Its usage notice lists คะ, ค่ะ, นะคะ for women and ครับ, นะครับ for men. — [ORST page (via search summary)](https://www.orst.go.th/FILEROOM/CABROYINWEB/DRAWER004/GENERAL/DATA0000/00000640.FLP/html/244/). I saw this only through a search summary, not the full page.
- Common usage, summarized by the search tool and not quoted from ORST: ค่ะ for statements, answers and confirmations ("ขอบคุณค่ะ", "ได้ค่ะ"); คะ for questions ("ทานข้าวหรือยังคะ"); นะคะ for requests, invitations and softening ("รอสักครู่นะคะ"). "ค๊ะ" is a misspelling. — [search summary incl. ORST, thethaiger](https://thethaiger.com/th/news/1476131/). Medium confidence.
- People write ค่ะ/คะ inconsistently. A TCI journal study examined how the written choice between [kháʔ] and [khàʔ] relates to writers' knowledge of tone marking. This matters because LLM output may contain ค่ะ where คะ is meant, and the TTS will then use the wrong tone. — [TCI: Variation of [kháʔ] and [khàʔ] in Written Thai](https://so04.tci-thaijo.org/index.php/abc/article/view/237206)
- Prasithrathsint (2019) studied the syntactic distribution and communicative function of the /kh/ polite particles. I saw only the citation, not the findings. — [Language and Linguistics, TCI](https://so04.tci-thaijo.org/index.php/joling/article/view/180922)
- Learner guides say the particles are expected in formal and polite speech and leaving them out sounds rude. They are often dropped among friends, and overusing them can sound stiff. — [ThaiPod101 formal Thai](https://www.thaipod101.com/lesson/thai-teachers-answer-your-questions-10-how-does-formal-thai-work?lp=144); [skills.sh Thai notes](https://www.skills.sh/clawic/skills/thai). These are low-authority sources.
- General call-center guidance, from English-language sources: be natural and conversational rather than exchanging information like a robot, but don't be overly familiar. When the agent doesn't know an answer, say they will find out rather than "I don't know." — [Call Centre Helper: courtesy phrases](https://www.callcentrehelper.com/the-best-courtesy-words-and-phrases-to-use-in-customer-service-114618.htm); [Call Centre Helper: 11 things never to say](https://www.callcentrehelper.com/11-things-a-call-centre-agent-should-never-say-but-many-do-68516.htm)
- A Thai service-mindset article lists "8 dangerous phrases" for service staff. I did not fetch it. — [JobsDB](https://th.jobsdb.com/th/career-advice/article/สร้างจิตสำนึกงานบริการ-4)

### Inferences (unsourced / native-speaker knowledge; verify with KPI QA scripts)
- Register: Thai insurance and bank call centers use polite conversational Thai (ภาษาสุภาพ / กึ่งทางการ), not academic or written register (ภาษาวิชาการ/ภาษาเขียน). LLM output tends to drift into written register, for example "ทั้งนี้", "อนึ่ง", "ดังกล่าว", "ดำเนินการ", "โปรดทราบว่า", which sounds read-aloud and robotic. Prefer spoken forms: "ตรงนี้", "แบบนี้นะคะ", "เดี๋ยว...ให้นะคะ", "ได้เลยค่ะ".
- Particle density: put one particle at the end of each turn-final clause or utterance, not on every comma-clause. In a 3-clause turn, ending only the last clause with ค่ะ or นะคะ, plus possibly one in the middle, sounds natural. Repeating "ค่ะ" after every phrase is the most common "robotic Thai" complaint.
- คะ vs ค่ะ: questions end in คะ ("สะดวกคุยไหมคะ"). Statements, answers and acknowledgements end in ค่ะ. นะคะ softens requests, reminders and confirmations ("รบกวนยืนยันอีกครั้งนะคะ"). Do not use "นะค่ะ"; that is a misspelling. Add a post-processing check: if a sentence has a question word (ไหม/หรือเปล่า/อะไร/เมื่อไร/ไหน/กี่/ยังไง) and ends in ค่ะ, rewrite it to คะ.
- Pronouns: agents use ดิฉัน in formal openings and disclosures ("ดิฉัน น้องเคพีไอ ผู้ช่วย AI จาก..."). After that, natural agents usually drop the first-person pronoun. For a persona named น้องเคพีไอ, self-reference by name ("น้องเคพีไอขออนุญาต...") is common in Thai brand bots but can sound childish if overused. Use it once in the intro, then drop pronouns. Avoid ฉัน, which is too intimate or literary for service talk, and หนู, which is too junior or cute.
- Addressing the customer: "คุณ + ชื่อ" (e.g., "คุณสมชาย") is warmer and more natural than repeating "คุณลูกค้า". Use "คุณลูกค้า" mainly when the name isn't confirmed, and limit it to about once per few turns. Dropping the second-person reference entirely is normal in Thai.
- Acknowledgements by function: plain receipt is "ค่ะ" or "ค่ะ ๆ" (short, falling); agreement or compliance is "ได้ค่ะ" or "ได้เลยค่ะ"; understanding is "เข้าใจค่ะ" or "เข้าใจแล้วค่ะ"; a change-of-state realization is "อ๋อ ค่ะ"; empathy is "เข้าใจเลยค่ะ" or "ขอโทษด้วยนะคะที่..."; formal receipt of an instruction is "รับทราบค่ะ". "รับทราบค่ะ" is bureaucratic and stiff if used for every acknowledgement. Rotate a few of these and don't repeat the same token every turn.
- Softeners and pre-requests: "ขออนุญาต..." (before verifying identity or asking for data), "รบกวน...นะคะ", "สักครู่นะคะ", "ไม่ทราบว่า...คะ" (polite question frame), "ถ้าสะดวก...". "ขออนุญาต" more than once or twice per call sounds scripted.
- What sounds robotic: written register; a particle on every clause; the identical acknowledgement each turn; full formal names repeated ("กรมธรรม์ประกันภัยอุบัติเหตุส่วนบุคคล พีเอ เต็มใจ" every time instead of "แผนพีเอ เต็มใจ"); reading full Buddhist-era dates and numbers with no grouping; no discourse markers (เอ่อ is fine sparingly; "คือ", "ก็คือ", "แล้วก็", "นะคะ"); long sentences with no internal pause.

### Gaps
- I found no Thai call-center script corpus or study that quantifies particle frequency, ดิฉัน vs pronoun-drop, or "คุณลูกค้า" frequency. KPI's own QA scripts and recorded calls are the best source.
- I did not obtain the full ORST notice text on คะ/ค่ะ/นะคะ. Cooke (1968) and Iwasaki & Horie on Thai pronouns and particles were not retrieved.

## Q2. Thai backchannel and feedback tokens on the phone (conversation analysis)

### Takeaway
There is one directly relevant telephone study (Wannaruk 1997). Thai backchannels are mostly short tokens signaling understanding. Brief restatements (repeating the other's words) are a distinctively Thai way to show agreement. A voicebot should emit very short ค่ะ-type tokens and occasional echo-repeats, not full sentences.

### Cited Findings
- Wannaruk (1997, PhD, UIUC), "Back-Channel Behavior in Thai and American Casual Telephone Conversations": in both languages, short utterances mostly signaled understanding, short questions requested clarification, and laughter showed emotional response. Brief restatements signaled agreement in Thai, while sentence completions served understanding in American English. — [IDEALS record](https://www.ideals.illinois.edu/items/81503); a short version is in [SUT repository](https://sutir.sut.ac.th/jspui/handle/123456789/421)
- Hasanam (2015, Chulalongkorn MA) studied backchannels among equal-status participants in nine task-based dyadic conversations, compared with daily conversation. — [CUIR](https://cuir.car.chula.ac.th/dspace/handle/123456789/51227?mode=full)
- A CA study on the Thai "Mister O" corpus found that teachers and students use similar backchannel forms and functions at different frequencies. — [TCI ABC journal](https://so04.tci-thaijo.org/index.php/abc/article/view/223631)
- A study of Korean learners of Thai lists backchannel functions: agreement, gratitude, emphasis, insistence, and queries, in lexical and non-lexical forms. — [Parichart Journal](https://so05.tci-thaijo.org/index.php/parichartjournal/article/view/270841)

### Inferences
- Bot backchannel inventory (native-speaker knowledge, not sourced): "ค่ะ", "ค่ะ ๆ", "อือ" (too casual for an agent, avoid), "อ๋อ ค่ะ", "ใช่ค่ะ", "จริงด้วยค่ะ", and an echo plus ค่ะ (customer: "ตุลาคมนะ" / bot: "ตุลาคม ค่ะ"). Echo-repeats fit Wannaruk's restatement-as-agreement finding and also work as implicit confirmation of slot values.
- In TTS, render backchannels as separate, very short utterances. Pre-synthesized and cached clips avoid TTS latency.

### Gaps
- I only saw abstracts. Token frequencies and placement relative to TRPs in Thai phone calls were not available.

## Q3. Reading numbers, money, dates, times, phone numbers, emails/URLs, and normalization tooling

### Takeaway
Normalize everything to Thai words before TTS. Don't let the TTS guess. PyThaiNLP has building blocks: num_to_thaiword, bahttext, thai_strftime, time_to_thaiword, maiyamok, and abbreviation_to_full_text. Phone numbers are read digit by digit with grouping pauses. Times written "น." are read as นาฬิกา. Dates use พ.ศ. years read as full numbers.

### Cited Findings
- PyThaiNLP util functions:
  - `num_to_thaiword(11)` → "สิบเอ็ด"
  - `bahttext(21)` → "ยี่สิบเอ็ดบาทถ้วน" (Excel BAHTTEXT style, 2 decimals)
  - `thai_strftime(dt, "%A %d %B %Y")` → "วันอาทิตย์ 09 มิถุนายน 2562" (Buddhist Era year, but digits stay digits)
  - `time_to_thaiword("8:17")` → "แปดนาฬิกาสิบเจ็ดนาที"; supports 24h, 6h (traditional โมง/ทุ่ม) and modified 6h formats
  - `convert_years` (BE↔AD; reliable only after 1941)
  - `maiyamok("เด็กๆชอบไปโรงเรียน")` → ['เด็ก','เด็ก','ชอบ','ไป','โรงเรียน']
  - `normalize()` removes zero-width chars and duplicate spaces and fixes repeated vowels
  - `abbreviation_to_full_text("รร.ของเราน่าอยู่")` → top candidate "โรงเรียนของเราน่าอยู่" (KhamYo)
  - `arabic_digit_to_thai_digit` / `thai_digit_to_arabic_digit`

  — [PyThaiNLP util docs](https://pythainlp.org/docs/5.0/api/util.html)
- Thai number-reading rules from teaching material: in numbers of 2 or more digits ending in 1, the final 1 is read "เอ็ด". Official document numbers are read digit by digit ("อ่านเรียงตัว"). House numbers starting with 0 are always read digit by digit. A time written with an hour number is read with "นาฬิกา". — [Trueplookpanya: ความรู้พื้นฐานเพื่อการอ่าน](https://www.trueplookpanya.com/learning/detail/31878-044467) (primary-school material, not ORST)

### Inferences (native-speaker conventions; verify)
- Money: "300,000 บาท" → "สามแสนบาท". bahttext(300000) gives "สามแสนบาทถ้วน". In speech, "ถ้วน" is normal for formal amounts but sounds receipt-like in conversation, so consider stripping it. Decimals: "1,250.50 บาท" → "หนึ่งพันสองร้อยห้าสิบบาท ห้าสิบสตางค์". Note "หนึ่งพัน" vs "พัน": speech often drops the leading หนึ่ง, but keep หนึ่ง for clarity on phone audio.
- Dates: "15 ตุลาคม 2569" → "วันที่สิบห้า ตุลาคม พ.ศ. สองพันห้าร้อยหกสิบเก้า", or in speech just "สิบห้า ตุลาคม สองห้าหกเก้า". Agents commonly read years digit by digit ("สองห้าหกเก้า"), which is shorter and clearer than "สองพันห้าร้อยหกสิบเก้า". Either is acceptable, so pick one and keep it consistent. Read the abbreviation "พ.ศ." as "พอศอ" in speech; "พุทธศักราช" is formal. Never let the TTS read "พ.ศ." letter-by-letter with the dots.
- Times: "00.01 น." → "ศูนย์นาฬิกาหนึ่งนาที" (formal 24h), or in speech "เที่ยงคืนหนึ่งนาที" or "หลังเที่ยงคืนหนึ่งนาที". For policy-coverage start times, formal "เวลาศูนย์นาฬิกาหนึ่งนาที" is common in Thai insurance documents. "น." must map to "นาฬิกา", or be removed after conversion. Risk: "น." also abbreviates other words, so do this only in the pattern `\d{1,2}[.:]\d{2}\s*น\.`.
- Phone numbers: read digit by digit, grouped by the hyphens, with a short pause between groups. "02-624-1111" → "ศูนย์สอง <pause> หกสองสี่ <pause> หนึ่งหนึ่งหนึ่งหนึ่ง". Use "หนึ่ง", never "เอ็ด", for digits in numbers. Some speakers say "โท" for 2 to avoid confusion with "สาม" over noisy lines. This is a military/radio convention and uncommon in call centers, so don't use it by default. Never let the TTS read "1111" as "หนึ่งพันหนึ่งร้อยสิบเอ็ด".
- Emails/URLs: spell out in Thai-pronounced English letters, with "แอท" for @, "ดอท" for ".", and "ขีดล่าง" for "_", e.g., "info at kpi dot co dot th" → "อินโฟ แอท เคพีไอ ดอท ซีโอ ดอท ทีเอช". Spelled letters are best inserted as Thai transliteration so the Thai voice doesn't switch accent mid-utterance. Better still, avoid reading emails on the phone and offer SMS/LINE instead.
- English loanwords and acronyms: transliterate to Thai for a consistent Thai accent. AI → "เอไอ", PA → "พีเอ", QR Code → "คิวอาร์โค้ด", KPI → "เคพีไอ". The product name is already in Thai script ("พีเอ เต็มใจ"), which is good.
- ๆ (ไม้ยมก): expand before TTS with maiyamok or a regex, because some TTS engines skip it or read it as a symbol. ฯ / ฯลฯ: expand to "และอื่น ๆ" → "และอื่นอื่น".
- Common normalization order: (1) protect phone numbers, policy numbers and IDs (digit-by-digit); (2) times with น.; (3) dates; (4) money with บาท; (5) remaining cardinals; (6) abbreviations (พ.ศ., น., บ., กทม.); (7) ๆ; (8) Latin acronyms → Thai transliteration lexicon.

### Gaps
- I couldn't retrieve an official ORST rule for reading phone numbers, times with "น.", or abbreviation reading ("พ.ศ." = พอศอ vs พุทธศักราช). The abbreviation guidance above is native-speaker knowledge.
- I didn't verify whether Gemini TTS normalizes Thai numbers and dates correctly on its own. No source tested this, so test it empirically with the KPI lines.

## Q4. Gemini TTS (2.5 / 3.1 / 3.8 Flash): streaming, style control, pause tags, voices, Thai support, known issues

### Takeaway
gemini-3.8-flash-tts supports Thai (Flash-Lite TTS does not), streaming 24 kHz mono 16-bit PCM, a per-turn `speech_metadata.style` string, and angle-bracket inline tags. The docs show `<short pause>` / `<long pause>`, not a bare `<pause>`. The docs also say long "Audio Profile / Director's Notes" prompts are the main cause of voice drift. For 3.8, Google recommends creating a custom voice with Voice design and keeping style strings minimal. Users report random tonal jumps after sentence boundaries on 3.8 (acknowledged by Google, unresolved), plus voice identity drift between separate requests on 3.1 and 2.5.

### Cited Findings
- Models (Gemini API): `gemini-3.8-flash-tts` and `gemini-3.8-flash-lite-tts` support single-speaker, multi-speaker, voice design and voice replication. 3.1 Flash TTS Preview and 2.5 Pro Preview TTS support single- and multi-speaker only. Flash-Lite is the "fast, cost-efficient workhorse" for voice agents, and Flash offers "maximum acoustic fidelity". — [Gemini API speech generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- Thai: Flash TTS supports "over 130 languages" and Flash-Lite "over 100". **Thai is supported by Flash TTS only, not Flash-Lite.** Language is auto-detected. — [Gemini API speech generation](https://ai.google.dev/gemini-api/docs/speech-generation). Cloud TTS lists th-TH as **GA** for its Gemini-TTS models (2.5 Flash/Pro, 3.1 Flash preview). — [Cloud TTS Gemini-TTS](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts)
- Streaming: with `stream: true`, the API returns "headerless raw 16-bit signed little-endian linear PCM (audio/l16, 24 kHz, mono)" chunks. Unary requests return WAV. The Interactions API example uses `model`, `input` (user_input text plus `speech_metadata.style`), `response_format: audio`, `generation_config.speech_config` (voice e.g. "Kore") and `stream: True`, and reads `step.delta` audio events. — [Gemini API speech generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- Latency: the Gemini API page gives **no** time-to-first-audio figure. Cloud docs only say "very low latency". — [Gemini API](https://ai.google.dev/gemini-api/docs/speech-generation); [Cloud TTS](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts)
- Style control (3.8): put turn-wide emotion, delivery, prosody, pacing and volume in `speech_metadata.style` (examples: "warm and enthusiastic", "whispered urgently"). Don't put immutable traits (age, gender, permanent accent) in style. Use a library voice or Voice design instead. The `text` field is "strictly" a verbatim transcript. Instructions are split by scope "to control delivery without having stage directions read aloud". — [Gemini API speech generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- Voice drift guidance: long "Audio Profile" paragraphs and multi-bullet "Director's Notes" carried over from earlier models "are the most common cause of voice drift". The fix is to create a custom voice via Voice design and reuse its ID with minimal or empty style. — [Gemini API speech generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- Inline tags (3.8, Gemini API): angle brackets, about 40 recommended vocal tags, including `<breath>`, `<sigh>`, `<laugh>`, `<chuckle>`, `<whispers>`, `<throat-clearing>`, `<tsk>`, and **`<short pause>` and `<long pause>`**. Sound-effect tags are discouraged. Use English tags in non-English transcripts. Multi-speaker backchannels use pipes, e.g. `|oh really?|`. — [Gemini API speech generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- **Discrepancy:** Cloud TTS docs (2.5 / 3.1 models) use square-bracket tags: `[short pause]`, `[medium pause]`, `[long pause]`, `[sigh]`, `[uhm]`, `[whispering]`, `[extremely fast]`, etc. Vocalized-adjective tags (`[scared]`, `[curious]`) cause "the tag itself is spoken". "The behavior of a new or untested tag is not always predictable". — [Cloud TTS Gemini-TTS](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts). The task brief's `<pause>` is not in the 3.8 list. Use `<short pause>` / `<long pause>`.
- Third-party pause durations for 3.1: short ≈250 ms, medium ≈500 ms, long ≈1000 ms+. Some tags may be spoken aloud. — [Replicate readme](https://replicate.com/google/gemini-3.1-flash-tts/readme) (unofficial)
- Google Cloud blog (3.1): tags are English-only but can mix with other-language text. Separate tags with text or punctuation, and don't put two tags directly adjacent. — [Google Cloud blog, 3.1 Flash TTS](https://cloud.google.com/blog/products/ai-machine-learning/gemini-3-1-flash-tts-on-google-cloud/) (via search summary)
- Pacing via punctuation: commas, periods and semicolons create pauses. — same source. LiveKit (3.1) recommends commas between clauses because period-separated fragments sound choppy, 1–2 ellipses per utterance for trailing pauses, and 1 em-dash per utterance for micro-pauses. — [LiveKit prompting guide](https://livekit.com/blog/gemini-3.1-flash-tts-prompting-guide)
- LiveKit (3.1) on prompts read aloud: "Vague prompts may fail to trigger the speech synthesis classifier". Use a synthesize-speech preamble and a `#### TRANSCRIPT` header. The apostrophe in "DIRECTOR'S" got spoken. Avoid "quiet", "flat", "monotone", "no rush" in style notes because they crashed prosody; prefer "warm and sincere", "patient and unhurried". Custom emotional tags (`[apologetically]`, `[softly]`) gave flatter delivery. Empty `content.parts` and 500 preview bugs need retry with backoff. — [LiveKit prompting guide](https://livekit.com/blog/gemini-3.1-flash-tts-prompting-guide)
- Cloud TTS limits: text and prompt fields ≤4,000 bytes each and ≤8,000 combined, so Thai at 3 bytes/char UTF-8 gives about 1,300 chars. Output is limited to about 655 s. temperature/top_k/top_p are ignored. In streaming, the prompt must be in the first chunk. — [Cloud TTS Gemini-TTS](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts)
- Female voices (Cloud TTS list): Achernar, Aoede, Autonoe, Callirrhoe, Despina, Erinome, Gacrux, Kore, Laomedeia, Leda, Pulcherrima, Sulafat, Vindemiatrix, Zephyr. — [Cloud TTS Gemini-TTS](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts). Gemini API descriptors: Vindemiatrix "Gentle", Sulafat "Warm", Despina "Smooth", Callirrhoe "Easy-going", Erinome "Clear", Gacrux "Mature" (per the Gemini API list; Kore, used in Google's code sample, had no descriptor in the fetched page). — [Gemini API speech generation](https://ai.google.dev/gemini-api/docs/speech-generation). 3.8 also has an Extended Voice Library filterable by language and gender, Voice design (`voice_...` IDs, 200 per project, 1-year TTL), and voice replication.
- Known issues (forum, user reports):
  - **3.8:** "drifts much less than previous models" but randomly switches tone. Nearly every 2–7 min clip had an abrupt tonal jump, usually right after a sentence boundary. A voice change mid-phrase inserted a word not in the input. A Google moderator escalated it to engineering. — [Forum: Gemini 3.8 TTS voice consistency issue](https://discuss.ai.google.dev/t/gemini-3-8-tts-voice-consistency-issue/186103)
  - **3.1:** voice identity (timbre, pitch, perceived age) changes between separate requests. — [Forum thread](https://discuss.ai.google.dev/t/gemini-3-1-flash-tts-preview-voice-identity-changes-between-separate-requests/179498)
  - **2.5:** female voice produced when a male voice was configured; voice inconsistent across long sentences (Feb 2026, no reply). — [Forum](https://discuss.ai.google.dev/t/gemini-tts-voice-consistency/124172); also [24-reply thread](https://discuss.ai.google.dev/t/inconsistent-audio-output-with-gemini-2-5-pro-preview-tts/101454)
  - A user complaint that the 3.8 voice is flat and generic for assistant apps. — [Forum](https://discuss.ai.google.dev/t/gemini-3-8-tts-voice-is-a-downgrade-for-personal-assistant-and-companion-apps/184911)

### Inferences
- For KPI: use `gemini-3.8-flash-tts`, not Flash-Lite, because of Thai support. Create one Voice-design voice ("calm, warm, professional Thai female contact-center agent, mid-pitch, clear diction") and reuse its ID. Keep `style` short and stable across all turns (e.g., "warm, polite and unhurried"). Changing the style per turn invites drift.
- Per-utterance requests (one per bot turn or sentence chunk) are inherently exposed to the reported between-request identity drift. Mitigate this with a fixed custom voice ID, identical style, and short chunks. Measure it with a speaker-embedding similarity check in QA.
- Inline tags: use only `<short pause>` / `<long pause>` (e.g., between phone-number groups and before key figures), with text between tags. Avoid emotion tags on a contact-center line. Verify on Thai text that tags are not vocalized.
- Number reading: since no source covers Gemini's Thai number handling, pre-normalize to Thai words (Q3) to remove the uncertainty and keep the internal TTS swap seamless.
- SIP: resample 24 kHz → 8 kHz (G.711) or 16 kHz (G.722) at the gateway. Test intelligibility of digits and tones after narrowband resampling.

### Gaps
- No official TTFA/latency figures for 3.8 Flash TTS streaming via the Interactions API. Measure it.
- I found no published evaluation of Gemini TTS Thai quality (tones, particle prosody, number reading).
- Gemini API byte and length limits for 3.8 are not stated on the page I fetched. The Cloud limits above apply to Cloud TTS models.

## Q5. Sentence segmentation and chunking for Thai TTS

### Takeaway
Thai has no sentence punctuation. A space marks a clause or sentence boundary. PyThaiNLP `sent_tokenize` defaults to the CRF "crfcut" engine (~87% space-correct on ORCHID) and also offers whitespace and wtpsplit ("wtp-*") engines. For streaming LLM→TTS, chunk at spaces that follow a particle (ค่ะ/คะ/นะคะ) or at newlines, using a minimum chunk length.

### Cited Findings
- `sent_tokenize(text, engine='crfcut', keep_whitespace=True)`. Engines: crfcut (CRF trained on TED; space-correct accuracy 87% on ORCHID vs 95% SOTA, 82% on TED), thaisum, tltk, wtp / wtp-tiny / wtp-mini / wtp-base / wtp-large (wtpsplit), whitespace (`r" +"`), and whitespace+newline. Whitespace splitting breaks dates: "['ฉันไปประชุมเมื่อวันที่', '11', 'มีนาคม']". `clause_tokenize(list_of_words)` uses a CRF trained on the Blackboard Treebank. `paragraph_tokenize` uses wtp-mini by default. — [PyThaiNLP tokenize docs](https://pythainlp.org/docs/5.0/api/tokenize.html)
- The 3.8 tonal jumps cluster right after sentence boundaries. — [Forum](https://discuss.ai.google.dev/t/gemini-3-8-tts-voice-consistency-issue/186103)

### Inferences
- Plain whitespace splitting is unsafe: it splits "15 ตุลาคม 2569", "300,000 บาท" and "พีเอ เต็มใจ". Normalize numbers first, or protect entity spans, before splitting.
- A practical streaming heuristic: make the LLM emit a newline or `|` between utterances in its output contract. Otherwise, flush a TTS chunk when a space follows ค่ะ/คะ/นะคะ/ครับ or a question word, the buffer has 15 or more Thai characters, and no protected entity is open. Running crfcut on each streamed token adds latency, so reserve it for fallback or offline.
- Larger chunks (1–2 sentences) give better prosody and fewer request-boundary voice shifts. Smaller chunks give lower time-to-first-audio. Start with the first chunk small (first clause) and later chunks at sentence size.

### Gaps
- No benchmark of wtp-* vs crfcut on conversational, LLM-generated Thai. No published data on Gemini TTS prosody across chunk boundaries for Thai.
