"""Opening survey components against a sealed extract and attaching reported figures."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_component_status,
    assert_equals_number,
    assert_null,
    assert_one_decimal,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
)


class TestSurveyComponentCreation:
    """A component is a workspace bound to one cycle and one same-cycle extract."""

    def test_omitting_the_component_code_is_a_schema_failure_before_any_posture_check(
        self, api, registrar, analyst
    ):
        """The cycle would admit the create, so only the missing field can explain the refusal.

        PRD 3.3: "An `IRAnalyst` opens a **survey component** — the preparation workspace for one
        survey of one cycle — by naming the `cycle_id`, the `frozen_file_id` of the census extract
        the component will be prepared from, and the `component_code` identifying the survey
        (`ENROLLMENT`, `COMPLETIONS`, `FINANCE` or `HR`)."

        Design: Corner/entities/corner_component_creation_missing_component_code_is_invalid_request
        """
        scenario = fx.census_locked_cycle(api, checksum="c1d2e3f4a5b60105")

        refused = api.create_survey_component(
            {"cycle_id": scenario.cycle_id, "frozen_file_id": scenario.extract_id}, analyst
        )
        validate_error(refused, ApiErrorId.INVALID_REQUEST, 400)

        rows, meta = validate_paginated(
            api.list_survey_components(analyst, cycle_id=scenario.cycle_id)
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_referenced_extract_must_hang_under_the_component_s_own_cycle(
        self, api, registrar, analyst
    ):
        """A real extract belonging to another cycle is unresolvable, not a state conflict.

        PRD 3.3: "The referenced extract must belong to that same cycle and its `domain` must
        equal the requested `component_code`; an extract from another cycle or from another domain
        is treated as unresolvable and reports `ERR_FROZEN_FILE_NOT_FOUND`."

        Design: Corner/entities/corner_component_requires_its_parent_cycle_and_a_same_cycle_extract
        """
        other_cycle = fx.create_cycle(
            api,
            registrar,
            cycle_code="IPEDS-2026",
            collection_year=2026,
            census_date="2025-10-15",
            collection_deadline="2026-02-15T23:59:59Z",
        )
        other_extract = fx.register_extract(
            api,
            other_cycle["id"],
            other_cycle["version"],
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=900,
            coverage_start_date="2025-09-01",
            coverage_end_date="2025-10-15",
            checksum="c1d2e3f4a5b60112",
        )
        scenario = fx.census_locked_cycle(api, checksum="c1d2e3f4a5b60113")

        unknown_parent = api.create_survey_component(
            f.make_survey_component_payload(
                K.UNKNOWN_UUID, scenario.extract_id, K.DOMAIN_ENROLLMENT
            ),
            analyst,
        )
        validate_error(unknown_parent, ApiErrorId.CYCLE_NOT_FOUND, 404)

        cross_cycle = api.create_survey_component(
            f.make_survey_component_payload(
                scenario.cycle_id, other_extract["id"], K.DOMAIN_ENROLLMENT
            ),
            analyst,
        )
        validate_error(cross_cycle, ApiErrorId.FROZEN_FILE_NOT_FOUND, 404)

        component = validate_success(
            api.create_survey_component(
                f.make_survey_component_payload(
                    scenario.cycle_id, scenario.extract_id, K.DOMAIN_ENROLLMENT
                ),
                analyst,
            ),
            201,
        )
        assert component["cycle_id"] == scenario.cycle_id
        assert component["frozen_file_id"] == scenario.extract_id
        assert_component_status(component, prep_status=K.PREP_DRAFT, edit_status=K.EDIT_NOT_RUN)

        _, meta = validate_paginated(
            api.list_survey_components(analyst, cycle_id=scenario.cycle_id)
        )
        assert meta["total_count"] == 1


class TestMetricDomainTable:
    """Each survey accepts only its own closed set of metric keys."""

    def test_each_survey_keeps_its_own_keys_while_the_fte_figure_is_shared(
        self, api, registrar, analyst
    ):
        """FTE_ENROLLMENT is legal on FINANCE as well because the per-FTE figure needs it there.

        PRD 3.3: "`FTE_ENROLLMENT` appears in two sets on purpose: the per-FTE expense figure
        below needs it on the `FINANCE` component, not merely on the enrollment one. Any other
        pairing is refused with `ERR_METRIC_DOMAIN_MISMATCH`, and the same rule governs the
        `metric_key` an external submission names against its source component (§3.8)."

        Design: Corner/validations/corner_val_metric_key_must_belong_to_the_component_domain_except_shared_fte
        """
        cycle = fx.create_cycle(api, registrar)
        enrollment_extract = fx.register_extract(
            api,
            cycle["id"],
            cycle["version"],
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1000,
            checksum="c1d2e3f4a5b60140",
        )
        finance_extract = fx.register_extract(
            api,
            cycle["id"],
            None,
            registrar,
            domain=K.DOMAIN_FINANCE,
            record_count=12,
            coverage_start_date="2026-07-01",
            coverage_end_date="2026-10-15",
            checksum="c1d2e3f4a5b60141",
        )
        fx.move_clock(api, K.CLOCK_AFTER_CENSUS, registrar)
        validate_success(api.census_lock_cycle(cycle["id"], registrar))

        enrollment_component = validate_success(
            api.create_survey_component(
                f.make_survey_component_payload(
                    cycle["id"], enrollment_extract["id"], K.DOMAIN_ENROLLMENT
                ),
                analyst,
            ),
            201,
        )
        finance_component = validate_success(
            api.create_survey_component(
                f.make_survey_component_payload(
                    cycle["id"], finance_extract["id"], K.DOMAIN_FINANCE
                ),
                analyst,
            ),
            201,
        )

        wrong_on_enrollment = api.add_component_metric(
            enrollment_component["id"],
            f.make_metric_payload(
                metric_key=K.METRIC_TOTAL_COMPLETIONS,
                reported_value=500,
                source_field_path="sis.completions.total",
            ),
            analyst,
        )
        validate_error(wrong_on_enrollment, ApiErrorId.METRIC_DOMAIN_MISMATCH, 422)

        wrong_on_finance = api.add_component_metric(
            finance_component["id"],
            f.make_metric_payload(
                metric_key=K.METRIC_TOTAL_HEADCOUNT,
                reported_value=1000,
                source_field_path="sis.enrollment.headcount",
            ),
            analyst,
        )
        validate_error(wrong_on_finance, ApiErrorId.METRIC_DOMAIN_MISMATCH, 422)

        shared_on_enrollment = validate_success(
            api.add_component_metric(
                enrollment_component["id"],
                f.make_metric_payload(
                    metric_key=K.METRIC_FTE_ENROLLMENT,
                    reported_value=940,
                    prior_year_value=940,
                    source_field_path="sis.enrollment.fte",
                ),
                analyst,
            ),
            201,
        )
        assert shared_on_enrollment["metric_key"] == K.METRIC_FTE_ENROLLMENT

        shared_on_finance = validate_success(
            api.add_component_metric(
                finance_component["id"],
                f.make_metric_payload(
                    metric_key=K.METRIC_FTE_ENROLLMENT,
                    reported_value=940,
                    prior_year_value=940,
                    source_field_path="fin.fte.reported",
                ),
                analyst,
            ),
            201,
        )
        assert shared_on_finance["metric_key"] == K.METRIC_FTE_ENROLLMENT

        hr_key_on_enrollment_source = api.create_external_submission(
            f.make_external_submission_payload(
                cycle["id"],
                enrollment_component["id"],
                target_type=K.TARGET_STATE,
                target_name="State Board of Higher Education",
                metric_key=K.METRIC_INSTRUCTIONAL_STAFF_HEADCOUNT,
                reported_value=300,
            ),
            analyst,
        )
        validate_error(hr_key_on_enrollment_source, ApiErrorId.METRIC_DOMAIN_MISMATCH, 422)

        _, metric_meta = validate_paginated(
            api.list_component_metrics(analyst, component_id=enrollment_component["id"])
        )
        assert metric_meta["total_count"] == 1
        _, submission_meta = validate_paginated(
            api.list_external_submissions(analyst, cycle_id=cycle["id"])
        )
        assert submission_meta["total_count"] == 0


class TestMetricCorrection:
    """A correction rewrites the figure, re-derives its variance and marks the row."""

    def test_a_correction_recomputes_the_variance_and_the_restated_flag_never_clears(
        self, api, analyst
    ):
        """Correcting the figure back to its original value leaves `restated` true.

        PRD 3.3: "The correction supplies a replacement `reported_value` and an optional
        `restatement_note` explaining the change; the stored value is overwritten, `restated` is
        set to true, the supplied note is stored, that metric's `variance_pct` is recomputed, and
        `version` is incremented."

        Design: Corner/endpoints/corner_ep_metric_patch_recomputes_variance_and_flags_the_row_restated
        """
        scenario = fx.component_on_locked_cycle(api, checksum="c1d2e3f4a5b60156")
        metric = scenario.metrics[0]
        assert_null(metric["variance_pct"], "metric.variance_pct")
        assert metric["restated"] is False
        assert_null(metric["restatement_note"], "metric.restatement_note")
        assert_version(metric, 1, "metric")

        note = "Residency reclassification added 125 students after the extract was pulled."
        corrected = validate_success(
            api.correct_component_metric(
                metric["id"],
                f.make_metric_correction_payload(1125, restatement_note=note),
                analyst,
            )
        )
        assert_equals_number(corrected["reported_value"], 1125, "metric.reported_value")
        assert_equals_number(corrected["variance_pct"], 12.5, "metric.variance_pct")
        assert_one_decimal(corrected["variance_pct"], "metric.variance_pct")
        assert corrected["restated"] is True
        assert corrected["restatement_note"] == note
        assert_version(corrected, 2, "metric")

        reverted = validate_success(
            api.correct_component_metric(
                metric["id"], f.make_metric_correction_payload(1000), analyst
            )
        )
        assert_equals_number(reverted["reported_value"], 1000, "metric.reported_value")
        assert_equals_number(reverted["variance_pct"], 0.0, "metric.variance_pct")
        assert reverted["restated"] is True
        assert_version(reverted, 3, "metric")

        stored = validate_success(api.get_component_metric(metric["id"], analyst))
        assert_equals_number(stored["variance_pct"], 0.0, "metric.variance_pct")
        assert stored["restated"] is True

        prepared = validate_success(api.prepare_component(scenario.component_id, analyst))
        assert_component_status(prepared, prep_status=K.PREP_PREPARED, edit_status=K.EDIT_CLEARED)
        _, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=scenario.component_id)
        )
        assert meta["total_count"] == 0


FINANCE_EXPENSE_METRICS = (
    {
        "metric_key": K.METRIC_INSTRUCTION_EXPENSES_CENTS,
        "reported_value": 1000007,
        "source_field_path": "fin.gl.instruction_total",
    },
    {
        "metric_key": K.METRIC_ACADEMIC_SUPPORT_EXPENSES_CENTS,
        "reported_value": 500007,
        "source_field_path": "fin.gl.academic_support_total",
    },
    {
        "metric_key": K.METRIC_STUDENT_SERVICES_EXPENSES_CENTS,
        "reported_value": 250007,
        "source_field_path": "fin.gl.student_services_total",
    },
)


class TestCoreExpensePerFte:
    """The per-FTE expense figure rounds each category before summing."""

    @staticmethod
    def _finance_component(api, fte_value, checksum):
        specs = list(FINANCE_EXPENSE_METRICS) + [
            {
                "metric_key": K.METRIC_FTE_ENROLLMENT,
                "reported_value": fte_value,
                "source_field_path": "sis.enrollment.fte",
            }
        ]
        return fx.component_on_locked_cycle(
            api,
            domain=K.DOMAIN_FINANCE,
            record_count=4,
            metrics=specs,
            coverage_start_date=K.REPORTING_YEAR_FLOOR,
            coverage_end_date=K.REPORTING_YEAR_CEILING,
            checksum=checksum,
        )

    def test_each_category_is_rounded_to_whole_cents_before_the_three_are_added(self, api, analyst):
        """166668 + 83335 + 41668 is 291671, one cent above the sum-then-divide order.

        PRD 3.3: "Otherwise **each functional category is divided by the FTE enrollment and
        rounded half up to whole cents first, and the three whole-cent results are then added
        together**."

        Design: Difficulty/combinatorial_formula/finance_core_expense_per_fte_rounds_each_category_before_summing
        """
        scenario = self._finance_component(api, 6, "a1b2c3d4e5f60003")

        prepared = validate_success(api.prepare_component(scenario.component_id, analyst))
        assert prepared["core_expense_per_fte_cents"] == 291671
        assert prepared["core_expense_per_fte_cents"] != 291670
        assert_component_status(
            prepared, prep_status=K.PREP_PREPARED, edit_status=K.EDIT_CLEARED, fatal_open_count=0
        )
        assert_equals_number(prepared["mapping_coverage_pct"], 100.0, "mapping_coverage_pct")
        assert_one_decimal(prepared["mapping_coverage_pct"], "mapping_coverage_pct")

        rows, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=scenario.component_id)
        )
        assert meta["total_count"] == 0
        assert rows == []

        academic = scenario.metric(K.METRIC_ACADEMIC_SUPPORT_EXPENSES_CENTS)
        stored = validate_success(api.get_component_metric(academic["id"], analyst))
        assert_null(stored["variance_pct"], "metric.variance_pct")

    def test_a_zero_fte_enrollment_publishes_no_per_fte_figure_at_all(self, api, analyst):
        """The guard is a null result rather than a division by zero.

        PRD 3.3: "If any of those four metrics is absent from the component, or if the FTE
        enrollment figure is exactly 0, the result is null and no per-FTE figure is published."

        Design: Difficulty/combinatorial_formula/finance_core_expense_per_fte_rounds_each_category_before_summing
        """
        scenario = self._finance_component(api, 0, "a1b2c3d4e5f60004")

        prepared = validate_success(api.prepare_component(scenario.component_id, analyst))
        assert_null(prepared["core_expense_per_fte_cents"], "core_expense_per_fte_cents")
        assert prepared["prep_status"] == K.PREP_PREPARED
        assert prepared["fatal_open_count"] == 0
