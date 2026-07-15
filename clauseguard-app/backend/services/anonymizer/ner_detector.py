"""Optional GLiNER-based named-entity detection.

Controlled by the environment variable ANONYMIZER_NER:
- "off" (default): NER is disabled.
- "on": lazy-load GLiNER and detect persons.

Any failure (download, import, OOM, runtime) is logged and the text is returned
unchanged so the pipeline never fails because of NER.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_ENV_FLAG = os.getenv("ANONYMIZER_NER", "off").lower()
_NER_ENABLED = _ENV_FLAG in ("1", "true", "on", "yes")

# Lazy singleton for the GLiNER model.
_model = None


def _load_model():
    """Lazy-load the GLiNER model."""
    global _model
    if _model is not None:
        return _model

    # Import here so the rest of the package works without gliner installed.
    from gliner import GLiNER

    logger.info("Loading GLiNER model (first run downloads ~500MB)...")
    _model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
    return _model


def _is_inside_placeholder(text: str, start: int, end: int) -> bool:
    """Return True if [start:end] overlaps an existing placeholder like [XXX_n]."""
    before = text[:start]
    after = text[end:]
    # A placeholder is open if there is an unmatched '[' before start without a ']'
    # and an unmatched ']' after end without a '['.
    open_before = before.count("[") - before.count("]")
    close_after = after.count("]") - after.count("[")
    return open_before > 0 and close_after > 0


def detect_people(text: str) -> list[tuple[str, float]]:
    """Detect person names in text using GLiNER.

    Returns a list of (entity_text, score) tuples.
    """
    if not _NER_ENABLED:
        return []

    try:
        model = _load_model()
        entities = model.predict_entities(text, labels=["person"], threshold=0.5)
        results = []
        for ent in entities:
            label = getattr(ent, "label", None) if not isinstance(ent, dict) else ent.get("label")
            if label != "person":
                continue
            score = float(
                getattr(ent, "score", 0.0) if not isinstance(ent, dict) else ent.get("score", 0.0)
            )
            if score < 0.5:
                continue
            start = int(
                getattr(ent, "start", 0) if not isinstance(ent, dict) else ent.get("start", 0)
            )
            end = int(
                getattr(ent, "end", 0) if not isinstance(ent, dict) else ent.get("end", 0)
            )
            if _is_inside_placeholder(text, start, end):
                continue
            entity_text = getattr(ent, "text", "") if not isinstance(ent, dict) else ent.get("text", "")
            results.append((entity_text, score))
        return results
    except Exception:
        logger.warning("NER detection failed; continuing without NER.", exc_info=True)
        return []
