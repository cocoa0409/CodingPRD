"""Difficulty rule: transitive_cascade — term close cascade and showcase stage cascade."""
from test_helpers import (
    TEST_USERS, api_client, validate_success,
    create_student, setup_open_term_with_section, enroll_with_fresh_version,
    confirm_enrollment, run_term_to_close, get_term, get_section, get_enrollment,
    get_student, setup_staged_showcase, get_venue_slot,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]


class TestTermCloseCascade:
    def test_close_cascades_term_section_enrollment(self):
        """PRD §3.1: "Closing the term moves it `IN_SESSION → CLOSED` (the term's
        terminal state): every `RUNNING` section becomes `COMPLETED`, every
        `CONFIRMED` enrollment on those sections becomes `COMPLETED`"

        Design: Difficulty/transitive_cascade/term_close_cascade_section_enrollment_student
        """
        ctx = setup_open_term_with_section(capacity=1)
        student = create_student()
        enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
        confirm_enrollment(enr["id"])
        term = run_term_to_close(ctx["section"]["id"])
        assert term["status"] == "CLOSED"
        section = get_section(ctx["section"]["id"])
        assert section["status"] == "COMPLETED"
        enrollment = get_enrollment(enr["id"])
        assert enrollment["status"] == "CREDITED"

    def test_close_cascades_into_student_alumni(self):
        """PRD §3.3: "Either way the level's `code` is added to the student's
        `completed_level_codes`, and the moment any enrollment of the student
        reaches `CREDITED`, the student's `is_alumni` flips to true."

        Design: Difficulty/transitive_cascade/term_close_cascade_section_enrollment_student
        """
        ctx = setup_open_term_with_section(capacity=1)
        student = create_student()
        enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
        confirm_enrollment(enr["id"])
        run_term_to_close(ctx["section"]["id"])
        stu = get_student(student["id"])
        assert ctx["level"]["code"] in stu["completed_level_codes"]
        assert stu["is_alumni"] is True


class TestShowcaseStageCascade:
    def test_stage_pass_credits_enrollment(self):
        """PRD §3.5: "On staging, the venue slot moves `RESERVED → BOOKED`; each
        enrollment graded `PASS` cascades `COMPLETED → CREDITED` with the
        consequences of §3.3 (level code into `completed_level_codes`, `is_alumni`
        flipping, `graded_showcase_id` recorded); each enrollment graded `FAIL`
        remains `COMPLETED` and earns no credit."

        Design: Difficulty/transitive_cascade/showcase_stage_cascade_enrollment_credit_alumni
        """
        ctx = setup_staged_showcase()
        staged = validate_success(api_client.stage_showcase(
            ctx["showcase"]["id"], {ctx["enrollment"]["id"]: "PASS"}, PD))
        assert staged["status"] == "STAGED"
        enrollment = get_enrollment(ctx["enrollment"]["id"])
        assert enrollment["status"] == "CREDITED"

    def test_stage_pass_books_slot_and_updates_student(self):
        """PRD §3.5: "On staging, the venue slot moves `RESERVED → BOOKED`; each
        enrollment graded `PASS` cascades `COMPLETED → CREDITED` with the
        consequences of §3.3 (level code into `completed_level_codes`, `is_alumni`
        flipping, `graded_showcase_id` recorded); each enrollment graded `FAIL`
        remains `COMPLETED` and earns no credit."

        Design: Difficulty/transitive_cascade/showcase_stage_cascade_enrollment_credit_alumni
        """
        ctx = setup_staged_showcase()
        validate_success(api_client.stage_showcase(
            ctx["showcase"]["id"], {ctx["enrollment"]["id"]: "PASS"}, PD))
        slot = get_venue_slot(ctx["slot"]["id"])
        assert slot["status"] == "BOOKED"
        stu = get_student(ctx["student"]["id"])
        assert ctx["level"]["code"] in stu["completed_level_codes"]
        assert stu["is_alumni"] is True
