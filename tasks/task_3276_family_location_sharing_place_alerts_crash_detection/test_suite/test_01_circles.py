"""Circle creation, defaults, listing, and not-found behavior."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_circle_payload,
    get_success_data,
    make_owner_headers,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


class TestCircleCreation:
    def test_circle_create_returns_all_declared_fields_and_initializes_posture(self, api, system_headers):
        """PRD §3.1: "The server creates the circle with `subscription_status` set
        to `TRIALING` and `circle_posture` set to `OPEN`. It simultaneously creates
        the first `Member` row, assigns that member the `OWNER` role, records their
        consent as self-granted with `scope` `FULL`, and points the circle's
        `owner_member_id` at the new member. The circle's tier-derived budgets are
        initialized at this moment: `assistance_units_balance` starts at 0 for
        `FREE`, 2 for `PLUS`, or 4 for `PROTECT`; `identity_protection_credits`
        starts at 1 for `PROTECT` and 0 on every other tier;
        `history_retention_days` starts at 7 for `FREE`, 30 for `PLUS`, or 60 for
        `PROTECT`."

        Design: Corner/entities/circle_create_returns_all_declared_fields_and_initializes_posture
        """
        reset_clock()
        resp = api.create_circle(
            create_circle_payload(
                name="InitFam", subscription_tier="PROTECT", billing_anchor_day=15,
                owner_display_name="Ivy", owner_birthdate="1981-11-11T00:00:00Z",
                owner_email="ivy@example.com",
            ),
            TEST_USERS["owner_headers"],
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        circle = validate_success(resp, 201)
        assert circle["subscription_status"] == "TRIALING"
        assert circle["circle_posture"] == "OPEN"
        assert circle["version"] == 1
        assert circle["assistance_units_balance"] == 4
        assert circle["identity_protection_credits"] == 1
        assert circle["history_retention_days"] == 60
        owner_headers = make_owner_headers(circle["owner_member_id"])
        owner = get_success_data(
            api.get_member(circle["id"], circle["owner_member_id"], owner_headers)
        )
        assert owner["role"] == "OWNER"
        assert owner["consent_state"] == "GRANTED"

    def test_circle_create_plus_initializes_two_units_and_thirty_day_retention(self, api, system_headers):
        """PRD §3.1: "`assistance_units_balance` starts at 0 for `FREE`, 2 for
        `PLUS`, or 4 for `PROTECT`; `identity_protection_credits` starts at 1 for
        `PROTECT` and 0 on every other tier; `history_retention_days` starts at 7
        for `FREE`, 30 for `PLUS`, or 60 for `PROTECT`."

        Design: Corner/entities/circle_create_returns_all_declared_fields_and_initializes_posture
        """
        reset_clock()
        resp = api.create_circle(
            create_circle_payload(
                name="PlusFam", subscription_tier="PLUS", billing_anchor_day=5,
                owner_display_name="P", owner_email="p2@example.com",
            ),
            TEST_USERS["owner_headers"],
        )
        circle = validate_success(resp, 201)
        assert circle["assistance_units_balance"] == 2
        assert circle["identity_protection_credits"] == 0
        assert circle["history_retention_days"] == 30
        assert circle["subscription_status"] == "TRIALING"
        assert circle["circle_posture"] == "OPEN"

    def test_circle_create_returns_computed_fields_in_same_response(self, api, system_headers):
        """PRD §3.1: "`assistance_units_balance` starts at 0 for `FREE`, 2 for
        `PLUS`, or 4 for `PROTECT` ... `history_retention_days` starts at 7 for
        `FREE`, 30 for `PLUS`, or 60 for `PROTECT`."

        Design: Corner/consistency_model/changes_visible_immediately_in_same_response
        """
        reset_clock()
        resp = api.create_circle(
            create_circle_payload(
                name="ImmFam", subscription_tier="PLUS", billing_anchor_day=5,
                owner_display_name="Im", owner_email="im@example.com",
            ),
            TEST_USERS["owner_headers"],
        )
        circle = validate_success(resp, 201)
        assert circle["assistance_units_balance"] == 2
        assert circle["history_retention_days"] == 30
        assert circle["version"] == 1

    def test_circle_create_free_tier_immediate_response(self, api, system_headers):
        """PRD §3.1: "`assistance_units_balance` starts at 0 for `FREE`, 2 for
        `PLUS`, or 4 for `PROTECT`; `identity_protection_credits` starts at 1 for
        `PROTECT` and 0 on every other tier; `history_retention_days` starts at 7
        for `FREE`, 30 for `PLUS`, or 60 for `PROTECT`."

        Design: Corner/consistency_model/changes_visible_immediately_in_same_response
        """
        reset_clock()
        resp = api.create_circle(
            create_circle_payload(
                name="ImmFree", subscription_tier="FREE", billing_anchor_day=5,
                owner_display_name="ImF", owner_email="imf@example.com",
            ),
            TEST_USERS["owner_headers"],
        )
        circle = validate_success(resp, 201)
        assert circle["assistance_units_balance"] == 0
        assert circle["identity_protection_credits"] == 0
        assert circle["history_retention_days"] == 7
        assert circle["version"] == 1


class TestCircleReadAndList:
    def test_circle_not_found_returns_404(self, api, system_headers):
        """PRD §2.5: "The first identifier that fails to resolve — or that
        resolves but belongs to a different parent than the path implies —
        produces `ERR_NOT_FOUND` (HTTP 404), and no further identifiers are
        consulted."

        Design: Corner/entities/circle_not_found_returns_404
        """
        reset_clock()
        resp = api.get_circle(NON_EXISTENT_UUID, system_headers)
        validate_error(resp, "ERR_NOT_FOUND")

    def test_circle_list_paginates_with_total_count_and_has_more(self, api, system_headers):
        """PRD §2.3: "The `meta` object of every list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/circle_list_paginates_with_total_count_and_has_more
        """
        reset_clock()
        for name, tier, day in (("First", "FREE", 1), ("Second", "FREE", 2), ("Third", "PLUS", 3)):
            api.create_circle(
                create_circle_payload(
                    name=name, subscription_tier=tier, billing_anchor_day=day,
                    owner_display_name=name, owner_email=f"{name.lower()}@example.com",
                ),
                TEST_USERS["owner_headers"],
            )
        data0, meta0 = validate_paginated(
            api.list_circles(system_headers, params={"limit": 2, "offset": 0})
        )
        assert len(data0) == 2
        assert meta0["total_count"] == 3
        assert meta0["has_more"] is True
        data1, meta1 = validate_paginated(
            api.list_circles(system_headers, params={"limit": 2, "offset": 2})
        )
        assert len(data1) == 1
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is False
