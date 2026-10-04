"""Difficulty queue: compensating invariants — the per-item unit balance across
sell-down plus write-off, and capital conservation across the waterfall.
"""
from test_helpers import (
    DEFAULT_APPROVAL_DEADLINE_ISO,
    TEST_USERS,
    api_client,
    assert_capital_conservation,
    assert_item_unit_balance,
    create_brand,
    create_innovation_project_payload,
    create_sell_down_payload,
    decide_case,
    finalize_case,
    get_item,
    propose_case,
    set_clock,
    setup_capital_cycle,
    setup_listed_item,
    validate_created,
    validate_ok,
)

SCP = TEST_USERS["supply_chain_planner_headers"]
FC = TEST_USERS["finance_controller_headers"]
PM = TEST_USERS["portfolio_manager_headers"]

CREATED_UNITS = 1000


class TestItemUnitBalanceInvariant:
    def _setup_item_with_1000_units(self):
        _, _, item = setup_listed_item(
            {"annual_units": 4000, "unit_net_revenue_cents": 2000,
             "unit_cost_cents": 500, "units_on_hand": CREATED_UNITS}
        )
        return item

    def _sell_down_200(self, item_id, expected_version):
        return validate_ok(
            api_client.sell_down_item(
                item_id, create_sell_down_payload(200, expected_version), SCP
            )
        )

    def test_sell_down_chain_conserves_unit_balance(self):
        """PRD §3.2: "Across every sell-down, finalize, and divestiture
        cascade, the item's unit balance is conserved: `units_on_hand` plus
        `units_sold_cumulative` plus `units_written_off_cumulative` always
        equals the `units_on_hand` the item was created with
        (`inv_item_unit_and_listed`)."
        PRD §3.3: "A successful sell-down subtracts `units_sold` from
        `units_on_hand`, adds it to `units_sold_cumulative`, and increments the
        item's `version` by 1".

        Design: Difficulty/compensating_invariant/item_unit_balance_conserved_across_sell_down_and_writeoff
        """
        item = self._setup_item_with_1000_units()
        assert item["version"] == 1
        after_first = self._sell_down_200(item["id"], item["version"])
        assert after_first["version"] == 2
        assert after_first["units_on_hand"] == 800
        after_second = self._sell_down_200(item["id"], after_first["version"])
        assert after_second["version"] == 3
        assert after_second["units_on_hand"] == 600
        assert after_second["units_sold_cumulative"] == 400
        # 600 on hand + 400 sold + 0 written off == 1000 created.
        assert_item_unit_balance(after_second, CREATED_UNITS)

    def test_finalize_writeoff_conserves_unit_balance(self):
        """PRD §3.2: "Across every sell-down, finalize, and divestiture
        cascade, the item's unit balance is conserved: `units_on_hand` plus
        `units_sold_cumulative` plus `units_written_off_cumulative` always
        equals the `units_on_hand` the item was created with
        (`inv_item_unit_and_listed`)."
        PRD §3.2: "Posting the charge adds it into the item's
        `obsolescence_charge_cents` accumulator, adds the written-off
        `units_on_hand` into `units_written_off_cumulative`, and sets
        `units_on_hand` to zero."

        Design: Difficulty/compensating_invariant/item_unit_balance_conserved_across_sell_down_and_writeoff
        """
        item = self._setup_item_with_1000_units()
        after_first = self._sell_down_200(item["id"], item["version"])
        self._sell_down_200(item["id"], after_first["version"])
        case = propose_case(item["id"])
        decide_case(case["id"], "APPROVE")
        set_clock(DEFAULT_APPROVAL_DEADLINE_ISO)
        finalize_case(case["id"])
        final = get_item(item["id"])
        assert final["units_on_hand"] == 0
        assert final["units_sold_cumulative"] == 400
        assert final["units_written_off_cumulative"] == 600
        # 0 on hand + 400 sold + 600 written off == 1000 created.
        assert_item_unit_balance(final, CREATED_UNITS)
        assert final["obsolescence_charge_cents"] == 300000, (
            f"STANDARD charge on 600 remaining units * 500 = 300000, got "
            f"{final['obsolescence_charge_cents']}"
        )


class TestCapitalConservationAcrossWaterfall:
    def _setup_cycle_with_three_projects(self):
        """Cycle total 1,000,000,000; three PROPOSED projects on a NON-core
        brand (STANDARD scores): P1 94.00 requesting 600M, P2 68.00 requesting
        500M, P3 46.00 requesting 300M."""
        cycle = setup_capital_cycle(
            total_capital_cents=1000000000,
            window_start="2026-09-01T00:00:00Z",
            window_end="2027-03-01T00:00:00Z",
        )
        brand = create_brand(core_flag=False, private_label_share_pct=40,
                             annual_net_revenue_cents=1000000000)
        p1 = validate_created(api_client.create_innovation_project(
            create_innovation_project_payload(
                brand["id"], cycle["id"], title="P1",
                requested_capital_cents=600000000,
                expected_revenue_cents_year3=2000000000, strategic_fit_score=90),
            PM,
        ))
        p2 = validate_created(api_client.create_innovation_project(
            create_innovation_project_payload(
                brand["id"], cycle["id"], title="P2",
                requested_capital_cents=500000000,
                expected_revenue_cents_year3=1000000000, strategic_fit_score=80),
            PM,
        ))
        p3 = validate_created(api_client.create_innovation_project(
            create_innovation_project_payload(
                brand["id"], cycle["id"], title="P3",
                requested_capital_cents=300000000,
                expected_revenue_cents_year3=500000000, strategic_fit_score=60),
            PM,
        ))
        assert p1["priority_score"] == 94.00, "Setup failed: P1 priority must be 94.00"
        return cycle, p1, p2, p3

    def test_waterfall_skip_and_continue_funding(self):
        """PRD §3.7: "a project whose `requested_capital_cents` fits within the
        current remainder — an exact fit counts, since the comparison is
        less-than-or-equal — becomes `FUNDED`, its request is added to
        `allocated_cents` and subtracted from the remainder; a project that
        does not fit becomes `DEFERRED`, and the walk **continues** down the
        list, so smaller later projects can still fund behind an oversized
        one."

        Design: Difficulty/compensating_invariant/capital_conservation_across_waterfall
        """
        cycle, p1, p2, p3 = self._setup_cycle_with_three_projects()
        validate_ok(api_client.run_capital_cycle_selection(cycle["id"], FC))
        p1_after = validate_ok(api_client.get_innovation_project(p1["id"], FC))
        p2_after = validate_ok(api_client.get_innovation_project(p2["id"], FC))
        p3_after = validate_ok(api_client.get_innovation_project(p3["id"], FC))
        assert p1_after["project_status"] == "FUNDED", (
            "P1 (94.00) fits the full pool and must fund"
        )
        assert p2_after["project_status"] == "DEFERRED", (
            "P2 (68.00): 500000000 > 400000000 remaining at its rank -> DEFERRED"
        )
        assert p3_after["project_status"] == "FUNDED", (
            "P3 (46.00): 300000000 <= 400000000 -> skip-and-continue funds it"
        )

    def test_capital_conservation_after_selection(self):
        """PRD §3.7: "Capital is conserved throughout: after selection,
        `allocated_cents` plus `remaining_cents` always equals
        `total_capital_cents` (invariant `inv_capital_conservation`)."

        Design: Difficulty/compensating_invariant/capital_conservation_across_waterfall
        """
        cycle, _, _, _ = self._setup_cycle_with_three_projects()
        locked = validate_ok(api_client.run_capital_cycle_selection(cycle["id"], FC))
        assert locked["cycle_status"] == "LOCKED"
        assert locked["allocated_cents"] == 900000000, (
            f"600M + 300M funded -> 900000000, got {locked['allocated_cents']}"
        )
        assert locked["remaining_cents"] == 100000000
        assert_capital_conservation(locked)
