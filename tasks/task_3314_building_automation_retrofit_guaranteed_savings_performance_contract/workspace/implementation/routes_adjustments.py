"""BaselineAdjustment routes."""
from flask import Blueprint

import db
import domain
import calc
from errors import ApiError, ok
from util import (body, new_id, now_iso, opt_number, paginate_args, paginate_list,
                  req_enum, req_int, require_roles, touch)

bp = Blueprint("adjustments", __name__)

REASONS = ("FACILITY_EXPANSION", "FACILITY_REDUCTION", "OCCUPANCY_CHANGE",
           "EQUIPMENT_CHANGE", "RATE_CHANGE")


@bp.route("/performance-contracts/<contractId>/baseline-adjustments", methods=["POST"])
def create_adjustment(contractId):
    require_roles("ESCOEngineer")
    c = domain.get_contract(contractId)
    data = body()
    baseline_id = data.get("baseline_id")
    if not isinstance(baseline_id, str) or baseline_id not in db.baselines \
            or db.baselines[baseline_id]["contract_id"] != c["id"]:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", 404,
                       "baseline_id does not resolve under the contract")
    supersedes = data.get("supersedes_adjustment_id")
    if supersedes is not None:
        if not isinstance(supersedes, str) or supersedes not in db.adjustments \
                or db.adjustments[supersedes]["contract_id"] != c["id"]:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", 404,
                           "supersedes_adjustment_id does not resolve")
    rec = {
        "id": new_id(),
        "contract_id": c["id"],
        "baseline_id": baseline_id,
        "supersedes_adjustment_id": supersedes,
        "reason": req_enum(data, "reason", REASONS),
        "kwh_delta": req_int(data, "kwh_delta"),
        "occupancy_factor_override": opt_number(data, "occupancy_factor_override",
                                                min_v=0, max_v=1, strict_min=True),
        "status": "PROPOSED",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.adjustments[rec["id"]] = rec
    return ok(domain.ser_adjustment(rec), code=201)


@bp.route("/performance-contracts/<contractId>/baseline-adjustments", methods=["GET"])
def list_adjustments(contractId):
    require_roles()
    c = domain.get_contract(contractId)
    limit, offset = paginate_args()
    items = [a for a in db.adjustments.values() if a["contract_id"] == c["id"]]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_adjustment(a) for a in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>/baseline-adjustments/<adjustmentId>", methods=["GET"])
def get_adjustment(contractId, adjustmentId):
    require_roles()
    _, a = domain.get_adjustment(contractId, adjustmentId)
    return ok(domain.ser_adjustment(a))


@bp.route("/performance-contracts/<contractId>/baseline-adjustments/<adjustmentId>/approve", methods=["POST"])
def approve_adjustment(contractId, adjustmentId):
    require_roles("OwnerRep")
    c, a = domain.get_adjustment(contractId, adjustmentId)
    if a["status"] != "PROPOSED":
        raise ApiError("ERR_ADJUSTMENT_NOT_PROPOSED", 409, "adjustment must be in PROPOSED")
    baseline = db.baselines.get(a["baseline_id"])
    if baseline is None or baseline["status"] not in ("LOCKED", "RESTATED"):
        raise ApiError("ERR_BASELINE_NOT_LOCKED", 409,
                       "baseline must be in LOCKED or RESTATED")
    approved = [x for x in db.adjustments.values()
                if x["baseline_id"] == baseline["id"] and x["status"] == "APPROVED"]
    latest = None
    if approved:
        latest = sorted(approved, key=lambda x: (x["created_at"], x["id"]))[-1]["id"]
    if a["supersedes_adjustment_id"] != latest:
        raise ApiError("ERR_STALE_ADJUSTMENT_CHAIN", 409,
                       "supersedes_adjustment_id must equal the latest APPROVED adjustment")
    data = body()
    expected = data.get("expected_baseline_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_baseline_version is required and must be an integer")
    if expected != baseline["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_baseline_version does not match the baseline version")
    if baseline["annual_energy_kwh"] + a["kwh_delta"] <= 0:
        raise ApiError("ERR_BASELINE_WOULD_GO_NONPOSITIVE", 422,
                       "the resulting annual_energy_kwh must remain > 0")

    # restatement: weather deviations compare against PRE-adjustment stored HDD/CDD
    pre_hdd = baseline["heating_degree_days"]
    pre_cdd = baseline["cooling_degree_days"]
    baseline["annual_energy_kwh"] += a["kwh_delta"]
    if a.get("occupancy_factor_override") is not None:
        baseline["occupancy_factor"] = a["occupancy_factor_override"]
    baseline["adjusted_annual_cost_cents"] = calc.baseline_adjusted_cost(
        baseline["annual_energy_kwh"], pre_hdd, pre_cdd, baseline["occupancy_factor"],
        pre_hdd, pre_cdd, baseline["rate_schedule"])
    baseline["version_tag"] += 1
    baseline["status"] = "RESTATED"
    touch(baseline)

    a["status"] = "APPROVED"
    touch(a)

    for r in db.reports.values():
        if r["contract_id"] == c["id"] and r["status"] in ("SUBMITTED", "ATTESTED"):
            domain.recompute_report_savings(c, baseline, r)
            touch(r)
    domain.recompute_contract_ledgers(c)
    c["updated_at"] = now_iso()
    return ok(domain.ser_adjustment(a))


@bp.route("/performance-contracts/<contractId>/baseline-adjustments/<adjustmentId>/reject", methods=["POST"])
def reject_adjustment(contractId, adjustmentId):
    require_roles("OwnerRep")
    _, a = domain.get_adjustment(contractId, adjustmentId)
    if a["status"] != "PROPOSED":
        raise ApiError("ERR_ADJUSTMENT_NOT_PROPOSED", 409, "adjustment must be in PROPOSED")
    a["status"] = "REJECTED"
    touch(a)
    return ok(domain.ser_adjustment(a))
