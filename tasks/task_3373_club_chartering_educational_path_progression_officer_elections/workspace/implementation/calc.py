"""Calculation rules.

Every constant and ordering below is pinned by SCAFFOLD.yaml section 1.3 and by
the matching prose in PRD sections 2.7, 2.9, 3.2, 3.4, 3.6, 3.8 and 3.9.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- dues quote constants ---------------------------------------------------
INTL_DUES_CENTS = Decimal("4500")
DISTRICT_LEVY_RATE = Decimal("1.075")
NEW_MEMBER_FEE_CENTS = Decimal("2000")
REINSTATEMENT_FEE_CENTS = Decimal("1000")
LATE_FEE_RATE = Decimal("0.05")
CYCLE_HALF_DAYS = 91

# --- standing score constants ----------------------------------------------
WEIGHT_DUES = 30
WEIGHT_OFFICER = 25
WEIGHT_EDUCATION = 20
WEIGHT_MEETING = 15
WEIGHT_DCP = 10
REQUIRED_MEMBER_COUNT = 20
OFFICER_TRAINED_TARGET = 4
EDUCATION_TARGET = 4
MEETINGS_TARGET = 6
DCP_TARGET = 5
GOOD_MIN = 80
PROBATION_MIN = 60
REVOKE_BELOW = 40

# --- dcp constants ----------------------------------------------------------
EDUCATION_POINT_CAP = 6
MEMBER_PER_MEMBERSHIP_CAP = 2
PRESIDENT_TIER_MIN = 9
SELECT_TIER_MIN = 7
DISTINGUISHED_TIER_MIN = 5

# --- meeting / rotation constants ------------------------------------------
BUFFER_MINUTES = 30
DEFAULT_DURATION_MINUTES = 90
WINDOW_DAYS = 7
MAX_SPEECH_ROLES = 2
REQUIRED_ROLE_SLOTS = 7

# --- education constants ----------------------------------------------------
LEVEL_ORDER = ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4", "LEVEL_5", "COMPLETED"]
LEVEL_REQUIREMENTS = {
    "LEVEL_1": (2, 2),
    "LEVEL_2": (1, 2),
    "LEVEL_3": (1, 2),
    "LEVEL_4": (1, 1),
    "LEVEL_5": (1, 1),
}
MAX_PROJECTS_PER_LEVEL = 6

# --- ballot constants -------------------------------------------------------
CONTENT_WEIGHT = Decimal("0.5")
DELIVERY_WEIGHT = Decimal("0.3")
LANGUAGE_WEIGHT = Decimal("0.2")
BALLOTS_REQUIRED = 3


def round_half_up_int(value):
    """Round a Decimal to the nearest whole unit, halves away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _half(value):
    return value / Decimal("2")


# --- dues quote -------------------------------------------------------------
def dues_quote_total_cents(membership, club):
    """The single dues quote, assembled and rounded in the pinned order.

    Each of the five lines is rounded to the nearest cent with round half up
    BEFORE the sum is taken (PRD section 2.9 / section 3.2).  For a first-time
    member who has never paid at a club whose club_dues_cents is 2999 this
    yields 10062, whereas sum-then-round yields 10061.
    """
    intl_line = INTL_DUES_CENTS * DISTRICT_LEVY_RATE
    club_line = Decimal(club["club_dues_cents"]) * DISTRICT_LEVY_RATE

    cycle_opened_at = club.get("cycle_opened_at")
    join_date = membership.get("join_date")
    if cycle_opened_at is not None and join_date is not None:
        if join_date >= cycle_opened_at + timedelta(days=CYCLE_HALF_DAYS):
            intl_line = _half(intl_line)
            club_line = _half(club_line)

    if membership.get("status") == "LAPSED":
        # reinstatement variant: the new-member line is forced to 0
        new_member_line = Decimal("0")
        reinstatement_line = REINSTATEMENT_FEE_CENTS
    else:
        if (
            membership.get("first_time_member")
            and membership.get("dues_paid_through_cycle") == -1
        ):
            new_member_line = NEW_MEMBER_FEE_CENTS
        else:
            new_member_line = Decimal("0")
        reinstatement_line = Decimal("0")

    if membership.get("dues_status") == "OVERDUE":
        late_line = LATE_FEE_RATE * (
            intl_line + club_line + new_member_line + reinstatement_line
        )
    else:
        late_line = Decimal("0")

    return (
        round_half_up_int(intl_line)
        + round_half_up_int(club_line)
        + round_half_up_int(new_member_line)
        + round_half_up_int(reinstatement_line)
        + round_half_up_int(late_line)
    )


# --- good standing score ----------------------------------------------------
def score_from_counts(
    paid_member_count,
    officer_trained_count,
    approved_level_completions_this_cycle,
    meetings_held_this_cycle,
    dcp_points,
):
    """Five capped components, each truncated to a whole number before summing."""
    dues_points = min(
        WEIGHT_DUES, (WEIGHT_DUES * paid_member_count) // REQUIRED_MEMBER_COUNT
    )
    officer_points = min(
        WEIGHT_OFFICER, (WEIGHT_OFFICER * officer_trained_count) // OFFICER_TRAINED_TARGET
    )
    education_points = min(
        WEIGHT_EDUCATION,
        (WEIGHT_EDUCATION * approved_level_completions_this_cycle) // EDUCATION_TARGET,
    )
    meeting_points = min(
        WEIGHT_MEETING, (WEIGHT_MEETING * meetings_held_this_cycle) // MEETINGS_TARGET
    )
    dcp_points_component = min(WEIGHT_DCP, (WEIGHT_DCP * dcp_points) // DCP_TARGET)
    return (
        dues_points
        + officer_points
        + education_points
        + meeting_points
        + dcp_points_component
    )


def posture_from_score(score):
    if score >= GOOD_MIN:
        return "GOOD"
    if score >= PROBATION_MIN:
        return "PROBATION"
    return "NOT_IN_GOOD_STANDING"


# --- dcp recognition points -------------------------------------------------
def dcp_points_from_parts(
    education_points,
    new_member_count_this_cycle,
    paid_member_count,
    officer_trained_count,
    contest_participation_count,
    cycle_open_standing,
):
    """The ten-point aggregate; evaluated before good_standing_score."""
    education = min(EDUCATION_POINT_CAP, education_points)
    membership_points = min(1, new_member_count_this_cycle // 4) + min(
        1, paid_member_count // REQUIRED_MEMBER_COUNT
    )
    training_points = min(1, officer_trained_count // OFFICER_TRAINED_TARGET)
    admin_points = (
        (1 if officer_trained_count == 7 else 0)
        + (1 if contest_participation_count >= 1 else 0)
        + (1 if cycle_open_standing == "GOOD" else 0)
    )
    return min(10, education + membership_points + training_points + admin_points)


def dcp_tier(points):
    if points >= PRESIDENT_TIER_MIN:
        return "PRESIDENT_DISTINGUISHED"
    if points >= SELECT_TIER_MIN:
        return "SELECT_DISTINGUISHED"
    if points >= DISTINGUISHED_TIER_MIN:
        return "DISTINGUISHED"
    return "NONE"


# --- education levels -------------------------------------------------------
def level_requirement(level):
    return LEVEL_REQUIREMENTS.get(level, (1, 1))


def path_level_number(level):
    """ProjectCompletion.level is an integer 1..5; path.level is an enum string."""
    if level in ("LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4", "LEVEL_5"):
        return int(level.split("_")[1])
    return None


def next_level(level):
    index = LEVEL_ORDER.index(level)
    if index >= len(LEVEL_ORDER) - 1:
        return None
    return LEVEL_ORDER[index + 1]


def previous_level(level):
    """One step down; LEVEL_1 and COMPLETED have no drop transition."""
    if level in ("LEVEL_1", "COMPLETED"):
        return None
    index = LEVEL_ORDER.index(level)
    return LEVEL_ORDER[index - 1]


# --- meetings ---------------------------------------------------------------
def meeting_overlaps(candidate_start, candidate_duration, existing_start, existing_duration):
    """Half-open intersection plus the one-sided 30-minute leading buffer."""
    candidate_end = candidate_start + timedelta(minutes=candidate_duration)
    existing_end = existing_start + timedelta(minutes=existing_duration)
    if existing_start < candidate_end and candidate_start < existing_end:
        return True
    gap = (candidate_start - existing_end).total_seconds() / 60.0
    if 0 <= gap < BUFFER_MINUTES:
        return True
    return False


def speech_roles_in_window(assignments, member_id, meeting_start):
    """Count SPEECH assignments of this member in [start-7d, start+7d]."""
    window_start = meeting_start - timedelta(days=WINDOW_DAYS)
    window_end = meeting_start + timedelta(days=WINDOW_DAYS)
    count = 0
    for assignment in assignments:
        if assignment["member_id"] != member_id:
            continue
        if assignment.get("role_class") != "SPEECH":
            continue
        if assignment.get("status") not in ("ASSIGNED", "COMPLETED", "NO_SHOW"):
            continue
        when = assignment.get("_meeting_scheduled_at")
        if when is None:
            continue
        if window_start <= when <= window_end:
            count += 1
    return count


# --- ballots and ranking ----------------------------------------------------
def ballot_total(content_score, delivery_score, language_score):
    blended = (
        Decimal(content_score) * CONTENT_WEIGHT
        + Decimal(delivery_score) * DELIVERY_WEIGHT
        + Decimal(language_score) * LANGUAGE_WEIGHT
    )
    return round_half_up_int(blended)


def rank_entries(entries):
    """judge_score_total descending, ties broken by created_at ascending."""
    return sorted(entries, key=lambda e: (-e["judge_score_total"], e["created_at"]))


# --- coaching queue ---------------------------------------------------------
QUEUE_LIMIT = 100


def coaching_queue_rank(clubs):
    """good_standing_score asc, then paid_member_count asc, then created_at asc."""
    return sorted(
        clubs,
        key=lambda c: (
            c["good_standing_score"],
            c["paid_member_count"],
            c["created_at"],
        ),
    )
