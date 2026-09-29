"""The settlement waterfall, the discount tiers and contract closure."""
from test_helpers import (
    ApiErrorId,
    assert_money,
    assert_settlement_statement,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _bare_active_agreement(api, per_acre_annual_fee=950.00, contracted_acres=15.0,
                           period_overhead_pool=1000.00, block_code="B-30",
                           vineyard_name="Ridgecrest Ranch", acres=15.0):
    """One ranch, one enrolled block, an `ACTIVE` agreement and no activity."""
    ranch = fx.create_vineyard(api, name=vineyard_name)
    block = fx.create_block(api, ranch["id"], block_code=block_code,
                            vine_spacing_ft=6.0, row_spacing_ft=10.0, acres=acres)
    contract = fx.create_contract(api, ranch["id"],
                                  per_acre_annual_fee=per_acre_annual_fee,
                                  period_overhead_pool=period_overhead_pool)
    fx.enroll_block(api, contract["id"], block["id"], contracted_acres)
    contract = fx.activate_contract(api, contract["id"], ranch["id"])
    return fx.Scenario(vineyard=ranch, block=fx.read_block(api, block["id"]),
                       contract=contract)


class TestClosureIsTerminalForSettlement:
    """PRD §3.9 — a closed agreement cannot be settled again."""

    def test_settling_a_closed_agreement_is_refused(self, api):
        """The agreement must be `ACTIVE`; running a settlement against one still in `DRAFT` or already `CLOSED` is refused with `ERR_CONTRACT_NOT_ACTIVE`.

        Design: Corner/state_machines/contract_settle_after_close_returns_contract_not_active
        """
        s = fx.setup_approved_plan(api)

        statement = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")
        assert_settlement_statement(statement)
        assert_money(statement["total_billable"], 11955.00, "total_billable")
        assert statement["contract_status"] == "CLOSED"

        validate_error(
            api.settle_period(s.contract["id"],
                              f.settle_period_payload("FINAL", "2026-12-31"),
                              fx.CTL),
            ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
        )

        contract = fx.read_contract(api, s.contract["id"])
        assert contract["contract_status"] == "CLOSED"
        assert contract["settled_period_count"] == 1
        assert_money(contract["last_settlement_total"], 11955.00,
                     "last_settlement_total")


class TestBillableActivityIsStateFiltered:
    """PRD §3.9 — only finished work, applied material and applied water bill."""

    def test_cancelled_labor_and_unfinished_activity_never_reach_the_client(self, api):
        """Its labor is the sum of `actual_labor_cost` over that block's work orders whose `execution_status` is `COMPLETED` — a cancelled order's reporting-time pay is a cost the farming company bears and never reaches the client.

        Design: Corner/calculations/settlement_direct_cost_excludes_cancelled_recommended_and_scheduled_activity
        """
        s = fx.setup_operational_block(api)

        finished = fx.create_work_order(api, s.block["id"], s.plan["id"],
                                        s.crew["id"], planned_vines=5200,
                                        planned_hours=12.0)
        fx.start_work_order(api, finished["id"], s.crew["id"])
        finished = fx.complete_work_order(api, finished["id"], s.crew["id"],
                                          5200, 12.0)
        assert_money(finished["actual_labor_cost"], 4343.30, "actual_labor_cost")

        abandoned = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="SUCKERING",
            scheduled_start="2026-08-06T06:00:00Z",
            scheduled_end="2026-08-06T14:00:00Z",
            planned_vines=3000, planned_hours=8.0,
        )
        fx.start_work_order(api, abandoned["id"], s.crew["id"])
        abandoned = fx.cancel_work_order(api, abandoned["id"], "WEATHER")
        assert_money(abandoned["actual_labor_cost"], 1017.72, "actual_labor_cost")

        s = fx.setup_recommended_spray(api, s)
        assert s.spray["spray_status"] == "RECOMMENDED"
        scheduled_water = fx.create_irrigation_event(api, s.block["id"],
                                                     s.plan["id"])
        assert scheduled_water["irrigation_status"] == "SCHEDULED"

        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 5361.02,
                     "committed_cost")

        statement = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")
        assert_settlement_statement(statement)
        assert_money(statement["direct_cost_total"], 5343.30, "direct_cost_total")
        assert_money(statement["management_fee_base"], 11875.00,
                     "management_fee_base")
        assert_money(statement["pass_through"], 427.46, "pass_through")
        assert_money(statement["tier_basis"], 12302.46, "tier_basis")
        assert statement["volume_discount_pct"] == 0.00
        assert_money(statement["volume_discount"], 0.00, "volume_discount")
        assert_money(statement["quality_incentive"], 0.00, "quality_incentive")
        assert_money(statement["total_billable"], 12302.46, "total_billable")
        assert statement["contract_status"] == "CLOSED"


class TestVolumeDiscountTiers:
    """PRD §3.9 — the rate is selected from the pre-discount basis."""

    def test_the_three_percent_tier_attaches_at_exactly_fifteen_thousand(self, api):
        """From `tier_basis` the volume discount rate is selected: `volume_discount_pct` is 0.00 when `tier_basis` is below 15,000, 0.03 when it is at least 15,000 but below 20,000, and 0.05 when it reaches 20,000.

        Design: Corner/calculations/settlement_volume_discount_tier_boundary_at_tier_1_floor
        """
        at_floor = _bare_active_agreement(api, period_overhead_pool=9375.00,
                                          vineyard_name="Ridgecrest Ranch")
        one_cent_under = _bare_active_agreement(api, period_overhead_pool=9374.90,
                                                vineyard_name="Highland Bench Ranch")

        top = fx.settle_period(api, at_floor.contract["id"], "FINAL", "2026-12-31")
        assert_settlement_statement(top)
        assert_money(top["direct_cost_total"], 9375.00, "direct_cost_total")
        assert_money(top["pass_through"], 750.00, "pass_through")
        assert_money(top["management_fee_base"], 14250.00, "management_fee_base")
        assert_money(top["tier_basis"], 15000.00, "tier_basis")
        assert top["volume_discount_pct"] == 0.03
        assert_money(top["volume_discount"], 427.50, "volume_discount")
        assert_money(top["total_billable"], 14572.50, "total_billable")

        below = fx.settle_period(api, one_cent_under.contract["id"], "FINAL",
                                 "2026-12-31")
        assert_settlement_statement(below)
        assert_money(below["direct_cost_total"], 9374.90, "direct_cost_total")
        assert_money(below["pass_through"], 749.99, "pass_through")
        assert_money(below["tier_basis"], 14999.99, "tier_basis")
        assert below["volume_discount_pct"] == 0.00
        assert_money(below["volume_discount"], 0.00, "volume_discount")
        assert_money(below["total_billable"], 14999.99, "total_billable")

        for scenario in (at_floor, one_cent_under):
            contract = fx.read_contract(api, scenario.contract["id"])
            assert contract["contract_status"] == "CLOSED"
            assert contract["settled_period_count"] == 1


class TestSettlementAuthority:
    """PRD §3.9 — the invoice belongs to the `Controller` alone."""

    def test_the_vineyard_manager_may_not_run_a_settlement(self, api):
        """Settlement is the `Controller`'s exclusive act, and it is where the whole season is converted into one invoice.

        Design: Corner/rbac/settle_period_forbidden_for_every_role_but_controller
        """
        s = fx.setup_approved_plan(api)

        validate_error(
            api.settle_period(s.contract["id"],
                              f.settle_period_payload("PROVISIONAL", "2026-08-31"),
                              fx.VM),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        )
        assert fx.read_contract(api, s.contract["id"])["settled_period_count"] == 0

        statement = validate_success(
            api.settle_period(s.contract["id"],
                              f.settle_period_payload("PROVISIONAL", "2026-08-31"),
                              fx.CTL)
        )
        assert_settlement_statement(statement)
        assert_money(statement["direct_cost_total"], 1000.00, "direct_cost_total")
        assert_money(statement["management_fee_base"], 11875.00,
                     "management_fee_base")
        assert_money(statement["pass_through"], 40.00, "pass_through")
        assert_money(statement["tier_basis"], 11915.00, "tier_basis")
        assert statement["volume_discount_pct"] == 0.00
        assert_money(statement["volume_discount"], 0.00, "volume_discount")
        assert_money(statement["quality_incentive"], 0.00, "quality_incentive")
        assert_money(statement["total_billable"], 11915.00, "total_billable")
        assert statement["contract_status"] == "ACTIVE"

        contract = fx.read_contract(api, s.contract["id"])
        assert contract["contract_status"] == "ACTIVE"
        assert contract["settled_period_count"] == 1
        assert_money(contract["last_settlement_total"], 11915.00,
                     "last_settlement_total")


class TestTheTwoSettlementModes:
    """PRD §3.9 — one stored season, two invoices."""

    def test_a_provisional_run_halves_the_pass_through_and_defers_the_incentive(self, api):
        """`pass_through` is `direct_cost_total` multiplied by the agreement's `cost_pass_through_pct` and multiplied again by the share the mode selects, rounded to two decimal places: a `FINAL` settlement passes through the full amount, while a `PROVISIONAL` settlement passes through exactly half of it, since an interim invoice should not front-load the client with costs the period may yet revise.

        Design: Difficulty/dual_variant_calc/contract_settlement_provisional_vs_final_divergence
        """
        s = fx.setup_settlement_scenario(api)
        assert_money(s.contract["accrued_quality_incentive"], 558.00,
                     "accrued_quality_incentive")

        interim = fx.settle_period(api, s.contract["id"], "PROVISIONAL",
                                   "2026-09-30")

        assert_settlement_statement(interim)
        assert_money(interim["direct_cost_total"], 6628.29, "direct_cost_total")
        assert_money(interim["management_fee_base"], 19095.00,
                     "management_fee_base")
        assert_money(interim["pass_through"], 265.13, "pass_through")
        assert_money(interim["tier_basis"], 19360.13, "tier_basis")
        assert interim["volume_discount_pct"] == 0.03
        assert_money(interim["volume_discount"], 572.85, "volume_discount")
        assert_money(interim["quality_incentive"], 0.00, "quality_incentive")
        assert_money(interim["total_billable"], 18787.28, "total_billable")
        assert interim["contract_status"] == "ACTIVE"

    def test_the_final_run_bills_eight_hundred_and_twenty_three_more(self, api):
        """With a `management_fee_base` of 19,095.00, a `direct_cost_total` of 6,628.29, a `cost_pass_through_pct` of 0.08 and an `accrued_quality_incentive` of 558.00, a `FINAL` run passes through 530.26, giving a `tier_basis` of 19,625.26, a `volume_discount_pct` of 0.03, a `volume_discount` of 572.85 and a `total_billable` of 19,610.41.

        Design: Difficulty/dual_variant_calc/contract_settlement_provisional_vs_final_divergence
        """
        s = fx.setup_settlement_scenario(api)

        interim = fx.settle_period(api, s.contract["id"], "PROVISIONAL",
                                   "2026-09-30")
        closing = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")

        assert_settlement_statement(closing)
        assert_money(closing["direct_cost_total"], 6628.29, "direct_cost_total")
        assert_money(closing["pass_through"], 530.26, "pass_through")
        assert_money(closing["tier_basis"], 19625.26, "tier_basis")
        assert closing["volume_discount_pct"] == 0.03
        assert_money(closing["volume_discount"], 572.85, "volume_discount")
        assert_money(closing["quality_incentive"], 558.00, "quality_incentive")
        assert_money(closing["total_billable"], 19610.41, "total_billable")
        assert closing["contract_status"] == "CLOSED"

        assert_money(closing["total_billable"] - interim["total_billable"], 823.13,
                     "settlement divergence")

        contract = fx.read_contract(api, s.contract["id"])
        assert contract["settled_period_count"] == 2
        assert_money(contract["last_settlement_total"], 19610.41,
                     "last_settlement_total")
        assert_money(contract["accrued_quality_incentive"], 558.00,
                     "accrued_quality_incentive")


class TestDirectCostRoundsAtTheBlock:
    """PRD §2.7 and §3.9 — the rounding boundary sits at the block."""

    def test_the_overhead_shares_are_rounded_block_by_block(self, api):
        """Those four quantities are added and the block's subtotal rounded to two decimal places, and only then does the subtotal join `direct_cost_total`; the running total is not re-rounded at the end.

        Design: Difficulty/combinatorial_formula/settlement_direct_cost_rounds_per_block_before_summing
        """
        s = fx.setup_settlement_scenario(api, include_received_load=False)
        assert_money(s.contract["total_contracted_acres"], 20.1,
                     "total_contracted_acres")
        assert_money(s.contract["accrued_quality_incentive"], 0.00,
                     "accrued_quality_incentive")

        statement = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")

        assert_settlement_statement(statement)
        assert_money(statement["direct_cost_total"], 6628.29, "direct_cost_total")
        assert_money(statement["management_fee_base"], 19095.00,
                     "management_fee_base")

    def test_summing_the_raw_shares_first_would_bill_one_cent_more(self, api):
        """Summing the raw values first and rounding once at the end would give 6,628.30, and that one cent is a divergence the settlement must not produce.

        Design: Difficulty/combinatorial_formula/settlement_direct_cost_rounds_per_block_before_summing
        """
        s = fx.setup_settlement_scenario(api, include_received_load=False)

        statement = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")

        assert_money(statement["direct_cost_total"], 6628.29, "direct_cost_total")
        assert abs(statement["direct_cost_total"] - 6628.30) > 0.005, (
            "direct_cost_total must not be the sum-then-round figure 6628.30"
        )
        assert_money(statement["pass_through"], 530.26, "pass_through")
        assert_money(statement["tier_basis"], 19625.26, "tier_basis")
        assert statement["volume_discount_pct"] == 0.03
        assert_money(statement["volume_discount"], 572.85, "volume_discount")
        assert_money(statement["quality_incentive"], 0.00, "quality_incentive")
        assert_money(statement["total_billable"], 19052.41, "total_billable")
        assert statement["contract_status"] == "CLOSED"


class TestTierBasisExcludesTheIncentive:
    """PRD §3.9 — the tier is keyed on cost, never on the quality bonus."""

    def test_the_incentive_stays_out_of_the_tier_basis(self, api):
        """`tier_basis` is `management_fee_base` plus that already-rounded `pass_through`, rounded to two decimal places — and it deliberately excludes both the volume discount, which has not been computed yet, and the quality incentive, which is not a cost at all.

        Design: Difficulty/combinatorial_formula/settlement_tier_keyed_on_prediscount_basis_excluding_incentive
        """
        s = fx.setup_settlement_scenario(api)
        assert_money(s.load["net_tons"], 12.40, "net_tons")
        assert_money(s.load["quality_incentive_amount"], 558.00,
                     "quality_incentive_amount")

        statement = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")

        assert_settlement_statement(statement)
        assert_money(statement["management_fee_base"], 19095.00,
                     "management_fee_base")
        assert_money(statement["pass_through"], 530.26, "pass_through")
        assert_money(statement["tier_basis"], 19625.26, "tier_basis")
        assert statement["volume_discount_pct"] == 0.03
        assert_money(statement["quality_incentive"], 558.00, "quality_incentive")

    def test_the_discount_is_taken_on_the_management_fee_base_alone(self, api):
        """`volume_discount` is then that rate applied to `management_fee_base` alone — never to `tier_basis` — rounded to two decimal places.

        Design: Difficulty/combinatorial_formula/settlement_tier_keyed_on_prediscount_basis_excluding_incentive
        """
        s = fx.setup_settlement_scenario(api)

        statement = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")

        assert_money(statement["volume_discount"], 572.85, "volume_discount")
        assert abs(statement["volume_discount"] - 954.75) > 0.005, (
            "the quality incentive must not lift the tier basis into the 0.05 band"
        )
        assert abs(statement["volume_discount"] - 588.76) > 0.005, (
            "the discount rate applies to the management fee base, not the tier basis"
        )
        assert_money(statement["total_billable"], 19610.41, "total_billable")


class TestSettlementOverAnEmptySeason:
    """PRD §3.9 — a wholly inactive agreement still settles cleanly."""

    def test_an_agreement_with_no_activity_bills_only_its_management_fee(self, api):
        """At the small end, an agreement with a single enrolled 5.0-acre block, a `period_overhead_pool` of 0.00 and no activity at all settles to a `direct_cost_total` of 0.00, a `pass_through` of 0.00, a `management_fee_base` of 4,750.00, a `tier_basis` of 4,750.00, a `volume_discount_pct` of 0.00 and a `total_billable` of 4,750.00.

        Design: Difficulty/boundary_precision_check/settlement_over_empty_activity_set_yields_zero_direct_cost
        """
        s = _bare_active_agreement(api, period_overhead_pool=0.00,
                                   contracted_acres=5.0, block_code="B-20",
                                   acres=5.0)

        statement = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")

        assert_settlement_statement(statement)
        assert_money(statement["direct_cost_total"], 0.00, "direct_cost_total")
        assert_money(statement["pass_through"], 0.00, "pass_through")
        assert_money(statement["management_fee_base"], 4750.00,
                     "management_fee_base")
        assert_money(statement["tier_basis"], 4750.00, "tier_basis")
        assert statement["volume_discount_pct"] == 0.00

    def test_an_empty_activity_set_settles_without_an_error(self, api):
        """An enrolled block with no qualifying activity still absorbs its overhead share, and a wholly inactive agreement with a `period_overhead_pool` of 0.00 settles to a `direct_cost_total` of 0.00 rather than an error.

        Design: Difficulty/boundary_precision_check/settlement_over_empty_activity_set_yields_zero_direct_cost
        """
        s = _bare_active_agreement(api, period_overhead_pool=0.00,
                                   contracted_acres=5.0, block_code="B-20",
                                   acres=5.0)
        assert_money(s.contract["total_contracted_acres"], 5.0,
                     "total_contracted_acres")

        statement = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")

        assert_money(statement["volume_discount"], 0.00, "volume_discount")
        assert_money(statement["quality_incentive"], 0.00, "quality_incentive")
        assert_money(statement["total_billable"], 4750.00, "total_billable")
        assert statement["contract_status"] == "CLOSED"

        contract = fx.read_contract(api, s.contract["id"])
        assert contract["settled_period_count"] == 1
        assert_money(contract["last_settlement_total"], 4750.00,
                     "last_settlement_total")
        assert_money(contract["total_contracted_acres"], 5.0,
                     "total_contracted_acres")


class TestClosureReachesTheHarvestDesk:
    """PRD §3.8 and §3.9 — the booking gauntlet reads a state two hops away."""

    def test_a_closed_agreement_blocks_every_further_booking(self, api):
        """`CLOSED` is terminal, and its most visible downstream consequence is that booking a harvest load against any block enrolled under a closed agreement is thereafter refused with `ERR_CONTRACT_NOT_ACTIVE`.

        Design: Difficulty/cross_entity_state_dependency/harvest_load_refused_after_contract_closed_by_final_settlement
        """
        s = fx.setup_harvest_ready(api)

        statement = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")
        assert statement["contract_status"] == "CLOSED"

        validate_error(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"],
                    fx.window_version(api, s.window["id"]),
                    estimated_tons=12.40,
                    delivery_eta="2026-09-14T09:00:00Z",
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
        )

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 0.00, "committed_tons")
        assert_money(window["remaining_tons"], 40.00, "remaining_tons")
        assert window["window_posture"] == "OPEN"
        assert_money(fx.read_block(api, s.block["id"])["committed_harvest_tons"],
                     0.00, "committed_harvest_tons")

    def test_the_closing_run_leaves_its_figures_on_the_agreement(self, api):
        """Every settlement run, whichever mode it used, increments the agreement's `settled_period_count` by 1, stores its `total_billable` in `last_settlement_total`, and increments the agreement's `version` by 1.

        Design: Difficulty/cross_entity_state_dependency/harvest_load_refused_after_contract_closed_by_final_settlement
        """
        s = fx.setup_harvest_ready(api)
        version_before = fx.read_contract(api, s.contract["id"])["version"]

        statement = fx.settle_period(api, s.contract["id"], "FINAL", "2026-12-31")

        assert_settlement_statement(statement)
        assert_money(statement["direct_cost_total"], 1000.00, "direct_cost_total")
        assert_money(statement["pass_through"], 80.00, "pass_through")
        assert_money(statement["management_fee_base"], 11875.00,
                     "management_fee_base")
        assert_money(statement["tier_basis"], 11955.00, "tier_basis")
        assert statement["volume_discount_pct"] == 0.00
        assert_money(statement["quality_incentive"], 0.00, "quality_incentive")
        assert_money(statement["total_billable"], 11955.00, "total_billable")

        contract = fx.read_contract(api, s.contract["id"])
        assert contract["contract_status"] == "CLOSED"
        assert contract["settled_period_count"] == 1
        assert_money(contract["last_settlement_total"], 11955.00,
                     "last_settlement_total")
        assert contract["version"] == version_before + 1
