"""Hire pricing, the clearinghouse fee and the two-variant statement.

Every case here drives the money chain end to end: elapsed hours to chargeable
hours to whole days to tiered cents, mileage rounded once per segment, and the
fee selected from the pre-fee basis.
"""

import pytest

from test_helpers import (
    AUGUST_BOOTSTRAP,
    BACK_76H,
    OUT_76H,
    ApiClient,
    allow_reclaim,
    assert_hours,
    assert_instant_equals,
    assert_money,
    closed_movement_of,
    computed_cycle,
    deliver_back,
    deliver_out,
    exchanged_cycle,
    file_dispute,
    file_reclaim,
    read_cycle,
    read_movement,
    register_car,
    set_clock,
    standard_world,
    submitted_repair_bill,
    three_line_world,
    validate_success,
)
import test_helpers.factories as f


class TestTimeComponentOrdering:
    """Free time comes off the hours, and only then do the hours become days."""

    def test_seventy_six_hour_segment_bills_three_days_not_four(self, api: ApiClient):
        """A 76.00-hour segment prices at 72.00 chargeable hours, 3 days and 7800 cents.

        PRD: "Free time is deducted from **hours** before any conversion to days: a segment of exactly 76.00 elapsed hours on a car type with 4 free hours bills three days, because 72.00 chargeable hours divided by 24 and rounded up is 3, and not four days as it would be if the free hours were deducted after the day count."

        Design: Difficulty/combinatorial_formula/hire_time_component_requires_free_time_subtraction_before_day_ceiling
        """
        world = standard_world(api, bootstrap_clock=AUGUST_BOOTSTRAP)
        deliver_out(api, world, world.car, OUT_76H, 12000)
        deliver_back(api, world, world.car, BACK_76H, 12415)
        movement = closed_movement_of(api, world.car, world.bn,
                                     world.accountant(world.bn))

        assert_instant_equals(movement["start_at"], OUT_76H, "start_at")
        assert_instant_equals(movement["end_at"], BACK_76H, "end_at")
        assert_hours(movement["chargeable_hours"], 72.00, "chargeable_hours")
        assert movement["chargeable_days"] == 3
        assert_money(movement["time_component_cents"], 7800, "time_component_cents")
        assert movement["time_component_cents"] != 10900
        assert_money(movement["mileage_component_cents"], 975, "mileage_component_cents")
        assert_money(movement["gross_hire_cents"], 8775, "gross_hire_cents")
        assert_money(movement["net_hire_cents"], 8775, "net_hire_cents")
        assert movement["status"] == "CLOSED"

    def test_long_segment_splits_across_the_two_per_diem_tiers(self, api: ApiClient):
        """172.00 elapsed hours give 168.00 chargeable hours, 7 days and 2x2350 + 5x3100.

        PRD: "The tier is **marginal, not flat**: the number of days billed at `per_diem_rate_cents` is the lesser of `chargeable_days` and `tier2_threshold_days`, the number billed at `tier2_per_diem_rate_cents` is `chargeable_days` minus `tier2_threshold_days` floored at zero, and `time_component_cents` is the sum of those two products."

        Design: Difficulty/combinatorial_formula/hire_time_component_requires_free_time_subtraction_before_day_ceiling
        """
        world = standard_world(api, bootstrap_clock="2026-08-19T00:00:00Z")
        deliver_out(api, world, world.car, "2026-08-20T00:00:00Z", 12000)
        deliver_back(api, world, world.car, "2026-08-27T04:00:00Z", 12000)
        movement = closed_movement_of(api, world.car, world.bn,
                                     world.accountant(world.bn))

        assert_hours(movement["chargeable_hours"], 168.00, "chargeable_hours")
        assert movement["chargeable_days"] == 7
        assert_money(movement["time_component_cents"], 20200, "time_component_cents")
        assert movement["time_component_cents"] != 23300
        assert_money(movement["mileage_component_cents"], 0, "mileage_component_cents")
        assert_money(movement["gross_hire_cents"], 20200, "gross_hire_cents")


class TestMileageRoundsOncePerSegment:
    """Two lines of 415 and 227 miles must report 1508 cents, never 1509."""

    def test_two_lines_round_per_segment_then_sum_to_14008(self, api: ApiClient):
        """The stored cycle reports 14008 of gross hire, a fee of 70 and 13938 net.

        PRD: "Rounding per line and then summing is normative and is observably different from summing and then rounding: at a rate of 2350 millicents per mile, a 415-mile segment prices at 975.25 cents and rounds to 975, a 227-mile segment prices at 533.45 cents and rounds to 533, and a cycle containing both must report 1508 cents of mileage — not the 1509 that an implementation accumulating exact millicents across lines and rounding at the end would produce."

        Design: Difficulty/combinatorial_formula/mileage_component_rounds_per_movement_then_sums_not_sum_then_rounds
        """
        world, cars, movements = three_line_world(api, cars=2)
        car1, car2 = cars

        assert movements[car1]["end_odometer_miles"] - movements[car1]["start_odometer_miles"] == 415
        assert_money(movements[car1]["mileage_component_cents"], 975, "car1 mileage")
        assert movements[car2]["end_odometer_miles"] - movements[car2]["start_odometer_miles"] == 227
        assert_money(movements[car2]["mileage_component_cents"], 533, "car2 mileage")

        cycle, computed = computed_cycle(api, world)
        assert computed["movement_line_count"] == 2
        assert_money(computed["gross_hire_cents"], 14008, "gross_hire_cents")
        assert computed["gross_hire_cents"] != 14009
        assert_money(computed["pre_fee_net_cents"], 14008, "pre_fee_net_cents")
        assert_money(computed["clearinghouse_fee_cents"], 70, "clearinghouse_fee_cents")
        assert_money(computed["net_settlement_cents"], 13938, "net_settlement_cents")

    def test_statement_read_applies_the_same_per_segment_rounding(self, api: ApiClient):
        """The computed statement read reports the same 1508 cents of mileage as the cycle.

        PRD: "`mileage_component_cents` is billable miles multiplied by `mileage_rate_millicents_per_mile`, divided by 1000 to convert millicents to cents, and rounded half up — **once per segment**."

        Design: Difficulty/combinatorial_formula/mileage_component_rounds_per_movement_then_sums_not_sum_then_rounds
        """
        world, cars, movements = three_line_world(api, cars=2)
        cycle, computed = computed_cycle(api, world)

        statement = validate_success(
            api.get_settlement_statement(cycle["id"], world.accountant(world.cx))
        )
        assert statement["movement_line_count"] == 2
        assert_money(statement["gross_hire_cents"], 14008, "statement gross_hire_cents")
        assert statement["gross_hire_cents"] != 14009
        time_total = sum(movements[c]["time_component_cents"] for c in cars)
        assert_money(time_total, 12500, "summed time components")
        assert statement["gross_hire_cents"] - time_total == 1508


class TestFeeBasisIsPreFeeNet:
    """The fee is keyed on the net after credits, never on the gross hire."""

    def test_reclaim_credit_moves_the_fee_off_the_gross_figure(self, api: ApiClient):
        """A 3900 reclaim credit drops the fee from 94 to 74 on unchanged 18708 gross.

        PRD: "Its basis is the absolute value of `pre_fee_net_cents` — the net *before* the fee, never `net_settlement_cents`, since feeding the post-fee figure back would be circular."

        Design: Difficulty/combinatorial_formula/clearinghouse_fee_keyed_on_pre_fee_net_not_gross_hire
        """
        world, cars, movements = three_line_world(api, cars=3, bad_order_car1=True)
        car1 = cars[0]

        claim = file_reclaim(api, world, movements[car1], "BAD_ORDER",
                            "2026-08-27T00:00:00Z", "2026-08-28T12:00:00Z")
        allowed = allow_reclaim(api, world, claim)
        assert_money(allowed["credit_cents"], 3900, "credit_cents")

        cycle, computed = computed_cycle(api, world)
        assert computed["movement_line_count"] == 3
        assert_money(computed["gross_hire_cents"], 18708, "gross_hire_cents")
        assert_money(computed["reclaim_credit_cents"], 3900, "reclaim_credit_cents")
        assert_money(computed["pre_fee_net_cents"], 14808, "pre_fee_net_cents")
        assert_money(computed["clearinghouse_fee_cents"], 74, "clearinghouse_fee_cents")
        assert computed["clearinghouse_fee_cents"] != 94
        assert_money(computed["net_settlement_cents"], 14734, "net_settlement_cents")

    def test_same_gross_with_no_credit_charges_the_published_ninety_four(self, api: ApiClient):
        """With no reclaim the same 18708 of gross hire yields the fee of 94.

        PRD: "Ordinary tier-one cases round half up in the usual way: 18708 yields 94, 14008 yields 70, 8035 yields 40 from 40.175, and 3906 yields 20 from 19.53."

        Design: Difficulty/combinatorial_formula/clearinghouse_fee_keyed_on_pre_fee_net_not_gross_hire
        """
        world, cars, movements = three_line_world(api, cars=3)
        nets = sorted(movements[c]["net_hire_cents"] for c in cars)
        assert nets == [4700, 5233, 8775]

        cycle, computed = computed_cycle(api, world)
        assert_money(computed["gross_hire_cents"], 18708, "gross_hire_cents")
        assert_money(computed["reclaim_credit_cents"], 0, "reclaim_credit_cents")
        assert_money(computed["pre_fee_net_cents"], 18708, "pre_fee_net_cents")
        assert_money(computed["clearinghouse_fee_cents"], 94, "clearinghouse_fee_cents")
        assert_money(computed["net_settlement_cents"], 18614, "net_settlement_cents")


class TestStatementVariantsDiverge:
    """One accepted dispute makes the two statement variants differ by 4676."""

    def test_as_reported_and_reconciled_reads_differ_by_four_six_seven_six(self, api: ApiClient):
        """AS_REPORTED remits 18614 while RECONCILED remits 13938 on the same cycle.

        PRD: "Three member segments netting 8775, 5233 and 4700 with no repair bills give an `AS_REPORTED` `pre_fee_net_cents` of 18708, a fee of 94 and a `net_settlement_cents` of 18614; after a dispute on the 4700 line is accepted at its full 4700, `dispute_adjustment_cents` is -4700, `pre_fee_net_cents` is 14008, the fee is 70 and the remittance is 13938 — a movement of 4676, not 4700."

        Design: Difficulty/dual_variant_calc/settlement_statement_as_reported_vs_reconciled_diverge_by_4676
        """
        world, cars, movements = three_line_world(api, cars=3)
        target = next(c for c in cars if movements[c]["net_hire_cents"] == 4700)
        cycle, computed, exchanged = exchanged_cycle(api, world)

        dispute = file_dispute(api, world, exchanged, "HIRE_RATE_MISAPPLIED", 4700,
                              movement_id=movements[target]["id"])
        validate_success(api.accept_dispute(dispute["id"], {},
                                           world.accountant(world.cx)))

        as_reported = validate_success(api.get_settlement_statement(
            cycle["id"], world.accountant(world.cx), params={"variant": "AS_REPORTED"}))
        reconciled = validate_success(api.get_settlement_statement(
            cycle["id"], world.accountant(world.cx), params={"variant": "RECONCILED"}))

        assert as_reported["variant_applied"] == "AS_REPORTED"
        assert_money(as_reported["dispute_adjustment_cents"], 0, "as-reported adjustment")
        assert_money(as_reported["pre_fee_net_cents"], 18708, "as-reported pre_fee")
        assert_money(as_reported["clearinghouse_fee_cents"], 94, "as-reported fee")
        assert_money(as_reported["net_settlement_cents"], 18614, "as-reported net")

        assert reconciled["variant_applied"] == "RECONCILED"
        assert_money(reconciled["dispute_adjustment_cents"], -4700, "reconciled adjustment")
        assert_money(reconciled["pre_fee_net_cents"], 14008, "reconciled pre_fee")
        assert_money(reconciled["clearinghouse_fee_cents"], 70, "reconciled fee")
        assert_money(reconciled["net_settlement_cents"], 13938, "reconciled net")

        assert as_reported["net_settlement_cents"] - reconciled["net_settlement_cents"] == 4676

    def test_stored_cycle_retains_both_variant_figures(self, api: ApiClient):
        """The cycle keeps 18614 as reported alongside 13938 reconciled.

        PRD: "Under `RECONCILED` — used once at least one dispute on the cycle is `ACCEPTED` — it contributes its `adjusted_net_hire_cents` instead."

        Design: Difficulty/dual_variant_calc/settlement_statement_as_reported_vs_reconciled_diverge_by_4676
        """
        world, cars, movements = three_line_world(api, cars=3)
        target = next(c for c in cars if movements[c]["net_hire_cents"] == 4700)
        cycle, computed, exchanged = exchanged_cycle(api, world)
        assert_money(exchanged["as_reported_net_cents"], 18614, "as_reported_net_cents")

        dispute = file_dispute(api, world, exchanged, "HIRE_RATE_MISAPPLIED", 4700,
                              movement_id=movements[target]["id"])
        validate_success(api.accept_dispute(dispute["id"], {},
                                           world.accountant(world.cx)))

        stored = read_cycle(api, world, cycle["id"])
        assert stored["status"] == "EXCHANGED"
        assert stored["variant_applied"] == "RECONCILED"
        assert_money(stored["as_reported_net_cents"], 18614, "as_reported_net_cents")
        assert_money(stored["reconciled_net_cents"], 13938, "reconciled_net_cents")
        assert_money(stored["dispute_adjustment_cents"], -4700, "dispute_adjustment_cents")
        assert_money(stored["net_settlement_cents"], 13938, "net_settlement_cents")

        line = read_movement(api, world, movements[target]["id"])
        assert_money(line["net_hire_cents"], 4700, "net_hire_cents")
        assert_money(line["adjusted_net_hire_cents"], 0, "adjusted_net_hire_cents")


class TestRepairResponsibilityRules:
    """The two responsibility rules select different roads from identical figures."""

    def test_owner_rule_and_handling_rule_pick_different_responsible_roads(self, api: ApiClient):
        """NORMAL_WEAR lands on owner CX for 48644 while HANDLING_DAMAGE lands on BN for 45250.

        PRD: "Under the `OWNER_RESPONSIBILITY_RULE`, used when `defect_class` is `NORMAL_WEAR` or `OWNER_APPLIANCE_DEFECT`, custody is irrelevant and `responsible_road_id` is simply the car's `owner_road_id`, because ordinary wear and owner-supplied appliances stay with the owner however far the car has travelled."

        Design: Difficulty/dual_variant_calc/repair_responsibility_handling_line_vs_owner_rule_picks_different_road
        """
        world = standard_world(api)
        second = register_car(api, "CX 100002", world.xm, world.cx, world=world)
        deliver_out(api, world, world.car, "2026-08-24T00:00:00Z", 1000)
        deliver_out(api, world, second, "2026-08-24T00:00:00Z", 2000)
        set_clock(api, "2026-08-26T12:00:00Z", world)
        for car_id in (world.car, second):
            validate_success(api.report_bad_order(
                car_id, f.bad_order_payload("2026-08-26T12:00:00Z"),
                world.clerk(world.bn)))
        set_clock(api, "2026-08-27T00:00:00Z", world)

        _, wear = submitted_repair_bill(api, world, world.car, world.bn, "NORMAL_WEAR",
                                       "2026-08-26T12:00:00Z", 3.5, 12000)
        _, handling = submitted_repair_bill(api, world, second, world.bn,
                                          "HANDLING_DAMAGE", "2026-08-26T12:00:00Z",
                                          3.5, 12000)

        assert wear["responsibility_rule_applied"] == "OWNER_RESPONSIBILITY_RULE"
        assert wear["responsible_road_id"] == world.cx
        assert_money(wear["labor_cents"], 33250, "labor_cents")
        assert_money(wear["subtotal_cents"], 45250, "subtotal_cents")
        assert_money(wear["handling_fee_cents"], 3394, "handling_fee_cents")
        assert_money(wear["total_cents"], 48644, "total_cents")

        assert handling["responsibility_rule_applied"] == "HANDLING_LINE_RULE"
        assert handling["responsible_road_id"] == world.bn
        assert_money(handling["labor_cents"], 33250, "labor_cents")
        assert_money(handling["subtotal_cents"], 45250, "subtotal_cents")
        assert_money(handling["handling_fee_cents"], 0, "handling_fee_cents")
        assert_money(handling["total_cents"], 45250, "total_cents")

        assert wear["responsible_road_id"] != handling["responsible_road_id"]
        assert wear["total_cents"] - handling["total_cents"] == 3394

    @pytest.mark.parametrize(
        "defect_class,expected_rule,expected_fee,expected_total",
        [
            ("HANDLING_DAMAGE", "HANDLING_LINE_RULE", 0, 45250),
            ("NORMAL_WEAR", "OWNER_RESPONSIBILITY_RULE", 3394, 48644),
            ("OWNER_APPLIANCE_DEFECT", "OWNER_RESPONSIBILITY_RULE", 3394, 48644),
        ],
    )
    def test_handling_fee_follows_the_selected_responsible_road(
        self, api: ApiClient, defect_class, expected_rule, expected_fee, expected_total
    ):
        """A bill of 3.50 hours and 12000 material totals 45250 or 48644 by defect class.

        PRD: "For 3.50 labor hours and 12000 material cents billed to another road: labor 33250, subtotal 45250, handling fee 3394 from 3393.75 rounded half up, total 48644 — and the identical bill where the responsible road is the billing road has a handling fee of 0 and a total of 45250."

        Design: Difficulty/dual_variant_calc/repair_responsibility_handling_line_vs_owner_rule_picks_different_road
        """
        world = standard_world(api)
        deliver_out(api, world, world.car, "2026-08-24T00:00:00Z", 1000)
        set_clock(api, "2026-08-26T12:00:00Z", world)
        validate_success(api.report_bad_order(
            world.car, f.bad_order_payload("2026-08-26T12:00:00Z"),
            world.clerk(world.bn)))
        set_clock(api, "2026-08-27T00:00:00Z", world)

        _, bill = submitted_repair_bill(api, world, world.car, world.bn, defect_class,
                                       "2026-08-26T12:00:00Z", 3.5, 12000)

        assert bill["responsibility_rule_applied"] == expected_rule
        assert bill["billing_road_id"] == world.bn
        expected_road = world.bn if expected_rule == "HANDLING_LINE_RULE" else world.cx
        assert bill["responsible_road_id"] == expected_road
        assert_money(bill["subtotal_cents"], 45250, "subtotal_cents")
        assert_money(bill["handling_fee_cents"], expected_fee, "handling_fee_cents")
        assert_money(bill["total_cents"], expected_total, "total_cents")
