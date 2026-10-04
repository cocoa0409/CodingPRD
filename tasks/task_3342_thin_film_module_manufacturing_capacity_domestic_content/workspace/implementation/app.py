"""Thin-Film Module Manufacturing Capacity & Domestic Content Qualification API.

Python + Flask, in-memory only. The store starts empty on every boot; all
entities are constructed through the declared API surface. Business rules that
reference the current time read the logical clock (never wall-clock time).
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock (startup default is exactly 2026-09-01T00:00:00Z) and the
# ops quarter counter advanced by POST /v1/_ops/close_quarter.
# ---------------------------------------------------------------------------
CLOCK = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}
OPS = {"quarter": 0}

# ---------------------------------------------------------------------------
# In-memory store. No seeding of any kind.
# ---------------------------------------------------------------------------
DB = {name: {} for name in (
    "customers", "module_series", "production_lines", "capacity_reservations",
    "production_runs", "deliveries", "component_lots", "compliance_attestations",
    "recycling_obligations", "warranty_claims",
)}
_SEQ = {"n": 0}

ROLES = (
    "PlantManager", "ContractsOfficer", "CustomerAdmin", "SupplyChainAuditor",
    "ComplianceOfficer", "LogisticsCoordinator", "WarrantyAdministrator",
    "RecyclingCoordinator",
)


# ---------------------------------------------------------------------------
# Errors and response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def api_err(error_id, status, message):
    raise ApiError(error_id, status, message)


def _wall_now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n.microsecond // 1000)


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {"api_request_id": _req_id(), "api_request_timestamp": _wall_now_iso()}


def ok(data, rtype="object", status=200, page=None):
    m = _meta()
    if page:
        m.update(page)
    return jsonify({"meta": m, "response_type": rtype, "data": data}), status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return jsonify({"meta": _meta(), "response_type": "error",
                    "data": {"error_id": e.error_id, "message": e.message}}), e.status


@app.errorhandler(404)
def _handle_404(e):
    return jsonify({"meta": _meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND",
                             "message": "Resource not found"}}), 404


@app.errorhandler(405)
def _handle_405(e):
    return jsonify({"meta": _meta(), "response_type": "error",
                    "data": {"error_id": "ERR_INVALID_REQUEST",
                             "message": "Method not allowed"}}), 405


# ---------------------------------------------------------------------------
# Auth (priority 1: headers present + declared role; priority 2: role allowed)
# ---------------------------------------------------------------------------
def require_roles(*roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not uid:
        api_err("ERR_UNAUTHENTICATED", 401,
                "Missing/invalid X-User-Role or X-User-ID header")
    if role not in roles:
        api_err("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")
    return uid, role


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def q2(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(x):
    return D(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def req_fields(b, *names):
    for n in names:
        if n not in b or b[n] is None:
            api_err("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % n)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def get_or_404(coll, rid):
    rec = DB[coll].get(rid)
    if rec is None:
        api_err("ERR_NOT_FOUND", 404, "Resource not found: %s" % rid)
    return rec


def new_record():
    _SEQ["n"] += 1
    ts = _wall_now_iso()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": _SEQ["n"]}


def touch(rec):
    rec["updated_at"] = _wall_now_iso()
    rec["version"] += 1


def _conv(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [_conv(x) for x in v]
    if isinstance(v, dict):
        return {k: _conv(x) for k, x in v.items()}
    return v


def pub(rec):
    return {k: _conv(v) for k, v in rec.items() if not k.startswith("_")}


def list_response(recs):
    recs = sorted(recs, key=lambda r: r["_seq"])
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        api_err("ERR_INVALID_REQUEST", 400, "Invalid pagination parameters")
    if limit < 1 or limit > 100 or offset < 0:
        api_err("ERR_INVALID_REQUEST", 400, "Invalid pagination parameters")
    total = len(recs)
    page = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return ok([pub(r) for r in recs[offset:offset + limit]], "array", 200, page)


def parse_dt(s, fname):
    if not isinstance(s, str):
        api_err("ERR_INVALID_REQUEST", 400, "Invalid datetime: %s" % fname)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        api_err("ERR_INVALID_REQUEST", 400, "Invalid datetime: %s" % fname)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def reservations_on_line(line_id):
    return [r for r in DB["capacity_reservations"].values()
            if r["line_id"] == line_id]


def line_bucket(line_id, statuses):
    return sum((D(r["contracted_mw"]) for r in reservations_on_line(line_id)
                if r["status"] in statuses), D(0))


def line_json(line):
    committed = line_bucket(line["id"], ("ACTIVE", "CONSTRAINED"))
    reserved = line_bucket(line["id"], ("PENDING", "DEPOSIT_HELD"))
    out = pub(line)
    out["committed_capacity_mw"] = float(committed)
    out["reserved_capacity_mw"] = float(reserved)
    out["available_capacity_mw"] = float(D(line["annual_capacity_mw"])
                                         - committed - reserved)
    # Warranty pool: contracted MW of ACTIVE/CONSTRAINED reservations whose
    # deliveries carry warranty coverage (all of them, by construction).
    out["warranty_reserved_mw"] = float(committed)
    return out


TIER_FRAC = {"TIER_A": D("0.05"), "TIER_B": D("0.10"), "TIER_C": D("0.20")}


def required_deposit(res):
    cust = DB["customers"].get(res["customer_id"])
    frac = TIER_FRAC[cust["credit_tier"]] if cust else D("0.20")
    return q2(D(res["contracted_mw"]) * D(1000000)
              * D(res["price_usd_per_w"]) * frac)


def deposit_forfeiture(res):
    delivered_value = q2(D(res["delivered_mw"]) * D(1000000)
                         * D(res["price_usd_per_w"]))
    contract_value = q2(D(res["contracted_mw"]) * D(1000000)
                        * D(res["price_usd_per_w"]))
    if delivered_value >= D("0.80") * contract_value:
        return D("0.00")
    return min(D(res["deposit_usd"]), q2(D("0.15") * (contract_value
                                                      - delivered_value)))


def nominal_kwh_per_kw(series):
    w = sum((D(b["wattage"]) * D(b["fraction"])
             for b in series["bin_profile"]), D(0))
    return q2(w * D("0.85") * D(8760) * D("0.001"))


def warranty_used_on_line(line_id):
    total = D(0)
    for c in DB["warranty_claims"].values():
        if c["status"] in ("APPROVED", "PAID"):
            res = DB["capacity_reservations"].get(c["reservation_id"])
            if res and res["line_id"] == line_id:
                total += D(c["claimed_mw"])
    return total


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@app.route("/v1/customers", methods=["POST"])
def create_customer():
    require_roles("ContractsOfficer")
    b = body()
    req_fields(b, "legal_name", "credit_tier", "tax_credit_flag")
    if not isinstance(b["legal_name"], str) or not b["legal_name"]:
        api_err("ERR_INVALID_REQUEST", 400, "legal_name must be a non-empty string")
    if b["credit_tier"] not in ("TIER_A", "TIER_B", "TIER_C"):
        api_err("ERR_INVALID_REQUEST", 400, "Invalid credit_tier")
    if not isinstance(b["tax_credit_flag"], bool):
        api_err("ERR_INVALID_REQUEST", 400, "tax_credit_flag must be a boolean")
    rec = new_record()
    rec.update({"legal_name": b["legal_name"], "credit_tier": b["credit_tier"],
                "tax_credit_flag": b["tax_credit_flag"]})
    DB["customers"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)


@app.route("/v1/customers", methods=["GET"])
def list_customers():
    require_roles("ContractsOfficer", "ComplianceOfficer",
                  "WarrantyAdministrator", "RecyclingCoordinator")
    recs = list(DB["customers"].values())
    tier = request.args.get("credit_tier")
    if tier is not None:
        recs = [r for r in recs if r["credit_tier"] == tier]
    return list_response(recs)


@app.route("/v1/customers/<cid>", methods=["GET"])
def get_customer(cid):
    require_roles("ContractsOfficer", "ComplianceOfficer", "CustomerAdmin")
    return ok(pub(get_or_404("customers", cid)))


@app.route("/v1/customers/<cid>/recycling-obligations", methods=["GET"])
def customer_obligations(cid):
    require_roles("RecyclingCoordinator", "CustomerAdmin")
    get_or_404("customers", cid)
    recs = [r for r in DB["recycling_obligations"].values()
            if r["customer_id"] == cid]
    return list_response(recs)


@app.route("/v1/customers/<cid>/capacity-reservations", methods=["GET"])
def customer_reservations(cid):
    require_roles("ContractsOfficer", "CustomerAdmin")
    get_or_404("customers", cid)
    recs = [r for r in DB["capacity_reservations"].values()
            if r["customer_id"] == cid]
    return list_response(recs)


# ---------------------------------------------------------------------------
# Module series
# ---------------------------------------------------------------------------
@app.route("/v1/module-series", methods=["POST"])
def create_series():
    require_roles("PlantManager")
    b = body()
    req_fields(b, "series_code", "technology", "nominal_wattage",
               "bin_profile", "temp_coefficient")
    if not isinstance(b["series_code"], str) or not b["series_code"]:
        api_err("ERR_INVALID_REQUEST", 400, "series_code must be a non-empty string")
    if b["technology"] not in ("CDTE_THIN_FILM", "CDTE_THIN_FILM_CUTE"):
        api_err("ERR_INVALID_REQUEST", 400, "Invalid technology")
    if not is_num(b["nominal_wattage"]) or D(b["nominal_wattage"]) <= 0:
        api_err("ERR_INVALID_REQUEST", 400, "nominal_wattage must be > 0")
    if not is_num(b["temp_coefficient"]):
        api_err("ERR_INVALID_REQUEST", 400, "temp_coefficient must be a number")
    bp = b["bin_profile"]
    if not isinstance(bp, list) or not bp:
        api_err("ERR_INVALID_REQUEST", 400, "bin_profile must be a non-empty array")
    total = D(0)
    for entry in bp:
        if (not isinstance(entry, dict) or "bin_code" not in entry
                or "wattage" not in entry or "fraction" not in entry
                or not is_num(entry["wattage"]) or not is_num(entry["fraction"])):
            api_err("ERR_INVALID_REQUEST", 400, "Invalid bin_profile entry")
        total += D(entry["fraction"])
    if total != D("1.0"):
        api_err("ERR_INVALID_REQUEST", 400,
                "bin_profile fractions must sum to 1.0")
    if any(s["series_code"] == b["series_code"]
           for s in DB["module_series"].values()):
        api_err("ERR_INVALID_REQUEST", 400, "series_code must be unique")
    rec = new_record()
    rec.update({"series_code": b["series_code"], "technology": b["technology"],
                "nominal_wattage": D(b["nominal_wattage"]), "bin_profile": bp,
                "temp_coefficient": D(b["temp_coefficient"]),
                "status": "ACTIVE"})
    DB["module_series"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)


@app.route("/v1/module-series/<sid>", methods=["GET"])
def get_series(sid):
    require_roles("PlantManager", "ContractsOfficer", "CustomerAdmin",
                  "LogisticsCoordinator")
    return ok(pub(get_or_404("module_series", sid)))


@app.route("/v1/module-series/<sid>/energy-model", methods=["GET"])
def series_energy_model(sid):
    require_roles("PlantManager", "ContractsOfficer", "CustomerAdmin")
    series = get_or_404("module_series", sid)
    return ok({"nominal_kwh_per_kw": float(nominal_kwh_per_kw(series)),
               "variant": "nominal"})


@app.route("/v1/module-series/<sid>/capacity-reservations", methods=["GET"])
def series_reservations(sid):
    require_roles("PlantManager", "ContractsOfficer")
    get_or_404("module_series", sid)
    recs = [r for r in DB["capacity_reservations"].values()
            if r["series_id"] == sid]
    return list_response(recs)


@app.route("/v1/module-series/<sid>/production-runs", methods=["GET"])
def series_runs(sid):
    require_roles("PlantManager", "SupplyChainAuditor")
    get_or_404("module_series", sid)
    recs = [r for r in DB["production_runs"].values() if r["series_id"] == sid]
    return list_response(recs)


# ---------------------------------------------------------------------------
# Production lines
# ---------------------------------------------------------------------------
@app.route("/v1/production-lines", methods=["POST"])
def create_line():
    require_roles("PlantManager")
    b = body()
    req_fields(b, "line_code", "site_country", "annual_capacity_mw")
    if not isinstance(b["line_code"], str) or not b["line_code"]:
        api_err("ERR_INVALID_REQUEST", 400, "line_code must be a non-empty string")
    if not isinstance(b["site_country"], str) or not b["site_country"]:
        api_err("ERR_INVALID_REQUEST", 400, "site_country must be a non-empty string")
    if not is_num(b["annual_capacity_mw"]) or D(b["annual_capacity_mw"]) <= 0:
        api_err("ERR_INVALID_REQUEST", 400, "annual_capacity_mw must be > 0")
    if any(l["line_code"] == b["line_code"]
           for l in DB["production_lines"].values()):
        api_err("ERR_INVALID_REQUEST", 400, "line_code must be unique")
    rec = new_record()
    rec.update({"line_code": b["line_code"], "site_country": b["site_country"],
                "annual_capacity_mw": D(b["annual_capacity_mw"]),
                "ramp_quarter_index": 0, "actual_yield_rate": None,
                "qualification_tier": "PROVISIONAL", "status": "COMMISSIONING"})
    DB["production_lines"][rec["id"]] = rec
    return ok(line_json(rec), "object", 201)


@app.route("/v1/production-lines/<lid>", methods=["GET"])
def get_line(lid):
    require_roles("PlantManager", "ContractsOfficer", "ComplianceOfficer",
                  "SupplyChainAuditor", "CustomerAdmin")
    return ok(line_json(get_or_404("production_lines", lid)))


@app.route("/v1/production-lines/<lid>/commission", methods=["POST"])
def commission_line(lid):
    require_roles("PlantManager")
    line = get_or_404("production_lines", lid)
    if line["status"] != "COMMISSIONING":
        api_err("ERR_INVALID_STATE", 409,
                "Line is not in COMMISSIONING status")
    if not any(r["line_id"] == lid for r in DB["production_runs"].values()):
        api_err("ERR_LINE_NOT_COMMISSIONABLE", 422,
                "Commission requires a first-article production run")
    line["status"] = "RAMPING"
    line["ramp_quarter_index"] = 0
    touch(line)
    return ok(line_json(line))


@app.route("/v1/production-lines/<lid>/reintroduce", methods=["POST"])
def reintroduce_line(lid):
    require_roles("PlantManager")
    line = get_or_404("production_lines", lid)
    if line["status"] != "AT_CAPACITY":
        api_err("ERR_INVALID_STATE", 409, "Line is not at AT_CAPACITY")
    b = body()
    req_fields(b, "series_id")
    series = get_or_404("module_series", b["series_id"])
    if series["status"] != "ACTIVE":
        api_err("ERR_SERIES_DISCONTINUED", 422, "Series is DISCONTINUED")
    runs = [r for r in DB["production_runs"].values() if r["line_id"] == lid]
    if runs:
        latest = max(runs, key=lambda r: r["_seq"])
        if latest["series_id"] == b["series_id"]:
            api_err("ERR_INVALID_REQUEST", 400,
                    "series_id must differ from the line's most recent run")
    line["status"] = "RAMPING"
    line["ramp_quarter_index"] = 0
    line["actual_yield_rate"] = None
    touch(line)
    return ok(line_json(line))


@app.route("/v1/production-lines/<lid>/suspend", methods=["POST"])
def suspend_line(lid):
    require_roles("PlantManager")
    line = get_or_404("production_lines", lid)
    if line["status"] not in ("RAMPING", "AT_CAPACITY"):
        api_err("ERR_INVALID_STATE", 409,
                "Only RAMPING or AT_CAPACITY lines can be suspended")
    for res in reservations_on_line(lid):
        if res["status"] == "ACTIVE":
            res["status"] = "CONSTRAINED"
            touch(res)
    line["status"] = "SUSPENDED"
    touch(line)
    return ok(line_json(line))


@app.route("/v1/production-lines/<lid>/resume", methods=["POST"])
def resume_line(lid):
    require_roles("PlantManager")
    line = get_or_404("production_lines", lid)
    if line["status"] != "SUSPENDED":
        api_err("ERR_INVALID_STATE", 409, "Line is not SUSPENDED")
    for res in reservations_on_line(lid):
        if res["status"] == "CONSTRAINED":
            res["status"] = "ACTIVE"
            touch(res)
    line["status"] = "RAMPING"
    touch(line)
    return ok(line_json(line))


@app.route("/v1/production-lines/<lid>/decommission", methods=["POST"])
def decommission_line(lid):
    require_roles("PlantManager")
    line = get_or_404("production_lines", lid)
    if line["status"] not in ("COMMISSIONING", "RAMPING", "AT_CAPACITY",
                              "SUSPENDED"):
        api_err("ERR_INVALID_STATE", 409, "Line cannot be decommissioned")
    if any(r["status"] in ("PENDING", "DEPOSIT_HELD", "ACTIVE", "CONSTRAINED")
           for r in reservations_on_line(lid)):
        api_err("ERR_LINE_HAS_OPEN_RESERVATIONS", 422,
                "Line has open reservations")
    line["status"] = "DECOMMISSIONED"
    touch(line)
    return ok(line_json(line))


@app.route("/v1/production-lines/<lid>/capacity-reservations", methods=["GET"])
def line_reservations(lid):
    require_roles("PlantManager", "ContractsOfficer")
    get_or_404("production_lines", lid)
    return list_response(reservations_on_line(lid))


@app.route("/v1/production-lines/<lid>/production-runs", methods=["GET"])
def line_runs(lid):
    require_roles("PlantManager", "SupplyChainAuditor")
    get_or_404("production_lines", lid)
    recs = [r for r in DB["production_runs"].values() if r["line_id"] == lid]
    return list_response(recs)


@app.route("/v1/production-lines/<lid>/compliance-attestations",
           methods=["GET"])
def line_attestations(lid):
    require_roles("ComplianceOfficer", "ContractsOfficer", "CustomerAdmin")
    get_or_404("production_lines", lid)
    recs = [r for r in DB["compliance_attestations"].values()
            if r["line_id"] == lid]
    return list_response(recs)


# ---------------------------------------------------------------------------
# Production runs
# ---------------------------------------------------------------------------
@app.route("/v1/production-runs", methods=["POST"])
def create_run():
    require_roles("PlantManager")
    b = body()
    req_fields(b, "line_id", "series_id", "quarter", "input_modules",
               "good_modules", "bin_counts")
    line = get_or_404("production_lines", b["line_id"])
    series = get_or_404("module_series", b["series_id"])
    inp = b["input_modules"]
    good = b["good_modules"]
    counts = b["bin_counts"]
    if (not is_int(inp) or inp <= 0 or not is_int(good) or good < 0
            or good > inp):
        api_err("ERR_RUN_INCONSISTENT", 422,
                "Require 0 <= good_modules <= input_modules, input_modules > 0")
    if not is_int(b["quarter"]) or b["quarter"] != line["ramp_quarter_index"]:
        api_err("ERR_RUN_INCONSISTENT", 422,
                "quarter must equal the line's current ramp_quarter_index")
    if not isinstance(counts, list):
        api_err("ERR_RUN_INCONSISTENT", 422, "bin_counts must be an array")
    known_bins = {e["bin_code"] for e in series["bin_profile"]}
    total = 0
    for entry in counts:
        if (not isinstance(entry, dict) or "bin_code" not in entry
                or "count" not in entry or not is_int(entry["count"])
                or entry["count"] < 0):
            api_err("ERR_RUN_INCONSISTENT", 422, "Invalid bin_counts entry")
        if entry["bin_code"] not in known_bins:
            api_err("ERR_RUN_INCONSISTENT", 422,
                    "bin_code not in the series bin_profile")
        total += entry["count"]
    if total != good:
        api_err("ERR_RUN_INCONSISTENT", 422,
                "bin_counts must sum to good_modules")
    rec = new_record()
    rec.update({"line_id": b["line_id"], "series_id": b["series_id"],
                "quarter": b["quarter"], "input_modules": inp,
                "good_modules": good, "bin_counts": counts,
                "run_yield_rate": q4(D(good) / D(inp))})
    DB["production_runs"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)


# ---------------------------------------------------------------------------
# Capacity reservations
# ---------------------------------------------------------------------------
@app.route("/v1/capacity-reservations", methods=["POST"])
def create_reservation():
    uid, _ = require_roles("CustomerAdmin")
    b = body()
    req_fields(b, "customer_id", "line_id", "series_id", "delivery_year",
               "contracted_mw", "price_usd_per_w", "deposit_usd", "term_years",
               "expected_line_version")
    # Ownership (priority 3) precedes existence (priority 4).
    if b["customer_id"] != uid:
        api_err("ERR_FORBIDDEN", 403,
                "CustomerAdmin may only book for their own customer")
    line = get_or_404("production_lines", b["line_id"])
    series = get_or_404("module_series", b["series_id"])
    get_or_404("customers", b["customer_id"])
    if (not is_int(b["delivery_year"])
            or b["delivery_year"] < CLOCK["now"].year):
        api_err("ERR_INVALID_REQUEST", 400,
                "delivery_year must be >= the current year")
    if not is_num(b["contracted_mw"]) or D(b["contracted_mw"]) <= 0:
        api_err("ERR_INVALID_REQUEST", 400, "contracted_mw must be > 0")
    if not is_num(b["price_usd_per_w"]) or D(b["price_usd_per_w"]) <= 0:
        api_err("ERR_INVALID_REQUEST", 400, "price_usd_per_w must be > 0")
    if not is_num(b["deposit_usd"]) or D(b["deposit_usd"]) < 0:
        api_err("ERR_INVALID_REQUEST", 400, "deposit_usd must be >= 0")
    if not is_int(b["term_years"]) or not (1 <= b["term_years"] <= 5):
        api_err("ERR_INVALID_REQUEST", 400, "term_years must be in 1..5")
    if not is_int(b["expected_line_version"]):
        api_err("ERR_INVALID_REQUEST", 400,
                "expected_line_version must be an integer")
    if b["expected_line_version"] != line["version"]:
        api_err("ERR_STALE_VERSION", 412,
                "expected_line_version does not match the line's version")
    if series["status"] != "ACTIVE":
        api_err("ERR_SERIES_DISCONTINUED", 422, "Series is DISCONTINUED")
    rec = new_record()
    rec.update({"customer_id": b["customer_id"], "line_id": b["line_id"],
                "series_id": b["series_id"],
                "delivery_year": b["delivery_year"],
                "contracted_mw": D(b["contracted_mw"]),
                "price_usd_per_w": D(b["price_usd_per_w"]),
                "deposit_usd": D(b["deposit_usd"]),
                "term_years": b["term_years"], "delivered_mw": D(0),
                "deposit_forfeited_usd": D(0), "status": "PENDING"})
    if D(b["deposit_usd"]) < required_deposit(rec):
        api_err("ERR_DEPOSIT_INSUFFICIENT", 422,
                "deposit_usd below the credit-tier minimum")
    DB["capacity_reservations"][rec["id"]] = rec
    touch(line)  # reserved bucket grows; line version increments
    return ok(pub(rec), "object", 201)


@app.route("/v1/capacity-reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    require_roles("ContractsOfficer", "CustomerAdmin", "WarrantyAdministrator",
                  "LogisticsCoordinator")
    return ok(pub(get_or_404("capacity_reservations", rid)))


@app.route("/v1/capacity-reservations/<rid>/post-deposit", methods=["POST"])
def post_deposit(rid):
    uid, _ = require_roles("CustomerAdmin")
    res = get_or_404("capacity_reservations", rid)
    if res["customer_id"] != uid:
        api_err("ERR_FORBIDDEN", 403, "Not the owning customer")
    if res["status"] != "PENDING":
        api_err("ERR_INVALID_STATE", 409, "Reservation is not PENDING")
    if D(res["deposit_usd"]) < required_deposit(res):
        api_err("ERR_DEPOSIT_INSUFFICIENT", 422,
                "deposit_usd below the credit-tier minimum")
    res["status"] = "DEPOSIT_HELD"
    touch(res)
    return ok(pub(res))


@app.route("/v1/capacity-reservations/<rid>/activate", methods=["POST"])
def activate_reservation(rid):
    require_roles("ContractsOfficer")
    res = get_or_404("capacity_reservations", rid)
    if res["status"] != "DEPOSIT_HELD":
        api_err("ERR_INVALID_STATE", 409, "Reservation is not DEPOSIT_HELD")
    line = get_or_404("production_lines", res["line_id"])
    if line["status"] not in ("RAMPING", "AT_CAPACITY"):
        api_err("ERR_INVALID_STATE", 409,
                "Line must be RAMPING or AT_CAPACITY to activate")
    # PRD §3.4 precondition is evaluated on the pre-transition state, where
    # the DEPOSIT_HELD reservation itself counts toward reserved_capacity_mw
    # (§2.7): available = nameplate - committed - reserved, no self-exclusion.
    available = D(line["annual_capacity_mw"]) \
        - line_bucket(line["id"], ("ACTIVE", "CONSTRAINED")) \
        - line_bucket(line["id"], ("PENDING", "DEPOSIT_HELD"))
    if available < D(res["contracted_mw"]):
        api_err("ERR_CAPACITY_UNAVAILABLE", 422,
                "line.available_capacity_mw < contracted_mw")
    series = get_or_404("module_series", res["series_id"])
    if series["status"] != "ACTIVE":
        api_err("ERR_SERIES_DISCONTINUED", 422, "Series is DISCONTINUED")
    res["status"] = "ACTIVE"
    touch(res)
    touch(line)  # reserved -> committed; line version increments
    return ok(pub(res))


@app.route("/v1/capacity-reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    uid, _ = require_roles("CustomerAdmin")
    res = get_or_404("capacity_reservations", rid)
    if res["customer_id"] != uid:
        api_err("ERR_FORBIDDEN", 403, "Not the owning customer")
    if res["status"] not in ("PENDING", "DEPOSIT_HELD", "ACTIVE",
                             "CONSTRAINED"):
        api_err("ERR_INVALID_STATE", 409, "Reservation cannot be cancelled")
    if res["status"] in ("ACTIVE", "CONSTRAINED"):
        res["deposit_forfeited_usd"] = deposit_forfeiture(res)
    res["status"] = "CANCELLED"
    touch(res)
    line = DB["production_lines"].get(res["line_id"])
    if line is not None:
        touch(line)  # bucket released; line version increments
    return ok(pub(res))


@app.route("/v1/capacity-reservations/<rid>/deliveries", methods=["GET"])
def reservation_deliveries(rid):
    require_roles("CustomerAdmin", "LogisticsCoordinator", "ContractsOfficer")
    get_or_404("capacity_reservations", rid)
    recs = [r for r in DB["deliveries"].values() if r["reservation_id"] == rid]
    return list_response(recs)


@app.route("/v1/capacity-reservations/<rid>/warranty-claims", methods=["GET"])
def reservation_claims(rid):
    require_roles("WarrantyAdministrator", "CustomerAdmin", "ContractsOfficer")
    get_or_404("capacity_reservations", rid)
    recs = [r for r in DB["warranty_claims"].values()
            if r["reservation_id"] == rid]
    return list_response(recs)


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------
def _delivery_content_status(line, customer):
    if line["qualification_tier"] == "QUALIFIED" \
            and customer["tax_credit_flag"]:
        return "QUALIFIED_DOMESTIC"
    if line["qualification_tier"] == "UNQUALIFIED":
        return "NON_QUALIFYING"
    return "UNEVALUATED"


def _window_conflict(res_id, ws, we, exclude_id=None):
    for d in DB["deliveries"].values():
        if d["reservation_id"] != res_id or d["id"] == exclude_id:
            continue
        if d["schedule_status"] not in ("SCHEDULED", "RESCHEDULED"):
            continue
        # Half-open intervals: touching windows do not conflict.
        if ws < d["_we"] and d["_ws"] < we:
            return True
    return False


@app.route("/v1/deliveries", methods=["POST"])
def create_delivery():
    uid, _ = require_roles("CustomerAdmin")
    b = body()
    req_fields(b, "reservation_id", "scheduled_window_start",
               "scheduled_window_end", "volume_mw", "lot_ids")
    res = get_or_404("capacity_reservations", b["reservation_id"])
    if res["customer_id"] != uid:
        api_err("ERR_FORBIDDEN", 403, "Not the owning customer")
    if not isinstance(b["lot_ids"], list):
        api_err("ERR_INVALID_REQUEST", 400, "lot_ids must be an array")
    lots = [get_or_404("component_lots", lid) for lid in b["lot_ids"]]
    if not is_num(b["volume_mw"]) or D(b["volume_mw"]) <= 0:
        api_err("ERR_INVALID_REQUEST", 400, "volume_mw must be > 0")
    ws = parse_dt(b["scheduled_window_start"], "scheduled_window_start")
    we = parse_dt(b["scheduled_window_end"], "scheduled_window_end")
    for lot in lots:
        if lot["status"] != "VERIFIED":
            api_err("ERR_LOT_NOT_VERIFIED", 422,
                    "Every lot must be VERIFIED at scheduling time")
    if not (we > ws):
        api_err("ERR_WINDOW_OVERLAP", 409,
                "scheduled_window_end must be after scheduled_window_start")
    if _window_conflict(res["id"], ws, we):
        api_err("ERR_WINDOW_OVERLAP", 409,
                "Window overlaps a sibling SCHEDULED/RESCHEDULED window")
    used = sum((D(d["volume_mw"]) for d in DB["deliveries"].values()
                if d["reservation_id"] == res["id"]
                and d["schedule_status"] in ("SCHEDULED", "RESCHEDULED",
                                             "DELIVERED")), D(0))
    if used + D(b["volume_mw"]) > D(res["contracted_mw"]):
        api_err("ERR_VOLUME_EXCEEDS_CONTRACT", 422,
                "Cumulative delivery volume exceeds contracted_mw")
    if res["status"] != "ACTIVE":
        api_err("ERR_RESERVATION_CONSTRAINED", 409,
                "Reservation is not ACTIVE")
    line = get_or_404("production_lines", res["line_id"])
    customer = get_or_404("customers", res["customer_id"])
    rec = new_record()
    rec.update({"reservation_id": res["id"],
                "scheduled_window_start": iso_z(ws),
                "scheduled_window_end": iso_z(we),
                "volume_mw": D(b["volume_mw"]), "lot_ids": list(b["lot_ids"]),
                "schedule_status": "SCHEDULED",
                "content_status": _delivery_content_status(line, customer),
                "_ws": ws, "_we": we})
    DB["deliveries"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)


@app.route("/v1/deliveries/<did>", methods=["GET"])
def get_delivery(did):
    require_roles("CustomerAdmin", "LogisticsCoordinator", "ContractsOfficer")
    return ok(pub(get_or_404("deliveries", did)))


@app.route("/v1/deliveries/<did>", methods=["PATCH"])
def reschedule_delivery(did):
    uid, _ = require_roles("CustomerAdmin")
    d = get_or_404("deliveries", did)
    res = get_or_404("capacity_reservations", d["reservation_id"])
    if res["customer_id"] != uid:
        api_err("ERR_FORBIDDEN", 403, "Not the owning customer")
    if d["schedule_status"] != "SCHEDULED":
        api_err("ERR_INVALID_STATE", 409,
                "Only a SCHEDULED delivery can be rescheduled")
    b = body()
    req_fields(b, "scheduled_window_start", "scheduled_window_end")
    ws = parse_dt(b["scheduled_window_start"], "scheduled_window_start")
    we = parse_dt(b["scheduled_window_end"], "scheduled_window_end")
    if not (we > ws):
        api_err("ERR_WINDOW_OVERLAP", 409,
                "scheduled_window_end must be after scheduled_window_start")
    if _window_conflict(res["id"], ws, we, exclude_id=did):
        api_err("ERR_WINDOW_OVERLAP", 409,
                "Window overlaps a sibling SCHEDULED/RESCHEDULED window")
    d["scheduled_window_start"] = iso_z(ws)
    d["scheduled_window_end"] = iso_z(we)
    d["_ws"] = ws
    d["_we"] = we
    d["schedule_status"] = "RESCHEDULED"
    touch(d)
    return ok(pub(d))


@app.route("/v1/deliveries/<did>/confirm", methods=["POST"])
def confirm_delivery(did):
    require_roles("LogisticsCoordinator")
    d = get_or_404("deliveries", did)
    if d["schedule_status"] not in ("SCHEDULED", "RESCHEDULED"):
        api_err("ERR_INVALID_STATE", 409,
                "Delivery is not SCHEDULED/RESCHEDULED")
    for lid in d["lot_ids"]:
        lot = get_or_404("component_lots", lid)
        if lot["status"] != "VERIFIED":
            api_err("ERR_LOT_NOT_VERIFIED", 422,
                    "Every lot must still be VERIFIED at confirm time")
    now = CLOCK["now"]
    if not (d["_ws"] <= now <= d["_we"]):
        api_err("ERR_DELIVERY_WINDOW_NOT_OPEN", 409,
                "Logical clock is outside the scheduled window")
    res = get_or_404("capacity_reservations", d["reservation_id"])
    if res["status"] != "ACTIVE":
        api_err("ERR_RESERVATION_CONSTRAINED", 409,
                "Reservation is not ACTIVE")
    d["schedule_status"] = "DELIVERED"
    touch(d)
    res["delivered_mw"] = D(res["delivered_mw"]) + D(d["volume_mw"])
    touch(res)
    return ok(pub(d))


@app.route("/v1/deliveries/<did>/cancel", methods=["POST"])
def cancel_delivery(did):
    uid, _ = require_roles("CustomerAdmin")
    d = get_or_404("deliveries", did)
    res = get_or_404("capacity_reservations", d["reservation_id"])
    if res["customer_id"] != uid:
        api_err("ERR_FORBIDDEN", 403, "Not the owning customer")
    if d["schedule_status"] not in ("SCHEDULED", "RESCHEDULED"):
        api_err("ERR_INVALID_STATE", 409,
                "Only a SCHEDULED/RESCHEDULED delivery can be cancelled")
    d["schedule_status"] = "CANCELLED"
    touch(d)
    return ok(pub(d))


# ---------------------------------------------------------------------------
# Component lots
# ---------------------------------------------------------------------------
@app.route("/v1/component-lots", methods=["POST"])
def create_lot():
    require_roles("SupplyChainAuditor")
    b = body()
    req_fields(b, "supplier_name", "lot_code", "component_type",
               "country_of_origin", "lot_cost_usd")
    if not isinstance(b["supplier_name"], str) or not b["supplier_name"]:
        api_err("ERR_INVALID_REQUEST", 400, "supplier_name must be a string")
    if not isinstance(b["lot_code"], str) or not b["lot_code"]:
        api_err("ERR_INVALID_REQUEST", 400, "lot_code must be a string")
    if b["component_type"] not in ("SEMICONDUCTOR_FEEDSTOCK", "GLASS",
                                   "BACKSHEET", "FRAME", "JUNCTION_BOX"):
        api_err("ERR_INVALID_REQUEST", 400, "Invalid component_type")
    if not isinstance(b["country_of_origin"], str) or not b["country_of_origin"]:
        api_err("ERR_INVALID_REQUEST", 400, "country_of_origin must be a string")
    if not is_num(b["lot_cost_usd"]) or D(b["lot_cost_usd"]) < 0:
        api_err("ERR_INVALID_REQUEST", 400, "lot_cost_usd must be >= 0")
    if any(l["lot_code"] == b["lot_code"] for l in DB["component_lots"].values()):
        api_err("ERR_INVALID_REQUEST", 400, "lot_code must be unique")
    rec = new_record()
    rec.update({"supplier_name": b["supplier_name"], "lot_code": b["lot_code"],
                "component_type": b["component_type"],
                "country_of_origin": b["country_of_origin"],
                "lot_cost_usd": D(b["lot_cost_usd"]),
                "status": "PENDING_INSPECTION"})
    DB["component_lots"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)


@app.route("/v1/component-lots/<lid>", methods=["GET"])
def get_lot(lid):
    require_roles("PlantManager", "SupplyChainAuditor", "ComplianceOfficer",
                  "ContractsOfficer", "CustomerAdmin", "LogisticsCoordinator",
                  "WarrantyAdministrator", "RecyclingCoordinator")
    return ok(pub(get_or_404("component_lots", lid)))


@app.route("/v1/component-lots/<lid>/verify", methods=["POST"])
def verify_lot(lid):
    require_roles("SupplyChainAuditor")
    lot = get_or_404("component_lots", lid)
    if lot["status"] not in ("PENDING_INSPECTION", "QUARANTINED"):
        api_err("ERR_INVALID_STATE", 409,
                "Only PENDING_INSPECTION or QUARANTINED lots can be verified")
    lot["status"] = "VERIFIED"
    touch(lot)
    return ok(pub(lot))


@app.route("/v1/component-lots/<lid>/quarantine", methods=["POST"])
def quarantine_lot(lid):
    require_roles("SupplyChainAuditor")
    lot = get_or_404("component_lots", lid)
    if lot["status"] not in ("PENDING_INSPECTION", "VERIFIED"):
        api_err("ERR_INVALID_STATE", 409,
                "Only PENDING_INSPECTION or VERIFIED lots can be quarantined")
    was_verified = lot["status"] == "VERIFIED"
    lot["status"] = "QUARANTINED"
    touch(lot)
    if was_verified:
        # Traceability cascade hop 2: recall every live delivery that
        # referenced this lot and mark its content non-qualifying.
        for d in DB["deliveries"].values():
            if lid in d["lot_ids"] and d["schedule_status"] in (
                    "SCHEDULED", "RESCHEDULED"):
                d["schedule_status"] = "RECALLED"
                d["content_status"] = "NON_QUALIFYING"
                touch(d)
    return ok(pub(lot))


# ---------------------------------------------------------------------------
# Compliance attestations
# ---------------------------------------------------------------------------
_COST_FIELDS = ("labor_cost_usd", "feedstock_cost_usd", "glass_cost_usd",
                "balance_of_system_cost_usd", "overhead_cost_usd")


@app.route("/v1/compliance-attestations", methods=["POST"])
def create_attestation():
    require_roles("ComplianceOfficer")
    b = body()
    req_fields(b, "line_id", "period_year", *_COST_FIELDS,
               "total_manufactured_cost_usd")
    get_or_404("production_lines", b["line_id"])
    if not is_int(b["period_year"]):
        api_err("ERR_INVALID_REQUEST", 400, "period_year must be an integer")
    for f in _COST_FIELDS + ("total_manufactured_cost_usd",):
        if not is_num(b[f]) or D(b[f]) < 0:
            api_err("ERR_INVALID_REQUEST", 400, "%s must be >= 0" % f)
    domestic = sum((D(b[f]) for f in _COST_FIELDS), D(0))
    if D(b["total_manufactured_cost_usd"]) < domestic:
        api_err("ERR_INVALID_REQUEST", 400,
                "total_manufactured_cost_usd must be >= sum of domestic parts")
    rec = new_record()
    rec.update({"line_id": b["line_id"], "period_year": b["period_year"],
                "labor_cost_usd": D(b["labor_cost_usd"]),
                "feedstock_cost_usd": D(b["feedstock_cost_usd"]),
                "glass_cost_usd": D(b["glass_cost_usd"]),
                "balance_of_system_cost_usd":
                    D(b["balance_of_system_cost_usd"]),
                "overhead_cost_usd": D(b["overhead_cost_usd"]),
                "total_manufactured_cost_usd":
                    D(b["total_manufactured_cost_usd"]),
                "printed_content_pct": None, "adjusted_content_pct": None,
                "manufactured_products_pct": None, "status": "DRAFT"})
    DB["compliance_attestations"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)


@app.route("/v1/compliance-attestations/<aid>/submit", methods=["POST"])
def submit_attestation(aid):
    require_roles("ComplianceOfficer")
    att = get_or_404("compliance_attestations", aid)
    if att["status"] != "DRAFT":
        api_err("ERR_INVALID_STATE", 409, "Attestation is not DRAFT")
    domestic = sum((D(att[f]) for f in _COST_FIELDS), D(0))
    total = D(att["total_manufactured_cost_usd"])
    if total < domestic:
        api_err("ERR_INVALID_REQUEST", 400,
                "total_manufactured_cost_usd must be >= sum of domestic parts")
    line = get_or_404("production_lines", att["line_id"])
    # Pinned order: manufactured_products_pct (VERIFIED lots only, domestic
    # origin == line site country), then printed, then adjusted.
    verified = [l for l in DB["component_lots"].values()
                if l["status"] == "VERIFIED"]
    lot_total = sum((D(l["lot_cost_usd"]) for l in verified), D(0))
    lot_domestic = sum((D(l["lot_cost_usd"]) for l in verified
                        if l["country_of_origin"] == line["site_country"]),
                       D(0))
    att["manufactured_products_pct"] = (
        q4(lot_domestic / lot_total) if lot_total > 0 else D("0.0000"))
    att["printed_content_pct"] = (
        q4(domestic / total) if total > 0 else D("0.0000"))
    att["adjusted_content_pct"] = q4((domestic + D("4.0")) / (total + D("4.0")))
    att["status"] = "SUBMITTED"
    touch(att)
    return ok(pub(att))


@app.route("/v1/compliance-attestations/<aid>/adjudicate", methods=["POST"])
def adjudicate_attestation(aid):
    require_roles("ComplianceOfficer")
    att = get_or_404("compliance_attestations", aid)
    if att["status"] != "SUBMITTED":
        api_err("ERR_INVALID_STATE", 409, "Attestation is not SUBMITTED")
    b = body()
    req_fields(b, "outcome")
    if b["outcome"] not in ("QUALIFY", "REJECT"):
        api_err("ERR_INVALID_REQUEST", 400, "outcome must be QUALIFY or REJECT")
    line = get_or_404("production_lines", att["line_id"])
    line_res_ids = {r["id"] for r in reservations_on_line(line["id"])}
    if b["outcome"] == "QUALIFY":
        if D(att["manufactured_products_pct"]) < D("0.40") \
                or D(att["printed_content_pct"]) < D("0.40"):
            api_err("ERR_CONTENT_THRESHOLD_NOT_MET", 422,
                    "Content thresholds not met; adjudication must be REJECT")
        att["status"] = "QUALIFIED"
        line["qualification_tier"] = "QUALIFIED"
        for d in DB["deliveries"].values():
            if d["reservation_id"] in line_res_ids and \
                    d["schedule_status"] in ("SCHEDULED", "RESCHEDULED"):
                res = DB["capacity_reservations"][d["reservation_id"]]
                cust = DB["customers"].get(res["customer_id"])
                if cust and cust["tax_credit_flag"]:
                    d["content_status"] = "QUALIFIED_DOMESTIC"
                    touch(d)
    else:
        att["status"] = "REJECTED"
        line["qualification_tier"] = "UNQUALIFIED"
        for d in DB["deliveries"].values():
            if d["reservation_id"] in line_res_ids and \
                    d["schedule_status"] in ("SCHEDULED", "RESCHEDULED"):
                d["content_status"] = "NON_QUALIFYING"
                touch(d)
    touch(att)
    touch(line)
    return ok(pub(att))


# ---------------------------------------------------------------------------
# Recycling obligations
# ---------------------------------------------------------------------------
def _fulfillment(ob):
    req = D(ob["required_collected_mw"])
    if req == 0:
        return D("1.0000")
    return q4(D(ob["collected_volume_mw"]) / req)


@app.route("/v1/recycling-obligations", methods=["POST"])
def create_obligation():
    require_roles("RecyclingCoordinator")
    b = body()
    req_fields(b, "customer_id", "period_year", "shipped_volume_mw")
    get_or_404("customers", b["customer_id"])
    if not is_int(b["period_year"]):
        api_err("ERR_INVALID_REQUEST", 400, "period_year must be an integer")
    if not is_num(b["shipped_volume_mw"]) or D(b["shipped_volume_mw"]) < 0:
        api_err("ERR_INVALID_REQUEST", 400, "shipped_volume_mw must be >= 0")
    rec = new_record()
    rec.update({"customer_id": b["customer_id"],
                "period_year": b["period_year"],
                "shipped_volume_mw": D(b["shipped_volume_mw"]),
                "required_collected_mw": q4(D(b["shipped_volume_mw"])
                                            * D("0.90")),
                "collected_volume_mw": D(0), "status": "OPEN"})
    rec["fulfillment_pct"] = _fulfillment(rec)
    DB["recycling_obligations"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)


@app.route("/v1/recycling-obligations/<oid>/collections", methods=["POST"])
def record_collection(oid):
    require_roles("RecyclingCoordinator")
    ob = get_or_404("recycling_obligations", oid)
    if ob["status"] not in ("OPEN", "COLLECTING"):
        api_err("ERR_INVALID_STATE", 409,
                "Obligation is not open for collections")
    b = body()
    req_fields(b, "volume_mw")
    if not is_num(b["volume_mw"]) or D(b["volume_mw"]) <= 0:
        api_err("ERR_INVALID_REQUEST", 400, "volume_mw must be > 0")
    ob["collected_volume_mw"] = D(ob["collected_volume_mw"]) + D(b["volume_mw"])
    ob["fulfillment_pct"] = _fulfillment(ob)
    ob["status"] = "COLLECTING"
    if D(ob["fulfillment_pct"]) >= D("1.0"):
        ob["status"] = "RECOVERED"
    touch(ob)
    return ok(pub(ob), "object", 201)


@app.route("/v1/recycling-obligations/<oid>/settle", methods=["POST"])
def settle_obligation(oid):
    require_roles("RecyclingCoordinator")
    ob = get_or_404("recycling_obligations", oid)
    if ob["status"] == "RECOVERED":
        ob["status"] = "SETTLED"
    elif ob["status"] == "OPEN" and D(ob["required_collected_mw"]) == 0:
        ob["status"] = "SETTLED"
    elif ob["status"] in ("OPEN", "COLLECTING"):
        api_err("ERR_OBLIGATION_NOT_MET", 422,
                "Obligation must be RECOVERED before settlement")
    else:
        api_err("ERR_INVALID_STATE", 409, "Obligation already settled")
    touch(ob)
    return ok(pub(ob))


# ---------------------------------------------------------------------------
# Warranty claims
# ---------------------------------------------------------------------------
@app.route("/v1/warranty-claims", methods=["POST"])
def create_claim():
    uid, _ = require_roles("CustomerAdmin")
    b = body()
    req_fields(b, "reservation_id", "claim_type", "claimed_mw")
    res = get_or_404("capacity_reservations", b["reservation_id"])
    if res["customer_id"] != uid:
        api_err("ERR_FORBIDDEN", 403,
                "Claims may only be filed against one's own reservations")
    if b["claim_type"] not in ("PRODUCT_DEFECT", "PERFORMANCE_SHORTFALL"):
        api_err("ERR_INVALID_REQUEST", 400, "Invalid claim_type")
    if not is_num(b["claimed_mw"]) or D(b["claimed_mw"]) <= 0:
        api_err("ERR_INVALID_REQUEST", 400, "claimed_mw must be > 0")
    has_measured = "measured_energy_kwh" in b \
        and b["measured_energy_kwh"] is not None
    if b["claim_type"] == "PERFORMANCE_SHORTFALL":
        if not has_measured or not is_num(b["measured_energy_kwh"]):
            api_err("ERR_INVALID_REQUEST", 400,
                    "measured_energy_kwh is required for PERFORMANCE_SHORTFALL")
    elif has_measured:
        api_err("ERR_INVALID_REQUEST", 400,
                "measured_energy_kwh is forbidden for PRODUCT_DEFECT")
    rec = new_record()
    rec.update({"reservation_id": b["reservation_id"],
                "claim_type": b["claim_type"],
                "claimed_mw": D(b["claimed_mw"]),
                "measured_energy_kwh": (D(b["measured_energy_kwh"])
                                        if has_measured else None),
                "claim_amount_usd": None, "status": "FILED"})
    DB["warranty_claims"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)


@app.route("/v1/warranty-claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    require_roles("WarrantyAdministrator")
    claim = get_or_404("warranty_claims", cid)
    if claim["status"] != "FILED":
        api_err("ERR_INVALID_STATE", 409, "Claim is not FILED")
    res = get_or_404("capacity_reservations", claim["reservation_id"])
    if res["status"] not in ("ACTIVE", "CONSTRAINED", "COMPLETED"):
        api_err("ERR_CLAIM_ON_CANCELLED", 409,
                "Reservation is not reviewable (status %s)" % res["status"])
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok(pub(claim))


@app.route("/v1/warranty-claims/<cid>/request-info", methods=["POST"])
def request_info_claim(cid):
    require_roles("WarrantyAdministrator")
    claim = get_or_404("warranty_claims", cid)
    if claim["status"] != "UNDER_REVIEW":
        api_err("ERR_INVALID_STATE", 409, "Claim is not UNDER_REVIEW")
    claim["status"] = "FILED"
    touch(claim)
    return ok(pub(claim))


@app.route("/v1/warranty-claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    require_roles("WarrantyAdministrator")
    claim = get_or_404("warranty_claims", cid)
    if claim["status"] != "UNDER_REVIEW":
        api_err("ERR_INVALID_STATE", 409, "Claim is not UNDER_REVIEW")
    b = body()
    req_fields(b, "outcome")
    if b["outcome"] not in ("APPROVE", "DENY"):
        api_err("ERR_INVALID_REQUEST", 400, "outcome must be APPROVE or DENY")
    if b["outcome"] == "DENY":
        claim["status"] = "DENIED"
        touch(claim)
        return ok(pub(claim))
    res = get_or_404("capacity_reservations", claim["reservation_id"])
    # Gate 1: performance shortfall must actually be below the guarantee.
    if claim["claim_type"] == "PERFORMANCE_SHORTFALL":
        guaranteed = q2(D(claim["claimed_mw"]) * D(1000) * D("1700.0"))
        measured = D(claim["measured_energy_kwh"])
        if measured >= guaranteed:
            api_err("ERR_INVALID_REQUEST", 400,
                    "Measured energy meets the guarantee; claim must be denied")
        amount = q2((guaranteed - measured) * D("0.05"))
    else:
        amount = q2(D(claim["claimed_mw"]) * D(res["price_usd_per_w"]))
    # Gate 2: line-level warranty capacity cap (exactly at cap passes).
    line = get_or_404("production_lines", res["line_id"])
    cap = q4(D("0.10") * D(line["annual_capacity_mw"]))
    if warranty_used_on_line(line["id"]) + D(claim["claimed_mw"]) > cap:
        api_err("ERR_WARRANTY_CAP_EXCEEDED", 422,
                "Approval would exceed the line warranty capacity cap")
    claim["claim_amount_usd"] = amount
    claim["status"] = "APPROVED"
    touch(claim)
    return ok(pub(claim))


@app.route("/v1/warranty-claims/<cid>/pay", methods=["POST"])
def pay_claim(cid):
    require_roles("WarrantyAdministrator")
    claim = get_or_404("warranty_claims", cid)
    if claim["status"] != "APPROVED":
        api_err("ERR_INVALID_STATE", 409, "Claim is not APPROVED")
    claim["status"] = "PAID"
    touch(claim)
    return ok(pub(claim))


@app.route("/v1/warranty-claims/<cid>/withdraw", methods=["POST"])
def withdraw_claim(cid):
    uid, _ = require_roles("CustomerAdmin")
    claim = get_or_404("warranty_claims", cid)
    res = get_or_404("capacity_reservations", claim["reservation_id"])
    if res["customer_id"] != uid:
        api_err("ERR_FORBIDDEN", 403, "Not the owning customer")
    if claim["status"] not in ("FILED", "UNDER_REVIEW"):
        api_err("ERR_INVALID_STATE", 409,
                "Only FILED or UNDER_REVIEW claims can be withdrawn")
    claim["status"] = "WITHDRAWN"
    touch(claim)
    return ok(pub(claim))


# ---------------------------------------------------------------------------
# Test-driving endpoints: logical clock and quarter close
# ---------------------------------------------------------------------------
@app.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlantManager")
    b = body()
    req_fields(b, "to_iso8601")
    dt = parse_dt(b["to_iso8601"], "to_iso8601")
    CLOCK["now"] = dt
    return ok({"current_utc": iso_z(dt)})


@app.route("/v1/_ops/close_quarter", methods=["POST"])
def close_quarter():
    require_roles("PlantManager")
    closed = OPS["quarter"]
    promoted = 0
    for line in list(DB["production_lines"].values()):
        if line["status"] != "RAMPING":
            continue
        q = line["ramp_quarter_index"]
        runs = [r for r in DB["production_runs"].values()
                if r["line_id"] == line["id"] and r["quarter"] == q]
        promote = False
        if runs:
            total_in = sum(r["input_modules"] for r in runs)
            total_good = sum(r["good_modules"] for r in runs)
            actual = q4(D(total_good) / D(total_in))
            line["actual_yield_rate"] = actual
            # Promotion is judged on the just-closed quarter and the
            # pre-increment ramp index.
            if actual >= D("0.85") and q >= 2:
                promote = True
        # An empty quarter leaves actual_yield_rate untouched (null stays
        # null) and never promotes, but the index still advances.
        line["ramp_quarter_index"] = q + 1
        if promote:
            line["status"] = "AT_CAPACITY"
            promoted += 1
        touch(line)
    # Reservation close-out sweep: term fully elapsed when the logical-clock
    # year is strictly greater than delivery_year + term_years - 1.
    completed = 0
    year = CLOCK["now"].year
    for res in list(DB["capacity_reservations"].values()):
        if res["status"] == "ACTIVE" \
                and year > res["delivery_year"] + res["term_years"] - 1:
            res["deposit_forfeited_usd"] = deposit_forfeiture(res)
            res["status"] = "COMPLETED"
            touch(res)
            line = DB["production_lines"].get(res["line_id"])
            if line is not None:
                touch(line)
            completed += 1
    OPS["quarter"] = closed + 1
    return ok({"closed_quarter": closed, "lines_promoted": promoted,
               "reservations_completed": completed})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
