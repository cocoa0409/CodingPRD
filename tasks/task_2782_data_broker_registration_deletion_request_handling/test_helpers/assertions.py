"""Entity assertions, timestamp/number canonicalisation and domain invariants."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import COMPLETION_BREACH_THRESHOLD

# ---------------------------------------------------------------------------
# Instant canonicalisation
#
# The PRD renders every timestamp as ISO 8601 UTC with exactly three fractional
# digits. Expected values written in tests are often quoted at second precision,
# so both sides are canonicalised before comparison instead of compared as raw
# strings.
# ---------------------------------------------------------------------------


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to `YYYY-MM-DDTHH:MM:SS.mmmZ`."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif "+" in text[10:]:
        text = text[: text.rindex("+")]
    if "." in text:
        base, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        base, frac = text, "000"
    return f"{base}.{frac}Z"


def parse_instant(value: str) -> datetime:
    canonical = canonical_instant(value)
    return datetime.strptime(canonical, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )


def format_instant(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def days_after(instant: str, days: int) -> str:
    """The instant `days` whole days later, in canonical form."""
    return format_instant(parse_instant(instant) + timedelta(days=days))


def days_before(instant: str, days: int) -> str:
    return format_instant(parse_instant(instant) - timedelta(days=days))


def assert_instant_equals(actual, expected, label="timestamp"):
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} {expected!r}, got {actual!r}"
    )


def assert_instant_shape(value, label="timestamp"):
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC timestamp, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Numeric comparison
# ---------------------------------------------------------------------------


def _as_decimal(value) -> Decimal:
    assert value is not None, "expected a number, got None"
    return Decimal(str(value))


def assert_decimal_equals(actual, expected, label="value"):
    assert _as_decimal(actual) == _as_decimal(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_score_equals(actual, expected, label="score"):
    """Two-decimal score comparison (0.00..100.00 fields)."""
    assert_decimal_equals(actual, expected, label)
    assert _as_decimal(actual).as_tuple().exponent >= -2, (
        f"{label} must carry at most two decimal places, got {actual}"
    )


def assert_ratio_equals(actual, expected, label="completion_ratio"):
    """Four-decimal ratio comparison."""
    assert_decimal_equals(actual, expected, label)
    assert _as_decimal(actual).as_tuple().exponent >= -4, (
        f"{label} must carry at most four decimal places, got {actual}"
    )


def assert_cents_equals(actual, expected, label="cents"):
    """Money is always a whole number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a whole number of cents, got {actual!r}"
    )
    assert actual == expected, f"Expected {label} {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Common-field shape
# ---------------------------------------------------------------------------


def assert_versioned_entity(data: dict, label="entity"):
    """Shape shared by every versioned entity: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert_instant_shape(data.get("created_at"), f"{label}.created_at")
    assert_instant_shape(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_append_only_entity(data: dict, label="entity"):
    """Shape shared by the append-only families: only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert_instant_shape(data.get("created_at"), f"{label}.created_at")


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_broker(data: dict):
    assert_versioned_entity(data, "broker")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert "@" in data["primary_contact_email"]
    assert len(data["home_state_code"]) == 2
    assert isinstance(data["operating_state_codes"], list)
    assert data["operating_state_codes"], "operating_state_codes must be non-empty"
    assert data["registry_standing"] in ("COMPLIANT", "DELINQUENT", "SUSPENDED")
    for counter in (
        "fee_deposited_cents",
        "fee_paid_cents",
        "fee_credit_cents",
        "open_breach_count",
        "request_intake_total",
        "request_open_count",
        "request_completed_count",
        "request_terminated_count",
        "audit_sequence_high_water",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"broker.{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert_broker_ledger_conserved(data)
    assert_broker_request_counters_conserved(data)


def assert_broker_ledger_conserved(data: dict):
    """fee_deposited_cents == fee_paid_cents + fee_credit_cents."""
    assert (
        data["fee_deposited_cents"]
        == data["fee_paid_cents"] + data["fee_credit_cents"]
    ), (
        "Fee ledger must reconcile: "
        f"{data['fee_deposited_cents']} != {data['fee_paid_cents']} + "
        f"{data['fee_credit_cents']}"
    )


def assert_broker_request_counters_conserved(data: dict):
    """request_intake_total == open + completed + terminated."""
    assert data["request_intake_total"] == (
        data["request_open_count"]
        + data["request_completed_count"]
        + data["request_terminated_count"]
    ), (
        "Request counters must reconcile: "
        f"{data['request_intake_total']} != {data['request_open_count']} + "
        f"{data['request_completed_count']} + {data['request_terminated_count']}"
    )


def assert_registration(data: dict):
    assert_versioned_entity(data, "registration")
    assert is_valid_uuid(data["broker_id"]), "registration.broker_id must be a UUID"
    assert len(data["state_code"]) == 2
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "ACCEPTED",
        "REJECTED",
        "WITHDRAWN",
        "EXPIRED",
    )
    assert_instant_shape(data["coverage_period_start"], "coverage_period_start")
    assert_instant_shape(data["coverage_period_end"], "coverage_period_end")
    assert isinstance(data["coverage_days"], int) and data["coverage_days"] >= 0
    assert isinstance(data["provisional_filing_fee_cents"], int)
    assert isinstance(data["charged_fee_cents"], int)
    assert _as_decimal(data["disclosure_completeness_score"]) >= 0


def assert_disclosure_item(data: dict):
    assert_append_only_entity(data, "disclosure_item")
    assert "updated_at" not in data, "disclosure items are append only"
    assert "version" not in data, "disclosure items are append only"
    assert data["category"] in (
        "SOURCES",
        "RECIPIENTS",
        "RETENTION",
        "SENSITIVE_CATEGORIES",
        "OPT_OUT_MECHANISM",
        "MINORS_DATA",
    )
    assert isinstance(data["content"], str) and data["content"]
    assert data["content_length"] == len(data["content"])


def assert_consumer(data: dict):
    assert_versioned_entity(data, "consumer")
    assert is_valid_uuid(data["broker_id"]), "consumer.broker_id must be a UUID"
    assert len(data["state_code"]) == 2
    assert data["collection_status"] in (
        "ACTIVE",
        "PURGE_PENDING",
        "PURGED",
        "REACQUIRED",
    )
    assert data["consent_status"] in (
        "NOT_REQUIRED",
        "CONSENT_PENDING",
        "CONSENT_GRANTED",
        "CONSENT_REVOKED",
    )
    assert isinstance(data["collection_event_count"], int)
    assert data["collection_event_count"] >= 1
    assert isinstance(data["opt_out_sale"], bool)
    assert isinstance(data["opt_out_sharing"], bool)


def assert_deletion_request(data: dict):
    assert_versioned_entity(data, "deletion_request")
    assert is_valid_uuid(data["broker_id"])
    assert is_valid_uuid(data["consumer_id"])
    assert data["intake_channel"] in (
        "DIRECT_PORTAL",
        "STATE_PLATFORM",
        "AUTHORIZED_AGENT",
        "EMAIL",
    )
    assert data["requested_scope"] in ("DELETE_ALL", "DELETE_SENSITIVE_ONLY")
    assert data["status"] in (
        "RECEIVED",
        "VERIFICATION_PENDING",
        "VERIFIED",
        "VERIFICATION_FAILED",
        "EXECUTING",
        "COMPLETED",
        "PARTIALLY_COMPLETED",
        "DENIED",
        "WITHDRAWN",
        "SUPERSEDED",
    )
    assert isinstance(data["compliance_breach"], bool)
    assert_propagation_counters_conserved(data)


def assert_propagation_counters_conserved(data: dict):
    """propagation_required_count == acked + waived + abandoned + outstanding."""
    assert data["propagation_required_count"] == (
        data["acked_task_count"]
        + data["waived_task_count"]
        + data["abandoned_task_count"]
        + data["outstanding_task_count"]
    ), (
        "Propagation counters must reconcile: "
        f"{data['propagation_required_count']} != {data['acked_task_count']} + "
        f"{data['waived_task_count']} + {data['abandoned_task_count']} + "
        f"{data['outstanding_task_count']}"
    )


def assert_verification_attempt(data: dict):
    assert_append_only_entity(data, "verification_attempt")
    assert "updated_at" not in data, "verification attempts are append only"
    assert "version" not in data, "verification attempts are append only"
    assert data["method"] in (
        "GOVT_ID",
        "TWO_DATA_POINTS",
        "PLATFORM_ASSERTION",
        "AGENT_LOA",
    )
    assert data["variant_applied"] in ("FRAUD_WEIGHTED", "PLATFORM_ASSERTED")
    assert data["outcome"] in ("PASS", "INCONCLUSIVE", "FAIL")
    assert Decimal("0") <= _as_decimal(data["assurance_score"]) <= Decimal("100")


def assert_downstream_recipient(data: dict):
    assert_versioned_entity(data, "downstream_recipient")
    assert is_valid_uuid(data["broker_id"])
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["contract_propagation_required"], bool)
    assert 1 <= data["ack_sla_days"] <= 90
    assert Decimal("0") <= _as_decimal(data["reliability_score"]) <= Decimal("100")


def assert_propagation_task(data: dict):
    assert_versioned_entity(data, "propagation_task")
    assert is_valid_uuid(data["deletion_request_id"])
    assert data["target_kind"] in (
        "ACTIVE_DATABASE",
        "BACKUP_ARCHIVE",
        "DERIVED_DATASET",
        "DOWNSTREAM_RECIPIENT",
    )
    assert data["status"] in (
        "PENDING",
        "DISPATCHED",
        "DEFERRED",
        "FAILED",
        "ACKED",
        "WAIVED",
        "ABANDONED",
    )
    assert isinstance(data["weight"], int) and data["weight"] > 0
    assert isinstance(data["sla_days"], int) and data["sla_days"] > 0
    assert_instant_shape(data["due_at"], "propagation_task.due_at")


def assert_suppression_entry(data: dict):
    assert_versioned_entity(data, "suppression_entry")
    assert is_valid_uuid(data["broker_id"])
    assert is_valid_uuid(data["consumer_id"])
    assert data["source_scope"] in ("ALL_SOURCES", "SINGLE_SOURCE")
    assert data["status"] in ("ACTIVE", "LIFTED", "EXPIRED")
    assert_instant_shape(data["window_start"], "window_start")
    assert_instant_shape(data["window_end"], "window_end")
    assert parse_instant(data["window_start"]) <= parse_instant(data["window_end"])
    assert isinstance(data["blocked_recollection_count"], int)


def assert_opt_out_signal(data: dict):
    assert_versioned_entity(data, "opt_out_signal")
    assert is_valid_uuid(data["broker_id"])
    assert is_valid_uuid(data["consumer_id"])
    assert data["signal_type"] in (
        "GPC_BROWSER",
        "PLATFORM_BULK",
        "WRITTEN_REQUEST",
        "AGENT_SUBMITTED",
    )
    assert data["scope"] in ("SALE", "SHARING", "SALE_AND_SHARING")
    assert data["status"] in ("RECEIVED", "HONORED", "SUPERSEDED")
    assert_instant_shape(data["honor_deadline_at"], "honor_deadline_at")


def assert_regulator_inquiry(data: dict):
    assert_versioned_entity(data, "regulator_inquiry")
    assert is_valid_uuid(data["broker_id"])
    assert data["status"] in ("OPEN", "RESPONDED", "CLOSED", "ESCALATED")
    assert data["adequacy_verdict"] in ("UNRATED", "ADEQUATE", "DEFICIENT")
    assert isinstance(data["cited_audit_event_ids"], list)
    assert data["cited_event_count"] == len(data["cited_audit_event_ids"])
    assert isinstance(data["coverage_bonus_applied"], bool)


def assert_audit_event(data: dict):
    assert_append_only_entity(data, "audit_event")
    assert "updated_at" not in data, "audit events are append only"
    assert "version" not in data, "audit events are append only"
    assert is_valid_uuid(data["broker_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert isinstance(data["subject_kind"], str) and data["subject_kind"]
    assert_instant_shape(data["retention_expires_at"], "retention_expires_at")


def assert_audit_trail_sequenced(events: list):
    """The trail is ordered by ascending sequence_no starting at 1."""
    numbers = [event["sequence_no"] for event in events]
    assert numbers == sorted(numbers), (
        f"Audit trail must be ordered by ascending sequence_no, got {numbers}"
    )


def assert_breach_consistent(data: dict):
    """compliance_breach is only true once nothing is outstanding and the
    weighted coverage landed below the breach threshold."""
    if data["compliance_breach"]:
        assert data["outstanding_task_count"] == 0, (
            "a breach can only be declared once no task is outstanding"
        )
        assert _as_decimal(data["completion_ratio"]) < Decimal(
            str(COMPLETION_BREACH_THRESHOLD)
        ), (
            "compliance_breach is true but completion_ratio "
            f"{data['completion_ratio']} is not below {COMPLETION_BREACH_THRESHOLD}"
        )
