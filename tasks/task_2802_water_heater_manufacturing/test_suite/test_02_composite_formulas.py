"""Multi-stage arithmetic whose stages and ordering are pinned by the contract.

The UEF floor composes a tier lookup with a sample derate and a capped credit,
the certified ratings round per test before averaging, and the recall admin fee
picks its band from the provisional subtotal only.
"""

import pytest

from test_helpers import (
    approx2,
    approx4,
    certification_payload,
    compliance_engineer_headers,
    data_of,
    efficiency_test_payload,
    fixtures as x,
    heat_pump_model_payload,
    large_gas_model_payload,
    make_full_plant,
    make_model,
    make_test_cell,
    product_model_payload,
    quality_inspector_headers,
    recall_campaign_payload,
    scope_payload,
    ship_unit,
    USER_ENGINEER,
    validate_success,
    warranty_analyst_headers,
    WINDOW_AUG02_06_10,
    WINDOW_AUG03_06_10,
    WINDOW_AUG04_06_10,
)

SERIAL_FIRST = "GX50-T-202608-00001"


def _three_scheduled_uef_tests(api):
    """One scheduled UEF test per model, each hitting a different cell of the floor.

    GX50-T is small-tier gas at R-20 with a three-unit sample, HP65-B is
    large-tier heat pump at R-25 with a two-unit sample, and GX75-R is
    large-tier gas at R-16 with a single-unit sample.
    """
    models = {
        "small_gas": make_model(api, product_model_payload())["id"],
        "large_heat_pump": make_model(api, heat_pump_model_payload())["id"],
        "large_gas": make_model(api, large_gas_model_payload())["id"],
    }
    cell_id = make_test_cell(api)["id"]
    tests = {}
    for key, window, sample in (
        ("small_gas", WINDOW_AUG02_06_10, 3),
        ("large_heat_pump", WINDOW_AUG03_06_10, 2),
        ("large_gas", WINDOW_AUG04_06_10, 1),
    ):
        tests[key] = data_of(
            api.create_efficiency_test(
                efficiency_test_payload(
                    models[key], cell_id, window=window, sample_size=sample
                ),
                compliance_engineer_headers(),
            )
        )["id"]
    x.set_clock(api, "2026-08-05T06:00:00Z")
    return models, tests


class TestUefEffectiveMinimumComposition:
    """The three-stage federal floor and the margin it produces."""

    @pytest.mark.parametrize(
        "model_key,measured,expected_minimum,expected_margin,expected_status",
        [
            ("small_gas", 0.585, 0.5600, 0.0250, "PASSED"),
            ("large_heat_pump", 2.95, 2.8800, 0.0700, "PASSED"),
            ("large_gas", 0.565, 0.5700, -0.0050, "FAILED"),
        ],
    )
    def test_01_effective_minimum_composes_tier_derate_and_capped_credit(
        self, api, model_key, measured, expected_minimum, expected_margin, expected_status
    ):
        """Each row exercises a different cell of all three stages at once.

        PRD: "**Fifth**, `effective_minimum` is the base minimum plus the derate
        minus the credit, rounded half up to four decimal places; the derate is
        never reapplied after the credit has been taken."

        Design: Difficulty/combinatorial_formula/uef_effective_minimum_multistage_tier_derate_credit
        """
        _models, tests = _three_scheduled_uef_tests(api)

        recorded = validate_success(
            api.record_test_result(
                tests[model_key],
                {"measured_value": measured},
                quality_inspector_headers(),
            )
        )

        assert recorded["effective_minimum"] == approx4(expected_minimum)
        assert recorded["margin"] == approx4(expected_margin)
        assert recorded["status"] == expected_status

    def test_02_every_recorded_result_moves_its_model_to_test_pending_unrated(self, api):
        """All three models leave UNCERTIFIED yet none publishes a rating.

        PRD: "Both branches store `measured_value`, `effective_minimum`, `margin`
        and `recorded_at`, the latter being the logical-clock instant at which the
        result was accepted, and both have the identical secondary effect on the
        catalogue: if the model's `certification_status` is still `UNCERTIFIED`, it
        moves `UNCERTIFIED → TEST_PENDING`."

        Design: Difficulty/combinatorial_formula/uef_effective_minimum_multistage_tier_derate_credit
        """
        models, tests = _three_scheduled_uef_tests(api)

        for key, measured in (
            ("small_gas", 0.585),
            ("large_heat_pump", 2.95),
            ("large_gas", 0.565),
        ):
            data_of(
                api.record_test_result(
                    tests[key], {"measured_value": measured}, quality_inspector_headers()
                )
            )

        for model_id in models.values():
            model = validate_success(
                api.get_product_model(model_id, compliance_engineer_headers())
            )
            assert model["certification_status"] == "TEST_PENDING"
            assert model["uef_rated"] is None


def _draft_certification_over_rounding_sensitive_readings(api):
    """A DRAFT certification over readings that expose the rounding order.

    The three UEF readings 0.585, 0.585 and 0.584 average to 0.5847 raw, so the
    published rating differs depending on whether each reading is rounded before
    or after the mean is taken. The FHR reading of 62.5 and the RECOVERY reading
    of 41.25 pin the two other per-metric widths at the same time.
    """
    model_id = make_model(api, product_model_payload())["id"]
    cell_id = make_test_cell(api)["id"]
    x.make_passing_test_suite(api, model_id, cell_id)
    cert = data_of(
        api.create_certification(
            certification_payload(model_id, x.model_version(api, model_id)),
            compliance_engineer_headers(),
        )
    )
    return model_id, cert["id"]


class TestCertifiedRatingRoundingOrder:
    """Each contributing test is rounded before the mean, not after."""

    def test_03_certified_uef_rounds_each_test_first_and_then_the_mean(self, api):
        """0.585, 0.585 and 0.584 publish 0.59, never the mean-then-round 0.58.

        PRD: "Averaging the raw readings and rounding only once at the end is
        forbidden: three `UEF` readings of 0.585, 0.585 and 0.584 yield 0.59 under
        the pinned order and 0.58 under the forbidden one."

        Design: Difficulty/combinatorial_formula/certified_uef_round_per_test_then_mean
        """
        _model_id, cert_id = _draft_certification_over_rounding_sensitive_readings(api)

        submitted = validate_success(
            api.submit_certification(cert_id, compliance_engineer_headers())
        )

        assert submitted["certified_uef"] == approx2(0.59)
        assert submitted["uef_test_count"] == 3

    def test_04_the_first_hour_and_recovery_ratings_use_their_own_widths(self, api):
        """A shared rounding width would publish 62.5 and 41.25 unchanged.

        PRD: "For the first-hour rating, do the same over the passing
        `FIRST_HOUR_RATING` tests but round each test to a whole gallon before
        averaging and round the mean to a whole gallon, giving `certified_fhr`."

        Design: Difficulty/combinatorial_formula/certified_uef_round_per_test_then_mean
        """
        _model_id, cert_id = _draft_certification_over_rounding_sensitive_readings(api)

        submitted = validate_success(
            api.submit_certification(cert_id, compliance_engineer_headers())
        )

        assert submitted["certified_fhr"] == 63
        assert submitted["certified_recovery"] == approx2(41.3)

    def test_05_submission_records_the_engineer_without_publishing_the_ratings(self, api):
        """The computed ratings live on the certification, not yet on the model.

        PRD: "Submission also stores the caller's `X-User-ID` as
        `submitted_by_user_id`; on a resubmission it **overwrites** that value with
        the resubmitting engineer's id and clears `reason_code`, which is why the
        approver eligible in one round may not be eligible in the next."

        Design: Difficulty/combinatorial_formula/certified_uef_round_per_test_then_mean
        """
        model_id, cert_id = _draft_certification_over_rounding_sensitive_readings(api)

        submitted = validate_success(
            api.submit_certification(cert_id, compliance_engineer_headers())
        )
        model = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == USER_ENGINEER
        assert model["certification_status"] == "TEST_PENDING"
        assert model["uef_rated"] is None


def _one_shipped_unit_and_two_draft_campaigns(api):
    """One shipped serial with a valve campaign and a tank campaign over it.

    The two remedies straddle two different fee bands, so the same population
    priced twice shows that the band is looked up rather than hard-coded.
    """
    plant = make_full_plant(api)
    ship_unit(api, plant, hardness_gpg=12.0)
    valve = data_of(
        api.create_recall_campaign(
            recall_campaign_payload(
                plant.model_id,
                campaign_code="RC-VLV",
                remedy_type="GAS_VALVE_KIT",
                budget_cents=100000,
            ),
            warranty_analyst_headers(),
        )
    )
    tank = data_of(
        api.create_recall_campaign(
            recall_campaign_payload(
                plant.model_id,
                campaign_code="RC-TNK",
                remedy_type="TANK_REPLACEMENT",
                budget_cents=200000,
            ),
            warranty_analyst_headers(),
        )
    )
    return plant, valve["id"], tank["id"]


class TestRecallAdminFeeBandSelection:
    """The fee band is picked from the provisional subtotal, once."""

    def test_06_gas_valve_kit_prices_at_20700_from_the_provisional_subtotal(self, api):
        """Re-banding the grossed-up total would price this remedy at 19,800.

        PRD: "The band is chosen **once**, from the provisional subtotal, and it is
        never re-selected after the fee has been added."

        Design: Difficulty/combinatorial_formula/recall_remedy_admin_fee_tier_pinned_from_provisional
        """
        _plant, valve_id, _tank_id = _one_shipped_unit_and_two_draft_campaigns(api)

        scoped = validate_success(
            api.scope_campaign(
                valve_id,
                scope_payload(SERIAL_FIRST, SERIAL_FIRST),
                warranty_analyst_headers(),
            )
        )

        assert scoped["per_unit_remedy_cost_cents"] == 20700
        assert scoped["status"] == "SCOPED"
        assert scoped["serial_range_start"] == SERIAL_FIRST

    def test_07_tank_replacement_lands_in_the_top_band_and_prices_at_80348(self, api):
        """A provisional 75,800 selects 0.06, so the rate itself is looked up.

        PRD: "Fourth, choose the administrative fee rate from that provisional
        subtotal by band: 0.15 when the subtotal is 20,000 cents or less, 0.10 when
        it is more than 20,000 but 50,000 or less, and 0.06 when it is more than
        50,000."

        Design: Difficulty/combinatorial_formula/recall_remedy_admin_fee_tier_pinned_from_provisional
        """
        _plant, _valve_id, tank_id = _one_shipped_unit_and_two_draft_campaigns(api)

        scoped = validate_success(
            api.scope_campaign(
                tank_id,
                scope_payload(SERIAL_FIRST, SERIAL_FIRST),
                warranty_analyst_headers(),
            )
        )

        assert scoped["per_unit_remedy_cost_cents"] == 80348
        assert scoped["status"] == "SCOPED"
        assert scoped["serial_range_start"] == SERIAL_FIRST

    def test_08_the_scope_estimate_multiplies_the_per_unit_cost_by_the_population(
        self, api
    ):
        """One affected serial makes each estimate equal to its per-unit cost.

        PRD: "`estimated_remedy_cost_cents` is then simply `affected_unit_count`
        multiplied by `per_unit_remedy_cost_cents`, with no further rounding, and it
        is a snapshot of the scope at the moment of scoping rather than a live
        figure."

        Design: Difficulty/combinatorial_formula/recall_remedy_admin_fee_tier_pinned_from_provisional
        """
        _plant, valve_id, tank_id = _one_shipped_unit_and_two_draft_campaigns(api)

        valve = validate_success(
            api.scope_campaign(
                valve_id,
                scope_payload(SERIAL_FIRST, SERIAL_FIRST),
                warranty_analyst_headers(),
            )
        )
        tank = validate_success(
            api.scope_campaign(
                tank_id,
                scope_payload(SERIAL_FIRST, SERIAL_FIRST),
                warranty_analyst_headers(),
            )
        )

        assert valve["affected_unit_count"] == 1
        assert valve["estimated_remedy_cost_cents"] == 20700
        assert tank["affected_unit_count"] == 1
        assert tank["estimated_remedy_cost_cents"] == 80348
