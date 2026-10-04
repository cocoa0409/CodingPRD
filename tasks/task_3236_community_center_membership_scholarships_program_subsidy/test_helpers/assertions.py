"""Domain assertions for the Community Center Membership API.

These wrap the shared structural helpers with the vocabulary of this PRD: money
amounts compare as integer cents, award fractions compare as exact declared
steps, and the common entity shapes are checked once here instead of in every
test.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ── Instants ───────────────────────────────────────────────────────────────

def assert_instant_format(value: str, label: str = "instant") -> None:
    """Assert a value is an ISO 8601 UTC instant in the rendering the PRD uses."""
    assert is_iso8601_timestamp(value), f"{label}: not an ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"{label}: must be rendered in UTC with a Z suffix: {value!r}"


# ── Numbers ────────────────────────────────────────────────────────────────

def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money amount, which the PRD carries as an integer number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_fraction(actual: Any, expected: float, label: str = "fraction") -> None:
    """Assert an award fraction or match tier, which the PRD fixes to declared steps."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert abs(float(actual) - float(expected)) < 1e-9, (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_ratio(actual: Any, expected: float, label: str = "income_ratio") -> None:
    """Assert a four-decimal-place ratio at the precision the PRD rounds to."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert round(float(actual), 4) == round(float(expected), 4), (
        f"{label}: expected {expected} at 4 decimal places, got {actual}"
    )


# ── Envelope and common fields ─────────────────────────────────────────────

def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Assert the meta block carries a prefixed request id and a UTC instant."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta["api_request_timestamp"], "meta.api_request_timestamp")


def assert_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert the full identity quartet every resource in this PRD carries."""
    assert is_valid_uuid(data.get("id")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_instant_format(data["created_at"], f"{label}.created_at")
    assert_instant_format(data["updated_at"], f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


# ── Listing envelope ───────────────────────────────────────────────────────

def assert_list_page(meta: Dict[str, Any], limit: int, offset: int, total: int, has_more: bool) -> None:
    """Assert a list response reports the page it served and the size of the collection."""
    assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset: expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total, (
        f"meta.total_count: expected {total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more: expected {has_more}, got {meta['has_more']}"
    )


# ── Domain shapes ──────────────────────────────────────────────────────────

MEMBERSHIP_STATUSES = ("ACTIVE", "ON_HOLD", "LAPSED", "CANCELLED")
DRAFT_STATUSES = ("CURRENT", "RETRY_PENDING", "DELINQUENT")
DRAFT_KINDS = ("REGULAR", "JOINING_FEE", "HOLD_FEE")
DRAFT_ROW_STATUSES = ("PENDING", "PAID", "FAILED")
APPLICATION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUIRED", "APPROVED", "DENIED", "EXPIRED")
SESSION_STATUSES = ("SCHEDULED", "REG_OPEN", "REG_CLOSED", "COMPLETED", "CANCELLED")
REGISTRATION_STATUSES = ("REGISTERED", "WAITLISTED", "CANCELLED", "REFUNDED", "EXPIRED")
REGISTRANT_CLASSES = ("HOME_MEMBER", "ASSOCIATION_MEMBER", "RECIPROCITY_VISITOR", "NON_MEMBER")
RESERVATION_STATUSES = ("REQUESTED", "APPROVED", "DENIED", "CANCELLED", "COMPLETED")
CAMPAIGN_STATUSES = ("DRAFT", "ACTIVE", "CLOSED")
DONATION_STATUSES = ("PLEDGED", "RECEIVED", "REFUNDED")


def assert_membership(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "membership")
    assert data["status"] in MEMBERSHIP_STATUSES, f"membership.status: {data['status']!r}"
    assert data["draft_status"] in DRAFT_STATUSES, f"membership.draft_status: {data['draft_status']!r}"
    assert data["lifetime_billed_cents"] >= 0, "lifetime_billed_cents must not be negative"


def assert_branch_pool_invariants(branch: Dict[str, Any]) -> None:
    """The scholarship-pool conservation law on a Branch record."""
    received = branch["scholarship_pool_received_cents"]
    obligated = branch["scholarship_pool_obligated_cents"]
    available = branch["scholarship_pool_available_cents"]
    assert available == received - obligated, (
        f"pool_available {available} != received {received} - obligated {obligated}"
    )
    assert available >= 0, "scholarship_pool_available_cents is never allowed to go negative"


def assert_draft(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "draft")
    assert data["kind"] in DRAFT_KINDS, f"draft.kind: {data['kind']!r}"
    assert data["status"] in DRAFT_ROW_STATUSES, f"draft.status: {data['status']!r}"
    assert isinstance(data["amount_cents"], int), "draft.amount_cents must be integer cents"
