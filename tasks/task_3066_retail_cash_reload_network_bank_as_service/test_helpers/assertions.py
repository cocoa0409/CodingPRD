"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §2.8)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """PRD §2.5: every entity carries id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_bank_sponsor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["oversight_tier"] in ["TIER_1", "TIER_2"]
    assert data["active_program_count"] >= 0
    assert data["oversight_reviews_completed"] >= 0
    assert isinstance(data["is_capacity_exhausted"], bool)


def assert_program(data: dict):
    assert_common_fields(data)
    assert data["program_type"] in ["BAAS_PROGRAM_MANAGER", "OWN_BANK_PROGRAM"]
    assert data["settlement_cycle"] in ["DAILY", "WEEKLY"]
    assert data["compliance_posture"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert 0.00 <= data["posture_score"] <= 100.00
    assert data["open_aml_alert_count"] >= 0
    assert data["posture_breach_count"] >= 0
    assert isinstance(data["is_oversight_overdue"], bool)


def assert_brand_partner(data: dict):
    assert_common_fields(data)
    assert data["partner_status"] in ["PENDING_ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED"]
    assert data["suspension_source"] in ["NONE", "POSTURE", "COMPLIANCE"]
    assert isinstance(data["onboarding_checklist_complete"], bool)
    assert isinstance(data["services_scope"], list)


def assert_retailer_agreement(data: dict):
    assert_common_fields(data)
    assert data["agreement_status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["accrual_pending_cents"] >= 0
    assert data["float_position_cents"] >= 0
    assert isinstance(data["contract_version_locked"], bool)


def assert_reload_location(data: dict):
    assert_common_fields(data)
    assert data["location_status"] in ["OPEN", "RESTRICTED", "CLOSED"]
    assert data["daily_accepted_cents"] >= 0
    assert data["daily_txn_count"] >= 0
    assert isinstance(data["is_velocity_breached"], bool)


def assert_card_account(data: dict):
    assert_common_fields(data)
    assert data["funding_status"] in ["UNFUNDED", "FUNDED", "DRAINED"]
    assert data["compliance_hold_status"] in ["CLEAR", "REVIEW", "FROZEN"]
    assert data["cardholder_agreement_type"] in ["REG_E", "VOLUNTARY", "CORPORATE"]
    assert data["balance_cents"] >= 0
    assert_card_account_ledger_invariant(data)


def assert_card_account_ledger_invariant(data: dict):
    """PRD §2.8: balance_cents is max(0, ledger_posted_cents - ledger_reversed_cents)."""
    expected = max(0, data["ledger_posted_cents"] - data["ledger_reversed_cents"])
    assert data["balance_cents"] == expected, (
        f"balance_cents {data['balance_cents']} != max(0, posted {data['ledger_posted_cents']} "
        f"- reversed {data['ledger_reversed_cents']}) == {expected}"
    )


def assert_load_transaction(data: dict):
    assert_common_fields(data)
    assert data["load_status"] in ["INITIATED", "FUNDED", "DECLINED", "SETTLED", "REVERSED"]
    assert data["reversal_reason"] in [
        "NONE", "AML_CONFIRMED", "DISPUTE_FAVOR_CARDHOLDER",
        "RETAILER_REQUEST", "STRUCTURING",
    ]
    assert data["risk_flag"] in ["NONE", "VELOCITY", "STRUCTURING"]
    assert data["principal_cents"] >= 100


def assert_load_fee_identity(data: dict):
    """PRD §3.4: program_fee_share_cents == convenience_fee_cents - retailer_fee_share_cents."""
    expected = round(data["convenience_fee_cents"] - data["retailer_fee_share_cents"], 2)
    assert abs(data["program_fee_share_cents"] - expected) < 0.005, (
        f"program share {data['program_fee_share_cents']} != fee "
        f"{data['convenience_fee_cents']} - retailer {data['retailer_fee_share_cents']}"
    )


def assert_aml_alert(data: dict):
    assert_common_fields(data)
    assert data["alert_type"] in ["VELOCITY", "STRUCTURING"]
    assert data["alert_status"] in ["OPEN", "UNDER_REVIEW", "CONFIRMED", "DISMISSED"]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["linked_load_ids"], list)


def assert_dispute_case(data: dict):
    assert_common_fields(data)
    assert data["case_status"] in [
        "OPEN", "RETAILER_RESPONSE", "PROGRAM_REVIEW", "RESOLVED_CARDHOLDER",
        "RESOLVED_RETAILER", "ESCALATED", "CLOSED",
    ]
    assert data["cardholder_agreement_type"] in ["REG_E", "VOLUNTARY", "CORPORATE"]
    assert data["response_round"] >= 0


def assert_loss_allocation(data: dict):
    assert_common_fields(data)
    assert data["allocation_status"] in ["DRAFT", "POSTED", "RECOVERED"]
    assert data["allocation_basis"] in ["FRAUD_LOSS", "AML_CONFIRMED", "DISPUTE_FAVOR_CARDHOLDER"]
    assert_loss_allocation_identity(data)


def assert_loss_allocation_identity(data: dict):
    """PRD §3.8: the three shares sum exactly to total_loss_cents."""
    total = (data["retailer_share_cents"] + data["program_share_cents"]
             + data["bank_share_cents"])
    assert total == data["total_loss_cents"], (
        f"shares {total} != total_loss_cents {data['total_loss_cents']}"
    )


def assert_settlement_batch(data: dict):
    assert_common_fields(data)
    assert data["batch_status"] in ["SCHEDULED", "OPEN", "SETTLED", "CLAWED_BACK"]


def assert_settlement_rounding_identity(data: dict):
    """PRD §3.8: settlement_rounding_delta_cents == accrued - net payable."""
    expected = round(data["accrued_retailer_share_cents"] - data["net_fee_payable_cents"], 2)
    assert abs(data["settlement_rounding_delta_cents"] - expected) < 0.005, (
        f"delta {data['settlement_rounding_delta_cents']} != accrued "
        f"{data['accrued_retailer_share_cents']} - payable {data['net_fee_payable_cents']}"
    )


def assert_float_window(data: dict):
    assert_common_fields(data)
    assert data["window_status"] in ["REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED"]
    assert data["float_amount_cents"] >= 1


def assert_program_frozen_cascade_no_reinstatement(load: dict, account: dict):
    """PRD §2.11: a cascade never re-instates what an earlier cascade reversed."""
    assert load["load_status"] == "REVERSED"
    assert account["ledger_reversed_cents"] >= load["principal_cents"] - 1
    assert account["balance_cents"] >= 0