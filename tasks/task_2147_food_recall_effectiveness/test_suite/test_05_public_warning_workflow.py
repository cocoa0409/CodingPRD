"""The press release and public warning decision."""
from test_helpers import (
    ApiErrorId,
    assert_public_warning,
    classified_case,
    make_coordinator_headers,
    validate_error,
    validate_paginated,
)

COORDINATOR_1 = make_coordinator_headers("coord-1")
COORDINATOR_2 = make_coordinator_headers("coord-2")

CLASS_THREE_EVALUATION = {
    "probability_of_adverse_health": "LOW",
    "severity_tier": 1,
    "exposure_population": 0,
    "vulnerable_population": False,
    "evidence_strength": "CONFIRMED",
}


def test_review_reject_cycles_the_draft_back_and_a_later_review_approves(api):
    """PRD §3.6: "A `decision` of `APPROVE` advances `IN_REVIEW → APPROVED`; a `decision` of `REJECT` sends the draft back along `IN_REVIEW → DRAFT` and increments `reject_count` by one."
    PRD §3.6: "Both branches stamp `reviewed_by_user_id` with the reviewing coordinator, and both are refused with `ERR_INVALID_WARNING_STATE` when the warning is not currently `IN_REVIEW`."

    Design: Corner/state_machines/public_warning_review_reject_cycles_back_to_draft_then_approves
    """
    case = classified_case()
    warning = case.draft_warning(
        warning_type="PUBLIC_WARNING", drafter_id="coord-1",
        headline="Do not eat lot L-88A",
        body="Listeria monocytogenes contamination confirmed.",
    )
    case.submit_warning(warning["id"], coordinator_id="coord-1")

    rejected = case.review_warning(
        warning["id"], "REJECT", reviewer_id="coord-2", review_note="Add the UPC list."
    )
    assert rejected["status"] == "DRAFT"
    assert rejected["reject_count"] == 1

    resubmitted = case.submit_warning(warning["id"], coordinator_id="coord-1")
    assert resubmitted["status"] == "IN_REVIEW"

    approved = case.review_warning(warning["id"], "APPROVE", reviewer_id="coord-2")
    assert_public_warning(approved)
    assert approved["status"] == "APPROVED"
    assert approved["reject_count"] == 1
    assert approved["reviewed_by_user_id"] == "coord-2"
    assert approved["drafted_by_user_id"] == "coord-1"
    assert approved["published_at"] is None


def test_a_coordinator_may_not_review_their_own_draft(api):
    """PRD §3.6: "Review takes a `decision` and an optional `review_note`, and the reviewer's `X-User-ID` must differ from the draft's `drafted_by_user_id`; a coordinator reviewing their own draft is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.6: "Drafting takes a `warning_type` of `PRESS_RELEASE`, `PUBLIC_WARNING` or `SOCIAL_MEDIA_ONLY`, a `headline` and a `body`; the draft is created in `status` `DRAFT` with `drafted_by_user_id` stamped from the acting `X-User-ID`, `reviewed_by_user_id` null, `reject_count` 0, `review_note` null and `published_at` null."

    Design: Corner/rbac/warning_reviewer_must_not_be_the_drafter_segregation_of_duties
    """
    case = classified_case()
    warning = case.draft_warning(
        warning_type="PRESS_RELEASE", drafter_id="coord-1",
        headline="Do not eat lot L-88A",
        body="Listeria contamination confirmed.",
    )
    case.submit_warning(warning["id"], coordinator_id="coord-1")

    self_review = api.review_public_warning(
        warning["id"], {"decision": "APPROVE"}, COORDINATOR_1
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert self_review.status_code == 403

    approved = case.review_warning(warning["id"], "APPROVE", reviewer_id="coord-2")
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == "coord-2"
    assert approved["reject_count"] == 0


def test_a_press_release_is_not_warranted_on_a_class_three_recall(api):
    """PRD §3.6: "One substantive gate applies at this last step: a `PRESS_RELEASE` or a `PUBLIC_WARNING` may only be published when the recall's `hazard_class` is `CLASS_I` or `CLASS_II`, because a class-three hazard does not warrant broad public alarm; attempting it on a `CLASS_III` recall is refused with `ERR_PUBLIC_WARNING_NOT_WARRANTED`."
    PRD §3.6: "Publication advances `APPROVED → PUBLISHED` and stamps `published_at` from the logical clock; `PUBLISHED` is terminal."

    Design: Corner/errors/publishing_a_press_release_on_a_class_three_recall_is_not_warranted
    """
    case = classified_case(
        hazard_class="CLASS_III", evaluation_overrides=CLASS_THREE_EVALUATION
    )
    warning = case.approved_warning(
        warning_type="PRESS_RELEASE", headline="Undeclared sesame",
        body="Lot L-88A mislabelled.",
    )

    response = api.publish_public_warning(warning["id"], COORDINATOR_2)
    validate_error(response, ApiErrorId.ERR_PUBLIC_WARNING_NOT_WARRANTED.value)
    assert response.status_code == 422

    rows, _ = validate_paginated(
        api.list_public_warnings(case.recall_id, COORDINATOR_1)
    )
    assert rows[0]["status"] == "APPROVED"
    assert rows[0]["published_at"] is None
    assert case.read_recall()["hazard_class"] == "CLASS_III"


class TestPublishGateOrdering:
    """A DRAFT press release on a CLASS_III recall violates the warning-state
    rung and the public-warning rung at once; the earlier rung wins."""

    @staticmethod
    def _class_three_case_with_a_drafted_press_release():
        case = classified_case(
            hazard_class="CLASS_III", evaluation_overrides=CLASS_THREE_EVALUATION
        )
        case.warning = case.draft_warning(
            warning_type="PRESS_RELEASE", drafter_id="coord-1",
            headline="Voluntary recall of frozen spinach",
            body="Consumers should not eat lot L-88A.",
        )
        return case

    def test_publishing_a_draft_reports_the_warning_state_error(self, api):
        """PRD §3.6: "Publishing anything that is not `APPROVED` is `ERR_INVALID_WARNING_STATE`."
        PRD §2.6: "Checks are evaluated strictly in the ascending order listed below; the first violated rung wins and short-circuits every later rung."
        PRD §2.6: "The public warning's `status` permits submit, review or publish — otherwise `ERR_INVALID_WARNING_STATE` (409). Applies to `POST /public-warnings/{id}/submit`, `/review` and `/publish`."

        Design: Difficulty/priority_pair_validation_conflict/publish_unsubmitted_warning_on_class3_recall_returns_state_error_not_safety_error
        """
        case = self._class_three_case_with_a_drafted_press_release()

        response = api.publish_public_warning(case.warning["id"], COORDINATOR_2)
        error = validate_error(response, ApiErrorId.ERR_INVALID_WARNING_STATE.value)
        assert response.status_code == 409
        assert error["error_id"] != ApiErrorId.ERR_PUBLIC_WARNING_NOT_WARRANTED.value

    def test_the_refused_publication_leaves_the_draft_unpublished(self, api):
        """PRD §2.6: "A press release or public warning may only be published when the recall's hazard class is one of the two most serious; a social-media-only notice is exempt — otherwise `ERR_PUBLIC_WARNING_NOT_WARRANTED` (422). Applies to `POST /public-warnings/{id}/publish`."
        PRD §3.6: "Publication advances `APPROVED → PUBLISHED` and stamps `published_at` from the logical clock; `PUBLISHED` is terminal."

        Design: Difficulty/priority_pair_validation_conflict/publish_unsubmitted_warning_on_class3_recall_returns_state_error_not_safety_error
        """
        case = self._class_three_case_with_a_drafted_press_release()
        response = api.publish_public_warning(case.warning["id"], COORDINATOR_2)
        validate_error(response, ApiErrorId.ERR_INVALID_WARNING_STATE.value)

        rows, _ = validate_paginated(
            api.list_public_warnings(case.recall_id, COORDINATOR_1)
        )
        assert rows[0]["status"] == "DRAFT"
        assert rows[0]["published_at"] is None
