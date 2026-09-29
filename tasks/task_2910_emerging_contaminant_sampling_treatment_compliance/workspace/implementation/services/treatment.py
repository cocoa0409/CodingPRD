"""Pilot scoring, technology selection and capital-project origination
(PRD sections 3.7 and 3.8).
"""

from datetime import timedelta
from decimal import Decimal

import constants as C
import db
from db import store
from numeric import divide, q2
from services import finance

ZERO2 = Decimal("0.00")


def pilots_for(evaluation_id):
    return [
        pilot
        for pilot in db.sorted_rows("pilots")
        if pilot["treatment_evaluation_id"] == evaluation_id
    ]


def removal_pct(influent, effluent):
    if influent is None or Decimal(influent) == 0:
        return ZERO2
    return q2(divide((Decimal(influent) - Decimal(effluent)) * 100, Decimal(influent)))


def lifecycle_cost_score(lifecycle_cost_cents):
    value = Decimal(100) - divide(Decimal(lifecycle_cost_cents), C.LIFECYCLE_COST_DIVISOR_CENTS)
    if value < 0:
        value = Decimal(0)
    return q2(value)


def technology_score(removal, lifecycle_score, residuals_burden, footprint, om_complexity):
    """Each weighted term is rounded to two places first; the already-rounded
    terms are then summed with no further rounding."""
    weights = C.TECHNOLOGY_WEIGHTS
    return (
        q2(weights["removal"] * Decimal(removal))
        + q2(weights["lifecycle_cost"] * Decimal(lifecycle_score))
        + q2(weights["residuals_burden"] * Decimal(residuals_burden))
        + q2(weights["footprint"] * Decimal(footprint))
        + q2(weights["om_complexity"] * Decimal(om_complexity))
    )


def windows_overlap(new_start, new_end, existing_start, existing_end):
    """Half-open overlap against an existing window widened by the
    decontamination buffer on both sides."""
    buffer = timedelta(hours=C.PILOT_DECONTAMINATION_BUFFER_HOURS)
    widened_start = existing_start - buffer
    widened_end = existing_end + buffer
    return new_start < widened_end and widened_start < new_end


def conflicting_pilot(entry_point_id, new_start, new_end, exclude_pilot_id=None):
    for pilot in db.sorted_rows("pilots"):
        if exclude_pilot_id is not None and pilot["id"] == exclude_pilot_id:
            continue
        if pilot["status"] not in ("PLANNED", "RUNNING"):
            continue
        evaluation = store.evaluations.get(pilot["treatment_evaluation_id"])
        if evaluation is None or evaluation["entry_point_id"] != entry_point_id:
            continue
        if windows_overlap(new_start, new_end, pilot["window_start_at"], pilot["window_end_at"]):
            return pilot
    return None


def qualifying_pilots(evaluation_id):
    return [
        pilot
        for pilot in pilots_for(evaluation_id)
        if pilot["status"] == "COMPLETED"
        and pilot["removal_pct"] is not None
        and pilot["removal_pct"] >= C.MIN_REMOVAL_PCT
    ]


def select_winner(evaluation_id):
    candidates = qualifying_pilots(evaluation_id)
    if not candidates:
        return None
    candidates.sort(
        key=lambda p: (
            -p["technology_score"],
            p["lifecycle_cost_cents"],
            p["created_at"],
            p["_seq"],
        )
    )
    return candidates[0]


def create_capital_project(evaluation, entry_point, winner):
    technology = winner["technology"]
    project = db.insert(
        "projects",
        {
            "entry_point_id": entry_point["id"],
            "treatment_evaluation_id": evaluation["id"],
            "selected_technology": technology,
            "required_disposal_method": C.FULL_SCALE_DISPOSAL_BY_TECHNOLOGY[technology],
            "concentrate_permit_required": C.CONCENTRATE_PERMIT_BY_TECHNOLOGY[technology],
            "capital_cost_cents": winner["capital_cost_estimate_cents"],
            "annual_om_cost_cents": winner["annual_om_estimate_cents"],
            "served_account_count": entry_point["served_account_count"],
            "annual_billed_kgal": entry_point["annual_billed_kgal"],
            "current_annual_revenue_cents": entry_point["baseline_annual_revenue_cents"],
            "rate_design": "UNIFORM",
            "funding_awarded_cents": 0,
            "grant_equivalent_cents": 0,
            "loan_principal_cents": 0,
            "recovered_cents": 0,
            "local_share_cents": 0,
            "borrowed_cents": 0,
            "annual_debt_service_cents": 0,
            "base_annual_requirement_cents": 0,
            "provisional_rate_impact_pct": ZERO2,
            "surcharge_bp": 0,
            "final_annual_requirement_cents": 0,
            "rate_impact_pct": ZERO2,
            "uniform_monthly_increase_cents": 0,
            "volumetric_rate_increase_cents_per_kgal": 0,
            "volumetric_monthly_increase_cents": 0,
            "monthly_bill_increase_cents": 0,
            "funding_status": "NOT_APPLIED",
            "construction_status": "PLANNED",
        },
    )
    finance.recompute_project(project)
    return project


def waste_classification_for(leachate):
    if Decimal(leachate) >= C.LEACHATE_HAZARDOUS_NG_PER_L:
        return "HAZARDOUS"
    if Decimal(leachate) >= C.LEACHATE_SPECIAL_NG_PER_L:
        return "SPECIAL_WASTE"
    return "NON_HAZARDOUS_SOLID"
