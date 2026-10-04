"""Recruiter Seats API — in-memory Flask implementation.

Multi-root REST surface: contracts, seats, recruiters, quota ledgers, credit
pools, candidate profiles, search projects, messages, job postings, promoted
slots, ATS integrations, ATS sync records, talent insights, renewal events,
and a logical clock test-driving endpoint.

Storage: in-memory dicts only. The store starts empty on every boot.
"""
import hashlib
import json
import math
import os
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_NOW = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_LOGICAL_NOW = {"now": _DEFAULT_NOW}


def now():
    return _LOGICAL_NOW["now"]


def iso(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return s


def parse_dt(s):
    if isinstance(s, str):
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    return None


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

db = {
    "contracts": {},
    "seats": {},
    "recruiters": {},
    "quota_ledgers": {},
    "credit_pools": {},
    "messages": {},
    "candidates": {},
    "projects": {},
    "job_postings": {},
    "promoted_slots": {},
    "ats_integrations": {},
    "ats_sync_records": {},
    "talent_reports": {},
    "renewal_events": {},
}

VALID_ROLES = {"ContractAdmin", "SeatAdmin", "RecruiterUser", "AtsService", "Auditor"}

TIER_LIMITS = {
    "RECRUITER_LITE": {"monthly_credit_per_seat": 30, "monthly_search_quota_per_seat": 100, "search_result_page_cap": 40},
    "RECRUITER_PRO": {"monthly_credit_per_seat": 100, "monthly_search_quota_per_seat": 1000, "search_result_page_cap": 100},
    "RECRUITER_CORP": {"monthly_credit_per_seat": 150, "monthly_search_quota_per_seat": 10000, "search_result_page_cap": 1000},
}

AGGREGATION_FLOOR = 25
THROTTLE_THRESHOLD = 3
PERIOD_DAYS = 30


# ---------------------------------------------------------------------------
# Errors and response envelope
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _request_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


def success_envelope(data, is_array=False, status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now()),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": iso(now()),
        },
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return handle_api_error(ApiError("ERR_NOT_FOUND", 404, "Not found"))


@app.errorhandler(405)
def handle_405(e):
    return handle_api_error(ApiError("ERR_NOT_FOUND", 404, "Not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return handle_api_error(ApiError("ERR_INVALID_REQUEST", 400, "Request shape error"))


# ---------------------------------------------------------------------------
# Auth / role helpers
# ---------------------------------------------------------------------------

def require_roles(allowed):
    role = request.headers.get("X-User-Role")
    if role is None or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role")
    if role not in allowed:
        raise ApiError("ERR_ROLE_FORBIDDEN", 403, "Role not permitted to invoke this endpoint")
    return role


def user_id():
    return request.headers.get("X-User-ID")


def body_json():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def require_fields(data, spec):
    """spec: list of (name, type, required) where type is a Python type or tuple."""
    for name, typ, required in spec:
        if name not in data or data[name] is None:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {name}")
            continue
        v = data[name]
        if typ is str and not isinstance(v, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a string")
        if typ is int and (not isinstance(v, int) or isinstance(v, bool)):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an integer")
        if typ is bool and not isinstance(v, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a boolean")
        if typ is list and not isinstance(v, list):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an array")
        if typ is dict and not isinstance(v, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an object")


def require_enum(data, name, allowed, required=True):
    v = data.get(name)
    if v is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {name}")
        return None
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Common entity helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


_SEQ = {"n": 0}


def stamp(obj):
    """Set created_at/updated_at/version for a freshly created entity."""
    t = iso(now())
    obj["id"] = new_id()
    obj["created_at"] = t
    obj["updated_at"] = t
    obj["version"] = 1
    _SEQ["n"] += 1
    obj["_seq"] = _SEQ["n"]
    return obj


def touch(obj):
    """Bump updated_at and version on mutation."""
    obj["updated_at"] = iso(now())
    obj["version"] += 1


def get_or_404(store, key):
    obj = db[store].get(key)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return obj


def paginate(items):
    """Apply limit/offset pagination per PRD §2.3; items already sorted."""
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid pagination parameters")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    return page, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


def sorted_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Clock-driven lazy transitions (checked on reads)
# ---------------------------------------------------------------------------

def apply_clock_driven_transitions():
    """Apply time-based transitions for contracts and messages based on logical clock."""
    n = now()
    for c in list(db["contracts"].values()):
        if c["contract_status"] == "ACTIVE" and c.get("current_period_end"):
            end = parse_dt(c["current_period_end"])
            if n >= end - timedelta(days=7):
                c["contract_status"] = "RENEWAL_PENDING"
                touch(c)
        if c["contract_status"] == "RENEWAL_PENDING" and c.get("current_period_end"):
            end = parse_dt(c["current_period_end"])
            if n > end + timedelta(days=14):
                c["contract_status"] = "EXPIRED"
                touch(c)
                # Expiration cascade: every seat -> REVOKED
                for s in db["seats"].values():
                    if s["contract_id"] == c["id"] and s["seat_status"] in ("UNASSIGNED", "ASSIGNED", "SUSPENDED"):
                        _revoke_seat(s, expiration=True)
    # Message expiry: 30 days after SENT while AWAITING
    for m in db["messages"].values():
        if m["delivery_status"] == "SENT" and m["response_status"] == "AWAITING":
            sent_at = parse_dt(m["updated_at"]) if m.get("_sent_at") is None else parse_dt(m["_sent_at"])
            if n >= sent_at + timedelta(days=30):
                m["response_status"] = "EXPIRED"
                touch(m)


@app.before_request
def _before():
    apply_clock_driven_transitions()


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _pub(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def contract_out(c):
    return _pub(c)


def seat_out(s):
    return _pub(s)


def recruiter_out(r):
    return _pub(r)


def ledger_out(l):
    d = _pub(l)
    d["searches_remaining"] = max(0, l["search_quota_total"] - l["searches_used"])
    return d


def pool_out(p):
    d = _pub(p)
    d["credits_available"] = max(0, p["credits_granted"] - p["credits_used"] + p["credits_returned"])
    return d


def message_out(m):
    return _pub(m)


def candidate_out(c):
    return _pub(c)


def project_out(p):
    d = _pub(p)
    d["message_count"] = sum(
        1 for m in db["messages"].values()
        if m.get("project_id") == p["id"] and m["delivery_status"] == "SENT"
    )
    return d


def posting_out(p):
    return _pub(p)


def slot_out(s):
    return _pub(s)


def integration_out(i):
    return _pub(i)


def sync_record_out(r):
    return _pub(r)


def report_out(r):
    return _pub(r)


def renewal_out(e):
    return _pub(e)


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------

def contract_tier_fields(tier):
    return TIER_LIMITS[tier]


def current_ledger(seat_id, period_index):
    """Active (consumable) ledger for a seat in a period: OPEN or EXHAUSTED."""
    for l in db["quota_ledgers"].values():
        if l["seat_id"] == seat_id and l["period_index"] == period_index and l["ledger_status"] in ("OPEN", "EXHAUSTED"):
            return l
    return None


def current_pool(seat_id, period_index):
    """Active (consumable) pool for a seat in a period: OPEN or THROTTLED."""
    for p in db["credit_pools"].values():
        if p["seat_id"] == seat_id and p["period_index"] == period_index and p["pool_status"] in ("OPEN", "THROTTLED"):
            return p
    return None


def open_ledger(seat_id, period_index):
    for l in db["quota_ledgers"].values():
        if l["seat_id"] == seat_id and l["period_index"] == period_index and l["ledger_status"] == "OPEN":
            return l
    return None


def open_pool(seat_id, period_index):
    for p in db["credit_pools"].values():
        if p["seat_id"] == seat_id and p["period_index"] == period_index and p["pool_status"] in ("OPEN", "THROTTLED"):
            return p
    return None


def _revoke_seat(seat, expiration=False):
    """Seat -> REVOKED; closes ledgers and pools. expiration=True clears recruiter link."""
    if seat["seat_status"] == "ASSIGNED":
        recruiter = db["recruiters"].get(seat.get("assigned_recruiter_id"))
        if recruiter and recruiter.get("active_seat_id") == seat["id"]:
            recruiter["active_seat_id"] = None
            touch(recruiter)
        contract = db["contracts"].get(seat["contract_id"])
        if contract:
            contract["seats_assigned"] = max(0, contract["seats_assigned"] - 1)
    seat["assigned_recruiter_id"] = None
    seat["seat_status"] = "REVOKED"
    touch(seat)
    for l in db["quota_ledgers"].values():
        if l["seat_id"] == seat["id"] and l["ledger_status"] in ("OPEN", "EXHAUSTED"):
            l["ledger_status"] = "CLOSED"
            touch(l)
    for p in db["credit_pools"].values():
        if p["seat_id"] == seat["id"] and p["pool_status"] in ("OPEN", "THROTTLED"):
            p["pool_status"] = "CLOSED"
            touch(p)


def visibility_ok(candidate, seat):
    """§3.4 visibility rule."""
    if candidate["privacy_setting"] == "PUBLIC":
        return True
    if candidate["privacy_setting"] == "CONNECTIONS_ONLY":
        # Walk the manager chain upward from the seat's assigned recruiter;
        # visible if any manager in the chain is ACTIVE.
        rid = seat.get("assigned_recruiter_id")
        seen = set()
        while rid and rid not in seen:
            seen.add(rid)
            rec = db["recruiters"].get(rid)
            if rec is None:
                break
            rid = rec.get("manager_recruiter_id")
            if rid:
                mgr = db["recruiters"].get(rid)
                if mgr is not None and mgr["recruiter_status"] == "ACTIVE":
                    return True
        return False
    if candidate.get("open_to_work") and candidate.get("open_to_work_visibility") in ("ALL_MEMBERS", "RECRUITERS_ONLY"):
        return True
    return False


def filter_match(candidate, spec):
    if not spec:
        return True
    ct = spec.get("current_title")
    if ct is not None:
        if ct not in (candidate.get("current_title") or ""):
            return False
    mye = spec.get("min_years_experience")
    if mye is not None:
        if (candidate.get("years_experience") or 0) < mye:
            return False
    if spec.get("open_to_work_only") is True:
        if not candidate.get("open_to_work"):
            return False
    return True


def fingerprint(vendor, external_tenant_id, candidate_id, event_type, payload):
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    raw = "|".join([vendor, external_tenant_id, candidate_id, event_type, normalized])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ===========================================================================
# Contracts
# ===========================================================================

@app.route("/contracts", methods=["POST"])
def create_contract():
    require_roles(["ContractAdmin"])
    data = body_json()
    require_fields(data, [
        ("contract_number", str, True),
        ("seat_cap", int, True),
        ("true_up_allowed", bool, False),
    ])
    tier = require_enum(data, "product_tier", {"RECRUITER_LITE", "RECRUITER_PRO", "RECRUITER_CORP"})
    if data["seat_cap"] < 1 or data["seat_cap"] > 5000:
        raise ApiError("ERR_INVALID_REQUEST", 400, "seat_cap must be between 1 and 5000")
    for c in db["contracts"].values():
        if c["contract_number"] == data["contract_number"]:
            raise ApiError("ERR_DUPLICATE", 409, "contract_number must be unique")
    tf = contract_tier_fields(tier)
    c = stamp({
        "contract_number": data["contract_number"],
        "product_tier": tier,
        "seat_cap": data["seat_cap"],
        "seats_purchased": 0,
        "seats_assigned": 0,
        "monthly_credit_per_seat": tf["monthly_credit_per_seat"],
        "monthly_search_quota_per_seat": tf["monthly_search_quota_per_seat"],
        "search_result_page_cap": tf["search_result_page_cap"],
        "current_period_start": None,
        "current_period_end": None,
        "period_index": 0,
        "contract_status": "PENDING_ACTIVATION",
        "true_up_allowed": data.get("true_up_allowed", True),
    })
    db["contracts"][c["id"]] = c
    return success_envelope(contract_out(c), status=201)


@app.route("/contracts", methods=["GET"])
def list_contracts():
    require_roles(["ContractAdmin", "Auditor"])
    items = list(db["contracts"].values())
    tier = request.args.get("product_tier")
    if tier:
        items = [c for c in items if c["product_tier"] == tier]
    status = request.args.get("contract_status")
    if status:
        items = [c for c in items if c["contract_status"] == status]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([contract_out(c) for c in page], is_array=True, pagination=pag)


@app.route("/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    require_roles(["ContractAdmin", "SeatAdmin", "Auditor"])
    c = get_or_404("contracts", contract_id)
    return success_envelope(contract_out(c))


@app.route("/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    require_roles(["ContractAdmin"])
    data = body_json()
    require_fields(data, [("seats_purchased_initial", int, True)])
    c = get_or_404("contracts", contract_id)
    n_seats = data["seats_purchased_initial"]
    if c["contract_status"] != "PENDING_ACTIVATION" or n_seats < 1:
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be PENDING_ACTIVATION with seats_purchased_initial >= 1")
    if n_seats > c["seat_cap"]:
        raise ApiError("ERR_INVALID_STATE", 409, "seats_purchased_initial exceeds seat_cap")
    n = now()
    c["seats_purchased"] = n_seats
    c["current_period_start"] = iso(n)
    c["current_period_end"] = iso(n + timedelta(days=PERIOD_DAYS))
    c["period_index"] = 1
    c["contract_status"] = "ACTIVE"
    touch(c)
    for i in range(1, n_seats + 1):
        s = stamp({
            "contract_id": c["id"],
            "seat_label": f"SEAT-{i}",
            "seat_status": "UNASSIGNED",
            "assigned_recruiter_id": None,
            "assignment_started_at": None,
            "assignment_audit_count": 0,
            "last_period_credit_refresh": 0,
        })
        db["seats"][s["id"]] = s
    return success_envelope(contract_out(c))


@app.route("/contracts/<contract_id>/suspend", methods=["POST"])
def suspend_contract(contract_id):
    require_roles(["Auditor"])
    c = get_or_404("contracts", contract_id)
    if c["contract_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE to suspend")
    approved = any(
        e for e in db["renewal_events"].values()
        if e["contract_id"] == c["id"] and e["event_kind"] == "SUSPENSION" and e["event_status"] == "APPROVED"
    )
    if not approved:
        raise ApiError("ERR_INVALID_STATE", 409, "An APPROVED SUSPENSION renewal event is required")
    c["contract_status"] = "SUSPENDED"
    touch(c)
    for s in db["seats"].values():
        if s["contract_id"] == c["id"] and s["seat_status"] == "ASSIGNED":
            s["seat_status"] = "SUSPENDED"
            touch(s)
            for m in db["messages"].values():
                if m["seat_id"] == s["id"] and m["response_status"] == "AWAITING":
                    m["response_status"] = "EXPIRED"
                    touch(m)
    return success_envelope(contract_out(c))


@app.route("/contracts/<contract_id>/resume", methods=["POST"])
def resume_contract(contract_id):
    require_roles(["ContractAdmin"])
    c = get_or_404("contracts", contract_id)
    if c["contract_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be SUSPENDED to resume")
    c["contract_status"] = "ACTIVE"
    touch(c)
    for s in db["seats"].values():
        if s["contract_id"] == c["id"] and s["seat_status"] == "SUSPENDED":
            s["seat_status"] = "ASSIGNED"
            touch(s)
    return success_envelope(contract_out(c))


# ===========================================================================
# Seats
# ===========================================================================

@app.route("/contracts/<contract_id>/seats", methods=["GET"])
def list_seats(contract_id):
    require_roles(["ContractAdmin", "SeatAdmin", "Auditor"])
    c = get_or_404("contracts", contract_id)
    items = [s for s in db["seats"].values() if s["contract_id"] == c["id"]]
    st = request.args.get("seat_status")
    if st:
        items = [s for s in items if s["seat_status"] == st]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([seat_out(s) for s in page], is_array=True, pagination=pag)


@app.route("/contracts/<contract_id>/seats/<seat_id>", methods=["GET"])
def get_seat(contract_id, seat_id):
    require_roles(["ContractAdmin", "SeatAdmin", "Auditor", "RecruiterUser"])
    c = get_or_404("contracts", contract_id)
    s = get_or_404("seats", seat_id)
    if s["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Seat not found under contract")
    return success_envelope(seat_out(s))


@app.route("/seats/<seat_id>", methods=["GET"])
def get_seat_top(seat_id):
    require_roles(["ContractAdmin", "SeatAdmin", "Auditor", "RecruiterUser"])
    s = get_or_404("seats", seat_id)
    return success_envelope(seat_out(s))


@app.route("/contracts/<contract_id>/seats/<seat_id>/assign", methods=["POST"])
def assign_seat(contract_id, seat_id):
    require_roles(["SeatAdmin"])
    data = body_json()
    require_fields(data, [("recruiter_id", str, True), ("expected_seat_version", int, True)])
    c = get_or_404("contracts", contract_id)
    s = get_or_404("seats", seat_id)
    if s["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Seat not found under contract")
    recruiter = get_or_404("recruiters", data["recruiter_id"])
    # OCC check (priority 3.5) before state checks
    if data["expected_seat_version"] != s["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_seat_version does not match current seat version")
    if c["contract_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE")
    if recruiter["recruiter_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Recruiter must be ACTIVE")
    # Priority 7: recruiter already seated
    if recruiter.get("active_seat_id") is not None:
        raise ApiError("ERR_RECRUITER_ALREADY_SEATED", 409, "Recruiter already holds a seat")
    # Priority 8: seat not available
    if s["seat_status"] != "UNASSIGNED" or s.get("assigned_recruiter_id") is not None:
        raise ApiError("ERR_SEAT_NOT_AVAILABLE", 409, "Seat is not UNASSIGNED")
    # Apply
    s["assigned_recruiter_id"] = recruiter["id"]
    s["assignment_started_at"] = iso(now())
    s["assignment_audit_count"] += 1
    s["seat_status"] = "ASSIGNED"
    touch(s)
    recruiter["active_seat_id"] = s["id"]
    touch(recruiter)
    c["seats_assigned"] += 1
    # Create period-scoped ledger/pool if no OPEN one exists at current period
    if open_ledger(s["id"], c["period_index"]) is None:
        l = stamp({
            "seat_id": s["id"],
            "period_index": c["period_index"],
            "search_quota_total": c["monthly_search_quota_per_seat"],
            "searches_used": 0,
            "ledger_status": "OPEN",
        })
        db["quota_ledgers"][l["id"]] = l
    if open_pool(s["id"], c["period_index"]) is None:
        p = stamp({
            "seat_id": s["id"],
            "period_index": c["period_index"],
            "credits_granted": c["monthly_credit_per_seat"],
            "credits_used": 0,
            "credits_returned": 0,
            "spam_strike_count": 0,
            "pool_status": "OPEN",
        })
        db["credit_pools"][p["id"]] = p
        s["last_period_credit_refresh"] = c["period_index"]
    return success_envelope(seat_out(s))


@app.route("/contracts/<contract_id>/seats/<seat_id>/unassign", methods=["POST"])
def unassign_seat(contract_id, seat_id):
    require_roles(["SeatAdmin"])
    c = get_or_404("contracts", contract_id)
    s = get_or_404("seats", seat_id)
    if s["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Seat not found under contract")
    if c["contract_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE")
    if s["seat_status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Seat must be ASSIGNED to unassign")
    recruiter = db["recruiters"].get(s.get("assigned_recruiter_id"))
    if recruiter:
        recruiter["active_seat_id"] = None
        touch(recruiter)
    s["assigned_recruiter_id"] = None
    s["assignment_started_at"] = None
    s["seat_status"] = "UNASSIGNED"
    touch(s)
    c["seats_assigned"] = max(0, c["seats_assigned"] - 1)
    return success_envelope(seat_out(s))


@app.route("/contracts/<contract_id>/seats/<seat_id>/suspend", methods=["POST"])
def suspend_seat(contract_id, seat_id):
    require_roles(["SeatAdmin"])
    c = get_or_404("contracts", contract_id)
    s = get_or_404("seats", seat_id)
    if s["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Seat not found under contract")
    if s["seat_status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Seat must be ASSIGNED to suspend")
    s["seat_status"] = "SUSPENDED"
    touch(s)
    for m in db["messages"].values():
        if m["seat_id"] == s["id"] and m["response_status"] == "AWAITING":
            m["response_status"] = "EXPIRED"
            touch(m)
    return success_envelope(seat_out(s))


@app.route("/contracts/<contract_id>/seats/<seat_id>/resume", methods=["POST"])
def resume_seat(contract_id, seat_id):
    require_roles(["SeatAdmin"])
    c = get_or_404("contracts", contract_id)
    s = get_or_404("seats", seat_id)
    if s["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Seat not found under contract")
    if s["seat_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Seat must be SUSPENDED to resume")
    if c["contract_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE")
    s["seat_status"] = "ASSIGNED"
    touch(s)
    return success_envelope(seat_out(s))


# ===========================================================================
# Recruiters
# ===========================================================================

@app.route("/recruiters", methods=["POST"])
def create_recruiter():
    require_roles(["ContractAdmin"])
    data = body_json()
    require_fields(data, [
        ("email", str, True),
        ("full_name", str, True),
        ("home_contract_id", str, True),
        ("manager_recruiter_id", str, False),
    ])
    email = data["email"].lower()
    contract = db["contracts"].get(data["home_contract_id"])
    if contract is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "home_contract_id does not resolve")
    mgr_id = data.get("manager_recruiter_id")
    if mgr_id is not None:
        mgr = db["recruiters"].get(mgr_id)
        if mgr is None or mgr["recruiter_status"] != "ACTIVE":
            raise ApiError("ERR_MANAGER_INACTIVE", 422, "manager_recruiter_id must reference an ACTIVE recruiter")
    for r in db["recruiters"].values():
        if r["email"] == email:
            raise ApiError("ERR_DUPLICATE", 409, "email must be unique")
    r = stamp({
        "email": email,
        "full_name": data["full_name"],
        "manager_recruiter_id": mgr_id,
        "recruiter_status": "ACTIVE",
        "home_contract_id": contract["id"],
        "active_seat_id": None,
    })
    db["recruiters"][r["id"]] = r
    return success_envelope(recruiter_out(r), status=201)


@app.route("/recruiters/<recruiter_id>", methods=["GET"])
def get_recruiter(recruiter_id):
    require_roles(["ContractAdmin", "SeatAdmin", "Auditor"])
    r = get_or_404("recruiters", recruiter_id)
    return success_envelope(recruiter_out(r))


@app.route("/recruiters", methods=["GET"])
def list_recruiters():
    require_roles(["ContractAdmin", "SeatAdmin", "Auditor"])
    items = list(db["recruiters"].values())
    st = request.args.get("recruiter_status")
    if st:
        items = [r for r in items if r["recruiter_status"] == st]
    else:
        items = [r for r in items if r["recruiter_status"] != "DEACTIVATED"]
    hc = request.args.get("home_contract_id")
    if hc:
        items = [r for r in items if r["home_contract_id"] == hc]
    mgr = request.args.get("manager_recruiter_id")
    if mgr:
        items = [r for r in items if r.get("manager_recruiter_id") == mgr]
    asid = request.args.get("active_seat_id")
    if asid:
        items = [r for r in items if r.get("active_seat_id") == asid]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([recruiter_out(r) for r in page], is_array=True, pagination=pag)


@app.route("/recruiters/<recruiter_id>/deactivate", methods=["POST"])
def deactivate_recruiter(recruiter_id):
    require_roles(["ContractAdmin"])
    r = get_or_404("recruiters", recruiter_id)
    if r["recruiter_status"] == "DEACTIVATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Recruiter already deactivated")
    if r.get("active_seat_id"):
        s = db["seats"].get(r["active_seat_id"])
        if s:
            c = db["contracts"].get(s["contract_id"])
            s["assigned_recruiter_id"] = None
            s["assignment_started_at"] = None
            s["seat_status"] = "UNASSIGNED"
            touch(s)
            if c:
                c["seats_assigned"] = max(0, c["seats_assigned"] - 1)
    r["active_seat_id"] = None
    r["recruiter_status"] = "DEACTIVATED"
    touch(r)
    return success_envelope(recruiter_out(r))


# ===========================================================================
# Quota ledgers & credit pools (introspection)
# ===========================================================================

@app.route("/seats/<seat_id>/quota-ledgers", methods=["GET"])
def list_quota_ledgers(seat_id):
    require_roles(["SeatAdmin", "RecruiterUser", "Auditor"])
    s = get_or_404("seats", seat_id)
    items = [l for l in db["quota_ledgers"].values() if l["seat_id"] == s["id"]]
    pi = request.args.get("period_index")
    if pi is not None:
        try:
            pi = int(pi)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "period_index must be an integer")
        items = [l for l in items if l["period_index"] == pi]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([ledger_out(l) for l in page], is_array=True, pagination=pag)


@app.route("/seats/<seat_id>/credit-pools", methods=["GET"])
def list_credit_pools(seat_id):
    require_roles(["SeatAdmin", "RecruiterUser", "Auditor"])
    s = get_or_404("seats", seat_id)
    items = [p for p in db["credit_pools"].values() if p["seat_id"] == s["id"]]
    pi = request.args.get("period_index")
    if pi is not None:
        try:
            pi = int(pi)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "period_index must be an integer")
        items = [p for p in items if p["period_index"] == pi]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([pool_out(p) for p in page], is_array=True, pagination=pag)


# ===========================================================================
# Candidate profiles & search
# ===========================================================================

@app.route("/candidate-profiles", methods=["POST"])
def create_candidate():
    require_roles(["ContractAdmin"])
    data = body_json()
    require_fields(data, [
        ("member_id", str, True),
        ("full_name", str, True),
        ("headline", str, True),
        ("open_to_work", bool, True),
        ("years_experience", int, True),
        ("current_title", str, True),
    ])
    privacy = require_enum(data, "privacy_setting", {"PUBLIC", "CONNECTIONS_ONLY", "PRIVATE"})
    otw_vis = require_enum(data, "open_to_work_visibility", {"ALL_MEMBERS", "RECRUITERS_ONLY", "NONE"})
    for c in db["candidates"].values():
        if c["member_id"] == data["member_id"]:
            raise ApiError("ERR_DUPLICATE", 409, "member_id must be unique")
    c = stamp({
        "member_id": data["member_id"],
        "full_name": data["full_name"],
        "headline": data["headline"],
        "privacy_setting": privacy,
        "open_to_work": data["open_to_work"],
        "open_to_work_visibility": otw_vis,
        "years_experience": data["years_experience"],
        "current_title": data["current_title"],
    })
    db["candidates"][c["id"]] = c
    return success_envelope(candidate_out(c), status=201)


@app.route("/candidate-profiles/<candidate_id>", methods=["GET"])
def get_candidate(candidate_id):
    require_roles(["ContractAdmin", "SeatAdmin", "RecruiterUser", "Auditor"])
    c = get_or_404("candidates", candidate_id)
    return success_envelope(candidate_out(c))


@app.route("/candidate-profiles/<candidate_id>/messages", methods=["GET"])
def candidate_messages(candidate_id):
    require_roles(["ContractAdmin", "Auditor"])
    c = get_or_404("candidates", candidate_id)
    items = [m for m in db["messages"].values() if m.get("candidate_id") == c["id"]]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([message_out(m) for m in page], is_array=True, pagination=pag)


@app.route("/seats/<seat_id>/candidate-search", methods=["POST"])
def candidate_search(seat_id):
    role = require_roles(["RecruiterUser", "SeatAdmin"])
    data = body_json()
    spec = data.get("filter_spec")
    if spec is not None and not isinstance(spec, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "filter_spec must be an object")
    s = get_or_404("seats", seat_id)
    c = get_or_404("contracts", s["contract_id"])
    # 4.1: seat must be ASSIGNED
    if s["seat_status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Seat must be ASSIGNED to consume search quota")
    # 4.2: RecruiterUser ownership
    if role == "RecruiterUser" and user_id() != s.get("assigned_recruiter_id"):
        raise ApiError("ERR_ROLE_FORBIDDEN", 403, "RecruiterUser must own the seat")
    # 12: quota
    ledger = current_ledger(s["id"], c["period_index"])
    if ledger is None or (ledger["search_quota_total"] - ledger["searches_used"]) < 1:
        raise ApiError("ERR_QUOTA_EXHAUSTED", 402, "Search quota exhausted")
    visible = [cand for cand in db["candidates"].values() if visibility_ok(cand, s)]
    matched = [cand for cand in visible if filter_match(cand, spec)]
    matched = sorted_created(matched)
    cap = c["search_result_page_cap"]
    results = matched[:cap]
    ledger["searches_used"] += 1
    if ledger["searches_used"] >= ledger["search_quota_total"]:
        ledger["ledger_status"] = "EXHAUSTED"
    touch(ledger)
    return success_envelope([candidate_out(x) for x in results], is_array=True)


# ===========================================================================
# Projects
# ===========================================================================

@app.route("/contracts/<contract_id>/projects", methods=["POST"])
def create_project(contract_id):
    require_roles(["SeatAdmin"])
    data = body_json()
    require_fields(data, [
        ("name", str, True),
        ("owner_seat_id", str, True),
        ("pinned_candidate_ids", list, False),
    ])
    c = get_or_404("contracts", contract_id)
    seat = db["seats"].get(data["owner_seat_id"])
    if seat is None or seat["contract_id"] != c["id"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "owner_seat_id must reference a seat on this contract")
    pinned = data.get("pinned_candidate_ids") or []
    if len(pinned) > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "pinned_candidate_ids capped at 100")
    for p in db["projects"].values():
        if p["contract_id"] == c["id"] and p["name"] == data["name"]:
            raise ApiError("ERR_DUPLICATE", 409, "Project name must be unique within contract")
    p = stamp({
        "contract_id": c["id"],
        "owner_seat_id": seat["id"],
        "name": data["name"],
        "project_status": "DRAFT",
        "pinned_candidate_ids": list(pinned),
    })
    db["projects"][p["id"]] = p
    return success_envelope(project_out(p), status=201)


@app.route("/contracts/<contract_id>/projects", methods=["GET"])
def list_projects(contract_id):
    require_roles(["SeatAdmin", "RecruiterUser", "Auditor"])
    c = get_or_404("contracts", contract_id)
    items = [p for p in db["projects"].values() if p["contract_id"] == c["id"]]
    st = request.args.get("project_status")
    if st:
        items = [p for p in items if p["project_status"] == st]
    ow = request.args.get("owner_seat_id")
    if ow:
        items = [p for p in items if p["owner_seat_id"] == ow]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([project_out(p) for p in page], is_array=True, pagination=pag)


@app.route("/contracts/<contract_id>/projects/<project_id>", methods=["GET"])
def get_project(contract_id, project_id):
    require_roles(["SeatAdmin", "RecruiterUser", "Auditor"])
    c = get_or_404("contracts", contract_id)
    p = get_or_404("projects", project_id)
    if p["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Project not found under contract")
    return success_envelope(project_out(p))


@app.route("/projects/<project_id>", methods=["GET"])
def get_project_top(project_id):
    require_roles(["SeatAdmin", "RecruiterUser", "Auditor"])
    p = get_or_404("projects", project_id)
    return success_envelope(project_out(p))


@app.route("/projects/<project_id>/open", methods=["POST"])
def open_project(project_id):
    require_roles(["SeatAdmin"])
    p = get_or_404("projects", project_id)
    c = get_or_404("contracts", p["contract_id"])
    if p["project_status"] not in ("DRAFT", "ON_HOLD"):
        raise ApiError("ERR_INVALID_STATE", 409, "Project must be DRAFT or ON_HOLD to open")
    if c["contract_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE")
    if p["project_status"] == "DRAFT":
        seat = db["seats"].get(p["owner_seat_id"])
        if seat is None or seat["seat_status"] != "ASSIGNED" or seat["contract_id"] != c["id"]:
            raise ApiError("ERR_INVALID_STATE", 409, "owner_seat_id must reference an ASSIGNED seat on this contract")
    p["project_status"] = "OPEN"
    touch(p)
    return success_envelope(project_out(p))


@app.route("/projects/<project_id>/hold", methods=["POST"])
def hold_project(project_id):
    require_roles(["SeatAdmin"])
    p = get_or_404("projects", project_id)
    if p["project_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Project must be OPEN to hold")
    p["project_status"] = "ON_HOLD"
    touch(p)
    return success_envelope(project_out(p))


@app.route("/projects/<project_id>/close", methods=["POST"])
def close_project(project_id):
    require_roles(["SeatAdmin"])
    p = get_or_404("projects", project_id)
    if p["project_status"] not in ("OPEN", "ON_HOLD"):
        raise ApiError("ERR_INVALID_STATE", 409, "Project must be OPEN or ON_HOLD to close")
    p["project_status"] = "CLOSED"
    touch(p)
    return success_envelope(project_out(p))


@app.route("/seats/<seat_id>/projects", methods=["GET"])
def seat_projects(seat_id):
    require_roles(["SeatAdmin", "RecruiterUser", "Auditor"])
    s = get_or_404("seats", seat_id)
    items = [p for p in db["projects"].values() if p["owner_seat_id"] == s["id"]]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([project_out(p) for p in page], is_array=True, pagination=pag)


# ===========================================================================
# Messages
# ===========================================================================

@app.route("/seats/<seat_id>/messages", methods=["POST"])
def send_message(seat_id):
    role = require_roles(["RecruiterUser", "SeatAdmin"])
    data = body_json()
    require_fields(data, [
        ("candidate_id", str, True),
        ("project_id", str, True),
        ("body", str, True),
        ("job_posting_id", str, False),
    ])
    s = get_or_404("seats", seat_id)
    c = get_or_404("contracts", s["contract_id"])
    candidate = get_or_404("candidates", data["candidate_id"])
    project = db["projects"].get(data["project_id"])
    if project is None:
        raise ApiError("ERR_NOT_FOUND", 404, "project_id does not resolve")
    jp = None
    if data.get("job_posting_id"):
        jp = db["job_postings"].get(data["job_posting_id"])
        if jp is None:
            raise ApiError("ERR_NOT_FOUND", 404, "job_posting_id does not resolve")
    # 4.1 seat state
    if s["seat_status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Seat must be ASSIGNED to send messages")
    # 4.2 RecruiterUser ownership
    if role == "RecruiterUser" and user_id() != s.get("assigned_recruiter_id"):
        raise ApiError("ERR_ROLE_FORBIDDEN", 403, "RecruiterUser must own the seat")
    pool = current_pool(s["id"], c["period_index"])
    # 5 anti-spam
    if pool is not None and pool["pool_status"] == "THROTTLED":
        raise ApiError("ERR_ANTISPAM_THROTTLED", 429, "Message credit pool is throttled")
    # 6 visibility
    if not visibility_ok(candidate, s):
        raise ApiError("ERR_CANDIDATE_NOT_VISIBLE", 403, "Candidate not visible to this recruiter")
    # Credit accounting
    free_send = candidate.get("open_to_work") and candidate.get("open_to_work_visibility") == "ALL_MEMBERS"
    credit_consumed = 0 if free_send else 1
    if credit_consumed == 1:
        avail = 0 if pool is None else max(0, pool["credits_granted"] - pool["credits_used"] + pool["credits_returned"])
        if avail < 1:
            raise ApiError("ERR_NO_CREDITS_REMAINING", 402, "No message credits remaining")
    # Dispatch: fails when PRIVATE and not open-to-work-visible
    dispatch_ok = not (candidate["privacy_setting"] == "PRIVATE" and not (
        candidate.get("open_to_work") and candidate.get("open_to_work_visibility") in ("ALL_MEMBERS", "RECRUITERS_ONLY")))
    m = stamp({
        "seat_id": s["id"],
        "candidate_id": candidate["id"],
        "project_id": project["id"],
        "job_posting_id": jp["id"] if jp else None,
        "body": data["body"],
        "delivery_status": "PENDING",
        "response_status": "AWAITING",
        "credit_consumed": credit_consumed,
        "credit_returned_flag": False,
        "_sent_at": None,
        "_sent_while_pool_open": pool is not None and pool["pool_status"] == "OPEN",
    })
    if dispatch_ok:
        m["delivery_status"] = "SENT"
        m["_sent_at"] = iso(now())
        if credit_consumed == 1 and pool is not None:
            pool["credits_used"] += 1
            touch(pool)
    else:
        m["delivery_status"] = "FAILED"
    db["messages"][m["id"]] = m
    return success_envelope(message_out(m), status=201)


@app.route("/messages/<message_id>", methods=["GET"])
def get_message(message_id):
    require_roles(["SeatAdmin", "RecruiterUser", "Auditor"])
    m = get_or_404("messages", message_id)
    return success_envelope(message_out(m))


@app.route("/messages", methods=["GET"])
def list_messages():
    require_roles(["SeatAdmin", "Auditor"])
    items = list(db["messages"].values())
    pj = request.args.get("project_id")
    if pj:
        items = [m for m in items if m.get("project_id") == pj]
    jp = request.args.get("job_posting_id")
    if jp:
        items = [m for m in items if m.get("job_posting_id") == jp]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([message_out(m) for m in page], is_array=True, pagination=pag)


@app.route("/seats/<seat_id>/messages", methods=["GET"])
def seat_messages(seat_id):
    require_roles(["SeatAdmin", "RecruiterUser", "Auditor"])
    s = get_or_404("seats", seat_id)
    items = [m for m in db["messages"].values() if m["seat_id"] == s["id"]]
    ds = request.args.get("delivery_status")
    if ds:
        items = [m for m in items if m["delivery_status"] == ds]
    rs = request.args.get("response_status")
    if rs:
        items = [m for m in items if m["response_status"] == rs]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([message_out(m) for m in page], is_array=True, pagination=pag)


@app.route("/messages/<message_id>/record-response", methods=["POST"])
def record_response(message_id):
    require_roles(["AtsService"])
    data = body_json()
    kind = require_enum(data, "response_kind", {"RESPONDED", "NEGATIVE_RESPONSE", "REPORTED_AS_SPAM"})
    m = get_or_404("messages", message_id)
    if m["delivery_status"] != "SENT" or m["response_status"] != "AWAITING":
        raise ApiError("ERR_INVALID_STATE", 409, "Message must be SENT and AWAITING")
    s = db["seats"].get(m["seat_id"])
    c = db["contracts"].get(s["contract_id"]) if s else None
    pool = current_pool(m["seat_id"], c["period_index"]) if c else None
    if kind == "RESPONDED":
        m["response_status"] = "RESPONDED"
        if m["credit_consumed"] == 1 and not m["credit_returned_flag"]:
            if pool is not None:
                pool["credits_returned"] += 1
                touch(pool)
            m["credit_returned_flag"] = True
        # spam-strike delta: -1 if sent while pool OPEN and count > 0
        if pool is not None and m.get("_sent_while_pool_open") and pool["spam_strike_count"] > 0:
            pool["spam_strike_count"] = max(0, pool["spam_strike_count"] - 1)
            touch(pool)
    elif kind == "NEGATIVE_RESPONSE":
        m["response_status"] = "NEGATIVE_RESPONSE"
        if pool is not None:
            pool["spam_strike_count"] += 1
            touch(pool)
    elif kind == "REPORTED_AS_SPAM":
        m["response_status"] = "REPORTED_AS_SPAM"
        if pool is not None:
            pool["spam_strike_count"] += 2
            touch(pool)
    touch(m)
    # throttle transitions
    if pool is not None:
        if pool["spam_strike_count"] >= THROTTLE_THRESHOLD and pool["pool_status"] == "OPEN":
            pool["pool_status"] = "THROTTLED"
            touch(pool)
        elif pool["spam_strike_count"] < THROTTLE_THRESHOLD and pool["pool_status"] == "THROTTLED":
            pool["pool_status"] = "OPEN"
            touch(pool)
    return success_envelope(message_out(m))


# ===========================================================================
# Job postings & promoted slots
# ===========================================================================

@app.route("/contracts/<contract_id>/job-postings", methods=["POST"])
def create_posting(contract_id):
    require_roles(["SeatAdmin"])
    data = body_json()
    require_fields(data, [
        ("title", str, True),
        ("budget_cents", int, True),
        ("daily_cap_cents", int, True),
        ("start_at", str, True),
        ("end_at", str, True),
        ("created_by_seat_id", str, True),
    ])
    pacing = require_enum(data, "pacing_mode", {"EVEN", "FRONT_LOADED"})
    c = get_or_404("contracts", contract_id)
    seat = db["seats"].get(data["created_by_seat_id"])
    if seat is None or seat["contract_id"] != c["id"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "created_by_seat_id must reference a seat on this contract")
    if data["budget_cents"] < 1000:
        raise ApiError("ERR_INVALID_REQUEST", 400, "budget_cents must be >= 1000")
    if data["daily_cap_cents"] < 100 or data["daily_cap_cents"] > data["budget_cents"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "daily_cap_cents must be >= 100 and <= budget_cents")
    start = parse_dt(data["start_at"])
    end = parse_dt(data["end_at"])
    if start is None or end is None or not (start < end) or (end - start) < timedelta(days=1):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "start_at must be before end_at by at least 1 day")
    p = stamp({
        "contract_id": c["id"],
        "created_by_seat_id": seat["id"],
        "title": data["title"],
        "budget_cents": data["budget_cents"],
        "daily_cap_cents": data["daily_cap_cents"],
        "pacing_mode": pacing,
        "start_at": iso(start),
        "end_at": iso(end),
        "spent_cents": 0,
        "posting_status": "DRAFT",
    })
    db["job_postings"][p["id"]] = p
    return success_envelope(posting_out(p), status=201)


@app.route("/contracts/<contract_id>/job-postings", methods=["GET"])
def list_postings(contract_id):
    require_roles(["SeatAdmin", "Auditor"])
    c = get_or_404("contracts", contract_id)
    items = [p for p in db["job_postings"].values() if p["contract_id"] == c["id"]]
    st = request.args.get("posting_status")
    if st:
        items = [p for p in items if p["posting_status"] == st]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([posting_out(p) for p in page], is_array=True, pagination=pag)


@app.route("/contracts/<contract_id>/job-postings/<job_posting_id>", methods=["GET"])
def get_posting(contract_id, job_posting_id):
    require_roles(["SeatAdmin", "RecruiterUser", "Auditor"])
    c = get_or_404("contracts", contract_id)
    p = get_or_404("job_postings", job_posting_id)
    if p["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Posting not found under contract")
    return success_envelope(posting_out(p))


@app.route("/job-postings/<job_posting_id>", methods=["GET"])
def get_posting_top(job_posting_id):
    require_roles(["SeatAdmin", "RecruiterUser", "Auditor"])
    p = get_or_404("job_postings", job_posting_id)
    return success_envelope(posting_out(p))


@app.route("/seats/<seat_id>/job-postings", methods=["GET"])
def seat_postings(seat_id):
    require_roles(["SeatAdmin", "Auditor"])
    s = get_or_404("seats", seat_id)
    items = [p for p in db["job_postings"].values() if p["created_by_seat_id"] == s["id"]]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([posting_out(p) for p in page], is_array=True, pagination=pag)


def _get_posting_scoped(contract_id, job_posting_id):
    c = get_or_404("contracts", contract_id)
    p = get_or_404("job_postings", job_posting_id)
    if p["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Posting not found under contract")
    return c, p


@app.route("/contracts/<contract_id>/job-postings/<job_posting_id>/activate", methods=["POST"])
def activate_posting(contract_id, job_posting_id):
    require_roles(["SeatAdmin"])
    c, p = _get_posting_scoped(contract_id, job_posting_id)
    if p["posting_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Posting must be DRAFT to activate")
    if c["contract_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE")
    slots = [s for s in db["promoted_slots"].values() if s["job_posting_id"] == p["id"] and s["slot_status"] in ("RESERVED", "CONFIRMED")]
    if not slots:
        raise ApiError("ERR_INVALID_STATE", 409, "At least one RESERVED or CONFIRMED promoted slot required")
    n = now()
    start = parse_dt(p["start_at"])
    end = parse_dt(p["end_at"])
    if not (start <= n < end):
        raise ApiError("ERR_INVALID_STATE", 409, "Current time must satisfy start_at <= now < end_at")
    p["posting_status"] = "ACTIVE"
    touch(p)
    return success_envelope(posting_out(p))


@app.route("/contracts/<contract_id>/job-postings/<job_posting_id>/pause", methods=["POST"])
def pause_posting(contract_id, job_posting_id):
    require_roles(["SeatAdmin"])
    c, p = _get_posting_scoped(contract_id, job_posting_id)
    if p["posting_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Posting must be ACTIVE to pause")
    p["posting_status"] = "PAUSED"
    touch(p)
    return success_envelope(posting_out(p))


@app.route("/contracts/<contract_id>/job-postings/<job_posting_id>/resume", methods=["POST"])
def resume_posting(contract_id, job_posting_id):
    require_roles(["SeatAdmin"])
    c, p = _get_posting_scoped(contract_id, job_posting_id)
    if p["posting_status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Posting must be PAUSED to resume")
    if p["spent_cents"] >= p["budget_cents"]:
        raise ApiError("ERR_INVALID_STATE", 409, "Budget exhausted")
    if now() >= parse_dt(p["end_at"]):
        raise ApiError("ERR_INVALID_STATE", 409, "Posting end has passed")
    p["posting_status"] = "ACTIVE"
    touch(p)
    return success_envelope(posting_out(p))


def _close_posting(p):
    p["posting_status"] = "CLOSED"
    touch(p)
    for s in db["promoted_slots"].values():
        if s["job_posting_id"] == p["id"] and s["slot_status"] == "RESERVED":
            s["slot_status"] = "RELEASED"
            touch(s)


@app.route("/contracts/<contract_id>/job-postings/<job_posting_id>/close", methods=["POST"])
def close_posting(contract_id, job_posting_id):
    require_roles(["SeatAdmin"])
    c, p = _get_posting_scoped(contract_id, job_posting_id)
    if p["posting_status"] not in ("ACTIVE", "PAUSED", "EXHAUSTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Posting cannot be closed from its current state")
    _close_posting(p)
    return success_envelope(posting_out(p))


@app.route("/contracts/<contract_id>/job-postings/<job_posting_id>/promoted-slots", methods=["POST"])
def create_slot(contract_id, job_posting_id):
    require_roles(["SeatAdmin"])
    data = body_json()
    require_fields(data, [("slot_date", str, True), ("reserved_cents", int, True)])
    c, p = _get_posting_scoped(contract_id, job_posting_id)
    if data["reserved_cents"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "reserved_cents must be >= 1")
    try:
        sd = parse_date(data["slot_date"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "slot_date must be YYYY-MM-DD")
    start_d = parse_dt(p["start_at"]).date()
    end_d = parse_dt(p["end_at"]).date()
    if not (start_d <= sd < end_d):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "slot_date outside posting date range")
    s = stamp({
        "job_posting_id": p["id"],
        "slot_date": data["slot_date"],
        "reserved_cents": data["reserved_cents"],
        "slot_status": "RESERVED",
    })
    db["promoted_slots"][s["id"]] = s
    return success_envelope(slot_out(s), status=201)


@app.route("/contracts/<contract_id>/job-postings/<job_posting_id>/promoted-slots", methods=["GET"])
def list_slots(contract_id, job_posting_id):
    require_roles(["SeatAdmin", "Auditor"])
    c, p = _get_posting_scoped(contract_id, job_posting_id)
    items = [s for s in db["promoted_slots"].values() if s["job_posting_id"] == p["id"]]
    st = request.args.get("slot_status")
    if st:
        items = [s for s in items if s["slot_status"] == st]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([slot_out(s) for s in page], is_array=True, pagination=pag)


@app.route("/job-postings/<job_posting_id>/promoted-slots", methods=["GET"])
def list_slots_top(job_posting_id):
    require_roles(["SeatAdmin", "Auditor"])
    p = get_or_404("job_postings", job_posting_id)
    items = [s for s in db["promoted_slots"].values() if s["job_posting_id"] == p["id"]]
    st = request.args.get("slot_status")
    if st:
        items = [s for s in items if s["slot_status"] == st]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([slot_out(s) for s in page], is_array=True, pagination=pag)


@app.route("/contracts/<contract_id>/job-postings/<job_posting_id>/record-spend", methods=["POST"])
def record_spend(contract_id, job_posting_id):
    require_roles(["SeatAdmin"])
    data = body_json()
    require_fields(data, [("amount_cents", int, True)])
    c, p = _get_posting_scoped(contract_id, job_posting_id)
    amount = data["amount_cents"]
    if p["posting_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Posting must be ACTIVE to record spend")
    start = parse_dt(p["start_at"])
    end = parse_dt(p["end_at"])
    total_days = max(1, (end - start).days)
    today = now().date()
    elapsed_days = (today - start.date()).days + 1
    elapsed_days = max(1, min(elapsed_days, total_days))
    budget = p["budget_cents"]
    if p["pacing_mode"] == "EVEN":
        cumulative_cap = (budget * elapsed_days) // total_days
    else:
        front_days = math.ceil(total_days / 2)
        if elapsed_days <= front_days:
            cumulative_cap = min(budget, (budget * 15 * elapsed_days) // (total_days * 10))
        else:
            num = budget * (15 * front_days + 5 * (elapsed_days - front_days))
            cumulative_cap = min(budget, num // (total_days * 10))
    if amount < 1 or amount > p["daily_cap_cents"] or (p["spent_cents"] + amount) > cumulative_cap or (p["spent_cents"] + amount) > budget:
        raise ApiError("ERR_PACING_VIOLATION", 422, "Spend event breaches pacing rule")
    p["spent_cents"] += amount
    if p["spent_cents"] >= budget:
        p["posting_status"] = "EXHAUSTED"
        for s in db["promoted_slots"].values():
            if s["job_posting_id"] == p["id"] and s["slot_status"] == "RESERVED":
                s["slot_status"] = "RELEASED"
                touch(s)
    touch(p)
    return success_envelope(posting_out(p))


# ===========================================================================
# ATS integrations & sync records
# ===========================================================================

@app.route("/contracts/<contract_id>/ats-integrations", methods=["POST"])
def create_integration(contract_id):
    require_roles(["ContractAdmin"])
    data = body_json()
    require_fields(data, [
        ("external_tenant_id", str, True),
        ("write_back_enabled", bool, False),
    ])
    vendor = require_enum(data, "vendor", {"GREENHOUSE", "LEVER", "WORKDAY", "ICIMS"})
    c = get_or_404("contracts", contract_id)
    for i in db["ats_integrations"].values():
        if i["contract_id"] == c["id"] and i["vendor"] == vendor and i["external_tenant_id"] == data["external_tenant_id"]:
            raise ApiError("ERR_DUPLICATE", 409, "vendor + external_tenant_id must be unique within contract")
    i = stamp({
        "contract_id": c["id"],
        "vendor": vendor,
        "external_tenant_id": data["external_tenant_id"],
        "write_back_enabled": data.get("write_back_enabled", True),
        "integration_status": "PROVISIONING",
    })
    db["ats_integrations"][i["id"]] = i
    return success_envelope(integration_out(i), status=201)


@app.route("/contracts/<contract_id>/ats-integrations", methods=["GET"])
def list_integrations(contract_id):
    require_roles(["ContractAdmin", "Auditor"])
    c = get_or_404("contracts", contract_id)
    items = [i for i in db["ats_integrations"].values() if i["contract_id"] == c["id"]]
    v = request.args.get("vendor")
    if v:
        items = [i for i in items if i["vendor"] == v]
    st = request.args.get("integration_status")
    if st:
        items = [i for i in items if i["integration_status"] == st]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([integration_out(i) for i in page], is_array=True, pagination=pag)


@app.route("/contracts/<contract_id>/ats-integrations/<integration_id>", methods=["GET"])
def get_integration(contract_id, integration_id):
    require_roles(["ContractAdmin", "Auditor"])
    c = get_or_404("contracts", contract_id)
    i = get_or_404("ats_integrations", integration_id)
    if i["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Integration not found under contract")
    return success_envelope(integration_out(i))


@app.route("/ats-integrations/<integration_id>", methods=["GET"])
def get_integration_top(integration_id):
    require_roles(["ContractAdmin", "Auditor"])
    i = get_or_404("ats_integrations", integration_id)
    return success_envelope(integration_out(i))


def _flush_queued_records(integration):
    """When an integration becomes CONNECTED, resolve QUEUED records."""
    if integration["integration_status"] != "CONNECTED" or not integration["write_back_enabled"]:
        return
    queued = sorted_created([
        r for r in db["ats_sync_records"].values()
        if r["ats_integration_id"] == integration["id"] and r["sync_status"] == "QUEUED"
    ])
    written_fps = {
        r["payload_fingerprint"]
        for r in db["ats_sync_records"].values()
        if r["ats_integration_id"] == integration["id"] and r["sync_status"] == "WRITTEN"
    }
    for r in queued:
        if r["payload_fingerprint"] in written_fps:
            r["sync_status"] = "DUPLICATE_SKIPPED"
            touch(r)
        else:
            r["sync_status"] = "WRITTEN"
            written_fps.add(r["payload_fingerprint"])
            touch(r)


@app.route("/contracts/<contract_id>/ats-integrations/<integration_id>/connect", methods=["POST"])
def connect_integration(contract_id, integration_id):
    require_roles(["ContractAdmin"])
    c = get_or_404("contracts", contract_id)
    i = get_or_404("ats_integrations", integration_id)
    if i["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Integration not found under contract")
    if i["integration_status"] not in ("PROVISIONING", "SYNC_ERROR"):
        raise ApiError("ERR_INVALID_STATE", 409, "Integration must be PROVISIONING or SYNC_ERROR to connect")
    if c["contract_status"] not in ("ACTIVE", "RENEWAL_PENDING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE or RENEWAL_PENDING")
    i["integration_status"] = "CONNECTED"
    touch(i)
    _flush_queued_records(i)
    return success_envelope(integration_out(i))


@app.route("/contracts/<contract_id>/ats-integrations/<integration_id>/disable", methods=["POST"])
def disable_integration(contract_id, integration_id):
    require_roles(["ContractAdmin"])
    c = get_or_404("contracts", contract_id)
    i = get_or_404("ats_integrations", integration_id)
    if i["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Integration not found under contract")
    if i["integration_status"] not in ("CONNECTED", "SYNC_ERROR"):
        raise ApiError("ERR_INVALID_STATE", 409, "Integration must be CONNECTED or SYNC_ERROR to disable")
    i["integration_status"] = "DISABLED"
    touch(i)
    for r in db["ats_sync_records"].values():
        if r["ats_integration_id"] == i["id"] and r["sync_status"] == "QUEUED":
            r["sync_status"] = "FAILED"
            touch(r)
    return success_envelope(integration_out(i))


@app.route("/ats-sync-records", methods=["POST"])
def create_sync_record():
    require_roles(["AtsService"])
    data = body_json()
    require_fields(data, [
        ("ats_integration_id", str, True),
        ("candidate_id", str, True),
        ("external_candidate_ref", str, True),
    ])
    event_type = require_enum(data, "event_type", {"APPLICATION_FORWARDED", "STAGE_CHANGED", "HIRED", "DISQUALIFIED"})
    if "payload" not in data or not isinstance(data["payload"], dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "payload must be an object")
    integration = get_or_404("ats_integrations", data["ats_integration_id"])
    candidate = get_or_404("candidates", data["candidate_id"])
    fp = fingerprint(integration["vendor"], integration["external_tenant_id"], candidate["id"], event_type, data["payload"])
    dup = any(
        r for r in db["ats_sync_records"].values()
        if r["ats_integration_id"] == integration["id"] and r["payload_fingerprint"] == fp and r["sync_status"] == "WRITTEN"
    )
    if dup:
        status = "DUPLICATE_SKIPPED"
    elif integration["integration_status"] == "CONNECTED" and integration["write_back_enabled"]:
        status = "WRITTEN"
    elif integration["integration_status"] == "DISABLED":
        status = "FAILED"
    else:
        status = "QUEUED"
    r = stamp({
        "ats_integration_id": integration["id"],
        "candidate_id": candidate["id"],
        "external_candidate_ref": data["external_candidate_ref"],
        "event_type": event_type,
        "payload_fingerprint": fp,
        "sync_status": status,
        "_payload": data["payload"],
    })
    db["ats_sync_records"][r["id"]] = r
    return success_envelope(sync_record_out(r), status=201)


@app.route("/ats-sync-records/<record_id>", methods=["GET"])
def get_sync_record(record_id):
    require_roles(["ContractAdmin", "Auditor"])
    r = get_or_404("ats_sync_records", record_id)
    return success_envelope(sync_record_out(r))


@app.route("/ats-sync-records", methods=["GET"])
def list_sync_records():
    require_roles(["ContractAdmin", "Auditor"])
    items = list(db["ats_sync_records"].values())
    iid = request.args.get("ats_integration_id")
    if iid:
        items = [r for r in items if r["ats_integration_id"] == iid]
    cid = request.args.get("candidate_id")
    if cid:
        items = [r for r in items if r["candidate_id"] == cid]
    st = request.args.get("sync_status")
    if st:
        items = [r for r in items if r["sync_status"] == st]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([sync_record_out(r) for r in page], is_array=True, pagination=pag)


# ===========================================================================
# Talent insights
# ===========================================================================

@app.route("/contracts/<contract_id>/talent-insights", methods=["POST"])
def create_report(contract_id):
    require_roles(["ContractAdmin"])
    data = body_json()
    require_fields(data, [("report_name", str, True), ("filter_spec", dict, True)])
    c = get_or_404("contracts", contract_id)
    r = stamp({
        "contract_id": c["id"],
        "report_name": data["report_name"],
        "filter_spec": data["filter_spec"],
        "matched_count": None,
        "aggregation_floor": AGGREGATION_FLOOR,
        "report_status": "DRAFT",
    })
    db["talent_reports"][r["id"]] = r
    return success_envelope(report_out(r), status=201)


@app.route("/contracts/<contract_id>/talent-insights", methods=["GET"])
def list_reports(contract_id):
    require_roles(["ContractAdmin", "Auditor"])
    c = get_or_404("contracts", contract_id)
    items = [r for r in db["talent_reports"].values() if r["contract_id"] == c["id"]]
    st = request.args.get("report_status")
    if st:
        items = [r for r in items if r["report_status"] == st]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([report_out(r) for r in page], is_array=True, pagination=pag)


@app.route("/contracts/<contract_id>/talent-insights/<report_id>", methods=["GET"])
def get_report(contract_id, report_id):
    require_roles(["ContractAdmin", "Auditor"])
    c = get_or_404("contracts", contract_id)
    r = get_or_404("talent_reports", report_id)
    if r["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Report not found under contract")
    return success_envelope(report_out(r))


def _compute_matched_count(report):
    """Visibility + filter logic, uncapped. Contract-scope reports have no
    specific requesting seat; treat as an unrestricted recruiter view where
    the CONNECTIONS_ONLY proxy uses any ACTIVE recruiter in the tenant."""
    count = 0
    for cand in db["candidates"].values():
        vis = False
        if cand["privacy_setting"] == "PUBLIC":
            vis = True
        elif cand["privacy_setting"] == "CONNECTIONS_ONLY":
            vis = any(r["recruiter_status"] == "ACTIVE" for r in db["recruiters"].values())
        elif cand.get("open_to_work") and cand.get("open_to_work_visibility") in ("ALL_MEMBERS", "RECRUITERS_ONLY"):
            vis = True
        if vis and filter_match(cand, report["filter_spec"]):
            count += 1
    return count


@app.route("/contracts/<contract_id>/talent-insights/<report_id>/generate", methods=["POST"])
def generate_report(contract_id, report_id):
    require_roles(["ContractAdmin"])
    c = get_or_404("contracts", contract_id)
    r = get_or_404("talent_reports", report_id)
    if r["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Report not found under contract")
    if r["report_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Report must be DRAFT to generate")
    if c["contract_status"] not in ("ACTIVE", "RENEWAL_PENDING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE or RENEWAL_PENDING")
    r["matched_count"] = _compute_matched_count(r)
    r["report_status"] = "GENERATED"
    touch(r)
    return success_envelope(report_out(r))


@app.route("/contracts/<contract_id>/talent-insights/<report_id>/publish", methods=["POST"])
def publish_report(contract_id, report_id):
    require_roles(["ContractAdmin"])
    c = get_or_404("contracts", contract_id)
    r = get_or_404("talent_reports", report_id)
    if r["contract_id"] != c["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Report not found under contract")
    if r["report_status"] != "GENERATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report must be GENERATED to publish")
    if (r.get("matched_count") or 0) < AGGREGATION_FLOOR:
        raise ApiError("ERR_AGGREGATION_FLOOR", 422, "matched_count below aggregation floor")
    r["report_status"] = "PUBLISHED"
    touch(r)
    return success_envelope(report_out(r))


# ===========================================================================
# Renewal events
# ===========================================================================

@app.route("/contracts/<contract_id>/renewal-events", methods=["POST"])
def create_renewal_event(contract_id):
    require_roles(["Auditor"])
    data = body_json()
    require_fields(data, [("expected_contract_version", int, True)])
    kind = require_enum(data, "event_kind", {"TRUE_UP", "RENEWAL", "SUSPENSION"})
    if "seats_delta" in data and data["seats_delta"] is not None and (not isinstance(data["seats_delta"], int) or isinstance(data["seats_delta"], bool)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "seats_delta must be an integer")
    c = get_or_404("contracts", contract_id)
    if data["expected_contract_version"] != c["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_contract_version does not match current contract version")
    e = stamp({
        "contract_id": c["id"],
        "event_kind": kind,
        "seats_delta": data.get("seats_delta"),
        "requested_by": user_id(),
        "event_status": "PROPOSED",
        "proration_credit_cents": None,
        "expected_contract_version": data["expected_contract_version"],
    })
    db["renewal_events"][e["id"]] = e
    touch(c)  # proposing increments contract version by 1
    return success_envelope(renewal_out(e), status=201)


@app.route("/renewal-events/<renewal_event_id>", methods=["GET"])
def get_renewal_event(renewal_event_id):
    require_roles(["Auditor", "ContractAdmin"])
    e = get_or_404("renewal_events", renewal_event_id)
    return success_envelope(renewal_out(e))


@app.route("/contracts/<contract_id>/renewal-events", methods=["GET"])
def list_renewal_events(contract_id):
    require_roles(["Auditor", "ContractAdmin"])
    c = get_or_404("contracts", contract_id)
    items = [e for e in db["renewal_events"].values() if e["contract_id"] == c["id"]]
    st = request.args.get("event_status")
    if st:
        items = [e for e in items if e["event_status"] == st]
    k = request.args.get("event_kind")
    if k:
        items = [e for e in items if e["event_kind"] == k]
    items = sorted_created(items)
    page, pag = paginate(items)
    return success_envelope([renewal_out(e) for e in page], is_array=True, pagination=pag)


@app.route("/renewal-events/<renewal_event_id>/approve", methods=["POST"])
def approve_renewal_event(renewal_event_id):
    require_roles(["Auditor"])
    e = get_or_404("renewal_events", renewal_event_id)
    c = get_or_404("contracts", e["contract_id"])
    if e["event_status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Event must be PROPOSED to approve")
    if c["contract_status"] not in ("ACTIVE", "RENEWAL_PENDING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE or RENEWAL_PENDING")
    if e["event_kind"] == "TRUE_UP":
        if not c.get("true_up_allowed", True):
            raise ApiError("ERR_INVALID_STATE", 409, "True-up not allowed on this contract")
        delta = e.get("seats_delta") or 0
        new_purchased = c["seats_purchased"] + delta
        if new_purchased < c["seats_assigned"] or new_purchased < 1 or new_purchased > c["seat_cap"]:
            raise ApiError("ERR_TRUEUP_BOUNDS", 422, "seats_purchased + seats_delta out of bounds")
        if delta < 0:
            n = now()
            end = parse_dt(c["current_period_end"])
            days_remaining = max(0, math.ceil((end - n).total_seconds() / 86400))
            days_elapsed = PERIOD_DAYS - days_remaining
            per_seat_cost = c["monthly_credit_per_seat"] * 100
            if c["product_tier"] == "RECRUITER_CORP":
                raw = Decimal(abs(delta) * per_seat_cost * days_elapsed) / Decimal(PERIOD_DAYS)
            else:
                raw = Decimal(abs(delta) * per_seat_cost * days_remaining) / Decimal(PERIOD_DAYS)
            e["proration_credit_cents"] = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    e["event_status"] = "APPROVED"
    touch(e)
    return success_envelope(renewal_out(e))


@app.route("/renewal-events/<renewal_event_id>/reject", methods=["POST"])
def reject_renewal_event(renewal_event_id):
    require_roles(["Auditor"])
    e = get_or_404("renewal_events", renewal_event_id)
    if e["event_status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Event must be PROPOSED to reject")
    e["event_status"] = "REJECTED"
    touch(e)
    return success_envelope(renewal_out(e))


@app.route("/renewal-events/<renewal_event_id>/apply", methods=["POST"])
def apply_renewal_event(renewal_event_id):
    require_roles(["Auditor"])
    e = get_or_404("renewal_events", renewal_event_id)
    c = get_or_404("contracts", e["contract_id"])
    if e["event_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Event must be APPROVED to apply")
    if e["event_kind"] == "SUSPENSION":
        if c["contract_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE to suspend")
        c["contract_status"] = "SUSPENDED"
        touch(c)
        for s in db["seats"].values():
            if s["contract_id"] == c["id"] and s["seat_status"] == "ASSIGNED":
                s["seat_status"] = "SUSPENDED"
                touch(s)
                for m in db["messages"].values():
                    if m["seat_id"] == s["id"] and m["response_status"] == "AWAITING":
                        m["response_status"] = "EXPIRED"
                        touch(m)
    elif e["event_kind"] == "RENEWAL":
        if c["contract_status"] != "RENEWAL_PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "Contract must be RENEWAL_PENDING to renew")
        prev_end = parse_dt(c["current_period_end"])
        c["period_index"] += 1
        c["current_period_start"] = iso(prev_end)
        c["current_period_end"] = iso(prev_end + timedelta(days=PERIOD_DAYS))
        c["contract_status"] = "ACTIVE"
        touch(c)
        for s in db["seats"].values():
            if s["contract_id"] != c["id"] or s["seat_status"] == "REVOKED":
                continue
            for l in db["quota_ledgers"].values():
                if l["seat_id"] == s["id"] and l["ledger_status"] in ("OPEN", "EXHAUSTED"):
                    l["ledger_status"] = "CLOSED"
                    touch(l)
            for p in db["credit_pools"].values():
                if p["seat_id"] == s["id"] and p["pool_status"] in ("OPEN", "THROTTLED"):
                    p["pool_status"] = "CLOSED"
                    touch(p)
            nl = stamp({
                "seat_id": s["id"],
                "period_index": c["period_index"],
                "search_quota_total": c["monthly_search_quota_per_seat"],
                "searches_used": 0,
                "ledger_status": "OPEN",
            })
            db["quota_ledgers"][nl["id"]] = nl
            np_ = stamp({
                "seat_id": s["id"],
                "period_index": c["period_index"],
                "credits_granted": c["monthly_credit_per_seat"],
                "credits_used": 0,
                "credits_returned": 0,
                "spam_strike_count": 0,
                "pool_status": "OPEN",
            })
            db["credit_pools"][np_["id"]] = np_
            s["last_period_credit_refresh"] = c["period_index"]
    elif e["event_kind"] == "TRUE_UP":
        if c["contract_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Contract must be ACTIVE to apply true-up")
        delta = e.get("seats_delta") or 0
        new_purchased = c["seats_purchased"] + delta
        if new_purchased < c["seats_assigned"] or new_purchased < 1 or new_purchased > c["seat_cap"]:
            raise ApiError("ERR_TRUEUP_BOUNDS", 422, "seats_purchased + seats_delta out of bounds")
        c["seats_purchased"] = new_purchased
        if delta > 0:
            existing_labels = {s["seat_label"] for s in db["seats"].values() if s["contract_id"] == c["id"]}
            seq = 0
            for _ in range(delta):
                seq += 1
                while f"SEAT-{seq}" in existing_labels:
                    seq += 1
                label = f"SEAT-{seq}"
                existing_labels.add(label)
                s = stamp({
                    "contract_id": c["id"],
                    "seat_label": label,
                    "seat_status": "UNASSIGNED",
                    "assigned_recruiter_id": None,
                    "assignment_started_at": None,
                    "assignment_audit_count": 0,
                    "last_period_credit_refresh": 0,
                })
                db["seats"][s["id"]] = s
        elif delta < 0:
            unassigned = sorted_created([
                s for s in db["seats"].values()
                if s["contract_id"] == c["id"] and s["seat_status"] == "UNASSIGNED"
            ])
            for s in unassigned[:abs(delta)]:
                _revoke_seat(s)
        touch(c)
    e["event_status"] = "APPLIED"
    touch(e)
    return success_envelope(renewal_out(e))


# ===========================================================================
# Logical clock
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(["ContractAdmin"])
    data = body_json()
    require_fields(data, [("to_iso8601", str, True)])
    t = parse_dt(data["to_iso8601"])
    if t is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO 8601 datetime")
    _LOGICAL_NOW["now"] = t
    apply_clock_driven_transitions()
    return success_envelope({"now_iso8601": iso(t)})


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
