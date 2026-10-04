"""Corner coverage — commemorative program and numismatic product state
machines (PRD §3.5, §3.6): the design-review self-loop, clock-driven sales
windows, disbursement gates (state and segregation of duties), product
orderability gates, and the withdrawal cascade."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UserRole,
    make_collector_headers,
    make_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_numismatic_order,
    assert_numismatic_product,
    assert_order_derived_status,
)
from test_helpers.factories import create_order_payload
from test_helpers.fixtures import (
    approve_program,
    create_collector,
    create_product,
    create_program,
    get_order,
    get_product,
    pay_order,
    place_order,
    set_clock,
    setup_on_sale_product,
    setup_on_sale_program,
    setup_sales_closed_program,
    setup_subscription,
)
from test_helpers.test_users import PROGRAM_MANAGER_USER_ID

MANAGER = TEST_USERS["program_manager_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def _get_program(api, program_id):
    return validate_success(api.get_program(program_id, MANAGER))


def test_program_revision_self_loop_increments_count(api):
    """PRD §3.5: "The creating user's id is recorded as `created_by_user_id`,
    and the program enters `DESIGN_REVIEW` with `design_revision_count` at
    zero."
    PRD §3.5: "Design authority rests with the `MintDirector`, whose `decision`
    either approves the design — moving the program `DESIGN_REVIEW →
    APPROVED_FOR_SALE` — or requests revisions, a deliberate self-loop that
    keeps the program in `DESIGN_REVIEW` while incrementing
    `design_revision_count` for legislation-driven redesign cycles."

    Design: Corner/state_machines/program_revision_self_loop_increments_count
    """
    program = create_program(api, name="Loop Program",
                             statute_reference="PL 119-20")
    assert program["status"] == "DESIGN_REVIEW"
    assert program["design_revision_count"] == 0

    program = approve_program(api, program["id"], decision="REVISION_REQUESTED")
    assert program["status"] == "DESIGN_REVIEW"
    assert program["design_revision_count"] == 1
    program = approve_program(api, program["id"], decision="REVISION_REQUESTED")
    assert program["status"] == "DESIGN_REVIEW"
    assert program["design_revision_count"] == 2

    program = approve_program(api, program["id"], decision="APPROVED")
    assert program["status"] == "APPROVED_FOR_SALE"
    assert program["design_revision_count"] == 2, (
        "approval is not a revision; the count stays at 2")


def test_program_sales_window_opens_and_closes_on_clock(api):
    """PRD §3.5: "When a clock-set sweep finds the clock at or past
    `sales_window_start`, an `APPROVED_FOR_SALE` program moves to `ON_SALE`
    and, in the same sweep, each of the program's products still in `SCHEDULED`
    whose `release_datetime` has been reached also moves to `ON_SALE`. When a
    sweep finds the clock at or past `sales_window_end`, an `ON_SALE` program
    moves to `SALES_CLOSED`."

    Design: Corner/state_machines/program_sales_window_opens_and_closes_on_clock
    """
    program = create_program(api, name="Window Program",
                             statute_reference="PL 119-21",
                             sales_window_start="2026-09-15T00:00:00Z",
                             sales_window_end="2026-12-31T00:00:00Z")
    approve_program(api, program["id"])

    set_clock(api, "2026-09-14T00:00:00Z")
    program = _get_program(api, program["id"])
    assert program["status"] == "APPROVED_FOR_SALE", (
        "the day before window start the sweep must not open sales")

    set_clock(api, "2026-09-15T00:00:00Z")
    program = _get_program(api, program["id"])
    assert program["status"] == "ON_SALE", (
        "at sales_window_start exactly (inclusive) the program opens")

    set_clock(api, "2026-12-31T00:00:00Z")
    program = _get_program(api, program["id"])
    assert program["status"] == "SALES_CLOSED", (
        "at sales_window_end exactly (inclusive) the program closes")


def test_program_disburse_before_sales_closed_rejected(api):
    """PRD §3.5: "Disbursement requires the program to be in `SALES_CLOSED` —
    any other state is rejected with `ERR_PROGRAM_NOT_DISBURSABLE` (422) — and
    the officer's `X-User-ID` must differ from the program's
    `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, 422, per §2.10)."

    Design: Corner/state_machines/program_disburse_before_sales_closed_rejected
    """
    program = setup_on_sale_program(api, name="Early Disburse",
                                    statute_reference="PL 119-22")
    assert program["status"] == "ON_SALE"

    # The disburser is not the creator, so only the state gate can fire.
    resp = api.disburse_surcharges(program["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_DISBURSABLE)
    assert _get_program(api, program["id"])["status"] == "ON_SALE"


def test_disburse_segregation_creator_cannot_disburse(api):
    """PRD §2.10: "Surcharge disbursement must be performed by a
    `FinanceOfficer` whose `X-User-ID` differs from the program's recorded
    `created_by_user_id`."
    PRD §3.5: "Disbursement requires the program to be in `SALES_CLOSED` — any
    other state is rejected with `ERR_PROGRAM_NOT_DISBURSABLE` (422) — and the
    officer's `X-User-ID` must differ from the program's `created_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`, 422, per §2.10)."

    Design: Corner/state_machines/disburse_segregation_creator_cannot_disburse
    """
    # The default creator is the program manager whose id is pm-1; the program
    # is swept past its window into SALES_CLOSED.
    program = setup_sales_closed_program(api, name="SoD Program",
                                         statute_reference="PL 119-23")
    assert program["status"] == "SALES_CLOSED"
    assert program["created_by_user_id"] == PROGRAM_MANAGER_USER_ID

    resp = api.disburse_surcharges(
        program["id"],
        make_headers(PROGRAM_MANAGER_USER_ID, UserRole.FINANCE_OFFICER.value))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    program = _get_program(api, program["id"])
    assert program["status"] == "SALES_CLOSED"
    assert program["disbursed_cents"] == 0


def test_order_on_scheduled_product_rejected(api):
    """PRD §3.6: "The `product_id` must resolve to an existing product
    (`ERR_UNKNOWN_PRODUCT`, 422) that is in `ON_SALE` or `SOLD_OUT`; orders
    against `SCHEDULED` or `WITHDRAWN` products are rejected with
    `ERR_PRODUCT_NOT_ORDERABLE` (422)."

    Design: Corner/state_machines/order_on_scheduled_product_rejected
    """
    # Release lies in the future and the clock stays at boot: SCHEDULED.
    product = create_product(api, product_code="FUT-1", product_family="F1",
                             product_type="PROOF_SET", price_cents=2000,
                             mintage_limit=100, household_order_limit=10,
                             release_datetime="2026-10-01T00:00:00Z")
    collector = create_collector(api, full_name="Early Bird",
                                 email="early@example.com", household_id="HH-1")

    resp = api.create_order(
        create_order_payload(product_id=product["id"], quantity=1),
        make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_ORDERABLE)
    assert get_product(api, product["id"])["status"] == "SCHEDULED"


def test_order_on_withdrawn_product_rejected(api):
    """PRD §3.6: "The `product_id` must resolve to an existing product
    (`ERR_UNKNOWN_PRODUCT`, 422) that is in `ON_SALE` or `SOLD_OUT`; orders
    against `SCHEDULED` or `WITHDRAWN` products are rejected with
    `ERR_PRODUCT_NOT_ORDERABLE` (422)."
    PRD §3.6: "Withdrawal runs no waitlist promotion, because the product is
    finished selling; `WITHDRAWN` is the product's only terminal state."

    Design: Corner/state_machines/order_on_withdrawn_product_rejected
    """
    product = setup_on_sale_product(api, product_code="WDR-1",
                                    product_family="F1", price_cents=2000,
                                    mintage_limit=100, household_order_limit=10)
    withdrawn = validate_success(api.withdraw_product(product["id"], MANAGER))
    assert withdrawn["status"] == "WITHDRAWN"
    collector = create_collector(api, full_name="Late Buyer",
                                 email="late@example.com", household_id="HH-1")

    resp = api.create_order(
        create_order_payload(product_id=product["id"], quantity=1),
        make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_ORDERABLE)
    assert get_product(api, product["id"])["status"] == "WITHDRAWN"


def test_product_withdraw_blocked_by_active_subscription(api):
    """PRD §3.6: "A `ProgramManager` may withdraw a product from `SCHEDULED`,
    `ON_SALE`, or `SOLD_OUT` — but never while any subscription in `ACTIVE` or
    `DUNNING` references it, and never once it is `WITHDRAWN`; both violations
    are rejected with `ERR_PRODUCT_NOT_WITHDRAWABLE` (422)."

    Design: Corner/state_machines/product_withdraw_blocked_by_active_subscription
    """
    product, _, subscription = setup_subscription(api)
    assert subscription["status"] == "ACTIVE"

    resp = api.withdraw_product(product["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_WITHDRAWABLE)
    assert get_product(api, product["id"])["status"] == "ON_SALE"


def test_product_withdraw_cancels_and_refunds_orders(api):
    """PRD §3.6: "Withdrawal cascades through the order book: every order of
    the product in `ALLOCATED` or `WAITLISTED` flips to `RELEASED`, which makes
    its derived status `CANCELLED`, and each such order already `PAID` is
    refunded to `REFUNDED`."
    PRD §3.6: "Withdrawal runs no waitlist promotion, because the product is
    finished selling; `WITHDRAWN` is the product's only terminal state."
    PRD §3.6: "A sold-out product still accepts orders — they join its
    waitlist."
    PRD §3.6: "It is derived from the two parallel dimensions the order
    actually carries: `CANCELLED` exactly when `allocation_status` is
    `RELEASED`; `COMPLETED` exactly when `payment_status` is `PAID` and
    `allocation_status` is `ALLOCATED`; and `ACTIVE` in every other
    combination."

    Design: Corner/state_machines/product_withdraw_cancels_and_refunds_orders
    """
    product = setup_on_sale_product(api, product_code="WDR-2",
                                    product_family="WFAM", price_cents=2000,
                                    mintage_limit=3, household_order_limit=9)
    payer = create_collector(api, full_name="Payer", email="py@example.com",
                             household_id="HH-1")
    waiter = create_collector(api, full_name="Waiter", email="wt@example.com",
                              household_id="HH-2")

    order_paid = place_order(api, product["id"], payer, 3)
    assert order_paid["allocation_status"] == "ALLOCATED"
    product = get_product(api, product["id"])
    assert product["status"] == "SOLD_OUT"  # 3 == mintage_limit
    order_paid = pay_order(api, order_paid, payer)
    assert order_paid["payment_status"] == "PAID"

    # SOLD_OUT still accepts orders; this one waitlists.
    order_wait = place_order(api, product["id"], waiter, 1)
    assert order_wait["allocation_status"] == "WAITLISTED"

    withdrawn = validate_success(api.withdraw_product(product["id"], MANAGER))
    assert_numismatic_product(withdrawn)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["allocated_units"] == 0

    order_paid = get_order(api, order_paid["id"])
    assert_numismatic_order(order_paid)
    assert_order_derived_status(order_paid)
    assert order_paid["payment_status"] == "REFUNDED"
    assert order_paid["allocation_status"] == "RELEASED"
    assert order_paid["status"] == "CANCELLED"

    order_wait = get_order(api, order_wait["id"])
    assert_numismatic_order(order_wait)
    assert_order_derived_status(order_wait)
    assert order_wait["allocation_status"] == "RELEASED"
    assert order_wait["payment_status"] == "UNPAID", (
        "a never-paid waitlisted order is released without a refund")
    assert order_wait["status"] == "CANCELLED", (
        "no promotion runs into a terminal product")
