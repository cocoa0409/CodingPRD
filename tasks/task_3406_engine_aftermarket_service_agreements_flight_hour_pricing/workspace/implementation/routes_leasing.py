"""SpareEngine pool and SpareEngineLease lifecycle: reserve (half-open overlap
+ model match), activate (in-window, visit active, spare available), return."""
from decimal import Decimal

from flask import Blueprint

from authz import check_operator_ownership, current_caller, require_roles
from calc import LEASE_DEPOSIT_USD, lease_days, windows_overlap
from envelope import paginate, pagination_params, success
from errors import api_err
from money import round2
from routes_visits import get_visit_or_404, visit_engine
from serialize import lease_json, spare_json
from storage import DB, new_id, next_seq, now, touch
from validate import as_datetime, as_number, as_str, body, req_field

bp = Blueprint("leasing", __name__)


def get_spare_or_404(spare_id):
    spare = DB["spares"].get(spare_id)
    if spare is None:
        raise api_err("ERR_SPARE_ENGINE_NOT_FOUND", "spare engine does not exist")
    return spare


def get_lease_or_404(lease_id):
    lease = DB["leases"].get(lease_id)
    if lease is None:
        raise api_err("ERR_LEASE_NOT_FOUND", "spare engine lease does not exist")
    return lease


def _lease_owner_operator(lease):
    visit = DB["visits"][lease["shop_visit_id"]]
    return visit_engine(visit)["operator_id"]


@bp.route("/api/spare-engines", methods=["POST"])
def create_spare():
    require_roles("PlatformAdmin")
    data = body()
    serial = as_str(req_field(data, "spare_serial"), "spare_serial")
    model = as_str(req_field(data, "engine_model"), "engine_model")
    rate = as_number(req_field(data, "daily_lease_rate_usd"), "daily_lease_rate_usd")
    if rate <= 0:
        raise api_err("ERR_INVALID_REQUEST", "daily_lease_rate_usd must be > 0")
    if any(s["spare_serial"] == serial for s in DB["spares"].values()):
        raise api_err("ERR_DUPLICATE_RESOURCE", "spare_serial already registered")
    ts = now()
    spare = {
        "id": new_id(), "spare_serial": serial, "engine_model": model,
        "daily_lease_rate_usd": rate, "status": "AVAILABLE",
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    DB["spares"][spare["id"]] = spare
    return success(spare_json(spare), 201)


@bp.route("/api/spare-engines/<spare_id>", methods=["GET"])
def get_spare(spare_id):
    current_caller()
    return success(spare_json(get_spare_or_404(spare_id)), 200)


@bp.route("/api/spare-engines/<spare_id>/leases", methods=["GET"])
def list_spare_leases(spare_id):
    current_caller()
    get_spare_or_404(spare_id)
    limit, offset = pagination_params()
    leases = sorted(
        (l for l in DB["leases"].values() if l["spare_engine_id"] == spare_id),
        key=lambda l: (l["created_at"], l["_seq"]),
    )
    page, meta = paginate(leases, limit, offset)
    return success([lease_json(l) for l in page], 200, meta)


@bp.route("/api/spare-engine-leases", methods=["POST"])
def create_lease():
    uid, role = require_roles("Operator")
    data = body()
    spare_id = as_str(req_field(data, "spare_engine_id"), "spare_engine_id")
    visit_id = as_str(req_field(data, "shop_visit_id"), "shop_visit_id")
    start = as_datetime(req_field(data, "start_date"), "start_date")
    end = as_datetime(req_field(data, "end_date"), "end_date")
    if not end > start:
        raise api_err("ERR_INVALID_WINDOW", "end_date must be strictly after start_date")
    spare = DB["spares"].get(spare_id)
    if spare is None:
        raise api_err("ERR_SPARE_ENGINE_NOT_FOUND", "spare engine does not exist")
    visit = DB["visits"].get(visit_id)
    if visit is None:
        raise api_err("ERR_SHOP_VISIT_NOT_FOUND", "shop visit does not exist")
    engine = visit_engine(visit)
    check_operator_ownership(uid, role, engine["operator_id"])
    for other in DB["leases"].values():
        if other["spare_engine_id"] != spare_id or other["status"] not in ("RESERVED", "ACTIVE"):
            continue
        if windows_overlap(start, end, other["start_date"], other["end_date"]):
            raise api_err("ERR_LEASE_WINDOW_OVERLAP",
                          "window overlaps another RESERVED/ACTIVE lease of the spare")
    if spare["engine_model"] != engine["engine_model"]:
        raise api_err("ERR_MODEL_MISMATCH",
                      "spare engine model does not match the visit engine's model")
    operator = DB["operators"].get(engine["operator_id"])
    days = lease_days(start, end)
    lease_cost = round2(Decimal(days) * spare["daily_lease_rate_usd"])
    deposit = Decimal(0) if (operator is not None and operator["credit_rating"] == "A") \
        else LEASE_DEPOSIT_USD
    ts = now()
    lease = {
        "id": new_id(), "spare_engine_id": spare_id, "shop_visit_id": visit_id,
        "start_date": start, "end_date": end, "status": "RESERVED",
        "lease_cost_usd": lease_cost, "deposit_usd": deposit,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    DB["leases"][lease["id"]] = lease
    return success(lease_json(lease), 201)


@bp.route("/api/spare-engine-leases/<lease_id>/activate", methods=["POST"])
def activate_lease(lease_id):
    uid, role = require_roles("Operator")
    lease = get_lease_or_404(lease_id)
    check_operator_ownership(uid, role, _lease_owner_operator(lease))
    if lease["status"] != "RESERVED":
        raise api_err("ERR_INVALID_STATE", "lease is not RESERVED")
    visit = DB["visits"][lease["shop_visit_id"]]
    if visit["status"] not in ("SCHEDULED", "INDUCTED"):
        raise api_err("ERR_INVALID_STATE", "covered visit is not SCHEDULED or INDUCTED")
    spare = DB["spares"][lease["spare_engine_id"]]
    if spare["status"] != "AVAILABLE":
        raise api_err("ERR_INVALID_STATE", "spare engine is not AVAILABLE")
    clock = now()
    if not (lease["start_date"] <= clock < lease["end_date"]):
        raise api_err("ERR_LEASE_NOT_IN_WINDOW",
                      "logical clock is outside the lease window")
    lease["status"] = "ACTIVE"
    touch(lease)
    spare["status"] = "LEASED"
    touch(spare)
    return success(lease_json(lease), 200)


@bp.route("/api/spare-engine-leases/<lease_id>/return", methods=["POST"])
def return_lease(lease_id):
    uid, role = require_roles("Operator")
    lease = get_lease_or_404(lease_id)
    check_operator_ownership(uid, role, _lease_owner_operator(lease))
    if lease["status"] != "ACTIVE":
        raise api_err("ERR_INVALID_STATE", "lease is not ACTIVE")
    spare = DB["spares"][lease["spare_engine_id"]]
    lease["status"] = "RETURNED"
    touch(lease)
    spare["status"] = "AVAILABLE"
    touch(spare)
    return success(lease_json(lease), 200)
