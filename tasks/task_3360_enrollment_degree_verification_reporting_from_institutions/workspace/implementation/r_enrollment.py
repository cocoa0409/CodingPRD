"""Enrollment file upload/screening/certification and entry reads
(PRD §3.3, §3.4).
"""
import math
from decimal import Decimal

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
    ERR_AGREEMENT_LAPSED,
    ERR_CROSS_INSTITUTION_ACCESS,
    ERR_ENTRY_NOT_FOUND,
    ERR_FILE_NOT_FOUND,
    ERR_INSTITUTION_NOT_FOUND,
    ERR_INSTITUTION_SUSPENDED,
    ERR_INVALID_STATE,
    ERR_PERIOD_NOT_FOUND,
    ERR_PERIOD_NOT_OPEN,
    ERR_STALE_VERSION,
    ERR_UNRESOLVED_ROWS,
    ERR_VALIDATION,
    get_body,
    list_response,
    ok_object,
    raise_err,
    req_field,
    req_int,
    req_str,
    try_parse_dt,
)

bp = Blueprint("enrollment", __name__)

READ_ROLES = (ROLE_CLEARINGHOUSE_OPS, ROLE_SUBMITTER, ROLE_CERTIFIER)

ROW_REQUIRED = (
    "full_name",
    "date_of_birth",
    "student_ref",
    "credit_hours",
    "career_level",
    "term_start",
    "term_end",
)


def _valid_credit_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _screen_row(row, seen_refs):
    """Deterministic row screening (PRD §3.3). Returns (parsed, reject_reason).
    parsed is None for rejected rows; reject_reason is None for clean rows."""
    if not isinstance(row, dict):
        return None, "MISSING_FIELD"
    for f in ROW_REQUIRED:
        if f not in row or row[f] is None:
            return None, "MISSING_FIELD"
    if not isinstance(row["full_name"], str) or not isinstance(row["student_ref"], str):
        return None, "MISSING_FIELD"
    # A row's student_ref counts as "already-seen" even when the row itself is
    # rejected for another reason (PRD §3.3: "an already-seen student_ref").
    ref = row["student_ref"]
    is_duplicate = ref in seen_refs
    seen_refs.add(ref)

    dob = try_parse_dt(row["date_of_birth"])
    if dob is None:
        return None, "MISSING_FIELD"
    servicer_ref = row.get("servicer_ref")
    if servicer_ref is not None and not isinstance(servicer_ref, str):
        return None, "MISSING_FIELD"

    career = row["career_level"]
    if not isinstance(career, str) or career not in ("UNDERGRAD", "GRADUATE"):
        return None, "INVALID_ENUM_VALUE"

    credits = row["credit_hours"]
    if not _valid_credit_number(credits) or credits < 0 or credits > calc.MAX_CREDIT_HOURS:
        return None, "INVALID_CREDITS"

    term_start = try_parse_dt(row["term_start"])
    term_end = try_parse_dt(row["term_end"])
    if term_start is None or term_end is None or not term_end > term_start:
        return None, "INVALID_TERM_DATES"

    withdrawal = row.get("withdrawal_date")
    if withdrawal is not None:
        withdrawal = try_parse_dt(withdrawal)
        if withdrawal is None or not (term_start <= withdrawal <= term_end):
            return None, "INVALID_WITHDRAWAL_DATE"

    if is_duplicate:
        return None, "DUPLICATE_STUDENT_IN_FILE"

    parsed = {
        "full_name": row["full_name"],
        "date_of_birth": dob,
        "student_ref": ref,
        "credit_hours": credits,
        "career_level": career,
        "term_start": term_start,
        "term_end": term_end,
        "withdrawal_date": withdrawal,
        "servicer_ref": servicer_ref,
    }
    return parsed, None

    parsed = {
        "full_name": row["full_name"],
        "date_of_birth": dob,
        "student_ref": ref,
        "credit_hours": credits,
        "career_level": career,
        "term_start": term_start,
        "term_end": term_end,
        "withdrawal_date": withdrawal,
        "servicer_ref": servicer_ref,
    }
    return parsed, None


def _resolve_student(full_name, dob):
    """Match on (lower(trim(full_name)), date_of_birth); create otherwise."""
    key = full_name.strip().lower()
    for s in db.store.students.values():
        if s["full_name"].strip().lower() == key and s["date_of_birth"] == dob:
            return s
    s = db.new_entity(
        {"full_name": full_name, "date_of_birth": dob, "deferment_standing": "NONE"}
    )
    db.store.students[s["id"]] = s
    return s


@bp.route("/enrollment-files", methods=["POST"])
def upload_file():
    caller = authenticate()
    require_role(caller, ROLE_SUBMITTER)
    data = get_body()
    # Tenancy (priority 4) precedes payload well-formedness (priority 7).
    raw_inst = data.get("institution_id")
    if isinstance(raw_inst, str) and raw_inst != caller.institution_id:
        raise_err(ERR_CROSS_INSTITUTION_ACCESS, "submitter's institution does not match the file's")
    institution_id = req_str(data, "institution_id")
    period_id = req_str(data, "reporting_period_id")
    expected_version = req_int(data, "expected_reporting_period_version")
    rows = req_field(data, "rows")
    if not isinstance(rows, list):
        raise_err(ERR_VALIDATION, "field 'rows' must be an array")

    inst = db.store.institutions.get(institution_id)
    if inst is None:
        raise_err(ERR_INSTITUTION_NOT_FOUND, "institution not found")
    period = db.store.periods.get(period_id)
    if period is None or period["institution_id"] != institution_id:
        raise_err(ERR_PERIOD_NOT_FOUND, "reporting period not found")
    # OCC on the period (PRD §2.6).
    if expected_version != period["version"]:
        raise_err(ERR_STALE_VERSION, "expected_reporting_period_version is stale")
    if inst["status"] != "ACTIVE":
        raise_err(ERR_INSTITUTION_SUSPENDED, "institution is suspended")
    if not cascade.active_agreement_covers(institution_id):
        raise_err(ERR_AGREEMENT_LAPSED, "no ACTIVE agreement covers now")
    if period["status"] == "SCHEDULED":
        raise_err(ERR_PERIOD_NOT_OPEN, "reporting period is still SCHEDULED")

    now = db.now()
    file = db.new_entity(
        {
            "institution_id": institution_id,
            "reporting_period_id": period_id,
            "submitted_by_user_id": caller.user_id,
            "row_count": 0,
            "accepted_rows": 0,
            "rejected_rows": 0,
            "status": "UPLOADED",
            "certified_at": None,
            "late_submission": False,
            "open_correction_count": 0,
        }
    )
    db.store.files[file["id"]] = file

    seen_refs = set()
    accepted = 0
    rejected = 0
    for idx, row in enumerate(rows):
        parsed, reason = _screen_row(row, seen_refs)
        if parsed is None:
            rejected += 1
            entry = db.new_entity(
                {
                    "file_id": file["id"],
                    "institution_id": institution_id,
                    "student_id": None,
                    "student_ref": row.get("student_ref") if isinstance(row, dict) else None,
                    "row_index": idx,
                    "credit_hours": row.get("credit_hours") if isinstance(row, dict) and _valid_credit_number(row.get("credit_hours")) else None,
                    "career_level": row.get("career_level") if isinstance(row, dict) else None,
                    "term_start": try_parse_dt(row.get("term_start")) if isinstance(row, dict) else None,
                    "term_end": try_parse_dt(row.get("term_end")) if isinstance(row, dict) else None,
                    "withdrawal_date": try_parse_dt(row.get("withdrawal_date")) if isinstance(row, dict) and row.get("withdrawal_date") is not None else None,
                    "servicer_ref": row.get("servicer_ref") if isinstance(row, dict) and isinstance(row.get("servicer_ref"), str) else None,
                    "entry_status": "REJECTED",
                    "reject_reason": reason,
                    "status_code": "NONE",
                    "census_status_code": "NONE",
                    "deferment_status": "NONE",
                    "source_case_id": None,
                }
            )
        else:
            accepted += 1
            student = _resolve_student(parsed["full_name"], parsed["date_of_birth"])
            entry = db.new_entity(
                {
                    "file_id": file["id"],
                    "institution_id": institution_id,
                    "student_id": student["id"],
                    "student_ref": parsed["student_ref"],
                    "row_index": idx,
                    "credit_hours": parsed["credit_hours"],
                    "career_level": parsed["career_level"],
                    "term_start": parsed["term_start"],
                    "term_end": parsed["term_end"],
                    "withdrawal_date": parsed["withdrawal_date"],
                    "servicer_ref": parsed["servicer_ref"],
                    "entry_status": "ACCEPTED",
                    "reject_reason": "NONE",
                    "status_code": "NONE",
                    "census_status_code": "NONE",
                    "deferment_status": "NONE",
                    "source_case_id": None,
                }
            )
            # Statuses computed as-of the upload date (PRD §3.3/§3.4).
            calc.recompute_entry(entry, now)
        db.store.entries[entry["id"]] = entry

    file["row_count"] = len(rows)
    file["accepted_rows"] = accepted
    file["rejected_rows"] = rejected

    # Upload supersedes any prior UPLOADED (uncertified) file for the period;
    # its REJECTED entries (keeping reject_reason) and ACCEPTED entries move
    # to SUPERSEDED with it (PRD §3.3).
    for f in db.store.files.values():
        if f["reporting_period_id"] == period_id and f["id"] != file["id"] and f["status"] == "UPLOADED":
            f["status"] = "SUPERSEDED"
            db.touch(f)
            cascade.supersede_file_entries(f, include_rejected=True)

    period["upload_count"] += 1
    db.touch(period)
    return ok_object(db.serialize(file), 201)


@bp.route("/enrollment-files/<fid>", methods=["GET"])
def get_file(fid):
    caller = authenticate()
    require_role(caller, *READ_ROLES)
    file = db.store.files.get(fid)
    if file is None:
        raise_err(ERR_FILE_NOT_FOUND, "enrollment file not found")
    if caller.role in REGISTRAR_ROLES and caller.institution_id != file["institution_id"]:
        from core import ERR_UNAUTHORIZED

        raise_err(ERR_UNAUTHORIZED, "registrar user may only access own institution's resources")
    return ok_object(db.serialize(file))


@bp.route("/enrollment-files", methods=["GET"])
def list_files():
    caller = authenticate()
    require_role(caller, *READ_ROLES)
    q = request.args
    institution_id = q.get("institution_id")
    if caller.role in REGISTRAR_ROLES:
        if institution_id is not None and institution_id != caller.institution_id:
            from core import ERR_UNAUTHORIZED

            raise_err(ERR_UNAUTHORIZED, "registrar user may only access own institution's resources")
        institution_id = caller.institution_id
    items = list(db.store.files.values())
    if institution_id is not None:
        items = [f for f in items if f["institution_id"] == institution_id]
    if q.get("reporting_period_id") is not None:
        items = [f for f in items if f["reporting_period_id"] == q["reporting_period_id"]]
    if q.get("submitted_by_user_id") is not None:
        items = [f for f in items if f["submitted_by_user_id"] == q["submitted_by_user_id"]]
    if q.get("status") is not None:
        items = [f for f in items if f["status"] == q["status"]]
    return list_response(db.sorted_created(items), db.serialize)


@bp.route("/enrollment-files/<fid>/certify", methods=["POST"])
def certify_file(fid):
    caller = authenticate()
    require_role(caller, ROLE_CERTIFIER)
    file = db.store.files.get(fid)
    if file is None:
        raise_err(ERR_FILE_NOT_FOUND, "enrollment file not found")
    if caller.institution_id != file["institution_id"]:
        raise_err(ERR_CROSS_INSTITUTION_ACCESS, "certifier's institution does not match the file's")
    if file["status"] != "UPLOADED":
        raise_err(ERR_INVALID_STATE, "only an UPLOADED file can be certified")
    inst = db.store.institutions.get(file["institution_id"])
    if inst is None:
        raise_err(ERR_INSTITUTION_NOT_FOUND, "institution not found")
    if inst["status"] != "ACTIVE":
        raise_err(ERR_INSTITUTION_SUSPENDED, "institution is suspended")
    if not cascade.active_agreement_covers(file["institution_id"]):
        raise_err(ERR_AGREEMENT_LAPSED, "no ACTIVE agreement covers now")
    if file["rejected_rows"] > 0:
        raise_err(ERR_UNRESOLVED_ROWS, "file carries rejected rows and can never be certified")

    now = db.now()
    period = db.store.periods.get(file["reporting_period_id"])
    file["certified_at"] = now
    file["late_submission"] = period is not None and now > period["submission_due_at"]

    # Supersede any other CERTIFIED / AMENDMENT_PENDING file for this period,
    # with its entries and undelivered notifications (PRD §3.4).
    for f in db.store.files.values():
        if (
            f["reporting_period_id"] == file["reporting_period_id"]
            and f["id"] != file["id"]
            and f["status"] in ("CERTIFIED", "AMENDMENT_PENDING")
        ):
            cascade.supersede_certified_file(f)

    # Recompute every ACCEPTED entry as-of certified_at and feed servicers.
    for e in db.store.entries.values():
        if e["file_id"] == file["id"] and e["entry_status"] == "ACCEPTED":
            calc.recompute_entry(e, now)
            db.touch(e)
            cascade.generate_notification(e)

    file["status"] = "CERTIFIED"
    db.touch(file)

    if period is not None:
        if period["outcome"] in ("NONE", "DELINQUENT"):
            period["outcome"] = "LATE" if file["late_submission"] else "ON_TIME"
        db.touch(period)
    inst["compliance_standing"] = calc.compliance_standing(inst["id"])
    db.touch(inst)
    return ok_object(db.serialize(file))


@bp.route("/enrollment-entries/<eid>", methods=["GET"])
def get_entry(eid):
    caller = authenticate()
    require_role(caller, *READ_ROLES)
    entry = db.store.entries.get(eid)
    if entry is None:
        raise_err(ERR_ENTRY_NOT_FOUND, "enrollment entry not found")
    if caller.role in REGISTRAR_ROLES and caller.institution_id != entry["institution_id"]:
        from core import ERR_UNAUTHORIZED

        raise_err(ERR_UNAUTHORIZED, "registrar user may only access own institution's resources")
    return ok_object(db.serialize(entry))


@bp.route("/enrollment-entries", methods=["GET"])
def list_entries():
    caller = authenticate()
    require_role(caller, *READ_ROLES)
    q = request.args
    institution_id = q.get("institution_id")
    if caller.role in REGISTRAR_ROLES:
        if institution_id is not None and institution_id != caller.institution_id:
            from core import ERR_UNAUTHORIZED

            raise_err(ERR_UNAUTHORIZED, "registrar user may only access own institution's resources")
        institution_id = caller.institution_id
    items = list(db.store.entries.values())
    if q.get("file_id") is not None:
        items = [e for e in items if e["file_id"] == q["file_id"]]
    if q.get("student_id") is not None:
        items = [e for e in items if e["student_id"] == q["student_id"]]
    if institution_id is not None:
        items = [e for e in items if e["institution_id"] == institution_id]
    if q.get("entry_status") is not None:
        items = [e for e in items if e["entry_status"] == q["entry_status"]]
    # File order: row_index ASC within a file, then created_at ASC (PRD §3.3).
    items.sort(key=lambda e: e["row_index"])
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))  # stable
    return list_response(items, db.serialize)
