"""exception_liability_accrual and carriage_clearance_ratio (PRD §3.5)."""
from core import config as C

REJECTED_BASE_CENTS = 25000
VIOLATED_BASE_CENTS = 75000
UNFILLED_SLOT_BASE_CENTS = 40000
COVERAGE_BREACH_CAP_BPS = 10000
CLEARED_WHEN_EMPTY_BPS = 10000
RATIO_SCALE_BPS = 10000

TERMINAL_LIABILITY_STATES = ("REJECTED", "VIOLATED", "MISSED")

# The union is NOT destructive: a window accrues a basis at each terminal event.
BASIS_FIELD = "_liability_bases"


def window_duration_minutes(window):
    """Whole minutes of the half-open [window_start, window_end) interval."""
    start = C.parse_dt(window.get("window_start"))
    end = C.parse_dt(window.get("window_end"))
    if start is None or end is None:
        return 0
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60)


def liability_for_state(window, status):
    """The accrual basis contributed by one terminal outcome."""
    if status == "REJECTED":
        return C.r2c(REJECTED_BASE_CENTS)
    if status == "VIOLATED":
        breach_bps = min(COVERAGE_BREACH_CAP_BPS, window_duration_minutes(window) * 100)
        return C.r2c(
            C.d(VIOLATED_BASE_CENTS)
            + C.d(VIOLATED_BASE_CENTS) * C.d(breach_bps) / C.d(RATIO_SCALE_BPS)
        )
    if status == "MISSED":
        return C.r2c(UNFILLED_SLOT_BASE_CENTS)
    return 0


def accrue(window, status):
    """Replay one terminal event into the window's chronological basis set."""
    bases = window.setdefault(BASIS_FIELD, {})
    if status in TERMINAL_LIABILITY_STATES:
        bases[status] = liability_for_state(window, status)
    total = 0
    for value in bases.values():
        total += int(value)
    window["carriage_exception_liability_cents"] = int(total)
    return window["carriage_exception_liability_cents"]


def liability_of(window):
    bases = window.get(BASIS_FIELD) or {}
    return int(sum(int(v) for v in bases.values()))


def recompute_agreement_rollup(store, agreement):
    """The pinned order: per-window figures, sum, round once, clamp, then ratio."""
    windows = store.windows_of(agreement["id"])
    raw = 0
    for window in windows:
        raw += liability_of(window)
    rounded = C.r2c(C.d(raw))
    cap = agreement.get("exception_liability_cap_cents")
    total = int(rounded)
    if cap is not None:
        total = min(total, int(cap))
    agreement["_exception_liability_cents"] = total
    agreement["_clearance_ratio_bps"] = clearance_ratio_bps(store, agreement)
    return total


def in_scope_windows(store, agreement):
    """CLEARED, SCHEDULED and BROADCAST windows populate the ratio denominator."""
    return [
        w for w in store.windows_of(agreement["id"])
        if w.get("clearance_status") in ("CLEARED", "SCHEDULED", "BROADCAST")
    ]


def clearance_ratio_bps(store, agreement):
    """What fraction of the agreement's live airtime actually cleared.

    In scope: CLEARED, SCHEDULED and BROADCAST windows. A window counts as
    cleared when its flag is true, when its status is BROADCAST (an aired window
    counts even if its flag was later disturbed), or when it has previously been
    cleared — live airtime that reached CLEARED and moved on to SCHEDULED is
    still airtime the network cleared.
    """
    scope = in_scope_windows(store, agreement)
    if not scope:
        return CLEARED_WHEN_EMPTY_BPS
    cleared = 0
    for window in scope:
        if (
            bool(window.get("is_cleared"))
            or window.get("clearance_status") == "BROADCAST"
            or bool(window.get("_ever_cleared"))
        ):
            cleared += 1
    return C.floor_div(cleared * RATIO_SCALE_BPS, len(scope))


def window_view(store, window):
    """The wire form of a window, carrying its agreement's derived rollups."""
    from core.base import public
    data = public(window)
    agreement = store.agreements.get(window.get("parent_agreement_id"))
    data["duration_minutes"] = window_duration_minutes(window)
    if agreement is not None:
        data["agreement_clearance_ratio_bps"] = int(
            agreement.get("_clearance_ratio_bps") or clearance_ratio_bps(store, agreement)
        )
        data["agreement_exception_liability_cents"] = int(
            agreement.get("_exception_liability_cents") or 0
        )
    return data


def agreement_view(store, agreement):
    from core.base import public
    data = public(agreement)
    recompute_agreement_rollup(store, agreement)
    data["clearance_ratio_bps"] = int(agreement.get("_clearance_ratio_bps") or 0)
    data["exception_liability_cents"] = int(agreement.get("_exception_liability_cents") or 0)
    windows = store.windows_of(agreement["id"])
    data["window_count"] = len(windows)
    data["cleared_window_count"] = len([w for w in windows if w.get("is_cleared")])
    return data


def refresh_windows_of(store, agreement_id, statuses=None):
    """Re-derive is_cleared on every window under the agreement."""
    for window in store.windows_of(agreement_id):
        refresh_window_flags(store, window)
        if statuses and window.get("clearance_status") in statuses:
            pass
    return None


def refresh_window_flags(store, window):
    """is_cleared is true exactly when CLEARED and no embargo obligation bites.

    A window that reaches CLEARED latches that fact: once cleared, it counts as
    cleared airtime for the agreement's coverage ratio even after it moves on to
    SCHEDULED or BROADCAST (only a rejection, violation or miss clears the flag).
    """
    status = window.get("clearance_status")
    satisfied = True
    embargo = C.parse_dt(window.get("embargo_until"))
    if embargo is not None:
        start = C.parse_dt(window.get("window_start"))
        if start is not None and start < embargo:
            satisfied = False
    window["is_cleared"] = bool(status == "CLEARED" and satisfied)
    if window["is_cleared"]:
        window["_ever_cleared"] = True
    return window["is_cleared"]


def refresh_agreement_from_windows(store, agreement_id):
    agreement = store.agreements.get(agreement_id)
    if agreement is not None:
        recompute_agreement_rollup(store, agreement)
    return agreement


def release_slot(store, slot):
    """Return a slot's capacity units to its feed and recompute congestion."""
    feed = store.feeds.get(slot.get("parent_feed_id"))
    if feed is None:
        return
    units = int(slot.get("_units") or 1)
    if slot.get("_reserved_units_recorded"):
        feed["reserved_capacity_units"] = max(
            0, int(feed.get("reserved_capacity_units") or 0) - units
        )
        slot["_reserved_units_recorded"] = False
    refresh_feed_flags(store, feed)
    from core.base import touch
    touch(feed)


def refresh_feed_flags(store, feed):
    total = int(feed.get("total_capacity_units") or 1)
    reserved = int(feed.get("reserved_capacity_units") or 0)
    ratio = C.floor_div(reserved * RATIO_SCALE_BPS, total)
    feed["_reserved_ratio_bps"] = ratio
    threshold = int(feed.get("max_reserved_capacity_ratio") or RATIO_SCALE_BPS)
    feed["crowded"] = bool(ratio >= threshold)
    return feed["crowded"]