"""Exact-tie boundaries: the liquidation floor, the exposure cap, the empty box."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_REFUND_EXCEEDS_EXPOSURE_CAP
from test_helpers.assertions import (
    assert_line_states,
    assert_money,
    assert_pct_equals,
    entries_of_type,
    plus_hours,
    sole_entry_of_type,
)
from test_helpers.constants import (
    CLIENT_STATUS_ACTIVE,
    CLOCK_STARTUP_INSTANT,
    DISPOSITION_DONATE,
    DISPOSITION_LIQUIDATE,
    DISPOSITION_RESTOCK,
    DS_DISPOSITION_ASSIGNED,
    ENTRY_RECOVERY_CREDIT,
    ENTRY_REFUND_DEBIT,
    FS_HOLD_PENDING_DISPOSITION,
    FS_REFUNDED,
    FS_RELEASE_PENDING,
    GRADE_A,
    GRADE_C,
    REASON_BUYER_REMORSE,
    REASON_DEFECTIVE,
    REASON_WRONG_ITEM,
)
from test_helpers.test_users import ANALYST, CLERK


def _tie_world(api, client_code):
    """Two grade-C lines whose recovery estimates tie and miss the same floor.

    Both items round to a 12000-cent provisional estimate, but the floor product
    is computed from each item's own declared value, so one line ties the floor
    exactly and the other misses it by forty scaled units.
    """
    return fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            client_code,
            name="Boundary One Client",
            liquidation_floor_pct=0.40,
            donation_allowed=True,
        ),
        items=[
            fx.widget_item_kwargs(sku="TIE-30000", declared_value_cents=30000),
            fx.widget_item_kwargs(sku="TIE-30001", declared_value_cents=30001),
        ],
        lines=[
            {
                "item_index": 0,
                "authorized_quantity": 1,
                "reason_code": REASON_BUYER_REMORSE,
            },
            {
                "item_index": 1,
                "authorized_quantity": 1,
                "reason_code": REASON_BUYER_REMORSE,
            },
        ],
        condition_grade=GRADE_C,
    )


def test_an_estimate_that_exactly_ties_the_liquidation_floor_liquidates(api):
    """PRD §3.4: "Otherwise, if the line's `recovery_value_cents` multiplied by
    one hundred is at least the item's `declared_value_cents` multiplied by the
    line's `quantity` multiplied by the client's `liquidation_floor_pct` scaled to
    an integer percentage (that fraction multiplied by one hundred and rounded
    half up), the disposition is `LIQUIDATE`. The comparison is on
    cross-multiplied integers and the floor is deliberately not pre-rounded to
    cents: an estimate that exactly ties the product liquidates, and one scaled
    point below it falls through."

    Design: Difficulty/boundary_precision_check/liquidation_floor_exact_tie_liquidates_one_cent_more_donates
    """
    world = _tie_world(api, "CLBOUND1")
    tie_line = world["lines"][0]

    # round_half_up(30000 * 0.40 * 1.00) is 12000, and 12000 * 100 is exactly
    # 30000 * 1 * 40.
    assert_money(tie_line["recovery_value_cents"], 12000, "recovery_value_cents")
    assert tie_line["recovery_value_cents"] * 100 == 30000 * 1 * 40
    assert_line_states(
        tie_line,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        financial_state=FS_HOLD_PENDING_DISPOSITION,
        disposition=DISPOSITION_LIQUIDATE,
        condition_grade=GRADE_C,
    )


def test_one_cent_of_declared_value_above_the_tie_falls_through_to_donation(api):
    """PRD §3.4: "Otherwise, if the client's `donation_allowed` is true, the
    `condition_grade` is not `SCRAP`, and the item's `regulated_flag` is false,
    the disposition is `DONATE`."

    Design: Difficulty/boundary_precision_check/liquidation_floor_exact_tie_liquidates_one_cent_more_donates
    """
    world = _tie_world(api, "CLBND1B")
    miss_line = world["lines"][1]

    # round_half_up(30001 * 0.40) is still 12000, because 12000.4 rounds down.
    assert_money(miss_line["recovery_value_cents"], 12000, "recovery_value_cents")
    assert miss_line["recovery_value_cents"] * 100 < 30001 * 1 * 40
    assert_line_states(
        miss_line,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        financial_state=FS_HOLD_PENDING_DISPOSITION,
        disposition=DISPOSITION_DONATE,
        condition_grade=GRADE_C,
    )


def test_the_two_lines_share_one_estimate_yet_split_on_the_floor_product(api):
    """PRD §3.4: "Per unit, the estimate is the item's `declared_value_cents`
    multiplied by the grade multiplier for the line's `condition_grade` and then
    by one minus the reason penalty for the line's `reason_code`, with that
    per-unit result rounded half up to a whole cent."

    Design: Difficulty/boundary_precision_check/liquidation_floor_exact_tie_liquidates_one_cent_more_donates
    """
    world = _tie_world(api, "CLBND1C")
    tie_line, miss_line = world["lines"]

    assert tie_line["recovery_value_cents"] == miss_line["recovery_value_cents"], (
        "both items round to the same provisional estimate"
    )
    assert tie_line["disposition"] != miss_line["disposition"], (
        "the floor product, not the estimate, is what separates them"
    )
    assert tie_line["disposition"] == DISPOSITION_LIQUIDATE
    assert miss_line["disposition"] == DISPOSITION_DONATE


def _capped_world(api, client_code):
    """A client whose exposure cap equals its first line's net refund exactly.

    Both lines are dispositioned and executed, then the clock is advanced past
    both 48-hour hold windows so only the cap rule can still refuse a release.
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            client_code, name="Capped Client", max_refund_exposure_cents=18000
        ),
        items=[
            fx.widget_item_kwargs(),
            fx.widget_item_kwargs(
                sku="PENNY-1",
                description="One cent probe item",
                declared_value_cents=1,
                unit_weight_grams=1,
                secondary_market_floor_cents=0,
            ),
        ],
        lines=[
            {
                "item_index": 0,
                "authorized_quantity": 1,
                "reason_code": REASON_DEFECTIVE,
            },
            {
                "item_index": 1,
                "authorized_quantity": 1,
                "reason_code": REASON_WRONG_ITEM,
            },
        ],
        grades=[GRADE_C, GRADE_A],
    )
    world["channel"] = fx.make_channel(api, **fx.auction_channel_kwargs("AUC1"))
    widget_line, penny_line = world["lines"]

    widget_order = fx.propose_and_approve(
        api, widget_line["id"], channel_id=world["channel"]["id"]
    )
    fx.execute_order(api, widget_order["id"])
    # A restock order has no channel and therefore no lot window at all.
    penny_order = fx.propose_and_approve(
        api, penny_line["id"], window_start_at=None, window_end_at=None
    )
    fx.execute_order(api, penny_order["id"])

    fx.set_clock(api, plus_hours(CLOCK_STARTUP_INSTANT, 72))
    world["widget_line"] = widget_line
    world["penny_line"] = penny_line
    return world


def test_a_release_that_exactly_reaches_the_exposure_cap_is_permitted(api):
    """PRD §2.6: "Priority 61 requires that the sum of already-released net
    refunds for the client plus this release not exceed the client's
    `max_refund_exposure_cents`, again allowing exact equality; it guards refund
    release and returns `ERR_REFUND_EXCEEDS_EXPOSURE_CAP`."

    Design: Difficulty/boundary_precision_check/refund_exposure_cap_exact_equality_allowed_one_cent_over_rejected
    """
    world = _capped_world(api, "CLCAP")
    widget_line = world["widget_line"]
    refund = fx.refund_release_for_line(api, widget_line["id"])
    # DEFECTIVE 0.00 + SL_STANDARD 0.00 + grade C 0.10 + no lateness band.
    assert_pct_equals(refund["restocking_fee_pct"], 0.10, "restocking_fee_pct")
    assert_money(refund["net_refund_cents"], 18000, "net_refund_cents")

    validate_success(api.release_refund(widget_line["id"], ANALYST), 200)

    released = fx.read_return_line(api, widget_line["id"])
    assert released["financial_state"] == FS_REFUNDED
    debit = sole_entry_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_REFUND_DEBIT
    )
    assert_money(debit["amount_cents"], -18000, "REFUND_DEBIT amount_cents")


def test_one_cent_beyond_the_exposure_cap_is_refused(api):
    """PRD §3.7: "And the client's cumulative released net refunds plus this one
    must not exceed its `max_refund_exposure_cents`, with exact equality
    permitted, or the refusal is `ERR_REFUND_EXCEEDS_EXPOSURE_CAP`."

    Design: Difficulty/boundary_precision_check/refund_exposure_cap_exact_equality_allowed_one_cent_over_rejected
    """
    world = _capped_world(api, "CLCAP2")
    validate_success(api.release_refund(world["widget_line"]["id"], ANALYST), 200)

    penny_line = world["penny_line"]
    penny_refund = fx.refund_release_for_line(api, penny_line["id"])
    # WRONG_ITEM 0.00 + SL_STANDARD 0.00 + grade A 0.00 + no lateness band.
    assert_pct_equals(penny_refund["restocking_fee_pct"], 0.00, "restocking_fee_pct")
    assert_money(penny_refund["restocking_fee_cents"], 0, "restocking_fee_cents")
    assert_money(penny_refund["net_refund_cents"], 1, "net_refund_cents")

    # 18000 already released plus 1 is 18001, one cent past the cap of 18000.
    response = api.release_refund(penny_line["id"], ANALYST)
    validate_error(response, ERR_REFUND_EXCEEDS_EXPOSURE_CAP, 409)

    after = fx.read_return_line(api, penny_line["id"])
    assert after["financial_state"] == FS_RELEASE_PENDING
    debits = entries_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_REFUND_DEBIT
    )
    assert len(debits) == 1, "only the first release may have written a debit"


def test_the_cap_refusal_is_not_a_suspension_of_the_client(api):
    """PRD §2.10: "The system also suspends automatically: whenever a ledger
    append recomputes `settlement_balance_cents` and the result falls below the
    negation of the client's `max_refund_exposure_cents`, the client moves from
    `ACTIVE` to `SUSPENDED` in the same request."

    Design: Difficulty/boundary_precision_check/refund_exposure_cap_exact_equality_allowed_one_cent_over_rejected
    """
    world = _capped_world(api, "CLCAP3")
    validate_success(api.release_refund(world["widget_line"]["id"], ANALYST), 200)
    validate_error(
        api.release_refund(world["penny_line"]["id"], ANALYST),
        ERR_REFUND_EXCEEDS_EXPOSURE_CAP,
        409,
    )

    credits = entries_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_RECOVERY_CREDIT
    )
    assert len(credits) == 2, f"one credit per executed order, got {len(credits)}"
    assert_money(credits[0]["amount_cents"], 5461, "liquidation RECOVERY_CREDIT")
    assert_money(credits[1]["amount_cents"], 1, "restock RECOVERY_CREDIT")

    client = fx.read_client(api, world["client"]["id"])
    # 5461 + 1 - 18000 is -12538, which is still above the negated 18000 cap.
    assert_money(client["settlement_balance_cents"], -12538, "settlement_balance_cents")
    assert client["status"] == CLIENT_STATUS_ACTIVE, client["status"]

    penny_line = fx.read_return_line(api, world["penny_line"]["id"])
    assert penny_line["disposition"] == DISPOSITION_RESTOCK


def _weight_world(api, client_code):
    """An issued authorization for one 1200-gram unit, with nothing scanned yet."""
    return fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            client_code, name="Weight Boundary Client"
        ),
        items=[
            fx.widget_item_kwargs(
                sku="HEAVY-1", description="Twelve hundred gram item"
            )
        ],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_BUYER_REMORSE}],
        scan=False,
    )


def _scan_carton(api, rma_id, tracking_reference, gross_weight_grams):
    """Scan one carton and assert the create answered 201."""
    response = api.create_receipt(
        f.receipt_payload(
            rma_id,
            tracking_reference=tracking_reference,
            gross_weight_grams=gross_weight_grams,
        ),
        CLERK,
    )
    return validate_success(response, 201)


def test_a_carton_at_exactly_sixty_percent_of_expectation_is_trusted(api):
    """PRD §3.3: "`empty_box_suspected` is then true when the scanned gross
    weight multiplied by one hundred is strictly less than the expected weight
    multiplied by sixty — in other words, when the carton weighs less than sixty
    percent of what it should. The comparison is a strict one on the
    cross-multiplied integers, so a carton weighing exactly sixty percent of
    expectation is **not** suspected."

    Design: Difficulty/boundary_precision_check/empty_box_weight_threshold_exact_sixty_percent_not_suspected
    """
    world = _weight_world(api, "CLWEIGH")
    receipt = _scan_carton(api, world["rma"]["id"], "TRK-15A", 840)

    # 200 grams of tare plus 1200 grams of authorized goods.
    assert receipt["expected_weight_grams"] == 1400, receipt["expected_weight_grams"]
    assert receipt["gross_weight_grams"] == 840
    assert 840 * 100 == 1400 * 60, "the fixture really sits on the boundary"
    assert receipt["empty_box_suspected"] is False, "exactly sixty percent is trusted"


def test_a_carton_one_scaled_point_lighter_is_suspected(api):
    """PRD §3.3: "`empty_box_suspected` is then true when the scanned gross
    weight multiplied by one hundred is strictly less than the expected weight
    multiplied by sixty — in other words, when the carton weighs less than sixty
    percent of what it should."

    Design: Difficulty/boundary_precision_check/empty_box_weight_threshold_exact_sixty_percent_not_suspected
    """
    world = _weight_world(api, "CLWEIGH2")
    receipt = _scan_carton(api, world["rma"]["id"], "TRK-15B", 839)

    assert receipt["expected_weight_grams"] == 1400, receipt["expected_weight_grams"]
    assert 839 * 100 < 1400 * 60
    assert receipt["empty_box_suspected"] is True, "83900 is below 84000"


def test_both_cartons_on_one_authorization_share_the_same_expectation(api):
    """PRD §3.3: "The sum deliberately uses `authorized_quantity` rather than
    `received_quantity` and applies no status filter to the lines, so a second
    partial carton on the same authorization is measured against the same
    whole-authorization expectation."

    Design: Difficulty/boundary_precision_check/empty_box_weight_threshold_exact_sixty_percent_not_suspected
    """
    world = _weight_world(api, "CLWEIGH3")
    first = _scan_carton(api, world["rma"]["id"], "TRK-15A", 840)
    second = _scan_carton(api, world["rma"]["id"], "TRK-15B", 839)

    assert first["expected_weight_grams"] == 1400
    assert second["expected_weight_grams"] == 1400
    assert first["expected_weight_grams"] == second["expected_weight_grams"]
    assert first["empty_box_suspected"] is False
    assert second["empty_box_suspected"] is True
