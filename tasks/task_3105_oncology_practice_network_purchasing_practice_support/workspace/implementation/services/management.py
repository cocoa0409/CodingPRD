"""Practice-management fee accrual and the fee statement.

Months are whole calendar months from term_start to the earlier of term_end and
the logical clock, inclusive of the month containing term_start. The accrued
figure is the monthly fee multiplied by the month count.
"""

from decimal import Decimal

import db
from utils import half_up, num, parse_iso, utc_now_dt, whole_months_between

FAIRNESS_FLOOR_CENTS = 50000
TIER_RATE_ADJ_ADJUSTMENT = Decimal("0.75")

BASIS_FIXED = "FIXED_MONTHLY"
BASIS_FTE = "PER_FTE"
BASIS_CLAIM = "PER_CLAIM"
BASIS_COLLECTIONS = "PERCENT_OF_NET_COLLECTIONS"


def term_end_effective(agreement, as_of=None):
    clock = as_of or utc_now_dt()
    end = parse_iso(agreement.get("term_end"))
    if end is None:
        return clock
    return min(end, clock)


def month_count(agreement, as_of=None):
    start = parse_iso(agreement.get("term_start"))
    if start is None:
        return 0
    return whole_months_between(start, term_end_effective(agreement, as_of))


def is_opaque(practice):
    """Revenue-cycle opacity: an excluded access scope. Nothing in the API sets
    it, so a practice is not opaque unless it is recorded that way."""
    return practice is not None and practice.get("access_scope") == "EXCLUDED"


def tier_adjusted_rate(agreement, practice):
    rate = num(agreement.get("fee_rate")) or Decimal(0)
    if rate < 0:
        from errors import ApiError

        raise ApiError("ERR_INVALID_REQUEST", "fee_rate may not be negative")
    tier = agreement.get("tier_level") or (practice or {}).get("tier_level")
    if tier == "TIER_1":
        return rate * TIER_RATE_ADJ_ADJUSTMENT
    return rate


def net_collections_cents(practice_id, agreement, as_of=None):
    """Sum of allowed_amount_cents over ADJUDICATED_PAID claims whose
    adjudication month falls inside the term; each claim counts once even when
    it was appealed."""
    start = parse_iso(agreement.get("term_start"))
    end = term_end_effective(agreement, as_of)
    if start is None:
        return 0
    total = 0
    for claim in db.where("claims", practice_id=practice_id):
        if claim["status"] != "ADJUDICATED_PAID":
            continue
        settled = parse_iso(claim.get("_adjudicated_at")) or parse_iso(claim.get("updated_at"))
        if settled is None:
            continue
        if not (start <= settled <= end):
            continue
        total += int(claim.get("allowed_amount_cents") or 0)
    return total


def per_claim_count(practice_id, agreement, as_of=None):
    start = parse_iso(agreement.get("term_start"))
    end = term_end_effective(agreement, as_of)
    if start is None:
        return 0
    count = 0
    for treatment in db.where("treatments", practice_id=practice_id):
        if treatment["status"] not in ("ADMINISTERED", "BILLED"):
            continue
        administered = parse_iso(treatment.get("administered_at"))
        if administered is None:
            continue
        if start <= administered <= end:
            count += 1
    return count


def monthly_fee_cents(agreement, practice, as_of=None):
    basis = agreement.get("fee_basis")
    if basis == BASIS_FIXED:
        return int(agreement.get("fixed_fee_cents") or 0), 0
    if basis == BASIS_FTE:
        return int(agreement.get("fte_count") or 0) * int(agreement.get("per_fte_fee_cents") or 0), 0
    if basis == BASIS_CLAIM:
        return (
            per_claim_count(practice["id"], agreement, as_of)
            * int(agreement.get("per_claim_fee_cents") or 0),
            0,
        )
    if basis == BASIS_COLLECTIONS:
        collections = net_collections_cents(practice["id"], agreement, as_of)
        rate = tier_adjusted_rate(agreement, practice)
        fee = half_up(Decimal(collections) * rate)
        if fee < FAIRNESS_FLOOR_CENTS and not is_opaque(practice):
            fee = FAIRNESS_FLOOR_CENTS
        return fee, collections
    return 0, 0


def accrue(agreement, practice, as_of=None):
    months = month_count(agreement, as_of)
    monthly, collections = monthly_fee_cents(agreement, practice, as_of)
    agreement["active_month_count"] = months
    agreement["accrued_fee_cents"] = monthly * months
    return {
        "agreement_id": agreement["id"],
        "accrued_fee_cents": agreement["accrued_fee_cents"],
        "monthly_fee_cents": monthly,
        "active_month_count": months,
        "net_collections_cents": collections,
    }


def statement(agreement, practice, as_of=None):
    return accrue(agreement, practice, as_of)