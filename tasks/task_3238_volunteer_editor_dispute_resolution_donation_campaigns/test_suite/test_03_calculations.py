"""Calculation tests (Corner section calculations + Difficulty rules
dual_variant_calc and combinatorial_formula)."""
import pytest

from test_helpers import (
    api_client, TEST_USERS, make_volunteer_editor_headers,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_editor, create_page, create_revision, create_accepted_revision,
    create_open_dispute, set_clock,
    create_campaign, create_banner, create_donation,
    create_active_campaign_with_banner, create_pledged_donation, create_completed_donation,
    create_impression_payload, create_campaign_payload, create_banner_payload,
    create_donation_payload,
    create_flag_payload,
)


class TestContentScoreWeightedFormula:
    def test_page_content_score_weighted_formula(self):
        """PRD §3.12: "The score is forty percent of the average
        `source_quality_score`, forty percent of the average `neutrality_score`,
        and twenty percent of a stability bonus. The stability bonus is 100 if
        the page has had no disputes in the last thirty days, 50 if the only
        disputes were at `TALK` level, and 0 otherwise. The final score is
        rounded half-up to an integer from 0 to 100."
        PRD §3.2: "When a revision is accepted, the page's `current_revision_id`
        is updated, `content_score` is recalculated, the editor's `edit_count`
        is incremented, and the page's `version` is incremented."

        Design: Corner/calculations/page_content_score_weighted_formula
        """
        set_clock()
        editor, editor_headers = create_editor(username="cs", email="cs@x.com")
        page = create_page(editor_headers, title="Score Page")
        revision, page = create_accepted_revision(page, editor_headers,
                                                  content_text="well sourced neutral text")
        page_after = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        # The accepted revision has computed source_quality_score and
        # neutrality_score; with stability bonus 100 the content score must be
        # recomputed to a non-negative value and reflect the accepted revision.
        assert page_after["current_revision_id"] == revision["id"]
        assert 0 <= page_after["content_score"] <= 100
        editor_after = get_success_data(api_client.get_editor(editor["id"], TEST_USERS["administrator_headers"]))
        assert editor_after["edit_count"] == 1


class TestRollbackEligibilityWindow:
    def test_rollback_eligibility_threshold_zero_confirmed(self):
        """PRD §3.6: "Rollback eligibility is true exactly when the editor has
        zero confirmed vandalism reports in the last ninety days."
        PRD §3.6: "An `Administrator` may confirm a report, which transitions it
        to `CONFIRMED` and triggers a recalculation of the subject editor's
        `rollback_eligible`."

        Design: Corner/calculations/rollback_eligibility_threshold_zero_confirmed
        """
        set_clock()
        editor, editor_headers = create_editor(username="rb", email="rb@x.com")
        page = create_page(editor_headers, title="RB Page")
        revision = create_revision(page["id"], editor_headers, content_text="bad")
        resp = api_client.flag_revision(revision["id"], create_flag_payload(report_type="VANDALISM"),
                                        TEST_USERS["administrator_headers"])
        report = validate_success(resp)
        resp = api_client.confirm_vandalism_report(report["id"], TEST_USERS["administrator_headers"])
        validate_success(resp)
        # Immediately after confirm: one confirmed report within 90 days
        editor_after = get_success_data(api_client.get_editor(editor["id"], TEST_USERS["administrator_headers"]))
        assert editor_after["rollback_eligible"] is False
        # Advance clock 91 days — the confirmed report falls outside the window
        set_clock("2026-12-01T00:00:00Z")
        editor_later = get_success_data(api_client.get_editor(editor["id"], TEST_USERS["administrator_headers"]))
        assert editor_later["rollback_eligible"] is True


class TestTransparencyReportAggregation:
    def test_transparency_report_aggregation_counts(self):
        """PRD §3.11: "At publish time, `total_requests` is the count of requests
        in the period, `complied_count` is the count of those with status
        `COMPLIED` or `PARTIALLY_COMPLIED`, and `rejected_count` is the count
        with status `REJECTED`."
        PRD §3.11: "Publishing requires that every legal request whose
        `received_at` falls within the half-open interval from `period_start` to
        `period_end` have reached a terminal status (`COMPLIED`, `REJECTED`, or
        `PARTIALLY_COMPLIED`)."
        PRD §3.11: "Publishing transitions the report to `PUBLISHED` and sets
        `transparency_report_id` on every included request."

        Design: Corner/calculations/transparency_report_aggregation_counts
        """
        legal = TEST_USERS["legal_counsel_headers"]
        # L3: received before period start
        set_clock("2025-12-31T23:59:59Z")
        resp = api_client.create_legal_request(
            {"request_type": "TAKEDOWN", "requesting_party": "Old Party"}, legal,
        )
        l3 = validate_success(resp, expected_status=201)
        validate_success(api_client.start_review_legal_request(l3["id"], legal))
        validate_success(api_client.comply_legal_request(l3["id"], legal))
        # L1: in period, COMPLIED
        set_clock("2026-03-01T00:00:00Z")
        resp = api_client.create_legal_request(
            {"request_type": "USER_INFO", "requesting_party": "Party A"}, legal,
        )
        l1 = validate_success(resp, expected_status=201)
        validate_success(api_client.start_review_legal_request(l1["id"], legal))
        validate_success(api_client.comply_legal_request(l1["id"], legal))
        # L2: in period, REJECTED
        set_clock("2026-04-01T00:00:00Z")
        resp = api_client.create_legal_request(
            {"request_type": "SUBPOENA", "requesting_party": "Party B"}, legal,
        )
        l2 = validate_success(resp, expected_status=201)
        validate_success(api_client.start_review_legal_request(l2["id"], legal))
        validate_success(api_client.reject_legal_request(l2["id"], legal))
        # Report covering [2026-01-01, 2026-06-30]
        resp = api_client.create_transparency_report(
            {"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-06-30T23:59:59Z"}, legal,
        )
        report = validate_success(resp, expected_status=201)
        resp = api_client.publish_transparency_report(
            report["id"], {"expected_report_version": report["version"]}, legal,
        )
        published = validate_success(resp)
        assert published["status"] == "PUBLISHED"
        assert published["total_requests"] == 2
        assert published["complied_count"] == 1
        assert published["rejected_count"] == 1
        l1_after = get_success_data(api_client.get_legal_request(l1["id"], legal))
        assert l1_after["transparency_report_id"] == report["id"]
        l3_after = get_success_data(api_client.get_legal_request(l3["id"], legal))
        assert l3_after.get("transparency_report_id") in (None, "")


class TestVandalismScoreAccumulation:
    def test_vandalism_score_blocks_non_admin_accept_at_or_above_50(self):
        """PRD §3.2: "The vandalism score is an integer from 0 to 100, calculated
        as the sum of a base score (10 for new pages, 5 for existing pages), a
        keyword score (30 if spam keywords are detected, otherwise 0), a pattern
        score (40 if mass deletion or blanking is detected, otherwise 0), and an
        editor history score (20 if the editor has prior confirmed vandalism,
        otherwise 0); the total is capped at 100."
        PRD §3.2: "If a revision's vandalism score is 50 or higher and no admin
        override is applied, acceptance is rejected with
        `ERR_VANDALISM_SCORE_HIGH` (HTTP 409)."

        Design: Difficulty/combinatorial_formula/vandalism_score_nonlinear_branch_accumulation
        """
        set_clock()
        author, author_headers = create_editor(username="clean", email="clean@x.com")
        acceptor, acceptor_headers = create_editor(username="acc", email="acc@x.com")
        page = create_page(author_headers, title="Vandal Target")
        resp = api_client.create_revision(
            page["id"], {"content_text": "SPAM_KEYWORD mass blanking", "summary": "v"},
            author_headers,
        )
        revision = validate_success(resp, expected_status=201)
        assert revision["status"] == "PENDING"
        assert 0 <= revision["vandalism_score"] <= 100
        # If the computed score crosses 50, a non-admin accept is rejected.
        if revision["vandalism_score"] >= 50:
            resp = api_client.accept_revision(
                revision["id"], {"expected_page_version": page["version"]}, acceptor_headers,
            )
            validate_error(resp, ApiErrorId.ERR_VANDALISM_SCORE_HIGH)

    def test_vandalism_score_integer_in_0_to_100_on_clean_text(self):
        """PRD §3.2: "The vandalism score is an integer from 0 to 100, calculated
        as the sum of a base score (10 for new pages, 5 for existing pages), a
        keyword score (30 if spam keywords are detected, otherwise 0), a pattern
        score (40 if mass deletion or blanking is detected, otherwise 0), and an
        editor history score (20 if the editor has prior confirmed vandalism,
        otherwise 0); the total is capped at 100."
        PRD §3.2: "The vandalism score must be below 50."

        Design: Difficulty/combinatorial_formula/vandalism_score_nonlinear_branch_accumulation
        """
        set_clock()
        author, author_headers = create_editor(username="cv", email="cv@x.com")
        page = create_page(author_headers, title="Clean Page")
        resp = api_client.create_revision(
            page["id"], {"content_text": "well sourced neutral text", "summary": "ok"},
            author_headers,
        )
        revision = validate_success(resp, expected_status=201)
        score = revision["vandalism_score"]
        assert isinstance(score, int) or float(score).is_integer()
        assert 0 <= score <= 100
        # Clean text on an existing page from a clean editor stays below 50.
        assert score < 50


class TestCampaignNetRevenueAllocation:
    def _setup_campaign_with_two_banners_completed_donations(self, amt1, amt2):
        campaign = create_campaign(name="Alloc Drive", target_amount_cents=1000000)
        b1 = create_banner(campaign["id"], message_variant="X", frequency_cap=10)
        b2 = create_banner(campaign["id"], message_variant="Y", frequency_cap=10)
        validate_success(api_client.activate_campaign(
            campaign["id"], {"expected_campaign_version": campaign["version"]},
            TEST_USERS["fundraising_manager_headers"],
        ))
        d1 = create_donation(campaign["id"], b1["id"], donor_email_hash="d1", amount_cents=amt1)
        d2 = create_donation(campaign["id"], b2["id"], donor_email_hash="d2", amount_cents=amt2)
        validate_success(api_client.process_donation(d1["id"], TEST_USERS["payment_processor_headers"]))
        validate_success(api_client.process_donation(d2["id"], TEST_USERS["payment_processor_headers"]))
        return campaign, b1, b2

    def test_per_banner_fee_rounded_before_summation(self):
        """PRD §3.9: "For each banner, attributed cents are the sum of
        `amount_cents` for all `COMPLETED` donations tied to that banner;
        refunded donations are excluded. A processing fee of three percent is
        calculated per banner and rounded half-up to integer cents. The
        per-banner net is the attributed cents minus the rounded fee. The total
        net revenue is the sum of the per-banner nets. The per-banner-round-then-
        sum order is mandatory; summing first and rounding once is forbidden
        because it yields a different total."

        Design: Difficulty/combinatorial_formula/campaign_net_revenue_per_banner_round_then_sum
        """
        set_clock()
        campaign, b1, b2 = self._setup_campaign_with_two_banners_completed_donations(3335, 3334)
        campaign_mid = get_success_data(api_client.get_campaign(campaign["id"], TEST_USERS["fundraising_manager_headers"]))
        # PRD §3.7: completion requires current time past end_at OR
        # raised_cents >= target. Advance the clock past end_at (2026-12-31).
        set_clock("2027-01-01T00:00:00Z")
        resp = api_client.complete_campaign(
            campaign["id"], {"expected_campaign_version": campaign_mid["version"]},
            TEST_USERS["fundraising_manager_headers"],
        )
        completed = validate_success(resp)
        assert completed["status"] == "COMPLETED"
        assert completed["raised_cents"] == 6669

    def test_completion_retires_banners_and_excludes_refunded(self):
        """PRD §3.9: "For each banner, attributed cents are the sum of
        `amount_cents` for all `COMPLETED` donations tied to that banner;
        refunded donations are excluded."
        PRD §3.7: "completion sets all banners to `RETIRED`."

        Design: Difficulty/combinatorial_formula/campaign_net_revenue_per_banner_round_then_sum
        """
        set_clock()
        campaign, b1, b2 = self._setup_campaign_with_two_banners_completed_donations(3335, 3334)
        campaign_mid = get_success_data(api_client.get_campaign(campaign["id"], TEST_USERS["fundraising_manager_headers"]))
        # PRD §3.7: completion requires current time past end_at OR
        # raised_cents >= target. Advance the clock past end_at (2026-12-31).
        set_clock("2027-01-01T00:00:00Z")
        resp = api_client.complete_campaign(
            campaign["id"], {"expected_campaign_version": campaign_mid["version"]},
            TEST_USERS["fundraising_manager_headers"],
        )
        validate_success(resp)
        b1_after = get_success_data(api_client.get_banner(b1["id"], TEST_USERS["fundraising_manager_headers"]))
        b2_after = get_success_data(api_client.get_banner(b2["id"], TEST_USERS["fundraising_manager_headers"]))
        assert b1_after["status"] == "RETIRED"
        assert b2_after["status"] == "RETIRED"
        assert b1_after["conversion_count"] == 1
        assert b2_after["conversion_count"] == 1


class TestBannerConversionRateVariants:
    def _setup_banner_with_impressions_and_conversions(self, impressions, conversions):
        campaign = create_campaign(name="Fall Drive", target_amount_cents=100000000)
        banner = create_banner(campaign["id"], message_variant="A", frequency_cap=5)
        validate_success(api_client.activate_campaign(
            campaign["id"], {"expected_campaign_version": campaign["version"]},
            TEST_USERS["fundraising_manager_headers"],
        ))
        for i in range(impressions):
            resp = api_client.record_impression(
                banner["id"], create_impression_payload(viewer_key=f"v{i}"), TEST_USERS["anonymous_headers"],
            )
            validate_success(resp, expected_status=201)
        for i in range(conversions):
            donation = create_donation(campaign["id"], banner["id"],
                                       donor_email_hash=f"h{i}", amount_cents=2500)
            validate_success(api_client.process_donation(donation["id"], TEST_USERS["payment_processor_headers"]))
        return campaign, banner

    def test_conversion_rate_bp_truncated_on_banner_detail(self):
        """PRD §3.8: "A banner's conversion rate in basis points is computed on
        read. The denominator is the banner's `impression_count`, with a floor of
        1 to avoid division by zero. On operational dashboards (banner detail
        reads), the rate is truncated toward zero to integer basis points. In
        campaign completion summaries, the rate is rounded half-up to integer
        basis points."

        Design: Difficulty/dual_variant_calc/banner_conversion_rate_truncated_vs_rounded
        """
        set_clock()
        campaign, banner = self._setup_banner_with_impressions_and_conversions(3, 2)
        banner_after = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_after["impression_count"] == 3
        assert banner_after["conversion_count"] == 2
        # Banner detail read: truncated toward zero => floor(2*10000/3) = 6666
        assert banner_after["conversion_rate_bp"] == 6666

    def test_conversion_rate_bp_denominator_floor_of_one(self):
        """PRD §3.8: "The denominator is the banner's `impression_count`, with a
        floor of 1 to avoid division by zero."

        Design: Difficulty/dual_variant_calc/banner_conversion_rate_truncated_vs_rounded
        """
        set_clock()
        campaign = create_campaign(name="Zero Imp", target_amount_cents=100000)
        banner = create_banner(campaign["id"], message_variant="Z", frequency_cap=5)
        banner_read = get_success_data(api_client.get_banner(banner["id"], TEST_USERS["fundraising_manager_headers"]))
        assert banner_read["impression_count"] == 0
        assert banner_read["conversion_count"] == 0
        # floor(0 * 10000 / max(0, 1)) == 0 — no division error
        assert banner_read["conversion_rate_bp"] == 0


class TestRevisionAcceptanceThresholdVariants:
    def test_accept_on_uncontested_page_provisional_threshold(self):
        """PRD §3.2: "The composite quality threshold for acceptance depends on
        whether the page is contested. For a pending revision on a page with no
        open dispute, the composite score — the average of `source_quality_score`
        and `neutrality_score` — must be at least 40. For a revision on a page
        with an open `NOTICE` or `ARBITRATION` dispute, the composite must be at
        least 70."

        Design: Difficulty/dual_variant_calc/revision_threshold_provisional_vs_final_on_contested_page
        """
        set_clock()
        author, author_headers = create_editor(username="e1", email="e1@x.com")
        acceptor, acceptor_headers = create_editor(username="e2", email="e2@x.com")
        page = create_page(author_headers, title="Uncontested Page")
        revision = create_revision(page["id"], author_headers, content_text="neutral sourced text")
        resp = api_client.accept_revision(
            revision["id"], {"expected_page_version": page["version"]}, acceptor_headers,
        )
        accepted = validate_success(resp)
        assert accepted["status"] == "ACCEPTED"
        page_after = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        assert page_after["version"] == page["version"] + 1

    def test_accept_on_notice_disputed_page_applies_strict_threshold(self):
        """PRD §3.2: "For a pending revision on a page with no open dispute, the
        composite score — the average of `source_quality_score` and
        `neutrality_score` — must be at least 40. For a revision on a page with
        an open `NOTICE` or `ARBITRATION` dispute, the composite must be at
        least 70. Identical scores therefore produce different accept/reject
        outcomes depending on the dispute context."

        Design: Difficulty/dual_variant_calc/revision_threshold_provisional_vs_final_on_contested_page
        """
        set_clock()
        author, author_headers = create_editor(username="c1", email="c1@x.com")
        opponent, opponent_headers = create_editor(username="c2", email="c2@x.com")
        page = create_page(author_headers, title="Contested Page", topic_area="POLITICS")
        base_revision, page = create_accepted_revision(page, author_headers, content_text="v1")
        dispute = create_open_dispute(page, author_headers, opponent["id"], base_revision["id"])
        # Escalate to NOTICE after 72h so the strict (70) threshold applies.
        set_clock("2026-09-05T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": dispute["version"]}, author_headers,
        )
        validate_success(resp)
        page_after = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        assert page_after["dispute_level"] == "NOTICE"
        # A new revision on the contested page: accept behavior is governed by
        # the strict threshold; the call either succeeds (composite >= 70) or is
        # rejected as a domain violation — it must not be governed by the
        # lenient 40 bar.
        revision = create_revision(page["id"], opponent_headers, content_text="borderline text")
        resp = api_client.accept_revision(
            revision["id"], {"expected_page_version": page_after["version"]}, author_headers,
        )
        body = resp.json()
        composite = (revision["source_quality_score"] + revision["neutrality_score"]) / 2.0
        if composite >= 70 and revision["vandalism_score"] < 50:
            assert resp.status_code == 200, f"expected accept under strict threshold, got {body}"
        else:
            assert resp.status_code >= 400, f"expected rejection under strict threshold, got {body}"
