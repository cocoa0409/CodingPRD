"""The agreement funding ledger (PRD 2.6) and the cascades built on top of it.

"the funding pool, the committed total, the accepted value, the disbursed
advance and the withheld balance are all derived quantities recomputed from the
underlying rows on every mutation, never incremented blindly".
"""

from fractions import Fraction

from money import apply_bps, round_half_up_dp
from store import db, fmt_date, ordered, shift_date, touch

# scaffold calculations.agreement_funding_ledger / ship_date_schedule constants
RESTRICT_TRIGGER_BPS = 3000
MAX_UPLIFT_BPS = 2500
MAX_SLIP_DAYS = 45
LIVE_OPS_QUARTER_COUNT = 4
REVERSION_FULL_THRESHOLD = Fraction(5, 10)
REVERSION_PARTIAL_THRESHOLD = Fraction(8, 10)

MILESTONE_NON_CANCELLED = (
    "DEFINED", "IN_DEVELOPMENT", "UNDER_REVIEW", "CURE_PENDING", "ACCEPTED", "BREACHED",
)


def milestones_of(agreement):
    rows = [m for m in db.milestones.values() if m["agreement_id"] == agreement["id"]]
    return ordered(rows)


def change_orders_of(agreement):
    rows = [c for c in db.change_orders.values() if c["agreement_id"] == agreement["id"]]
    return ordered(rows)


def statements_of(agreement):
    rows = [s for s in db.statements.values() if s["agreement_id"] == agreement["id"]]
    return ordered(rows)


def payments_of_milestone(milestone):
    rows = [p for p in db.payments.values() if p["milestone_id"] == milestone["id"]]
    return ordered(rows)


def payments_of(agreement):
    ids = {m["id"] for m in milestones_of(agreement)}
    return ordered([p for p in db.payments.values() if p["milestone_id"] in ids])


def engagements_of_milestone(milestone):
    rows = [e for e in db.engagements.values() if e["milestone_id"] == milestone["id"]]
    return ordered(rows)


def engagements_of(agreement):
    ids = {m["id"] for m in milestones_of(agreement)}
    return ordered([e for e in db.engagements.values() if e["milestone_id"] in ids])


def invoices_of_engagement(engagement):
    rows = [i for i in db.invoices.values() if i["engagement_id"] == engagement["id"]]
    return ordered(rows)


def builds_of_milestone(milestone):
    rows = [b for b in db.builds.values() if b["milestone_id"] == milestone["id"]]
    return ordered(rows)


def reviews_of_build(build):
    rows = [r for r in db.reviews.values() if r["build_id"] == build["id"]]
    return ordered(rows)


def restrict_threshold_cents(agreement):
    """PRD 2.6: pool * 3000 bps / 10000, rounded half up to whole cents."""
    return apply_bps(agreement["funding_pool_cents"], RESTRICT_TRIGGER_BPS)


def recompute_posture(agreement):
    """PRD 2.6: FROZEN first and overriding, then RESTRICTED (inclusive), else OPEN."""
    if agreement["status"] in ("SUSPENDED", "TERMINATED"):
        return "FROZEN"
    if agreement["accepted_value_cents"] >= restrict_threshold_cents(agreement):
        return "RESTRICTED"
    return "OPEN"


def recompute_ledger(agreement):
    """Recompute every derived funding field of PRD 2.6 from the rows."""
    orders = change_orders_of(agreement)
    milestones = milestones_of(agreement)
    payments = payments_of(agreement)

    uplift_funded = sum(
        c["requested_amount_cents"] for c in orders if c["state"] == "APPROVED_UPLIFT"
    )
    pool = agreement["advance_total_cents"] + uplift_funded
    committed = sum(
        m["funded_amount_cents"] + m["uplift_cents"]
        for m in milestones
        if m["status"] != "CANCELLED"
    )
    accepted_value = sum(
        m["funded_amount_cents"] + m["uplift_cents"]
        for m in milestones
        if m["status"] == "ACCEPTED"
    )
    disbursed = sum(
        p["net_amount_cents"] or 0 for p in payments if p["status"] == "AUTHORIZED"
    )
    holdback = sum(
        p["holdback_cents"] or 0 for p in payments if p["status"] == "AUTHORIZED"
    )
    withheld = sum(
        p["scheduled_amount_cents"]
        for p in payments
        if p["status"] in ("HELD_PENDING_CURE", "WITHHELD")
    )
    breaches = sum(1 for m in milestones if m["status"] == "BREACHED")

    agreement["uplift_funded_cents"] = uplift_funded
    agreement["funding_pool_cents"] = pool
    agreement["committed_cents"] = committed
    agreement["available_funding_cents"] = pool - committed
    agreement["accepted_value_cents"] = accepted_value
    agreement["advance_disbursed_cents"] = disbursed
    agreement["holdback_reserve_cents"] = holdback
    agreement["withheld_payment_cents"] = withheld
    agreement["breach_count"] = breaches
    agreement["unrecouped_advance_cents"] = max(
        0, disbursed - agreement["advance_recouped_cents"]
    )
    agreement["funding_posture"] = recompute_posture(agreement)
    return agreement


def apply_suspension_consequences(agreement):
    """PRD 3.3 steps one and three: hold pending payments, suspend live engagements."""
    for payment in payments_of(agreement):
        if payment["status"] == "PENDING_AUTHORIZATION":
            payment["status"] = "HELD_PENDING_CURE"
            touch(payment)
    for engagement in engagements_of(agreement):
        if engagement["status"] == "ACTIVE":
            engagement["status"] = "SUSPENDED"
            touch(engagement)


def promote_engagements_of_milestone(milestone):
    """A milestone reaching IN_DEVELOPMENT promotes its PROPOSED engagements."""
    for engagement in engagements_of_milestone(milestone):
        if engagement["status"] == "PROPOSED":
            engagement["status"] = "ACTIVE"
            touch(engagement)


def unlock_dependents(agreement, milestone):
    """PRD 3.5 step two / 3.2 activation step one: DEFINED -> IN_DEVELOPMENT."""
    for candidate in milestones_of(agreement):
        if (
            candidate["depends_on_milestone_id"] == milestone["id"]
            and candidate["status"] == "DEFINED"
        ):
            candidate["status"] = "IN_DEVELOPMENT"
            touch(candidate)
            promote_engagements_of_milestone(candidate)


def recompute_ship_date(agreement):
    """PRD 3.7 ship-date recomputation, worked "from scratch rather than
    incrementally": every APPROVED_UPLIFT / APPROVED_CUT order in ascending
    decided_at with ties broken by ascending created_at."""
    from store import parse_date

    applied = [
        c for c in change_orders_of(agreement)
        if c["state"] in ("APPROVED_UPLIFT", "APPROVED_CUT")
    ]
    applied.sort(key=lambda c: (c["decided_at"], c["created_at"], c["_seq"]))
    delta = sum(c["ship_date_delta_days"] for c in applied)
    original = parse_date(agreement["ship_date_original"])
    current = shift_date(original, delta)
    agreement["ship_date_current"] = fmt_date(current)
    agreement["schedule_slip_days"] = (current - original).days
    return agreement["schedule_slip_days"]


def accepted_milestone_ratio(agreement):
    """PRD 3.9: accepted count over every milestone ever created, 4 decimals."""
    milestones = milestones_of(agreement)
    total = len(milestones)
    if total == 0:
        return Fraction(0)
    accepted = sum(1 for m in milestones if m["status"] == "ACCEPTED")
    return round_half_up_dp(Fraction(accepted, total), 4)


def settle_rights(agreement):
    """PRD 3.9 rights settlement, run at termination and at completion."""
    ratio = accepted_milestone_ratio(agreement)
    agreement["accepted_milestone_ratio"] = ratio
    if ratio < REVERSION_FULL_THRESHOLD:
        agreement["ip_reversion_state"] = "REVERTED_TO_DEVELOPER"
        agreement["sequel_rights_holder"] = "DEVELOPER"
    elif ratio < REVERSION_PARTIAL_THRESHOLD:
        agreement["ip_reversion_state"] = "PARTIAL_REVERSION"
        agreement["sequel_rights_holder"] = "SHARED"
    else:
        agreement["ip_reversion_state"] = "RETAINED_BY_PUBLISHER"
        agreement["sequel_rights_holder"] = "PUBLISHER"


COMPLETION_BLOCKING_STATUSES = (
    "DEFINED", "IN_DEVELOPMENT", "UNDER_REVIEW", "CURE_PENDING", "BREACHED",
)


def evaluate_completion(agreement):
    """PRD 3.9 completion, the last step of an acceptance cascade."""
    if agreement["status"] != "ACTIVE":
        return False
    milestones = milestones_of(agreement)
    gold_accepted = any(
        m["gate_profile"] == "GOLD" and m["status"] == "ACCEPTED" for m in milestones
    )
    if not gold_accepted:
        return False
    if any(m["status"] in COMPLETION_BLOCKING_STATUSES for m in milestones):
        return False
    agreement["status"] = "COMPLETED"
    agreement["post_launch_support_state"] = "ACTIVE"
    recompute_ledger(agreement)
    settle_rights(agreement)
    return True
