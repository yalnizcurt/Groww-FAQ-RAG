"""PII guard — detect PAN, Aadhaar, account numbers, OTPs, email, phone in input."""

from __future__ import annotations

import re
from typing import List

# PAN: 5 letters, 4 digits, 1 letter.
_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
# Aadhaar: 12 digits, optionally with spaces in groups of 4.
_AADHAAR_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
# Indian phone: +91 followed by 10 digits, or 10 digits beginning with 6–9.
_PHONE_RE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}\b")
# Email.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# OTP keyword + digits (allow some words between keyword and digits, e.g. "OTP is 123456").
_OTP_RE = re.compile(r"\b(otp|one[- ]time[- ]password)\b[^\d\n]{0,30}\d{4,8}\b", re.IGNORECASE)
# Account number: digits 9-18 long that are NOT part of phone/aadhaar.
_ACCOUNT_RE = re.compile(r"\b(?:account|a/c|acct)[\s.:]*\d{6,18}\b", re.IGNORECASE)


def detect_pii(text: str) -> List[str]:
    if not text:
        return []
    t = text.strip()
    found: List[str] = []
    if _PAN_RE.search(t):
        found.append("pan")
    if _AADHAAR_RE.search(t):
        found.append("aadhaar")
    if _PHONE_RE.search(t):
        found.append("phone")
    if _EMAIL_RE.search(t):
        found.append("email")
    if _OTP_RE.search(t):
        found.append("otp")
    if _ACCOUNT_RE.search(t):
        found.append("account")
    return found
