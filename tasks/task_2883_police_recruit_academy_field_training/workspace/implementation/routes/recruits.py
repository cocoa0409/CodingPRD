"""Recruits: intake, stage advancement, exits, probation decisions, progress."""
from flask import Blueprint, g, request

import calc
import ops
import serial
from core import base_row, d2, fail, num, store, today, touch
from routes.common import (
    body_fk,
    check_recruit_not_terminal,
    created,
    listing,
    ok,
    path_row,
    require_roles,
    unique_or_conflict,
)
from validate import (
    body,
    opt_int,
    query_enum,
    query_str,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("recruits", __name__)

AGE_BRACKETS = ("AGE_20_29", "AGE_30_39", "AGE_40_49")
PIPELINE_STAGES = ("APPLICANT", "SCREENING", "ACADEMY", "FIELD_TRAINING", "PROBATION",
                   "CERTIFIED", "DISMISSED", "WITHDRAWN")
CLEARANCE_STATUSES = ("PENDING", "PARTIAL", "CLEARED", "DISQUALIFIED")
ACADEMY_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "REMEDIATION", "DISMISSAL_PENDING", "COMPLETE")
PROBATION_STATUSES = ("NOT_APPLICABLE", "ACTIVE", "EXTENSION_REQUIRED", "PASSED", "SEPARATED")
SCREENING_TYPES = ("BACKGROUND", "MEDICAL", "PSYCHOLOGICAL", "PHYSICAL_FITNESS")
REASON_CODES = ("ACADEMIC_FAILURE", "ABSENCE_LIMIT", "INTEGRITY", "MEDICAL",
                "FIELD_TRAINING_FAILURE", "PROBATION_SEPARATION", "VOLUNTARY_WITHDRAWAL")
SUCCESSOR = {
    "SCREENING": "ACADEMY",
    "ACADEMY": "FIELD_TRAINING",
    "FIELD_TRAINING": "PROBATION",
}

READ_ONE_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
                  "BackgroundInvestigator", "MedicalExaminer", "FieldTrainingOfficer", "Recruit")
LIST_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian")
PROGRESS_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian", "Recruit")


def _own_recruit_or_403(recruit_id):
    """Rung 4: the entity-backed Recruit identity may only read its own row."""
    if g.role == "Recruit" and g.user_id != recruit_id:
        fail("ERR_NOT_RESOURCE_OWNER", "recruit identity may only read its own record")


@bp.post("/recruits")
def create_recruit():
    require_roles("TrainingCoordinator", "AcademyDirector")
    payload = body()
    cls = body_fk(payload, "academy_class_id", "classes")
    class_id = req_str(payload, "academy_class_id", min_len=1, max_len=200)
    applicant_number = req_str(payload, "applicant_number", min_len=1, max_len=24)
    full_name = req_str(payload, "full_name", min_len=1, max_len=120)
    date_of_birth = req_date(payload, "date_of_birth")
    age_bracket = req_enum(payload, "age_bracket", AGE_BRACKETS)
    if cls is None:
        fail("ERR_ACADEMY_CLASS_NOT_FOUND", "academy class does not exist")

    unique_or_conflict("recruits", "applicant_number", applicant_number)

    row = base_row()
    row.update({
        "academy_class_id": class_id,
        "applicant_number": applicant_number,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "age_bracket": age_bracket,
        "pipeline_stage": "APPLICANT",
        "clearance_status": "PENDING",
        "academy_status": "NOT_STARTED",
        "probation_status": "NOT_APPLICABLE",
        "probation_start": None,
        "probation_base_days": 365,
        "probation_extension_days": 0,
        "probation_milestone_due_date": None,
        "probation_milestone_score": None,
        "probation_scheduled_end": None,
        "dismissal_reason_code": None,
    })
    store.recruits[row["id"]] = row
    return created(serial.recruit_json(row))


@bp.get("/recruits/<recruit_id>")
def read_recruit(recruit_id):
    require_roles(*READ_ONE_ROLES)
    _own_recruit_or_403(recruit_id)
    row = path_row("recruits", recruit_id)
    return ok(serial.recruit_json(row))


@bp.get("/recruits")
def list_recruits():
    require_roles(*LIST_ROLES)
    class_id = query_str("academy_class_id")
    pipeline_stage = query_enum("pipeline_stage", PIPELINE_STAGES)
    clearance_status = query_enum("clearance_status", CLEARANCE_STATUSES)
    academy_status = query_enum("academy_status", ACADEMY_STATUSES)
    probation_status = query_enum("probation_status", PROBATION_STATUSES)

    def predicate(row):
        if class_id is not None and row["academy_class_id"] != class_id:
            return False
        if pipeline_stage is not None and row["pipeline_stage"] != pipeline_stage:
            return False
        if clearance_status is not None and row["clearance_status"] != clearance_status:
            return False
        if academy_status is not None and row["academy_status"] != academy_status:
            return False
        if probation_status is not None and row["probation_status"] != probation_status:
            return False
        return True

    return listing("recruits", serial.recruit_json, predicate)


def _substantive_screening_fault(recruit):
    """The two substantive faults behind a DISQUALIFIED clearance."""
    standard = calc.standard_for_recruit(recruit)
    for record in calc.recruit_screenings(recruit["id"]):
        if record["disqualifier_codes"]:
            fail("ERR_DISQUALIFIER_UNWAIVED", "an unwaived disqualifier is on file")
    if standard is not None:
        for record in calc.recruit_screenings(recruit["id"]):
            if record["screening_type"] != "PHYSICAL_FITNESS":
                continue
            score = record["composite_score"]
            if score is not None and int(score) < int(standard["fitness_pass_score"]):
                fail("ERR_FITNESS_STANDARD_NOT_MET", "physical fitness composite is below the bar")
    fail("ERR_CLEARANCE_INCOMPLETE", "clearance is not complete")


@bp.post("/recruits/<recruit_id>/advance-stage")
def advance_stage(recruit_id):
    require_roles("TrainingCoordinator")
    recruit = path_row("recruits", recruit_id)
    payload = body()
    to_stage = req_enum(payload, "to_stage", PIPELINE_STAGES)
    probation_start = None
    probation_base_days = 365
    if to_stage == "PROBATION":
        probation_start = req_date(payload, "probation_start")
        probation_base_days = opt_int(payload, "probation_base_days", minimum=0, default=365)

    check_recruit_not_terminal(recruit)

    current = recruit["pipeline_stage"]
    if SUCCESSOR.get(current) != to_stage:
        fail("ERR_STAGE_TRANSITION_NOT_ALLOWED",
             "%s is not the single legal successor of %s" % (to_stage, current))

    if to_stage == "ACADEMY":
        cls = calc.class_for_recruit(recruit)
        if cls is None or cls["status"] not in ("FORMING", "IN_SESSION", "AT_RISK"):
            fail("ERR_INVALID_STATE", "cohort is not receiving recruits")
        if recruit["clearance_status"] != "CLEARED":
            if recruit["clearance_status"] in ("PENDING", "PARTIAL"):
                fail("ERR_CLEARANCE_INCOMPLETE", "clearance_status is %s"
                     % recruit["clearance_status"])
            _substantive_screening_fault(recruit)
        recruit["pipeline_stage"] = "ACADEMY"
        if recruit["academy_status"] == "NOT_STARTED":
            recruit["academy_status"] = "IN_PROGRESS"
    elif to_stage == "FIELD_TRAINING":
        if recruit["academy_status"] != "COMPLETE":
            fail("ERR_INVALID_STATE", "academy_status must be COMPLETE")
        recruit["pipeline_stage"] = "FIELD_TRAINING"
    else:
        rotations = calc.recruit_rotations(recruit["id"])
        if not any(r["status"] == "COMPLETED" for r in rotations):
            fail("ERR_INVALID_STATE", "no completed field training rotation")
        if any(r["status"] == "PLANNED" for r in rotations):
            fail("ERR_INVALID_STATE", "a planned rotation is still open")
        recruit["pipeline_stage"] = "PROBATION"
        recruit["probation_start"] = probation_start
        recruit["probation_base_days"] = probation_base_days
        recruit["probation_status"] = "ACTIVE"
        calc.derive_probation_schedule(recruit)

    touch(recruit)
    ops.append_entry(
        recruit,
        "STAGE_ENTRY",
        stage_code=to_stage,
        subject_entity="Recruit",
        subject_entity_id=recruit["id"],
        detail="pipeline stage advanced to %s" % to_stage,
    )
    return ok(serial.recruit_json(recruit))


@bp.post("/recruits/<recruit_id>/dismiss")
def dismiss(recruit_id):
    require_roles("AcademyDirector")
    recruit = path_row("recruits", recruit_id)
    payload = body()
    reason_code = req_enum(payload, "reason_code", REASON_CODES)
    req_str(payload, "justification", min_len=1, max_len=2000)

    check_recruit_not_terminal(recruit)
    departed = recruit["pipeline_stage"]
    if departed not in ("SCREENING", "ACADEMY", "FIELD_TRAINING", "PROBATION"):
        fail("ERR_INVALID_STATE", "no exit is declared from %s" % departed)

    recruit["pipeline_stage"] = "WITHDRAWN" if reason_code == "VOLUNTARY_WITHDRAWAL" else "DISMISSED"
    recruit["dismissal_reason_code"] = reason_code
    touch(recruit)

    if departed == "ACADEMY":
        ops.void_provisional_attendance(recruit, "recruit exited pipeline")
    elif departed == "FIELD_TRAINING":
        ops.abort_open_rotations(recruit, "recruit exited pipeline")
    elif departed == "PROBATION":
        if recruit["probation_status"] in ("ACTIVE", "EXTENSION_REQUIRED"):
            recruit["probation_status"] = "SEPARATED"
        ops.abort_open_rotations(recruit, "recruit exited pipeline")

    ops.append_entry(
        recruit,
        "ADVERSE_EXIT",
        stage_code=departed,
        subject_entity="Recruit",
        subject_entity_id=recruit["id"],
        detail="pipeline exit recorded with reason %s" % reason_code,
    )
    return ok(serial.recruit_json(recruit))


@bp.post("/recruits/<recruit_id>/probation-decisions")
def probation_decision(recruit_id):
    require_roles("AcademyDirector")
    recruit = path_row("recruits", recruit_id)
    payload = body()
    decision = req_enum(payload, "decision", ("PASS", "EXTEND", "SEPARATE"))
    req_str(payload, "justification", min_len=1, max_len=2000)

    check_recruit_not_terminal(recruit)

    status = recruit["probation_status"]
    if status not in ("ACTIVE", "EXTENSION_REQUIRED"):
        fail("ERR_PROBATION_NOT_ACTIVE", "probation_status is %s" % status)
    if decision == "PASS":
        if status != "ACTIVE":
            fail("ERR_INVALID_STATE", "PASS is legal from ACTIVE only")
        if recruit["probation_milestone_score"] is None:
            fail("ERR_INVALID_STATE", "no probation milestone score is on file")
        due = recruit["probation_milestone_due_date"]
        if due is not None and today() < due:
            fail("ERR_MILESTONE_NOT_REACHED", "probation milestone date is not reached")
    elif decision == "EXTEND":
        if status != "EXTENSION_REQUIRED":
            fail("ERR_INVALID_STATE", "EXTEND is legal from EXTENSION_REQUIRED only")

    if decision == "PASS":
        recruit["probation_status"] = "PASSED"
    elif decision == "EXTEND":
        recruit["probation_status"] = "ACTIVE"
    else:
        recruit["probation_status"] = "SEPARATED"
        recruit["pipeline_stage"] = "DISMISSED"
        recruit["dismissal_reason_code"] = "PROBATION_SEPARATION"
        ops.abort_open_rotations(recruit, "probation separation")

    touch(recruit)
    calc.derive_probation_schedule(recruit)
    ops.append_entry(
        recruit,
        "ADVERSE_EXIT" if decision == "SEPARATE" else "PROBATION_DECISION",
        stage_code="PROBATION",
        subject_entity="Recruit",
        subject_entity_id=recruit["id"],
        detail="probation decision %s recorded" % decision,
    )
    return ok(serial.recruit_json(recruit))


@bp.get("/recruits/<recruit_id>/certification-progress")
def certification_progress(recruit_id):
    require_roles(*PROGRESS_ROLES)
    _own_recruit_or_403(recruit_id)
    recruit = path_row("recruits", recruit_id)
    basis = query_enum("basis", ("ATTENDED", "SCHEDULED"), default="ATTENDED")
    standard = calc.standard_for_recruit(recruit)

    per_topic = calc.recruit_per_topic_hours(recruit, basis)
    unmet = {}
    if standard is not None:
        for entry in standard["topic_requirements"]:
            code = entry["topic_code"]
            shortfall = d2(entry["required_hours"]) - per_topic.get(code, d2(0))
            unmet[code] = shortfall if shortfall > d2(0) else d2(0)

    return ok({
        "recruit_id": recruit["id"],
        "basis": basis,
        "total_hours": num(calc.recruit_total_hours(recruit, basis)),
        "per_topic_hours": serial.hours_map(per_topic),
        "unmet_topic_hours": serial.hours_map(unmet),
        "exam_status": calc.exam_status_map(recruit, standard),
        "unexcused_absence_hours": num(calc.recruit_unexcused_absence_hours(recruit)),
        "make_up_hours_owed": num(calc.recruit_make_up_hours_owed(recruit)),
        "eligible_for_certification": calc.eligible_for_certification(recruit),
    })


@bp.post("/recruits/<recruit_id>/screenings")
def order_screening(recruit_id):
    require_roles("TrainingCoordinator")
    recruit = path_row("recruits", recruit_id)
    payload = body()
    screening_type = req_enum(payload, "screening_type", SCREENING_TYPES)

    check_recruit_not_terminal(recruit)

    existing = calc.recruit_screenings(recruit["id"])
    for record in existing:
        if record["screening_type"] == screening_type:
            fail("ERR_DUPLICATE_SCREENING_TYPE",
                 "a %s screening already exists for this recruit" % screening_type)

    row = base_row()
    row.update({
        "recruit_id": recruit["id"],
        "screening_type": screening_type,
        "status": "ORDERED",
        "attempt_number": 1,
        "raw_metrics": None,
        "composite_score": None,
        "disqualifier_codes": [],
        "waiver_justification": None,
        "findings_recorded_by_user_id": None,
        "adjudicated_by_user_id": None,
        "findings_recorded_at": None,
    })
    store.screenings[row["id"]] = row

    if recruit["pipeline_stage"] == "APPLICANT" and not existing:
        recruit["pipeline_stage"] = "SCREENING"
        touch(recruit)
        ops.append_system_entry(
            recruit,
            "STAGE_ENTRY",
            stage_code="SCREENING",
            subject_entity="ScreeningRecord",
            subject_entity_id=row["id"],
            detail="pipeline stage advanced to SCREENING on first screening order",
        )

    return created(serial.screening_json(row))
