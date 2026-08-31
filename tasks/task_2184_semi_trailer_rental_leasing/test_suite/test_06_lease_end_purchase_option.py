"""The lease-end purchase option: when it is offered, what it costs, and what
exercising or declining it does to the unit."""


from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    read_agreement,
    read_agreement_unit,
    read_branch,
    read_trailer,
    settle_agreement,
    setup_returned_unit,
    setup_settled_lease_with_purchase_option,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def test_purchase_option_price_caps_the_credit_on_the_pre_credit_base_price(api):
    """PRD §3.6: "Step three computes the base price as whichever is greater, the
    unit's current `net_book_value_cents` or its equipment class's
    `residual_floor_cents`. Step four computes the credit cap as thirty percent of
    that base price with any fractional cent discarded. Step five takes the applied
    credit as the smaller of the uncapped credit and the cap. Step six sets
    `purchase_option_price_cents` to whichever is greater, the base price less the
    applied credit, or the equipment class's `residual_floor_cents`."
    PRD §3.6: "Computing the cap from the post-credit price, or applying the credit
    before the residual floor, yields a different and incorrect number."

    Design: Difficulty/combinatorial_formula/purchase_option_credit_cap_keyed_on_pre_credit_base_price
    """
    scn = setup_settled_lease_with_purchase_option()

    assert scn["trailer_at_settlement"]["net_book_value_cents"] == 2662500, (
        "49 whole thirty-day months of straight-line depreciation"
    )
    assert read_trailer(scn["trailer_id"])["net_book_value_cents"] == 2662500

    agreement = read_agreement(scn["agreement_id"])
    assert agreement["purchase_option_status"] == "OFFERED"
    assert agreement["purchase_option_price_cents"] == 2262419, (
        "a 400081 credit capped at 798750, taken off a base price of 2662500"
    )
    assert agreement["status"] == "CLOSED"


def test_purchase_option_reads_the_final_total_this_settlement_just_wrote(api):
    """PRD §3.6: "Step one takes the cumulative amount paid as the
    `final_total_cents` just written by this same settlement. Step two computes the
    uncapped credit as twelve percent of that cumulative amount, rounded half-up to
    whole cents."
    PRD §3.6: "During settlement the server tests three conditions together: the
    contract's `product` must be `FULL_SERVICE_LEASE`, its `unit_count` must be
    exactly 1, and the number of calendar days from its `start_date` to its
    `end_date` must be at least 720."

    Design: Difficulty/combinatorial_formula/purchase_option_credit_cap_keyed_on_pre_credit_base_price
    """
    scn = setup_settled_lease_with_purchase_option()

    agreement = read_agreement(scn["agreement_id"])
    assert agreement["quoted_total_cents"] == 2774000
    assert agreement["final_total_cents"] == 3334010

    line = read_agreement_unit(scn["unit_id"])
    assert line["excess_miles"] == 37334
    assert line["peak_days"] == 0
    assert line["drop_charge_cents"] == 0

    assert agreement["purchase_option_price_cents"] == 2262419


def test_exercising_the_option_sells_the_unit_out_of_the_fleet(api):
    """PRD §3.6: "Exercising it moves `purchase_option_status` `OFFERED →
    EXERCISED`; a contract whose option status is anything other than `OFFERED` is
    rejected with `ERR_PURCHASE_OPTION_NOT_OFFERED`, and the single contract unit
    line's trailer must have `availability_status` exactly `AVAILABLE`, with
    anything else rejected as `ERR_TRAILER_NOT_AVAILABLE`."
    PRD §3.6: "On exercise the trailer moves `AVAILABLE → SOLD`, which removes it
    from `on_hand_count` and `serviceable_available_count` at its
    `current_branch_id` and from every availability pool permanently, and the
    contract's `version` increments by 1."

    Design: Corner/endpoints/exercise_purchase_option_marks_trailer_sold
    """
    scn = setup_settled_lease_with_purchase_option()
    assert scn["agreement"]["purchase_option_status"] == "OFFERED"
    assert scn["agreement"]["purchase_option_price_cents"] == 2262419

    agreement = validate_success(
        api.exercise_purchase_option(
            scn["agreement_id"], make_customer_headers(scn["customer_id"])
        )
    )
    assert agreement["purchase_option_status"] == "EXERCISED"
    assert agreement["purchase_option_price_cents"] == 2262419

    assert read_trailer(scn["trailer_id"])["availability_status"] == "SOLD"
    assert read_branch(scn["branch_id"])["on_hand_count"] == 0


def test_declining_the_option_leaves_the_unit_in_the_rental_fleet(api):
    """PRD §3.6: "Declining the offer moves `purchase_option_status` `OFFERED →
    DECLINED` under the same `ERR_PURCHASE_OPTION_NOT_OFFERED` guard; the trailer
    is untouched by a decline and simply stays `AVAILABLE` in the rental fleet, and
    the contract's `version` increments by 1."

    Design: Corner/endpoints/decline_purchase_option_keeps_trailer_in_the_rental_fleet
    """
    scn = setup_settled_lease_with_purchase_option()
    assert scn["agreement"]["purchase_option_status"] == "OFFERED"

    agreement = validate_success(
        api.decline_purchase_option(
            scn["agreement_id"], make_customer_headers(scn["customer_id"])
        )
    )
    assert agreement["purchase_option_status"] == "DECLINED"
    assert agreement["purchase_option_price_cents"] == 2262419

    assert read_trailer(scn["trailer_id"])["availability_status"] == "AVAILABLE"
    assert read_branch(scn["branch_id"])["on_hand_count"] == 1


def test_a_short_term_rental_never_carries_a_purchase_option(api):
    """PRD §3.6: "When any of the three fails, `purchase_option_status` remains
    `NOT_OFFERED` and `purchase_option_price_cents` remains null."
    PRD §3.6: "Exercising it moves `purchase_option_status` `OFFERED → EXERCISED`;
    a contract whose option status is anything other than `OFFERED` is rejected
    with `ERR_PURCHASE_OPTION_NOT_OFFERED`"

    Design: Corner/errors/exercise_purchase_option_on_short_term_rental_returns_not_offered
    """
    scn = setup_returned_unit()
    agreement = settle_agreement(scn)
    assert agreement["purchase_option_status"] == "NOT_OFFERED"
    assert agreement.get("purchase_option_price_cents") is None

    response = api.exercise_purchase_option(
        scn["agreement_id"], make_customer_headers(scn["customer_id"])
    )
    validate_error(response, ApiErrorId.ERR_PURCHASE_OPTION_NOT_OFFERED.value)

    assert read_trailer(scn["trailer_id"])["availability_status"] == "AVAILABLE"
