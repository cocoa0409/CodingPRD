"""Warranty claims (PRD 3.9) and the test-driving logical clock (PRD 2.4)."""
from flask import Blueprint, request

from db import STORES, new_record, get_clock, set_clock
from helpers import (
    body, require_roles, ok_obj, list_response, get_or_404, req_str,
    req_int, opt_str, raise_err, now_iso, parse_date, clock_date, parse_dt,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_NOT_OWNER, E_PROJECT_NOT_FOUND,
    E_WARRANTY_CLAIM_NOT_FOUND, E_PROJECT_NOT_COMPLETED, E_WARRANTY_EXPIRED,
    E_WARRANTY_CAP,
)
from logic import bump, warranty_reserve_remaining
from serializers import ser_warranty_claim

bp = Blueprint("warranty", __name__)

CLAIM_STATUSES = ("SUBMITTED", "APPROVED", "DENIED", "RESOLVED")


@bp.post("/rebuild/warranty-claims")
def create_claim():
    uid, role = require_roles("Homeowner", "AffiliateStaff")
    b = body()
    project_id = b.get("project_id")
    if project_id is None:
        raise_err(E_INVALID_REQUEST, 400, "project_id is required")
    project = get_or_404("projects", project_id, E_PROJECT_NOT_FOUND)
    # Tier 3: the Homeowner identity is the project's application id.
    if role == "Homeowner" and uid != project["application_id"]:
        raise_err(E_NOT_OWNER, 403,
                  "a Homeowner may file claims only on its own project")
    if project["status"] != "WARRANTY_ACTIVE":
        raise_err(E_PROJECT_NOT_COMPLETED, 409,
                  "the project must be WARRANTY_ACTIVE")
    description = req_str(b, "description")
    amount = req_int(b, "claim_amount_cents", lo=1)
    until = parse_date(project["warranty_valid_until"])
    if until is None or clock_date() > until:
        raise_err(E_WARRANTY_EXPIRED, 422,
                  "the warranty window has expired")
    rec = new_record("warranty_claims", {
        "project_id": project_id,
        "description": description,
        "claim_amount_cents": amount,
        "status": "SUBMITTED",
        "payout_cents": None,
        "submitted_on": get_clock(),
        "resolution_note": None,
    }, now_iso)
    return ok_obj(ser_warranty_claim(rec), 201)


@bp.get("/rebuild/warranty-claims")
def list_claims():
    require_roles("Any")
    recs = list(STORES["warranty_claims"].values())
    pid = request.args.get("project_id")
    if pid is not None:
        recs = [r for r in recs if r["project_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_response(recs, ser_warranty_claim)


@bp.get("/rebuild/warranty-claims/<claimId>")
def get_claim(claimId):
    require_roles("Any")
    rec = get_or_404("warranty_claims", claimId, E_WARRANTY_CLAIM_NOT_FOUND)
    return ok_obj(ser_warranty_claim(rec))


@bp.patch("/rebuild/warranty-claims/<claimId>")
def patch_claim(claimId):
    require_roles("AffiliateStaff")
    rec = get_or_404("warranty_claims", claimId, E_WARRANTY_CLAIM_NOT_FOUND)
    b = body()
    if "status" not in b:
        raise_err(E_INVALID_REQUEST, 400, "status is required")
    target = b["status"]
    if not isinstance(target, str) or target not in CLAIM_STATUSES:
        raise_err(E_INVALID_REQUEST, 400,
                  "status must be one of " + ", ".join(CLAIM_STATUSES))
    if target == "APPROVED":
        if rec["status"] != "SUBMITTED":
            raise_err(E_INVALID_STATE, 409,
                      "only a SUBMITTED claim can be approved")
        payout = req_int(b, "payout_cents", lo=1)
        if payout > rec["claim_amount_cents"]:
            raise_err(E_INVALID_REQUEST, 400,
                      "payout_cents may not exceed claim_amount_cents")
        project = STORES["projects"].get(rec["project_id"])
        if payout > warranty_reserve_remaining(project):
            raise_err(E_WARRANTY_CAP, 402,
                      "payout exceeds the remaining warranty reserve")
        rec["payout_cents"] = payout
        rec["status"] = "APPROVED"
    elif target == "DENIED":
        if rec["status"] != "SUBMITTED":
            raise_err(E_INVALID_STATE, 409,
                      "only a SUBMITTED claim can be denied")
        rec["status"] = "DENIED"
        if "resolution_note" in b:
            rec["resolution_note"] = opt_str(b, "resolution_note")
    elif target == "RESOLVED":
        if rec["status"] != "APPROVED":
            raise_err(E_INVALID_STATE, 409,
                      "only an APPROVED claim can be resolved")
        rec["status"] = "RESOLVED"
        if "resolution_note" in b:
            rec["resolution_note"] = opt_str(b, "resolution_note")
    else:  # SUBMITTED is not a drivable target
        raise_err(E_INVALID_STATE, 409, "no transition to %s" % target)
    bump(rec)
    return ok_obj(ser_warranty_claim(rec))


@bp.post("/_clock/set_current_utc")
def set_clock_route():
    require_roles("PlatformAdmin")
    b = body()
    value = b.get("to_iso8601")
    if parse_dt(value) is None:
        raise_err(E_INVALID_REQUEST, 400,
                  "to_iso8601 must be an ISO-8601 date/datetime")
    set_clock(value)
    return ok_obj({"current_utc": get_clock()})
