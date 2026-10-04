"""Dealer channel events."""
from flask import Blueprint

import db
import services
from errors import (
    err_not_found, err_invalid_request, err_channel_exclusivity,
    err_channel_event_overlap, err_invalid_period,
)
from response import (
    body, get_auth, require_roles, success_obj, paginate,
    req_int, req_enum, req_ts,
)

bp = Blueprint("channel_events", __name__)

READ = ["PlatformAdmin", "RegionManager", "ChannelDirector", "DealerPrincipal"]


def _serialize(e):
    return dict(e)


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.post("/dealers/<did>/channel-events")
def create_channel_event(did):
    _, role = get_auth()
    require_roles(role, ["ChannelDirector"])
    dealer = db.dealers.get(did)
    if dealer is None:
        raise err_not_found("dealer not found")
    data = body()
    period_start = req_ts(data, "period_start")
    period_end = req_ts(data, "period_end")
    channel = req_enum(data, "channel", {"INDEPENDENT", "BIGBOX"})
    sales = req_int(data, "sales_cents")
    services.refresh_dealer_channel(dealer)
    if channel == "BIGBOX" and dealer["channel_posture"] == "BLOCKED":
        raise err_channel_exclusivity()
    # exact-duplicate check (priority 12) before period-shape (16)
    for ev in db.channel_events.values():
        if (
            ev["dealer_id"] == did
            and ev["channel"] == channel
            and ev["status"] == "CONFIRMED"
            and db.parse_ts(ev["period_start"]) == period_start
            and db.parse_ts(ev["period_end"]) == period_end
        ):
            raise err_channel_event_overlap()
    if period_end <= period_start:
        raise err_invalid_period("period_end must be after period_start")
    if period_start > db.now():
        raise err_invalid_period("period_start must not be in the future")
    if sales <= 0:
        raise err_invalid_request("sales_cents must be > 0")
    # partial overlap supersedes
    for ev in db.channel_events.values():
        if (
            ev["dealer_id"] == did
            and ev["channel"] == channel
            and ev["status"] == "CONFIRMED"
            and _overlaps(period_start, period_end, db.parse_ts(ev["period_start"]), db.parse_ts(ev["period_end"]))
        ):
            ev["status"] = "SUPERSEDED"
    rec = {
        "id": db.new_id(),
        "created_at": db.fmt_ts(db.now()),
    }
    rec.update({
        "dealer_id": did,
        "period_start": db.fmt_ts(period_start),
        "period_end": db.fmt_ts(period_end),
        "channel": channel,
        "sales_cents": sales,
        "status": "CONFIRMED",
    })
    db.channel_events[rec["id"]] = rec
    services.refresh_dealer_channel(dealer)
    db.touch(dealer)
    return success_obj(_serialize(rec), 201)


@bp.get("/dealers/<did>/channel-events")
def list_channel_events(did):
    _, role = get_auth()
    require_roles(role, READ)
    if did not in db.dealers:
        raise err_not_found("dealer not found")
    items = [e for e in db.channel_events.values() if e["dealer_id"] == did]
    return paginate([_serialize(e) for e in items])
