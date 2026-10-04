"""View grants: blackout, territory, tier, replay checks (PRD §3.4, §3.12)."""
from test_helpers import (
    ApiErrorId,
    create_active_property,
    create_territory_rule_payload,
    create_viewer,
    create_window,
    make_completed_window,
    make_live_window,
    make_viewer_headers,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import RM


def _grant(api, window_id, viewer_id, grant_type):
    return api.create_view_grant(
        window_id,
        {"viewer_id": viewer_id, "grant_type": grant_type},
        make_viewer_headers(viewer_id),
    )


def test_view_grant_blackout_priority_beats_tier_insufficient(api):
    """PRD §3.4: "The grant runs four checks in priority order. First,
    blackout: if any `ACTIVE` `BLACKOUT` territory rule covers the current
    logical time for the viewer's region on this window, the grant is
    rejected with `ERR_BLACKOUT_REGION_BLOCKED` (HTTP 403). ... Third, tier:
    a `LIVE` grant against a window whose `rights_mode` is `EXCLUSIVE`
    requires the viewer's `subscription_tier` to be `PREMIUM` ...".

    An AD_SUPPORTED viewer under an ACTIVE blackout on an EXCLUSIVE window
    fails with the blackout error, not the tier error.

    Design: Corner/validations/view_grant_blackout_priority_beats_tier_insufficient
    """
    prop = create_active_property()
    window = create_window(
        prop["id"],
        rights_mode="EXCLUSIVE",
        scheduled_start="2026-09-29T18:00:00Z",
        scheduled_end="2026-09-29T21:00:00Z",
        territory_scope=["510"],
        regional_block=True,
        is_marquee=True,
    )
    validate_success(
        api.create_territory_rule(
            create_territory_rule_payload(
                window["id"], region_code="510",
                effective_start="2026-09-29T17:00:00Z",
                effective_end="2026-09-29T20:00:00Z",
            ),
            RM,
        ),
        expected_status=201,
    )
    from test_helpers import create_pool, hold_and_confirm
    pool = create_pool(total_units=10)
    hold_and_confirm(pool["id"], window["id"], units=1)
    set_clock("2026-09-29T18:00:00Z")
    validate_success(api.go_live_window(window["id"], RM))
    viewer = create_viewer(home_region="510")  # default AD_SUPPORTED tier
    resp = _grant(api, window["id"], viewer["id"], "LIVE")
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_REGION_BLOCKED)


def test_view_grant_territory_not_licensed(api):
    """PRD §3.4: "Second, territory: the viewer's region must appear in the
    window's `territory_scope`, else `ERR_TERRITORY_NOT_LICENSED`
    (HTTP 403)."

    Design: Corner/validations/view_grant_territory_not_licensed
    """
    _, window = make_live_window(
        window_overrides={
            "scheduled_start": "2026-09-30T18:00:00Z",
            "scheduled_end": "2026-09-30T21:00:00Z",
            "territory_scope": ["510"],
            "regional_block": False,
        },
        live_at="2026-09-30T18:00:00Z",
    )
    viewer = create_viewer(home_region="620")
    resp = _grant(api, window["id"], viewer["id"], "LIVE")
    validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_LICENSED)


def test_tier_insufficient_for_exclusive_live_grant(api):
    """PRD §3.4: "a `LIVE` grant against a window whose `rights_mode` is
    `EXCLUSIVE` requires the viewer's `subscription_tier` to be `PREMIUM`;
    ... A tier failure surfaces `ERR_TIER_INSUFFICIENT` (HTTP 402)."

    Design: Corner/validations/tier_insufficient_for_exclusive_live_grant
    """
    _, window = make_live_window(
        window_overrides={
            "rights_mode": "EXCLUSIVE",
            "scheduled_start": "2026-10-11T18:00:00Z",
            "scheduled_end": "2026-10-11T21:00:00Z",
            "territory_scope": ["510"],
            "regional_block": False,
            "is_marquee": True,
        },
        live_at="2026-10-11T18:00:00Z",
    )
    viewer = create_viewer(home_region="510")  # AD_SUPPORTED default
    resp = _grant(api, window["id"], viewer["id"], "LIVE")
    validate_error(resp, ApiErrorId.ERR_TIER_INSUFFICIENT)


def test_replay_expired_grant_returns_replay_expired(api):
    """PRD §3.12: "When the logical clock reaches `expires_at`, the asset
    transitions to `EXPIRED`." and "any `REPLAY` grant request against a
    non-`AVAILABLE` asset is rejected with `ERR_REPLAY_EXPIRED` (HTTP 409)."

    replay_hours 1; clock advanced past completion + 1h.

    Design: Corner/errors/replay_expired_grant_returns_replay_expired
    """
    _, window = make_completed_window(
        window_overrides={
            "scheduled_start": "2026-10-05T18:00:00Z",
            "scheduled_end": "2026-10-05T21:00:00Z",
            "replay_hours": 1,
        },
        live_at="2026-10-05T18:00:00Z",
    )
    set_clock("2026-10-05T20:30:00Z")  # past available_from + 1h
    viewer = create_viewer(home_region="510")
    resp = _grant(api, window["id"], viewer["id"], "REPLAY")
    validate_error(resp, ApiErrorId.ERR_REPLAY_EXPIRED)


def test_replay_grant_increments_replay_views(api):
    """PRD §3.12: "The `replay_views` counter starts at zero and increments
    by 1 each time a `REPLAY` view grant is issued while the asset is
    `AVAILABLE`."

    Design: Corner/state_machines/replay_grant_increments_replay_views_side_effect
    """
    _, window = make_completed_window(
        window_overrides={
            "scheduled_start": "2026-09-26T18:00:00Z",
            "scheduled_end": "2026-09-26T21:00:00Z",
            "replay_hours": 48,
        },
        live_at="2026-09-26T18:00:00Z",
    )
    viewer = create_viewer(home_region="510")
    grant = validate_success(_grant(api, window["id"], viewer["id"], "REPLAY"), expected_status=201)
    assert grant["grant_type"] == "REPLAY"
    assets = validate_success(api.list_replay_assets(RM, params={"window_id": window["id"]}))
    assert len(assets) == 1
    assert assets[0]["replay_views"] == 1
