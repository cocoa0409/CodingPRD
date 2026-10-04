"""Corner queue B — section: entities.

Creation, retrieval, listing, required fields, computed fields and defaults for the
hub, print site, print market, print route and market-type constraints.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_hub_with_clock,
    create_print_site_response,
    create_site,
    create_region,
    create_market,
    create_route,
    create_market_response,
    get_print_site,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    NON_EXISTENT_UUID,
    TEST_USERS,
)
from test_helpers.constants import (CLOCK_2026_09_01, SITE_CED,
                                    SITE_CED_NON_DEFAULT_SLOT, CLOCK_2026_09_30)

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_hub_create_returns_every_declared_field_and_opens_posture():
    """PRD §3.1: "On creation the hub's `press_posture` begins at `OPEN`, its
    `legal_notice_block` begins false, and its `min_on_time_ratio_pct` — the
    statutory floor described in §2.9 — defaults to 90 unless supplied."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/region_hub_create_returns_every_declared_field_and_opens_posture
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)

    response = api.create_hub(
        {
            "name": "North Ridge Media Group",
            "total_newsroom_headcount": 30,
            "max_print_tonnage_budget_cents": 5000000,
            "transfer_cost_ceiling_cents": 20000,
        },
        ADMIN,
    )
    hub = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    assert is_valid_uuid(hub["id"])
    assert hub["name"] == "North Ridge Media Group"
    assert hub["total_newsroom_headcount"] == 30
    assert hub["press_posture"] == "OPEN"
    assert hub["legal_notice_block"] is False
    assert hub["min_on_time_ratio_pct"] == 90
    assert hub["unassigned_headcount"] == 30
    assert hub["version"] == 1


def test_print_site_get_round_trips_every_configuration_field():
    """PRD §3.1: "A site also declares how many `distinct_shifts_per_night` it runs,
    defaulting to 4, and a `loading_slot_minutes` dock window, defaulting to 30."
    PRD §3.1: "the system derives `capacity_copies` as the number of presses
    multiplied by the number of shifts per night, multiplied by eight hours,
    multiplied by the per-press hourly throughput".

    Design: Corner/entities/print_site_get_round_trips_every_configuration_field
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)
    site = create_site(hub["id"], **SITE_CED_NON_DEFAULT_SLOT)

    fetched = validate_success(api.get_print_site(site["id"], PRINT_OPS), 200)

    assert fetched["code"] == "CED"
    assert fetched["press_units"] == 1
    assert fetched["shifts_per_night"] == 2
    assert fetched["allocation_method"] == "PROPORTIONAL"
    assert fetched["distinct_shifts_per_night"] == 2
    assert fetched["loading_slot_minutes"] == 45, (
        "the non-default loading slot must round-trip unchanged"
    )
    assert fetched["capacity_copies"] == 400000
    assert fetched["capacity_remaining_copies"] == 400000


def test_print_markets_list_paginates_and_reports_total_count():
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it defaults
    to 10, its minimum accepted value is 1 and its maximum is 100."
    PRD §2.3: "The pagination fields `limit`, `offset`, `total_count` and `has_more`
    are carried in the `meta` object of every list response."

    Design: Corner/entities/print_markets_list_paginates_and_reports_total_count
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)
    region = create_region(hub["id"])
    for name in ("Riverton", "Fallow", "Eastport"):
        create_market(region["id"], name=name)

    first_page = api.list_print_markets(
        PRINT_OPS, {"region_id": region["id"], "limit": 2, "offset": 0})
    rows, meta = validate_paginated(first_page)

    assert len(rows) == 2, f"limit=2 must return exactly two rows, got {len(rows)}"
    assert meta["total_count"] == 3, (
        f"total_count counts the filtered set, got {meta['total_count']}"
    )
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert rows[0]["created_at"] <= rows[1]["created_at"], (
        "list endpoints return resources in ascending creation order"
    )

    second_page = api.list_print_markets(
        PRINT_OPS, {"region_id": region["id"], "limit": 2, "offset": 2})
    rows2, meta2 = validate_paginated(second_page)

    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_print_market_get_unknown_id_returns_resource_not_found():
    """PRD §2.6: "the first segment that does not resolve to an existing row is the
    one reported, as `ERR_RESOURCE_NOT_FOUND` (HTTP 404) — never a later one."
    PRD §2.6: "Paths in this API are hierarchical, and path parameters are uniformly
    named `{id}` at each level."

    Design: Corner/entities/print_market_get_unknown_id_returns_resource_not_found
    """
    create_hub_with_clock(CLOCK_2026_09_01)

    response = api.get_print_market(NON_EXISTENT_UUID, PRINT_OPS)
    body = response.json()

    assert response.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_RESOURCE_NOT_FOUND"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


def test_region_create_without_name_returns_invalid_request():
    """PRD §2.12: "a missing or empty required name or code is refused as
    `ERR_INVALID_REQUEST` (HTTP 400) before the uniqueness check is reached."
    PRD §2.11: "a malformed body is reported as `ERR_INVALID_REQUEST` (HTTP 400)
    before any identity check runs."

    Design: Corner/entities/region_create_without_name_returns_invalid_request
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)

    response = api.create_region(
        hub["id"],
        {"daily_headcount_floor": 4, "daily_headcount_cap": 10, "allocation_priority": 1},
        PRINT_OPS,
    )

    error = validate_error(response, "ERR_INVALID_REQUEST")
    assert response.status_code == 400
    assert error["error_id"] == "ERR_INVALID_REQUEST"

    rows = validate_success(api.list_regions(hub["id"], PRINT_OPS), 200)
    assert rows == [], "no region may be written when the request is refused"


def test_print_site_capacity_fields_are_computed_and_input_is_ignored():
    """PRD §3.1: "From these the system derives `capacity_copies` as the number of
    presses multiplied by the number of shifts per night, multiplied by eight hours,
    multiplied by the per-press hourly throughput".
    PRD §3.1: "and reports `capacity_remaining_copies` as the difference, which is
    never negative."

    Design: Corner/entities/print_site_capacity_fields_are_computed_and_input_is_ignored
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)

    created = validate_success(
        api.create_print_site(
            hub["id"],
            {
                "code": "KOT",
                "press_units": 2,
                "shifts_per_night": 2,
                "copies_per_hour_per_press": 25000,
                "max_concurrent_departures": 2,
                "allocation_method": "PRIORITY",
                "capacity_copies": 999999999,
            },
            PRINT_OPS,
        ),
        201,
    )

    assert created["capacity_copies"] == 800000, (
        f"capacity_copies is derived, not accepted: got {created['capacity_copies']}"
    )
    assert created["capacity_remaining_copies"] == 800000
    assert created["allocated_copies"] == 0
    assert created["annualized_savings_cents"] == 180000.00
    assert created["realized_savings_cents"] == 180000.00
    assert created["savings_divergence_cents"] == 0.00


def test_print_route_transit_and_buffer_defaults_applied():
    """PRD §3.2: "It may also set the `publication_deadline_utc` wall time by which
    its edition must be delivery-ready (defaulting to 05:30 UTC), an
    `on_time_margin_minutes` slack (defaulting to 30)".
    PRD §3.3: "The route's `distance_miles` is its `transit_minutes` divided by
    sixty, multiplied by fifty-five miles per hour, rounded half up to two decimals."

    Design: Corner/entities/print_route_transit_and_buffer_defaults_applied
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"])

    route = get_success_data(api.create_print_route(
        site["id"],
        {
            "destination_market_id": market["id"],
            "transit_minutes": 120,
            "dispatch_cutoff_utc": "01:00",
            "is_direct_hop": True,
        },
        PRINT_OPS))
    refreshed_market = get_success_data(api.get_print_market(market["id"], PRINT_OPS))

    assert route["transit_minutes"] == 120
    assert route["dispatch_cutoff_utc"] == "01:00"
    assert refreshed_market["publication_deadline_utc"] == "05:30", (
        f"the deadline defaults to 05:30, got "
        f"{refreshed_market['publication_deadline_utc']}"
    )
    assert refreshed_market["on_time_margin_minutes"] == 30, (
        f"the margin defaults to 30, got {refreshed_market['on_time_margin_minutes']}"
    )
    assert route["distance_miles"] == 110.00
    assert route["marginal_mileage_cost"] == 90.00, (
        "with zero stops the transport cost is the mileage charge alone"
    )
    assert route["stops_per_night"] == 0


def test_market_create_rejects_an_out_of_range_frequency_and_unknown_enum():
    """PRD §3.2: "and its current `print_edition_per_week` between 1 and 7".
    PRD §3.2: "and the `single_copy_market_rule` it follows (defaulting to
    `carrier`)."

    Design: Corner/entities/subscriber_contract_has_no_lifecycle_delete_and_rejects_bad_enum
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)
    region = create_region(hub["id"])

    response = api.create_print_market(
        region["id"],
        {
            "name": "Riverton",
            "per_copy_revenue_cents": 45,
            "daily_route_cost_ceiling_cents": 9000,
            "weighted_demand_units": 7000,
            "print_edition_per_week": 9,
            "single_copy_market_rule": "carrier",
        },
        PRINT_OPS,
    )

    error = validate_error(response, "ERR_INVALID_REQUEST")
    assert response.status_code == 400
    assert error["error_id"] == "ERR_INVALID_REQUEST"

    rows = validate_success(
        api.list_print_markets(PRINT_OPS, {"region_id": region["id"]}), 200)
    assert rows == [], "no market row may be written for an out-of-range frequency"

    bad_enum = api.create_print_market(
        region["id"],
        {
            "name": "Riverton",
            "per_copy_revenue_cents": 45,
            "daily_route_cost_ceiling_cents": 9000,
            "weighted_demand_units": 7000,
            "print_edition_per_week": 7,
            "single_copy_market_rule": "streetcorner",
        },
        PRINT_OPS,
    )
    assert bad_enum.status_code in (400, 409), (
        f"an enum member outside the declared set must be refused, got "
        f"{bad_enum.status_code}"
    )