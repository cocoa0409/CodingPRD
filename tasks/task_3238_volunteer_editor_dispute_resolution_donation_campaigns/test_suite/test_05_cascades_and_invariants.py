"""Cross-entity cascades, compensating invariants, conditional actions, and
cross-cutting concerns (optimistic concurrency, frequency-cap day buckets,
immediate consistency). Covers Difficulty rules transitive_cascade and
compensating_invariant, and Corner sections endpoints and cross_cutting_layers.

Skipped instances (PRD-silent, per the PRD-first filter):
- Difficulty/resource_temporal_overlap/campaign_window_overlap_same_geo — the
  PRD states no campaign-window-overlap rule anywhere in §3.7/§3.8.
- Difficulty/resource_temporal_overlap/transparency_report_period_overlap — the
  PRD states no period-overlap rejection rule for report creation in §3.11.
- Corner/consistency_model/donation_process_immediately_visible_in_campaign_total
  — asserts no additional rule beyond the process side effects already covered
  by the cross_entity_state_dependency tests.
"""
import pytest

from test_helpers import (
    api_client, TEST_USERS, make_volunteer_editor_headers,
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_editor, create_page, create_revision, create_accepted_revision,
    create_open_dispute, set_clock,
    create_campaign, create_banner, create_donation,
    create_active_campaign_with_banner, create_completed_donation,
    create_grant_program, setup_scored_application_under_review,
    setup_approved_application,
    create_transparency_report,
)


class TestEditorBlockCascade:
    def _setup_blockable_editor_with_cascade_targets(self, username="blockme"):
        """Editor with 3 confirmed vandalism reports (block precondition), one
        extra PENDING revision, and one OPEN dispute initiated by the editor."""
        editor, editor_headers = create_editor(username=username, email=f"{username}@x.com")
        respondent, respondent_headers = create_editor(username=f"{username}_r", email=f"{username}_r@x.com")
        page = create_page(editor_headers, title="Cascade Page")
        # Three confirmed vandalism reports in the last 90 days.
        for i in range(3):
            rev = create_revision(page["id"], editor_headers, content_text=f"bad {i}")
            resp = api_client.flag_revision(rev["id"], {"report_type": "VANDALISM"},
                                            TEST_USERS["administrator_headers"])
            report = validate_success(resp)
            validate_success(api_client.confirm_vandalism_report(report["id"], TEST_USERS["administrator_headers"]))
        # One still-PENDING revision (never flagged).
        pending_revision = create_revision(page["id"], editor_headers, content_text="pending")
        # One OPEN dispute initiated by the editor against the respondent.
        resp_revision, page = create_accepted_revision(page, respondent_headers, content_text="base")
        dispute = create_open_dispute(page, editor_headers, respondent["id"], resp_revision["id"],
                                      dispute_type="CONDUCT")
        return editor, page, pending_revision, dispute

    def test_editor_block_cascades_to_revisions_and_disputes(self):
        """PRD §3.1: "An `Administrator` may permanently block an editor who has
        three or more confirmed vandalism reports in the last ninety days, or who
        is subject to a court order, or who has repeatedly evaded
        conflict-of-interest disclosure. Blocking transitions `account_status` to
        `BLOCKED` — a terminal state — and flags all pending revisions and closes
        all open disputes the editor initiated."
        PRD §2.6: "When a state transition on one entity affects related
        entities, the API performs those cascades atomically as part of the same
        request."

        Design: Difficulty/transitive_cascade/editor_block_cascades_to_revisions_and_disputes
        """
        set_clock()
        editor, page, pending_revision, dispute = self._setup_blockable_editor_with_cascade_targets()
        resp = api_client.block_editor(editor["id"], TEST_USERS["administrator_headers"])
        blocked = validate_success(resp)
        assert blocked["account_status"] == "BLOCKED"
        revision_after = get_success_data(api_client.get_revision(pending_revision["id"], TEST_USERS["administrator_headers"]))
        assert revision_after["status"] == "FLAGGED"
        dispute_after = get_success_data(api_client.get_dispute(dispute["id"], TEST_USERS["administrator_headers"]))
        assert dispute_after["status"] == "CLOSED"

    def test_editor_block_cascade_creates_vandalism_report_for_flagged_revision(self):
        """PRD §3.1: "Blocking transitions `account_status` to `BLOCKED` — a
        terminal state — and flags all pending revisions and closes all open
        disputes the editor initiated."
        PRD §3.2: "Flagging transitions the revision to `FLAGGED` and creates a
        `VandalismReport`."

        Design: Difficulty/transitive_cascade/editor_block_cascades_to_revisions_and_disputes
        """
        set_clock()
        editor, page, pending_revision, dispute = self._setup_blockable_editor_with_cascade_targets("blockme2")
        validate_success(api_client.block_editor(editor["id"], TEST_USERS["administrator_headers"]))
        resp = api_client.list_vandalism_reports(
            TEST_USERS["administrator_headers"], params={"revision_id": pending_revision["id"]},
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] >= 1, "a vandalism report must exist for the cascade-flagged revision"
        page_after = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        assert page_after["dispute_level"] == "NONE"


class TestCampaignCancelCascade:
    def _setup_active_campaign_with_pledge(self, name="Cancel Drive"):
        campaign, banner = create_active_campaign_with_banner(
            campaign_overrides={"name": name, "target_amount_cents": 500000},
            banner_overrides={"message_variant": "C", "frequency_cap": 3},
        )
        donation = create_donation(campaign["id"], banner["id"], donor_email_hash="dx", amount_cents=1000)
        return campaign, banner, donation

    def test_campaign_cancel_cascades_to_banners_and_donations(self):
        """PRD §3.7: "A campaign may be cancelled at any time; cancellation sets
        all banners to `RETIRED` and transitions all `PLEDGED` donations to
        `FAILED`."
        PRD §2.6: "activating or pausing a campaign also flips the status of
        every banner under that campaign."

        Design: Difficulty/transitive_cascade/campaign_cancel_cascades_to_banners_and_donations
        """
        set_clock()
        campaign, banner, donation = self._setup_active_campaign_with_pledge()
        campaign_mid = get_success_data(api_client.get_campaign(campaign["id"], TEST_USERS["fundraising_manager_headers"]))
        resp = api_client.cancel_campaign(
            campaign["id"], {"expected_campaign_version": campaign_mid["version"]},
            TEST_USERS["fundraising_manager_headers"],
        )
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        banner_after = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_after["status"] == "RETIRED"
        donation_after = get_success_data(api_client.get_donation(donation["id"], TEST_USERS["fundraising_manager_headers"]))
        assert donation_after["status"] == "FAILED"
        campaign_after = get_success_data(api_client.get_campaign(campaign["id"], TEST_USERS["fundraising_manager_headers"]))
        assert campaign_after["raised_cents"] == 0

    def test_campaign_pause_and_reactivate_flip_banner_status(self):
        """PRD §3.7: "A campaign may be paused, which sets all its banners to
        `PAUSED`. A paused campaign may be reactivated provided the current time
        has not passed `end_at`; reactivation sets all banners back to `ACTIVE`."

        Design: Difficulty/transitive_cascade/campaign_cancel_cascades_to_banners_and_donations
        """
        set_clock()
        campaign, banner, donation = self._setup_active_campaign_with_pledge("Pause Drive X")
        campaign_mid = get_success_data(api_client.get_campaign(campaign["id"], TEST_USERS["fundraising_manager_headers"]))
        resp = api_client.pause_campaign(
            campaign["id"], {"expected_campaign_version": campaign_mid["version"]},
            TEST_USERS["fundraising_manager_headers"],
        )
        paused = validate_success(resp)
        assert paused["status"] == "PAUSED"
        banner_after = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_after["status"] == "PAUSED"
        resp = api_client.activate_campaign(
            campaign["id"], {"expected_campaign_version": paused["version"]},
            TEST_USERS["fundraising_manager_headers"],
        )
        reactivated = validate_success(resp)
        assert reactivated["status"] == "ACTIVE"
        banner_after = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_after["status"] == "ACTIVE"


class TestRefundInvariant:
    def test_campaign_raised_cents_refund_invariant(self):
        """PRD §3.9: "Processing transitions the donation to `COMPLETED`, sets
        `processed_at`, increments the campaign's `raised_cents` by the donation
        amount, and increments the banner's `conversion_count`."
        PRD §3.9: "Refunding transitions the donation to `REFUNDED`, decrements
        the campaign's `raised_cents` by the donation amount, and decrements the
        banner's `conversion_count`."

        Design: Difficulty/compensating_invariant/campaign_raised_cents_refund_invariant
        """
        set_clock()
        campaign, banner = create_active_campaign_with_banner(campaign_overrides={"name": "Refund Drive"})
        donation = create_donation(campaign["id"], banner["id"], donor_email_hash="rd", amount_cents=7000)
        validate_success(api_client.process_donation(donation["id"], TEST_USERS["payment_processor_headers"]))
        campaign_mid = get_success_data(api_client.get_campaign(campaign["id"], TEST_USERS["fundraising_manager_headers"]))
        assert campaign_mid["raised_cents"] == 7000
        resp = api_client.refund_donation(donation["id"], TEST_USERS["fundraising_manager_headers"])
        refunded = validate_success(resp)
        assert refunded["status"] == "REFUNDED"
        campaign_after = get_success_data(api_client.get_campaign(campaign["id"], TEST_USERS["fundraising_manager_headers"]))
        assert campaign_after["raised_cents"] == 0
        banner_after = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_after["conversion_count"] == 0

    def test_refund_window_allows_refund_within_90_days(self):
        """PRD §3.9: "A `FundraisingManager` may refund a completed donation
        within ninety days of `processed_at`; a later attempt is rejected with
        `ERR_REFUND_WINDOW_EXPIRED` (HTTP 409)."

        Design: Difficulty/compensating_invariant/campaign_raised_cents_refund_invariant
        """
        set_clock()
        campaign, banner = create_active_campaign_with_banner(
            campaign_overrides={"name": "Refund Window Drive", "end_at": "2027-06-30T23:59:59Z"},
        )
        donation = create_donation(campaign["id"], banner["id"], donor_email_hash="rw2", amount_cents=2500)
        validate_success(api_client.process_donation(donation["id"], TEST_USERS["payment_processor_headers"]))
        # 30 days later — within the 90-day window.
        set_clock("2026-10-01T00:00:00Z")
        resp = api_client.refund_donation(donation["id"], TEST_USERS["fundraising_manager_headers"])
        refunded = validate_success(resp)
        assert refunded["status"] == "REFUNDED"
        campaign_after = get_success_data(api_client.get_campaign(campaign["id"], TEST_USERS["fundraising_manager_headers"]))
        assert campaign_after["raised_cents"] == 0


class TestGrantBudgetInvariant:
    def _setup_program_with_first_approval(self, budget=80000, first_award=50000):
        applicant, applicant_headers = create_editor(username="inv", email="inv@x.com")
        program = create_grant_program(name="Invariant Fund", budget_cents=budget)
        setup_approved_application(
            program, applicant_headers, awarded_cents=first_award,
            scores={"impact_score": 90, "feasibility_score": 90,
                    "budget_reasonableness_score": 90, "community_support_score": 90},
            project_title="First", requested_cents=first_award,
        )
        return program, applicant_headers

    def test_grant_allocated_cents_never_exceeds_budget_invariant(self):
        """PRD §3.10: "Approval also requires that the program's `allocated_cents`
        plus the application's `awarded_cents` not exceed `budget_cents`;
        exceeding the budget is rejected with `ERR_GRANT_BUDGET_EXCEEDED`
        (HTTP 409)."
        PRD §3.10: "Approval transitions the application to `APPROVED` and
        increments the program's `allocated_cents` by `awarded_cents`."

        Design: Difficulty/compensating_invariant/grant_allocated_cents_never_exceeds_budget_invariant
        """
        set_clock()
        program, applicant_headers = self._setup_program_with_first_approval()
        second = setup_scored_application_under_review(
            program, applicant_headers,
            scores={"impact_score": 90, "feasibility_score": 90,
                    "budget_reasonableness_score": 90, "community_support_score": 90},
            project_title="Second", requested_cents=40000,
        )
        resp = api_client.approve_grant_application(
            second["id"],
            {"awarded_cents": 40000, "expected_application_version": second["version"]},
            TEST_USERS["grant_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_BUDGET_EXCEEDED)
        program_after = get_success_data(api_client.get_grant_program(program["id"], TEST_USERS["grant_administrator_headers"]))
        assert program_after["allocated_cents"] == 50000
        assert program_after["allocated_cents"] <= program_after["budget_cents"]

    def test_failed_approve_leaves_allocated_cents_bit_identical(self):
        """PRD §3.10: "Approval transitions the application to `APPROVED` and
        increments the program's `allocated_cents` by `awarded_cents`."
        PRD §3.10: "exceeding the budget is rejected with
        `ERR_GRANT_BUDGET_EXCEEDED` (HTTP 409)."

        Design: Difficulty/compensating_invariant/grant_allocated_cents_never_exceeds_budget_invariant
        """
        set_clock()
        program, applicant_headers = self._setup_program_with_first_approval()
        program_before = get_success_data(api_client.get_grant_program(program["id"], TEST_USERS["grant_administrator_headers"]))
        second = setup_scored_application_under_review(
            program, applicant_headers,
            scores={"impact_score": 90, "feasibility_score": 90,
                    "budget_reasonableness_score": 90, "community_support_score": 90},
            project_title="Over2", requested_cents=40000,
        )
        resp = api_client.approve_grant_application(
            second["id"],
            {"awarded_cents": 40000, "expected_application_version": second["version"]},
            TEST_USERS["grant_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_BUDGET_EXCEEDED)
        program_after = get_success_data(api_client.get_grant_program(program["id"], TEST_USERS["grant_administrator_headers"]))
        assert program_after["allocated_cents"] == program_before["allocated_cents"]


class TestTakedownComplianceLocksPage:
    def test_takedown_compliance_locks_page_full(self):
        """PRD §3.11: "Compliance transitions the request to `COMPLIED`; if the
        request is a takedown, the page's `protection_level` is set to `FULL`,
        and if a `target_page_id` was set, the page's revisions are locked."

        Design: Corner/endpoints/takedown_compliance_locks_page_full
        """
        set_clock()
        legal = TEST_USERS["legal_counsel_headers"]
        editor, editor_headers = create_editor(username="tk", email="tk@x.com")
        page = create_page(editor_headers, title="TK Page")
        assert page["protection_level"] == "NONE"
        resp = api_client.create_legal_request(
            {"request_type": "TAKEDOWN", "target_page_id": page["id"], "requesting_party": "Gov"},
            legal,
        )
        legal_request = validate_success(resp, expected_status=201)
        validate_success(api_client.start_review_legal_request(legal_request["id"], legal))
        resp = api_client.comply_legal_request(legal_request["id"], legal)
        complied = validate_success(resp)
        assert complied["status"] == "COMPLIED"
        page_after = get_success_data(api_client.get_page(page["id"], legal))
        assert page_after["protection_level"] == "FULL"


class TestDonationsListFilter:
    def test_donations_list_filter_by_banner_id(self):
        """PRD §4: GET `/wiki/donations` — "List donations, filterable by
        campaign_id or banner_id".
        PRD §2.3: "The `meta` object in list responses includes `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/donations_list_filter_by_banner_id
        """
        set_clock()
        campaign = create_campaign(name="Filter Drive")
        b1 = create_banner(campaign["id"], message_variant="F1")
        b2 = create_banner(campaign["id"], message_variant="F2")
        validate_success(api_client.activate_campaign(
            campaign["id"], {"expected_campaign_version": campaign["version"]},
            TEST_USERS["fundraising_manager_headers"],
        ))
        create_donation(campaign["id"], b1["id"], donor_email_hash="f1", amount_cents=100)
        create_donation(campaign["id"], b2["id"], donor_email_hash="f2", amount_cents=200)
        resp = api_client.list_donations(
            TEST_USERS["fundraising_manager_headers"], params={"banner_id": b1["id"]},
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["banner_id"] == b1["id"]
        assert data[0]["amount_cents"] == 100


class TestOptimisticConcurrency:
    def test_occ_stale_page_version_on_accept(self):
        """PRD §2.8: "Accepting a revision requires `expected_page_version`
        matching the target `WikiPage`'s current `version`."
        PRD §2.8: "If the value does not match the parent entity's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_page_version_on_accept
        """
        set_clock()
        editor, editor_headers = create_editor(username="occ", email="occ@x.com")
        page = create_page(editor_headers, title="OCC Page")
        r1 = create_revision(page["id"], editor_headers, content_text="r1")
        r2 = create_revision(page["id"], editor_headers, content_text="r2")
        # First accept bumps the page version.
        resp = api_client.accept_revision(
            r1["id"], {"expected_page_version": page["version"]}, TEST_USERS["administrator_headers"],
        )
        validate_success(resp)
        page_mid = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        assert page_mid["version"] == page["version"] + 1
        # Second accept with the stale captured version is rejected.
        resp = api_client.accept_revision(
            r2["id"], {"expected_page_version": page["version"]}, TEST_USERS["administrator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_stale_report_version_on_publish(self):
        """PRD §2.8: "Publishing a transparency report requires
        `expected_report_version` matching the target `TransparencyReport`'s
        current `version`."
        PRD §2.8: "If the value does not match the parent entity's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_report_version_on_publish
        """
        set_clock()
        legal = TEST_USERS["legal_counsel_headers"]
        report = create_transparency_report(
            period_start="2026-01-01T00:00:00Z", period_end="2026-03-31T23:59:59Z",
        )
        resp = api_client.publish_transparency_report(
            report["id"], {"expected_report_version": report["version"] - 1}, legal,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_success_data(api_client.get_transparency_report(report["id"], legal))
        assert after["status"] == "DRAFT"


class TestFrequencyCapDayBucket:
    def test_frequency_cap_resets_on_new_day_bucket(self):
        """PRD §3.8: "It is rejected with `ERR_BANNER_FREQUENCY_CAP` (HTTP 409)
        if the viewer has already reached the daily cap."
        PRD §3.8: "The impression's `day_bucket` is derived from `served_at` as
        the UTC date in `YYYY-MM-DD` form and is used for frequency-cap
        counting."

        Design: Corner/cross_cutting_layers/frequency_cap_resets_on_new_day_bucket
        """
        set_clock("2026-09-01T23:59:00Z")
        campaign, banner = create_active_campaign_with_banner(
            campaign_overrides={"name": "Reset Drive"},
            banner_overrides={"message_variant": "RS", "frequency_cap": 1},
        )
        resp = api_client.record_impression(
            banner["id"], {"viewer_key": "rv", "country_code": "US"},
            TEST_USERS["anonymous_headers"],
        )
        validate_success(resp, expected_status=201)
        # Same day: second impression exceeds the cap of 1.
        resp = api_client.record_impression(
            banner["id"], {"viewer_key": "rv", "country_code": "US"},
            TEST_USERS["anonymous_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BANNER_FREQUENCY_CAP)
        # New UTC day: the day_bucket rolls over and the same viewer is served again.
        set_clock("2026-09-02T00:01:00Z")
        resp = api_client.record_impression(
            banner["id"], {"viewer_key": "rv", "country_code": "US"},
            TEST_USERS["anonymous_headers"],
        )
        validate_success(resp, expected_status=201)
        banner_after = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_after["impression_count"] == 2
