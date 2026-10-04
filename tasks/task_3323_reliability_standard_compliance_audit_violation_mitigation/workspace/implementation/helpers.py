"""Shared helpers: constants, datetime parsing, serialization, pagination."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from db import db
from errors import err_invalid_request
from response import fmt_ts

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FUNCTION_CODES = {"GO", "GOP", "TO", "TOP", "TP", "BA", "RC", "IA", "PC", "DP", "LSE", "RP"}

# STANDARD_LIBRARY: mapping of function code -> list of {standard_id, standard_code}.
# Deterministic; each function maps to two standards so that unions across
# functions are meaningful and shared standards exist across functions.
STANDARD_LIBRARY = {
    "GO":  [{"standard_id": "STD-GO-001", "standard_code": "BAL-001"}, {"standard_id": "STD-GO-002", "standard_code": "VAR-002"}],
    "GOP": [{"standard_id": "STD-GOP-001", "standard_code": "IRO-010"}, {"standard_id": "STD-GOP-002", "standard_code": "TOP-002"}],
    "TO":  [{"standard_id": "STD-TO-001", "standard_code": "FAC-003"}, {"standard_id": "STD-TO-002", "standard_code": "PRC-005"}],
    "TOP": [{"standard_id": "STD-TOP-001", "standard_code": "TOP-001"}, {"standard_id": "STD-TOP-002", "standard_code": "TOP-002"}],
    "TP":  [{"standard_id": "STD-TP-001", "standard_code": "TPL-001"}, {"standard_id": "STD-TP-002", "standard_code": "FAC-003"}],
    "BA":  [{"standard_id": "STD-BA-001", "standard_code": "BAL-001"}, {"standard_id": "STD-BA-002", "standard_code": "BAL-003"}],
    "RC":  [{"standard_id": "STD-RC-001", "standard_code": "IRO-010"}, {"standard_id": "STD-RC-002", "standard_code": "TOP-001"}],
    "IA":  [{"standard_id": "STD-IA-001", "standard_code": "INT-004"}, {"standard_id": "STD-IA-002", "standard_code": "BAL-003"}],
    "PC":  [{"standard_id": "STD-PC-001", "standard_code": "MOD-025"}, {"standard_id": "STD-PC-002", "standard_code": "MOD-026"}],
    "DP":  [{"standard_id": "STD-DP-001", "standard_code": "PRC-005"}, {"standard_id": "STD-DP-002", "standard_code": "PRC-001"}],
    "LSE": [{"standard_id": "STD-LSE-001", "standard_code": "BAL-003"}, {"standard_id": "STD-LSE-002", "standard_code": "INT-004"}],
    "RP":  [{"standard_id": "STD-RP-001", "standard_code": "PER-003"}, {"standard_id": "STD-RP-002", "standard_code": "PER-005"}],
}

# Appeal windows (days). PRD references APPEAL_WINDOW_DAYS and
# FEDERAL_REVIEW_WINDOW_DAYS without literal values; NERC-aligned defaults.
APPEAL_WINDOW_DAYS = 30
FEDERAL_REVIEW_WINDOW_DAYS = 30

# Penalty pricing constants (scaffold §1.3)
BASE_BY_VRF = {"MINIMAL": 1000, "MODERATE": 5000, "SERIOUS": 25000}
SEVERE_MULTIPLIER = 2.0
HIGH_MULTIPLIER = 1.5
SELF_REPORT_DISCOUNT = 0.6
SELF_LOG_DISCOUNT = 0.4
GAP_AGGRAVATION = 1.25
RECIDIVISM_RATE = 0.1
RECIDIVISM_CAP = 5
COVERAGE_GAP_THRESHOLD = 0.8

OPEN_VIOLATION_STATUSES = {"OPEN", "MITIGATION_SUBMITTED", "MITIGATION_IN_PROGRESS", "APPEALED"}


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

def parse_dt(value, field="timestamp"):
    """Parse an ISO 8601 datetime string to an aware UTC datetime."""
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err_invalid_request(f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def touch(row):
    """Refresh updated_at and bump version on a mutation."""
    row["updated_at"] = clock_now()
    row["version"] = row.get("version", 1) + 1


def new_common():
    now = clock_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination(args):
    """Parse limit/offset per PRD §2.3. Defaults: limit=10, offset=0; 1<=limit<=100."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def sort_and_page(rows, limit, offset):
    rows = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    total = len(rows)
    return rows[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Serialization (datetimes -> ISO strings; Decimals -> numbers)
# ---------------------------------------------------------------------------

def serialize(row):
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = fmt_ts(v)
        elif isinstance(v, dict):
            out[k] = serialize(v)
        elif isinstance(v, list):
            out[k] = [serialize(x) if isinstance(x, dict) else (fmt_ts(x) if isinstance(x, datetime) else x) for x in v]
        else:
            out[k] = v
    return out


def entity_applicable_standards(functions):
    """Union of STANDARD_LIBRARY entries for the given function codes.

    Deduplicated by standard_id, preserving first-seen order following the
    registration_functions input order.
    """
    seen = {}
    for code in functions:
        for entry in STANDARD_LIBRARY.get(code, []):
            if entry["standard_id"] not in seen:
                seen[entry["standard_id"]] = dict(entry)
    return list(seen.values())


def entity_has_standard(entity, standard_id):
    return any(s["standard_id"] == standard_id for s in entity["applicable_standards"])
