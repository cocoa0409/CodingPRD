"""Baseline routes."""
from flask import Blueprint

import db
import domain
import calc
from errors import ApiError, ok
from util import (body, new_id, now_iso, paginate_args, paginate_list,
                  parse_dt, req_int, req_number, require_roles, touch,
                  validate_rate_schedule)

bp = Blueprint("baselines", __name__)


@bp.route("/performance-contracts/<contractId>/baselines", methods=["POST"])
def create_baseline(contractId):
    require_roles("ESCOEngineer")
    c = domain.get_contract(contractId)
    data = body()
    start = parse_dt(data.get("baseline_period_start"), "baseline_period_start")
    end = parse_dt(data.get("baseline_period_end"), "baseline_period_end")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "baseline_period_end must be after baseline_period_start")
    rec = {
        "id": new_id(),
        "contract_id": c["id"],
        "baseline_period_start": start.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "baseline_period_end": end.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "annual_energy_kwh": req_int(data, "annual_energy_kwh", min_v=1),
        "rate_schedule": validate_rate_schedule(data.get("rate_schedule")),
        "heating_degree_days": req_number(data, "heating_degree_days", min_v=0),
        "cooling_degree_days": req_number(data, "cooling_degree_days", min_v=0),
        "occupancy_factor": req_number(data, "occupancy_factor", min_v=0, max_v=1, strict_min=True),
        "adjusted_annual_cost_cents": None,
        "status": "DRAFT",
        "version_tag": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.baselines[rec["id"]] = rec
    return ok(domain.ser_baseline(rec), code=201)


@bp.route("/performance-contracts/<contractId>/baselines", methods=["GET"])
def list_baselines(contractId):
    require_roles()
    c = domain.get_contract(contractId)
    limit, offset = paginate_args()
    items = [b for b in db.baselines.values() if b["contract_id"] == c["id"]]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_baseline(b) for b in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>/baselines/<baselineId>", methods=["GET"])
def get_baseline(contractId, baselineId):
    require_roles()
    _, b = domain.get_baseline(contractId, baselineId)
    return ok(domain.ser_baseline(b))


@bp.route("/performance-contracts/<contractId>/baselines/<baselineId>/submit", methods=["POST"])
def submit_baseline(contractId, baselineId):
    require_roles("ESCOEngineer")
    c, b = domain.get_baseline(contractId, baselineId)
    if b["status"] != "DRAFT":
        raise ApiError("ERR_BASELINE_NOT_DRAFT", 409, "baseline must be in DRAFT")
    if c["status"] != "AUDIT":
        raise ApiError("ERR_CONTRACT_NOT_IN_AUDIT", 409, "contract must be in AUDIT")
    # initial pass: weather deltas vs itself are zero by construction
    b["adjusted_annual_cost_cents"] = calc.baseline_adjusted_cost(
        b["annual_energy_kwh"], b["heating_degree_days"], b["cooling_degree_days"],
        b["occupancy_factor"], b["heating_degree_days"], b["cooling_degree_days"],
        b["rate_schedule"])
    b["status"] = "SUBMITTED"
    touch(b)
    return ok(domain.ser_baseline(b))


@bp.route("/performance-contracts/<contractId>/baselines/<baselineId>/approve", methods=["POST"])
def approve_baseline(contractId, baselineId):
    require_roles("OwnerRep")
    _, b = domain.get_baseline(contractId, baselineId)
    if b["status"] != "SUBMITTED":
        raise ApiError("ERR_BASELINE_NOT_SUBMITTED", 409, "baseline must be in SUBMITTED")
    b["status"] = "APPROVED"
    touch(b)
    return ok(domain.ser_baseline(b))


@bp.route("/performance-contracts/<contractId>/baselines/<baselineId>/reject", methods=["POST"])
def reject_baseline(contractId, baselineId):
    require_roles("OwnerRep")
    _, b = domain.get_baseline(contractId, baselineId)
    if b["status"] != "SUBMITTED":
        raise ApiError("ERR_BASELINE_NOT_SUBMITTED", 409, "baseline must be in SUBMITTED")
    b["status"] = "REJECTED"
    touch(b)
    return ok(domain.ser_baseline(b))
