"""Ad slots: fill two-leg protocol, OCC on window, pod feasibility (PRD §3.8, §2.6)."""
from test_helpers import (
    AD,
    RM,
    ApiErrorId,
    create_active_property,
    create_booked_campaign,
    create_slot,
    create_window,
    fill_slot,
    get_success_data,
    validate_error,
    validate_success,
)


def _window_with_campaign(api):
    prop = create_active_property()
    window = create_window(
        prop["id"],
        scheduled_start="2026-10-08T18:00:00Z",
        scheduled_end="2026-10-08T21:00:00Z",
    )
    campaign = create_booked_campaign()
    return prop, window, campaign


def test_occ_stale_window_version_on_slot_fill(api):
    """PRD §2.6: "Filling an `AdSlot` via the slot-fill endpoint requires a
    non-optional `expected_window_version` field carrying the client's last
    observed `version` of the parent `StreamingWindow`. If the window's
    version has advanced since the client last read it — for example,
    because a window cancel or supersede cascade just mutated it — the fill
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.8: "A successful fill — across either leg — increments the parent
    window's `version` by 1."

    Design: Corner/cross_cutting_layers/occ_stale_window_version_on_slot_fill
    """
    _, window, campaign = _window_with_campaign(api)
    slot_a = create_slot(window["id"], break_index=1, pod_index=1,
                         duration_seconds=30, slot_scope="NATIONAL")
    slot_b = create_slot(window["id"], break_index=1, pod_index=2,
                         duration_seconds=30, slot_scope="NATIONAL")
    stale_version = window["version"]
    # First fill advances the window version.
    resp1 = api.fill_ad_slot(
        slot_a["id"],
        {"campaign_id": campaign["id"], "expected_window_version": stale_version},
        AD,
    )
    validate_success(resp1)
    # Second fill with the pre-first-fill version is stale.
    resp2 = api.fill_ad_slot(
        slot_b["id"],
        {"campaign_id": campaign["id"], "expected_window_version": stale_version},
        AD,
    )
    validate_error(resp2, ApiErrorId.ERR_STALE_VERSION)


def test_pod_construction_feasible_fill_reserved(api):
    """PRD §3.8: "Within a given `break_index`, the durations of all slots
    must sum to exactly 120 seconds — the pod length is fixed." and "the
    fill must satisfy pod-construction duration feasibility, else the
    request is rejected with `ERR_POD_INFEASIBLE` (HTTP 422). The
    reservation leg sets `booked_campaign_id` to the campaign and increments
    the slot's `version`."

    30 FILLED + 30 being filled + 60 OPEN sums to exactly 120, so the fill
    is feasible and lands in RESERVED.

    Design: Corner/calculations/pod_construction_feasibility_120_seconds
    """
    _, window, campaign = _window_with_campaign(api)
    slot_a = create_slot(window["id"], break_index=1, pod_index=1,
                         duration_seconds=30, slot_scope="NATIONAL")
    slot_b = create_slot(window["id"], break_index=1, pod_index=2,
                         duration_seconds=30, slot_scope="NATIONAL")
    create_slot(window["id"], break_index=1, pod_index=3,
                duration_seconds=60, slot_scope="NATIONAL")
    fill_slot(slot_a["id"], campaign["id"])  # slot_a RESERVED
    reserved_b = fill_slot(slot_b["id"], campaign["id"])
    assert reserved_b["status"] == "RESERVED"
    assert reserved_b["booked_campaign_id"] == campaign["id"]


def test_local_slot_fill_region_mismatch_returns_pod_infeasible(api):
    """PRD §3.8: "a `LOCAL` slot may only be filled by a campaign whose
    `region_target` includes the slot's `region_code`" and "the fill must
    satisfy pod-construction duration feasibility, else the request is
    rejected with `ERR_POD_INFEASIBLE` (HTTP 422)."
    PRD §2.5: "19. `ERR_POD_INFEASIBLE` (HTTP 422) — the slot fill violates
    pod-construction feasibility or region targeting."

    Design: Corner/validations/local_slot_fill_region_mismatch_returns_pod_infeasible
    """
    _, window, _ = _window_with_campaign(api)
    wrong_region_campaign = create_booked_campaign(region_target=["620"])
    slot = create_slot(window["id"], break_index=1, pod_index=1,
                       duration_seconds=30, slot_scope="LOCAL", region_code="510")
    current_wv = get_success_data(api.get_window(window["id"], RM))["version"]
    resp = api.fill_ad_slot(
        slot["id"],
        {"campaign_id": wrong_region_campaign["id"], "expected_window_version": current_wv},
        AD,
    )
    validate_error(resp, ApiErrorId.ERR_POD_INFEASIBLE)


def test_pod_summary_computed_read(api):
    """PRD §3.8: "A computed read against the window returns a
    pod-construction summary of the form `{ breaks, total_open_seconds,
    total_filled_seconds }`, with `breaks` arrayed per break."

    One 30s RESERVED/FILLED slot plus 30s OPEN plus 60s OPEN:
    total_filled_seconds == 30, total_open_seconds == 90.

    Design: Corner/endpoints/pod_summary_computed_read
    """
    _, window, campaign = _window_with_campaign(api)
    slot_a = create_slot(window["id"], break_index=1, pod_index=1,
                         duration_seconds=30, slot_scope="NATIONAL")
    create_slot(window["id"], break_index=1, pod_index=2,
                duration_seconds=30, slot_scope="NATIONAL")
    create_slot(window["id"], break_index=1, pod_index=3,
                duration_seconds=60, slot_scope="NATIONAL")
    fill_slot(slot_a["id"], campaign["id"])  # 30 seconds no longer OPEN
    summary = validate_success(api.get_window_pods(window["id"], AD))
    assert summary["total_filled_seconds"] == 30, (
        f"expected total_filled_seconds 30, got {summary['total_filled_seconds']}"
    )
    assert summary["total_open_seconds"] == 90, (
        f"expected total_open_seconds 90, got {summary['total_open_seconds']}"
    )
    assert isinstance(summary["breaks"], list) and len(summary["breaks"]) >= 1
