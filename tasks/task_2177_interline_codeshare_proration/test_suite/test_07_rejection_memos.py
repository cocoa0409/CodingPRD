"""The rejection-memo cycle: dispute, counter, withdrawal, arbitration and the cascade."""

from test_helpers import (
    ApiErrorId,
    OPERATOR,
    assert_clearinghouse_zero_sum,
    assert_iso_instant_equals,
    accept_memo,
    assert_memo,
    counter_memo,
    create_memo_payload,
    escalate_memo,
    invoice_version,
    make_billing_agent_headers,
    read_carrier,
    read_coupon,
    read_invoice,
    read_memo,
    read_ticket,
    re_reject_memo,
    set_clock,
    setup_cleared_invoice,
    setup_cleared_invoice_with_raised_memo,
    setup_submitted_invoice,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Raise-time guards
# --------------------------------------------------------------------------- #
def test_memo_against_a_submitted_but_uncleared_invoice_is_refused(api):
    """PRD §3.8: "The invoice must be `CLEARED` or `PARTIALLY_REJECTED` — a memo against a
    `DRAFT`, `SUBMITTED`, `FULLY_REJECTED` or `SETTLED` invoice is refused with
    `ERR_INVOICE_NOT_CLEARED`."

    Design: Corner/validations/memo_against_a_submitted_but_uncleared_invoice_returns_invoice_not_cleared
    """
    ctx = setup_submitted_invoice(ticket_number="0057000000001")

    resp = api.create_memo(
        create_memo_payload(
            ctx["invoice"]["id"],
            ctx["coupon"]["id"],
            invoice_version(ctx["invoice"]["id"]),
            amount_minor=10000,
            reason_code="SPA_NOT_APPLIED",
        ),
        make_billing_agent_headers(ctx["aa"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_CLEARED.value)

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "SUBMITTED"
    assert invoice["cleared_at"] is None
    assert invoice["disputed_amount_minor"] == 0


def test_memo_amount_above_the_coupon_allocation_is_refused(api):
    """PRD §2.7: "**Memo within coupon.** The contested `amount_minor` is no larger than the
    coupon's current `allocated_amount_minor` — otherwise `ERR_MEMO_AMOUNT_EXCEEDS_COUPON`
    (422). Applies to memo raise and memo re-reject."
    PRD §2.7: "**Memo within invoice.** The invoice's `disputed_amount_minor` plus its
    `rejected_amount_minor` plus the requested `amount_minor` is no larger than its
    `total_claim_minor`; on a re-rejection the memo's own previous `amount_minor` is excluded
    from the running disputed figure before the comparison. Otherwise
    `ERR_MEMO_AMOUNT_EXCEEDS_INVOICE` (422). Applies to memo raise and memo re-reject."

    Design: Corner/validations/memo_amount_above_the_coupon_allocation_returns_exceeds_coupon
    """
    ctx = setup_cleared_invoice(ticket_number="0055000000001")
    version = invoice_version(ctx["invoice"]["id"])

    resp = api.create_memo(
        create_memo_payload(
            ctx["invoice"]["id"], ctx["coupon"]["id"], version,
            amount_minor=100001, reason_code="FARE_BASIS_ERROR",
        ),
        make_billing_agent_headers(ctx["aa"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMO_AMOUNT_EXCEEDS_COUPON.value)

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["disputed_amount_minor"] == 0
    assert invoice["version"] == version, "a refused raise bumps nothing"


def test_memo_amount_above_the_invoice_claim_is_refused(api):
    """PRD §3.8: "The contested `amount_minor` may not exceed the coupon's current
    `allocated_amount_minor` (`ERR_MEMO_AMOUNT_EXCEEDS_COUPON`), and the invoice's
    `disputed_amount_minor` plus its `rejected_amount_minor` plus the requested amount may not
    exceed its `total_claim_minor` (`ERR_MEMO_AMOUNT_EXCEEDS_INVOICE`) — on a re-rejection the
    memo's own previous `amount_minor` is first removed from the disputed running total, so
    raising a round from 400 to 500 is tested as an incremental 100, not as an additional 500."

    Design: Corner/validations/memo_amount_above_the_invoice_claim_returns_exceeds_invoice
    """
    ctx = setup_cleared_invoice(ticket_number="0056000000001")
    assert read_coupon(ctx["coupon"]["id"])["allocated_amount_minor"] == 100000
    assert read_invoice(ctx["invoice"]["id"])["total_claim_minor"] == 99250

    resp = api.create_memo(
        create_memo_payload(
            ctx["invoice"]["id"], ctx["coupon"]["id"], invoice_version(ctx["invoice"]["id"]),
            amount_minor=99500, reason_code="DUPLICATE_BILLING",
        ),
        make_billing_agent_headers(ctx["aa"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMO_AMOUNT_EXCEEDS_INVOICE.value)

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["disputed_amount_minor"] == 0
    assert invoice["status"] == "CLEARED"


def test_second_raise_on_a_stale_invoice_version_is_rejected(api):
    """PRD §2.8: "A `POST /interline/rejection-memos` request must carry
    `expected_invoice_version` holding the `version` of the target `BillingInvoice` as the
    client last read it. If that value does not equal the invoice's current `version`, the
    memo is not created and the request is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP
    412)."
    PRD §3.8: "A successful raise opens the memo in `RAISED` status at `stage` 1, copies the
    invoice's `billed_carrier_id` into `raised_by_carrier_id`, stamps `raised_at` with the
    current logical clock, sets `counter_amount_minor` to zero, adds `amount_minor` to the
    invoice's `disputed_amount_minor`, and bumps the invoice's `version`."

    Design: Corner/cross_cutting_layers/memo_raise_with_stale_invoice_version_returns_412
    """
    ctx = setup_cleared_invoice(ticket_number="0070000000001")
    stale_version = invoice_version(ctx["invoice"]["id"])

    first = validate_success(
        api.create_memo(
            create_memo_payload(
                ctx["invoice"]["id"], ctx["coupon"]["id"], stale_version,
                amount_minor=10000, reason_code="PRORATE_FACTOR_DISPUTE",
            ),
            make_billing_agent_headers(ctx["aa"]["id"]),
        ),
        201,
    )

    resp = api.create_memo(
        create_memo_payload(
            ctx["invoice"]["id"], ctx["coupon"]["id"], stale_version,
            amount_minor=5000, reason_code="SPA_NOT_APPLIED",
        ),
        make_billing_agent_headers(ctx["aa"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_INVOICE_VERSION.value)

    assert read_invoice(ctx["invoice"]["id"])["disputed_amount_minor"] == 10000
    rows, meta = validate_paginated(
        api.list_memos(OPERATOR, params={"invoice_id": ctx["invoice"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]

    retried = validate_success(
        api.create_memo(
            create_memo_payload(
                ctx["invoice"]["id"], ctx["coupon"]["id"],
                invoice_version(ctx["invoice"]["id"]),
                amount_minor=5000, reason_code="SPA_NOT_APPLIED",
            ),
            make_billing_agent_headers(ctx["aa"]["id"]),
        ),
        201,
    )
    assert retried["stage"] == 1
    assert read_invoice(ctx["invoice"]["id"])["disputed_amount_minor"] == 15000


# --------------------------------------------------------------------------- #
# Exits without a cascade
# --------------------------------------------------------------------------- #
def test_arbitrating_a_memo_that_never_escalated_is_refused(api):
    """PRD §2.7: "**Memo state.** Countering and accepting require `RAISED`; re-rejecting
    requires `COUNTERED`; withdrawing and escalating require `RAISED` or `COUNTERED`;
    arbitrating requires `ARBITRATION` — otherwise `ERR_MEMO_STATE_INVALID` (409). Applies to
    memo counter, re-reject, accept, withdraw, escalate and arbitrate."

    Design: Corner/state_machines/arbitrating_a_memo_that_never_escalated_returns_memo_state_invalid
    """
    ctx = setup_cleared_invoice_with_raised_memo(
        ticket_number="0036000000001", reason_code="DUPLICATE_BILLING"
    )

    resp = api.arbitrate_memo(ctx["memo"]["id"], "UPHELD", OPERATOR)
    validate_error(resp, ApiErrorId.ERR_MEMO_STATE_INVALID.value)

    memo = read_memo(ctx["memo"]["id"])
    assert memo["status"] == "RAISED"
    assert memo["resolved_at"] is None
    coupon = read_coupon(ctx["coupon"]["id"])
    assert coupon["allocated_amount_minor"] == 100000
    assert coupon["coupon_status"] == "FLOWN"
    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "CLEARED"
    assert invoice["rejected_amount_minor"] == 0
    assert read_carrier(ctx["aa"]["id"])["open_reproration_count"] == 0


def test_withdrawal_releases_the_disputed_amount_and_nothing_else(api):
    """PRD §3.8: "Withdrawal sets `status` to `WITHDRAWN`, stamps `resolved_at`, subtracts the
    memo's `amount_minor` from the invoice's `disputed_amount_minor`, and bumps both versions
    — no balance, coupon or ticket is touched."

    Design: Corner/state_machines/memo_withdraw_releases_the_disputed_amount_without_touching_the_coupon
    """
    ctx = setup_cleared_invoice_with_raised_memo(
        ticket_number="0037000000001", reason_code="CURRENCY_ERROR"
    )
    assert read_invoice(ctx["invoice"]["id"])["disputed_amount_minor"] == 10000

    memo = validate_success(
        api.withdraw_memo(
            ctx["memo"]["id"],
            {"expected_invoice_version": invoice_version(ctx["invoice"]["id"])},
            make_billing_agent_headers(ctx["aa"]["id"]),
        ),
        200,
    )
    assert_memo(memo)
    assert memo["status"] == "WITHDRAWN"
    assert_iso_instant_equals(memo["resolved_at"], "2026-09-06T00:00:00Z")

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["disputed_amount_minor"] == 0
    assert invoice["rejected_amount_minor"] == 0
    assert invoice["status"] == "CLEARED"

    coupon = read_coupon(ctx["coupon"]["id"])
    assert coupon["allocated_amount_minor"] == 100000
    assert coupon["adjusted_amount_minor"] == 0
    assert coupon["coupon_status"] == "FLOWN"

    ticket = read_ticket(ctx["ticket"]["id"])
    assert ticket["proration_status"] == "FINAL"
    assert ticket["billing_status"] == "BILLED"

    assert read_carrier(ctx["bb"]["id"])["settled_receivable_minor"] == 99250
    assert read_carrier(ctx["aa"]["id"])["settled_payable_minor"] == 99250
    assert read_carrier(ctx["aa"]["id"])["open_reproration_count"] == 0


def test_escalating_a_young_stage_one_memo_is_refused(api):
    """PRD §3.8: "Either side's `BillingAgent`, matched on `billing_carrier_id` or on
    `billed_carrier_id`, may escalate a `RAISED` or `COUNTERED` memo into `ARBITRATION`, but
    only once it is exhausted or stale: the memo's `stage` must be 3, or its `age_days` must
    be at least 90. An escalation that meets neither condition is refused with
    `ERR_ARBITRATION_NOT_ELIGIBLE`."
    PRD §3.8: "From `age_days` follows `aging_bucket`: `CURRENT` below 30 days, `AGED_30` from
    30 up to but not including 60, `AGED_60` from 60 up to but not including 90, and `AGED_90`
    at 90 days and beyond."

    Design: Corner/errors/escalating_a_young_stage_one_memo_returns_arbitration_not_eligible
    """
    ctx = setup_cleared_invoice_with_raised_memo(
        ticket_number="0066000000001", reason_code="CURRENCY_ERROR"
    )

    resp = api.escalate_memo(ctx["memo"]["id"], make_billing_agent_headers(ctx["aa"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ARBITRATION_NOT_ELIGIBLE.value)

    memo = read_memo(ctx["memo"]["id"])
    assert memo["status"] == "RAISED"
    assert memo["stage"] == 1
    assert memo["age_days"] == 0
    assert memo["aging_bucket"] == "CURRENT"


def test_memo_escalates_at_exactly_ninety_days_of_age(api):
    """PRD §3.8: "A memo's `age_days` is the whole number of days between `raised_at` and an
    anchor instant, computed by taking the difference in whole seconds and dividing by 86400
    with the remainder discarded."
    PRD §3.8: "Either side's `BillingAgent`, matched on `billing_carrier_id` or on
    `billed_carrier_id`, may escalate a `RAISED` or `COUNTERED` memo into `ARBITRATION`, but
    only once it is exhausted or stale: the memo's `stage` must be 3, or its `age_days` must
    be at least 90. An escalation that meets neither condition is refused with
    `ERR_ARBITRATION_NOT_ELIGIBLE`."
    PRD §3.8: "Escalation sets `status` to `ARBITRATION` and bumps the memo's `version`;
    nothing else moves."

    Design: Corner/cross_cutting_layers/memo_escalates_at_exactly_ninety_days_of_age
    """
    ctx = setup_cleared_invoice_with_raised_memo(ticket_number="0072000000001")
    set_clock("2026-12-05T00:00:00Z")

    aged = read_memo(ctx["memo"]["id"])
    assert aged["age_days"] == 90, f"expected 90 whole days, got {aged['age_days']}"
    assert aged["aging_bucket"] == "AGED_90"

    escalated = validate_success(
        api.escalate_memo(ctx["memo"]["id"], make_billing_agent_headers(ctx["bb"]["id"])),
        200,
    )
    assert escalated["status"] == "ARBITRATION"
    assert escalated["stage"] == 1, "the age gate alone carried it, not the stage gate"
    assert read_invoice(ctx["invoice"]["id"])["disputed_amount_minor"] == 10000


def test_arbitrated_denial_settles_the_dispute_without_moving_a_cent(api):
    """PRD §3.8: "A `DENIED` ruling sets `status` to `RESOLVED_DENIED`, stamps `resolved_at`,
    subtracts the memo's `amount_minor` from the invoice's `disputed_amount_minor`, bumps both
    the memo's and the invoice's `version`, and stops there — no balance, coupon or ticket
    effect at all."
    PRD §3.8: "The anchor is the memo's `resolved_at` once it has reached any of the four
    resolved states, and the current logical clock while it is still live; the value is
    therefore recomputed on every read of a memo and frozen at resolution."

    Design: Corner/consistency_model/arbitrated_denial_settles_the_dispute_without_moving_a_cent
    """
    ctx = setup_cleared_invoice_with_raised_memo(
        ticket_number="0073000000001", reason_code="FARE_BASIS_ERROR"
    )
    set_clock("2026-12-05T00:00:00Z")
    escalate_memo(ctx["memo"]["id"], ctx["aa"]["id"])

    ruled = validate_success(api.arbitrate_memo(ctx["memo"]["id"], "DENIED", OPERATOR), 200)
    assert ruled["status"] == "RESOLVED_DENIED"
    assert_iso_instant_equals(ruled["resolved_at"], "2026-12-05T00:00:00Z")

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["disputed_amount_minor"] == 0
    assert invoice["rejected_amount_minor"] == 0
    assert invoice["status"] == "CLEARED"
    assert invoice["net_billed_minor"] == 99250

    coupon = read_coupon(ctx["coupon"]["id"])
    assert coupon["allocated_amount_minor"] == 100000
    assert coupon["adjusted_amount_minor"] == 0
    assert coupon["coupon_status"] == "FLOWN"

    ticket = read_ticket(ctx["ticket"]["id"])
    assert ticket["proration_status"] == "FINAL"
    assert ticket["billing_status"] == "BILLED"

    aa = read_carrier(ctx["aa"]["id"])
    bb = read_carrier(ctx["bb"]["id"])
    assert bb["settled_receivable_minor"] == 99250
    assert aa["settled_payable_minor"] == 99250
    assert aa["open_reproration_count"] == 0
    assert_clearinghouse_zero_sum([aa, bb])
    assert read_memo(ctx["memo"]["id"])["age_days"] == 90, "frozen at resolution"


def test_re_rejecting_a_stage_three_memo_is_refused(api):
    """PRD §3.8: "Re-rejection requires the memo to be `COUNTERED` and its `stage` to be below
    3; a fourth round is refused with `ERR_MEMO_STAGE_EXHAUSTED`. It returns `status` to
    `RAISED`, increments `stage` by one, overwrites `amount_minor` and `reason_code`, resets
    `counter_amount_minor` to zero, adjusts the invoice's `disputed_amount_minor` by the
    difference between the old and new amounts, and bumps both the memo's and the invoice's
    `version`."

    Design: Corner/errors/re_rejecting_a_stage_three_memo_returns_stage_exhausted
    """
    ctx = setup_cleared_invoice_with_raised_memo(ticket_number="0065000000001")
    memo_id = ctx["memo"]["id"]
    invoice_id = ctx["invoice"]["id"]

    counter_memo(memo_id, ctx["bb"]["id"], 4000, "round one")
    re_reject_memo(memo_id, invoice_id, ctx["aa"]["id"], 12000, "SPA_NOT_APPLIED")
    counter_memo(memo_id, ctx["bb"]["id"], 5000, "round two")
    re_reject_memo(memo_id, invoice_id, ctx["aa"]["id"], 15000, "FARE_BASIS_ERROR")
    counter_memo(memo_id, ctx["bb"]["id"], 6000, "round three")
    version_before = invoice_version(invoice_id)

    resp = api.re_reject_memo(
        memo_id,
        {
            "amount_minor": 18000,
            "reason_code": "DUPLICATE_BILLING",
            "expected_invoice_version": version_before,
        },
        make_billing_agent_headers(ctx["aa"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMO_STAGE_EXHAUSTED.value)

    memo = read_memo(memo_id)
    assert memo["stage"] == 3
    assert memo["status"] == "COUNTERED"
    assert memo["amount_minor"] == 15000
    assert memo["counter_amount_minor"] == 6000

    invoice = read_invoice(invoice_id)
    assert invoice["disputed_amount_minor"] == 15000
    assert invoice["version"] == version_before, "the refused fourth round bumps nothing"


# --------------------------------------------------------------------------- #
# The RAISED -> COUNTERED -> RAISED negotiation cycle
# --------------------------------------------------------------------------- #
def _memo_through_two_counter_rounds():
    ctx = setup_cleared_invoice_with_raised_memo(ticket_number="0016000000001")
    memo_id = ctx["memo"]["id"]
    invoice_id = ctx["invoice"]["id"]
    counter_memo(memo_id, ctx["bb"]["id"], 4000, "MITA straight-rate factor correctly applied")
    re_reject_memo(memo_id, invoice_id, ctx["aa"]["id"], 12000, "SPA_NOT_APPLIED")
    counter_memo(memo_id, ctx["bb"]["id"], 5000, "no SPA in force for this sector")
    re_reject_memo(memo_id, invoice_id, ctx["aa"]["id"], 15000, "FARE_BASIS_ERROR")
    return ctx


def test_memo_returns_to_raised_at_stage_three_after_two_counter_rounds(api):
    """PRD §3.8: "Re-rejection requires the memo to be `COUNTERED` and its `stage` to be below
    3; a fourth round is refused with `ERR_MEMO_STAGE_EXHAUSTED`. It returns `status` to
    `RAISED`, increments `stage` by one, overwrites `amount_minor` and `reason_code`, resets
    `counter_amount_minor` to zero, adjusts the invoice's `disputed_amount_minor` by the
    difference between the old and new amounts, and bumps both the memo's and the invoice's
    `version`."
    PRD §3.8: "Countering supplies a `counter_amount_minor`, which may not exceed the memo's
    `amount_minor`, and a free-text `counter_reason`; it sets `status` to `COUNTERED`, records
    both fields, bumps the memo's `version`, and pointedly leaves the invoice's
    `disputed_amount_minor` unchanged, because nothing has been conceded in ledger terms yet."

    Design: Difficulty/non_linear_state_machine/memo_raised_countered_raised_negotiation_cycle
    """
    ctx = _memo_through_two_counter_rounds()

    memo = read_memo(ctx["memo"]["id"])
    assert_memo(memo)
    assert memo["status"] == "RAISED", "the cycle ends back on the RAISED side"
    assert memo["stage"] == 3
    assert memo["amount_minor"] == 15000
    assert memo["counter_amount_minor"] == 0

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["disputed_amount_minor"] == 15000
    assert invoice["rejected_amount_minor"] == 0


def test_re_rejection_never_restarts_the_memo_aging_clock(api):
    """PRD §3.8: "Critically, it leaves `raised_at` alone — the aging clock keeps running from
    the original raise across the entire negotiation, which is what stops a carrier from
    resetting the clock by stalling."
    PRD §3.8: "From `age_days` follows `aging_bucket`: `CURRENT` below 30 days, `AGED_30` from
    30 up to but not including 60, `AGED_60` from 60 up to but not including 90, and `AGED_90`
    at 90 days and beyond."

    Design: Difficulty/non_linear_state_machine/memo_raised_countered_raised_negotiation_cycle
    """
    ctx = _memo_through_two_counter_rounds()

    memo = read_memo(ctx["memo"]["id"])
    assert_iso_instant_equals(memo["raised_at"], "2026-09-06T00:00:00Z")
    assert memo["age_days"] == 0
    assert memo["aging_bucket"] == "CURRENT"

    set_clock("2026-10-06T00:00:00Z")
    aged = read_memo(ctx["memo"]["id"])
    assert aged["age_days"] == 30, "the clock still runs from the original raise"
    assert aged["aging_bucket"] == "AGED_30"


# --------------------------------------------------------------------------- #
# The five-hop acceptance cascade
# --------------------------------------------------------------------------- #
def _accepted_memo_scenario():
    ctx = setup_cleared_invoice_with_raised_memo(ticket_number="0018000000001")
    ctx["accepted"] = accept_memo(
        ctx["memo"]["id"], ctx["invoice"]["id"], ctx["bb"]["id"]
    )
    return ctx


def test_memo_acceptance_moves_the_invoice_and_both_settled_balances(api):
    """PRD §3.8: "Hop 1 resolves the memo itself: `status` becomes `ACCEPTED` or
    `RESOLVED_UPHELD`, `resolved_at` is stamped with the current logical clock, `age_days` and
    `aging_bucket` freeze, and the memo's `version` bumps."
    PRD §3.8: "The memo's `amount_minor` is added to the invoice's `rejected_amount_minor` and
    removed from its `disputed_amount_minor`, and `net_billed_minor` is recomputed as
    `total_claim_minor` less the new `rejected_amount_minor`. The memo's
    `settlement_impact_minor` is written as its `amount_minor` multiplied by the invoice's
    `fixed_rate_scaled`, divided by 1000000, rounded half up, and that figure is subtracted
    from the billing carrier's `settled_receivable_minor` and from the billed carrier's
    `settled_payable_minor`, with `net_position_minor` recomputed on both."
    PRD §3.8: "The fork is decided by one comparison: if the invoice's `rejected_amount_minor`
    before this memo plus the memo's `amount_minor` is strictly less than `total_claim_minor`
    the invoice moves to `PARTIALLY_REJECTED`; if it is greater than or equal to
    `total_claim_minor` the invoice moves to `FULLY_REJECTED`."

    Design: Difficulty/transitive_cascade/memo_accept_five_hop_cascade_to_carrier_counter
    """
    ctx = _accepted_memo_scenario()

    memo = read_memo(ctx["memo"]["id"])
    assert memo["status"] == "ACCEPTED"
    assert_iso_instant_equals(memo["resolved_at"], "2026-09-06T00:00:00Z")
    assert memo["settlement_impact_minor"] == 10000

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "PARTIALLY_REJECTED"
    assert invoice["rejected_amount_minor"] == 10000
    assert invoice["disputed_amount_minor"] == 0
    assert invoice["net_billed_minor"] == 89250

    assert read_carrier(ctx["bb"]["id"])["settled_receivable_minor"] == 89250
    assert read_carrier(ctx["aa"]["id"])["settled_payable_minor"] == 89250


def test_memo_acceptance_cascades_through_coupon_ticket_and_carrier(api):
    """PRD §3.8: "Hop 3 moves the contested coupon, because the invoice's
    `rejected_amount_minor` increased. The memo's `amount_minor` is subtracted from the
    coupon's `allocated_amount_minor` and the same figure added to its
    `adjusted_amount_minor`; `coupon_status` becomes `ADJUSTED`; and the same figure is added
    to the owning ticket's `unallocated_residual_minor`, which is what preserves the
    fare-conservation identity through the adjustment."
    PRD §3.8: "Hop 4 moves the owning ticket, because its coupon changed: `proration_status`
    becomes `REPRORATION_REQUIRED` and `billing_status` becomes `DISPUTED`, both written in
    the same hop even though the two axes remain independently reachable, and the ticket's
    `version` bumps."
    PRD §3.8: "Hop 5 moves the validating carrier, because the ticket entered
    `REPRORATION_REQUIRED`: that carrier's `open_reproration_count` increments by one, and
    once the resulting count reaches 3 or more its `audit_flag` is set to true."

    Design: Difficulty/transitive_cascade/memo_accept_five_hop_cascade_to_carrier_counter
    """
    ctx = _accepted_memo_scenario()

    coupon = read_coupon(ctx["coupon"]["id"])
    assert coupon["allocated_amount_minor"] == 90000
    assert coupon["adjusted_amount_minor"] == 10000
    assert coupon["coupon_status"] == "ADJUSTED"

    ticket = read_ticket(ctx["ticket"]["id"])
    assert ticket["unallocated_residual_minor"] == 10000, "90000 + 10000 == the 100000 fare"
    assert ticket["proration_status"] == "REPRORATION_REQUIRED"
    assert ticket["billing_status"] == "DISPUTED"

    aa = read_carrier(ctx["aa"]["id"])
    bb = read_carrier(ctx["bb"]["id"])
    assert aa["open_reproration_count"] == 1
    assert aa["audit_flag"] is False, "the flag only trips once the count reaches 3"
    assert aa["net_position_minor"] == -89250
    assert bb["net_position_minor"] == 89250
    assert_clearinghouse_zero_sum([aa, bb])


# --------------------------------------------------------------------------- #
# The dispute window outranks the coupon-on-invoice check
# --------------------------------------------------------------------------- #
def _cleared_invoice_plus_an_uninvoiced_coupon():
    from test_helpers import new_carrier, setup_flown_final_prorated_ticket

    ctx = setup_cleared_invoice(ticket_number="0021000000001")
    ctx["invoice_version_at_clearance"] = invoice_version(ctx["invoice"]["id"])
    cc = new_carrier("CC")
    _ticket2, coupons2, _run2 = setup_flown_final_prorated_ticket(
        ctx["aa"]["id"],
        cc["id"],
        ticket_number="0021000000002",
        total_fare_minor=50000,
        tpm_miles=500,
        origin="CDG",
        destination="FCO",
    )
    ctx["cc"] = cc
    ctx["foreign_coupon"] = coupons2[0]
    return ctx


def test_expired_dispute_window_outranks_the_coupon_on_invoice_check(api):
    """PRD §2.7: "**Memo window.** The current logical clock is at most 45 whole days after
    the invoice's `cleared_at` — otherwise `ERR_MEMO_WINDOW_EXPIRED` (409). Applies to memo
    raise and memo re-reject."
    PRD §2.7: "**Coupon on invoice.** The contested `coupon_id` has a `billing_invoice_id`
    equal to the `invoice_id` named in the request (for a re-rejection, the memo's own
    invoice) — otherwise `ERR_COUPON_NOT_ON_INVOICE` (422). Applies to memo raise."
    PRD §2.7: "This ladder is global and absolute: a later check never masks an earlier one,
    and a request that would fail step 30 but also fails step 4 is answered as step 4."

    Design: Difficulty/priority_pair_validation_conflict/memo_raise_window_beats_coupon_not_on_invoice
    """
    ctx = _cleared_invoice_plus_an_uninvoiced_coupon()
    assert read_coupon(ctx["foreign_coupon"]["id"])["billing_invoice_id"] is None

    set_clock("2026-10-22T00:00:00Z")
    resp = api.create_memo(
        create_memo_payload(
            ctx["invoice"]["id"],
            ctx["foreign_coupon"]["id"],
            ctx["invoice_version_at_clearance"],
            amount_minor=5000,
            reason_code="FARE_BASIS_ERROR",
        ),
        make_billing_agent_headers(ctx["aa"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMO_WINDOW_EXPIRED.value)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_COUPON_NOT_ON_INVOICE.value


def test_late_memo_raise_creates_no_memo_and_leaves_the_invoice_untouched(api):
    """PRD §3.8: "A memo must also be raised inside the clearing house's dispute window: the
    current logical clock may be no more than 45 whole days after the invoice's `cleared_at`,
    and a late raise or a late re-rejection is refused with `ERR_MEMO_WINDOW_EXPIRED`."
    PRD §2.7: "When a request violates more than one rule, the response is decided by the
    **first** rule that fails in the ordering below, and no side effect of the request has
    been applied when it does."

    Design: Difficulty/priority_pair_validation_conflict/memo_raise_window_beats_coupon_not_on_invoice
    """
    ctx = _cleared_invoice_plus_an_uninvoiced_coupon()
    version_at_clearance = ctx["invoice_version_at_clearance"]

    set_clock("2026-10-22T00:00:00Z")
    validate_error(
        api.create_memo(
            create_memo_payload(
                ctx["invoice"]["id"],
                ctx["foreign_coupon"]["id"],
                version_at_clearance,
                amount_minor=5000,
                reason_code="FARE_BASIS_ERROR",
            ),
            make_billing_agent_headers(ctx["aa"]["id"]),
        ),
        ApiErrorId.ERR_MEMO_WINDOW_EXPIRED.value,
    )

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["disputed_amount_minor"] == 0
    assert invoice["version"] == version_at_clearance
    _rows, meta = validate_paginated(
        api.list_memos(OPERATOR, params={"invoice_id": ctx["invoice"]["id"]})
    )
    assert meta["total_count"] == 0, "no memo row survives a refused raise"
