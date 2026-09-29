"""The calculation catalogue (PRD sections 3.3, 3.5, 3.7, 3.8)."""
from decimal import Decimal

import num
from store import DB, order_key

# --- priority_point_score -------------------------------------------------
POINTS_PER_DOLLAR_UNIT_CENTS = Decimal(100000)
GIVING_TIER_1_CENTS = Decimal(2500000)
GIVING_TIER_2_CENTS = Decimal(10000000)
RATE_TIER_1 = Decimal("1.0")
RATE_TIER_2 = Decimal("1.5")
RATE_TIER_3 = Decimal("2.0")
LOYALTY_STREAK_THRESHOLD = 5
LOYALTY_MULTIPLIER = Decimal("1.10")
NO_LOYALTY_MULTIPLIER = Decimal("1.00")
STREAK_YEARS_CAP = 20
STREAK_POINTS_PER_YEAR = Decimal(5)
TENURE_SEASONS_CAP = 30
TENURE_POINTS_PER_SEASON = Decimal(3)
ALUMNI_BONUS = {
    "ALUMNUS": Decimal(25),
    "FACULTY_STAFF": Decimal(15),
    "STUDENT": Decimal(5),
    "NON_ALUMNUS": Decimal(0),
}
BONUS_STATUSES = ("ACTIVE", "LAPSED")

QUALIFYING_DESIGNATIONS = ("ATHLETICS_ANNUAL", "CAPITAL")
VARIANT_STATUSES = {
    "PROVISIONAL": ("PLEDGED", "RECEIVED"),
    "CERTIFIED": ("RECEIVED",),
}

# --- seat_requirement_amount / postseason_allocation_charge ---------------
RENEWAL_ESCALATOR = Decimal("1.03")
RENEWAL_CEILING_RATIO = Decimal("0.85")
HANDLING_TIER_1_CENTS = 50000
HANDLING_TIER_2_CENTS = 250000
HANDLING_RATE_LOW = Decimal("0.06")
HANDLING_RATE_MID = Decimal("0.04")
HANDLING_RATE_HIGH = Decimal("0.02")
FEE_EVENT_TYPES = ("POSTSEASON", "AWAY_GAME")

# --- reseating -----------------------------------------------------------
RESEATING_PRORATION_NUMERATOR = Decimal(7)
RESEATING_PRORATION_DENOMINATOR = Decimal(12)

# --- transfers -----------------------------------------------------------
TRANSFER_PCT_CAP_BY_BASIS = {
    "DEATH": Decimal("1.00"),
    "DIVORCE": Decimal("0.50"),
    "ENTITY_DISSOLUTION": Decimal("1.00"),
    "ENTITY_GIVING_REALIGNMENT": Decimal("0.25"),
}

# --- postures / analysis -------------------------------------------------
SOFT_POSTURE_RATIO = Decimal("0.30")
SOFT_ADJUSTMENT_RATIO = Decimal("0.90")
PREMIUM_ADJUSTMENT_RATIO = Decimal("1.10")
RETENTION_STREAK_FLOOR = 2

# --- holds / disputes ----------------------------------------------------
HOLD_MINUTES = 4320
INFO_REQUEST_ROUND_CAP = 2


# ---------------------------------------------------------------------------
# The annual priority-point formula
# ---------------------------------------------------------------------------
def input_set(donor, recalc, variant):
    """Gifts that a variant of this recalculation reads (PRD section 3.2)."""
    admitted = VARIANT_STATUSES[variant]
    cutoff = recalc["cutoff_date"]
    rows = []
    for gift in DB.gifts.values():
        if gift["donor_id"] != donor["id"]:
            continue
        if gift["gift_date"] > cutoff:
            continue
        if gift["designation"] not in QUALIFYING_DESIGNATIONS:
            continue
        if gift["gift_status"] not in admitted:
            continue
        rows.append(gift)
    return rows


def giving_component(qualifying_cents):
    """S1: three marginal bands, each at its own rate per $1,000."""
    total = Decimal(qualifying_cents)
    band1 = min(total, GIVING_TIER_1_CENTS)
    band2 = max(Decimal(0), min(total, GIVING_TIER_2_CENTS) - GIVING_TIER_1_CENTS)
    band3 = max(Decimal(0), total - GIVING_TIER_2_CENTS)
    raw = ((band1 / POINTS_PER_DOLLAR_UNIT_CENTS) * RATE_TIER_1
           + (band2 / POINTS_PER_DOLLAR_UNIT_CENTS) * RATE_TIER_2
           + (band3 / POINTS_PER_DOLLAR_UNIT_CENTS) * RATE_TIER_3)
    return num.round2(raw), band1, band2, band3


def streak_from_years(years, cycle_year):
    """The consecutive-giving streak: backwards walk with a single one-year grace."""
    year = int(cycle_year)
    if year not in years:
        year -= 1
    count = 0
    while year in years:
        count += 1
        year -= 1
    return count


def loyalty_multiplier(streak):
    if streak >= LOYALTY_STREAK_THRESHOLD:
        return LOYALTY_MULTIPLIER
    return NO_LOYALTY_MULTIPLIER


def alumni_bonus(donor):
    if donor["donor_status"] not in BONUS_STATUSES:
        return Decimal(0)
    return ALUMNI_BONUS.get(donor["alumni_status"], Decimal(0))


def score_variant(donor, recalc, variant):
    """Score one donor under one variant; returns every component figure."""
    gifts = input_set(donor, recalc, variant)
    qualifying_cents = sum(int(g["amount_cents"]) for g in gifts)
    years = set(int(g["cycle_year"]) for g in gifts)
    streak = streak_from_years(years, recalc["cycle_year"])
    s1, band1, band2, band3 = giving_component(qualifying_cents)
    mult = loyalty_multiplier(streak)
    s3 = num.round2(s1 * mult)
    capped_streak = min(streak, STREAK_YEARS_CAP)
    s4 = num.round2(Decimal(capped_streak) * STREAK_POINTS_PER_YEAR)
    seasons = int(donor.get("season_ticket_seasons_purchased") or 0)
    capped_seasons = min(seasons, TENURE_SEASONS_CAP)
    s5 = num.round2(Decimal(capped_seasons) * TENURE_POINTS_PER_SEASON)
    s6 = num.round2(alumni_bonus(donor))
    s7 = num.round2(num.dec(donor["transferred_points_in"])
                    - num.dec(donor["transferred_points_out"]))
    adjust = num.round2(donor["dispute_adjustment_points"])
    s8 = s3 + s4 + s5 + s6 + s7 + adjust
    s9 = num.floor_zero(num.round2(s8))
    base = num.round2(s3 + s4 + s5 + s6)
    return {
        "variant": variant,
        "qualifying_cents": qualifying_cents,
        "streak": streak,
        "seasons": seasons,
        "s1": s1,
        "band1": band1,
        "band2": band2,
        "band3": band3,
        "multiplier": mult,
        "s3": s3,
        "s4": s4,
        "s5": s5,
        "s6": s6,
        "s7": s7,
        "adjustment": adjust,
        "base": base,
        "total": s9,
    }


def certified_points_value(donor):
    """certified_points is derived, not stored independently (PRD section 3.3)."""
    raw = (num.dec(donor["certified_base_points"])
           + num.dec(donor["transferred_points_in"])
           - num.dec(donor["transferred_points_out"])
           + num.dec(donor["dispute_adjustment_points"]))
    return num.floor_zero(num.round2(raw))


# ---------------------------------------------------------------------------
# Ledger basis notes
# ---------------------------------------------------------------------------
def basis_notes(figures):
    """One human-readable derivation per formula component."""
    cents = figures["qualifying_cents"]
    return {
        "CUMULATIVE_GIVING": (
            "qualifying giving %d cents split marginally as %s / %s / %s cents at "
            "rates 1.0 / 1.5 / 2.0 per 100000 cents giving %s points, multiplied by "
            "the loyalty multiplier %s for a %d-year streak" % (
                cents, figures["band1"], figures["band2"], figures["band3"],
                figures["s1"], figures["multiplier"], figures["streak"])),
        "CONSECUTIVE_YEARS": (
            "streak of %d years capped at %d, times 5 points per year"
            % (figures["streak"], STREAK_YEARS_CAP)),
        "SEASON_TICKET_TENURE": (
            "%d season-ticket seasons purchased capped at %d, times 3 points per season"
            % (figures["seasons"], TENURE_SEASONS_CAP)),
        "ALUMNI_STATUS": "alumni bonus for the donor's alumni_status and donor_status",
        "NET_TRANSFER": "transferred_points_in minus transferred_points_out",
        "DISPUTE_ADJUSTMENT": "cumulative granted_points_delta from upheld disputes",
    }


def component_points(figures):
    return {
        "CUMULATIVE_GIVING": figures["s3"],
        "CONSECUTIVE_YEARS": figures["s4"],
        "SEASON_TICKET_TENURE": figures["s5"],
        "ALUMNI_STATUS": figures["s6"],
        "NET_TRANSFER": figures["s7"],
        "DISPUTE_ADJUSTMENT": figures["adjustment"],
    }


LEDGER_ENTRY_TYPES = (
    "CUMULATIVE_GIVING",
    "CONSECUTIVE_YEARS",
    "SEASON_TICKET_TENURE",
    "ALUMNI_STATUS",
    "NET_TRANSFER",
    "DISPUTE_ADJUSTMENT",
)


# ---------------------------------------------------------------------------
# Ranking (PRD section 3.5)
# ---------------------------------------------------------------------------
RANKABLE_STATUSES = ("ACTIVE", "LAPSED")


def rank_sort_key(donor):
    """certified_points DESC, cumulative_giving_cents DESC,
    consecutive_giving_years DESC, created_at ASC.  id is never an input."""
    return (
        -num.dec(donor["certified_points"]),
        -int(donor["cumulative_giving_cents"]),
        -int(donor["consecutive_giving_years"]),
        order_key(donor),
    )


def rank_pool_all():
    """The pool used at certification: every ACTIVE or LAPSED donor."""
    pool = [d for d in DB.donors.values() if d["donor_status"] in RANKABLE_STATUSES]
    return sorted(pool, key=rank_sort_key)


def holds_assigned_seat(donor_id):
    for row in DB.assignments.values():
        if row["donor_id"] == donor_id and row["occupancy_status"] == "ASSIGNED":
            return True
    return False


def event_pool(event):
    """The candidate pool for a selection event, already ranked."""
    floor = num.dec(event["eligible_donor_min_points"])
    pool = []
    for donor in DB.donors.values():
        if donor["donor_status"] not in RANKABLE_STATUSES:
            continue
        if num.dec(donor["certified_points"]) < floor:
            continue
        if event["event_type"] != "SEASON_TICKET" and not holds_assigned_seat(donor["id"]):
            continue
        pool.append(donor)
    return sorted(pool, key=rank_sort_key)


# ---------------------------------------------------------------------------
# Section posture and pricing (PRD section 3.7)
# ---------------------------------------------------------------------------
def underwater_ratio(underwater_seat_count, assigned_seat_count):
    divisor = assigned_seat_count if assigned_seat_count > 0 else 1
    return num.round4(Decimal(int(underwater_seat_count)) / Decimal(int(divisor)))


def pricing_posture(underwater_seat_count, assigned_seat_count, seats_available):
    ratio = underwater_ratio(underwater_seat_count, assigned_seat_count)
    if ratio >= SOFT_POSTURE_RATIO:
        return "SOFT"
    if ratio == 0 and int(seats_available) == 0:
        return "PREMIUM"
    return "NORMAL"


def recommended_requirement_cents(section):
    rate = section["per_seat_requirement_cents"]
    posture = section["pricing_posture"]
    if posture == "SOFT":
        return num.round_cents(Decimal(int(rate)) * SOFT_ADJUSTMENT_RATIO)
    if posture == "PREMIUM":
        return num.round_cents(Decimal(int(rate)) * PREMIUM_ADJUSTMENT_RATIO)
    return int(rate)


def grandfathered_rate(section, cycle_year):
    """The requirement_history rate for a cycle year, or None when absent."""
    for entry in section["requirement_history"]:
        if int(entry["cycle_year"]) == int(cycle_year):
            return int(entry["per_seat_requirement_cents"])
    return None


def seat_requirement_cents(section, pricing_mode, grandfathered, event_cycle_year,
                           first_occupied_cycle_year):
    """seat_requirement_amount: RENEWAL escalates and caps, MARKET pays the rate."""
    market = int(section["per_seat_requirement_cents"])
    if pricing_mode != "RENEWAL":
        return market
    years_held = int(event_cycle_year) - int(first_occupied_cycle_year)
    escalated = num.round_cents(
        Decimal(int(grandfathered)) * (RENEWAL_ESCALATOR ** years_held))
    ceiling = num.round_cents(Decimal(market) * RENEWAL_CEILING_RATIO)
    return min(escalated, ceiling)


def handling_fee_cents(requirement_cents, event_type):
    """postseason_allocation_charge; the band is keyed on requirement_cents alone."""
    if event_type not in FEE_EVENT_TYPES:
        return 0
    base = int(requirement_cents)
    if base < HANDLING_TIER_1_CENTS:
        rate = HANDLING_RATE_LOW
    elif base < HANDLING_TIER_2_CENTS:
        rate = HANDLING_RATE_MID
    else:
        rate = HANDLING_RATE_HIGH
    return num.round_cents(Decimal(base) * rate)


def reseating_share_cents(requirement_cents):
    """Seven twelfths of the row's requirement, rounded before it is summed."""
    return num.round_cents(Decimal(int(requirement_cents))
                           * RESEATING_PRORATION_NUMERATOR
                           / RESEATING_PRORATION_DENOMINATOR)


def transfer_pct_cap(basis):
    return TRANSFER_PCT_CAP_BY_BASIS[basis]


def max_transferable_points(source_donor, basis):
    cap = transfer_pct_cap(basis)
    return num.round2(num.dec(source_donor["certified_points"]) * cap)


def basis_precondition_holds(basis, source_donor, recipient_donor_id):
    if basis == "DEATH":
        return source_donor["donor_status"] == "DECEASED"
    if basis == "DIVORCE":
        return (source_donor["entity_type"] == "JOINT_HOUSEHOLD"
                and source_donor["household_partner_donor_id"] == recipient_donor_id)
    if basis == "ENTITY_DISSOLUTION":
        return source_donor["donor_status"] == "DISSOLVED_ENTITY"
    if basis == "ENTITY_GIVING_REALIGNMENT":
        return source_donor["entity_type"] in ("CORPORATION", "FOUNDATION")
    return False


# ---------------------------------------------------------------------------
# Retention analysis (PRD section 3.5)
# ---------------------------------------------------------------------------
def retention_analysis(recalc, donors):
    retained = 0
    new_donors = 0
    lapsed_risk = 0
    total_points = Decimal(0)
    for donor in donors:
        streak = int(donor["consecutive_giving_years"])
        if streak >= RETENTION_STREAK_FLOOR:
            retained += 1
        elif streak == 1:
            new_donors += 1
        elif streak == 0 and int(donor["cumulative_giving_cents"]) > 0:
            lapsed_risk += 1
        total_points += num.dec(donor["certified_points"])
    rate_divisor = retained + lapsed_risk
    if rate_divisor == 0:
        rate_divisor = 1
    rate = num.round4(Decimal(retained) / Decimal(rate_divisor))
    processed = int(recalc["donors_processed_count"])
    avg_divisor = processed if processed > 0 else 1
    average = num.round2(total_points / Decimal(avg_divisor))
    return {
        "cycle_year": int(recalc["cycle_year"]),
        "donors_processed_count": processed,
        "retained_donor_count": retained,
        "new_donor_count": new_donors,
        "lapsed_risk_donor_count": lapsed_risk,
        "retention_rate": num.ratio_out(rate),
        "average_certified_points": num.points_out(average),
        "certified_points_sum": num.points_out(recalc["certified_points_sum"]),
    }
