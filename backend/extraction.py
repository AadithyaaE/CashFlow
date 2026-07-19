"""Document ingestion pipeline for invoice uploads.

Single pipeline, three entry points:

    PDF (digital text)  --\
    PDF (scanned)  -> OCR ---> get_document_text() -> extract_invoice_fields()
    Image (jpg/png) -> OCR --/

Both OCR (for scanned PDFs and images) and the final structured-field
extraction go through Gemini: OCR uses Gemini's vision input to transcribe
raw text, and that text — regardless of where it came from — is fed into the
same Gemini text-extraction prompt. This keeps exactly one parsing pipeline
instead of a separate code path per input type.
"""

import base64
import json
import re
from datetime import datetime

import fitz
from langchain_core.messages import HumanMessage


# A digital PDF page with real invoice content typically yields well over a
# few hundred characters of selectable text. Anything under this is treated
# as a scanned/image-only page and routed through OCR instead.
MIN_DIGITAL_TEXT_CHARS = 40

MAX_OCR_PAGES = 3  # bound cost/latency for multi-page scans

SUPPORTED_IMAGE_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}

# Mirrors the conversion table the old regex parser used, kept as the single
# source of truth now that both live in one place.
EXCHANGE_RATES_TO_INR = {
    "INR": 1,
    "USD": 86,
    "EUR": 99,
    "GBP": 116,
}

REQUIRED_FIELDS = [
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "total_amount",
    "currency",
    "gst",
    "category",
    "payment_terms",
    "description",
]


class ExtractionError(Exception):
    """Raised when the document can't be turned into any usable text at all."""


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_pdf_text(filepath: str) -> str:
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    return text


def render_pdf_pages_to_png(filepath: str, max_pages: int = MAX_OCR_PAGES):
    doc = fitz.open(filepath)
    images = []
    # Higher-than-default zoom noticeably improves OCR accuracy on scans.
    matrix = fitz.Matrix(2, 2)
    for page in doc[:max_pages]:
        pix = page.get_pixmap(matrix=matrix)
        images.append(pix.tobytes("png"))
    return images


def ocr_image_with_gemini(llm, image_bytes: bytes, mime_type: str) -> str:
    if llm is None:
        raise ExtractionError("AI extraction is not configured on the server.")

    b64 = base64.b64encode(image_bytes).decode("utf-8")

    message = HumanMessage(content=[
        {
            "type": "text",
            "text": (
                "Transcribe every piece of visible text in this document image "
                "exactly as it appears — vendor details, line items, totals, "
                "dates, tax lines, terms, everything. Preserve line breaks. "
                "Return only the raw transcribed text, no commentary, no "
                "markdown formatting."
            ),
        },
        {
            "type": "image_url",
            "image_url": f"data:{mime_type};base64,{b64}",
        },
    ])

    response = llm.invoke([message])
    return (response.content or "").strip()


def get_document_text(llm, filepath: str, extension: str) -> str:
    """Single dispatch point: returns plain text regardless of source format."""

    extension = extension.lower().lstrip(".")

    if extension == "pdf":

        try:
            digital_text = extract_pdf_text(filepath)
        except Exception as exc:
            raise ExtractionError("Could not read this PDF file.") from exc

        if len(digital_text.strip()) >= MIN_DIGITAL_TEXT_CHARS:
            return digital_text

        # Little or no selectable text -> treat as a scanned PDF and OCR
        # each page image through the same Gemini vision call used for
        # uploaded images.
        try:
            page_images = render_pdf_pages_to_png(filepath)
        except Exception as exc:
            raise ExtractionError("Could not read this PDF file.") from exc

        if not page_images:
            raise ExtractionError("This PDF has no pages to read.")

        ocr_text = "\n\n".join(
            ocr_image_with_gemini(llm, img, "image/png") for img in page_images
        )
        return ocr_text

    if extension in SUPPORTED_IMAGE_MIME:
        with open(filepath, "rb") as f:
            image_bytes = f.read()
        return ocr_image_with_gemini(llm, image_bytes, SUPPORTED_IMAGE_MIME[extension])

    raise ExtractionError(f"Unsupported file type: .{extension}")


# ---------------------------------------------------------------------------
# Gemini structured field extraction
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are an invoice data extraction engine. Read the document text below and extract these fields:

- vendor_name: the company/person being paid (issuer of the invoice)
- invoice_number: the invoice/receipt/bill identifier printed on the document
- invoice_date: the date the invoice was issued
- due_date: the payment due date
- total_amount: the final total amount due, as a plain number with no currency symbol or thousands separators
- currency: the ISO-like currency code (INR, USD, EUR, GBP, etc.) based on the symbol or text used
- gst: any GST/VAT/sales tax amount or rate shown on the invoice (as printed, e.g. "18%" or "450.00")
- category: a short business expense category (e.g. Cloud Services, Rent, Utilities, Software, Payroll, Consulting, General)
- payment_terms: payment terms text if present (e.g. "Net 30", "Due on receipt")
- description: a one-sentence summary of what the invoice is for

Rules:
- Dates must be formatted as DD-MM-YYYY. If a date is genuinely not present, use null.
- If a field is not present anywhere in the text, use null (not an empty string, not a guess).
- total_amount must be a JSON number, not a string. If it cannot be determined, use null.
- Do not invent data that is not in the text.
- Return ONLY a single valid JSON object with exactly these keys: vendor_name, invoice_number, invoice_date, due_date, total_amount, currency, gst, category, payment_terms, description. No markdown code fences, no explanation, no extra text.

Document text:
---
{text}
---
"""


def _strip_json_fence(raw: str) -> str:
    raw = raw.strip()
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if match:
        return match.group(1)
    # Fall back to the first {...} block in case Gemini added stray prose.
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    return match.group(0) if match else raw


def _call_gemini_for_fields(llm, text: str) -> dict:
    if llm is None:
        raise ExtractionError("AI extraction is not configured on the server.")

    # Gemini's context window comfortably fits far more than this, but an
    # invoice's meaningful content is always near the top — trimming keeps
    # OCR noise from very long scans from drowning out the real fields.
    trimmed = text[:12000]

    prompt = EXTRACTION_PROMPT.format(text=trimmed)
    response = llm.invoke(prompt)
    raw = response.content or ""

    try:
        return json.loads(_strip_json_fence(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ExtractionError("Gemini did not return valid JSON for this document.") from exc


def normalize_date(value):
    """Best-effort normalization to the app's DD-MM-YYYY convention."""

    if not value or not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    formats = ["%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue

    return None


def _parse_amount(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.]", "", value)
        try:
            return float(cleaned) if cleaned else 0.0
        except ValueError:
            return 0.0
    return 0.0


def extract_invoice_fields(llm, text: str) -> dict:
    """Runs the Gemini extraction prompt and validates/normalizes the result.

    Returns a dict with the extracted fields (amount already converted to
    INR, matching how the rest of the app stores amounts) plus a
    `needs_review` flag the caller surfaces to the user when the fields
    critical to the app (vendor, amount, due date) couldn't be determined
    confidently.
    """

    if not text or not text.strip():
        raise ExtractionError("Could not extract any text from this document.")

    raw_fields = _call_gemini_for_fields(llm, text)

    vendor = (raw_fields.get("vendor_name") or "").strip() or "Unknown Vendor"

    amount = _parse_amount(raw_fields.get("total_amount"))

    currency = (raw_fields.get("currency") or "INR").strip().upper() or "INR"
    if currency not in EXCHANGE_RATES_TO_INR:
        currency = "INR"

    amount_inr = round(amount * EXCHANGE_RATES_TO_INR.get(currency, 1), 2)

    due_date = normalize_date(raw_fields.get("due_date")) or "Unknown"
    invoice_date = normalize_date(raw_fields.get("invoice_date"))

    category = (raw_fields.get("category") or "").strip() or "General"

    def clean_str(key):
        value = raw_fields.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    needs_review = (
        vendor == "Unknown Vendor"
        or amount_inr <= 0
        or due_date == "Unknown"
    )

    return {
        "vendor": vendor,
        "amount": amount_inr,
        "currency": currency,
        "due_date": due_date,
        "invoice_date": invoice_date,
        "invoice_number": clean_str("invoice_number"),
        "gst": clean_str("gst"),
        "category": category,
        "payment_terms": clean_str("payment_terms"),
        "description": clean_str("description"),
        "needs_review": needs_review,
    }
