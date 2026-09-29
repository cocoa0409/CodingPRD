"""Which single error a multiply-invalid request reports, and how an operation on one
entity reads the live state of a neighbouring entity.

The first half of this module pins the Order of Refusal: each scenario builds a
request that breaks two rules at once and asserts that the higher rung wins, then
relieves only that higher rung and asserts the lower one now fires, so the suite
proves a ranking rather than merely that some error was raised. A refused request
applies no side effect of any kind, so every refusal is followed by a re-read that
shows the target's version did not move.

The second half pins dependencies that cross an entity boundary: a route commitment
reads its driver's live qualification status and the reimbursement schedule published
for that driver's vehicle class, and a zone clearance reads an address's effective
zone state, which is itself a function of a dispute's terminal state and the logical
clock. Each pair is exercised twice — once with the neighbour in the state the
operation requires, and once with only the neighbour's state flipped.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers import assertions as a
from test_helpers.constants import (
    CAR_COST_MODEL,
    DEFAULT_CLOCK,
    NOON_CLOCK,
    SCOOTER_COST_MODEL,
)
from test_helpers.test_users import (
    DISPATCHER_HEADERS,
    SECOND_COMPLIANCE_HEADERS,
    make_driver_headers,
    make_manager_headers,
)

# An address inside the ring, 170100 micro-degrees due north of the store origin,
# so 11.34 grid miles and a 41-minute modelled drive against a 40-minute ceiling:
# geometrically inside, therefore EDGE rather than OUT_OF_ZONE.
EDGE_ADDRESS_LAT_MICRO = 39170100
EDGE_ADDRESS_LON_MICRO = -84000000

# An address 15000 micro-degrees due north of the store origin: exactly 1.00 grid
# mile, a 9-minute drive, IN_ZONE.
ONE_MILE_LAT_MICRO = 39015000
ONE_MILE_LON_MICRO = -84000000


def _returned_route_with_a_driver_at_the_cash_limit():
    """A store whose cash limit is exactly 2900 cents, and a one-stop route already
    checked back in after collecting a 2900-cent cash ticket at its only door.

    The ticket is a 15-minute address at a store charging 399 cents with 2200 cents
    of food and a 500-cent tip, so the charged fee is 200 and the total is 2900. The
    driver therefore holds exactly the store's limit and reads DROP_REQUIRED, while
    the route sits in RETURNED, from which departure is not declared.
    """
    world = fx.setup_route(
        "RETURNED",
        ("A",),
        clock=NOON_CLOCK,
        store_overrides={"cash_limit_cents": 2900},
        planned_depart_at="2026-08-05T12:05:00Z",
        order_overrides={"payment_method": "CASH"},
        actual_miles=(3.4,),
    )
    driver = fx.read_driver(world["driver"]["id"])
    assert driver["cash_on_hand_cents"] == 2900
    assert driver["cash_posture"] == "DROP_REQUIRED"
    return world


def test_departing_a_returned_route_reports_the_route_state_and_never_the_cash_limit():
    """A departure that breaks both the route-state rule and the cash-limit rule reports
    the route state, with the 409 of the state rung rather than the 402 of the cash rung.

    PRD: "Because this rule sits below every state check, attempting to depart an already-checked-in route reports the route state, not the cash."
    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_error_outranks_cash_limit_error_on_depart
    """
    world = _returned_route_with_a_driver_at_the_cash_limit()
    driver_id = world["driver"]["id"]
    dispatch_id = world["dispatch"]["id"]

    before_dispatch = fx.read_dispatch(dispatch_id)
    before_driver = fx.read_driver(driver_id)
    assert before_dispatch["status"] == "RETURNED", "departure is not declared from RETURNED"
    assert before_driver["cash_posture"] == "DROP_REQUIRED", (
        "the fiscal rule is genuinely violated at the moment of the call"
    )

    response = api_client.depart_dispatch(dispatch_id, make_driver_headers(driver_id))
    assert response.status_code == 409, (
        "the route-state refusal carries 409; the cash-limit refusal it outranks carries 402"
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DISPATCH_STATE.value)

    after_dispatch = fx.read_dispatch(dispatch_id)
    after_driver = fx.read_driver(driver_id)
    assert after_dispatch["status"] == "RETURNED"
    assert after_dispatch["departed_at"] is not None, "the earlier successful departure stands"
    assert after_dispatch["version"] == before_dispatch["version"], (
        "a refused request applies no side effect of any kind"
    )
    assert after_driver["cash_on_hand_cents"] == 2900
    assert after_driver["version"] == before_driver["version"]


def test_cash_limit_refuses_departure_once_the_route_state_objection_is_lifted():
    """With the route-state objection lifted by a freshly committed route, the same driver
    holding exactly the store's limit is refused departure on the fiscal rule alone.

    PRD: "A driver holding exactly the limit is already blocked and must visit the safe first; the refusal is `ERR_CASH_LIMIT_REACHED` and it carries HTTP 402."
    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_error_outranks_cash_limit_error_on_depart
    """
    world = _returned_route_with_a_driver_at_the_cash_limit()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]

    fresh_order = fx.add_ready_order(store_id, world["addresses"]["A"]["id"])
    second = fx.open_dispatch(driver_id, "2026-08-05T14:00:00Z")
    fx.stack_stop(second["id"], fresh_order["id"], 1)
    locked = fx.lock_route(second["id"])
    assert locked["status"] == "LOCKED", "departure is declared from LOCKED"
    assert fx.read_driver(driver_id)["cash_posture"] == "DROP_REQUIRED"

    response = api_client.depart_dispatch(second["id"], make_driver_headers(driver_id))
    assert response.status_code == 402, "the cash-on-hand limit that blocks a departure is a 402"
    validate_error(response, ApiErrorId.ERR_CASH_LIMIT_REACHED.value)

    after = fx.read_dispatch(second["id"])
    assert after["status"] == "LOCKED"
    assert after["departed_at"] is None
    assert after["version"] == locked["version"]


def _stop_free_route_for_a_suspended_driver():
    """A store with a reimbursement schedule for the driver's vehicle class, a driver
    carried to QUALIFIED and then signed SUSPENDED, and an empty route still in DRAFT
    with no stops at all."""
    world = fx.setup_operational_store(clock=DEFAULT_CLOCK, address_keys=())
    driver_id = world["driver"]["id"]
    fx.sign_decision(driver_id, "SUSPEND", SECOND_COMPLIANCE_HEADERS)
    dispatch = fx.open_dispatch(driver_id, "2026-08-05T18:00:00Z")
    assert dispatch["stop_count"] == 0
    return world, dispatch


def test_stop_free_lock_by_a_suspended_driver_reports_the_qualification_failure():
    """A commitment that breaks both the qualification rule and the empty-route rule
    reports the qualification failure, the two candidates sharing HTTP 422 so that only
    the error identifier discriminates.

    PRD: "This sits deliberately above every capacity and constraint rule, so a stop-free lock attempted by a suspended driver reports the qualification failure rather than the empty route."
    Design: Difficulty/priority_pair_validation_conflict/driver_qualification_error_outranks_stop_free_dispatch_error_on_lock
    """
    world, dispatch = _stop_free_route_for_a_suspended_driver()
    driver_id = world["driver"]["id"]
    dispatch_id = dispatch["id"]

    before = fx.read_dispatch(dispatch_id)
    assert before["status"] == "DRAFT"
    assert before["stop_count"] == 0, "the empty-route rule is genuinely violated too"
    assert fx.read_driver(driver_id)["qualification_status"] == "SUSPENDED"

    response = api_client.lock_dispatch(dispatch_id, DISPATCHER_HEADERS)
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_DRIVER_NOT_QUALIFIED.value)

    after = fx.read_dispatch(dispatch_id)
    assert after["status"] == "DRAFT"
    assert after["route_minutes"] is None
    assert after["estimated_reimbursement_cents"] is None
    assert after["resolved_cost_model_id"] is None
    assert after["version"] == before["version"], (
        "a refused commitment applies no side effect of any kind"
    )
    assert fx.read_driver(driver_id)["qualification_status"] == "SUSPENDED"


def test_empty_route_refusal_surfaces_once_the_driver_is_reinstated():
    """Reinstating the driver removes the higher-ranked objection and the same commitment
    is then refused for carrying no counted stop.

    PRD: "And the route must carry at least one counted stop, or the commitment is refused with `ERR_DISPATCH_HAS_NO_STOPS` — an empty route has no schedule to resolve, no last stop to drive home from, and nothing to reimburse."
    Design: Difficulty/priority_pair_validation_conflict/driver_qualification_error_outranks_stop_free_dispatch_error_on_lock
    """
    world, dispatch = _stop_free_route_for_a_suspended_driver()
    driver_id = world["driver"]["id"]
    dispatch_id = dispatch["id"]

    fx.sign_decision(driver_id, "REINSTATE", SECOND_COMPLIANCE_HEADERS)
    assert fx.read_driver(driver_id)["qualification_status"] == "QUALIFIED"
    before = fx.read_dispatch(dispatch_id)
    assert before["stop_count"] == 0

    response = api_client.lock_dispatch(dispatch_id, DISPATCHER_HEADERS)
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_DISPATCH_HAS_NO_STOPS.value)

    after = fx.read_dispatch(dispatch_id)
    assert after["status"] == "DRAFT"
    assert after["route_minutes"] is None
    assert after["estimated_reimbursement_cents"] is None
    assert after["version"] == before["version"]


def _draft_route_for_a_qualified_driver():
    """A store, one qualified insured driver, and a brand-new route with no stops,
    still in DRAFT — a status from which settlement is not declared."""
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    driver = fx.add_qualified_driver(store["id"])
    dispatch = fx.open_dispatch(driver["id"], "2026-08-05T18:00:00Z")
    assert dispatch["status"] == "DRAFT"
    return store, driver, dispatch


def test_dispatcher_settling_a_draft_route_is_refused_on_the_role_gate():
    """Settlement is a manager act, so a dispatcher calling it is refused on the role gate
    before the route's own status is ever examined, and learns nothing about that status.

    PRD: "That role gate is evaluated before any resource named in the path is loaded, so a role that is not permitted to call an endpoint learns nothing about whether the identifiers in the path exist."
    Design: Difficulty/priority_pair_validation_conflict/dispatcher_cannot_settle_so_authz_error_outranks_dispatch_state_error
    """
    store, _driver, dispatch = _draft_route_for_a_qualified_driver()
    dispatch_id = dispatch["id"]
    before = fx.read_dispatch(dispatch_id)
    assert before["status"] == "DRAFT", "an illegal source state for settlement"

    response = api_client.settle_dispatch(dispatch_id, DISPATCHER_HEADERS)
    assert response.status_code == 403, (
        "the role gate answers 403; the route-state refusal it outranks answers 409"
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    after = fx.read_dispatch(dispatch_id)
    assert after["status"] == "DRAFT"
    assert after["actual_reimbursement_cents"] is None, "nothing was settled"
    assert after["reimbursement_variance_cents"] is None
    assert after["version"] == before["version"]


def test_manager_settling_a_draft_route_is_refused_on_the_route_state():
    """With the role gate satisfied by the owning manager, the same settlement of a draft
    route is refused on the route's status.

    PRD: "A route's `status` moves among `DRAFT`, `STACKED`, `LOCKED`, `EN_ROUTE`, `RETURNED`, and the three terminal states `SETTLED`, `RECALLED` and `CANCELLED`; a route action requested from a status that does not declare it is refused with `ERR_INVALID_DISPATCH_STATE`."
    Design: Difficulty/priority_pair_validation_conflict/dispatcher_cannot_settle_so_authz_error_outranks_dispatch_state_error
    """
    store, _driver, dispatch = _draft_route_for_a_qualified_driver()
    dispatch_id = dispatch["id"]
    before = fx.read_dispatch(dispatch_id)

    response = api_client.settle_dispatch(dispatch_id, make_manager_headers(store["id"]))
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_INVALID_DISPATCH_STATE.value)

    after = fx.read_dispatch(dispatch_id)
    assert after["status"] == "DRAFT"
    assert after["actual_reimbursement_cents"] is None
    assert after["version"] == before["version"]


def _stacked_route_ready_to_commit():
    """A perfectly committable route: one fee-disclosed READY order at a 3.00-mile
    IN_ZONE address stacked as its only stop, a resolvable schedule for the driver's
    vehicle class, and a qualified insured driver."""
    world = fx.setup_stacked_route(("A",), planned_depart_at="2026-08-05T18:00:00Z")
    dispatch = fx.read_dispatch(world["dispatch"]["id"])
    assert dispatch["status"] == "STACKED"
    assert dispatch["stop_count"] == 1
    return world


def test_commitment_succeeds_while_the_route_s_driver_reads_qualified():
    """With the route's driver reading QUALIFIED, the commitment writes all four of the
    fields it computes: the round-trip duration, the return instant, the snapshotted
    schedule and the estimated reimbursement.

    PRD: "Committing a route therefore writes four fields at once: `route_minutes` and `expected_return_at` from the round-trip model, `resolved_cost_model_id` from the selector, and `estimated_reimbursement_cents` from the estimated variant of the waterfall."
    Design: Difficulty/cross_entity_state_dependency/lock_of_a_valid_route_depends_on_driver_qualification_state
    """
    world = _stacked_route_ready_to_commit()
    dispatch_id = world["dispatch"]["id"]
    assert fx.read_driver(world["driver"]["id"])["qualification_status"] == "QUALIFIED"

    data = validate_success(api_client.lock_dispatch(dispatch_id, DISPATCHER_HEADERS), 200)
    a.assert_dispatch(data)
    assert data["status"] == "LOCKED"
    assert data["route_minutes"] == 24, (
        "a single 3.00-mile stop models at 9 out, 6 of handoff and 9 home"
    )
    assert data["route_minutes"] == a.expected_route_minutes([3.00], 3, 6)
    assert data["estimated_reimbursement_cents"] == 336
    assert data["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [3.00], CAR_COST_MODEL
    )
    assert data["resolved_cost_model_id"] == world["cost_model"]["id"]
    a.assert_iso_millis(data["expected_return_at"], "expected_return_at")
    assert a.parse_instant(data["expected_return_at"]) == a.parse_instant(
        a.instant_plus("2026-08-05T18:00:00Z", minutes=24)
    )


def test_commitment_is_refused_when_only_the_driver_s_qualification_state_is_flipped():
    """Nothing about the route changes, yet suspending its driver alone refuses the
    commitment, because suspension recalls nothing and is felt only at the next commit.

    PRD: "`SUSPEND` moves a driver `QUALIFIED → SUSPENDED` and bumps the driver's `version`, and it deliberately does **not** recall anything: existing routes stay exactly where they are, and the consequence of suspension is felt only when someone next tries to commit or depart a route."
    Design: Difficulty/cross_entity_state_dependency/lock_of_a_valid_route_depends_on_driver_qualification_state
    """
    world = _stacked_route_ready_to_commit()
    dispatch_id = world["dispatch"]["id"]
    driver_id = world["driver"]["id"]
    stop_id = world["stops"][0]["id"]
    order_id = world["orders"][0]["id"]

    fx.sign_decision(driver_id, "SUSPEND", SECOND_COMPLIANCE_HEADERS)
    before = fx.read_dispatch(dispatch_id)
    assert before["status"] == "STACKED", "the suspension did not recall the route"
    assert before["stop_count"] == 1

    response = api_client.lock_dispatch(dispatch_id, DISPATCHER_HEADERS)
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_DRIVER_NOT_QUALIFIED.value)

    after = fx.read_dispatch(dispatch_id)
    assert after["status"] == "STACKED"
    assert after["stop_count"] == 1
    assert after["route_minutes"] is None
    assert after["expected_return_at"] is None
    assert after["resolved_cost_model_id"] is None
    assert after["estimated_reimbursement_cents"] is None
    assert after["version"] == before["version"]
    assert fx.read_stop(stop_id)["status"] == "PENDING"
    assert fx.read_order(order_id)["fulfillment_status"] == "ASSIGNED"


def test_reinstating_the_driver_lets_the_identical_commitment_through_unchanged():
    """A suspend-and-reinstate cycle on the driver leaves no residue on the route: the
    identical commitment then produces exactly the figures a never-suspended route does.

    PRD: "`REINSTATE` moves a driver `SUSPENDED → QUALIFIED` and re-applies the same three substantive checks as qualification — points at most 5, a verified certificate covering the logical clock, and an acting officer who is not the recorder of the newest pull — again stamping `qualified_by_user_id` and bumping `version`."
    Design: Difficulty/cross_entity_state_dependency/lock_of_a_valid_route_depends_on_driver_qualification_state
    """
    world = _stacked_route_ready_to_commit()
    dispatch_id = world["dispatch"]["id"]
    driver_id = world["driver"]["id"]

    fx.sign_decision(driver_id, "SUSPEND", SECOND_COMPLIANCE_HEADERS)
    fx.sign_decision(driver_id, "REINSTATE", SECOND_COMPLIANCE_HEADERS)
    assert fx.read_driver(driver_id)["qualification_status"] == "QUALIFIED"

    data = validate_success(api_client.lock_dispatch(dispatch_id, DISPATCHER_HEADERS), 200)
    assert data["status"] == "LOCKED"
    assert data["route_minutes"] == 24
    assert data["estimated_reimbursement_cents"] == 336
    assert data["resolved_cost_model_id"] == world["cost_model"]["id"]
    assert data["stop_count"] == 1


def _edge_address_order_and_open_dispute():
    """A store, one EDGE address 11.34 grid miles out whose 41-minute modelled drive
    exceeds the 40-minute ceiling, one order still PLACED on that address, and a dispute
    on the address picked up for review but not yet decided."""
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    address = fx.add_address_at(store_id, EDGE_ADDRESS_LAT_MICRO, EDGE_ADDRESS_LON_MICRO)
    assert address["grid_miles"] == 11.34
    assert address["drive_time_estimate_minutes"] == 41
    assert address["zone_state"] == "EDGE"
    order = fx.place_order(
        store_id, address["id"], customer_name="Hana", customer_phone="555-0108"
    )
    dispute = fx.open_dispute(
        address["id"], evidence_note="Driveway is on our side of the creek"
    )
    dispute = fx.review_dispute(dispute["id"], "START_REVIEW", store_id)
    assert dispute["status"] == "UNDER_REVIEW"
    return store, address, order, dispute


def test_clearing_an_edge_order_succeeds_while_the_dispute_grant_is_in_force():
    """A granted dispute puts an override on the address, so the same clearance the model
    would refuse is accepted for as long as the clock stays before the granted expiry.

    PRD: "And the destination's `effective_zone_state` must read `IN_ZONE`, or the request fails with `ERR_ADDRESS_OUT_OF_AREA` — which for a parked edge address means the clearance can only succeed while a granted dispute's `override_until` is still strictly ahead of the clock."
    Design: Difficulty/cross_entity_state_dependency/zone_clearance_of_an_edge_order_depends_on_dispute_grant_state
    """
    store, address, order, dispute = _edge_address_order_and_open_dispute()
    granted = fx.review_dispute(
        dispute["id"], "GRANT", store["id"], granted_until="2026-08-05T23:00:00Z"
    )
    assert granted["status"] == "GRANTED"
    assert granted["resolution"] == "GRANTED"

    overridden = fx.read_address(address["id"])
    assert overridden["zone_state"] == "EDGE", "the geometric verdict never moves"
    assert overridden["override_state"] == "IN_ZONE"
    assert overridden["effective_zone_state"] == "IN_ZONE"

    data = validate_success(
        api_client.zone_decision(order["id"], f.zone_decision_payload("CLEAR"), DISPATCHER_HEADERS),
        200,
    )
    assert data["fulfillment_status"] == "ZONE_CLEARED"


def test_clearing_an_edge_order_is_refused_while_the_dispute_is_still_under_review():
    """Flipping only the dispute's state back to undecided refuses the identical clearance,
    so the gate lives on the neighbouring dispute rather than on the order itself.

    PRD: "And the destination's `effective_zone_state` must read `IN_ZONE`, or the request fails with `ERR_ADDRESS_OUT_OF_AREA` — which for a parked edge address means the clearance can only succeed while a granted dispute's `override_until` is still strictly ahead of the clock."
    Design: Difficulty/cross_entity_state_dependency/zone_clearance_of_an_edge_order_depends_on_dispute_grant_state
    """
    _store, address, order, dispute = _edge_address_order_and_open_dispute()
    before = fx.read_order(order["id"])
    assert before["fulfillment_status"] == "PLACED"

    response = api_client.zone_decision(
        order["id"], f.zone_decision_payload("CLEAR"), DISPATCHER_HEADERS
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_ADDRESS_OUT_OF_AREA.value)

    after_order = fx.read_order(order["id"])
    assert after_order["fulfillment_status"] == "PLACED"
    assert after_order["settlement_status"] == "UNDISCLOSED"
    assert after_order["version"] == before["version"]

    after_address = fx.read_address(address["id"])
    assert after_address["zone_state"] == "EDGE"
    assert after_address["override_state"] is None
    assert after_address["override_until"] is None
    assert after_address["effective_zone_state"] == "EDGE"

    after_dispute = validate_success(
        api_client.get_address_dispute(dispute["id"], DISPATCHER_HEADERS), 200
    )
    assert after_dispute["status"] == "UNDER_REVIEW"
    assert after_dispute["resolution"] is None


def test_clearing_an_edge_order_is_refused_again_once_the_granted_override_lapses():
    """The override bound is exclusive, so the moment the clock reaches the granted expiry
    the address falls back to its stored EDGE verdict and clearance is refused again.

    PRD: "An address override runs until `override_until` exclusive: the override is in force while `override_until` is strictly after the logical clock, and has lapsed the moment the clock reaches it."
    Design: Difficulty/cross_entity_state_dependency/zone_clearance_of_an_edge_order_depends_on_dispute_grant_state
    """
    store, address, order, dispute = _edge_address_order_and_open_dispute()
    store_id = store["id"]
    fx.review_dispute(dispute["id"], "GRANT", store_id, granted_until="2026-08-05T23:00:00Z")
    assert fx.read_address(address["id"])["effective_zone_state"] == "IN_ZONE"

    fx.set_clock("2026-08-05T23:00:00Z")
    lapsed = fx.read_address(address["id"])
    assert lapsed["override_state"] == "IN_ZONE", "the recorded override is not erased"
    assert a.parse_instant(lapsed["override_until"]) == a.parse_instant("2026-08-05T23:00:00Z")
    assert lapsed["effective_zone_state"] == "EDGE", (
        "the effective state falls back to the stored verdict the moment the clock reaches the bound"
    )

    before = fx.read_order(order["id"])
    assert before["fulfillment_status"] == "PLACED", "the grant left this untouched order alone"

    response = api_client.zone_decision(
        order["id"], f.zone_decision_payload("CLEAR"), DISPATCHER_HEADERS
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_ADDRESS_OUT_OF_AREA.value)

    after = fx.read_order(order["id"])
    assert after["fulfillment_status"] == "PLACED"
    assert after["version"] == before["version"]


def _stacked_route_whose_store_publishes_only_a_scooter_schedule():
    """A store whose only reimbursement schedule is the scooter one, a qualified driver
    whose vehicle class is CAR, and a fee-disclosed ready order stacked as the only stop
    of a route waiting to be committed.

    A schedule plainly exists in the store; it simply does not name the driver's
    vehicle class, which is what the selector matches on.
    """
    world = fx.setup_operational_store(
        clock=DEFAULT_CLOCK,
        address_keys=("A",),
        cost_model_overrides=dict(SCOOTER_COST_MODEL),
    )
    scooter_model = world["cost_model"]
    assert scooter_model["vehicle_class"] == "SCOOTER"
    assert world["driver"]["vehicle_class"] == "CAR"
    order = fx.add_ready_order(world["store"]["id"], world["addresses"]["A"]["id"])
    dispatch = fx.open_dispatch(world["driver"]["id"], "2026-08-05T18:00:00Z")
    fx.stack_stop(dispatch["id"], order["id"], 1)
    return world, scooter_model, fx.read_dispatch(dispatch["id"])


def test_commitment_resolves_the_schedule_published_for_the_drivers_vehicle_class():
    """Once a schedule naming the driver's own vehicle class is published, the identical
    commitment resolves that schedule and prices the route from it.

    PRD: "The selector considers every vehicle cost model whose `store_id` matches the driver's store, whose `vehicle_class` matches the driver's `vehicle_class`, whose `status` is `ACTIVE`, and whose `effective_from` is at or before the route's `planned_depart_at`."
    Design: Difficulty/cross_entity_state_dependency/lock_depends_on_a_cost_model_existing_for_the_drivers_vehicle_class
    """
    world, scooter_model, dispatch = _stacked_route_whose_store_publishes_only_a_scooter_schedule()
    car_model = fx.add_cost_model(world["store"]["id"], **CAR_COST_MODEL)
    assert car_model["vehicle_class"] == "CAR"
    assert car_model["id"] != scooter_model["id"]

    locked = validate_success(api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS), 200)
    assert locked["status"] == "LOCKED"
    assert locked["resolved_cost_model_id"] == car_model["id"], (
        "the schedule is resolved from the driver's vehicle class, not from whichever"
        " schedule happens to exist in the store"
    )
    assert locked["route_minutes"] == 24
    assert locked["route_minutes"] == a.expected_route_minutes([3.00], 3, 6)
    assert locked["estimated_reimbursement_cents"] == 336
    assert locked["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [3.00], CAR_COST_MODEL
    )


def test_commitment_is_refused_when_no_schedule_names_the_drivers_vehicle_class():
    """With only a scooter schedule on file the selector resolves nothing for a car
    driver, so the commitment is refused and none of the four priced fields is written.

    PRD: "The schedule selector must resolve exactly one schedule, or the commitment is refused with `ERR_NO_COST_MODEL`."
    Design: Difficulty/cross_entity_state_dependency/lock_depends_on_a_cost_model_existing_for_the_drivers_vehicle_class
    """
    _world, scooter_model, dispatch = _stacked_route_whose_store_publishes_only_a_scooter_schedule()
    assert dispatch["status"] == "STACKED"
    assert dispatch["stop_count"] == 1

    response = api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS)
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_NO_COST_MODEL.value)

    after = fx.read_dispatch(dispatch["id"])
    assert after["status"] == "STACKED"
    assert after["resolved_cost_model_id"] is None
    assert after["estimated_reimbursement_cents"] is None
    assert after["route_minutes"] is None
    assert after["expected_return_at"] is None
    assert after["version"] == dispatch["version"], (
        "a refused commitment applies no side effect of any kind"
    )

    still_published = validate_success(
        api_client.get_vehicle_cost_model(scooter_model["id"], DISPATCHER_HEADERS), 200
    )
    assert still_published["status"] == "ACTIVE", (
        "an eligible-looking schedule does exist and was refused purely on vehicle class"
    )


def test_commitment_of_a_scooter_driver_resolves_the_scooter_schedule_and_its_floor():
    """A driver whose vehicle class is SCOOTER resolves the scooter schedule on the same
    single-stop route, and a 1.00-mile stop lands on that schedule's per-stop floor.

    PRD: "And the floor genuinely bites: a scooter schedule paying 90 cents per delivery with a 3.00-mile cap, 35 cents per tier-1 mile and a 250-cent per-stop floor pays 250 cents for a single 1.00-mile stop, because the raw 125 cents falls short of the floor."
    Design: Difficulty/cross_entity_state_dependency/lock_depends_on_a_cost_model_existing_for_the_drivers_vehicle_class
    """
    world = fx.setup_operational_store(
        clock=DEFAULT_CLOCK,
        address_keys=(),
        cost_model_overrides=dict(SCOOTER_COST_MODEL),
        driver_overrides={"vehicle_class": "SCOOTER"},
    )
    store_id = world["store"]["id"]
    scooter_model = world["cost_model"]
    assert world["driver"]["vehicle_class"] == "SCOOTER"

    address = fx.add_address_at(store_id, ONE_MILE_LAT_MICRO, ONE_MILE_LON_MICRO)
    assert address["grid_miles"] == 1.00
    assert address["drive_time_estimate_minutes"] == 9
    assert address["zone_state"] == "IN_ZONE"

    order = fx.add_ready_order(store_id, address["id"])
    dispatch = fx.open_dispatch(world["driver"]["id"], "2026-08-05T18:00:00Z")
    fx.stack_stop(dispatch["id"], order["id"], 1)

    locked = validate_success(api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS), 200)
    assert locked["status"] == "LOCKED"
    assert locked["resolved_cost_model_id"] == scooter_model["id"]
    assert locked["route_minutes"] == 12
    assert locked["route_minutes"] == a.expected_route_minutes([1.00], 3, 6)
    assert locked["estimated_reimbursement_cents"] == 250, (
        "the raw 125 cents falls short of the schedule's per-stop floor"
    )
    assert locked["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [1.00], SCOOTER_COST_MODEL
    )
