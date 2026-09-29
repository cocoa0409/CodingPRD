"""The derived surfacing requirement on a play area: tier base, two uplifts and
the absolute minimum.

Every test starts against an empty database with the logical clock at its
mandatory startup default and builds its own areas from `test_helpers.fixtures`.
"""

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


# --------------------------------------------------------------------------
# Local setup helper
# --------------------------------------------------------------------------
def _setup_three_areas_on_clay() -> dict:
    """Three areas on CLAY sites, each holding exactly one DRAFT deck placement.

    Area A1 is a toddler engineered-wood-fibre area committed to 40 cm, area A2
    is a school-age engineered-wood-fibre area on the same project committed to
    40 cm, and area A3 is a toddler poured-rubber area on a second project
    committed to 20 cm. Every deck contributes a 122 cm play surface.
    """
    fx.create_active_standard()
    toddler_deck = fx.create_certified_model(f.deck_model_payload())
    school_deck = fx.create_certified_model(
        f.deck_model_payload(
            sku="DECK-SCH-122",
            age_group="SCHOOL_AGE_5_12",
            color_options=["CEDAR", "SLATE"],
        )
    )

    project_one = fx.create_project_in_consultation(
        client_name="Highland Fields",
        site_length_cm=5000,
        site_soil_type="CLAY",
        budget_cents=900000,
        required_age_groups=["TODDLER_6_23M", "SCHOOL_AGE_5_12"],
    )
    area_one = fx.create_play_area(
        project_one["id"],
        age_group="TODDLER_6_23M",
        axis_origin_cm=0,
        axis_length_cm=2000,
        surfacing_material="ENGINEERED_WOOD_FIBER",
        surfacing_depth_cm=40,
    )
    area_two = fx.create_play_area(
        project_one["id"],
        age_group="SCHOOL_AGE_5_12",
        axis_origin_cm=2000,
        axis_length_cm=2000,
        surfacing_material="ENGINEERED_WOOD_FIBER",
        surfacing_depth_cm=40,
    )

    project_two = fx.create_project_in_consultation(
        client_name="Brookside Tots",
        site_soil_type="CLAY",
        required_age_groups=["TODDLER_6_23M"],
    )
    area_three = fx.create_play_area(
        project_two["id"],
        age_group="TODDLER_6_23M",
        axis_origin_cm=0,
        axis_length_cm=2000,
        surfacing_material="POURED_RUBBER",
        surfacing_depth_cm=20,
    )

    fx.create_placement(
        area_one["id"], toddler_deck["id"], color_choice="CEDAR", x_start_cm=700,
        quantity=1,
    )
    fx.create_placement(
        area_two["id"], school_deck["id"], color_choice="CEDAR", x_start_cm=2700,
        quantity=1,
    )
    fx.create_placement(
        area_three["id"], toddler_deck["id"], color_choice="CEDAR", x_start_cm=700,
        quantity=1,
    )

    return {
        "toddler_deck": toddler_deck,
        "school_deck": school_deck,
        "project_one": project_one,
        "project_two": project_two,
        "area_one": fx.get_play_area(area_one["id"]),
        "area_two": fx.get_play_area(area_two["id"]),
        "area_three": fx.get_play_area(area_three["id"]),
    }


# --------------------------------------------------------------------------
# The requirement is a nested maximum, never a sum
# --------------------------------------------------------------------------
class TestRequiredSurfacingDepthDerivation:
    def test_toddler_and_clay_uplifts_are_taken_separately_not_summed(self):
        """A toddler wood-fibre area on clay requires 28 cm rather than 31 cm.

        PRD: "Two uplifts then apply, and **they are not additive**: each is applied to the base on its own to form a candidate, and the requirement is the largest candidate."

        Design: Difficulty/combinatorial_formula/surfacing_depth_nested_max_over_tier_age_and_soil_uplifts
        """
        scenario = _setup_three_areas_on_clay()
        area = scenario["area_one"]

        a.assert_play_area(area)
        assert area["critical_fall_height_cm"] == 122, (
            "the single DRAFT deck contributes a 122 cm play surface, got "
            f"{area['critical_fall_height_cm']}"
        )
        assert a.expected_base_attenuation_depth(122, "ENGINEERED_WOOD_FIBER") == 23
        assert area["required_surfacing_depth_cm"] == 28, (
            "expected the larger of the 5 cm toddler candidate and the 3 cm clay "
            f"candidate over a base of 23, got {area['required_surfacing_depth_cm']}"
        )
        assert area["required_surfacing_depth_cm"] != 31, (
            "adding both uplifts to the base would give 31 cm, which the two "
            "independent candidates must never produce"
        )
        a.assert_required_surfacing_depth(area, "CLAY", expected=28)

    def test_a_school_age_area_on_the_same_clay_project_takes_the_soil_uplift_alone(self):
        """Without the toddler band, only the clay candidate lifts the base.

        PRD: "The second candidate is the base plus 3 centimetres when the owning project's `site_soil_type` is `CLAY`, and the base unchanged otherwise."

        Design: Difficulty/combinatorial_formula/surfacing_depth_nested_max_over_tier_age_and_soil_uplifts
        """
        scenario = _setup_three_areas_on_clay()
        area = scenario["area_two"]

        a.assert_play_area(area)
        assert area["age_group"] == "SCHOOL_AGE_5_12", (
            f"expected a SCHOOL_AGE_5_12 area, got {area['age_group']}"
        )
        assert area["critical_fall_height_cm"] == 122, (
            f"expected a critical fall height of 122, got {area['critical_fall_height_cm']}"
        )
        assert area["required_surfacing_depth_cm"] == 26, (
            "expected 23 plus the 3 cm clay uplift, got "
            f"{area['required_surfacing_depth_cm']}"
        )
        assert (
            area["required_surfacing_depth_cm"]
            < scenario["area_one"]["required_surfacing_depth_cm"]
        ), "the same fall height and material must require less outside the toddler band"
        a.assert_required_surfacing_depth(area, "CLAY", expected=26)

    def test_the_absolute_minimum_dominates_both_poured_rubber_candidates(self):
        """Poured rubber's candidates of 10 and 8 cm are floored at 15 cm.

        PRD: "`required_surfacing_depth_cm` is the greatest of those two candidates and the absolute minimum of 15 centimetres — which is why an area with no placements at all still reads 15."

        Design: Difficulty/combinatorial_formula/surfacing_depth_nested_max_over_tier_age_and_soil_uplifts
        """
        scenario = _setup_three_areas_on_clay()
        area = scenario["area_three"]

        a.assert_play_area(area)
        assert area["surfacing_material"] == "POURED_RUBBER", (
            f"expected a POURED_RUBBER area, got {area['surfacing_material']}"
        )
        assert area["critical_fall_height_cm"] == 122, (
            f"expected a critical fall height of 122, got {area['critical_fall_height_cm']}"
        )
        assert a.expected_base_attenuation_depth(122, "POURED_RUBBER") == 5
        assert area["required_surfacing_depth_cm"] == 15, (
            "the 15 cm minimum outranks a base of 5 with either uplift, got "
            f"{area['required_surfacing_depth_cm']}"
        )
        assert area["required_surfacing_depth_cm"] != 10, (
            "the larger candidate of 10 cm must not be reported as the requirement"
        )
        a.assert_required_surfacing_depth(area, "CLAY", expected=15)

    def test_the_committed_depth_is_an_input_the_recompute_never_rewrites(self):
        """Placing a component derives the requirement and leaves the commitment.

        PRD: "Protective surfacing is specified per area by `surfacing_material`, either `ENGINEERED_WOOD_FIBER` or `POURED_RUBBER`, and by `surfacing_depth_cm`, the depth the design commits to, between 0 and 120 centimetres inclusive."

        Design: Difficulty/combinatorial_formula/surfacing_depth_nested_max_over_tier_age_and_soil_uplifts
        """
        scenario = _setup_three_areas_on_clay()

        assert scenario["area_one"]["surfacing_depth_cm"] == 40, (
            "the depth the design committed to must survive the recompute, got "
            f"{scenario['area_one']['surfacing_depth_cm']}"
        )
        assert scenario["area_two"]["surfacing_depth_cm"] == 40, (
            f"expected 40 cm, got {scenario['area_two']['surfacing_depth_cm']}"
        )
        assert scenario["area_three"]["surfacing_depth_cm"] == 20, (
            f"expected 20 cm, got {scenario['area_three']['surfacing_depth_cm']}"
        )
        for key in ("area_one", "area_two", "area_three"):
            area = scenario[key]
            assert area["required_surfacing_depth_cm"] == a.expected_required_surfacing_depth(
                area["critical_fall_height_cm"],
                area["surfacing_material"],
                area["age_group"],
                "CLAY",
            ), (
                f"the derived requirement on {key} does not follow from the fall "
                "height, the material, the age band and the soil"
            )
