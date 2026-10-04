"""Ombudsman lifecycle (certify / leave / decertify) and training records."""
from flask import Blueprint

from auth import require_role, require_ownership
from errors import ApiError
from helpers import (
    body_json, req_enum, req_str, req_int, req_num, req_dt,
    get_ombudsman, ser_ombudsman, ser_training,
    apply_ombudsman_expiry, touch, add_audit_note,
    OMBUDSMAN_STATUSES, MODULE_CODES, CORE_MODULES,
    CERT_MIN_HOURS, RECERT_MIN_HOURS, CERT_TERM_MONTHS, RECERT_WINDOW_MONTHS,
    ACTIVE_CASELOAD_STATUSES,
)
from store import db
from util import now, new_id, success, paginate, add_months

bp = Blueprint("ombudsmen", __name__)


def _segregation_check(o, actor_uid):
    """A coordinator who proctored any of this volunteer's records may not
    certify or recertify them. Evaluated before the training checks."""
    for t in db.training_records.values():
        if t["ombudsman_id"] == o["id"] and t["proctor_id"] == actor_uid:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES", 403,
                "Certifying coordinator proctored training for this ombudsman",
            )


def _cert_requirements(o):
    recs = [t for t in db.training_records.values() if t["ombudsman_id"] == o["id"]]
    for mod in CORE_MODULES:
        if not any(r["module_code"] == mod and r["exam_score"] >= 80 for r in recs):
            raise ApiError(
                "ERR_CERTIFICATION_REQUIREMENTS_UNMET", 422,
                "Core module %s lacks a record with exam_score >= 80" % mod,
            )
    if sum(r["hours"] for r in recs) < CERT_MIN_HOURS:
        raise ApiError(
            "ERR_CERTIFICATION_REQUIREMENTS_UNMET", 422,
            "total_training_hours below %s" % CERT_MIN_HOURS,
        )


def _recert_requirements(o):
    cutoff = add_months(now(), -RECERT_WINDOW_MONTHS)
    recent = [
        t for t in db.training_records.values()
        if t["ombudsman_id"] == o["id"] and cutoff <= t["completed_on"] <= now()
    ]
    if not recent or sum(r["hours"] for r in recent) < RECERT_MIN_HOURS:
        raise ApiError(
            "ERR_CERTIFICATION_REQUIREMENTS_UNMET", 422,
            "Recertification requires recent training totalling >= %s hours"
            % RECERT_MIN_HOURS,
        )


def _decertify_cascade(o):
    """Three linked steps: revert active assigned cases to TRIAGE, moot their
    PROPOSED rounds with an AUDIT note each, withdraw the ombudsman's DRAFT
    referrals on the reverted cases."""
    for c in db.cases.values():
        if (c["assigned_ombudsman_id"] == o["id"]
                and c["status"] in ACTIVE_CASELOAD_STATUSES):
            c["status"] = "TRIAGE"
            c["assigned_ombudsman_id"] = None
            touch(c)
            for r in db.rounds.values():
                if r["case_id"] == c["id"] and r["status"] == "PROPOSED":
                    r["status"] = "CLOSED_MOOT"
                    touch(r)
                    add_audit_note(
                        c["id"],
                        "Mediation round %d closed moot on ombudsman decertification"
                        % r["round_number"],
                    )
            for ref in db.referrals.values():
                if (ref["case_id"] == c["id"] and ref["status"] == "DRAFT"
                        and ref["created_by_ombudsman_id"] == o["id"]):
                    ref["status"] = "WITHDRAWN"
                    touch(ref)


@bp.route("/reemployment/ombudsmen/<oid>/state", methods=["POST"])
def ombudsman_state(oid):
    role, uid = require_role("ProgramCoordinator")
    body = body_json()
    to_status = req_enum(body, "to_status", OMBUDSMAN_STATUSES)
    o = get_ombudsman(oid)
    apply_ombudsman_expiry(o)
    frm = o["status"]
    if to_status == "CERTIFIED":
        if frm == "TRAINEE":
            _segregation_check(o, uid)
            _cert_requirements(o)
            o["certified_on"] = now()
            o["certification_expires_on"] = add_months(now(), CERT_TERM_MONTHS)
            o["status"] = "CERTIFIED"
        elif frm == "ON_LEAVE":
            exp = o["certification_expires_on"]
            if exp is not None and now() > exp:
                raise ApiError(
                    "ERR_INVALID_STATE", 409,
                    "Certification has expired; the volunteer is EXPIRED",
                )
            o["status"] = "CERTIFIED"
        elif frm == "EXPIRED":
            _segregation_check(o, uid)
            _recert_requirements(o)
            o["certified_on"] = now()
            o["certification_expires_on"] = add_months(now(), CERT_TERM_MONTHS)
            o["status"] = "CERTIFIED"
        else:
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition from %s to CERTIFIED" % frm,
            )
    elif to_status == "ON_LEAVE":
        if frm != "CERTIFIED":
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition from %s to ON_LEAVE" % frm,
            )
        o["status"] = "ON_LEAVE"
    elif to_status == "DECERTIFIED":
        if frm == "CERTIFIED":
            _decertify_cascade(o)
            o["status"] = "DECERTIFIED"
        elif frm == "TRAINEE":
            o["status"] = "DECERTIFIED"
        else:
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "Cannot transition from %s to DECERTIFIED" % frm,
            )
    else:
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "No transition to %s exists" % to_status,
        )
    touch(o)
    return success(ser_ombudsman(o))


@bp.route("/reemployment/training-records", methods=["POST"])
def create_training_record():
    role, uid = require_role("ProgramCoordinator")
    body = body_json()
    ombudsman_id = req_str(body, "ombudsman_id")
    module_code = req_enum(body, "module_code", MODULE_CODES)
    hours = req_num(body, "hours")
    exam_score = req_int(body, "exam_score")
    if exam_score < 0 or exam_score > 100:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "exam_score must be between 0 and 100"
        )
    completed_on = req_dt(body, "completed_on")
    get_ombudsman(ombudsman_id)
    tid = new_id()
    rec = {
        "id": tid, "ombudsman_id": ombudsman_id, "module_code": module_code,
        "hours": hours, "exam_score": exam_score, "completed_on": completed_on,
        "proctor_id": uid, "created_at": now(), "_seq": db.next_seq(),
    }
    db.training_records[tid] = rec
    return success(ser_training(rec), "object", 201)


@bp.route("/reemployment/ombudsmen/<oid>/training-records", methods=["GET"])
def list_training_records(oid):
    role, uid = require_role("Ombudsman", "ProgramCoordinator")
    get_ombudsman(oid)
    if role == "Ombudsman":
        require_ownership(oid == uid)
    items = [t for t in db.training_records.values() if t["ombudsman_id"] == oid]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    page, meta = paginate(items)
    return success([ser_training(t) for t in page], "array", 200, meta)
