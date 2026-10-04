"""Entity shape assertions built on the framework's generic validators."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import types as t


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional digits.

    PRD §2.4 pins three fractional digits only for created_at/updated_at and
    api_request_timestamp; other timestamp fields (start_at, end_at,
    next_retry_at, due_before, sent_at) may be serialized with or without
    fractional digits by a faithful implementation, so tests must compare
    instants, not strings.
    """
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    """Assert two ISO 8601 strings denote the same instant."""
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601, got {actual!r}"
    a = _parse_instant(actual)
    e = _parse_instant(expected)
    assert a == e, f"{label}: expected instant {expected}, got {actual}"


def assert_common_fields(data: dict, entity_label: str = "entity"):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_append_only_fields(data: dict, entity_label: str = "record"):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity_label} must not carry updated_at"
    assert "version" not in data, f"{entity_label} must not carry version"


def assert_subscription(data: dict):
    assert_common_fields(data, "subscription")
    assert data["status"] in {
        t.SubscriptionStatus.PENDING_ACTIVATION,
        t.SubscriptionStatus.ACTIVE,
        t.SubscriptionStatus.SUSPENDED,
        t.SubscriptionStatus.CANCEL_SCHEDULED,
        t.SubscriptionStatus.CANCELLED,
        t.SubscriptionStatus.EXPIRED,
        t.SubscriptionStatus.TRANSFERRED_AWAY,
    }
    assert data["kind"] in {
        t.SubscriptionKind.TRIAL,
        t.SubscriptionKind.PAID,
        t.SubscriptionKind.SAVE_OFFER,
    }
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data.get("current_term_price_cents"), int)
    assert data["current_term_price_cents"] >= 0


def assert_radio(data: dict):
    assert_common_fields(data, "radio")
    assert data["activation_status"] in {
        t.RadioActivationStatus.UNREGISTERED,
        t.RadioActivationStatus.REGISTERED,
        t.RadioActivationStatus.SUSPENDED,
        t.RadioActivationStatus.DEACTIVATED,
    }
    assert data["hardware_generation"] in {
        t.HardwareGeneration.GEN1,
        t.HardwareGeneration.GEN2,
        t.HardwareGeneration.GEN3,
    }


def assert_signal_command(data: dict):
    assert_common_fields(data, "signal_command")
    assert data["status"] in {
        t.SignalStatus.QUEUED,
        t.SignalStatus.SENT,
        t.SignalStatus.ACKED,
        t.SignalStatus.FAILED,
        t.SignalStatus.EXHAUSTED,
        t.SignalStatus.SUPERSEDED,
    }
    assert data["command_type"] in {
        t.CommandType.ACTIVATE,
        t.CommandType.DEACTIVATE,
        t.CommandType.SUSPEND,
        t.CommandType.RESUME,
    }
    assert isinstance(data.get("attempt_count"), int)
    assert 0 <= data["attempt_count"] <= 3


def assert_ledger_entry(data: dict):
    assert_append_only_fields(data, "ledger entry")
    assert data["entry_type"] in {
        t.LedgerEntryType.CHARGE,
        t.LedgerEntryType.PRORATION_CREDIT,
        t.LedgerEntryType.REFUND,
        t.LedgerEntryType.SAVE_CREDIT,
        t.LedgerEntryType.TRANSFER_ADJUSTMENT,
    }
    assert isinstance(data.get("amount_cents"), int)


def ledger_amount_of(entries, entry_type: str):
    """Return the amount_cents of the first ledger entry of the given type."""
    for entry in entries:
        if entry.get("entry_type") == entry_type:
            return entry.get("amount_cents")
    raise AssertionError(f"no ledger entry of type {entry_type} in {entries}")


def ledger_entries_of(entries, entry_type: str):
    return [e for e in entries if e.get("entry_type") == entry_type]
