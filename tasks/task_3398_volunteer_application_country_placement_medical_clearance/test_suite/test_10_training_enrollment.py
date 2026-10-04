"""Training enrollment: the compliance gate (clearances), the pinned-program
and capacity gates, the assessment lifecycle, and enrollment state guards."""

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_START,
    TEST_USERS,
    adjudicate_background,
    api_client,
    assess_enrollment,
    clear_legal,
    clear_medical,
    create_accepted_scenario,
    create_applicant,
    create_country_program,
    create_enrolled_scenario,
    create_fully_cleared_scenario,
    create_medical_clearance,
    create_program_with_opening,
    create_training_cohort,
    determine_medical_clearance,
    ensure_cohort_in_session,
    get_application,
    get_cohort,
    run_applicant_to_accepted,
    run_applicant_to_enrolled,
    run_applicant_to_fully_cleared,
    set_clock,
    validate_error,
    validate_success,
)

PLACER = TEST_USERS["placement_officer_headers"]
TRAINER = TEST_USERS["training_director_headers"]


def _enroll_error(app_id, cohort_id, expected_error, expected_status):
    return validate_error(
        api_client.create_training_enrollment(
            {"application_id": app_id, "training_cohort_id": cohort_id}, PLACER),
        expected_error, expected_status)


def _enrollments_of(app_id):
    return validate_success(
        api_client.list_training_enrollments(
            PLACER, params={"application_id": app_id}), 200)


class TestComplianceGate:
    def test_enrollment_gated_by_legal_clearance_pending_suitability(self):
        """PRD §3.7: "The application must be `ACCEPTED`
        (`ERR_INVALID_APPLICATION_STATE` otherwise) and fully cleared — its
        medical clearance `CLEARED` or `CLEARED_WITH_ACCOMMODATION` and its
        legal clearance's `overall_status` `CLEARED`, otherwise
        `ERR_CLEARANCES_NOT_CLEARED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/enrollment_gated_by_legal_clearance_state
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_accepted_scenario()
        app_id = scenario["application"]["id"]
        ana = scenario["applicant"]
        # Medical cleared; legal background adjudicated but suitability
        # still PENDING, so overall_status is PENDING.
        clear_medical(app_id, ana["id"])
        adjudicate_background(scenario["legal_clearance"]["id"], outcome="CLEAR")

        cohort = create_training_cohort(scenario["program"]["id"])
        _enroll_error(app_id, cohort["id"],
                      ApiErrorId.ERR_CLEARANCES_NOT_CLEARED, 422)
        assert _enrollments_of(app_id) == []
        assert get_cohort(cohort["id"])["enrolled_count"] == 0
        assert get_application(app_id)["status"] == "ACCEPTED"

    def test_enrollment_gated_by_legal_clearance_fully_pending(self):
        """PRD §3.7: "The application must be `ACCEPTED`
        (`ERR_INVALID_APPLICATION_STATE` otherwise) and fully cleared — its
        medical clearance `CLEARED` or `CLEARED_WITH_ACCOMMODATION` and its
        legal clearance's `overall_status` `CLEARED`, otherwise
        `ERR_CLEARANCES_NOT_CLEARED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/enrollment_gated_by_legal_clearance_state
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_accepted_scenario()
        app_id = scenario["application"]["id"]
        ana = scenario["applicant"]
        # Medical cleared; neither legal dimension touched (both PENDING).
        clear_medical(app_id, ana["id"])
        legal = scenario["legal_clearance"]
        assert legal["overall_status"] == "PENDING"

        cohort = create_training_cohort(scenario["program"]["id"])
        _enroll_error(app_id, cohort["id"],
                      ApiErrorId.ERR_CLEARANCES_NOT_CLEARED, 422)
        assert _enrollments_of(app_id) == []
        assert get_cohort(cohort["id"])["enrolled_count"] == 0
        assert get_application(app_id)["status"] == "ACCEPTED"

    def test_enrollment_compliance_check_beats_capacity_check(self):
        """PRD §2.9: "Compliance gates run seventh —
        `ERR_CLEARANCES_NOT_CLEARED`, `ERR_SUITABILITY_SELF_APPROVAL`,
        `ERR_ACCOMMODATION_DETERMINATION_INVALID`, and
        `ERR_DENTAL_TREATMENT_PENDING`, all HTTP 422 — followed by
        business-constraint gates eighth and the temporal gate on service
        completion (`ERR_SERVICE_TERM_NOT_REACHED`) ninth."
        PRD §3.7: "The cohort must belong to the invitation's
        `pinned_country_program_id` (`ERR_COHORT_PROGRAM_MISMATCH`, HTTP
        422), must have `enrolled_count` still strictly below `capacity`
        (`ERR_COHORT_CAPACITY_EXCEEDED`, HTTP 409), and must still be
        `SCHEDULED`."

        Design: Difficulty/priority_pair_validation_conflict/enrollment_compliance_check_beats_capacity_check
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 2})
        cohort = create_training_cohort(program["id"], capacity=1)
        # Ana fills the cohort's only seat.
        ana = create_applicant()
        run_applicant_to_enrolled(ana, opening, cohort)
        assert get_cohort(cohort["id"])["enrolled_count"] == 1

        # Bob violates BOTH the compliance gate (legal PENDING) and the
        # capacity gate (cohort full); compliance must be reported.
        bob = create_applicant()
        bob_bundle = run_applicant_to_accepted(bob, opening)
        clear_medical(bob_bundle["application"]["id"], bob["id"])
        _enroll_error(bob_bundle["application"]["id"], cohort["id"],
                      ApiErrorId.ERR_CLEARANCES_NOT_CLEARED, 422)
        assert _enrollments_of(bob_bundle["application"]["id"]) == []
        assert get_cohort(cohort["id"])["enrolled_count"] == 1
        assert get_application(bob_bundle["application"]["id"])["status"] == "ACCEPTED"

    def test_enrollment_compliance_beats_capacity_with_deferred_medical(self):
        """PRD §2.9: "Compliance gates run seventh —
        `ERR_CLEARANCES_NOT_CLEARED`, `ERR_SUITABILITY_SELF_APPROVAL`,
        `ERR_ACCOMMODATION_DETERMINATION_INVALID`, and
        `ERR_DENTAL_TREATMENT_PENDING`, all HTTP 422 — followed by
        business-constraint gates eighth and the temporal gate on service
        completion (`ERR_SERVICE_TERM_NOT_REACHED`) ninth."
        PRD §3.7: "The application must be `ACCEPTED`
        (`ERR_INVALID_APPLICATION_STATE` otherwise) and fully cleared — its
        medical clearance `CLEARED` or `CLEARED_WITH_ACCOMMODATION` and its
        legal clearance's `overall_status` `CLEARED`, otherwise
        `ERR_CLEARANCES_NOT_CLEARED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/enrollment_compliance_check_beats_capacity_check
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 2})
        cohort = create_training_cohort(program["id"], capacity=1)
        ana = create_applicant()
        run_applicant_to_enrolled(ana, opening, cohort)
        assert get_cohort(cohort["id"])["enrolled_count"] == 1

        # Bob: legal fully CLEARED, but his medical clearance is DEFERRED
        # (not a cleared outcome) — compliance fails and beats capacity.
        bob = create_applicant()
        bob_bundle = run_applicant_to_accepted(bob, opening)
        clear_legal(bob_bundle["legal_clearance"]["id"])
        clearance = create_medical_clearance(
            bob_bundle["application"]["id"], bob["id"])
        determine_medical_clearance(clearance["id"], determination="DEFERRED")
        _enroll_error(bob_bundle["application"]["id"], cohort["id"],
                      ApiErrorId.ERR_CLEARANCES_NOT_CLEARED, 422)
        assert get_cohort(cohort["id"])["enrolled_count"] == 1
        assert get_application(bob_bundle["application"]["id"])["status"] == "ACCEPTED"

    def test_enrollment_requires_medical_clearance_variant(self):
        """PRD §3.7: "The application must be `ACCEPTED`
        (`ERR_INVALID_APPLICATION_STATE` otherwise) and fully cleared — its
        medical clearance `CLEARED` or `CLEARED_WITH_ACCOMMODATION` and its
        legal clearance's `overall_status` `CLEARED`, otherwise
        `ERR_CLEARANCES_NOT_CLEARED` (HTTP 422)."

        Design: Corner/validations/enrollment_requires_medical_clearance_variant
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_accepted_scenario()
        app_id = scenario["application"]["id"]
        # Legal fully CLEARED; no medical clearance was ever filed.
        clear_legal(scenario["legal_clearance"]["id"])

        cohort = create_training_cohort(scenario["program"]["id"])
        _enroll_error(app_id, cohort["id"],
                      ApiErrorId.ERR_CLEARANCES_NOT_CLEARED, 422)
        assert _enrollments_of(app_id) == []
        assert get_cohort(cohort["id"])["enrolled_count"] == 0
        assert get_application(app_id)["status"] == "ACCEPTED"


class TestCohortGates:
    def test_enrollment_cohort_program_mismatch(self):
        """PRD §3.7: "The cohort must belong to the invitation's
        `pinned_country_program_id` (`ERR_COHORT_PROGRAM_MISMATCH`, HTTP
        422), must have `enrolled_count` still strictly below `capacity`
        (`ERR_COHORT_CAPACITY_EXCEEDED`, HTTP 409), and must still be
        `SCHEDULED`."
        PRD §2.6: "Every downstream consumer evaluates against the snapshot:
        medical clearance reviews measure declared conditions against the
        `pinned_country_medical_tier` even if the live program tier has since
        changed, and training enrollment requires the cohort to belong to the
        `pinned_country_program_id` rather than to whatever program the
        opening might later be associated with."

        Design: Corner/validations/enrollment_cohort_program_mismatch
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_fully_cleared_scenario()
        app_id = scenario["application"]["id"]
        # A cohort in a different program than the invitation's pinned one.
        other_program = create_country_program(country_code="EC", name="Ecuador",
                                               medical_support_tier=2)
        cohort_ec = create_training_cohort(other_program["id"])

        _enroll_error(app_id, cohort_ec["id"],
                      ApiErrorId.ERR_COHORT_PROGRAM_MISMATCH, 422)
        assert _enrollments_of(app_id) == []
        assert get_cohort(cohort_ec["id"])["enrolled_count"] == 0
        assert get_application(app_id)["status"] == "ACCEPTED"

    def test_cohort_capacity_exceeded_pure(self):
        """PRD §3.7: "The cohort must belong to the invitation's
        `pinned_country_program_id` (`ERR_COHORT_PROGRAM_MISMATCH`, HTTP
        422), must have `enrolled_count` still strictly below `capacity`
        (`ERR_COHORT_CAPACITY_EXCEEDED`, HTTP 409), and must still be
        `SCHEDULED`."
        PRD §3.7: "Success creates the enrollment in `ENROLLED` with
        `assessment_attempts` at zero and all three component scores unset,
        increments the cohort's `enrolled_count`, and moves the application
        from `ACCEPTED` to `CLEARED_TO_DEPART`."

        Design: Corner/validations/cohort_capacity_exceeded_pure
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 2})
        cohort = create_training_cohort(program["id"], capacity=1)
        ana = create_applicant()
        run_applicant_to_enrolled(ana, opening, cohort)
        assert get_cohort(cohort["id"])["enrolled_count"] == 1

        # Bob passes the compliance gate (both clearances CLEARED); only the
        # capacity gate can fire.
        bob = create_applicant()
        bob_bundle = run_applicant_to_fully_cleared(bob, opening)
        _enroll_error(bob_bundle["application"]["id"], cohort["id"],
                      ApiErrorId.ERR_COHORT_CAPACITY_EXCEEDED, 409)
        assert _enrollments_of(bob_bundle["application"]["id"]) == []
        assert get_cohort(cohort["id"])["enrolled_count"] == 1
        assert get_application(bob_bundle["application"]["id"])["status"] == "ACCEPTED"


class TestAssessmentLifecycle:
    def test_training_fail_remediate_second_fail_separates(self):
        """PRD §3.7: "Passing requires the language score to meet or exceed
        the cohort program's `language_threshold_score` and both the
        technical and cultural scores to reach at least 2.5; any component
        short of its threshold fails the attempt."
        PRD §3.7: "A `FAILED` enrollment may be moved into `REMEDIATION` —
        remediation from any other state fails with
        `ERR_ENROLLMENT_NOT_ASSESSABLE` — which grants a second and final
        attempt: a pass from `REMEDIATION` promotes to `PASSED`, while a
        second consecutive failed assessment separates the trainee.
        Separation moves the enrollment to `SEPARATED` and the application to
        `SEPARATED` (terminal), rescinds the accepted invitation with the
        usual seat release and `FILLED`-to-`OPEN` reopening, and decrements
        the cohort's `enrolled_count`."

        Design: Corner/state_machines/training_fail_remediate_second_fail_separates
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_enrolled_scenario()
        cohort = scenario["cohort"]
        enrollment = scenario["enrollment"]
        app_id = scenario["application"]["id"]
        ensure_cohort_in_session(cohort["id"])
        assert get_application(app_id)["status"] == "IN_TRAINING"

        # First attempt: language 2.0 is short of the 2.5 threshold.
        failed = assess_enrollment(
            enrollment["id"], language_score=2.0, technical_score=3.0,
            cultural_score=3.0)
        assert failed["status"] == "FAILED"
        assert failed["assessment_attempts"] == 1

        remediated = validate_success(
            api_client.remediate_training_enrollment(enrollment["id"], TRAINER),
            200)
        assert remediated["status"] == "REMEDIATION"

        # Second consecutive failure separates the trainee.
        separated = assess_enrollment(
            enrollment["id"], language_score=2.0, technical_score=3.0,
            cultural_score=3.0)
        assert separated["status"] == "SEPARATED"
        assert separated["assessment_attempts"] == 2

        # The separation cascade.
        assert get_application(app_id)["status"] == "SEPARATED"
        invitation = validate_success(
            api_client.get_invitation(scenario["invitation"]["id"], PLACER), 200)
        assert invitation["status"] == "RESCINDED"
        opening_now = validate_success(
            api_client.get_assignment_opening(scenario["opening"]["id"], PLACER), 200)
        assert opening_now["seats_committed"] == 0
        assert get_cohort(cohort["id"])["enrolled_count"] == 0

    def test_enrollment_action_state_guards(self):
        """PRD §3.7: "Assessment belongs to the `TrainingDirector` and to a
        live classroom: it requires the cohort `IN_SESSION` (`ERR_INVALID_STATE`
        otherwise) and the enrollment `ENROLLED` or `REMEDIATION`
        (`ERR_ENROLLMENT_NOT_ASSESSABLE` otherwise)."
        PRD §3.7: "A `TrainingDirector` swears in a `PASSED` enrollment — any
        other state fails with `ERR_ENROLLMENT_NOT_ASSESSABLE` — which creates
        the volunteer's service record: `service_start_date` read from the
        logical clock, `expected_completion_date` exactly 810 days later,
        status `ACTIVE`, and `application_id`, `assignment_opening_id`, and
        `country_program_id` copied from the accepted invitation and its
        pinned program."
        PRD §3.7: "A `FAILED` enrollment may be moved into `REMEDIATION` —
        remediation from any other state fails with
        `ERR_ENROLLMENT_NOT_ASSESSABLE` — which grants a second and final
        attempt: a pass from `REMEDIATION` promotes to `PASSED`, while a
        second consecutive failed assessment separates the trainee."

        Design: Corner/state_machines/enrollment_action_state_guards
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_enrolled_scenario()
        cohort = scenario["cohort"]
        enrollment = scenario["enrollment"]
        app_id = scenario["application"]["id"]
        # Clock is still 2026-09-01: the cohort is SCHEDULED, not IN_SESSION.
        assert get_cohort(cohort["id"])["status"] == "SCHEDULED"

        # Assess is blocked by the cohort state guard.
        validate_error(
            api_client.assess_training_enrollment(
                enrollment["id"],
                {"language_score": 3.0, "technical_score": 3.0,
                 "cultural_score": 3.0},
                TRAINER),
            ApiErrorId.ERR_INVALID_STATE, 409)
        # Swear-in requires PASSED; remediate requires FAILED.
        validate_error(
            api_client.swear_in_training_enrollment(enrollment["id"], TRAINER),
            ApiErrorId.ERR_ENROLLMENT_NOT_ASSESSABLE, 409)
        validate_error(
            api_client.remediate_training_enrollment(enrollment["id"], TRAINER),
            ApiErrorId.ERR_ENROLLMENT_NOT_ASSESSABLE, 409)

        current = validate_success(
            api_client.get_training_enrollment(enrollment["id"], TRAINER), 200)
        assert current["status"] == "ENROLLED"
        assert current["assessment_attempts"] == 0
        assert get_cohort(cohort["id"])["enrolled_count"] == 1
        assert get_application(app_id)["status"] == "CLEARED_TO_DEPART"
