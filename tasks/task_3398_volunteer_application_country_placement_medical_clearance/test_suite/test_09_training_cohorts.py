"""Training cohorts: aggregate-capacity overlap semantics (vs the strict
interview exclusion) and the clock-sweep session lifecycle."""

from test_helpers import (
    ApiErrorId,
    COHORT_END_DATE,
    COHORT_START_DATE,
    DEFAULT_CLOCK_START,
    TEST_USERS,
    api_client,
    create_enrolled_scenario,
    create_country_program,
    create_training_cohort,
    get_application,
    get_cohort,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
TRAINER = TEST_USERS["training_director_headers"]


class TestAggregateCapacityOverlap:
    def test_cohort_overlap_permitted_up_to_summed_capacity(self):
        """PRD §3.7: "Cohorts of the same program may overlap in time, but
        only up to a budget: the new cohort's `capacity` plus the summed
        capacities of all overlapping cohorts of that program in `SCHEDULED`
        or `IN_SESSION` must not exceed the program's `training_capacity`, or
        creation fails with `ERR_TRAINING_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/cohort_overlap_aggregate_capacity_semantics
        """
        set_clock(DEFAULT_CLOCK_START)
        program = create_country_program(training_capacity=10)
        cohort_a = create_training_cohort(
            program["id"], name="PST-A",
            start_date="2027-01-01T00:00:00Z", end_date="2027-03-31T00:00:00Z",
            capacity=6)
        # Overlaps A; summed capacity 6 + 4 == 10 sits exactly at the cap.
        cohort_b = create_training_cohort(
            program["id"], name="PST-B",
            start_date="2027-02-01T00:00:00Z", end_date="2027-04-30T00:00:00Z",
            capacity=4)
        assert cohort_a["status"] == "SCHEDULED"
        assert cohort_b["status"] == "SCHEDULED"

        # One more overlapping seat breaches the summed budget.
        validate_error(
            api_client.create_training_cohort(
                {"country_program_id": program["id"], "name": "PST-C",
                 "start_date": "2027-02-15T00:00:00Z",
                 "end_date": "2027-03-15T00:00:00Z", "capacity": 1},
                ADMIN),
            ApiErrorId.ERR_TRAINING_CAPACITY_EXCEEDED, 409)

        cohorts = validate_success(
            api_client.list_training_cohorts(
                ADMIN, params={"country_program_id": program["id"]}), 200)
        assert {c["id"] for c in cohorts} == {cohort_a["id"], cohort_b["id"]}, \
            "the rejected cohort must not be persisted"

    def test_adjacent_cohort_windows_do_not_count_as_overlap(self):
        """PRD §3.7: "Two half-open windows overlap exactly when each starts
        before the other ends, so cohorts that merely touch — one ending the
        instant another begins — do not count against each other."
        PRD §3.7: "This aggregate-capacity rule is the deliberate counterpart
        of the interview rule in §3.3: interviews exclude one another
        absolutely, while cohorts share a budget."

        Design: Difficulty/resource_temporal_overlap/cohort_overlap_aggregate_capacity_semantics
        """
        set_clock(DEFAULT_CLOCK_START)
        program = create_country_program(training_capacity=10)
        create_training_cohort(
            program["id"], name="PST-A",
            start_date="2027-01-01T00:00:00Z", end_date="2027-03-31T00:00:00Z",
            capacity=6)
        # Adjacent to A: starts the instant A ends, so A's seats are free.
        cohort_d = create_training_cohort(
            program["id"], name="PST-D",
            start_date="2027-03-31T00:00:00Z", end_date="2027-06-30T00:00:00Z",
            capacity=10)
        assert cohort_d["status"] == "SCHEDULED", \
            "an adjacent window must not count against the capacity budget"

        # Overlapping only A, and exactly at the cap: 6 + 4 == 10.
        cohort_e = create_training_cohort(
            program["id"], name="PST-E",
            start_date="2027-02-01T00:00:00Z", end_date="2027-03-01T00:00:00Z",
            capacity=4)
        assert cohort_e["status"] == "SCHEDULED"

        # Overlapping both A and E: 6 + 4 + 1 == 11 > 10, rejected.
        validate_error(
            api_client.create_training_cohort(
                {"country_program_id": program["id"], "name": "PST-F",
                 "start_date": "2027-02-15T00:00:00Z",
                 "end_date": "2027-03-01T00:00:00Z", "capacity": 1},
                ADMIN),
            ApiErrorId.ERR_TRAINING_CAPACITY_EXCEEDED, 409)


class TestCohortClockSweep:
    def test_cohort_clock_sweep_session_start_and_conclusion(self):
        """PRD §2.4: "Every training cohort in `SCHEDULED` whose `start_date`
        has been reached or passed becomes `IN_SESSION`, and each of its
        enrollments in `ENROLLED` or `REMEDIATION` moves its application from
        `CLEARED_TO_DEPART` to `IN_TRAINING`."
        PRD §2.4: "Every training cohort in `IN_SESSION` whose `end_date` has
        been reached or passed becomes `CONCLUDED`."

        Design: Corner/state_machines/cohort_clock_sweep_session_start_and_conclusion
        """
        set_clock(DEFAULT_CLOCK_START)
        scenario = create_enrolled_scenario()
        cohort = scenario["cohort"]
        enrollment = scenario["enrollment"]
        app_id = scenario["application"]["id"]
        assert cohort["status"] == "SCHEDULED"
        assert scenario["application"]["status"] == "CLEARED_TO_DEPART"

        # Clock reaches start_date: the cohort opens, the trainee moves in.
        set_clock(COHORT_START_DATE)
        cohort = get_cohort(cohort["id"])
        assert cohort["status"] == "IN_SESSION"
        assert cohort["enrolled_count"] == 1
        assert get_application(app_id)["status"] == "IN_TRAINING", \
            "session start cascades enrolled applications to IN_TRAINING"
        enrollment_now = validate_success(
            api_client.get_training_enrollment(enrollment["id"], TRAINER), 200)
        assert enrollment_now["status"] == "ENROLLED", \
            "the sweep does not change the enrollment itself"

        # Clock reaches end_date: the cohort concludes.
        set_clock(COHORT_END_DATE)
        assert get_cohort(cohort["id"])["status"] == "CONCLUDED"
