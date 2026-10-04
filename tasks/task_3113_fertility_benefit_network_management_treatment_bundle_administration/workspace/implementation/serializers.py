"""Public field maps — one per entity, in scaffold declaration order."""

from clock import fmt_dt

FIELDS = {
    "employer_accounts": [
        "id", "created_at", "updated_at", "version",
        "employer_name", "plan_year", "funding_type", "allocation_method",
        "enrollment_limit", "account_status", "active_member_count", "entitlement_count",
    ],
    "bundle_entitlements": [
        "id", "created_at", "updated_at", "version",
        "employer_account_id", "bundle_type", "lifetime_max_cycles", "max_cycles_per_year",
        "max_transfers_per_cycle", "pharmacy_pool_cents", "copay_max",
        "effective_from", "effective_to", "cycles_consumed", "cycles_committed",
        "cycles_remaining", "pharmacy_consumed_cents", "pharmacy_remaining_cents",
        "bundle_status",
    ],
    "care_advocates": [
        "id", "created_at", "updated_at", "version",
        "full_name", "states_licensed", "specializations", "caseload_limit",
        "credentials_expire_on", "current_caseload", "assignments_completed",
        "advocate_status",
    ],
    "members": [
        "id", "created_at", "updated_at", "version",
        "employer_account_id", "external_ref", "full_name", "state_code",
        "required_track", "member_status", "care_advocate_id", "clinic_id",
        "pathway_selected", "completed_cycles", "live_births_recorded",
        "intake_completed_at",
    ],
    "clinics": [
        "id", "created_at", "updated_at", "version",
        "legal_name", "npi", "required_quality_report_count", "state_code",
        "network_tier", "min_live_birth_rate_bps", "max_multiple_birth_rate_bps",
        "maturity_report_threshold", "live_birth_rate_bps", "multiple_birth_rate_bps",
        "composite_quality_bps", "cycles_reported", "clinic_status",
    ],
    "clinic_contracts": [
        "id", "created_at", "updated_at", "version",
        "clinic_id", "effective_from", "effective_to", "bundle_rates",
        "contracting_status", "frozen_reason",
    ],
    "treatment_plans": [
        "id", "created_at", "updated_at", "version",
        "member_id", "care_advocate_id", "bundle_entitlement_id", "clinic_id",
        "pathway_type", "plan_status", "planned_cycles", "min_inter_cycle_days",
        "selected_bundle_price_cents", "cycles_completed", "plan_blocked_reason",
    ],
    "preauthorizations": [
        "id", "created_at", "updated_at", "version",
        "treatment_plan_id", "cycle_sequence_index", "criteria_inputs",
        "member_cost_share_pct", "review_status", "consumption_status",
        "clinical_criteria_score", "approved_cycles", "consumed_cycles",
        "bundle_price_snapshot_cents", "effective_from", "effective_to",
        "denial_reason_code", "decision_actor",
    ],
    "treatment_cycles": [
        "id", "created_at", "updated_at", "version",
        "treatment_plan_id", "preauthorization_id", "member_id", "cycle_index",
        "cycle_status", "retrieval_date", "transfer_date", "embryos_transferred",
        "consumption_marker",
    ],
    "medication_orders": [
        "id", "created_at", "updated_at", "version",
        "member_id", "care_advocate_id", "preauthorization_id", "medication_code",
        "specialty_drug", "quantity", "days_supply", "acquisition_cost_cents",
        "dispensing_pharmacy", "pharmacy_status", "plan_paid_cents",
        "member_cost_cents", "dispensed_on",
    ],
    "pathway_requests": [
        "id", "created_at", "updated_at", "version",
        "member_id", "care_advocate_id", "pathway_type", "pathway_status",
        "consent_signed", "consent_signed_on", "gestational_carrier_ref",
        "donor_agency_ref", "coverage_pct", "pathway_cost_cents",
    ],
    "claims": [
        "id", "created_at", "updated_at", "version",
        "member_id", "preauthorization_id", "treatment_cycle_id",
        "service_category", "billed_cents", "claim_status", "allowed_cents",
        "member_cost_share_cents", "plan_paid_cents",
        "member_accumulator_before_cents", "member_accumulator_after_cents",
        "adjudication_basis", "pended_reason",
    ],
    "outcome_records": [
        "id", "created_at", "updated_at", "version",
        "clinic_id", "treatment_cycle_id", "member_id", "live_birth",
        "births_count", "multiple_birth", "gestational_weeks",
        "outcome_recorded_on", "outcome_status", "amendment_reason", "void_reason",
    ],
    "surrender_routes": [
        "id", "created_at", "updated_at", "version",
        "member_id", "pathway_type", "carrier_kind", "route_from", "route_to",
        "route_status", "surrender_cost_cents", "raw_cost_cents",
    ],
}

# Fields stored as datetimes and rendered as ISO 8601 UTC strings.
DATETIME_FIELDS = {
    "bundle_entitlements": ("effective_from", "effective_to"),
    "care_advocates": ("credentials_expire_on",),
    "members": ("intake_completed_at",),
    "clinic_contracts": ("effective_from", "effective_to"),
    "preauthorizations": ("effective_from", "effective_to"),
    "treatment_cycles": ("retrieval_date", "transfer_date"),
    "medication_orders": ("dispensed_on",),
    "pathway_requests": ("consent_signed_on",),
    "outcome_records": ("outcome_recorded_on",),
    "surrender_routes": ("route_from", "route_to"),
}


def serialize(collection, row):
    """Render one row using only its declared public fields."""
    out = {}
    dt_fields = DATETIME_FIELDS.get(collection, ())
    for name in FIELDS[collection]:
        if name not in row:
            continue
        value = row[name]
        if name in dt_fields:
            value = fmt_dt(value)
        out[name] = value
    return out


def serialize_many(collection, rows):
    return [serialize(collection, r) for r in rows]