"""Support records (coaching / evaluation) and the logical clock capability."""

from flask import Blueprint

import serialize
import services
import validation
from envelope import ok, read_json, require_auth
from errors import ApiError
from store import MEMBERS, SUPPORT_RECORDS, set_clock, stamp
from util import iso

bp = Blueprint("misc", __name__)


@bp.route("/corps/support-records", methods=["POST"])
def create_support_record():
    require_auth(["Coach"])
    body = read_json()
    validation.require(
        body,
        "corps_member_id",
        "record_type",
        "coach_user_id",
        "session_start",
        "session_end",
        "effectiveness_score",
    )
    corps_member_id = validation.string(body, "corps_member_id")
    record_type = validation.enum(body, "record_type", validation.RECORD_TYPES)
    coach_user_id = validation.string(body, "coach_user_id")
    session_start = validation.timestamp(body, "session_start")
    session_end = validation.timestamp(body, "session_end")
    effectiveness_score = validation.integer(body, "effectiveness_score", minimum=1, maximum=5)
    notes = body.get("notes")

    if corps_member_id not in MEMBERS:
        raise ApiError("ERR_MEMBER_NOT_FOUND")

    start_iso = iso(session_start)
    end_iso = iso(session_end)
    if record_type == "COACHING":
        for existing in SUPPORT_RECORDS.values():
            if existing["record_type"] != "COACHING":
                continue
            if existing["coach_user_id"] != coach_user_id:
                continue
            # Half-open intervals [session_start, session_end): a session that
            # begins exactly when another ends does not conflict.
            if existing["session_start"] < end_iso and start_iso < existing["session_end"]:
                raise ApiError("ERR_COACH_SCHEDULE_OVERLAP")

    record = {
        "corps_member_id": corps_member_id,
        "record_type": record_type,
        "coach_user_id": coach_user_id,
        "session_start": start_iso,
        "session_end": end_iso,
        "effectiveness_score": effectiveness_score,
        "notes": notes,
    }
    stamp(record)
    SUPPORT_RECORDS[record["id"]] = record
    return ok(serialize.support_record(record), 201)


@bp.route("/corps/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    # The clock-setting capability is the sole operation exempt from the header
    # check; the role check still applies.
    require_auth(["PlatformAdmin"], skip_header_check=True)
    body = read_json()
    to_iso8601 = validation.timestamp(body, "to_iso8601")
    set_clock(to_iso8601)
    services.settle_clock_effects()
    return ok({}, 200, response_type="object")
