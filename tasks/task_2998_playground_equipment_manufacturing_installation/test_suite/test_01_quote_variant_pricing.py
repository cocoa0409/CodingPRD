"""Quote pricing: the two variants and the single rounding point each pins.

Every test starts against an empty database with the logical clock at its
mandatory startup default, and builds its own priced design from
`test_helpers.fixtures`.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["design_consultant_headers"]


# --------------------------------------------------------------------------
# Local setup helpers
# --------------------------------------------------------------------------
def _setup_two_line_design() -> dict:
    """A CONSULTATION project holding exactly two VALIDATED placements, both on
    a chargeable colour, plus an ISSUED rendering.

    The post line is 10750 x 3 and the deck line is 64350 x 1, so the priced
    unit count is 4.
    """
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Cedar Hollow"}
    )
    area_id = scenario["area"]["id"]
    scenario["post_placement"] = fx.create_validated_placement(
        area_id,
        scenario["post"]["id"],
        color_choice="FOREST_GREEN",
        x_start_cm=200,
        quantity=3,
    )
    scenario["deck_placement"] = fx.create_validated_placement(
        area_id,
        scenario["deck"]["id"],
        color_choice="SKY_BLUE",
        x_start_cm=700,
        quantity=1,
    )
    scenario["rendering"] = fx.issue_rendering(
        scenario["project"]["id"], scenario["standard"]["id"]
    )
    return scenario


def _issue_quote(scenario: dict, variant: str) -> dict:
    """Issue one quote against the scenario's rendering and return it."""
    project_id = scenario["project"]["id"]
    payload = f.quote_payload(
        project_id,
        scenario["rendering"]["id"],
        fx.project_version(project_id),
        variant=variant,
    )
    return validate_success(api_client.create_quote(payload, CONSULTANT), 201)


# --------------------------------------------------------------------------
# The three-placement set priced under both variants
# --------------------------------------------------------------------------
class TestProvisionalVersusFirmOnTheSamePlacementSet:
    def test_provisional_subtotal_sits_one_cent_above_the_firm_subtotal(self):
        """PROVISIONAL rounds each uplifted line, FIRM rounds the sum once.

        PRD: "For a `PROVISIONAL` quote, each raw line is rounded half up to whole cents first, and `subtotal_cents` is the sum of those rounded lines. For a `FIRM` quote, the exact unrounded raw lines are summed first and the single total is rounded half up to whole cents once, at the end."

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_firm_diverge_on_same_placement_set
        """
        scenario = fx.setup_three_placement_design()
        provisional = _issue_quote(scenario, "PROVISIONAL")
        firm = _issue_quote(scenario, "FIRM")

        a.assert_quote(provisional)
        a.assert_quote(firm)
        a.assert_cents(provisional["subtotal_cents"], "subtotal_cents")
        a.assert_cents(firm["subtotal_cents"], "subtotal_cents")

        assert provisional["variant"] == "PROVISIONAL", (
            f"expected PROVISIONAL, got {provisional['variant']}"
        )
        assert firm["variant"] == "FIRM", f"expected FIRM, got {firm['variant']}"
        assert provisional["subtotal_cents"] == 333895, (
            "expected 333895 from rounding each of the three uplifted lines first, "
            f"got {provisional['subtotal_cents']}"
        )
        assert firm["subtotal_cents"] == 333894, (
            "expected 333894 from rounding the exact sum once, "
            f"got {firm['subtotal_cents']}"
        )
        assert provisional["subtotal_cents"] - firm["subtotal_cents"] == 1, (
            "the two rounding orders must differ by exactly one cent on this set, got "
            f"{provisional['subtotal_cents'] - firm['subtotal_cents']}"
        )

    def test_both_variants_price_five_units_of_freight_and_no_discount(self):
        """Freight and the priced unit count are variant-independent here.

        PRD: "`priced_unit_count` is the sum of `quantity` over the placements the variant included. `freight_cents` is a flat base of 48000 cents plus 1250 cents for every priced unit."

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_firm_diverge_on_same_placement_set
        """
        scenario = fx.setup_three_placement_design()
        provisional = _issue_quote(scenario, "PROVISIONAL")
        firm = _issue_quote(scenario, "FIRM")

        for quote in (provisional, firm):
            a.assert_freight(quote)
            a.assert_cents(quote["freight_cents"], "freight_cents")
            a.assert_cents(quote["discount_cents"], "discount_cents")
            assert quote["priced_unit_count"] == 5, (
                "quantities 3 + 1 + 1 make a priced unit count of 5, got "
                f"{quote['priced_unit_count']}"
            )
            assert quote["freight_cents"] == 54250, (
                f"expected freight 54250 for 5 priced units, got {quote['freight_cents']}"
            )
            assert quote["discount_cents"] == 0, (
                f"expected no volume discount at this subtotal, got {quote['discount_cents']}"
            )

    def test_the_one_cent_rounding_delta_survives_into_total_cents(self):
        """The subtotal delta is not absorbed by freight or discount.

        PRD: "`freight_cents` is a flat base of 48000 cents plus 1250 cents for
        every priced unit."
        PRD: "`total_cents` is `subtotal_cents` plus `freight_cents` less `discount_cents`."

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_firm_diverge_on_same_placement_set
        """
        scenario = fx.setup_three_placement_design()
        provisional = _issue_quote(scenario, "PROVISIONAL")
        firm = _issue_quote(scenario, "FIRM")

        a.assert_quote_arithmetic(provisional)
        a.assert_quote_arithmetic(firm)
        a.assert_cents(provisional["total_cents"], "total_cents")
        a.assert_cents(firm["total_cents"], "total_cents")

        assert provisional["total_cents"] == 388145, (
            f"expected total 388145 on the PROVISIONAL quote, got {provisional['total_cents']}"
        )
        assert firm["total_cents"] == 388144, (
            f"expected total 388144 on the FIRM quote, got {firm['total_cents']}"
        )
        assert provisional["total_cents"] - firm["total_cents"] == 1, (
            "the one-cent rounding-order delta must survive into total_cents, got "
            f"{provisional['total_cents'] - firm['total_cents']}"
        )

    def test_issuing_the_firm_quote_expires_the_provisional_quote(self):
        """The later issuance expires the project's earlier ISSUED quote.

        PRD: "Issuing a quote creates it in `ISSUED` status with `subtotal_cents`, `freight_cents`, `discount_cents`, `total_cents` and `priced_unit_count` all frozen, moves every other `Quote` of the project still in `ISSUED` to `EXPIRED`, and increments the project's `version` by one."

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_firm_diverge_on_same_placement_set
        """
        scenario = fx.setup_three_placement_design()
        provisional = _issue_quote(scenario, "PROVISIONAL")
        assert provisional["status"] == "ISSUED", (
            f"a freshly issued quote is ISSUED, got {provisional['status']}"
        )
        firm = _issue_quote(scenario, "FIRM")

        expired = fx.get_quote(provisional["id"])
        assert expired["status"] == "EXPIRED", (
            "the PROVISIONAL quote must be EXPIRED once the FIRM quote is issued, got "
            f"{expired['status']}"
        )
        assert fx.get_quote(firm["id"])["status"] == "ISSUED", (
            "the newly issued FIRM quote stays ISSUED"
        )
        assert expired["subtotal_cents"] == 333895, (
            "the expired quote keeps its frozen pricing, got "
            f"{expired['subtotal_cents']}"
        )


# --------------------------------------------------------------------------
# The two-line set that isolates the rounding point
# --------------------------------------------------------------------------
class TestRoundingOrderOnATwoLineSet:
    def test_per_line_rounding_yields_one_cent_more_than_rounding_once_at_the_end(self):
        """Two exact lines of 34507.5 and 68854.5 separate the two orders.

        PRD: "For a `PROVISIONAL` quote, each raw line is rounded half up to whole cents first, and `subtotal_cents` is the sum of those rounded lines. For a `FIRM` quote, the exact unrounded raw lines are summed first and the single total is rounded half up to whole cents once, at the end."

        Design: Difficulty/combinatorial_formula/quote_rounding_order_pinned_per_line_for_provisional_and_end_for_firm
        """
        scenario = _setup_two_line_design()
        provisional = _issue_quote(scenario, "PROVISIONAL")
        firm = _issue_quote(scenario, "FIRM")

        a.assert_quote(provisional)
        a.assert_quote(firm)
        assert provisional["subtotal_cents"] == 103363, (
            "expected 103363 from rounding 34507.5 and 68854.5 line by line, got "
            f"{provisional['subtotal_cents']}"
        )
        assert firm["subtotal_cents"] == 103362, (
            "expected 103362 from rounding the exact sum 103362.0 once, got "
            f"{firm['subtotal_cents']}"
        )
        assert provisional["subtotal_cents"] - firm["subtotal_cents"] == 1, (
            "two half-cent lines put the per-line order exactly one cent higher, got "
            f"{provisional['subtotal_cents'] - firm['subtotal_cents']}"
        )

    def test_freight_is_flat_base_plus_per_unit_and_is_never_discounted(self):
        """The discount tier reads the subtotal alone and freight is untouched.

        PRD: "The tier is selected on `subtotal_cents` **alone** — never on the subtotal plus freight — and freight itself is never discounted."

        Design: Difficulty/combinatorial_formula/quote_rounding_order_pinned_per_line_for_provisional_and_end_for_firm
        """
        scenario = _setup_two_line_design()
        provisional = _issue_quote(scenario, "PROVISIONAL")
        firm = _issue_quote(scenario, "FIRM")

        for quote in (provisional, firm):
            a.assert_freight(quote)
            assert quote["priced_unit_count"] == 4, (
                "quantities 3 + 1 make a priced unit count of 4, got "
                f"{quote['priced_unit_count']}"
            )
            assert quote["freight_cents"] == 53000, (
                f"expected freight 53000 for 4 priced units, got {quote['freight_cents']}"
            )
            assert quote["discount_cents"] == 0, (
                "a subtotal of roughly 103362 cents earns no volume discount, got "
                f"{quote['discount_cents']}"
            )

    def test_the_rounding_order_delta_survives_into_total_cents(self):
        """Freight is added after the rounding point, so the delta persists.

        PRD: "`freight_cents` is a flat base of 48000 cents plus 1250 cents for
        every priced unit."
        PRD: "`total_cents` is `subtotal_cents` plus `freight_cents` less `discount_cents`."

        Design: Difficulty/combinatorial_formula/quote_rounding_order_pinned_per_line_for_provisional_and_end_for_firm
        """
        scenario = _setup_two_line_design()
        provisional = _issue_quote(scenario, "PROVISIONAL")
        firm = _issue_quote(scenario, "FIRM")

        a.assert_quote_arithmetic(provisional)
        a.assert_quote_arithmetic(firm)
        assert provisional["total_cents"] == 156363, (
            f"expected total 156363 on the PROVISIONAL quote, got {provisional['total_cents']}"
        )
        assert firm["total_cents"] == 156362, (
            f"expected total 156362 on the FIRM quote, got {firm['total_cents']}"
        )
        assert firm["total_cents"] != 156363, (
            "adding freight after the rounding point must not erase the one-cent delta"
        )
