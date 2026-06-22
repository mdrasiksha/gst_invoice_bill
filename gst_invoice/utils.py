"""Utility helpers for validation, dates, GSTINs and amount-to-words."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INDIAN_STATE_CODES = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman and Diu",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
}

STATE_ALIASES = {
    "andaman & nicobar islands": "Andaman and Nicobar Islands",
    "andaman nicobar islands": "Andaman and Nicobar Islands",
    "ap": "Andhra Pradesh",
    "ar": "Arunachal Pradesh",
    "as": "Assam",
    "br": "Bihar",
    "cg": "Chhattisgarh",
    "ch": "Chandigarh",
    "dd": "Daman and Diu",
    "dh": "Dadra and Nagar Haveli and Daman and Diu",
    "dl": "Delhi",
    "dn": "Dadra and Nagar Haveli and Daman and Diu",
    "ga": "Goa",
    "gj": "Gujarat",
    "hp": "Himachal Pradesh",
    "hr": "Haryana",
    "jh": "Jharkhand",
    "jk": "Jammu and Kashmir",
    "ka": "Karnataka",
    "kl": "Kerala",
    "la": "Ladakh",
    "ld": "Lakshadweep",
    "mh": "Maharashtra",
    "ml": "Meghalaya",
    "mn": "Manipur",
    "mp": "Madhya Pradesh",
    "mz": "Mizoram",
    "nl": "Nagaland",
    "od": "Odisha",
    "or": "Odisha",
    "pb": "Punjab",
    "py": "Puducherry",
    "rj": "Rajasthan",
    "sk": "Sikkim",
    "tn": "Tamil Nadu",
    "tr": "Tripura",
    "ts": "Telangana",
    "uk": "Uttarakhand",
    "up": "Uttar Pradesh",
    "ut": "Uttarakhand",
    "wb": "West Bengal",
}

ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def validate_gstin(gstin: str, optional: bool = False) -> bool:
    gstin = gstin.strip().upper()
    return (optional and not gstin) or bool(GSTIN_RE.match(gstin))


def validate_phone(phone: str) -> bool:
    return not phone.strip() or bool(PHONE_RE.match(phone.strip()))


def validate_email(email: str) -> bool:
    return not email.strip() or bool(EMAIL_RE.match(email.strip()))


def state_code_from_gstin(gstin: str) -> str:
    return gstin[:2] if gstin and len(gstin) >= 2 else ""


def normalize_state_name(state: str) -> str:
    value = " ".join((state or "").strip().split())
    if not value:
        return ""
    lowered = value.lower()
    if lowered in STATE_ALIASES:
        return STATE_ALIASES[lowered]
    for name in INDIAN_STATE_CODES.values():
        if lowered == name.lower():
            return name
    return value


def state_code_from_state(state: str) -> str:
    normalized = normalize_state_name(state)
    for code, name in INDIAN_STATE_CODES.items():
        if normalized.lower() == name.lower():
            return code
    return ""


def state_name_from_code(code: str) -> str:
    return INDIAN_STATE_CODES.get((code or "").strip().zfill(2), "")


def state_code_matches_state(state: str, code: str) -> bool:
    expected = state_code_from_state(state)
    return bool(expected and expected == (code or "").strip().zfill(2))


def _two_digit_words(number: int) -> str:
    if number < 20:
        return ONES[number]
    return (TENS[number // 10] + " " + ONES[number % 10]).strip()


def _three_digit_words(number: int) -> str:
    words = []
    if number >= 100:
        words.append(ONES[number // 100] + " Hundred")
        number %= 100
    if number:
        words.append(_two_digit_words(number))
    return " ".join(words)


def amount_to_words(amount: float | Decimal) -> str:
    """Convert INR amount to Indian numbering words."""
    amount = money(amount)
    rupees = int(amount)
    paise = int((amount - rupees) * 100)
    if rupees == 0:
        words = "Zero"
    else:
        parts = []
        crore, rupees = divmod(rupees, 10_000_000)
        lakh, rupees = divmod(rupees, 100_000)
        thousand, rupees = divmod(rupees, 1_000)
        hundred = rupees
        for value, label in ((crore, "Crore"), (lakh, "Lakh"), (thousand, "Thousand")):
            if value:
                parts.append(_three_digit_words(value) + " " + label)
        if hundred:
            parts.append(_three_digit_words(hundred))
        words = " ".join(parts)
    suffix = f" and {_two_digit_words(paise)} Paise" if paise else ""
    return f"Rupees {words}{suffix} Only"
