"""Domain assertion helpers.

All comparisons of decimal quantities go through `assert_load` / `assert_ratio`
/ `assert_pct` so a float-representation artefact can never be mistaken for a
rounding defect, and all instant comparisons go through `assert_instant_equals`
so a sub-second width difference can never be mistaken for a clock defect.
"""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import LOAD_DP, PCT_DP, RATIO_DP

# --------------------------------------------------------------- numeric compare


def _quantize(value: float, dp: int) -> float:
    return round(float(value) + 0.0, dp)


def assert_decimal_equals(actual: Any, expected: float, dp: int, label: str = "") -> None:
    """Assert a JSON number equals `expected` when both are read at `dp` places."""
    assert actual is not None, "{}: expected {} but the field was null".format(label, expected)
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        "{}: expected a JSON number, got {!r}".format(label, actual)
    )
    assert _quantize(actual, dp) == _quantize(expected, dp), (
        "{}: expected {} at {} dp, got {}".format(label, expected, dp, actual)
    )


def assert_load(actual: Any, expected: float, label: str = "load") -> None:
    """Loads are carried in pounds per year and stored to 2 decimal places (§2.5)."""
    assert_decimal_equals(actual, expected, LOAD_DP, label)


def assert_ratio(actual: Any, expected: float, label: str = "ratio") -> None:
    """Ratios and factors that discount or route a quantity are carried to 4 dp (§2.5)."""
    assert_decimal_equals(actual, expected, RATIO_DP, label)


def assert_pct(actual: Any, expected: float, label: str = "pct") -> None:
    """Percentages are carried to 2 decimal places (§2.5)."""
    assert_decimal_equals(actual, expected, PCT_DP, label)


def assert_decimal_places_at_most(actual: Any, dp: int, label: str = "") -> None:
    """Assert a stored number carries no more than `dp` decimal places."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        "{}: expected a JSON number, got {!r}".format(label, actual)
    )
    assert _quantize(actual, dp) == _quantize(actual, dp + 6), (
        "{}: {} carries more than {} decimal places".format(label, actual, dp)
    )


def assert_integer(actual: Any, expected: Optional[int] = None, label: str = "") -> None:
    """§2.5 lists the fields that are whole numbers; assert the JSON type too."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        "{}: expected an integer, got {!r}".format(label, actual)
    )
    if expected is not None:
        assert actual == expected, "{}: expected {}, got {}".format(label, expected, actual)


def assert_is_null(actual: Any, label: str = "") -> None:
    assert actual is None, "{}: expected null, got {!r}".format(label, actual)


# ------------------------------------------------------------------- timestamps


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two ISO-8601 UTC instants after canonicalising both to 3 fraction digits."""
    assert actual is not None, "{}: expected {} but the field was null".format(label, expected)
    assert canonical_instant(actual) == canonical_instant(expected), (
        "{}: expected {} (canonically {}), got {} (canonically {})".format(
            label, expected, canonical_instant(expected), actual, canonical_instant(actual)
        )
    )


def assert_iso_instant(actual: Any, label: str = "timestamp") -> None:
    """§2.4: a timestamp in ISO 8601 UTC notation with exactly three fractional digits."""
    assert isinstance(actual, str) and actual, "{}: expected a string, got {!r}".format(
        label, actual
    )
    assert is_iso8601_timestamp(actual), "{}: {!r} is not an ISO-8601 timestamp".format(
        label, actual
    )


def assert_calendar_date(actual: Any, expected: Optional[str] = None, label: str = "date") -> None:
    """ISO calendar dates are carried in year-month-day form."""
    assert isinstance(actual, str), "{}: expected a string date, got {!r}".format(label, actual)
    assert len(actual) >= 10 and actual[4] == "-" and actual[7] == "-", (
        "{}: {!r} is not an ISO calendar date".format(label, actual)
    )
    if expected is not None:
        assert actual[:10] == expected[:10], "{}: expected {}, got {}".format(
            label, expected, actual
        )


# --------------------------------------------------------------- common fields


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """§2.4 common fields for a mutable resource: id, created_at, updated_at, version."""
    assert is_valid_uuid(row.get("id")), "id must be a prefix-less UUID, got {!r}".format(
        row.get("id")
    )
    assert_iso_instant(row.get("created_at"), "created_at")
    assert_iso_instant(row.get("updated_at"), "updated_at")
    assert_integer(row.get("version"), expected_version, "version")
    assert row["version"] >= 1, "version starts at 1 when the row is created"


def assert_append_only_fields(row: Dict[str, Any]) -> None:
    """§2.4: a monitoring sample and a verification event "each carry only `id` and
    `created_at`. Neither has an `updated_at` field nor a `version` field"."""
    assert is_valid_uuid(row.get("id")), "id must be a prefix-less UUID, got {!r}".format(
        row.get("id")
    )
    assert_iso_instant(row.get("created_at"), "created_at")
    assert "updated_at" not in row, "an append-only record must carry no updated_at field"
    assert "version" not in row, "an append-only record must carry no version field"


def assert_version_is(row: Dict[str, Any], expected: int, label: str = "version") -> None:
    assert_integer(row.get("version"), expected, label)


def assert_version_advanced(row: Dict[str, Any], previous_version: int, label: str = "version") -> None:
    assert isinstance(row.get("version"), int), "{}: expected an integer".format(label)
    assert row["version"] > previous_version, (
        "{}: expected a version above {}, got {}".format(label, previous_version, row["version"])
    )


def assert_version_unchanged(row: Dict[str, Any], previous_version: int, label: str = "version") -> None:
    assert row.get("version") == previous_version, (
        "{}: expected the version to stay at {}, got {}".format(
            label, previous_version, row.get("version")
        )
    )


# ------------------------------------------------------------------- invariants


def assert_load_conservation(assessment: Dict[str, Any]) -> None:
    """§2.9: `loading_capacity_lbs_yr` is exactly equal to the sum of
    `margin_of_safety_lbs_yr`, `effective_background_lbs_yr`, `wla_total_lbs_yr`,
    `la_total_lbs_yr` and `reserve_allocation_lbs_yr`."""
    terms = [
        assessment["margin_of_safety_lbs_yr"],
        assessment["effective_background_lbs_yr"],
        assessment["wla_total_lbs_yr"],
        assessment["la_total_lbs_yr"],
        assessment["reserve_allocation_lbs_yr"],
    ]
    for index, term in enumerate(terms):
        assert term is not None, "load-conservation term {} is null".format(index)
    total = round(sum(round(float(t), 2) for t in terms), 2)
    assert_load(
        total,
        float(assessment["loading_capacity_lbs_yr"]),
        "load conservation (MOS + background + WLA + LA + reserve)",
    )


def assert_credit_mass_conservation(batch: Dict[str, Any]) -> None:
    """§2.9: a batch's `issued_lbs` is exactly equal to the sum of `available_lbs`,
    `reserved_lbs`, `retired_lbs` and `invalidated_lbs` at every instant."""
    buckets = round(
        round(float(batch["available_lbs"]), 2)
        + round(float(batch["reserved_lbs"]), 2)
        + round(float(batch["retired_lbs"]), 2)
        + round(float(batch["invalidated_lbs"]), 2),
        2,
    )
    assert_load(
        buckets,
        float(batch["issued_lbs"]),
        "credit mass conservation (available + reserved + retired + invalidated)",
    )


def assert_batch_buckets(
    batch: Dict[str, Any],
    available: float,
    reserved: float,
    retired: float,
    invalidated: float,
) -> None:
    """Assert all four balance buckets at once and re-check mass conservation."""
    assert_load(batch["available_lbs"], available, "available_lbs")
    assert_load(batch["reserved_lbs"], reserved, "reserved_lbs")
    assert_load(batch["retired_lbs"], retired, "retired_lbs")
    assert_load(batch["invalidated_lbs"], invalidated, "invalidated_lbs")
    assert_credit_mass_conservation(batch)


def assert_trading_gate(watershed: Dict[str, Any], expected_status: str) -> None:
    """§2.10: `trading_enabled` "is true if and only if `program_status` equals `ACTIVE`"."""
    assert watershed["program_status"] == expected_status, (
        "program_status: expected {}, got {}".format(expected_status, watershed["program_status"])
    )
    assert watershed["trading_enabled"] is (expected_status == "ACTIVE"), (
        "trading_enabled must be true if and only if program_status is ACTIVE; "
        "status={} trading_enabled={}".format(expected_status, watershed["trading_enabled"])
    )


# ----------------------------------------------------------------- envelope shape


def assert_object_envelope(body: Dict[str, Any]) -> None:
    """§2.2: a single-resource success envelope carries exactly meta, response_type, data."""
    assert set(body.keys()) == {"meta", "response_type", "data"}, (
        "success envelope must carry exactly meta, response_type and data; got {}".format(
            sorted(body.keys())
        )
    )
    assert body["response_type"] == "object", (
        "response_type must be 'object' for a single resource, got {!r}".format(
            body["response_type"]
        )
    )


def assert_error_envelope(body: Dict[str, Any], expected_error_id: str) -> None:
    """§2.2: an error envelope's `meta` "contains only api_request_id and
    api_request_timestamp", and its data carries `error_id` and `message`."""
    assert set(body.keys()) == {"meta", "response_type", "data"}, (
        "error envelope must carry exactly meta, response_type and data; got {}".format(
            sorted(body.keys())
        )
    )
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "error meta must contain only api_request_id and api_request_timestamp; got {}".format(
            sorted(body["meta"].keys())
        )
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_, got {!r}".format(body["meta"]["api_request_id"])
    )
    assert_iso_instant(body["meta"]["api_request_timestamp"], "api_request_timestamp")
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        "error data must carry exactly error_id and message; got {}".format(
            sorted(body["data"].keys())
        )
    )
    assert body["data"]["error_id"] == expected_error_id
    assert body["data"]["message"].strip(), "message must be a non-empty explanation"


def assert_request_metadata(body: Dict[str, Any]) -> None:
    """§2.2: `api_request_id` "starts with `req_`" and `api_request_timestamp` is
    a server-generated ISO 8601 UTC timestamp with three fractional digits."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith(
        "req_"
    ), "api_request_id must start with req_, got {!r}".format(meta.get("api_request_id"))
    assert_iso_instant(meta.get("api_request_timestamp"), "api_request_timestamp")


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """§2.3: every list response carries limit, offset, total_count and has_more."""
    assert_integer(meta.get("limit"), limit, "meta.limit")
    assert_integer(meta.get("offset"), offset, "meta.offset")
    assert_integer(meta.get("total_count"), total_count, "meta.total_count")
    assert meta.get("has_more") is has_more, (
        "meta.has_more: expected {}, got {!r}".format(has_more, meta.get("has_more"))
    )


def ids_of(rows: Iterable[Dict[str, Any]]) -> list:
    return [row["id"] for row in rows]


def field_sequence(rows: Iterable[Dict[str, Any]], field: str) -> list:
    return [row[field] for row in rows]
