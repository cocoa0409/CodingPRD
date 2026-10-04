"""Calculation rules (SCAFFOLD §1.3 / PRD §3), constants pinned by PRD prose.

All comparisons consume the ROUNDED value (PRD §2.6): 4dp half-up for adjusted
emissions, conformity ratios, completion rates and dosing deviation; 2dp
half-up for dosing targets; integer cents half-up for money, with the pinned
rounding order each narrative names; integer floor arithmetic for scores.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import clock
import store

# --- pinned constants ---
EMISSIONS_COMPONENT_CLASSES = (
    "AFTERTREATMENT_SCR", "AFTERTREATMENT_DPF", "DOSING_SYSTEM",
    "NOX_SENSOR", "EGR_SYSTEM",
)
EXTENDED_WARRANTY_YEARS = 5
EXTENDED_WARRANTY_MILES = 100000
EXTENDED_WARRANTY_HOURS = 3000
MAINTENANCE_INTERVAL_MILES = 15000
NEGLECT_MISSED_INTERVAL_POINTS = 25
NEGLECT_BAD_DEF_POINTS = 15
NEGLECT_CRITICAL_FAULT_POINTS = 20
NEGLECT_SCORE_CAP = 100
NEGLECT_PARTIAL_MIN_SCORE = 30
NEGLECT_DENY_MIN_SCORE = 60
PARTIAL_CUSTOMER_SHARE_CAP_PCT = Decimal("0.5")
CORE_PROVISIONAL_CREDIT_PCT = Decimal("0.6")
GRADE_PCT = {"A": Decimal("1.0"), "B": Decimal("0.75"), "C": Decimal("0.5")}
MAX_CORE_CREDIT_PCT_OF_PRICE = Decimal("0.4")
SPEC_MULT = {
    "STANDARD": Decimal("1.0"),
    "PLUS": Decimal("1.15"),
    "PREMIUM": Decimal("1.3"),
}
CONFORMITY_RATIO_THRESHOLD = Decimal("0.9")
DEFAULT_COMPLETION_THRESHOLD = 0.95
FAULT_WEIGHT = {"CRITICAL": 40, "MAJOR": 20, "MINOR": 5}
FAULT_RISK_DRIFT_DIVISOR = Decimal("10")
FAULT_RISK_DRIFT_CAP = 30
DEF_ZERO_MILES_THRESHOLD = 500
DEF_ZERO_PENALTY_POINTS = 25
FAULT_RISK_SCORE_CAP = 100
PREDICTIVE_SERVICE_THRESHOLD = 70
DOSING_BASE_G_PER_KWH = Decimal("6.0")
DOSING_REFERENCE_DISPLACEMENT_L = Decimal("12.0")
DOSING_TOLERANCE_PCT = Decimal("0.05")
NOX_SENSOR_PPM_MAX = Decimal("400")
REQUIRED_TEST_TYPES = ("FTP", "RMC", "SET")


def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def round_dp(x, dp):
    """Round half-up to dp decimal places; returns a Decimal."""
    return D(x).quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)


def cents(x):
    """Round half-up to whole cents; returns an int."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- adjusted_emissions: test-run record-results ---
def emissions_result(measured_nox, measured_pm, deterioration_factor,
                     nox_limit, pm_limit):
    adj_nox = round_dp(D(measured_nox) * D(deterioration_factor), 4)
    adj_pm = round_dp(D(measured_pm) * D(deterioration_factor), 4)
    # equality at the limit PASSES (<=), compared on the rounded values
    result = "PASS" if (adj_nox <= D(nox_limit) and adj_pm <= D(pm_limit)) else "FAIL"
    return float(adj_nox), float(adj_pm), result


# --- dosing_calibration_check: aftertreatment-spec calibrate ---
def dosing_calibration(displacement_liters, observed_def, observed_nox_ppm_avg):
    target = round_dp(
        DOSING_BASE_G_PER_KWH * D(displacement_liters) / DOSING_REFERENCE_DISPLACEMENT_L, 2)
    if target == 0:
        deviation = Decimal("0")
    else:
        deviation = round_dp(abs(D(observed_def) - target) / target, 4)
    # boundary inclusive: deviation exactly 0.0500 calibrates
    status = ("CALIBRATED"
              if (deviation <= DOSING_TOLERANCE_PCT and D(observed_nox_ppm_avg) <= NOX_SENSOR_PPM_MAX)
              else "UNCALIBRATED")
    return float(target), float(deviation), status


# --- conformity_ratio: in-use-results create ---
def conformity(passing_units, sample_size):
    ratio = round_dp(Decimal(passing_units) / Decimal(sample_size), 4)
    # threshold inclusive: exactly 0.9000 is CONFORMING
    outcome = "CONFORMING" if ratio >= CONFORMITY_RATIO_THRESHOLD else "NON_CONFORMING"
    return float(ratio), outcome


# --- campaign_completion_rate ---
def completion_rate_dec(verified, notified):
    if notified == 0:
        return Decimal("0")
    return round_dp(Decimal(verified) / Decimal(notified), 4)


# --- warranty_coverage_determination (claim create + coverage read) ---
def coverage_windows(unit, std, component_class, now):
    """component_class=None evaluates the extended window legs without the
    class condition (the per-unit computed coverage read)."""
    in_service = unit["in_service_date"]
    base_end = clock.add_years(in_service, std["base_warranty_years"])
    base_open = (now < base_end) and (unit["accumulated_miles"] < std["base_warranty_miles"])
    ext_years = min(EXTENDED_WARRANTY_YEARS, std["useful_life_years"])
    ext_miles = min(EXTENDED_WARRANTY_MILES, std["useful_life_miles"])
    ext_hours = min(EXTENDED_WARRANTY_HOURS, std["useful_life_hours"])
    ext_end = clock.add_years(in_service, ext_years)
    ext_legs_open = ((now < ext_end)
                     and (unit["accumulated_miles"] < ext_miles)
                     and (unit["accumulated_hours"] < ext_hours))
    extended_open = ext_legs_open and (component_class is None
                                       or component_class in EMISSIONS_COMPONENT_CLASSES)
    if component_class is None:
        variant = None  # read-only form: no variant is stamped
    elif component_class in EMISSIONS_COMPONENT_CLASSES and ext_legs_open:
        variant = "EXTENDED_EMISSIONS"  # extended takes precedence when both open
    elif base_open:
        variant = "BASE_WARRANTY"
    else:
        variant = None
    return {
        "base_covered": base_open,
        "base_coverage_end": base_end,
        "extended_covered": ext_legs_open if component_class is None else extended_open,
        "extended_coverage_end": ext_end,
        "variant": variant,
    }


# --- neglect_score: warranty-claim adjudicate (integer arithmetic) ---
def neglect_score(unit):
    uid = unit["id"]
    expected_oil = unit["accumulated_miles"] // MAINTENANCE_INTERVAL_MILES
    oil_changes = sum(
        1 for r in store.maintenance.values()
        if r["engine_unit_id"] == uid and r["maintenance_type"] == "OIL_CHANGE")
    missed_oil = max(0, expected_oil - oil_changes)
    bad_def = sum(
        1 for r in store.maintenance.values()
        if r["engine_unit_id"] == uid
        and r["maintenance_type"] == "DEF_SERVICE"
        and r["def_quality_ok"] is False)
    crit_snaps = sum(
        1 for s in store.snapshots.values()
        if s["engine_unit_id"] == uid
        and any(fc["severity"] == "CRITICAL" for fc in s["fault_codes"]))
    score = (NEGLECT_MISSED_INTERVAL_POINTS * missed_oil
             + NEGLECT_BAD_DEF_POINTS * bad_def
             + NEGLECT_CRITICAL_FAULT_POINTS * crit_snaps)
    return min(NEGLECT_SCORE_CAP, score)


def decision_band(score):
    if score < NEGLECT_PARTIAL_MIN_SCORE:
        return "APPROVE_FULL"
    if score < NEGLECT_DENY_MIN_SCORE:
        return "APPROVE_PARTIAL"
    return "DENY_NEGLECT"


# --- partial_claim_proration (pinned: round the rate first, then multiply) ---
def partial_proration(claim, unit, std):
    claimed = claim["claimed_amount_cents"]
    if claim["coverage_variant"] == "EXTENDED_EMISSIONS":
        # MILEAGE_BASED
        term_miles = min(EXTENDED_WARRANTY_MILES, std["useful_life_miles"])
        per_mile_rate = cents(Decimal(claimed) / Decimal(term_miles))
        raw_share = per_mile_rate * unit["accumulated_miles"]
    else:
        # TIME_BASED
        term_days = std["base_warranty_years"] * 365
        elapsed_days = max(0, (claim["created_at"] - unit["in_service_date"]).days)
        daily_rate = cents(Decimal(claimed) / Decimal(term_days))
        raw_share = daily_rate * elapsed_days
    share_cap = cents(Decimal(claimed) * PARTIAL_CUSTOMER_SHARE_CAP_PCT)
    customer_share = min(raw_share, share_cap)
    return customer_share, claimed - customer_share


# --- reman money (pinned evaluation order, PRD §3.9) ---
def spec_level_surcharge(quoted_price_cents, spec_level):
    return cents(Decimal(quoted_price_cents) * (SPEC_MULT[spec_level] - Decimal("1.0")))


def provisional_core_credit(quoted_core_value_cents):
    return cents(Decimal(quoted_core_value_cents) * CORE_PROVISIONAL_CREDIT_PCT)


def final_core_credit(quoted_core_value_cents, core_grade, effective_price_cents):
    grade_value = cents(Decimal(quoted_core_value_cents) * GRADE_PCT[core_grade])
    credit_cap = cents(Decimal(effective_price_cents) * MAX_CORE_CREDIT_PCT_OF_PRICE)
    return min(grade_value, credit_cap)


# --- fault_risk_score: telematics-snapshot ingest ---
def fault_risk_score(fault_codes, nox_sensor_drift_ppm, def_consumption_gal,
                     miles_before, odometer_miles):
    fault_points = sum(FAULT_WEIGHT[fc["severity"]] for fc in fault_codes)
    drift_points = int(
        (abs(D(nox_sensor_drift_ppm)) / FAULT_RISK_DRIFT_DIVISOR).to_integral_value(
            rounding="ROUND_FLOOR"))
    drift_points = min(FAULT_RISK_DRIFT_CAP, drift_points)
    def_penalty = (DEF_ZERO_PENALTY_POINTS
                   if (D(def_consumption_gal) == 0
                       and (odometer_miles - miles_before) > DEF_ZERO_MILES_THRESHOLD)
                   else 0)
    return min(FAULT_RISK_SCORE_CAP, fault_points + drift_points + def_penalty)


# --- lab_window_overlap_check: strict half-open [s, e), scoped by lab_code ---
def lab_window_conflict(lab_code, new_start, new_end, exclude_id=None):
    for r in store.test_runs.values():
        if r["lab_code"] != lab_code or r["id"] == exclude_id:
            continue
        if r["status"] not in ("SCHEDULED", "COMPLETED"):
            continue  # REJECTED / INVALIDATED never block
        if new_start < r["scheduled_end"] and r["scheduled_start"] < new_end:
            return True
    return False


# --- shop_bay_capacity_check: aggregate day-bucket semantics ---
def bay_capacity_ok(center_id, scheduled_start_day, bay_days, bay_capacity_per_day):
    start = scheduled_start_day.date()
    new_days = [start + timedelta(days=i) for i in range(bay_days)]
    occupied = {d: 0 for d in new_days}
    for wo in store.work_orders.values():
        if wo["service_center_id"] != center_id:
            continue
        if wo["status"] not in ("SCHEDULED", "IN_BAY"):
            continue  # COMPLETED / VERIFIED / CANCELLED occupy nothing
        ws = wo["scheduled_start_day"].date()
        for i in range(wo["bay_days"]):
            d = ws + timedelta(days=i)
            if d in occupied:
                occupied[d] += 1
    return all(n + 1 <= bay_capacity_per_day for n in occupied.values())
