"""Version guards, the substitute selector and the settled-in-one-round promise.

Two writes in the fulfillment centre can quietly overwrite a decision the client
never saw, so both of them make the client carry the version it last read: a
shopper booking delivery capacity must present the basket's `version`, and a pick
operator opening a fresh substitution round must present the short line's
`version`, and a view that has since moved on is turned away at 412 with nothing
created and no capacity touched. When a short pick does need a substitute, the
selector filters the catalogue before it ranks it — an item the grid cannot
actually give up, because there is not enough of it on hand or because its zone
is sitting in an accuracy hold, never reaches the ranking at all, however close
its price sits to the ordered item — and only then does price distance, and the
cheaper of two equidistant items, decide the offer. Everything those requests
move is already settled when they answer: the booking body carries its own frozen
surge and quoted fee, the slot's ledger and recomputed multiplier are readable
with no second write, the basket's charge waterfall is filled in, and the wave's
order count and posture arrive in the body of the request that slotted the order
rather than on a later read.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_delivery_wave_shape,
    assert_field_absent_or_null,
    assert_int_field,
    assert_money,
    assert_order_money,
    assert_order_statuses,
    assert_ratio,
    assert_sku_ledger,
    assert_slot_booking_shape,
    assert_slot_ledger,
    assert_status,
    assert_substitution_proposal_shape,
    assert_surge_multiplier,
    assert_version_is,
    assert_wave_posture,
    list_items_and_meta,
    read_object,
)
from test_helpers.types import (
    BillingStatus,
    BookingStatus,
    FulfillmentStatus,
    GridZoneStatus,
    LineStatus,
    PickTaskStatus,
    ProposalStatus,
    SubstitutionResolution,
    WavePosture,
    WaveStatus,
)


def _basket_ready_to_book(api):
    """A shopper on a ten-unit slot with one two-unit line of a 700-cent item."""
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api)
    sku = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=10, withheld_units=0
    )
    basket = fixtures.build_shopper_with_basket(
        api, route["id"], [sku["id"]], ordered_qty=2
    )
    return {
        "route": route,
        "sku": sku,
        "slot": slot,
        "account": basket["account"],
        "order": basket["order"],
    }


def test_booking_on_a_basket_version_read_before_a_second_line_is_refused(
    api, make_customer_headers
):
    """A shopper who priced their basket before adding another item may not book on that view.

    Cites the requirement it rests on: "If `expected_order_version` does not equal
    that order's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412) and no booking is created."

    Design: Corner/complexity_layers/occ_booking_rejects_an_order_version_captured_before_a_second_line_was_added
    """
    ready = _basket_ready_to_book(api)
    account_id = ready["account"]["id"]
    order_id = ready["order"]["id"]
    shopper = make_customer_headers(account_id)

    observed_version = fixtures.read_order(api, account_id, order_id)["version"]
    fixtures.add_order_line(
        api, account_id, order_id, ready["sku"]["id"], ordered_qty=1
    )

    refused = api.create_slot_booking(
        factories.slot_booking_payload(
            ready["slot"]["id"], order_id, observed_version, units=3
        ),
        shopper,
    )
    validate_error(refused, ApiError.STALE_VERSION.value)

    order_now = fixtures.read_order(api, account_id, order_id)
    assert_version_is(order_now, observed_version + 1)
    assert_order_statuses(
        order_now,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )

    slot_now = fixtures.read_delivery_slot(api, ready["slot"]["id"])
    assert_slot_ledger(
        slot_now,
        total_capacity_units=10,
        withheld_units=0,
        held_units=0,
        confirmed_units=0,
        available_units=10,
    )

    bookings, meta = list_items_and_meta(
        api.list_slot_bookings(shopper, params={"customer_order_id": order_id})
    )
    assert meta["total_count"] == 0, "the refused booking must not have been created"
    assert bookings == [], f"no booking should exist for the basket, got {bookings}"


def test_rebooking_on_the_refreshed_basket_version_holds_capacity_and_prices_the_order(
    api, make_customer_headers
):
    """Re-reading the basket after the refusal yields the one version that lets the same booking through.

    Cites the requirement it rests on: "If `available_units` is greater than or
    equal to `units`, the booking is created in status `HELD` and it occupies that
    capacity: the slot's `held_units`, `confirmed_units` and `available_units` are
    recomputed by the ledger, the slot's `surge_multiplier` is recomputed, the
    charge waterfall runs on the order so that `delivery_fee_cents`,
    `loyalty_discount_cents` and `order_total_cents` become non-null, and the
    order's `version` is incremented by 1."

    Design: Corner/complexity_layers/occ_booking_rejects_an_order_version_captured_before_a_second_line_was_added
    """
    ready = _basket_ready_to_book(api)
    account_id = ready["account"]["id"]
    order_id = ready["order"]["id"]
    slot_id = ready["slot"]["id"]
    shopper = make_customer_headers(account_id)

    observed_version = fixtures.read_order(api, account_id, order_id)["version"]
    fixtures.add_order_line(
        api, account_id, order_id, ready["sku"]["id"], ordered_qty=1
    )
    validate_error(
        api.create_slot_booking(
            factories.slot_booking_payload(slot_id, order_id, observed_version, units=3),
            shopper,
        ),
        ApiError.STALE_VERSION.value,
    )

    refreshed_version = fixtures.read_order(api, account_id, order_id)["version"]
    assert refreshed_version == observed_version + 1, (
        "only the line creation should have moved the basket's version"
    )

    booking = read_object(
        api.create_slot_booking(
            factories.slot_booking_payload(
                slot_id, order_id, refreshed_version, units=3
            ),
            shopper,
        ),
        expected_status=201,
    )
    assert_slot_booking_shape(booking)
    assert_status(booking, BookingStatus.HELD.value)
    assert_int_field(booking, "units", 3)
    assert_ratio(booking, "surge_multiplier_at_booking", 1.00, places=2)
    assert_money(booking, "quoted_fee_cents", 599)

    slot_now = fixtures.read_delivery_slot(api, slot_id)
    assert_slot_ledger(
        slot_now,
        total_capacity_units=10,
        withheld_units=0,
        held_units=3,
        confirmed_units=0,
        available_units=7,
    )

    order_now = fixtures.read_order(api, account_id, order_id)
    assert_order_money(
        order_now,
        merchandise_subtotal_cents=2100,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=2699,
    )
    assert_version_is(order_now, refreshed_version + 1)


def _short_line_after_a_declined_first_round(api):
    """A short line whose first substitution round was offered and then refused.

    The two comparable substitutes are registered only after the short pick, so
    the pick itself found no candidate and opened no round of its own.
    """
    plant = fixtures.build_plant(api)
    group_code = f"DRY-{factories.unique_suffix()}"
    ordered_sku = fixtures.create_inventory_sku(
        api,
        plant["zone"]["id"],
        substitution_group_code=group_code,
        unit_price_cents=700,
        physical_units=100,
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=10
    )
    short = fixtures.build_short_line(
        api,
        plant["route"]["id"],
        slot["id"],
        [ordered_sku["id"]],
        ordered_qty=2,
        picked_units=1,
    )
    substitutes = fixtures.build_substitution_group(
        api, plant["zone"]["id"], group_code, [750, 800], physical_units=100
    )
    account_id = short["account"]["id"]
    line_id = short["line"]["id"]

    first_round_version = fixtures.read_order_line(api, account_id, line_id)["version"]
    first_round = fixtures.create_substitution_proposal(
        api, line_id, substitutes[0]["id"], first_round_version
    )
    fixtures.propose_substitution(api, first_round["id"])
    fixtures.decline_substitution(api, account_id, first_round["id"])
    return {
        "account_id": account_id,
        "order_id": short["order"]["id"],
        "line_id": line_id,
        "ordered_sku": ordered_sku,
        "declined_substitute": substitutes[0],
        "next_substitute": substitutes[1],
        "first_round": first_round,
        "line_version_before_first_round": first_round_version,
    }


def test_second_substitution_round_on_the_first_round_line_version_is_refused(
    api, pick_operator_headers
):
    """An operator replaying the view the first round was opened from may not open the second.

    Cites the requirement it rests on: "If `expected_order_line_version` does not
    equal that line's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412) and no proposal is created."

    Design: Corner/complexity_layers/occ_proposal_rejects_an_order_line_version_captured_before_the_previous_round
    """
    situation = _short_line_after_a_declined_first_round(api)
    line_id = situation["line_id"]
    stale_line_version = situation["line_version_before_first_round"]

    refused = api.create_substitution_proposal(
        factories.substitution_proposal_payload(
            line_id,
            situation["next_substitute"]["id"],
            stale_line_version,
            supersedes_proposal_id=situation["first_round"]["id"],
        ),
        pick_operator_headers,
    )
    validate_error(refused, ApiError.STALE_VERSION.value)

    proposals, meta = list_items_and_meta(
        api.list_substitution_proposals(
            pick_operator_headers, params={"order_line_id": line_id}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the declined first round should exist, got {meta['total_count']}"
    )
    assert_status(proposals[0], ProposalStatus.DECLINED.value)

    line_now = fixtures.read_order_line(api, situation["account_id"], line_id)
    assert_version_is(line_now, stale_line_version + 1)
    assert_status(line_now, LineStatus.SHORT.value, field="line_status")
    assert_status(
        line_now,
        SubstitutionResolution.PENDING.value,
        field="substitution_resolution",
    )


def test_second_substitution_round_opens_once_the_line_version_is_re_read(
    api, pick_operator_headers
):
    """With the line's current version in hand the operator opens round two over the declined round one.

    Cites the requirement it rests on: "Its `proposed_price_delta_cents` is the
    substitute SKU's `unit_price_cents` multiplied by the line's `ordered_qty`,
    less the line's `provisional_line_price_cents`; it is an exact integer
    difference and may well be negative when the substitute is cheaper."

    Design: Corner/complexity_layers/occ_proposal_rejects_an_order_line_version_captured_before_the_previous_round
    """
    situation = _short_line_after_a_declined_first_round(api)
    line_id = situation["line_id"]
    account_id = situation["account_id"]
    first_round = situation["first_round"]

    validate_error(
        api.create_substitution_proposal(
            factories.substitution_proposal_payload(
                line_id,
                situation["next_substitute"]["id"],
                situation["line_version_before_first_round"],
                supersedes_proposal_id=first_round["id"],
            ),
            pick_operator_headers,
        ),
        ApiError.STALE_VERSION.value,
    )

    current_line_version = fixtures.read_order_line(api, account_id, line_id)["version"]
    second_round = read_object(
        api.create_substitution_proposal(
            factories.substitution_proposal_payload(
                line_id,
                situation["next_substitute"]["id"],
                current_line_version,
                supersedes_proposal_id=first_round["id"],
            ),
            pick_operator_headers,
        ),
        expected_status=201,
    )
    assert_substitution_proposal_shape(second_round)
    assert_status(second_round, ProposalStatus.DRAFT.value)
    assert_int_field(second_round, "round_no", 2)
    assert second_round["supersedes_proposal_id"] == first_round["id"], (
        "round two must name the declined round it replaces"
    )
    assert_money(second_round, "proposed_price_delta_cents", 200)
    assert_field_absent_or_null(second_round, "expires_at")

    retired = fixtures.read_substitution_proposal(api, first_round["id"])
    assert_status(retired, ProposalStatus.DECLINED.value)
    assert_int_field(retired, "round_no", 1)

    line_now = fixtures.read_order_line(api, account_id, line_id)
    assert_status(line_now, LineStatus.SHORT.value, field="line_status")
    assert_status(
        line_now,
        SubstitutionResolution.PENDING.value,
        field="substitution_resolution",
    )

    order_now = fixtures.read_order(api, account_id, situation["order_id"])
    assert_int_field(order_now, "open_substitution_count", 1)
    assert order_now["dispatch_blocked"] is True, (
        "a line still awaiting a substitution decision keeps the order blocked"
    )


def _short_line_with_four_comparable_candidates(api):
    """A short pick surrounded by four same-group candidates, two of them unusable.

    The ordered item costs 700 cents.  Two survivors sit symmetrically at 650 and
    750; the two that would otherwise win on price distance are a thin item with a
    single unit on hand and an item stored in a zone an audit has just put on hold.
    """
    plant = fixtures.build_plant(api)
    ambient_zone = plant["zone"]
    held_zone = fixtures.create_grid_zone(api)
    group_code = f"DRY-{factories.unique_suffix()}"

    def _candidate(zone_id, price, units):
        return fixtures.create_inventory_sku(
            api,
            zone_id,
            substitution_group_code=group_code,
            unit_price_cents=price,
            physical_units=units,
        )

    ordered_sku = _candidate(ambient_zone["id"], 700, 100)
    dearer_sku = _candidate(ambient_zone["id"], 750, 100)
    cheaper_sku = _candidate(ambient_zone["id"], 650, 100)
    thin_sku = _candidate(ambient_zone["id"], 700, 1)
    held_zone_sku = _candidate(held_zone["id"], 700, 100)

    fixtures.record_audit_counts(api, held_zone["id"], [(held_zone_sku["id"], 90)])

    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=10
    )
    short = fixtures.build_short_line(
        api,
        plant["route"]["id"],
        slot["id"],
        [ordered_sku["id"]],
        ordered_qty=2,
        picked_units=1,
    )
    return {
        "ambient_zone": ambient_zone,
        "held_zone": held_zone,
        "ordered_sku": ordered_sku,
        "dearer_sku": dearer_sku,
        "cheaper_sku": cheaper_sku,
        "thin_sku": thin_sku,
        "held_zone_sku": held_zone_sku,
        "short": short,
    }


def test_symmetric_price_tie_is_broken_by_the_cheaper_substitute(
    api, pick_operator_headers
):
    """Two substitutes equally far from the ordered price are separated by the cheaper one winning.

    Cites the requirement it rests on: "Candidates are ranked by how close their
    price is to the ordered item: first by the absolute difference between the
    candidate's `unit_price_cents` and the ordered SKU's `unit_price_cents`,
    ascending; then, among equally distant candidates, by the candidate's own
    `unit_price_cents` ascending, so the cheaper of two equidistant items wins;
    then by `sku_code` ascending; and finally, when all three rank keys tie, by
    `created_at` ascending."

    Design: Corner/complexity_layers/selector_policy_filters_before_it_ranks_and_breaks_a_symmetric_price_tie_by_the_cheaper_sku
    """
    scene = _short_line_with_four_comparable_candidates(api)
    short = scene["short"]
    line_id = short["line"]["id"]

    task = fixtures.read_pick_task(api, short["task"]["id"])
    assert_status(task, PickTaskStatus.SHORT.value)
    assert_int_field(task, "picked_units", 1)

    proposals, meta = list_items_and_meta(
        api.list_substitution_proposals(
            pick_operator_headers, params={"order_line_id": line_id}
        )
    )
    assert meta["total_count"] == 1, (
        f"the short pick should have opened exactly one offer, got {meta['total_count']}"
    )
    offer = proposals[0]
    assert_substitution_proposal_shape(offer)
    assert offer["substitute_sku_id"] == scene["cheaper_sku"]["id"], (
        "the 650-cent item must win the tie against the 750-cent item"
    )
    assert_status(offer, ProposalStatus.DRAFT.value)
    assert_int_field(offer, "round_no", 1)
    assert_field_absent_or_null(offer, "expires_at")
    assert_money(offer, "proposed_price_delta_cents", -100)


def test_ineligible_substitutes_are_dropped_before_the_price_ranking_runs(
    api, pick_operator_headers
):
    """A thin item and an item in a held zone never reach the ranking, though their price is exact.

    Cites the requirement it rests on: "The **substitute selector** starts from the
    SKU originally ordered on the line and considers every other catalogue SKU that
    is not that SKU itself, shares its `temperature_zone`, carries the same
    `substitution_group_code`, is stored in a grid zone whose status is
    `OPERATIONAL`, and has an `on_hand_units` of at least the line's
    `ordered_qty`."

    Design: Corner/complexity_layers/selector_policy_filters_before_it_ranks_and_breaks_a_symmetric_price_tie_by_the_cheaper_sku
    """
    scene = _short_line_with_four_comparable_candidates(api)
    short = scene["short"]

    offer = fixtures.proposal_for_line(api, short["line"]["id"])
    assert offer["substitute_sku_id"] != scene["thin_sku"]["id"], (
        "an item with one unit on hand cannot cover a two-unit line"
    )
    assert offer["substitute_sku_id"] != scene["held_zone_sku"]["id"], (
        "an item stored in a zone on audit hold is not reachable by the grid"
    )
    assert offer["substitute_sku_id"] == scene["cheaper_sku"]["id"]

    thin_now = fixtures.read_inventory_sku(api, scene["thin_sku"]["id"])
    assert_sku_ledger(thin_now, physical_units=1, allocated_units=0, on_hand_units=1)

    held_zone_now = fixtures.read_grid_zone(api, scene["held_zone"]["id"])
    assert_status(held_zone_now, GridZoneStatus.AUDIT_HOLD.value)
    picking_zone_now = fixtures.read_grid_zone(api, scene["ambient_zone"]["id"])
    assert_status(picking_zone_now, GridZoneStatus.OPERATIONAL.value)

    chosen_now = fixtures.read_inventory_sku(api, scene["cheaper_sku"]["id"])
    assert_sku_ledger(
        chosen_now, physical_units=100, allocated_units=0, on_hand_units=100
    )

    wave_now = fixtures.read_wave(api, short["wave"]["id"])
    assert_wave_posture(wave_now, WavePosture.RESTRICTED.value)
    assert_status(wave_now, WaveStatus.PICKING.value)


def _basket_on_a_short_notice_slot(api):
    """A five-unit slot opening eight hours out, with a four-unit basket ready for it."""
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api)
    sku = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api,
        route["id"],
        window_start="2026-08-01T08:00:00.000Z",
        window_end="2026-08-01T10:00:00.000Z",
        total_capacity_units=5,
        withheld_units=0,
    )
    basket = fixtures.build_shopper_with_basket(
        api, route["id"], [sku["id"]], ordered_qty=4
    )
    return {
        "route": route,
        "sku": sku,
        "slot": slot,
        "account": basket["account"],
        "order": basket["order"],
    }


def test_one_booking_settles_the_slot_ledger_its_surge_and_the_charge_waterfall_at_once(
    api, make_customer_headers
):
    """Reserving capacity leaves nothing to poll for: the quote, the ledger and the totals are all settled.

    Cites the requirement it rests on: "Both branches capture the price context
    identically: `surge_multiplier_at_booking` is set to the slot's
    `surge_multiplier` as it stands at that instant and is frozen thereafter, and
    `quoted_fee_cents` is the route's `base_delivery_fee_cents` multiplied by that
    frozen multiplier, rounded half up to whole cents."

    Design: Corner/consistency_model/immediate_consistency_shows_every_derived_change_in_the_same_response
    """
    ready = _basket_on_a_short_notice_slot(api)
    account_id = ready["account"]["id"]
    order_id = ready["order"]["id"]
    slot_id = ready["slot"]["id"]
    shopper = make_customer_headers(account_id)

    assert_surge_multiplier(ready["slot"], 1.20)

    order_version = fixtures.read_order(api, account_id, order_id)["version"]
    booking = read_object(
        api.create_slot_booking(
            factories.slot_booking_payload(slot_id, order_id, order_version, units=4),
            shopper,
        ),
        expected_status=201,
    )
    assert_slot_booking_shape(booking)
    assert_status(booking, BookingStatus.HELD.value)
    assert_ratio(booking, "surge_multiplier_at_booking", 1.20, places=2)
    assert_money(booking, "quoted_fee_cents", 719)

    slot_now = fixtures.read_delivery_slot(api, slot_id)
    assert_slot_ledger(
        slot_now,
        total_capacity_units=5,
        withheld_units=0,
        held_units=4,
        confirmed_units=0,
        available_units=1,
    )
    assert_surge_multiplier(slot_now, 1.35)

    order_now = fixtures.read_order(api, account_id, order_id)
    assert_order_money(
        order_now,
        merchandise_subtotal_cents=2800,
        delivery_fee_cents=719,
        loyalty_discount_cents=0,
        order_total_cents=3519,
    )
    assert_order_statuses(
        order_now,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )


def test_confirming_and_slotting_carry_their_derived_figures_in_their_own_bodies(
    api, make_customer_headers, wave_planner_headers
):
    """The confirmation and the slotting each answer with the counts and postures they just moved.

    Cites the requirement it rests on: "On success the order's `wave_id` is set to
    the wave, the order advances `SLOTTED → WAVED`, the wave's `order_count` is
    recomputed, the wave's `posture` is recomputed, and the order's `version` is
    incremented by 1."

    Design: Corner/consistency_model/immediate_consistency_shows_every_derived_change_in_the_same_response
    """
    ready = _basket_on_a_short_notice_slot(api)
    account_id = ready["account"]["id"]
    order_id = ready["order"]["id"]
    slot_id = ready["slot"]["id"]
    shopper = make_customer_headers(account_id)

    booking = fixtures.create_slot_booking(api, account_id, slot_id, order_id, units=4)
    confirmed = read_object(api.confirm_slot_booking(booking["id"], shopper))
    assert_status(confirmed, BookingStatus.CONFIRMED.value)

    slotted_order = fixtures.read_order(api, account_id, order_id)
    assert_order_statuses(
        slotted_order,
        fulfillment_status=FulfillmentStatus.SLOTTED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )
    assert_order_money(
        slotted_order, order_total_cents=3519, authorized_amount_cents=3519
    )

    wave = fixtures.create_delivery_wave(
        api, ready["route"]["id"], slot_id, cutoff_at="2026-08-01T06:00:00.000Z"
    )
    slotting_body = read_object(
        api.slot_orders(
            wave["id"], factories.slot_orders_payload(order_id), wave_planner_headers
        )
    )
    assert_delivery_wave_shape(slotting_body)
    assert_int_field(slotting_body, "order_count", 1)
    assert_wave_posture(slotting_body, WavePosture.OPEN.value)
    assert_status(slotting_body, WaveStatus.FORMING.value)

    waved_order = fixtures.read_order(api, account_id, order_id)
    assert_order_statuses(
        waved_order, fulfillment_status=FulfillmentStatus.WAVED.value
    )
    assert waved_order["wave_id"] == wave["id"], "the order must name the wave it joined"

    booking_now = fixtures.read_slot_booking(api, booking["id"])
    assert_ratio(booking_now, "surge_multiplier_at_booking", 1.20, places=2)
    assert_money(booking_now, "quoted_fee_cents", 719)
    slot_now = fixtures.read_delivery_slot(api, slot_id)
    assert float(slot_now["surge_multiplier"]) > 1.20, (
        "the slot's live multiplier has moved on while the booked quote stays frozen"
    )
