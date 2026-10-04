"""Difficulty queue: dual-variant calculations (obsolescence charge and
innovation priority score) — identical inputs, variant-selected outcomes.
"""
import pytest

from test_helpers import (
    DEFAULT_APPROVAL_DEADLINE_ISO,
    WORKED,
    api_client,
    assert_item,
    create_brand,
    create_innovation_project_payload,
    create_item,
    create_plant,
    decide_case,
    finalize_case,
    get_item,
    propose_case,
    set_clock,
    setup_capital_cycle,
    validate_created,
)


def _setup_executing_items_with_inventory():
    """One brand/plant hosting a STANDARD twin and a SALVAGE twin, both with
    approved cases and the logical clock advanced to the sell-through deadline.

    Returns (item_standard_id, item_salvage_id, case_standard_id, case_salvage_id).
    """
    brand = create_brand(core_flag=True, private_label_share_pct=40,
                         annual_net_revenue_cents=1000000000)
    plant = create_plant(quarterly_capacity_units=1000000)
    item_std = create_item(brand["id"], plant["id"], annual_units=4000,
                           unit_net_revenue_cents=2000, unit_cost_cents=500,
                           units_on_hand=100)
    item_sal = create_item(brand["id"], plant["id"], annual_units=4000,
                           unit_net_revenue_cents=2000, unit_cost_cents=500,
                           units_on_hand=100, salvageable=True)
    case_std = propose_case(item_std["id"])
    case_sal = propose_case(item_sal["id"])
    decide_case(case_std["id"], "APPROVE")
    decide_case(case_sal["id"], "APPROVE")
    set_clock(DEFAULT_APPROVAL_DEADLINE_ISO)
    return item_std["id"], item_sal["id"], case_std["id"], case_sal["id"]


def _create_worked_project(headers, brand, cycle):
    """Raw project-creation call with the worked-example inputs (fit 80,
    year-3 revenue 1,000,000,000, request 1000)."""
    return api_client.create_innovation_project(
        create_innovation_project_payload(
            brand["id"],
            cycle["id"],
            requested_capital_cents=1000,
            expected_revenue_cents_year3=1000000000,
            strategic_fit_score=80,
        ),
        headers,
    )


class TestObsolescenceDualVariant:
    def test_obsolescence_standard_variant_charges_full_cost(self):
        """PRD §3.2: "Under the `STANDARD` variant (`salvageable` false), the
        charge is the full remaining cost: `units_on_hand` multiplied by
        `unit_cost_cents`, with no recovery."
        PRD §3.2: "Posting the charge adds it into the item's
        `obsolescence_charge_cents` accumulator, adds the written-off
        `units_on_hand` into `units_written_off_cumulative`, and sets
        `units_on_hand` to zero."

        Design: Difficulty/dual_variant_calc/obsolescence_standard_vs_salvage_variant
        """
        item_std_id, _, case_std_id, _ = _setup_executing_items_with_inventory()
        finalize_case(case_std_id)
        item = get_item(item_std_id)
        assert_item(item)
        assert item["item_status"] == "DISCONTINUED"
        assert item["obsolescence_charge_cents"] == WORKED["OBSOLESCENCE_STANDARD_CENTS"], (
            f"STANDARD charge must be 100 * 500 = 50000, got "
            f"{item['obsolescence_charge_cents']}"
        )
        assert item["units_on_hand"] == 0
        assert item["units_written_off_cumulative"] == 100

    def test_obsolescence_salvage_variant_recovers_twenty_percent(self):
        """PRD §3.2: "Under the `SALVAGE` variant (`salvageable` true), 20
        percent of the cost is recovered, so the charge is 80 percent of the
        full cost — `units_on_hand` times `unit_cost_cents` times 0.8 — rounded
        half-up to integer cents; identical inputs always yield a strictly
        smaller charge under `SALVAGE` than under `STANDARD` (100 units at 500
        cents cost: 50,000 cents standard versus 40,000 cents salvage)."

        Design: Difficulty/dual_variant_calc/obsolescence_standard_vs_salvage_variant
        """
        item_std_id, item_sal_id, case_std_id, case_sal_id = (
            _setup_executing_items_with_inventory()
        )
        finalize_case(case_std_id)
        finalize_case(case_sal_id)
        item_std = get_item(item_std_id)
        item_sal = get_item(item_sal_id)
        assert item_sal["obsolescence_charge_cents"] == WORKED["OBSOLESCENCE_SALVAGE_CENTS"], (
            f"SALVAGE charge must be round_half_up(100 * 500 * 0.80) = 40000, got "
            f"{item_sal['obsolescence_charge_cents']}"
        )
        assert item_std["obsolescence_charge_cents"] == WORKED["OBSOLESCENCE_STANDARD_CENTS"]
        assert item_sal["obsolescence_charge_cents"] < item_std["obsolescence_charge_cents"], (
            "Identical inventory inputs must yield a strictly smaller SALVAGE charge"
        )
        assert item_sal["units_on_hand"] == 0
        assert item_sal["units_written_off_cumulative"] == 100


class TestInnovationPriorityDualVariant:
    def test_priority_score_standard_variant_plain_blend(self, pm_headers):
        """PRD §3.7: "Under the `STANDARD` variant (`core_flag` false), that
        rounded blend is the `priority_score`."
        PRD §3.7: "a project with `strategic_fit_score` 80 and
        `expected_revenue_cents_year3` of 1,000,000,000 scores 68.00 under
        `STANDARD` and 78.00 under `CORE_BRAND`."

        Design: Difficulty/dual_variant_calc/innovation_priority_standard_vs_core_brand_variant
        """
        cycle = setup_capital_cycle(
            total_capital_cents=1000000000,
            window_start="2026-09-01T00:00:00Z",
            window_end="2027-03-01T00:00:00Z",
        )
        brand = create_brand(core_flag=False, private_label_share_pct=10,
                             annual_net_revenue_cents=500000000)
        data = validate_created(_create_worked_project(pm_headers, brand, cycle))
        assert data["priority_score"] == WORKED["PRIORITY_STANDARD_WORKED"], (
            f"STANDARD priority must be 0.6*80 + 0.4*50 = 68.00, got "
            f"{data['priority_score']}"
        )

    def test_priority_score_core_brand_variant_adds_bonus(self, pm_headers):
        """PRD §3.7: "Under the `CORE_BRAND` variant (`core_flag` true), a bonus
        of exactly 10 points is added **after** the rounding, and the result is
        then capped at 100. Identical project inputs therefore score strictly
        higher for a core brand: a project with `strategic_fit_score` 80 and
        `expected_revenue_cents_year3` of 1,000,000,000 scores 68.00 under
        `STANDARD` and 78.00 under `CORE_BRAND`."

        Design: Difficulty/dual_variant_calc/innovation_priority_standard_vs_core_brand_variant
        """
        cycle = setup_capital_cycle(
            total_capital_cents=1000000000,
            window_start="2026-09-01T00:00:00Z",
            window_end="2027-03-01T00:00:00Z",
        )
        brand_nc = create_brand(core_flag=False, private_label_share_pct=10,
                                annual_net_revenue_cents=500000000)
        brand_c = create_brand(core_flag=True, private_label_share_pct=10,
                               annual_net_revenue_cents=500000000)
        ps_nc = validate_created(
            _create_worked_project(pm_headers, brand_nc, cycle)
        )["priority_score"]
        ps_c = validate_created(
            _create_worked_project(pm_headers, brand_c, cycle)
        )["priority_score"]
        assert ps_c == WORKED["PRIORITY_CORE_BRAND_WORKED"], (
            f"CORE_BRAND priority must be 68.00 + 10 = 78.00, got {ps_c}"
        )
        assert ps_nc == WORKED["PRIORITY_STANDARD_WORKED"]
        assert ps_c - ps_nc == pytest.approx(10.00, abs=1e-9), (
            "Identical project inputs must score exactly the 10-point bonus apart"
        )
