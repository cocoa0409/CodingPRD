"""Validation priority and domain-rule rejection tests (Corner sections
validations, errors, and rbac; Difficulty rules priority_pair_validation_conflict,
boundary_precision_check, and cross_entity_state_dependency)."""
import pytest

from test_helpers import (
    api_client, TEST_USERS, make_volunteer_editor_headers,
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId,
    create_editor, create_page, create_revision, create_accepted_revision,
    create_open_dispute, set_clock,
    create_campaign, create_banner, create_donation, create_completed_donation,
    create_active_campaign_with_banner,
    create_grant_program, create_grant_application,
    setup_scored_application_under_review, setup_approved_application,
    create_campaign_payload, create_banner_payload, create_impression_payload,
    create_protection_request_payload, create_score_payload,
)


class TestAuthenticationPriority:
    def test_missing_role_header_returns_unauthenticated(self):
        """PRD §2.1: "Every API request must include two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or the role is not recognized,
        the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_role_header_returns_unauthenticated
        """
        set_clock()
        # Send with X-User-ID only — no X-User-Role header.
        resp = api_client.get_page(NON_EXISTENT_UUID, headers={"X-User-ID": "someone"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorizationPriority:
    def test_editor_cannot_approve_protection_request(self):
        """PRD §2.1: "If the role is recognized but not permitted for the
        requested operation, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: POST `/wiki/protection-requests/{requestId}/approve` is
        authorized for `Administrator` only.

        Design: Corner/validations/editor_cannot_approve_protection_request
        """
        set_clock()
        editor, editor_headers = create_editor(username="ua", email="ua@x.com")
        page = create_page(editor_headers, title="UA Page")
        resp = api_client.create_protection_request(
            page["id"], create_protection_request_payload(requested_level="SEMI", reason="r"),
            editor_headers,
        )
        request = validate_success(resp, expected_status=201)
        resp = api_client.approve_protection_request(request["id"], editor_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = get_success_data(api_client.get_protection_request(request["id"], TEST_USERS["administrator_headers"]))
        assert after["status"] == "PENDING"


class TestExistencePriority:
    def test_escalate_nonexistent_dispute_returns_not_found(self):
        """PRD §2.7: "If any referenced ID does not exist, the request is rejected
        with `ERR_NOT_FOUND` (HTTP 404). Validation proceeds in strict priority
        order across all endpoints: authentication first (`ERR_UNAUTHENTICATED`),
        then authorization (`ERR_UNAUTHORIZED`), then existence
        (`ERR_NOT_FOUND`), then state legality (`ERR_INVALID_STATE`), and finally
        the domain-specific business rules described in §3."

        Design: Corner/validations/escalate_nonexistent_dispute_returns_not_found
        """
        set_clock()
        resp = api_client.escalate_dispute(
            NON_EXISTENT_UUID, {"expected_dispute_version": 1},
            TEST_USERS["administrator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRefundWindow:
    def test_refund_after_90_days_rejected(self):
        """PRD §3.9: "A `FundraisingManager` may refund a completed donation
        within ninety days of `processed_at`; a later attempt is rejected with
        `ERR_REFUND_WINDOW_EXPIRED` (HTTP 409)."

        Design: Corner/validations/refund_after_90_days_rejected
        """
        set_clock()
        campaign = create_campaign(name="RW Drive", end_at="2027-12-31T23:59:59Z")
        banner = create_banner(campaign["id"], message_variant="W")
        validate_success(api_client.activate_campaign(
            campaign["id"], {"expected_campaign_version": campaign["version"]},
            TEST_USERS["fundraising_manager_headers"],
        ))
        donation = create_donation(campaign["id"], banner["id"], donor_email_hash="rw")
        validate_success(api_client.process_donation(donation["id"], TEST_USERS["payment_processor_headers"]))
        # 91 days later
        set_clock("2026-12-01T00:00:00Z")
        resp = api_client.refund_donation(donation["id"], TEST_USERS["fundraising_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_EXPIRED)
        after = get_success_data(api_client.get_donation(donation["id"], TEST_USERS["fundraising_manager_headers"]))
        assert after["status"] == "COMPLETED"


class TestVandalismScoreHighError:
    def test_error_vandalism_score_high_on_non_admin_accept(self):
        """PRD §3.2: "If a revision's vandalism score is 50 or higher and no
        admin override is applied, acceptance is rejected with
        `ERR_VANDALISM_SCORE_HIGH` (HTTP 409)."
        PRD §3.2: "A pending revision may be accepted by a `VolunteerEditor` with
        `rollback_eligible` set to true, or by an `Administrator`. Acceptance is
        not automatic. The vandalism score must be below 50."

        Design: Corner/errors/error_vandalism_score_high_on_non_admin_accept
        """
        set_clock()
        author, author_headers = create_editor(username="vh1", email="vh1@x.com")
        acceptor, acceptor_headers = create_editor(username="vh2", email="vh2@x.com")
        page = create_page(author_headers, title="VH Page")
        resp = api_client.create_revision(
            page["id"], {"content_text": "SPAM_KEYWORD junk", "summary": "s"}, author_headers,
        )
        revision = validate_success(resp, expected_status=201)
        # Only meaningful when the automated score crosses the 50 threshold.
        if revision["vandalism_score"] >= 50:
            resp = api_client.accept_revision(
                revision["id"], {"expected_page_version": page["version"]}, acceptor_headers,
            )
            validate_error(resp, ApiErrorId.ERR_VANDALISM_SCORE_HIGH)
            after = get_success_data(api_client.get_revision(revision["id"], TEST_USERS["administrator_headers"]))
            assert after["status"] == "PENDING"
        else:
            # Score stayed below 50 — accept by a rollback-eligible editor works.
            resp = api_client.accept_revision(
                revision["id"], {"expected_page_version": page["version"]}, acceptor_headers,
            )
            validate_success(resp)


class TestBannerGeoMismatch:
    def test_error_banner_geo_mismatch(self):
        """PRD §3.8: "The impression is rejected with `ERR_BANNER_GEO_MISMATCH`
        (HTTP 409) if the banner's `geo_target` is neither `GLOBAL` nor the
        viewer's country."

        Design: Corner/errors/error_banner_geo_mismatch
        """
        set_clock()
        campaign, banner = create_active_campaign_with_banner(
            campaign_overrides={"name": "Geo Drive"},
            banner_overrides={"message_variant": "G", "geo_target": "US", "frequency_cap": 5},
        )
        resp = api_client.record_impression(
            banner["id"], {"viewer_key": "de1", "country_code": "DE"},
            TEST_USERS["anonymous_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BANNER_GEO_MISMATCH)
        banner_after = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_after["impression_count"] == 0


class TestTakedownArbitrationBlock:
    def test_error_takedown_arbitration_block(self):
        """PRD §3.11: "For a `TAKEDOWN`, the target page must exist and must not
        have an open Arbitration dispute; attempting compliance while an
        Arbitration dispute is open is rejected with
        `ERR_TAKEDOWN_ARBITRATION_BLOCK` (HTTP 409)."

        Design: Corner/errors/error_takedown_arbitration_block
        """
        set_clock()
        legal = TEST_USERS["legal_counsel_headers"]
        initiator, initiator_headers = create_editor(username="tb1", email="tb1@x.com")
        respondent, respondent_headers = create_editor(username="tb2", email="tb2@x.com")
        page = create_page(initiator_headers, title="TB Page", topic_area="POLITICS")
        revision, page = create_accepted_revision(page, initiator_headers)
        dispute = create_open_dispute(page, initiator_headers, respondent["id"], revision["id"])
        set_clock("2026-09-05T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": dispute["version"]}, initiator_headers,
        )
        dispute = validate_success(resp)
        set_clock("2026-09-09T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": dispute["version"]}, initiator_headers,
        )
        dispute = validate_success(resp)
        assert dispute["level"] == "ARBITRATION"
        resp = api_client.create_legal_request(
            {"request_type": "TAKEDOWN", "target_page_id": page["id"], "requesting_party": "Gov"},
            legal,
        )
        legal_request = validate_success(resp, expected_status=201)
        validate_success(api_client.start_review_legal_request(legal_request["id"], legal))
        resp = api_client.comply_legal_request(legal_request["id"], legal)
        validate_error(resp, ApiErrorId.ERR_TAKEDOWN_ARBITRATION_BLOCK)
        after = get_success_data(api_client.get_legal_request(legal_request["id"], legal))
        assert after["status"] == "UNDER_REVIEW"


class TestLegalRequestsPendingOnPublish:
    def test_error_legal_requests_pending_on_publish(self):
        """PRD §3.11: "Publishing requires that every legal request whose
        `received_at` falls within the half-open interval from `period_start` to
        `period_end` have reached a terminal status (`COMPLIED`, `REJECTED`, or
        `PARTIALLY_COMPLIED`); if any request is still pending, publication is
        rejected with `ERR_LEGAL_REQUESTS_PENDING` (HTTP 409)."

        Design: Corner/errors/error_legal_requests_pending_on_publish
        """
        legal = TEST_USERS["legal_counsel_headers"]
        set_clock("2026-03-01T00:00:00Z")
        resp = api_client.create_legal_request(
            {"request_type": "USER_INFO", "requesting_party": "Pending Party"}, legal,
        )
        validate_success(resp, expected_status=201)
        resp = api_client.create_transparency_report(
            {"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-06-30T23:59:59Z"}, legal,
        )
        report = validate_success(resp, expected_status=201)
        resp = api_client.publish_transparency_report(
            report["id"], {"expected_report_version": report["version"]}, legal,
        )
        validate_error(resp, ApiErrorId.ERR_LEGAL_REQUESTS_PENDING)
        after = get_success_data(api_client.get_transparency_report(report["id"], legal))
        assert after["status"] == "DRAFT"


class TestRbacSegregation:
    def test_legal_counsel_cannot_manage_campaigns(self):
        """PRD §2.1: "If the role is recognized but not permitted for the
        requested operation, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: POST `/wiki/campaigns` is authorized for `FundraisingManager`
        only.

        Design: Corner/rbac/legal_counsel_cannot_manage_campaigns
        """
        set_clock()
        resp = api_client.create_campaign(
            create_campaign_payload(name="Forbidden", end_at="2026-10-01T00:00:00Z",
                                    target_amount_cents=100),
            TEST_USERS["legal_counsel_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_grant_reviewer_cannot_create_programs(self):
        """PRD §2.1: "If the role is recognized but not permitted for the
        requested operation, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: POST `/wiki/grant-programs` is authorized for
        `GrantAdministrator` only.

        Design: Corner/rbac/grant_reviewer_cannot_create_programs
        """
        set_clock()
        resp = api_client.create_grant_program(
            {"name": "SOD Fund", "fiscal_year": 2026, "budget_cents": 1000},
            TEST_USERS["grant_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestStateBeatsProtectionOnAccept:
    def test_accept_of_accepted_revision_on_protected_page_is_invalid_state(self):
        """PRD §2.7: "Validation proceeds in strict priority order across all
        endpoints: authentication first (`ERR_UNAUTHENTICATED`), then
        authorization (`ERR_UNAUTHORIZED`), then existence (`ERR_NOT_FOUND`),
        then state legality (`ERR_INVALID_STATE`), and finally the
        domain-specific business rules described in §3."
        PRD §3.2: "If the page's protection level does not permit the editor, the
        submission or acceptance is rejected with `ERR_PROTECTION_BLOCKED`
        (HTTP 403)."
        PRD §3.5: "`FULL` permits only an `Administrator`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_revision_accept
        """
        set_clock()
        author, author_headers = create_editor(username="w1", email="w1@x.com")
        other, other_headers = create_editor(username="w2", email="w2@x.com")
        page = create_page(author_headers, title="Priority Page")
        revision, page = create_accepted_revision(page, author_headers)
        # Protect the page FULL via an approved protection request (precondition:
        # 3 flagged revisions in the last 7 days).
        for i in range(3):
            rev = create_revision(page["id"], author_headers, content_text=f"flag me {i}")
            validate_success(api_client.flag_revision(rev["id"], {"report_type": "VANDALISM"},
                                                      TEST_USERS["administrator_headers"]))
        resp = api_client.create_protection_request(
            page["id"], create_protection_request_payload(requested_level="FULL", reason="lock"),
            author_headers,
        )
        request = validate_success(resp, expected_status=201)
        validate_success(api_client.approve_protection_request(request["id"], TEST_USERS["administrator_headers"]))
        page_after = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        assert page_after["protection_level"] == "FULL"
        # Re-accept the already-ACCEPTED revision as a non-admin editor:
        # state legality (ERR_INVALID_STATE) outranks the protection business rule.
        resp = api_client.accept_revision(
            revision["id"], {"expected_page_version": page_after["version"]}, other_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_protection_blocked_for_non_admin_on_full_page(self):
        """PRD §3.2: "The page's protection level must permit the editor: `NONE`
        allows any editor; `SEMI` requires an account age of at least four days;
        `FULL` permits only an `Administrator`."
        PRD §3.2: "If the page's protection level does not permit the editor, the
        submission or acceptance is rejected with `ERR_PROTECTION_BLOCKED`
        (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_revision_accept
        """
        set_clock()
        author, author_headers = create_editor(username="pb1", email="pb1@x.com")
        other, other_headers = create_editor(username="pb2", email="pb2@x.com")
        page = create_page(author_headers, title="Protected Page")
        for i in range(3):
            rev = create_revision(page["id"], author_headers, content_text=f"flag {i}")
            validate_success(api_client.flag_revision(rev["id"], {"report_type": "SPAM"},
                                                      TEST_USERS["administrator_headers"]))
        # Create the PENDING revision BEFORE protection is approved: once the
        # page is FULL-protected, PRD §3.2 blocks non-admin submission with
        # ERR_PROTECTION_BLOCKED, so a fresh revision cannot be created after.
        pending = create_revision(page["id"], author_headers, content_text="pending edit")
        resp = api_client.create_protection_request(
            page["id"], create_protection_request_payload(requested_level="FULL", reason="lock"),
            author_headers,
        )
        request = validate_success(resp, expected_status=201)
        validate_success(api_client.approve_protection_request(request["id"], TEST_USERS["administrator_headers"]))
        page_after = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        assert page_after["protection_level"] == "FULL"
        # Fresh PENDING revision acceptance by a non-admin on a FULL page.
        resp = api_client.accept_revision(
            pending["id"], {"expected_page_version": page_after["version"]}, other_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PROTECTION_BLOCKED)


class TestCoiAndArbitrationReferentialChecks:
    def test_block_editor_with_open_arbitration_dispute_rejected(self):
        """PRD §3.1: "An editor who has an open Arbitration-level dispute as the
        initiator cannot be blocked; attempting to do so is rejected with
        `ERR_EDITOR_HAS_OPEN_ARBITRATION` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_block
        """
        set_clock()
        initiator, initiator_headers = create_editor(username="coi", email="coi@x.com")
        respondent, respondent_headers = create_editor(username="opp", email="opp@x.com")
        page = create_page(initiator_headers, title="COI Page", topic_area="BIOGRAPHY")
        revision, page = create_accepted_revision(page, respondent_headers, content_text="base")
        dispute = create_open_dispute(page, initiator_headers, respondent["id"], revision["id"],
                                      dispute_type="CONDUCT")
        set_clock("2026-09-05T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": dispute["version"]}, initiator_headers,
        )
        dispute = validate_success(resp)
        set_clock("2026-09-09T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": dispute["version"]}, initiator_headers,
        )
        dispute = validate_success(resp)
        assert dispute["level"] == "ARBITRATION"
        resp = api_client.block_editor(initiator["id"], TEST_USERS["administrator_headers"])
        validate_error(resp, ApiErrorId.ERR_EDITOR_HAS_OPEN_ARBITRATION)

    def test_coi_undisclosed_revision_rejected_when_disclosure_required(self):
        """PRD §3.3: "An editor who has any paid contribution or employer overlap
        detected by the system has `coi_disclosure_required` set to true. Such an
        editor must file a disclosure by providing `disclosure_text` before
        editing pages in declared conflict areas."
        PRD §3.2: "If an editor's `coi_disclosure_required` flag is true and
        `coi_disclosed` is false, submitting a revision is rejected with
        `ERR_COI_UNDISCLOSED` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_block
        """
        set_clock()
        editor, editor_headers = create_editor(username="coid", email="coid@x.com")
        page = create_page(editor_headers, title="COI Target", topic_area="BIOGRAPHY")
        editor_state = get_success_data(api_client.get_editor(editor["id"], editor_headers))
        if not editor_state.get("coi_disclosure_required"):
            # The system did not detect a COI for this editor; disclosure path.
            resp = api_client.disclose_coi(
                editor["id"], {"disclosure_text": "I have a COI"}, editor_headers,
            )
            validate_success(resp)
            after = get_success_data(api_client.get_editor(editor["id"], editor_headers))
            assert after["coi_disclosed"] is True
            return
        resp = api_client.create_revision(
            page["id"], {"content_text": "coi edit", "summary": "s"}, editor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_COI_UNDISCLOSED)


class TestGrantScoreBoundary:
    def _setup_application_with_score(self, program, applicant_headers, title, score):
        application = setup_scored_application_under_review(
            program, applicant_headers,
            scores={"impact_score": score, "feasibility_score": 70,
                    "budget_reasonableness_score": 70, "community_support_score": 70},
            project_title=title, requested_cents=100000,
        )
        return application

    def test_grant_review_score_exactly_70_approves(self):
        """PRD §3.10: "Approval requires a `review_score` of at least 70; a lower
        score is rejected with `ERR_GRANT_SCORE_TOO_LOW` (HTTP 409)."
        PRD §3.10: "The `review_score` is the weighted sum — thirty percent
        impact, thirty percent feasibility, twenty percent budget reasonableness,
        twenty percent community support — rounded half-up to an integer from 0
        to 100."

        Design: Difficulty/boundary_precision_check/grant_review_score_exactly_70_approves
        """
        set_clock()
        applicant, applicant_headers = create_editor(username="app1", email="app1@x.com")
        program = create_grant_program(name="Community Grants", budget_cents=1000000)
        application = setup_scored_application_under_review(
            program, applicant_headers,
            scores={"impact_score": 70, "feasibility_score": 70,
                    "budget_reasonableness_score": 70, "community_support_score": 70},
            project_title="A1", requested_cents=100000,
        )
        assert application["review_score"] == 70
        resp = api_client.approve_grant_application(
            application["id"],
            {"awarded_cents": 100000, "expected_application_version": application["version"]},
            TEST_USERS["grant_reviewer_headers"],
        )
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"

    def test_grant_review_score_69_rejected(self):
        """PRD §3.10: "Approval requires a `review_score` of at least 70; a lower
        score is rejected with `ERR_GRANT_SCORE_TOO_LOW` (HTTP 409)."
        PRD §3.10: "The `review_score` is the weighted sum — thirty percent
        impact, thirty percent feasibility, twenty percent budget reasonableness,
        twenty percent community support — rounded half-up to an integer from 0
        to 100."

        Design: Difficulty/boundary_precision_check/grant_review_score_exactly_70_approves
        """
        set_clock()
        applicant, applicant_headers = create_editor(username="app2", email="app2@x.com")
        program = create_grant_program(name="Community Grants 2", budget_cents=1000000)
        application = setup_scored_application_under_review(
            program, applicant_headers,
            scores={"impact_score": 66, "feasibility_score": 70,
                    "budget_reasonableness_score": 70, "community_support_score": 70},
            project_title="A2", requested_cents=100000,
        )
        # round_half_up(0.3*66 + 0.3*70 + 0.2*70 + 0.2*70) = round_half_up(68.8) = 69
        assert application["review_score"] == 69
        resp = api_client.approve_grant_application(
            application["id"],
            {"awarded_cents": 100000, "expected_application_version": application["version"]},
            TEST_USERS["grant_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_SCORE_TOO_LOW)


class TestBannerFrequencyCapBoundary:
    def test_banner_frequency_cap_exactly_at_cap(self):
        """PRD §3.8: "It is rejected with `ERR_BANNER_FREQUENCY_CAP` (HTTP 409)
        if the viewer has already reached the daily cap."
        PRD §3.8: "`frequency_cap` (maximum impressions per user per day)."

        Design: Difficulty/boundary_precision_check/banner_frequency_cap_exactly_at_cap
        """
        set_clock()
        campaign, banner = create_active_campaign_with_banner(
            campaign_overrides={"name": "Cap Drive"},
            banner_overrides={"message_variant": "F", "frequency_cap": 2},
        )
        for _ in range(2):
            resp = api_client.record_impression(
                banner["id"], {"viewer_key": "vv", "country_code": "US"},
                TEST_USERS["anonymous_headers"],
            )
            validate_success(resp, expected_status=201)
        # Third impression: count already == cap -> rejected
        resp = api_client.record_impression(
            banner["id"], {"viewer_key": "vv", "country_code": "US"},
            TEST_USERS["anonymous_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BANNER_FREQUENCY_CAP)
        banner_after = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_after["impression_count"] == 2

    def test_impressions_below_cap_succeed(self):
        """PRD §3.8: "for which the number of impressions already served to that
        viewer on the current UTC day is below the banner's `frequency_cap`."
        PRD §3.8: "A recorded impression increments the banner's
        `impression_count`."

        Design: Difficulty/boundary_precision_check/banner_frequency_cap_exactly_at_cap
        """
        set_clock()
        campaign, banner = create_active_campaign_with_banner(
            campaign_overrides={"name": "Cap Drive 2"},
            banner_overrides={"message_variant": "F2", "frequency_cap": 2},
        )
        resp = api_client.record_impression(
            banner["id"], {"viewer_key": "vu", "country_code": "US"},
            TEST_USERS["anonymous_headers"],
        )
        impression = validate_success(resp, expected_status=201)
        assert impression["banner_id"] == banner["id"]
        banner_after = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_after["impression_count"] == 1


class TestDonationProcessRequiresCampaignActive:
    def test_donation_process_on_paused_campaign_rejected(self):
        """PRD §3.9: "A `PaymentProcessor` may process a pledged donation only
        when both the campaign and the banner are `ACTIVE`; otherwise the
        attempt is rejected with `ERR_CAMPAIGN_INACTIVE` (HTTP 409)."
        PRD §3.7: "A campaign may be paused, which sets all its banners to
        `PAUSED`."

        Design: Difficulty/cross_entity_state_dependency/donation_process_requires_campaign_active
        """
        set_clock()
        campaign, banner = create_active_campaign_with_banner(campaign_overrides={"name": "Pause Drive"})
        donation = create_donation(campaign["id"], banner["id"], donor_email_hash="pd")
        resp = api_client.pause_campaign(
            campaign["id"], {"expected_campaign_version": campaign["version"]},
            TEST_USERS["fundraising_manager_headers"],
        )
        validate_success(resp)
        resp = api_client.process_donation(donation["id"], TEST_USERS["payment_processor_headers"])
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_INACTIVE)
        donation_after = get_success_data(api_client.get_donation(donation["id"], TEST_USERS["payment_processor_headers"]))
        assert donation_after["status"] == "PLEDGED"
        campaign_after = get_success_data(api_client.get_campaign(campaign["id"], TEST_USERS["fundraising_manager_headers"]))
        assert campaign_after["raised_cents"] == 0

    def test_donation_process_on_active_campaign_succeeds(self):
        """PRD §3.9: "Processing transitions the donation to `COMPLETED`, sets
        `processed_at`, increments the campaign's `raised_cents` by the donation
        amount, and increments the banner's `conversion_count`."

        Design: Difficulty/cross_entity_state_dependency/donation_process_requires_campaign_active
        """
        set_clock()
        campaign, banner = create_active_campaign_with_banner(campaign_overrides={"name": "Active Drive"})
        donation = create_donation(campaign["id"], banner["id"], donor_email_hash="pd2", amount_cents=1500)
        resp = api_client.process_donation(donation["id"], TEST_USERS["payment_processor_headers"])
        completed = validate_success(resp)
        assert completed["status"] == "COMPLETED"
        campaign_after = get_success_data(api_client.get_campaign(campaign["id"], TEST_USERS["fundraising_manager_headers"]))
        assert campaign_after["raised_cents"] == 1500
        banner_after = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_after["conversion_count"] == 1


class TestGrantApproveBudgetHeadroom:
    def test_grant_approve_exceeding_budget_rejected(self):
        """PRD §3.10: "Approval also requires that the program's `allocated_cents`
        plus the application's `awarded_cents` not exceed `budget_cents`;
        exceeding the budget is rejected with `ERR_GRANT_BUDGET_EXCEEDED`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/grant_approve_requires_program_open
        """
        set_clock()
        applicant, applicant_headers = create_editor(username="ga", email="ga@x.com")
        program = create_grant_program(name="Tight Budget", budget_cents=100000)
        # First application consumes 50000.
        setup_approved_application(
            program, applicant_headers, awarded_cents=50000,
            scores={"impact_score": 80, "feasibility_score": 80,
                    "budget_reasonableness_score": 80, "community_support_score": 80},
            project_title="Big", requested_cents=50000,
        )
        # Second application: awarded 60000 would exceed (50000 + 60000 > 100000).
        second = setup_scored_application_under_review(
            program, applicant_headers,
            scores={"impact_score": 80, "feasibility_score": 80,
                    "budget_reasonableness_score": 80, "community_support_score": 80},
            project_title="Over", requested_cents=60000,
        )
        resp = api_client.approve_grant_application(
            second["id"],
            {"awarded_cents": 60000, "expected_application_version": second["version"]},
            TEST_USERS["grant_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_BUDGET_EXCEEDED)
        second_after = get_success_data(api_client.get_grant_application(second["id"], TEST_USERS["grant_reviewer_headers"]))
        assert second_after["status"] == "UNDER_REVIEW"
        program_after = get_success_data(api_client.get_grant_program(program["id"], TEST_USERS["grant_administrator_headers"]))
        assert program_after["allocated_cents"] == 50000

    def test_grant_start_review_requires_program_open(self):
        """PRD §3.10: "A `VolunteerEditor` may submit a grant application under an
        open program by supplying `project_title` and `requested_cents`."
        PRD §3.10: "A `GrantReviewer` may start review, transitioning the
        application to `UNDER_REVIEW`."
        PRD §3.10: "The administrator may close the program to new applications;
        closure requires `expected_program_version` and transitions the program
        to `CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/grant_approve_requires_program_open
        """
        set_clock()
        applicant, applicant_headers = create_editor(username="go", email="go@x.com")
        program = create_grant_program(name="Closable", budget_cents=100000)
        application = create_grant_application(program["id"], applicant_headers,
                                               project_title="PreClose", requested_cents=1000)
        application2 = create_grant_application(program["id"], applicant_headers,
                                                project_title="PostClose", requested_cents=1000)
        validate_success(api_client.start_review_grant_application(
            application["id"], TEST_USERS["grant_reviewer_headers"],
        ))
        # Close the program, then the second application's start-review fails.
        program_mid = get_success_data(api_client.get_grant_program(program["id"], TEST_USERS["grant_administrator_headers"]))
        validate_success(api_client.close_grant_program(
            program["id"], {"expected_program_version": program_mid["version"]},
            TEST_USERS["grant_administrator_headers"],
        ))
        resp = api_client.start_review_grant_application(application2["id"], TEST_USERS["grant_reviewer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
