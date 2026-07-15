import io
import re
import tempfile
from pathlib import Path
from typing import Tuple

from docx import Document
from fastapi import HTTPException, UploadFile, status

from services.anonymizer.pdf_reader import extract_text as extract_pdf_text

MAX_FILE_SIZE = 2 * 1024 * 1024
CONTRACT_KEYWORDS = [
    "contrat",
    "article",
    "partie",
    "parties",
    "accord",
    "convention",
    "conditions",
    "prestation",
    "client",
    "fournisseur",
    "clause",
]


async def extract_text(file: UploadFile) -> Tuple[str, int]:
    content_type = (file.content_type or "").lower()
    filename = (file.filename or "").lower()

    try:
        raw = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to read uploaded file",
        ) from exc

    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 2 MB limit",
        )

    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )

    if content_type == "text/plain" or filename.endswith(".txt"):
        text = _decode_text(raw)
    elif content_type == "application/pdf" or filename.endswith(".pdf"):
        text = _extract_pdf(raw)
    elif (
        content_type
        in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        }
        or filename.endswith(".docx")
    ):
        text = _extract_docx(raw)
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Use PDF, DOCX, or TXT.",
        )

    text = text.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No extractable text found in file",
        )

    if not _looks_like_contract(text):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded text does not appear to be a contract",
        )

    return text, len(text)


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_pdf(raw: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        return extract_pdf_text(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _extract_docx(raw: bytes) -> str:
    document = Document(io.BytesIO(raw))
    parts = [paragraph.text for paragraph in document.paragraphs]
    return "\n".join(parts)


def _looks_like_contract(text: str) -> bool:
    lowered = text.lower()
    matches = sum(1 for keyword in CONTRACT_KEYWORDS if keyword in lowered)
    return matches >= 2
