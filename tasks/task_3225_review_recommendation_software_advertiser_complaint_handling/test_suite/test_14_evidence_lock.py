"""Evidence-confirmed reviews are permanently locked out of DISPLAYED."""
from test_helpers import (
    INVESTIGATOR,
    MODERATOR,
    ApiErrorId,
    create_complaint_payload,
    create_solicitation_case_payload,
    make_business_owner_headers,
    make_reporter_headers,
    setup_claimed_page,
    create_review,
    create_user,
    get_review,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestEvidenceConfirmedLockout:
    def _setup_evidence_confirmed(self, api):
        page, owner = setup_claimed_page()
        author = create_user()
        reporter = create_user()
        review = create_review(page["id"], author["id"], rating=1)
        case = validate_success(
            api.create_solicitation_case(
                page["id"],
                create_solicitation_case_payload(target_review_ids=[review["id"]]),
                make_reporter_headers(reporter["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.investigate_case(case["id"], INVESTIGATOR))
        validate_success(api.confirm_case(case["id"], INVESTIGATOR))
        return page, owner, review

    def test_evidence_confirmed_review_never_returns_to_displayed(self, api):
        """PRD §3.3: "Any transition that would place an evidence-confirmed
        review into `DISPLAYED` — whether via re-evaluation or via complaint
        resolution — is rejected with `ERR_REVIEW_EVIDENCE_LOCKED` (HTTP 409).
        A review in `REMOVED` is terminal and never re-enters scoring."

        Design: Corner/cross_cutting_layers/evidence_confirmed_locks_displayed_forever
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, review = self._setup_evidence_confirmed(api)
        review_after = get_review(review["id"])
        assert review_after["recommendation_state"] == "REMOVED"
        assert review_after["evidence_confirmed"] is True

    def test_late_restore_attempt_on_confirmed_review_rejected(self, api):
        """PRD §3.3: "Any transition that would place an evidence-confirmed
        review into `DISPLAYED` — whether via re-evaluation or via complaint
        resolution — is rejected with `ERR_REVIEW_EVIDENCE_LOCKED` (HTTP 409)."

        Design: Corner/cross_cutting_layers/evidence_confirmed_locks_displayed_forever
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        author = create_user()
        reporter = create_user()
        review = create_review(page["id"], author["id"], rating=1)
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
        case = validate_success(
            api.create_solicitation_case(
                page["id"],
                create_solicitation_case_payload(target_review_ids=[review["id"]]),
                make_reporter_headers(reporter["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.investigate_case(case["id"], INVESTIGATOR))
        validate_success(api.confirm_case(case["id"], INVESTIGATOR))
        assert get_review(review["id"])["evidence_confirmed"] is True
        r = api.resolve_complaint(complaint["id"], {"action": "RESTORE_REVIEW"}, MODERATOR)
        validate_error(r, ApiErrorId.ERR_REVIEW_EVIDENCE_LOCKED.value)
