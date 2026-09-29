"""Reference data, the envelope, defaults and the shape gates around them.

These are the registry rows every later workflow stands on: roads, junctions,
rate books, cars and the append-only event log, checked for their declared
defaults, their computed seeds, their immutability and the precedence order in
which a malformed body is refused.
"""

from test_helpers import (
    DEFAULT_PER_DIEM_CREDIT_LIMIT_CENTS,
    ERR_CAR_NOT_FOUND,
    ERR_CAR_TYPE_NOT_FOUND,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_REQUEST,
    ERR_RAILROAD_NOT_FOUND,
    SERVER_START_CLOCK_UTC,
    ApiClient,
    admin_headers,
    assert_error_envelope,
    assert_instant_equals,
    assert_money,
    assert_no_common_update_fields,
    assert_timestamp_format,
    assert_versioned_row,
    closed_movement_of,
    deliver_back,
    deliver_out,
    ids_of,
    is_valid_uuid,
    make_fleet_owner_headers,
    make_interchange_clerk_headers,
    register_car,
    register_railroad,
    request_id_of,
    set_clock,
    standard_world,
    validate_paginated,
    validate_success,
)
import test_helpers.factories as f

UNUSED_CAR_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_CAR_TYPE_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_ROAD_ID = "33333333-3333-4333-8333-333333333333"


class TestRailroadRegistry:
    """A road is admitted with two fields and every derived figure seeded."""

    def test_creation_returns_the_envelope_and_every_seeded_field(self, api: ApiClient):
        """POST with mark and name alone returns 201, version 1 and three zeroes.

        PRD: "A road is created with `foreign_car_balance`, `per_diem_exposure_cents` and `owned_car_count` all at 0 and `version` at 1."

        Design: Corner/entities/railroad_creation_returns_201_with_envelope_and_all_fields
        """
        response = api.create_railroad(
            f.railroad_payload("BN", "Bear Northern Railway"), admin_headers())
        road = validate_success(response, 201)

        body = response.json()
        assert body["response_type"] == "object"
        assert request_id_of(response).startswith("req_")
        assert_timestamp_format(body["meta"]["api_request_timestamp"])

        assert road["reporting_mark"] == "BN"
        assert road["name"] == "Bear Northern Railway"
        assert road["status"] == "ACTIVE"
        assert_money(road["per_diem_credit_limit_cents"],
                     DEFAULT_PER_DIEM_CREDIT_LIMIT_CENTS,
                     "per_diem_credit_limit_cents")
        assert road["foreign_car_balance"] == 0
        assert_money(road["per_diem_exposure_cents"], 0, "per_diem_exposure_cents")
        assert road["owned_car_count"] == 0

        assert_versioned_row(road, 1, "railroad")
        assert is_valid_uuid(road["id"])
        assert "_" not in road["id"] and ":" not in road["id"]
        assert_instant_equals(road["created_at"], SERVER_START_CLOCK_UTC, "created_at")
        assert_instant_equals(road["updated_at"], road["created_at"], "updated_at")

    def test_the_two_optional_inputs_are_defaults_not_hard_coded_values(self, api: ApiClient):
        """One road takes ACTIVE and 100000000; the next overrides both.

        PRD: "`per_diem_credit_limit_cents` caps how much snapshot per-diem exposure the road is allowed to carry, must not be negative, and defaults to 100000000 cents — one million dollars."

        Design: Corner/entities/railroad_created_without_optional_fields_applies_declared_defaults
        """
        defaulted = validate_success(api.create_railroad(
            f.railroad_payload("BN", "Bear Northern Railway"), admin_headers()), 201)
        explicit = validate_success(api.create_railroad(
            f.railroad_payload("CX", "Coast Express Lines", status="SUSPENDED",
                               per_diem_credit_limit_cents=25000),
            admin_headers()), 201)

        assert defaulted["status"] == "ACTIVE"
        assert_money(defaulted["per_diem_credit_limit_cents"],
                     DEFAULT_PER_DIEM_CREDIT_LIMIT_CENTS, "default limit")

        assert explicit["status"] == "SUSPENDED"
        assert_money(explicit["per_diem_credit_limit_cents"], 25000, "explicit limit")
        assert explicit["status"] != defaulted["status"]


class TestJunctionRegistry:
    """Both connected roads are validated by foreign key, not by nesting."""

    def test_an_unknown_connected_road_is_refused_before_the_row_exists(self, api: ApiClient):
        """A junction naming one real road and one unknown id is a 404, and the real pair is 201.

        PRD: "A junction is registered with a unique `junction_code`, a human-readable `name`, and the identifiers `road_a_id` and `road_b_id` of the two connected railroads, which must be two different existing roads."

        Design: Corner/entities/junction_road_ids_must_reference_existing_railroads
        """
        bn = register_railroad(api, "BN")
        cx = register_railroad(api, "CX")

        refused = api.create_junction(
            f.junction_payload("JCT-BAD", cx, UNKNOWN_ROAD_ID, name="Nowhere Interchange"),
            admin_headers())
        assert_error_envelope(refused, ERR_RAILROAD_NOT_FOUND, 404)

        junction = validate_success(api.create_junction(
            f.junction_payload("JCT-CHI", cx, bn, name="Chicago Interchange"),
            admin_headers()), 201)
        assert junction["status"] == "OPEN"

        by_a, _ = validate_paginated(api.list_junctions(admin_headers(),
                                                       params={"road_a_id": cx}))
        by_b, _ = validate_paginated(api.list_junctions(admin_headers(),
                                                       params={"road_b_id": bn}))
        assert junction["id"] in ids_of(by_a)
        assert junction["id"] in ids_of(by_b)

        missing, meta = validate_paginated(api.list_junctions(
            admin_headers(), params={"junction_code": "JCT-BAD"}))
        assert missing == []
        assert meta["total_count"] == 0


class TestCarRegistry:
    """A car row carries three independent dimensions and validated parents."""

    def test_the_stored_car_is_read_back_with_all_three_dimensions(self, api: ApiClient):
        """GET returns the registered marks plus ON_HOME_ROAD, SERVICEABLE, NO_OBLIGATION.

        PRD: "Reading one car returns all three dimensions together."

        Design: Corner/entities/car_retrieval_returns_the_stored_row
        """
        world = standard_world(api)
        echoed = validate_success(api.get_car(world.car, world.owner(world.cx)))

        assert echoed["id"] == world.car
        assert echoed["car_mark"] == "CX 100001"
        assert echoed["car_type_id"] == world.xm
        assert echoed["owner_road_id"] == world.cx
        assert echoed["current_handling_road_id"] == world.cx

        assert echoed["custody_status"] == "ON_HOME_ROAD"
        assert echoed["mechanical_status"] == "SERVICEABLE"
        assert echoed["routing_status"] == "NO_OBLIGATION"

        assert echoed["cumulative_mileage"] == 0
        assert echoed["prescribed_return_junction_id"] is None
        assert echoed["bad_order_since"] is None
        assert_versioned_row(echoed, 1, "car")

    def test_a_dangling_car_type_reference_is_a_body_foreign_key_failure(self, api: ApiClient):
        """A valid body naming an unused car_type_id is 404 and writes nothing.

        PRD: "Every foreign key in the request body resolves to an existing row, reported through the same not-found catalogue as step 5."

        Design: Corner/entities/car_with_unknown_car_type_id_returns_not_found
        """
        cx = register_railroad(api, "CX")
        refused = api.create_car(
            f.car_payload("CX 100001", UNKNOWN_CAR_TYPE_ID, cx),
            make_fleet_owner_headers(cx))
        assert_error_envelope(refused, ERR_CAR_TYPE_NOT_FOUND, 404)

        rows, meta = validate_paginated(api.list_cars(make_fleet_owner_headers(cx),
                                                     params={"owner_road_id": cx}))
        assert rows == []
        assert meta["total_count"] == 0

    def test_an_unused_uuid_in_the_path_is_a_not_found_not_a_null_body(self, api: ApiClient):
        """A well-formed but unused car id yields 404 ERR_CAR_NOT_FOUND.

        PRD: "Every identifier in the URL path resolves to an existing row of its entity, checked left to right, the error naming the entity that failed: `ERR_RAILROAD_NOT_FOUND`, `ERR_JUNCTION_NOT_FOUND`, `ERR_CAR_TYPE_NOT_FOUND`, `ERR_CAR_NOT_FOUND`, `ERR_INTERCHANGE_EVENT_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_RECLAIM_CLAIM_NOT_FOUND`, `ERR_EMBARGO_ORDER_NOT_FOUND`, `ERR_REPAIR_BILL_NOT_FOUND`, `ERR_SETTLEMENT_CYCLE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CORRECTION_REQUEST_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`."

        Design: Corner/entities/car_get_with_unknown_uuid_returns_not_found
        """
        cx = register_railroad(api, "CX")
        refused = api.get_car(UNUSED_CAR_ID, make_fleet_owner_headers(cx))
        assert refused.status_code == 404
        assert_error_envelope(refused, ERR_CAR_NOT_FOUND, 404)
        assert refused.json()["data"]["message"].strip() != ""


CAPTURE_CLOCK = "2026-08-24T00:00:00Z"


def _capture_ready_world(api):
    """Two roads, a rate book, JCT-CHI and one CX car, with the clock at 08-24."""
    world = standard_world(api)
    set_clock(api, CAPTURE_CLOCK, world)
    return world


class TestInterchangeEventLog:
    """The log is append-only, filtered, paginated and shape-checked in order."""

    def test_the_event_list_filters_by_car_and_pages_in_interchange_order(self, api: ApiClient):
        """Three events for one car page 2 then 1, ordered by interchange_at ascending.

        PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` counts every row matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current page."

        Design: Corner/entities/interchange_events_listing_filters_and_paginates
        """
        world = standard_world(api, bootstrap_clock="2026-08-20T00:00:00Z")
        car1 = world.car
        car2 = register_car(api, "CX 100002", world.xm, world.cx, world=world)

        deliver_out(api, world, car1, "2026-08-24T00:00:00Z", 100)
        deliver_out(api, world, car2, "2026-08-25T00:00:00Z", 50)
        deliver_back(api, world, car1, "2026-08-26T00:00:00Z", 200)
        deliver_out(api, world, car1, "2026-08-27T00:00:00Z", 300)

        clerk = make_interchange_clerk_headers(world.cx)
        page1, meta1 = validate_paginated(api.list_interchange_events(
            clerk, params={"car_id": car1, "limit": 2, "offset": 0}))
        page2, meta2 = validate_paginated(api.list_interchange_events(
            clerk, params={"car_id": car1, "limit": 2, "offset": 2}))

        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        instants = [row["interchange_at"] for row in page1 + page2]
        assert_instant_equals(instants[0], "2026-08-24T00:00:00Z", "first instant")
        assert_instant_equals(instants[1], "2026-08-26T00:00:00Z", "second instant")
        assert_instant_equals(instants[2], "2026-08-27T00:00:00Z", "third instant")

        assert all(row["car_id"] == car1 for row in page1 + page2)
        other, other_meta = validate_paginated(api.list_interchange_events(
            clerk, params={"car_id": car2}))
        assert other_meta["total_count"] == 1
        assert other[0]["id"] not in ids_of(page1 + page2)

    def test_a_missing_required_field_is_refused_before_any_business_rule(self, api: ApiClient):
        """Omitting load_status is 400 ERR_INVALID_REQUEST and logs nothing.

        PRD: "Request shape on every write: each required field present, of the declared JSON type, and inside its declared numeric or string bounds — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/interchange_event_missing_required_load_status_rejected
        """
        world = _capture_ready_world(api)
        payload = f.delivery_event_payload(world.car, world.jct, world.cx, world.bn,
                                          CAPTURE_CLOCK, 100)
        payload.pop("load_status")

        refused = api.create_interchange_event(payload,
                                              make_interchange_clerk_headers(world.cx))
        assert_error_envelope(refused, ERR_INVALID_REQUEST, 400)

        rows, meta = validate_paginated(api.list_interchange_events(
            make_interchange_clerk_headers(world.cx), params={"car_id": world.car}))
        assert rows == []
        assert meta["total_count"] == 0
        car = validate_success(api.get_car(world.car, world.owner(world.cx)))
        assert car["custody_status"] == "ON_HOME_ROAD"

    def test_a_well_typed_value_outside_the_enum_is_refused_after_the_shape_gate(self, api: ApiClient):
        """load_status PARTIAL is 422 ERR_INVALID_ENUM_VALUE, not the 400 of an absent key.

        PRD: "Every enum-typed input is a member of its declared value set — `event_type`, `load_status`, `reason`, `defect_class`, `correction_type`, `direction`, `dispute_reason`, `variant` and every `status` filter — otherwise `ERR_INVALID_ENUM_VALUE`."

        Design: Corner/entities/interchange_event_invalid_enum_value_rejected
        """
        world = _capture_ready_world(api)
        refused = api.create_interchange_event(
            f.delivery_event_payload(world.car, world.jct, world.cx, world.bn,
                                     CAPTURE_CLOCK, 100, "PARTIAL"),
            make_interchange_clerk_headers(world.cx))
        assert_error_envelope(refused, ERR_INVALID_ENUM_VALUE, 422)
        assert refused.status_code != 400

        rows, meta = validate_paginated(api.list_interchange_events(
            make_interchange_clerk_headers(world.cx), params={"car_id": world.car}))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_captured_event_exposes_no_version_and_no_updated_at(self, api: ApiClient):
        """The stored log line carries id and created_at only, at RECORDED and CLERK_CAPTURE.

        PRD: "Three record kinds are immutable by design and carry only `id` and `created_at` — for these, both `updated_at` and `version` are absent from the payload entirely:"

        Design: Corner/entities/interchange_event_is_immutable_and_carries_no_version
        """
        world = standard_world(api)
        captured = deliver_out(api, world, world.car, CAPTURE_CLOCK, 1000)

        stored = validate_success(api.get_interchange_event(
            captured["id"], make_interchange_clerk_headers(world.cx)))
        assert stored["id"] == captured["id"]
        assert_no_common_update_fields(stored, "interchange event")
        assert_timestamp_format(stored["created_at"])
        assert_instant_equals(stored["created_at"], CAPTURE_CLOCK, "created_at")
        assert stored["status"] == "RECORDED"
        assert stored["source"] == "CLERK_CAPTURE"
        assert stored["corrects_event_id"] is None
        assert stored["recorded_by_road_id"] == world.cx


class TestSegmentMoneyIsSystemComputed:
    """No endpoint accepts a segment's money; capture alone produces it."""

    def test_a_forty_eight_hour_loaded_segment_prices_itself_at_4935(self, api: ApiClient):
        """Closing the segment yields 44.00 hours, 2 days, 4700, 235 and 4935 with no input.

        PRD: "A hire segment is created by the system, never by a client, and it is the row that carries the money."

        Design: Corner/entities/movement_money_fields_are_computed_not_accepted_as_input
        """
        world = standard_world(api)
        deliver_out(api, world, world.car, CAPTURE_CLOCK, 1000)
        deliver_back(api, world, world.car, "2026-08-26T00:00:00Z", 1100)

        segment = closed_movement_of(api, world.car, world.bn,
                                    world.accountant(world.bn))
        assert segment["chargeable_hours"] == 44.00
        assert segment["chargeable_days"] == 2
        assert_money(segment["time_component_cents"], 4700, "time_component_cents")
        assert_money(segment["mileage_component_cents"], 235, "mileage_component_cents")
        assert_money(segment["gross_hire_cents"], 4935, "gross_hire_cents")
        assert_money(segment["reclaim_credit_cents"], 0, "reclaim_credit_cents")
        assert_money(segment["reverse_route_penalty_cents"], 0,
                     "reverse_route_penalty_cents")
        assert_money(segment["net_hire_cents"], 4935, "net_hire_cents")

        assert segment["hire_liable"] is True
        assert segment["start_odometer_miles"] == 1000
        assert segment["end_odometer_miles"] == 1100
