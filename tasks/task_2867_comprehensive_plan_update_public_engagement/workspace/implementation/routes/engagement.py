"""Venues, engagement activities and weighted participation (PRD 3.6)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import constants as K
import serial
import validation as V
from db import bump, clock_now, db, dec, new_row, sort_rows
from errors import ApiError
from response import (actor, authenticate, created, filter_param, ok, paginate,
                      pagination)
from services import calc, planservice, repo

bp = Blueprint("engagement", __name__)

_READERS = K.ALL_ROLES


@bp.post("/planning/venues")
def create_venue():
    authenticate([K.ROLE_STAFF])
    data = V.body()
    name = V.get_str(data, "name", 1, 120)
    capacity = V.get_int(data, "seated_capacity", 1)
    buffer_minutes = V.get_int(data, "turnover_buffer_minutes", 0, 240,
                               required=False, default=0)
    ada = V.get_bool(data, "ada_accessible", default=True)
    transit = V.get_bool(data, "transit_served", default=False)
    row = new_row({
        "name": name,
        "seated_capacity": capacity,
        "turnover_buffer_minutes": buffer_minutes,
        "ada_accessible": ada,
        "transit_served": transit,
    }, versioned=False)
    db.venues[row["id"]] = row
    return created(serial.venue(row))


@bp.post("/planning/engagement-activities")
def create_activity():
    authenticate([K.ROLE_STAFF])
    data = V.body()
    plan_id = V.get_str(data, "plan_update_id", 1, None)
    activity_type = V.get_enum(data, "activity_type", K.ACTIVITY_TYPES)
    title = V.get_str(data, "title", 1, 160)
    start_at = V.get_instant(data, "start_at")
    end_at = V.get_instant(data, "end_at")
    interpretation = V.get_bool(data, "interpretation_offered", default=False)
    venue_id = V.get_str(data, "venue_id", 1, None, required=False)
    if end_at <= start_at:
        V.bad("end_at must be strictly after start_at.")
    needs_venue = activity_type in ("WORKSHOP", "TARGETED_OUTREACH")
    if needs_venue and venue_id is None:
        V.bad("venue_id is required for a workshop or targeted-outreach "
              "activity.")
    if not needs_venue and venue_id is not None:
        V.bad("venue_id must not be supplied for a survey.")

    plan = repo.plan(plan_id)
    venue = repo.venue(venue_id) if venue_id is not None else None
    planservice.ensure_not_adopted(plan)

    if venue is not None:
        buffer_minutes = timedelta(minutes=int(venue["turnover_buffer_minutes"]))
        for other in db.engagement_activities.values():
            if other["venue_id"] != venue["id"]:
                continue
            if other["status"] not in ("SCHEDULED", "COMPLETED"):
                continue
            if (start_at - buffer_minutes) < other["end_at"] and \
                    (end_at + buffer_minutes) > other["start_at"]:
                raise ApiError("ERR_VENUE_TIME_CONFLICT")
        if activity_type == "TARGETED_OUTREACH":
            if not (venue["transit_served"] and venue["ada_accessible"]):
                raise ApiError("ERR_VENUE_NOT_EQUITY_ELIGIBLE")

    row = new_row({
        "plan_update_id": plan["id"],
        "venue_id": venue["id"] if venue is not None else None,
        "activity_type": activity_type,
        "title": title,
        "start_at": start_at,
        "end_at": end_at,
        "interpretation_offered": interpretation,
        "status": "SCHEDULED",
        "record_count": 0,
        "underrepresented_record_count": 0,
        "weighting_variant": ("OUTREACH_WEIGHTED"
                              if activity_type == "TARGETED_OUTREACH"
                              else "STANDARD"),
        "total_weighted_count": Decimal("0.0"),
        "underrepresented_weighted_count": Decimal("0.0"),
        "equity_share_pct": Decimal("0.0"),
    })
    db.engagement_activities[row["id"]] = row
    return created(serial.activity(row))


@bp.get("/planning/engagement-activities/<row_id>")
def read_activity(row_id):
    authenticate(_READERS)
    return ok(serial.activity(repo.activity(row_id)))


@bp.get("/planning/engagement-activities")
def list_activities():
    authenticate(_READERS)
    limit, offset = pagination()
    plan_id = filter_param("plan_update_id")
    venue_id = filter_param("venue_id")
    activity_type = filter_param("activity_type")
    status = filter_param("status")
    rows = sort_rows(list(db.engagement_activities.values()))
    if plan_id is not None:
        rows = [r for r in rows if r["plan_update_id"] == plan_id]
    if venue_id is not None:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    if activity_type is not None:
        rows = [r for r in rows if r["activity_type"] == activity_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, serial.activity)


@bp.post("/planning/engagement-activities/<row_id>/complete")
def complete_activity(row_id):
    authenticate([K.ROLE_STAFF])
    row = repo.activity(row_id)
    plan = repo.plan(row["plan_update_id"])
    planservice.ensure_not_adopted(plan)
    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_ACTIVITY_NOT_SCHEDULED")
    if clock_now() < row["end_at"]:
        raise ApiError("ERR_ACTIVITY_NOT_ENDED")
    if int(row["record_count"]) < 1:
        raise ApiError("ERR_NO_PARTICIPATION_RECORDS")

    row["equity_share_pct"] = calc.equity_share(
        row["underrepresented_weighted_count"], row["total_weighted_count"])
    row["status"] = "COMPLETED"
    bump(row)
    planservice.refresh(plan)
    bump(plan)
    return ok(serial.activity(row))


@bp.post("/planning/engagement-activities/<row_id>/cancel")
def cancel_activity(row_id):
    authenticate([K.ROLE_STAFF])
    row = repo.activity(row_id)
    data = V.body()
    V.get_str(data, "cancellation_reason", 1, 2000, required=False,
              non_blank=False)
    plan = repo.plan(row["plan_update_id"])
    if row["status"] == "CANCELLED":
        raise ApiError("ERR_ACTIVITY_CLOSED")
    was_completed = row["status"] == "COMPLETED"
    if was_completed:
        planservice.ensure_not_adopted(plan)

    row["status"] = "CANCELLED"
    bump(row)
    if was_completed:
        # Compensation: the plan's weighted totals are recomputed from the
        # remaining COMPLETED activities, which conserves them exactly.
        planservice.refresh(plan)
        bump(plan)
    return ok(serial.activity(row))


# --- participation records --------------------------------------------------

@bp.post("/planning/participation-records")
def create_record():
    authenticate([K.ROLE_STAFF])
    data = V.body()
    activity_id = V.get_str(data, "activity_id", 1, None)
    respondent_ref = V.get_str(data, "respondent_ref", 1, 64)
    group = V.get_enum(data, "demographic_group", K.DEMOGRAPHIC_GROUPS)
    census_tract = V.get_str(data, "census_tract", 4, 12)
    interpreter_used = V.get_bool(data, "interpreter_used", default=False)
    comment_text = V.get_str(data, "comment_text", 1, 4000, required=False,
                             non_blank=False)

    activity = repo.activity(activity_id)
    plan = db.plan_updates.get(activity["plan_update_id"])
    if plan is not None:
        planservice.ensure_not_adopted(plan)
    if activity["status"] != "SCHEDULED":
        raise ApiError("ERR_ACTIVITY_NOT_SCHEDULED")
    for existing in repo.records_of(activity["id"]):
        if existing["respondent_ref"] == respondent_ref:
            raise ApiError("ERR_DUPLICATE_PARTICIPATION")

    underrepresented = calc.is_underrepresented(group)
    weight = calc.record_weight(activity["weighting_variant"], interpreter_used)
    row = new_row({
        "activity_id": activity["id"],
        "respondent_ref": respondent_ref,
        "demographic_group": group,
        "interpreter_used": interpreter_used,
        "census_tract": census_tract,
        "comment_text": comment_text,
        "is_underrepresented": underrepresented,
        "weight": weight,
    }, versioned=False)
    db.participation_records[row["id"]] = row

    activity["record_count"] = int(activity["record_count"]) + 1
    activity["total_weighted_count"] = calc.weight_sum(
        [activity["total_weighted_count"], weight])
    if underrepresented:
        activity["underrepresented_record_count"] = \
            int(activity["underrepresented_record_count"]) + 1
        activity["underrepresented_weighted_count"] = calc.weight_sum(
            [activity["underrepresented_weighted_count"], weight])
    else:
        activity["underrepresented_weighted_count"] = calc.weight_sum(
            [activity["underrepresented_weighted_count"]])
    bump(activity)
    return created(serial.participation(row))


@bp.get("/planning/engagement-activities/<row_id>/participation-records")
def list_records(row_id):
    authenticate(_READERS)
    activity = repo.activity(row_id)
    limit, offset = pagination()
    group = filter_param("demographic_group")
    rows = repo.records_of(activity["id"])
    if group is not None:
        rows = [r for r in rows if r["demographic_group"] == group]
    return paginate(rows, limit, offset, serial.participation)


_ = (actor, dec)
