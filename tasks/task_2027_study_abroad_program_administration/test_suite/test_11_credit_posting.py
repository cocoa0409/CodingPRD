"""Return transcript and credit posting (PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_approved_preapproval,
    create_pending_preapproval,
    create_returned_home_application,
    create_transcript_posting,
    setup_open_program_with_application,
    setup_returned_home_with_approved_courses,
    validate_error,
    validate_success,
    api_client,
    COORD_A_HEADERS,
    FACULTY_HEADERS,
)


class TestProvisionalVsFinal:
    def test_credit_posting_provisional_vs_final(self, api):
        """PRD §3.8: "Both reuse the pinned per-course rule of §3.3: each line's
        `host_credits` — read from the referenced pre-approval — is multiplied by the
        agreement's `credit_conversion_factor` and rounded to the nearest half credit, ties
        away from zero, before any summation. `provisional_credits` sums those per-course
        values over **all** transcript lines regardless of grade, giving the planning view;
        `final_credits` sums only lines whose `grade_points` are at least 2.0, with weaker
        lines contributing nothing."

        Design: Difficulty/dual_variant_calc/credit_posting_provisional_vs_final
        """
        program, student, application, cpas = setup_returned_home_with_approved_courses(
            courses=[("HIST310", 3), ("ART220", 5)],
        )
        posting = create_transcript_posting(
            application["id"],
            [
                {"course_preapproval_id": cpas[0]["id"], "grade_points": 3.0},
                {"course_preapproval_id": cpas[1]["id"], "grade_points": 1.7},
            ],
        )
        # factor 0.75: HIST310 host 3 -> 2.25 -> 2.5; ART220 host 5 -> 3.75 -> 4.0.
        assert posting["provisional_credits"] == pytest.approx(6.5, abs=1e-9), (
            f"provisional_credits sums ALL lines (2.5 + 4.0), got {posting['provisional_credits']}"
        )
        assert posting["final_credits"] == pytest.approx(2.5, abs=1e-9), (
            "final_credits counts only grade >= 2.0 lines; ART220 grade 1.7 contributes 0, "
            f"got {posting['final_credits']}"
        )
        assert posting["provisional_credits"] != posting["final_credits"]

    def test_credit_posting_all_passing_lines(self, api):
        """PRD §3.8: "`final_credits` sums only lines whose `grade_points` are at least 2.0,
        with weaker lines contributing nothing."

        Design: Difficulty/dual_variant_calc/credit_posting_provisional_vs_final
        """
        program, student, application, cpas = setup_returned_home_with_approved_courses(
            courses=[("HIST310", 3), ("ART220", 5)],
        )
        posting = create_transcript_posting(
            application["id"],
            [
                {"course_preapproval_id": cpas[0]["id"], "grade_points": 3.0},
                {"course_preapproval_id": cpas[1]["id"], "grade_points": 2.0},
            ],
        )
        # Both lines at grade >= 2.0: variants converge at 2.5 + 4.0.
        assert posting["provisional_credits"] == pytest.approx(6.5, abs=1e-9)
        assert posting["final_credits"] == pytest.approx(6.5, abs=1e-9)


class TestPostCascade:
    def test_credit_post_posting_cascade(self, api):
        """PRD §3.8: "Posting stamps `posted_by` with the caller's `X-User-ID`, moves the
        posting to `POSTED` (terminal), and cascades to the application: `RETURNED_HOME` →
        `CREDIT_POSTED`, with the application's `transfer_credits_posted` set to the
        posting's `final_credits`."

        Design: Difficulty/transitive_cascade/credit_post_posting_cascade
        """
        program, student, application, cpas = setup_returned_home_with_approved_courses(
            courses=[("HIST310", 3), ("ART220", 5)],
        )
        posting = create_transcript_posting(
            application["id"],
            [
                {"course_preapproval_id": cpas[0]["id"], "grade_points": 3.0},
                {"course_preapproval_id": cpas[1]["id"], "grade_points": 1.7},
            ],
        )
        posted = validate_success(api.post_credit_posting(posting["id"], FACULTY_HEADERS))
        assert posted["status"] == "POSTED"
        assert posted["posted_by"] == "fac-1"

        app_after = validate_success(
            api.get_application(application["id"], COORD_A_HEADERS)
        )
        assert app_after["status"] == "CREDIT_POSTED"
        assert app_after["transfer_credits_posted"] == pytest.approx(2.5, abs=1e-9), (
            "The application receives the posting's final_credits (grade-filtered), "
            f"got {app_after['transfer_credits_posted']}"
        )

    def test_post_twice_returns_invalid_state(self, api):
        """PRD §3.8: "A `FacultyApprover` posts a `PENDING` credit posting ..." and
        PRD §2.10: "The target resource must be in a valid from-state for the requested
        transition ... otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/transitive_cascade/credit_post_posting_cascade
        """
        program, student, application, cpas = setup_returned_home_with_approved_courses(
            courses=[("HIST310", 3)],
        )
        posting = create_transcript_posting(
            application["id"],
            [{"course_preapproval_id": cpas[0]["id"], "grade_points": 3.0}],
        )
        validate_success(api.post_credit_posting(posting["id"], FACULTY_HEADERS))
        resp = api.post_credit_posting(posting["id"], FACULTY_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPostingValidation:
    def test_preapproval_invalid_on_posting(self, api):
        """PRD §3.8: "every `course_preapproval_id` must reference a pre-approval that
        belongs to this same application and is in `APPROVED` status
        (`ERR_PREAPPROVAL_INVALID`)."

        Design: Corner/validations/preapproval_invalid_on_posting
        """
        # One HIST310 pre-approval left PENDING (never reviewed).
        program, student, application, _cpas = setup_returned_home_with_approved_courses(
            courses=[("ART220", 5)],
        )
        pending_cpa = create_pending_preapproval(
            {"id": application["id"]}, student, "HIST310", 3,
        )
        resp = api.create_credit_posting(
            application["id"],
            {"lines": [{"course_preapproval_id": pending_cpa["id"], "grade_points": 3.0}]},
            FACULTY_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_PREAPPROVAL_INVALID)

    def test_duplicate_credit_posting_blocked(self, api):
        """PRD §3.8: "An application carries at most one credit posting in `PENDING` or
        `POSTED` (`ERR_DUPLICATE_CREDIT_POSTING`)."

        Design: Corner/validations/duplicate_credit_posting_blocked
        """
        program, student, application, cpas = setup_returned_home_with_approved_courses(
            courses=[("HIST310", 3)],
        )
        create_transcript_posting(
            application["id"],
            [{"course_preapproval_id": cpas[0]["id"], "grade_points": 3.0}],
        )
        resp = api.create_credit_posting(
            application["id"],
            {"lines": [{"course_preapproval_id": cpas[0]["id"], "grade_points": 3.2}]},
            FACULTY_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CREDIT_POSTING)

    def test_grade_out_of_range_rejected(self, api):
        """PRD §3.8: "Every `grade_points` must lie between 0.0 and 4.0 inclusive
        (`ERR_GRADE_OUT_OF_RANGE`) ..."

        Design: Corner/validations/grade_out_of_range_rejected
        """
        program, student, application, cpas = setup_returned_home_with_approved_courses(
            courses=[("HIST310", 3)],
        )
        resp = api.create_credit_posting(
            application["id"],
            {"lines": [{"course_preapproval_id": cpas[0]["id"], "grade_points": 4.5}]},
            FACULTY_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_GRADE_OUT_OF_RANGE)
