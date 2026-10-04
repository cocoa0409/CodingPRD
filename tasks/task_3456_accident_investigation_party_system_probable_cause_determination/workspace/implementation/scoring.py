"""Launch scoring (PRD section 3.1; SCAFFOLD calculations).

statutory_launch_score: integer arithmetic, inclusive tier lower bounds,
clamped to [0, 100]; gates adoption.

risk_adjusted_launch_score: weighted components, each rounded half-up to one
decimal BEFORE summation (order pinned), then clamped; observability only.
"""

from decimal import Decimal, ROUND_HALF_UP

from constants import (
    CATASTROPHIC_FATALITY_BONUS,
    CATASTROPHIC_FATALITY_THRESHOLD,
    CATEGORY_DAMAGE_MULTIPLIER,
    DAMAGE_POINTS_HIGH,
    DAMAGE_POINTS_LOW,
    DAMAGE_POINTS_MID,
    DAMAGE_TIER_HIGH_MIN_CENTS,
    DAMAGE_TIER_MID_MIN_CENTS,
    FATALITY_BASE_POINTS,
    FATALITY_WEIGHT,
    FULL_LAUNCH_THRESHOLD,
    INJURY_CAP,
    INJURY_WEIGHT,
    LIMITED_LAUNCH_THRESHOLD,
    MODAL_BUMP_CATEGORIES,
    MODAL_BUMP_POINTS,
    PUBLIC_INTEREST_WEIGHT,
    PUBLIC_TRANSPORT_POINTS,
    SCORE_MAX,
    SCORE_MIN,
)


def _components(fatalities_count, injuries_count, damage_estimate_cents,
                is_public_transport, category):
    if fatalities_count == 0:
        fatality_points = 0
    else:
        fatality_points = FATALITY_BASE_POINTS
        if fatalities_count >= CATASTROPHIC_FATALITY_THRESHOLD:
            fatality_points += CATASTROPHIC_FATALITY_BONUS

    if damage_estimate_cents == 0:
        damage_points = 0
    elif damage_estimate_cents < DAMAGE_TIER_MID_MIN_CENTS:
        damage_points = DAMAGE_POINTS_LOW
    elif damage_estimate_cents < DAMAGE_TIER_HIGH_MIN_CENTS:
        damage_points = DAMAGE_POINTS_MID
    else:
        damage_points = DAMAGE_POINTS_HIGH

    injury_points = min(injuries_count, INJURY_CAP)

    public_points = 0
    if is_public_transport:
        public_points += PUBLIC_TRANSPORT_POINTS
    if category in MODAL_BUMP_CATEGORIES:
        public_points += MODAL_BUMP_POINTS

    return fatality_points, damage_points, injury_points, public_points


def _round1(value):
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def compute_launch_scores(fatalities_count, injuries_count,
                          damage_estimate_cents, is_public_transport, category):
    fatality_points, damage_points, injury_points, public_points = _components(
        fatalities_count, injuries_count, damage_estimate_cents,
        is_public_transport, category,
    )

    statutory_score = (
        fatality_points + damage_points + injury_points + public_points
    )
    statutory_score = max(SCORE_MIN, min(SCORE_MAX, statutory_score))

    c_fatality = _round1(Decimal(fatality_points) * Decimal(str(FATALITY_WEIGHT)))
    c_damage = _round1(
        Decimal(damage_points) * Decimal(str(CATEGORY_DAMAGE_MULTIPLIER[category]))
    )
    c_injury = _round1(Decimal(injury_points) * Decimal(str(INJURY_WEIGHT)))
    c_public = _round1(Decimal(public_points) * Decimal(str(PUBLIC_INTEREST_WEIGHT)))
    risk_total = c_fatality + c_damage + c_injury + c_public
    risk_total = max(Decimal(SCORE_MIN), min(Decimal(SCORE_MAX), risk_total))
    risk_adjusted_score = float(risk_total)

    if statutory_score >= FULL_LAUNCH_THRESHOLD:
        suggested_mode = "FULL_GO_TEAM"
    elif statutory_score >= LIMITED_LAUNCH_THRESHOLD:
        suggested_mode = "LIMITED"
    else:
        suggested_mode = "DECLINED"

    return statutory_score, risk_adjusted_score, suggested_mode
