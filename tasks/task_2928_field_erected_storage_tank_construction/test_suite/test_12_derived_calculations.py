"""Derived quantities: settlement metrics, thickness rounding, clearance constants,
document aggregates and the in-service inspection schedule.

Each case pins the exact stored figure, because a formula that is right to full
precision but stored at the wrong scale is still wrong.
"""

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_angle,
    assert_instant,
    assert_list_total,
    assert_settlement,
    assert_tank_state,
    assert_thickness,
)
from test_helpers.constants import (
    APP_DESIGNED,
    APP_MIXER,
    APP_NOZZLE,
    APP_ROOF_VENT,
    APP_STAIRWAY,
    CLOCK_BASE,
    DOC_AS_BUILT_DRAWING,
    DOC_COATING_REPORT,
    DOC_HYDROTEST_RECORD,
    DOC_MILL_TEST_REPORTS,
    DOC_RT_FILM_LOG,
    GOVERNING_DESIGN,
    NC_NOT_APPLICABLE,
    PACKAGE_ACCEPTED,
    PACKAGE_DRAFT,
    PHASE_COATED,
    PHASE_COMMISSIONED,
    POSTURE_OPEN,
    REQUIRED_DOCUMENT_TYPES,
    SCOPE_EXTERNAL_COATING,
    SCOPE_INTERNAL_LINING,
    SURVEY_ROLE_BASELINE,
    SURVEY_ROLE_MONITORING,
    THICKNESS_ADEQUATE,
    VERDICT_BASELINE,
    VERDICT_WITHIN_TOLERANCE,
)
from test_helpers.test_users import AI3, PE1


class TestSettlementMetrics:
    def test_a_rigid_body_sinking_scores_zero_on_both_differential_metrics(self, api):
        """Two inches down everywhere is uniform settlement and nothing else.

        PRD: "`uniform_settlement_in` is the arithmetic mean of those per-point
        settlements."

        PRD: "A monitoring survey's `verdict` is `WITHIN_TOLERANCE` when the
        governing metric is no greater than the package's
        `allowable_differential_in` **and** the uniform settlement is no greater
        than the package's `permitted_uniform_settlement_in`; otherwise it is
        `OUT_OF_TOLERANCE`."

        Design: Corner/calculations/uniform_settlement_scores_zero_on_both_metrics
        """
        ctx = X.tank_with_baseline(api, clock=CLOCK_BASE)
        baseline = X.read_survey(api, ctx.baseline_id)
        assert baseline["survey_role"] == SURVEY_ROLE_BASELINE
        assert baseline["verdict"] == VERDICT_BASELINE
        assert_settlement(baseline["uniform_settlement_in"], 0.000, "baseline uniform")
        assert_settlement(baseline["governing_metric_in"], 0.000, "baseline governing metric")

        monitoring = X.create_survey(api, ctx.package_id, X.SETTLED_2IN, 50.0)

        assert monitoring["survey_role"] == SURVEY_ROLE_MONITORING
        assert_instant(monitoring["measured_at_utc"], CLOCK_BASE, "measurement instant")
        assert_settlement(monitoring["uniform_settlement_in"], 2.000, "uniform settlement")
        assert_settlement(monitoring["max_out_of_plane_in"], 0.000, "cosine metric")
        assert_settlement(monitoring["max_adjacent_differential_in"], 0.000, "adjacent metric")
        assert_settlement(monitoring["governing_metric_in"], 0.000, "governing metric")
        assert monitoring["verdict"] == VERDICT_WITHIN_TOLERANCE
        assert monitoring["nonconformance_state"] == NC_NOT_APPLICABLE

        assert_tank_state(
            X.read_tank(api, ctx.tank_id), posture=POSTURE_OPEN, nonconformance_count=0
        )


class TestShellCourseThicknessArithmetic:
    def test_each_loading_case_is_rounded_before_the_three_way_maximum(self, api):
        """Course two sits eight feet up, so the design case governs at 0.358.

        PRD: "Each of `required_thickness_design_in` and
        `required_thickness_test_in` is rounded half up to 3 decimal places
        *before* anything is compared."

        PRD: "The governing requirement, `required_thickness_in`, is the largest of
        three candidates: the rounded design-condition thickness, the rounded
        test-condition thickness, and the tank's `min_nominal_thickness_in`
        diameter floor from §3.1; it too is expressed to 3 decimal places."

        Design: Corner/calculations/required_thickness_rounds_each_case_to_three_decimals
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        first = X.create_course(api, tank["id"], 1)

        second = X.create_course(api, tank["id"], 2, plate_thickness_in=0.375)

        assert second["course_bottom_elevation_ft"] == 8.0
        assert second["design_liquid_height_ft"] == 32.0
        assert_thickness(second["required_thickness_design_in"], 0.358, "design thickness")
        assert_thickness(second["required_thickness_test_in"], 0.324, "test thickness")
        assert_thickness(tank["min_nominal_thickness_in"], 0.250, "min nominal floor")
        assert_thickness(second["required_thickness_in"], 0.358, "governing thickness")
        assert second["governing_case"] == GOVERNING_DESIGN
        assert second["thickness_verdict"] == THICKNESS_ADEQUATE

        untouched = X.read_course(api, first["id"])
        assert untouched["course_bottom_elevation_ft"] == 0.0
        assert_thickness(
            untouched["required_thickness_design_in"], 0.434, "course one design thickness"
        )

    def test_the_elevation_stack_ignores_courses_of_other_tanks(self, api):
        """A twenty-foot course on a sibling tank contributes nothing.

        PRD: "First the geometry: the course's `course_bottom_elevation_ft` is the
        sum of `course_width_ft` over every course of the same tank with a lower
        `course_number`, taken in ascending order, so the bottom course sits at
        elevation 0."

        PRD: "Courses of other tanks never contribute."

        Design: Corner/calculations/elevation_stack_excludes_courses_of_other_tanks
        """
        X.set_clock(api, CLOCK_BASE)
        first_tank = X.create_tank(api)
        second_tank = X.create_tank(api, tank_tag="TK-102")
        X.create_course(api, first_tank["id"], 1)
        other = X.create_course(
            api, second_tank["id"], 1, course_width_ft=20.0, plate_thickness_in=0.5
        )

        course_two = X.create_course(api, first_tank["id"], 2, plate_thickness_in=0.375)

        assert course_two["course_bottom_elevation_ft"] == 8.0
        assert_thickness(course_two["required_thickness_in"], 0.358, "governing thickness")
        assert course_two["governing_case"] == GOVERNING_DESIGN

        other_after = X.read_course(api, other["id"])
        assert other_after["course_bottom_elevation_ft"] == 0.0
        assert_thickness(
            other_after["required_thickness_design_in"], 0.434, "sibling design thickness"
        )

        assert_list_total(api.list_shell_courses(PE1, {"tank_id": first_tank["id"]}), 2)
        assert_list_total(api.list_shell_courses(PE1, {"tank_id": second_tank["id"]}), 1)


class TestClearanceAndDocumentAggregates:
    def test_every_appurtenance_type_takes_its_declared_clearance_constant(self, api):
        """The nozzle factor beats the floor at six inches and loses at four.

        PRD: "For a `NOZZLE` or a `MANWAY` it is the greater of 8.0 degrees and
        `nominal_size_in` multiplied by 1.5, so small nozzles all sit at the
        8.0-degree floor while a size above 5.333… inches begins to drive the
        requirement upward."

        PRD: "A `STAIRWAY` requires 30.0 degrees, a `MIXER` 20.0 degrees, and a
        `ROOF_VENT` 5.0 degrees; those three are flat values and ignore
        `nominal_size_in` entirely."

        Design: Corner/calculations/clearance_envelope_applies_each_declared_type_constant
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        course = X.create_course(api, tank["id"], 1)

        expected = {
            (APP_NOZZLE, 6.0, 0.0): 9.0,
            (APP_NOZZLE, 4.0, 40.0): 8.0,
            (APP_STAIRWAY, 36.0, 90.0): 30.0,
            (APP_MIXER, 18.0, 180.0): 20.0,
            (APP_ROOF_VENT, 8.0, 270.0): 5.0,
        }
        for (kind, size, azimuth), clearance in expected.items():
            row = X.create_appurtenance(
                api,
                tank["id"],
                course["id"],
                appurtenance_type=kind,
                nominal_size_in=size,
                azimuth_deg=azimuth,
            )
            assert_angle(row["required_clearance_deg"], clearance, f"{kind} clearance")
            assert row["status"] == APP_DESIGNED
            assert row["installed_at_utc"] is None

        assert_list_total(api.list_appurtenances(PE1, {"tank_id": tank["id"]}), 5)

    def test_document_aggregates_normalise_order_and_tolerate_duplicates(self, api):
        """Four records, three distinct types, and the required order preserved.

        PRD: "Every record increments `document_count`, duplicates included, so
        `document_count` is a count of documents and not a count of types."

        PRD: "`submitted_document_types` holds the distinct types recorded, emitted
        in the required order first and then any extra types in the order they were
        first recorded, and `missing_document_types` is the required list minus the
        submitted types, preserving the required order."

        Design: Corner/calculations/document_completeness_aggregates_distinct_types_in_declared_order
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        package = X.create_commissioning_package(api, tank["id"])
        assert package["submitted_document_types"] == []
        assert package["missing_document_types"] == REQUIRED_DOCUMENT_TYPES
        assert package["document_count"] == 0

        X.add_document(api, package["id"], DOC_HYDROTEST_RECORD, "HT-1")
        X.add_document(api, package["id"], DOC_COATING_REPORT, "CR-1")
        X.add_document(api, package["id"], DOC_MILL_TEST_REPORTS, "MTR-1")
        after = X.add_document(api, package["id"], DOC_HYDROTEST_RECORD, "HT-1-REV-B")

        assert after["document_count"] == 4
        assert after["submitted_document_types"] == [
            DOC_MILL_TEST_REPORTS,
            DOC_HYDROTEST_RECORD,
            DOC_COATING_REPORT,
        ]
        assert after["missing_document_types"] == [DOC_RT_FILM_LOG, DOC_AS_BUILT_DRAWING]
        assert after["status"] == PACKAGE_DRAFT


class TestInServiceInspectionSchedule:
    def test_the_acceptance_review_derives_the_whole_inspection_schedule(self, api):
        """Bottom-plate life drives both intervals, and both dates anchor on acceptance.

        PRD: "`bottom_remaining_life_years` is the tank's `bottom_thickness_in`
        less its `bottom_minimum_thickness_in`, divided by its
        `assumed_corrosion_rate_ipy`, rounded half up to 2 decimal places."

        PRD: "`external_inspection_interval_years` is 5 when the tank has a coating
        application with `scope` `EXTERNAL_COATING` whose `status` is `ACCEPTED`,
        and 2 otherwise; an internal lining, however well it passed, earns nothing
        here."

        Design: Corner/calculations/inspection_intervals_decay_from_bottom_plate_life
        """
        ctx = X.submitted_package_tank(
            api, scopes=(SCOPE_INTERNAL_LINING, SCOPE_EXTERNAL_COATING)
        )
        assert_tank_state(X.read_tank(api, ctx.tank_id), phase=PHASE_COATED)
        before = X.read_commissioning_package(api, ctx.commissioning_id)
        assert before["internal_inspection_interval_years"] is None
        assert before["next_internal_due_utc"] is None

        reviewed = X.review_package(api, ctx.commissioning_id, headers=AI3, remarks="records complete")

        assert reviewed["status"] == PACKAGE_ACCEPTED
        assert reviewed["reviewed_by_user_id"] == "ai-3"
        assert_instant(reviewed["accepted_at_utc"], "2026-08-11T00:00:00Z", "acceptance stamp")
        assert reviewed["bottom_remaining_life_years"] == 15.00
        assert reviewed["internal_inspection_interval_years"] == 7
        assert reviewed["external_inspection_interval_years"] == 5
        assert_instant(
            reviewed["next_internal_due_utc"], "2033-08-11T00:00:00Z", "internal due date"
        )
        assert_instant(
            reviewed["next_external_due_utc"], "2031-08-11T00:00:00Z", "external due date"
        )

        assert_tank_state(
            X.read_tank(api, ctx.tank_id), phase=PHASE_COMMISSIONED, posture=POSTURE_OPEN
        )
