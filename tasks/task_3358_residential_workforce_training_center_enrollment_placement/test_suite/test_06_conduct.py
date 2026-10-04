"""Conduct: zero tolerance, rolling points window, board separation cascade."""
from test_helpers import (
    ADVISOR,
    INSTRUCTOR,
    ApiErrorId,
    api_client,
    assign_bed,
    fetch_transition_plan,
    get_center,
    get_enrollment,
    get_trade_program,
    report_incident,
    sanction_incident,
    setup_enrolled_student,
    transition_incident,
    validate_error,
    validate_success,
)


class TestZeroTolerance:
    def test_zero_tolerance_flag_and_sanction_rejection(self):
        """PRD section 3.4: "The system derives zero_tolerance at report time:
        it is true exactly for VIOLENCE, DRUGS, and WEAPONS." and "A
        zero-tolerance incident may not be sanctioned directly — the sanction
        action on it is rejected with ERR_ZERO_TOLERANCE_BOARD_REQUIRED".

        Design: Corner/state_machines/zero_tolerance_sanction_rejected
        """
        bundle = setup_enrolled_student(center_name="ZT Center")
        enrollment = bundle["enrollment"]
        violent = report_incident(enrollment["id"], "VIOLENCE", "2026-08-20")
        assert violent["zero_tolerance"] is True
        transition_incident(violent["id"], "begin_investigation")
        resp = api_client.transition_conduct_incident(
            violent["id"], {"action": "sanction", "sanction_points": 3}, ADVISOR
        )
        validate_error(resp, ApiErrorId.ERR_ZERO_TOLERANCE_BOARD_REQUIRED)

    def test_non_zero_tolerance_sanction_succeeds(self):
        """PRD section 3.4: "sanction it with sanction_points between 1 and 5
        inclusive, landing in SANCTIONED".

        Design: Corner/state_machines/zero_tolerance_sanction_rejected
        """
        bundle = setup_enrolled_student(center_name="ZT Center")
        enrollment = bundle["enrollment"]
        violent = report_incident(enrollment["id"], "VIOLENCE", "2026-08-20")
        transition_incident(violent["id"], "begin_investigation")
        theft = report_incident(enrollment["id"], "THEFT", "2026-08-21")
        assert theft["zero_tolerance"] is False
        transition_incident(theft["id"], "begin_investigation")
        sanctioned = transition_incident(theft["id"], "sanction",
                                         sanction_points=3)
        assert sanctioned["status"] == "SANCTIONED"
        assert sanctioned["sanction_points"] == 3
        rows = validate_success(
            api_client.list_conduct_incidents(enrollment["id"], ADVISOR)
        )
        assert len(rows) == 2


class TestRollingPoints:
    def test_exactly_ten_points_activates_hold(self):
        """PRD section 3.4: "The hold is on whenever any incident of the
        enrollment sits in BOARD_REVIEW, or whenever the rolling points reach
        at least 10 — exactly 10 points activates the hold."

        Design: Corner/state_machines/rolling_points_threshold_exactly_ten_activates_hold
        """
        bundle = setup_enrolled_student(center_name="Pts Center")
        enrollment = bundle["enrollment"]
        sanction_incident(enrollment["id"], "THEFT", "2026-08-10", 4)
        sanction_incident(enrollment["id"], "CURFEW_VIOLATION", "2026-08-15", 5)
        assert get_enrollment(enrollment["id"])["conduct_hold"] is False, (
            "9 rolling points is below the threshold"
        )
        sanction_incident(enrollment["id"], "OTHER", "2026-08-20", 1)
        assert get_enrollment(enrollment["id"])["conduct_hold"] is True, (
            "exactly 10 rolling points activates the hold (>= semantics)"
        )

    def test_day_91_drops_out_of_window(self):
        """PRD section 3.4: "A rolling window opens 90 days before the logical
        clock date; the enrollment's rolling points are the sum of
        sanction_points over its own incidents in SANCTIONED whose occurred_at
        falls inside the window, with the window inclusive at both ends as a
        date comparison."

        Design: Corner/state_machines/rolling_points_window_boundary_excludes_day_91
        """
        bundle = setup_enrolled_student(center_name="Win Center")
        enrollment = bundle["enrollment"]
        # Default clock date 2026-09-01: window covers 2026-06-03..2026-09-01.
        sanction_incident(enrollment["id"], "THEFT", "2026-06-02", 5)
        sanction_incident(enrollment["id"], "THEFT", "2026-06-03", 5)
        assert get_enrollment(enrollment["id"])["conduct_hold"] is False, (
            "only the window-edge sanction counts (5 < 10); the day-91 "
            "incident is excluded"
        )


class TestBoardSeparationCascade:
    def _setup(self):
        bundle = setup_enrolled_student(
            center_name="Cascade Center", total_beds=1, capacity=1,
            residential_track=True,
        )
        enrollment = bundle["enrollment"]
        assignment = assign_bed(enrollment["id"], move_in_date="2026-09-01",
                                bed_label="B-01")
        incident = report_incident(enrollment["id"], "VIOLENCE", "2026-09-01")
        transition_incident(incident["id"], "begin_investigation")
        transition_incident(incident["id"], "refer_board")
        return bundle, assignment, incident

    def test_board_separation_hits_enrollment_and_plan(self):
        """PRD section 3.4: "First the owning enrollment's training axis moves
        to SEPARATED, with exit_date set to the clock date and exit_reason set
        to CONDUCT_BOARD." and "The same mutation auto-creates the student's
        transition plan with all three service tracks PENDING."

        Design: Difficulty/transitive_cascade/board_separation_cascades_enrollment_dorm_center_program
        """
        bundle, _assignment, incident = self._setup()
        enrollment = bundle["enrollment"]
        decided = transition_incident(incident["id"], "separate")
        assert decided["status"] == "SEPARATION_ORDERED"
        after = get_enrollment(enrollment["id"])
        assert after["training_status"] == "SEPARATED"
        assert after["residential_status"] == "RELEASED"
        assert after["exit_reason"] == "CONDUCT_BOARD"
        plan = fetch_transition_plan(enrollment["id"])
        assert plan is not None
        assert plan["status"] == "ACTIVE"
        assert plan["job_placement_status"] == "PENDING"
        assert plan["housing_status"] == "PENDING"
        assert plan["transportation_status"] == "PENDING"

    def test_board_separation_terminates_bed_and_frees_seat(self):
        """PRD section 3.4: "That enrollment mutation releases the program
        seat — enrolled count down by one, with the FULL-to-OPEN flip when the
        program had been full — and terminates the enrollment's ACTIVE
        dormitory assignments with the clock date as move-out, which in turn
        recomputes the center's beds_in_use and beds_available."

        Design: Difficulty/transitive_cascade/board_separation_cascades_enrollment_dorm_center_program
        """
        bundle, assignment, incident = self._setup()
        transition_incident(incident["id"], "separate")
        rows = validate_success(
            api_client.list_dormitory_assignments(
                bundle["enrollment"]["id"], ADVISOR
            )
        )
        assert rows[0]["id"] == assignment["id"]
        assert rows[0]["status"] == "TERMINATED"
        assert rows[0]["move_out_date"] == "2026-09-01"
        center = get_center(bundle["center"]["id"])
        assert center["beds_in_use"] == 0
        assert center["beds_available"] == 1
        program = get_trade_program(bundle["center"]["id"],
                                    bundle["program"]["id"])
        assert program["open_seats"] == 1
        assert program["status"] == "OPEN"


class TestConductRbac:
    def test_instructor_cannot_report_incident(self):
        """PRD section 2.7: "an authenticated role outside the endpoint's
        authorization list produces ERR_FORBIDDEN_ROLE" — the role check is
        reported before any identifier resolution.

        Design: Corner/rbac/instructor_cannot_report_incident
        """
        resp = api_client.create_conduct_incident(
            {"enrollment_id": "11111111-2222-3333-4444-555555555555",
             "infraction_code": "THEFT", "occurred_at": "2026-08-20"},
            INSTRUCTOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
