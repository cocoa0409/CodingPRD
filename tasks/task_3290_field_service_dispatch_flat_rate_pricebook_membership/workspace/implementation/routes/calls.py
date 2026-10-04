"""Call records and the coaching pipeline (PRD 3.13)."""

from flask import Blueprint, request

from constants import (ROLE_CUSTOMER_SERVICE, ROLE_MANAGER,
                       COACHING_STATUSES)
from common import (body_json, require_roles, require_str, require_int,
                    optional_str, optional_datetime, optional_int,
                    enum_field)
from constants import clock
import store
import serializers
import calc
from errors import (ApiError, not_found, invalid_request, ERR_INVALID_STATE,
                    ERR_CALL_NOT_REVIEWABLE)
from response import created, object_ok, array_ok, read_pagination, paginate

bp = Blueprint("calls", __name__)

ASSIGN_DECISIONS = {"ASSIGN_COACHING", "ASSIGN", "COACHING"}
REVIEW_DECISIONS = {"COMPLETE_REVIEW", "COMPLETE", "REVIEW", "REVIEWED"}


@bp.route("/call-records", methods=["POST"])
def create_call_record():
    require_roles([ROLE_CUSTOMER_SERVICE])
    payload = body_json()
    campaign_id = require_str(payload, "campaign_id")
    if campaign_id not in store.campaigns:
        raise not_found("campaign")
    cs_user_id = require_str(payload, "cs_user_id")
    duration = require_int(payload, "duration_seconds")
    if duration < 0:
        raise invalid_request("duration_seconds must not be negative")
    recording_uri = require_str(payload, "recording_uri")
    started_at = optional_datetime(payload, "started_at_utc", clock.now())

    row = store.new_row(
        "CallRecord",
        campaign_id=campaign_id,
        cs_user_id=cs_user_id,
        started_at_utc=started_at,
        duration_seconds=duration,
        recording_uri=recording_uri,
        coaching_status="UNREVIEWED",
        attributed_appointment_id=None,
        coached_by_user_id=None,
    )
    store.call_records[row["id"]] = row
    return created(serializers.call_record(row))


@bp.route("/call-records/<call_id>/coaching", methods=["POST"])
def coaching(call_id):
    role, user_id = require_roles([ROLE_MANAGER])
    row = store.call_records.get(call_id)
    if row is None:
        raise not_found("call record")
    payload = body_json()
    decision = require_str(payload, "decision").strip().upper()
    if decision not in ASSIGN_DECISIONS and decision not in REVIEW_DECISIONS:
        raise invalid_request("decision must assign coaching or complete the review")

    if decision in ASSIGN_DECISIONS:
        if row["coaching_status"] != "UNREVIEWED":
            raise ApiError(ERR_INVALID_STATE)
        row["coaching_status"] = "COACHING_ASSIGNED"
        row["coached_by_user_id"] = user_id
        store.touch(row)
        return object_ok(serializers.call_record(row))

    # completing the review: the cross-entity guard is identical on both paths
    if row["coaching_status"] == "REVIEWED":
        raise ApiError(ERR_INVALID_STATE)
    attributed = row.get("attributed_appointment_id")
    if not attributed:
        raise ApiError(ERR_CALL_NOT_REVIEWABLE)
    appointment = store.appointments.get(attributed)
    if appointment is None or appointment["status"] != "COMPLETED":
        raise ApiError(ERR_CALL_NOT_REVIEWABLE)
    row["coaching_status"] = "REVIEWED"
    store.touch(row)
    return object_ok(serializers.call_record(row))


@bp.route("/campaigns/<campaign_id>/call-records", methods=["GET"])
def list_campaign_calls(campaign_id):
    require_roles([ROLE_MANAGER, ROLE_CUSTOMER_SERVICE])
    if campaign_id not in store.campaigns:
        raise not_found("campaign")
    limit, offset = read_pagination(request.args)
    coaching_status = request.args.get("coaching_status")
    items = [c for c in store.by_created(store.call_records)
             if c["campaign_id"] == campaign_id]
    if coaching_status:
        items = [c for c in items if c["coaching_status"] == coaching_status]
    page, total = paginate(items, limit, offset)
    return array_ok([serializers.call_record(c) for c in page], limit, offset, total)