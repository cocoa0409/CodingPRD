"""Who may write what: the five exclusive capacities, the cross-role refusals, the partitioned reads and the identity checks."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_USER_ID,
    DIRECTOR_USER_ID,
    SHARED_ACTOR_ID,
    ApiErrorId,
    assert_cell,
    assert_component_status,
    assert_cycle_ledger,
    assert_cycle_posture,
    assert_edit_check,
    assert_instant_equals,
    assert_null,
    assert_publication_ledger,
    assert_request_counters,
    assert_restatement,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
    make_analyst_headers,
    make_director_headers,
)

HEADCOUNT_DEFINITION = "EF_TOTAL_HEADCOUNT"
HEADCOUNT_DOMAIN = ["HEADCOUNT"]

CERTIFICATION_STATEMENT = (
    "I certify the enrollment component as reported to the federal collection."
)
ANALYST_CERTIFICATION_ATTEMPT = "The analyst attempts to certify the component it assembled."

INTERNAL_OFFICE = "Office of Institutional Effectiveness"
CAMPUS_NEWSPAPER = "Campus Newspaper"

SECOND_CLOCK = "2026-11-02T00:00:00Z"
SECOND_CLOCK_ECHO = "2026-11-02T00:00:00.000Z"

HEADCOUNT_30 = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 30,
        "prior_year_value": 30,
        "source_field_path": "sis.enrollment.headcount",
    },
)
HEADCOUNT_1125 = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 1125,
        "prior_year_value": 1000,
        "source_field_path": "sis.enrollment.headcount",
    },
)

NURSING_EXPLANATION = "A new nursing cohort of 125 students entered in the fall term."
NURSING_COMPARISON = "Prior year 1000 headcount; current 1125 after the nursing expansion."
SELF_ADJUDICATION_NOTE = "Accepting the explanation I wrote myself."
ADJUDICATION_NOTE = "Nursing expansion confirmed against the admissions file."
DOUBLE_COUNT_JUSTIFICATION = "Five students were double counted across two majors."
SELF_REJECTION_REASON = "Rejecting the request I filed myself."
NOTICE_REFERENCE = "IR-NOTICE-2026-014"
PUBLICATION_START = "2026-12-01T00:00:00Z"


class TestEveryRoleExecutesItsOwnExclusiveWrites:
    """The positive half of the role model: one cycle in which all five capacities are exercised."""

    def test_registrar_analyst_steward_director_and_disclosure_officer_are_each_admitted(
        self, api, analyst, director, registrar, steward, disclosure
    ):
        """A blanket deny would satisfy every 403 in the suite and fail this one walk-through.

        PRD 2.1: "A `RegistrarOfficer` owns the census snapshot and the student roster: opening cycles, registering census extracts, locking the census, defining and locking cohorts, recording tracked outcomes and filing allowable-exclusion claims."

        PRD 2.1: "An `IRAnalyst` assembles survey components, reports metrics, explains prior-year variances, proposes element mappings, drafts external submissions, reconciles them, publishes dashboard figures and files restatement requests."

        PRD 2.1: "A `DataSteward` owns the federal definition library and the verdict on local-to-federal element mappings."

        PRD 2.1: "An `IRDirector` is the approving authority: certifying and federally submitting components, adjudicating edit checks and exclusion claims, deciding restatements, overriding held variances, transmitting external submissions, withdrawing publications, and freezing or reopening the cycle."

        PRD 2.1: "A `DisclosureOfficer` intakes data requests, builds the crosstab, runs disclosure avoidance and closes the request, and is the only role permitted to write disclosure artefacts."

        PRD 2.4: "Recomputation counts as mutation."

        Design: Corner/rbac/corner_rbac_all_five_roles_execute_their_own_exclusive_writes_in_one_cycle
        """
        cycle = validate_success(
            api.create_reporting_cycle(f.make_reporting_cycle_payload(), registrar), 201
        )
        assert_version(cycle, 1, "cycle")

        extract = validate_success(
            api.register_frozen_file(
                cycle["id"], f.make_frozen_file_payload(cycle["version"]), registrar
            ),
            201,
        )
        assert extract["status"] == K.FROZEN_FILE_ACTIVE

        # The clock is a shared capability: the steward may drive it.
        clock = validate_success(api.set_clock(K.CLOCK_AFTER_CENSUS, steward))
        assert_instant_equals(clock["current_utc"], K.CLOCK_AFTER_CENSUS_ECHO, "current_utc")

        locked = validate_success(api.census_lock_cycle(cycle["id"], registrar))
        assert_cycle_posture(locked, K.POSTURE_CENSUS_LOCKED)

        component = validate_success(
            api.create_survey_component(
                f.make_survey_component_payload(cycle["id"], extract["id"]), analyst
            ),
            201,
        )
        validate_success(
            api.add_component_metric(
                component["id"],
                f.make_metric_payload(
                    metric_key=K.METRIC_TOTAL_HEADCOUNT,
                    reported_value=1000,
                    prior_year_value=1000,
                    source_field_path="sis.enrollment.headcount",
                ),
                analyst,
            ),
            201,
        )

        definition = validate_success(
            api.create_federal_definition(
                f.make_federal_definition_payload(
                    definition_code=HEADCOUNT_DEFINITION,
                    survey_component=K.DOMAIN_ENROLLMENT,
                    value_domain=HEADCOUNT_DOMAIN,
                    unit_of_measure="COUNT",
                    required=False,
                ),
                steward,
            ),
            201,
        )
        assert definition["definition_code"] == HEADCOUNT_DEFINITION

        validate_success(api.prepare_component(component["id"], analyst))
        certified = validate_success(
            api.certify_component(
                component["id"], f.make_certification_payload(CERTIFICATION_STATEMENT), director
            )
        )
        assert_component_status(
            certified, prep_status=K.PREP_CERTIFIED, edit_status=K.EDIT_CLEARED, fatal_open_count=0
        )
        assert certified["prepared_by_user_id"] == ANALYST_USER_ID
        assert certified["certified_by_user_id"] == DIRECTOR_USER_ID

        frozen = validate_success(api.freeze_cycle(cycle["id"], director))
        assert_cycle_posture(frozen, K.POSTURE_FROZEN)
        assert_cycle_ledger(frozen, frozen_file_count=1, active_record_count=1000)
        # create 1, the extract's ledger recomputation +1, the census lock +1, the freeze +1.
        assert_version(frozen, 4, "cycle")

        request = validate_success(
            api.create_data_request(
                cycle["id"],
                f.make_data_request_payload(
                    requester_org=INTERNAL_OFFICE,
                    requester_type=K.REQUESTER_INTERNAL,
                    requested_metric_key=K.METRIC_TOTAL_HEADCOUNT,
                ),
                disclosure,
            ),
            201,
        )
        assert_request_counters(request, cell_count=0, status=K.REQUEST_RECEIVED)


class TestNoRoleReachesIntoAnotherRolesExclusiveWrite:
    """Six cross-role writes, six 403s, and the director gets no implicit superset."""

    def test_both_directions_are_refused_and_nothing_is_written(
        self, api, analyst, director, registrar, steward, disclosure
    ):
        """The capacities are a partition, not a hierarchy: the director cannot register an extract.

        PRD 2.1: "Each endpoint declares the roles permitted to call it (see §4); a syntactically valid actor whose role is not on that list is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        PRD 2.1: "An `IRDirector` is the approving authority: certifying and federally submitting components, adjudicating edit checks and exclusion claims, deciding restatements, overriding held variances, transmitting external submissions, withdrawing publications, and freezing or reopening the cycle."

        PRD 2.1: "A `RegistrarOfficer` owns the census snapshot and the student roster: opening cycles, registering census extracts, locking the census, defining and locking cohorts, recording tracked outcomes and filing allowable-exclusion claims."

        PRD 2.1: "An `IRAnalyst` assembles survey components, reports metrics, explains prior-year variances, proposes element mappings, drafts external submissions, reconciles them, publishes dashboard figures and files restatement requests."

        PRD 2.1: "A `DataSteward` owns the federal definition library and the verdict on local-to-federal element mappings."

        PRD 3.1: "The payload carries a `cycle_code` — the human-readable identifier such as `IPEDS-2027`, between 1 and 32 characters, and unique across all cycles under case-sensitive comparison, with a collision reported as `ERR_DUPLICATE_CYCLE_CODE` — together with the `collection_year` the cycle reports on (an integer at least 2000 and at most 2100), the `census_date`, and the `collection_deadline`, which must fall strictly after midnight UTC on the census date."

        Design: Corner/rbac/corner_rbac_no_role_may_reach_into_another_roles_exclusive_write
        """
        scenario = fx.component_on_locked_cycle(api, metrics=())
        before = fx.read_cycle(api, scenario.cycle_id)

        analyst_certifying = api.certify_component(
            scenario.component_id,
            f.make_certification_payload(ANALYST_CERTIFICATION_ATTEMPT),
            analyst,
        )
        validate_error(analyst_certifying, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        director_registering = api.register_frozen_file(
            scenario.cycle_id,
            f.make_frozen_file_payload(before["version"], domain=K.DOMAIN_HR, record_count=400),
            director,
        )
        validate_error(director_registering, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        registrar_assembling = api.create_survey_component(
            f.make_survey_component_payload(
                scenario.cycle_id, scenario.extract_id, component_code=K.DOMAIN_COMPLETIONS
            ),
            registrar,
        )
        validate_error(registrar_assembling, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        steward_publishing = api.create_publication(
            f.make_publication_payload(
                scenario.component_id,
                metric_key=K.METRIC_TOTAL_HEADCOUNT,
                published_value=1000,
                effective_from=PUBLICATION_START,
            ),
            steward,
        )
        validate_error(steward_publishing, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        disclosure_opening_a_cycle = api.create_reporting_cycle(
            f.make_reporting_cycle_payload(
                cycle_code=K.CYCLE_CODE_ALT,
                collection_year=2028,
                census_date="2027-10-15",
                collection_deadline="2028-02-15T23:59:59Z",
            ),
            disclosure,
        )
        validate_error(disclosure_opening_a_cycle, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        director_defining = api.create_federal_definition(
            f.make_federal_definition_payload(
                definition_code=HEADCOUNT_DEFINITION,
                survey_component=K.DOMAIN_ENROLLMENT,
                value_domain=HEADCOUNT_DOMAIN,
                unit_of_measure="COUNT",
                required=True,
            ),
            director,
        )
        validate_error(director_defining, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        untouched_component = validate_success(
            api.get_survey_component(scenario.component_id, analyst)
        )
        assert_component_status(untouched_component, prep_status=K.PREP_DRAFT)
        assert_null(untouched_component["certified_by_user_id"], "certified_by_user_id")
        assert_version(untouched_component, 1, "component")

        untouched_cycle = validate_success(api.get_reporting_cycle(scenario.cycle_id, director))
        assert_cycle_ledger(untouched_cycle, frozen_file_count=1, active_record_count=1000)
        assert_version(untouched_cycle, before["version"], "cycle")

        # Nothing was written for the refused cycle: the code is still free for its owner to take.
        reopened_slot = validate_success(
            api.create_reporting_cycle(
                f.make_reporting_cycle_payload(
                    cycle_code=K.CYCLE_CODE_ALT,
                    collection_year=2028,
                    census_date="2027-10-15",
                    collection_deadline="2028-02-15T23:59:59Z",
                ),
                registrar,
            ),
            201,
        )
        assert reopened_slot["cycle_code"] == K.CYCLE_CODE_ALT

        _definitions, definition_meta = validate_paginated(api.list_federal_definitions(steward))
        assert definition_meta["total_count"] == 0

        _publications, publication_meta = validate_paginated(api.list_publications(analyst))
        assert publication_meta["total_count"] == 0


class TestReadsAreSharedExceptTheTwoDisclosureFamilies:
    """The shared set is not "all GETs": the disclosure reads are partitioned by role."""

    def test_the_same_disclosure_read_answers_the_director_and_refuses_the_other_three(
        self, api, analyst, director, registrar, steward, disclosure
    ):
        """Ordinary reads and the clock are open to all five roles; two families are not.

        PRD 2.1: "Read access is broad — every role may read cycles, extracts, components, metrics, edit checks, cohorts, members, definitions, mappings, submissions, publications and restatements — with one deliberate narrowing: data-request and disclosure-cell reads are visible only to `DisclosureOfficer` and `IRDirector`."

        PRD 2.1: "Each endpoint declares the roles permitted to call it (see §4); a syntactically valid actor whose role is not on that list is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        PRD 2.5: "All temporal rules in this system read a **logical clock** rather than wall-clock time, and a dedicated test-driving capability sets it: a caller in any of the five roles supplies a `to_iso8601` instant and the server answers with the clock's new reading in a `current_utc` field."

        Design: Corner/rbac/corner_rbac_reads_are_shared_by_all_five_roles_except_the_disclosure_reads
        """
        scenario = fx.request_with_cells(
            api,
            "GENDER",
            (("FEMALE", 30),),
            metrics=HEADCOUNT_30,
            record_count=30,
            requester_org=CAMPUS_NEWSPAPER,
            requester_type=K.REQUESTER_MEDIA,
            requested_metric_key=K.METRIC_TOTAL_HEADCOUNT,
        )
        request_id = scenario.request_id
        cell_id = scenario.cells[0]["id"]

        clock = validate_success(api.set_clock(SECOND_CLOCK, disclosure))
        assert_instant_equals(clock["current_utc"], SECOND_CLOCK_ECHO, "current_utc")

        cycle = validate_success(api.get_reporting_cycle(scenario.cycle_id, disclosure))
        assert_cycle_posture(cycle, K.POSTURE_FROZEN)
        component = validate_success(api.get_survey_component(scenario.component_id, steward))
        assert_component_status(component, prep_status=K.PREP_CERTIFIED)

        validate_error(api.list_data_requests(steward), ApiErrorId.ROLE_NOT_PERMITTED, 403)
        validate_error(
            api.get_data_request(request_id, analyst), ApiErrorId.ROLE_NOT_PERMITTED, 403
        )
        validate_error(
            api.get_disclosure_cell(cell_id, registrar), ApiErrorId.ROLE_NOT_PERMITTED, 403
        )

        rows, meta = validate_paginated(
            api.list_disclosure_cells(director, request_id=request_id, limit=100)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [cell_id]

        cell = validate_success(api.get_disclosure_cell(cell_id, disclosure))
        assert_cell(cell, suppression_state=K.CELL_PENDING, released_count=None, raw_count=30)

        seen_by_director = validate_success(api.get_data_request(request_id, director))
        assert seen_by_director["requester_type"] == K.REQUESTER_MEDIA
        assert_request_counters(seen_by_director, cell_count=1, status=K.REQUEST_RECEIVED)


class TestSegregationOfDutiesBindsAdjudicationAndTheRestatementDecision:
    """Two anchors beyond certification: the explainer may not adjudicate, the requester may not decide."""

    def test_one_shared_identity_is_refused_at_the_adjudication_and_at_both_restatement_verdicts(
        self, api, analyst, director
    ):
        """The role is IRDirector on all three calls, so only the identity comparison can refuse them.

        PRD 2.10: "The system enforces it by comparing the acting `X-User-ID` against the opaque identifier recorded by the preceding step, and a match is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD 2.10: "Adjudicating an edit check compares the actor against `explained_by_user_id`."

        PRD 2.10: "Approving a restatement request and rejecting a restatement request both compare the actor against `requested_by_user_id`."

        PRD 3.7: "It requires the request to be `SUBMITTED` (else `ERR_INVALID_RESTATEMENT_STATE`), its parent publication to be `RESTATEMENT_PENDING` (else `ERR_INVALID_PUBLICATION_STATE`), the acting `X-User-ID` to differ from `requested_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES` — a request whose requester is the literal `SYSTEM` can never collide), and, when `public_notice_required` is true, a `public_notice_reference` of 3 to 120 characters, absent which the approval reports `ERR_PUBLIC_NOTICE_REQUIRED`."

        PRD 3.7: "Otherwise `delta_pct` is the absolute difference between `proposed_value` and the baseline, divided by the absolute baseline, multiplied by 100, rounded half up to two decimal places, and `public_notice_required` is true when `delta_pct` is at least 2.00."

        PRD 3.7: "On success the request records `approved_by_user_id`, stores the reference, and increments its `version`; the publication sets `published_value` to the request's `proposed_value`, increases `net_applied_delta` by the difference between `proposed_value` and `baseline_value` rounded half up to one decimal place, increments `restatement_count` by one, moves to `RESTATED`, and increments its own `version`."

        Design: Corner/rbac/corner_rbac_segregation_of_duties_binds_adjudicate_and_the_restatement_decision
        """
        shared_analyst = make_analyst_headers(SHARED_ACTOR_ID)
        shared_director = make_director_headers(SHARED_ACTOR_ID)

        scenario = fx.prepared_component(api, record_count=1125, metrics=HEADCOUNT_1125)
        assert len(scenario.checks) == 1, "one prior-year variance check is expected"
        check_id = scenario.checks[0]["id"]
        assert_edit_check(
            scenario.checks[0],
            metric_key=K.METRIC_TOTAL_HEADCOUNT,
            severity=K.SEVERITY_WARNING,
            status=K.CHECK_OPEN,
            variance_pct=12.5,
        )

        explained = validate_success(
            api.explain_edit_check(
                check_id,
                f.make_explanation_payload(NURSING_EXPLANATION, NURSING_COMPARISON),
                shared_analyst,
            )
        )
        assert_edit_check(explained, status=K.CHECK_EXPLAINED)
        assert explained["explained_by_user_id"] == SHARED_ACTOR_ID

        self_adjudication = api.adjudicate_edit_check(
            check_id,
            f.make_adjudication_payload(K.DECISION_ACCEPT, adjudication_note=SELF_ADJUDICATION_NOTE),
            shared_director,
        )
        validate_error(self_adjudication, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
        still_explained = validate_success(api.get_edit_check(check_id, analyst))
        assert_edit_check(still_explained, status=K.CHECK_EXPLAINED)
        assert_null(still_explained["adjudicated_by_user_id"], "adjudicated_by_user_id")

        accepted = validate_success(
            api.adjudicate_edit_check(
                check_id,
                f.make_adjudication_payload(K.DECISION_ACCEPT, adjudication_note=ADJUDICATION_NOTE),
                director,
            )
        )
        assert_edit_check(accepted, status=K.CHECK_ACCEPTED)
        assert accepted["adjudicated_by_user_id"] == DIRECTOR_USER_ID
        assert_component_status(
            validate_success(api.get_survey_component(scenario.component_id, analyst)),
            edit_status=K.EDIT_CLEARED,
        )

        validate_success(
            api.certify_component(
                scenario.component_id,
                f.make_certification_payload(CERTIFICATION_STATEMENT),
                director,
            )
        )
        frozen = validate_success(api.freeze_cycle(scenario.cycle_id, director))
        assert_cycle_posture(frozen, K.POSTURE_FROZEN)

        publication = validate_success(
            api.create_publication(
                f.make_publication_payload(
                    scenario.component_id,
                    metric_key=K.METRIC_TOTAL_HEADCOUNT,
                    published_value=1125,
                    effective_from=PUBLICATION_START,
                ),
                analyst,
            ),
            201,
        )
        assert_publication_ledger(
            publication,
            published_value=1125,
            original_value=1125,
            restatement_count=0,
            publication_status=K.PUBLICATION_PUBLISHED,
        )
        assert_version(publication, 1, "publication")

        restatement = validate_success(
            api.file_restatement(
                publication["id"],
                f.make_restatement_payload(
                    1120,
                    publication["version"],
                    justification=DOUBLE_COUNT_JUSTIFICATION,
                ),
                shared_analyst,
            ),
            201,
        )
        assert_restatement(
            restatement,
            status=K.RESTATEMENT_SUBMITTED,
            origin=K.ORIGIN_ANALYST,
            requested_by_user_id=SHARED_ACTOR_ID,
            baseline_value=1125,
            proposed_value=1120,
            delta_pct=0.44,
            public_notice_required=False,
        )
        assert_publication_ledger(
            validate_success(api.get_publication(publication["id"], analyst)),
            published_value=1125,
            publication_status=K.PUBLICATION_RESTATEMENT_PENDING,
        )

        self_approval = api.approve_restatement(
            restatement["id"],
            shared_director,
            f.make_restatement_approval_payload(NOTICE_REFERENCE),
        )
        validate_error(self_approval, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

        self_rejection = api.reject_restatement(
            restatement["id"],
            f.make_restatement_rejection_payload(SELF_REJECTION_REASON),
            shared_director,
        )
        validate_error(self_rejection, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

        undecided = validate_success(api.get_restatement(restatement["id"], analyst))
        assert_restatement(undecided, status=K.RESTATEMENT_SUBMITTED)
        assert_null(undecided["approved_by_user_id"], "approved_by_user_id")

        applied = validate_success(
            api.approve_restatement(
                restatement["id"], director, f.make_restatement_approval_payload(NOTICE_REFERENCE)
            )
        )
        assert_restatement(applied, status=K.RESTATEMENT_APPLIED)
        assert applied["approved_by_user_id"] == DIRECTOR_USER_ID
        assert_publication_ledger(
            validate_success(api.get_publication(publication["id"], analyst)),
            published_value=1120,
            original_value=1125,
            net_applied_delta=-5.0,
            restatement_count=1,
            publication_status=K.PUBLICATION_RESTATED,
        )
