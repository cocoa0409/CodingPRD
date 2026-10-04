"""Queue A (difficulty) translations: validation-priority pairs and
boundary precision.

Covers rule_id priority_pair_validation_conflict:
- state_vs_safety_on_promote_with_open_exception (2 tests)
Covers rule_id boundary_precision_check:
- station_queue_full_at_exactly_max_queue (2 tests)
- order_cutoff_strict_inequality (2 tests)
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    validate_success,
    get_success_data,
    ApiErrorId,
    set_clock,
    create_zone,
    create_sku,
    create_pick_station,
    create_pod,
    create_order_with_line,
    create_pick_task_payload,
    create_customer_order_payload,
    create_software_release_payload,
    create_floor_exception_payload,
    get_station_version,
    get_station,
    get_pick_task,
    stow_units,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]
SUPERVISOR = TEST_USERS["floor_supervisor_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
ENGINEER = TEST_USERS["release_engineer_headers"]


def _setup_draft_release_with_open_exception():
    """Zone with an OPEN (never triaged) floor exception; release in DRAFT."""
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=2)
    get_success_data(
        api_client.create_floor_exception(
            create_floor_exception_payload(zone["id"], kind="BLOCKED_PATH"),
            SUPERVISOR,
        )
    )
    release = get_success_data(
        api_client.create_software_release(
            create_software_release_payload(release_code="9.9.9"), ENGINEER
        )
    )
    return zone, release


def test_promote_draft_release_with_open_exception_fails_state_first(api):
    """PRD §2.6: "Requests are validated in a fixed priority order, and the
    first failing check determines the error returned."
    PRD §2.6: "5. **State legality** — the target entity is in a status from
    which the requested transition is defined (`ERR_INVALID_STATE`, 409)."
    PRD §2.6: "6. **Safety interlocks** — no FROZEN-zone entry, open-exception
    gating, stranded-robot, or segregation-of-duties violation
    (`ERR_SAFETY_INTERLOCK`, 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_promote_with_open_exception
    """
    _zone, release = _setup_draft_release_with_open_exception()
    resp = api.promote_software_release(release["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_promote_draft_release_with_open_exception_http_409(api):
    """PRD §2.6: "5. **State legality** — the target entity is in a status from
    which the requested transition is defined (`ERR_INVALID_STATE`, 409)."
    PRD §2.6: "Requests are validated in a fixed priority order, and the first
    failing check determines the error returned."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_promote_with_open_exception
    """
    _zone, release = _setup_draft_release_with_open_exception()
    resp = api.promote_software_release(release["id"], ADMIN)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409, f"ERR_INVALID_STATE must be HTTP 409, got {resp.status_code}"


def _setup_full_station(max_queue=2, tasks_sequenced=2, sku_qty=10):
    """Stocked station whose queue is filled to max_queue. Returns
    (env, sku) where env holds zone/pod/station."""
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=2)
    pod = create_pod(zone["id"], pod_code="P1", slot_capacity=5)
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    station = create_pick_station(zone["id"], station_code="ST1", max_queue=max_queue)
    stow_units(sku, quantity=sku_qty)
    tasks = []
    for i in range(tasks_sequenced):
        order, line = create_order_with_line(sku["id"], quantity=1)
        task = get_success_data(
            api_client.create_pick_task(
                create_pick_task_payload(
                    order["id"], line["id"], pod["id"], station["id"], quantity=1
                ),
                FLOW,
            )
        )
        tasks.append(
            get_success_data(
                api_client.sequence_pick_task(
                    task["id"], get_station_version(station["id"]), FLOW
                )
            )
        )
    return {"zone": zone, "pod": pod, "sku": sku, "station": station, "tasks": tasks}


def test_station_queue_at_max_rejects_next_sequence(api):
    """PRD §3.3: "Sequencing is legal only while the station is `OPEN` with
    `queue_length` below `max_queue`."
    PRD §2.6: "9. **Capacity** — station queue length below `max_queue` on
    sequencing (`ERR_CAPACITY_EXCEEDED`, 422)."

    Design: Difficulty/boundary_precision_check/station_queue_full_at_exactly_max_queue
    """
    env = _setup_full_station(max_queue=2, tasks_sequenced=2)
    station_now = get_station(env["station"]["id"])
    assert station_now["queue_length"] == 2, (
        f"precondition: queue full at max_queue=2, got {station_now['queue_length']}"
    )
    order, line = create_order_with_line(env["sku"]["id"], quantity=1)
    task3 = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                order["id"], line["id"], env["pod"]["id"],
                env["station"]["id"], quantity=1,
            ),
            FLOW,
        )
    )
    resp = api.sequence_pick_task(
        task3["id"], get_station_version(env["station"]["id"]), FLOW
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_station_queue_full_rejection_leaves_task_created(api):
    """PRD §3.3: "Sequencing is legal only while the station is `OPEN` with
    `queue_length` below `max_queue`."
    PRD §2.6: "9. **Capacity** — station queue length below `max_queue` on
    sequencing (`ERR_CAPACITY_EXCEEDED`, 422)."

    Design: Difficulty/boundary_precision_check/station_queue_full_at_exactly_max_queue
    """
    env = _setup_full_station(max_queue=2, tasks_sequenced=2)
    order, line = create_order_with_line(env["sku"]["id"], quantity=1)
    task3 = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                order["id"], line["id"], env["pod"]["id"],
                env["station"]["id"], quantity=1,
            ),
            FLOW,
        )
    )
    resp = api.sequence_pick_task(
        task3["id"], get_station_version(env["station"]["id"]), FLOW
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    assert resp.status_code == 422
    task_after = get_pick_task(task3["id"])
    assert task_after["status"] == "CREATED", (
        f"rejected sequence must leave the task CREATED, got {task_after['status']}"
    )


def test_order_cutoff_equal_clock_not_missed(api):
    """PRD §2.4: "An order still in `RECEIVED` whose `cutoff_at` equals the
    current logical clock exactly is **not** yet missed; only a clock strictly
    later than `cutoff_at` triggers `CUTOFF_MISSED`."

    Design: Difficulty/boundary_precision_check/order_cutoff_strict_inequality
    """
    set_clock("2026-09-01T08:00:00Z")
    create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                max_human_occupancy=2)
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    order = get_success_data(
        api_client.create_customer_order(
            create_customer_order_payload(
                sku["id"], order_code="O1",
                cutoff_at="2026-09-01T10:00:00Z", priority=1,
            ),
            FLOW,
        )
    )
    set_clock("2026-09-01T10:00:00Z")
    fetched = get_success_data(api_client.get_customer_order(order["id"], FLOW))
    assert fetched["status"] == "RECEIVED", (
        f"clock == cutoff_at exactly must NOT miss the cutoff, got {fetched['status']}"
    )


def test_order_cutoff_one_second_past_flips_to_missed(api):
    """PRD §2.4: "An order still in `RECEIVED` whose `cutoff_at` equals the
    current logical clock exactly is **not** yet missed; only a clock strictly
    later than `cutoff_at` triggers `CUTOFF_MISSED`."

    Design: Difficulty/boundary_precision_check/order_cutoff_strict_inequality
    """
    set_clock("2026-09-01T08:00:00Z")
    create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                max_human_occupancy=2)
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    order = get_success_data(
        api_client.create_customer_order(
            create_customer_order_payload(
                sku["id"], order_code="O1",
                cutoff_at="2026-09-01T10:00:00Z", priority=1,
            ),
            FLOW,
        )
    )
    set_clock("2026-09-01T10:00:01Z")
    fetched = get_success_data(api_client.get_customer_order(order["id"], FLOW))
    assert fetched["status"] == "CUTOFF_MISSED", (
        f"clock strictly past cutoff_at must flip the order to CUTOFF_MISSED, "
        f"got {fetched['status']}"
    )
