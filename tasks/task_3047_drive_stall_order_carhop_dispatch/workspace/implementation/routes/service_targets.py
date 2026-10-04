"""ServiceTargetProfile endpoints (PRD 3.5)."""
from db import db
from errors import invalid_request
from middleware import (
    require_auth,
    body_json,
    get_int,
    get_enum,
    pagination_params,
    sort_by_created,
)
from response import success_object, success_array
from serializers import service_target_profile as ser_profile
from services import make_record, touch, get_location
from . import service_targets_bp

CHANNELS = ["STALL_INTERCOM", "APP_CHECKIN", "DRIVE_THRU", "PATIO"]
WEATHER_MODES = ["NORMAL", "HEAT_ADVISORY", "STORM"]
PROFILE_STATUSES = ["ACTIVE", "RETIRED"]
ROLES = ["ShiftManager", "PlatformAdmin"]


@service_targets_bp.route("/locations/<locationId>/service-targets", methods=["POST"])
def create_profile(locationId):
    require_auth(ROLES)
    loc = get_location(locationId)
    body = body_json()
    channel = get_enum(body, "channel", CHANNELS, required=True)
    weather_mode = get_enum(body, "weather_mode", WEATHER_MODES, required=True)
    target_seconds = get_int(body, "target_seconds", required=True, minimum=1)
    # At most one ACTIVE profile per (location, channel, weather_mode).
    for p in db.service_target_profiles.values():
        if (
            p["location_id"] == loc["id"]
            and p["channel"] == channel
            and p["weather_mode"] == weather_mode
            and p["status"] == "ACTIVE"
        ):
            p["status"] = "RETIRED"
            touch(p)
    rec = make_record()
    rec.update(
        {
            "location_id": loc["id"],
            "channel": channel,
            "weather_mode": weather_mode,
            "target_seconds": target_seconds,
            "status": "ACTIVE",
        }
    )
    db.service_target_profiles[rec["id"]] = rec
    return success_object(ser_profile(rec), 201)


@service_targets_bp.route("/locations/<locationId>/service-targets", methods=["GET"])
def list_profiles(locationId):
    require_auth(ROLES)
    from flask import request

    get_location(locationId)
    channel = request.args.get("channel")
    status = request.args.get("status")
    if channel is not None and channel not in CHANNELS:
        invalid_request("channel must be a valid order channel")
    if status is not None and status not in PROFILE_STATUSES:
        invalid_request("status must be ACTIVE or RETIRED")
    profiles = [p for p in db.service_target_profiles.values() if p["location_id"] == locationId]
    if channel is not None:
        profiles = [p for p in profiles if p["channel"] == channel]
    if status is not None:
        profiles = [p for p in profiles if p["status"] == status]
    profiles = sort_by_created(profiles)
    limit, offset = pagination_params()
    total = len(profiles)
    page = profiles[offset : offset + limit]
    return success_array([ser_profile(p) for p in page], limit, offset, total)
