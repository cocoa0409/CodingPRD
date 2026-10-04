"""Network posture: shortfall degradation confirmed by the ops-run
checkpoint's full recompute."""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    validate_success,
)
from test_helpers.fixtures import (
    commit_batch,
    create_batch,
    setup_hub_with_line,
)

NA = TEST_USERS["network_admin_headers"]
HM = TEST_USERS["hub_manager_headers"]


def _run_shortfall_pair(api, network_code):
    """Two batches each produced 50 vs planned 100 (yield 0.5 < 0.85) ->
    both SHORTFALL today. Returns (network, hub, [b1, b2])."""
    network, hub, line = setup_hub_with_line(
        network_code=network_code, hub_code="H2", region="R2", capacity=500,
        line_overrides={"line_kind": "GLAZE_WATERFALL", "service_interval_hours": 200},
    )
    batches = []
    for _ in range(2):
        batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=100)
        commit_batch(network["id"], hub["id"], batch["id"])
        get_success_data(api.start_batch(network["id"], hub["id"], batch["id"], HM))
        completed = get_success_data(
            api.complete_batch(network["id"], hub["id"], batch["id"], {"produced_dozens": 50}, HM)
        )
        batches.append(completed)
    return network, hub, batches


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/network_posture_incremental_vs_opsrun_projection
# ---------------------------------------------------------------------------

def test_two_shortfalls_degrade_posture_at_ops_run(api):
    """PRD §2.6: "Otherwise, if at least two production batches have entered
    `SHORTFALL` today, or if any door in the network is `SUSPENDED`, the
    posture is `DEGRADED`."
    PRD §3.9: "Each checkpoint performs a full posture recompute from scratch
    rather than an incremental update ... advances the network's
    `ops_run_index` by one ... The checkpoint reports back the new
    `ops_run_index`, the `expired_batch_count`, the `expired_order_count`,
    and the recomputed `network_posture`."

    Design: Difficulty/dual_variant_calc/network_posture_incremental_vs_opsrun_projection
    """
    network, hub, batches = _run_shortfall_pair(api, "N2")
    for batch in batches:
        assert batch["batch_status"] == "SHORTFALL", (
            "yield 50/100 == 0.5 < 0.85 minimum yield rate -> SHORTFALL"
        )

    resp = api.run_ops_run(network["id"], NA)
    data = validate_success(resp, expected_status=201)
    assert data["network_posture"] == "DEGRADED", (
        "full recompute at the checkpoint confirms DEGRADED from two shortfalls"
    )
    assert data["ops_run_index"] == 1

    after = validate_success(api.get_network(network["id"], NA))
    assert after["network_posture"] == "DEGRADED"
    assert after["ops_run_index"] == 1


def test_shortfall_batches_recorded_then_checkpoint_advances_index(api):
    """PRD §3.3: "If produced dozens fall short of the 0.85 yield floor, the
    batch lands in `SHORTFALL` instead".
    PRD §3.9: "advances the network's `ops_run_index` by one".

    Design: Difficulty/dual_variant_calc/network_posture_incremental_vs_opsrun_projection
    """
    network, hub, batches = _run_shortfall_pair(api, "N2B")
    for batch in batches:
        fetched = validate_success(api.get_batch(network["id"], hub["id"], batch["id"], HM))
        assert fetched["batch_status"] == "SHORTFALL"

    resp = api.run_ops_run(network["id"], NA)
    data = validate_success(resp, expected_status=201)
    assert data["ops_run_index"] == 1
    assert data["network_posture"] == "DEGRADED"
