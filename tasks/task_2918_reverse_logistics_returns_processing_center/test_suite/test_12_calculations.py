"""Pinned arithmetic: weight expectations, fee bands, rounding order and selection."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_instant_equals,
    assert_line_states,
    assert_money,
    assert_pct_equals,
    plus_hours,
    sole_entry_of_type,
)
from test_helpers.constants import (
    CHANNEL_WINDOW_A_END,
    CHANNEL_WINDOW_A_START,
    CLIENT_STATUS_ACTIVE,
    CLOCK_STARTUP_INSTANT,
    DEFAULT_REFUND_HOLD_HOURS,
    DISPOSITION_DESTROY,
    DISPOSITION_LIQUIDATE,
    DISPOSITION_REFURBISH,
    DISPOSITION_RESTOCK,
    DO_EXECUTED,
    DS_DISPOSITION_ASSIGNED,
    DS_DISPOSITIONED,
    ENTRY_DESTRUCTION_WRITE_OFF,
    ENTRY_RECOVERY_CREDIT,
    ENTRY_REFUND_DEBIT,
    ENTRY_REFURB_COST,
    FS_REFUNDED,
    GRADE_A,
    GRADE_B,
    GRADE_C,
    GRADE_SCRAP,
    PACKAGING_TARE_GRAMS,
    REASON_BUYER_REMORSE,
    REASON_DEFECTIVE,
    REASON_SHIPPING_DAMAGE,
    RMA_PARTIALLY_RECEIVED,
    SL_WHITE_GLOVE,
    TEST_RESULT_FAIL,
    TEST_RESULT_PASS,
    TEST_WINDOW_1_END,
    TEST_WINDOW_1_START,
    TEST_WINDOW_2_END,
    TEST_WINDOW_2_START,
    USER_ANALYST,
    USER_QA,
    USER_TECH,
    WO_REPACKAGED,
)
from test_helpers.test_users import (
    ANALYST,
    CLERK,
    GRADER,
    SUPERVISOR,
    SUPERVISOR_2,
    TECHNICIAN,
)

# An order placed exactly sixty-one whole days before the startup clock, which
# is one day past the sixty-day lateness boundary.
ORDER_PLACED_SIXTY_ONE_DAYS_AGO = "2026-06-01T00:00:00Z"


def test_expected_carton_weight_is_the_tare_plus_every_authorized_line(api):
    """PRD §3.3: "`expected_weight_grams` is the sum, over every authorization
    line of that receipt's authorization, of the line's item
    `unit_weight_grams` multiplied by that line's `authorized_quantity`, plus a
    fixed packaging tare of 200 grams."

    Design: Corner/calculations/corner_calc_expected_weight_is_tare_plus_authorized_line_weights
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "Calc One", "client_code": "CA1"},
        items=[
            fx.widget_item_kwargs(
                sku="HEAVY-1", description="Heavy widget", unit_weight_grams=1200
            ),
            fx.widget_item_kwargs(
                sku="LIGHT-1",
                description="Light widget",
                declared_value_cents=5000,
                unit_weight_grams=500,
                secondary_market_floor_cents=500,
            ),
        ],
        lines=[
            {"item_index": 0, "authorized_quantity": 3, "reason_code": REASON_DEFECTIVE},
            {"item_index": 1, "authorized_quantity": 2, "reason_code": REASON_DEFECTIVE},
        ],
        rma_kwargs={"order_reference": "ORD-CA1", "customer_reference": "CUST-CA1"},
        scan=False,
    )

    receipt = validate_success(
        api.create_receipt(
            f.receipt_payload(
                world["rma"]["id"],
                tracking_reference="TRK-CA1",
                gross_weight_grams=4800,
            ),
            CLERK,
        ),
        201,
    )
    by_hand = PACKAGING_TARE_GRAMS + 3 * 1200 + 2 * 500
    assert by_hand == 4800
    assert receipt["expected_weight_grams"] == by_hand, (
        "the tare is added once and every authorized line contributes its weight"
    )
    assert receipt["empty_box_suspected"] is False, (
        "4800 x 100 is not below 4800 x 60, so the carton is not a suspected empty box"
    )

    rma = fx.read_rma(api, world["rma"]["id"])
    assert rma["authorized_unit_total"] == 5


def test_a_second_carton_is_still_weighed_against_the_whole_authorization(api):
    """PRD §3.3: "`expected_weight_grams` is the sum, over every authorization
    line of that receipt's authorization, of the line's item
    `unit_weight_grams` multiplied by that line's `authorized_quantity`, plus a
    fixed packaging tare of 200 grams."

    Design: Corner/calculations/corner_calc_expected_weight_uses_authorized_not_received_quantity
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "Calc Two", "client_code": "CA2"},
        items=[fx.widget_item_kwargs(sku="HEAVY-1", description="Heavy widget")],
        lines=[{"authorized_quantity": 3, "reason_code": REASON_DEFECTIVE}],
        rma_kwargs={"order_reference": "ORD-CA2", "customer_reference": "CUST-CA2"},
        scan=False,
    )
    assert world["expected_weight_grams"] == 3800

    first = fx.make_receipt(
        api, world["rma"]["id"], 3800, tracking_reference="TRK-CA2A"
    )
    fx.scan_line(api, first["id"], world["rma_line"]["id"], quantity=1)

    second = validate_success(
        api.create_receipt(
            f.receipt_payload(
                world["rma"]["id"],
                tracking_reference="TRK-CA2B",
                gross_weight_grams=2600,
            ),
            CLERK,
        ),
        201,
    )
    assert second["expected_weight_grams"] == 3800, (
        "the expectation is the full authorization, not the two outstanding units"
    )
    assert second["empty_box_suspected"] is False, (
        "2600 x 100 == 260000 is not below 3800 x 60 == 228000"
    )

    rma = fx.read_rma(api, world["rma"]["id"])
    assert rma["status"] == RMA_PARTIALLY_RECEIVED
    assert rma["received_unit_total"] == 1


def test_only_one_lateness_band_applies_at_sixty_one_days(api):
    """PRD §3.4: "A lateness adjustment is added from mutually exclusive,
    non-cumulative bands keyed on `days_since_order`: 0.20 when it is greater
    than 60 days, otherwise 0.10 when it is greater than 30 days, otherwise
    0.00."

    Design: Corner/calculations/corner_calc_late_fee_bands_are_mutually_exclusive_not_cumulative
    """
    world = fx.graded_scenario(
        api,
        client_kwargs={
            "name": "Calc Three",
            "client_code": "CA3",
            "service_level": SL_WHITE_GLOVE,
        },
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_BUYER_REMORSE}],
        rma_kwargs={
            "order_reference": "ORD-CA3",
            "customer_reference": "CUST-CA3",
            "order_placed_at": ORDER_PLACED_SIXTY_ONE_DAYS_AGO,
        },
        tracking_reference="TRK-CA3",
        condition_grade=GRADE_B,
    )
    line = fx.read_return_line(api, world["line"]["id"])
    assert line["days_since_order"] == 61

    release = world["refund_release"]
    # 0.20 buyer remorse - 0.10 white glove + 0.05 grade B + 0.20 lateness.
    assert_pct_equals(release["restocking_fee_pct"], 0.35, "restocking_fee_pct")
    assert_money(release["gross_refund_cents"], 20000, "gross_refund_cents")
    assert_money(release["restocking_fee_cents"], 7000, "restocking_fee_cents")
    assert_money(release["net_refund_cents"], 13000, "net_refund_cents")
    assert release["restocking_fee_pct"] != 0.45, (
        "adding both lateness bands together would give 0.45 and a 9000-cent fee"
    )

    assert_line_states(line, disposition=DISPOSITION_RESTOCK)


def test_the_fee_ceiling_clamps_the_sum_and_not_the_individual_terms(api):
    """PRD §3.4: "The four terms are summed, and the sum — never the individual
    terms — is then floored at 0.00 and capped at 0.50, so a white-glove credit
    of minus 0.10 can offset a grade surcharge of plus 0.05 before the floor is
    tested."

    Design: Corner/calculations/corner_calc_fee_ceiling_clamps_the_sum_after_all_four_terms
    """
    world = fx.graded_scenario(
        api,
        client_kwargs={"name": "Calc Four", "client_code": "CA4"},
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_BUYER_REMORSE}],
        rma_kwargs={
            "order_reference": "ORD-CA4",
            "customer_reference": "CUST-CA4",
            "order_placed_at": ORDER_PLACED_SIXTY_ONE_DAYS_AGO,
        },
        tracking_reference="TRK-CA4",
        condition_grade=GRADE_SCRAP,
    )
    release = world["refund_release"]
    # 0.20 + 0.00 + 0.25 + 0.20 sums to 0.65 and is clamped once to 0.50.
    assert_pct_equals(release["restocking_fee_pct"], 0.50, "restocking_fee_pct")
    assert_money(release["gross_refund_cents"], 20000, "gross_refund_cents")
    assert_money(release["restocking_fee_cents"], 10000, "restocking_fee_cents")
    assert_money(release["net_refund_cents"], 10000, "net_refund_cents")
    assert (
        release["gross_refund_cents"]
        == release["restocking_fee_cents"] + release["net_refund_cents"]
    ), "gross must split exactly into fee and net"

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(line, disposition=DISPOSITION_DESTROY)
    assert_money(line["recovery_value_cents"], 0, "recovery at a 0.00 multiplier")


def test_the_recovery_estimate_rounds_per_unit_before_multiplying(api):
    """PRD §3.4: "`recovery_value_cents` is that rounded per-unit figure
    multiplied by the line's `quantity` — rounding once per unit before the
    multiplication, never once at the end."

    Design: Corner/calculations/corner_calc_recovery_rounds_per_unit_before_multiplying_quantity
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "Calc Five", "client_code": "CA5"},
        items=[
            fx.widget_item_kwargs(
                sku="ODD-1",
                description="Odd-valued widget",
                declared_value_cents=20001,
            )
        ],
        lines=[{"authorized_quantity": 2, "reason_code": REASON_DEFECTIVE}],
        rma_kwargs={"order_reference": "ORD-CA5", "customer_reference": "CUST-CA5"},
        tracking_reference="TRK-CA5",
    )
    graded = validate_success(
        api.grade_line(world["line"]["id"], f.grade_payload(GRADE_C), GRADER),
        200,
    )
    # round_half_up(20001 x 0.40 x 0.90) is 7200 per unit, times a quantity of 2.
    assert_money(graded["recovery_value_cents"], 14400, "recovery_value_cents")
    assert graded["recovery_value_cents"] != 14401, (
        "multiplying first and rounding once at the end would give 14401"
    )
    assert_line_states(graded, disposition=DISPOSITION_LIQUIDATE)


def test_a_projected_refurbishment_margin_of_exactly_zero_does_not_refurbish(api):
    """PRD §3.4: "Otherwise, if refurbishment is effectively available for this
    item, the `condition_grade` is `B` or `C`, the `hazard_class` is `NONE`, and
    the projected refurbishment margin is strictly greater than zero, the
    disposition is `REFURBISH`."

    Design: Corner/calculations/corner_calc_d5_strict_zero_refurb_margin_does_not_refurbish
    """
    world = fx.received_scenario(
        api,
        client_kwargs={
            "name": "Calc Six",
            "client_code": "CA6",
            "restock_grade_floor": GRADE_A,
        },
        items=[
            fx.widget_item_kwargs(
                sku="MARGIN-0",
                description="Zero-margin SKU",
                declared_value_cents=9231,
                refurb_eligible=True,
                secondary_market_floor_cents=500,
            ),
            fx.widget_item_kwargs(
                sku="MARGIN-1",
                description="One-cent-margin SKU",
                declared_value_cents=9232,
                refurb_eligible=True,
                secondary_market_floor_cents=500,
            ),
        ],
        lines=[
            {"item_index": 0, "authorized_quantity": 1, "reason_code": REASON_DEFECTIVE},
            {"item_index": 1, "authorized_quantity": 1, "reason_code": REASON_DEFECTIVE},
        ],
        rma_kwargs={"order_reference": "ORD-CA6", "customer_reference": "CUST-CA6"},
        tracking_reference="TRK-CA6",
    )

    # round_half_up(9231 x 0.65) is 6000, so the margin over the 6000-cent
    # standard refurbishment cost is exactly zero and the strict test fails.
    zero_margin = fx.grade_line(api, world["lines"][0]["id"], GRADE_B)
    assert_money(zero_margin["recovery_value_cents"], 5400, "recovery_value_cents")
    assert_line_states(
        zero_margin,
        disposition=DISPOSITION_LIQUIDATE,
        disposition_state=DS_DISPOSITION_ASSIGNED,
    )

    # round_half_up(9232 x 0.65) is 6001, a margin of one cent.
    one_cent_margin = fx.grade_line(api, world["lines"][1]["id"], GRADE_B)
    assert_money(one_cent_margin["recovery_value_cents"], 5401, "recovery_value_cents")
    assert_line_states(
        one_cent_margin,
        disposition=DISPOSITION_REFURBISH,
        disposition_state=DS_DISPOSITION_ASSIGNED,
    )


def test_the_secondary_market_floor_beats_a_lower_indexed_estimate(api):
    """PRD §3.6: "For a `LIQUIDATE` order the per-unit provisional recovery —
    again the line's `recovery_value_cents` divided by its `quantity` — is
    multiplied by the resolved channel's current `price_index_pct` and rounded
    half up to a cent, and the result is then raised, if necessary, to the
    item's `secondary_market_floor_cents`; the index multiplication is rounded
    before the floor is applied, so the floor wins ties exactly at equality."

    Design: Corner/calculations/corner_calc_unit_price_secondary_market_floor_beats_indexed_estimate
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("CA7", name="Calc Seven"),
        items=[
            fx.widget_item_kwargs(
                sku="FLOOR-1",
                description="High-floor widget",
                secondary_market_floor_cents=8000,
            )
        ],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        rma_kwargs={"order_reference": "ORD-CA7", "customer_reference": "CUST-CA7"},
        tracking_reference="TRK-CA7",
        condition_grade=GRADE_C,
    )
    channel = fx.make_channel(
        api, **fx.auction_channel_kwargs("AU07", name="Auction Seven")
    )

    order = fx.propose_order(
        api,
        world["line"]["id"],
        channel_id=channel["id"],
        disposition=DISPOSITION_LIQUIDATE,
        quantity=1,
    )
    # The indexed estimate is 7200 at a price_index_pct of 1.0000; the floor wins.
    assert_money(order["unit_price_cents"], 8000, "unit_price_cents")
    assert order["selected_by_policy"] is False, (
        "the caller named the channel, so the policy did not resolve it"
    )
    assert_money(order["gross_lot_value_cents"], 0, "gross before execution")

    fx.approve_order(api, order["id"], headers=SUPERVISOR)
    executed = fx.execute_order(api, order["id"], headers=SUPERVISOR_2)
    assert executed["status"] == DO_EXECUTED
    assert_money(executed["gross_lot_value_cents"], 8000, "gross_lot_value_cents")
    assert_pct_equals(executed["effective_fee_pct"], 0.18, "effective_fee_pct")
    assert_money(executed["channel_fee_cents"], 1440, "channel_fee_cents")
    assert_money(executed["refurb_cost_cents"], 0, "refurb_cost_cents")
    assert_money(executed["net_recovery_cents"], 6560, "net_recovery_cents")

    credit = sole_entry_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_RECOVERY_CREDIT
    )
    assert_money(credit["amount_cents"], 6068, "RECOVERY_CREDIT amount_cents")

    line = fx.read_return_line(api, world["line"]["id"])
    assert_money(line["recovery_value_cents"], 6560, "recovery after execution")
    assert_line_states(line, disposition_state=DS_DISPOSITIONED)


def test_a_release_attempted_at_exactly_the_eligible_instant_succeeds(api):
    """PRD §3.7: "A release is permitted when the current logical clock is at or
    after `release_eligible_at`; the comparison is inclusive at millisecond
    resolution, so an attempt at exactly `release_eligible_at` succeeds and one
    millisecond earlier is refused with `ERR_REFUND_HOLD_ACTIVE`."

    Design: Corner/calculations/corner_calc_refund_release_permitted_at_exactly_release_eligible_at
    """
    world = fx.graded_scenario(
        api,
        client_kwargs={"name": "Calc Eight", "client_code": "CA8"},
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        rma_kwargs={"order_reference": "ORD-CA8", "customer_reference": "CUST-CA8"},
        tracking_reference="TRK-CA8",
        condition_grade=GRADE_C,
    )
    channel = fx.make_channel(
        api, **fx.auction_channel_kwargs("AU08", name="Auction Eight")
    )
    order = fx.propose_order(
        api,
        world["line"]["id"],
        channel_id=channel["id"],
        disposition=DISPOSITION_LIQUIDATE,
        quantity=1,
    )
    fx.approve_order(api, order["id"], headers=SUPERVISOR)
    executed = fx.execute_order(api, order["id"], headers=SUPERVISOR_2)
    assert_instant_equals(executed["executed_at"], CLOCK_STARTUP_INSTANT, "executed_at")

    eligible_at = plus_hours(CLOCK_STARTUP_INSTANT, DEFAULT_REFUND_HOLD_HOURS)
    pending = fx.refund_release_for_line(api, world["line"]["id"])
    assert_instant_equals(
        pending["release_eligible_at"], eligible_at, "release_eligible_at"
    )

    fx.set_clock(api, eligible_at)
    released_line = validate_success(
        api.release_refund(world["line"]["id"], ANALYST), 200
    )
    assert_line_states(released_line, financial_state=FS_REFUNDED)

    release = fx.refund_release_for_line(api, world["line"]["id"])
    assert_instant_equals(release["released_at"], eligible_at, "released_at")
    assert release["released_by_user_id"] == USER_ANALYST
    assert_money(release["net_refund_cents"], 18000, "net_refund_cents")

    entries = fx.list_ledger(api, world["client"]["id"])
    assert len(entries) == 2, "one recovery credit and one refund debit"
    credit = sole_entry_of_type(entries, ENTRY_RECOVERY_CREDIT)
    debit = sole_entry_of_type(entries, ENTRY_REFUND_DEBIT)
    assert_money(credit["amount_cents"], 5461, "RECOVERY_CREDIT amount_cents")
    assert_money(debit["amount_cents"], -18000, "REFUND_DEBIT amount_cents")
    assert credit["sequence_no"] < debit["sequence_no"], (
        "the recovery credit was appended before the refund debit"
    )

    client = fx.read_client(api, world["client"]["id"])
    assert_money(
        client["settlement_balance_cents"], -12539, "settlement_balance_cents"
    )
    assert client["status"] == CLIENT_STATUS_ACTIVE


def test_the_destruction_fee_is_charged_per_unit_in_the_ledger(api):
    """PRD §3.8: "A `DESTRUCTION_WRITE_OFF` is appended when a `DESTROY` order
    executes, and its amount is the negative of the item's
    `declared_value_cents` plus the 750-cent certified-destruction fee, that sum
    multiplied by the order's `quantity`."

    Design: Corner/calculations/corner_calc_destruction_write_off_charges_the_fee_per_unit
    """
    world = fx.graded_scenario(
        api,
        client_kwargs={"name": "Calc Nine", "client_code": "CA9"},
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 2, "reason_code": REASON_SHIPPING_DAMAGE}],
        rma_kwargs={"order_reference": "ORD-CA9", "customer_reference": "CUST-CA9"},
        tracking_reference="TRK-CA9",
        condition_grade=GRADE_SCRAP,
    )
    assert_line_states(world["line"], disposition=DISPOSITION_DESTROY)

    channel = fx.make_destruction_channel(
        api, name="Destruction Nine", channel_code="CD09"
    )
    order = fx.propose_order(
        api,
        world["line"]["id"],
        channel_id=channel["id"],
        disposition=DISPOSITION_DESTROY,
        quantity=2,
    )
    fx.approve_order(api, order["id"], headers=SUPERVISOR)
    executed = fx.execute_order(api, order["id"], headers=SUPERVISOR)
    assert executed["status"] == DO_EXECUTED, (
        "the same supervisor may approve and execute when dual signoff is off"
    )
    assert_money(executed["unit_price_cents"], 0, "unit_price_cents")
    assert_money(executed["gross_lot_value_cents"], 0, "gross_lot_value_cents")
    assert_money(executed["net_recovery_cents"], 0, "net_recovery_cents")

    entries = fx.list_ledger(api, world["client"]["id"])
    assert len(entries) == 1
    write_off = sole_entry_of_type(entries, ENTRY_DESTRUCTION_WRITE_OFF)
    # -((20000 declared + 750 destruction fee) x 2 units).
    assert_money(write_off["amount_cents"], -41500, "DESTRUCTION_WRITE_OFF amount")

    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["shrink_ledger_cents"], -41500, "shrink_ledger_cents")
    assert_money(
        client["settlement_balance_cents"], -41500, "settlement_balance_cents"
    )
    assert client["units_dispositioned"] == 2
    assert client["units_in_process"] == 0


def test_the_channel_selector_ranks_on_net_then_breaks_ties_on_channel_code(api):
    """PRD §3.6: "Ties break in order: lower `fee_pct` first, then lower
    `min_lot_value_cents`, then lower `channel_code` compared lexicographically."

    Design: Corner/calculations/corner_calc_channel_selector_ranks_then_tie_breaks_on_channel_code
    """
    world = fx.graded_scenario(
        api,
        client_kwargs={"name": "Calc Ten", "client_code": "CA10"},
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        rma_kwargs={"order_reference": "ORD-CA10", "customer_reference": "CUST-CA10"},
        tracking_reference="TRK-CA10",
        condition_grade=GRADE_C,
    )
    # Created in the order AA01, BB01, CC01 so insertion order cannot be
    # mistaken for the documented tie-break.
    expensive = fx.make_channel(
        api, **fx.auction_channel_kwargs("AA01", name="Auction AA", fee_pct=0.20)
    )
    first_cheap = fx.make_channel(
        api, **fx.auction_channel_kwargs("BB01", name="Auction BB")
    )
    second_cheap = fx.make_channel(
        api, **fx.auction_channel_kwargs("CC01", name="Auction CC")
    )

    line = fx.read_return_line(api, world["line"]["id"])
    order = validate_success(
        api.create_disposition_order(
            f.disposition_order_payload(
                line["id"],
                line["version"],
                disposition=DISPOSITION_LIQUIDATE,
                quantity=1,
                channel_window_start_at=CHANNEL_WINDOW_A_START,
                channel_window_end_at=CHANNEL_WINDOW_A_END,
            ),
            SUPERVISOR,
        ),
        201,
    )
    assert order["selected_by_policy"] is True, (
        "the caller omitted channel_id, so the policy resolved it"
    )
    assert order["channel_id"] == first_cheap["id"]
    assert order["channel_id"] != expensive["id"], (
        "AA01's effective fee of 0.26 projects only 5328 against 5904"
    )
    assert order["channel_id"] != second_cheap["id"], (
        "CC01 ties BB01 on net, fee_pct and min_lot_value_cents, and loses on code"
    )
    assert_money(order["unit_price_cents"], 7200, "unit_price_cents")
    assert order["disposition"] == DISPOSITION_LIQUIDATE


def test_refurbishment_overhead_is_applied_once_across_two_test_cycles(api):
    """PRD §3.5: "Repackaging stamps `packaging_cost_cents` and
    `resulting_grade`, moves the work order to `REPACKAGED`, and computes its
    fully loaded `total_cost_cents`: the accumulated `labor_minutes_total`
    multiplied by a labour rate of 95 cents per minute, plus the accumulated
    `parts_cost_cents`, plus `packaging_cost_cents`, with that direct subtotal
    then increased by a 15 percent overhead and rounded half up to a whole
    cent."

    Design: Corner/calculations/corner_calc_refurb_overhead_applied_once_across_two_test_cycles
    """
    world = fx.graded_scenario(
        api,
        client_kwargs={
            "name": "Calc Eleven",
            "client_code": "CA11",
            "restock_grade_floor": GRADE_A,
        },
        items=[
            fx.widget_item_kwargs(
                sku="REFURB-1",
                description="Refurbishable widget",
                refurb_eligible=True,
            )
        ],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        rma_kwargs={"order_reference": "ORD-CA11", "customer_reference": "CUST-CA11"},
        tracking_reference="TRK-CA11",
        condition_grade=GRADE_B,
    )
    assert_line_states(world["line"], disposition=DISPOSITION_REFURBISH)

    bay = fx.make_general_bay(api, bay_code="GB-CA11")
    work_order = fx.open_work_order(api, world["line"]["id"])
    assert work_order["assigned_technician_user_id"] == USER_TECH

    fx.start_test(
        api, work_order["id"], bay["id"], TEST_WINDOW_1_START, TEST_WINDOW_1_END
    )
    fx.record_test_result(
        api, work_order["id"], TEST_RESULT_FAIL, labor_minutes=30, parts_cost_cents=500
    )
    fx.start_test(
        api, work_order["id"], bay["id"], TEST_WINDOW_2_START, TEST_WINDOW_2_END
    )
    fx.record_test_result(
        api, work_order["id"], TEST_RESULT_PASS, labor_minutes=20
    )

    repackaged = validate_success(
        api.repackage_work_order(
            work_order["id"],
            f.repackage_payload(packaging_cost_cents=700, resulting_grade=GRADE_B),
            TECHNICIAN,
        ),
        200,
    )
    assert repackaged["status"] == WO_REPACKAGED
    assert repackaged["labor_minutes_total"] == 50
    assert_money(repackaged["parts_cost_cents"], 500, "parts_cost_cents")
    assert_money(repackaged["packaging_cost_cents"], 700, "packaging_cost_cents")
    # round_half_up((50 x 95 + 500 + 700) x 1.15) is 6843; charging the overhead
    # once per cycle would not give this figure.
    assert_money(repackaged["total_cost_cents"], 6843, "total_cost_cents")
    assert repackaged["rework_cycles"] == 1
    assert repackaged["qa_user_id"] == USER_QA, (
        "the assigned technician never signed off its own test"
    )

    cost = sole_entry_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_REFURB_COST
    )
    assert_money(cost["amount_cents"], -6843, "REFURB_COST amount_cents")

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        condition_grade=GRADE_B,
        disposition=DISPOSITION_LIQUIDATE,
    )
    assert_money(line["recovery_value_cents"], 11700, "recovery_value_cents")

    release = fx.refund_release_for_line(api, world["line"]["id"])
    assert_pct_equals(release["restocking_fee_pct"], 0.05, "restocking_fee_pct")
    assert_money(release["restocking_fee_cents"], 1000, "restocking_fee_cents")
    assert_money(release["net_refund_cents"], 19000, "net_refund_cents")
