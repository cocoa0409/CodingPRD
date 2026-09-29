"""Usage-window attribution, throttling and rate-limit breach."""
from datetime import timedelta

from constants import SUSTAINED_WINDOW_SECONDS
from db import new_id, store


def effective_allowance(assignment):
    return assignment["monthly_call_allowance"] + assignment["bonus_call_credit"]


def throttle_for(consumed, effective):
    """Exact rational comparison, no intermediate rounding."""
    if effective <= 0:
        return ("HARD_THROTTLED", consumed - effective if consumed > 0 else 0)
    if consumed >= effective:
        return ("HARD_THROTTLED", consumed - effective)
    if consumed * 5 >= effective * 4:
        return ("SOFT_THROTTLED", 0)
    return ("NORMAL", 0)


def reevaluate_throttle(assignment):
    """Recompute throttle_state after a credit or a monthly reset."""
    state, _ = throttle_for(
        assignment["monthly_calls_consumed"], effective_allowance(assignment)
    )
    changed = assignment["throttle_state"] != state
    assignment["throttle_state"] = state
    return changed


def ingest_window(assignment, developer, window_start, total_calls, burst_calls):
    window_end = window_start + timedelta(minutes=60)

    if assignment["tier"] in ("PARTNER", "PRIVILEGED") and (
        assignment["burst_credit_balance"] >= burst_calls
    ):
        variant = "BURST_ISOLATED"
        charged = total_calls - burst_calls
        credit_consumed = burst_calls
    else:
        variant = "BURST_INCLUSIVE"
        charged = total_calls
        credit_consumed = 0

    assignment["burst_credit_balance"] -= credit_consumed
    assignment["monthly_calls_consumed"] += charged
    consumed_after = assignment["monthly_calls_consumed"]

    state, overage = throttle_for(consumed_after, effective_allowance(assignment))
    assignment["throttle_state"] = state

    breach = total_calls > assignment["burst_rpm"] * SUSTAINED_WINDOW_SECONDS

    window = {
        "id": new_id(),
        "quota_assignment_id": assignment["id"],
        "window_start": window_start,
        "window_end": window_end,
        "total_calls": total_calls,
        "burst_calls": burst_calls,
        "attribution_variant": variant,
        "calls_charged_to_allowance": charged,
        "burst_credit_consumed": credit_consumed,
        "monthly_calls_consumed_after": consumed_after,
        "overage_calls": overage,
        "rate_limit_breach": breach,
        "resulting_throttle_state": state,
    }
    store.stamp_new(window, versioned=False)
    store.usage_windows[window["id"]] = window
    store.touch(assignment)

    if state == "NORMAL" and not breach:
        developer["clean_window_count"] += 1
    else:
        developer["throttled_window_count"] += 1
        developer["clean_window_count"] = 0
    store.touch(developer)

    return window


def windows_of(assignment_id):
    records = [
        w
        for w in store.usage_windows.values()
        if w["quota_assignment_id"] == assignment_id
    ]
    records.sort(key=lambda w: (w["window_start"], w["_seq"]))
    return records


def latest_window_start(assignment_id):
    latest = None
    for window in store.usage_windows.values():
        if window["quota_assignment_id"] != assignment_id:
            continue
        if latest is None or window["window_start"] > latest:
            latest = window["window_start"]
    return latest


def window_exists(assignment_id, window_start):
    for window in store.usage_windows.values():
        if (
            window["quota_assignment_id"] == assignment_id
            and window["window_start"] == window_start
        ):
            return True
    return False
