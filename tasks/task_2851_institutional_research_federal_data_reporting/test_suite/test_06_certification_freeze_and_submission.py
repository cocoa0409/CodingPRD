"""Closing the collection: the freeze preconditions, the deadline instant and the archive bubble."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    SHARED_ACTOR_ID,
    assert_component_status,
    assert_cycle_posture,
    assert_instant_equals,
    assert_null,
    constants as K,
    factories as f,
    fixtures as fx,
    make_analyst_headers,
    make_director_headers,
)

ENROLLMENT_STATEMENT = (
    "I certify the enrollment component as reported to the federal collection."
)
COMPLETIONS_STATEMENT = (
    "I certify the completions component as reported to the federal collection."
)
COMPLETIONS_METRIC = {
    "metric_key": K.METRIC_TOTAL_COMPLETIONS,
    "reported_value": 250,
    "prior_year_value": 250,
    "source_field_path": "sis.degrees.awarded_total",
}
HEADCOUNT_METRIC = {
    "metric_key": K.METRIC_TOTAL_HEADCOUNT,
    "reported_value": 1000,
    "prior_year_value": 1000,
    "source_field_path": "sis.enrollment.headcount",
}


def _locked_cycle_with_two_extracts(api, registrar, enrollment_checksum, completions_checksum):
    """A CENSUS_LOCKED cycle carrying one ENROLLMENT and one COMPLETIONS extract."""
    cycle = fx.create_cycle(api, registrar)
    enrollment = fx.register_extract(
        api,
        cycle["id"],
        cycle["version"],
        registrar,
        domain=K.DOMAIN_ENROLLMENT,
        record_count=1000,
        checksum=enrollment_checksum,
    )
    completions = fx.register_extract(
        api,
        cycle["id"],
        None,
        registrar,
        domain=K.DOMAIN_COMPLETIONS,
        record_count=250,
        checksum=completions_checksum,
    )
    fx.move_clock(api, K.CLOCK_AFTER_CENSUS, registrar)
    locked = validate_success(api.census_lock_cycle(cycle["id"], registrar))
    assert_cycle_posture(locked, K.POSTURE_CENSUS_LOCKED)
    return locked, enrollment, completions


def _draft_component(api, cycle_id, frozen_file_id, component_code, analyst):
    """Open the preparation workspace for one survey of the cycle."""
    return validate_success(
        api.create_survey_component(
            f.make_survey_component_payload(cycle_id, frozen_file_id, component_code),
            analyst,
        ),
        201,
    )


def _carry_to_certified(api, component_id, metric, statement, analyst, director):
    """Attach the metric, prepare as the analyst and certify as the director."""
    validate_success(api.add_component_metric(component_id, f.make_metric_payload(**metric), analyst), 201)
    prepared = validate_success(api.prepare_component(component_id, analyst))
    assert_component_status(prepared, prep_status=K.PREP_PREPARED, edit_status=K.EDIT_CLEARED)
    certified = validate_success(
        api.certify_component(component_id, f.make_certification_payload(statement), director)
    )
    assert_component_status(certified, prep_status=K.PREP_CERTIFIED)
    return certified


class TestFreezePreconditions:
    """One error covers both the empty cycle and the straggling draft component."""

    def test_freeze_is_refused_with_no_components_and_with_one_straggler(
        self, api, registrar, analyst, director
    ):
        """Only when every component is CERTIFIED does the identical call move the posture.

        PRD 3.5: "At least one survey component must exist for the cycle, and every component of
        the cycle must be `CERTIFIED`; either failure reports `ERR_COMPONENTS_NOT_READY`, so an
        empty cycle and a cycle with one straggling `DRAFT` component are refused by the same
        error."

        Design: Corner/state_machines/corner_sm_freeze_requires_at_least_one_component_and_all_certified
        """
        cycle, enrollment, completions = _locked_cycle_with_two_extracts(
            api, registrar, "c1d2e3f4a5b60122", "c1d2e3f4a5b60123"
        )

        empty = api.freeze_cycle(cycle["id"], director)
        validate_error(empty, ApiErrorId.COMPONENTS_NOT_READY, 409)

        component_a = _draft_component(
            api, cycle["id"], enrollment["id"], K.DOMAIN_ENROLLMENT, analyst
        )
        _carry_to_certified(
            api, component_a["id"], HEADCOUNT_METRIC, ENROLLMENT_STATEMENT, analyst, director
        )
        component_b = _draft_component(
            api, cycle["id"], completions["id"], K.DOMAIN_COMPLETIONS, analyst
        )
        assert_component_status(component_b, prep_status=K.PREP_DRAFT)

        straggler = api.freeze_cycle(cycle["id"], director)
        validate_error(straggler, ApiErrorId.COMPONENTS_NOT_READY, 409)

        held = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_posture(held, K.POSTURE_CENSUS_LOCKED)
        assert_null(held["frozen_at"], "cycle.frozen_at")

        _carry_to_certified(
            api, component_b["id"], COMPLETIONS_METRIC, COMPLETIONS_STATEMENT, analyst, director
        )

        frozen = validate_success(api.freeze_cycle(cycle["id"], director))
        assert_cycle_posture(frozen, K.POSTURE_FROZEN)
        assert_instant_equals(frozen["frozen_at"], K.CLOCK_AFTER_CENSUS_ECHO, "cycle.frozen_at")

        for component_id in (component_a["id"], component_b["id"]):
            assert_component_status(
                validate_success(api.get_survey_component(component_id, analyst)),
                prep_status=K.PREP_CERTIFIED,
            )


class TestSubmissionIsTerminal:
    """Federal transmission is irreversible, and the last one archives the cycle itself."""

    def test_the_last_submit_archives_the_cycle_and_locks_every_submitted_component(
        self, api, registrar, analyst, director
    ):
        """Nobody requests archival: it is derived from the aggregate state of the children.

        PRD 3.5: "The submission also bubbles upward — when the last component of the cycle reaches
        `SUBMITTED`, so that **every** component of that cycle is `SUBMITTED`, the system itself
        drives the cycle `FROZEN → ARCHIVED` and increments the cycle's `version`."

        Design: Corner/state_machines/corner_sm_submitted_component_is_locked_and_last_submit_archives_the_cycle
        """
        cycle, enrollment, completions = _locked_cycle_with_two_extracts(
            api, registrar, "c1d2e3f4a5b60119", "c1d2e3f4a5b60120"
        )
        component_a = _draft_component(
            api, cycle["id"], enrollment["id"], K.DOMAIN_ENROLLMENT, analyst
        )
        _carry_to_certified(
            api, component_a["id"], HEADCOUNT_METRIC, ENROLLMENT_STATEMENT, analyst, director
        )
        component_b = _draft_component(
            api, cycle["id"], completions["id"], K.DOMAIN_COMPLETIONS, analyst
        )
        _carry_to_certified(
            api, component_b["id"], COMPLETIONS_METRIC, COMPLETIONS_STATEMENT, analyst, director
        )
        frozen = validate_success(api.freeze_cycle(cycle["id"], director))
        assert_cycle_posture(frozen, K.POSTURE_FROZEN)

        submitted_a = validate_success(api.submit_component(component_a["id"], director))
        assert_component_status(submitted_a, prep_status=K.PREP_SUBMITTED)
        assert_instant_equals(
            submitted_a["submitted_at"], K.CLOCK_AFTER_CENSUS_ECHO, "component.submitted_at"
        )
        assert_cycle_posture(
            validate_success(api.get_reporting_cycle(cycle["id"], registrar)), K.POSTURE_FROZEN
        )

        refused = api.revert_component_to_draft(
            component_a["id"],
            f.make_revert_payload(
                "Attempting to reopen a component that has already been submitted federally."
            ),
            director,
        )
        validate_error(refused, ApiErrorId.INVALID_COMPONENT_STATE, 409)
        assert_component_status(
            validate_success(api.get_survey_component(component_a["id"], analyst)),
            prep_status=K.PREP_SUBMITTED,
        )

        submitted_b = validate_success(api.submit_component(component_b["id"], director))
        assert_component_status(submitted_b, prep_status=K.PREP_SUBMITTED)
        archived = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_posture(archived, K.POSTURE_ARCHIVED)

        blocked = api.reopen_cycle(
            cycle["id"],
            f.make_reopen_payload(
                "Attempting to reopen a cycle whose components have all been submitted."
            ),
            director,
        )
        validate_error(blocked, ApiErrorId.INVALID_CYCLE_STATE, 409)

        terminal = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_posture(terminal, K.POSTURE_ARCHIVED)
        assert terminal["reopen_count"] == 0
        assert_null(terminal["reopen_reason"], "cycle.reopen_reason")

        rows, meta = validate_paginated(
            api.list_survey_components(
                analyst, cycle_id=cycle["id"], prep_status=K.PREP_SUBMITTED
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


class TestDeadlineIsInclusiveToTheMillisecond:
    """Equality with the collection deadline passes; one millisecond later does not."""

    def test_certify_at_the_deadline_binds_and_submit_one_millisecond_later_is_refused(
        self, api, registrar, analyst, director
    ):
        """The refused submit leaves the component CERTIFIED and never bubbles the cycle onward.

        PRD 2.5: "In each, the clock must be at or before `collection_deadline` — equality passes,
        and a clock strictly after the deadline yields `ERR_COLLECTION_DEADLINE_PASSED` (HTTP 422)."

        Design: Corner/validations/corner_val_certify_passes_exactly_at_the_deadline_and_submit_fails_one_millisecond_later
        """
        scenario = fx.prepared_component(
            api,
            metrics=[HEADCOUNT_METRIC],
            checksum="c1d2e3f4a5b60145",
        )
        assert_component_status(
            scenario.component, prep_status=K.PREP_PREPARED, edit_status=K.EDIT_CLEARED
        )

        fx.move_clock(api, K.COLLECTION_DEADLINE, director)
        certified = validate_success(
            api.certify_component(
                scenario.component_id,
                f.make_certification_payload(ENROLLMENT_STATEMENT),
                director,
            )
        )
        assert_component_status(certified, prep_status=K.PREP_CERTIFIED)
        assert certified["certified_by_user_id"] == "director-1"

        frozen = validate_success(api.freeze_cycle(scenario.cycle_id, director))
        assert_cycle_posture(frozen, K.POSTURE_FROZEN)

        fx.move_clock(api, "2027-02-15T23:59:59.001Z", director)
        too_late = api.submit_component(scenario.component_id, director)
        validate_error(too_late, ApiErrorId.COLLECTION_DEADLINE_PASSED, 422)

        held = validate_success(api.get_survey_component(scenario.component_id, analyst))
        assert_component_status(held, prep_status=K.PREP_CERTIFIED)
        assert_null(held["submitted_at"], "component.submitted_at")
        assert_cycle_posture(
            validate_success(api.get_reporting_cycle(scenario.cycle_id, registrar)),
            K.POSTURE_FROZEN,
        )


PRIOR_YEAR_HEADCOUNT = {
    "metric_key": K.METRIC_TOTAL_HEADCOUNT,
    "reported_value": 1000,
    "prior_year_value": 1000,
    "source_field_path": "sis.enrollment.total_headcount",
}


class TestSegregationOutranksTheDeadline:
    """Priority 13 beats priority 22, across two different error categories and status codes."""

    @staticmethod
    def _prepared_by_the_shared_actor(api, checksum):
        """A PREPARED component whose prepared_by_user_id is the shared operator identifier."""
        scenario = fx.component_on_locked_cycle(
            api, metrics=[PRIOR_YEAR_HEADCOUNT], checksum=checksum
        )
        scenario.components = [
            validate_success(
                api.prepare_component(
                    scenario.component_id, make_analyst_headers(SHARED_ACTOR_ID)
                )
            )
        ]
        assert scenario.component["prepared_by_user_id"] == SHARED_ACTOR_ID
        assert_component_status(
            scenario.component, prep_status=K.PREP_PREPARED, edit_status=K.EDIT_CLEARED
        )
        return scenario

    def test_the_shared_actor_sees_the_duties_error_though_the_deadline_has_also_passed(
        self, api, analyst, director
    ):
        """One call breaks both rules and only the lower-numbered priority is reported.

        PRD 2.12: "Checks are evaluated in strict ascending priority and **the first violated rule
        decides the response; no later rule is evaluated**:"

        PRD 2.12: "13. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_collection_deadline_passed_on_certify
        """
        scenario = self._prepared_by_the_shared_actor(api, "a1b2c3d4e5f60011")
        fx.move_clock(api, K.CLOCK_PAST_DEADLINE, director)

        refused = api.certify_component(
            scenario.component_id,
            f.make_certification_payload(
                "I certify the fall enrollment component after the deadline."
            ),
            make_director_headers(SHARED_ACTOR_ID),
        )
        error = validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
        assert error["error_id"] != ApiErrorId.COLLECTION_DEADLINE_PASSED.value

        held = validate_success(api.get_survey_component(scenario.component_id, analyst))
        assert_component_status(
            held, prep_status=K.PREP_PREPARED, edit_status=K.EDIT_CLEARED
        )
        assert held["prepared_by_user_id"] == SHARED_ACTOR_ID
        assert_null(held["certified_by_user_id"], "component.certified_by_user_id")

    def test_each_of_the_two_rules_fires_alone_when_only_it_is_violated(
        self, api, analyst, director
    ):
        """The losing rule is genuinely live: a distinct director past the deadline still fails.

        PRD 2.12: "22. The clock is past the collection deadline — `ERR_COLLECTION_DEADLINE_PASSED`
        (422)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_collection_deadline_passed_on_certify
        """
        scenario = self._prepared_by_the_shared_actor(api, "a1b2c3d4e5f60012")

        fx.move_clock(api, K.CLOCK_PAST_DEADLINE, director)
        late = api.certify_component(
            scenario.component_id,
            f.make_certification_payload(
                "I certify the fall enrollment component after the deadline."
            ),
            director,
        )
        validate_error(late, ApiErrorId.COLLECTION_DEADLINE_PASSED, 422)

        fx.move_clock(api, K.CLOCK_AFTER_CENSUS, director)
        conflicted = api.certify_component(
            scenario.component_id,
            f.make_certification_payload(ENROLLMENT_STATEMENT),
            make_director_headers(SHARED_ACTOR_ID),
        )
        validate_error(conflicted, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

        certified = validate_success(
            api.certify_component(
                scenario.component_id,
                f.make_certification_payload(ENROLLMENT_STATEMENT),
                director,
            )
        )
        assert_component_status(certified, prep_status=K.PREP_CERTIFIED)
        assert certified["certified_by_user_id"] == "director-1"
        assert certified["prepared_by_user_id"] == SHARED_ACTOR_ID


class TestFrozenCycleOutranksTheDuplicateKey:
    """Priority 6 beats priority 27 even though both errors carry HTTP 409."""

    @staticmethod
    def _reverted_component_on_a_frozen_cycle(api, director, checksum):
        """A DRAFT component holding one TOTAL_HEADCOUNT metric beneath a FROZEN cycle."""
        scenario = fx.frozen_cycle(api, metrics=[PRIOR_YEAR_HEADCOUNT], checksum=checksum)
        assert_cycle_posture(scenario.cycle, K.POSTURE_FROZEN)
        scenario.components = [
            validate_success(
                api.revert_component_to_draft(
                    scenario.component_id,
                    f.make_revert_payload(
                        "Decertified for a post-freeze review of the residency coding."
                    ),
                    director,
                )
            )
        ]
        assert_component_status(
            scenario.component, prep_status=K.PREP_DRAFT, edit_status=K.EDIT_NOT_RUN
        )
        return scenario

    def test_a_duplicate_metric_key_on_a_frozen_cycle_reports_the_posture_error(
        self, api, analyst, director, registrar
    ):
        """Only the error_id separates a correctly ordered cascade from one run in declaration order.

        PRD 2.12: "One consequence deserves emphasis because it is easy to get backwards: because
        posture gating (priorities 6 through 9) precedes the target row's own state check (priority
        11), a request that is wrong in both ways reports the *cycle* problem."

        PRD 2.12: "6. Pre-freeze work against a `FROZEN` or `ARCHIVED` cycle — `ERR_CYCLE_FROZEN`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/frozen_cycle_state_error_outranks_duplicate_metric_key_conflict
        """
        scenario = self._reverted_component_on_a_frozen_cycle(api, director, "a1b2c3d4e5f60010")

        collision = api.add_component_metric(
            scenario.component_id,
            f.make_metric_payload(
                K.METRIC_TOTAL_HEADCOUNT,
                reported_value=1234,
                prior_year_value=1000,
                source_field_path="sis.enrollment.total_headcount_v2",
            ),
            analyst,
        )
        error = validate_error(collision, ApiErrorId.CYCLE_FROZEN, 409)
        assert error["error_id"] != ApiErrorId.DUPLICATE_METRIC_KEY.value

        rows, meta = validate_paginated(
            api.list_component_metrics(analyst, component_id=scenario.component_id)
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["metric_key"] == K.METRIC_TOTAL_HEADCOUNT
        assert rows[0]["reported_value"] == 1000

        assert_component_status(
            validate_success(api.get_survey_component(scenario.component_id, analyst)),
            prep_status=K.PREP_DRAFT,
        )
        assert_cycle_posture(
            validate_success(api.get_reporting_cycle(scenario.cycle_id, registrar)),
            K.POSTURE_FROZEN,
        )

    def test_the_losing_uniqueness_rule_still_fires_on_a_cycle_that_is_not_frozen(
        self, api, analyst, director
    ):
        """A fresh key beneath the frozen cycle still fails, and the same duplicate passes it.

        PRD 2.12: "27. Scoped uniqueness — the nine `ERR_DUPLICATE_…` codes (409)."

        PRD 3.3: "The pair of `component_id` and `metric_key` must be unique, with a collision
        reporting `ERR_DUPLICATE_METRIC_KEY`."

        Design: Difficulty/priority_pair_validation_conflict/frozen_cycle_state_error_outranks_duplicate_metric_key_conflict
        """
        frozen = self._reverted_component_on_a_frozen_cycle(api, director, "a1b2c3d4e5f60013")
        fresh_key = api.add_component_metric(
            frozen.component_id,
            f.make_metric_payload(
                K.METRIC_FTE_ENROLLMENT,
                reported_value=940,
                source_field_path="sis.enrollment.fte",
            ),
            analyst,
        )
        validate_error(fresh_key, ApiErrorId.CYCLE_FROZEN, 409)

        draft = fx.component_on_locked_cycle(
            api,
            metrics=[PRIOR_YEAR_HEADCOUNT],
            checksum="a1b2c3d4e5f60014",
            cycle_code=K.CYCLE_CODE_ALT,
        )
        duplicate = api.add_component_metric(
            draft.component_id,
            f.make_metric_payload(
                K.METRIC_TOTAL_HEADCOUNT,
                reported_value=1234,
                prior_year_value=1000,
                source_field_path="sis.enrollment.total_headcount_v2",
            ),
            analyst,
        )
        validate_error(duplicate, ApiErrorId.DUPLICATE_METRIC_KEY, 409)

        rows, meta = validate_paginated(
            api.list_component_metrics(analyst, component_id=draft.component_id)
        )
        assert meta["total_count"] == 1
        assert rows[0]["reported_value"] == 1000
