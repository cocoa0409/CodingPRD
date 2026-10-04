"""Appraisal and repair escrow endpoints."""
from datetime import timedelta

from flask import Blueprint

from auth import authenticate, require_role, check_ownership
from routes_cases import get_case_or_404
from services import appraisals_of_case, escrows_of_case
from store import db, make_entity, bump, public, logical_date
from util import (ApiError, ok_object, paginate, get_body, need_int, verr,
                  parse_date, MISSING)

bp = Blueprint("appraisals", __name__)

APPRAISAL_TERMINAL = ("REJECTED", "EXPIRED", "TRANSFERRED")


def _get_appraisal_or_404(appraisal_id):
    a = db.appraisals.get(appraisal_id)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "appraisal %s does not exist" % appraisal_id)
    return a


def _get_escrow_or_404(escrow_id):
    e = db.escrows.get(escrow_id)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "repair escrow %s does not exist" % escrow_id)
    return e


# ---------------------------------------------------------------------------
# Appraisals
# ---------------------------------------------------------------------------
@bp.post("/mi/loan-cases/<loanCaseId>/appraisals")
def create_appraisal(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["LenderOfficer"])
    case = get_case_or_404(loanCaseId)
    check_ownership(uid, role, case["lender_id"])
    b = get_body()
    value = need_int(b, "appraised_value_cents", minimum=1)
    eff_raw = b.get("effective_date", MISSING)
    if eff_raw is MISSING:
        verr("missing required field: effective_date")
    try:
        eff = parse_date(eff_raw)
    except (ValueError, TypeError):
        verr("effective_date must be an ISO date YYYY-MM-DD")
    mps = b.get("mps_deficiency_codes", [])
    if not isinstance(mps, list):
        verr("mps_deficiency_codes must be a list")
    appraisal = make_entity({
        "loan_case_id": case["id"],
        "appraised_value_cents": value,
        "effective_date": eff_raw,
        "expiry_date": (eff + timedelta(days=120)).isoformat(),
        "mps_deficiency_codes": list(mps),
        "status": "DELIVERED",
        "transferred_from_case_id": None,
    })
    db.appraisals[appraisal["id"]] = appraisal
    return ok_object(public(appraisal), 201)


@bp.get("/mi/loan-cases/<loanCaseId>/appraisals")
def list_appraisals(loanCaseId):
    authenticate()
    get_case_or_404(loanCaseId)
    return paginate(appraisals_of_case(loanCaseId))


@bp.post("/mi/appraisals/<appraisalId>/decide")
def decide_appraisal(appraisalId):
    uid, role = authenticate()
    require_role(role, ["FhaReviewer"])
    appraisal = _get_appraisal_or_404(appraisalId)
    b = get_body()
    decision = b.get("decision", MISSING)
    if decision is MISSING:
        verr("missing required field: decision")
    if decision not in ("ACCEPT", "REJECT"):
        verr("decision must be ACCEPT or REJECT")
    if appraisal["status"] in APPRAISAL_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "appraisal is %s; no further decisions" % appraisal["status"])
    if appraisal["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE",
                       "appraisal decision requires DELIVERED, got %s" % appraisal["status"])
    appraisal["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    bump(appraisal)
    return ok_object(public(appraisal), 200)


@bp.post("/mi/appraisals/<appraisalId>/transfer")
def transfer_appraisal(appraisalId):
    uid, role = authenticate()
    require_role(role, ["LenderOfficer"])
    appraisal = _get_appraisal_or_404(appraisalId)
    src_case = db.cases[appraisal["loan_case_id"]]
    # Priority 3: caller owns the lender of the appraisal's current case.
    check_ownership(uid, role, src_case["lender_id"])
    b = get_body()
    to_id = b.get("to_loan_case_id", MISSING)
    if to_id is MISSING or not isinstance(to_id, str):
        verr("to_loan_case_id is required and must be a string")
    target = db.cases.get(to_id)
    if target is None:
        raise ApiError("ERR_NOT_FOUND", "target loan case %s does not exist" % to_id)
    # Cross-case ownership: target must belong to the same lender.
    if target["lender_id"] != src_case["lender_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP",
                       "target case belongs to a different lender")
    # Priority 7: state legality.
    if appraisal["status"] in APPRAISAL_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "appraisal is %s; cannot transfer" % appraisal["status"])
    if appraisal["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE",
                       "transfer requires an ACCEPTED appraisal, got %s" % appraisal["status"])
    if target["status"] != "CASE_NUMBER_ASSIGNED":
        raise ApiError("ERR_INVALID_STATE",
                       "target case must be CASE_NUMBER_ASSIGNED, got %s" % target["status"])
    # Priority 9: target must be free of a live appraisal.
    for other in appraisals_of_case(target["id"]):
        if other["status"] in ("DELIVERED", "ACCEPTED"):
            raise ApiError("ERR_CASE_ALREADY_HAS_APPRAISAL",
                           "target case already has a DELIVERED or ACCEPTED appraisal")
    # Priority 10: transfer strictly before expiry_date (half-open window).
    if logical_date() >= parse_date(appraisal["expiry_date"]):
        raise ApiError("ERR_TRANSFER_WINDOW_CLOSED",
                       "appraisal is at or past its expiry_date")
    appraisal["transferred_from_case_id"] = appraisal["loan_case_id"]
    appraisal["loan_case_id"] = target["id"]
    appraisal["status"] = "TRANSFERRED"
    bump(appraisal)
    return ok_object(public(appraisal), 200)


# ---------------------------------------------------------------------------
# Repair escrows
# ---------------------------------------------------------------------------
@bp.post("/mi/loan-cases/<loanCaseId>/repair-escrows")
def create_escrow(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["LenderOfficer"])
    case = get_case_or_404(loanCaseId)
    check_ownership(uid, role, case["lender_id"])
    b = get_body()
    amount = need_int(b, "amount_cents", minimum=1)
    start_raw = b.get("start_date", MISSING)
    end_raw = b.get("end_date", MISSING)
    if start_raw is MISSING:
        verr("missing required field: start_date")
    if end_raw is MISSING:
        verr("missing required field: end_date")
    try:
        start = parse_date(start_raw)
    except (ValueError, TypeError):
        verr("start_date must be an ISO date YYYY-MM-DD")
    try:
        end = parse_date(end_raw)
    except (ValueError, TypeError):
        verr("end_date must be an ISO date YYYY-MM-DD")
    if start > end:
        verr("start_date must not be after end_date")
    # Closed-window overlap, including merely touching endpoints, against any
    # OPEN or FROZEN escrow of the same case.
    for other in escrows_of_case(case["id"]):
        if other["status"] not in ("OPEN", "FROZEN"):
            continue
        o_start = parse_date(other["start_date"])
        o_end = parse_date(other["end_date"])
        if start <= o_end and o_start <= end:
            raise ApiError("ERR_ESCROW_WINDOW_OVERLAP",
                           "window intersects another OPEN or FROZEN escrow of this case")
    escrow = make_entity({
        "loan_case_id": case["id"],
        "amount_cents": amount,
        "start_date": start_raw,
        "end_date": end_raw,
        "status": "OPEN",
        "freeze_origin": None,
        "remaining_amount_cents": amount,
        "disbursed_amount_cents": 0,
    })
    db.escrows[escrow["id"]] = escrow
    return ok_object(public(escrow), 200)


@bp.get("/mi/loan-cases/<loanCaseId>/repair-escrows")
def list_escrows(loanCaseId):
    authenticate()
    get_case_or_404(loanCaseId)
    return paginate(escrows_of_case(loanCaseId))


@bp.post("/mi/repair-escrows/<escrowId>/disburse")
def disburse_escrow(escrowId):
    uid, role = authenticate()
    require_role(role, ["ServicerOfficer"])
    escrow = _get_escrow_or_404(escrowId)
    case = db.cases[escrow["loan_case_id"]]
    check_ownership(uid, role, case["lender_id"])
    b = get_body()
    amount = need_int(b, "disbursed_amount_cents", minimum=1)
    if amount > escrow["amount_cents"]:
        verr("disbursed_amount_cents must not exceed the escrow amount")
    # Priority 7: terminal lockdown.
    if escrow["status"] in ("DISBURSED", "FORFEITED"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "escrow is %s; cannot disburse" % escrow["status"])
    # Priority 10: disbursement on or before end_date.
    if escrow["status"] == "EXPIRED" or logical_date() > parse_date(escrow["end_date"]):
        raise ApiError("ERR_ESCROW_EXPIRED",
                       "escrow end_date has passed")
    # Priority 11: frozen escrows cannot disburse.
    if escrow["status"] == "FROZEN":
        raise ApiError("ERR_ESCROW_FROZEN", "escrow is FROZEN")
    escrow["status"] = "DISBURSED"
    escrow["disbursed_amount_cents"] = amount
    escrow["remaining_amount_cents"] = escrow["amount_cents"] - amount
    bump(escrow)
    return ok_object(public(escrow), 200)
