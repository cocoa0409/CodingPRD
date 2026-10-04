"""FinancingFacility routes."""
from flask import Blueprint

import db
import domain
import calc
from errors import ApiError, ok
from util import (body, new_id, now_iso, paginate_args, paginate_list,
                  parse_dt, req_enum, req_int, req_number, require_roles, touch)

bp = Blueprint("facilities", __name__)

FACILITY_TYPES = ("LEASE", "BOND", "THIRD_PARTY")


@bp.route("/performance-contracts/<contractId>/financing-facilities", methods=["POST"])
def create_facility(contractId):
    require_roles("ESCOEngineer")
    c = domain.get_contract(contractId)
    data = body()
    principal = req_int(data, "principal_cents", min_v=1)
    if principal > c["contract_value_cents"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "principal_cents must not exceed contract_value_cents")
    term = req_int(data, "term_years", min_v=1, max_v=30)
    if term > c["contract_term_years"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "term_years must not exceed the contract term")
    rec = {
        "id": new_id(),
        "contract_id": c["id"],
        "facility_type": req_enum(data, "facility_type", FACILITY_TYPES),
        "principal_cents": principal,
        "annual_rate_pct": req_number(data, "annual_rate_pct", min_v=0, max_v=30),
        "term_years": term,
        "annual_payment_cents": None,
        "coverage_ratio": None,
        "drawn_cents": 0,
        "status": "DRAFT",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.facilities[rec["id"]] = rec
    return ok(domain.ser_facility(rec), code=201)


@bp.route("/performance-contracts/<contractId>/financing-facilities", methods=["GET"])
def list_facilities(contractId):
    require_roles()
    c = domain.get_contract(contractId)
    limit, offset = paginate_args()
    items = [f for f in db.facilities.values() if f["contract_id"] == c["id"]]
    items.sort(key=lambda f: (f["created_at"], f["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_facility(f) for f in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>/financing-facilities/<facilityId>", methods=["GET"])
def get_facility(contractId, facilityId):
    require_roles()
    _, f = domain.get_facility(contractId, facilityId)
    return ok(domain.ser_facility(f))


@bp.route("/performance-contracts/<contractId>/financing-facilities/<facilityId>/submit", methods=["POST"])
def submit_facility(contractId, facilityId):
    require_roles("ESCOEngineer")
    c, f = domain.get_facility(contractId, facilityId)
    if f["status"] != "DRAFT":
        raise ApiError("ERR_FACILITY_NOT_DRAFT", 409, "facility must be in DRAFT")
    if c["status"] != "SCOPED":
        raise ApiError("ERR_CONTRACT_NOT_SCOPED", 409, "contract must be in SCOPED")
    payment = calc.financing_payment(
        f["facility_type"], f["principal_cents"], f["annual_rate_pct"], f["term_years"])
    f["annual_payment_cents"] = payment
    f["coverage_ratio"] = calc.coverage_ratio(c["guaranteed_annual_savings_cents"], payment)
    f["status"] = "SUBMITTED"
    touch(f)
    return ok(domain.ser_facility(f))


@bp.route("/performance-contracts/<contractId>/financing-facilities/<facilityId>/approve", methods=["POST"])
def approve_facility(contractId, facilityId):
    require_roles("LenderOfficer")
    _, f = domain.get_facility(contractId, facilityId)
    if f["status"] != "SUBMITTED":
        raise ApiError("ERR_FACILITY_NOT_SUBMITTED", 409, "facility must be in SUBMITTED")
    if f["coverage_ratio"] is None or f["coverage_ratio"] < 1.0:
        raise ApiError("ERR_COVERAGE_BELOW_ONE", 422, "coverage ratio must be >= 1.0000")
    f["status"] = "APPROVED"
    touch(f)
    return ok(domain.ser_facility(f))


@bp.route("/performance-contracts/<contractId>/financing-facilities/<facilityId>/cancel", methods=["POST"])
def cancel_facility(contractId, facilityId):
    require_roles("LenderOfficer")
    _, f = domain.get_facility(contractId, facilityId)
    if f["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_FACILITY_NOT_CANCELLABLE", 409,
                       "facility must be in DRAFT or SUBMITTED")
    f["status"] = "CANCELLED"
    touch(f)
    for d in db.draws.values():
        if d["facility_id"] == f["id"] and d["status"] == "REQUESTED":
            d["status"] = "REJECTED"
    return ok(domain.ser_facility(f))


@bp.route("/performance-contracts/<contractId>/financing-facilities/<facilityId>/payoff", methods=["POST"])
def payoff_facility(contractId, facilityId):
    require_roles("OwnerRep")
    c, f = domain.get_facility(contractId, facilityId)
    if f["status"] != "FUNDING":
        raise ApiError("ERR_FACILITY_NOT_FUNDING", 409, "facility must be in FUNDING")
    gsd = parse_dt(c["guarantee_start_date"], "guarantee_start_date")
    if db.logical_now() < domain.add_years(gsd, f["term_years"]):
        raise ApiError("ERR_FACILITY_TERM_NOT_ELAPSED", 422,
                       "the financing term has not elapsed")
    f["status"] = "PAID_OFF"
    touch(f)
    return ok(domain.ser_facility(f))
