"""Warranty coverage variants and the pricing of a replacement-part purchase.

Every test starts against an empty database with the logical clock at its
mandatory startup default and builds its own preconditions from
`test_helpers.fixtures`.
"""

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

INSTALLED_ON = "2026-08-15"
FAILURE_DATE = "2029-08-20"


# --------------------------------------------------------------------------
# Local setup helpers
# --------------------------------------------------------------------------
def _setup_installed_climber_and_slide_project() -> dict:
    """An INSTALLED project whose single toddler area holds one metal climber
    and one plastic slide, both at their no-cost default colour.

    Both models carry a ten-year term and a list price of 215450 cents, so the
    two placements differ in category and in nothing else that coverage reads.
    """
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Riverbend Park", "budget_cents": 600000}
    )
    area_id = scenario["area"]["id"]
    scenario["climber_placement"] = fx.create_validated_placement(
        area_id,
        scenario["climber"]["id"],
        color_choice=scenario["climber"]["color_options"][0],
        x_start_cm=400,
        quantity=1,
    )
    scenario["slide_placement"] = fx.create_validated_placement(
        area_id,
        scenario["slide"]["id"],
        color_choice=scenario["slide"]["color_options"][0],
        x_start_cm=1300,
        quantity=1,
    )
    scenario["rendering"] = fx.issue_rendering(
        scenario["project"]["id"], scenario["standard"]["id"]
    )
    return fx.setup_installed_project(scenario=scenario, installed_on=INSTALLED_ON)


def _file_claim(project_id: str, placement_id: str) -> dict:
    """File one claim for a single failed unit on the shared failure date."""
    return fx.create_warranty_claim(
        project_id, placement_id, FAILURE_DATE, quantity=1
    )


def _setup_two_claims_on_one_installed_project() -> dict:
    """Both claims filed on the same day against the same installed project."""
    scenario = _setup_installed_climber_and_slide_project()
    fx.set_clock_to_date(FAILURE_DATE)
    project_id = scenario["project"]["id"]
    scenario["climber_claim"] = _file_claim(
        project_id, scenario["climber_placement"]["id"]
    )
    scenario["slide_claim"] = _file_claim(
        project_id, scenario["slide_placement"]["id"]
    )
    return scenario


def _setup_legacy_and_current_placements() -> dict:
    """One CONSULTATION project holding two DRAFT placements: a LEGACY plastic
    slide listed at 215450 cents and a current deck listed at 247000 cents."""
    standard = fx.create_active_standard()
    legacy_model = fx.create_certified_model(f.slide_model_payload())
    current_model = fx.create_certified_model(
        f.deck_model_payload(sku="DECK-V2-247", unit_price_cents=247000)
    )
    legacy_model = fx.set_model_lifecycle(legacy_model["id"], "LEGACY")
    project = fx.create_project_in_consultation(
        client_name="Willow Bend", budget_cents=900000
    )
    area = fx.create_play_area(project["id"])
    legacy_placement = fx.create_placement(
        area["id"],
        legacy_model["id"],
        color_choice=legacy_model["color_options"][0],
        x_start_cm=1300,
        quantity=1,
    )
    current_placement = fx.create_placement(
        area["id"],
        current_model["id"],
        color_choice=current_model["color_options"][0],
        x_start_cm=700,
        quantity=1,
    )
    return {
        "standard": standard,
        "legacy_model": legacy_model,
        "current_model": current_model,
        "project": project,
        "area": area,
        "legacy_placement": legacy_placement,
        "current_placement": current_placement,
    }


def _buy_part(placement_id: str, replacement_model_id: str, quantity: int) -> dict:
    """Purchase replacement parts for one placement and return it."""
    return fx.retrofit_placement(placement_id, replacement_model_id, quantity)


# --------------------------------------------------------------------------
# Two claims, identical commercial inputs, two coverage variants
# --------------------------------------------------------------------------
class TestProratedVersusStepCoverage:
    def test_prorated_and_step_coverage_diverge_on_identical_claim_inputs(self):
        """Category alone selects the variant, and the two disagree here.

        PRD: "Coverage is thus a step function rather than a ramp, and on identical inputs the two variants genuinely diverge: the same ten-year term at elapsed year 3 pays 70 percent under `PRORATED` and 100 percent under `STEP`."

        Design: Difficulty/dual_variant_calc/warranty_prorated_vs_step_diverge_on_identical_claim_inputs
        """
        scenario = _setup_two_claims_on_one_installed_project()
        climber_claim = scenario["climber_claim"]
        slide_claim = scenario["slide_claim"]

        a.assert_warranty_claim(climber_claim)
        a.assert_warranty_claim(slide_claim)

        assert climber_claim["claim_category"] == "METAL_CLIMBER", (
            f"expected claim_category METAL_CLIMBER, got {climber_claim['claim_category']}"
        )
        assert climber_claim["coverage_variant"] == "PRORATED", (
            f"expected coverage_variant PRORATED, got {climber_claim['coverage_variant']}"
        )
        assert slide_claim["claim_category"] == "PLASTIC_SLIDE", (
            f"expected claim_category PLASTIC_SLIDE, got {slide_claim['claim_category']}"
        )
        assert slide_claim["coverage_variant"] == "STEP", (
            f"expected coverage_variant STEP, got {slide_claim['coverage_variant']}"
        )
        assert climber_claim["covered_pct"] == 70, (
            "a ten-year term claimed in elapsed year 3 covers 70 percent when prorated, got "
            f"{climber_claim['covered_pct']}"
        )
        assert slide_claim["covered_pct"] == 100, (
            "the same term under the step function still covers 100 percent, got "
            f"{slide_claim['covered_pct']}"
        )
        assert a.expected_covered_pct("METAL_CLIMBER", 10, 3) == 70
        assert a.expected_covered_pct("PLASTIC_SLIDE", 10, 3) == 100

    def test_reimbursement_follows_the_diverging_covered_percentages(self):
        """The same list price and quantity yield two reimbursements.

        PRD: "`reimbursement_cents` is then the model's `unit_price_cents` multiplied by the claim's `quantity` multiplied by `covered_pct`, divided by one hundred, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/warranty_prorated_vs_step_diverge_on_identical_claim_inputs
        """
        scenario = _setup_two_claims_on_one_installed_project()
        climber_claim = scenario["climber_claim"]
        slide_claim = scenario["slide_claim"]

        a.assert_cents(climber_claim["reimbursement_cents"], "reimbursement_cents")
        a.assert_cents(slide_claim["reimbursement_cents"], "reimbursement_cents")

        assert climber_claim["reimbursement_cents"] == 150815, (
            "expected 150815 cents from 215450 at 70 percent, got "
            f"{climber_claim['reimbursement_cents']}"
        )
        assert slide_claim["reimbursement_cents"] == 215450, (
            "expected the full 215450 cents at 100 percent, got "
            f"{slide_claim['reimbursement_cents']}"
        )
        delta = slide_claim["reimbursement_cents"] - climber_claim["reimbursement_cents"]
        assert delta == 64635, (
            f"the two variants must differ by 64635 cents on this claim pair, got {delta}"
        )

    def test_both_claims_share_the_same_elapsed_whole_year(self):
        """Installation date and failure date are shared, so elapsed_years is.

        PRD: "`elapsed_years` is the whole number of years between installation and failure: take the number of days from the project's `installed_on` to the claim's `failure_date`, divide by 365, and discard any fraction, rounding down."

        Design: Difficulty/dual_variant_calc/warranty_prorated_vs_step_diverge_on_identical_claim_inputs
        """
        scenario = _setup_two_claims_on_one_installed_project()
        project = fx.get_project(scenario["project"]["id"])

        assert project["installed_on"] == INSTALLED_ON, (
            f"expected installed_on {INSTALLED_ON}, got {project['installed_on']}"
        )
        assert a.days_between(INSTALLED_ON, FAILURE_DATE) == 1101, (
            "the claim pair is filed 1101 days after installation"
        )
        for label, claim in (
            ("climber", scenario["climber_claim"]),
            ("slide", scenario["slide_claim"]),
        ):
            assert claim["failure_date"] == FAILURE_DATE, (
                f"the {label} claim froze the wrong failure_date: {claim['failure_date']}"
            )
            assert claim["elapsed_years"] == 3, (
                f"expected elapsed_years 3 on the {label} claim, got {claim['elapsed_years']}"
            )
            assert claim["status"] == "SUBMITTED", (
                f"a filed claim starts SUBMITTED, got {claim['status']} on the {label} claim"
            )


# --------------------------------------------------------------------------
# The handling waiver is decided on the line, not on the total
# --------------------------------------------------------------------------
class TestRetrofitHandlingWaiver:
    def test_legacy_surcharge_lifts_the_line_over_the_threshold_and_waives_handling(self):
        """An eighteen-percent surcharge is added before the waiver is judged.

        PRD: "First the surcharge: when the replacement model's `lifecycle_status` is `LEGACY`, `retrofit_unit_price_cents` is the model's `unit_price_cents` plus eighteen percent of that `unit_price_cents` rounded half up to whole cents, and `legacy_surcharge_applied` is set true; otherwise `retrofit_unit_price_cents` is simply the model's `unit_price_cents` and `legacy_surcharge_applied` is false."

        Design: Difficulty/combinatorial_formula/retrofit_handling_waiver_evaluated_on_line_not_total
        """
        scenario = _setup_legacy_and_current_placements()
        placement = _buy_part(
            scenario["legacy_placement"]["id"], scenario["legacy_model"]["id"], 1
        )

        a.assert_placement(placement)
        assert placement["legacy_surcharge_applied"] is True, (
            "a LEGACY replacement model must set legacy_surcharge_applied, got "
            f"{placement['legacy_surcharge_applied']}"
        )
        assert placement["retrofit_unit_price_cents"] == 254231, (
            "expected 215450 plus a surcharge of 38781, got "
            f"{placement['retrofit_unit_price_cents']}"
        )
        assert placement["retrofit_handling_cents"] == 0, (
            "a line of 254231 cents waives handling, got "
            f"{placement['retrofit_handling_cents']}"
        )
        assert placement["retrofit_total_cents"] == 254231, (
            f"expected a total of 254231 cents, got {placement['retrofit_total_cents']}"
        )

    def test_handling_is_charged_on_a_line_below_the_threshold_whose_total_clears_it(self):
        """247000 attracts handling even though 250500 exceeds the threshold.

        PRD: "A line of exactly 250000 cents therefore waives handling, while a line of 247000 cents attracts the 3500-cent charge and totals 250500 cents — above the threshold, yet handling still applies, because the decision was made on 247000."

        Design: Difficulty/combinatorial_formula/retrofit_handling_waiver_evaluated_on_line_not_total
        """
        scenario = _setup_legacy_and_current_placements()
        placement = _buy_part(
            scenario["current_placement"]["id"], scenario["current_model"]["id"], 1
        )

        a.assert_placement(placement)
        assert placement["legacy_surcharge_applied"] is False, (
            "an ACTIVE replacement model carries no surcharge, got "
            f"{placement['legacy_surcharge_applied']}"
        )
        assert placement["retrofit_unit_price_cents"] == 247000, (
            f"expected the plain list price 247000, got {placement['retrofit_unit_price_cents']}"
        )
        assert placement["retrofit_handling_cents"] == 3500, (
            "a line of 247000 cents attracts the flat 3500-cent charge, got "
            f"{placement['retrofit_handling_cents']}"
        )
        assert placement["retrofit_total_cents"] == 250500, (
            f"expected a total of 250500 cents, got {placement['retrofit_total_cents']}"
        )
        assert placement["retrofit_total_cents"] > 250000, (
            "the resulting total clears the threshold the waiver never read"
        )

    def test_doubling_the_quantity_flips_the_same_placements_waiver(self):
        """The threshold is read on the line, so quantity moves the waiver.

        PRD: "When the line amount is greater than or equal to 250000 cents, `retrofit_handling_cents` is 0; otherwise it is a flat 3500 cents."

        Design: Difficulty/combinatorial_formula/retrofit_handling_waiver_evaluated_on_line_not_total
        """
        scenario = _setup_legacy_and_current_placements()
        placement_id = scenario["current_placement"]["id"]
        model_id = scenario["current_model"]["id"]

        single = _buy_part(placement_id, model_id, 1)
        assert single["retrofit_quantity"] == 1, (
            f"expected retrofit_quantity 1, got {single['retrofit_quantity']}"
        )
        assert single["retrofit_handling_cents"] == 3500, (
            f"a single unit is charged handling, got {single['retrofit_handling_cents']}"
        )

        doubled = _buy_part(placement_id, model_id, 2)
        a.assert_placement(doubled)
        assert doubled["retrofit_quantity"] == 2, (
            f"expected retrofit_quantity 2, got {doubled['retrofit_quantity']}"
        )
        assert doubled["retrofit_handling_cents"] == 0, (
            "a line of 494000 cents waives handling, got "
            f"{doubled['retrofit_handling_cents']}"
        )
        assert doubled["retrofit_total_cents"] == 494000, (
            f"expected a total of 494000 cents, got {doubled['retrofit_total_cents']}"
        )

    def test_a_like_for_like_part_sale_leaves_the_placement_status_unchanged(self):
        """Only a superseding replacement on a demoted placement moves status.

        PRD: "Where the placement was in `NEEDS_RECERTIFICATION` and the replacement supersedes its model, the placement's `component_model_id` is rewritten to the replacement and its `status` moves `NEEDS_RECERTIFICATION → VALIDATED`."

        Design: Difficulty/combinatorial_formula/retrofit_handling_waiver_evaluated_on_line_not_total
        """
        scenario = _setup_legacy_and_current_placements()
        legacy = _buy_part(
            scenario["legacy_placement"]["id"], scenario["legacy_model"]["id"], 1
        )
        current = _buy_part(
            scenario["current_placement"]["id"], scenario["current_model"]["id"], 1
        )

        assert legacy["status"] == "DRAFT", (
            f"the legacy placement must stay DRAFT, got {legacy['status']}"
        )
        assert current["status"] == "DRAFT", (
            f"the current placement must stay DRAFT, got {current['status']}"
        )
        assert legacy["component_model_id"] == scenario["legacy_model"]["id"], (
            "a like-for-like sale must not rewrite component_model_id"
        )
        assert current["component_model_id"] == scenario["current_model"]["id"], (
            "a like-for-like sale must not rewrite component_model_id"
        )
