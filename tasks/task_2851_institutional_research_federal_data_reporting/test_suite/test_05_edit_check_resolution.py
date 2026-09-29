"""Talking an edit check down: the explanation loop, the two decisions and the certify gate."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_component_status,
    assert_edit_check,
    assert_null,
    assert_version,
    assert_version_bumped,
    constants as K,
    factories as f,
    fixtures as fx,
)

HEADCOUNT_EXPLANATION = (
    "A new dual-enrollment high-school program added 125 undergraduates at census."
)
HEADCOUNT_PRIOR_NOTE = "Prior year predates the dual-enrollment agreement."
CERTIFICATION_STATEMENT = (
    "I certify the enrollment component as reported to the federal collection."
)


class TestCertifyRequiresClearedEditStatus:
    """The certify gate is the one place where the two state dimensions meet."""

    def test_certify_is_refused_until_the_check_is_explained_and_accepted(
        self, api, analyst, director
    ):
        """Certification only opens after the raised check has reached a terminal verdict.

        PRD 3.5: "The component's `edit_status` must be exactly `CLEARED`, so every raised check
        must have reached `ACCEPTED`, `WAIVED` or `VOIDED`; anything else reports
        `ERR_EDIT_CHECKS_UNRESOLVED`, and note that this gate is what makes the two state
        dimensions meet — `prep_status` and `edit_status` evolve independently everywhere except
        here."

        Design: Corner/state_machines/corner_sm_certify_requires_cleared_edit_status_after_explain_and_accept
        """
        scenario = fx.prepared_component(
            api,
            record_count=1125,
            metrics=[
                {
                    "metric_key": K.METRIC_TOTAL_HEADCOUNT,
                    "reported_value": 1125,
                    "prior_year_value": 1000,
                    "source_field_path": "sis.enrollment.headcount",
                }
            ],
            checksum="c1d2e3f4a5b60121",
        )
        assert len(scenario.checks) == 1
        check = scenario.checks[0]
        assert_edit_check(
            check,
            check_code=K.PY_VAR_PREFIX + K.METRIC_TOTAL_HEADCOUNT,
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            severity=K.SEVERITY_WARNING,
            status=K.CHECK_OPEN,
            sequence_no=1,
            variance_pct=12.5,
            observed_value=1125,
            prior_year_value=1000,
            explanation_round=0,
        )
        assert_component_status(
            scenario.component,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_OPEN_EDITS,
            fatal_open_count=0,
        )

        refused = api.certify_component(
            scenario.component_id, f.make_certification_payload(CERTIFICATION_STATEMENT), director
        )
        validate_error(refused, ApiErrorId.EDIT_CHECKS_UNRESOLVED, 409)

        held = validate_success(api.get_survey_component(scenario.component_id, analyst))
        assert_component_status(
            held, prep_status=K.PREP_PREPARED, edit_status=K.EDIT_OPEN_EDITS, fatal_open_count=0
        )
        assert_null(held["certified_by_user_id"], "component.certified_by_user_id")
        assert_null(held["certification_statement"], "component.certification_statement")

        explained = validate_success(
            api.explain_edit_check(
                check["id"],
                f.make_explanation_payload(HEADCOUNT_EXPLANATION, HEADCOUNT_PRIOR_NOTE),
                analyst,
            )
        )
        assert_edit_check(explained, status=K.CHECK_EXPLAINED, explanation_round=1)
        assert explained["explained_by_user_id"] == "analyst-1"
        assert_component_status(
            validate_success(api.get_survey_component(scenario.component_id, analyst)),
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_EXPLAINED,
        )

        accepted = validate_success(
            api.adjudicate_edit_check(
                check["id"],
                f.make_adjudication_payload(
                    K.DECISION_ACCEPT, "Explanation matches the signed program agreement."
                ),
                director,
            )
        )
        assert_edit_check(accepted, status=K.CHECK_ACCEPTED)
        assert accepted["adjudicated_by_user_id"] == "director-1"

        cleared = validate_success(api.get_survey_component(scenario.component_id, analyst))
        assert_component_status(
            cleared,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_CLEARED,
            fatal_open_count=0,
        )

        certified = validate_success(
            api.certify_component(
                scenario.component_id,
                f.make_certification_payload(CERTIFICATION_STATEMENT),
                director,
            )
        )
        assert_component_status(
            certified, prep_status=K.PREP_CERTIFIED, edit_status=K.EDIT_CLEARED
        )
        assert certified["certified_by_user_id"] == "director-1"
        assert certified["certification_statement"] == CERTIFICATION_STATEMENT


class TestEditCheckTransitionList:
    """Each verb is defined from a closed list of source states and nowhere else."""

    def test_adjudicating_an_open_check_and_reexplaining_an_accepted_one_are_both_refused(
        self, api, analyst, director
    ):
        """Neither refusal moves the check's status nor advances its explanation counter.

        PRD 3.4: "Both variants require the parent component to be sitting at `prep_status`
        `PREPARED`, and a check on a component in any other preparation state is refused with
        `ERR_INVALID_COMPONENT_STATE`; a check whose own `status` is neither `OPEN` nor `REJECTED`
        is refused with `ERR_INVALID_EDIT_CHECK_STATE`."

        PRD 3.4: "All three branches require the check to be `EXPLAINED` (otherwise
        `ERR_INVALID_EDIT_CHECK_STATE`) and all three require the acting `X-User-ID` to differ from
        `explained_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/state_machines/corner_sm_edit_check_rejects_triggers_outside_its_transition_list
        """
        scenario = fx.prepared_component(
            api,
            record_count=1125,
            metrics=[
                {
                    "metric_key": K.METRIC_TOTAL_HEADCOUNT,
                    "reported_value": 1125,
                    "prior_year_value": 1000,
                    "source_field_path": "sis.enrollment.headcount",
                }
            ],
            checksum="c1d2e3f4a5b60125",
        )
        open_checks, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=scenario.component_id, status=K.CHECK_OPEN)
        )
        assert meta["total_count"] == 1
        assert len(open_checks) == 1
        check = open_checks[0]
        assert_edit_check(check, status=K.CHECK_OPEN, explanation_round=0)

        premature = api.adjudicate_edit_check(
            check["id"],
            f.make_adjudication_payload(
                K.DECISION_ACCEPT, "Adjudicating before any explanation exists."
            ),
            director,
        )
        validate_error(premature, ApiErrorId.INVALID_EDIT_CHECK_STATE, 409)

        untouched = validate_success(api.get_edit_check(check["id"], analyst))
        assert_edit_check(untouched, status=K.CHECK_OPEN, explanation_round=0)
        assert_null(untouched["adjudicated_by_user_id"], "edit_check.adjudicated_by_user_id")

        validate_success(
            api.explain_edit_check(
                check["id"],
                f.make_explanation_payload(HEADCOUNT_EXPLANATION, HEADCOUNT_PRIOR_NOTE),
                analyst,
            )
        )
        accepted = validate_success(
            api.adjudicate_edit_check(
                check["id"],
                f.make_adjudication_payload(
                    K.DECISION_ACCEPT, "Explanation matches the signed program agreement."
                ),
                director,
            )
        )
        assert_edit_check(accepted, status=K.CHECK_ACCEPTED, explanation_round=1)

        replay = api.explain_edit_check(
            check["id"],
            f.make_explanation_payload(
                "Attempting to re-explain a check that has already been accepted.",
                "No new information is offered.",
            ),
            analyst,
        )
        validate_error(replay, ApiErrorId.INVALID_EDIT_CHECK_STATE, 409)

        terminal = validate_success(api.get_edit_check(check["id"], analyst))
        assert_edit_check(terminal, status=K.CHECK_ACCEPTED, explanation_round=1)
        assert terminal["explanation_text"] == HEADCOUNT_EXPLANATION
        assert_component_status(
            validate_success(api.get_survey_component(scenario.component_id, analyst)),
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_CLEARED,
        )


class TestExplanationLengthBoundary:
    """The twenty-character floor is measured after trimming and is inclusive."""

    def test_nineteen_characters_is_refused_while_exactly_twenty_passes(
        self, api, analyst
    ):
        """The refused round leaves the narrative unwritten and the counter at zero.

        PRD 3.4: "The payload carries `explanation_text`, the analyst's account of the flagged
        value, which must be at least 20 characters after trimming and at most 2000 — anything
        shorter is refused with `ERR_EXPLANATION_TOO_SHORT` — and `prior_year_comparison_note`, the
        narrative comparing the value to the prior year, which must be between 10 and 2000
        characters, with a violation reported as `ERR_INVALID_REQUEST`."

        Design: Corner/validations/corner_val_explanation_length_boundary_at_twenty_characters
        """
        too_short = "Late add-drop surge"
        long_enough = "Late add-drop surge."
        assert len(too_short) == 19
        assert len(long_enough) == K.MIN_EXPLANATION_LENGTH

        scenario = fx.prepared_component(
            api,
            record_count=1125,
            metrics=[
                {
                    "metric_key": K.METRIC_TOTAL_HEADCOUNT,
                    "reported_value": 1125,
                    "prior_year_value": 1000,
                    "source_field_path": "sis.enrollment.headcount",
                }
            ],
            checksum="c1d2e3f4a5b60142",
        )
        check = scenario.checks[0]
        prior_note = "Prior year headcount was 1000 on the same census date."

        refused = api.explain_edit_check(
            check["id"], f.make_explanation_payload(too_short, prior_note), analyst
        )
        validate_error(refused, ApiErrorId.EXPLANATION_TOO_SHORT, 422)

        unwritten = validate_success(api.get_edit_check(check["id"], analyst))
        assert_edit_check(unwritten, status=K.CHECK_OPEN, explanation_round=0)
        assert_null(unwritten["explanation_text"], "edit_check.explanation_text")
        assert_version(unwritten, 1, "edit_check")
        assert_component_status(
            validate_success(api.get_survey_component(scenario.component_id, analyst)),
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_OPEN_EDITS,
        )

        accepted = validate_success(
            api.explain_edit_check(
                check["id"], f.make_explanation_payload(long_enough, prior_note), analyst
            )
        )
        assert_edit_check(accepted, status=K.CHECK_EXPLAINED, explanation_round=1)
        assert accepted["explanation_text"] == long_enough
        assert accepted["explained_by_user_id"] == "analyst-1"
        assert_component_status(
            validate_success(api.get_survey_component(scenario.component_id, analyst)),
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_EXPLAINED,
        )


class TestWaiverIsSeverityConditional:
    """WAIVE and ACCEPT share one endpoint but not one set of legal targets."""

    def test_the_fatal_check_refuses_the_waiver_while_the_warning_waives_cleanly(
        self, api, analyst, director
    ):
        """The same payload is legal on the warning and illegal on the fatal check.

        PRD 3.4: "A decision of `WAIVE` drives `EXPLAINED → WAIVED` and is the divergent branch: it
        clears the check *without* accepting the explanation, and it is legal only when the check's
        `severity` is `WARNING` — a waiver aimed at a `FATAL` check is refused with
        `ERR_WAIVER_NOT_PERMITTED`."

        Design: Corner/validations/corner_val_a_fatal_check_cannot_be_waived_but_a_warning_can
        """
        scenario = fx.prepared_component(
            api,
            record_count=1300,
            metrics=[
                {
                    "metric_key": K.METRIC_FTE_ENROLLMENT,
                    "reported_value": 1125,
                    "prior_year_value": 1000,
                    "source_field_path": "sis.enrollment.fte",
                },
                {
                    "metric_key": K.METRIC_TOTAL_HEADCOUNT,
                    "reported_value": 1300,
                    "prior_year_value": 1000,
                    "source_field_path": "sis.enrollment.headcount",
                },
            ],
            checksum="c1d2e3f4a5b60148",
        )
        assert len(scenario.checks) == 2
        warning, fatal = scenario.checks
        assert_edit_check(
            warning,
            check_code=K.PY_VAR_PREFIX + K.METRIC_FTE_ENROLLMENT,
            severity=K.SEVERITY_WARNING,
            sequence_no=1,
            variance_pct=12.5,
        )
        assert_edit_check(
            fatal,
            check_code=K.PY_VAR_PREFIX + K.METRIC_TOTAL_HEADCOUNT,
            severity=K.SEVERITY_FATAL,
            sequence_no=2,
            variance_pct=30.0,
        )

        validate_success(
            api.explain_edit_check(
                warning["id"],
                f.make_explanation_payload(
                    "Full-time load definition was corrected mid-year, lifting the FTE conversion.",
                    "Prior year FTE was 1000 under the old load table.",
                ),
                analyst,
            )
        )
        validate_success(
            api.explain_edit_check(
                fatal["id"],
                f.make_explanation_payload(
                    "A new online campus opened and added three hundred headcount in one term.",
                    "Prior year headcount was 1000 before the online campus.",
                ),
                analyst,
            )
        )
        assert_component_status(
            validate_success(api.get_survey_component(scenario.component_id, analyst)),
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_EXPLAINED,
            fatal_open_count=1,
        )

        refused = api.adjudicate_edit_check(
            fatal["id"],
            f.make_adjudication_payload(
                K.DECISION_WAIVE, "Attempting to waive the fatal variance to save time."
            ),
            director,
        )
        validate_error(refused, ApiErrorId.WAIVER_NOT_PERMITTED, 422)
        assert_edit_check(
            validate_success(api.get_edit_check(fatal["id"], analyst)), status=K.CHECK_EXPLAINED
        )
        assert_component_status(
            validate_success(api.get_survey_component(scenario.component_id, analyst)),
            fatal_open_count=1,
        )

        waived = validate_success(
            api.adjudicate_edit_check(
                warning["id"],
                f.make_adjudication_payload(
                    K.DECISION_WAIVE,
                    "Warning-level variance waived; the load-table change is documented.",
                ),
                director,
            )
        )
        assert_edit_check(waived, status=K.CHECK_WAIVED)

        accepted = validate_success(
            api.adjudicate_edit_check(
                fatal["id"],
                f.make_adjudication_payload(
                    K.DECISION_ACCEPT,
                    "Explanation accepted; the online campus enrolment is verified.",
                ),
                director,
            )
        )
        assert_edit_check(accepted, status=K.CHECK_ACCEPTED)

        cleared = validate_success(api.get_survey_component(scenario.component_id, analyst))
        assert_component_status(
            cleared,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_CLEARED,
            fatal_open_count=0,
        )

        certified = validate_success(
            api.certify_component(
                scenario.component_id,
                f.make_certification_payload(CERTIFICATION_STATEMENT),
                director,
            )
        )
        assert_component_status(certified, prep_status=K.PREP_CERTIFIED)


NURSING_EXPLANATION = (
    "Growth attributed to the new nursing programme cohort enrolled this fall."
)
NURSING_PRIOR_NOTE = "Prior year 1000, current year 1100."
NURSING_REJECTION = "Explanation does not reconcile with the programme census roster."
NURSING_REVISION = (
    "Revised explanation: 100 of the increase are nursing entrants, cross-checked against the "
    "programme roster."
)
NURSING_REVISION_NOTE = (
    "Prior year 1000, current year 1100, reconciled to the nursing roster."
)


class TestTwoIndependentDimensions:
    """prep_status and edit_status are two dimensions of one row, not one status field."""

    @staticmethod
    def _prepared_with_one_warning(api):
        """A PREPARED component holding exactly one OPEN WARNING check at 10.0 percent."""
        return fx.prepared_component(
            api,
            record_count=1100,
            metrics=[
                {
                    "metric_key": K.METRIC_TOTAL_HEADCOUNT,
                    "reported_value": 1100,
                    "prior_year_value": 1000,
                    "source_field_path": "sis.enrollment.total_headcount",
                }
            ],
            checksum="a1b2c3d4e5f60007",
        )

    @staticmethod
    def _negotiate_to_accepted(api, check_id, analyst, director):
        """Explain, suffer a rejection, re-explain and finally win acceptance."""
        validate_success(
            api.explain_edit_check(
                check_id,
                f.make_explanation_payload(NURSING_EXPLANATION, NURSING_PRIOR_NOTE),
                analyst,
            )
        )
        validate_success(
            api.adjudicate_edit_check(
                check_id,
                f.make_adjudication_payload(K.DECISION_REJECT, NURSING_REJECTION),
                director,
            )
        )
        validate_success(
            api.explain_edit_check(
                check_id,
                f.make_explanation_payload(NURSING_REVISION, NURSING_REVISION_NOTE),
                analyst,
            )
        )
        return validate_success(
            api.adjudicate_edit_check(
                check_id,
                f.make_adjudication_payload(
                    K.DECISION_ACCEPT, "Revised explanation reconciles; accepted."
                ),
                director,
            )
        )

    def test_the_rejection_loop_rewinds_edit_status_and_never_touches_prep_status(
        self, api, analyst, director
    ):
        """Two explanation rounds pass while prep_status holds the single value PREPARED.

        PRD 3.4: "A single rejection is enough to drive `EXPLAINED → OPEN_EDITS`, which is the
        rejection loop: the component falls back out of `EXPLAINED` and must be re-explained before
        it can be certified, and the dimension cycles `EXPLAINED → OPEN_EDITS → EXPLAINED` once per
        negotiation round."

        Design: Difficulty/non_linear_state_machine/component_prep_status_and_edit_status_advance_as_independent_dimensions
        """
        scenario = self._prepared_with_one_warning(api)
        check = scenario.checks[0]
        assert_edit_check(
            check,
            check_code=K.PY_VAR_PREFIX + K.METRIC_TOTAL_HEADCOUNT,
            severity=K.SEVERITY_WARNING,
            status=K.CHECK_OPEN,
            variance_pct=10.0,
            explanation_round=0,
        )
        postures = []

        def observe():
            row = validate_success(api.get_survey_component(scenario.component_id, analyst))
            postures.append(row["prep_status"])
            return row

        opened = observe()
        assert_component_status(
            opened,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_OPEN_EDITS,
            fatal_open_count=0,
        )
        assert opened["prepared_by_user_id"] == "analyst-1"

        first = validate_success(
            api.explain_edit_check(
                check["id"],
                f.make_explanation_payload(NURSING_EXPLANATION, NURSING_PRIOR_NOTE),
                analyst,
            )
        )
        assert_edit_check(first, status=K.CHECK_EXPLAINED, explanation_round=1)
        explained = observe()
        assert_component_status(
            explained, prep_status=K.PREP_PREPARED, edit_status=K.EDIT_EXPLAINED
        )
        assert_version_bumped(explained, opened, "component")

        rejected = validate_success(
            api.adjudicate_edit_check(
                check["id"],
                f.make_adjudication_payload(K.DECISION_REJECT, NURSING_REJECTION),
                director,
            )
        )
        assert_edit_check(rejected, status=K.CHECK_REJECTED, explanation_round=1)
        assert rejected["adjudicated_by_user_id"] == "director-1"
        rewound = observe()
        assert_component_status(
            rewound,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_OPEN_EDITS,
            fatal_open_count=0,
        )
        assert rewound["prepared_by_user_id"] == "analyst-1"
        assert_version_bumped(rewound, explained, "component")

        second = validate_success(
            api.explain_edit_check(
                check["id"],
                f.make_explanation_payload(NURSING_REVISION, NURSING_REVISION_NOTE),
                analyst,
            )
        )
        assert_edit_check(second, status=K.CHECK_EXPLAINED, explanation_round=2)
        assert second["explanation_text"] == NURSING_REVISION
        reexplained = observe()
        assert_component_status(
            reexplained, prep_status=K.PREP_PREPARED, edit_status=K.EDIT_EXPLAINED
        )

        finished = validate_success(
            api.adjudicate_edit_check(
                check["id"],
                f.make_adjudication_payload(
                    K.DECISION_ACCEPT, "Revised explanation reconciles; accepted."
                ),
                director,
            )
        )
        assert_edit_check(
            finished, status=K.CHECK_ACCEPTED, severity=K.SEVERITY_WARNING, explanation_round=2
        )
        cleared = observe()
        assert_component_status(
            cleared,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_CLEARED,
            fatal_open_count=0,
        )
        assert set(postures) == {K.PREP_PREPARED}

    def test_the_prep_dimension_advances_alone_once_the_edit_dimension_has_cleared(
        self, api, analyst, director
    ):
        """Certifying moves prep_status only and leaves the negotiated check exactly as it stood.

        PRD 3.5: "On success the component moves to `CERTIFIED`, `certified_by_user_id` records the
        director, the statement is stored verbatim, and `version` is incremented."

        Design: Difficulty/non_linear_state_machine/component_prep_status_and_edit_status_advance_as_independent_dimensions
        """
        scenario = self._prepared_with_one_warning(api)
        check = scenario.checks[0]
        accepted = self._negotiate_to_accepted(api, check["id"], analyst, director)
        assert_edit_check(accepted, status=K.CHECK_ACCEPTED, explanation_round=2)

        before = validate_success(api.get_survey_component(scenario.component_id, analyst))
        assert_component_status(
            before, prep_status=K.PREP_PREPARED, edit_status=K.EDIT_CLEARED, fatal_open_count=0
        )

        certified = validate_success(
            api.certify_component(
                scenario.component_id,
                f.make_certification_payload(CERTIFICATION_STATEMENT),
                director,
            )
        )
        assert_component_status(
            certified,
            prep_status=K.PREP_CERTIFIED,
            edit_status=K.EDIT_CLEARED,
            fatal_open_count=0,
        )
        assert certified["certified_by_user_id"] == "director-1"
        assert certified["certification_statement"] == CERTIFICATION_STATEMENT
        assert certified["prepared_by_user_id"] == "analyst-1"
        assert_version_bumped(certified, before, "component")

        untouched = validate_success(api.get_edit_check(check["id"], analyst))
        assert_edit_check(
            untouched,
            status=K.CHECK_ACCEPTED,
            severity=K.SEVERITY_WARNING,
            explanation_round=2,
            variance_pct=10.0,
        )
        assert untouched["explanation_text"] == NURSING_REVISION
