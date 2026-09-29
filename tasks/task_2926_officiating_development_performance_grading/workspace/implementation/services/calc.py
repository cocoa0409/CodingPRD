"""Pure calculations (PRD 2.7, 3.3, 3.4, 3.6, 3.9).

Every quantity is a Decimal carried to exactly 2 decimal places and every
rounding step is round-half-up. `float` is never used for a derived number.
"""

from datetime import timedelta
from decimal import Decimal

from validation import q2

# --- enums ----------------------------------------------------------------

POSITIONS = ["REFEREE", "UMPIRE", "DOWN_JUDGE"]
TIERS = ["TIER_3", "TIER_2", "TIER_1"]
CALL_CATEGORIES = ["HOLDING", "PASS_INTERFERENCE", "ROUGHING_PASSER", "FALSE_START"]
GRADE_CODES = ["CORRECT", "INCORRECT_CALL", "MISSED_CALL", "INADVERTENT_WHISTLE"]
IMPACTS = ["LOW", "MEDIUM", "HIGH", "GAME_CRITICAL"]
REVIEW_CATEGORIES = ["SCORING_PLAY", "TURNOVER", "PLAYER_SAFETY", "GAME_ADMIN"]
REPLAY_DECISIONS = ["STANDS", "CONFIRMED", "REVERSED"]
RECORD_TYPES = ["RULES_CLINIC", "PHYSICAL_TEST", "RULES_EXAM"]
REPORT_TYPES = ["POOL_REPORT", "RULES_CLARIFICATION"]
REASON_CATEGORIES = ["PERFORMANCE", "CONDUCT", "ATTENDANCE"]
SEVERITIES = ["WARNING", "REMEDIATION", "SUSPENSION"]

# --- per-play error points (PRD 3.6) --------------------------------------

GRADE_BASE = {
    "CORRECT": Decimal("0.00"),
    "INCORRECT_CALL": Decimal("1.00"),
    "MISSED_CALL": Decimal("1.50"),
    "INADVERTENT_WHISTLE": Decimal("2.00"),
}
IMPACT_MULTIPLIER = {
    "LOW": Decimal("0.50"),
    "MEDIUM": Decimal("1.00"),
    "HIGH": Decimal("1.75"),
    "GAME_CRITICAL": Decimal("2.50"),
}
POSITION_FACTOR = {
    "REFEREE": Decimal("1.20"),
    "UMPIRE": Decimal("1.00"),
    "DOWN_JUDGE": Decimal("0.90"),
}


def play_error_points(grade_code, impact, official_position):
    """"Per-play error points are the product of three factors, rounded half up
    to two decimal places. ... The third is a position factor read from the
    graded official's registered `position`. ... The rounding happens once, on
    the product, at the moment the play is written."""
    return q2(GRADE_BASE[grade_code]
              * IMPACT_MULTIPLIER[impact]
              * POSITION_FACTOR[official_position])


# --- season aggregate (PRD 3.6) -------------------------------------------

ERROR_SCALE = Decimal("20.00")


def weighted_error_points(ordered_grades):
    """"`weighted_error_points` is the running sum of their per-play
    `error_points` -- values that were already rounded when each play was
    written -- and no further rounding is applied to the total.\""""
    total = Decimal("0.00")
    for grade in ordered_grades:
        total = total + grade["error_points"]
    return total


def accuracy_index(total_error_points, graded_play_count):
    """"An official with no plays in the included set reads exactly 100.00.
    Otherwise the index is 100.00 minus the quantity obtained by dividing
    `weighted_error_points` by `graded_play_count` and multiplying the quotient
    by an error scale of 20.00, with the final result rounded half up.\""""
    if graded_play_count == 0:
        return Decimal("100.00")
    quotient = total_error_points / Decimal(graded_play_count)
    return q2(Decimal("100.00") - quotient * ERROR_SCALE)


# --- crew strength (PRD 3.4) ----------------------------------------------

EXPERIENCE_CAP = 12
TIER_WEIGHT = {
    "TIER_1": Decimal("1.00"),
    "TIER_2": Decimal("0.80"),
    "TIER_3": Decimal("0.60"),
}
POSITION_WEIGHT = {
    "REFEREE": Decimal("1.30"),
    "UMPIRE": Decimal("1.00"),
    "DOWN_JUDGE": Decimal("0.85"),
}


def assignment_contribution(seasons_experience, tier, assignment_position):
    """"Each included assignment contributes points equal to the lesser of 12
    and its official's `seasons_experience`, multiplied by a tier weight ...
    multiplied again by a position weight ... where the position weight is read
    from the assignment's `position`, not from the official's registered
    position -- and the product is rounded half up to two decimal places.\""""
    capped = min(EXPERIENCE_CAP, seasons_experience)
    return q2(Decimal(capped) * TIER_WEIGHT[tier] * POSITION_WEIGHT[assignment_position])


def crew_strength_index(contributions, crew_size_required):
    """"the sum of those already-rounded contributions, taken in `created_at`
    ascending order, divided by the program's `crew_size_required`, and rounded
    half up to two decimal places. The divisor is the required crew size, never
    the number of included assignments." An empty included set yields 0.00."""
    if not contributions:
        return Decimal("0.00")
    total = Decimal("0.00")
    for value in contributions:
        total = total + value
    return q2(total / Decimal(crew_size_required))


# --- field evaluation (PRD 3.3) -------------------------------------------

W_MECHANICS = Decimal("0.40")
W_RULES = Decimal("0.35")
W_PRESENCE = Decimal("0.25")
MIN_EVALUATIONS = 2
MIN_EVAL_AVERAGE = Decimal("75.00")


def composite_score(mechanics_score, rules_score, presence_score):
    """"40 percent of the mechanics score plus 35 percent of the rules score
    plus 25 percent of the presence score -- rounded half up to two decimal
    places.\""""
    return q2(mechanics_score * W_MECHANICS
              + rules_score * W_RULES
              + presence_score * W_PRESENCE)


def evaluation_average(ordered_composites):
    """"the mean of the already-rounded `composite_score` values of every report
    on that application, taken in `created_at` ascending order and rounded half
    up to two decimal places.\""""
    if not ordered_composites:
        return None
    total = Decimal("0.00")
    for value in ordered_composites:
        total = total + value
    return q2(total / Decimal(len(ordered_composites)))


# --- advancement criteria (PRD 3.3) ---------------------------------------

TIER_ORDER = {"TIER_3": 1, "TIER_2": 2, "TIER_1": 3}
MIN_EXPERIENCE_FOR_TIER = {"TIER_2": 5, "TIER_1": 8}
ADVANCEMENT_MIN_ACCURACY = Decimal("90.00")


# --- retention (PRD 3.9) --------------------------------------------------

W_ACCURACY = Decimal("0.70")
W_AVAILABILITY = Decimal("0.30")
BAND_HIGH_FLOOR = Decimal("90.00")
BAND_MID_FLOOR = Decimal("80.00")
PENALTY_HIGH = Decimal("2.00")
PENALTY_MID = Decimal("5.00")
PENALTY_LOW = Decimal("9.00")
RETAIN_FLOOR = Decimal("90.00")
DEVELOP_FLOOR = Decimal("75.00")
SCORE_FLOOR = Decimal("0.00")


def availability_component(completed_count, obligated_count):
    """"100.00 multiplied by the completed count, divided by the greater of 1
    and the obligation total, rounded half up to two decimal places.\""""
    divisor = max(1, obligated_count)
    return q2(Decimal("100.00") * Decimal(completed_count) / Decimal(divisor))


def retention_score(accuracy, availability, deficiency_count):
    """Three stages. Stage one is the raw composite. Stage two selects a penalty
    rate FROM THAT RAW COMPOSITE, before any penalty is applied. Stage three
    subtracts rate * deficiency count from the raw composite, rounds, and clamps
    at a floor of exactly 0.00."""
    raw_score = q2(accuracy * W_ACCURACY + availability * W_AVAILABILITY)
    if raw_score >= BAND_HIGH_FLOOR:
        penalty_rate = PENALTY_HIGH
    elif raw_score >= BAND_MID_FLOOR:
        penalty_rate = PENALTY_MID
    else:
        penalty_rate = PENALTY_LOW
    score = q2(raw_score - penalty_rate * Decimal(deficiency_count))
    if score < SCORE_FLOOR:
        score = SCORE_FLOOR
    return score


def retention_recommendation(score):
    """"`RETAIN` when >= 90.00, `DEVELOP` when >= 75.00, and `RELEASE`
    otherwise.\""""
    if score >= RETAIN_FLOOR:
        return "RETAIN"
    if score >= DEVELOP_FLOOR:
        return "DEVELOP"
    return "RELEASE"


# --- intervals (PRD 3.4, 3.5) ---------------------------------------------

GAME_DURATION_HOURS = 4


def occupancy_window(kickoff_utc, travel_lead_hours, min_rest_hours_between_games):
    """"`occupied_from_utc` is the game's `kickoff_utc` moved earlier by the
    program's `travel_lead_hours`. `occupied_until_utc` is the game's
    `kickoff_utc` moved later by four hours of game duration and then further by
    the program's `min_rest_hours_between_games`.\""""
    occupied_from = kickoff_utc - timedelta(hours=travel_lead_hours)
    occupied_until = (kickoff_utc
                      + timedelta(hours=GAME_DURATION_HOURS)
                      + timedelta(hours=min_rest_hours_between_games))
    return occupied_from, occupied_until


def windows_conflict(new_from, new_until, existing_from, existing_until):
    """Half-open [from, until): "Two windows conflict when the new window's
    start is strictly earlier than the existing window's end and the existing
    window's start is strictly earlier than the new window's end. Exact
    adjacency does not conflict.\""""
    return new_from < existing_until and existing_from < new_until


def review_windows_conflict(new_open, new_close, existing_open, existing_close):
    """Closed [open, close]: "two review windows conflict when the new window's
    open instant is at or before the existing window's close instant and the
    existing window's open instant is at or before the new window's close
    instant. Touching endpoints therefore do conflict here.\""""
    return new_open <= existing_close and existing_open <= new_close


def elapsed_whole_seconds(start, end):
    """Interval and elapsed-time arithmetic is done in whole seconds of UTC."""
    return int((end - start).total_seconds())
