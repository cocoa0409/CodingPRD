"""Shared primitives: timestamps, the logical clock format, normalization, decimals."""
import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import fail

# --- datetime -------------------------------------------------------------
# PRD 2.4: created_at / updated_at / envelope timestamps carry three fractional
# digits.  Every OTHER datetime, on input and on output, is second precision
# with a trailing Z and no fractional digits are emitted or accepted.
SECOND_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
LOOSE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def fmt_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_sec(dt):
    """ISO 8601 UTC with second precision and a trailing Z."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_second_instant(raw, error_id="ERR_INVALID_REQUEST"):
    if not isinstance(raw, str) or not SECOND_RE.match(raw):
        fail(error_id, "Expected an ISO 8601 UTC instant with second precision and a trailing Z.")
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        fail(error_id, "Invalid datetime value.")


def parse_loose_instant(raw, error_id="ERR_INVALID_REQUEST"):
    if not isinstance(raw, str) or not LOOSE_RE.match(raw):
        fail(error_id, "Expected an ISO 8601 UTC instant with a trailing Z.")
    head = raw[:19]
    return datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def utcnow():
    return datetime.now(timezone.utc)


# --- decimals -------------------------------------------------------------
D0 = Decimal("0")
Q1 = Decimal("0.1")
Q2 = Decimal("0.01")
Q3 = Decimal("0.001")


def dec(value):
    return Decimal(str(value))


def r1(value):
    return dec(value).quantize(Q1, rounding=ROUND_HALF_UP)


def r2(value):
    return dec(value).quantize(Q2, rounding=ROUND_HALF_UP)


def r3(value):
    return dec(value).quantize(Q3, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal for JSON output."""
    if value is None:
        return None
    return float(value)


def ceil_dec(value):
    return int(math.ceil(float(dec(value))))


# --- text normalization (PRD 2.8) ----------------------------------------
def normalize(text):
    """Trim, collapse internal whitespace runs to one space, uppercase."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text).strip()).upper()


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fmt1(value):
    """Render a number at exactly one decimal place."""
    return str(r1(value))
