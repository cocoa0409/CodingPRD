#!/usr/bin/env python3
"""Online Vehicle Purchase, Delivery Choice & Return Window API.

In-memory Flask implementation built from PRD.md + SCAFFOLD.yaml.
Storage: Python dicts keyed by id. No disk persistence, no seeding.
Logical clock starts at 2026-09-01T00:00:00Z and only moves via
POST /vehicle-hub/_clock/set_current_utc.
"""

import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from flask import Flask, jsonify, request

app = Flask(__name__)

# =========================================================================
# Logical clock
# =========================================================================
CLOCK = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return CLOCK["now"]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


# =========================================================================
# Error catalog
# =========================================================================
ERR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_PREQUAL_EXPIRED": 422,
    "ERR_RETURN_WINDOW_CLOSED": 422,
    "ERR_MILEAGE_LIMIT_EXCEEDED": 422,
    "ERR_DEFECT_DISCLOSED": 422,
    "ERR_WARRANTY_WINDOW_EXPIRED": 422,
    "ERR_APPOINTMENT_CONFLICT": 409,
    "ERR_TRANSIT_SLOT_CONFLICT": 409,
    "ERR_RECON_CAPACITY_FULL": 409,
    "ERR_REGION_NOT_SERVICED": 422,
    "ERR_FINANCING_CAP_EXCEEDED": 402,
    "ERR_DOWN_PAYMENT_TOO_LOW": 402,
    "ERR_TEMP_TAG_EXPIRED": 422,
    "ERR_DEPENDENCY_NOT_READY": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNSUPPORTED_STATE": 422,
    "ERR_NO_CENTER_FOR_MARKET": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = ERR_HTTP[error_id]


def err(error_id, message):
    raise ApiError(error_id, message)


# =========================================================================
# Response envelope
# =========================================================================
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def success(data, code=200, page=None):
    meta = {"api_request_id": _req_id(), "api_request_timestamp": iso(now())}
    if page is not None:
        meta.update(page)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def error_body(error_id, message, status):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": iso(now())},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e.error_id, e.message, e.status)


@app.errorhandler(404)
def handle_404(e):
    return error_body("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_body("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_500(e):
    return error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % e, 500)


# =========================================================================
# In-memory store
# =========================================================================
DB = {
    "customers": {},
    "centers": {},
    "vehicles": {},
    "annotations": {},
    "prequals": {},
    "tradeins": {},
    "orders": {},
    "titleregs": {},
    "appointments": {},
    "transits": {},
    "claims": {},
    "repairauths": {},
    "intakes": {},
}
SEQ = {"n": 0}


def new_record(extra):
    SEQ["n"] += 1
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": iso(now()),
        "updated_at": iso(now()),
        "version": 1,
        "_seq": SEQ["n"],
    }
    rec.update(extra)
    return rec


def touch(rec):
    rec["updated_at"] = iso(now())
    rec["version"] += 1


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# =========================================================================
# Auth
# =========================================================================
ROLES = {
    "Customer",
    "PlatformAdmin",
    "CustomerAdvocate",
    "ReconOperator",
    "RegistrationClerk",
    "WarrantyAdmin",
}


def authenticate(allowed):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role / X-User-ID headers")
    if role not in allowed:
        err("ERR_UNAUTHORIZED", "Role not permitted to invoke this endpoint")
    return uid, role


def own(customer_id, uid):
    if customer_id != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "Acting customer does not own this resource")


# =========================================================================
# Request helpers
# =========================================================================
def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def req_field(data, field):
    if field not in data or data[field] is None:
        err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return data[field]


def req_str(data, field):
    v = req_field(data, field)
    if not isinstance(v, str) or not v:
        err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return v


def req_int(data, field, minimum=None, strict_positive=False):
    v = req_field(data, field)
    if not is_int(v):
        err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if strict_positive and v <= 0:
        err("ERR_INVALID_REQUEST", "Field %s must be > 0" % field)
    if minimum is not None and v < minimum:
        err("ERR_INVALID_REQUEST", "Field %s must be >= %d" % (field, minimum))
    return v


def req_enum(data, field, values):
    v = req_field(data, field)
    if v not in values:
        err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(values)))
    return v


def paginate(records):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit, offset = 10, 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            err("ERR_INVALID_REQUEST", "offset must be >= 0")
    items = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page_items = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page_items) < total,
    }
    return [pub(r) for r in page_items], meta


def get_or_404(store, rid, label="Resource"):
    rec = DB[store].get(rid)
    if rec is None:
        err("ERR_NOT_FOUND", "%s not found: %s" % (label, rid))
    return rec


# =========================================================================
# Constants & calculations
# =========================================================================
STATE_TAX_BPS = {"GA": 700, "TX": 625, "CA": 725, "FL": 600, "NY": 800}
HOME_STATE = "GA"
TERM_MONTHS = 72
MIN_DOWN_BPS = 1000
MIN_LISTED_PRICE_CENTS = 100000
TRADE_IN_FLOOR_CENTS = 50000
ODOMETER_SOFT_CAP = 60000
ODO_DEDUCT_PER_1K_CENTS = 1200
BAND_BASE = {"ECONOMY": 1200000, "MID": 2000000, "PREMIUM": 3200000}
ADJUST_PER_MISMATCH_CENTS = 40000
APR_BPS = {"A": 490, "B": 690, "C": 990, "D": 1490}
BAND_CAP = {"A": 9000000, "B": 6500000, "C": 4000000, "D": 2200000}
INCOME_MULTIPLIER_BPS = 2500
PREQUAL_VALID_DAYS = 14
TRADE_IN_VALID_DAYS = 7
RETURN_WINDOW_DAYS = 7
RETURN_MILEAGE_LIMIT = 400
EXCESS_WEAR_FEE_CENTS = 50000
WARRANTY_CLAIM_CAP_CENTS = 400000
WARRANTY_WINDOW_DAYS = 100
WARRANTY_MILEAGE_LIMIT = 4189
VENDING_DEPOSIT_CENTS = 25000
TEMP_TAG_DAYS = {"IN_STATE": 30, "OUT_OF_STATE": 45}
REG_PROCESSING_DAYS = {"IN_STATE": 10, "OUT_OF_STATE": 21}
TRANSIT_BUFFER_MINUTES = 120
TIRE_RANK = {"GOOD": 0, "FAIR": 1, "POOR": 2}


def amortize(principal_cents, apr_bps, n):
    """Exact rational amortization; half-up rounding once at the final step."""
    if principal_cents <= 0:
        return 0
    r = Fraction(apr_bps, 120000)
    if r == 0:
        pay = Fraction(principal_cents, n)
    else:
        f = (1 + r) ** n
        pay = Fraction(principal_cents) * r * f / (f - 1)
    rounded = (Decimal(pay.numerator) / Decimal(pay.denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(rounded)


def recompute_listed(vehicle):
    active = [
        a
        for a in DB["annotations"].values()
        if a["vehicle_id"] == vehicle["id"] and a["status"] == "ACTIVE"
    ]
    ded = sum(a["deduction_cents"] for a in active)
    vehicle["listed_price_cents"] = max(vehicle["base_price_cents"] - ded, MIN_LISTED_PRICE_CENTS)
    vehicle["annotation_count"] = len(active)


def trade_in_initial_offer(q):
    base = BAND_BASE[q["vehicle_band"]]
    if q["accident_history"]:
        base -= 150000
    if q["mechanical_issues"]:
        base -= 250000
    if q["smoker_vehicle"]:
        base -= 75000
    base += {"GOOD": 0, "FAIR": -30000, "POOR": -90000}[q["tire_condition"]]
    odo_over = max(q["odometer"] - ODOMETER_SOFT_CAP, 0)
    base -= (odo_over // 1000) * ODO_DEDUCT_PER_1K_CENTS
    return max(base, TRADE_IN_FLOOR_CENTS)


def trade_in_adjustment(initial, mismatches):
    if mismatches == 0:
        return initial
    if mismatches <= 2:
        return max(initial - mismatches * ADJUST_PER_MISMATCH_CENTS, TRADE_IN_FLOOR_CENTS)
    return max((initial * 70) // 100, TRADE_IN_FLOOR_CENTS)


def compute_total_due(order, vehicle, offer):
    price = vehicle["listed_price_cents"]
    tax = (price * STATE_TAX_BPS[order["state_code"]]) // 10000
    credit = 0
    if offer is not None and offer["status"] == "CONFIRMED" and offer.get("adjusted_offer_cents") is not None:
        credit = offer["adjusted_offer_cents"]
    return max(price + tax - credit, 0)


def sweep_prequal(p):
    if p["status"] == "PREQUALIFIED" and now() > parse_dt(p["expires_at"]):
        p["status"] = "EXPIRED"
        touch(p)


def sweep_tradein(t):
    if t["status"] == "OFFERED" and now() > parse_dt(t["expires_at"]):
        t["status"] = "EXPIRED"
        touch(t)


def processing_mode_for(state_code):
    return "IN_STATE" if state_code == HOME_STATE else "OUT_OF_STATE"


def slot_available(center_id, exclude_vehicle_id=None):
    center = DB["centers"][center_id]
    count = sum(
        1
        for v in DB["vehicles"].values()
        if v.get("center_id") == center_id
        and v["status"] in ("INTAKE", "IN_RECON")
        and v["id"] != exclude_vehicle_id
    )
    return count < center["slot_count"]


def daily_available(center_id):
    center = DB["centers"][center_id]
    today = now().date().isoformat()
    count = sum(
        1
        for v in DB["vehicles"].values()
        if v.get("center_id") == center_id
        and v["status"] == "IN_RECON"
        and v.get("_in_work_date") == today
    )
    return count < center["daily_capacity"]


def region_serviced(market_code, address_region):
    return address_region == market_code or address_region.startswith(market_code + "-")


# =========================================================================
# Clock
# =========================================================================
@app.route("/vehicle-hub/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["PlatformAdmin"])
    data = body()
    target = parse_dt(req_field(data, "to_iso8601"))
    if target is None:
        err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp")
    CLOCK["now"] = target
    return success({"current_utc": iso(now())})


# =========================================================================
# Customers
# =========================================================================
@app.route("/vehicle-hub/customers", methods=["POST"])
def create_customer():
    authenticate(["PlatformAdmin"])
    data = body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    state_code = req_str(data, "state_code")
    dfc = data.get("default_fulfillment_choice", "HOME_DELIVERY")
    if dfc not in ("HOME_DELIVERY", "VENDING_MACHINE"):
        err("ERR_INVALID_REQUEST", "default_fulfillment_choice must be HOME_DELIVERY or VENDING_MACHINE")
    if any(c["email"] == email for c in DB["customers"].values()):
        err("ERR_INVALID_REQUEST", "email already registered")
    if state_code not in STATE_TAX_BPS:
        err("ERR_UNSUPPORTED_STATE", "state_code not supported: %s" % state_code)
    rec = new_record(
        {
            "full_name": full_name,
            "email": email,
            "state_code": state_code,
            "default_fulfillment_choice": dfc,
        }
    )
    DB["customers"][rec["id"]] = rec
    return success(pub(rec), 201)


@app.route("/vehicle-hub/customers/<cid>", methods=["GET"])
def get_customer(cid):
    authenticate(["PlatformAdmin", "Customer", "CustomerAdvocate"])
    return success(pub(get_or_404("customers", cid, "Customer")))


@app.route("/vehicle-hub/customers", methods=["GET"])
def list_customers():
    authenticate(["PlatformAdmin", "CustomerAdvocate"])
    items = list(DB["customers"].values())
    sc = request.args.get("state_code")
    if sc is not None:
        items = [c for c in items if c["state_code"] == sc]
    items, meta = paginate(items)
    return success(items, 200, meta)


# =========================================================================
# Reconditioning centers
# =========================================================================
@app.route("/vehicle-hub/reconditioning-centers", methods=["POST"])
def create_center():
    authenticate(["PlatformAdmin"])
    data = body()
    rec = new_record(
        {
            "name": req_str(data, "name"),
            "market_code": req_str(data, "market_code"),
            "daily_capacity": req_int(data, "daily_capacity", minimum=1),
            "slot_count": req_int(data, "slot_count", minimum=1),
        }
    )
    DB["centers"][rec["id"]] = rec
    return success(pub(rec), 201)


@app.route("/vehicle-hub/reconditioning-centers/<cid>", methods=["GET"])
def get_center(cid):
    authenticate(["PlatformAdmin", "ReconOperator"])
    return success(pub(get_or_404("centers", cid, "ReconditioningCenter")))


@app.route("/vehicle-hub/reconditioning-centers", methods=["GET"])
def list_centers():
    authenticate(["PlatformAdmin", "ReconOperator"])
    items = list(DB["centers"].values())
    mc = request.args.get("market_code")
    if mc is not None:
        items = [c for c in items if c["market_code"] == mc]
    items, meta = paginate(items)
    return success(items, 200, meta)


# =========================================================================
# Vehicles
# =========================================================================
@app.route("/vehicle-hub/vehicles", methods=["POST"])
def create_vehicle():
    authenticate(["PlatformAdmin", "ReconOperator"])
    data = body()
    center_id = data.get("center_id")
    if center_id is not None:
        get_or_404("centers", center_id, "ReconditioningCenter")
    vin = req_str(data, "vin")
    if len(vin) != 17:
        err("ERR_INVALID_REQUEST", "vin must be 17 characters")
    if any(v["vin"] == vin for v in DB["vehicles"].values()):
        err("ERR_INVALID_REQUEST", "vin already exists")
    make = req_str(data, "make")
    model = req_str(data, "model")
    year = req_int(data, "year")
    mileage = req_int(data, "mileage", minimum=0)
    base_price = req_int(data, "base_price_cents", strict_positive=True)
    market_code = req_str(data, "market_code")
    rec = new_record(
        {
            "vin": vin,
            "make": make,
            "model": model,
            "year": year,
            "mileage": mileage,
            "base_price_cents": base_price,
            "market_code": market_code,
            "center_id": center_id,
            "status": "INTAKE",
            "listed_price_cents": max(base_price, MIN_LISTED_PRICE_CENTS),
            "annotation_count": 0,
        }
    )
    DB["vehicles"][rec["id"]] = rec
    if center_id is not None:
        intake = new_record(
            {
                "vehicle_id": rec["id"],
                "center_id": center_id,
                "arrived_at": None,
                "status": "PENDING_ARRIVAL",
            }
        )
        DB["intakes"][intake["id"]] = intake
    return success(pub(rec), 201)


@app.route("/vehicle-hub/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    authenticate(["PlatformAdmin", "ReconOperator", "Customer", "CustomerAdvocate", "WarrantyAdmin"])
    return success(pub(get_or_404("vehicles", vid, "Vehicle")))


@app.route("/vehicle-hub/vehicles", methods=["GET"])
def list_vehicles():
    authenticate(["PlatformAdmin", "ReconOperator", "Customer", "CustomerAdvocate", "WarrantyAdmin"])
    items = list(DB["vehicles"].values())
    for param in ("status", "market_code", "center_id"):
        val = request.args.get(param)
        if val is not None:
            items = [v for v in items if v.get(param) == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/vehicles/<vid>/start-recon", methods=["POST"])
def vehicle_start_recon(vid):
    authenticate(["ReconOperator"])
    v = get_or_404("vehicles", vid, "Vehicle")
    if v["status"] != "INTAKE":
        err("ERR_INVALID_STATE", "Vehicle must be INTAKE to start recon")
    center_id = v.get("center_id")
    if center_id is None or center_id not in DB["centers"]:
        err("ERR_NOT_FOUND", "Vehicle center_id does not reference an existing center")
    if not daily_available(center_id):
        err("ERR_RECON_CAPACITY_FULL", "Center daily capacity exhausted")
    if not slot_available(center_id, exclude_vehicle_id=vid):
        err("ERR_RECON_CAPACITY_FULL", "Center slot count exhausted")
    v["status"] = "IN_RECON"
    v["_in_work_date"] = now().date().isoformat()
    touch(v)
    return success(pub(v))


@app.route("/vehicle-hub/vehicles/<vid>/list", methods=["POST"])
def vehicle_list(vid):
    authenticate(["ReconOperator"])
    v = get_or_404("vehicles", vid, "Vehicle")
    if v["status"] != "IN_RECON":
        err("ERR_INVALID_STATE", "Vehicle must be IN_RECON to list")
    for intake in DB["intakes"].values():
        if intake["vehicle_id"] == vid and intake["status"] not in ("COMPLETE", "CANCELLED"):
            err("ERR_DEPENDENCY_NOT_READY", "Linked ReconIntake not COMPLETE or CANCELLED")
    recompute_listed(v)
    v["center_id"] = None
    v["status"] = "LISTED"
    touch(v)
    return success(pub(v))


@app.route("/vehicle-hub/vehicles/<vid>/remove", methods=["POST"])
def vehicle_remove(vid):
    authenticate(["PlatformAdmin"])
    v = get_or_404("vehicles", vid, "Vehicle")
    if v["status"] != "INTAKE":
        err("ERR_INVALID_STATE", "Only INTAKE vehicles can be removed")
    v["status"] = "REMOVED"
    touch(v)
    return success(pub(v))


# =========================================================================
# Imperfection annotations
# =========================================================================
@app.route("/vehicle-hub/vehicles/<vid>/annotations", methods=["POST"])
def create_annotation(vid):
    authenticate(["ReconOperator", "PlatformAdmin"])
    v = get_or_404("vehicles", vid, "Vehicle")
    data = body()
    rec = new_record(
        {
            "vehicle_id": vid,
            "area": req_str(data, "area"),
            "severity": req_enum(data, "severity", ("COSMETIC", "MINOR", "MODERATE", "MAJOR")),
            "deduction_cents": req_int(data, "deduction_cents", minimum=0),
            "image_count": req_int(data, "image_count", minimum=0),
            "status": "ACTIVE",
        }
    )
    DB["annotations"][rec["id"]] = rec
    if v["status"] == "LISTED":
        recompute_listed(v)
        touch(v)
    return success(pub(rec), 201)


@app.route("/vehicle-hub/vehicles/<vid>/annotations", methods=["GET"])
def list_annotations(vid):
    authenticate(["PlatformAdmin", "ReconOperator", "Customer", "CustomerAdvocate", "WarrantyAdmin"])
    get_or_404("vehicles", vid, "Vehicle")
    items = [a for a in DB["annotations"].values() if a["vehicle_id"] == vid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/annotations/<aid>/retract", methods=["POST"])
def retract_annotation(aid):
    authenticate(["PlatformAdmin"])
    a = get_or_404("annotations", aid, "ImperfectionAnnotation")
    if a["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Annotation must be ACTIVE to retract")
    a["status"] = "RETRACTED"
    touch(a)
    v = DB["vehicles"].get(a["vehicle_id"])
    if v is not None and v["status"] == "LISTED":
        recompute_listed(v)
        touch(v)
    return success(pub(a))


# =========================================================================
# Financing prequalification
# =========================================================================
@app.route("/vehicle-hub/financing/prequalify", methods=["POST"])
def prequalify():
    uid, _ = authenticate(["Customer"])
    get_or_404("customers", uid, "Customer")
    data = body()
    income = req_int(data, "annual_income_cents", minimum=0)
    band = req_enum(data, "credit_band", ("A", "B", "C", "D"))
    conservative = data.get("conservative_mode", False)
    if not isinstance(conservative, bool):
        err("ERR_INVALID_REQUEST", "conservative_mode must be a boolean")
    apr = APR_BPS[band]
    income_cap = (income * INCOME_MULTIPLIER_BPS) // 10000
    band_cap = BAND_CAP[band]
    if conservative:
        max_amount = min((income_cap * 80) // 100, (band_cap * 90) // 100)
        mode = "CONSERVATIVE"
    else:
        max_amount = min(income_cap, band_cap)
        mode = "STANDARD"
    rec = new_record(
        {
            "customer_id": uid,
            "annual_income_cents": income,
            "credit_band": band,
            "max_amount_cents": max_amount,
            "apr_bps": apr,
            "monthly_payment_cents": amortize(max_amount, apr, TERM_MONTHS),
            "pricing_mode": mode,
            "status": "PREQUALIFIED",
            "expires_at": iso(now() + timedelta(days=PREQUAL_VALID_DAYS)),
            "locked_order_id": None,
        }
    )
    DB["prequals"][rec["id"]] = rec
    return success(pub(rec), 201)


@app.route("/vehicle-hub/financing/<pid>", methods=["GET"])
def get_prequal(pid):
    authenticate(["Customer", "PlatformAdmin"])
    p = get_or_404("prequals", pid, "FinancingPrequalification")
    sweep_prequal(p)
    return success(pub(p))


@app.route("/vehicle-hub/financing", methods=["GET"])
def list_prequals():
    authenticate(["Customer", "PlatformAdmin"])
    items = list(DB["prequals"].values())
    for p in items:
        sweep_prequal(p)
    for param in ("customer_id", "status", "locked_order_id"):
        val = request.args.get(param)
        if val is not None:
            items = [p for p in items if p.get(param) == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


# =========================================================================
# Trade-in offers
# =========================================================================
@app.route("/vehicle-hub/trade-ins", methods=["POST"])
def create_tradein():
    uid, _ = authenticate(["Customer"])
    get_or_404("customers", uid, "Customer")
    data = body()
    vin = req_str(data, "vin")
    q = data.get("questionnaire")
    if not isinstance(q, dict):
        err("ERR_INVALID_REQUEST", "questionnaire must be an object")
    band = q.get("vehicle_band")
    if band not in BAND_BASE:
        err("ERR_INVALID_REQUEST", "questionnaire.vehicle_band must be ECONOMY, MID or PREMIUM")
    for f in ("accident_history", "mechanical_issues", "smoker_vehicle"):
        if not isinstance(q.get(f), bool):
            err("ERR_INVALID_REQUEST", "questionnaire.%s must be a boolean" % f)
    tire = q.get("tire_condition")
    if tire not in TIRE_RANK:
        err("ERR_INVALID_REQUEST", "questionnaire.tire_condition must be GOOD, FAIR or POOR")
    odo = q.get("odometer")
    if not is_int(odo) or odo < 0:
        err("ERR_INVALID_REQUEST", "questionnaire.odometer must be a non-negative integer")
    rec = new_record(
        {
            "customer_id": uid,
            "vin": vin,
            "questionnaire": {
                "vehicle_band": band,
                "accident_history": q["accident_history"],
                "mechanical_issues": q["mechanical_issues"],
                "tire_condition": tire,
                "odometer": odo,
                "smoker_vehicle": q["smoker_vehicle"],
            },
            "initial_offer_cents": trade_in_initial_offer(q),
            "adjusted_offer_cents": None,
            "status": "OFFERED",
            "expires_at": iso(now() + timedelta(days=TRADE_IN_VALID_DAYS)),
        }
    )
    DB["tradeins"][rec["id"]] = rec
    return success(pub(rec), 201)


@app.route("/vehicle-hub/trade-ins/<tid>", methods=["GET"])
def get_tradein(tid):
    authenticate(["Customer", "CustomerAdvocate", "PlatformAdmin"])
    t = get_or_404("tradeins", tid, "TradeInOffer")
    sweep_tradein(t)
    return success(pub(t))


@app.route("/vehicle-hub/trade-ins", methods=["GET"])
def list_tradeins():
    authenticate(["Customer", "CustomerAdvocate", "PlatformAdmin"])
    items = list(DB["tradeins"].values())
    for t in items:
        sweep_tradein(t)
    for param in ("customer_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [t for t in items if t.get(param) == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/trade-ins/<tid>/inspect", methods=["POST"])
def inspect_tradein(tid):
    authenticate(["CustomerAdvocate"])
    t = get_or_404("tradeins", tid, "TradeInOffer")
    if t["status"] != "OFFERED":
        err("ERR_INVALID_STATE", "Trade-in offer must be OFFERED to inspect")
    if now() > parse_dt(t["expires_at"]):
        t["status"] = "EXPIRED"
        touch(t)
        err("ERR_PREQUAL_EXPIRED", "Trade-in offer has expired")
    data = body()
    for f in ("accident_history_found", "mechanical_issues_found", "smoker_detected"):
        if not isinstance(data.get(f), bool):
            err("ERR_INVALID_REQUEST", "%s must be a boolean" % f)
    observed = data.get("tire_condition_observed")
    if observed not in TIRE_RANK:
        err("ERR_INVALID_REQUEST", "tire_condition_observed must be GOOD, FAIR or POOR")
    q = t["questionnaire"]
    mismatches = 0
    if data["accident_history_found"] and not q["accident_history"]:
        mismatches += 1
    if data["mechanical_issues_found"] and not q["mechanical_issues"]:
        mismatches += 1
    if data["smoker_detected"] and not q["smoker_vehicle"]:
        mismatches += 1
    if TIRE_RANK[observed] > TIRE_RANK[q["tire_condition"]]:
        mismatches += 1
    t["adjusted_offer_cents"] = trade_in_adjustment(t["initial_offer_cents"], mismatches)
    t["status"] = "INSPECTED"
    touch(t)
    return success(pub(t))


def recompute_orders_for_offer(offer, clear_link=False):
    for o in DB["orders"].values():
        if o.get("trade_in_offer_id") == offer["id"] and o["status"] in ("DRAFT", "RESERVED"):
            if clear_link:
                o["trade_in_offer_id"] = None
                v = DB["vehicles"].get(o["vehicle_id"])
                o["total_due_cents"] = compute_total_due(o, v, None) if v else o["total_due_cents"]
            else:
                v = DB["vehicles"].get(o["vehicle_id"])
                if v is not None:
                    o["total_due_cents"] = compute_total_due(o, v, offer)
            touch(o)


@app.route("/vehicle-hub/trade-ins/<tid>/confirm", methods=["POST"])
def confirm_tradein(tid):
    uid, _ = authenticate(["Customer"])
    t = get_or_404("tradeins", tid, "TradeInOffer")
    if t["status"] != "INSPECTED":
        err("ERR_INVALID_STATE", "Trade-in offer must be INSPECTED to confirm")
    own(t["customer_id"], uid)
    if now() > parse_dt(t["expires_at"]):
        err("ERR_PREQUAL_EXPIRED", "Trade-in offer has expired")
    t["status"] = "CONFIRMED"
    touch(t)
    recompute_orders_for_offer(t, clear_link=False)
    return success(pub(t))


@app.route("/vehicle-hub/trade-ins/<tid>/decline", methods=["POST"])
def decline_tradein(tid):
    uid, _ = authenticate(["Customer"])
    t = get_or_404("tradeins", tid, "TradeInOffer")
    if t["status"] != "INSPECTED":
        err("ERR_INVALID_STATE", "Trade-in offer must be INSPECTED to decline")
    own(t["customer_id"], uid)
    t["status"] = "DECLINED"
    touch(t)
    recompute_orders_for_offer(t, clear_link=True)
    return success(pub(t))


# =========================================================================
# Purchase orders
# =========================================================================
@app.route("/vehicle-hub/orders", methods=["POST"])
def create_order():
    uid, _ = authenticate(["Customer"])
    cust = get_or_404("customers", uid, "Customer")
    data = body()
    vehicle_id = req_field(data, "vehicle_id")
    v = get_or_404("vehicles", vehicle_id, "Vehicle")
    offer = None
    offer_id = data.get("trade_in_offer_id")
    if offer_id is not None:
        offer = get_or_404("tradeins", offer_id, "TradeInOffer")
    fc = req_enum(data, "fulfillment_choice", ("HOME_DELIVERY", "VENDING_MACHINE"))
    rec = new_record(
        {
            "customer_id": uid,
            "vehicle_id": vehicle_id,
            "fulfillment_choice": fc,
            "state_code": cust["state_code"],
            "trade_in_offer_id": offer_id,
            "financing_id": None,
            "status": "DRAFT",
            "payment_status": "UNPAID",
            "delivery_status": "NOT_SCHEDULED",
            "down_payment_cents": 0,
            "amount_financed_cents": 0,
            "total_due_cents": 0,
            "odometer_at_delivery": None,
            "delivered_at": None,
            "return_deadline": None,
            "return_requested_mileage": None,
            "return_reason_code": None,
            "return_inspection_result": None,
            "refund_amount_cents": None,
            "refund_processed_at": None,
            "deposit_cents": 0,
        }
    )
    rec["total_due_cents"] = compute_total_due(rec, v, offer)
    DB["orders"][rec["id"]] = rec
    return success(pub(rec), 201)


@app.route("/vehicle-hub/orders/<oid>", methods=["GET"])
def get_order(oid):
    authenticate(["Customer", "PlatformAdmin", "CustomerAdvocate", "WarrantyAdmin", "RegistrationClerk"])
    return success(pub(get_or_404("orders", oid, "PurchaseOrder")))


@app.route("/vehicle-hub/orders", methods=["GET"])
def list_orders():
    authenticate(["Customer", "PlatformAdmin", "CustomerAdvocate", "WarrantyAdmin", "RegistrationClerk"])
    items = list(DB["orders"].values())
    for param in (
        "customer_id",
        "vehicle_id",
        "trade_in_offer_id",
        "financing_id",
        "status",
        "payment_status",
        "delivery_status",
    ):
        val = request.args.get(param)
        if val is not None:
            items = [o for o in items if o.get(param) == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/orders/<oid>/fulfillment-choice", methods=["POST"])
def switch_fulfillment(oid):
    uid, _ = authenticate(["Customer"])
    o = get_or_404("orders", oid, "PurchaseOrder")
    if o["status"] not in ("DRAFT", "RESERVED"):
        err("ERR_INVALID_STATE", "Fulfillment choice can only change while DRAFT or RESERVED")
    own(o["customer_id"], uid)
    data = body()
    fc = req_enum(data, "fulfillment_choice", ("HOME_DELIVERY", "VENDING_MACHINE"))
    o["fulfillment_choice"] = fc
    touch(o)
    return success(pub(o))


@app.route("/vehicle-hub/orders/<oid>/reserve", methods=["POST"])
def reserve_order(oid):
    uid, _ = authenticate(["Customer"])
    o = get_or_404("orders", oid, "PurchaseOrder")
    v = DB["vehicles"].get(o["vehicle_id"])
    if v is None:
        err("ERR_NOT_FOUND", "Vehicle not found: %s" % o["vehicle_id"])
    data = body()
    evv = data.get("expected_vehicle_version")
    if evv is not None:
        if not is_int(evv):
            err("ERR_INVALID_REQUEST", "expected_vehicle_version must be an integer")
        if evv != v["version"]:
            err("ERR_STALE_VERSION", "Vehicle version has advanced")
    if o["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Order must be DRAFT to reserve")
    if v["status"] != "LISTED":
        err("ERR_INVALID_STATE", "Vehicle must be LISTED to reserve")
    own(o["customer_id"], uid)
    if o.get("trade_in_offer_id"):
        offer = DB["tradeins"].get(o["trade_in_offer_id"])
        if offer is None:
            err("ERR_NOT_FOUND", "TradeInOffer not found")
        sweep_tradein(offer)
        if offer["status"] not in ("OFFERED", "INSPECTED", "CONFIRMED"):
            err("ERR_INVALID_STATE", "Trade-in offer not in a reservable state")
    if evv is None:
        err("ERR_INVALID_REQUEST", "Missing required field: expected_vehicle_version")
    o["status"] = "RESERVED"
    touch(o)
    v["status"] = "RESERVED"
    touch(v)
    return success(pub(o))


@app.route("/vehicle-hub/orders/<oid>/structure", methods=["POST"])
def structure_order(oid):
    uid, _ = authenticate(["Customer"])
    o = get_or_404("orders", oid, "PurchaseOrder")
    data = body()
    prequal = None
    financing_id = data.get("financing_id")
    if financing_id is not None:
        prequal = get_or_404("prequals", financing_id, "FinancingPrequalification")
    if o["status"] != "RESERVED":
        err("ERR_INVALID_STATE", "Order must be RESERVED to structure")
    own(o["customer_id"], uid)
    if prequal is not None:
        if prequal["customer_id"] != o["customer_id"]:
            err("ERR_FORBIDDEN_OWNERSHIP", "Prequalification belongs to another customer")
        if prequal["status"] == "PREQUALIFIED" and now() > parse_dt(prequal["expires_at"]):
            prequal["status"] = "EXPIRED"
            touch(prequal)
            err("ERR_PREQUAL_EXPIRED", "Prequalification has expired")
        if prequal["status"] != "PREQUALIFIED":
            err("ERR_INVALID_STATE", "Prequalification must be PREQUALIFIED")
    offer = None
    if o.get("trade_in_offer_id"):
        offer = DB["tradeins"].get(o["trade_in_offer_id"])
        if offer is None:
            err("ERR_NOT_FOUND", "TradeInOffer not found")
        if offer["status"] == "OFFERED" and now() > parse_dt(offer["expires_at"]):
            offer["status"] = "EXPIRED"
            touch(offer)
            err("ERR_PREQUAL_EXPIRED", "Trade-in offer has expired")
    v = DB["vehicles"].get(o["vehicle_id"])
    if v is None:
        err("ERR_NOT_FOUND", "Vehicle not found")
    if o["state_code"] not in STATE_TAX_BPS:
        err("ERR_UNSUPPORTED_STATE", "state_code not supported: %s" % o["state_code"])
    total_due = compute_total_due(o, v, offer)
    down = 0
    financed = 0
    if prequal is not None:
        down_input = data.get("down_payment_cents", 0)
        if not is_int(down_input) or down_input < 0:
            err("ERR_INVALID_REQUEST", "down_payment_cents must be a non-negative integer")
        financed = total_due - down_input
        if financed > prequal["max_amount_cents"]:
            err("ERR_FINANCING_CAP_EXCEEDED", "amount_financed_cents exceeds max_amount_cents")
        if down_input < (total_due * MIN_DOWN_BPS) // 10000:
            err("ERR_DOWN_PAYMENT_TOO_LOW", "Down payment below 10 percent of total_due_cents")
        down = down_input
    if offer is not None and offer["status"] != "CONFIRMED":
        err("ERR_DEPENDENCY_NOT_READY", "Trade-in offer must be CONFIRMED to structure")
    o["down_payment_cents"] = down
    o["amount_financed_cents"] = financed
    o["total_due_cents"] = total_due
    o["financing_id"] = financing_id
    o["status"] = "STRUCTURED"
    touch(o)
    if prequal is not None:
        prequal["status"] = "LOCKED"
        prequal["locked_order_id"] = o["id"]
        touch(prequal)
    titlereg = new_record(
        {
            "order_id": o["id"],
            "vehicle_id": o["vehicle_id"],
            "state_code": o["state_code"],
            "status": "PENDING",
            "temp_tag_number": None,
            "temp_tag_expires_at": None,
            "filed_at": None,
            "registration_due_at": None,
            "missed_commitment": False,
            "processing_mode": processing_mode_for(o["state_code"]),
        }
    )
    DB["titleregs"][titlereg["id"]] = titlereg
    return success(pub(o))


@app.route("/vehicle-hub/orders/<oid>/appointments", methods=["POST"])
def book_appointment(oid):
    uid, _ = authenticate(["Customer"])
    o = get_or_404("orders", oid, "PurchaseOrder")
    data = body()
    eov = data.get("expected_order_version")
    if eov is not None:
        if not is_int(eov):
            err("ERR_INVALID_REQUEST", "expected_order_version must be an integer")
        if eov != o["version"]:
            err("ERR_STALE_VERSION", "Order version has advanced")
    if o["status"] != "STRUCTURED":
        err("ERR_INVALID_STATE", "Order must be STRUCTURED to book an appointment")
    own(o["customer_id"], uid)
    v = DB["vehicles"].get(o["vehicle_id"])
    if v is None:
        err("ERR_NOT_FOUND", "Vehicle not found")
    kind = o["fulfillment_choice"]
    market_code = data.get("market_code")
    address_region = data.get("address_region")
    vending_site_code = data.get("vending_site_code")
    start = parse_dt(data.get("start_at"))
    end = parse_dt(data.get("end_at"))
    if data.get("start_at") is not None and start is None:
        err("ERR_INVALID_REQUEST", "start_at must be a valid ISO 8601 timestamp")
    if data.get("end_at") is not None and end is None:
        err("ERR_INVALID_REQUEST", "end_at must be a valid ISO 8601 timestamp")
    # Priority 12: appointment overlap
    if start is not None and end is not None:
        for a in DB["appointments"].values():
            if a["status"] != "SCHEDULED":
                continue
            if kind == "HOME_DELIVERY":
                if a["kind"] != "HOME_DELIVERY" or a["market_code"] != market_code:
                    continue
            else:
                if a["kind"] != "VENDING_MACHINE" or a.get("vending_site_code") != vending_site_code:
                    continue
            a_s, a_e = parse_dt(a["start_at"]), parse_dt(a["end_at"])
            if start < a_e and a_s < end:
                err("ERR_APPOINTMENT_CONFLICT", "Appointment interval overlaps a scheduled appointment")
    # Priority 15: market match. (PRD names a per-market "serviceability list" for
    # address_region but never defines any list contents, so no region can be
    # determined unserviceable; only the market mismatch is derivable.)
    if market_code is not None and market_code != v["market_code"]:
        err("ERR_REGION_NOT_SERVICED", "Appointment market_code does not match vehicle market")
    # Priority 20: request shape
    if eov is None:
        err("ERR_INVALID_REQUEST", "Missing required field: expected_order_version")
    if not isinstance(market_code, str) or not market_code:
        err("ERR_INVALID_REQUEST", "market_code is required")
    if start is None:
        err("ERR_INVALID_REQUEST", "start_at is required")
    if end is None:
        err("ERR_INVALID_REQUEST", "end_at is required")
    if end <= start:
        err("ERR_INVALID_REQUEST", "end_at must be strictly after start_at")
    if kind == "HOME_DELIVERY":
        if not isinstance(address_region, str) or not address_region:
            err("ERR_INVALID_REQUEST", "address_region is required for HOME_DELIVERY")
    else:
        if not isinstance(vending_site_code, str) or not vending_site_code:
            err("ERR_INVALID_REQUEST", "vending_site_code is required for VENDING_MACHINE")
    rec = new_record(
        {
            "order_id": o["id"],
            "kind": kind,
            "market_code": market_code,
            "address_region": address_region if kind == "HOME_DELIVERY" else None,
            "vending_site_code": vending_site_code if kind == "VENDING_MACHINE" else None,
            "start_at": iso(start),
            "end_at": iso(end),
            "status": "SCHEDULED",
        }
    )
    DB["appointments"][rec["id"]] = rec
    o["status"] = "APPOINTMENT_SET"
    o["delivery_status"] = "SCHEDULED"
    touch(o)
    return success(pub(rec), 201)


@app.route("/vehicle-hub/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    authenticate(["Customer", "CustomerAdvocate", "PlatformAdmin"])
    return success(pub(get_or_404("appointments", aid, "DeliveryAppointment")))


@app.route("/vehicle-hub/appointments", methods=["GET"])
def list_appointments():
    authenticate(["Customer", "CustomerAdvocate", "PlatformAdmin"])
    items = list(DB["appointments"].values())
    for param in ("order_id", "market_code", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if a.get(param) == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


def revert_order_to_structured(order):
    if order["status"] == "APPOINTMENT_SET":
        order["status"] = "STRUCTURED"
        order["delivery_status"] = "NOT_SCHEDULED"
        touch(order)


@app.route("/vehicle-hub/appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    uid, _ = authenticate(["Customer"])
    a = get_or_404("appointments", aid, "DeliveryAppointment")
    if a["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Appointment must be SCHEDULED to cancel")
    o = DB["orders"].get(a["order_id"])
    if o is None:
        err("ERR_NOT_FOUND", "Order not found")
    own(o["customer_id"], uid)
    a["status"] = "CANCELLED"
    touch(a)
    revert_order_to_structured(o)
    return success(pub(a))


@app.route("/vehicle-hub/appointments/<aid>/no-show", methods=["POST"])
def no_show_appointment(aid):
    authenticate(["CustomerAdvocate"])
    a = get_or_404("appointments", aid, "DeliveryAppointment")
    if a["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Appointment must be SCHEDULED to mark no-show")
    if now() <= parse_dt(a["end_at"]):
        err("ERR_INVALID_STATE", "Appointment has not ended yet")
    o = DB["orders"].get(a["order_id"])
    a["status"] = "NO_SHOW"
    touch(a)
    if o is not None:
        revert_order_to_structured(o)
    return success(pub(a))


@app.route("/vehicle-hub/orders/<oid>/complete", methods=["POST"])
def complete_order(oid):
    authenticate(["PlatformAdmin"])
    o = get_or_404("orders", oid, "PurchaseOrder")
    if o["status"] != "APPOINTMENT_SET":
        err("ERR_INVALID_STATE", "Order must be APPOINTMENT_SET to complete")
    appt = None
    for a in DB["appointments"].values():
        if a["order_id"] == oid and a["status"] == "SCHEDULED":
            appt = a
            break
    if appt is None:
        err("ERR_INVALID_STATE", "No SCHEDULED appointment for this order")
    data = body()
    odometer = req_int(data, "odometer_at_delivery", minimum=0)
    if o["fulfillment_choice"] == "HOME_DELIVERY" and data.get("payment_confirmed") is not True:
        err("ERR_INVALID_REQUEST", "payment_confirmed must be true for HOME_DELIVERY completion")
    v = DB["vehicles"].get(o["vehicle_id"])
    if v is None:
        err("ERR_NOT_FOUND", "Vehicle not found")
    delivered = now()
    o["status"] = "COMPLETED"
    o["delivery_status"] = "DELIVERED"
    o["delivered_at"] = iso(delivered)
    o["odometer_at_delivery"] = odometer
    o["return_deadline"] = iso(delivered + timedelta(days=RETURN_WINDOW_DAYS))
    o["payment_status"] = "PAID" if o["amount_financed_cents"] == 0 else "FINANCED"
    o["deposit_cents"] = VENDING_DEPOSIT_CENTS if o["fulfillment_choice"] == "VENDING_MACHINE" else 0
    touch(o)
    v["status"] = "SOLD"
    touch(v)
    appt["status"] = "COMPLETED"
    touch(appt)
    for tr in DB["titleregs"].values():
        if tr["order_id"] == oid and tr["status"] == "PENDING":
            mode = processing_mode_for(o["state_code"])
            tr["status"] = "TEMP_TAG_ISSUED"
            tr["temp_tag_number"] = "TT-" + str(tr["_seq"]).zfill(8)
            tr["temp_tag_expires_at"] = iso(delivered + timedelta(days=TEMP_TAG_DAYS[mode]))
            touch(tr)
    return success(pub(o))


@app.route("/vehicle-hub/orders/<oid>/return", methods=["POST"])
def initiate_return(oid):
    uid, _ = authenticate(["Customer"])
    o = get_or_404("orders", oid, "PurchaseOrder")
    if o["status"] != "COMPLETED":
        err("ERR_INVALID_STATE", "Order must be COMPLETED to initiate a return")
    own(o["customer_id"], uid)
    data = body()
    if o.get("return_deadline") is not None and now() > parse_dt(o["return_deadline"]):
        err("ERR_RETURN_WINDOW_CLOSED", "Return window has closed")
    mileage = data.get("return_mileage")
    if not is_int(mileage):
        err("ERR_INVALID_REQUEST", "return_mileage must be an integer")
    reason = data.get("reason_code")
    if not isinstance(reason, str) or not reason:
        err("ERR_INVALID_REQUEST", "reason_code is required")
    if o.get("odometer_at_delivery") is not None:
        if mileage - o["odometer_at_delivery"] > RETURN_MILEAGE_LIMIT:
            err("ERR_MILEAGE_LIMIT_EXCEEDED", "Return mileage exceeds the 400 mile limit")
    v = DB["vehicles"].get(o["vehicle_id"])
    if v is None:
        err("ERR_NOT_FOUND", "Vehicle not found")
    o["status"] = "RETURN_INITIATED"
    o["payment_status"] = "REFUND_PENDING"
    o["return_requested_mileage"] = mileage
    o["return_reason_code"] = reason
    touch(o)
    v["status"] = "RETURN_INBOUND"
    touch(v)
    for tr in DB["titleregs"].values():
        if tr["order_id"] == oid and tr["status"] == "TEMP_TAG_ISSUED":
            tr["status"] = "BLOCKED"
            touch(tr)
    return success(pub(o))


@app.route("/vehicle-hub/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, role = authenticate(["Customer", "PlatformAdmin"])
    o = get_or_404("orders", oid, "PurchaseOrder")
    if o["status"] not in ("RESERVED", "STRUCTURED", "APPOINTMENT_SET"):
        err("ERR_INVALID_STATE", "Order cannot be cancelled from its current state")
    if role == "Customer":
        own(o["customer_id"], uid)
    was_structured = o["status"] in ("STRUCTURED", "APPOINTMENT_SET")
    was_appointment_set = o["status"] == "APPOINTMENT_SET"
    v = DB["vehicles"].get(o["vehicle_id"])
    if v is not None and v["status"] == "RESERVED":
        v["status"] = "LISTED"
        touch(v)
    if was_structured and o.get("financing_id"):
        p = DB["prequals"].get(o["financing_id"])
        if p is not None and p["status"] == "LOCKED" and p.get("locked_order_id") == oid:
            p["status"] = "PREQUALIFIED"
            p["locked_order_id"] = None
            touch(p)
    if was_structured:
        for tr in list(DB["titleregs"].values()):
            if tr["order_id"] == oid and tr["status"] == "PENDING":
                del DB["titleregs"][tr["id"]]
    if was_appointment_set:
        for a in DB["appointments"].values():
            if a["order_id"] == oid and a["status"] == "SCHEDULED":
                a["status"] = "CANCELLED"
                touch(a)
    o["status"] = "CANCELLED"
    touch(o)
    return success(pub(o))


# =========================================================================
# Return transit & intake
# =========================================================================
def find_transit_for_order(oid):
    candidates = [t for t in DB["transits"].values() if t["order_id"] == oid]
    if not candidates:
        return None
    return sorted(candidates, key=lambda t: t["_seq"])[-1]


@app.route("/vehicle-hub/returns/<order_id>/schedule-pickup", methods=["POST"])
def schedule_pickup(order_id):
    authenticate(["CustomerAdvocate"])
    o = get_or_404("orders", order_id, "PurchaseOrder")
    if o["status"] != "RETURN_INITIATED":
        err("ERR_INVALID_STATE", "Order must be RETURN_INITIATED to schedule pickup")
    v = DB["vehicles"].get(o["vehicle_id"])
    if v is None:
        err("ERR_NOT_FOUND", "Vehicle not found")
    data = body()
    start = parse_dt(data.get("start_at"))
    end = parse_dt(data.get("end_at"))
    if data.get("start_at") is not None and start is None:
        err("ERR_INVALID_REQUEST", "start_at must be a valid ISO 8601 timestamp")
    if data.get("end_at") is not None and end is None:
        err("ERR_INVALID_REQUEST", "end_at must be a valid ISO 8601 timestamp")
    # Priority 13: transit overlap with 120-minute buffer
    if start is not None and end is not None:
        buffer = timedelta(minutes=TRANSIT_BUFFER_MINUTES)
        new_buf_end = end + buffer
        for t in DB["transits"].values():
            if t["market_code"] != v["market_code"]:
                continue
            if t["status"] not in ("PICKUP_SCHEDULED", "PICKED_UP"):
                continue
            t_s = parse_dt(t["start_at"])
            t_e = parse_dt(t["end_at"]) + buffer
            if start < t_e and t_s < new_buf_end:
                err("ERR_TRANSIT_SLOT_CONFLICT", "Buffered transit interval overlaps an active transit")
    if start is None:
        err("ERR_INVALID_REQUEST", "start_at is required")
    if end is None:
        err("ERR_INVALID_REQUEST", "end_at is required")
    if end <= start:
        err("ERR_INVALID_REQUEST", "end_at must be strictly after start_at")
    rec = new_record(
        {
            "order_id": order_id,
            "vehicle_id": o["vehicle_id"],
            "market_code": v["market_code"],
            "start_at": iso(start),
            "end_at": iso(end),
            "buffer_minutes": TRANSIT_BUFFER_MINUTES,
            "status": "PICKUP_SCHEDULED",
        }
    )
    DB["transits"][rec["id"]] = rec
    return success(pub(rec), 201)


@app.route("/vehicle-hub/orders/<oid>/return-transit", methods=["GET"])
def get_order_return_transit(oid):
    authenticate(["CustomerAdvocate", "PlatformAdmin", "Customer"])
    get_or_404("orders", oid, "PurchaseOrder")
    items = [t for t in DB["transits"].values() if t["order_id"] == oid]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/returns/<order_id>/transit/pickup", methods=["POST"])
def transit_pickup(order_id):
    authenticate(["CustomerAdvocate"])
    o = get_or_404("orders", order_id, "PurchaseOrder")
    t = find_transit_for_order(order_id)
    if t is None:
        err("ERR_NOT_FOUND", "No return transit for this order")
    if o["status"] != "RETURN_INITIATED":
        err("ERR_INVALID_STATE", "Order must be RETURN_INITIATED")
    if t["status"] != "PICKUP_SCHEDULED":
        err("ERR_INVALID_STATE", "Transit must be PICKUP_SCHEDULED")
    t["status"] = "PICKED_UP"
    touch(t)
    return success(pub(t))


@app.route("/vehicle-hub/returns/<order_id>/transit/arrive", methods=["POST"])
def transit_arrive(order_id):
    authenticate(["CustomerAdvocate"])
    get_or_404("orders", order_id, "PurchaseOrder")
    t = find_transit_for_order(order_id)
    if t is None:
        err("ERR_NOT_FOUND", "No return transit for this order")
    if t["status"] != "PICKED_UP":
        err("ERR_INVALID_STATE", "Transit must be PICKED_UP")
    t["status"] = "ARRIVED_AT_CENTER"
    touch(t)
    return success(pub(t))


@app.route("/vehicle-hub/returns/<order_id>/intake", methods=["POST"])
def return_intake(order_id):
    authenticate(["CustomerAdvocate"])
    o = get_or_404("orders", order_id, "PurchaseOrder")
    if o["status"] != "RETURN_INITIATED":
        err("ERR_INVALID_STATE", "Order must be RETURN_INITIATED for intake")
    t = find_transit_for_order(order_id)
    if t is None or t["status"] != "ARRIVED_AT_CENTER":
        err("ERR_INVALID_STATE", "Return transit must be ARRIVED_AT_CENTER")
    data = body()
    result = req_enum(data, "inspection_result", ("ACCEPT", "REJECT"))
    excess_wear = data.get("excess_wear", False)
    if not isinstance(excess_wear, bool):
        err("ERR_INVALID_REQUEST", "excess_wear must be a boolean")
    v = DB["vehicles"].get(o["vehicle_id"])
    if v is None:
        err("ERR_NOT_FOUND", "Vehicle not found")
    if result == "ACCEPT":
        # Priority 22: placement selector (checked before any mutation)
        centers = [c for c in DB["centers"].values() if c["market_code"] == v["market_code"]]
        if not centers:
            err("ERR_NO_CENTER_FOR_MARKET", "No reconditioning center for market %s" % v["market_code"])
        center = sorted(centers, key=lambda c: (c["created_at"], c["_seq"]))[0]
        fee = EXCESS_WEAR_FEE_CENTS if excess_wear else 0
        refund = max(o["total_due_cents"] - fee, 0)
        o["refund_amount_cents"] = refund
        o["return_inspection_result"] = "ACCEPT"
        o["refund_processed_at"] = iso(now())
        o["payment_status"] = "REFUNDED"
        o["status"] = "RETURN_COMPLETED"
        touch(o)
        v["status"] = "INTAKE"
        v["center_id"] = center["id"]
        touch(v)
        intake = new_record(
            {
                "vehicle_id": v["id"],
                "center_id": center["id"],
                "arrived_at": None,
                "status": "PENDING_ARRIVAL",
            }
        )
        DB["intakes"][intake["id"]] = intake
        for claim in DB["claims"].values():
            if claim["order_id"] == order_id and claim["status"] in ("FILED", "UNDER_REVIEW"):
                claim["status"] = "DENIED"
                claim["review_note"] = "order returned"
                touch(claim)
        for tr in list(DB["titleregs"].values()):
            if tr["order_id"] == order_id and tr["status"] == "BLOCKED":
                del DB["titleregs"][tr["id"]]
    else:  # REJECT
        o["return_inspection_result"] = "REJECT"
        o["status"] = "COMPLETED"
        o["payment_status"] = "PAID" if o["amount_financed_cents"] == 0 else "FINANCED"
        o["return_requested_mileage"] = None
        o["return_reason_code"] = None
        touch(o)
        v["status"] = "REMOVED"
        touch(v)
        for tr in DB["titleregs"].values():
            if tr["order_id"] == order_id and tr["status"] == "BLOCKED":
                tr["status"] = "TEMP_TAG_ISSUED"
                touch(tr)
    t["status"] = "INTAKE_DONE"
    touch(t)
    return success(pub(o))


# =========================================================================
# Title & registration
# =========================================================================
@app.route("/vehicle-hub/title-registrations/<tid>/file", methods=["POST"])
def file_registration(tid):
    authenticate(["RegistrationClerk"])
    tr = get_or_404("titleregs", tid, "TitleRegistration")
    if tr["status"] != "TEMP_TAG_ISSUED":
        err("ERR_INVALID_STATE", "Registration must be TEMP_TAG_ISSUED to file")
    o = DB["orders"].get(tr["order_id"])
    if o is None:
        err("ERR_NOT_FOUND", "Order not found")
    if o["status"] != "COMPLETED":
        err("ERR_INVALID_STATE", "Order must be COMPLETED to file registration")
    if tr.get("temp_tag_expires_at") is not None and now() > parse_dt(tr["temp_tag_expires_at"]):
        err("ERR_TEMP_TAG_EXPIRED", "Temporary tag has expired")
    mode = processing_mode_for(o["state_code"])
    filed = now()
    tr["status"] = "FILED"
    tr["processing_mode"] = mode
    tr["filed_at"] = iso(filed)
    tr["registration_due_at"] = iso(filed + timedelta(days=REG_PROCESSING_DAYS[mode]))
    touch(tr)
    return success(pub(tr))


@app.route("/vehicle-hub/title-registrations/<tid>/register", methods=["POST"])
def register_registration(tid):
    authenticate(["RegistrationClerk"])
    tr = get_or_404("titleregs", tid, "TitleRegistration")
    if tr["status"] != "FILED":
        err("ERR_INVALID_STATE", "Registration must be FILED to register")
    tr["status"] = "REGISTERED"
    if tr.get("registration_due_at") is not None:
        tr["missed_commitment"] = now() > parse_dt(tr["registration_due_at"])
    else:
        tr["missed_commitment"] = False
    touch(tr)
    return success(pub(tr))


@app.route("/vehicle-hub/title-registrations/<tid>", methods=["GET"])
def get_registration(tid):
    authenticate(["RegistrationClerk", "PlatformAdmin", "CustomerAdvocate"])
    return success(pub(get_or_404("titleregs", tid, "TitleRegistration")))


@app.route("/vehicle-hub/title-registrations", methods=["GET"])
def list_registrations():
    authenticate(["RegistrationClerk", "PlatformAdmin", "CustomerAdvocate"])
    items = list(DB["titleregs"].values())
    for param in ("order_id", "vehicle_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [t for t in items if t.get(param) == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


# =========================================================================
# Defect claims & repair authorizations
# =========================================================================
@app.route("/vehicle-hub/defect-claims", methods=["POST"])
def create_claim():
    uid, _ = authenticate(["Customer"])
    data = body()
    order_id = req_field(data, "order_id")
    o = get_or_404("orders", order_id, "PurchaseOrder")
    own(o["customer_id"], uid)
    if o["status"] != "COMPLETED":
        err("ERR_INVALID_STATE", "Defect claims may only be filed against COMPLETED orders")
    description = req_str(data, "defect_description")
    area = req_str(data, "defect_area")
    mileage = data.get("current_mileage")
    if mileage is not None and (not is_int(mileage) or mileage < 0):
        err("ERR_INVALID_REQUEST", "current_mileage must be a non-negative integer")
    v = DB["vehicles"].get(o["vehicle_id"])
    disclosed_areas = set()
    if v is not None:
        disclosed_areas = {
            a["area"]
            for a in DB["annotations"].values()
            if a["vehicle_id"] == v["id"] and a["status"] == "ACTIVE"
        }
    rec = new_record(
        {
            "order_id": order_id,
            "vehicle_id": o["vehicle_id"],
            "defect_description": description,
            "defect_area": area,
            "status": "FILED",
            "disclosure_flag": "DISCLOSED" if area in disclosed_areas else "UNDISCLOSED",
            "review_note": None,
            "authorized_estimate_cents": None,
            "current_mileage": mileage,
        }
    )
    DB["claims"][rec["id"]] = rec
    return success(pub(rec), 201)


@app.route("/vehicle-hub/defect-claims/<cid>", methods=["GET"])
def get_claim(cid):
    authenticate(["Customer", "WarrantyAdmin", "PlatformAdmin"])
    return success(pub(get_or_404("claims", cid, "DefectClaim")))


@app.route("/vehicle-hub/defect-claims", methods=["GET"])
def list_claims():
    authenticate(["Customer", "WarrantyAdmin", "PlatformAdmin"])
    items = list(DB["claims"].values())
    for param in ("order_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if c.get(param) == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/defect-claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    authenticate(["WarrantyAdmin"])
    c = get_or_404("claims", cid, "DefectClaim")
    if c["status"] != "FILED":
        err("ERR_INVALID_STATE", "Claim must be FILED to review")
    o = DB["orders"].get(c["order_id"])
    if o is None:
        err("ERR_NOT_FOUND", "Order not found")
    if o["status"] != "COMPLETED":
        err("ERR_INVALID_STATE", "Order must be COMPLETED")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success(pub(c))


def latest_auth_for_claim(cid):
    auths = [a for a in DB["repairauths"].values() if a["claim_id"] == cid]
    if not auths:
        return None
    return sorted(auths, key=lambda a: a["_seq"])[-1]


@app.route("/vehicle-hub/defect-claims/<cid>/authorize", methods=["POST"])
def authorize_claim(cid):
    authenticate(["WarrantyAdmin"])
    c = get_or_404("claims", cid, "DefectClaim")
    reauth = False
    if c["status"] == "UNDER_REVIEW":
        pass
    elif c["status"] == "AUTHORIZED":
        prior = latest_auth_for_claim(cid)
        if prior is not None and prior["status"] == "VOIDED":
            reauth = True
        else:
            err("ERR_INVALID_STATE", "Claim already has an active authorization")
    else:
        err("ERR_INVALID_STATE", "Claim must be UNDER_REVIEW to authorize")
    o = DB["orders"].get(c["order_id"])
    if o is None:
        err("ERR_NOT_FOUND", "Order not found")
    if o["status"] != "COMPLETED":
        err("ERR_INVALID_STATE", "Order must be COMPLETED to authorize")
    if c["disclosure_flag"] != "UNDISCLOSED":
        err("ERR_DEFECT_DISCLOSED", "Disclosed defects are never covered")
    if o.get("delivered_at") is not None:
        if now() > parse_dt(o["delivered_at"]) + timedelta(days=WARRANTY_WINDOW_DAYS):
            err("ERR_WARRANTY_WINDOW_EXPIRED", "Warranty window has expired")
    if c.get("current_mileage") is not None and o.get("odometer_at_delivery") is not None:
        if c["current_mileage"] - o["odometer_at_delivery"] > WARRANTY_MILEAGE_LIMIT:
            err("ERR_WARRANTY_WINDOW_EXPIRED", "Warranty mileage limit exceeded")
    data = body()
    estimate = req_int(data, "estimate_cents", strict_positive=True)
    note = data.get("review_note")
    if note is not None and not isinstance(note, str):
        err("ERR_INVALID_REQUEST", "review_note must be a string")
    covered = min(estimate, WARRANTY_CLAIM_CAP_CENTS)
    auth_rec = new_record(
        {
            "claim_id": cid,
            "estimate_cents": estimate,
            "covered_amount_cents": covered,
            "deductible_cents": estimate - covered,
            "status": "ISSUED",
        }
    )
    DB["repairauths"][auth_rec["id"]] = auth_rec
    c["status"] = "AUTHORIZED"
    c["authorized_estimate_cents"] = estimate
    if note is not None:
        c["review_note"] = note
    touch(c)
    return success(pub(auth_rec))


@app.route("/vehicle-hub/defect-claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    authenticate(["WarrantyAdmin"])
    c = get_or_404("claims", cid, "DefectClaim")
    if c["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "Claim must be UNDER_REVIEW to deny")
    data = body()
    note = req_str(data, "review_note")
    c["status"] = "DENIED"
    c["review_note"] = note
    touch(c)
    return success(pub(c))


@app.route("/vehicle-hub/defect-claims/<cid>/complete-repair", methods=["POST"])
def complete_repair(cid):
    authenticate(["WarrantyAdmin"])
    c = get_or_404("claims", cid, "DefectClaim")
    if c["status"] != "AUTHORIZED":
        err("ERR_INVALID_STATE", "Claim must be AUTHORIZED to complete repair")
    auth_rec = latest_auth_for_claim(cid)
    if auth_rec is None or auth_rec["status"] != "ISSUED":
        err("ERR_INVALID_STATE", "Linked RepairAuthorization must be ISSUED")
    auth_rec["status"] = "COMPLETED"
    touch(auth_rec)
    c["status"] = "REPAIR_COMPLETE"
    touch(c)
    return success(pub(c))


@app.route("/vehicle-hub/repair-authorizations/<aid>", methods=["GET"])
def get_repair_auth(aid):
    authenticate(["WarrantyAdmin", "PlatformAdmin"])
    return success(pub(get_or_404("repairauths", aid, "RepairAuthorization")))


@app.route("/vehicle-hub/repair-authorizations", methods=["GET"])
def list_repair_auths():
    authenticate(["WarrantyAdmin", "PlatformAdmin"])
    items = list(DB["repairauths"].values())
    for param in ("claim_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if a.get(param) == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/repair-authorizations/<aid>/void", methods=["POST"])
def void_repair_auth(aid):
    authenticate(["WarrantyAdmin"])
    a = get_or_404("repairauths", aid, "RepairAuthorization")
    if a["status"] != "ISSUED":
        err("ERR_INVALID_STATE", "Authorization must be ISSUED to void")
    data = body()
    req_str(data, "reason")
    a["status"] = "VOIDED"
    touch(a)
    return success(pub(a))


# =========================================================================
# Recon intakes
# =========================================================================
@app.route("/vehicle-hub/recon-intakes", methods=["POST"])
def create_intake():
    authenticate(["ReconOperator", "PlatformAdmin"])
    data = body()
    vehicle_id = req_field(data, "vehicle_id")
    get_or_404("vehicles", vehicle_id, "Vehicle")
    center_id = req_field(data, "center_id")
    get_or_404("centers", center_id, "ReconditioningCenter")
    rec = new_record(
        {
            "vehicle_id": vehicle_id,
            "center_id": center_id,
            "arrived_at": None,
            "status": "PENDING_ARRIVAL",
        }
    )
    DB["intakes"][rec["id"]] = rec
    return success(pub(rec), 201)


@app.route("/vehicle-hub/recon-intakes/<iid>", methods=["GET"])
def get_intake(iid):
    authenticate(["ReconOperator", "PlatformAdmin"])
    return success(pub(get_or_404("intakes", iid, "ReconIntake")))


@app.route("/vehicle-hub/recon-intakes", methods=["GET"])
def list_intakes():
    authenticate(["ReconOperator", "PlatformAdmin"])
    items = list(DB["intakes"].values())
    for param in ("vehicle_id", "center_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [i for i in items if i.get(param) == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/recon-intakes/<iid>/arrive", methods=["POST"])
def intake_arrive(iid):
    authenticate(["ReconOperator"])
    intake = get_or_404("intakes", iid, "ReconIntake")
    if intake["status"] != "PENDING_ARRIVAL":
        err("ERR_INVALID_STATE", "Intake must be PENDING_ARRIVAL to arrive")
    if not slot_available(intake["center_id"], exclude_vehicle_id=intake["vehicle_id"]):
        err("ERR_RECON_CAPACITY_FULL", "Center slot count exhausted")
    intake["status"] = "RECEIVED"
    intake["arrived_at"] = iso(now())
    touch(intake)
    v = DB["vehicles"].get(intake["vehicle_id"])
    if v is not None and v["status"] == "RETURN_INBOUND":
        v["status"] = "INTAKE"
        touch(v)
    return success(pub(intake))


@app.route("/vehicle-hub/recon-intakes/<iid>/start-work", methods=["POST"])
def intake_start_work(iid):
    authenticate(["ReconOperator"])
    intake = get_or_404("intakes", iid, "ReconIntake")
    if intake["status"] != "RECEIVED":
        err("ERR_INVALID_STATE", "Intake must be RECEIVED to start work")
    if not daily_available(intake["center_id"]):
        err("ERR_RECON_CAPACITY_FULL", "Center daily capacity exhausted")
    intake["status"] = "IN_WORK"
    touch(intake)
    v = DB["vehicles"].get(intake["vehicle_id"])
    if v is not None and v["status"] in ("INTAKE", "RETURN_INBOUND"):
        v["status"] = "IN_RECON"
        v["center_id"] = intake["center_id"]
        v["_in_work_date"] = now().date().isoformat()
        touch(v)
    return success(pub(intake))


@app.route("/vehicle-hub/recon-intakes/<iid>/complete", methods=["POST"])
def intake_complete(iid):
    authenticate(["ReconOperator"])
    intake = get_or_404("intakes", iid, "ReconIntake")
    if intake["status"] != "IN_WORK":
        err("ERR_INVALID_STATE", "Intake must be IN_WORK to complete")
    v = DB["vehicles"].get(intake["vehicle_id"])
    if v is None or v["status"] != "IN_RECON":
        err("ERR_INVALID_STATE", "Vehicle must be IN_RECON")
    intake["status"] = "COMPLETE"
    touch(intake)
    return success(pub(intake))


@app.route("/vehicle-hub/recon-intakes/<iid>/cancel", methods=["POST"])
def intake_cancel(iid):
    authenticate(["PlatformAdmin"])
    intake = get_or_404("intakes", iid, "ReconIntake")
    if intake["status"] != "PENDING_ARRIVAL":
        err("ERR_INVALID_STATE", "Intake must be PENDING_ARRIVAL to cancel")
    intake["status"] = "CANCELLED"
    touch(intake)
    return success(pub(intake))


# =========================================================================
# Reverse-reachability list endpoints
# =========================================================================
@app.route("/vehicle-hub/customers/<cid>/orders", methods=["GET"])
def customer_orders(cid):
    authenticate(["Customer", "PlatformAdmin", "CustomerAdvocate"])
    get_or_404("customers", cid, "Customer")
    items = [o for o in DB["orders"].values() if o["customer_id"] == cid]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/customers/<cid>/financing", methods=["GET"])
def customer_financing(cid):
    authenticate(["Customer", "PlatformAdmin"])
    get_or_404("customers", cid, "Customer")
    items = [p for p in DB["prequals"].values() if p["customer_id"] == cid]
    for p in items:
        sweep_prequal(p)
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/customers/<cid>/trade-ins", methods=["GET"])
def customer_tradeins(cid):
    authenticate(["Customer", "CustomerAdvocate", "PlatformAdmin"])
    get_or_404("customers", cid, "Customer")
    items = [t for t in DB["tradeins"].values() if t["customer_id"] == cid]
    for t in items:
        sweep_tradein(t)
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/orders/<oid>/title-registration", methods=["GET"])
def order_title_registration(oid):
    authenticate(["RegistrationClerk", "PlatformAdmin", "CustomerAdvocate", "Customer"])
    get_or_404("orders", oid, "PurchaseOrder")
    items = [t for t in DB["titleregs"].values() if t["order_id"] == oid]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/orders/<oid>/defect-claims", methods=["GET"])
def order_defect_claims(oid):
    authenticate(["Customer", "WarrantyAdmin", "PlatformAdmin"])
    get_or_404("orders", oid, "PurchaseOrder")
    items = [c for c in DB["claims"].values() if c["order_id"] == oid]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/defect-claims/<cid>/repair-authorizations", methods=["GET"])
def claim_repair_auths(cid):
    authenticate(["WarrantyAdmin", "PlatformAdmin"])
    get_or_404("claims", cid, "DefectClaim")
    items = [a for a in DB["repairauths"].values() if a["claim_id"] == cid]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/vehicles/<vid>/recon-intakes", methods=["GET"])
def vehicle_recon_intakes(vid):
    authenticate(["ReconOperator", "PlatformAdmin"])
    get_or_404("vehicles", vid, "Vehicle")
    items = [i for i in DB["intakes"].values() if i["vehicle_id"] == vid]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/vehicles/<vid>/return-transits", methods=["GET"])
def vehicle_return_transits(vid):
    authenticate(["CustomerAdvocate", "PlatformAdmin"])
    get_or_404("vehicles", vid, "Vehicle")
    items = [t for t in DB["transits"].values() if t["vehicle_id"] == vid]
    val = request.args.get("order_id")
    if val is not None:
        items = [t for t in items if t["order_id"] == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/vehicles/<vid>/defect-claims", methods=["GET"])
def vehicle_defect_claims(vid):
    authenticate(["Customer", "WarrantyAdmin", "PlatformAdmin"])
    get_or_404("vehicles", vid, "Vehicle")
    items = [c for c in DB["claims"].values() if c["vehicle_id"] == vid]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/reconditioning-centers/<cid>/recon-intakes", methods=["GET"])
def center_recon_intakes(cid):
    authenticate(["ReconOperator", "PlatformAdmin"])
    get_or_404("centers", cid, "ReconditioningCenter")
    items = [i for i in DB["intakes"].values() if i["center_id"] == cid]
    val = request.args.get("status")
    if val is not None:
        items = [i for i in items if i["status"] == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


@app.route("/vehicle-hub/reconditioning-centers/<cid>/vehicles", methods=["GET"])
def center_vehicles(cid):
    authenticate(["ReconOperator", "PlatformAdmin"])
    get_or_404("centers", cid, "ReconditioningCenter")
    items = [v for v in DB["vehicles"].values() if v.get("center_id") == cid]
    val = request.args.get("status")
    if val is not None:
        items = [v for v in items if v["status"] == val]
    items, meta = paginate(items)
    return success(items, 200, meta)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
