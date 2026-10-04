"""Selection-move entitlement sweep conservation and complaint grace-window
boundary precision."""
from test_helpers import (
    ApiErrorId,
    make_subscriber_headers,
    make_support_agent_headers,
    set_clock,
    setup_week4_game_account_sub,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_SUPPORT = make_support_agent_headers("sa-jane")


def _nyc_sub_two_games(api, email):
    """NYC-billed account with ACTIVE BASE subscription over a week-4 slate
    holding KC@DAL and BUF@NYC."""
    return setup_week4_game_account_sub(
        email=email, billing_zip="10001", markets=("DAL", "NYC"),
        games=("KC@DAL", "BUF@NYC"),
    )


def test_add_withdraws_and_compensating_remove_restores_granted_rows(
    api, league_ops_headers, platform_admin_headers
):
    """PRD §3.4: "the move sweeps game entitlements across the season: for
    every subscription of the season whose `status` is `ACTIVE`, entitlements
    for the moved game transition from `GRANTED` to `WITHDRAWN` with
    `withdrawn_reason` `NATIONAL_SELECTION` when a game is added to the
    national list, and from `WITHDRAWN` back to `GRANTED` —
    `withdrawn_reason` cleared to null — when a game is removed and its
    existing withdrawal reason was `NATIONAL_SELECTION`."

    Design: Difficulty/compensating_invariant/selection_move_entitlement_count_conservation
    """
    ctx = _nyc_sub_two_games(api, "inv@x.com")
    slate = ctx["slate"]
    game_dal = ctx["games"][0]
    sub_id = ctx["subscription"]["id"]

    ents, meta = validate_paginated(
        api.list_game_entitlements(
            platform_admin_headers,
            params={"subscription_id": sub_id, "status": "GRANTED"},
        )
    )
    assert meta["total_count"] == 2

    slate_now = validate_success(api.get_week_slate(slate["id"], league_ops_headers))
    moved = validate_success(
        api.slate_selection(slate["id"], game_dal["id"], "ADD",
                            slate_now["version"], league_ops_headers)
    )

    all_rows, _ = validate_paginated(
        api.list_game_entitlements(
            platform_admin_headers, params={"subscription_id": sub_id}
        )
    )
    assert len(all_rows) == 2
    by_status = {}
    for row in all_rows:
        by_status.setdefault(row["status"], []).append(row)
    assert len(by_status.get("GRANTED", [])) == 1
    withdrawn = by_status.get("WITHDRAWN", [])
    assert len(withdrawn) == 1
    assert withdrawn[0]["withdrawn_reason"] == "NATIONAL_SELECTION"
    assert withdrawn[0]["game_id"] == game_dal["id"]

    restored = validate_success(
        api.slate_selection(slate["id"], game_dal["id"], "REMOVE",
                            moved["version"], league_ops_headers)
    )
    assert restored["package_game_count"] == 2

    all_rows2, _ = validate_paginated(
        api.list_game_entitlements(
            platform_admin_headers, params={"subscription_id": sub_id}
        )
    )
    assert len(all_rows2) == 2
    for row in all_rows2:
        assert row["status"] == "GRANTED"
        assert row["withdrawn_reason"] is None


def test_remove_does_not_resurrect_other_withdrawal_reasons(
    api, league_ops_headers, platform_admin_headers
):
    """PRD §3.4: "A withdrawal originally stamped `SUBSCRIPTION_CANCELLED` or
    `ENTITLEMENT_REVOKED` is untouched by a removal."

    Design: Difficulty/compensating_invariant/selection_move_entitlement_count_conservation
    """
    ctx = _nyc_sub_two_games(api, "inv2@x.com")
    slate = ctx["slate"]
    game_dal = ctx["games"][0]
    sub_id = ctx["subscription"]["id"]
    account_id = ctx["account"]["id"]

    slate_now = validate_success(api.get_week_slate(slate["id"], league_ops_headers))
    moved = validate_success(
        api.slate_selection(slate["id"], game_dal["id"], "ADD",
                            slate_now["version"], league_ops_headers)
    )
    # Cancel stamps the already-WITHDRAWN row's sweep; the NATIONAL_SELECTION
    # row for game_dal is not GRANTED so cancel leaves its reason, and the
    # remaining GRANTED row becomes SUBSCRIPTION_CANCELLED.
    validate_success(
        api.cancel_subscription(sub_id, make_subscriber_headers(account_id))
    )
    validate_success(
        api.slate_selection(slate["id"], game_dal["id"], "REMOVE",
                            moved["version"], league_ops_headers)
    )

    all_rows, _ = validate_paginated(
        api.list_game_entitlements(
            platform_admin_headers, params={"subscription_id": sub_id}
        )
    )
    assert len(all_rows) == 2
    for row in all_rows:
        assert row["status"] == "WITHDRAWN"
        assert row["withdrawn_reason"] in (
            "NATIONAL_SELECTION",
            "SUBSCRIPTION_CANCELLED",
        )


def _complaint_at_purchase(api, email, detail):
    """ACTIVE paid sub (16667) bought at 2026-09-01 + a BLACKOUT_DISPUTE
    complaint filed the same day."""
    ctx = setup_week4_game_account_sub(email=email, billing_zip="75001")
    case = validate_success(
        api.create_complaint_case(
            ctx["account"]["id"], ctx["subscription"]["id"],
            ctx["games"][0]["id"], "BLACKOUT_DISPUTE", detail,
            make_subscriber_headers(ctx["account"]["id"]),
        ),
        expected_status=201,
    )
    ctx["case"] = case
    return ctx


def test_approve_at_exactly_grace_boundary_succeeds(api, platform_admin_headers):
    """PRD §3.7: "The complaint must have been filed within the season's
    `grace_days` of the subscription's purchase, measured against the logical
    clock at second granularity with an inclusive boundary: filing exactly
    `grace_days` after purchase is still eligible, one second beyond is not,
    and an out-of-window approval is `ERR_COMPLAINT_WINDOW_EXPIRED` (HTTP
    422)."

    Design: Corner/calculations/complaint_window_inclusive_boundary
    """
    ctx = _complaint_at_purchase(api, "bnd@x.com", "first")
    set_clock("2026-09-08T00:00:00Z")  # exactly 7 days after the 09-01 purchase
    approved = validate_success(
        api.resolve_complaint_case(ctx["case"]["id"], "APPROVE", "at boundary",
                                   ADMIN_SUPPORT)
    )
    assert approved["status"] == "APPROVED_REFUND"
    assert approved["refund_amount_cents"] == 1111


def test_approve_one_second_past_grace_boundary_rejected(
    api, platform_admin_headers
):
    """PRD §3.7: "filing exactly `grace_days` after purchase is still
    eligible, one second beyond is not, and an out-of-window approval is
    `ERR_COMPLAINT_WINDOW_EXPIRED` (HTTP 422)."

    Design: Corner/calculations/complaint_window_inclusive_boundary
    """
    ctx = _complaint_at_purchase(api, "bnd2@x.com", "second")
    set_clock("2026-09-08T00:00:01Z")  # one second past the 7-day window
    validate_error(
        api.resolve_complaint_case(ctx["case"]["id"], "APPROVE",
                                   "one second late", ADMIN_SUPPORT),
        ApiErrorId.ERR_COMPLAINT_WINDOW_EXPIRED,
    )
    case_now = validate_success(
        api.get_complaint_case(ctx["case"]["id"], platform_admin_headers)
    )
    assert case_now["status"] == "OPEN"
