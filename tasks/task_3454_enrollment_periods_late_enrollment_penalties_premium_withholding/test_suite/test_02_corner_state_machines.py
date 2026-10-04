"""Corner coverage: state-machine terminal states, cycles, and clock tracking."""

from test_helpers import (
    APPEALS_OFFICER_HEADERS,
    ApiErrorId,
    adjudicate_appeal,
    adjust_arrangement,
    advance_clock_and_run_cycle,
    appeal_decision_payload,
    create_employer_coverage,
    list_appeals,
    list_enrollment_periods,
    list_premium_determinations,
    make_beneficiary_headers,
    read_enrollment,
    register_beneficiary,
    set_clock,
    setup_appeal_under_review,
    setup_beneficiary_with_enrollment,
    setup_terminated_enrollment_interval,
    setup_withholding_shortfall,
    terminate_enrollment,
    validate_error,
    verify_employer_coverage,
)


class TestCoverageEnrollmentTerminalStates:
    def test_terminate_already_terminated_enrollment_rejected(self, client):
        """PRD section 3.2: "Both `TERMINATED` and `CANCELLED` are terminal:
        any further transition attempt on them — including a second
        termination — fails with `ERR_INVALID_STATE`." PRD section 3.2:
        "terminating an `ACTIVE` enrollment moves it to `TERMINATED` with
        `end_month` set to the clock month, making the clock month the first
        uncovered month."

        Design: Corner/state_machines/terminate_already_terminated_enrollment_rejected
        """
        beneficiary, enrollment = setup_terminated_enrollment_interval(client)
        assert enrollment["enrollment_status"] == "TERMINATED"
        assert enrollment["end_month"] == "2026-06"
        assert enrollment["collection_status"] == "CLOSED"

        response = client.terminate_enrollment(
            enrollment["id"], headers=make_beneficiary_headers(beneficiary["id"])
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        reread = read_enrollment(client, enrollment["id"])
        assert reread["enrollment_status"] == "TERMINATED"
        assert reread["end_month"] == "2026-06", "no side effects on rejection"

    def test_terminate_pending_enrollment_cancels_without_end_month(self, client):
        """PRD section 3.2: "Terminating a `PENDING` enrollment moves it to
        `CANCELLED` and leaves `end_month` null — the coverage never began".
        PRD section 3.2: "enrolling before `T` yields an effective month of
        `T` itself" (born 1961-06-12, attainment 2026-06, enrolled at clock
        month 2026-05, so the enrollment waits PENDING for 2026-06).

        Design: Corner/state_machines/terminate_pending_enrollment_cancels_without_end_month
        """
        beneficiary, enrollment = setup_beneficiary_with_enrollment(client)
        assert enrollment["enrollment_status"] == "PENDING"
        assert enrollment["effective_month"] == "2026-06"

        terminated = terminate_enrollment(client, enrollment)
        assert terminated["enrollment_status"] == "CANCELLED"
        assert terminated["end_month"] is None
        assert terminated["collection_status"] == "CLOSED"


class TestAppealCaseTerminalStates:
    def test_adjudicate_terminal_appeal_rejected(self, client):
        """PRD section 3.6: "the case must be `UNDER_REVIEW`, otherwise
        `ERR_APPEAL_NOT_REVIEWABLE`." PRD section 3.6: "`APPROVED` and
        `DENIED` are both terminal."

        Design: Corner/state_machines/adjudicate_terminal_appeal_rejected
        """
        beneficiary, determination, appeal = setup_appeal_under_review(client)
        denied = adjudicate_appeal(client, appeal, "DENIED")
        assert denied["status"] == "DENIED"

        response = client.adjudicate_appeal(
            appeal["id"],
            appeal_decision_payload("APPROVED"),
            headers=APPEALS_OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_APPEAL_NOT_REVIEWABLE)

        appeals = list_appeals(client, beneficiary)
        assert appeals[0]["status"] == "DENIED", "the appeal stays DENIED"
        determinations = list_premium_determinations(client, beneficiary)
        assert len(determinations) == 1, "a rejected adjudication creates nothing"
        assert determinations[0]["id"] == determination["id"]
        assert determinations[0]["status"] == "FINAL"


class TestEmployerCoverageVerificationCycle:
    def test_employer_record_reverify_after_rejection_cycle(self, client):
        """PRD section 3.3: "a `REJECTED` record may later be verified — the
        machine is cyclic on that resubmission path — but a `REJECTED`
        decision is only valid from `UNVERIFIED`."

        Design: Corner/state_machines/employer_record_reverify_after_rejection_cycle
        """
        beneficiary = register_beneficiary(client, date_of_birth="1961-03-10")
        record = create_employer_coverage(client, beneficiary)
        assert record["verification_status"] == "UNVERIFIED"

        rejected = verify_employer_coverage(client, record["id"], decision="REJECTED")
        assert rejected["verification_status"] == "REJECTED"

        verified = verify_employer_coverage(client, record["id"], decision="VERIFIED")
        assert verified["verification_status"] == "VERIFIED"


class TestWithholdingArrangementResume:
    def test_withholding_resume_blocked_when_benefit_still_insufficient(self, client):
        """PRD section 3.7: "The adjustment resumes a `SUSPENDED` arrangement —
        moving it back to `ACTIVE` — exactly when the new benefit amount covers
        the sum of the current monthly premiums of the beneficiary's `ACTIVE`
        billable (`PART_B` and `PART_D`) enrollments; if it does not, the
        arrangement stays `SUSPENDED` without error."

        Design: Corner/state_machines/withholding_resume_blocked_when_benefit_still_insufficient
        """
        state = setup_withholding_shortfall(client)
        assert state["arrangement"]["status"] == "SUSPENDED"

        adjusted = adjust_arrangement(client, state["arrangement"]["id"], 20000)
        assert adjusted["monthly_benefit_cents"] == 20000
        assert adjusted["status"] == "SUSPENDED", (
            "20000 < 21950 total monthly premium: resume precondition fails "
            "without error"
        )


class TestEnrollmentPeriodClockTracking:
    def test_enrollment_period_status_tracks_clock_across_cycles(self, client):
        """PRD section 3.2: "A window is `UPCOMING` before its first month,
        flips from `UPCOMING` to `OPEN` once the clock month falls within the
        inclusive range from `window_start_month` to `window_end_month`, and
        becomes `EXPIRED` — from either `UPCOMING` or `OPEN` — once the clock
        month passes `window_end_month`." PRD section 3.2: "A stored window's
        `status` is clock-derived and is recomputed at row creation and on
        every monthly cycle."

        Design: Corner/state_machines/enrollment_period_status_tracks_clock_across_cycles
        """
        set_clock(client, "2026-06-01T00:00:00Z")
        beneficiary = register_beneficiary(client, date_of_birth="1961-12-14")
        periods = list_enrollment_periods(client, beneficiary)
        assert periods[0]["window_type"] == "IEP"
        assert periods[0]["status"] == "UPCOMING"

        advance_clock_and_run_cycle(client, "2026-10-05T00:00:00Z")
        periods = list_enrollment_periods(client, beneficiary)
        assert periods[0]["status"] == "OPEN"

        advance_clock_and_run_cycle(client, "2027-05-05T00:00:00Z")
        periods = list_enrollment_periods(client, beneficiary)
        assert periods[0]["status"] == "EXPIRED"
