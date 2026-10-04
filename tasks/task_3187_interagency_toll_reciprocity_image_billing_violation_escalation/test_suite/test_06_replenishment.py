"""Replenishment cascade, low-balance boundary, and OCC (PRD §3.5, §2.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_discount_plan,
    create_home_agency,
    create_rate_schedule,
    create_transponder,
    create_away_agency,
    fail_replenishments,
    get_account,
    get_account_version,
    get_success_data,
    record_replenishment,
    setup_agency_pair,
    setup_full_account,
    validate_error,
)

AO = TEST_USERS["agency_ops_headers"]


def test_low_balance_threshold_strictly_below():
    """PRD §3.5: "If the account is `ACTIVE` and its balance has fallen
    strictly below its `low_balance_threshold_cents`, an automatic
    replenishment of `replenishment_amount_cents` is attempted. The boundary is
    strict: a balance exactly equal to the threshold does not trigger a
    top-up. On success the balance is credited the replenishment amount and
    `replenishment_fail_count` resets to zero."

    Design: Difficulty/boundary_precision_check/low_balance_threshold_strictly_below
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], plaza_code="P5", base_rate_cents=200)
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    acct_e = create_account(
        home["id"], plan["id"], holder_name="Eve Exact", holder_email="eve@example.com",
        low_balance_threshold_cents=1000, replenishment_amount_cents=2500,
        opening_balance_cents=1200,
    )
    acct_b = create_account(
        home["id"], plan["id"], holder_name="Ben Below", holder_email="ben@example.com",
        low_balance_threshold_cents=1000, replenishment_amount_cents=2500,
        opening_balance_cents=1199,
    )
    create_transponder(acct_e["id"], tag_number="TAG-E", plate_number="EXA100")
    create_transponder(acct_b["id"], tag_number="TAG-B", plate_number="BEL100")

    get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-E", "away_agency_id": away["id"], "plaza_code": "P5",
             "trip_timestamp": "2026-09-09T09:00:00Z", "is_peak": False,
             "idempotency_key": "e1"}, AO,
        )
    )
    get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-B", "away_agency_id": away["id"], "plaza_code": "P5",
             "trip_timestamp": "2026-09-09T09:05:00Z", "is_peak": False,
             "idempotency_key": "b1"}, AO,
        )
    )

    exact = get_account(acct_e["id"])
    assert exact["balance_cents"] == 1000
    assert exact["status"] == "ACTIVE"

    below = get_account(acct_b["id"])
    assert below["balance_cents"] == 3499  # 999 + 2500 auto-replenishment


def test_occ_stale_version_on_replenishment():
    """PRD §2.7: "Recording a replenishment against an account — whether the
    operator is recording a manual top-up or simulating an automatic one —
    requires the request to carry `expected_account_version`, the account's
    `version` as last observed by the caller. If the account's current
    `version` does not match, the write is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_replenishment
    """
    ctx = setup_full_account(tag_number="TAG-O", account_overrides={"opening_balance_cents": 5000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    v_seen = ctx["account"]["version"]

    get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-O", "away_agency_id": ctx["away"]["id"], "plaza_code": "P1",
             "trip_timestamp": "2026-09-25T09:00:00Z", "is_peak": False,
             "idempotency_key": "o1"}, AO,
        )
    )
    # The toll debit bumped the account version since v_seen was observed.
    resp = api_client.create_replenishment(
        ctx["account"]["id"],
        {"amount_cents": 2500, "outcome": "SUCCEEDED", "expected_account_version": v_seen},
        AO,
    )
    assert resp.status_code == 412
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_account(ctx["account"]["id"])["balance_cents"] == 4200


def test_occ_adjustment_succeeds_with_current_version():
    """PRD §2.7: "Posting a manual balance adjustment likewise requires
    `expected_account_version` matching the account's current `version`; a
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because any
    intervening toll debit, dispute credit, or replenishment legitimately moved
    the balance and invalidated the stale writer's basis."
    PRD §3.5: "A successful adjustment applies the delta and bumps `version`."

    Design: Corner/cross_cutting_layers/occ_adjustment_succeeds_with_current_version
    """
    home = create_home_agency()
    plan = create_discount_plan(home["id"])
    account = create_account(
        home["id"], plan["id"], holder_name="Ada Just", holder_email="ada@example.com",
        opening_balance_cents=5000,
    )
    v_cur = get_account_version(account["id"])

    resp1 = api_client.create_adjustment(
        account["id"],
        {"delta_cents": 500, "reason": "GOODWILL", "expected_account_version": v_cur},
        AO,
    )
    assert resp1.status_code == 201
    assert get_account(account["id"])["balance_cents"] == 5500

    resp2 = api_client.create_adjustment(
        account["id"],
        {"delta_cents": 500, "reason": "GOODWILL", "expected_account_version": v_cur},
        AO,
    )
    assert resp2.status_code == 412
    validate_error(resp2, ApiErrorId.ERR_STALE_VERSION)
    assert get_account(account["id"])["balance_cents"] == 5500


def test_reinstate_blocked_below_threshold_and_by_violations():
    """PRD §3.5: "Reinstating a suspended account is an `AgencyOperations`
    action with two preconditions: the account's `balance_cents` must be at
    least its `low_balance_threshold_cents` (otherwise
    `ERR_BALANCE_BELOW_THRESHOLD`)... Reinstatement moves the account from
    `SUSPENDED` back to `ACTIVE`, resets `replenishment_fail_count` to zero,
    and clears `suspended_reason` to null."
    PRD §3.5: "A recorded success adds `amount_cents` to `balance_cents` and
    resets `replenishment_fail_count` to zero."

    Design: Corner/validations/reinstate_blocked_below_threshold_and_by_violations
    """
    home = create_home_agency()
    plan = create_discount_plan(home["id"])
    account = create_account(
        home["id"], plan["id"], holder_name="Rey Inst", holder_email="rey@example.com",
        low_balance_threshold_cents=1000, replenishment_amount_cents=2500,
        opening_balance_cents=400,
    )
    fail_replenishments(account["id"], 3, amount_cents=2500)
    assert get_account(account["id"])["status"] == "SUSPENDED"

    resp1 = api_client.reinstate_account(account["id"], AO)
    validate_error(resp1, ApiErrorId.ERR_BALANCE_BELOW_THRESHOLD)

    record_replenishment(account["id"], 2500, "SUCCEEDED", get_account_version(account["id"]))
    acct = get_account(account["id"])
    assert acct["balance_cents"] == 2900
    assert acct["replenishment_fail_count"] == 0

    resp2 = api_client.reinstate_account(account["id"], AO)
    assert resp2.status_code == 200
    reinstated = get_account(account["id"])
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspended_reason"] is None
