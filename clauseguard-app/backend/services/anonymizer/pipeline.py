"""PII anonymization pipeline.

Steps:
1. Party names (full + last-token surname) masking FIRST.
2. Optional GLiNER NER person detection.
3. Ordered regex rule masking (IBAN, RIB, ICE, CIN, CNSS, IF, phone, email).
4. Final verification pass + optional leak error.
"""

import re
from typing import Optional

from .ner_detector import detect_people
from .placeholders import PlaceholderStore, preserve_whitespace_replace
from .regex_rules import get_rules


class AnonymizationLeakError(Exception):
    """Raised when PII is still detectable after two masking passes."""

    pass


def _build_party_regex(patterns: list[str]) -> Optional[re.Pattern]:
    escaped = [re.escape(p) for p in patterns if p.strip()]
    if not escaped:
        return None
    # Longest first so multi-word names match before their sub-components.
    escaped.sort(key=len, reverse=True)
    return re.compile(rf"\b({'|'.join(escaped)})\b", re.IGNORECASE)


def _letter_index(n: int) -> str:
    """Return 0-based letter index: 0->A, 1->B, ... 25->Z, 26->AA, etc."""
    result = ""
    n += 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(ord("A") + rem) + result
    return result


def _mask_people(text: str, store: PlaceholderStore, stats: dict) -> str:
    """Mask person names detected by the optional NER layer."""
    people = detect_people(text)
    if not people:
        return text

    masked = text
    for person_text, score in people:
        pattern = rf"\b{re.escape(person_text)}\b"
        regex = re.compile(pattern, re.IGNORECASE)

        def replace_person(match: re.Match) -> str:
            label = store.get_label("person", match.group(0).strip())
            return preserve_whitespace_replace(match, label)

        masked = regex.sub(replace_person, masked)

    stats["ner_persons"] = stats.get("ner_persons", 0) + len(people)
    return masked


def _mask_party_names(text: str, party_names: list[str], store: PlaceholderStore) -> str:
    """Mask full party names and standalone last-token surnames.

    Surname = last token of the name, when it is at least 4 characters long.
    This covers surnames like "Benjelloun" and "Fassi" while leaving short
    particles (El, Ben, etc.) untouched.

    Surnames get their own placeholder mapping back to the exact surname text
    so that round-trip unmasking preserves the original document verbatim.
    """
    full_names: list[str] = []
    surname_entries: list[tuple[str, str, str]] = []

    for idx, raw_name in enumerate(party_names):
        name = raw_name.strip()
        if not name:
            continue
        full_names.append(name)
        full_label = f"[PARTIE_{_letter_index(idx)}]"
        store.set_label("partie", name, full_label)

        tokens = name.split()
        if len(tokens) > 1:
            surname = tokens[-1].strip()
            if len(surname) >= 4:
                surname_label = f"[PARTIE_{_letter_index(idx)}_NOM]"
                store.set_label("partie_nom", surname, surname_label)
                surname_entries.append((surname.lower(), surname_label, surname))

    masked = text

    # Mask full names first.
    full_regex = _build_party_regex(full_names)
    if full_regex:
        def replace_full(match: re.Match) -> str:
            label = store.lookup("partie", match.group(0).lower())
            if not label:
                label = store.get_label("partie", match.group(0))
            return preserve_whitespace_replace(match, label)

        masked = full_regex.sub(replace_full, masked)

    # Mask standalone surnames.
    surnames = [entry[0] for entry in surname_entries]
    surname_regex = _build_party_regex(surnames)
    if surname_regex:
        def replace_surname(match: re.Match) -> str:
            key = match.group(0).lower()
            for k, label, _ in surname_entries:
                if k == key:
                    return preserve_whitespace_replace(match, label)
            return match.group(0)

        masked = surname_regex.sub(replace_surname, masked)

    return masked


def _apply_rule_matches(
    text: str,
    category: str,
    rule: re.Pattern,
    store: PlaceholderStore,
) -> tuple[str, int]:
    """Apply a regex rule to text and return (new_text, number_of_matches).

    Replacements are applied from right to left so that earlier replacements do
    not invalidate the match positions of later matches.
    """
    matches = list(rule.finditer(text))
    if not matches:
        return text, 0

    parts: list[str] = []
    prev_end = len(text)
    for match in reversed(matches):
        original = match.group(0).strip()
        label = store.get_label(category, original)
        replacement = preserve_whitespace_replace(match, label)
        parts.append(text[match.end() : prev_end])
        parts.append(replacement)
        prev_end = match.start()
    parts.append(text[:prev_end])

    # Because we iterated right-to-left, parts are in reverse order.
    return "".join(reversed(parts)), len(matches)


def _mask_with_rules(text: str, store: PlaceholderStore, stats: dict) -> str:
    masked = text
    for category, rule in get_rules():
        masked, count = _apply_rule_matches(masked, category, rule, store)
        if count:
            # Count each distinct placeholder occurrence.
            for match in rule.finditer(text):
                original = match.group(0).strip()
                label = store.get_label(category, original)
                stats[label] = stats.get(label, 0) + 1
            text = masked
    return masked


def _final_verification(
    text: str,
    party_names: list[str],
    store: PlaceholderStore,
    stats: dict,
) -> str:
    """Run a second masking pass; raise AnonymizationLeakError if leaks remain."""
    leaks_found = 0
    masked = text

    # Re-check regex rules first so emails/phones are not broken by party-name
    # replacements.
    for category, rule in get_rules():
        masked, count = _apply_rule_matches(masked, category, rule, store)
        leaks_found += count

    # Re-check party names.
    prev = masked
    masked = _mask_party_names(masked, party_names, store)
    if masked != prev:
        leaks_found += 1

    if leaks_found:
        stats["second_pass_fixes"] = stats.get("second_pass_fixes", 0) + leaks_found

    # After second pass, if anything remains, raise.
    remaining = _find_any_match(masked, party_names)
    if remaining:
        raise AnonymizationLeakError(
            f"document non anonymisable automatiquement, revue manuelle requise ({remaining})"
        )

    return masked


def _find_any_match(text: str, party_names: list[str]) -> Optional[str]:
    for category, rule in get_rules():
        match = rule.search(text)
        if match:
            return f"{category}: {match.group(0)!r}"
    for name in party_names:
        if name.strip():
            pattern = rf"\b{re.escape(name.strip())}\b"
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return f"party: {match.group(0)!r}"
            # Also check surname alone.
            tokens = name.strip().split()
            if len(tokens) > 1:
                surname = tokens[-1]
                if len(surname) >= 4:
                    pattern = rf"\b{re.escape(surname)}\b"
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return f"party surname: {match.group(0)!r}"
    return None


def mask_pii(text: str, party_names: Optional[list[str]] = None) -> tuple[str, dict, dict]:
    """Mask PII in text.

    Returns (masked_text, mapping, stats).
    """
    store = PlaceholderStore()
    stats: dict = {"second_pass_fixes": 0}

    masked = text
    if party_names:
        masked = _mask_party_names(masked, party_names, store)
    masked = _mask_people(masked, store, stats)
    masked = _mask_with_rules(masked, store, stats)
    masked = _final_verification(masked, party_names or [], store, stats)

    return masked, store.mapping, stats


def unmask_text(masked_text: str, mapping: dict) -> str:
    """Restore original values from a mapping."""
    restored = masked_text
    # Replace longest placeholders first to avoid partial collisions.
    for label, original in sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True):
        restored = restored.replace(label, original)
    return restored
