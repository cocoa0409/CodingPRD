"""Small shared route guards: path resolution, paging and horizon windows."""

import envelope
import refs
import shape
import store
from errors import fail


def must(table, row_id, error_id):
    rec = refs.get(table, row_id)
    if rec is None:
        fail(error_id)
    return rec


def page(serializer, records):
    limit, offset = shape.q_pagination()
    return envelope.listing([serializer(rec) for rec in records], limit, offset)


def horizon_bounds(prop):
    """(exclusive lower bound, inclusive upper bound) as date strings."""
    today = refs.clock_date_str()
    return today, refs.shift(today, prop["booking_horizon_days"])


def inside_horizon(prop, day_s):
    low, high = horizon_bounds(prop)
    return low < day_s <= high


def require_horizon(prop, dates, error_id="ERR_WINDOW_OUTSIDE_HORIZON"):
    for day in dates:
        if not inside_horizon(prop, day):
            fail(error_id)


def require_stay_horizon(prop, arrival_date, departure_date):
    low, high = horizon_bounds(prop)
    if not (arrival_date > low and departure_date <= high):
        fail("ERR_STAY_OUTSIDE_HORIZON")


def analytics_window(prop, start_date, end_date):
    if end_date < start_date:
        fail("ERR_ANALYTICS_WINDOW_INVALID")
    span = (refs.pd(end_date) - refs.pd(start_date)).days + 1
    if span > prop["mix_window_days"]:
        fail("ERR_ANALYTICS_WINDOW_INVALID")
    return span
