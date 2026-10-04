"""Depth tests for non-linear state-machine cycles (re-submit, restrict cycles)."""
from test_helpers import (
    api_client,
    create_active_developer,
    create_title,
    create_user,
    get_success_data,
    make_developer_headers,
    read_title,
    submit_and_get_review,
    validate_error,
    validate_success,
    TEST_USERS,
)

REVIEWER = TEST_USERS["store_reviewer_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


class TestTitleReviewRejectResubmitCycle:
    def test_reject_resubmit_schedule_cancel_cycle(self):
        """PRD §3.2: "Cancelling a scheduled release returns the title from
        `RELEASE_SCHEDULED` to `APPROVED` and clears `scheduled_release_at`."

        Design: Difficulty/non_linear_state_machine/title_review_reject_resubmit_cycle
        """
        developer = create_active_developer()
        title = create_title(developer)
        dev_headers = make_developer_headers(developer["id"])

        # First submission rejected back to DRAFT.
        review1 = submit_and_get_review(title, developer)
        get_success_data(
            api_client.reject_store_page_review(
                review1["id"], {"review_notes": "capsule art missing"}, REVIEWER
            )
        )
        title = read_title(title["id"], developer)
        assert title["status"] == "DRAFT"
        assert title["review_notes"] == "capsule art missing"

        # Second submission takes the next sequence number and is approved.
        review2 = submit_and_get_review(title, developer)
        assert review2["submission_seq"] == 2
        get_success_data(api_client.approve_store_page_review(review2["id"], REVIEWER))

        # Schedule then cancel — the RELEASE_SCHEDULED -> APPROVED back-edge.
        get_success_data(
            api_client.schedule_release(
                title["id"], {"release_at": "2026-09-20T00:00:00Z"}, dev_headers
            )
        )
        title = get_success_data(api_client.cancel_release(title["id"], dev_headers))
        assert title["status"] == "APPROVED"
        assert title["scheduled_release_at"] is None
        assert title["review_notes"] == "capsule art missing"

    def test_second_submission_after_rejection_allowed_with_new_sequence(self):
        """PRD §3.2: "Rejection likewise requires a `SUBMITTED` review, moves the
        review to `REJECTED`, and sends the title back to `DRAFT`, copying the
        payload's `review_notes` onto the title so the developer can see why it
        failed."

        Design: Difficulty/non_linear_state_machine/title_review_reject_resubmit_cycle
        """
        developer = create_active_developer()
        title = create_title(developer)

        review1 = submit_and_get_review(title, developer)
        assert review1["submission_seq"] == 1
        assert review1["status"] == "SUBMITTED"
        rejected = get_success_data(
            api_client.reject_store_page_review(
                review1["id"], {"review_notes": "icon too small"}, REVIEWER
            )
        )
        assert rejected["status"] == "REJECTED"

        title = read_title(title["id"], developer)
        assert title["status"] == "DRAFT"
        assert title["review_notes"] == "icon too small"

        review2 = submit_and_get_review(title, developer)
        assert review2["submission_seq"] == 2
        assert review2["status"] == "SUBMITTED"


class TestUserAccountRestrictUnrestrictCycle:
    def test_restrict_unrestrict_restrict_reenters_cycle(self):
        """PRD §3.5: "Unrestricting an account clears `refund_restricted`,
        recomputes the score from the trailing window (floored at zero), and
        returns the account to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/user_account_restrict_unrestrict_cycle
        """
        user = create_user()
        assert user["status"] == "ACTIVE"

        restricted = get_success_data(api_client.restrict_user(user["id"], TRUST))
        assert restricted["status"] == "RESTRICTED"
        assert restricted["refund_restricted"] is True

        unrestricted = get_success_data(api_client.unrestrict_user(user["id"], TRUST))
        assert unrestricted["status"] == "ACTIVE"
        assert unrestricted["refund_restricted"] is False

        restricted_again = get_success_data(api_client.restrict_user(user["id"], TRUST))
        assert restricted_again["status"] == "RESTRICTED"
        assert restricted_again["refund_restricted"] is True

    def test_each_cycle_transition_increments_version(self):
        """PRD §2.5: "Every persisted resource carries `id` (a server-minted
        UUID with no type prefix), `created_at` (ISO 8601 UTC with three
        fractional digits), `updated_at` (same format, refreshed on every
        mutation), and `version` (an integer starting at its initial value that
        increments by one on every mutation of that resource)."

        Design: Difficulty/non_linear_state_machine/user_account_restrict_unrestrict_cycle
        """
        user = create_user()
        v0 = user["version"]

        get_success_data(api_client.restrict_user(user["id"], TRUST))
        get_success_data(api_client.unrestrict_user(user["id"], TRUST))
        final = get_success_data(api_client.restrict_user(user["id"], TRUST))

        assert final["version"] == v0 + 3
        assert final["status"] == "RESTRICTED"
        assert final["refund_restricted"] is True
