"""Dual-variant payment pricing (PRD 3.7)."""

from decimal import Decimal

import calc
import lookup
from store import db, new_row

STANDARD = "STANDARD_LTCH_PPS"
SITE_NEUTRAL = "SITE_NEUTRAL"


def drg_in_force(stay, override_drg_rate_id=None):
    """The override rate entry when one was supplied, else the referral's anticipated DRG."""
    if override_drg_rate_id is not None:
        return lookup.drg_rate(override_drg_rate_id)
    referral = db.referrals[stay["referral_id"]]
    return db.drg_rates[referral["drg_rate_id"]]


def select_variant(stay):
    """PRD 3.7 step one: patient-level criteria decide the variant."""
    referral = db.referrals[stay["referral_id"]]
    if referral["prior_acute_discharge_at"] is None:
        return SITE_NEUTRAL
    icu_days = referral["icu_days_at_referral"]
    if icu_days is not None and icu_days >= calc.ICU_DAYS_SITE_NEUTRAL_MIN:
        return STANDARD
    plan = lookup.stay_weaning_plan(stay["id"])
    if plan is not None and Decimal(plan["vent_hours_total"]) >= calc.VENT_HOURS_SITE_NEUTRAL_MIN:
        return STANDARD
    return SITE_NEUTRAL


def refresh_stay_outlier_fields(stay, drg):
    """Covered length of stay is already banked; the SSO threshold follows the DRG in force."""
    threshold = calc.sso_threshold_days(drg["alos_days"])
    covered = stay["covered_los_days"] if stay["covered_los_days"] is not None else 0
    stay["sso_threshold_days"] = threshold
    stay["short_stay_outlier_applied"] = covered <= threshold


def create_determination(stay, drg, priced_by_user_id, recalculation_reason=None):
    """Price the stay under both variants and store the whole audit trail on one row.

    The caller is responsible for bumping the stay's version exactly once.
    """
    refresh_stay_outlier_fields(stay, drg)
    covered = stay["covered_los_days"] if stay["covered_los_days"] is not None else 0
    sso_applied = stay["short_stay_outlier_applied"]
    cost = stay["estimated_cost_cents"]

    full_amount = calc.full_standard_amount_cents(drg)
    standard_base = calc.standard_base_cents(drg, full_amount, covered, sso_applied)
    site_neutral_base = calc.site_neutral_base_cents(drg, cost)

    standard_variant_amount = standard_base + calc.high_cost_outlier(standard_base, cost)
    site_neutral_variant_amount = site_neutral_base + calc.high_cost_outlier(site_neutral_base, cost)

    variant = select_variant(stay)
    base_payment = standard_base if variant == STANDARD else site_neutral_base
    outlier_payment = calc.high_cost_outlier(base_payment, cost)
    total_payment = base_payment + outlier_payment
    payment_pct = calc.discharge_payment_pct(base_payment, full_amount)

    determination = new_row("determinations")
    determination.update({
        "stay_id": stay["id"],
        "payment_variant": variant,
        "drg_code_used": drg["drg_code"],
        "relative_weight_used": drg["relative_weight"],
        "alos_days_used": drg["alos_days"],
        "ipps_per_diem_used_cents": drg["ipps_comparable_per_diem_cents"],
        "ipps_full_used_cents": drg["ipps_comparable_full_cents"],
        "covered_los_days_used": covered,
        "full_standard_amount_cents": full_amount,
        "standard_variant_amount_cents": standard_variant_amount,
        "site_neutral_variant_amount_cents": site_neutral_variant_amount,
        "base_payment_cents": base_payment,
        "outlier_payment_cents": outlier_payment,
        "total_payment_cents": total_payment,
        "discharge_payment_pct": payment_pct,
        "short_stay_outlier_applied": sso_applied,
        "status": "DRAFT",
        "priced_by_user_id": priced_by_user_id,
        "finalized_by_user_id": None,
        "recalculation_reason": recalculation_reason,
        "void_reason": None,
    })
    db.determinations[determination["id"]] = determination

    stay["discharge_payment_pct"] = payment_pct
    stay["payment_review_status"] = "PRICED"
    return determination
