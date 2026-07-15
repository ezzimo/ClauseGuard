"""Ordered Moroccan PII regex rules.

Rules are applied longest/most specific first.  We intentionally do NOT mask
bare 6-10 digit numbers (RC numbers, references, amounts) unless they carry a
contextual prefix (CNSS / IF).
"""

import re

ORDERED_RULES: list[tuple[str, re.Pattern]] = [
    ("IBAN", re.compile(r"\bMA\d{2}(?:[ ]?\d){24}\b", re.IGNORECASE)),
    ("RIB", re.compile(r"\b\d(?:[ ]?\d){23}\b")),
    ("ICE", re.compile(r"\b\d{15}\b")),
    ("CIN", re.compile(r"\b[A-Z]{1,2}\d{5,7}\b")),
    ("CNSS", re.compile(r"\bCNSS\s*:?\s*\d{7,10}\b", re.IGNORECASE)),
    (
        "IF",
        re.compile(
            r"\b(?:IF|Identifiant\s+Fiscal)\s*:?\s*\d{6,10}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "PHONE",
        re.compile(
            r"(?:\+212|0)[\s.\-]?[5-7](?:[\s.\-]?\d){8}",
            re.IGNORECASE,
        ),
    ),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
]


def get_rules() -> list[tuple[str, re.Pattern]]:
    """Return a fresh view of the ordered rule list."""
    return list(ORDERED_RULES)
