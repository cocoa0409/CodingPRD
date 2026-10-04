"""Entity assertions and domain invariant checkers (PRD §2.10, §2.8)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Common-field helpers ─────────────────────────────

def assert_common_fields(data: dict) -> None:
    """Every resource carrying the common field set (PRD §2.10)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_append_only_fields(data: dict) -> None:
    """Append-only ledgers carry only id + created_at (PRD §2.10)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert "updated_at" not in data or data["updated_at"] is None
    assert "version" not in data or data["version"] is None


# ─── Participant (PRD §2.4) ───────────────────────────

def assert_participant(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["lei"], str) and data["lei"]
    assert data["participant_class"] in (
        "BANK", "BROKER_DEALER", "CUSTODIAN_BANK", "INSURANCE_CARRIER")
    assert data["membership_status"] in (
        "PENDING", "ACTIVE", "SUSPENDED", "DEFAULTED", "EXPELLED")
    assert isinstance(data["net_capital_cents"], int)
    assert isinstance(data["required_min_net_capital_cents"], int)
    assert data["financial_standard_status"] in ("PASS", "FAIL")
    assert isinstance(data["is_defaulted"], bool)
    assert isinstance(data["requires_segregated_custody"], bool)
    assert is_iso8601_timestamp(data["last_financial_review_at"])


def assert_participant_financial_standard(data: dict) -> None:
    """The derived floor and verdict agree with the class base and the flat floor."""
    floor = max(
        {"BANK": 1_500_000_000,
         "BROKER_DEALER": 250_000_000,
         "CUSTODIAN_BANK": 750_000_000,
         "INSURANCE_CARRIER": 1_000_000_000}[data["participant_class"]],
        500_000_000,
    )
    assert data["required_min_net_capital_cents"] == floor, (
        f"Expected floor {floor} for {data['participant_class']}, "
        f"got {data['required_min_net_capital_cents']}"
    )
    expected = "PASS" if data["net_capital_cents"] >= floor else "FAIL"
    assert data["financial_standard_status"] == expected, (
        f"Expected {expected} at capital {data['net_capital_cents']} vs floor {floor}, "
        f"got {data['financial_standard_status']}"
    )


# ─── ClearingMemberDeposit (PRD §2.5) ─────────────────

def assert_deposit(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["participant_id"])
    assert isinstance(data["posted_amount_cents"], int)
    assert data["status"] in (
        "PENDING", "SATISFIED", "DEFICIENT_GRACE", "DEFICIENT_DEFAULT")


def assert_deposit_transaction(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["deposit_id"])
    assert is_valid_uuid(data["participant_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] != 0
    assert data["txn_type"] in ("POST", "RELEASE")
    expected_type = "POST" if data["amount_cents"] > 0 else "RELEASE"
    assert data["txn_type"] == expected_type, (
        f"txn_type must be derived from the sign of amount_cents: "
        f"{data['amount_cents']} implies {expected_type}, got {data['txn_type']}"
    )


# ─── TradeSubmission (PRD §2.6) ───────────────────────

def assert_trade_submission(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["participant_id"])
    assert is_valid_uuid(data["counterparty_participant_id"])
    assert is_valid_uuid(data["security_id"])
    assert data["side"] in ("BUY", "SELL")
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["trade_price_cents"], int) and data["trade_price_cents"] > 0
    assert is_iso8601_timestamp(data["trade_date"])
    assert data["lock_status"] in ("OPEN", "LOCKED_IN", "DISPUTED", "CANCELLED")
    assert data["match_status"] in ("UNMATCHED", "MATCHED", "ALLEGED", "UNRESOLVED")
    assert data["affirmation_status"] in (
        "UNCONFIRMED", "AFFIRMED", "UNCONFIRMED_BREACH")
    assert isinstance(data["allegations_received"], int) and data["allegations_received"] >= 0


# ─── Security (PRD §2.10, §3.3) ───────────────────────

def assert_security(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["ticker"], str) and data["ticker"]
    assert isinstance(data["cusip"], str) and data["cusip"]
    assert isinstance(data["currency"], str)
    assert isinstance(data["prev_settlement_price_cents"], int)
    assert isinstance(data["current_volatility_bps"], int)


# ─── CustodyAccount (PRD §3.8) ────────────────────────

def assert_custody_account(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["participant_id"])
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert data["account_type"] in ("SEGREGATED", "HOUSE", "PLEDGED")
    assert data["status"] in ("OPEN", "PLEDGED", "FROZEN")
    assert isinstance(data["positions"], list)


def assert_custody_position(position: dict) -> None:
    assert is_valid_uuid(position["security_id"])
    assert isinstance(position["settled_quantity"], int)


# ─── SettlementWindow (PRD §2.7) ──────────────────────

def assert_settlement_window(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["security_id"])
    assert isinstance(data["settlement_date"], str) and len(data["settlement_date"]) == 10
    assert is_iso8601_timestamp(data["trade_entry_deadline"])
    assert is_iso8601_timestamp(data["affirmation_deadline"])
    assert data["status"] in ("OPEN", "NETTED", "SETTLED", "CLOSED")


# ─── NetPosition (PRD §3.5, §3.6, §3.7) ───────────────

def assert_net_position(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["window_id"])
    assert is_valid_uuid(data["participant_id"])
    assert is_valid_uuid(data["security_id"])
    assert isinstance(data["net_quantity"], int)
    assert isinstance(data["cash_delta_cents"], int)
    assert isinstance(data["settlement_obligation_cents"], int)
    assert data["dvp_status"] in ("FUNDED", "DELIVERED", "RECEIVED", "FAILED")
    assert isinstance(data["funded_amount_cents"], int)
    assert isinstance(data["mark_to_market_cents"], int)


def assert_net_position_invariants(data: dict) -> None:
    """Funding is never required against a net receipt (PRD §3.5)."""
    assert data["settlement_obligation_cents"] == max(data["cash_delta_cents"], 0), (
        f"settlement_obligation_cents must be max(cash_delta_cents, 0): "
        f"cash_delta={data['cash_delta_cents']}, obligation={data['settlement_obligation_cents']}"
    )
    assert 0 <= data["funded_amount_cents"] <= data["settlement_obligation_cents"], (
        "funded_amount_cents saturates at settlement_obligation_cents"
    )


# ─── CorporateAction (PRD §3.8) ───────────────────────

def assert_corporate_action(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["security_id"])
    assert data["action_type"] in ("SPLIT", "REVERSE_SPLIT", "CASH_DIVIDEND")
    assert isinstance(data["ratio_numerator"], int)
    assert isinstance(data["ratio_denominator"], int) and data["ratio_denominator"] > 0
    assert isinstance(data["cash_rate_cents_per_unit"], int)
    assert data["status"] in ("ANNOUNCED", "APPLIED", "REVERSED")


# ─── ClearingFund / FundComponent (PRD §2.13, §3.9) ───

def assert_clearing_fund(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["security_id"])
    assert data["status"] in ("OPEN", "RECOMPUTED")
    assert isinstance(data["fund_balance_cents"], int)
    assert isinstance(data["total_component_cents"], int)
    assert data["participant_class"] in (
        "BANK", "BROKER_DEALER", "CUSTODIAN_BANK", "INSURANCE_CARRIER")
    assert isinstance(data["experiences_deficit"], bool)


def assert_fund_component(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["clearing_fund_id"])
    assert is_valid_uuid(data["participant_id"])
    assert isinstance(data["component_amount_cents"], int)
    assert isinstance(data["component_balance_cents"], int)
    assert isinstance(data["generation"], int) and data["generation"] >= 1
    assert data["status"] in ("ASSESSED", "COLLECTED", "RELEASED")


# ─── DefaultProceeding / LossAllocationTransaction (PRD §3.9) ───

def assert_default_proceeding(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["participant_id"])
    assert isinstance(data["reason_code"], str)
    assert data["status"] in ("DECLARED", "LIQUIDATING", "LIQUIDATED", "ALLOCATED")
    assert isinstance(data["liquidation_proceeds_cents"], int)
    assert isinstance(data["deficit_amount_cents"], int)
    assert isinstance(data["defaulter_resources_cents"], int)
    assert isinstance(data["allocated_total_cents"], int)


def assert_loss_allocation_transaction(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["default_proceeding_id"])
    assert is_valid_uuid(data["fund_component_id"])
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data["posted_at"])


# ─── Cross-entity invariants ──────────────────────────

def assert_netting_sum(total_net_quantity: int,
                       buy_quantity: int, sell_quantity: int) -> None:
    assert total_net_quantity == buy_quantity - sell_quantity, (
        f"net_quantity must be signed buy minus sell: {buy_quantity} - {sell_quantity} "
        f"= {buy_quantity - sell_quantity}, got {total_net_quantity}"
    )


def assert_loss_allocation_pairing(allocation_amounts: list, deficit_amount_cents: int) -> None:
    """After the remainder repair the written amounts sum to -deficit exactly (PRD §3.9)."""
    total = sum(allocation_amounts)
    assert total == -deficit_amount_cents, (
        f"SUM(loss allocation amounts) must equal -deficit: expected "
        f"{-deficit_amount_cents}, got {total}"
    )