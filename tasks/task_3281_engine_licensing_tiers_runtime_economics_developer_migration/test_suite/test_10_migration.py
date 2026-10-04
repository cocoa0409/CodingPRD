"""Migration assessments: buyout quote, completion gate, completion cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_org_owner_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_org,
    create_editor_version,
    create_project,
    ship_project,
    setup_shipped_project,
    setup_personal_and_pro_tiers,
    create_subscription,
    create_migration,
    advance_migration,
    setup_cooling_off_migration,
    create_asset_listing_payload,
    create_report,
    submit_report,
    review_report,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / buyout_quote_nonlinear_tenure_and_remaining_months
# ---------------------------------------------------------------------------

class TestBuyoutQuote:
    def test_reduced_tenure_tier_and_partial_month_rounding(self, api):
        """PRD §3.8: "the committed seat remainder is the sum, over the org's ACTIVE and
        EXHAUSTED seat subscriptions, of purchased_seats times 15,000 cents per
        seat-month times the number of remaining whole months until coverage_end (any
        partial remaining month rounds up); and the early termination fee depends on
        the org's tenure measured from its created_at — at least 36 months of tenure,
        no fee; at least 12 months but fewer than 36, ten percent of the sum of the two
        components, rounded half up to whole cents; under 12 months, twenty-five
        percent of that sum, rounded half up. The quote is the sum of the three
        components."

        Design: Difficulty/combinatorial_formula/buyout_quote_nonlinear_tenure_and_remaining_months
        """
        set_clock("2025-09-01T00:00:00Z")
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Migrator", contact_email="m@x.com")
        create_subscription(
            org, purchased_seats=4, coverage_start="2026-09-01", coverage_end="2027-03-01"
        )
        set_clock("2026-12-15T00:00:00Z")

        assessment = create_migration(org)
        advanced = advance_migration(org, assessment["id"], "EXPORT_READY")
        # 4 seats x 15,000 x 3 remaining months = 180,000; 10% of 180,000 = 18,000.
        assert advanced["buyout_quote_cents"] == 198_000

    def test_quote_zero_for_clean_slate_org(self, api):
        """PRD §3.8: "the outstanding invoices component is the org's
        balance_due_cents; the committed seat remainder is the sum, over the org's
        ACTIVE and EXHAUSTED seat subscriptions, of purchased_seats times 15,000 cents
        per seat-month times the number of remaining whole months until coverage_end
        (any partial remaining month rounds up)".

        Design: Difficulty/combinatorial_formula/buyout_quote_nonlinear_tenure_and_remaining_months
        """
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Clean Slate", contact_email="cs@x.com")
        assessment = create_migration(org)
        advanced = advance_migration(org, assessment["id"], "EXPORT_READY")
        # No invoices, no subscriptions: every component is zero.
        assert advanced["buyout_quote_cents"] == 0


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / migration_completion_requires_all_invoices_settled
# ---------------------------------------------------------------------------

class TestMigrationCompletionGate:
    def test_unpaid_invoice_blocks_completion(self, api):
        """PRD §3.8: "Advancing to COMPLETED is gated on three conditions, all enforced
        together under ERR_MIGRATION_BLOCKED: the current date must be on or after
        cooling_off_until, every RuntimeFeeInvoice of the org must be PAID or WAIVED,
        and no AuditCase on the org may be OPENED, EVIDENCE_REQUESTED, or APPEALED."

        Design: Difficulty/cross_entity_state_dependency/migration_completion_requires_all_invoices_settled
        """
        org, ev, project = setup_shipped_project(
            revenue_cents=160_000_000, version_string="2022.3.17f1"
        )
        set_clock("2026-09-01T00:00:00Z")
        report = create_report(org, project["id"], "2026-09", 1_100_000)
        submit_report(org, report["id"])
        review_report(report["id"], "REVIEW")
        review_report(report["id"], "ACCEPT")

        assessment = setup_cooling_off_migration(org)
        set_clock("2026-09-20T00:00:00Z")

        owner = make_org_owner_headers(org["id"])
        resp = api.advance_migration_assessment(
            assessment["id"], {"target": "COMPLETED"}, owner
        )
        validate_error(resp, ApiErrorId.ERR_MIGRATION_BLOCKED.value)

        assessments, _ = validate_paginated(
            api.list_migration_assessments(org["id"], owner)
        )
        assert assessments[0]["assessment_status"] == "COOLING_OFF"

    def test_cooling_off_not_elapsed_blocks_completion(self, api):
        """PRD §3.8: "Advancing to COMPLETED is gated on three conditions, all enforced
        together under ERR_MIGRATION_BLOCKED: the current date must be on or after
        cooling_off_until, every RuntimeFeeInvoice of the org must be PAID or WAIVED,
        and no AuditCase on the org may be OPENED, EVIDENCE_REQUESTED, or APPEALED."

        Design: Difficulty/cross_entity_state_dependency/migration_completion_requires_all_invoices_settled
        """
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Impatient", contact_email="imp@x.com")
        set_clock("2026-09-01T00:00:00Z")
        assessment = setup_cooling_off_migration(org)
        # No clock advance: cooling-off has not elapsed, and there are no invoices.
        owner = make_org_owner_headers(org["id"])
        resp = api.advance_migration_assessment(
            assessment["id"], {"target": "COMPLETED"}, owner
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["data"]["error_id"] in (
            ApiErrorId.ERR_MIGRATION_BLOCKED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ), f"unexpected error_id: {body['data'].get('error_id')}"


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_layers / migration_completion_archives_projects_and_delists
# ---------------------------------------------------------------------------

class TestMigrationCompletionCascade:
    def test_completion_archives_projects_and_delists_listings(self, api):
        """PRD §3.8: "Completion cascades: the org's migration_status becomes MIGRATED,
        every GameProject of the org — DEVELOPMENT, SHIPPED, or FROZEN — transitions to
        ARCHIVED, and every APPROVED AssetListing of the org is DELISTED."

        Design: Corner/cross_cutting_layers/migration_completion_archives_projects_and_delists
        """
        set_clock("2026-09-01T00:00:00Z")
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Mig2 Co", contact_email="m2@x.com")
        ev = create_editor_version("2022.3.70f1", "2022.3", "2025-09-01")
        project = create_project(org, ev["id"], title="Game M2")
        ship_project(org, project)

        owner = make_org_owner_headers(org["id"])
        listing = get_success_data(
            api.create_asset_listing(
                org["id"],
                create_asset_listing_payload(title="Mig Asset", price_cents=10_000),
                owner,
            ),
            201,
        )
        get_success_data(api.submit_listing_review(listing["id"], owner), 200)
        get_success_data(
            api.review_asset_listing(listing["id"], {"action": "APPROVE"}, REVIEWER), 200
        )

        assessment = setup_cooling_off_migration(org)
        set_clock("2026-09-20T00:00:00Z")
        completed = advance_migration(org, assessment["id"], "COMPLETED")
        assert completed["assessment_status"] == "COMPLETED"

        org_now = get_success_data(api.get_org(org["id"], ADMIN), 200)
        assert org_now["migration_status"] == "MIGRATED"

        project_now = get_success_data(api.get_project(project["id"], ADMIN), 200)
        assert project_now["project_status"] == "ARCHIVED"

        listing_now = get_success_data(api.get_asset_listing(listing["id"], ADMIN), 200)
        assert listing_now["listing_status"] == "DELISTED"
