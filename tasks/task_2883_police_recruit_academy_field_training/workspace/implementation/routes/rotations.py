"""Field training rotations, daily observation reports and cascade B."""
from flask import Blueprint, g

import calc
import ops
import serial
from core import base_row, fail, store, today, touch
from routes.common import (
    body_fk,
    check_recruit_not_terminal,
    created,
    listing,
    ok,
    path_row,
    require_roles,
)
from validate import (
    body,
    check_date_interval,
    dimension_ratings,
    opt_bool,
    query_bool,
    query_enum,
    query_str,
    req_date,
    req_int,
    req_str,
)

bp = Blueprint("rotations", __name__)

ROTATION_STATUSES = ("PLANNED", "ACTIVE", "REMEDIAL", "COMPLETED", "ABORTED")
LIVE_ROTATION_STATUSES = ("PLANNED", "ACTIVE", "REMEDIAL")
NON_ABORTED_STATUSES = ("PLANNED", "ACTIVE", "REMEDIAL", "COMPLETED")
ROTATION_READ_ONE = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
                     "FieldTrainingOfficer", "Recruit")
ROTATION_LIST = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
                 "FieldTrainingOfficer")
REPORT_READ_ONE = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
                   "FieldTrainingOfficer", "Recruit")
REPORT_LIST = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
               "FieldTrainingOfficer")
FTO_LOAD_CEILING = 2


def _intersects(start_a, end_a, start_b, end_b):
    """Closed date intervals: adjacency counts as intersection (§2.11)."""
    return not (end_a < start_b or end_b < start_a)


def _check_fto_certified(instructor):
    """Rung 57."""
    if (instructor is None
            or instructor["certification_status"] != "CERTIFIED"
            or not instructor["fto_certified"]):
        fail("ERR_FTO_NOT_CERTIFIED",
             "the assigned officer is not a certified field training officer")


@bp.post("/field-training-rotations")
def create_rotation():
    require_roles("TrainingCoordinator")
    payload = body()
    recruit = body_fk(payload, "recruit_id", "recruits")
    instructor = body_fk(payload, "fto_instructor_id", "instructors")
    prior = body_fk(payload, "prior_rotation_id", "rotations")

    recruit_id = req_str(payload, "recruit_id", min_len=1)
    fto_instructor_id = req_str(payload, "fto_instructor_id", min_len=1)
    phase_number = req_int(payload, "phase_number", minimum=1, maximum=4)
    start_date = req_date(payload, "start_date")
    end_date = req_date(payload, "end_date")
    expected_version = req_int(payload, "expected_recruit_version")
    prior_rotation_id = payload.get("prior_rotation_id")
    if prior_rotation_id is not None and not isinstance(prior_rotation_id, str):
        fail("ERR_INVALID_REQUEST", "prior_rotation_id must be a string or null")

    check_date_interval(start_date, end_date)

    if expected_version != recruit["version"]:
        fail("ERR_STALE_RECRUIT_VERSION",
             "expected_recruit_version does not match the recruit's version")

    check_recruit_not_terminal(recruit)
    _check_fto_certified(instructor)

    siblings = calc.recruit_rotations(recruit_id)
    for other in siblings:
        if other["status"] == "ABORTED":
            continue
        if _intersects(start_date, end_date, other["start_date"], other["end_date"]):
            fail("ERR_ROTATION_DATE_OVERLAP",
                 "the candidate interval intersects another live rotation")

    for other in siblings:
        if other["status"] == "ABORTED":
            continue
        if other["fto_instructor_id"] == fto_instructor_id:
            fail("ERR_TRAINER_ROTATION_VIOLATION",
                 "this officer has already trained this recruit")

    if phase_number > 1:
        if prior is None:
            fail("ERR_PRIOR_ROTATION_MISMATCH",
                 "prior_rotation_id is required beyond the first phase")
        if (prior["recruit_id"] != recruit_id
                or prior["phase_number"] != phase_number - 1
                or prior["status"] != "COMPLETED"):
            fail("ERR_PRIOR_ROTATION_MISMATCH",
                 "prior_rotation_id does not name the coherent predecessor")
    elif prior is not None:
        if (prior["recruit_id"] != recruit_id
                or prior["phase_number"] != phase_number - 1
                or prior["status"] != "COMPLETED"):
            fail("ERR_PRIOR_ROTATION_MISMATCH",
                 "prior_rotation_id does not name the coherent predecessor")

    load = 0
    for other in calc.instructor_rotations(fto_instructor_id):
        if other["status"] not in LIVE_ROTATION_STATUSES:
            continue
        if _intersects(start_date, end_date, other["start_date"], other["end_date"]):
            load += 1
    if load >= FTO_LOAD_CEILING:
        fail("ERR_FTO_LOAD_EXCEEDED",
             "the officer already holds the maximum concurrent trainee load")

    for other in siblings:
        if other["status"] != "ABORTED" and other["phase_number"] == phase_number:
            fail("ERR_INVALID_STATE",
                 "phase %d already exists for this recruit" % phase_number)

    row = base_row()
    row.update({
        "recruit_id": recruit_id,
        "fto_instructor_id": fto_instructor_id,
        "prior_rotation_id": prior_rotation_id,
        "phase_number": phase_number,
        "start_date": start_date,
        "end_date": end_date,
        "status": "PLANNED",
        "final_narrative": None,
        "abort_reason": None,
    })
    store.rotations[row["id"]] = row
    touch(recruit)
    return created(serial.rotation_json(row))


@bp.get("/field-training-rotations/<rotation_id>")
def read_rotation(rotation_id):
    require_roles(*ROTATION_READ_ONE)
    row = path_row("rotations", rotation_id)
    return ok(serial.rotation_json(row))


@bp.get("/field-training-rotations")
def list_rotations():
    require_roles(*ROTATION_LIST)
    recruit_id = query_str("recruit_id")
    fto_instructor_id = query_str("fto_instructor_id")
    prior_rotation_id = query_str("prior_rotation_id")
    status = query_enum("status", ROTATION_STATUSES)

    def predicate(row):
        if recruit_id is not None and row["recruit_id"] != recruit_id:
            return False
        if fto_instructor_id is not None and row["fto_instructor_id"] != fto_instructor_id:
            return False
        if prior_rotation_id is not None and row["prior_rotation_id"] != prior_rotation_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return listing("rotations", serial.rotation_json, predicate)


@bp.post("/field-training-rotations/<rotation_id>/activate")
def activate_rotation(rotation_id):
    require_roles("TrainingCoordinator")
    rotation = path_row("rotations", rotation_id)

    if rotation["status"] != "PLANNED":
        fail("ERR_INVALID_STATE",
             "activation is not declared from %s" % rotation["status"])

    instructor = store.instructors.get(rotation["fto_instructor_id"])
    _check_fto_certified(instructor)

    recruit = store.recruits.get(rotation["recruit_id"])
    if recruit is None or recruit["pipeline_stage"] not in ("FIELD_TRAINING", "PROBATION"):
        fail("ERR_INVALID_STATE", "the trainee is not in field training")
    for other in calc.recruit_rotations(recruit["id"]):
        if other["id"] != rotation["id"] and other["status"] in ("ACTIVE", "REMEDIAL"):
            fail("ERR_INVALID_STATE",
                 "another rotation of this trainee is already in service")

    rotation["status"] = "ACTIVE"
    touch(rotation)
    touch(instructor)
    return ok(serial.rotation_json(rotation))


@bp.post("/field-training-rotations/<rotation_id>/complete")
def complete_rotation(rotation_id):
    require_roles("FieldTrainingOfficer", "TrainingCoordinator")
    rotation = path_row("rotations", rotation_id)
    payload = body()
    final_narrative = req_str(payload, "final_narrative", min_len=1, max_len=2000)

    if rotation["status"] not in ("ACTIVE", "REMEDIAL"):
        fail("ERR_ROTATION_NOT_ACTIVE",
             "a rotation at %s cannot be completed" % rotation["status"])
    if calc.rotation_dor_count(rotation) < 1:
        fail("ERR_INVALID_STATE",
             "completion requires at least one non-voided observation report")
    if today() < rotation["end_date"]:
        fail("ERR_INVALID_STATE", "the rotation window has not closed yet")

    rotation["status"] = "COMPLETED"
    rotation["final_narrative"] = final_narrative
    touch(rotation)

    instructor = store.instructors.get(rotation["fto_instructor_id"])
    if instructor is not None:
        touch(instructor)

    recruit = store.recruits.get(rotation["recruit_id"])
    if recruit is not None and recruit["probation_start"] is not None:
        ops.rederive_probation(recruit)
    return ok(serial.rotation_json(rotation))


@bp.post("/field-training-rotations/<rotation_id>/abort")
def abort_rotation_route(rotation_id):
    require_roles("AcademyDirector", "TrainingCoordinator")
    rotation = path_row("rotations", rotation_id)
    payload = body()
    reason = req_str(payload, "reason", min_len=1, max_len=2000)

    if rotation["status"] not in LIVE_ROTATION_STATUSES:
        fail("ERR_INVALID_STATE",
             "a rotation at %s cannot be aborted" % rotation["status"])

    ops.abort_rotation(rotation, reason)
    recruit = store.recruits.get(rotation["recruit_id"])
    if recruit is not None:
        ops.restore_probation_after_abort(recruit)
    return ok(serial.rotation_json(rotation))


@bp.post("/field-training-rotations/<rotation_id>/observation-reports")
def file_report(rotation_id):
    require_roles("FieldTrainingOfficer")
    rotation = path_row("rotations", rotation_id)
    if g.user_id != rotation["fto_instructor_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "the acting officer is not assigned to this rotation")

    payload = body()
    author = body_fk(payload, "author_instructor_id", "instructors")
    author_instructor_id = req_str(payload, "author_instructor_id", min_len=1)
    observed_on = req_date(payload, "observed_on")
    ratings = dimension_ratings(payload)
    narrative = req_str(payload, "narrative", min_len=1, max_len=2000)
    not_responding = opt_bool(payload, "not_responding_to_training", default=False)

    if rotation["status"] not in ("ACTIVE", "REMEDIAL"):
        fail("ERR_ROTATION_NOT_ACTIVE",
             "a report cannot be filed against a rotation at %s" % rotation["status"])

    if (observed_on < rotation["start_date"]
            or observed_on > rotation["end_date"]
            or observed_on > today()):
        fail("ERR_DOR_OUTSIDE_ROTATION_WINDOW",
             "observed_on falls outside the rotation window")

    if author_instructor_id != rotation["fto_instructor_id"]:
        fail("ERR_DOR_AUTHOR_NOT_ASSIGNED_FTO",
             "the author is not the officer assigned to this rotation")

    for other in calc.rotation_reports(rotation["id"]):
        if other["observed_on"] == observed_on:
            fail("ERR_DUPLICATE_DOR",
                 "a report already exists for this rotation and date")

    row = base_row()
    row.update({
        "field_training_rotation_id": rotation["id"],
        "author_instructor_id": author_instructor_id,
        "observed_on": observed_on,
        "dimension_ratings": ratings,
        "not_responding_to_training": not_responding,
        "narrative": narrative,
        "dor_mean": calc.dor_mean(ratings),
        "voided": False,
    })
    store.reports[row["id"]] = row

    recruit = store.recruits.get(rotation["recruit_id"])
    if recruit is not None:
        ops.append_entry(
            recruit,
            "DOR_FILED",
            stage_code="FIELD_TRAINING",
            subject_entity="ObservationReport",
            subject_entity_id=row["id"],
            detail="daily observation report filed",
        )
        ops.cascade_b(rotation, recruit)
    else:
        touch(rotation)
    return created(serial.report_json(row))


@bp.get("/observation-reports/<observation_report_id>")
def read_report(observation_report_id):
    require_roles(*REPORT_READ_ONE)
    row = path_row("reports", observation_report_id)
    return ok(serial.report_json(row))


@bp.get("/observation-reports")
def list_reports():
    require_roles(*REPORT_LIST)
    rotation_id = query_str("field_training_rotation_id")
    author_instructor_id = query_str("author_instructor_id")
    voided = query_bool("voided")

    def predicate(row):
        if rotation_id is not None and row["field_training_rotation_id"] != rotation_id:
            return False
        if author_instructor_id is not None and row["author_instructor_id"] != author_instructor_id:
            return False
        if voided is not None and row["voided"] != voided:
            return False
        return True

    return listing("reports", serial.report_json, predicate)
