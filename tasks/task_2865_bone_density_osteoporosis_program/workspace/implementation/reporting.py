"""Calculation 8: the seven ordered steps of the report interpretation."""
from decimal import Decimal

import calc
import queries
from db import db, today
from util import completed_years, dec, rnd

D = Decimal
ACTIVE_PLAN_STATUSES = ("ON_THERAPY", "ADHERENCE_HOLD", "DRUG_HOLIDAY")


def classify(patient, session, age_years):
    who_path = (
        (patient["sex"] == "FEMALE" and patient["postmenopausal"])
        or (patient["sex"] == "MALE" and age_years >= calc.WHO_MALE_MIN_AGE_YEARS)
    )
    if who_path:
        lowest_t = session["lowest_t_score"]
        if lowest_t is None:
            return "T_SCORE_WHO", None
        value = dec(lowest_t)
        if value <= calc.OSTEOPOROSIS_T_MAX:
            category = "OSTEOPOROSIS"
        elif value <= calc.OSTEOPENIA_T_MAX:
            category = "OSTEOPENIA"
        else:
            category = "NORMAL"
        return "T_SCORE_WHO", category
    lowest_z = session["lowest_z_score"]
    if lowest_z is None:
        return "Z_SCORE_AGE_MATCHED", None
    if dec(lowest_z) <= calc.BELOW_EXPECTED_Z_MAX:
        return "Z_SCORE_AGE_MATCHED", "BELOW_EXPECTED_RANGE_FOR_AGE"
    return "Z_SCORE_AGE_MATCHED", "WITHIN_EXPECTED_RANGE_FOR_AGE"


def _usable_at(session_id, site_code):
    for row in queries.measurements(session_id):
        if row["site_code"] == site_code and row["site_usable_for_diagnosis"]:
            return row
    return None


def serial_comparison(session):
    """Step two: the least-significant-change interpretation."""
    blank = {
        "lsc_site_code": None,
        "current_bmd_used_g_cm2": None,
        "prior_bmd_used_g_cm2": None,
        "bmd_change_g_cm2": None,
        "bmd_change_pct": None,
    }
    if session["prior_session_id"] is None:
        blank["lsc_interpretation"] = "NO_PRIOR"
        return blank
    if session["prior_comparison_status"] == "NOT_COMPARABLE_DEVICE_MISMATCH":
        blank["lsc_interpretation"] = "NOT_COMPARABLE_DEVICE"
        return blank
    prior_session = db.scan_sessions.get(session["prior_session_id"])
    site_code = None
    current_row = None
    prior_row = None
    for candidate in calc.LSC_SITE_PRECEDENCE:
        current_row = _usable_at(session["id"], candidate)
        prior_row = _usable_at(prior_session["id"], candidate) if prior_session else None
        if current_row is not None and prior_row is not None:
            site_code = candidate
            break
    if site_code is None:
        blank["lsc_interpretation"] = "NO_COMMON_SITE"
        return blank
    factor = D("1.0000")
    if session["prior_comparison_status"] == "PRIOR_CROSS_CAL_ADJUSTED":
        factor = dec(session["applied_cross_cal_factor"])
    current_bmd = dec(current_row["bmd_g_cm2"])
    adjusted_prior = rnd(dec(prior_row["bmd_g_cm2"]) * factor, 4)
    difference = current_bmd - adjusted_prior
    change = rnd(difference, 4)
    change_pct = rnd(D(100) * difference / adjusted_prior, 2)
    lsc = dec(session["applied_lsc_g_cm2"])
    if abs(change) < lsc:
        interpretation = "NO_SIGNIFICANT_CHANGE"
    elif change <= -lsc:
        interpretation = "SIGNIFICANT_LOSS"
    else:
        interpretation = "SIGNIFICANT_GAIN"
    return {
        "lsc_site_code": site_code,
        "current_bmd_used_g_cm2": current_bmd,
        "prior_bmd_used_g_cm2": adjusted_prior,
        "bmd_change_g_cm2": change,
        "bmd_change_pct": change_pct,
        "lsc_interpretation": interpretation,
    }


def clinical_interval(category, session, lsc_interpretation):
    """Step three: the category interval, then the two caps in order."""
    lowest_t = session["lowest_t_score"]
    if category == "OSTEOPOROSIS":
        months = calc.INTERVAL_OSTEOPOROSIS
    elif category == "OSTEOPENIA":
        short = lowest_t is not None and dec(lowest_t) <= calc.OSTEOPENIA_SHORT_INTERVAL_T_MAX
        months = calc.INTERVAL_OSTEOPENIA_SHORT if short else calc.INTERVAL_OSTEOPENIA_LONG
    elif category == "NORMAL":
        months = calc.INTERVAL_NORMAL
    elif category == "BELOW_EXPECTED_RANGE_FOR_AGE":
        months = calc.INTERVAL_BELOW_EXPECTED
    else:
        months = calc.INTERVAL_WITHIN_EXPECTED
    if lsc_interpretation == "SIGNIFICANT_LOSS":
        months = min(months, calc.SIGNIFICANT_LOSS_INTERVAL_CAP)
    if lsc_interpretation in ("NOT_COMPARABLE_DEVICE", "NO_COMMON_SITE"):
        months = min(months, calc.NON_COMPARABLE_INTERVAL_CAP)
    return months


def recommended_action(patient, category, frax, lsc_interpretation,
                       recommended_months, clinical_months):
    """Step six: the first matching branch wins."""
    threshold_met = frax is not None and frax["treatment_threshold_met"]
    if category == "OSTEOPOROSIS" or threshold_met:
        for plan in queries.plans_of_patient(patient["id"]):
            if plan["status"] in ACTIVE_PLAN_STATUSES:
                return "CONTINUE_TREATMENT"
        return "INITIATE_TREATMENT"
    if lsc_interpretation == "SIGNIFICANT_LOSS":
        return "REFER_SECONDARY_WORKUP"
    if recommended_months > clinical_months:
        return "PAYER_LIMITED_INTERVAL"
    return "ROUTINE_INTERVAL"


def audit_elements(report, session):
    """Step seven: the fixed-order narrative audit."""
    missing = []
    if report["lsc_interpretation"] in ("NOT_COMPARABLE_DEVICE", "NO_COMMON_SITE") \
            and report["non_comparability_note"] is None:
        missing.append("LSC_NON_COMPARABILITY_NOTE")
    if session["vfa_performed"] and report["vfa_narrative"] is None:
        missing.append("VFA_FINDINGS")
    report["missing_element_codes"] = missing
    report["required_elements_complete"] = not missing


def derive(report, session):
    """Re-derive every computed field of a report from current session state."""
    patient = db.patients[session["patient_id"]]
    order = queries.order_of_session(session)
    policy = queries.policy_of(patient)
    frax = None
    if report["frax_assessment_id"] is not None:
        frax = db.frax_assessments.get(report["frax_assessment_id"])

    age_years = completed_years(patient["_birth_date"], today())
    report["patient_age_years"] = age_years
    basis, category = classify(patient, session, age_years)
    report["classification_basis"] = basis
    report["diagnostic_category"] = category

    report.update(serial_comparison(session))
    report["applied_lsc_g_cm2"] = session["applied_lsc_g_cm2"]

    months = clinical_interval(category, session, report["lsc_interpretation"])
    report["clinical_interval_months"] = months
    floor = calc.payer_floor_months(policy, order["indication"])
    report["payer_floor_months"] = floor
    recommended = max(months, floor)
    report["recommended_interval_months"] = recommended
    report["recommended_action"] = recommended_action(
        patient, category, frax, report["lsc_interpretation"], recommended, months
    )
    audit_elements(report, session)
    return report
