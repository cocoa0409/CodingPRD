"""Member/plan/showtime/registration claims (Corner/entities)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_member,
    create_member_payload,
    create_plan_payload,
    create_published_plan,
    create_active_member,
    create_theater_with_auditorium,
    create_theater_payload,
    create_showtime_payload,
    enroll_member,
    get_success_data,
    make_member_headers,
    record_concession_purchase,
    set_clock,
    setup_member_with_subscription,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
SERVICES = TEST_USERS["member_services_headers"]


class TestMemberRegistration:

    def test_member_register_success_system_fields_and_defaults(self, api):
        """PRD §3.1: "The account is created in `REGISTERED` status with
        `loyalty_points_balance` starting at zero."
        PRD §2.4: "The `id` is a server-minted UUID string with no type prefix."

        Design: Corner/entities/member_register_success_system_fields_and_defaults
        """
        resp = api.create_member(
            {"email": "fresh@x.com", "full_name": "Fresh Member"}, SERVICES)
        data = validate_success(resp, expected_status=201)
        assert_member(data)
        assert data["status"] == "REGISTERED", f"expected REGISTERED, got {data['status']}"
        assert data["loyalty_points_balance"] == 0
        assert data["no_show_strikes_active"] == 0

    def test_member_register_missing_email_returns_invalid_request(self, api):
        """PRD §4: "Request payloads must contain only the fields declared for
        the endpoint; unknown keys, missing required fields, type mismatches,
        enum violations, and out-of-range scalars are rejected with
        `ERR_INVALID_REQUEST`."
        PRD §3.1: "A `MemberServices` operator registers a new member by
        supplying an `email` and a `full_name`."

        Design: Corner/entities/member_register_missing_email_returns_invalid_request
        """
        resp = api.create_member({"full_name": "No Email"}, SERVICES)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_member_get_nonexistent_returns_not_found(self, api):
        """PRD §2.8: "A request referencing a non-existent parent is rejected
        with `ERR_NOT_FOUND` (HTTP 404) before any child identifier is examined,
        and each subsequent path identifier is checked in turn."

        Design: Corner/entities/member_get_nonexistent_returns_not_found
        """
        resp = api.get_member(NON_EXISTENT_UUID, SERVICES)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_members_list_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` object of every list response carries the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/members_list_pagination_envelope
        """
        for i in range(3):
            get_success_data(api.create_member(
                {"email": f"p{i}@x.com", "full_name": f"P {i}"}, SERVICES))
        resp = api.list_members(SERVICES, params={"limit": 2, "offset": 0})
        rows, meta = validate_paginated(resp)
        assert len(rows) == 2, f"expected 2 rows, got {len(rows)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_loyalty_ledger_immutable_no_update_endpoint(self, api):
        """PRD §2.4: "A `LoyaltyLedgerEntry` and a `SettlementLine` are
        append-only records: each carries `id` and `created_at` only, and both
        `updated_at` and `version` are absent from them entirely."

        Design: Corner/entities/loyalty_ledger_immutable_no_update_endpoint
        """
        set_clock()
        plan = create_published_plan(
            tier="PLUS", loyalty_points_multiplier_pct=125,
            concession_discount_pct=10, premium_format_allowed=True)
        theater, _auditorium = create_theater_with_auditorium()
        member = create_active_member(email="im@x.com", full_name="IM")
        enroll_member(member["id"], plan["id"])
        record_concession_purchase(member, theater["id"], 1000)
        resp = api.list_loyalty_ledger(SERVICES, params={"member_id": member["id"]})
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, f"expected 1 entry, got {meta['total_count']}"
        entry = rows[0]
        assert entry["kind"] == "EARN_CONCESSION"
        assert "updated_at" not in entry, "append-only entry must not carry updated_at"
        assert "version" not in entry, "append-only entry must not carry version"

    def test_plan_create_enum_violation_returns_invalid_request(self, api):
        """PRD §4: "Request payloads must contain only the fields declared for
        the endpoint; unknown keys, missing required fields, type mismatches,
        enum violations, and out-of-range scalars are rejected with
        `ERR_INVALID_REQUEST`."
        PRD §3.2: "a `tier` of `BASIC`, `PLUS`, or `PREMIER`"

        Design: Corner/entities/plan_create_enum_violation_returns_invalid_request
        """
        payload = create_plan_payload(code="BAD", tier="GOLD")
        resp = api.create_plan(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_showtime_parent_relationship_wrong_auditorium(self, api):
        """PRD §2.8: "Body-supplied foreign keys are validated for existence
        under the same `ERR_NOT_FOUND` code before business rules run."

        Design: Corner/entities/showtime_parent_relationship_wrong_auditorium
        """
        resp = api.create_showtime(
            create_showtime_payload(NON_EXISTENT_UUID, starts_at="2026-09-05T19:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_subscription_computed_fields_input_ignored(self, api):
        """PRD §4: "Request payloads must contain only the fields declared for
        the endpoint; unknown keys, missing required fields, type mismatches,
        enum violations, and out-of-range scalars are rejected with
        `ERR_INVALID_REQUEST`."
        PRD §3.3: "A member enrolls by supplying a `plan_id`"

        Design: Corner/entities/subscription_computed_fields_input_ignored
        """
        set_clock()
        plan = create_published_plan()
        member = create_active_member(email="cf@x.com", full_name="CF")
        resp = api.enroll_subscription(
            member["id"], {"plan_id": plan["id"], "current_cycle_index": 99}, SERVICES)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
