"""Retro-commissioning measures: the two savings variants and their certification."""

from test_helpers import (
    ApiErrorId,
    assert_energy_baseline,
    create_energy_baseline_payload,
    create_project,
    get_baseline,
    setup_retro_project_with_post_period,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import CXA


class TestSavingsVariants:
    def test_both_variants_are_computed_side_by_side_from_one_row(self, api):
        """PRD §3.9: "The **`DEEMED`** variant is the stipulated engineering estimate and
        reads no metered data at all. It is `stipulated_kwh_per_hour` multiplied by
        `operating_hours` multiplied by a realisation factor of 0.85, rounded half up to two
        decimal places, and written to `deemed_savings_kwh`."
        PRD §3.9: "The **`MEASURED`** variant is weather-normalised measurement and
        verification. First the baseline is adjusted for weather: `baseline_kwh` is
        multiplied by the post period's degree days divided by the baseline period's degree
        days, and that adjusted baseline is rounded half up to two decimal places **before**
        anything is subtracted from it. Then the metered `post_kwh` is subtracted from the
        rounded adjusted baseline to give gross savings. Gross savings are floored at zero —
        a measure that used more energy after the retrofit claims zero, never a negative.
        Finally a fixed uncertainty deduction of ten percent is applied by multiplying the
        floored figure by 0.90, and the result is rounded half up to two decimal places and
        written to `measured_savings_kwh`."

        Design: Difficulty/dual_variant_calc/retro_savings_deemed_vs_measured_diverge_on_energy_baseline
        """
        setup = setup_retro_project_with_post_period()
        baseline = setup["baseline"]

        assert_energy_baseline(baseline)
        assert baseline["status"] == "POST_PERIOD_RECORDED"
        assert baseline["deemed_savings_kwh"] == 46537.50, (
            "12.5 * 4380 * 0.85"
        )
        assert baseline["measured_savings_kwh"] == 19800.00, (
            "(round(480000 * 2880 / 3200) - 410000) * 0.90"
        )
        assert baseline["deemed_savings_kwh"] != baseline["measured_savings_kwh"]
        assert baseline["certified_savings_kwh"] is None
        assert baseline["certified_variant"] is None

    def test_certification_freezes_the_chosen_variant(self, api):
        """PRD §3.9: "Certification freezes one of the two. The `CxAuthority` names a
        `variant` of `DEEMED` or `MEASURED`, and the server copies that variant's value into
        `certified_savings_kwh`, records the choice in `certified_variant`, and moves the
        measure `POST_PERIOD_RECORDED` → `CERTIFIED`."

        Design: Difficulty/dual_variant_calc/retro_savings_deemed_vs_measured_diverge_on_energy_baseline
        """
        setup = setup_retro_project_with_post_period()

        certified = validate_success(
            api.certify_savings(setup["baseline"]["id"], {"variant": "MEASURED"}, CXA),
            200,
        )
        assert certified["certified_savings_kwh"] == 19800.00
        assert certified["certified_variant"] == "MEASURED"
        assert certified["status"] == "CERTIFIED"

        stored = get_baseline(setup["baseline"]["id"])
        assert stored["deemed_savings_kwh"] == 46537.50
        assert stored["measured_savings_kwh"] == 19800.00
        assert stored["certified_savings_kwh"] == 19800.00

    def test_gross_savings_are_floored_at_zero(self, api):
        """PRD §3.9: "Gross savings are floored at zero — a measure that used more energy
        after the retrofit claims zero, never a negative."
        PRD §3.9: "Certification freezes one of the two. The `CxAuthority` names a `variant`
        of `DEEMED` or `MEASURED`, and the server copies that variant's value into
        `certified_savings_kwh`, records the choice in `certified_variant`, and moves the
        measure `POST_PERIOD_RECORDED` → `CERTIFIED`."

        Design: Corner/calculations/measured_savings_floor_at_zero_when_post_period_exceeds_adjusted_baseline
        """
        setup = setup_retro_project_with_post_period(
            post_kwh=500_000, post_hdd=2_880, measure_code="RCX-VAV-RESET"
        )
        baseline = setup["baseline"]

        assert baseline["deemed_savings_kwh"] == 46537.50
        assert baseline["measured_savings_kwh"] == 0.00, (
            "500000 metered against an adjusted baseline of 432000.00 claims zero"
        )

        certified = validate_success(
            api.certify_savings(baseline["id"], {"variant": "DEEMED"}, CXA), 200
        )
        assert certified["certified_variant"] == "DEEMED"
        assert certified["certified_savings_kwh"] == 46537.50
        assert certified["status"] == "CERTIFIED"


class TestCertificationTargetGate:
    def test_an_enhanced_target_admits_only_the_measured_variant(self, api):
        """PRD §3.9: "The `MEASURED` variant may be certified on any engagement whatever its
        certification target. The `DEEMED` variant may be certified only when the
        engagement's `certification_target` is `NONE` or `STANDARD`; an engagement chasing
        `ENHANCED` may certify only `MEASURED`, and asking for `DEEMED` there is refused
        with `ERR_VARIANT_NOT_PERMITTED`."

        Design: Corner/calculations/enhanced_certification_target_permits_only_measured_variant
        """
        setup = setup_retro_project_with_post_period(certification_target="ENHANCED")

        refused = api.certify_savings(
            setup["baseline"]["id"], {"variant": "DEEMED"}, CXA
        )
        validate_error(refused, ApiErrorId.ERR_VARIANT_NOT_PERMITTED.value, 422)
        assert get_baseline(setup["baseline"]["id"])["status"] == "POST_PERIOD_RECORDED"

        certified = validate_success(
            api.certify_savings(setup["baseline"]["id"], {"variant": "MEASURED"}, CXA),
            200,
        )
        assert certified["certified_savings_kwh"] == 19800.00
        assert certified["certified_variant"] == "MEASURED"
        assert certified["status"] == "CERTIFIED"

    def test_energy_baselines_are_refused_on_new_construction(self, api):
        """PRD §3.9: "Retro-commissioning engagements — those whose `project_type` is
        `RETRO_COMMISSIONING` — carry energy measures that new-construction engagements do
        not."
        PRD §3.9: "Attempting this on a `NEW_CONSTRUCTION` engagement is refused with
        `ERR_RETRO_ONLY`."

        Design: Corner/calculations/retro_only_gate_rejects_energy_baseline_on_new_construction
        """
        project = create_project(
            name="NewCon Cx",
            building_name="NewCon Block",
            contract_value_cents=40_000_000,
        )

        response = api.create_energy_baseline(
            create_energy_baseline_payload(project["id"]), CXA
        )
        validate_error(response, ApiErrorId.ERR_RETRO_ONLY.value, 422)

        _, meta = validate_paginated(
            api.list_energy_baselines(CXA, params={"project_id": project["id"]})
        )
        assert meta["total_count"] == 0
