"""
Sizing the backup: the two sizing methods and the essential-loads nesting.

The load calculation is where the whole project's numbers are set, and it is the one
place where two genuinely different arithmetics answer the same question. These tests
pin both methods on identical premises and pin the order in which the essential-loads
branch clamps and then derives.
"""

from test_helpers import (
    BackupScope,
    LoadCalcStatus,
    LoadMethod,
    assert_created_record,
    assert_quantity,
    factories,
    fixtures,
    validate_success,
)


def _site(api):
    """One installer and one site, with nothing sized yet."""
    project = fixtures.certified_installer(api)
    return fixtures.site_for(api, project)


class TestStandardVersusMeasuredWholeHome:
    """The two methods consume disjoint inputs and reach different figures."""

    def test_standard_method_sizes_the_whole_home_from_the_nameplate_va_split(self, api):
        """The standard method applies the demand split and keeps only the larger HVAC term.

        The lighting term is 2400 square feet at 3 VA each, so the other-load subtotal is
        7200 + 18000 = 25200 VA; the first 3000 counts in full and the remaining 22200
        counts at 40 percent, giving 11880 VA, and the HVAC term is the larger of 9600 and
        7200. Together that is 21480 VA, or 21.48 kW, and a whole-home scope carries that
        figure straight into the continuous requirement and multiplies it by 1.75 for surge.

        PRD 3.2: "the first 3000 volt-amperes of that subtotal count at full value, and every volt-ampere of the subtotal beyond 3000 counts at 40 percent"
        PRD 3.2: "Separately, the HVAC term is the larger of `heating_va` and `cooling_va` — the smaller of the two is discarded, not added."
        PRD 3.2: "When the scope is `WHOLE_HOME`, `required_continuous_kw` is exactly `connected_load_kw`, and `required_surge_kw` is `connected_load_kw` multiplied by 1.75, rounded half up to two decimals."

        Design: Difficulty/dual_variant_calc/load_sizing_standard_optional_vs_measured_demand_whole_home
        """
        project = _site(api)

        calc = validate_success(
            api.create_load_calculation(
                factories.whole_home_load_calculation_payload(project.site_id),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        assert_created_record(calc)
        assert calc["method"] == LoadMethod.STANDARD
        assert calc["backup_scope"] == BackupScope.WHOLE_HOME
        assert calc["status"] == LoadCalcStatus.DRAFT
        assert_quantity(calc, "connected_load_kw", 21.48)
        assert_quantity(calc, "required_continuous_kw", 21.48)
        assert_quantity(calc, "required_surge_kw", 37.59)

    def test_measured_method_ignores_the_nameplate_inputs_and_sizes_from_the_metered_peak(
        self, api
    ):
        """On the same premises the measured method reaches a different figure entirely.

        The measured calculation carries exactly the same volt-ampere inputs as the standard
        one, and none of them count: 14.0 kW of metered peak with the 25 percent headroom
        allowance gives 17.50 kW, which is 3.98 kW below the standard method's answer and
        drags the surge requirement down with it.

        PRD 3.2: "Under the measured method, `connected_load_kw` is instead `measured_peak_kw` multiplied by 1.25 — a 25 percent headroom allowance — rounded half up to two decimals, and every one of the nameplate volt-ampere inputs is ignored."
        PRD 3.2: "The same premise therefore yields a different `connected_load_kw` under the two methods, and under whole-home scoping a different `required_continuous_kw` and `required_surge_kw` as well."

        Design: Difficulty/dual_variant_calc/load_sizing_standard_optional_vs_measured_demand_whole_home
        """
        project = _site(api)
        standard = validate_success(
            api.create_load_calculation(
                factories.whole_home_load_calculation_payload(project.site_id),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        measured = validate_success(
            api.create_load_calculation(
                factories.measured_load_calculation_payload(
                    project.site_id, measured_peak_kw=14.0
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        assert measured["method"] == LoadMethod.MEASURED
        assert_quantity(measured, "connected_load_kw", 17.50)
        assert_quantity(measured, "required_continuous_kw", 17.50)
        assert_quantity(measured, "required_surge_kw", 30.63)
        assert measured["connected_load_kw"] != standard["connected_load_kw"], (
            "the two methods must not agree on connected_load_kw"
        )
        assert measured["required_surge_kw"] != standard["required_surge_kw"]


class TestEssentialLoadsClampAndSurge:
    """The essential branch clamps first and derives the surge from the clamped value."""

    ESSENTIAL_CIRCUITS = [
        {"label": "HEAT_PUMP", "load_kw": 12.0, "has_motor": True},
        {"label": "RANGE", "load_kw": 9.6, "has_motor": False},
        {"label": "KITCHEN", "load_kw": 3.5, "has_motor": False},
        {"label": "PUMP", "load_kw": 2.4, "has_motor": True},
    ]

    def _clamped_calculation(self, api, project):
        return validate_success(
            api.create_load_calculation(
                factories.load_calculation_payload(
                    project.site_id,
                    method=LoadMethod.MEASURED,
                    backup_scope=BackupScope.ESSENTIAL_LOADS,
                    measured_peak_kw=8.0,
                    essential_circuits=self.ESSENTIAL_CIRCUITS,
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

    def test_essential_continuous_requirement_is_clamped_to_the_connected_load(self, api):
        """The circuit arithmetic wants 24.55 kW; the connected load caps it at 10.00 kW.

        The top two circuits total 21.6 kW and half the remaining 5.9 kW adds 2.95 kW, so the
        circuit subtotal is 24.55 kW. The measured connected load is 8.0 kW with the headroom
        allowance, that is 10.00 kW, and because the rule takes the smaller of the two the
        continuous requirement lands on 10.00 kW.

        PRD 3.2: "The continuous requirement is the top-circuit total plus half of the remainder total, but never more than `connected_load_kw` — the smaller of those two quantities is taken — rounded half up to two decimals."

        Design: Difficulty/combinatorial_formula/essential_loads_nested_min_max_clamp_under_measured_method
        """
        project = _site(api)

        calc = self._clamped_calculation(api, project)

        assert_quantity(calc, "connected_load_kw", 10.00)
        assert_quantity(calc, "required_continuous_kw", 10.00)
        assert calc["required_continuous_kw"] != 24.55, (
            "the unclamped circuit subtotal must not survive into required_continuous_kw"
        )

    def test_essential_surge_is_derived_from_the_clamped_continuous_value(self, api):
        """The surge term reads the clamped continuous figure, not the raw circuit subtotal.

        The largest motor candidate is the 12.0 kW heat pump at three times inrush, that is
        36.0 kW, and a quarter of the clamped 10.00 kW continuous figure adds 2.5 kW for a
        surge requirement of 38.50 kW. Taking the quarter from the unclamped 24.55 kW subtotal
        would have produced 42.14 kW instead.

        PRD 3.2: "for every circuit whose `has_motor` is true, its `load_kw` multiplied by 3.0 is a candidate, and the largest candidate is the motor surge figure"
        PRD 3.2: "`required_surge_kw` is then that motor surge figure plus 25 percent of the already-computed `required_continuous_kw`, rounded half up to two decimals."

        Design: Difficulty/combinatorial_formula/essential_loads_nested_min_max_clamp_under_measured_method
        """
        project = _site(api)

        calc = self._clamped_calculation(api, project)

        assert_quantity(calc, "required_surge_kw", 38.50)
        assert calc["required_surge_kw"] != 42.14, (
            "the surge term must not be taken from the unclamped continuous subtotal"
        )
        assert len(calc["essential_circuits"]) == len(self.ESSENTIAL_CIRCUITS)
