"""Access control, envelopes, and nested listing: authentication,
authorization denials, error envelope shape, and FK reverse reachability."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_network_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_door,
    create_network,
    create_route,
    setup_delivered_shipment,
    setup_hub_with_line,
)
from test_helpers.test_users import make_door_manager_headers as dmh

NA = TEST_USERS["network_admin_headers"]
HM = TEST_USERS["hub_manager_headers"]
RP = TEST_USERS["route_planner_headers"]
RD = TEST_USERS["route_driver_headers"]


# ---------------------------------------------------------------------------
# Corner/errors/unauthenticated_request_rejected
# ---------------------------------------------------------------------------

def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request missing either header, or presenting a role the
    system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/unauthenticated_request_rejected
    """
    resp = api.list_networks({"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ---------------------------------------------------------------------------
# Corner/rbac/hub_manager_cannot_create_network
# ---------------------------------------------------------------------------

def test_hub_manager_cannot_create_network(api):
    """PRD §2.1: "A request whose role is not permitted to perform the
    requested operation — per the role column of the endpoint table in §4 —
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: `POST /networks` is authorized for NetworkAdmin only.

    Design: Corner/rbac/hub_manager_cannot_create_network
    """
    resp = api.create_network(
        create_network_payload(network_code="BAD", display_name="Bad"), HM
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Corner/rbac/route_driver_cannot_dispatch_route
# ---------------------------------------------------------------------------

def test_route_driver_cannot_dispatch_route(api):
    """PRD §2.1: "A request whose role is not permitted to perform the
    requested operation — per the role column of the endpoint table in §4 —
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: route dispatch is authorized for RoutePlanner only.

    Design: Corner/rbac/route_driver_cannot_dispatch_route
    """
    network, hub, _line = setup_hub_with_line(network_code="NRB", hub_code="HRB", region="RRB")
    route = create_route(
        network["id"], hub["id"], route_code="RRB", vehicle_capacity_dozens=100
    )

    resp = api.dispatch_route(network["id"], hub["id"], route["id"], RD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    after = validate_success(api.get_route(network["id"], hub["id"], route["id"], RP))
    assert after["route_status"] == "PLANNING"


# ---------------------------------------------------------------------------
# Corner/rbac/door_manager_cannot_resolve_stale_credit
# ---------------------------------------------------------------------------

def test_door_manager_cannot_resolve_stale_credit(api):
    """PRD §2.1: "A request whose role is not permitted to perform the
    requested operation — per the role column of the endpoint table in §4 —
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: stale-credit resolve is authorized for NetworkAdmin only;
    PRD §3.6: "A `NetworkAdmin` resolves a disputed credit by supplying a
    `resolution_credit_cents` amount".

    Design: Corner/rbac/door_manager_cannot_resolve_stale_credit
    """
    from test_helpers.fixtures import create_stale_pull

    env = setup_delivered_shipment(
        network_code="NDM", region="RDM", planned_dozens=40, dozens_shipped=20,
    )
    nid, did, sid = env["network"]["id"], env["door"]["id"], env["shipment"]["id"]

    credit = create_stale_pull(nid, did, sid, 3)
    validate_success(api.dispute_stale_credit(nid, did, credit["id"], dmh(did)))

    resp = api.resolve_stale_credit(
        nid, did, credit["id"], {"resolution_credit_cents": 1000}, dmh(did)
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    after = validate_success(api.get_stale_credit(nid, did, credit["id"], dmh(did)))
    assert after["credit_state"] == "DISPUTED"


# ---------------------------------------------------------------------------
# Corner/endpoints/error_envelope_shape_on_failure
# ---------------------------------------------------------------------------

def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" — `response_type` is "error", `data` carries
    `error_id` and `message`, and "The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/error_envelope_shape_on_failure
    """
    resp = api.get_network(NON_EXISTENT_UUID, NA)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"]


# ---------------------------------------------------------------------------
# Corner/endpoints/fk_reverse_reachability_list_endpoints
# ---------------------------------------------------------------------------

def test_fk_reverse_reachability_list_endpoints(api):
    """PRD §2.7: "Most resources live beneath a network in the URL hierarchy
    — a batch under a hub under a network".
    PRD §4: `GET /networks/{nid}/hubs` lists hubs in a network;
    `GET /networks/{nid}/hubs/{hid}/lines` lists lines for a hub.

    Design: Corner/endpoints/fk_reverse_reachability_list_endpoints
    """
    network, hub, line = setup_hub_with_line(
        network_code="NRV", hub_code="HRV", region="RRV",
        line_overrides={"line_kind": "GLAZE_WATERFALL", "rated_dozens_per_hour": 60},
    )
    hubs, meta_h = validate_paginated(api.list_hubs(network["id"], NA))
    assert meta_h["total_count"] == 1
    assert hubs[0]["id"] == hub["id"]

    lines, meta_l = validate_paginated(api.list_lines(network["id"], hub["id"], HM))
    assert meta_l["total_count"] == 1
    assert lines[0]["id"] == line["id"]
