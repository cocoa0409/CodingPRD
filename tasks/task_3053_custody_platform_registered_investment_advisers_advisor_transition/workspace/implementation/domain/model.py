"""Row factory, mutation helpers and per-entity serialization.

Every entity carries the four common properties from PRD §2.8: `id` (a UUID),
`created_at`, `updated_at` and `version`.  `version` starts at 0 and increments
by one on every mutation, including mutations the platform performs on its own
initiative during a cascade.
"""

from core.store import STORE, new_id

VERSION_INITIAL = 0

# Serialization order per entity — exactly the fields declared in SCAFFOLD §1.1
# plus the four common properties.  Internal bookkeeping keys are never exposed.
OUTPUT_ORDER = {
    "AdvisorFirm": [
        "id", "legal_name", "crd_number", "home_state_code",
        "custody_agreement_status", "firm_posture", "posture_reason_code",
        "agreement_executed_at", "supervision_evidence_status",
        "entitlement_count", "household_fee_basis_total_cents",
        "created_at", "updated_at", "version",
    ],
    "CustodyAgreement": [
        "id", "firm_id", "agreement_status", "adviser_crd_number",
        "drafted_by_user_id", "executed_by_user_id", "signed_at",
        "countersignature_hash", "superseded_by_agreement_id",
        "created_at", "updated_at", "version",
    ],
    "AdvisorFirmEntitlement": [
        "id", "firm_id", "entitlement_code", "requested_custody_agreement_id",
        "entitlement_status", "effective_from", "payload_integrity_verified",
        "created_at", "updated_at", "version",
    ],
    "Household": [
        "id", "firm_id", "household_name", "household_status",
        "household_fee_basis_cents", "household_annual_fee_cents",
        "billing_period_number", "created_at", "updated_at", "version",
    ],
    "HouseholdAccount": [
        "id", "household_id", "firm_id", "account_number", "account_type",
        "account_status", "market_value_cents", "account_fee_basis_cents",
        "billable", "householding_consent", "last_listed_cents",
        "last_listed_at", "model_portfolio_id", "billed_period_count",
        "created_at", "updated_at", "version",
    ],
    "AssetTransfer": [
        "id", "receiving_account_id", "firm_id", "transfer_status",
        "delivering_firm_name", "method", "sent_basis_confidence",
        "carryover_cents", "cost_basis_complete", "rejected_reason_code",
        "credited_at", "created_at", "updated_at", "version",
    ],
    "TransferLot": [
        "id", "transfer_id", "symbol", "quantity_micros",
        "sent_cost_basis_cents", "lot_inventory_date", "valuation_price_micros",
        "basis_appraisal_cents", "suspected_double_basis",
        "basis_confidence_grade", "created_at", "updated_at", "version",
    ],
    "ModelPortfolio": [
        "id", "firm_id", "model_name", "model_status", "approval_round_number",
        "drift_approved_at", "target_weight_total_bps",
        "created_at", "updated_at", "version",
    ],
    "ModelTarget": [
        "id", "model_id", "symbol", "target_weight_bps",
        "created_at", "updated_at", "version",
    ],
    "BlockOrder": [
        "id", "firm_id", "model_id", "symbol", "side",
        "total_requested_share_micros", "executed_share_micros",
        "execution_price_micros", "block_status", "unallocated_share_micros",
        "preview_notional_cents", "created_at", "updated_at", "version",
    ],
    "BlockAllocation": [
        "id", "block_order_id", "account_id", "requested_share_micros",
        "share_micros", "allocation_rank", "allocated_cost_cents",
        "average_price_micros", "fee_rebate_cents", "allocation_status",
        "created_at", "updated_at", "version",
    ],
    "FeeBillingRun": [
        "id", "firm_id", "household_id", "period_start_date",
        "period_end_date", "period_days", "billing_run_status",
        "fee_basis_snapshot_cents", "fee_variant_used", "gross_fee_cents",
        "credit_applied_cents", "net_fee_cents", "stated_invoice_cents",
        "settlement_evidence_hash", "created_at", "updated_at", "version",
    ],
    "FeeCredit": [
        "id", "household_id", "credit_cents", "earned_on_date",
        "credit_status", "applied_to_billing_run_id",
        "created_at", "updated_at", "version",
    ],
    "AlternativeAssetHolding": [
        "id", "account_id", "asset_name", "asset_acceptance_status",
        "unit_count", "stated_value_cents", "accepted_value_cents",
        "haircut_pct", "valuation_floor_cents", "valuation_as_of_date",
        "valuation_age_days", "stale_valuation", "fee_basis_eligible",
        "created_at", "updated_at", "version",
    ],
    "MoneyMovementInstruction": [
        "id", "account_id", "standing_instruction_id", "amount_cents",
        "movement_type", "movement_status", "authorization_note",
        "jurisdiction_withholding_required", "withheld_cents",
        "net_disbursed_cents", "authorized_at",
        "created_at", "updated_at", "version",
    ],
    "StandingInstruction": [
        "id", "account_id", "instruction_type", "payee_name",
        "periodic_limit_cents", "verification_status", "verification_token",
        "verified_at", "round_trip_days", "consumed_period_cents",
        "created_at", "updated_at", "version",
    ],
    "CustodyRulesEvidence": [
        "id", "firm_id", "requirement_code", "requirement_status", "critical",
        "drafted_by_user_id", "accepted_by_user_id", "evidence_document_hash",
        "submitted_at", "evidence_round_number",
        "created_at", "updated_at", "version",
    ],
    "DataFeedProvision": [
        "id", "firm_id", "feed_type", "provision_status",
        "provisioned_records_count", "delivery_endpoint_host",
        "throttle_reason_code", "last_delivered_at", "delivered_count",
        "created_at", "updated_at", "version",
    ],
    "OnboardingBatch": [
        "id", "firm_id", "batch_kind", "batch_status", "chunk_size",
        "requested_item_count", "dispatched_item_count",
        "skipped_duplicate_count", "created_at", "updated_at", "version",
    ],
    "AdminActionLog": [
        "id", "firm_id", "admin_action_kind", "admin_action_status",
        "admin_action_detail", "acknowledged_note", "acknowledged_by_user_id",
        "created_at", "updated_at", "version",
    ],
    "SystemConfig": [
        "id", "config_key", "database_invariant_enforcement",
        "platform_fee_enabled", "created_at", "updated_at", "version",
    ],
    "DatabaseInvariant": [
        "id", "firm_id", "invariant_code", "invariant_status",
        "expected_total_cents", "observed_total_cents", "breach_detail_code",
        "last_evaluated_at", "created_at", "updated_at", "version",
    ],
    "ExaminationBundle": [
        "id", "firm_id", "period_start_date", "period_end_date",
        "bundle_status", "missing_evidence_codes", "sealed_evidence_hash",
        "generated_at", "created_at", "updated_at", "version",
    ],
}

# Entities whose rows are firm-scoped, used by the reference-integrity check.
FIRM_SCOPED = {
    "CustodyAgreement", "AdvisorFirmEntitlement", "Household", "HouseholdAccount",
    "AssetTransfer", "ModelPortfolio", "BlockOrder", "FeeBillingRun",
    "CustodyRulesEvidence", "DataFeedProvision", "OnboardingBatch",
    "AdminActionLog", "DatabaseInvariant", "ExaminationBundle",
}


def create(entity, **fields):
    now = STORE.clock.now()
    row = {
        "id": new_id(),
        "_entity": entity,
        "_created_instant": now,
        "_seq": STORE.next_seq(entity),
        "created_at": now,
        "updated_at": now,
        "version": VERSION_INITIAL,
    }
    row.update(fields)
    return STORE.put(entity, row)


def touch(row, stamp=True):
    """Bump a row's version and refresh its updated_at."""
    row["version"] = int(row.get("version", VERSION_INITIAL)) + 1
    if stamp:
        row["updated_at"] = STORE.clock.now()
    return row


def mutate(row, **changes):
    for key, value in changes.items():
        row[key] = value
    return touch(row)


def serialize(row):
    if row is None:
        return None
    order = OUTPUT_ORDER.get(row.get("_entity"))
    if order is None:
        return {k: v for k, v in row.items() if not k.startswith("_")}
    return {name: row.get(name) for name in order}


def serialize_many(rows):
    return [serialize(r) for r in rows]


def summarize(row, keep):
    """Serialize a row but retain only the named fields."""
    full = serialize(row)
    return {k: full.get(k) for k in keep}