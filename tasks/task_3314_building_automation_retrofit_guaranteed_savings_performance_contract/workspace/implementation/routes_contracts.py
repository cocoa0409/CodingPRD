"""PerformanceContract lifecycle routes."""
from flask import Blueprint, request

import db
import domain
from errors import ApiError, ok
from util import (body, new_id, now_iso, paginate_args, paginate_list,
                  parse_dt, req_enum, req_int, req_string, require_roles, touch)

bp = Blueprint("contracts", __name__)

MV_PROTOCOLS = ("IPMVP_A", "IPMVP_B", "IPMVP_C", "IPMVP_D")


@bp.route("/performance-contracts", methods=["POST"])
def create_contract():
    require_roles("ESCOEngineer")
    data = body()
    gsd = parse_dt(data.get("guarantee_start_date"), "guarantee_start_date")
    rec = {
        "id": new_id(),
        "facility_name": req_string(data, "facility_name"),
        "contract_term_years": req_int(data, "contract_term_years", min_v=1, max_v=25),
        "guarantee_start_date": gsd.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "mv_protocol": req_enum(data, "mv_protocol", MV_PROTOCOLS),
        "guaranteed_annual_savings_cents": req_int(data, "guaranteed_annual_savings_cents", min_v=1),
        "contract_value_cents": req_int(data, "contract_value_cents", min_v=1),
        "guarantee_shortfall_reserve_cents": 0,
        "cumulative_verified_savings_cents": 0,
        "status": "AUDIT",
        "executed_baseline_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.contracts[rec["id"]] = rec
    return ok(domain.ser_contract(rec), code=201)


@bp.route("/performance-contracts", methods=["GET"])
def list_contracts():
    require_roles()
    limit, offset = paginate_args()
    items = list(db.contracts.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    eb = request.args.get("executed_baseline_id")
    if eb is not None:
        items = [c for c in items if c.get("executed_baseline_id") == eb]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_contract(c) for c in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>", methods=["GET"])
def get_contract(contractId):
    require_roles()
    c = domain.get_contract(contractId)
    return ok(domain.ser_contract(c))


@bp.route("/performance-contracts/<contractId>/complete-audit", methods=["POST"])
def complete_audit(contractId):
    require_roles("ESCOEngineer")
    c = domain.get_contract(contractId)
    if c["status"] != "AUDIT":
        raise ApiError("ERR_CONTRACT_NOT_IN_AUDIT", 409, "contract must be in AUDIT")
    approved = [b for b in db.baselines.values()
                if b["contract_id"] == c["id"] and b["status"] == "APPROVED"]
    if not approved:
        raise ApiError("ERR_BASELINE_NOT_APPROVED", 409, "an APPROVED baseline is required")
    measures = [m for m in db.measures.values()
                if m["contract_id"] == c["id"] and m["status"] in ("PROPOSED", "INCLUDED")]
    if not measures:
        raise ApiError("ERR_NO_MEASURES_IDENTIFIED", 409, "at least one measure is required")
    baseline = sorted(approved, key=lambda b: (b["created_at"], b["id"]))[0]
    gsd = parse_dt(c["guarantee_start_date"], "guarantee_start_date")
    if gsd <= db.logical_now():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "guarantee_start_date must be later than the audit completion date")
    c["executed_baseline_id"] = baseline["id"]
    c["status"] = "SCOPED"
    touch(c)
    return ok(domain.ser_contract(c))


@bp.route("/performance-contracts/<contractId>/execute", methods=["POST"])
def execute_contract(contractId):
    require_roles("OwnerRep")
    c = domain.get_contract(contractId)
    if c["status"] != "SCOPED":
        raise ApiError("ERR_CONTRACT_NOT_SCOPED", 409, "contract must be in SCOPED")
    approved_bundles = [b for b in db.bundles.values()
                        if b["contract_id"] == c["id"] and b["status"] == "APPROVED"]
    if not approved_bundles:
        raise ApiError("ERR_NO_APPROVED_BUNDLE", 409, "an APPROVED bundle is required")
    facilities = [f for f in db.facilities.values()
                  if f["contract_id"] == c["id"] and f["status"] in ("APPROVED", "FUNDING")]
    if not facilities:
        raise ApiError("ERR_NO_APPROVED_FINANCING", 409, "an APPROVED or FUNDING facility is required")
    for b in approved_bundles:
        if b["blended_payback_years"] is None or b["blended_payback_years"] > c["contract_term_years"]:
            raise ApiError("ERR_BUNDLE_PAYBACK_EXCEEDS_TERM", 422,
                           "blended payback exceeds the contract term")
    baseline = db.baselines.get(c["executed_baseline_id"])
    if baseline is not None and baseline["status"] == "APPROVED":
        baseline["status"] = "LOCKED"
        touch(baseline)
    for b in approved_bundles:
        b["status"] = "ACTIVE"
        touch(b)
    c["status"] = "EXECUTED"
    touch(c)
    return ok(domain.ser_contract(c))


@bp.route("/performance-contracts/<contractId>/mobilize", methods=["POST"])
def mobilize_contract(contractId):
    require_roles("ESCOEngineer")
    c = domain.get_contract(contractId)
    if c["status"] != "EXECUTED":
        raise ApiError("ERR_CONTRACT_NOT_EXECUTED", 409, "contract must be in EXECUTED")
    mobilized = [p for p in db.phases.values()
                 if p["contract_id"] == c["id"] and p["status"] == "MOBILIZED"]
    if not mobilized:
        raise ApiError("ERR_NO_MOBILIZED_PHASE", 409, "a MOBILIZED phase is required")
    for f in db.facilities.values():
        if f["contract_id"] == c["id"] and f["status"] == "APPROVED":
            f["status"] = "FUNDING"
            touch(f)
    c["status"] = "CONSTRUCTION"
    touch(c)
    return ok(domain.ser_contract(c))


@bp.route("/performance-contracts/<contractId>/commence-performance", methods=["POST"])
def commence_performance(contractId):
    require_roles("OwnerRep")
    c = domain.get_contract(contractId)
    if c["status"] != "CONSTRUCTION":
        raise ApiError("ERR_CONTRACT_NOT_IN_CONSTRUCTION", 409, "contract must be in CONSTRUCTION")
    phases = [p for p in db.phases.values() if p["contract_id"] == c["id"]]
    if any(p["status"] != "COMPLETE" for p in phases):
        raise ApiError("ERR_PHASES_INCOMPLETE", 409, "all phases must be COMPLETE")
    active_bundles = [b for b in db.bundles.values()
                      if b["contract_id"] == c["id"] and b["status"] == "ACTIVE"]
    active_ids = {b["id"] for b in active_bundles}
    bad = [m for m in db.measures.values()
           if m["bundle_id"] in active_ids and m["status"] not in ("VERIFIED", "EXCLUDED")]
    if bad:
        raise ApiError("ERR_MEASURES_UNVERIFIED", 409,
                       "every measure in an active bundle must be VERIFIED or EXCLUDED")
    gsd = parse_dt(c["guarantee_start_date"], "guarantee_start_date")
    if db.logical_now() < gsd:
        raise ApiError("ERR_GUARANTEE_PERIOD_NOT_STARTED", 422,
                       "the guarantee period has not started")
    c["status"] = "PERFORMANCE"
    touch(c)
    return ok(domain.ser_contract(c))


@bp.route("/performance-contracts/<contractId>/close", methods=["POST"])
def close_contract(contractId):
    require_roles("OwnerRep")
    c = domain.get_contract(contractId)
    if c["status"] != "PERFORMANCE":
        raise ApiError("ERR_CONTRACT_NOT_IN_PERFORMANCE", 409, "contract must be in PERFORMANCE")
    reconciled_years = {r["period_year"] for r in db.reports.values()
                        if r["contract_id"] == c["id"] and r["status"] == "RECONCILED"}
    for year in range(1, c["contract_term_years"] + 1):
        if year not in reconciled_years:
            raise ApiError("ERR_RECONCILIATION_INCOMPLETE", 409,
                           "reconciled reports are missing for some guarantee years")
    open_disputes = [d for d in db.disputes.values()
                     if d["contract_id"] == c["id"] and d["status"] in ("OPEN", "ESCALATED")]
    if open_disputes:
        raise ApiError("ERR_OPEN_DISPUTES_EXIST", 409, "open disputes exist")
    if c["guarantee_shortfall_reserve_cents"] != 0:
        raise ApiError("ERR_UNPAID_SHORTFALL_RESERVE", 409,
                       "the shortfall reserve must be zero to close")
    for f in db.facilities.values():
        if f["contract_id"] == c["id"] and f["status"] == "FUNDING" and f["drawn_cents"] == 0:
            f["status"] = "PAID_OFF"
            touch(f)
    c["status"] = "CLOSED"
    touch(c)
    return ok(domain.ser_contract(c))


@bp.route("/performance-contracts/<contractId>/terminate", methods=["POST"])
def terminate_contract(contractId):
    require_roles("OwnerRep")
    c = domain.get_contract(contractId)
    if c["status"] not in ("AUDIT", "SCOPED"):
        raise ApiError("ERR_CONTRACT_NOT_TERMINABLE", 409,
                       "terminate is allowed only from AUDIT or SCOPED")
    for b in db.bundles.values():
        if b["contract_id"] == c["id"] and b["status"] not in ("WITHDRAWN", "COMPLETE"):
            b["status"] = "WITHDRAWN"
            touch(b)
            for m in db.measures.values():
                if m["bundle_id"] == b["id"] and m["status"] not in ("VERIFIED", "EXCLUDED"):
                    m["status"] = "EXCLUDED"
                    touch(m)
    for f in db.facilities.values():
        if f["contract_id"] == c["id"] and f["status"] in ("DRAFT", "SUBMITTED"):
            f["status"] = "CANCELLED"
            touch(f)
    c["status"] = "TERMINATED"
    touch(c)
    return ok(domain.ser_contract(c))
