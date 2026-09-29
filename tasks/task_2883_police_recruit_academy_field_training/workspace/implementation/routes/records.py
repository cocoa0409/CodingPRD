"""The immutable training record and the logical clock."""
from flask import Blueprint

import serial
from core import fail, fmt_instant, store, touch
from routes.common import listing, ok, path_row, require_roles
from validate import body, query_enum, query_str, req_instant

bp = Blueprint("records", __name__)

ENTRY_KINDS = (
    "STAGE_ENTRY",
    "ADVERSE_EXIT",
    "HOURS_CREDIT",
    "HOURS_REVERSAL",
    "SCREENING_ADJUDICATION",
    "EXAM_RESULT",
    "DOR_FILED",
    "PROBATION_DECISION",
    "CERTIFICATION_ISSUED",
)
STAGE_CODES = ("SCREENING", "ACADEMY", "FIELD_TRAINING", "PROBATION")
ENTRY_ROLES = ("AcademyDirector", "RecordsCustodian", "TrainingCoordinator")
CLOCK_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
               "BackgroundInvestigator", "MedicalExaminer", "AcademyInstructor",
               "FieldTrainingOfficer")


@bp.get("/training-record-entries/<training_record_entry_id>")
def read_entry(training_record_entry_id):
    require_roles(*ENTRY_ROLES)
    row = path_row("entries", training_record_entry_id)
    return ok(serial.entry_json(row))


@bp.get("/training-record-entries")
def list_entries():
    require_roles(*ENTRY_ROLES)
    recruit_id = query_str("recruit_id")
    academy_class_id = query_str("academy_class_id")
    kind = query_enum("kind", ENTRY_KINDS)
    stage_code = query_enum("stage_code", STAGE_CODES)

    def predicate(row):
        if recruit_id is not None and row["recruit_id"] != recruit_id:
            return False
        if academy_class_id is not None and row["academy_class_id"] != academy_class_id:
            return False
        if kind is not None and row["kind"] != kind:
            return False
        if stage_code is not None and row["stage_code"] != stage_code:
            return False
        return True

    return listing("entries", serial.entry_json, predicate)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(*CLOCK_ROLES)
    payload = body()
    target = req_instant(payload, "current_utc")

    if target < store.clock:
        fail("ERR_CLOCK_NOT_MONOTONIC",
             "the logical clock never moves backwards")

    store.clock = target
    for instructor in store.instructors.values():
        expires_at = instructor.get("certification_expires_at")
        if (instructor["certification_status"] == "CERTIFIED"
                and expires_at is not None
                and expires_at < target):
            instructor["certification_status"] = "EXPIRED"
            touch(instructor)
    return ok({"current_utc": fmt_instant(target)})
