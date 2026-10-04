"""Carrying-cost burden (PRD 3.9).

The surcharge models the higher cost of carrying a newly built home and lands on
a bucket that depends on the condition of the property being bought.  When the
new property's grade is ``A`` or ``B`` the high-cost bucket is
``NEW_CONSTRUCTION_INSURANCE``; for any other grade it is ``NEW_TAX``.  The
surcharge is 2500 basis points and the program computes it one of two ways,
selected from its ``projected_carry_months`` and never from the data:

* three months or more -- **pooled**: sum all the program's carrying costs,
  apply the surcharge to that pooled total once, floor it, and add the whole
  pool to the high-cost bucket before the buckets are attributed;
* fewer than three months -- **per row**: apply the surcharge to each
  high-cost-bucket row's own amount and floor it individually.

Because the two approaches floor at different points, a program whose rows
straddle the high-cost bucket can report a different outstanding amount under
each.  Only the buckets whose carrying costs are still unpaid contribute to the
``outstanding_carrying_cost_cents`` a program reports.
"""

from constants import (
    BURDEN_POOL_THRESHOLD_MONTHS,
    CARRYING_COST_KINDS,
    HIGH_COST_BUCKET_GRADE_AB,
    HIGH_COST_BUCKET_OTHER_GRADE,
    NEW_CONSTRUCTION_ADJUSTMENT_BPS,
    BPS_DENOMINATOR,
)
from services.lookup import lookup
from store import db

UNPAID = "UNPAID"


def high_cost_bucket_for_program(program):
    """The bucket the construction surcharge lands on for this program."""
    new_property = lookup("properties", program.get("new_property_id"))
    grade = (new_property or {}).get("condition_grade")
    if grade in ("A", "B"):
        return HIGH_COST_BUCKET_GRADE_AB
    return HIGH_COST_BUCKET_OTHER_GRADE


def rows_for_program(program_id):
    return [c for c in db.all("carrying_costs") if c.get("bridge_program_id") == program_id]


def compute_outstanding_cents(program):
    """The ``carrying_cost_burden`` calculation."""
    rows = rows_for_program(program["id"])
    if not rows:
        return 0

    high_cost_bucket = high_cost_bucket_for_program(program)
    months = int(program.get("projected_carry_months") or 0)

    if months >= BURDEN_POOL_THRESHOLD_MONTHS:
        # Pooled: the adjustment is computed once on the aggregate of all rows.
        pooled_total = sum(int(r.get("amount_cents") or 0) for r in rows)
        pooled_adjustment = (pooled_total * NEW_CONSTRUCTION_ADJUSTMENT_BPS) // BPS_DENOMINATOR

        outstanding = 0
        for kind in CARRYING_COST_KINDS:
            unpaid = [r for r in rows if r.get("kind") == kind and r.get("repayment_status") == UNPAID]
            if not unpaid:
                continue
            bucket = sum(int(r.get("amount_cents") or 0) for r in unpaid)
            if kind == high_cost_bucket:
                bucket += pooled_adjustment
            outstanding += bucket
        return outstanding

    # Per row: the adjustment is floored individually on each high-cost row.
    outstanding = 0
    for row in rows:
        if row.get("repayment_status") != UNPAID:
            continue
        amount = int(row.get("amount_cents") or 0)
        if row.get("kind") == high_cost_bucket:
            amount += (amount * NEW_CONSTRUCTION_ADJUSTMENT_BPS) // BPS_DENOMINATOR
        outstanding += amount
    return outstanding


def recompute_program_burden(program, bump_version=False):
    """Refresh ``outstanding_carrying_cost_cents`` from the current rows.

    A derivation on its own does not bump the version (PRD 2.5 is satisfied by
    the mutation that triggered the recomputation); pass ``bump_version`` when
    the caller wants the recomputation itself treated as the mutation.
    """
    from services import touch

    program["outstanding_carrying_cost_cents"] = compute_outstanding_cents(program)
    if bump_version:
        touch(program)
    return program


def attributed_buckets(program):
    """The per-bucket attribution, exposed for the disclosure/summary surfaces."""
    rows = rows_for_program(program["id"])
    high_cost_bucket = high_cost_bucket_for_program(program)
    months = int(program.get("projected_carry_months") or 0)
    attributed = {kind: 0 for kind in CARRYING_COST_KINDS}

    if months >= BURDEN_POOL_THRESHOLD_MONTHS:
        pooled_total = sum(int(r.get("amount_cents") or 0) for r in rows)
        pooled_adjustment = (pooled_total * NEW_CONSTRUCTION_ADJUSTMENT_BPS) // BPS_DENOMINATOR
        for kind in CARRYING_COST_KINDS:
            attributed[kind] = sum(int(r.get("amount_cents") or 0) for r in rows if r.get("kind") == kind)
            if kind == high_cost_bucket:
                attributed[kind] += pooled_adjustment
    else:
        for row in rows:
            amount = int(row.get("amount_cents") or 0)
            if row.get("kind") == high_cost_bucket:
                amount += (amount * NEW_CONSTRUCTION_ADJUSTMENT_BPS) // BPS_DENOMINATOR
            attributed[row.get("kind")] = attributed.get(row.get("kind"), 0) + amount
    return attributed