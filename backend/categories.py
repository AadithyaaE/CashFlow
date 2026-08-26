"""Category normalization — single source of truth.

Invoice categories are free text (see models.py — a plain String column, no
enum or lookup table). They come from three places: Gemini/OCR extraction,
the manual-expense form, and the invoice-edit form. Without normalization,
the same real-world expense type fragments across "Utilities" / "utilities"
/ "UTILITY" style variants, which then shows up as duplicate entries
anywhere categories are grouped (Analytics charts, the AI Copilot's
"biggest expense" answer).

normalize_category() is imported by extraction.py, main.py, and cfo.py so
there is exactly one normalization rule instead of three drifting copies.
"""

import re

# A small, explicit table of same-concept variants worth collapsing —
# deliberately NOT a general vendor-to-category taxonomy. "Utility" is just
# the singular of the extraction prompt's own canonical "Utilities" example;
# "Cloud" is shorthand for its "Cloud Services" example. Vendor names like
# "AWS" or "Amazon AWS" are intentionally left alone: a vendor name isn't
# the same thing as a category, and nothing in the existing architecture
# defines "Cloud Services" as a bucket other vendors should collapse into —
# merging those would be guessing at a taxonomy that doesn't exist yet.
CATEGORY_ALIASES = {
    "utility": "Utilities",
    "cloud": "Cloud Services",
}


def normalize_category(value: str | None) -> str:
    """Canonicalizes a free-text category string: trims/collapses
    whitespace, applies acronym-aware title casing (so "AWS" doesn't become
    "Aws"), then checks the small alias table above. Falls back to
    "General" for an empty value, matching the existing extraction/
    manual-expense default.
    """
    if not value or not isinstance(value, str):
        return "General"

    collapsed = re.sub(r"\s+", " ", value).strip()
    if not collapsed:
        return "General"

    alias = CATEGORY_ALIASES.get(collapsed.lower())
    if alias:
        return alias

    words = []
    for word in collapsed.split(" "):
        if word.isupper() and len(word) <= 5:
            words.append(word)  # preserve likely acronyms: AWS, GST, IT
        elif word.islower() or word.isupper():
            # Simple case (all-lower, or an all-upper word too long to be a
            # short acronym, e.g. "UTILITIES") — apply straight title casing.
            words.append(word[:1].upper() + word[1:].lower())
        else:
            # Already has meaningful internal capitalization (OpenAI,
            # iPhone, eBay) — leave it exactly as typed instead of
            # lowercasing everything after the first letter.
            words.append(word)
    return " ".join(words)
