"""`kpi-tts`: audition voices, speak a line, and measure real turn lengths with the Gemini Live voice."""

import argparse
import asyncio
import statistics
import subprocess
import sys
import time
from pathlib import Path

from kpi_voicebot.campaigns import get_profile
from kpi_voicebot.config import get_settings
from kpi_voicebot.tts import Speaker, fidelity, seconds, speaker, write_wav
from kpi_voicebot.tts_text import speakable

# Female voices from Google's prebuilt catalogue that sound calm and professional in Thai.
AUDITION_VOICES = ["Sulafat", "Vindemiatrix", "Despina", "Erinome", "Achernar", "Kore", "Aoede", "Leda"]
AUDITION_LINES = [
    "สวัสดีค่ะ ขอเรียนสายคุณสมชาย ใจดีค่ะ",
    "ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาทค่ะ",
    "ผู้รับผลประโยชน์ คือ นางสาวสมใจ ใจดี บุตรสาว ใช่ไหมคะ",
    "เรื่องรอสายนาน ดิฉันจดไว้ให้แล้วนะคะ ขอบคุณที่บอกค่ะ",
]
OUT = Path(".local/tts_audition")


def play(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["afplay", str(path)], check=False)


async def audition(voices: list[str], listen: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{'voice':14} {'first audio':>11} {'speech':>7} {'chars/s':>8} {'verbatim':>9}")
    for voice in voices:
        s = speaker(get_settings(), voice, provider="gemini")
        clips, firsts, scores = [], [], []
        for line in AUDITION_LINES:
            spoken = speakable(line)
            pcm = b"".join([c async for c in s.voice.stream(spoken)])
            clips.append(pcm)
            firsts.append(s.voice.last_first_audio_s)
            scores.append(fidelity(spoken, s.voice.last_heard))
        await s.voice.close()
        joined = (b"\x00\x00" * (s.sample_rate // 2)).join(clips)
        write_wav(OUT / f"{voice}.wav", joined, s.sample_rate)
        chars = sum(len(speakable(line).replace(" ", "")) for line in AUDITION_LINES)
        speech = sum(seconds(c, s.sample_rate) for c in clips)
        print(f"{voice:14} {statistics.median(firsts):10.2f}s {speech:6.1f}s {chars / speech:8.1f} {min(scores):9.2f}")
        if listen:
            play(OUT / f"{voice}.wav")
    print(f"\nListen: open {OUT.resolve()} (one file per voice)")


async def _scenario_turns(profile_id: str = "all") -> dict[str, str]:
    """Every distinct bot turn the scripted scenarios produce (text -> directive key)."""
    from typing import Any

    from kpi_voicebot.models import Directive
    from kpi_voicebot.simulator import build_engine, load_scenarios, run_script

    turns: dict[str, str] = {}

    class Sink:
        async def bot(self, d: Directive, n: int, complete: bool) -> None:
            turns.setdefault(" ".join(seg.text for seg in d.segments[:n]), d.key)

        async def customer(self, text: str) -> None: ...
        async def event(self, kind: str, data: dict[str, Any] | None = None) -> None: ...

    for sc in load_scenarios():
        if profile_id not in {"all", sc.profile}:
            continue
        profile = get_profile(sc.profile)
        assert profile is not None
        await run_script(build_engine(sc.campaign, profile.case, "สมชาย ใจดี"), sc.customer, Sink())
    return turns


async def prerender(profile_id: str, concurrency: int = 4) -> None:
    """Verified readings of every scripted turn, so a call plays them with no wait at all."""
    turns = list(await _scenario_turns(profile_id))
    if not turns:
        sys.exit(f"no scenarios for profile {profile_id}")
    speakers = [speaker(get_settings()) for _ in range(concurrency)]
    queue: asyncio.Queue[str] = asyncio.Queue()
    for text in turns:
        queue.put_nowait(text)
    failed: list[str] = []
    started = time.monotonic()

    async def work(s: Speaker) -> None:
        while not queue.empty():
            text = queue.get_nowait()
            if not await s.prerender(text):
                failed.append(text)
        await s.voice.close()

    await asyncio.gather(*(work(s) for s in speakers))
    print(f"{len(turns) - len(failed)}/{len(turns)} turns verified in {time.monotonic() - started:.0f}s")
    for text in failed:
        print(f"  not verified (will be spoken live): {text}")


async def lengths() -> None:
    """Real spoken length of every scripted bot turn (uses and fills the cache)."""
    s = speaker(get_settings())
    started = time.monotonic()
    real = sorted(
        [(seconds(await s.render(text), s.sample_rate), key) for text, key in (await _scenario_turns()).items()],
        reverse=True,
    )
    await s.voice.close()
    over = [t for t in real if t[0] > 12]
    print(
        f"{len(real)} distinct bot turns in {time.monotonic() - started:.0f}s; "
        f"median {statistics.median(t[0] for t in real):.1f}s; {len(over)} over 12 s"
    )
    for sec, key in real[:12]:
        print(f"  {sec:5.1f}s  {key}")


# Replies a customer gives on these calls, including the ones the bot must not mishear.
ASR_REPLIES = [
    "ครับ",
    "อ่าห้ะ",
    "ถั่วต้ม",
    "ไม่ใช่ครับ เบี้ยสามพันบาทต่อปี",
    "ตอนนี้ไม่สะดวกครับ โทรมาใหม่พรุ่งนี้บ่ายสองโมงได้ไหม",
    "ครับ คิดว่าน่าจะใช่นะ",
    "ก็โอเคนะครับ แต่รอสายนานไปหน่อย",
    "ให้สี่คะแนนครับ",
    "ใช่ครับ ผมสมชาย ใจดี พูดอยู่ครับ",
]


def _resample(pcm: bytes, src: int, dst: int) -> bytes:
    """Linear resampling 16-bit mono (enough for a recognition benchmark)."""
    import array

    samples = array.array("h", pcm)
    n = int(len(samples) * dst / src)
    out = array.array("h", bytes(2 * n))
    for i in range(n):
        x = i * src / dst
        j = int(x)
        frac = x - j
        a = samples[j] if j < len(samples) else 0
        b = samples[j + 1] if j + 1 < len(samples) else a
        out[i] = int(a + (b - a) * frac)
    return out.tobytes()


async def asr_bench() -> None:
    """Speak typical customer replies with JAI TTS, stream them to JaiASR at real-time pace,
    and report what it heard and how fast the turn was committed."""
    import difflib

    from kpi_voicebot.asr import FRAME_BYTES, SpeechStream, TurnCollector, speech_stream

    settings = get_settings()
    s = speaker(settings)
    for reply in ASR_REPLIES:
        pcm = _resample(await s.render(reply), s.sample_rate, 16_000)
        stream = speech_stream(settings)
        await stream.open(context="สมชาย ใจดี, พีเอ เต็มใจ")
        collector = TurnCollector()

        async def listen(st: SpeechStream = stream, col: TurnCollector = collector) -> None:
            async for event in st.events():
                col.feed(event)

        listener = asyncio.ensure_future(listen())
        audio = pcm + b"\x00\x00" * 16_000  # a second of silence after speaking
        speech_end = 0.0
        started = time.monotonic()
        for i in range(0, len(audio), FRAME_BYTES):
            await stream.send(audio[i : i + FRAME_BYTES])
            if i >= len(pcm) and not speech_end:
                speech_end = time.monotonic()
            await asyncio.sleep(max(0.0, started + (i + FRAME_BYTES) / 32_000 - time.monotonic()))
        await stream.finish()
        await asyncio.wait_for(listener, 15)
        await stream.close()
        heard = " ".join(collector.committed + ([collector.partial] if collector.partial else []))
        lag = collector.last_commit_at - speech_end if collector.last_commit_at else float("nan")
        score = difflib.SequenceMatcher(None, reply.replace(" ", ""), heard.replace(" ", "")).ratio()
        print(f"{score:4.2f}  commit +{lag:4.2f}s after speech  said: {reply}  heard: {heard}")
    await s.voice.close()


async def say(text: str) -> None:
    s = speaker(get_settings())
    pcm = await s.render(text)
    await s.voice.close()
    path = OUT / "say.wav"
    write_wav(path, pcm, s.sample_rate)
    print(f"{speakable(text)}  ({seconds(pcm, s.sample_rate):.1f}s, first audio {s.voice.last_first_audio_s:.2f}s)")
    play(path)


def main() -> None:
    parser = argparse.ArgumentParser(prog="kpi-tts", description="KPI voicebot speech tools (JAI TTS voice)")
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("audition", help="render sample lines in several Gemini female voices (comparison only)")
    a.add_argument("--voices", nargs="*", default=AUDITION_VOICES)
    a.add_argument("--listen", action="store_true", help="play each voice (macOS)")
    p = sub.add_parser("prerender", help="verify and cache every scripted turn (no wait during calls)")
    p.add_argument("profile", nargs="?", default="all", help="profile id, or 'all'")
    sub.add_parser("lengths", help="measure the real spoken length of every scripted bot turn")
    sub.add_parser("asr-bench", help="JaiASR accuracy and commit latency on typical customer replies")
    s = sub.add_parser("say", help="speak one line with the configured voice")
    s.add_argument("text")
    args = parser.parse_args()
    if args.command == "audition":
        asyncio.run(audition(args.voices, args.listen))
    elif args.command == "prerender":
        asyncio.run(prerender(args.profile))
    elif args.command == "asr-bench":
        asyncio.run(asr_bench())
    elif args.command == "lengths":
        asyncio.run(lengths())
    else:
        asyncio.run(say(args.text))
