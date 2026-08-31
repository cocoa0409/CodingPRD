"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import BOX_FACE_VALUE_CENTS


# ─── Shared shape helpers ─────────────────────────────────────────────────

def assert_common_fields(data: dict, entity_name: str = "resource") -> None:
    """Resources that carry the full common set: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an integer"
    assert data["version"] >= 1, f"{entity_name}.version starts at 1, got {data['version']}"


def assert_append_only_fields(data: dict, entity_name: str = "record") -> None:
    """Append-only records carry only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{entity_name} must not carry updated_at"
    assert "version" not in data, f"{entity_name} must not carry version"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z with or without
    fractional seconds."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected_iso: str, label: str = "timestamp") -> None:
    """Assert two ISO 8601 UTC timestamps name the same instant."""
    assert actual is not None, f"{label} must not be null"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_vault(data: dict) -> None:
    assert_common_fields(data, "Vault")
    assert isinstance(data["vault_code"], str) and 1 <= len(data["vault_code"]) <= 32
    assert isinstance(data["name"], str)
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN"), (
        f"Vault.posture must be OPEN, RESTRICTED or FROZEN, got {data['posture']!r}"
    )
    assert isinstance(data["pickup_concurrency_limit"], int)
    assert data["pickup_concurrency_limit"] >= 1
    assert isinstance(data["cash_letter_adjustment_cents"], int)
    assert isinstance(data["coin_face_value_on_hand_cents"], int)


def assert_customer_account(data: dict) -> None:
    assert_common_fields(data, "CustomerAccount")
    assert isinstance(data["account_number"], str)
    assert isinstance(data["customer_name"], str)
    assert data["tier"] in ("PREMIUM", "STANDARD", "WATCH")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for field in (
        "ledger_balance_cents",
        "provisional_credit_cents",
        "available_balance_cents",
        "denied_claim_count",
        "counterfeit_incident_count",
        "hold_count",
    ):
        assert isinstance(data[field], int), f"CustomerAccount.{field} must be an integer"
    assert isinstance(data["risk_score"], (int, float))
    assert data["risk_grade"] in ("A", "B", "C", "D")
    assert_account_balance_identity(data)


def assert_account_balance_identity(data: dict) -> None:
    """available_balance_cents always equals ledger_balance_cents + provisional_credit_cents."""
    expected = data["ledger_balance_cents"] + data["provisional_credit_cents"]
    assert data["available_balance_cents"] == expected, (
        "available_balance_cents must equal ledger_balance_cents + provisional_credit_cents: "
        f"{data['available_balance_cents']} != {data['ledger_balance_cents']} + "
        f"{data['provisional_credit_cents']}"
    )


def assert_deposit_ticket(data: dict) -> None:
    assert_common_fields(data, "DepositTicket")
    assert is_valid_uuid(data["customer_account_id"])
    assert is_valid_uuid(data["vault_id"])
    assert isinstance(data["courier_manifest_number"], str)
    assert isinstance(data["carrier_courier_user_id"], str)
    assert isinstance(data["declared_bag_count"], int) and data["declared_bag_count"] >= 1
    assert data["status"] in (
        "INTAKE",
        "VERIFIED",
        "PROVISIONAL_CREDITED",
        "HELD",
        "SETTLEMENT_READY",
        "SETTLED",
    ), f"DepositTicket.status unexpected: {data['status']!r}"
    for field in (
        "declared_total_cents",
        "counted_total_cents",
        "processing_fee_total_cents",
        "provisional_credit_cents",
        "final_settlement_cents",
        "settlement_delta_cents",
        "material_variance_open_count",
    ):
        assert isinstance(data[field], int), f"DepositTicket.{field} must be an integer"


def assert_sealed_bag(data: dict) -> None:
    assert_common_fields(data, "SealedBag")
    assert is_valid_uuid(data["deposit_ticket_id"])
    assert isinstance(data["seal_number"], str)
    assert data["bag_type"] in ("CURRENCY", "COIN", "MIXED")
    assert data["custody_status"] in ("SEALED", "IN_TRANSIT", "VAULT_RECEIVED", "OPENED")
    assert data["count_status"] in ("PENDING", "COUNTING", "COUNTED", "ADJUSTED")
    for field in (
        "declared_amount_cents",
        "declared_note_count",
        "declared_coin_weight_grams",
        "counted_amount_cents",
        "counted_note_count",
        "counted_coin_weight_grams",
        "variance_cents",
        "processing_fee_cents",
        "seized_amount_cents",
        "claim_adjustment_cents",
        "settlement_amount_cents",
    ):
        assert isinstance(data[field], int), f"SealedBag.{field} must be an integer"
    assert isinstance(data["materiality_flag"], bool)
    assert data["declared_amount_cents"] >= 0


def assert_bag_settlement_identity(data: dict) -> None:
    """settlement_amount_cents = counted_amount_cents + claim_adjustment_cents - seized_amount_cents."""
    expected = (
        data["counted_amount_cents"] + data["claim_adjustment_cents"] - data["seized_amount_cents"]
    )
    assert data["settlement_amount_cents"] == expected, (
        "settlement_amount_cents must equal counted_amount_cents + claim_adjustment_cents "
        f"- seized_amount_cents: {data['settlement_amount_cents']} != {expected}"
    )


def assert_custody_event(data: dict) -> None:
    assert_append_only_fields(data, "CustodyEvent")
    assert is_valid_uuid(data["sealed_bag_id"])
    assert data["event_type"] in ("PICKUP", "TRANSFER", "VAULT_RECEIPT", "OPEN")
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["location_code"], str)
    assert isinstance(data["observed_seal_number"], str)
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["seal_intact"], bool)


def assert_counting_machine(data: dict) -> None:
    assert_common_fields(data, "CountingMachine")
    assert is_valid_uuid(data["vault_id"])
    assert isinstance(data["machine_code"], str)
    assert data["machine_type"] in ("CURRENCY_SORTER", "COIN_COUNTER", "MIXED_PROCESSOR")
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")


def assert_count_session(data: dict) -> None:
    assert_common_fields(data, "CountSession")
    assert is_valid_uuid(data["sealed_bag_id"])
    assert is_valid_uuid(data["counting_machine_id"])
    assert isinstance(data["operator_user_id"], str) and data["operator_user_id"]
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "SUPERSEDED")
    for field in (
        "counted_amount_cents",
        "counted_note_count",
        "counted_coin_weight_grams",
        "seized_face_value_cents",
    ):
        assert isinstance(data[field], int), f"CountSession.{field} must be an integer"


def assert_fitness_lot(data: dict) -> None:
    assert_common_fields(data, "FitnessLot")
    assert is_valid_uuid(data["count_session_id"])
    assert data["category"] in ("FIT", "UNFIT", "COUNTERFEIT_SUSPECT")
    assert data["status"] in (
        "PENDING_DEPOSIT",
        "PENDING_REVIEW",
        "ATTACHED",
        "DEPOSITED",
        "SEIZED",
    )
    assert isinstance(data["denomination_cents"], int)
    assert isinstance(data["note_count"], int) and data["note_count"] >= 1
    assert data["face_value_cents"] == data["denomination_cents"] * data["note_count"], (
        "FitnessLot.face_value_cents must equal denomination_cents * note_count"
    )


def assert_counterfeit_report(data: dict) -> None:
    assert_common_fields(data, "CounterfeitReport")
    assert is_valid_uuid(data["fitness_lot_id"])
    assert isinstance(data["serial_number"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED")
    assert isinstance(data["denomination_cents"], int)
    assert isinstance(data["note_count"], int)
    assert data["seized_face_value_cents"] == data["denomination_cents"] * data["note_count"], (
        "CounterfeitReport.seized_face_value_cents must equal denomination_cents * note_count"
    )


def assert_discrepancy_claim(data: dict) -> None:
    assert_common_fields(data, "DiscrepancyClaim")
    assert is_valid_uuid(data["sealed_bag_id"])
    assert is_valid_uuid(data["customer_account_id"])
    assert data["claim_type"] in ("COUNT_VARIANCE", "STATEMENT_ADJUSTMENT")
    assert data["status"] in ("SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED")
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 1
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1
    assert isinstance(data["resolution_amount_cents"], int)
    assert is_iso8601_timestamp(data["filed_at"]), "DiscrepancyClaim.filed_at must be ISO 8601"


def assert_fed_deposit(data: dict) -> None:
    assert_common_fields(data, "FedDeposit")
    assert is_valid_uuid(data["vault_id"])
    assert isinstance(data["cash_letter_number"], str)
    assert isinstance(data["deposit_date"], str)
    assert data["status"] in (
        "PREPARED",
        "SUBMITTED",
        "CONFIRMED",
        "CONFIRMED_WITH_ADJUSTMENT",
    )
    for field in (
        "declared_total_cents",
        "credited_total_cents",
        "adjustment_cents",
        "attached_lot_count",
    ):
        assert isinstance(data[field], int), f"FedDeposit.{field} must be an integer"


def assert_coin_order(data: dict) -> None:
    assert_common_fields(data, "CoinOrder")
    assert is_valid_uuid(data["customer_account_id"])
    assert is_valid_uuid(data["vault_id"])
    assert data["status"] in (
        "REQUESTED",
        "APPROVED_FULL",
        "APPROVED_PARTIAL",
        "REJECTED",
        "RELEASED",
        "RETURNED",
    )
    for field in ("total_boxes_requested", "total_boxes_allocated", "charge_cents"):
        assert isinstance(data[field], int), f"CoinOrder.{field} must be an integer"
    assert isinstance(data["fill_ratio_pct"], (int, float))


def assert_coin_order_line(data: dict) -> None:
    assert_append_only_fields(data, "CoinOrderLine")
    assert is_valid_uuid(data["coin_order_id"])
    assert data["denomination"] in ("PENNY", "NICKEL", "DIME", "QUARTER")
    for field in ("boxes_requested", "boxes_allocated", "boxes_returned", "line_face_value_cents"):
        assert isinstance(data[field], int), f"CoinOrderLine.{field} must be an integer"
    assert data["line_face_value_cents"] == (
        data["boxes_allocated"] * BOX_FACE_VALUE_CENTS[data["denomination"]]
    ), "CoinOrderLine.line_face_value_cents must equal boxes_allocated * the box face value"


def assert_vault_inventory(data: dict) -> None:
    assert_common_fields(data, "VaultInventory")
    assert is_valid_uuid(data["vault_id"])
    assert data["denomination"] in ("PENNY", "NICKEL", "DIME", "QUARTER")
    for field in ("on_hand_boxes", "reserved_boxes", "available_boxes"):
        assert isinstance(data[field], int), f"VaultInventory.{field} must be an integer"
    assert data["on_hand_boxes"] >= 0, "on_hand_boxes must never go below zero"
    assert data["available_boxes"] == max(data["on_hand_boxes"] - data["reserved_boxes"], 0), (
        "available_boxes must equal on_hand_boxes minus reserved_boxes, floored at 0"
    )


def assert_customer_statement(data: dict) -> None:
    assert is_valid_uuid(data["customer_account_id"])
    for field in (
        "ledger_balance_cents",
        "provisional_credit_cents",
        "available_balance_cents",
        "open_ticket_count",
        "settled_ticket_count",
        "open_claim_count",
    ):
        assert isinstance(data[field], int), f"statement.{field} must be an integer"
    for field in ("risk_score", "projected_risk_score"):
        assert isinstance(data[field], (int, float)), f"statement.{field} must be numeric"
    for field in ("risk_grade", "projected_risk_grade"):
        assert data[field] in ("A", "B", "C", "D"), f"statement.{field} must be a letter band"


def assert_cash_letter_reconciliation(data: dict) -> None:
    assert is_valid_uuid(data["vault_id"])
    for field in (
        "shipped_total_cents",
        "credited_total_cents",
        "outstanding_cents",
        "net_adjustment_cents",
    ):
        assert isinstance(data[field], int), f"reconciliation.{field} must be an integer"
    assert isinstance(data["reconciled"], bool)


# ─── Domain helpers ───────────────────────────────────────────────────────

def vault_coin_face_value(positions: list) -> int:
    """SUM over positions of on_hand_boxes * the standard box face value."""
    return sum(p["on_hand_boxes"] * BOX_FACE_VALUE_CENTS[p["denomination"]] for p in positions)


def find_inventory_position(positions: list, denomination: str) -> Optional[dict]:
    for position in positions:
        if position["denomination"] == denomination:
            return position
    return None


def find_coin_order_line(lines: list, denomination: str) -> Optional[dict]:
    for line in lines:
        if line["denomination"] == denomination:
            return line
    return None


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "parse_instant",
    "assert_instant_equals",
    "assert_vault",
    "assert_customer_account",
    "assert_account_balance_identity",
    "assert_deposit_ticket",
    "assert_sealed_bag",
    "assert_bag_settlement_identity",
    "assert_custody_event",
    "assert_counting_machine",
    "assert_count_session",
    "assert_fitness_lot",
    "assert_counterfeit_report",
    "assert_discrepancy_claim",
    "assert_fed_deposit",
    "assert_coin_order",
    "assert_coin_order_line",
    "assert_vault_inventory",
    "assert_customer_statement",
    "assert_cash_letter_reconciliation",
    "vault_coin_face_value",
    "find_inventory_position",
    "find_coin_order_line",
]
