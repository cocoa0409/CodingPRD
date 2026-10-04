"""Transition plans: conditional auto-create, hire inheritance, bubble-up,
tiered allowances, service window expiry."""
from test_helpers import (
    MANAGER,
    SPECIALIST,
    ApiErrorId,
    api_client,
    activate_placement,
    assign_applicant,
    create_center,
    create_employer_agreement,
    create_trade_program,
    enroll_applicant,
    fetch_transition_plan,
    make_eligible_applicant,
    propose_placement,
    record_hours,
    record_service,
    set_clock,
    setup_enrolled_student,
    transition_placement,
    validate_error,
    validate_success,
)


class TestConditionalPlanCreation:
    def test_separate_creates_pending_plan_with_twelve_month_window(self):
        """PRD section 3.7: "The plan records the separation_date as the
        logical-clock date the enrollment went terminal and sets expires_at
        twelve months after that date, which is when the service window
        closes."

        Design: Corner/state_machines/unenroll_creates_no_plan_but_separate_does
        """
        bundle = setup_enrolled_student(center_name="Plan Center", capacity=5)
        enrollment = bundle["enrollment"]
        validate_success(
            api_client.transition_enrollment(
                enrollment["id"], {"action": "separate", "reason": "MEDICAL"},
                MANAGER,
            ),
            200,
        )
        plan = fetch_transition_plan(enrollment["id"])
        assert plan is not None
        assert plan["status"] == "ACTIVE"
        assert plan["separation_date"] == "2026-09-01"
        assert plan["expires_at"] == "2027-09-01"
        assert plan["job_placement_status"] == "PENDING"
        assert plan["housing_status"] == "PENDING"
        assert plan["transportation_status"] == "PENDING"

    def test_unenroll_creates_no_plan(self):
        """PRD section 3.7: "Fetching a student's plan returns an array of zero
        or one entries — zero while the enrollment is still active or exited
        via unenrollment."
        PRD section 3.3: "Unenrolling with a reason lands the enrollment in
        UNENROLLED: it stamps exit_date and exit_reason, releases the seat
        with the same FULL-to-OPEN flip, terminates active dormitory rows the
        same way, flips the applicant to RELEASED — and creates no transition
        plan."

        Design: Corner/state_machines/unenroll_creates_no_plan_but_separate_does
        """
        bundle = setup_enrolled_student(center_name="Plan Center", capacity=5)
        enrollment = bundle["enrollment"]
        validate_success(
            api_client.transition_enrollment(
                enrollment["id"],
                {"action": "unenroll", "reason": "WITHDRAWN"},
                MANAGER,
            ),
            200,
        )
        rows = validate_success(
            api_client.get_transition_plan(enrollment["id"], SPECIALIST)
        )
        assert rows == []


class TestHireInheritance:
    def test_converted_hire_initializes_job_track(self):
        """PRD section 3.3: "when a completed work placement flagged
        converted_to_hire exists for the enrollment, the plan's job track
        initializes already COMPLETED with job_starting_wage_cents taken from
        the placement's hire_wage_cents, and otherwise all three tracks start
        PENDING."

        Design: Corner/state_machines/hire_conversion_initializes_plan_job_track
        """
        set_clock("2026-08-20T00:00:00Z")
        bundle = setup_enrolled_student(center_name="Hire Center")
        enrollment = bundle["enrollment"]
        agreement = create_employer_agreement(employer_name="HireCo")
        placement = propose_placement(enrollment["id"], agreement["id"],
                                      hourly_wage_cents=130000)
        activate_placement(placement["id"])
        set_clock("2026-09-01T00:00:00Z")
        for day in range(20, 32):  # 2026-08-20 .. 2026-08-31 at 10 h/day
            record_hours(placement["id"], f"2026-08-{day}", 10, verified=True)
        completed = transition_placement(
            placement["id"], "complete", converted_to_hire=True,
            hire_wage_cents=160000,
        )
        assert completed["status"] == "COMPLETED"
        validate_success(
            api_client.transition_enrollment(
                enrollment["id"], {"action": "complete"}, MANAGER
            ),
            200,
        )
        plan = fetch_transition_plan(enrollment["id"])
        assert plan is not None
        assert plan["job_placement_status"] == "COMPLETED"
        assert plan["job_starting_wage_cents"] == 160000
        assert plan["housing_status"] == "PENDING"
        assert plan["transportation_status"] == "PENDING"
        assert plan["status"] == "ACTIVE"


class TestBubbleUp:
    def _graduate_plan(self):
        bundle = setup_enrolled_student(center_name="Bubble Center")
        enrollment = bundle["enrollment"]
        validate_success(
            api_client.transition_enrollment(
                enrollment["id"], {"action": "complete"}, MANAGER
            ),
            200,
        )
        plan = fetch_transition_plan(enrollment["id"])
        assert plan is not None
        return plan

    def test_plan_stays_active_until_last_track_leaves_pending(self):
        """PRD section 3.7: "The plan's overall status is computed on read,
        never stored: COMPLETED once all three tracks sit in COMPLETED or
        WAIVED; otherwise EXPIRED once the logical clock date passes expires_at
        while any track is still PENDING; otherwise ACTIVE." and "the status
        is re-evaluated on every track mutation."

        Design: Corner/state_machines/plan_bubble_up_completes_after_last_track
        """
        plan = self._graduate_plan()
        after_job = record_service(plan["id"], "JOB_PLACEMENT", "COMPLETED",
                                   starting_wage_cents=160000)
        assert after_job["status"] == "ACTIVE"
        assert after_job["job_starting_wage_cents"] == 160000
        after_housing = record_service(plan["id"], "HOUSING", "COMPLETED")
        assert after_housing["status"] == "ACTIVE"
        after_transport = record_service(plan["id"], "TRANSPORTATION",
                                         "COMPLETED", distance_miles=30)
        assert after_transport["status"] == "COMPLETED"

    def test_allowances_materialize_on_completing_writes(self):
        """PRD section 3.7: "A completed housing track entitles the plan to a
        flat 50000-cent stipend: housing_stipend_cents reads 50000 once the
        track is COMPLETED and 0 before." and "more than 25 but no more than
        100 miles pays 7500 cents".

        Design: Corner/state_machines/plan_bubble_up_completes_after_last_track
        """
        plan = self._graduate_plan()
        assert plan["housing_stipend_cents"] == 0
        assert plan["transport_allowance_cents"] == 0
        record_service(plan["id"], "JOB_PLACEMENT", "COMPLETED",
                       starting_wage_cents=160000)
        after_housing = record_service(plan["id"], "HOUSING", "COMPLETED")
        assert after_housing["housing_stipend_cents"] == 50000
        after_transport = record_service(plan["id"], "TRANSPORTATION",
                                         "COMPLETED", distance_miles=30)
        assert after_transport["transport_allowance_cents"] == 7500


class TestTransportTiers:
    def _graduate_plans(self):
        """Three COMPLETED graduates at ONE center (design recipe): a fresh
        center per graduate would tie the §3.2 ranking (all scores equal once
        completion releases the seat) and the created_at tie-break would send
        later applicants to the oldest center, not their own."""
        center = create_center(name="Tier Center", total_beds=4)
        program = create_trade_program(center["id"], capacity=10)
        plans = {}
        for name, barrier in (("T25", "FOSTER_CARE"), ("T100", "HOMELESS"),
                              ("T101", "OFFENDER")):
            applicant, _case = make_eligible_applicant(
                full_name=name, barrier_flags=[barrier],
            )
            assign_applicant(applicant)
            enrollment = enroll_applicant(applicant["id"], program["id"])
            validate_success(
                api_client.transition_enrollment(
                    enrollment["id"], {"action": "complete"}, MANAGER
                ),
                200,
            )
            plans[name] = fetch_transition_plan(enrollment["id"])
        return plans

    def test_tier_boundaries_are_inclusive_at_lower_tier(self):
        """PRD section 3.7: "no more than 25 miles pays 2500 cents, more than
        25 but no more than 100 miles pays 7500 cents, and anything beyond 100
        miles pays 15000 cents — the boundaries belong to the lower tier, so
        exactly 25 miles pays 2500 and exactly 100 miles pays 7500."

        Design: Corner/calculations/transport_allowance_tier_boundaries
        """
        plans = self._graduate_plans()
        plan25 = plans["T25"]
        plan100 = plans["T100"]
        plan101 = plans["T101"]
        assert record_service(plan25["id"], "TRANSPORTATION", "COMPLETED",
                              distance_miles=25)["transport_allowance_cents"] == 2500
        assert record_service(plan100["id"], "TRANSPORTATION", "COMPLETED",
                              distance_miles=100)["transport_allowance_cents"] == 7500
        assert record_service(plan101["id"], "TRANSPORTATION", "COMPLETED",
                              distance_miles=101)["transport_allowance_cents"] == 15000


class TestServiceWindowExpiry:
    def test_service_after_expiry_rejected_and_plan_reads_expired(self):
        """PRD section 3.7: "Recording any outcome after the window has closed
        — the clock date past expires_at, so the plan reads EXPIRED — is
        rejected with ERR_TRANSITION_WINDOW_EXPIRED, and on this endpoint that
        window check outranks the generic state check".

        Design: Corner/validations/transition_service_after_window_expired
        """
        set_clock("2026-09-01T00:00:00Z")
        bundle = setup_enrolled_student(center_name="WinSvc Center")
        enrollment = bundle["enrollment"]
        validate_success(
            api_client.transition_enrollment(
                enrollment["id"], {"action": "complete"}, MANAGER
            ),
            200,
        )
        plan = fetch_transition_plan(enrollment["id"])
        assert plan["expires_at"] == "2027-09-01"
        set_clock("2027-09-02T00:00:00Z")
        resp = api_client.record_transition_service(
            plan["id"], {"service_type": "HOUSING", "outcome": "COMPLETED"},
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSITION_WINDOW_EXPIRED)
        expired = fetch_transition_plan(enrollment["id"])
        assert expired["status"] == "EXPIRED"
