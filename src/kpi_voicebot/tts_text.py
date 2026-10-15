"""Thai text normalisation for speech: what the TTS should *say*, not what the screen shows.

Numbers, money, dates, times, phone numbers, emails, web addresses and acronyms are
turned into Thai words in a fixed order, so the voice never guesses ("300,000" →
"สามแสน", "02-624-1111" → "ศูนย์สอง หกสองสี่ หนึ่งหนึ่งหนึ่งหนึ่ง").
"""

import re

_DIGITS = ("ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า")
_PLACES = ("", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน")
_LETTERS = {
    "a": "เอ",
    "b": "บี",
    "c": "ซี",
    "d": "ดี",
    "e": "อี",
    "f": "เอฟ",
    "g": "จี",
    "h": "เอช",
    "i": "ไอ",
    "j": "เจ",
    "k": "เค",
    "l": "แอล",
    "m": "เอ็ม",
    "n": "เอ็น",
    "o": "โอ",
    "p": "พี",
    "q": "คิว",
    "r": "อาร์",
    "s": "เอส",
    "t": "ที",
    "u": "ยู",
    "v": "วี",
    "w": "ดับเบิลยู",
    "x": "เอ็กซ์",
    "y": "วาย",
    "z": "แซด",
}
_WORDS = {"com": "คอม", "qr code": "คิวอาร์โค้ด", "qr": "คิวอาร์", "email": "อีเมล", "e-mail": "อีเมล"}
# Domain names people say as words; any other label is spelled letter by letter.
_DOMAIN_WORDS = {
    "com": "คอม",
    "net": "เน็ต",
    "org": "ออร์ก",
    "gmail": "จีเมล",
    "hotmail": "ฮอตเมล",
    "outlook": "เอาท์ลุค",
    "yahoo": "ยาฮู",
    "icloud": "ไอคลาวด์",
    "live": "ไลฟ์",
    "example": "เอ็กแซมเปิล",
}
_SYMBOLS = {".": "ดอท", "_": "อันเดอร์สกอร์", "-": "ขีด", "+": "พลัส"}


def number_words(n: int) -> str:
    """Thai reading of a non-negative integer (เอ็ด for a trailing one, ยี่สิบ for twenty)."""
    if n == 0:
        return "ศูนย์"
    if n >= 1_000_000:
        millions, rest = divmod(n, 1_000_000)
        return number_words(millions) + "ล้าน" + (number_words(rest) if rest else "")
    out = []
    digits = str(n)
    length = len(digits)
    for i, ch in enumerate(digits):
        d = int(ch)
        place = length - i - 1
        if d == 0:
            continue
        if place == 0 and d == 1 and length > 1:
            out.append("เอ็ด")
        elif place == 1 and d == 1:
            out.append("สิบ")
        elif place == 1 and d == 2:
            out.append("ยี่สิบ")
        else:
            out.append(_DIGITS[d] + _PLACES[place])
    return "".join(out)


def digits_words(s: str) -> str:
    """Digit by digit, as Thai speakers read phone and account numbers ("หนึ่ง", never "เอ็ด")."""
    return "".join(_DIGITS[int(c)] for c in s if c.isdigit())


def spell(token: str) -> str:
    return "".join(_LETTERS.get(c, c) for c in token.lower() if c.isalnum())


def spell_out(token: str) -> str:
    """Letter by letter with a beat between letters, as an agent reads back an address:
    "somchai" → "เอส โอ เอ็ม ซี เอช เอ ไอ". Digits are Thai digit names."""
    out = []
    for c in token.lower():
        if c.isdigit():
            out.append(_DIGITS[int(c)])
        elif c in _LETTERS:
            out.append(_LETTERS[c])
        elif c in _SYMBOLS:
            out.append(_SYMBOLS[c])
    return " ".join(out)


def _phone(m: re.Match[str]) -> str:
    groups = re.split(r"[-\s]", m.group(0))
    return " ".join(digits_words(g) for g in groups if g)


def clock_words(hour: int, minute: int) -> str:
    """The time as Thai people say it, not as a timetable reads it:
    00.01 → เที่ยงคืนหนึ่งนาที, 08.30 → แปดโมงครึ่ง, 14.00 → บ่ายสองโมง, 19.15 → หนึ่งทุ่มสิบห้านาที."""
    hour %= 24
    if hour == 0:
        base = "เที่ยงคืน"
    elif hour <= 5:
        base = f"ตี{number_words(hour)}"
    elif hour <= 11:
        base = f"{number_words(hour)}โมงเช้า" if minute == 0 else f"{number_words(hour)}โมง"
    elif hour == 12:
        base = "เที่ยง" if minute else "เที่ยงวัน"
    elif hour == 13:
        base = "บ่ายโมง"
    elif hour <= 15:
        base = f"บ่าย{number_words(hour - 12)}โมง"
    elif hour <= 18:
        base = f"{number_words(hour - 12)}โมงเย็น" if minute == 0 else f"{number_words(hour - 12)}โมง"
    else:
        base = f"{number_words(hour - 18)}ทุ่ม"
    if minute == 0:
        return base
    if minute == 30:
        return f"{base}ครึ่ง"
    return f"{base}{number_words(minute)}นาที"


def _time(m: re.Match[str]) -> str:
    return clock_words(int(m.group(1)), int(m.group(2)))


def _domain(domain: str) -> str:
    parts = []
    for label in domain.split("."):
        low = label.lower()
        parts.append(_DOMAIN_WORDS.get(low) or (spell(label) if len(label) <= 3 else spell_out(label)))
    return " ดอท ".join(parts)


def _email(m: re.Match[str]) -> str:
    # The part before @ is personal: spell it, so the customer can check every letter.
    local, domain = m.group(1), m.group(2)
    return f"{spell_out(local)} แอท {_domain(domain)}"


def _url(m: re.Match[str]) -> str:
    # Thai speakers say "เคพีไอ ดอท ซีโอ ดอท ทีเอช" and skip the "www".
    host = m.group(0).removeprefix("https://").removeprefix("http://").rstrip("/")
    return _domain(host.removeprefix("www."))


def _amount(m: re.Match[str]) -> str:
    whole, _, frac = m.group(0).replace(",", "").partition(".")
    spoken = number_words(int(whole))
    if frac and int(frac):
        spoken += " จุด " + " ".join(_DIGITS[int(c)] for c in frac)
    return spoken


_LATIN_WORDS = {"excel": "เอ็กเซล", "email": "อีเมล", "line": "ไลน์", "online": "ออนไลน์", "ok": "โอเค", "code": "โค้ด"}
_ACRONYMS = {"AI": "เอไอ", "PA": "พีเอ", "KPI": "เคพีไอ", "SMS": "เอสเอ็มเอส", "SIP": "ซิป", "OTP": "โอทีพี"}


def speakable(text: str) -> str:
    """Normalise display text into what the voice should say. Order matters."""
    t = text
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)  # Markdown link → its text, never the address twice
    t = re.sub(r"[*`]+|^\s*#+\s*", " ", t)  # stray Markdown emphasis or headings (not _ : e-mails use it)
    t = re.sub(r"\(([^)]*)\)", r"\1", t)  # (มหาชน) → มหาชน
    t = re.sub(r"([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)", _email, t)
    t = re.sub(r"(?:https?://)?www\.[\w.-]+", _url, t)
    t = re.sub(r"\b0\d{1,2}[-\s]\d{3}[-\s]\d{4}\b|\b0\d{8,9}\b", _phone, t)
    t = re.sub(r"\b(\d{1,2})[.:](\d{2})\s*น\.", _time, t)
    t = re.sub(r"\bQR\s*Code\b", "คิวอาร์โค้ด", t, flags=re.IGNORECASE)
    for acronym, spoken in _ACRONYMS.items():
        t = re.sub(rf"(?<![A-Za-z]){acronym}(?![A-Za-z])", spoken, t)
    t = re.sub(r"\d[\d,]*(?:\.\d+)?", _amount, t)
    # A Thai voice cannot read Latin script: say known words, spell anything else.
    t = re.sub(r"[A-Za-z]+", lambda m: _LATIN_WORDS.get(m.group(0).lower()) or spell(m.group(0)), t)
    t = t.replace("ๆ", "")  # rare in our wording; the TTS repeats correctly without the mark
    return re.sub(r"\s+", " ", t).strip()
