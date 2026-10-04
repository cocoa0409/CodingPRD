"""RBAC corners, optimistic-concurrency corners, and cross-cutting consistency."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_assignment,
    create_order,
    create_product,
    create_rep,
    create_route,
    create_route_day,
    create_shelf_execution_payload,
    create_store,
    load_route_day,
    lot_entry,
    make_rep_headers,
    make_store_manager_headers,
    make_supervisor_headers,
    order_line,
    set_clock,
    start_route_day,
    submit_order,
    validate_error,
    validate_success,
)


def test_rep_cannot_approve_stale_credit_role_denied(api):
    """PRD §4: "POST /dsd/stale-credits/{creditId}/approve — Approve a pending
    credit (segregation of duties enforced) | RouteSupervisor".
    PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/rep_cannot_approve_stale_credit_role_denied
    """
    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-ST", "2026-09-06", 20)], rep
    )
    start_route_day(day["id"], rep)

    resp = api.create_stale_credit(
        {
            "route_day_id": day["id"],
            "store_id": store["id"],
            "product_id": product["id"],
            "qty_cases": 2,
        },
        make_rep_headers(rep["id"]),
    )
    credit = validate_success(resp, expected_status=201)

    resp = api.approve_stale_credit(credit["id"], make_rep_headers(rep["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    credit_after = validate_success(
        api.get_stale_credit(credit["id"], make_supervisor_headers())
    )
    assert credit_after["status"] == "PENDING_APPROVAL"


def test_segregation_of_duties_supervisor_cannot_approve_own_credit(api):
    """PRD §2.1: "the supervisor who approves or rejects a stale credit must
    not be the user who created it, or the request fails with
    ERR_SEGREGATION_OF_DUTIES (HTTP 403)."
    PRD §4: "POST /dsd/stale-credits | RouteSalesRep, RouteSupervisor".

    Design: Corner/rbac/segregation_of_duties_supervisor_cannot_approve_own_credit
    """
    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-ST", "2026-09-06", 20)], rep
    )
    start_route_day(day["id"], rep)

    # A supervisor MAY originate a credit (shared operation)...
    resp = api.create_stale_credit(
        {
            "route_day_id": day["id"],
            "store_id": store["id"],
            "product_id": product["id"],
            "qty_cases": 2,
        },
        make_supervisor_headers("sup-1"),
    )
    credit = validate_success(resp, expected_status=201)

    # ...but may not approve it themselves.
    resp = api.approve_stale_credit(credit["id"], make_supervisor_headers("sup-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    # A different supervisor may approve.
    resp = api.approve_stale_credit(credit["id"], make_supervisor_headers("sup-2"))
    approved = validate_success(resp)
    assert approved["status"] == "APPROVED"


def test_unassigned_rep_cannot_load_or_start_route_day(api):
    """PRD §3.3: "Loading is permitted only while the route day is PLANNED, the
    route itself is ACTIVE, and the acting rep's identity matches the route's
    rsr_id (ERR_REP_NOT_ASSIGNED otherwise)."

    Design: Corner/rbac/unassigned_rep_cannot_load_or_start_route_day
    """
    rep1 = create_rep(full_name="Rep One")
    rep2 = create_rep(full_name="Rep Two")
    store = create_store()
    product = create_product()
    route = create_route(rep1["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])

    resp = api.load_route_day(
        day["id"],
        {"lots": [lot_entry(product["id"], "L-1", "2026-09-20", 10)]},
        make_rep_headers(rep2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REP_NOT_ASSIGNED)

    day_after = validate_success(
        api.get_route_day(day["id"], make_supervisor_headers())
    )
    assert day_after["status"] == "PLANNED"
    assert day_after["loaded_cases"] == 0


def test_store_manager_cannot_verify_other_stores_shelf_execution(api):
    """PRD §3.6: "the acting manager's identity must equal the execution's
    store_id, failing with ERR_STORE_SCOPE_VIOLATION otherwise."
    PRD §3.6: "Either outcome stamps verified_by_user_id with the acting
    manager."

    Design: Corner/rbac/store_manager_cannot_verify_other_stores_shelf_execution
    """
    set_clock()
    rep = create_rep()
    store_a = create_store(store_code="SA")
    store_b = create_store(store_code="SB")
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store_a["id"])
    create_assignment(route["id"], store_b["id"], stop_sequence=2)
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 20)], rep
    )
    start_route_day(day["id"], rep)

    resp = api.create_shelf_execution(
        create_shelf_execution_payload(day["id"], store_a["id"], product["id"]),
        make_rep_headers(rep["id"]),
    )
    execution = validate_success(resp, expected_status=201)

    # Store B's manager is out of scope for store A's execution.
    resp = api.verify_shelf_execution(
        execution["id"], {"outcome": "VERIFIED"}, make_store_manager_headers(store_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_STORE_SCOPE_VIOLATION)

    # Store A's manager verifies.
    resp = api.verify_shelf_execution(
        execution["id"], {"outcome": "VERIFIED"}, make_store_manager_headers(store_a["id"])
    )
    verified = validate_success(resp)
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == store_a["id"]


def test_occ_order_revision_stale_version_rejected(api):
    """PRD §2.7: "Revising a draft order requires the request to carry
    expected_store_order_version, holding the client's last observed version of
    the order; if the order's current version on the server has advanced past
    that value — because another accepted revision already replaced the line
    set — the request is rejected with ERR_STALE_VERSION (HTTP 412), preventing
    the client from overwriting a line set it has not observed."

    Design: Corner/cross-cutting/occ_order_revision_stale_version_rejected
    """
    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 50)], rep
    )
    start_route_day(day["id"], rep)

    order = create_order(day["id"], store["id"], [order_line(product["id"], 10)], rep)
    order_v1 = order["version"]

    resp = api.revise_order(
        order["id"],
        {
            "lines": [{"product_id": product["id"], "qty_ordered_cases": 20}],
            "expected_store_order_version": order_v1,
        },
        make_rep_headers(rep["id"]),
    )
    revised = validate_success(resp)
    order_v2 = revised["version"]

    # A revision still carrying the pre-first-revision version is stale.
    resp = api.revise_order(
        order["id"],
        {
            "lines": [{"product_id": product["id"], "qty_ordered_cases": 30}],
            "expected_store_order_version": order_v1,
        },
        make_rep_headers(rep["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # A revision carrying the current version succeeds.
    resp = api.revise_order(
        order["id"],
        {
            "lines": [{"product_id": product["id"], "qty_ordered_cases": 30}],
            "expected_store_order_version": order_v2,
        },
        make_rep_headers(rep["id"]),
    )
    final = validate_success(resp)
    assert final["gross_total_cents"] == 15000
    assert final["version"] == 3


def test_occ_promo_execution_stale_agreement_version_rejected(api):
    """PRD §2.7: "Submitting a promo execution requires
    expected_promo_agreement_version, holding the client's last observed
    version of the agreement; if the agreement's version has advanced since
    (for example because a prior execution submission already bumped it), the
    submission is likewise rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross-cutting/occ_promo_execution_stale_agreement_version_rejected
    """
    from test_helpers import create_promo_agreement_payload

    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 10)], rep
    )
    start_route_day(day["id"], rep)

    resp = api.create_promo_agreement(
        create_promo_agreement_payload(store["id"], product["id"]),
        make_supervisor_headers(),
    )
    agreement = validate_success(resp, expected_status=201)
    resp = api.activate_promo_agreement(agreement["id"], make_supervisor_headers())
    active = validate_success(resp)
    agr_v2 = active["version"]

    resp = api.create_promo_execution(
        {
            "agreement_id": agreement["id"],
            "route_day_id": day["id"],
            "photo_url": "https://photos/one.jpg",
            "expected_promo_agreement_version": agr_v2,
        },
        make_rep_headers(rep["id"]),
    )
    validate_success(resp, expected_status=201)

    # The first submission bumped the agreement version; the old expected
    # version is now stale.
    resp = api.create_promo_execution(
        {
            "agreement_id": agreement["id"],
            "route_day_id": day["id"],
            "photo_url": "https://photos/two.jpg",
            "expected_promo_agreement_version": agr_v2,
        },
        make_rep_headers(rep["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_cascade_lot_open_on_start_observable_immediately(api):
    """PRD §3.3: "Loading creates one truck-inventory lot per payload entry in
    SEALED status, recomputes the route day's loaded_cases, transitions the day
    PLANNED → LOADED, and increments the route day's version."
    PRD §3.3: "Starting the route day — again the assigned rep's action,
    requiring the day to be LOADED (ERR_ROUTE_DAY_NOT_LOADED otherwise) —
    flips every lot of the day from SEALED to OPEN and moves the day to
    IN_PROGRESS, incrementing the day's version."

    Design: Corner/cross-cutting/cascade_lot_open_on_start_observable_immediately
    """
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 10)], rep
    )

    from test_helpers import get_lot_by_code, get_route_day

    lot = get_lot_by_code(day["id"], "L-1")
    assert lot["status"] == "SEALED"

    start_route_day(day["id"], rep)

    resp = api.get_truck_lot(lot["id"], make_supervisor_headers())
    lot_after = validate_success(resp)
    assert lot_after["status"] == "OPEN"
    assert get_route_day(day["id"])["status"] == "IN_PROGRESS"


def test_delivery_effects_visible_in_same_read_after_write(api):
    """PRD §3.5: "A successful delivery stamps delivered_at with the logical
    clock, moves the order to DELIVERED, increments its version, and triggers
    two recomputes: the route day's delivered_cases refreshes from the lots,
    and if a settlement already exists for the day in OPEN status, its
    gross_delivered_cents, forward_expected_cents, and
    chronological_expected_cents are recomputed as well — a settlement in
    BALANCED auto-reopens to OPEN on the same trigger (see §3.9)."

    Design: Corner/consistency_model/delivery_effects_visible_in_same_read_after_write
    """
    from test_helpers import get_route_day

    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 30)], rep
    )
    start_route_day(day["id"], rep)
    order = create_order(day["id"], store["id"], [order_line(product["id"], 12)], rep)
    submit_order(order["id"], rep)

    resp = api.deliver_order(
        order["id"],
        {"lines": [{"product_id": product["id"], "qty_delivered_cases": 12}]},
        make_rep_headers(rep["id"]),
    )
    delivered = validate_success(resp)
    assert delivered["status"] == "DELIVERED"
    assert delivered["gross_total_cents"] == 6000

    # The follow-up read shows the recomputed day total immediately.
    day_after = get_route_day(day["id"])
    assert day_after["delivered_cases"] == 12
