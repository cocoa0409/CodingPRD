"""Statements of support and recognition awards, plus their employer listings."""
from flask import Blueprint

from auth import require_role, require_ownership
from errors import ApiError
from helpers import (
    body_json, req_str, req_enum, opt_int,
    get_employer, get_statement, get_award,
    ser_statement, ser_award, touch,
    apply_statement_lapse, employer_resolved_count, employer_open_count,
    STATEMENT_STATUSES, AWARD_TIERS, AWARD_STATUSES,
    VET_RESOLVED_GATE, TIER_BONUS,
    POINTS_PER_RESOLVED_CASE, POINTS_SIGNED_STATEMENT, PENALTY_PER_OPEN_CASE,
    TIER_GATE_BASE_BRONZE, TIER_GATE_BASE_SILVER, TIER_GATE_BASE_GOLD,
)
from store import db
from util import now, new_id, success, paginate, add_months

bp = Blueprint("recognition", __name__)


@bp.route("/reemployment/statements-of-support", methods=["POST"])
def create_statement():
    role, uid = require_role("Employer", "ProgramCoordinator")
    body = body_json()
    employer_id = req_str(body, "employer_id")
    signer_name = req_str(body, "signer_name")
    signer_title = req_str(body, "signer_title")
    term_months = opt_int(body, "term_months", 24)
    get_employer(employer_id)
    if role == "Employer":
        require_ownership(employer_id == uid)
    sid = new_id()
    t = now()
    s = {
        "id": sid, "employer_id": employer_id,
        "signer_name": signer_name, "signer_title": signer_title,
        "term_months": term_months, "status": "PLEDGED",
        "signed_on": None, "expires_on": None,
        "created_at": t, "updated_at": t, "version": 1, "_seq": db.next_seq(),
    }
    db.statements[sid] = s
    return success(ser_statement(s), "object", 201)


@bp.route("/reemployment/statements-of-support/<sid>/state", methods=["POST"])
def statement_state(sid):
    role, uid = require_role("Employer", "ProgramCoordinator")
    body = body_json()
    to_status = req_enum(body, "to_status", STATEMENT_STATUSES)
    # Transition-level actor rule: REVOKED belongs to coordinators.
    if to_status == "REVOKED" and role != "ProgramCoordinator":
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403,
            "Only a ProgramCoordinator revokes statements",
        )
    s = get_statement(sid)
    apply_statement_lapse(s)
    if role == "Employer":
        require_ownership(s["employer_id"] == uid)
    frm = s["status"]
    if to_status == "SIGNED":
        # PLEDGED -> SIGNED (sign) or LAPSED -> SIGNED (renewal).
        if frm not in ("PLEDGED", "LAPSED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition statement from %s to SIGNED" % frm,
            )
        s["signed_on"] = now()
        s["expires_on"] = add_months(now(), s["term_months"])
        s["status"] = "SIGNED"
    elif to_status == "REVOKED":
        if frm not in ("PLEDGED", "SIGNED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition statement from %s to REVOKED" % frm,
            )
        s["status"] = "REVOKED"
    else:
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "No transition to %s exists" % to_status,
        )
    touch(s)
    return success(ser_statement(s))


@bp.route("/reemployment/employers/<eid>/statements-of-support", methods=["GET"])
def list_statements(eid):
    role, uid = require_role("Employer", "Ombudsman", "ProgramCoordinator")
    get_employer(eid)
    if role == "Employer":
        require_ownership(eid == uid)
    items = [s for s in db.statements.values() if s["employer_id"] == eid]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, meta = paginate(items)
    return success([ser_statement(s) for s in page], "array", 200, meta)


@bp.route("/reemployment/recognition-awards", methods=["POST"])
def create_award():
    role, uid = require_role("Ombudsman", "ProgramCoordinator")
    body = body_json()
    employer_id = req_str(body, "employer_id")
    tier = req_enum(body, "tier", AWARD_TIERS)
    rationale = req_str(body, "rationale")
    get_employer(employer_id)
    if role == "Ombudsman":
        # Nominator standing: at least one case assigned to this ombudsman
        # and closed RESOLVED_INFORMAL for this employer.
        qualified = any(
            c["assigned_ombudsman_id"] == uid
            and c["employer_id"] == employer_id
            and c["status"] == "RESOLVED_INFORMAL"
            for c in db.cases.values()
        )
        if not qualified:
            raise ApiError(
                "ERR_NOMINATION_NOT_QUALIFIED", 409,
                "Ombudsman nominator was never the assignee on a "
                "RESOLVED_INFORMAL case for this employer",
            )
    aid = new_id()
    t = now()
    a = {
        "id": aid, "employer_id": employer_id, "tier": tier,
        "rationale": rationale,
        "nominated_by_id": uid, "nominated_by_role": role,
        "status": "NOMINATED",
        "score_base": None, "tier_qualified": None,
        "score_bonus": None, "score_final": None,
        "created_at": t, "updated_at": t, "version": 1, "_seq": db.next_seq(),
    }
    db.awards[aid] = a
    return success(ser_award(a), "object", 201)


@bp.route("/reemployment/recognition-awards/<aid>/state", methods=["POST"])
def award_state(aid):
    require_role("ProgramCoordinator")
    body = body_json()
    to_status = req_enum(body, "to_status", AWARD_STATUSES)
    a = get_award(aid)
    frm = a["status"]
    if to_status == "VETTED":
        if frm != "NOMINATED":
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition award from %s to VETTED" % frm,
            )
        eid = a["employer_id"]
        has_signed = False
        for s in db.statements.values():
            if s["employer_id"] == eid:
                apply_statement_lapse(s)
                if s["status"] == "SIGNED":
                    has_signed = True
        resolved = employer_resolved_count(eid)
        if not has_signed or resolved < VET_RESOLVED_GATE[a["tier"]]:
            raise ApiError(
                "ERR_AWARD_ELIGIBILITY_UNMET", 409,
                "Statement requirement or resolved-case gate not met",
            )
        open_c = employer_open_count(eid)
        base = (POINTS_PER_RESOLVED_CASE * resolved
                + (POINTS_SIGNED_STATEMENT if has_signed else 0)
                - PENALTY_PER_OPEN_CASE * open_c)
        if base >= TIER_GATE_BASE_GOLD:
            tq = "GOLD"
        elif base >= TIER_GATE_BASE_SILVER:
            tq = "SILVER"
        elif base >= TIER_GATE_BASE_BRONZE:
            tq = "BRONZE"
        else:
            raise ApiError(
                "ERR_AWARD_ELIGIBILITY_UNMET", 409,
                "score_base %d is below every tier gate" % base,
            )
        bonus = TIER_BONUS[tq]
        a["score_base"] = base
        a["tier_qualified"] = tq  # derived from score_base ALONE
        a["score_bonus"] = bonus
        a["score_final"] = base + bonus
        a["status"] = "VETTED"
    elif to_status == "CONFERRED":
        if frm != "VETTED":
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition award from %s to CONFERRED" % frm,
            )
        a["status"] = "CONFERRED"
        # employer.recognition_tier is derived at read from CONFERRED awards.
    elif to_status == "DECLINED":
        if frm not in ("NOMINATED", "VETTED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition award from %s to DECLINED" % frm,
            )
        a["status"] = "DECLINED"
    else:
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "No transition to %s exists" % to_status,
        )
    touch(a)
    return success(ser_award(a))


@bp.route("/reemployment/employers/<eid>/recognition-awards", methods=["GET"])
def list_awards(eid):
    role, uid = require_role("Employer", "Ombudsman", "ProgramCoordinator")
    get_employer(eid)
    if role == "Employer":
        require_ownership(eid == uid)
    items = [a for a in db.awards.values() if a["employer_id"] == eid]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, meta = paginate(items)
    return success([ser_award(a) for a in page], "array", 200, meta)
