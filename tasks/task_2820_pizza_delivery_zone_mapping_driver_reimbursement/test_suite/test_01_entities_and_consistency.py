"""Resource shape, birth state and the immediacy of every create-time projection.

Each test in this file files one resource through the documented endpoints and
pins what the API reports back about it: which of the four common properties the
resource carries (a motor-vehicle-record pull carries only two), what a freshly
created record reads as before anything else has happened to it, which figures
the service re-derives on read, and which computed fields stay null until the
event that fills them. A second group pins the refusals that leave no record
behind at all — a missing required field, an unlisted enum member, an identifier
that resolves to nothing, and an address belonging to another store. The last
two tests pin that a creation and a route commitment each publish every derived
figure in their own response body, so a client never has to read the resource
back to learn what it has just committed to.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers import assertions as a
from test_helpers.constants import (
    CAR_COST_MODEL,
    DEFAULT_CLOCK,
    NOON_CLOCK,
    STORE_DEFAULTS,
    STORE_LAT_MICRO,
    STORE_LON_MICRO,
    TEST_POLYGON,
    TEST_ZONE_MODEL,
    ZONE_EFFECTIVE_FROM,
    ZONE_EFFECTIVE_TO,
)
from test_helpers.test_users import (
    BOOTSTRAP_MANAGER_HEADERS,
    CARE_HEADERS,
    COMPLIANCE_HEADERS,
    COMPLIANCE_OFFICER_USER_ID,
    DISPATCHER_HEADERS,
    make_manager_headers,
)


def _object_envelope(response, expected_status=200):
    """Unwrap a single-resource answer and pin the standard success envelope: a
    single resource reads as an object and the meta block carries the server-minted
    request identifier and request timestamp."""
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource reads as an object, got {body['response_type']!r}"
    )
    meta = body["meta"]
    request_id = meta.get("api_request_id")
    assert type(request_id) is str and request_id.startswith("req_"), (
        f"meta.api_request_id must be a string starting with req_, got {request_id!r}"
    )
    a.assert_iso_millis(meta["api_request_timestamp"], "meta.api_request_timestamp")
    return data


def _assert_instant(actual, expected, field="instant"):
    """An instant reads back with exactly three fractional-second digits and denotes
    the same moment as the value the request supplied."""
    a.assert_iso_millis(actual, field)
    assert a.parse_instant(actual) == a.parse_instant(expected), (
        f"expected {field} to be {expected}, got {actual}"
    )


def test_store_registration_echoes_its_policy_and_zeroes_every_aggregate():
    """A store registered with every policy field supplied echoes them back and is
    born with all three cash-and-workload aggregates at 0 and no area in force.

    PRD: "A freshly registered store reports `cash_collected_total_cents`, `safe_deposit_total_cents` and `unassigned_order_count` all at 0, and `active_zone_version_number` as null because no delivery area is in force yet."
    Design: Corner/entities/store_creation_returns_declared_fields_and_zeroed_aggregates
    """
    fx.set_clock(DEFAULT_CLOCK)

    payload = f.create_store_payload(
        store_number="7421",
        name="Riverside",
        latitude_micro=STORE_LAT_MICRO,
        longitude_micro=STORE_LON_MICRO,
        promise_minutes=30,
        delivery_fee_cents=399,
        cash_limit_cents=5000,
        hot_bag_count=4,
        max_stacked_stops=3,
        handoff_minutes_per_stop=6,
        dispatch_reset_buffer_minutes=10,
        service_posture="OPEN",
    )
    store = _object_envelope(api_client.create_store(payload, BOOTSTRAP_MANAGER_HEADERS), 201)

    a.assert_store(store)
    assert store["store_number"] == "7421"
    assert store["name"] == "Riverside"
    assert store["latitude_micro"] == STORE_LAT_MICRO
    assert store["longitude_micro"] == STORE_LON_MICRO
    assert store["promise_minutes"] == 30
    assert store["delivery_fee_cents"] == 399
    assert store["cash_limit_cents"] == 5000
    assert store["hot_bag_count"] == 4
    assert store["max_stacked_stops"] == 3
    assert store["handoff_minutes_per_stop"] == 6
    assert store["dispatch_reset_buffer_minutes"] == 10
    assert store["service_posture"] == "OPEN"

    assert store["cash_collected_total_cents"] == 0
    assert store["safe_deposit_total_cents"] == 0
    assert store["unassigned_order_count"] == 0
    assert store["active_zone_version_number"] is None
    assert store["version"] == 1
    _assert_instant(store["created_at"], DEFAULT_CLOCK, "created_at")


def test_store_registration_omitting_every_policy_field_takes_the_defaults():
    """A store registered with only its identity and its coordinates silently accepts
    the declared default for every policy field.

    PRD: "Every remaining field is policy, and every one has a default the store may accept silently: the advertised order-to-door `promise_minutes` defaults to 30 whole minutes and must be at least 1; the base customer `delivery_fee_cents` defaults to 399 and must be at least 0; the `cash_limit_cents` ceiling on how much cash a driver may carry defaults to 5000 (fifty dollars) and must be at least 0; `hot_bag_count`, the number of insulated bag slots the store physically owns, defaults to 4 and must be at least 1; `max_stacked_stops`, the ceiling on stops in one trip, defaults to 3 and must be at least 1; `handoff_minutes_per_stop`, the flat curbside allowance the route model charges at each door, defaults to 6 and must be at least 0; and `dispatch_reset_buffer_minutes`, the recovery time appended to a driver's occupied interval after a route comes back, defaults to 10 and must be at least 0."
    Design: Corner/entities/store_optional_config_defaults_are_applied_when_omitted
    """
    fx.set_clock(DEFAULT_CLOCK)

    payload = {
        "store_number": "9001",
        "name": "Bare Minimum",
        "latitude_micro": STORE_LAT_MICRO,
        "longitude_micro": STORE_LON_MICRO,
    }
    store = _object_envelope(api_client.create_store(payload, BOOTSTRAP_MANAGER_HEADERS), 201)

    a.assert_store(store)
    assert store["promise_minutes"] == 30 == STORE_DEFAULTS["promise_minutes"]
    assert store["delivery_fee_cents"] == 399 == STORE_DEFAULTS["delivery_fee_cents"]
    assert store["cash_limit_cents"] == 5000 == STORE_DEFAULTS["cash_limit_cents"]
    assert store["hot_bag_count"] == 4 == STORE_DEFAULTS["hot_bag_count"]
    assert store["max_stacked_stops"] == 3 == STORE_DEFAULTS["max_stacked_stops"]
    assert (
        store["handoff_minutes_per_stop"] == 6 == STORE_DEFAULTS["handoff_minutes_per_stop"]
    )
    assert (
        store["dispatch_reset_buffer_minutes"]
        == 10
        == STORE_DEFAULTS["dispatch_reset_buffer_minutes"]
    )
    assert store["service_posture"] == "OPEN" == STORE_DEFAULTS["service_posture"]
    assert store["version"] == 1


def test_store_version_starts_at_one_and_advances_by_one_on_the_first_edit():
    """A store is born at version 1 with a server-minted identifier and creation
    instant, and its first policy edit moves the version to exactly 2 while leaving
    the identifier and the creation instant untouched.

    PRD: "Almost every resource additionally carries `updated_at`, refreshed to the current instant on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource."
    Design: Corner/entities/store_system_fields_are_server_generated_and_version_starts_at_one
    """
    fx.set_clock(DEFAULT_CLOCK)

    created = _object_envelope(
        api_client.create_store(
            f.create_store_payload(store_number="7421", name="Riverside"),
            BOOTSTRAP_MANAGER_HEADERS,
        ),
        201,
    )
    a.assert_common_fields(created, expected_version=1)
    _assert_instant(created["created_at"], DEFAULT_CLOCK, "created_at")
    _assert_instant(created["updated_at"], DEFAULT_CLOCK, "updated_at")
    store_id = created["id"]

    fx.set_clock("2026-08-05T10:30:00Z")
    edited = _object_envelope(
        api_client.update_store(
            store_id, {"name": "Riverside East"}, make_manager_headers(store_id)
        ),
        200,
    )
    assert edited["id"] == store_id
    assert edited["created_at"] == created["created_at"]
    assert edited["version"] == 2
    assert edited["name"] == "Riverside East"
    assert edited["store_number"] == "7421"
    _assert_instant(edited["updated_at"], "2026-08-05T10:30:00Z", "updated_at")

    reread = fx.read_store(store_id)
    assert reread["id"] == store_id
    assert reread["created_at"] == created["created_at"]
    assert reread["version"] == 2
    assert reread["name"] == "Riverside East"


def test_order_without_the_customer_phone_is_refused_and_no_order_is_written():
    """An order body that omits the required customer telephone number is refused as
    an invalid request and leaves no order and no store workload behind.

    PRD: "Generic schema validity: required fields present, declared types honoured, enum members in range, integers within their stated bounds, datetimes well-formed ISO 8601 UTC instants — else `ERR_INVALID_REQUEST` (400), on every endpoint that takes a body or a query string."
    Design: Corner/entities/order_creation_missing_required_customer_phone_returns_invalid_request
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    address = fx.add_address(store_id, "A")

    payload = f.create_order_payload(store_id, address["id"])
    del payload["customer_phone"]

    response = api_client.create_order(payload, DISPATCHER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.json()["response_type"] == "error"

    orders, meta = validate_paginated(
        api_client.list_orders(DISPATCHER_HEADERS, {"store_id": store_id})
    )
    assert orders == []
    assert meta["total_count"] == 0
    assert fx.read_store(store_id)["unassigned_order_count"] == 0


def test_driver_with_a_vehicle_class_outside_the_declared_set_is_refused():
    """Hiring a driver on a vehicle class that is not one of the three declared
    members is refused as an invalid request and hires nobody.

    PRD: "A new driver requires the employing `store_id`, the driver's legal `full_name`, a `license_number` that must be unique among the drivers of that same store — a collision within the store is `ERR_LICENSE_NUMBER_TAKEN` — and a `vehicle_class`, which is `CAR`, `SUV` or `SCOOTER` and later selects the reimbursement schedule."
    Design: Corner/entities/driver_creation_with_an_unknown_vehicle_class_is_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store(store_number="7421", name="Riverside")
    store_id = store["id"]
    manager_headers = make_manager_headers(store_id)

    response = api_client.create_driver(
        f.create_driver_payload(store_id, vehicle_class="HOVERBOARD"), manager_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    drivers, meta = validate_paginated(
        api_client.list_drivers(manager_headers, {"store_id": store_id})
    )
    assert drivers == []
    assert meta["total_count"] == 0


def test_service_address_is_classified_once_at_the_moment_it_is_filed():
    """Filing an address computes its grid distance, its drive-time estimate and its
    zone standing there and then, stamping the instant and the area version used.

    PRD: "Before a store can quote an address it must classify it, and classification happens exactly once, at the moment the address is filed."
    Design: Corner/entities/service_address_computed_fields_are_derived_at_creation
    """
    store, zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]

    address = _object_envelope(
        api_client.create_service_address(
            f.create_service_address_payload(
                store_id, 39094950, -84000000, line1="900 North Rd", crosses_barrier=False
            ),
            DISPATCHER_HEADERS,
        ),
        201,
    )

    a.assert_service_address(address)
    assert address["store_id"] == store_id
    assert address["line1"] == "900 North Rd"
    assert address["latitude_micro"] == 39094950
    assert address["longitude_micro"] == -84000000
    assert address["crosses_barrier"] is False
    assert (
        address["grid_miles"]
        == 6.33
        == a.expected_grid_miles(39094950, -84000000, STORE_LAT_MICRO, STORE_LON_MICRO)
    )
    assert (
        address["drive_time_estimate_minutes"]
        == 25
        == a.expected_drive_minutes(
            6.33,
            TEST_ZONE_MODEL["base_drive_minutes"],
            TEST_ZONE_MODEL["minutes_per_mile"],
        )
    )
    assert address["zone_state"] == "IN_ZONE"
    assert address["effective_zone_state"] == "IN_ZONE"
    assert address["override_state"] is None
    assert address["override_until"] is None
    _assert_instant(address["evaluated_at"], DEFAULT_CLOCK, "evaluated_at")
    assert address["evaluated_zone_version_number"] == zone_version["version_number"] == 1
    assert address["version"] == 1


def test_draft_area_version_reads_back_its_ring_and_its_drive_time_model():
    """A published but not yet activated delivery-area version reads back with its
    ordered ring, all five drive-time constants, its window, and no lineage or
    activation instant yet.

    PRD: "It begins in `DRAFT` status — the other statuses being `ACTIVE` and the terminal `SUPERSEDED` — with `supersedes_zone_version_id` and `activated_at` both null."
    Design: Corner/entities/zone_version_retrieval_returns_the_stored_polygon_and_thresholds
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store(store_number="7421", name="Riverside")
    draft = fx.publish_zone_version(store["id"])

    zone_version = _object_envelope(
        api_client.get_zone_version(draft["id"], DISPATCHER_HEADERS), 200
    )

    a.assert_zone_version(zone_version)
    assert zone_version["id"] == draft["id"]
    assert zone_version["store_id"] == store["id"]
    assert zone_version["status"] == "DRAFT"
    assert zone_version["version_number"] == 1
    assert len(zone_version["polygon"]) == 4
    assert [
        (vertex["latitude_micro"], vertex["longitude_micro"])
        for vertex in zone_version["polygon"]
    ] == [
        (vertex["latitude_micro"], vertex["longitude_micro"]) for vertex in TEST_POLYGON
    ]
    assert zone_version["polygon"][0]["latitude_micro"] == 38900000
    assert zone_version["polygon"][0]["longitude_micro"] == -84200000
    _assert_instant(zone_version["effective_from"], ZONE_EFFECTIVE_FROM, "effective_from")
    _assert_instant(zone_version["effective_to"], ZONE_EFFECTIVE_TO, "effective_to")
    assert zone_version["max_drive_time_minutes"] == 40
    assert zone_version["base_drive_minutes"] == 6
    assert zone_version["minutes_per_mile"] == 3
    assert zone_version["peak_surcharge_minutes"] == 7
    assert zone_version["barrier_surcharge_minutes"] == 4
    assert zone_version["supersedes_zone_version_id"] is None
    assert zone_version["activated_at"] is None
    assert zone_version["version"] == 1


def test_service_address_pages_report_the_unpaginated_total_and_has_more():
    """Paging three classified addresses two at a time reports the effective page
    size and offset, the total before pagination, and has_more only while records
    remain beyond the page.

    PRD: "The `meta` object of every list response carries `limit` (the effective page size applied), `offset` (the effective starting position), `total_count` (the number of records matching the filters before pagination), and `has_more` (true exactly when records remain beyond the current page)."
    Design: Corner/entities/service_addresses_listing_paginates_with_total_count_and_has_more
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    near = fx.add_address(store_id, "A")
    middle = fx.add_address(store_id, "D")
    far = fx.add_address(store_id, "C")

    first_response = api_client.list_service_addresses(
        DISPATCHER_HEADERS, {"store_id": store_id, "limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_page) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_service_addresses(
            DISPATCHER_HEADERS, {"store_id": store_id, "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    paged_ids = {row["id"] for row in first_page} | {row["id"] for row in second_page}
    assert paged_ids == {near["id"], middle["id"], far["id"]}


def test_service_address_listing_filtered_on_zone_state_narrows_the_total():
    """Filtering the address collection on zone standing returns only the matching
    addresses and reports the filtered total rather than the collection total.

    PRD: "Service addresses accept `store_id` and `zone_state`."
    Design: Corner/entities/service_addresses_listing_paginates_with_total_count_and_has_more
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    near = fx.add_address(store_id, "A")
    middle = fx.add_address(store_id, "D")
    far = fx.add_address(store_id, "C")
    assert near["zone_state"] == "IN_ZONE"
    assert middle["zone_state"] == "IN_ZONE"
    assert far["zone_state"] == "OUT_OF_ZONE"

    rows, meta = validate_paginated(
        api_client.list_service_addresses(
            DISPATCHER_HEADERS,
            {"store_id": store_id, "zone_state": "IN_ZONE", "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert {row["id"] for row in rows} == {near["id"], middle["id"]}
    assert far["id"] not in {row["id"] for row in rows}


def test_reading_a_route_that_never_existed_reports_the_route_as_missing():
    """A route identifier in the path that resolves to nothing is reported as the
    route being missing, with the not-found status.

    PRD: "Every path identifier resolves, left to right, else the corresponding not-found error (404) — on every endpoint that has path parameters."
    Design: Corner/entities/get_dispatch_with_an_unknown_id_returns_dispatch_not_found
    """
    fx.set_clock(DEFAULT_CLOCK)

    response = api_client.get_dispatch(
        "11111111-1111-4111-8111-111111111111", DISPATCHER_HEADERS
    )
    error = validate_error(response, ApiErrorId.ERR_DISPATCH_NOT_FOUND.value)
    assert response.status_code == 404
    assert error["error_id"] == "ERR_DISPATCH_NOT_FOUND"

    routes, meta = validate_paginated(api_client.list_dispatches(DISPATCHER_HEADERS))
    assert routes == []
    assert meta["total_count"] == 0


def test_a_record_pull_carries_no_version_and_no_updated_at():
    """A motor-vehicle-record pull reads back as an append-only audit record: an
    identifier and a creation instant and no mutation bookkeeping of any kind.

    PRD: "A pull is an immutable audit record: it has an `id` and a `created_at` and nothing else in the way of common properties, no `updated_at`, no `version`, and no way to amend it."
    Design: Corner/entities/mvr_check_is_immutable_and_exposes_no_version_field
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store(store_number="7421", name="Riverside")
    driver = fx.hire_driver(store["id"], full_name="Dana Ortiz", license_number="DL-1001")
    pull = fx.record_mvr_check(
        driver["id"],
        COMPLIANCE_HEADERS,
        result="CLEAR",
        violation_points=0,
        checked_on="2026-08-01T08:00:00Z",
    )
    a.assert_append_only_common_fields(pull)

    read_back = _object_envelope(api_client.get_mvr_check(pull["id"], COMPLIANCE_HEADERS), 200)

    a.assert_mvr_check(read_back)
    a.assert_append_only_common_fields(read_back)
    assert "version" not in read_back
    assert "updated_at" not in read_back
    assert read_back["id"] == pull["id"]
    assert read_back["created_at"] == pull["created_at"]
    _assert_instant(read_back["created_at"], DEFAULT_CLOCK, "created_at")
    assert read_back["driver_id"] == driver["id"]
    assert read_back["result"] == "CLEAR"
    assert read_back["violation_points"] == 0
    _assert_instant(read_back["checked_on"], "2026-08-01T08:00:00Z", "checked_on")
    assert read_back["recorded_by_user_id"] == COMPLIANCE_OFFICER_USER_ID


def test_order_naming_another_stores_address_reports_the_address_as_missing():
    """An order that names an address belonging to a different store is refused as a
    missing address rather than as a scope error, and no order is written anywhere.

    PRD: "One body reference carries an extra ownership condition: an order's `service_address_id` must name an address belonging to the same store as the order's `store_id`, and an address belonging to a different store is reported as `ERR_SERVICE_ADDRESS_NOT_FOUND` rather than as a scope error."
    Design: Corner/entities/order_creation_against_an_address_of_another_store_is_not_found
    """
    first_store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    first_address = fx.add_address(first_store["id"], "A")
    second_store = fx.register_store(store_number="7422", name="Hillside")
    fx.publish_active_zone_version(second_store["id"])

    response = api_client.create_order(
        f.create_order_payload(second_store["id"], first_address["id"]),
        DISPATCHER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_ADDRESS_NOT_FOUND.value)
    assert response.status_code == 404

    for store_id in (first_store["id"], second_store["id"]):
        orders, meta = validate_paginated(
            api_client.list_orders(DISPATCHER_HEADERS, {"store_id": store_id})
        )
        assert orders == []
        assert meta["total_count"] == 0


def test_a_record_pull_under_an_unknown_driver_reports_the_driver_as_missing():
    """Recording a record pull under a driver identifier that resolves to nothing is
    refused as a missing driver and files no audit record.

    PRD: "Each maps to its own not-found error: `ERR_STORE_NOT_FOUND`, `ERR_ZONE_VERSION_NOT_FOUND`, `ERR_SERVICE_ADDRESS_NOT_FOUND`, `ERR_ADDRESS_DISPUTE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_MVR_CHECK_NOT_FOUND`, `ERR_INSURANCE_VERIFICATION_NOT_FOUND`, `ERR_VEHICLE_COST_MODEL_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_DISPATCH_STOP_NOT_FOUND`, `ERR_SAFE_DROP_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` and `ERR_REIMBURSEMENT_LINE_NOT_FOUND`, all returned with HTTP 404."
    Design: Corner/entities/mvr_check_under_an_unknown_driver_is_not_found
    """
    fx.set_clock(DEFAULT_CLOCK)
    fx.register_store(store_number="7421", name="Riverside")

    response = api_client.create_mvr_check(
        "22222222-2222-4222-8222-222222222222",
        f.create_mvr_check_payload(
            result="CLEAR", violation_points=0, checked_on="2026-08-01T08:00:00Z"
        ),
        COMPLIANCE_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DRIVER_NOT_FOUND.value)
    assert response.status_code == 404

    pulls, meta = validate_paginated(api_client.list_mvr_checks(COMPLIANCE_HEADERS))
    assert pulls == []
    assert meta["total_count"] == 0


def test_order_creation_answers_with_every_priced_field_already_computed():
    """The body that answers order creation already carries the tier, the surcharged
    base, the waiver, the charged fee and the total, so no read-back is needed.

    PRD: "A 15-minute address at a store charging 399 cents, with 2200 cents of food and a 500-cent tip, lands in `BASE` with a 399-cent surcharged base, a waiver of 50, a charged fee of 200 cents (399 halved is 199.5, which rounds half up to 200) and a total of 2900 cents."
    Design: Corner/consistency_model/the_order_creation_response_already_carries_every_priced_field
    """
    store, _zone_version = fx.bootstrap(NOON_CLOCK)
    store_id = store["id"]
    address = fx.add_address(store_id, "A")
    assert store["delivery_fee_cents"] == 399
    assert address["drive_time_estimate_minutes"] == 15

    order = _object_envelope(
        api_client.create_order(
            f.create_order_payload(
                store_id,
                address["id"],
                food_subtotal_cents=2200,
                tip_cents=500,
                payment_method="CARD",
            ),
            DISPATCHER_HEADERS,
        ),
        201,
    )

    a.assert_order(order)
    expected = a.expected_order_pricing(15, 399, 2200, 500)
    assert order["fee_tier"] == "BASE" == expected["fee_tier"]
    assert order["base_delivery_fee_cents"] == 399 == expected["base_delivery_fee_cents"]
    assert order["fee_waiver_pct"] == 50 == expected["fee_waiver_pct"]
    assert order["delivery_fee_cents"] == 200 == expected["delivery_fee_cents"]
    assert order["total_charge_cents"] == 2900 == expected["total_charge_cents"]
    assert order["food_subtotal_cents"] == 2200
    assert order["tip_cents"] == 500
    assert order["promise_minutes_snapshot"] == 30
    _assert_instant(order["placed_at"], NOON_CLOCK, "placed_at")

    read_back = _object_envelope(api_client.get_order(order["id"], CARE_HEADERS), 200)
    assert read_back["fee_tier"] == "BASE"
    assert read_back["base_delivery_fee_cents"] == 399
    assert read_back["fee_waiver_pct"] == 50
    assert read_back["delivery_fee_cents"] == 200
    assert read_back["total_charge_cents"] == 2900
    assert read_back["order_to_door_gross_minutes"] is None


def test_committing_a_route_answers_with_the_whole_route_projection():
    """The body that answers a route commitment already carries the route minutes, the
    expected return instant, the snapshotted reimbursement schedule and the estimated
    reimbursement, with the actual figure still unset.

    PRD: "Committing a route therefore writes four fields at once: `route_minutes` and `expected_return_at` from the round-trip model, `resolved_cost_model_id` from the selector, and `estimated_reimbursement_cents` from the estimated variant of the waterfall."
    Design: Corner/consistency_model/the_lock_response_already_carries_the_whole_route_projection
    """
    world = fx.setup_operational_store(clock=NOON_CLOCK, address_keys=("A",))
    store_id = world["store"]["id"]
    address = world["addresses"]["A"]
    order = fx.add_ready_order(store_id, address["id"])
    dispatch = fx.open_dispatch(world["driver"]["id"], "2026-08-05T12:05:00Z")
    fx.stack_stop(dispatch["id"], order["id"], 1)
    assert address["grid_miles"] == 3.00

    locked = _object_envelope(api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS), 200)

    a.assert_dispatch(locked)
    assert locked["status"] == "LOCKED"
    assert locked["stop_count"] == 1
    assert (
        locked["route_minutes"]
        == 24
        == a.expected_route_minutes(
            [3.00],
            TEST_ZONE_MODEL["minutes_per_mile"],
            STORE_DEFAULTS["handoff_minutes_per_stop"],
        )
    )
    _assert_instant(
        locked["expected_return_at"],
        a.instant_plus("2026-08-05T12:05:00Z", minutes=24),
        "expected_return_at",
    )
    _assert_instant(locked["expected_return_at"], "2026-08-05T12:29:00Z", "expected_return_at")
    assert locked["resolved_cost_model_id"] == world["cost_model"]["id"]
    assert (
        locked["estimated_reimbursement_cents"]
        == 336
        == a.expected_reimbursement_from_model([3.00], CAR_COST_MODEL)
    )
    assert locked["actual_reimbursement_cents"] is None
    assert locked["reimbursement_variance_cents"] is None

    read_back = _object_envelope(api_client.get_dispatch(dispatch["id"], DISPATCHER_HEADERS), 200)
    assert read_back["status"] == "LOCKED"
    assert read_back["route_minutes"] == 24
    _assert_instant(read_back["expected_return_at"], "2026-08-05T12:29:00Z", "expected_return_at")
    assert read_back["resolved_cost_model_id"] == world["cost_model"]["id"]
    assert read_back["estimated_reimbursement_cents"] == 336
    assert read_back["actual_reimbursement_cents"] is None

    lines, meta = validate_paginated(
        api_client.list_reimbursement_lines(
            world["manager_headers"], {"dispatch_id": dispatch["id"]}
        )
    )
    assert lines == []
    assert meta["total_count"] == 0
