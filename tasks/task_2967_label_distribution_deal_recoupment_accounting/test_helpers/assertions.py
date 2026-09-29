"""
Domain assertions for the Label Distribution Recoupment API.

These wrap the raw comparisons the tests need so that a failure message names
the field and both values. Two families deserve a note:

* **Percentages.** A conforming server may render a four-decimal fraction as a
  JSON number (``0.1500``) or as a decimal string (``"0.1500"``), and a JSON
  number may arrive as the float ``0.15``. ``assert_pct_equals`` compares
  numerically through ``decimal.Decimal`` so none of those spellings can produce
  a spurious failure, while a genuinely different rate still fails.

* **Instants.** ``assert_instant_equals`` canonicalises both sides to exactly
  three fractional digits before comparing, so ``2026-08-01T00:00:00Z`` and
  ``2026-08-01T00:00:00.000Z`` are the same instant. Use
  ``assert_instant_precision`` when the *rendering* itself is under test.
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional, Sequence

from prd_bench_local_runner.testing import is_valid_uuid, validate_paginated

from .api_client import canonical_instant
from .constants import (
    APPEND_ONLY_COMMON_FIELDS,
    MUTABLE_COMMON_FIELDS,
    PCT_QUANTUM,
    REQUEST_ID_PREFIX,
)

_THREE_DIGIT_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def as_decimal(value: Any) -> Decimal:
    """Coerce a JSON number / decimal string / Decimal to Decimal exactly."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise AssertionError("expected a number, got a boolean: %r" % (value,))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value: Any, decimal_places: int = 0) -> Decimal:
    """PRD Section 2.6 rounding: half up, to ``decimal_places`` digits."""
    quantum = Decimal(1).scaleb(-decimal_places)
    return as_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents_half_up(value: Any) -> int:
    """Derived money: rounded half up to whole cents."""
    return int(round_half_up(value, 0))


def pct_half_up(value: Any) -> Decimal:
    """A derived *stored* percentage: rounded half up to four decimal places."""
    return round_half_up(value, 4)


def units_ceiling(value: Any) -> int:
    """The one non-half-up operator: the inventory obligation floor rounds a unit
    count UP to the next whole unit (PRD Section 3.7)."""
    dec = as_decimal(value)
    whole = int(dec)
    return whole if dec == whole else whole + 1


# ---------------------------------------------------------------------------
# Percentages
# ---------------------------------------------------------------------------

def assert_pct_equals(actual: Any, expected: Any, field: str = "percentage") -> None:
    assert actual is not None, "%s: expected %s, got null" % (field, expected)
    got = as_decimal(actual)
    want = as_decimal(expected)
    assert got == want, "%s: expected %s, got %s" % (field, want, got)


def assert_pct_in_range(
    actual: Any, minimum: Any, maximum: Any, field: str = "percentage"
) -> None:
    got = as_decimal(actual)
    assert as_decimal(minimum) <= got <= as_decimal(maximum), (
        "%s: %s outside declared range [%s, %s]" % (field, got, minimum, maximum)
    )


def assert_pct_four_decimals(actual: Any, field: str = "percentage") -> None:
    """A stored percentage must be expressible at exactly four decimal places."""
    got = as_decimal(actual)
    assert got == got.quantize(PCT_QUANTUM), (
        "%s: %s carries more precision than four decimal places" % (field, got)
    )


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def assert_money(actual: Any, expected: int, field: str = "amount") -> None:
    """Money is "integers denominated in whole cents ... no field stores money as
    a decimal string" (PRD Section 2.6)."""
    assert not isinstance(actual, str), (
        "%s: money must be a JSON integer, got the string %r" % (field, actual)
    )
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        "%s: money must be a JSON integer, got %r (%s)"
        % (field, actual, type(actual).__name__)
    )
    assert actual == expected, "%s: expected %d cents, got %d" % (
        field,
        expected,
        actual,
    )


def assert_field_money(record: dict, field: str, expected: int) -> None:
    assert field in record, "record is missing field %r" % field
    assert_money(record[field], expected, field)


def assert_fields_money(record: dict, **expected: int) -> None:
    for field, value in expected.items():
        assert_field_money(record, field, value)


# ---------------------------------------------------------------------------
# Generic field assertions
# ---------------------------------------------------------------------------

def assert_field(record: dict, field: str, expected: Any) -> None:
    assert field in record, "record is missing field %r" % field
    assert record[field] == expected, "%s: expected %r, got %r" % (
        field,
        expected,
        record[field],
    )


def assert_fields(record: dict, **expected: Any) -> None:
    for field, value in expected.items():
        assert_field(record, field, value)


def assert_null(record: dict, *fields: str) -> None:
    for field in fields:
        assert field in record, "record is missing field %r" % field
        assert record[field] is None, "%s: expected null, got %r" % (
            field,
            record[field],
        )


def assert_not_null(record: dict, *fields: str) -> None:
    for field in fields:
        assert record.get(field) is not None, "%s: expected a value, got null" % field


def assert_status(record: dict, expected: str, field: str = "status") -> None:
    assert record.get(field) == expected, "%s: expected %s, got %r" % (
        field,
        expected,
        record.get(field),
    )


# ---------------------------------------------------------------------------
# Timestamps and dates
# ---------------------------------------------------------------------------

def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    assert actual is not None, "%s: expected %s, got null" % (field, expected)
    got = canonical_instant(actual)
    want = canonical_instant(expected)
    assert got == want, "%s: expected %s, got %s (raw %r)" % (
        field,
        want,
        got,
        actual,
    )


def assert_instant_precision(actual: Any, field: str = "instant") -> None:
    """PRD Section 2.4: an instant is "rendered in ISO 8601 with a trailing Z and
    exactly three fractional digits"."""
    assert isinstance(actual, str), "%s: expected an ISO 8601 string, got %r" % (
        field,
        actual,
    )
    assert _THREE_DIGIT_INSTANT_RE.match(actual), (
        "%s: %r is not an ISO 8601 UTC instant with exactly three fractional digits"
        % (field, actual)
    )


def assert_date(actual: Any, expected: str, field: str = "date") -> None:
    assert actual == expected, "%s: expected %s, got %r" % (field, expected, actual)


def assert_is_date(actual: Any, field: str = "date") -> None:
    assert isinstance(actual, str) and _DATE_RE.match(actual), (
        "%s: %r is not a YYYY-MM-DD calendar date" % (field, actual)
    )


# ---------------------------------------------------------------------------
# Common-field families (PRD Section 2.4)
# ---------------------------------------------------------------------------

def assert_mutable_common_fields(record: dict, entity: str = "record") -> None:
    """The nine mutable types carry id, created_at, updated_at and version."""
    for field in MUTABLE_COMMON_FIELDS:
        assert field in record, "%s: missing common field %r" % (entity, field)
    assert is_valid_uuid(record["id"]), "%s: id %r is not a UUID" % (
        entity,
        record["id"],
    )
    assert_instant_precision(record["created_at"], "%s.created_at" % entity)
    assert_instant_precision(record["updated_at"], "%s.updated_at" % entity)
    assert isinstance(record["version"], int) and not isinstance(
        record["version"], bool
    ), "%s: version must be an integer, got %r" % (entity, record["version"])
    assert record["version"] >= 1, "%s: version must start at 1" % entity


def assert_append_only_common_fields(record: dict, entity: str = "record") -> None:
    """The two append-only types carry only id and created_at - and must carry
    "neither updated_at nor version"."""
    for field in APPEND_ONLY_COMMON_FIELDS:
        assert field in record, "%s: missing common field %r" % (entity, field)
    assert is_valid_uuid(record["id"]), "%s: id %r is not a UUID" % (
        entity,
        record["id"],
    )
    assert_instant_precision(record["created_at"], "%s.created_at" % entity)
    assert "updated_at" not in record, (
        "%s is append-only and must not carry updated_at" % entity
    )
    assert "version" not in record, (
        "%s is append-only and must not carry version" % entity
    )


def assert_version_is(record: dict, expected: int, entity: str = "record") -> None:
    assert record.get("version") == expected, "%s.version: expected %r, got %r" % (
        entity,
        expected,
        record.get("version"),
    )


def assert_version_bumped(
    before: dict, after: dict, by: int = 1, entity: str = "record"
) -> None:
    got = after.get("version")
    want = before.get("version") + by
    assert got == want, "%s.version: expected %r (was %r + %d), got %r" % (
        entity,
        want,
        before.get("version"),
        by,
        got,
    )


def assert_version_unchanged(before: dict, after: dict, entity: str = "record") -> None:
    assert after.get("version") == before.get("version"), (
        "%s.version: expected it to stay at %r, got %r"
        % (entity, before.get("version"), after.get("version"))
    )


def assert_server_owned_id(record: dict, submitted_id: Optional[str] = None) -> None:
    """PRD Section 2.4: the server mints the id and "a client-supplied id field is
    ignored rather than honoured"."""
    assert is_valid_uuid(record["id"]), "id %r is not a UUID" % record["id"]
    if submitted_id is not None:
        assert record["id"] != submitted_id, (
            "a client-supplied id must be ignored, but the server stored %r"
            % submitted_id
        )


# ---------------------------------------------------------------------------
# Lists (PRD Section 2.3) - every list endpoint in this API is paginated
# ---------------------------------------------------------------------------

def validate_list(response) -> tuple:
    """Every collection listing in this API pages, so this delegates to the
    shared paginated validator and returns ``(items, meta)``."""
    return validate_paginated(response)


def validate_unpaginated_list(response, expected_status: int = 200) -> list:
    """An array-shaped 2xx body whose meta is not asserted to carry paging state.

    Provided for completeness; prefer ``validate_list`` for the endpoints of PRD
    Section 4, all of which report ``limit``, ``offset``, ``total_count`` and
    ``has_more``.
    """
    assert response.status_code == expected_status, (
        "expected %d, got %d: %s"
        % (expected_status, response.status_code, response.text)
    )
    body = response.json()
    assert body.get("response_type") == "array", (
        "expected response_type 'array', got %r" % body.get("response_type")
    )
    assert isinstance(body.get("data"), list), "data must be a JSON array"
    return body["data"]


def assert_pagination_meta(
    meta: dict,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if limit is not None:
        assert meta["limit"] == limit, "meta.limit: expected %r, got %r" % (
            limit,
            meta["limit"],
        )
    if offset is not None:
        assert meta["offset"] == offset, "meta.offset: expected %r, got %r" % (
            offset,
            meta["offset"],
        )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            "meta.total_count: expected %r, got %r" % (total_count, meta["total_count"])
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, "meta.has_more: expected %r, got %r" % (
            has_more,
            meta["has_more"],
        )


def assert_total_count(response, expected: int) -> list:
    items, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        "meta.total_count: expected %d, got %d" % (expected, meta["total_count"])
    )
    return items


def assert_ordered_by_created_at(items: Sequence[dict]) -> None:
    """PRD Section 2.3: "Results are ordered by created_at ascending"."""
    stamps = [canonical_instant(item["created_at"]) for item in items]
    assert stamps == sorted(stamps), (
        "list is not ordered by created_at ascending: %r" % (stamps,)
    )


def assert_id_order(items: Sequence[dict], expected_ids: Sequence[str]) -> None:
    got = [item["id"] for item in items]
    assert got == list(expected_ids), "list order: expected %r, got %r" % (
        list(expected_ids),
        got,
    )


def ids_of(items: Iterable[dict]) -> list:
    return [item["id"] for item in items]


def find_by_id(items: Iterable[dict], record_id: str) -> dict:
    for item in items:
        if item.get("id") == record_id:
            return item
    raise AssertionError("no record with id %r in the listing" % record_id)


def find_by_release(items: Iterable[dict], release_id: str) -> dict:
    for item in items:
        if item.get("release_id") == release_id:
            return item
    raise AssertionError("no record for release %r in the listing" % release_id)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def assert_request_meta(response) -> dict:
    """PRD Section 2.2: api_request_id starts with ``req_`` and
    api_request_timestamp is an ISO 8601 UTC instant with three fractional
    digits."""
    meta = response.json()["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith(REQUEST_ID_PREFIX), (
        "meta.api_request_id must start with %r, got %r"
        % (REQUEST_ID_PREFIX, meta["api_request_id"])
    )
    assert_instant_precision(
        meta.get("api_request_timestamp"), "meta.api_request_timestamp"
    )
    return meta


def assert_error_meta_has_no_pagination(response) -> None:
    """PRD Section 2.2: "The meta object for error responses contains only
    api_request_id and api_request_timestamp"."""
    meta = response.json()["meta"]
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, "an error envelope's meta must not carry %r" % field


# ---------------------------------------------------------------------------
# Conserved quantities (PRD Section 2.9)
# ---------------------------------------------------------------------------

def assert_advance_conserved(deal: dict) -> None:
    """"advance_amount_cents always equals advance_recouped_cents plus
    unrecouped_advance_cents"."""
    total = deal["advance_amount_cents"]
    recouped = deal["advance_recouped_cents"]
    outstanding = deal["unrecouped_advance_cents"]
    assert total == recouped + outstanding, (
        "advance conservation broken: %d != %d + %d" % (total, recouped, outstanding)
    )


def assert_reserve_conserved(run: dict) -> None:
    """"reserve_initial_cents always equals reserve_held_cents plus
    reserve_liquidated_cents"."""
    initial = run["reserve_initial_cents"]
    held = run["reserve_held_cents"]
    liquidated = run["reserve_liquidated_cents"]
    assert initial == held + liquidated, (
        "reserve conservation broken: %d != %d + %d" % (initial, held, liquidated)
    )
