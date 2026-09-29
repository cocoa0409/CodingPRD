"""Domain assertion helpers.

Timestamps are never compared as raw strings. PRD 2.4 fixes the *stored*
format at ISO 8601 UTC with exactly three fractional digits and a trailing
`Z`, while the instants a test supplies in a request body (and the instants
quoted in the PRD's own worked examples) are written without the fractional
part. `canonical_instant` parses both onto the same point in time so a
comparison tests the instant, not its spelling; `assert_instant_equals` is
what tests should use everywhere.
"""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Tuple

import requests

from prd_bench_local_runner.testing import validate_success

# PRD 2.4: exactly three fractional digits and a trailing Z.
STORED_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PAGINATION_META_FIELDS = ("limit", "offset", "total_count", "has_more")


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def canonical_instant(value: str) -> datetime:
    """Parse any ISO 8601 UTC instant spelling onto a timezone-aware datetime.

    Accepts a trailing `Z` and an optional fractional-second part of any
    width, so `2026-08-01T00:00:00Z` and `2026-08-01T00:00:00.000Z` compare
    equal.
    """
    assert isinstance(value, str), f"expected an ISO 8601 instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two instants as points in time, ignoring fractional width."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def assert_stored_instant_format(value: Any, label: str = "timestamp") -> None:
    """PRD 2.4: stored instants carry exactly three fractional digits and Z."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert STORED_INSTANT_RE.match(value), (
        f"{label} must be ISO 8601 UTC with exactly three fractional digits and a "
        f"trailing Z, got {value!r}"
    )


def assert_date_only(value: Any, expected: Optional[str] = None,
                     label: str = "date") -> None:
    """PRD 2.4 lists the fields carried as plain `YYYY-MM-DD` calendar dates."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert DATE_ONLY_RE.match(value), (
        f"{label} must be a YYYY-MM-DD calendar date, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"{label}: expected {expected}, got {value}"


def instant_plus_days(instant: str, days: int) -> str:
    """The instant `days` whole days after `instant`, spelled without fractions."""
    moment = canonical_instant(instant) + timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def date_plus_days(day: str, days: int) -> str:
    """The calendar date `days` days after `day`."""
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def validate_unpaginated(response: requests.Response,
                         expected_status: int = 200) -> Dict[str, Any]:
    """Validate a single-resource or computed-object success response.

    PRD 2.3: only list responses carry `limit`, `offset`, `total_count` and
    `has_more`; a single-resource response omits all four. Use this for every
    read and write that answers with one object.
    """
    data = validate_success(response, expected_status)
    meta = response.json()["meta"]
    for field in PAGINATION_META_FIELDS:
        assert field not in meta or meta[field] is None, (
            f"single-resource response must omit meta.{field}, got {meta.get(field)!r}"
        )
    assert response.json()["response_type"] == "object", (
        "single-resource response_type must be 'object'"
    )
    return data


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None,
                         label: str = "row") -> None:
    """PRD 2.4: most rows carry id, created_at, updated_at and version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in row, f"{label} must carry {field}"
    assert_stored_instant_format(row["created_at"], f"{label}.created_at")
    assert_stored_instant_format(row["updated_at"], f"{label}.updated_at")
    assert isinstance(row["version"], int), f"{label}.version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"{label}.version: expected {expected_version}, got {row['version']}"
        )


def assert_component_field_shape(component: Dict[str, Any]) -> None:
    """PRD 2.4: a recipe component carries only `id` and `created_at`."""
    assert "id" in component, "component must carry id"
    assert "created_at" in component, "component must carry created_at"
    assert_stored_instant_format(component["created_at"], "component.created_at")
    assert "updated_at" not in component, (
        "a recipe component must not carry updated_at"
    )
    assert "version" not in component, "a recipe component must not carry version"


def assert_fields_are_none(row: Dict[str, Any], fields, label: str = "row") -> None:
    for field in fields:
        assert row.get(field) is None, (
            f"{label}.{field} must be null, got {row.get(field)!r}"
        )


def assert_ordered_by(rows: List[Dict[str, Any]], field: str,
                      descending: bool = False) -> None:
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows must be ordered by {field} "
        f"{'descending' if descending else 'ascending'}: got {values}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """PRD 2.3: list responses are ordered by `created_at` ascending."""
    instants = [canonical_instant(row["created_at"]) for row in rows]
    assert instants == sorted(instants), (
        f"rows must be ordered by created_at ascending: got "
        f"{[row['created_at'] for row in rows]}"
    )


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


# ---------------------------------------------------------------------------
# Arithmetic mirrors (PRD 2.7)
# ---------------------------------------------------------------------------
def round_half_up(value, places: int = 0):
    """Round half up, the only rounding mode PRD 2.7 permits."""
    quantum = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


def calorie_ladder(raw) -> int:
    """PRD 2.7 calorie declaration ladder, applied once to a raw total."""
    amount = Decimal(str(raw))
    if amount < 5:
        return 0
    if amount <= 50:
        return round_half_up(amount / 5) * 5
    return round_half_up(amount / 10) * 10


def sodium_ladder(raw) -> int:
    """PRD 2.7 sodium declaration ladder, applied once to a raw total."""
    amount = Decimal(str(raw))
    if amount < 5:
        return 0
    if amount <= 140:
        return round_half_up(amount / 5) * 5
    return round_half_up(amount / 10) * 10


def reprint_tolerance(prior_max: int) -> int:
    """PRD 3.4: max(20 calories, 20 per cent of the prior maximum)."""
    return max(20, round_half_up(Decimal(str(prior_max)) * Decimal("0.20")))


def assert_money_cents(value: Any, expected: Optional[int] = None,
                       label: str = "amount") -> None:
    """PRD 2.7: money is held in whole cents as an integer."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer count of whole cents, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"{label}: expected {expected} cents, got {value}"


def assert_two_decimal_places(value: Any, label: str = "value") -> None:
    """PRD 2.7 holds component-level figures at two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    quantised = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert Decimal(str(value)) == quantised, (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_numeric_equals(actual: Any, expected, label: str = "value") -> None:
    """Compare a JSON number against an expected decimal value exactly."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert Decimal(str(actual)) == Decimal(str(expected)), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Board line text (PRD 3.3)
# ---------------------------------------------------------------------------
def expected_display_calorie_text(declared_min: int, declared_max: int) -> str:
    if declared_min == declared_max:
        return f"{declared_min} Cal"
    return f"{declared_min}-{declared_max} Cal"


# ---------------------------------------------------------------------------
# Aggregate readbacks
# ---------------------------------------------------------------------------
def assert_brand_counters(
    brand: Dict[str, Any],
    coverage_status: Optional[str] = None,
    coverage_reason: Optional[str] = None,
    counted_unit_count: Optional[int] = None,
    standard_item_count: Optional[int] = None,
    compliance_posture: Optional[str] = None,
    open_reprint_obligation_count: Optional[int] = None,
    overdue_board_count: Optional[int] = None,
    open_enforcement_escalated_count: Optional[int] = None,
    has_published_disclosure_packet: Optional[bool] = None,
) -> None:
    """Assert the brand fields named, ignoring the ones left as None."""
    expectations: List[Tuple[str, Any]] = [
        ("coverage_status", coverage_status),
        ("coverage_reason", coverage_reason),
        ("counted_unit_count", counted_unit_count),
        ("standard_item_count", standard_item_count),
        ("compliance_posture", compliance_posture),
        ("open_reprint_obligation_count", open_reprint_obligation_count),
        ("overdue_board_count", overdue_board_count),
        ("open_enforcement_escalated_count", open_enforcement_escalated_count),
        ("has_published_disclosure_packet", has_published_disclosure_packet),
    ]
    for field, expected in expectations:
        if expected is None:
            continue
        assert brand.get(field) == expected, (
            f"Brand.{field}: expected {expected!r}, got {brand.get(field)!r}"
        )


def assert_board_state(
    board: Dict[str, Any],
    publication_status: Optional[str] = None,
    calorie_compliance_status: Optional[str] = None,
    listing_count: Optional[int] = None,
    stale_listing_count: Optional[int] = None,
    reprint_count: Optional[int] = None,
) -> None:
    expectations: List[Tuple[str, Any]] = [
        ("publication_status", publication_status),
        ("calorie_compliance_status", calorie_compliance_status),
        ("listing_count", listing_count),
        ("stale_listing_count", stale_listing_count),
        ("reprint_count", reprint_count),
    ]
    for field, expected in expectations:
        if expected is None:
            continue
        assert board.get(field) == expected, (
            f"MenuBoard.{field}: expected {expected!r}, got {board.get(field)!r}"
        )


def assert_item_declaration(
    item: Dict[str, Any],
    declared_calorie_min: Optional[int] = None,
    declared_calorie_max: Optional[int] = None,
    declared_sodium_mg: Optional[int] = None,
    labeling_status: Optional[str] = None,
    labeling_exempt: Optional[bool] = None,
    approved_recipe_version_no: Optional[int] = None,
) -> None:
    expectations: List[Tuple[str, Any]] = [
        ("declared_calorie_min", declared_calorie_min),
        ("declared_calorie_max", declared_calorie_max),
        ("declared_sodium_mg", declared_sodium_mg),
        ("labeling_status", labeling_status),
        ("labeling_exempt", labeling_exempt),
        ("approved_recipe_version_no", approved_recipe_version_no),
    ]
    for field, expected in expectations:
        if expected is None:
            continue
        assert item.get(field) == expected, (
            f"MenuItem.{field}: expected {expected!r}, got {item.get(field)!r}"
        )
