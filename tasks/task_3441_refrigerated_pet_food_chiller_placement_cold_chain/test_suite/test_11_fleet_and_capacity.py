"""Fleet registry, decommission, serials, and capacity expansion (PRD §2.12, §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_capacity_project_payload,
    create_chiller,
    create_chiller_batch_payload,
    make_platform_admin_headers,
    make_production_planner_headers,
    setup_active_placement,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_decommission_installed_chiller_rejected(api, platform_admin_headers):
    """PRD §3.3: "A `PlatformAdmin` may decommission an `IN_STOCK` chiller,
    moving it to the terminal `DECOMMISSIONED` state; attempting it in any
    other status is rejected with 409 `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decommission_installed_chiller_rejected
    """
    ctx = setup_active_placement()
    resp = api.decommission_chiller(ctx["chiller"]["id"], platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409

    chiller = validate_success(api.get_chiller(ctx["chiller"]["id"], platform_admin_headers))
    assert chiller["status"] == "INSTALLED"


def test_decommission_twice_terminal_lockdown(api, platform_admin_headers, production_planner_headers):
    """PRD §3.3: "A `PlatformAdmin` may decommission an `IN_STOCK` chiller,
    moving it to the terminal `DECOMMISSIONED` state; attempting it in any
    other status is rejected with 409 `ERR_INVALID_STATE`."
    PRD §2.11: "First, fleet size changes only through batch registration of
    new chillers — never through installation, retirement, relocation,
    agreement termination, or decommissioning; decommissioning changes a
    chiller's status, not the count."

    Design: Corner/state_machines/decommission_twice_terminal_lockdown
    """
    chiller = create_chiller(model="COMPACT", serial_prefix="DC")
    first = validate_success(api.decommission_chiller(chiller["id"], platform_admin_headers),
                             expected_status=200)
    assert first["status"] == "DECOMMISSIONED"

    resp = api.decommission_chiller(chiller["id"], platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409, "DECOMMISSIONED is terminal"

    _, meta = validate_paginated(api.list_chillers(production_planner_headers))
    assert meta["total_count"] == 1, "decommission changes status, never the fleet count"


def test_serial_collision_batch_rejected(api, production_planner_headers):
    """PRD §3.3: "Serial numbers are unique across the fleet: if the batch
    would mint any `serial_no` that already exists, the whole batch is rejected
    with 409 `ERR_SERIAL_NOT_UNIQUE`."
    PRD §3.3: "Numbering starts at `serial_start_seq` when the caller supplies
    it, and otherwise at the next free sequence for that prefix."

    Design: Corner/errors/serial_collision_batch_rejected
    """
    batch1 = create_chiller_batch_payload(model="COMPACT", serial_prefix="DP", quantity=1)
    data = validate_success(api.create_chillers(batch1, production_planner_headers), expected_status=201)
    assert data[0]["serial_no"] == "DP-0001"

    colliding = create_chiller_batch_payload(model="COMPACT", serial_prefix="DP", quantity=2,
                                             serial_start_seq=1)
    resp = api.create_chillers(colliding, production_planner_headers)
    validate_error(resp, ApiErrorId.ERR_SERIAL_NOT_UNIQUE)
    assert resp.status_code == 409, "would re-mint DP-0001"

    _, meta = validate_paginated(api.list_chillers(production_planner_headers))
    assert meta["total_count"] == 1, "atomic rejection: no partial batch persists"


def test_expansion_sequence_and_capacity_ledger(api, production_planner_headers):
    """PRD §3.3: "Commissioning moves `APPROVED` to the terminal
    `COMMISSIONED` state and updates the ledger's `commissioned_capacity`, but
    only in strict approval order: if any other project is still `APPROVED`
    with a strictly smaller `sequence_no`, the commission is rejected with 409
    `ERR_EXPANSION_SEQUENCE_VIOLATION`."
    PRD §2.12: "Registering a manufactured batch of size `quantity` requires
    `quantity` to be no greater than `headroom` evaluated at registration time;
    otherwise the entire batch is rejected atomically with 422
    `ERR_CAPACITY_EXCEEDED` — no partial registration occurs."

    Design: Corner/calculations/expansion_sequence_and_capacity_ledger
    """
    planner = make_production_planner_headers("pp-1")
    approver = make_platform_admin_headers("admin-1")
    p1 = validate_success(
        api.create_capacity_project(create_capacity_project_payload(name="Line 2 tooling",
                                                                    capacity_delta_units=100), planner),
        expected_status=201,
    )
    p2 = validate_success(
        api.create_capacity_project(create_capacity_project_payload(name="Line 3 building",
                                                                    capacity_delta_units=50), planner),
        expected_status=201,
    )
    a1 = validate_success(api.approve_capacity_project(p1["id"], approver), expected_status=200)
    a2 = validate_success(api.approve_capacity_project(p2["id"], approver), expected_status=200)
    assert a1["sequence_no"] == 1 and a2["sequence_no"] == 2, "approval order pins sequence_no"

    resp = api.commission_capacity_project(p2["id"], approver)
    validate_error(resp, ApiErrorId.ERR_EXPANSION_SEQUENCE_VIOLATION)
    assert resp.status_code == 409, "P1 (sequence 1) still APPROVED blocks commissioning P2"

    c1 = validate_success(api.commission_capacity_project(p1["id"], approver), expected_status=200)
    c2 = validate_success(api.commission_capacity_project(p2["id"], approver), expected_status=200)
    assert c1["status"] == "COMMISSIONED" and c2["status"] == "COMMISSIONED"

    # Ledger: 200 base + 100 + 50 = 350 headroom.
    big = validate_success(
        api.create_chillers(create_chiller_batch_payload(model="COMPACT", serial_prefix="CAP", quantity=250),
                            production_planner_headers),
        expected_status=201,
    )
    assert len(big) == 250, "250 <= 350 headroom"
    resp = api.create_chillers(create_chiller_batch_payload(model="COMPACT", serial_prefix="CAP2", quantity=101),
                               production_planner_headers)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    assert resp.status_code == 422, "250 registered + 101 > 350: whole batch rejected atomically"


def test_chiller_list_pagination_envelope(api, platform_admin_headers, production_planner_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The
    `offset` parameter specifies how many items to skip and defaults to 0.
    Unless a list endpoint states otherwise in §3, results are sorted by
    `created_at` in ascending order. Every list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more` in the `meta`
    object of the envelope."

    Design: Corner/endpoints/chiller_list_pagination_envelope
    """
    validate_success(
        api.create_chillers({"model": "COMPACT", "serial_prefix": "PG", "quantity": 3},
                            production_planner_headers),
        expected_status=201,
    )
    page1, meta1 = validate_paginated(api.list_chillers(platform_admin_headers, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3 and meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_chillers(platform_admin_headers, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3 and meta2["has_more"] is False

    serials = [row["serial_no"] for row in page1 + page2]
    assert serials == ["PG-0001", "PG-0002", "PG-0003"], "created_at ascending across pages, each serial once"


def test_production_planner_cannot_approve_own_project(api, production_planner_headers):
    """PRD §3.3: "Approval is a `PlatformAdmin` action on a `PROPOSED` project
    — any other starting state yields 409 `ERR_INVALID_STATE` — and segregation
    of duties forbids the approver's `X-User-ID` from equalling
    `created_by_user_id`, on pain of 403 `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/production_planner_cannot_approve_own_project
    """
    project = validate_success(
        api.create_capacity_project(create_capacity_project_payload(name="Line 2 tooling",
                                                                    capacity_delta_units=100),
                                    make_production_planner_headers("pp-1")),
        expected_status=201,
    )
    assert project["created_by_user_id"] == "pp-1"

    resp = api.approve_capacity_project(project["id"], make_platform_admin_headers("pp-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert resp.status_code == 403, "approver id equals created_by_user_id even though the role is authorized"
