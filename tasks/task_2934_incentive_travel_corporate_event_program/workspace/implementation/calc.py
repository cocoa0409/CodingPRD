"""Every calculation rule from PRD 3.2 - 3.9.

Money is never touched with floats: all rate-driven results go through
decimal.Decimal with ROUND_HALF_UP unless the PRD names floor or ceil.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from store import add_days, day_span, parse_dt

# ------------------------------------------------------------------ constants
GUEST_SHARE_BP = 6250
GRATUITY_BP = 350

BUDGET_POSTURE_WATCH_BP = 8500
BUDGET_POSTURE_OVER_BP = 10000

FM_RELIEF_BP = {"NONE": 0, "STANDARD": 2500, "EXPANDED": 6000}

BUSINESS_PURPOSE_EXCLUSION_BP = 1500

FED_SUPPLEMENTAL_BP = 2200
FICA_BP = 765
STATE_TIER_LOW_BP = 300
STATE_TIER_MID_BP = 500
STATE_TIER_HIGH_BP = 700
STATE_TIER_MID_FLOOR_CENTS = 500000
STATE_TIER_HIGH_FLOOR_CENTS = 1500000

DEVIATION_FREE_DAYS = 2
DEVIATION_DAY_FEE_CENTS = 9500
DEVIATION_MAX_DAYS_TOTAL = 7
CHANGE_FEE_BASE_CENTS = 12500
CHANGE_FEE_ESCALATOR_BP = 5000
CHANGE_FEE_CAP_BP = 4000
UPGRADE_STEP = {"ECONOMY": 0, "PREMIUM_ECONOMY": 48000, "BUSINESS": 165000}

TRANSFER_BUFFER_MINUTES = 45

MAX_NEGOTIATION_ROUNDS = 5
MAX_DESTINATION_RISK = 60
MIN_INSPECTION_SCORE = 70

QUALIFIER_ROLLUP_STATES = ("QUALIFIED", "NOTIFIED", "REGISTERED", "TRAVELLED")
REGISTRATION_ROLLUP_STATES = ("CONFIRMED", "TRAVELLED")


# --------------------------------------------------------------- arithmetic
def round_half_up(numerator, denominator=1):
    """round_half_up(numerator / denominator) to a whole unit."""
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_ceil(numerator, denominator=1):
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal(1), rounding=ROUND_CEILING))


def floor_div(numerator, denominator):
    return numerator // denominator


# ------------------------------------------------- tier_assignment_selector
def eligible_tiers(db, qualifier):
    """Every tier of the qualifier's program whose threshold <= actual_metric."""
    pool = [t for t in db.award_tiers.values()
            if t["program_id"] == qualifier["program_id"]
            and t["qualification_threshold"] <= qualifier["actual_metric"]]
    # Richest rung actually cleared: threshold DESC, then tier_rank ASC.
    pool.sort(key=lambda t: (-t["qualification_threshold"], t["tier_rank"]))
    return pool


def select_tier(db, qualifier):
    pool = eligible_tiers(db, qualifier)
    return pool[0] if pool else None


# --------------------------------------------------- qualifier_committed_cost
def qualifier_committed_cost(db, qualifier, tier=None):
    """Three independently rounded components plus the tier upgrade allowance."""
    if tier is None:
        tier = db.award_tiers.get(qualifier.get("assigned_tier_id"))
    if tier is None:
        return 0
    program = db.programs.get(qualifier["program_id"])
    base_pp = program["per_person_cost_basis_cents"] if program else 0

    winner_component = round_half_up(base_pp * (10000 + tier["service_load_bp"]), 10000)
    guest_component = round_half_up(base_pp * GUEST_SHARE_BP, 10000)
    gratuity_component = round_half_up(base_pp * GRATUITY_BP, 10000)

    return (winner_component
            + guest_component * qualifier["guest_count"]
            + gratuity_component
            + tier["upgrade_allowance_cents"])


# ------------------------------------------------------- program_budget_rollup
def program_budget_rollup(db, program):
    # PRD 3.1: a newly chartered program seeds committed_budget_cents AND
    # budget_headroom_cents to 0, and "the budget identity described in 2.10
    # takes hold the first time the budget rollup runs". Running the rollup is
    # therefore what arms the identity; before that the seeded zeros stand.
    program["budget_rollup_armed"] = True
    award_side = sum(q["committed_cost_cents"] for q in db.qualifiers.values()
                     if q["program_id"] == program["id"]
                     and q["award_status"] in QUALIFIER_ROLLUP_STATES)
    air_side = sum(r["cost_cents"] for r in db.registrations.values()
                   if r["program_id"] == program["id"]
                   and r["attendance_status"] in REGISTRATION_ROLLUP_STATES)

    committed = award_side + air_side
    total = program["budget_total_cents"]
    program["committed_budget_cents"] = committed
    program["budget_headroom_cents"] = total - committed

    utilization_bp = 0 if total == 0 else floor_div(committed * 10000, total)
    if utilization_bp <= BUDGET_POSTURE_WATCH_BP:
        program["budget_posture"] = "OK"
    elif utilization_bp <= BUDGET_POSTURE_OVER_BP:
        program["budget_posture"] = "WATCH"
    else:
        program["budget_posture"] = "OVERCOMMITTED"
    return program


def program_counts(db, program):
    rows = [q for q in db.qualifiers.values() if q["program_id"] == program["id"]]
    program["qualified_count"] = sum(1 for q in rows
                                    if q["award_status"] in QUALIFIER_ROLLUP_STATES)
    program["travelled_count"] = sum(1 for q in rows if q["award_status"] == "TRAVELLED")
    return program


def reported_award_total(db, program):
    total = 0
    for report in db.tax_award_reports.values():
        if report["status"] != "FILED":
            continue
        qualifier = db.qualifiers.get(report["qualifier_id"])
        if qualifier and qualifier["program_id"] == program["id"]:
            total += report["reported_value_cents"]
    program["reported_award_total_cents"] = total
    return program


# ----------------------------------------------------------- room_night_ledger
def registration_room_nights(registration):
    return registration["rooms"] * day_span(registration["arrival_date"],
                                            registration["departure_date"])


def room_night_ledger(db, contract):
    confirmed = sum(r["room_nights"] for r in db.registrations.values()
                    if r["program_id"] == contract["program_id"]
                    and r["attendance_status"] in REGISTRATION_ROLLUP_STATES)
    blocked = contract["room_nights_blocked"]
    contract["room_nights_confirmed"] = confirmed
    contract["room_nights_available"] = blocked - confirmed
    floor_rn = attrition_floor(contract)
    shortfall = max(0, floor_rn - confirmed)
    contract["attrition_posture"] = "AT_RISK" if shortfall > 0 else "CLEAR"
    return contract


def attrition_floor(contract):
    return round_ceil(contract["room_nights_blocked"] * (10000 - contract["attrition_allowance_bp"]),
                      10000)


def shortfall_room_nights(contract):
    return max(0, attrition_floor(contract) - contract["room_nights_confirmed"])


def per_night_occupancy_ok(db, contract, candidate):
    """Half-open interval [arrival_date, departure_date) per-night room gate."""
    start = parse_dt(candidate["arrival_date"])
    nights = day_span(candidate["arrival_date"], candidate["departure_date"])
    peers = [r for r in db.registrations.values()
             if r["program_id"] == contract["program_id"]
             and r["id"] != candidate["id"]
             and r["attendance_status"] in REGISTRATION_ROLLUP_STATES]
    for index in range(nights):
        night = start.replace() + _days(index)
        occupancy = 0
        for peer in peers:
            arrive = parse_dt(peer["arrival_date"])
            depart = parse_dt(peer["departure_date"])
            if arrive <= night < depart:
                occupancy += peer["rooms"]
        if occupancy + candidate["rooms"] > contract["room_block_count"]:
            return False
    return True


def _days(count):
    from datetime import timedelta
    return timedelta(days=count)


# --------------------------------------------- cancellation_exposure_projection
def exposure_projection(db, contract, logical_now):
    contract_value = (contract["room_block_count"] * contract["contracted_nights"]
                      * contract["nightly_rate_cents"])

    floor_rn = attrition_floor(contract)
    shortfall = max(0, floor_rn - contract["room_nights_confirmed"])
    attrition_basis = shortfall * contract["nightly_rate_cents"]

    now_dt = parse_dt(logical_now)
    milestones = [m for m in db.deposit_milestones.values()
                  if m["contract_id"] == contract["id"]
                  and m["status"] in ("SCHEDULED", "PAID")]
    milestones.sort(key=lambda m: m["sequence"])

    pre_relief = 0
    for milestone in milestones:
        due = parse_dt(milestone["due_at"])
        if due is not None and due <= now_dt:
            pre_relief += milestone["amount_cents"]
        else:
            pre_relief += round_half_up(
                milestone["amount_cents"] * (10000 - milestone["refundable_bp"]), 10000)

    relief_bp = FM_RELIEF_BP.get(contract["force_majeure_clause"], 0)
    deposit_basis = round_half_up(pre_relief * (10000 - relief_bp), 10000)

    binding_basis = contract["exposure_basis"]
    binding = attrition_basis if binding_basis == "ATTRITION_BASIS" else deposit_basis

    return {
        "contract_id": contract["id"],
        "contract_value_cents": contract_value,
        "attrition_basis_cents": attrition_basis,
        "deposit_forfeiture_basis_cents": deposit_basis,
        "deposit_pre_relief_cents": pre_relief,
        "force_majeure_relief_bp": relief_bp,
        "binding_basis": binding_basis,
        "binding_exposure_cents": binding,
        "room_nights_blocked": contract["room_nights_blocked"],
        "room_nights_confirmed": contract["room_nights_confirmed"],
        "attrition_floor_room_nights": floor_rn,
        "shortfall_room_nights": shortfall,
    }


def program_cancellation_exposure(db, program):
    total = 0
    for contract in db.supplier_contracts.values():
        if contract["program_id"] != program["id"] or contract["status"] != "EXECUTED":
            continue
        room_night_ledger(db, contract)
        total += exposure_projection(db, contract, db.logical_now())["binding_exposure_cents"]
    program["cancellation_exposure_cents"] = total
    return program


# --------------------------------------------------------- taxable award base
def taxable_award_base(committed_cost_cents):
    exclusion = round_half_up(committed_cost_cents * BUSINESS_PURPOSE_EXCLUSION_BP, 10000)
    return committed_cost_cents - exclusion


def state_supplemental_bp(award_value_cents):
    if award_value_cents < STATE_TIER_MID_FLOOR_CENTS:
        return STATE_TIER_LOW_BP
    if award_value_cents < STATE_TIER_HIGH_FLOOR_CENTS:
        return STATE_TIER_MID_BP
    return STATE_TIER_HIGH_BP


def taxable_award_gross_up(award_value_cents, gross_up_method):
    """Returns (combined_rate_bp, gross_up_cents, reported_value_cents)."""
    award = award_value_cents
    if gross_up_method == "NONE":
        combined_rate_bp = 0
        gross_up_cents = 0
    elif gross_up_method == "FLAT_SUPPLEMENTAL":
        combined_rate_bp = FED_SUPPLEMENTAL_BP
        gross_up_cents = round_half_up(award * FED_SUPPLEMENTAL_BP, 10000)
    else:  # FULL_GROSS_UP - state tier keyed on the PRE-gross-up award value.
        combined_rate_bp = FED_SUPPLEMENTAL_BP + FICA_BP + state_supplemental_bp(award)
        reported = round_half_up(award * 10000, 10000 - combined_rate_bp)
        gross_up_cents = reported - award
    return combined_rate_bp, gross_up_cents, award + gross_up_cents


# ----------------------------------------------------- air_cost_and_change_fee
def air_cost_and_change_fee(db, registration):
    qualifier = db.qualifiers.get(registration["qualifier_id"])
    tier = db.award_tiers.get(qualifier.get("assigned_tier_id")) if qualifier else None
    tier_step = UPGRADE_STEP.get(tier["air_cabin_class"], 0) if tier else 0
    allowance = tier["upgrade_allowance_cents"] if tier else 0

    seat_step = UPGRADE_STEP.get(registration.get("air_cabin_class"), 0)
    billable_step = max(0, seat_step - tier_step)
    registration["air_upgrade_cost_cents"] = max(0, billable_step - allowance)

    total_days = registration["air_deviation_pre_days"] + registration["air_deviation_post_days"]
    chargeable_days = max(0, total_days - DEVIATION_FREE_DAYS)
    registration["air_deviation_fee_cents"] = chargeable_days * DEVIATION_DAY_FEE_CENTS

    cap = round_half_up(registration["air_base_fare_cents"] * CHANGE_FEE_CAP_BP, 10000)
    cumulative = 0
    for k in range(1, registration["air_change_count"] + 1):
        power = k - 1
        cumulative += round_half_up(CHANGE_FEE_BASE_CENTS * (10000 + CHANGE_FEE_ESCALATOR_BP) ** power,
                                    10000 ** power)
    registration["air_change_fee_total_cents"] = min(cap, cumulative)

    registration["cost_cents"] = (registration["air_upgrade_cost_cents"]
                                  + registration["air_deviation_fee_cents"]
                                  + registration["air_change_fee_total_cents"])
    return registration


# ------------------------------------------------------ activity_seat_allocation
def activity_counts(db, activity):
    rows = [s for s in db.activity_signups.values() if s["activity_id"] == activity["id"]]
    activity["booked_count"] = sum(1 for s in rows if s["status"] == "BOOKED")
    activity["waitlist_count"] = sum(1 for s in rows if s["status"] == "WAITLISTED")
    return activity


def _promotion_key(db, signup):
    registration = db.registrations.get(signup["registration_id"])
    qualifier = db.qualifiers.get(registration["qualifier_id"]) if registration else None
    employee_code = qualifier["employee_code"] if qualifier else ""
    return (signup["created_at"], employee_code)


def promote_one(db, activity):
    """Exactly one promotion per released BOOKED seat, only while OPEN."""
    if activity["status"] != "OPEN":
        return None
    pool = [s for s in db.activity_signups.values()
            if s["activity_id"] == activity["id"] and s["status"] == "WAITLISTED"]
    if not pool:
        return None
    pool.sort(key=lambda s: _promotion_key(db, s))
    winner = pool[0]
    winner["status"] = "BOOKED"
    winner["promoted_at"] = db.logical_now()
    db.touch(winner)
    activity_counts(db, activity)
    return winner


# ------------------------------------------------------ activity_schedule_conflict
def has_schedule_conflict(db, registration_id, target_activity):
    buffer_delta = _minutes(TRANSFER_BUFFER_MINUTES)
    target_start = parse_dt(target_activity["start_at"])
    target_end = parse_dt(target_activity["end_at"])
    for signup in db.activity_signups.values():
        if signup["registration_id"] != registration_id:
            continue
        if signup["status"] not in ("BOOKED", "WAITLISTED"):
            continue
        existing = db.onsite_activities.get(signup["activity_id"])
        if existing is None:
            continue
        existing_start = parse_dt(existing["start_at"])
        existing_end = parse_dt(existing["end_at"])
        if target_start < (existing_end + buffer_delta) and existing_start < (target_end + buffer_delta):
            return True
    return False


def _minutes(count):
    from datetime import timedelta
    return timedelta(minutes=count)


# ---------------------------------------------------------- program_measurement
def program_measurement(db, program):
    travellers = [q for q in db.qualifiers.values()
                  if q["program_id"] == program["id"] and q["award_status"] == "TRAVELLED"]
    baseline_total = sum(q["baseline_metric"] for q in travellers)
    actual_total = sum(q["actual_metric"] for q in travellers)

    if not travellers or baseline_total == 0:
        sales_lift_pct = None
    else:
        lift_bp = round_half_up((actual_total - baseline_total) * 10000, baseline_total)
        sales_lift_pct = float(Decimal(lift_bp) / Decimal(100))

    surveyed = [r for r in db.registrations.values()
                if r["program_id"] == program["id"] and r["satisfaction_score"] is not None]
    if not surveyed:
        satisfaction_index = None
    else:
        centi = round_half_up(sum(r["satisfaction_score"] for r in surveyed) * 100, len(surveyed))
        satisfaction_index = float(Decimal(centi) / Decimal(100))

    return {
        "sales_lift_pct": sales_lift_pct,
        "satisfaction_index": satisfaction_index,
        "baseline_metric_total": baseline_total,
        "actual_metric_total": actual_total,
        "survey_count": len(surveyed),
    }


# ------------------------------------------------------------------- contract
def contract_value(contract):
    return (contract["room_block_count"] * contract["contracted_nights"]
            * contract["nightly_rate_cents"])


def scheduled_deposit_total(db, contract, exclude_id=None):
    total = 0
    for milestone in db.deposit_milestones.values():
        if milestone["contract_id"] != contract["id"]:
            continue
        if milestone["status"] == "CANCELLED":
            continue
        if exclude_id is not None and milestone["id"] == exclude_id:
            continue
        total += milestone["amount_cents"]
    return total


def recompute_stay_end(contract):
    contract["stay_end_at"] = add_days(contract["stay_start_at"], contract["contracted_nights"])
    return contract
