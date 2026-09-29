"""Domain assertions layered on top of the framework validators.

Everything here is derived from PRD 2.2 (envelope), 2.3 (pagination),
2.4 (identity, instants, version) and 2.6 (money).
"""

import re
from typing import Any, Dict, List, Optional, Sequence

import requests

from prd_bench_local_runner.testing import is_valid_uuid

from .api_client import canonicalise_response_instant
from .constants import END_OF_DAY

_THREE_DIGIT_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ---------------------------------------------------------------------------
# PRD 2.3 - list validators.  Both shapes are provided; PRD 2.3 declares that
# *every* collection endpoint of this service carries the four pagination
# fields in ``meta``, so ``validate_paginated`` from the framework is the one
# tests use.  ``validate_unpaginated`` exists for any endpoint that turns out
# to return a bare array, so that a shared-helper assumption can never be the
# reason a test fails.
# ---------------------------------------------------------------------------
def validate_unpaginated(response: requests.Response) -> List[Any]:
    """Validate a list response that carries no pagination metadata."""
    assert response.status_code == 200, (
        "Expected 200 for list response, got %s: %s"
        % (response.status_code, response.text)
    )
    body = response.json()
    assert "data" in body, "Missing 'data'"
    assert isinstance(body["data"], list), "'data' must be an array"
    return body["data"]


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """PRD 2.3: ``limit``, ``offset``, ``total_count`` and ``has_more`` in meta."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, "meta.%s missing from list envelope" % field
    if limit is not None:
        assert meta["limit"] == limit, "meta.limit %s != %s" % (meta["limit"], limit)
    if offset is not None:
        assert meta["offset"] == offset, (
            "meta.offset %s != %s" % (meta["offset"], offset)
        )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            "meta.total_count %s != %s" % (meta["total_count"], total_count)
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            "meta.has_more %s != %s" % (meta["has_more"], has_more)
        )


def assert_error_meta_is_minimal(response: requests.Response) -> None:
    """PRD 2.2: an error ``meta`` contains only the two request fields."""
    meta = response.json()["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        "error meta must carry only api_request_id and api_request_timestamp, got %s"
        % sorted(meta.keys())
    )


def error_payload_of(response: requests.Response) -> Dict[str, Any]:
    """PRD 2.2: the error payload lives in ``data``, carrying exactly
    ``error_id`` and ``message``.  This is the *only* place in the suite that
    unwraps an error envelope, so no test can double-unwrap it."""
    return response.json()["data"]


def error_id_of(response: requests.Response) -> str:
    """The winning ``error_id`` of a rejected request (PRD 2.2)."""
    return error_payload_of(response)["error_id"]


def assert_request_id_prefixed(response: requests.Response) -> None:
    """PRD 2.2: ``meta.api_request_id`` begins with ``req_``."""
    request_id = response.json()["meta"]["api_request_id"]
    assert request_id.startswith("req_"), (
        "meta.api_request_id must start with 'req_', got %r" % request_id
    )


# ---------------------------------------------------------------------------
# PRD 2.4 - identity, instants and version counters
# ---------------------------------------------------------------------------
def assert_server_minted_id(value: Any) -> None:
    """PRD 2.4: ``id`` is a UUID with no type prefix of any kind."""
    assert isinstance(value, str), "id must be a string, got %r" % (value,)
    assert is_valid_uuid(value), "id must be a bare UUID, got %r" % value


def assert_instant_format(value: Any, field: str = "instant") -> None:
    """PRD 2.4: computed instants carry exactly three fractional-second digits."""
    assert isinstance(value, str), "%s must be a string, got %r" % (field, value)
    assert _THREE_DIGIT_INSTANT.match(value), (
        "%s must be ISO 8601 UTC with exactly three fractional digits, got %r"
        % (field, value)
    )


def assert_instant_eq(actual: Optional[str], expected: Optional[str], field: str = "instant") -> None:
    """Compare two instants after canonicalising sub-second width."""
    assert canonicalise_response_instant(actual) == canonicalise_response_instant(
        expected
    ), "%s: expected %r, got %r" % (field, expected, actual)


def assert_end_of_day(value: Any, field: str = "deadline") -> None:
    """PRD 2.4: every computed deadline lands on ``23:59:59.999Z``."""
    assert_instant_format(value, field)
    assert value.endswith(END_OF_DAY), (
        "%s must land on the last millisecond of its date, got %r" % (field, value)
    )


def assert_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """PRD 2.4: ``id``, ``created_at``, ``updated_at`` and ``version``."""
    assert_server_minted_id(data.get("id"))
    assert_instant_format(data.get("created_at"), "created_at")
    assert_instant_format(data.get("updated_at"), "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            "version %s != %s" % (data["version"], expected_version)
        )


def assert_light_fields(data: Dict[str, Any]) -> None:
    """PRD 2.4: a car notification and a piece of dispute evidence carry only
    ``id`` and ``created_at`` - neither an ``updated_at`` nor a ``version``."""
    assert_server_minted_id(data.get("id"))
    assert_instant_format(data.get("created_at"), "created_at")
    assert "updated_at" not in data, (
        "this resource must not carry updated_at, got %r" % data.get("updated_at")
    )
    assert "version" not in data, (
        "this resource must not carry version, got %r" % data.get("version")
    )


def assert_version_is(data: Dict[str, Any], expected: int) -> None:
    assert data["version"] == expected, (
        "expected version %s, got %s" % (expected, data["version"])
    )


# ---------------------------------------------------------------------------
# PRD 2.6 - money discipline
# ---------------------------------------------------------------------------
def assert_integer_cents(value: Any, field: str) -> None:
    """PRD 2.6: all monetary amounts are integer counts of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        "%s must be an integer number of cents, got %r (%s)"
        % (field, value, type(value).__name__)
    )


def assert_charge_money_invariant(charge: Dict[str, Any]) -> None:
    """PRD 2.6: ``credit_applied_cents <= gross_amount_cents`` and
    ``net_amount_cents == gross_amount_cents - credit_applied_cents``."""
    for field in ("gross_amount_cents", "credit_applied_cents", "net_amount_cents"):
        assert_integer_cents(charge[field], field)
    assert charge["credit_applied_cents"] <= charge["gross_amount_cents"], (
        "credit_applied_cents %s exceeds gross_amount_cents %s"
        % (charge["credit_applied_cents"], charge["gross_amount_cents"])
    )
    assert (
        charge["net_amount_cents"]
        == charge["gross_amount_cents"] - charge["credit_applied_cents"]
    ), (
        "net_amount_cents %s != gross %s - credit %s"
        % (
            charge["net_amount_cents"],
            charge["gross_amount_cents"],
            charge["credit_applied_cents"],
        )
    )


def assert_invoice_money_invariant(invoice: Dict[str, Any]) -> None:
    """PRD 2.6: ``total_net_cents + total_credit_cents == total_gross_cents``."""
    for field in ("total_gross_cents", "total_credit_cents", "total_net_cents"):
        assert_integer_cents(invoice[field], field)
    assert (
        invoice["total_net_cents"] + invoice["total_credit_cents"]
        == invoice["total_gross_cents"]
    ), (
        "invoice money invariant broken: net %s + credit %s != gross %s"
        % (
            invoice["total_net_cents"],
            invoice["total_credit_cents"],
            invoice["total_gross_cents"],
        )
    )


# ---------------------------------------------------------------------------
# PRD 2.3 - list ordering
# ---------------------------------------------------------------------------
def assert_ordered_by_created_at(rows: Sequence[Dict[str, Any]]) -> None:
    """PRD 2.3: every list is ordered by ``created_at`` ascending with ``id``
    ascending as the tie-break."""
    keys = [(row["created_at"], row["id"]) for row in rows]
    assert keys == sorted(keys), "list is not ordered by (created_at, id) ascending"


def ids_of(rows: Sequence[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def find_by_id(rows: Sequence[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    for row in rows:
        if row["id"] == row_id:
            return row
    raise AssertionError("id %s not present in %s" % (row_id, ids_of(rows)))


# ---------------------------------------------------------------------------
# Field-set assertions
# ---------------------------------------------------------------------------
def assert_fields_present(data: Dict[str, Any], fields: Sequence[str]) -> None:
    missing = [f for f in fields if f not in data]
    assert not missing, "missing declared fields: %s" % missing


def assert_subset_equal(data: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert every key/value pair in ``expected`` matches ``data``."""
    mismatches = {
        key: (expected[key], data.get(key))
        for key in expected
        if data.get(key) != expected[key]
    }
    assert not mismatches, "field mismatches (expected, actual): %s" % mismatches


# ---------------------------------------------------------------------------
# PRD 2.5 - the three day calendars.  These walkers let a test compute the
# instant it expects rather than hard-coding an opaque literal, and they are
# written to the letter of PRD 2.5: "for n equal to zero the answer is the
# given date itself".
# ---------------------------------------------------------------------------
import datetime as _dt


def _as_date(value: str) -> _dt.date:
    """Accept either a bare ``YYYY-MM-DD`` or a full instant."""
    return _dt.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def is_business_date(value: str) -> bool:
    """PRD 2.5: a business date is Monday through Friday UTC, unconditionally."""
    return _as_date(value).weekday() < 5


def is_eligible_date(value: str, weekend_excluded: bool) -> bool:
    """PRD 2.5: an eligible date excludes Saturday and Sunday only when the
    governing tariff sets ``weekend_excluded``."""
    if not weekend_excluded:
        return True
    return _as_date(value).weekday() < 5


def add_business_dates(start: str, n: int) -> str:
    """The ``n``-th business date at or after ``start``.

    ``n == 0`` returns ``start`` itself, per PRD 2.5.  When ``start`` is not
    itself a business date the walk begins at the next one that is.
    """
    current = _as_date(start)
    counted = 0
    while True:
        if current.weekday() < 5:
            if counted == n:
                return current.isoformat()
            counted += 1
        current += _dt.timedelta(days=1)


def business_dates_strictly_after(start: str, n: int) -> str:
    """The ``n``-th business date strictly after ``start`` (PRD 3.8 / 3.9)."""
    current = _as_date(start) + _dt.timedelta(days=1)
    remaining = n
    while True:
        if current.weekday() < 5:
            remaining -= 1
            if remaining == 0:
                return current.isoformat()
        current += _dt.timedelta(days=1)


def add_eligible_dates(start: str, n: int, weekend_excluded: bool) -> str:
    """The ``n``-th eligible date at or after ``start`` (PRD 2.5 / 3.3)."""
    current = _as_date(start)
    counted = 0
    while True:
        if is_eligible_date(current.isoformat(), weekend_excluded):
            if counted == n:
                return current.isoformat()
            counted += 1
        current += _dt.timedelta(days=1)


def add_calendar_days(start: str, n: int) -> str:
    """PRD 3.7: the plain calendar walk used by the invoice dispute window."""
    return (_as_date(start) + _dt.timedelta(days=n)).isoformat()


def end_of(date_str: str) -> str:
    """The last millisecond of a date, the shape every computed deadline takes."""
    return "%sT%s" % (date_str[:10], END_OF_DAY)


def start_of(date_str: str) -> str:
    return "%sT00:00:00.000Z" % date_str[:10]


def calendar_dates_between(start: str, end: str) -> List[str]:
    """Every date in the closed interval ``[start, end]`` (PRD 3.5 storage)."""
    first, last = _as_date(start), _as_date(end)
    out: List[str] = []
    while first <= last:
        out.append(first.isoformat())
        first += _dt.timedelta(days=1)
    return out
