"""Domain assertions for the CCR contract's field shapes and derived values.

These wrap the numeric and temporal conventions the contract fixes in §2.4 and
§2.6 so that a test reads as a statement about the regulation rather than a
statement about float comparison.
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── Temporal shapes ───────────────────────────────────────────────────────


def assert_instant_format(value: Any, label: str = "instant") -> None:
    """An ISO 8601 UTC instant, as §2.4 requires of created_at and updated_at."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not an ISO 8601 UTC instant: {value!r}"


def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two instants on their canonical form, not their spelling."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected instant {expected!r}, got {actual!r}"
    )


def assert_date(actual: Any, expected: Optional[str], label: str = "date") -> None:
    """A plain calendar date in YYYY-MM-DD form, or null when expected is None."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert ISO_DATE_RE.match(actual), f"{label} is not a YYYY-MM-DD date: {actual!r}"
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"


def assert_date_format(value: Any, label: str = "date") -> None:
    """Only the shape, for a date whose value the test does not pin."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert ISO_DATE_RE.match(value), f"{label} is not a YYYY-MM-DD date: {value!r}"


# ── Numeric shapes ────────────────────────────────────────────────────────


def assert_cents(actual: Any, expected: Optional[int], label: str = "amount") -> None:
    """Money is an integer count of cents - never a string, never a decimal."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r} ({type(actual).__name__})"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_tons(actual: Any, expected: int, label: str = "tons") -> None:
    """Tonnage is whole-ton integer arithmetic with no rounding anywhere."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of tons, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} tons, got {actual}"


def assert_quantity(actual: Any, expected: float, places: int, label: str = "quantity") -> None:
    """A decimal quantity carried to a fixed number of places.

    The value must arrive as a JSON number, not a string, and must agree with
    the expected figure at the field's declared precision.
    """
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {actual!r} ({type(actual).__name__})"
    )
    tolerance = 0.5 * (10 ** -places)
    assert abs(float(actual) - float(expected)) < tolerance, (
        f"{label}: expected {expected:.{places}f}, got {actual!r}"
    )


def assert_two_dp(actual: Any, expected: float, label: str = "value") -> None:
    """A percentage, distance, depth or settlement figure: 2 decimal places."""
    assert_quantity(actual, expected, 2, label)


def assert_three_dp(actual: Any, expected: float, label: str = "value") -> None:
    """A seismic peak ground acceleration: 3 decimal places."""
    assert_quantity(actual, expected, 3, label)


def assert_four_dp(actual: Any, expected: float, label: str = "value") -> None:
    """An analytical value, background mean or prediction limit: 4 places."""
    assert_quantity(actual, expected, 4, label)


def assert_six_dp(actual: Any, expected: float, label: str = "value") -> None:
    """A reported background standard deviation: 6 decimal places."""
    assert_quantity(actual, expected, 6, label)


# ── Identity, mutation counters and append-only records ───────────────────


def assert_identity_fields(entity: Dict[str, Any], label: str = "resource") -> None:
    """Every resource carries a server-minted UUID id and a created_at instant."""
    assert "id" in entity, f"{label} has no id"
    assert is_valid_uuid(entity["id"]), f"{label} id is not a bare UUID: {entity['id']!r}"
    assert_instant_format(entity.get("created_at"), f"{label}.created_at")


def assert_versioned(entity: Dict[str, Any], expected_version: int, label: str = "resource") -> None:
    """A mutable resource carries updated_at and a version at the given count."""
    assert_identity_fields(entity, label)
    assert_instant_format(entity.get("updated_at"), f"{label}.updated_at")
    assert entity.get("version") == expected_version, (
        f"{label}.version: expected {expected_version}, got {entity.get('version')!r}"
    )


def assert_append_only(entity: Dict[str, Any], label: str = "record") -> None:
    """An append-only certification record carries no mutation counter at all.

    §2.4 requires updated_at and version to be *absent* from the representation
    rather than present and null, so their mere presence is a failure.
    """
    assert_identity_fields(entity, label)
    assert "updated_at" not in entity, f"{label} must not carry updated_at: {entity.get('updated_at')!r}"
    assert "version" not in entity, f"{label} must not carry version: {entity.get('version')!r}"


# ── Envelope and list shapes ──────────────────────────────────────────────


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Every response's meta carries a req_-prefixed id and a UTC instant."""
    meta = body.get("meta")
    assert isinstance(meta, dict), f"meta must be an object, got {meta!r}"
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id must start with 'req_', got {request_id!r}"
    )
    assert_instant_format(meta.get("api_request_timestamp"), "api_request_timestamp")


def assert_page_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """A list response echoes the effective window and the pre-window total."""
    assert meta.get("limit") == limit, f"meta.limit: expected {limit}, got {meta.get('limit')!r}"
    assert meta.get("offset") == offset, f"meta.offset: expected {offset}, got {meta.get('offset')!r}"
    assert meta.get("total_count") == total_count, (
        f"meta.total_count: expected {total_count}, got {meta.get('total_count')!r}"
    )
    assert meta.get("has_more") is has_more, (
        f"meta.has_more: expected {has_more}, got {meta.get('has_more')!r}"
    )


def assert_ids(rows: Sequence[Dict[str, Any]], expected_ids: Iterable[str], label: str = "page") -> None:
    """The page holds exactly these identifiers, in this order."""
    actual = [row["id"] for row in rows]
    expected = list(expected_ids)
    assert actual == expected, f"{label}: expected ids {expected}, got {actual}"


def assert_string_list(actual: Any, expected: List[str], label: str = "list") -> None:
    """An ordered list of enumerated strings, compared position by position."""
    assert isinstance(actual, list), f"{label} must be a list, got {actual!r}"
    assert actual == expected, f"{label}: expected {expected}, got {actual}"
