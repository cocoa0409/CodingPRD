"""Production batches: capacity gating, line state dependencies, OCC on
commit, invalid transitions, and the commit/cancel capacity invariant."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.fixtures import (
    commit_batch,
    create_batch,
    create_completed_batch,
    hub_version,
    setup_hub_with_line,
)

NA = TEST_USERS["network_admin_headers"]
HM = TEST_USERS["hub_manager_headers"]


# ---------------------------------------------------------------------------
# Corner/state_machines/batch_invalid_transition_start_from_scheduled
# ---------------------------------------------------------------------------

def test_start_scheduled_batch_rejected(api):
    """PRD §3.3: "Starting a committed batch moves it to `RUNNING`" — start is
    defined only from `COMMITTED`; "the batch starts in `SCHEDULED`".
    PRD §2.10: "state admissibility of the target resource for the requested
    transition (`ERR_INVALID_STATE`...)".

    Design: Corner/state_machines/batch_invalid_transition_start_from_scheduled
    """
    network, hub, line = setup_hub_with_line(network_code="NS", hub_code="HS", region="RS")
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=50)
    assert batch["batch_status"] == "SCHEDULED"

    resp = api.start_batch(network["id"], hub["id"], batch["id"], HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_batch(network["id"], hub["id"], batch["id"], HM))
    assert after["batch_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner/state_machines/terminal_batch_rejects_complete
# ---------------------------------------------------------------------------

def test_complete_cancelled_batch_rejected(api):
    """PRD §2.10: "a transition attempted against a resource already in a
    terminal state is rejected with `ERR_ALREADY_TERMINAL`, also HTTP 409";
    `ERR_INVALID_STATE` (409) is also admissible here because both are state
    rejections at the same precedence rung.
    PRD §3.3: "A batch in `SCHEDULED` or `COMMITTED` may instead be cancelled
    outright".

    Design: Corner/state_machines/terminal_batch_rejects_complete
    """
    network, hub, line = setup_hub_with_line(
        network_code="NT", hub_code="HT", region="RT",
        line_overrides={"line_kind": "GLAZE_WATERFALL", "rated_dozens_per_hour": 80},
    )
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=40)
    validate_success(api.cancel_batch(network["id"], hub["id"], batch["id"], HM))

    resp = api.complete_batch(
        network["id"], hub["id"], batch["id"], {"produced_dozens": 40}, HM
    )
    actual = validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE]
    )
    assert actual in ("ERR_ALREADY_TERMINAL", "ERR_INVALID_STATE")

    after = validate_success(api.get_batch(network["id"], hub["id"], batch["id"], HM))
    assert after["batch_status"] == "CANCELLED", "no side effects may fire on a terminal batch"


# ---------------------------------------------------------------------------
# Corner/validations/batch_commit_over_capacity_rejected
# ---------------------------------------------------------------------------

def test_batch_commit_over_capacity_rejected(api):
    """PRD §3.3: "Commit is permitted only when ... the hub's
    `committed_dozens_today` plus the batch's `planned_dozens` does not
    exceed the hub's `daily_capacity_dozens` (violations are rejected with
    `ERR_CAPACITY_EXCEEDED`)".

    Design: Corner/validations/batch_commit_over_capacity_rejected
    """
    network, hub, line = setup_hub_with_line(
        network_code="NCP", hub_code="HCP", region="RCP", capacity=100,
        line_overrides={"rated_dozens_per_hour": 200},
    )
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=150)

    resp = api.commit_batch(
        network["id"], hub["id"], batch["id"],
        {"expected_hub_version": hub_version(network["id"], hub["id"])}, HM,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    after = validate_success(api.get_batch(network["id"], hub["id"], batch["id"], HM))
    assert after["batch_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner/validations/line_busy_second_batch_start_rejected
# ---------------------------------------------------------------------------

def test_line_busy_second_batch_start_rejected(api):
    """PRD §3.3: "no other batch may be `RUNNING` on the same line — a second
    start on a busy line is rejected with `ERR_LINE_BUSY` (HTTP 409)."

    Design: Corner/validations/line_busy_second_batch_start_rejected
    """
    network, hub, line = setup_hub_with_line(
        network_code="NLB", hub_code="HLB", region="RLB", capacity=500,
        line_overrides={"service_interval_hours": 500},
    )
    batch1 = create_batch(network["id"], hub["id"], line["id"], planned_dozens=50)
    commit_batch(network["id"], hub["id"], batch1["id"])
    validate_success(api.start_batch(network["id"], hub["id"], batch1["id"], HM))

    batch2 = create_batch(network["id"], hub["id"], line["id"], planned_dozens=50)
    commit_batch(network["id"], hub["id"], batch2["id"])

    resp = api.start_batch(network["id"], hub["id"], batch2["id"], HM)
    validate_error(resp, ApiErrorId.ERR_LINE_BUSY)

    after = validate_success(api.get_batch(network["id"], hub["id"], batch2["id"], HM))
    assert after["batch_status"] == "COMMITTED"


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_stale_hub_version_on_batch_commit
# ---------------------------------------------------------------------------

def test_occ_stale_hub_version_on_batch_commit(api):
    """PRD §2.9: "Committing a production batch requires the request to carry
    `expected_hub_version` holding the client's last observed `version` of
    the parent hub. Because every batch commit, cancel, or completion
    rewrites the hub's `committed_dozens_today`, a stale hub view would run
    the capacity check against stale data; a mismatch with the hub's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_hub_version_on_batch_commit
    """
    network, hub, line = setup_hub_with_line(network_code="NOC", hub_code="HOC", region="ROC")
    batch1 = create_batch(network["id"], hub["id"], line["id"], planned_dozens=50)
    batch2 = create_batch(network["id"], hub["id"], line["id"], planned_dozens=50)
    v0 = hub_version(network["id"], hub["id"])

    # First commit succeeds against the observed version and advances it.
    resp1 = api.commit_batch(
        network["id"], hub["id"], batch1["id"], {"expected_hub_version": v0}, HM
    )
    validate_success(resp1)

    # Second commit replays the now-stale version.
    resp2 = api.commit_batch(
        network["id"], hub["id"], batch2["id"], {"expected_hub_version": v0}, HM
    )
    validate_error(resp2, ApiErrorId.ERR_STALE_VERSION)

    batch2_after = validate_success(api.get_batch(network["id"], hub["id"], batch2["id"], HM))
    assert batch2_after["batch_status"] == "SCHEDULED"

    hub_after = validate_success(api.get_hub(network["id"], hub["id"], NA))
    assert hub_after["committed_dozens_today"] == 50, "only the first commit may apply"


# ---------------------------------------------------------------------------
# Corner/consistency_model/immediate_consistency_committed_dozens_visible_in_response_and_read
# ---------------------------------------------------------------------------

def test_commit_immediately_visible_in_response_and_read(api):
    """PRD §3.3: "A successful commit adds `planned_dozens` to
    `committed_dozens_today` and bumps both the hub's and the batch's
    `version`."
    PRD §3.1: "this figure is recomputed on every batch commit, cancel, or
    completion".

    Design: Corner/consistency_model/immediate_consistency_committed_dozens_visible_in_response_and_read
    """
    network, hub, line = setup_hub_with_line(network_code="NIC", hub_code="HIC", region="RIC")
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=60)

    resp = api.commit_batch(
        network["id"], hub["id"], batch["id"],
        {"expected_hub_version": hub_version(network["id"], hub["id"])}, HM,
    )
    committed = validate_success(resp)
    assert committed["batch_status"] == "COMMITTED"

    hub_after = validate_success(api.get_hub(network["id"], hub["id"], NA))
    assert hub_after["committed_dozens_today"] == 60, (
        "committed_dozens_today must reflect the commit with no reconciliation lag"
    )


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/commit_then_cancel_conserves_hub_capacity
# ---------------------------------------------------------------------------

def test_commit_then_cancel_restores_committed_dozens(api):
    """PRD §3.3: "A successful commit adds `planned_dozens` to
    `committed_dozens_today`" and "a cancelled `COMMITTED` batch decrements
    `committed_dozens_today` by its planned size."

    Design: Difficulty/compensating_invariant/commit_then_cancel_conserves_hub_capacity
    """
    network, hub, line = setup_hub_with_line(network_code="N17", hub_code="H17", region="R17")
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=100)

    validate_success(
        api.commit_batch(
            network["id"], hub["id"], batch["id"],
            {"expected_hub_version": hub_version(network["id"], hub["id"])}, HM,
        )
    )
    mid = validate_success(api.get_hub(network["id"], hub["id"], NA))
    assert mid["committed_dozens_today"] == 100

    validate_success(api.cancel_batch(network["id"], hub["id"], batch["id"], HM))
    after = validate_success(api.get_hub(network["id"], hub["id"], NA))
    assert after["committed_dozens_today"] == 0, (
        "the compensating cancel must restore the pre-commit committed_dozens_today"
    )
    assert after["daily_capacity_dozens"] == 500


def test_commit_then_cancel_leaves_batch_cancelled(api):
    """PRD §3.3: "A batch in `SCHEDULED` or `COMMITTED` may instead be
    cancelled outright — by the `HubManager` or by the maintenance cascade —
    and a cancelled `COMMITTED` batch decrements `committed_dozens_today` by
    its planned size."

    Design: Difficulty/compensating_invariant/commit_then_cancel_conserves_hub_capacity
    """
    network, hub, line = setup_hub_with_line(network_code="N17B", hub_code="H17B", region="R17")
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=100)
    commit_batch(network["id"], hub["id"], batch["id"])

    resp = api.cancel_batch(network["id"], hub["id"], batch["id"], HM)
    cancelled = validate_success(resp)
    assert cancelled["batch_status"] == "CANCELLED"

    after = validate_success(api.get_batch(network["id"], hub["id"], batch["id"], HM))
    assert after["batch_status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/batch_commit_blocked_when_line_in_maintenance
# ---------------------------------------------------------------------------

def test_batch_commit_blocked_when_line_in_maintenance(api):
    """PRD §3.3: "Commit is permitted only when the batch's line is
    `OPERATIONAL` or `DEGRADED`".
    PRD §2.10: "state admissibility of the target resource for the requested
    transition (`ERR_INVALID_STATE`...)".

    Design: Difficulty/cross_entity_state_dependency/batch_commit_blocked_when_line_in_maintenance
    """
    network, hub, line = setup_hub_with_line(network_code="N13", hub_code="H13", region="R13")
    validate_success(api.start_maintenance(network["id"], hub["id"], line["id"], HM))
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=50)

    resp = api.commit_batch(
        network["id"], hub["id"], batch["id"],
        {"expected_hub_version": hub_version(network["id"], hub["id"])}, HM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_batch(network["id"], hub["id"], batch["id"], HM))
    assert after["batch_status"] == "SCHEDULED"


def test_batch_commit_blocked_when_line_in_maintenance_does_not_touch_hub(api):
    """PRD §3.3: "Commit is permitted only when the batch's line is
    `OPERATIONAL` or `DEGRADED`" — a rejected commit must not add to
    `committed_dozens_today`: "A successful commit adds `planned_dozens` to
    `committed_dozens_today`".

    Design: Difficulty/cross_entity_state_dependency/batch_commit_blocked_when_line_in_maintenance
    """
    network, hub, line = setup_hub_with_line(network_code="N13B", hub_code="H13B", region="R13")
    validate_success(api.start_maintenance(network["id"], hub["id"], line["id"], HM))
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=50)
    before = validate_success(api.get_hub(network["id"], hub["id"], NA))

    resp = api.commit_batch(
        network["id"], hub["id"], batch["id"],
        {"expected_hub_version": before["version"]}, HM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_hub(network["id"], hub["id"], NA))
    assert after["committed_dozens_today"] == before["committed_dozens_today"] == 0
