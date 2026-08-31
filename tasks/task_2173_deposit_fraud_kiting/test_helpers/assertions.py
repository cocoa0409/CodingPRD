"""Entity assertions and domain invariant checkers."""

import re
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

BARE_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_FRACTIONAL_TS_RE = re.compile(r"\.\d{3}(Z|[+-]\d{2}:?\d{2})$")


# ---------------------------------------------------------------------------
# Timestamp utilities
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into an aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Both values must denote the same UTC instant, whatever the spelling."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected the instant {expected_iso}, got {actual}"
    )


def assert_three_fractional_digits(value: str, label: str = "timestamp"):
    """PRD §2.4: created_at / updated_at carry three fractional digits."""
    assert _FRACTIONAL_TS_RE.search(value), (
        f"{label} must be an ISO 8601 UTC timestamp with three fractional digits, got {value!r}"
    )


def plus_days(iso: str, days: int) -> str:
    """The same instant advanced by whole calendar days, spelled with a Z."""
    moved = parse_instant(iso) + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Common-field assertions
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict, label: str = "resource"):
    """PRD §2.4: every resource exposes id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert BARE_UUID_RE.match(data["id"]), (
        f"{label}.id must be a bare UUID with no type prefix, got {data['id']!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer at least 1, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_customer(data: dict):
    assert_common_fields(data, "Customer")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert re.fullmatch(r"\d{4}", data["tin_last4"]), "tin_last4 must be exactly four digits"
    assert data["kyc_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["watchlist_hit"], bool)
    assert isinstance(data["preservation_hold_active"], bool)
    assert isinstance(data["open_fraud_case_count"], int)


def assert_deposit_account(data: dict):
    assert_common_fields(data, "DepositAccount")
    assert is_valid_uuid(data["customer_id"])
    assert data["product_type"] in ("CHECKING", "SAVINGS", "MONEY_MARKET")
    assert data["open_channel"] in ("BRANCH", "ONLINE", "MOBILE")
    assert is_iso8601_timestamp(data["opened_at"])
    assert data["lifecycle_status"] in (
        "PENDING_FUNDING", "ACTIVE", "RESTRICTED", "CLOSED", "CHARGED_OFF",
    )
    assert data["access_posture"] in ("NORMAL", "STEP_UP_REQUIRED", "LOCKED")
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert data["risk_band"] in ("STANDARD", "ELEVATED", "HIGH")
    assert data["risk_score_basis"] in ("PROVISIONAL_AT_OPEN", "REFRESHED")
    assert isinstance(data["ato_indicator_codes"], list)
    assert isinstance(data["ato_score"], int) and 0 <= data["ato_score"] <= 100
    assert isinstance(data["step_up_failure_count"], int)
    for field in (
        "ledger_balance_cents", "available_balance_cents",
        "held_amount_cents", "charged_off_amount_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["closure_reason"] in (None, "MULE_SUBSTANTIATED", "KITING_SUBSTANTIATED")
    assert_funds_conservation(data)


def assert_funding_source(data: dict):
    assert_common_fields(data, "FundingSource")
    assert is_valid_uuid(data["account_id"])
    assert data["source_type"] in ("EXTERNAL_ACH", "WIRE", "CARD_PUSH")
    assert re.fullmatch(r"\d{4}", data["routing_last4"])
    assert data["verification_status"] in (
        "DECLARED", "MICRO_DEPOSIT_SENT", "FAILED_ATTEMPT", "VERIFIED", "BLOCKED",
    )
    assert isinstance(data["attempt_count"], int)
    assert isinstance(data["total_attempt_count"], int)


def assert_account_link(data: dict):
    assert_common_fields(data, "AccountLink")
    assert is_valid_uuid(data["from_account_id"])
    assert is_valid_uuid(data["to_account_id"])
    assert data["link_type"] in (
        "SHARED_DEVICE", "SHARED_ADDRESS", "SHARED_PHONE", "TRANSFER_COUNTERPARTY",
    )
    assert isinstance(data["confidence_bps"], int) and 0 <= data["confidence_bps"] <= 10000
    assert isinstance(data["is_risk_bearing"], bool)


def assert_deposit_item(data: dict):
    assert_common_fields(data, "DepositItem")
    assert is_valid_uuid(data["account_id"])
    assert data["item_type"] in ("CHECK", "ACH", "CASH")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert is_iso8601_timestamp(data["deposit_at"])
    assert data["status"] in ("PENDING", "CLEARED", "RETURNED")
    assert data["return_reason"] in (
        None, "NSF", "ACCOUNT_CLOSED", "UNCOLLECTED_FUNDS", "STOP_PAYMENT",
    )
    assert isinstance(data["immediate_credit_cents"], int)
    assert isinstance(data["held_cents"], int)
    assert data["immediate_credit_cents"] + data["held_cents"] == data["amount_cents"], (
        "immediate_credit_cents plus held_cents must equal amount_cents"
    )


def assert_check_hold(data: dict):
    assert_common_fields(data, "CheckHold")
    assert is_valid_uuid(data["deposit_item_id"])
    assert data["hold_type"] in (
        "STANDARD", "EXCEPTION_NEW_ACCOUNT", "EXCEPTION_LARGE_DEPOSIT",
        "EXCEPTION_RISK", "EXCEPTION_FRAUD",
    )
    assert isinstance(data["held_amount_cents"], int) and data["held_amount_cents"] >= 0
    assert is_iso8601_timestamp(data["hold_start_at"])
    assert is_iso8601_timestamp(data["hold_release_at"])
    assert data["status"] in ("ACTIVE", "RELEASED", "OVERRIDDEN", "CHARGED_BACK")


def assert_hold_override_review(data: dict):
    assert_common_fields(data, "HoldOverrideReview")
    assert is_valid_uuid(data["check_hold_id"])
    assert isinstance(data["requested_release_cents"], int) and data["requested_release_cents"] >= 1
    assert is_iso8601_timestamp(data["release_effective_at"])
    assert is_iso8601_timestamp(data["release_window_end_at"])
    assert parse_instant(data["release_window_end_at"]) > parse_instant(data["release_effective_at"])
    assert isinstance(data["justification"], str) and 1 <= len(data["justification"]) <= 500
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "RETURNED_FOR_INFO", "APPROVED",
        "DENIED", "EXECUTED", "SUPERSEDED",
    )
    assert isinstance(data["loss_exposure_cents"], int)
    assert isinstance(data["adjusted_exposure_cents"], int)
    assert isinstance(data["revision_count"], int)


def assert_fraud_case(data: dict):
    assert_common_fields(data, "FraudCase")
    assert is_valid_uuid(data["primary_account_id"])
    assert data["case_type"] in ("KITING", "MULE")
    assert data["status"] in (
        "OPENED", "INVESTIGATING", "SUBSTANTIATED", "UNSUBSTANTIATED", "CLOSED",
    )
    assert data["detection_source"] in ("KITING_SCAN", "ANALYST_MANUAL")
    assert data["scan_mode"] in (None, "STRICT", "INCLUSIVE")
    assert isinstance(data["cycle_account_ids"], list)
    assert isinstance(data["exposure_at_risk_cents"], int)
    assert isinstance(data["reopen_count"], int)


def assert_charge_off(data: dict):
    assert_common_fields(data, "ChargeOff")
    assert is_valid_uuid(data["account_id"])
    for field in (
        "gross_loss_cents", "collateral_offset_cents", "base_net_cents",
        "recovery_fee_cents", "net_charge_off_cents", "principal_recovered_cents",
        "fee_recovered_cents", "outstanding_loss_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in (
        "PROPOSED", "APPROVED", "BOOKED", "REFERRED_TO_RECOVERY",
        "RECOVERED_PARTIAL", "RECOVERED_FULL", "REVERSED", "SUPERSEDED",
    )
    assert_charge_off_invariants(data)


def assert_subpoena_request(data: dict):
    assert_common_fields(data, "SubpoenaRequest")
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["issuing_agency"], str) and 1 <= len(data["issuing_agency"]) <= 120
    assert isinstance(data["docket_number"], str) and 1 <= len(data["docket_number"]) <= 64
    assert is_iso8601_timestamp(data["received_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert is_iso8601_timestamp(data["preservation_start_at"])
    assert is_iso8601_timestamp(data["preservation_end_at"])
    assert parse_instant(data["preservation_end_at"]) > parse_instant(data["preservation_start_at"])
    assert data["status"] in (
        "RECEIVED", "UNDER_LEGAL_REVIEW", "PRODUCED", "OBJECTED", "QUASHED",
    )
    assert isinstance(data["is_late"], bool)


def assert_bsa_referral(data: dict):
    assert_common_fields(data, "BsaReferral")
    assert is_valid_uuid(data["fraud_case_id"])
    assert isinstance(data["narrative"], str) and 1 <= len(data["narrative"]) <= 2000
    assert data["suspected_activity_code"] in (
        "KITING", "MULE_ACTIVITY", "STRUCTURING", "ACCOUNT_TAKEOVER",
    )
    assert isinstance(data["aggregate_amount_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")
    assert isinstance(data["drafted_by_user_id"], str) and data["drafted_by_user_id"]
    assert isinstance(data["revision_count"], int)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_funds_conservation(account: dict):
    """PRD §2.9: available_balance_cents + held_amount_cents == ledger_balance_cents."""
    assert (
        account["available_balance_cents"] + account["held_amount_cents"]
        == account["ledger_balance_cents"]
    ), (
        "funds conservation broken: "
        f"available {account['available_balance_cents']} + held {account['held_amount_cents']} "
        f"!= ledger {account['ledger_balance_cents']}"
    )


def assert_charge_off_invariants(charge_off: dict):
    """PRD §3.8: outstanding_loss_cents is the derived residual and never negative."""
    assert charge_off["outstanding_loss_cents"] >= 0, "outstanding_loss_cents must never be negative"
    assert (
        charge_off["outstanding_loss_cents"]
        == charge_off["net_charge_off_cents"]
        - charge_off["principal_recovered_cents"]
        - charge_off["fee_recovered_cents"]
    ), "outstanding_loss_cents must equal net less principal recovered less fee recovered"


def assert_net_bank_position(account: dict, expected: int):
    """PRD §2.9: ledger_balance_cents minus charged_off_amount_cents."""
    actual = account["ledger_balance_cents"] - account["charged_off_amount_cents"]
    assert actual == expected, (
        f"net bank position expected {expected}, got {actual} "
        f"(ledger {account['ledger_balance_cents']}, "
        f"charged off {account['charged_off_amount_cents']})"
    )


def assert_account_balances(account: dict, ledger: int, available: int, held: int):
    """Assert the whole balance triple at once and re-check conservation."""
    assert account["ledger_balance_cents"] == ledger, (
        f"ledger_balance_cents expected {ledger}, got {account['ledger_balance_cents']}"
    )
    assert account["available_balance_cents"] == available, (
        f"available_balance_cents expected {available}, got {account['available_balance_cents']}"
    )
    assert account["held_amount_cents"] == held, (
        f"held_amount_cents expected {held}, got {account['held_amount_cents']}"
    )
    assert_funds_conservation(account)
