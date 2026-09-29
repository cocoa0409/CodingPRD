"""The cycle's loop back through REOPENED, the withdrawal void, and cascades read immediately."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_cohort_counts,
    assert_common_fields,
    assert_component_status,
    assert_cycle_ledger,
    assert_cycle_posture,
    assert_divergence_is_difference_of_published_variants,
    assert_edit_check,
    assert_equals_number,
    assert_instant_equals,
    assert_null,
    assert_publication_ledger,
    assert_rate_variants,
    assert_restatement,
    assert_version,
    assert_version_bumped,
    constants as K,
    factories as f,
    fixtures as fx,
)

HEADCOUNT_GROWTH = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 1100,
        "prior_year_value": 1000,
        "source_field_path": "sis.enrollment.total_headcount",
    },
)
STEADY_HEADCOUNT = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 1000,
        "prior_year_value": 1000,
        "source_field_path": "sis.enrollment.headcount",
    },
)
COMPLETIONS_FLAT = (
    {
        "metric_key": K.METRIC_TOTAL_COMPLETIONS,
        "reported_value": 250,
        "prior_year_value": 250,
        "source_field_path": "sis.degrees.awarded_total",
    },
)
REOPEN_REASON = (
    "State auditors identified a late residency reclassification affecting the fall census."
)
SECOND_LAP_EXPLANATION = (
    "Second-lap explanation: the nursing cohort remains the sole driver of the headcount increase."
)
SECOND_LAP_NOTE = "Prior year 1000, current year 1100 after the residency reclassification."
SECOND_LAP_ACCEPTANCE = "Re-explained after reopen; accepted."
SECOND_LAP_STATEMENT = "I re-certify the fall enrollment component after the reopened review."
SECOND_LAP_CLOCK = "2026-11-15T00:00:00Z"
SECOND_LAP_CLOCK_ECHO = "2026-11-15T00:00:00.000Z"
FIRST_CORRECTION = (
    "First correction: twenty-five late-conferred degrees were omitted from the extract."
)
REVISED_CORRECTION = (
    "Revised correction: only ten of the late-conferred degrees fall inside the census window."
)
POST_WITHDRAWAL_ATTEMPT = (
    "Attempting to restate a publication that has already been withdrawn from the dashboard."
)
WITHDRAWAL_REASON = (
    "The completions figure is withdrawn from the dashboard pending a full re-extract."
)


class TestThePostureLoopsBackThroughReopened:
    """The cycle re-enters CENSUS_LOCKED and FROZEN a second time, and the lap is countable."""

    @staticmethod
    def _first_lap(api, checksum):
        """A FROZEN cycle whose single component was certified over one accepted WARNING check."""
        scenario = fx.frozen_cycle(
            api, metrics=HEADCOUNT_GROWTH, record_count=1000, checksum=checksum
        )
        first_lap_checks = fx.list_checks(api, scenario.component_id)
        assert len(first_lap_checks) == 1
        assert_edit_check(
            first_lap_checks[0],
            check_code="PY_VAR_TOTAL_HEADCOUNT",
            severity=K.SEVERITY_WARNING,
            status=K.CHECK_ACCEPTED,
            sequence_no=1,
            variance_pct=10.0,
        )
        return scenario, first_lap_checks[0]

    @staticmethod
    def _second_lap_extract(api, cycle_id, registrar, checksum):
        """A fresh extract over the post-census window, registrable only because of the reopen."""
        return fx.register_extract(
            api,
            cycle_id,
            None,
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1100,
            coverage_start_date=K.COVERAGE_START_SECOND,
            coverage_end_date=K.COVERAGE_END_SECOND,
            checksum=checksum,
        )

    def test_the_second_lap_ends_frozen_again_with_one_reopen_and_two_locked_extracts(
        self, api, registrar, analyst, director
    ):
        """The first lap's check survives as VOIDED history beside the second lap's own check.

        PRD 3.5: "Level one sets `snapshot_posture` to `REOPENED`, increments `reopen_count`,
        stores the reason in `reopen_reason` and increments the cycle's `version`."

        PRD 3.5: "Throughout the reopen, every census extract of the cycle keeps its `status` of
        `LOCKED` — none is superseded automatically — but a fresh extract carrying an identical
        `domain` and coverage window may now be registered to supersede one, which is exactly how
        the loop `FROZEN → REOPENED → CENSUS_LOCKED → FROZEN` is closed."

        PRD 3.5: "This closes the preparation loop `DRAFT → PREPARED → DRAFT`, so a corrected
        metric can be re-prepared and freshly re-flagged; each lap raises a brand-new set of checks
        whose `sequence_no` again starts at 1, while the previous lap's checks remain visible as
        `VOIDED` history."

        Design: Difficulty/non_linear_state_machine/cycle_posture_loops_frozen_reopened_census_locked_frozen_again
        """
        scenario, first_check = self._first_lap(api, "a1b2c3d4e5f60005")
        cycle_id = scenario.cycle_id
        component_id = scenario.component_id

        reopened = validate_success(
            api.reopen_cycle(cycle_id, f.make_reopen_payload(REOPEN_REASON), director)
        )
        assert_cycle_posture(reopened, K.POSTURE_REOPENED)
        assert_cycle_ledger(reopened, reopen_count=1)

        second_extract = self._second_lap_extract(
            api, cycle_id, registrar, "a1b2c3d4e5f60006"
        )
        assert second_extract["status"] == K.FROZEN_FILE_ACTIVE
        assert_null(
            second_extract["supersedes_frozen_file_id"], "extract.supersedes_frozen_file_id"
        )

        relocked = validate_success(api.census_lock_cycle(cycle_id, registrar))
        assert_cycle_posture(relocked, K.POSTURE_CENSUS_LOCKED)
        assert_cycle_ledger(relocked, frozen_file_count=2, active_record_count=2100, reopen_count=1)

        reprepared = validate_success(api.prepare_component(component_id, analyst))
        assert_component_status(
            reprepared,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_OPEN_EDITS,
            fatal_open_count=0,
        )

        second_lap_open = validate_success(
            api.list_edit_checks(analyst, component_id=component_id, status=K.CHECK_OPEN)
        )
        assert len(second_lap_open) == 1
        second_check = second_lap_open[0]
        assert_edit_check(
            second_check,
            check_code="PY_VAR_TOTAL_HEADCOUNT",
            severity=K.SEVERITY_WARNING,
            sequence_no=1,
            variance_pct=10.0,
        )
        assert second_check["id"] != first_check["id"]

        validate_success(
            api.explain_edit_check(
                second_check["id"],
                f.make_explanation_payload(
                    explanation_text=SECOND_LAP_EXPLANATION,
                    prior_year_comparison_note=SECOND_LAP_NOTE,
                ),
                analyst,
            )
        )
        accepted = validate_success(
            api.adjudicate_edit_check(
                second_check["id"],
                f.make_adjudication_payload(adjudication_note=SECOND_LAP_ACCEPTANCE),
                director,
            )
        )
        assert_edit_check(accepted, status=K.CHECK_ACCEPTED)

        recertified = validate_success(
            api.certify_component(
                component_id, f.make_certification_payload(SECOND_LAP_STATEMENT), director
            )
        )
        assert_component_status(
            recertified, prep_status=K.PREP_CERTIFIED, edit_status=K.EDIT_CLEARED
        )

        refrozen = validate_success(api.freeze_cycle(cycle_id, director))
        assert_cycle_posture(refrozen, K.POSTURE_FROZEN)
        assert_cycle_ledger(refrozen, frozen_file_count=2, active_record_count=2100, reopen_count=1)

        for extract_id in (scenario.extract_id, second_extract["id"]):
            stored = validate_success(api.get_frozen_file(extract_id, registrar))
            assert stored["status"] == K.FROZEN_FILE_LOCKED

        voided = validate_success(api.get_edit_check(first_check["id"], analyst))
        assert_edit_check(voided, status=K.CHECK_VOIDED, sequence_no=1)

        rows, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=component_id)
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2

    def test_the_lap_must_pass_through_census_locked_again_before_it_can_freeze(
        self, api, registrar, director
    ):
        """A reopened cycle cannot shortcut straight back to FROZEN, however certified it once was.

        PRD 3.5: "The cycle must be `CENSUS_LOCKED`; firing it from `OPEN` or `REOPENED` reports
        `ERR_INVALID_CYCLE_STATE`."

        PRD 3.5: "Level two, caused by level one, reverts every survey component of the cycle whose
        `prep_status` is `CERTIFIED`: `prep_status` becomes `DRAFT`, `certified_by_user_id` and
        `certification_statement` are cleared, `edit_status` is forced to `NOT_RUN`, every edit
        check of that component at `OPEN`, `EXPLAINED`, `REJECTED`, `ACCEPTED` or `WAIVED` is
        voided, and the component's `version` is incremented, with components processed in
        `created_at` ascending order."

        PRD 2.6: "The snapshot is sealed at that point and stays sealed until the cycle is
        reopened, so extract registration requires a posture of `OPEN` or `REOPENED`; an attempt
        while `CENSUS_LOCKED` is refused with `ERR_CENSUS_LOCKED` (HTTP 409)."

        PRD 3.1: "The lock then sets `snapshot_posture` to `CENSUS_LOCKED`, writes
        `census_locked_at` from the logical clock, increments the cycle's `version`, walks the
        cycle's `ACTIVE` extracts in `created_at` ascending order flipping each one
        `ACTIVE → LOCKED` with its own `version` incremented, and recomputes `active_record_count`
        and `frozen_file_count` — the record total is unchanged in value, because locked extracts
        remain inside the sum."

        Design: Difficulty/non_linear_state_machine/cycle_posture_loops_frozen_reopened_census_locked_frozen_again
        """
        scenario, first_check = self._first_lap(api, "a1b2c3d4e5f60008")
        cycle_id = scenario.cycle_id

        reopened = validate_success(
            api.reopen_cycle(cycle_id, f.make_reopen_payload(REOPEN_REASON), director)
        )
        assert_cycle_posture(reopened, K.POSTURE_REOPENED)
        assert_cycle_ledger(reopened, reopen_count=1)
        assert reopened["reopen_reason"] == REOPEN_REASON

        reverted = validate_success(api.get_survey_component(scenario.component_id, registrar))
        assert_component_status(
            reverted,
            prep_status=K.PREP_DRAFT,
            edit_status=K.EDIT_NOT_RUN,
            fatal_open_count=0,
        )
        assert_null(reverted["certified_by_user_id"], "component.certified_by_user_id")
        assert_null(reverted["certification_statement"], "component.certification_statement")

        voided = validate_success(api.get_edit_check(first_check["id"], registrar))
        assert_edit_check(voided, status=K.CHECK_VOIDED)

        too_early = api.freeze_cycle(cycle_id, director)
        validate_error(too_early, ApiErrorId.INVALID_CYCLE_STATE, 409)

        held = validate_success(api.get_reporting_cycle(cycle_id, registrar))
        assert_cycle_posture(held, K.POSTURE_REOPENED)
        assert_cycle_ledger(held, frozen_file_count=1, active_record_count=1000, reopen_count=1)

        second_extract = self._second_lap_extract(
            api, cycle_id, registrar, "a1b2c3d4e5f60009"
        )
        assert second_extract["status"] == K.FROZEN_FILE_ACTIVE

        fx.move_clock(api, SECOND_LAP_CLOCK, registrar)
        relocked = validate_success(api.census_lock_cycle(cycle_id, registrar))
        assert_cycle_posture(relocked, K.POSTURE_CENSUS_LOCKED)
        assert_instant_equals(
            relocked["census_locked_at"], SECOND_LAP_CLOCK_ECHO, "cycle.census_locked_at"
        )
        assert_cycle_ledger(relocked, frozen_file_count=2, active_record_count=2100, reopen_count=1)
        assert_version_bumped(relocked, held, "cycle")

        stored = validate_success(api.get_frozen_file(second_extract["id"], registrar))
        assert stored["status"] == K.FROZEN_FILE_LOCKED


class TestWithdrawalVoidsWhatSupersessionLeftStanding:
    """Two terminal fates on one publication: SUPERSEDED by a rival, VOIDED by the withdrawal."""

    def test_the_older_request_is_superseded_and_only_the_live_one_is_voided(
        self, api, analyst, director
    ):
        """A withdrawn publication refuses new requests while its voided one refuses approval.

        PRD 3.7: "Filing also supersedes the competition: every *other* restatement request of the
        same publication still sitting at `SUBMITTED` moves to `SUPERSEDED`, so at most one request
        is ever live on a publication."

        PRD 3.7: "Three of the four states — `PUBLISHED`, `RESTATEMENT_PENDING` and `RESTATED` —
        accept **withdrawal** by an `IRDirector` — `PUBLISHED → WITHDRAWN`,
        `RESTATEMENT_PENDING → WITHDRAWN` and `RESTATED → WITHDRAWN` — which requires a
        `withdrawal_reason` of 10 to 500 characters, stores it, moves `publication_status` to
        `WITHDRAWN`, increments `version`, and voids every restatement request of that publication
        still sitting at `SUBMITTED`."

        PRD 3.7: "A `WITHDRAWN` publication never accepts a restatement and is never visited by a
        cascade, reporting `ERR_INVALID_PUBLICATION_STATE`."

        PRD 3.7: "It requires the request to be `SUBMITTED` (else `ERR_INVALID_RESTATEMENT_STATE`),
        its parent publication to be `RESTATEMENT_PENDING` (else `ERR_INVALID_PUBLICATION_STATE`),
        the acting `X-User-ID` to differ from `requested_by_user_id` (else
        `ERR_SEGREGATION_OF_DUTIES` — a request whose requester is the literal `SYSTEM` can never
        collide), and, when `public_notice_required` is true, a `public_notice_reference` of 3 to
        120 characters, absent which the approval reports `ERR_PUBLIC_NOTICE_REQUIRED`."

        Design: Corner/state_machines/corner_sm_withdrawal_voids_pending_requests_and_locks_the_publication
        """
        scenario = fx.published_figure(
            api,
            metric_key="COMPLETIONS_TOTAL_FALL",
            published_value=250.0,
            metrics=COMPLETIONS_FLAT,
            record_count=250,
            checksum="c1d2e3f4a5b60127",
            domain=K.DOMAIN_COMPLETIONS,
        )
        publication_id = scenario.publication_id

        first = fx.file_restatement(api, scenario, 275.0, justification=FIRST_CORRECTION)
        assert_restatement(first, status=K.RESTATEMENT_SUBMITTED, baseline_value=250.0)

        second = fx.file_restatement(api, scenario, 260.0, justification=REVISED_CORRECTION)
        assert_restatement(
            second,
            status=K.RESTATEMENT_SUBMITTED,
            origin=K.ORIGIN_ANALYST,
            baseline_value=250.0,
            proposed_value=260.0,
            delta_pct=4.00,
            public_notice_required=True,
        )
        superseded = validate_success(api.get_restatement(first["id"], analyst))
        assert_restatement(superseded, status=K.RESTATEMENT_SUPERSEDED)

        withdrawn = validate_success(
            api.withdraw_publication(
                publication_id, f.make_withdrawal_payload(WITHDRAWAL_REASON), director
            )
        )
        assert_publication_ledger(
            withdrawn,
            published_value=250.0,
            original_value=250.0,
            net_applied_delta=0.0,
            restatement_count=0,
            publication_status=K.PUBLICATION_WITHDRAWN,
        )
        assert withdrawn["withdrawal_reason"] == WITHDRAWAL_REASON

        voided = validate_success(api.get_restatement(second["id"], analyst))
        assert_restatement(voided, status=K.RESTATEMENT_VOIDED)
        still_superseded = validate_success(api.get_restatement(first["id"], analyst))
        assert_restatement(still_superseded, status=K.RESTATEMENT_SUPERSEDED)

        refused_filing = api.file_restatement(
            publication_id,
            f.make_restatement_payload(
                265.0, withdrawn["version"], justification=POST_WITHDRAWAL_ATTEMPT
            ),
            analyst,
        )
        validate_error(refused_filing, ApiErrorId.INVALID_PUBLICATION_STATE, 409)

        refused_approval = api.approve_restatement(
            second["id"], director, f.make_restatement_approval_payload("PN-2027-021")
        )
        validate_error(refused_approval, ApiErrorId.INVALID_RESTATEMENT_STATE, 409)

        rows, meta = validate_paginated(
            api.list_restatements(analyst, publication_id=publication_id)
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


class TestEveryDerivedFieldIsAlreadyCorrectWhenTheWriteAnswers:
    """Nothing is deferred: each write answers with its own recomputed ledger."""

    def test_the_counters_and_the_variance_are_never_null_then_backfilled(
        self, api, registrar, analyst
    ):
        """The edit check raised by preparation is listable the moment preparation answers.

        PRD 3.1: "A newly opened cycle begins at `snapshot_posture` `OPEN`, with `reopen_count` at
        0, `active_record_count` at 0, `frozen_file_count` at 0, `census_locked_at`, `frozen_at` and
        `reopen_reason` all null, and `version` 1."

        PRD 3.1: "Two derived ledgers on the cycle are rewritten every time an extract is registered
        and every time any extract's `status` changes."

        PRD 3.3: "The server records the owning `component_id` and starts the row with `restated`
        false, `restatement_note` and `variance_pct` null, and `version` 1."

        PRD 3.3: "A successful run writes the acting operator's identifier into
        `prepared_by_user_id`, sets `prep_status` to `PREPARED`, increments `version`, recomputes
        `mapping_coverage_pct`, recomputes `core_expense_per_fte_cents` for finance components
        (writing null for all others), recomputes every metric's `variance_pct`, raises the edit
        checks described next, re-derives `edit_status`, and recomputes `fatal_open_count`."

        PRD 3.3: "Otherwise, when the metric's `variance_pct` is not null and is at least 10.0, the
        same `PY_VAR_` check code is raised but with `severity` `WARNING`, again carrying the
        metric's `variance_pct`."

        Design: Corner/consistency_model/corner_consistency_every_computed_field_is_already_correct_in_the_mutating_response
        """
        cycle = validate_success(
            api.create_reporting_cycle(f.make_reporting_cycle_payload(), registrar), 201
        )
        assert_cycle_posture(cycle, K.POSTURE_OPEN)
        assert_cycle_ledger(cycle, frozen_file_count=0, active_record_count=0, reopen_count=0)
        assert_null(cycle["census_locked_at"], "cycle.census_locked_at")
        assert_null(cycle["frozen_at"], "cycle.frozen_at")
        assert_version(cycle, 1, "cycle")
        assert_common_fields(cycle, "cycle")

        extract = fx.register_extract(
            api,
            cycle["id"],
            cycle["version"],
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1125,
            checksum="c1d2e3f4a5b60172",
        )
        assert extract["status"] == K.FROZEN_FILE_ACTIVE
        assert_instant_equals(
            extract["snapshot_taken_at"], K.CLOCK_STARTUP_UTC_ECHO, "extract.snapshot_taken_at"
        )
        assert_version(extract, 1, "extract")

        counted = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_ledger(counted, frozen_file_count=1, active_record_count=1125)
        assert_version(counted, 2, "cycle")

        fx.move_clock(api, K.CLOCK_AFTER_CENSUS, registrar)
        locked = validate_success(api.census_lock_cycle(cycle["id"], registrar))
        assert_cycle_posture(locked, K.POSTURE_CENSUS_LOCKED)
        assert_instant_equals(
            locked["census_locked_at"], K.CLOCK_AFTER_CENSUS_ECHO, "cycle.census_locked_at"
        )
        assert_cycle_ledger(locked, frozen_file_count=1, active_record_count=1125)
        assert_version(locked, 3, "cycle")

        component = validate_success(
            api.create_survey_component(
                f.make_survey_component_payload(cycle["id"], extract["id"], K.DOMAIN_ENROLLMENT),
                analyst,
            ),
            201,
        )
        assert_component_status(
            component,
            prep_status=K.PREP_DRAFT,
            edit_status=K.EDIT_NOT_RUN,
            fatal_open_count=0,
        )
        assert_version(component, 1, "component")

        metric = validate_success(
            api.add_component_metric(
                component["id"],
                f.make_metric_payload(
                    metric_key=K.METRIC_TOTAL_HEADCOUNT,
                    reported_value=1125,
                    prior_year_value=1000,
                    source_field_path="sis.enrollment.headcount",
                ),
                analyst,
            ),
            201,
        )
        assert metric["restated"] is False
        assert_null(metric["variance_pct"], "metric.variance_pct")
        assert_version(metric, 1, "metric")

        before_prepare = validate_success(api.get_survey_component(component["id"], analyst))
        prepared = validate_success(api.prepare_component(component["id"], analyst))
        assert_component_status(
            prepared,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_OPEN_EDITS,
            fatal_open_count=0,
        )
        assert prepared["prepared_by_user_id"] == "analyst-1"
        assert_version_bumped(prepared, before_prepare, "component")

        computed = validate_success(api.get_component_metric(metric["id"], analyst))
        assert_equals_number(computed["variance_pct"], 12.5, "metric.variance_pct")

        rows, meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=component["id"])
        )
        assert meta["total_count"] == 1
        assert_edit_check(
            rows[0],
            check_code="PY_VAR_TOTAL_HEADCOUNT",
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            severity=K.SEVERITY_WARNING,
            status=K.CHECK_OPEN,
            sequence_no=1,
            variance_pct=12.5,
            observed_value=1125,
            prior_year_value=1000,
        )


class TestCascadedRowsAreReadableOnTheVeryNextGet:
    """The lock's extract flip and the freeze's cohort lock are both visible on the first read."""

    def test_the_cohort_is_already_locked_and_rated_when_the_freeze_answers(
        self, api, registrar, analyst, director
    ):
        """The census lock leaves the cohort alone; the freeze locks it and pins both variants.

        PRD 3.1: "The lock then sets `snapshot_posture` to `CENSUS_LOCKED`, writes
        `census_locked_at` from the logical clock, increments the cycle's `version`, walks the
        cycle's `ACTIVE` extracts in `created_at` ascending order flipping each one
        `ACTIVE → LOCKED` with its own `version` incremented, and recomputes `active_record_count`
        and `frozen_file_count` — the record total is unchanged in value, because locked extracts
        remain inside the sum."

        PRD 3.5: "The freeze also carries one cascade into the cohort world: every cohort definition
        of the cycle whose `status` is `DRAFT` **and** whose `adjusted_count` is at least 1 is
        locked — `status` becomes `LOCKED`, `locked_at` is stamped, both rate variants are
        recomputed, and `version` is incremented — processed in `created_at` ascending order."

        PRD 3.6: "It is computed from **the two already-rounded variants**, not re-derived from the
        underlying counts, so it is exactly the difference of the two published figures."

        PRD 3.3: "Otherwise nothing is raised for that metric."

        Design: Corner/consistency_model/corner_consistency_cross_entity_cascades_are_visible_on_the_very_next_read
        """
        scenario = fx.open_cycle_with_extract(
            api, record_count=1000, checksum="c1d2e3f4a5b60173"
        )
        scenario = fx.cohort_on_scenario(
            api,
            scenario,
            fx.roster_of(K.OUTCOME_COMPLETED_150, K.OUTCOME_NO_LONGER_ENROLLED),
            cohort_type=K.COHORT_GRAD_RATE_150,
            entry_term="FALL2020",
            publication_metric_key="GRAD_RATE_150_FALL2020",
        )
        cohort_id = scenario.cohort_id

        fx.move_clock(api, K.CLOCK_AFTER_CENSUS, registrar)
        locked_cycle = validate_success(api.census_lock_cycle(scenario.cycle_id, registrar))
        assert_cycle_posture(locked_cycle, K.POSTURE_CENSUS_LOCKED)

        flipped = validate_success(api.get_frozen_file(scenario.extract_id, analyst))
        assert flipped["status"] == K.FROZEN_FILE_LOCKED
        assert_version(flipped, 2, "extract")

        untouched = validate_success(api.get_cohort(cohort_id, analyst))
        assert untouched["status"] == K.COHORT_DRAFT
        assert_null(untouched["locked_at"], "cohort.locked_at")
        # PRD 3.6 recomputes both variants as each member arrives, so the DRAFT cohort
        # already carries them; what the census lock leaves alone is the lock itself.
        assert_rate_variants(untouched, federal_rate_pct=50.0, ranking_rate_pct=50.0)

        component = validate_success(
            api.create_survey_component(
                f.make_survey_component_payload(
                    scenario.cycle_id, scenario.extract_id, K.DOMAIN_ENROLLMENT
                ),
                analyst,
            ),
            201,
        )
        fx.add_metrics(api, component["id"], STEADY_HEADCOUNT)
        prepared = validate_success(api.prepare_component(component["id"], analyst))
        assert_component_status(
            prepared,
            prep_status=K.PREP_PREPARED,
            edit_status=K.EDIT_CLEARED,
            fatal_open_count=0,
        )
        no_checks, checks_meta = validate_paginated(
            api.list_edit_checks(analyst, component_id=component["id"])
        )
        assert checks_meta["total_count"] == 0
        assert no_checks == []

        validate_success(
            api.certify_component(component["id"], f.make_certification_payload(), director)
        )

        frozen = validate_success(api.freeze_cycle(scenario.cycle_id, director))
        assert_cycle_posture(frozen, K.POSTURE_FROZEN)
        assert_instant_equals(frozen["frozen_at"], K.CLOCK_AFTER_CENSUS_ECHO, "cycle.frozen_at")

        cascaded = validate_success(api.get_cohort(cohort_id, analyst))
        assert cascaded["status"] == K.COHORT_LOCKED
        assert_instant_equals(cascaded["locked_at"], K.CLOCK_AFTER_CENSUS_ECHO, "cohort.locked_at")
        assert_cohort_counts(
            cascaded,
            initial_count=2,
            exclusion_count=0,
            adjusted_count=2,
            completers_count=1,
            retained_count=1,
        )
        assert_rate_variants(cascaded, federal_rate_pct=50.0, ranking_rate_pct=50.0)
        assert_version_bumped(cascaded, untouched, "cohort")

        summary = validate_success(api.get_cohort_rate_summary(cohort_id, analyst))
        assert_rate_variants(summary, federal_rate_pct=50.0, ranking_rate_pct=50.0)
        assert_equals_number(summary["rate_divergence_pp"], 0.0, "rate_divergence_pp")
        assert summary["exclusion_count"] == 0
        assert_divergence_is_difference_of_published_variants(summary)
