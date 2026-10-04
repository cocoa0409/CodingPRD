"""Envelope shape, resource-scoped 404s, auth, RBAC, ownership, and OCC."""
import pytest

from test_helpers import (
    ADMIN,
    ASSOCIATE,
    MANAGER,
    UNKNOWN_ID,
    ApiErrorId,
    create_club,
    create_club_payload,
    create_curbside_order,
    create_item,
    create_member,
    create_session,
    get_member,
    member_headers,
    scan_unit_line,
    setup_club_member,
    setup_paid_session,
    setup_session_with_unit_item,
    stage_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestNotFound:
    def test_get_session_not_found_returns_404(self, api):
        """PRD §2.8: "Each resource family has its own scoped code:
        `ERR_CLUB_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`,
        `ERR_SCAN_SESSION_NOT_FOUND`, `ERR_SCAN_LINE_NOT_FOUND`,
        `ERR_INTERCEPT_NOT_FOUND`, `ERR_EXIT_VERIFICATION_NOT_FOUND`,
        `ERR_LP_CASE_NOT_FOUND`, and `ERR_CURBSIDE_ORDER_NOT_FOUND`, all HTTP
        404."

        Design: Corner/entities/get_session_not_found_returns_404
        """
        resp = api.get_scan_session(UNKNOWN_ID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCAN_SESSION_NOT_FOUND)

    def test_get_club_not_found_returns_404(self, api):
        """PRD §2.8: "Each resource family has its own scoped code:
        `ERR_CLUB_NOT_FOUND`, ... all HTTP 404."

        Design: Corner/entities/get_club_not_found_returns_404
        """
        resp = api.get_club(UNKNOWN_ID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLUB_NOT_FOUND)

    def test_get_member_not_found_returns_404(self, api):
        """PRD §2.8: "Each resource family has its own scoped code: ...
        `ERR_MEMBER_NOT_FOUND`, ... all HTTP 404."

        Design: Corner/entities/get_member_not_found_returns_404
        """
        resp = api.get_member(UNKNOWN_ID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND)

    def test_unknown_ids_return_resource_specific_404s(self, api):
        """PRD §2.8: "Each resource family has its own scoped code:
        `ERR_CLUB_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`,
        `ERR_SCAN_SESSION_NOT_FOUND`, `ERR_SCAN_LINE_NOT_FOUND`,
        `ERR_INTERCEPT_NOT_FOUND`, `ERR_EXIT_VERIFICATION_NOT_FOUND`,
        `ERR_LP_CASE_NOT_FOUND`, and `ERR_CURBSIDE_ORDER_NOT_FOUND`, all HTTP
        404."

        Design: Corner/entities/unknown_ids_return_resource_specific_404s
        """
        checks = [
            (api.get_offer(UNKNOWN_ID, ADMIN), ApiErrorId.ERR_OFFER_NOT_FOUND),
            (api.get_scan_line(UNKNOWN_ID, ADMIN), ApiErrorId.ERR_SCAN_LINE_NOT_FOUND),
            (api.get_intercept(UNKNOWN_ID, ADMIN), ApiErrorId.ERR_INTERCEPT_NOT_FOUND),
            (
                api.get_exit_verification(UNKNOWN_ID, ADMIN),
                ApiErrorId.ERR_EXIT_VERIFICATION_NOT_FOUND,
            ),
            (api.get_lp_case(UNKNOWN_ID, ADMIN), ApiErrorId.ERR_LP_CASE_NOT_FOUND),
            (
                api.get_curbside_order(UNKNOWN_ID, ADMIN),
                ApiErrorId.ERR_CURBSIDE_ORDER_NOT_FOUND,
            ),
        ]
        for resp, error_id in checks:
            validate_error(resp, error_id)


class TestEnvelope:
    def test_error_envelope_shape_and_success_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard error response format" carrying `data.error_id` and
        `data.message`; "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" with
        `meta.api_request_id` and a `response_type` of "object" for a single
        resource.

        Design: Corner/errors/error_envelope_shape_and_success_envelope_shape
        """
        resp = api.get_club(UNKNOWN_ID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLUB_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert "api_request_id" in body["meta"]
        assert "message" in body["data"]

        resp = api.create_club(create_club_payload(name="Club EV"), ADMIN)
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["data"]["id"]


class TestAuth:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        value outside the declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api.get_club(UNKNOWN_ID, headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_unknown_role_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        value outside the declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api.get_club(
            UNKNOWN_ID,
            headers={
                "X-User-ID": "whoever",
                "X-User-Role": "SuperUser",
                "Content-Type": "application/json",
            },
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestOwnership:
    def test_member_cannot_pay_other_members_session(self, api):
        """PRD §2.1: "ownership checks on any resource that references a
        `Member` — scan sessions and curbside orders in particular — compare
        the resource's member foreign key to `X-User-ID`, and a mismatch is
        rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` (HTTP 403)."

        Design: Corner/validations/member_cannot_pay_other_members_session
        """
        club, _member = setup_club_member()
        item = create_item(club["id"], sku="MILK", unit_price_cents=500)
        member_a = create_member(club["id"], tier="CLUB", birth_year=1990)
        member_b = create_member(club["id"], tier="CLUB", birth_year=1991)
        session = create_session(club, member_a)
        scan_unit_line(session, member_a, item, quantity=1)

        resp = api.pay_session(session["id"], member_headers(member_b))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP)
        resp = api.get_scan_session(session["id"], ADMIN)
        assert resp.json()["data"]["status"] == "OPEN"


class TestRbac:
    def test_member_cannot_resolve_intercept_unauthorized(self, api):
        """PRD §2.1: "If the headers are well-formed but the role is not
        permitted to call the endpoint, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."; PRD §4: "POST |
        `/intercepts/{id}/resolve` | Approve or deny a restricted intercept |
        Associate".

        Design: Corner/rbac/member_cannot_resolve_intercept_unauthorized
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=1500, quantity=1,
            member_overrides={"tier": "PLUS", "birth_year": 1990},
            restricted_class="ALCOHOL",
        )
        resp = api.list_session_intercepts(session["id"], ASSOCIATE)
        intercept = resp.json()["data"][0]

        resp = api.resolve_intercept(
            intercept["id"],
            {"decision": "APPROVE", "birth_year_verified": True},
            member_headers(member),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_associate_cannot_patch_club_unauthorized(self, api):
        """PRD §2.1: "If the headers are well-formed but the role is not
        permitted to call the endpoint, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."; PRD §4: "PATCH | `/clubs/{id}` |
        Update club configuration (OCC-guarded) | ClubManager".

        Design: Corner/rbac/associate_cannot_patch_club_unauthorized
        """
        club = create_club()
        resp = api.update_club(
            club["id"],
            {"expected_club_version": club["version"], "scan_go_enabled": False},
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        resp = api.get_club(club["id"], ADMIN)
        assert resp.json()["data"]["scan_go_enabled"] is True

    def test_club_manager_cannot_void_payment_unauthorized(self, api):
        """PRD §2.1: "If the headers are well-formed but the role is not
        permitted to call the endpoint, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."; PRD §4: "POST |
        `/scan-sessions/{id}/void-payment` | Void a paid session with full
        refund | LossPreventionOfficer".

        Design: Corner/rbac/club_manager_cannot_void_payment_unauthorized
        """
        club, item, member, session, pay_data = setup_paid_session(
            price_cents=500, quantity=1,
        )
        resp = api.void_payment(session["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        resp = api.get_scan_session(session["id"], ADMIN)
        assert resp.json()["data"]["status"] == "PAID"

    def test_lp_officer_cannot_scan_lines_unauthorized(self, api):
        """PRD §2.1: "If the headers are well-formed but the role is not
        permitted to call the endpoint, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."; PRD §4: "POST |
        `/scan-sessions/{id}/lines` | Scan an item into the session | Member".

        Design: Corner/rbac/lp_officer_cannot_scan_lines_unauthorized
        """
        from test_helpers import LPO

        club, member = setup_club_member()
        item = create_item(club["id"], sku="MILK", unit_price_cents=500)
        session = create_session(club, member)

        resp = api.scan_line(
            session["id"], {"catalog_item_id": item["id"], "quantity": 1}, LPO,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_platform_admin_cannot_stage_curbside_unauthorized(self, api):
        """PRD §2.1: "If the headers are well-formed but the role is not
        permitted to call the endpoint, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."; PRD §4: "POST |
        `/curbside-orders/{id}/stage` | Stage a placed order into a slot and
        window | Associate".

        Design: Corner/rbac/platform_admin_cannot_stage_curbside_unauthorized
        """
        club = create_club()
        member = create_member(club["id"], tier="CLUB", birth_year=1990)
        order = create_curbside_order(club, member, item_count=2)

        resp = api.stage_curbside_order(
            order["id"],
            {
                "staging_slot_label": "S1",
                "window_start_iso": "2026-09-01T14:00:00Z",
                "window_end_iso": "2026-09-01T15:00:00Z",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOcc:
    def test_occ_stale_version_on_club_patch_returns_412(self, api):
        """PRD §2.7: "updating a club's configuration requires the request to
        carry `expected_club_version`, a non-optional field holding the
        version of the `Club` the caller last observed; if it no longer
        matches the club's current `version` — because another `ClubManager`
        has saved a newer configuration in the meantime — the update is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_club_patch_returns_412
        """
        club = create_club(name="Club OCC1")
        stale_version = club["version"]

        resp = api.update_club(
            club["id"],
            {"expected_club_version": stale_version, "lp_unscanned_threshold": 3},
            MANAGER,
        )
        validate_success(resp)

        resp = api.update_club(
            club["id"],
            {"expected_club_version": stale_version, "scan_go_enabled": False},
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        resp = api.get_club(club["id"], ADMIN)
        assert resp.json()["data"]["scan_go_enabled"] is True

    def test_occ_stale_version_on_curbside_reschedule_returns_412(self, api):
        """PRD §2.7: "rescheduling a curbside order requires the request to
        carry `expected_curbside_order_version`, likewise non-optional,
        matched against the `CurbsideOrder`'s current `version`; a stale
        value is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_curbside_reschedule_returns_412
        """
        club = create_club(name="Club OCC2")
        member = create_member(club["id"], tier="CLUB", birth_year=1990)
        order = create_curbside_order(club, member, item_count=2)
        stale_version = order["version"]
        staged = stage_order(
            order["id"], "S1", "2026-09-01T14:00:00Z", "2026-09-01T15:00:00Z",
        )

        resp = api.reschedule_curbside_order(
            order["id"],
            {
                "staging_slot_label": "S2",
                "window_start_iso": "2026-09-01T16:00:00Z",
                "window_end_iso": "2026-09-01T17:00:00Z",
                "expected_curbside_order_version": stale_version,
            },
            member_headers(member),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        resp = api.reschedule_curbside_order(
            order["id"],
            {
                "staging_slot_label": "S2",
                "window_start_iso": "2026-09-01T16:00:00Z",
                "window_end_iso": "2026-09-01T17:00:00Z",
                "expected_curbside_order_version": staged["version"],
            },
            member_headers(member),
        )
        rescheduled = validate_success(resp)
        assert rescheduled["status"] == "STAGING"
        assert rescheduled["staging_slot_label"] == "S2"


class TestImmediateConsistency:
    def test_pay_effects_visible_immediately_on_reread(self, api):
        """PRD §3.4: "mints the session's `receipt_code`, stamps `paid_at`
        with the logical clock, adds `final_total_cents` to the member's
        `lifetime_charged_cents`, and — for `PLUS` members — accrues pending
        cash rewards (§3.8)."

        Design: Corner/consistency_model/pay_effects_visible_immediately_on_reread
        """
        club, item, member, session, pay_data = setup_paid_session(
            price_cents=800, quantity=2,
            member_overrides={"tier": "PLUS", "birth_year": 1990},
        )
        resp = api.get_scan_session(session["id"], member_headers(member))
        reread = validate_success(resp)
        assert reread["status"] == "PAID"
        assert reread["final_total_cents"] == 1600
        assert reread["receipt_code"] is not None

        member_now = get_member(member["id"])
        assert member_now["lifetime_charged_cents"] == 1600
        # floor(1600 * 2 / 100) = 32.
        assert member_now["cash_rewards_pending_cents"] == 32
