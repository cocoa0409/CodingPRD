"""Presorted-actual postage and the three-component cost per book.

Tier fallback, the weight surcharge, the drop-level automation share and the
independent rounding of each cost component all compose into one figure, and
none of the four inputs predicts it on its own.
"""
from test_helpers import (
    CLOCK_START,
    assert_circulation_line,
    assert_drop,
    assert_postal_presort_batch,
    fetch_drop,
    fetch_line,
    fetch_plan,
    iso_utc,
    set_clock,
    setup_presorted_drop,
)


def _heavy_book_world() -> dict:
    """A 148-page drop of 20000 books presorted as a 149-piece batch declared
    FIVE_DIGIT plus a 19851-piece batch declared THREE_DIGIT."""
    set_clock(CLOCK_START)
    return setup_presorted_drop(
        batches=[("FIVE_DIGIT", 149), ("THREE_DIGIT", 19851)],
        segment_overrides={"segment_code": "S_PREMIUM"},
        plan_overrides={"plan_code": "P1"},
        drop_overrides={"page_count": 148, "in_home_date": iso_utc("2026-09-15")},
    )


def _fifty_thousand_book_world() -> dict:
    """A 94-page drop of 50000 books presorted 20000 FIVE_DIGIT / 30000
    MIXED_AADC, so the automation share falls well short of the gate."""
    set_clock(CLOCK_START)
    return setup_presorted_drop(
        batches=[("FIVE_DIGIT", 20000), ("MIXED_AADC", 30000)],
        segment_overrides={"segment_code": "S_BIG", "housefile_count": 50000},
        plan_overrides={"plan_code": "P1"},
        drop_overrides={"page_count": 94, "in_home_date": iso_utc("2026-09-15")},
        line_overrides={"requested_quantity": 50000},
    )


class TestBatchQualification:
    def test_a_batch_below_its_tier_minimum_falls_back_and_loses_automation(self):
        """PRD §3.7: "A batch whose `piece_count` clears its declared tier's
        minimum keeps that tier as its `effective_tier`; a batch that falls short
        of the minimum drops to `MIXED_AADC` instead."

        Design: Difficulty/combinatorial_formula/presort_tier_fallback_weight_surcharge_and_automation_share_compose
        """
        world = _heavy_book_world()
        small, big = world["presort_batches"]
        assert_postal_presort_batch(small)
        assert_postal_presort_batch(big)

        assert world["drop"]["weight_oz_milli"] == 5920

        assert small["declared_tier"] == "FIVE_DIGIT"
        assert small["effective_tier"] == "MIXED_AADC"
        assert small["rate_cents_per_piece"] == 58
        assert small["weight_surcharge_cents_per_piece"] == 17
        assert small["batch_postage_cents"] == 11175
        assert small["is_automation_qualified"] is False

        assert big["effective_tier"] == "THREE_DIGIT"
        assert big["rate_cents_per_piece"] == 47
        assert big["weight_surcharge_cents_per_piece"] == 17
        assert big["batch_postage_cents"] == 1270464
        assert big["is_automation_qualified"] is True

    def test_the_automation_discount_pays_only_for_the_qualifying_pieces(self):
        """PRD §3.7: "when the drop qualifies, the discount is 2 cents for each
        automation-qualified piece, and when it does not qualify the discount is
        zero. `postage_total_cents` is the batch postage sum less that discount."

        Design: Difficulty/combinatorial_formula/presort_tier_fallback_weight_surcharge_and_automation_share_compose
        """
        world = _heavy_book_world()
        drop = fetch_drop(world["drop"]["id"])
        assert_drop(drop)
        assert drop["automation_share_bps"] == 9925
        assert drop["automation_qualified"] is True
        assert drop["postage_total_cents"] == 1241937
        assert drop["postage_cents_per_book"] == 62
        assert drop["printing_cents_per_book"] == 385
        assert drop["paper_cents_per_book"] == 34
        assert drop["cost_per_book_cents"] == 481
        assert drop["cost_basis"] == "PRESORTED_ACTUAL"
        assert drop["production_status"] == "PRESORTED"

        line = fetch_line(world["line"]["id"])
        assert_circulation_line(line)
        assert line["committed_cost_cents"] == 9480000
        assert line["circulation_cost_cents"] == 9620000
        assert line["contribution_cents"] == 14800

        plan = fetch_plan(world["plan"]["id"])
        assert plan["planned_contribution_cents"] == 14800


class TestCostPerBookRoundingOrder:
    def test_each_cost_component_is_rounded_on_its_own_before_the_sum(self):
        """PRD §3.6: "`cost_per_book_cents` is the sum of those three
        independently rounded components — not the rounding of their exact sum,
        as §2.6 insists."

        Design: Difficulty/combinatorial_formula/cost_per_book_per_component_rounding_order_pinned_at_306
        """
        world = _fifty_thousand_book_world()
        drop = fetch_drop(world["drop"]["id"])
        assert_drop(drop)

        assert drop["planned_quantity"] == 50000
        assert drop["print_rebate_bps"] == 500
        assert drop["automation_share_bps"] == 4000
        assert drop["automation_qualified"] is False
        assert drop["postage_total_cents"] == 2580000

        assert drop["printing_cents_per_book"] == 232
        assert drop["paper_cents_per_book"] == 22
        assert drop["postage_cents_per_book"] == 52
        assert drop["cost_per_book_cents"] == 306
        assert drop["cost_per_book_cents"] != 305
        assert drop["cost_per_book_cents"] == (
            drop["printing_cents_per_book"]
            + drop["paper_cents_per_book"]
            + drop["postage_cents_per_book"]
        )

    def test_the_committed_cost_stays_at_the_provisional_rate_after_presort(self):
        """PRD §3.5: "`provisional_cost_per_book_cents` is the sum of those three
        whole-cent components, and once set it is **never** recomputed after
        allocation."

        Design: Difficulty/combinatorial_formula/cost_per_book_per_component_rounding_order_pinned_at_306
        """
        world = _fifty_thousand_book_world()
        drop = fetch_drop(world["drop"]["id"])
        line = fetch_line(world["line"]["id"])
        plan = fetch_plan(world["plan"]["id"])

        assert drop["provisional_cost_per_book_cents"] == 309
        assert drop["cost_basis"] == "PRESORTED_ACTUAL"

        assert_circulation_line(line)
        assert line["committed_cost_cents"] == 15450000
        assert line["circulation_cost_cents"] == 15300000
        assert line["gross_margin_cents"] == 24087000
        assert line["contribution_cents"] == 8787000

        assert plan["planned_cost_cents"] == 15300000
        assert plan["planned_contribution_cents"] == 8787000
