"""Domain assertions layered on the framework validators.

Two things need normalising before an equality check is meaningful:

* an instant may be serialised with or without fractional digits, so
  `assert_instant` compares the two forms at whole-second resolution;
* a money field is a two-decimal quantity, so `assert_money` compares it with an
  absolute tolerance of one hundredth and also proves the precision.
"""

import re

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import (
    MONEY_DP,
    PAGINATION_META_KEYS,
    PCT_DP,
    RATE_DP,
    VERSIONLESS_ENTITIES,
)

_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z?$")


def normalise_instant(value):
    """Reduce an ISO 8601 UTC instant to whole-second resolution."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    match = _INSTANT_RE.match(value)
    assert match, f"not an ISO 8601 UTC instant: {value!r}"
    return match.group(1) + "Z"


def assert_instant(actual, expected, field=""):
    """Compare two instants at whole-second resolution."""
    label = f"{field}: " if field else ""
    assert normalise_instant(actual) == normalise_instant(expected), (
        f"{label}expected instant {expected}, got {actual}"
    )


def assert_money(actual, expected, field=""):
    """A USD field equals `expected` to the cent."""
    label = f"{field}: " if field else ""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label}expected a JSON number for a USD amount, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}expected {expected}, got {actual}"
    )


def assert_decimal_places(value, places, field=""):
    """The serialised value carries no more than `places` decimal digits."""
    label = f"{field}: " if field else ""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label}expected a JSON number, got {value!r}"
    )
    rounded = round(float(value), places)
    assert abs(float(value) - rounded) < 10 ** (-(places + 4)), (
        f"{label}expected at most {places} decimal places, got {value}"
    )


def assert_money_precision(value, field=""):
    assert_decimal_places(value, MONEY_DP, field)


def assert_rate_precision(value, field=""):
    assert_decimal_places(value, RATE_DP, field)


def assert_pct_precision(value, field=""):
    assert_decimal_places(value, PCT_DP, field)


def assert_common_fields(row, entity_name=""):
    """`id` is a UUID, `created_at` an ISO 8601 instant, and unless the entity is
    one of the three reference types, `updated_at` and `version` are present."""
    assert is_valid_uuid(row.get("id")), f"{entity_name} id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"{entity_name} created_at is not ISO 8601: {row.get('created_at')!r}"
    )
    if entity_name in VERSIONLESS_ENTITIES:
        assert "updated_at" not in row, f"{entity_name} must not carry updated_at"
        assert "version" not in row, f"{entity_name} must not carry version"
    else:
        assert is_iso8601_timestamp(row.get("updated_at")), (
            f"{entity_name} updated_at is not ISO 8601: {row.get('updated_at')!r}"
        )
        assert isinstance(row.get("version"), int) and not isinstance(
            row.get("version"), bool
        ), f"{entity_name} version is not an integer: {row.get('version')!r}"
        assert row["version"] >= 1, f"{entity_name} version must start at 1"


def assert_reference_row(row, entity_name):
    """A Territory, ComparableTitle or DistributionRow carries id and created_at only."""
    assert entity_name in VERSIONLESS_ENTITIES, (
        f"{entity_name} is not one of the three version-free resource types"
    )
    assert_common_fields(row, entity_name)


def assert_version(row, expected, entity_name=""):
    assert row.get("version") == expected, (
        f"{entity_name} expected version {expected}, got {row.get('version')}"
    )


def assert_no_id_echo(row, submitted_id):
    """A client-supplied id has no effect."""
    assert row.get("id") != submitted_id, "the client-supplied id was honoured"


# --------------------------------------------------------------------------
# Envelope helpers
# --------------------------------------------------------------------------
def assert_object_response(response, expected_status=200):
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "object", (
        f"expected response_type object, got {body['response_type']!r}"
    )
    return data


def assert_created(response):
    return assert_object_response(response, 201)


def assert_list_response(response, expected_total=None, expected_rows=None):
    """Validate a paginated list and optionally its total_count and page length."""
    rows, meta = validate_paginated(response)
    for key in PAGINATION_META_KEYS:
        assert key in meta, f"list meta is missing {key}"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"expected total_count {expected_total}, got {meta['total_count']}"
        )
    if expected_rows is not None:
        assert len(rows) == expected_rows, (
            f"expected {expected_rows} rows on the page, got {len(rows)}"
        )
    return rows, meta


def assert_page_window(meta, limit, offset, total_count, has_more):
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_single_resource_meta(response):
    """A single-resource response omits all four pagination fields."""
    meta = response.json()["meta"]
    for key in PAGINATION_META_KEYS:
        assert key not in meta, f"single-resource meta must omit {key}"


def assert_empty_collection(response):
    rows, meta = assert_list_response(response, expected_total=0, expected_rows=0)
    assert meta["has_more"] is False, "an empty collection must report has_more false"
    return rows


# --------------------------------------------------------------------------
# Domain assertions
# --------------------------------------------------------------------------
def assert_film_counters(
    film,
    committed=None,
    collected=None,
    gap=None,
    published_count=None,
    licensed_count=None,
    sales_status=None,
):
    if committed is not None:
        assert_money(film["total_mg_committed_usd"], committed, "total_mg_committed_usd")
    if collected is not None:
        assert_money(film["total_mg_collected_usd"], collected, "total_mg_collected_usd")
    if gap is not None:
        assert_money(film["financing_gap_usd"], gap, "financing_gap_usd")
    if published_count is not None:
        assert film["published_territory_count"] == published_count, (
            f"expected published_territory_count {published_count}, "
            f"got {film['published_territory_count']}"
        )
    if licensed_count is not None:
        assert film["licensed_territory_count"] == licensed_count, (
            f"expected licensed_territory_count {licensed_count}, "
            f"got {film['licensed_territory_count']}"
        )
    if sales_status is not None:
        assert film["sales_status"] == sales_status, (
            f"expected sales_status {sales_status}, got {film['sales_status']}"
        )


def assert_contract_axes(contract, negotiation=None, delivery=None, collection=None):
    """The three status axes advance independently."""
    if negotiation is not None:
        assert contract["negotiation_status"] == negotiation, (
            f"expected negotiation_status {negotiation}, "
            f"got {contract['negotiation_status']}"
        )
    if delivery is not None:
        assert contract["delivery_status"] == delivery, (
            f"expected delivery_status {delivery}, got {contract['delivery_status']}"
        )
    if collection is not None:
        assert contract["collection_status"] == collection, (
            f"expected collection_status {collection}, got {contract['collection_status']}"
        )


def assert_buyer_exposure(buyer, gross=None, net=None):
    if gross is not None:
        assert_money(buyer["outstanding_exposure_usd"], gross, "outstanding_exposure_usd")
    if net is not None:
        assert_money(buyer["net_unpaid_exposure_usd"], net, "net_unpaid_exposure_usd")


def assert_account_invariant(account):
    """total_receipts_usd minus total_distributed_usd minus balance_usd is exactly zero."""
    residual = (
        round(float(account["total_receipts_usd"]), 2)
        - round(float(account["total_distributed_usd"]), 2)
        - round(float(account["balance_usd"]), 2)
    )
    assert abs(residual) < 0.005, (
        "receipts less distributions less balance must be exactly zero, got "
        f"{residual} from {account}"
    )


def assert_account_counters(
    account, receipts=None, distributed=None, balance=None, run_count=None
):
    if receipts is not None:
        assert_money(account["total_receipts_usd"], receipts, "total_receipts_usd")
    if distributed is not None:
        assert_money(account["total_distributed_usd"], distributed, "total_distributed_usd")
    if balance is not None:
        assert_money(account["balance_usd"], balance, "balance_usd")
    if run_count is not None:
        assert account["run_count"] == run_count, (
            f"expected run_count {run_count}, got {account['run_count']}"
        )
    assert_account_invariant(account)


def assert_valuation_prices(valuation, estimate, ask, floor):
    assert_money(valuation["estimate_usd"], estimate, "estimate_usd")
    assert_money(valuation["ask_price_usd"], ask, "ask_price_usd")
    assert_money(valuation["floor_price_usd"], floor, "floor_price_usd")
    for field in ("estimate_usd", "ask_price_usd", "floor_price_usd"):
        assert_money_precision(valuation[field], field)


def assert_facility_figures(
    facility, collateral=None, advance=None, drawn=None, outstanding=None, status=None
):
    if collateral is not None:
        assert_money(facility["eligible_collateral_usd"], collateral, "eligible_collateral_usd")
    if advance is not None:
        assert_money(facility["advance_amount_usd"], advance, "advance_amount_usd")
    if drawn is not None:
        assert_money(facility["drawn_amount_usd"], drawn, "drawn_amount_usd")
    if outstanding is not None:
        assert_money(facility["outstanding_debt_usd"], outstanding, "outstanding_debt_usd")
    if status is not None:
        assert facility["status"] == status, (
            f"expected facility status {status}, got {facility['status']}"
        )


def assert_allocations(run, expected_amounts, tier_count=None):
    """The allocations array has one entry per tier, ordered by tier_order ascending,
    with the given amounts."""
    allocations = run["allocations"]
    if tier_count is not None:
        assert len(allocations) == tier_count, (
            f"the allocations array must hold one entry per tier: expected "
            f"{tier_count}, got {len(allocations)}"
        )
    assert len(allocations) == len(expected_amounts), (
        f"expected {len(expected_amounts)} allocations, got {len(allocations)}"
    )
    for index, (allocation, expected) in enumerate(zip(allocations, expected_amounts)):
        assert_money(allocation["amount_usd"], expected, f"allocations[{index}].amount_usd")
        for key in ("tier_id", "tier_type", "recipient_name", "amount_usd"):
            assert key in allocation, f"allocations[{index}] is missing {key}"


def assert_tier(tier, recouped=None, cap=None, status=None):
    if recouped is not None:
        assert_money(tier["recouped_usd"], recouped, "recouped_usd")
    if cap is not None:
        assert_money(tier["cap_usd"], cap, "cap_usd")
    if status is not None:
        assert tier["status"] == status, (
            f"expected tier status {status}, got {tier['status']}"
        )


def find_by(rows, **criteria):
    """The single row matching every criterion."""
    matches = [
        row for row in rows if all(row.get(key) == value for key, value in criteria.items())
    ]
    assert len(matches) == 1, f"expected exactly one row matching {criteria}, got {matches}"
    return matches[0]


def ordered_by(rows, field):
    return [row[field] for row in rows]
