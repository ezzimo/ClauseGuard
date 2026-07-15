"""PDF text extraction using PyMuPDF."""

from pathlib import Path


def extract_text(path: str | Path) -> str:
    """Extract text from a PDF file path."""
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    parts = []
    for page in doc:
        text = page.get_text()
        if text:
            parts.append(text)
    doc.close()
    return "\n".join(parts)
