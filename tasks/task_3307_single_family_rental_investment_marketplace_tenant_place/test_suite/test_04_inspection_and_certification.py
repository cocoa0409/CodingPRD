"""Inspection reports, certification gating, and verification controls."""
import pytest

from test_helpers import (
    ApiErrorId,
    REVIEWER_HEADERS,
    attach_lease,
    attach_verified_inspection,
    create_inspection_report_payload,
    get_success_data,
    make_reviewer_headers,
    make_seller_headers,
    setup_certified_listing,
    setup_draft_listing,
    setup_program,
    setup_seller,
    validate_error,
    validate_success,
)


class TestCertificationGate:
    def test_certify_blocked_while_lease_disclosure_pending(self, api):
        """PRD §3.2: "Certification (`IN_REVIEW` → `CERTIFIED`) enforces, as
        cross-entity preconditions failing with `ERR_PRECONDITION`: the
        listing's `certification_program_id` is set and that program's `active`
        flag is true; the latest `VERIFIED` report — latest by `inspection_date`,
        with ties broken by `created_at` descending — has an `overall_score` of
        at least the program's `min_inspection_score`; that same report's
        `title_grade` is at least as good as the program's `min_title_grade` in
        the ordering `A` best, then `B`, then `C`; and, when the program's
        `requires_lease_disclosure` is true, at least one lease on the listing
        has `disclosure_status` of `DISCLOSED` with a tenancy `status` of
        `ACTIVE`."

        Design: Corner/validations/certification_requires_disclosed_lease_when_program_demands
        """
        seller = setup_seller()
        program = setup_program(requires_lease_disclosure=True)
        listing = setup_draft_listing(seller, certification_program_id=program["id"])
        attach_verified_inspection(seller, listing)
        attach_lease(seller, listing)  # stays PENDING
        seller_h = make_seller_headers(seller["id"])
        api.transition_listing(listing["id"], {"action": "SUBMIT"}, seller_h)
        api.transition_listing(listing["id"], {"action": "BEGIN_REVIEW"}, REVIEWER_HEADERS)
        resp = api.transition_listing(listing["id"], {"action": "CERTIFY"}, REVIEWER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PRECONDITION)

    def test_certify_succeeds_after_lease_disclosed(self, api):
        """PRD §3.2: "Certification (`IN_REVIEW` → `CERTIFIED`) enforces, as
        cross-entity preconditions failing with `ERR_PRECONDITION`: the
        listing's `certification_program_id` is set and that program's `active`
        flag is true; the latest `VERIFIED` report — latest by `inspection_date`,
        with ties broken by `created_at` descending — has an `overall_score` of
        at least the program's `min_inspection_score`; that same report's
        `title_grade` is at least as good as the program's `min_title_grade` in
        the ordering `A` best, then `B`, then `C`; and, when the program's
        `requires_lease_disclosure` is true, at least one lease on the listing
        has `disclosure_status` of `DISCLOSED` with a tenancy `status` of
        `ACTIVE`."

        Design: Corner/validations/certification_requires_disclosed_lease_when_program_demands
        """
        seller = setup_seller()
        program = setup_program(requires_lease_disclosure=True)
        listing = setup_draft_listing(seller, certification_program_id=program["id"])
        attach_verified_inspection(seller, listing)
        lease = attach_lease(seller, listing)
        seller_h = make_seller_headers(seller["id"])
        api.transition_listing(listing["id"], {"action": "SUBMIT"}, seller_h)
        api.transition_listing(listing["id"], {"action": "BEGIN_REVIEW"}, REVIEWER_HEADERS)
        disclosed = get_success_data(
            api.transition_lease(lease["id"], {"action": "DISCLOSE"}, seller_h)
        )
        assert disclosed["disclosure_status"] == "DISCLOSED"
        resp = api.transition_listing(listing["id"], {"action": "CERTIFY"}, REVIEWER_HEADERS)
        listing = validate_success(resp)
        assert listing["status"] == "CERTIFIED"


class TestInspectionVerification:
    def test_verify_by_submitting_seller_id_rejected(self, api):
        """PRD §3.2: "Verification is segregation-of-duties controlled: the
        reviewer's `X-User-ID` must differ from `submitted_by_seller_id`,
        otherwise `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/seller_cannot_verify_own_inspection
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        seller_h = make_seller_headers(seller["id"])
        resp = api.create_inspection_report(
            listing["id"], create_inspection_report_payload(), seller_h
        )
        report = get_success_data(resp)
        api.transition_inspection_report(report["id"], {"action": "SUBMIT"}, seller_h)
        # Reviewer carrying the same id as the submitting seller.
        resp = api.transition_inspection_report(
            report["id"], {"action": "VERIFY"}, make_reviewer_headers(seller["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        reports = get_success_data(api.list_inspection_reports(listing["id"], seller_h))
        assert reports[0]["status"] == "SUBMITTED"

    def test_verify_by_distinct_reviewer_succeeds(self, api):
        """PRD §3.2: "A `CertificationReviewer` then either verifies the report
        (`SUBMITTED` → `VERIFIED`) or rejects it (`SUBMITTED` → `REJECTED`)."

        Design: Corner/rbac/seller_cannot_verify_own_inspection
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        report = attach_verified_inspection(seller, listing)
        assert report["status"] == "VERIFIED"


class TestInspectionRevisionLoop:
    def test_rejected_report_returns_to_draft_on_revise(self, api):
        """PRD §3.2: "A rejected report is not terminal for the listing — the
        seller may revise it (`REJECTED` → `DRAFT`), and a report may cycle
        through draft, submission, and rejection repeatedly until it verifies."

        Design: Difficulty/non_linear_state_machine/inspection_revision_loop
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        seller_h = make_seller_headers(seller["id"])
        resp = api.create_inspection_report(
            listing["id"],
            create_inspection_report_payload(
                overall_score=40,
                disclosed_defects=[{"code": "ELEC-1", "severity": "HIGH", "description": "panel"}],
            ),
            seller_h,
        )
        report = get_success_data(resp)
        api.transition_inspection_report(report["id"], {"action": "SUBMIT"}, seller_h)
        rejected = get_success_data(
            api.transition_inspection_report(report["id"], {"action": "REJECT"}, REVIEWER_HEADERS)
        )
        assert rejected["status"] == "REJECTED"
        revised = get_success_data(
            api.transition_inspection_report(report["id"], {"action": "REVISE"}, seller_h)
        )
        assert revised["status"] == "DRAFT"

    def test_revised_report_verifies_on_resubmission(self, api):
        """PRD §3.2: "submission stamps the report's `submitted_by_seller_id`
        with the acting seller's `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/inspection_revision_loop
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        seller_h = make_seller_headers(seller["id"])
        resp = api.create_inspection_report(
            listing["id"],
            create_inspection_report_payload(
                overall_score=40,
                disclosed_defects=[{"code": "ELEC-1", "severity": "HIGH", "description": "panel"}],
            ),
            seller_h,
        )
        report = get_success_data(resp)
        api.transition_inspection_report(report["id"], {"action": "SUBMIT"}, seller_h)
        api.transition_inspection_report(report["id"], {"action": "REJECT"}, REVIEWER_HEADERS)
        api.transition_inspection_report(report["id"], {"action": "REVISE"}, seller_h)
        api.transition_inspection_report(report["id"], {"action": "SUBMIT"}, seller_h)
        verified = get_success_data(
            api.transition_inspection_report(report["id"], {"action": "VERIFY"}, REVIEWER_HEADERS)
        )
        assert verified["status"] == "VERIFIED"
        assert verified["submitted_by_seller_id"] == seller["id"]


class TestCertifyRbac:
    def test_buyer_cannot_certify_listing(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint — or whose entity-backed caller does not own the resource where
        ownership is declared — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/buyer_cannot_certify_listing
        """
        from test_helpers import make_buyer_headers, setup_buyer

        seller = setup_seller()
        buyer = setup_buyer()
        program = setup_program()
        listing = setup_draft_listing(seller, certification_program_id=program["id"])
        attach_verified_inspection(seller, listing)
        seller_h = make_seller_headers(seller["id"])
        api.transition_listing(listing["id"], {"action": "SUBMIT"}, seller_h)
        api.transition_listing(listing["id"], {"action": "BEGIN_REVIEW"}, REVIEWER_HEADERS)
        resp = api.transition_listing(
            listing["id"], {"action": "CERTIFY"}, make_buyer_headers(buyer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        listing_now = get_success_data(api.get_listing(listing["id"], seller_h))
        assert listing_now["status"] == "IN_REVIEW"

    def test_reviewer_certifies_in_review_listing(self, api):
        """PRD §3.2: "Once `CERTIFIED`, the seller publishes the listing
        (`CERTIFIED` → `LISTED`), making it visible for offers."

        Design: Corner/rbac/buyer_cannot_certify_listing
        """
        ctx = setup_certified_listing()
        assert ctx["listing"]["status"] == "CERTIFIED"
        seller_h = make_seller_headers(ctx["seller"]["id"])
        published = get_success_data(
            api.transition_listing(ctx["listing"]["id"], {"action": "PUBLISH"}, seller_h)
        )
        assert published["status"] == "LISTED"
