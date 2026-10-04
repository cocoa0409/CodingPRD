"""Entity assertions and domain invariant checkers.

Every entity here carries the standard server-managed quartet except
``AuditEvent``, which is immutable and carries only ``id`` and ``created_at``.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """AuditEvent contract: id + created_at only, and no mutations."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an audit event has no updated_at"
    assert "version" not in data, "an audit event has no version"


# ─── Ledger ───────────────────────────────────────────

def assert_ledger(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["currency"] in ("USD", "EUR", "GBP")
    assert isinstance(data["period_index"], int)
    assert isinstance(data["period_closed_through_index"], int)
    for field in ("pending_balance_cents", "posted_balance_cents",
                  "delivered_fee_transfers_cents", "undeliverable_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in ("OPEN", "CLOSED")


def assert_ledger_invariants(data: dict):
    """Domain invariants that must hold after any ledger-scoped operation."""
    assert isinstance(data["pending_balance_cents"], int)
    assert isinstance(data["posted_balance_cents"], int)
    assert data["delivered_fee_transfers_cents"] >= 0
    assert data["undeliverable_cents"] >= 0
    assert data["period_index"] >= 1
    assert data["period_closed_through_index"] >= 0


# ─── Legal entity / counterparty / relationship ───────

def assert_legal_entity(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["short_code"], str) and data["short_code"]
    assert data["entity_type"] in ("PLATFORM", "ORGANISATION")
    assert isinstance(data["default_velocity_limit_cents"], int)
    if data["entity_type"] == "ORGANISATION":
        assert data["home_ledger_id"] is not None, \
            "an ORGANISATION row must name its home_ledger_id"


def assert_counterparty(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["legal_entity_id"])
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert data["velocity_limit_cents"] is None or isinstance(data["velocity_limit_cents"], int)
    assert data["status"] in ("ACTIVE", "RESTRICTED", "BLOCKED", "CLOSED")


def assert_relationship(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["legal_entity_id"])
    assert is_valid_uuid(data["partner_legal_entity_id"])
    assert data["legal_entity_id"] != data["partner_legal_entity_id"]
    assert data["purpose"] in ("ACCOUNT_SHARING", "PAYMENT_RAIL_AGREEMENT", "DISPUTE_CHANNEL")
    assert isinstance(data["account_data_sharing"], bool)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")


# ─── Accounts ─────────────────────────────────────────

def assert_bank_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["legal_entity_id"])
    assert isinstance(data["institution_name"], str) and data["institution_name"]
    assert isinstance(data["routing_number"], str) and len(data["routing_number"]) == 9
    assert isinstance(data["account_number_last4"], str) and len(data["account_number_last4"]) == 4
    assert isinstance(data["supported_rails"], list) and data["supported_rails"]
    assert set(data["supported_rails"]).issubset({"ACH", "WIRE", "RTP", "CHECK"})
    assert isinstance(data["available_funds_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_virtual_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bank_account_id"])
    assert isinstance(data["virtual_account_number"], str)
    assert 10 <= len(data["virtual_account_number"]) <= 16
    assert isinstance(data["reference_code"], str)
    assert 6 <= len(data["reference_code"]) <= 12
    assert data["status"] in ("OPEN", "CLOSED")


# ─── Statements ───────────────────────────────────────

def assert_bank_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bank_account_id"])
    assert isinstance(data["institution_ref"], str) and data["institution_ref"]
    assert is_iso8601_timestamp(data["cycle_date"])
    assert isinstance(data["opening_balance_cents"], int)
    assert isinstance(data["closing_balance_cents"], int)
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["matched_posted_cents"], int)
    assert isinstance(data["unmatched_amount_cents"], int)
    assert data["status"] in ("IMPORTED", "RECONCILING", "RECONCILED",
                              "DISCREPANCY", "REVISED", "SUPERSEDED")


def assert_statement_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bank_statement_id"])
    assert isinstance(data["bank_reference"], str) and data["bank_reference"]
    assert isinstance(data["amount_cents"], int)
    assert data["direction"] in ("CREDIT", "DEBIT")
    assert is_iso8601_timestamp(data["effective_at"])
    assert data["match_state"] in ("UNMATCHED", "MATCHED", "IGNORED")


# ─── Payment orders ───────────────────────────────────

def assert_payment_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["legal_entity_id"])
    assert is_valid_uuid(data["ledger_id"])
    assert is_valid_uuid(data["counterparty_id"])
    assert is_valid_uuid(data["source_account_id"])
    assert data["rail"] in ("ACH", "WIRE", "RTP", "CHECK")
    assert data["direction"] in ("CREDIT", "DEBIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["settlement_speed"] in ("STANDARD", "SAME_DAY")
    assert isinstance(data["idempotency_key"], str) and data["idempotency_key"]
    assert isinstance(data["cutoffs"], list)
    assert data["status"] in ("PENDING_APPROVAL", "APPROVED", "ACH_DISPATCHED",
                              "WIRE_DISPATCHED", "RTP_DISPATCHED", "CHECK_DISPATCHED",
                              "IN_FLIGHT", "SETTLED", "RETURNED", "REVERSED", "CANCELLED")
    assert data["settlement_status"] in ("UNSETTLED", "IN_SETTLEMENT", "SETTLED", "FAILED")


# ─── Transactions ─────────────────────────────────────

def assert_transaction(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ledger_id"])
    assert data["entry_type"] in ("ORIGINATING", "RETURN", "REVERSAL", "FEE",
                                  "ADJUSTMENT", "DEPOSIT")
    assert data["direction"] in ("DEBIT", "CREDIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["net_effect_cents"], int)
    assert is_iso8601_timestamp(data["value_effective_utc"])
    assert data["lifecycle_status"] in ("PENDING", "POSTED", "VOID", "REJECTED")
    assert data["settlement_status"] in ("UNSETTLED", "IN_SETTLEMENT", "SETTLED")


def assert_net_effect_matches_direction(data: dict):
    """net_effect_cents is the negative of amount_cents for DEBIT and positive for CREDIT."""
    expected = -data["amount_cents"] if data["direction"] == "DEBIT" else data["amount_cents"]
    assert data["net_effect_cents"] == expected, (
        f"net_effect_cents {data['net_effect_cents']} does not match direction "
        f"{data['direction']} over amount {data['amount_cents']}"
    )


# ─── Exceptions ───────────────────────────────────────

def assert_exception_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ledger_id"])
    assert data["kind"] in ("UNMATCHED_DEPOSIT", "RETURN", "REVERSAL",
                            "FAILED_PAYMENT", "STATEMENT_VARIANCE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["attributed_fee_cents"], int)
    assert isinstance(data["attributable_amount_cents"], int)
    assert is_iso8601_timestamp(data["opened_utc"])
    assert isinstance(data["age_business_days"], int)
    assert data["aging_bucket"] in ("CURRENT", "AGING", "ESCALATED", "CRITICAL")
    assert data["status"] in ("OPEN", "ASSIGNED", "ESCALATED", "RESOLVED", "WAIVED")


# ─── Pools, release requests, calendar, audit ─────────

def assert_settlement_pool(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ledger_id"])
    assert isinstance(data["member_bank_account_ids"], list)
    assert data["forced_settlement_status"] in ("READY", "DEGRADED", "FAILED")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_pool_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["settlement_pool_id"])
    assert is_valid_uuid(data["bank_account_id"])
    assert isinstance(data["weight_units"], int) and data["weight_units"] > 0


def assert_release_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["payment_order_id"])
    assert is_valid_uuid(data["counterparty_id"])
    assert is_iso8601_timestamp(data["needed_by_utc"])
    assert data["request_state"] in ("PENDING", "SATISFIED", "DECLINED", "DENIED")


def assert_banking_calendar(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["legal_entity_id"])
    assert data["timezone"] in ("America/New_York", "America/Chicago", "Europe/London")
    assert isinstance(data["is_open"], bool)
    assert isinstance(data["cutoffs"], list)
    assert isinstance(data["allowed_rails"], list)


def assert_audit_event(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["ledger_id"])
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["action"], str) and "." in data["action"]
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["details"], dict)