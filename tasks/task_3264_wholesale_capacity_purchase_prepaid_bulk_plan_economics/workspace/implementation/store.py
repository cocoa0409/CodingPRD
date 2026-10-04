"""In-memory data store, logical clock, id minting and response envelope.

Nothing is seeded: every table starts empty on each fresh process, and every
entity in a test is built through the declared API surface.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError

# --- Tables (all empty at boot) ---------------------------------------------
AGREEMENTS = {}
PLANS = {}
SUBSCRIBERS = {}
TERMS = {}
ACTIVATIONS = {}
PARTNERS = {}
INVENTORY = {}
CYCLES = {}
CASES = {}
ADDONS = {}

DB = {
    "agreements": AGREEMENTS,
    "plans": PLANS,
    "subscribers": SUBSCRIBERS,
    "terms": TERMS,
    "activations": ACTIVATIONS,
    "partners": PARTNERS,
    "inventory": INVENTORY,
    "cycles": CYCLES,
    "cases": CASES,
    "addons": ADDONS,
}

# Logical clock. PRD 2.8: reads exactly 2026-09-01T00:00:00Z at startup and
# never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}

EPS = Decimal("0.001")


def now():
    """The current logical clock instant (aware UTC)."""
    return CLOCK["now"]


def now_iso():
    return iso(CLOCK["now"])


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}".format(dt.microsecond // 1000) + "Z"


def parse_ts(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "current_utc is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Calendar-month arithmetic, clamping the day to the target month."""
    total = dt.month - 1 + int(months)
    year = dt.year + total // 12
    month = total % 12 + 1
    days_in_month = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return dt.replace(year=year, month=month, day=min(dt.day, days_in_month))


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def add_seconds(dt, seconds):
    return dt + timedelta(seconds=int(seconds))


def add_hours(dt, hours):
    return dt + timedelta(hours=int(hours))


def new_id():
    return str(uuid.uuid4())


def stamp(record):
    """Set the system-managed identity block on a brand-new row."""
    at = now_iso()
    record["id"] = new_id()
    record["created_at"] = at
    record["updated_at"] = at
    record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on every modification."""
    record["updated_at"] = now_iso()
    record["version"] = int(record.get("version", 1)) + 1
    return record


def bump(record):
    """Version-only bump used where the scaffold pins a version increment."""
    return touch(record)


def round_half_up(value):
    """Round half up on a single division step (PRD 2.6)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_dec(value):
    from decimal import ROUND_CEILING
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def floor_dec(value):
    from decimal import ROUND_FLOOR
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


# --- Serialisation ----------------------------------------------------------
FIELD_ORDER = {
    "CapacityAgreement": [
        "id", "created_at", "updated_at", "version", "host_network_name", "state_code",
        "data_rate_microcents_per_mb", "voice_rate_microcents_per_min", "sms_rate_microcents_per_msg",
        "committed_data_mb", "committed_voice_minutes", "committed_sms_messages",
        "agreement_status", "congestion_active", "congestion_index", "allocated_data_mb",
        "remaining_data_mb", "resolved_purchase_cost_microcents",
    ],
    "Plan": [
        "id", "created_at", "updated_at", "version", "agreement_id", "plan_code", "term_months",
        "intro_price_cents", "renewal_price_cents", "data_allotment_mb", "voice_allotment_min",
        "sms_allotment_msg", "deprioritization_threshold_mb", "plan_status",
    ],
    "Subscriber": [
        "id", "created_at", "updated_at", "version", "msisdn", "full_name", "state_code",
        "subscriber_status", "allocation_status", "cycle_index", "cycles_rolled",
        "data_used_mb_cycle", "deprioritized_this_cycle", "cycle_deprioritization_days",
        "support_seconds_used", "support_seconds_budget", "self_service_deflection_count",
    ],
    "PrepaidTerm": [
        "id", "created_at", "updated_at", "version", "subscriber_id", "plan_id", "term_status",
        "term_price_cents", "starts_at", "expires_at", "deferred_revenue_cents",
        "earned_revenue_cents", "breakage_days", "breakage_cents_recognized", "void_reason",
    ],
    "Activation": [
        "id", "created_at", "updated_at", "version", "subscriber_id", "prepaid_term_id",
        "retail_partner_id", "activation_channel", "activation_status", "port_status",
        "porting_msisdn", "losing_carrier", "account_number_last4", "rejection_code",
        "held_data_mb", "provisioned_msisdn", "accepted_msisdn",
    ],
    "RetailPartner": [
        "id", "created_at", "updated_at", "version", "partner_name", "partner_status",
        "partner_state_codes", "shipment_sla_days",
    ],
    "SimInventory": [
        "id", "created_at", "updated_at", "version", "retail_partner_id",
        "reserved_for_activation_id", "sim_media_type", "state_code", "unit_count",
        "inventory_status", "reserved_count", "shipment_channel", "units_shipped",
        "shipment_sla_days",
    ],
    "CycleRecord": [
        "id", "created_at", "prepaid_term_id", "cycle_index", "cycle_status", "opened_at",
        "closed_at", "cycle_data_used_mb", "cycle_deprioritization_days", "earned_cents",
    ],
    "SupportCase": [
        "id", "created_at", "updated_at", "version", "subscriber_id", "topic_code",
        "case_status", "handling_seconds", "sla_due_at", "escalation_reason",
    ],
    "AddOn": [
        "id", "created_at", "updated_at", "version", "subscriber_id", "addon_type",
        "addon_status", "addon_price_cents", "per_day_allotment_mb", "addon_days", "start_at",
        "end_at", "deprovisioned_msisdn",
    ],
}

# CycleRecord is the immutable exception: no updated_at, no version (PRD 2.5).
NO_IDENTITY = {"CycleRecord"}


def serialize(kind, record):
    out = {}
    for key in FIELD_ORDER[kind]:
        out[key] = record.get(key)
    return out


def serialize_many(kind, records):
    return [serialize(kind, r) for r in records]


def envelope(data, response_type="object", pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20].upper(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return {"meta": meta, "response_type": response_type, "data": data}, 200 if response_type != "error" else None


def paginate(records, limit, offset):
    """PRD 2.3 pagination: limit default 10, min 1, max 100; offset default 0."""
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(records)
    window = records[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }


def by_created(records):
    """Default list ordering: ascending creation timestamp (PRD 2.3)."""
    return sorted(records, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))