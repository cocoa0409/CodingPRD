"""Territory checks: effective-market variant selection, verdict chain,
override supremacy, and evidence-row immutability."""
from test_helpers import (
    TEST_USERS,
    create_game,
    create_grant,
    create_market,
    create_offer,
    create_season,
    create_slate,
    make_subscriber_headers,
    make_support_agent_headers,
    register_account,
    set_clock,
    setup_week4_game_account_sub,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _nyc_account_with_dal_game(api):
    """Account billed in NYC (10001), ACTIVE BASE subscription, week-4 game
    KC@DAL whose home market is DAL."""
    ctx = setup_week4_game_account_sub(
        email="terr@x.com", billing_zip="10001", markets=("NYC", "DAL"),
        games=("KC@DAL",),
    )
    return ctx


def test_active_account_uses_device_market_and_blackouts_home_game(
    api, platform_admin_headers
):
    """PRD §3.6: "For an account in `ACTIVE` status, the device-preferred
    variant applies: the effective market is `device_market_code` when the
    device ZIP mapped to a market, falling back to `billing_market_code` only
    when the device ZIP is unmapped." PRD §3.6: "if the game's
    `home_market_code` equals the effective market, the verdict is
    `BLACKED_OUT`".

    Design: Difficulty/dual_variant_calc/effective_market_device_vs_billing_authoritative
    """
    ctx = _nyc_account_with_dal_game(api)
    check = validate_success(
        api.create_territory_check(
            ctx["account"]["id"], ctx["subscription"]["id"],
            ctx["games"][0]["id"], "75001",
            make_subscriber_headers(ctx["account"]["id"]),
        ),
        expected_status=201,
    )
    assert check["effective_market_code"] == "DAL"
    assert check["verdict"] == "BLACKED_OUT"


def test_suspension_switches_effective_market_to_billing(
    api, compliance_auditor_headers
):
    """PRD §3.6: "For an account in `SUSPENDED` status — one flagged for
    commercial misuse — the billing-authoritative variant applies:
    `billing_market_code` wins always, even when the device ZIP maps cleanly
    to a different market. A flagged account, in other words, loses the
    benefit of device-location deference."

    Design: Difficulty/dual_variant_calc/effective_market_device_vs_billing_authoritative
    """
    ctx = _nyc_account_with_dal_game(api)
    game_id = ctx["games"][0]["id"]

    before = validate_success(
        api.create_territory_check(
            ctx["account"]["id"], ctx["subscription"]["id"], game_id, "75001",
            make_subscriber_headers(ctx["account"]["id"]),
        ),
        expected_status=201,
    )
    assert before["effective_market_code"] == "DAL"
    assert before["verdict"] == "BLACKED_OUT"

    flagged = validate_success(
        api.flag_commercial_misuse(
            ctx["account"]["id"], "suspected bar streaming",
            compliance_auditor_headers,
        )
    )
    assert flagged["status"] == "SUSPENDED"

    # The misuse flag also suspends the subscription's entitlement dimension,
    # so the post-flag check fails the entitlement gate before the verdict
    # reaches the market comparison.
    after = validate_success(
        api.create_territory_check(
            ctx["account"]["id"], ctx["subscription"]["id"], game_id, "75001",
            make_support_agent_headers("sa-jane"),
        ),
        expected_status=201,
    )
    assert after["effective_market_code"] == "NYC"
    assert after["verdict"] == "NO_ENTITLEMENT"

    sub_now = validate_success(
        api.get_subscription(ctx["subscription"]["id"],
                             make_support_agent_headers("sa-jane"))
    )
    assert sub_now["entitlement_state"] == "SUSPENDED"
    assert sub_now["status"] == "ACTIVE"


def test_national_selected_game_verdicts_not_in_package(
    api, league_ops_headers
):
    """PRD §3.6: "if the game's week slate is `FINALIZED` or `LOCKED` and the
    game is not in the slate's `finalized_game_ids`, the verdict is
    `NOT_IN_PACKAGE`; equivalently, if the slate is still `PRELIMINARY` and
    the game appears in its live `national_game_ids`, the verdict is likewise
    `NOT_IN_PACKAGE`."

    Design: Corner/calculations/game_availability_excludes_national_selections_from_package
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="NYC", name="New York", zip_prefixes=["100"],
                  home_team_codes=["NYC"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    create_market(code="LA", name="Los Angeles", zip_prefixes=["900"],
                  home_team_codes=["LAC"])
    slate = create_slate(season["id"], week_index=4)
    game_dal = create_game(season["id"], away_team_code="KC",
                           home_team_code="DAL",
                           kickoff_at="2026-08-30T17:00:00Z",
                           home_market_code="DAL")
    create_game(season["id"], away_team_code="BUF", home_team_code="NYC",
                kickoff_at="2026-08-30T17:00:00Z", home_market_code="NYC")
    create_game(season["id"], away_team_code="LAC", home_team_code="DEN",
                kickoff_at="2026-08-30T20:00:00Z", home_market_code="LA")
    offer = create_offer(season["id"])
    account = register_account(email="pack@x.com", billing_zip="10001")
    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    validate_success(
        api.simulate_payment(sub["id"], "SUCCEEDED", ADMIN)
    )
    slate_now = validate_success(api.get_week_slate(slate["id"], league_ops_headers))
    moved = validate_success(
        api.slate_selection(slate["id"], game_dal["id"], "ADD",
                            slate_now["version"], league_ops_headers)
    )
    assert moved["package_game_count"] == 2

    check = validate_success(
        api.create_territory_check(
            account["id"], sub["id"], game_dal["id"], "10001",
            make_subscriber_headers(account["id"]),
        ),
        expected_status=201,
    )
    assert check["verdict"] == "NOT_IN_PACKAGE"


def test_territory_check_row_re_reads_identically_after_state_change(
    api, platform_admin_headers
):
    """PRD §2.4: "`Payment` rows and `TerritoryCheck` rows are append-only
    evidence: each carries only `id` and `created_at`. Neither `updated_at`
    nor `version` exists on them, because neither is ever mutated — a payment
    ledger entry or a territory-check verdict, once written, is permanent."

    Design: Corner/entities/payment_and_territory_check_rows_are_immutable
    """
    ctx = setup_week4_game_account_sub(email="im@x.com", billing_zip="75001")
    check = validate_success(
        api.create_territory_check(
            ctx["account"]["id"], ctx["subscription"]["id"],
            ctx["games"][0]["id"], "75001",
            make_subscriber_headers(ctx["account"]["id"]),
        ),
        expected_status=201,
    )
    assert check["verdict"] == "BLACKED_OUT"
    assert "updated_at" not in check
    assert "version" not in check

    # Mutate surrounding state: cancel the subscription.
    validate_success(
        api.cancel_subscription(
            ctx["subscription"]["id"],
            make_subscriber_headers(ctx["account"]["id"]),
        )
    )

    reread = validate_success(
        api.get_territory_check(check["id"], platform_admin_headers)
    )
    assert reread["verdict"] == check["verdict"]
    assert reread["effective_market_code"] == check["effective_market_code"]
    assert reread["checked_at"] == check["checked_at"]
    assert "updated_at" not in reread
    assert "version" not in reread
