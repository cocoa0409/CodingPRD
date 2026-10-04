"""Calculation rules — SCAFFOLD.yaml Table 3 and PRD section 3.

Money is handled with Decimal and half-up rounding to whole cents; every
rounding order the scaffold pins is honoured literally.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db
from domain import grade_distance

TIER_1_CEILING_CENTS = 2500000
TIER_2_CEILING_CENTS = 10000000
TIER_1_MULT = Decimal("1.00")
TIER_2_MULT = Decimal("0.95")
TIER_3_MULT = Decimal("0.90")

DOWNGRADE_WEIGHT = Decimal("3")
DEFAULT_WEIGHT = Decimal("2")

ACCURACY_FLOOR = 70
ACCURACY_SCALE = 200

EVENT_DRIVEN_BONUS = 25
POSTURE_FLOOR = 25


def round_cents(value):
    """Half-up rounding to whole cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# allocated_fee_cents — waterfall_allocation
# ---------------------------------------------------------------------------
def allocate_fee(engagement, request):
    """Share of the engagement fee for one request.

    denominator sums instrument_notional_cents over ALL requests sharing the
    engagement_letter_id at every request_status, and the row being opened is
    included in its own denominator.  Rounding happens per request first; the
    engagement's fee_credited_cents is then the sum of those rounded shares.
    """
    siblings = [
        r
        for r in db.rating_requests.values()
        if r["engagement_letter_id"] == engagement["id"]
    ]
    denominator = sum(int(r["instrument_notional_cents"] or 0) for r in siblings)
    if denominator <= 0:
        return 0

    fee_amount = Decimal(int(engagement["fee_amount_cents"] or 0))
    notional = Decimal(int(request["instrument_notional_cents"] or 0))
    base_share = fee_amount * notional / Decimal(denominator)

    if base_share < TIER_1_CEILING_CENTS:
        multiplier = TIER_1_MULT
    elif base_share < TIER_2_CEILING_CENTS:
        multiplier = TIER_2_MULT
    else:
        multiplier = TIER_3_MULT

    raw = base_share * multiplier
    return round_cents(raw)


def credited_total(engagement_id):
    """Sum of the rounded per-request shares over the letter's requests."""
    return sum(
        int(r["allocated_fee_cents"] or 0)
        for r in db.rating_requests.values()
        if r["engagement_letter_id"] == engagement_id
    )


# ---------------------------------------------------------------------------
# dissent_score — weighted_scoring
# ---------------------------------------------------------------------------
def dissent_tally(committee_id, decided_grade, published_mode):
    """dissent_count and dissent_score over the committee's dissent votes.

    Internal mode (DRAFT) weights every dissent at 2; published mode
    (APPEAL_WINDOW or later) weights a DOWNGRADE dissent at 3.  Each
    contribution is weight * grade_step_distance(voter, decided).
    """
    total = Decimal("0")
    count = 0
    for vote in db.committee_votes.values():
        if vote["rating_committee_id"] != committee_id:
            continue
        if not vote.get("is_dissent"):
            continue
        count += 1
        if published_mode and vote["vote_value"] == "DOWNGRADE":
            weight = DOWNGRADE_WEIGHT
        else:
            weight = DEFAULT_WEIGHT
        steps = grade_distance(vote.get("assigned_grade"), decided_grade)
        total += weight * Decimal(steps)
    return count, round_2(total)


def dissent_score_for(committee_id, decided_grade, published_mode):
    return dissent_tally(committee_id, decided_grade, published_mode)[1]


# ---------------------------------------------------------------------------
# accuracy_only_compensation
# ---------------------------------------------------------------------------
def compensation_components(base_salary_cents, rating_accuracy_score):
    """accuracy bonus, fee bonus (always 0) and the conserved total."""
    base = int(base_salary_cents or 0)
    score = Decimal(str(rating_accuracy_score if rating_accuracy_score is not None else 0))
    excess = score - Decimal(ACCURACY_FLOOR)
    if excess < 0:
        excess = Decimal("0")
    accuracy_bonus = round_cents(Decimal(base) * excess / Decimal(ACCURACY_SCALE))
    fee_bonus = 0
    total = base + accuracy_bonus + fee_bonus
    if total == 0:
        separation = Decimal("1.0000")
    else:
        separation = round_4(Decimal(base + accuracy_bonus) / Decimal(total))
    return accuracy_bonus, fee_bonus, total, separation


# ---------------------------------------------------------------------------
# escalation_index
# ---------------------------------------------------------------------------
def escalation_index(review):
    """base = overdue_days, plus 25 when EVENT_DRIVEN, plus any escalation
    bonus already earned, floored by the posture-driven ACTIVE_WATCH floor."""
    base = int(review.get("overdue_days") or 0)
    tier_bonus = EVENT_DRIVEN_BONUS if review.get("review_type") == "EVENT_DRIVEN" else 0
    earned = int(review.get("escalation_bonus") or 0)
    floor = int(review.get("posture_floor") or 0)
    return max(base + tier_bonus + earned, floor)


def apply_posture_floor(rated_entity_id):
    """Idempotent floor of 25 on every OPEN review of an entity."""
    for review in db.surveillance_reviews.values():
        if review["rated_entity_id"] != rated_entity_id:
            continue
        if review["review_status"] not in (
            "SCHEDULED",
            "OVERDUE",
            "ESCALATED",
            "IN_PROGRESS",
        ):
            continue
        review["posture_floor"] = POSTURE_FLOOR
        review["escalation_index"] = escalation_index(review)


# ---------------------------------------------------------------------------
# consecutive_lead_months
# ---------------------------------------------------------------------------
def lead_rows(analyst_id):
    return [
        r
        for r in db.team_assignments.values()
        if r["lead_analyst_id"] == analyst_id
    ]


def lead_streak_months(analyst_id, end_instant):
    """Whole 30-day months in the lead's current unbroken streak.

    Start = earliest assigned_at among rows whose status is not REVOKED.
    End = latest window_start among CONFIRMED rows, or the current instant
    when any CONFIRMED row is open-ended.  A REVOKED row extends neither
    bound.  Ties on assigned_at break by created_at ascending.
    """
    rows = sorted(
        lead_rows(analyst_id),
        key=lambda r: (r["assigned_at"], r["created_at"]),
    )
    live = [r for r in rows if r["status"] != "REVOKED"]
    if not live:
        return 0, None

    start = live[0]["assigned_at"]
    confirmed = [r for r in live if r["status"] == "CONFIRMED"]
    if not confirmed:
        end = start
    elif any(r.get("window_end") is None for r in confirmed):
        end = end_instant
    else:
        end = max(r["window_start"] for r in confirmed)
        if end < start:
            end = start

    delta_days = (end - start).total_seconds() / float(86400)
    months = int(delta_days // 30)
    if months < 0:
        months = 0
    return months, start


def recompute_rotation(analyst, end_instant):
    """Refresh consecutive_lead_months and rotation_eligible for the lead.

    The boundary is inclusive: a streak of exactly 60 months is NOT eligible.
    """
    months, _start = lead_streak_months(analyst["id"], end_instant)
    analyst["consecutive_lead_months"] = months
    analyst["rotation_eligible"] = months < 60
    return months