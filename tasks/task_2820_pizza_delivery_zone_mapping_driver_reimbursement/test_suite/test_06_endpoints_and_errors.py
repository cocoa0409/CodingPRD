"""Endpoint-contract and error-contract behaviour of the Store Operations API.

The first half pins per-endpoint contracts the PRD states in prose rather than in
a formula: a store-policy edit is a partial update that touches only the fields
the request names and advances the store's version by exactly one; the manager's
cash-reconciliation read re-derives the conservation identity from live stop and
safe-drop state; a fee disclosure whose quote does not match the computed fee is
recorded rather than rejected; opening an address dispute links the dispute to the
address without disturbing the address's own classification; and a carryout
redirect out of a parked order freezes the hold clock, voids the settlement
dimension and lands the order in a terminal state.

The second half pins the error contract itself: every path variable owns its own
not-found identifier, so the path segment rather than the shape of the identifier
decides the code; a stop that exists but hangs off a different route is not found
under the route named to its left; and a second attempt at a transition that has
already happened is refused with the state error of the entity named by the last
path segment, leaving every figure the first attempt moved exactly where it was.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers import assertions as a
from test_helpers.constants import DEFAULT_CLOCK, NOON_CLOCK
from test_helpers.test_users import (
    CARE_HEADERS,
    COMPLIANCE_HEADERS,
    DISPATCHER_HEADERS,
    make_driver_headers,
    make_manager_headers,
)


# --- Store policy edits -------------------------------------------------------


def test_store_policy_edit_touches_only_the_fields_the_request_names():
    """A policy edit naming two fields moves those two and leaves the rest of the
    policy at the defaults registration accepted silently.

    PRD: "Store policy can be edited later, and every field except the coordinates is editable: `store_number`, `name`, `promise_minutes`, `delivery_fee_cents`, `cash_limit_cents`, `hot_bag_count`, `max_stacked_stops`, `handoff_minutes_per_stop`, `dispatch_reset_buffer_minutes` and `service_posture` are each optional on the edit, and the uniqueness rule on `store_number` applies to the edit exactly as it applies to registration."
    Design: Corner/endpoints/store_policy_patch_is_a_partial_update_that_bumps_the_version
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store(store_number="7421", name="Riverside")
    store_id = store["id"]

    edited = validate_success(
        api_client.update_store(
            store_id,
            f.update_store_payload(delivery_fee_cents=449, hot_bag_count=6),
            make_manager_headers(store_id),
        ),
        200,
    )

    assert edited["delivery_fee_cents"] == 449
    assert edited["hot_bag_count"] == 6
    assert edited["promise_minutes"] == 30
    assert edited["service_posture"] == "OPEN"
    assert edited["max_stacked_stops"] == 3
    assert edited["cash_limit_cents"] == 5000
    assert edited["store_number"] == "7421"
    assert edited["name"] == "Riverside"

    read_back = fx.read_store(store_id, DISPATCHER_HEADERS)
    assert read_back["delivery_fee_cents"] == 449
    assert read_back["hot_bag_count"] == 6
    assert read_back["max_stacked_stops"] == 3
    assert read_back["cash_limit_cents"] == 5000
    assert read_back["handoff_minutes_per_stop"] == 6
    assert read_back["dispatch_reset_buffer_minutes"] == 10


def test_one_store_policy_edit_advances_the_version_by_exactly_one():
    """One edit carrying two changed fields is one increment of the store version,
    not one per field, and the read agrees with the write.

    PRD: "An edit increments the store's `version` by 1."
    Design: Corner/endpoints/store_policy_patch_is_a_partial_update_that_bumps_the_version
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store(store_number="7421", name="Riverside")
    store_id = store["id"]
    version_before = store["version"]

    edited = validate_success(
        api_client.update_store(
            store_id,
            f.update_store_payload(delivery_fee_cents=449, hot_bag_count=6),
            make_manager_headers(store_id),
        ),
        200,
    )

    assert edited["version"] == version_before + 1
    assert fx.read_store(store_id, DISPATCHER_HEADERS)["version"] == version_before + 1


def test_a_store_policy_edit_leaves_the_computed_totals_to_the_read():
    """The four figures a store read re-derives are not reset or frozen by a policy
    edit; the read still recomputes them from live state.

    PRD: "A store's `cash_collected_total_cents`, `safe_deposit_total_cents`, `unassigned_order_count` and `active_zone_version_number` are all recomputed when the store is read."
    Design: Corner/endpoints/store_policy_patch_is_a_partial_update_that_bumps_the_version
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store(store_number="7421", name="Riverside")
    store_id = store["id"]

    validate_success(
        api_client.update_store(
            store_id,
            f.update_store_payload(delivery_fee_cents=449, hot_bag_count=6),
            make_manager_headers(store_id),
        ),
        200,
    )

    read_back = validate_success(api_client.get_store(store_id, DISPATCHER_HEADERS), 200)
    assert read_back["cash_collected_total_cents"] == 0
    assert read_back["safe_deposit_total_cents"] == 0
    assert read_back["unassigned_order_count"] == 0
    assert read_back["active_zone_version_number"] is None


# --- The cash reconciliation read ---------------------------------------------


def _cash_order_delivered_at_the_door():
    """Drive one CASH order on address A through a 12:36:00Z door arrival.

    The ticket is 2200 cents of food, a 200-cent charged fee and a 500-cent tip,
    so the driver takes 2900 cents of the customer's cash at the door.
    """
    world = fx.setup_route(
        "EN_ROUTE",
        ("A",),
        clock=NOON_CLOCK,
        planned_depart_at="2026-08-05T12:05:00Z",
        order_overrides={"payment_method": "CASH"},
    )
    assert world["orders"][0]["total_charge_cents"] == 2900
    fx.set_clock("2026-08-05T12:36:00Z")
    fx.arrive_at_door(
        world["dispatch"]["id"],
        world["stops"][0]["id"],
        world["driver"]["id"],
        3.4,
        2900,
    )
    return world


def test_the_cash_reconciliation_read_recomputes_the_conservation_identity():
    """After 2900 cents at the door and a 1900-cent drop the reconciliation read
    reports 2900 collected, 1900 in the safe, 1000 in the pouch and reconciled.

    PRD: "It returns the store's `store_id`, its `cash_collected_total_cents`, its `safe_deposit_total_cents`, the summed `driver_cash_on_hand_total_cents` across the store's drivers, and a `reconciled` flag that is true exactly when the collected total equals the safe-deposit total plus the drivers' combined cash on hand."
    Design: Corner/endpoints/cash_reconciliation_read_recomputes_the_conservation_identity
    """
    world = _cash_order_delivered_at_the_door()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    fx.record_safe_drop(driver_id, 1900, envelope_number="ENV-007")

    reconciliation = validate_success(
        api_client.get_cash_reconciliation(store_id, make_manager_headers(store_id)), 200
    )

    assert reconciliation["store_id"] == store_id
    assert reconciliation["cash_collected_total_cents"] == 2900
    assert reconciliation["safe_deposit_total_cents"] == 1900
    assert reconciliation["driver_cash_on_hand_total_cents"] == 1000
    assert reconciliation["reconciled"] is True
    a.assert_cash_conservation(reconciliation)


def test_the_reconciliation_read_agrees_with_the_driver_own_pouch_figure():
    """The store-level cash-on-hand total is the same 1000 cents the driver read
    re-derives, and 1000 leaves the driver clear of the 5000-cent limit.

    PRD: "The driver's `cash_posture` is `DROP_REQUIRED` when `cash_on_hand_cents` is greater than or equal to the owning store's `cash_limit_cents`, and `CLEAR` otherwise."
    Design: Corner/endpoints/cash_reconciliation_read_recomputes_the_conservation_identity
    """
    world = _cash_order_delivered_at_the_door()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    fx.record_safe_drop(driver_id, 1900, envelope_number="ENV-007")

    manager_headers = make_manager_headers(store_id)
    reconciliation = validate_success(
        api_client.get_cash_reconciliation(store_id, manager_headers), 200
    )
    driver = validate_success(api_client.get_driver(driver_id, manager_headers), 200)

    assert driver["cash_on_hand_cents"] == 1000
    assert driver["cash_posture"] == "CLEAR"
    assert reconciliation["driver_cash_on_hand_total_cents"] == driver["cash_on_hand_cents"]


# --- Fee disclosure -----------------------------------------------------------


def _order_awaiting_disclosure():
    """One freshly taken CARD order on address A, priced at a 200-cent fee."""
    store, _zone_version = fx.bootstrap(NOON_CLOCK)
    address = fx.add_address(store["id"], "A")
    order = fx.place_order(store["id"], address["id"])
    assert order["delivery_fee_cents"] == 200
    assert order["tip_cents"] == 500
    return store, order


def test_an_inaccurate_fee_disclosure_is_recorded_rather_than_rejected():
    """A 999-cent quote against a 200-cent fee with no tip notice succeeds with
    HTTP 200 and is filed as an inaccurate disclosure.

    PRD: "A mis-quote is deliberately **recorded rather than rejected** — the request succeeds — because the record of the inaccuracy is what a later fee-disclosure complaint is priced against."
    Design: Corner/endpoints/fee_disclosure_records_an_inaccurate_disclosure_instead_of_rejecting_it
    """
    _store, order = _order_awaiting_disclosure()

    disclosed = validate_success(
        api_client.disclose_fee(
            order["id"], f.disclose_fee_payload(999, 500, False), DISPATCHER_HEADERS
        ),
        200,
    )

    assert disclosed["settlement_status"] == "DISCLOSED"
    assert disclosed["disclosed_fee_cents"] == 999
    assert disclosed["disclosed_tip_cents"] == 500
    assert disclosed["driver_tip_notice_given"] is False
    assert disclosed["fee_disclosure_accurate"] is False
    assert disclosed["delivery_fee_cents"] == 200


def test_an_accurate_disclosure_moves_only_the_settlement_dimension():
    """A matching quote with the tip notice given reads back accurate, stamps the
    disclosure instant from the clock and leaves the fulfillment dimension alone.

    PRD: "On success `fee_disclosed_at` is stamped from the logical clock and `fee_disclosure_accurate` is computed: it is true only when `disclosed_fee_cents` equals the order's computed `delivery_fee_cents`, `disclosed_tip_cents` equals the order's `tip_cents`, and `driver_tip_notice_given` is true; it is false when any of those three fails, and it is null before disclosure has happened at all."
    Design: Corner/endpoints/fee_disclosure_records_an_inaccurate_disclosure_instead_of_rejecting_it
    """
    _store, order = _order_awaiting_disclosure()
    assert order["fee_disclosure_accurate"] is None

    disclosed = validate_success(
        api_client.disclose_fee(order["id"], f.disclose_fee_payload(200, 500, True), CARE_HEADERS),
        200,
    )

    assert disclosed["disclosed_fee_cents"] == 200
    assert disclosed["fee_disclosure_accurate"] is True
    assert disclosed["settlement_status"] == "DISCLOSED"
    assert disclosed["fulfillment_status"] == "PLACED"
    a.assert_iso_millis(disclosed["fee_disclosed_at"], "fee_disclosed_at")
    assert disclosed["fee_disclosed_at"] == "2026-08-05T12:00:00.000Z"


def test_disclosing_the_fee_twice_is_an_invalid_order_state():
    """Disclosure is declared only out of an undisclosed settlement dimension, so a
    second quote on an already disclosed order is refused.

    PRD: "The action advances the settlement dimension `UNDISCLOSED → DISCLOSED` and requires the settlement dimension to be exactly `UNDISCLOSED`; it also requires the fulfillment dimension to be none of `DECLINED_OUT_OF_AREA`, `CARRYOUT_REDIRECTED` or `CLOSED`."
    Design: Corner/endpoints/fee_disclosure_records_an_inaccurate_disclosure_instead_of_rejecting_it
    """
    _store, order = _order_awaiting_disclosure()
    fx.disclose_fee(order)

    validate_error(
        api_client.disclose_fee(order["id"], f.disclose_fee_payload(200, 500, True), CARE_HEADERS),
        ApiErrorId.ERR_INVALID_ORDER_STATE.value,
    )

    unchanged = fx.read_order(order["id"])
    assert unchanged["settlement_status"] == "DISCLOSED"
    assert unchanged["disclosed_fee_cents"] == 200


# --- Opening an address dispute ------------------------------------------------


def _store_with_an_edge_and_an_in_zone_address():
    """A store in force with the edge address E and the in-zone address A filed."""
    store, _zone_version = fx.bootstrap(NOON_CLOCK)
    edge = fx.add_address(store["id"], "E", line1="1 Ring Rd")
    in_zone = fx.add_address(store["id"], "A", line1="12 Oak St")
    assert edge["zone_state"] == "EDGE"
    assert in_zone["zone_state"] == "IN_ZONE"
    return store, edge, in_zone


def test_opening_a_dispute_links_it_to_the_named_address_and_starts_submitted():
    """A new dispute answers 201, carries the address it names, and opens with an
    empty review history.

    PRD: "A new dispute begins in `SUBMITTED` status with `review_round_count` at 0, `resolution` null, `decided_at` null and `reviewer_user_id` null."
    Design: Corner/endpoints/opening_a_dispute_links_it_to_the_address_without_altering_the_address
    """
    _store, edge, _in_zone = _store_with_an_edge_and_an_in_zone_address()

    dispute = validate_success(
        api_client.create_address_dispute(
            f.create_address_dispute_payload(
                edge["id"],
                claimed_state="IN_ZONE",
                evidence_note="Customer says the driveway is inside the ring",
            ),
            CARE_HEADERS,
        ),
        201,
    )

    assert dispute["service_address_id"] == edge["id"]
    assert dispute["claimed_state"] == "IN_ZONE"
    assert dispute["status"] == "SUBMITTED"
    assert dispute["review_round_count"] == 0
    assert dispute["resolution"] is None
    assert dispute["decided_at"] is None
    assert dispute["reviewer_user_id"] is None


def test_an_open_dispute_leaves_the_address_classification_untouched():
    """A dispute merely claims the address is in zone; until it is granted the
    address still reads EDGE with no override recorded.

    PRD: "The address's `effective_zone_state` is what every downstream rule actually consults, and it is re-derived on every read rather than stored: when `override_state` is not null and `override_until` is strictly later than the logical clock, the effective state is the `override_state`; in every other case — no override recorded, or an override whose expiry the clock has reached — the effective state falls back to the stored `zone_state`."
    Design: Corner/endpoints/opening_a_dispute_links_it_to_the_address_without_altering_the_address
    """
    _store, edge, _in_zone = _store_with_an_edge_and_an_in_zone_address()
    validate_success(
        api_client.create_address_dispute(
            f.create_address_dispute_payload(edge["id"]), CARE_HEADERS
        ),
        201,
    )

    read_back = validate_success(api_client.get_service_address(edge["id"], CARE_HEADERS), 200)

    assert read_back["drive_time_estimate_minutes"] == 46
    assert read_back["zone_state"] == "EDGE"
    assert read_back["override_state"] is None
    assert read_back["override_until"] is None
    assert read_back["effective_zone_state"] == "EDGE"


def test_the_dispute_list_scopes_to_the_disputed_service_address():
    """Filtering the dispute collection by service address returns the one dispute
    on the edge address and nothing at all for the untouched in-zone address.

    PRD: "Disputes accept `service_address_id` and `status`."
    Design: Corner/endpoints/opening_a_dispute_links_it_to_the_address_without_altering_the_address
    """
    store, edge, in_zone = _store_with_an_edge_and_an_in_zone_address()
    dispute = fx.open_dispute(edge["id"])
    manager_headers = make_manager_headers(store["id"])

    on_edge, edge_meta = validate_paginated(
        api_client.list_address_disputes(manager_headers, {"service_address_id": edge["id"]})
    )
    on_in_zone, in_zone_meta = validate_paginated(
        api_client.list_address_disputes(manager_headers, {"service_address_id": in_zone["id"]})
    )

    assert edge_meta["total_count"] == 1
    assert [entry["id"] for entry in on_edge] == [dispute["id"]]
    assert in_zone_meta["total_count"] == 0
    assert on_in_zone == []


def test_a_dispute_naming_an_unknown_address_is_a_service_address_not_found():
    """Both sides of the link have to exist, so a body reference to an absent
    address is reported as an address that cannot be found.

    PRD: "Body-level references are checked on delivery-area version creation, service-address creation, driver creation, vehicle-cost-model creation, order creation, dispute creation, route-stop insertion and complaint creation, and they report the same not-found error identifiers listed above."
    Design: Corner/endpoints/opening_a_dispute_links_it_to_the_address_without_altering_the_address
    """
    _store, _edge, _in_zone = _store_with_an_edge_and_an_in_zone_address()

    validate_error(
        api_client.create_address_dispute(
            f.create_address_dispute_payload(NON_EXISTENT_UUID), CARE_HEADERS
        ),
        ApiErrorId.ERR_SERVICE_ADDRESS_NOT_FOUND.value,
    )


# --- Redirecting a parked order to the counter ---------------------------------


def _order_parked_on_the_edge():
    """One order parked on the edge address at 12:00:00Z, read at 12:08:00Z."""
    store, _zone_version = fx.bootstrap(NOON_CLOCK)
    edge = fx.add_address(store["id"], "E", line1="1 Ring Rd")
    order = fx.place_order(store["id"], edge["id"])
    parked = fx.decide_zone(order["id"], "HOLD")
    assert parked["fulfillment_status"] == "ZONE_HELD"
    assert parked["zone_held_at"] == "2026-08-05T12:00:00.000Z"
    fx.set_clock("2026-08-05T12:08:00Z")
    return store, edge, order


def test_a_carryout_redirect_out_of_a_parked_order_voids_the_settlement_side():
    """Offering the counter to a parked edge order answers 200, banks the eight
    minutes the order spent parked, and voids the settlement dimension.

    PRD: "It accrues `zone_hold_minutes` on the same terms when `zone_held_at` is not null, records `declined_reason` as `DRIVE_TIME_EXCEEDED`, and drives the settlement dimension to `VOIDED`."
    Design: Corner/endpoints/carryout_redirect_is_reachable_only_from_a_zone_held_order
    """
    _store, _edge, order = _order_parked_on_the_edge()

    redirected = validate_success(
        api_client.zone_decision(
            order["id"], f.zone_decision_payload("REDIRECT_CARRYOUT"), DISPATCHER_HEADERS
        ),
        200,
    )

    assert redirected["fulfillment_status"] == "CARRYOUT_REDIRECTED"
    assert redirected["settlement_status"] == "VOIDED"
    assert redirected["zone_hold_minutes"] == 8
    assert redirected["declined_reason"] == "DRIVE_TIME_EXCEEDED"


def test_production_cannot_start_on_a_redirected_order():
    """CARRYOUT_REDIRECTED is terminal on the fulfillment dimension, so the make
    line has nothing left to declare.

    PRD: "Any order action requested from a status that does not declare it is rejected with `ERR_INVALID_ORDER_STATE`."
    Design: Corner/endpoints/carryout_redirect_is_reachable_only_from_a_zone_held_order
    """
    _store, _edge, order = _order_parked_on_the_edge()
    fx.decide_zone(order["id"], "REDIRECT_CARRYOUT")

    validate_error(
        api_client.production(order["id"], f.production_payload("START"), DISPATCHER_HEADERS),
        ApiErrorId.ERR_INVALID_ORDER_STATE.value,
    )

    assert fx.read_order(order["id"])["fulfillment_status"] == "CARRYOUT_REDIRECTED"


def test_a_carryout_redirect_needs_an_edge_or_out_of_zone_destination():
    """The same redirect on an order whose address reads in zone has no fringe to
    redirect away from and is refused.

    PRD: "`REDIRECT_CARRYOUT` offers the customer the counter instead of the car, advancing the order to the terminal `CARRYOUT_REDIRECTED` from either `PLACED` or `ZONE_HELD` under the same `EDGE`-or-`OUT_OF_ZONE` requirement and the same `ERR_DECLINE_NOT_APPLICABLE` refusal."
    Design: Corner/endpoints/carryout_redirect_is_reachable_only_from_a_zone_held_order
    """
    store, _zone_version = fx.bootstrap(NOON_CLOCK)
    in_zone = fx.add_address(store["id"], "A", line1="12 Oak St")
    order = fx.place_order(store["id"], in_zone["id"])
    assert order["fulfillment_status"] == "PLACED"

    validate_error(
        api_client.zone_decision(
            order["id"], f.zone_decision_payload("REDIRECT_CARRYOUT"), DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_DECLINE_NOT_APPLICABLE.value,
    )

    unchanged = fx.read_order(order["id"])
    assert unchanged["fulfillment_status"] == "PLACED"
    assert unchanged["declined_reason"] is None


# --- Type-scoped not-found identifiers -----------------------------------------


def _store_and_hired_driver():
    """A registered store and one freshly hired driver, both real identifiers."""
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store(store_number="7421", name="Riverside")
    driver = fx.hire_driver(store["id"], full_name="Dana Ortiz", license_number="DL-1001")
    return store, driver


def test_each_read_surface_reports_its_own_not_found_identifier():
    """The same absent identifier read through eight different collections yields
    eight different error identifiers, one per path variable.

    PRD: "Each maps to its own not-found error: `ERR_STORE_NOT_FOUND`, `ERR_ZONE_VERSION_NOT_FOUND`, `ERR_SERVICE_ADDRESS_NOT_FOUND`, `ERR_ADDRESS_DISPUTE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_MVR_CHECK_NOT_FOUND`, `ERR_INSURANCE_VERIFICATION_NOT_FOUND`, `ERR_VEHICLE_COST_MODEL_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_DISPATCH_STOP_NOT_FOUND`, `ERR_SAFE_DROP_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` and `ERR_REIMBURSEMENT_LINE_NOT_FOUND`, all returned with HTTP 404."
    Design: Corner/errors/every_unknown_id_read_returns_its_own_entity_specific_not_found
    """
    _store_and_hired_driver()

    validate_error(
        api_client.get_zone_version(NON_EXISTENT_UUID, DISPATCHER_HEADERS),
        ApiErrorId.ERR_ZONE_VERSION_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_address_dispute(NON_EXISTENT_UUID, DISPATCHER_HEADERS),
        ApiErrorId.ERR_ADDRESS_DISPUTE_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_vehicle_cost_model(NON_EXISTENT_UUID, DISPATCHER_HEADERS),
        ApiErrorId.ERR_VEHICLE_COST_MODEL_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_insurance_verification(NON_EXISTENT_UUID, COMPLIANCE_HEADERS),
        ApiErrorId.ERR_INSURANCE_VERIFICATION_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_dispatch_stop(NON_EXISTENT_UUID, DISPATCHER_HEADERS),
        ApiErrorId.ERR_DISPATCH_STOP_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_reimbursement_line(NON_EXISTENT_UUID, COMPLIANCE_HEADERS),
        ApiErrorId.ERR_REIMBURSEMENT_LINE_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_safe_drop(NON_EXISTENT_UUID, DISPATCHER_HEADERS),
        ApiErrorId.ERR_SAFE_DROP_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_complaint(NON_EXISTENT_UUID, CARE_HEADERS),
        ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value,
    )


def test_a_real_store_identifier_is_not_an_mvr_check_identifier():
    """Reading the record-pull collection with a live store identifier reports the
    pull as missing rather than the store, because the path segment picks the code.

    PRD: "Each maps to its own not-found error: `ERR_STORE_NOT_FOUND`, `ERR_ZONE_VERSION_NOT_FOUND`, `ERR_SERVICE_ADDRESS_NOT_FOUND`, `ERR_ADDRESS_DISPUTE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_MVR_CHECK_NOT_FOUND`, `ERR_INSURANCE_VERIFICATION_NOT_FOUND`, `ERR_VEHICLE_COST_MODEL_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_DISPATCH_STOP_NOT_FOUND`, `ERR_SAFE_DROP_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` and `ERR_REIMBURSEMENT_LINE_NOT_FOUND`, all returned with HTTP 404."
    Design: Corner/errors/every_unknown_id_read_returns_its_own_entity_specific_not_found
    """
    store, _driver = _store_and_hired_driver()

    validate_error(
        api_client.get_mvr_check(store["id"], COMPLIANCE_HEADERS),
        ApiErrorId.ERR_MVR_CHECK_NOT_FOUND.value,
    )


def test_a_real_driver_identifier_is_not_an_order_identifier():
    """Reading the order collection with a live driver identifier reports the order
    as missing rather than the driver.

    PRD: "Each maps to its own not-found error: `ERR_STORE_NOT_FOUND`, `ERR_ZONE_VERSION_NOT_FOUND`, `ERR_SERVICE_ADDRESS_NOT_FOUND`, `ERR_ADDRESS_DISPUTE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_MVR_CHECK_NOT_FOUND`, `ERR_INSURANCE_VERIFICATION_NOT_FOUND`, `ERR_VEHICLE_COST_MODEL_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_DISPATCH_STOP_NOT_FOUND`, `ERR_SAFE_DROP_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` and `ERR_REIMBURSEMENT_LINE_NOT_FOUND`, all returned with HTTP 404."
    Design: Corner/errors/every_unknown_id_read_returns_its_own_entity_specific_not_found
    """
    _store, driver = _store_and_hired_driver()

    validate_error(
        api_client.get_order(driver["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_ORDER_NOT_FOUND.value,
    )


# --- A stop that hangs off a different route ------------------------------------


def _two_routes_one_of_them_out_of_the_door():
    """Two qualified drivers, one departed route and one still-stacked route whose
    single stop belongs to the second driver's trip."""
    world = fx.setup_operational_store(clock=NOON_CLOCK, address_keys=("A",))
    store_id = world["store"]["id"]
    driver_one = world["driver"]
    driver_two = fx.add_qualified_driver(
        store_id, full_name="Rex Vale", license_number="DL-1002"
    )
    address = world["addresses"]["A"]
    order_one = fx.add_ready_order(store_id, address["id"])
    order_two = fx.add_ready_order(store_id, address["id"])

    route_a = fx.open_dispatch(driver_one["id"], "2026-08-05T12:05:00Z")
    route_b = fx.open_dispatch(driver_two["id"], "2026-08-05T13:30:00Z")
    fx.stack_stop(route_a["id"], order_one["id"], 1)
    stop_b = fx.stack_stop(route_b["id"], order_two["id"], 1)
    fx.lock_route(route_a["id"])
    fx.depart_route(route_a["id"], driver_one["id"])

    return {
        "store_id": store_id,
        "driver_one": driver_one,
        "route_a": route_a,
        "route_b": route_b,
        "stop_b": stop_b,
        "order_two": order_two,
    }


def test_a_door_arrival_naming_another_routes_stop_is_a_stop_not_found():
    """The driver of the departed route knocking on a stop that belongs to the other
    route is told the stop does not exist, not that its state is wrong.

    PRD: "A stop identifier that does exist but belongs to a different route than the one named earlier in the same path is treated as not found under this rule — it is not reported as a mismatch of any other kind."
    Design: Corner/errors/a_stop_of_another_dispatch_is_not_found_under_this_dispatch
    """
    scene = _two_routes_one_of_them_out_of_the_door()

    validate_error(
        api_client.door_arrival(
            scene["route_a"]["id"],
            scene["stop_b"]["id"],
            f.door_arrival_payload(3.4),
            make_driver_headers(scene["driver_one"]["id"]),
        ),
        ApiErrorId.ERR_DISPATCH_STOP_NOT_FOUND.value,
    )


def test_removing_another_routes_stop_through_this_route_is_a_stop_not_found():
    """Un-stacking through the wrong parent route reports the stop as missing under
    the route named to its left.

    PRD: "A stop identifier that does exist but belongs to a different route than the one named earlier in the same path is treated as not found under this rule — it is not reported as a mismatch of any other kind."
    Design: Corner/errors/a_stop_of_another_dispatch_is_not_found_under_this_dispatch
    """
    scene = _two_routes_one_of_them_out_of_the_door()

    validate_error(
        api_client.delete_dispatch_stop(
            scene["route_a"]["id"], scene["stop_b"]["id"], DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_DISPATCH_STOP_NOT_FOUND.value,
    )


def test_a_misdirected_stop_call_leaves_the_stop_and_its_route_untouched():
    """Neither misdirected call touches anything: the stop is still pending on its
    own route, its order is still assigned and the route still counts one stop.

    PRD: "Rules are evaluated in the strict ascending order below; the first violated rule short-circuits the request, no later rule is evaluated, and **no side effect of any kind is applied**."
    Design: Corner/errors/a_stop_of_another_dispatch_is_not_found_under_this_dispatch
    """
    scene = _two_routes_one_of_them_out_of_the_door()
    validate_error(
        api_client.door_arrival(
            scene["route_a"]["id"],
            scene["stop_b"]["id"],
            f.door_arrival_payload(3.4),
            make_driver_headers(scene["driver_one"]["id"]),
        ),
        ApiErrorId.ERR_DISPATCH_STOP_NOT_FOUND.value,
    )
    validate_error(
        api_client.delete_dispatch_stop(
            scene["route_a"]["id"], scene["stop_b"]["id"], DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_DISPATCH_STOP_NOT_FOUND.value,
    )

    stop = validate_success(
        api_client.get_dispatch_stop(scene["stop_b"]["id"], DISPATCHER_HEADERS), 200
    )
    assert stop["status"] == "PENDING"
    assert stop["dispatch_id"] == scene["route_b"]["id"]
    assert stop["arrived_at"] is None
    assert fx.read_order(scene["order_two"]["id"])["fulfillment_status"] == "ASSIGNED"
    assert fx.read_dispatch(scene["route_b"]["id"])["stop_count"] == 1


# --- Removing a stop that has already been released ------------------------------


def _route_with_one_released_stop():
    """A two-stop stacked route whose first stop has already been un-stacked."""
    world = fx.setup_stacked_route(
        ("A", "A"),
        clock=NOON_CLOCK,
        planned_depart_at="2026-08-05T12:05:00Z",
        hot_bag_slots=(1, 1),
    )
    dispatch_id = world["dispatch"]["id"]
    released_stop = world["stops"][0]
    fx.unstack_stop(dispatch_id, released_stop["id"])
    return world, dispatch_id, released_stop


def test_removing_an_already_released_stop_is_an_invalid_stop_state():
    """Un-stacking requires the stop itself to be pending, so the second removal of
    the same stop is refused on the stop's own state.

    PRD: "Removing a stop requires the route to be `STACKED` and the stop itself to be `PENDING`; a stop in any other status is refused with `ERR_INVALID_STOP_STATE`."
    Design: Corner/errors/removing_an_already_released_stop_is_an_invalid_stop_state
    """
    _world, dispatch_id, released_stop = _route_with_one_released_stop()

    after_first = fx.read_stop(released_stop["id"])
    assert after_first["status"] == "RELEASED"
    assert after_first["sequence"] == 1

    validate_error(
        api_client.delete_dispatch_stop(dispatch_id, released_stop["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_INVALID_STOP_STATE.value,
    )


def test_the_refused_second_removal_does_not_double_revert_anything():
    """The compensating inverse ran once: the route still counts the surviving stop
    and one bag slot, and the released stop's order is ready rather than reverted twice.

    PRD: "The stop's status becomes `RELEASED`, its order reverts `ASSIGNED → READY`, and the route's `committed_hot_bag_slots` and `stop_count` both fall back to their pre-insertion values — the hot-bag pool must return to exactly the total it had before, which is why released stops stop being counted."
    Design: Corner/errors/removing_an_already_released_stop_is_an_invalid_stop_state
    """
    world, dispatch_id, released_stop = _route_with_one_released_stop()
    released_order = world["orders"][0]

    validate_error(
        api_client.delete_dispatch_stop(dispatch_id, released_stop["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_INVALID_STOP_STATE.value,
    )

    route = validate_success(api_client.get_dispatch(dispatch_id, DISPATCHER_HEADERS), 200)
    assert route["stop_count"] == 1
    assert route["committed_hot_bag_slots"] == 1
    assert route["status"] == "STACKED"
    assert fx.read_order(released_order["id"])["fulfillment_status"] == "READY"


def test_a_door_arrival_on_a_released_stop_is_an_invalid_stop_state():
    """The rule keys on the stop's status rather than on the endpoint, so once the
    route is out of the door the released stop still refuses a handoff.

    PRD: "The entity named by the **last** path parameter has its state checked here, and a violation on that entity pre-empts every business rule below it, including every fiscal rule."
    Design: Corner/errors/removing_an_already_released_stop_is_an_invalid_stop_state
    """
    world, dispatch_id, released_stop = _route_with_one_released_stop()
    driver_id = world["driver"]["id"]
    fx.lock_route(dispatch_id)
    fx.depart_route(dispatch_id, driver_id)

    validate_error(
        api_client.door_arrival(
            dispatch_id,
            released_stop["id"],
            f.door_arrival_payload(3.4),
            make_driver_headers(driver_id),
        ),
        ApiErrorId.ERR_INVALID_STOP_STATE.value,
    )

    assert fx.read_stop(released_stop["id"])["status"] == "RELEASED"


# --- Proposing a remedy twice on one complaint -----------------------------------


def _complaint_with_a_proposed_remedy():
    """A quality complaint on a delivered 2200-cent ticket, already sized once."""
    world = fx.setup_route(
        "EN_ROUTE", ("A",), clock=NOON_CLOCK, planned_depart_at="2026-08-05T12:05:00Z"
    )
    fx.set_clock("2026-08-05T12:36:00Z")
    fx.arrive_at_door(
        world["dispatch"]["id"], world["stops"][0]["id"], world["driver"]["id"], 3.4, 0
    )
    order = fx.read_order(world["orders"][0]["id"])
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["food_subtotal_cents"] == 2200

    complaint = fx.log_complaint(
        order["id"], "QUALITY", description="Wrong toppings on both pizzas"
    )
    proposed = fx.propose_remedy(complaint["id"])
    assert proposed["status"] == "REMEDY_PROPOSED"
    assert proposed["proposed_remedy_cents"] == 1100
    return world, order, complaint


def test_proposing_a_second_remedy_on_one_complaint_is_an_invalid_complaint_state():
    """Sizing the credit is declared only out of OPEN, so a complaint already at
    REMEDY_PROPOSED refuses a second proposal.

    PRD: "Complaint statuses are `OPEN`, `REMEDY_PROPOSED`, and the terminal `REMEDY_ISSUED` and `DISMISSED`; an action not declared from the current status is refused with `ERR_INVALID_COMPLAINT_STATE`."
    Design: Corner/errors/proposing_a_second_remedy_on_the_same_complaint_is_an_invalid_complaint_state
    """
    _world, _order, complaint = _complaint_with_a_proposed_remedy()

    validate_error(
        api_client.propose_remedy(complaint["id"], CARE_HEADERS),
        ApiErrorId.ERR_INVALID_COMPLAINT_STATE.value,
    )


def test_the_refused_proposal_leaves_the_sized_remedy_exactly_as_it_was():
    """The first sizing stands untouched at half the food subtotal, and a proposal
    has moved no money on the order.

    PRD: "For a `QUALITY` complaint the raw remedy is half of `food_subtotal_cents` — the subtotal multiplied by 50, divided by 100, rounded half up — and the `remedy_basis` is `QUALITY_HALF`."
    Design: Corner/errors/proposing_a_second_remedy_on_the_same_complaint_is_an_invalid_complaint_state
    """
    _world, order, complaint = _complaint_with_a_proposed_remedy()
    validate_error(
        api_client.propose_remedy(complaint["id"], CARE_HEADERS),
        ApiErrorId.ERR_INVALID_COMPLAINT_STATE.value,
    )

    read_back = validate_success(api_client.get_complaint(complaint["id"], CARE_HEADERS), 200)
    assert read_back["status"] == "REMEDY_PROPOSED"
    assert read_back["proposed_remedy_cents"] == 1100
    assert read_back["remedy_basis"] == "QUALITY_HALF"
    assert read_back["resolved_at"] is None
    assert fx.read_order(order["id"])["remedy_issued_cents"] == 0


# --- Voiding a safe drop that has already been voided ----------------------------


def _voided_safe_drop():
    """The whole 2900-cent pouch dropped at 12:36:00Z and voided at 12:40:00Z."""
    world = _cash_order_delivered_at_the_door()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    drop = fx.record_safe_drop(driver_id, 2900, envelope_number="ENV-011")
    assert drop["status"] == "RECORDED"

    fx.set_clock("2026-08-05T12:40:00Z")
    voided = fx.void_safe_drop(drop["id"], store_id, voided_reason="Envelope miscounted")
    assert voided["status"] == "VOIDED"
    a.assert_iso_millis(voided["voided_at"], "voided_at")
    assert voided["voided_at"] == "2026-08-05T12:40:00.000Z"
    return world, drop


def test_voiding_an_already_voided_drop_is_an_invalid_safe_drop_state():
    """VOIDED is the drop's terminal state, so a second void is refused and the
    second reason never overwrites the recorded one.

    PRD: "Voiding requires a `voided_reason` and advances the drop `RECORDED → VOIDED`, its only transition and its terminal state; voiding a drop that is already `VOIDED` is refused with `ERR_INVALID_SAFE_DROP_STATE`."
    Design: Corner/errors/voiding_an_already_voided_safe_drop_is_an_invalid_safe_drop_state
    """
    world, drop = _voided_safe_drop()
    store_id = world["store"]["id"]

    validate_error(
        api_client.void_safe_drop(
            drop["id"],
            f.void_safe_drop_payload(voided_reason="Second attempt"),
            make_manager_headers(store_id),
        ),
        ApiErrorId.ERR_INVALID_SAFE_DROP_STATE.value,
    )

    read_back = validate_success(
        api_client.get_safe_drop(drop["id"], make_manager_headers(store_id)), 200
    )
    assert read_back["status"] == "VOIDED"
    assert read_back["voided_reason"] == "Envelope miscounted"


def test_the_refused_second_void_swings_the_cash_only_once():
    """One void is one compensating swing: the safe is empty again, the whole 2900
    cents is back in the pouch, and the identity still holds.

    PRD: "A successful void stamps `voided_at` from the logical clock, records the `voided_reason`, and is the exact compensating inverse of the drop: the driver's `cash_on_hand_cents` rises by `amount_cents`, the store's `safe_deposit_total_cents` falls by the same figure, and both the driver's `version` and the store's `version` increment by 1."
    Design: Corner/errors/voiding_an_already_voided_safe_drop_is_an_invalid_safe_drop_state
    """
    world, drop = _voided_safe_drop()
    store_id = world["store"]["id"]
    manager_headers = make_manager_headers(store_id)

    validate_error(
        api_client.void_safe_drop(
            drop["id"],
            f.void_safe_drop_payload(voided_reason="Second attempt"),
            manager_headers,
        ),
        ApiErrorId.ERR_INVALID_SAFE_DROP_STATE.value,
    )

    reconciliation = validate_success(
        api_client.get_cash_reconciliation(store_id, manager_headers), 200
    )
    assert reconciliation["cash_collected_total_cents"] == 2900
    assert reconciliation["safe_deposit_total_cents"] == 0
    assert reconciliation["driver_cash_on_hand_total_cents"] == 2900
    assert reconciliation["reconciled"] is True
    a.assert_cash_conservation(reconciliation)


def test_a_fresh_drop_is_accepted_once_a_void_has_returned_the_cash():
    """Because the void put the whole 2900 cents back in the pouch, a replacement
    drop of the same amount is within what the ledger says is there.

    PRD: "The drop may not exceed what the ledger says is in the pouch: an `amount_cents` greater than the driver's `cash_on_hand_cents` is refused with `ERR_SAFE_DROP_EXCEEDS_CASH`, because a drop must never break the conservation identity."
    Design: Corner/errors/voiding_an_already_voided_safe_drop_is_an_invalid_safe_drop_state
    """
    world, _drop = _voided_safe_drop()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]

    replacement = validate_success(
        api_client.create_safe_drop(
            driver_id,
            f.create_safe_drop_payload(2900, envelope_number="ENV-012"),
            make_driver_headers(driver_id),
        ),
        201,
    )

    assert replacement["status"] == "RECORDED"
    assert replacement["amount_cents"] == 2900
    assert replacement["voided_at"] is None
    assert replacement["voided_reason"] is None
    reconciliation = validate_success(
        api_client.get_cash_reconciliation(store_id, make_manager_headers(store_id)), 200
    )
    assert reconciliation["safe_deposit_total_cents"] == 2900
    assert reconciliation["driver_cash_on_hand_total_cents"] == 0
