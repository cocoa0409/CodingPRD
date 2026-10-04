"""The revision cycle and the milestone's two independent state dimensions."""
from test_helpers import ApiErrorId, err, validate_error, validate_success

from test_helpers.fixtures import (
    COMPLETER,
    REVIEWER,
    VERIFIER,
    applicant_headers,
    complete_milestone,
    create_application,
    create_applicant,
    create_region,
    milestones_by_type,
    record_practice_hours,
    review,
    set_clock,
    setup_member_scenario,
    start_milestone,
    verify_milestone,
)


def _pipeline():
    region = create_region()
    applicant = create_applicant()
    application = create_application(applicant["id"], region["id"])
    return region, applicant, application


class TestRevisionCycle:
    """UNDER_REVIEW -> RETURNED_FOR_REVISION -> UNDER_REVIEW is re-enterable."""

    def test_cycle_closes_twice_and_lands_back_under_review(self, api):
        """PRD §3.2: "The return moves the application from `UNDER_REVIEW` to `RETURNED_FOR_REVISION`, increments `revision_count`, stamps `returned_at` with the current logical clock"
        PRD §3.2: "The applicant — and only the applicant, identified by their own `X-User-ID` matching the application's `applicant_id` — may resubmit, which moves the application back from `RETURNED_FOR_REVISION` to `UNDER_REVIEW` and clears `returned_at` to null."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_reentry
        """
        _, applicant, application = _pipeline()
        app_id = application["id"]
        applicant_hdrs = applicant_headers(applicant["id"])

        review(app_id, 4.0, REVIEWER)
        validate_success(api.return_application(app_id, REVIEWER, "missing leadership essay"))
        validate_success(api.resubmit_application(app_id, applicant_hdrs))
        validate_success(api.return_application(app_id, REVIEWER, "essay still incomplete"))
        data = validate_success(api.resubmit_application(app_id, applicant_hdrs))

        assert data["revision_count"] == 2
        assert data["status"] == "UNDER_REVIEW", (
            "a linear pipeline could not return to the review state a second time"
        )
        assert data.get("returned_at") is None, "the second resubmission clears returned_at"

    def test_fourth_return_is_refused(self, api):
        """PRD §3.2: "Revision is a bounded loop: a return is only permitted while `revision_count` is below 3, so the fourth return attempt is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_reentry
        """
        _, applicant, application = _pipeline()
        app_id = application["id"]
        applicant_hdrs = applicant_headers(applicant["id"])

        review(app_id, 4.0, REVIEWER)
        for _ in range(3):
            validate_success(api.return_application(app_id, REVIEWER, "needs work"))
            validate_success(api.resubmit_application(app_id, applicant_hdrs))

        response = api.return_application(app_id, REVIEWER, "one return too many")
        validate_error(response, err(ApiErrorId.ERR_INVALID_STATE), 409)

        after = validate_success(api.get_application(app_id, REVIEWER))
        assert after["revision_count"] == 3
        assert after["status"] == "UNDER_REVIEW"

    def test_resubmission_after_the_window_is_refused(self, api):
        """PRD §3.2: "Resubmission is time-boxed: the current logical clock must be at or before `returned_at` plus 30 days."
        PRD §3.2: "A resubmission attempted after that window is refused with `ERR_INVALID_STATE`"

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_reentry
        """
        _, applicant, application = _pipeline()
        app_id = application["id"]
        applicant_hdrs = applicant_headers(applicant["id"])

        review(app_id, 4.0, REVIEWER)
        validate_success(api.return_application(app_id, REVIEWER, "missing essay"))
        set_clock("2026-10-02T00:00:00Z")

        response = api.resubmit_application(app_id, applicant_hdrs)
        validate_error(response, err(ApiErrorId.ERR_INVALID_STATE), 409)

        after = validate_success(api.get_application(app_id, REVIEWER))
        assert after["status"] == "RETURNED_FOR_REVISION"


class TestMilestoneParallelDimensions:
    """progress_status and verification_status move independently."""

    def test_completion_leaves_verification_unverified(self, api):
        """PRD §3.5: "A milestone may therefore sit indefinitely at `COMPLETED` with verification still `UNVERIFIED`; the two dimensions advance on their own schedules, and the shortcuts and preconditions listed above are the only places they touch."

        Design: Difficulty/non_linear_state_machine/milestone_parallel_dimensions_diverge
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)
        milestone_id = milestones_by_type(member_id)["COURSEWORK"]["id"]

        started = start_milestone(milestone_id)
        assert started["progress_status"] == "IN_PROGRESS"
        assert started["verification_status"] == "UNVERIFIED"

        completed = complete_milestone(milestone_id, COMPLETER)
        assert completed["progress_status"] == "COMPLETED", "progress reached its end state"
        assert completed["verification_status"] == "UNVERIFIED", (
            "the verification dimension did not move with completion"
        )

    def test_rejection_leaves_progress_completed(self, api):
        """PRD §3.5: "The second dimension is `verification_status`, running `UNVERIFIED` to `VERIFIED` or to `REJECTED`."

        The combined state (COMPLETED, REJECTED) is reachable, which a single
        linear state axis could not produce.

        Design: Difficulty/non_linear_state_machine/milestone_parallel_dimensions_diverge
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)
        milestone_id = milestones_by_type(member_id)["COURSEWORK"]["id"]

        start_milestone(milestone_id)
        complete_milestone(milestone_id, COMPLETER)
        rejected = verify_milestone(milestone_id, "REJECT", VERIFIER)

        assert rejected["verification_status"] == "REJECTED"
        assert rejected["progress_status"] == "COMPLETED", (
            "the rejection edge does not undo the completion"
        )
