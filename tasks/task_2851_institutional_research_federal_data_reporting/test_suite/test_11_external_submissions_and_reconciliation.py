"""External recipients: the single-pass allowance arithmetic, the hold, the override and transmission."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_common_fields,
    assert_instant_equals,
    assert_null,
    assert_reconciliation,
    assert_reconciliation_fields_all_null,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
)

STATE_BOARD = "State Board of Higher Education"
CONSORTIUM_NAME = "Regional Higher-Ed Consortium"
DATA_EXCHANGE = "Regional Data Exchange Consortium"
RANKING_PUBLISHER = "National University Ranking"

ENROLLMENT_CERTIFICATION = (
    "I certify the enrollment component as reported to the federal collection."
)
COMPLETIONS_CERTIFICATION = (
    "I certify the completions component as reported to the federal collection."
)
RANKING_OVERRIDE = (
    "The ranking definition counts non-degree seekers that the federal definition excludes."
)

ENROLLMENT_METRICS = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 1000,
        "prior_year_value": 1000,
        "source_field_path": "sis.enrollment.headcount",
    },
)
ENROLLMENT_WITH_ZERO_FTE = ENROLLMENT_METRICS + (
    {
        "metric_key": K.METRIC_FTE_ENROLLMENT,
        "reported_value": 0,
        "prior_year_value": 0,
        "source_field_path": "sis.enrollment.fte",
    },
)
COMPLETIONS_METRICS = (
    {
        "metric_key": K.METRIC_TOTAL_COMPLETIONS,
        "reported_value": 500,
        "prior_year_value": 500,
        "source_field_path": "sis.completions.total",
    },
)


def _two_domain_locked_cycle(
    api, registrar, analyst, enrollment_metrics, completions_metrics, checksums
):
    """A CENSUS_LOCKED cycle carrying one DRAFT ENROLLMENT and one DRAFT COMPLETIONS component."""
    cycle = fx.create_cycle(api, registrar)
    extracts = {
        K.DOMAIN_ENROLLMENT: fx.register_extract(
            api,
            cycle["id"],
            cycle["version"],
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1000,
            checksum=checksums[0],
        ),
        K.DOMAIN_COMPLETIONS: fx.register_extract(
            api,
            cycle["id"],
            None,
            registrar,
            domain=K.DOMAIN_COMPLETIONS,
            record_count=500,
            checksum=checksums[1],
        ),
    }
    fx.move_clock(api, K.CLOCK_AFTER_CENSUS, registrar)
    validate_success(api.census_lock_cycle(cycle["id"], registrar))

    components = {}
    for domain, metrics in (
        (K.DOMAIN_ENROLLMENT, enrollment_metrics),
        (K.DOMAIN_COMPLETIONS, completions_metrics),
    ):
        component = validate_success(
            api.create_survey_component(
                f.make_survey_component_payload(
                    cycle["id"], extracts[domain]["id"], component_code=domain
                ),
                analyst,
            ),
            201,
        )
        fx.add_metrics(api, component["id"], metrics)
        components[domain] = component
    return cycle, components


def _certify(api, component_id, statement, analyst, director):
    """Prepare as the analyst then certify as the director, returning the certified row."""
    validate_success(api.prepare_component(component_id, analyst))
    return validate_success(
        api.certify_component(component_id, f.make_certification_payload(statement), director)
    )


class TestAllowanceTierComesFromTheUnadjustedGap:
    """The tier is derived once from raw_delta_pct, and the verdict proves it was not re-derived."""

    def test_a_consortium_gap_of_one_point_four_reconciles_in_a_single_pass(
        self, api, analyst
    ):
        """Re-tiering the reduced 0.90 would have produced a hold instead of a reconciliation.

        PRD 3.8: "A raw delta of 1.40 earns an allowance of 0.50 and an effective delta of 0.90 in
        a single pass; feeding 0.90 back into the tier table would put it in the lowest band,
        produce an allowance of 0.00, and yield an effective delta of 1.40 instead — a different
        number, and for a `CONSORTIUM` recipient a different verdict."

        PRD 3.8: "The row starts at `status` `DRAFT` with all five reconciliation fields —
        `federal_value`, `raw_delta_pct`, `allowance_pct`, `effective_delta_pct` and
        `tolerance_pct` — null, `override_reason`, `overridden_by_user_id`,
        `transmission_reference` and `transmitted_at` null, and `version` 1."

        Design: Difficulty/combinatorial_formula/submission_reconciliation_allowance_tier_derives_from_raw_delta_only
        """
        scenario = fx.certified_component(
            api, metrics=ENROLLMENT_METRICS, checksum="a1b2c3d4e5f60004"
        )
        submission = fx.draft_submission(
            api,
            scenario,
            target_type=K.TARGET_CONSORTIUM,
            target_name=CONSORTIUM_NAME,
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            reported_value=1014,
        )
        assert submission["status"] == K.SUBMISSION_DRAFT
        assert_reconciliation_fields_all_null(submission)
        assert_null(submission["override_reason"], "submission.override_reason")
        assert_null(submission["overridden_by_user_id"], "submission.overridden_by_user_id")
        assert_null(submission["transmission_reference"], "submission.transmission_reference")
        assert_null(submission["transmitted_at"], "submission.transmitted_at")
        assert_version(submission, 1, "submission")
        assert_common_fields(submission, "submission")

        reconciled = validate_success(api.reconcile_submission(submission["id"], analyst))
        assert_reconciliation(
            reconciled,
            federal_value=1000,
            raw_delta_pct=1.40,
            allowance_pct=K.ALLOWANCE_TIER_MID,
            effective_delta_pct=0.90,
            tolerance_pct=K.TOLERANCE_BY_TARGET_TYPE[K.TARGET_CONSORTIUM],
            status=K.SUBMISSION_RECONCILED,
        )
        assert reconciled["status"] != K.SUBMISSION_VARIANCE_HOLD
        assert_version(reconciled, 2, "submission")

    def test_the_strict_tier_bound_reconciles_a_wider_gap_than_the_one_it_holds(
        self, api, analyst
    ):
        """A gap of exactly 1.00 clears the state tolerance while a smaller 0.90 gap is held.

        PRD 3.8: "The tier bounds are strict, so a raw delta of exactly 1.00 falls into the middle
        band and a raw delta of exactly 5.00 falls into the top band."

        PRD 3.8: "The verdict is taken by comparing the reduced gap against the tolerance, and the
        comparison is inclusive: when `effective_delta_pct` is less than or equal to
        `tolerance_pct` the submission is reconciled, and otherwise it is held."

        Design: Difficulty/combinatorial_formula/submission_reconciliation_allowance_tier_derives_from_raw_delta_only
        """
        scenario = fx.certified_component(
            api, metrics=ENROLLMENT_METRICS, checksum="a1b2c3d4e5f60005"
        )
        on_the_bound = fx.draft_submission(
            api,
            scenario,
            target_type=K.TARGET_STATE,
            target_name=STATE_BOARD,
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            reported_value=1010,
        )
        below_the_bound = fx.draft_submission(
            api,
            scenario,
            target_type=K.TARGET_STATE,
            target_name="State Council on Postsecondary Education",
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            reported_value=1009,
        )

        wider = validate_success(api.reconcile_submission(on_the_bound["id"], analyst))
        assert_reconciliation(
            wider,
            federal_value=1000,
            raw_delta_pct=K.ALLOWANCE_TIER_LOW_BOUND,
            allowance_pct=K.ALLOWANCE_TIER_MID,
            effective_delta_pct=0.50,
            tolerance_pct=K.TOLERANCE_BY_TARGET_TYPE[K.TARGET_STATE],
            status=K.SUBMISSION_RECONCILED,
        )

        narrower = validate_success(api.reconcile_submission(below_the_bound["id"], analyst))
        assert_reconciliation(
            narrower,
            federal_value=1000,
            raw_delta_pct=0.90,
            allowance_pct=K.ALLOWANCE_TIER_LOW,
            effective_delta_pct=0.90,
            tolerance_pct=K.TOLERANCE_BY_TARGET_TYPE[K.TARGET_STATE],
            status=K.SUBMISSION_VARIANCE_HOLD,
        )
        assert narrower["raw_delta_pct"] < wider["raw_delta_pct"]

        rows, meta = validate_paginated(
            api.list_external_submissions(
                analyst, cycle_id=scenario.cycle_id, status=K.SUBMISSION_RECONCILED
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["target_name"] == STATE_BOARD


class TestReconciliationWaitsForACertifiedSource:
    """The gate is the sibling component's prep_status, not the submission's own state."""

    def test_the_same_reconcile_is_refused_on_a_prepared_source_and_passes_once_certified(
        self, api, analyst, director
    ):
        """Nothing about the submission changes between the refusal and the success.

        PRD 3.8: "Both require the submission to be `DRAFT`, reporting
        `ERR_INVALID_SUBMISSION_STATE` otherwise, and both require the referenced component's
        `prep_status` to be `CERTIFIED` or `SUBMITTED`, because an uncertified component has no
        authoritative federal value to compare against, reporting `ERR_SOURCE_NOT_CERTIFIED`."

        PRD 3.8: "The federal figure is read: `federal_value` is the `reported_value` of the
        component metric on the referenced component whose `metric_key` equals the submission's
        `metric_key`."

        Design: Difficulty/cross_entity_state_dependency/reconcile_blocked_until_source_component_reaches_certified
        """
        scenario = fx.prepared_component(
            api, metrics=ENROLLMENT_METRICS, checksum="a1b2c3d4e5f60016"
        )
        assert scenario.component["prep_status"] == K.PREP_PREPARED
        assert scenario.component["edit_status"] == K.EDIT_CLEARED

        submission = fx.draft_submission(
            api,
            scenario,
            target_type=K.TARGET_STATE,
            target_name=STATE_BOARD,
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            reported_value=1005,
        )
        refused = api.reconcile_submission(submission["id"], analyst)
        validate_error(refused, ApiErrorId.SOURCE_NOT_CERTIFIED, 409)

        untouched = validate_success(api.get_external_submission(submission["id"], analyst))
        assert untouched["status"] == K.SUBMISSION_DRAFT
        assert_reconciliation_fields_all_null(untouched)
        assert_version(untouched, 1, "submission")

        certified = validate_success(
            api.certify_component(
                scenario.component_id,
                f.make_certification_payload(ENROLLMENT_CERTIFICATION),
                director,
            )
        )
        assert certified["prep_status"] == K.PREP_CERTIFIED

        reconciled = validate_success(api.reconcile_submission(submission["id"], analyst))
        assert_reconciliation(
            reconciled,
            federal_value=1000,
            raw_delta_pct=0.50,
            allowance_pct=K.ALLOWANCE_TIER_LOW,
            effective_delta_pct=0.50,
            tolerance_pct=K.TOLERANCE_BY_TARGET_TYPE[K.TARGET_STATE],
            status=K.SUBMISSION_RECONCILED,
        )
        assert_version(reconciled, 2, "submission")

    def test_a_draft_source_is_refused_while_a_federally_submitted_source_passes(
        self, api, registrar, analyst, director
    ):
        """A source already sent to the federal collection is as authoritative as a certified one.

        PRD 3.8: "Both require the submission to be `DRAFT`, reporting
        `ERR_INVALID_SUBMISSION_STATE` otherwise, and both require the referenced component's
        `prep_status` to be `CERTIFIED` or `SUBMITTED`, because an uncertified component has no
        authoritative federal value to compare against, reporting `ERR_SOURCE_NOT_CERTIFIED`."

        PRD 3.5: "On success `prep_status` becomes `SUBMITTED`, `submitted_at` is stamped from the
        logical clock, and `version` is incremented."

        Design: Difficulty/cross_entity_state_dependency/reconcile_blocked_until_source_component_reaches_certified
        """
        cycle, components = _two_domain_locked_cycle(
            api,
            registrar,
            analyst,
            ENROLLMENT_METRICS,
            COMPLETIONS_METRICS,
            ("a1b2c3d4e5f60017", "a1b2c3d4e5f60018"),
        )
        enrollment = components[K.DOMAIN_ENROLLMENT]
        assert enrollment["prep_status"] == K.PREP_DRAFT

        submission = validate_success(
            api.create_external_submission(
                f.make_external_submission_payload(
                    cycle["id"],
                    enrollment["id"],
                    target_type=K.TARGET_STATE,
                    target_name=STATE_BOARD,
                    metric_key=K.METRIC_TOTAL_HEADCOUNT,
                    reported_value=1005,
                ),
                analyst,
            ),
            201,
        )
        validate_error(
            api.reconcile_submission(submission["id"], analyst),
            ApiErrorId.SOURCE_NOT_CERTIFIED,
            409,
        )

        _certify(api, enrollment["id"], ENROLLMENT_CERTIFICATION, analyst, director)
        _certify(
            api,
            components[K.DOMAIN_COMPLETIONS]["id"],
            COMPLETIONS_CERTIFICATION,
            analyst,
            director,
        )
        frozen = validate_success(api.freeze_cycle(cycle["id"], director))
        assert frozen["snapshot_posture"] == K.POSTURE_FROZEN

        sent = validate_success(api.submit_component(enrollment["id"], director))
        assert sent["prep_status"] == K.PREP_SUBMITTED
        assert_instant_equals(
            sent["submitted_at"], K.CLOCK_AFTER_CENSUS_ECHO, "component.submitted_at"
        )

        reconciled = validate_success(api.reconcile_submission(submission["id"], analyst))
        assert_reconciliation(
            reconciled,
            federal_value=1000,
            raw_delta_pct=0.50,
            allowance_pct=K.ALLOWANCE_TIER_LOW,
            effective_delta_pct=0.50,
            tolerance_pct=K.TOLERANCE_BY_TARGET_TYPE[K.TARGET_STATE],
            status=K.SUBMISSION_RECONCILED,
        )

        still_frozen = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert still_frozen["snapshot_posture"] == K.POSTURE_FROZEN


class TestRankingHoldSurvivesTheDirectorsOverride:
    """A raw gap of exactly 5.00 earns the top allowance and still misses the ranking tolerance."""

    def test_a_held_ranking_figure_is_overridden_without_recomputation_and_then_transmitted(
        self, api, analyst, director
    ):
        """The override moves the status and nothing else, so the audit trail keeps the 4.00 gap.

        PRD 3.8: "The tier bounds are strict, so a raw delta of exactly 1.00 falls into the middle
        band and a raw delta of exactly 5.00 falls into the top band."

        PRD 3.8: "The override stores the reason, records `overridden_by_user_id`, and increments
        `version`, and it deliberately **does not recompute** the five reconciliation fields: the
        variance that was measured is preserved exactly as recorded, so the audit trail shows both
        that the figure was out of tolerance and that a named director accepted it anyway."

        PRD 3.8: "On success `status` becomes `TRANSMITTED`, the reference is stored,
        `transmitted_at` is stamped from the logical clock, and `version` is incremented."

        Design: Corner/calculations/corner_calc_reconciliation_constants_hold_a_ranking_submission_at_raw_five_percent
        """
        scenario = fx.certified_component(
            api, metrics=ENROLLMENT_METRICS, checksum="c1d2e3f4a5b60133"
        )
        submission = fx.draft_submission(
            api,
            scenario,
            target_type=K.TARGET_RANKING,
            target_name=RANKING_PUBLISHER,
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            reported_value=1050,
        )

        held = validate_success(api.reconcile_submission(submission["id"], analyst))
        assert_reconciliation(
            held,
            federal_value=1000,
            raw_delta_pct=K.ALLOWANCE_TIER_HIGH_BOUND,
            allowance_pct=K.ALLOWANCE_TIER_HIGH,
            effective_delta_pct=4.00,
            tolerance_pct=K.TOLERANCE_BY_TARGET_TYPE[K.TARGET_RANKING],
            status=K.SUBMISSION_VARIANCE_HOLD,
        )
        assert_version(held, 2, "submission")
        assert_null(held["override_reason"], "submission.override_reason")

        overridden = validate_success(
            api.override_submission_variance(
                submission["id"], f.make_variance_override_payload(RANKING_OVERRIDE), director
            )
        )
        assert_reconciliation(
            overridden,
            federal_value=1000,
            raw_delta_pct=K.ALLOWANCE_TIER_HIGH_BOUND,
            allowance_pct=K.ALLOWANCE_TIER_HIGH,
            effective_delta_pct=4.00,
            tolerance_pct=K.TOLERANCE_BY_TARGET_TYPE[K.TARGET_RANKING],
            status=K.SUBMISSION_RECONCILED,
        )
        assert overridden["override_reason"] == RANKING_OVERRIDE
        assert overridden["overridden_by_user_id"] == "director-1"
        assert_version(overridden, 3, "submission")

        frozen = validate_success(api.freeze_cycle(scenario.cycle_id, director))
        assert frozen["snapshot_posture"] == K.POSTURE_FROZEN

        transmitted = validate_success(
            api.transmit_submission(
                submission["id"], f.make_transmission_payload("RNK-2027-0001"), director
            )
        )
        assert transmitted["status"] == K.SUBMISSION_TRANSMITTED
        assert transmitted["transmission_reference"] == "RNK-2027-0001"
        assert_instant_equals(
            transmitted["transmitted_at"],
            K.CLOCK_AFTER_CENSUS_ECHO,
            "submission.transmitted_at",
        )
        assert_reconciliation(transmitted, effective_delta_pct=4.00)
        assert_version(transmitted, 4, "submission")


class TestStepOneNeedsAUsableFederalFigure:
    """An absent metric row and a zero-valued one fail the same step with different identifiers."""

    def test_a_missing_counterpart_and_a_zero_base_counterpart_report_distinct_refusals(
        self, api, registrar, analyst, director
    ):
        """Both submissions stay DRAFT with all five reconciliation fields still null.

        PRD 3.8: "Both require the matching component metric to exist on that component, reporting
        `ERR_FEDERAL_VALUE_UNAVAILABLE` when it does not. And the arithmetic requires a non-zero
        denominator: when the matching metric's `reported_value` is exactly 0, the percentage gap
        is undefined and the reconciliation is refused with `ERR_ZERO_BASE_RECONCILIATION` rather
        than producing a null or an infinity."

        PRD 3.3: "When `prior_year_value` is exactly 0, `variance_pct` is also null, because a
        percentage change from a zero base is undefined; this zero-base case is not ignored, it is
        escalated separately below."

        Design: Corner/validations/corner_val_reconciliation_needs_a_federal_counterpart_with_a_non_zero_base
        """
        cycle, components = _two_domain_locked_cycle(
            api,
            registrar,
            analyst,
            ENROLLMENT_WITH_ZERO_FTE,
            COMPLETIONS_METRICS,
            ("c1d2e3f4a5b60149", "c1d2e3f4a5b60150"),
        )
        enrollment = _certify(
            api, components[K.DOMAIN_ENROLLMENT]["id"], ENROLLMENT_CERTIFICATION, analyst, director
        )
        completions = _certify(
            api,
            components[K.DOMAIN_COMPLETIONS]["id"],
            COMPLETIONS_CERTIFICATION,
            analyst,
            director,
        )

        zero_base = validate_success(
            api.create_external_submission(
                f.make_external_submission_payload(
                    cycle["id"],
                    enrollment["id"],
                    target_type=K.TARGET_STATE,
                    target_name=STATE_BOARD,
                    metric_key=K.METRIC_FTE_ENROLLMENT,
                    reported_value=500,
                ),
                analyst,
            ),
            201,
        )
        no_counterpart = validate_success(
            api.create_external_submission(
                f.make_external_submission_payload(
                    cycle["id"],
                    completions["id"],
                    target_type=K.TARGET_CONSORTIUM,
                    target_name=DATA_EXCHANGE,
                    metric_key=K.METRIC_CIP_PROGRAM_COUNT,
                    reported_value=40,
                ),
                analyst,
            ),
            201,
        )

        missing = api.reconcile_submission(no_counterpart["id"], analyst)
        validate_error(missing, ApiErrorId.FEDERAL_VALUE_UNAVAILABLE, 422)
        still_draft = validate_success(api.get_external_submission(no_counterpart["id"], analyst))
        assert still_draft["status"] == K.SUBMISSION_DRAFT
        assert_reconciliation_fields_all_null(still_draft)
        assert_version(still_draft, 1, "submission")

        divide_by_zero = api.reconcile_submission(zero_base["id"], analyst)
        validate_error(divide_by_zero, ApiErrorId.ZERO_BASE_RECONCILIATION, 422)
        held = validate_success(api.get_external_submission(zero_base["id"], analyst))
        assert held["status"] == K.SUBMISSION_DRAFT
        assert_reconciliation_fields_all_null(held)

        fte = validate_success(
            api.list_component_metrics(
                analyst, component_id=enrollment["id"], metric_key=K.METRIC_FTE_ENROLLMENT
            )
        )
        assert fte[0]["reported_value"] == 0
        assert_null(fte[0]["variance_pct"], "metric.variance_pct")

        rows, meta = validate_paginated(
            api.list_external_submissions(
                analyst, cycle_id=cycle["id"], status=K.SUBMISSION_DRAFT
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


class TestTransmissionHasTwoIndependentGates:
    """One action, two guards: the submission's own status and the cycle's posture."""

    def test_a_draft_submission_and_an_unfrozen_cycle_block_transmission_with_different_ids(
        self, api, registrar, analyst, director
    ):
        """The same director call fails twice for different reasons before it finally lands.

        PRD 3.8: "It is the director's act, requires the submission to be `RECONCILED` (else
        `ERR_INVALID_SUBMISSION_STATE`), requires the cycle's `snapshot_posture` to be `FROZEN` or
        `ARCHIVED` (else `ERR_CYCLE_NOT_FROZEN`), requires the logical clock to be at or before the
        cycle's `collection_deadline` with equality passing (else
        `ERR_COLLECTION_DEADLINE_PASSED`), and requires a `transmission_reference` of 3 to 64
        characters identifying the recipient's acknowledgement."

        PRD 3.8: "On success `status` becomes `TRANSMITTED`, the reference is stored,
        `transmitted_at` is stamped from the logical clock, and `version` is incremented."

        PRD 2.12: "because posture gating (priorities 6 through 9) precedes the target row's own
        state check (priority 11), a request that is wrong in both ways reports the *cycle*
        problem."

        Design: Corner/endpoints/corner_ep_transmit_is_gated_on_both_the_submission_and_the_cycle
        """
        scenario = fx.certified_component(
            api, metrics=ENROLLMENT_METRICS, checksum="c1d2e3f4a5b60157"
        )
        submission = fx.draft_submission(
            api,
            scenario,
            target_type=K.TARGET_STATE,
            target_name=STATE_BOARD,
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            reported_value=1002,
        )
        reference = f.make_transmission_payload("STATE-2027-0001")

        # Wrong in both ways — DRAFT submission beneath a CENSUS_LOCKED cycle — so the
        # posture gate at priority 8 answers before the row's own state check at priority 11.
        too_early = api.transmit_submission(submission["id"], reference, director)
        validate_error(too_early, ApiErrorId.CYCLE_NOT_FROZEN, 409)

        reconciled = validate_success(api.reconcile_submission(submission["id"], analyst))
        assert_reconciliation(
            reconciled,
            federal_value=1000,
            raw_delta_pct=0.20,
            allowance_pct=K.ALLOWANCE_TIER_LOW,
            effective_delta_pct=0.20,
            tolerance_pct=K.TOLERANCE_BY_TARGET_TYPE[K.TARGET_STATE],
            status=K.SUBMISSION_RECONCILED,
        )

        unfrozen = api.transmit_submission(submission["id"], reference, director)
        validate_error(unfrozen, ApiErrorId.CYCLE_NOT_FROZEN, 409)
        waiting = validate_success(api.get_external_submission(submission["id"], analyst))
        assert waiting["status"] == K.SUBMISSION_RECONCILED
        assert_null(waiting["transmitted_at"], "submission.transmitted_at")
        assert_null(waiting["transmission_reference"], "submission.transmission_reference")
        assert_version(waiting, 2, "submission")

        locked_cycle = validate_success(api.get_reporting_cycle(scenario.cycle_id, registrar))
        assert locked_cycle["snapshot_posture"] == K.POSTURE_CENSUS_LOCKED

        frozen = validate_success(api.freeze_cycle(scenario.cycle_id, director))
        assert frozen["snapshot_posture"] == K.POSTURE_FROZEN

        # With the posture gate satisfied, the submission's own state gate answers alone.
        never_reconciled = fx.draft_submission(
            api,
            scenario,
            target_type=K.TARGET_STATE,
            target_name=STATE_BOARD,
            metric_key=K.METRIC_FTE_ENROLLMENT,
            reported_value=940,
        )
        still_draft = api.transmit_submission(never_reconciled["id"], reference, director)
        validate_error(still_draft, ApiErrorId.INVALID_SUBMISSION_STATE, 409)

        transmitted = validate_success(
            api.transmit_submission(submission["id"], reference, director)
        )
        assert transmitted["status"] == K.SUBMISSION_TRANSMITTED
        assert transmitted["transmission_reference"] == "STATE-2027-0001"
        assert_instant_equals(
            transmitted["transmitted_at"],
            K.CLOCK_AFTER_CENSUS_ECHO,
            "submission.transmitted_at",
        )
        assert_version(transmitted, 3, "submission")
