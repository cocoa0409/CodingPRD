"""Frequency cap: strict-less-than admission, equality blocks (PRD §3.10)."""
from test_helpers import (
    AD,
    ApiErrorId,
    create_booked_campaign,
    create_slot,
    create_viewer,
    fill_slot_twice,
    make_live_window,
    validate_error,
    validate_success,
)


def _servable_slot(api, cap):
    """LIVE window + FILLED NATIONAL slot booked to a campaign with the
    given per-viewer cap. Returns (window, slot, campaign)."""
    _, window = make_live_window(
        window_overrides={
            "scheduled_start": "2026-09-13T18:00:00Z",
            "scheduled_end": "2026-09-13T21:00:00Z",
        },
        live_at="2026-09-13T18:00:00Z",
    )
    campaign = create_booked_campaign(frequency_cap_per_viewer=cap)
    slot = create_slot(window["id"], break_index=1, pod_index=1,
                       duration_seconds=30, slot_scope="NATIONAL")
    fill_slot_twice(slot["id"], campaign["id"])
    return window, slot, campaign


def test_frequency_cap_exact_equality_blocks(api):
    """PRD §3.10: "The viewer is eligible to be served only when this count
    is strictly less than `frequency_cap_per_viewer`; a count exactly equal
    to the cap blocks the serve with `ERR_FREQUENCY_CAP_EXCEEDED`
    (HTTP 422). The boundary is pinned: equality blocks."

    Cap 2: serves 1 and 2 succeed; serve 3 fails.

    Design: Difficulty/boundary_precision_check/frequency_cap_exact_equality_blocks
    """
    _, slot, _ = _servable_slot(api, cap=2)
    viewer = create_viewer()
    r1 = api.serve_ad_slot(slot["id"], {"viewer_id": viewer["id"]}, AD)
    validate_success(r1, expected_status=201)
    r2 = api.serve_ad_slot(slot["id"], {"viewer_id": viewer["id"]}, AD)
    validate_success(r2, expected_status=201)
    r3 = api.serve_ad_slot(slot["id"], {"viewer_id": viewer["id"]}, AD)
    validate_error(r3, ApiErrorId.ERR_FREQUENCY_CAP_EXCEEDED)


def test_frequency_cap_counts_per_viewer_independently(api):
    """PRD §3.10: "Count the impressions for the `(campaign_id, viewer_id)`
    pair whose `served_at` falls in the half-open interval from
    `window_start` (inclusive) to now (exclusive)."

    The cap is per (campaign, viewer): a second viewer is unaffected by the
    first viewer reaching the cap.

    Design: Difficulty/boundary_precision_check/frequency_cap_exact_equality_blocks
    """
    _, slot, _ = _servable_slot(api, cap=1)
    viewer_a = create_viewer()
    viewer_b = create_viewer()
    validate_success(api.serve_ad_slot(slot["id"], {"viewer_id": viewer_a["id"]}, AD), expected_status=201)
    blocked = api.serve_ad_slot(slot["id"], {"viewer_id": viewer_a["id"]}, AD)
    validate_error(blocked, ApiErrorId.ERR_FREQUENCY_CAP_EXCEEDED)
    # Different viewer, same campaign+slot: still eligible.
    ok = api.serve_ad_slot(slot["id"], {"viewer_id": viewer_b["id"]}, AD)
    validate_success(ok, expected_status=201)


def test_serve_reports_frequency_cap_error_at_cap_one(api):
    """PRD §3.8: "Serve runs the frequency-cap check (§3.10) and rejects with
    `ERR_FREQUENCY_CAP_EXCEEDED` (HTTP 422) when the cap has been reached."

    With cap 1, the first serve succeeds and the immediate repeat fails.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_pair_on_serve
    """
    _, slot, campaign = _servable_slot(api, cap=1)
    viewer = create_viewer()
    validate_success(api.serve_ad_slot(slot["id"], {"viewer_id": viewer["id"]}, AD), expected_status=201)
    resp = api.serve_ad_slot(slot["id"], {"viewer_id": viewer["id"]}, AD)
    validate_error(resp, ApiErrorId.ERR_FREQUENCY_CAP_EXCEEDED)


def test_serve_success_records_impression_fields(api):
    """PRD §3.8: "A successful serve records `campaign_id`, `viewer_id`,
    `slot_id`, `served_at` set to the current logical time, `revenue_cents`
    computed per §3.10, and `fill_source` set to `NATIONAL` for a
    `NATIONAL` slot or `LOCAL_INSERTION` for a `LOCAL` slot."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_pair_on_serve
    """
    window, slot, campaign = _servable_slot(api, cap=5)
    viewer = create_viewer()
    impression = validate_success(
        api.serve_ad_slot(slot["id"], {"viewer_id": viewer["id"]}, AD), expected_status=201
    )
    assert impression["campaign_id"] == campaign["id"]
    assert impression["viewer_id"] == viewer["id"]
    assert impression["slot_id"] == slot["id"]
    assert impression["fill_source"] == "NATIONAL"
    assert impression["served_at"] == "2026-09-13T18:00:00Z"
