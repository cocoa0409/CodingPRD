"""The testimony calendar."""
from datetime import timedelta

from flask import Blueprint

import serialize
import services as S
from auth import CASE_MANAGER, endpoint
from envelope import object_response
from errors import ApiError
from store import db, new_row, touch
from util import whole_day_floor
from validate import Field, parse

bp = Blueprint("court", __name__)

BUFFER = timedelta(minutes=S.TRAVEL_BUFFER_MINUTES)


def _events_of_analyst(analyst_id):
    return [
        e for e in db.court_events.values() if e["analyst_id"] == analyst_id
    ]


@bp.route("/lab/court-events", methods=["POST"])
@endpoint(CASE_MANAGER)
def create_court_event():
    body = parse([
        Field("examination_request_id", "string", required=True, min_length=1),
        Field("analyst_id", "string", required=True, min_length=1),
        Field("court_name", "string", required=True, min_length=1, max_length=120),
        Field("docket_number", "string", required=True, min_length=1, max_length=40),
        Field("start_utc", "instant", required=True),
        Field("end_utc", "instant", required=True),
        Field("subpoena_received", "boolean", default=False),
    ])
    request_row = S.find_examination_request(body["examination_request_id"])
    analyst = S.find_analyst(body["analyst_id"])
    for existing in _events_of_analyst(analyst["id"]):
        if (existing["status"] != "CANCELLED"
                and existing["docket_number"] == body["docket_number"]):
            raise ApiError("ERR_DUPLICATE_RESOURCE")
    if request_row["status"] != "RELEASED":
        raise ApiError("ERR_EXAM_REQUEST_INVALID_STATE")
    if body["end_utc"] <= body["start_utc"]:
        raise ApiError("ERR_INVALID_INTERVAL")
    if request_row["assigned_analyst_id"] != analyst["id"]:
        raise ApiError("ERR_REFERENTIAL_MISMATCH")
    for existing in _events_of_analyst(analyst["id"]):
        if existing["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        blocked_start = existing["start_utc"] - BUFFER
        blocked_end = existing["end_utc"] + BUFFER
        if body["start_utc"] < blocked_end and blocked_start < body["end_utc"]:
            raise ApiError("ERR_TESTIMONY_SCHEDULE_CONFLICT")
    notice_days = whole_day_floor(db.now(), body["start_utc"])
    if (not body["subpoena_received"]
            and notice_days < S.MIN_TESTIMONY_NOTICE_DAYS):
        raise ApiError("ERR_INSUFFICIENT_TESTIMONY_NOTICE")
    row = new_row()
    row.update({
        "examination_request_id": request_row["id"],
        "analyst_id": analyst["id"],
        "court_name": body["court_name"],
        "docket_number": body["docket_number"],
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "notice_days": notice_days,
        "subpoena_received": body["subpoena_received"],
        "status": "SCHEDULED",
        "testimony_note": None,
        "cancellation_reason": None,
    })
    db.court_events[row["id"]] = row
    return object_response(serialize.court_event(row), 201)


@bp.route("/lab/court-events/<court_event_id>/confirm", methods=["POST"])
@endpoint(CASE_MANAGER)
def confirm_court_event(court_event_id):
    event = S.find_court_event(court_event_id)
    parse([])
    if event["status"] != "SCHEDULED":
        raise ApiError("ERR_COURT_EVENT_INVALID_STATE")
    event["status"] = "CONFIRMED"
    event["subpoena_received"] = True
    touch(event)
    return object_response(serialize.court_event(event), 200)


@bp.route("/lab/court-events/<court_event_id>/complete", methods=["POST"])
@endpoint(CASE_MANAGER)
def complete_court_event(court_event_id):
    event = S.find_court_event(court_event_id)
    body = parse([Field("testimony_note", "string", required=True)])
    if event["status"] != "CONFIRMED":
        raise ApiError("ERR_COURT_EVENT_INVALID_STATE")
    if db.now() < event["end_utc"]:
        raise ApiError("ERR_COURT_EVENT_NOT_ELAPSED")
    event["status"] = "TESTIFIED"
    event["testimony_note"] = body["testimony_note"]
    touch(event)
    return object_response(serialize.court_event(event), 200)


@bp.route("/lab/court-events/<court_event_id>/cancel", methods=["POST"])
@endpoint(CASE_MANAGER)
def cancel_court_event(court_event_id):
    event = S.find_court_event(court_event_id)
    body = parse([Field("cancellation_reason", "string", required=True)])
    if event["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_COURT_EVENT_INVALID_STATE")
    event["status"] = "CANCELLED"
    event["cancellation_reason"] = body["cancellation_reason"]
    touch(event)
    return object_response(serialize.court_event(event), 200)
