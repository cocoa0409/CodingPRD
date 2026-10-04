"""SavingsReport routes and dispute filing."""
from flask import Blueprint

import db
import domain
from errors import ApiError, ok
from util import (body, new_id, now_iso, paginate_args, paginate_list,
                  parse_dt, req_int, req_number, require_roles, touch)

bp = Blueprint("reports", __name__)


@bp.route("/performance-contracts/<contractId>/reports", methods=["POST"])
def create_report(contractId):
    require_roles("ESCOEngineer")
    c = domain.get_contract(contractId)
    data = body()
    year = req_int(data, "period_year", min_v=1)
    existing = [r for r in db.reports.values()
                if r["contract_id"] == c["id"] and r["period_year"] == year]
    if existing:
        raise ApiError("ERR_DUPLICATE_REPORT_PERIOD", 409,
                       "a report already exists for this period_year")
    rec = {
        "id": new_id(),
        "contract_id": c["id"],
        "period_year": year,
        "actual_energy_kwh": req_int(data, "actual_energy_kwh", min_v=0),
        "period_hdd": req_number(data, "period_hdd", min_v=0),
        "period_cdd": req_number(data, "period_cdd", min_v=0),
        "period_occupancy_factor": req_number(data, "period_occupancy_factor",
                                              min_v=0, max_v=1, strict_min=True),
        "verified_savings_cents": None,
        "shortfall_cents": None,
        "status": "DRAFT",
        "attested_by_owner_rep_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.reports[rec["id"]] = rec
    return ok(domain.ser_report(rec), code=201)


@bp.route("/performance-contracts/<contractId>/reports", methods=["GET"])
def list_reports(contractId):
    require_roles()
    c = domain.get_contract(contractId)
    limit, offset = paginate_args()
    items = [r for r in db.reports.values() if r["contract_id"] == c["id"]]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_report(r) for r in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>/reports/<reportId>", methods=["GET"])
def get_report(contractId, reportId):
    require_roles()
    _, r = domain.get_report(contractId, reportId)
    return ok(domain.ser_report(r))


@bp.route("/performance-contracts/<contractId>/reports/<reportId>/submit", methods=["POST"])
def submit_report(contractId, reportId):
    require_roles("ESCOEngineer")
    c, r = domain.get_report(contractId, reportId)
    if r["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT", 409, "report must be in DRAFT")
    if c["status"] != "PERFORMANCE":
        raise ApiError("ERR_CONTRACT_NOT_IN_PERFORMANCE", 409,
                       "contract must be in PERFORMANCE")
    gsd = parse_dt(c["guarantee_start_date"], "guarantee_start_date")
    threshold = domain.period_end_threshold(gsd, r["period_year"])
    if db.logical_now() < threshold:
        raise ApiError("ERR_PERIOD_NOT_ENDED", 422,
                       "the guarantee year for this report has not ended")
    baseline = db.baselines.get(c.get("executed_baseline_id"))
    domain.recompute_report_savings(c, baseline, r)
    r["status"] = "SUBMITTED"
    touch(r)
    return ok(domain.ser_report(r))


@bp.route("/performance-contracts/<contractId>/reports/<reportId>/attest", methods=["POST"])
def attest_report(contractId, reportId):
    uid, _ = require_roles("OwnerRep")
    _, r = domain.get_report(contractId, reportId)
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_SUBMITTED", 409, "report must be in SUBMITTED")
    r["attested_by_owner_rep_id"] = uid
    r["status"] = "ATTESTED"
    touch(r)
    return ok(domain.ser_report(r))


@bp.route("/performance-contracts/<contractId>/reports/<reportId>/reconcile", methods=["POST"])
def reconcile_report(contractId, reportId):
    require_roles("OwnerRep")
    c, r = domain.get_report(contractId, reportId)
    if r["status"] != "ATTESTED":
        raise ApiError("ERR_REPORT_NOT_ATTESTED", 409, "report must be in ATTESTED")
    data = body()
    expected = data.get("expected_contract_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_contract_version is required and must be an integer")
    if expected != c["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_contract_version does not match the contract version")
    r["status"] = "RECONCILED"
    touch(r)
    domain.recompute_contract_ledgers(c)
    touch(c)
    return ok(domain.ser_report(r))


@bp.route("/performance-contracts/<contractId>/reports/<reportId>/disputes", methods=["POST"])
def file_dispute(contractId, reportId):
    uid, role = require_roles("OwnerRep", "ESCOEngineer")
    c, r = domain.get_report(contractId, reportId)
    data = body()
    ref = data.get("report_id")
    if ref is None or ref != r["id"]:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", 404,
                       "report_id does not resolve")
    claimed = req_int(data, "claimed_savings_cents", min_v=0)
    if role == "OwnerRep":
        if r["status"] != "SUBMITTED":
            raise ApiError("ERR_REPORT_NOT_SUBMITTED", 409,
                           "report must be in SUBMITTED for an owner dispute")
        filed_by = "OWNER"
        pre_state = "SUBMITTED"
    else:
        if r["status"] != "ATTESTED":
            raise ApiError("ERR_REPORT_NOT_ATTESTED", 409,
                           "report must be in ATTESTED for an ESCO dispute")
        filed_by = "ESCO"
        pre_state = "ATTESTED"
    rec = {
        "id": new_id(),
        "contract_id": c["id"],
        "report_id": r["id"],
        "filed_by_role": filed_by,
        "claimed_savings_cents": claimed,
        "resolution_savings_cents": None,
        "status": "OPEN",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_pre_state": pre_state,
        "_pre_attester": r.get("attested_by_owner_rep_id"),
    }
    db.disputes[rec["id"]] = rec
    r["status"] = "DISPUTED"
    touch(r)
    out = domain.ser_dispute(rec)
    out.pop("_pre_state", None)
    out.pop("_pre_attester", None)
    return ok(out, code=201)
