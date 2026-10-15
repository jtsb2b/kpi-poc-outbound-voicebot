"""Destination parsing.

Thai numbers are stored canonically as E.164 (+66...) and converted to the national
0... form only at the SIP boundary, because that is the format the shared gateway accepts.
Non-Thai numbers are kept in E.164 but are not dialable until an international dial
format for the gateway is confirmed.
"""

import re
from dataclasses import dataclass
from typing import Literal

import phonenumbers

DestinationKind = Literal["thai", "international", "extension"]

_SEPARATORS = re.compile(r"[\s\-().]")
_EXTENSION = re.compile(r"^\d{3,5}$")


@dataclass(frozen=True)
class Destination:
    kind: DestinationKind
    entered: str
    e164: str | None
    display: str
    sip_destination: str | None
    dialable: bool
    reason: str | None = None


class InvalidPhone(ValueError):
    pass


def parse_destination(raw: str, *, allow_extensions: bool = False) -> Destination:
    entered = raw.strip()
    compact = _SEPARATORS.sub("", entered)
    if not compact:
        raise InvalidPhone("กรุณากรอกหมายเลขโทรศัพท์")

    if _EXTENSION.match(compact):
        if not allow_extensions:
            raise InvalidPhone("หมายเลขสั้นเกินไป (ยังไม่เปิดใช้เบอร์ภายใน)")
        return Destination("extension", entered, None, compact, compact, True)

    if compact.startswith("00"):
        compact = "+" + compact[2:]
    elif compact.startswith("66") and not compact.startswith("+"):
        compact = "+" + compact

    try:
        number = phonenumbers.parse(compact, "TH")
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhone("รูปแบบหมายเลขโทรศัพท์ไม่ถูกต้อง") from exc
    if not phonenumbers.is_valid_number(number):
        raise InvalidPhone("หมายเลขโทรศัพท์ไม่ถูกต้อง")

    e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    if phonenumbers.region_code_for_number(number) == "TH":
        national = "0" + str(number.national_number)
        display = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
        return Destination("thai", entered, e164, display, national, True)

    display = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    return Destination("international", entered, e164, display, None, False, "ยังไม่รองรับการโทรต่างประเทศ")
