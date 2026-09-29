"""Derived quantities that are read live rather than stored.

Occupancy shares and installed utility loads depend on the logical clock, so
they are recomputed on every read; the resources that own them still get their
version bumped at the events PRD section 3 names.
"""

from decimal import Decimal

import ledger
import money
import store

# Sentinel for an open-ended (null) window end.  All instants are canonical
# ISO 8601 strings, so lexicographic comparison is chronological comparison.
OPEN_ENDED = "9999-12-31T23:59:59.999Z"

ASSIGNMENT_HOLDING_STATUSES = ("PROPOSED", "ACTIVE")


def window_end(value):
    return OPEN_ENDED if value is None else value


def windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open windows overlap when each starts strictly before the other ends."""
    return a_from < window_end(b_to) and b_from < window_end(a_to)


def window_contains(record, moment):
    return record["effective_from"] <= moment < window_end(record.get("effective_to"))


def assignments_of_space(space_id):
    return store.by_created(
        [a for a in store.db.space_assignments.values() if a["space_id"] == space_id]
    )


def assignments_of_faculty(faculty_id):
    return store.by_created(
        [a for a in store.db.space_assignments.values() if a["faculty_id"] == faculty_id]
    )


def allocated_share_pct(space):
    """Sum of holding shares whose window contains the current clock instant."""
    moment = ledger.clock_iso()
    total = 0
    for assignment in assignments_of_space(space["id"]):
        if assignment["status"] not in ASSIGNMENT_HOLDING_STATUSES:
            continue
        if window_contains(assignment, moment):
            total += int(assignment["share_pct"])
    return total


def overlapping_share_pct(space_id, candidate_from, candidate_to, exclude_id=None):
    """Peers for the 100-percent envelope check: window against window."""
    total = 0
    for assignment in assignments_of_space(space_id):
        if assignment["id"] == exclude_id:
            continue
        if assignment["status"] not in ASSIGNMENT_HOLDING_STATUSES:
            continue
        if windows_overlap(
            candidate_from,
            candidate_to,
            assignment["effective_from"],
            assignment.get("effective_to"),
        ):
            total += int(assignment["share_pct"])
    return total


def orders_in_space(space_id, status=None):
    orders = [
        o for o in store.db.equipment_orders.values() if o["install_space_id"] == space_id
    ]
    if status is not None:
        orders = [o for o in orders if o["status"] == status]
    return store.by_created(orders)


def installed_power_kw(space):
    total = Decimal("0")
    for order in orders_in_space(space["id"], "INSTALLED"):
        total = money.kw(total + money.dec(order["required_power_kw"]))
    return money.kw(total)


def installed_fume_hoods(space):
    return sum(
        int(o["required_fume_hoods"]) for o in orders_in_space(space["id"], "INSTALLED")
    )


# ---------------------------------------------------------------------------
# Staff appointment pricing (PRD 3.8)
# ---------------------------------------------------------------------------


def month_span(start_date, end_date):
    """Inclusive month span between two calendar dates."""
    return (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month) + 1


def monthly_charge_cents(appointment):
    """fte-weighted monthly charge, rounded half up to whole cents FIRST."""
    return money.cents_half_up(
        money.dec(appointment["monthly_cost_cents"]) * money.dec(appointment["fte"])
    )


def encumbrance_total_cents(appointment):
    return monthly_charge_cents(appointment) * int(appointment["committed_months"])


def appointment_disbursed_cents(appointment):
    total = 0
    for row in ledger.rows_for_package(appointment["package_id"]):
        if row["kind"] != ledger.KIND_DISBURSEMENT:
            continue
        if row["source_kind"] != ledger.SOURCE_STAFF_APPOINTMENT:
            continue
        if row["source_id"] != appointment["id"]:
            continue
        total += int(row["amount_cents"])
    return total


def appointment_amounts(appointment):
    disbursed = appointment_disbursed_cents(appointment)
    if appointment["status"] == "ACTIVE":
        encumbered = encumbrance_total_cents(appointment) - disbursed
    else:
        encumbered = 0
    return {"encumbered_cents": encumbered, "disbursed_cents": disbursed}


# ---------------------------------------------------------------------------
# Equipment order amounts (PRD 3.7)
# ---------------------------------------------------------------------------


def order_amounts(order):
    quoted = int(order["quoted_cents"])
    status = order["status"]
    encumbered = quoted if status in ("ORDERED", "DELIVERED", "UTILITY_BLOCKED") else 0
    disbursed = quoted if status == "INSTALLED" else 0
    return {"encumbered_cents": encumbered, "disbursed_cents": disbursed}


# ---------------------------------------------------------------------------
# Faculty retention rounds (PRD 3.9)
# ---------------------------------------------------------------------------


def retention_round(faculty_id):
    return len(
        [
            p
            for p in store.db.packages.values()
            if p["faculty_id"] == faculty_id
            and p["package_kind"] == "RETENTION_COUNTEROFFER"
            and p["negotiation_status"] in ("ACTIVE", "CLOSED_OUT", "SUPERSEDED")
        ]
    )
