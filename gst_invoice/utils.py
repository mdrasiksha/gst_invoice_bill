"""Utility helpers for validation, dates, GSTINs and amount-to-words."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

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
