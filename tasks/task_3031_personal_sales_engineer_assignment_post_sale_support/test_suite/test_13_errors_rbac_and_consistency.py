"""Breadth: error catalogue entries, RBAC edges, cascades, and immediate visibility."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    ANONYMOUS,
    PLATFORM_ADMIN,
    SALES_OPS,
    SERVICE_DEPT,
    SETUP_TECH,
    SUPPORT_AGENT,
    accept_assignment,
    activate_warranty_plan,
    backorders_for,
    create_assignment,
    create_backorder,
    create_customer,
    create_engineer,
    create_product,
    create_quote,
    create_service_center,
    create_support_ticket,
    create_warranty_claim,
    create_warranty_plan,
    end_assignment,
    escalate_ticket,
    finalize_allocation,
    get_support_ticket,
    quote_version,
    route_claim,
    setup_book_world,
    setup_reserved_quote,
    setup_shipped_instrument,
    start_sweep,
    set_clock,
    triage_ticket,
    amend_quote,
)


def test_family_mismatch_blocks_routing_even_with_spare_capacity():
    """PRD 3.6: "The claim's product family must also appear in the center's
    `accepted_families` list, so that a microphone is not routed to a desk
    authorized only for amplifiers and guitars; a family mismatch raises
    `ERR_SERVICE_CENTER_FAMILY_NOT_ACCEPTED` at HTTP 422."

    Design: Corner/errors/service_center_family_not_accepted_blocks_routing
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")
    center = create_service_center(name="Amarillo Amp Bench", region="SOUTH",
                                   capacity_slots=3, accepted_families=["AMPLIFIER"])
    claim = create_warranty_claim(plan, center)

    resp = api_client.route_warranty_claim(claim["id"], SUPPORT_AGENT)
    validate_error(resp, ApiErrorId.ERR_SERVICE_CENTER_FAMILY_NOT_ACCEPTED)
    assert resp.json()["data"]["error_id"] != "ERR_SERVICE_CENTER_CAPACITY_FULL"


def test_a_family_mismatch_route_leaves_the_claim_and_slot_untouched():
    """PRD 3.6: "Routing stamps `routed_at`, increments the center's
    `open_ticket_count`, moves the claim to `ROUTED`, moves the plan to
    `REPAIR_IN_PROGRESS`".

    Design: Corner/errors/service_center_family_not_accepted_blocks_routing
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")
    center = create_service_center(name="Amarillo Amp Bench", region="SOUTH",
                                   capacity_slots=3, accepted_families=["AMPLIFIER"])
    claim = create_warranty_claim(plan, center)
    api_client.route_warranty_claim(claim["id"], SUPPORT_AGENT)

    after = validate_success(api_client.get_warranty_claim(claim["id"], SUPPORT_AGENT))
    assert after["status"] == "PENDING_ROUTING"
    assert after.get("routed_at") is None
    rows = api_client.list_service_centers(SUPPORT_AGENT, {"region": "SOUTH"}).json()["data"]
    assert [row for row in rows if row["id"] == center["id"]][0]["open_ticket_count"] == 0


def test_suspended_center_refuses_a_claim_route():
    """PRD 3.6: "A claim in `PENDING_ROUTING` may be routed to its named center
    only if that center is `OPEN` — a suspended center refuses the route with
    `ERR_SERVICE_CENTER_SUSPENDED` at HTTP 409".

    Design: Corner/errors/suspended_center_refuses_routing
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")
    center = create_service_center(capacity_slots=2, accepted_families=["GUITAR", "AMPLIFIER"])
    suspended = validate_success(api_client.suspend_service_center(center["id"], PLATFORM_ADMIN))
    assert suspended["status"] == "SUSPENDED"

    claim = create_warranty_claim(plan, center)
    resp = api_client.route_warranty_claim(claim["id"], SUPPORT_AGENT)
    validate_error(resp, ApiErrorId.ERR_SERVICE_CENTER_SUSPENDED)


def test_reopening_a_center_lets_the_same_route_succeed():
    """PRD 3.10: "an administrator may suspend it — moving it to `SUSPENDED` so
    that it accepts no further claim routes, per §3.6 — or return a suspended
    center to `OPEN`."

    Design: Corner/errors/suspended_center_refuses_routing
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")
    center = create_service_center(capacity_slots=2, accepted_families=["GUITAR", "AMPLIFIER"])
    api_client.suspend_service_center(center["id"], PLATFORM_ADMIN)
    claim = create_warranty_claim(plan, center)
    api_client.route_warranty_claim(claim["id"], SUPPORT_AGENT)

    reopened = validate_success(api_client.reopen_service_center(center["id"], PLATFORM_ADMIN))
    assert reopened["status"] == "OPEN"

    routed = route_claim(claim)
    assert routed["status"] == "ROUTED"
    plan_after = validate_success(api_client.get_warranty_plan(plan["id"], SUPPORT_AGENT))
    assert plan_after["status"] == "REPAIR_IN_PROGRESS"


def test_a_refused_suspend_route_leaves_the_plan_in_claim_open():
    """PRD 3.6: "Either way the plan moves to `CLAIM_OPEN` and the new
    `WarrantyClaim` begins in `PENDING_ROUTING`".

    Design: Corner/errors/suspended_center_refuses_routing
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")
    center = create_service_center(capacity_slots=2, accepted_families=["GUITAR", "AMPLIFIER"])
    api_client.suspend_service_center(center["id"], PLATFORM_ADMIN)
    claim = create_warranty_claim(plan, center)

    api_client.route_warranty_claim(claim["id"], SUPPORT_AGENT)

    plan_after = validate_success(api_client.get_warranty_plan(plan["id"], SUPPORT_AGENT))
    assert plan_after["status"] == "CLAIM_OPEN"


def test_a_request_without_identity_headers_is_unauthenticated():
    """PRD 2.1: "A request missing either header — or carrying one that is empty
    or malformed — is rejected with `ERR_UNAUTHENTICATED` and HTTP 401 before
    any resource is touched."

    Design: Corner/errors/unauthenticated_call_returns_unauthenticated
    """
    set_clock("2026-09-01T00:00:00.000Z")
    create_customer("Riley Chance", "riley.chance@example.com", "IN")

    resp = api_client.get("/customers", headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401
    assert resp.json()["response_type"] == "error"


def test_an_empty_role_header_is_also_unauthenticated():
    """PRD 2.1: "Both are mandatory. A request missing either header — or
    carrying one that is empty or malformed — is rejected with
    `ERR_UNAUTHENTICATED` and HTTP 401 before any resource is touched."

    Design: Corner/errors/unauthenticated_call_returns_unauthenticated
    """
    set_clock("2026-09-01T00:00:00.000Z")
    create_customer("Riley Chance", "riley.chance@example.com", "IN")

    resp = api_client.get(
        "/customers",
        headers={"X-User-ID": "someone", "X-User-Role": "", "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_unauthenticated_error_body_omits_any_customer_payload():
    """PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/unauthenticated_call_returns_unauthenticated
    """
    set_clock("2026-09-01T00:00:00.000Z")
    create_customer("Riley Chance", "riley.chance@example.com", "IN")

    resp = api_client.get("/customers", headers={"Content-Type": "application/json"})
    body = resp.json()
    assert set(body["data"].keys()) == {"error_id", "message"}
    assert "full_name" not in resp.text


def test_unknown_backorder_id_returns_backorder_not_found():
    """PRD 2.10: "an unknown `Backorder` yields `ERR_BACKORDER_NOT_FOUND`".
    PRD 2.10: "All of these carry HTTP 404."

    Design: Corner/errors/backorder_not_found_for_unknown_id
    """
    set_clock("2026-09-01T00:00:00.000Z")
    resp = api_client.get_backorder(NON_EXISTENT_UUID, SALES_OPS)
    validate_error(resp, ApiErrorId.ERR_BACKORDER_NOT_FOUND)


def test_unknown_backorder_error_carries_no_entity_payload():
    """PRD 2.2: "The `data` field contains the resource object or an array of
    resource objects. For 2xx responses with no data, it contains an empty
    object."

    Design: Corner/errors/backorder_not_found_for_unknown_id
    """
    set_clock("2026-09-01T00:00:00.000Z")
    resp = api_client.get_backorder(NON_EXISTENT_UUID, SALES_OPS)
    body = resp.json()
    assert resp.status_code == 404
    assert set(body["data"].keys()) == {"error_id", "message"}


def test_unknown_gear_exchange_id_returns_gear_exchange_not_found():
    """PRD 2.10: "an unknown `GearExchange` yields `ERR_GEAR_EXCHANGE_NOT_FOUND`."

    Design: Corner/errors/gear_exchange_not_found_for_unknown_id
    """
    set_clock("2026-09-01T00:00:00.000Z")
    resp = api_client.get_gear_exchange(NON_EXISTENT_UUID, SUPPORT_AGENT)
    validate_error(resp, ApiErrorId.ERR_GEAR_EXCHANGE_NOT_FOUND)


def test_gear_exchange_not_found_message_names_the_resource():
    """PRD 2.2: "The `message` provides a human-readable explanation of what
    went wrong." PRD 2.10: "Each resource type has its own not-found code so
    that a caller learns which segment broke".

    Design: Corner/errors/gear_exchange_not_found_for_unknown_id
    """
    set_clock("2026-09-01T00:00:00.000Z")
    resp = api_client.get_gear_exchange(NON_EXISTENT_UUID, SUPPORT_AGENT)
    message = resp.json()["data"]["message"].lower()
    assert "gear" in message or "exchange" in message


def test_sales_engineer_ops_may_not_accept_an_assignment():
    """PRD 4: "POST `/assignments/{id}/accept` — Engineer accepts the
    assignment, making it the book owner — Authorized Role(s): `Engineer`."
    PRD 2.1: "A request that presents a perfectly well-formed pair of headers
    but claims a role the target operation does not admit is rejected with
    `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/sales_engineer_ops_cannot_accept_own_book_assignment
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False,
                             accept=False)
    resp = api_client.accept_assignment(world["assignment_id"], SALES_OPS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_a_refused_accept_leaves_the_proposal_and_book_alone():
    """PRD 3.1: "A `PENDING_ACCEPT` assignment is a proposal, and the engineer
    decides."

    Design: Corner/rbac/sales_engineer_ops_cannot_accept_own_book_assignment
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False,
                             accept=False)
    api_client.accept_assignment(world["assignment_id"], SALES_OPS)

    after = validate_success(api_client.get_assignment(world["assignment_id"], SALES_OPS))
    assert after["status"] == "PENDING_ACCEPT"
    assert after.get("assigned_at") is None
    engineer = validate_success(api_client.get_engineer(world["engineer_id"], SALES_OPS))
    assert engineer["active_book_size"] == 0


def test_setup_technician_may_not_void_a_warranty_plan():
    """PRD 2.1: "`PlatformAdmin` is the only role that may advance the logical
    clock, register catalogue products and service centers, void a warranty
    plan, suspend or terminally close a customer account, or expire a
    certification attempt." PRD 3.6: "Voiding is the administrator's terminal
    override, available from `PENDING`, `ACTIVE`, or `EXPIRED`".

    Design: Corner/rbac/setup_technician_cannot_void_warranty_plan
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    # starts_on may not be later than the logical clock (PRD 3.6).
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")

    resp = api_client.void_warranty_plan(plan["id"], SETUP_TECH)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    after = validate_success(api_client.get_warranty_plan(plan["id"], SUPPORT_AGENT))
    assert after["status"] == "ACTIVE"


def test_platform_admin_can_void_a_warranty_plan():
    """PRD 3.6: "Voiding is the administrator's terminal override, available
    from `PENDING`, `ACTIVE`, or `EXPIRED`, and it is deliberately blunt: the
    plan moves to `VOIDED`".

    Design: Corner/rbac/setup_technician_cannot_void_warranty_plan
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    # starts_on may not be later than the logical clock (PRD 3.6).
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")

    voided = validate_success(api_client.void_warranty_plan(plan["id"], PLATFORM_ADMIN))
    assert voided["status"] == "VOIDED"


def test_anonymous_caller_may_not_list_customers():
    """PRD 2.1: "A request that presents a perfectly well-formed pair of headers
    but claims a role the target operation does not admit is rejected with
    `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/anonymous_cannot_list_customers
    """
    set_clock("2026-09-01T00:00:00.000Z")
    create_customer("Riley Chance", "riley.chance@example.com", "IN")

    resp = api_client.list_customers(ANONYMOUS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_anonymous_caller_may_still_list_products_and_register_accounts():
    """PRD 2.1: "A health probe at `GET /health`, together with self-service
    account and catalogue creation, is exempt from the header requirement
    entirely".

    Design: Corner/rbac/anonymous_cannot_list_customers
    """
    set_clock("2026-09-01T00:00:00.000Z")
    create_product()
    listed = validate_success(api_client.list_products(ANONYMOUS))
    assert len(listed) >= 1

    created = validate_success(
        api_client.create_customer(
            {"full_name": "Fresh Caller", "email": "fresh.caller@example.com",
             "home_state": "IN"},
            ANONYMOUS,
        ),
        expected_status=201,
    )
    assert created["status"] == "PENDING"


def test_support_agent_may_not_resolve_an_escalated_ticket():
    """PRD 2.1: "`ServiceDepartment` exclusively owns ticket resolution and
    de-escalation, and shares nothing else but reads." PRD 3.7: "Resolution is
    the terminal move and is available from `IN_TRIAGE` to the support desk and
    from either `IN_TRIAGE` or `ESCALATED` to the service department."

    Design: Corner/rbac/service_department_owns_escalated_resolution
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")
    center = create_service_center()
    ticket = create_support_ticket(world["customer"], center)
    triage_ticket(ticket)
    escalated = escalate_ticket(ticket)
    assert escalated["status"] == "ESCALATED"
    assert escalated["escalation_seq"] == 1

    # The SupportAgent role does not admit resolution from ESCALATED, so the
    # caller is refused because the ticket is not in a state this role may
    # resolve (PRD 3.7 + PRD 2.11 invalid-state).
    resp = api_client.resolve_support_ticket(ticket["id"], SUPPORT_AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_service_department_resolves_the_escalated_ticket():
    """PRD 2.1: "`ServiceDepartment` exclusively owns ticket resolution and
    de-escalation, and shares nothing else but reads." PRD 3.7: "Resolving from
    `ESCALATED` also decrements the named center's `open_ticket_count`,
    releasing the slot the escalation was occupying".

    Design: Corner/rbac/service_department_owns_escalated_resolution
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")
    center = create_service_center()
    ticket = create_support_ticket(world["customer"], center)
    triage_ticket(ticket)
    escalate_ticket(ticket)
    api_client.resolve_support_ticket(ticket["id"], SUPPORT_AGENT)

    resolved = validate_success(api_client.resolve_support_ticket(ticket["id"], SERVICE_DEPT))
    assert resolved["status"] == "RESOLVED"
    rows = api_client.list_service_centers(SUPPORT_AGENT, {"region": "MIDWEST"}).json()["data"]
    assert [row for row in rows if row["id"] == center["id"]][0]["open_ticket_count"] == 0


def test_stale_customer_version_on_a_second_assignment_is_rejected():
    """PRD 2.5: "A request to create an `Assignment` must carry
    `expected_customer_version` in its body, non-optionally, and it must match
    the target `Customer`'s current `version`." PRD 2.5: "is refused with
    `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_customer_version_on_second_assignment_create_returns_412
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False,
                             accept=False)
    stale_version = validate_success(
        api_client.get_customer(world["customer_id"], SALES_OPS))["version"]
    created = create_assignment(world["customer"], world["engineer"],
                                expected_customer_version=stale_version)
    assert created["status"] == "PENDING_ACCEPT"

    resp = api_client.create_assignment(
        {"customer_id": world["customer_id"], "engineer_id": world["engineer_id"],
         "reason_code": "REGION_CHANGE", "expected_customer_version": stale_version},
        SALES_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_a_stale_assignment_create_leaves_no_residue():
    """PRD 2.5: "a caller whose view of the customer predates someone else's
    change to that customer's assignment history is turned away with
    `ERR_STALE_VERSION` before the assignment row exists at all."

    Design: Corner/cross_cutting_complexity_layers/stale_customer_version_on_second_assignment_create_returns_412
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False,
                             accept=False)
    live = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    create_assignment(world["customer"], world["engineer"],
                      expected_customer_version=live["version"])
    rows_before, meta_before = validate_paginated(
        api_client.list_assignments(SALES_OPS, {"customer_id": world["customer_id"]})
    )
    # The second create is turned away before the assignment row exists, so the
    # book still holds exactly the rows it held before the refusal.
    api_client.create_assignment(
        {"customer_id": world["customer_id"], "engineer_id": world["engineer_id"],
         "reason_code": "REGION_CHANGE", "expected_customer_version": live["version"]},
        SALES_OPS,
    )
    rows, meta = validate_paginated(
        api_client.list_assignments(SALES_OPS, {"customer_id": world["customer_id"]})
    )
    assert meta["total_count"] == meta_before["total_count"] == 2


def test_stale_quote_version_on_reserve_after_an_amend_is_rejected():
    """PRD 2.5: "If the two disagree — which is what happens when a legitimate
    amend has already returned the quote to `SUBMITTED` and bumped its
    `version`, leaving the current caller's view stale — the reservation is
    rejected with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_quote_version_on_reserve_after_amend_returns_412
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    stale_version = quote_version(world["quote_id"], SALES_OPS)
    amended = amend_quote(world["quote"], world["engineer"])
    assert amended["version"] == stale_version + 1

    resp = api_client.reserve_quote(
        world["quote_id"], {"expected_quote_version": stale_version},
        {"X-User-ID": world["engineer_id"], "X-User-Role": "Engineer",
         "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_refreshed_quote_version_lets_the_reservation_succeed():
    """PRD 2.5: "A reservation request against a `Quote` must carry
    `expected_quote_version` in its body. The value is compared against the
    quote's current `version`."

    Design: Corner/cross_cutting_complexity_layers/stale_quote_version_on_reserve_after_amend_returns_412
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    stale_version = quote_version(world["quote_id"], SALES_OPS)
    amended = amend_quote(world["quote"], world["engineer"])
    api_client.reserve_quote(
        world["quote_id"], {"expected_quote_version": stale_version},
        {"X-User-ID": world["engineer_id"], "X-User-Role": "Engineer",
         "Content-Type": "application/json"},
    )

    from test_helpers.fixtures import reserve_quote

    reserved = reserve_quote(amended, world["engineer"])
    assert reserved["status"] == "RESERVED"
    assert reserved["version"] == amended["version"] + 1
    assert reserved["reserved_at"] is not None


def test_ending_an_assignment_clears_the_customer_engineer_mirror():
    """PRD 2.4: "`Customer` mirrors the outcome of that rule in
    `assigned_engineer_id`, which holds the `engineer_id` of the customer's
    `ACTIVE` assignment and is null when no assignment is `ACTIVE`."

    Design: Corner/cross_cutting_complexity_layers/derived_assigned_engineer_mirror_reconciles_after_end
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False)
    before = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert before["assigned_engineer_id"] == world["engineer_id"]

    end_assignment(world["assignment"], SALES_OPS)

    after = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert after["assigned_engineer_id"] is None
    assert after["version"] == before["version"] + 1


def test_ending_an_assignment_reconciles_the_book_counter():
    """PRD 2.8: "`active_book_size` counts an engineer's `ACTIVE` assignments."
    PRD 2.8: "each is recomputed by the operation that would change its
    inputs."

    Design: Corner/cross_cutting_complexity_layers/derived_assigned_engineer_mirror_reconciles_after_end
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False)
    end_assignment(world["assignment"], SALES_OPS)

    engineer = validate_success(api_client.get_engineer(world["engineer_id"], SALES_OPS))
    assert engineer["active_book_size"] == 0
    rows, _ = validate_paginated(
        api_client.list_assignments(SALES_OPS, {"engineer_id": world["engineer_id"]})
    )
    assert len([row for row in rows if row["status"] == "ACTIVE"]) == 0


def test_reservation_creates_one_backorder_per_quote_line():
    """PRD 3.3: "creates exactly one `Backorder` per `QuoteLine` on that quote,
    each in `PREORDER_PENDING` status with an `alloc_sequence` one greater than
    the highest already present."

    Design: Corner/cross_cutting_complexity_layers/qualifying_quote_reservation_cascades_to_one_backorder_per_line
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    assert world["quote"]["status"] == "RESERVED"

    rows, meta = validate_paginated(
        api_client.list_backorders(SALES_OPS, {"engineer_id": world["engineer_id"]})
    )
    assert meta["total_count"] == 2
    assert all(row["status"] == "PREORDER_PENDING" for row in rows)
    assert all(row["units_requested"] == 1 for row in rows)


def test_the_two_cascade_backorders_carry_distinct_allocation_sequences():
    """PRD 3.3: "each in `PREORDER_PENDING` status with an `alloc_sequence` one
    greater than the highest already present."

    Design: Corner/cross_cutting_complexity_layers/qualifying_quote_reservation_cascades_to_one_backorder_per_line
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)

    rows, _ = validate_paginated(
        api_client.list_backorders(SALES_OPS, {"engineer_id": world["engineer_id"]})
    )
    sequences = sorted(row["alloc_sequence"] for row in rows)
    assert len(set(sequences)) == 2
    assert sequences[1] == sequences[0] + 1


def test_the_accept_response_itself_carries_the_new_state():
    """PRD 3.1: "Acceptance stamps `assigned_at` from the logical clock, advances
    the customer's `sequence` bookkeeping by assigning the next index,
    increments the holding engineer's `active_book_size`, and mirrors the holder
    into the customer's `assigned_engineer_id`."

    Design: Corner/consistency_model/immediate_visibility_of_state_change_within_the_same_response
    """
    set_clock("2026-09-19T00:00:00.000Z")
    world = setup_book_world(clock="2026-09-19T00:00:00.000Z", with_catalog=False,
                             accept=False)
    accepted = accept_assignment(world["assignment"])
    assert accepted["status"] == "ACTIVE"
    assert accepted["sequence"] == 1
    assert accepted["assigned_at"] == "2026-09-19T00:00:00.000Z"


def test_reads_immediately_reflect_the_accept_without_any_wait():
    """PRD 2.8: "Derived state propagates. When one operation changes a fact
    that another resource summarizes, the summarizer is updated in the same
    mutation rather than being left stale for a later reader to fix."

    Design: Corner/consistency_model/immediate_visibility_of_state_change_within_the_same_response
    """
    set_clock("2026-09-19T00:00:00.000Z")
    world = setup_book_world(clock="2026-09-19T00:00:00.000Z", with_catalog=False,
                             accept=False)
    accepted = accept_assignment(world["assignment"])

    engineer = validate_success(api_client.get_engineer(world["engineer_id"], SALES_OPS))
    assert engineer["active_book_size"] == 1
    customer = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert customer["assigned_engineer_id"] == world["engineer_id"]
    assert accepted["status"] == "ACTIVE"


def test_finalize_allocation_response_reports_the_final_units_filled():
    """PRD 3.5: "The final variant, stored in `units_filled` when the allocation
    is finalized, is a single pass that depletes the pool".

    Design: Corner/consistency_model/backorder_allocation_visible_in_the_finalize_response
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    backorder = create_backorder(world["guitar_line"], world["engineer"],
                                 units_requested=2,
                                 preorder_open_at="2026-09-19T00:00:00.000Z")
    swept = start_sweep(backorder, pool_units=1)
    assert swept["overcommit_estimate_units"] == 1

    finalized = finalize_allocation(backorder, pool_units=1)
    assert finalized["units_filled"] == 1
    assert finalized["status"] == "PARTIALLY_FILLED"


def test_a_subsequent_read_agrees_with_the_finalize_response():
    """PRD 3.5: "The eligible set is the backorders for the same product whose
    status is `ALLOCATION_SWEEP`, `PARTIALLY_FILLED`, or `BOARD_FILLED`".

    Design: Corner/consistency_model/backorder_allocation_visible_in_the_finalize_response
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    backorder = create_backorder(world["guitar_line"], world["engineer"],
                                 units_requested=2,
                                 preorder_open_at="2026-09-19T00:00:00.000Z")
    start_sweep(backorder, pool_units=1)
    finalized = finalize_allocation(backorder, pool_units=1)

    stored = validate_success(api_client.get_backorder(backorder["id"], SALES_OPS))
    assert stored["units_filled"] == finalized["units_filled"] == 1
    assert stored["units_filled"] <= 1