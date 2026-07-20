"""Shared LLM-response parsing helpers.

LLM responses sometimes wrap the JSON payload in markdown fences and/or a
conversational preamble/postamble ("Souhaitez-vous que je..."). These two
helpers are the hardening used everywhere a flow response is parsed as JSON:
main.py (findings, report) and services/quality_loop.py (critic, refiner).
"""


def strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def extract_json_object(text: str) -> str:
    """Slice from the first '{' to the last '}'.

    Raises ValueError (a parse-failure, not a crash) if no JSON object
    delimiters are found.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in response")
    return text[start : end + 1]


def extract_json(text: str) -> str:
    """Convenience: strip fences then extract the JSON object substring."""
    return extract_json_object(strip_markdown_fences(text))
