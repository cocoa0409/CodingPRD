"""The chronological payoff replay: application orders, segments and reversal."""

from test_helpers import (
    assert_payoff_quote_shape,
    book_payment,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_creditor_headers,
    read_judgment,
    setup_judgment,
    validate_success,
)

CM = make_case_manager_headers()
CO = make_compliance_officer_headers("co-1")


def _judgment_with_one_payment():
    """5,000,000 cents at 1,000 bps entered 2026-01-01 with 45,000 cents of taxed
    costs, plus a single 1,000,000-cent payment received 2026-03-02."""
    ctx = setup_judgment(court_case_number="CV-2026-0001")
    ctx["payment"] = book_payment(
        ctx["judgment"]["id"], 1_000_000, received_on="2026-03-02"
    )
    return ctx


# ==========================================================================
# The same history priced under both application orders
# ==========================================================================
def test_the_two_application_orders_price_the_same_history_differently(api):
    """PRD §3.8: "If the event is a payment, its amount is consumed bucket by
    bucket: under `STATUTORY_ORDER` the buckets are taken in the order costs, then
    accrued interest, then principal; under `PRINCIPAL_FIRST` they are taken in
    the order principal, then accrued interest, then costs."
    PRD §3.8: "The same identical payment history produces a different
    `total_payoff_cents` under the two application orders, because
    `PRINCIPAL_FIRST` drives principal down faster and so accrues less interest in
    later segments while leaving unpaid interest and costs behind, whereas
    `STATUTORY_ORDER` clears costs and interest first and so keeps principal — and
    therefore future interest — higher for longer."
    PRD §3.8: "The application order is the `application_order` supplied on a
    quote request, and otherwise the judgment's own `application_order`."

    Design: Difficulty/dual_variant_calc/payoff_statutory_vs_principal_first_on_judgment_ledger
    """
    ctx = _judgment_with_one_payment()

    statutory = validate_success(
        api.get_payoff(
            ctx["judgment"]["id"], CM,
            {"as_of": "2026-08-01", "application_order": "STATUTORY_ORDER"},
        )
    )
    assert_payoff_quote_shape(statutory)
    assert statutory["total_payoff_cents"] == 4_299_064
    assert statutory["principal_balance_cents"] == 4_127_192
    assert statutory["accrued_interest_cents"] == 171_872
    assert statutory["costs_balance_cents"] == 0

    principal_first = validate_success(
        api.get_payoff(
            ctx["judgment"]["id"], CM,
            {"as_of": "2026-08-01", "application_order": "PRINCIPAL_FIRST"},
        )
    )
    assert_payoff_quote_shape(principal_first)
    assert principal_first["total_payoff_cents"] == 4_293_767
    assert principal_first["principal_balance_cents"] == 4_000_000
    assert principal_first["accrued_interest_cents"] == 248_767
    assert principal_first["costs_balance_cents"] == 45_000

    assert (
        statutory["total_payoff_cents"] - principal_first["total_payoff_cents"] == 5_297
    )


def test_the_booked_payment_split_follows_the_statutory_bucket_order(api):
    """PRD §3.8: "Booking a payment runs that replay as a persisting recompute and
    writes this payment's own split into `applied_to_costs_cents`,
    `applied_to_interest_cents` and `applied_to_principal_cents`."
    PRD §3.8: "Each bucket absorbs the smaller of the amount still unconsumed and
    that bucket's current balance, that balance falls by the amount absorbed, and
    the remainder moves to the next bucket; the amount is always fully consumed,
    which is guaranteed by the rule that a payment may never exceed the payoff."
    PRD §3.8: "When the walk finishes, `total_payoff_cents` is principal plus
    interest plus costs, and `gross_exposure_cents` is that sum plus
    `collected_to_date_cents`."

    Design: Difficulty/dual_variant_calc/payoff_statutory_vs_principal_first_on_judgment_ledger
    """
    ctx = _judgment_with_one_payment()
    payment = ctx["payment"]

    assert payment["applied_to_costs_cents"] == 45_000
    assert payment["applied_to_interest_cents"] == 82_192
    assert payment["applied_to_principal_cents"] == 872_808

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["application_order"] == "STATUTORY_ORDER"
    assert judgment["total_payoff_cents"] == 4_299_064
    assert judgment["principal_balance_cents"] == 4_127_192


# ==========================================================================
# Segment boundaries
# ==========================================================================
def test_a_quote_on_the_entry_date_produces_no_interest_segment(api):
    """PRD §3.8: "For each event in turn, the number of whole days from the cursor
    up to but not including the event date is computed; when that count is greater
    than zero, interest for the segment is the current principal multiplied by
    `interest_rate_bps`, multiplied by the number of days, divided by ten thousand
    and then by a day basis of 365, **rounded half up to a whole cent and added to
    the running interest balance**, after which the cursor advances to the event
    date."
    PRD §3.8: "And **segment boundaries are only the events, plus `entered_on` and
    the reference date** — adding taxed costs never opens a segment, because costs
    earn no interest."

    Design: Difficulty/boundary_precision_check/payoff_zero_day_segment_produces_zero_interest
    """
    ctx = setup_judgment(court_case_number="CV-2026-0606")

    quote = validate_success(
        api.get_payoff(ctx["judgment"]["id"], CM, {"as_of": "2026-01-01"})
    )
    assert_payoff_quote_shape(quote)
    assert quote["accrued_interest_cents"] == 0
    assert quote["total_payoff_cents"] == 5_045_000
    assert quote["segment_count"] == 0


def test_one_day_past_entry_produces_exactly_one_interest_segment(api):
    """PRD §3.8: "After the final event, one more segment is accrued from the
    cursor to the reference date under the same rule."
    PRD §3.8: "It answers with `as_of`, `application_order`,
    `principal_balance_cents`, `accrued_interest_cents`, `costs_balance_cents`,
    `total_payoff_cents`, `collected_to_date_cents`, `gross_exposure_cents`, and
    `segment_count`, the number of interest segments the walk produced."

    Design: Difficulty/boundary_precision_check/payoff_zero_day_segment_produces_zero_interest
    """
    ctx = setup_judgment(court_case_number="CV-2026-0607")

    quote = validate_success(
        api.get_payoff(ctx["judgment"]["id"], CM, {"as_of": "2026-01-02"})
    )
    assert_payoff_quote_shape(quote)
    assert quote["accrued_interest_cents"] == 1_370
    assert quote["total_payoff_cents"] == 5_046_370
    assert quote["segment_count"] == 1


# ==========================================================================
# Reversal conserves the ledger
# ==========================================================================
def test_booking_a_payment_moves_value_out_of_the_balances_into_collections(api):
    """PRD §2.11: "A judgment's `gross_exposure_cents` — the sum of
    `principal_balance_cents`, `accrued_interest_cents`, `costs_balance_cents` and
    `collected_to_date_cents` — is the conserved quantity across the payment and
    reversal pair, because booking a payment moves value out of the three balances
    and into collections while reversing it moves value back."

    Design: Difficulty/compensating_invariant/payment_reversal_conserves_judgment_gross_exposure
    """
    ctx = setup_judgment(court_case_number="CV-2026-0901")

    before = read_judgment(ctx["judgment"]["id"])
    assert before["gross_exposure_cents"] == 5_335_411
    assert before["principal_balance_cents"] == 5_000_000
    assert before["accrued_interest_cents"] == 290_411
    assert before["costs_balance_cents"] == 45_000

    book_payment(ctx["judgment"]["id"], 1_000_000, received_on="2026-03-02")

    during = read_judgment(ctx["judgment"]["id"])
    assert during["gross_exposure_cents"] == 5_299_064
    assert during["contingency_fee_cents"] == 330_000
    assert during["collected_to_date_cents"] == 1_000_000


def test_reversal_replays_from_entry_rather_than_patching_an_inverse_delta(api):
    """PRD §3.8: "Reversal moves the payment `APPLIED → REVERSED`, stamps
    `reversal_reason` and `reversed_on` with the current clock date, and removes
    the payment from the replay input set entirely; the judgment's balances are
    then replayed from `entered_on` over the remaining `APPLIED` payments to the
    current clock date."
    PRD §3.8: "It is never patched by an inverse delta, which would leave the
    interest segments wrong."
    PRD §3.8: "Because `collected_to_date_cents` falls, `contingency_fee_cents`
    and `net_to_creditor_cents` are recomputed from scratch — and the tier itself
    may drop, changing every surviving payment's own slice."

    Design: Difficulty/compensating_invariant/payment_reversal_conserves_judgment_gross_exposure
    """
    ctx = setup_judgment(court_case_number="CV-2026-0902")
    payment = book_payment(ctx["judgment"]["id"], 1_000_000, received_on="2026-03-02")

    reversed_payment = validate_success(
        api.reverse_payment(payment["id"], "NSF returned item", CO)
    )
    assert reversed_payment["status"] == "REVERSED"

    after = read_judgment(ctx["judgment"]["id"])
    assert after["gross_exposure_cents"] == 5_335_411
    assert after["principal_balance_cents"] == 5_000_000
    assert after["accrued_interest_cents"] == 290_411, (
        "a full replay restores 290411; an inverse-delta undo would leave 254064"
    )
    assert after["accrued_interest_cents"] != 254_064
    assert after["costs_balance_cents"] == 45_000
    assert after["collected_to_date_cents"] == 0
    assert after["contingency_fee_cents"] == 0


# ==========================================================================
# Corner coverage
# ==========================================================================
def test_the_replay_orders_payments_by_received_on_not_by_arrival(api):
    """PRD §3.8: "Payments may be recorded out of chronological order, which is
    precisely why `received_on` rather than arrival order is the replay key."
    PRD §3.8: "The surviving events are sorted by date ascending; where a payment
    and a renewal share a date, the payment is applied first and the
    capitalization second; where two payments share a date, `created_at` ascending
    breaks the tie, never the identifier."

    Design: Corner/calculations/payoff_replay_sorts_out_of_sequence_payments_by_received_on
    """
    ctx = setup_judgment(court_case_number="CV-2026-3001")

    book_payment(ctx["judgment"]["id"], 500_000, received_on="2026-06-01")
    earlier = book_payment(ctx["judgment"]["id"], 1_000_000, received_on="2026-03-02")

    assert earlier["applied_to_costs_cents"] == 45_000
    assert earlier["applied_to_interest_cents"] == 82_192
    assert earlier["applied_to_principal_cents"] == 872_808

    quote = validate_success(
        api.get_payoff(ctx["judgment"]["id"], CM, {"as_of": "2026-08-01"})
    )
    assert quote["principal_balance_cents"] == 3_730_089
    assert quote["accrued_interest_cents"] == 62_338
    assert quote["costs_balance_cents"] == 0
    assert quote["total_payoff_cents"] == 3_792_427
    assert quote["segment_count"] == 3


def test_a_payoff_quote_under_the_other_order_stores_nothing(api):
    """PRD §3.8: "Anyone with an interest in the file may pull a **non-persisting
    payoff quote** — `CaseManager`, `EnforcementOfficer`, `ComplianceOfficer`,
    `Creditor` and `Debtor` all may."
    PRD §3.8: "The quote accepts `as_of`, which defaults to the current clock
    date, and `application_order`, which defaults to the judgment's own and lets a
    caller price the other variant against an identical payment history."
    PRD §3.8: "It answers with `as_of`, `application_order`,
    `principal_balance_cents`, `accrued_interest_cents`, `costs_balance_cents`,
    `total_payoff_cents`, `collected_to_date_cents`, `gross_exposure_cents`, and
    `segment_count`, the number of interest segments the walk produced. It stores
    nothing."

    Design: Corner/endpoints/payoff_quote_with_explicit_application_order_does_not_persist
    """
    ctx = _judgment_with_one_payment()

    quote = validate_success(
        api.get_payoff(
            ctx["judgment"]["id"],
            make_creditor_headers(ctx["creditor"]["id"]),
            {"as_of": "2026-08-01", "application_order": "PRINCIPAL_FIRST"},
        )
    )
    assert quote["total_payoff_cents"] == 4_293_767
    assert quote["application_order"] == "PRINCIPAL_FIRST"

    stored = read_judgment(ctx["judgment"]["id"])
    assert stored["total_payoff_cents"] == 4_299_064
    assert stored["application_order"] == "STATUTORY_ORDER"
    assert stored["principal_balance_cents"] == 4_127_192
