"""Error catalogue and access tiers: entity-specific 404s on reads and
actions, the authentication/authorization/ownership tiers, and the error
envelope (PRD §2.1, §2.2, §2.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    certify_minutes,
    create_competition_payload,
    create_org,
    make_grantee_staff_headers,
    make_member_headers,
    register_member,
    set_clock,
    setup_active_enrollment,
    setup_org_competition,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
TRUST = TEST_USERS["trust_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestEntitySpecificNotFound:
    @pytest.mark.parametrize(
        "kind,method,path",
        [
            ("ERR_ORGANIZATION_NOT_FOUND", "GET", "/organizations/{uuid}"),
            ("ERR_COMPETITION_NOT_FOUND", "GET", "/competitions/{uuid}"),
            ("ERR_APPLICATION_NOT_FOUND", "GET", "/applications/{uuid}"),
            ("ERR_AWARD_NOT_FOUND", "GET", "/awards/{uuid}"),
            ("ERR_SLOT_NOT_FOUND", "GET", "/slots/{uuid}"),
            ("ERR_MEMBER_NOT_FOUND", "GET", "/members/{uuid}"),
            ("ERR_EDUCATION_AWARD_NOT_FOUND", "GET", "/education-awards/{uuid}"),
            ("ERR_FINDING_NOT_FOUND", "GET", "/findings/{uuid}"),
        ],
    )
    def test_unknown_read_paths_return_entity_specific_404(self, api, kind, method, path):
        """Every single-resource read of an unallocated id returns the
        entity-specific 404, never a generic not-found.

        PRD §2.10: "The not-found errors are resource-specific: `ERR_ORGANIZATION_NOT_FOUND`, `ERR_COMPETITION_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CHECK_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_EDUCATION_AWARD_NOT_FOUND`, `ERR_USE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_GRIEVANCE_NOT_FOUND`, and `ERR_MEASURE_NOT_FOUND`."

        Design: Corner/errors/unknown_read_paths_return_entity_specific_404
        """
        set_clock()
        resp = api.get(path.format(uuid=NON_EXISTENT_UUID), headers=OFFICER)
        err = validate_error(resp, ApiErrorId(kind))
        assert resp.status_code == 404
        assert err["error_id"] == kind

    def test_unknown_check_path_returns_check_not_found(self, api):
        """The component-results action on an unallocated check id resolves to
        the check-specific 404.

        PRD §2.10: "Path identifiers resolve left to right. When a path nests one resource under another, the server validates the leftmost identifier first and rejects with the 404 error of the first segment that does not resolve"

        Design: Corner/errors/unknown_read_paths_return_entity_specific_404
        """
        set_clock()
        resp = api.record_component_result(
            NON_EXISTENT_UUID, {"component": "NSOPR", "result": "CLEAR"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_CHECK_NOT_FOUND)
        assert resp.status_code == 404

    def test_unknown_action_paths_return_entity_specific_404(self, api):
        """Action endpoints on unallocated path ids return the entity-specific
        404 of the path's own resource.

        PRD §2.10: "Path identifiers resolve left to right. When a path nests one resource under another, the server validates the leftmost identifier first and rejects with the 404 error of the first segment that does not resolve — for example, an unknown award segment yields `ERR_AWARD_NOT_FOUND` before any enrollment, slot, visit, measure, or match-report validation beneath it is attempted."

        Design: Corner/errors/unknown_action_paths_return_entity_specific_404
        """
        base = setup_org_competition()
        member = register_member()
        staff = make_grantee_staff_headers(base["org_id"])
        e_ent = api.certify_hour_entry(NON_EXISTENT_UUID, staff)
        validate_error(e_ent, ApiErrorId.ERR_ENTRY_NOT_FOUND)
        e_use = api.decide_use(NON_EXISTENT_UUID, {"decision": "APPROVE"}, TRUST)
        validate_error(e_use, ApiErrorId.ERR_USE_NOT_FOUND)
        e_vis = api.conduct_visit(NON_EXISTENT_UUID, CO)
        validate_error(e_vis, ApiErrorId.ERR_VISIT_NOT_FOUND)
        e_grv = api.escalate_grievance(NON_EXISTENT_UUID, make_member_headers(member["id"]))
        validate_error(e_grv, ApiErrorId.ERR_GRIEVANCE_NOT_FOUND)
        e_msr = api.submit_measure_report(
            NON_EXISTENT_UUID,
            {"period_start": "2026-10-01", "period_end": "2026-12-31", "actual_value": 5},
            staff,
        )
        validate_error(e_msr, ApiErrorId.ERR_MEASURE_NOT_FOUND)

    def test_enrollment_get_unknown_id_returns_enrollment_not_found(self, api):
        """An unallocated enrollmentId yields ERR_ENROLLMENT_NOT_FOUND in the
        standard error envelope.

        PRD §2.10: "The not-found errors are resource-specific"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/entities/enrollment_get_unknown_id_returns_enrollment_not_found
        """
        set_clock()
        resp = api.get_enrollment(NON_EXISTENT_UUID, OFFICER)
        body = resp.json()
        assert body["response_type"] == "error"
        err = validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND)
        assert resp.status_code == 404
        assert err["message"]


class TestAccessTiers:
    def test_missing_auth_headers_is_unauthenticated(self, api):
        """A request carrying neither X-User-ID nor X-User-Role is rejected at
        the authentication tier, before role authorization.

        PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's capacity. A request missing either header, or carrying an `X-User-Role` value outside the declared role set, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/competition_create_missing_auth_headers_returns_unauthenticated
        """
        set_clock()
        resp = api.create_competition(create_competition_payload(), headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401

    def test_member_cannot_create_competition(self, api):
        """The Member role is not admitted to competition creation.

        PRD §2.1: "Each endpoint admits a specific set of roles (enumerated in §4); a caller whose role is not admitted is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/member_cannot_create_competition_returns_unauthorized
        """
        set_clock()
        member = register_member()
        resp = api.create_competition(
            create_competition_payload(), make_member_headers(member["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403

    def test_grantee_staff_cannot_touch_another_orgs_enrollment(self, api, officer_headers):
        """Entity-backed ownership: org B's staff certifying an entry on
        org A's enrollment is rejected, and the entry is unchanged.

        PRD §2.1: "When `X-User-Role` is `GranteeStaff`, `X-User-ID` is the `id` of the acting GranteeOrganization. Ownership checks on any org-scoped resource compare the resource's `organization_id` against `X-User-ID`; a mismatch is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/grantee_staff_cannot_touch_another_orgs_enrollment
        """
        scenario = setup_active_enrollment()
        staff_a = make_grantee_staff_headers(scenario["org_id"])
        entry = validate_success(
            api.create_hour_entry(
                scenario["enrollment_id"],
                {"service_date": "2026-10-16", "minutes": 480, "activity_code": "DIRECT_SERVICE"},
                staff_a,
            ),
            201,
        )
        org_b = create_org(
            legal_name="Other Valley Corps", ein="98-7654321", org_type="PUBLIC_AGENCY"
        )
        resp = api.certify_hour_entry(entry["id"], make_grantee_staff_headers(org_b["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
        rows, _ = validate_paginated(
            api.list_hour_entries(scenario["enrollment_id"], officer_headers)
        )
        assert rows[0]["status"] == "PENDING", "the cross-org attempt changed nothing"
