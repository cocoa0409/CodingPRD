"""Genetic analysis, projected inbreeding and demographic need on a recommendation."""

from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INBREEDING_LIMIT_EXCEEDED
from test_helpers.assertions import assert_four_decimals, assert_money


def _full_sibling_world(api):
    """Two full siblings: both carry the same non-null sire and the same dam."""
    world = fx.base_world(api)
    sire = fx.accession(world, world.sender_id, "CR-SIRE", "MALE",
                        "2012-01-05", 40.00)
    dam = fx.accession(world, world.sender_id, "CR-DAM", "FEMALE",
                       "2013-02-06", 45.00)
    male = fx.accession(world, world.sender_id, "CR-101", "MALE", "2019-05-10",
                        12.45, sire_id=sire["id"], dam_id=dam["id"])
    female = fx.accession(world, world.receiver_id, "HB-201", "FEMALE",
                         "2020-03-15", 30.00, sire_id=sire["id"],
                         dam_id=dam["id"])
    world.m1_id, world.m1_version = male["id"], male["version"]
    world.f1_id, world.f1_version = female["id"], female["version"]
    world.extra["sire"], world.extra["dam"] = sire, dam
    return world


class TestProjectedInbreedingByAnalysisMode:
    """The projected figure is derived one way under each analysis mode."""

    def test_pedigree_only_ignores_a_supplied_molecular_panel(self, api):
        """An unrelated pair scores 0.0000 even when band sharing is supplied.

        PRD: "Under `PEDIGREE_ONLY` it equals the pedigree coefficient exactly,
        rounded half up to four decimal places; a `molecular_similarity_pct`
        submitted anyway is stored on the record but contributes nothing, so an
        unrelated pair scores 0.0000 and lands on `RECOMMENDED` every time."

        Design: Difficulty/dual_variant_calc/pedigree_only_vs_molecular_projected_inbreeding
        """
        world = fx.base_pair(api)
        response = api.create_recommendation(
            f.recommendation_payload(
                world.program_id, world.m1_id, world.m1_version,
                paired_animal_id=world.f1_id,
                sending_institution_id=world.sender_id,
                receiving_institution_id=world.receiver_id,
                analysis_mode="PEDIGREE_ONLY",
                molecular_similarity_pct=80.0,
            ),
            world.coordinator,
        )
        data = validate_success(response, 201)
        assert_four_decimals(data["kinship_coefficient"], 0.0000,
                             "kinship_coefficient")
        assert_four_decimals(data["projected_offspring_inbreeding"], 0.0000,
                             "projected_offspring_inbreeding")
        assert data["pairing_verdict"] == "RECOMMENDED"
        assert float(data["molecular_similarity_pct"]) == pytest.approx(80.0,
                                                                       abs=0.005)

    def test_molecular_mode_blends_four_tenths_of_the_band_sharing(self, api):
        """The same unrelated pair reaches 0.3200 once the panel is weighted.

        PRD: "The projected figure is then four tenths of that percentage
        expressed as a proportion of one — the percentage divided by 100 — plus
        six tenths of the pedigree coefficient, with the sum rounded half up to
        four decimal places."

        Design: Difficulty/dual_variant_calc/pedigree_only_vs_molecular_projected_inbreeding
        """
        world = fx.base_pair(api)
        response = api.create_recommendation(
            f.recommendation_payload(
                world.program_id, world.m1_id, world.m1_version,
                paired_animal_id=world.f1_id,
                sending_institution_id=world.sender_id,
                receiving_institution_id=world.receiver_id,
                analysis_mode="PEDIGREE_PLUS_MOLECULAR",
                molecular_similarity_pct=80.0,
            ),
            world.coordinator,
        )
        data = validate_success(response, 201)
        assert_four_decimals(data["kinship_coefficient"], 0.0000,
                             "kinship_coefficient")
        assert_four_decimals(data["projected_offspring_inbreeding"], 0.3200,
                             "projected_offspring_inbreeding")
        assert data["pairing_verdict"] == "NOT_RECOMMENDED"

    def test_full_siblings_carry_their_pedigree_coefficient_through_both_modes(
            self, api):
        """Full sibs score 0.2500 on pedigree and 0.3500 once markers weigh in.

        PRD: "The two animals share both a non-null sire and a non-null dam:
        they are **full siblings**, contributing 0.2500."

        Design: Difficulty/dual_variant_calc/pedigree_only_vs_molecular_projected_inbreeding
        """
        world = _full_sibling_world(api)
        pedigree_only = validate_success(
            api.create_recommendation(
                f.recommendation_payload(
                    world.program_id, world.m1_id, world.m1_version,
                    paired_animal_id=world.f1_id,
                    sending_institution_id=world.sender_id,
                    receiving_institution_id=world.receiver_id,
                    analysis_mode="PEDIGREE_ONLY",
                ),
                world.coordinator,
            ),
            201,
        )
        assert_four_decimals(pedigree_only["kinship_coefficient"], 0.2500,
                             "kinship_coefficient")
        assert_four_decimals(pedigree_only["projected_offspring_inbreeding"],
                             0.2500, "projected_offspring_inbreeding")
        assert pedigree_only["pairing_verdict"] == "NOT_RECOMMENDED"

        refreshed = world.read_animal(world.m1_id)
        molecular = validate_success(
            api.create_recommendation(
                f.recommendation_payload(
                    world.program_id, world.m1_id, refreshed["version"],
                    paired_animal_id=world.f1_id,
                    sending_institution_id=world.sender_id,
                    receiving_institution_id=world.receiver_id,
                    analysis_mode="PEDIGREE_PLUS_MOLECULAR",
                    molecular_similarity_pct=50.0,
                ),
                world.coordinator,
            ),
            201,
        )
        assert_four_decimals(molecular["kinship_coefficient"], 0.2500,
                             "kinship_coefficient")
        assert_four_decimals(molecular["projected_offspring_inbreeding"], 0.3500,
                             "projected_offspring_inbreeding")

    def test_a_non_breeding_directive_leaves_both_coefficients_null(self, api):
        """A HOLD directive reports NOT_APPLICABLE with no coefficients at all.

        PRD: "For any recommendation whose type is not `BREED_WITH` the verdict
        is `NOT_APPLICABLE`, and both `kinship_coefficient` and
        `projected_offspring_inbreeding` are null on the record."

        Design: Difficulty/dual_variant_calc/pedigree_only_vs_molecular_projected_inbreeding
        """
        world = fx.base_pair(api)
        data = validate_success(
            api.create_recommendation(
                f.recommendation_payload(
                    world.program_id, world.m1_id, world.m1_version,
                    recommendation_type="HOLD", paired_animal_id=None,
                ),
                world.coordinator,
            ),
            201,
        )
        assert data["pairing_verdict"] == "NOT_APPLICABLE"
        assert data["kinship_coefficient"] is None
        assert data["projected_offspring_inbreeding"] is None


class TestDemographicNeedAndGeneticValue:
    """The management-tier weight scales the whole demographic composite."""

    def _recommend(self, world, program_id, male, female):
        return validate_success(
            world.api.create_recommendation(
                f.recommendation_payload(
                    program_id, male["id"], male["version"],
                    paired_animal_id=female["id"],
                    sending_institution_id=world.sender_id,
                    receiving_institution_id=world.receiver_id,
                ),
                {"X-User-Id": program_id, "X-User-Role": "ProgramCoordinator"},
            ),
            201,
        )

    def test_ssp_red_scores_the_full_weighted_composite(self, api):
        """Target 300, population 2, founder 12.45, kinship 0 gives 0.9593.

        PRD: "Those three rounded factors are combined as one half of the
        population gap plus three tenths of founder scarcity plus two tenths of
        kinship relief — weights that are fixed and sum to 1 — and the composite
        is then multiplied by the programme's management-tier weight: 0.6 for
        `SSP_GREEN`, 0.8 for `SSP_YELLOW`, 1.0 for `SSP_RED` and 0.3 for
        `STUDBOOK_ONLY`."

        Design: Difficulty/combinatorial_formula/demographic_need_index_nonlinear_program_weighted_composite
        """
        world = fx.base_pair(api)
        assert world.read_program()["current_population_count"] == 2
        data = self._recommend(
            world, world.program_id,
            {"id": world.m1_id, "version": world.m1_version},
            {"id": world.f1_id},
        )
        assert_four_decimals(data["demographic_need_index"], 0.9593,
                             "demographic_need_index")
        assert_money(data["genetic_value_score"], 95.93, "genetic_value_score")

    def test_studbook_only_scales_the_identical_demographics_down(self, api):
        """The same demographics under STUDBOOK_ONLY score 0.2878 and 28.78.

        PRD: "Because the tier weight scales the whole composite after the
        weighted sum, a `STUDBOOK_ONLY` programme can never out-score an
        `SSP_RED` programme on identical demographics."

        Design: Difficulty/combinatorial_formula/demographic_need_index_nonlinear_program_weighted_composite
        """
        world = fx.base_pair(api, program_type="STUDBOOK_ONLY")
        assert world.read_program()["current_population_count"] == 2
        data = self._recommend(
            world, world.program_id,
            {"id": world.m1_id, "version": world.m1_version},
            {"id": world.f1_id},
        )
        assert_four_decimals(data["demographic_need_index"], 0.2878,
                             "demographic_need_index")
        assert_money(data["genetic_value_score"], 28.78, "genetic_value_score")

    def test_genetic_value_score_is_the_rounded_index_times_one_hundred(self, api):
        """The score is derived from the rounded index, not an intermediate.

        PRD: "The `genetic_value_score` follows from it directly: it is the
        *rounded* `demographic_need_index` multiplied by 100, rounded half up to
        two decimal places."

        Design: Difficulty/combinatorial_formula/demographic_need_index_nonlinear_program_weighted_composite
        """
        world = fx.base_pair(api)
        data = self._recommend(
            world, world.program_id,
            {"id": world.m1_id, "version": world.m1_version},
            {"id": world.f1_id},
        )
        index = float(data["demographic_need_index"])
        assert_money(data["genetic_value_score"], round(index * 100, 2),
                     "genetic_value_score")
        assert_four_decimals(data["demographic_need_index"], 0.9593,
                             "demographic_need_index")


class TestMolecularInbreedingExactLimit:
    """The 0.125 ceiling is closed at its lower edge and read after rounding."""

    @staticmethod
    def _molecular_rec(world, subject_id, subject_version, paired_id,
                       molecular_similarity_pct):
        return validate_success(
            world.api.create_recommendation(
                f.recommendation_payload(
                    world.program_id, subject_id, subject_version,
                    paired_animal_id=paired_id,
                    sending_institution_id=world.sender_id,
                    receiving_institution_id=world.receiver_id,
                    analysis_mode="PEDIGREE_PLUS_MOLECULAR",
                    molecular_similarity_pct=molecular_similarity_pct,
                ),
                world.coordinator,
            ),
            201,
        )

    def test_band_sharing_of_exactly_31_25_lands_on_the_ceiling(self, api):
        """31.25 percent projects to exactly 0.1250 and is NOT_RECOMMENDED.

        PRD: "a pair with no recorded relationship whatsoever, whose pedigree
        coefficient is 0.0000, is pushed all the way to `NOT_RECOMMENDED` once
        its band sharing reaches 31.25 percent"

        Design: Difficulty/boundary_precision_check/molecular_inbreeding_exact_limit_blocks_endorsement
        """
        world = fx.base_pair(api)
        data = self._molecular_rec(world, world.m1_id, world.m1_version,
                                   world.f1_id, 31.25)
        assert_four_decimals(data["kinship_coefficient"], 0.0000,
                             "kinship_coefficient")
        assert_four_decimals(data["projected_offspring_inbreeding"], 0.1250,
                             "projected_offspring_inbreeding")
        assert data["pairing_verdict"] == "NOT_RECOMMENDED"

    def test_endorsement_of_the_ceiling_pair_is_refused_and_persists_nothing(
            self, api):
        """A NOT_RECOMMENDED directive stays PROPOSED and leaves genetics alone.

        PRD: "a `BREED_WITH` directive whose `pairing_verdict` is
        `NOT_RECOMMENDED` may never be endorsed, and the attempt is refused with
        `ERR_INBREEDING_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/molecular_inbreeding_exact_limit_blocks_endorsement
        """
        world = fx.base_pair(api)
        data = self._molecular_rec(world, world.m1_id, world.m1_version,
                                   world.f1_id, 31.25)
        response = api.endorse_recommendation(data["id"], world.sender)
        validate_error(response, ERR_INBREEDING_LIMIT_EXCEEDED)
        assert world.read_recommendation(data["id"])["status"] == "PROPOSED"
        assert world.read_animal(world.m1_id)["genetic_designation"] == "UNEVALUATED"
        assert world.read_animal(world.f1_id)["genetic_designation"] == "UNEVALUATED"

    def test_one_hundredth_below_the_ceiling_is_conditional_and_endorsable(
            self, api):
        """31.2 percent projects to 0.1248, which is CONDITIONAL, so it endorses.

        PRD: "A `CONDITIONAL` verdict, by contrast, is endorsable exactly like a
        `RECOMMENDED` one."

        Design: Difficulty/boundary_precision_check/molecular_inbreeding_exact_limit_blocks_endorsement
        """
        world = fx.base_pair(api)
        data = self._molecular_rec(world, world.m1_id, world.m1_version,
                                   world.f1_id, 31.2)
        assert_four_decimals(data["projected_offspring_inbreeding"], 0.1248,
                             "projected_offspring_inbreeding")
        assert data["pairing_verdict"] == "CONDITIONAL"
        endorsed = validate_success(
            api.endorse_recommendation(data["id"], world.sender)
        )
        assert endorsed["status"] == "ENDORSED"
        assert world.read_animal(world.m1_id)["genetic_designation"] == \
            "BREED_RECOMMENDED"
        assert world.read_animal(world.f1_id)["genetic_designation"] == \
            "BREED_RECOMMENDED"
