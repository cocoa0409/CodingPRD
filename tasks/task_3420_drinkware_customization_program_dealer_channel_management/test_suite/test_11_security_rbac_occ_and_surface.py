"""Context headers, RBAC and ownership, entity-specific 404s, pagination with
filters, and optimistic concurrency (PRD sections 2.1, 2.3, 2.6, 2.7)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    boot_clock,
    create_authorized_dealer,
    create_colorway_drop,
    create_dealer,
    create_enforcement_case,
    create_open_application,
    create_order,
    create_print_slot,
    create_product_line,
    get_allocation,
    get_application,
    get_case,
    get_drop,
    get_dealer,
    get_order,
    get_slot,
    make_buyer_headers,
    make_channel_manager_headers,
    make_dealer_headers,
    make_prepress_tech_headers,
    reserve_slot,
    set_clock,
    setup_catalog,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_CM = TEST_USERS["channel_manager_headers"]
_PRODUCTION = TEST_USERS["production_lead_headers"]


def test_dealers_create_missing_auth_headers_returns_400(api):
    """A request with no context headers is rejected before any role or
    existence logic, in the error envelope shape.

    PRD section 2.1: "A request missing either header, or whose role value is
    not one of the declared roles, is rejected with
    `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`."
    PRD section 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and the data object carries
    "`error_id`" plus "a human-readable explanation of what went wrong."

    Design: Corner/validations/dealers_create_missing_auth_headers_returns_400
    """
    resp = api.create_dealer(
        {"legal_name": "No Headers Co", "storefront_address": "0 Nowhere",
         "region_code": "TX-N", "sell_through_pct": 50, "tenure_years": 1},
        {})
    assert resp.status_code == 400
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_MISSING_OR_INVALID_CONTEXT_HEADER"
    assert body["data"]["message"]

    rows, meta = validate_paginated(api.list_dealers(_CM))
    assert len(rows) == 0 and meta["total_count"] == 0


def test_role_denied_for_other_roles_exclusive_ops(api):
    """Role exclusivity on three axes: a Buyer cannot lock a slot, a Dealer
    cannot resolve a case, a PrepressTech cannot decide an application.

    PRD section 2.1: "Each operation in §4 names the roles permitted to call
    it; an attempt to perform an action outside the caller's designated role,
    or to act on a resource the caller does not own where ownership applies,
    is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD section 4: POST /drinkware/print-slots/{id}/lock is ProductionLead-only;
    POST /drinkware/enforcement-cases/{id}/resolve and
    POST /drinkware/dealer-applications/{id}/decide are ChannelManager-only.

    Design: Corner/rbac/role_denied_for_other_roles_exclusive_ops
    """
    boot_clock()
    pair = create_open_application()
    case = create_enforcement_case(seller_handle="rb-1",
                                   listing_url="https://amazon.example/d/rb1")
    slot = create_print_slot()

    resp_lock = api.lock_print_slot(slot["id"], make_buyer_headers("buyer-std"))
    validate_error(resp_lock, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    resp_resolve = api.resolve_enforcement_case(
        case["id"],
        {"outcome": "DISMISSED", "resolution_notes": "dealer trying to self-clear"},
        make_dealer_headers(pair["dealer"]["id"]))
    validate_error(resp_resolve, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    resp_decide = api.decide_application(
        pair["application"]["id"],
        {"decision": "APPROVE", "decision_reason": "prepress overreach"},
        make_prepress_tech_headers("pp-1"))
    validate_error(resp_decide, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    assert get_slot(slot["id"])["status"] == "OPEN"
    assert get_case(case["id"])["status"] == "UNDER_REVIEW"
    assert get_application(pair["application"]["id"])["status"] == "SUBMITTED"


def test_dealer_cannot_read_other_dealer(api):
    """The Dealer role gates on identity, not on the role alone: a cross-dealer
    read is 403 while the own-record read succeeds.

    PRD section 2.1: "When `X-User-Role` is `Dealer`, `X-User-ID` is the `id`
    of the acting `Dealer` record; ownership checks on any resource that
    references a dealer — the dealer's own record, its applications, its
    launch allocations — compare the resource's dealer foreign key to
    `X-User-ID`."

    Design: Corner/rbac/dealer_cannot_read_other_dealer
    """
    boot_clock()
    dealer_a = create_dealer(legal_name="Standard Dealer Co")
    dealer_b = create_dealer(legal_name="Other Dealer Co")

    resp = api.get_dealer(dealer_b["id"], make_dealer_headers(dealer_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    own = validate_success(api.get_dealer(dealer_a["id"],
                                          make_dealer_headers(dealer_a["id"])))
    assert own["legal_name"] == "Standard Dealer Co"


def test_buyer_cannot_submit_other_buyers_order(api):
    """Buyer ownership is keyed on buyer_ref: another buyer's submit is 403
    and authorizes nothing.

    PRD section 2.1: "A `Buyer` role caller may act only on customization
    orders, artwork proofs, and warranty claims whose `buyer_ref` equals the
    caller's `X-User-ID`."

    Design: Corner/rbac/buyer_cannot_submit_other_buyers_order
    """
    boot_clock()
    catalog = setup_catalog()
    order = create_order(catalog["line"]["id"], catalog["drop"]["id"],
                         buyer_ref="buyer-std")

    resp = api.submit_order(order["id"], make_buyer_headers("buyer-intruder"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert get_order(order["id"])["payment_status"] == "UNPAID"


def test_dealer_cannot_request_for_other_dealer(api):
    """The allocation body's dealer_id must equal the acting Dealer identity;
    a spoofed request is 403 before any window or credit logic.

    PRD section 3.4: "a `Dealer` requests units by naming its `dealer_id` —
    which must equal the acting dealer identity —"
    PRD section 2.1: "an attempt to perform an action outside the caller's
    designated role, or to act on a resource the caller does not own where
    ownership applies, is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/dealer_cannot_request_for_other_dealer
    """
    boot_clock()
    dealer_d = create_dealer()
    dealer_e = create_dealer(legal_name="Spoof Target Co")
    catalog = setup_catalog()

    resp = api.create_launch_allocation(
        {"dealer_id": dealer_e["id"], "drop_id": catalog["drop"]["id"],
         "requested_units": 3},
        make_dealer_headers(dealer_d["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    rows, meta = validate_paginated(api.list_launch_allocations(
        _ADMIN, params={"dealer_id": dealer_e["id"]}))
    assert len(rows) == 0 and meta["total_count"] == 0


def test_entity_not_found_sweep(api):
    """Every resource GET maps an unknown but well-formed id to its
    entity-specific 404 error id.

    PRD section 2.7: "(4) existence of referenced resources, where path
    identifiers resolve left-to-right and then body foreign keys resolve in
    the endpoint's declared input order, each surfacing its entity-specific
    404 (`ERR_DEALER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_PRODUCT_LINE_NOT_FOUND`, `ERR_DROP_NOT_FOUND`,
    `ERR_ALLOCATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`,
    `ERR_SLOT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`)"

    Design: Corner/errors/entity_not_found_sweep
    """
    boot_clock()
    missing = NON_EXISTENT_UUID
    expectations = [
        (api.get_dealer(missing, _CM), ApiErrorId.ERR_DEALER_NOT_FOUND),
        (api.get_dealer_application(missing, _CM),
         ApiErrorId.ERR_APPLICATION_NOT_FOUND),
        (api.get_enforcement_case(missing, _CM), ApiErrorId.ERR_CASE_NOT_FOUND),
        (api.get_product_line(missing, _ADMIN),
         ApiErrorId.ERR_PRODUCT_LINE_NOT_FOUND),
        (api.get_colorway_drop(missing, _ADMIN), ApiErrorId.ERR_DROP_NOT_FOUND),
        (api.get_launch_allocation(missing, _ADMIN),
         ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        (api.get_customization_order(missing, _ADMIN),
         ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.get_artwork_proof(missing, _ADMIN), ApiErrorId.ERR_PROOF_NOT_FOUND),
        (api.get_print_slot(missing, _ADMIN), ApiErrorId.ERR_SLOT_NOT_FOUND),
        (api.get_warranty_claim(missing, _ADMIN), ApiErrorId.ERR_CLAIM_NOT_FOUND),
    ]
    for resp, error_id in expectations:
        assert resp.status_code == 404, f"expected 404 for {error_id}"
        validate_error(resp, error_id)
        assert resp.json()["response_type"] == "error"


def test_orders_list_filter_plus_pagination(api):
    """Filters and pagination compose: reservation_status=HELD isolates the
    one reserved order, and unfiltered pages slice the full set.

    PRD section 3.5: "Orders can be listed filtered by `buyer_ref`,
    `product_line_id`, `colorway_drop_id`, `slot_id`, `schedule_status`, and
    `reservation_status`"
    PRD section 2.3: "The `limit` parameter caps the number of items returned;
    it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items and defaults to 0."

    Design: Corner/cross_cutting_layers/orders_list_filter_plus_pagination
    """
    boot_clock()
    catalog = setup_catalog()
    slot = create_print_slot()
    orders = [create_order(catalog["line"]["id"], catalog["drop"]["id"],
                           buyer_ref=f"buyer-f{i}") for i in (1, 2, 3)]
    submit_order(orders[0]["id"], "buyer-f1")
    reserve_slot(orders[0]["id"], slot["id"], "buyer-f1")

    held, meta_held = validate_paginated(api.list_customization_orders(
        _PRODUCTION, params={"reservation_status": "HELD"}))
    assert len(held) == 1 and meta_held["total_count"] == 1
    assert held[0]["id"] == orders[0]["id"]

    page1, meta1 = validate_paginated(api.list_customization_orders(
        _PRODUCTION, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2 and meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_customization_orders(
        _PRODUCTION, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1 and meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_occ_stale_dealer_version_on_resolve_then_fresh_succeeds(api):
    """A matched confirmation carrying a stale dealer version is rejected
    without side effects; the same resolve with the current version applies
    the points exactly once.

    PRD section 2.6: "Resolving an enforcement case with the outcome
    `CONFIRMED_VIOLATION` against a matched dealer requires the request to
    carry `expected_dealer_version`, the version of that dealer the client
    last observed. Because every confirmation recomputes the dealer's
    infraction standing and bumps the dealer's `version`, a client holding a
    stale view of that standing is rejected with `ERR_STALE_DEALER_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_dealer_version_on_resolve_then_fresh_succeeds
    """
    pair = create_authorized_dealer()
    dealer_id = pair["dealer"]["id"]
    case = create_enforcement_case(matched_dealer_id=dealer_id,
                                   marketplace="EBAY", seller_handle="occ-1",
                                   listing_url="https://ebay.example/i/o1")
    version = get_dealer(dealer_id)["version"]

    stale = api.resolve_enforcement_case(
        case["id"],
        {"outcome": "CONFIRMED_VIOLATION", "infraction_category": "MAP_VIOLATION",
         "resolution_notes": "stale write", "expected_dealer_version": version - 1},
        _CM)
    validate_error(stale, ApiErrorId.ERR_STALE_DEALER_VERSION)
    assert get_case(case["id"])["status"] == "UNDER_REVIEW"
    assert get_dealer(dealer_id)["version"] == version, "the stale attempt changed nothing"

    fresh = validate_success(api.resolve_enforcement_case(
        case["id"],
        {"outcome": "CONFIRMED_VIOLATION", "infraction_category": "MAP_VIOLATION",
         "resolution_notes": "fresh write", "expected_dealer_version": version},
        _CM))
    assert fresh["status"] == "CONFIRMED_VIOLATION"
    assert fresh["infraction_points"] == 4, "MAP_VIOLATION row of the points table"
    dealer = get_dealer(dealer_id)
    assert dealer["infraction_points"] == 4
    assert dealer["version"] == version + 1, "the dealer version bumped exactly once"


def test_occ_stale_drop_version_on_lock_then_fresh_succeeds(api):
    """An allocation request bumps the drop's version, so a lock carrying the
    pre-request version is stale; re-reading and locking succeeds.

    PRD section 2.6: "Locking a drop's allocation requires
    `expected_drop_version` matching the drop's current `version`; a mismatch
    is rejected with `ERR_STALE_DROP_VERSION` (HTTP 412)."
    PRD section 3.4: "A successful request records a snapshot of the drop's
    `dealer_unit_price_cents` into the allocation's `unit_price_cents`, starts
    in `REQUESTED` with `allocated_units` at 0, and increments the drop's
    `version` because the request set changed."

    Design: Corner/cross_cutting_layers/occ_stale_drop_version_on_lock_then_fresh_succeeds
    """
    pair = create_authorized_dealer()
    dealer_id = pair["dealer"]["id"]
    line = create_product_line()
    drop = create_colorway_drop(line["id"])  # dealer_unit_price_cents 1800

    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.open_allocation(drop["id"], _ADMIN))
    version_before_request = get_drop(drop["id"])["version"]

    alloc = validate_success(api.create_launch_allocation(
        {"dealer_id": dealer_id, "drop_id": drop["id"], "requested_units": 5},
        make_dealer_headers(dealer_id)), 201)
    assert alloc["unit_price_cents"] == 1800, "request-time price snapshot"

    set_clock("2026-09-21T00:00:00Z")
    stale = api.lock_allocation(
        drop["id"], {"expected_drop_version": version_before_request}, _ADMIN)
    validate_error(stale, ApiErrorId.ERR_STALE_DROP_VERSION)

    version_now = get_drop(drop["id"])["version"]
    assert version_now == version_before_request + 1, \
        "exactly one bump from the allocation request"

    locked = validate_success(api.lock_allocation(
        drop["id"], {"expected_drop_version": version_now}, _ADMIN))
    assert locked["status"] == "ALLOCATION_LOCKED"
    final = get_allocation(alloc["id"])
    assert final["status"] == "ALLOCATED"
    assert final["allocated_units"] == 5, "pool was sufficient for a full grant"
