"""Referrals to federal enforcement agencies: draft, lifecycle, list."""
from datetime import timedelta

from flask import Blueprint

from auth import require_role, require_ownership
from errors import ApiError
from helpers import (
    body_json, req_str, req_enum, opt_str,
    get_case, get_referral, ser_referral, touch, add_audit_note,
    AGENCIES, REFERRAL_STATUSES, REFERRAL_WINDOW_DAYS,
)
from routes_cases import _case_party_check
from store import db
from util import now, new_id, success, paginate

bp = Blueprint("referrals", __name__)


@bp.route("/reemployment/referrals", methods=["POST"])
def create_referral():
    role, uid = require_role("Ombudsman")
    body = body_json()
    case_id = req_str(body, "case_id")
    agency = req_enum(body, "agency", AGENCIES)
    summary = req_str(body, "summary")
    case = get_case(case_id)
    # Only the assigned ombudsman drafts a referral on the case.
    require_ownership(case["assigned_ombudsman_id"] == uid)
    if case["status"] != "ESCALATION_PENDING":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "Case must be ESCALATION_PENDING to draft a referral",
        )
    rid = new_id()
    t = now()
    r = {
        "id": rid, "case_id": case_id, "agency": agency, "summary": summary,
        "status": "DRAFT", "submitted_at": None, "info_request_note": None,
        "created_by_ombudsman_id": uid,
        "created_at": t, "updated_at": t, "version": 1, "_seq": db.next_seq(),
    }
    db.referrals[rid] = r
    return success(ser_referral(r), "object", 201)


@bp.route("/reemployment/referrals/<rid>/state", methods=["POST"])
def referral_state(rid):
    role, uid = require_role("ProgramCoordinator", "AgencyReviewer")
    body = body_json()
    to_status = req_enum(body, "to_status", REFERRAL_STATUSES)
    info_note = opt_str(body, "info_request_note")
    ref = get_referral(rid)
    case = get_case(ref["case_id"])
    frm = ref["status"]
    if to_status == "SUBMITTED":
        if role != "ProgramCoordinator":
            raise ApiError(
                "ERR_UNAUTHORIZED_ROLE", 403,
                "Only a ProgramCoordinator submits referrals",
            )
        if frm == "DRAFT":
            if case["status"] != "ESCALATION_PENDING":
                raise ApiError(
                    "ERR_INVALID_STATE", 409,
                    "Case is not ESCALATION_PENDING",
                )
            # First submission only: within escalated_at + 30 days
            # (submission at exactly the 30-day mark is inside the window).
            if now() > case["escalated_at"] + timedelta(days=REFERRAL_WINDOW_DAYS):
                raise ApiError(
                    "ERR_REFERRAL_WINDOW_PASSED", 422,
                    "The 30-day referral window has passed",
                )
            ref["submitted_at"] = now()
            ref["status"] = "SUBMITTED"
            touch(ref)
            # Cascade: case -> REFERRED; PROPOSED rounds closed moot with
            # an AUDIT note each; the assigned caseload drop is derived.
            case["status"] = "REFERRED"
            touch(case)
            for r in db.rounds.values():
                if r["case_id"] == case["id"] and r["status"] == "PROPOSED":
                    r["status"] = "CLOSED_MOOT"
                    touch(r)
                    add_audit_note(
                        case["id"],
                        "Mediation round %d closed moot on referral submission"
                        % r["round_number"],
                    )
        elif frm == "RETURNED_FOR_INFO":
            # Resubmission: the 30-day window does not re-apply.
            if case["status"] != "REFERRED":
                raise ApiError(
                    "ERR_INVALID_STATE", 409,
                    "Case is not REFERRED",
                )
            ref["status"] = "SUBMITTED"
            touch(ref)
        else:
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition referral from %s to SUBMITTED" % frm,
            )
    elif to_status == "ACKNOWLEDGED":
        if role != "AgencyReviewer":
            raise ApiError(
                "ERR_UNAUTHORIZED_ROLE", 403,
                "Only an AgencyReviewer acknowledges referrals",
            )
        if frm != "SUBMITTED":
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition referral from %s to ACKNOWLEDGED" % frm,
            )
        ref["status"] = "ACKNOWLEDGED"
        touch(ref)
    elif to_status == "RETURNED_FOR_INFO":
        if role != "AgencyReviewer":
            raise ApiError(
                "ERR_UNAUTHORIZED_ROLE", 403,
                "Only an AgencyReviewer returns referrals for information",
            )
        if frm != "SUBMITTED":
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition referral from %s to RETURNED_FOR_INFO" % frm,
            )
        ref["status"] = "RETURNED_FOR_INFO"
        ref["info_request_note"] = info_note
        touch(ref)
    elif to_status == "WITHDRAWN":
        if role != "ProgramCoordinator":
            raise ApiError(
                "ERR_UNAUTHORIZED_ROLE", 403,
                "Only a ProgramCoordinator withdraws referrals",
            )
        if frm != "DRAFT":
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition referral from %s to WITHDRAWN" % frm,
            )
        ref["status"] = "WITHDRAWN"
        touch(ref)
    else:
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "No transition to %s exists" % to_status,
        )
    return success(ser_referral(ref))


@bp.route("/reemployment/cases/<cid>/referrals", methods=["GET"])
def list_referrals(cid):
    role, uid = require_role("ServiceMember", "Employer", "Ombudsman",
                             "ProgramCoordinator")
    case = get_case(cid)
    _case_party_check(case, role, uid)
    items = [r for r in db.referrals.values() if r["case_id"] == cid]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, meta = paginate(items)
    return success([ser_referral(r) for r in page], "array", 200, meta)
