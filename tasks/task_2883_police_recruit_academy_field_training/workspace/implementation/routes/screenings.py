"""Screening records: findings and adjudication."""
from flask import Blueprint, g, request

import calc
import ops
import serial
from core import fail, now, store, touch
from routes.common import listing, ok, path_row, require_roles
from validate import body, code_list, opt_str, query_enum, query_str, raw_metrics, req_enum

bp = Blueprint("screenings", __name__)

SCREENING_TYPES = ("BACKGROUND", "MEDICAL", "PSYCHOLOGICAL", "PHYSICAL_FITNESS")
SCREENING_STATUSES = ("ORDERED", "FINDINGS_RECORDED", "RETEST_REQUIRED", "CLEARED",
                      "WAIVED", "DISQUALIFIED")
TERMINAL_SCREENING = ("CLEARED", "WAIVED", "DISQUALIFIED")
READ_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
              "BackgroundInvestigator", "MedicalExaminer")
ACT_ROLES = ("BackgroundInvestigator", "MedicalExaminer", "TrainingCoordinator")

SUBJECT_SCOPE = {
    "BackgroundInvestigator": ("BACKGROUND",),
    "MedicalExaminer": ("MEDICAL", "PSYCHOLOGICAL"),
    "TrainingCoordinator": ("PHYSICAL_FITNESS",),
}


def _subject_scope_or_403(record):
    allowed = SUBJECT_SCOPE.get(g.role, ())
    if record["screening_type"] not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED",
             "role %s does not own %s screenings" % (g.role, record["screening_type"]))


@bp.get("/screening-records/<screening_id>")
def read_screening(screening_id):
    require_roles(*READ_ROLES)
    row = path_row("screenings", screening_id)
    return ok(serial.screening_json(row))


@bp.get("/screening-records")
def list_screenings():
    require_roles(*READ_ROLES)
    recruit_id = query_str("recruit_id")
    screening_type = query_enum("screening_type", SCREENING_TYPES)
    status = query_enum("status", SCREENING_STATUSES)

    def predicate(row):
        if recruit_id is not None and row["recruit_id"] != recruit_id:
            return False
        if screening_type is not None and row["screening_type"] != screening_type:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return listing("screenings", serial.screening_json, predicate)


@bp.post("/screening-records/<screening_id>/findings")
def record_findings(screening_id):
    require_roles(*ACT_ROLES)
    record = path_row("screenings", screening_id)
    _subject_scope_or_403(record)

    payload = body()
    metrics = raw_metrics(payload, record["screening_type"])
    codes = code_list(payload, "disqualifier_codes")

    if record["status"] in TERMINAL_SCREENING:
        fail("ERR_SCREENING_ALREADY_ADJUDICATED", "this screening is already adjudicated")
    if record["status"] not in ("ORDERED", "RETEST_REQUIRED"):
        fail("ERR_INVALID_STATE", "findings are not accepted from %s" % record["status"])

    was_retest = record["status"] == "RETEST_REQUIRED"
    record["status"] = "FINDINGS_RECORDED"
    record["raw_metrics"] = metrics
    record["disqualifier_codes"] = codes
    record["findings_recorded_by_user_id"] = g.user_id
    record["findings_recorded_at"] = now()
    if was_retest:
        record["attempt_number"] = int(record["attempt_number"]) + 1
        record["adjudicated_by_user_id"] = None

    if record["screening_type"] == "PHYSICAL_FITNESS":
        recruit = store.recruits.get(record["recruit_id"])
        standard = calc.standard_for_recruit(recruit) if recruit else None
        if standard is None:
            record["composite_score"] = None
        else:
            composite, _smallest = calc.fitness_composite(
                metrics, recruit["age_bracket"], standard
            )
            record["composite_score"] = composite
    else:
        record["composite_score"] = None

    touch(record)
    return ok(serial.screening_json(record))


@bp.post("/screening-records/<screening_id>/adjudicate")
def adjudicate(screening_id):
    require_roles(*ACT_ROLES)
    record = path_row("screenings", screening_id)
    _subject_scope_or_403(record)

    payload = body()
    decision = req_enum(payload, "decision", ("CLEAR", "WAIVE", "DISQUALIFY", "RETEST"))
    waiver_justification = opt_str(payload, "waiver_justification", min_len=0, max_len=2000)

    if decision == "RETEST" and g.role != "TrainingCoordinator":
        fail("ERR_ROLE_NOT_PERMITTED", "only a TrainingCoordinator may order a retest")

    if record["status"] in TERMINAL_SCREENING:
        fail("ERR_SCREENING_ALREADY_ADJUDICATED", "this screening is already adjudicated")
    if record["status"] != "FINDINGS_RECORDED":
        fail("ERR_INVALID_STATE", "adjudication is legal only from FINDINGS_RECORDED")

    recruit = store.recruits.get(record["recruit_id"])
    standard = calc.standard_for_recruit(recruit) if recruit else None

    # rung 54
    if decision == "CLEAR" and record["disqualifier_codes"]:
        fail("ERR_DISQUALIFIER_UNWAIVED", "a disqualifier is on file and unwaived")
    if decision == "WAIVE":
        if record["screening_type"] == "PHYSICAL_FITNESS":
            fail("ERR_DISQUALIFIER_UNWAIVED", "physical fitness shortfalls are never waivable")
        if waiver_justification is None or waiver_justification.strip() == "":
            fail("ERR_DISQUALIFIER_UNWAIVED", "a waiver requires a justification")

    # rung 55
    if decision == "CLEAR" and record["screening_type"] == "PHYSICAL_FITNESS":
        score = record["composite_score"]
        bar = int(standard["fitness_pass_score"]) if standard is not None else 60
        if score is None or int(score) < bar:
            fail("ERR_FITNESS_STANDARD_NOT_MET", "composite score is below the pass score")

    # rung 56
    if record["findings_recorded_by_user_id"] is not None and \
            g.user_id == record["findings_recorded_by_user_id"]:
        fail("ERR_SAME_ACTOR_ADJUDICATION",
             "the adjudicating user may not be the user who recorded the findings")

    if decision == "RETEST":
        bar = int(standard["fitness_pass_score"]) if standard is not None else 60
        score = record["composite_score"]
        if record["screening_type"] != "PHYSICAL_FITNESS":
            fail("ERR_INVALID_STATE", "a retest is declared for physical fitness only")
        if score is None or int(score) >= bar:
            fail("ERR_INVALID_STATE", "a retest requires a composite below the pass score")

    record["adjudicated_by_user_id"] = g.user_id
    if decision == "CLEAR":
        record["status"] = "CLEARED"
    elif decision == "WAIVE":
        record["status"] = "WAIVED"
        record["waiver_justification"] = waiver_justification
    elif decision == "DISQUALIFY":
        record["status"] = "DISQUALIFIED"
    else:
        record["status"] = "RETEST_REQUIRED"
    touch(record)

    if recruit is not None:
        if decision == "DISQUALIFY":
            recruit["clearance_status"] = "DISQUALIFIED"
        elif decision in ("CLEAR", "WAIVE"):
            recruit["clearance_status"] = calc.derive_clearance_status(recruit)
        touch(recruit)
        if decision != "RETEST":
            ops.append_entry(
                recruit,
                "SCREENING_ADJUDICATION",
                stage_code="SCREENING",
                subject_entity="ScreeningRecord",
                subject_entity_id=record["id"],
                detail="screening adjudicated %s" % decision,
            )

    return ok(serial.screening_json(record))
