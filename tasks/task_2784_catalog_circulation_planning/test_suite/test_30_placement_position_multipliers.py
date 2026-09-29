"""Square-inch economics: three positions, one deliberate half-cent, one ledger.

The back-cover placement lands its forecast numerator on an exact .5, which
separates ROUND_HALF_UP from banker's rounding. Productivity is then asserted as a
re-division of that already-rounded forecast rather than a fresh computation from
the exact product, and the drop's square-inch ledger is reconciled against its
5632-inch capacity after all three creates.
"""
from test_helpers import (
    CLOCK_START,
    assert_drop_space_conserved,
    assert_page_placement,
    fetch_drop,
    iso_utc,
    new_drop,
    new_page_placement,
    new_plan,
    new_season,
    set_clock,
)

FRONT = {
    "product_sku": "SKU-FRONT",
    "product_name": "Wool throw",
    "unit_price_cents": 12900,
    "unit_cogs_cents": 5400,
    "demand_per_sq_inch_cents": 4200,
    "page_number": 1,
    "sq_in_offset": 0,
    "square_inches": 44,
    "placement_position": "FRONT_COVER",
}

HOT = {
    "product_sku": "SKU-HOT",
    "product_name": "Cast pan",
    "unit_price_cents": 8900,
    "unit_cogs_cents": 3700,
    "demand_per_sq_inch_cents": 4133,
    "page_number": 2,
    "sq_in_offset": 0,
    "square_inches": 7,
    "placement_position": "HOT_SPOT",
}

BACK = {
    "product_sku": "SKU-BACK",
    "product_name": "Barn coat",
    "unit_price_cents": 24900,
    "unit_cogs_cents": 10400,
    "demand_per_sq_inch_cents": 4015,
    "page_number": 64,
    "sq_in_offset": 0,
    "square_inches": 3,
    "placement_position": "BACK_COVER",
}


def _three_placements_in_three_positions() -> dict:
    """A 64-page drop of a DRAFT plan, carrying one front-cover, one hot-spot and
    one back-cover placement on three different pages."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    return {
        "empty_drop": drop,
        "front": new_page_placement(drop["id"], **FRONT),
        "hot": new_page_placement(drop["id"], **HOT),
        "back": new_page_placement(drop["id"], **BACK),
        "drop": fetch_drop(drop["id"]),
    }


class TestPositionMultipliersAndTheRoundedForecast:
    def test_each_position_selects_its_own_multiplier_and_forecast(self, api):
        """PRD §3.4: "The position selects a multiplier in basis points as
        `position_multiplier_bps` — 18000 for `FRONT_COVER`, 14000 for `HOT_SPOT`,
        13000 for `BACK_COVER`, and 10000 for `INSIDE`. The placement's
        `forecast_space_demand_cents` is its `square_inches` multiplied by its
        `demand_per_sq_inch_cents`, multiplied by `position_multiplier_bps`, divided by
        ten thousand, and rounded half up to whole cents."

        Design: Corner/calculations/placement_position_multipliers_drive_a_re_divided_productivity
        """
        world = _three_placements_in_three_positions()

        for placement in (world["front"], world["hot"], world["back"]):
            assert_page_placement(placement)

        assert world["front"]["position_multiplier_bps"] == 18000
        assert world["front"]["forecast_space_demand_cents"] == 332640

        assert world["hot"]["position_multiplier_bps"] == 14000
        assert world["hot"]["forecast_space_demand_cents"] == 40503

        # The exact product is 15658.5, so half up goes up; banker's rounding to even
        # would report 15658.
        assert world["back"]["position_multiplier_bps"] == 13000
        assert world["back"]["forecast_space_demand_cents"] == 15659
        assert world["back"]["forecast_space_demand_cents"] != 15658

    def test_productivity_re_divides_the_already_rounded_forecast(self, api):
        """PRD §3.4: "Its `space_productivity_cents_per_sq_in` is then
        `forecast_space_demand_cents` divided by `square_inches`, rounded half up — a
        deliberate re-division of the already-rounded forecast rather than an
        independent computation from the exact product."

        Design: Corner/calculations/placement_position_multipliers_drive_a_re_divided_productivity
        """
        world = _three_placements_in_three_positions()

        assert world["front"]["space_productivity_cents_per_sq_in"] == 7560

        # 40503 / 7 is 5786.142857, rounded down from the rounded numerator.
        assert world["hot"]["space_productivity_cents_per_sq_in"] == 5786

        # 15659 / 3 is 5219.666, rounded up; the exact 15658.5 / 3 would give 5220 too,
        # but a numerator rounded to even (15658) would give 5219.
        assert world["back"]["space_productivity_cents_per_sq_in"] == 5220
        assert world["back"]["space_productivity_cents_per_sq_in"] != 5219


class TestTheDropSquareInchLedger:
    def test_an_empty_drop_has_its_whole_capacity_free(self, api):
        """PRD §3.4: "The drop's `weight_oz_milli` is `page_count` multiplied by the
        season's `paper_oz_per_page_milli`, giving thousandths of an ounce of paper per
        book. The drop's `square_inch_capacity` is `page_count` multiplied by the
        season's `usable_sq_in_per_page`. At creation `allocated_square_inches` is 0
        and `unallocated_square_inches` therefore equals the full capacity."

        Design: Corner/calculations/placement_position_multipliers_drive_a_re_divided_productivity
        """
        world = _three_placements_in_three_positions()
        empty = world["empty_drop"]

        assert empty["square_inch_capacity"] == 5632
        assert empty["weight_oz_milli"] == 2560
        assert empty["allocated_square_inches"] == 0
        assert empty["unallocated_square_inches"] == 5632
        assert_drop_space_conserved(empty)

    def test_three_creates_move_exactly_their_own_space(self, api):
        """PRD §3.4: "A successful placement adds its `square_inches` to the drop's
        `allocated_square_inches` and subtracts the same amount from
        `unallocated_square_inches`, and increments the drop's `version` by one."

        Design: Corner/calculations/placement_position_multipliers_drive_a_re_divided_productivity
        """
        world = _three_placements_in_three_positions()
        drop = world["drop"]

        assert drop["allocated_square_inches"] == 54
        assert drop["allocated_square_inches"] == 44 + 7 + 3
        assert drop["unallocated_square_inches"] == 5578
        assert drop["square_inch_capacity"] == 5632
        assert_drop_space_conserved(drop)
        assert drop["version"] == world["empty_drop"]["version"] + 3
