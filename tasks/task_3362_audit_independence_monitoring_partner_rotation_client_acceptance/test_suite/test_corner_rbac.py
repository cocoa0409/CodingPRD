"""Breadth claims about the segregation of duties between roles."""

from test_helpers import (
    ApiErrorId,
    COMMITTEE_HEADERS,
    LIAISON_HEADERS,
    NON_EXISTENT_UUID,
    OFFICER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    affiliate_payload,
    client_payload,
    finding_payload,
    fixtures,
    get_acceptance_data,
    get_engagement_data,
    get_review_data,
    make_engagement_partner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAcceptanceSegregation:
    """The independence office and the acceptance committee do not overlap."""

    def test_segregation_holds_in_both_directions(self, api):
        """PRD §2.12: "the committee that approves an acceptance never staffs
        the engagement, the independence office that raises a finding never
        signs the engagement".
        PRD §2.12: "A request that attempts a mutation outside the caller's role
        is rejected with `ERR_UNAUTHORIZED_ROLE`".

        Design: Corner/rbac/independence_officer_cannot_decide_acceptance
        """
        fixtures.set_clock(api)
        world = fixtures.seed_reference_data(api, legal_name="Perrin Optical")
        acceptance = fixtures.open_acceptance(
            api, world["client"]["id"], world["engagement"]["id"],
            industry_expertise_required="TECH", industry_expertise_confirmed=True,
        )
        fixtures.record_integrity(api, acceptance["id"])
        fixtures.submit_acceptance(api, acceptance["id"])

        # The officer may not cast the decision.
        refused_decision = api.decide_acceptance(
            acceptance["id"],
            {"decision": "APPROVE", "decision_notes": "officer attempt"},
            OFFICER_HEADERS,
        )
        validate_error(refused_decision, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        # The committee may not raise a finding.
        refused_finding = api.create_finding(
            finding_payload(
                professional_id=NON_EXISTENT_UUID,
                engagement_id=world["engagement"]["id"],
                expected_engagement_version=world["engagement"]["version"],
                origin="DECLARATION", origin_ref_id="decl-po-1",
                finding_type="WORKLOAD_LIMIT", severity="LOW",
                discovered_on="2026-09-01T00:00:00Z",
            ),
            COMMITTEE_HEADERS,
        )
        validate_error(refused_finding, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        unchanged = get_acceptance_data(api, acceptance["id"])
        assert unchanged["status"] == "SUBMITTED"

    def test_the_committee_decision_still_succeeds(self, api):
        """PRD §2.12: "Acceptance decisions belong exclusively to the
        `ClientAcceptanceCommittee`, which also records the integrity evidence
        those decisions rest on".

        Design: Corner/rbac/independence_officer_cannot_decide_acceptance
        """
        fixtures.set_clock(api)
        world = fixtures.seed_reference_data(api, legal_name="Perrin Optical")
        acceptance = fixtures.build_acceptance(
            api, world["client"]["id"], world["engagement"]["id"],
            expertise_required="TECH",
        )

        fixtures.decide_acceptance_ok(api, acceptance["id"], "APPROVE", "clean")

        decided = get_acceptance_data(api, acceptance["id"])
        engagement = get_engagement_data(api, world["engagement"]["id"])
        assert decided["status"] == "APPROVED"
        assert engagement["status"] == "ACTIVE"


class TestReferenceDataOwnership:
    """Only the platform administrator mints reference data."""

    def test_engagement_partner_cannot_create_reference_data(self, api):
        """PRD §2.12: "Reference data and the logical clock are the
        `PlatformAdmin`'s exclusive domain."

        Design: Corner/rbac/engagement_partner_cannot_create_client
        """
        fixtures.set_clock(api)
        world = fixtures.seed_reference_data(api)

        refused_client = api.create_client(
            client_payload(legal_name="Sable Ridge Capital", industry_code="FINANCIAL_SERVICES"),
            world["ep_headers"],
        )
        validate_error(refused_client, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        refused_affiliate = api.create_affiliate(
            affiliate_payload(
                firm_name="Deloitte Malaysia", country_code="MY",
                network_tier="CORRESPONDENT", independence_framework="IFAC_BASELINE",
            ),
            world["ep_headers"],
        )
        validate_error(refused_affiliate, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        clients, _ = validate_paginated(api.list_clients(PLATFORM_ADMIN_HEADERS))
        assert [row for row in clients if row["legal_name"] == "Sable Ridge Capital"] == []
        affiliates, _ = validate_paginated(api.list_affiliates(PLATFORM_ADMIN_HEADERS))
        assert [row for row in affiliates if row["firm_name"] == "Deloitte Malaysia"] == []

    def test_platform_admin_can_create_the_same_records(self, api):
        """PRD §2.1: "`PlatformAdmin` — the firm operations administrator, who
        owns reference data (clients, affiliates, professionals), affiliate
        attestation intake and the logical clock."

        Design: Corner/rbac/engagement_partner_cannot_create_client
        """
        fixtures.set_clock(api)
        created_client = validate_success(
            api.create_client(
                client_payload(legal_name="Sable Ridge Capital", industry_code="FINANCIAL_SERVICES"),
                PLATFORM_ADMIN_HEADERS,
            ),
            201,
        )
        created_affiliate = validate_success(
            api.create_affiliate(
                affiliate_payload(
                    firm_name="Deloitte Malaysia", country_code="MY",
                    network_tier="CORRESPONDENT", independence_framework="IFAC_BASELINE",
                ),
                PLATFORM_ADMIN_HEADERS,
            ),
            201,
        )
        assert created_client["legal_name"] == "Sable Ridge Capital"
        assert created_affiliate["firm_name"] == "Deloitte Malaysia"


class TestQualityReviewerOwnership:
    """Quality reviews belong to the reviewing professional alone."""

    def test_engagement_partner_cannot_start_a_quality_review(self, api):
        """PRD §2.12: "quality reviews and inspection responses belong
        exclusively to the `QualityReviewer`."

        Design: Corner/rbac/quality_reviewer_exclusive_operations_reject_other_roles
        """
        world = fixtures.scenario_reviewer_ownership(api)
        review_id = world["review"]["id"]

        refused = api.transition_review(
            review_id,
            {"action": "START"},
            make_engagement_partner_headers(world["reviewer"]["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        unchanged = get_review_data(api, review_id)
        assert unchanged["status"] == "SCHEDULED"

    def test_the_quality_reviewer_identity_owns_the_review(self, api):
        """PRD §2.1: "When `X-User-Role` is `EngagementPartner` or
        `QualityReviewer`, `X-User-ID` is the `id` of the acting
        `Professional`".

        Design: Corner/rbac/quality_reviewer_exclusive_operations_reject_other_roles
        """
        world = fixtures.scenario_reviewer_ownership(api)
        review_id = world["review"]["id"]
        reviewer_id = world["reviewer"]["id"]
        assert world["review"]["reviewer_id"] == reviewer_id

        fixtures.review_transition_ok(api, review_id, "START", reviewer_id)

        stored = get_review_data(api, review_id)
        assert stored["status"] == "IN_PROGRESS"
