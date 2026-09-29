"""Money and measurement variants across the fulfillment centre.

A weighed grocery line is priced twice from the very same basket entry: the
provisional price is struck at the till the moment the shopper drops the item
into the basket, reading the catalogue's declared per-unit weight, while the
final price is struck on the picking floor when the bots come back with the
joint actually on the scale, reading the measured weight instead — so an
identical order can cost a different amount once it has been picked, which is
precisely what drives the order's money dimension from authorised to adjusted.
A grid zone's counting accuracy is likewise scored twice from one audit: the
unit-weighted score pools every variance across every counted unit and divides
once, so one enormous accurate pallet can mask a tiny badly miscounted jar,
while the SKU-weighted score divides per SKU first and then averages, giving the
jar and the pallet equal say; only the unit-weighted figure is allowed to put
the zone on an audit hold. The van's transport cost is accumulated stop by stop,
each stop's kilometre charge rounded to whole cents before the stops are added,
because summing the raw kilometre products and rounding once at the end quietly
loses a cent whenever two drops land on a half-cent boundary. And the charge
waterfall runs in a pinned order — subtotal, then delivery fee with its free
delivery waiver read off the subtotal alone, then the loyalty discount keyed on
a pre-discount figure that already contains that fee, then the total — so the
shopper's tier can be reached by the delivery fee that the waiver decided to
charge.
"""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_int_field,
    assert_load_sequence,
    assert_money,
    assert_order_money,
    assert_order_statuses,
    assert_ratio,
    assert_sku_ledger,
    assert_slot_ledger,
    assert_status,
)
from test_helpers.constants import ACCURACY_HOLD_THRESHOLD, DEFAULT_CLOCK_UTC
from test_helpers.types import (
    BillingStatus,
    BookingStatus,
    FulfillmentStatus,
    GridZoneStatus,
    LineStatus,
    LoyaltyTier,
    TemperatureZone,
    ToteStatus,
    WavePosture,
    WaveStatus,
)

LOAD_START = "2026-08-05T08:00:00.000Z"
LOAD_END = "2026-08-05T09:00:00.000Z"


def test_a_weighed_basket_line_is_priced_from_the_declared_nominal_weight(api):
    """A weighed line's provisional price reads the catalogue's declared weight.

    Cites the requirement it rests on: "For a catchweight item, the service first forms the nominal total weight by multiplying the SKU's `nominal_weight_grams` by the line's `ordered_qty`, then multiplies the SKU's `price_per_kg_cents` by that nominal total weight, divides the product by 1,000 — the number of grams in a kilogram — and rounds the result half up to whole cents."

    Design: Difficulty/dual_variant_calc/catchweight_line_price_provisional_vs_final
    """
    plant = fixtures.build_plant(
        api, route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 150}
    )
    beef = fixtures.create_catchweight_sku(
        api,
        plant["zone"]["id"],
        unit_price_cents=625,
        price_per_kg_cents=1250,
        nominal_weight_grams=500,
        weight_tolerance_pct=0.05,
        physical_units=100,
    )

    basket = fixtures.build_shopper_with_basket(
        api, plant["route"]["id"], [beef["id"]], ordered_qty=2, stop_distance_km=2.03
    )
    line = basket["lines"][0]

    # 1250 cents per kg over a declared 500 g x 2 units = 1000 g.
    assert_money(line, "provisional_line_price_cents", 1250)
    assert_field_absent_or_null(line, "final_line_price_cents")
    assert_int_field(line, "nominal_weight_grams", 500)
    assert_status(line, LineStatus.PENDING.value, field="line_status")
    assert_field_absent_or_null(line, "picked_units")
    assert_field_absent_or_null(line, "picked_weight_grams")

    order = fixtures.read_order(api, basket["account"]["id"], basket["order"]["id"])
    assert_order_money(order, merchandise_subtotal_cents=1250)
    assert_field_absent_or_null(order, "delivery_fee_cents")
    assert_field_absent_or_null(order, "loyalty_discount_cents")
    assert_field_absent_or_null(order, "order_total_cents")


def test_the_final_price_of_a_weighed_line_reads_the_weight_on_the_scale(api):
    """Completing the retrieval reprices the weighed line from the measured weight.

    Cites the requirement it rests on: "For a catchweight item it is the SKU's `price_per_kg_cents` multiplied by the measured total weight in grams, divided by 1,000, rounded half up to whole cents — the same shape as the provisional variant but reading the *measured* weight instead of the declared one."

    Design: Difficulty/dual_variant_calc/catchweight_line_price_provisional_vs_final
    """
    plant = fixtures.build_plant(
        api, route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 150}
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    beef = fixtures.create_catchweight_sku(
        api,
        plant["zone"]["id"],
        unit_price_cents=625,
        price_per_kg_cents=1250,
        nominal_weight_grams=500,
        weight_tolerance_pct=0.05,
        physical_units=100,
    )
    confirmed = fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [beef["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.BASIC.value,
        stop_distance_km=2.03,
    )
    # The declared weight priced the basket at 1250 + a 599 fee when authorised.
    assert_order_money(confirmed["order"], authorized_amount_cents=1849)

    wave = fixtures.create_delivery_wave(api, plant["route"]["id"], slot["id"])
    fixtures.slot_order_into_wave(api, wave["id"], confirmed["order"]["id"])
    fixtures.start_picking(api, wave["id"])
    task = fixtures.pick_task_for_line(api, confirmed["lines"][0]["id"])
    fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        wave["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )

    fixtures.complete_pick_task(api, task["id"], 2, actual_weight_grams=1040)

    line = fixtures.read_order_line(
        api, confirmed["account"]["id"], confirmed["lines"][0]["id"]
    )
    assert_money(line, "provisional_line_price_cents", 1250)
    # 1250 cents per kg over the measured 1040 g = 1300 cents, not 1250.
    assert_money(line, "final_line_price_cents", 1300)
    assert_status(line, LineStatus.PICKED.value, field="line_status")
    assert_int_field(line, "picked_units", 2)
    assert_int_field(line, "picked_weight_grams", 1040)

    order = fixtures.read_order(
        api, confirmed["account"]["id"], confirmed["order"]["id"]
    )
    assert_order_money(
        order,
        merchandise_subtotal_cents=1300,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=1899,
        authorized_amount_cents=1849,
    )
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.PICKING.value,
        billing_status=BillingStatus.ADJUSTED.value,
    )

    picked_sku = fixtures.read_inventory_sku(api, beef["id"])
    assert_sku_ledger(
        picked_sku, physical_units=98, allocated_units=0, on_hand_units=98
    )


def test_a_weighed_line_that_lands_on_its_declared_weight_leaves_the_money_dimension_alone(
    api,
):
    """When the scale agrees with the catalogue the two price variants agree too.

    Cites the requirement it rests on: "When a re-run produces the same total that is already stored, the `billing_status` does not move at all."

    Design: Difficulty/dual_variant_calc/catchweight_line_price_provisional_vs_final
    """
    plant = fixtures.build_plant(
        api, route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 150}
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    beef = fixtures.create_catchweight_sku(
        api,
        plant["zone"]["id"],
        unit_price_cents=625,
        price_per_kg_cents=1250,
        nominal_weight_grams=500,
        weight_tolerance_pct=0.05,
        physical_units=100,
    )
    confirmed = fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [beef["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.BASIC.value,
        stop_distance_km=2.03,
    )
    assert_order_money(confirmed["order"], authorized_amount_cents=1849)

    wave = fixtures.create_delivery_wave(api, plant["route"]["id"], slot["id"])
    fixtures.slot_order_into_wave(api, wave["id"], confirmed["order"]["id"])
    fixtures.start_picking(api, wave["id"])
    task = fixtures.pick_task_for_line(api, confirmed["lines"][0]["id"])
    fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        wave["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )

    # The joint weighs exactly the declared 500 g x 2 units.
    fixtures.complete_pick_task(api, task["id"], 2, actual_weight_grams=1000)

    line = fixtures.read_order_line(
        api, confirmed["account"]["id"], confirmed["lines"][0]["id"]
    )
    assert_money(line, "provisional_line_price_cents", 1250)
    assert_money(line, "final_line_price_cents", 1250)
    assert_int_field(line, "picked_weight_grams", 1000)
    assert_status(line, LineStatus.PICKED.value, field="line_status")

    order = fixtures.read_order(
        api, confirmed["account"]["id"], confirmed["order"]["id"]
    )
    assert_order_money(
        order,
        merchandise_subtotal_cents=1250,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=1849,
        authorized_amount_cents=1849,
    )
    assert_order_statuses(order, billing_status=BillingStatus.AUTHORIZED.value)


def test_both_weighed_price_variants_round_a_half_cent_upward(api):
    """A weighed line sitting on the half cent rounds away from zero in both variants.

    Cites the requirement it rests on: "Wherever a computation produces a non-integral money figure, the result is rounded **half up** to whole cents — a value exactly on the half-cent boundary rounds away from zero, upward."

    Design: Difficulty/dual_variant_calc/catchweight_line_price_provisional_vs_final
    """
    plant = fixtures.build_plant(
        api, route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 150}
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    cheese = fixtures.create_catchweight_sku(
        api,
        plant["zone"]["id"],
        unit_price_cents=630,
        price_per_kg_cents=1250,
        nominal_weight_grams=501,
        weight_tolerance_pct=0.05,
        physical_units=100,
    )
    confirmed = fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [cheese["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.BASIC.value,
        stop_distance_km=2.03,
    )
    # A declared 501 g x 2 units at 1250 cents per kg is 1252.5 cents.
    assert_money(confirmed["lines"][0], "provisional_line_price_cents", 1253)
    assert_order_money(confirmed["order"], authorized_amount_cents=1852)

    wave = fixtures.create_delivery_wave(api, plant["route"]["id"], slot["id"])
    fixtures.slot_order_into_wave(api, wave["id"], confirmed["order"]["id"])
    fixtures.start_picking(api, wave["id"])
    task = fixtures.pick_task_for_line(api, confirmed["lines"][0]["id"])
    fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        wave["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )

    # A measured 1006 g at 1250 cents per kg is 1257.5 cents.
    fixtures.complete_pick_task(api, task["id"], 2, actual_weight_grams=1006)

    line = fixtures.read_order_line(
        api, confirmed["account"]["id"], confirmed["lines"][0]["id"]
    )
    assert_money(line, "provisional_line_price_cents", 1253)
    assert_money(line, "final_line_price_cents", 1258)

    order = fixtures.read_order(
        api, confirmed["account"]["id"], confirmed["order"]["id"]
    )
    assert_order_money(
        order,
        merchandise_subtotal_cents=1258,
        delivery_fee_cents=599,
        order_total_cents=1857,
        authorized_amount_cents=1852,
    )
    assert_order_statuses(order, billing_status=BillingStatus.ADJUSTED.value)


def test_one_audit_scores_a_zone_by_pooled_units_and_by_equal_weight_per_sku(api):
    """The pooled unit-weighted score masks a small badly counted jar the per-SKU average exposes.

    Cites the requirement it rests on: "The **unit-weighted score** pools first and divides once: the absolute values of every scored SKU's variance are added into a single total variance, every scored SKU's system figure is added into a single total system count, and the score is one minus the ratio of those two totals."

    Design: Difficulty/dual_variant_calc/zone_inventory_accuracy_unit_vs_sku_weighted
    """
    zone = fixtures.create_grid_zone(api)
    bulk_rice = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=500, physical_units=1000
    )
    saffron = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=2500, physical_units=10
    )

    fixtures.record_audit_counts(
        api, zone["id"], [(bulk_rice["id"], 995), (saffron["id"], 8)]
    )

    audited = fixtures.read_grid_zone(api, zone["id"])
    # Pooled: 1 - (5 + 2) / (1000 + 10) = 0.99306930...
    assert_ratio(audited, "accuracy_score_unit_weighted", 0.9931)
    # Averaged per SKU: ((1 - 5/1000) + (1 - 2/10)) / 2 = 0.8975
    assert_ratio(audited, "accuracy_score_sku_weighted", 0.8975)
    assert audited["accuracy_score_unit_weighted"] >= ACCURACY_HOLD_THRESHOLD
    assert_status(audited, GridZoneStatus.OPERATIONAL.value)
    assert_instant_equals(
        audited["last_audited_at"], DEFAULT_CLOCK_UTC, label="last_audited_at"
    )

    counted_rice = fixtures.read_inventory_sku(api, bulk_rice["id"])
    assert_int_field(counted_rice, "last_count_system_units", 1000)
    assert_int_field(counted_rice, "last_count_counted_units", 995)
    assert_int_field(counted_rice, "last_count_variance_units", -5)
    assert_sku_ledger(
        counted_rice, physical_units=995, allocated_units=0, on_hand_units=995
    )

    counted_saffron = fixtures.read_inventory_sku(api, saffron["id"])
    assert_int_field(counted_saffron, "last_count_system_units", 10)
    assert_int_field(counted_saffron, "last_count_counted_units", 8)
    assert_int_field(counted_saffron, "last_count_variance_units", -2)
    assert_sku_ledger(
        counted_saffron, physical_units=8, allocated_units=0, on_hand_units=8
    )


def test_the_audit_hold_gate_reads_only_the_unit_weighted_score(api):
    """A zone is held on its pooled score even while its per-SKU average passes.

    Cites the requirement it rests on: "The SKU-weighted score is reported for operator dashboards and never moves the zone's status, no matter how low it falls."

    Design: Difficulty/dual_variant_calc/zone_inventory_accuracy_unit_vs_sku_weighted
    """
    zone = fixtures.create_grid_zone(api)
    bulk_rice = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=500, physical_units=1000
    )
    saffron = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=2500, physical_units=10
    )

    # The pallet is 30 units short; the jar counts perfectly.
    fixtures.record_audit_counts(
        api, zone["id"], [(bulk_rice["id"], 970), (saffron["id"], 10)]
    )

    audited = fixtures.read_grid_zone(api, zone["id"])
    # Pooled: 1 - 30 / 1010 = 0.97029702..., below the 0.9800 hold threshold.
    assert_ratio(audited, "accuracy_score_unit_weighted", 0.9703)
    # Averaged per SKU: ((1 - 30/1000) + 1) / 2 = 0.9850, above the threshold.
    assert_ratio(audited, "accuracy_score_sku_weighted", 0.9850)
    assert audited["accuracy_score_unit_weighted"] < ACCURACY_HOLD_THRESHOLD
    assert audited["accuracy_score_sku_weighted"] >= ACCURACY_HOLD_THRESHOLD
    assert_status(audited, GridZoneStatus.AUDIT_HOLD.value)
    assert_instant_equals(
        audited["last_audited_at"], DEFAULT_CLOCK_UTC, label="last_audited_at"
    )

    counted_rice = fixtures.read_inventory_sku(api, bulk_rice["id"])
    assert_int_field(counted_rice, "last_count_variance_units", -30)
    assert_sku_ledger(
        counted_rice, physical_units=970, allocated_units=0, on_hand_units=970
    )

    counted_saffron = fixtures.read_inventory_sku(api, saffron["id"])
    assert_int_field(counted_saffron, "last_count_variance_units", 0)
    assert_sku_ledger(
        counted_saffron, physical_units=10, allocated_units=0, on_hand_units=10
    )


def test_transport_cost_rounds_each_drop_before_the_van_route_is_totalled(api):
    """Two drops on the half cent each round up before the route total is formed.

    Cites the requirement it rests on: "For each stop, the route's `per_km_cost_cents` is multiplied by that order's `stop_distance_km` and the product is rounded half up to whole cents. Those per-stop integers are then added exactly to give `transport_cost_cents`."

    Design: Difficulty/combinatorial_formula/wave_transport_cost_round_per_stop_then_sum
    """
    plant = fixtures.build_plant(
        api, route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 150}
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    pasta = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    near = fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [pasta["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.BASIC.value,
        stop_distance_km=2.03,
    )
    far = fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [pasta["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.BASIC.value,
        stop_distance_km=2.11,
    )

    wave = fixtures.create_delivery_wave(api, plant["route"]["id"], slot["id"])
    fixtures.slot_order_into_wave(api, wave["id"], near["order"]["id"])
    fixtures.slot_order_into_wave(api, wave["id"], far["order"]["id"])
    fixtures.assign_dock(api, wave["id"], plant["bay"]["id"], LOAD_START, LOAD_END)
    fixtures.start_picking(api, wave["id"])
    tasks = fixtures.pick_tasks_for_wave(api, wave["id"])
    tote = fixtures.create_tote(
        api,
        wave["id"],
        tasks[0]["pick_station_id"],
        temperature_zone=TemperatureZone.AMBIENT.value,
    )
    for task in tasks:
        fixtures.assign_tote(api, task["id"], tote["id"])
        fixtures.start_retrieval(api, task["id"])
        fixtures.complete_pick_task(api, task["id"], 2)
    fixtures.seal_tote(api, tote["id"])
    fixtures.consolidate_wave(api, wave["id"])

    sequenced = fixtures.compute_loading_sequence(api, wave["id"])

    # 150 x 2.03 = 304.5 -> 305 and 150 x 2.11 = 316.5 -> 317, so 622.
    # Summing 4.14 km first and rounding once would report 621.
    assert_money(sequenced, "transport_cost_cents", 622)
    assert_status(sequenced, WaveStatus.LOADING.value)
    assert_load_sequence(sequenced, [tote["id"]])

    assert_status(fixtures.read_tote(api, tote["id"]), ToteStatus.LOADED.value)
    for stop in (near, far):
        loaded = fixtures.read_order(api, stop["account"]["id"], stop["order"]["id"])
        assert_order_statuses(
            loaded, fulfillment_status=FulfillmentStatus.LOADED.value
        )
        assert_order_money(loaded, order_total_cents=1999)


def test_transport_cost_never_rounds_the_whole_van_route_at_the_end(api):
    """Two drops whose cents both round down keep the route total below the single-rounding figure.

    Cites the requirement it rests on: "The rounding order here is mandatory and is the round-per-item-then-sum rule of §2.6: summing the exact kilometre products and rounding once at the end is explicitly not the rule, and produces a different total whenever two or more stops land on a half cent."

    Design: Difficulty/combinatorial_formula/wave_transport_cost_round_per_stop_then_sum
    """
    plant = fixtures.build_plant(
        api, route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 110}
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    pasta = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    near = fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [pasta["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.BASIC.value,
        stop_distance_km=2.03,
    )
    far = fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [pasta["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.BASIC.value,
        stop_distance_km=4.03,
    )

    wave = fixtures.create_delivery_wave(api, plant["route"]["id"], slot["id"])
    fixtures.slot_order_into_wave(api, wave["id"], near["order"]["id"])
    fixtures.slot_order_into_wave(api, wave["id"], far["order"]["id"])
    fixtures.assign_dock(api, wave["id"], plant["bay"]["id"], LOAD_START, LOAD_END)
    fixtures.start_picking(api, wave["id"])
    tasks = fixtures.pick_tasks_for_wave(api, wave["id"])
    tote = fixtures.create_tote(
        api,
        wave["id"],
        tasks[0]["pick_station_id"],
        temperature_zone=TemperatureZone.AMBIENT.value,
    )
    for task in tasks:
        fixtures.assign_tote(api, task["id"], tote["id"])
        fixtures.start_retrieval(api, task["id"])
        fixtures.complete_pick_task(api, task["id"], 2)
    fixtures.seal_tote(api, tote["id"])
    fixtures.consolidate_wave(api, wave["id"])

    sequenced = fixtures.compute_loading_sequence(api, wave["id"])

    # 110 x 2.03 = 223.3 -> 223 and 110 x 4.03 = 443.3 -> 443, so 666.
    # Summing 6.06 km first gives 666.6 and would round once to 667.
    assert_money(sequenced, "transport_cost_cents", 666)
    assert_status(sequenced, WaveStatus.LOADING.value)
    assert_status(sequenced, WavePosture.OPEN.value, field="posture")


def test_the_free_delivery_waiver_reads_the_subtotal_while_the_loyalty_tier_reads_the_post_fee_figure(
    api,
):
    """The fee waiver is decided on merchandise alone, the discount tier on merchandise plus fee.

    Cites the requirement it rests on: "The service forms the pre-discount total as `merchandise_subtotal_cents` plus `delivery_fee_cents`, and this is the figure the discount tier is keyed on."

    Design: Difficulty/combinatorial_formula/order_charge_evaluation_order_fee_then_tiered_discount
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api)
    hamper = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=4900, physical_units=50
    )
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)
    basket = fixtures.build_shopper_with_basket(
        api,
        route["id"],
        [hamper["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.PREMIER.value,
        stop_distance_km=3.00,
    )

    booking = fixtures.create_slot_booking(
        api, basket["account"]["id"], slot["id"], basket["order"]["id"], units=1
    )

    assert_status(booking, BookingStatus.HELD.value)
    assert_ratio(booking, "surge_multiplier_at_booking", 1.00, places=2)
    assert_money(booking, "quoted_fee_cents", 599)

    order = fixtures.read_order(api, basket["account"]["id"], basket["order"]["id"])
    # 9800 is under the 10000 waiver, so the 599 fee stands; the PREMIER tier is
    # then keyed on 10399, giving 1039.9 -> 1040 rather than 980 on 9800 alone.
    assert_order_money(
        order,
        merchandise_subtotal_cents=9800,
        delivery_fee_cents=599,
        loyalty_discount_cents=1040,
        order_total_cents=9359,
    )
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
    assert_field_absent_or_null(order, "authorized_amount_cents")

    booked_slot = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        booked_slot,
        total_capacity_units=10,
        withheld_units=0,
        held_units=1,
        confirmed_units=0,
        available_units=9,
    )


def test_a_basket_of_exactly_one_hundred_dollars_waives_the_fee_before_the_discount_is_keyed(
    api,
):
    """The waived fee contributes nothing to the figure the loyalty tier is keyed on.

    Cites the requirement it rests on: "Then the waiver applies: if `merchandise_subtotal_cents` is at least one hundred dollars — 10,000 cents — the fee is overwritten with 0."

    Design: Difficulty/combinatorial_formula/order_charge_evaluation_order_fee_then_tiered_discount
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api)
    hamper = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=5000, physical_units=50
    )
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)
    basket = fixtures.build_shopper_with_basket(
        api,
        route["id"],
        [hamper["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.PREMIER.value,
        stop_distance_km=3.00,
    )

    booking = fixtures.create_slot_booking(
        api, basket["account"]["id"], slot["id"], basket["order"]["id"], units=1
    )

    # The booking still quotes the pre-waiver fee it froze at booking time.
    assert_money(booking, "quoted_fee_cents", 599)

    order = fixtures.read_order(api, basket["account"]["id"], basket["order"]["id"])
    # A subtotal of exactly 10000 earns free delivery, so the tier is keyed on
    # 10000 and the ten per cent discount is 1000, not 1059.9 on 10599.
    assert_order_money(
        order,
        merchandise_subtotal_cents=10000,
        delivery_fee_cents=0,
        loyalty_discount_cents=1000,
        order_total_cents=9000,
    )


def test_a_plus_shopper_reaches_the_discount_threshold_only_once_the_fee_is_added(api):
    """A basket under fifty dollars still earns the PLUS rate because the fee lifts it over.

    Cites the requirement it rests on: "A `PLUS` shopper receives five per cent when the pre-discount total is at least fifty dollars — 5,000 cents — and zero per cent below that."

    Design: Difficulty/combinatorial_formula/order_charge_evaluation_order_fee_then_tiered_discount
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api)
    crate = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=2300, physical_units=50
    )
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)
    basket = fixtures.build_shopper_with_basket(
        api,
        route["id"],
        [crate["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.PLUS.value,
        stop_distance_km=3.00,
    )

    booking = fixtures.create_slot_booking(
        api, basket["account"]["id"], slot["id"], basket["order"]["id"], units=1
    )

    assert_status(booking, BookingStatus.HELD.value)
    assert_money(booking, "quoted_fee_cents", 599)

    order = fixtures.read_order(api, basket["account"]["id"], basket["order"]["id"])
    # 4600 alone would earn a PLUS shopper nothing; 4600 + 599 = 5199 earns five
    # per cent, which is 259.95 and rounds half up to 260.
    assert_order_money(
        order,
        merchandise_subtotal_cents=4600,
        delivery_fee_cents=599,
        loyalty_discount_cents=260,
        order_total_cents=4939,
    )


def test_a_premier_shopper_under_fifty_dollars_still_receives_the_lower_rate(api):
    """Below the tier boundary a PREMIER shopper drops to five per cent rather than to nothing.

    Cites the requirement it rests on: "A `PREMIER` shopper receives ten per cent when the pre-discount total is at least 5,000 cents and five per cent below that; a `PREMIER` shopper is never without a discount."

    Design: Difficulty/combinatorial_formula/order_charge_evaluation_order_fee_then_tiered_discount
    """
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(api)
    staple = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=500, physical_units=50
    )
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)
    basket = fixtures.build_shopper_with_basket(
        api,
        route["id"],
        [staple["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.PREMIER.value,
        stop_distance_km=3.00,
    )

    booking = fixtures.create_slot_booking(
        api, basket["account"]["id"], slot["id"], basket["order"]["id"], units=1
    )

    assert_status(booking, BookingStatus.HELD.value)

    order = fixtures.read_order(api, basket["account"]["id"], basket["order"]["id"])
    # 1000 + 599 = 1599 is under 5000, so the rate is five per cent: 79.95 -> 80.
    assert_order_money(
        order,
        merchandise_subtotal_cents=1000,
        delivery_fee_cents=599,
        loyalty_discount_cents=80,
        order_total_cents=1519,
    )
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
