# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
"""Common formatting rules for CRA's 2026 and 2027 T619, T4A and T5018 files."""
import re
import unicodedata

# CRA keeps only these characters and discards the rest. Each field follows one of three tables
# in the T619 specification: names, addresses, or free text typed on a keyboard.
FRENCH = "éàâçèêëîïôùüûÉÀÂÇÈÊËÎÏÔÙÜÛ"
NAME_ALLOWED = re.compile(rf"[^A-Za-z0-9{FRENCH}'&.\- ]")
ADDRESS_ALLOWED = re.compile(rf"[^A-Za-z0-9{FRENCH}'&.\- /#,(){{}}\[\]]")
KEYBOARD_ALLOWED = re.compile(rf"[^A-Za-z0-9{FRENCH}'&.\- /#,(){{}}\[\]\"\\|?!$%*+:;@]")
CONTACT_ALLOWED = re.compile(rf"[^A-Za-z0-9{FRENCH}'\- ]")
# Letters that do not decompose into a plain letter and an accent.
SPELLED = {
    "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ø": "o", "Ø": "O", "ł": "l", "Ł": "L",
    "đ": "d", "Đ": "D", "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ı": "i",
    "\u2018": "'", "\u2019": "'", "\u02bc": "'", "`": "'", "\u00b4": "'",
    "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u00a0": " ",
}

LIMITS = {
    "surname": 20,
    "given_name": 12,
    "initial": 1,
    "name_line": 30,
    "address_line": 30,
    "city": 28,
    "postal_code": 10,
    "contact_name": 22,
    "transmitter_contact_name": 35,
    "transmitter_name": 35,
    "email": 60,
    "amendment_note": 1309,
}
TABLES = {
    "address_line": ADDRESS_ALLOWED,
    "city": ADDRESS_ALLOWED,
    "amendment_note": KEYBOARD_ALLOWED,
    "contact_name": CONTACT_ALLOWED,
    "transmitter_contact_name": CONTACT_ALLOWED,
}

COUNTRY_CODES = {"CA": "CAN", "US": "USA"}
PROGRAM_ACCOUNT = re.compile(r"^\d{9}[A-Z]{2}\d{4}$")
SIN_PLACEHOLDER = "000000000"
BN_PLACEHOLDER = "000000000RT0000"


def transliterate(value, table=NAME_ALLOWED):
    """Turn letters CRA would discard into the nearest letter it keeps: Peña becomes Pena and
    Wałęsa becomes Walesa, while CRA's own French letters stay as they are."""
    result = []
    for char in value or "":
        char = SPELLED.get(char, char)
        if table.sub("", char) != char:
            char = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c))
        result.append(char)
    return "".join(result)


def clean_text(value, limit_key=None):
    """Keep only characters CRA accepts, collapse spaces and cut to the field's length."""
    table = TABLES.get(limit_key, NAME_ALLOWED)
    value = table.sub(" ", transliterate((value or "").replace("\n", " "), table))
    value = re.sub(r"\s+", " ", value).strip()
    if limit_key:
        value = value[: LIMITS[limit_key]].strip()
    return value


def changed_by_cleaning(value, limit_key):
    """True when CRA would receive something other than what was typed."""
    return bool(value) and clean_text(value, limit_key) != re.sub(r"\s+", " ", value).strip()


def split_lines(value, limit_key, count):
    """Split a long name over several lines on word boundaries."""
    words, lines, current = clean_text(value).split(), [], ""
    limit = LIMITS[limit_key]
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word[:limit]
    if current:
        lines.append(current)
    return lines[:count]


def postal_code(value, country_code="CA"):
    value = re.sub(r"[^A-Za-z0-9 \-]", "", value or "").upper().strip()
    if country_code == "CA":
        value = value.replace(" ", "").replace("-", "")
    return value[: LIMITS["postal_code"]]


def program_account(value):
    value = re.sub(r"[\s-]", "", value or "").upper()
    return value if PROGRAM_ACCOUNT.match(value) else ""


def sin_digits(value):
    value = re.sub(r"\D", "", value or "")
    return value if len(value) == 9 else ""


def phone_parts(value):
    """Return (area code, 'NNN-NNNN', extension) from a North American number, or None."""
    value = value or ""
    extension = ""
    match = re.search(r"(?:ext\.?|x|#)\s*(\d{1,5})\s*$", value, re.IGNORECASE)
    if match:
        extension = match.group(1)
        value = value[: match.start()]
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return digits[:3], f"{digits[3:6]}-{digits[6:]}", extension


def amount(value):
    return f"{max(value, 0.0):.2f}"
