"""Row -> JSON projections. Every clock-dependent field is derived here, at
serialization time, so a clock move needs no batch job to be visible."""
from decimal import Decimal

from derive import (
    allocated_pct,
    assertion_status,
    availability,
    coverage,
    effective_rate,
    group_derived,
    level_target,
    period_metrics,
    realization,
    spell_age_days,
    weighted_fte,
)
from helpers import fmt_date, fmt_instant
from store import db


def common(row):
    body = {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
    }
    if "version" in row:
        body["updated_at"] = fmt_instant(row["updated_at"])
        body["version"] = row["version"]
    return body


def practice_group(row):
    body = common(row)
    body.update(
        {
            "name": row["name"],
            "geography_code": row["geography_code"],
            "parent_group_id": row.get("parent_group_id"),
            "external_sourcing_cap_pct": row["external_sourcing_cap_pct"],
            "level_targets": row.get("level_targets") or {},
        }
    )
    body.update(group_derived(row))
    return body


def skill(row):
    body = common(row)
    body.update(
        {
            "code": row["code"],
            "name": row["name"],
            "family": row["family"],
            "scarcity_index": row["scarcity_index"],
            "retired": row["retired"],
        }
    )
    return body


def consultant(row):
    body = common(row)
    body.update(
        {
            "full_name": row["full_name"],
            "email": row["email"],
            "level": row["level"],
            "practice_group_id": row["practice_group_id"],
            "home_city": row["home_city"],
            "home_geo_code": row["home_geo_code"],
            "cost_rate_usd_per_hour": row["cost_rate_usd_per_hour"],
            "standard_bill_rate_usd_per_hour": row["standard_bill_rate_usd_per_hour"],
            "travel_max_nights_per_week": row["travel_max_nights_per_week"],
            "travel_willing_international": row["travel_willing_international"],
            "development_goal_skill_id": row.get("development_goal_skill_id"),
            "industry_experience": [
                {"industry_code": entry["industry_code"], "years": entry["years"]}
                for entry in (row.get("industry_experience") or [])
            ],
            "availability_status": availability(row),
            "allocated_pct": allocated_pct(row),
            "separated_on": fmt_instant(row["separated_on"]) if row.get("separated_on") else None,
        }
    )
    return body


def skill_assertion(row):
    body = common(row)
    body.update(
        {
            "consultant_id": row["consultant_id"],
            "skill_id": row["skill_id"],
            "proficiency_level": row["proficiency_level"],
            "certification_code": row.get("certification_code"),
            "certification_expires_on": fmt_date(row.get("certification_expires_on")),
            "last_used_on": fmt_date(row.get("last_used_on")),
            "assertion_status": assertion_status(row),
        }
    )
    return body


def demand(row):
    body = common(row)
    body.update(
        {
            "client_name": row["client_name"],
            "practice_group_id": row["practice_group_id"],
            "required_skill_id": row["required_skill_id"],
            "min_proficiency_level": row["min_proficiency_level"],
            "required_fte": row["required_fte"],
            "win_probability_pct": row["win_probability_pct"],
            "start_date": fmt_date(row["start_date"]),
            "end_date": fmt_date(row["end_date"]),
            "industry_code": row["industry_code"],
            "onsite_nights_per_week": row["onsite_nights_per_week"],
            "is_international": row["is_international"],
            "standard_rate_usd_per_hour": row["standard_rate_usd_per_hour"],
            "requested_rate_usd_per_hour": row["requested_rate_usd_per_hour"],
            "approved_rate_usd_per_hour": row.get("approved_rate_usd_per_hour"),
            "effective_rate_usd_per_hour": effective_rate(row),
            "pipeline_status": row["pipeline_status"],
            "staffing_mode": row.get("staffing_mode"),
            "weighted_fte": weighted_fte(row),
            "closed_outcome": row.get("closed_outcome"),
        }
    )
    body.update(coverage(row))
    body.update(realization(row))
    return body


def assignment(row):
    body = common(row)
    body.update(
        {
            "consultant_id": row["consultant_id"],
            "demand_opportunity_id": row["demand_opportunity_id"],
            "allocation_pct": row["allocation_pct"],
            "start_date": fmt_date(row["start_date"]),
            "end_date": fmt_date(row["end_date"]),
            "category": row["category"],
            "bill_rate_usd_per_hour": row["bill_rate_usd_per_hour"],
            "cost_rate_usd_per_hour": row["cost_rate_usd_per_hour"],
            "match_score": row["match_score"],
            "status": row["status"],
            "confirmed_on": fmt_date(row.get("confirmed_on")),
            "activated_on": fmt_date(row.get("activated_on")),
            "released_on": fmt_date(row.get("released_on")),
        }
    )
    return body


def bench_spell(row):
    body = common(row)
    body.update(
        {
            "consultant_id": row["consultant_id"],
            "started_on": fmt_date(row["started_on"]),
            "age_reset_on": fmt_date(row.get("age_reset_on")),
            "ended_on": fmt_date(row.get("ended_on")),
            "state": row["state"],
            "escalation_count": row["escalation_count"],
            "age_days": spell_age_days(row),
            "reskilling_program_id": row.get("reskilling_program_id"),
            "internal_project_code": row.get("internal_project_code"),
            "investment_started_on": fmt_date(row.get("investment_started_on")),
            "investment_ended_on": fmt_date(row.get("investment_ended_on")),
            "separation_proposed_by_user_id": row.get("separation_proposed_by_user_id"),
            "separation_decided_by_user_id": row.get("separation_decided_by_user_id"),
            "separation_decision": row.get("separation_decision"),
        }
    )
    return body


def seats_taken(program):
    return sum(
        1
        for spell in db.all("bench_spells")
        if spell.get("reskilling_program_id") == program["id"] and spell["state"] == "RESKILLING"
    )


def program(row):
    body = common(row)
    body.update(
        {
            "skill_id": row["skill_id"],
            "target_proficiency_level": row["target_proficiency_level"],
            "cohort_start_on": fmt_date(row["cohort_start_on"]),
            "cohort_end_on": fmt_date(row["cohort_end_on"]),
            "seat_capacity": row["seat_capacity"],
            "seats_taken": seats_taken(row),
            "cooldown_days": row["cooldown_days"],
            "status": row["status"],
        }
    )
    return body


def active_placements_count(firm):
    return sum(
        1
        for placement in db.all("external_placements")
        if placement["subcontractor_firm_id"] == firm["id"]
        and placement["status"] in ("APPROVED", "ACTIVE")
    )


def firm(row):
    body = common(row)
    body.update(
        {
            "name": row["name"],
            "geo_code": row["geo_code"],
            "max_concurrent_placements": row["max_concurrent_placements"],
            "markup_pct": row["markup_pct"],
            "pass_through_rate_usd_per_hour": row["pass_through_rate_usd_per_hour"],
            "approval_status": row["approval_status"],
            "active_placements_count": active_placements_count(row),
        }
    )
    return body


def placement(row):
    body = common(row)
    body.update(
        {
            "subcontractor_firm_id": row["subcontractor_firm_id"],
            "demand_opportunity_id": row["demand_opportunity_id"],
            "fte": row["fte"],
            "start_date": fmt_date(row["start_date"]),
            "end_date": fmt_date(row["end_date"]),
            "pass_through_rate_usd_per_hour": row["pass_through_rate_usd_per_hour"],
            "bill_rate_usd_per_hour": row["bill_rate_usd_per_hour"],
            "status": row["status"],
            "terminated_on": fmt_date(row.get("terminated_on")),
        }
    )
    return body


def discount_approval(row):
    body = common(row)
    body.update(
        {
            "demand_opportunity_id": row["demand_opportunity_id"],
            "requested_rate_usd_per_hour": row["requested_rate_usd_per_hour"],
            "standard_rate_usd_per_hour": row["standard_rate_usd_per_hour"],
            "discount_pct": row["discount_pct"],
            "provisional_realization_pct": row["provisional_realization_pct"],
            "blended_cost_rate_usd_per_hour": row["blended_cost_rate_usd_per_hour"],
            "projected_margin_pct": row["projected_margin_pct"],
            "required_tier": row["required_tier"],
            "tier_escalated": row["tier_escalated"],
            "status": row["status"],
            "requested_by_user_id": row["requested_by_user_id"],
            "decided_by_user_id": row.get("decided_by_user_id"),
            "decision_note": row.get("decision_note"),
            "revision_count": row["revision_count"],
        }
    )
    return body


def utilization_period(row):
    body = common(row)
    body.update(
        {
            "consultant_id": row["consultant_id"],
            "period_start_on": fmt_date(row["period_start_on"]),
            "period_end_on": fmt_date(row["period_end_on"]),
            "holiday_hours": row["holiday_hours"],
            "target_utilization_pct": row["target_utilization_pct"],
            "status": row["status"],
        }
    )
    body.update(period_metrics(row))
    return body


def hiring_forecast(row):
    body = common(row)
    body.update(
        {
            "skill_code": row["skill_code"],
            "geography_code": row["geography_code"],
            "horizon_start_on": fmt_date(row["horizon_start_on"]),
            "horizon_end_on": fmt_date(row["horizon_end_on"]),
            "basis": row["basis"],
            "weighted_demand_fte": row["weighted_demand_fte"],
            "internal_supply_fte": row["internal_supply_fte"],
            "external_supply_fte": row["external_supply_fte"],
            "gap_fte": row["gap_fte"],
            "recommended_hires": row["recommended_hires"],
            "generated_at": fmt_instant(row["generated_at"]),
        }
    )
    return body


BY_KIND = {
    "practice_groups": practice_group,
    "skills": skill,
    "consultants": consultant,
    "skill_assertions": skill_assertion,
    "demand_opportunities": demand,
    "assignments": assignment,
    "bench_spells": bench_spell,
    "reskilling_programs": program,
    "subcontractor_firms": firm,
    "external_placements": placement,
    "discount_approvals": discount_approval,
    "utilization_periods": utilization_period,
    "hiring_forecasts": hiring_forecast,
}


def render(row):
    return BY_KIND[row["_kind"]](row)


def render_all(rows):
    return [render(row) for row in rows]
