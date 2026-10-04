"""Validation errors, RBAC denials, and segregation of duties."""
from test_helpers import (
    ADMIN,
    MODERATOR,
    NON_EXISTENT_UUID,
    OPS,
    ApiErrorId,
    create_complaint_payload,
    create_consumer_alert_payload,
    create_page,
    create_page_claim_payload,
    create_review,
    create_solicitation_case_payload,
    create_user,
    get_review,
    make_business_owner_headers,
    make_reporter_headers,
    make_reviewer_headers,
    make_trust_investigator_headers,
    setup_claimed_page,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestReviewSubmissionValidation:
    def test_rating_out_of_range_rejected(self, api):
        """PRD §3.3: "A `Reviewer` submits a review to a specific page by
        providing a `rating` (an integer between 1 and 5, inclusive)".
        PRD §2.7: "structural payload checks (missing fields, wrong types, enum
        violations, minimum-length violations, out-of-range values, and
        reversed date ranges — all surfaced as `ERR_INVALID_REQUEST`)".

        Design: Corner/entities/review_rating_out_of_range_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user()
        page = create_page()
        r = api.create_review(
            page["id"],
            {"rating": 6, "text": "Six stars is out of range and must fail."},
            make_reviewer_headers(author["id"]),
        )
        validate_error(r, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_owner_authored_review_is_solicitation_suspect(self, api):
        """PRD §3.3: "the solicitation prohibition applies: the author must not
        be the page's claimed owner, and the author must not have an `OPEN` or
        `INVESTIGATING` `SolicitationCase` targeting their prior reviews on
        this same page — violations are rejected with
        `ERR_SOLICITATION_SUSPECT` (HTTP 422)."

        Design: Corner/validations/owner_authored_review_solicitation_suspect
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        r = api.create_review(
            page["id"],
            {"rating": 5, "text": "Owner tries to review their own business."},
            make_reviewer_headers(owner["id"]),
        )
        validate_error(r, ApiErrorId.ERR_SOLICITATION_SUSPECT.value)

    def test_suspended_author_rejected(self, api):
        """PRD §3.3: "Next, the author's own `status` must be `ACTIVE`;
        otherwise the submission is rejected with `ERR_USER_NOT_ACTIVE`
        (HTTP 409)."

        Design: Corner/errors/err_user_not_active_on_suspended_author
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user()
        validate_success(api.suspend_user(author["id"], OPS))
        page = create_page()
        r = api.create_review(
            page["id"],
            {"rating": 4, "text": "Suspended user attempts to post a review."},
            make_reviewer_headers(author["id"]),
        )
        validate_error(r, ApiErrorId.ERR_USER_NOT_ACTIVE.value)


class TestEditWindow:
    # NOTE: test_edit_after_72h_window_expired and
    # test_edit_within_72h_succeeds_and_sets_flag were deleted 2026-09-30
    # (unique-derivability collapse). Both require a freshly submitted review
    # to remain `PENDING` so the author can edit it. But PRD §3.3 also says
    # the recommendation software "is immediately evaluated against it in its
    # at-submission variant" and "A score of at least 700 transitions the
    # review toward `DISPLAYED`; anything below 700 transitions it toward
    # `FILTERED`" — under which a submitted review leaves `PENDING` at
    # creation (the reading the rest of the suite — scoring, aggregates,
    # merge cascade, evidence lock — is built on). The counter-sentence
    # "it stays in `PENDING` until the next evaluation pass" supports the
    # opposite reading. Both readings trace to verbatim PRD sentences, so
    # the asserted precondition is not uniquely derivable.
    pass


class TestComplaintIntakeValidation:
    def test_complaint_by_non_owner_rejected(self, api):
        """PRD §3.7: "Filing is rejected with `ERR_COMPLAINT_CONFLICT`
        (HTTP 409) when any of: the caller is not the page's claimed owner;
        the review's `page_id` does not match the page the complaint is filed
        on; the `kind` is `FILTERED_DISPUTE` but the review is not currently in
        `FILTERED`; or another complaint on the same review is already in
        `OPEN`, `UNDER_REVIEW`, or `ESCALATED`."

        Design: Corner/validations/complaint_by_non_owner_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        author = create_user()
        stranger = create_user()
        review = create_review(page["id"], author["id"], rating=2)
        r = api.create_complaint(
            page["id"],
            create_complaint_payload(review_id=review["id"], kind="NEGATIVE_DISPUTE"),
            make_business_owner_headers(stranger["id"]),
        )
        validate_error(r, ApiErrorId.ERR_COMPLAINT_CONFLICT.value)


class TestClaimIntakeValidation:
    def test_second_open_claim_on_same_page_rejected(self, api):
        """PRD §3.4: "in both cases the page must be `ACTIVE` and no other
        claim in `SUBMITTED` or `VERIFIED` may already exist on the page — any
        violation is rejected with `ERR_CLAIM_CONFLICT` (HTTP 409)."

        Design: Corner/validations/duplicate_open_claim_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page()
        claimant1, claimant2 = create_user(), create_user()
        validate_success(
            api.create_page_claim(page["id"], create_page_claim_payload(),
                                  make_business_owner_headers(claimant1["id"])),
            expected_status=201,
        )
        r = api.create_page_claim(page["id"], create_page_claim_payload(),
                                  make_business_owner_headers(claimant2["id"]))
        validate_error(r, ApiErrorId.ERR_CLAIM_CONFLICT.value)


class TestClaimVerificationExpiry:
    def test_verify_after_seven_days_expires_claim(self, api):
        """PRD §3.4: "The claimant must then verify the claim by resubmitting
        the `verification_code` within 7 days of the claim's `created_at`."
        PRD §3.4: "A verification attempted after the seven-day window — or
        with a code that does not match — is rejected with
        `ERR_VERIFICATION_EXPIRED` (HTTP 410). If the window elapses without
        verification, the system marks the claim `EXPIRED` the next time the
        logical clock advances past it."

        Design: Corner/state_machines/pageclaim_expiry_via_clock
        """
        set_clock("2026-09-01T00:00:00Z")
        claimant = create_user()
        page = create_page()
        claim = validate_success(
            api.create_page_claim(page["id"], create_page_claim_payload(),
                                  make_business_owner_headers(claimant["id"])),
            expected_status=201,
        )
        set_clock("2026-09-09T00:00:00Z")
        r = api.verify_page_claim(
            claim["id"], {"verification_code": claim["verification_code"]},
            make_business_owner_headers(claimant["id"]),
        )
        # PRD names ERR_VERIFICATION_EXPIRED for "a verification attempted
        # after the seven-day window", but also mandates the lazy EXPIRED
        # transition on clock advance — under which §2.7's state-before-
        # business ordering yields ERR_INVALID_STATE instead. Both readings
        # are PRD-faithful, so accept either.
        validate_error_is_one_of(
            r,
            [ApiErrorId.ERR_VERIFICATION_EXPIRED.value,
             ApiErrorId.ERR_INVALID_STATE.value],
        )
        claim_after = validate_success(api.get_page_claim(claim["id"], ADMIN))
        assert claim_after["status"] == "EXPIRED"


class TestNotFoundAndRoleOrdering:
    def test_unknown_review_id_returns_not_found(self, api):
        """PRD §2.7: "the server validates path identifiers from left to right,
        rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that
        does not resolve to an existing resource."

        Design: Corner/entities/review_get_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        r = api.get_review(NON_EXISTENT_UUID, OPS)
        validate_error(r, ApiErrorId.ERR_NOT_FOUND.value)

    def test_resolve_nonexistent_complaint_returns_not_found(self, api):
        """PRD §2.7: "the server validates path identifiers from left to right,
        rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that
        does not resolve to an existing resource."

        Design: Corner/validations/not_found_precedes_state_check
        """
        set_clock("2026-09-01T00:00:00Z")
        r = api.resolve_complaint(NON_EXISTENT_UUID, {"action": "UPHOLD_FILTER"}, MODERATOR)
        validate_error(r, ApiErrorId.ERR_NOT_FOUND.value)

    def test_malformed_payload_checked_before_state(self, api):
        """PRD §2.7: "Across the entire surface, validation proceeds in this
        strict order: authentication of the headers first, then role
        authorization, then path and body reference existence, then structural
        payload checks (missing fields, wrong types, enum violations,
        minimum-length violations, out-of-range values, and reversed date
        ranges — all surfaced as `ERR_INVALID_REQUEST`), then state-machine
        admissibility of the operation (`ERR_INVALID_STATE`), and only then
        domain-specific business rules."

        Design: Corner/validations/state_priority_over_malformed_business_combo
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        author = create_user()
        review = create_review(page["id"], author["id"], rating=3)
        complaint = validate_success(
            api.create_complaint(
                page["id"],
                create_complaint_payload(review_id=review["id"], kind="NEGATIVE_DISPUTE"),
                make_business_owner_headers(owner["id"]),
            ),
            expected_status=201,
        )
        # Complaint is OPEN (wrong state) AND the payload omits `action`
        # (malformed); the structural check must win.
        r = api.resolve_complaint(complaint["id"], {}, MODERATOR)
        validate_error(r, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestRoleExclusiveDenials:
    def test_reviewer_cannot_moderate_complaints(self, api):
        """PRD §2.1: "A request whose role is well-formed but not permitted for
        the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: `POST /platform/complaints/{complaintId}/start-review` is
        authorized for ContentModerator only.

        Design: Corner/rbac/reviewer_cannot_moderate_complaints
        """
        set_clock("2026-09-01T00:00:00Z")
        reviewer = create_user()
        r = api.start_review_complaint(
            NON_EXISTENT_UUID, make_reviewer_headers(reviewer["id"])
        )
        validate_error(r, ApiErrorId.ERR_FORBIDDEN.value)

    def test_business_owner_cannot_place_consumer_alerts(self, api):
        """PRD §2.1: "A request whose role is well-formed but not permitted for
        the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: `POST /platform/business-pages/{pageId}/consumer-alerts` is
        authorized for SupportAdmin only.

        Design: Corner/rbac/business_owner_cannot_place_consumer_alerts
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        r = api.create_consumer_alert(
            page["id"],
            create_consumer_alert_payload(kind="SUSPICIOUS_ACTIVITY"),
            make_business_owner_headers(owner["id"]),
        )
        validate_error(r, ApiErrorId.ERR_FORBIDDEN.value)

    def test_legal_ops_cannot_execute_merges(self, api):
        """PRD §2.1: "A request whose role is well-formed but not permitted for
        the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: `POST /platform/merge-requests/{mergeRequestId}/execute` is
        authorized for SupportAdmin only.

        Design: Corner/rbac/legal_ops_cannot_execute_merges
        """
        set_clock("2026-09-01T00:00:00Z")
        legal_headers = {"X-User-ID": "test-legal-ops-1", "X-User-Role": "LegalOps"}
        pd, ps = create_page(name="Legal Dup"), create_page(name="Legal Surv")
        mr = validate_success(
            api.create_merge_request(
                {
                    "duplicate_page_id": pd["id"],
                    "survivor_page_id": ps["id"],
                    "reason": "Duplicate listings on the same street.",
                },
                {"X-User-ID": "test-support-admin-1", "X-User-Role": "SupportAdmin"},
            ),
            expected_status=201,
        )
        r = api.execute_merge_request(
            mr["id"], {"expected_duplicate_page_version": pd["version"]}, legal_headers
        )
        validate_error(r, ApiErrorId.ERR_FORBIDDEN.value)
        mr_after = validate_success(
            api.get_merge_request(
                mr["id"],
                {"X-User-ID": "test-support-admin-1", "X-User-Role": "SupportAdmin"},
            )
        )
        assert mr_after["status"] == "PENDING"


class TestSegregationOfDuties:
    def test_investigator_cannot_confirm_own_reported_case(self, api):
        """PRD §3.8: "Confirmation requires segregation of duties: the
        investigator must not be the case's reporter — a self-confirm is
        rejected with `ERR_SELF_ACTION` (HTTP 403)."

        Design: Corner/rbac/segregation_of_duties_case_confirm
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user()
        reporter = create_user()
        page = create_page()
        review = create_review(page["id"], author["id"], rating=2)
        case = validate_success(
            api.create_solicitation_case(
                page["id"],
                create_solicitation_case_payload(target_review_ids=[review["id"]]),
                make_reporter_headers(reporter["id"]),
            ),
            expected_status=201,
        )
        investigator_headers = make_trust_investigator_headers(reporter["id"])
        validate_success(api.investigate_case(case["id"], investigator_headers))
        r = api.confirm_case(case["id"], investigator_headers)
        validate_error(r, ApiErrorId.ERR_SELF_ACTION.value)
        case_after = validate_success(
            api.get_solicitation_case(case["id"], investigator_headers)
        )
        assert case_after["status"] == "INVESTIGATING"
