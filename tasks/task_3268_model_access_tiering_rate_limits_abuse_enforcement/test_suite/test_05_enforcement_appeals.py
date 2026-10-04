"""Abuse enforcement, OCC, appeals, reinstatement, and segregation-of-duties tests."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    create_abuse_case_payload,
    create_and_activate_organization,
    create_claimed_case,
    create_organization,
    create_settled_payment,
    issue_action,
    make_organization_admin_headers,
    make_trust_analyst_headers,
    make_trust_lead_headers,
    set_clock,
    setup_org_with_pending_appeal,
    setup_restricted_org,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStaleVersionOnCaseAction:
    def test_stale_expected_version_rejected(self, api):
        """PRD §3.7: "is the single OCC-guarded write of §2.10 — the request must carry `expected_abuse_case_version` matching the case's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.10: "If the case's current `version` no longer matches — because another writer has advanced the case since the caller read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from acting on a case state it has not seen."

        Design: Corner/errors/err_stale_version_on_case_action
        """
        set_clock()
        org = create_organization(legal_name="OCC Co")
        case, case_v = create_claimed_case(org["id"], severity="MEDIUM", analyst_id="analyst-1")
        resp = api.create_abuse_action(
            case["id"],
            {"action_type": "WARN", "expected_abuse_case_version": case_v - 1},
            make_trust_analyst_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestAppealAlreadyPending:
    def test_second_pending_appeal_rejected(self, api):
        """PRD §3.8: "At most one appeal may be `PENDING` for a case at a time; a second filing while one is pending is rejected with `ERR_APPEAL_ALREADY_PENDING` (HTTP 409)."

        Design: Corner/errors/err_appeal_already_pending_triggered
        """
        set_clock()
        org, case, appeal = setup_org_with_pending_appeal(legal_name="Double Appeal Co")
        resp = api.create_appeal(
            {"abuse_case_id": case["id"]}, make_organization_admin_headers(org["id"])
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_PENDING)


class TestAppealSegregationOfDuties:
    def test_resolver_must_differ_from_action_issuer(self, api):
        """PRD §3.8: "Segregation of duties applies again: the resolver, recorded as the appeal's `resolved_by`, must not be the user whose `issued_by` stands on the appealed action — a self-resolution is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

        Design: Corner/rbac/segregation_of_duties_appeal_resolver
        """
        set_clock()
        org = create_and_activate_organization(legal_name="SoD Appeal Co")
        case, case_v = create_claimed_case(
            org["id"], severity="HIGH", analyst_id="shared-user"
        )
        issue_action(case["id"], case_v, "RESTRICT", issuer_id="shared-user")
        appeal = validate_success(
            api.create_appeal(
                {"abuse_case_id": case["id"]}, make_organization_admin_headers(org["id"])
            ),
            expected_status=201,
        )
        resp = api.grant_appeal(appeal["id"], make_trust_lead_headers("shared-user"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestAppealGrantCascade:
    def _setup_and_grant(self, api):
        set_clock()
        org = create_and_activate_organization(legal_name="Reinstate Co")
        case, case_v = create_claimed_case(
            org["id"], severity="HIGH", analyst_id="analyst-1"
        )
        action = issue_action(case["id"], case_v, "RESTRICT", issuer_id="analyst-1")
        appeal = validate_success(
            api.create_appeal(
                {"abuse_case_id": case["id"]}, make_organization_admin_headers(org["id"])
            ),
            expected_status=201,
        )
        granted = validate_success(
            api.grant_appeal(appeal["id"], make_trust_lead_headers("lead-other"))
        )
        return org, case, action, appeal, granted

    def test_grant_reinstates_case_and_organization(self, api):
        """PRD §3.8: "Granting is a compound transition. The appeal moves `PENDING → GRANTED` (terminal) and its `version` increments; the appealed action is revoked, stamping its `revoked_at` with the current logical time; the case moves `ACTIONED → REINSTATED` (terminal); and the organization returns to its pre-action posture — `SUSPENDED → ACTIVE` or `RESTRICTED → ACTIVE` as applicable — with its `version` incremented."

        Design: Corner/state_machines/appeal_grant_cascades_reinstate_organization
        """
        org, case, action, appeal, granted = self._setup_and_grant(api)
        assert granted["status"] == "GRANTED"
        case_data = validate_success(api.get_abuse_case(case["id"], ADMIN))
        assert case_data["status"] == "REINSTATED"
        org_data = validate_success(api.get_organization(org["id"], ADMIN))
        assert org_data["status"] == "ACTIVE", (
            f"pre-action posture must be restored, got {org_data['status']}"
        )

    def test_grant_revokes_appealed_action(self, api):
        """PRD §3.8: "the appealed action is revoked, stamping its `revoked_at` with the current logical time"

        Design: Corner/state_machines/appeal_grant_cascades_reinstate_organization
        """
        org, case, action, appeal, granted = self._setup_and_grant(api)
        actions, meta = validate_paginated(api.list_abuse_case_actions(case["id"], ADMIN))
        assert meta["total_count"] == 1
        assert actions[0]["revoked_at"] is not None, (
            "the appealed action must carry a non-null revoked_at after the grant"
        )
