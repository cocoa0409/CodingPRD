"""Event application approval: the guarded ladder of §3.3 and the generative
side effects of §3.4.

Validation runs as a ladder and the rung that fires first determines the
response (§2.12). The OCC guard is checked first, as §3.3 requires ("the first
guarantee the operator needs is that the view of the event they are approving
against is current"); the state rungs follow before the business rungs, and the
business rungs fire in the fixed relative order given by §1.4.
"""

import db as store
import computed as calcs
from errors import fail
from utils import utc_day_key, occupancy_window, padded_window, half_open_overlap, max_concurrent

# EventApplication terminal states per §1.2; anything else is non-terminal.
TERMINAL_STATUSES = ("DENIED", "WITHDRAWN", "REPORTED")


def is_non_terminal(application):
    return application["status"] not in TERMINAL_STATUSES


def check_format_legality(application, format_row):
    """format_code equality plus the rotation-epoch legality rule (§3.3).

    The supplied format_code must equal the format_code carried by the format
    named by format_id, and that format must not have rotated past the epoch in
    which the cited set release was legalized.
    """
    if application["format_code"] != format_row["format_code"]:
        fail("ERR_FORMAT_CODE_NOT_LEGAL",
             "format_code does not match the format named by format_id.")

    recorded = store.db.format_legal_sets.get(format_row["id"], {})
    if application["set_release_id"] in recorded:
        legalized_epoch = recorded[application["set_release_id"]]
        if format_row["current_epoch"] > legalized_epoch:
            fail("ERR_FORMAT_CODE_NOT_LEGAL",
                 "The cited format has rotated past the epoch in which this set release "
                 "was legalized.")


def check_approval(application, store_row, format_row, body):
    # --- Optimistic concurrency (§2.10) -------------------------------------
    expected = body.get("expected_store_version")
    if expected is not None and expected != store_row["version"]:
        fail("ERR_STALE_VERSION",
             "expected_store_version does not match the store's current version.")

    # --- State rungs (§1.4 priorities 6-8) ---------------------------------
    if application["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE",
             "Only a SUBMITTED application may be approved.")

    if store_row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE",
             "A suspended store cannot sanction an event.")

    if application["prizing_report_status"] != "NOT_DUE":
        fail("ERR_REPORTING_WINDOW_OPEN",
             "The application's reporting window is already open.")

    release = store.db.set_releases.get(application["set_release_id"])
    if release is None or release["status"] != "RELEASED":
        fail("ERR_SET_NOT_STREET_LEGAL",
             "The cited set release has not reached its street date.")

    # --- Business rungs (§1.4 priorities 9-13) -----------------------------
    if application["tier"] == "CHAMPIONSHIP":
        invited = any(
            c["code_kind"] == "DIGITAL" and c["status"] == "AVAILABLE"
            for c in store.redemptions_for_application(application["id"])
        )
        if not invited:
            fail("ERR_INVITATION_REQUIRED",
                 "CHAMPIONSHIP approval requires an AVAILABLE DIGITAL code redemption "
                 "bound to this application.")

    check_daily_tier_slot(application, store_row)
    check_event_space_capacity(application, store_row)
    check_event_window_overlap(application, store_row)
    check_format_legality(application, format_row)


# --------------------------------------------------------------------------
# The three calendar rules (§3.3)
# --------------------------------------------------------------------------

def check_daily_tier_slot(application, store_row):
    """Strictly fewer than daily_event_capacity competitive events on this day.

    Only QUALIFIER and CHAMPIONSHIP events consume the store's daily competitive
    slot, and only applications standing in SUBMITTED or APPROVED count. "Any two
    events sharing that calendar day collide once the store's capacity is
    reached" (§3.3), so the rule compares the store's *other* live competitive
    events on the same UTC calendar day against the capacity: with a capacity of
    1 the first such event is legal and the second is refused. The application
    being approved is excluded from the count, since at this instant it is the
    event being placed, not one the store already holds.
    """
    if application["tier"] not in ("QUALIFIER", "CHAMPIONSHIP"):
        return
    day = utc_day_key(application["scheduled_date"])
    occupants = [
        a for a in store.applications_of_store(store_row["id"])
        if a["id"] != application["id"]
        and a["status"] in ("SUBMITTED", "APPROVED")
        and a["tier"] in ("QUALIFIER", "CHAMPIONSHIP")
        and utc_day_key(a["scheduled_date"]) == day
    ]
    capacity = store_row["daily_event_capacity"]
    if capacity is not None and len(occupants) >= capacity:
        fail("ERR_TIER_SLOT_CONFLICT",
             "The store already holds its full daily capacity of competitive events "
             "on this UTC calendar day.")


def check_event_space_capacity(application, store_row):
    """No instant may be covered by more than event_space_capacity padded windows.

    Padded windows run from thirty minutes before the event's scheduled_date to
    thirty minutes after a six-hour event-length window that starts at the
    scheduled_date, and are drawn from the store's non-terminal applications.
    """
    intervals = [
        padded_window(a["scheduled_date"])
        for a in store.applications_of_store(store_row["id"])
        if is_non_terminal(a)
    ]
    capacity = store_row["event_space_capacity"]
    if capacity is None:
        return
    if max_concurrent(intervals) > capacity:
        fail("ERR_EVENT_SPACE_CAPACITY",
             "More than event_space_capacity buffered event occupancies cover a single "
             "instant in this store's event space.")


def check_event_window_overlap(application, store_row):
    """No other non-terminal application may overlap this half-open window.

    A prior event ending exactly at this event's scheduled_date does not
    overlap; boundary equality is legal for this rule.
    """
    mine = occupancy_window(application["scheduled_date"])
    for other in store.applications_of_store(store_row["id"]):
        if other["id"] == application["id"]:
            continue
        if not is_non_terminal(other):
            continue
        if half_open_overlap(occupancy_window(other["scheduled_date"]), mine):
            fail("ERR_EVENT_WINDOW_OVERLAP",
                 "Another non-terminal application of this store overlaps this "
                 "application's occupancy window.")


# --------------------------------------------------------------------------
# Generative side effects (§3.4, §3.5)
# --------------------------------------------------------------------------

def apply_approval(application, store_row, body):
    """Create the prize allocation and set the application's deadline.

    The pool's size is fixed at this instant by tier_prize_support_pool and is
    never revisited afterwards.

    Because sanctioning is only legal on a set release that has already reached
    `RELEASED` (§3.3), the cited street date has necessarily passed by the time
    an application is approved, so the reporting window that §3.4 opens "the
    moment the cited set release reaches its street date" is already open: a
    competitive application is approved with `prizing_report_status` at `DUE`.
    A `LOCAL` event carries no deadline and its window never opens, so it stays
    `NOT_DUE` through approval.
    """
    pool_mode = body.get("pool_mode") or "BUNDLED"
    member_count = calcs.count_redeemed_digital_members(application["id"])
    base_tp = calcs.tier_prize_support_pool(application["tier"], member_count, pool_mode)

    allocation = store.insert_prize_allocation(
        application["store_id"], application["id"], application["tier"], base_tp)

    release = store.db.set_releases.get(application["set_release_id"])
    deadline = calcs.reporting_due_by(application["tier"], release["street_date"])

    changes = {
        "status": "APPROVED",
        "prize_allocation_id": allocation["id"],
        "reporting_due_by": deadline,
    }
    # A competitive event's reporting window is already open at this point
    # (the street date has passed); a LOCAL event's window never opens.
    if deadline is not None:
        changes["prizing_report_status"] = "DUE"

    store.touch(application, **changes)
    store.touch(store_row)
    return allocation