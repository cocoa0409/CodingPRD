"""Domain assertions: numeric precision, instant comparison, envelope shapes."""

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def validate_unpaginated(response: requests.Response, expected_status: int = 200) -> dict:
    """Validate a single-object success response and return its ``data`` payload.

    Used for the computed reads that return one object rather than a page, so no
    pagination fields are expected in ``meta``.
    """
    body = response.json()
    data = validate_success(response, expected_status)
    assert body["response_type"] == "object", (
        f"Expected response_type 'object', got '{body['response_type']}'"
    )
    assert isinstance(data, dict), f"Expected an object payload, got {type(data)}"
    return data


def assert_object_envelope(response: requests.Response, expected_status: int = 200) -> dict:
    """Assert the object envelope and return ``data``."""
    return validate_unpaginated(response, expected_status)


# ---------------------------------------------------------------------------
# Numeric precision
# ---------------------------------------------------------------------------
def _as_float(value: Any, field: str) -> float:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {value!r} ({type(value).__name__})"
    )
    return float(value)


def assert_decimals(value: Any, places: int, field: str = "value") -> float:
    """Assert a JSON number equals itself rounded to ``places`` decimal places."""
    number = _as_float(value, field)
    assert abs(number - round(number, places)) < 1e-9, (
        f"{field} must carry at most {places} decimal places, got {value!r}"
    )
    return number


def assert_amount(actual: Any, expected: float, field: str = "amount") -> None:
    """Assert a two-decimal tonnage / percentage / energy / money figure."""
    number = _as_float(actual, field)
    assert abs(number - expected) < 5e-3, f"{field}: expected {expected}, got {actual!r}"


def assert_oxide(actual: Any, expected: float, field: str = "oxide") -> None:
    """Assert a four-decimal oxide percentage."""
    number = _as_float(actual, field)
    assert abs(number - expected) < 5e-5, f"{field}: expected {expected}, got {actual!r}"


def assert_intensity(actual: Any, expected: float, field: str = "intensity") -> None:
    """Assert a three-decimal emission intensity."""
    number = _as_float(actual, field)
    assert abs(number - expected) < 5e-4, f"{field}: expected {expected}, got {actual!r}"


def assert_int(actual: Any, expected: int, field: str = "value") -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Timestamps — always canonicalised before comparison, never compared as strings
# ---------------------------------------------------------------------------
def canonical_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant into a timezone-aware UTC ``datetime``.

    Accepts a trailing ``Z`` as well as an explicit offset and any number of
    fractional digits, so two spellings of the same instant compare equal.
    """
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str, field: str = "timestamp") -> None:
    """Assert two ISO 8601 instants denote the same moment."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected instant {expected}, got {actual!r}"
    )


def assert_created_at_format(row: dict) -> None:
    """Assert ``created_at`` is an ISO 8601 UTC instant with three fractional digits."""
    created_at = row.get("created_at")
    assert isinstance(created_at, str), f"created_at must be a string, got {created_at!r}"
    assert is_iso8601_timestamp(created_at), f"created_at is not ISO 8601: {created_at!r}"
    assert_three_fractional_digits(created_at, "created_at")


def assert_three_fractional_digits(value: str, field: str = "timestamp") -> None:
    assert "." in value, f"{field} must carry three fractional digits, got {value!r}"
    fraction = value.split(".", 1)[1]
    digits = "".join(ch for ch in fraction if ch.isdigit())
    assert len(digits) == 3, (
        f"{field} must carry exactly three fractional digits, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Common field families
# ---------------------------------------------------------------------------
def assert_common_fields(row: dict, expected_version: Optional[int] = None) -> None:
    """Assert the id / created_at / updated_at / version family of a versioned row."""
    assert is_valid_uuid(row.get("id")), f"id must be a UUID with no prefix: {row.get('id')!r}"
    assert_created_at_format(row)
    assert isinstance(row.get("updated_at"), str), "updated_at must be present"
    assert_three_fractional_digits(row["updated_at"], "updated_at")
    assert isinstance(row.get("version"), int) and not isinstance(row.get("version"), bool), (
        f"version must be an integer, got {row.get('version')!r}"
    )
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"version: expected {expected_version}, got {row['version']}"
        )


def assert_immutable_row_fields(row: dict) -> None:
    """Assert the identity family of the one immutable resource: id and created_at only."""
    assert is_valid_uuid(row.get("id")), f"id must be a UUID: {row.get('id')!r}"
    assert_created_at_format(row)
    assert "updated_at" not in row, "an immutable row must not carry updated_at"
    assert "version" not in row, "an immutable row must not carry version"


def assert_fields_absent(row: dict, fields: Iterable[str]) -> None:
    for field in fields:
        assert field not in row, f"{field} must not be present on this row"


def assert_ordered_by_created_at(rows: list) -> None:
    """Assert rows are ordered by created_at ascending with id ascending as tie-break."""
    keys = [(canonical_instant(r["created_at"]), r["id"]) for r in rows]
    assert keys == sorted(keys), "rows must be ordered by created_at ASC then id ASC"
