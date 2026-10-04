"""The order's parallel fulfillment/payment dimensions and the credit-hold boundary (PRD §2.8, §3.4, §3.6)."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import PROGRAM_MANAGER_HEADERS, WEEK_NEXT, order_line
from test_helpers import fixtures


def _two_order_credit_world(api, credit_limit_cents):
    """Account with the given limit; o1 acknowledged, o2 acknowledged into hold."""
    world = fixtures.setup_active_program(
        api, account_overrides={"credit_limit_cents": credit_limit_cents}
    )
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=100)
    fixtures.create_finish_batch(api)
    return world


def test_payment_release_unblocks_scheduling(api):
    """A held order's payment dimension clears when a sibling order is paid,
    without either order's fulfillment state moving.

    PRD §3.6: "An order carries two state dimensions that evolve independently."
    PRD §2.8: "Symmetrically, whenever a recompute finds the exposure at or below the limit, every order of that account currently sitting in `CREDIT_HOLD` flips back to `UNINVOICED`."
    PRD §2.8: "every order not in `CANCELLED` contributes its `quoted_total_cents` while its `payment_status` is `UNINVOICED` or `CREDIT_HOLD`, its `invoiced_total_cents` once `INVOICED`, and nothing once `PAID`."
    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_evolve_independently
    """
    world = _two_order_credit_world(api, 100000)
    # o1 is acknowledged before o2 is placed: per PRD §2.8 a SUBMITTED order
    # already contributes its quoted_total_cents to open_exposure_cents, so
    # o1's own acknowledgement is evaluated at 95000 <= 100000 only while o2
    # has not yet entered the sum.
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=10)]
    )
    fixtures.acknowledge_order(api, o1["id"])      # exposure 95000 <= 100000
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=1)],
    )
    o2_ack = fixtures.acknowledge_order(api, o2["id"])  # 104500 > 100000 -> hold
    assert o2_ack["payment_status"] == "CREDIT_HOLD"
    assert o2_ack["status"] == "ACKNOWLEDGED"

    # o1 walks fulfillment and payment independently of o2's hold.
    fixtures.schedule_order(api, o1["id"])
    fixtures.start_production(api, o1["id"])
    fixtures.complete_manufacturing(api, o1["id"])
    fixtures.invoice_order(api, o1["id"])
    o1_paid = fixtures.pay_order(api, o1["id"])
    assert o1_paid["payment_status"] == "PAID"
    assert o1_paid["status"] == "MFG_COMPLETE"

    # The payment recompute released o2's hold; its fulfillment state is untouched.
    o2_after = fixtures.get_order(api, o2["id"])
    assert o2_after["payment_status"] == "UNINVOICED"
    assert o2_after["status"] == "ACKNOWLEDGED"

    scheduled = fixtures.schedule_order(api, o2["id"])
    assert scheduled["status"] == "SCHEDULED"


def test_invoice_gate_requires_manufacturing_complete(api):
    """Invoicing is refused before MFG_COMPLETE; the payment dimension moves
    without touching fulfillment.

    PRD §3.6: "Invoicing, the `UNINVOICED` → `INVOICED` step driven by a `ProgramManager`, is legal only once the order stands in `MFG_COMPLETE`, `SHIPPED`, or `DELIVERED` (`ERR_INVALID_STATE` otherwise), and it applies the invoiced variant of the pricing rule."
    PRD §3.6: "Exactly two gates bind the dimensions together: scheduling requires `UNINVOICED` (§3.4), and invoicing requires the fulfillment side to be far enough along."
    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_evolve_independently
    """
    world = _two_order_credit_world(api, 100000000)
    order = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=1)]
    )
    fixtures.acknowledge_order(api, order["id"])

    early = api.transition_order_financial(
        order["id"], {"to_status": "INVOICED"}, PROGRAM_MANAGER_HEADERS
    )
    validate_error(early, "ERR_INVALID_STATE")
    unchanged = fixtures.get_order(api, order["id"])
    assert unchanged["status"] == "ACKNOWLEDGED"
    assert unchanged["payment_status"] == "UNINVOICED"

    fixtures.schedule_order(api, order["id"])
    fixtures.start_production(api, order["id"])
    fixtures.complete_manufacturing(api, order["id"])
    invoiced = fixtures.invoice_order(api, order["id"])
    assert invoiced["payment_status"] == "INVOICED"
    assert invoiced["status"] == "MFG_COMPLETE"
    paid = fixtures.pay_order(api, order["id"])
    assert paid["payment_status"] == "PAID"
    assert paid["status"] == "MFG_COMPLETE"


def test_exposure_equal_to_limit_passes_one_cent_over_holds(api):
    """Exposure exactly at the limit passes; one order past it lands on hold.

    PRD §2.8: "An order moves onto `CREDIT_HOLD` when the account's `open_exposure_cents` is strictly greater than its `credit_limit_cents`; an exposure exactly equal to the limit passes without a hold."
    PRD §3.4: "Acknowledgement sets the order's `price_lock` to true and runs the credit evaluation of §2.8: if including the order pushes the account's `open_exposure_cents` strictly above its `credit_limit_cents`, the order's `payment_status` becomes `CREDIT_HOLD`; otherwise it stays `UNINVOICED`."
    Design: Difficulty/boundary_precision_check/credit_limit_equality_passes_one_cent_over_holds
    """
    world = fixtures.setup_active_program(
        api, account_overrides={"credit_limit_cents": 95000}
    )
    # Each order is acknowledged before the next is placed: per PRD §2.8 a
    # SUBMITTED order already contributes its quoted_total_cents to the
    # account's open_exposure_cents, so the boundary reading is only isolated
    # when the sibling has not yet entered the sum.
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=6)]
    )
    fixtures.acknowledge_order(api, o1["id"])  # 57000

    # 57000 + 38000 = 95000 == limit: boundary is inclusive-pass.
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=4)],
    )
    o2_ack = fixtures.acknowledge_order(api, o2["id"])
    assert o2_ack["status"] == "ACKNOWLEDGED"
    assert o2_ack["payment_status"] == "UNINVOICED"

    # +9500 -> 104500 > 95000: strictly over, so o3 holds.
    o3 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="3 Job Ln", lines=[order_line(quantity=1)],
    )
    o3_ack = fixtures.acknowledge_order(api, o3["id"])
    assert o3_ack["status"] == "ACKNOWLEDGED"
    assert o3_ack["payment_status"] == "CREDIT_HOLD"

    account = fixtures.get_account(api, world["account"]["id"])
    assert account["open_exposure_cents"] == 104500


def test_exact_limit_boundary_single_orders(api):
    """A one-order account at exactly its limit stays clear; the next holds.

    PRD §2.8: "An order moves onto `CREDIT_HOLD` when the account's `open_exposure_cents` is strictly greater than its `credit_limit_cents`; an exposure exactly equal to the limit passes without a hold."
    Design: Difficulty/boundary_precision_check/credit_limit_equality_passes_one_cent_over_holds
    """
    world = fixtures.setup_active_program(
        api, account_overrides={"credit_limit_cents": 9500}
    )
    # Each order is acknowledged before the next is placed: per PRD §2.8 a
    # SUBMITTED order already contributes its quoted_total_cents to the
    # account's open_exposure_cents, so the boundary reading is only isolated
    # when the sibling has not yet entered the sum.
    o1 = fixtures.place_order(api, world["account"], world["program"])
    o1_ack = fixtures.acknowledge_order(api, o1["id"])  # exposure 9500 == 9500
    assert o1_ack["payment_status"] == "UNINVOICED"

    o2 = fixtures.place_order(
        api, world["account"], world["program"], jobsite_address="2 Job Ln"
    )
    o2_ack = fixtures.acknowledge_order(api, o2["id"])  # 19000 > 9500
    assert o2_ack["payment_status"] == "CREDIT_HOLD"

    account = fixtures.get_account(api, world["account"]["id"])
    assert account["open_exposure_cents"] == 19000
