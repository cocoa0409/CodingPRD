"""Preparation: variance arithmetic, mapping coverage and the deterministic edit-check cascade."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_component_status,
    assert_edit_check,
    assert_equals_number,
    assert_metric_keys_ascending,
    assert_null,
    assert_one_decimal,
    assert_sequence_numbers_ascending,
    constants as K,
    factories as f,
    fixtures as fx,
)

FINANCE_WINDOW = {
    "coverage_start_date": K.REPORTING_YEAR_FLOOR,
    "coverage_end_date": K.REPORTING_YEAR_CEILING,
}


class TestVarianceThresholdBoundaries:
    """Both variance thresholds are inclusive and read the same one-decimal figure."""

    def test_a_variance_of_exactly_ten_warns_while_exactly_twentyfive_is_fatal(
        self, api, analyst
    ):
        """9.9 is silent, 10.0 warns and 25.0 is fatal in a single deterministic run.

        PRD 3.3: "Two thresholds read that figure, and both are inclusive: a variance of at least
        10.0 percent is a warning-level concern, and a variance of at least 25.0 percent is a fatal
        one. Exactly 10.0 is a warning, exactly 25.0 is fatal, and 9.9 raises nothing at all."

        Design: Difficulty/boundary_precision_check/prior_year_variance_at_exactly_ten_and_twentyfive_percent_thresholds
        """
        scenario = fx.component_on_locked_cycle(
            api,
            domain=K.DOMAIN_FINANCE,
            record_count=3,
            metrics=(
                {
                    "metric_key": K.METRIC_INSTRUCTION_EXPENSES_CENTS,
                    "reported_value": 1100,
                    "prior_year_value": 1000,
                    "source_field_path": "fin.gl.instruction_total",
                },
                {
                    "metric_key": K.METRIC_ACADEMIC_SUPPORT_EXPENSES_CENTS,
                    "reported_value": 1099,
                    "prior_year_value": 1000,
                    "source_field_path": "fin.gl.academic_support_total",
                },
                {
                    "metric_key": K.METRIC_STUDENT_SERVICES_EXPENSES_CENTS,
                    "reported_value": 1250,
                    "prior_year_value": 1000,
                    "source_field_path": "fin.gl.student_services_total",
                },
            ),
            checksum="a1b2c3d4e5f60012",
            **FINANCE_WINDOW,
        )

        prepared = validate_success(api.prepare_component(scenario.component_id, analyst))
        assert_component_status(
            prepared,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_OPEN_EDITS,
            fatal_open_count=1,
        )
        assert_null(prepared["core_expense_per_fte_cents"], "core_expense_per_fte_cents")

        for key, expected in (
            (K.METRIC_INSTRUCTION_EXPENSES_CENTS, 10.0),
            (K.METRIC_ACADEMIC_SUPPORT_EXPENSES_CENTS, 9.9),
            (K.METRIC_STUDENT_SERVICES_EXPENSES_CENTS, 25.0),
        ):
            stored = validate_success(
                api.get_component_metric(scenario.metric(key)["id"], analyst)
            )
            assert_equals_number(stored["variance_pct"], expected, "%s.variance_pct" % key)
            assert_one_decimal(stored["variance_pct"], "%s.variance_pct" % key)

        checks, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=scenario.component_id)
        )
        assert meta["total_count"] == 2
        assert_sequence_numbers_ascending(checks)
        assert_metric_keys_ascending(checks)
        assert_edit_check(
            checks[0],
            check_code=K.PY_VAR_PREFIX + K.METRIC_INSTRUCTION_EXPENSES_CENTS,
            metric_key=K.METRIC_INSTRUCTION_EXPENSES_CENTS,
            severity=K.SEVERITY_WARNING,
            status=K.CHECK_OPEN,
            sequence_no=1,
            variance_pct=10.0,
            observed_value=1100,
            prior_year_value=1000,
        )
        assert_edit_check(
            checks[1],
            check_code=K.PY_VAR_PREFIX + K.METRIC_STUDENT_SERVICES_EXPENSES_CENTS,
            severity=K.SEVERITY_FATAL,
            sequence_no=2,
            variance_pct=25.0,
        )
        assert not [
            c for c in checks if c["metric_key"] == K.METRIC_ACADEMIC_SUPPORT_EXPENSES_CENTS
        ]

    def test_a_variance_just_below_the_fatal_line_stays_a_warning(self, api, analyst):
        """24.9 is under 25.0, so the check is raised but no fatal is opened.

        PRD 3.3: "Otherwise, when the metric's `variance_pct` is not null and is at least 10.0,
        the same `PY_VAR_` check code is raised but with `severity` `WARNING`, again carrying the
        metric's `variance_pct`."

        Design: Difficulty/boundary_precision_check/prior_year_variance_at_exactly_ten_and_twentyfive_percent_thresholds
        """
        scenario = fx.component_on_locked_cycle(
            api,
            metrics=(
                {
                    "metric_key": K.METRIC_TOTAL_HEADCOUNT,
                    "reported_value": 1249,
                    "prior_year_value": 1000,
                    "source_field_path": "sis.enrollment.headcount",
                },
                {
                    "metric_key": K.METRIC_FTE_ENROLLMENT,
                    "reported_value": 940,
                    "prior_year_value": 1000,
                    "source_field_path": "sis.enrollment.fte",
                },
            ),
            checksum="a1b2c3d4e5f60013",
        )

        prepared = validate_success(api.prepare_component(scenario.component_id, analyst))
        assert_component_status(
            prepared, edit_status=K.EDIT_OPEN_EDITS, fatal_open_count=0
        )

        checks, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=scenario.component_id)
        )
        assert meta["total_count"] == 1
        assert_edit_check(
            checks[0],
            check_code=K.PY_VAR_PREFIX + K.METRIC_TOTAL_HEADCOUNT,
            severity=K.SEVERITY_WARNING,
            sequence_no=1,
            variance_pct=24.9,
        )
        headcount = validate_success(
            api.get_component_metric(
                scenario.metric(K.METRIC_TOTAL_HEADCOUNT)["id"], analyst
            )
        )
        assert_equals_number(headcount["variance_pct"], 24.9, "metric.variance_pct")
        fte = validate_success(
            api.get_component_metric(scenario.metric(K.METRIC_FTE_ENROLLMENT)["id"], analyst)
        )
        assert_equals_number(fte["variance_pct"], 6.0, "metric.variance_pct")


class TestVariancePrecision:
    """The variance is rounded half up to one decimal before either threshold reads it."""

    def test_a_ten_point_zero_five_variance_rounds_up_and_crosses_the_warning_line(
        self, api, analyst
    ):
        """2201 against 2000 stores 10.1, not the truncated 10.0.

        PRD 3.3: "Otherwise `variance_pct` is the absolute difference between `reported_value` and
        `prior_year_value`, divided by `prior_year_value`, multiplied by 100, and rounded half up
        to one decimal place."

        Design: Corner/calculations/corner_calc_prior_year_variance_rounds_half_up_to_one_decimal
        """
        scenario = fx.component_on_locked_cycle(
            api,
            record_count=2201,
            metrics=(
                {
                    "metric_key": K.METRIC_TOTAL_HEADCOUNT,
                    "reported_value": 2201,
                    "prior_year_value": 2000,
                    "source_field_path": "sis.enrollment.headcount",
                },
                {
                    "metric_key": K.METRIC_FTE_ENROLLMENT,
                    "reported_value": 1998,
                    "prior_year_value": 2000,
                    "source_field_path": "sis.enrollment.fte",
                },
            ),
            checksum="c1d2e3f4a5b60132",
        )

        prepared = validate_success(api.prepare_component(scenario.component_id, analyst))
        assert_component_status(
            prepared, edit_status=K.EDIT_OPEN_EDITS, fatal_open_count=0
        )

        headcount = validate_success(
            api.get_component_metric(scenario.metric(K.METRIC_TOTAL_HEADCOUNT)["id"], analyst)
        )
        assert_equals_number(headcount["variance_pct"], 10.1, "metric.variance_pct")
        fte = validate_success(
            api.get_component_metric(scenario.metric(K.METRIC_FTE_ENROLLMENT)["id"], analyst)
        )
        assert_equals_number(fte["variance_pct"], 0.1, "metric.variance_pct")

        checks, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=scenario.component_id)
        )
        assert meta["total_count"] == 1
        assert_edit_check(
            checks[0],
            check_code=K.PY_VAR_PREFIX + K.METRIC_TOTAL_HEADCOUNT,
            severity=K.SEVERITY_WARNING,
            sequence_no=1,
            variance_pct=10.1,
        )


class TestEditCheckCascadeOrder:
    """The cascade walks metric keys in ascending order, not insertion order."""

    def test_a_zero_base_metric_added_second_still_takes_sequence_number_one(self, api, analyst):
        """FTE_ENROLLMENT sorts before TOTAL_HEADCOUNT even though it was reported later.

        PRD 3.3: "The component's metrics are walked in `metric_key` ascending order — ties are
        impossible because the key is unique per component — and a cascade of five branches is
        evaluated top-down for each metric, stopping at the first branch that matches, so **at most
        one check is raised per metric**:"

        Design: Corner/calculations/corner_calc_edit_checks_are_emitted_in_metric_key_ascending_order
        """
        scenario = fx.component_on_locked_cycle(
            api,
            record_count=500,
            metrics=(
                {
                    "metric_key": K.METRIC_TOTAL_HEADCOUNT,
                    "reported_value": 0,
                    "source_field_path": "sis.enrollment.headcount",
                },
                {
                    "metric_key": K.METRIC_FTE_ENROLLMENT,
                    "reported_value": 500,
                    "prior_year_value": 0,
                    "source_field_path": "sis.enrollment.fte",
                },
            ),
            checksum="c1d2e3f4a5b60131",
        )

        prepared = validate_success(api.prepare_component(scenario.component_id, analyst))
        assert_component_status(
            prepared, edit_status=K.EDIT_OPEN_EDITS, fatal_open_count=1
        )

        for key in (K.METRIC_TOTAL_HEADCOUNT, K.METRIC_FTE_ENROLLMENT):
            stored = validate_success(
                api.get_component_metric(scenario.metric(key)["id"], analyst)
            )
            assert_null(stored["variance_pct"], "%s.variance_pct" % key)

        checks, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=scenario.component_id)
        )
        assert meta["total_count"] == 2
        assert_sequence_numbers_ascending(checks)
        assert_edit_check(
            checks[0],
            check_code=K.PY_ZERO_BASE_PREFIX + K.METRIC_FTE_ENROLLMENT,
            metric_key=K.METRIC_FTE_ENROLLMENT,
            severity=K.SEVERITY_FATAL,
            sequence_no=1,
            observed_value=500,
            prior_year_value=0,
            variance_pct=None,
        )
        assert_edit_check(
            checks[1],
            check_code=K.ZERO_NO_BASE_PREFIX + K.METRIC_TOTAL_HEADCOUNT,
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            severity=K.SEVERITY_WARNING,
            sequence_no=2,
            observed_value=0,
            variance_pct=None,
        )

        _, fatal_meta = validate_paginated(
            api.list_edit_checks(
                analyst, component_id=scenario.component_id, severity=K.SEVERITY_FATAL
            )
        )
        assert fatal_meta["total_count"] == 1


class TestMappingCoverage:
    """Coverage is measured at preparation time over the required definition set."""

    def test_one_validated_mapping_out_of_two_required_definitions_raises_the_component_fatal(
        self, api, analyst, steward
    ):
        """A merely PROPOSED mapping is not coverage, so half the required set is unmapped.

        PRD 3.2: "Otherwise a definition counts as covered when at least one element mapping exists
        whose `definition_id` names it, whose `cycle_id` names the component's cycle, and whose
        `status` is `VALIDATED` — proposals and rejections never count, and `local_system_code` is
        ignored entirely, so any single validated mapping covers its definition no matter which
        local system it came from."

        Design: Corner/calculations/corner_calc_half_covered_mapping_raises_the_component_level_fatal_check
        """
        scenario = fx.component_on_locked_cycle(api, checksum="c1d2e3f4a5b60129")
        level = fx.create_definition(
            api,
            steward,
            definition_code="ENR_LEVEL",
            value_domain=["UNDERGRAD", "GRADUATE"],
            required=True,
            unit_of_measure="code",
        )
        status = fx.create_definition(
            api,
            steward,
            definition_code="ENR_STATUS",
            value_domain=["FULL_TIME", "PART_TIME"],
            required=True,
            unit_of_measure="code",
        )
        covered = fx.validated_mapping(
            api,
            scenario.cycle_id,
            level["id"],
            local_field_path="sis.student.level",
            transform_expression="upper(level_code)",
            value_map={"UG": "UNDERGRAD", "GR": "GRADUATE"},
        )
        uncovered = fx.propose_mapping(
            api,
            scenario.cycle_id,
            status["id"],
            analyst,
            local_field_path="sis.student.load",
            transform_expression="upper(load_code)",
            value_map={"FT": "FULL_TIME"},
        )
        assert covered["status"] == K.MAPPING_VALIDATED
        assert uncovered["status"] == K.MAPPING_PROPOSED

        prepared = validate_success(api.prepare_component(scenario.component_id, analyst))
        assert_equals_number(prepared["mapping_coverage_pct"], 50.0, "mapping_coverage_pct")
        assert_component_status(
            prepared,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_OPEN_EDITS,
            fatal_open_count=1,
        )
        assert prepared["prepared_by_user_id"] == "analyst-1"

        checks, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=scenario.component_id)
        )
        assert meta["total_count"] == 1
        assert_edit_check(
            checks[0],
            check_code=K.CHECK_CODE_UNMAPPED_ELEMENTS,
            metric_key=K.UNMAPPED_ELEMENTS_METRIC_KEY,
            severity=K.SEVERITY_FATAL,
            status=K.CHECK_OPEN,
            sequence_no=1,
            variance_pct=None,
            observed_value=None,
            prior_year_value=None,
        )

    def test_definitions_of_another_survey_year_or_optional_status_are_not_required(
        self, api, analyst, steward
    ):
        """With the required set empty the convention is full coverage and no flag.

        PRD 3.2: "When that set is empty the convention is that nothing required is fully covered,
        and `mapping_coverage_pct` is 100.0."

        Design: Corner/calculations/corner_calc_mapping_coverage_required_set_is_filtered_by_component_and_cycle
        """
        scenario = fx.component_on_locked_cycle(api, checksum="c1d2e3f4a5b60130")
        fx.create_definition(
            api,
            steward,
            definition_code="CMP_CIP",
            survey_component=K.DOMAIN_COMPLETIONS,
            value_domain=["CIP_11", "CIP_14"],
            required=True,
            unit_of_measure="code",
        )
        fx.create_definition(
            api,
            steward,
            definition_code="ENR_OPTIONAL",
            survey_component=K.DOMAIN_ENROLLMENT,
            value_domain=["YES", "NO"],
            required=False,
            unit_of_measure="flag",
        )
        fx.create_definition(
            api,
            steward,
            definition_code="ENR_FUTURE",
            survey_component=K.DOMAIN_ENROLLMENT,
            value_domain=["UNDERGRAD"],
            required=True,
            unit_of_measure="code",
            effective_cycle_code=K.CYCLE_CODE_ALT,
        )

        prepared = validate_success(api.prepare_component(scenario.component_id, analyst))
        assert_equals_number(prepared["mapping_coverage_pct"], 100.0, "mapping_coverage_pct")
        assert_component_status(
            prepared,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_CLEARED,
            fatal_open_count=0,
        )
        assert_null(prepared["core_expense_per_fte_cents"], "core_expense_per_fte_cents")

        _, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=scenario.component_id)
        )
        assert meta["total_count"] == 0


class TestPrepareGatesOnTheReferencedExtract:
    """The preparation gate reads a third entity: the extract the component points at."""

    @staticmethod
    def _reopened_cycle(api, director, checksum):
        scenario = fx.frozen_cycle(api, checksum=checksum)
        scenario.cycle = validate_success(
            api.reopen_cycle(
                scenario.cycle_id,
                f.make_reopen_payload(
                    reopen_reason=(
                        "The vendor re-delivered the census extract after correcting a residency flag."
                    )
                ),
                director,
            )
        )
        return scenario

    def test_a_superseded_extract_blocks_a_draft_component_on_a_reopened_cycle(
        self, api, registrar, analyst, director
    ):
        """Both the component and its cycle are in permitting states; only the extract is not.

        PRD 3.3: "Four preconditions guard it: the component must be `DRAFT`; the parent cycle's
        posture must be `CENSUS_LOCKED` or `REOPENED`, because the census-date snapshot rule permits
        preparation only from a census-locked extract, and anything else reports
        `ERR_INVALID_CYCLE_STATE`; the referenced extract's `status` must be `ACTIVE` or `LOCKED`,
        and a `SUPERSEDED` extract reports `ERR_FROZEN_FILE_SUPERSEDED`; and at least one component
        metric must exist, failing which the run reports `ERR_NO_METRICS`."

        Design: Difficulty/cross_entity_state_dependency/prepare_refused_when_referenced_census_extract_is_superseded
        """
        scenario = self._reopened_cycle(api, director, "a1b2c3d4e5f60014")
        incumbent_id = scenario.extract_id

        replacement = fx.register_extract(
            api,
            scenario.cycle_id,
            None,
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1005,
            coverage_start_date=K.COVERAGE_START,
            coverage_end_date=K.COVERAGE_END,
            checksum="b2c3d4e5f6a70015",
        )

        refused = api.prepare_component(scenario.component_id, analyst)
        validate_error(refused, ApiErrorId.FROZEN_FILE_SUPERSEDED, 409)

        incumbent = validate_success(api.get_frozen_file(incumbent_id, registrar))
        assert incumbent["status"] == K.FROZEN_FILE_SUPERSEDED
        successor = validate_success(api.get_frozen_file(replacement["id"], registrar))
        assert successor["status"] == K.FROZEN_FILE_ACTIVE
        assert successor["supersedes_frozen_file_id"] == incumbent_id

        cycle = validate_success(api.get_reporting_cycle(scenario.cycle_id, registrar))
        assert cycle["active_record_count"] == 1005
        assert cycle["snapshot_posture"] == K.POSTURE_REOPENED

        component = validate_success(api.get_survey_component(scenario.component_id, analyst))
        assert_component_status(
            component, prep_status=K.PREP_DRAFT, edit_status=K.EDIT_NOT_RUN
        )

    def test_a_reopened_cycle_prepares_again_while_its_extract_is_still_locked(
        self, api, registrar, analyst, director
    ):
        """A fresh extract over another window leaves the referenced one LOCKED and admissible.

        PRD 3.3: "A successful run writes the acting operator's identifier into
        `prepared_by_user_id`, sets `prep_status` to `PREPARED`, increments `version`, recomputes
        `mapping_coverage_pct`, recomputes `core_expense_per_fte_cents` for finance components
        (writing null for all others), recomputes every metric's `variance_pct`, raises the edit
        checks described next, re-derives `edit_status`, and recomputes `fatal_open_count`."

        Design: Difficulty/cross_entity_state_dependency/prepare_refused_when_referenced_census_extract_is_superseded
        """
        scenario = self._reopened_cycle(api, director, "a1b2c3d4e5f60016")

        fresh = fx.register_extract(
            api,
            scenario.cycle_id,
            None,
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=40,
            coverage_start_date=K.COVERAGE_START_SECOND,
            coverage_end_date=K.COVERAGE_END_SECOND,
            checksum="b2c3d4e5f6a70017",
        )
        assert_null(fresh["supersedes_frozen_file_id"], "supersedes_frozen_file_id")

        referenced = validate_success(api.get_frozen_file(scenario.extract_id, registrar))
        assert referenced["status"] == K.FROZEN_FILE_LOCKED

        prepared = validate_success(api.prepare_component(scenario.component_id, analyst))
        assert_component_status(
            prepared,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_CLEARED,
            fatal_open_count=0,
        )
        assert prepared["prepared_by_user_id"] == "analyst-1"
        assert_equals_number(prepared["mapping_coverage_pct"], 100.0, "mapping_coverage_pct")
