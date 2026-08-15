"""Commission meetings (PRD 3.4)."""
from flask import Blueprint

from middleware import get_caller, check_role_allowed
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import new_record
from util import fmt_dt
from validate import get_body, req_str, req_int, req_datetime

bp = Blueprint("meetings", __name__, url_prefix="/preservation")


@bp.post("/meetings")
def create_meeting():
    caller = get_caller()
    body = get_body()
    meeting_date = req_datetime(body, "meeting_date")
    location = req_str(body, "location")
    agenda_capacity = req_int(body, "agenda_capacity", minimum=0)
    check_role_allowed(caller, ["PreservationStaff"])
    rec = new_record("meetings", {
        "meeting_date": fmt_dt(meeting_date),
        "location": location,
        "agenda_capacity": agenda_capacity,
        "scheduled_hearing_count": 0,
    })
    return success_object(public(rec), status=201)


@bp.get("/meetings")
def list_meetings():
    return list_response("meetings")


@bp.get("/meetings/<rid>")
def get_meeting(rid):
    return get_one("meetings", rid)
