"""Row -> JSON serializers. Field sets follow SCAFFOLD entity declarations."""
from db import iso, to_num

# field kinds: "v" verbatim, "t" timestamp, "n" numeric (Decimal -> float)
_SPECS = {
    "PlanUpdate": [
        ("title", "v"), ("jurisdiction_code", "v"), ("base_year", "v"),
        ("horizon_year", "v"), ("status", "v"), ("state_review_status", "v"),
        ("compliance_posture", "v"), ("adopted_scenario_id", "v"),
        ("open_consistency_link_count", "v"),
        ("required_elements_complete_count", "v"),
        ("housing_shortfall_total", "v"), ("equity_share_pct", "n"),
        ("participation_weight_total", "n"),
        ("underrepresented_weight_total", "n"), ("resubmission_count", "v"),
        ("monitoring_on_track_count", "v"), ("state_findings", "v"),
        ("adopted_at", "t"),
    ],
    "InventoryDataset": [
        ("plan_update_id", "v"), ("inventory_type", "v"), ("vintage_year", "v"),
        ("status", "v"), ("record_count", "v"), ("vacant_acres", "n"),
        ("underutilized_acres", "n"), ("infrastructure_constrained_acres", "n"),
        ("allowed_density_units_per_acre", "n"),
        ("referencing_scenario_count", "v"), ("authored_by_user_id", "v"),
        ("certified_by_user_id", "v"),
    ],
    "GrowthScenario": [
        ("plan_update_id", "v"), ("land_use_inventory_id", "v"), ("label", "v"),
        ("method", "v"), ("horizon_year", "v"), ("base_households", "v"),
        ("annual_household_growth_rate", "n"), ("job_growth_total", "v"),
        ("demolition_replacement_units", "v"), ("capacity_variant", "v"),
        ("land_capacity_units", "v"), ("projected_demand_units", "v"),
        ("capacity_gap_units", "v"), ("status", "v"),
    ],
    "HousingAllocation": [
        ("plan_update_id", "v"), ("income_tier", "v"), ("assigned_units", "v"),
        ("cycle_deadline", "t"), ("tier_capacity_units", "v"),
        ("carryover_in_units", "v"), ("accommodated_units", "v"),
        ("shortfall_units", "v"),
    ],
    "PlanElement": [
        ("plan_update_id", "v"), ("element_type", "v"), ("title", "v"),
        ("draft_body", "v"), ("policy_count", "v"), ("status", "v"),
        ("consistency_status", "v"), ("revision_round", "v"),
        ("authored_by_user_id", "v"), ("reviewed_by_user_id", "v"),
    ],
    "ConsistencyLink": [
        ("source_element_id", "v"), ("target_element_id", "v"),
        ("dependency_type", "v"), ("status", "v"),
        ("reconciliation_note", "v"), ("reconciled_by_user_id", "v"),
        ("staled_by_amendment_id", "v"),
    ],
    "Venue": [
        ("name", "v"), ("seated_capacity", "v"),
        ("turnover_buffer_minutes", "v"), ("ada_accessible", "v"),
        ("transit_served", "v"),
    ],
    "EngagementActivity": [
        ("plan_update_id", "v"), ("venue_id", "v"), ("activity_type", "v"),
        ("title", "v"), ("start_at", "t"), ("end_at", "t"),
        ("interpretation_offered", "v"), ("status", "v"), ("record_count", "v"),
        ("underrepresented_record_count", "v"), ("weighting_variant", "v"),
        ("total_weighted_count", "n"), ("underrepresented_weighted_count", "n"),
        ("equity_share_pct", "n"),
    ],
    "ParticipationRecord": [
        ("activity_id", "v"), ("respondent_ref", "v"),
        ("demographic_group", "v"), ("interpreter_used", "v"),
        ("census_tract", "v"), ("comment_text", "v"),
        ("is_underrepresented", "v"), ("weight", "n"),
    ],
    "EnvironmentalReview": [
        ("plan_update_id", "v"), ("document_type", "v"), ("title", "v"),
        ("status", "v"), ("comment_period_days", "v"), ("circulated_at", "t"),
        ("comment_period_ends_at", "t"), ("preferred_alternative_id", "v"),
        ("alternative_count", "v"), ("certified_at", "t"),
    ],
    "PlanAlternative": [
        ("environmental_review_id", "v"), ("label", "v"),
        ("traffic_vmt_index", "n"), ("ghg_index", "n"), ("habitat_index", "n"),
        ("water_index", "n"), ("raw_impact_score", "n"),
        ("mitigation_credit", "n"), ("net_impact_score", "n"), ("status", "v"),
    ],
    "Hearing": [
        ("plan_update_id", "v"), ("body_type", "v"), ("scheduled_start", "t"),
        ("scheduled_end", "t"), ("notice_published_at", "t"), ("status", "v"),
        ("outcome", "v"), ("amendment_count", "v"),
        ("adopted_amendment_count", "v"), ("opened_at", "t"),
        ("closed_at", "t"),
    ],
    "Amendment": [
        ("hearing_id", "v"), ("target_element_id", "v"), ("summary", "v"),
        ("policy_delta", "v"), ("status", "v"),
        ("element_version_at_proposal", "v"), ("applied_policy_count", "v"),
        ("prior_element_status", "v"), ("proposed_by_user_id", "v"),
    ],
    "ImplementationAction": [
        ("plan_update_id", "v"), ("source_element_id", "v"),
        ("action_type", "v"), ("title", "v"), ("indicator_name", "v"),
        ("indicator_direction", "v"), ("baseline_value", "n"),
        ("target_value", "n"), ("latest_reading_value", "n"),
        ("latest_reading_at", "t"), ("reading_count", "v"),
        ("on_track", "v"), ("status", "v"), ("due_at", "t"),
    ],
}

# Venue and ParticipationRecord carry no updated_at and no version (PRD 2.4).
_UNVERSIONED = ("Venue", "ParticipationRecord")


def _dump(entity, row):
    out = {"id": row["id"]}
    for name, kind in _SPECS[entity]:
        value = row.get(name)
        if kind == "t":
            out[name] = iso(value)
        elif kind == "n":
            out[name] = to_num(value)
        else:
            out[name] = value
    out["created_at"] = iso(row["created_at"])
    if entity not in _UNVERSIONED:
        out["updated_at"] = iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def plan_update(row):
    return _dump("PlanUpdate", row)


def inventory(row):
    return _dump("InventoryDataset", row)


def scenario(row):
    return _dump("GrowthScenario", row)


def allocation(row):
    return _dump("HousingAllocation", row)


def element(row):
    return _dump("PlanElement", row)


def link(row):
    return _dump("ConsistencyLink", row)


def venue(row):
    return _dump("Venue", row)


def activity(row):
    return _dump("EngagementActivity", row)


def participation(row):
    return _dump("ParticipationRecord", row)


def review(row):
    return _dump("EnvironmentalReview", row)


def alternative(row):
    return _dump("PlanAlternative", row)


def hearing(row):
    return _dump("Hearing", row)


def amendment(row):
    return _dump("Amendment", row)


def action(row):
    return _dump("ImplementationAction", row)
