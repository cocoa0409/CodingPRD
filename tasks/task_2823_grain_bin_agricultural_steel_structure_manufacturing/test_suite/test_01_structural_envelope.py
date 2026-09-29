"""The geometry, loading and stiffener pipeline of a bin design, and the analysis
register that probes it under the other design method."""

import pytest
from test_helpers import (
    ADMIN,
    assert_bin_design,
    assert_design_analysis,
    create_design,
    create_design_analysis_payload,
    engineer_headers,
    read_design,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAsdVersusLrfdStiffenerDivergence:
    def test_the_two_allowables_drive_twelve_stiffeners_under_asd_and_eleven_under_lrfd(
        self, api
    ):
        """PRD §3.2: "Under `ASD` the allowable capacity per stiffener is the nominal 180.0
        divided by a safety factor of 2.00, which is exactly 90.0 kilopascal-metres. Under
        `LRFD` it is the nominal 180.0 multiplied by a resistance factor of 0.90 and divided
        by a load factor of 1.60, which is exactly 101.25 kilopascal-metres — twelve and a
        half percent more than `ASD`, so the same geometry and loading can legitimately
        require strictly fewer stiffeners under `LRFD` than under `ASD`."
        PRD §3.2: "The `utilization_ratio` is then the `governing_demand_kpa` multiplied by
        the rounded `circumference_m`, divided by the product of the final
        `required_stiffener_count` and the allowable per-stiffener capacity, rounded half up
        to 4 decimal places."

        Design: Difficulty/dual_variant_calc/asd_vs_lrfd_stiffener_count_diverges_on_identical_bin_design
        """
        ref = setup_reference_data()
        design = create_design(ref)
        assert_bin_design(design)
        assert design["design_method"] == "ASD"
        assert design["circumference_m"] == pytest.approx(37.699, abs=1e-9)
        assert design["governing_demand_kpa"] == pytest.approx(28.518, abs=1e-9)
        assert design["governing_load_case"] == "GRAIN_LATERAL"
        assert design["required_stiffener_count"] == 12
        assert design["utilization_ratio"] == pytest.approx(0.9955, abs=1e-9)
        assert design["version"] == 1

        asd = validate_success(
            api.create_design_analysis(
                design["id"],
                create_design_analysis_payload("ASD", 1),
                engineer_headers(ref),
            ),
            201,
        )
        assert_design_analysis(asd)
        assert asd["analysis_index"] == 1
        assert asd["design_method"] == "ASD"
        assert asd["allowable_kpa_m"] == pytest.approx(90.0, abs=1e-9)
        assert asd["governing_load_case"] == "GRAIN_LATERAL"
        assert asd["governing_demand_kpa"] == pytest.approx(28.518, abs=1e-9)
        assert asd["required_stiffener_count"] == 12
        assert asd["utilization_ratio"] == pytest.approx(0.9955, abs=1e-9)
        assert asd["verdict"] == "PASS"
        assert asd["superseded"] is False

        lrfd = validate_success(
            api.create_design_analysis(
                design["id"],
                create_design_analysis_payload("LRFD", 2),
                engineer_headers(ref),
            ),
            201,
        )
        assert lrfd["analysis_index"] == 2
        assert lrfd["design_method"] == "LRFD"
        assert lrfd["allowable_kpa_m"] == pytest.approx(101.25, abs=1e-9)
        assert lrfd["governing_load_case"] == "GRAIN_LATERAL"
        assert lrfd["governing_demand_kpa"] == pytest.approx(28.518, abs=1e-9)
        assert lrfd["required_stiffener_count"] == 11
        assert lrfd["utilization_ratio"] == pytest.approx(0.9653, abs=1e-9)
        assert lrfd["verdict"] == "PASS"
        assert lrfd["superseded"] is False

        assert lrfd["required_stiffener_count"] < asd["required_stiffener_count"]

    def test_the_cross_method_analysis_bumps_the_parent_but_never_rewrites_its_steel(
        self, api
    ):
        """PRD §3.3: "The chosen `design_method` on the analysis is deliberately independent
        of the design's own `design_method`, which is what makes the analysis register
        useful: an engineer may probe an `ASD` design under `LRFD` to see how much steel a
        method change would save."
        PRD §3.3: "Creating an analysis advances the parent design's `version` by 1, which is
        precisely why the next analysis create must present a refreshed
        `expected_bin_design_version` or be rejected with `ERR_STALE_DESIGN_VERSION`."

        Design: Difficulty/dual_variant_calc/asd_vs_lrfd_stiffener_count_diverges_on_identical_bin_design
        """
        ref = setup_reference_data()
        design = create_design(ref)

        validate_success(
            api.create_design_analysis(
                design["id"],
                create_design_analysis_payload("ASD", 1),
                engineer_headers(ref),
            ),
            201,
        )
        validate_success(
            api.create_design_analysis(
                design["id"],
                create_design_analysis_payload("LRFD", 2),
                engineer_headers(ref),
            ),
            201,
        )

        after = read_design(design["id"])
        assert after["version"] == 3
        assert after["status"] == "DRAFT"
        assert after["design_method"] == "ASD"
        assert after["required_stiffener_count"] == 12
        assert after["utilization_ratio"] == pytest.approx(0.9955, abs=1e-9)
        assert after["sheet_gauge_mm"] == pytest.approx(1.6, abs=1e-9)

        rows, meta = validate_paginated(
            api.list_design_analyses(design["id"], ADMIN, {"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 2
        assert [row["analysis_index"] for row in rows] == [1, 2]
        assert [row["superseded"] for row in rows] == [False, False]
        assert [row["allowable_kpa_m"] for row in rows] == pytest.approx([90.0, 101.25])
        assert [row["required_stiffener_count"] for row in rows] == [12, 11]


class TestHighWindStiffenerBoundary:
    def test_one_hundred_fifteen_mph_grants_the_bonus_and_the_roof_ring_while_114_grants_neither(
        self, api
    ):
        """PRD §3.2: "A design counts as high-wind when its `design_wind_speed_mph` is at or
        above 115."
        PRD §3.2: "Second — and only after that floor has been applied — a bonus of 2
        stiffeners is added when the design is high-wind."
        PRD §3.2: "Finally, `roof_ring_required` is true exactly when the design is high-wind
        by the same 115 mile-per-hour test that grants the stiffener bonus — the two flags
        always agree."

        Design: Difficulty/boundary_precision_check/wind_speed_115_mph_adds_high_wind_stiffener_bonus_while_114_does_not
        """
        ref = setup_reference_data()

        below = create_design(ref, design_wind_speed_mph=114)
        assert below["design_wind_speed_mph"] == 114
        assert below["wind_demand_kpa"] == pytest.approx(9.357, abs=1e-9)
        assert below["governing_demand_kpa"] == pytest.approx(28.518, abs=1e-9)
        assert below["governing_load_case"] == "GRAIN_LATERAL"
        assert below["required_stiffener_count"] == 12
        assert below["roof_ring_required"] is False
        assert below["utilization_ratio"] == pytest.approx(0.9955, abs=1e-9)

        at = create_design(ref, design_wind_speed_mph=115)
        assert at["design_wind_speed_mph"] == 115
        assert at["wind_demand_kpa"] == pytest.approx(9.522, abs=1e-9)
        assert at["governing_demand_kpa"] == pytest.approx(28.518, abs=1e-9)
        assert at["governing_load_case"] == "GRAIN_LATERAL"
        assert at["required_stiffener_count"] == 14
        assert at["roof_ring_required"] is True

        assert at["required_stiffener_count"] - below["required_stiffener_count"] == 2
        assert at["roof_ring_required"] != below["roof_ring_required"]

    def test_the_bonus_relieves_utilization_without_touching_demand_geometry_or_gauge(
        self, api
    ):
        """PRD §3.2: "The `utilization_ratio` is then the `governing_demand_kpa` multiplied by
        the rounded `circumference_m`, divided by the product of the final
        `required_stiffener_count` and the allowable per-stiffener capacity, rounded half up
        to 4 decimal places."
        PRD §3.2: "The `wind_demand_kpa` is 0.9 multiplied by the square of the
        `design_wind_speed_mph`, multiplied by the `eave_height_m`, then divided by the
        `diameter_m` and by 1000, rounded half up to 3 decimal places."
        PRD §3.2: "the stored `sheet_gauge_mm` is the lowest ladder value that is at or above
        the `governing_demand_kpa` multiplied by 0.05"

        Design: Difficulty/boundary_precision_check/wind_speed_115_mph_adds_high_wind_stiffener_bonus_while_114_does_not
        """
        ref = setup_reference_data()

        below = create_design(ref, design_wind_speed_mph=114)
        at = create_design(ref, design_wind_speed_mph=115)

        assert below["utilization_ratio"] == pytest.approx(0.9955, abs=1e-9)
        assert at["utilization_ratio"] == pytest.approx(0.8533, abs=1e-9)
        assert at["utilization_ratio"] < below["utilization_ratio"]

        # The extra steel is a code bonus, not a re-evaluation of the loading: every
        # geometry and demand field is identical across the boundary.
        for field in (
            "circumference_m",
            "sheets_per_course",
            "sheet_courses",
            "sidewall_sheet_count",
            "roof_panel_count",
            "capacity_m3",
            "grain_lateral_kpa",
            "moisture_factor",
            "grain_demand_kpa",
            "seismic_demand_kpa",
            "governing_demand_kpa",
            "governing_load_case",
            "sheet_gauge_mm",
        ):
            assert at[field] == below[field], field

        assert below["sheet_gauge_mm"] == pytest.approx(1.6, abs=1e-9)
        assert at["sheet_gauge_mm"] == pytest.approx(1.6, abs=1e-9)


class TestGoverningLoadCaseSwitches:
    def test_wind_and_seismic_each_take_the_governing_slot_when_they_beat_grain(self, api):
        """PRD §3.2: "The `governing_demand_kpa` is the largest of the three rounded demands.
        The `governing_load_case` names which one won, resolved in a fixed order so that ties
        are never ambiguous: it is `GRAIN_LATERAL` when the `grain_demand_kpa` equals the
        governing value; otherwise `WIND_UPLIFT` when the `wind_demand_kpa` equals it;
        otherwise `SEISMIC_BASE_SHEAR`."
        PRD §3.2: "Seismic demand uses the jurisdiction's category to pick a base-shear factor
        — 0.05 for category `A`, 0.12 for `B`, 0.22 for `C` and 0.33 for `D` — and the
        `seismic_demand_kpa` is that factor multiplied by the profile's
        `bulk_density_kg_per_m3`, by 9.81 and by the capped design depth, divided by 1000,
        rounded half up to 3 decimal places."

        Design: Corner/calculations/governing_load_case_switches_to_wind_uplift_and_to_seismic_base_shear_when_they_beat_grain
        """
        ref = setup_reference_data()

        windy = create_design(
            ref,
            diameter_m=6.0,
            eave_height_m=12.0,
            roof_pitch_deg=30,
            design_wind_speed_mph=150,
            moisture_pct=14.0,
        )
        assert windy["grain_lateral_kpa"] == pytest.approx(35.648, abs=1e-9)
        assert windy["moisture_factor"] == pytest.approx(1.0, abs=1e-9)
        assert windy["grain_demand_kpa"] == pytest.approx(35.648, abs=1e-9)
        assert windy["wind_demand_kpa"] == pytest.approx(40.5, abs=1e-9)
        assert windy["seismic_demand_kpa"] == pytest.approx(4.244, abs=1e-9)
        assert windy["governing_demand_kpa"] == pytest.approx(40.5, abs=1e-9)
        assert windy["governing_load_case"] == "WIND_UPLIFT"
        assert windy["circumference_m"] == pytest.approx(18.85, abs=1e-9)
        assert windy["sheet_courses"] == 15
        assert windy["sheets_per_course"] == 18
        assert windy["sidewall_sheet_count"] == 270
        assert windy["roof_panel_count"] == 21
        assert windy["capacity_m3"] == pytest.approx(355.61, abs=1e-9)
        assert windy["required_stiffener_count"] == 11
        assert windy["utilization_ratio"] == pytest.approx(0.7711, abs=1e-9)
        assert windy["sheet_gauge_mm"] == pytest.approx(2.5, abs=1e-9)
        assert windy["roof_ring_required"] is True

        quake = create_design(
            ref,
            jurisdiction="CA-VALLEY",
            grain_profile="LOWK",
            moisture_pct=13.0,
            design_wind_speed_mph=105,
        )
        assert quake["grain_lateral_kpa"] == pytest.approx(20.37, abs=1e-9)
        assert quake["grain_demand_kpa"] == pytest.approx(20.37, abs=1e-9)
        assert quake["wind_demand_kpa"] == pytest.approx(7.938, abs=1e-9)
        assert quake["seismic_demand_kpa"] == pytest.approx(22.407, abs=1e-9)
        assert quake["governing_demand_kpa"] == pytest.approx(22.407, abs=1e-9)
        assert quake["governing_load_case"] == "SEISMIC_BASE_SHEAR"
        assert quake["capacity_m3"] == pytest.approx(1216.25, abs=1e-9)
        assert quake["required_stiffener_count"] == 10
        assert quake["utilization_ratio"] == pytest.approx(0.9386, abs=1e-9)
        assert quake["sheet_gauge_mm"] == pytest.approx(1.3, abs=1e-9)
        assert quake["roof_ring_required"] is False


class TestStiffenerCountClampBlocksReview:
    def test_the_clamp_pushes_utilization_past_one_and_the_failing_analysis_holds_the_design_in_draft(
        self, api
    ):
        """PRD §3.2: "Third, the result is capped, and the stored `required_stiffener_count` is
        the smaller of that figure and a ceiling of 24 stiffeners."
        PRD §3.2: "Because the stiffener count is capped at 24, a sufficiently punishing load
        produces a `utilization_ratio` above 1.0 that cannot be engineered away by adding
        steel rings."
        PRD §3.3: "If no such row exists at all — because none has been run, because every
        candidate was superseded by a revision, or because every surviving analysis used the
        other method — the submission is rejected with `ERR_NO_PASSING_ANALYSIS`. If such a
        row exists but its `verdict` is `FAIL`, the submission is rejected with
        `ERR_DESIGN_ANALYSIS_FAILED`."

        Design: Corner/calculations/stiffener_count_clamps_at_the_maximum_and_a_failing_analysis_blocks_review
        """
        ref = setup_reference_data()
        design = create_design(
            ref,
            grain_profile="DENSE",
            diameter_m=15.5,
            eave_height_m=12.0,
            moisture_pct=12.0,
            design_wind_speed_mph=105,
        )
        assert design["grain_lateral_kpa"] == pytest.approx(71.221, abs=1e-9)
        assert design["wind_demand_kpa"] == pytest.approx(7.682, abs=1e-9)
        assert design["seismic_demand_kpa"] == pytest.approx(6.475, abs=1e-9)
        assert design["governing_load_case"] == "GRAIN_LATERAL"
        assert design["circumference_m"] == pytest.approx(48.695, abs=1e-9)
        assert design["sheet_courses"] == 15
        assert design["sheets_per_course"] == 45
        assert design["sidewall_sheet_count"] == 675
        assert design["roof_panel_count"] == 55
        assert design["capacity_m3"] == pytest.approx(2545.56, abs=1e-9)
        assert design["required_stiffener_count"] == 24
        assert design["utilization_ratio"] == pytest.approx(1.6056, abs=1e-9)
        assert design["sheet_gauge_mm"] == pytest.approx(3.0, abs=1e-9)
        assert design["status"] == "DRAFT"

        validate_error(
            api.submit_design_for_review(design["id"], engineer_headers(ref)),
            "ERR_NO_PASSING_ANALYSIS",
            422,
        )

        analysis = validate_success(
            api.create_design_analysis(
                design["id"],
                create_design_analysis_payload("ASD", 1),
                engineer_headers(ref),
            ),
            201,
        )
        assert analysis["required_stiffener_count"] == 24
        assert analysis["utilization_ratio"] == pytest.approx(1.6056, abs=1e-9)
        assert analysis["verdict"] == "FAIL"

        validate_error(
            api.submit_design_for_review(design["id"], engineer_headers(ref)),
            "ERR_DESIGN_ANALYSIS_FAILED",
            422,
        )
        assert read_design(design["id"])["status"] == "DRAFT"
