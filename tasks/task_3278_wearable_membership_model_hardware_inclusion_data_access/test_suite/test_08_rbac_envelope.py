"""Access control: role denial, ownership denial, anonymous restrictions, pagination."""
from test_helpers import (
    ApiErrorId,
    create_member,
    create_member_with_term,
    make_coach_headers,
    make_member_headers,
    provision_device_for,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRoleDenial:
    def test_member_cannot_access_dashboard(self, api, anonymous_headers):
        """PRD: "If the role is declared but not authorized for the target
        endpoint, the request is rejected with ERR_FORBIDDEN_ROLE."

        Design: Corner/rbac/member_cannot_access_dashboard_or_decide
        """
        member = create_member()
        coach = make_coach_headers("coach-6")
        team = validate_success(
            api.create_team(
                {"name": "TR1", "team_type": "SPORTS", "coach_user_id": "coach-6"},
                coach,
            ),
            expected_status=201,
        )
        resp = api.get_team_dashboard(team["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_anonymous_only_registers(self, api, anonymous_headers):
        """PRD: "**Anonymous** — an unauthenticated caller permitted only to register a
        new member."
        PRD: "If the role is declared but not authorized for the target endpoint,
        the request is rejected with ERR_FORBIDDEN_ROLE."

        Design: Corner/rbac/anonymous_only_registers
        """
        resp = api.list_devices(anonymous_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_anonymous_list_devices_denied_before_existence(self, api, anonymous_headers):
        """PRD: "If the role is declared but not authorized for the target
        endpoint, the request is rejected with ERR_FORBIDDEN_ROLE."

        Design: Corner/rbac/anonymous_only_registers
        """
        member = create_member()
        resp = api.get_member(member["id"], anonymous_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestOwnership:
    def test_coach_ownership_and_member_ownership(self, api, anonymous_headers):
        """PRD: "When X-User-Role is Coach, X-User-ID is an opaque operator
        identifier; it is recorded as coach_user_id on the Team the coach creates,
        and team-ownership checks compare the team's stored coach_user_id to
        X-User-ID, with a mismatch rejected as ERR_NOT_RESOURCE_OWNER."
        PRD: "When X-User-Role is Member, X-User-ID is the id of the acting
        Member; ownership checks on any member-scoped resource compare the
        resource's member_id foreign key to X-User-ID, and a mismatch is rejected
        with ERR_NOT_RESOURCE_OWNER."

        Design: Corner/rbac/coach_ownership_and_member_ownership
        """
        member_a = create_member()
        member_b = create_member()
        coach = make_coach_headers("coach-6")
        team = validate_success(
            api.create_team(
                {"name": "TR2", "team_type": "SPORTS", "coach_user_id": "coach-6"},
                coach,
            ),
            expected_status=201,
        )
        # A different coach does not own the team.
        resp = api.add_team_membership(
            team["id"], {"member_id": member_a["id"]}, make_coach_headers("coach-other")
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
        # Member B acting on member A's merch orders.
        resp = api.place_merch_order(
            member_a["id"],
            {
                "lines": [
                    {"sku": "B1", "category": "BAND_ACCESSORY", "unit_price_cents": 100, "qty": 1},
                ]
            },
            make_member_headers(member_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    def test_foreign_member_cannot_read_member_terms(self, api, anonymous_headers):
        """PRD: "ownership checks on any member-scoped resource compare the
        resource's member_id foreign key to X-User-ID, and a mismatch is rejected
        with ERR_NOT_RESOURCE_OWNER."

        Design: Corner/rbac/coach_ownership_and_member_ownership
        """
        member_a = create_member()
        member_b = create_member()
        resp = api.list_member_terms(member_a["id"], make_member_headers(member_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)


class TestPagination:
    def test_list_pagination_envelope(self, api, anonymous_headers, support_headers):
        """PRD: "List endpoints accept limit and offset query parameters. limit
        defaults to 10, with a minimum of 1 and a maximum of 100; offset defaults
        to 0. List responses are sorted by created_at ascending unless a workflow
        states a more specific ordering, and the meta object of a list response
        carries limit, offset, total_count, and has_more."

        Design: Corner/endpoints/list_pagination_envelope
        """
        member, term = create_member_with_term()
        for serial in ("SN-E1", "SN-E2", "SN-E3"):
            provision_device_for(member["id"], term["id"], serial_number=serial)
        data, meta = validate_paginated(
            api.list_devices(
                support_headers,
                params={"member_id": member["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_list_pagination_second_page(self, api, anonymous_headers, support_headers):
        """PRD: "List endpoints accept limit and offset query parameters. limit
        defaults to 10, with a minimum of 1 and a maximum of 100; offset defaults
        to 0."
        PRD: "the meta object of a list response carries limit, offset,
        total_count, and has_more."

        Design: Corner/endpoints/list_pagination_envelope
        """
        member, term = create_member_with_term()
        for serial in ("SN-E1", "SN-E2", "SN-E3"):
            provision_device_for(member["id"], term["id"], serial_number=serial)
        data, meta = validate_paginated(
            api.list_devices(
                support_headers,
                params={"member_id": member["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
