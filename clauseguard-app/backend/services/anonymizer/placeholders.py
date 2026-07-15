"""Placeholder replacement engine.

Design goals:
- Preserve surrounding whitespace from the matched text.
- Same original value -> same placeholder everywhere.
- Expose a clean mapping {placeholder: original}.
"""

import re
from typing import Optional


class PlaceholderStore:
    """Generates and tracks placeholders for original values."""

    def __init__(self) -> None:
        self._mapping: dict[str, str] = {}
        self._value_to_label: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self._mapping)

    def get_label(self, category: str, original: str) -> str:
        """Return a stable placeholder for a category+original pair."""
        key = f"{category.lower()}:{original}"
        if key in self._value_to_label:
            return self._value_to_label[key]

        self._counters[category] = self._counters.get(category, 0) + 1
        label = f"[{category.upper()}_{self._counters[category]}]"
        self._value_to_label[key] = label
        self._mapping[label] = original
        return label

    def set_label(self, category: str, original: str, label: str) -> None:
        """Manually register a placeholder for a category+original pair."""
        key = f"{category.lower()}:{original}"
        self._value_to_label[key] = label
        self._mapping[label] = original

    def lookup(self, category: str, original: str) -> Optional[str]:
        """Return an existing placeholder for a category+original pair."""
        key = f"{category.lower()}:{original}"
        return self._value_to_label.get(key)


def preserve_whitespace_replace(match: re.Match, label: str) -> str:
    """Replace a regex match with a label while preserving leading/trailing whitespace."""
    text = match.group(0)
    leading = ""
    trailing = ""
    i = 0
    while i < len(text) and text[i].isspace():
        leading += text[i]
        i += 1
    j = len(text) - 1
    while j >= 0 and text[j].isspace():
        trailing = text[j] + trailing
        j -= 1
    return f"{leading}{label}{trailing}"


def replace_match(
    store: PlaceholderStore,
    category: str,
    match: re.Match,
    original_override: Optional[str] = None,
) -> str:
    original = original_override if original_override is not None else match.group(0)
    # Normalize the stored original value to the stripped form for stability.
    stripped = original.strip()
    label = store.get_label(category, stripped)
    return preserve_whitespace_replace(match, label)
