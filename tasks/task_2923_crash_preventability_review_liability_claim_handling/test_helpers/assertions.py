"""Domain assertions and the small arithmetic helpers the rules require."""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from test_helpers.types import (
    API_REQUEST_ID_PREFIX,
    ERROR_DATA_KEYS,
    META_ALWAYS_KEYS,
    META_PAGINATION_KEYS,
    RESPONSE_TYPE_ARRAY,
    RESPONSE_TYPE_ERROR,
    RESPONSE_TYPE_OBJECT,
)

# ---------------------------------------------------------------------------
# Instant handling
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an instant, tolerating any fractional-second width."""
    assert isinstance(value, str), f"expected an instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instant(value: str) -> str:
    """Normalise an instant to whole seconds with a trailing Z."""
    return parse_instant(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_instant(
    value: str,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
    milliseconds: int = 0,
) -> str:
    """Return the instant moved by the supplied offset, in whole seconds."""
    moved = parse_instant(value) + timedelta(
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        milliseconds=milliseconds,
    )
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def days_between(earlier: str, later: str) -> int:
    """Whole days elapsed from the earlier instant to the later one."""
    return (parse_instant(later) - parse_instant(earlier)).days


def assert_instants_equal(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two instants by value, ignoring fractional-second width."""
    assert actual is not None, f"{label} is missing"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )


def assert_timestamp_shape(value: Any, label: str = "timestamp") -> None:
    """Timestamps are ISO 8601 in UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} should be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO 8601: {value!r}"
    assert value.endswith("Z"), f"{label} should be expressed in UTC: {value!r}"
    fraction = value[:-1].split(".")
    assert len(fraction) == 2 and len(fraction[1]) == 3, (
        f"{label} should carry exactly three fractional digits: {value!r}"
    )


# ---------------------------------------------------------------------------
# Envelope assertions
# ---------------------------------------------------------------------------


def assert_meta_shape(body: Dict[str, Any], paginated: bool = False) -> None:
    """Every envelope carries a request identifier and a request timestamp."""
    meta = body["meta"]
    for key in META_ALWAYS_KEYS:
        assert key in meta, f"meta is missing {key}"
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith(API_REQUEST_ID_PREFIX), (
        f"api_request_id should be prefixed with {API_REQUEST_ID_PREFIX}: "
        f"{meta['api_request_id']!r}"
    )
    assert_timestamp_shape(meta["api_request_timestamp"], "api_request_timestamp")
    for key in META_PAGINATION_KEYS:
        if paginated:
            assert key in meta, f"a collection read must publish meta.{key}"
        else:
            assert key not in meta, (
                f"a single-resource or write response must omit meta.{key}"
            )


def assert_object_envelope(body: Dict[str, Any]) -> Dict[str, Any]:
    assert body["response_type"] == RESPONSE_TYPE_OBJECT, (
        f"response_type should be {RESPONSE_TYPE_OBJECT}, got {body['response_type']!r}"
    )
    assert_meta_shape(body, paginated=False)
    return body["data"]


def assert_array_envelope(body: Dict[str, Any]) -> Sequence[Dict[str, Any]]:
    assert body["response_type"] == RESPONSE_TYPE_ARRAY, (
        f"response_type should be {RESPONSE_TYPE_ARRAY}, got {body['response_type']!r}"
    )
    assert_meta_shape(body, paginated=True)
    assert isinstance(body["data"], list)
    return body["data"]


def assert_error_envelope(body: Dict[str, Any]) -> Dict[str, Any]:
    assert body["response_type"] == RESPONSE_TYPE_ERROR, (
        f"response_type should be {RESPONSE_TYPE_ERROR}, got {body['response_type']!r}"
    )
    assert_meta_shape(body, paginated=False)
    for key in ERROR_DATA_KEYS:
        assert key in body["data"], f"error payload is missing {key}"
    return body["data"]


def assert_page(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    """Check the four pagination keys published directly on meta."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count should be {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more should be {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"limit should be {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset should be {offset}, got {meta['offset']}"


# ---------------------------------------------------------------------------
# Row assertions
# ---------------------------------------------------------------------------


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A versioned row carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id should be a UUID with no prefix: {row['id']!r}"
    assert_timestamp_shape(row["created_at"], "created_at")
    assert_timestamp_shape(row["updated_at"], "updated_at")
    assert isinstance(row["version"], int), "version should be an integer"
    assert row["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"version should be {expected_version}, got {row['version']}"
        )


def assert_append_only_fields(row: Dict[str, Any]) -> None:
    """An append-only row carries only id and created_at as system fields."""
    assert is_valid_uuid(row["id"]), f"id should be a UUID with no prefix: {row['id']!r}"
    assert_timestamp_shape(row["created_at"], "created_at")
    assert "updated_at" not in row, "an append-only row must not carry updated_at"
    assert "version" not in row, "an append-only row must not carry version"


def assert_declared_fields(row: Dict[str, Any], fields: Iterable[str]) -> None:
    missing = [field for field in fields if field not in row]
    assert not missing, f"row is missing declared fields: {missing}"


def assert_fields_equal(row: Dict[str, Any], expected: Dict[str, Any]) -> None:
    for key, value in expected.items():
        assert row[key] == value, f"{key} should be {value!r}, got {row[key]!r}"


def assert_row_ids(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """Rows appear exactly once each, in the given order."""
    assert [row["id"] for row in rows] == list(expected_ids), (
        f"expected rows {list(expected_ids)}, got {[row['id'] for row in rows]}"
    )


def assert_id_set(rows: Sequence[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    assert {row["id"] for row in rows} == set(expected_ids), (
        f"expected the set {sorted(set(expected_ids))}, "
        f"got {sorted(row['id'] for row in rows)}"
    )


# ---------------------------------------------------------------------------
# Rounding and money
# ---------------------------------------------------------------------------


def round_half_up(value: Any, places: int = 0) -> Decimal:
    """Round half away from zero at the given number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def cents_half_up(value: Any) -> int:
    """Round a cent quantity half up to a whole cent."""
    return int(round_half_up(value, 0))


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Money is carried as an integer number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} should be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label} should be {expected} cents, got {actual}"


def assert_decimal_places(actual: Any, places: int, label: str = "value") -> None:
    """Check that a rounded quantity carries no more precision than allowed."""
    as_decimal = Decimal(str(actual))
    assert as_decimal == as_decimal.quantize(
        Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
    ), f"{label} should be rounded to {places} decimal places, got {actual!r}"


def assert_rate(actual: Any, expected: float, label: str = "rate") -> None:
    """Crash rates are published to three decimal places."""
    assert_decimal_places(actual, 3, label)
    assert Decimal(str(actual)) == round_half_up(expected, 3), (
        f"{label} should be {expected:.3f}, got {actual!r}"
    )


def assert_score_2dp(actual: Any, expected: float, label: str = "score") -> None:
    """Ballot and committee scores are published to two decimal places."""
    assert_decimal_places(actual, 2, label)
    assert Decimal(str(actual)) == round_half_up(expected, 2), (
        f"{label} should be {expected:.2f}, got {actual!r}"
    )


def assert_points_1dp(actual: Any, expected: float, label: str = "points") -> None:
    """Driver points are published to one decimal place."""
    assert_decimal_places(actual, 1, label)
    assert Decimal(str(actual)) == round_half_up(expected, 1), (
        f"{label} should be {expected:.1f}, got {actual!r}"
    )


def assert_multiplier(actual: Any, expected: float, label: str = "multiplier") -> None:
    assert Decimal(str(actual)) == round_half_up(expected, 2), (
        f"{label} should be {expected:.2f}, got {actual!r}"
    )


# ---------------------------------------------------------------------------
# Rule calculators, used to express expectations in domain language
# ---------------------------------------------------------------------------


def weighted_member_score(scores: Dict[str, int], mechanical_factor: bool) -> Decimal:
    """Weighted ballot score, renormalised when the mechanical criterion drops."""
    from test_helpers.constants import (
        CRITERION_WEIGHTS,
        MECHANICAL_CRITERION,
        WEIGHT_DENOMINATOR_FULL,
        WEIGHT_DENOMINATOR_NO_MECHANICAL,
    )

    numerator = Decimal("0")
    for criterion, weight in CRITERION_WEIGHTS.items():
        if criterion == MECHANICAL_CRITERION and not mechanical_factor:
            continue
        numerator += Decimal(str(weight)) * Decimal(str(scores[criterion]))
    denominator = Decimal(
        str(WEIGHT_DENOMINATOR_FULL if mechanical_factor else WEIGHT_DENOMINATOR_NO_MECHANICAL)
    )
    return round_half_up(numerator / denominator, 2)


def committee_score(member_scores: Sequence[Any]) -> Decimal:
    """Mean of the already-rounded member scores, itself rounded to two places."""
    total = sum((Decimal(str(score)) for score in member_scores), Decimal("0"))
    return round_half_up(total / Decimal(len(member_scores)), 2)


def alae_rate(indemnity_cents: int) -> Decimal:
    """Expense rate keyed on the indemnity amount alone."""
    from test_helpers.constants import ALAE_RATE_BANDS

    for threshold, rate in ALAE_RATE_BANDS:
        if indemnity_cents >= threshold:
            return Decimal(str(rate))
    raise AssertionError("indemnity must be non negative")


def alae_cents(indemnity_cents: int) -> int:
    return cents_half_up(Decimal(indemnity_cents) * alae_rate(indemnity_cents))


def reserve_multiplier(risk_score: int) -> Decimal:
    from test_helpers.constants import RESERVE_MULTIPLIER_BANDS

    for threshold, multiplier in RESERVE_MULTIPLIER_BANDS:
        if risk_score >= threshold:
            return Decimal(str(multiplier))
    raise AssertionError("risk score must be non negative")


def reserve_from_gross(
    gross_cents: int, risk_score: int, counsel_assigned: bool
) -> int:
    """Reserve estimate: multiplied gross, plus the counsel load, then floored."""
    from test_helpers.constants import COUNSEL_EXPENSE_RATE, RESERVE_FLOOR_CENTS

    multiplied = cents_half_up(Decimal(gross_cents) * reserve_multiplier(risk_score))
    if counsel_assigned:
        multiplied += cents_half_up(Decimal(gross_cents) * Decimal(str(COUNSEL_EXPENSE_RATE)))
    return max(multiplied, RESERVE_FLOOR_CENTS)


def provisional_gross_cents(
    severity: str, injury_transported_count: int, fatality_count: int
) -> int:
    from test_helpers.constants import (
        FATALITY_UNIT_CENTS,
        INJURY_TRANSPORTED_UNIT_CENTS,
        SEVERITY_RESERVE_BASE_CENTS,
    )

    return (
        SEVERITY_RESERVE_BASE_CENTS[severity]
        + INJURY_TRANSPORTED_UNIT_CENTS * injury_transported_count
        + FATALITY_UNIT_CENTS * fatality_count
    )


def crash_rate_per_million_miles(
    preventable_crash_count: int, annual_miles_millions: Any
) -> Decimal:
    return round_half_up(
        Decimal(preventable_crash_count) / Decimal(str(annual_miles_millions)), 3
    )


def risk_tier_for_rate(rate: Any) -> str:
    from test_helpers.constants import (
        RISK_TIER_CRITICAL,
        RISK_TIER_CRITICAL_MIN_RATE,
        RISK_TIER_ELEVATED,
        RISK_TIER_ELEVATED_MIN_RATE,
        RISK_TIER_STANDARD,
    )

    as_decimal = Decimal(str(rate))
    if as_decimal >= Decimal(str(RISK_TIER_CRITICAL_MIN_RATE)):
        return RISK_TIER_CRITICAL
    if as_decimal >= Decimal(str(RISK_TIER_ELEVATED_MIN_RATE)):
        return RISK_TIER_ELEVATED
    return RISK_TIER_STANDARD


def action_tier_for_points(points: Any) -> str:
    from test_helpers.constants import ACTION_TIER_NONE, ACTION_TIER_THRESHOLDS

    as_decimal = Decimal(str(points))
    for threshold, tier in ACTION_TIER_THRESHOLDS:
        if as_decimal >= Decimal(str(threshold)):
            return tier
    return ACTION_TIER_NONE
