"""Audit cases: conversion cascade, appeal exhaustion."""
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
    declare_revenue,
    setup_personal_and_pro_tiers,
    open_audit_case,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / audit_conversion_depth3_tier_seatbackbill_invoicererate
# ---------------------------------------------------------------------------

class TestAuditConversionCascade:
    def test_conversion_depth3_cascade(self, api):
        """PRD §3.8: "Hop one: the org's effective_tier_code becomes the resolved tier
        and its trust_score drops by 15. Hop two: the back-bill is computed — the org's
        declarations are processed in period_month ascending order (ties broken by
        declared_at ascending), the breach month is the first period whose cumulative
        annualized effective revenue (the annualized projection variant) exceeded the
        old tier's revenue_ceiling_cents, the months since breach are the whole months
        between the breach month and the current month with any partial month rounded
        down, the shortfall is the new tier's seat_minimum minus the total
        purchased_seats across the org's ACTIVE and EXHAUSTED subscriptions (floored at
        zero), and back_bill_cents is the shortfall times the new tier's
        seat_overage_cents times the months since breach. Hop three: every open
        PROVISIONAL invoice on the org is re-rated under the new tier's constants and
        relabeled CONVERTED — if the new tier is not runtime-fee-exempt and the old one
        was, provisional amounts may rise — and balance_due_cents is recomputed."

        Design: Difficulty/transitive_cascade/audit_conversion_depth3_tier_seatbackbill_invoicererate
        """
        set_clock("2026-01-05T00:00:00Z")
        setup_personal_and_pro_tiers()
        org = create_org("PERSONAL", legal_name="Audit Target", contact_email="a@x.com")
        declare_revenue(org["id"], period_month="2026-01", gross_revenue_cents=25_000_000)

        # A SHIPPED project with one report left DRAFT (created before the audit
        # freeze applies).
        ev = create_editor_version("2022.3.11f1", "2022.3", "2025-09-01")
        project = create_project(org, ev["id"], title="Game T")
        ship_project(org, project)
        report = create_report(org, project["id"], "2026-01", 1_100_000)

        case = open_audit_case(org, trigger_reason="REVENUE_CEILING_BREACH")
        get_success_data(api.request_audit_evidence(case["id"], AUDITOR), 200)
        set_clock("2026-06-01T00:00:00Z")

        resolved = get_success_data(
            api.resolve_audit_case(
                case["id"], {"outcome": "CONVERT", "resolved_tier_code": "PRO"}, AUDITOR
            ),
            200,
        )
        assert resolved["back_bill_cents"] == 250_000  # 2 seats x 25,000 x 5 months

        org_now = get_success_data(api.get_org(org["id"], ADMIN), 200)
        assert org_now["effective_tier_code"] == "PRO"
        assert org_now["trust_score"] == 65

    def test_conversion_requires_strictly_higher_tier(self, api):
        """PRD §3.8: "Resolving with outcome CONVERT and a resolved_tier_code forces a
        tier conversion, provided the resolved tier is strictly higher in rank than the
        org's current effective_tier_code".

        Design: Difficulty/transitive_cascade/audit_conversion_depth3_tier_seatbackbill_invoicererate
        """
        setup_personal_and_pro_tiers()
        org = create_org("PERSONAL", legal_name="Audit Target", contact_email="a@x.com")
        declare_revenue(org["id"], period_month="2026-01", gross_revenue_cents=25_000_000)
        case = open_audit_case(org, trigger_reason="REVENUE_CEILING_BREACH")
        get_success_data(api.request_audit_evidence(case["id"], AUDITOR), 200)

        # PERSONAL is not strictly higher than the org's current PERSONAL.
        resp = api.resolve_audit_case(
            case["id"], {"outcome": "CONVERT", "resolved_tier_code": "PERSONAL"}, AUDITOR
        )
        assert resp.status_code in (400, 409, 422), (
            f"expected 4xx rejecting a non-upward conversion, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Queue B — errors / appeal_exhausted_after_two_appeals
# ---------------------------------------------------------------------------

class TestAppealExhaustion:
    def test_third_appeal_rejected(self, api):
        """PRD §3.8: "An OrgOwner appeals a CONVERTED case, provided appeal_count is
        below 2; each appeal increments appeal_count by 1, and an appeal on a case that
        has already exhausted two appeals, or is not CONVERTED, is rejected with
        ERR_APPEAL_EXHAUSTED."

        Design: Corner/errors/appeal_exhausted_after_two_appeals
        """
        setup_personal_and_pro_tiers()
        org = create_org("PERSONAL", legal_name="Appeal Co", contact_email="ap@x.com")
        declare_revenue(org["id"], period_month="2026-01", gross_revenue_cents=25_000_000)
        owner = make_org_owner_headers(org["id"])

        case = open_audit_case(org, trigger_reason="REVENUE_CEILING_BREACH")
        get_success_data(api.request_audit_evidence(case["id"], AUDITOR), 200)
        get_success_data(
            api.resolve_audit_case(
                case["id"], {"outcome": "CONVERT", "resolved_tier_code": "PRO"}, AUDITOR
            ),
            200,
        )

        for _ in range(2):
            appealed = get_success_data(api.appeal_audit_case(case["id"], owner), 200)
            assert appealed["case_status"] == "APPEALED"
            # Deny each appeal: conversion stands, case returns to CONVERTED.
            get_success_data(
                api.resolve_audit_case(
                    case["id"], {"outcome": "CONVERT", "resolved_tier_code": "PRO"}, AUDITOR
                ),
                200,
            )

        resp = api.appeal_audit_case(case["id"], owner)
        validate_error(resp, ApiErrorId.ERR_APPEAL_EXHAUSTED.value)

        cases, _ = validate_paginated(api.list_audit_cases(org["id"], AUDITOR))
        target = [c for c in cases if c["id"] == case["id"]]
        assert len(target) == 1
        assert target[0]["case_status"] == "CONVERTED"
        assert target[0]["appeal_count"] == 2
