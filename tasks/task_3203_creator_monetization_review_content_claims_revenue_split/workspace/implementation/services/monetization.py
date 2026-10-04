"""The monetization application loop and the reviewer decision cascade."""

import db
from db import touch
from errors import raise_error
from services import channel as channel_svc
from services import content as content_svc

MIN_WATCH_HOURS = 4000
MIN_SUBSCRIBERS = 1000

WATCH_HOURS_DIVISOR = 1000
SUBSCRIBER_DIVISOR = 500
STRIKE_PENALTY = 10

APPLICABLE_STATUSES = ("MONETIZATION_NOT_APPLIED", "MONETIZATION_REJECTED")


def apply_for_monetization(channel):
    """POST /channels/{id}/monetization-applications."""
    if channel["monetization_status"] not in APPLICABLE_STATUSES:
        raise_error("ERR_INVALID_STATE")

    # PRD section 3.1 states the three preconditions first ("Three preconditions
    # guard the transition ... A channel whose posture is RESTRICTED cannot file
    # an application at all"), so a non-zero policy strike count is reported
    # distinctly from a restricted posture.
    if (
        int(channel.get("lifetime_watch_hours", 0)) < MIN_WATCH_HOURS
        or int(channel.get("subscriber_count", 0)) < MIN_SUBSCRIBERS
    ):
        raise_error("ERR_MONETIZATION_INELIGIBLE")
    if int(channel.get("policy_strike_count", 0)) != 0:
        raise_error("ERR_MONETIZATION_BLOCKED_BY_STRIKE")

    posture = channel.get("monetization_posture")
    if posture == "FROZEN":
        raise_error("ERR_POSTURE_FROZEN")
    if posture == "RESTRICTED":
        raise_error("ERR_POSTURE_RESTRICTED")

    channel["monetization_status"] = "MONETIZATION_PENDING"
    channel_svc.recompute_posture(channel)
    touch(channel)
    return channel


def review_monetization(channel, decision):
    """POST /channels/{id}/monetization-review."""
    if channel["monetization_status"] != "MONETIZATION_PENDING":
        raise_error("ERR_INVALID_STATE")

    if decision == "REJECT":
        channel["monetization_status"] = "MONETIZATION_REJECTED"
        channel_svc.recompute_posture(channel)
        touch(channel)
        return channel

    if decision != "APPROVE":
        raise_error("ERR_INVALID_STATE")

    items = [
        item for item in db.all_of("content_items") if item["channel_id"] == channel["id"]
    ]
    for item in items:
        if item["upload_status"] in ("CLASSIFIED", "CLAIM_SCAN_COMPLETE"):
            if item.get("ad_suitability") == "NO_ADS":
                raise_error("ERR_CLASSIFICATION_BLOCKS_MONETIZATION")

    # hop 1: the channel is approved and every CLASSIFIED item is settled forward.
    channel["monetization_status"] = "MONETIZATION_APPROVED"

    settled = [i for i in items if i["upload_status"] == "CLASSIFIED"]
    for item in settled:
        # hop 2: materialise one claim per matching reference at >= 0.500; each
        # such claim starts ACTIVE with lock_reason PENDING_RETRO while the
        # channel's posture is OPEN.
        for reference, score in content_svc.matching_references(item):
            content_svc.create_auto_claim(item, reference, score)
        item["upload_status"] = "CLAIM_SCAN_COMPLETE"
        # hop 3/4: the claim-revenue-lock cascade ran inside create_auto_claim,
        # which leaves holds_revenue recomputed to TRUE on the item.
        content_svc.recompute_item(item)
        touch(item)

    channel_svc.recompute_posture(channel)
    touch(channel)
    return channel


def review_queue():
    """Channels in MONETIZATION_PENDING ranked by the channel health score.

    The score is compared at six decimal places and ties break on created_at
    ascending -- never on id.
    """
    eligible = [
        c
        for c in db.all_of("channels")
        if c["monetization_status"] == "MONETIZATION_PENDING"
    ]
    if not eligible:
        return []

    def score(channel):
        return (
            (channel["lifetime_watch_hours"] / WATCH_HOURS_DIVISOR)
            + (channel["subscriber_count"] / SUBSCRIBER_DIVISOR)
            - (STRIKE_PENALTY * channel["copyright_strike_count"])
        )

    return sorted(eligible, key=lambda c: (-round(score(c), 6), c["created_at"], c["id"]))