"""Revenue events and the routing ledger."""

from flask import Blueprint

import db
from errors import raise_error
from middleware import require_role
from response import ok
from routes.common import (
    body,
    get_channel,
    get_claim,
    get_content_item,
    paginated,
    require_stream_type,
    sort_by_created_at,
)
from routes.serializers import content_item_view
from services import content as content_svc
from services import revenue as revenue_svc

bp = Blueprint("revenue", __name__, url_prefix="/api")


@bp.post("/channels/<channel_id>/revenue-events")
def create_revenue_event(channel_id):
    require_role("PlatformAdmin")
    channel = get_channel(channel_id)
    payload = body()

    content_item_id = payload.get("content_item_id")
    if content_item_id is not None:
        get_content_item(content_item_id)

    event = revenue_svc.record_revenue_event(
        channel["id"],
        payload.get("stream_type"),
        payload.get("amount_cents") or 0,
        content_item_id,
    )
    return ok(dict(event), 201)


@bp.get("/channels/<channel_id>/revenue-events")
def list_channel_revenue_events(channel_id):
    require_role("Any")
    channel = get_channel(channel_id)
    rows = [e for e in db.all_of("revenue_events") if e["channel_id"] == channel["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])


@bp.get("/content-items/<item_id>/revenue-events")
def list_item_revenue_events(item_id):
    require_role("Any")
    item = get_content_item(item_id)
    rows = [e for e in db.all_of("revenue_events") if e["content_item_id"] == item["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])


@bp.post("/revenue-routings")
def create_routing():
    require_role("PlatformAdmin")
    payload = body()

    item = get_content_item(payload.get("content_item_id"))
    channel = get_channel(item["channel_id"])

    claim_id = payload.get("claim_id")
    claim = get_claim(claim_id) if claim_id else None

    # A payload-level code check sits alongside the validation ladder, so an
    # unsupported stream is reported before the staleness guard.
    require_stream_type(payload.get("stream_type"))

    # OCC on the content item: the mandatory expected_content_item_version.
    expected = payload.get("expected_content_item_version")
    if expected is None:
        raise_error("ERR_STALE_VERSION")
    if int(expected) != item["version"]:
        raise_error("ERR_STALE_VERSION")

    if channel.get("monetization_posture") == "FROZEN":
        raise_error("ERR_POSTURE_FROZEN")

    routing = revenue_svc.create_routing(
        item, claim, payload.get("stream_type"), payload.get("gross_revenue_cents") or 0
    )
    db.touch(item)
    return ok(dict(routing), 201)


@bp.get("/content-items/<item_id>/revenue-routings")
def list_item_routings(item_id):
    require_role("Any")
    item = get_content_item(item_id)
    rows = [r for r in db.all_of("revenue_routings") if r["content_item_id"] == item["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])


@bp.get("/channels/<channel_id>/revenue-routings")
def list_channel_routings(channel_id):
    require_role("Any")
    channel = get_channel(channel_id)
    rows = revenue_svc.routings_of_channel(channel["id"])
    return paginated([dict(r) for r in sort_by_created_at(rows)])