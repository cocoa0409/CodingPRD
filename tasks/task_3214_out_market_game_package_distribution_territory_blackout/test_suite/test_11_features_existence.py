"""Feature entitlements and existence-before-state ordering."""
from test_helpers import (
    ApiErrorId,
    NONEXISTENT_UUID,
    make_subscriber_headers,
    register_account,
    setup_week4_game_account_sub,
    validate_error,
    validate_success,
)


def test_features_read_reports_snapshot_flags_and_market_adjusted_count(
    api, platform_admin_headers
):
    """PRD §3.11: "The first is a computed read, the subscription's features,
    which aggregates three things fresh on every call: `multiview` — true
    exactly when the subscription's offer snapshot has `includes_multiview`
    and the `entitlement_state` is `ENABLED`; `companion` — the same for
    `includes_companion`; and `package_games_available_this_week` — the count
    of the subscription's entitlement rows in `status` `GRANTED` whose
    `week_index` equals the season week containing the current logical-clock
    instant, minus those rows whose game's `home_market_code` equals the
    account's `billing_market_code`."

    Design: Corner/calculations/features_read_aggregation_respects_entitlement_state
    """
    ctx = setup_week4_game_account_sub(
        email="feat@x.com", billing_zip="10001",
        markets=("NYC", "DAL"),
        games=("BUF@NYC", "KC@DAL"),
        offer_overrides={"plan_tier": "PREMIUM", "base_price_cents": 30000,
                         "includes_multiview": True, "includes_companion": True},
    )
    sub_id = ctx["subscription"]["id"]
    features = validate_success(
        api.get_subscription_features(
            sub_id, make_subscriber_headers(ctx["account"]["id"])
        )
    )
    assert features["multiview"] is True
    assert features["companion"] is True
    # Two GRANTED week-4 rows; the NYC-home game matches the account's billing
    # market and is subtracted.
    assert features["package_games_available_this_week"] == 1


def test_features_flags_gate_on_entitlement_state_while_count_uses_rows(
    api, platform_admin_headers
):
    """PRD §3.11: "`multiview` — true exactly when the subscription's offer
    snapshot has `includes_multiview` and the `entitlement_state` is
    `ENABLED`; `companion` — the same for `includes_companion`". PRD §3.5:
    "while suspended, territory checks for the subscription return
    `NO_ENTITLEMENT`, but the entitlement rows themselves are unchanged."

    Design: Corner/calculations/features_read_aggregation_respects_entitlement_state
    """
    ctx = setup_week4_game_account_sub(
        email="feat2@x.com", billing_zip="10001",
        markets=("NYC", "DAL"),
        games=("BUF@NYC", "KC@DAL"),
        offer_overrides={"plan_tier": "PREMIUM", "base_price_cents": 30000,
                         "includes_multiview": True, "includes_companion": True},
    )
    sub_id = ctx["subscription"]["id"]
    validate_success(api.suspend_entitlement(sub_id, platform_admin_headers))
    features = validate_success(
        api.get_subscription_features(
            sub_id, make_subscriber_headers(ctx["account"]["id"])
        )
    )
    assert features["multiview"] is False
    assert features["companion"] is False
    # The count is entitlement-row based; suspension does not mutate the rows.
    assert features["package_games_available_this_week"] == 1


def test_cancelling_nonexistent_subscription_reports_not_found(api):
    """PRD §2.8: "Endpoints that address resources through hierarchical paths
    validate path identifiers left to right — grant before season before
    week-slate or offer; account before subscription, venue license, complaint
    case, student verification, or override. The first identifier that does
    not resolve to an existing resource fails the whole request with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/existence_checked_before_state_on_bad_path_id
    """
    account = register_account(email="ex@x.com", billing_zip="10001")
    validate_error(
        api.cancel_subscription(
            NONEXISTENT_UUID, make_subscriber_headers(account["id"])
        ),
        ApiErrorId.ERR_NOT_FOUND,
    )


def test_get_nonexistent_subscription_reports_not_found(
    api, platform_admin_headers
):
    """PRD §2.8: "The first identifier that does not resolve to an existing
    resource fails the whole request with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/existence_checked_before_state_on_bad_path_id
    """
    register_account(email="ex2@x.com", billing_zip="10001")
    validate_error(
        api.get_subscription(NONEXISTENT_UUID, platform_admin_headers),
        ApiErrorId.ERR_NOT_FOUND,
    )
