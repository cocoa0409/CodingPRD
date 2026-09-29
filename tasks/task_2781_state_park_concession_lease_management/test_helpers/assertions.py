"""Domain assertions layered on the framework validators."""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── scalar comparisons ────────────────────────────────────────────────────

def as_decimal(value: Any) -> Decimal:
    """Normalize a percentage-shaped value (number or numeric string) to Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise AssertionError(f"expected a numeric percentage, got bool {value!r}")
    return Decimal(str(value))


def assert_pct_equals(actual: Any, expected: Any, field: str = "percentage") -> None:
    """Two-decimal percentage equality that tolerates number/string encodings."""
    assert actual is not None, f"{field} is missing"
    a, e = as_decimal(actual), as_decimal(expected)
    assert a == e, f"{field}: expected {e}, got {a} (raw {actual!r})"


def assert_cents_equals(actual: Any, expected: int, field: str = "amount") -> None:
    """Monetary equality; every money field is an integer count of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field}: expected an integer count of cents, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected} cents, got {actual}"


def assert_is_integer_cents(value: Any, field: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field}: expected an integer count of cents, got {value!r}"
    )


def assert_two_decimals_at_most(value: Any, field: str = "percentage") -> None:
    exponent = as_decimal(value).as_tuple().exponent
    assert isinstance(exponent, int) and exponent >= -2, (
        f"{field}: expected at most two decimal places, got {value!r}"
    )


# ─── common record shape (PRD §2.5) ────────────────────────────────────────

def assert_identity_fields(record: Dict[str, Any], versioned: bool = True) -> None:
    assert is_valid_uuid(record.get("id")), f"id is not a UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record.get("created_at")), (
        f"created_at is not ISO 8601: {record.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(record.get("updated_at")), (
            f"updated_at is not ISO 8601: {record.get('updated_at')!r}"
        )
        assert record.get("version") == 1 or isinstance(record.get("version"), int), (
            f"version must be an integer, got {record.get('version')!r}"
        )


def assert_freshly_created(record: Dict[str, Any]) -> None:
    """A brand-new versioned record: version 1 and updated_at == created_at."""
    assert_identity_fields(record)
    assert record["version"] == 1, f"new record version: expected 1, got {record['version']}"
    assert record["updated_at"] == record["created_at"], (
        "on creation updated_at must equal created_at: "
        f"{record['updated_at']!r} vs {record['created_at']!r}"
    )


def assert_version_is(record: Dict[str, Any], expected: int) -> None:
    assert record.get("version") == expected, (
        f"version: expected {expected}, got {record.get('version')!r}"
    )


def assert_append_only_record(record: Dict[str, Any]) -> None:
    """Score sheets carry id and created_at only — no updated_at, no version."""
    assert_identity_fields(record, versioned=False)
    assert "updated_at" not in record or record.get("updated_at") is None, (
        "an append-only record must not carry updated_at"
    )
    assert "version" not in record or record.get("version") is None, (
        "an append-only record must not carry version"
    )


# ─── status helpers ────────────────────────────────────────────────────────

def assert_status(record: Dict[str, Any], expected: str, field: str = "status") -> None:
    assert record.get(field) == str(expected), (
        f"{field}: expected {expected}, got {record.get(field)!r}"
    )


def assert_lease_state(
    lease: Dict[str, Any],
    contract_status: Optional[str] = None,
    compliance_status: Optional[str] = None,
) -> None:
    """The lease carries two independent status dimensions (PRD §2.10)."""
    if contract_status is not None:
        assert lease.get("contract_status") == str(contract_status), (
            f"contract_status: expected {contract_status}, got {lease.get('contract_status')!r}"
        )
    if compliance_status is not None:
        assert lease.get("compliance_status") == str(compliance_status), (
            f"compliance_status: expected {compliance_status}, "
            f"got {lease.get('compliance_status')!r}"
        )


def _as_instant(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 UTC instant, else None.

    PRD §2.8 declares `submission_deadline` and `cure_deadline` to be ISO 8601
    UTC timestamps but pins a fractional-second width only for `created_at` and
    `updated_at` (§2.5). Instants are therefore compared as instants, not as
    strings, so that ``...T00:00:00Z`` and ``...T00:00:00.000Z`` agree.
    """
    if not isinstance(value, str) or "T" not in value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def assert_fields(record: Dict[str, Any], expected: Dict[str, Any]) -> None:
    for key, value in expected.items():
        actual = record.get(key)
        if actual != value:
            expected_instant, actual_instant = _as_instant(value), _as_instant(actual)
            if (
                expected_instant is not None
                and actual_instant is not None
                and expected_instant == actual_instant
            ):
                continue
        assert actual == value, f"{key}: expected {value!r}, got {actual!r}"


def assert_null(record: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert record.get(field, None) is None, (
            f"{field}: expected null, got {record.get(field)!r}"
        )


# ─── collection helpers ────────────────────────────────────────────────────

def ids_of(rows: Sequence[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_contains_id(rows: Sequence[Dict[str, Any]], record_id: str) -> None:
    assert record_id in ids_of(rows), f"{record_id} missing from listing"


def assert_excludes_id(rows: Sequence[Dict[str, Any]], record_id: str) -> None:
    assert record_id not in ids_of(rows), f"{record_id} unexpectedly present in listing"


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not ordered by created_at ascending: {stamps}"


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if total_count is not None:
        assert meta.get("total_count") == total_count, (
            f"meta.total_count: expected {total_count}, got {meta.get('total_count')!r}"
        )
    if limit is not None:
        assert meta.get("limit") == limit, (
            f"meta.limit: expected {limit}, got {meta.get('limit')!r}"
        )
    if offset is not None:
        assert meta.get("offset") == offset, (
            f"meta.offset: expected {offset}, got {meta.get('offset')!r}"
        )
    if has_more is not None:
        assert meta.get("has_more") is has_more, (
            f"meta.has_more: expected {has_more}, got {meta.get('has_more')!r}"
        )


def error_id_of(response) -> str:
    """The machine-readable error_id from an error envelope (PRD §2.2)."""
    return response.json()["data"]["error_id"]
