"""Per-family serializers.  Every declared field of PRD 1.1 appears on every
representation of that family, null where nothing has been recorded yet."""

COMMON = ("id", "created_at", "updated_at", "version")

BRAND_FIELDS = (
    "code",
    "name",
    "tier",
    "base_royalty_rate_pct",
    "marketing_fund_rate_pct",
    "protected_radius_miles",
    "min_room_count",
    "standard_term_years",
    "operating_unit_count",
    "open_application_count",
)

OWNER_FIELDS = (
    "legal_name",
    "contact_email",
    "liquid_assets_amount",
    "net_worth_amount",
    "credit_score",
    "existing_units_count",
    "capacity_score_standalone",
    "capacity_score_portfolio_adjusted",
    "capacity_band_standalone",
    "capacity_band_portfolio_adjusted",
    "financial_profile_revision",
    "status",
)

UNIT_FIELDS = (
    "brand_id",
    "unit_name",
    "market_code",
    "x_miles",
    "y_miles",
    "room_count",
    "adr_amount",
    "occupancy_pct",
    "territory_start_date",
    "territory_end_date",
    "status",
    "status_reason",
)

APPLICATION_FIELDS = (
    "owner_id",
    "brand_id",
    "property_name",
    "market_code",
    "property_x_miles",
    "property_y_miles",
    "room_count",
    "current_affiliation",
    "building_age_years",
    "requested_term_years",
    "requested_conversion_date",
    "status",
    "revision_round",
    "financial_review_status",
    "capacity_basis",
    "capacity_score_at_review",
    "capacity_band_at_review",
    "financial_reviewer_user_id",
    "impact_study_status",
    "preliminary_impact_score",
    "impact_unit_count_preliminary",
    "base_impact_score",
    "final_impact_score",
    "impact_unit_count_final",
    "sustained_claim_count",
    "encroachment_verdict",
    "claim_window_closes_at",
    "encroachment_waiver_granted",
    "decision_outcome",
    "decision_user_id",
    "decided_at",
    "decision_notes",
    "revision_notes",
    "revision_response",
)

CLAIM_FIELDS = (
    "application_id",
    "existing_unit_id",
    "claimed_revenue_loss_pct",
    "narrative",
    "distance_miles",
    "status",
    "penalty_points_applied",
    "resolution_notes",
    "resolved_at",
    "filed_by_user_id",
)

AGREEMENT_FIELDS = (
    "application_id",
    "brand_code",
    "royalty_rate_pct",
    "marketing_fund_rate_pct",
    "term_years",
    "effective_date",
    "expiry_date",
    "liquidated_damages_cap_months",
    "status",
    "compliance_status",
    "training_status",
    "systems_status",
    "channel_status",
    "de_identification_status",
    "de_identification_deadline",
    "de_identification_items_completed",
    "de_identification_breach_penalty",
    "consecutive_qa_failure_count",
    "revenue_periods",
    "royalty_fee_to_date",
    "marketing_fund_contributed_total",
    "reservation_fee_to_date",
    "total_fees_assessed",
    "reported_period_count",
    "default_notice_issued_at",
    "pip_cure_deadline",
    "transfer_consent_blocked",
    "transfer_consent_count",
    "termination_cause",
    "liquidated_damages_formula",
    "liquidated_damages_amount",
    "liquidated_damages_paid_amount",
    "remaining_term_months_at_termination",
    "trailing_avg_monthly_fee",
    "post_termination_status",
    "executed_at",
    "opened_at",
    "last_inspection_at",
    "terminated_at",
    "closed_out_at",
)

PIP_FIELDS = (
    "agreement_id",
    "scope_notes",
    "status",
    "items_total_count",
    "items_pending_count",
    "items_submitted_count",
    "items_verified_count",
    "items_overdue_count",
    "total_estimated_cost",
    "cost_per_room",
    "key_money_pct",
    "franchisor_key_money",
    "owner_net_cost",
    "owner_net_cost_per_room",
    "escalation_required",
    "accepted_at",
    "overall_deadline",
    "extension_granted_days_total",
    "acknowledgement",
)

PIP_ITEM_FIELDS = (
    "pip_id",
    "category",
    "priority",
    "description",
    "estimated_cost",
    "status",
    "base_due_date",
    "due_date",
    "extension_status",
    "extension_requested_days",
    "extension_granted_days_total",
    "extension_request_count",
    "extension_reason",
    "rejection_count",
    "completion_evidence",
    "completed_at",
    "verified_at",
    "overdue_at",
)

INSPECTION_FIELDS = (
    "agreement_id",
    "inspection_at",
    "cleanliness_score",
    "condition_score",
    "brand_standard_score",
    "guest_experience_score",
    "critical_defect_count",
    "life_safety_defect",
    "weighted_score",
    "total_score",
    "grade",
    "cure_period_days",
    "cure_deadline",
    "status",
    "inspector_user_id",
    "cure_reviewer_user_id",
    "cure_evidence",
    "cure_submitted_at",
    "cure_reviewed_at",
    "review_notes",
)

TRANSFER_FIELDS = (
    "agreement_id",
    "proposed_owner_id",
    "request_type",
    "lender_name",
    "transfer_fee",
    "non_compliance_surcharge",
    "total_consent_fee",
    "proposed_owner_capacity_band",
    "status",
    "refusal_reason",
    "decision_user_id",
    "decided_at",
    "decision_notes",
    "submitted_by_user_id",
)

REVENUE_ENTRY_FIELDS = (
    "period_month",
    "gross_room_revenue",
    "royalty_fee",
    "marketing_fee",
    "reservation_fee",
    "period_total_fee",
    "superseded",
)

_FIELDS_BY_KIND = {
    "brand": BRAND_FIELDS,
    "owner": OWNER_FIELDS,
    "existing_unit": UNIT_FIELDS,
    "application": APPLICATION_FIELDS,
    "claim": CLAIM_FIELDS,
    "agreement": AGREEMENT_FIELDS,
    "pip": PIP_FIELDS,
    "pip_item": PIP_ITEM_FIELDS,
    "inspection": INSPECTION_FIELDS,
    "transfer_request": TRANSFER_FIELDS,
}


def _entry(entry):
    return {name: entry.get(name) for name in REVENUE_ENTRY_FIELDS}


def dump(row):
    """Render one stored row as its API representation."""
    if row is None:
        return None
    out = {name: row.get(name) for name in COMMON}
    for name in _FIELDS_BY_KIND[row["_kind"]]:
        value = row.get(name)
        if name == "revenue_periods":
            value = [_entry(e) for e in (value or [])]
        elif name == "de_identification_items_completed":
            value = list(value or [])
        out[name] = value
    return out


def dump_all(rows):
    return [dump(row) for row in rows]
