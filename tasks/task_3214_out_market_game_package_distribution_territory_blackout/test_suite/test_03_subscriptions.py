"""Subscriptions: parallel state dimensions, payment activation fan-out,
cancel semantics, and withdrawal snapshot retention."""
from test_helpers import (
    ApiErrorId,
    create_game,
    create_grant,
    create_market,
    create_offer,
    create_season,
    create_slate,
    make_subscriber_headers,
    register_account,
    set_clock,
    setup_account_with_pending_sub,
    setup_week4_game_account_sub,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_suspend_restore_and_cancel_move_dimensions_independently(
    api, platform_admin_headers
):
    """PRD §3.5: "The subscription carries two parallel state dimensions that
    evolve independently. The lifecycle `status` runs `PENDING_PAYMENT` →
    `ACTIVE` → (`CANCELLED` | `EXPIRED`); the access posture
    `entitlement_state` runs among `ENABLED`, `SUSPENDED`, and `REVOKED`."

    Design: Difficulty/non_linear_state_machine/subscription_parallel_status_and_entitlement_dimensions
    """
    ctx = setup_week4_game_account_sub(email="par@x.com", billing_zip="10001")
    sub = ctx["subscription"]

    suspended = validate_success(
        api.suspend_entitlement(sub["id"], platform_admin_headers)
    )
    assert suspended["status"] == "ACTIVE"
    assert suspended["entitlement_state"] == "SUSPENDED"

    restored = validate_success(
        api.restore_entitlement(sub["id"], platform_admin_headers)
    )
    assert restored["status"] == "ACTIVE"
    assert restored["entitlement_state"] == "ENABLED"
    assert restored["paid_amount_cents"] == 16667

    cancelled = validate_success(
        api.cancel_subscription(sub["id"], make_subscriber_headers(ctx["account"]["id"]))
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["entitlement_state"] == "REVOKED"
    assert cancelled["cancelled_at"] is not None


def test_entitlement_suspend_restore_leaves_payment_and_lifecycle_untouched(
    api, platform_admin_headers
):
    """PRD §3.5: "Meanwhile a `PlatformAdmin` may suspend the entitlement
    dimension alone, `ENABLED` → `SUSPENDED`, leaving lifecycle `status`
    untouched: while suspended, territory checks for the subscription return
    `NO_ENTITLEMENT`, but the entitlement rows themselves are unchanged."

    Design: Difficulty/non_linear_state_machine/subscription_parallel_status_and_entitlement_dimensions
    """
    ctx = setup_week4_game_account_sub(email="par2@x.com", billing_zip="10001")
    sub = ctx["subscription"]

    validate_success(api.suspend_entitlement(sub["id"], platform_admin_headers))
    check = validate_success(
        api.create_territory_check(
            ctx["account"]["id"], sub["id"], ctx["games"][0]["id"], "75001",
            make_subscriber_headers(ctx["account"]["id"]),
        ),
        expected_status=201,
    )
    assert check["verdict"] == "NO_ENTITLEMENT"

    restored = validate_success(
        api.restore_entitlement(sub["id"], platform_admin_headers)
    )
    assert restored["status"] == "ACTIVE"
    assert restored["entitlement_state"] == "ENABLED"
    rows, meta = validate_paginated(
        api.list_subscription_payments(sub["id"], platform_admin_headers)
    )
    assert meta["total_count"] == 1
    assert rows[0]["kind"] == "CHARGE"


def test_activation_fans_out_granted_entitlements_for_package_games(
    api, platform_admin_headers
):
    """PRD §3.5: "When the simulated outcome is success, the subscription
    moves `PENDING_PAYMENT` → `ACTIVE`: `paid_amount_cents` increases by
    `price_charged_cents`, a `Payment` row of `kind` `CHARGE` is appended, and
    the entitlement fan-out fires — a `GameEntitlement` row in `status`
    `GRANTED` is created for every package-eligible game of every week slate
    in the season, skipping games that are national-selected at creation
    time"

    Design: Corner/state_machines/subscription_activation_fans_out_granted_entitlements
    """
    ctx = setup_account_with_pending_sub(email="act@x.com")
    # Build week-4 slate with two games and a week-5 slate with one game,
    # all before activation so the fan-out sees three package games.
    season = ctx["season"]
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    create_slate(season["id"], week_index=4)
    create_slate(season["id"], week_index=5)
    create_game(season["id"], week_index=4, away_team_code="KC",
                home_team_code="DAL", kickoff_at="2026-08-30T17:00:00Z",
                home_market_code="DAL")
    create_game(season["id"], week_index=4, away_team_code="BUF",
                home_team_code="DAL", kickoff_at="2026-08-30T20:00:00Z",
                home_market_code="DAL")
    create_game(season["id"], week_index=5, away_team_code="LAC",
                home_team_code="DAL", kickoff_at="2026-09-06T17:00:00Z",
                home_market_code="DAL")

    sub = validate_success(
        api.simulate_payment(ctx["subscription"]["id"], "SUCCEEDED",
                             platform_admin_headers)
    )
    assert sub["status"] == "ACTIVE"
    assert sub["entitlement_state"] == "ENABLED"
    assert sub["paid_amount_cents"] == 16667

    ledger, meta = validate_paginated(
        api.list_subscription_payments(sub["id"], platform_admin_headers)
    )
    assert meta["total_count"] == 1
    assert ledger[0]["kind"] == "CHARGE"
    assert ledger[0]["amount_cents"] == 16667

    ents, ent_meta = validate_paginated(
        api.list_game_entitlements(
            platform_admin_headers,
            params={"subscription_id": sub["id"], "status": "GRANTED"},
        )
    )
    assert ent_meta["total_count"] == 3


def test_activation_skips_games_national_selected_at_creation(
    api, platform_admin_headers, league_ops_headers
):
    """PRD §3.5: "When the simulated outcome is success, the subscription
    moves `PENDING_PAYMENT` → `ACTIVE`: `paid_amount_cents` increases by
    `price_charged_cents`, a `Payment` row of `kind` `CHARGE` is appended, and
    the entitlement fan-out fires — a `GameEntitlement` row in `status`
    `GRANTED` is created for every package-eligible game of every week slate
    in the season, skipping games that are national-selected at creation
    time"

    Design: Corner/state_machines/subscription_activation_fans_out_granted_entitlements
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    slate = create_slate(season["id"], week_index=4)
    game_a = create_game(season["id"], away_team_code="KC",
                         home_team_code="DAL",
                         kickoff_at="2026-08-30T17:00:00Z",
                         home_market_code="DAL")
    game_b = create_game(season["id"], away_team_code="BUF",
                         home_team_code="DAL",
                         kickoff_at="2026-08-30T20:00:00Z",
                         home_market_code="DAL")
    slate_now = validate_success(api.get_week_slate(slate["id"], league_ops_headers))
    validate_success(
        api.slate_selection(slate["id"], game_a["id"], "ADD",
                            slate_now["version"], league_ops_headers)
    )
    offer = create_offer(season["id"])
    account = register_account(email="skip@x.com", billing_zip="10001")
    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    validate_success(api.simulate_payment(sub["id"], "SUCCEEDED",
                                          platform_admin_headers))
    ents, meta = validate_paginated(
        api.list_game_entitlements(
            platform_admin_headers,
            params={"subscription_id": sub["id"], "status": "GRANTED"},
        )
    )
    granted_game_ids = [row["game_id"] for row in ents]
    assert meta["total_count"] == 1
    assert granted_game_ids == [game_b["id"]]


def test_failed_initial_payment_cancels_without_ledger_row(
    api, platform_admin_headers
):
    """PRD §3.5: "When the simulated outcome is failure, the subscription
    moves `PENDING_PAYMENT` → `CANCELLED`: `entitlement_state` becomes
    `REVOKED`, `cancelled_at` is stamped, and — notably — no `Payment` row is
    appended at all."

    Design: Corner/state_machines/failed_initial_payment_cancels_without_ledger_row
    """
    ctx = setup_account_with_pending_sub(email="fail@x.com")
    sub = validate_success(
        api.simulate_payment(ctx["subscription"]["id"], "FAILED",
                             platform_admin_headers)
    )
    assert sub["status"] == "CANCELLED"
    assert sub["entitlement_state"] == "REVOKED"
    assert sub["cancelled_at"] is not None

    _, meta = validate_paginated(
        api.list_subscription_payments(sub["id"], platform_admin_headers)
    )
    assert meta["total_count"] == 0
    assert sub["paid_amount_cents"] == 0

    _, ent_meta = validate_paginated(
        api.list_game_entitlements(
            platform_admin_headers, params={"subscription_id": sub["id"]}
        )
    )
    assert ent_meta["total_count"] == 0


def test_cancel_from_pending_payment_rejected(api, platform_admin_headers):
    """PRD §3.5: "A subscriber (or venue manager) who owns the account may
    cancel an `ACTIVE` subscription" — a `PENDING_PAYMENT` subscription is not
    in a valid source state for cancel, and per PRD §2.8 "non-terminal
    wrong-state calls yield `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancel_from_pending_payment_rejected
    """
    ctx = setup_account_with_pending_sub(email="pend@x.com")
    sub = ctx["subscription"]
    validate_error(
        api.cancel_subscription(
            sub["id"], make_subscriber_headers(ctx["account"]["id"])
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )
    reread = validate_success(
        api.get_subscription(sub["id"], platform_admin_headers)
    )
    assert reread["status"] == "PENDING_PAYMENT"


def test_second_cancel_rejected_and_first_cancel_facts_hold(
    api, platform_admin_headers
):
    """PRD §2.8: "Source-state legality — the target resource is in a valid
    source state for the requested transition; a transition attempted against
    a terminal state instead yields `ERR_ALREADY_TERMINAL` (both HTTP 409;
    non-terminal wrong-state calls yield `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/double_cancel_idempotency_returns_invalid_state
    """
    ctx = setup_week4_game_account_sub(email="dc@x.com", billing_zip="10001")
    sub = ctx["subscription"]
    first = validate_success(
        api.cancel_subscription(
            sub["id"], make_subscriber_headers(ctx["account"]["id"])
        )
    )
    assert first["status"] == "CANCELLED"

    resp = api.cancel_subscription(
        sub["id"], make_subscriber_headers(ctx["account"]["id"])
    )
    assert resp.status_code == 409, (
        f"second cancel must fail 409, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["data"]["error_id"] in (
        ApiErrorId.ERR_ALREADY_TERMINAL.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    reread = validate_success(
        api.get_subscription(sub["id"], platform_admin_headers)
    )
    assert reread["status"] == "CANCELLED"
    assert reread["cancelled_at"] == first["cancelled_at"]
    assert reread["paid_amount_cents"] == first["paid_amount_cents"]


def test_withdrawn_offer_preserves_existing_subscription_snapshot(
    api, platform_admin_headers
):
    """PRD §3.5: "An offer is born `ACTIVE` and may be withdrawn, moving to
    `WITHDRAWN`; withdrawal rejects new purchases but leaves existing
    subscriptions' snapshots untouched."

    Design: Corner/endpoints/withdrawn_offer_preserves_existing_subscription_snapshot
    """
    ctx = setup_account_with_pending_sub(email="snap@x.com")
    offer = ctx["offer"]
    sub = ctx["subscription"]
    validate_success(api.withdraw_offer(offer["id"], platform_admin_headers))

    activated = validate_success(
        api.simulate_payment(sub["id"], "SUCCEEDED", platform_admin_headers)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["price_charged_cents"] == 16667
    assert activated["plan_tier"] == "BASE"

    # New purchase against the withdrawn offer fails.
    account2 = register_account(email="snap2@x.com", billing_zip="10001")
    validate_error(
        api.create_subscription(account2["id"], offer["id"],
                                make_subscriber_headers(account2["id"])),
        ApiErrorId.ERR_OFFER_NOT_AVAILABLE,
    )
