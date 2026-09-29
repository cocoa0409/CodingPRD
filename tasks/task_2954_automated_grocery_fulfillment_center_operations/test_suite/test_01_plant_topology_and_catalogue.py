"""Standing plant, catalogue and the shopper's basket.

Nothing can be picked in the fulfillment centre until the site administrator has
described the building: the delivery routes the vans drive, the dock bays they
load from, the robotic grid zones that hold the stock and the pick stations
where totes are filled, and then the catalogue of groceries that live in those
zones together with the delivery slots and shopper accounts that hang off each
route. These tests walk that registration surface item by item — what a fresh
route, bay, zone, station, SKU, maintenance window, delivery slot and shopper
account look like the instant they come into existence, which registrations the
service refuses outright, how the catalogue is browsed and paged, and finally
how a shopper opens a basket and prices the first line into it while the money
figures deliberately stay open until a delivery slot has actually been booked.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_common_fields,
    assert_customer_account_shape,
    assert_customer_order_shape,
    assert_delivery_route_shape,
    assert_delivery_slot_shape,
    assert_field_absent_or_null,
    assert_grid_zone_shape,
    assert_instant_equals,
    assert_inventory_sku_shape,
    assert_int_field,
    assert_maintenance_window_shape,
    assert_money,
    assert_order_line_shape,
    assert_order_statuses,
    assert_pick_station_shape,
    assert_sku_ledger,
    assert_slot_ledger,
    assert_station_status_matches_count,
    assert_status,
    assert_surge_multiplier,
    assert_version_is,
    list_items_and_meta,
    only_item,
    read_object,
)
from test_helpers.types import (
    BillingStatus,
    FulfillmentStatus,
    GridZoneStatus,
    LineStatus,
    LoyaltyTier,
    MaintenanceWindowStatus,
    PickStationStatus,
    SubstitutionResolution,
    TemperatureZone,
)


def test_registering_a_delivery_route_persists_every_declared_parameter(
    api, admin_headers
):
    """A route registration stores the van capacity, the pre-surge fee and the per-kilometre cost exactly as submitted.

    Cites the requirement it rests on: "Three commercial parameters ride on the
    same registration: `van_capacity_totes`, the largest number of totes one van
    on this route can carry, which must be at least 1 and at most 400;
    `base_delivery_fee_cents`, the pre-surge delivery fee in cents, which must be
    at least 0 and at most 5,000, that is at most fifty dollars; and
    `per_km_cost_cents`, the transport cost per kilometre in cents, which must be
    at least 1 and at most 2,000."

    Design: Corner/entities/create_delivery_route_persists_all_input_fields
    """
    payload = factories.delivery_route_payload(
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )

    created = read_object(api.create_delivery_route(payload, admin_headers), 201)

    assert_delivery_route_shape(created)
    assert created["route_code"] == "RT-NORTH"
    assert created["service_area_name"] == "North Reach"
    assert_int_field(created, "van_capacity_totes", 40)
    assert_money(created, "base_delivery_fee_cents", 599)
    assert_money(created, "per_km_cost_cents", 150)
    assert_version_is(created, 1)
    assert_instant_equals(created["updated_at"], created["created_at"], "updated_at")

    fetched = read_object(api.get_delivery_route(created["id"], admin_headers))
    assert fetched["id"] == created["id"]
    assert fetched["route_code"] == "RT-NORTH"
    assert fetched["service_area_name"] == "North Reach"
    assert_int_field(fetched, "van_capacity_totes", 40)
    assert_money(fetched, "base_delivery_fee_cents", 599)
    assert_money(fetched, "per_km_cost_cents", 150)
    assert_version_is(fetched, 1)


def test_reading_an_unregistered_delivery_route_reports_route_not_found(
    api, admin_headers
):
    """A read of a route identifier the site has never issued answers with the route family's own not-found code.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_delivery_route_unknown_id_returns_route_not_found
    """
    bay = fixtures.create_dock_bay(api, bay_code="BAY-1", parallel_van_capacity=2)

    response = api.get_delivery_route(NON_EXISTENT_UUID, admin_headers)

    validate_error(response, ApiError.ROUTE_NOT_FOUND.value)

    surviving_bay = read_object(api.get_dock_bay(bay["id"], admin_headers))
    assert surviving_bay["bay_code"] == "BAY-1"
    assert_int_field(surviving_bay, "parallel_van_capacity", 2)
    assert_version_is(surviving_bay, 1)


def test_registering_a_route_without_a_per_kilometre_cost_is_rejected(
    api, admin_headers
):
    """A route registration that omits the transport cost per kilometre is refused and no route is created.

    Cites the requirement it rests on: "The request body contains every required
    field and no unknown field; every value has the correct JSON type; every
    enum-typed value is drawn from that field's declared set; every quantity or
    money amount is a non-negative integer; every decimal respects its declared
    scale; every instant parses as an ISO 8601 UTC timestamp."

    Design: Corner/entities/create_delivery_route_missing_per_km_cost_cents_rejected
    """
    bay = fixtures.create_dock_bay(api, bay_code="BAY-1", parallel_van_capacity=2)
    payload = factories.delivery_route_payload(
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
    )
    payload.pop("per_km_cost_cents")

    response = api.create_delivery_route(payload, admin_headers)

    validate_error(response, ApiError.INVALID_REQUEST.value)

    _slots, slot_meta = list_items_and_meta(api.list_delivery_slots(admin_headers))
    assert slot_meta["total_count"] == 0

    surviving_bay = read_object(api.get_dock_bay(bay["id"], admin_headers))
    assert_int_field(surviving_bay, "parallel_van_capacity", 2)


def test_registering_a_route_whose_van_carries_no_totes_is_rejected(api, admin_headers):
    """A route claiming a van capacity of zero totes is refused, because a van must be able to carry at least one tote.

    Cites the requirement it rests on: "Three commercial parameters ride on the
    same registration: `van_capacity_totes`, the largest number of totes one van
    on this route can carry, which must be at least 1 and at most 400;
    `base_delivery_fee_cents`, the pre-surge delivery fee in cents, which must be
    at least 0 and at most 5,000, that is at most fifty dollars; and
    `per_km_cost_cents`, the transport cost per kilometre in cents, which must be
    at least 1 and at most 2,000."

    Design: Corner/entities/create_delivery_route_van_capacity_totes_zero_rejected
    """
    payload = factories.delivery_route_payload(
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=0,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )

    response = api.create_delivery_route(payload, admin_headers)

    validate_error(response, ApiError.INVALID_REQUEST.value)


def test_registering_a_second_route_under_a_used_route_code_is_rejected(
    api, admin_headers
):
    """Two delivery routes may not share a route code, and the refusal leaves the first route's own details untouched.

    Cites the requirement it rests on: "Registering a delivery route captures a
    `route_code` — a human-readable identifier of between 1 and 32 characters
    that must be unique across all routes, with a blank or duplicated value
    rejected as `ERR_INVALID_REQUEST` — together with a `service_area_name` of
    between 1 and 80 characters naming the geography the van covers."

    Design: Corner/entities/create_delivery_route_duplicate_route_code_rejected
    """
    first = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )

    response = api.create_delivery_route(
        factories.delivery_route_payload(
            route_code="RT-NORTH",
            service_area_name="South Reach",
            van_capacity_totes=20,
            base_delivery_fee_cents=499,
            per_km_cost_cents=120,
        ),
        admin_headers,
    )

    validate_error(response, ApiError.INVALID_REQUEST.value)

    surviving = read_object(api.get_delivery_route(first["id"], admin_headers))
    assert surviving["service_area_name"] == "North Reach"
    assert_int_field(surviving, "van_capacity_totes", 40)
    assert_money(surviving, "base_delivery_fee_cents", 599)
    assert_version_is(surviving, 1)


def test_reading_an_unregistered_dock_bay_reports_dock_bay_not_found(
    api, wave_planner_headers, admin_headers
):
    """A read of a dock bay identifier the site has never issued answers with the dock bay family's own not-found code.

    Cites the requirement it rests on: "Every identifier embedded in the URL path
    exists, validated left to right."

    Design: Corner/entities/get_dock_bay_unknown_id_returns_dock_bay_not_found
    """
    bay = fixtures.create_dock_bay(api, bay_code="BAY-1", parallel_van_capacity=2)

    response = api.get_dock_bay(NON_EXISTENT_UUID, wave_planner_headers)

    validate_error(response, ApiError.DOCK_BAY_NOT_FOUND.value)

    surviving = read_object(api.get_dock_bay(bay["id"], admin_headers))
    assert surviving["bay_code"] == "BAY-1"


def test_a_newly_registered_grid_zone_is_operational_with_no_accuracy_history(
    api, grid_engineer_headers
):
    """A freshly registered frozen grid zone is in service with both accuracy figures and its audit timestamp still empty.

    Cites the requirement it rests on: "A newly registered zone is `OPERATIONAL`;
    both of its accuracy figures, `accuracy_score_unit_weighted` and
    `accuracy_score_sku_weighted`, are null until the zone has been audited at
    least once, as is `last_audited_at`."

    Design: Corner/entities/create_grid_zone_defaults_operational_status_and_null_scores
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-FROZEN",
        temperature_zone=TemperatureZone.FROZEN.value,
        bot_count=12,
    )

    fetched = read_object(api.get_grid_zone(zone["id"], grid_engineer_headers))

    assert_grid_zone_shape(fetched)
    assert_status(fetched, GridZoneStatus.OPERATIONAL.value)
    assert fetched["temperature_zone"] == TemperatureZone.FROZEN.value
    assert_int_field(fetched, "bot_count", 12)
    assert_field_absent_or_null(fetched, "accuracy_score_unit_weighted")
    assert_field_absent_or_null(fetched, "accuracy_score_sku_weighted")
    assert_field_absent_or_null(fetched, "last_audited_at")
    assert_version_is(fetched, 1)


def test_registering_a_grid_zone_in_an_unlisted_temperature_class_is_rejected(
    api, admin_headers
):
    """A grid zone declaring a temperature class outside ambient, chilled and frozen is refused.

    Cites the requirement it rests on: "Everything that moves through the
    building carries exactly one temperature class, drawn from the three values
    `AMBIENT`, `CHILLED` and `FROZEN`."

    Design: Corner/entities/create_grid_zone_invalid_temperature_zone_rejected
    """
    payload = factories.grid_zone_payload(
        zone_code="GZ-COOL", temperature_zone="COOL", bot_count=4
    )

    response = api.create_grid_zone(payload, admin_headers)

    validate_error(response, ApiError.INVALID_REQUEST.value)


def test_reading_an_unregistered_grid_zone_reports_zone_not_found(
    api, grid_engineer_headers
):
    """A read of a grid zone identifier the site has never issued answers with the zone family's own not-found code.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_grid_zone_unknown_id_returns_zone_not_found
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-AMBIENT",
        temperature_zone=TemperatureZone.AMBIENT.value,
        bot_count=4,
    )

    response = api.get_grid_zone(NON_EXISTENT_UUID, grid_engineer_headers)

    validate_error(response, ApiError.ZONE_NOT_FOUND.value)

    surviving = read_object(api.get_grid_zone(zone["id"], grid_engineer_headers))
    assert_status(surviving, GridZoneStatus.OPERATIONAL.value)


def test_a_newly_registered_pick_station_stands_idle_with_no_open_totes(
    api, pick_operator_headers
):
    """A freshly registered pick station holds no open tote and therefore reports itself idle, keeping its declared capability set.

    Cites the requirement it rests on: "The station's `status` is derived from
    that count with no free parameters — it is `IDLE` exactly when
    `current_tote_count` is zero, and `ACTIVE` otherwise."

    Design: Corner/entities/create_pick_station_defaults_zero_totes_and_idle_status
    """
    station = fixtures.create_pick_station(
        api,
        station_code="PS-COLD",
        temperature_zone_capability=[
            TemperatureZone.CHILLED.value,
            TemperatureZone.FROZEN.value,
        ],
        max_concurrent_totes=3,
    )

    fetched = read_object(api.get_pick_station(station["id"], pick_operator_headers))

    assert_pick_station_shape(fetched)
    assert_int_field(fetched, "current_tote_count", 0)
    assert_status(fetched, PickStationStatus.IDLE.value)
    assert_station_status_matches_count(fetched)
    assert_int_field(fetched, "max_concurrent_totes", 3)
    assert fetched["temperature_zone_capability"] == [
        TemperatureZone.CHILLED.value,
        TemperatureZone.FROZEN.value,
    ]


def test_reading_an_unregistered_pick_station_reports_pick_station_not_found(
    api, pick_operator_headers
):
    """A read of a pick station identifier the site has never issued answers with the station family's own not-found code.

    Cites the requirement it rests on: "Every identifier embedded in the URL path
    exists, validated left to right."

    Design: Corner/entities/get_pick_station_unknown_id_returns_pick_station_not_found
    """
    station = fixtures.create_pick_station(
        api,
        station_code="PS-AMBIENT",
        temperature_zone_capability=[TemperatureZone.AMBIENT.value],
        max_concurrent_totes=4,
    )

    response = api.get_pick_station(NON_EXISTENT_UUID, pick_operator_headers)

    validate_error(response, ApiError.PICK_STATION_NOT_FOUND.value)

    surviving = read_object(api.get_pick_station(station["id"], pick_operator_headers))
    assert surviving["station_code"] == "PS-AMBIENT"


def test_a_newly_catalogued_sku_is_entirely_on_hand_and_never_counted(
    api, pick_operator_headers
):
    """A brand-new chilled SKU has nothing allocated against it, so all of its physical units are on hand and its audit trail is empty.

    Cites the requirement it rests on: "`allocated_units` starts at 0 and
    `on_hand_units` starts equal to `physical_units`, exactly as the ledger
    identity of §2.9 requires."

    Design: Corner/entities/create_inventory_sku_computes_on_hand_units_from_physical_units
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-CHILLED",
        temperature_zone=TemperatureZone.CHILLED.value,
        bot_count=6,
    )
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        sku_code="CHL-1",
        name="Fresh Milk",
        temperature_zone=TemperatureZone.CHILLED.value,
        substitution_group_code="DAIRY",
        unit_price_cents=120,
        physical_units=250,
    )

    fetched = read_object(api.get_inventory_sku(sku["id"], pick_operator_headers))

    assert_inventory_sku_shape(fetched)
    assert_sku_ledger(fetched, physical_units=250, allocated_units=0, on_hand_units=250)
    assert_field_absent_or_null(fetched, "last_count_system_units")
    assert_field_absent_or_null(fetched, "last_count_counted_units")
    assert_field_absent_or_null(fetched, "last_count_variance_units")
    assert_field_absent_or_null(fetched, "price_per_kg_cents")
    assert_field_absent_or_null(fetched, "nominal_weight_grams")
    assert_field_absent_or_null(fetched, "weight_tolerance_pct")


def test_a_catalogued_sku_carries_server_minted_identity_and_refuses_stray_body_keys(
    api, admin_headers
):
    """The catalogue mints the SKU's identifier, timestamps and version itself, and a registration carrying an unrecognised body key is refused.

    Cites the requirement it rests on: "It is generated by the server, never
    supplied by the client, and it carries no type prefix — it is a bare UUID
    string, not `order_` followed by a UUID."

    Cites the requirement it rests on: "The request body contains every required
    field and no unknown field; every value has the correct JSON type; every
    enum-typed value is drawn from that field's declared set; every quantity or
    money amount is a non-negative integer; every decimal respects its declared
    scale; every instant parses as an ISO 8601 UTC timestamp."

    Design: Corner/entities/create_inventory_sku_system_fields_generated_and_extra_field_ignored
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-AMBIENT",
        temperature_zone=TemperatureZone.AMBIENT.value,
        bot_count=4,
    )

    created = read_object(
        api.create_inventory_sku(
            factories.inventory_sku_payload(
                zone["id"],
                sku_code="AMB-1",
                name="Pasta",
                substitution_group_code="DRY",
                unit_price_cents=700,
                physical_units=100,
            ),
            admin_headers,
        ),
        201,
    )

    assert_inventory_sku_shape(created)
    assert_common_fields(created)
    assert not created["id"].startswith("sku_")
    assert_version_is(created, 1)
    assert_instant_equals(created["updated_at"], created["created_at"], "updated_at")
    assert_sku_ledger(created, physical_units=100, allocated_units=0, on_hand_units=100)

    stray = api.create_inventory_sku(
        factories.inventory_sku_payload(
            zone["id"],
            sku_code="AMB-2",
            name="Rice",
            substitution_group_code="DRY",
            unit_price_cents=700,
            physical_units=100,
            shelf_nickname="top shelf",
        ),
        admin_headers,
    )

    validate_error(stray, ApiError.INVALID_REQUEST.value)


def test_cataloguing_a_sku_into_an_unregistered_grid_zone_reports_zone_not_found(
    api, admin_headers
):
    """A SKU registration whose grid zone does not exist is refused with the zone family's not-found code before any field-shape work happens.

    Cites the requirement it rests on: "Every foreign-key identifier supplied in
    the request body exists, validated in the order in which the fields are
    listed for that endpoint."

    Design: Corner/entities/create_inventory_sku_unknown_grid_zone_returns_zone_not_found
    """
    payload = factories.inventory_sku_payload(
        NON_EXISTENT_UUID,
        sku_code="AMB-1",
        name="Pasta",
        substitution_group_code="DRY",
        unit_price_cents=700,
        physical_units=100,
    )

    response = api.create_inventory_sku(payload, admin_headers)

    validate_error(response, ApiError.ZONE_NOT_FOUND.value)


def test_reading_an_uncatalogued_sku_reports_sku_not_found(
    api, wave_planner_headers, admin_headers
):
    """A read of a SKU identifier the catalogue has never issued answers with the SKU family's own not-found code.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_inventory_sku_unknown_id_returns_sku_not_found
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-AMBIENT",
        temperature_zone=TemperatureZone.AMBIENT.value,
        bot_count=4,
    )
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        sku_code="AMB-1",
        name="Pasta",
        substitution_group_code="DRY",
        unit_price_cents=700,
        physical_units=100,
    )

    response = api.get_inventory_sku(NON_EXISTENT_UUID, wave_planner_headers)

    validate_error(response, ApiError.SKU_NOT_FOUND.value)

    surviving = read_object(api.get_inventory_sku(sku["id"], admin_headers))
    assert surviving["sku_code"] == "AMB-1"


def test_browsing_the_catalogue_pages_ten_of_twelve_skus_by_default(
    api, wave_planner_headers
):
    """A catalogue of twelve groceries browsed without paging inputs hands back the first ten and says more remain.

    Cites the requirement it rests on: "`limit` sets the page size: it defaults to
    10 when omitted, its minimum accepted value is 1 and its maximum accepted
    value is 100."

    Design: Corner/entities/list_inventory_skus_returns_paginated_envelope_with_default_limit
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-AMBIENT",
        temperature_zone=TemperatureZone.AMBIENT.value,
        bot_count=4,
    )
    for index in range(1, 13):
        fixtures.create_inventory_sku(
            api,
            zone["id"],
            sku_code=f"AMB-{index:02d}",
            name=f"Item {index:02d}",
            substitution_group_code="DRY",
            unit_price_cents=700,
            physical_units=10,
        )

    items, meta = list_items_and_meta(api.list_inventory_skus(wave_planner_headers))

    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert len(items) == 10
    for item in items:
        assert_common_fields(item)


def test_browsing_the_catalogue_by_substitution_group_returns_only_that_group(
    api, pick_operator_headers
):
    """Narrowing the catalogue to one substitution group hands back only the interchangeable items of that group.

    Cites the requirement it rests on: "The catalogue can be browsed as a
    filtered collection, narrowing by `grid_zone_id`, by `temperature_zone` or by
    `substitution_group_code`, which is also how a client discovers which SKUs
    live in a given zone."

    Design: Corner/entities/list_inventory_skus_filtered_by_substitution_group_code
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-CHILLED",
        temperature_zone=TemperatureZone.CHILLED.value,
        bot_count=6,
    )
    for code, name, price in (("PRD-1", "Lettuce", 150), ("PRD-2", "Spinach", 180)):
        fixtures.create_inventory_sku(
            api,
            zone["id"],
            sku_code=code,
            name=name,
            temperature_zone=TemperatureZone.CHILLED.value,
            substitution_group_code="PRODUCE",
            unit_price_cents=price,
            physical_units=60,
        )
    dairy = fixtures.create_inventory_sku(
        api,
        zone["id"],
        sku_code="DRY-9",
        name="Fresh Milk",
        temperature_zone=TemperatureZone.CHILLED.value,
        substitution_group_code="DAIRY",
        unit_price_cents=120,
        physical_units=90,
    )

    items, meta = list_items_and_meta(
        api.list_inventory_skus(
            pick_operator_headers,
            params={"substitution_group_code": "DAIRY", "limit": 10, "offset": 0},
        )
    )

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    hit = only_item(items)
    assert hit["id"] == dairy["id"]
    assert hit["substitution_group_code"] == "DAIRY"


def test_browsing_the_catalogue_with_a_zero_page_size_is_rejected(
    api, wave_planner_headers, admin_headers
):
    """A catalogue browse asking for a page of zero rows is refused rather than quietly falling back to the default page size.

    Cites the requirement it rests on: "A `limit` outside the range 1 through 100
    inclusive, or a negative `offset`, or either parameter supplied as something
    other than an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/entities/list_inventory_skus_limit_zero_returns_invalid_pagination
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-AMBIENT",
        temperature_zone=TemperatureZone.AMBIENT.value,
        bot_count=4,
    )
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        sku_code="AMB-1",
        name="Pasta",
        substitution_group_code="DRY",
        unit_price_cents=700,
        physical_units=100,
    )

    response = api.list_inventory_skus(
        wave_planner_headers, params={"limit": 0, "offset": 0}
    )

    validate_error(response, ApiError.INVALID_PAGINATION.value)

    surviving = read_object(api.get_inventory_sku(sku["id"], admin_headers))
    assert_sku_ledger(
        surviving, physical_units=100, allocated_units=0, on_hand_units=100
    )


def test_browsing_the_catalogue_beyond_the_largest_page_size_is_rejected(
    api, wave_planner_headers
):
    """A page size of one hundred rows is accepted while one hundred and one is refused, so the maximum page size is inclusive.

    Cites the requirement it rests on: "A `limit` outside the range 1 through 100
    inclusive, or a negative `offset`, or either parameter supplied as something
    other than an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/entities/list_inventory_skus_limit_above_hundred_returns_invalid_pagination
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-AMBIENT",
        temperature_zone=TemperatureZone.AMBIENT.value,
        bot_count=4,
    )
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        sku_code="AMB-1",
        name="Pasta",
        substitution_group_code="DRY",
        unit_price_cents=700,
        physical_units=100,
    )

    accepted, accepted_meta = list_items_and_meta(
        api.list_inventory_skus(wave_planner_headers, params={"limit": 100, "offset": 0})
    )
    assert accepted_meta["limit"] == 100
    assert only_item(accepted)["id"] == sku["id"]

    response = api.list_inventory_skus(
        wave_planner_headers, params={"limit": 101, "offset": 0}
    )

    validate_error(response, ApiError.INVALID_PAGINATION.value)


def test_scheduling_a_maintenance_window_leaves_the_grid_in_service(
    api, grid_engineer_headers, admin_headers
):
    """Booking engineering time on a grid zone records a scheduled window without taking the bots out of service.

    Cites the requirement it rests on: "A window is created in status
    `SCHEDULED`, and the zone remains `OPERATIONAL` — scheduling alone never
    takes the grid down."

    Design: Corner/entities/create_maintenance_window_defaults_scheduled_status
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-AMBIENT",
        temperature_zone=TemperatureZone.AMBIENT.value,
        bot_count=4,
    )

    window = read_object(
        api.create_maintenance_window(
            factories.maintenance_window_payload(
                zone["id"],
                window_start="2026-08-03T01:00:00.000Z",
                window_end="2026-08-03T03:00:00.000Z",
            ),
            grid_engineer_headers,
        ),
        201,
    )

    assert_maintenance_window_shape(window)
    assert_status(window, MaintenanceWindowStatus.SCHEDULED.value)
    assert window["grid_zone_id"] == zone["id"]
    assert_instant_equals(
        window["window_start"], "2026-08-03T01:00:00.000Z", "window_start"
    )
    assert_instant_equals(window["window_end"], "2026-08-03T03:00:00.000Z", "window_end")
    assert_version_is(window, 1)

    zone_after = read_object(api.get_grid_zone(zone["id"], admin_headers))
    assert_status(zone_after, GridZoneStatus.OPERATIONAL.value)


def test_scheduling_a_maintenance_window_that_ends_when_it_starts_is_rejected(
    api, grid_engineer_headers
):
    """An engineering window whose exclusive end instant equals its inclusive start instant is refused and no window is recorded on the zone.

    Cites the requirement it rests on: "Scheduling a window names an existing grid
    zone, an inclusive `window_start` and an exclusive `window_end`, each an
    ISO 8601 UTC instant with three fractional digits, with `window_start`
    strictly before `window_end`."

    Design: Corner/entities/create_maintenance_window_end_not_after_start_rejected
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-AMBIENT",
        temperature_zone=TemperatureZone.AMBIENT.value,
        bot_count=4,
    )

    response = api.create_maintenance_window(
        factories.maintenance_window_payload(
            zone["id"],
            window_start="2026-08-03T01:00:00.000Z",
            window_end="2026-08-03T01:00:00.000Z",
        ),
        grid_engineer_headers,
    )

    validate_error(response, ApiError.INVALID_REQUEST.value)

    _windows, meta = list_items_and_meta(
        api.list_maintenance_windows(
            grid_engineer_headers, params={"grid_zone_id": zone["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_reading_an_unscheduled_maintenance_window_reports_maintenance_window_not_found(
    api, grid_engineer_headers
):
    """A read of a maintenance window identifier that was never scheduled answers with the window family's own not-found code.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_maintenance_window_unknown_id_returns_maintenance_window_not_found
    """
    zone = fixtures.create_grid_zone(
        api,
        zone_code="GZ-AMBIENT",
        temperature_zone=TemperatureZone.AMBIENT.value,
        bot_count=4,
    )
    window = fixtures.create_maintenance_window(
        api,
        zone["id"],
        window_start="2026-08-03T01:00:00.000Z",
        window_end="2026-08-03T03:00:00.000Z",
    )

    response = api.get_maintenance_window(NON_EXISTENT_UUID, grid_engineer_headers)

    validate_error(response, ApiError.MAINTENANCE_WINDOW_NOT_FOUND.value)

    surviving = read_object(
        api.get_maintenance_window(window["id"], grid_engineer_headers)
    )
    assert_status(surviving, MaintenanceWindowStatus.SCHEDULED.value)


def test_opening_a_delivery_slot_derives_its_available_capacity_and_quiet_surge(
    api, admin_headers
):
    """A fresh slot holding six of its forty units back from sale reports thirty-four available and a quiet surge multiplier of one.

    Cites the requirement it rests on: "On creation, `held_units` and
    `confirmed_units` are 0, `available_units` is computed from the ledger
    identity of §2.9, and the slot's `surge_multiplier` is computed immediately."

    Cites the requirement it rests on: "The three premiums are added to 1.00, the
    sum is rounded half up to two decimal places, and the rounded figure is then
    clamped into the closed interval from 1.00 to 1.80: anything below the floor
    becomes 1.00 and anything above the ceiling becomes 1.80."

    Design: Corner/entities/create_delivery_slot_computes_available_units_and_base_surge
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )

    slot = read_object(
        api.create_delivery_slot(
            factories.delivery_slot_payload(
                route["id"],
                window_start="2026-08-05T10:00:00.000Z",
                window_end="2026-08-05T12:00:00.000Z",
                total_capacity_units=40,
                withheld_units=6,
            ),
            admin_headers,
        ),
        201,
    )

    assert_delivery_slot_shape(slot)
    assert_slot_ledger(
        slot,
        total_capacity_units=40,
        withheld_units=6,
        held_units=0,
        confirmed_units=0,
        available_units=34,
    )
    assert_surge_multiplier(slot, 1.00)
    assert_version_is(slot, 1)


def test_opening_a_delivery_slot_that_withholds_more_than_its_capacity_is_rejected(
    api, admin_headers
):
    """A slot may not open holding back more units than it physically has, and the refusal leaves the route with no slot at all.

    Cites the requirement it rests on: "The slot's `total_capacity_units` is its
    physical capacity in delivery units and must be at least 1 and at most 5,000,
    while `withheld_units` states how many of those units are held back from
    sale; it defaults to 0, may never be negative, and may never exceed
    `total_capacity_units`."

    Design: Corner/entities/create_delivery_slot_withheld_units_above_capacity_rejected
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )

    response = api.create_delivery_slot(
        factories.delivery_slot_payload(
            route["id"],
            window_start="2026-08-05T10:00:00.000Z",
            window_end="2026-08-05T12:00:00.000Z",
            total_capacity_units=10,
            withheld_units=11,
        ),
        admin_headers,
    )

    validate_error(response, ApiError.INVALID_REQUEST.value)

    _slots, meta = list_items_and_meta(
        api.list_delivery_slots(admin_headers, params={"route_id": route["id"]})
    )
    assert meta["total_count"] == 0


def test_reading_an_unopened_delivery_slot_reports_slot_not_found(
    api, wave_planner_headers, admin_headers
):
    """A read of a delivery slot identifier that was never opened answers with the slot family's own not-found code.

    Cites the requirement it rests on: "Every identifier embedded in the URL path
    exists, validated left to right."

    Design: Corner/entities/get_delivery_slot_unknown_id_returns_slot_not_found
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )
    slot = fixtures.create_delivery_slot(
        api,
        route["id"],
        window_start="2026-08-05T10:00:00.000Z",
        window_end="2026-08-05T12:00:00.000Z",
        total_capacity_units=10,
        withheld_units=0,
    )

    response = api.get_delivery_slot(NON_EXISTENT_UUID, wave_planner_headers)

    validate_error(response, ApiError.SLOT_NOT_FOUND.value)

    surviving = read_object(api.get_delivery_slot(slot["id"], admin_headers))
    assert_slot_ledger(
        surviving,
        total_capacity_units=10,
        withheld_units=0,
        held_units=0,
        confirmed_units=0,
        available_units=10,
    )


def test_registering_a_shopper_on_an_unregistered_home_route_reports_route_not_found(
    api, admin_headers
):
    """A shopper cannot be bound to a home route that does not exist, and the refusal leaves the site with no account.

    Cites the requirement it rests on: "The account also names a `home_route_id`,
    which must reference an existing route: it is the only route the shopper may
    ever book delivery slots on, and it is the route a wave must serve for that
    shopper's orders to be slotted into it."

    Design: Corner/entities/create_customer_account_unknown_home_route_returns_route_not_found
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )

    response = api.create_customer_account(
        factories.customer_account_payload(
            NON_EXISTENT_UUID,
            email="ada@example.com",
            full_name="Ada Lane",
            loyalty_tier=LoyaltyTier.BASIC.value,
        ),
        admin_headers,
    )

    validate_error(response, ApiError.ROUTE_NOT_FOUND.value)

    _accounts, meta = list_items_and_meta(
        api.list_customer_accounts(admin_headers, params={"home_route_id": route["id"]})
    )
    assert meta["total_count"] == 0


def test_reading_an_unregistered_shopper_account_reports_customer_account_not_found(
    api, admin_headers
):
    """A read of a shopper account identifier that was never registered answers with the account family's own not-found code.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_customer_account_unknown_id_returns_customer_account_not_found
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )
    account = fixtures.create_customer_account(
        api,
        route["id"],
        email="ada@example.com",
        full_name="Ada Lane",
        loyalty_tier=LoyaltyTier.BASIC.value,
    )

    response = api.get_customer_account(NON_EXISTENT_UUID, admin_headers)

    validate_error(response, ApiError.CUSTOMER_ACCOUNT_NOT_FOUND.value)

    surviving = read_object(api.get_customer_account(account["id"], admin_headers))
    assert surviving["loyalty_tier"] == LoyaltyTier.BASIC.value


def test_a_shopper_registered_without_a_loyalty_tier_joins_the_basic_tier(
    api, admin_headers
):
    """A shopper registered with no loyalty tier named lands in the basic tier, the tier that earns no discount.

    Cites the requirement it rests on: "Finally, a shopper account is registered
    with an `email` that must contain an at-sign and must be unique across all
    accounts, a `full_name` of 1 to 120 characters, and a `loyalty_tier` drawn
    from `BASIC`, `PLUS` and `PREMIER` which defaults to `BASIC` and which later
    selects the discount schedule of the charge waterfall."

    Design: Corner/entities/create_customer_account_defaults_basic_loyalty_tier
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )

    spelled_out = read_object(
        api.create_customer_account(
            factories.customer_account_payload(
                route["id"],
                email="bo@example.com",
                full_name="Bo Ray",
                loyalty_tier=LoyaltyTier.BASIC.value,
            ),
            admin_headers,
        ),
        201,
    )

    assert_customer_account_shape(spelled_out)
    assert spelled_out["loyalty_tier"] == LoyaltyTier.BASIC.value
    assert spelled_out["home_route_id"] == route["id"]
    assert_version_is(spelled_out, 1)

    silent_payload = factories.customer_account_payload(
        route["id"], email="cass@example.com", full_name="Cass Vine"
    )
    silent_payload.pop("loyalty_tier")

    defaulted = read_object(
        api.create_customer_account(silent_payload, admin_headers), 201
    )

    assert defaulted["loyalty_tier"] == LoyaltyTier.BASIC.value
    assert defaulted["home_route_id"] == route["id"]
    assert_version_is(defaulted, 1)


def test_browsing_shopper_accounts_by_home_route_returns_only_that_route(
    api, wave_planner_headers
):
    """Narrowing the shopper roll to one home route hands back only the shoppers that route serves.

    Cites the requirement it rests on: "Accounts can be listed filtered by
    `home_route_id` or by `loyalty_tier`."

    Design: Corner/entities/list_customer_accounts_filtered_by_home_route_id
    """
    north = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )
    south = fixtures.create_delivery_route(
        api,
        route_code="RT-SOUTH",
        service_area_name="South Reach",
        van_capacity_totes=30,
        base_delivery_fee_cents=499,
        per_km_cost_cents=120,
    )
    northern_shopper = fixtures.create_customer_account(
        api,
        north["id"],
        email="ada@example.com",
        full_name="Ada Lane",
        loyalty_tier=LoyaltyTier.BASIC.value,
    )
    southern_shopper = fixtures.create_customer_account(
        api,
        south["id"],
        email="bo@example.com",
        full_name="Bo Ray",
        loyalty_tier=LoyaltyTier.PLUS.value,
    )

    items, meta = list_items_and_meta(
        api.list_customer_accounts(
            wave_planner_headers,
            params={"home_route_id": south["id"], "limit": 10, "offset": 0},
        )
    )

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    hit = only_item(items)
    assert hit["id"] == southern_shopper["id"]
    assert hit["id"] != northern_shopper["id"]
    assert hit["home_route_id"] == south["id"]


def test_a_new_basket_opens_in_draft_with_no_money_settled(
    api, make_customer_headers, admin_headers
):
    """A shopper's freshly opened basket is a draft awaiting authorization, with an empty subtotal and no fee, discount or total yet.

    Cites the requirement it rests on: "The order starts with `fulfillment_status`
    `DRAFT` and `billing_status` `PENDING_AUTH`; its `wave_id` is null because it
    has not been waved; its `merchandise_subtotal_cents` is 0 while
    `delivery_fee_cents`, `loyalty_discount_cents` and `order_total_cents` are all
    null; `authorized_amount_cents` and `captured_amount_cents` are null;
    `dispatch_blocked` is false; and `open_substitution_count` is 0."

    Design: Corner/entities/create_customer_order_defaults_draft_pending_auth_and_zero_subtotal
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )
    account = fixtures.create_customer_account(
        api,
        route["id"],
        email="ada@example.com",
        full_name="Ada Lane",
        loyalty_tier=LoyaltyTier.BASIC.value,
    )

    order = read_object(
        api.create_customer_order(
            factories.customer_order_payload(stop_distance_km=5.00),
            make_customer_headers(account["id"]),
        ),
        201,
    )

    assert_customer_order_shape(order)
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
    assert_money(order, "merchandise_subtotal_cents", 0)
    assert_field_absent_or_null(order, "delivery_fee_cents")
    assert_field_absent_or_null(order, "loyalty_discount_cents")
    assert_field_absent_or_null(order, "order_total_cents")
    assert_field_absent_or_null(order, "authorized_amount_cents")
    assert_field_absent_or_null(order, "captured_amount_cents")
    assert order["dispatch_blocked"] is False
    assert_int_field(order, "open_substitution_count", 0)
    assert_field_absent_or_null(order, "wave_id")
    assert_version_is(order, 1)

    fetched = read_object(api.get_customer_order(order["id"], admin_headers))
    assert_order_statuses(
        fetched,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )


def test_a_basket_belongs_to_the_shopper_named_in_the_request_headers(
    api, make_customer_headers, admin_headers
):
    """Two shoppers sending the identical basket request each end up owning their own basket, because ownership comes from the acting identity.

    Cites the requirement it rests on: "Its `customer_id` is taken from the
    `X-User-ID` header of the acting `Customer` and is never read from the request
    body, so a shopper cannot open a basket on someone else's behalf."

    Design: Corner/entities/create_customer_order_sets_customer_id_from_user_header
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )
    ada = fixtures.create_customer_account(
        api,
        route["id"],
        email="ada@example.com",
        full_name="Ada Lane",
        loyalty_tier=LoyaltyTier.BASIC.value,
    )
    bo = fixtures.create_customer_account(
        api,
        route["id"],
        email="bo@example.com",
        full_name="Bo Ray",
        loyalty_tier=LoyaltyTier.BASIC.value,
    )

    ada_basket = read_object(
        api.create_customer_order(
            factories.customer_order_payload(stop_distance_km=5.00),
            make_customer_headers(ada["id"]),
        ),
        201,
    )
    bo_basket = read_object(
        api.create_customer_order(
            factories.customer_order_payload(stop_distance_km=5.00),
            make_customer_headers(bo["id"]),
        ),
        201,
    )

    assert ada_basket["customer_id"] == ada["id"]
    assert bo_basket["customer_id"] == bo["id"]
    assert float(bo_basket["stop_distance_km"]) == 5.00

    _orders, meta = list_items_and_meta(
        api.list_customer_orders(admin_headers, params={"customer_id": bo["id"]})
    )
    assert meta["total_count"] == 1


def test_reading_an_unopened_basket_reports_order_not_found(
    api, wave_planner_headers, make_customer_headers
):
    """A read of a basket identifier no shopper ever opened answers with the order family's own not-found code.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_customer_order_unknown_id_returns_order_not_found
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )
    account = fixtures.create_customer_account(
        api,
        route["id"],
        email="ada@example.com",
        full_name="Ada Lane",
        loyalty_tier=LoyaltyTier.BASIC.value,
    )
    order = fixtures.create_customer_order(api, account["id"], stop_distance_km=5.00)

    response = api.get_customer_order(NON_EXISTENT_UUID, wave_planner_headers)

    validate_error(response, ApiError.ORDER_NOT_FOUND.value)

    surviving = read_object(
        api.get_customer_order(order["id"], make_customer_headers(account["id"]))
    )
    assert_order_statuses(
        surviving, fulfillment_status=FulfillmentStatus.DRAFT.value
    )


def test_pricing_a_basket_line_quotes_the_shelf_price_and_defers_the_final_figure(
    api, make_customer_headers, admin_headers
):
    """A line dropped into a basket is quoted at shelf price times quantity, while the figure that will actually be charged stays open until the goods are physically retrieved.

    Cites the requirement it rests on: "For an item that is not sold by weight,
    the provisional price is the SKU's `unit_price_cents` multiplied by the line's
    `ordered_qty`; because both are integers, the product is already whole cents."

    Design: Corner/entities/add_order_line_computes_provisional_price_and_leaves_final_null
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )
    zone = fixtures.create_grid_zone(
        api, zone_code="GZ-A", temperature_zone=TemperatureZone.AMBIENT.value
    )
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        sku_code="SKU-OATS",
        name="Rolled Oats 1kg",
        temperature_zone=TemperatureZone.AMBIENT.value,
        substitution_group_code="OATS",
        unit_price_cents=700,
        physical_units=500,
    )
    account = fixtures.create_customer_account(
        api,
        route["id"],
        email="ada@example.com",
        full_name="Ada Lane",
        loyalty_tier=LoyaltyTier.BASIC.value,
    )
    shopper_headers = make_customer_headers(account["id"])
    order = fixtures.create_customer_order(api, account["id"], stop_distance_km=5.00)

    line = read_object(
        api.add_order_line(
            order["id"],
            factories.order_line_payload(sku["id"], ordered_qty=2),
            shopper_headers,
        ),
        201,
    )

    assert_order_line_shape(line)
    assert line["order_id"] == order["id"]
    assert line["sku_id"] == sku["id"]
    assert_int_field(line, "ordered_qty", 2)
    assert_money(line, "provisional_line_price_cents", 1400)
    assert_field_absent_or_null(line, "final_line_price_cents")
    assert_field_absent_or_null(line, "nominal_weight_grams")
    assert_field_absent_or_null(line, "picked_units")
    assert_field_absent_or_null(line, "picked_weight_grams")
    assert_status(line, LineStatus.PENDING.value, field="line_status")
    assert_status(
        line,
        SubstitutionResolution.NOT_REQUIRED.value,
        field="substitution_resolution",
    )
    assert_common_fields(line)
    assert_version_is(line, 1)

    priced_basket = fixtures.read_order(api, account["id"], order["id"])
    assert_money(priced_basket, "merchandise_subtotal_cents", 1400)
    assert_field_absent_or_null(priced_basket, "delivery_fee_cents")
    assert_field_absent_or_null(priced_basket, "order_total_cents")
    assert_version_is(priced_basket, 2)

    stored_line = read_object(api.get_order_line(line["id"], admin_headers))
    assert_money(stored_line, "provisional_line_price_cents", 1400)


def test_ordering_a_grocery_that_is_not_in_the_catalogue_reports_sku_not_found(
    api, make_customer_headers, admin_headers
):
    """A line naming a grocery the catalogue has never heard of is refused with the catalogue's own not-found code, and the basket is left untouched.

    Cites the requirement it rests on: "Every foreign-key identifier supplied in
    the request body exists, validated in the order in which the fields are listed
    for that endpoint."

    Design: Corner/entities/add_order_line_unknown_sku_returns_sku_not_found
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )
    account = fixtures.create_customer_account(
        api,
        route["id"],
        email="ada@example.com",
        full_name="Ada Lane",
        loyalty_tier=LoyaltyTier.BASIC.value,
    )
    shopper_headers = make_customer_headers(account["id"])
    order = fixtures.create_customer_order(api, account["id"], stop_distance_km=5.00)

    response = api.add_order_line(
        order["id"],
        factories.order_line_payload(NON_EXISTENT_UUID, ordered_qty=2),
        shopper_headers,
    )

    validate_error(response, ApiError.SKU_NOT_FOUND.value)

    untouched = fixtures.read_order(api, account["id"], order["id"])
    assert_money(untouched, "merchandise_subtotal_cents", 0)
    assert_version_is(untouched, 1)

    _lines, meta = list_items_and_meta(
        api.list_order_lines(admin_headers, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_ordering_a_grocery_in_a_quantity_of_none_is_rejected(
    api, make_customer_headers, admin_headers
):
    """A shopper cannot add a line that asks for nothing at all; the smallest quantity a basket line may carry is one unit.

    Cites the requirement it rests on: "Adding a line to a `DRAFT` basket takes a
    `sku_id` naming the catalogue item and an `ordered_qty` of at least 1 and at
    most 200."

    Design: Corner/entities/add_order_line_ordered_qty_zero_rejected
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )
    zone = fixtures.create_grid_zone(
        api, zone_code="GZ-A", temperature_zone=TemperatureZone.AMBIENT.value
    )
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        sku_code="SKU-OATS",
        name="Rolled Oats 1kg",
        temperature_zone=TemperatureZone.AMBIENT.value,
        substitution_group_code="OATS",
        unit_price_cents=700,
        physical_units=500,
    )
    account = fixtures.create_customer_account(
        api,
        route["id"],
        email="ada@example.com",
        full_name="Ada Lane",
        loyalty_tier=LoyaltyTier.BASIC.value,
    )
    shopper_headers = make_customer_headers(account["id"])
    order = fixtures.create_customer_order(api, account["id"], stop_distance_km=5.00)

    response = api.add_order_line(
        order["id"],
        factories.order_line_payload(sku["id"], ordered_qty=0),
        shopper_headers,
    )

    validate_error(response, ApiError.INVALID_REQUEST.value)

    untouched = fixtures.read_order(api, account["id"], order["id"])
    assert_money(untouched, "merchandise_subtotal_cents", 0)
    assert_version_is(untouched, 1)

    _lines, meta = list_items_and_meta(
        api.list_order_lines(admin_headers, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0

    accepted = read_object(
        api.add_order_line(
            order["id"],
            factories.order_line_payload(sku["id"], ordered_qty=1),
            shopper_headers,
        ),
        201,
    )
    assert_int_field(accepted, "ordered_qty", 1)


def test_reading_a_basket_line_that_was_never_added_reports_order_line_not_found(
    api, admin_headers, make_customer_headers
):
    """A read of a basket-line identifier that belongs to no basket answers with the order-line family's own not-found code.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_order_line_unknown_id_returns_order_line_not_found
    """
    route = fixtures.create_delivery_route(
        api,
        route_code="RT-NORTH",
        service_area_name="North Reach",
        van_capacity_totes=40,
        base_delivery_fee_cents=599,
        per_km_cost_cents=150,
    )
    zone = fixtures.create_grid_zone(
        api, zone_code="GZ-A", temperature_zone=TemperatureZone.AMBIENT.value
    )
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        sku_code="SKU-OATS",
        name="Rolled Oats 1kg",
        temperature_zone=TemperatureZone.AMBIENT.value,
        substitution_group_code="OATS",
        unit_price_cents=700,
        physical_units=500,
    )
    account = fixtures.create_customer_account(
        api,
        route["id"],
        email="ada@example.com",
        full_name="Ada Lane",
        loyalty_tier=LoyaltyTier.BASIC.value,
    )
    order = fixtures.create_customer_order(api, account["id"], stop_distance_km=5.00)
    line = fixtures.add_order_line(
        api, account["id"], order["id"], sku["id"], ordered_qty=1
    )

    response = api.get_order_line(NON_EXISTENT_UUID, admin_headers)

    validate_error(response, ApiError.ORDER_LINE_NOT_FOUND.value)

    surviving = read_object(api.get_order_line(line["id"], admin_headers))
    assert surviving["id"] == line["id"]
    assert_status(surviving, LineStatus.PENDING.value, field="line_status")
