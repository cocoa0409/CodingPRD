"""Due-process records and stay-put protection (PRD section 3.9)."""
from flask import Blueprint

from auth import COMPLIANCE_OFFICER, endpoint
from envelope import created, ok
from errors import ApiError
from ledgers import recompute_student_ledger
from resolve import body_ref, path_ref
from serialize import public
from store import db, new_record, now_iso, touch
from validate import body, opt_str, req_date, req_enum, req_str

bp = Blueprint("due_process", __name__)

RECORD_TYPES = ("COMPLAINT", "DUE_PROCESS_HEARING", "MEDIATION_AGREEMENT")
STAY_PUT_TYPES = ("COMPLAINT", "DUE_PROCESS_HEARING")
CLOSING_STATUSES = ("RESOLVED", "DISMISSED")


@bp.post("/esy/due-process-records")
@endpoint((COMPLIANCE_OFFICER,))
def create_due_process_record():
    data = body()
    body_ref(data, "student_id", "student")

    student_id = req_str(data, "student_id", 1, None)
    record_type = req_enum(data, "record_type", RECORD_TYPES)
    filed_on = req_date(data, "filed_on")
    allegation_summary = req_str(data, "allegation_summary", 1, 500)

    record = new_record("DueProcessRecord", {
        "student_id": student_id,
        "record_type": record_type,
        "filed_on": filed_on,
        "allegation_summary": allegation_summary,
        "status": "OPEN",
        "stay_put_active": record_type in STAY_PUT_TYPES,
        "resolution_note": None,
        "resolved_at": None,
    })
    db.records[record["id"]] = record

    student = db.students.get(student_id)
    if student is not None:
        recompute_student_ledger(student)
    return created(public(record))


@bp.patch("/esy/due-process-records/<record_id>")
@endpoint((COMPLIANCE_OFFICER,))
def close_due_process_record(record_id):
    record = path_ref("record", record_id)
    data = body()
    target = req_enum(data, "status", CLOSING_STATUSES)
    resolution_note = opt_str(data, "resolution_note", 1, None)

    if record["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")

    record["status"] = target
    if resolution_note is not None:
        record["resolution_note"] = resolution_note
    if target == "RESOLVED":
        record["resolved_at"] = now_iso()
    record["stay_put_active"] = False
    touch(record)

    student = db.students.get(record["student_id"])
    if student is not None:
        recompute_student_ledger(student)
    return ok(public(record))
