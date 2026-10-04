"""Referral economics: fee reconciliation and the underwriting discount waterfall.

**Fee reconciliation (PRD 3.7).**  The fee a referral earns is the sum of three
terms:

* the base term -- ``qualifying_volume_cents`` multiplied by the referral's
  ``referral_rate_bps`` and divided by ten thousand;
* a bonus that depends on the agent's standing -- an agent whose
  ``qualification_status`` is ``QUALIFIED`` earns 300 basis points applied to the
  base, and any other agent earns no bonus at all;
* a coordination credit that caps out -- the number of the referral's
  ``COMPLETED`` coordination tasks multiplied by 8000 cents each, the whole of
  that capped at 20000 cents.

Tasks in ``OPEN`` or ``IN_PROGRESS`` count for nothing and a ``CANCELLED`` task
is excluded outright.  ``reconciled_fee_cents`` is the sum and
``fee_variance_cents`` is that figure minus the base.

PRD 2.4 names the referral economics of PRD 3.7 as the single family of
calculations where rounding to the nearer integer is used, so the computed fee
fields are rounded HALF_UP rather than floored.  Everywhere else a computed cent
amount is the floor of its expression.

**Discount waterfall (PRD 3.8).**  Two pools -- the agent referral pool of 25000
cents and the coordination credit pool of 10000 cents -- are consumed in a fixed
order that differs by the requesting referral's ``role_scope``.  On the
``DEPARTING_SIDE`` the referral pool drains first; on the ``NEW_SIDE`` or the
``RESALE_SIDE`` the coordination pool drains first and the referral pool only
participates once it is exhausted.  Within a pool the allocation is the smaller
of what remains to be funded and what the pool still holds.  Pools are consumed
per approval and do not carry across advances, so each approval starts full.
"""

from decimal import Decimal, ROUND_HALF_UP

from constants import (
    AGENT_REFERRAL_POOL_CENTS,
    BPS_DENOMINATOR,
    COORDINATION_CREDIT_CAP_CENTS,
    COORDINATION_CREDIT_PER_TASK_CENTS,
    COORDINATION_CREDIT_POOL_CENTS,
    QUALIFIED_BONUS_BPS,
)
from store import db

QUALIFIED = "QUALIFIED"


def _half_up(numerator, denominator):
    """Round ``numerator / denominator`` to the nearest cent, half away from zero."""
    if denominator == 0:
        return 0
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def base_fee_cents(referral):
    return _half_up(
        int(referral.get("qualifying_volume_cents") or 0) * int(referral.get("referral_rate_bps") or 0),
        BPS_DENOMINATOR,
    )


def completed_task_count(referral_id):
    return len([
        t for t in db.all("coordination_tasks")
        if t.get("referral_id") == referral_id and t.get("status") == "COMPLETED"
    ])


def compute_fee_fields(referral, agent):
    """Return ``(base, reconciled, variance)`` for the referral."""
    base = base_fee_cents(referral)

    bonus = 0
    if agent is not None and agent.get("qualification_status") == QUALIFIED:
        bonus = _half_up(base * QUALIFIED_BONUS_BPS, BPS_DENOMINATOR)

    credits = min(
        COORDINATION_CREDIT_CAP_CENTS,
        completed_task_count(referral["id"]) * COORDINATION_CREDIT_PER_TASK_CENTS,
    )

    reconciled = base + bonus + credits
    variance = reconciled - base
    return base, reconciled, variance


def refresh_fee_fields(referral, agent):
    """Recompute and store the referral's three computed fee fields."""
    base, reconciled, variance = compute_fee_fields(referral, agent)
    referral["base_fee_cents"] = base
    referral["reconciled_fee_cents"] = reconciled
    referral["fee_variance_cents"] = variance
    return referral


def allocate_discount(requested_discount_cents, role_scope):
    """The ``refer_discount_waterfall`` calculation.

    Returns ``(granted_cents, unfunded_cents)``.
    """
    if role_scope == "DEPARTING_SIDE":
        pools = [AGENT_REFERRAL_POOL_CENTS, COORDINATION_CREDIT_POOL_CENTS]
    else:
        pools = [COORDINATION_CREDIT_POOL_CENTS, AGENT_REFERRAL_POOL_CENTS]

    remaining = int(requested_discount_cents or 0)
    granted = 0
    for pool in pools:
        take = min(pool, remaining)
        granted += take
        remaining -= take
    return granted, max(remaining, 0)


def discount_for_advance(advance):
    """Allocate the discount for an approval against the requesting referral.

    The requesting referral is the one attached to the advance's program on the
    side the advance funds.  Where no referral is attached, the agent-first
    ordering is used, which is the ``DEPARTING_SIDE`` default.
    """
    referral = db.first_by_field("referrals", "bridge_program_id", advance.get("bridge_program_id"))
    role_scope = (referral or {}).get("role_scope")
    requested = int(advance.get("amount_cents") or 0)
    return allocate_discount(requested, role_scope)