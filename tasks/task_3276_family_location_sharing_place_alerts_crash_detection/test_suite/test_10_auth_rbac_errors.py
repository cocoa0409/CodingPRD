"""Authentication, authorization, error semantics, and OCC validation order."""
from test_helpers import (
    TEST_USERS,
    change_tier_payload,
    create_circle,
    create_place_payload,
    get_circle_state,
    get_member_state,
    get_success_data,
    invite_and_grant_member,
    invite_and_grant_minor,
    invite_grant_promote_admin,
    invite_member,
    make_admin_headers,
    make_member_headers,
    make_minor_headers,
    make_owner_headers,
    post_fix,
    report_crash_for_member,
    reset_clock,
    run_sweeps,
    set_clock,
    start_trip,
    validate_error,
    validate_paginated,
    validate_success,
    verify_dispatch_payload,
)
from test_helpers.api_client import api_client


class TestAuthentication:
    def test_unauthenticated_request_returns_401(self, api, system_headers):
        """PRD §2.1: "Every request to the API must carry two authentication
        headers: `X-User-ID`, identifying the acting user, and `X-User-Role`,
        naming the role under which that user is acting. ... A request that
        omits either header, or that carries a role outside this set, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_returns_401
        """
        reset_clock()
        resp = api.list_circles({"Content-Type": "application/json"})
        validate_error(resp, "ERR_UNAUTHENTICATED")

    def test_unauthenticated_request_missing_user_id_returns_401(self, api, system_headers):
        """PRD §2.1: "A request that omits either header, or that carries a role
        outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_returns_401
        """
        reset_clock()
        resp = api.list_circles({"X-User-Role": "System", "Content-Type": "application/json"})
        validate_error(resp, "ERR_UNAUTHENTICATED")


class TestForbiddenRoles:
    def test_role_not_permitted_returns_403(self, api, system_headers):
        """PRD §2.1: "A request whose role is well-formed but not permitted for
        the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/role_not_permitted_returns_403
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="RbacTierFam")
        member = invite_and_grant_member(circle, owner_headers, display_name="Sub", email="sub@example.com")
        member_headers = make_member_headers(member["id"])
        version = get_circle_state(circle["id"], member_headers)["version"]
        resp = api.change_tier(
            circle["id"], change_tier_payload("PROTECT", version), member_headers,
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_member_cannot_invite_members(self, api, system_headers):
        """PRD §2.1: "A request whose role is well-formed but not permitted for
        the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST /api/circles/{id}/members | Invite a member to the circle
        | Owner, Admin"

        Design: Corner/validations/role_not_permitted_returns_403
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="RbacInviteFam")
        member = invite_and_grant_member(circle, owner_headers, display_name="Mno", email="mno@example.com")
        resp = api.invite_member(
            circle["id"],
            {"display_name": "Nope2", "birthdate": "1990-01-01T00:00:00Z", "email": "nope2@example.com"},
            make_member_headers(member["id"]),
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_admin_cannot_verify_dispatch(self, api, system_headers):
        """PRD §2.1: "A request whose role is well-formed but not permitted for
        the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST /api/emergency-dispatches/{id}/verify | Owner verifies
        the dispatch, moving it VERIFIED then STAGED | Owner"

        Design: Corner/rbac/admin_cannot_verify_dispatch
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="RBACFam")
        admin, admin_headers = invite_grant_promote_admin(
            circle, owner_headers, display_name="Ad2", email="ad2@example.com",
        )
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        _fix, trip_id = start_trip(circle, owner, owner_headers,
                                   recorded_at="2026-09-01T00:00:00Z")
        crash = report_crash_for_member(circle, owner, owner_headers, trip_id, delta_v=20.0)
        set_clock("2026-09-01T00:11:00Z")
        run_sweeps()
        escalated = get_success_data(api.get_crash(crash["id"], owner_headers))
        dispatch_id = escalated["dispatch_id"]
        resp = api.verify_dispatch(dispatch_id, verify_dispatch_payload(), admin_headers)
        validate_error(resp, "ERR_FORBIDDEN")
        dispatch = get_success_data(api.get_dispatch(dispatch_id, owner_headers))
        assert dispatch["dispatch_status"] == "PENDING_VERIFICATION"

    def test_minor_cannot_invite_member(self, api, system_headers):
        """PRD §2.1: "A request whose role is well-formed but not permitted for
        the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST /api/circles/{id}/members | Invite a member to the circle
        | Owner, Admin"

        Design: Corner/rbac/minor_cannot_invite_member
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="MinorInviteFam")
        kid = invite_and_grant_minor(circle, owner_headers, display_name="K3", email="k3@example.com")
        resp = api.invite_member(
            circle["id"],
            {"display_name": "Nope", "birthdate": "1990-01-01T00:00:00Z", "email": "nope@example.com"},
            make_minor_headers(kid["id"]),
        )
        validate_error(resp, "ERR_FORBIDDEN")


class TestInvalidState:
    def test_err_invalid_state_invalid_transition_generic(self, api, system_headers):
        """PRD §3.2: "Demoting an `ADMIN` back to `MEMBER` has no preconditions
        beyond the circle being writable, and likewise increments the member's
        `version`."

        Design: Corner/errors/err_invalid_state_invalid_transition_generic
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="DemoteFam")
        member = invite_and_grant_member(circle, owner_headers, display_name="M", email="m@example.com")
        resp = api.demote_member(circle["id"], member["id"], owner_headers)
        validate_error(resp, "ERR_INVALID_STATE")

    def test_err_invalid_state_double_demote_rejected(self, api, system_headers):
        """PRD §3.2: "Demoting an `ADMIN` back to `MEMBER` has no preconditions
        beyond the circle being writable, and likewise increments the member's
        `version`."

        Design: Corner/errors/err_invalid_state_invalid_transition_generic
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="DemoteFam2")
        member = invite_and_grant_member(circle, owner_headers, display_name="M2", email="m2@example.com")
        validate_success(api.promote_member(circle["id"], member["id"], owner_headers))
        validate_success(api.demote_member(circle["id"], member["id"], owner_headers))
        resp = api.demote_member(circle["id"], member["id"], owner_headers)
        validate_error(resp, "ERR_INVALID_STATE")


class TestOccValidationOrder:
    def test_state_vs_business_safety_on_minor_consent_revoke(self, api, system_headers):
        """PRD §3.2: "For a `MINOR` target, only the `OWNER` may revoke; an
        attempt by an `ADMIN`, by another member, or by the minor themselves is
        rejected with `ERR_MINOR_CONSENT_LOCKED` (HTTP 403)."
        PRD §3.2: "A successful revocation appends a `ConsentRecord` with
        `consent_action` `REVOKE`, flips the member's `consent_state` to
        `REVOKED`, increments the member's `version`, and triggers three
        compensations across the rest of the system: every location fix the
        member's device subsequently submits is recorded as `REJECTED_CONSENT`
        rather than accepted; every `OPEN` crash event on that member
        transitions to `FALSE_ALARM`; and every wellness check still `SENT` for
        that member is `CANCELLED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_minor_consent_revoke
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="MinorFam")
        kid = invite_and_grant_minor(circle, owner_headers, display_name="Kid", email="kid@example.com")
        # OWNER revokes the minor's consent: kid is now REVOKED.
        validate_success(api.revoke_consent(circle["id"], kid["id"], owner_headers))
        assert get_member_state(circle["id"], kid["id"], owner_headers)["consent_state"] == "REVOKED"
        admin, admin_headers = invite_grant_promote_admin(
            circle, owner_headers, display_name="Ad", email="ad@example.com",
        )
        resp = api.revoke_consent(circle["id"], kid["id"], admin_headers)
        assert resp.status_code in (403, 409), (
            f"revoking an already-REVOKED minor must fail with 403 or 409, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["response_type"] == "error"
        error_id = body["data"]["error_id"]
        if resp.status_code == 403:
            assert error_id == "ERR_MINOR_CONSENT_LOCKED"
        else:
            assert error_id == "ERR_INVALID_STATE"

    def test_owner_revoke_of_granted_minor_succeeds(self, api, system_headers):
        """PRD §3.2: "For a `MINOR` target, only the `OWNER` may revoke; an
        attempt by an `ADMIN`, by another member, or by the minor themselves is
        rejected with `ERR_MINOR_CONSENT_LOCKED` (HTTP 403)."
        PRD §3.2: "A successful revocation appends a `ConsentRecord` with
        `consent_action` `REVOKE`, flips the member's `consent_state` to
        `REVOKED`, increments the member's `version`, and triggers three
        compensations across the rest of the system: every location fix the
        member's device subsequently submits is recorded as `REJECTED_CONSENT`
        rather than accepted; every `OPEN` crash event on that member
        transitions to `FALSE_ALARM`; and every wellness check still `SENT` for
        that member is `CANCELLED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_minor_consent_revoke
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="MinorOkFam")
        kid = invite_and_grant_minor(circle, owner_headers, display_name="Kid2", email="kid2@example.com")
        validate_success(api.revoke_consent(circle["id"], kid["id"], owner_headers))
        assert get_member_state(circle["id"], kid["id"], owner_headers)["consent_state"] == "REVOKED"
