"""The two four-hop cascades and the listing gate on shipping (PRD §3.3, §3.9).

The area-closure cascade runs downstream from a rainfall reading that names none
of the rows it moves; the recall cascade runs in the opposite direction, climbing
from a leaf investigation to the dealer and back down onto a consignment the
traceback never traced. Both are entered by a single write.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    confirm_payload,
    design_world,
    DW_AREA_CODE,
    dw_assemble_shipment,
    dw_land_lot,
    dw_ship,
    get_success_data,
    illness_investigation_payload,
    iso,
    issue_authorization,
    set_clock,
    ship_payload,
    tag_lot,
    TEST_USERS,
    to_millis,
    traceback_payload,
    trigger_rainfall_closure,
    validate_error,
    validate_success,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# --------------------------------------------------------------------------
# Downstream: one rainfall reading, four hops
# --------------------------------------------------------------------------
RAIN_OBSERVED_AT = iso(2026, 8, 10, 10, 50)
RAIN_REOPEN_ELIGIBLE_AT = iso(2026, 8, 14, 10, 50)


def _world_swept_by_one_rainfall_reading():
    """A complete harvest chain -- an ACTIVE authorization, a landed and tagged
    10-bushel lot, and a CREATED interstate shipment holding it -- and then a
    single 1.5-inch accumulation on the growing area against a threshold of 1.0.
    The rainfall event names the area only; it mentions no authorization, no
    vessel, no lot and no shipment."""
    world = design_world(
        stage="shipment",
        shipment_overrides={"destination_state": "VA"},
        lot_overrides={"lot_code": "LOT-001"},
    )
    world["rain"] = trigger_rainfall_closure(
        world["area"]["id"], RAIN_OBSERVED_AT, inches_24h=1.5, gauge_code="RG-7")
    return world


def test_one_rainfall_reading_closes_the_area_without_touching_its_classification():
    """1.5 inches is at or above the area's 1.0-inch threshold, so
    `triggered_closure` is true and `harvest_status` moves to CLOSED_RAINFALL,
    while `classification` is never touched by a rainfall event and stays
    APPROVED. The closure clock is anchored on the event's `observed_at` rather
    than on the logical clock: `last_closure_started_at` is 10:50 on 2026-08-10
    and `closure_reopen_eligible_at` is that instant plus the area's 96
    `rainfall_closure_hours`, four days later.

    Design: Difficulty/transitive_cascade/rainfall_closure_cascades_authorization_void_lot_embargo_shipment_hold
    """
    world = _world_swept_by_one_rainfall_reading()

    assert world["rain"]["triggered_closure"] is True
    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["harvest_status"] == "CLOSED_RAINFALL"
    assert area["classification"] == "APPROVED"
    assert area["last_closure_started_at"] == to_millis(RAIN_OBSERVED_AT)
    assert area["closure_reopen_eligible_at"] == to_millis(
        RAIN_REOPEN_ELIGIBLE_AT)
    assert area["consecutive_clean_samples"] == 0


def test_the_closure_walks_from_the_authorization_out_to_vessel_and_deployment():
    """Hop 1 voids the ACTIVE authorization with `void_reason` AREA_CLOSURE and
    the event records the one authorization it voided in
    `voided_authorization_count`. Hop 2 rides that void onto two further rows the
    event never named: the vessel's `active_authorization_count` is released back
    to 0 and the deployment returns from HARVESTING to DEPLOYED.

    Design: Difficulty/transitive_cascade/rainfall_closure_cascades_authorization_void_lot_embargo_shipment_hold
    """
    world = _world_swept_by_one_rainfall_reading()

    assert world["rain"]["voided_authorization_count"] == 1
    authorization = get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], OPERATOR))
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))
    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))

    assert authorization["status"] == "VOIDED"
    assert authorization["void_reason"] == "AREA_CLOSURE"
    assert vessel["active_authorization_count"] == 0
    assert unit["status"] == "DEPLOYED"


def test_the_closure_reaches_the_lot_and_its_shipment_two_hops_further():
    """Hop 3 embargoes the voided authorization's TAGGED lot with
    `embargo_reason` AREA_CLOSURE, and hop 4 drags the CREATED shipment holding
    that lot to HELD with `held_reason` LOT_EMBARGO. The cascade is a safety
    action, not a reversal: the lease's `royalty_accrued_cents` still holds the
    lot's 3760-cent settlement and every shellstock-tag field the lot earned is
    retained.

    Design: Difficulty/transitive_cascade/rainfall_closure_cascades_authorization_void_lot_embargo_shipment_hold
    """
    world = _world_swept_by_one_rainfall_reading()

    lot = get_success_data(api_client.get_harvest_lot(
        world["lot"]["id"], OPERATOR))
    shipment = get_success_data(api_client.get_shipment(
        world["shipment"]["id"], AUTHORITY))
    lease = get_success_data(
        api_client.get_lease(world["lease"]["id"], AUTHORITY))

    assert lot["status"] == "EMBARGOED"
    assert lot["embargo_reason"] == "AREA_CLOSURE"
    assert shipment["status"] == "HELD"
    assert shipment["held_reason"] == "LOT_EMBARGO"
    assert shipment["recall_reason"] is None
    assert lease["royalty_accrued_cents"] == 3760
    assert lot["tag_area_code"] == DW_AREA_CODE
    assert lot["tag_harvest_date"] == "2026-08-10"


# --------------------------------------------------------------------------
# Upstream: one confirmation, four hops climbing to the dealer and back
# --------------------------------------------------------------------------
SHIP1_AT = iso(2026, 8, 10, 10, 45)
SHIP2_AT = iso(2026, 8, 10, 10, 50)
AUG15_WINDOW_START = iso(2026, 8, 15, 6)
AUG15_WINDOW_END = iso(2026, 8, 15, 18)
AUG15_HARVEST_CLOCK = iso(2026, 8, 15, 11)
REPORTED_AT = iso(2026, 8, 15, 10)
CONFIRMED_AT = iso(2026, 8, 15, 11)


def _confirmed_broad_recall_world():
    """One dealer holds three consignments. Two carry lots harvested on
    2026-08-10 out of area GA-114 and have already shipped; the third carries a
    lot harvested five days later under a second authorization and is still
    CREATED. A BROAD traceback is run from the first shipment and confirmed."""
    world = design_world(
        stage="shipped",
        shipment_overrides={"destination_state": "VA"},
        lot_overrides={"lot_code": "LOT-001"},
        shipped_at=SHIP1_AT,
    )
    world["lot1"] = world["lot"]
    world["ship1"] = world["shipment"]

    world["lot2"] = dw_land_lot(world, lot_code="LOT-002")
    world["lot2"] = tag_lot(world, world["lot2"], harvest_date="2026-08-10")
    world["ship2"] = dw_assemble_shipment(
        world, [world["lot2"]["id"]], destination_state="VA")
    dw_ship(world, world["ship2"], SHIP2_AT)

    world["auth1"] = validate_success(api_client.close_harvest_authorization(
        world["authorization"]["id"], OPERATOR))
    set_clock(AUG15_WINDOW_START)
    auth2 = issue_authorization(
        world["lease"], world["unit"], world["vessel"], world["dealer"],
        AUG15_WINDOW_START, AUG15_WINDOW_END, OPERATOR,
        {"projected_bushels": 600})
    world["auth2"] = get_success_data(
        api_client.activate_harvest_authorization(auth2["id"], OPERATOR))

    set_clock(AUG15_HARVEST_CLOCK)
    world["lot3"] = dw_land_lot(
        world,
        first_out_of_water_at=iso(2026, 8, 15, 6),
        last_out_of_water_at=iso(2026, 8, 15, 8),
        placed_in_temperature_control_at=iso(2026, 8, 15, 10, 30),
        authorization=world["auth2"], lot_code="LOT-003")
    world["lot3"] = tag_lot(world, world["lot3"], harvest_date="2026-08-15")
    world["ship3"] = dw_assemble_shipment(
        world, [world["lot3"]["id"]], destination_state="VA")

    investigation = get_success_data(api_client.create_illness_investigation(
        world["ship1"]["id"],
        illness_investigation_payload(REPORTED_AT, illness_count=5),
        AUTHORITY))
    get_success_data(api_client.run_traceback(
        investigation["id"], traceback_payload("BROAD"), AUTHORITY))
    world["investigation"] = validate_success(
        api_client.confirm_illness_investigation(
            investigation["id"], confirm_payload(confirmed_at=CONFIRMED_AT),
            AUTHORITY))
    return world


def test_a_broad_traceback_pulls_in_the_sibling_lot_off_the_other_shipment():
    """The seed set is only the source shipment's own lot, but BROAD casts a net
    over the same waters on the same days: the second lot shares
    `tag_area_code` GA-114 and the same `tag_harvest_date`, so it is pulled in
    across the consignment boundary and `traced_lot_count` is 2. Hop 1 then
    recalls both traced lots, and the supplied `confirmed_at` is what is stored.

    Design: Difficulty/transitive_cascade/illness_confirmation_cascades_lot_recall_shipment_recall_dealer_suspension
    """
    world = _confirmed_broad_recall_world()
    investigation = world["investigation"]

    assert investigation["status"] == "CONFIRMED"
    assert investigation["confirmed_at"] == to_millis(CONFIRMED_AT)
    assert investigation["traced_lot_count"] == 2
    assert investigation["recalled_shipment_count"] == 2

    for key in ("lot1", "lot2"):
        lot = get_success_data(api_client.get_harvest_lot(
            world[key]["id"], OPERATOR))
        assert lot["status"] == "RECALLED"


def test_two_recalled_shipments_earn_two_strikes_and_suspend_the_dealer():
    """Hop 2 climbs from each recalled lot to its own shipment -- two distinct
    shipments, both already SHIPPED, both moved to RECALLED with `recall_reason`
    ILLNESS_TRACEBACK. Hop 3 climbs one further to the dealer they share, adding
    one strike per recalled shipment: `recall_strike_count` reaches 2, which is
    at the inclusive DEALER_SUSPENSION_STRIKE_THRESHOLD, so the LISTED dealer
    moves to SUSPENDED with `suspension_reason` RECALL_STRIKES.

    Design: Difficulty/transitive_cascade/illness_confirmation_cascades_lot_recall_shipment_recall_dealer_suspension
    """
    world = _confirmed_broad_recall_world()

    for key in ("ship1", "ship2"):
        shipment = get_success_data(api_client.get_shipment(
            world[key]["id"], AUTHORITY))
        assert shipment["status"] == "RECALLED"
        assert shipment["recall_reason"] == "ILLNESS_TRACEBACK"

    dealer = get_success_data(
        api_client.get_dealer(world["dealer"]["id"], AUTHORITY))
    assert dealer["recall_strike_count"] == 2
    assert dealer["listing_status"] == "SUSPENDED"
    assert dealer["suspension_reason"] == "RECALL_STRIKES"


def test_the_fourth_hop_holds_a_consignment_the_traceback_never_traced():
    """Hop 4 descends from the suspended dealer onto its remaining CREATED
    consignment. The third shipment was never implicated -- its lot's
    `tag_harvest_date` of 2026-08-15 is five days outside the one-day
    TRACEBACK_DAY_WINDOW, so that lot stays TAGGED and is not recalled -- yet the
    shipment is HELD with `held_reason` DEALER_SUSPENSION and `recall_reason`
    still null, which distinguishes collateral from implicated. The recall
    cascade touches no authorization: the first stays CLOSED, the second stays
    ACTIVE, and the vessel still carries one.

    Design: Difficulty/transitive_cascade/illness_confirmation_cascades_lot_recall_shipment_recall_dealer_suspension
    """
    world = _confirmed_broad_recall_world()

    ship3 = get_success_data(api_client.get_shipment(
        world["ship3"]["id"], AUTHORITY))
    lot3 = get_success_data(api_client.get_harvest_lot(
        world["lot3"]["id"], OPERATOR))

    assert ship3["status"] == "HELD"
    assert ship3["held_reason"] == "DEALER_SUSPENSION"
    assert ship3["recall_reason"] is None
    assert lot3["status"] == "TAGGED"
    assert lot3["tag_harvest_date"] == "2026-08-15"

    auth1 = get_success_data(api_client.get_harvest_authorization(
        world["auth1"]["id"], OPERATOR))
    auth2 = get_success_data(api_client.get_harvest_authorization(
        world["auth2"]["id"], OPERATOR))
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))

    assert auth1["status"] == "CLOSED"
    assert auth2["status"] == "ACTIVE"
    assert vessel["active_authorization_count"] == 1


# --------------------------------------------------------------------------
# The listing gate reads a party entity outside the harvest aggregate
# --------------------------------------------------------------------------
INTRASTATE_SHIP_AT = iso(2026, 8, 10, 10, 45)


def _intrastate_shipment_of_an_unlisted_dealer():
    """The dealer was registered but no certification renewal was ever recorded,
    so it is still NOT_LISTED with `icssl_listed_through` null even though its
    `certified_through` is years away. Its shipment is deliberately intrastate --
    a North Carolina destination for a North Carolina dealer -- and every field of
    the shipment itself is valid."""
    return design_world(
        stage="shipment",
        list_dealer=False,
        lot_overrides={"lot_code": "LOT-001"},
        shipment_overrides={"destination_state": "NC"},
    )


def test_an_intrastate_shipment_is_still_blocked_by_an_unlisted_dealer():
    """Shipping reads the dealer's `listing_status`, a party record outside the
    harvest aggregate the shipment belongs to. Because `is_interstate` is false
    the interstate listing rule does not apply, so the answer is the general
    ERR_DEALER_NOT_LISTED at HTTP 409 rather than
    ERR_DEALER_NOT_LISTED_FOR_INTERSTATE.

    Design: Difficulty/cross_entity_state_dependency/shipment_ship_blocked_by_unlisted_dealer
    """
    world = _intrastate_shipment_of_an_unlisted_dealer()
    assert world["shipment"]["is_interstate"] is False

    response = api_client.ship_shipment(
        world["shipment"]["id"], ship_payload(INTRASTATE_SHIP_AT),
        world["dealer_headers"])

    body = validate_error(response, ApiErrorId.ERR_DEALER_NOT_LISTED, 409)
    assert body["error_id"] != ApiErrorId.ERR_DEALER_NOT_LISTED_FOR_INTERSTATE


def test_the_refused_shipment_leaves_the_lot_and_the_dealer_untouched():
    """The refusal changes nothing: the shipment stays CREATED with `shipped_at`
    null and `is_interstate` false, its lot stays TAGGED rather than moving to
    SHIPPED, and the dealer keeps every field it had -- NOT_LISTED, a null
    `icssl_listed_through`, a `certified_through` of 2027-06-30 and no strikes.

    Design: Difficulty/cross_entity_state_dependency/shipment_ship_blocked_by_unlisted_dealer
    """
    world = _intrastate_shipment_of_an_unlisted_dealer()
    api_client.ship_shipment(
        world["shipment"]["id"], ship_payload(INTRASTATE_SHIP_AT),
        world["dealer_headers"])

    shipment = get_success_data(api_client.get_shipment(
        world["shipment"]["id"], AUTHORITY))
    lot = get_success_data(api_client.get_harvest_lot(
        world["lot"]["id"], OPERATOR))
    dealer = get_success_data(
        api_client.get_dealer(world["dealer"]["id"], AUTHORITY))

    assert shipment["status"] == "CREATED"
    assert shipment["shipped_at"] is None
    assert shipment["is_interstate"] is False
    assert lot["status"] == "TAGGED"
    assert dealer["listing_status"] == "NOT_LISTED"
    assert dealer["icssl_listed_through"] is None
    assert dealer["certified_through"] == "2027-06-30"
    assert dealer["recall_strike_count"] == 0
