"""Accessorial pricing and duplicate-event protection (PRD section 3.5)."""
from datetime import timedelta

import constants
import db
from errors import ApiError


def whole_minutes(start_at, end_at):
    return int((end_at - start_at).total_seconds()) // 60


def date_set(start_at, end_at):
    """The inclusive set of UTC calendar dates the interval touches."""
    first = start_at.date()
    last = end_at.date()
    dates = set()
    cursor = first
    while cursor <= last:
        dates.add(cursor)
        cursor = cursor + timedelta(days=1)
    return dates


def price(claim, load):
    """Return (billable_units, amount_cents) for a claim at approval time."""
    accessorial_type = claim["accessorial_type"]
    minutes = whole_minutes(claim["start_at"], claim["end_at"])

    if accessorial_type == "DETENTION":
        billable_minutes = max(minutes - constants.DETENTION_FREE_MINUTES, 0)
        units = billable_minutes // constants.DETENTION_BUFFER_MINUTES
        amount = units * constants.DETENTION_INCREMENT_CENTS
        amount = min(amount, constants.DETENTION_CAP_CENTS)
        return units, amount

    if accessorial_type == "LAYOVER":
        day_count = len(date_set(claim["start_at"], claim["end_at"]))
        units = max(day_count - 1, 0)
        units = min(units, constants.LAYOVER_MAX_PAYABLE_DAYS)
        return units, units * constants.LAYOVER_DAILY_CENTS

    if accessorial_type == "STOP_OFF":
        units = max((load["stop_count"] or 0) - 1, 0)
        return units, units * constants.STOP_OFF_CENTS

    if accessorial_type == "TARPING":
        return 1, constants.TARPING_FLAT_CENTS

    # BREAKDOWN
    units = max(minutes // 1440 - 1, 0)
    return units, units * constants.BREAKDOWN_DAILY_CENTS


def check_overlap(load_id, driver_id, accessorial_type, start_at, end_at):
    """Rungs 39 and 40: duplicate-event protection, whose shape differs by type."""
    if accessorial_type in constants.INTERVAL_OVERLAP_TYPES:
        buffer_delta = timedelta(minutes=constants.DETENTION_BUFFER_MINUTES)
        for other in db.accessorial_claims.values():
            if other["load_id"] != load_id:
                continue
            if other["status"] == "REJECTED":
                continue
            stored_start = other["start_at"]
            stored_end = other["end_at"] + buffer_delta
            if start_at < stored_end and end_at > stored_start:
                raise ApiError("ERR_ACCESSORIAL_OVERLAP")
        return

    if accessorial_type == "LAYOVER":
        new_dates = date_set(start_at, end_at)
        for other in db.accessorial_claims.values():
            if other["accessorial_type"] != "LAYOVER":
                continue
            if other["driver_id"] != driver_id:
                continue
            if other["status"] == "REJECTED":
                continue
            if new_dates & date_set(other["start_at"], other["end_at"]):
                raise ApiError("ERR_LAYOVER_OVERLAP")
