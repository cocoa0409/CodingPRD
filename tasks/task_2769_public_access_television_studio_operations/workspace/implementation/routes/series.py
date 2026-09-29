"""Series lineage, seniority and hold plans (PRD 3.2)."""

from flask import Blueprint

import calc
import constants as C
import db
import middleware
import support
import validation
from errors import ApiError, invalid_transition, not_found

bp = Blueprint("series", __name__)

READ_ROLES = (
    C.ROLE_CENTER_ADMIN,
    C.ROLE_SCHEDULING_COORDINATOR,
    C.ROLE_CONTENT_REVIEWER,
    C.ROLE_PRODUCER,
)


@bp.post("/series")
def create_series():
    user_id, role = middleware.authorize(C.ROLE_PRODUCER, C.ROLE_SCHEDULING_COORDINATOR)
    body = validation.body()
    producer_id = validation.req_id(body, "producer_id")
    title = validation.req_string(body, "title")
    cadence = validation.req_enum(body, "cadence", C.SERIES_CADENCES)
    first_air_date = validation.req_datetime(body, "first_air_date")
    predecessor_series_id = validation.opt_id(body, "predecessor_series_id")
    if db.get("producers", producer_id) is None:
        raise not_found("producer", producer_id)
    if predecessor_series_id is not None and db.get("series", predecessor_series_id) is None:
        raise not_found("series", predecessor_series_id)
    middleware.require_owner(producer_id, user_id, role)
    row = db.new_row(
        "series",
        {
            "producer_id": producer_id,
            "title": title,
            "cadence": cadence,
            "first_air_date": first_air_date,
            "predecessor_series_id": predecessor_series_id,
            "sequence_number": db.next_series_sequence(),
            "seniority_at": None,
            "status": "PROPOSED",
            "hold_plan_slots_granted": 0,
            "remaining_hold_slots": 0,
            "missed_windows": 0,
        },
    )
    return support.created("series", row)


@bp.get("/series/<series_id>")
def read_series(series_id):
    middleware.authorize(*READ_ROLES)
    row = support.must_exist("series", series_id)
    return support.single("series", row)


@bp.get("/series")
def list_series():
    middleware.authorize(*READ_ROLES)
    producer_id = validation.query_string("producer_id")
    predecessor_series_id = validation.query_string("predecessor_series_id")
    status = validation.query_enum("status", C.SERIES_STATUSES)
    validation.pagination()
    rows = support.filter_rows(
        "series",
        [
            ("producer_id", producer_id),
            ("predecessor_series_id", predecessor_series_id),
            ("status", status),
        ],
    )
    return support.collection_response("series", rows)


@bp.post("/series/<series_id>/activate")
def activate_series(series_id):
    middleware.authorize(C.ROLE_SCHEDULING_COORDINATOR)
    validation.body()
    row = support.must_exist("series", series_id)
    if row["status"] not in ("PROPOSED", "LAPSED"):
        raise invalid_transition("Only a proposed or lapsed series may be activated")
    producer = db.get("producers", row["producer_id"])
    # priority 10, then the certification gate (PRD 3.2)
    if producer is None or producer["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCER_NOT_ACTIVE", "The owning producer is not active")
    if calc.certification_level(producer) == "NONE":
        raise invalid_transition("An uncertified owner cannot hold airtime priority")
    was_lapsed = row["status"] == "LAPSED"
    row["status"] = "ACTIVE"
    if was_lapsed:
        row["missed_windows"] = 0
        row["remaining_hold_slots"] = row["hold_plan_slots_granted"]
    row["seniority_at"] = calc.series_seniority_at(row)
    db.bump(row)
    return support.single("series", row)


@bp.post("/series/<series_id>/hold-plans")
def replace_hold_plan(series_id):
    middleware.authorize(C.ROLE_SCHEDULING_COORDINATOR)
    body = validation.body()
    expected_series_version = validation.req_int(body, "expected_series_version")
    granted = validation.req_int(body, "hold_plan_slots_granted", minimum=0)
    row = support.must_exist("series", series_id)
    # priority 8 runs before the state check (PRD 2.7 / 3.2)
    if expected_series_version != row["version"]:
        raise ApiError("ERR_STALE_SERIES_VERSION", "The series has advanced since it was read")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_SERIES_NOT_ACTIVE", "A hold plan may only be written on an active series")
    row["hold_plan_slots_granted"] = granted
    row["remaining_hold_slots"] = granted
    db.bump(row)
    return support.single("series", row)
