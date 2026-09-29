"""Which error the server names: the 401 gate, the fourteen 404 families, the row-state ids and the nine duplicates."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_cell,
    assert_cohort_counts,
    assert_component_status,
    assert_cycle_ledger,
    assert_cycle_posture,
    assert_error_body_leaks_nothing,
    assert_instant_equals,
    assert_null,
    assert_request_counters,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
    make_headers_missing_role,
    make_headers_missing_user_id,
    make_headers_unknown_role,
    make_headers_without_auth,
)

ATTENDANCE_DEFINITION = "EF_ATTENDANCE_STATUS"
ATTENDANCE_DOMAIN = ["FULL_TIME", "PART_TIME"]
ATTENDANCE_VALUE_MAP = {"FT": "FULL_TIME", "PT": "PART_TIME"}
NARROWED_VALUE_MAP = {"FT": "FULL_TIME"}
HR_VALUE_MAP = {"F": "FULL_TIME"}
SIS_LOAD_PATH = "SIS.ENROLL.LOAD_CODE"
SIS_LOAD_PATH_ALT = "SIS.ENROLL.LOAD_CODE_ALT"
HR_LOAD_PATH = "HR.APPT.LOAD_CODE"
ETHNICITY_PATH = "SIS.STUDENT.ETHNICITY"
ETHNICITY_VALUE_MAP = {"A": "ASIAN"}

ARMED_FORCES_EVIDENCE = "Active duty orders dated 2023-08-14 are on file with the registrar."
REFILED_EVIDENCE = "Refiling the same active duty orders a second time by mistake."
PREMATURE_REVIEW_NOTE = "Reviewing a claim that was never filed."

INTERNAL_OFFICE = "Office of Institutional Effectiveness"
STATE_BOARD = "State Board"

EARLY_RELEASE_NOTE = "Releasing before the disclosure screen has run."
RELEASE_NOTE = "Screened counts released to the internal office."
SECOND_RELEASE_NOTE = "Releasing a second time."

CERTIFICATION_STATEMENT = (
    "I certify the enrollment component as reported to the federal collection."
)

SHORT_COVERAGE_START = "2026-08-01"
SHORT_COVERAGE_END = "2026-08-31"

HEADCOUNT_30 = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 30,
        "prior_year_value": 30,
        "source_field_path": "sis.enrollment.headcount",
    },
)


class TestBothHeaderDefectsCollapseToOneUnauthenticated:
    """A missing header and an unrecognised role are the same 401, decided before anything else."""

    def test_absent_headers_and_an_unknown_role_are_both_refused_before_any_lookup(
        self, api, analyst, registrar
    ):
        """Authentication is settled before RBAC and before the row is even looked up.

        PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the five recognised roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

        PRD 2.1: "The five roles are `IRAnalyst`, `IRDirector`, `RegistrarOfficer`, `DataSteward` and `DisclosureOfficer`."

        PRD 2.2: "- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/corner_err_missing_or_unknown_role_header_is_unauthenticated
        """
        cycle = fx.create_cycle(api, registrar)

        for defective in (
            make_headers_without_auth(),
            make_headers_missing_user_id(),
            make_headers_missing_role(),
            make_headers_unknown_role(),
        ):
            refused = api.get_reporting_cycle(cycle["id"], defective)
            validate_error(refused, ApiErrorId.UNAUTHENTICATED, 401)
            assert_error_body_leaks_nothing(refused.json())
            assert "cycle_code" not in refused.json()["data"]

        # A defective actor never reaches the 404 either: authentication is decided first.
        unresolvable = api.get_reporting_cycle(K.UNKNOWN_UUID, make_headers_unknown_role())
        validate_error(unresolvable, ApiErrorId.UNAUTHENTICATED, 401)

        read = validate_success(api.get_reporting_cycle(cycle["id"], analyst))
        assert read["cycle_code"] == K.CYCLE_CODE
        assert read["id"] == cycle["id"]


class TestEveryEntityFamilyAnswersWithItsOwn404:
    """Fourteen unknown identifiers, fourteen distinct 404 ids — in the path and in the body alike."""

    def test_each_unknown_identifier_names_its_own_family_in_path_and_in_body(
        self, api, analyst, registrar, steward, disclosure
    ):
        """The same uuid names nothing everywhere, and every family still reports its own code.

        PRD 2.12: "The thirteen path identifiers map to their own error codes: `{cycle_id}` to `ERR_CYCLE_NOT_FOUND`, `{frozen_file_id}` to `ERR_FROZEN_FILE_NOT_FOUND`, `{component_id}` to `ERR_COMPONENT_NOT_FOUND`, `{metric_id}` to `ERR_METRIC_NOT_FOUND`, `{edit_check_id}` to `ERR_EDIT_CHECK_NOT_FOUND`, `{cohort_id}` to `ERR_COHORT_NOT_FOUND`, `{member_id}` to `ERR_MEMBER_NOT_FOUND`, `{mapping_id}` to `ERR_MAPPING_NOT_FOUND`, `{submission_id}` to `ERR_SUBMISSION_NOT_FOUND`, `{publication_id}` to `ERR_PUBLICATION_NOT_FOUND`, `{restatement_id}` to `ERR_RESTATEMENT_NOT_FOUND`, `{request_id}` to `ERR_DATA_REQUEST_NOT_FOUND`, and `{cell_id}` to `ERR_CELL_NOT_FOUND`."

        PRD 2.12: "Foreign keys carried in a request body are resolved the same way and produce the same codes: an unresolvable `cycle_id` gives `ERR_CYCLE_NOT_FOUND`, `frozen_file_id` gives `ERR_FROZEN_FILE_NOT_FOUND`, `component_id` gives `ERR_COMPONENT_NOT_FOUND`, and `definition_id` gives `ERR_DEFINITION_NOT_FOUND`."

        Design: Corner/errors/corner_err_every_not_found_id_is_reachable_by_path_or_body_reference
        """
        scenario = fx.census_locked_cycle(api)

        validate_error(
            api.get_reporting_cycle(K.UNKNOWN_UUID, analyst), ApiErrorId.CYCLE_NOT_FOUND, 404
        )
        validate_error(
            api.get_frozen_file(K.UNKNOWN_UUID, analyst), ApiErrorId.FROZEN_FILE_NOT_FOUND, 404
        )
        validate_error(
            api.get_survey_component(K.UNKNOWN_UUID, analyst), ApiErrorId.COMPONENT_NOT_FOUND, 404
        )
        validate_error(
            api.get_component_metric(K.UNKNOWN_UUID, analyst), ApiErrorId.METRIC_NOT_FOUND, 404
        )
        validate_error(
            api.get_edit_check(K.UNKNOWN_UUID, analyst), ApiErrorId.EDIT_CHECK_NOT_FOUND, 404
        )
        validate_error(
            api.get_cohort(K.UNKNOWN_UUID, registrar), ApiErrorId.COHORT_NOT_FOUND, 404
        )
        validate_error(
            api.get_cohort_member(K.UNKNOWN_UUID, registrar), ApiErrorId.MEMBER_NOT_FOUND, 404
        )
        validate_error(
            api.get_federal_definition(K.UNKNOWN_UUID, steward),
            ApiErrorId.DEFINITION_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_element_mapping(K.UNKNOWN_UUID, steward), ApiErrorId.MAPPING_NOT_FOUND, 404
        )
        validate_error(
            api.get_external_submission(K.UNKNOWN_UUID, analyst),
            ApiErrorId.SUBMISSION_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_publication(K.UNKNOWN_UUID, analyst), ApiErrorId.PUBLICATION_NOT_FOUND, 404
        )
        validate_error(
            api.get_restatement(K.UNKNOWN_UUID, analyst), ApiErrorId.RESTATEMENT_NOT_FOUND, 404
        )
        validate_error(
            api.get_data_request(K.UNKNOWN_UUID, disclosure),
            ApiErrorId.DATA_REQUEST_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_disclosure_cell(K.UNKNOWN_UUID, disclosure), ApiErrorId.CELL_NOT_FOUND, 404
        )

        # The same discrimination applies to references carried in a request body.
        validate_error(
            api.create_survey_component(
                f.make_survey_component_payload(K.UNKNOWN_UUID, scenario.extract_id), analyst
            ),
            ApiErrorId.CYCLE_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_survey_component(
                f.make_survey_component_payload(scenario.cycle_id, K.UNKNOWN_UUID), analyst
            ),
            ApiErrorId.FROZEN_FILE_NOT_FOUND,
            404,
        )
        validate_error(
            api.propose_element_mapping(
                f.make_element_mapping_payload(
                    scenario.cycle_id,
                    K.UNKNOWN_UUID,
                    local_field_path=ETHNICITY_PATH,
                    value_map=ETHNICITY_VALUE_MAP,
                ),
                analyst,
            ),
            ApiErrorId.DEFINITION_NOT_FOUND,
            404,
        )

        rows, meta = validate_paginated(
            api.list_survey_components(analyst, cycle_id=scenario.cycle_id)
        )
        assert meta["total_count"] == 0, "a refused reference must not leave a partial component"
        assert rows == []


class TestTheSealedSnapshotAndTheWrongRowStateKeepDistinctIds:
    """Three refusals, three ids: the sealed snapshot, the exclusion loop and the mapping verdict."""

    def test_a_second_extract_a_premature_review_and_a_settled_mapping_each_name_their_own_id(
        self, api, analyst, director, registrar, steward
    ):
        """A sealed cycle is not a frozen one, and each row-level lifecycle reports its own code.

        PRD 2.6: "The snapshot is sealed at that point and stays sealed until the cycle is reopened, so extract registration requires a posture of `OPEN` or `REOPENED`; an attempt while `CENSUS_LOCKED` is refused with `ERR_CENSUS_LOCKED` (HTTP 409)."

        PRD 3.6: "Both variants store `exclusion_claimed_by_user_id` and increment the member's `version`, both require the parent cohort's cycle not to be `ARCHIVED`, and a member in any other exclusion state reports `ERR_INVALID_EXCLUSION_STATE`."

        PRD 3.6: "`CLAIMED → APPROVED` on an approval, `CLAIMED → DENIED` on a denial, and `APPROVED → DENIED` on a denial of an already-approved exclusion, which is the compensating action that reverses an approval."

        PRD 3.2: "A revision is refused with `ERR_INVALID_MAPPING_STATE` unless the mapping is `REJECTED`, with `ERR_CYCLE_FROZEN` when the cycle's posture is `FROZEN` or `ARCHIVED`, and with `ERR_VALUE_DOMAIN_VIOLATION` when any value of the *new* `value_map` falls outside the target definition's `value_domain`."

        PRD 3.2: "On success the steward's opaque identifier is written to `validated_by_user_id`, `rejection_reason` is cleared to null, and `version` is incremented; `VALIDATED` is terminal for the mapping."

        Design: Corner/errors/corner_err_sealed_snapshot_and_wrong_row_state_ids_are_distinct
        """
        scenario = fx.census_locked_cycle(api)
        assert_cycle_posture(scenario.cycle, K.POSTURE_CENSUS_LOCKED)

        sealed = api.register_frozen_file(
            scenario.cycle_id,
            f.make_frozen_file_payload(
                scenario.cycle["version"],
                record_count=40,
                coverage_start_date=SHORT_COVERAGE_START,
                coverage_end_date=SHORT_COVERAGE_END,
            ),
            registrar,
        )
        validate_error(sealed, ApiErrorId.CENSUS_LOCKED, 409)
        assert_cycle_ledger(
            fx.read_cycle(api, scenario.cycle_id), frozen_file_count=1, active_record_count=1000
        )

        scenario = fx.cohort_on_scenario(
            api, scenario, fx.roster_of(K.OUTCOME_NO_LONGER_ENROLLED)
        )
        member = scenario.member("S001")
        assert member["exclusion_status"] == K.EXCLUSION_NONE

        premature = api.review_exclusion_claim(
            member["id"],
            f.make_exclusion_review_payload(K.DECISION_APPROVE, review_note=PREMATURE_REVIEW_NOTE),
            director,
        )
        validate_error(premature, ApiErrorId.INVALID_EXCLUSION_STATE, 409)
        untouched = validate_success(api.get_cohort_member(member["id"], registrar))
        assert untouched["exclusion_status"] == K.EXCLUSION_NONE
        assert_null(untouched["exclusion_reviewed_by_user_id"], "exclusion_reviewed_by_user_id")
        assert_version(untouched, 1, "member")

        claimed = validate_success(
            api.file_exclusion_claim(
                member["id"],
                f.make_exclusion_claim_payload(
                    K.EXCLUSION_CODE_ARMED_FORCES,
                    exclusion_evidence_note=ARMED_FORCES_EVIDENCE,
                ),
                registrar,
            )
        )
        assert claimed["exclusion_status"] == K.EXCLUSION_CLAIMED
        assert claimed["exclusion_code"] == K.EXCLUSION_CODE_ARMED_FORCES
        assert_version(claimed, 2, "member")

        refiled = api.file_exclusion_claim(
            member["id"],
            f.make_exclusion_claim_payload(
                K.EXCLUSION_CODE_ARMED_FORCES, exclusion_evidence_note=REFILED_EVIDENCE
            ),
            registrar,
        )
        validate_error(refiled, ApiErrorId.INVALID_EXCLUSION_STATE, 409)
        still_claimed = validate_success(api.get_cohort_member(member["id"], registrar))
        assert still_claimed["exclusion_status"] == K.EXCLUSION_CLAIMED
        assert still_claimed["exclusion_evidence_note"] == ARMED_FORCES_EVIDENCE
        assert_version(still_claimed, 2, "member")

        definition = fx.create_definition(
            api,
            steward,
            definition_code=ATTENDANCE_DEFINITION,
            survey_component=K.DOMAIN_ENROLLMENT,
            value_domain=ATTENDANCE_DOMAIN,
            unit_of_measure="CODE",
            required=False,
        )
        mapping = validate_success(
            api.propose_element_mapping(
                f.make_element_mapping_payload(
                    scenario.cycle_id,
                    definition["id"],
                    local_system_code=K.LOCAL_SYSTEM_SIS,
                    local_field_path=SIS_LOAD_PATH,
                    value_map=ATTENDANCE_VALUE_MAP,
                ),
                analyst,
            ),
            201,
        )
        assert mapping["status"] == K.MAPPING_PROPOSED

        premature_revision = api.revise_element_mapping(
            mapping["id"],
            f.make_mapping_revision_payload(
                transform_expression="TRIM(x)", value_map=NARROWED_VALUE_MAP
            ),
            analyst,
        )
        validate_error(premature_revision, ApiErrorId.INVALID_MAPPING_STATE, 409)
        unrevised = validate_success(api.get_element_mapping(mapping["id"], steward))
        assert unrevised["status"] == K.MAPPING_PROPOSED
        assert unrevised["revision_round"] == 0
        assert unrevised["local_field_path"] == SIS_LOAD_PATH
        assert_version(unrevised, 1, "mapping")

        validated = validate_success(
            api.validate_element_mapping(
                mapping["id"], f.make_mapping_verdict_payload(K.DECISION_APPROVE), steward
            )
        )
        assert validated["status"] == K.MAPPING_VALIDATED
        assert_null(validated["rejection_reason"], "rejection_reason")
        assert_version(validated, 2, "mapping")

        second_verdict = api.validate_element_mapping(
            mapping["id"], f.make_mapping_verdict_payload(K.DECISION_APPROVE), steward
        )
        validate_error(second_verdict, ApiErrorId.INVALID_MAPPING_STATE, 409)
        terminal = validate_success(api.get_element_mapping(mapping["id"], steward))
        assert terminal["status"] == K.MAPPING_VALIDATED
        assert_version(terminal, 2, "mapping")


class TestTheDataRequestRefusesEveryOutOfOrderStep:
    """One id covers four wrong turns while the legal calls still walk RECEIVED to RELEASED."""

    def test_early_release_late_cell_second_screen_and_second_release_are_all_refused(
        self, api, disclosure
    ):
        """The crosstab is fixed by screening and both terminal steps happen exactly once.

        PRD 3.9: "Cells may be added only while the request is `RECEIVED`; once it has been screened the crosstab is fixed, and a later addition reports `ERR_INVALID_DATA_REQUEST_STATE`."

        PRD 3.9: "Both branches require the request to be `RECEIVED` (else `ERR_INVALID_DATA_REQUEST_STATE`), the cycle to be `FROZEN` or `ARCHIVED` (else `ERR_CYCLE_NOT_FROZEN`), and `cell_count` to be at least 1 (else `ERR_NO_CELLS_TO_SCREEN`)."

        PRD 3.9: "It requires the request to be `SCREENED` (else `ERR_INVALID_DATA_REQUEST_STATE`) and the cycle to be `FROZEN` or `ARCHIVED` (else `ERR_CYCLE_NOT_FROZEN`), and it accepts an optional `release_note`."

        PRD 3.9: "Both branches store the note, increment `version`, and are terminal, as is `REFUSED`."

        Design: Corner/errors/corner_err_data_request_lifecycle_rejects_every_out_of_order_step
        """
        scenario = fx.request_with_cells(
            api,
            "GENDER",
            (("FEMALE", 30),),
            metrics=HEADCOUNT_30,
            record_count=30,
            requester_org=INTERNAL_OFFICE,
            requester_type=K.REQUESTER_INTERNAL,
            requested_metric_key=K.METRIC_TOTAL_HEADCOUNT,
            avoidance_method=K.AVOIDANCE_SMALL_CELL_SUPPRESSION,
            min_cell_size=K.DEFAULT_MIN_CELL_SIZE,
        )
        request_id = scenario.request_id
        cell_id = scenario.cells[0]["id"]

        early = api.release_data_request(
            request_id, disclosure, f.make_release_payload(EARLY_RELEASE_NOTE)
        )
        validate_error(early, ApiErrorId.INVALID_DATA_REQUEST_STATE, 409)
        unscreened = validate_success(api.get_data_request(request_id, disclosure))
        assert_request_counters(unscreened, cell_count=1, status=K.REQUEST_RECEIVED)
        assert_null(unscreened["release_note"], "release_note")
        assert_null(unscreened["screened_at"], "screened_at")

        screened = validate_success(api.screen_data_request(request_id, disclosure))
        assert_request_counters(
            screened,
            cell_count=1,
            released_cell_count=1,
            suppressed_cell_count=0,
            residual_disclosure_risk=False,
            status=K.REQUEST_SCREENED,
        )
        assert_instant_equals(screened["screened_at"], K.CLOCK_AFTER_CENSUS_ECHO, "screened_at")

        late_cell = api.add_disclosure_cell(
            request_id, f.make_disclosure_cell_payload("GENDER", "MALE", 25), disclosure
        )
        validate_error(late_cell, ApiErrorId.INVALID_DATA_REQUEST_STATE, 409)
        fixed = validate_success(api.get_data_request(request_id, disclosure))
        assert_request_counters(fixed, cell_count=1, status=K.REQUEST_SCREENED)

        second_screen = api.screen_data_request(request_id, disclosure)
        validate_error(second_screen, ApiErrorId.INVALID_DATA_REQUEST_STATE, 409)

        released = validate_success(
            api.release_data_request(request_id, disclosure, f.make_release_payload(RELEASE_NOTE))
        )
        assert_request_counters(released, cell_count=1, released_cell_count=1, status=K.REQUEST_RELEASED)
        assert released["release_note"] == RELEASE_NOTE

        second_release = api.release_data_request(
            request_id, disclosure, f.make_release_payload(SECOND_RELEASE_NOTE)
        )
        validate_error(second_release, ApiErrorId.INVALID_DATA_REQUEST_STATE, 409)
        terminal = validate_success(api.get_data_request(request_id, disclosure))
        assert_request_counters(terminal, status=K.REQUEST_RELEASED)
        assert terminal["release_note"] == RELEASE_NOTE

        cell = validate_success(api.get_disclosure_cell(cell_id, disclosure))
        assert_cell(cell, suppression_state=K.CELL_RELEASED, released_count=30, raw_count=30)


class TestFiveDuplicateIdsEachAtItsOwnDeclaredScope:
    """The cycle code, the component, the metric key, the cohort triple and the roster identifier."""

    def test_five_collisions_and_the_two_near_misses_that_must_still_succeed(
        self, api, analyst, registrar
    ):
        """A generic 'already exists' would either collapse the five ids or refuse the near misses.

        PRD 3.1: "The payload carries a `cycle_code` — the human-readable identifier such as `IPEDS-2027`, between 1 and 32 characters, and unique across all cycles under case-sensitive comparison, with a collision reported as `ERR_DUPLICATE_CYCLE_CODE` — together with the `collection_year` the cycle reports on (an integer at least 2000 and at most 2100), the `census_date`, and the `collection_deadline`, which must fall strictly after midnight UTC on the census date."

        PRD 3.3: "Only one component per survey may exist per cycle, so a second attempt at the same pair of `cycle_id` and `component_code` reports `ERR_DUPLICATE_COMPONENT`."

        PRD 3.3: "The pair of `component_id` and `metric_key` must be unique, with a collision reporting `ERR_DUPLICATE_METRIC_KEY`."

        PRD 3.6: "The triple of `cycle_id`, `cohort_type` and `entry_term` must be unique, so a second cohort of the same type for the same term reports `ERR_DUPLICATE_COHORT`."

        PRD 3.6: "The identifier must be unique within the cohort, so a repeat reports `ERR_DUPLICATE_MEMBER`."

        Design: Corner/errors/corner_err_uniqueness_ids_part_one_cycle_component_metric_cohort_member
        """
        scenario = fx.component_on_locked_cycle(api)
        scenario = fx.cohort_on_scenario(api, scenario, fx.roster_of(K.OUTCOME_COMPLETED_150))
        first_cohort_id = scenario.cohort_id

        same_code = api.create_reporting_cycle(
            f.make_reporting_cycle_payload(
                cycle_code=K.CYCLE_CODE,
                collection_year=2028,
                census_date="2027-10-15",
                collection_deadline="2028-02-15T23:59:59Z",
            ),
            registrar,
        )
        validate_error(same_code, ApiErrorId.DUPLICATE_CYCLE_CODE, 409)

        same_component = api.create_survey_component(
            f.make_survey_component_payload(
                scenario.cycle_id, scenario.extract_id, component_code=K.DOMAIN_ENROLLMENT
            ),
            analyst,
        )
        validate_error(same_component, ApiErrorId.DUPLICATE_COMPONENT, 409)

        same_metric_key = api.add_component_metric(
            scenario.component_id,
            f.make_metric_payload(
                metric_key=K.METRIC_TOTAL_HEADCOUNT,
                reported_value=1001,
                prior_year_value=1000,
                source_field_path="sis.enrollment.headcount_v2",
            ),
            analyst,
        )
        validate_error(same_metric_key, ApiErrorId.DUPLICATE_METRIC_KEY, 409)
        metrics, metric_meta = validate_paginated(
            api.list_component_metrics(analyst, component_id=scenario.component_id)
        )
        assert metric_meta["total_count"] == 1, "the refused metric must not have been written"
        assert metrics[0]["reported_value"] == 1000

        same_triple = api.create_cohort(
            scenario.cycle_id,
            f.make_cohort_payload(
                cohort_type=K.COHORT_GRAD_RATE_150,
                entry_term="FALL2020",
                publication_metric_key="GRAD_RATE_150_FALL2020_V2",
            ),
            registrar,
        )
        validate_error(same_triple, ApiErrorId.DUPLICATE_COHORT, 409)

        # Near miss one: the scope is the triple, so a different entry_term is a different cohort.
        second_cohort = validate_success(
            api.create_cohort(
                scenario.cycle_id,
                f.make_cohort_payload(
                    cohort_type=K.COHORT_GRAD_RATE_150,
                    entry_term="FALL2021",
                    publication_metric_key="GRAD_RATE_150_FALL2021",
                ),
                registrar,
            ),
            201,
        )
        assert second_cohort["cohort_type"] == K.COHORT_GRAD_RATE_150
        assert second_cohort["entry_term"] == "FALL2021"

        repeat_member = api.add_cohort_member(
            first_cohort_id,
            f.make_member_payload(
                "S001", entry_status=K.ENTRY_PART_TIME, outcome=K.OUTCOME_STILL_ENROLLED
            ),
            registrar,
        )
        validate_error(repeat_member, ApiErrorId.DUPLICATE_MEMBER, 409)
        assert_cohort_counts(
            validate_success(api.get_cohort(first_cohort_id, registrar)), initial_count=1
        )
        stored = validate_success(api.get_cohort_member(scenario.member("S001")["id"], registrar))
        assert stored["entry_status"] == K.ENTRY_FULL_TIME
        assert stored["outcome"] == K.OUTCOME_COMPLETED_150

        # Near miss two: the roster identifier is unique per cohort, not per cycle.
        seated_again = validate_success(
            api.add_cohort_member(
                second_cohort["id"],
                f.make_member_payload(
                    "S001", entry_status=K.ENTRY_FULL_TIME, outcome=K.OUTCOME_COMPLETED_150
                ),
                registrar,
            ),
            201,
        )
        assert seated_again["student_local_id"] == "S001"
        assert_cohort_counts(
            validate_success(api.get_cohort(second_cohort["id"], registrar)), initial_count=1
        )


class TestTheRemainingFourDuplicateIdsOrderedAroundTheFreeze:
    """The definition pair, the mapping triple, the submission triple and the crosstab cell triple."""

    def test_four_more_collisions_and_the_freeze_that_outranks_the_uniqueness_check(
        self, api, analyst, director, disclosure, steward
    ):
        """Once the cycle is frozen a duplicate mapping cannot even reach its uniqueness check.

        PRD 3.2: "The pair of `definition_code` and `effective_cycle_code` must be unique; a collision reports `ERR_DUPLICATE_DEFINITION`."

        PRD 3.2: "The triple of `cycle_id`, `definition_id` and `local_system_code` must be unique among mappings whose `status` is anything other than `REJECTED`, so a rejected proposal does not block a fresh attempt on the same field; a collision against a live row reports `ERR_DUPLICATE_MAPPING`."

        PRD 3.8: "The triple of `cycle_id`, `target_name` and `metric_key` must be unique among rows whose `status` is not `TRANSMITTED`, so a second draft to the same recipient for the same metric reports `ERR_DUPLICATE_SUBMISSION` while a figure already transmitted leaves the slot free for a corrected resubmission."

        PRD 3.9: "The triple of `request_id`, `dimension_group` and `dimension_key` must be unique, so a repeated category within a dimension reports `ERR_DUPLICATE_CELL`."

        PRD 2.6: "Twelve operations sit in this band: registering a census extract, creating a survey component, adding a reported metric, correcting a reported metric, preparing a component, certifying a component, defining a cohort, adding a cohort member, patching a member's outcome, proposing an element mapping, validating an element mapping, and revising a rejected element mapping."

        PRD 2.12: "Checks are evaluated in strict ascending priority and **the first violated rule decides the response; no later rule is evaluated**:"

        Design: Corner/errors/corner_err_uniqueness_ids_part_two_definition_mapping_submission_cell
        """
        scenario = fx.component_on_locked_cycle(api)
        definition = fx.create_definition(
            api,
            steward,
            definition_code=ATTENDANCE_DEFINITION,
            survey_component=K.DOMAIN_ENROLLMENT,
            value_domain=ATTENDANCE_DOMAIN,
            unit_of_measure="CODE",
            required=False,
        )
        mapping = validate_success(
            api.propose_element_mapping(
                f.make_element_mapping_payload(
                    scenario.cycle_id,
                    definition["id"],
                    local_system_code=K.LOCAL_SYSTEM_SIS,
                    local_field_path=SIS_LOAD_PATH,
                    value_map=ATTENDANCE_VALUE_MAP,
                ),
                analyst,
            ),
            201,
        )
        validate_success(
            api.create_external_submission(
                f.make_external_submission_payload(
                    scenario.cycle_id,
                    scenario.component_id,
                    target_type=K.TARGET_STATE,
                    target_name=STATE_BOARD,
                    metric_key=K.METRIC_TOTAL_HEADCOUNT,
                    reported_value=1000,
                ),
                analyst,
            ),
            201,
        )

        same_definition_pair = api.create_federal_definition(
            f.make_federal_definition_payload(
                definition_code=ATTENDANCE_DEFINITION,
                survey_component=K.DOMAIN_HR,
                value_domain=["FULL_TIME"],
                unit_of_measure="CODE",
                required=True,
            ),
            steward,
        )
        validate_error(same_definition_pair, ApiErrorId.DUPLICATE_DEFINITION, 409)

        same_mapping_triple = api.propose_element_mapping(
            f.make_element_mapping_payload(
                scenario.cycle_id,
                definition["id"],
                local_system_code=K.LOCAL_SYSTEM_SIS,
                local_field_path=SIS_LOAD_PATH_ALT,
                value_map=NARROWED_VALUE_MAP,
            ),
            analyst,
        )
        validate_error(same_mapping_triple, ApiErrorId.DUPLICATE_MAPPING, 409)
        unchanged = validate_success(api.get_element_mapping(mapping["id"], steward))
        assert unchanged["local_field_path"] == SIS_LOAD_PATH
        assert_version(unchanged, 1, "mapping")

        # The triple includes local_system_code, so a second source system is a fresh mapping.
        hr_mapping = validate_success(
            api.propose_element_mapping(
                f.make_element_mapping_payload(
                    scenario.cycle_id,
                    definition["id"],
                    local_system_code=K.LOCAL_SYSTEM_HR,
                    local_field_path=HR_LOAD_PATH,
                    value_map=HR_VALUE_MAP,
                ),
                analyst,
            ),
            201,
        )
        assert hr_mapping["local_system_code"] == K.LOCAL_SYSTEM_HR
        assert hr_mapping["status"] == K.MAPPING_PROPOSED

        same_submission_triple = api.create_external_submission(
            f.make_external_submission_payload(
                scenario.cycle_id,
                scenario.component_id,
                target_type=K.TARGET_RANKING,
                target_name=STATE_BOARD,
                metric_key=K.METRIC_TOTAL_HEADCOUNT,
                reported_value=1005,
            ),
            analyst,
        )
        validate_error(same_submission_triple, ApiErrorId.DUPLICATE_SUBMISSION, 409)

        validate_success(api.prepare_component(scenario.component_id, analyst))
        certified = validate_success(
            api.certify_component(
                scenario.component_id,
                f.make_certification_payload(CERTIFICATION_STATEMENT),
                director,
            )
        )
        assert_component_status(
            certified, prep_status=K.PREP_CERTIFIED, edit_status=K.EDIT_CLEARED, fatal_open_count=0
        )
        frozen = validate_success(api.freeze_cycle(scenario.cycle_id, director))
        assert_cycle_posture(frozen, K.POSTURE_FROZEN)

        # The very same duplicate triple, retried after the freeze, never reaches priority 27.
        after_freeze = api.propose_element_mapping(
            f.make_element_mapping_payload(
                scenario.cycle_id,
                definition["id"],
                local_system_code=K.LOCAL_SYSTEM_SIS,
                local_field_path=SIS_LOAD_PATH_ALT,
                value_map=NARROWED_VALUE_MAP,
            ),
            analyst,
        )
        validate_error(after_freeze, ApiErrorId.CYCLE_FROZEN, 409)

        request = validate_success(
            api.create_data_request(
                scenario.cycle_id,
                f.make_data_request_payload(
                    requester_org=INTERNAL_OFFICE,
                    requester_type=K.REQUESTER_INTERNAL,
                    requested_metric_key=K.METRIC_TOTAL_HEADCOUNT,
                ),
                disclosure,
            ),
            201,
        )
        female = validate_success(
            api.add_disclosure_cell(
                request["id"], f.make_disclosure_cell_payload("GENDER", "FEMALE", 540), disclosure
            ),
            201,
        )
        assert_cell(female, suppression_state=K.CELL_PENDING, released_count=None, raw_count=540)

        same_cell_triple = api.add_disclosure_cell(
            request["id"], f.make_disclosure_cell_payload("GENDER", "FEMALE", 541), disclosure
        )
        validate_error(same_cell_triple, ApiErrorId.DUPLICATE_CELL, 409)
        kept = validate_success(api.get_disclosure_cell(female["id"], disclosure))
        assert_cell(kept, suppression_state=K.CELL_PENDING, raw_count=540)
        assert_request_counters(
            validate_success(api.get_data_request(request["id"], disclosure)), cell_count=1
        )

        # dimension_key is part of the scope, so the other category is admitted.
        validate_success(
            api.add_disclosure_cell(
                request["id"], f.make_disclosure_cell_payload("GENDER", "MALE", 460), disclosure
            ),
            201,
        )
        assert_request_counters(
            validate_success(api.get_data_request(request["id"], disclosure)), cell_count=2
        )
