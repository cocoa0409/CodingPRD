"""Channel lifecycle, the monetization loop, strikes and the review queue."""

from flask import Blueprint

import db
from errors import raise_error
from middleware import require_creator_owns, require_role
from response import ok
from routes.common import body, get_channel, paginated, sort_by_created_at
from routes.serializers import channel_view
from services import channel as channel_svc
from services import monetization as monetization_svc

bp = Blueprint("channels", __name__, url_prefix="/api")

PATCHABLE_FIELDS = (
    "channel_name",
    "country_code",
    "tax_tin_status",
    "tax_treaty",
    "payment_threshold_cents",
    "policy_strike_count",
)


@bp.post("/channels")
def create_channel():
    require_role("Anonymous", "PlatformAdmin")
    payload = body()

    if not payload.get("channel_name"):
        raise_error("ERR_INVALID_STATE", "channel_name is required.")

    channel = db.common_fields(
        {
            "channel_name": payload["channel_name"],
            "country_code": payload.get("country_code"),
            "lifetime_watch_hours": int(payload.get("lifetime_watch_hours") or 0),
            "subscriber_count": int(payload.get("subscriber_count") or 0),
            "policy_strike_count": int(payload.get("policy_strike_count") or 0),
            "copyright_strike_count": 0,
            "last_copyright_strike_activated_at": None,
            "monetization_status": "MONETIZATION_NOT_APPLIED",
            "monetization_posture": "OPEN",
            "membership_offered": bool(payload.get("membership_offered") or False),
            "tax_tin_status": payload.get("tax_tin_status") or "TIN_MISSING",
            "tax_treaty": bool(payload.get("tax_treaty") or False),
            "payment_threshold_cents": int(payload.get("payment_threshold_cents") or 10000),
        }
    )
    db.insert("channels", channel)
    channel_svc.recompute_posture(channel)
    return ok(channel_view(channel), 201)


@bp.get("/channels")
def list_channels():
    require_role("Any")
    rows = sort_by_created_at(db.all_of("channels"))
    return paginated([channel_view(c) for c in rows])


@bp.get("/channels/<channel_id>")
def get_channel_by_id(channel_id):
    require_role("Any")
    return ok(channel_view(get_channel(channel_id)))


@bp.patch("/channels/<channel_id>")
def update_channel(channel_id):
    require_role("Creator", "PlatformAdmin")
    channel = get_channel(channel_id)
    require_creator_owns(channel_id)

    payload = body()
    for field in PATCHABLE_FIELDS:
        if field in payload and payload[field] is not None:
            if field in ("tax_treaty",):
                channel[field] = bool(payload[field])
            elif field in ("payment_threshold_cents", "policy_strike_count"):
                channel[field] = int(payload[field])
            else:
                channel[field] = payload[field]

    # Raising policy_strike_count above zero immediately narrows the channel.
    channel_svc.recompute_posture(channel)
    db.touch(channel)
    return ok(channel_view(channel))


@bp.post("/channels/<channel_id>/monetization-applications")
def monetization_application(channel_id):
    require_role("Creator")
    channel = get_channel(channel_id)
    require_creator_owns(channel_id)
    return ok(channel_view(monetization_svc.apply_for_monetization(channel)))


@bp.post("/channels/<channel_id>/monetization-review")
def monetization_review(channel_id):
    require_role("MonetizationReviewer")
    channel = get_channel(channel_id)
    decision = body().get("decision")
    return ok(channel_view(monetization_svc.review_monetization(channel, decision)))


@bp.get("/review-queue")
def review_queue():
    require_role("MonetizationReviewer")
    rows = monetization_svc.review_queue()
    return paginated([channel_view(c) for c in rows])


# --- community policy strikes ------------------------------------------------

@bp.post("/channels/<channel_id>/strikes")
def create_channel_strike(channel_id):
    require_role("Moderator", "PlatformAdmin")
    channel = get_channel(channel_id)
    payload = body()
    strike = channel_svc.issue_channel_strike(
        channel["id"], payload.get("kind"), payload.get("reason_code")
    )
    return ok(dict(strike), 201)


@bp.get("/channels/<channel_id>/strikes")
def list_channel_strikes(channel_id):
    require_role("Any")
    channel = get_channel(channel_id)
    rows = [s for s in db.all_of("channel_strikes") if s["channel_id"] == channel["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])


# --- copyright strikes -------------------------------------------------------

@bp.get("/channels/<channel_id>/copyright-strikes")
def list_channel_copyright_strikes(channel_id):
    require_role("Any")
    channel = get_channel(channel_id)
    rows = [s for s in db.all_of("copyright_strikes") if s["channel_id"] == channel["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])