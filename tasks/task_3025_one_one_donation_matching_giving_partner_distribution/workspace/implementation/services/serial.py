"""Field ordering for outgoing resource objects.

The key order follows the scaffold's entity tables field for field: common
fields first (``id``, ``created_at``, ``updated_at``, ``version``), then the
declared fields in declaration order.  ``GivingPartnerVetting`` is deliberately
excluded from the common-field convention (PRD 2.10) and carries only ``id``
and ``created_at``.
"""

COMMON = ["id", "created_at", "updated_at", "version"]

ORDER = {
    "GivingPartner": COMMON + [
        "legal_name", "partner_type", "operating_region", "operating_state_code",
        "service_radius_miles", "registry_id", "ein", "founded_year",
        "unduplicated_recipients_per_facility", "need_tier", "registry_verified",
        "status", "vetting_round", "latest_vetting_round_id", "total_rejections",
        "need_score", "capacity_utilization_units", "impact_units_total",
        "impact_units_retail_equivalent", "avg_distribution_completion_days",
        "claim_attributed_units", "attributed_percentage", "entrance_returns_units",
        "partner_performance_grade", "last_vetted_at",
    ],
    "PartnerCapacityProfile": COMMON + [
        "partner_id", "season_code", "max_allocatable_units", "reserved_units",
        "committed_units", "capacity_utilization_units", "effective_from",
        "effective_to", "status",
    ],
    "GivingPartnerVetting": [
        "id", "created_at", "partner_id", "round_number", "outcome",
        "registry_check_passed", "tax_check_passed", "on_site_check_passed",
        "capacity_check_passed", "need_verification_points",
        "need_verification_evidence", "valid_until", "outcome_message",
    ],
    "DonationProduct": COMMON + [
        "product_name", "product_kind", "design_channel", "design_weight_score",
        "obligation_model", "approved_donation_ratio_units", "retail_price_cents",
        "unit_cost_cents", "is_reusable", "status", "active_season_code",
        "obligation_units_total", "impact_units_retail_equivalent",
    ],
    "DonationProductLine": COMMON + [
        "donation_product_id", "gtin", "unit_size_label", "is_essential_good",
        "donation_eligible", "obligation_units", "unit_obligation_cost_cents",
        "design_variant_code", "status",
    ],
    "DonationLiability": COMMON + [
        "donation_product_id", "impact_season_id", "donation_liability_units",
        "final_liability_units", "provisional_liability_units", "obligation_units",
        "accrued_obligation_cents", "donation_cost_cents", "donation_credit_units",
        "frozen_units", "required_stated_units", "carried_in_units",
        "carried_out_units", "status", "freeze_recorded_at",
    ],
    "DonationAllocation": COMMON + [
        "giving_partner_id", "impact_season_id", "donation_product_id",
        "donation_liability_id", "claim_id", "allocation_kind", "allocated_units",
        "priority_tier", "rank_score", "status",
    ],
    "DonationDistribution": COMMON + [
        "allocation_id", "shipped_units", "received_units",
        "impact_units_confirmed", "discrepancy_units", "shipment_reference",
        "carrier_code", "shipped_at", "received_at", "exception_reason", "status",
    ],
    "ImpactSeason": COMMON + [
        "season_code", "starts_at", "ends_at", "freezes_at",
        "liability_carry_in_units", "claim_frozen_units_total",
        "opening_carry_obligation_cents", "requested_season_code", "is_final",
        "attributed_units_total", "attributed_percentage_total",
        "total_shipped_units", "total_received_units",
        "liability_reconciliation_delta", "status",
    ],
    "MarketingClaim": COMMON + [
        "donation_product_id", "partner_id", "stated_donation_units",
        "stated_ratio_text", "winback_multiplier", "stated_reference_period",
        "substantiated_donation_units", "substantiated_ratio_value", "status",
    ],
    "SalesOrder": COMMON + [
        "order_number", "channel", "status", "fulfillment_status", "ordered_units",
        "returned_units", "fulfilled_units", "refunded_cents", "placed_at", "paid_at",
    ],
    "SalesOrderLine": COMMON + [
        "sales_order_id", "donation_product_id", "donation_product_line_id",
        "quantity", "unit_price_cents", "line_discount_cents", "return_window_days",
        "obligated_units", "status",
    ],
    "ReturnRequest": COMMON + [
        "sales_order_line_id", "donation_liability_id", "request_reason",
        "requested_units", "is_exchange", "replacement_product_id",
        "replacement_is_donation_good", "status", "terminal_outcome",
        "refund_amount_cents", "liability_delta_units", "window_expires_at",
    ],
    "ImpactAudit": COMMON + [
        "impact_season_id", "claim_id", "audit_kind", "claimed_donation_units",
        "shipped_units_verified", "received_units_verified", "unit_clearance_rate",
        "scorecard_total", "transaction_test_sample_size",
        "transaction_test_exceptions", "partner_performance_grade",
        "liability_reconciliation_delta", "status", "finalization_error_message",
        "finalized_at",
    ],
    "AllocationPlan": [
        "id", "created_at", "updated_at", "version", "claim_id",
        "donation_product_id", "liquidity_cap", "baseline_units", "demand_units",
        "pool_units", "season_code",
    ],
}


def serialize(kind, record):
    """Project a record onto its declared field order."""
    if record is None:
        return None
    keys = ORDER.get(kind)
    if not keys:
        return dict(record)
    out = {}
    for key in keys:
        out[key] = record.get(key)
    for key, value in record.items():
        if key not in out and not key.startswith("_"):
            out[key] = value
    return out


def serialize_many(kind, records):
    return [serialize(kind, r) for r in records]