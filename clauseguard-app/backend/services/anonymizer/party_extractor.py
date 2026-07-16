"""Heuristic extraction of person names from Moroccan/French contracts.

This is intentionally lightweight and regex-based so it works without
 downloading an NER model.  It looks for names introduced by courtesy titles
 (M., Monsieur, Mme, Madame, etc.) and for signature-block lines.
"""

import re

_PARTICLES = {
    "el", "ben", "bin", "bint", "ould",
    "de", "du", "des", "la", "le", "les",
    "van", "der", "den", "di", "del", "dos", "das", "al",
}

_STOP_TITLES = {
    "gérant", "gerant", "gérante", "gerante",
    "directeur", "directrice", "directeur général", "directrice générale",
    "général", "generale", "general", "manager",
    "président", "president", "présidente", "presidente",
    "fondateur", "fondatrice", "ceo", "dg", "administrateur", "administratrice",
    "représentant", "representant", "représentante", "representante",
    "associé", "associe", "associée", "associee",
}

_NAME_TOKEN = r"[A-Z][\w'-]+"
_PARTICLE_RE = "|".join(re.escape(p) for p in _PARTICLES)
# Keep names on a single line; do not let "\s" swallow newlines.
_NAME_UNIT = rf"(?:{_PARTICLE_RE}[ \t]+)?{_NAME_TOKEN}"
_NAME_RE = rf"{_NAME_UNIT}(?:[ \t]+{_NAME_UNIT}){{0,4}}"

_TITLE_RE = re.compile(
    rf"\b(?:M\.|Monsieur|Mme|Madame|Mlle|Mademoiselle)[ \t]+(?P<name>{_NAME_RE})",
    re.IGNORECASE,
)

# Signature lines like:
#   Pour le Prestataire
#   Youssef El Idrissi
_SIGNATURE_RE = re.compile(
    rf"^Pour le[ \t]+\w+[ \t]*$\s*(?P<name>{_NAME_RE})(?=\n|$)",
    re.IGNORECASE | re.MULTILINE,
)


def _trim_stop_titles(name: str) -> str:
    tokens = name.split()
    while tokens and tokens[-1].lower().rstrip(",.;:") in _STOP_TITLES:
        tokens.pop()
    return " ".join(tokens)


def extract_party_names(text: str) -> list[str]:
    """Return a deduplicated list of person names found in *text*."""
    candidates: list[str] = []
    for match in _TITLE_RE.finditer(text):
        name = _trim_stop_titles(match.group("name"))
        if name:
            candidates.append(name)
    for match in _SIGNATURE_RE.finditer(text):
        name = _trim_stop_titles(match.group("name"))
        if name:
            candidates.append(name)

    seen: set[str] = set()
    result: list[str] = []
    for name in candidates:
        key = name.lower()
        if key not in seen and len(name) >= 4:
            seen.add(key)
            result.append(name)
    return result
