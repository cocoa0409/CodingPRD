"""Account creation, retrieval, defaults, and validation (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_discount_plan,
    create_home_agency,
    get_account,
    validate_error,
    validate_paginated,
)

AO = TEST_USERS["agency_ops_headers"]
VO = TEST_USERS["violations_officer_headers"]


def test_account_get_round_trips_computed_and_input_fields():
    """PRD §3.2: "Optional `low_balance_threshold_cents` (default 1000) and
    `replenishment_amount_cents` (default 2500) tune the account's
    auto-replenishment behavior, and an optional `opening_balance_cents` seeds
    `balance_cents` (default zero). New accounts start `ACTIVE` with
    `replenishment_fail_count`, `discount_used_today_cents`, and
    `trips_this_month` all at zero, and `suspended_reason` null."

    Design: Corner/entities/account_get_round_trips_computed_and_input_fields
    """
    home = create_home_agency()
    plan = create_discount_plan(home["id"])
    account = create_account(
        home["id"],
        plan["id"],
        holder_name="Rita Round",
        holder_email="rita@example.com",
        low_balance_threshold_cents=1500,
        replenishment_amount_cents=3000,
        opening_balance_cents=7000,
    )
    resp = api_client.get_account(account["id"], VO)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["balance_cents"] == 7000
    assert data["replenishment_fail_count"] == 0
    assert data["low_balance_threshold_cents"] == 1500
    assert data["replenishment_amount_cents"] == 3000
    assert data["status"] == "ACTIVE"
    assert data["suspended_reason"] is None
    assert data["discount_used_today_cents"] == 0
    assert data["trips_this_month"] == 0


def test_account_create_missing_holder_email_returns_invalid_request():
    """PRD §3.2: "Opening an account requires the `home_agency_id` of the
    issuing agency, the holder's `holder_name` and `holder_email`, and the
    `discount_plan_id` of the plan the holder enrolls in."

    Design: Corner/entities/account_create_missing_holder_email_returns_invalid_request
    """
    home = create_home_agency()
    plan = create_discount_plan(home["id"])
    resp = api_client.create_account(
        {"home_agency_id": home["id"], "holder_name": "No Email", "discount_plan_id": plan["id"]},
        AO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    list_resp = api_client.list_accounts(AO)
    rows, meta = validate_paginated(list_resp)
    assert len(rows) == 0


def test_account_defaults_applied_when_optional_fields_omitted():
    """PRD §3.2: "Optional `low_balance_threshold_cents` (default 1000) and
    `replenishment_amount_cents` (default 2500) tune the account's
    auto-replenishment behavior, and an optional `opening_balance_cents` seeds
    `balance_cents` (default zero)."

    Design: Corner/entities/account_defaults_applied_when_optional_fields_omitted
    """
    home = create_home_agency()
    plan = create_discount_plan(home["id"])
    account = create_account(
        home["id"],
        plan["id"],
        holder_name="Dee Fault",
        holder_email="dee@example.com",
    )
    assert account["low_balance_threshold_cents"] == 1000
    assert account["replenishment_amount_cents"] == 2500
    assert account["balance_cents"] == 0
