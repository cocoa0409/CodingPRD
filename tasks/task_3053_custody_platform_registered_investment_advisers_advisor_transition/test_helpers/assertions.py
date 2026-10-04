"""Entity assertions and domain invariant checkers (PRD §2.8, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CENTS_FIELDS = {
    "market_value_cents", "account_fee_basis_cents", "household_fee_basis_cents",
    "household_annual_fee_cents", "carryover_cents", "sent_cost_basis_cents",
    "basis_appraisal_cents", "allocated_cost_cents", "fee_rebate_cents",
    "credit_cents", "gross_fee_cents", "credit_applied_cents", "net_fee_cents",
    "stated_invoice_cents", "fee_basis_snapshot_cents", "accepted_value_cents",
    "stated_value_cents", "valuation_floor_cents", "periodic_limit_cents",
    "consumed_period_cents", "amount_cents", "withheld_cents",
    "net_disbursed_cents", "expected_total_cents", "observed_total_cents",
    "household_fee_basis_total_cents", "last_listed_cents",
}


def _assert_common_fields(data: dict):
    """Every entity carries id + created_at + updated_at + version (PRD §2.8)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at its initial value of at least 1"


def _assert_whole_cents(data: dict, *field_names: str):
    for name in field_names:
        if data.get(name) is None:
            continue
        value = data[name]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{name} must be a whole number of cents, got {value!r}"
        )


def assert_advisor_firm(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["crd_number"], str) and len(data["crd_number"]) > 0
    assert data["custody_agreement_status"] in [
        "PENDING", "EXECUTED", "SUPERSEDED", "TERMINATED",
    ], f"unexpected custody_agreement_status {data['custody_agreement_status']!r}"
    assert data["firm_posture"] in ["OPEN", "LIMITED", "SUSPENDED", "FROZEN"]
    assert data["supervision_evidence_status"] in ["CLEAR", "DEFICIENT", "UNKNOWN"]
    assert isinstance(data["entitlement_count"], int) and data["entitlement_count"] >= 0
    _assert_whole_cents(data, "household_fee_basis_total_cents")


def assert_custody_agreement(data: dict):
    _assert_common_fields(data)
    assert data["agreement_status"] in [
        "DRAFT", "PENDING_SIGNATURE", "EXECUTED", "SUPERSEDED", "TERMINATED",
    ]
    assert isinstance(data["adviser_crd_number"], str)


def assert_entitlement(data: dict):
    _assert_common_fields(data)
    assert data["entitlement_code"] in [
        "TRADING_AUTHORIZATION", "MONEY_MOVEMENT", "MODEL_MANAGEMENT", "BILLING",
        "ALTERNATIVE_ASSETS", "DATA_FEED", "API_ACCESS",
    ]
    assert data["entitlement_status"] in ["REQUESTED", "GRANTED", "SUSPENDED", "REVOKED"]
    assert isinstance(data["payload_integrity_verified"], bool)


def assert_household(data: dict):
    _assert_common_fields(data)
    assert data["household_status"] in ["ACTIVE", "BILLING_HELD", "CLOSED"]
    _assert_whole_cents(data, "household_fee_basis_cents", "household_annual_fee_cents")
    assert isinstance(data["billing_period_number"], int)


def assert_household_account(data: dict):
    _assert_common_fields(data)
    assert data["account_type"] in ["INDIVIDUAL", "JOINT", "TRUST", "IRA", "ROTH_IRA", "ENTITY"]
    assert data["account_status"] in ["PENDING", "OPEN", "FROZEN", "CLOSED"]
    assert data["householding_consent"] in ["OP_IN", "OP_OUT", "NONE"]
    assert isinstance(data["billable"], bool)
    _assert_whole_cents(data, "market_value_cents", "account_fee_basis_cents")


def assert_asset_transfer(data: dict):
    _assert_common_fields(data)
    assert data["transfer_status"] in [
        "REQUESTED", "SUBMITTED", "RECEIVED", "REJECTED", "BASIS_REVIEW", "CREDITED",
    ]
    assert data["method"] in ["ACAT", "DIRECT_ROLLOVER", "DTC_NON_ACAT"]


def assert_transfer_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["symbol"], str) and len(data["symbol"]) > 0
    assert isinstance(data["quantity_micros"], int)
    assert isinstance(data["valuation_price_micros"], int)
    assert data.get("basis_confidence_grade") in ["HIGH", "MEDIUM", "LOW", "NONE", None]


def assert_model_portfolio(data: dict):
    _assert_common_fields(data)
    assert data["model_status"] in ["DRAFT", "APPROVED", "REBALANCING", "ACTIVE", "ARCHIVED"]
    assert isinstance(data["approval_round_number"], int)
    assert data["target_weight_total_bps"] == 10000 or data["model_status"] == "DRAFT"


def assert_block_order(data: dict):
    _assert_common_fields(data)
    assert data["symbol"] and data["side"] in ["BUY", "SELL"]
    assert data["block_status"] in [
        "DRAFT", "SUBMITTED", "EXECUTED", "ALLOCATED", "SETTLED", "UNALLOCATED",
    ]
    assert isinstance(data["executed_share_micros"], int)
    assert isinstance(data["execution_price_micros"], int)


def assert_block_allocation(data: dict):
    _assert_common_fields(data)
    assert data["allocation_status"] in ["PENDING", "ALLOCATED", "REBATED", "SETTLED"]
    assert isinstance(data["allocation_rank"], int)


def assert_billing_run(data: dict):
    _assert_common_fields(data)
    assert data["billing_run_status"] in ["SETTLED", "INVOICE_MISMATCH", "REOPENED", "VOIDED"]
    assert data["fee_variant_used"] in ["HOUSEHOLD_AGGREGATED", "PER_ACCOUNT"]
    _assert_whole_cents(
        data, "period_days", "fee_basis_snapshot_cents", "gross_fee_cents",
        "credit_applied_cents", "net_fee_cents", "stated_invoice_cents",
    )


def assert_fee_credit(data: dict):
    _assert_common_fields(data)
    assert data["credit_status"] in ["AVAILABLE", "PARTIALLY_APPLIED", "APPLIED"]
    _assert_whole_cents(data, "credit_cents")


def assert_alternative_holding(data: dict):
    _assert_common_fields(data)
    assert data["asset_acceptance_status"] in ["PENDING", "UNDER_REVIEW", "ACCEPTED", "REJECTED"]
    _assert_whole_cents(data, "stated_value_cents", "valuation_floor_cents", "accepted_value_cents")


def assert_money_movement(data: dict):
    _assert_common_fields(data)
    assert data["movement_status"] in [
        "DRAFT", "PENDING_AUTHORIZATION", "AUTHORIZED", "REJECTED", "CANCELLED", "COMPLETED",
    ]
    assert data["movement_type"] in ["ACH_DISBURSEMENT", "WIRE", "JOURNAL", "CHECK"]
    _assert_whole_cents(data, "amount_cents")


def assert_standing_instruction(data: dict):
    _assert_common_fields(data)
    assert data["verification_status"] in ["PENDING", "VERIFIED", "EXPIRED", "REVOKED"]
    assert data["instruction_type"] in ["THIRD_PARTY_DISBURSEMENT", "WIRE", "JOURNAL"]
    _assert_whole_cents(data, "periodic_limit_cents", "consumed_period_cents")


def assert_custody_evidence(data: dict):
    _assert_common_fields(data)
    assert data["requirement_status"] in [
        "PENDING", "SUBMITTED", "ACCEPTED", "DEFICIENT", "WAIVED", "LAPSED",
    ]
    assert isinstance(data["critical"], bool)
    assert isinstance(data["evidence_round_number"], int)


def assert_data_feed(data: dict):
    _assert_common_fields(data)
    assert data["provision_status"] in ["REQUESTED", "ACTIVE", "THROTTLED", "REVOKED"]
    assert data["feed_type"] in ["POSITIONS", "TRANSACTIONS", "BALANCES", "FEES", "ALTERNATIVES"]


def assert_onboarding_batch(data: dict):
    _assert_common_fields(data)
    assert data["batch_kind"] in ["ACCOUNTS", "TRANSFERS", "LOTS", "EVIDENCE"]
    assert data["batch_status"] in ["CREATED", "DISPATCHED", "COMPLETED"]


def assert_admin_action(data: dict):
    _assert_common_fields(data)
    assert data["admin_action_kind"] in ["REGULATORY_FREEZE", "DEFICIENCY_NOTICE"]
    assert data["admin_action_status"] in ["UNACKNOWLEDGED", "ACTIVE", "ACKNOWLEDGED"]


def assert_system_config(data: dict):
    _assert_common_fields(data)
    assert data["config_key"] == "CUSTODY_PLATFORM_DEFAULTS"
    assert data["database_invariant_enforcement"] in ["WARN", "ENFORCED"]
    assert isinstance(data["platform_fee_enabled"], bool)


def assert_database_invariant(data: dict):
    _assert_common_fields(data)
    assert data["invariant_code"] in [
        "CUSTODY_AGREEMENT_CONSISTENCY", "TRANSFER_BASIS_CONSERVATION",
        "HOUSEHOLD_FEE_BASIS_RECONCILIATION", "CASCADE_ECONOMIC_EFFECT",
    ]
    assert data["invariant_status"] in ["HOLDING", "BROKEN"]
    _assert_whole_cents(data, "expected_total_cents", "observed_total_cents")


def assert_examination_bundle(data: dict):
    _assert_common_fields(data)
    assert data["bundle_status"] in ["ASSEMBLING", "GENERATED", "INCOMPLETE", "SEALED"]
    assert isinstance(data["missing_evidence_codes"], list)


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_household_fee_basis_invariants(data: dict):
    """The household basis is a non-negative whole-cent aggregate of its accounts."""
    assert data["household_fee_basis_cents"] >= 0
    assert isinstance(data["household_fee_basis_cents"], int)
    assert data["household_annual_fee_cents"] >= 0


def assert_block_allocation_invariants(block: dict, allocations: list):
    """sum(allocated_cost_cents) - sum(fee_rebate_cents) == block notional."""
    allocated = sum(a["allocated_cost_cents"] for a in allocations if a.get("allocated_cost_cents") is not None)
    rebates = sum(a.get("fee_rebate_cents") or 0 for a in allocations)
    notional = round(block["executed_share_micros"] * block["execution_price_micros"] / 10_000_000_000)
    assert allocated - rebates == notional, (
        f"allocated {allocated} minus rebates {rebates} must equal block notional {notional}"
    )


def assert_allocation_shares_sum(allocations: list, executed_share_micros: int):
    """The shares actually assigned never exceed the executed total."""
    assigned = sum(a["share_micros"] for a in allocations if a.get("share_micros") is not None)
    assert assigned <= executed_share_micros


def assert_carryover_matches_high_grade_lots(transfer: dict, lots: list):
    """carryover_cents is the sum of sent basis over HIGH-graded lots only."""
    expected = sum(
        lot["sent_cost_basis_cents"]
        for lot in lots
        if lot.get("basis_confidence_grade") == "HIGH" and lot.get("sent_cost_basis_cents")
    )
    assert transfer["carryover_cents"] == expected


def assert_consumed_limit_invariant(instruction: dict, movements: list):
    """Authorization books consumption; completion never adds to it again."""
    authorized = sum(
        m["amount_cents"] for m in movements
        if m["movement_status"] in ("AUTHORIZED", "COMPLETED")
    )
    assert instruction["consumed_period_cents"] == authorized