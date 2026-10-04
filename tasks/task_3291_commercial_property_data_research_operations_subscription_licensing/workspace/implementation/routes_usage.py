"""UsageEvent endpoints and seat usage monitoring (PRD 3.9)."""
from flask import Blueprint, request

import auth
import calc
import core
import lookups
import responses
from serializers_licensing import usage_event as ser_event

bp = Blueprint("usage", __name__, url_prefix="/data-research")

EVENT_TYPES = {"DATASET_DOWNLOAD", "REPORT_EXPORT", "BULK_LOOKUP", "API_QUERY"}


@bp.post("/seats/<seat_id>/usage-events")
def create_usage_event(seat_id):
    user_id, role = auth.read_headers()
    payload = core.body_of(request)
    market = core.require_string(payload, "market")
    event_type = core.require_enum(payload, "event_type", EVENT_TYPES)
    record_count = core.require_int(payload, "record_count")
    distinguishing_ip = core.require_string(payload, "distinguishing_ip")
    occurred_at = core.require_datetime(payload, "occurred_at")
    actor = auth.authorize_as(user_id, role, ["SeatUser", "PlatformAdmin"])
    seat = lookups.get_seat_any(seat_id)
    contract = lookups.get_contract(seat["contract_id"])

    if record_count < 0:
        raise core.ApiError("ERR_INVALID_REQUEST", "record_count must be zero or greater.")
    if contract["status"] not in ("ACTIVE", "GRACE"):
        raise core.ApiError("ERR_SUBSCRIPTION_INACTIVE")

    org = core.organizations.get(contract["subscriber_organization_id"])
    if org is not None and org["status"] == "SUSPENDED":
        # A suspended organization's seats are gated from recording usage.
        raise core.ApiError("ERR_SUBSCRIPTION_INACTIVE")

    presenting_user_id = user_id
    record = {
        "id": core.new_id(),
        "seat_id": seat["id"],
        "user_id": presenting_user_id,
        "market": market,
        "event_type": event_type,
        "record_count": record_count,
        "distinguishing_ip": distinguishing_ip,
        "occurred_at": core.fmt_dt(occurred_at),
        "created_at": core.now_iso(),
    }
    core.usage_events[record["id"]] = record
    calc.refresh_seat_monitoring(seat)
    return responses.ok_object(ser_event(record), 201)


@bp.get("/seats/<seat_id>/usage-events")
def list_seat_events(seat_id):
    auth.authorize(["LicensingAdmin", "EnforcementOfficer", "SeatUser", "PlatformAdmin"])
    lookups.get_seat_any(seat_id)
    limit, offset = core.pagination_args(request)
    return responses.paged(lookups.events_of(seat_id), limit, offset, ser_event)


@bp.get("/usage-events")
def list_usage_events():
    auth.authorize(["LicensingAdmin", "EnforcementOfficer", "PlatformAdmin"])
    limit, offset = core.pagination_args(request)
    rows = list(core.usage_events.values())
    seat_filter = request.args.get("seat_id")
    user_filter = request.args.get("user_id")
    if seat_filter:
        rows = [e for e in rows if e["seat_id"] == seat_filter]
    if user_filter:
        rows = [e for e in rows if e["user_id"] == user_filter]
    return responses.paged(rows, limit, offset, ser_event)


@bp.get("/usage-events/<usage_event_id>")
def get_usage_event(usage_event_id):
    auth.authorize(["LicensingAdmin", "EnforcementOfficer", "PlatformAdmin"])
    record = lookups.get_usage_event(usage_event_id)
    return responses.ok_object(ser_event(record))