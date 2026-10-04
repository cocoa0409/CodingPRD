"""Complaint moderation: state dependencies, conserved aggregates, terminal states."""
from test_helpers import (
    MODERATOR,
    OPS,
    ApiErrorId,
    create_complaint_payload,
    create_page,
    create_review,
    create_user,
    get_page,
    get_review,
    get_user,
    make_business_owner_headers,
    setup_claimed_page,
    setup_complaint,
    set_clock,
    validate_error,
    validate_success,
)


class TestResolveDependsOnReviewState:
    def test_uphold_filter_succeeds_while_review_still_filtered(self, api):
        """PRD §3.7: "For a complaint of kind `FILTERED_DISPUTE`, this action
        additionally requires the subject review to still be in `FILTERED` at
        resolve time".

        Design: Difficulty/cross_entity_state_dependency/complaint_resolve_depends_on_review_state
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, author, review, complaint = setup_complaint(
            kind="FILTERED_DISPUTE", author_trust=50
        )
        assert get_review(review["id"])["recommendation_state"] == "FILTERED"
        resolved = validate_success(
            api.resolve_complaint(complaint["id"], {"action": "UPHOLD_FILTER"}, MODERATOR)
        )
        assert resolved["status"] == "RESOLVED_UPHELD"

    def test_uphold_filter_fails_after_review_promoted(self, api):
        """PRD §3.7: "if the review has since moved (for example because a
        re-evaluation promoted it), the resolution is rejected with
        `ERR_REVIEW_STATE_CHANGED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/complaint_resolve_depends_on_review_state
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, author, review, complaint = setup_complaint(
            kind="FILTERED_DISPUTE", author_trust=50
        )
        # Raise the author's trust so re-evaluation promotes the review.
        validate_success(api.adjust_trust(author["id"], {"trust_score": 100}, OPS))
        promoted = validate_success(api.evaluate_review(review["id"], OPS))
        assert promoted["recommendation_state"] == "DISPLAYED"
        r = api.resolve_complaint(complaint["id"], {"action": "UPHOLD_FILTER"}, MODERATOR)
        validate_error(r, ApiErrorId.ERR_REVIEW_STATE_CHANGED.value)
        complaint_after = validate_success(api.get_complaint(complaint["id"], MODERATOR))
        assert complaint_after["status"] == "UNDER_REVIEW"


class TestDisplayedCountConservation:
    def test_restore_then_remove_returns_aggregates_to_baseline(self, api):
        """PRD §3.7: "Resolution with `action` = `RESTORE_REVIEW` requires the
        review to be in `FILTERED` and its `evidence_confirmed` to be false; on
        success the review's `recommendation_state` moves to `DISPLAYED`, the
        page's `displayed_review_count` is incremented, the displayed average
        is recomputed, and the complaint ends in `RESOLVED_ACTIONED`."
        PRD §3.7: "on success the review transitions to `REMOVED`, the page's
        displayed aggregates are recomputed (decrementing
        `displayed_review_count` if the review had been `DISPLAYED`)".

        Design: Difficulty/compensating_invariant/displayed_count_conserved_across_restore_remove
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        author = create_user(trust_score=100)
        review = create_review(page["id"], author["id"], rating=4)
        assert review["recommendation_state"] == "DISPLAYED"
        assert get_page(page["id"])["displayed_review_count"] == 1
        # Drop trust so re-evaluation filters the review (baseline: 0, avg 0).
        validate_success(api.adjust_trust(author["id"], {"trust_score": 50}, OPS))
        filtered = validate_success(api.evaluate_review(review["id"], OPS))
        assert filtered["recommendation_state"] == "FILTERED"
        baseline = get_page(page["id"])
        assert baseline["displayed_review_count"] == 0
        assert baseline["displayed_rating_avg_x100"] == 0
        # Forward: RESTORE_REVIEW.
        complaint = validate_success(
            api.create_complaint(
                page["id"],
                create_complaint_payload(review_id=review["id"], kind="FILTERED_DISPUTE"),
                make_business_owner_headers(owner["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.start_review_complaint(complaint["id"], MODERATOR))
        validate_success(
            api.resolve_complaint(complaint["id"], {"action": "RESTORE_REVIEW"}, MODERATOR)
        )
        mid = get_page(page["id"])
        assert mid["displayed_review_count"] == 1
        assert mid["displayed_rating_avg_x100"] == 400
        # Compensating: REMOVE_REVIEW.
        complaint2 = validate_success(
            api.create_complaint(
                page["id"],
                create_complaint_payload(review_id=review["id"], kind="NEGATIVE_DISPUTE"),
                make_business_owner_headers(owner["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.start_review_complaint(complaint2["id"], MODERATOR))
        validate_success(
            api.resolve_complaint(complaint2["id"], {"action": "REMOVE_REVIEW"}, MODERATOR)
        )
        end = get_page(page["id"])
        assert end["displayed_review_count"] == baseline["displayed_review_count"]
        assert end["displayed_rating_avg_x100"] == baseline["displayed_rating_avg_x100"]

    def test_remove_review_applies_removal_trust_penalty(self, api):
        """PRD §3.7: "the author's `trust_score` is reduced by 5 (clamped to
        the 0..100 floor) with no change to `strike_count`".

        Design: Difficulty/compensating_invariant/displayed_count_conserved_across_restore_remove
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        author = create_user(trust_score=100)
        review = create_review(page["id"], author["id"], rating=4)
        validate_success(api.adjust_trust(author["id"], {"trust_score": 50}, OPS))
        validate_success(api.evaluate_review(review["id"], OPS))
        complaint = validate_success(
            api.create_complaint(
                page["id"],
                create_complaint_payload(review_id=review["id"], kind="FILTERED_DISPUTE"),
                make_business_owner_headers(owner["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.start_review_complaint(complaint["id"], MODERATOR))
        validate_success(
            api.resolve_complaint(complaint["id"], {"action": "RESTORE_REVIEW"}, MODERATOR)
        )
        complaint2 = validate_success(
            api.create_complaint(
                page["id"],
                create_complaint_payload(review_id=review["id"], kind="NEGATIVE_DISPUTE"),
                make_business_owner_headers(owner["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.start_review_complaint(complaint2["id"], MODERATOR))
        validate_success(
            api.resolve_complaint(complaint2["id"], {"action": "REMOVE_REVIEW"}, MODERATOR)
        )
        assert get_review(review["id"])["recommendation_state"] == "REMOVED"
        author_after = get_user(author["id"])
        assert author_after["trust_score"] == 45
        assert author_after["strike_count"] == 0


class TestEscalation:
    def test_escalate_sets_flag_and_state(self, api):
        """PRD §3.7: "From `UNDER_REVIEW` the moderator may escalate, moving
        the complaint to `ESCALATED` and setting `escalated` to true."

        Design: Corner/state_machines/complaint_escalate_sets_flag_and_state
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, author, review, complaint = setup_complaint(
            kind="FILTERED_DISPUTE", author_trust=50
        )
        escalated = validate_success(api.escalate_complaint(complaint["id"], MODERATOR))
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalated"] is True

    def test_escalated_complaint_remains_decidable(self, api):
        """PRD §3.7: "Both `UNDER_REVIEW` and `ESCALATED` are decidable states:
        the moderator may reject the complaint outright (transitioning it to
        terminal `REJECTED`) or resolve it with one of three actions supplied
        in the `action` field."

        Design: Corner/state_machines/complaint_escalate_sets_flag_and_state
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, author, review, complaint = setup_complaint(
            kind="FILTERED_DISPUTE", author_trust=50
        )
        validate_success(api.escalate_complaint(complaint["id"], MODERATOR))
        resolved = validate_success(
            api.resolve_complaint(complaint["id"], {"action": "UPHOLD_FILTER"}, MODERATOR)
        )
        assert resolved["status"] == "RESOLVED_UPHELD"
        assert resolved["escalated"] is True


class TestTerminalLockdown:
    def test_terminal_complaint_accepts_no_further_action(self, api):
        """PRD §3.7: "A complaint in any terminal state (`RESOLVED_UPHELD`,
        `RESOLVED_ACTIONED`, `REJECTED`) accepts no further moderation action;
        attempts are rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/complaint_terminal_lockdown
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, author, review, complaint = setup_complaint(
            kind="FILTERED_DISPUTE", author_trust=50
        )
        validate_success(
            api.resolve_complaint(complaint["id"], {"action": "UPHOLD_FILTER"}, MODERATOR)
        )
        r = api.reject_complaint(complaint["id"], MODERATOR)
        validate_error(r, ApiErrorId.ERR_INVALID_STATE.value)

    def test_terminal_complaint_cannot_be_restarted_or_escalated(self, api):
        """PRD §3.7: "A complaint in any terminal state (`RESOLVED_UPHELD`,
        `RESOLVED_ACTIONED`, `REJECTED`) accepts no further moderation action;
        attempts are rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/complaint_terminal_lockdown
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, author, review, complaint = setup_complaint(
            kind="FILTERED_DISPUTE", author_trust=50
        )
        validate_success(
            api.resolve_complaint(complaint["id"], {"action": "UPHOLD_FILTER"}, MODERATOR)
        )
        validate_error(
            api.start_review_complaint(complaint["id"], MODERATOR),
            ApiErrorId.ERR_INVALID_STATE.value,
        )
        validate_error(
            api.escalate_complaint(complaint["id"], MODERATOR),
            ApiErrorId.ERR_INVALID_STATE.value,
        )
        validate_error(
            api.resolve_complaint(complaint["id"], {"action": "REMOVE_REVIEW"}, MODERATOR),
            ApiErrorId.ERR_INVALID_STATE.value,
        )
        complaint_after = validate_success(api.get_complaint(complaint["id"], MODERATOR))
        assert complaint_after["status"] == "RESOLVED_UPHELD"


class TestImmediateConsistency:
    def test_restore_recompute_visible_in_same_read(self, api):
        """PRD §3.7: "on success the review's `recommendation_state` moves to
        `DISPLAYED`, the page's `displayed_review_count` is incremented, the
        displayed average is recomputed, and the complaint ends in
        `RESOLVED_ACTIONED`."
        PRD §2.6: "every cascaded mutation is applied atomically alongside the
        primary change".

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_read
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        author = create_user(trust_score=50)
        review = create_review(page["id"], author["id"], rating=5)
        assert review["recommendation_state"] == "FILTERED"
        complaint = validate_success(
            api.create_complaint(
                page["id"],
                create_complaint_payload(review_id=review["id"], kind="FILTERED_DISPUTE"),
                make_business_owner_headers(owner["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.start_review_complaint(complaint["id"], MODERATOR))
        resolved = validate_success(
            api.resolve_complaint(complaint["id"], {"action": "RESTORE_REVIEW"}, MODERATOR)
        )
        assert resolved["status"] == "RESOLVED_ACTIONED"
        page_after = get_page(page["id"])
        assert page_after["displayed_review_count"] == 1
        assert page_after["displayed_rating_avg_x100"] == 500
        assert get_review(review["id"])["recommendation_state"] == "DISPLAYED"


class TestEvaluateRemovedReview:
    def test_evaluate_on_removed_review_is_invalid_state(self, api):
        """PRD §3.3: "A review in `REMOVED` is terminal and never re-enters
        scoring."
        PRD §5: `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/evaluate_removed_review_invalid_state
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, author, review, complaint = setup_complaint(
            kind="NEGATIVE_DISPUTE", author_trust=50, rating=1
        )
        validate_success(
            api.resolve_complaint(complaint["id"], {"action": "REMOVE_REVIEW"}, MODERATOR)
        )
        assert get_review(review["id"])["recommendation_state"] == "REMOVED"
        r = api.evaluate_review(review["id"], OPS)
        validate_error(r, ApiErrorId.ERR_INVALID_STATE.value)
        assert get_review(review["id"])["recommendation_state"] == "REMOVED"
