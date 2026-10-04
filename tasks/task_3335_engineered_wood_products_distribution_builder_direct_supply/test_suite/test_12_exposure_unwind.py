"""Direct-order behavior and exposure unwind assertions."""
from test_helpers import (
    ApiErrorId,
    cancel_order,
    confirm_order,
    create_branch,
    create_order,
    create_product,
    create_truck_shift,
    get_builder,
    get_builder_exposure,
    get_job,
    receive_lot,
    request_delivery,
    schedule_delivery,
    set_clock,
    setup_builder_with_job,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import ACCT, CREDIT


def test_confirm_then_cancel_restores_builder_committed_exposure_cents():
    """PRD §3.6: "A successful confirm moves the order to CONFIRMED, adds
    order_total_cents to both the builder's and the job's
    exposure_committed_cents" and "From CONFIRMED, cancellation additionally
    ... subtracts order_total_cents from both committed-exposure counters".

    Design: Difficulty/compensating_invariant/confirm_then_cancel_restores_builder_committed_exposure_cents
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 100, 40000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=20,
                         unit_price_cents=100000, product_id=product["id"])
    confirm_order(order["id"])

    exposure = get_builder_exposure(builder["id"])
    assert exposure["exposure_committed_cents"] == 2000000
    assert get_job(job["id"])["exposure_committed_cents"] == 2000000

    cancel_order(order["id"])

    exposure = get_builder_exposure(builder["id"])
    assert exposure["exposure_committed_cents"] == 0
    assert exposure["exposure_settled_cents"] == 0
    assert get_job(job["id"])["exposure_committed_cents"] == 0


def test_cancel_from_on_hold_unwinds_committed_without_touching_lots():
    """PRD §3.6: "From ON_HOLD, cancellation subtracts order_total_cents from
    both committed counters without touching lots, since suspension already
    released them."

    Design: Difficulty/compensating_invariant/confirm_then_cancel_restores_builder_committed_exposure_cents
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    lot = receive_lot(branch["id"], product["id"], 10, 40000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                         unit_price_cents=100000, product_id=product["id"])
    confirm_order(order["id"])

    resp = api.credit_review(builder["id"], {"decision": "SUSPEND"}, CREDIT)
    validate_success(resp)

    from test_helpers import get_lot, get_order
    assert get_order(order["id"])["order_status"] == "ON_HOLD"
    l_mid = get_lot(lot["id"])
    assert l_mid["qty_reserved_mbf"] == 0
    assert l_mid["qty_available_mbf"] == 10

    cancel_order(order["id"])

    exposure = get_builder_exposure(builder["id"])
    assert exposure["exposure_committed_cents"] == 0
    assert exposure["exposure_settled_cents"] == 0
    assert get_job(job["id"])["exposure_committed_cents"] == 0

    # Lots untouched by the ON_HOLD cancel (already released by suspension).
    l = get_lot(lot["id"])
    assert l["qty_reserved_mbf"] == 0
    assert l["qty_available_mbf"] == 10
    assert l["qty_sold_mbf"] == 0
