"""Settlement pricing and lifecycle: PROVISIONAL vs FINAL variants, the
pinned evaluation order keying the volume tier on pre-discount week spend,
tier boundaries, finalize preconditions, the dispute loop, and customer
credit suspension and recovery.
"""

from test_helpers import (
    ADMIN,
    SALES,
    api_client,
    create_commitment,
    create_customer,
    create_order_payload,
    dispute_payload,
    finalize_scenario,
    finalize_settlement,
    make_customer_headers,
    read_commitment,
    read_customer,
    read_order,
    read_order_settlement,
    set_clock,
    setup_pricing_scenario,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def test_provisional_price_is_a_point_observation(api):
    """At ship time the settlement prices off the single latest quotation
    effective at or before the ship clock: 170, not the week average.

    PRD §3.4: "The **provisional** price, computed when the order ships
    (§3.6), is a point observation: the server takes the quotation matching
    the commitment's region and the order's size class with the latest
    `effective_date` at or before the ship clock, breaking ties by later
    quotation creation, and records it as the settlement's
    `provisional_index_cents`. The `provisional_unit_price_cents` is that
    index plus the commitment's `price_adjustment_cents_per_dozen` — a fixed
    premium or discount that may be negative — and the
    `provisional_total_cents` is the `dozen_shipped` times that unit price."

    Design: Difficulty/dual_variant_calc/settlement_provisional_point_vs_final_week_average
    """
    scn = setup_pricing_scenario()  # ship clock 2026-09-12
    settlement = scn["settlement"]
    assert settlement["status"] == "PROVISIONAL"
    # Quotations 150 @ 09-07, 160 @ 09-09, 170 @ 09-11: latest <= 09-12.
    assert settlement["provisional_index_cents"] == 170
    assert settlement["provisional_unit_price_cents"] == 182  # 170 + 12
    assert settlement["provisional_total_cents"] == 5_460_000  # 30000 * 182
    assert settlement["final_total_cents"] is None


def test_final_price_uses_week_average_and_volume_discount(api):
    """At finalize the same order reprices off the week-window mean minus the
    volume discount: the variants provably diverge on identical order data.

    PRD §3.4: "Step one: `final_index_average_cents` is the mean of
    `price_cents_per_dozen` across *all* quotations matching the region and
    size class whose `effective_date` falls inside the settlement week — the
    half-open window from `ship_week_start` to seven days later — rounded
    half up to a whole cent."
    PRD §3.4: "`RETAIL`: same-week spend of at least 500,000 cents earns 2
    cents per dozen off; at least 2,000,000 cents earns 4."
    PRD §3.4: "Identical inputs therefore produce provisional and final
    totals that diverge whenever quotations moved within the week."
    PRD §3.7: "Finalization computes the final pricing of §3.4 in its pinned
    order, moves the order from `SHIPPED` to `SETTLED`".

    Design: Difficulty/dual_variant_calc/settlement_provisional_point_vs_final_week_average
    """
    scn = setup_pricing_scenario()
    finalize_scenario(scn)  # clock 2026-09-15: the week has closed

    settlement = scn["settlement"]
    assert settlement["status"] == "FINAL"
    # mean of 150, 160, 170 = 160 (all inside [09-07, 09-14)).
    assert settlement["final_index_average_cents"] == 160
    # Week pre-discount spend 30000 * 172 = 5160000 >= 2000000 -> 4 cents.
    assert settlement["final_volume_discount_cents"] == 4
    assert settlement["final_unit_price_cents"] == 168  # 172 - 4
    assert settlement["final_total_cents"] == 5_040_000  # 30000 * 168
    # The two variants diverge on identical order data.
    assert settlement["provisional_unit_price_cents"] == 182
    assert settlement["final_unit_price_cents"] != settlement[
        "provisional_unit_price_cents"
    ]
    assert read_order(scn["order"]["id"])["status"] == "SETTLED"


def test_volume_tier_keyed_on_prediscount_week_spend(api):
    """The tier threshold compares against PRE-discount week spend:
    11700 dozen x 172 = 2012400 >= 2000000 earns the 4-cent tier.

    PRD §3.4: "Step three: the customer's **week spend** is the sum, over
    every one of the customer's orders with the same `ship_week_start` in
    `SHIPPED` or `SETTLED` status, of that order's `allocated_dozen` times
    its own pre-discount unit price — the week-average index for *that*
    order's size class plus *its* commitment's adjustment — so step three
    depends only on pre-discount figures and never on step four. Step four:
    `final_volume_discount_cents` is the per-dozen discount of the customer's
    segment tier whose spend threshold is the greatest threshold not
    exceeding the week spend, or zero when no threshold is met."

    Design: Difficulty/combinatorial_formula/settlement_discount_keyed_on_prediscount_week_spend
    """
    scn = setup_pricing_scenario(dozen_ordered=11_700, weekly_dozen=50_000)
    finalize_scenario(scn)

    settlement = scn["settlement"]
    assert settlement["final_index_average_cents"] == 160
    assert settlement["final_volume_discount_cents"] == 4
    assert settlement["final_unit_price_cents"] == 168


def test_post_discount_total_does_not_demote_the_tier(api):
    """The post-discount total (1965600) falls below the 2000000 threshold,
    yet the discount stands — the tier was keyed on pre-discount spend.

    PRD §3.4: "Step five: `final_unit_price_cents` is the pre-discount unit
    minus that discount. Step six: `final_total_cents` is the
    `dozen_shipped` times the final unit." and step three "depends only on
    pre-discount figures and never on step four."
    PRD §3.7: "Finalization computes the final pricing of §3.4 in its pinned
    order".

    Design: Difficulty/combinatorial_formula/settlement_discount_keyed_on_prediscount_week_spend
    """
    scn = setup_pricing_scenario(dozen_ordered=11_700, weekly_dozen=50_000)
    finalize_scenario(scn)

    settlement = scn["settlement"]
    assert settlement["status"] == "FINAL"
    assert settlement["final_total_cents"] == 1_965_600  # 11700 * 168
    assert settlement["final_total_cents"] < 2_000_000
    # ... yet the 4-cent tier was still granted.
    assert settlement["final_volume_discount_cents"] == 4


def test_volume_tier_grants_discount_at_exact_threshold(api):
    """The tier comparison is >= : week pre-discount spend of exactly
    2000000 cents (12500 dozen x 160) grants the 4-cent discount.

    PRD §3.4: "`RETAIL`: same-week spend of at least 500,000 cents earns 2
    cents per dozen off; at least 2,000,000 cents earns 4." and "Step four:
    `final_volume_discount_cents` is the per-dozen discount of the customer's
    segment tier whose spend threshold is the greatest threshold not
    exceeding the week spend, or zero when no threshold is met."

    Design: Corner/calculations/volume_tier_grants_discount_at_exact_threshold
    """
    scn = setup_pricing_scenario(
        dozen_ordered=12_500, adjustment=0, weekly_dozen=50_000, hens=30_000,
    )
    finalize_scenario(scn)

    settlement = scn["settlement"]
    assert settlement["status"] == "FINAL"
    assert settlement["final_index_average_cents"] == 160
    # Exactly 2000000 cents of pre-discount spend meets the >= threshold.
    assert settlement["final_volume_discount_cents"] == 4
    assert settlement["final_unit_price_cents"] == 156
    assert settlement["final_total_cents"] == 1_950_000  # 12500 * 156


def test_settlement_finalize_before_week_close_returns_409(api):
    """Finalizing before the clock reaches ship_week_start + 7 days fails;
    the settlement stays PROVISIONAL.

    PRD §3.7: "A `SalesManager` finalizes a `PROVISIONAL` settlement (else
    `ERR_INVALID_STATE`) once the clock has reached seven days past
    `ship_week_start` (else `ERR_SETTLEMENT_NOT_FINALIZABLE`)".

    Design: Corner/state_machines/settlement_finalize_before_week_close_returns_409
    """
    scn = setup_pricing_scenario(
        dozen_ordered=10_000,
        quotations=((150, "2026-09-07T00:00:00Z"),),
        ship_clock="2026-09-08T00:00:00Z",
    )
    set_clock("2026-09-10T00:00:00Z")  # week closes 2026-09-14T00:00:00Z

    validate_error(
        api.finalize_settlement(scn["settlement"]["id"], SALES),
        ERR.ERR_SETTLEMENT_NOT_FINALIZABLE,
    )
    after = read_order_settlement(scn["order"]["id"])
    assert after["status"] == "PROVISIONAL"
    assert after["final_total_cents"] is None


def test_finalize_without_week_quotation_returns_no_quotation(api):
    """A pre-week quotation suffices for the provisional price but not for
    the week-window average: finalize fails.

    PRD §3.7: "at least one quotation for the region and size class falls
    inside the settlement week (else `ERR_NO_QUOTATION`)".
    PRD §3.4: "Step one: `final_index_average_cents` is the mean of
    `price_cents_per_dozen` across *all* quotations matching the region and
    size class whose `effective_date` falls inside the settlement week — the
    half-open window from `ship_week_start` to seven days later".

    Design: Corner/errors/finalize_without_week_quotation_returns_no_quotation
    """
    scn = setup_pricing_scenario(
        dozen_ordered=10_000,
        quotations=((140, "2026-08-31T00:00:00Z"),),  # before the ship week
    )
    # The provisional price used the pre-week point observation.
    assert scn["settlement"]["provisional_index_cents"] == 140
    assert scn["settlement"]["provisional_unit_price_cents"] == 152

    set_clock("2026-09-15T00:00:00Z")
    validate_error(
        api.finalize_settlement(scn["settlement"]["id"], SALES),
        ERR.ERR_NO_QUOTATION,
    )
    after = read_order_settlement(scn["order"]["id"])
    assert after["status"] == "PROVISIONAL"


def _setup_finalized_scenario(api):
    scn = setup_pricing_scenario()
    finalize_scenario(scn)
    assert scn["settlement"]["final_total_cents"] == 5_040_000
    return scn


def test_settlement_dispute_resolve_cycle_pins_amounts(api):
    """FINAL -> DISPUTED -> FINAL -> DISPUTED repeats without error, and
    resolve preserves the finalize-time numbers.

    PRD §3.7: "The owning `Customer` disputes a `FINAL` settlement (else
    `ERR_INVALID_STATE`), supplying a `reason` that is stored in
    `disputed_reason`". "A `SalesManager` resolves a `DISPUTED` settlement
    back to `FINAL` (else `ERR_INVALID_STATE`), clearing `disputed_reason` —
    and crucially *not* recomputing any amounts; the numbers pinned at
    finalization are preserved verbatim."

    Design: Difficulty/non_linear_state_machine/settlement_final_disputed_final_cycle
    """
    scn = _setup_finalized_scenario(api)
    settlement_id = scn["settlement"]["id"]
    customer_headers = make_customer_headers(scn["customer"]["id"])

    disputed = validate_success(
        api.dispute_settlement(
            settlement_id, dispute_payload("week-average mismatch vs buyer "
                                           "records"), customer_headers,
        )
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["disputed_reason"] == (
        "week-average mismatch vs buyer records"
    )

    resolved = validate_success(api.resolve_settlement(settlement_id, SALES))
    assert resolved["status"] == "FINAL"
    assert resolved["disputed_reason"] is None
    # The loop repeats without error.
    disputed_again = validate_success(
        api.dispute_settlement(
            settlement_id, dispute_payload("second review round"),
            customer_headers,
        )
    )
    assert disputed_again["status"] == "DISPUTED"

    # Amounts pinned at finalize survive the whole cycle.
    assert disputed_again["final_total_cents"] == 5_040_000
    assert disputed_again["final_unit_price_cents"] == 168


def test_dispute_keeps_outstanding_unchanged(api):
    """A DISPUTED settlement still counts toward the customer's outstanding
    balance throughout the loop.

    PRD §3.7: "the customer's `outstanding_cents` is unchanged because a
    `DISPUTED` settlement still counts toward outstanding."
    PRD §3.5: "outstanding is always the sum of `final_total_cents` over the
    customer's settlements in `FINAL` or `DISPUTED` status, with
    `PROVISIONAL` and `PAID` settlements excluded."

    Design: Difficulty/non_linear_state_machine/settlement_final_disputed_final_cycle
    """
    scn = _setup_finalized_scenario(api)
    settlement_id = scn["settlement"]["id"]
    customer_id = scn["customer"]["id"]
    assert read_customer(customer_id)["outstanding_cents"] == 5_040_000

    validate_success(
        api.dispute_settlement(
            settlement_id, dispute_payload("review"),
            make_customer_headers(customer_id),
        )
    )
    assert read_customer(customer_id)["outstanding_cents"] == 5_040_000

    validate_success(api.resolve_settlement(settlement_id, SALES))
    after = read_order_settlement(scn["order"]["id"])
    assert after["status"] == "FINAL"
    assert after["disputed_reason"] is None
    assert read_customer(customer_id)["outstanding_cents"] == 5_040_000


def test_customer_suspension_and_recovery_via_credit(api):
    """Finalize pushes outstanding over the credit limit and suspends the
    customer; activation of a fresh commitment fails the state gate, a new
    order fails the fiscal gate, and mark-paid restores standing.

    PRD §3.7: "Finalization ... adds `final_total_cents` to the customer's
    `outstanding_cents`, and — if that pushes outstanding over the customer's
    `credit_limit_cents` — suspends the customer to `SUSPENDED`."
    PRD §3.5: "activation requires the commitment `PENDING` and the customer
    `ACTIVE` (either failure is `ERR_INVALID_STATE`)".
    PRD §3.6: "the customer must not be `SUSPENDED` (else
    `ERR_CUSTOMER_SUSPENDED`)".
    PRD §3.7: "A `SalesManager` marks a `FINAL` settlement paid (else
    `ERR_INVALID_STATE`), subtracting `final_total_cents` from the customer's
    `outstanding_cents`; if the customer was `SUSPENDED` and outstanding has
    fallen back to or below `credit_limit_cents`, standing is restored to
    `ACTIVE`."

    Design: Corner/validations/customer_suspension_and_recovery_via_credit
    """
    scn = setup_pricing_scenario(credit_limit_cents=5_000_000)
    finalize_scenario(scn)
    # outstanding 5040000 > credit 5000000.
    customer_id = scn["customer"]["id"]
    suspended = read_customer(customer_id)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["outstanding_cents"] == 5_040_000

    # A new commitment can be booked but cannot activate while suspended.
    second = create_commitment(
        customer_id, weekly_dozen_committed=5_000,
        price_adjustment_cents_per_dozen=0,
    )
    validate_error(
        api.activate_commitment(second["id"], SALES), ERR.ERR_INVALID_STATE
    )

    # A new order on the still-ACTIVE original commitment hits the fiscal
    # gate.
    commitment = read_commitment(scn["commitment"]["id"])
    assert commitment["status"] == "ACTIVE"
    response = api.create_order(
        commitment["id"],
        create_order_payload(
            ship_week_start="2026-09-14T00:00:00Z",
            dozen_ordered=1_000,
            size_class="LARGE",
            expected_commitment_version=commitment["version"],
        ),
        make_customer_headers(customer_id),
    )
    validate_error(response, ERR.ERR_CUSTOMER_SUSPENDED)

    paid = validate_success(
        api.mark_settlement_paid(scn["settlement"]["id"], SALES)
    )
    assert paid["status"] == "PAID"
    restored = read_customer(customer_id)
    assert restored["outstanding_cents"] == 0
    assert restored["status"] == "ACTIVE"
