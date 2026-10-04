"""Feed sources (PRD §3.1): electronic collection authority registered in
SETUP only."""
from flask import Blueprint

from auth import require_roles, body
from envelope import ok_object, paginate
from errors import raise_err
from loaders import get_event, require_posture, base_record
from serializers import feed_json
from store import db
from util import nonblank

bp = Blueprint("feeds", __name__)

READ_ROLES = (
    "ElectionOpsAdmin", "CoveragePlanner", "StringerCoordinator",
    "TabulationClerk", "DecisionAnalyst", "DecisionDeskChief", "RecountOfficer",
)
PRIORITY_TIERS = ("PRIMARY", "SECONDARY")


@bp.post("/election-events/<rid>/feed-sources")
def create_feed(rid):
    require_roles("ElectionOpsAdmin")
    event = get_event(rid)
    require_posture(event, "SETUP")
    data = body()
    for f in ("feed_name", "state_codes"):
        if f not in data or data[f] is None:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not nonblank(data["feed_name"]):
        raise_err("ERR_INVALID_REQUEST", "feed_name must be a non-blank string")
    codes = data["state_codes"]
    if (not isinstance(codes, list) or not codes
            or any(not nonblank(s) for s in codes)):
        raise_err("ERR_INVALID_REQUEST", "state_codes must be a non-empty array of codes")
    tier = data.get("priority_tier", "SECONDARY")
    if tier is None:
        tier = "SECONDARY"
    if tier not in PRIORITY_TIERS:
        raise_err("ERR_INVALID_REQUEST", "priority_tier out of range")
    for f in db["feeds"].values():
        if f["event_id"] == event["id"] and f["feed_name"] == data["feed_name"]:
            raise_err("ERR_DUPLICATE_FEED", "feed_name already registered in this event")
    rec = base_record()
    rec.update({
        "event_id": event["id"],
        "feed_name": data["feed_name"],
        "state_codes": list(codes),
        "priority_tier": tier,
    })
    db["feeds"][rec["id"]] = rec
    return ok_object(feed_json(rec), 201)


@bp.get("/election-events/<rid>/feed-sources")
def list_feeds(rid):
    require_roles(*READ_ROLES)
    event = get_event(rid)
    rows = [f for f in db["feeds"].values() if f["event_id"] == event["id"]]
    return paginate(rows, feed_json)
