"""Academy classes (cohorts), certification runs and the two reports."""
from flask import Blueprint, request

import calc
import ops
import serial
from core import base_row, d2, fail, num, store, touch
from routes.common import (
    body_fk,
    created,
    listing,
    ok,
    path_row,
    require_roles,
    unique_or_conflict,
)
from validate import body, query_enum, query_int, req_date, req_int, req_str

bp = Blueprint("classes", __name__)

CLASS_STATUSES = ("FORMING", "IN_SESSION", "AT_RISK", "GRADUATED")
READ_ONE_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
                  "AcademyInstructor", "FieldTrainingOfficer")
LIST_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian")


@bp.post("/academy-classes")
def create_class():
    require_roles("AcademyDirector")
    payload = body()
    standard = body_fk(payload, "certification_standard_id", "standards")
    standard_id = req_str(payload, "certification_standard_id", min_len=1, max_len=200)
    class_code = req_str(payload, "class_code", min_len=1, max_len=24)
    start_date = req_date(payload, "start_date")
    planned_seats = req_int(payload, "planned_seats", minimum=1)
    if standard is None:
        fail("ERR_CERTIFICATION_STANDARD_NOT_FOUND", "certification standard does not exist")

    unique_or_conflict("classes", "class_code", class_code)

    row = base_row()
    row.update({
        "certification_standard_id": standard_id,
        "class_code": class_code,
        "start_date": start_date,
        "planned_seats": planned_seats,
        "status": "FORMING",
    })
    store.classes[row["id"]] = row
    return created(serial.class_json(row))


@bp.get("/academy-classes/<class_id>")
def read_class(class_id):
    require_roles(*READ_ONE_ROLES)
    row = path_row("classes", class_id)
    return ok(serial.class_json(row))


@bp.get("/academy-classes")
def list_classes():
    require_roles(*LIST_ROLES)
    standard_id = request.args.get("certification_standard_id")
    status = query_enum("status", CLASS_STATUSES)

    def predicate(row):
        if standard_id is not None and row["certification_standard_id"] != standard_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return listing("classes", serial.class_json, predicate)


SKIP_ORDER = ("PROBATION_NOT_PASSED", "HOURS_SHORTFALL", "TOPIC_SHORTFALL", "EXAM_NOT_PASSED")


def _skip_reason(recruit, standard):
    if recruit["pipeline_stage"] != "PROBATION" or recruit["probation_status"] != "PASSED":
        return "PROBATION_NOT_PASSED"
    if standard is None:
        return "HOURS_SHORTFALL"
    if calc.recruit_total_hours(recruit, "ATTENDED") < d2(standard["min_total_hours"]):
        return "HOURS_SHORTFALL"
    if not calc.topics_satisfied(recruit, standard):
        return "TOPIC_SHORTFALL"
    if not calc.exams_all_passed(recruit, standard):
        return "EXAM_NOT_PASSED"
    return None


@bp.post("/academy-classes/<class_id>/certify-graduates")
def certify_graduates(class_id):
    require_roles("AcademyDirector")
    cls = path_row("classes", class_id)
    if cls["status"] not in ("IN_SESSION", "AT_RISK"):
        fail("ERR_INVALID_STATE", "cohort is not open for certification")
    standard = calc.standard_for_class(cls)

    certified_ids = []
    skipped = []
    for recruit in calc.class_recruits(cls["id"]):
        reason = _skip_reason(recruit, standard)
        if reason is not None:
            skipped.append({"recruit_id": recruit["id"], "reason_code": reason})
            continue
        recruit["pipeline_stage"] = "CERTIFIED"
        touch(recruit)
        ops.append_entry(
            recruit,
            "CERTIFICATION_ISSUED",
            stage_code="PROBATION",
            subject_entity="Recruit",
            subject_entity_id=recruit["id"],
            detail="certification issued on cohort certification run",
        )
        certified_ids.append(recruit["id"])

    touch(cls)
    if certified_ids:
        cls["status"] = "GRADUATED"

    return ok({
        "academy_class_id": cls["id"],
        "class_status": cls["status"],
        "certified_count": len(certified_ids),
        "certified_recruit_ids": certified_ids,
        "skipped": skipped,
    })


@bp.get("/academy-classes/<class_id>/attrition-analysis")
def attrition_analysis(class_id):
    require_roles("AcademyDirector", "RecordsCustodian", "TrainingCoordinator")
    cls = path_row("classes", class_id)
    report = calc.attrition_analysis(cls)
    return ok({
        "academy_class_id": report["academy_class_id"],
        "stages": [
            {
                "stage_code": stage["stage_code"],
                "entered": stage["entered"],
                "adverse_exits": stage["adverse_exits"],
                "voluntary_exits": stage["voluntary_exits"],
                "attrition_rate": num(stage["attrition_rate"]),
            }
            for stage in report["stages"]
        ],
        "survival_to_certification": num(report["survival_to_certification"]),
        "voluntary_exits_total": report["voluntary_exits_total"],
        "rolling_mean_scores": dict(
            (key, num(value)) for key, value in report["rolling_mean_scores"].items()
        ),
    })


@bp.get("/academy-classes/<class_id>/pipeline-forecast")
def pipeline_forecast(class_id):
    require_roles("AcademyDirector", "RecordsCustodian")
    cls = path_row("classes", class_id)
    target = query_int("target_sworn_officers", minimum=0, required=True)
    report = calc.pipeline_forecast(cls, target)
    return ok({
        "academy_class_id": report["academy_class_id"],
        "target_sworn_officers": report["target_sworn_officers"],
        "survival_to_certification": num(report["survival_to_certification"]),
        "required_applicants": report["required_applicants"],
        "per_stage_expected": dict(report["per_stage_expected"]),
    })
