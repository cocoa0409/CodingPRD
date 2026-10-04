"""Payload factories — one per entity, input fields only."""
import uuid

from .constants import TEST_DEFAULTS


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_code": _unique("ACCT"),
        "legal_name": "Test Shippers LLC",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "contract_ref": _unique("CTR"),
        "demurrage_free_days": 2,
        "detention_free_days": 5,
        "saturday_counts_as_free_day": False,
        "demurrage_rate_schedule": TEST_DEFAULTS["RATE_SCHEDULE"],
        "detention_rate_schedule": TEST_DEFAULTS["RATE_SCHEDULE"],
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_to": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_terminal_payload(**overrides) -> dict:
    defaults = {
        "terminal_code": _unique("T"),
        "timezone": TEST_DEFAULTS["TERMINAL_TIMEZONE"],
        "daily_appointment_capacity": TEST_DEFAULTS["TERMINAL_DAILY_CAPACITY"],
        "gate_closed_weekends": True,
    }
    defaults.update(overrides)
    return defaults


def create_holiday_payload(**overrides) -> dict:
    defaults = {
        "holiday_date": "2026-09-07T00:00:00Z",
        "name": "Labor Day",
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(**overrides) -> dict:
    defaults = {
        "slot_date": "2026-09-10T00:00:00Z",
        "slot_seq": 1,
        "capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_return_location_payload(terminal_id, **overrides) -> dict:
    defaults = {
        "location_code": _unique("LOC"),
        "terminal_id": terminal_id,
        "accepts_equipment_types": [TEST_DEFAULTS["EQUIPMENT_TYPE"]],
        "daily_empty_capacity": TEST_DEFAULTS["LOCATION_DAILY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_container_payload(account_id, contract_id, terminal_id, **overrides) -> dict:
    defaults = {
        "container_number": f"MATU{uuid.uuid4().int % 10000000:07d}",
        "equipment_type": TEST_DEFAULTS["EQUIPMENT_TYPE"],
        "customer_account_id": account_id,
        "service_contract_id": contract_id,
        "terminal_id": terminal_id,
        "discharge_ts": "2026-08-31T12:00:00Z",
        "available_ts": "2026-09-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def set_hold_payload(hold_code="CUSTOMS_HOLD", action="PLACE", **overrides) -> dict:
    defaults = {"hold_code": hold_code, "action": action}
    defaults.update(overrides)
    return defaults


def gate_out_payload(**overrides) -> dict:
    defaults = {"slot_override": True, "slot_override_reason": "waived for test"}
    defaults.update(overrides)
    return defaults


def book_appointment_payload(slot_id, **overrides) -> dict:
    defaults = {"slot_id": slot_id}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(contested_amount_cents, **overrides) -> dict:
    defaults = {
        "dispute_reason": "OTHER",
        "contested_amount_cents": contested_amount_cents,
        "evidence_window_start": "2026-09-02T00:00:00Z",
        "evidence_window_end": "2026-09-04T00:00:00Z",
        "evidence_summary": "documented claim",
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "evidence_type": "OTHER",
        "evidence_date": "2026-09-03T00:00:00Z",
        "reference_uri": f"s3://evidence/{uuid.uuid4().hex[:8]}.png",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def propose_waiver_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "justification": "documented goodwill"}
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(resolution_code, expected_dispute_version, **overrides) -> dict:
    defaults = {
        "resolution_code": resolution_code,
        "resolution_justification": "documented resolution",
        "expected_dispute_version": expected_dispute_version,
    }
    defaults.update(overrides)
    return defaults
