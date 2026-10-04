"""In-store events, reservations, the fenced waitlist, and loyalty tiers."""

from db import VIP_PASSED_MB_THRESHOLD, db, now
from services.core import touch
from services.launch import reclass_waiting_rows

# Rows that occupy a seat of a slot.
SEAT_HOLDING = ("REGISTERED", "PROMOTED", "PASSED")


def recompute_event_counts(event):
    """registered_count counts the seat-holders; waitlisted_count the waiting rows."""
    event["registered_count"] = len([
        r for r in db().mini_build_reservations.values()
        if r["store_event_id"] == event["id"] and r["status"] in SEAT_HOLDING])
    event["waitlisted_count"] = len([
        r for r in db().mini_build_reservations.values()
        if r["store_event_id"] == event["id"] and r["status"] == "WAITLISTED"])
    return event


def children_of(event):
    return [r for r in db().mini_build_reservations.values()
            if r["store_event_id"] == event["id"]]


def recompute_tier(member):
    """vip_early_access_eligibility -- exactly the threshold promotes, only passes count."""
    member["tier"] = ("VIP" if member["passed_mb_reservations"] >= VIP_PASSED_MB_THRESHOLD
                      else "STANDARD")
    return member


def apply_standing_sanction(member):
    """A member becomes RESTRICTED at the no-show threshold, or when home freezes."""
    from db import NO_SHOW_RESTRICT_COUNT
    if member["stage"] != "ACTIVE":
        return member
    home = db().stores.get(member["home_store_id"])
    if member["passed_mb_reservations"] >= NO_SHOW_RESTRICT_COUNT:
        member["stage"] = "RESTRICTED"
    elif home is not None and home["stage"] == "FROZEN":
        member["stage"] = "RESTRICTED"
    return member


def within_event_window(event):
    current = now()
    return event["start_utc"] <= current < event["end_utc"]


def promote_off_waitlist(event, pool, base_registered):
    """Promote in arrival order while the accumulated seats still fit.

    Equality is a promotion: registered_count + seats == capacity is admitted.
    Every remaining waitlisted row of the pool is recorded as NOT_ADMITTED.
    """
    pool = sorted(pool, key=lambda r: r["arrival_counter"])
    registered = base_registered
    for reservation in pool:
        if registered + reservation["seats"] <= event["capacity_units"]:
            reservation["status"] = "PROMOTED"
            touch(reservation)
            registered += reservation["seats"]
            member = db().members.get(reservation["member_id"])
            if member is not None:
                reclass_waiting_rows(member)
        else:
            reservation["status"] = "NOT_ADMITTED"
            touch(reservation)
    recompute_event_counts(event)
    return event


def cancel_driven_promotion(event, release_mark):
    """The seats a cancellation just freed go to rows already waiting at that instant."""
    # PRD §3.6 fences a promotion pool at rows whose wait_mark is "at or below"
    # the fence, so a row that joined at the current fence is in the pool.
    pool = [r for r in children_of(event)
            if r["status"] == "WAITLISTED" and r["wait_mark"] <= release_mark]
    promote_off_waitlist(event, pool, event["registered_count"])
    touch(event)
    return event