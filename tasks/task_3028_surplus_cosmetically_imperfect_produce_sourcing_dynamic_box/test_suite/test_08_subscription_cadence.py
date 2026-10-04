"""Subscription cadence: skips, auto-skips, pause hops and optimistic concurrency."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ApiErrorId,
    build_order,
    make_center,
    make_customer,
    advance_clock,
    make_lot,
    make_operator_headers,
    make_supplier,
    reset_clock,
    setup_center_supplier_lot,
    setup_subscriber,
)
from test_helpers.fixtures import (
    award_lot,
    line_plan,
    make_bid,
    make_lot_ready,
    pack_order,
    refresh_lot,
    refresh_subscription,
)


def _award_and_ready(api, lot, supplier):
    make_bid(api, lot["id"], supplier["id"], cost=100,
             quantity=lot["quantity_available"])
    return make_lot_ready(api, award_lot(api, lot), "PASS")


# ---------------------------------------------------------------------------
# The shelf-life floor and the auto-skip cascade
# ---------------------------------------------------------------------------
def test_subscription_shelf_life_floor_binds_at_the_boundary(api):
    """PRD §3.2: "It cascades that recomputation into the subscription
    shelf-life rule, so an awarded lot with a shelf life strictly below the
    subscription shelf-life floor immediately pushes every `ACTIVE`
    subscription of that lane into `AUTO_SKIPPED`."
    PRD §3.8: "every `ACTIVE` subscription of that lane moves to `AUTO_SKIPPED`
    and has `skipped_cycle_index` set to its serving cycle index plus one."

    Design: Corner/calculations/subscription_shelf_life_floor_autoskips_at_the_boundary
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    supplier = make_supplier(api, name="Shelf Life Farms", region="NE")
    customer, subscription = setup_subscriber(api, region="NE", email="shelf@example.com")

    # A lot whose awarded shelf life clears the floor leaves the subscription alone.
    boundary = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                        procurement_grade="SURPLUS", unit_weight_grams=100,
                        unit_cost_cents=100, quantity_available=300,
                        harvest_date="2026-09-01T00:00:00Z",
                        expiry_date="2026-09-15T00:00:00Z",
                        ready_date="2026-09-05T00:00:00Z", product_name="SL1")
    make_bid(api, boundary["id"], supplier["id"], cost=100, quantity=300)
    award_lot(api, boundary)
    cleared = refresh_lot(api, boundary)
    assert cleared["shelf_life_days"] >= 14, (
        "Setup failed: this lot must clear the subscription shelf-life floor"
    )
    assert refresh_subscription(api, subscription)["status"] == "ACTIVE"

    # BAKERY carries a much shorter shelf life, so the award forces the auto-skip.
    short = make_lot(api, supplier["id"], center["id"], category="BAKERY",
                     procurement_grade="SURPLUS", unit_weight_grams=100,
                     unit_cost_cents=100, quantity_available=300,
                     harvest_date="2026-09-01T00:00:00Z",
                     expiry_date="2026-09-06T00:00:00Z",
                     ready_date="2026-09-05T00:00:00Z", product_name="SL2")
    make_bid(api, short["id"], supplier["id"], cost=100, quantity=300)
    award_lot(api, short)
    shortened = refresh_lot(api, short)
    assert shortened["shelf_life_days"] < cleared["shelf_life_days"], (
        "Setup failed: the second lot must carry the shorter shelf life"
    )

    after = refresh_subscription(api, subscription)
    assert after["status"] == "AUTO_SKIPPED"
    assert after["skipped_cycle_index"] == after["serving_cycle_index"] + 1


# ---------------------------------------------------------------------------
# Explicit skip and the pause hop limit
# ---------------------------------------------------------------------------
def test_skip_records_the_next_cycle_and_advances_the_version(api):
    """PRD §3.8: "A permitted skip moves the subscription from `ACTIVE` to
    `SKIPPED`, sets `skipped_cycle_index` to the serving cycle index plus one,
    stamps `skipped_on` with the current logical clock, and increments the
    subscription's version by one."

    Design: Difficulty/transitive_cascade/subscription_skip_rejection_cascades_to_the_built_box
    """
    reset_clock(api)
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")
    customer, subscription = setup_subscriber(api, region="NE", email="sk@example.com")

    skipped = validate_success(
        api.skip_subscription(
            subscription["id"],
            {"expected_subscription_version": subscription["version"]},
            ADMIN,
        ),
        200,
    )

    assert skipped["status"] == "SKIPPED"
    assert skipped["skipped_cycle_index"] == 2
    assert skipped["skipped_on"] is not None
    assert skipped["version"] == subscription["version"] + 1


def test_fifth_pause_hop_is_refused(api):
    """PRD §3.8: "a pause is admitted only while `pause_count` is strictly
    below the maximum pause hops"
    PRD §3.8: "The `pause_count` field is bounded to the range 0 to 4 inclusive,
    and that bound is the practical limit on how many times a subscription may
    hop into the paused state over its life."

    Design: Corner/state_machines/subscription_pause_beyond_the_hop_limit_returns_invalid_state
    """
    reset_clock(api)
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")
    customer, subscription = setup_subscriber(api, region="NE", email="ph@example.com")

    for hop in range(4):
        validate_success(api.pause_subscription(subscription["id"], {}, ADMIN), 200)
        advance_clock(api, f"2026-09-0{2 + hop}T00:00:00Z")
        validate_success(api.resume_subscription(subscription["id"], {}, ADMIN), 200)

    before = refresh_subscription(api, subscription)
    assert before["pause_count"] == 4

    response = api.pause_subscription(subscription["id"], {}, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    after = refresh_subscription(api, subscription)
    assert after["status"] == "ACTIVE"
    assert after["pause_count"] == 4


# ---------------------------------------------------------------------------
# Optimistic concurrency on the skip
# ---------------------------------------------------------------------------
def test_stale_subscription_skip_is_refused(api):
    """PRD §2.10: "A skip request must carry `expected_subscription_version`,
    holding the `Subscription` version the client last observed. If the
    subscription's plan has moved on since that read — through a resume, a
    pause, or a server-side auto-skip that changed the row — the supplied value
    no longer matches the subscription's current `version`, and the request is
    refused with `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_layers/stale_subscription_skip_is_refused
    """
    reset_clock(api)
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")
    customer, subscription = setup_subscriber(api, region="NE", email="oc@example.com")
    stale_version = subscription["version"]

    validate_success(api.pause_subscription(subscription["id"], {}, ADMIN), 200)
    advance_clock(api, "2026-09-03T00:00:00Z")
    validate_success(api.resume_subscription(subscription["id"], {}, ADMIN), 200)

    current = refresh_subscription(api, subscription)
    assert current["version"] != stale_version, (
        "Setup failed: the pause and resume must advance the subscription version"
    )

    response = api.skip_subscription(
        subscription["id"], {"expected_subscription_version": stale_version}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    after = refresh_subscription(api, subscription)
    assert after["status"] == "ACTIVE"
    assert after["skipped_cycle_index"] is None
    assert after["pause_count"] == 1


def test_stale_box_order_version_finalize_is_refused(api):
    """PRD §2.10: "A finalise request must carry `expected_box_order_version`, holding the
    `BoxOrder` version the client last observed, and a value that no longer
    matches the order's current `version` — because a build or a reprice has
    rewritten the order's pricing and readiness fields since the client captured
    its view — is likewise refused with `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_layers/stale_box_order_version_finalize_is_refused
    """
    reset_clock(api)
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")
    customer, subscription = setup_subscriber(api, region="NE", email="of@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    stale_version = order["version"]

    response = api.finalize_box_order(
        order["id"], {"expected_box_order_version": stale_version - 1}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    current = validate_success(
        api.finalize_box_order(
            order["id"], {"expected_box_order_version": stale_version}, ADMIN
        ),
        200,
    )
    assert current["status"] == "AWAITING_WINDOW"


# ---------------------------------------------------------------------------
# The skip cascade into the build
# ---------------------------------------------------------------------------
def test_a_paused_subscription_blocks_the_pack_of_its_built_order(api):
    """PRD §3.7: "the order's subscription must be in `ACTIVE`, `SKIPPED` or
    `AUTO_SKIPPED` — a `PAUSED` or `CANCELLED` subscription's order cannot be packed."
    PRD §3.9: "Twelfth is subscription cadence eligibility"

    Design: Difficulty/transitive_cascade/subscription_skip_rejection_cascades_to_the_built_box
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    supplier = make_supplier(api, name="Skippable Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=200,
                   unit_cost_cents=100, quantity_available=200)
    lot = _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(api, region="NE", email="sk@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    built = build_order(api, order, center, line_plan((lot["id"], 6)))
    live = get_success_data(api.get_subscription(subscription["id"], ADMIN))

    validate_success(
        api.skip_subscription(
            live["id"], {"expected_subscription_version": live["version"]}, ADMIN
        ),
        200,
    )
    validate_success(api.pause_subscription(subscription["id"], {}, ADMIN), 200)

    response = api.pack_box_order(
        built["id"], {"expected_box_order_version": built["version"]},
        make_operator_headers(center["id"]),
    )
    # §3.9 scopes ERR_SUBSCRIPTION_INELIGIBLE to order creation (rung 12); the
    # pack's own subscription requirement in §3.7 names no error, so the
    # refusal may lawfully be reported as the state refusal instead.
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_SUBSCRIPTION_INELIGIBLE, ApiErrorId.ERR_INVALID_STATE],
    )

    subscription_read = refresh_subscription(api, subscription)
    assert subscription_read["status"] == "PAUSED"
    # §3.8: a skip records the serving cycle index plus one, and the
    # finalisation that preceded it advanced that index by one cadence period.
    assert subscription_read["skipped_cycle_index"] == (
        subscription_read["serving_cycle_index"] + 1
    )
    order_read = get_success_data(api.get_box_order(built["id"], ADMIN))
    assert order_read["status"] == "BUILDING"
    assert order_read["cold_chain_selected"] is False


def test_a_paused_subscription_blocks_the_pack_of_its_built_order_directly(api):
    """PRD §3.7: "the order's subscription must be in `ACTIVE`, `SKIPPED` or
    `AUTO_SKIPPED` — a `PAUSED` or `CANCELLED` subscription's order cannot be packed."
    PRD §3.7: "Packing an order is an operator operation and it is guarded by
    three requirements that must all hold."

    Design: Difficulty/cross_entity_state_dependency/box_pack_requires_the_subscription_not_to_be_paused
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    supplier = make_supplier(api, name="Cross Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=200,
                   unit_cost_cents=100, quantity_available=200)
    lot = _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(api, region="NE", email="xena@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    built = build_order(api, order, center, line_plan((lot["id"], 6)))
    validate_success(api.pause_subscription(subscription["id"], {}, ADMIN), 200)

    response = api.pack_box_order(
        built["id"], {"expected_box_order_version": built["version"]},
        make_operator_headers(center["id"]),
    )
    # The pack's subscription requirement names no error id in §3.7, so the
    # refusal is admitted as either the cadence error or the state refusal.
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_SUBSCRIPTION_INELIGIBLE, ApiErrorId.ERR_INVALID_STATE],
    )

    assert refresh_subscription(api, subscription)["status"] == "PAUSED"
    order_read = get_success_data(api.get_box_order(built["id"], ADMIN))
    assert order_read["status"] == "BUILDING"
    assert order_read["cold_chain_selected"] is False
