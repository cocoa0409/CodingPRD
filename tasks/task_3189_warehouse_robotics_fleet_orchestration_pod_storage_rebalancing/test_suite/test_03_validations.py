"""Validation and error-path tests (queue B: validations section)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    set_clock,
    create_zone,
    create_drive_unit,
    create_charger,
    create_charging_session_payload,
    setup_stocked_station,
    create_order_with_line,
    create_pick_task_payload,
    create_and_sequence_pick_task,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]
SUPERVISOR = TEST_USERS["floor_supervisor_headers"]


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or presenting a role
    outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    resp = api.list_zones(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_insufficient_inventory_blocks_pick_task_creation(api):
    """PRD §3.2: "both task creation and task sequencing reject a request
    whose quantity exceeds available units with `ERR_INSUFFICIENT_INVENTORY`
    — at creation, the SKU-wide availability (`total_units_on_hand` minus
    `total_units_reserved`) must cover the line remainder."

    Design: Corner/validations/insufficient_inventory_blocks_pick_task_creation
    """
    env = setup_stocked_station(quantity=2)
    order, line = create_order_with_line(env["sku"]["id"], quantity=5)
    resp = api.create_pick_task(
        create_pick_task_payload(
            order["id"], line["id"], env["pod"]["id"], env["station"]["id"],
            quantity=5,
        ),
        FLOW,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)


def test_line_must_belong_to_order_referential(api):
    """PRD §3.3: "The line must belong to the order
    (`ERR_REFERENTIAL_MISMATCH`)."

    Design: Corner/validations/line_must_belong_to_order_referential
    """
    env = setup_stocked_station(quantity=10)
    order1, _line1 = create_order_with_line(env["sku"]["id"], quantity=1)
    order2, line2 = create_order_with_line(env["sku"]["id"], quantity=1)
    resp = api.create_pick_task(
        create_pick_task_payload(
            order1["id"], line2["id"], env["pod"]["id"], env["station"]["id"],
            quantity=1,
        ),
        FLOW,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENTIAL_MISMATCH)


def test_stranded_robot_exception_requires_drive_unit(api):
    """PRD §3.6: "a `drive_unit_id` is required exactly when `kind` is
    `STRANDED_ROBOT`; any other combination is rejected with
    `ERR_REFERENTIAL_MISMATCH`."

    Design: Corner/validations/stranded_robot_exception_requires_drive_unit
    """
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=5, height=5)
    resp = api.create_floor_exception(
        {"kind": "STRANDED_ROBOT", "zone_id": zone["id"]}, SUPERVISOR
    )
    validate_error(resp, ApiErrorId.ERR_REFERENTIAL_MISMATCH)


def test_charger_full_blocks_new_session(api):
    """PRD §3.5: "A `FlowController` opens a `ChargingSession` by supplying
    `charger_id` and `drive_unit_id`; the unit must be `ACTIVE`, the charger's
    `slots_in_use` below its `slot_count` (`ERR_CAPACITY_EXCEEDED`)."

    Design: Corner/validations/charger_full_blocks_new_session
    """
    set_clock()
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=5, height=5)
    charger = create_charger(zone["id"], slot_count=1)
    du1 = create_drive_unit(zone["id"], unit_code="DU1")
    du2 = create_drive_unit(zone["id"], unit_code="DU2")
    validate_success(
        api.create_charging_session(
            create_charging_session_payload(charger["id"], du1["id"]), FLOW
        ),
        expected_status=201,
    )
    resp = api.create_charging_session(
        create_charging_session_payload(charger["id"], du2["id"]), FLOW
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_dispatch_with_no_eligible_drive_unit(api):
    """PRD §3.5: "An empty pool rejects the dispatch with
    `ERR_NO_ELIGIBLE_DRIVE_UNIT`."

    Design: Corner/validations/dispatch_with_no_eligible_drive_unit
    """
    # Stocked station but NO drive units registered at all.
    env = setup_stocked_station(quantity=5)
    order, line = create_order_with_line(env["sku"]["id"], quantity=1)
    queued = create_and_sequence_pick_task(
        order, line, env["pod"], env["station"]
    )
    assert queued["status"] == "QUEUED"
    resp = api.dispatch_pick_task(queued["id"], FLOW)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_DRIVE_UNIT)


def test_occ_stale_version_on_sequence(api):
    """PRD §2.7: "A request to sequence a pick task into a station queue must
    carry `expected_station_version` equal to the station's current
    `version`; if another sequencing decision has advanced the station's
    version since the client last read it, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/err_stale_version_triggerable
    """
    env = setup_stocked_station(quantity=5)
    station = env["station"]
    stale_version = station["version"]  # version captured before any sequencing
    order, line = create_order_with_line(env["sku"]["id"], quantity=2)
    task_a = validate_success(
        api.create_pick_task(
            create_pick_task_payload(
                order["id"], line["id"], env["pod"]["id"], station["id"], quantity=1
            ),
            FLOW,
        ),
        expected_status=201,
    )
    task_b = validate_success(
        api.create_pick_task(
            create_pick_task_payload(
                order["id"], line["id"], env["pod"]["id"], station["id"], quantity=1
            ),
            FLOW,
        ),
        expected_status=201,
    )
    # First sequence succeeds and bumps the station version.
    validate_success(api.sequence_pick_task(task_a["id"], stale_version, FLOW))
    # Second sequence with the now-stale version must be rejected.
    resp = api.sequence_pick_task(task_b["id"], stale_version, FLOW)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_no_eligible_pod_when_all_pods_frozen(api):
    """PRD §3.4: "When no candidate pod exists, placement transitions the task
    to the terminal `REJECTED` and the request fails with
    `ERR_NO_ELIGIBLE_POD` (HTTP 422)."
    PRD §3.4: "The placement selector considers every pod in `IN_STORAGE` or
    `RESERVED` whose zone posture is not `FROZEN`."

    Design: Corner/errors/err_no_eligible_pod_triggerable
    """
    from test_helpers import (
        create_sku,
        create_pod,
        create_stow_task_payload,
        get_sku_version,
        setup_frozen_zone,
    )

    env = setup_frozen_zone(max_human_occupancy=1)
    zone = env["zone"]
    # Re-read to confirm FROZEN after the grant.
    from test_helpers import get_zone
    assert get_zone(zone["id"])["posture"] == "FROZEN"
    create_pod(zone["id"], pod_code="P1", slot_capacity=5)
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    task = validate_success(
        api.create_stow_task(create_stow_task_payload(sku["id"], quantity=1), FLOW),
        expected_status=201,
    )
    resp = api.place_stow_task(task["id"], get_sku_version(sku["id"]), FLOW)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_POD)
    task_after = validate_success(api.get_stow_task(task["id"], FLOW))
    assert task_after["status"] == "REJECTED", (
        f"stow task must be REJECTED when selector pool empty, got {task_after['status']}"
    )
