"""pdftext.py — single source of truth for PDF -> text.

Both extract.py (the builder) and verifier.py (the grader) read the source
document through THIS module, so a span the extractor copies is byte-for-byte
findable by the verifier. The text layer comes from pdfplumber; image-only
pages fall back to OCR (pytesseract + pdf2image) so a degraded scan still
produces *something* to ground against — deliberately garbled, which is what
drives the confidence gate on the scanned demo doc.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import List

import pdfplumber

# How few characters a page may have before we treat it as image-only and OCR it.
_MIN_TEXT_LAYER_CHARS = 10


def normalize_ws(text: str) -> str:
    """Collapse every run of whitespace to a single space and strip.

    Grounding compares spans after this transform, so the extractor and the
    verifier agree regardless of how pdfplumber laid out newlines/columns.
    """
    return re.sub(r"\s+", " ", text or "").strip()


def _ocr_page(pdf_path: str, page_number: int) -> str:
    """OCR a single (1-indexed) page. Imported lazily so the born-digital path
    never requires tesseract/poppler to be installed."""
    from pdf2image import convert_from_path  # type: ignore
    import pytesseract  # type: ignore

    images = convert_from_path(
        pdf_path, first_page=page_number, last_page=page_number, dpi=200
    )
    if not images:
        return ""
    return pytesseract.image_to_string(images[0]) or ""


@lru_cache(maxsize=64)
def page_texts(pdf_path: str) -> tuple:
    """Return a tuple of per-page text, index 0 == page 1.

    A page whose text layer is essentially empty is OCR'd. Cached so repeated
    grounding checks within a run don't re-open or re-OCR the file.
    """
    pages: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            txt = page.extract_text() or ""
            if len(txt.strip()) < _MIN_TEXT_LAYER_CHARS:
                try:
                    txt = _ocr_page(pdf_path, i)
                except Exception as exc:  # pragma: no cover - surfaced to caller
                    txt = ""
                    print(
                        f"[pdftext] OCR unavailable for {pdf_path} p{i}: {exc}"
                    )
            pages.append(txt)
    return tuple(pages)


def full_text(pdf_path: str) -> str:
    """All pages joined, page-marked — the form fed to the model."""
    parts = []
    for i, txt in enumerate(page_texts(pdf_path), start=1):
        parts.append(f"=== PAGE {i} ===\n{txt}")
    return "\n\n".join(parts)


def span_in_page(span: str, pdf_path: str, page_number: int) -> bool:
    """True if `span` appears verbatim (whitespace-insensitive) on the page."""
    pages = page_texts(pdf_path)
    if page_number < 1 or page_number > len(pages):
        return False
    return normalize_ws(span) in normalize_ws(pages[page_number - 1])


def span_anywhere(span: str, pdf_path: str):
    """Return the 1-indexed page a span appears on, or None. Lets the verifier
    forgive an off-by-one page citation while still proving provenance."""
    for i, txt in enumerate(page_texts(pdf_path), start=1):
        if normalize_ws(span) in normalize_ws(txt):
            return i
    return None
