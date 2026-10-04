"""Builder credit lifecycle: initial state, approval, and exposure reads."""
from test_helpers import (
    approve_builder,
    create_builder,
    get_builder_exposure,
    set_clock,
    setup_order_confirmed,
    create_order,
    confirm_order,
    request_delivery,
    create_truck_shift,
    schedule_delivery,
    complete_delivery,
)
from test_helpers import api_client as api
from test_helpers.fixtures import CREDIT


def test_builder_created_provisional_then_approve_activates():
    """PRD §3.4: "A new builder's credit_status is PROVISIONAL, its
    credit_limit_cents is 0, and both exposure counters start at 0." and
    "Approving a PROVISIONAL builder moves it to ACTIVE and sets
    credit_limit_cents; the limit must be present and greater than 0."

    Design: Corner/state_machines/builder_created_provisional_then_approve_activates
    """
    builder = create_builder()
    assert builder["credit_status"] == "PROVISIONAL"
    assert builder["credit_limit_cents"] == 0
    assert builder["exposure_committed_cents"] == 0
    assert builder["exposure_settled_cents"] == 0
    v0 = builder["version"]

    approved = approve_builder(builder["id"], 5000000)
    assert approved["credit_status"] == "ACTIVE"
    assert approved["credit_limit_cents"] == 5000000
    assert approved["version"] == v0 + 1


def test_builder_exposure_committed_includes_undelivered_settled_does_not():
    """PRD §3.4: "exposure_committed_cents is the sum of order_total_cents
    over the builder's orders in CONFIRMED or ON_HOLD, and
    exposure_settled_cents is the sum of delivered_total_cents over the
    builder's orders in DELIVERED; a computed exposure read also reports
    credit_limit_cents and credit_headroom_cents, the last being the credit
    limit minus committed exposure minus settled exposure."

    Design: Difficulty/dual_variant_calc/builder_exposure_committed_includes_undelivered_settled_does_not
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_order_confirmed(
        credit_limit_cents=20000000, order_qty=20, unit_price_cents=100000
    )
    builder = scenario["builder"]
    branch = scenario["branch"]
    job = scenario["job"]
    product = scenario["product"]
    o1 = scenario["order"]

    o2 = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=30, unit_price_cents=100000, product_id=product["id"],
    )
    o2 = confirm_order(o2["id"])

    d2 = request_delivery(o2["id"])
    shift = create_truck_shift()
    d2 = schedule_delivery(d2["id"], shift["id"])
    set_clock("2026-09-10T13:00:00Z")
    complete_delivery(d2["id"], "COMPLETED")

    exposure = get_builder_exposure(builder["id"])
    assert exposure["exposure_committed_cents"] == 2000000
    assert exposure["exposure_settled_cents"] == 3000000
    assert exposure["credit_limit_cents"] == 20000000
    assert exposure["credit_headroom_cents"] == 15000000

    o1_now = api.get_sales_order(o1["id"], CREDIT).json()["data"]
    o2_now = api.get_sales_order(o2["id"], CREDIT).json()["data"]
    assert o1_now["order_status"] == "CONFIRMED"
    assert o2_now["order_status"] == "DELIVERED"


def test_builder_exposure_headroom_recomputed_on_second_confirm():
    """PRD §3.4: "a computed exposure read also reports credit_limit_cents and
    credit_headroom_cents, the last being the credit limit minus committed
    exposure minus settled exposure." Two confirmed-but-undelivered orders
    both count in committed, and headroom reflects the running sum.

    Design: Difficulty/dual_variant_calc/builder_exposure_committed_includes_undelivered_settled_does_not
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_order_confirmed(
        credit_limit_cents=20000000, order_qty=20, unit_price_cents=100000
    )
    builder = scenario["builder"]
    branch = scenario["branch"]
    job = scenario["job"]
    product = scenario["product"]

    o2 = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=30, unit_price_cents=100000, product_id=product["id"],
    )
    confirm_order(o2["id"])

    exposure = get_builder_exposure(builder["id"])
    assert exposure["exposure_committed_cents"] == 5000000
    assert exposure["exposure_settled_cents"] == 0
    assert exposure["credit_headroom_cents"] == 15000000
