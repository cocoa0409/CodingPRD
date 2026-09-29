"""Lifecycle transitions of the Store Operations API.

Every test here pins one declared transition — or one refusal of an undeclared
one — together with the side effects the specification attributes to that same
transition: the delivery-area version DRAFT/ACTIVE/SUPERSEDED chain and the
store bump that rides along with an activation, the dispute cycle's terminal
withdrawal, the driver qualification dimension from applicant to pending
checks, the two independent order dimensions at birth and under a carryout-only
posture, the route's refusal to depart before it is committed, the stop-free
draft route that cancels rather than recalls, and the remake that rewinds a
delivered order's stopwatch. Where a transition is undeclared the test also
pins the silence: the refused call must move neither the status nor the version
of the record it named.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers import assertions as a
from test_helpers.constants import (
    ADDRESS_DRIVE_MINUTES,
    ADDRESS_GRID_MILES,
    DEFAULT_CLOCK,
    NOON_CLOCK,
    STORE_DEFAULTS,
)
from test_helpers.test_users import (
    CARE_HEADERS,
    COMPLIANCE_HEADERS,
    COMPLIANCE_OFFICER_USER_ID,
    DISPATCHER_HEADERS,
    SECOND_COMPLIANCE_HEADERS,
    make_driver_headers,
    make_manager_headers,
)

JULY_FROM = "2026-07-01T00:00:00Z"
JULY_TO = "2026-08-01T00:00:00Z"
AUGUST_FROM = "2026-08-01T00:00:00Z"
AUGUST_TO = "2026-09-01T00:00:00Z"


def test_activating_the_later_window_supersedes_the_earlier_active_window():
    """Putting the August window in force stamps the supersession lineage onto it and drives the July window it displaces to SUPERSEDED.

    PRD: "That version's `id` is written onto the new version's `supersedes_zone_version_id`, and that version's own status becomes `SUPERSEDED`."
    Design: Corner/state_machines/zone_version_activation_supersedes_the_earlier_window_and_bumps_the_store
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    manager_headers = make_manager_headers(store_id)

    july = fx.publish_zone_version(store_id, effective_from=JULY_FROM, effective_to=JULY_TO)
    fx.activate_zone_version(july["id"], store_id)
    august = fx.publish_zone_version(
        store_id, effective_from=AUGUST_FROM, effective_to=AUGUST_TO
    )
    assert august["status"] == "DRAFT"
    assert august["supersedes_zone_version_id"] is None
    assert august["activated_at"] is None

    activated = validate_success(
        api_client.activate_zone_version(august["id"], manager_headers), 200
    )

    a.assert_zone_version(activated)
    assert activated["id"] == august["id"]
    assert activated["status"] == "ACTIVE"
    a.assert_iso_millis(activated["activated_at"], "activated_at")
    assert a.parse_instant(activated["activated_at"]) == a.parse_instant(DEFAULT_CLOCK)
    assert activated["supersedes_zone_version_id"] == july["id"]
    assert activated["version_number"] == july["version_number"] + 1

    displaced = get_success_data(api_client.get_zone_version(july["id"], manager_headers), 200)
    assert displaced["status"] == "SUPERSEDED"
    assert displaced["supersedes_zone_version_id"] is None


def test_zone_version_activation_bumps_the_store_and_re_derives_the_active_area_number():
    """The activation increments the parent store's version exactly once, and the store's active area number re-derives to the window that now contains the logical clock.

    PRD: "Either way the parent store's `version` increments by 1, and the store's `active_zone_version_number` — re-derived on read as the `version_number` of whichever `ACTIVE` version's window contains the logical clock, and null when none does — begins reporting the new area."
    Design: Corner/state_machines/zone_version_activation_supersedes_the_earlier_window_and_bumps_the_store
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    manager_headers = make_manager_headers(store_id)

    july = fx.publish_zone_version(store_id, effective_from=JULY_FROM, effective_to=JULY_TO)
    fx.activate_zone_version(july["id"], store_id)
    august = fx.publish_zone_version(
        store_id, effective_from=AUGUST_FROM, effective_to=AUGUST_TO
    )

    before = fx.read_store(store_id)
    assert before["active_zone_version_number"] is None, (
        "the in-force July window does not contain the logical clock"
    )

    validate_success(api_client.activate_zone_version(august["id"], manager_headers), 200)

    after = fx.read_store(store_id)
    a.assert_store(after)
    assert after["version"] == before["version"] + 1
    assert after["active_zone_version_number"] == august["version_number"]


def test_activating_an_already_active_zone_version_is_refused_as_invalid_state():
    """A second activation of the same in-force window is refused, and leaves the activation stamp, the version lineage and the parent store untouched.

    PRD: "It requires the version to be in `DRAFT` — anything else is `ERR_INVALID_ZONE_VERSION_STATE` — requires the acting manager to own the version's store, and re-confirms that the `polygon` still carries at least three vertices."
    Design: Corner/state_machines/activating_an_already_active_zone_version_is_rejected_as_invalid_state
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    manager_headers = make_manager_headers(store_id)

    draft = fx.publish_zone_version(
        store_id, effective_from=JULY_FROM, effective_to=AUGUST_TO
    )
    active = fx.activate_zone_version(draft["id"], store_id)
    assert active["status"] == "ACTIVE"
    a.assert_iso_millis(active["activated_at"], "activated_at")
    before_store = fx.read_store(store_id)

    validate_error(
        api_client.activate_zone_version(draft["id"], manager_headers),
        ApiErrorId.ERR_INVALID_ZONE_VERSION_STATE.value,
    )

    unchanged = get_success_data(api_client.get_zone_version(draft["id"], manager_headers), 200)
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["activated_at"] == active["activated_at"]
    assert unchanged["version"] == active["version"], "the refused call mutated nothing"
    assert unchanged["supersedes_zone_version_id"] is None
    after_store = fx.read_store(store_id)
    assert after_store["version"] == before_store["version"], (
        "a refused activation bumps no parent store version"
    )
    assert after_store["active_zone_version_number"] == unchanged["version_number"]


def test_superseded_zone_version_cannot_be_put_back_in_force():
    """A window that has already been displaced is terminal, so re-activating it is refused and the store keeps reporting the window that took over.

    PRD: "It requires the version to be in `DRAFT` — anything else is `ERR_INVALID_ZONE_VERSION_STATE` — requires the acting manager to own the version's store, and re-confirms that the `polygon` still carries at least three vertices."
    Design: Corner/state_machines/superseded_zone_version_cannot_be_reactivated
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    manager_headers = make_manager_headers(store_id)

    july = fx.publish_zone_version(store_id, effective_from=JULY_FROM, effective_to=JULY_TO)
    fx.activate_zone_version(july["id"], store_id)
    august = fx.publish_zone_version(
        store_id, effective_from=AUGUST_FROM, effective_to=AUGUST_TO
    )
    fx.activate_zone_version(august["id"], store_id)
    superseded = get_success_data(api_client.get_zone_version(july["id"], manager_headers), 200)
    assert superseded["status"] == "SUPERSEDED"

    validate_error(
        api_client.activate_zone_version(july["id"], manager_headers),
        ApiErrorId.ERR_INVALID_ZONE_VERSION_STATE.value,
    )

    still_superseded = get_success_data(
        api_client.get_zone_version(july["id"], manager_headers), 200
    )
    assert still_superseded["status"] == "SUPERSEDED"
    assert still_superseded["version"] == superseded["version"]
    still_active = get_success_data(
        api_client.get_zone_version(august["id"], manager_headers), 200
    )
    assert still_active["status"] == "ACTIVE"
    assert fx.read_store(store_id)["active_zone_version_number"] == august["version_number"]


def test_a_new_order_occupies_the_initial_state_of_both_dimensions():
    """A freshly taken ticket is PLACED on the fulfillment dimension and UNDISCLOSED on the settlement dimension, with the stopwatch started and the promise frozen.

    PRD: "At creation the order stamps `placed_at` from the logical clock — this is the start of the order-to-door stopwatch — and copies the store's current `promise_minutes` into its own `promise_minutes_snapshot`, permanently insulating this ticket from later policy edits."
    Design: Corner/state_machines/order_starts_placed_and_undisclosed_on_both_dimensions
    """
    fx.set_clock(NOON_CLOCK)
    store = fx.register_store(promise_minutes=30)
    store_id = store["id"]
    fx.publish_active_zone_version(store_id)
    address = fx.add_address(store_id, "A")

    payload = f.create_order_payload(
        store_id,
        address["id"],
        food_subtotal_cents=2200,
        tip_cents=500,
        payment_method="CARD",
    )
    order = validate_success(api_client.create_order(payload, DISPATCHER_HEADERS), 201)

    a.assert_order(order)
    assert order["fulfillment_status"] == "PLACED"
    assert order["settlement_status"] == "UNDISCLOSED"
    a.assert_iso_millis(order["placed_at"], "placed_at")
    assert a.parse_instant(order["placed_at"]) == a.parse_instant(NOON_CLOCK)
    assert order["promise_minutes_snapshot"] == 30
    assert order["ready_at"] is None
    assert order["door_arrival_at"] is None
    assert order["zone_held_at"] is None
    assert order["declined_reason"] is None
    assert order["remake_count"] == 0
    assert order["zone_hold_minutes"] == 0
    assert order["remake_hold_minutes"] == 0
    assert order["remedy_issued_cents"] == 0
    assert order["remake_credit_cents"] == 0
    assert order["fee_disclosure_accurate"] is None
    assert order["fee_disclosed_at"] is None
    assert fx.read_store(store_id)["unassigned_order_count"] == 0, (
        "a placed order is not one of the four statuses that need a route"
    )


def test_production_start_on_a_placed_order_is_refused_as_invalid_order_state():
    """Production start is declared only from zone-cleared or remake-queued, so an order that has not passed the delivery-area gate is refused and neither dimension moves.

    PRD: "Any order action requested from a status that does not declare it is rejected with `ERR_INVALID_ORDER_STATE`."
    Design: Corner/state_machines/production_start_on_a_placed_order_is_rejected_as_invalid_order_state
    """
    fx.set_clock(NOON_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    fx.publish_active_zone_version(store_id)
    address = fx.add_address(store_id, "A")
    order = fx.place_order(
        store_id,
        address["id"],
        food_subtotal_cents=2200,
        tip_cents=500,
        payment_method="CARD",
    )
    assert order["fulfillment_status"] == "PLACED"

    validate_error(
        api_client.production(order["id"], f.production_payload("START"), DISPATCHER_HEADERS),
        ApiErrorId.ERR_INVALID_ORDER_STATE.value,
    )

    unchanged = fx.read_order(order["id"])
    assert unchanged["fulfillment_status"] == "PLACED"
    assert unchanged["ready_at"] is None
    assert unchanged["settlement_status"] == "UNDISCLOSED", (
        "the refused call touched neither dimension"
    )
    assert unchanged["version"] == order["version"]


def test_departing_a_stacked_route_is_refused_as_invalid_dispatch_state():
    """Departure is declared only from a committed route, so a merely stacked route is refused on its state ahead of the driver-qualification gate its applicant driver would also fail.

    PRD: "A route's `status` moves among `DRAFT`, `STACKED`, `LOCKED`, `EN_ROUTE`, `RETURNED`, and the three terminal states `SETTLED`, `RECALLED` and `CANCELLED`; a route action requested from a status that does not declare it is refused with `ERR_INVALID_DISPATCH_STATE`."
    Design: Corner/state_machines/depart_before_lock_is_rejected_as_invalid_dispatch_state
    """
    fx.set_clock(NOON_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    fx.publish_active_zone_version(store_id)
    address = fx.add_address(store_id, "A")
    driver = fx.hire_driver(store_id)
    assert driver["qualification_status"] == "APPLICANT"
    order = fx.add_ready_order(
        store_id,
        address["id"],
        food_subtotal_cents=2200,
        tip_cents=500,
        payment_method="CARD",
    )
    dispatch = fx.open_dispatch(driver["id"], "2026-08-05T12:05:00Z")
    stop = fx.stack_stop(dispatch["id"], order["id"], 1)
    stacked = fx.read_dispatch(dispatch["id"])
    assert stacked["status"] == "STACKED"

    validate_error(
        api_client.depart_dispatch(dispatch["id"], make_driver_headers(driver["id"])),
        ApiErrorId.ERR_INVALID_DISPATCH_STATE.value,
    )

    unchanged = fx.read_dispatch(dispatch["id"])
    assert unchanged["status"] == "STACKED"
    assert unchanged["departed_at"] is None
    assert unchanged["version"] == stacked["version"]
    assert fx.read_order(order["id"])["fulfillment_status"] == "ASSIGNED", (
        "the carried order did not advance to en route"
    )
    assert fx.read_stop(stop["id"])["status"] == "PENDING"


def test_a_withdrawn_dispute_refuses_a_further_review_action():
    """Withdrawal is terminal, so picking the dispute back up for review is refused and neither the review-round count nor the disputed address moves.

    PRD: "Requesting an action that is not declared from the dispute's current status is rejected with `ERR_INVALID_DISPUTE_STATE`."
    Design: Corner/state_machines/withdrawn_dispute_rejects_a_further_review_action
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    fx.publish_active_zone_version(store_id)
    address = fx.add_address(store_id, "E")
    assert address["zone_state"] == "EDGE"
    dispute = fx.open_dispute(address["id"])
    assert dispute["status"] == "SUBMITTED"
    withdrawn = fx.review_dispute(
        dispute["id"], "WITHDRAW", headers=CARE_HEADERS, note="Customer withdrew the claim"
    )
    assert withdrawn["status"] == "WITHDRAWN"

    validate_error(
        api_client.review_address_dispute(
            dispute["id"],
            f.review_dispute_payload("START_REVIEW"),
            make_manager_headers(store_id),
        ),
        ApiErrorId.ERR_INVALID_DISPUTE_STATE.value,
    )

    unchanged = get_success_data(
        api_client.get_address_dispute(dispute["id"], make_manager_headers(store_id)), 200
    )
    a.assert_address_dispute(unchanged)
    assert unchanged["status"] == "WITHDRAWN"
    assert unchanged["review_round_count"] == 0
    assert unchanged["decided_at"] is None
    assert unchanged["resolution"] is None
    assert unchanged["reviewer_user_id"] == withdrawn["reviewer_user_id"]
    assert unchanged["version"] == withdrawn["version"]

    still_edge = fx.read_address(address["id"])
    assert still_edge["override_state"] is None
    assert still_edge["override_until"] is None
    assert still_edge["effective_zone_state"] == "EDGE"
    assert still_edge["zone_state"] == "EDGE"
    assert still_edge["grid_miles"] == 13.33
    assert still_edge["grid_miles"] == ADDRESS_GRID_MILES["E"]
    assert still_edge["drive_time_estimate_minutes"] == 46
    assert still_edge["drive_time_estimate_minutes"] == ADDRESS_DRIVE_MINUTES["E"]


def test_a_clear_record_pull_advances_the_applicant_to_pending_checks():
    """A clear motor-vehicle-record pull with no points moves the applicant on the qualification dimension, re-derives the latest point total and bumps the driver once, while the insurance dimension stays where it was.

    PRD: "A pull whose `result` is `CLEAR` or `MINOR_VIOLATIONS` also advances an applicant `APPLICANT → PENDING_CHECKS`."
    Design: Corner/state_machines/first_clear_mvr_check_moves_the_applicant_to_pending_checks
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    driver = fx.hire_driver(store["id"])
    assert driver["qualification_status"] == "APPLICANT"
    assert driver["version"] == 1

    pull = validate_success(
        api_client.create_mvr_check(
            driver["id"],
            f.create_mvr_check_payload(
                result="CLEAR", violation_points=0, checked_on="2026-08-01T00:00:00Z"
            ),
            COMPLIANCE_HEADERS,
        ),
        201,
    )

    a.assert_mvr_check(pull)
    assert pull["driver_id"] == driver["id"]
    assert pull["result"] == "CLEAR"
    assert pull["violation_points"] == 0
    assert pull["recorded_by_user_id"] == COMPLIANCE_OFFICER_USER_ID

    moved = fx.read_driver(driver["id"])
    a.assert_driver(moved)
    assert moved["qualification_status"] == "PENDING_CHECKS"
    assert moved["mvr_points_latest"] == 0
    assert moved["version"] == driver["version"] + 1
    assert moved["insurance_status"] == "NONE", "no certificate is on file yet"
    assert moved["qualified_by_user_id"] is None
    assert moved["disqualified_reason"] is None


def test_qualifying_an_applicant_driver_is_refused_as_invalid_driver_state():
    """Qualification is declared only from pending checks, so an applicant with nothing on file is refused on its state rather than on the insurance or point-total rules it would also fail.

    PRD: "The `qualification_status` dimension runs `APPLICANT`, `PENDING_CHECKS`, `QUALIFIED`, `SUSPENDED` and the terminal `DISQUALIFIED`; a decision that is not declared from the driver's current status — including any decision at all on a driver already `DISQUALIFIED` — is refused with `ERR_INVALID_DRIVER_STATE`."
    Design: Corner/state_machines/qualify_decision_on_an_applicant_driver_is_rejected_as_invalid_driver_state
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    driver = fx.hire_driver(store["id"])
    assert driver["qualification_status"] == "APPLICANT"

    validate_error(
        api_client.create_qualification_decision(
            driver["id"],
            f.qualification_decision_payload("QUALIFY"),
            SECOND_COMPLIANCE_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_DRIVER_STATE.value,
    )

    unchanged = fx.read_driver(driver["id"])
    assert unchanged["qualification_status"] == "APPLICANT"
    assert unchanged["version"] == driver["version"]
    assert unchanged["qualified_by_user_id"] is None
    assert unchanged["insurance_status"] == "NONE"
    assert unchanged["mvr_points_latest"] == 0


def test_recalling_a_stop_free_draft_route_cancels_it_rather_than_recalling_it():
    """A route recalled while still a stop-free draft records the reason and lands in the terminal cancelled state, having reserved and therefore released nothing.

    PRD: "One special case sits alongside: recalling a route that is still `DRAFT` with a `stop_count` of 0 records the `recalled_reason` and drives the route to the terminal `CANCELLED` instead of `RECALLED`, since there is nothing to release."
    Design: Corner/state_machines/recall_of_a_stop_free_draft_dispatch_cancels_it
    """
    fx.set_clock(NOON_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    driver = fx.hire_driver(store_id)
    dispatch = fx.open_dispatch(driver["id"], "2026-08-05T12:05:00Z")
    assert dispatch["status"] == "DRAFT"
    assert dispatch["stop_count"] == 0

    recalled = validate_success(
        api_client.recall_dispatch(
            dispatch["id"],
            f.recall_payload("Shift ended before the route was built"),
            DISPATCHER_HEADERS,
        ),
        200,
    )

    a.assert_dispatch(recalled)
    assert recalled["status"] == "CANCELLED"
    assert recalled["recalled_reason"] == "Shift ended before the route was built"
    assert recalled["stop_count"] == 0
    assert recalled["committed_hot_bag_slots"] == 0
    assert recalled["route_minutes"] is None
    assert recalled["expected_return_at"] is None
    assert recalled["resolved_cost_model_id"] is None
    assert recalled["estimated_reimbursement_cents"] is None
    assert recalled["departed_at"] is None
    assert recalled["returned_at"] is None
    assert fx.read_driver(driver["id"])["reimbursement_accrued_cents"] == 0

    lines, meta = validate_paginated(
        api_client.list_reimbursement_lines(
            make_manager_headers(store_id), {"dispatch_id": dispatch["id"]}
        )
    )
    assert meta["total_count"] == 0, "a route that never held a stop wrote no ledger line"
    assert lines == []


def test_an_order_taken_under_a_carryout_only_posture_is_born_redirected():
    """An order taken while the store is carryout-only is priced and then immediately redirected on the fulfillment dimension with its settlement dimension voided, so it never joins the unassigned queue.

    PRD: "When the store's `service_posture` is `CARRYOUT_ONLY` at the moment the order is created, the order is born already redirected: its fulfillment dimension goes `PLACED → CARRYOUT_REDIRECTED`, its `declined_reason` is set to `STORE_CARRYOUT_ONLY`, and its settlement dimension is set to `VOIDED`."
    Design: Corner/state_machines/order_created_under_carryout_only_posture_is_redirected_at_creation
    """
    fx.set_clock(NOON_CLOCK)
    store = fx.register_store(service_posture="OPEN")
    store_id = store["id"]
    fx.publish_active_zone_version(store_id)
    address = fx.add_address(store_id, "A")
    fx.edit_store(store_id, service_posture="CARRYOUT_ONLY")

    order = validate_success(
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
    assert order["fulfillment_status"] == "CARRYOUT_REDIRECTED"
    assert order["settlement_status"] == "VOIDED"
    assert order["declined_reason"] == "STORE_CARRYOUT_ONLY"

    priced = a.expected_order_pricing(
        ADDRESS_DRIVE_MINUTES["A"], STORE_DEFAULTS["delivery_fee_cents"], 2200, 500
    )
    assert order["delivery_fee_cents"] == 200 == priced["delivery_fee_cents"]
    assert order["total_charge_cents"] == 2900 == priced["total_charge_cents"]
    assert fx.read_store(store_id)["unassigned_order_count"] == 0


def test_a_redirected_order_refuses_a_later_delivery_area_decision():
    """Redirection at creation is terminal on the fulfillment dimension, so a delivery-area disposition afterwards is refused on the order's state and leaves it exactly where it was.

    PRD: "Any order action requested from a status that does not declare it is rejected with `ERR_INVALID_ORDER_STATE`."
    Design: Corner/state_machines/order_created_under_carryout_only_posture_is_redirected_at_creation
    """
    fx.set_clock(NOON_CLOCK)
    store = fx.register_store(service_posture="OPEN")
    store_id = store["id"]
    fx.publish_active_zone_version(store_id)
    address = fx.add_address(store_id, "A")
    fx.edit_store(store_id, service_posture="CARRYOUT_ONLY")
    order = fx.place_order(store_id, address["id"])
    assert order["fulfillment_status"] == "CARRYOUT_REDIRECTED"

    validate_error(
        api_client.zone_decision(
            order["id"], f.zone_decision_payload("CLEAR"), DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_INVALID_ORDER_STATE.value,
    )

    unchanged = fx.read_order(order["id"])
    assert unchanged["fulfillment_status"] == "CARRYOUT_REDIRECTED"
    assert unchanged["settlement_status"] == "VOIDED"
    assert unchanged["declined_reason"] == "STORE_CARRYOUT_ONLY"
    assert unchanged["version"] == order["version"]
    assert unchanged["zone_hold_minutes"] == 0


def _deliver_one_late_order():
    """Walk a single-stop route to a handoff that lands 36 minutes after the order
    was taken, which is the one shape a remake for lateness is eligible from."""
    world = fx.setup_operational_store(
        clock=NOON_CLOCK, address_keys=("A",), store_overrides={"promise_minutes": 30}
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    order = fx.add_ready_order(store_id, world["addresses"]["A"]["id"])
    dispatch = fx.open_dispatch(driver_id, "2026-08-05T12:05:00Z")
    stop = fx.stack_stop(dispatch["id"], order["id"])
    fx.lock_route(dispatch["id"])
    fx.depart_route(dispatch["id"], driver_id)
    fx.set_clock("2026-08-05T12:36:00Z")
    fx.arrive_at_door(dispatch["id"], stop["id"], driver_id, 3.40, 0)
    delivered = fx.read_order(order["id"])
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["settlement_status"] == "CHARGED"
    assert delivered["order_to_door_gross_minutes"] == 36
    return {
        "store_id": store_id,
        "driver_id": driver_id,
        "order": delivered,
        "dispatch": dispatch,
        "stop": stop,
    }


def test_queueing_a_remake_moves_the_delivered_order_and_its_stop():
    """A remake on a late delivered order advances both of its dimensions at once, moves the delivering stop to remade, counts the remake and books the absorbed food cost, while the route it travelled on is left alone.

    PRD: "Queueing a remake advances the order `DELIVERED → REMAKE_QUEUED` and rewinds the stopwatch."
    Design: Corner/state_machines/remake_moves_the_delivered_order_to_remake_queued_and_adjusts_settlement
    """
    world = _deliver_one_late_order()
    order = world["order"]

    remade = validate_success(
        api_client.remake_order(
            order["id"], f.remake_payload("LATE"), make_manager_headers(world["store_id"])
        ),
        200,
    )

    a.assert_order(remade)
    assert remade["fulfillment_status"] == "REMAKE_QUEUED"
    assert remade["settlement_status"] == "ADJUSTED"
    assert remade["remake_count"] == 1
    assert remade["remake_credit_cents"] == order["food_subtotal_cents"] == 2200
    assert remade["version"] > order["version"]

    stop = fx.read_stop(world["stop"]["id"])
    a.assert_dispatch_stop(stop)
    assert stop["status"] == "REMADE"
    assert stop["actual_miles"] == 3.40, "the odometer reading survives the remake"
    assert stop["cash_collected_cents"] == 0

    route = fx.read_dispatch(world["dispatch"]["id"])
    assert route["status"] == "EN_ROUTE", "a remake is an order-level act, not a route-level one"
    assert route["actual_reimbursement_cents"] is None
    assert fx.read_store(world["store_id"])["unassigned_order_count"] == 1

    lines, meta = validate_paginated(
        api_client.list_reimbursement_lines(
            make_manager_headers(world["store_id"]), {"dispatch_id": world["dispatch"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert lines[0]["line_type"] == "PROVISIONAL_STOP"
    assert lines[0]["status"] == "PROVISIONAL"
    assert fx.read_driver(world["driver_id"])["reimbursement_accrued_cents"] == 0


def test_queueing_a_remake_rewinds_the_order_to_door_stopwatch():
    """The same transition disowns the delivery that produced the timings: the parked minutes accrue into the remake hold, the door arrival is set back to null, and both order-to-door figures are cleared.

    PRD: "The whole minutes between the recorded `door_arrival_at` and the logical clock — the whole-second difference divided by 60 and truncated downward — accrue into the order's `remake_hold_minutes`; `door_arrival_at` is then set back to null and both `order_to_door_gross_minutes` and `order_to_door_net_minutes` are cleared, because the delivery that produced them has been disowned."
    Design: Corner/state_machines/remake_moves_the_delivered_order_to_remake_queued_and_adjusts_settlement
    """
    world = _deliver_one_late_order()
    order = world["order"]
    assert order["door_arrival_at"] is not None
    a.assert_iso_millis(order["door_arrival_at"], "door_arrival_at")

    remade = validate_success(
        api_client.remake_order(
            order["id"], f.remake_payload("LATE"), make_manager_headers(world["store_id"])
        ),
        200,
    )

    assert remade["remake_hold_minutes"] == 0, "the remake was queued on the arrival minute itself"
    assert remade["door_arrival_at"] is None
    assert remade["order_to_door_gross_minutes"] is None
    assert remade["order_to_door_net_minutes"] is None
    assert remade["zone_hold_minutes"] == 0, "the order was never parked out of area"
