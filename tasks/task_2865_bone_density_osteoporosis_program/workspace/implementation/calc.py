"""The twelve calculations of PRD section 3, with their declared constants."""
from decimal import Decimal

from util import add_months, completed_months, completed_years, dec, rnd

D = Decimal

# --- 3.3 phantom quality control -------------------------------------------
QC_PASS_MAX_SD = D("1.000")
QC_WARN_MAX_SD = D("1.500")
QC_SHIFT_MIN_SD = D("1.000")
QC_SHIFT_RUN_COUNT = 3
QC_RELEASE_PASS_STREAK = 2
QC_HOLD_CANCEL_HORIZON_HOURS = 48

# --- 3.2 precision certification -------------------------------------------
LSC_COEFFICIENT = D("2.77")
MIN_PRECISION_DEGREES_OF_FREEDOM = 30

# --- 3.3 cross calibration -------------------------------------------------
CROSS_CAL_TOLERANCE_PCT = D("1.00")
CROSS_CAL_MAX_PCT = D("5.00")
REQUIRED_PHANTOM_RUNS = {
    "SOFTWARE_UPGRADE": 3,
    "DETECTOR_REPLACEMENT": 5,
    "XRAY_TUBE_REPLACEMENT": 5,
    "DEVICE_REPLACEMENT": 10,
}

# --- 3.5 site measurement --------------------------------------------------
MIN_VALID_VERTEBRAE = 2
LUMBAR_LEVELS = ("L1", "L2", "L3", "L4")
CENTRAL_SITES = ("LUMBAR_SPINE", "FEMORAL_NECK", "TOTAL_HIP")
SITE_PRECEDENCE = ("LUMBAR_SPINE", "FEMORAL_NECK", "TOTAL_HIP", "FOREARM_33")
LSC_SITE_PRECEDENCE = ("TOTAL_HIP", "LUMBAR_SPINE", "FEMORAL_NECK")

# --- 3.5 vertebral fracture assessment ------------------------------------
VFA_AGE_THRESHOLD_YEARS = 70
GENANT_FRACTURE_MIN_GRADE = 1

# --- 3.6 positioning review ----------------------------------------------
DEFECT_WEIGHTS = {
    "ROTATION_FEMUR": 3,
    "INCORRECT_ROI": 3,
    "INADEQUATE_SCAN_LENGTH": 3,
    "ABDUCTION_FEMUR": 2,
    "SPINE_NOT_STRAIGHT": 2,
    "MOTION_ARTIFACT": 2,
    "ARTIFACT_IN_FIELD": 1,
}
POSITIONING_REPEAT_THRESHOLD = 3
MAX_POSITIONING_REPEATS = 2

# --- 3.7 FRAX -------------------------------------------------------------
AGE_REFERENCE_YEARS = 50
AGE_POINTS_PER_YEAR = D("0.10")
SEX_POINTS_FEMALE = D("0.60")
SEX_POINTS_MALE = D("0.00")
BMI_POINTS_UNDER_20 = D("0.80")
BMI_POINTS_20_TO_30 = D("0.00")
BMI_POINTS_OVER_30 = D("-0.40")
BMI_LOW_BOUND = D("20.00")
BMI_HIGH_BOUND = D("30.00")
CRF_POINTS = (
    ("prior_fragility_fracture", D("1.90")),
    ("parental_hip_fracture", D("1.30")),
    ("current_smoker", D("0.90")),
    ("glucocorticoid_use", D("1.60")),
    ("rheumatoid_arthritis", D("1.20")),
    ("secondary_osteoporosis", D("0.80")),
)
ALCOHOL_RISK_MIN_UNITS = D("3.0")
ALCOHOL_POINTS = D("1.00")
BMD_POINTS_PER_T_UNIT = D("-1.20")
MAJOR_BASE = D("3.0")
MAJOR_SLOPE = D("6.0")
MAJOR_FLOOR = D("0.5")
MAJOR_CAP = D("60.0")
HIP_BASE = D("0.4")
HIP_SLOPE = D("1.6")
HIP_FLOOR = D("0.1")
HIP_CAP = D("30.0")
TREATMENT_THRESHOLD_MAJOR_PCT = D("20.0")
TREATMENT_THRESHOLD_HIP_PCT = D("3.0")

# --- 3.7/3.8 interval determination ---------------------------------------
OSTEOPOROSIS_T_MAX = D("-2.5")
OSTEOPENIA_T_MAX = D("-1.0")
BELOW_EXPECTED_Z_MAX = D("-2.0")
OSTEOPENIA_SHORT_INTERVAL_T_MAX = D("-2.0")
INTERVAL_OSTEOPOROSIS = 12
INTERVAL_OSTEOPENIA_SHORT = 12
INTERVAL_OSTEOPENIA_LONG = 24
INTERVAL_NORMAL = 60
INTERVAL_BELOW_EXPECTED = 24
INTERVAL_WITHIN_EXPECTED = 60
SIGNIFICANT_LOSS_INTERVAL_CAP = 12
NON_COMPARABLE_INTERVAL_CAP = 24
WHO_MALE_MIN_AGE_YEARS = 50

# --- 3.9 adherence --------------------------------------------------------
REFILL_PHARMACY_CLAIM_WEIGHT = D("1.0")
REFILL_PATIENT_REPORT_WEIGHT = D("0.5")
MPR_CAP = D("1.5")
MPR_ADHERENT_MIN = D("0.800")
MPR_PARTIAL_MIN = D("0.500")
DENOSUMAB_MAX_GAP_DAYS = 210
HOLIDAY_MIN_THERAPY_MONTHS = 60
HOLIDAY_REVIEW_INTERVAL_MONTHS = 24
MAX_CONSECUTIVE_NONADHERENT_REVIEWS = 2
FOLLOWUP_EARLY_WINDOW_DAYS = 7
FOLLOWUP_INTERVAL_MONTHS = {
    "BISPHOSPHONATE_ORAL": 3,
    "ANABOLIC_PTH": 3,
    "DENOSUMAB": 6,
    "SERM": 6,
    "BISPHOSPHONATE_IV": 12,
}
HOLIDAY_DRUG_CLASSES = ("BISPHOSPHONATE_ORAL", "BISPHOSPHONATE_IV")
HOLIDAY_MAX_T_SCORE = D("-2.5")

PAYER_FLOOR_FIELD = {
    "BASELINE_SCREENING": "baseline_screening_min_interval_months",
    "SERIAL_MONITORING": "baseline_screening_min_interval_months",
    "HIGH_RISK_CASE_FINDING": "high_risk_min_interval_months",
    "TREATMENT_MONITORING": "treatment_monitoring_min_interval_months",
}


def score_phantom_run(device, phantom_bmd):
    """Calculation 1a: deviation, deviation in SD units, and the result band."""
    deviation = rnd(dec(phantom_bmd) - dec(device["phantom_baseline_bmd_g_cm2"]), 4)
    sd_units = rnd(deviation / dec(device["phantom_baseline_sd_g_cm2"]), 3)
    magnitude = abs(sd_units)
    if magnitude <= QC_PASS_MAX_SD:
        result = "PASS"
    elif magnitude <= QC_WARN_MAX_SD:
        result = "WARN"
    else:
        result = "FAIL"
    return deviation, sd_units, result


def detect_shift(sd_units, preceding_daily_runs):
    """Calculation 1b: this run plus the two immediately preceding daily runs."""
    needed = QC_SHIFT_RUN_COUNT - 1
    if len(preceding_daily_runs) < needed:
        return False
    window = [sd_units] + [dec(row["deviation_sd_units"]) for row in preceding_daily_runs[:needed]]
    for value in window:
        if abs(value) < QC_SHIFT_MIN_SD or value == 0:
            return False
    signs = {1 if value > 0 else -1 for value in window}
    return len(signs) == 1


def precision_lsc(patient_count, scans_per_patient, rms_sd):
    """Calculation 2: degrees of freedom and the least significant change."""
    degrees_of_freedom = patient_count * (scans_per_patient - 1)
    if degrees_of_freedom < MIN_PRECISION_DEGREES_OF_FREEDOM:
        return degrees_of_freedom, None
    return degrees_of_freedom, rnd(LSC_COEFFICIENT * dec(rms_sd), 4)


def cross_calibration(baseline_values, new_values):
    """Calculation 3: phantom means, percent difference, factor and outcome."""
    baseline_mean = rnd(sum(dec(v) for v in baseline_values) / len(baseline_values), 4)
    new_mean = rnd(sum(dec(v) for v in new_values) / len(new_values), 4)
    percent_difference = rnd(D(100) * (new_mean - baseline_mean) / baseline_mean, 2)
    magnitude = abs(percent_difference)
    if magnitude < CROSS_CAL_TOLERANCE_PCT:
        outcome = "WITHIN_TOLERANCE_NO_FACTOR"
        factor = D("1.0000")
    elif magnitude <= CROSS_CAL_MAX_PCT:
        outcome = "FACTOR_APPLIED"
        factor = rnd(baseline_mean / new_mean, 4)
    else:
        outcome = "REJECTED_EXCESSIVE_DRIFT"
        factor = None
    return baseline_mean, new_mean, percent_difference, factor, outcome


def select_prior(candidate_pool, densitometer_id, calibration_generation):
    """Calculation 4: the three-stage comparison-prior waterfall."""
    def rank(row):
        return (row["submitted_at_utc"], row["created_at"], row["_seq"])

    same_device = [row for row in candidate_pool if row["densitometer_id"] == densitometer_id]
    if same_device:
        prior = max(same_device, key=rank)
        if prior["calibration_generation"] < calibration_generation:
            return prior, "PRIOR_CROSS_CAL_ADJUSTED"
        return prior, "COMPARABLE_SAME_DEVICE"
    if candidate_pool:
        return max(candidate_pool, key=rank), "NOT_COMPARABLE_DEVICE_MISMATCH"
    return None, "BASELINE_NO_PRIOR"


def site_scores(site_code, bmd, reference_mean, reference_sd,
                age_matched_mean, age_matched_sd, included_vertebrae):
    """Calculation 5: t-score, z-score, vertebral count and usability."""
    t_score = rnd((dec(bmd) - dec(reference_mean)) / dec(reference_sd), 1)
    z_score = rnd((dec(bmd) - dec(age_matched_mean)) / dec(age_matched_sd), 1)
    if site_code == "LUMBAR_SPINE":
        valid_count = len(included_vertebrae or [])
        usable = valid_count >= MIN_VALID_VERTEBRAE
    else:
        valid_count = 0
        usable = True
    return t_score, z_score, valid_count, usable


def diagnostic_selection(rows):
    """Calculation 6: lowest t-score, its site, and the lowest z-score."""
    candidates = [
        row for row in rows
        if row["site_usable_for_diagnosis"] and row["site_code"] in CENTRAL_SITES
    ]
    if not candidates:
        candidates = [row for row in rows if row["site_code"] == "FOREARM_33"]
    if not candidates:
        return None, None, None
    lowest_t = min(dec(row["t_score"]) for row in candidates)
    site = None
    for site_code in SITE_PRECEDENCE:
        for row in candidates:
            if row["site_code"] == site_code and dec(row["t_score"]) == lowest_t:
                site = site_code
                break
        if site is not None:
            break
    lowest_z = min(dec(row["z_score"]) for row in candidates)
    return lowest_t, site, lowest_z


def frax_points(patient, profile, femoral_neck_t_score, clock_date):
    """Calculation 7: the additive FRAX points model and both probabilities."""
    age_years = completed_years(patient["_birth_date"], clock_date)
    excess_years = age_years - AGE_REFERENCE_YEARS
    if excess_years < 0:
        excess_years = 0
    age_points = rnd(D(excess_years) * AGE_POINTS_PER_YEAR, 2)
    sex_points = rnd(SEX_POINTS_FEMALE if patient["sex"] == "FEMALE" else SEX_POINTS_MALE, 2)
    bmi_used = dec(profile["bmi"])
    if bmi_used < BMI_LOW_BOUND:
        bmi_points = BMI_POINTS_UNDER_20
    elif bmi_used <= BMI_HIGH_BOUND:
        bmi_points = BMI_POINTS_20_TO_30
    else:
        bmi_points = BMI_POINTS_OVER_30
    bmi_points = rnd(bmi_points, 2)
    clinical = D(0)
    for field, weight in CRF_POINTS:
        if profile[field]:
            clinical += weight
    if dec(profile["alcohol_units_per_day"]) >= ALCOHOL_RISK_MIN_UNITS:
        clinical += ALCOHOL_POINTS
    clinical_risk_points = rnd(clinical, 2)
    if femoral_neck_t_score is None:
        bmd_points = rnd(D(0), 2)
    else:
        bmd_points = rnd(dec(femoral_neck_t_score) * BMD_POINTS_PER_T_UNIT, 2)
    raw_score = rnd(age_points + sex_points + bmi_points + clinical_risk_points + bmd_points, 2)
    major = MAJOR_BASE + MAJOR_SLOPE * raw_score
    major = min(max(major, MAJOR_FLOOR), MAJOR_CAP)
    hip = HIP_BASE + HIP_SLOPE * raw_score
    hip = min(max(hip, HIP_FLOOR), HIP_CAP)
    major = rnd(major, 1)
    hip = rnd(hip, 1)
    major_met = major >= TREATMENT_THRESHOLD_MAJOR_PCT
    hip_met = hip >= TREATMENT_THRESHOLD_HIP_PCT
    if major_met and hip_met:
        basis = "BOTH"
    elif major_met:
        basis = "MAJOR_OSTEOPOROTIC"
    elif hip_met:
        basis = "HIP"
    else:
        basis = "NONE"
    return {
        "age_years": age_years,
        "bmi_used": bmi_used,
        "age_points": age_points,
        "sex_points": sex_points,
        "bmi_points": bmi_points,
        "clinical_risk_points": clinical_risk_points,
        "bmd_points": bmd_points,
        "raw_score": raw_score,
        "major_osteoporotic_10yr_pct": major,
        "hip_fracture_10yr_pct": hip,
        "treatment_threshold_met": major_met or hip_met,
        "threshold_basis": basis,
    }


def positioning_outcome(defect_codes, repeat_count):
    """Calculation 11: weighted severity, repeat criterion and outcome."""
    severity = sum(DEFECT_WEIGHTS[code] for code in set(defect_codes))
    criterion_met = severity >= POSITIONING_REPEAT_THRESHOLD
    if not criterion_met:
        outcome = "ACCEPTED"
    elif repeat_count < MAX_POSITIONING_REPEATS:
        outcome = "REPEAT_REQUIRED"
    else:
        outcome = "ACCEPTED_WITH_LIMITATION"
    return severity, criterion_met, outcome


def vfa_eligibility(policy, profile, age_years):
    """Calculation 12a: the first matching eligibility branch."""
    if profile is not None:
        height_loss = dec(profile["height_loss_cm"])
        if height_loss >= dec(policy["vfa_requires_height_loss_cm"]):
            return "ELIGIBLE_HEIGHT_LOSS"
        if profile["glucocorticoid_use"]:
            return "ELIGIBLE_GLUCOCORTICOID"
    if age_years >= VFA_AGE_THRESHOLD_YEARS:
        return "ELIGIBLE_AGE_THRESHOLD"
    return "NOT_ELIGIBLE"


def vfa_grading(genant_grades):
    """Calculation 12b: maximum grade and fracture count."""
    return (
        max(genant_grades),
        sum(1 for grade in genant_grades if grade >= GENANT_FRACTURE_MIN_GRADE),
    )


def payer_floor_months(policy, indication):
    return policy[PAYER_FLOOR_FIELD[indication]]


def frequency_eligibility(patient, policy, requested_date):
    """Calculation 9: lifetime cap first, then the grace-window comparison."""
    next_eligible = patient["next_eligible_scan_date"]
    if patient["lifetime_screening_scan_count"] >= policy["max_lifetime_screening_scans"]:
        return "INELIGIBLE_LIFETIME_CAP", next_eligible
    if next_eligible is None:
        return "ELIGIBLE", None
    earliest = next_eligible
    earliest_date = _as_date(earliest)
    if requested_date >= earliest_date:
        return "ELIGIBLE", earliest
    grace_start = earliest_date - _days(policy["repeat_scan_grace_days"])
    if requested_date >= grace_start:
        return "ELIGIBLE_WITH_GRACE", earliest
    return "INELIGIBLE_TOO_SOON", earliest


def _as_date(value):
    from util import parse_date
    return value if not isinstance(value, str) else parse_date(value)


def _days(count):
    from datetime import timedelta
    return timedelta(days=count)


def adherence_metrics(plan, refills, review_date, start_date):
    """Calculation 10: possession ratio, verdict and the denosumab gap."""
    window_days = (review_date - start_date).days
    eligible = [
        row for row in refills
        if _as_date(row["dispensed_date"]) >= start_date
        and _as_date(row["dispensed_date"]) < review_date
    ]
    covered = D(0)
    for row in eligible:
        if row["source"] == "PATIENT_REPORT":
            if plan["adherence_source_policy"] == "CLAIMS_ONLY":
                continue
            weight = REFILL_PATIENT_REPORT_WEIGHT
        else:
            weight = REFILL_PHARMACY_CLAIM_WEIGHT
        covered += D(row["days_supplied"]) * weight
    covered = rnd(covered, 1)
    if window_days > 0:
        ratio = rnd(min(MPR_CAP, covered / D(window_days)), 3)
    else:
        ratio = rnd(D(0), 3)
    if ratio >= MPR_ADHERENT_MIN:
        status = "ADHERENT"
    elif ratio >= MPR_PARTIAL_MIN:
        status = "PARTIAL"
    else:
        status = "NON_ADHERENT"
    gap_days = None
    if plan["drug_class"] == "DENOSUMAB" and eligible:
        latest = max(
            eligible,
            key=lambda row: (row["dispensed_date"], row["created_at"], row["_seq"]),
        )
        coverage_end = _as_date(latest["dispensed_date"]) + _days(latest["days_supplied"])
        gap_days = (review_date - coverage_end).days
        if gap_days < 0:
            gap_days = 0
    return {
        "adherence_window_days": window_days,
        "covered_days_supplied": covered,
        "medication_possession_ratio": ratio,
        "adherence_status": status,
        "denosumab_gap_days": gap_days,
    }


def holiday_eligible(plan, cumulative_months, last_finalized_session):
    """Calculation 10b: the three conjunctive drug-holiday conditions."""
    if plan["drug_class"] not in HOLIDAY_DRUG_CLASSES:
        return False
    if cumulative_months < HOLIDAY_MIN_THERAPY_MONTHS:
        return False
    if last_finalized_session is None:
        return False
    lowest = last_finalized_session.get("lowest_t_score")
    if lowest is None:
        return False
    return dec(lowest) > HOLIDAY_MAX_T_SCORE


def cumulative_therapy_months(start_date, review_date):
    months = completed_months(start_date, review_date)
    return months if months > 0 else 0
