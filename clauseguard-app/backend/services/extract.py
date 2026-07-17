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
    # Routing is by filename extension only. Browsers send unreliable MIME
    # types for .txt/.csv (often both "text/plain"), so content_type must
    # never decide which extractor runs.
    filename = (file.filename or "").lower()
    extension = Path(filename).suffix

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

    if extension == ".pdf":
        text = _extract_pdf(raw)
    elif extension == ".docx":
        text = _extract_docx(raw)
    elif extension == ".txt":
        text = _decode_text(raw)
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="format non supporte (PDF, DOCX, TXT)",
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
    # Order matters: latin-1 never raises (it maps every byte 0-255), so it
    # must be the last resort or cp1252-encoded text (curly quotes, em-dash,
    # oe-ligature, etc. in the 0x80-0x9F range) would silently decode wrong.
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


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
