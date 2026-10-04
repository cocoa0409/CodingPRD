"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_customer_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["account_code"], str) and data["account_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["credit_hold"], bool)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_service_contract(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["contract_ref"], str) and data["contract_ref"]
    assert 0 <= data["demurrage_free_days"] <= 30
    assert 0 <= data["detention_free_days"] <= 30
    assert isinstance(data["saturday_counts_as_free_day"], bool)
    assert data["demurrage_rate_schedule"] in ("STANDARD", "EXTENDED_TIERED")
    assert data["detention_rate_schedule"] in ("STANDARD", "EXTENDED_TIERED")
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_terminal(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["terminal_code"], str) and data["terminal_code"]
    assert isinstance(data["timezone"], str) and data["timezone"]
    assert data["daily_appointment_capacity"] >= 1
    assert isinstance(data["gate_closed_weekends"], bool)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_terminal_holiday(data: dict):
    # Append-only ledger fact: id + created_at only, no updated_at, no version
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "TerminalHoliday must not carry version"
    assert "updated_at" not in data, "TerminalHoliday must not carry updated_at"


def assert_appointment_slot(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["slot_seq"], int)
    assert data["capacity"] >= 1
    assert isinstance(data["booked_count"], int)
    assert 0 <= data["booked_count"] <= data["capacity"]
    assert data["status"] in ("OPEN", "FULL", "RELEASED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_return_location(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["location_code"], str) and data["location_code"]
    assert isinstance(data["accepts_equipment_types"], list)
    assert data["daily_empty_capacity"] >= 1
    assert data["status"] in ("OPEN", "RESTRICTED", "CLOSED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_container(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["container_number"], str) and data["container_number"]
    assert data["equipment_type"] in ("DRY20", "DRY40", "DRY40HC", "REEFER40", "FLATRACK40")
    assert data["status"] in ("DISCHARGED", "AVAILABLE", "GATE_OUT", "EMPTY_RETURNED", "BILLED")
    for f in ("demurrage_billable_days", "detention_billable_days",
              "demurrage_amount_cents", "detention_amount_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative integer"
    assert isinstance(data["hold_flags"], list)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_charge_accrual(data: dict):
    # Append-only ledger fact: id + created_at only, no updated_at, no version
    assert is_valid_uuid(data.get("id", ""))
    assert data["charge_kind"] in ("DEMURRAGE", "DETENTION")
    assert isinstance(data["billable_days"], int) and data["billable_days"] >= 0
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["rate_schedule"] in ("STANDARD", "EXTENDED_TIERED")
    assert isinstance(data["voided"], bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "ChargeAccrual must not carry version"
    assert "updated_at" not in data, "ChargeAccrual must not carry updated_at"


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    for f in ("demurrage_total_cents", "detention_total_cents", "gross_amount_cents",
              "credit_total_cents", "paid_total_cents", "balance_due_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative integer"
    assert data["gross_amount_cents"] == (
        data["demurrage_total_cents"] + data["detention_total_cents"]
    ), "gross must equal demurrage + detention totals"
    assert data["balance_due_cents"] == (
        data["gross_amount_cents"] - data["credit_total_cents"] - data["paid_total_cents"]
    ), "balance_due must equal gross - credits - payments"
    assert data["aging_bucket"] in ("CURRENT", "DAYS_1_30", "DAYS_31_60", "DAYS_61_PLUS")
    assert data["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID", "DISPUTED", "WRITTEN_OFF")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_dispute(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["dispute_reason"] in (
        "APPOINTMENT_UNAVAILABLE", "CHASSIS_SHORTAGE", "CUSTOMS_HOLD",
        "FREE_TIME_MISCALC", "RATE_MISMATCH", "OTHER",
    )
    assert isinstance(data["contested_amount_cents"], int) and data["contested_amount_cents"] >= 1
    assert isinstance(data["escalated"], bool)
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "RESOLVED_FULL_CREDIT",
        "RESOLVED_PARTIAL_CREDIT", "RESOLVED_DENIED", "WITHDRAWN",
    )
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_dispute_evidence(data: dict):
    # Append-only ledger fact: id + created_at only, no updated_at, no version
    assert is_valid_uuid(data.get("id", ""))
    assert data["evidence_type"] in (
        "APPOINTMENT_SCREENSHOT", "CHASSIS_POOL_NOTICE", "CUSTOMS_HOLD_NOTICE",
        "APPOINTMENT_API_LOG", "OTHER",
    )
    assert isinstance(data["reference_uri"], str) and data["reference_uri"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "DisputeEvidence must not carry version"
    assert "updated_at" not in data, "DisputeEvidence must not carry updated_at"


def assert_credit_waiver(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["authority_tier"] in ("TIER_1_AGENT", "TIER_2_SUPERVISOR", "TIER_3_DIRECTOR")
    assert isinstance(data["justification"], str) and data["justification"]
    assert data["status"] in ("PROPOSED", "APPLIED", "REJECTED", "REVERSED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_payment(data: dict):
    # Append-only ledger fact: id + created_at only, no updated_at, no version
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] == "SETTLED"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "Payment must not carry version"
    assert "updated_at" not in data, "Payment must not carry updated_at"


def assert_invoice_net_invariant(invoice: dict):
    """The invoice net position identity must hold at all times."""
    assert invoice["balance_due_cents"] == (
        invoice["gross_amount_cents"]
        - invoice["credit_total_cents"]
        - invoice["paid_total_cents"]
    ), (
        f"Invoice net invariant violated: balance {invoice['balance_due_cents']} != "
        f"gross {invoice['gross_amount_cents']} - credits {invoice['credit_total_cents']} "
        f"- payments {invoice['paid_total_cents']}"
    )
