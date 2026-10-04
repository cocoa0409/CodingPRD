"""Shared helpers: logical clock, datetimes, validation, auth, records, pricing."""

import fnmatch
import zlib
from datetime import datetime, timezone

from flask import request

import db
from errors import (
    invalid_request, unauthenticated, forbidden, not_found,
)
from response import new_uuid, iso_now

ROLES = {"PlatformAdmin", "BillingAdmin", "IngestionAgent", "TeamLead", "FinanceReader"}
PLAN_TIERS = {"FREE", "PRO", "ENTERPRISE"}
METERS = {"INFRA_HOST", "CUSTOM_METRIC", "LOG_INGEST", "LOG_INDEX", "TRACE", "SYNTHETIC"}
MONITOR_KINDS = {"METRIC", "LOG", "APM", "SYNTHETIC"}
ENFORCEMENTS = {"WARN", "BLOCK"}

SOFT_CAP = 10000
BYTES_PER_GB = 1000000000
EVENTS_PER_MILLION = 1000000
BP_BASE = 10000


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.6)
# ---------------------------------------------------------------------------

def clock_utc():
    return db.logical_clock["current_utc"]


# ---------------------------------------------------------------------------
# Datetime handling
# ---------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 datetime to an aware datetime. Accepts trailing Z."""
    if not isinstance(value, str):
        return None
    try:
        s = value
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------

_MISSING = object()


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        if request.data:
            raise invalid_request("Request body is not valid JSON")
        body = {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def req_field(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        raise invalid_request(f"Missing required field: {name}")
    return value


def req_str(body, name):
    value = req_field(body, name)
    if not isinstance(value, str):
        raise invalid_request(f"Field {name} must be a string")
    return value


def opt_str(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return None
    if not isinstance(value, str):
        raise invalid_request(f"Field {name} must be a string")
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(body, name):
    value = req_field(body, name)
    if not _is_int(value):
        raise invalid_request(f"Field {name} must be an integer")
    return value


def opt_int(body, name, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not _is_int(value):
        raise invalid_request(f"Field {name} must be an integer")
    return value


def opt_bool(body, name, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        raise invalid_request(f"Field {name} must be a boolean")
    return value


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        raise invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return value


def req_dt(body, name):
    value = req_str(body, name)
    dt = parse_dt(value)
    if dt is None:
        raise invalid_request(f"Field {name} must be an ISO 8601 datetime")
    return dt


def req_list_of_str(body, name):
    value = req_field(body, name)
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise invalid_request(f"Field {name} must be an array of strings")
    return value


def parse_pagination():
    """limit/offset query params: default 10/0, min 1, max 100 (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def parse_bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    raise invalid_request(f"Query parameter {name} must be true or false")


# ---------------------------------------------------------------------------
# Auth (PRD §2.1; validation priorities 1-2)
# ---------------------------------------------------------------------------

def check_auth():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not user_id:
        raise unauthenticated()
    return role


def require_roles(role, allowed):
    if role not in allowed:
        raise forbidden()


# ---------------------------------------------------------------------------
# Record construction / mutation (PRD §2.4)
# ---------------------------------------------------------------------------

def new_record(fields, common=True, immutable=False):
    now = iso_now()
    rec = {"id": new_uuid()}
    if common or immutable:
        rec["created_at"] = now
    if common:
        rec["updated_at"] = now
    rec.update(fields)
    if common:
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version on any mutation."""
    if "version" in rec:
        rec["version"] += 1
    if "updated_at" in rec:
        rec["updated_at"] = iso_now()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def lookup(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise not_found()
    return rec


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def get_plan_for_account(account):
    for cfg in db.plan_tier_configs.values():
        if cfg["plan_tier"] == account["plan_tier"]:
            return cfg
    return None


def get_or_create_accumulator(period, meter):
    for acc in db.meter_accumulators.values():
        if acc["billing_period_id"] == period["id"] and acc["meter"] == meter:
            return acc
    acc = new_record({
        "billing_period_id": period["id"],
        "meter": meter,
        "quantity": 0,
        "committed_consumed_quantity": 0,
        "on_demand_quantity": 0,
    })
    db.meter_accumulators[acc["id"]] = acc
    return acc


def find_active_commitment(account_id, meter):
    """ACTIVE commitment for account+meter whose window covers the logical clock."""
    now = parse_dt(clock_utc())
    candidates = []
    for c in db.commitments.values():
        if c["billing_account_id"] != account_id or c["meter"] != meter:
            continue
        if c["status"] != "ACTIVE":
            continue
        ws = parse_dt(c["window_start_utc"])
        we = parse_dt(c["window_end_utc"])
        if ws <= now <= we:
            candidates.append(c)
    candidates.sort(key=lambda c: c["created_at"])
    return candidates[0] if candidates else None


def _debit_commitment(commitment, portion):
    commitment["consumed_quantity"] += portion
    if commitment["consumed_quantity"] == commitment["committed_quantity"]:
        commitment["status"] = "EXHAUSTED"
    touch(commitment)


def bump_meter(period, account, meter, delta):
    """Add delta units to the period's meter accumulator, drawing down any
    ACTIVE commitment first (PRD §3.4 charge-split-before-rate)."""
    if delta == 0:
        return get_or_create_accumulator(period, meter)
    acc = get_or_create_accumulator(period, meter)
    acc["quantity"] += delta
    if delta > 0:
        commitment = find_active_commitment(account["id"], meter)
        if commitment is not None:
            headroom = max(commitment["committed_quantity"] - commitment["consumed_quantity"], 0)
            portion = min(delta, headroom)
            acc["committed_consumed_quantity"] += portion
            _debit_commitment(commitment, portion)
    acc["on_demand_quantity"] = acc["quantity"] - acc["committed_consumed_quantity"]
    touch(acc)
    return acc


def plan_overage_rate_cents(plan, meter):
    """Fallback on-demand rate for a meter when no commitment covers it."""
    if plan is None:
        return 0
    return {
        "INFRA_HOST": plan["host_overage_rate_cents"],
        "CUSTOM_METRIC": plan["custom_metric_rate_cents_per_unit"],
        "LOG_INGEST": plan["log_ingest_rate_cents_per_gb"],
        "LOG_INDEX": plan["log_index_rate_cents_per_million"],
        "TRACE": 0,
        "SYNTHETIC": 0,
    }.get(meter, 0)


def rate_usage_amount_cents(account, meter, quantity):
    """Rate one usage quantity into integer cents (PRD §3.4 mode (a)).

    Split before rate: committed portion (ACTIVE commitment headroom) at the
    commitment's rate, overage portion at the commitment's overage rate, or —
    with no ACTIVE commitment — the whole quantity at the plan's on-demand rate.
    """
    commitment = find_active_commitment(account["id"], meter)
    if commitment is not None:
        headroom = max(commitment["committed_quantity"] - commitment["consumed_quantity"], 0)
        committed_portion = min(quantity, headroom)
        overage_portion = max(quantity - committed_portion, 0)
        return (committed_portion * commitment["committed_unit_rate_cents"]
                + overage_portion * commitment["overage_unit_rate_cents"])
    plan = get_plan_for_account(account)
    return quantity * plan_overage_rate_cents(plan, meter)


def select_winning_filter(account_id, service_tag):
    """Exclusion filter selection (SCAFFOLD exclusion_filter_selection):
    enabled + glob match; winner = (priority ASC, created_at ASC); id is
    FORBIDDEN as tie-break."""
    candidates = []
    for f in db.exclusion_filters.values():
        if f["billing_account_id"] != account_id:
            continue
        if not f["enabled"]:
            continue
        if fnmatch.fnmatchcase(service_tag, f["service_tag_pattern"]):
            candidates.append(f)
    if not candidates:
        return None
    candidates.sort(key=lambda f: (f["priority"], f["created_at"]))
    return candidates[0]


def sample_admits(service_tag, sample_rate_pct):
    """Deterministic benchmark rule: admit when hash(service_tag) mod 100
    is strictly less than sample_rate_pct. CRC32 is stable across processes."""
    h = zlib.crc32(service_tag.encode("utf-8")) & 0xFFFFFFFF
    return (h % 100) < sample_rate_pct
