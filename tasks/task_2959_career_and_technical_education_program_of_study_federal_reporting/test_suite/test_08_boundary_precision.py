"""Boundary and precision probes on the thresholds the specification pins.

Every rule this module exercises has a constant with a declared inclusive or
exclusive side: the concentrator credit floor, the federal minimum cohort size,
the two-decimal rounding of the met threshold, and the employer-parity clause on
committee attendance. Each test therefore places its data immediately below, at,
or immediately above the constant, so that an implementation using the wrong
comparison operator or rounding at the wrong width is falsified by the equal
case alone.
"""

from test_helpers import (
    assert_cohort_figures,
    assert_credit_hours,
    assert_pct,
    assert_quorum_figures,
    errors,
    f,
    k,
    users,
    validate_error,
    validate_unpaginated,
)

CLNA_MEETING_INSTANT = "2026-08-04T14:00:00.000Z"


def _program_with_active_secondary_course(build, cip_code, course_code):
    """A DRAFT program carrying one ACTIVE SECONDARY course of 4.00 credits."""
    program = build.create_program(cip_code, cluster=k.CLUSTER_INFORMATION_TECHNOLOGY)
    course = build.add_course(
        program["id"],
        f.secondary_course(course_code, 1, 4.0, status=k.COURSE_ACTIVE),
    )
    return program["id"], course["id"]


def _program_with_course_and_credential(build, cip_code, course_code, credential_code):
    """The same program plus one NATIONAL credential that needs no exam score."""
    program_id, course_id = _program_with_active_secondary_course(
        build, cip_code, course_code
    )
    credential = build.add_credential(
        program_id, credential_code, tier=k.TIER_NATIONAL, exam_required=False
    )
    return program_id, course_id, credential["id"]


def _enroll_cohort(build, program_id, course_id, credential_id, size, verified_count):
    """Enroll ``size`` students at exactly 2.00 credits, verifying the first few."""
    student_ids = []
    for index in range(size):
        student = build.enroll(
            program_id, str(100000001 + index), cohort_year=2026
        )
        build.post_credit(student["id"], course_id, 2.0)
        if index < verified_count:
            build.attain(student["id"], credential_id)
        student_ids.append(student["id"])
    return student_ids


def _committee_with_roster(build, cip_code, roster):
    """Charter a committee needing 3 present members and 2 employer seats."""
    program = build.create_program(cip_code, cluster=k.CLUSTER_AGRICULTURE)
    committee_row = build.charter_committee(
        program["id"], quorum_min_members=3, employer_seat_min=2
    )
    return build.seat_roster(committee_row["id"], roster)


class TestConcentratorCreditThreshold:
    """The two-credit floor that separates a participant from a concentrator."""

    def test_balance_of_exactly_two_credits_classifies_as_concentrator(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "Third, `concentrator_status` is decided by a three-way ladder
        evaluated top to bottom: the student is a `COMPLETER` when
        `cte_credits_earned` is at least 2.0 credit hours **and** `exited_on` is
        non-null **and** `verified_qualifying_attainment_count` is at least 1;
        failing that, the student is a `CONCENTRATOR` when `cte_credits_earned`
        alone is at least 2.0 credit hours; failing that, the student is a
        `PARTICIPANT`. The credit comparison is inclusive — a balance of exactly
        2.0 classifies as at least `CONCENTRATOR`, while 1.99 does not"

        PRD §2.11: "Credit-hour quantities — `credit_hours`,
        `articulated_credit_hours`, `secondary_credit_total`,
        `postsecondary_credit_total`, `articulated_credit_total` and
        `cte_credits_earned` — are carried at two decimal places, round-half-up."

        Design: Difficulty/boundary_precision_check/concentrator_threshold_at_exactly_two_credits_versus_one_point_nine_nine
        """
        program_id, course_id = _program_with_active_secondary_course(
            build, "11.0201", "CSP-1"
        )
        student = build.enroll(program_id, "100000001", cohort_year=2026)
        build.post_credit(student["id"], course_id, 2.0)

        row = validate_unpaginated(
            api.get_student(student["id"], registrar_headers), 200
        )
        assert_credit_hours(row["cte_credits_earned"], 2.00, "cte_credits_earned")
        assert row["concentrator_status"] == k.CONCENTRATOR_CONCENTRATOR

    def test_balance_one_hundredth_short_of_two_credits_stays_a_participant(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "Third, `concentrator_status` is decided by a three-way ladder
        evaluated top to bottom: the student is a `COMPLETER` when
        `cte_credits_earned` is at least 2.0 credit hours **and** `exited_on` is
        non-null **and** `verified_qualifying_attainment_count` is at least 1;
        failing that, the student is a `CONCENTRATOR` when `cte_credits_earned`
        alone is at least 2.0 credit hours; failing that, the student is a
        `PARTICIPANT`. The credit comparison is inclusive — a balance of exactly
        2.0 classifies as at least `CONCENTRATOR`, while 1.99 does not"

        PRD §2.11: "Credit-hour quantities — `credit_hours`,
        `articulated_credit_hours`, `secondary_credit_total`,
        `postsecondary_credit_total`, `articulated_credit_total` and
        `cte_credits_earned` — are carried at two decimal places, round-half-up."

        Design: Difficulty/boundary_precision_check/concentrator_threshold_at_exactly_two_credits_versus_one_point_nine_nine
        """
        program_id, course_id = _program_with_active_secondary_course(
            build, "11.0202", "CSP-2"
        )
        student = build.enroll(program_id, "100000002", cohort_year=2026)
        build.post_credit(student["id"], course_id, 1.99)

        row = validate_unpaginated(
            api.get_student(student["id"], registrar_headers), 200
        )
        assert_credit_hours(row["cte_credits_earned"], 1.99, "cte_credits_earned")
        assert row["concentrator_status"] == k.CONCENTRATOR_PARTICIPANT

    def test_balance_one_hundredth_over_two_credits_classifies_as_concentrator(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "Third, `concentrator_status` is decided by a three-way ladder
        evaluated top to bottom: the student is a `COMPLETER` when
        `cte_credits_earned` is at least 2.0 credit hours **and** `exited_on` is
        non-null **and** `verified_qualifying_attainment_count` is at least 1;
        failing that, the student is a `CONCENTRATOR` when `cte_credits_earned`
        alone is at least 2.0 credit hours; failing that, the student is a
        `PARTICIPANT`. The credit comparison is inclusive — a balance of exactly
        2.0 classifies as at least `CONCENTRATOR`, while 1.99 does not"

        PRD §3.6: "First, `cte_credits_earned` is rebuilt as the sum of
        `credit_delta` across every accepted posting for that student whose target
        course was in `status` `ACTIVE` at the time of posting, rounded half-up to
        two decimal places."

        Design: Difficulty/boundary_precision_check/concentrator_threshold_at_exactly_two_credits_versus_one_point_nine_nine
        """
        program_id, course_id = _program_with_active_secondary_course(
            build, "11.0203", "CSP-3"
        )
        student = build.enroll(program_id, "100000003", cohort_year=2026)
        build.post_credit(student["id"], course_id, 1.99)
        build.post_credit(student["id"], course_id, 0.02)

        row = validate_unpaginated(
            api.get_student(student["id"], registrar_headers), 200
        )
        assert_credit_hours(row["cte_credits_earned"], 2.01, "cte_credits_earned")
        assert row["concentrator_status"] == k.CONCENTRATOR_CONCENTRATOR


class TestEmptyCohortScoring:
    """The empty-set edge of the accountability aggregation."""

    def test_indicator_over_an_empty_cohort_publishes_a_null_preliminary_figure(
        self, api, build, reviewer_headers
    ):
        """PRD §3.8: "`denominator_count` is the number of students whose program
        matches the indicator's program, whose `cohort_year` matches the
        indicator's `cohort_year`, and whose `concentrator_status` is
        `CONCENTRATOR` or `COMPLETER`; a `PARTICIPANT` counts in neither the
        numerator nor the denominator. `numerator_count` is the number of those
        same students whose `verified_qualifying_attainment_count` is at least 1.
        `small_cohort_flag` is true exactly when `denominator_count` is below the
        federal minimum cohort size of 5. The raw percentage is null when
        `denominator_count` is zero; otherwise it is 100 multiplied by
        `numerator_count`, divided by `denominator_count`, rounded half-up to two
        decimal places."

        PRD §3.8: "The `PRELIMINARY_UNADJUSTED` variant ignores
        `small_cohort_flag` completely: it publishes the raw percentage as
        `preliminary_actual_pct` and sets `preliminary_status_projection` to `MET`
        when the raw percentage is at least `met_threshold_pct`, to `NOT_MET` when
        it is strictly below, and to `UNDEFINED` whenever either the raw
        percentage or `met_threshold_pct` is null."

        PRD §3.8: "Acceptance copies `last_offer_pct` into `negotiated_level_pct`
        and sets `met_threshold_pct` to that level multiplied by the federal
        tolerance of 0.90, rounded half-up to two decimal places."

        Design: Difficulty/boundary_precision_check/empty_cohort_denominator_zero_yields_null_actual_and_not_scored
        """
        program_id, course_id, credential_id = _program_with_course_and_credential(
            build, "43.0107", "CRJ-1", "CRJ-CRT"
        )
        _enroll_cohort(build, program_id, course_id, credential_id, 2, 0)

        agreed = build.agreed_indicator(
            program_id,
            k.INDICATOR_4S1_CREDENTIAL,
            44.44,
            reporting_year=2030,
            baseline_pct=60.0,
            cohort_year=2029,
        )
        assert_pct(agreed["met_threshold_pct"], 40.00, "met_threshold_pct")

        row = validate_unpaginated(
            api.get_indicator(agreed["id"], reviewer_headers), 200
        )
        assert_cohort_figures(row, 0, 0, True)
        assert row["preliminary_actual_pct"] is None
        assert row["preliminary_status_projection"] == k.PROJECTION_UNDEFINED

    def test_closing_an_empty_cohort_records_not_scored_with_a_null_actual(
        self, api, build, reviewer_headers
    ):
        """PRD §3.8: "When `denominator_count` is below 5 — including the case
        where it is zero — the indicator is scored `NOT_SCORED`. `actual_pct`
        still takes the final variant's output, which is null when
        `denominator_count` is zero and otherwise the unsuppressed percentage, and
        `consecutive_miss_count` is left exactly as it was."

        PRD §3.8: "The raw percentage is null when `denominator_count` is zero;
        otherwise it is 100 multiplied by `numerator_count`, divided by
        `denominator_count`, rounded half-up to two decimal places."

        Design: Difficulty/boundary_precision_check/empty_cohort_denominator_zero_yields_null_actual_and_not_scored
        """
        program_id, course_id, credential_id = _program_with_course_and_credential(
            build, "43.0108", "CRJ-2", "CRJ-CRT2"
        )
        _enroll_cohort(build, program_id, course_id, credential_id, 2, 0)

        agreed = build.agreed_indicator(
            program_id,
            k.INDICATOR_4S1_CREDENTIAL,
            44.44,
            reporting_year=2030,
            baseline_pct=60.0,
            cohort_year=2029,
        )
        build.close_year(agreed["id"], "2030-09-30")

        row = validate_unpaginated(
            api.get_indicator(agreed["id"], reviewer_headers), 200
        )
        assert row["actual_pct"] is None
        assert row["status"] == k.PI_NOT_SCORED
        assert row["consecutive_miss_count"] == 0

    def test_closing_a_cohort_of_four_records_not_scored_with_a_zero_actual(
        self, api, build, reviewer_headers
    ):
        """PRD §3.8: "When `denominator_count` is below 5 — including the case
        where it is zero — the indicator is scored `NOT_SCORED`. `actual_pct`
        still takes the final variant's output, which is null when
        `denominator_count` is zero and otherwise the unsuppressed percentage, and
        `consecutive_miss_count` is left exactly as it was."

        PRD §3.8: "`small_cohort_flag` is true exactly when `denominator_count` is
        below the federal minimum cohort size of 5. The raw percentage is null
        when `denominator_count` is zero; otherwise it is 100 multiplied by
        `numerator_count`, divided by `denominator_count`, rounded half-up to two
        decimal places."

        Design: Difficulty/boundary_precision_check/empty_cohort_denominator_zero_yields_null_actual_and_not_scored
        """
        program_id, course_id, credential_id = _program_with_course_and_credential(
            build, "43.0109", "CRJ-3", "CRJ-CRT3"
        )
        _enroll_cohort(build, program_id, course_id, credential_id, 4, 0)

        agreed = build.agreed_indicator(
            program_id,
            k.INDICATOR_4S1_CREDENTIAL,
            44.44,
            reporting_year=2027,
            baseline_pct=60.0,
            cohort_year=2026,
        )
        assert_pct(agreed["met_threshold_pct"], 40.00, "met_threshold_pct")

        before = validate_unpaginated(
            api.get_indicator(agreed["id"], reviewer_headers), 200
        )
        assert_cohort_figures(before, 4, 0, True)
        assert_pct(before["preliminary_actual_pct"], 0.00, "preliminary_actual_pct")
        assert before["preliminary_status_projection"] == k.PROJECTION_NOT_MET

        build.close_year(agreed["id"], "2027-09-30")

        row = validate_unpaginated(
            api.get_indicator(agreed["id"], reviewer_headers), 200
        )
        assert_pct(row["actual_pct"], 0.00, "actual_pct")
        assert row["status"] == k.PI_NOT_SCORED
        assert row["consecutive_miss_count"] == 0


class TestMetThresholdRounding:
    """One hundredth of a point on the negotiated level flips the year's score."""

    def test_negotiated_level_rounding_down_lets_identical_data_meet_the_target(
        self, api, build, reviewer_headers
    ):
        """PRD §3.8: "Acceptance copies `last_offer_pct` into `negotiated_level_pct`
        and sets `met_threshold_pct` to that level multiplied by the federal
        tolerance of 0.90, rounded half-up to two decimal places."

        PRD §3.8: "The raw percentage is null when `denominator_count` is zero;
        otherwise it is 100 multiplied by `numerator_count`, divided by
        `denominator_count`, rounded half-up to two decimal places."

        PRD §3.8: "When `denominator_count` is at least 5 and `actual_pct` is at
        least `met_threshold_pct` (the comparison is inclusive), the indicator is
        scored `MET` and `consecutive_miss_count` is reset to 0."

        Design: Difficulty/boundary_precision_check/met_threshold_rounding_at_forty_four_point_four_four_versus_forty_four_point_four_five
        """
        program_id, course_id, credential_id = _program_with_course_and_credential(
            build, "52.0201", "BUS-1", "MOS-EX"
        )
        _enroll_cohort(build, program_id, course_id, credential_id, 5, 2)

        agreed = build.agreed_indicator(
            program_id,
            k.INDICATOR_4S1_CREDENTIAL,
            44.44,
            reporting_year=2027,
            baseline_pct=60.0,
            cohort_year=2026,
        )
        assert_pct(agreed["met_threshold_pct"], 40.00, "met_threshold_pct")

        build.close_year(agreed["id"], "2027-09-30")

        row = validate_unpaginated(
            api.get_indicator(agreed["id"], reviewer_headers), 200
        )
        assert_cohort_figures(row, 5, 2, False)
        assert_pct(row["actual_pct"], 40.00, "actual_pct")
        assert row["status"] == k.PI_MET
        assert row["consecutive_miss_count"] == 0

    def test_negotiated_level_rounding_up_makes_the_same_data_miss_the_target(
        self, api, build, reviewer_headers
    ):
        """PRD §3.8: "Acceptance copies `last_offer_pct` into `negotiated_level_pct`
        and sets `met_threshold_pct` to that level multiplied by the federal
        tolerance of 0.90, rounded half-up to two decimal places."

        PRD §3.8: "The raw percentage is null when `denominator_count` is zero;
        otherwise it is 100 multiplied by `numerator_count`, divided by
        `denominator_count`, rounded half-up to two decimal places."

        PRD §3.8: "When `denominator_count` is at least 5 and `actual_pct` is
        strictly below `met_threshold_pct`, the indicator is scored `NOT_MET` and
        `consecutive_miss_count` increases by 1"

        Design: Difficulty/boundary_precision_check/met_threshold_rounding_at_forty_four_point_four_four_versus_forty_four_point_four_five
        """
        program_id, course_id, credential_id = _program_with_course_and_credential(
            build, "52.0202", "BUS-2", "MOS-WD"
        )
        _enroll_cohort(build, program_id, course_id, credential_id, 5, 2)

        agreed = build.agreed_indicator(
            program_id,
            k.INDICATOR_4S1_CREDENTIAL,
            44.45,
            reporting_year=2028,
            baseline_pct=60.0,
            cohort_year=2026,
        )
        assert_pct(agreed["met_threshold_pct"], 40.01, "met_threshold_pct")

        build.close_year(agreed["id"], "2028-09-30")

        row = validate_unpaginated(
            api.get_indicator(agreed["id"], reviewer_headers), 200
        )
        assert_cohort_figures(row, 5, 2, False)
        assert_pct(row["actual_pct"], 40.00, "actual_pct")
        assert row["status"] == k.PI_NOT_MET
        assert row["consecutive_miss_count"] == 1

    def test_two_levels_one_hundredth_apart_round_to_distinct_met_thresholds(
        self, build
    ):
        """PRD §3.8: "Acceptance copies `last_offer_pct` into `negotiated_level_pct`
        and sets `met_threshold_pct` to that level multiplied by the federal
        tolerance of 0.90, rounded half-up to two decimal places. In other words, a
        district hits its target if it achieves at least ninety percent of the
        level it agreed to."

        PRD §2.11: "Percentages used in accountability — `baseline_pct`,
        `negotiated_level_pct`, `last_offer_pct`, `met_threshold_pct`,
        `preliminary_actual_pct` and `actual_pct` — are carried at two decimal
        places, round-half-up."

        Design: Difficulty/boundary_precision_check/met_threshold_rounding_at_forty_four_point_four_four_versus_forty_four_point_four_five
        """
        program_id, _course_id, _credential_id = _program_with_course_and_credential(
            build, "52.0203", "BUS-3", "MOS-PP"
        )

        lower = build.agreed_indicator(
            program_id,
            k.INDICATOR_4S1_CREDENTIAL,
            44.44,
            reporting_year=2027,
            baseline_pct=60.0,
            cohort_year=2026,
        )
        higher = build.agreed_indicator(
            program_id,
            k.INDICATOR_4S1_CREDENTIAL,
            44.45,
            reporting_year=2028,
            baseline_pct=60.0,
            cohort_year=2026,
        )

        assert_pct(lower["negotiated_level_pct"], 44.44, "negotiated_level_pct")
        assert_pct(lower["met_threshold_pct"], 40.00, "met_threshold_pct")
        assert_pct(higher["negotiated_level_pct"], 44.45, "negotiated_level_pct")
        assert_pct(higher["met_threshold_pct"], 40.01, "met_threshold_pct")


ROSTER_TWO_EMPLOYERS = (
    ("Rosa Vega", k.SECTOR_EMPLOYER, "EMP-1", True),
    ("Ken Ade", k.SECTOR_EMPLOYER, "EMP-2", False),
    ("Iris Lund", k.SECTOR_POSTSECONDARY, "PSE-1", False),
    ("Paul Ozu", k.SECTOR_LABOR, "LAB-1", False),
    ("Mira Cole", k.SECTOR_PARENT, "PAR-1", False),
)

ROSTER_THREE_EMPLOYERS = (
    ("Rosa Vega", k.SECTOR_EMPLOYER, "EMP-1", True),
    ("Ken Ade", k.SECTOR_EMPLOYER, "EMP-2", False),
    ("Nia Brandt", k.SECTOR_EMPLOYER, "EMP-3", False),
    ("Iris Lund", k.SECTOR_POSTSECONDARY, "PSE-1", False),
    ("Paul Ozu", k.SECTOR_LABOR, "LAB-1", False),
)


class TestEmployerParityBoundary:
    """Employers holding exactly half of the eligible attendance carry quorum."""

    def test_two_employers_among_four_attendees_carry_quorum(
        self, api, build, director_headers
    ):
        """PRD §3.3: "Quorum requires three things simultaneously:
        `eligible_attendee_count` at least `quorum_min_members`,
        `employer_attendee_count` at least `employer_seat_min`, and employer parity
        — twice `employer_attendee_count` at least `eligible_attendee_count`,
        meaning employers must hold at least half of the eligible attendance. The
        parity clause is inclusive, so employers holding exactly half satisfies it.
        The result is stored in `quorum_met`."

        PRD §3.3: "`eligible_attendee_count` is then the number of eligible
        attendees, and `employer_attendee_count` is the number of those whose
        `sector` is `EMPLOYER`."

        PRD §3.3: "A filing without an `amendment_reason` moves the meeting
        `SCHEDULED → FINALIZED`, writing `held_at`, `attendee_member_ids`,
        `vote_yes`, `vote_no` and `minutes_url` from the request and recomputing
        `eligible_attendee_count`, `employer_attendee_count`, `quorum_met` and
        `endorsement_passed`."

        PRD §3.3: "`endorsement_passed` is a stricter reading of the same figures:
        it is true only when `quorum_met` is true, `vote_yes` is strictly greater
        than `vote_no`, and `vote_yes` plus `vote_no` is no greater than
        `eligible_attendee_count`. A tied vote does not endorse."

        Design: Difficulty/boundary_precision_check/employer_parity_at_exactly_half_of_attendance_passes_while_bare_minority_fails
        """
        committee = _committee_with_roster(build, "01.0601", ROSTER_TWO_EMPLOYERS)
        meeting = build.schedule_meeting(
            committee.committee_id,
            committee.chair_member_id,
            k.AGENDA_CLNA_STAKEHOLDER,
            CLNA_MEETING_INSTANT,
        )
        attendees = committee.member_ids[:4]
        build.file_minutes(
            meeting["id"],
            committee.chair_member_id,
            CLNA_MEETING_INSTANT,
            attendees,
            4,
            0,
        )

        row = validate_unpaginated(
            api.get_meeting(meeting["id"], director_headers), 200
        )
        assert_quorum_figures(row, 4, 2, True, True)
        assert row["minutes_status"] == k.MINUTES_FINALIZED

    def test_two_employers_among_five_attendees_are_a_bare_minority(
        self, api, build, director_headers
    ):
        """PRD §3.3: "Quorum requires three things simultaneously:
        `eligible_attendee_count` at least `quorum_min_members`,
        `employer_attendee_count` at least `employer_seat_min`, and employer parity
        — twice `employer_attendee_count` at least `eligible_attendee_count`,
        meaning employers must hold at least half of the eligible attendance. The
        parity clause is inclusive, so employers holding exactly half satisfies it.
        The result is stored in `quorum_met`."

        PRD §3.3: "The three failure modes report separately and in this order: a
        headcount below `quorum_min_members` is `ERR_QUORUM_NOT_MET`; then an
        employer shortfall — either too few employers against `employer_seat_min`
        or employers holding strictly less than half the eligible attendance — is
        `ERR_EMPLOYER_SEAT_SHORTFALL`; then `vote_yes` plus `vote_no` exceeding
        `eligible_attendee_count` is `ERR_VOTE_COUNT_EXCEEDS_ATTENDANCE`."

        PRD §3.3: "The new meeting begins with `minutes_status` `SCHEDULED`, an
        empty `attendee_member_ids` list, `vote_yes` and `vote_no` both at 0,
        `quorum_met` and `endorsement_passed` both false, and `held_at`,
        `minutes_url` and `amendment_reason` all null"

        Design: Difficulty/boundary_precision_check/employer_parity_at_exactly_half_of_attendance_passes_while_bare_minority_fails
        """
        committee = _committee_with_roster(build, "01.0602", ROSTER_TWO_EMPLOYERS)
        meeting = build.schedule_meeting(
            committee.committee_id,
            committee.chair_member_id,
            k.AGENDA_CLNA_STAKEHOLDER,
            CLNA_MEETING_INSTANT,
        )

        response = api.file_minutes(
            meeting["id"],
            f.minutes_payload(CLNA_MEETING_INSTANT, committee.member_ids, 5, 0),
            users.chair_headers(committee.chair_member_id),
        )
        validate_error(response, errors.ERR_EMPLOYER_SEAT_SHORTFALL)

        row = validate_unpaginated(
            api.get_meeting(meeting["id"], director_headers), 200
        )
        assert row["minutes_status"] == k.MINUTES_SCHEDULED
        assert row["quorum_met"] is False

    def test_three_employers_among_five_attendees_carry_quorum(
        self, api, build, director_headers
    ):
        """PRD §3.3: "Quorum requires three things simultaneously:
        `eligible_attendee_count` at least `quorum_min_members`,
        `employer_attendee_count` at least `employer_seat_min`, and employer parity
        — twice `employer_attendee_count` at least `eligible_attendee_count`,
        meaning employers must hold at least half of the eligible attendance. The
        parity clause is inclusive, so employers holding exactly half satisfies it.
        The result is stored in `quorum_met`."

        PRD §3.3: "`eligible_attendee_count` is then the number of eligible
        attendees, and `employer_attendee_count` is the number of those whose
        `sector` is `EMPLOYER`."

        Design: Difficulty/boundary_precision_check/employer_parity_at_exactly_half_of_attendance_passes_while_bare_minority_fails
        """
        committee = _committee_with_roster(build, "01.0603", ROSTER_THREE_EMPLOYERS)
        meeting = build.schedule_meeting(
            committee.committee_id,
            committee.chair_member_id,
            k.AGENDA_CLNA_STAKEHOLDER,
            CLNA_MEETING_INSTANT,
        )
        build.file_minutes(
            meeting["id"],
            committee.chair_member_id,
            CLNA_MEETING_INSTANT,
            committee.member_ids,
            5,
            0,
        )

        row = validate_unpaginated(
            api.get_meeting(meeting["id"], director_headers), 200
        )
        assert_quorum_figures(row, 5, 3, True, True)
        assert row["minutes_status"] == k.MINUTES_FINALIZED
