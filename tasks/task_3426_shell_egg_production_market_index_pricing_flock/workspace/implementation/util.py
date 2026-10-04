"""Time handling (logical clock stamping / ISO-8601 parsing), exact rounding
helpers (Fraction-based, half-up), and the fixed response envelope."""

import re
import uuid
from datetime import datetime, timezone
from fractions import Fraction

from flask import jsonify, request

from errors import ApiError, ERR_INVALID_REQUEST

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Enum vocabularies (from SCAFFOLD.yaml entity table)
# ---------------------------------------------------------------------------
REGIONS = ["MIDWEST", "SOUTHEAST", "SOUTHWEST", "WEST", "NORTHEAST"]
SIZE_CLASSES = ["JUMBO", "EXTRA_LARGE", "LARGE", "MEDIUM", "SMALL", "PEEWEE"]
PROGRAMS = ["CONVENTIONAL", "CAGE_FREE", "ORGANIC"]
HOUSING_STYLES = ["CONVENTIONAL", "CAGE_FREE", "ORGANIC"]
OWNERSHIPS = ["OWNED", "CONTRACT"]
PATHOGENS = ["HPAI", "LPAI", "NEWCASTLE", "SALMONELLA"]
DISPOSAL_METHODS = ["COMPOSTING", "BURIAL", "INCINERATION", "LANDFILL"]
SEGMENTS = ["RETAIL", "FOODSERVICE", "PROCESSOR"]
COMMODITIES = ["CORN", "SOYBEAN_MEAL"]
SOURCES = ["URNER_BARRY", "USDA_AMS"]
CERT_PROGRAMS = ["CAGE_FREE", "ORGANIC"]
CERT_RESULTS = ["PASSED", "FAILED"]
TARGET_STYLES = ["CAGE_FREE", "ORGANIC"]

ROLES = [
    "PlatformAdmin", "ProductionPlanner", "ComplexManager", "PlantManager",
    "ProcurementLead", "HealthOfficial", "QualityAuditor", "SalesManager",
    "Customer",
]


# ---------------------------------------------------------------------------
# Ids and timestamps
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


def _fmt(dt):
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    """Real wall-clock now, ISO-8601 UTC with exactly three fractional digits.

    Used only for the envelope's api_request_timestamp (request metadata);
    every business timestamp reads the logical clock instead.
    """
    return _fmt(datetime.now(UTC))


def canonical_iso(dt):
    """Canonical server timestamp: ISO-8601 UTC, three fractional digits, Z."""
    return _fmt(dt)


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$"
)


def parse_datetime(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not _ISO_RE.match(s):
        raise ValueError("bad iso8601: %r" % value)
    body = s
    if body.endswith("Z"):
        body = body[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(body)
    except ValueError:
        raise ValueError("bad iso8601: %r" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Exact arithmetic helpers
# ---------------------------------------------------------------------------
def floor_frac(f):
    """Mathematical floor of a Fraction (works for negatives too)."""
    return f.numerator // f.denominator


def ceil_frac(f):
    return -((-f.numerator) // f.denominator)


def round_half_up(f):
    """Round a Fraction to the nearest integer, halves rounded up."""
    return floor_frac(f + Fraction(1, 2))


def round2_half_up(f):
    """Round a Fraction half-up to two decimal places; returns a float."""
    return round_half_up(f * 100) / 100.0


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD response_envelope / PRD §2.2)
# ---------------------------------------------------------------------------
def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": wall_now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": wall_now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": wall_now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 (min 1, max 100), offset default 0
# ---------------------------------------------------------------------------
def pagination_args():
    def _parse(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "%s must be an integer" % name
            )

    limit = _parse("limit", 10)
    offset = _parse("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
