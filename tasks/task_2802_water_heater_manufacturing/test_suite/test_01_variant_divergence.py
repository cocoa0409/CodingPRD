"""Two computed reads whose variants disagree on the same rows.

The warranty analysis and the recall completion read both publish two figures
over one population; each pair shares its numerator and differs only in the
denominator the PRD names for it.
"""

from test_helpers import (
    approx2,
    campaign_notices,
    compliance_engineer_headers,
    data_of,
    fixtures as x,
    label_unit,
    make_full_plant,
    plant_operator_headers,
    ship_unit,
    validate_success,
    warranty_analyst_headers,
)


def _two_unit_cohort(api):
    """One 2026-08 cohort holding a very-hard 5-month unit and a soft 3-month unit.

    Both units are drawn from the same released lot of the same model, so the
    only thing that separates them is the installation water and the instant
    each one shipped.
    """
    plant = make_full_plant(api)
    u1 = ship_unit(api, plant, hardness_gpg=12.0)
    x.set_clock(api, "2026-10-05T06:00:00Z")
    u2 = ship_unit(api, plant, hardness_gpg=2.0)
    x.set_clock(api, "2027-02-01T00:00:00Z")
    claim = x.make_open_claim(api, u1, reported_water_hardness_gpg=12.0)
    data_of(api.validate_claim(claim["id"], warranty_analyst_headers()))
    return plant, u1, u2


class TestTankFailureRateVariants:
    """The naive and exposure-weighted rates over one shipped cohort."""

    def test_01_cohort_naive_rate_divides_by_the_unit_head_count(self, api):
        """The default variant reports one claim over two shipped units.

        PRD: "The `COHORT_NAIVE` variant — the field-reporting view, and the one
        used when `variant` is omitted — divides `tank_leak_claim_count` by
        `shipped_unit_count` and multiplies by 1,000,000, treating every shipped
        unit as one unit of equal risk regardless of age or water chemistry."

        Design: Difficulty/dual_variant_calc/tank_failure_rate_cohort_naive_vs_exposure_weighted
        """
        plant, _u1, _u2 = _two_unit_cohort(api)

        report = validate_success(
            api.get_warranty_analysis(
                plant.model_id,
                warranty_analyst_headers(),
                {"production_period": "2026-08"},
            )
        )

        assert report["variant"] == "COHORT_NAIVE"
        assert report["shipped_unit_count"] == 2
        assert report["tank_leak_claim_count"] == 1
        assert report["failure_rate_ppm"] == approx2(500000.0)

    def test_02_exposure_weighted_rate_divides_by_weighted_unit_months(self, api):
        """The same claim over 11.40 weighted unit-months reports 87719.3 ppm.

        PRD: "The `EXPOSURE_WEIGHTED` variant — the reliability-engineering view —
        divides the same `tank_leak_claim_count` by `weighted_exposure_unit_months`
        and multiplies by 1,000,000, expressing the rate per million weighted
        unit-months instead."

        Design: Difficulty/dual_variant_calc/tank_failure_rate_cohort_naive_vs_exposure_weighted
        """
        plant, _u1, _u2 = _two_unit_cohort(api)

        report = validate_success(
            api.get_warranty_analysis(
                plant.model_id,
                warranty_analyst_headers(),
                {"production_period": "2026-08", "variant": "EXPOSURE_WEIGHTED"},
            )
        )

        assert report["variant"] == "EXPOSURE_WEIGHTED"
        assert report["shipped_unit_count"] == 2
        assert report["tank_leak_claim_count"] == 1
        assert report["failure_rate_ppm"] == approx2(87719.3)

    def test_03_weighted_exposure_and_band_mix_are_identical_under_both_variants(
        self, api
    ):
        """Only the rate diverges: the exposure sum and the band mix do not.

        PRD: "`weighted_exposure_unit_months` is the sum, across the cohort, of
        each unit's `months_in_service` multiplied by its `hardness_factor`,
        rounded to two decimal places half up, and it is the exposure measure that
        makes a soft-water unit count for less than a very-hard-water unit of the
        same age."

        Design: Difficulty/dual_variant_calc/tank_failure_rate_cohort_naive_vs_exposure_weighted
        """
        plant, _u1, _u2 = _two_unit_cohort(api)

        naive = validate_success(
            api.get_warranty_analysis(
                plant.model_id,
                warranty_analyst_headers(),
                {"production_period": "2026-08", "variant": "COHORT_NAIVE"},
            )
        )
        weighted = validate_success(
            api.get_warranty_analysis(
                plant.model_id,
                warranty_analyst_headers(),
                {"production_period": "2026-08", "variant": "EXPOSURE_WEIGHTED"},
            )
        )

        for report in (naive, weighted):
            assert report["weighted_exposure_unit_months"] == approx2(11.40)
            assert report["soft_unit_count"] == 1
            assert report["moderate_unit_count"] == 0
            assert report["hard_unit_count"] == 0
            assert report["very_hard_unit_count"] == 1

    def test_04_each_unit_carries_the_months_and_factor_the_weighting_reads(self, api):
        """5 months at 1.80 and 3 months at 0.80 are what sum to 11.40.

        PRD: "From shipment onward a unit read reports `months_in_service`,
        recomputed on every read as the whole number of 30-day months that have
        elapsed between `shipped_at` and the current logical clock, truncated
        downward and never rounded up; it stays null while `shipped_at` is null."

        Design: Difficulty/dual_variant_calc/tank_failure_rate_cohort_naive_vs_exposure_weighted
        """
        _plant, u1, u2 = _two_unit_cohort(api)

        very_hard = validate_success(api.get_heater_unit(u1, plant_operator_headers()))
        soft = validate_success(api.get_heater_unit(u2, plant_operator_headers()))

        assert very_hard["months_in_service"] == 5
        assert very_hard["hardness_factor"] == approx2(1.80)
        assert soft["months_in_service"] == 3
        assert soft["hardness_factor"] == approx2(0.80)


def _announced_three_unit_recall(api):
    """Three serialised units of one model, two shipped and one still in the plant.

    RC-001 is scoped over the whole serial range and announced, so the fan-out
    has issued notices to the two shipped units and held the third.
    """
    plant = make_full_plant(api)
    u1 = ship_unit(api, plant, hardness_gpg=12.0)
    u2 = ship_unit(api, plant, hardness_gpg=2.0)
    u3 = label_unit(api, plant)
    campaign = x.make_announced_campaign(
        api,
        plant.model_id,
        "GX50-T-202608-00001",
        "GX50-T-202608-00003",
    )
    notices = campaign_notices(api, campaign["id"])
    data_of(api.notify_notice(notices[0]["id"], warranty_analyst_headers()))
    return plant, campaign, notices, (u1, u2, u3)


class TestRecallCompletionVariants:
    """The notice-based and population-based completion percentages."""

    def test_05_notice_based_completion_divides_by_the_issued_notices(self, api):
        """One remedy out of two issued notices reads 50.00 percent.

        PRD: "`completion_pct_notice_based` divides `remedied_count` by
        `notice_count`, multiplies by 100 and rounds to two decimal places half up:
        it measures how well the notification programme performed against the
        owners it could write to."

        Design: Difficulty/dual_variant_calc/recall_completion_notice_based_vs_population_based
        """
        _plant, campaign, notices, _units = _announced_three_unit_recall(api)

        data_of(api.remedy_notice(notices[0]["id"], warranty_analyst_headers()))
        completion = validate_success(
            api.get_campaign_completion(campaign["id"], warranty_analyst_headers())
        )

        assert completion["notice_count"] == 2
        assert completion["remedied_count"] == 1
        assert completion["unreachable_count"] == 0
        assert completion["completion_pct_notice_based"] == approx2(50.00)

    def test_06_population_based_completion_divides_by_the_scoped_population(self, api):
        """The same remedy over three scoped units reads 33.33 percent.

        PRD: "`completion_pct_population_based` divides the same `remedied_count`
        by `affected_unit_count`, multiplies by 100 and rounds to two decimal
        places half up: it measures the recall against every unit in scope,
        including the in-plant units that were held rather than notified."

        Design: Difficulty/dual_variant_calc/recall_completion_notice_based_vs_population_based
        """
        _plant, campaign, notices, _units = _announced_three_unit_recall(api)

        data_of(api.remedy_notice(notices[0]["id"], warranty_analyst_headers()))
        completion = validate_success(
            api.get_campaign_completion(campaign["id"], warranty_analyst_headers())
        )

        assert completion["affected_unit_count"] == 3
        assert completion["remedied_count"] == 1
        assert completion["completion_pct_population_based"] == approx2(33.33)

    def test_07_the_held_in_plant_unit_is_what_separates_the_two_denominators(self, api):
        """The labelled unit enlarges the population without entering the notices.

        PRD: "Every affected unit whose `build_status` is `ASSEMBLED` or `LABELED`
        is instead moved to `HELD` with `hold_reason_code` set to `RECALL_SCOPE`
        and `held_from_status` set to the status it was holding, and receives
        **no** notice at all — there is no owner to notify for a unit that never
        left the plant."

        Design: Difficulty/dual_variant_calc/recall_completion_notice_based_vs_population_based
        """
        plant, _campaign, notices, units = _announced_three_unit_recall(api)
        _u1, _u2, u3 = units

        held = validate_success(api.get_heater_unit(u3, plant_operator_headers()))
        model = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )

        assert len(notices) == 2
        assert held["build_status"] == "HELD"
        assert held["hold_reason_code"] == "RECALL_SCOPE"
        assert model["release_status"] == "RESTRICTED"
        assert model["held_unit_count"] == 1

    def test_08_the_first_remedy_moves_the_campaign_to_in_remedy(self, api):
        """Recording the first remedy bubbles the campaign out of ANNOUNCED.

        PRD: "The first remedy recorded against a campaign bubbles up and moves
        that campaign `ANNOUNCED → IN_REMEDY`, incrementing the campaign's
        `version`; subsequent remedies leave the campaign in `IN_REMEDY` and do
        not move it again."

        Design: Difficulty/dual_variant_calc/recall_completion_notice_based_vs_population_based
        """
        _plant, campaign, notices, _units = _announced_three_unit_recall(api)

        data_of(api.remedy_notice(notices[0]["id"], warranty_analyst_headers()))
        after = validate_success(
            api.get_recall_campaign(campaign["id"], warranty_analyst_headers())
        )

        assert after["status"] == "IN_REMEDY"
