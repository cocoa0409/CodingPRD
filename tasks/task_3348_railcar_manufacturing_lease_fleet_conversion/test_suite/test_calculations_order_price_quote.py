"""Order price quote: line ceilings, the fee cap and the two quote bases.

The quote is the arithmetic core of the backlog: each bill-of-material line is
rounded up to a whole dollar before it is summed, the labour charge is added
once, and the change fee is the smaller of the per-endorsement fee and the
eight-percent cap. The same algorithm runs on two bases, and which one is read
is decided by the order's own state rather than by the caller.

Every expected figure below is recomputed from the PRD's stated formula against
the catalogue the fixture actually builds.
"""

from test_helpers import (
    CLOCK_START_ISO,
    TEST_USERS,
    api_client,
    approve_endorsement,
    create_component_payload,
    create_endorsement,
    create_order,
    days_between,
    get_success_data,
    reserve_order,
    set_clock,
    worst_gated_lead_days,
)

from test_calculations_support import ADMIN, SUPPLY, box_car_catalogue

LEASE = TEST_USERS["lease_administrator_headers"]


def test_three_line_committed_quote_sums_ceiled_lines_and_labor(api):
    """PRD §3.1: "The line amount for the row is then the effective quantity
    multiplied by the component's `unit_cost_cents`, plus a line surcharge of
    25,000 cents, divided by one hundred, rounded up to the next whole number,
    and multiplied back by one hundred — that is, each line is rounded up to the
    next whole dollar before it is summed."
    PRD §3.1: "The labor charge is the car type's `build_hours` multiplied by the
    labor rate of 45,000 cents per build hour. The unrounded total is the
    component subtotal plus the labor charge."
    PRD §3.1: "The change fee actually charged is the smaller of the raw fee and
    the cap, and the order's `unit_price_cents` is the unrounded total plus that
    change fee."

    A three-row bill of materials is quoted on the day it is taken, so the
    forecast substitution window is empty and the draft quote equals the
    committed re-quote. The wheelset line is 4 * 18000 + 25000 = 97000, the
    casting line 2 * 40000 + 25000 = 105000 and the coating line
    3 * 12500 + 25000 = 62500, giving a 264500 subtotal; thirty build hours of
    labour add 1350000 and no endorsement is in force, so the quote is 1614500.

    Design: Corner/calculations/order_price_quote_correct_result_three_line_committed_quote
    """
    set_clock(CLOCK_START_ISO)
    catalogue = box_car_catalogue()
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=150,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )

    assert days_between("2026-09-01", "2026-12-01") == 91
    assert worst_gated_lead_days(catalogue) == 23, (
        "the gate is cleared by a wide margin, so it cannot be what stops the order"
    )
    assert order["status"] == "DRAFT"
    assert order["unit_price_cents"] == 1614500, (
        "per-line ceilings are summed before the labour charge is added"
    )

    reserved = reserve_order(order["id"])
    assert reserved["status"] == "COMPONENT_RESERVED"
    assert reserved["unit_price_cents"] == 1614500, (
        "the committed re-quote reads the same locked costs on the order date"
    )


def test_pending_endorsement_is_excluded_from_the_quote_until_approved(api):
    """PRD §3.1: "For each row, the effective quantity is the
    `substitute_qty_per_car` of the endorsement on this order whose
    `original_component_id` matches the row's `component_id` and whose status is
    `APPROVED` or `APPLIED`, if such an endorsement exists; otherwise the
    effective quantity is the row's own `qty_per_car`. Endorsements in `PENDING`,
    `REJECTED` or `SUPERSEDED` status are excluded from that substitution set
    entirely and never affect the quote."
    PRD §3.3: "On success the endorsement becomes `APPROVED`, the production
    order's `unit_price_cents` is recomputed on the committed basis of §3.1 with
    the endorsed substitute standing in for the original component"

    The same endorsement leaves the quote at 1614500 while it is pending and
    moves it to 1617500 once approved: the wheelset line re-prices from
    4 * 18000 + 25000 = 97000 to 3 * 20000 + 25000 = 85000, the subtotal falls
    to 252500, and the single approved endorsement adds the raw 15000-cent fee
    under the 128200-cent cap.

    Design: Corner/calculations/order_price_quote_pending_endorsement_excluded_from_input_set
    """
    set_clock(CLOCK_START_ISO)
    catalogue = box_car_catalogue()
    substitute = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-220",
                component_class="WHEELSET",
                unit_cost_cents=20000,
                lead_time_days=30,
                on_hand_qty=100,
            ),
            SUPPLY,
        )
    )
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=150,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    reserved = reserve_order(order["id"])
    assert reserved["unit_price_cents"] == 1614500

    endorsement = create_endorsement(
        order,
        catalogue["wheelset"],
        substitute,
        substitute_qty_per_car=3,
        decides_material=True,
    )
    assert endorsement["status"] == "PENDING"

    while_pending = get_success_data(
        api_client.get_production_order(order["id"], ADMIN)
    )
    assert while_pending["unit_price_cents"] == 1614500, (
        "a pending endorsement is outside the substitution set"
    )

    approved = approve_endorsement(endorsement["id"], LEASE)
    assert approved["status"] == "APPROVED"

    after_approval = get_success_data(
        api_client.get_production_order(order["id"], ADMIN)
    )
    assert after_approval["unit_price_cents"] == 1617500, (
        "the approved substitute re-prices its row and adds one change fee"
    )
    assert after_approval["unit_price_cents"] - while_pending["unit_price_cents"] == 3000


def test_quote_reads_every_named_constant_including_the_fee_cap(api):
    """PRD §3.1: "The component subtotal is the sum of those line amounts, in
    the row order established above."
    PRD §3.1: "The change-fee cap is 8 percent of the unrounded total, floored to
    a whole cent. The raw change fee is 15,000 cents multiplied by the number of
    endorsements on this order whose status is `APPROVED` or `APPLIED`."
    PRD §3.1: "The change fee actually charged is the smaller of the raw fee and
    the cap"

    Two approved substitutions that carry their originals' costs leave the
    subtotal and the labour charge untouched at 309500, so the whole movement is
    the fee term: 309500 + 15000 with one endorsement and 309500 + 24760 with
    two, because the raw 30000-cent fee is clipped by the eight-percent cap of
    24760.

    Design: Corner/calculations/order_price_quote_constants_line_surcharge_and_fee_cap
    """
    set_clock(CLOCK_START_ISO)
    catalogue = box_car_catalogue(
        model_code="BOX-201",
        build_hours=1,
        line_count_family="LINE-C",
    )
    wheelset_substitute = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-220",
                component_class="WHEELSET",
                unit_cost_cents=18000,
                lead_time_days=30,
                on_hand_qty=100,
            ),
            SUPPLY,
        )
    )
    casting_substitute = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="CS-220",
                component_class="CASTING",
                unit_cost_cents=40000,
                lead_time_days=45,
                on_hand_qty=100,
            ),
            SUPPLY,
        )
    )
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=5,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-10-01",
    )
    reserved = reserve_order(order["id"])
    assert reserved["unit_price_cents"] == 309500, (
        "264500 of ceiled lines plus one 45000-cent build hour"
    )

    first = create_endorsement(
        order,
        catalogue["wheelset"],
        wheelset_substitute,
        substitute_qty_per_car=4,
        decides_material=True,
    )
    assert approve_endorsement(first["id"], LEASE)["status"] == "APPROVED"
    one_fee = get_success_data(api_client.get_production_order(order["id"], ADMIN))
    assert one_fee["unit_price_cents"] == 324500, (
        "one approved endorsement adds the raw 15000-cent fee, under the cap"
    )

    second = create_endorsement(
        order,
        catalogue["casting"],
        casting_substitute,
        substitute_qty_per_car=2,
        decides_material=True,
    )
    assert approve_endorsement(second["id"], LEASE)["status"] == "APPROVED"
    two_fees = get_success_data(api_client.get_production_order(order["id"], ADMIN))
    assert two_fees["unit_price_cents"] == 334260, (
        "the second endorsement is clipped by the eight-percent cap: "
        "floor(309500 * 8 / 100) == 24760"
    )
    assert two_fees["unit_price_cents"] - one_fee["unit_price_cents"] == 9760


def test_draft_order_takes_the_forecast_basis_then_the_committed_one(api):
    """PRD §3.1: "The committed basis applies once the order has been
    component-reserved or released, at which point contract prices and the
    endorsed composition are locked. The forecast basis applies while the order
    is still `DRAFT` and the current date is more than the lock horizon of 120
    days past `order_date`."
    PRD §3.1: "for every row whose `component_class` is `WHEELSET` or `CASTING`
    and where the current date is more than 120 days past the order's
    `order_date`, the component's `unit_cost_cents` is replaced by that cost
    multiplied by 110 and divided by 100, rounded up to a whole cent"
    PRD §3.1: "for every row whose `component_class` is `COATING` and whose
    component `lead_time_days` exceeds 60 days, the component's
    `unit_cost_cents` is replaced by that cost multiplied by 104 and divided by
    100, rounded up to a whole cent."

    The order is taken 153 days after its order date, so the draft quote lapses
    the wheelset cost to 19800 and the casting cost to 44000 — the coating lead
    time of 20 days is inside the 60-day threshold, so the coating line stays at
    62500. The forecast quote is 1629700; reserving the components switches to
    the committed basis and the locked 1614500.

    Design: Corner/calculations/order_price_quote_variant_selection_forecast_then_committed
    """
    set_clock("2027-02-01T00:00:00Z")
    catalogue = box_car_catalogue(set_clock_first=False)
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=150,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2027-04-01",
    )

    assert days_between("2026-09-01", "2027-02-01") == 153
    assert order["status"] == "DRAFT"
    assert order["unit_price_cents"] == 1629700, (
        "the lapsed wheelset and casting costs price the draft order: "
        "(104200 + 113000 + 62500) + 1350000"
    )

    reserved = reserve_order(order["id"])
    assert reserved["status"] == "COMPONENT_RESERVED"
    assert reserved["unit_price_cents"] == 1614500, (
        "reservation locks the contract prices back to 18000 and 40000"
    )
    assert order["unit_price_cents"] - reserved["unit_price_cents"] == 15200, (
        "the switch is a re-quote of one row, not a second order"
    )

    listed = get_success_data(api_client.list_production_orders(ADMIN, {"limit": 10}))
    assert len(listed) == 1
