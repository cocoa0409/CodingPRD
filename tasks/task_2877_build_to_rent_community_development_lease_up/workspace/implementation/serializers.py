"""Response payloads. Every field traces to the entity definitions of PRD sections 2.4 and 3."""
from __future__ import annotations

COMMUNITY_FIELDS = (
    "id", "name", "market_code", "total_planned_units", "product_mix",
    "single_ownership_covenant", "concession_budget_cents", "facility_commitment_cents",
    "maintenance_tech_headcount", "plat_status", "plat_revision_round",
    "plat_submitted_by_user_id", "plat_package_reference", "lifecycle_status",
    "management_mode", "pm_company_name", "pm_effective_from", "facility_status",
    "posture", "released_unit_count", "available_unit_count", "leased_unit_count",
    "occupancy_ratio", "amenity_delivery_ratio", "committed_concession_cents",
    "construction_impact_credit_cents", "created_at", "updated_at", "version",
)

PHASE_FIELDS = (
    "id", "community_id", "predecessor_phase_id", "sequence_index", "kind",
    "planned_unit_count", "amenity_weight", "construction_window_start",
    "construction_window_end", "status", "halt_count", "pre_halt_status",
    "released_homesite_count", "leased_homesite_count",
    "created_at", "updated_at", "version",
)

HOMESITE_FIELDS = (
    "id", "phase_id", "lot_number", "product_type", "bedrooms", "square_feet",
    "status", "off_market_reason", "occupancy_certificate_number",
    "occupancy_certificate_issued_at", "released_at", "turn_cycle_count",
    "last_turn_ready_at", "created_at", "updated_at", "version",
)

SCHEDULE_FIELDS = (
    "id", "community_id", "product_type", "effective_from", "repricing_mode",
    "asking_rent_cents", "applied_growth_bps", "status", "superseded_at",
    "published_by_user_id", "created_at", "updated_at", "version",
)

PROGRAM_FIELDS = (
    "id", "community_id", "program_code", "tier", "free_weeks", "amortization_mode",
    "eligible_product_types", "restricted_posture_eligible", "max_budget_cents",
    "committed_cents", "status", "superseded_at", "created_at", "updated_at", "version",
)

HOUSEHOLD_FIELDS = (
    "id", "primary_applicant_name", "email", "household_size", "monthly_income_cents",
    "credit_tier", "active_lease_count", "created_at", "updated_at", "version",
)

LEASE_FIELDS = (
    "id", "homesite_id", "household_id", "concession_program_id", "priced_by_schedule_id",
    "term_months", "start_date", "end_date", "base_rent_cents",
    "community_services_fee_cents", "gross_monthly_charge_cents", "total_concession_cents",
    "concession_schedule", "monthly_concession_credit_cents", "first_period_charge_cents",
    "net_effective_rent_cents", "concession_applied_cents", "concession_remaining_cents",
    "credits_applied_count", "lease_status", "concession_status",
    "concession_requested_by_user_id", "concession_decided_by_user_id",
    "cancellation_reason", "signed_by_name", "executed_at", "notice_date",
    "move_out_date", "construction_impact_credit_cents",
    "created_at", "updated_at", "version",
)

TURN_ORDER_FIELDS = (
    "id", "homesite_id", "window_start", "window_end", "scope", "tech_count",
    "material_cost_cents", "window_hours", "labor_cost_cents", "total_turn_cost_cents",
    "tenant_recoverable_cents", "community_opex_cents", "capital_reserve_cents",
    "status", "completed_at", "created_at", "updated_at", "version",
)

# An absorption review is an immutable snapshot: it carries only id and created_at
# beyond its own data, with no updated_at and no version (PRD section 2.4).
REVIEW_FIELDS = (
    "id", "community_id", "product_type", "window_start", "window_end",
    "planned_absorption_units", "actual_absorption_units", "available_supply_units",
    "posture_at_review", "pacing_index", "concession_tier", "recommended_growth_bps",
    "created_by_user_id", "created_at",
)


def _project(record, fields):
    return {field: record.get(field) for field in fields}


def community(record):
    return _project(record, COMMUNITY_FIELDS)


def phase(record):
    return _project(record, PHASE_FIELDS)


def homesite(record):
    return _project(record, HOMESITE_FIELDS)


def schedule(record):
    return _project(record, SCHEDULE_FIELDS)


def program(record):
    return _project(record, PROGRAM_FIELDS)


def household(record):
    return _project(record, HOUSEHOLD_FIELDS)


def lease(record):
    payload = _project(record, LEASE_FIELDS)
    payload["concession_schedule"] = [
        {"period_index": entry["period_index"], "credit_cents": entry["credit_cents"]}
        for entry in record.get("concession_schedule") or []
    ]
    return payload


def turn_order(record):
    return _project(record, TURN_ORDER_FIELDS)


def review(record):
    return _project(record, REVIEW_FIELDS)
