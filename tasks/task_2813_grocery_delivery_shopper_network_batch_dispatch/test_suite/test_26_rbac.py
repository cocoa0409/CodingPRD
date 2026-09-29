"""Corner section rbac.

Three sweeps over the role model: every role's own exclusive writes succeed,
every role is refused on a write that belongs to somebody else, and ownership
is compared per resource so that peers cannot reach each other's rows while the
shared catalog read stays open to all of them.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BATCH_NOT_SHOPPING,
    ERR_NOT_RESOURCE_OWNER,
    ERR_UNAUTHORIZED_ROLE,
)
from test_helpers.assertions import (
    assert_fields,
    assert_total_count,
    read_batch,
    read_catalog_item,
    read_customer,
    read_line,
)
from test_helpers.constants import (
    BATCH_BUILDING,
    BATCH_CLAIMED,
    CLOCK_0800,
    CREDIT_REASON_SUPPORT_GOODWILL,
    LINE_REQUESTED,
    PAYMENT_AUTHORIZED,
    TIER_PROBATION,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    SUPPORT_HEADERS,
    make_customer_headers,
    make_retailer_manager_headers,
    make_shopper_headers,
)


def test_each_role_performs_its_own_exclusive_writes(api):
    """PRD 2.1: "A `Customer` places grocery orders, adjudicates in-aisle
    substitutions, rates shoppers, and adjusts tips. A `Shopper` claims batches, shops
    the aisles, proposes substitutions, checks out, and delivers. A `RetailerManager`
    owns one retailer's catalog, shelf prices, markup policy, and parity-disclosure
    posture. A `DispatchAdmin` operates the dispatch board: building batches, offering
    them, reassigning abandoned work, finalizing payouts, and driving the logical
    clock. A `CustomerSupport` operator works the back office: registering customers,
    posting goodwill credits, and reading the whole board." Section 4 names the single
    authorized role of each write used below.

    One chain walks the whole board with each call issued by the one role that owns
    it, and every call is accepted.

    Design: Corner/rbac/every_role_exercises_its_own_exclusive_writes
    """
    fx.set_clock(api, CLOCK_0800)

    retailer = validate_success(
        api.create_retailer(
            f.retailer_payload(
                legal_name="Bay Fresh Market LLC",
                store_code="BFM-01",
                catalog_markup_pct=0.15,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    r1 = retailer["id"]

    item = validate_success(
        api.create_catalog_item(
            f.catalog_item_each_payload(
                r1, sku="SKU-EACH-EBT", name="Canned Beans",
                in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
            ),
            make_retailer_manager_headers(r1),
        ),
        201,
    )
    assert_fields(item, catalog_price_cents=460)

    customer = validate_success(
        api.create_customer(
            f.customer_payload(display_name="Dana Ortiz", card_last4="4242"),
            SUPPORT_HEADERS,
        ),
        201,
    )
    c1 = customer["id"]
    customer_headers = make_customer_headers(c1)

    shopper = validate_success(
        api.create_shopper(
            f.shopper_payload(
                display_name="Sam Reyes", service_area_code="SF-42",
                vehicle_capacity_units=10,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    s1 = shopper["id"]

    order = validate_success(
        api.create_order(
            f.order_payload(
                c1, r1,
                delivery_distance_mi=3.0,
                delivery_deadline="2026-08-01T11:00:00Z",
                ebt_requested=False,
                tip_amount_cents=0,
            ),
            customer_headers,
        ),
        201,
    )
    validate_success(
        api.create_order_line(
            order["id"], f.line_each_payload(item["id"], 1), customer_headers
        ),
        201,
    )
    placed = validate_success(api.submit_order(order["id"], customer_headers), 200)
    assert_fields(placed, payment_status=PAYMENT_AUTHORIZED)

    batch = validate_success(
        api.create_batch(
            f.batch_payload(
                service_area_code="SF-42",
                shop_window_start="2026-08-01T08:00:00Z",
                shop_window_end="2026-08-01T11:00:00Z",
                tier_access_floor=TIER_PROBATION,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_success(
        api.add_order_to_batch(
            batch["id"],
            f.batch_order_payload(order["id"], batch["version"]),
            ADMIN_HEADERS,
        ),
        201,
    )
    offered = validate_success(api.dispatch_batch(batch["id"], ADMIN_HEADERS), 200)
    assert_fields(offered, offered_shopper_id=s1)

    claimed = validate_success(
        api.claim_batch(batch["id"], make_shopper_headers(s1)), 200
    )
    assert_fields(claimed, status=BATCH_CLAIMED, claimed_shopper_id=s1)

    credit = validate_success(
        api.create_customer_credit(
            c1,
            f.credit_entry_payload(500, CREDIT_REASON_SUPPORT_GOODWILL),
            SUPPORT_HEADERS,
        ),
        201,
    )
    assert_fields(credit, amount_cents=500)
    assert_fields(read_customer(api, c1, SUPPORT_HEADERS), credit_balance_cents=500)


def test_no_role_can_perform_another_roles_exclusive_write(api):
    """PRD 2.1: "If the headers are well formed but the declared role is not among the
    roles authorized for the addressed operation in section 4, the request is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD 2.8 places that check at rank 2,
    above every state precondition.

    Five borrowed writes are refused, one per role. The `DispatchAdmin` attempt to
    pick a line is the sharpest: the admin outranks nobody, and its refusal is the
    rank-2 role code rather than the rank-8 batch-state code that the same call would
    also earn on a `BUILDING` batch.

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_write
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api, display_name="Dana Ortiz", card_last4="4242")
    c1 = customer["id"]
    customer_headers = make_customer_headers(c1)
    shopper = fx.make_shopper(
        api, display_name="Sam Reyes", service_area_code="SF-42",
        vehicle_capacity_units=10,
    )
    s1 = shopper["id"]

    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    line = fx.add_line_each(api, order["id"], c1, item["id"], 1)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-42",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])

    validate_error(
        api.dispatch_batch(batch["id"], customer_headers), ERR_UNAUTHORIZED_ROLE, 403
    )
    assert_fields(read_batch(api, batch["id"], ADMIN_HEADERS), status=BATCH_BUILDING)

    validate_error(
        api.create_order(
            f.order_payload(
                c1, r1,
                delivery_distance_mi=3.0,
                delivery_deadline="2026-08-01T11:00:00Z",
            ),
            make_shopper_headers(s1),
        ),
        ERR_UNAUTHORIZED_ROLE,
        403,
    )
    assert_total_count(api.list_orders(ADMIN_HEADERS, {"customer_id": c1}), 1)

    validate_error(
        api.create_customer_credit(
            c1,
            f.credit_entry_payload(500, CREDIT_REASON_SUPPORT_GOODWILL),
            make_retailer_manager_headers(r1),
        ),
        ERR_UNAUTHORIZED_ROLE,
        403,
    )
    assert_fields(read_customer(api, c1, SUPPORT_HEADERS), credit_balance_cents=0)

    validate_error(
        api.create_catalog_item(
            f.catalog_item_each_payload(
                r1, sku="SKU-SNEAK", name="Sneaky Item", in_store_price_cents=100
            ),
            SUPPORT_HEADERS,
        ),
        ERR_UNAUTHORIZED_ROLE,
        403,
    )
    assert_total_count(api.list_catalog_items(ADMIN_HEADERS, {"retailer_id": r1}), 1)

    admin_pick = validate_error(
        api.pick_order_line(line["id"], f.pick_each_payload(1), ADMIN_HEADERS),
        ERR_UNAUTHORIZED_ROLE,
        403,
    )
    assert admin_pick["error_id"] != ERR_BATCH_NOT_SHOPPING, (
        "the rank-2 role gate must answer before the rank-8 batch-state gate, so a "
        "DispatchAdmin never learns whether the batch was shoppable"
    )
    assert_fields(
        read_line(api, line["id"], ADMIN_HEADERS),
        status=LINE_REQUESTED,
        final_price_cents=0,
    )


def test_peers_cannot_reach_each_others_rows_but_share_the_catalog_read(api):
    """PRD 2.1: for a `Shopper`, "For starting to shop, picking a line, proposing a
    replacement, checking out, delivering, and abandoning, ownership requires
    `X-User-ID` to equal the batch's `claimed_shopper_id`"; for a `RetailerManager`,
    "Ownership checks compare `X-User-ID` to the addressed catalog item's
    `retailer_id`, and to the addressed retailer's own `id` when the retailer itself
    is the target of a policy update." And: "Any ownership mismatch on a resource
    addressed by a `Customer`, a `Shopper`, or a `RetailerManager` is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Each stranger is refused on the write it does not own - and the refusal is 403,
    not 404, because the row exists - while `GET /catalog-items/{id}`, which section 4
    grants to five roles with no ownership clause, answers all of them.

    Design: Corner/rbac/peers_cannot_reach_each_others_resources_but_share_the_catalog
    """
    fx.set_clock(api, CLOCK_0800)
    owner_retailer = fx.make_retailer(
        api, legal_name="Bay Fresh Market LLC", store_code="BFM-01",
        catalog_markup_pct=0.15,
    )
    r1 = owner_retailer["id"]
    rival_retailer = fx.make_retailer(
        api, legal_name="Rival Grocers Inc", store_code="RGI-02",
        catalog_markup_pct=0.15,
    )
    r2 = rival_retailer["id"]
    item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    owner_customer = fx.make_customer(
        api, display_name="Dana Ortiz", card_last4="4242"
    )
    c1 = owner_customer["id"]
    stranger_customer = fx.make_customer(
        api, display_name="Evan Park", card_last4="1717"
    )
    c2 = stranger_customer["id"]
    first_shopper = fx.make_shopper(
        api, display_name="Sam Reyes", service_area_code="SF-42",
        vehicle_capacity_units=10,
    )
    s1 = first_shopper["id"]
    second_shopper = fx.make_shopper(
        api, display_name="Tia Nunez", service_area_code="SF-42",
        vehicle_capacity_units=10,
    )
    s2 = second_shopper["id"]

    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, order["id"], c1, item["id"], 1)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-42",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    offered = fx.dispatch(api, batch["id"])
    assert_fields(offered, offered_shopper_id=s1)
    fx.claim(api, batch["id"], s1)

    validate_error(
        api.start_shopping(batch["id"], make_shopper_headers(s2)),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )
    assert_fields(
        read_batch(api, batch["id"], ADMIN_HEADERS),
        status=BATCH_CLAIMED,
        claimed_shopper_id=s1,
    )

    validate_error(
        api.patch_catalog_item(
            item["id"], {"in_store_price_cents": 100},
            make_retailer_manager_headers(r2),
        ),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )
    assert_fields(
        read_catalog_item(api, item["id"], ADMIN_HEADERS),
        in_store_price_cents=400,
        catalog_price_cents=460,
    )

    for reader in (
        make_shopper_headers(s2),
        SUPPORT_HEADERS,
        make_retailer_manager_headers(r2),
    ):
        shared = validate_success(api.get_catalog_item(item["id"], reader), 200)
        assert_fields(shared, catalog_price_cents=460)
