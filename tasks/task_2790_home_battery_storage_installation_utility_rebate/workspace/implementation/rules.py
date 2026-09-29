"""Cross-cutting business rules: logical-clock comparisons, certification and coverage
prerequisites, overlap checks and the incentive ledger moves."""

from datetime import timedelta

import store
from common import (
    COMMISSIONING_TRAVEL_BUFFER_MIN,
    TERRITORY_DISPATCH_CAP_KW,
    dec,
    kw,
    parse_iso,
)
from errors import ApiError


# --------------------------------------------------------------------------- #
# Logical clock comparisons
# --------------------------------------------------------------------------- #

def clock_dt():
    return parse_iso(store.now())


def clock_before(iso_value):
    """True when the logical clock is strictly earlier than the given instant."""
    return clock_dt() < parse_iso(iso_value)


def clock_reached(iso_value):
    """True when the logical clock is at or after the given instant."""
    return clock_dt() >= parse_iso(iso_value)


def clock_at_or_before(iso_value):
    """True when the logical clock has not passed the given instant (inclusive)."""
    return clock_dt() <= parse_iso(iso_value)


# --------------------------------------------------------------------------- #
# Certification and coverage (precedence step 10)
# --------------------------------------------------------------------------- #

def require_certified(installer, model_code):
    if installer is None:
        raise ApiError("ERR_INSTALLER_NOT_CERTIFIED", "Installer is not certified.")
    if installer["certification_status"] != "ACTIVE":
        raise ApiError("ERR_INSTALLER_NOT_CERTIFIED", "Installer certification is suspended.")
    if not clock_before(installer["certification_expires_on"]):
        raise ApiError("ERR_INSTALLER_NOT_CERTIFIED", "Installer certification has lapsed.")
    if model_code not in (installer.get("certified_model_codes") or []):
        raise ApiError(
            "ERR_INSTALLER_NOT_CERTIFIED",
            "Installer is not certified for model %s." % model_code,
        )


def require_load_calc_approved(calculation, site_id):
    if calculation is None or calculation["status"] != "APPROVED":
        raise ApiError("ERR_LOAD_CALC_NOT_APPROVED", "Load calculation is not approved.")
    if calculation["site_id"] != site_id:
        raise ApiError(
            "ERR_LOAD_CALC_NOT_APPROVED",
            "Load calculation belongs to a different site.",
        )


def require_capacity(continuous_kw, calculation):
    if dec(continuous_kw) < dec(calculation["required_continuous_kw"]):
        raise ApiError(
            "ERR_CAPACITY_BELOW_REQUIRED",
            "Bank continuous power is below the required continuous kW.",
        )


# --------------------------------------------------------------------------- #
# Overlap checks (precedence step 12)
# --------------------------------------------------------------------------- #

def require_no_test_window_conflict(installer_id, window_start, window_end, exclude_test_id=None):
    buffer_delta = timedelta(minutes=COMMISSIONING_TRAVEL_BUFFER_MIN)
    new_start = parse_iso(window_start)
    new_end = parse_iso(window_end)
    for test in store.rows("tests"):
        if exclude_test_id is not None and test["id"] == exclude_test_id:
            continue
        system = store.get("battery_systems", test["battery_system_id"])
        if system is None or system["installer_id"] != installer_id:
            continue
        other_start = parse_iso(test["window_start"])
        other_end = parse_iso(test["window_end"])
        if new_start >= other_end:
            gap = new_start - other_end
        elif other_start >= new_end:
            gap = other_start - new_end
        else:
            raise ApiError(
                "ERR_TEST_WINDOW_CONFLICT",
                "The window overlaps another commissioning window of this installer.",
            )
        # Windows that abut exactly are fine, as is any separation of at least the
        # travel buffer; anything closer than the buffer conflicts.
        if timedelta(0) < gap < buffer_delta:
            raise ApiError(
                "ERR_TEST_WINDOW_CONFLICT",
                "The window is closer than the travel buffer to another window.",
            )


def require_territory_capacity(territory_code, window_start, window_end, target_kw):
    new_start = parse_iso(window_start)
    new_end = parse_iso(window_end)
    overlapping = []
    for event in store.rows("events"):
        if event["territory_code"] != territory_code:
            continue
        other_start = parse_iso(event["window_start"])
        other_end = parse_iso(event["window_end"])
        if other_start < new_end and new_start < other_end:
            overlapping.append((other_start, other_end, dec(event["target_kw"])))
    if not overlapping:
        if dec(target_kw) > TERRITORY_DISPATCH_CAP_KW:
            raise ApiError(
                "ERR_TERRITORY_CAPACITY_EXCEEDED",
                "The event exceeds the territory dispatch capacity cap.",
            )
        return
    instants = set([new_start])
    for other_start, _other_end, _kw in overlapping:
        if new_start <= other_start < new_end:
            instants.add(other_start)
    for instant in instants:
        total = dec(target_kw)
        for other_start, other_end, other_kw in overlapping:
            if other_start <= instant < other_end:
                total += other_kw
        if total > TERRITORY_DISPATCH_CAP_KW:
            raise ApiError(
                "ERR_TERRITORY_CAPACITY_EXCEEDED",
                "The event would push the territory total above the capacity cap.",
            )


# --------------------------------------------------------------------------- #
# Incentive ledger moves (PRD 2.10) -- exact integer transfers
# --------------------------------------------------------------------------- #

def reserve_funds(program, amount):
    program["remaining_budget_cents"] -= amount
    program["reserved_budget_cents"] += amount
    store.touch(program)


def release_hold(program, amount):
    program["reserved_budget_cents"] -= amount
    program["remaining_budget_cents"] += amount
    store.touch(program)


def disburse(program, amount):
    program["reserved_budget_cents"] -= amount
    program["paid_budget_cents"] += amount
    store.touch(program)


def reverse_payment(program, amount):
    program["paid_budget_cents"] -= amount
    program["remaining_budget_cents"] += amount
    store.touch(program)


# --------------------------------------------------------------------------- #
# Dispatch capacity ledger
# --------------------------------------------------------------------------- #

def add_pledged_capacity(event, amount):
    event["enrolled_pledged_kw"] = kw(dec(event["enrolled_pledged_kw"]) + dec(amount))
    store.touch(event)
