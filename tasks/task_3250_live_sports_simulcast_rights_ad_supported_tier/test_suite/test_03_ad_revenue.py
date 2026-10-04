"""Ad revenue attribution: pinned single final rounding (PRD §3.10)."""
from test_helpers import (
    AD,
    assert_impression,
    create_booked_campaign,
    create_slot,
    create_viewer,
    fill_slot_twice,
    make_live_window,
    validate_success,
)


def _setup_revenue_scenario(api, cpm_cents, duration_seconds=15, slot_scope="LOCAL",
                            region_code="510", is_marquee=True):
    """Marquee EXCLUSIVE LIVE window + FILLED slot + AD_SUPPORTED viewer."""
    prop, window = make_live_window(
        property_overrides={"required_local_breaks_per_event": 0},
        window_overrides={
            "rights_mode": "EXCLUSIVE",
            "is_marquee": is_marquee,
            "scheduled_start": "2026-09-06T18:00:00Z",
            "scheduled_end": "2026-09-06T21:00:00Z",
            "replay_hours": 24,
        },
        live_at="2026-09-06T18:00:00Z",
    )
    campaign = create_booked_campaign(cpm_cents=cpm_cents, region_target=["510"])
    slot = create_slot(
        window["id"],
        break_index=1,
        pod_index=1,
        duration_seconds=duration_seconds,
        slot_scope=slot_scope,
        region_code=region_code if slot_scope == "LOCAL" else None,
    )
    fill_slot_twice(slot["id"], campaign["id"])
    viewer = create_viewer(home_region="510")
    return window, slot, campaign, viewer


def test_ad_revenue_single_final_rounding_local_marquee(api):
    """PRD §3.10: "The base is `cpm_cents` multiplied by the slot's
    `duration_seconds` divided by 30 ... A local multiplier applies when the
    slot's `slot_scope` is `LOCAL`: the base is multiplied by 1.5 ... A
    marquee multiplier of 2.0 applies when the window's `is_marquee` is true
    and the window's `rights_mode` is `EXCLUSIVE` ... `revenue_cents` is
    this raw value rounded half-up to integer cents, with rounding applied
    **once** at the end. Per-factor rounding is forbidden."

    cpm 1001 on a 15s LOCAL slot of a marquee EXCLUSIVE window:
    raw = 1001 * 0.5 * 1.5 * 2 / 1000 = 1.5015 -> round half-up = 2.

    Design: Difficulty/combinatorial_formula/ad_revenue_single_final_rounding_local_marquee
    """
    window, slot, campaign, viewer = _setup_revenue_scenario(api, cpm_cents=1001)
    resp = api.serve_ad_slot(slot["id"], {"viewer_id": viewer["id"]}, AD)
    impression = validate_success(resp, expected_status=201)
    assert_impression(impression)
    assert impression["revenue_cents"] == 2, (
        f"expected round_half_up(1.5015)=2, got {impression['revenue_cents']}"
    )


def test_ad_revenue_fill_source_local_insertion(api):
    """PRD §3.8: "A successful serve records `campaign_id`, `viewer_id`,
    `slot_id`, `served_at` set to the current logical time, `revenue_cents`
    computed per §3.10, and `fill_source` set to `NATIONAL` for a
    `NATIONAL` slot or `LOCAL_INSERTION` for a `LOCAL` slot."

    Design: Difficulty/combinatorial_formula/ad_revenue_single_final_rounding_local_marquee
    """
    window, slot, campaign, viewer = _setup_revenue_scenario(api, cpm_cents=1001)
    resp = api.serve_ad_slot(slot["id"], {"viewer_id": viewer["id"]}, AD)
    impression = validate_success(resp, expected_status=201)
    assert impression["fill_source"] == "LOCAL_INSERTION"
    assert impression["campaign_id"] == campaign["id"]
    assert impression["viewer_id"] == viewer["id"]
    assert impression["slot_id"] == slot["id"]
