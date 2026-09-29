"""Response projections: exactly the fields SCAFFOLD §1.1 declares per entity."""

COMMON = ["created_at", "updated_at", "version"]

FIELDS = {
    "ProgramTier": [
        "id", "tier_code", "member_share_bps", "gpo_retention_bps",
        "admin_fee_bps_low", "admin_fee_bps_high", "compliance_min_ratio_bps",
        "markup_cap_bps", "dispute_window_days", "reversal_posture_limit",
    ] + COMMON,
    "Distributor": [
        "id", "name", "dba_code", "contracted_markup_bps", "status",
        "active_letter_count", "overbilled_recovered_cents",
    ] + COMMON,
    "Member": [
        "id", "legal_name", "tier_id", "committed_annual_spend_cents",
        "enrollment_status", "reconciliation_posture", "payout_hold",
        "active_letter_count", "accrued_member_share_cents",
        "attributed_gpo_retention_cents", "attributed_admin_fee_cents",
        "ytd_net_snapshot_cents", "dispute_reversal_count",
        "recovery_credit_cents",
    ] + COMMON,
    "AuthorizationLetter": [
        "id", "member_id", "distributor_id", "effective_from", "effective_to",
        "signatory_name", "scope", "status", "countersigned_at",
    ] + COMMON,
    "ManufacturerDeal": [
        "id", "manufacturer_name", "deal_code", "effective_from",
        "effective_to", "required_purchase_window_days", "status",
        "contracted_item_count", "last_purchase_date",
    ] + COMMON,
    "ContractedItem": [
        "id", "deal_id", "manufacturer_sku", "normalized_item_key",
        "pack_size", "baseline_unit_cost_cents", "contract_unit_cost_cents",
        "status", "approved_rate_card_count",
    ] + COMMON,
    "RateCard": [
        "id", "contracted_item_id", "supersedes_rate_card_id", "rate_type",
        "flat_rate_cents_per_case", "percent_bps", "tier_breaks",
        "effective_from", "effective_to", "status", "pinned_item_version",
    ] + COMMON,
    "PurchaseBatch": [
        "id", "distributor_id", "period_start", "period_end",
        "source_reference", "normalization_status", "audit_status",
        "line_count", "total_cases_ingested", "matched_cases",
        "unmatched_cases", "overbilled_cents", "recovered_cents",
        "accrued_by_user_id", "payout_hold",
    ] + COMMON,
    "PurchaseLine": [
        "id", "purchase_batch_id", "member_id", "contracted_item_id",
        "distributor_sku", "vendor_item_description",
        "normalized_item_key_reported", "cases_shipped",
        "invoice_unit_cost_cents", "distributor_base_cost_cents",
        "invoice_date", "invoice_extended_cents", "match_status",
        "accrual_block_reason", "overbilled_cents",
    ] + COMMON,
    "RebateAccrual": [
        "id", "purchase_line_id", "member_id", "rate_card_id", "basis",
        "accrued_cases", "gross_rebate_cents", "admin_fee_bps_applied",
        "admin_fee_cents", "net_distributable_cents", "member_share_cents",
        "gpo_retention_cents", "final_adjustment_cents", "status",
        "reversal_reason", "validated_by_user_id",
    ] + COMMON,
    "ManufacturerClaim": [
        "id", "deal_id", "period_start", "period_end", "claimed_units",
        "claimed_amount_cents", "accrued_amount_cents", "variance_bps",
        "status", "reconciled_at",
    ] + COMMON,
    "RebateDispute": [
        "id", "accrual_id", "claim_id", "reason_code",
        "disputed_amount_cents", "opened_by_user_id", "accrual_status_before",
        "evidence_round_count", "status", "decided_by_user_id",
        "decision_note",
    ] + COMMON,
    # ComplianceReview is a point-in-time verdict: id and created_at only.
    "ComplianceReview": [
        "id", "member_id", "deal_id", "window_start", "window_end",
        "window_days", "committed_spend_prorated_cents",
        "contracted_spend_cents", "deal_wide_contracted_spend_cents",
        "purchase_ratio_bps", "result", "triggered_deal_loss", "created_at",
    ],
}


def dump(rec):
    kind = rec["_kind"]
    return {name: rec.get(name) for name in FIELDS[kind]}


def dump_all(records):
    return [dump(r) for r in records]
