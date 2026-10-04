"""Wire representation of every entity (SCAFFOLD 1.1 field lists)."""

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "hubs": (
        "iata_code", "name", "sort_window_open_minutes", "sort_window_close_minutes",
        "live_planned_package_total", "posture", "contingency_mode", "alternate_hub_id",
        "ops_run_index",
    ),
    "banks": (
        "hub_id", "bank_code", "scheduled_start_minutes", "scheduled_end_minutes",
        "actual_start_minutes", "hydraulic_crew_available", "status",
        "effective_sort_budget_minutes",
    ),
    "aircraft": (
        "bank_id", "tail_number", "origin_station_code", "scheduled_arrival_minutes",
        "actual_arrival_minutes", "capacity_weight_grams", "inbound_weight_grams",
        "unload_completed_minutes", "maintenance_hold", "status",
    ),
    "packages": (
        "hub_id", "aircraft_id", "tracking_number", "acknowledgement_number",
        "commodity_class", "destination_hub_code", "service_level",
        "commitment_cutoff_minutes", "planned_weight_grams", "rated_weight_grams",
        "dimension_weight_grams", "induction_status", "sort_status", "commitment_status",
        "handling_status", "last_sort_minutes", "buildup_id", "assigned_lane_id",
        "staged_feeder_id", "handling_posture", "commitment_posture",
        "final_commitment_minutes",
    ),
    "lanes": (
        "hub_id", "lane_code", "lane_kind", "commodity_capability",
        "capacity_weight_grams", "certified_until_minutes", "turnout_start_minutes",
        "turnout_end_minutes", "status", "lane_load_grams",
    ),
    "moves": (
        "hub_id", "aircraft_id", "sequence", "status", "weight_limit_grams",
        "planned_weight_grams", "loaded_weight_grams", "forward_capacity_grams",
        "load_plan_tier", "gateway_requirements",
    ),
    "buildups": (
        "hub_id", "load_move_id", "destination_gateway_code", "rated_weight_grams",
        "container_limit_grams", "hazardous_load", "hazardous_weight_grams",
        "hazardous_cap_grams", "requires_container", "status", "load_plan_tier",
    ),
    "feeders": (
        "hub_id", "feeder_code", "origin_station_code", "scheduled_departure_minutes",
        "stage_capacity_grams", "window_minutes", "status", "staged_weight_grams",
    ),
    "shifts": (
        "hub_id", "shift_code", "start_minutes", "end_minutes", "headcount",
        "productivity_grams_per_operator_hour", "forecast_volume_grams",
        "certified_for_hazmat", "volume_variance_pct", "staffing_posture", "status",
    ),
    # OpsRun and ServiceFailureClaim carry id and created_at only (PRD 2.8)
    "ops_runs": ("hub_id", "run_index", "minute_of_day", "level", "verdict"),
    "failures": (
        "hub_id", "package_id", "cause_code", "attributed_role", "failure_minutes",
        "refund_eligible", "refund_amount_cents", "status",
    ),
    "claims": ("service_failure_id", "claim_index", "outcome", "actor_role", "note"),
}

# OpsRun / ServiceFailureClaim are never modified in place.
_IMMUTABLE = ("ops_runs", "claims")


def to_dict(table, record):
    if record is None:
        return None
    if table in _IMMUTABLE:
        out = {"id": record.get("id"), "created_at": record.get("created_at")}
    else:
        out = {key: record.get(key) for key in COMMON}
    for field in FIELDS[table]:
        out[field] = record.get(field)
    return out


def to_list(table, records):
    return [to_dict(table, record) for record in records]