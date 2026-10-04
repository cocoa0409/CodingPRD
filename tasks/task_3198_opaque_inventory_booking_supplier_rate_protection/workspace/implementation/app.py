"""Opaque Inventory Booking & Supplier Rate Protection API.

Single-file Flask implementation driven by PRD.md / SCAFFOLD.yaml.
The store is in-memory and starts empty on every boot.
"""

import math
import os
import secrets
import uuid
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
ROLES = {"PlatformAdmin", "Customer", "CustomerService", "FinanceOps"}

GOODWILL_SUPPLIER_THRESHOLD = 0.15  # strict >
REPEAT_WIN_THRESHOLD = 3
REPEAT_WIN_PENALTY = 25
WATCH_THRESHOLD = 20
BLOCKED_THRESHOLD = 50

E_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
E_PERM = "ERR_INSUFFICIENT_PERMISSIONS"
E_STATE = "ERR_INVALID_STATE"
E_REQ = "ERR_INVALID_REQUEST"
E_DATE = "ERR_INVALID_DATE_RANGE"
E_DISC = "ERR_DISCLOSURE_BOUNDARY_VIOLATION"
E_BLOCKED = "ERR_CUSTOMER_BLOCKED"
E_DUP_COMPLAINT = "ERR_DUPLICATE_COMPLAINT"
E_BID_FLOOR = "ERR_BID_BELOW_FLOOR"
E_GOODWILL = "ERR_INVALID_GOODWILL_AMOUNT"
E_OPEN_BATCH = "ERR_SUPPLIER_HAS_OPEN_BATCH"
E_STALE = "ERR_STALE_VERSION"
E_BATCH_EMPTY = "ERR_BATCH_EMPTY"

NOT_FOUND = {
    "suppliers": "ERR_SUPPLIER_NOT_FOUND",
    "properties": "ERR_PROPERTY_NOT_FOUND",
    "rate_windows": "ERR_RATE_WINDOW_NOT_FOUND",
    "disclosure_zones": "ERR_DISCLOSURE_ZONE_NOT_FOUND",
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "opaque_bids": "ERR_OPAQUE_BID_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "complaint_cases": "ERR_COMPLAINT_CASE_NOT_FOUND",
    "settlement_batches": "ERR_SETTLEMENT_BATCH_NOT_FOUND",
    "fraud_flags": "ERR_FRAUD_FLAG_NOT_FOUND",
}

# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot)
# ---------------------------------------------------------------------------

db = {
    "suppliers": {},
    "properties": {},
    "rate_windows": {},
    "disclosure_zones": {},
    "customers": {},
    "opaque_bids": {},
    "bookings": {},
    "complaint_cases": {},
    "settlement_batches": {},
    "fraud_flags": {},
}
logical_clock = None
_seq = 0


def _init_clock():
    global logical_clock
    logical_clock = datetime(2026, 9, 1, tzinfo=timezone.utc)


_init_clock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_ts():
    """ISO 8601 UTC timestamp with three fractional digits (logical clock)."""
    global _seq
    _seq += 1
    ts = logical_clock + timedelta(microseconds=_seq)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def wall_ts():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def round4(x):
    """Round half-up to 4 decimal places."""
    return math.floor(x * 10000 + 0.5) / 10000.0


def parse_dt(s):
    """Parse an ISO-8601 datetime/date string to an aware UTC datetime.

    Returns None on failure."""
    if not isinstance(s, str):
        return None
    v = s.strip()
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify({
        "meta": {"api_request_id": "req_" + secrets.token_hex(8),
                 "api_request_timestamp": wall_ts()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.status


@app.errorhandler(404)
def _nf(e):
    return jsonify({
        "meta": {"api_request_id": "req_" + secrets.token_hex(8),
                 "api_request_timestamp": wall_ts()},
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found"},
    }), 404


@app.errorhandler(405)
def _mna(e):
    return jsonify({
        "meta": {"api_request_id": "req_" + secrets.token_hex(8),
                 "api_request_timestamp": wall_ts()},
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }), 405


@app.errorhandler(Exception)
def _boom(e):
    return jsonify({
        "meta": {"api_request_id": "req_" + secrets.token_hex(8),
                 "api_request_timestamp": wall_ts()},
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }), 500


def ok_obj(data, code=200):
    return jsonify({
        "meta": {"api_request_id": "req_" + secrets.token_hex(8),
                 "api_request_timestamp": wall_ts()},
        "response_type": "object",
        "data": data,
    }), code


def ok_list(items):
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(E_REQ, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(E_REQ, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(E_REQ, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(E_REQ, 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return jsonify({
        "meta": {"api_request_id": "req_" + secrets.token_hex(8),
                 "api_request_timestamp": wall_ts(),
                 "limit": limit, "offset": offset,
                 "total_count": total, "has_more": offset + limit < total},
        "response_type": "array",
        "data": page,
    }), 200


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def auth(allowed_roles):
    """Validate auth headers and role permission; returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise ApiError(E_AUTH, 400, "X-User-ID header missing or malformed")
    if not role or role not in ROLES:
        raise ApiError(E_AUTH, 400, "X-User-Role header missing or malformed")
    if role not in allowed_roles:
        raise ApiError(E_PERM, 403, "Role not permitted for this operation")
    return uid, role


def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] += 1


def get_or_404(store_key, rid):
    rec = db[store_key].get(rid)
    if rec is None:
        raise ApiError(NOT_FOUND[store_key], 404,
                       f"{store_key} {rid} does not exist")
    return rec


def sorted_items(store_key):
    return sorted(db[store_key].values(), key=lambda r: r["created_at"])


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def pub_supplier(s):
    return {k: s[k] for k in (
        "id", "legal_name", "opaque_commission_pct", "parity_protection_enabled",
        "concealment_discount_min_pct", "status", "created_at", "updated_at",
        "version")}


def pub_property(p):
    return {k: p[k] for k in (
        "id", "supplier_id", "brand_name", "star_rating", "neighborhood_code",
        "amenity_codes", "published_rate_cents", "created_at", "updated_at",
        "version")}


def pub_window(w):
    return {k: w[k] for k in (
        "id", "property_id", "check_in_date", "check_out_date",
        "opaque_rate_cents", "rooms_allocated", "rooms_sold", "status",
        "created_at", "updated_at", "version")}


def pub_zone(z):
    return {k: z[k] for k in (
        "id", "neighborhood_code", "min_star_rating", "revealed_amenity_codes",
        "created_at", "updated_at", "version")}


def pub_customer(c):
    return {k: c[k] for k in (
        "id", "email", "full_name", "fraud_score", "fraud_status",
        "opaque_win_count_30d", "created_at", "updated_at", "version")}


def pub_bid(b):
    return {k: b[k] for k in (
        "id", "customer_id", "neighborhood_code", "min_star_rating",
        "check_in_date", "check_out_date", "bid_price_cents", "offer_mode",
        "computed_price_cents", "winning_property_id",
        "winning_rate_window_id", "concealment_discount_pct", "status",
        "required_amenity_codes", "created_at", "updated_at", "version")}


def pub_booking(b):
    return {k: b[k] for k in (
        "id", "opaque_bid_id", "customer_id", "property_id", "supplier_id",
        "rate_window_id", "check_in_date", "check_out_date",
        "charged_price_cents", "supplier_remittance_cents",
        "platform_commission_cents", "payment_status", "fulfillment_status",
        "created_at", "updated_at", "version")}


def pub_case(c):
    return {k: c[k] for k in (
        "id", "booking_id", "customer_id", "category", "description",
        "resolution", "goodwill_credit_cents", "status", "created_at",
        "updated_at", "version")}


def pub_batch(b):
    return {k: b[k] for k in (
        "id", "supplier_id", "period_start_date", "period_end_date",
        "booking_ids", "gross_remittance_cents", "goodwill_deduction_cents",
        "net_remittance_cents", "status", "created_at", "updated_at",
        "version")}


def pub_flag(f):
    return {k: f[k] for k in (
        "id", "customer_id", "booking_id", "reason_code", "score_delta",
        "status", "created_at", "updated_at", "version")}


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def date_only(rec, field):
    """Parse a stored date-only field to an aware UTC datetime."""
    return parse_dt(rec[field])


def find_zone(neighborhood_code):
    for z in db["disclosure_zones"].values():
        if z["neighborhood_code"] == neighborhood_code:
            return z
    return None


def nights_between(ci, co):
    return (co - ci).days


def candidate_set(bid):
    """Eligible (property, window) pairs for a bid. Returns list of tuples."""
    ci = date_only(bid, "check_in_date")
    co = date_only(bid, "check_out_date")
    zone = find_zone(bid["neighborhood_code"])
    revealed = set(zone["revealed_amenity_codes"]) if zone else set()
    required = bid.get("required_amenity_codes") or []
    out = []
    for p in db["properties"].values():
        if p["neighborhood_code"] != bid["neighborhood_code"]:
            continue
        if p["star_rating"] < bid["min_star_rating"]:
            continue
        supplier = db["suppliers"].get(p["supplier_id"])
        if supplier is None or supplier["status"] != "ACTIVE":
            continue
        if required:
            pamen = set(p["amenity_codes"])
            if not all(a in pamen and a in revealed for a in required):
                continue
        for w in db["rate_windows"].values():
            if w["property_id"] != p["id"]:
                continue
            if w["status"] != "OPEN":
                continue
            wci = date_only(w, "check_in_date")
            wco = date_only(w, "check_out_date")
            if not (wci <= ci and wco >= co):
                continue
            if not (w["rooms_sold"] < w["rooms_allocated"]):
                continue
            out.append((p, w))
    return out


def compute_price_floor(bid):
    """Bid-level computed_price_cents: min over candidates of per-candidate
    floor. Returns None when no candidates exist."""
    n = nights_between(date_only(bid, "check_in_date"),
                       date_only(bid, "check_out_date"))
    floors = []
    for p, w in candidate_set(bid):
        supplier = db["suppliers"][p["supplier_id"]]
        base = w["opaque_rate_cents"] * n
        floor_price = math.ceil(base * (1 - supplier["concealment_discount_min_pct"]))
        floors.append(floor_price)
    return min(floors) if floors else None


def select_winner(bid):
    cands = candidate_set(bid)
    if not cands:
        return None
    cands.sort(key=lambda pw: (
        pw[1]["opaque_rate_cents"],
        -pw[0]["published_rate_cents"],
        pw[1]["created_at"],
        pw[0]["created_at"],
    ))
    return cands[0]


def recompute_fraud_status(customer):
    score = customer["fraud_score"]
    if score >= BLOCKED_THRESHOLD:
        customer["fraud_status"] = "BLOCKED"
    elif score >= WATCH_THRESHOLD:
        customer["fraud_status"] = "WATCH"
    else:
        customer["fraud_status"] = "CLEAR"


def win_count_30d(customer_id):
    lo = logical_clock - timedelta(days=30)
    n = 0
    for b in db["opaque_bids"].values():
        if b["customer_id"] != customer_id or b["status"] != "ACCEPTED":
            continue
        created = parse_dt(b["created_at"])
        if lo <= created <= logical_clock:
            n += 1
    return n


def goodwill_for_booking(booking_id):
    """Return the goodwill_credit_cents of the linked RESOLVED GOODWILL_CREDIT
    complaint case for this booking, else 0."""
    for c in db["complaint_cases"].values():
        if (c["booking_id"] == booking_id and c["status"] == "RESOLVED"
                and c["resolution"] == "GOODWILL_CREDIT"):
            return c["goodwill_credit_cents"]
    return 0


def chargeback_applies(booking):
    gw = goodwill_for_booking(booking["id"])
    if gw <= 0:
        return False, 0
    ratio = round4(gw / booking["charged_price_cents"])
    return ratio > GOODWILL_SUPPLIER_THRESHOLD, gw


def run_settlement_selection(batch):
    bids = [b for b in db["bookings"].values()
            if b["supplier_id"] == batch["supplier_id"]
            and b["fulfillment_status"] == "CONFIRMED"
            and date_only(b, "check_out_date") >= date_only(batch, "period_start_date")
            and date_only(b, "check_out_date") < date_only(batch, "period_end_date")]
    bids.sort(key=lambda b: (date_only(b, "check_out_date"), b["created_at"]))
    batch["booking_ids"] = [b["id"] for b in bids]
    gross = 0
    deduction = 0
    for b in bids:
        gross += b["supplier_remittance_cents"]
        applies, gw = chargeback_applies(b)
        if applies:
            deduction += gw
    batch["gross_remittance_cents"] = gross
    batch["goodwill_deduction_cents"] = deduction
    batch["net_remittance_cents"] = gross - deduction


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@app.post("/_clock/set_current_utc")
def set_clock():
    auth(["PlatformAdmin"])
    b = body()
    cur = parse_dt(b.get("current_utc"))
    if cur is None:
        raise ApiError(E_REQ, 400, "current_utc must be an ISO-8601 timestamp")
    global logical_clock
    logical_clock = cur
    # Re-evaluate EXPIRED transitions for still-PENDING bids.
    for bid in sorted_items("opaque_bids"):
        if bid["status"] == "PENDING" and date_only(bid, "check_in_date") <= cur:
            bid["status"] = "EXPIRED"
            touch(bid)
    n = logical_clock
    ts = n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
    return ok_obj({"current_utc": ts})


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

@app.post("/opaque/suppliers")
def create_supplier():
    auth(["PlatformAdmin"])
    b = body()
    legal_name = b.get("legal_name")
    comm = b.get("opaque_commission_pct")
    cmin = b.get("concealment_discount_min_pct")
    parity = b.get("parity_protection_enabled", True)
    if not isinstance(legal_name, str) or not legal_name:
        raise ApiError(E_REQ, 400, "legal_name is required")
    if not is_num(comm) or not (0 < comm < 1):
        raise ApiError(E_REQ, 400, "opaque_commission_pct must be in (0,1)")
    if not is_num(cmin) or not (0 <= cmin < 1):
        raise ApiError(E_REQ, 400, "concealment_discount_min_pct must be in [0,1)")
    if not isinstance(parity, bool):
        raise ApiError(E_REQ, 400, "parity_protection_enabled must be a boolean")
    ts = now_ts()
    s = {
        "id": new_id(), "legal_name": legal_name,
        "opaque_commission_pct": comm,
        "parity_protection_enabled": parity,
        "concealment_discount_min_pct": cmin,
        "status": "ACTIVE",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["suppliers"][s["id"]] = s
    return ok_obj(pub_supplier(s), 201)


@app.get("/opaque/suppliers")
def list_suppliers():
    auth(["PlatformAdmin", "FinanceOps", "CustomerService"])
    items = sorted_items("suppliers")
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return ok_list([pub_supplier(s) for s in items])


@app.get("/opaque/suppliers/<supplierId>")
def get_supplier(supplierId):
    auth(["PlatformAdmin", "FinanceOps", "CustomerService"])
    return ok_obj(pub_supplier(get_or_404("suppliers", supplierId)))


def _close_open_windows_for_supplier(supplier_id):
    prop_ids = {p["id"] for p in db["properties"].values()
                if p["supplier_id"] == supplier_id}
    for w in db["rate_windows"].values():
        if w["property_id"] in prop_ids and w["status"] == "OPEN":
            w["status"] = "CLOSED"
            touch(w)


@app.post("/opaque/suppliers/<supplierId>/suspend")
def suspend_supplier(supplierId):
    auth(["PlatformAdmin"])
    s = get_or_404("suppliers", supplierId)
    if s["status"] != "ACTIVE":
        raise ApiError(E_STATE, 409, "Supplier is not ACTIVE")
    s["status"] = "SUSPENDED"
    touch(s)
    _close_open_windows_for_supplier(s["id"])
    return ok_obj(pub_supplier(s))


@app.post("/opaque/suppliers/<supplierId>/reinstate")
def reinstate_supplier(supplierId):
    auth(["PlatformAdmin"])
    s = get_or_404("suppliers", supplierId)
    if s["status"] != "SUSPENDED":
        raise ApiError(E_STATE, 409, "Supplier is not SUSPENDED")
    s["status"] = "ACTIVE"
    touch(s)
    return ok_obj(pub_supplier(s))


@app.post("/opaque/suppliers/<supplierId>/terminate")
def terminate_supplier(supplierId):
    auth(["PlatformAdmin"])
    s = get_or_404("suppliers", supplierId)
    if s["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(E_STATE, 409, "Supplier cannot be terminated from its state")
    for batch in db["settlement_batches"].values():
        if (batch["supplier_id"] == s["id"]
                and batch["status"] in ("DRAFT", "APPROVED")):
            raise ApiError(E_OPEN_BATCH, 409,
                           "Supplier has a DRAFT or APPROVED settlement batch")
    s["status"] = "TERMINATED"
    touch(s)
    _close_open_windows_for_supplier(s["id"])
    return ok_obj(pub_supplier(s))


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

@app.post("/opaque/properties")
def create_property():
    auth(["PlatformAdmin"])
    b = body()
    supplier_id = b.get("supplier_id")
    if not isinstance(supplier_id, str):
        raise ApiError(E_REQ, 400, "supplier_id is required")
    get_or_404("suppliers", supplier_id)
    brand = b.get("brand_name")
    star = b.get("star_rating")
    hood = b.get("neighborhood_code")
    amenities = b.get("amenity_codes")
    rate = b.get("published_rate_cents")
    if not isinstance(brand, str) or not brand:
        raise ApiError(E_REQ, 400, "brand_name is required")
    if not is_int(star) or not (1 <= star <= 5):
        raise ApiError(E_REQ, 400, "star_rating must be an integer in 1..5")
    if not isinstance(hood, str) or not hood:
        raise ApiError(E_REQ, 400, "neighborhood_code is required")
    if not isinstance(amenities, list) or not all(isinstance(a, str) for a in amenities):
        raise ApiError(E_REQ, 400, "amenity_codes must be a list of strings")
    if not is_int(rate) or rate < 0:
        raise ApiError(E_REQ, 400, "published_rate_cents must be a non-negative integer")
    ts = now_ts()
    p = {
        "id": new_id(), "supplier_id": supplier_id, "brand_name": brand,
        "star_rating": star, "neighborhood_code": hood,
        "amenity_codes": list(amenities), "published_rate_cents": rate,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["properties"][p["id"]] = p
    return ok_obj(pub_property(p), 201)


@app.get("/opaque/properties")
def list_properties():
    auth(["PlatformAdmin", "FinanceOps", "CustomerService"])
    items = sorted_items("properties")
    sid = request.args.get("supplier_id")
    hood = request.args.get("neighborhood_code")
    if sid is not None:
        items = [p for p in items if p["supplier_id"] == sid]
    if hood is not None:
        items = [p for p in items if p["neighborhood_code"] == hood]
    return ok_list([pub_property(p) for p in items])


@app.get("/opaque/properties/<propertyId>")
def get_property(propertyId):
    auth(["PlatformAdmin", "FinanceOps", "CustomerService"])
    return ok_obj(pub_property(get_or_404("properties", propertyId)))


# ---------------------------------------------------------------------------
# Rate windows
# ---------------------------------------------------------------------------

@app.post("/opaque/rate-windows")
def create_rate_window():
    auth(["PlatformAdmin"])
    b = body()
    property_id = b.get("property_id")
    if not isinstance(property_id, str):
        raise ApiError(E_REQ, 400, "property_id is required")
    get_or_404("properties", property_id)
    ci = parse_dt(b.get("check_in_date"))
    co = parse_dt(b.get("check_out_date"))
    rate = b.get("opaque_rate_cents")
    rooms = b.get("rooms_allocated")
    if ci is None or co is None:
        raise ApiError(E_REQ, 400, "check_in_date and check_out_date are required")
    if not (co > ci):
        raise ApiError(E_DATE, 400, "check_out_date must be strictly after check_in_date")
    if not is_int(rate) or rate < 0:
        raise ApiError(E_REQ, 400, "opaque_rate_cents must be a non-negative integer")
    if not is_int(rooms) or rooms < 1:
        raise ApiError(E_REQ, 400, "rooms_allocated must be a positive integer")
    ts = now_ts()
    w = {
        "id": new_id(), "property_id": property_id,
        "check_in_date": b.get("check_in_date"),
        "check_out_date": b.get("check_out_date"),
        "opaque_rate_cents": rate, "rooms_allocated": rooms, "rooms_sold": 0,
        "status": "OPEN",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["rate_windows"][w["id"]] = w
    return ok_obj(pub_window(w), 201)


@app.get("/opaque/rate-windows")
def list_rate_windows():
    auth(["PlatformAdmin", "FinanceOps", "CustomerService"])
    items = sorted_items("rate_windows")
    pid = request.args.get("property_id")
    status = request.args.get("status")
    if pid is not None:
        items = [w for w in items if w["property_id"] == pid]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return ok_list([pub_window(w) for w in items])


@app.get("/opaque/rate-windows/<rateWindowId>")
def get_rate_window(rateWindowId):
    auth(["PlatformAdmin", "FinanceOps", "CustomerService"])
    return ok_obj(pub_window(get_or_404("rate_windows", rateWindowId)))


@app.post("/opaque/rate-windows/<rateWindowId>/close")
def close_rate_window(rateWindowId):
    auth(["PlatformAdmin"])
    w = get_or_404("rate_windows", rateWindowId)
    b = body()
    exp = b.get("expected_rate_window_version")
    if exp is not None and exp != w["version"]:
        raise ApiError(E_STALE, 412, "RateWindow version mismatch")
    if w["status"] != "OPEN":
        raise ApiError(E_STATE, 409, "RateWindow is not OPEN")
    w["status"] = "CLOSED"
    touch(w)
    return ok_obj(pub_window(w))


# ---------------------------------------------------------------------------
# Disclosure zones
# ---------------------------------------------------------------------------

@app.post("/opaque/disclosure-zones")
def create_zone():
    auth(["PlatformAdmin"])
    b = body()
    hood = b.get("neighborhood_code")
    minstar = b.get("min_star_rating")
    revealed = b.get("revealed_amenity_codes")
    if not isinstance(hood, str) or not hood:
        raise ApiError(E_REQ, 400, "neighborhood_code is required")
    if not is_int(minstar) or not (1 <= minstar <= 5):
        raise ApiError(E_REQ, 400, "min_star_rating must be an integer in 1..5")
    if not isinstance(revealed, list) or not all(isinstance(a, str) for a in revealed):
        raise ApiError(E_REQ, 400, "revealed_amenity_codes must be a list of strings")
    if find_zone(hood) is not None:
        raise ApiError(E_REQ, 400, "a disclosure zone already exists for this neighborhood_code")
    ts = now_ts()
    z = {
        "id": new_id(), "neighborhood_code": hood, "min_star_rating": minstar,
        "revealed_amenity_codes": list(revealed),
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["disclosure_zones"][z["id"]] = z
    return ok_obj(pub_zone(z), 201)


@app.get("/opaque/disclosure-zones")
def list_zones():
    auth(["PlatformAdmin", "Customer", "CustomerService"])
    items = sorted_items("disclosure_zones")
    hood = request.args.get("neighborhood_code")
    if hood is not None:
        items = [z for z in items if z["neighborhood_code"] == hood]
    return ok_list([pub_zone(z) for z in items])


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@app.post("/opaque/customers")
def create_customer():
    auth(["PlatformAdmin"])
    b = body()
    email = b.get("email")
    name = b.get("full_name")
    if not isinstance(email, str) or not email:
        raise ApiError(E_REQ, 400, "email is required")
    if not isinstance(name, str) or not name:
        raise ApiError(E_REQ, 400, "full_name is required")
    for c in db["customers"].values():
        if c["email"] == email:
            raise ApiError(E_REQ, 400, "email must be unique")
    ts = now_ts()
    c = {
        "id": new_id(), "email": email, "full_name": name,
        "fraud_score": 0, "fraud_status": "CLEAR", "opaque_win_count_30d": 0,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["customers"][c["id"]] = c
    return ok_obj(pub_customer(c), 201)


@app.get("/opaque/customers")
def list_customers():
    auth(["PlatformAdmin", "CustomerService", "FinanceOps"])
    items = sorted_items("customers")
    fs = request.args.get("fraud_status")
    if fs is not None:
        items = [c for c in items if c["fraud_status"] == fs]
    return ok_list([pub_customer(c) for c in items])


@app.get("/opaque/customers/<customerId>")
def get_customer(customerId):
    uid, role = auth(["PlatformAdmin", "CustomerService", "FinanceOps", "Customer"])
    c = get_or_404("customers", customerId)
    if role == "Customer" and c["id"] != uid:
        raise ApiError(E_PERM, 403, "Customers may only read themselves")
    return ok_obj(pub_customer(c))


# ---------------------------------------------------------------------------
# Opaque bids
# ---------------------------------------------------------------------------

@app.post("/opaque/opaque-bids")
def create_bid():
    uid, role = auth(["Customer"])
    b = body()
    customer_id = b.get("customer_id")
    if not isinstance(customer_id, str):
        raise ApiError(E_REQ, 400, "customer_id is required")
    customer = get_or_404("customers", customer_id)
    if customer_id != uid:
        raise ApiError(E_PERM, 403, "Customers may only place bids for themselves")
    hood = b.get("neighborhood_code")
    minstar = b.get("min_star_rating")
    ci = parse_dt(b.get("check_in_date"))
    co = parse_dt(b.get("check_out_date"))
    mode = b.get("offer_mode")
    price = b.get("bid_price_cents")
    required = b.get("required_amenity_codes")
    if not isinstance(hood, str) or not hood:
        raise ApiError(E_REQ, 400, "neighborhood_code is required")
    if not is_int(minstar) or not (1 <= minstar <= 5):
        raise ApiError(E_REQ, 400, "min_star_rating must be an integer in 1..5")
    if ci is None or co is None:
        raise ApiError(E_REQ, 400, "check_in_date and check_out_date are required")
    if mode not in ("BID", "FIXED"):
        raise ApiError(E_REQ, 400, "offer_mode must be BID or FIXED")
    # Disclosure zone for the amenity-filter membership check.
    zone = find_zone(hood)
    # Fraud gate.
    if customer["fraud_status"] == "BLOCKED":
        raise ApiError(E_BLOCKED, 403, "Customer is BLOCKED")
    # Temporal gate.
    if not (co > ci):
        raise ApiError(E_DATE, 400, "check_out_date must be strictly after check_in_date")
    if ci < logical_clock:
        raise ApiError(E_DATE, 400, "check_in_date must not be in the past")
    # Mode semantics + amenity filter membership.
    if mode == "BID":
        if not is_int(price) or price <= 0:
            raise ApiError(E_REQ, 400, "bid_price_cents is required in BID mode")
    if required is not None:
        if not isinstance(required, list) or not all(isinstance(a, str) for a in required):
            raise ApiError(E_REQ, 400, "required_amenity_codes must be a list of strings")
        revealed = set(zone["revealed_amenity_codes"]) if zone else set()
        for a in required:
            if a not in revealed:
                raise ApiError(E_REQ, 400,
                               "amenity filter value not in the zone's revealed_amenity_codes")
    ts = now_ts()
    bid = {
        "id": new_id(), "customer_id": customer_id, "neighborhood_code": hood,
        "min_star_rating": minstar,
        "check_in_date": b.get("check_in_date"),
        "check_out_date": b.get("check_out_date"),
        "bid_price_cents": price if mode == "BID" else None,
        "offer_mode": mode,
        "computed_price_cents": None,
        "winning_property_id": None, "winning_rate_window_id": None,
        "concealment_discount_pct": None,
        "status": "PENDING",
        "required_amenity_codes": list(required) if required else [],
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["opaque_bids"][bid["id"]] = bid
    bid["computed_price_cents"] = compute_price_floor(bid)
    return ok_obj(pub_bid(bid), 201)


@app.get("/opaque/opaque-bids")
def list_bids():
    uid, role = auth(["PlatformAdmin", "CustomerService", "Customer"])
    items = sorted_items("opaque_bids")
    if role == "Customer":
        items = [b for b in items if b["customer_id"] == uid]
    cid = request.args.get("customer_id")
    status = request.args.get("status")
    wp = request.args.get("winning_property_id")
    ww = request.args.get("winning_rate_window_id")
    if cid is not None:
        items = [b for b in items if b["customer_id"] == cid]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if wp is not None:
        items = [b for b in items if b["winning_property_id"] == wp]
    if ww is not None:
        items = [b for b in items if b["winning_rate_window_id"] == ww]
    return ok_list([pub_bid(b) for b in items])


@app.get("/opaque/opaque-bids/<bidId>")
def get_bid(bidId):
    uid, role = auth(["PlatformAdmin", "CustomerService", "Customer"])
    b = get_or_404("opaque_bids", bidId)
    if role == "Customer" and b["customer_id"] != uid:
        raise ApiError(E_PERM, 403, "Customers may only read their own bids")
    return ok_obj(pub_bid(b))


@app.post("/opaque/opaque-bids/<bidId>/evaluate")
def evaluate_bid(bidId):
    auth(["PlatformAdmin", "CustomerService"])
    bid = get_or_404("opaque_bids", bidId)
    req = body()
    customer = db["customers"].get(bid["customer_id"])
    exp = req.get("expected_customer_version")
    if exp is not None and customer is not None and exp != customer["version"]:
        raise ApiError(E_STALE, 412, "Customer version mismatch")
    if bid["status"] != "PENDING":
        raise ApiError(E_STATE, 409, "Bid is not PENDING")
    fail_on_reject = req.get("fail_on_reject") is True
    if customer["fraud_status"] == "BLOCKED":
        raise ApiError(E_BLOCKED, 403, "Customer is BLOCKED")

    def reject():
        bid["status"] = "REJECTED"
        touch(bid)
        if fail_on_reject:
            raise ApiError(E_BID_FLOOR, 422,
                           "Bid below floor or no eligible candidate")
        return ok_obj(pub_bid(bid))

    winner = select_winner(bid)
    computed = compute_price_floor(bid)
    bid["computed_price_cents"] = computed
    if winner is None or computed is None:
        return reject()
    prop, window = winner
    supplier = db["suppliers"][prop["supplier_id"]]
    n = nights_between(date_only(bid, "check_in_date"),
                       date_only(bid, "check_out_date"))
    if bid["offer_mode"] == "BID":
        charged = bid["bid_price_cents"]
        if charged < computed:
            return reject()
        published_total = prop["published_rate_cents"] * n
        if published_total <= 0:
            return reject()
        disc = round4((published_total - charged) / published_total)
        if disc < supplier["concealment_discount_min_pct"]:
            return reject()
    else:
        charged = computed
        published_total = prop["published_rate_cents"] * n
        disc = round4((published_total - charged) / published_total) if published_total > 0 else 0.0

    # Acceptance cascade.
    bid["status"] = "ACCEPTED"
    bid["winning_property_id"] = prop["id"]
    bid["winning_rate_window_id"] = window["id"]
    bid["concealment_discount_pct"] = disc
    touch(bid)

    comm = supplier["opaque_commission_pct"]
    remit = math.floor(charged * (1 - comm))
    commission = charged - remit
    ts = now_ts()
    booking = {
        "id": new_id(), "opaque_bid_id": bid["id"],
        "customer_id": bid["customer_id"], "property_id": prop["id"],
        "supplier_id": supplier["id"], "rate_window_id": window["id"],
        "check_in_date": bid["check_in_date"],
        "check_out_date": bid["check_out_date"],
        "charged_price_cents": charged,
        "supplier_remittance_cents": remit,
        "platform_commission_cents": commission,
        "payment_status": "CAPTURED", "fulfillment_status": "CONFIRMED",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["bookings"][booking["id"]] = booking

    window["rooms_sold"] += 1
    if window["rooms_sold"] == window["rooms_allocated"]:
        window["status"] = "EXHAUSTED"
    touch(window)

    customer["opaque_win_count_30d"] = win_count_30d(customer["id"])
    if customer["opaque_win_count_30d"] > REPEAT_WIN_THRESHOLD:
        fts = now_ts()
        flag = {
            "id": new_id(), "customer_id": customer["id"],
            "booking_id": booking["id"], "reason_code": "REPEAT_WIN_RATE",
            "score_delta": REPEAT_WIN_PENALTY, "status": "OPEN",
            "applied": True,
            "created_at": fts, "updated_at": fts, "version": 1,
        }
        db["fraud_flags"][flag["id"]] = flag
        customer["fraud_score"] += REPEAT_WIN_PENALTY
        recompute_fraud_status(customer)
    touch(customer)
    return ok_obj(pub_bid(bid))


@app.post("/opaque/opaque-bids/<bidId>/withdraw")
def withdraw_bid(bidId):
    uid, role = auth(["Customer"])
    bid = get_or_404("opaque_bids", bidId)
    if bid["customer_id"] != uid:
        raise ApiError(E_PERM, 403, "Only the bid's customer may withdraw it")
    if bid["status"] != "PENDING":
        raise ApiError(E_STATE, 409, "Bid is not PENDING")
    bid["status"] = "WITHDRAWN"
    touch(bid)
    return ok_obj(pub_bid(bid))


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

@app.get("/opaque/bookings")
def list_bookings():
    uid, role = auth(["PlatformAdmin", "CustomerService", "FinanceOps", "Customer"])
    items = sorted_items("bookings")
    if role == "Customer":
        items = [b for b in items if b["customer_id"] == uid]
    for param, field in (("customer_id", "customer_id"),
                         ("supplier_id", "supplier_id"),
                         ("property_id", "property_id"),
                         ("opaque_bid_id", "opaque_bid_id"),
                         ("rate_window_id", "rate_window_id"),
                         ("fulfillment_status", "fulfillment_status")):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b[field] == v]
    return ok_list([pub_booking(b) for b in items])


@app.get("/opaque/bookings/<bookingId>")
def get_booking(bookingId):
    uid, role = auth(["PlatformAdmin", "CustomerService", "FinanceOps", "Customer"])
    b = get_or_404("bookings", bookingId)
    if role == "Customer" and b["customer_id"] != uid:
        raise ApiError(E_PERM, 403, "Customers may only read their own bookings")
    return ok_obj(pub_booking(b))


@app.post("/opaque/bookings/<bookingId>/mark-service-failure")
def mark_service_failure(bookingId):
    auth(["CustomerService"])
    b = get_or_404("bookings", bookingId)
    if b["fulfillment_status"] != "CONFIRMED":
        raise ApiError(E_STATE, 409, "Booking fulfillment_status is not CONFIRMED")
    case = None
    for c in db["complaint_cases"].values():
        if (c["booking_id"] == b["id"] and c["category"] == "SERVICE_FAILURE"
                and c["status"] == "RESOLVED" and c["resolution"] == "FULL_REFUND"):
            case = c
            break
    if case is None:
        raise ApiError(E_STATE, 409,
                       "No RESOLVED SERVICE_FAILURE complaint with FULL_REFUND exists")
    b["payment_status"] = "REFUNDED"
    b["fulfillment_status"] = "SERVICE_FAILED"
    b["supplier_remittance_cents"] = 0
    b["platform_commission_cents"] = 0
    touch(b)
    window = db["rate_windows"].get(b["rate_window_id"])
    if window is not None:
        was_exhausted = window["status"] == "EXHAUSTED"
        window["rooms_sold"] = max(0, window["rooms_sold"] - 1)
        if was_exhausted:
            window["status"] = "OPEN"
        touch(window)
    return ok_obj(pub_booking(b))


@app.post("/opaque/bookings/<bookingId>/grant-goodwill")
def grant_goodwill(bookingId):
    auth(["CustomerService"])
    b = get_or_404("bookings", bookingId)
    if b["fulfillment_status"] != "CONFIRMED":
        raise ApiError(E_STATE, 409, "Booking fulfillment_status is not CONFIRMED")
    gw = goodwill_for_booking(b["id"])
    if gw <= 0:
        raise ApiError(E_STATE, 409,
                       "No RESOLVED GOODWILL_CREDIT complaint exists for this booking")
    if not (0 < gw < b["charged_price_cents"]):
        raise ApiError(E_GOODWILL, 422,
                       "goodwill_credit_cents must be in (0, charged_price_cents)")
    b["payment_status"] = "PARTIALLY_REFUNDED"
    touch(b)
    return ok_obj(pub_booking(b))


# ---------------------------------------------------------------------------
# Complaint cases
# ---------------------------------------------------------------------------

@app.post("/opaque/complaint-cases")
def create_case():
    uid, role = auth(["Customer", "CustomerService"])
    b = body()
    booking_id = b.get("booking_id")
    if not isinstance(booking_id, str):
        raise ApiError(E_REQ, 400, "booking_id is required")
    booking = get_or_404("bookings", booking_id)
    category = b.get("category")
    description = b.get("description")
    if category not in ("PROPERTY_MISREPRESENTED", "SERVICE_FAILURE",
                        "DISSATISFIED_REVEAL", "OTHER"):
        raise ApiError(E_REQ, 400, "invalid category")
    if not isinstance(description, str):
        raise ApiError(E_REQ, 400, "description is required")
    if role == "Customer" and booking["customer_id"] != uid:
        raise ApiError(E_PERM, 403,
                       "Customers may complain only against their own bookings")
    for c in db["complaint_cases"].values():
        if c["booking_id"] == booking_id and c["status"] in ("OPEN", "UNDER_REVIEW"):
            raise ApiError(E_DUP_COMPLAINT, 409,
                           "An OPEN or UNDER_REVIEW case already exists for this booking")
    ts = now_ts()
    case = {
        "id": new_id(), "booking_id": booking_id,
        "customer_id": booking["customer_id"], "category": category,
        "description": description, "resolution": "NONE",
        "goodwill_credit_cents": 0, "status": "OPEN",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["complaint_cases"][case["id"]] = case
    return ok_obj(pub_case(case), 201)


@app.get("/opaque/complaint-cases")
def list_cases():
    uid, role = auth(["PlatformAdmin", "CustomerService", "Customer"])
    items = sorted_items("complaint_cases")
    if role == "Customer":
        items = [c for c in items if c["customer_id"] == uid]
    for param in ("booking_id", "customer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    return ok_list([pub_case(c) for c in items])


@app.get("/opaque/complaint-cases/<caseId>")
def get_case(caseId):
    uid, role = auth(["PlatformAdmin", "CustomerService", "Customer"])
    c = get_or_404("complaint_cases", caseId)
    if role == "Customer" and c["customer_id"] != uid:
        raise ApiError(E_PERM, 403, "Customers may only read their own cases")
    return ok_obj(pub_case(c))


@app.post("/opaque/complaint-cases/<caseId>/start-review")
def start_review(caseId):
    auth(["CustomerService"])
    c = get_or_404("complaint_cases", caseId)
    if c["status"] != "OPEN":
        raise ApiError(E_STATE, 409, "Case is not OPEN")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return ok_obj(pub_case(c))


@app.post("/opaque/complaint-cases/<caseId>/resolve")
def resolve_case(caseId):
    auth(["CustomerService"])
    c = get_or_404("complaint_cases", caseId)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError(E_STATE, 409, "Case is not UNDER_REVIEW")
    b = body()
    resolution = b.get("resolution")
    if resolution not in ("GOODWILL_CREDIT", "FULL_REFUND"):
        raise ApiError(E_REQ, 400, "resolution must be GOODWILL_CREDIT or FULL_REFUND")
    if c["category"] == "DISSATISFIED_REVEAL" and resolution != "GOODWILL_CREDIT":
        raise ApiError(E_REQ, 400,
                       "DISSATISFIED_REVEAL must resolve as GOODWILL_CREDIT")
    gw = 0
    if resolution == "GOODWILL_CREDIT":
        gw = b.get("goodwill_credit_cents")
        booking = db["bookings"].get(c["booking_id"])
        charged = booking["charged_price_cents"] if booking else 0
        if not is_int(gw) or not (0 < gw < charged):
            raise ApiError(E_GOODWILL, 422,
                           "goodwill_credit_cents must be in (0, charged_price_cents)")
    c["resolution"] = resolution
    c["goodwill_credit_cents"] = gw if resolution == "GOODWILL_CREDIT" else 0
    c["status"] = "RESOLVED"
    touch(c)
    return ok_obj(pub_case(c))


@app.post("/opaque/complaint-cases/<caseId>/reject")
def reject_case(caseId):
    auth(["CustomerService"])
    c = get_or_404("complaint_cases", caseId)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError(E_STATE, 409, "Case is not UNDER_REVIEW")
    c["status"] = "REJECTED"
    touch(c)
    return ok_obj(pub_case(c))


# ---------------------------------------------------------------------------
# Settlement batches
# ---------------------------------------------------------------------------

@app.post("/opaque/settlement-batches")
def create_batch():
    auth(["FinanceOps"])
    b = body()
    supplier_id = b.get("supplier_id")
    if not isinstance(supplier_id, str):
        raise ApiError(E_REQ, 400, "supplier_id is required")
    get_or_404("suppliers", supplier_id)
    ps = parse_dt(b.get("period_start_date"))
    pe = parse_dt(b.get("period_end_date"))
    if ps is None or pe is None:
        raise ApiError(E_REQ, 400, "period_start_date and period_end_date are required")
    if not (pe > ps):
        raise ApiError(E_DATE, 400,
                       "period_end_date must be strictly after period_start_date")
    ts = now_ts()
    batch = {
        "id": new_id(), "supplier_id": supplier_id,
        "period_start_date": b.get("period_start_date"),
        "period_end_date": b.get("period_end_date"),
        "booking_ids": [], "gross_remittance_cents": 0,
        "goodwill_deduction_cents": 0, "net_remittance_cents": 0,
        "status": "DRAFT",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["settlement_batches"][batch["id"]] = batch
    run_settlement_selection(batch)
    return ok_obj(pub_batch(batch), 201)


@app.get("/opaque/settlement-batches")
def list_batches():
    auth(["PlatformAdmin", "FinanceOps"])
    items = sorted_items("settlement_batches")
    for param in ("supplier_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b[param] == v]
    return ok_list([pub_batch(b) for b in items])


@app.get("/opaque/settlement-batches/<batchId>")
def get_batch(batchId):
    auth(["PlatformAdmin", "FinanceOps"])
    return ok_obj(pub_batch(get_or_404("settlement_batches", batchId)))


@app.post("/opaque/settlement-batches/<batchId>/reselect")
def reselect_batch(batchId):
    auth(["FinanceOps"])
    batch = get_or_404("settlement_batches", batchId)
    if batch["status"] != "DRAFT":
        raise ApiError(E_STATE, 409, "Batch is not DRAFT")
    run_settlement_selection(batch)
    touch(batch)
    return ok_obj(pub_batch(batch))


@app.post("/opaque/settlement-batches/<batchId>/approve")
def approve_batch(batchId):
    auth(["FinanceOps"])
    batch = get_or_404("settlement_batches", batchId)
    req = body()
    exp = req.get("expected_settlement_batch_version")
    if exp is not None and exp != batch["version"]:
        raise ApiError(E_STALE, 412, "SettlementBatch version mismatch")
    if batch["status"] != "DRAFT":
        raise ApiError(E_STATE, 409, "Batch is not DRAFT")
    supplier = db["suppliers"].get(batch["supplier_id"])
    if supplier is not None and supplier["status"] == "TERMINATED":
        raise ApiError(E_STATE, 409, "Supplier is TERMINATED")
    if not batch["booking_ids"]:
        raise ApiError(E_BATCH_EMPTY, 422,
                       "SettlementBatch approval requires a non-empty booking_ids")
    comm = supplier["opaque_commission_pct"] if supplier else 0
    gross = 0
    deduction = 0
    for bid_id in batch["booking_ids"]:
        booking = db["bookings"].get(bid_id)
        if booking is None:
            continue
        if booking["fulfillment_status"] == "SERVICE_FAILED":
            booking["supplier_remittance_cents"] = 0
            booking["platform_commission_cents"] = 0
        elif booking["payment_status"] == "PARTIALLY_REFUNDED":
            applies, gw = chargeback_applies(booking)
            if applies:
                base = booking["charged_price_cents"] - gw
                remit = math.floor(base * (1 - comm))
                booking["supplier_remittance_cents"] = remit
                booking["platform_commission_cents"] = base - remit
                deduction += gw
        if booking["fulfillment_status"] == "CONFIRMED":
            booking["fulfillment_status"] = "SETTLED"
        touch(booking)
        gross += booking["supplier_remittance_cents"]
    batch["gross_remittance_cents"] = gross
    batch["goodwill_deduction_cents"] = deduction
    batch["net_remittance_cents"] = gross - deduction
    batch["status"] = "APPROVED"
    touch(batch)
    return ok_obj(pub_batch(batch))


@app.post("/opaque/settlement-batches/<batchId>/void")
def void_batch(batchId):
    auth(["FinanceOps"])
    batch = get_or_404("settlement_batches", batchId)
    if batch["status"] != "DRAFT":
        raise ApiError(E_STATE, 409, "Batch is not DRAFT")
    batch["status"] = "VOIDED"
    touch(batch)
    return ok_obj(pub_batch(batch))


@app.post("/opaque/settlement-batches/<batchId>/mark-paid")
def mark_paid_batch(batchId):
    auth(["FinanceOps"])
    batch = get_or_404("settlement_batches", batchId)
    if batch["status"] != "APPROVED":
        raise ApiError(E_STATE, 409, "Batch is not APPROVED")
    batch["status"] = "PAID"
    touch(batch)
    return ok_obj(pub_batch(batch))


# ---------------------------------------------------------------------------
# Fraud flags
# ---------------------------------------------------------------------------

@app.post("/opaque/fraud-flags")
def create_flag():
    auth(["PlatformAdmin"])
    b = body()
    customer_id = b.get("customer_id")
    if not isinstance(customer_id, str):
        raise ApiError(E_REQ, 400, "customer_id is required")
    get_or_404("customers", customer_id)
    reason = b.get("reason_code")
    delta = b.get("score_delta")
    booking_id = b.get("booking_id")
    if reason not in ("ARBITRAGE_PATTERN", "REPEAT_WIN_RATE", "MANUAL_REVIEW"):
        raise ApiError(E_REQ, 400, "invalid reason_code")
    if not is_int(delta) or delta <= 0:
        raise ApiError(E_REQ, 400, "score_delta must be a positive integer")
    if booking_id is not None:
        if not isinstance(booking_id, str):
            raise ApiError(E_REQ, 400, "booking_id must be a string")
        get_or_404("bookings", booking_id)
    ts = now_ts()
    flag = {
        "id": new_id(), "customer_id": customer_id, "booking_id": booking_id,
        "reason_code": reason, "score_delta": delta, "status": "OPEN",
        "applied": False,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["fraud_flags"][flag["id"]] = flag
    return ok_obj(pub_flag(flag), 201)


@app.get("/opaque/fraud-flags")
def list_flags():
    auth(["PlatformAdmin", "CustomerService"])
    items = sorted_items("fraud_flags")
    for param in ("customer_id", "booking_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f[param] == v]
    return ok_list([pub_flag(f) for f in items])


@app.get("/opaque/fraud-flags/<flagId>")
def get_flag(flagId):
    auth(["PlatformAdmin", "CustomerService"])
    return ok_obj(pub_flag(get_or_404("fraud_flags", flagId)))


@app.post("/opaque/fraud-flags/<flagId>/uphold")
def uphold_flag(flagId):
    auth(["PlatformAdmin"])
    flag = get_or_404("fraud_flags", flagId)
    if flag["status"] != "OPEN":
        raise ApiError(E_STATE, 409, "Flag is not OPEN")
    customer = db["customers"].get(flag["customer_id"])
    if customer is not None and not flag.get("applied"):
        customer["fraud_score"] += flag["score_delta"]
        flag["applied"] = True
        recompute_fraud_status(customer)
        touch(customer)
    flag["status"] = "UPHELD"
    touch(flag)
    return ok_obj(pub_flag(flag))


@app.post("/opaque/fraud-flags/<flagId>/dismiss")
def dismiss_flag(flagId):
    auth(["PlatformAdmin"])
    flag = get_or_404("fraud_flags", flagId)
    if flag["status"] != "OPEN":
        raise ApiError(E_STATE, 409, "Flag is not OPEN")
    customer = db["customers"].get(flag["customer_id"])
    if customer is not None and flag.get("applied"):
        customer["fraud_score"] = max(0, customer["fraud_score"] - flag["score_delta"])
        flag["applied"] = False
        recompute_fraud_status(customer)
        touch(customer)
    flag["status"] = "DISMISSED"
    touch(flag)
    return ok_obj(pub_flag(flag))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
