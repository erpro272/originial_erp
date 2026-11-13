"""Indian GST helpers: GSTIN/PAN validation, state codes, money and number parsing.

Pure functions, no I/O. Used by customers (master data) and invoices (extraction checks).
"""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# GST state / UT codes (CBIC). 97 = Other Territory, 99 = Centre Jurisdiction.
STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan",
    "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}  # fmt: skip
_STATE_BY_NAME = {v.lower(): k for k, v in STATE_CODES.items()}
_STATE_ALIASES = {
    "j&k": "01", "jammu & kashmir": "01", "hp": "02", "uk": "05", "uttaranchal": "05",
    "new delhi": "07", "nct of delhi": "07", "up": "09", "orissa": "21", "mp": "23",
    "gj": "24", "mh": "27", "ka": "29", "tn": "33", "pondicherry": "34", "ts": "36",
    "ap": "37", "wb": "19", "daman and diu": "26", "dadra and nagar haveli": "26",
}  # fmt: skip

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum(first14: str) -> str:
    """GSTIN check character (mod-36 algorithm used by GSTN)."""
    total = 0
    for i, ch in enumerate(first14):
        product = _B36.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _B36[(36 - total % 36) % 36]


def gstin_errors(gstin: str | None) -> list[str]:
    """Empty list when valid. Messages are user-facing."""
    if not gstin:
        return []
    g = gstin.strip().upper()
    if len(g) != 15:
        return ["GSTIN must be 15 characters."]
    if not GSTIN_RE.match(g):
        return ["GSTIN format is invalid (expected e.g. 27AAACT2727Q1ZV)."]
    errs = []
    if g[:2] not in STATE_CODES:
        errs.append(f"GSTIN state code {g[:2]} does not exist.")
    if gstin_checksum(g[:14]) != g[14]:
        errs.append("GSTIN checksum is invalid (check for a typo).")
    return errs


def is_valid_gstin(gstin: str | None) -> bool:
    return bool(gstin) and not gstin_errors(gstin)


def pan_errors(pan: str | None) -> list[str]:
    if not pan:
        return []
    return [] if PAN_RE.match(pan.strip().upper()) else ["PAN format is invalid (e.g. AAACT2727Q)."]


def pan_from_gstin(gstin: str) -> str:
    return gstin.strip().upper()[2:12]


def state_code_from_gstin(gstin: str) -> str:
    return gstin.strip()[:2]


def normalize_state(value: str | None) -> str | None:
    """'Maharashtra' / 'MH' / '27' / '27-Maharashtra' -> '27'."""
    if not value:
        return None
    v = value.strip()
    m = re.match(r"^(\d{1,2})\b", v)
    if m and m.group(1).zfill(2) in STATE_CODES:
        return m.group(1).zfill(2)
    name = re.sub(r"^\d+\s*[-:]\s*", "", v).strip().lower().rstrip(".")
    return _STATE_BY_NAME.get(name) or _STATE_ALIASES.get(name)


# ---- money ---------------------------------------------------------------------------

_MONEY_CLEAN = re.compile(r"[₹,\s]|rs\.?|inr|/-", re.IGNORECASE)


def parse_money_paise(raw: str | None) -> int | None:
    """'₹1,23,456.50' -> 12345650. '(1,000)' or '-1,000' -> negative. None if unparseable."""
    if raw is None:
        return None
    s = raw.strip()
    neg = (s.startswith("(") and s.endswith(")")) or s.startswith(("-", "−"))
    s = _MONEY_CLEAN.sub("", s).strip("()-−+")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    paise = int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return -paise if neg else paise


def parse_decimal(raw: str | None) -> Decimal | None:
    """'1,20,000' -> 120000 ; '18%' -> 18 ; '2.5 KG' -> 2.5."""
    if raw is None:
        return None
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+", raw.replace(" ", ""))
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None


# ---- amount in words (Indian system) ---------------------------------------------------

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip
_SCALES = {
    "hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
    "lacs": 100_000, "crore": 10_000_000, "crores": 10_000_000, "million": 1_000_000,
}  # fmt: skip


def _words_to_int(words: list[str]) -> int | None:
    total = current = 0
    seen = False
    for w in words:
        if w in _UNITS:
            current += _UNITS[w]
            seen = True
        elif w == "hundred":
            current = (current or 1) * 100
            seen = True
        elif w in _SCALES:
            total += (current or 1) * _SCALES[w]
            current = 0
            seen = True
        else:
            return None
    return total + current if seen else None


def words_to_paise(text: str | None) -> int | None:
    """'Rupees Fifty Lakh Twelve Thousand and Fifty Paise Only' -> 5_012_000_50."""
    if not text:
        return None
    t = text.lower().replace("-", " ").replace(",", " ")
    t = re.sub(r"\b(indian|inr|rs\.?|rupee|rupees|only)\b|[^a-z ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    rupee_part, paise_part = t, ""
    m = re.match(r"^(.*?)\s*\b(?:paise|paisa)\b\s*$", t)
    if m:
        body = m.group(1)
        if " and " in f" {body} ":
            idx = f" {body} ".rfind(" and ")
            rupee_part, paise_part = body[: max(idx - 1, 0)], body[idx + 3 :]
        else:  # "<rupees> <paise>" without "and": paise are the words after the last scale
            toks = body.split()
            last = max((i for i, w in enumerate(toks) if w in _SCALES), default=-1)
            rupee_part, paise_part = " ".join(toks[: last + 1]), " ".join(toks[last + 1 :])
    words = [w for w in rupee_part.split() if w != "and"]
    rupees = _words_to_int(words) if words else 0
    paise = _words_to_int(paise_part.split()) if paise_part.strip() else 0
    if rupees is None or paise is None or paise >= 100:
        return None
    return rupees * 100 + paise


def financial_year(d: "object") -> str:
    """date(2026, 11, 13) -> '2026-27' (Indian FY runs April to March)."""
    from datetime import date as _date

    assert isinstance(d, _date)
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"
