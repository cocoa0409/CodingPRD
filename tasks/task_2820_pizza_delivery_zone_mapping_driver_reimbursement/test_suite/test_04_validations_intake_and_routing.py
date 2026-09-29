"""Refusals along the intake and routing path of the Store Operations API.

Every test here fires one request that the PRD says must be refused, pins the
exact error identifier the PRD names for that condition (its HTTP status being
fixed by the error catalogue of §5), and then proves the refusal was silent: the
targeted entity's status and `version` have not moved and no child record was
created. Boundary refusals additionally pin the neighbouring value that the PRD
says must be accepted, so an inclusive/exclusive edge cannot be misplaced. The
conditions covered are the domain-shape rules on a freshly supplied polygon,
delivery-area window and insurance-coverage window; the two uniqueness rules; the
requirement for a delivery-area version actually in force; the three mirror-image
zone-decision refusals plus the service-posture gate read at clearance time; the
stop-insertion gates on order readiness, the stacking cap and cross-store
association; the aggregate hot-bag and fee-disclosure gates on commitment; and
the outstanding-stop gate on check-in.
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
    ADDRESS_COORDS,
    CAR_COST_MODEL,
    DEFAULT_CLOCK,
    NOON_CLOCK,
    TEST_POLYGON,
    TEST_ZONE_MODEL,
    ZONE_EFFECTIVE_FROM,
    ZONE_EFFECTIVE_TO,
)
from test_helpers.test_users import (
    BOOTSTRAP_MANAGER_HEADERS,
    COMPLIANCE_HEADERS,
    DISPATCHER_HEADERS,
    make_driver_headers,
    make_manager_headers,
)

# The planned departure every routing scenario below leaves at, five minutes
# after the mid-day working instant.
DEPART_AT = "2026-08-05T12:05:00Z"


def test_publishing_a_two_vertex_ring_is_rejected_as_an_invalid_polygon():
    """A ring of only two vertices is refused as an invalid polygon and stores nothing.

    PRD: "Fewer than three vertices is rejected as `ERR_INVALID_POLYGON`, and an `effective_to` that is not strictly later than `effective_from` is rejected as `ERR_INVALID_ZONE_WINDOW`."
    Design: Corner/validations/polygon_and_window_schema_violations_are_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    fx.hire_driver(store_id)
    before = fx.read_store(store_id)

    payload = f.create_zone_version_payload(
        store_id,
        before["version"],
        polygon=f.polygon_from_pairs(
            [(38900000, -84200000), (39200000, -84200000)]
        ),
        effective_from=ZONE_EFFECTIVE_FROM,
        effective_to=ZONE_EFFECTIVE_TO,
    )
    validate_error(
        api_client.create_zone_version(payload, make_manager_headers(store_id)),
        ApiErrorId.ERR_INVALID_POLYGON.value,
    )

    _versions, meta = validate_paginated(
        api_client.list_zone_versions(DISPATCHER_HEADERS, {"store_id": store_id})
    )
    assert meta["total_count"] == 0, "a refused publication stores no delivery-area version"
    after = fx.read_store(store_id)
    assert after["version"] == before["version"]
    assert after["active_zone_version_number"] is None


def test_publishing_a_zero_length_effective_window_is_rejected():
    """An effective_to equal to effective_from fails the strictly-after test.

    PRD: "Fewer than three vertices is rejected as `ERR_INVALID_POLYGON`, and an `effective_to` that is not strictly later than `effective_from` is rejected as `ERR_INVALID_ZONE_WINDOW`."
    Design: Corner/validations/polygon_and_window_schema_violations_are_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    fx.hire_driver(store_id)
    before = fx.read_store(store_id)

    payload = f.create_zone_version_payload(
        store_id,
        before["version"],
        polygon=[dict(vertex) for vertex in TEST_POLYGON],
        effective_from=ZONE_EFFECTIVE_FROM,
        effective_to=ZONE_EFFECTIVE_FROM,
    )
    validate_error(
        api_client.create_zone_version(payload, make_manager_headers(store_id)),
        ApiErrorId.ERR_INVALID_ZONE_WINDOW.value,
    )

    _versions, meta = validate_paginated(
        api_client.list_zone_versions(DISPATCHER_HEADERS, {"store_id": store_id})
    )
    assert meta["total_count"] == 0
    after = fx.read_store(store_id)
    assert after["version"] == before["version"]
    assert after["active_zone_version_number"] is None


def test_filing_a_backwards_coverage_window_is_rejected():
    """A coverage_to earlier than coverage_from is refused and files no certificate.

    PRD: "A `coverage_to` that is not strictly later than `coverage_from` is refused with `ERR_INVALID_COVERAGE_WINDOW`."
    Design: Corner/validations/polygon_and_window_schema_violations_are_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    driver = fx.hire_driver(store["id"])
    driver_id = driver["id"]
    before = fx.read_driver(driver_id)
    assert before["insurance_status"] == "NONE"

    payload = f.create_insurance_verification_payload(
        before["version"],
        policy_number="POL-9001",
        coverage_from="2026-08-01T00:00:00Z",
        coverage_to="2026-07-01T00:00:00Z",
        liability_limit_cents=10000000,
    )
    validate_error(
        api_client.create_insurance_verification(driver_id, payload, COMPLIANCE_HEADERS),
        ApiErrorId.ERR_INVALID_COVERAGE_WINDOW.value,
    )

    _certificates, meta = validate_paginated(
        api_client.list_insurance_verifications(COMPLIANCE_HEADERS, {"driver_id": driver_id})
    )
    assert meta["total_count"] == 0, "a refused filing stores no certificate"
    after = fx.read_driver(driver_id)
    assert after["insurance_status"] == "NONE"
    assert after["qualification_status"] == "APPLICANT"
    assert after["version"] == before["version"]


def test_registering_a_second_store_with_a_taken_store_number_is_rejected():
    """store_number is unique across every store, so a second 7421 is refused.

    PRD: "Uniqueness: `store_number` is globally unique across stores and `license_number` is unique within its store, yielding `ERR_STORE_NUMBER_TAKEN` or `ERR_LICENSE_NUMBER_TAKEN` (both 409) — on store registration, store policy edits and driver creation."
    Design: Corner/validations/duplicate_store_number_and_license_number_are_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store(store_number="7421", name="Riverside")
    store_id = store["id"]

    collision = f.create_store_payload(
        store_number="7421",
        name="Lakeside",
        latitude_micro=39100000,
        longitude_micro=-84100000,
    )
    validate_error(
        api_client.create_store(collision, BOOTSTRAP_MANAGER_HEADERS),
        ApiErrorId.ERR_STORE_NUMBER_TAKEN.value,
    )

    after = fx.read_store(store_id)
    assert after["store_number"] == "7421"
    assert after["name"] == "Riverside", "the incumbent store is untouched by the refusal"
    assert after["version"] == store["version"]


def test_hiring_a_second_driver_with_a_taken_licence_number_is_rejected():
    """license_number is unique within its store, so a second DL-1001 is refused.

    PRD: "Uniqueness: `store_number` is globally unique across stores and `license_number` is unique within its store, yielding `ERR_STORE_NUMBER_TAKEN` or `ERR_LICENSE_NUMBER_TAKEN` (both 409) — on store registration, store policy edits and driver creation."
    Design: Corner/validations/duplicate_store_number_and_license_number_are_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store(store_number="7421", name="Riverside")
    store_id = store["id"]
    driver = fx.hire_driver(store_id, full_name="Dana Ortiz", license_number="DL-1001")

    collision = f.create_driver_payload(
        store_id,
        full_name="Eli Vance",
        license_number="DL-1001",
        vehicle_class="SCOOTER",
    )
    validate_error(
        api_client.create_driver(collision, make_manager_headers(store_id)),
        ApiErrorId.ERR_LICENSE_NUMBER_TAKEN.value,
    )

    drivers, meta = validate_paginated(
        api_client.list_drivers(DISPATCHER_HEADERS, {"store_id": store_id})
    )
    assert meta["total_count"] == 1, "only the original driver exists"
    assert drivers[0]["id"] == driver["id"]
    assert drivers[0]["license_number"] == "DL-1001"
    assert drivers[0]["vehicle_class"] == "CAR"
    assert drivers[0]["version"] == driver["version"]


def test_filing_an_address_against_a_draft_only_delivery_area_is_rejected():
    """A published but never activated delivery area classifies nothing.

    PRD: "Filing fails with `ERR_NO_ACTIVE_ZONE_VERSION` when the store has no `ACTIVE` delivery-area version whose window contains the logical clock, because there is nothing to classify against."
    Design: Corner/validations/address_creation_with_only_a_draft_zone_version_is_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    draft = fx.publish_zone_version(store_id, **TEST_ZONE_MODEL)
    assert draft["status"] == "DRAFT"

    latitude_micro, longitude_micro = ADDRESS_COORDS["A"]
    payload = f.create_service_address_payload(
        store_id, latitude_micro, longitude_micro, line1="12 Oak St", crosses_barrier=False
    )
    validate_error(
        api_client.create_service_address(payload, DISPATCHER_HEADERS),
        ApiErrorId.ERR_NO_ACTIVE_ZONE_VERSION.value,
    )

    unchanged = validate_success(
        api_client.get_zone_version(draft["id"], DISPATCHER_HEADERS), 200
    )
    assert unchanged["status"] == "DRAFT", "the refusal does not put the draft in force"
    assert unchanged["activated_at"] is None
    assert unchanged["version"] == draft["version"]
    _addresses, meta = validate_paginated(
        api_client.list_service_addresses(DISPATCHER_HEADERS, {"store_id": store_id})
    )
    assert meta["total_count"] == 0, "no unclassified address is left behind"


def test_the_same_address_filing_succeeds_once_the_delivery_area_is_in_force():
    """Activating the same version is all it takes for the identical filing to classify.

    PRD: "On success the address records `evaluated_zone_version_number`, the `version_number` of the version that did the classifying, and `evaluated_at`, the logical-clock instant of the evaluation."
    Design: Corner/validations/address_creation_with_only_a_draft_zone_version_is_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    draft = fx.publish_zone_version(store_id, **TEST_ZONE_MODEL)
    active = fx.activate_zone_version(draft["id"], store_id)
    assert active["status"] == "ACTIVE"

    latitude_micro, longitude_micro = ADDRESS_COORDS["A"]
    payload = f.create_service_address_payload(
        store_id, latitude_micro, longitude_micro, line1="12 Oak St", crosses_barrier=False
    )
    address = validate_success(
        api_client.create_service_address(payload, DISPATCHER_HEADERS), 201
    )
    assert address["zone_state"] == "IN_ZONE"
    assert address["effective_zone_state"] == "IN_ZONE"
    assert address["grid_miles"] == 3.00
    assert address["drive_time_estimate_minutes"] == 15
    assert address["evaluated_zone_version_number"] == 1
    a.assert_iso_millis(address["evaluated_at"], "evaluated_at")


def test_clearing_an_order_to_an_out_of_area_address_is_rejected():
    """An address the model puts outside the area cannot be cleared for delivery.

    PRD: "And the destination's `effective_zone_state` must read `IN_ZONE`, or the request fails with `ERR_ADDRESS_OUT_OF_AREA` — which for a parked edge address means the clearance can only succeed while a granted dispute's `override_until` is still strictly ahead of the clock."
    Design: Corner/validations/clearing_an_out_of_area_order_is_rejected
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    address = fx.add_address(store_id, "C")
    assert address["zone_state"] == "OUT_OF_ZONE"
    assert address["effective_zone_state"] == "OUT_OF_ZONE"
    assert address["grid_miles"] == 26.67
    assert address["drive_time_estimate_minutes"] == 87

    order = fx.place_order(store_id, address["id"])
    assert order["fulfillment_status"] == "PLACED"

    validate_error(
        api_client.zone_decision(
            order["id"], f.zone_decision_payload("CLEAR"), DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_ADDRESS_OUT_OF_AREA.value,
    )

    after = fx.read_order(order["id"])
    assert after["fulfillment_status"] == "PLACED", "the refused clearance moves nothing"
    assert after["settlement_status"] == "UNDISCLOSED"
    assert after["zone_held_at"] is None
    assert after["declined_reason"] is None
    assert after["version"] == order["version"]
    assert fx.read_store(store_id)["unassigned_order_count"] == 0


def test_holding_an_in_zone_order_is_rejected():
    """An address the model already accepts cannot be parked for review.

    PRD: "It requires the address's `effective_zone_state` to be `EDGE` or `OUT_OF_ZONE`; an address the model already accepts cannot be parked for review and yields `ERR_ZONE_HOLD_NOT_APPLICABLE` — the exact mirror image of the clearance rule."
    Design: Corner/validations/zone_hold_and_decline_on_an_in_zone_order_are_rejected
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    address = fx.add_address(store_id, "A")
    assert address["effective_zone_state"] == "IN_ZONE"
    order = fx.place_order(store_id, address["id"])

    validate_error(
        api_client.zone_decision(
            order["id"], f.zone_decision_payload("HOLD"), DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_ZONE_HOLD_NOT_APPLICABLE.value,
    )

    after = fx.read_order(order["id"])
    assert after["fulfillment_status"] == "PLACED"
    assert after["zone_held_at"] is None
    assert after["version"] == order["version"]

    cleared = validate_success(
        api_client.zone_decision(
            order["id"], f.zone_decision_payload("CLEAR"), DISPATCHER_HEADERS
        ),
        200,
    )
    assert cleared["fulfillment_status"] == "ZONE_CLEARED", "the mirror decision is accepted"
    assert cleared["version"] == order["version"] + 1


def test_declining_an_in_zone_order_is_rejected():
    """The store owes an in-zone address a delivery, so it cannot decline one.

    PRD: "It likewise requires an `effective_zone_state` of `EDGE` or `OUT_OF_ZONE`, refusing an in-zone address with `ERR_DECLINE_NOT_APPLICABLE`, since the store owes an in-zone address a delivery."
    Design: Corner/validations/zone_hold_and_decline_on_an_in_zone_order_are_rejected
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    address = fx.add_address(store_id, "A")
    order = fx.place_order(store_id, address["id"])

    validate_error(
        api_client.zone_decision(
            order["id"], f.zone_decision_payload("DECLINE"), DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_DECLINE_NOT_APPLICABLE.value,
    )

    after = fx.read_order(order["id"])
    assert after["fulfillment_status"] == "PLACED", "the ticket is not turned away"
    assert after["settlement_status"] == "UNDISCLOSED"
    assert after["declined_reason"] is None
    assert after["version"] == order["version"]


def test_redirecting_an_in_zone_order_to_carryout_is_rejected():
    """A carryout-only posture does not make redirection available for an in-zone address.

    PRD: "`REDIRECT_CARRYOUT` offers the customer the counter instead of the car, advancing the order to the terminal `CARRYOUT_REDIRECTED` from either `PLACED` or `ZONE_HELD` under the same `EDGE`-or-`OUT_OF_ZONE` requirement and the same `ERR_DECLINE_NOT_APPLICABLE` refusal."
    Design: Corner/validations/clearing_after_the_store_switches_to_carryout_only_is_rejected
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    address = fx.add_address(store_id, "A")
    order = fx.place_order(store_id, address["id"])
    assert fx.edit_store(store_id, service_posture="CARRYOUT_ONLY")["service_posture"] == (
        "CARRYOUT_ONLY"
    )

    validate_error(
        api_client.zone_decision(
            order["id"], f.zone_decision_payload("REDIRECT_CARRYOUT"), DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_DECLINE_NOT_APPLICABLE.value,
    )

    after = fx.read_order(order["id"])
    assert after["fulfillment_status"] == "PLACED"
    assert after["settlement_status"] == "UNDISCLOSED"
    assert after["declined_reason"] is None
    assert after["version"] == order["version"]


def test_clearing_after_the_posture_moves_to_carryout_only_is_rejected():
    """A posture change after intake blocks the clearance of an in-zone order.

    PRD: "The store's `service_posture` must be `OPEN`; a `CLOSED` or `CARRYOUT_ONLY` store clears nothing and is refused with `ERR_STORE_NOT_ACCEPTING_DELIVERY`, a case that arises when the posture was changed after the order was taken."
    Design: Corner/validations/clearing_after_the_store_switches_to_carryout_only_is_rejected
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    address = fx.add_address(store_id, "A")
    order = fx.place_order(store_id, address["id"])
    assert order["fulfillment_status"] == "PLACED"

    edited = fx.edit_store(store_id, service_posture="CARRYOUT_ONLY")
    assert edited["service_posture"] == "CARRYOUT_ONLY"

    validate_error(
        api_client.zone_decision(
            order["id"], f.zone_decision_payload("CLEAR"), DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_STORE_NOT_ACCEPTING_DELIVERY.value,
    )

    after = fx.read_order(order["id"])
    assert after["fulfillment_status"] == "PLACED", "an order taken while open simply waits"
    assert after["declined_reason"] is None
    assert after["version"] == order["version"]
    assert fx.read_address(address["id"])["effective_zone_state"] == "IN_ZONE"
    assert fx.read_store(store_id)["unassigned_order_count"] == 0


def test_stacking_a_zone_cleared_order_is_rejected_as_not_ready():
    """A cleared, disclosed ticket that never reached the make line cannot be stacked.

    PRD: "The referenced order's fulfillment status must be exactly `READY`, or the insertion is refused with `ERR_ORDER_NOT_READY`; that order must also not be voided on the settlement dimension, a condition the `READY` requirement subsumes in practice, since a voided ticket has a terminal fulfillment status."
    Design: Corner/validations/stacking_an_order_that_is_not_ready_is_rejected
    """
    world = fx.setup_operational_store(clock=NOON_CLOCK, address_keys=("A",))
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    address = world["addresses"]["A"]

    placed = fx.place_order(store_id, address["id"])
    fx.decide_zone(placed["id"], "CLEAR")
    fx.disclose_fee(placed)
    order = fx.read_order(placed["id"])
    assert order["fulfillment_status"] == "ZONE_CLEARED"
    assert order["settlement_status"] == "DISCLOSED"

    dispatch = fx.open_dispatch(driver_id, DEPART_AT)
    assert dispatch["status"] == "DRAFT"

    validate_error(
        api_client.create_dispatch_stop(
            dispatch["id"], f.create_dispatch_stop_payload(order["id"], 1), DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_ORDER_NOT_READY.value,
    )

    after_dispatch = fx.read_dispatch(dispatch["id"])
    assert after_dispatch["status"] == "DRAFT"
    assert after_dispatch["stop_count"] == 0
    assert after_dispatch["committed_hot_bag_slots"] == 0
    assert after_dispatch["version"] == dispatch["version"]
    _stops, meta = validate_paginated(
        api_client.list_dispatch_stops(DISPATCHER_HEADERS, {"dispatch_id": dispatch["id"]})
    )
    assert meta["total_count"] == 0, "no stop record is written by the refusal"
    after_order = fx.read_order(order["id"])
    assert after_order["fulfillment_status"] == "ZONE_CLEARED"
    assert after_order["version"] == order["version"]


def test_restacking_an_assigned_order_reports_the_not_ready_refusal():
    """An order already carried by a pending stop is no longer READY, so it cannot be stacked again.

    PRD: "The order named in a route-stop insertion has fulfillment status `READY`, else `ERR_ORDER_NOT_READY` (409) — on route-stop insertion."
    Design: Corner/validations/restacking_an_assigned_order_reports_the_not_ready_error_because_priority_26_outranks_27
    """
    world = fx.setup_route(
        "STACKED", ("A",), clock=NOON_CLOCK, planned_depart_at=DEPART_AT, hot_bag_slots=[1]
    )
    dispatch_id = world["dispatch"]["id"]
    order = fx.read_order(world["orders"][0]["id"])
    assert order["fulfillment_status"] == "ASSIGNED"
    first_stop = world["stops"][0]
    assert first_stop["sequence"] == 1
    dispatch_before = fx.read_dispatch(dispatch_id)
    assert dispatch_before["stop_count"] == 1
    assert dispatch_before["committed_hot_bag_slots"] == 1

    validate_error(
        api_client.create_dispatch_stop(
            dispatch_id, f.create_dispatch_stop_payload(order["id"], 1), DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_ORDER_NOT_READY.value,
    )

    after_dispatch = fx.read_dispatch(dispatch_id)
    assert after_dispatch["status"] == "STACKED"
    assert after_dispatch["stop_count"] == 1, "the second insertion adds nothing"
    assert after_dispatch["committed_hot_bag_slots"] == 1
    assert after_dispatch["version"] == dispatch_before["version"]
    stops, meta = validate_paginated(
        api_client.list_dispatch_stops(DISPATCHER_HEADERS, {"dispatch_id": dispatch_id})
    )
    assert meta["total_count"] == 1
    assert stops[0]["id"] == first_stop["id"]
    assert stops[0]["status"] == "PENDING"
    after_order = fx.read_order(order["id"])
    assert after_order["fulfillment_status"] == "ASSIGNED"
    assert after_order["version"] == order["version"]


def test_second_stop_beyond_a_one_stop_cap_is_rejected():
    """A store that allows one stop per trip refuses the second insertion.

    PRD: "Inserting must not push the route's `stop_count` beyond the store's `max_stacked_stops`, or the insertion is refused with `ERR_STACK_LIMIT_EXCEEDED`."
    Design: Corner/validations/stacking_beyond_the_store_stack_limit_is_rejected
    """
    world = fx.setup_operational_store(
        clock=NOON_CLOCK, address_keys=("A",), store_overrides={"max_stacked_stops": 1}
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    address = world["addresses"]["A"]
    assert world["store"]["max_stacked_stops"] == 1

    first_order = fx.add_ready_order(store_id, address["id"])
    second_order = fx.add_ready_order(store_id, address["id"])
    dispatch = fx.open_dispatch(driver_id, DEPART_AT)
    fx.stack_stop(dispatch["id"], first_order["id"], 1)
    dispatch_before = fx.read_dispatch(dispatch["id"])
    assert dispatch_before["stop_count"] == 1

    validate_error(
        api_client.create_dispatch_stop(
            dispatch["id"],
            f.create_dispatch_stop_payload(second_order["id"], 1),
            DISPATCHER_HEADERS,
        ),
        ApiErrorId.ERR_STACK_LIMIT_EXCEEDED.value,
    )

    after_dispatch = fx.read_dispatch(dispatch["id"])
    assert after_dispatch["stop_count"] == 1, "the capped route keeps its single stop"
    assert after_dispatch["committed_hot_bag_slots"] == 1
    assert after_dispatch["version"] == dispatch_before["version"]
    _stops, meta = validate_paginated(
        api_client.list_dispatch_stops(DISPATCHER_HEADERS, {"dispatch_id": dispatch["id"]})
    )
    assert meta["total_count"] == 1
    after_second = fx.read_order(second_order["id"])
    assert after_second["fulfillment_status"] == "READY"
    assert after_second["version"] == second_order["version"]


def test_second_stop_is_accepted_once_the_cap_is_raised_to_two():
    """Raising max_stacked_stops to two is all the identical second insertion needs.

    PRD: "Inserting must not push the route's `stop_count` beyond the store's `max_stacked_stops`, or the insertion is refused with `ERR_STACK_LIMIT_EXCEEDED`."
    Design: Corner/validations/stacking_beyond_the_store_stack_limit_is_rejected
    """
    world = fx.setup_operational_store(
        clock=NOON_CLOCK, address_keys=("A",), store_overrides={"max_stacked_stops": 1}
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    address = world["addresses"]["A"]

    first_order = fx.add_ready_order(store_id, address["id"])
    second_order = fx.add_ready_order(store_id, address["id"])
    dispatch = fx.open_dispatch(driver_id, DEPART_AT)
    fx.stack_stop(dispatch["id"], first_order["id"], 1)

    raised = fx.edit_store(store_id, max_stacked_stops=2)
    assert raised["max_stacked_stops"] == 2

    stop = validate_success(
        api_client.create_dispatch_stop(
            dispatch["id"],
            f.create_dispatch_stop_payload(second_order["id"], 1),
            DISPATCHER_HEADERS,
        ),
        201,
    )
    assert stop["sequence"] == 2, "the accepted stop takes the next sequence number"
    assert stop["status"] == "PENDING"
    assert stop["hot_bag_slots"] == 1

    after_dispatch = fx.read_dispatch(dispatch["id"])
    assert after_dispatch["status"] == "STACKED"
    assert after_dispatch["stop_count"] == 2
    assert after_dispatch["committed_hot_bag_slots"] == 2
    assert fx.read_order(second_order["id"])["fulfillment_status"] == "ASSIGNED"


def test_stacking_an_order_from_another_store_is_rejected():
    """Both records exist, so a cross-store insertion is refused as an association error.

    PRD: "The referenced order must belong to the same store as the route's driver, or the insertion is refused with `ERR_ORDER_STORE_MISMATCH` — both records exist, so this is a refusal of the association, not a not-found."
    Design: Corner/validations/stacking_an_order_belonging_to_another_store_is_rejected
    """
    world = fx.setup_operational_store(clock=NOON_CLOCK, address_keys=("A",))
    driver_id = world["driver"]["id"]

    other_store = fx.register_store(
        store_number="7422",
        name="Lakeside",
        latitude_micro=39100000,
        longitude_micro=-84100000,
    )
    other_store_id = other_store["id"]
    fx.publish_active_zone_version(other_store_id)
    other_address = fx.add_address_at(
        other_store_id, 39130000, -84115000, line1="5 Lake St"
    )
    assert other_address["effective_zone_state"] == "IN_ZONE"
    other_order = fx.add_ready_order(
        other_store_id,
        other_address["id"],
        tip_cents=0,
        customer_name="Cara",
        customer_phone="555-0103",
    )
    assert other_order["fulfillment_status"] == "READY"

    dispatch = fx.open_dispatch(driver_id, DEPART_AT)

    validate_error(
        api_client.create_dispatch_stop(
            dispatch["id"],
            f.create_dispatch_stop_payload(other_order["id"], 1),
            DISPATCHER_HEADERS,
        ),
        ApiErrorId.ERR_ORDER_STORE_MISMATCH.value,
    )

    after_dispatch = fx.read_dispatch(dispatch["id"])
    assert after_dispatch["status"] == "DRAFT", "the other store's route stays empty"
    assert after_dispatch["stop_count"] == 0
    assert after_dispatch["committed_hot_bag_slots"] == 0
    assert after_dispatch["version"] == dispatch["version"]
    _stops, meta = validate_paginated(
        api_client.list_dispatch_stops(DISPATCHER_HEADERS, {"dispatch_id": dispatch["id"]})
    )
    assert meta["total_count"] == 0
    after_order = fx.read_order(other_order["id"])
    assert after_order["fulfillment_status"] == "READY"
    assert after_order["version"] == other_order["version"]


def test_locking_a_route_committing_three_slots_against_two_bags_is_rejected():
    """A route asking for three bag slots from a two-bag shelf cannot be committed.

    PRD: "The store's bag pool must accommodate the route: taking every route of the same store whose status is `LOCKED` or `EN_ROUTE` and whose half-open reservation window from `planned_depart_at` inclusive to `expected_return_at` exclusive intersects this route's window, the sum of their `committed_hot_bag_slots` plus this route's own `committed_hot_bag_slots` must not exceed the store's `hot_bag_count`, or the commitment is refused with `ERR_HOT_BAG_CAPACITY_EXCEEDED`."
    Design: Corner/validations/locking_a_route_whose_own_stops_exceed_the_hot_bag_pool_is_rejected
    """
    world = fx.setup_operational_store(
        clock=NOON_CLOCK,
        address_keys=("A",),
        store_overrides={"hot_bag_count": 2, "max_stacked_stops": 3},
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    address = world["addresses"]["A"]
    assert world["store"]["hot_bag_count"] == 2

    first_order = fx.add_ready_order(store_id, address["id"])
    second_order = fx.add_ready_order(store_id, address["id"])
    dispatch = fx.open_dispatch(driver_id, DEPART_AT)
    fx.stack_stop(dispatch["id"], first_order["id"], 2)
    fx.stack_stop(dispatch["id"], second_order["id"], 1)
    before = fx.read_dispatch(dispatch["id"])
    assert before["status"] == "STACKED"
    assert before["committed_hot_bag_slots"] == 3

    validate_error(
        api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_HOT_BAG_CAPACITY_EXCEEDED.value,
    )

    after = fx.read_dispatch(dispatch["id"])
    assert after["status"] == "STACKED", "a refused commitment leaves the route stacked"
    assert after["committed_hot_bag_slots"] == 3
    assert after["route_minutes"] is None
    assert after["expected_return_at"] is None
    assert after["resolved_cost_model_id"] is None
    assert after["estimated_reimbursement_cents"] is None
    assert after["version"] == before["version"]


def test_locking_succeeds_when_the_route_commits_exactly_the_two_bags_available():
    """Releasing the two-slot stop and re-inserting it for one slot lets the commitment through.

    PRD: "The store's bag pool must accommodate the route: taking every route of the same store whose status is `LOCKED` or `EN_ROUTE` and whose half-open reservation window from `planned_depart_at` inclusive to `expected_return_at` exclusive intersects this route's window, the sum of their `committed_hot_bag_slots` plus this route's own `committed_hot_bag_slots` must not exceed the store's `hot_bag_count`, or the commitment is refused with `ERR_HOT_BAG_CAPACITY_EXCEEDED`."
    Design: Corner/validations/locking_a_route_whose_own_stops_exceed_the_hot_bag_pool_is_rejected
    """
    world = fx.setup_operational_store(
        clock=NOON_CLOCK,
        address_keys=("A",),
        store_overrides={"hot_bag_count": 2, "max_stacked_stops": 3},
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    address = world["addresses"]["A"]

    first_order = fx.add_ready_order(store_id, address["id"])
    second_order = fx.add_ready_order(store_id, address["id"])
    dispatch = fx.open_dispatch(driver_id, DEPART_AT)
    first_stop = fx.stack_stop(dispatch["id"], first_order["id"], 2)
    fx.stack_stop(dispatch["id"], second_order["id"], 1)
    released = fx.unstack_stop(dispatch["id"], first_stop["id"])
    assert released["committed_hot_bag_slots"] == 1, "the pool returns to its pre-insertion total"
    replacement = fx.stack_stop(dispatch["id"], first_order["id"], 1)
    assert replacement["sequence"] == 3, "a released ordinal is never reused"
    before = fx.read_dispatch(dispatch["id"])
    assert before["committed_hot_bag_slots"] == 2

    locked = validate_success(api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS), 200)
    assert locked["status"] == "LOCKED"
    assert locked["committed_hot_bag_slots"] == 2
    assert locked["stop_count"] == 2
    assert locked["route_minutes"] == 39
    assert locked["route_minutes"] == a.expected_route_minutes([3.00, 3.00], 3, 6)
    assert locked["estimated_reimbursement_cents"] == 651
    assert locked["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [3.00, 3.00], CAR_COST_MODEL
    )
    assert locked["resolved_cost_model_id"] == world["cost_model"]["id"]
    assert a.parse_instant(locked["expected_return_at"]) == a.parse_instant(
        a.instant_plus(DEPART_AT, minutes=39)
    )


def test_locking_a_route_carrying_an_undisclosed_ticket_is_rejected():
    """Disclosure gates the commitment, so an unquoted ticket blocks the lock.

    PRD: "Every counted stop's order must have a settlement status of `DISCLOSED` or `CHARGED`, or the commitment is refused with `ERR_FEE_NOT_DISCLOSED`: fee-versus-tip disclosure is a gate on dispatch rather than on delivery, so nothing rolls until every ticket on the route has been quoted to its customer."
    Design: Corner/validations/locking_a_route_carrying_an_undisclosed_order_is_rejected
    """
    world = fx.setup_operational_store(clock=NOON_CLOCK, address_keys=("A",))
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    address = world["addresses"]["A"]

    order = fx.add_ready_order(store_id, address["id"], disclose=False)
    assert order["fulfillment_status"] == "READY"
    assert order["settlement_status"] == "UNDISCLOSED"

    dispatch = fx.open_dispatch(driver_id, DEPART_AT)
    fx.stack_stop(dispatch["id"], order["id"], 1)
    before = fx.read_dispatch(dispatch["id"])
    assert before["status"] == "STACKED"

    validate_error(
        api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_FEE_NOT_DISCLOSED.value,
    )

    after = fx.read_dispatch(dispatch["id"])
    assert after["status"] == "STACKED"
    assert after["route_minutes"] is None
    assert after["expected_return_at"] is None
    assert after["resolved_cost_model_id"] is None
    assert after["estimated_reimbursement_cents"] is None
    assert after["version"] == before["version"]
    assert fx.read_order(order["id"])["settlement_status"] == "UNDISCLOSED"


def test_locking_succeeds_once_the_outstanding_ticket_is_disclosed():
    """Quoting the fee to the customer is all the identical commitment needs.

    PRD: "Every counted stop's order must have a settlement status of `DISCLOSED` or `CHARGED`, or the commitment is refused with `ERR_FEE_NOT_DISCLOSED`: fee-versus-tip disclosure is a gate on dispatch rather than on delivery, so nothing rolls until every ticket on the route has been quoted to its customer."
    Design: Corner/validations/locking_a_route_carrying_an_undisclosed_order_is_rejected
    """
    world = fx.setup_operational_store(clock=NOON_CLOCK, address_keys=("A",))
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    address = world["addresses"]["A"]

    order = fx.add_ready_order(store_id, address["id"], disclose=False)
    dispatch = fx.open_dispatch(driver_id, DEPART_AT)
    fx.stack_stop(dispatch["id"], order["id"], 1)

    disclosed = fx.disclose_fee(order)
    assert disclosed["settlement_status"] == "DISCLOSED"

    locked = validate_success(api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS), 200)
    assert locked["status"] == "LOCKED"
    assert locked["stop_count"] == 1
    assert locked["committed_hot_bag_slots"] == 1
    assert locked["route_minutes"] == 24
    assert locked["route_minutes"] == a.expected_route_minutes([3.00], 3, 6)
    assert locked["estimated_reimbursement_cents"] == 336
    assert locked["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [3.00], CAR_COST_MODEL
    )
    assert locked["resolved_cost_model_id"] == world["cost_model"]["id"]
    assert a.parse_instant(locked["expected_return_at"]) == a.parse_instant(
        a.instant_plus(DEPART_AT, minutes=24)
    )


def test_checking_in_a_route_with_a_pending_stop_is_rejected():
    """A driver cannot check in while one of the two doors is still unopened.

    PRD: "Every stop on the route must have reached a terminal stop status — `DELIVERED`, `RELEASED` or `REMADE` — or the check-in is refused with `ERR_STOPS_OUTSTANDING`, because a driver cannot come back while a pizza is still in the bag."
    Design: Corner/validations/returning_with_a_stop_still_pending_is_rejected
    """
    world = fx.setup_route(
        "EN_ROUTE",
        ("A", "A"),
        clock=NOON_CLOCK,
        planned_depart_at=DEPART_AT,
        hot_bag_slots=[1, 1],
    )
    dispatch_id = world["dispatch"]["id"]
    driver_id = world["driver"]["id"]
    first_stop, second_stop = world["stops"]

    fx.set_clock("2026-08-05T12:20:00Z")
    delivered = fx.arrive_at_door(dispatch_id, first_stop["id"], driver_id, 3.4, None)
    assert delivered["status"] == "DELIVERED"
    assert delivered["actual_miles"] == 3.40
    before = fx.read_dispatch(dispatch_id)
    assert before["status"] == "EN_ROUTE"

    validate_error(
        api_client.return_dispatch(dispatch_id, make_driver_headers(driver_id)),
        ApiErrorId.ERR_STOPS_OUTSTANDING.value,
    )

    after = fx.read_dispatch(dispatch_id)
    assert after["status"] == "EN_ROUTE", "the route stays out on the road"
    assert after["returned_at"] is None
    assert after["actual_reimbursement_cents"] is None
    assert after["reimbursement_variance_cents"] is None
    assert after["committed_hot_bag_slots"] == 2, "the bags are still reserved"
    assert after["version"] == before["version"]
    assert fx.read_stop(second_stop["id"])["status"] == "PENDING"
    assert fx.read_driver(driver_id)["reimbursement_accrued_cents"] == 0
