"""DisseminationActivity endpoints: create, list, complete."""
from flask import Blueprint

import store
from clock import parse_iso
from errors import raise_err
from serialize import activity_out
from services import (activities_of_study, maybe_complete_study,
                      study_has_published_report)
from util import new_entity, ok_list, ok_obj, paginate, sort_created, touch
from validation import (ROLE_PRINCIPAL_INVESTIGATOR, STAFF_ROLES,
                        authenticate, authorize, check_schema, get_json_body)

bp = Blueprint("dissemination", __name__)


@bp.post("/evaluation/studies/<study_id>/dissemination-activities")
def create_activity(study_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    study = store.studies.get(study_id)
    if study is None:
        raise_err("ERR_NOT_FOUND", "Study not found")
    body = get_json_body()
    check_schema(body, {
        "activity_type": ("enum:WEBINAR|TA_SESSION|BRIEF", True),
        "title": ("str", True),
        "scheduled_at": ("dt", True),
        "operator_count": ("int", True),
    })
    if body["operator_count"] < 1:
        raise_err("ERR_INVALID_REQUEST", "operator_count must be >= 1")
    if study["status"] in ("TERMINATED", "COMPLETED"):
        raise_err("ERR_STUDY_INVALID_STATE",
                  "A terminated or completed study accepts no new "
                  "activities")
    if not study_has_published_report(study_id):
        raise_err("ERR_NO_PUBLISHED_REPORT",
                  "The study has no PUBLISHED report yet")
    activity = new_entity({
        "study_id": study_id,
        "activity_type": body["activity_type"],
        "title": body["title"],
        "scheduled_at": parse_iso(body["scheduled_at"]),
        "operator_count": body["operator_count"],
        "status": "PLANNED",
    })
    store.dissemination_activities[activity["id"]] = activity
    return ok_obj(activity_out(activity), 201)


@bp.get("/evaluation/studies/<study_id>/dissemination-activities")
def list_activities(study_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    if study_id not in store.studies:
        raise_err("ERR_NOT_FOUND", "Study not found")
    items = sort_created(activities_of_study(study_id))
    page, limit, offset, total = paginate(items)
    return ok_list([activity_out(a) for a in page], limit, offset, total)


@bp.post("/evaluation/dissemination-activities/<activity_id>/complete")
def complete_activity(activity_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    activity = store.dissemination_activities.get(activity_id)
    if activity is None:
        raise_err("ERR_NOT_FOUND", "Dissemination activity not found")
    body = get_json_body()
    check_schema(body, {})
    if activity["status"] != "PLANNED":
        raise_err("ERR_DISSEMINATION_INVALID_STATE",
                  "Only a PLANNED activity can be completed")
    activity["status"] = "COMPLETED"
    touch(activity)
    study = store.studies.get(activity["study_id"])
    maybe_complete_study(study)
    return ok_obj(activity_out(activity))
