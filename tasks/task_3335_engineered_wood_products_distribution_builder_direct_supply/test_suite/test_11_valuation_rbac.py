"""Valuation variant divergence and RBAC/validation-priority tests."""
from test_helpers import (
    ApiErrorId,
    complete_delivery,
    confirm_order,
    create_active_builder,
    create_branch,
    create_job,
    create_order,
    create_order_line,
    create_product,
    create_sales_order_payload,
    create_takeoff,
    create_truck_shift,
    get_builder,
    get_lot,
    get_order,
    get_takeoff,
    make_builder_contact_headers,
    receive_lot,
    request_delivery,
    schedule_delivery,
    set_clock,
    setup_builder_with_job,
    submit_design,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import ACCT, BRANCH_MGR, CREDIT, FLEET


def _drive_delivery_to_completion(order_id, clock_at="2026-09-10T13:00:00Z"):
    delivery = request_delivery(order_id)
    shift = create_truck_shift()
    schedule_delivery(delivery["id"], shift["id"])
    set_clock(clock_at)
    return complete_delivery(delivery["id"], "COMPLETED")


def test_valuation_fifo_vs_weighted_average_diverge_on_same_lots():
    """PRD §3.3: "The FIFO figure, returned as fifo_value_cents, values each
    lot with remaining quantity — remaining being qty_available_mbf plus
    qty_reserved_mbf, sold quantity excluded — at that lot's own
    unit_cost_cents_per_mbf, walking lots oldest-first by received_at
    ascending with created_at ascending as the tie-break, which is the same
    order in which sales consume lots. The weighted-average figure, returned
    as weighted_avg_value_cents, computes a pool average cost per mbf as the
    sum of each lot's qty_received_mbf times its unit_cost_cents_per_mbf,
    divided by the sum of qty_received_mbf, over all lots ever received at the
    branch; the remaining value is that pool average multiplied by the total
    remaining quantity, rounded half-up to integer cents, and sales decrement
    the pool at the pool average rather than at any lot's own cost. ... The
    response also carries delta_cents, the difference between the two
    figures."

    Design: Difficulty/dual_variant_calc/valuation_fifo_vs_weighted_average_diverge_on_same_lots
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    set_clock("2026-09-02T08:00:00Z")
    lot1 = receive_lot(branch["id"], product["id"], 10, 50000)
    set_clock("2026-09-03T08:00:00Z")
    receive_lot(branch["id"], product["id"], 10, 60000)
    builder, job = setup_builder_with_job(5000000)
    set_clock("2026-09-04T08:00:00Z")
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                         unit_price_cents=100000, product_id=product["id"])
    confirm_order(order["id"])
    _drive_delivery_to_completion(order["id"])

    valuation = validate_success(api.get_branch_valuation(branch["id"], BRANCH_MGR))
    assert valuation["fifo_value_cents"] == 600000, (
        "FIFO values the remaining lot at its own cost 10 * 60000, "
        f"got {valuation['fifo_value_cents']}"
    )
    assert valuation["weighted_avg_value_cents"] == 550000, (
        f"pool average 55000 * 10 remaining mbf, got {valuation['weighted_avg_value_cents']}"
    )
    assert valuation["delta_cents"] == 50000

    l1 = get_lot(lot1["id"])
    assert l1["lot_status"] == "SOLD_OUT"
    assert l1["qty_sold_mbf"] == 10


def test_valuation_sales_decrement_pool_at_average_not_lot_cost():
    """PRD §3.3: "sales decrement the pool at the pool average rather than at
    any lot's own cost." After selling 5 of 20 mbf from two uneven-cost lots,
    the weighted figure is the pool average times the remaining quantity —
    15 mbf * 55000 = 825000 — not the sum of per-lot residual costs.

    Design: Difficulty/dual_variant_calc/valuation_fifo_vs_weighted_average_diverge_on_same_lots
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    set_clock("2026-09-02T08:00:00Z")
    receive_lot(branch["id"], product["id"], 10, 50000)
    set_clock("2026-09-03T08:00:00Z")
    receive_lot(branch["id"], product["id"], 10, 60000)
    builder, job = setup_builder_with_job(5000000)
    set_clock("2026-09-04T08:00:00Z")
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=5,
                         unit_price_cents=100000, product_id=product["id"])
    confirm_order(order["id"])
    _drive_delivery_to_completion(order["id"])

    valuation = validate_success(api.get_branch_valuation(branch["id"], BRANCH_MGR))
    # FIFO: L1 has 5 remaining @ 50000 plus L2 has 10 @ 60000.
    assert valuation["fifo_value_cents"] == 850000
    # Weighted: pool average 55000 * 15 remaining.
    assert valuation["weighted_avg_value_cents"] == 825000
    assert valuation["delta_cents"] == 25000


def test_missing_role_header_returns_context_header_error():
    """PRD §2.1: "Every request must carry two headers: X-User-ID and
    X-User-Role. If either header is missing, or if X-User-Role does not match
    one of the declared role names below, the request is rejected with
    ERR_MISSING_OR_INVALID_CONTEXT_HEADER (HTTP 400)." PRD §2.8: "first, the
    context-header check (ERR_MISSING_OR_INVALID_CONTEXT_HEADER); second, the
    role-and-ownership check (ERR_FORBIDDEN); third, identifier existence
    (ERR_NOT_FOUND)".

    Design: Corner/validations/missing_role_header_returns_context_header_error
    """
    resp = api._request(
        "GET",
        "/sales-orders/8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
        headers={"X-User-ID": "test-anon-1"},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER)


def test_confirm_nonexistent_order_existence_beats_state():
    """PRD §2.5: "Path parameters are validated strictly left-to-right: each
    identifier in a nested URL must exist before the next is examined, and the
    first missing identifier short-circuits the request with ERR_NOT_FOUND
    (HTTP 404)."

    Design: Corner/validations/confirm_nonexistent_order_existence_beats_state
    """
    resp = api.confirm_sales_order(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ACCT
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_builder_contact_cannot_confirm_order():
    """PRD §4: POST /sales-orders/{order_id}/confirm is authorized for
    AccountManager only; PRD §2.1: "a permitted-role failure, or an
    entity-ownership failure described below, yields ERR_FORBIDDEN
    (HTTP 403)".

    Design: Corner/rbac/builder_contact_cannot_confirm_order
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 100, 40000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                         unit_price_cents=100000, product_id=product["id"])

    resp = api.confirm_sales_order(
        order["id"], make_builder_contact_headers(builder["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_order(order["id"])["order_status"] == "DRAFT"


def test_credit_manager_cannot_create_orders_segregation_of_duties():
    """PRD §2.1: "CreditManager — credit officer; onboards builders, runs
    credit reviews, files and releases liens. Deliberately segregated from
    order entry." PRD §4: POST /jobs/{job_id}/sales-orders is authorized for
    AccountManager only.

    Design: Corner/rbac/credit_manager_cannot_create_orders_segregation_of_duties
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    builder, job = setup_builder_with_job(5000000)
    version = get_builder(builder["id"])["version"]

    resp = api.create_sales_order(
        job["id"],
        create_sales_order_payload(
            branch["id"],
            version,
            lines=[create_order_line(product["id"], qty_mbf=10)],
        ),
        CREDIT,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    orders, _meta = validate_paginated(
        api.list_sales_orders(ACCT, params={"job_id": job["id"]})
    )
    assert orders == []


def test_builder_contact_cannot_touch_other_builders_takeoff():
    """PRD §2.1: "requesting a revision on a quoted take-off, and accepting a
    quoted take-off all require that the calling BuilderContact's X-User-ID
    equal the builder_id of the job that owns the take-off; any mismatch is
    ERR_FORBIDDEN."

    Design: Corner/rbac/builder_contact_cannot_touch_other_builders_takeoff
    """
    set_clock("2026-09-01T00:00:00Z")
    b1 = create_active_builder(5000000, "Alpha Homes", "ID")
    b2 = create_active_builder(5000000, "Beta Homes", "WA")
    job2 = create_job(b2["id"], job_name="Beta Lot 2")
    t2 = create_takeoff(job2["id"], b2["id"], plan_reference="PLAN-B")
    submit_design(t2["id"], design_package_reference="DSN-B",
                  quoted_total_cents=810000)

    resp = api.revise_takeoff(
        t2["id"],
        {"revision_note": "intruder revision"},
        make_builder_contact_headers(b1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    t2_now = get_takeoff(t2["id"])
    assert t2_now["takeoff_status"] == "QUOTED"
    assert t2_now["revision_count"] == 0


def test_fleet_coordinator_cannot_create_products():
    """PRD §4: POST /products is authorized for OpsAdmin only; PRD §2.1: "a
    permitted-role failure, or an entity-ownership failure described below,
    yields ERR_FORBIDDEN (HTTP 403)".

    Design: Corner/rbac/fleet_coordinator_cannot_create_products
    """
    resp = api.create_product(
        {
            "sku_code": "LVL-DF-16",
            "product_family": "LVL_BEAM",
            "species": "DOUGLAS_FIR",
            "dimension_label": "16in",
        },
        FLEET,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
