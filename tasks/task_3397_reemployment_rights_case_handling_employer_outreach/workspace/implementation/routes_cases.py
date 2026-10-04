"""ReemploymentCase: file, read, list, assign (OCC), and lifecycle state."""
from datetime import timedelta

from flask import Blueprint, request

from auth import require_role, require_ownership
from errors import ApiError
from helpers import (
    body_json, req_str, req_int, req_enum, opt_enum, opt_bool, opt_dt,
    get_member, get_employer, get_case, get_ombudsman,
    ser_case, touch, add_audit_note,
    apply_ombudsman_expiry, apply_case_round_expiry,
    active_caseload, MAX_ACTIVE_CASELOAD, REOPEN_WINDOW_DAYS,
    ISSUE_TYPES, EXCUSE_CATEGORIES, CASE_STATUSES, SECTORS,
)
from store import db
from util import now, new_id, success, paginate

bp = Blueprint("cases", __name__)

# Transition actor rules keyed on (from_status, to_status).
CASE_TRANSITIONS = {
    ("INTAKE", "TRIAGE"): {"ProgramCoordinator"},
    ("CLOSED_UNRESOLVED", "TRIAGE"): {"ServiceMember"},
    ("IN_MEDIATION", "ESCALATION_PENDING"): {"Ombudsman"},
    ("AWAITING_RESPONSE", "ESCALATION_PENDING"): {"Ombudsman"},
    ("INTAKE", "CLOSED_WITHDRAWN"): {"ServiceMember"},
    ("TRIAGE", "CLOSED_WITHDRAWN"): {"ServiceMember"},
    ("ASSIGNED", "CLOSED_WITHDRAWN"): {"ServiceMember"},
    ("IN_MEDIATION", "CLOSED_WITHDRAWN"): {"ServiceMember"},
    ("AWAITING_RESPONSE", "CLOSED_WITHDRAWN"): {"ServiceMember"},
    ("ESCALATION_PENDING", "CLOSED_WITHDRAWN"): {"ServiceMember"},
    ("IN_MEDIATION", "CLOSED_UNRESOLVED"): {"Ombudsman"},
    ("AWAITING_RESPONSE", "CLOSED_UNRESOLVED"): {"Ombudsman"},
}

# Targets whose actor role is fixed regardless of the source state.
TO_LEVEL_ACTORS = {
    "ESCALATION_PENDING": {"Ombudsman"},
    "CLOSED_WITHDRAWN": {"ServiceMember"},
    "CLOSED_UNRESOLVED": {"Ombudsman"},
}


@bp.route("/reemployment/cases", methods=["POST"])
def create_case():
    role, uid = require_role("ServiceMember")
    body = body_json()
    member_id = req_str(body, "member_id")
    employer_id = req_str(body, "employer_id")
    issue_type = req_enum(body, "issue_type", ISSUE_TYPES)
    description = req_str(body, "description")
    application_submitted_at = opt_dt(body, "application_submitted_at")
    excuse_claimed = opt_bool(body, "excuse_claimed", False)
    excuse_category = opt_enum(body, "excuse_category", EXCUSE_CATEGORIES)
    # Body FKs resolve in declared input order: member_id before employer_id.
    get_member(member_id)
    get_employer(employer_id)
    require_ownership(member_id == uid)
    cid = new_id()
    t = now()
    c = {
        "id": cid, "member_id": member_id, "employer_id": employer_id,
        "issue_type": issue_type, "description": description,
        "application_submitted_at": application_submitted_at,
        "excuse_claimed": excuse_claimed, "excuse_category": excuse_category,
        "assigned_ombudsman_id": None, "status": "INTAKE",
        "escalated_at": None, "closed_at": None,
        "created_at": t, "updated_at": t, "version": 1, "_seq": db.next_seq(),
    }
    db.cases[cid] = c
    return success(ser_case(c), "object", 201)


def _case_party_check(case, role, uid):
    """Single-case and case sub-resource reads are restricted to the four
    case parties: filing member, respondent employer, assigned ombudsman,
    coordinators."""
    if role == "ServiceMember":
        require_ownership(case["member_id"] == uid)
    elif role == "Employer":
        require_ownership(case["employer_id"] == uid)
    elif role == "Ombudsman":
        require_ownership(case["assigned_ombudsman_id"] == uid)


@bp.route("/reemployment/cases/<cid>", methods=["GET"])
def read_case(cid):
    role, uid = require_role("ServiceMember", "Employer", "Ombudsman",
                             "ProgramCoordinator")
    case = get_case(cid)
    _case_party_check(case, role, uid)
    return success(ser_case(case))


@bp.route("/reemployment/cases", methods=["GET"])
def list_cases():
    require_role("Ombudsman", "ProgramCoordinator")
    args = request.args
    status_f = args.get("status")
    if status_f is not None and status_f not in CASE_STATUSES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown status filter")
    issue_f = args.get("issue_type")
    if issue_f is not None and issue_f not in ISSUE_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown issue_type filter")
    sector_f = args.get("sector")
    if sector_f is not None and sector_f not in SECTORS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown sector filter")
    member_f = args.get("member_id")
    employer_f = args.get("employer_id")
    omb_f = args.get("assigned_ombudsman_id")
    items = []
    for c in db.cases.values():
        if member_f is not None and c["member_id"] != member_f:
            continue
        if employer_f is not None and c["employer_id"] != employer_f:
            continue
        if omb_f is not None and c["assigned_ombudsman_id"] != omb_f:
            continue
        if status_f is not None and c["status"] != status_f:
            continue
        if issue_f is not None and c["issue_type"] != issue_f:
            continue
        if sector_f is not None:
            emp = db.employers.get(c["employer_id"])
            if emp is None or emp["sector"] != sector_f:
                continue
        items.append(c)
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, meta = paginate(items)
    return success([ser_case(c) for c in page], "array", 200, meta)


@bp.route("/reemployment/cases/<cid>/assign", methods=["POST"])
def assign_case(cid):
    require_role("ProgramCoordinator")
    body = body_json()
    ombudsman_id = req_str(body, "ombudsman_id")
    expected = req_int(body, "expected_case_version")
    case = get_case(cid)
    o = get_ombudsman(ombudsman_id)
    apply_case_round_expiry(case)
    apply_ombudsman_expiry(o)
    # State gates (priority 6).
    if case["status"] not in ("TRIAGE", "ASSIGNED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "Case in %s cannot be assigned" % case["status"],
        )
    if o["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_OMBUDSMAN_NOT_CERTIFIED", 409,
            "Ombudsman is not currently CERTIFIED",
        )
    # OCC (priority 7).
    if expected != case["version"]:
        raise ApiError(
            "ERR_STALE_CASE_VERSION", 412,
            "expected_case_version does not match the case's current version",
        )
    # Neutrality screen (priority 8).
    if o["employer_affiliation_id"] is not None \
            and o["employer_affiliation_id"] == case["employer_id"]:
        raise ApiError(
            "ERR_CONFLICT_OF_INTEREST", 409,
            "Ombudsman declared an affiliation with the case's employer",
        )
    # Caseload cap (priority 10); exactly 4 blocks.
    if active_caseload(o["id"]) >= MAX_ACTIVE_CASELOAD:
        raise ApiError(
            "ERR_CASELOAD_FULL", 409,
            "Ombudsman active caseload has reached %d" % MAX_ACTIVE_CASELOAD,
        )
    case["assigned_ombudsman_id"] = o["id"]
    case["status"] = "ASSIGNED"
    touch(case)
    return success(ser_case(case))


def _moot_proposed_rounds(case, why):
    for r in db.rounds.values():
        if r["case_id"] == case["id"] and r["status"] == "PROPOSED":
            r["status"] = "CLOSED_MOOT"
            touch(r)
            add_audit_note(
                case["id"],
                "Mediation round %d closed moot: %s" % (r["round_number"], why),
            )


@bp.route("/reemployment/cases/<cid>/state", methods=["POST"])
def case_state(cid):
    role, uid = require_role("ServiceMember", "Ombudsman", "ProgramCoordinator")
    body = body_json()
    to_status = req_enum(body, "to_status", CASE_STATUSES)
    case = get_case(cid)
    apply_case_round_expiry(case)
    frm = case["status"]
    # Transition-level actor rules determinable from the target alone.
    fixed = TO_LEVEL_ACTORS.get(to_status)
    if fixed is not None and role not in fixed:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403,
            "Role %s may not drive a case to %s" % (role, to_status),
        )
    # Ownership (priority 5), evaluated only because the case exists.
    if role == "ServiceMember":
        require_ownership(case["member_id"] == uid)
    elif role == "Ombudsman":
        require_ownership(case["assigned_ombudsman_id"] == uid)
    allowed = CASE_TRANSITIONS.get((frm, to_status))
    if allowed is None:
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "No transition from %s to %s" % (frm, to_status),
        )
    if role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403,
            "Role %s may not drive %s -> %s" % (role, frm, to_status),
        )
    t = now()
    if to_status == "TRIAGE":
        if frm == "CLOSED_UNRESOLVED":
            # Member reopen within the 60-day window (inclusive boundary).
            if t > case["closed_at"] + timedelta(days=REOPEN_WINDOW_DAYS):
                raise ApiError(
                    "ERR_REOPEN_WINDOW_PASSED", 422,
                    "Reopen window has passed",
                )
            case["closed_at"] = None
        case["status"] = "TRIAGE"
    elif to_status == "ESCALATION_PENDING":
        exhausted = any(
            r["case_id"] == cid and r["status"] in ("DECLINED", "EXPIRED")
            for r in db.rounds.values()
        )
        if not exhausted:
            raise ApiError(
                "ERR_NO_EXHAUSTED_ROUND", 409,
                "Escalation requires a DECLINED or EXPIRED round",
            )
        case["status"] = "ESCALATION_PENDING"
        case["escalated_at"] = t
    elif to_status == "CLOSED_WITHDRAWN":
        if frm == "AWAITING_RESPONSE":
            _moot_proposed_rounds(case, "case withdrawn")
        if frm == "ESCALATION_PENDING":
            for ref in db.referrals.values():
                if ref["case_id"] == cid and ref["status"] == "DRAFT":
                    ref["status"] = "WITHDRAWN"
                    touch(ref)
        if frm in ("ASSIGNED", "IN_MEDIATION", "AWAITING_RESPONSE",
                   "ESCALATION_PENDING"):
            case["assigned_ombudsman_id"] = None
        case["closed_at"] = t
        case["status"] = "CLOSED_WITHDRAWN"
    elif to_status == "CLOSED_UNRESOLVED":
        if frm == "AWAITING_RESPONSE":
            _moot_proposed_rounds(case, "case closed unresolved")
        case["assigned_ombudsman_id"] = None
        case["closed_at"] = t
        case["status"] = "CLOSED_UNRESOLVED"
    touch(case)
    return success(ser_case(case))
