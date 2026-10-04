"""Entity assertions and domain invariant checkers (PRD §2.2–§2.7, §3).

`assert_<entity>(data)` checks the structural contract of one resource: field
presence, primitive types, and enum membership. Expected *values* are never
hardcoded here — callers pass them to the generic checkers (e.g.
`assert_purse_balances(purse, ledger=..., spendable=...)`).

`canonical_instant` / `instants_equal` compare ISO-8601 instants at second
precision so that a server emitting zero, three, or more fractional digits
never turns into a false failure.
"""
import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountStatus,
    AuthorizationType,
    BatchStatus,
    CardStatus,
    ContractStatus,
    CreditStatus,
    DeliveryStatus,
    DeliveryType,
    DisputeStatus,
    DisputeType,
    InvestigationStatus,
    ItemRestrictionMode,
    ItemStatus,
    LedgerEntryType,
    PostingStatus,
    ProgramStatus,
    ProgramType,
    PurseStatus,
    RetailerStatus,
    TxnStatus,
)

_INSTANT_RE = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?P<frac>\.\d+)?(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 instant to `YYYY-MM-DDTHH:MM:SSZ`."""
    if value is None:
        return None
    match = _INSTANT_RE.match(str(value).strip())
    if not match:
        return value
    return match.group("base") + "Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO-8601 instants name the same second."""
    return canonical_instant(left) == canonical_instant(right)


def _assert_common_fields(data: Dict[str, Any], label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def _assert_enum(data: Dict[str, Any], field: str, enum_cls, label: str) -> None:
    values = [member.value for member in enum_cls]
    assert data.get(field) in values, f"{label}.{field} must be one of {values}, got {data.get(field)!r}"


def _assert_opt_instant(data: Dict[str, Any], field: str, label: str) -> None:
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), f"{label}.{field} must be null or ISO 8601"


def _assert_opt_int(data: Dict[str, Any], field: str, label: str) -> None:
    value = data.get(field)
    assert value is None or isinstance(value, int), f"{label}.{field} must be null or int"


# --- Per-entity structural assertions ----------------------------------------

def assert_state_contract(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "StateContract")
    assert isinstance(data.get("state_code"), str) and re.match(r"^[A-Z]{2}$", data["state_code"]), (
        "state_code must be two uppercase letters"
    )
    _assert_enum(data, "contract_status", ContractStatus, "StateContract")


def assert_benefit_program(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "BenefitProgram")
    assert isinstance(data.get("contract_id"), str)
    _assert_enum(data, "program_type", ProgramType, "BenefitProgram")
    _assert_enum(data, "program_status", ProgramStatus, "BenefitProgram")
    _assert_enum(data, "item_restriction_mode", ItemRestrictionMode, "BenefitProgram")


def assert_retailer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Retailer")
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("retailer_name"), str) and data["retailer_name"]
    assert isinstance(data.get("acquirer_reference"), str) and data["acquirer_reference"]
    _assert_enum(data, "retailer_status", RetailerStatus, "Retailer")
    assert isinstance(data.get("skimming_incident_count"), int) and data["skimming_incident_count"] >= 0


def assert_retailer_item(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "RetailerItem")
    assert isinstance(data.get("retailer_id"), str)
    assert isinstance(data.get("upc"), str) and re.match(r"^[0-9]{12}$", data["upc"]), (
        "upc must be twelve digits"
    )
    assert isinstance(data.get("food_eligible"), bool)
    assert isinstance(data.get("effective_from"), str) and _DATE_RE.match(data["effective_from"])
    effective_to = data.get("effective_to")
    assert effective_to is None or (isinstance(effective_to, str) and _DATE_RE.match(effective_to))
    _assert_enum(data, "item_status", ItemStatus, "RetailerItem")


def assert_case_account(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "CaseAccount")
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("case_identifier"), str) and re.match(r"^[0-9]{10}$", data["case_identifier"])
    assert isinstance(data.get("head_of_household_name"), str) and data["head_of_household_name"]
    _assert_enum(data, "account_status", AccountStatus, "CaseAccount")


def assert_purse(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Purse")
    assert isinstance(data.get("case_account_id"), str)
    assert isinstance(data.get("program_id"), str)
    _assert_enum(data, "purse_status", PurseStatus, "Purse")
    _assert_opt_instant(data, "last_activity_at", "Purse")
    _assert_opt_instant(data, "expungement_notice_sent_at", "Purse")
    assert isinstance(data.get("ledger_balance_cents"), int), "Purse.ledger_balance_cents must be int"
    assert isinstance(data.get("spendable_balance_cents"), int), "Purse.spendable_balance_cents must be int"


def assert_ledger_entry(data: Dict[str, Any]) -> None:
    # Append-only (PRD §2.5): id + created_at, and NEVER updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "LedgerEntry.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "LedgerEntry.created_at must be ISO 8601"
    assert "updated_at" not in data, "LedgerEntry must not carry updated_at (append-only)"
    assert "version" not in data, "LedgerEntry must not carry version (append-only)"
    assert isinstance(data.get("purse_id"), str)
    _assert_enum(data, "entry_type", LedgerEntryType, "LedgerEntry")
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0, (
        "LedgerEntry.amount_cents must be a positive integer"
    )
    for ref_field in ("posting_id", "reference_id", "memo"):
        value = data.get(ref_field)
        assert value is None or isinstance(value, str), f"LedgerEntry.{ref_field} must be null or str"


def assert_benefit_posting(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "BenefitPosting")
    assert isinstance(data.get("purse_id"), str)
    assert isinstance(data.get("benefit_month"), str) and _MONTH_RE.match(data["benefit_month"])
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert isinstance(data.get("prorated"), bool)
    assert isinstance(data.get("scheduled_date"), str) and _DATE_RE.match(data["scheduled_date"])
    assert is_iso8601_timestamp(data.get("available_at", "")), "available_at must be ISO 8601"
    _assert_enum(data, "posting_status", PostingStatus, "BenefitPosting")
    _assert_opt_instant(data, "resolved_at", "BenefitPosting")


def assert_card(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Card")
    assert isinstance(data.get("case_account_id"), str)
    assert isinstance(data.get("pan_token"), str) and data["pan_token"]
    _assert_enum(data, "card_status", CardStatus, "Card")
    # pin_secret is masked in every response (PRD §3.6): never the stored value.
    pin_secret = data.get("pin_secret")
    assert pin_secret is None or pin_secret == "****", "pin_secret must be masked as '****'"
    assert isinstance(data.get("pin_fail_count"), int) and data["pin_fail_count"] >= 0
    replacement_of = data.get("replacement_of_card_id")
    assert replacement_of is None or isinstance(replacement_of, str)
    _assert_opt_int(data, "fee_charged_cents", "Card")
    assert isinstance(data.get("fee_waived"), bool)
    _assert_opt_instant(data, "mailed_at", "Card")
    _assert_opt_instant(data, "activated_at", "Card")


def assert_purchase_transaction(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "PurchaseTransaction")
    assert isinstance(data.get("retailer_id"), str)
    assert isinstance(data.get("case_account_id"), str)
    assert isinstance(data.get("card_id"), str)
    _assert_enum(data, "authorization_type", AuthorizationType, "PurchaseTransaction")
    for money_field in ("food_charge_cents", "cash_charge_cents", "disaster_charge_cents",
                        "total_cents", "exception_flag_count"):
        assert isinstance(data.get(money_field), int) and data[money_field] >= 0, (
            f"PurchaseTransaction.{money_field} must be a non-negative integer"
        )
    _assert_enum(data, "txn_status", TxnStatus, "PurchaseTransaction")
    batch_id = data.get("batch_id")
    assert batch_id is None or isinstance(batch_id, str)
    _assert_opt_instant(data, "voided_at", "PurchaseTransaction")


def assert_skimming_claim(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SkimmingClaim")
    assert isinstance(data.get("case_account_id"), str)
    assert isinstance(data.get("card_id"), str)
    assert isinstance(data.get("authorization_ids"), list) and len(data["authorization_ids"]) >= 1
    assert isinstance(data.get("claimed_amount_cents"), int) and data["claimed_amount_cents"] > 0
    assert isinstance(data.get("incident_description"), str)
    assert isinstance(data.get("freeze_purse"), bool)
    _assert_enum(data, "investigation_status", InvestigationStatus, "SkimmingClaim")
    _assert_enum(data, "credit_status", CreditStatus, "SkimmingClaim")
    assert isinstance(data.get("provisional_credit_cents"), int) and data["provisional_credit_cents"] >= 0
    _assert_opt_instant(data, "provisional_credited_at", "SkimmingClaim")
    _assert_opt_int(data, "substantiated_amount_cents", "SkimmingClaim")
    assert isinstance(data.get("filed_by_user_id"), str)
    assert data.get("filed_by_role") in ("Cardholder", "CardholderServices"), (
        "filed_by_role must be Cardholder or CardholderServices"
    )
    decided_by = data.get("decided_by_user_id")
    assert decided_by is None or isinstance(decided_by, str)
    _assert_opt_instant(data, "investigated_at", "SkimmingClaim")
    _assert_opt_instant(data, "decided_at", "SkimmingClaim")


def assert_settlement_batch(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SettlementBatch")
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("acquirer_reference"), str) and data["acquirer_reference"]
    assert isinstance(data.get("settlement_date"), str) and _DATE_RE.match(data["settlement_date"])
    assert is_iso8601_timestamp(data.get("cutoff_at", "")), "cutoff_at must be ISO 8601"
    _assert_enum(data, "batch_status", BatchStatus, "SettlementBatch")
    for money_field in ("gross_settled_cents", "txn_count", "acquirer_fee_cents",
                        "adjustment_total_cents", "net_position_cents"):
        assert isinstance(data.get(money_field), int), (
            f"SettlementBatch.{money_field} must be an integer"
        )
    assert isinstance(data.get("settled_authorization_ids"), list)
    _assert_opt_int(data, "actual_settled_cents", "SettlementBatch")
    _assert_opt_instant(data, "reconciled_at", "SettlementBatch")


def assert_settlement_dispute(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SettlementDispute")
    assert isinstance(data.get("settlement_batch_id"), str)
    _assert_enum(data, "dispute_type", DisputeType, "SettlementDispute")
    _assert_enum(data, "dispute_status", DisputeStatus, "SettlementDispute")
    assert isinstance(data.get("disputed_amount_cents"), int)
    _assert_opt_int(data, "adjustment_cents", "SettlementDispute")
    retailer_id = data.get("retailer_id")
    assert retailer_id is None or isinstance(retailer_id, str)
    filed_by = data.get("filed_by_user_id")
    assert filed_by is None or isinstance(filed_by, str)
    _assert_opt_instant(data, "decided_at", "SettlementDispute")


def assert_data_delivery(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "DataDelivery")
    assert isinstance(data.get("contract_id"), str)
    _assert_enum(data, "delivery_type", DeliveryType, "DataDelivery")
    assert isinstance(data.get("period"), str)
    _assert_enum(data, "delivery_status", DeliveryStatus, "DataDelivery")


# --- Domain invariant checkers (parameterised; no hardcoded answers) ---------

def assert_purse_balances(purse: Dict[str, Any],
                          ledger_balance_cents: Optional[int] = None,
                          spendable_balance_cents: Optional[int] = None) -> None:
    """Assert one or both balance views on a purse read (PRD §2.7)."""
    if ledger_balance_cents is not None:
        assert purse.get("ledger_balance_cents") == ledger_balance_cents, (
            f"Expected ledger_balance_cents {ledger_balance_cents}, got {purse.get('ledger_balance_cents')}"
        )
    if spendable_balance_cents is not None:
        assert purse.get("spendable_balance_cents") == spendable_balance_cents, (
            f"Expected spendable_balance_cents {spendable_balance_cents}, got {purse.get('spendable_balance_cents')}"
        )


def assert_batch_position(batch: Dict[str, Any], gross_settled_cents: int,
                          acquirer_fee_cents: int, adjustment_total_cents: int,
                          net_position_cents: int) -> None:
    """Assert the four settlement figures and their arithmetic relation (PRD §3.9)."""
    assert batch.get("gross_settled_cents") == gross_settled_cents
    assert batch.get("acquirer_fee_cents") == acquirer_fee_cents
    assert batch.get("adjustment_total_cents") == adjustment_total_cents
    assert batch.get("net_position_cents") == net_position_cents
    assert net_position_cents == gross_settled_cents - acquirer_fee_cents + adjustment_total_cents, (
        "net_position_cents must equal gross - fee + adjustments"
    )


def assert_ledger_entry_types(entries, expected_types) -> None:
    """Assert the ledger's entry_type sequence in returned (created_at ASC) order."""
    actual = [entry.get("entry_type") for entry in entries]
    assert actual == list(expected_types), f"Expected entry types {list(expected_types)}, got {actual}"


__all__ = [name for name in dir() if name.startswith("assert_") or name in ("canonical_instant", "instants_equal")]
