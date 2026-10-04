"""RBAC, action endpoints, filtered lists, and clock-default tests
(queue B: rbac / endpoints / cross_cutting sections)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_zone_payload,
    create_sku_payload,
    create_customer_order_payload,
    create_zone,
    create_drive_unit,
    create_pod,
    create_sku,
    create_pick_station,
    setup_triaged_human_exception,
    create_human_entry_permit_payload,
    setup_release_in_status,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]
SUPERVISOR = TEST_USERS["floor_supervisor_headers"]
OPERATOR = TEST_USERS["station_operator_headers"]
ENGINEER = TEST_USERS["release_engineer_headers"]


def test_station_operator_cannot_create_zone(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint per
    the authorization matrix is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /fleet/zones is authorized for FleetAdmin only.

    Design: Corner/rbac/station_operator_cannot_create_zone
    """
    resp = api.create_zone(
        create_zone_payload(
            zone_code="ZX", grid_x=0, grid_y=0, width=5, height=5,
            max_human_occupancy=1,
        ),
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_release_engineer_cannot_grant_permit(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint per
    the authorization matrix is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /fleet/human-entry-permits/{id}/grant is authorized for
    SafetyOfficer only.

    Design: Corner/rbac/release_engineer_cannot_grant_permit
    """
    from test_helpers import set_clock

    set_clock()
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=5, height=5,
                       max_human_occupancy=1)
    exception = setup_triaged_human_exception(zone)
    permit = validate_success(
        api.create_human_entry_permit(
            create_human_entry_permit_payload(zone["id"], exception["id"]),
            SUPERVISOR,
        ),
        expected_status=201,
    )
    resp = api.grant_human_entry_permit(permit["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_flow_controller_cannot_record_validation(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint per
    the authorization matrix is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /fleet/software-releases/{id}/record-validation is authorized
    for SafetyOfficer only.

    Design: Corner/rbac/flow_controller_cannot_record_validation
    """
    release = setup_release_in_status("VALIDATING")
    resp = api.record_validation(release["id"], {"outcome": "PASS"}, FLOW)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_retire_drive_unit_action_endpoint(api):
    """PRD §3.1: "A `FleetAdmin` may retire an `ACTIVE` unit — provided no
    non-terminal pick task references it — moving it to the terminal `RETIRED`
    status and incrementing its `version`."

    Design: Corner/endpoints/retire_drive_unit_action_endpoint
    """
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=5, height=5)
    du = create_drive_unit(zone["id"], unit_code="DU1")
    retired = validate_success(api.retire_drive_unit(du["id"], ADMIN))
    assert retired["status"] == "RETIRED"
    # RETIRED is terminal: a second retire is an illegal transition.
    resp = api.retire_drive_unit(du["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_pause_and_reopen_station(api):
    """PRD §3.1: "A `FlowController` may pause an `OPEN` station (status
    becomes `PAUSED`, station `version` increments) and later reopen it
    (status returns to `OPEN`)."

    Design: Corner/endpoints/pause_and_reopen_station
    """
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=5, height=5)
    station = create_pick_station(zone["id"], station_code="ST1", max_queue=5)
    v0 = station["version"]
    paused = validate_success(api.pause_pick_station(station["id"], FLOW))
    assert paused["status"] == "PAUSED"
    assert paused["version"] == v0 + 1, (
        f"pause must increment version: {v0} -> {paused['version']}"
    )
    reopened = validate_success(api.reopen_pick_station(station["id"], FLOW))
    assert reopened["status"] == "OPEN"
    assert reopened["version"] == v0 + 2, (
        f"reopen must increment version again: {v0} -> {reopened['version']}"
    )


def test_filtered_list_pods_by_zone(api):
    """PRD §2.10: "Reverse-reachability listings exist for the chargers, pods,
    pick stations, and human-entry permits of a zone."

    Design: Corner/endpoints/filtered_list_pods_by_zone
    """
    z1 = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=5, height=5,
                     max_human_occupancy=1)
    z2 = create_zone(zone_code="Z2", grid_x=5, grid_y=0, width=5, height=5,
                     max_human_occupancy=1)
    create_pod(z1["id"], pod_code="P1", slot_capacity=5)
    create_pod(z2["id"], pod_code="P2", slot_capacity=5)
    data, meta = validate_paginated(api.list_zone_pods(z1["id"], ADMIN))
    assert meta["total_count"] == 1, f"expected exactly 1 pod in Z1, got {meta['total_count']}"
    assert data[0]["pod_code"] == "P1"


def test_clock_default_is_2026_09_01(api):
    """PRD §2.4: "Before any clock-driving call, the logical clock reads
    exactly `2026-09-01T00:00:00Z` and must never fall back to real wall-clock
    time."
    PRD §2.4: "An order still in `RECEIVED` whose `cutoff_at` equals the
    current logical clock exactly is **not** yet missed; only a clock strictly
    later than `cutoff_at` triggers `CUTOFF_MISSED`."

    Design: Corner/cross_cutting/clock_default_is_2026_09_01
    """
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    order = validate_success(
        api.create_customer_order(
            create_customer_order_payload(
                sku["id"], cutoff_at="2026-09-01T00:00:01Z", priority=1
            ),
            FLOW,
        ),
        expected_status=201,
    )
    fetched = validate_success(api.get_customer_order(order["id"], FLOW))
    assert fetched["status"] == "RECEIVED", (
        f"default clock 2026-09-01T00:00:00Z is strictly before the cutoff; "
        f"order must stay RECEIVED, got {fetched['status']}"
    )
