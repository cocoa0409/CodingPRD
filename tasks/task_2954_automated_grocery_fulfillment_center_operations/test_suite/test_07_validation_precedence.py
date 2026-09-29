"""Which refusal a fulfillment-centre request earns when it breaks several house rules at once.

A shopper who books a slot with a mistyped slot reference, a mistyped basket reference
and a stale view of that basket all in one request is told about the slot and nothing
else; an operator who offers a substitute that supersedes an offer the shopper has not
yet answered is told the supersede target is wrong rather than that the round is still
open; and an administrator who withholds capacity is measured against the physical
ceiling of the slot rather than against what is still on sale, so the withholding that
drives the slot negative bumps a confirmed shopper instead of being refused. Alongside
that single ordered gate sit the guards that only some requests ever meet: a measured
weight is reconciled against a tolerance band only for goods sold by weight and is not
even accepted on goods sold by the unit, the uncommitted-stock guard is summed across
every line of a wave rather than tested line by line, and the grid-zone service status
that blocks a substitution approval belongs to the substitute's zone rather than to the
short line itself. Each test below drives one such collision to the floor and reads back
the one refusal the contract names, together with the proof that nothing else moved.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_int_field,
    assert_money,
    assert_order_money,
    assert_order_statuses,
    assert_ratio,
    assert_sku_ledger,
    assert_slot_ledger,
    assert_status,
    assert_surge_multiplier,
    list_items_and_meta,
    read_object,
)
from test_helpers.constants import MINIMUM_ORDER_CENTS
from test_helpers.types import (
    BillingStatus,
    BookingStatus,
    FulfillmentStatus,
    GridZoneStatus,
    LineStatus,
    PickTaskStatus,
    ProposalStatus,
    SubstitutionResolution,
    TemperatureZone,
    WaveStatus,
)

AMBIENT = TemperatureZone.AMBIENT.value
CHILLED = TemperatureZone.CHILLED.value


def _two_short_lines_with_one_declined_round(api):
    """A basket whose two ambient lines both came back empty from the grid.

    The first line's opening offer has been sent to the shopper and refused, so
    that line is short with no offer outstanding; the second line still carries
    the offer the picking floor raised automatically.
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    ambient_zone = fixtures.create_grid_zone(api, temperature_zone=AMBIENT)
    chilled_zone = fixtures.create_grid_zone(api, temperature_zone=CHILLED)
    fixtures.create_pick_station(
        api, temperature_zone_capability=[AMBIENT], max_concurrent_totes=3
    )
    pasta, penne, fusilli = fixtures.build_substitution_group(
        api, ambient_zone["id"], "DRY", [700, 750, 760], physical_units=100
    )
    cream = fixtures.create_inventory_sku(
        api,
        chilled_zone["id"],
        temperature_zone=CHILLED,
        substitution_group_code="DRY",
        unit_price_cents=900,
        physical_units=100,
    )
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)
    picking = fixtures.build_picking_wave(
        api, route["id"], slot["id"], [pasta["id"], penne["id"]], ordered_qty=2, units=4
    )
    pasta_line, penne_line = picking["lines"]
    tote = None
    for line in (pasta_line, penne_line):
        task = fixtures.pick_task_for_line(api, line["id"])
        driven = fixtures.drive_task_to_retrieving(
            api,
            task["id"],
            picking["wave"]["id"],
            task["pick_station_id"],
            AMBIENT,
            tote=tote,
        )
        tote = driven["tote"]
        fixtures.complete_pick_task(api, task["id"], 0)
    account_id = picking["account"]["id"]
    declined_round = fixtures.proposal_for_line(api, pasta_line["id"])
    fixtures.propose_substitution(api, declined_round["id"])
    fixtures.decline_substitution(api, account_id, declined_round["id"])
    return {
        "account_id": account_id,
        "order_id": picking["order"]["id"],
        "pasta_line_id": pasta_line["id"],
        "penne_line_id": penne_line["id"],
        "pasta": pasta,
        "penne": penne,
        "fusilli": fusilli,
        "cream": cream,
        "declined_round": declined_round,
        "open_round": fixtures.proposal_for_line(api, penne_line["id"]),
    }


def test_superseding_a_still_open_offer_names_the_supersede_target_not_the_open_round(
    api, pick_operator_headers
):
    """An offer that supersedes an unanswered offer on a line that is still open is
    refused for the supersede target, because that guard is checked first.

    Cites the requirement it rests on: "When more than one condition is violated by the same request, the identifier returned is the one whose gate sits earliest in the ordered precedence of §2.8."

    Design: Corner/validations/proposal_creation_guards_rank_the_supersede_target_above_already_open
    """
    floor = _two_short_lines_with_one_declined_round(api)
    line = fixtures.read_order_line(api, floor["account_id"], floor["penne_line_id"])

    response = api.create_substitution_proposal(
        factories.substitution_proposal_payload(
            floor["penne_line_id"],
            floor["pasta"]["id"],
            line["version"],
            supersedes_proposal_id=floor["open_round"]["id"],
        ),
        pick_operator_headers,
    )
    validate_error(response, ApiError.SUPERSEDE_TARGET_INVALID.value)

    untouched = fixtures.read_substitution_proposal(api, floor["open_round"]["id"])
    assert_status(untouched, ProposalStatus.DRAFT.value)
    _items, meta = list_items_and_meta(
        api.list_substitution_proposals(
            pick_operator_headers, params={"order_line_id": floor["penne_line_id"]}
        )
    )
    assert meta["total_count"] == 1, "the refused offer must not have been recorded"


def test_each_substitution_offer_guard_answers_alone_and_a_refused_round_may_be_superseded(
    api, pick_operator_headers
):
    """Offered on their own, a chilled substitute for an ambient line and a fresh offer
    on a line whose offer is still open earn their own refusals, while superseding the
    round the shopper actually refused opens round two.

    Cites the requirement it rests on: "A line that already has a proposal in `DRAFT` or `PROPOSED` refuses a new one with `ERR_PROPOSAL_ALREADY_OPEN`."

    Design: Corner/validations/proposal_creation_guards_rank_the_supersede_target_above_already_open
    """
    floor = _two_short_lines_with_one_declined_round(api)
    account_id = floor["account_id"]
    pasta_line_id = floor["pasta_line_id"]
    penne_line_id = floor["penne_line_id"]

    across_the_cold_chain = api.create_substitution_proposal(
        factories.substitution_proposal_payload(
            pasta_line_id,
            floor["cream"]["id"],
            fixtures.read_order_line(api, account_id, pasta_line_id)["version"],
        ),
        pick_operator_headers,
    )
    validate_error(across_the_cold_chain, ApiError.SUBSTITUTE_NOT_COMPARABLE.value)

    onto_an_open_round = api.create_substitution_proposal(
        factories.substitution_proposal_payload(
            penne_line_id,
            floor["pasta"]["id"],
            fixtures.read_order_line(api, account_id, penne_line_id)["version"],
        ),
        pick_operator_headers,
    )
    validate_error(onto_an_open_round, ApiError.PROPOSAL_ALREADY_OPEN.value)

    second_round = read_object(
        api.create_substitution_proposal(
            factories.substitution_proposal_payload(
                pasta_line_id,
                floor["penne"]["id"],
                fixtures.read_order_line(api, account_id, pasta_line_id)["version"],
                supersedes_proposal_id=floor["declined_round"]["id"],
            ),
            pick_operator_headers,
        ),
        201,
    )
    assert_status(second_round, ProposalStatus.DRAFT.value)
    assert_int_field(second_round, "round_no", 2)
    assert second_round["supersedes_proposal_id"] == floor["declined_round"]["id"]
    assert second_round["substitute_sku_id"] == floor["penne"]["id"]
    assert_money(second_round, "proposed_price_delta_cents", 100)
    assert_field_absent_or_null(second_round, "expires_at")

    line = fixtures.read_order_line(api, account_id, pasta_line_id)
    assert_status(line, LineStatus.SHORT.value, field="line_status")
    assert_status(
        line, SubstitutionResolution.PENDING.value, field="substitution_resolution"
    )
    order = fixtures.read_order(api, account_id, floor["order_id"])
    assert_int_field(order, "open_substitution_count", 2)
    assert order["dispatch_blocked"] is True


def _slot_holding_one_confirmed_booking_and_a_second_basket(api):
    """A ten-unit slot carrying one confirmed two-unit booking, plus a waiting basket."""
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api, temperature_zone=AMBIENT)
    sku = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=10, withheld_units=0
    )
    booked = fixtures.build_confirmed_order(
        api, route["id"], slot["id"], [sku["id"]], ordered_qty=2, units=2
    )
    waiting = fixtures.build_shopper_with_basket(
        api, route["id"], [sku["id"]], ordered_qty=2
    )
    return {"slot": slot, "booked": booked, "waiting": waiting}


def test_withholding_up_to_the_physical_ceiling_bumps_the_confirmed_shopper(api):
    """Withholding is measured against the slot's physical capacity less what is already
    withheld, so the withholding that drives the slot negative is admitted and repairs
    the ledger by bumping the confirmed booking rather than refusing the request.

    Cites the requirement it rests on: "Each bumped booking advances `CONFIRMED → BUMPED`, and its order falls back on both dimensions: `fulfillment_status` goes `SLOTTED → DRAFT`, `billing_status` goes `AUTHORIZED → PENDING_AUTH`, `authorized_amount_cents` reverts to null, and because the order no longer holds a booking in `HELD` or `CONFIRMED`, the waterfall's step 2 now stops early, so `delivery_fee_cents`, `loyalty_discount_cents` and `order_total_cents` all revert to null as well."

    Design: Corner/validations/withhold_capacity_bumps_a_confirmed_booking_but_never_breaches_the_physical_ceiling
    """
    yard = _slot_holding_one_confirmed_booking_and_a_second_basket(api)
    slot_id = yard["slot"]["id"]
    account_id = yard["booked"]["account"]["id"]
    booking_id = yard["booked"]["booking"]["id"]
    order_id = yard["booked"]["order"]["id"]

    slot = fixtures.withhold_capacity(api, slot_id, 8)
    assert_slot_ledger(
        slot,
        total_capacity_units=10,
        withheld_units=8,
        held_units=0,
        confirmed_units=2,
        available_units=0,
    )
    assert_surge_multiplier(slot, 1.35)
    assert_status(
        fixtures.read_slot_booking(api, booking_id), BookingStatus.CONFIRMED.value
    )

    slot = fixtures.withhold_capacity(api, slot_id, 2)
    assert_slot_ledger(
        slot,
        total_capacity_units=10,
        withheld_units=10,
        held_units=0,
        confirmed_units=0,
        available_units=0,
    )
    assert_surge_multiplier(slot, 1.00)
    assert_status(
        fixtures.read_slot_booking(api, booking_id), BookingStatus.BUMPED.value
    )

    order = fixtures.read_order(api, account_id, order_id)
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
    assert_money(order, "merchandise_subtotal_cents", 1400)
    for field in (
        "authorized_amount_cents",
        "delivery_fee_cents",
        "loyalty_discount_cents",
        "order_total_cents",
    ):
        assert_field_absent_or_null(order, field)


def test_withholding_past_the_ceiling_and_booking_a_fully_withheld_slot_are_both_refused(
    api, admin_headers, make_customer_headers
):
    """Once every unit of a slot is withheld, one more unit of withholding breaches the
    slot's physical capacity and a one-unit booking could never be satisfied, so the two
    requests are refused rather than being absorbed or waitlisted.

    Cites the requirement it rests on: "And the requested `units` may not exceed the slot's `total_capacity_units` less its `withheld_units`, because such a booking could never be satisfied even from a completely empty slot; that refusal is `ERR_SLOT_UNITS_EXCEED_CAPACITY`."

    Design: Corner/validations/withhold_capacity_bumps_a_confirmed_booking_but_never_breaches_the_physical_ceiling
    """
    yard = _slot_holding_one_confirmed_booking_and_a_second_basket(api)
    slot_id = yard["slot"]["id"]
    fixtures.withhold_capacity(api, slot_id, 8)
    fixtures.withhold_capacity(api, slot_id, 2)

    over_the_ceiling = api.withhold_capacity(
        slot_id, factories.capacity_units_payload(1), admin_headers
    )
    validate_error(over_the_ceiling, ApiError.WITHHELD_UNITS_EXCEEDED.value)
    assert_slot_ledger(
        fixtures.read_delivery_slot(api, slot_id),
        total_capacity_units=10,
        withheld_units=10,
        available_units=0,
    )

    waiting_account_id = yard["waiting"]["account"]["id"]
    waiting_order = fixtures.read_order(
        api, waiting_account_id, yard["waiting"]["order"]["id"]
    )
    unsatisfiable = api.create_slot_booking(
        factories.slot_booking_payload(
            slot_id, waiting_order["id"], waiting_order["version"], units=1
        ),
        make_customer_headers(waiting_account_id),
    )
    validate_error(unsatisfiable, ApiError.SLOT_UNITS_EXCEED_CAPACITY.value)
    _items, meta = list_items_and_meta(
        api.list_slot_bookings(
            admin_headers, params={"customer_order_id": waiting_order["id"]}
        )
    )
    assert meta["total_count"] == 0, "the refused booking must not have been waitlisted"


def test_a_booking_sitting_exactly_on_the_minimum_basket_and_the_bookable_ceiling_is_held(
    api, make_customer_headers
):
    """Every fiscal and referential guard on a slot booking is a non-strict comparison,
    so a ten-dollar basket booking exactly the slot's bookable units on its own home
    route is admitted and holds that capacity.

    Cites the requirement it rests on: "The order meets the minimum basket value: its `merchandise_subtotal_cents` is at least ten dollars, that is 1,000 cents, at the moment a slot booking is created."

    Design: Corner/validations/booking_exactly_at_the_minimum_order_and_capacity_ceiling_is_accepted
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api, temperature_zone=AMBIENT)
    sku = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=1000, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=5, withheld_units=3
    )
    basket = fixtures.build_shopper_with_basket(
        api, route["id"], [sku["id"]], ordered_qty=1
    )
    account_id = basket["account"]["id"]
    order = fixtures.read_order(api, account_id, basket["order"]["id"])
    assert_money(order, "merchandise_subtotal_cents", MINIMUM_ORDER_CENTS)

    booking = read_object(
        api.create_slot_booking(
            factories.slot_booking_payload(
                slot["id"], order["id"], order["version"], units=2
            ),
            make_customer_headers(account_id),
        ),
        201,
    )
    assert_status(booking, BookingStatus.HELD.value)
    assert_int_field(booking, "units", 2)
    assert_ratio(booking, "surge_multiplier_at_booking", 1.00, places=2)
    assert_money(booking, "quoted_fee_cents", 599)

    assert_slot_ledger(
        fixtures.read_delivery_slot(api, slot["id"]),
        total_capacity_units=5,
        withheld_units=3,
        held_units=2,
        confirmed_units=0,
        available_units=0,
    )
    assert_surge_multiplier(fixtures.read_delivery_slot(api, slot["id"]), 1.35)

    order = fixtures.read_order(api, account_id, order["id"])
    assert_order_money(
        order,
        merchandise_subtotal_cents=1000,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=1599,
    )
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )


def _basket_whose_version_has_moved_on(api):
    """A seven-hundred-cent basket of three units whose held version is one behind.

    The shopper's earlier reading of the basket was taken before a third unit was
    added, so that reading no longer matches the basket the fulfillment centre
    holds.
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api, temperature_zone=AMBIENT)
    sku = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)
    basket = fixtures.build_shopper_with_basket(
        api, route["id"], [sku["id"]], ordered_qty=2
    )
    account_id = basket["account"]["id"]
    order_id = basket["order"]["id"]
    stale_version = fixtures.read_order(api, account_id, order_id)["version"]
    fixtures.add_order_line(api, account_id, order_id, sku["id"], ordered_qty=1)
    return {
        "account_id": account_id,
        "order_id": order_id,
        "slot_id": slot["id"],
        "stale_version": stale_version,
    }


def test_a_booking_naming_two_unknown_records_is_refused_for_the_slot_first(
    api, admin_headers, make_customer_headers
):
    """A booking request that names an unknown slot, an unknown basket and a stale basket
    version all at once is answered about the slot, then about the basket once the slot is
    repaired, and only about the stale version once both records resolve.

    Cites the requirement it rests on: "Every foreign-key identifier supplied in the request body exists, validated in the order in which the fields are listed for that endpoint. Violation yields the same resource-specific not-found code as check 5, with HTTP 404. Applies to every `POST` endpoint whose body contains an identifier field."

    Design: Corner/validations/body_foreign_keys_are_resolved_left_to_right_before_the_occ_guard
    """
    basket = _basket_whose_version_has_moved_on(api)
    shopper = make_customer_headers(basket["account_id"])

    both_unknown = api.create_slot_booking(
        factories.slot_booking_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, basket["stale_version"], units=3
        ),
        shopper,
    )
    validate_error(both_unknown, ApiError.SLOT_NOT_FOUND.value)

    order_unknown = api.create_slot_booking(
        factories.slot_booking_payload(
            basket["slot_id"], NON_EXISTENT_UUID, basket["stale_version"], units=3
        ),
        shopper,
    )
    validate_error(order_unknown, ApiError.ORDER_NOT_FOUND.value)

    stale_only = api.create_slot_booking(
        factories.slot_booking_payload(
            basket["slot_id"], basket["order_id"], basket["stale_version"], units=3
        ),
        shopper,
    )
    validate_error(stale_only, ApiError.STALE_VERSION.value)

    assert_slot_ledger(
        fixtures.read_delivery_slot(api, basket["slot_id"]),
        total_capacity_units=10,
        withheld_units=0,
        held_units=0,
        confirmed_units=0,
        available_units=10,
    )
    _items, meta = list_items_and_meta(
        api.list_slot_bookings(
            admin_headers, params={"customer_order_id": basket["order_id"]}
        )
    )
    assert meta["total_count"] == 0, "no booking may survive a refused request"


def test_the_same_booking_succeeds_once_the_shopper_quotes_the_current_basket_version(
    api, admin_headers, make_customer_headers
):
    """With both records resolving and the basket version quoted as the fulfillment centre
    now holds it, the booking is admitted, takes its capacity out of the slot and prices
    the basket.

    Cites the requirement it rests on: "If `expected_order_version` does not equal that order's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no booking is created."

    Design: Corner/validations/body_foreign_keys_are_resolved_left_to_right_before_the_occ_guard
    """
    basket = _basket_whose_version_has_moved_on(api)
    account_id = basket["account_id"]
    fresh_version = fixtures.read_order(api, account_id, basket["order_id"])["version"]
    assert fresh_version == basket["stale_version"] + 1

    booking = read_object(
        api.create_slot_booking(
            factories.slot_booking_payload(
                basket["slot_id"], basket["order_id"], fresh_version, units=3
            ),
            make_customer_headers(account_id),
        ),
        201,
    )
    assert_status(booking, BookingStatus.HELD.value)
    assert_int_field(booking, "units", 3)

    assert_slot_ledger(
        fixtures.read_delivery_slot(api, basket["slot_id"]),
        total_capacity_units=10,
        withheld_units=0,
        held_units=3,
        confirmed_units=0,
        available_units=7,
    )
    order = fixtures.read_order(api, account_id, basket["order_id"])
    assert_order_money(
        order,
        merchandise_subtotal_cents=2100,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=2699,
    )
    _items, meta = list_items_and_meta(
        api.list_slot_bookings(
            admin_headers, params={"customer_order_id": basket["order_id"]}
        )
    )
    assert meta["total_count"] == 1


def _short_line_whose_substitute_lives_in_another_zone(api):
    """A short ambient line whose only comparable substitute is stored elsewhere.

    The ordered goods sit in one grid zone and the interchangeable substitute in a
    second, so the two zones' service status can be moved independently. A third
    article in the substitute's zone belongs to no substitution family and exists
    only to be miscounted.
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    ordered_zone = fixtures.create_grid_zone(api, temperature_zone=AMBIENT)
    substitute_zone = fixtures.create_grid_zone(api, temperature_zone=AMBIENT)
    fixtures.create_pick_station(
        api, temperature_zone_capability=[AMBIENT], max_concurrent_totes=4
    )
    ordered = fixtures.create_inventory_sku(
        api,
        ordered_zone["id"],
        substitution_group_code="PASTA",
        unit_price_cents=700,
        physical_units=100,
    )
    substitute = fixtures.create_inventory_sku(
        api,
        substitute_zone["id"],
        substitution_group_code="PASTA",
        unit_price_cents=750,
        physical_units=100,
    )
    unrelated = fixtures.create_inventory_sku(
        api,
        substitute_zone["id"],
        substitution_group_code="CEREAL",
        unit_price_cents=400,
        physical_units=100,
    )
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)
    short = fixtures.build_short_line(
        api, route["id"], slot["id"], [ordered["id"]], ordered_qty=2, picked_units=1, units=2
    )
    proposal = fixtures.proposal_for_line(api, short["line"]["id"])
    assert proposal["substitute_sku_id"] == substitute["id"]
    proposal = fixtures.propose_substitution(api, proposal["id"])
    return {
        "account_id": short["account"]["id"],
        "order_id": short["order"]["id"],
        "line_id": short["line"]["id"],
        "ordered_zone_id": ordered_zone["id"],
        "substitute_zone_id": substitute_zone["id"],
        "substitute_id": substitute["id"],
        "unrelated_id": unrelated["id"],
        "proposal_id": proposal["id"],
    }


def test_approving_a_substitute_is_refused_when_the_substitutes_zone_is_on_audit_hold(
    api, make_customer_headers, pick_operator_headers
):
    """A failed inventory count in the zone that stores the substitute closes that zone to
    the bots, so the shopper's acceptance is refused even though the short line's own zone
    is fully in service.

    Cites the requirement it rests on: "The grid zone holding the SKU being retrieved has status `OPERATIONAL`; a zone in `MAINTENANCE` or in `AUDIT_HOLD` may not be entered by the robotic grid. Violation: `ERR_ZONE_NOT_OPERATIONAL` (409). Applies to three operations: `POST /pick-tasks/{taskId}/start-retrieval`, `POST /delivery-waves/{waveId}/start-picking` and `POST /substitution-proposals/{proposalId}/approve`."

    Design: Corner/validations/substitution_approval_reads_the_substitute_zone_status_not_the_line_state
    """
    floor = _short_line_whose_substitute_lives_in_another_zone(api)
    held_zone = fixtures.record_audit_counts(
        api, floor["substitute_zone_id"], [(floor["unrelated_id"], 90)]
    )
    assert_ratio(held_zone, "accuracy_score_unit_weighted", 0.9000)
    assert_status(held_zone, GridZoneStatus.AUDIT_HOLD.value)
    assert_status(
        fixtures.read_grid_zone(api, floor["ordered_zone_id"]),
        GridZoneStatus.OPERATIONAL.value,
    )

    refusal = api.approve_substitution(
        floor["proposal_id"], make_customer_headers(floor["account_id"])
    )
    validate_error(refusal, ApiError.ZONE_NOT_OPERATIONAL.value)

    assert_status(
        fixtures.read_substitution_proposal(api, floor["proposal_id"]),
        ProposalStatus.PROPOSED.value,
    )
    line = fixtures.read_order_line(api, floor["account_id"], floor["line_id"])
    assert_status(line, LineStatus.SHORT.value, field="line_status")
    assert_status(
        line, SubstitutionResolution.PENDING.value, field="substitution_resolution"
    )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, floor["substitute_id"]),
        physical_units=100,
        allocated_units=0,
        on_hand_units=100,
    )
    _items, meta = list_items_and_meta(
        api.list_pick_tasks(
            pick_operator_headers, params={"order_line_id": floor["line_id"]}
        )
    )
    assert meta["total_count"] == 1, "no retrieval may be raised for a refused substitute"


def test_the_identical_approval_goes_through_once_the_recount_returns_the_zone_to_service(
    api, make_customer_headers, pick_operator_headers
):
    """A clean recount of the miscounted article returns the substitute's zone to service,
    and the very same acceptance then closes the line's cycle back onto its opening status
    and reprices it at the substitute's price.

    Cites the requirement it rests on: "On success the line advances `SHORT → PENDING`, closing the line's cycle back onto its initial status, with `substitution_resolution` moving `PENDING → SUBSTITUTED` and `picked_units` reset to null because the earlier short pick no longer describes the line's outcome."

    Design: Corner/validations/substitution_approval_reads_the_substitute_zone_status_not_the_line_state
    """
    floor = _short_line_whose_substitute_lives_in_another_zone(api)
    fixtures.record_audit_counts(
        api, floor["substitute_zone_id"], [(floor["unrelated_id"], 90)]
    )
    cleared = fixtures.record_audit_counts(
        api, floor["substitute_zone_id"], [(floor["unrelated_id"], 90)]
    )
    assert_ratio(cleared, "accuracy_score_unit_weighted", 1.0000)
    assert_status(cleared, GridZoneStatus.OPERATIONAL.value)

    fixtures.approve_substitution(api, floor["account_id"], floor["proposal_id"])

    line = fixtures.read_order_line(api, floor["account_id"], floor["line_id"])
    assert_status(line, LineStatus.PENDING.value, field="line_status")
    assert_status(
        line, SubstitutionResolution.SUBSTITUTED.value, field="substitution_resolution"
    )
    assert_field_absent_or_null(line, "picked_units")
    assert_money(line, "final_line_price_cents", 1500)

    order = fixtures.read_order(api, floor["account_id"], floor["order_id"])
    assert_order_money(
        order,
        merchandise_subtotal_cents=1500,
        delivery_fee_cents=599,
        order_total_cents=2099,
    )
    assert_int_field(order, "open_substitution_count", 0)
    assert order["dispatch_blocked"] is False

    assert_sku_ledger(
        fixtures.read_inventory_sku(api, floor["substitute_id"]),
        physical_units=100,
        allocated_units=2,
        on_hand_units=98,
    )
    _items, meta = list_items_and_meta(
        api.list_pick_tasks(
            pick_operator_headers, params={"order_line_id": floor["line_id"]}
        )
    )
    assert meta["total_count"] == 2, "the accepted substitute earns its own retrieval"


def _two_waves_competing_for_three_units(api):
    """Three units of one scarce article on the shelf and two waves that want it.

    The morning wave carries two shoppers who each ordered two units; the
    afternoon wave carries a single shopper who ordered two. Each individual
    demand fits inside the three units on hand; only the morning wave's pair
    does not.
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api, temperature_zone=AMBIENT)
    fixtures.create_pick_station(
        api, temperature_zone_capability=[AMBIENT], max_concurrent_totes=6
    )
    scarce = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=700, physical_units=3
    )
    morning_slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=10
    )
    afternoon_slot = fixtures.create_delivery_slot(
        api,
        route["id"],
        total_capacity_units=10,
        window_start="2026-08-05T14:00:00.000Z",
        window_end="2026-08-05T16:00:00.000Z",
    )
    first = fixtures.build_waved_order(
        api, route["id"], morning_slot["id"], [scarce["id"]], ordered_qty=2, units=2
    )
    second = fixtures.build_waved_order(
        api,
        route["id"],
        morning_slot["id"],
        [scarce["id"]],
        ordered_qty=2,
        units=2,
        wave=first["wave"],
    )
    afternoon = fixtures.build_waved_order(
        api, route["id"], afternoon_slot["id"], [scarce["id"]], ordered_qty=2, units=2
    )
    return {
        "scarce_id": scarce["id"],
        "morning_wave_id": first["wave"]["id"],
        "morning_line_ids": [first["lines"][0]["id"], second["lines"][0]["id"]],
        "morning_orders": [
            (first["account"]["id"], first["order"]["id"]),
            (second["account"]["id"], second["order"]["id"]),
        ],
        "afternoon_wave_id": afternoon["wave"]["id"],
        "afternoon_line_id": afternoon["lines"][0]["id"],
        "afternoon_order": (afternoon["account"]["id"], afternoon["order"]["id"]),
    }


def test_two_individually_affordable_lines_cannot_both_be_admitted_from_three_units(
    api, wave_planner_headers, pick_operator_headers
):
    """Releasing a wave to the floor weighs every line of that wave against the uncommitted
    stock at once, so two two-unit demands on three units on hand are refused together and
    the wave stays where it was.

    Cites the requirement it rests on: "The inventory test is taken across all the lines of the wave together, so two lines competing for the same scarce SKU cannot both be admitted."

    Design: Corner/validations/two_individually_satisfiable_lines_exceed_stock_only_in_aggregate
    """
    floor = _two_waves_competing_for_three_units(api)

    refusal = api.start_picking(floor["morning_wave_id"], wave_planner_headers)
    validate_error(refusal, ApiError.INSUFFICIENT_INVENTORY.value)

    assert_status(
        fixtures.read_wave(api, floor["morning_wave_id"]), WaveStatus.FORMING.value
    )
    for account_id, order_id in floor["morning_orders"]:
        assert_order_statuses(
            fixtures.read_order(api, account_id, order_id),
            fulfillment_status=FulfillmentStatus.WAVED.value,
        )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, floor["scarce_id"]),
        physical_units=3,
        allocated_units=0,
        on_hand_units=3,
    )
    _items, meta = list_items_and_meta(
        api.list_pick_tasks(
            pick_operator_headers, params={"delivery_wave_id": floor["morning_wave_id"]}
        )
    )
    assert meta["total_count"] == 0, "a refused release raises no retrieval work"


def test_a_wave_carrying_one_of_those_lines_alone_is_released_and_commits_its_units(
    api, pick_operator_headers
):
    """A single two-unit demand sits comfortably inside the three units on hand, so its wave
    is released and those two units become committed, which is exactly why the refusal of the
    two-line wave can only have come from the aggregate.

    Cites the requirement it rests on: "The SKU has enough uncommitted stock: its `on_hand_units` is at least the number of units the request would allocate, summed across all lines of the wave when a wave starts picking. Violation: `ERR_INSUFFICIENT_INVENTORY` (409)."

    Design: Corner/validations/two_individually_satisfiable_lines_exceed_stock_only_in_aggregate
    """
    floor = _two_waves_competing_for_three_units(api)

    wave = fixtures.start_picking(api, floor["afternoon_wave_id"])
    assert_status(wave, WaveStatus.PICKING.value)

    account_id, order_id = floor["afternoon_order"]
    assert_order_statuses(
        fixtures.read_order(api, account_id, order_id),
        fulfillment_status=FulfillmentStatus.PICKING.value,
    )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, floor["scarce_id"]),
        physical_units=3,
        allocated_units=2,
        on_hand_units=1,
    )

    task = fixtures.pick_task_for_line(api, floor["afternoon_line_id"])
    assert_status(task, PickTaskStatus.QUEUED.value)
    assert_int_field(task, "allocated_units", 2)
    for line_id in floor["morning_line_ids"]:
        _items, meta = list_items_and_meta(
            api.list_pick_tasks(pick_operator_headers, params={"order_line_id": line_id})
        )
        assert meta["total_count"] == 0, "an unreleased wave has no retrieval work"


def _wave_carrying_one_flat_line_and_one_weighed_line(api):
    """One basket holding an article sold by the unit and one sold by weight.

    Both lines are two units and both retrievals are already under way with the
    bots, so the two completions differ in nothing except whether the article is
    weighed.
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api, temperature_zone=AMBIENT)
    fixtures.create_pick_station(
        api, temperature_zone_capability=[AMBIENT], max_concurrent_totes=6
    )
    flat = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=700, physical_units=100
    )
    weighed = fixtures.create_catchweight_sku(
        api,
        zone["id"],
        price_per_kg_cents=1200,
        nominal_weight_grams=500,
        weight_tolerance_pct=0.05,
        physical_units=100,
    )
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)
    picking = fixtures.build_picking_wave(
        api, route["id"], slot["id"], [flat["id"], weighed["id"]], ordered_qty=2, units=4
    )
    flat_line, weighed_line = picking["lines"]
    tote = None
    tasks = {}
    for label, line in (("flat", flat_line), ("weighed", weighed_line)):
        task = fixtures.pick_task_for_line(api, line["id"])
        driven = fixtures.drive_task_to_retrieving(
            api,
            task["id"],
            picking["wave"]["id"],
            task["pick_station_id"],
            AMBIENT,
            tote=tote,
        )
        tote = driven["tote"]
        tasks[label] = driven["task"]
    return {
        "account_id": picking["account"]["id"],
        "order_id": picking["order"]["id"],
        "flat_line_id": flat_line["id"],
        "weighed_line_id": weighed_line["id"],
        "flat_task_id": tasks["flat"]["id"],
        "weighed_task_id": tasks["weighed"]["id"],
        "flat_sku_id": flat["id"],
        "weighed_sku_id": weighed["id"],
    }


def test_a_measured_weight_on_an_article_sold_by_the_unit_is_not_even_accepted(
    api, pick_operator_headers
):
    """An article sold by the unit carries no tolerance band at all, so reporting a measured
    weight on its retrieval is rejected as a body the operation does not take rather than
    being weighed against anything, and the same retrieval closes cleanly once the weight is
    left off.

    Cites the requirement it rests on: "The `PickOperator` reports `picked_units`, the number of units actually retrieved, which must be at least 0 and at most the task's `allocated_units`; and for a catchweight SKU also `actual_weight_grams`, the measured total weight in grams, which is required for a catchweight SKU and must be omitted for any other."

    Design: Corner/validations/weight_tolerance_is_checked_only_when_the_sku_is_catchweight
    """
    floor = _wave_carrying_one_flat_line_and_one_weighed_line(api)

    weighed_by_mistake = api.complete_pick_task(
        floor["flat_task_id"],
        factories.complete_pick_task_payload(2, actual_weight_grams=1200),
        pick_operator_headers,
    )
    validate_error(weighed_by_mistake, ApiError.INVALID_REQUEST.value)
    assert_status(
        fixtures.read_pick_task(api, floor["flat_task_id"]),
        PickTaskStatus.RETRIEVING.value,
    )

    task = fixtures.complete_pick_task(api, floor["flat_task_id"], 2)
    assert_status(task, PickTaskStatus.COMPLETED.value)
    assert_field_absent_or_null(task, "actual_weight_grams")

    line = fixtures.read_order_line(api, floor["account_id"], floor["flat_line_id"])
    assert_status(line, LineStatus.PICKED.value, field="line_status")
    assert_int_field(line, "picked_units", 2)
    assert_money(line, "final_line_price_cents", 1400)
    assert_field_absent_or_null(line, "nominal_weight_grams")
    assert_field_absent_or_null(line, "picked_weight_grams")
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, floor["flat_sku_id"]),
        physical_units=98,
        allocated_units=0,
        on_hand_units=98,
    )


def test_a_weighed_article_is_refused_outside_its_tolerance_band_and_priced_inside_it(
    api, pick_operator_headers
):
    """The measured total weight of a weighed article is reconciled against the band its line
    snapshotted, so a fifth over the declared weight is refused before any price is written
    while the declared weight itself closes the retrieval and prices it by the kilogram.

    Cites the requirement it rests on: "For a catchweight SKU, the deviation ratio between the measured and the nominal total weight does not exceed the SKU's `weight_tolerance_pct`; a ratio exactly equal to the tolerance is accepted and only a strictly greater ratio is rejected. Violation: `ERR_WEIGHT_OUT_OF_TOLERANCE` (422). Applies to `POST /pick-tasks/{taskId}/complete`."

    Design: Corner/validations/weight_tolerance_is_checked_only_when_the_sku_is_catchweight
    """
    floor = _wave_carrying_one_flat_line_and_one_weighed_line(api)
    line = fixtures.read_order_line(api, floor["account_id"], floor["weighed_line_id"])
    assert_int_field(line, "nominal_weight_grams", 500)
    assert_money(line, "provisional_line_price_cents", 1200)

    out_of_band = api.complete_pick_task(
        floor["weighed_task_id"],
        factories.complete_pick_task_payload(2, actual_weight_grams=1200),
        pick_operator_headers,
    )
    validate_error(out_of_band, ApiError.WEIGHT_OUT_OF_TOLERANCE.value)
    assert_status(
        fixtures.read_pick_task(api, floor["weighed_task_id"]),
        PickTaskStatus.RETRIEVING.value,
    )
    line = fixtures.read_order_line(api, floor["account_id"], floor["weighed_line_id"])
    assert_status(line, LineStatus.PENDING.value, field="line_status")
    assert_field_absent_or_null(line, "final_line_price_cents")

    task = fixtures.complete_pick_task(
        api, floor["weighed_task_id"], 2, actual_weight_grams=1000
    )
    assert_status(task, PickTaskStatus.COMPLETED.value)
    assert_int_field(task, "actual_weight_grams", 1000)

    line = fixtures.read_order_line(api, floor["account_id"], floor["weighed_line_id"])
    assert_status(line, LineStatus.PICKED.value, field="line_status")
    assert_int_field(line, "picked_weight_grams", 1000)
    assert_money(line, "final_line_price_cents", 1200)
    assert_order_money(
        fixtures.read_order(api, floor["account_id"], floor["order_id"]),
        merchandise_subtotal_cents=2600,
        delivery_fee_cents=599,
        order_total_cents=3199,
    )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, floor["weighed_sku_id"]),
        physical_units=98,
        allocated_units=0,
        on_hand_units=98,
    )
