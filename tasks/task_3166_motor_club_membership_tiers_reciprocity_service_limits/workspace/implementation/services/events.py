"""MembershipEvent append helper."""

from db import DB, CLOCK, new_id, fmt_ts


def append_event(membership_id, event_type, from_tier=None, to_tier=None, note=""):
    now = CLOCK.now()
    ev = {
        "id": new_id(),
        "membership_id": membership_id,
        "event_type": event_type,
        "from_tier": from_tier,
        "to_tier": to_tier,
        "effective_at": fmt_ts(now),
        "note": note,
        "created_at": fmt_ts(now),
        "_created_dt": now,
    }
    DB.membership_events[ev["id"]] = ev
    return ev
