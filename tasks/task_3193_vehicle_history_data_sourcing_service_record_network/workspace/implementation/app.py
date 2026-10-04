"""Vehicle History Network API — PRD-benchmark implementation.

In-memory only (Python dicts keyed by id). No persistence, no seeding.
Logical clock defaults to 2026-09-01T00:00:00Z and never falls back to
wall-clock time.
"""

import os
import re
import threading
import uuid
from datetime import datetime, date

from flask import Flask, request, jsonify

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLES = [
    "NetworkAdmin",
    "SourceOperator",
    "ShopOperator",
    "VehicleOwner",
    "DealerAgent",
    "GuaranteeAdmin",
]

SOURCE_TYPES = ["MVA", "INSURER", "AUCTION", "SERVICE_SHOP", "INSPECTION_STATION"]
RECORD_TYPES = ["TITLE_BRAND", "ACCIDENT", "SERVICE", "INSPECTION"]
PRODUCTS = ["CONSUMER_SINGLE", "DEALER_SUBSCRIPTION"]
RESOLUTION_ACTIONS = ["WITHDRAW", "SUPERSEDE"]
SUB_TIERS = ["NONE", "STANDARD", "PRO"]

SEVERITY = {"NONE": 0, "CLEAN": 1, "LEMON": 2, "FLOOD": 3, "REBUILT": 4, "SALVAGE": 5}

DEFAULT_BRAND_LEXICON = {
    "CA": {
        "salvage certificate": "SALVAGE",
        "revived salvage": "REBUILT",
        "flood": "FLOOD",
        "lemon law buyback": "LEMON",
        "clean": "CLEAN",
    },
    "TX": {
        "salvage title": "SALVAGE",
        "rebuilt": "REBUILT",
        "water damage": "FLOOD",
        "manufacturer buyback": "LEMON",
        "clear": "CLEAN",
    },
}

CONF_HIGH = 85
CONF_MEDIUM = 70
CONF_LOW = 40

PRO_THRESHOLD = 50

CONSUMER_SINGLE_PRICE_CENTS = 3999
CONSUMER_RETURN_PRICE_CENTS = 1900
STANDARD_INCLUDED = 25
PRO_INCLUDED = 200
OVERAGE_BASE_CENTS = 500
OVERAGE_STEP_CENTS = 100
OVERAGE_STEP_EVERY = 10
OVERAGE_FLOOR_CENTS = 300

WINDOW_EPOCHS = 30
DEALER_SUSPEND_THRESHOLD_CENTS = 1000000

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

VIN_LENGTH = 17
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

STORE = {
    "networks": {},
    "sources": {},
    "shops": {},
    "vehicles": {},
    "records": {},
    "corrections": {},
    "consumers": {},
    "dealers": {},
    "listings": {},
    "claims": {},
    "reports": {},
}

CLOCK = {"iso": DEFAULT_CLOCK}

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Invalid state transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)


def err_stale(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return CLOCK["iso"]


def clock_date():
    return _parse_date_part(CLOCK["iso"])


def _parse_date_part(s):
    """Extract the date portion (YYYY-MM-DD) of an ISO8601 string."""
    if not isinstance(s, str) or len(s) < 10:
        return "1970-01-01"
    return s[:10]


def bump(obj):
    """Mutate: refresh updated_at and increment version."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1


def touch(obj):
    """Create: set created_at/updated_at and version=1."""
    ts = now_iso()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1


def req_body():
    data = request.get_json(silent=True)
    if data is None:
        raise err_invalid("Request body must be JSON")
    if not isinstance(data, dict):
        raise err_invalid("Request body must be a JSON object")
    return data


def require_string(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise err_invalid(f"Missing or invalid field: {field}")
    return v


def require_int(data, field):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid(f"Missing or invalid field: {field}")
    return v


def optional_int(data, field):
    v = data.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid(f"Invalid field: {field}")
    return v


def optional_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_invalid(f"Invalid field: {field}")
    return v


def require_enum(data, field, values):
    v = require_string(data, field)
    if v not in values:
        raise err_invalid(f"Invalid value for {field}")
    return v


def parse_event_date(data, field="event_date"):
    v = require_string(data, field)
    if not DATE_RE.match(v):
        raise err_invalid(f"Invalid date format: {field}")
    try:
        date(int(v[0:4]), int(v[5:7]), int(v[8:10]))
    except ValueError:
        raise err_invalid(f"Invalid date: {field}")
    return v


def date_diff_days(a, b):
    """a - b in days (YYYY-MM-DD strings)."""
    try:
        da = date(int(a[0:4]), int(a[5:7]), int(a[8:10]))
        db = date(int(b[0:4]), int(b[5:7]), int(b[8:10]))
    except (ValueError, TypeError):
        return 10 ** 9
    return (da - db).days


def hamming_one(a, b):
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    if len(a) != len(b):
        return False
    diff = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            diff += 1
            if diff > 1:
                return False
    return diff == 1


def validate_vin(v):
    if not isinstance(v, str) or len(v) != VIN_LENGTH:
        raise err_invalid("vin must be a 17-character string")
    return v


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def ok_object(obj, status=200):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:24],
            "api_request_timestamp": now_iso(),
        },
        "response_type": "object",
        "data": obj if obj is not None else {},
    }
    return jsonify(body), status


def ok_list(items, total, limit, offset):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:24],
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + limit) < total,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid("Invalid limit")
        if limit < 1 or limit > 100:
            raise err_invalid("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid("Invalid offset")
        if offset < 0:
            raise err_invalid("offset must be >= 0")
    return limit, offset


def list_response(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    total = len(items)
    page = items[offset: offset + limit]
    return ok_list(page, total, limit, offset)


def error_response(err):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:24],
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# App & middleware
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(e):
    return error_response(err_not_found())


@app.errorhandler(405)
def handle_405(e):
    return error_response(err_not_found())


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(e)))


@app.before_request
def auth_gate():
    # Auth (priority 1): headers present and role declared
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "Missing or invalid user context headers",
        )
    # Auth (priority 2): RBAC
    allowed = None
    for (m, pattern), roles in ROUTE_ROLES.items():
        if m == request.method and pattern.match(request.path):
            allowed = roles
            break
    if allowed is None:
        # Unknown route -> let Flask produce 404 with our envelope.
        return
    if "Any" not in allowed and role not in allowed:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "Role not permitted")


# ---------------------------------------------------------------------------
# Endpoint table & RBAC
# ---------------------------------------------------------------------------

ENDPOINTS = [
    ("POST", "/_clock/set_current_utc", ["NetworkAdmin"]),
    ("POST", "/networks", ["NetworkAdmin"]),
    ("GET", "/networks/{networkId}", ["Any"]),
    ("GET", "/networks/{networkId}/corrections", ["Any"]),
    ("GET", "/networks/{networkId}/consumers", ["Any"]),
    ("GET", "/networks/{networkId}/dealers", ["Any"]),
    ("GET", "/networks/{networkId}/records", ["Any"]),
    ("GET", "/networks/{networkId}/listings", ["Any"]),
    ("GET", "/networks/{networkId}/claims", ["Any"]),
    ("GET", "/networks/{networkId}/reports", ["Any"]),
    ("POST", "/advance_epoch", ["NetworkAdmin"]),
    ("POST", "/sources", ["NetworkAdmin"]),
    ("GET", "/sources/{sourceId}", ["Any"]),
    ("GET", "/sources", ["Any"]),
    ("POST", "/sources/{sourceId}/activate", ["NetworkAdmin"]),
    ("POST", "/sources/{sourceId}/reactivate", ["NetworkAdmin"]),
    ("POST", "/sources/{sourceId}/reset_streak", ["NetworkAdmin"]),
    ("POST", "/sources/{sourceId}/terminate", ["NetworkAdmin"]),
    ("GET", "/sources/{sourceId}/records", ["Any"]),
    ("POST", "/records", ["SourceOperator"]),
    ("GET", "/records", ["Any"]),
    ("GET", "/records/{recordId}", ["Any"]),
    ("GET", "/vehicles/{vehicleId}", ["Any"]),
    ("GET", "/vehicles", ["Any"]),
    ("GET", "/vehicles/{vehicleId}/records", ["Any"]),
    ("POST", "/shops", ["NetworkAdmin"]),
    ("GET", "/shops/{shopId}", ["Any"]),
    ("GET", "/shops", ["Any"]),
    ("POST", "/shops/{shopId}/approve", ["NetworkAdmin"]),
    ("POST", "/shops/{shopId}/suspend", ["NetworkAdmin"]),
    ("POST", "/shops/{shopId}/reactivate", ["NetworkAdmin"]),
    ("POST", "/shops/{shopId}/terminate", ["NetworkAdmin"]),
    ("POST", "/shops/{shopId}/service-records", ["ShopOperator"]),
    ("GET", "/shops/{shopId}/service-records", ["Any"]),
    ("POST", "/vehicles/{vehicleId}/corrections", ["VehicleOwner", "ShopOperator"]),
    ("GET", "/corrections/{correctionId}", ["Any"]),
    ("GET", "/vehicles/{vehicleId}/corrections/{correctionId}", ["Any"]),
    ("GET", "/vehicles/{vehicleId}/corrections", ["Any"]),
    ("GET", "/corrections", ["Any"]),
    ("POST", "/corrections/{correctionId}/route_to_source", ["NetworkAdmin"]),
    ("POST", "/corrections/{correctionId}/source_confirm", ["SourceOperator"]),
    ("POST", "/corrections/{correctionId}/source_deny", ["SourceOperator"]),
    ("POST", "/corrections/{correctionId}/apply", ["NetworkAdmin"]),
    ("POST", "/consumers", ["VehicleOwner"]),
    ("GET", "/consumers/{consumerId}", ["Any"]),
    ("GET", "/consumers", ["Any"]),
    ("POST", "/consumers/{consumerId}/credit", ["NetworkAdmin"]),
    ("POST", "/dealers", ["NetworkAdmin"]),
    ("GET", "/dealers/{dealerId}", ["Any"]),
    ("GET", "/dealers", ["Any"]),
    ("POST", "/dealers/{dealerId}/subscribe", ["DealerAgent"]),
    ("POST", "/dealers/{dealerId}/reinstate", ["NetworkAdmin"]),
    ("POST", "/dealers/{dealerId}/listings", ["DealerAgent"]),
    ("GET", "/dealers/{dealerId}/listings", ["Any"]),
    ("GET", "/listings/{listingId}", ["Any"]),
    ("GET", "/listings", ["Any"]),
    ("POST", "/dealers/{dealerId}/listings/{listingId}/publish", ["DealerAgent"]),
    ("POST", "/dealers/{dealerId}/listings/{listingId}/delist", ["DealerAgent"]),
    ("POST", "/dealers/{dealerId}/listings/{listingId}/enroll_guarantee", ["DealerAgent"]),
    ("POST", "/claims", ["GuaranteeAdmin", "DealerAgent"]),
    ("GET", "/claims/{claimId}", ["Any"]),
    ("GET", "/claims", ["Any"]),
    ("GET", "/dealers/{dealerId}/claims", ["Any"]),
    ("POST", "/claims/{claimId}/approve", ["GuaranteeAdmin"]),
    ("POST", "/claims/{claimId}/reject", ["GuaranteeAdmin"]),
    ("POST", "/reports", ["VehicleOwner", "DealerAgent"]),
    ("GET", "/reports/{reportId}", ["Any"]),
    ("GET", "/reports", ["Any"]),
    ("GET", "/vehicles/{vehicleId}/reports", ["Any"]),
    ("GET", "/consumers/{consumerId}/reports", ["Any"]),
    ("GET", "/dealers/{dealerId}/reports", ["Any"]),
]

ROUTE_ROLES = {}
for _method, _template, _roles in ENDPOINTS:
    _pattern = re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", _template) + "$")
    ROUTE_ROLES[(_method, _pattern)] = _roles

# ---------------------------------------------------------------------------
# Entity accessors
# ---------------------------------------------------------------------------


def get_network_or_404(nid):
    n = STORE["networks"].get(nid)
    if n is None:
        raise err_not_found("Network not found")
    return n


def resolve_network(data):
    """Resolve the owning network for a create request.

    PRD names the entity input fields but not a mandatory `network_id` body
    field; when the body omits it and exactly one network exists, that
    network is implied. An explicit `network_id` is always honored.
    """
    nid = data.get("network_id")
    if nid is None:
        if len(STORE["networks"]) == 1:
            nid = next(iter(STORE["networks"].keys()))
        else:
            raise err_invalid("Missing or invalid field: network_id")
    if not isinstance(nid, str):
        raise err_invalid("Missing or invalid field: network_id")
    return get_network_or_404(nid)


def get_source_or_404(sid):
    s = STORE["sources"].get(sid)
    if s is None:
        raise err_not_found("DataSource not found")
    return s


def get_shop_or_404(sid):
    s = STORE["shops"].get(sid)
    if s is None:
        raise err_not_found("Shop not found")
    return s


def get_vehicle_or_404(vid):
    v = STORE["vehicles"].get(vid)
    if v is None:
        raise err_not_found("Vehicle not found")
    return v


def get_record_or_404(rid):
    r = STORE["records"].get(rid)
    if r is None:
        raise err_not_found("HistoryRecord not found")
    return r


def get_correction_or_404(cid):
    c = STORE["corrections"].get(cid)
    if c is None:
        raise err_not_found("CorrectionRequest not found")
    return c


def get_consumer_or_404(cid):
    c = STORE["consumers"].get(cid)
    if c is None:
        raise err_not_found("ConsumerAccount not found")
    return c


def get_dealer_or_404(did):
    d = STORE["dealers"].get(did)
    if d is None:
        raise err_not_found("Dealer not found")
    return d


def get_listing_or_404(lid):
    l = STORE["listings"].get(lid)
    if l is None:
        raise err_not_found("InventoryListing not found")
    return l


def get_claim_or_404(cid):
    c = STORE["claims"].get(cid)
    if c is None:
        raise err_not_found("GuaranteeClaim not found")
    return c


def get_report_or_404(rid):
    r = STORE["reports"].get(rid)
    if r is None:
        raise err_not_found("ReportOrder not found")
    return r


def records_for_vehicle(vehicle_id):
    return [r for r in STORE["records"].values() if r["vehicle_id"] == vehicle_id]


def active_records_for_vehicle(vehicle_id):
    return [r for r in records_for_vehicle(vehicle_id) if r["status"] == "ACTIVE"]


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def severity_of(brand):
    return SEVERITY.get(brand, 0)


def confidence_level_of(score):
    if score is None:
        return None
    if score >= CONF_HIGH:
        return "HIGH"
    if score >= CONF_MEDIUM:
        return "MEDIUM"
    if score >= CONF_LOW:
        return "LOW"
    return "UNRELIABLE"


def compute_confidence(record):
    """Accident confidence. Uses the submitting source's CURRENT reliability."""
    source = STORE["sources"].get(record["source_id"])
    if source is None:
        reliability = 0
        source_type = None
    else:
        reliability = source["reliability_score"]
        source_type = source["source_type"]
    reliability = max(0, min(100, reliability))

    same_type = 0
    cross_type = 0
    for other in STORE["records"].values():
        if other["id"] == record["id"]:
            continue
        if other["vehicle_id"] != record["vehicle_id"]:
            continue
        if other["record_type"] != "ACCIDENT":
            continue
        if other["status"] != "ACTIVE":
            continue
        if other["source_id"] == record["source_id"]:
            continue
        if abs(date_diff_days(other["event_date"], record["event_date"])) > 30:
            continue
        other_source = STORE["sources"].get(other["source_id"])
        other_type = other_source["source_type"] if other_source else None
        if other_type == source_type:
            same_type += 1
        else:
            cross_type += 1
    same_bonus = 10 * min(2, same_type)
    cross_bonus = 20 * min(2, cross_type)
    raw = (40 + same_bonus + cross_bonus) * (reliability / 100.0)
    return int(raw // 1)  # floor


def recompute_accident_confidence(record):
    if record["record_type"] != "ACCIDENT":
        return
    record["confidence_score"] = compute_confidence(record)
    record["confidence_level"] = confidence_level_of(record["confidence_score"])


def recompute_vehicle_rollup(vehicle):
    records = records_for_vehicle(vehicle["id"])
    active = [r for r in records if r["status"] == "ACTIVE"]
    titles = [r for r in active if r["record_type"] == "TITLE_BRAND"]
    if not titles:
        vehicle["canonical_brand"] = "NONE"
        vehicle["brand_severity"] = 0
    else:
        winner = max(
            titles,
            key=lambda r: (
                r.get("brand_severity") or 0,
                # tie-break: earliest event_date, earliest created_at -> invert
                _invert_date_key(r.get("event_date") or ""),
                _invert_str_key(r.get("created_at") or ""),
            ),
        )
        vehicle["canonical_brand"] = winner.get("canonical_brand")
        vehicle["brand_severity"] = winner.get("brand_severity") or 0
    vehicle["active_record_count"] = len(active)
    vehicle["superseded_record_count"] = len(
        [r for r in records if r["status"] == "SUPERSEDED"]
    )
    accidents = [
        r
        for r in active
        if r["record_type"] == "ACCIDENT" and (r.get("confidence_score") or 0) >= CONF_MEDIUM
    ]
    vehicle["max_confirmed_accident_severity"] = (
        max([r.get("damage_severity") or 0 for r in accidents]) if accidents else 0
    )
    bump(vehicle)


def _invert_date_key(d):
    """Map YYYY-MM-DD so that max() picks the earliest date."""
    try:
        return (9999 - int(d[0:4]), 99 - int(d[5:7]), 99 - int(d[8:10]))
    except (ValueError, TypeError):
        return (0, 0, 0)


def _invert_str_key(s):
    # max() picks smallest string when inverted char-by-char; approximate with
    # negative ordering using a tuple of (255 - ord) is expensive; instead sort
    # via negative length-safe trick: use tuple of -ord per char.
    return tuple(-ord(c) for c in s)


def dedupe_group_key_for(record_type, vin, jurisdiction, event_date):
    if record_type == "TITLE_BRAND":
        return f"{vin}|TITLE_BRAND|{jurisdiction}"
    if record_type in ("ACCIDENT", "INSPECTION"):
        return f"{vin}|{record_type}|{event_date}"
    return None  # SERVICE


def content_signature(rec):
    return (
        rec.get("raw_brand_text"),
        rec.get("damage_severity"),
        rec.get("odometer_reading"),
        rec.get("reported_cost_cents"),
    )


def normalize_brand(network, jurisdiction, raw_brand_text):
    lex = (network.get("brand_lexicon") or {}).get(jurisdiction) or {}
    if raw_brand_text not in lex:
        raise ApiError(
            "ERR_UNKNOWN_BRAND_TERM", 422, "Unknown brand term for jurisdiction"
        )
    return lex[raw_brand_text]


def update_shop_tier(shop):
    count = len(
        [
            r
            for r in STORE["records"].values()
            if r["source_id"] == shop.get("data_source_id")
            and r["record_type"] == "SERVICE"
            and r["status"] == "ACTIVE"
        ]
    )
    new_tier = "PRO" if count >= PRO_THRESHOLD else "BASIC"
    current = shop["reporting_tool_tier"]
    changed = False
    if current == "PRO" and new_tier == "BASIC":
        # downgrade applies immediately regardless of status
        shop["reporting_tool_tier"] = "BASIC"
        changed = True
    elif current == "BASIC" and new_tier == "PRO":
        if shop["status"] == "ACTIVE":
            shop["reporting_tool_tier"] = "PRO"
            changed = True
        # else deferred until reactivation
    if changed:
        bump(shop)


def recompute_dealer_overage(dealer):
    included = 0
    if dealer["subscription_tier"] == "STANDARD":
        included = STANDARD_INCLUDED
    elif dealer["subscription_tier"] == "PRO":
        included = PRO_INCLUDED
    dealer["period_overage_units"] = max(0, dealer["period_reports_used"] - included)


def create_vehicle(network_id, vin):
    v = {
        "id": new_id(),
        "network_id": network_id,
        "vin": vin,
        "canonical_brand": "NONE",
        "brand_severity": 0,
        "max_confirmed_accident_severity": 0,
        "active_record_count": 0,
        "superseded_record_count": 0,
    }
    touch(v)
    STORE["vehicles"][v["id"]] = v
    return v


def match_vehicle(network_id, vin):
    vehicles = [v for v in STORE["vehicles"].values() if v["network_id"] == network_id]
    exact = [v for v in vehicles if v["vin"] == vin]
    if exact:
        return exact[0], "EXACT_VIN"
    fuzzy = [v for v in vehicles if hamming_one(v["vin"], vin)]
    if len(fuzzy) > 1:
        raise ApiError("ERR_AMBIGUOUS_VIN_MATCH", 409, "Ambiguous VIN match")
    if len(fuzzy) == 1:
        return fuzzy[0], "FUZZY_VIN"
    return create_vehicle(network_id, vin), "EXACT_VIN"


def odometer_check(vehicle_id, record_type, event_date, odometer_reading):
    if record_type not in ("SERVICE", "INSPECTION") or odometer_reading is None:
        return
    max_prior = None
    for r in STORE["records"].values():
        if r["vehicle_id"] != vehicle_id:
            continue
        if r["record_type"] not in ("SERVICE", "INSPECTION"):
            continue
        if r["status"] != "ACTIVE":
            continue
        if r.get("odometer_reading") is None:
            continue
        if r["event_date"] < event_date:
            if max_prior is None or r["odometer_reading"] > max_prior:
                max_prior = r["odometer_reading"]
    if max_prior is not None and odometer_reading < max_prior:
        raise ApiError("ERR_ODOMETER_ROLLBACK", 422, "Odometer rollback")


# ---------------------------------------------------------------------------
# Ingest pipeline
# ---------------------------------------------------------------------------


def ingest_record(*, network, source, vin, record_type, jurisdiction, raw_brand_text,
                  event_date, damage_severity, odometer_reading,
                  reported_cost_cents, payload_ref, idempotency_key,
                  expected_vehicle_version):
    # event_date must not be in the future (logical clock)
    if event_date > clock_date():
        source["record_rejection_streak"] = source.get("record_rejection_streak", 0) + 1
        bump(source)
        raise ApiError("ERR_EVENT_IN_FUTURE", 422, "event_date in the future")

    # Idempotency replay: same key + identical payload -> return original.
    prior = None
    for r in STORE["records"].values():
        if r["network_id"] == network["id"] and r.get("idempotency_key") == idempotency_key:
            prior = r
            break
    payload_tuple = (
        vin, source["id"], record_type, jurisdiction, raw_brand_text, event_date,
        damage_severity, odometer_reading, reported_cost_cents, payload_ref,
    )
    if prior is not None:
        prior_payload = (
            prior["vin"], prior["source_id"], prior["record_type"],
            prior.get("jurisdiction"), prior.get("raw_brand_text"),
            prior["event_date"], prior.get("damage_severity"),
            prior.get("odometer_reading"), prior.get("reported_cost_cents"),
            prior.get("payload_ref"),
        )
        if prior_payload == payload_tuple:
            return prior, False
        source["record_rejection_streak"] = source.get("record_rejection_streak", 0) + 1
        bump(source)
        raise ApiError("ERR_IDEMPOTENCY_CONFLICT", 409, "Idempotency conflict")

    # VIN match (may lazily create the vehicle)
    vehicle, match_method = match_vehicle(network["id"], vin)

    # OCC on the vehicle
    if expected_vehicle_version is not None:
        if expected_vehicle_version != vehicle["version"]:
            source["record_rejection_streak"] = source.get("record_rejection_streak", 0) + 1
            bump(source)
            raise err_stale("Stale vehicle version")

    # Brand normalization (TITLE_BRAND only)
    canonical_brand = None
    brand_severity = None
    if record_type == "TITLE_BRAND":
        try:
            canonical_brand = normalize_brand(network, jurisdiction, raw_brand_text)
        except ApiError:
            source["record_rejection_streak"] = source.get("record_rejection_streak", 0) + 1
            bump(source)
            raise
        brand_severity = severity_of(canonical_brand)

    # Odometer monotonicity (SERVICE/INSPECTION)
    try:
        odometer_check(vehicle["id"], record_type, event_date, odometer_reading)
    except ApiError:
        source["record_rejection_streak"] = source.get("record_rejection_streak", 0) + 1
        bump(source)
        raise

    group_key = dedupe_group_key_for(record_type, vin, jurisdiction, event_date)

    # Dedupe: same-source existing ACTIVE record in same group.
    if group_key is not None:
        existing = [
            r
            for r in STORE["records"].values()
            if r["vehicle_id"] == vehicle["id"]
            and r["status"] == "ACTIVE"
            and r.get("dedupe_group_key") == group_key
            and r["source_id"] == source["id"]
        ]
        if existing:
            existing.sort(key=lambda r: (r["created_at"], r["id"]))
            old = existing[0]
            old_sig = content_signature(old)
            new_sig = (raw_brand_text, damage_severity, odometer_reading, reported_cost_cents)
            if old_sig == new_sig:
                source["record_rejection_streak"] = source.get("record_rejection_streak", 0) + 1
                bump(source)
                raise ApiError("ERR_DUPLICATE_RECORD", 409, "Duplicate record")
            # Supersede: create replacement first, then retire the old one.
            new_rec = _build_record(
                network=network, source=source, vehicle=vehicle, vin=vin,
                record_type=record_type, jurisdiction=jurisdiction,
                raw_brand_text=raw_brand_text, event_date=event_date,
                damage_severity=damage_severity, odometer_reading=odometer_reading,
                reported_cost_cents=reported_cost_cents, payload_ref=payload_ref,
                idempotency_key=idempotency_key, match_method=match_method,
                group_key=group_key, canonical_brand=canonical_brand,
                brand_severity=brand_severity,
            )
            old["status"] = "SUPERSEDED"
            old["superseded_by_record_id"] = new_rec["id"]
            bump(old)
            _post_ingest(network, source, vehicle, new_rec)
            recompute_vehicle_rollup(vehicle)
            return new_rec, True

    new_rec = _build_record(
        network=network, source=source, vehicle=vehicle, vin=vin,
        record_type=record_type, jurisdiction=jurisdiction,
        raw_brand_text=raw_brand_text, event_date=event_date,
        damage_severity=damage_severity, odometer_reading=odometer_reading,
        reported_cost_cents=reported_cost_cents, payload_ref=payload_ref,
        idempotency_key=idempotency_key, match_method=match_method,
        group_key=group_key, canonical_brand=canonical_brand,
        brand_severity=brand_severity,
    )
    _post_ingest(network, source, vehicle, new_rec)
    recompute_vehicle_rollup(vehicle)
    return new_rec, True


def _build_record(*, network, source, vehicle, vin, record_type, jurisdiction,
                  raw_brand_text, event_date, damage_severity, odometer_reading,
                  reported_cost_cents, payload_ref, idempotency_key, match_method,
                  group_key, canonical_brand, brand_severity):
    rec = {
        "id": new_id(),
        "network_id": network["id"],
        "vehicle_id": vehicle["id"],
        "vin": vin,
        "source_id": source["id"],
        "record_type": record_type,
        "jurisdiction": jurisdiction,
        "raw_brand_text": raw_brand_text,
        "event_date": event_date,
        "damage_severity": damage_severity,
        "odometer_reading": odometer_reading,
        "reported_cost_cents": reported_cost_cents,
        "payload_ref": payload_ref,
        "idempotency_key": idempotency_key,
        "dedupe_group_key": group_key,
        "match_method": match_method,
        "confidence_score": None,
        "confidence_level": None,
        "canonical_brand": canonical_brand,
        "brand_severity": brand_severity,
        "status": "ACTIVE",
        "superseded_by_record_id": None,
        "submitted_epoch_index": network["epoch_index"],
    }
    touch(rec)
    STORE["records"][rec["id"]] = rec
    if record_type == "ACCIDENT":
        recompute_accident_confidence(rec)
    return rec


def _post_ingest(network, source, vehicle, rec):
    # accepted submission resets rejection streak
    source["record_rejection_streak"] = 0
    bump(source)
    # shop tool tier for shop-provisioned SERVICE records
    shop = _shop_for_source(source["id"])
    if shop is not None and rec["record_type"] == "SERVICE":
        update_shop_tier(shop)


def _shop_for_source(source_id):
    for s in STORE["shops"].values():
        if s.get("data_source_id") == source_id:
            return s
    return None


def withdraw_record(rec):
    if rec["status"] != "ACTIVE":
        return
    rec["status"] = "WITHDRAWN"
    bump(rec)
    vehicle = STORE["vehicles"].get(rec["vehicle_id"])
    if vehicle is not None:
        recompute_vehicle_rollup(vehicle)
    shop = _shop_for_source(rec["source_id"])
    if shop is not None and rec["record_type"] == "SERVICE":
        update_shop_tier(shop)


def void_record(rec):
    if rec["status"] != "ACTIVE":
        return
    rec["status"] = "VOIDED"
    bump(rec)
    vehicle = STORE["vehicles"].get(rec["vehicle_id"])
    if vehicle is not None:
        recompute_vehicle_rollup(vehicle)


def suspend_source(source, network):
    if source["status"] != "ACTIVE":
        return
    source["status"] = "SUSPENDED"
    source["suspended_epoch_index"] = network["epoch_index"]
    bump(source)
    for rec in list(STORE["records"].values()):
        if rec["source_id"] == source["id"] and rec["status"] == "ACTIVE":
            withdraw_record(rec)


# ---------------------------------------------------------------------------
# Clock / network
# ---------------------------------------------------------------------------


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    data = req_body()
    to_iso8601 = require_string(data, "to_iso8601")
    CLOCK["iso"] = to_iso8601
    return ok_object({})


@app.route("/networks", methods=["POST"])
def create_network():
    data = req_body()
    name = require_string(data, "name")
    cap = require_int(data, "guarantee_payout_cap_cents")
    if cap < 0:
        raise err_invalid("guarantee_payout_cap_cents must be >= 0")
    net = {
        "id": new_id(),
        "name": name,
        "epoch_index": 0,
        "brand_lexicon": {j: dict(m) for j, m in DEFAULT_BRAND_LEXICON.items()},
        "guarantee_payout_cap_cents": cap,
        "enrolled_listing_count": 0,
    }
    touch(net)
    STORE["networks"][net["id"]] = net
    return ok_object(net, 201)


@app.route("/networks/<nid>", methods=["GET"])
def get_network(nid):
    return ok_object(get_network_or_404(nid))


@app.route("/networks/<nid>/corrections", methods=["GET"])
def network_corrections(nid):
    get_network_or_404(nid)
    return list_response([c for c in STORE["corrections"].values() if c["network_id"] == nid])


@app.route("/networks/<nid>/consumers", methods=["GET"])
def network_consumers(nid):
    get_network_or_404(nid)
    return list_response([c for c in STORE["consumers"].values() if c["network_id"] == nid])


@app.route("/networks/<nid>/dealers", methods=["GET"])
def network_dealers(nid):
    get_network_or_404(nid)
    return list_response([d for d in STORE["dealers"].values() if d["network_id"] == nid])


@app.route("/networks/<nid>/records", methods=["GET"])
def network_records(nid):
    get_network_or_404(nid)
    return list_response([r for r in STORE["records"].values() if r["network_id"] == nid])


@app.route("/networks/<nid>/listings", methods=["GET"])
def network_listings(nid):
    get_network_or_404(nid)
    return list_response([l for l in STORE["listings"].values() if l["network_id"] == nid])


@app.route("/networks/<nid>/claims", methods=["GET"])
def network_claims(nid):
    get_network_or_404(nid)
    return list_response([c for c in STORE["claims"].values() if c["network_id"] == nid])


@app.route("/networks/<nid>/reports", methods=["GET"])
def network_reports(nid):
    get_network_or_404(nid)
    return list_response([r for r in STORE["reports"].values() if r["network_id"] == nid])


# ---------------------------------------------------------------------------
# Advance epoch
# ---------------------------------------------------------------------------


@app.route("/advance_epoch", methods=["POST"])
def advance_epoch():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise err_invalid()
    nid = data.get("network_id") or request.args.get("network_id")
    if not nid:
        if len(STORE["networks"]) == 1:
            nid = next(iter(STORE["networks"].keys()))
        else:
            raise err_invalid("network_id is required")
    net = get_network_or_404(nid)
    epoch_just_ended = net["epoch_index"]
    net["epoch_index"] += 1
    bump(net)

    # 1. Feed reliability decay over ACTIVE sources in this network
    for source in list(STORE["sources"].values()):
        if source["network_id"] != nid or source["status"] != "ACTIVE":
            continue
        submitted = len(
            [
                r
                for r in STORE["records"].values()
                if r["source_id"] == source["id"]
                and r["submitted_epoch_index"] == epoch_just_ended
            ]
        )
        if submitted == 0:
            source["consecutive_missed_epochs"] = source.get("consecutive_missed_epochs", 0) + 1
            source["reliability_score"] = max(0, source["reliability_score"] - 10)
        else:
            source["consecutive_missed_epochs"] = 0
            source["reliability_score"] = min(100, source["reliability_score"] + 2)
        bump(source)
        if (
            source["consecutive_missed_epochs"] >= 3
            or source.get("record_rejection_streak", 0) >= 3
        ):
            suspend_source(source, net)

    # 2. Recompute accident confidence (post-decay reliability), purge stale UNRELIABLE
    affected_vehicles = set()
    for rec in list(STORE["records"].values()):
        if (
            rec["network_id"] == nid
            and rec["record_type"] == "ACCIDENT"
            and rec["status"] == "ACTIVE"
        ):
            recompute_accident_confidence(rec)
            bump(rec)
            affected_vehicles.add(rec["vehicle_id"])
    for rec in list(STORE["records"].values()):
        if (
            rec["network_id"] == nid
            and rec["record_type"] == "ACCIDENT"
            and rec["status"] == "ACTIVE"
            and (rec.get("confidence_score") or 0) < CONF_LOW
            and rec["submitted_epoch_index"] <= net["epoch_index"] - 2
        ):
            void_record(rec)
            affected_vehicles.discard(rec["vehicle_id"])
    for vid in affected_vehicles:
        vehicle = STORE["vehicles"].get(vid)
        if vehicle is not None:
            recompute_vehicle_rollup(vehicle)

    # 3. Expire overdue corrections
    for c in list(STORE["corrections"].values()):
        if (
            c["network_id"] == nid
            and c["status"] == "AWAITING_SOURCE"
            and c.get("source_deadline_epoch") is not None
            and net["epoch_index"] > c["source_deadline_epoch"]
        ):
            c["status"] = "EXPIRED"
            bump(c)

    # 4. Claim sweep: OPEN claims failing escalation -> DENIED
    for claim in list(STORE["claims"].values()):
        if claim["network_id"] != nid or claim["status"] != "OPEN":
            continue
        listing = STORE["listings"].get(claim["listing_id"])
        if listing is None:
            continue
        vehicle = STORE["vehicles"].get(listing["vehicle_id"])
        if vehicle is None:
            continue
        enrolled_sev = severity_of(listing.get("enrolled_brand"))
        if vehicle["brand_severity"] <= enrolled_sev:
            claim["status"] = "DENIED"
            bump(claim)

    # 5. Settle APPROVED claims -> PAID
    for claim in list(STORE["claims"].values()):
        if claim["network_id"] == nid and claim["status"] == "APPROVED":
            claim["status"] = "PAID"
            claim["payout_epoch_index"] = net["epoch_index"]
            bump(claim)

    # 6. Dealer auto-suspension
    for dealer in list(STORE["dealers"].values()):
        if (
            dealer["network_id"] == nid
            and dealer["status"] == "ACTIVE"
            and dealer["invoice_balance_cents"] > DEALER_SUSPEND_THRESHOLD_CENTS
        ):
            dealer["status"] = "SUSPENDED"
            bump(dealer)

    return ok_object(net)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


@app.route("/sources", methods=["POST"])
def create_source():
    data = req_body()
    net = resolve_network(data)
    source_type = require_enum(data, "source_type", SOURCE_TYPES)
    jurisdiction = require_string(data, "jurisdiction")
    src = {
        "id": new_id(),
        "network_id": net["id"],
        "source_type": source_type,
        "jurisdiction": jurisdiction,
        "status": "PENDING",
        "reliability_score": 100,
        "consecutive_missed_epochs": 0,
        "suspended_epoch_index": None,
        "record_rejection_streak": 0,
    }
    touch(src)
    STORE["sources"][src["id"]] = src
    return ok_object(src, 201)


@app.route("/sources/<sid>", methods=["GET"])
def get_source(sid):
    return ok_object(get_source_or_404(sid))


@app.route("/sources", methods=["GET"])
def list_sources():
    items = list(STORE["sources"].values())
    network_id = request.args.get("network_id")
    status = request.args.get("status")
    source_type = request.args.get("source_type")
    if network_id is not None:
        items = [s for s in items if s["network_id"] == network_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if source_type is not None:
        items = [s for s in items if s["source_type"] == source_type]
    return list_response(items)


@app.route("/sources/<sid>/activate", methods=["POST"])
def activate_source(sid):
    src = get_source_or_404(sid)
    if src["status"] != "PENDING":
        raise err_invalid_state("Source not in PENDING")
    src["status"] = "ACTIVE"
    src["reliability_score"] = 100
    src["consecutive_missed_epochs"] = 0
    bump(src)
    return ok_object(src)


@app.route("/sources/<sid>/reactivate", methods=["POST"])
def reactivate_source(sid):
    src = get_source_or_404(sid)
    if src["status"] != "SUSPENDED":
        raise err_invalid_state("Source not SUSPENDED")
    net = get_network_or_404(src["network_id"])
    if net["epoch_index"] - (src.get("suspended_epoch_index") or 0) < 1:
        raise ApiError("ERR_REMEDIATION_TOO_EARLY", 409, "Remediation too early")
    if src.get("record_rejection_streak", 0) >= 3:
        raise ApiError("ERR_STREAK_NOT_RESET", 409, "Rejection streak not reset")
    src["status"] = "ACTIVE"
    src["reliability_score"] = 50
    src["consecutive_missed_epochs"] = 0
    src["record_rejection_streak"] = 0
    src["suspended_epoch_index"] = None
    bump(src)
    return ok_object(src)


@app.route("/sources/<sid>/reset_streak", methods=["POST"])
def reset_streak(sid):
    src = get_source_or_404(sid)
    src["record_rejection_streak"] = 0
    bump(src)
    return ok_object(src)


@app.route("/sources/<sid>/terminate", methods=["POST"])
def terminate_source(sid):
    src = get_source_or_404(sid)
    if src["status"] == "ACTIVE":
        active_records = [
            r for r in STORE["records"].values()
            if r["source_id"] == sid and r["status"] == "ACTIVE"
        ]
        if active_records:
            raise ApiError("ERR_SOURCE_HAS_ACTIVE_RECORDS", 409, "Source has active records")
    elif src["status"] == "SUSPENDED":
        net = get_network_or_404(src["network_id"])
        if net["epoch_index"] - (src.get("suspended_epoch_index") or 0) < 2:
            raise ApiError("ERR_TERMINATION_TOO_EARLY", 409, "Termination too early")
    else:
        raise err_invalid_state("Source cannot be terminated from current state")
    src["status"] = "TERMINATED"
    bump(src)
    return ok_object(src)


@app.route("/sources/<sid>/records", methods=["GET"])
def source_records(sid):
    get_source_or_404(sid)
    items = [r for r in STORE["records"].values() if r["source_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@app.route("/records", methods=["POST"])
def submit_record():
    uid = request.headers.get("X-User-ID")
    data = req_body()
    source_id = require_string(data, "source_id")
    vin = validate_vin(require_string(data, "vin"))
    record_type = require_enum(data, "record_type", RECORD_TYPES)
    event_date = parse_event_date(data)
    jurisdiction = optional_string(data, "jurisdiction")
    raw_brand_text = optional_string(data, "raw_brand_text")
    damage_severity = optional_int(data, "damage_severity")
    odometer_reading = optional_int(data, "odometer_reading")
    reported_cost_cents = optional_int(data, "reported_cost_cents")
    payload_ref = require_string(data, "payload_ref")
    idempotency_key = require_string(data, "idempotency_key")
    expected_vehicle_version = optional_int(data, "expected_vehicle_version")

    if damage_severity is not None and (damage_severity < 1 or damage_severity > 10):
        raise err_invalid("damage_severity must be 1..10")
    if odometer_reading is not None and odometer_reading < 0:
        raise err_invalid("odometer_reading must be >= 0")
    if reported_cost_cents is not None and reported_cost_cents < 0:
        raise err_invalid("reported_cost_cents must be >= 0")
    if record_type == "TITLE_BRAND":
        if jurisdiction is None or raw_brand_text is None:
            raise err_invalid("jurisdiction and raw_brand_text required for TITLE_BRAND")

    # PRD §3.1/§3.3: fields not applicable to the record's type are null.
    if record_type == "TITLE_BRAND":
        damage_severity = None
        odometer_reading = None
        reported_cost_cents = None
    elif record_type == "ACCIDENT":
        jurisdiction = None
        raw_brand_text = None
        odometer_reading = None
    elif record_type == "INSPECTION":
        jurisdiction = None
        raw_brand_text = None
        damage_severity = None
        reported_cost_cents = None
    elif record_type == "SERVICE":
        jurisdiction = None
        raw_brand_text = None
        damage_severity = None

    source = get_source_or_404(source_id)
    if source["status"] != "ACTIVE":
        raise ApiError("ERR_SOURCE_NOT_ACTIVE", 409, "Source not ACTIVE")
    if uid != source_id:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "SourceOperator identity mismatch")
    net = get_network_or_404(source["network_id"])

    rec, created = ingest_record(
        network=net, source=source, vin=vin, record_type=record_type,
        jurisdiction=jurisdiction, raw_brand_text=raw_brand_text,
        event_date=event_date, damage_severity=damage_severity,
        odometer_reading=odometer_reading, reported_cost_cents=reported_cost_cents,
        payload_ref=payload_ref, idempotency_key=idempotency_key,
        expected_vehicle_version=expected_vehicle_version,
    )
    return ok_object(rec, 201)


@app.route("/records", methods=["GET"])
def list_records():
    items = list(STORE["records"].values())
    for param in ("network_id", "vehicle_id", "source_id", "superseded_by_record_id",
                  "record_type", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    return list_response(items)


@app.route("/records/<rid>", methods=["GET"])
def get_record(rid):
    return ok_object(get_record_or_404(rid))


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------


@app.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    return ok_object(get_vehicle_or_404(vid))


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    items = list(STORE["vehicles"].values())
    network_id = request.args.get("network_id")
    canonical_brand = request.args.get("canonical_brand")
    if network_id is not None:
        items = [v for v in items if v["network_id"] == network_id]
    if canonical_brand is not None:
        items = [v for v in items if v["canonical_brand"] == canonical_brand]
    return list_response(items)


@app.route("/vehicles/<vid>/records", methods=["GET"])
def vehicle_records(vid):
    get_vehicle_or_404(vid)
    items = [r for r in STORE["records"].values() if r["vehicle_id"] == vid]
    record_type = request.args.get("record_type")
    status = request.args.get("status")
    if record_type is not None:
        items = [r for r in items if r["record_type"] == record_type]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items)


# ---------------------------------------------------------------------------
# Shops
# ---------------------------------------------------------------------------


@app.route("/shops", methods=["POST"])
def create_shop():
    data = req_body()
    net = resolve_network(data)
    legal_name = require_string(data, "legal_name")
    shop = {
        "id": new_id(),
        "network_id": net["id"],
        "legal_name": legal_name,
        "status": "APPLIED",
        "suspended_epoch_index": None,
        "data_source_id": None,
        "reporting_tool_tier": "NONE",
    }
    touch(shop)
    STORE["shops"][shop["id"]] = shop
    return ok_object(shop, 201)


@app.route("/shops/<sid>", methods=["GET"])
def get_shop(sid):
    return ok_object(get_shop_or_404(sid))


@app.route("/shops", methods=["GET"])
def list_shops():
    items = list(STORE["shops"].values())
    for param in ("network_id", "data_source_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s.get(param) == v]
    return list_response(items)


@app.route("/shops/<sid>/approve", methods=["POST"])
def approve_shop(sid):
    shop = get_shop_or_404(sid)
    if shop["status"] != "APPLIED":
        raise err_invalid_state("Shop not APPLIED")
    shop["status"] = "ACTIVE"
    src = {
        "id": new_id(),
        "network_id": shop["network_id"],
        "source_type": "SERVICE_SHOP",
        "jurisdiction": "SHOP",
        "status": "ACTIVE",
        "reliability_score": 100,
        "consecutive_missed_epochs": 0,
        "suspended_epoch_index": None,
        "record_rejection_streak": 0,
    }
    touch(src)
    STORE["sources"][src["id"]] = src
    shop["data_source_id"] = src["id"]
    shop["reporting_tool_tier"] = "BASIC"
    bump(shop)
    return ok_object(shop)


@app.route("/shops/<sid>/suspend", methods=["POST"])
def suspend_shop(sid):
    shop = get_shop_or_404(sid)
    if shop["status"] != "ACTIVE":
        raise err_invalid_state("Shop not ACTIVE")
    net = get_network_or_404(shop["network_id"])
    shop["status"] = "SUSPENDED"
    shop["suspended_epoch_index"] = net["epoch_index"]
    bump(shop)
    return ok_object(shop)


@app.route("/shops/<sid>/reactivate", methods=["POST"])
def reactivate_shop(sid):
    shop = get_shop_or_404(sid)
    if shop["status"] != "SUSPENDED":
        raise err_invalid_state("Shop not SUSPENDED")
    net = get_network_or_404(shop["network_id"])
    if net["epoch_index"] - (shop.get("suspended_epoch_index") or 0) < 1:
        raise ApiError("ERR_REMEDIATION_TOO_EARLY", 409, "Remediation too early")
    shop["status"] = "ACTIVE"
    shop["suspended_epoch_index"] = None
    bump(shop)
    # apply deferred tier upgrade
    update_shop_tier(shop)
    return ok_object(shop)


@app.route("/shops/<sid>/terminate", methods=["POST"])
def terminate_shop(sid):
    shop = get_shop_or_404(sid)
    if shop["status"] != "ACTIVE":
        raise err_invalid_state("Shop not ACTIVE")
    open_corrections = [
        c for c in STORE["corrections"].values()
        if c.get("requester_shop_id") == sid and c["status"] in ("OPEN", "AWAITING_SOURCE")
    ]
    if open_corrections:
        raise ApiError("ERR_SHOP_HAS_OPEN_CORRECTIONS", 409, "Shop has open corrections")
    shop["status"] = "TERMINATED"
    bump(shop)
    src_id = shop.get("data_source_id")
    if src_id:
        src = STORE["sources"].get(src_id)
        if src is not None:
            active_records = [
                r for r in STORE["records"].values()
                if r["source_id"] == src_id and r["status"] == "ACTIVE"
            ]
            if not active_records:
                src["status"] = "TERMINATED"
                bump(src)
    return ok_object(shop)


@app.route("/shops/<sid>/service-records", methods=["POST"])
def shop_service_record(sid):
    uid = request.headers.get("X-User-ID")
    shop = get_shop_or_404(sid)
    if uid != sid:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "ShopOperator identity mismatch")
    if shop["status"] != "ACTIVE":
        raise ApiError("ERR_SHOP_NOT_ACTIVE", 409, "Shop not ACTIVE")
    data = req_body()
    vin = validate_vin(require_string(data, "vin"))
    event_date = parse_event_date(data)
    odometer_reading = require_int(data, "odometer_reading")
    if odometer_reading < 0:
        raise err_invalid("odometer_reading must be >= 0")
    reported_cost_cents = optional_int(data, "reported_cost_cents")
    if reported_cost_cents is not None and reported_cost_cents < 0:
        raise err_invalid("reported_cost_cents must be >= 0")
    payload_ref = require_string(data, "payload_ref")
    idempotency_key = require_string(data, "idempotency_key")
    expected_vehicle_version = optional_int(data, "expected_vehicle_version")

    src_id = shop.get("data_source_id")
    source = get_source_or_404(src_id)
    if source["status"] != "ACTIVE":
        raise ApiError("ERR_SOURCE_NOT_ACTIVE", 409, "Provisioned source not ACTIVE")
    net = get_network_or_404(shop["network_id"])

    rec, _created = ingest_record(
        network=net, source=source, vin=vin, record_type="SERVICE",
        jurisdiction=None, raw_brand_text=None, event_date=event_date,
        damage_severity=None, odometer_reading=odometer_reading,
        reported_cost_cents=reported_cost_cents, payload_ref=payload_ref,
        idempotency_key=idempotency_key,
        expected_vehicle_version=expected_vehicle_version,
    )
    return ok_object(rec, 201)


@app.route("/shops/<sid>/service-records", methods=["GET"])
def shop_service_records(sid):
    shop = get_shop_or_404(sid)
    items = [
        r for r in STORE["records"].values()
        if shop.get("data_source_id") and r["source_id"] == shop["data_source_id"]
    ]
    return list_response(items)


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


@app.route("/vehicles/<vid>/corrections", methods=["POST"])
def open_correction(vid):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    vehicle = get_vehicle_or_404(vid)
    data = req_body()
    target_record_id = require_string(data, "target_record_id")
    reason = require_string(data, "reason")
    corrected_record = data.get("corrected_record")
    if corrected_record is not None and not isinstance(corrected_record, dict):
        raise err_invalid("corrected_record must be an object")
    expected_vehicle_version = data.get("expected_vehicle_version")
    if expected_vehicle_version is None or isinstance(expected_vehicle_version, bool) \
            or not isinstance(expected_vehicle_version, int):
        raise err_invalid("expected_vehicle_version is required")
    if expected_vehicle_version != vehicle["version"]:
        raise err_stale("Stale vehicle version")

    target = STORE["records"].get(target_record_id)
    if target is None or target["vehicle_id"] != vid or target["status"] != "ACTIVE":
        raise ApiError("ERR_RECORD_NOT_ACTIVE", 409, "Target record not ACTIVE on vehicle")

    net = get_network_or_404(vehicle["network_id"])
    requester_role = "OWNER" if role == "VehicleOwner" else "SHOP"
    requester_shop_id = uid if role == "ShopOperator" else None
    corr = {
        "id": new_id(),
        "network_id": net["id"],
        "vehicle_id": vid,
        "target_record_id": target_record_id,
        "requester_role": requester_role,
        "requester_shop_id": requester_shop_id,
        "reason": reason,
        "corrected_record": corrected_record,
        "status": "OPEN",
        "resolution_action": None,
        "opened_epoch_index": net["epoch_index"],
        "source_deadline_epoch": None,
    }
    touch(corr)
    STORE["corrections"][corr["id"]] = corr
    return ok_object(corr, 201)


@app.route("/corrections/<cid>", methods=["GET"])
def get_correction(cid):
    return ok_object(get_correction_or_404(cid))


@app.route("/vehicles/<vid>/corrections/<cid>", methods=["GET"])
def get_correction_scoped(vid, cid):
    get_vehicle_or_404(vid)
    corr = get_correction_or_404(cid)
    if corr["vehicle_id"] != vid:
        raise err_not_found("Correction not found for vehicle")
    return ok_object(corr)


@app.route("/vehicles/<vid>/corrections", methods=["GET"])
def vehicle_corrections(vid):
    get_vehicle_or_404(vid)
    items = [c for c in STORE["corrections"].values() if c["vehicle_id"] == vid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items)


@app.route("/corrections", methods=["GET"])
def list_corrections():
    items = list(STORE["corrections"].values())
    for param in ("network_id", "vehicle_id", "target_record_id", "requester_shop_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    return list_response(items)


@app.route("/corrections/<cid>/route_to_source", methods=["POST"])
def route_correction(cid):
    corr = get_correction_or_404(cid)
    if corr["status"] != "OPEN":
        raise err_invalid_state("Correction not OPEN")
    target = STORE["records"].get(corr["target_record_id"])
    if target is None or target["status"] != "ACTIVE":
        raise ApiError("ERR_RECORD_NOT_ACTIVE", 409, "Target record not ACTIVE")
    net = get_network_or_404(corr["network_id"])
    corr["status"] = "AWAITING_SOURCE"
    corr["source_deadline_epoch"] = net["epoch_index"] + 2
    bump(corr)
    return ok_object(corr)


@app.route("/corrections/<cid>/source_confirm", methods=["POST"])
def source_confirm(cid):
    uid = request.headers.get("X-User-ID")
    corr = get_correction_or_404(cid)
    if corr["status"] != "AWAITING_SOURCE":
        raise err_invalid_state("Correction not AWAITING_SOURCE")
    target = STORE["records"].get(corr["target_record_id"])
    if target is None or uid != target["source_id"]:
        raise ApiError("ERR_NOT_RECORD_SOURCE", 403, "Not the record's owning source")
    corr["status"] = "VERIFIED"
    bump(corr)
    return ok_object(corr)


@app.route("/corrections/<cid>/source_deny", methods=["POST"])
def source_deny(cid):
    uid = request.headers.get("X-User-ID")
    corr = get_correction_or_404(cid)
    if corr["status"] != "AWAITING_SOURCE":
        raise err_invalid_state("Correction not AWAITING_SOURCE")
    target = STORE["records"].get(corr["target_record_id"])
    if target is None or uid != target["source_id"]:
        raise ApiError("ERR_NOT_RECORD_SOURCE", 403, "Not the record's owning source")
    corr["status"] = "REJECTED"
    bump(corr)
    return ok_object(corr)


@app.route("/corrections/<cid>/apply", methods=["POST"])
def apply_correction(cid):
    corr = get_correction_or_404(cid)
    if corr["status"] != "VERIFIED":
        raise err_invalid_state("Correction not VERIFIED")
    data = req_body()
    action = require_enum(data, "resolution_action", RESOLUTION_ACTIONS)
    corrected = data.get("corrected_record")
    if corrected is None:
        corrected = corr.get("corrected_record")
    if action == "SUPERSEDE" and not corrected:
        raise ApiError("ERR_CORRECTION_PAYLOAD_REQUIRED", 400, "corrected_record required")

    target = STORE["records"].get(corr["target_record_id"])
    if target is None or target["status"] != "ACTIVE":
        raise err_invalid_state("Target record not ACTIVE")
    net = get_network_or_404(corr["network_id"])
    vehicle = get_vehicle_or_404(corr["vehicle_id"])
    source = get_source_or_404(target["source_id"])

    corr["resolution_action"] = action
    if action == "WITHDRAW":
        corr["status"] = "APPLIED"
        bump(corr)
        withdraw_record(target)
    else:  # SUPERSEDE
        corrected = dict(corrected)
        record_type = target["record_type"]
        # Corrected fields default to the target's existing values.
        event_date = corrected.get("event_date", target["event_date"])
        if not isinstance(event_date, str) or not DATE_RE.match(event_date):
            raise err_invalid("corrected_record.event_date invalid")
        if event_date > clock_date():
            raise ApiError("ERR_EVENT_IN_FUTURE", 422, "event_date in the future")
        jurisdiction = corrected.get("jurisdiction", target.get("jurisdiction"))
        raw_brand_text = corrected.get("raw_brand_text", target.get("raw_brand_text"))
        damage_severity = corrected.get("damage_severity", target.get("damage_severity"))
        odometer_reading = corrected.get("odometer_reading", target.get("odometer_reading"))
        reported_cost_cents = corrected.get(
            "reported_cost_cents", target.get("reported_cost_cents"))
        canonical_brand = None
        brand_severity = None
        if record_type == "TITLE_BRAND":
            canonical_brand = normalize_brand(net, jurisdiction, raw_brand_text)
            brand_severity = severity_of(canonical_brand)
        group_key = dedupe_group_key_for(
            record_type, target["vin"], jurisdiction, event_date)
        new_rec = _build_record(
            network=net, source=source, vehicle=vehicle, vin=target["vin"],
            record_type=record_type, jurisdiction=jurisdiction,
            raw_brand_text=raw_brand_text, event_date=event_date,
            damage_severity=damage_severity, odometer_reading=odometer_reading,
            reported_cost_cents=reported_cost_cents,
            payload_ref=corrected.get("payload_ref", target.get("payload_ref")),
            idempotency_key=new_id(),
            match_method=target.get("match_method") or "EXACT_VIN",
            group_key=group_key, canonical_brand=canonical_brand,
            brand_severity=brand_severity,
        )
        target["status"] = "SUPERSEDED"
        target["superseded_by_record_id"] = new_rec["id"]
        bump(target)
        recompute_vehicle_rollup(vehicle)
        corr["status"] = "APPLIED"
        bump(corr)
    return ok_object(corr)


# ---------------------------------------------------------------------------
# Consumers
# ---------------------------------------------------------------------------


@app.route("/consumers", methods=["POST"])
def create_consumer():
    data = req_body()
    net = resolve_network(data)
    email = require_string(data, "email")
    consumer = {
        "id": new_id(),
        "network_id": net["id"],
        "email": email,
        "credit_balance_cents": 0,
    }
    touch(consumer)
    STORE["consumers"][consumer["id"]] = consumer
    return ok_object(consumer, 201)


@app.route("/consumers/<cid>", methods=["GET"])
def get_consumer(cid):
    return ok_object(get_consumer_or_404(cid))


@app.route("/consumers", methods=["GET"])
def list_consumers():
    items = list(STORE["consumers"].values())
    network_id = request.args.get("network_id")
    if network_id is not None:
        items = [c for c in items if c["network_id"] == network_id]
    return list_response(items)


@app.route("/consumers/<cid>/credit", methods=["POST"])
def credit_consumer(cid):
    consumer = get_consumer_or_404(cid)
    data = req_body()
    amount = require_int(data, "amount_cents")
    if amount < 0:
        raise err_invalid("amount_cents must be >= 0")
    consumer["credit_balance_cents"] += amount
    bump(consumer)
    return ok_object(consumer)


# ---------------------------------------------------------------------------
# Dealers
# ---------------------------------------------------------------------------


@app.route("/dealers", methods=["POST"])
def create_dealer():
    data = req_body()
    net = resolve_network(data)
    legal_name = require_string(data, "legal_name")
    dealer = {
        "id": new_id(),
        "network_id": net["id"],
        "legal_name": legal_name,
        "subscription_tier": "NONE",
        "status": "ACTIVE",
        "subscription_started_epoch": None,
        "period_reports_used": 0,
        "period_overage_units": 0,
        "invoice_balance_cents": 0,
    }
    touch(dealer)
    STORE["dealers"][dealer["id"]] = dealer
    return ok_object(dealer, 201)


@app.route("/dealers/<did>", methods=["GET"])
def get_dealer(did):
    return ok_object(get_dealer_or_404(did))


@app.route("/dealers", methods=["GET"])
def list_dealers():
    items = list(STORE["dealers"].values())
    network_id = request.args.get("network_id")
    status = request.args.get("status")
    if network_id is not None:
        items = [d for d in items if d["network_id"] == network_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_response(items)


@app.route("/dealers/<did>/subscribe", methods=["POST"])
def subscribe_dealer(did):
    uid = request.headers.get("X-User-ID")
    dealer = get_dealer_or_404(did)
    if uid != did:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "DealerAgent identity mismatch")
    data = req_body()
    tier = require_enum(data, "tier", SUB_TIERS)
    net = get_network_or_404(dealer["network_id"])
    dealer["subscription_tier"] = tier
    if tier == "NONE":
        dealer["subscription_started_epoch"] = None
    else:
        dealer["subscription_started_epoch"] = net["epoch_index"]
    dealer["period_reports_used"] = 0
    recompute_dealer_overage(dealer)
    bump(dealer)
    return ok_object(dealer)


@app.route("/dealers/<did>/reinstate", methods=["POST"])
def reinstate_dealer(did):
    dealer = get_dealer_or_404(did)
    if dealer["status"] != "SUSPENDED":
        raise err_invalid_state("Dealer not SUSPENDED")
    if dealer["invoice_balance_cents"] > DEALER_SUSPEND_THRESHOLD_CENTS:
        raise ApiError("ERR_DEALER_BALANCE_OUTSTANDING", 409, "Balance outstanding")
    dealer["status"] = "ACTIVE"
    bump(dealer)
    return ok_object(dealer)


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


@app.route("/dealers/<did>/listings", methods=["POST"])
def create_listing(did):
    uid = request.headers.get("X-User-ID")
    dealer = get_dealer_or_404(did)
    if uid != did:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "DealerAgent identity mismatch")
    data = req_body()
    vehicle_id = require_string(data, "vehicle_id")
    vehicle = STORE["vehicles"].get(vehicle_id)
    if vehicle is None or vehicle["network_id"] != dealer["network_id"]:
        raise err_not_found("Vehicle not found")
    asking = require_int(data, "asking_price_cents")
    if asking < 0:
        raise err_invalid("asking_price_cents must be >= 0")
    listing = {
        "id": new_id(),
        "network_id": dealer["network_id"],
        "dealer_id": did,
        "vehicle_id": vehicle_id,
        "asking_price_cents": asking,
        "status": "DRAFT",
        "guarantee_status": "UNENROLLED",
        "enrolled_brand": None,
        "window_start_epoch": None,
        "window_end_epoch": None,
    }
    touch(listing)
    STORE["listings"][listing["id"]] = listing
    return ok_object(listing, 201)


@app.route("/dealers/<did>/listings", methods=["GET"])
def dealer_listings(did):
    get_dealer_or_404(did)
    items = [l for l in STORE["listings"].values() if l["dealer_id"] == did]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(items)


@app.route("/listings/<lid>", methods=["GET"])
def get_listing(lid):
    return ok_object(get_listing_or_404(lid))


@app.route("/listings", methods=["GET"])
def list_listings():
    items = list(STORE["listings"].values())
    for param in ("network_id", "vehicle_id", "dealer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if l.get(param) == v]
    return list_response(items)


def _get_owned_listing(did, lid):
    dealer = get_dealer_or_404(did)
    listing = STORE["listings"].get(lid)
    if listing is None or listing["dealer_id"] != did:
        raise err_not_found("Listing not found for dealer")
    uid = request.headers.get("X-User-ID")
    if uid != did:
        raise ApiError("ERR_NOT_LISTING_OWNER", 403, "Not listing owner")
    return dealer, listing


@app.route("/dealers/<did>/listings/<lid>/publish", methods=["POST"])
def publish_listing(did, lid):
    dealer, listing = _get_owned_listing(did, lid)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise err_invalid()
    window_end = data.get("window_end_epoch")
    if window_end is not None and (isinstance(window_end, bool) or not isinstance(window_end, int)):
        raise err_invalid("window_end_epoch must be an integer")
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED", 409, "Dealer suspended")
    vehicle = STORE["vehicles"].get(listing["vehicle_id"])
    if vehicle is None:
        raise err_not_found("Vehicle not found")
    if listing["status"] != "DRAFT":
        raise err_invalid_state("Listing not DRAFT")
    net = get_network_or_404(dealer["network_id"])
    listing["status"] = "PUBLISHED"
    listing["window_start_epoch"] = net["epoch_index"]
    if window_end is not None:
        if window_end <= listing["window_start_epoch"]:
            raise err_invalid("window_end_epoch must be > window_start_epoch")
        listing["window_end_epoch"] = window_end
    bump(listing)
    return ok_object(listing)


@app.route("/dealers/<did>/listings/<lid>/delist", methods=["POST"])
def delist_listing(did, lid):
    dealer, listing = _get_owned_listing(did, lid)
    if listing["status"] != "PUBLISHED":
        raise err_invalid_state("Listing not PUBLISHED")
    if listing["guarantee_status"] == "ENROLLED":
        open_claims = [
            c for c in STORE["claims"].values()
            if c["listing_id"] == lid and c["status"] in ("OPEN", "APPROVED")
        ]
        if open_claims:
            raise ApiError("ERR_CLAIM_IN_FLIGHT", 409, "Claim in flight")
        listing["guarantee_status"] = "VOIDED"
        net = get_network_or_404(dealer["network_id"])
        net["enrolled_listing_count"] = max(0, net["enrolled_listing_count"] - 1)
        bump(net)
    listing["status"] = "DELISTED"
    bump(listing)
    return ok_object(listing)


@app.route("/dealers/<did>/listings/<lid>/enroll_guarantee", methods=["POST"])
def enroll_guarantee(did, lid):
    dealer, listing = _get_owned_listing(did, lid)
    data = req_body()
    expected = data.get("expected_listing_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid("expected_listing_version is required")
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED", 409, "Dealer suspended")
    vehicle = STORE["vehicles"].get(listing["vehicle_id"])
    if vehicle is None:
        raise err_not_found("Vehicle not found")
    if listing["status"] != "PUBLISHED" or listing["guarantee_status"] != "UNENROLLED" \
            or vehicle["brand_severity"] > 1:
        raise ApiError("ERR_NOT_ENROLLABLE", 409, "Listing not enrollable")
    if expected != listing["version"]:
        raise err_stale("Stale listing version")
    listing["guarantee_status"] = "ENROLLED"
    listing["enrolled_brand"] = vehicle["canonical_brand"]
    net = get_network_or_404(dealer["network_id"])
    net["enrolled_listing_count"] += 1
    bump(net)
    bump(listing)
    return ok_object(listing)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def escalation_holds(listing, vehicle, claim):
    """True when the current canonical brand is a post-enrollment escalation
    attributable to a record ACTIVE at claim open or later."""
    enrolled_sev = severity_of(listing.get("enrolled_brand"))
    if vehicle["brand_severity"] <= enrolled_sev:
        return False
    # Find a currently ACTIVE title record carrying the canonical brand whose
    # submission epoch is >= the claim's open epoch.
    titles = [
        r for r in STORE["records"].values()
        if r["vehicle_id"] == vehicle["id"]
        and r["record_type"] == "TITLE_BRAND"
        and r["status"] == "ACTIVE"
        and (r.get("brand_severity") or 0) == vehicle["brand_severity"]
        and r["submitted_epoch_index"] >= claim["opened_epoch_index"]
    ]
    if not titles:
        return False
    return True


@app.route("/claims", methods=["POST"])
def file_claim():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    data = req_body()
    listing_id = require_string(data, "listing_id")
    claimant_name = require_string(data, "claimant_name")
    claim_reason = require_string(data, "claim_reason")
    listing = get_listing_or_404(listing_id)
    if role == "DealerAgent" and uid != listing["dealer_id"]:
        raise ApiError("ERR_NOT_LISTING_OWNER", 403, "Not listing owner")
    net = get_network_or_404(listing["network_id"])
    if listing["guarantee_status"] != "ENROLLED":
        raise ApiError("ERR_GUARANTEE_NOT_ENROLLED", 409, "Guarantee not enrolled")
    other = [
        c for c in STORE["claims"].values()
        if c["listing_id"] == listing_id and c["status"] in ("OPEN", "APPROVED")
    ]
    if other:
        raise ApiError("ERR_CLAIM_OVERLAP", 409, "Claim overlap")
    if listing.get("window_end_epoch") is not None \
            and net["epoch_index"] >= listing["window_end_epoch"]:
        raise ApiError("ERR_LISTING_WINDOW_CLOSED", 409, "Listing window closed")
    claim = {
        "id": new_id(),
        "network_id": listing["network_id"],
        "dealer_id": listing["dealer_id"],
        "listing_id": listing_id,
        "claimant_name": claimant_name,
        "claim_reason": claim_reason,
        "status": "OPEN",
        "payout_cents": 0,
        "payout_epoch_index": None,
        "opened_epoch_index": net["epoch_index"],
    }
    touch(claim)
    STORE["claims"][claim["id"]] = claim
    return ok_object(claim, 201)


@app.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    return ok_object(get_claim_or_404(cid))


@app.route("/claims", methods=["GET"])
def list_claims():
    items = list(STORE["claims"].values())
    for param in ("network_id", "listing_id", "dealer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    return list_response(items)


@app.route("/dealers/<did>/claims", methods=["GET"])
def dealer_claims(did):
    get_dealer_or_404(did)
    items = [c for c in STORE["claims"].values() if c["dealer_id"] == did]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items)


@app.route("/claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    claim = get_claim_or_404(cid)
    if claim["status"] != "OPEN":
        raise err_invalid_state("Claim not OPEN")
    listing = get_listing_or_404(claim["listing_id"])
    if listing["guarantee_status"] != "ENROLLED":
        raise ApiError("ERR_GUARANTEE_NOT_ENROLLED", 409, "Guarantee not enrolled")
    vehicle = get_vehicle_or_404(listing["vehicle_id"])
    if not escalation_holds(listing, vehicle, claim):
        raise ApiError("ERR_BRAND_NOT_ESCALATED", 409, "Brand not escalated")
    net = get_network_or_404(claim["network_id"])
    dealer = get_dealer_or_404(claim["dealer_id"])

    enrolled_sev = severity_of(listing.get("enrolled_brand"))
    delta = vehicle["brand_severity"] - enrolled_sev
    if delta >= 3:
        pct = 100
    elif delta == 2:
        pct = 75
    else:
        pct = 50
    base = listing["asking_price_cents"]
    provisional = (base * pct) // 100
    prior_paid = sum(
        c["payout_cents"]
        for c in STORE["claims"].values()
        if c["status"] == "PAID"
        and STORE["listings"].get(c["listing_id"]) is not None
        and STORE["listings"][c["listing_id"]]["vehicle_id"] == vehicle["id"]
    )
    lifetime_remaining = max(0, net["guarantee_payout_cap_cents"] - prior_paid)
    payout = min(provisional, lifetime_remaining)

    claim["payout_cents"] = payout
    claim["status"] = "APPROVED"
    bump(claim)
    listing["guarantee_status"] = "VOIDED"
    bump(listing)
    net["enrolled_listing_count"] = max(0, net["enrolled_listing_count"] - 1)
    bump(net)
    dealer["invoice_balance_cents"] += payout
    bump(dealer)
    return ok_object(claim)


@app.route("/claims/<cid>/reject", methods=["POST"])
def reject_claim(cid):
    claim = get_claim_or_404(cid)
    if claim["status"] != "OPEN":
        raise err_invalid_state("Claim not OPEN")
    claim["status"] = "REJECTED"
    bump(claim)
    return ok_object(claim)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def build_snapshot(vehicle):
    active = active_records_for_vehicle(vehicle["id"])
    active.sort(key=lambda r: (r["created_at"], r["id"]))
    def slim(r):
        return {
            "id": r["id"],
            "source_id": r["source_id"],
            "record_type": r["record_type"],
            "event_date": r["event_date"],
            "jurisdiction": r.get("jurisdiction"),
            "raw_brand_text": r.get("raw_brand_text"),
            "canonical_brand": r.get("canonical_brand"),
            "brand_severity": r.get("brand_severity"),
            "damage_severity": r.get("damage_severity"),
            "odometer_reading": r.get("odometer_reading"),
            "reported_cost_cents": r.get("reported_cost_cents"),
            "confidence_score": r.get("confidence_score"),
            "confidence_level": r.get("confidence_level"),
            "status": r["status"],
        }
    return {
        "vehicle_id": vehicle["id"],
        "vin": vehicle["vin"],
        "canonical_brand": vehicle["canonical_brand"],
        "brand_severity": vehicle["brand_severity"],
        "max_confirmed_accident_severity": vehicle["max_confirmed_accident_severity"],
        "active_record_count": vehicle["active_record_count"],
        "records": [slim(r) for r in active],
    }


@app.route("/reports", methods=["POST"])
def purchase_report():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    data = req_body()
    vehicle_id = require_string(data, "vehicle_id")
    product = require_enum(data, "product", PRODUCTS)
    vehicle = get_vehicle_or_404(vehicle_id)
    net = get_network_or_404(vehicle["network_id"])

    buyer_consumer_id = None
    buyer_dealer_id = None
    price = 0

    if product == "CONSUMER_SINGLE":
        if role != "VehicleOwner":
            raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "Role not permitted for product")
        buyer_consumer_id = data.get("buyer_consumer_id") or uid
        consumer = STORE["consumers"].get(buyer_consumer_id)
        if consumer is None or consumer["network_id"] != net["id"]:
            raise err_not_found("Consumer not found")
        prior = [
            o for o in STORE["reports"].values()
            if o.get("buyer_consumer_id") == buyer_consumer_id
            and o["vehicle_id"] == vehicle_id
            and o["status"] == "CONFIRMED"
        ]
        price = CONSUMER_RETURN_PRICE_CENTS if prior else CONSUMER_SINGLE_PRICE_CENTS
        if consumer["credit_balance_cents"] < price:
            raise ApiError("ERR_INSUFFICIENT_CREDIT", 402, "Insufficient credit")
        consumer["credit_balance_cents"] -= price
        bump(consumer)
    else:  # DEALER_SUBSCRIPTION
        if role != "DealerAgent":
            raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "Role not permitted for product")
        buyer_dealer_id = data.get("buyer_dealer_id") or uid
        dealer = STORE["dealers"].get(buyer_dealer_id)
        if dealer is None or dealer["network_id"] != net["id"]:
            raise err_not_found("Dealer not found")
        if uid != buyer_dealer_id:
            raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "DealerAgent identity mismatch")
        if dealer["subscription_tier"] == "NONE":
            raise ApiError("ERR_NO_SUBSCRIPTION", 402, "No subscription")
        started = dealer.get("subscription_started_epoch")
        if started is None or net["epoch_index"] >= started + WINDOW_EPOCHS:
            raise ApiError(
                "ERR_SUBSCRIPTION_WINDOW_EXPIRED", 409, "Subscription window expired")
        included = STANDARD_INCLUDED if dealer["subscription_tier"] == "STANDARD" else PRO_INCLUDED
        if dealer["period_reports_used"] < included:
            price = 0
        else:
            overage_index = dealer["period_reports_used"] - included + 1
            overage_price = OVERAGE_BASE_CENTS - OVERAGE_STEP_CENTS * (
                (overage_index - 1) // OVERAGE_STEP_EVERY)
            price = max(OVERAGE_FLOOR_CENTS, overage_price)
        if price > 0:
            dealer["invoice_balance_cents"] += price
        dealer["period_reports_used"] += 1
        recompute_dealer_overage(dealer)
        bump(dealer)

    order = {
        "id": new_id(),
        "network_id": net["id"],
        "vehicle_id": vehicle_id,
        "product": product,
        "buyer_consumer_id": buyer_consumer_id,
        "buyer_dealer_id": buyer_dealer_id,
        "price_cents": price,
        "snapshot": build_snapshot(vehicle),
        "status": "CONFIRMED",
    }
    touch(order)
    STORE["reports"][order["id"]] = order
    return ok_object(order, 201)


@app.route("/reports/<rid>", methods=["GET"])
def get_report(rid):
    return ok_object(get_report_or_404(rid))


@app.route("/reports", methods=["GET"])
def list_reports():
    items = list(STORE["reports"].values())
    for param in ("network_id", "vehicle_id", "buyer_consumer_id", "buyer_dealer_id", "product"):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o.get(param) == v]
    return list_response(items)


@app.route("/vehicles/<vid>/reports", methods=["GET"])
def vehicle_reports(vid):
    get_vehicle_or_404(vid)
    return list_response([o for o in STORE["reports"].values() if o["vehicle_id"] == vid])


@app.route("/consumers/<cid>/reports", methods=["GET"])
def consumer_reports(cid):
    get_consumer_or_404(cid)
    return list_response([o for o in STORE["reports"].values() if o.get("buyer_consumer_id") == cid])


@app.route("/dealers/<did>/reports", methods=["GET"])
def dealer_reports(did):
    get_dealer_or_404(did)
    return list_response([o for o in STORE["reports"].values() if o.get("buyer_dealer_id") == did])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
