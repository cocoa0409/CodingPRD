"""The conserved bond ledger (PRD 2.9 and 3.9 / scaffold restoration_bond_release).

Two rounding orders coexist and the divergence is intentional:
  per_task_provisional -- round each task's share, then sum
  final_closeout       -- sum the verified areas, then round once
"""

import math
from decimal import Decimal

import db
from services import calc


def tasks_of_venue(venue_id):
    return db.where("restoration_tasks", venue_id=venue_id)


def verified_tasks(venue_id):
    return [t for t in tasks_of_venue(venue_id) if t["status"] == "VERIFIED"]


def per_task_share(venue, task):
    """round_half_up(restoration_bond_cents * area_sqm / disturbed_area_sqm)."""
    disturbed = int(venue["disturbed_area_sqm"])
    if disturbed <= 0:
        return 0
    raw = Decimal(int(venue["restoration_bond_cents"])) * Decimal(int(task["area_sqm"])) / Decimal(
        disturbed
    )
    return calc.round_cents(raw)


def gross_total(venue):
    """Sum the verified areas first, then round the product exactly once."""
    disturbed = int(venue["disturbed_area_sqm"])
    if disturbed <= 0:
        return 0
    verified_area = sum(int(t["area_sqm"]) for t in verified_tasks(venue["id"]))
    raw = Decimal(int(venue["restoration_bond_cents"])) * Decimal(verified_area) / Decimal(disturbed)
    return calc.round_cents(raw)


def late_days(deadline_utc, clock):
    if deadline_utc is None:
        return 0
    if clock <= deadline_utc:
        return 0
    seconds = db.seconds_between(deadline_utc, clock)
    hours = Decimal(seconds) / Decimal(3600)
    return int(math.ceil(hours / Decimal(24)))


def apply_progressive_settlement(venue):
    """bond_released_cents becomes the sum of the VERIFIED per-task figures."""
    released = sum(int(t["bond_release_cents"]) for t in verified_tasks(venue["id"]))
    venue["bond_released_cents"] = released
    calc.apply_bond_held(venue)


def apply_final_settlement(venue, permit):
    """Gross once-rounded, late penalty capped at gross, remainder onto one task."""
    gross = gross_total(venue)
    days = late_days(permit["restoration_deadline_utc"] if permit else None, db.now())
    penalty = min(calc.LATE_PENALTY_PER_DAY_CENTS * days, gross)
    net_total = gross - penalty

    verified = verified_tasks(venue["id"])
    per_task_sum = sum(int(t["bond_release_cents"]) for t in verified)
    remainder = net_total - per_task_sum
    if verified and remainder != 0:
        target = sorted(
            verified,
            key=lambda t: (-int(t["area_sqm"]), t["created_at"], t["_seq"]),
        )[0]
        with db.mutation(target):
            target["bond_release_cents"] = int(target["bond_release_cents"]) + remainder

    venue["bond_released_cents"] = net_total
    venue["bond_forfeited_cents"] = penalty
    calc.apply_bond_held(venue)
