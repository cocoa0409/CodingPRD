"""Depth: the dual-variant restocking fee and the conserved gear-credit balance."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_coverage_conserved
from test_helpers.fixtures import (
    SALES_OPS,
    SUPPORT_AGENT,
    add_quote_line,
    complete_exchange,
    create_gear_exchange,
    create_product,
    create_quote,
    get_customer as read_customer,
    get_exchange,
    request_return,
    set_clock,
    setup_book_world,
    start_trial,
)


_STUDIO_WORLD_SEQ = [0]


def _studio_world_with_tone_mismatch_exchange(line_price_cents=40000,
                                              reason="TONE_MISMATCH",
                                              clock="2026-09-10T00:00:00.000Z",
                                              tier="STUDIO"):
    # Each distinct world needs its own engineer and customer identity: the
    # email is unique across Engineer and across Customer (PRD 3.1 / 3.10).
    _STUDIO_WORLD_SEQ[0] += 1
    seq = _STUDIO_WORLD_SEQ[0]
    world = setup_book_world(clock=clock, customer_name="Nova Bay %d" % seq,
                             customer_email="nova.bay%d@example.com" % seq,
                             engineer_name="Dana Riggs %d" % seq,
                             engineer_email="dana.riggs%d@sweetwater.example" % seq,
                             home_state="CA", with_catalog=False,
                             customer_extra={"account_tier": tier})
    code = "SW-GTR-4%02d" % seq
    create_product(product_code=code, display_name="Studio Guitar 400",
                   product_family="GUITAR", unit_price_cents=line_price_cents)
    quote = create_quote(world["customer"], world["engineer"], "INSTRUMENT_ONLY")
    line = add_quote_line(quote, world["engineer"], product_code=code,
                          quantity=1, is_anchor=True)
    exchange = create_gear_exchange(line, world["customer"], reason)
    world.update({"quote": quote, "line": line, "exchange": exchange,
                  "exchange_id": exchange["id"]})
    return world


def test_restocking_fee_provisional_variant_applies_only_the_reason_rate():
    """PRD 3.8: "In the provisional variant, stored when the trial starts, only
    the reason rate is applied — the tier adjustment and the near-expiry
    component are not yet known and are ignored, so the fee is the line total
    multiplied by the reason rate and divided by 10000, rounded half-up to 2
    decimal places."

    Design: Difficulty/dual_variant_calc/restocking_fee_provisional_vs_final_on_gear_exchange
    """
    world = _studio_world_with_tone_mismatch_exchange()
    started = start_trial(world["exchange"])

    assert started["restocking_fee_bps"] == 1500
    assert started["restocking_fee_cents"] == 6000, "40000 * 1500 / 10000 == 6000"
    assert started["status"] == "TRIAL_ACTIVE"
    assert started["trial_start_date"] == "2026-09-10T00:00:00.000Z"
    assert started["trial_end_date"] == "2026-09-24T00:00:00.000Z"


def test_restocking_fee_final_variant_applies_the_composed_effective_rate():
    """PRD 3.8: "In the final variant, stored when the return is requested, the
    composed effective rate is applied in place of the bare reason rate, with
    the same single rounding against the line total." PRD 3.8: "a `STUDIO`
    customer returning for `TONE_MISMATCH` pays 500 basis points effective
    against the 1500 that the provisional form had suggested."

    Design: Difficulty/dual_variant_calc/restocking_fee_provisional_vs_final_on_gear_exchange
    """
    world = _studio_world_with_tone_mismatch_exchange()
    start_trial(world["exchange"])
    returned = request_return(world["exchange"])

    assert returned["restocking_fee_bps"] == 500, (
        "1500 TONE_MISMATCH + (-1000) STUDIO + 0 near-expiry == 500"
    )
    assert returned["restocking_fee_cents"] == 2000, "40000 * 500 / 10000 == 2000"
    assert returned["status"] == "RETURN_REQUESTED"
    assert returned["trial_end_date"] == "2026-09-24T00:00:00.000Z"


def test_provisional_and_final_restocking_fees_disagree_on_identical_data():
    """PRD 3.8: "The gap between the two variants can be wide: a `STUDIO`
    customer returning for `TONE_MISMATCH` pays 500 basis points effective
    against the 1500 that the provisional form had suggested."

    Design: Difficulty/dual_variant_calc/restocking_fee_provisional_vs_final_on_gear_exchange
    """
    world = _studio_world_with_tone_mismatch_exchange()
    provisional = start_trial(world["exchange"])
    final = request_return(world["exchange"])

    assert provisional["restocking_fee_cents"] == 6000
    assert final["restocking_fee_cents"] == 2000
    assert provisional["restocking_fee_cents"] - final["restocking_fee_cents"] == 4000


def test_restocking_fee_uses_the_studio_tier_adjustment_of_minus_one_thousand():
    """PRD 3.8: "The tier adjustment is fixed per account tier: `STANDARD`
    adjusts the rate by 0 basis points, `PREMIUM` adjusts it by -500 basis
    points, and `STUDIO` adjusts it by -1000 basis points."

    Design: Difficulty/dual_variant_calc/restocking_fee_provisional_vs_final_on_gear_exchange
    """
    world = _studio_world_with_tone_mismatch_exchange()
    start_trial(world["exchange"])
    returned = request_return(world["exchange"])
    assert returned["restocking_fee_bps"] == 500

    standard_world = _studio_world_with_tone_mismatch_exchange(tier="STANDARD",
                                                               clock="2026-09-10T00:00:00.000Z")
    start_trial(standard_world["exchange"])
    standard_return = request_return(standard_world["exchange"])
    assert standard_return["restocking_fee_bps"] == 1500
    assert standard_return["restocking_fee_cents"] == 6000


def test_completed_exchange_reconciles_refund_credit_and_retained_fee():
    """PRD 3.8: "Completion recomputes `refund_credit_cents` as the line total
    minus the final restocking fee ... the refund credit is added, and the
    restocking fee is then credited back as a fee offset. The second increment
    is what makes the conservation invariant exact rather than approximate; the
    net effect of a completed exchange on the balance is the full line total,
    and the fee and the credit can never drift apart because they are written
    together."

    Design: Difficulty/compensating_invariant/gear_exchange_restocking_fee_offsets_refund_credit
    """
    world = _studio_world_with_tone_mismatch_exchange(line_price_cents=50000,
                                                      clock="2026-09-24T00:00:00.000Z")
    start_trial(world["exchange"])
    returned = request_return(world["exchange"])
    assert returned["restocking_fee_cents"] == 2500, (
        "50000 * (1500 TONE_MISMATCH - 1000 STUDIO) / 10000"
    )

    completed = complete_exchange(world["exchange"])
    assert completed["status"] == "EXCHANGED"
    assert completed["refund_credit_cents"] == 47500

    customer = read_customer(world["customer_id"])
    assert customer["lifetime_gear_credit_cents"] == 50000
    assert_coverage_conserved(customer["lifetime_gear_credit_cents"], 50000)


def test_conserved_credit_plus_fee_equals_line_value_across_the_complete_call():
    """PRD 3.8: "the net effect of a completed exchange on the balance is the
    full line total, and the fee and the credit can never drift apart because
    they are written together."

    Design: Difficulty/compensating_invariant/gear_exchange_restocking_fee_offsets_refund_credit
    """
    world = _studio_world_with_tone_mismatch_exchange(line_price_cents=50000,
                                                      clock="2026-09-24T00:00:00.000Z")
    start_trial(world["exchange"])
    request_return(world["exchange"])

    before = read_customer(world["customer_id"])
    assert before["lifetime_gear_credit_cents"] == 0

    completed = complete_exchange(world["exchange"])
    after = read_customer(world["customer_id"])

    assert after["lifetime_gear_credit_cents"] + completed["restocking_fee_cents"] == 52500
    assert after["lifetime_gear_credit_cents"] == 50000
    fetched = get_exchange(world["exchange_id"])
    assert fetched["status"] == "EXCHANGED"


def test_trial_window_is_half_open_and_the_refund_reads_the_closed_line_value():
    """PRD 3.8: "It is admitted only from `RETURN_REQUESTED`, and only while the
    logical clock is not past `trial_end_date` — the boundary instant itself
    still counts as in time". PRD 3.8: "Starting the trial stamps
    `trial_start_date` from the logical clock, derives `trial_end_date` as
    fourteen days later".

    Design: Difficulty/compensating_invariant/gear_exchange_restocking_fee_offsets_refund_credit
    """
    world = _studio_world_with_tone_mismatch_exchange(line_price_cents=50000,
                                                      clock="2026-09-24T00:00:00.000Z")
    started = start_trial(world["exchange"])
    assert started["trial_start_date"] == "2026-09-24T00:00:00.000Z"
    assert started["trial_end_date"] == "2026-10-08T00:00:00.000Z"

    request_return(world["exchange"])
    set_clock("2026-10-08T00:00:00.000Z")
    completed = complete_exchange(world["exchange"])
    assert completed["status"] == "EXCHANGED"

    other = _studio_world_with_tone_mismatch_exchange(clock="2026-09-24T00:00:00.000Z")
    start_trial(other["exchange"])
    request_return(other["exchange"])
    set_clock("2026-10-09T00:00:00.000Z")
    resp = api_client.complete_exchange(other["exchange"]["id"], SUPPORT_AGENT)
    validate_error(resp, ApiErrorId.ERR_TRIAL_WINDOW_EXPIRED)


def test_exchange_completion_needs_the_authoring_engineer_present_for_the_trial():
    """PRD 3.8: "It is admitted only from `DRAFT`, and only when the customer's
    assignment in their book is currently `ACTIVE` — an unowned account has no
    engineer to stand behind the exchange, and the attempt fails with
    `ERR_CUSTOMER_ASSIGNMENT_REQUIRED` at HTTP 422."

    Design: Difficulty/compensating_invariant/gear_exchange_restocking_fee_offsets_refund_credit
    """
    world = _studio_world_with_tone_mismatch_exchange()
    resp = api_client.start_trial(world["exchange"]["id"], SUPPORT_AGENT)
    validate_success(resp)

    api_client.end_assignment(world["assignment_id"], SALES_OPS)

    orphan = _studio_world_with_tone_mismatch_exchange(clock="2026-09-10T00:00:00.000Z")
    api_client.end_assignment(orphan["assignment_id"], SALES_OPS)
    blocked = api_client.start_trial(orphan["exchange"]["id"], SUPPORT_AGENT)
    validate_error(blocked, ApiErrorId.ERR_CUSTOMER_ASSIGNMENT_REQUIRED)