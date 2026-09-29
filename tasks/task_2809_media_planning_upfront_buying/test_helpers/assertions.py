"""Domain assertions for the Media Planning & Upfront Buying API.

The helpers here say one thing each and say it in the vocabulary of the domain:
that a resource carries the identity and audit fields it must, that an
append-only record carries neither an update instant nor a version, that a money
figure is integer cents, that a percentage or index carries the declared number
of decimals, and that two instants denote the same moment whatever fractional
precision each was written with.
"""

from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    REQUEST_ID_PREFIX,
    canonical_instant,
    dec,
)
from .types import (
    APPEND_ONLY_FIELDS,
    COMMON_FIELDS,
    FORBIDDEN_ON_APPEND_ONLY,
    PAGINATION_META_KEYS,
)


# ==========================================================================
# Envelope and identity
# ==========================================================================
def assert_envelope_meta(body: Mapping[str, Any]) -> None:
    """The envelope's meta block carries a prefixed request id and an instant."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith(REQUEST_ID_PREFIX), (
        f"api_request_id must start with '{REQUEST_ID_PREFIX}', "
        f"got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp is not an ISO-8601 instant: "
        f"{meta['api_request_timestamp']!r}"
    )
    assert_millisecond_precision(meta["api_request_timestamp"], "api_request_timestamp")


def assert_millisecond_precision(value: str, field: str = "timestamp") -> None:
    """A timestamp is rendered in UTC with exactly three fractional digits."""
    assert value.endswith("Z"), f"{field} must be a UTC instant ending in Z: {value!r}"
    assert "." in value, f"{field} must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"{field} must carry exactly three fractional digits, got {value!r}"
    )


def assert_common_fields(resource: Mapping[str, Any], expected_version: Optional[int] = None) -> None:
    """A mutable resource carries a UUID id, both instants and a version."""
    for field in COMMON_FIELDS:
        assert field in resource, f"resource is missing the common field {field!r}"
    assert is_valid_uuid(resource["id"]), (
        f"id must be an unprefixed UUID, got {resource['id']!r}"
    )
    assert_millisecond_precision(resource["created_at"], "created_at")
    assert_millisecond_precision(resource["updated_at"], "updated_at")
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_append_only_shape(record: Mapping[str, Any]) -> None:
    """An append-only record carries an id and a creation instant and nothing more."""
    for field in APPEND_ONLY_FIELDS:
        assert field in record, f"append-only record is missing {field!r}"
    assert is_valid_uuid(record["id"]), (
        f"id must be an unprefixed UUID, got {record['id']!r}"
    )
    assert_millisecond_precision(record["created_at"], "created_at")
    for field in FORBIDDEN_ON_APPEND_ONLY:
        assert field not in record, (
            f"an append-only record must not carry {field!r}; got {record.get(field)!r}"
        )


def assert_fields_present(resource: Mapping[str, Any], fields: Iterable[str]) -> None:
    """Every named field is present on the resource."""
    missing = [field for field in fields if field not in resource]
    assert not missing, f"resource is missing declared fields: {missing}"


def assert_version_advanced(before: Mapping[str, Any], after: Mapping[str, Any], by: int = 1) -> None:
    """A mutation moved the version forward by exactly the given step."""
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version'] + by}, got {after['version']}"
    )


def assert_unchanged(before: Mapping[str, Any], after: Mapping[str, Any], fields: Iterable[str]) -> None:
    """None of the named fields moved."""
    for field in fields:
        assert after[field] == before[field], (
            f"{field} was expected to stay {before[field]!r} but became {after[field]!r}"
        )


# ==========================================================================
# Money, audience and precision
# ==========================================================================
def assert_cents(resource: Mapping[str, Any], field: str, expected: int) -> None:
    """A money field holds exactly the expected integer number of cents."""
    actual = resource[field]
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be integer cents, got {type(actual).__name__} {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected} cents, got {actual}"


def assert_impressions(resource: Mapping[str, Any], field: str, expected: int) -> None:
    """An audience field holds exactly the expected whole number of impressions."""
    actual = resource[field]
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be a whole number of impressions, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_decimal_places(value: Any, places: int, field: str = "value") -> None:
    """A numeric figure is carried to at most the declared number of decimals."""
    quantised = dec(value).normalize()
    exponent = quantised.as_tuple().exponent
    actual_places = -exponent if exponent < 0 else 0
    assert actual_places <= places, (
        f"{field} must carry at most {places} decimals, got {value!r}"
    )


def assert_quantity(resource: Mapping[str, Any], field: str, expected: float, places: int) -> None:
    """A percentage, rate or index equals the expected figure at that precision."""
    actual = resource[field]
    assert dec(actual) == dec(expected), (
        f"{field}: expected {expected}, got {actual}"
    )
    assert_decimal_places(actual, places, field)


def assert_pct2(resource: Mapping[str, Any], field: str, expected: float) -> None:
    """A two-decimal percentage or ratio."""
    assert_quantity(resource, field, expected, 2)


def assert_pct4(resource: Mapping[str, Any], field: str, expected: float) -> None:
    """A four-decimal percentage, rate or index."""
    assert_quantity(resource, field, expected, 4)


def assert_close(actual: Any, expected: Any, field: str = "value") -> None:
    """Two numeric figures denote the same decimal quantity."""
    assert dec(actual) == dec(expected), f"{field}: expected {expected}, got {actual}"


# ==========================================================================
# Instants
# ==========================================================================
def assert_instant_equals(actual: str, expected: str, field: str = "timestamp") -> None:
    """Two instants denote the same moment whatever precision each was written with."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected {canonical_instant(expected)}, got {canonical_instant(actual)}"
    )


def assert_instant_field(resource: Mapping[str, Any], field: str, expected: str) -> None:
    """A resource's instant field denotes the expected moment."""
    assert resource[field] is not None, f"{field} was expected to be set"
    assert_instant_equals(resource[field], expected, field)


def assert_null_instant(resource: Mapping[str, Any], field: str) -> None:
    """A resource's instant field is still unset."""
    assert resource[field] is None, f"{field} was expected to be null, got {resource[field]!r}"


# ==========================================================================
# Pagination
# ==========================================================================
def assert_pagination_meta(
    meta: Mapping[str, Any],
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    """A list response's meta block carries the four pagination fields."""
    for key in PAGINATION_META_KEYS:
        assert key in meta, f"list meta is missing {key!r}"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count: expected {expected_total}, got {meta['total_count']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"limit: expected {expected_limit}, got {meta['limit']}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"offset: expected {expected_offset}, got {meta['offset']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"has_more: expected {expected_has_more}, got {meta['has_more']}"
        )


def assert_created_at_ascending(rows: Sequence[Mapping[str, Any]]) -> None:
    """A listing is ordered by creation instant, oldest first."""
    instants = [canonical_instant(row["created_at"]) for row in rows]
    assert instants == sorted(instants), (
        f"rows are not ordered by created_at ascending: {instants}"
    )


def assert_ids_equal(rows: Sequence[Mapping[str, Any]], expected_ids: Sequence[str]) -> None:
    """A listing holds exactly these identifiers in this order."""
    assert [row["id"] for row in rows] == list(expected_ids), (
        f"expected ids {list(expected_ids)}, got {[row['id'] for row in rows]}"
    )


# ==========================================================================
# Axis states
# ==========================================================================
def assert_campaign_axes(
    campaign: Mapping[str, Any],
    plan_status: Optional[str] = None,
    funding_status: Optional[str] = None,
    plan_posture: Optional[str] = None,
) -> None:
    """The campaign's planning, funding and posture axes read as named."""
    if plan_status is not None:
        assert campaign["plan_status"] == plan_status, (
            f"plan_status: expected {plan_status}, got {campaign['plan_status']}"
        )
    if funding_status is not None:
        assert campaign["funding_status"] == funding_status, (
            f"funding_status: expected {funding_status}, got {campaign['funding_status']}"
        )
    if plan_posture is not None:
        assert campaign["plan_posture"] == plan_posture, (
            f"plan_posture: expected {plan_posture}, got {campaign['plan_posture']}"
        )


def assert_buy_axes(
    buy: Mapping[str, Any],
    buy_status: Optional[str] = None,
    stewardship_status: Optional[str] = None,
    settlement_status: Optional[str] = None,
) -> None:
    """The buy's three independent axes read as named."""
    if buy_status is not None:
        assert buy["buy_status"] == buy_status, (
            f"buy_status: expected {buy_status}, got {buy['buy_status']}"
        )
    if stewardship_status is not None:
        assert buy["stewardship_status"] == stewardship_status, (
            f"stewardship_status: expected {stewardship_status}, "
            f"got {buy['stewardship_status']}"
        )
    if settlement_status is not None:
        assert buy["settlement_status"] == settlement_status, (
            f"settlement_status: expected {settlement_status}, "
            f"got {buy['settlement_status']}"
        )


def assert_invoice_axes(
    invoice: Mapping[str, Any],
    client_status: Optional[str] = None,
    seller_status: Optional[str] = None,
) -> None:
    """The invoice's receivable and payable axes read as named."""
    if client_status is not None:
        assert invoice["client_status"] == client_status, (
            f"client_status: expected {client_status}, got {invoice['client_status']}"
        )
    if seller_status is not None:
        assert invoice["seller_status"] == seller_status, (
            f"seller_status: expected {seller_status}, got {invoice['seller_status']}"
        )


def assert_allocation_posture(
    allocation: Mapping[str, Any],
    status: Optional[str] = None,
    posture: Optional[str] = None,
) -> None:
    """The allocation's editability and commitment posture read as named."""
    if status is not None:
        assert allocation["status"] == status, (
            f"allocation status: expected {status}, got {allocation['status']}"
        )
    if posture is not None:
        assert allocation["posture"] == posture, (
            f"allocation posture: expected {posture}, got {allocation['posture']}"
        )


# ==========================================================================
# Cost and ledger invariants
# ==========================================================================
def assert_cost_stack(buy: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    """The buy's whole cost stack agrees with the expected figures."""
    assert_cents(buy, "net_media_cost_cents", expected["net_media_cost_cents"])
    assert_pct4(buy, "commission_rate", expected["commission_rate"])
    assert_cents(buy, "agency_commission_cents", expected["agency_commission_cents"])
    assert_cents(buy, "gross_cost_cents", expected["gross_cost_cents"])
    assert buy["gross_cost_cents"] == (
        buy["net_media_cost_cents"] + buy["agency_commission_cents"]
    ), "gross cost must be the net media cost plus its commission"


def assert_invoice_rollup(invoice: Mapping[str, Any], lines: Sequence[Mapping[str, Any]]) -> None:
    """The invoice rollups equal the per-line figures summed after rounding."""
    assert invoice["line_count"] == len(lines), (
        f"line_count: expected {len(lines)}, got {invoice['line_count']}"
    )
    assert invoice["seller_payable_cents"] == sum(l["line_net_cents"] for l in lines), (
        "seller payable must be the sum of the line net figures"
    )
    assert invoice["agency_commission_cents"] == sum(
        l["line_commission_cents"] for l in lines
    ), "invoice commission must sum the per-line commissions, each already rounded"
    assert invoice["gross_billable_cents"] == sum(l["line_gross_cents"] for l in lines), (
        "gross billable must be the sum of the line gross figures"
    )


def assert_budget_ledger_balances(campaign: Mapping[str, Any]) -> None:
    """The campaign's two budget residues agree with its budget."""
    assert (
        campaign["allocated_budget_cents"] + campaign["unallocated_budget_cents"]
        == campaign["total_budget_cents"]
    ), "allocated plus unallocated must equal the total budget"
    assert (
        campaign["committed_gross_cents"] + campaign["uncommitted_budget_cents"]
        == campaign["total_budget_cents"]
    ), "committed plus uncommitted must equal the total budget"


def assert_avail_conserved(
    forecast: Mapping[str, Any], occupying_projections: Iterable[int]
) -> None:
    """The avail's remaining inventory is its total less the impressions held."""
    held = sum(occupying_projections)
    assert forecast["available_impressions"] == forecast["total_impressions"] - held, (
        f"available_impressions: expected "
        f"{forecast['total_impressions'] - held}, got {forecast['available_impressions']}"
    )


def assert_group_reach(run: Mapping[str, Any], expected: Mapping[str, float]) -> None:
    """The run reports exactly these channel groups with these reach figures."""
    actual: Dict[str, Any] = run["group_reach_pct"]
    assert set(actual) == set(expected), (
        f"group_reach_pct keys: expected {sorted(expected)}, got {sorted(actual)}"
    )
    for group, figure in expected.items():
        assert dec(actual[group]) == dec(figure), (
            f"group_reach_pct[{group}]: expected {figure}, got {actual[group]}"
        )
        assert_decimal_places(actual[group], 4, f"group_reach_pct[{group}]")
