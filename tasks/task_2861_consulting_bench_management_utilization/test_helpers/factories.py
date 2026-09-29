"""Payload factories for the Consulting Bench Management API (PRD §3, §4).

Every money / rate / percentage / FTE value is emitted as a JSON *number*
because PRD §2.6 declares all such fields as numbers, not strings. Every
`_date` / `_on` field is emitted as a YYYY-MM-DD string and every instant as a
full ISO-8601 UTC instant, exactly as PRD §2.5 declares.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    DATE_FRI_AUG_28,
    DATE_MON_AUG_03,
)

_email_counter = itertools.count(1)
_name_counter = itertools.count(1)
_code_counter = itertools.count(1)


def unique_email(stem: str = "consultant") -> str:
    return f"{stem}.{next(_email_counter)}@firm.test"


def unique_name(stem: str = "Group") -> str:
    return f"{stem} {next(_name_counter)}"


def unique_skill_code(stem: str = "SKILL") -> str:
    return f"{stem}_{next(_code_counter)}"


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``...`` (i.e. "leave omitted")."""
    return {k: v for k, v in payload.items() if v is not ...}


# ------------------------------------------------------------ PracticeGroup --
def practice_group_payload(
    name: str = "Cloud NA",
    geography_code: str = "NA",
    parent_group_id: Any = ...,
    external_sourcing_cap_pct: Any = ...,
    level_targets: Any = ...,
) -> Dict[str, Any]:
    return _prune(
        {
            "name": name,
            "geography_code": geography_code,
            "parent_group_id": parent_group_id,
            "external_sourcing_cap_pct": external_sourcing_cap_pct,
            "level_targets": level_targets,
        }
    )


# -------------------------------------------------------------------- Skill --
def skill_payload(
    code: str = "CLOUD_ARCH",
    name: str = "Cloud Architecture",
    family: str = "CLOUD",
    scarcity_index: Any = ...,
    retired: Any = ...,
) -> Dict[str, Any]:
    return _prune(
        {
            "code": code,
            "name": name,
            "family": family,
            "scarcity_index": scarcity_index,
            "retired": retired,
        }
    )


# --------------------------------------------------------------- Consultant --
def consultant_payload(
    practice_group_id: str,
    full_name: str = "Ada Byron",
    email: str = "ada.byron@firm.test",
    level: str = "CONSULTANT",
    home_city: str = "Boston",
    home_geo_code: str = "NA",
    cost_rate_usd_per_hour: float = 120.00,
    standard_bill_rate_usd_per_hour: float = 300.00,
    travel_max_nights_per_week: Any = ...,
    travel_willing_international: Any = ...,
    development_goal_skill_id: Any = ...,
    industry_experience: Any = ...,
) -> Dict[str, Any]:
    return _prune(
        {
            "full_name": full_name,
            "email": email,
            "level": level,
            "practice_group_id": practice_group_id,
            "home_city": home_city,
            "home_geo_code": home_geo_code,
            "cost_rate_usd_per_hour": cost_rate_usd_per_hour,
            "standard_bill_rate_usd_per_hour": standard_bill_rate_usd_per_hour,
            "travel_max_nights_per_week": travel_max_nights_per_week,
            "travel_willing_international": travel_willing_international,
            "development_goal_skill_id": development_goal_skill_id,
            "industry_experience": industry_experience,
        }
    )


def industry_experience(industry_code: str = "RETAIL", years: float = 2) -> List[Dict]:
    return [{"industry_code": industry_code, "years": years}]


# ------------------------------------------------------------ SkillAssertion --
def skill_assertion_payload(
    consultant_id: str,
    skill_id: str,
    proficiency_level: int = 4,
    certification_code: Any = ...,
    certification_expires_on: Any = ...,
    last_used_on: Any = ...,
) -> Dict[str, Any]:
    return _prune(
        {
            "consultant_id": consultant_id,
            "skill_id": skill_id,
            "proficiency_level": proficiency_level,
            "certification_code": certification_code,
            "certification_expires_on": certification_expires_on,
            "last_used_on": last_used_on,
        }
    )


# ------------------------------------------------------- DemandOpportunity --
def demand_payload(
    practice_group_id: str,
    required_skill_id: str,
    client_name: str = "Acme Retail",
    min_proficiency_level: int = 3,
    required_fte: float = 1.00,
    win_probability_pct: int = 60,
    start_date: str = DATE_MON_AUG_03,
    end_date: str = DATE_FRI_AUG_28,
    industry_code: str = "RETAIL",
    onsite_nights_per_week: int = 2,
    standard_rate_usd_per_hour: float = 250.00,
    requested_rate_usd_per_hour: float = 240.00,
    is_international: Any = ...,
) -> Dict[str, Any]:
    return _prune(
        {
            "client_name": client_name,
            "practice_group_id": practice_group_id,
            "required_skill_id": required_skill_id,
            "min_proficiency_level": min_proficiency_level,
            "required_fte": required_fte,
            "win_probability_pct": win_probability_pct,
            "start_date": start_date,
            "end_date": end_date,
            "industry_code": industry_code,
            "onsite_nights_per_week": onsite_nights_per_week,
            "is_international": is_international,
            "standard_rate_usd_per_hour": standard_rate_usd_per_hour,
            "requested_rate_usd_per_hour": requested_rate_usd_per_hour,
        }
    )


# ---------------------------------------------------------------- Assignment --
def assignment_payload(
    consultant_id: str,
    demand_opportunity_id: str,
    expected_consultant_version: int,
    allocation_pct: float = 100.00,
    start_date: str = DATE_MON_AUG_03,
    end_date: str = "2026-08-29",
    category: str = "BILLABLE",
) -> Dict[str, Any]:
    return {
        "consultant_id": consultant_id,
        "demand_opportunity_id": demand_opportunity_id,
        "allocation_pct": allocation_pct,
        "start_date": start_date,
        "end_date": end_date,
        "category": category,
        "expected_consultant_version": expected_consultant_version,
    }


# --------------------------------------------------------- ReskillingProgram --
def reskilling_program_payload(
    skill_id: str,
    target_proficiency_level: int = 5,
    cohort_start_on: str = "2026-09-01",
    cohort_end_on: str = "2026-09-30",
    seat_capacity: int = 2,
    cooldown_days: Any = ...,
) -> Dict[str, Any]:
    return _prune(
        {
            "skill_id": skill_id,
            "target_proficiency_level": target_proficiency_level,
            "cohort_start_on": cohort_start_on,
            "cohort_end_on": cohort_end_on,
            "seat_capacity": seat_capacity,
            "cooldown_days": cooldown_days,
        }
    )


# -------------------------------------------------------- SubcontractorFirm --
def firm_payload(
    name: str = "Northwind Partners",
    geo_code: str = "NA",
    max_concurrent_placements: int = 1,
    pass_through_rate_usd_per_hour: float = 150.00,
    markup_pct: Any = ...,
    approval_status: Any = ...,
) -> Dict[str, Any]:
    return _prune(
        {
            "name": name,
            "geo_code": geo_code,
            "max_concurrent_placements": max_concurrent_placements,
            "pass_through_rate_usd_per_hour": pass_through_rate_usd_per_hour,
            "markup_pct": markup_pct,
            "approval_status": approval_status,
        }
    )


# -------------------------------------------------------- ExternalPlacement --
def placement_payload(
    subcontractor_firm_id: str,
    demand_opportunity_id: str,
    fte: float = 1.00,
    start_date: str = DATE_MON_AUG_03,
    end_date: str = "2026-08-17",
) -> Dict[str, Any]:
    return {
        "subcontractor_firm_id": subcontractor_firm_id,
        "demand_opportunity_id": demand_opportunity_id,
        "fte": fte,
        "start_date": start_date,
        "end_date": end_date,
    }


# ----------------------------------------------------------- DiscountApproval --
def discount_approval_payload(
    demand_opportunity_id: str,
    requested_rate_usd_per_hour: float,
    expected_opportunity_version: int,
    decision_note: Any = ...,
) -> Dict[str, Any]:
    return _prune(
        {
            "demand_opportunity_id": demand_opportunity_id,
            "requested_rate_usd_per_hour": requested_rate_usd_per_hour,
            "expected_opportunity_version": expected_opportunity_version,
            "decision_note": decision_note,
        }
    )


# ---------------------------------------------------------- UtilizationPeriod --
def utilization_period_payload(
    period_start_on: str = DATE_MON_AUG_03,
    period_end_on: str = DATE_FRI_AUG_28,
    holiday_hours: Any = ...,
) -> Dict[str, Any]:
    return _prune(
        {
            "period_start_on": period_start_on,
            "period_end_on": period_end_on,
            "holiday_hours": holiday_hours,
        }
    )


# ------------------------------------------------------------- HiringForecast --
def hiring_forecast_payload(
    skill_code: str = "CLOUD_ARCH",
    geography_code: str = "NA",
    horizon_start_on: str = DATE_MON_AUG_03,
    horizon_end_on: str = DATE_FRI_AUG_28,
    basis: Any = ...,
) -> Dict[str, Any]:
    return _prune(
        {
            "skill_code": skill_code,
            "geography_code": geography_code,
            "horizon_start_on": horizon_start_on,
            "horizon_end_on": horizon_end_on,
            "basis": basis,
        }
    )
