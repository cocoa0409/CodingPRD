"""Paid-miles determination and the two competing linehaul legs.

These tests exercise the load-pricing arithmetic that delivery runs: which stored
mileage column pays, the short-haul floor, the mileage band, the revenue share and
the max() selection between the two legs.
"""

from test_helpers import (
    CLERK_HEADERS,
    api_client,
    fixtures,
    validate_success,
)
from test_helpers.constants import (
    LONG_HAUL_BUMP_CENTS,
    MILEAGE_BAND_BREAK,
)
from test_helpers.types import DriverType, LineType, MileageGuide, PerDiemMethod


def _guide_environment(mileage_guide, legal_name):
    """An ACTIVE leased-operator package on one mileage guide, plus an ACTIVE driver."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=mileage_guide,
        per_diem_method=PerDiemMethod.NONE,
        name=f"Leased {mileage_guide}",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name=legal_name,
        home_state="TX",
    )
    return package, driver


class TestMileageGuideSelectsThePayingColumn:
    """The same haul pays differently under the two mileage guides."""

    def test_practical_guide_pays_the_practical_miles_column_and_the_per_mile_leg_wins(self):
        """The practical guide pays practical_miles, and its longer distance makes the
        per-mile leg out-earn the revenue share.

        PRD 3.4: "`base_guide_miles` is the load's `practical_miles` when that guide is
        `PRACTICAL` or its `hhg_miles` when that guide is `HHG`."
        PRD 3.4: "The choice matters: the practical guide's longer distance raises paid
        miles and can make the per-mile component out-earn the revenue-percentage
        component".

        Design: Difficulty/dual_variant_calc/paid_miles_guide_variant_practical_vs_hhg
        """
        _, driver = _guide_environment(MileageGuide.PRACTICAL, "Aaron Practical")
        load = fixtures.tender_load(
            driver["id"],
            practical_miles=780,
            hhg_miles=742,
            linehaul_revenue_cents=180000,
            origin_zip="75201",
            dest_zip="30303",
            stop_count=1,
        )

        fixtures.set_clock(fixtures.TS_DISPATCH)
        fixtures.dispatch(load["id"])
        fixtures.set_clock(fixtures.TS_DELIVER)
        delivered = validate_success(
            api_client.deliver_load(load["id"], {}, CLERK_HEADERS)
        )

        assert delivered["applied_mileage_guide"] == MileageGuide.PRACTICAL
        assert delivered["base_guide_miles"] == 780
        assert delivered["paid_miles"] == 780
        assert delivered["short_haul_floor_applied"] is False
        assert delivered["linehaul_line_type"] == LineType.LINEHAUL_PER_MILE
        assert delivered["linehaul_pay_cents"] == 46080, (
            f"780 paid miles must pay 46080 cents, got {delivered['linehaul_pay_cents']}"
        )

    def test_hhg_guide_pays_the_shorter_column_and_flips_the_winning_leg(self):
        """The household-goods guide pays hhg_miles on the identical load, and its
        shorter distance flips the winner to the revenue-percentage leg.

        PRD 3.4: "while the household-goods guide's shorter distance lowers paid miles
        for the identical load and can flip the winning component the other way."
        PRD 3.4: "The winner sets `linehaul_pay_cents` and `linehaul_line_type`, which is
        `LINEHAUL_PER_MILE` when the per-mile leg wins and `LINEHAUL_PERCENT` when the
        percentage leg wins."

        Design: Difficulty/dual_variant_calc/paid_miles_guide_variant_practical_vs_hhg
        """
        _, driver = _guide_environment(MileageGuide.HHG, "Bea Householder")
        load = fixtures.tender_load(
            driver["id"],
            practical_miles=780,
            hhg_miles=742,
            linehaul_revenue_cents=180000,
            origin_zip="75201",
            dest_zip="30303",
            stop_count=1,
        )

        fixtures.set_clock(fixtures.TS_DISPATCH)
        fixtures.dispatch(load["id"])
        fixtures.set_clock(fixtures.TS_DELIVER)
        delivered = validate_success(
            api_client.deliver_load(load["id"], {}, CLERK_HEADERS)
        )

        assert delivered["applied_mileage_guide"] == MileageGuide.HHG
        assert delivered["base_guide_miles"] == 742
        assert delivered["paid_miles"] == 742
        assert delivered["short_haul_floor_applied"] is False
        assert delivered["linehaul_line_type"] == LineType.LINEHAUL_PERCENT
        assert delivered["linehaul_pay_cents"] == 45000, (
            f"2500 bps of 180000 cents must pay 45000, got {delivered['linehaul_pay_cents']}"
        )

    def test_two_drivers_on_the_two_guides_price_the_same_haul_differently(self):
        """One haul, two packages: the pair of stored mileage columns is what the guide
        choice selects between, and the two loads settle on different legs.

        PRD 3.4: "Both must be strictly greater than zero, and both are stored regardless
        of which guide the driver's package actually pays on, because the pair is exactly
        what a later mileage dispute argues about."

        Design: Difficulty/dual_variant_calc/paid_miles_guide_variant_practical_vs_hhg
        """
        _, driver_practical = _guide_environment(MileageGuide.PRACTICAL, "Aaron Practical")
        _, driver_hhg = _guide_environment(MileageGuide.HHG, "Bea Householder")

        load_a = fixtures.tender_load(
            driver_practical["id"], practical_miles=780, hhg_miles=742,
            linehaul_revenue_cents=180000, stop_count=1,
        )
        load_b = fixtures.tender_load(
            driver_hhg["id"], practical_miles=780, hhg_miles=742,
            linehaul_revenue_cents=180000, stop_count=1,
        )

        fixtures.set_clock(fixtures.TS_DISPATCH)
        fixtures.dispatch(load_a["id"])
        fixtures.dispatch(load_b["id"])
        fixtures.set_clock(fixtures.TS_DELIVER)
        fixtures.deliver(load_a["id"])
        fixtures.deliver(load_b["id"])

        priced_a = fixtures.read_load(load_a["id"])
        priced_b = fixtures.read_load(load_b["id"])

        assert priced_a["practical_miles"] == priced_b["practical_miles"] == 780
        assert priced_a["hhg_miles"] == priced_b["hhg_miles"] == 742
        assert priced_a["paid_miles"] == 780 and priced_b["paid_miles"] == 742
        assert priced_a["linehaul_pay_cents"] == 46080
        assert priced_b["linehaul_pay_cents"] == 45000
        assert priced_a["linehaul_line_type"] == LineType.LINEHAUL_PER_MILE
        assert priced_b["linehaul_line_type"] == LineType.LINEHAUL_PERCENT


def _band_environment():
    """One package with both linehaul legs and one ACTIVE driver on it."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        name="Leased Combinatorial",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Cal Combinatorial",
        home_state="TX",
    )
    return package, driver


def _deliver_priced_load(driver_id, miles, revenue_cents):
    """Tender, dispatch and deliver one load whose two mileage columns agree, so the
    guide choice is not in play, and return the priced load."""
    load = fixtures.tender_load(
        driver_id,
        practical_miles=miles,
        hhg_miles=miles,
        linehaul_revenue_cents=revenue_cents,
        stop_count=1,
    )
    fixtures.set_clock(fixtures.TS_DISPATCH)
    fixtures.dispatch(load["id"])
    fixtures.set_clock(fixtures.TS_DELIVER)
    fixtures.deliver(load["id"])
    return fixtures.read_load(load["id"])


class TestLinehaulBandAndTieBreak:
    """The per-mile band, the revenue share and the max() between them."""

    def test_marginal_band_rate_applies_only_to_the_miles_beyond_the_break(self):
        """At exactly the band break every mile earns the base rate; the 501st mile earns
        the base rate plus three cents, so the two loads differ by exactly 61 cents.

        PRD 3.4: "paid miles up to and including the band break at 500 miles earn the
        `PER_MILE` component's `rate_value` in cents each, and every mile beyond 500 earns
        a marginal rate of that `rate_value` plus 3 cents".

        Design: Difficulty/combinatorial_formula/linehaul_band_max_and_tie_composite
        """
        _, driver = _band_environment()

        at_break = _deliver_priced_load(driver["id"], 500, 100000)
        past_break = _deliver_priced_load(driver["id"], 501, 100000)

        assert at_break["paid_miles"] == MILEAGE_BAND_BREAK
        assert at_break["linehaul_pay_cents"] == 29000
        assert at_break["linehaul_line_type"] == LineType.LINEHAUL_PER_MILE
        assert past_break["linehaul_pay_cents"] == 29061
        assert past_break["linehaul_line_type"] == LineType.LINEHAUL_PER_MILE
        assert (
            past_break["linehaul_pay_cents"] - at_break["linehaul_pay_cents"]
            == 58 + LONG_HAUL_BUMP_CENTS
        ), "the 501st mile must earn the base rate plus the marginal bump"

    def test_long_haul_load_composes_both_bands_rather_than_one_flat_rate(self):
        """A 780-mile load pays 500 miles at the base rate plus 280 at the marginal rate,
        which is 46080 cents and not the 45240 a single flat rate would give.

        PRD 3.4: "formally, the lesser of `paid_miles` and 500 multiplied by the rate, plus
        the excess of `paid_miles` over 500 (zero when there is no excess) multiplied by the
        rate plus 3."

        Design: Difficulty/combinatorial_formula/linehaul_band_max_and_tie_composite
        """
        _, driver = _band_environment()

        long_haul = _deliver_priced_load(driver["id"], 780, 180000)

        assert long_haul["paid_miles"] == 780
        assert long_haul["linehaul_line_type"] == LineType.LINEHAUL_PER_MILE
        assert long_haul["linehaul_pay_cents"] == 46080
        assert long_haul["linehaul_pay_cents"] != 780 * 58, (
            "a single flat rate across the whole distance would pay 45240, not 46080"
        )

    def test_exact_tie_between_the_two_legs_is_won_by_the_per_mile_leg(self):
        """400 miles at 58 cents and 2500 bps of 92800 cents both come to 23200, and the
        tie goes to the per-mile leg.

        PRD 3.4: "Selection between the legs is non-linear: when both exist, the greater one
        wins, and an exact tie is won by the per-mile leg."

        Design: Difficulty/combinatorial_formula/linehaul_band_max_and_tie_composite
        """
        _, driver = _band_environment()

        tied = _deliver_priced_load(driver["id"], 400, 92800)

        assert tied["linehaul_pay_cents"] == 23200
        assert tied["linehaul_line_type"] == LineType.LINEHAUL_PER_MILE, (
            "an exact tie must resolve to the per-mile leg, not the percentage leg"
        )

    def test_revenue_percentage_leg_wins_when_it_is_the_greater_of_the_two(self):
        """On a short high-revenue haul the revenue share is the greater leg and takes both
        the amount and the line type.

        PRD 3.4: "The **revenue-percentage leg** is the load's `linehaul_revenue_cents`
        multiplied by the `REVENUE_PERCENT` component's `rate_value` in basis points, divided
        by 10,000 and rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/linehaul_band_max_and_tie_composite
        """
        _, driver = _band_environment()

        percent_won = _deliver_priced_load(driver["id"], 300, 100024)

        assert percent_won["paid_miles"] == 300
        assert percent_won["linehaul_pay_cents"] == 25006
        assert percent_won["linehaul_line_type"] == LineType.LINEHAUL_PERCENT
        assert percent_won["linehaul_pay_cents"] > 300 * 58, (
            "the percentage leg only wins when it exceeds the per-mile leg"
        )
