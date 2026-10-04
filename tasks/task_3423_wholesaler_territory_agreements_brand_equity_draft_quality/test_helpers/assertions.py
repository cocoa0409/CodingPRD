"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 instant, tolerating 'Z' and fractional digits."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_instant_equals(actual, expected_iso: str, label: str = "timestamp"):
    """Compare two clock instants semantically, not by string rendering.

    The PRD pins clock-derived instants (rofr_deadline, consummation_deadline,
    voided_at, amended_at, last_audit_at) to exact moments; an implementation
    may legitimately render them with or without fractional seconds.
    """
    assert actual is not None, f"{label} must be present, got None"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_territory(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in ("VACANT", "AWARDED")
    assert "incumbent_wholesaler_id" in data


def assert_wholesaler(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["tier"] in ("GOLD", "SILVER", "BRONZE")
    assert data["status"] in ("APPLICANT", "APPOINTED", "SUSPENDED", "TERMINATED")
    assert isinstance(data["suspended_account_count"], int)
    assert isinstance(data["supplier_book"], list)


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["territory_id"])
    assert is_valid_uuid(data["wholesaler_id"])
    assert isinstance(data["brand_scope"], list)
    assert data["weighting_profile"] in ("STANDARD", "SHARE_TILTED")
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert isinstance(data["amendment_log"], list)


def assert_transfer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["buyer_wholesaler_id"])
    assert data["status"] in (
        "SUBMITTED", "QUALIFIED", "ROFR_OPEN", "ROFR_EXERCISED", "ROFR_WAIVED",
        "ROFR_LAPSED", "APPROVED", "REJECTED", "CONSUMMATED", "EXPIRED",
    )


def assert_allocation_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["brand_code"], str) and data["brand_code"]
    assert isinstance(data["total_qty_cases"], int)
    assert data["status"] in ("OPEN", "LOCKED", "CLOSED")
    assert isinstance(data["requests"], list)
    assert isinstance(data["assignments"], list)


def assert_retail_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data["serving_wholesaler_id"])
    assert data["status"] in ("ACTIVE", "SERVICE_SUSPENDED")
    assert isinstance(data["line_cleaning_frequency_days"], int)


def assert_draft_audit(data: dict):
    """DraftAudit is immutable evidence: id + created_at only — no updated_at,
    no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an audit carries no updated_at"
    assert "version" not in data, "an audit carries no version"
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["stale_keg_count"], int)
    assert isinstance(data["critical_keg_flag"], bool)
    assert isinstance(data["line_cleaning_overdue"], bool)
    assert data["result"] in ("PASS", "FAIL", "CRITICAL_FAIL")


def assert_pos_grant(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["value_cents"], int)
    assert data["status"] in ("ISSUED", "VOIDED")
    assert isinstance(data["granted_year"], int)


def assert_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["wholesaler_id"])
    assert data["period_quarter"] in ("Q1", "Q2", "Q3", "Q4")
    assert data["weighting_profile_snapshot"] in ("STANDARD", "SHARE_TILTED")
    assert data["status"] in ("PUBLISHED", "ACKNOWLEDGED", "DISPUTED")


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["review_id"])
    assert data["status"] in ("PROPOSED", "ACTIVE", "VERIFIED", "FAILED")
    assert isinstance(data["revision_count"], int)


def assert_promotion(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["brand_code"], str) and data["brand_code"]
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["opt_ins"], list)


def assert_case_ledger_conserved(event: dict):
    """committed + pending + released + remainder == total_qty_cases."""
    total = (
        event["committed_qty"]
        + event["pending_qty"]
        + event["released_qty"]
        + event["unassigned_remainder"]
    )
    assert total == event["total_qty_cases"], (
        f"case ledger not conserved: {event['committed_qty']}+"
        f"{event['pending_qty']}+{event['released_qty']}+"
        f"{event['unassigned_remainder']} != {event['total_qty_cases']}"
    )


def get_assignment(event: dict, wholesaler_id: str) -> dict:
    for assignment in event["assignments"]:
        if assignment["wholesaler_id"] == wholesaler_id:
            return assignment
    raise AssertionError(
        f"no assignment for wholesaler {wholesaler_id} in event {event.get('id')}"
    )
