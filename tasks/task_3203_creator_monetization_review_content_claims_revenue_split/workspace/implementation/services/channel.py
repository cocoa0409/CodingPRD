"""Channel posture, strike counters and the strike expiry sweep.

Posture recomputation follows the ordered branches of PRD section 2.4: the four
conditions are evaluated top to bottom and the first match wins.
"""

import db
from db import add_days, now, parse_iso8601, to_iso8601, touch
from services.money import STRIKE_LIFETIME_DAYS

COPYRIGHT_TERMINATION_THRESHOLD = 3
COPYRIGHT_RESTRICTION_THRESHOLD = 2
POLICY_TERMINATION_THRESHOLD = 3


def recompute_posture(channel):
    if channel["monetization_status"] == "MONETIZATION_REVOKED":
        posture = "FROZEN"
    elif channel.get("policy_strike_count", 0) > 0:
        posture = "RESTRICTED"
    elif count_copyright_strikes(channel["id"]) >= COPYRIGHT_RESTRICTION_THRESHOLD:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    channel["monetization_posture"] = posture
    return posture


def count_copyright_strikes(channel_id):
    return sum(
        1
        for s in db.all_of("copyright_strikes")
        if s["channel_id"] == channel_id and s["status"] == "ACTIVE"
    )


def count_policy_strikes(channel_id):
    return sum(
        1
        for s in db.all_of("channel_strikes")
        if s["channel_id"] == channel_id
        and s["status"] == "ACTIVE"
        and s.get("kind") == "COMMUNITY"
    )


def refresh_copyright_strike_count(channel_id):
    """Recompute copyright_strike_count and last_copyright_strike_activated_at."""
    channel = db.get("channels", channel_id)
    if channel is None:
        return
    channel["copyright_strike_count"] = count_copyright_strikes(channel_id)
    recent = [
        s
        for s in db.all_of("copyright_strikes")
        if s["channel_id"] == channel_id and s["status"] in ("ACTIVE", "EXPIRED")
    ]
    _stamp_latest(channel, recent)
    recompute_posture(channel)


def _stamp_latest(channel, strikes):
    if not strikes:
        channel["last_copyright_strike_activated_at"] = None
        return
    latest = max(strikes, key=lambda s: (s["created_at"], s["id"]))
    channel["last_copyright_strike_activated_at"] = latest["created_at"]


def refresh_policy_strike_count(channel_id):
    channel = db.get("channels", channel_id)
    if channel is None:
        return
    channel["policy_strike_count"] = count_policy_strikes(channel_id)
    recompute_posture(channel)


def fail_locked_batches(channel_id):
    """A revocation moves every LOCKED payout batch of the channel to FAILED."""
    for batch in db.all_of("payout_batches"):
        if batch["channel_id"] == channel_id and batch["status"] == "LOCKED":
            batch["status"] = "FAILED"
            touch(batch)


def apply_community_strike_termination(channel_id):
    """The third ACTIVE COMMUNITY strike revokes the channel."""
    channel = db.get("channels", channel_id)
    if channel is None:
        return
    if channel["policy_strike_count"] >= POLICY_TERMINATION_THRESHOLD:
        channel["monetization_status"] = "MONETIZATION_REVOKED"
        touch(channel)
        fail_locked_batches(channel_id)
    recompute_posture(channel)


def apply_copyright_strike_thresholds(channel_id):
    """Three or more active copyright strikes revoke; exactly two restrict."""
    channel = db.get("channels", channel_id)
    if channel is None:
        return
    strikes = channel["copyright_strike_count"]
    if strikes >= COPYRIGHT_TERMINATION_THRESHOLD:
        channel["monetization_status"] = "MONETIZATION_REVOKED"
        touch(channel)
        fail_locked_batches(channel_id)
        recompute_posture(channel)
    elif strikes == COPYRIGHT_RESTRICTION_THRESHOLD:
        recompute_posture(channel)
    else:
        recompute_posture(channel)


def issue_channel_strike(channel_id, kind, reason_code):
    """POST /channels/{id}/strikes -- a community policy strike."""
    issued = now()
    strike = db.common_fields(
        {
            "channel_id": channel_id,
            "kind": kind,
            "reason_code": reason_code,
            "status": "ACTIVE",
            "issued_at": to_iso8601(issued),
            "expires_at": to_iso8601(add_days(issued, STRIKE_LIFETIME_DAYS)),
        },
        created_at=issued,
    )
    db.insert("channel_strikes", strike)

    channel = db.get("channels", channel_id)
    channel["policy_strike_count"] = count_policy_strikes(channel_id)
    recompute_posture(channel)
    apply_community_strike_termination(channel_id)
    touch(channel)
    return strike


def issue_copyright_strike(channel_id, content_item_id, claim_id):
    """One CopyrightStrike per taken-down claim, with its channel ordinal."""
    issued = now()
    existing = [s for s in db.all_of("copyright_strikes") if s["channel_id"] == channel_id]
    strike = db.common_fields(
        {
            "channel_id": channel_id,
            "content_item_id": content_item_id,
            "claim_id": claim_id,
            "strike_sequence": len(existing) + 1,
            "status": "ACTIVE",
            "acknowledged": False,
            "expires_at": to_iso8601(add_days(issued, STRIKE_LIFETIME_DAYS)),
        },
        created_at=issued,
    )
    db.insert("copyright_strikes", strike)
    return strike


def run_strike_expiry_sweep():
    """The sweep, run whenever the logical clock is advanced (PRD 2.9)."""
    clock = now()
    touched_channels = set()

    for bucket in ("channel_strikes", "copyright_strikes"):
        for strike in db.all_of(bucket):
            if strike["status"] != "ACTIVE":
                continue
            expires_at = parse_iso8601(strike["expires_at"])
            if expires_at is not None and clock >= expires_at:
                strike["status"] = "EXPIRED"
                touch(strike)
                touched_channels.add(strike["channel_id"])

    for channel_id in touched_channels:
        channel = db.get("channels", channel_id)
        if channel is None:
            continue
        channel["policy_strike_count"] = count_policy_strikes(channel_id)
        channel["copyright_strike_count"] = count_copyright_strikes(channel_id)
        recent = [
            s
            for s in db.all_of("copyright_strikes")
            if s["channel_id"] == channel_id and s["status"] in ("ACTIVE", "EXPIRED")
        ]
        _stamp_latest(channel, recent)
        if (
            channel["monetization_status"] == "MONETIZATION_REVOKED"
            and channel["policy_strike_count"] == 0
            and channel["copyright_strike_count"] == 0
        ):
            channel["monetization_status"] = "MONETIZATION_PENDING"
        recompute_posture(channel)
        touch(channel)