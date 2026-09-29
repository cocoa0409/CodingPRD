"""Derived figures read back exactly as the arithmetic in the requirements
document specifies: pathway weights, seat input sets, pacing bands, rate
precision, posture thresholds, the GPA input set and transcript coding."""

from test_helpers import (
    CreditPolicy,
    GradeCode,
    GradeReplacementMode,
    GradeReplacementPolicy,
    IntakePosture,
    ModalityCode,
    Modality,
    PacingFlag,
    Pathway,
    PlanPosture,
    PlanStatus,
    PriorOutcome,
    ReferralStatus,
    ReplacementStatus,
    SubjectArea,
    DISTRICT_ADMIN_HEADERS,
    REGISTRAR_HEADERS,
    assert_close,
    assert_readiness_figures,
    assert_seat_picture,
    assert_transcript_coding,
    factories as f,
    fixtures as fx,
    make_placement_coordinator_headers,
    validate_success,
)

BEHAVIOR_CASE = {
    "pathway": Pathway.BEHAVIOR.value,
    "deficiency_credits": 3.00,
    "behavior_incident_count": 4,
    "days_disengaged": 15,
}

ALG1 = {
    "code": "ALG1",
    "title": "Algebra I",
    "subject_area": SubjectArea.MATH.value,
    "credit_value": 1.00,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "min_passing_percent": 60.00,
}

ENG1 = dict(
    ALG1, code="ENG1", title="English I", subject_area=SubjectArea.ELA.value
)


class TestReferralPriorityUsesThePathwayWeightSet:
    """The BEHAVIOR weight set and the additive re-referral bump."""

    def test_the_behavior_weight_set_scores_this_case_at_exactly_one_number(self, api):
        """Components 0.3750, 0.8000 and 0.5000 weighted 0.20 / 0.60 / 0.20 with each
        term rounded before the sum gives 0.6550, which no other weight set produces
        from these three counters.

        PRD: "Each weighted term is rounded to 4 decimal places **before** the three
        are summed, and the sum is rounded to 4 decimal places as well — the
        rounding order is pinned and produces a different result from summing
        first."

        Design: Corner/calculations/priority_score_behavior_weights_and_re_referral_bump
        """
        home_school = fx.open_home_school(api)
        center = fx.open_center(api, name="Cedar AEC")
        student = fx.register_student(
            api, home_school["id"], grade_level=11, cohort_year=2027
        )

        referral = fx.submit_referral(
            api, student["id"], center["id"], home_school["id"], **BEHAVIOR_CASE
        )
        assert referral["pathway"] == Pathway.BEHAVIOR.value
        assert_close(referral["priority_score"], 0.6550, "priority score")
        assert referral["prior_referral_id"] is None
        assert referral["status"] == ReferralStatus.SUBMITTED.value

    def test_citing_a_prior_referral_adds_the_bump_without_re_weighting(self, api):
        """The re-referral carries byte-identical counters and scores 0.7050, exactly
        0.0500 above the first score.

        PRD: "When the referral cites a `prior_referral_id`, a re-referral bump of
        0.0500 is added to the base and the result is held at a maximum of 1.0000
        and rounded to 4 decimal places; when no prior referral is cited the base is
        the score unchanged."

        Design: Corner/calculations/priority_score_behavior_weights_and_re_referral_bump
        """
        home_school = fx.open_home_school(api)
        center = fx.open_center(api, name="Cedar AEC")
        student = fx.register_student(
            api, home_school["id"], grade_level=11, cohort_year=2027
        )
        first = fx.submit_referral(
            api, student["id"], center["id"], home_school["id"], **BEHAVIOR_CASE
        )
        fx.screen_referral(api, first["id"], center["id"])
        validate_success(
            api.deny_referral(
                first["id"],
                f.deny_referral_payload(),
                make_placement_coordinator_headers(center["id"]),
            )
        )

        again = fx.submit_referral(
            api,
            student["id"],
            center["id"],
            home_school["id"],
            prior_referral_id=first["id"],
            **BEHAVIOR_CASE,
        )
        assert again["prior_referral_id"] == first["id"]
        assert_close(again["priority_score"], 0.7050, "re-referral priority score")
        assert_close(
            again["priority_score"] - first["priority_score"],
            0.0500,
            "the bump is additive",
        )


class TestSeatAndPostureInputSetsCountOnlyWhatTheyDeclare:
    """A waitlisted referral holds no seat, so it enters no seat figure."""

    def test_only_the_offered_referral_reserves_a_seat(self, api):
        """One WAITLISTED and one PLACEMENT_OFFERED referral at a ten-seat centre
        give seats_reserved 1 and seats_available 9, not 2 and 8.

        PRD: "`seats_reserved` is the number of referrals at this center whose
        `status` is `PLACEMENT_OFFERED`. A referral sitting in `WAITLISTED` reserves
        nothing."

        Design: Corner/calculations/intake_posture_input_set_ignores_waitlisted_referrals
        """
        home_school = fx.open_home_school(api)
        center = fx.open_center(api, name="Cedar AEC", seat_capacity=10)
        first_student = fx.register_student(
            api, home_school["id"], grade_level=11, cohort_year=2027
        )
        second_student = fx.register_student(
            api, home_school["id"], grade_level=11, cohort_year=2027
        )
        held = fx.screened_referral(
            api, first_student["id"], center["id"], home_school["id"]
        )
        offered = fx.screened_referral(
            api, second_student["id"], center["id"], home_school["id"]
        )

        waitlisted = fx.waitlist_referral(
            api,
            held["id"],
            center["id"],
            waitlist_reason="awaiting counsellor availability",
        )
        assert waitlisted["status"] == ReferralStatus.WAITLISTED.value
        assert waitlisted["waitlist_reason"] == "awaiting counsellor availability"
        assert waitlisted["offer_expires_on"] is None

        seated = fx.offer_seat(
            api, offered["id"], center["id"], expected_center_version=1, offer_valid_days=10
        )
        assert seated["status"] == ReferralStatus.PLACEMENT_OFFERED.value
        assert seated["offer_expires_on"] == "2026-08-11"

        center = fx.read_center(api, center["id"])
        assert_seat_picture(center, 0, 1, 9, IntakePosture.OPEN.value)
        assert center["seats_committed"] == 1


def _two_enrollment_placement(api):
    """One placement carrying two eight-module, forty-day enrollments, one at
    three modules passed and one at two."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    first_course = fx.publish_course(api, **ALG1)
    second_course = fx.publish_course(api, **ENG1)
    student = fx.register_student(
        api, home_school["id"], grade_level=11, cohort_year=2027
    )
    referral = fx.screened_referral(
        api, student["id"], center["id"], home_school["id"]
    )
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
        start_date="2026-08-01",
    )
    ahead = fx.enroll_new_credit(api, placement["id"], first_course["id"])
    behind = fx.enroll_new_credit(api, placement["id"], second_course["id"])
    fx.report_progress(
        api,
        ahead["id"],
        modules_passed_delta=3,
        seat_hours_delta=20.00,
        module_avg_percent=72.00,
    )
    fx.report_progress(
        api,
        behind["id"],
        modules_passed_delta=2,
        seat_hours_delta=15.00,
        module_avg_percent=68.00,
    )
    return {
        "center": center,
        "student": student,
        "placement": placement,
        "ahead": ahead,
        "behind": behind,
    }


class TestPacingBandsFollowTheTwoPublishedConstants:
    """One module of difference separates BEHIND from CRITICAL."""

    def test_one_module_of_difference_separates_behind_from_critical(self, api):
        """Twenty days into a forty-day window the expected fraction is 0.5000, so
        three of eight modules indexes 0.750 and two of eight indexes 0.500, landing
        in the two lower bands with neither reading ON_PACE.

        PRD: "The resulting `pacing_flag` is `ON_PACE` when the index is at least
        0.900, otherwise `BEHIND` when it is at least 0.700, otherwise `CRITICAL`."

        Design: Corner/calculations/pace_index_constants_place_enrollment_in_behind_and_critical_bands
        """
        world = _two_enrollment_placement(api)
        validate_success(
            api.advance_clock_to("2026-08-21T00:00:00Z", DISTRICT_ADMIN_HEADERS)
        )

        ahead = fx.read_enrollment(api, world["ahead"]["id"])
        assert_close(ahead["pace_index"], 0.750, "pace index of the faster enrollment")
        assert ahead["pacing_flag"] == PacingFlag.BEHIND.value

        behind = fx.read_enrollment(api, world["behind"]["id"])
        assert_close(behind["pace_index"], 0.500, "pace index of the slower enrollment")
        assert behind["pacing_flag"] == PacingFlag.CRITICAL.value

        assert ahead["pacing_flag"] != PacingFlag.ON_PACE.value
        assert behind["pacing_flag"] != PacingFlag.ON_PACE.value

        placement = fx.read_placement(api, world["placement"]["id"])
        assert_close(placement["pacing_component"], 0.6250, "pacing component")


class TestRatePrecisionIsCarriedToFourPlaces:
    """A repeating quotient is stored at four places, not two."""

    def test_twenty_of_thirty_days_stores_a_four_place_rate(self, api):
        """The rate reads 0.6667 rather than 0.67 or 0.6666, and the readiness base
        carries that precision through the 0.50 weight to 0.3334.

        PRD: "From those, `attendance_rate` is derived as days present divided by
        days enrolled, rounded to 4 decimal places, and it reads null while
        `days_enrolled` is still zero."

        Design: Corner/calculations/attendance_rate_precision_four_decimal_places
        """
        home_school = fx.open_home_school(api)
        center = fx.open_center(api, name="Cedar AEC")
        student = fx.register_student(
            api, home_school["id"], grade_level=11, cohort_year=2027
        )
        referral = fx.screened_referral(
            api, student["id"], center["id"], home_school["id"]
        )
        fx.offer_seat(api, referral["id"], center["id"])
        placement = fx.accept_seat(
            api,
            referral["id"],
            home_school["id"],
            credit_policy=CreditPolicy.SEAT_TIME.value,
        )
        assert placement["attendance_rate"] is None

        logged = fx.log_attendance(api, placement["id"], 20, 30)
        assert logged["days_present"] == 20
        assert logged["days_enrolled"] == 30
        assert_close(logged["attendance_rate"], 0.6667, "attendance rate")
        assert_close(logged["attendance_component"], 0.6667, "attendance component")
        assert_close(logged["pacing_component"], 0.0000, "pacing component")
        assert_close(logged["credit_component"], 0.0000, "credit component")
        assert_readiness_figures(logged, base_score=0.3334, bonus=0.0000, score=0.3334)
        assert logged["re_entry_eligible"] is False


def _senior_plan_world(api):
    """A grade-12 owner of a five-credit plan, so the grade expectation is the
    whole requirement and the two posture edges sit at 4.00 and 4.75."""
    home_school = fx.open_home_school(api)
    student = fx.register_student(
        api, home_school["id"], grade_level=12, cohort_year=2026
    )
    plan = fx.open_active_plan(
        api,
        student["id"],
        required_credits_total=5.00,
        grade_replacement_policy=GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
        projected_completion_term="2026-S2",
    )
    return {
        "home_school": home_school,
        "student": student,
        "plan": plan,
        "first_course": fx.publish_course(api, **dict(ALG1, credit_value=2.00)),
        "second_course": fx.publish_course(api, **dict(ENG1, credit_value=2.00)),
        "third_course": fx.publish_course(
            api,
            code="ART1",
            title="Studio Art",
            subject_area=SubjectArea.ELECTIVE.value,
            credit_value=0.75,
            total_modules=3,
            required_seat_hours=45.00,
            pacing_days=30,
        ),
    }


class TestPlanPostureEdgesAreInclusive:
    """Eighty and ninety-five percent of the grade expectation are both >=."""

    def test_exactly_eighty_percent_of_the_expectation_reads_at_risk(self, api):
        """Two credits against a 5.00 expectation read OFF_TRACK, and the fourth
        credit lands exactly on 4.00 and flips the posture to AT_RISK.

        PRD: "Otherwise, if the earned credits are at least eighty percent of
        that same expectation, again rounded to 2 decimal places before comparing,
        the posture is `AT_RISK`."

        Design: Corner/calculations/plan_posture_threshold_boundaries_at_eighty_and_ninety_five_percent
        """
        world = _senior_plan_world(api)
        fx.post_prior_record(
            api,
            world["student"]["id"],
            world["first_course"]["id"],
            term_code="2025FA",
            original_percent=92.00,
            credits_attempted=2.00,
            outcome=PriorOutcome.PASSED.value,
        )

        off_track = fx.read_plan(api, world["plan"]["id"])
        assert_close(off_track["expected_credits_by_grade"], 5.00, "expected credits")
        assert_close(off_track["credits_earned"], 2.00, "plan credits earned")
        assert_close(off_track["credits_remaining"], 3.00, "plan credits remaining")
        assert off_track["posture"] == PlanPosture.OFF_TRACK.value

        fx.post_prior_record(
            api,
            world["student"]["id"],
            world["second_course"]["id"],
            term_code="2025FA",
            original_percent=92.00,
            credits_attempted=2.00,
            outcome=PriorOutcome.PASSED.value,
        )

        at_risk = fx.read_plan(api, world["plan"]["id"])
        assert_close(at_risk["credits_earned"], 4.00, "plan credits earned")
        assert_close(at_risk["credits_remaining"], 1.00, "plan credits remaining")
        assert at_risk["posture"] == PlanPosture.AT_RISK.value

    def test_exactly_ninety_five_percent_of_the_expectation_reads_on_track(self, api):
        """A three-quarter credit row lands the ledger exactly on 4.75 and the
        posture reads ON_TRACK while the plan is still ACTIVE.

        PRD: "Otherwise, if the earned credits are at least ninety-five percent of
        the expected credits by grade — that threshold itself rounded to 2 decimal
        places before the comparison is made — the posture is `ON_TRACK`."

        Design: Corner/calculations/plan_posture_threshold_boundaries_at_eighty_and_ninety_five_percent
        """
        world = _senior_plan_world(api)
        for course_key, term in (
            ("first_course", "2025FA"),
            ("second_course", "2025FA"),
        ):
            fx.post_prior_record(
                api,
                world["student"]["id"],
                world[course_key]["id"],
                term_code=term,
                original_percent=92.00,
                credits_attempted=2.00,
                outcome=PriorOutcome.PASSED.value,
            )
        fx.post_prior_record(
            api,
            world["student"]["id"],
            world["third_course"]["id"],
            term_code="2025SP",
            original_percent=92.00,
            credits_attempted=0.75,
            outcome=PriorOutcome.PASSED.value,
        )

        plan = fx.read_plan(api, world["plan"]["id"])
        assert_close(plan["credits_earned"], 4.75, "plan credits earned")
        assert_close(plan["credits_remaining"], 0.25, "plan credits remaining")
        assert plan["posture"] == PlanPosture.ON_TRACK.value
        assert plan["status"] == PlanStatus.ACTIVE.value

        student = fx.read_student(api, world["student"]["id"])
        assert_close(student["credits_earned_total"], 4.75, "credits earned total")


class TestTheGpaInputSetDiffersFromTheCreditLedger:
    """The failed row counts in the GPA and not in the credit total; the
    incomplete row counts in neither."""

    def test_the_failed_row_counts_and_the_incomplete_row_never_does(self, api):
        """Across one PASSED, one FAILED and one INCOMPLETE row the credit total is
        1.00 while the GPA divides 3.000 quality points by 2.00 credits to reach
        1.50.

        PRD: "The first kind is historical: every prior course record of the student
        whose `replacement_status` is `NOT_REPLACED` and whose `outcome` is either
        `FAILED` or `PASSED` contributes its `original_grade_code` and its
        `credits_attempted`; a row whose outcome is `INCOMPLETE` never counts."

        Design: Corner/calculations/gpa_aggregation_counts_failed_rows_but_never_incomplete_rows
        """
        home_school = fx.open_home_school(api)
        student = fx.register_student(
            api, home_school["id"], grade_level=11, cohort_year=2027
        )
        passed_course = fx.publish_course(api, **ALG1)
        failed_course = fx.publish_course(api, **ENG1)
        incomplete_course = fx.publish_course(
            api, **dict(ALG1, code="BIO1", title="Biology I", subject_area=SubjectArea.SCIENCE.value)
        )

        passed = fx.post_prior_record(
            api,
            student["id"],
            passed_course["id"],
            term_code="2025FA",
            original_percent=85.00,
            credits_attempted=1.00,
            outcome=PriorOutcome.PASSED.value,
        )
        failed = fx.post_prior_record(
            api,
            student["id"],
            failed_course["id"],
            term_code="2025FA",
            original_percent=40.00,
            credits_attempted=1.00,
            outcome=PriorOutcome.FAILED.value,
        )
        incomplete = fx.post_prior_record(
            api,
            student["id"],
            incomplete_course["id"],
            term_code="2025SP",
            original_percent=55.00,
            credits_attempted=1.00,
            outcome=PriorOutcome.INCOMPLETE.value,
        )
        assert passed["original_grade_code"] == GradeCode.B.value
        assert failed["original_grade_code"] == GradeCode.F.value
        assert incomplete["original_grade_code"] == GradeCode.I.value
        assert incomplete["replacement_status"] == ReplacementStatus.NOT_REPLACED.value

        student = fx.read_student(api, student["id"])
        assert_close(student["credits_earned_total"], 1.00, "credits earned total")
        assert_close(student["gpa"], 1.50, "gpa")
        assert_close(student["alt_ed_credits"], 0.00, "alt ed credits")
        assert_close(student["ncaa_acceptable_credits"], 0.00, "ncaa credits")


BIO1_ONLINE = {
    "code": "BIO1",
    "title": "Biology I",
    "subject_area": SubjectArea.SCIENCE.value,
    "credit_value": 1.00,
    "modality": Modality.ONLINE.value,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "proctoring_required": True,
    "proctored_exam_weight": 0.40,
    "ncaa_approved": True,
    "min_passing_percent": 60.00,
}


def _clean_proctored_submission(api):
    """An ONLINE, NCAA-approved, proctored enrollment at full modules with one
    clean COMPLETED exam scoring 78.00, submitted at 84.00 by the teacher."""
    world = fx.proctored_world(
        api,
        credit_policy=CreditPolicy.COMPETENCY.value,
        course_overrides=dict(BIO1_ONLINE),
        plan_overrides={"required_credits_total": 24.00},
        referral_overrides={
            "deficiency_credits": 6.00,
            "behavior_incident_count": 1,
            "days_disengaged": 6,
        },
        student_overrides={"grade_level": 11, "cohort_year": 2027},
    )
    fx.report_progress(
        api,
        world["enrollment"]["id"],
        modules_passed_delta=8,
        seat_hours_delta=10.00,
        module_avg_percent=84.00,
    )
    session = fx.book_proctor_session(
        api,
        world["enrollment"]["id"],
        world["station"]["id"],
        world["center"]["id"],
        scheduled_start="2026-08-05T09:00:00.000Z",
        scheduled_end="2026-08-05T10:00:00.000Z",
    )
    fx.complete_proctor_session(
        api, session["id"], world["center"]["id"], 78.00, integrity_incident=False
    )
    world["session"] = session
    world["enrollment"] = fx.submit_work(api, world["enrollment"]["id"], 84.00)
    return world


class TestOneAwardExercisesTheWholeCodingChain:
    """Mastery, modality, grade band and NCAA acceptance on a single row."""

    def test_blended_mastery_of_eighty_one_point_six_pays_the_full_credit(self, api):
        """Sixty percent of 84.00 plus forty percent of 78.00 is 81.60, which clears
        the top competency band, so the full 1.00 credit posts on ten seat hours.

        PRD: "Under `COMPETENCY` the student is paid for demonstrated mastery, in
        three bands: when `mastery_pct` is at least 80.00 the award is the course's
        full `credit_value` regardless of seat hours or unfinished modules; when
        `mastery_pct` is at least 70.00 but below 80.00 the award is the credit value
        multiplied by the module fraction — `modules_passed`, held at a maximum of
        the course's `total_modules`, divided by `total_modules`, rounded to 4
        decimal places — then floored down to a multiple of 0.25; and when
        `mastery_pct` is below 70.00 the award computes to 0.00 and is refused with
        `ERR_MASTERY_NOT_MET`."

        Design: Corner/calculations/transcript_coding_propagates_modality_grade_and_ncaa_acceptance
        """
        world = _clean_proctored_submission(api)

        enrollment = fx.read_enrollment(api, world["enrollment"]["id"])
        assert_close(enrollment["mastery_pct"], 81.60, "blended mastery")
        assert_close(enrollment["seat_hours_logged"], 10.00, "seat hours logged")

        award = fx.award_credit(
            api, world["enrollment"]["id"], world["plan"]["id"], REGISTRAR_HEADERS
        )
        assert_close(award["credits_awarded"], 1.00, "credits awarded")
        assert award["award_basis"] == CreditPolicy.COMPETENCY.value
        assert award["posted_on"] == "2026-08-01"
        assert award["prior_course_record_id"] is None

        student = fx.read_student(api, world["student"]["id"])
        assert_close(student["alt_ed_credits"], 1.00, "alt ed credits")
        assert_close(student["gpa"], 3.00, "gpa")

    def test_the_posted_row_carries_every_transcript_code(self, api):
        """The ONLINE modality codes OL, the code reads BIO1-OL-AE, the 84.00 final
        percent codes B, the row is alt-ed flagged, NCAA acceptance holds on all four
        conjuncts and the replacement mode is NONE for new credit.

        PRD: "It also carries the district's transcript coding: `modality_code` is
        `OL` for an `ONLINE` course, `PK` for `PACKET` and `BL` for `BLENDED`;
        `transcript_code` is the course's `code`, then a hyphen, then that modality
        code, then the literal suffix `-AE`; `alt_ed_flag` is always true, because
        every award posted through this system is alternative-education coded;
        `transcript_grade_code` is derived from the enrollment's `final_percent` by
        band — `A` at 90 or above, `B` at 80 or above, `C` at 70 or above, and
        otherwise `D`, there being no `F` band since a sub-passing percent cannot be
        posted at all; and `ncaa_acceptable` is true only when all four of the
        following hold together — the course's `ncaa_approved` is true, the course's
        `proctoring_required` is true, a `COMPLETED` proctored session with
        `integrity_incident` false exists for the enrollment, and `credits_awarded`
        equals the course's full `credit_value`."

        Design: Corner/calculations/transcript_coding_propagates_modality_grade_and_ncaa_acceptance
        """
        world = _clean_proctored_submission(api)

        award = fx.award_credit(
            api, world["enrollment"]["id"], world["plan"]["id"], REGISTRAR_HEADERS
        )
        assert award["modality_code"] == ModalityCode.ONLINE.value
        assert_transcript_coding(award, "BIO1", ModalityCode.ONLINE.value, GradeCode.B.value)
        assert award["ncaa_acceptable"] is True
        assert award["grade_replacement_mode"] == GradeReplacementMode.NONE.value

        student = fx.read_student(api, world["student"]["id"])
        assert_close(
            student["ncaa_acceptable_credits"], 1.00, "ncaa acceptable credits"
        )
        assert_close(student["credits_earned_total"], 1.00, "credits earned total")
