"""Tier determination variants, org onboarding, and base entity contracts."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PERSONAL_TIER,
    PRO_TIER,
    ENTERPRISE_TIER,
    EDUCATION_TIER,
    TEST_USERS,
    make_org_owner_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_org,
    create_org_payload,
    declare_revenue,
    setup_personal_and_pro_tiers,
    setup_all_tiers,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / tier_assessment_partial_year_actual_vs_annualized
# ---------------------------------------------------------------------------

class TestTierAssessmentVariants:
    def test_tier_assessment_variants_partial_year(self, api):
        """PRD §2.7: "The annualized projection variant takes the same sum but, when fewer
        than 12 months have been declared, scales the partial run-rate up to a full year."
        PRD §3.1: "When fewer than 12 months exist, the actual variant takes that partial
        sum as-is while the annualized variant divides the partial sum by the number of
        months declared, multiplies by 12, and rounds half up to whole cents".

        Design: Difficulty/dual_variant_calc/tier_assessment_partial_year_actual_vs_annualized
        """
        setup_all_tiers()
        org = create_org("PERSONAL", legal_name="Small Studio", contact_email="s@x.com")
        for month in ("2026-01", "2026-02", "2026-03", "2026-04"):
            declare_revenue(org["id"], period_month=month, gross_revenue_cents=4_000_000)

        data = validate_success(
            api.get_tier_assessment(org["id"], make_org_owner_headers(org["id"])), 200
        )
        assert data["months_declared"] == 4
        assert data["actual_ttm_revenue_cents"] == 16_000_000
        assert data["annualized_revenue_cents"] == 48_000_000
        assert data["tier_by_actual"] == "PERSONAL"
        assert data["tier_by_annualized"] == "PRO"
        assert data["effective_tier_code"] == "PRO"

    def test_tier_assessment_effective_tier_bumped_to_org(self, api):
        """PRD §3.1: "Each declaration triggers a full tier determination; both variants
        are visible side by side on the tier-assessment computed read, which reports
        org_id, actual_ttm_revenue_cents, annualized_revenue_cents, lifetime_funding_cents,
        months_declared, tier_by_actual, tier_by_annualized, and the org's current
        effective_tier_code."
        PRD §3.1: "The org's effective_tier_code is the higher of its declared tier and
        the signal tier."

        Design: Difficulty/dual_variant_calc/tier_assessment_partial_year_actual_vs_annualized
        """
        setup_all_tiers()
        org = create_org("PERSONAL", legal_name="Small Studio", contact_email="s@x.com")
        for month in ("2026-01", "2026-02", "2026-03", "2026-04"):
            declare_revenue(org["id"], period_month=month, gross_revenue_cents=4_000_000)

        refreshed = validate_success(api.get_org(org["id"], ADMIN), 200)
        assert refreshed["effective_tier_code"] == "PRO"

        assessment = validate_success(api.get_tier_assessment(org["id"], AUDITOR), 200)
        assert assessment["org_id"] == org["id"]
        assert assessment["lifetime_funding_cents"] == 0
        assert assessment["effective_tier_code"] == "PRO"


# ---------------------------------------------------------------------------
# Queue B — entities section
# ---------------------------------------------------------------------------

class TestOrgCreationDefaults:
    def test_org_creation_applies_system_defaults(self, api):
        """PRD §3.1: "At registration the org's effective_tier_code is initialized to
        its declared_tier_code, its trust_score is set to 80 on a 0-to-100 scale, and
        its org_standing is set to GOOD."

        Design: Corner/entities/org_creation_applies_system_defaults
        """
        get_success_data(api.create_tier(dict(PERSONAL_TIER), ADMIN), 201)
        org = validate_success(
            api.create_org(
                create_org_payload(
                    legal_name="Defaults Co",
                    contact_email="d@x.com",
                    declared_tier_code="PERSONAL",
                ),
                ADMIN,
            ),
            201,
        )
        assert org["trust_score"] == 80
        assert org["org_standing"] == "GOOD"
        assert org["effective_tier_code"] == "PERSONAL"
        assert org["migration_status"] == "NONE"
        assert org["balance_due_cents"] == 0


class TestRevenueDeclarationShape:
    def test_revenue_declaration_carries_no_version_or_updated_at(self, api):
        """PRD §2.4: "a RevenueDeclaration carries only id and created_at (both
        updated_at and version are absent — a declaration, once filed, is never
        mutated)".

        Design: Corner/entities/revenue_declaration_immutable_no_version_field
        """
        get_success_data(api.create_tier(dict(PERSONAL_TIER), ADMIN), 201)
        org = create_org("PERSONAL", legal_name="Imm Co", contact_email="i@x.com")
        decl = validate_success(
            api.create_revenue_declaration(
                org["id"],
                {
                    "period_month": "2026-01",
                    "gross_revenue_cents": 1_000_000,
                    "funding_received_cents": 0,
                },
                make_org_owner_headers(org["id"]),
            ),
            201,
        )
        assert "id" in decl and "created_at" in decl
        assert "version" not in decl, "RevenueDeclaration must not expose version"
        assert "updated_at" not in decl, "RevenueDeclaration must not expose updated_at"


class TestDuplicateDeclaration:
    def test_duplicate_declaration_period_rejected(self, api):
        """PRD §3.1: "the period_month the declaration covers (a YYYY-MM string, unique
        per org — a second declaration for an already-covered month is rejected with
        ERR_DUPLICATE_PERIOD)".

        Design: Corner/entities/duplicate_declaration_period_rejected
        """
        get_success_data(api.create_tier(dict(PERSONAL_TIER), ADMIN), 201)
        org = create_org("PERSONAL", legal_name="Dup Co", contact_email="du@x.com")
        owner = make_org_owner_headers(org["id"])
        get_success_data(
            api.create_revenue_declaration(
                org["id"],
                {"period_month": "2026-01", "gross_revenue_cents": 1_000_000, "funding_received_cents": 0},
                owner,
            ),
            201,
        )
        resp = api.create_revenue_declaration(
            org["id"],
            {"period_month": "2026-01", "gross_revenue_cents": 2_000_000, "funding_received_cents": 0},
            owner,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD.value)


class TestPaginationEnvelope:
    def test_revenue_declaration_listing_envelope_defaults(self, api):
        """PRD §2.3: "The limit parameter sets the maximum number of items returned; it
        defaults to 10 when omitted, must be at least 1, and may not exceed 100. The
        offset parameter sets how many items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry limit, offset, total_count, and
        has_more inside the meta object of the response envelope."

        Design: Corner/entities/listing_pagination_envelope
        """
        get_success_data(api.create_tier(dict(PERSONAL_TIER), ADMIN), 201)
        org = create_org("PERSONAL", legal_name="Page Co", contact_email="pg@x.com")
        declare_revenue(org["id"], period_month="2026-01", gross_revenue_cents=1_000_000)

        resp = api.list_revenue_declarations(org["id"], make_org_owner_headers(org["id"]))
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(data) == 1


class TestNotFound:
    def test_get_missing_project_returns_not_found(self, api):
        """PRD §2.10: "The first identifier that does not correspond to an existing
        resource yields ERR_NOT_FOUND (HTTP 404)".

        Design: Corner/entities/get_missing_project_returns_not_found
        """
        resp = api.get_project("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestEducationTierGate:
    def test_education_tier_requires_verified_flag(self, api):
        """PRD §3.1: "An org asserting the EDUCATION tier must also pass education
        verification: registration sets education_verified (defaulting to false) and
        declaring EDUCATION without it is rejected with ERR_TIER_FEATURE_NOT_ALLOWED."

        Design: Corner/validations/education_tier_requires_verified_flag
        """
        get_success_data(api.create_tier(dict(EDUCATION_TIER), ADMIN), 201)

        rejected = api.create_org(
            create_org_payload(
                legal_name="Fake School", contact_email="fs@x.com", declared_tier_code="EDUCATION"
            ),
            ADMIN,
        )
        validate_error(rejected, ApiErrorId.ERR_TIER_FEATURE_NOT_ALLOWED.value)

        ok = validate_success(
            api.create_org(
                create_org_payload(
                    legal_name="Real School",
                    contact_email="rs@x.com",
                    declared_tier_code="EDUCATION",
                    education_verified=True,
                ),
                ADMIN,
            ),
            201,
        )
        assert ok["effective_tier_code"] == "EDUCATION"
