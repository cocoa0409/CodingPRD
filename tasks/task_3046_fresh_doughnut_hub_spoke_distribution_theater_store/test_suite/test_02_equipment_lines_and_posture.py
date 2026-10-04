"""Equipment line lifecycle cascades: maintenance cancel cascade, decommission
door-suspension cascade, and ops-run checkpoint behavior."""
from test_helpers import (
    TEST_USERS,
    assert_production_batch,
    get_success_data,
    validate_success,
)
from test_helpers.fixtures import (
    commit_batch,
    create_batch,
    create_door,
    create_hub,
    create_network,
    setup_hub_with_line,
)

NA = TEST_USERS["network_admin_headers"]
HM = TEST_USERS["hub_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/maintenance_start_cancels_batch_recomputes_hub_then_posture
# ---------------------------------------------------------------------------

def test_maintenance_start_cancels_committed_batch_and_drains_hub(api):
    """PRD §3.2: "Starting maintenance fires a broad cascade: every batch
    `SCHEDULED` on the line for today is moved to `CANCELLED`; each such
    batch that had been `COMMITTED` decrements the hub's
    `committed_dozens_today` by its `planned_dozens`; and the network's
    posture is recomputed."

    Design: Difficulty/transitive_cascade/maintenance_start_cancels_batch_recomputes_hub_then_posture
    """
    network, hub, line = setup_hub_with_line(
        network_code="N7", hub_code="H7", region="R7", capacity=500,
        line_overrides={"service_interval_hours": 100},
    )
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=100)
    commit_batch(network["id"], hub["id"], batch["id"])

    mid = validate_success(
        api.get_hub(network["id"], hub["id"], NA)
    )
    assert mid["committed_dozens_today"] == 100

    resp = api.start_maintenance(network["id"], hub["id"], line["id"], HM)
    line_after = validate_success(resp)
    assert line_after["line_status"] == "MAINTENANCE"

    batch_after = validate_success(api.get_batch(network["id"], hub["id"], batch["id"], HM))
    assert_production_batch(batch_after)
    assert batch_after["batch_status"] == "CANCELLED", (
        "link A->B: the committed batch must be cancelled by the cascade"
    )

    hub_after = validate_success(api.get_hub(network["id"], hub["id"], NA))
    assert hub_after["committed_dozens_today"] == 0, (
        "link B->C: cancel decrements committed_dozens_today by planned_dozens (100 - 100)"
    )


def test_maintenance_start_posture_suspends_when_last_line_goes_down(api):
    """PRD §2.6: "If any hub in the network has zero equipment lines in
    `OPERATIONAL` or `DEGRADED` status, the posture is `SUSPENDED`."
    PRD §3.2: "Starting maintenance fires a broad cascade ... and the
    network's posture is recomputed."

    Design: Difficulty/transitive_cascade/maintenance_start_cancels_batch_recomputes_hub_then_posture
    """
    network, hub, line = setup_hub_with_line(
        network_code="N7B", hub_code="H7B", region="R7", capacity=500,
        line_overrides={"service_interval_hours": 100},
    )
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=100)
    commit_batch(network["id"], hub["id"], batch["id"])

    validate_success(api.start_maintenance(network["id"], hub["id"], line["id"], HM))

    network_after = validate_success(api.get_network(network["id"], NA))
    assert network_after["network_posture"] == "SUSPENDED", (
        "link C->D: the hub's only line entered MAINTENANCE, so no OPERATIONAL/"
        "DEGRADED line remains and posture must be SUSPENDED"
    )


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/cascading_side_effects_decommission_suspends_doors
# ---------------------------------------------------------------------------

def test_decommission_last_line_suspends_supplied_doors(api):
    """PRD §3.2: "if the decommission leaves the hub with no remaining line
    in `OPERATIONAL` or `DEGRADED`, every door supplied exclusively by that
    hub flips to `SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_decommission_suspends_doors
    """
    network, hub, line = setup_hub_with_line(
        network_code="NDC", hub_code="HDC", region="RDC", capacity=500,
        line_overrides={"service_interval_hours": 100},
    )
    door1 = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE", region="RDC", hub_id=hub["id"]
    )
    door2 = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region="RDC")

    resp = api.decommission_line(network["id"], hub["id"], line["id"], HM)
    line_after = validate_success(resp)
    assert line_after["line_status"] == "DECOMMISSIONED"

    door1_after = validate_success(api.get_door(network["id"], door1["id"], NA))
    assert door1_after["door_status"] == "SUSPENDED", (
        "supplied door must suspend when its hub loses its last working line"
    )
    door2_after = validate_success(api.get_door(network["id"], door2["id"], NA))
    assert door2_after["door_status"] == "ACTIVE", (
        "self-supplied theater door must be unaffected by another hub's decommission"
    )


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/ops_run_checkpoint_expires_stale_scheduled_batches
# ---------------------------------------------------------------------------

def test_ops_run_expires_stale_scheduled_batches(api):
    """PRD §3.9: "Each checkpoint ... auto-cancels any `SCHEDULED` batches
    whose `production_date` has fallen in the past ... advances the network's
    `ops_run_index` by one ... The checkpoint reports back the new
    `ops_run_index`, the `expired_batch_count`, the `expired_order_count`,
    and the recomputed `network_posture`."

    Design: Corner/cross_cutting_complexity_layers/ops_run_checkpoint_expires_stale_scheduled_batches
    """
    network, hub, line = setup_hub_with_line(
        network_code="NOR", hub_code="HOR", region="ROR", capacity=500,
        line_overrides={"line_kind": "GLAZE_WATERFALL", "rated_dozens_per_hour": 80,
                        "service_interval_hours": 100},
    )
    batch_old = create_batch(
        network["id"], hub["id"], line["id"], planned_dozens=40,
        production_date="2026-09-01",
    )
    batch_today = create_batch(
        network["id"], hub["id"], line["id"], planned_dozens=40,
        production_date="2026-09-02",
    )
    get_success_data(api.set_clock("2026-09-02T00:00:00Z", NA))

    resp = api.run_ops_run(network["id"], NA)
    data = validate_success(resp, expected_status=201)
    assert data["expired_batch_count"] == 1
    assert data["ops_run_index"] == 1

    old_after = validate_success(api.get_batch(network["id"], hub["id"], batch_old["id"], HM))
    assert old_after["batch_status"] == "CANCELLED", "stale SCHEDULED batch must be swept"
    today_after = validate_success(api.get_batch(network["id"], hub["id"], batch_today["id"], HM))
    assert today_after["batch_status"] == "SCHEDULED", "same-day batch must survive"
