"""Warranty reservation selector and the live exposure cell model.

Selector (`warranty_reservation_status_selector`): candidates are the
reservations of a listing whose warranty_state is ACTIVE, REPAIRING or
REPLACED.  Ranked by activated_on DESC, ties broken by created_at ASC.  The row
id is forbidden as either key.  An empty candidate set raises
ERR_RESERVATION_NOT_FOUND -- it is never a null winner.
"""

from db import store, add_days, calendar_days_between
from errors import fail
from numeric import rhu_int
from vocab import (
    DEFAULT_UNIT_RESERVE_PER_DAY_CENTS,
    RESERVATION_EXPIRY_SWEEP_DAYS,
    WARRANTY_STATES,
)

SELECTABLE_STATES = ("ACTIVE", "REPAIRING", "REPLACED")
LIVE_CELL_STATES = ("REPAIRING", "REPLACED")
ZERO_CELL_STATES = ("ACTIVE", "COMPLETED")


def candidates_for_listing(listing_id):
    return [
        row for row in store.reservations.values()
        if row["listing_id"] == listing_id and row["warranty_state"] in SELECTABLE_STATES
    ]


def select_servicing_reservation(listing):
    """Return the reservation currently servicing `listing`, or raise 404."""
    pool = candidates_for_listing(listing["id"])
    if not pool:
        raise fail("ERR_RESERVATION_NOT_FOUND")
    # activated_on DESC, then created_at ASC.  `id` never participates.
    pool.sort(key=lambda r: r["created_at"])
    pool.sort(key=lambda r: r["_activated_dt"], reverse=True)
    winner = pool[0]
    # The winning row must agree with the listing's servicing seller.
    if winner.get("_servicing_seller_id") and \
            winner["_servicing_seller_id"] != listing.get("servicing_seller_id"):
        raise fail("ERR_RESERVATION_NOT_FOUND")
    return winner


def reserve_cents_for_claim(reservation):
    """PRD §3.6: min(90000, 25000 + 151 * unit_reserve_per_day_cents)."""
    from vocab import CLAIM_RESERVE_BASE_CENTS, CLAIM_RESERVE_CAP_CENTS, CLAIM_RESERVE_DAY_FACTOR
    raw = CLAIM_RESERVE_BASE_CENTS + CLAIM_RESERVE_DAY_FACTOR * reservation.get(
        "unit_reserve_per_day_cents", DEFAULT_UNIT_RESERVE_PER_DAY_CENTS)
    return min(CLAIM_RESERVE_CAP_CENTS, raw)


def refresh_expired_on(reservation):
    """expired_on = activated_on + warranty_period_days (recomputed on change)."""
    reservation["expired_on"] = _iso(add_days(
        reservation["_activated_dt"], reservation["warranty_period_days"]))


def _iso(dt):
    from db import iso
    return iso(dt)


def remaining_fraction(reservation, clock):
    """Calendar days from the clock to the cell's expiry, over the period."""
    expiry = add_days(reservation["_activated_dt"], reservation["warranty_period_days"])
    remaining = max(0, calendar_days_between(clock, expiry))
    period = reservation["warranty_period_days"]
    if period <= 0:
        return 0.0
    return remaining / period


def cell_value_cents(reservation, clock):
    """One live cell, rounded individually (round_half_up) to integer cents."""
    fraction = remaining_fraction(reservation, clock)
    raw = reservation["reserved_units"] * reservation["unit_reserve_per_day_cents"] * fraction
    return rhu_int(raw, 0)


def cell_value_raw(reservation, clock):
    """The unrounded cell value, used by the single-rounding trace."""
    fraction = remaining_fraction(reservation, clock)
    return reservation["reserved_units"] * reservation["unit_reserve_per_day_cents"] * fraction


def live_cells(seller_id, clock):
    """Every live cell for the seller's listings.

    A cell is live when its reservation is its listing's servicing reservation
    and is in REPAIRING or REPLACED.  ACTIVE and COMPLETED contribute zero.
    """
    cells = []
    for listing in store.listings.values():
        if listing.get("serving_seller_id") != seller_id:
            continue
        if listing.get("servicing_seller_id") != seller_id:
            continue
        if listing["listing_state"] == "WITHDRAWN":
            continue
        try:
            winner = select_servicing_reservation(listing)
        except Exception:
            continue
        if winner["warranty_state"] in LIVE_CELL_STATES:
            cells.append(winner)
    return cells


def service_days(seller_id, clock):
    """Calendar days contributed by the seller's archived exposure cells.

    Used by `seller_tier_escalation`.  A seller with no archived cells has a
    service-day count of zero.
    """
    total = 0
    for cell in live_cells(seller_id, clock):
        expiry = add_days(cell["_activated_dt"], cell["warranty_period_days"])
        total += max(0, calendar_days_between(clock, expiry))
    return total


def sweep_expiries(clock):
    """System transition fired whenever the logical clock advances.

    Reservations still ACTIVE whose expired_on the clock has passed strictly
    become COMPLETED.
    """
    changed = []
    for reservation in list(store.reservations.values()):
        if reservation["warranty_state"] != "ACTIVE":
            continue
        expiry = add_days(reservation["_activated_dt"], reservation["warranty_period_days"])
        if clock > expiry:
            reservation["warranty_state"] = "COMPLETED"
            _touch(reservation, clock)
            changed.append(reservation)
    return changed


def _touch(reservation, clock):
    from db import touch
    touch(reservation, clock)