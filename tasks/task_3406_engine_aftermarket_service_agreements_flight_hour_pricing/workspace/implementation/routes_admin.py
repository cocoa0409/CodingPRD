"""PlatformAdmin master-data endpoints and engine reads:
clock, operators, engines (+ nested visit/report lists).
"""
import re
from decimal import Decimal

from flask import Blueprint, request

from authz import current_caller, require_roles
from cascade import expire_agreements
from envelope import paginate, pagination_params, success
from errors import api_err
from serialize import engine_json, operator_json, report_json, visit_json
from storage import DB, new_id, next_seq, now, set_clock
from validate import as_datetime, as_enum, as_int, as_str, body, req_field

bp = Blueprint("admin", __name__)

IATA_RE = re.compile(r"^[A-Z]{2}$")
SEVERITY_TIERS = {"BENIGN", "MODERATE", "HARSH"}


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("PlatformAdmin")
    data = body()
    to_dt = as_datetime(req_field(data, "to_iso8601"), "to_iso8601")
    set_clock(to_dt)
    expire_agreements(to_dt)
    return success({}, 200)


@bp.route("/api/operators", methods=["POST"])
def create_operator():
    require_roles("PlatformAdmin")
    data = body()
    name = as_str(req_field(data, "name"), "name")
    iata = as_str(req_field(data, "iata_code"), "iata_code")
    if not IATA_RE.match(iata):
        raise api_err("ERR_INVALID_REQUEST", "iata_code must be two uppercase letters")
    rating = as_enum(req_field(data, "credit_rating"), "credit_rating", {"A", "B", "C"})
    if any(o["iata_code"] == iata for o in DB["operators"].values()):
        raise api_err("ERR_DUPLICATE_RESOURCE", "iata_code already registered")
    ts = now()
    op = {
        "id": new_id(), "name": name, "iata_code": iata, "credit_rating": rating,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    DB["operators"][op["id"]] = op
    return success(operator_json(op), 201)


@bp.route("/api/engines", methods=["POST"])
def create_engine():
    require_roles("PlatformAdmin")
    data = body()
    operator_id = as_str(req_field(data, "operator_id"), "operator_id")
    esn = as_str(req_field(data, "esn"), "esn")
    model = as_str(req_field(data, "engine_model"), "engine_model")
    tier = as_enum(req_field(data, "base_severity_tier"), "base_severity_tier", SEVERITY_TIERS)
    llp = as_int(req_field(data, "llp_remaining_cycles"), "llp_remaining_cycles")
    if llp < 0:
        raise api_err("ERR_INVALID_REQUEST", "llp_remaining_cycles must be >= 0")
    if operator_id not in DB["operators"]:
        raise api_err("ERR_OPERATOR_NOT_FOUND", "operator does not exist")
    if any(e["esn"] == esn for e in DB["engines"].values()):
        raise api_err("ERR_DUPLICATE_RESOURCE", "esn already registered")
    ts = now()
    engine = {
        "id": new_id(), "operator_id": operator_id, "esn": esn, "engine_model": model,
        "base_severity_tier": tier,
        "cumulative_flight_hours": Decimal(0), "cumulative_cycles": 0,
        "llp_remaining_cycles": llp,
        "agreement_id": None, "assumed_annual_hours": None,
        "assumed_cycles_per_month": None, "enrolled_at": None,
        "status": "IN_SERVICE", "projected_next_removal_date": None,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    DB["engines"][engine["id"]] = engine
    return success(engine_json(engine), 201)


def get_engine_or_404(engine_id):
    engine = DB["engines"].get(engine_id)
    if engine is None:
        raise api_err("ERR_ENGINE_NOT_FOUND", "engine does not exist")
    return engine


@bp.route("/api/engines/<engine_id>", methods=["GET"])
def get_engine(engine_id):
    current_caller()
    return success(engine_json(get_engine_or_404(engine_id)), 200)


@bp.route("/api/engines", methods=["GET"])
def list_engines():
    current_caller()
    limit, offset = pagination_params()
    op_filter = request.args.get("operator_id")
    ag_filter = request.args.get("agreement_id")
    engines = sorted(DB["engines"].values(), key=lambda e: (e["created_at"], e["_seq"]))
    if op_filter is not None:
        engines = [e for e in engines if e["operator_id"] == op_filter]
    if ag_filter is not None:
        engines = [e for e in engines if e["agreement_id"] == ag_filter]
    page, meta = paginate(engines, limit, offset)
    return success([engine_json(e) for e in page], 200, meta)


@bp.route("/api/engines/<engine_id>/shop-visits", methods=["GET"])
def list_engine_visits(engine_id):
    current_caller()
    get_engine_or_404(engine_id)
    limit, offset = pagination_params()
    visits = sorted(
        (v for v in DB["visits"].values() if v["engine_id"] == engine_id),
        key=lambda v: (v["created_at"], v["_seq"]),
    )
    page, meta = paginate(visits, limit, offset)
    return success([visit_json(v) for v in page], 200, meta)


@bp.route("/api/engines/<engine_id>/flight-hour-reports", methods=["GET"])
def list_engine_reports(engine_id):
    current_caller()
    get_engine_or_404(engine_id)
    limit, offset = pagination_params()
    reports = sorted(
        (r for r in DB["reports"].values() if r["engine_id"] == engine_id),
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    page, meta = paginate(reports, limit, offset)
    return success([report_json(r) for r in page], 200, meta)
