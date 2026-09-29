"""The eleven calculations of PRD 3, with every rounding placed where the PRD
puts it and no rounding anywhere else."""

from fractions import Fraction

from money import apply_bps, frac, round_half_up, round_half_up_dp
from store import db, shift_date

# --- build_gate_evaluation (PRD 3.4) -------------------------------------


def _pct(value):
    return Fraction(value, 100)


GATE_THRESHOLDS = {
    "ALPHA": {"feature": _pct(7000), "crash": _pct(9500), "content": _pct(5000), "blockers": 20},
    "BETA": {"feature": _pct(9000), "crash": _pct(9800), "content": _pct(8000), "blockers": 5},
    "GOLD": {"feature": _pct(10000), "crash": _pct(9950), "content": _pct(10000), "blockers": 0},
}

STABILITY_SURPLUS_PCT = _pct(50)
FEATURE_RELAXATION_PCT = _pct(200)
CURE_CONTENT_UPLIFT_PCT = _pct(500)

READINESS_FEATURE_WEIGHT = Fraction(45, 100)
READINESS_CRASH_WEIGHT = Fraction(35, 100)
READINESS_CONTENT_WEIGHT = Fraction(20, 100)


def gate_thresholds(milestone, crash_free_pct):
    """The two adjustments of PRD 3.4, in the fixed order: content bar first,
    then the feature bar with its stability concession."""
    profile = GATE_THRESHOLDS[milestone["gate_profile"]]

    content = profile["content"] - frac(milestone["content_threshold_relief_pct"])
    if milestone["status"] == "CURE_PENDING":
        content = content + CURE_CONTENT_UPLIFT_PCT
    content = min(_pct(10000), max(_pct(0), content))

    surplus = (
        milestone["gate_profile"] != "GOLD"
        and crash_free_pct >= profile["crash"] + STABILITY_SURPLUS_PCT
    )
    feature = profile["feature"] - (FEATURE_RELAXATION_PCT if surplus else _pct(0))
    return feature, profile["crash"], content, profile["blockers"]


def gate_passes(milestone, feature_pct, crash_pct, content_pct, blockers):
    """All four conditions must hold and every comparison is inclusive."""
    feature_bar, crash_bar, content_bar, blocker_bar = gate_thresholds(milestone, crash_pct)
    return (
        feature_pct >= feature_bar
        and crash_pct >= crash_bar
        and content_pct >= content_bar
        and blockers <= blocker_bar
    )


def readiness_score(feature_pct, crash_pct, content_pct):
    total = (
        READINESS_FEATURE_WEIGHT * feature_pct
        + READINESS_CRASH_WEIGHT * crash_pct
        + READINESS_CONTENT_WEIGHT * content_pct
    )
    return round_half_up_dp(total, 2)


# --- contractor_budget_utilization (PRD 3.8) -----------------------------

COMMITTED_BASIS_STATUSES = ("PROPOSED", "ACTIVE", "SUSPENDED", "COMPLETED")


def committed_basis_cents(milestone):
    from ledger import engagements_of_milestone

    return sum(
        e["committed_cents"]
        for e in engagements_of_milestone(milestone)
        if e["status"] in COMMITTED_BASIS_STATUSES
    )


def incurred_basis_cents(milestone):
    """APPROVED invoice amounts, "computed without regard to the engagement's own
    status"."""
    from ledger import engagements_of_milestone, invoices_of_engagement

    total = 0
    for engagement in engagements_of_milestone(milestone):
        for invoice in invoices_of_engagement(engagement):
            if invoice["status"] == "APPROVED":
                total += invoice["amount_cents"]
    return total


def budget_summary(milestone):
    committed = committed_basis_cents(milestone)
    incurred = incurred_basis_cents(milestone)
    budget = milestone["contractor_budget_cents"]
    return {
        "milestone_id": milestone["id"],
        "contractor_budget_cents": budget,
        "committed_basis_cents": committed,
        "incurred_basis_cents": incurred,
        "available_committed_cents": max(0, budget - committed),
        "overrun_cents": max(0, incurred - budget),
    }


# --- payment_disbursement (PRD 3.6) --------------------------------------

HOLDBACK_TIER_1_MAX_CENTS = 2500000
HOLDBACK_TIER_2_MAX_CENTS = 10000000
CURE_PENALTY_BPS = 250
CURE_PENALTY_CAP_BPS = 500


def disbursement(payment, milestone):
    """The four pinned steps of PRD 3.6; exactly one rounding, in step three."""
    # step one: gross
    incurred = incurred_basis_cents(milestone)
    overrun = max(0, incurred - milestone["contractor_budget_cents"])
    gross = payment["scheduled_amount_cents"] - overrun

    # step two: the tier reads the step-one gross, inclusive at both upper bounds
    if gross <= HOLDBACK_TIER_1_MAX_CENTS:
        tier_bps = 0
    elif gross <= HOLDBACK_TIER_2_MAX_CENTS:
        tier_bps = 500
    else:
        tier_bps = 1000

    # step three: the cure penalty joins the rate before the single rounding
    penalty = min(CURE_PENALTY_CAP_BPS, CURE_PENALTY_BPS * milestone["cure_count"])
    holdback_bps = tier_bps + penalty
    holdback = apply_bps(gross, holdback_bps)

    # step four: the remainder
    return {
        "contractor_overrun_cents": overrun,
        "gross_amount_cents": gross,
        "holdback_bps": holdback_bps,
        "holdback_cents": holdback,
        "net_amount_cents": gross - holdback,
    }


# --- cure_window (PRD 3.5) -----------------------------------------------

CURE_DAYS_MIN = 1
CURE_DAYS_MAX = 30
CURE_DAYS_DEFAULT = 14
MAX_CURE_ROUNDS = 2


def cure_deadline(decided_at, cure_days):
    """"the deadline is the review's decided_at advanced by that many days --
    that is, by cure_days multiplied by 86400 seconds"."""
    from datetime import timedelta

    return decided_at + timedelta(seconds=cure_days * 86400)


# --- reviewer_window_occupancy (PRD 3.5) ---------------------------------


def reviewer_window_conflict(reviewer_user_id, start, end):
    """Half-open windows, strict on both sides, so adjacency is legal."""
    from store import parse_instant

    for review in db.reviews.values():
        if review["reviewer_user_id"] != reviewer_user_id:
            continue
        other_start = parse_instant(review["review_window_start_at"])
        other_end = parse_instant(review["review_window_end_at"])
        if start < other_end and other_start < end:
            return True
    return False


# --- vendor_cooldown_occupancy (PRD 3.8) ---------------------------------

VENDOR_COOLDOWN_DAYS = 3
COOLDOWN_STATUSES = ("PROPOSED", "ACTIVE", "SUSPENDED", "COMPLETED")


def vendor_cooldown_conflict(studio_id, vendor_code, start_date, end_date):
    """Closed date intervals padded symmetrically by three days on both sides."""
    from store import parse_date

    for engagement in db.engagements.values():
        if engagement["studio_id"] != studio_id:
            continue
        if engagement["vendor_code"] != vendor_code:
            continue
        if engagement["status"] not in COOLDOWN_STATUSES:
            continue
        other_start = parse_date(engagement["start_date"])
        other_end = parse_date(engagement["end_date"])
        if (
            start_date <= shift_date(other_end, VENDOR_COOLDOWN_DAYS)
            and other_start <= shift_date(end_date, VENDOR_COOLDOWN_DAYS)
        ):
            return True
    return False


# --- live_ops_draw_allowance (PRD 3.9) -----------------------------------


def live_ops_total_cap(agreement):
    from ledger import LIVE_OPS_QUARTER_COUNT

    return agreement["live_ops_quarterly_funding_cents"] * LIVE_OPS_QUARTER_COUNT


# --- royalty_settlement (PRD 3.9) ----------------------------------------

MAX_REVENUE_LINES = 12


def line_distributables(lines, platform_fee_bps):
    """Per-line net less that line's own rounded platform fee, in submitted order."""
    values = []
    for line in lines:
        net = line["gross_cents"] - line["returns_cents"]
        fee = apply_bps(net, platform_fee_bps)
        values.append(net - fee)
    return values


def provisional_settlement(agreement, lines, recoupable_cost_cents):
    """The PROVISIONAL variant: period-scoped, royalty rounded per revenue line."""
    distributables = line_distributables(lines, agreement["platform_fee_bps"])
    distributable_total = sum(distributables)

    cost_cap = apply_bps(distributable_total, agreement["recoupable_cost_cap_bps"])
    cost_deduction = min(recoupable_cost_cents, cost_cap)
    recoupment_base = max(0, distributable_total - cost_deduction)
    recoup_applied = min(agreement["unrecouped_advance_cents"], recoupment_base)
    royalty_base = recoupment_base - recoup_applied

    royalty = 0
    if distributable_total != 0:
        for value in distributables:
            share = Fraction(royalty_base) * Fraction(value, distributable_total)
            royalty += round_half_up(share * agreement["royalty_rate_bps"] / 10000)

    return {
        "distributable_total_cents": distributable_total,
        "cost_deduction_cents": cost_deduction,
        "recoupment_base_cents": recoupment_base,
        "recoup_applied_cents": recoup_applied,
        "royalty_base_cents": royalty_base,
        "provisional_royalty_payable_cents": royalty,
    }


def final_settlement(agreement, statement):
    """The FINAL variant: life-to-date, one rounding on the cumulative base."""
    from ledger import statements_of

    finalized = [s for s in statements_of(agreement) if s["state"] == "FINALIZED"]
    finalized.sort(key=lambda s: (s["finalized_at"], s["created_at"], s["_seq"]))
    working = finalized + [statement]

    cum_distributable = sum(s["distributable_total_cents"] for s in working)
    cum_cost_claimed = sum(s["recoupable_cost_cents"] for s in working)
    cum_cost_allowed = min(
        cum_cost_claimed,
        apply_bps(cum_distributable, agreement["recoupable_cost_cap_bps"]),
    )
    cum_base = max(0, cum_distributable - cum_cost_allowed)
    cum_recoup_applied = min(agreement["advance_disbursed_cents"], cum_base)
    cum_royalty_base = cum_base - cum_recoup_applied
    cum_royalty_owed = apply_bps(cum_royalty_base, agreement["royalty_rate_bps"])
    payable = cum_royalty_owed - agreement["royalties_paid_to_date_cents"]
    return {
        "cum_recoup_applied_cents": cum_recoup_applied,
        "final_royalty_payable_cents": payable,
    }
