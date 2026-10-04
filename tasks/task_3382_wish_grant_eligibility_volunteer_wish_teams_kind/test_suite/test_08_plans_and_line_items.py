"""Fulfillment plans and line-item reservation: empty-plan rejection, the
category-vs-wish-type mapping, the exact-remaining quantity boundary, and the
pinned unit-first rounding order.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line_item,
    api_client,
    assert_offer_quantities,
    assert_plan_totals,
    create_donation_offer,
    create_line_item_payload,
    get_donation_offer,
    get_fulfillment_plan,
    setup_planning_wish,
    submit_plan,
    validate_error,
)

WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]


def test_plan_submit_empty_rejected():
    """PRD section 3.6: "Submitting moves a `DRAFT` plan to `PENDING_APPROVAL`
    with a version increment; a plan holding no `RESERVED` line items and zero
    `cash_cost_cents` cannot be submitted and is rejected with `ERR_EMPTY_PLAN`
    (HTTP 422)."

    Design: Corner/validations/plan_submit_empty_rejected
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM", cash_cost_cents=0)
    plan = ctx["plan"]

    empty = api_client.submit_plan(plan["id"], WISH_COORDINATOR)
    validate_error(empty, ApiErrorId.ERR_EMPTY_PLAN)
    assert get_fulfillment_plan(plan["id"])["status"] == "DRAFT"

    offer = create_donation_offer(quantity_total=4, unit_retail_cents=12000)
    add_line_item(plan["id"], offer["id"], 1)
    submitted = submit_plan(plan["id"])
    assert submitted["status"] == "PENDING_APPROVAL"


def test_category_mismatch_retailer_line_on_travel_plan():
    """PRD section 3.6: "the offer's category must fit the wish type's
    fulfillment path — `TRAVEL` wishes draw from `AIRLINE` and `RESORT`,
    `RECEIVE_ITEM` from `RETAILER`, `MEET_PERSON` from `SPONSOR`, and
    `BE_SOMETHING` from `SPONSOR` or `RETAILER`, with any other pairing
    rejected as `ERR_CATEGORY_WISH_TYPE_MISMATCH` (HTTP 422)"

    Design: Corner/validations/category_mismatch_retailer_line_on_travel_plan
    """
    ctx = setup_planning_wish(wish_type="TRAVEL",
                              captured_true_wish="fly to the ocean",
                              cash_cost_cents=0)
    plan = ctx["plan"]
    retailer = create_donation_offer(
        partner_name="ToyWorld", category="RETAILER", quantity_total=4,
        unit_retail_cents=12000)
    airline = create_donation_offer(
        partner_name="SkyWay Airlines", category="AIRLINE", quantity_total=4,
        unit_retail_cents=50000)

    bad = api_client.create_plan_line_item(
        plan["id"], create_line_item_payload(retailer["id"], 1),
        WISH_COORDINATOR)
    validate_error(bad, ApiErrorId.ERR_CATEGORY_WISH_TYPE_MISMATCH)
    assert get_donation_offer(retailer["id"])["quantity_reserved"] == 0, (
        "the rejected line must reserve nothing"
    )

    good = add_line_item(plan["id"], airline["id"], 1)
    assert good["status"] == "RESERVED"
    assert good["line_fmv_cents"] == 50000


def test_line_item_over_remaining_quantity_rejected():
    """PRD section 3.6: "the requested `quantity` must not exceed the offer's
    `quantity_available`, where exactly the remaining quantity is allowed
    (`ERR_INSUFFICIENT_DONATION_QTY`, HTTP 409)."

    Design: Difficulty/boundary_precision_check/line_item_exact_remaining_quantity_boundary
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM", cash_cost_cents=0)
    plan = ctx["plan"]
    offer = create_donation_offer(quantity_total=10, unit_retail_cents=12000)

    add_line_item(plan["id"], offer["id"], 7)
    mid = get_donation_offer(offer["id"])
    assert_offer_quantities(mid, quantity_reserved=7, quantity_available=3)
    assert mid["status"] == "AVAILABLE"

    over = api_client.create_plan_line_item(
        plan["id"], create_line_item_payload(offer["id"], 4), WISH_COORDINATOR)
    validate_error(over, ApiErrorId.ERR_INSUFFICIENT_DONATION_QTY)
    after = get_donation_offer(offer["id"])
    assert_offer_quantities(after, quantity_reserved=7, quantity_available=3)


def test_line_item_exact_remaining_quantity_succeeds():
    """PRD section 3.6: "the requested `quantity` must not exceed the offer's
    `quantity_available`, where exactly the remaining quantity is allowed"
    PRD section 3.5: "when a reservation takes the last available unit the
    offer becomes `FULLY_RESERVED`"

    Design: Difficulty/boundary_precision_check/line_item_exact_remaining_quantity_boundary
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM", cash_cost_cents=0)
    plan = ctx["plan"]
    offer = create_donation_offer(quantity_total=10, unit_retail_cents=12000)

    add_line_item(plan["id"], offer["id"], 7)
    over = api_client.create_plan_line_item(
        plan["id"], create_line_item_payload(offer["id"], 4), WISH_COORDINATOR)
    validate_error(over, ApiErrorId.ERR_INSUFFICIENT_DONATION_QTY)

    exact = add_line_item(plan["id"], offer["id"], 3)
    assert exact["status"] == "RESERVED"
    final = get_donation_offer(offer["id"])
    assert_offer_quantities(final, quantity_reserved=10, quantity_available=0)
    assert final["status"] == "FULLY_RESERVED"


def test_plan_total_unit_fmv_rounded_at_unit_level():
    """PRD section 3.5: "Under `PARTNER_DECLARED`, the partner's
    `partner_declared_unit_cents` is required — omitting it is a malformed
    request (`ERR_INVALID_REQUEST`) — and the unit value is the lesser of that
    declared figure and a cap computed as 80 percent of `unit_retail_cents`,
    with the cap itself rounded half-up to integer cents before the
    comparison."
    retail 33333 -> cap round-half-up(26666.4) == 26666; min(31999, 26666) ==
    26666.

    Design: Difficulty/combinatorial_formula/plan_total_rounds_unit_fmv_before_multiply
    """
    offer = create_donation_offer(
        partner_name="GameWholesale", category="RETAILER",
        valuation_method="PARTNER_DECLARED", description="board game bundle",
        quantity_total=8, unit_retail_cents=33333,
        partner_declared_unit_cents=31999)
    fetched = get_donation_offer(offer["id"])
    assert fetched["fmv_unit_cents"] == 26666, (
        f"cap rounds at the unit level: expected 26666, got "
        f"{fetched['fmv_unit_cents']}"
    )


def test_plan_total_multiplies_after_unit_rounding():
    """PRD section 2.6: "The pinned evaluation order is therefore: round the
    per-unit value first, multiply by the line quantity, sum across the plan's
    lines, and add cash last. An implementation that sums raw unrounded values
    and rounds once at the end will produce different cents and is incorrect."
    3 x 26666 == 79998 (the round-after-multiplying order would give 79999).

    Design: Difficulty/combinatorial_formula/plan_total_rounds_unit_fmv_before_multiply
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM",
                              captured_true_wish="a pallet of board games",
                              cash_cost_cents=2)
    plan = ctx["plan"]
    offer = create_donation_offer(
        partner_name="GameWholesale", category="RETAILER",
        valuation_method="PARTNER_DECLARED", description="board game bundle",
        quantity_total=8, unit_retail_cents=33333,
        partner_declared_unit_cents=31999)
    line = add_line_item(plan["id"], offer["id"], 3)
    assert line["line_fmv_cents"] == 79998, (
        f"unit-first rounding pins 3 x 26666 == 79998, got "
        f"{line['line_fmv_cents']}"
    )
    plan_now = get_fulfillment_plan(plan["id"])
    assert_plan_totals(plan_now, cash_cost_cents=2,
                       in_kind_value_cents=79998, total_cost_cents=80000)
