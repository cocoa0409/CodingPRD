"""Cascades: property suspend depth-3 and window complete depth-2 (PRD §2.9, §3.3)."""
from test_helpers import (
    AD,
    RM,
    SO,
    api_client,
    assert_ad_slot,
    create_active_property,
    create_booked_campaign,
    create_pool,
    create_slot,
    create_window,
    fill_slot,
    get_success_data,
    hold_and_confirm,
    make_live_window,
    set_clock,
    validate_success,
)


def test_property_suspend_cascades_window_and_slot(api):
    """PRD §2.9: "Suspending a property cancels every `SCHEDULED` window
    under it (see §3.1); each window cancellation then cancels its ad slots
    and releases its capacity reservations."
    PRD §3.3: "Cancellation transitions every `AdSlot` of the window to
    `CANCELLED` (clearing `booked_campaign_id` on any `RESERVED` slot ...)".

    Design: Difficulty/transitive_cascade/property_suspend_cascades_window_slot_impression_depth3
    """
    prop = create_active_property()
    window = create_window(
        prop["id"],
        scheduled_start="2026-09-08T18:00:00Z",
        scheduled_end="2026-09-08T21:00:00Z",
        replay_hours=24,
    )
    campaign = create_booked_campaign()
    slot = create_slot(prop_id := window["id"], break_index=1, pod_index=1,
                       duration_seconds=30, slot_scope="NATIONAL")
    reserved = fill_slot(slot["id"], campaign["id"])
    assert reserved["status"] == "RESERVED"
    assert reserved["booked_campaign_id"] == campaign["id"]

    validate_success(api.suspend_property(prop["id"], RM))

    window_after = validate_success(api.get_window(window["id"], RM))
    assert window_after["status"] == "CANCELLED"
    slots = validate_success(api.list_ad_slots(AD, params={"window_id": window["id"]}))
    assert len(slots) == 1
    assert slots[0]["status"] == "CANCELLED"
    assert slots[0]["booked_campaign_id"] is None


def test_property_suspend_releases_window_reservations(api):
    """PRD §3.1: "on suspension, every `SCHEDULED` window of the property
    transitions to `CANCELLED` with the full cancel cascade described in
    §3.2 — ad slots on those windows are cancelled and their capacity
    reservations released."
    PRD §3.5: "in every release path the reservation transitions to
    `RELEASED` and the pool's `committed_units` is decremented by `units`."

    Design: Difficulty/transitive_cascade/property_suspend_cascades_window_slot_impression_depth3
    """
    prop = create_active_property()
    window = create_window(
        prop["id"],
        scheduled_start="2026-09-08T18:00:00Z",
        scheduled_end="2026-09-08T21:00:00Z",
        capacity_required_units=3,
    )
    pool = create_pool(total_units=20)
    res = hold_and_confirm(pool["id"], window["id"], units=3)
    pool_mid = get_success_data(api.get_capacity_pool(pool["id"], SO))
    assert pool_mid["committed_units"] == 3

    validate_success(api.suspend_property(prop["id"], RM))

    res_after = get_success_data(api.get_capacity_reservation(res["id"], SO))
    assert res_after["status"] == "RELEASED"
    pool_after = get_success_data(api.get_capacity_pool(pool["id"], SO))
    assert pool_after["committed_units"] == 0


def _live_window_with_pool(window_overrides, capacity_units, live_at):
    """make_live_window variant that also returns the pool used for capacity,
    so the test can read the pool directly by id (PRD §3.5 defines
    `committed_units` as the sum over non-terminal reservations; it does not
    define a window-to-pool reverse filter)."""
    prop = create_active_property()
    window = create_window(prop["id"], **window_overrides)
    pool = create_pool(total_units=max(capacity_units, 100))
    hold_and_confirm(pool["id"], window["id"], units=capacity_units)
    set_clock(live_at)
    window = get_success_data(api_client.go_live_window(window["id"], RM))
    return prop, window, pool


def test_window_complete_creates_replay_asset_and_releases_reservations(api):
    """PRD §3.3: "Completion creates a `ReplayAsset` with `status` set to
    `AVAILABLE`, `available_from` set to the current logical time, and
    `expires_at` set to `available_from` plus the window's `replay_hours`.
    Completion also releases every `CONFIRMED` capacity reservation of the
    window (each transitions to `RELEASED` and decrements its pool's
    `committed_units` by its `units`) ...".

    Design: Difficulty/transitive_cascade/window_complete_cascades_replay_reservation_depth2
    """
    prop, window, pool = _live_window_with_pool(
        window_overrides={
            "scheduled_start": "2026-09-09T18:00:00Z",
            "scheduled_end": "2026-09-09T21:00:00Z",
            "capacity_required_units": 5,
            "replay_hours": 48,
        },
        capacity_units=5,
        live_at="2026-09-09T18:00:00Z",
    )
    pool_id = pool["id"]
    before = get_success_data(api.get_capacity_pool(pool_id, SO))
    assert before["committed_units"] == 5

    completed = validate_success(api.complete_window(window["id"], RM))
    assert completed["status"] == "COMPLETE"

    pool_after = get_success_data(api.get_capacity_pool(pool_id, SO))
    assert pool_after["committed_units"] == 0

    assets = validate_success(api.list_replay_assets(RM, params={"window_id": window["id"]}))
    assert len(assets) == 1
    asset = assets[0]
    assert asset["status"] == "AVAILABLE"
    assert asset["available_from"] == "2026-09-09T18:00:00Z"
    # expires_at == available_from + replay_hours(48h)
    assert asset["expires_at"] == "2026-09-11T18:00:00Z"


def test_window_complete_releases_only_after_confirm_counted(api):
    """PRD §2.9: "Completing a `LIVE` window releases its `CONFIRMED`
    reservations, creates a `ReplayAsset`, and triggers a recompute of the
    property's `amortized_fee_cents`."

    Completing with several confirmed reservations drains every pool the
    window drew from, not just one.

    Design: Difficulty/transitive_cascade/window_complete_cascades_replay_reservation_depth2
    """
    prop = create_active_property()
    window = create_window(
        prop["id"],
        scheduled_start="2026-09-09T18:00:00Z",
        scheduled_end="2026-09-09T21:00:00Z",
        capacity_required_units=6,
        replay_hours=0,
    )
    pool_a = create_pool(total_units=20)
    pool_b = create_pool(total_units=20)
    hold_and_confirm(pool_a["id"], window["id"], units=3)
    hold_and_confirm(pool_b["id"], window["id"], units=3)
    set_clock("2026-09-09T18:00:00Z")
    validate_success(api.go_live_window(window["id"], RM))
    validate_success(api.complete_window(window["id"], RM))
    for pool in (pool_a, pool_b):
        after = get_success_data(api.get_capacity_pool(pool["id"], SO))
        assert after["committed_units"] == 0, (
            f"pool {pool['pool_code']} committed_units {after['committed_units']} != 0 after complete"
        )
