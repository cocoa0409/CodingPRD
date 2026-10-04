"""Calculations (SCAFFOLD calculations table, PRD 3.4-3.9).

Every monetary result is an integer number of cents; intermediate counts
(rolls, hours, percentages, scores) are floored before use.  Money is never
computed with float; Decimal with ROUND_HALF_UP is used wherever a division or
a rate produces a monetary result.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from . import clock, store

# --- constants pinned by the scaffold -------------------------------------
VARIANCE_TOLERANCE_CENTS = 500
ASSET_DEDUCTION_CENTS = 150000
INCOME_DIVISOR_CENTS = 20000
ELIGIBILITY_THRESHOLD = 65

MIN_RATED_HOURS = 8
BRONZE_MAX_CENTS_PER_HOUR = 4000
SILVER_MAX_CENTS_PER_HOUR = 8000
GOLD_MAX_CENTS_PER_HOUR = 12000
DEMOTION_INDEX_FLOOR = 2000

ROLL_QUARTER_CENTS = 1000
ROLL_DIME_CENTS = 500
ROLL_NICKEL_CENTS = 200
ROLL_PENNY_CENTS = 50
FEE_MILLS_PER_ROLL = 12
CURRENCY_FEE_PER_MILLE = 5
CHECK_FEE_PER_MILLE = 8

OVERTIME_AFTER_MINUTES = 420
OVERTIME_MULTIPLIER = Decimal("1.5")
MAX_SHIFT_MINUTES = 480

BASE_SCORE = 100
COMPLETED_DELTA = 1
LATE_CANCEL_DELTA = -5
NO_SHOW_DELTA = -15
SCORE_FLOOR = 0
SCORE_CEILING = 100
SUSPENSION_THRESHOLD = 60

MIN_LIFT_CENTS = 0
REST_BUFFER_MINUTES = 30
UNDERSTAFFED_THRESHOLD_PCT = 80
MAX_DIGITAL_GIFT_CENTS = 500000
MINOR_CURFEW_HOUR_LOCAL = 20

DAILY_RATE_CENTS = {
    "TYPE_1": 95000,
    "TYPE_2": 72000,
    "TYPE_3": 48000,
    "TYPE_4": 30000,
    "TYPE_5": 18000,
}
REGULAR_DAY_LIMIT = 14
SURGE_MULTIPLIER = Decimal("0.6")

TIER_LADDER = ["UNRATED", "BRONZE", "SILVER", "GOLD", "PLATINUM"]

COUNTED_DEPOSIT_STATUSES = ("DEPOSITED", "RECONCILED")
COUNTED_ATTRIBUTION_STATUSES = ("ATTRIBUTED",)


def clamp(value, low, high):
    return max(low, min(high, value))


def round_half_up(value, places=0):
    """Round half up; returns int when places == 0."""
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    out = dec.quantize(quant, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(out)
    return out


def minutes_between(start, end):
    """Whole minutes between two instants (exact, may be fractional)."""
    return (end - start).total_seconds() / 60.0


def shift_duration_minutes(shift):
    start = clock.parse(shift.get("starts_at"))
    end = clock.parse(shift.get("ends_at"))
    if start is None or end is None:
        return 0
    return minutes_between(start, end)


def shift_duration_hours(shift):
    return shift_duration_minutes(shift) / 60.0


# --- kettle_collection_variance (dual variant) -----------------------------
def counted_total(collection):
    return int(collection.get("coin_cents", 0) or 0) + int(collection.get("currency_cents", 0) or 0) + int(
        collection.get("check_cents", 0) or 0
    )


def provisional_variance(collection):
    """counted_total_cents - declared_cents (exact integer cents)."""
    return counted_total(collection) - int(collection.get("declared_cents", 0) or 0)


def final_variance(collection):
    """deposited_cents - (counted_total_cents - handling_fee_cents)."""
    return int(collection.get("deposited_cents", 0) or 0) - (
        counted_total(collection) - int(collection.get("handling_fee_cents", 0) or 0)
    )


# --- deposit_denomination_split (aggregation) ------------------------------
def handling_fee_cents(coin_cents, currency_cents, check_cents):
    """Per-denomination fees floored individually, then summed (never re-rounded)."""
    coin = int(coin_cents or 0)
    currency = int(currency_cents or 0)
    check = int(check_cents or 0)

    quarters = (coin * 40) // 100
    dimes = (coin * 30) // 100
    nickels = (coin * 20) // 100
    pennies = coin - quarters - dimes - nickels

    fee_q = ((quarters // ROLL_QUARTER_CENTS) * FEE_MILLS_PER_ROLL) // 10
    fee_d = ((dimes // ROLL_DIME_CENTS) * FEE_MILLS_PER_ROLL) // 10
    fee_n = ((nickels // ROLL_NICKEL_CENTS) * FEE_MILLS_PER_ROLL) // 10
    fee_p = ((pennies // ROLL_PENNY_CENTS) * FEE_MILLS_PER_ROLL) // 10
    fee_currency = (currency * CURRENCY_FEE_PER_MILLE) // 1000
    fee_check = (check * CHECK_FEE_PER_MILLE) // 1000
    return fee_q + fee_d + fee_n + fee_p + fee_currency + fee_check


# --- shift_paid_amount (threshold) -----------------------------------------
def shift_paid_amount(shift, hourly_rate_cents):
    duration = shift_duration_minutes(shift)
    if duration < 0:
        duration = 0
    paid_minutes = max(0, duration - int(shift.get("break_minutes", 0) or 0))
    base_minutes = min(paid_minutes, OVERTIME_AFTER_MINUTES)
    overtime_minutes = max(0, paid_minutes - OVERTIME_AFTER_MINUTES)

    paid_hours = round_half_up(Decimal(str(paid_minutes)) / Decimal(60), 2)
    rate = Decimal(int(hourly_rate_cents or 0))
    amount = (Decimal(str(base_minutes)) / Decimal(60)) * rate + (
        Decimal(str(overtime_minutes)) / Decimal(60)
    ) * rate * OVERTIME_MULTIPLIER
    return float(paid_hours), round_half_up(amount, 0)


# --- assistance_eligibility_score (dual variant) ---------------------------
def provisional_score(annual_income_cents, household_size):
    size = max(1, int(household_size or 1))
    per_member = int(annual_income_cents or 0) // size
    return clamp(100 - (per_member // INCOME_DIVISOR_CENTS), 0, 100)


def eligibility_score(verified_income_cents, household_size):
    size = max(1, int(household_size or 1))
    adjusted = max(0, int(verified_income_cents or 0) - (ASSET_DEDUCTION_CENTS * size))
    per_member = adjusted // size
    return clamp(100 - (per_member // INCOME_DIVISOR_CENTS), 0, 100)


# --- campaign_total_raised (aggregation) -----------------------------------
def location_total_cents(location_id):
    total = 0
    for collection in store.rows("kettle_collections"):
        if collection.get("kettle_location_id") != location_id:
            continue
        if collection.get("deposit_status") in COUNTED_DEPOSIT_STATUSES:
            total += int(collection.get("counted_total_cents", 0) or 0)
    for gift in store.rows("digital_givings"):
        if gift.get("kettle_location_id") != location_id:
            continue
        if gift.get("attribution_status") in COUNTED_ATTRIBUTION_STATUSES:
            total += int(gift.get("attributed_cents", 0) or 0)
    return total


def campaign_components(campaign_id):
    location_ids = {
        loc["id"] for loc in store.rows("kettle_locations") if loc.get("campaign_id") == campaign_id
    }
    collections_total = 0
    for collection in store.rows("kettle_collections"):
        if collection.get("kettle_location_id") in location_ids and collection.get(
            "deposit_status"
        ) in COUNTED_DEPOSIT_STATUSES:
            collections_total += int(collection.get("counted_total_cents", 0) or 0)
    digital_total = 0
    for gift in store.rows("digital_givings"):
        if gift.get("campaign_id") == campaign_id and gift.get("attribution_status") in (
            COUNTED_ATTRIBUTION_STATUSES
        ):
            digital_total += int(gift.get("attributed_cents", 0) or 0)
    return collections_total, digital_total


def campaign_total_raised(campaign_id):
    collections_total, digital_total = campaign_components(campaign_id)
    return collections_total + digital_total


# --- location_performance_index (threshold) --------------------------------
def location_shift_counts(location_id):
    completed = 0
    cancelled = 0
    no_show = 0
    covered_minutes = 0
    for shift in store.rows("shifts"):
        if shift.get("kettle_location_id") != location_id:
            continue
        status = shift.get("status")
        if status == "COMPLETED":
            completed += 1
            covered_minutes += int(round(shift_duration_minutes(shift)))
        elif status == "CANCELLED":
            cancelled += 1
        elif status == "NO_SHOW":
            no_show += 1
    return completed, cancelled, no_show, covered_minutes


def tier_from_cents_per_hour(cents_per_hour):
    if cents_per_hour < BRONZE_MAX_CENTS_PER_HOUR:
        return "BRONZE"
    if cents_per_hour < SILVER_MAX_CENTS_PER_HOUR:
        return "SILVER"
    if cents_per_hour < GOLD_MAX_CENTS_PER_HOUR:
        return "GOLD"
    return "PLATINUM"


def demote_tier(tier):
    if tier not in TIER_LADDER:
        return tier
    index = TIER_LADDER.index(tier)
    return TIER_LADDER[max(0, index - 1)]


def performance_snapshot(location_id):
    """Compute cents_per_hour, performance_index and tier for one location."""
    completed, cancelled, no_show, covered_minutes = location_shift_counts(location_id)
    total = location_total_cents(location_id)
    covered_hours = covered_minutes // 60
    cents_per_hour = total // max(covered_hours, 1)

    disruption_count = cancelled + no_show
    denominator = max(completed + disruption_count, 1)
    disruption_rate_pct = (100 * disruption_count) // denominator
    performance_index = (cents_per_hour * (100 - disruption_rate_pct)) // 100

    if covered_hours < MIN_RATED_HOURS:
        tier = "UNRATED"
    else:
        tier = tier_from_cents_per_hour(cents_per_hour)
        if performance_index < DEMOTION_INDEX_FLOOR:
            tier = demote_tier(tier)

    return {
        "covered_minutes": covered_minutes,
        "covered_hours": covered_hours,
        "location_total_cents": total,
        "cents_per_hour": cents_per_hour,
        "performance_index": performance_index,
        "disruption_rate_pct": disruption_rate_pct,
        "performance_tier": tier,
    }


def recompute_location(location):
    """Recompute and store a location's derived figures (a mutation)."""
    snap = performance_snapshot(location["id"])
    location["covered_minutes"] = snap["covered_minutes"]
    location["location_total_cents"] = snap["location_total_cents"]
    location["cents_per_hour"] = snap["cents_per_hour"]
    location["performance_tier"] = snap["performance_tier"]
    store.touch(location)
    return snap


def apply_variance_demotion(location):
    """A VARIANCE_HOLD collection downgrades the location one tier step."""
    current = location.get("performance_tier") or "UNRATED"
    location["performance_tier"] = demote_tier(current)
    store.touch(location)


def location_remaining_scheduled_hours(location_id):
    total_minutes = 0.0
    for shift in store.rows("shifts"):
        if shift.get("kettle_location_id") != location_id:
            continue
        if shift.get("status") in ("SCHEDULED", "CONFIRMED"):
            total_minutes += shift_duration_minutes(shift)
    return total_minutes / 60.0


def coverage_for_date(location, on_date):
    """shift_coverage_gap: COMPLETED shifts only, on the evaluated date."""
    required = max(int(location.get("daily_required_minutes", 0) or 0), 1)
    covered = 0
    for shift in store.rows("shifts"):
        if shift.get("kettle_location_id") != location["id"]:
            continue
        if shift.get("status") != "COMPLETED":
            continue
        start = clock.parse(shift.get("starts_at"))
        if start is None or start.date() != on_date:
            continue
        covered += int(round(shift_duration_minutes(shift)))
    coverage_pct = (100 * covered) // required
    return covered, coverage_pct, coverage_pct < UNDERSTAFFED_THRESHOLD_PCT


# --- bell_ringer_reliability_score (weighted scoring) ----------------------
def reliability_snapshot(ringer_id):
    completed = 0
    late_cancels = 0
    no_shows = 0
    for shift in store.rows("shifts"):
        if shift.get("bell_ringer_id") != ringer_id:
            continue
        status = shift.get("status")
        if status == "COMPLETED":
            completed += 1
        elif status == "CANCELLED" and shift.get("_prev_status") == "CONFIRMED":
            late_cancels += 1
        elif status == "NO_SHOW":
            no_shows += 1
    score = BASE_SCORE + completed * COMPLETED_DELTA + late_cancels * LATE_CANCEL_DELTA + no_shows * NO_SHOW_DELTA
    return clamp(score, SCORE_FLOOR, SCORE_CEILING), completed, late_cancels, no_shows


def recompute_reliability(ringer):
    score, _c, _l, _n = reliability_snapshot(ringer["id"])
    ringer["reliability_score"] = score
    store.touch(ringer)
    return score


def recompute_scheduled_hours(ringer):
    total_minutes = 0.0
    for shift in store.rows("shifts"):
        if shift.get("bell_ringer_id") != ringer["id"]:
            continue
        if shift.get("status") in ("SCHEDULED", "CONFIRMED"):
            total_minutes += shift_duration_minutes(shift)
    ringer["scheduled_hours"] = float(round_half_up(Decimal(str(total_minutes)) / Decimal(60), 2))
    store.touch(ringer)
    return ringer["scheduled_hours"]


# --- canteen_deployment_cost (tiered pricing) ------------------------------
def deployment_cost(deployment):
    status = deployment.get("status")
    if status in ("DENIED", "CANCELLED"):
        return 0
    deployed_at = clock.parse(deployment.get("deployed_at"))
    if deployed_at is None:
        return 0
    demobilized_at = clock.parse(deployment.get("demobilized_at"))
    end = demobilized_at if demobilized_at is not None else clock.now()
    seconds = (end - deployed_at).total_seconds()
    if seconds <= 0:
        billed_days = 0
    else:
        billed_days = int(math.ceil(seconds / 86400.0))
    base_rate = DAILY_RATE_CENTS.get(deployment.get("incident_command_level"), 0)
    regular_days = min(billed_days, REGULAR_DAY_LIMIT)
    surge_days = max(0, billed_days - REGULAR_DAY_LIMIT)
    per_canteen = Decimal(regular_days) * Decimal(base_rate) + Decimal(surge_days) * Decimal(
        base_rate
    ) * SURGE_MULTIPLIER
    assigned = int(deployment.get("assigned_canteen_count", 0) or 0)
    return round_half_up(Decimal(assigned) * per_canteen, 0)


# --- reallocation_expected_lift (combinatorial) ----------------------------
def expected_lift(moved_hours, source_cents_per_hour, target_cents_per_hour):
    diff = max(MIN_LIFT_CENTS, int(target_cents_per_hour) - int(source_cents_per_hour))
    return round_half_up(Decimal(str(moved_hours)) * Decimal(diff), 0)


# --- program_capacity_allocation (waterfall) -------------------------------
def enrollment_order(entries):
    return sorted(entries, key=lambda e: (e.get("enrolled_at") or "", e.get("participant_name") or ""))


def enrollment_counts(program):
    entries = enrollment_order(program.get("enrollment_log") or [])
    capacity = int(program.get("capacity", 0) or 0)
    return min(len(entries), capacity), max(0, len(entries) - capacity)


# --- selector: digital_giving_attribution_selector -------------------------
def select_attribution_location(campaign_id):
    candidates = []
    for location in store.rows("kettle_locations"):
        if location.get("campaign_id") != campaign_id or location.get("status") != "ACTIVE":
            continue
        site = store.find("host_sites", location.get("host_site_id"))
        if site is None or site.get("permission_status") != "APPROVED":
            continue
        candidates.append(location)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (-int(r.get("covered_minutes", 0) or 0), r.get("created_at") or "", r.get("_seq", 0)))
    return candidates[0]


# --- selector: shift_auto_assign_selector ----------------------------------
def _intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _gap_minutes(a_start, a_end, b_start, b_end):
    if _intervals_overlap(a_start, a_end, b_start, b_end):
        return None
    if a_end <= b_start:
        return (b_start - a_end).total_seconds() / 60.0
    return (a_start - b_end).total_seconds() / 60.0


def select_auto_assign_ringer(starts_at, ends_at):
    candidates = []
    for ringer in store.rows("bell_ringers"):
        if ringer.get("engagement_status") != "ACTIVE":
            continue
        if ringer.get("screening_status") != "CLEARED":
            continue
        expires = clock.parse(ringer.get("screening_expires_at"))
        if expires is None or expires <= starts_at:
            continue
        blocked = False
        for shift in store.rows("shifts"):
            if shift.get("bell_ringer_id") != ringer["id"]:
                continue
            status = shift.get("status")
            if status not in ("SCHEDULED", "CONFIRMED", "CHECKED_IN"):
                continue
            s = clock.parse(shift.get("starts_at"))
            e = clock.parse(shift.get("ends_at"))
            if s is None or e is None:
                continue
            if _intervals_overlap(starts_at, ends_at, s, e):
                blocked = True
                break
            gap = _gap_minutes(starts_at, ends_at, s, e)
            if gap is not None and gap < REST_BUFFER_MINUTES:
                blocked = True
                break
        if blocked:
            continue
        candidates.append(ringer)
    if not candidates:
        return None
    candidates.sort(
        key=lambda r: (
            -int(r.get("reliability_score", 0) or 0),
            float(r.get("scheduled_hours", 0) or 0),
            r.get("created_at") or "",
            r.get("_seq", 0),
        )
    )
    return candidates[0]
