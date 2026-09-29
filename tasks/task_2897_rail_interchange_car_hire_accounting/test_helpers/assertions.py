"""Assertion helpers layered on the framework validators."""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Reduce an ISO-8601 instant to a comparable canonical form.

    ``2026-08-24T00:00:00Z``, ``2026-08-24T00:00:00.000Z`` and
    ``2026-08-24T00:00:00.000000Z`` all denote the same instant, so sub-second
    padding and the UTC designator form must never decide a test.
    """
    if value is None:
        return None
    assert isinstance(value, str), f"expected an ISO-8601 string, got {value!r}"
    match = _INSTANT_RE.match(value.strip())
    assert match, f"not an ISO-8601 instant: {value!r}"
    year, month, day, hour, minute, second, frac, offset = match.groups()
    frac = (frac or "").rstrip("0").rstrip(".")
    micros = 0
    if frac:
        digits = (frac + "000000")[:6]
        micros = int(digits)
    if offset in ("Z", "+00:00", "+0000", "-00:00", "-0000"):
        shift_minutes = 0
    else:
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        shift_minutes = sign * (int(body[:2]) * 60 + int(body[2:]))
    total = int(hour) * 60 + int(minute) - shift_minutes
    # Instants in this API are always UTC-designated, so a non-zero offset is
    # only normalised inside the same day.
    hour_out, minute_out = divmod(total % (24 * 60), 60)
    base = f"{year}-{month}-{day}T{hour_out:02d}:{minute_out:02d}:{int(second):02d}"
    if micros:
        return f"{base}.{micros:06d}Z"
    return f"{base}Z"


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two instants ignoring sub-second padding."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_is_instant(value: Any, label: str = "instant") -> None:
    """The value is a present, well-formed ISO-8601 instant."""
    assert value is not None, f"{label} must not be null"
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _INSTANT_RE.match(value.strip()), f"{label} is not ISO-8601: {value!r}"


def assert_money(actual: Any, expected: int, label: str = "amount_cents") -> None:
    """A money field is an integer number of cents with the expected value."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a JSON integer number of cents, got {actual!r} "
        f"({type(actual).__name__})"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_money_field(row: Dict[str, Any], field: str, expected: int) -> None:
    """Shorthand for ``assert_money(row[field], expected, field)``."""
    assert field in row, f"missing money field {field!r} in {sorted(row)}"
    assert_money(row[field], expected, field)


def assert_hours(actual: Any, expected: float, label: str = "hours") -> None:
    """An hours field carries two decimal places and the expected value."""
    assert actual is not None, f"{label} must not be null"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert abs(float(actual) - expected) < 0.005, (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_pct(actual: Any, expected: float, label: str = "pct") -> None:
    """A percentage field carries two decimal places and the expected value."""
    assert actual is not None, f"{label} must not be null"
    assert abs(float(actual) - expected) < 0.005, (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_error_envelope(response, expected_error_id: str, expected_status: int) -> Dict[str, Any]:
    """Full error-envelope check: status, response_type, and exactly two keys.

    Every failure carries ``response_type`` ``"error"``, a ``data`` object
    holding exactly ``error_id`` and ``message``, and a ``meta`` block with a
    fresh ``api_request_id``; no resource field may leak into ``data``.

    Returns the ``data`` object itself, so a caller may go on to assert on the
    ``error_id`` it holds without unwrapping the envelope a second time.
    """
    assert response.status_code == expected_status, (
        f"expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    data = body.get("data")
    assert isinstance(data, dict), f"error data must be an object, got {data!r}"
    assert set(data.keys()) == {"error_id", "message"}, (
        f"error data keys must be exactly error_id and message, got {sorted(data)}"
    )
    assert data["error_id"] == expected_error_id, (
        f"expected {expected_error_id}, got {data['error_id']}"
    )
    assert isinstance(data["message"], str) and data["message"].strip(), (
        "error message must be a non-empty string"
    )
    meta = body.get("meta")
    assert isinstance(meta, dict), f"meta must be an object, got {meta!r}"
    assert meta.get("api_request_id"), "meta.api_request_id must be present"
    assert meta.get("api_request_timestamp"), "meta.api_request_timestamp must be present"
    return data


def request_id_of(response) -> str:
    """The ``meta.api_request_id`` of any envelope."""
    meta = response.json().get("meta") or {}
    request_id = meta.get("api_request_id")
    assert request_id, "meta.api_request_id must be present"
    return request_id


def assert_no_common_update_fields(row: Dict[str, Any], label: str = "row") -> None:
    """A row declared without the common-field block has no version/updated_at."""
    assert "id" in row, f"{label} must expose id"
    assert "created_at" in row, f"{label} must expose created_at"
    assert "version" not in row, f"{label} must not expose version, got {row.get('version')!r}"
    assert "updated_at" not in row, (
        f"{label} must not expose updated_at, got {row.get('updated_at')!r}"
    )


def assert_versioned_row(row: Dict[str, Any], expected_version: Optional[int] = None,
                         label: str = "row") -> None:
    """A versioned row exposes the whole common-field block."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in row, f"{label} must expose {field}"
    assert is_valid_uuid(row["id"]), f"{label}.id must be a UUID, got {row['id']!r}"
    assert isinstance(row["version"], int), f"{label}.version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"{label}.version: expected {expected_version}, got {row['version']}"
        )


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    """The ``id`` of every row, in order."""
    return [row["id"] for row in rows]


def assert_distinct(values: Sequence[Any], label: str = "values") -> None:
    """Every value in the sequence is pairwise distinct."""
    assert len(set(values)) == len(values), f"{label} must be pairwise distinct: {values}"


def strip_volatile(body: Dict[str, Any]) -> Tuple[Any, Any]:
    """A comparable projection of an envelope, ignoring the per-request meta."""
    meta = dict(body.get("meta") or {})
    meta.pop("api_request_id", None)
    meta.pop("api_request_timestamp", None)
    return body.get("data"), meta


__all__ = [
    "assert_at_least_one_succeeds",
    "assert_cost_precision",
    "assert_distinct",
    "assert_error_envelope",
    "assert_exactly_one_succeeds",
    "assert_hours",
    "assert_instant_equals",
    "assert_is_instant",
    "assert_money",
    "assert_money_field",
    "assert_no_common_update_fields",
    "assert_pct",
    "assert_race_outcome",
    "assert_timestamp_format",
    "assert_version_incremented",
    "assert_versioned_row",
    "canonical_instant",
    "get_success_data",
    "ids_of",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "request_id_of",
    "run_race",
    "strip_volatile",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
]
