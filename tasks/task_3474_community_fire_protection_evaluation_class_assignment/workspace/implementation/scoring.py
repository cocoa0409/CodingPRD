"""All §1.3 / PRD §3.6-§3.8 calculations, with constants from the scaffold."""
from decimal import Decimal, getcontext

from util import dec, q2, round_half_up_int, parse_date, add_calendar_months

getcontext().prec = 40
D = Decimal

# --- constants (SCAFFOLD §1.3) ---------------------------------------------
REFERENCE_RESIDUAL_PSI = D("20")
PRESSURE_EXPONENT = D("0.54")

NEEDED_PUMP_GPM = D("1750")
LADDER_MIN_FT = 75
TANKER_MIN_GAL = 1000

NEEDED_ON_SHIFT = D("6")
VOLUNTEER_FACTOR = D("0.5")

TRAINING_HOURS_BENCHMARK = D("240")
LIVE_FIRE_CAP = D("6")

FLOW_TARGET_MULT = D("1.5")
HYDRANT_CREDIT_MIN_GPM = D("1000")
STORAGE_DURATION_MIN = D("120")
STALE_FACTOR = D("0.5")
STALE_MONTHS = 60
ALT_SITE_TARGET = D("2")

ALARM_FAST_SECONDS = 60
ALARM_SLOW_SECONDS = 90

CRR_ITEM_CAP = D("2.0")
CRR_TOTAL_CAP = D("5.5")
CRR_PCT_OF_SUBTOTAL = D("0.10")

DIVERGENCE_RATIO = D("0.5")

HYDRANT_RADIUS_FT = 1000
STATION_RADIUS_MI = D("5.0")

EXPOSURE_CAP_CENTS = 500000000
COVERAGE_VALUE_CAP_RATIO = D("1.5")

EVAL_INTERVAL_MONTHS = 60
REEVAL_MIN_MONTHS = 12
APPEAL_WINDOW_DAYS = 90

MODIFIER_TABLE = {
    1: D("0.65"), 2: D("0.70"), 3: D("0.75"), 4: D("0.80"), 5: D("0.85"),
    6: D("0.90"), 7: D("0.95"), 8: D("1.00"), 9: D("1.10"), 10: D("1.25"),
}


def class_of(total):
    t = dec(total)
    for threshold, cls in [(90, 1), (80, 2), (70, 3), (60, 4), (50, 5),
                           (40, 6), (30, 7), (20, 8), (10, 9)]:
        if t >= D(threshold):
            return cls
    return 10


def compute_flow_20(static_psi, residual_psi, measured_flow_gpm):
    """flow_normalization: integer gpm, round-half-up."""
    s = dec(static_psi)
    r = dec(residual_psi)
    m = dec(measured_flow_gpm)
    ratio = (s - REFERENCE_RESIDUAL_PSI) / (s - r)
    value = m * (ratio ** PRESSURE_EXPONENT)
    return round_half_up_int(value)


def premium_amounts(coverage_cents, base_rate_bp, modifier, term_months):
    """premium_amounts: PROVISIONAL rounds once at the end; FINAL rounds per
    month then multiplies. The two rounding orders are pinned (PRD §3.8)."""
    annual_exact = D(coverage_cents) * D(base_rate_bp) * dec(modifier) / D(10000)
    provisional = round_half_up_int(annual_exact * D(term_months) / D(12))
    monthly = round_half_up_int(annual_exact / D(12))
    final = monthly * term_months
    return provisional, final


def compute_scores(community, dept, apparatus, system, hydrants, credits, cycle):
    """Compute every ScoreSheet field. Each named subscore is rounded half-up
    to 2dp before summation into a total (PRD §2.6)."""
    # --- fire department arm (max 50) ---
    frontline = [a for a in apparatus if a["status"] == "FRONTLINE"]
    pump_sum = sum(a["pump_capacity_gpm"] or 0 for a in frontline if a["kind"] == "ENGINE")
    pump_pts = q2(D(8) * min(D(1), D(pump_sum) / NEEDED_PUMP_GPM))
    ladder_pts = D(6) if any(
        a["kind"] in ("LADDER", "QUINT") and (a["ladder_height_ft"] or 0) >= LADDER_MIN_FT
        for a in frontline
    ) else D(0)
    reserve_pts = D(3) if any(
        a["kind"] == "ENGINE" for a in apparatus if a["status"] == "RESERVE"
    ) else D(0)
    tanker_pts = D(3) if any(
        a["kind"] == "TANKER" and (a["tank_capacity_gal"] or 0) >= TANKER_MIN_GAL
        for a in frontline
    ) else D(0)
    equipment_points = q2(pump_pts + ladder_pts + reserve_pts + tanker_pts)

    if dept["dept_type"] == "CAREER":
        factor = D("1.0")
        staffing_variant = "RAW_HEADCOUNT"
    else:
        factor = VOLUNTEER_FACTOR
        staffing_variant = "CAREER_EQUIVALENT"
    effective_strength = dec(dept["career_on_duty_per_shift"]) + factor * dec(dept["volunteers_on_duty_avg"])
    staffing_points = q2(D(15) * min(D(1), effective_strength / NEEDED_ON_SHIFT))

    hours_pts = q2(D(6) * min(D(1), dec(dept["training_hours_per_firefighter_annual"]) / TRAINING_HOURS_BENCHMARK))
    facility_pts = {"A": D(3), "B": D(2), "C": D(1)}[dept["training_facility_level"]]
    training_points = hours_pts + facility_pts
    if not dept["live_fire_training"]:
        training_points = min(training_points, LIVE_FIRE_CAP)
    training_points = q2(training_points)

    response_points = q2(D(6) * dec(dept["coverage_pct_within_5mi"]) / D(100))
    fd_total_points = q2(equipment_points + staffing_points + training_points + response_points)

    # --- water arm (max 40) ---
    nff = dec(system["needed_fire_flow_gpm"])
    supply_points = q2(D(10) * min(D(1), dec(system["supply_works_capacity_gpm"]) / nff))
    storage_points = q2(D(5) * min(D(1), dec(system["storage_capacity_gal"]) / (nff * STORAGE_DURATION_MIN)))
    rural = dec(community["rural_area_pct"]) > D(50) and system["alternate_verified"]
    if rural:
        water_variant = "RURAL_SHUTTLE"
        flow_points = q2(D(18) * min(D(1), dec(system["alternate_shuttle_capacity_gpm"]) / nff))
        distribution_points = q2(D(7) * min(D(1), dec(system["alternate_sites_count"]) / ALT_SITE_TARGET))
    else:
        water_variant = "MUNICIPAL"
        cutoff = add_calendar_months(parse_date(cycle["data_freeze_date"]), -STALE_MONTHS).isoformat()
        eff_sum = D(0)
        creditworthy = 0
        for h in hydrants:
            if h["status"] != "ACTIVE" or h["max_flow_gpm"] is None:
                continue
            f = dec(h["max_flow_gpm"])
            if not (h["last_certified_test_date"] >= cutoff):
                f = f * STALE_FACTOR  # staleness halving applied per hydrant before summation
            eff_sum += f
            if f >= HYDRANT_CREDIT_MIN_GPM:
                creditworthy += 1
        flow_points = q2(D(18) * min(D(1), eff_sum / (FLOW_TARGET_MULT * nff)))
        needed_hydrants = -(-int(system["needed_fire_flow_gpm"]) // 1000)  # ceil(NFF/1000)
        distribution_points = q2(D(7) * min(D(1), D(creditworthy) / D(needed_hydrants)))
    water_total_points = q2(supply_points + flow_points + distribution_points + storage_points)

    # --- communications (max 10, whole points) ---
    ops = community["comms_operators_on_duty_min"]
    ops_pts = 4 if ops >= 2 else (2 if ops == 1 else 0)
    sec = community["comms_avg_alarm_to_dispatch_seconds"]
    alarm_pts = 4 if sec <= ALARM_FAST_SECONDS else (2 if sec <= ALARM_SLOW_SECONDS else 0)
    rc = community["comms_redundant_circuits"]
    bp = community["comms_backup_power"]
    redundancy_pts = 2 if (rc and bp) else (1 if (rc or bp) else 0)
    comms_points = D(ops_pts + alarm_pts + redundancy_pts)

    # --- risk reduction (pinned order: subtotal first, then caps) ---
    subtotal_points = q2(fd_total_points + water_total_points + comms_points)
    crr_raw_points = D(0)
    for c in credits:
        if c["status"] == "VERIFIED":
            crr_raw_points += dec(c["credited_points"])
    pct_cap = q2(CRR_PCT_OF_SUBTOTAL * subtotal_points)
    crr_effective_points = min(crr_raw_points, CRR_TOTAL_CAP, pct_cap)

    # --- divergence, adjusted total, classes ---
    half_fd = DIVERGENCE_RATIO * fd_total_points
    if water_total_points < half_fd:
        divergence_penalty_points = q2(D(2) * (half_fd - water_total_points))
    else:
        divergence_penalty_points = D("0.00")
    adjusted_total_points = q2(subtotal_points + crr_effective_points - divergence_penalty_points)
    base_class = class_of(adjusted_total_points)

    hydrant_component = flow_points + distribution_points
    if system["alternate_verified"]:
        alternate_component = q2(D(18) * min(D(1), dec(system["alternate_shuttle_capacity_gpm"]) / nff)) \
            + q2(D(7) * min(D(1), dec(system["alternate_sites_count"]) / ALT_SITE_TARGET))
    else:
        alternate_component = D(0)
    split_total = adjusted_total_points - hydrant_component + alternate_component
    if split_total < 0:
        split_total = D(0)
    split_class_beyond_hydrant = class_of(split_total)

    return {
        "equipment_points": equipment_points,
        "staffing_points": staffing_points,
        "staffing_variant_used": staffing_variant,
        "training_points": training_points,
        "response_points": response_points,
        "fd_total_points": fd_total_points,
        "supply_points": supply_points,
        "flow_points": flow_points,
        "distribution_points": distribution_points,
        "storage_points": storage_points,
        "water_total_points": water_total_points,
        "water_variant_used": water_variant,
        "comms_points": comms_points,
        "crr_raw_points": crr_raw_points,
        "crr_effective_points": crr_effective_points,
        "subtotal_points": subtotal_points,
        "divergence_penalty_points": divergence_penalty_points,
        "adjusted_total_points": adjusted_total_points,
        "base_class": base_class,
        "split_class_beyond_hydrant": split_class_beyond_hydrant,
    }
