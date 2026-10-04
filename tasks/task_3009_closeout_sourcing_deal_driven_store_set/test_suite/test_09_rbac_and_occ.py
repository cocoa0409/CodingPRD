"""Role-based access control and optimistic concurrency."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_aisle_assignment_payload,
    create_default_jurisdiction,
    create_disposition,
    create_lot,
    create_lot_payload,
    create_member,
    create_priced_lot,
    create_store,
    create_vendor,
    get_lot,
    get_store,
    get_success_data,
    make_club_member_headers,
    set_clock,
    setup_disposition_review_lot,
    setup_sellable_store,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]
BUYER = TEST_USERS["sourcing_buyer_headers"]
FLOOR = TEST_USERS["store_manager_headers"]


def test_store_manager_cannot_price_lot_unauthorized(api, floor_headers,
                                                     buyer_headers):
    """PRD §4: POST /lots/{lot_id}/price — "Set the retail price against the
    substantiated comparison price | PricingLead".
    PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/store_manager_cannot_price_lot_unauthorized
    """
    from test_helpers import create_cleared_lot

    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_cleared_lot(vendor["id"], jur["id"], buyer_headers,
                             quantity_total=10, total_cost_cents=1000,
                             est_sellable_qty=10)
    resp = api.price_lot(lot["id"], {"retail_price_cents": 4000,
                                     "advertises_comparison": True},
                         floor_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert get_lot(lot["id"])["commercial_status"] == "CLEARED"


def test_safety_officer_cannot_create_lots_unauthorized(api, officer_headers):
    """PRD §4: POST /lots — "Acquire a closeout lot | SourcingBuyer, Admin".
    PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/safety_officer_cannot_create_lots_unauthorized
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    resp = api.create_lot(create_lot_payload(vendor["id"], jur["id"],
                                             quantity_total=10,
                                             total_cost_cents=1000,
                                             est_sellable_qty=10),
                          officer_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_club_member_cannot_spend_for_other_member_unauthorized(api):
    """PRD §2.1: "when a `ClubMember` places a purchase carrying a
    `member_id`, the `X-User-ID` header must equal that `member_id` — a member
    may not transact under another member's identity".

    Design: Corner/rbac/club_member_cannot_spend_for_other_member_unauthorized
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    m1 = create_member(ctx["store"]["id"], member_code="M-1", tier="GOLD")
    m2 = create_member(ctx["store"]["id"], member_code="M-2", tier="BRONZE")
    # Member 1's identity presenting member 2's id: ownership violation.
    resp = api.create_purchase(
        ctx["store"]["id"],
        {"lot_id": ctx["lot"]["id"], "qty": 1, "member_id": m2["id"]},
        make_club_member_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_anonymous_cannot_claim_member_pricing_unauthorized(api,
                                                            guest_headers):
    """PRD §2.1: "an `Anonymous` caller must not supply a `member_id` at
    all."
    PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/anonymous_cannot_claim_member_pricing_unauthorized
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    member = create_member(ctx["store"]["id"], member_code="M-1", tier="GOLD")
    resp = api.create_purchase(
        ctx["store"]["id"],
        {"lot_id": ctx["lot"]["id"], "qty": 1, "member_id": member["id"]},
        guest_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_admin_can_perform_shared_operations(api, admin_headers):
    """PRD §4: POST /lots — "Acquire a closeout lot | SourcingBuyer, Admin".
    PRD §3.2: "The server stamps `created_by_user_id` from the caller's
    `X-User-ID` — this becomes the segregation-of-duties anchor for
    screening".

    Design: Corner/rbac/admin_can_perform_shared_operations
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    resp = api.create_lot(create_lot_payload(vendor["id"], jur["id"],
                                             title="Admin Lot",
                                             quantity_total=10,
                                             total_cost_cents=1000,
                                             est_sellable_qty=10),
                          admin_headers)
    lot = get_success_data(resp)
    assert lot["commercial_status"] == "SOURCED"
    assert lot["created_by_user_id"] == "admin-1"


def test_occ_stale_store_version_rejected_on_assignment(api, floor_headers):
    """PRD §2.8: "Creating an aisle assignment on a store must carry
    `expected_store_version`, the client's last observed `version` of that
    store; if the store's current `version` no longer matches — because
    another writer has advanced it since the client last read the store — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a
    supersede built on an outdated view of the layout."

    Design: Corner/cross_cutting_layers/occ_stale_store_version_rejected_on_assignment
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_priced_lot(vendor["id"], jur["id"],
                            lot_overrides={"quantity_total": 10,
                                           "est_sellable_qty": 10})
    stale_version = store["version"]
    get_success_data(api.create_aisle_assignment(
        store["id"],
        create_aisle_assignment_payload(lot["id"], stale_version,
                                        aisle_code="A1", daily_unit_limit=4),
        floor_headers))
    # The first creation advanced the store version; replaying the captured
    # one on a different aisle must be rejected.
    resp = api.create_aisle_assignment(
        store["id"],
        create_aisle_assignment_payload(lot["id"], stale_version,
                                        aisle_code="A2", daily_unit_limit=4),
        floor_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    assert get_store(store["id"])["version"] == stale_version + 1


def test_occ_correct_store_version_succeeds_and_bumps(api, floor_headers):
    """PRD §2.8: "Creating an aisle assignment on a store must carry
    `expected_store_version`, the client's last observed `version` of that
    store".
    PRD §3.9: "Creation carries the `expected_store_version` OCC field per
    §2.8 and bumps the store's `version`."

    Design: Corner/cross_cutting_layers/occ_correct_store_version_succeeds_and_bumps
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_priced_lot(vendor["id"], jur["id"],
                            lot_overrides={"quantity_total": 10,
                                           "est_sellable_qty": 10})
    get_success_data(api.create_aisle_assignment(
        store["id"],
        create_aisle_assignment_payload(lot["id"], store["version"],
                                        aisle_code="A1", daily_unit_limit=4),
        floor_headers))
    assert get_store(store["id"])["version"] == 2
    second = get_success_data(api.create_aisle_assignment(
        store["id"],
        create_aisle_assignment_payload(lot["id"], 2, aisle_code="A2",
                                        daily_unit_limit=6),
        floor_headers))
    assert second["status"] == "ACTIVE"
    assert get_store(store["id"])["version"] == 3


def test_occ_stale_lot_version_rejected_on_disposition(api, buyer_headers):
    """PRD §2.8: "Creating a disposition on a lot must likewise carry
    `expected_lot_version` matching the lot's current `version`; a mismatch is
    rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's picture
    of the lot's pricing and allocation state is out of date."

    Design: Corner/cross_cutting_layers/occ_stale_lot_version_rejected_on_disposition
    """
    ctx = setup_disposition_review_lot()
    lot = ctx["lot"]
    stale_version = lot["version"]
    d1 = create_disposition(lot["id"], action="MARKDOWN", markdown_pct=25,
                            expected_lot_version=stale_version)
    assert d1["status"] == "PENDING"
    # The first creation bumped the lot version; the second replay is stale.
    resp = api.create_disposition(
        lot["id"],
        {"action": "MARKDOWN", "markdown_pct": 40,
         "expected_lot_version": stale_version},
        buyer_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    data, _ = validate_paginated(api.list_dispositions(lot["id"], ADMIN))
    live = [d for d in data if d["id"] == d1["id"]]
    assert live and live[0]["status"] == "PENDING"
