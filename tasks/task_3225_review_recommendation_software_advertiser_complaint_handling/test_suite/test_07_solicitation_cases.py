"""Solicitation cases: confirm cascade, trust variants, strikes, alerts."""
from test_helpers import (
    INVESTIGATOR,
    MODERATOR,
    OPS,
    ApiErrorId,
    create_complaint_payload,
    create_page,
    create_review,
    create_solicitation_case_payload,
    create_user,
    get_page,
    get_review,
    get_user,
    make_business_owner_headers,
    make_reporter_headers,
    make_reviewer_headers,
    make_trust_investigator_headers,
    setup_claimed_page,
    set_clock,
    validate_error,
    validate_success,
)


def _confirm_case(api, page_id, review_ids, reporter_id):
    case = validate_success(
        api.create_solicitation_case(
            page_id,
            create_solicitation_case_payload(target_review_ids=review_ids),
            make_reporter_headers(reporter_id),
        ),
        expected_status=201,
    )
    validate_success(api.investigate_case(case["id"], INVESTIGATOR))
    return validate_success(api.confirm_case(case["id"], INVESTIGATOR))


class TestConfirmCascadeHopOne:
    def test_confirm_removes_targets_and_marks_evidence(self, api):
        """PRD §3.8: "In the first hop, every target review is marked
        `evidence_confirmed` = true and moved to `REMOVED`: a `DISPLAYED`
        review decrements its page's `displayed_review_count` and recomputes
        the average".

        Design: Difficulty/transitive_cascade/solicitation_confirm_three_hop_cascade
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page()
        author = create_user(trust_score=100)
        reporter = create_user()
        review = create_review(page["id"], author["id"], rating=5)
        assert review["recommendation_state"] == "DISPLAYED"
        assert get_page(page["id"])["displayed_review_count"] == 1
        case = _confirm_case(api, page["id"], [review["id"]], reporter["id"])
        assert case["status"] == "CONFIRMED"
        assert case["confirmed_review_count"] == 1
        review_after = get_review(review["id"])
        assert review_after["recommendation_state"] == "REMOVED"
        assert review_after["evidence_confirmed"] is True
        page_after = get_page(page["id"])
        assert page_after["displayed_review_count"] == 0
        assert page_after["displayed_rating_avg_x100"] == 0

    def test_confirm_places_solicitation_evidence_alert_with_cooldown(self, api):
        """PRD §3.8: "In the third hop, unless an `ACTIVE` consumer alert of
        kind `SOLICITATION_EVIDENCE` already exists on the case's page, the
        system auto-places one whose `case_id` references this case, whose
        `status` is `ACTIVE`, and whose `review_cooldown_until` is the current
        logical time plus 30 days."

        Design: Difficulty/transitive_cascade/solicitation_confirm_three_hop_cascade
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page()
        author = create_user()
        reporter = create_user()
        review = create_review(page["id"], author["id"], rating=2)
        case = _confirm_case(api, page["id"], [review["id"]], reporter["id"])
        alerts = validate_success(api.list_page_consumer_alerts(page["id"], OPS))
        matching = [
            a for a in alerts
            if a["kind"] == "SOLICITATION_EVIDENCE" and a["status"] == "ACTIVE"
        ]
        assert len(matching) == 1
        assert matching[0]["case_id"] == case["id"]


class TestConfirmCascadeHopTwoForceFlag:
    def test_second_strike_force_flags_authors_other_reviews(self, api):
        """PRD §3.8: "any author whose `strike_count` reaches at least 2 then
        has all of their other reviews across all pages force-flagged — each
        such review transitions to `FILTERED` unless it is already `REMOVED`,
        and any that were `DISPLAYED` decrement their pages'
        `displayed_review_count` and trigger a recompute of the displayed
        average."

        Design: Difficulty/transitive_cascade/solicitation_confirm_three_hop_cascade
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user(trust_score=100)
        reporter = create_user()
        page1, page2, page3 = create_page(), create_page(), create_page()
        r1 = create_review(page1["id"], author["id"], rating=5)
        r2 = create_review(page2["id"], author["id"], rating=4)
        r3 = create_review(page3["id"], author["id"], rating=3)
        assert get_page(page3["id"])["displayed_review_count"] == 1
        # First strike: case on page2.
        _confirm_case(api, page2["id"], [r2["id"]], reporter["id"])
        # Second strike: case on page1 -> crosses the escalation threshold.
        _confirm_case(api, page1["id"], [r1["id"]], reporter["id"])
        author_after = get_user(author["id"])
        assert author_after["strike_count"] == 2
        r3_after = get_review(r3["id"])
        assert r3_after["recommendation_state"] == "FILTERED"
        assert get_page(page3["id"])["displayed_review_count"] == 0

    def test_confirm_cooldown_blocks_new_reviews_on_case_page(self, api):
        """PRD §3.9: "While an `ACTIVE` alert's `review_cooldown_until` is
        later than the current logical time, new review submissions on the page
        are rejected with `ERR_PAGE_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/transitive_cascade/solicitation_confirm_three_hop_cascade
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page()
        author = create_user()
        reporter = create_user()
        review = create_review(page["id"], author["id"], rating=2)
        _confirm_case(api, page["id"], [review["id"]], reporter["id"])
        newcomer = create_user()
        r = api.create_review(
            page["id"],
            {"rating": 4, "text": "An honest review attempted during cooldown."},
            make_reviewer_headers(newcomer["id"]),
        )
        validate_error(r, ApiErrorId.ERR_PAGE_NOT_ACTIVE.value)


class TestTrustUpdateVariants:
    def test_strike_path_penalty_and_strike_count(self, api):
        """PRD §3.8: "In the second hop, each distinct author of a confirmed
        review has their `strike_count` incremented by 1 and their
        `trust_score` reduced by 15 (clamped to a 0..100 floor)".

        Design: Difficulty/dual_variant_calc/trust_strike_path_vs_removal_path
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        author = create_user()
        reporter = create_user()
        review = create_review(page["id"], author["id"], rating=2)
        case = _confirm_case(api, page["id"], [review["id"]], reporter["id"])
        author_after = get_user(author["id"])
        assert author_after["trust_score"] == 35
        assert author_after["strike_count"] == 1
        assert get_review(review["id"])["recommendation_state"] == "REMOVED"

    def test_removal_path_penalty_without_strike(self, api):
        """PRD §3.7: "the author's `trust_score` is reduced by 5 (clamped to
        the 0..100 floor) with no change to `strike_count`".

        Design: Difficulty/dual_variant_calc/trust_strike_path_vs_removal_path
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        author = create_user()
        review = create_review(page["id"], author["id"], rating=1)
        complaint = validate_success(
            api.create_complaint(
                page["id"],
                create_complaint_payload(review_id=review["id"], kind="NEGATIVE_DISPUTE"),
                make_business_owner_headers(owner["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.start_review_complaint(complaint["id"], MODERATOR))
        resolved = validate_success(
            api.resolve_complaint(complaint["id"], {"action": "REMOVE_REVIEW"}, MODERATOR)
        )
        assert resolved["status"] == "RESOLVED_ACTIONED"
        author_after = get_user(author["id"])
        assert author_after["trust_score"] == 45
        assert author_after["strike_count"] == 0
        assert get_review(review["id"])["recommendation_state"] == "REMOVED"

    def test_case_driven_removal_does_not_resolve_open_complaint(self, api):
        """PRD §3.8: "In the first hop, every target review is marked
        `evidence_confirmed` = true and moved to `REMOVED`".
        PRD §3.7: "The new complaint's `status` is `OPEN`" and complaints
        transition only via the moderation actions listed in §3.7.

        Design: Difficulty/dual_variant_calc/trust_strike_path_vs_removal_path
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        author = create_user()
        reporter = create_user()
        review = create_review(page["id"], author["id"], rating=2)
        complaint = validate_success(
            api.create_complaint(
                page["id"],
                create_complaint_payload(review_id=review["id"], kind="NEGATIVE_DISPUTE"),
                make_business_owner_headers(owner["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.start_review_complaint(complaint["id"], MODERATOR))
        _confirm_case(api, page["id"], [review["id"]], reporter["id"])
        complaint_after = validate_success(api.get_complaint(complaint["id"], MODERATOR))
        assert complaint_after["status"] == "UNDER_REVIEW"


class TestAlertCooldownOverlap:
    def test_submission_inside_cooldown_rejected(self, api):
        """PRD §3.9: "On placement the alert's `status` is `ACTIVE`,
        `lifted_by_admin_id` is null, and `review_cooldown_until` is set to the
        current logical time plus 30 days. While an `ACTIVE` alert's
        `review_cooldown_until` is later than the current logical time, new
        review submissions on the page are rejected with `ERR_PAGE_NOT_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/consumer_alert_cooldown_overlap
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page()
        author = create_user()
        reporter = create_user()
        review = create_review(page["id"], author["id"], rating=1)
        _confirm_case(api, page["id"], [review["id"]], reporter["id"])
        newcomer = create_user()
        r = api.create_review(
            page["id"],
            {"rating": 4, "text": "New reviewer blocked inside the cooldown."},
            make_reviewer_headers(newcomer["id"]),
        )
        validate_error(r, ApiErrorId.ERR_PAGE_NOT_ACTIVE.value)

    def test_submission_at_cooldown_boundary_admitted_and_alert_stays(self, api):
        """PRD §3.9: "While an `ACTIVE` alert's `review_cooldown_until` is
        later than the current logical time, new review submissions on the page
        are rejected with `ERR_PAGE_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/consumer_alert_cooldown_overlap
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page()
        author = create_user()
        reporter = create_user()
        review = create_review(page["id"], author["id"], rating=1)
        _confirm_case(api, page["id"], [review["id"]], reporter["id"])
        # Exactly at the 30-day boundary the cooldown no longer applies.
        set_clock("2026-10-01T00:00:00Z")
        newcomer = create_user()
        admitted = validate_success(
            api.create_review(
                page["id"],
                {"rating": 4, "text": "New reviewer admitted at the boundary."},
                make_reviewer_headers(newcomer["id"]),
            ),
            expected_status=201,
        )
        assert admitted["recommendation_state"] in ["PENDING", "DISPLAYED", "FILTERED"]
        alerts = validate_success(api.list_page_consumer_alerts(page["id"], OPS))
        assert any(
            a["kind"] == "SOLICITATION_EVIDENCE" and a["status"] == "ACTIVE"
            for a in alerts
        )


class TestCaseTargetValidation:
    def test_cross_page_targets_rejected(self, api):
        """PRD §3.8: "Violations of the target shape (empty list, more than 10
        entries, duplicates, reviews on a different page, already-removed
        reviews) are rejected with `ERR_CASE_TARGETS_INVALID` (HTTP 422)."

        Design: Corner/validations/case_targets_cross_page_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user()
        reporter = create_user()
        page1, page2 = create_page(), create_page()
        r1 = create_review(page1["id"], author["id"], rating=4)
        r2 = create_review(page2["id"], author["id"], rating=4)
        r = api.create_solicitation_case(
            page1["id"],
            create_solicitation_case_payload(target_review_ids=[r1["id"], r2["id"]]),
            make_reporter_headers(reporter["id"]),
        )
        validate_error(r, ApiErrorId.ERR_CASE_TARGETS_INVALID.value)
