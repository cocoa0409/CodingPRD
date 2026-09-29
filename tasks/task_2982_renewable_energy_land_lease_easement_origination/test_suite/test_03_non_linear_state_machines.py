"""Cyclic negotiation and the two parallel dimensions of a lease."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ERR_NEGOTIATION_ROUND_LIMIT
from test_helpers.assertions import (
    assert_cents_equals,
    assert_instant_equals,
    assert_lease_dimensions,
    assert_status,
)
from test_helpers.factories import counter_payload
from test_helpers.fixtures import (
    caprock_qualified_parcel,
    caprock_recorded_lease,
    client,
    counter_option,
    draft_royalty_option,
    issue_invoice,
    pay_invoice,
    raise_invoice,
    read_invoice,
    read_lease,
    read_option,
    revise_option,
    send_option,
    set_clock,
)
from test_helpers.test_users import make_landowner_headers


def _option_in_negotiation():
    """A royalty-hybrid option on a qualified parcel, already on the table."""
    setup = caprock_qualified_parcel()
    option = draft_royalty_option(setup["parcel"]["id"], setup["landowner"]["id"])
    send_option(option["id"])
    return setup["landowner"]["id"], option["id"]


def test_three_negotiation_cycles_return_the_option_to_the_table_each_time():
    """
    Countering, revising and re-sending traverses the same loop three times. Each
    counter advances the round index, each revision returns the instrument to the
    agent, and the terms carried by each hop overwrite only what was supplied.

    PRD: "The full negotiation cycle is therefore `SENT → COUNTERED → REVISED →
    SENT`, traversable up to three times."

    Design: Difficulty/non_linear_state_machine/option_negotiation_loop_three_rounds_then_limit
    """
    landowner_id, option_id = _option_in_negotiation()

    countered = counter_option(option_id, landowner_id, option_fee_per_acre_cents=2600)
    assert_status(countered, "COUNTERED", "option")
    assert countered["round_index"] == 1

    revised = revise_option(option_id, base_rent_per_acre_cents=121000)
    assert_status(revised, "REVISED", "option")
    assert_status(send_option(option_id), "SENT", "option")

    countered = counter_option(option_id, landowner_id, option_fee_per_acre_cents=2750)
    assert countered["round_index"] == 2
    revise_option(option_id, base_rent_per_acre_cents=122000)
    send_option(option_id)

    countered = counter_option(option_id, landowner_id, option_fee_per_acre_cents=2900)
    assert countered["round_index"] == 3
    revised = revise_option(option_id, base_rent_per_acre_cents=123000)
    assert_status(revised, "REVISED", "option")
    assert_status(send_option(option_id), "SENT", "option")

    option = read_option(option_id)
    assert option["round_index"] == 3
    assert_cents_equals(
        option["option_fee_per_acre_cents"], 2900, "option_fee_per_acre_cents"
    )
    assert_cents_equals(
        option["base_rent_per_acre_cents"], 123000, "base_rent_per_acre_cents"
    )


def test_a_fourth_counter_is_refused_and_leaves_the_terms_on_the_table():
    """
    After three completed counters the loop is closed. The fourth counter is
    rejected outright, and none of the terms it carried reach the instrument.

    PRD: "The negotiation is capped at three completed counters: a counter is
    accepted only while `round_index` is still below 3, so the fourth counter is
    refused with `ERR_NEGOTIATION_ROUND_LIMIT` (422)."

    Design: Difficulty/non_linear_state_machine/option_negotiation_loop_three_rounds_then_limit
    """
    landowner_id, option_id = _option_in_negotiation()
    for fee, rent in ((2600, 121000), (2750, 122000), (2900, 123000)):
        counter_option(option_id, landowner_id, option_fee_per_acre_cents=fee)
        revise_option(option_id, base_rent_per_acre_cents=rent)
        send_option(option_id)

    response = client().counter_option(
        option_id,
        counter_payload(option_fee_per_acre_cents=3100),
        make_landowner_headers(landowner_id),
    )

    validate_error(response, ERR_NEGOTIATION_ROUND_LIMIT)
    option = read_option(option_id)
    assert option["round_index"] == 3
    assert_status(option, "SENT", "option")
    assert_cents_equals(
        option["option_fee_per_acre_cents"], 2900, "option_fee_per_acre_cents"
    )
    assert option["royalty_rate_bps"] == 350
    assert option["escalator_pct_bps"] == 200


def test_omitted_counter_terms_keep_whatever_value_they_currently_hold():
    """
    A counter that names only the option fee leaves the royalty, the escalator and
    the structure exactly as the developer proposed them.

    PRD: "Each of the seven counterable terms may be supplied to overwrite the
    agreement's current value immediately — `option_fee_per_acre_cents`,
    `extension_fee_per_acre_cents`, `base_rent_per_acre_cents`,
    `royalty_rate_bps`, `escalator_pct_bps`, `escalator_mode` and
    `option_term_days` — and every omitted term keeps whatever value it
    currently holds."

    Design: Difficulty/non_linear_state_machine/option_negotiation_loop_three_rounds_then_limit
    """
    landowner_id, option_id = _option_in_negotiation()
    before = read_option(option_id)

    countered = counter_option(option_id, landowner_id, option_fee_per_acre_cents=2600)

    assert_cents_equals(
        countered["option_fee_per_acre_cents"], 2600, "option_fee_per_acre_cents"
    )
    assert countered["royalty_rate_bps"] == before["royalty_rate_bps"]
    assert countered["escalator_pct_bps"] == before["escalator_pct_bps"]
    assert countered["escalator_mode"] == before["escalator_mode"]
    assert countered["option_term_days"] == before["option_term_days"]
    assert countered["rent_structure_type"] == before["rent_structure_type"]
    assert_cents_equals(
        countered["extension_fee_per_acre_cents"],
        before["extension_fee_per_acre_cents"],
        "extension_fee_per_acre_cents",
    )


def test_a_recorded_lease_can_still_be_waiting_for_its_first_rent():
    """
    Posting security, submitting and recording the memorandum drive the recording
    dimension all the way to its terminal value while the rent dimension has not
    moved at all.

    PRD: "A lease can reach `CURRENT` on its rent dimension while still
    `UNRECORDED`, and it can be `RECORDED` while still `PENDING_FIRST_RENT`."

    Design: Difficulty/non_linear_state_machine/lease_parallel_rent_and_recording_dimensions
    """
    setup = caprock_recorded_lease(royalty_hybrid=True)
    lease = setup["lease"]

    assert_lease_dimensions(lease, "PENDING_FIRST_RENT", "RECORDED")
    assert_cents_equals(
        lease["security_posted_cents"], 5225000, "security_posted_cents"
    )
    assert lease["recording_instrument_no"] == "2026-0044821"
    assert_instant_equals(lease["recorded_at"], "2026-08-01T00:00:00Z", "recorded_at")
    assert lease["last_paid_invoice_year"] == 0


def test_delinquency_and_payment_move_only_the_rent_dimension():
    """
    An overdue invoice drives the rent dimension to delinquent and payment closes
    the cycle back to current, while the recording dimension and its recorded
    instant sit untouched throughout.

    PRD: "The delinquency sweep of §2.6 moves a lease whose rent dimension reads
    `PENDING_FIRST_RENT` or `CURRENT` to `DELINQUENT` as soon as it holds at
    least one invoice in `ISSUED` whose `due_at` has been reached or passed — so
    both `PENDING_FIRST_RENT → DELINQUENT` and `CURRENT → DELINQUENT` are
    reachable."

    Design: Difficulty/non_linear_state_machine/lease_parallel_rent_and_recording_dimensions
    """
    setup = caprock_recorded_lease(royalty_hybrid=True)
    lease_id = setup["lease"]["id"]

    invoice = raise_invoice(lease_id, period_year=1, production_mwh=90000)
    assert_cents_equals(invoice["gross_rent_cents"], 13230000, "gross_rent_cents")
    issued = issue_invoice(invoice["id"])
    assert_instant_equals(issued["due_at"], "2026-09-15T00:00:00Z", "due_at")

    sweeps = set_clock("2026-09-16T00:00:00Z")
    assert sweeps["delinquent_lease_count"] == 1
    assert_lease_dimensions(read_lease(lease_id), "DELINQUENT", "RECORDED")

    pay_invoice(invoice["id"], 13230000)

    lease = read_lease(lease_id)
    assert_lease_dimensions(lease, "CURRENT", "RECORDED")
    assert lease["last_paid_invoice_year"] == 1
    assert_instant_equals(lease["recorded_at"], "2026-08-01T00:00:00Z", "recorded_at")
    assert_instant_equals(
        read_invoice(invoice["id"])["paid_at"], "2026-09-16T00:00:00Z", "paid_at"
    )


def test_issuing_sets_the_due_date_forty_five_days_out():
    """
    A draft invoice carries no due date at all; issuing it stamps one exactly
    forty-five days after the instant of issue.

    PRD: "**Issuing** moves a `DRAFT` invoice to `ISSUED`, stamps `issued_at`
    from the logical clock, and sets `due_at` to `issued_at` advanced by
    forty-five days of net terms; `due_at` is null while the invoice is still
    `DRAFT`."

    Design: Difficulty/non_linear_state_machine/lease_parallel_rent_and_recording_dimensions
    """
    setup = caprock_recorded_lease(royalty_hybrid=True)
    invoice = raise_invoice(setup["lease"]["id"], period_year=1, production_mwh=90000)
    assert invoice["due_at"] is None, f"draft due_at should be null, got {invoice['due_at']}"

    issued = issue_invoice(invoice["id"])

    assert_status(issued, "ISSUED", "invoice")
    assert_instant_equals(issued["issued_at"], "2026-08-01T00:00:00Z", "issued_at")
    assert_instant_equals(issued["due_at"], "2026-09-15T00:00:00Z", "due_at")
