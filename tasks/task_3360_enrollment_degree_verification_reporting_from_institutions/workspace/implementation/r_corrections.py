"""Correction case filing and decision (PRD §3.5) with the full
supersede/notification cascade and segregation of duties.
"""
import math

from flask import Blueprint, request

import calc
import cascade
import db
from auth import (
    ROLE_CERTIFIER,
    ROLE_CLEARINGHOUSE_OPS,
    ROLE_SUBMITTER,
    REGISTRAR_ROLES,
    authenticate,
    require_role,
)
from core import (
    ERR_CASE_NOT_FOUND,
    ERR_CROSS_INSTITUTION_ACCESS,
    ERR_ENTRY_NOT_FOUND,
    ERR_ENTRY_SUPERSEDED,
    ERR_INVALID_STATE,
    ERR_OPEN_CORRECTION_EXISTS,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
    ERR_VALIDATION,
    get_body,
    list_response,
    ok_object,
    opt_bool,
    raise_err,
    req_enum,
    req_field,
    req_str,
    try_parse_dt,
)

bp = Blueprint("corrections", __name__)

READ_ROLES = (ROLE_CLEARINGHOUSE_OPS, ROLE_SUBMITTER, ROLE_CERTIFIER)
FILE_ROLES = (ROLE_SUBMITTER, ROLE_CERTIFIER)
REASON_CODES = ("REPORTING_ERROR", "STATUS_MISSTATEMENT", "LATE_WITHDRAWAL_NOTICE")


def _entry_institution(case):
    entry = db.store.entries.get(case["enrollment_entry_id"])
    return entry["institution_id"] if entry else None


@bp.route("/correction-cases", methods=["POST"])
def file_case():
    caller = authenticate()
    require_role(caller, *FILE_ROLES)
    data = get_body()
    entry_id = req_str(data, "enrollment_entry_id")
    reason_code = req_enum(data, "reason_code", REASON_CODES)
    clear_withdrawal = opt_bool(data, "clear_withdrawal_date", False)

    corrected_credits = None
    if data.get("corrected_credit_hours") is not None:
        v = data["corrected_credit_hours"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise_err(ERR_VALIDATION, "corrected_credit_hours must be a number")
        if v < 0 or v > calc.MAX_CREDIT_HOURS:
            raise_err(ERR_VALIDATION, "corrected_credit_hours out of range 0..30")
        corrected_credits = v

    corrected_withdrawal = None
    if data.get("corrected_withdrawal_date") is not None:
        corrected_withdrawal = try_parse_dt(data["corrected_withdrawal_date"])
        if corrected_withdrawal is None:
            raise_err(ERR_VALIDATION, "corrected_withdrawal_date is not a valid date")
    if clear_withdrawal and corrected_withdrawal is not None:
        raise_err(ERR_VALIDATION, "clear_withdrawal_date and corrected_withdrawal_date are mutually exclusive")

    entry = db.store.entries.get(entry_id)
    if entry is None:
        raise_err(ERR_ENTRY_NOT_FOUND, "enrollment entry not found")
    if caller.institution_id != entry["institution_id"]:
        raise_err(ERR_CROSS_INSTITUTION_ACCESS, "filer's institution does not match the entry's")
    file = db.store.files.get(entry["file_id"])
    if file is None or file["status"] not in ("CERTIFIED", "AMENDMENT_PENDING"):
        raise_err(ERR_INVALID_STATE, "corrections target entries of CERTIFIED or AMENDMENT_PENDING files")
    if entry["entry_status"] == "SUPERSEDED":
        raise_err(ERR_ENTRY_SUPERSEDED, "cannot file a correction against a SUPERSEDED entry")
    if entry["entry_status"] != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, "corrections target ACCEPTED entries")
    for c in db.store.cases.values():
        if c["enrollment_entry_id"] == entry_id and c["status"] == "FILED":
            raise_err(ERR_OPEN_CORRECTION_EXISTS, "a FILED correction case already exists for this entry")

    case = db.new_entity(
        {
            "enrollment_entry_id": entry_id,
            "filed_by_user_id": caller.user_id,
            "corrected_credit_hours": corrected_credits,
            "corrected_withdrawal_date": corrected_withdrawal,
            "clear_withdrawal_date": clear_withdrawal,
            "reason_code": reason_code,
            "status": "FILED",
            "decided_by_user_id": None,
            "decided_at": None,
        }
    )
    db.store.cases[case["id"]] = case
    if file["status"] == "CERTIFIED":
        file["status"] = "AMENDMENT_PENDING"
    file["open_correction_count"] += 1
    db.touch(file)
    return ok_object(db.serialize(case), 201)


@bp.route("/correction-cases/<cid>", methods=["GET"])
def get_case(cid):
    caller = authenticate()
    require_role(caller, *READ_ROLES)
    case = db.store.cases.get(cid)
    if case is None:
        raise_err(ERR_CASE_NOT_FOUND, "correction case not found")
    if caller.role in REGISTRAR_ROLES and caller.institution_id != _entry_institution(case):
        raise_err(ERR_UNAUTHORIZED, "registrar user may only access own institution's resources")
    return ok_object(db.serialize(case))


@bp.route("/correction-cases", methods=["GET"])
def list_cases():
    caller = authenticate()
    require_role(caller, *READ_ROLES)
    q = request.args
    items = list(db.store.cases.values())
    if caller.role in REGISTRAR_ROLES:
        items = [c for c in items if _entry_institution(c) == caller.institution_id]
    if q.get("enrollment_entry_id") is not None:
        items = [c for c in items if c["enrollment_entry_id"] == q["enrollment_entry_id"]]
    if q.get("filed_by_user_id") is not None:
        items = [c for c in items if c["filed_by_user_id"] == q["filed_by_user_id"]]
    if q.get("status") is not None:
        items = [c for c in items if c["status"] == q["status"]]
    return list_response(db.sorted_created(items), db.serialize)


def _close_case_on_file(file):
    file["open_correction_count"] -= 1
    if file["open_correction_count"] == 0 and file["status"] == "AMENDMENT_PENDING":
        file["status"] = "CERTIFIED"
    db.touch(file)


@bp.route("/correction-cases/<cid>/decision", methods=["POST"])
def decide_case(cid):
    caller = authenticate()
    require_role(caller, ROLE_CERTIFIER)
    data = get_body()
    outcome = req_enum(data, "outcome", ("APPROVED", "DENIED"))
    case = db.store.cases.get(cid)
    if case is None:
        raise_err(ERR_CASE_NOT_FOUND, "correction case not found")
    entry = db.store.entries.get(case["enrollment_entry_id"])
    if entry is None:
        raise_err(ERR_ENTRY_NOT_FOUND, "enrollment entry not found")
    if caller.institution_id != entry["institution_id"]:
        raise_err(ERR_CROSS_INSTITUTION_ACCESS, "decider's institution does not match the entry's")
    if case["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "only a FILED case can be decided")
    if caller.user_id == case["filed_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "the deciding certifier must differ from the filer")

    now = db.now()
    case["decided_by_user_id"] = caller.user_id
    case["decided_at"] = now
    file = db.store.files.get(entry["file_id"])

    if outcome == "DENIED":
        case["status"] = "DENIED"
        db.touch(case)
        if file is not None:
            _close_case_on_file(file)
        return ok_object(db.serialize(case))

    # APPROVED: supersede the old entry and install a replacement (PRD §3.5).
    case["status"] = "APPLIED"
    db.touch(case)

    old_deferment = entry["deferment_status"]
    entry["entry_status"] = "SUPERSEDED"
    db.touch(entry)

    if case["clear_withdrawal_date"]:
        new_withdrawal = None
    elif case["corrected_withdrawal_date"] is not None:
        new_withdrawal = case["corrected_withdrawal_date"]
    else:
        new_withdrawal = entry["withdrawal_date"]
    new_credits = (
        case["corrected_credit_hours"]
        if case["corrected_credit_hours"] is not None
        else entry["credit_hours"]
    )

    replacement = db.new_entity(
        {
            "file_id": entry["file_id"],
            "institution_id": entry["institution_id"],
            "student_id": entry["student_id"],
            "student_ref": entry["student_ref"],
            "row_index": file["row_count"],
            "credit_hours": new_credits,
            "career_level": entry["career_level"],
            "term_start": entry["term_start"],
            "term_end": entry["term_end"],
            "withdrawal_date": new_withdrawal,
            "servicer_ref": entry["servicer_ref"],
            "entry_status": "ACCEPTED",
            "reject_reason": "NONE",
            "status_code": "NONE",
            "census_status_code": "NONE",
            "deferment_status": "NONE",
            "source_case_id": case["id"],
        }
    )
    # Statuses recomputed as-of the decision date (PRD §3.5).
    calc.recompute_entry(replacement, now)
    db.store.entries[replacement["id"]] = replacement

    file["row_count"] += 1
    file["accepted_rows"] += 1

    # Notification cascade: only when the determination actually changed.
    if replacement["deferment_status"] != old_deferment:
        cascade.supersede_notifications_for_entry(entry["id"])
        if replacement["servicer_ref"]:
            cascade.generate_notification(replacement)

    _close_case_on_file(file)
    return ok_object(db.serialize(case))
