"""DisciplineIncident endpoints: report, list, get, approve, void."""
from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.calc import (district_of_year, get_published_spec,
                           recompute_enrollment, severity_score)
from services.serializers import incident_out
from validators import body, req_dt, req_enum, req_int, req_str

bp = Blueprint("incidents", __name__)

ACTION_TYPES = {"NONE", "ISS", "OSS", "EXPULSION"}


def _get_incident_or_404(iid):
    i = store["incidents"].get(iid)
    if not i:
        raise ApiError("ERR_INCIDENT_NOT_FOUND", 404,
                       "No discipline incident with the given id")
    return i


@bp.post("/sis/discipline-incidents")
def create_incident():
    _uid, role = auth_context()
    data = body()
    student_id = req_str(data, "student_id")
    enrollment_id = req_str(data, "enrollment_id")
    incident_date = req_dt(data, "incident_date")
    raw_offense_code = req_str(data, "raw_offense_code")
    action_type = req_enum(data, "action_type", ACTION_TYPES)
    action_days = req_int(data, "action_days")
    # action_days must be exactly 0 for NONE, strictly positive otherwise.
    if action_type == "NONE":
        if action_days != 0:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "action_days must be 0 when action_type is NONE")
    elif action_days <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "action_days must be > 0 for a real disciplinary action")
    require_role(role, {"Registrar"})
    student = store["students"].get(student_id)
    if not student:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "student_id does not reference an existing student")
    e = store["enrollments"].get(enrollment_id)
    if not e:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "enrollment_id does not reference an existing enrollment")
    year = store["school_years"][e["school_year_id"]]
    if student["district_id"] != year["district_id"]:
        raise ApiError("ERR_DISTRICT_MISMATCH", 422,
                       "incident booked against an enrollment of a different district's student")
    if not (year["start_date"] <= incident_date < year["end_date"]):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422,
                       "incident_date must lie inside the enrollment's school-year window")
    district = district_of_year(year)
    spec = get_published_spec(district["state_code"]) if district else None
    if not spec:
        raise ApiError("ERR_SPEC_NOT_PUBLISHED", 409,
                       "No PUBLISHED spec for the district's state")
    mapping = spec["discipline_code_map"].get(raw_offense_code)
    if mapping is None:
        raise ApiError("ERR_UNMAPPED_DISCIPLINE_CODE", 422,
                       "raw_offense_code absent from the PUBLISHED spec discipline_code_map")
    base = mapping.get("severity_base")
    inc = {"id": new_id(), "student_id": student_id,
           "enrollment_id": enrollment_id, "incident_date": incident_date,
           "raw_offense_code": raw_offense_code, "action_type": action_type,
           "action_days": action_days,
           "state_offense_code": mapping.get("state_offense_code"),
           "severity_base": base,
           "severity_score": severity_score(base, action_days, action_type),
           "status": "REPORTED"}
    stamp_new(inc)
    store["incidents"][inc["id"]] = inc
    return ok_obj(incident_out(inc), 201)


@bp.get("/sis/discipline-incidents")
def list_incidents():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    student_id = request.args.get("student_id")
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    items = [i for i in store["incidents"].values()
             if (student_id is None or i["student_id"] == student_id)
             and (enrollment_id is None or i["enrollment_id"] == enrollment_id)
             and (status is None or i["status"] == status)]
    items.sort(key=lambda i: (i["created_at"], i["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([incident_out(i) for i in page], total, limit, offset)


@bp.get("/sis/discipline-incidents/<iid>")
def get_incident(iid):
    _uid, role = auth_context()
    require_role(role, READERS)
    return ok_obj(incident_out(_get_incident_or_404(iid)))


@bp.post("/sis/discipline-incidents/<iid>/approve")
def approve_incident(iid):
    _uid, role = auth_context()
    require_role(role, {"Registrar"})
    inc = _get_incident_or_404(iid)
    if inc["status"] != "REPORTED":
        raise ApiError("ERR_INCIDENT_NOT_REPORTED", 409,
                       "Approve requires incident REPORTED")
    inc["status"] = "APPROVED"
    touch(inc)
    # OSS approval cascades full action_days weight into the enrollment.
    if inc["action_type"] == "OSS":
        e = store["enrollments"].get(inc["enrollment_id"])
        if e:
            recompute_enrollment(e)
            touch(e)
    return ok_obj(incident_out(inc))


@bp.post("/sis/discipline-incidents/<iid>/void")
def void_incident(iid):
    _uid, role = auth_context()
    require_role(role, {"Registrar"})
    inc = _get_incident_or_404(iid)
    if inc["status"] not in ("REPORTED", "APPROVED"):
        raise ApiError("ERR_INCIDENT_ALREADY_VOIDED", 409,
                       "Incident already VOIDED; no further transitions")
    compensate_oss = (inc["status"] == "APPROVED"
                      and inc["action_type"] == "OSS")
    inc["status"] = "VOIDED"
    touch(inc)
    # Compensation: voiding an APPROVED OSS incident reverses the cascade.
    if compensate_oss:
        e = store["enrollments"].get(inc["enrollment_id"])
        if e:
            recompute_enrollment(e)
            touch(e)
    return ok_obj(incident_out(inc))
