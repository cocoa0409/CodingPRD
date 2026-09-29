"""The four compensating ledgers of PRD 2.10.

Each is maintained by full recomputation from the rows that define it, never by
incremental arithmetic, so that no drift can accumulate across any sequence of
operations.  Every recomputation advances the touched row's version and
refreshes its updated_at, exactly as PRD 2.4 requires of a row mutated as a
consequence of another resource's transition.
"""

from decimal import Decimal

from calc import rhu
from store import db, touch

OVEN_COUNTED_STATUSES = ("IMPREGNATED", "SURGE_TESTED", "ACCEPTED")
CELL_COUNTED_STATUSES = ("SCHEDULED", "COMPLETED")
ORDER_OUTSTANDING_STATUSES = ("CONFIRMED", "IN_PRODUCTION")


def recompute_oven(oven):
    """booked_minutes is the sum of impregnation_minutes over the stator builds
    booked into this oven whose status is IMPREGNATED, SURGE_TESTED or
    ACCEPTED."""
    total = 0
    for build in db.stator_builds.values():
        if build.get("oven_id") == oven["id"] and build["status"] in OVEN_COUNTED_STATUSES:
            total += build.get("impregnation_minutes") or 0
    oven["booked_minutes"] = total
    touch(oven)


def cell_tests(cell_id):
    return [t for t in db.performance_tests.values()
            if t.get("test_cell_id") == cell_id and t["status"] in CELL_COUNTED_STATUSES]


def instantaneous_draw(tests, instant):
    total = Decimal(0)
    for t in tests:
        if t["window_start"] <= instant < t["window_end"]:
            total += t["dyno_draw_kw"]
    return total


def recompute_cell(cell):
    """peak_reserved_kw is the largest instantaneous sum of reserved draw across
    the SCHEDULED and COMPLETED tests occupying the cell, and reads 0.0 when the
    cell holds no such tests."""
    tests = cell_tests(cell["id"])
    peak = Decimal(0)
    for t in tests:
        total = instantaneous_draw(tests, t["window_start"])
        if total > peak:
            peak = total
    cell["peak_reserved_kw"] = rhu(peak, 1)
    touch(cell)


def recompute_allowance(distributor):
    """units_outstanding plus stock_allowance_remaining_units always equals
    committed_annual_units: a confirmed or in-production order holds units,
    a cancelled or fulfilled one has released them."""
    outstanding = 0
    for order in db.orders.values():
        if (order["distributor_id"] == distributor["id"]
                and order["status"] in ORDER_OUTSTANDING_STATUSES):
            outstanding += order["quantity"]
    distributor["units_outstanding"] = outstanding
    distributor["stock_allowance_remaining_units"] = (
        distributor["committed_annual_units"] - outstanding)
    touch(distributor)


def distributor_claims(distributor_id):
    return [c for c in db.warranty_claims.values()
            if c["distributor_id"] == distributor_id]


def recompute_credit_balance(distributor):
    """warranty_credit_balance_cents is the sum of warranty_credit_cents over
    this distributor's claims whose credit_posted flag is true."""
    total = 0
    for claim in distributor_claims(distributor["id"]):
        if claim.get("credit_posted"):
            total += claim.get("warranty_credit_cents") or 0
    distributor["warranty_credit_balance_cents"] = total
    touch(distributor)


def recompute_presumed_defects(distributor):
    """open_presumed_defect_count is the count of this distributor's claims that
    carry a defect presumption and are still open."""
    count = 0
    for claim in distributor_claims(distributor["id"]):
        if claim.get("defect_presumption_applied") and claim["status"] != "CLOSED":
            count += 1
    distributor["open_presumed_defect_count"] = count
    touch(distributor)
