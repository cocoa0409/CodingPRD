"""Install reports: OCC, supersession, invalid transitions, audit freeze, RBAC,
dispute/revision cycle, provisional vs final variants, and fee arithmetic."""
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
    create_report,
    ship_project,
    setup_shipped_project,
    setup_shipped_project_with_lifetime,
    setup_personal_and_pro_tiers,
    create_and_submit_report,
    create_and_accept_report,
    create_and_dispute_report,
    submit_report,
    review_report,
    get_invoice_for_report,
    open_audit_case,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Queue B — endpoints / occ_stale_project_version_on_report_create
# ---------------------------------------------------------------------------

class TestReportCreateOCC:
    def test_stale_project_version_rejected(self, api):
        """PRD §2.9: "Creating an install report against a project requires the request
        to carry expected_project_version, holding the version of the GameProject as the
        client last observed it. If the project's current version does not match —
        because, for instance, another writer's report creation has already archived a
        still-DRAFT report for the same period and advanced the project — the create is
        rejected with ERR_STALE_VERSION (HTTP 412)".

        Design: Corner/endpoints/occ_stale_project_version_on_report_create
        """
        org, ev, project = setup_shipped_project(version_string="2022.3.50f1")
        owner = make_org_owner_headers(org["id"])
        stale_version = project["version"]
        get_success_data(
            api.create_install_report(
                project["id"],
                {
                    "period_month": "2026-01",
                    "new_device_installs": 5,
                    "reinstalls": 0,
                    "bundle_installs": 0,
                    "expected_project_version": stale_version,
                },
                owner,
            ),
            201,
        )
        resp = api.create_install_report(
            project["id"],
            {
                "period_month": "2026-02",
                "new_device_installs": 7,
                "reinstalls": 0,
                "bundle_installs": 0,
                "expected_project_version": stale_version,
            },
            owner,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Queue B — endpoints / draft_supersession_archives_prior_draft_and_voids_invoice
# ---------------------------------------------------------------------------

class TestDraftSupersession:
    def test_second_draft_for_same_period_archives_first(self, api):
        """PRD §3.4: "Because a create for a period legitimately supersedes a still-DRAFT
        report for the same period — the prior draft is archived and its PROVISIONAL
        invoice is voided, with the new report's supersedes_report_id pointing back at
        the archived draft".

        Design: Corner/endpoints/draft_supersession_archives_prior_draft_and_voids_invoice
        """
        org, ev, project = setup_shipped_project(version_string="2022.3.51f1")
        owner = make_org_owner_headers(org["id"])
        rep1 = create_report(org, project["id"], "2026-01", 5)
        rep2 = create_report(org, project["id"], "2026-01", 9)

        archived = get_success_data(api.get_install_report(rep1["id"], ADMIN), 200)
        assert archived["report_status"] == "ARCHIVED"
        live = get_success_data(api.get_install_report(rep2["id"], ADMIN), 200)
        assert live["report_status"] == "DRAFT"
        assert live["supersedes_report_id"] == rep1["id"]

        reports, _ = validate_paginated(
            api.list_project_install_reports(project["id"], owner)
        )
        live_for_period = [
            r for r in reports
            if r["period_month"] == "2026-01" and r["report_status"] != "ARCHIVED"
        ]
        assert len(live_for_period) == 1
        assert live_for_period[0]["id"] == rep2["id"]


# ---------------------------------------------------------------------------
# Queue B — state_machines / review_accept_from_draft_returns_invalid_state
# ---------------------------------------------------------------------------

class TestReviewFromDraft:
    def test_review_accept_on_draft_rejected(self, api):
        """PRD §3.4: "From SUBMITTED, a ReviewBoard member takes the report into
        UNDER_REVIEW by reviewing with action REVIEW. From UNDER_REVIEW the same review
        capability, invoked with action ACCEPT, accepts the report".

        Design: Corner/state_machines/review_accept_from_draft_returns_invalid_state
        """
        org, ev, project = setup_shipped_project(version_string="2022.3.20f1")
        report = create_report(org, project["id"], "2026-01", 10)

        resp = api.review_install_report(report["id"], {"action": "ACCEPT"}, REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

        still_draft = get_success_data(api.get_install_report(report["id"], ADMIN), 200)
        assert still_draft["report_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B — validations / report_submit_blocked_by_open_audit
# ---------------------------------------------------------------------------

class TestAuditFreeze:
    def test_submit_blocked_by_open_audit(self, api):
        """PRD §3.4: "Submission requires the owning project to be SHIPPED (not frozen
        or archived) and the owning org to be free of any open audit — an AuditCase in
        OPENED or EVIDENCE_REQUESTED (and, for the migration gate, APPEALED) freezes
        reporting, and a submit attempt during an audit is rejected with
        ERR_AUDIT_IN_PROGRESS."

        Design: Corner/validations/report_submit_blocked_by_open_audit
        """
        org, ev, project = setup_shipped_project(version_string="2022.3.40f1")
        report = create_report(org, project["id"], "2026-01", 10)
        case = open_audit_case(org, trigger_reason="MANUAL")
        get_success_data(api.request_audit_evidence(case["id"], AUDITOR), 200)

        resp = api.submit_install_report(report["id"], make_org_owner_headers(org["id"]))
        validate_error(resp, ApiErrorId.ERR_AUDIT_IN_PROGRESS.value)

        still_draft = get_success_data(api.get_install_report(report["id"], ADMIN), 200)
        assert still_draft["report_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B — rbac / finance_ops_cannot_review_reports
# ---------------------------------------------------------------------------

class TestReviewRoleSeparation:
    def test_finance_ops_cannot_review_reports(self, api):
        """PRD §2.1: "ReviewBoard is the content and install-report reviewer who accepts
        or disputes install reports and approves or rejects asset listings."
        PRD §2.1: "Even with well-formed headers, a caller whose role is not listed as
        authorized for the target endpoint is rejected with ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/finance_ops_cannot_review_reports
        """
        org, ev, project = setup_shipped_project(version_string="2022.3.61f1")
        report = create_and_submit_report(org, project["id"], "2026-01", 5)

        resp = api.review_install_report(report["id"], {"action": "ACCEPT"}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / install_report_dispute_revision_cycle
# ---------------------------------------------------------------------------

class TestDisputeRevisionCycle:
    def test_dispute_revise_resubmit_completes_cycle(self, api):
        """PRD §3.4: "The OrgOwner may revise a DISPUTED report back to DRAFT, supplying
        corrected new_device_installs, reinstalls, and bundle_installs; billable_installs
        is recomputed, and the invoice moves to ADJUSTED with a recomputed
        provisional_amount_cents. The revision cycle DISPUTED back through DRAFT and
        SUBMITTED may repeat as often as needed."

        Design: Difficulty/non_linear_state_machine/install_report_dispute_revision_cycle
        """
        org, ev, project, _ = setup_shipped_project_with_lifetime(
            1_000_000, version_string="2022.3.9f1"
        )
        rep2 = create_and_dispute_report(org, project["id"], "2026-02", 150_000, note="overcount")

        owner = make_org_owner_headers(org["id"])
        revised = get_success_data(
            api.revise_install_report(
                rep2["id"],
                {"new_device_installs": 120_000, "reinstalls": 0, "bundle_installs": 0},
                owner,
            ),
            200,
        )
        assert revised["report_status"] == "DRAFT"
        assert revised["billable_installs"] == 120_000

        resubmitted = get_success_data(api.submit_install_report(rep2["id"], owner), 200)
        assert resubmitted["report_status"] == "SUBMITTED"

        invoice = get_invoice_for_report(rep2["id"])
        assert invoice["assessment_status"] == "PROVISIONAL"
        # 100,000 x 20c + 20,000 x 5c, line-then-sum.
        assert invoice["provisional_amount_cents"] == 2_100_000

    def test_invoice_assessment_flips_across_cycle(self, api):
        """PRD §3.4: "Alternatively the reviewer may dispute the report with action
        DISPUTE and a review_note: the report moves to DISPUTED, the note is stored, and
        the invoice's assessment status becomes DISPUTED with its amount frozen at the
        provisional figure."
        PRD §3.4: "billable_installs is recomputed, and the invoice moves to ADJUSTED
        with a recomputed provisional_amount_cents."

        Design: Difficulty/non_linear_state_machine/install_report_dispute_revision_cycle
        """
        org, ev, project, _ = setup_shipped_project_with_lifetime(
            1_000_000, version_string="2022.3.9f1"
        )
        rep2 = create_and_submit_report(org, project["id"], "2026-02", 150_000)
        invoice = get_invoice_for_report(rep2["id"])
        assert invoice["assessment_status"] == "PROVISIONAL"
        assert invoice["provisional_amount_cents"] == 2_250_000

        review_report(rep2["id"], "REVIEW")
        review_report(rep2["id"], "DISPUTE", review_note="overcount")
        invoice = get_invoice_for_report(rep2["id"])
        assert invoice["assessment_status"] == "DISPUTED"

        owner = make_org_owner_headers(org["id"])
        get_success_data(
            api.revise_install_report(
                rep2["id"],
                {"new_device_installs": 120_000, "reinstalls": 0, "bundle_installs": 0},
                owner,
            ),
            200,
        )
        invoice = get_invoice_for_report(rep2["id"])
        assert invoice["assessment_status"] == "ADJUSTED"
        assert invoice["provisional_amount_cents"] == 2_100_000


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / runtime_fee_provisional_vs_final_after_dispute_revision
# ---------------------------------------------------------------------------

class TestProvisionalVsFinalAfterRevision:
    def test_provisional_charged_final_zero_after_downward_revision(self, api):
        """PRD §3.4: "The final variant runs at acceptance — or when a FinanceOps
        operator explicitly finalizes a PROVISIONAL invoice whose source report is
        ACCEPTED — and recomputes billable_installs from the post-dispute revised
        figures, re-evaluating the gate against the lifetime count at acceptance time; a
        dispute revision that lowers billable installs below the crossing point yields a
        final amount smaller than the provisional for identical originally-submitted
        data."

        Design: Difficulty/dual_variant_calc/runtime_fee_provisional_vs_final_after_dispute_revision
        """
        org, ev, project, _ = setup_shipped_project_with_lifetime(
            950_000, version_string="2022.3.1f1"
        )
        rep2 = create_and_dispute_report(
            org, project["id"], "2026-03", 150_000, note="install count overstated"
        )
        invoice = get_invoice_for_report(rep2["id"])
        # 950k lifetime leaves 50k below the 1M threshold; chargeable = 100k at 20c.
        assert invoice["provisional_amount_cents"] == 2_000_000

        owner = make_org_owner_headers(org["id"])
        get_success_data(
            api.revise_install_report(
                rep2["id"],
                {"new_device_installs": 40_000, "reinstalls": 0, "bundle_installs": 0},
                owner,
            ),
            200,
        )
        get_success_data(api.submit_install_report(rep2["id"], owner), 200)
        review_report(rep2["id"], "REVIEW")
        review_report(rep2["id"], "ACCEPT")

        invoice = get_invoice_for_report(rep2["id"])
        assert invoice["assessment_status"] == "FINALIZED"
        # Revised 40k pulls lifetime + billable (990k) back below the 1M gate.
        assert invoice["final_amount_cents"] == 0

        project_now = get_success_data(api.get_project(project["id"], ADMIN), 200)
        assert project_now["lifetime_installs"] == 990_000

    def test_final_variant_uses_lifetime_at_acceptance(self, api):
        """PRD §3.4: "The provisional variant runs at submit time on the self-reported
        figures and the lifetime count as of submission".
        PRD §3.4: "the invoice's assessment_status becomes FINALIZED with
        final_amount_cents recomputed under the final variant and due_date set to 30
        days after finalization".

        Design: Difficulty/dual_variant_calc/runtime_fee_provisional_vs_final_after_dispute_revision
        """
        org, ev, project, _ = setup_shipped_project_with_lifetime(
            950_000, version_string="2022.3.1f1"
        )
        rep2 = create_and_dispute_report(
            org, project["id"], "2026-03", 150_000, note="install count overstated"
        )
        provisional = get_invoice_for_report(rep2["id"])["provisional_amount_cents"]
        # 950k lifetime leaves 50k below the 1M threshold; chargeable = 100k at 20c.
        assert provisional == 2_000_000

        owner = make_org_owner_headers(org["id"])
        get_success_data(
            api.revise_install_report(
                rep2["id"],
                {"new_device_installs": 40_000, "reinstalls": 0, "bundle_installs": 0},
                owner,
            ),
            200,
        )
        get_success_data(api.submit_install_report(rep2["id"], owner), 200)
        review_report(rep2["id"], "REVIEW")
        review_report(rep2["id"], "ACCEPT")

        invoice = get_invoice_for_report(rep2["id"])
        assert invoice["final_amount_cents"] == 0
        assert invoice["final_amount_cents"] < provisional


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / runtime_fee_line_then_sum_rounding_pinned
# ---------------------------------------------------------------------------

class TestLineThenSumRounding:
    def test_provisional_invoice_splits_rate_tiers(self, api):
        """PRD §3.4: "Chargeable installs are priced marginally: the first 100,000
        chargeable installs in the period are charged at 20 cents each, and every
        chargeable install beyond 100,000 at 5 cents each. Each rate tier's line amount
        is rounded half up to whole cents first, and the invoice amount is the sum of
        the rounded lines — never the other way around."

        Design: Difficulty/combinatorial_formula/runtime_fee_line_then_sum_rounding_pinned
        """
        org, ev, project, _ = setup_shipped_project_with_lifetime(
            1_000_000, version_string="2023.1.0f1"
        )
        rep2 = create_and_submit_report(org, project["id"], "2026-02", 150_000)
        invoice = get_invoice_for_report(rep2["id"])
        # 100,000 x 20c + 50,000 x 5c = 2,000,000 + 250,000.
        assert invoice["provisional_amount_cents"] == 2_250_000

    def test_provisional_uses_self_reported_figures(self, api):
        """PRD §3.4: "At submission the system creates the report's RuntimeFeeInvoice
        in PROVISIONAL assessment status and UNPAID payment status, with
        provisional_amount_cents computed by the provisional variant of the runtime fee
        assessment; lifetime_installs on the project is not yet touched."

        Design: Difficulty/combinatorial_formula/runtime_fee_line_then_sum_rounding_pinned
        """
        org, ev, project, _ = setup_shipped_project_with_lifetime(
            1_000_000, version_string="2023.1.0f1"
        )
        rep2 = create_and_submit_report(org, project["id"], "2026-02", 150_000)
        invoice = get_invoice_for_report(rep2["id"])
        assert invoice["assessment_status"] == "PROVISIONAL"
        assert invoice["payment_status"] == "UNPAID"

        project_now = get_success_data(api.get_project(project["id"], ADMIN), 200)
        assert project_now["lifetime_installs"] == 1_000_000


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / install_threshold_exactly_one_million_vs_one_below
# ---------------------------------------------------------------------------

class TestInstallThresholdBoundary:
    def test_exactly_one_million_charges_nothing(self, api):
        """PRD §3.4: "The gate is a conjunction of two thresholds, evaluated on the
        actual trailing-twelve-months revenue variant: the project's lifetime_installs
        before this report, plus the report's billable_installs, must reach at least one
        million installs, and the org's effective revenue must reach at least one
        hundred million cents."
        PRD §3.4: "Installs below the threshold are never charged: when the threshold
        is crossed within the reporting period, only the portion of billable_installs
        above the threshold minus the prior lifetime count is chargeable."

        Design: Difficulty/boundary_precision_check/install_threshold_exactly_one_million_vs_one_below
        """
        org, ev, project = setup_shipped_project(
            revenue_cents=160_000_000, version_string="2022.3.15f1"
        )
        rep = create_and_accept_report(org, project["id"], "2026-01", 1_000_000)
        invoice = get_invoice_for_report(rep["id"])
        assert invoice["final_amount_cents"] == 0

        project_now = get_success_data(api.get_project(project["id"], ADMIN), 200)
        assert project_now["lifetime_installs"] == 1_000_000

    def test_one_install_above_threshold_is_charged(self, api):
        """PRD §3.4: "Installs below the threshold are never charged: when the
        threshold is crossed within the reporting period, only the portion of
        billable_installs above the threshold minus the prior lifetime count is
        chargeable."

        Design: Difficulty/boundary_precision_check/install_threshold_exactly_one_million_vs_one_below
        """
        org, ev, project = setup_shipped_project(
            revenue_cents=160_000_000, version_string="2022.3.15f1"
        )
        rep = create_and_accept_report(org, project["id"], "2026-01", 1_000_001)
        invoice = get_invoice_for_report(rep["id"])
        # The single install above the threshold is in the 20c band.
        assert invoice["final_amount_cents"] == 20


# ---------------------------------------------------------------------------
# Queue B — calculations / runtime_fee_crossing_split_charges_only_excess
# ---------------------------------------------------------------------------

class TestThresholdCrossingSplit:
    def test_crossing_charges_only_excess(self, api):
        """PRD §3.4: "Installs below the threshold are never charged: when the
        threshold is crossed within the reporting period, only the portion of
        billable_installs above the threshold minus the prior lifetime count is
        chargeable."

        Design: Corner/calculations/runtime_fee_crossing_split_charges_only_excess
        """
        org, ev, project, _ = setup_shipped_project_with_lifetime(
            900_000, version_string="2022.3.21f1"
        )
        rep2 = create_and_submit_report(org, project["id"], "2026-02", 200_000)
        invoice = get_invoice_for_report(rep2["id"])
        # Only 100,000 installs above the threshold are chargeable, all at 20c.
        assert invoice["provisional_amount_cents"] == 2_000_000


# ---------------------------------------------------------------------------
# Queue B — calculations / reinstalls_and_bundle_installs_excluded_from_billable
# ---------------------------------------------------------------------------

class TestBillableInstallsFiltering:
    def test_reinstalls_and_bundle_installs_excluded(self, api):
        """PRD §3.4: "The billable_installs of a report are exactly its
        new_device_installs; reinstalls and bundle installs never contribute."

        Design: Corner/calculations/reinstalls_and_bundle_installs_excluded_from_billable
        """
        org, ev, project = setup_shipped_project(
            revenue_cents=160_000_000, version_string="2022.3.22f1"
        )
        rep = create_and_accept_report(
            org, project["id"], "2026-01", 100, reinstalls=5_000_000, bundle_installs=3_000_000
        )
        assert rep["billable_installs"] == 100

        project_now = get_success_data(api.get_project(project["id"], ADMIN), 200)
        assert project_now["lifetime_installs"] == 100
