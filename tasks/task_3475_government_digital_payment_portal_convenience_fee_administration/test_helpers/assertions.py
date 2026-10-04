"""Entity assertions and domain invariant checkers.

``assert_<entity>(data)`` validates the shape and typing of one resource body.
Per PRD section 2.5, ContractPricingTier, ComplianceAttestation, FeeQuote and
SelfFundingLedgerEntry carry only ``id`` and ``created_at`` — their assertions
also require ``version`` and ``updated_at`` to be ABSENT. Nullable system
fields (``activated_at``, ``effective_to``, ``verified_at``,
``current_batch_id``, ``captured_at``, ``returned_at``,
``actual_deposit_cents``, ``resolution_note``, ``evidence_note``,
``decided_by_user_id``, ...) are type-checked only when present.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# shared low-level checks
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def _assert_append_only_fields(data: dict, entity: str):
    """PRD 2.5: these resource kinds carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "version" not in data, f"{entity} must not carry a version field"
    assert "updated_at" not in data, f"{entity} must not carry an updated_at field"


def _assert_opt_ts(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or an ISO 8601 timestamp, got {value!r}"
    )


def _assert_opt_date(data: dict, field: str):
    value = data.get(field)
    if value is None:
        return
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be a YYYY-MM-DD string, got {value!r}"
    )


def _assert_cents(data: dict, field: str):
    assert isinstance(data.get(field), int), f"{field} must be an integer number of cents"


def _assert_opt_cents(data: dict, field: str):
    value = data.get(field)
    assert value is None or isinstance(value, int), (
        f"{field} must be null or an integer number of cents, got {value!r}"
    )


# ---------------------------------------------------------------------------
# per-entity assertions
# ---------------------------------------------------------------------------

def assert_agency(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["agency_type"] in ("STATE", "LOCAL")
    assert data["default_fee_model"] in ("CONVENIENCE_FEE", "ABSORBED")
    assert data["status"] in ("ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED")
    _assert_opt_ts(data, "activated_at")


def assert_settlement_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert isinstance(data["routing_number"], str) and len(data["routing_number"]) == 9
    assert isinstance(data["account_number_last4"], str) and len(data["account_number_last4"]) == 4
    _assert_opt_ts(data, "effective_from")
    _assert_opt_ts(data, "effective_to")
    assert data["status"] in ("PENDING_VERIFICATION", "VERIFIED", "RETIRED")
    assert isinstance(data["verification_attempts"], int) and data["verification_attempts"] >= 0
    _assert_opt_ts(data, "verified_at")


def assert_pricing_tier(data: dict):
    _assert_append_only_fields(data, "ContractPricingTier")
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    _assert_cents(data, "volume_min_cents")
    _assert_opt_cents(data, "volume_max_cents")
    assert isinstance(data["rate_bp"], int)
    assert isinstance(data["per_txn_cents"], int)
    month = data["effective_month"]
    assert isinstance(month, str) and len(month) == 7 and month[4] == "-", (
        f"effective_month must be YYYY-MM, got {month!r}"
    )


def assert_attestation(data: dict):
    _assert_append_only_fields(data, "ComplianceAttestation")
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert data["attestation_type"] in ("PCI_DSS_AOC", "PENETRATION_TEST", "INTEGRATION_REVIEW")
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"
    assert data["status"] in ("CURRENT", "EXPIRED")


def assert_service(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert isinstance(data["service_code"], str) and data["service_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["fee_model"] in ("CONVENIENCE_FEE", "ABSORBED")
    methods = data["allowed_methods"]
    assert isinstance(methods, list) and len(methods) >= 1, "allowed_methods must be non-empty"
    assert all(m in ("CARD", "ECHECK", "WALLET") for m in methods)
    _assert_cents(data, "min_amount_cents")
    _assert_cents(data, "max_amount_cents")
    assert data["min_amount_cents"] <= data["max_amount_cents"]
    assert isinstance(data["gl_code"], str) and data["gl_code"]
    assert data["status"] in ("DRAFT", "ACTIVE", "DEACTIVATED")


def assert_statutory_authorization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("service_id", "")), "service_id must be a UUID"
    assert isinstance(data["statute_citation"], str) and data["statute_citation"]
    assert isinstance(data["disclosure_text_version"], str) and data["disclosure_text_version"]
    _assert_cents(data, "fee_cap_cents")
    assert is_iso8601_timestamp(data.get("effective_from", "")), "effective_from must be ISO 8601"
    assert is_iso8601_timestamp(data.get("effective_to", "")), "effective_to must be ISO 8601"
    assert data["status"] in ("DRAFT", "APPROVED")
    assert isinstance(data["in_effect"], bool), "in_effect is a computed boolean"


def assert_payer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["billing_zip"], str) and data["billing_zip"]


def assert_instrument(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("payer_id", "")), "payer_id must be a UUID"
    assert data["method"] in ("CARD", "ECHECK", "WALLET")
    if data["method"] == "CARD":
        assert data.get("card_brand") in ("VISA", "MASTERCARD", "AMEX", "DISCOVER")
        assert data.get("card_cost_bucket") in ("CONSUMER_DEBIT", "CONSUMER_CREDIT", "COMMERCIAL")
    assert isinstance(data["last4"], str) and len(data["last4"]) == 4
    assert isinstance(data["token_ref"], str) and data["token_ref"], "token_ref is server-minted"
    assert data["status"] in ("ACTIVE", "PENDING_VERIFICATION", "DEACTIVATED")
    assert isinstance(data["ach_verify_failures"], int) and 0 <= data["ach_verify_failures"] <= 3
    assert not any(k in data for k in ("pan", "card_number", "account_number")), (
        "only masked data may be stored — no full PAN/ABA field may appear"
    )


def assert_fee_quote(data: dict):
    _assert_append_only_fields(data, "FeeQuote")
    assert is_valid_uuid(data.get("service_id", "")), "service_id must be a UUID"
    assert is_valid_uuid(data.get("payer_id", "")), "payer_id must be a UUID"
    authz = data.get("statutory_authorization_id")
    assert authz is None or is_valid_uuid(authz), "statutory_authorization_id must be null or a UUID"
    _assert_cents(data, "amount_cents")
    assert data["method"] in ("CARD", "ECHECK", "WALLET")
    _assert_cents(data, "quoted_fee_cents")
    _assert_cents(data, "payer_total_cents")
    dtv = data.get("disclosure_text_version")
    assert dtv is None or isinstance(dtv, str)
    assert isinstance(data["service_version_pinned"], int) and data["service_version_pinned"] >= 1
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"
    assert data["status"] in ("OPEN", "CONSUMED", "VOIDED")


def assert_transaction(data: dict):
    _assert_common_fields(data)
    for fk in ("quote_id", "instrument_id", "service_id", "agency_id", "payer_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    batch = data.get("current_batch_id")
    assert batch is None or is_valid_uuid(batch), "current_batch_id must be null or a UUID"
    assert data["method"] in ("CARD", "ECHECK", "WALLET")
    assert data["fee_model"] in ("CONVENIENCE_FEE", "ABSORBED")
    _assert_cents(data, "amount_cents")
    _assert_cents(data, "charged_fee_cents")
    _assert_cents(data, "final_fee_cents")
    _assert_cents(data, "payer_total_cents")
    assert data["funds_status"] in (
        "AUTHORIZED", "CAPTURED", "SETTLED", "VOIDED", "RETURNED", "RE_PRESENTED",
    )
    assert isinstance(data["representment_count"], int) and 0 <= data["representment_count"] <= 1
    _assert_opt_ts(data, "captured_at")
    _assert_opt_date(data, "value_date")
    _assert_opt_ts(data, "returned_at")
    _assert_cents(data, "refunded_cents")
    _assert_cents(data, "charged_back_cents")
    _assert_cents(data, "remaining_refundable_cents")


def assert_settlement_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    _assert_opt_date(data, "business_date")
    assert isinstance(data.get("business_date"), str) and data["business_date"]
    assert data["status"] in ("OPEN", "CLOSED", "SUBMITTED", "CONFIRMED", "EXCEPTION", "RECONCILED")
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0
    _assert_cents(data, "gross_amount_cents")
    _assert_cents(data, "fees_withheld_cents")
    _assert_cents(data, "refund_debits_cents")
    _assert_cents(data, "return_debits_cents")
    _assert_cents(data, "chargeback_debits_cents")
    _assert_cents(data, "deposit_cents")
    _assert_opt_date(data, "deposit_due_date")
    _assert_opt_ts(data, "submitted_at")
    _assert_opt_ts(data, "confirmed_at")
    _assert_opt_cents(data, "actual_deposit_cents")
    assert isinstance(data["open_exception_count"], int) and data["open_exception_count"] >= 0


def assert_reconciliation_exception(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("batch_id", "")), "batch_id must be a UUID"
    assert data["exception_type"] in ("AMOUNT_MISMATCH", "DEPOSIT_LATE")
    _assert_cents(data, "expected_cents")
    _assert_opt_cents(data, "actual_cents")
    assert isinstance(data["detail"], str)
    assert data["status"] in ("OPEN", "RESOLVED")
    note = data.get("resolution_note")
    assert note is None or isinstance(note, str)


def assert_refund(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("transaction_id", "")), "transaction_id must be a UUID"
    _assert_cents(data, "amount_cents")
    assert isinstance(data["reason"], str)
    assert isinstance(data["initiated_by_user_id"], str) and data["initiated_by_user_id"]
    decider = data.get("decided_by_user_id")
    assert decider is None or isinstance(decider, str)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_chargeback_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("transaction_id", "")), "transaction_id must be a UUID"
    assert data["reason_code"] in ("FRAUD", "DUPLICATE", "SERVICE_NOT_RECEIVED", "CREDIT_NOT_ISSUED")
    _assert_opt_cents(data, "network_debit_cents")
    assert is_iso8601_timestamp(data.get("opened_at", "")), "opened_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("evidence_due_at", "")), "evidence_due_at must be ISO 8601"
    note = data.get("evidence_note")
    assert note is None or isinstance(note, str)
    assert data["status"] in ("OPENED", "CONTESTED", "ACCEPTED", "WON", "LOST")


def assert_ledger_entry(data: dict):
    _assert_append_only_fields(data, "SelfFundingLedgerEntry")
    period = data["period"]
    assert isinstance(period, str) and len(period) == 7 and period[4] == "-", (
        f"period must be YYYY-MM, got {period!r}"
    )
    for field in (
        "fees_collected_cents", "absorbed_billed_cents", "absorbed_billed_flat_cents",
        "processing_costs_cents", "accrual_portal_recovery_cents",
        "cash_portal_recovery_cents", "surplus_remitted_cents",
        "pool_balance_after_cents", "portal_cost_remaining_accrual_cents",
        "portal_cost_remaining_cash_cents",
    ):
        _assert_cents(data, field)


# ---------------------------------------------------------------------------
# domain invariants
# ---------------------------------------------------------------------------

def assert_transaction_money_conservation(txn: dict):
    """PRD: remaining_refundable_cents is always amount - refunded - charged_back."""
    assert (
        txn["refunded_cents"] + txn["charged_back_cents"] + txn["remaining_refundable_cents"]
        == txn["amount_cents"]
    ), (
        f"refunded {txn['refunded_cents']} + charged_back {txn['charged_back_cents']} "
        f"+ remaining {txn['remaining_refundable_cents']} != amount {txn['amount_cents']}"
    )


def assert_batch_deposit_identity(batch: dict):
    """PRD: deposit_cents = gross - refund_debits - return_debits - chargeback_debits.

    Only meaningful once the batch has been closed (deposit is 0 while OPEN).
    """
    assert (
        batch["gross_amount_cents"]
        - batch["refund_debits_cents"]
        - batch["return_debits_cents"]
        - batch["chargeback_debits_cents"]
        == batch["deposit_cents"]
    ), (
        f"batch deposit {batch['deposit_cents']} != gross {batch['gross_amount_cents']} "
        f"- refunds {batch['refund_debits_cents']} - returns {batch['return_debits_cents']} "
        f"- chargebacks {batch['chargeback_debits_cents']}"
    )


def assert_pool_conservation(entry: dict, prior_pool_balance_cents: int = 0):
    """PRD waterfall: pool_balance_after == prior + fees + absorbed_billed
    - processing_costs - cash_recovery - surplus, with zero remainder."""
    pool_available = (
        entry["fees_collected_cents"]
        + entry["absorbed_billed_cents"]
        - entry["processing_costs_cents"]
    )
    expected = (
        prior_pool_balance_cents
        + pool_available
        - entry["cash_portal_recovery_cents"]
        - entry["surplus_remitted_cents"]
    )
    assert entry["pool_balance_after_cents"] == expected, (
        f"pool_balance_after {entry['pool_balance_after_cents']} != prior "
        f"{prior_pool_balance_cents} + pool_available {pool_available} - cash "
        f"{entry['cash_portal_recovery_cents']} - surplus {entry['surplus_remitted_cents']}"
    )
