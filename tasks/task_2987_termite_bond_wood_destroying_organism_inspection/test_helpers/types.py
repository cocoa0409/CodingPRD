"""Entity field contracts for the Termite Bond & WDO Inspection API.

Each entry lists the field names that a persisted resource of that type must
expose, split into the common envelope fields and the domain-specific fields.

Three record types are immutable by design and carry neither ``updated_at``
nor ``version``: a graph cell notation, a pesticide application record, and a
bait-station service visit.  Every other resource carries the full common
field set.
"""

# Common fields present on mutable resources.
COMMON_FIELDS_MUTABLE = ("id", "created_at", "updated_at", "version")

# Common fields present on the three immutable record types.
COMMON_FIELDS_IMMUTABLE = ("id", "created_at")

# Fields that must be ABSENT from the three immutable record types.
FORBIDDEN_IMMUTABLE_FIELDS = ("updated_at", "version")


PROPERTY_FIELDS = (
    "address_line1",
    "state_code",
    "construction_type",
    "square_footage",
    "linear_footage",
    "year_built",
    "crawl_clearance_inches",
    "has_attached_structures",
    "total_conducive_condition_count",
    "waived_conducive_condition_count",
    "open_conducive_condition_count",
    "active_infestation_on_record",
)

INSPECTOR_FIELDS = (
    "full_name",
    "license_number",
    "license_state",
    "license_categories",
    "license_expires_on",
    "fumigation_endorsement",
    "ce_credits",
    "status",
)

INSPECTION_FIELDS = (
    "property_id",
    "inspector_id",
    "purpose",
    "status",
    "scheduled_start_at",
    "scheduled_end_at",
    "closing_date",
    "supersedes_inspection_id",
    "sequence_no",
    "graph_completed_at",
    "no_findings_attested",
    "findings_count",
    "conducive_condition_count",
    "active_infestation_found",
    "damage_estimate_total_usd",
)

# Immutable: a graph cell notation.
GRAPH_FINDING_FIELDS = (
    "inspection_id",
    "finding_type",
    "grid_ref",
    "organism",
    "severity",
    "conducive_code",
    "damage_estimate_usd",
    "pre_existing",
)

TREATMENT_PLAN_FIELDS = (
    "property_id",
    "inspection_id",
    "applicator_id",
    "method",
    "chemical_product_code",
    "status",
    "fumigation_permit_number",
    "fumigation_start_at",
    "fumigation_reentry_at",
    "target_gallons",
    "target_station_count",
    "quoted_price_usd",
    "gallons_applied_total",
    "escalated_station_count",
    "retreat_required",
    "completed_at",
)

# Immutable: a pesticide application record.
PESTICIDE_RECORD_FIELDS = (
    "treatment_plan_id",
    "product_epa_number",
    "gallons_applied",
    "concentration_pct",
    "applied_at",
    "applicator_license_number",
    "applicator_license_state",
    "state_code",
    "retention_until",
)

BAIT_STATION_FIELDS = (
    "treatment_plan_id",
    "station_index",
    "grid_ref",
    "status",
    "last_serviced_at",
    "next_due_at",
    "consecutive_activity_count",
    "service_count",
    "matrix_replacement_count",
)

# Immutable: a bait-station service visit.
STATION_SERVICE_FIELDS = (
    "bait_station_id",
    "activity_level",
    "matrix_replaced",
    "serviced_at",
    "serviced_by_license_number",
    "days_since_last_service",
    "interval_compliance",
)

BOND_FIELDS = (
    "property_id",
    "treatment_plan_id",
    "coverage_tier",
    "status",
    "issued_by_user_id",
    "conducive_waiver_codes",
    "base_premium_usd",
    "repair_liability_cap_usd",
    "annual_premium_usd",
    "claims_paid_to_date_usd",
    "reserved_claim_amount_usd",
    "remaining_repair_cap_usd",
    "issued_on",
    "current_term_start",
    "current_term_end",
    "renewal_window_opens_on",
    "term_index",
    "lapse_date",
    "reinstatement_count",
    "retreat_required",
    "coverage_watch",
    "retreat_credit_count",
)

BOND_RENEWAL_FIELDS = (
    "bond_id",
    "inspection_id",
    "status",
    "term_index",
    "due_on",
    "base_renewal_fee_usd",
    "inspection_fee_usd",
    "conducive_surcharge_usd",
    "late_fee_usd",
    "invoice_total_usd",
    "amount_paid_usd",
    "paid_at",
)

WDO_REPORT_FIELDS = (
    "inspection_id",
    "form_code",
    "state_code",
    "closing_date",
    "status",
    "requested_at",
    "due_at",
    "issued_at",
    "turnaround_hours",
    "sla_breached",
    "amendment_count",
    "amendment_reason_code",
)

DAMAGE_CLAIM_FIELDS = (
    "bond_id",
    "claim_type",
    "status",
    "claimed_damage_usd",
    "reported_at",
    "verifying_inspection_id",
    "exclusion_basis",
    "excluded_pre_existing_usd",
    "eligible_damage_usd",
    "deductible_usd",
    "projected_payout_usd",
    "approved_payout_usd",
    "denial_reason_code",
    "adjudicated_by_user_id",
)


# Map of logical entity name -> (domain fields, is_immutable)
ENTITY_CONTRACTS = {
    "property": (PROPERTY_FIELDS, False),
    "inspector": (INSPECTOR_FIELDS, False),
    "inspection": (INSPECTION_FIELDS, False),
    "graph_finding": (GRAPH_FINDING_FIELDS, True),
    "treatment_plan": (TREATMENT_PLAN_FIELDS, False),
    "pesticide_record": (PESTICIDE_RECORD_FIELDS, True),
    "bait_station": (BAIT_STATION_FIELDS, False),
    "station_service": (STATION_SERVICE_FIELDS, True),
    "bond": (BOND_FIELDS, False),
    "bond_renewal": (BOND_RENEWAL_FIELDS, False),
    "wdo_report": (WDO_REPORT_FIELDS, False),
    "damage_claim": (DAMAGE_CLAIM_FIELDS, False),
}
