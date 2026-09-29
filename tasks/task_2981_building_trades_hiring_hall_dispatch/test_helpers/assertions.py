"""
Domain assertions for the Building Trades Hiring Hall Dispatch API.

Thin wrappers over the shared envelope validators plus the shape checks §2.2,
§2.3 and §2.4 make contractual. The success wrappers return the unwrapped
`data` payload, so nothing downstream indexes `["data"]` a second time.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant, parse_instant
from .api_errors import ERROR_HTTP_STATUS
from .constants import (
    COMMON_FIELDS_FULL,
    COMMON_FIELDS_REDUCED,
    PAGINATION_META_FIELDS,
)

# ─── Success and error entry points ───────────────────────────────────────────


def expect_created(response) -> Dict[str, Any]:
    """§4: creation of a new persisted resource answers with HTTP 201."""
    return validate_success(response, 201)


def expect_ok(response) -> Dict[str, Any]:
    """§4: every read, list, state change, clock set and sweep answers with 200."""
    return validate_success(response, 200)


def expect_error(response, error_id: str, status: Optional[int] = None) -> Dict[str, Any]:
    """
    Assert the §5 error code, cross-checking the HTTP status from the catalogue.

    Passing `status` explicitly is only needed when a test wants the status to
    be asserted independently of the registered mapping.
    """
    return validate_error(response, error_id, status or ERROR_HTTP_STATUS.get(error_id))


def expect_one_of(response, error_ids: Sequence[str]) -> str:
    """For outcomes the PRD leaves to more than one acceptable code."""
    return validate_error_is_one_of(response, list(error_ids))


# ─── Envelope shape (§2.2) ────────────────────────────────────────────────────


def assert_envelope_meta(response) -> Dict[str, Any]:
    """`api_request_id` starts with `req_`; the timestamp carries three digits."""
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    stamp = meta["api_request_timestamp"]
    assert is_iso8601_timestamp(stamp), f"meta.api_request_timestamp malformed: {stamp!r}"
    assert stamp.endswith("Z") and len(stamp.split(".")[-1]) == 4, (
        "meta.api_request_timestamp must carry exactly three fractional digits: "
        f"{stamp!r}"
    )
    return meta


def assert_error_meta_is_minimal(response) -> None:
    """§2.2: an error `meta` carries only the request id and the timestamp."""
    meta = response.json()["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"Error meta must carry only the two request fields, got {sorted(meta.keys())}"
    )


# ─── List reads: paginated and unpaginated (§2.3) ──────────────────────────────


def validate_list(response) -> Tuple[List[Any], Dict[str, Any]]:
    """
    A collection endpoint: §2.3 requires all four pagination fields in `meta`.

    Returns the row list and the meta dict.
    """
    rows, meta = validate_paginated(response)
    assert isinstance(rows, list), "A list endpoint must return an array in data"
    return rows, meta


def validate_unpaginated(response, expected_status: int = 200) -> Any:
    """
    A read whose payload is an array but which declares no pagination fields.

    Used where the PRD describes a computed projection rather than a collection
    page, so that the four §2.3 fields are not demanded of it.
    """
    data = validate_success(response, expected_status)
    return data


def assert_pagination(meta: Dict[str, Any], limit: int, offset: int, total: int,
                      has_more: bool) -> None:
    """§2.3: `limit`/`offset` echo the page, `total_count` counts the filtered set."""
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total, (
        f"Expected total_count {total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_single_read_omits_pagination(response) -> None:
    """§2.3: single-resource reads omit `limit`, `offset`, `total_count`, `has_more`."""
    meta = response.json()["meta"]
    present = [field for field in PAGINATION_META_FIELDS if field in meta]
    assert not present, (
        f"A single-resource read must omit the pagination fields, found {present}"
    )


# ─── Identity and audit columns (§2.4) ────────────────────────────────────────


def assert_full_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None
                              ) -> None:
    """The ten resources of §2.4 carry id, created_at, updated_at and version."""
    for field in COMMON_FIELDS_FULL:
        assert field in data, f"Missing common field {field!r}"
    assert is_valid_uuid(data["id"]), f"id must be a bare UUID: {data['id']!r}"
    assert_instant_shape(data["created_at"])
    assert_instant_shape(data["updated_at"])
    assert isinstance(data["version"], int), "version must be an integer"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_reduced_common_fields(data: Dict[str, Any]) -> None:
    """A skill endorsement and a ledger entry carry only id and created_at."""
    for field in COMMON_FIELDS_REDUCED:
        assert field in data, f"Missing common field {field!r}"
    assert is_valid_uuid(data["id"]), f"id must be a bare UUID: {data['id']!r}"
    assert_instant_shape(data["created_at"])
    assert "updated_at" not in data, "A reduced-shape record must carry no updated_at"
    assert "version" not in data, "A reduced-shape record must carry no version"


def assert_bare_uuid(value: str) -> None:
    """§2.4: an `id` is a server-minted UUID with no type prefix of any kind."""
    assert is_valid_uuid(value), f"Not a bare UUID: {value!r}"


def assert_instant_shape(value: str) -> None:
    """§2.4: an instant is ISO 8601 UTC with exactly three fractional digits."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC instant: {value!r}"
    assert "." in value and len(value.split(".")[-1]) == 4, (
        f"Instant must carry exactly three fractional digits: {value!r}"
    )


def assert_instant_equals(actual: Optional[str], expected: Optional[str],
                           label: str = "instant") -> None:
    """Compare two instants on the moment they denote, to the millisecond."""
    if expected is None:
        assert actual is None, f"Expected {label} to be null, got {actual!r}"
        return
    assert actual is not None, f"Expected {label} == {expected}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_instant_order(earlier: str, later: str) -> None:
    """Assert a strict ordering between two instants."""
    assert parse_instant(earlier) < parse_instant(later), (
        f"Expected {earlier} to precede {later}"
    )


# ─── Money and hours (§2.9) ───────────────────────────────────────────────────


def assert_integer_money(value: Any, label: str = "cents") -> None:
    """§2.9: money is whole cents as a JSON number, never a string or a float."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_integer_hours(value: Any, label: str = "hours") -> None:
    """§2.9: hours are whole hours as a JSON number."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of hours, got {value!r}"
    )


def round_half_up_bp(amount: int, factor_bp: int, scale: int = 10000) -> int:
    """
    §2.9's proportional rule: multiply by basis points, divide by the scale,
    and round half up so an exact half rounds away from zero.
    """
    numerator = amount * factor_bp
    quotient, remainder = divmod(numerator, scale)
    if remainder * 2 >= scale:
        quotient += 1
    return quotient


# ─── Entity assertions ────────────────────────────────────────────────────────


def assert_registration_on_book(data: Dict[str, Any], position: Optional[int] = None,
                                 demotions: Optional[int] = None) -> None:
    """A `REGISTERED` row carries a one-based `position_number` (§3.3)."""
    assert data["status"] == "REGISTERED", (
        f"Expected registration REGISTERED, got {data['status']}"
    )
    assert data["removal_reason"] is None, (
        "removal_reason is null while the status is REGISTERED"
    )
    if position is not None:
        assert data["position_number"] == position, (
            f"Expected position_number {position}, got {data['position_number']}"
        )
    if demotions is not None:
        assert data["demotion_count"] == demotions, (
            f"Expected demotion_count {demotions}, got {data['demotion_count']}"
        )


def assert_registration_off_book(data: Dict[str, Any], status: str,
                                  removal_reason: Optional[str] = None) -> None:
    """§3.3: `position_number` is null whenever the status is not `REGISTERED`."""
    assert data["status"] == status, f"Expected status {status}, got {data['status']}"
    assert data["position_number"] is None, (
        f"position_number must be null when status is {status}, "
        f"got {data['position_number']}"
    )
    if removal_reason is not None:
        assert data["removal_reason"] == removal_reason, (
            f"Expected removal_reason {removal_reason}, got {data['removal_reason']}"
        )


def assert_slot_conservation(job_request: Dict[str, Any], referrals: List[Dict[str, Any]],
                              slot_kind: str, requested: int) -> None:
    """
    §3.5: the open counter is the requested count minus the referrals of that
    slot kind whose status is `ISSUED` or `ACCEPTED`, so the two always sum to
    the headcount originally requested.
    """
    open_field = (
        "open_journeyworker_slots"
        if slot_kind == "JOURNEYWORKER"
        else "open_apprentice_slots"
    )
    committed = [
        row
        for row in referrals
        if row["slot_kind"] == slot_kind and row["status"] in ("ISSUED", "ACCEPTED")
    ]
    total = job_request[open_field] + len(committed)
    assert total == requested, (
        f"{open_field} ({job_request[open_field]}) plus committed {slot_kind} "
        f"referrals ({len(committed)}) must equal the {requested} requested, got {total}"
    )


def assert_ordinal_block(rows: List[Dict[str, Any]]) -> List[int]:
    """
    §3.4: surviving rows are renumbered 1 through `registered_count` with no
    holes. Returns the sorted ordinals so callers can assert the permutation.
    """
    ordinals = sorted(row["position_number"] for row in rows)
    assert ordinals == list(range(1, len(rows) + 1)), (
        f"Ordinals must form the block 1..{len(rows)} with no holes, got {ordinals}"
    )
    return ordinals


def find_row(rows: List[Dict[str, Any]], key: str, value: Any) -> Dict[str, Any]:
    """Locate exactly one row in a list payload by a field value."""
    matches = [row for row in rows if row.get(key) == value]
    assert len(matches) == 1, (
        f"Expected exactly one row with {key} == {value!r}, found {len(matches)}"
    )
    return matches[0]


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    """Project the `id` of every row, order preserved."""
    return [row["id"] for row in rows]
