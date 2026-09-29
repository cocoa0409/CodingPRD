"""Domain assertions layered on top of the framework validators.

The instant helpers exist because §2.4 pins one width — "an ISO-8601 UTC
timestamp with exactly three fractional digits" — while §2.5's clock endpoint
"echoes back the instant it was given". Comparing raw strings would therefore
fail on sub-second width alone, so every instant comparison in the suite goes
through :func:`canonical_instant`.
"""

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import Resource

_THREE_FRACTIONAL_DIGITS = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Instants and dates
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse any ISO-8601 UTC instant the API may emit into a datetime."""
    assert isinstance(value, str), f"Expected an instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_instant(value: str) -> str:
    """Normalise an instant to millisecond precision UTC for comparison."""
    parsed = parse_instant(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


def instants_equal(left: str, right: str) -> bool:
    return canonical_instant(left) == canonical_instant(right)


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    assert instants_equal(actual, expected), (
        f"{label}: expected {canonical_instant(expected)}, "
        f"got {canonical_instant(actual)}"
    )


def assert_created_at_format(value: str) -> None:
    """§2.4: `created_at` is an ISO-8601 UTC instant with three fractional digits."""
    assert isinstance(value, str), f"created_at must be a string, got {value!r}"
    assert _THREE_FRACTIONAL_DIGITS.match(value), (
        f"created_at must be an ISO-8601 UTC instant with exactly three "
        f"fractional digits, got {value!r}"
    )


def assert_date_only(value: str, label: str = "date") -> None:
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _DATE_ONLY.match(value), (
        f"{label} must be a calendar date in YYYY-MM-DD form, got {value!r}"
    )


def iso_date(value: str) -> date:
    assert_date_only(value)
    return date.fromisoformat(value)


def plus_days(value: str, days: int) -> str:
    """Return the calendar date `days` after the given date, as YYYY-MM-DD."""
    return (iso_date(value) + timedelta(days=days)).isoformat()


def instant_at(day: str, time_part: str = "00:00:00") -> str:
    """Compose a full ISO-8601 instant from a calendar date and a wall time."""
    assert_date_only(day)
    return f"{day}T{time_part}Z"


def plus_minutes(instant: str, minutes: int) -> str:
    """Return the instant `minutes` after the given instant, in Z form."""
    moved = parse_instant(instant) + timedelta(minutes=minutes)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Envelope and common-field assertions
# ---------------------------------------------------------------------------
def assert_meta_envelope(body: Dict[str, Any]) -> None:
    """§2.2: `api_request_id` starts with `req_`; the timestamp has 3 digits."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert _THREE_FRACTIONAL_DIGITS.match(meta["api_request_timestamp"]), (
        "api_request_timestamp must be an ISO 8601 UTC timestamp with three "
        f"fractional digits, got {meta['api_request_timestamp']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def assert_identity_fields(resource: Resource) -> None:
    """§2.4: a server-minted UUID `id` plus a three-digit-precision `created_at`."""
    assert is_valid_uuid(resource["id"]), (
        f"id must be a server-minted UUID, got {resource['id']!r}"
    )
    assert_created_at_format(resource["created_at"])


def assert_versioned_entity(resource: Resource, expected_version: Optional[int] = None) -> None:
    """§2.4: every entity but the tariff carries `updated_at` and `version`."""
    assert_identity_fields(resource)
    assert_created_at_format(resource["updated_at"])
    assert isinstance(resource["version"], int), "version must be an integer"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_no_version_fields(resource: Resource) -> None:
    """§2.4 exempts the tariff, which "carries only `id` and `created_at`"."""
    assert "version" not in resource, "UtilityTariff must not carry a version"
    assert "updated_at" not in resource, "UtilityTariff must not carry updated_at"


def assert_fields_absent(resource: Resource, field_names: Iterable[str]) -> None:
    for name in field_names:
        assert name not in resource, f"{name} must not be echoed back on the resource"


def assert_ids_in_order(items: Iterable[Resource], expected_ids: Iterable[str]) -> None:
    actual = [item["id"] for item in items]
    expected = list(expected_ids)
    assert actual == expected, f"expected ids in order {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Ledger and monitoring invariants (§2.9)
# ---------------------------------------------------------------------------
def assert_credit_identity(agreement: Resource) -> None:
    """§2.9: the balance is earned minus applied and "is never negative"."""
    earned = agreement["credit_earned_cents"]
    applied = agreement["credit_applied_cents"]
    balance = agreement["credit_balance_cents"]
    assert balance == earned - applied, (
        f"credit_balance_cents must equal credit_earned_cents minus "
        f"credit_applied_cents: {balance} != {earned} - {applied}"
    )
    assert balance >= 0, f"credit_balance_cents must never be negative, got {balance}"


def assert_credit_counters(
    agreement: Resource, earned: int, applied: int, balance: int
) -> None:
    assert agreement["credit_earned_cents"] == earned, (
        f"credit_earned_cents: expected {earned}, "
        f"got {agreement['credit_earned_cents']}"
    )
    assert agreement["credit_applied_cents"] == applied, (
        f"credit_applied_cents: expected {applied}, "
        f"got {agreement['credit_applied_cents']}"
    )
    assert agreement["credit_balance_cents"] == balance, (
        f"credit_balance_cents: expected {balance}, "
        f"got {agreement['credit_balance_cents']}"
    )
    assert_credit_identity(agreement)


def assert_monitoring_counters(
    agreement: Resource, open_count: int, excused_minutes: int
) -> None:
    assert agreement["open_outage_count"] == open_count, (
        f"open_outage_count: expected {open_count}, "
        f"got {agreement['open_outage_count']}"
    )
    assert agreement["excused_downtime_minutes"] == excused_minutes, (
        f"excused_downtime_minutes: expected {excused_minutes}, "
        f"got {agreement['excused_downtime_minutes']}"
    )


def assert_state_dimensions(
    agreement: Resource,
    lifecycle_state: Optional[str] = None,
    monitoring_status: Optional[str] = None,
    service_status: Optional[str] = None,
) -> None:
    """§2.8: the three dimensions are independent and asserted independently."""
    if lifecycle_state is not None:
        assert agreement["lifecycle_state"] == lifecycle_state, (
            f"lifecycle_state: expected {lifecycle_state}, "
            f"got {agreement['lifecycle_state']}"
        )
    if monitoring_status is not None:
        assert agreement["monitoring_status"] == monitoring_status, (
            f"monitoring_status: expected {monitoring_status}, "
            f"got {agreement['monitoring_status']}"
        )
    if service_status is not None:
        assert agreement["service_status"] == service_status, (
            f"service_status: expected {service_status}, "
            f"got {agreement['service_status']}"
        )
