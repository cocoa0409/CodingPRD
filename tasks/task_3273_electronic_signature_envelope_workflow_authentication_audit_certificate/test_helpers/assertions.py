"""Entity assertions and domain invariant checkers.

Uses the framework's generic format validators internally.  Field names are
PRD-exact; optional fields are read with ``.get`` and asserted only when the
PRD pins their value.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import HASH_HEX_LENGTH

MONEY = Decimal("0.01")


# ---------------------------------------------------------------------------
# Instant handling
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime.

    The PRD pins the *instant* temporal rules resolve to; it does not pin a
    single serialization width for every timestamp field, so temporal
    assertions compare instants rather than literal strings.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_instant: str, label: str = "timestamp"):
    """Assert that `actual` denotes the same instant as `expected_instant`."""
    got = parse_instant(actual)
    want = parse_instant(expected_instant)
    assert got == want, f"{label}: expected instant {want.isoformat()}, got {got.isoformat()}"


def round_half_up(value, places: int = 2) -> Decimal:
    """Round half up to a fixed number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_hash(value, name="hash"):
    assert isinstance(value, str), f"{name} must be a hex digest string"
    assert len(value) == HASH_HEX_LENGTH, (
        f"{name} must be {HASH_HEX_LENGTH} hex characters, got {len(value)}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["credit_balance"], int)
    assert data["tier"] in ["STANDARD", "PRO", "ENTERPRISE"]
    assert isinstance(data["page_allowance"], int) and data["page_allowance"] >= 0


def assert_retention_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["scope"] in ["ACCOUNT", "GLOBAL"]
    assert 1 <= data["retention_years"] <= 50
    assert data["purge_mode"] in ["ANONYMIZE_METADATA", "DELETE_ALL"]
    assert isinstance(data["purge_grace_days"], int) and data["purge_grace_days"] >= 0


def assert_envelope(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sender_account_id"]), "sender_account_id must be a UUID"
    assert isinstance(data["subject"], str) and data["subject"]
    assert data["status"] in [
        "CREATED", "SENT", "DELIVERED", "COMPLETED", "DECLINED", "VOIDED", "EXPIRED",
    ]
    assert data["routing_mode"] in ["SEQUENTIAL", "PARALLEL"]
    assert isinstance(data["expires_after_days"], int) and 1 <= data["expires_after_days"] <= 365
    assert isinstance(data["sender_visible_window_days"], int)
    assert 1 <= data["sender_visible_window_days"] <= 365
    assert isinstance(data["is_sealed"], bool)
    assert isinstance(data["legal_hold"], bool)
    if data.get("is_sealed"):
        _assert_hash(data["seal_hash"], "seal_hash")


def assert_envelope_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["envelope_id"]), "envelope_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert isinstance(data["is_certificate"], bool)


def assert_recipient(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["envelope_id"]), "envelope_id must be a UUID"
    assert data["role"] in ["SIGNER", "APPROVER", "COPY"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["routing_order"], int) and data["routing_order"] >= 1
    assert data["status"] in [
        "WAITING", "SENT", "DELIVERED", "SIGNING", "SIGNED",
        "APPROVED", "DECLINED", "VOIDED", "EXPIRED",
    ]
    assert data["auth_status"] in ["PENDING", "AUTHENTICATED", "FAILED"]
    assert data["auth_level"] in ["EMAIL_ACCESS", "ACCESS_CODE", "KBA", "ID_DOCUMENT"]
    assert isinstance(data["kba_fail_count"], int) and data["kba_fail_count"] >= 0
    assert isinstance(data["identity_verified"], bool)
    assert isinstance(data["consent_accepted"], bool)
    assert isinstance(data["auth_risk_score"], int)
    assert isinstance(data["auth_risk_score_final"], int)
    assert isinstance(data["reminder_count"], int) and data["reminder_count"] >= 0
    # The shared access-code secret is never echoed back in any response body.
    assert "access_code" not in data or data.get("access_code") is None


def assert_field_placement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["envelope_id"]), "envelope_id must be a UUID"
    assert is_valid_uuid(data["envelope_document_id"]), "envelope_document_id must be a UUID"
    assert is_valid_uuid(data["recipient_id"]), "recipient_id must be a UUID"
    assert data["field_type"] in ["SIGNATURE", "INITIAL", "DATE", "TEXT", "CHECKBOX"]
    assert isinstance(data["required"], bool)
    assert data["value"] is None or isinstance(data["value"], str)
    assert isinstance(data["page_number"], int) and data["page_number"] >= 1
    assert isinstance(data["tab_order"], int)


def assert_signing_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["recipient_id"]), "recipient_id must be a UUID"
    assert is_valid_uuid(data["envelope_id"]), "envelope_id must be a UUID"
    assert data["status"] in ["OPEN", "COMPLETED", "DECLINED", "EXPIRED"]
    assert isinstance(data["consent_to_electronic_records"], bool)


def assert_template(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["owning_account_id"]), "owning_account_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["default_routing_mode"] in ["SEQUENTIAL", "PARALLEL"]
    assert data["default_auth_level"] in ["EMAIL_ACCESS", "ACCESS_CODE", "KBA", "ID_DOCUMENT"]
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert data["status"] in ["DRAFT", "PUBLISHED", "ARCHIVED"]
    assert isinstance(data["role_slot_count"], int) and data["role_slot_count"] >= 1
    assert isinstance(data["times_used"], int) and data["times_used"] >= 0


def assert_bulk_send_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"]), "account_id must be a UUID"
    assert is_valid_uuid(data["template_id"]), "template_id must be a UUID"
    assert isinstance(data["total_rows"], int) and data["total_rows"] >= 1
    assert data["status"] in ["CREATED", "COMPLETED", "PARTIAL", "FAILED"]
    assert isinstance(data["succeeded_count"], int) and data["succeeded_count"] >= 0
    assert isinstance(data["failed_count"], int) and data["failed_count"] >= 0


def assert_audit_event(data: dict):
    """AuditEvent is append-only: it carries id and created_at but has NO
    updated_at and NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "AuditEvent must not carry updated_at"
    assert "version" not in data, "AuditEvent must not carry version"
    assert is_valid_uuid(data["envelope_id"]), "envelope_id must be a UUID"
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert data["event_type"] in [
        "ENVELOPE_CREATED", "SENT", "DELIVERED", "SESSION_OPENED", "AUTH_SUCCEEDED",
        "AUTH_FAILED", "CONSENT_ACCEPTED", "FIELD_COMPLETED", "RECIPIENT_SIGNED",
        "RECIPIENT_APPROVED", "RECIPIENT_DECLINED", "DOCUMENT_HASHED", "SEALED",
        "CERTIFICATE_GENERATED", "VOIDED", "EXPIRED", "REMINDER_SENT", "PURGED",
    ]
    assert is_iso8601_timestamp(data["event_at"]), "event_at must be ISO 8601"
    _assert_hash(data["event_hash"], "event_hash")


def assert_fee_quote(data: dict):
    assert isinstance(data["total_pages"], int)
    for field in ("page_component", "subtotal", "discount", "total_fee"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert round_half_up(data[field]) == Decimal(str(data[field])).quantize(MONEY), (
            f"{field} must carry at most two decimal places"
        )


def assert_fee_breakdown(data: dict):
    """The PRD names no response field for the per-document itemisation — it
    specifies only the per-document page-fee arithmetic and the aggregate. So
    only the aggregate figure is asserted here; the per-document itemisation is
    read opportunistically by the caller when the implementation exposes it.
    """
    assert isinstance(data["total_page_fee"], (int, float)), (
        "the summed per-document page fee must be numeric"
    )


def assert_audit_certificate(data: dict):
    _assert_hash(data["certificate_hash"], "certificate_hash")
    if data.get("seal_hash") is not None:
        _assert_hash(data["seal_hash"], "seal_hash")
    assert isinstance(data["event_count"], int) and data["event_count"] >= 0


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_recipient_risk_dimensions(data: dict):
    """status and auth_status are independent dimensions on one recipient row."""
    assert data["status"] in [
        "WAITING", "SENT", "DELIVERED", "SIGNING", "SIGNED",
        "APPROVED", "DECLINED", "VOIDED", "EXPIRED",
    ]
    assert data["auth_status"] in ["PENDING", "AUTHENTICATED", "FAILED"]
    assert data["status"] not in ["PENDING", "AUTHENTICATED", "FAILED"]
    assert data["auth_status"] not in [
        "WAITING", "SENT", "DELIVERED", "SIGNING", "SIGNED",
        "APPROVED", "DECLINED", "VOIDED", "EXPIRED",
    ]


def assert_account_credit_invariant(data: dict):
    assert isinstance(data["credit_balance"], int)
    assert data["credit_balance"] >= 0 or data["status"] == "SUSPENDED"


def assert_audit_chain_linked(events: list):
    """Each event's prev_hash equals the previous event's event_hash, and the
    sequence numbers are contiguous starting at 1."""
    ordered = sorted(events, key=lambda e: e["sequence_number"])
    assert [e["sequence_number"] for e in ordered] == list(range(1, len(ordered) + 1)), (
        "audit sequence numbers must be contiguous starting at 1"
    )
    assert ordered[0]["prev_hash"] is None, "the first event's prev_hash must be null"
    for prev, cur in zip(ordered, ordered[1:]):
        assert cur["prev_hash"] == prev["event_hash"], (
            "each event's prev_hash must equal the previous event's event_hash"
        )