"""Pick-task lifecycle and state-machine tests (queue B: state_machines)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    set_clock,
    setup_stocked_station,
    create_order_with_line,
    setup_dispatched_task,
    get_pick_task,
    get_drive_unit,
    get_pod,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]
SUPERVISOR = TEST_USERS["floor_supervisor_headers"]


def _setup_created_task():
    """Stocked station + order + a CREATED pick task (not sequenced)."""
    env = setup_stocked_station(quantity=5)
    order, line = create_order_with_line(env["sku"]["id"], quantity=1)
    task = validate_success(
        api_client.create_pick_task(
            {
                "order_id": order["id"],
                "line_id": line["id"],
                "pod_id": env["pod"]["id"],
                "station_id": env["station"]["id"],
                "quantity": 1,
            },
            FLOW,
        ),
        expected_status=201,
    )
    env.update({"order": order, "line": line, "task": task})
    return env


def test_pick_task_terminal_cancelled_rejects_dispatch(api):
    """PRD §2.6: "State legality — the target entity is in a status from which
    the requested transition is defined (`ERR_INVALID_STATE`, 409)."
    PRD §3.3: "A `FlowController` may cancel a task in `CREATED` or `QUEUED`."

    Design: Corner/state_machines/pick_task_terminal_cancelled_rejects_dispatch
    """
    env = _setup_created_task()
    cancelled = validate_success(api.cancel_pick_task(env["task"]["id"], FLOW))
    assert cancelled["status"] == "CANCELLED"
    resp = api.dispatch_pick_task(env["task"]["id"], FLOW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_pick_task_initial_state_created(api):
    """PRD §3.3: "A task is born `CREATED` with no `sequence_index` and no
    `drive_unit_id`."

    Design: Corner/state_machines/pick_task_initial_state_created
    """
    env = _setup_created_task()
    task = env["task"]
    assert task["status"] == "CREATED", f"expected CREATED, got {task['status']}"
    assert task.get("sequence_index") is None, (
        f"sequence_index must be null while CREATED, got {task.get('sequence_index')}"
    )


def test_pick_task_est_cost_null_until_dispatch(api):
    """PRD §3.3: "A task is born `CREATED` with no `sequence_index` and no
    `drive_unit_id`."
    PRD §3.3: "the planning variant of the travel-cost estimate is written to
    the task's `est_cost`." (at dispatch)

    Design: Corner/entities/pick_task_est_cost_computed_at_dispatch
    """
    env = _setup_created_task()
    task = env["task"]
    assert task["status"] == "CREATED"
    assert task.get("est_cost") is None, (
        f"est_cost must be null at creation, got {task.get('est_cost')}"
    )


def test_pod_quarantined_on_stranded_robot(api):
    """PRD §3.6: "Reporting a `STRANDED_ROBOT` against an `EN_ROUTE` unit
    cascades immediately: the unit becomes `STRANDED`, its in-flight task
    becomes `FAILED` (station `queue_length` decrements, the pod becomes
    `QUARANTINED`, and the slot's `quantity_reserved` and SKU's
    `total_units_reserved` release the task's quantity)."

    Design: Corner/state_machines/pod_quarantined_on_stranded_robot
    """
    env = setup_dispatched_task()
    du = get_drive_unit(env["du"]["id"])
    assert du["status"] == "EN_ROUTE", f"precondition: unit EN_ROUTE, got {du['status']}"
    resp = api.create_floor_exception(
        {"kind": "STRANDED_ROBOT", "zone_id": env["z1"]["id"],
         "drive_unit_id": env["du"]["id"]},
        SUPERVISOR,
    )
    validate_success(resp, expected_status=201)
    assert get_drive_unit(env["du"]["id"])["status"] == "STRANDED"
    assert get_pick_task(env["task"]["id"])["status"] == "FAILED"
    assert get_pod(env["pod"]["id"])["status"] == "QUARANTINED"


def test_release_failed_to_draft_cycle(api):
    """PRD §3.7: "An `outcome` of `FAIL` requires non-empty `defect_notes`,
    moves the release to `FAILED`, and sets `safety_check_passed` false; the
    `ReleaseEngineer` may then revise the release back to `DRAFT`."

    Design: Corner/state_machines/release_failed_to_draft_cycle
    """
    from test_helpers import setup_release_in_status

    release = setup_release_in_status("FAILED")
    assert release["status"] == "FAILED"
    revised = validate_success(
        api.revise_software_release(release["id"], TEST_USERS["release_engineer_headers"])
    )
    assert revised["status"] == "DRAFT", (
        f"revise must return release to DRAFT, got {revised['status']}"
    )
