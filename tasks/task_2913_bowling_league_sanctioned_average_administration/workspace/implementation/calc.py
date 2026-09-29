"""Calculations of PRD 3.6, 3.7, 3.3 and 3.8. Integers and Decimal only."""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

MIN_PRIOR_GAMES_FOR_CARRYOVER = 21

NATIONAL_FEE_ADULT_CENTS = 2600
NATIONAL_FEE_YOUTH_CENTS = 1200
LOCAL_ASSOCIATION_FEE_CENTS = 500
LATE_FILING_GRACE_DAYS = 21
LATE_PENALTY_CENTS = 1000

POINTS_PER_MATCH = 4

RESERVE_TIER_THRESHOLD_CENTS = 100000
RESERVE_PCT_HIGH = Decimal("0.08")
RESERVE_PCT_LOW = Decimal("0.05")
ADMIN_FEE_PCT = Decimal("0.03")

MAX_REVIEW_ROUNDS = 3

PROTEST_WINDOW_HOURS = 72
AWARD_WINDOW_HOURS = 168
TRAVEL_BUFFER_MINUTES = 30


def floor_int(dec):
    return int(Decimal(dec).to_integral_value(rounding=ROUND_FLOOR))


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def trunc_div(numerator, denominator):
    """Truncate toward zero; both operands are non-negative integers here."""
    if denominator == 0:
        return None
    return int(Decimal(numerator) / Decimal(denominator))


# --------------------------------------------------------- entering_average --
def entering_average(league, prior_season_average, prior_season_games):
    games = prior_season_games or 0
    if (
        prior_season_average is not None
        and games >= MIN_PRIOR_GAMES_FOR_CARRYOVER
        and league.get("carryover_policy") in ("PRIOR_SEASON_FULL", "BLENDED")
    ):
        return prior_season_average
    return None


# ----------------------------------------------------------- bowler_average --
def bowler_average(league, certified_games, certified_pins, entering_avg,
                   prior_season_games):
    """Returns (average_status, current_average)."""
    minimum = league.get("minimum_games_for_average")
    quotient = trunc_div(certified_pins, certified_games) if certified_games >= 1 else None
    if minimum is not None and certified_games >= minimum:
        return "ESTABLISHED", quotient
    policy = league.get("carryover_policy")
    if policy == "PRIOR_SEASON_FULL":
        if entering_avg is not None:
            return "PROVISIONAL", entering_avg
        return "PROVISIONAL", quotient
    if policy == "BLENDED":
        if entering_avg is not None:
            games = prior_season_games or 0
            total = entering_avg * games + certified_pins
            denominator = games + certified_games
            if denominator == 0:
                return "PROVISIONAL", None
            return "PROVISIONAL", trunc_div(total, denominator)
        return "PROVISIONAL", quotient
    # carryover_policy NONE, or no bylaws adopted yet
    return "PROVISIONAL", quotient


# ---------------------------------------------------------- bowler_handicap --
def percentage_for(league, member_class):
    if member_class == "YOUTH":
        return league.get("handicap_percentage_youth")
    return league.get("handicap_percentage")


def basis_average(league, entering_avg, current_avg):
    if league.get("handicap_average_basis") == "ENTERING":
        return entering_avg
    if league.get("handicap_average_basis") == "CURRENT":
        return current_avg if current_avg is not None else entering_avg
    return None


def capped_handicap(league, basis, pct):
    """floor(max(0, handicap_base - basis) * pct) then the ceiling."""
    base = league.get("handicap_base")
    ceiling = league.get("max_handicap_per_game")
    if base is None or ceiling is None or pct is None or basis is None:
        return 0
    difference = base - basis
    if difference < 0:
        difference = 0
    floored = floor_int(Decimal(difference) * Decimal(pct))
    return min(ceiling, floored)


def bowler_handicap(league, sanction_status, entering_avg, current_avg, member_class):
    if sanction_status != "SANCTIONED":
        return 0
    basis = basis_average(league, entering_avg, current_avg)
    if basis is None:
        return 0
    return capped_handicap(league, basis, percentage_for(league, member_class))


def vacancy_handicap(league):
    return capped_handicap(league, league.get("vacancy_average"),
                           league.get("handicap_percentage"))


def absentee_handicap(league, entering_avg, current_avg, member_class):
    basis = basis_average(league, entering_avg, current_avg)
    if basis is None:
        return 0
    deduction = league.get("absentee_deduction") or 0
    penalised = basis - deduction
    if penalised < 0:
        penalised = 0
    return capped_handicap(league, penalised, percentage_for(league, member_class))


# -------------------------------------------------------- remittance_amount --
def remittance_pricing(elapsed_days, member_classes):
    """member_classes is the ordered list of each listed membership's class."""
    penalty_per_member = (
        LATE_PENALTY_CENTS if elapsed_days > LATE_FILING_GRACE_DAYS else 0
    )
    member_count = len(member_classes)
    penalty_cents = member_count * penalty_per_member
    total = penalty_cents
    for member_class in member_classes:
        national = (
            NATIONAL_FEE_ADULT_CENTS
            if member_class == "ADULT"
            else NATIONAL_FEE_YOUTH_CENTS
        )
        total += national + LOCAL_ASSOCIATION_FEE_CENTS
    return member_count, penalty_cents, total


# -------------------------------------------- prize waterfall and standings --
def waterfall(plan_basis_cents):
    """Returns (reserve_cents, admin_fee_cents, net_distributable_cents)."""
    pct = (
        RESERVE_PCT_HIGH
        if plan_basis_cents >= RESERVE_TIER_THRESHOLD_CENTS
        else RESERVE_PCT_LOW
    )
    reserve = floor_int(Decimal(plan_basis_cents) * pct)
    admin = round_half_up(Decimal(plan_basis_cents - reserve) * ADMIN_FEE_PCT)
    return reserve, admin, plan_basis_cents - reserve - admin


def place_amounts(net_distributable_cents, weights, place_count):
    raw = []
    for place in range(1, place_count + 1):
        weight = weights[place - 1]
        raw.append(floor_int(Decimal(net_distributable_cents) * Decimal(weight)))
    remainder = net_distributable_cents - sum(raw)
    index = 0
    while remainder > 0:
        raw[index % place_count] += 1
        remainder -= 1
        index += 1
    return raw
