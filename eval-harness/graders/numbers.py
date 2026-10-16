"""Number parsing and tolerant comparison shared by the graders.

Reports print numbers as "16,431,923원", "₩2,958,765", "19,655.41", "87.8%",
"1.2만" or "3.5M", while metadata stores raw floats. These helpers turn report
text into floats and decide whether a printed number is the same quantity as a
stored value, allowing for display rounding.
"""
import math
import re

# A number as printed in a report: optional sign, digits with thousands
# separators, optional decimals, optional Korean/English magnitude suffix.
NUMBER_RE = re.compile(
    r"(?<![\w.])([-+−]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(만|억|천|[KMB](?![a-zA-Z]))?"
)

_SUFFIX = {"천": 1e3, "만": 1e4, "억": 1e8, "K": 1e3, "M": 1e6, "B": 1e9}


def parse_numbers(text):
    """Return [(value, start, end, decimals)] for every number in text."""
    found = []
    for m in NUMBER_RE.finditer(text):
        sign, whole, frac, suffix = m.groups()
        value = float(whole.replace(",", "") + (frac or ""))
        if suffix:
            value *= _SUFFIX[suffix]
        if sign in ("-", "−"):
            value = -value
        decimals = len(frac) - 1 if frac else 0
        found.append((value, m.start(), m.end(), decimals if not suffix else None))
    return found


def matches(printed, decimals, stored, rel_tol=0.005):
    """Whether a printed number plausibly displays the stored value.

    Accepts exact display rounding at the printed precision (19,655 for
    19655.41), a small relative tolerance for scaled units (1.2만 for 12,345),
    and a stored ratio between 0 and 1 printed as a percentage (0.878 shown as 87.8).
    """
    if stored is None or printed is None:
        return False
    try:
        stored = float(stored)
    except (TypeError, ValueError):
        return False
    if math.isnan(stored):
        return False
    # A ratio may be printed as a percentage (0.878 → 87.8); other values may not.
    for candidate in (stored, stored * 100) if 0 < abs(stored) <= 1 else (stored,):
        if decimals is not None and round(candidate, decimals) == round(printed, decimals):
            return True
        if decimals is not None and abs(candidate - printed) <= 0.5 * 10 ** (-decimals) + 1e-9:
            return True
        if candidate == 0:
            if printed == 0:
                return True
            continue
        if abs(candidate - printed) / abs(candidate) <= rel_tol:
            return True
    return False

