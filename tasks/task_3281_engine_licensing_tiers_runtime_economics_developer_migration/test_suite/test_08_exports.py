"""Export agreements and builds: activeness gates, overlap semantics."""
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
    create_agreement,
    create_export_agreement_payload,
    create_export_build_payload,
    setup_active_agreement,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / export_build_requires_active_agreement
# ---------------------------------------------------------------------------

class TestBuildRequiresActiveAgreement:
    def test_build_against_pending_agreement_rejected(self, api):
        """PRD §3.7: "The referenced agreement must belong to the same org, match the
        build's platform_code, and be ACTIVE — a missing, wrong-org, wrong-platform, or
        non-active agreement is rejected with ERR_AGREEMENT_INACTIVE."

        Design: Difficulty/cross_entity_state_dependency/export_build_requires_active_agreement
        """
        org, ev, project = setup_shipped_project(version_string="2022.3.16f1")
        agreement = create_agreement(org)  # PENDING, never activated
        owner = make_org_owner_headers(org["id"])

        resp = api.create_export_build(
            project["id"],
            create_export_build_payload(agreement["id"], build_label="b0"),
            owner,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_INACTIVE.value)

        builds, _ = validate_paginated(
            api.list_project_export_builds(project["id"], owner)
        )
        assert len(builds) == 0

    def test_build_against_active_agreement_succeeds(self, api):
        """PRD §3.7: "While an agreement is ACTIVE, the org may record ExportBuilds
        against it: an OrgOwner records a build on one of their projects by supplying
        the agreement_id, the platform_code, and a free-form build_label; the server
        stamps created_on."

        Design: Difficulty/cross_entity_state_dependency/export_build_requires_active_agreement
        """
        org, ev, project, agreement = setup_active_agreement()
        owner = make_org_owner_headers(org["id"])
        build = get_success_data(
            api.create_export_build(
                project["id"],
                create_export_build_payload(agreement["id"], build_label="b-ok"),
                owner,
            ),
            201,
        )
        assert build["agreement_id"] == agreement["id"]
        assert build["platform_code"] == "CONSOLE_A"


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict / export_build_referential_beats_temporal_interval
# ---------------------------------------------------------------------------

class TestRevokedAgreementBuildRejected:
    def test_build_against_revoked_agreement_rejected(self, api):
        """PRD §3.7: "The referenced agreement must belong to the same org, match the
        build's platform_code, and be ACTIVE — a missing, wrong-org, wrong-platform, or
        non-active agreement is rejected with ERR_AGREEMENT_INACTIVE."
        PRD §3.7: "A PlatformAdmin revokes an ACTIVE agreement, after which future
        ExportBuild creation for that platform is rejected."

        Design: Difficulty/priority_pair_validation_conflict/export_build_referential_beats_temporal_interval
        """
        org, ev, project, agreement = setup_active_agreement()
        get_success_data(api.revoke_export_agreement(agreement["id"], ADMIN), 200)

        owner = make_org_owner_headers(org["id"])
        resp = api.create_export_build(
            project["id"],
            create_export_build_payload(agreement["id"], build_label="b1"),
            owner,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_INACTIVE.value)

    def test_revoked_agreement_blocks_all_future_builds(self, api):
        """PRD §3.7: "A PlatformAdmin revokes an ACTIVE agreement, after which future
        ExportBuild creation for that platform is rejected."

        Design: Difficulty/priority_pair_validation_conflict/export_build_referential_beats_temporal_interval
        """
        org, ev, project, agreement = setup_active_agreement()
        owner = make_org_owner_headers(org["id"])
        first = get_success_data(
            api.create_export_build(
                project["id"],
                create_export_build_payload(agreement["id"], build_label="pre-revoke"),
                owner,
            ),
            201,
        )
        assert first["agreement_id"] == agreement["id"]

        get_success_data(api.revoke_export_agreement(agreement["id"], ADMIN), 200)

        resp = api.create_export_build(
            project["id"],
            create_export_build_payload(agreement["id"], build_label="post-revoke"),
            owner,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_INACTIVE.value)

        builds, _ = validate_paginated(
            api.list_project_export_builds(project["id"], owner)
        )
        assert len(builds) == 1


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / export_agreement_closed_interval_adjacency_conflicts
# ---------------------------------------------------------------------------

class TestAgreementClosedIntervalOverlap:
    def test_shared_endpoint_conflicts(self, api):
        """PRD §3.7: "The term is a closed interval: both endpoints are inclusive,
        term_start must be on or before term_end (a reversed or malformed interval
        fails with ERR_INVALID_INTERVAL), and the overlap rule is correspondingly
        stricter than the subscription rule — two ACTIVE or PENDING agreements for the
        same org and platform whose closed terms so much as touch, including an
        existing agreement ending exactly on the new term's start date, conflict, and a
        conflicting request fails with ERR_AGREEMENT_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/export_agreement_closed_interval_adjacency_conflicts
        """
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Closed Co", contact_email="cl@x.com")
        create_agreement(org, term_start="2026-01-01", term_end="2026-12-31")

        owner = make_org_owner_headers(org["id"])
        resp = api.create_export_agreement(
            org["id"],
            create_export_agreement_payload(term_start="2026-12-31", term_end="2027-06-30"),
            owner,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_OVERLAP.value)

    def test_disjoint_terms_do_not_conflict(self, api):
        """PRD §3.7: "two ACTIVE or PENDING agreements for the same org and platform
        whose closed terms so much as touch, including an existing agreement ending
        exactly on the new term's start date, conflict, and a conflicting request fails
        with ERR_AGREEMENT_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/export_agreement_closed_interval_adjacency_conflicts
        """
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Closed Co", contact_email="cl@x.com")
        create_agreement(org, term_start="2026-01-01", term_end="2026-12-31")

        owner = make_org_owner_headers(org["id"])
        second = get_success_data(
            api.create_export_agreement(
                org["id"],
                create_export_agreement_payload(term_start="2027-01-01", term_end="2027-06-30"),
                owner,
            ),
            201,
        )
        assert second["agreement_status"] == "PENDING"
