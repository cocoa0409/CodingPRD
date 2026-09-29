"""State-machine edges: entry states, refused edges and system transitions
(PRD §3.3, §3.5, §3.6, §3.7, §3.9).

Every state machine in this API is entered at exactly one state, leaves it by a
named capability, and refuses every other edge with a state-precondition error
from rung 7 of the §2.7 ladder. Three of those machines are exercised here from
both sides: the authorization walk ISSUED -> ACTIVE -> CLOSED and the counters
it moves on the vessel, the deployment and the area; the dealer listing
dimension and its suspension cascade; and the investigation walk with its two
terminal states. The seed-lot machine contributes the one edge no endpoint owns
at all -- READY_FOR_PLANTING -> PLANTED, which follows the gear arithmetic.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    close_investigation_payload,
    confirm_payload,
    design_world,
    DW_ACTIVATE_CLOCK,
    dw_assemble_shipment,
    DW_CLOCK,
    DW_DEALER_CERT_NO,
    dw_dealer_payload,
    dw_land_lot,
    dw_tag_lot,
    DW_WINDOW_END,
    DW_WINDOW_START,
    get_success_data,
    growout_unit_payload,
    harvest_authorization_payload,
    illness_investigation_payload,
    iso,
    nursery_start_payload,
    set_clock,
    suspend_payload,
    TEST_USERS,
    to_millis,
    traceback_payload,
    trigger_rainfall_closure,
    validate_error,
    validate_paginated,
    validate_success,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]

CLOSE_CLOCK = iso(2026, 8, 10, 14)
EARLY_ACTIVATE_CLOCK = iso(2026, 8, 10, 5, 59, 59)
SECOND_ACTIVATE_CLOCK = iso(2026, 8, 10, 7)
SHIPPED_AT = iso(2026, 8, 10, 10, 50)
LOT_B_FIRST_OUT = iso(2026, 8, 10, 9)
LOT_B_LAST_OUT = iso(2026, 8, 10, 9, 30)
LOT_B_IN_CONTROL = iso(2026, 8, 10, 10, 45)
INVESTIGATION_CLOCK = iso(2026, 8, 11, 9)
REPORTED_AT = iso(2026, 8, 11, 8)
RAIN_OBSERVED_AT = iso(2026, 7, 25)
RAIN_REOPEN_ELIGIBLE_AT = iso(2026, 7, 29)


# --------------------------------------------------------------------------
# The authorization walk: ISSUED -> ACTIVE -> CLOSED
# --------------------------------------------------------------------------
def _active_world():
    """The reference chain up to an ACTIVE authorization. It was issued and then
    activated at 06:00 on 2026-08-10, the inclusive start of its own window, so
    `harvest_start_at` is that instant, the deployment is HARVESTING and the
    vessel -- capacity 2 -- carries the one live authorization."""
    return design_world(stage="active")


def test_closing_returns_the_deployment_to_deployed_and_releases_the_vessel():
    """Closing is the only edge out of ACTIVE that a client can take, and it
    settles three rows at once. The authorization itself reaches the terminal
    CLOSED with `harvest_end_at` stamped from the logical clock -- 14:00, which
    is strictly after the 06:00 `harvest_start_at` the activation stamped -- and
    with `void_reason` still null, because a close is not a void. The deployment
    comes back from HARVESTING to DEPLOYED, and the vessel's
    `active_authorization_count` drops by 1 to 0 even though nothing about the
    vessel's capacity of 2 changed. The area's `open_authorization_count`, which
    counts only ISSUED and ACTIVE rows, is recomputed to 0.

    Design: Corner/state_machines/close_authorization_returns_the_unit_to_deployed_and_releases_vessel_capacity
    """
    world = _active_world()
    set_clock(CLOSE_CLOCK)

    authorization = validate_success(api_client.close_harvest_authorization(
        world["authorization"]["id"], OPERATOR))

    assert authorization["status"] == "CLOSED"
    assert authorization["harvest_start_at"] == to_millis(DW_ACTIVATE_CLOCK)
    assert authorization["harvest_end_at"] == to_millis(CLOSE_CLOCK)
    assert authorization["void_reason"] is None

    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))
    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))

    assert unit["status"] == "DEPLOYED"
    assert vessel["active_authorization_count"] == 0
    assert vessel["concurrent_authorization_capacity"] == 2
    assert area["open_authorization_count"] == 0


def _issued_world_with_the_clock_before_the_window():
    """The chain up to an ISSUED authorization, with `activate_clock=None` so the
    logical clock is never advanced out of the 2026-08-01 epoch: the window
    2026-08-10T06:00Z-18:00Z is pure future intent, which issue explicitly
    permits."""
    return design_world(stage="issued", activate_clock=None)


def test_activating_one_second_before_the_window_opens_is_outside_the_window():
    """Activation reads the logical clock, not a client-supplied instant, and the
    permitted window is half-open from `window_start` inclusive. At 05:59:59 the
    clock is one second short of the 06:00 start, so the request is refused with
    ERR_OUTSIDE_AUTHORIZATION_WINDOW at HTTP 409. Every earlier rung is clean --
    the authorization really is in ISSUED, the deployment really is DEPLOYED and
    the area is APPROVED and OPEN -- so neither ERR_INVALID_AUTHORIZATION_STATE
    nor ERR_AREA_HARVEST_CLOSED can be the answer. The refusal leaves the
    machine where it was: still ISSUED with `harvest_start_at` null, the
    deployment still DEPLOYED, and the vessel still carrying the one
    authorization that issue counted.

    Design: Corner/state_machines/activate_before_the_window_opens_returns_outside_authorization_window
    """
    world = _issued_world_with_the_clock_before_the_window()
    assert world["authorization"]["status"] == "ISSUED"
    set_clock(EARLY_ACTIVATE_CLOCK)

    response = api_client.activate_harvest_authorization(
        world["authorization"]["id"], OPERATOR)

    body = validate_error(
        response, ApiErrorId.ERR_OUTSIDE_AUTHORIZATION_WINDOW, 409)
    assert body["error_id"] != ApiErrorId.ERR_INVALID_AUTHORIZATION_STATE
    assert body["error_id"] != ApiErrorId.ERR_AREA_HARVEST_CLOSED

    authorization = get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], OPERATOR))
    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))

    assert authorization["status"] == "ISSUED"
    assert authorization["harvest_start_at"] is None
    assert authorization["harvest_end_at"] is None
    assert unit["status"] == "DEPLOYED"
    assert vessel["active_authorization_count"] == 1


def test_a_second_activation_on_an_active_authorization_is_refused_by_state():
    """ACTIVE is not a state activation accepts, so the second attempt is
    ERR_INVALID_AUTHORIZATION_STATE at HTTP 409 -- and the state rung is reached
    before the window rung, which the 07:00 clock would have passed anyway, so
    ERR_OUTSIDE_AUTHORIZATION_WINDOW is not the answer. The refusal is inert:
    `harvest_start_at` is not re-stamped from the new clock but keeps the 06:00
    instant of the first activation, `harvest_end_at` stays null, the deployment
    stays HARVESTING, and the vessel counter is not double-incremented.

    Design: Corner/state_machines/second_activate_on_an_active_authorization_returns_invalid_authorization_state
    """
    world = _active_world()
    set_clock(SECOND_ACTIVATE_CLOCK)

    response = api_client.activate_harvest_authorization(
        world["authorization"]["id"], OPERATOR)

    body = validate_error(
        response, ApiErrorId.ERR_INVALID_AUTHORIZATION_STATE, 409)
    assert body["error_id"] != ApiErrorId.ERR_OUTSIDE_AUTHORIZATION_WINDOW

    authorization = get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], OPERATOR))
    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))

    assert authorization["status"] == "ACTIVE"
    assert authorization["harvest_start_at"] == to_millis(DW_ACTIVATE_CLOCK)
    assert authorization["harvest_end_at"] is None
    assert unit["status"] == "HARVESTING"
    assert vessel["active_authorization_count"] == 1


# --------------------------------------------------------------------------
# The dealer listing dimension and the suspension cascade
# --------------------------------------------------------------------------
def _dealer_holding_one_shipped_and_one_created_consignment():
    """One LISTED dealer holds two interstate consignments landed under the same
    authorization. LOT-A's shipment left the dock at 10:50 and is SHIPPED;
    LOT-B was landed on its own out-of-water span of 09:00 to 09:30 with
    temperature control at 10:45 -- 105 minutes against a 270-minute allowance,
    so it tags COMPLIANT -- then assembled into a second shipment that was never
    shipped, so that one is still CREATED. Ten plus twenty bushels stays inside
    the authorization's 600-bushel projection."""
    world = design_world(
        stage="shipped",
        shipment_overrides={"destination_state": "VA"},
        lot_overrides={"lot_code": "LOT-A"},
        shipped_at=SHIPPED_AT,
    )
    world["lot_a"] = world["lot"]
    world["ship_a"] = world["shipment"]
    world["lot_b"] = dw_land_lot(
        world,
        first_out_of_water_at=LOT_B_FIRST_OUT,
        last_out_of_water_at=LOT_B_LAST_OUT,
        placed_in_temperature_control_at=LOT_B_IN_CONTROL,
        lot_code="LOT-B",
        bushels=20,
    )
    world["lot_b"] = dw_tag_lot(world, world["lot_b"])
    world["ship_b"] = dw_assemble_shipment(
        world, [world["lot_b"]["id"]], destination_state="VA")
    return world


def test_suspension_holds_the_created_consignment_but_not_the_shipped_one():
    """A suspension out of LISTED sets `listing_status` SUSPENDED with
    `suspension_reason` AUTHORITY_ACTION -- not RECALL_STRIKES, since no recall
    was involved and `recall_strike_count` stays 0 -- and leaves the
    certification paperwork alone. Its cascade is deliberately narrow: it moves
    only shipments in CREATED, so LOT-B's consignment becomes HELD with
    `held_reason` DEALER_SUSPENSION while LOT-A's already-SHIPPED consignment is
    untouched, keeping a null `held_reason` and the 10:50 `shipped_at` it was
    stamped with. The lots follow their shipments: LOT-A stays SHIPPED and LOT-B
    stays TAGGED, because a hold is not an embargo.

    Design: Corner/state_machines/dealer_suspension_holds_created_shipments_but_not_shipped_ones
    """
    world = _dealer_holding_one_shipped_and_one_created_consignment()
    assert world["ship_b"]["status"] == "CREATED"

    dealer = validate_success(api_client.suspend_dealer(
        world["dealer"]["id"], suspend_payload(), AUTHORITY))

    assert dealer["listing_status"] == "SUSPENDED"
    assert dealer["suspension_reason"] == "AUTHORITY_ACTION"
    assert dealer["recall_strike_count"] == 0
    assert dealer["icssl_listed_through"] == "2027-06-30"
    assert dealer["certified_through"] == "2027-06-30"

    ship_a = get_success_data(
        api_client.get_shipment(world["ship_a"]["id"], AUTHORITY))
    ship_b = get_success_data(
        api_client.get_shipment(world["ship_b"]["id"], AUTHORITY))
    lot_a = get_success_data(
        api_client.get_harvest_lot(world["lot_a"]["id"], OPERATOR))
    lot_b = get_success_data(
        api_client.get_harvest_lot(world["lot_b"]["id"], OPERATOR))

    assert ship_b["status"] == "HELD"
    assert ship_b["held_reason"] == "DEALER_SUSPENSION"
    assert ship_b["recall_reason"] is None
    assert ship_a["status"] == "SHIPPED"
    assert ship_a["held_reason"] is None
    assert ship_a["shipped_at"] == to_millis(SHIPPED_AT)
    assert lot_a["status"] == "SHIPPED"
    assert lot_b["status"] == "TAGGED"


def test_a_newly_certified_dealer_starts_not_listed_with_zero_strikes():
    """Certification is the only entry into the dealer machine, and it lands on
    the least privileged of the three listing states: NOT_LISTED, with
    `icssl_listed_through` null because interstate listing arrives only with a
    later renewal, `suspension_reason` null, `recall_strike_count` 0 and
    `version` 1. The `certified_through` date the request supplied is stored as
    given, so a dealer can be certified for years and still not be listed --
    the two dates are independent.

    Design: Corner/state_machines/new_dealer_starts_not_listed_with_zero_strikes
    """
    set_clock(DW_CLOCK)

    dealer = validate_success(
        api_client.create_dealer(dw_dealer_payload(), AUTHORITY), 201)

    assert dealer["listing_status"] == "NOT_LISTED"
    assert dealer["icssl_listed_through"] is None
    assert dealer["suspension_reason"] is None
    assert dealer["recall_strike_count"] == 0
    assert dealer["version"] == 1
    assert dealer["certified_through"] == "2027-06-30"
    assert dealer["certification_no"] == DW_DEALER_CERT_NO


# --------------------------------------------------------------------------
# The seed-lot walk: the refused edge and the edge no endpoint owns
# --------------------------------------------------------------------------
def _received_seed_lot_world():
    """The chain up to a seed lot that has only been received. No screening has
    been recorded, so `status` is RECEIVED with `screening_result` null, and the
    nursery fields are all still empty. No vibrio plan is published because
    nothing here reaches a harvest."""
    return design_world(stage="seed", seed_stage="received", publish_plan=False)


def test_nursery_start_on_an_unscreened_lot_is_refused_by_the_state_rung():
    """Nursery grow-out starts only from SCREENED, so a lot still in RECEIVED is
    refused with ERR_INVALID_SEED_LOT_STATE at HTTP 409. The acting identity is
    the lease's own operator and the requested 2026-04-05 start is both at or
    after the 2026-04-01 `shipped_on` and well before the logical clock, so
    neither ERR_LEASE_OWNERSHIP_VIOLATION nor ERR_FUTURE_DATED_EVENT applies --
    and in any case rung 7 would answer before rung 10's future-dating test. The
    refused edge stamps nothing: `nursery_started_on` and `nursery_system` are
    still null and the lot has not moved.

    Design: Corner/state_machines/nursery_start_on_an_unscreened_seed_lot_returns_invalid_seed_lot_state
    """
    world = _received_seed_lot_world()
    assert world["seed_lot"]["status"] == "RECEIVED"

    response = api_client.start_nursery(
        world["seed_lot"]["id"],
        nursery_start_payload("2026-04-05", "UPWELLER"), OPERATOR)

    body = validate_error(response, ApiErrorId.ERR_INVALID_SEED_LOT_STATE, 409)
    assert body["error_id"] != ApiErrorId.ERR_LEASE_OWNERSHIP_VIOLATION
    assert body["error_id"] != ApiErrorId.ERR_FUTURE_DATED_EVENT

    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], OPERATOR))
    assert seed_lot["status"] == "RECEIVED"
    assert seed_lot["screening_result"] is None
    assert seed_lot["nursery_started_on"] is None
    assert seed_lot["nursery_system"] is None
    assert seed_lot["unallocated_seed_count"] == 0


def _world_with_two_thirds_of_the_seed_deployed():
    """The reference lot completed nursery with 60000 of its 100000 seed
    surviving, and the first deployment -- 40 BOTTOM gear units on plot P1 --
    took 40000 of them, so 20000 are still unallocated."""
    return design_world(
        stage="unit", unit_overrides={"seed_count_planted": 40000})


def test_the_last_unallocated_seed_bubbles_the_lot_up_to_planted():
    """READY_FOR_PLANTING -> PLANTED is not driven by any seed-lot capability: it
    follows the gear. The first deployment left `unallocated_seed_count` at 20000
    and the lot sitting in READY_FOR_PLANTING; a second deployment on plot P2
    that consumes exactly the remaining 20000 drives that figure to precisely 0
    and the lot bubbles up to PLANTED inside the deployment request itself. The
    allocated total is now the whole 60000 surviving seed, the lease's
    `deployed_gear_units` is 40 plus 60 against an authorized 200, and the first
    deployment is untouched by its sibling.

    Design: Corner/state_machines/seed_lot_bubbles_up_to_planted_when_the_last_unallocated_seed_is_deployed
    """
    world = _world_with_two_thirds_of_the_seed_deployed()
    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], OPERATOR))
    assert seed_lot["status"] == "READY_FOR_PLANTING"
    assert seed_lot["allocated_seed_count"] == 40000
    assert seed_lot["unallocated_seed_count"] == 20000

    unit_two = validate_success(api_client.create_growout_unit(
        growout_unit_payload(
            world["lease"]["id"], world["seed_lot"]["id"],
            plot_code="P2", gear_type="RACK_AND_BAG", gear_units=60,
            seed_count_planted=20000, deployed_on="2026-05-06",
            planned_retrieval_on="2026-10-20"),
        OPERATOR), 201)

    assert unit_two["status"] == "DEPLOYED"
    assert unit_two["plot_code"] == "P2"

    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], OPERATOR))
    lease = get_success_data(
        api_client.get_lease(world["lease"]["id"], AUTHORITY))
    unit_one = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))

    assert seed_lot["status"] == "PLANTED"
    assert seed_lot["allocated_seed_count"] == 60000
    assert seed_lot["unallocated_seed_count"] == 0
    assert seed_lot["surviving_seed_count"] == 60000
    assert lease["deployed_gear_units"] == 100
    assert lease["authorized_gear_units"] == 200
    assert unit_one["status"] == "DEPLOYED"


# --------------------------------------------------------------------------
# The investigation walk: a terminal state refuses both remaining edges
# --------------------------------------------------------------------------
def _closed_unsubstantiated_investigation_world():
    """A shipped interstate consignment, an investigation opened against it the
    next morning at 08:00 with the clock at 09:00, and then closed as
    unsubstantiated straight out of OPEN. Because no traceback was ever run, the
    investigation reaches its terminal state with `scope_variant` still null and
    both traced fields still at their opening values."""
    world = design_world(
        stage="shipped",
        shipment_overrides={"destination_state": "VA"},
        lot_overrides={"lot_code": "LOT-A"},
        shipped_at=SHIPPED_AT,
    )
    set_clock(INVESTIGATION_CLOCK)
    investigation = get_success_data(api_client.create_illness_investigation(
        world["shipment"]["id"], illness_investigation_payload(REPORTED_AT),
        AUTHORITY))
    world["investigation"] = validate_success(
        api_client.close_illness_investigation(
            investigation["id"], close_investigation_payload(), AUTHORITY))
    return world


def test_a_closed_unsubstantiated_investigation_refuses_traceback_and_confirm():
    """CLOSED_UNSUBSTANTIATED is terminal, so an investigation is decided exactly
    once. Traceback accepts only OPEN or TRACEBACK and confirmation accepts only
    TRACEBACK, so both requests are refused with the same
    ERR_INVALID_INVESTIGATION_STATE at HTTP 409. Neither refusal leaves a trace:
    `scope_variant` stays null, `traced_lot_ids` stays empty, `traced_lot_count`
    and `recalled_shipment_count` stay 0 and `confirmed_at` stays null. Most
    tellingly, the recall cascade never ran -- the source shipment is still
    SHIPPED with a null `recall_reason`, its lot is still SHIPPED, and the dealer
    keeps zero strikes and its LISTED standing.

    Design: Corner/state_machines/traceback_on_a_closed_unsubstantiated_investigation_returns_invalid_investigation_state
    """
    world = _closed_unsubstantiated_investigation_world()
    investigation_id = world["investigation"]["id"]
    assert world["investigation"]["status"] == "CLOSED_UNSUBSTANTIATED"

    traceback_response = api_client.run_traceback(
        investigation_id, traceback_payload("BROAD"), AUTHORITY)
    confirm_response = api_client.confirm_illness_investigation(
        investigation_id, confirm_payload(), AUTHORITY)

    validate_error(
        traceback_response, ApiErrorId.ERR_INVALID_INVESTIGATION_STATE, 409)
    validate_error(
        confirm_response, ApiErrorId.ERR_INVALID_INVESTIGATION_STATE, 409)

    investigation = get_success_data(
        api_client.get_illness_investigation(investigation_id, AUTHORITY))
    assert investigation["status"] == "CLOSED_UNSUBSTANTIATED"
    assert investigation["scope_variant"] is None
    assert investigation["traced_lot_ids"] == []
    assert investigation["traced_lot_count"] == 0
    assert investigation["recalled_shipment_count"] == 0
    assert investigation["confirmed_at"] is None

    shipment = get_success_data(
        api_client.get_shipment(world["shipment"]["id"], AUTHORITY))
    lot = get_success_data(
        api_client.get_harvest_lot(world["lot"]["id"], OPERATOR))
    dealer = get_success_data(
        api_client.get_dealer(world["dealer"]["id"], AUTHORITY))

    assert shipment["status"] == "SHIPPED"
    assert shipment["recall_reason"] is None
    assert lot["status"] == "SHIPPED"
    assert dealer["recall_strike_count"] == 0
    assert dealer["listing_status"] == "LISTED"


# --------------------------------------------------------------------------
# The area's harvest dimension gates issue, and an elapsed closure never
# self-heals
# --------------------------------------------------------------------------
def _deployment_on_an_area_closed_by_rainfall():
    """A complete deployment -- current inspection and predator-control logs, a
    LISTED dealer, a vessel of capacity 2 and rent paid through 2026-12-31 -- on
    an area whose 1.00-inch threshold was met by a 1.50-inch accumulation
    observed at midnight on 2026-07-25. That closed the area for harvest with a
    reopen-eligible instant of 2026-07-29, and the logical clock is left at the
    2026-08-01 epoch: already three days past eligibility, with no reopen
    requested."""
    world = design_world(stage="unit")
    world["rain"] = trigger_rainfall_closure(
        world["area"]["id"], RAIN_OBSERVED_AT, inches_24h=1.5,
        gauge_code="RG-7")
    return world


def test_issue_is_refused_while_the_area_is_still_closed_for_rainfall():
    """The `harvest_status` gate bites at issue, not only at activation, and an
    elapsed closure does not self-heal: reopening is a separate authority act on
    the other dimension, so the area is still CLOSED_RAINFALL even though the
    clock has passed `closure_reopen_eligible_at`. The issue is therefore refused
    with ERR_AREA_HARVEST_CLOSED at HTTP 409. The two area dimensions stay
    orthogonal -- a rainfall event never touches `classification`, which is still
    APPROVED, so ERR_AREA_CLASSIFICATION_NOT_HARVESTABLE is not the answer -- and
    the 2026-07-20 husbandry logs are current, ruling out ERR_HUSBANDRY_LAPSED.
    Nothing is created: `open_authorization_count` stays 0 and no authorization
    exists. The design's list read is filtered by lease; the PRD names that
    filter but not its query-parameter spelling, so the unfiltered list is
    asserted instead, which is equivalent here because each test runs against a
    fresh database holding only this lease.

    Design: Corner/state_machines/issue_authorization_while_the_area_is_closed_for_rainfall_returns_area_harvest_closed
    """
    world = _deployment_on_an_area_closed_by_rainfall()
    assert world["rain"]["triggered_closure"] is True

    response = api_client.create_harvest_authorization(
        harvest_authorization_payload(
            world["lease"]["id"], world["unit"]["id"], world["vessel"]["id"],
            world["dealer"]["id"], DW_WINDOW_START, DW_WINDOW_END,
            projected_bushels=600),
        OPERATOR)

    body = validate_error(response, ApiErrorId.ERR_AREA_HARVEST_CLOSED, 409)
    assert body["error_id"] != ApiErrorId.ERR_AREA_CLASSIFICATION_NOT_HARVESTABLE
    assert body["error_id"] != ApiErrorId.ERR_HUSBANDRY_LAPSED

    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["harvest_status"] == "CLOSED_RAINFALL"
    assert area["classification"] == "APPROVED"
    assert area["last_closure_started_at"] == to_millis(RAIN_OBSERVED_AT)
    assert area["closure_reopen_eligible_at"] == to_millis(
        RAIN_REOPEN_ELIGIBLE_AT)
    assert area["open_authorization_count"] == 0

    _rows, meta = validate_paginated(
        api_client.list_harvest_authorizations(AUTHORITY))
    assert meta["total_count"] == 0
