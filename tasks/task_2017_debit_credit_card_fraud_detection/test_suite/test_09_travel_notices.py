"""Travel notices: window shape, half-open overlap, account-state gating."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_card,
    set_clock,
)

MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_travel_window_inverted_returns_invalid_window(api):
    """PRD §3.10: "`end_date` must fall after `start_date`, else
    `ERR_INVALID_WINDOW`." PRD §5: ERR_INVALID_WINDOW -> 422.

    Design: Corner/validations/travel_window_inverted_returns_invalid_window
    """
    acct = create_account("ACCT-V3", cardholder_name="Val Three")
    card = create_card(acct["id"], "PT-V3")
    resp = api.create_travel_notice(
        {
            "card_id": card["id"],
            "region_country": "MX",
            "start_date": "2026-08-10",
            "end_date": "2026-08-05",
        },
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, expected_status=422)


class TestTravelNoticeRequiresActiveAccount:
    def test_create_on_suspended_account_rejected(self, api):
        """PRD §3.1: "while an account is `SUSPENDED`, attempts to create new travel
        notices or new cards for it are rejected with `ERR_ACCOUNT_NOT_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/travel_notice_requires_active_account
        """
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-CE1", cardholder_name="Cross One")
        card = create_card(acct["id"], "PT-CE1")
        get_success_suspend = api.suspend_account(acct["id"], MANAGER)
        assert get_success_suspend.status_code == 200
        resp = api.create_travel_notice(
            {
                "card_id": card["id"],
                "region_country": "MX",
                "start_date": "2026-08-10",
                "end_date": "2026-08-20",
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, expected_status=409)

    def test_create_succeeds_after_reinstate(self, api):
        """PRD §3.1: "Suspension moves an account from `ACTIVE` to `SUSPENDED` and
        reinstatement returns it"; "while an account is `SUSPENDED`, attempts to
        create new travel notices or new cards for it are rejected with
        `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/travel_notice_requires_active_account
        """
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-CE1", cardholder_name="Cross One")
        card = create_card(acct["id"], "PT-CE1")
        api.suspend_account(acct["id"], MANAGER)
        api.reinstate_account(acct["id"], MANAGER)
        created = validate_success(
            api.create_travel_notice(
                {
                    "card_id": card["id"],
                    "region_country": "MX",
                    "start_date": "2026-08-10",
                    "end_date": "2026-08-20",
                },
                ANALYST,
            ),
            expected_status=201,
        )
        assert created["notice_status"] == "ACTIVE"


def test_card_create_on_suspended_account_rejected(api):
    """PRD §3.1: "while an account is `SUSPENDED`, attempts to create new travel
    notices or new cards for it are rejected with `ERR_ACCOUNT_NOT_ACTIVE`
    (HTTP 409)."; "Cards are issued by a `FraudOpsManager` against an `ACTIVE`
    account".

    Design: Corner/endpoints/card_create_on_suspended_account_rejected
    """
    acct = create_account("ACCT-EP5", cardholder_name="Ep Five")
    api.suspend_account(acct["id"], MANAGER)
    payload = {
        "account_id": acct["id"],
        "pan_token": "PT-EP5",
        "product_type": "CREDIT",
        "network": "VISA",
    }
    resp = api.create_card(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, expected_status=409)
    api.reinstate_account(acct["id"], MANAGER)
    created = validate_success(api.create_card(payload, MANAGER), expected_status=201)
    assert created["card_status"] == "ACTIVE"


class TestTravelNoticeHalfOpenOverlap:
    def _setup(self, api):
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-TO1", cardholder_name="Tee One")
        card = create_card(acct["id"], "PT-TO1")
        return acct, card

    def test_touching_boundaries_do_not_overlap(self, api):
        """PRD §3.10: "a new `ACTIVE` notice that overlaps an existing `ACTIVE`
        notice for the same card and `region_country` under half-open interval
        semantics (touching boundaries do not overlap) is rejected with
        `ERR_TRAVEL_NOTICE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/travel_notice_half_open_overlap
        """
        _acct, card = self._setup(api)
        n1 = validate_success(
            api.create_travel_notice(
                {"card_id": card["id"], "region_country": "MX", "start_date": "2026-08-10", "end_date": "2026-08-20"},
                ANALYST,
            ),
            expected_status=201,
        )
        n2 = validate_success(
            api.create_travel_notice(
                {"card_id": card["id"], "region_country": "MX", "start_date": "2026-08-05", "end_date": "2026-08-10"},
                ANALYST,
            ),
            expected_status=201,
        )
        assert n1["notice_status"] == "ACTIVE"
        assert n2["notice_status"] == "ACTIVE"

    def test_interior_overlap_rejected_and_other_region_allowed(self, api):
        """PRD §3.10: "Overlap is policed per card and region: a new `ACTIVE` notice
        that overlaps an existing `ACTIVE` notice for the same card and
        `region_country` under half-open interval semantics (touching boundaries do
        not overlap) is rejected with `ERR_TRAVEL_NOTICE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/travel_notice_half_open_overlap
        """
        _acct, card = self._setup(api)
        n1 = validate_success(
            api.create_travel_notice(
                {"card_id": card["id"], "region_country": "MX", "start_date": "2026-08-10", "end_date": "2026-08-20"},
                ANALYST,
            ),
            expected_status=201,
        )
        n2 = validate_success(
            api.create_travel_notice(
                {"card_id": card["id"], "region_country": "MX", "start_date": "2026-08-05", "end_date": "2026-08-10"},
                ANALYST,
            ),
            expected_status=201,
        )
        # One interior day shared with N1
        resp = api.create_travel_notice(
            {"card_id": card["id"], "region_country": "MX", "start_date": "2026-08-19", "end_date": "2026-08-21"},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_TRAVEL_NOTICE_OVERLAP, expected_status=409)
        # Same dates but different region: no collision
        n4 = validate_success(
            api.create_travel_notice(
                {"card_id": card["id"], "region_country": "JP", "start_date": "2026-08-15", "end_date": "2026-08-18"},
                ANALYST,
            ),
            expected_status=201,
        )
        assert n4["notice_status"] == "ACTIVE"
        notices, meta = validate_paginated(
            api.list_card_travel_notices(card["id"], MANAGER, params={"notice_status": "ACTIVE"})
        )
        assert meta["total_count"] == 3
        ids = {n["id"] for n in notices}
        assert ids == {n1["id"], n2["id"], n4["id"]}
