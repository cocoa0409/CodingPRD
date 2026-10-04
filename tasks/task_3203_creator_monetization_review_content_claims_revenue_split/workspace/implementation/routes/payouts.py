"""Membership schedules, member enrolment, member payouts and payout batches."""

from flask import Blueprint

import db
from errors import raise_error
from middleware import require_creator_owns, require_role
from response import ok, ok_empty
from routes.common import body, get_channel, get_payout_batch, paginated, sort_by_created_at
from services import payout as payout_svc

bp = Blueprint("payouts", __name__, url_prefix="/api")


# --- membership schedules ----------------------------------------------------

@bp.post("/channels/<channel_id>/membership-schedules")
def publish_schedule(channel_id):
    require_role("Creator")
    channel = get_channel(channel_id)
    require_creator_owns(channel_id)

    # Publishing is available only while the channel is MONETIZATION_APPROVED.
    if channel["monetization_status"] != "MONETIZATION_APPROVED":
        raise_error("ERR_INVALID_STATE")

    payload = body()
    schedule = payout_svc.publish_membership_schedule(
        channel,
        payload.get("tier_name"),
        payload.get("monthly_fee_cents") or 0,
        payload.get("perks"),
    )
    return ok(dict(schedule), 201)


@bp.get("/channels/<channel_id>/membership-schedules")
def list_membership_schedules(channel_id):
    require_role("Any")
    channel = get_channel(channel_id)
    rows = [s for s in db.all_of("membership_schedules") if s["channel_id"] == channel["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])


# --- memberships -------------------------------------------------------------

@bp.post("/channels/<channel_id>/memberships")
def enrol_member(channel_id):
    require_role("Creator", "PlatformAdmin")
    channel = get_channel(channel_id)
    require_creator_owns(channel_id)

    payload = body()
    member = payout_svc.enrol_member(
        channel,
        payload.get("member_name"),
        payload.get("monthly_fee_cents") or 0,
        payload.get("joined_at"),
    )
    return ok(dict(member), 201)


@bp.get("/channels/<channel_id>/memberships")
def list_members(channel_id):
    require_role("Any")
    channel = get_channel(channel_id)
    rows = [m for m in db.all_of("channel_memberships") if m["channel_id"] == channel["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])


@bp.post("/channels/<channel_id>/member-payout-runs")
def member_payout_run(channel_id):
    require_role("PlatformAdmin")
    channel = get_channel(channel_id)
    payload = body()
    payout_svc.run_member_payout(channel, payload.get("total_payout_cents") or 0)
    return ok_empty()


# --- payout batches ----------------------------------------------------------

@bp.post("/channels/<channel_id>/payouts/lock")
def lock_payouts(channel_id):
    require_role("PlatformAdmin")
    channel = get_channel(channel_id)
    if channel.get("monetization_posture") == "FROZEN":
        raise_error("ERR_POSTURE_FROZEN")

    payload = body()
    batch = payout_svc.lock_payout_batch(
        channel, payload.get("period_start_at"), payload.get("period_end_at")
    )
    return ok(dict(batch))


@bp.post("/channels/<channel_id>/payouts/<batch_id>/release")
def release_payouts(channel_id, batch_id):
    require_role("PlatformAdmin")
    channel = get_channel(channel_id)
    batch = get_payout_batch(channel["id"], batch_id)
    if channel.get("monetization_posture") == "FROZEN":
        raise_error("ERR_POSTURE_FROZEN")

    payout_svc.release_payout_batch(
        channel, batch, body().get("expected_payout_batch_version")
    )
    return ok(dict(batch))


@bp.get("/channels/<channel_id>/payouts")
def list_payouts(channel_id):
    require_role("Any")
    channel = get_channel(channel_id)
    rows = [b for b in db.all_of("payout_batches") if b["channel_id"] == channel["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])


@bp.get("/channels/<channel_id>/payouts/<batch_id>")
def get_channel_payout(channel_id, batch_id):
    require_role("Any")
    channel = get_channel(channel_id)
    return ok(dict(get_payout_batch(channel["id"], batch_id)))


@bp.get("/payouts/<batch_id>")
def get_payout_by_id(batch_id):
    require_role("Any")
    batch = db.get("payout_batches", batch_id)
    if batch is None:
        raise_error("ERR_PAYOUT_BATCH_NOT_FOUND")
    return ok(dict(batch))


@bp.get("/payouts/<batch_id>/route-batch")
def get_route_batch(batch_id):
    require_role("Any")
    batch = db.get("payout_batches", batch_id)
    if batch is None:
        raise_error("ERR_PAYOUT_BATCH_NOT_FOUND")
    route_id = batch.get("route_batch_id")
    rows = []
    if route_id:
        route = db.get("payout_batches", route_id)
        if route is not None:
            rows = [dict(route)]
    return paginated(rows)