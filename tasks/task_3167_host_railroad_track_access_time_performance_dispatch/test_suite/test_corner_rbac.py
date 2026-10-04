"""RBAC corners: peer isolation, role denial, and segregation of duties."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    PASSENGER_OPERATOR_HEADERS,
    STATE_SPONSOR_HEADERS,
    factories,
    fixtures,
    make_host_rep_headers,
)


def test_host_rep_of_other_railroad_cannot_actualize_passage(api):
    """A HostRailroadRep of a different railroad is 403 on this corridor's passage.

    PRD: "A request whose role is not authorized for the endpoint, or — in the case of a host representative — whose identity does not match the owning railroad of the target resource, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD: "When `X-User-Role` is `HostRailroadRep`, `X-User-ID` is the `id` of the acting `HostRailroad`; ownership checks on any resource that references a `HostRailroad` — directly, or through the corridor/agreement chain that links corridors, agreements, timetables, runs, incidents, projects, windows, and disruptions back to a host railroad — compare the resource's owning-railroad identifier to `X-User-ID`."
    Design: Corner/rbac/host_rep_of_other_railroad_forbidden
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    other_host = fixtures.create_host(api, name="Other Rail", reporting_mark="OTH")
    run = net["runs"][0]
    p1, _p2 = net["passages"][0]
    fixtures.depart_run(api, net, run["id"], "2026-09-02T08:00:00Z")

    response = api.actualize_segment_passage(
        p1["id"],
        {"actual_entry_at": "2026-09-02T08:00:00Z", "actual_exit_at": "2026-09-02T08:27:00Z"},
        make_host_rep_headers(other_host["id"]),
    )

    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_FORBIDDEN)
    assert fixtures.read_passage(api, p1["id"])["status"] == "PLANNED"


def test_state_sponsor_cannot_create_corridor(api):
    """StateSponsor is limited to funding agreements; corridor creation is denied.

    PRD: "A request whose role is not authorized for the endpoint, or — in the case of a host representative — whose identity does not match the owning railroad of the target resource, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    Design: Corner/rbac/state_sponsor_cannot_create_corridor_forbidden
    """
    net = fixtures.setup_network(api)

    response = api.create_corridor(
        factories.corridor_payload(net["host"]["id"], code="ZZ", name="Z", endpoint_a="A", endpoint_b="B", service_type="LONG_DISTANCE", annual_cost_cents=1),
        STATE_SPONSOR_HEADERS,
    )

    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_FORBIDDEN)


def test_passenger_operator_cannot_lock_maintenance_window(api):
    """Maintenance lock is host-exclusive; the passenger operator gets 403.

    PRD: "A request whose role is not authorized for the endpoint, or — in the case of a host representative — whose identity does not match the owning railroad of the target resource, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    Design: Corner/rbac/passenger_operator_cannot_lock_maintenance_forbidden
    """
    net = fixtures.setup_network(api)
    window = fixtures.create_window(
        api,
        net,
        track_segment_id=net["seg1"]["id"],
        window_start_at="2026-09-08T06:00:00Z",
        window_end_at="2026-09-08T08:00:00Z",
        equipment_unit_id="EQ-3",
        clearance_buffer_minutes=15,
    )

    response = api.lock_maintenance_window(window["id"], PASSENGER_OPERATOR_HEADERS)

    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_FORBIDDEN)
    assert fixtures.read_window(api, window["id"])["status"] == "PLANNED"


def test_host_rep_cannot_confirm_incident_but_operator_can(api):
    """Confirmation is passenger-side: the coding host rep gets 403; the operator succeeds.

    PRD: "The passenger operator countersigns the host's coding by confirming an `OPEN` incident, moving it to `CONFIRMED`."
    PRD: "A request whose role is not authorized for the endpoint, or — in the case of a host representative — whose identity does not match the owning railroad of the target resource, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    Design: Corner/rbac/host_rep_cannot_confirm_own_incident_forbidden
    """
    net = fixtures.run_0902_completed_20_late(api)
    incident = fixtures.code_incident(
        api, net, net["run"]["id"], "HOST_FREIGHT_HOLD", 20, segment_passage_id=net["passage_ids"][0]
    )

    blocked = api.confirm_delay_incident(incident["id"], net["host_headers"])
    assert blocked.status_code == 403
    validate_error(blocked, ApiErrorId.ERR_FORBIDDEN)

    confirmed = validate_success(
        api.confirm_delay_incident(incident["id"], PASSENGER_OPERATOR_HEADERS), 200
    )
    assert confirmed["status"] == "CONFIRMED"
