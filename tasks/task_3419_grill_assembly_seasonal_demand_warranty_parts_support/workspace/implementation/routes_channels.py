"""ChannelAccount create/read (PRD §3.4). subsidy_bp is derived, never written."""

from flask import Blueprint

from auth import authenticate, check_ownership, require_role
from constants import CHANNEL_TYPES, SERVICE_TIERS, SUBSIDY_BP_BY_CHANNEL_TYPE
from errors import not_found, validation
from serialize import channel_out
from store import db, new_entity
from util import get_body, ok, req_enum, req_int, req_str

bp = Blueprint("channels", __name__, url_prefix="/grillops")


@bp.post("/channels")
def create_channel():
    _, role = authenticate()
    require_role(role, ("PlannerAdmin",))
    data = get_body()
    name = req_str(data, "name")
    channel_type = req_enum(data, "channel_type", CHANNEL_TYPES)
    service_tier = data.get("service_tier")
    if service_tier is None:
        service_tier = "STANDARD"
    elif service_tier not in SERVICE_TIERS:
        raise validation("service_tier must be STANDARD or PREMIUM")
    allocation_priority = req_int(data, "allocation_priority")
    credit_limit_cents = req_int(data, "credit_limit_cents")
    if credit_limit_cents < 0:
        raise validation("credit_limit_cents must be >= 0")
    channel = new_entity({
        "name": name,
        "channel_type": channel_type,
        "service_tier": service_tier,
        "allocation_priority": allocation_priority,
        "credit_limit_cents": credit_limit_cents,
        "subsidy_bp": SUBSIDY_BP_BY_CHANNEL_TYPE[channel_type],
        "outstanding_exposure_cents": 0,
        "accessory_attach_rate": 0.0,
        "fuel_attach_rate": 0.0,
    })
    db.channels[channel["id"]] = channel
    return ok(channel_out(channel), status=201)


@bp.get("/channels/<channel_id>")
def get_channel(channel_id):
    user_id, role = authenticate()
    require_role(role, ("PlannerAdmin", "ChannelRep", "ServiceAgent"))
    channel = db.channels.get(channel_id)
    if channel is None:
        raise not_found("CHANNEL")
    if role == "ChannelRep":
        check_ownership(user_id, channel["id"])
    return ok(channel_out(channel))
