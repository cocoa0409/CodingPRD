"""Uptime prediction: the 720-hour window, the optimistic/conservative dual
variants, and the parts recommendation keyed off the conservative score."""

import pytest

from test_helpers import (
    get_uptime,
    ingest_batch,
    read_machine,
    set_clock,
    setup_activated_machine,
    setup_connected_machine,
)


def test_uptime_window_excludes_records_older_than_720_hours(api):
    """PRD section 3.8: "It looks at the trailing 720 hours — reported as
    `window_hours` — aligned to whole-hour buckets" and "The parts
    recommendation reads the rounded conservative score against two thresholds:
    below 70.0 the recommendation is `OVERHAUL_KIT`". A batch wholly before
    the window contributes nothing: both scores are 0.0.

    Design: Corner/calculations/uptime_window_excludes_records_older_than_720_hours
    """
    ctx = setup_connected_machine(api)
    machine_id = ctx["machine"]["id"]
    set_clock(api, "2026-10-01T00:00:00Z")
    ingest_batch(ctx, api, machine_id, batch_id="b-old",
                 start_hour_iso="2026-08-15T00:00:00Z", hour_count=100,
                 payload_mb=10)

    uptime = get_uptime(ctx, api, machine_id)
    assert uptime["window_hours"] == 720
    assert uptime["filled_hours"] == 0
    assert uptime["conservative_score"] == pytest.approx(0.0)
    assert uptime["optimistic_score"] == pytest.approx(0.0)
    assert uptime["parts_recommendation"] == "OVERHAUL_KIT"


def test_uptime_optimistic_vs_conservative_scores(api):
    """PRD section 3.8: "The conservative score divides those filled hours by
    the 720-hour window, multiplies by 100, and rounds half-up to one decimal"
    and "The optimistic score bridges gaps: an empty bucket counts as covered
    when its immediately preceding bucket is filled, the number of such buckets
    is `bridged_hours`, and the optimistic score is filled plus bridged over
    720, times 100, rounded half-up to one decimal — always at least the
    conservative score for identical data." 600 contiguous filled buckets at
    the 2026-10-01 clock: conservative 83.3, optimistic 83.5 (exactly one
    bucket bridged).

    Design: Difficulty/dual_variant_calc/uptime_prediction_optimistic_vs_conservative
    """
    ctx = setup_activated_machine(api)
    machine_id = ctx["machine"]["id"]
    ingest_batch(ctx, api, machine_id, batch_id="b-win",
                 start_hour_iso="2026-09-01T00:00:00Z", hour_count=600,
                 payload_mb=100)
    set_clock(api, "2026-10-01T00:00:00Z")

    uptime = get_uptime(ctx, api, machine_id)
    assert uptime["window_hours"] == 720
    assert uptime["filled_hours"] == 600
    assert uptime["bridged_hours"] == 1
    assert uptime["conservative_score"] == pytest.approx(83.3)
    assert uptime["optimistic_score"] == pytest.approx(83.5)


def test_uptime_parts_recommendation_keys_off_conservative(api):
    """PRD section 3.8: "The parts recommendation reads the rounded
    conservative score against two thresholds: below 70.0 the recommendation
    is `OVERHAUL_KIT`; at least 70.0 but below 85.0 it is `SERVICE_KIT`; at
    85.0 or above it is `NONE`." — the conservative 83.3 (not the optimistic
    83.5) drives the label, and the machine that accepted its first batch is
    `IN_SERVICE` ("the first accepted telemetry batch flips an `ACTIVATED`
    machine to `IN_SERVICE`", PRD section 3.1).

    Design: Difficulty/dual_variant_calc/uptime_prediction_optimistic_vs_conservative
    """
    ctx = setup_activated_machine(api)
    machine_id = ctx["machine"]["id"]
    ingest_batch(ctx, api, machine_id, batch_id="b-win",
                 start_hour_iso="2026-09-01T00:00:00Z", hour_count=600,
                 payload_mb=100)
    set_clock(api, "2026-10-01T00:00:00Z")

    uptime = get_uptime(ctx, api, machine_id)
    assert uptime["conservative_score"] == pytest.approx(83.3)
    assert uptime["parts_recommendation"] == "SERVICE_KIT"
    machine = read_machine(ctx, api, machine_id)
    assert machine["lifecycle_status"] == "IN_SERVICE"
