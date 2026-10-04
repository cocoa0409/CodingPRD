"""Cascades (grant terminate, season POST advance) and optimistic-concurrency
conflicts on slates and seasons."""
from test_helpers import (
    ApiErrorId,
    create_game,
    create_grant,
    create_market,
    create_offer,
    create_season,
    create_slate,
    create_venue_license,
    make_subscriber_headers,
    register_account,
    set_clock,
    setup_week4_game_account_sub,
    validate_error,
    validate_paginated,
    validate_success,
)


def _regular_season_ctx(api, league_ops_headers):
    """Grant + 18-week season advanced to REGULAR + DAL market + week-4 slate
    with one game + BASE offer."""
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    create_slate(season["id"], week_index=4)
    create_game(season["id"], week_index=4, away_team_code="KC",
                home_team_code="DAL", kickoff_at="2026-08-30T17:00:00Z",
                home_market_code="DAL")
    advanced = validate_success(
        api.advance_season_phase(season["id"], season["version"], league_ops_headers)
    )
    assert advanced["phase"] == "REGULAR"
    offer = create_offer(season["id"])
    return grant, advanced, offer


def _paid_sub(api, offer, email, billing_zip):
    account = register_account(email=email, billing_zip=billing_zip)
    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    return account, sub


def test_terminate_cascades_through_season_subscription_entitlement_license(
    api, platform_admin_headers, league_ops_headers, compliance_auditor_headers
):
    """PRD §3.1: "Each season under the grant is pushed to phase `POST` if it
    is not already there. Every subscription whose season belongs to the grant
    and whose `status` is `ACTIVE` is transitioned to `CANCELLED`, its
    `cancelled_at` stamped with the logical-clock instant and its
    `entitlement_state` forced to `REVOKED`. Every game entitlement hanging
    under those subscriptions moves to `WITHDRAWN` with `withdrawn_reason`
    `ENTITLEMENT_REVOKED`. And every venue license held by accounts of this
    distributor is `REVOKED`."

    Design: Difficulty/transitive_cascade/grant_terminate_depth4_cascade
    """
    grant, season, offer = _regular_season_ctx(api, league_ops_headers)
    account, sub = _paid_sub(api, offer, "fan@x.com", "10001")
    validate_success(
        api.simulate_payment(sub["id"], "SUCCEEDED", platform_admin_headers)
    )

    venue_account = register_account(
        email="bar@x.com", full_name="Bar Keep", account_kind="COMMERCIAL",
        billing_zip="75001",
    )
    license_ = create_venue_license(venue_account["id"], fire_code_occupancy=80)
    validate_success(
        api.certify_venue_license(license_["id"], compliance_auditor_headers)
    )

    terminated = validate_success(
        api.terminate_rights_grant(grant["id"], platform_admin_headers)
    )
    assert terminated["status"] == "TERMINATED"

    season_now = validate_success(
        api.get_season(season["id"], league_ops_headers)
    )
    assert season_now["phase"] == "POST"

    sub_now = validate_success(
        api.get_subscription(sub["id"], platform_admin_headers)
    )
    assert sub_now["status"] == "CANCELLED"
    assert sub_now["entitlement_state"] == "REVOKED"

    ents, _ = validate_paginated(
        api.list_game_entitlements(
            platform_admin_headers, params={"subscription_id": sub["id"]}
        )
    )
    assert len(ents) > 0
    for row in ents:
        assert row["status"] == "WITHDRAWN"
        assert row["withdrawn_reason"] == "ENTITLEMENT_REVOKED"

    license_now = validate_success(
        api.get_venue_license(license_["id"], compliance_auditor_headers)
    )
    assert license_now["status"] == "REVOKED"


def test_terminate_stamps_cancelled_at_and_strips_entitlements(
    api, platform_admin_headers, league_ops_headers
):
    """PRD §3.1: "Every subscription whose season belongs to the grant and
    whose `status` is `ACTIVE` is transitioned to `CANCELLED`, its
    `cancelled_at` stamped with the logical-clock instant and its
    `entitlement_state` forced to `REVOKED`."

    Design: Difficulty/transitive_cascade/grant_terminate_depth4_cascade
    """
    grant, season, offer = _regular_season_ctx(api, league_ops_headers)
    account, sub = _paid_sub(api, offer, "fan2@x.com", "10001")
    validate_success(
        api.simulate_payment(sub["id"], "SUCCEEDED", platform_admin_headers)
    )
    validate_success(api.terminate_rights_grant(grant["id"], platform_admin_headers))

    sub_now = validate_success(
        api.get_subscription(sub["id"], platform_admin_headers)
    )
    assert sub_now["status"] == "CANCELLED"
    assert sub_now["cancelled_at"] is not None
    # Stamped with the logical-clock instant (2026-09-01T00:00:00Z); fractional
    # second rendering is serializer-dependent, so compare the instant prefix.
    assert str(sub_now["cancelled_at"]).startswith("2026-09-01T00:00:00")
    assert sub_now["entitlement_state"] == "REVOKED"


def test_season_post_advance_expires_active_subscriptions(
    api, league_ops_headers, platform_admin_headers
):
    """PRD §3.2: "The second advance, `REGULAR` → `POST`, carries a heavy
    cascade: every subscription of the season whose `status` is `ACTIVE`
    transitions to `EXPIRED` (its `entitlement_state` left unchanged unless it
    was already `REVOKED`), and every game entitlement under those
    subscriptions that is `GRANTED` becomes `WITHDRAWN` with
    `withdrawn_reason` `ENTITLEMENT_REVOKED`."

    Design: Difficulty/transitive_cascade/season_post_advance_depth2_cascade
    """
    _, season, offer = _regular_season_ctx(api, league_ops_headers)
    acct_a, sub_a = _paid_sub(api, offer, "a@x.com", "10001")
    acct_b, sub_b = _paid_sub(api, offer, "b@x.com", "75001")
    for sub in (sub_a, sub_b):
        validate_success(
            api.simulate_payment(sub["id"], "SUCCEEDED", platform_admin_headers)
        )

    advanced = validate_success(
        api.advance_season_phase(season["id"], season["version"],
                                 league_ops_headers)
    )
    assert advanced["phase"] == "POST"

    for sub in (sub_a, sub_b):
        sub_now = validate_success(
            api.get_subscription(sub["id"], platform_admin_headers)
        )
        assert sub_now["status"] == "EXPIRED"
        ents, _ = validate_paginated(
            api.list_game_entitlements(
                platform_admin_headers, params={"subscription_id": sub["id"]}
            )
        )
        assert len(ents) > 0
        for row in ents:
            assert row["status"] == "WITHDRAWN"
            assert row["withdrawn_reason"] == "ENTITLEMENT_REVOKED"


def test_expired_not_cancelled_marks_season_end(api, league_ops_headers,
                                                platform_admin_headers):
    """PRD §3.2: "Note the deliberate distinction between a subscription
    ending `EXPIRED` (season ran out from under it) and `CANCELLED` (someone
    actively cancelled) — the refund math in §3.7 reads that distinction."

    Design: Difficulty/transitive_cascade/season_post_advance_depth2_cascade
    """
    _, season, offer = _regular_season_ctx(api, league_ops_headers)
    account, sub = _paid_sub(api, offer, "dist@x.com", "10001")
    validate_success(
        api.simulate_payment(sub["id"], "SUCCEEDED", platform_admin_headers)
    )
    validate_success(
        api.advance_season_phase(season["id"], season["version"],
                                 league_ops_headers)
    )
    sub_now = validate_success(
        api.get_subscription(sub["id"], platform_admin_headers)
    )
    assert sub_now["status"] == "EXPIRED"
    assert sub_now["status"] != "CANCELLED"


def test_selection_move_with_stale_version_rejected(api, league_ops_headers):
    """PRD §2.7: "Moving a national selection on a weekly slate — adding or
    removing a game — requires `expected_slate_version` in the request body,
    matching the target `WeekSlate`'s current `version`." PRD §2.7: "If the
    supplied value does not match the parent entity's current `version` —
    because another writer has advanced the slate or the season since the
    client last read it — the request is rejected with
    `ERR_STALE_SLATE_VERSION` (HTTP 412) for the two slate operations".

    Design: Corner/errors/stale_slate_version_occ_conflict
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
    observed_version = slate["version"]
    validate_success(
        api.slate_selection(slate["id"], game_a["id"], "ADD",
                            observed_version, league_ops_headers)
    )
    validate_error(
        api.slate_selection(slate["id"], game_b["id"], "ADD",
                            observed_version, league_ops_headers),
        ApiErrorId.ERR_STALE_SLATE_VERSION,
    )
    slate_now = validate_success(
        api.get_week_slate(slate["id"], league_ops_headers)
    )
    assert slate_now["national_game_ids"] == [game_a["id"]]


def test_finalize_with_stale_version_rejected(api, league_ops_headers):
    """PRD §2.7: "Finalizing a weekly slate likewise requires
    `expected_slate_version` matching the slate's current `version`." PRD
    §2.7: "the request is rejected with `ERR_STALE_SLATE_VERSION` (HTTP 412)
    for the two slate operations".

    Design: Corner/errors/stale_slate_version_occ_conflict
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
    observed_version = slate["version"]
    moved = validate_success(
        api.slate_selection(slate["id"], game_a["id"], "ADD",
                            observed_version, league_ops_headers)
    )
    assert moved["version"] == observed_version + 1
    validate_error(
        api.finalize_week_slate(slate["id"], observed_version,
                                league_ops_headers),
        ApiErrorId.ERR_STALE_SLATE_VERSION,
    )
    slate_now = validate_success(
        api.get_week_slate(slate["id"], league_ops_headers)
    )
    assert slate_now["slate_status"] == "PRELIMINARY"


def test_advance_phase_with_stale_season_version_rejected(
    api, league_ops_headers
):
    """PRD §2.7: "Advancing a season's phase requires
    `expected_season_version` matching the target `Season`'s current
    `version`. If the supplied value does not match the parent entity's
    current `version` — because another writer has advanced the slate or the
    season since the client last read it — the request is rejected with
    `ERR_STALE_SLATE_VERSION` (HTTP 412) for the two slate operations, or
    `ERR_STALE_SEASON_VERSION` (HTTP 412) for the phase advance."

    Design: Corner/errors/stale_season_version_occ_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_slate(season["id"], week_index=1)
    validate_error(
        api.advance_season_phase(season["id"], season["version"] + 5,
                                 league_ops_headers),
        ApiErrorId.ERR_STALE_SEASON_VERSION,
    )
    season_now = validate_success(api.get_season(season["id"], league_ops_headers))
    assert season_now["phase"] == "PRE_SALE"


def test_advance_phase_with_current_version_succeeds(api, league_ops_headers):
    """PRD §3.2: "The first advance, `PRE_SALE` → `REGULAR`, additionally
    requires that at least one week slate already exists for the season; a
    season cannot go "regular" with no weekly structure at all." PRD §3.2:
    "Each successful advance increments the season's `version` by one."

    Design: Corner/errors/stale_season_version_occ_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_slate(season["id"], week_index=1)
    advanced = validate_success(
        api.advance_season_phase(season["id"], season["version"],
                                 league_ops_headers)
    )
    assert advanced["phase"] == "REGULAR"
    assert advanced["version"] == season["version"] + 1
