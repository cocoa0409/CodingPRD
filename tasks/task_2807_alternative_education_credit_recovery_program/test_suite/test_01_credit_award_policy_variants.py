"""The seat-time and competency credit variants, and the grade-replacement
policy that decides what the transcript GPA reports."""

from test_helpers import (
    AwardStatus,
    CreditPolicy,
    GradeReplacementMode,
    GradeReplacementPolicy,
    PriorOutcome,
    ProgressState,
    ReplacementStatus,
    assert_close,
    assert_credit_award,
    fixtures as fx,
    validate_success,
)

COURSE = {
    "credit_value": 1.00,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "proctoring_required": False,
    "ncaa_approved": False,
    "min_passing_percent": 60.00,
}


def _two_placements_one_center(api, policy_a, policy_b):
    """One school, one centre, one course and two students placed under the two
    credit policies, each with an ACTIVE plan."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api)
    course = fx.publish_course(api, **COURSE)
    placed = []
    for policy in (policy_a, policy_b):
        student = fx.register_student(api, home_school["id"], grade_level=9)
        plan = fx.open_active_plan(api, student["id"], required_credits_total=24.00)
        referral = fx.screened_referral(
            api, student["id"], center["id"], home_school["id"]
        )
        fx.offer_seat(api, referral["id"], center["id"])
        placement = fx.accept_seat(
            api, referral["id"], home_school["id"], credit_policy=policy
        )
        placed.append({"student": student, "plan": plan, "placement": placement})
    return home_school, center, course, placed


def _identical_coursework(api, course, placed, prior_records=None):
    """Give both placements byte-identical coursework and submit both."""
    enrollments = []
    for index, entry in enumerate(placed):
        if prior_records is None:
            enrollment = fx.enroll_new_credit(
                api, entry["placement"]["id"], course["id"]
            )
        else:
            enrollment = fx.enroll_recovery(
                api,
                entry["placement"]["id"],
                course["id"],
                prior_records[index]["id"],
            )
        fx.report_progress(
            api,
            enrollment["id"],
            modules_passed_delta=7 if prior_records is None else 8,
            seat_hours_delta=30.00 if prior_records is None else 55.00,
            module_avg_percent=84.00,
        )
        enrollments.append(fx.submit_work(api, enrollment["id"], 84.00))
    return enrollments


class TestSeatTimeVersusCompetencyOnIdenticalCoursework:
    """The same coursework pays differently under the two credit policies."""

    def test_seat_time_pays_half_a_credit_where_competency_pays_the_full_value(
        self, api, second_registrar_headers
    ):
        """Seven of eight modules and thirty of sixty seat hours at a mastery of
        84.00 post 0.50 credits on the seat-time placement and 1.00 on the
        competency placement.

        PRD: "Under `SEAT_TIME` the student is paid for time in the seat: the
        seat fraction is `seat_hours_logged` divided by the course's
        `required_seat_hours`, rounded to 4 decimal places and held at a maximum
        of 1.0000, and the credits are the course's `credit_value` multiplied by
        that seat fraction, then floored down to a multiple of 0.25."

        Design: Difficulty/dual_variant_calc/seat_time_vs_competency_award_same_progress_inputs
        """
        _, _, course, placed = _two_placements_one_center(
            api, CreditPolicy.SEAT_TIME.value, CreditPolicy.COMPETENCY.value
        )
        seat_time_enrollment, competency_enrollment = _identical_coursework(
            api, course, placed
        )

        assert_close(seat_time_enrollment["mastery_pct"], 84.00, "seat-time mastery")
        assert_close(
            competency_enrollment["mastery_pct"], 84.00, "competency mastery"
        )

        seat_time_award = validate_success(
            api.award_credit(
                seat_time_enrollment["id"],
                {"expected_graduation_plan_version": fx.plan_version(api, placed[0]["plan"]["id"])},
                second_registrar_headers,
            ),
            201,
        )
        competency_award = validate_success(
            api.award_credit(
                competency_enrollment["id"],
                {"expected_graduation_plan_version": fx.plan_version(api, placed[1]["plan"]["id"])},
                second_registrar_headers,
            ),
            201,
        )

        assert_close(seat_time_award["credits_awarded"], 0.50, "seat-time credits")
        assert_close(competency_award["credits_awarded"], 1.00, "competency credits")
        assert_close(
            competency_award["credits_awarded"] - seat_time_award["credits_awarded"],
            0.50,
            "divergence produced only by the placement's credit policy",
        )

    def test_award_basis_is_copied_from_the_placement_credit_policy(
        self, api, second_registrar_headers
    ):
        """Each posted row names the policy that governed it, and both rows
        carry the same transcript grade band and no grade replacement.

        PRD: "That row carries the `course_enrollment_id` it was awarded for,
        the `student_id` denormalized from the enrollment's placement so the
        transcript can be queried by student, the `prior_course_record_id` it
        replaces or averages against when there is one, the computed
        `credits_awarded`, an `award_basis` copied verbatim from the placement's
        `credit_policy`, and a `posted_on` stamp holding the logical clock date
        at posting."

        Design: Difficulty/dual_variant_calc/seat_time_vs_competency_award_same_progress_inputs
        """
        _, _, course, placed = _two_placements_one_center(
            api, CreditPolicy.SEAT_TIME.value, CreditPolicy.COMPETENCY.value
        )
        enrollments = _identical_coursework(api, course, placed)

        awards = [
            validate_success(
                api.award_credit(
                    enrollment["id"],
                    {"expected_graduation_plan_version": fx.plan_version(api, entry["plan"]["id"])},
                    second_registrar_headers,
                ),
                201,
            )
            for enrollment, entry in zip(enrollments, placed)
        ]

        for award in awards:
            assert_credit_award(award)
            assert award["status"] == AwardStatus.POSTED.value
            assert award["transcript_grade_code"] == "B"
            assert award["grade_replacement_mode"] == GradeReplacementMode.NONE.value
            assert award["prior_course_record_id"] is None
        assert awards[0]["award_basis"] == CreditPolicy.SEAT_TIME.value
        assert awards[1]["award_basis"] == CreditPolicy.COMPETENCY.value
        assert awards[0]["student_id"] == placed[0]["student"]["id"]
        assert awards[1]["student_id"] == placed[1]["student"]["id"]

    def test_the_two_ledgers_diverge_while_both_transcripts_report_the_same_gpa(
        self, api, second_registrar_headers
    ):
        """The plan ledgers separate at 0.50 against 1.00 credits, yet a single
        B row gives both students a GPA of 3.00.

        PRD: "`credits_earned` mirrors the owner's `credits_earned_total`, which
        is the sum of `credits_attempted` across the student's historical rows
        whose `outcome` is `PASSED`, plus the sum of `credits_awarded` across
        the student's credit awards whose `status` is `POSTED`, the total rounded
        to 2 decimal places."

        Design: Difficulty/dual_variant_calc/seat_time_vs_competency_award_same_progress_inputs
        """
        _, _, course, placed = _two_placements_one_center(
            api, CreditPolicy.SEAT_TIME.value, CreditPolicy.COMPETENCY.value
        )
        enrollments = _identical_coursework(api, course, placed)
        for enrollment, entry in zip(enrollments, placed):
            validate_success(
                api.award_credit(
                    enrollment["id"],
                    {"expected_graduation_plan_version": fx.plan_version(api, entry["plan"]["id"])},
                    second_registrar_headers,
                ),
                201,
            )

        seat_time_plan = fx.read_plan(api, placed[0]["plan"]["id"])
        competency_plan = fx.read_plan(api, placed[1]["plan"]["id"])
        assert_close(seat_time_plan["credits_earned"], 0.50, "seat-time plan ledger")
        assert_close(competency_plan["credits_earned"], 1.00, "competency plan ledger")

        seat_time_student = fx.read_student(api, placed[0]["student"]["id"])
        competency_student = fx.read_student(api, placed[1]["student"]["id"])
        assert_close(seat_time_student["credits_earned_total"], 0.50, "student total")
        assert_close(competency_student["credits_earned_total"], 1.00, "student total")
        assert_close(seat_time_student["gpa"], 3.00, "seat-time gpa")
        assert_close(competency_student["gpa"], 3.00, "competency gpa")


class TestGradeReplacementPolicyDivergence:
    """Identical failed history and identical recovery work produce two
    materially different transcripts."""

    @staticmethod
    def _two_recoveries(api):
        home_school = fx.open_home_school(api)
        center = fx.open_center(api)
        course = fx.publish_course(api, **COURSE)
        entries = []
        for policy in (
            GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
            GradeReplacementPolicy.AVERAGE_ON_RECOVERY.value,
        ):
            student = fx.register_student(api, home_school["id"], grade_level=9)
            prior_record = fx.post_prior_record(
                api,
                student["id"],
                course["id"],
                original_percent=42.00,
                credits_attempted=1.00,
                outcome=PriorOutcome.FAILED.value,
            )
            plan = fx.open_active_plan(
                api,
                student["id"],
                required_credits_total=24.00,
                grade_replacement_policy=policy,
            )
            referral = fx.screened_referral(
                api, student["id"], center["id"], home_school["id"]
            )
            fx.offer_seat(api, referral["id"], center["id"])
            placement = fx.accept_seat(
                api,
                referral["id"],
                home_school["id"],
                credit_policy=CreditPolicy.COMPETENCY.value,
            )
            enrollment = fx.enroll_recovery(
                api, placement["id"], course["id"], prior_record["id"]
            )
            fx.report_progress(
                api,
                enrollment["id"],
                modules_passed_delta=8,
                seat_hours_delta=55.00,
                module_avg_percent=84.00,
            )
            enrollment = fx.submit_work(api, enrollment["id"], 84.00)
            entries.append(
                {
                    "student": student,
                    "prior_record": prior_record,
                    "plan": plan,
                    "enrollment": enrollment,
                }
            )
        return entries

    def test_replacement_mode_follows_the_plan_policy_and_stamps_the_failed_row(
        self, api, second_registrar_headers
    ):
        """The REPLACE_ON_RECOVERY award posts FULL_REPLACEMENT and stamps its
        backing row REPLACED; the AVERAGE_ON_RECOVERY award posts AVERAGED and
        leaves the row NOT_REPLACED.

        PRD: "The row's `grade_replacement_mode` is `NONE` when
        `enrollment_type` is `NEW_CREDIT`; otherwise it is `FULL_REPLACEMENT`
        when the student's plan carries `grade_replacement_policy` of
        `REPLACE_ON_RECOVERY`, and `AVERAGED` when the plan carries
        `AVERAGE_ON_RECOVERY`."

        Design: Difficulty/dual_variant_calc/gpa_replace_vs_average_policy_divergence
        """
        entries = self._two_recoveries(api)
        awards = [
            validate_success(
                api.award_credit(
                    entry["enrollment"]["id"],
                    {
                        "expected_graduation_plan_version": fx.plan_version(
                            api, entry["plan"]["id"]
                        )
                    },
                    second_registrar_headers,
                ),
                201,
            )
            for entry in entries
        ]

        assert (
            awards[0]["grade_replacement_mode"]
            == GradeReplacementMode.FULL_REPLACEMENT.value
        )
        assert awards[1]["grade_replacement_mode"] == GradeReplacementMode.AVERAGED.value
        replaced = fx.read_prior_record(api, entries[0]["prior_record"]["id"])
        averaged = fx.read_prior_record(api, entries[1]["prior_record"]["id"])
        assert replaced["replacement_status"] == ReplacementStatus.REPLACED.value
        assert averaged["replacement_status"] == ReplacementStatus.NOT_REPLACED.value
        assert replaced["original_grade_code"] == "F"
        assert averaged["original_grade_code"] == "F"

    def test_the_averaged_transcript_reports_a_materially_lower_gpa(
        self, api, second_registrar_headers
    ):
        """Both students bank 1.00 credit, but the replaced history reports a
        GPA of 3.00 while the averaged history reports 1.50.

        PRD: "Under `AVERAGE_ON_RECOVERY`, a recovery award posts with
        `grade_replacement_mode` of `AVERAGED`, the failed historical row stays
        `NOT_REPLACED`, and both rows count — the original `F` contributing 0.000
        quality points against its full `credits_attempted` while the recovery
        contributes its own, with the denominator holding both attempts."

        Design: Difficulty/dual_variant_calc/gpa_replace_vs_average_policy_divergence
        """
        entries = self._two_recoveries(api)
        for entry in entries:
            validate_success(
                api.award_credit(
                    entry["enrollment"]["id"],
                    {
                        "expected_graduation_plan_version": fx.plan_version(
                            api, entry["plan"]["id"]
                        )
                    },
                    second_registrar_headers,
                ),
                201,
            )

        replaced_student = fx.read_student(api, entries[0]["student"]["id"])
        averaged_student = fx.read_student(api, entries[1]["student"]["id"])
        assert_close(
            replaced_student["credits_earned_total"], 1.00, "replaced credits earned"
        )
        assert_close(
            averaged_student["credits_earned_total"], 1.00, "averaged credits earned"
        )
        assert_close(replaced_student["gpa"], 3.00, "gpa under REPLACE_ON_RECOVERY")
        assert_close(averaged_student["gpa"], 1.50, "gpa under AVERAGE_ON_RECOVERY")

    def test_the_recovery_award_records_the_row_it_recovers_and_banks_the_credit(
        self, api, second_registrar_headers
    ):
        """Each recovery award cites its backing historical row, posts the full
        1.00 credit and leaves its enrollment in AWARDED.

        PRD: "**Hop 1** moves `progress_state` from `SUBMITTED_FOR_AWARD` to
        `AWARDED` and creates a credit award in `POSTED` status."

        Design: Difficulty/dual_variant_calc/gpa_replace_vs_average_policy_divergence
        """
        entries = self._two_recoveries(api)
        for entry in entries:
            award = validate_success(
                api.award_credit(
                    entry["enrollment"]["id"],
                    {
                        "expected_graduation_plan_version": fx.plan_version(
                            api, entry["plan"]["id"]
                        )
                    },
                    second_registrar_headers,
                ),
                201,
            )
            assert award["prior_course_record_id"] == entry["prior_record"]["id"]
            assert award["status"] == AwardStatus.POSTED.value
            assert_close(award["credits_awarded"], 1.00, "recovery credits")
            enrollment = fx.read_enrollment(api, entry["enrollment"]["id"])
            assert enrollment["progress_state"] == ProgressState.AWARDED.value
            assert_close(enrollment["awarded_credits"], 1.00, "enrollment awarded_credits")
