"""Entity specifications: field inventory, input coercion, creation and serialization."""
import uuid

from core import DB, fail, D  # noqa: F401

COMMON = ["id", "created_at", "updated_at", "version"]

# name -> {fields: [...], required: [...], ints: [...], nums: [...], bools: [...],
#          enums: {...}, system: {...}, defaults: {...}}
SPECS = {
    "region_hubs": {
        "fields": ["name", "total_newsroom_headcount", "max_print_tonnage_budget_cents",
                   "transfer_cost_ceiling_cents", "min_on_time_ratio_pct",
                   "press_posture", "legal_notice_block", "unassigned_headcount"],
        "required": ["name", "total_newsroom_headcount", "max_print_tonnage_budget_cents",
                     "transfer_cost_ceiling_cents"],
        "ints": ["total_newsroom_headcount", "max_print_tonnage_budget_cents",
                 "transfer_cost_ceiling_cents", "min_on_time_ratio_pct",
                 "unassigned_headcount"],
        "nums": [], "bools": ["legal_notice_block"],
        "enums": {"press_posture": ["OPEN", "RESTRICTED", "SUSPENDED"]},
        "defaults": {"min_on_time_ratio_pct": 90, "press_posture": "OPEN",
                     "legal_notice_block": False, "unassigned_headcount": 0},
    },
    "regions": {
        "fields": ["region_hub_id", "name", "daily_headcount_floor", "daily_headcount_cap",
                   "allocation_priority", "region_need_score", "guaranteed_headcount",
                   "allocated_newsroom_headcount", "member_market_count", "status"],
        "required": ["name", "daily_headcount_floor", "daily_headcount_cap",
                     "allocation_priority"],
        "ints": ["daily_headcount_floor", "daily_headcount_cap", "allocation_priority",
                 "guaranteed_headcount", "allocated_newsroom_headcount",
                 "member_market_count"],
        "nums": ["region_need_score"], "bools": [],
        "enums": {"status": ["active", "consolidated"]},
        "defaults": {"status": "active", "region_need_score": 0, "guaranteed_headcount": 0,
                     "allocated_newsroom_headcount": 0, "member_market_count": 0},
    },
    "print_sites": {
        "fields": ["print_site_hub_id", "code", "press_units", "shifts_per_night",
                   "copies_per_hour_per_press", "distinct_shifts_per_night",
                   "loading_slot_minutes", "max_concurrent_departures", "allocation_method",
                   "capacity_copies", "allocated_copies", "capacity_remaining_copies",
                   "annualized_savings_cents", "realized_savings_cents",
                   "savings_divergence_cents", "status"],
        "required": ["code", "press_units", "shifts_per_night", "copies_per_hour_per_press",
                     "max_concurrent_departures", "allocation_method"],
        "ints": ["press_units", "shifts_per_night", "copies_per_hour_per_press",
                 "distinct_shifts_per_night", "loading_slot_minutes",
                 "max_concurrent_departures", "capacity_copies", "allocated_copies",
                 "capacity_remaining_copies"],
        "nums": ["annualized_savings_cents", "realized_savings_cents",
                 "savings_divergence_cents"],
        "bools": [],
        "enums": {"allocation_method": ["PRIORITY", "PROPORTIONAL"],
                  "status": ["active", "closing", "consolidating", "closed"]},
        "defaults": {"distinct_shifts_per_night": 4, "loading_slot_minutes": 30,
                     "status": "active", "allocated_copies": 0,
                     "annualized_savings_cents": 0, "realized_savings_cents": 0,
                     "savings_divergence_cents": 0},
    },
    "print_markets": {
        "fields": ["region_id", "name", "publication_deadline_utc", "on_time_margin_minutes",
                   "per_copy_revenue_cents", "daily_route_cost_ceiling_cents",
                   "weighted_demand_units", "print_edition_per_week",
                   "guaranteed_floor_copies", "selected_print_route_id",
                   "replacement_route_id", "print_site_transfer_cost_cents",
                   "print_site_transfer_credit_cents", "net_print_site_transfer_cost_cents",
                   "route_selection_status", "delivery_boycott_active",
                   "transfer_cost_disputed", "target_print_edition_per_week",
                   "notices_dispatched_at", "renewals_accepted_count",
                   "single_copy_market_rule", "newsstand_contribution_cents",
                   "carrier_contribution_cents", "keeps_print_single_copy", "status",
                   "frequency_change_status"],
        "required": ["name", "per_copy_revenue_cents", "daily_route_cost_ceiling_cents",
                     "weighted_demand_units", "print_edition_per_week"],
        "ints": ["on_time_margin_minutes", "per_copy_revenue_cents",
                 "daily_route_cost_ceiling_cents", "weighted_demand_units",
                 "print_edition_per_week", "guaranteed_floor_copies",
                 "target_print_edition_per_week", "renewals_accepted_count"],
        "nums": ["print_site_transfer_cost_cents", "print_site_transfer_credit_cents",
                 "net_print_site_transfer_cost_cents", "newsstand_contribution_cents",
                 "carrier_contribution_cents"],
        "bools": ["delivery_boycott_active", "transfer_cost_disputed",
                  "keeps_print_single_copy"],
        "enums": {"single_copy_market_rule": ["newsstand", "carrier"],
                  "route_selection_status": ["current", "needs_reassignment"],
                  "status": ["active", "consolidation_planned", "transfer_in_progress",
                             "withdrawn"],
                  "frequency_change_status": ["none", "proposed", "notices_dispatched",
                                              "applied", "rejected"]},
        "defaults": {"publication_deadline_utc": "05:30", "on_time_margin_minutes": 30,
                     "guaranteed_floor_copies": 0, "single_copy_market_rule": "carrier",
                     "status": "active", "frequency_change_status": "none",
                     "renewals_accepted_count": 0, "selected_print_route_id": None,
                     "notices_dispatched_at": None, "delivery_boycott_active": False,
                     "transfer_cost_disputed": False},
    },
    "print_routes": {
        "fields": ["origin_print_site_id", "destination_market_id", "transit_minutes",
                   "buffer_minutes", "dispatch_cutoff_utc", "is_direct_hop",
                   "distance_miles", "marginal_mileage_cost", "stops_per_night",
                   "total_copies_allocated", "route_transport_cost",
                   "marginal_cost_per_copy_cents", "status"],
        "required": ["destination_market_id", "transit_minutes", "dispatch_cutoff_utc",
                     "is_direct_hop"],
        "ints": ["transit_minutes", "buffer_minutes", "stops_per_night",
                 "total_copies_allocated"],
        "nums": ["distance_miles", "marginal_mileage_cost", "route_transport_cost",
                 "marginal_cost_per_copy_cents"],
        "bools": ["is_direct_hop"],
        "enums": {"status": ["eligible", "committed", "orphaned"]},
        "defaults": {"buffer_minutes": 45, "status": "eligible"},
    },
    "editions": {
        "fields": ["print_market_id", "assigned_print_site_id", "slug", "page_count",
                   "requested_print_run_copies", "allocated_print_run_copies",
                   "press_run_hours", "press_ready_utc", "latest_edition_ready_utc",
                   "minutes_late", "late_edition_penalty_cents", "is_on_time",
                   "late_sports_engineering_flag", "legal_notice_count", "correction_open",
                   "correction_redispatch_cost_cents", "next_edition_slot_taken",
                   "second_edition_slot_open", "status"],
        "required": ["assigned_print_site_id", "slug", "page_count",
                     "requested_print_run_copies", "late_sports_engineering_flag",
                     "legal_notice_count"],
        "ints": ["page_count", "requested_print_run_copies", "allocated_print_run_copies",
                 "minutes_late", "late_edition_penalty_cents", "legal_notice_count",
                 "next_edition_slot_taken"],
        "nums": ["press_run_hours", "correction_redispatch_cost_cents"],
        "bools": ["is_on_time", "late_sports_engineering_flag", "correction_open",
                  "second_edition_slot_open"],
        "enums": {"status": ["in_production", "on_time_dispatch", "late_dispatch",
                             "delivered_market", "reverted_to_digital"]},
        "defaults": {"correction_open": False, "next_edition_slot_taken": 0,
                     "second_edition_slot_open": False, "status": "in_production",
                     "press_run_hours": 0, "allocated_print_run_copies": 0},
    },
    "delivery_contractors": {
        "fields": ["contractor_hub_id", "name", "pay_basis", "per_copy_rate_cents",
                   "min_stop_guarantee", "net_60_available", "cost_per_copy_ceiling_cents",
                   "last_load_claim_weight_lbs", "sanction_reason_code", "status"],
        "required": ["name", "pay_basis", "per_copy_rate_cents", "min_stop_guarantee",
                     "net_60_available", "cost_per_copy_ceiling_cents",
                     "last_load_claim_weight_lbs"],
        "ints": ["per_copy_rate_cents", "min_stop_guarantee", "cost_per_copy_ceiling_cents",
                 "last_load_claim_weight_lbs"],
        "nums": [], "bools": ["net_60_available"],
        "enums": {"pay_basis": ["PER_STOP", "PER_COPY"],
                  "status": ["active", "suspended", "terminated"]},
        "defaults": {"status": "active", "sanction_reason_code": None},
    },
    "delivery_routes": {
        "fields": ["delivery_contractor_id", "print_market_id", "route_code",
                   "stop_capacity", "per_stop_fee_cents", "dist_per_stop_miles",
                   "cost_per_copy_ceiling_cents", "printed_copies_surcharge_cents",
                   "cost_run_date", "base_cost_cents", "last_cost_run_date",
                   "printed_copies_last_run", "copy_volume_tier_pct",
                   "contractor_status_factor", "copies_carried_night", "route_night_cost",
                   "cost_per_copy_cents", "status"],
        "required": ["print_market_id", "route_code", "stop_capacity", "per_stop_fee_cents",
                     "dist_per_stop_miles", "cost_per_copy_ceiling_cents",
                     "printed_copies_surcharge_cents", "cost_run_date"],
        "ints": ["stop_capacity", "per_stop_fee_cents", "cost_per_copy_ceiling_cents",
                 "printed_copies_surcharge_cents", "printed_copies_last_run",
                 "copies_carried_night"],
        "nums": ["dist_per_stop_miles", "base_cost_cents", "copy_volume_tier_pct",
                 "contractor_status_factor", "route_night_cost", "cost_per_copy_cents"],
        "bools": [],
        "enums": {"status": ["prepared", "contract_active", "suspended", "terminated"]},
        "defaults": {"status": "prepared", "last_cost_run_date": None,
                     "printed_copies_last_run": 0, "copies_carried_night": 0,
                     "copy_volume_tier_pct": 0.0, "contractor_status_factor": 1.0,
                     "route_night_cost": 0, "cost_per_copy_cents": 0},
    },
    "delivery_stops": {
        "fields": ["delivery_route_id", "print_market_id", "stop_code",
                   "contracted_daily_copies", "contracted_daily_fee_cents",
                   "pause_start_date", "pause_end_date", "pause_window_days", "status"],
        "required": ["print_market_id", "stop_code", "contracted_daily_copies",
                     "contracted_daily_fee_cents"],
        "ints": ["contracted_daily_copies", "contracted_daily_fee_cents",
                 "pause_window_days"],
        "nums": [], "bools": [],
        "enums": {"status": ["active", "paused", "terminated"]},
        "defaults": {"pause_start_date": None, "pause_end_date": None,
                     "pause_window_days": 0, "status": "active"},
    },
    "subscribers": {
        "fields": ["delivery_stop_id", "subscriber_ref", "remaining_print_issues",
                   "paid_through_utc", "print_issue_value_cents", "migration_credit_cents",
                   "churn_retention_credit_cents", "offer_recommendation", "status",
                   "offer_status", "delivery_status"],
        "required": ["subscriber_ref", "remaining_print_issues", "paid_through_utc",
                     "print_issue_value_cents"],
        "ints": ["remaining_print_issues", "print_issue_value_cents",
                 "migration_credit_cents", "churn_retention_credit_cents"],
        "nums": [], "bools": [],
        "enums": {"offer_recommendation": ["PRINT_CREDIT", "DIGITAL_UPGRADE",
                                           "FULL_REFUND"],
                  "status": ["active", "paused", "migrated", "churned_pending_retention",
                             "churned"],
                  "offer_status": ["none", "offered", "accepted", "declined"],
                  "delivery_status": ["none", "paused", "resumed", "terminated"]},
        "defaults": {"status": "active", "offer_status": "none", "delivery_status": "none"},
    },
    "newsroom_positions": {
        "fields": ["region_id", "role_code", "expertise_code", "monthly_cost_cents",
                   "allocated_headcount", "status"],
        "required": ["role_code", "expertise_code", "monthly_cost_cents"],
        "ints": ["monthly_cost_cents", "allocated_headcount"],
        "nums": [], "bools": [],
        "enums": {"status": ["open", "closed"]},
        "defaults": {"status": "open", "allocated_headcount": 0},
    },
    "newsroom_changes": {
        "fields": ["newsroom_position_id", "to_region_id", "from_region_id",
                   "effective_date", "layoff_order_index", "requested_slots",
                   "allocated_slots", "residual_headcount", "severance_cost_cents",
                   "created_by", "status"],
        "required": ["newsroom_position_id", "to_region_id", "from_region_id",
                     "effective_date", "layoff_order_index", "requested_slots"],
        "ints": ["layoff_order_index", "requested_slots", "allocated_slots",
                 "residual_headcount"],
        "nums": ["severance_cost_cents"], "bools": [],
        "enums": {"status": ["proposed", "approved", "applied", "rejected"]},
        "defaults": {"status": "proposed", "allocated_slots": 0, "residual_headcount": 0,
                     "severance_cost_cents": 0},
    },
    "title_closures": {
        "fields": ["title_hub_id", "title_code", "archive_retention_years",
                   "digital_replacement_url", "archive_handoff_checksum", "status"],
        "required": ["title_code", "archive_retention_years", "digital_replacement_url"],
        "ints": ["archive_retention_years"],
        "nums": [], "bools": [],
        "enums": {"status": ["announced", "notice_published", "suspended", "merged",
                             "archived"]},
        "defaults": {"status": "announced", "archive_handoff_checksum": None},
    },
    "retention_actions": {
        "fields": ["subscriber_contract_id", "retention_offer_code",
                   "retention_credit_cents", "cooling_off_expires_utc",
                   "eligibility_policy_id", "status"],
        "required": ["retention_offer_code", "retention_credit_cents",
                     "eligibility_policy_id"],
        "ints": ["retention_credit_cents"], "nums": [], "bools": [],
        "enums": {"status": ["open", "accepted", "expired", "cancelled"]},
        "defaults": {"status": "open"},
    },
}


def spec_fields(coll):
    return COMMON + SPECS[coll]["fields"]


def stamp(row):
    row["updated_at"] = DB.clock.iso()


def bump(row):
    row["version"] = int(row.get("version", 1)) + 1
    stamp(row)


def touch(row):
    """Recomputation is an ordinary mutation: refresh timestamp and version."""
    bump(row)


def new_row(coll, system=None):
    sp = SPECS[coll]
    row = {
        "id": str(uuid.uuid4()),
        "created_at": DB.clock.iso(),
        "updated_at": DB.clock.iso(),
        "version": 1,
    }
    for f in sp["fields"]:
        row[f] = None
    for f, v in sp.get("defaults", {}).items():
        row[f] = v
    for f, v in (system or {}).items():
        row[f] = v
    return row


def _coerce(coll, field, value):
    sp = SPECS[coll]
    if value is None:
        return None
    if field in sp["ints"]:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            fail("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
        try:
            iv = int(value)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
        if D(value) != D(iv):
            fail("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
        return iv
    if field in sp["nums"]:
        try:
            return float(value)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Field %s must be a number." % field)
    if field in sp["bools"]:
        if not isinstance(value, bool):
            fail("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
        return value
    if field in sp["enums"]:
        if value not in sp["enums"][field]:
            fail("ERR_INVALID_REQUEST", "Field %s has an unrecognised value." % field)
        return value
    return value


def apply_input(coll, row, data, required, extra_allowed=()):
    """Validate and apply a request body onto a new row."""
    sp = SPECS[coll]
    allowed = set(sp["fields"]) | set(sp["enums"].keys()) | set(extra_allowed)
    for key in data:
        if key not in allowed:
            fail("ERR_INVALID_REQUEST", "Unknown field %s." % key)
    for f in required:
        if f not in data or data[f] is None:
            fail("ERR_INVALID_REQUEST", "Field %s is required." % f)
        if f not in sp["ints"] and f not in sp["nums"] and f not in sp["bools"] \
                and f not in sp["enums"] and isinstance(data[f], str) and data[f] == "":
            fail("ERR_INVALID_REQUEST", "Field %s must not be empty." % f)
    for key, value in data.items():
        if key in extra_allowed:
            continue
        row[key] = _coerce(coll, key, value)
    return row