"""Boundary and precision tests: metrics evaluated exactly on their threshold,
one step past it, and against an empty input set.

Every threshold in this file is a strict comparison, so the on-boundary value is
clean and only the value one step beyond it is refused. Each refusal is also
checked for the absence of side effects.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, BUILD_FROM, BUILD_TO, SEP_01

REPORT_INSTANT = "2026-08-21T00:00:00.000Z"

SUV_EAST_LEASE_RULE = {
    "model_code": "SUV7",
    "region_code": "EAST",
    "build_date_from": BUILD_FROM,
    "build_date_to": BUILD_TO,
    "allowed_deal_types": ["LEASE"],
}


# --- Setup: three deliveries reported at one logical instant ------------------


def _lag_boundary_deliveries() -> dict:
    """One dealer and three CASH deliveries reported at the same logical instant
    2026-08-21T00:00:00.000Z, so `reported_at` is identical across them and the
    asserted sale instant is the only variable: 2026-08-11 gives a lag of exactly
    ten days, 2026-08-10 gives eleven, and 2026-08-22 is future-dated."""
    fx.set_clock(REPORT_INSTANT)
    dealer = fx.register_dealer(
        dealer_code="D-830",
        name="Eastvale Motorworks",
        region_code="EAST",
        historical_volume_units=7,
        market_opportunity_bps=0,
    )

    def _report(sale_date: str) -> dict:
        return fx.report_delivery(
            dealer["id"],
            model_code="MX5",
            trim_code="BASE",
            build_date="2026-06-01T00:00:00.000Z",
            msrp_cents=3100000,
            sale_date=sale_date,
            customer_region_code="EAST",
            deal_type="CASH",
        )

    return {
        "dealer": dealer,
        "lag_10": _report("2026-08-11T00:00:00.000Z"),
        "lag_11": _report("2026-08-10T00:00:00.000Z"),
        "future": _report("2026-08-22T00:00:00.000Z"),
    }


def test_a_reporting_lag_of_exactly_ten_days_is_clean_and_validates():
    """A reporting lag landing exactly on ten days leaves the flag false and the
    delivery validates normally.

    PRD: "`back_dated_flag` is set to true when either of two conditions holds:
    `reporting_lag_days` is **strictly greater** than ten days, or `sale_date` is
    strictly later than `reported_at`. The strictness matters — a lag of exactly
    ten days is clean and leaves the flag false."

    Design: Difficulty/boundary_precision_check/reporting_lag_boundary_is_strictly_greater_than_ten_days
    """
    state = _lag_boundary_deliveries()

    # reported_at is the logical clock, never wall-clock time, and is identical
    # across all three reports.
    for key in ("lag_10", "lag_11", "future"):
        assert state[key]["reported_at"] == REPORT_INSTANT, state[key]

    on_boundary = state["lag_10"]
    a.assert_int_field(on_boundary, "reporting_lag_days", 10)
    assert on_boundary["back_dated_flag"] is False, on_boundary

    validated = validate_success(
        api_client.validate_delivery(on_boundary["id"], fx.VALIDATOR)
    )
    a.assert_status(validated, "VALIDATED")


def test_a_reporting_lag_of_eleven_days_is_flagged_and_cannot_be_validated():
    """One day past the boundary flips the flag and the validation is refused.

    PRD: "Its `back_dated_flag` must be false, and a flagged delivery is refused
    with `ERR_BACK_DATED_SALE_DETECTED`."

    Design: Difficulty/boundary_precision_check/reporting_lag_boundary_is_strictly_greater_than_ten_days
    """
    state = _lag_boundary_deliveries()

    just_over = state["lag_11"]
    a.assert_int_field(just_over, "reporting_lag_days", 11)
    assert just_over["back_dated_flag"] is True, just_over

    response = api_client.validate_delivery(just_over["id"], fx.VALIDATOR)
    validate_error(response, ApiErrorId.ERR_BACK_DATED_SALE_DETECTED.value)

    # The refused validation incremented nothing.
    after = fx.read_delivery(just_over["id"])
    a.assert_status(after, "REPORTED")
    a.assert_null_fields(after, ["validated_by_user_id"])
    a.assert_version(after, 1)


def test_a_future_dated_sale_is_caught_by_the_second_arm_and_keeps_a_negative_lag():
    """A sale instant later than the report is flagged by the second arm of the
    condition rather than by the ten-day threshold, and the lag is stored
    negative rather than clamped to zero.

    PRD: "`reporting_lag_days` is the whole number of days between the sale and
    the report: the elapsed seconds from `sale_date` to `reported_at` divided by
    86400 seconds and floored toward negative infinity. The value is therefore
    negative whenever a dealer reports a future-dated sale."

    Design: Difficulty/boundary_precision_check/reporting_lag_boundary_is_strictly_greater_than_ten_days
    """
    state = _lag_boundary_deliveries()

    future = state["future"]
    a.assert_int_field(future, "reporting_lag_days", -1)
    assert future["back_dated_flag"] is True, future
    # The threshold arm is not what caught it: -1 is not strictly greater than 10.
    assert future["reporting_lag_days"] < 10, future

    response = api_client.validate_delivery(future["id"], fx.VALIDATOR)
    validate_error(response, ApiErrorId.ERR_BACK_DATED_SALE_DETECTED.value)


# --- Setup: a lease program whose only claim was rejected ---------------------


def _zero_denominator_lease_program() -> tuple:
    """A DRAFT LEASE_SUPPORT program with a funded budget of 8000000 cents and no
    claims at all, plus the dealer that will later claim against it."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="D-840",
        name="Larkspur Leasing Motors",
        region_code="EAST",
        historical_volume_units=5,
        market_opportunity_bps=0,
    )
    program = fx.create_draft_program(
        f.create_program_payload(
            program_code="ZERO-LSE",
            name="Zero Denominator Lease Support",
            incentive_type="LEASE_SUPPORT",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=100000,
            residual_support_bps=400,
            budget_cents=8000000,
            stack_group="ZERO",
            priority_rank=81,
            accrual_method="UNIT_BASED",
        )
    )
    return dealer, program


def _rejected_only_lease_claim() -> dict:
    """Carry that program to ACTIVE, give it one VALIDATED SUV7 LEASE delivery and
    one claim, and have the claim adjudicated with decision REJECT — so both
    aggregate denominators end up empty."""
    dealer, program = _zero_denominator_lease_program()
    fx.add_eligibility_rule(program["id"], **SUV_EAST_LEASE_RULE)
    fx.submit_program(program["id"])
    fx.approve_program(program["id"])

    fx.set_clock("2026-08-07T00:00:00.000Z")
    delivery = fx.report_lease_delivery(
        dealer["id"],
        model_code="SUV7",
        trim_code="TOURING",
        build_date="2026-06-15T00:00:00.000Z",
        msrp_cents=4800000,
        sale_date="2026-08-07T00:00:00.000Z",
        customer_region_code="EAST",
        term_months=36,
        base_residual_bps=5200,
    )
    fx.validate_delivery(delivery["id"])
    claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 292000)
    rejected = fx.adjudicate_claim(
        claim["id"], "REJECT", rejection_error_id="ERR_NO_ELIGIBLE_PROGRAM"
    )
    return {
        "dealer": dealer,
        "program": program,
        "delivery": delivery,
        "claim": rejected,
    }


def test_spend_summary_of_a_program_with_no_claims_at_all_is_all_integer_zeros():
    """With no claims in existence both quotients are exactly 0 integers, never
    null and never a division error.

    PRD: "`per_unit_spend_cents` is that spend divided by `claimed_units` and
    floored; when `claimed_units` is 0 the result is exactly 0 rather than null
    and never a division error."

    Design: Difficulty/boundary_precision_check/empty_claim_set_yields_zero_per_unit_spend_and_zero_residual_impact
    """
    _dealer, program = _zero_denominator_lease_program()

    summary = validate_success(api_client.get_spend_summary(program["id"], fx.DESIGNER))
    a.assert_spend_summary(
        summary,
        program["id"],
        claimed_units=0,
        committed_cents=0,
        paid_cents=0,
        accrued_budget_cents=0,
        per_unit_spend_cents=0,
        residual_impact_bps=0,
        budget_remaining_cents=8000000,
    )


def test_a_rejected_only_claim_leaves_per_unit_spend_and_the_ledger_at_zero():
    """The program's single claim was rejected, so it leaves the monitored claim
    set and the per-unit spend quotient falls back to the exact zero of the empty
    denominator.

    PRD: "It rests on the same claim set as the committed ledger: the program's
    claims whose `validation_status` is `VALIDATED` and whose `payment_status` is
    `UNPAID`, `SCHEDULED` or `PAID`, so that rejected and charged-back claims
    leave the set immediately."

    Design: Difficulty/boundary_precision_check/empty_claim_set_yields_zero_per_unit_spend_and_zero_residual_impact
    """
    state = _rejected_only_lease_claim()

    claim = state["claim"]
    a.assert_claim_dimensions(claim, "REJECTED", "UNPAID")
    a.assert_money(claim, "approved_amount_cents", 0)
    assert claim["rejection_error_id"] == "ERR_NO_ELIGIBLE_PROGRAM", claim

    summary = validate_success(
        api_client.get_spend_summary(state["program"]["id"], fx.ADJUDICATOR)
    )
    a.assert_int_field(summary, "claimed_units", 0)
    a.assert_money(summary, "per_unit_spend_cents", 0)
    a.assert_money(summary, "committed_cents", 0)
    a.assert_money(summary, "paid_cents", 0)
    a.assert_money(summary, "accrued_budget_cents", 0)
    # budget_remaining_cents is budget_cents minus committed_cents, and committed
    # is 0, so the whole funded budget is still available.
    a.assert_money(summary, "budget_remaining_cents", 8000000)


def test_a_rejected_only_claim_leaves_residual_impact_at_zero():
    """The lease program's supported unit count is 0, so the residual calculation
    stops at its second step and never reaches either of the two divisions
    downstream of it.

    PRD: "Step two counts those same claims as the supported unit count, and if
    that count is 0 then `residual_impact_bps` is 0 and the calculation stops."

    Design: Difficulty/boundary_precision_check/empty_claim_set_yields_zero_per_unit_spend_and_zero_residual_impact
    """
    state = _rejected_only_lease_claim()

    program = fx.read_program(state["program"]["id"])
    assert program["incentive_type"] == "LEASE_SUPPORT", program
    a.assert_bps(program, "residual_impact_bps", 0)

    # The empty input set is a 200 with the full projection, never a 404 and
    # never an error.
    summary = validate_success(
        api_client.get_spend_summary(state["program"]["id"], fx.ADJUDICATOR), 200
    )
    a.assert_bps(summary, "residual_impact_bps", 0)
    a.assert_money(summary, "per_unit_spend_cents", 0)


# --- Setup: a CAPPED_TOTAL pair and two deliveries straddling the cap ---------


def _capped_pair_state() -> dict:
    """A CUSTOMER_CASH program and a LEASE_SUPPORT program over the same
    SUV7/EAST/LEASE footprint, joined by a CAPPED_TOTAL edge whose combined
    ceiling is 400000 cents. Neither program sets an own ceiling, so the pair cap
    is the only headroom. Two LEASE deliveries differ by 25 cents of MSRP, which
    is exactly the gap that moves the lease leg by one cent, and each already
    carries an accepted cash claim of 150000 cents."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="D-850",
        name="Stonegate Auto Plaza",
        region_code="EAST",
        historical_volume_units=8,
        market_opportunity_bps=0,
    )

    prog_cash = fx.create_draft_program(
        f.create_program_payload(
            program_code="CAP-CASH",
            name="Capped Stack Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=150000,
            stack_cap_cents=0,
            budget_cents=90000000,
            stack_group="CAP",
            priority_rank=91,
            accrual_method="UNIT_BASED",
        )
    )
    fx.add_eligibility_rule(prog_cash["id"], **SUV_EAST_LEASE_RULE)

    prog_lease = fx.create_draft_program(
        f.create_program_payload(
            program_code="CAP-LSE",
            name="Capped Stack Lease Support",
            incentive_type="LEASE_SUPPORT",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=100000,
            residual_support_bps=400,
            stack_cap_cents=0,
            budget_cents=90000000,
            stack_group="CAP",
            priority_rank=92,
            accrual_method="UNIT_BASED",
        )
    )
    fx.add_eligibility_rule(prog_lease["id"], **SUV_EAST_LEASE_RULE)

    edge = fx.add_stack_edge(
        prog_cash["id"], prog_lease["id"], mode="CAPPED_TOTAL",
        cap_amount_cents=400000,
    )

    fx.submit_program(prog_cash["id"])
    fx.approve_program(prog_cash["id"])
    fx.submit_program(prog_lease["id"])
    fx.approve_program(prog_lease["id"])

    fx.set_clock("2026-08-09T00:00:00.000Z")

    def _report(msrp_cents: int, build_date: str) -> dict:
        return fx.report_lease_delivery(
            dealer["id"],
            model_code="SUV7",
            trim_code="TOURING",
            build_date=build_date,
            msrp_cents=msrp_cents,
            sale_date="2026-08-09T00:00:00.000Z",
            customer_region_code="EAST",
            term_months=36,
            base_residual_bps=5200,
        )

    del_on = _report(3750000, "2026-06-05T00:00:00.000Z")
    del_over = _report(3750025, "2026-06-06T00:00:00.000Z")
    fx.validate_delivery(del_on["id"])
    fx.validate_delivery(del_over["id"])

    claim_on_cash = fx.submit_claim(
        dealer["id"], del_on["id"], prog_cash["id"], 150000
    )
    claim_over_cash = fx.submit_claim(
        dealer["id"], del_over["id"], prog_cash["id"], 150000
    )

    return {
        "dealer": dealer,
        "prog_cash": prog_cash,
        "prog_lease": prog_lease,
        "edge": edge,
        "del_on": del_on,
        "del_over": del_over,
        "claim_on_cash": claim_on_cash,
        "claim_over_cash": claim_over_cash,
    }


def _claim_lease_leg(state: dict, delivery_id: str, claimed_amount_cents: int):
    """Submit the lease-support claim for one delivery with a fresh version guard."""
    return api_client.create_claim(
        f.create_claim_payload(
            delivery_id,
            state["prog_lease"]["id"],
            claimed_amount_cents,
            fx.program_version(state["prog_lease"]["id"]),
        ),
        make_dealer_headers(state["dealer"]["id"]),
    )


def test_stacked_total_landing_exactly_on_the_pair_cap_is_accepted():
    """A running total of 150000 plus a gross of 250000 lands exactly on the
    400000 pair cap and is accepted, because the comparison is strict.

    PRD: "A stacked total landing exactly on the headroom is accepted, because
    the comparison is strict."

    Design: Difficulty/boundary_precision_check/stacked_total_landing_exactly_on_the_pair_cap_is_accepted
    """
    state = _capped_pair_state()

    a.assert_money(state["edge"], "cap_amount_cents", 400000)
    # Headroom is the pair cap alone: neither program sets an own ceiling.
    a.assert_money(fx.read_program(state["prog_cash"]["id"]), "stack_cap_cents", 0)
    a.assert_money(fx.read_program(state["prog_lease"]["id"]), "stack_cap_cents", 0)
    # Both cash claims stand, each contributing a gross of 150000 as the running
    # total the waterfall starts from.
    a.assert_claim_dimensions(
        fx.read_claim(state["claim_on_cash"]["id"]), "SUBMITTED", "UNPAID"
    )
    a.assert_claim_dimensions(
        fx.read_claim(state["claim_over_cash"]["id"]), "SUBMITTED", "UNPAID"
    )

    claim = validate_success(
        _claim_lease_leg(state, state["del_on"]["id"], 250000), 201
    )
    a.assert_money(claim, "snapshot_per_unit_cents", 100000)

    approved = fx.adjudicate_claim(claim["id"])
    a.assert_claim_dimensions(approved, "VALIDATED", "UNPAID")
    # 100000 of per-unit rate plus a lease leg of 150000 on an MSRP of 3750000.
    a.assert_money(approved, "approved_amount_cents", 250000)


def test_a_stacked_total_one_cent_over_the_pair_cap_is_refused_and_persists_nothing():
    """Twenty-five cents more MSRP moves the lease leg to 150001, the stacked
    total to 400001, and the claim is refused rather than quietly trimmed.

    PRD: "Note that ceilings are enforced as refusals and never as silent trims:
    an over-ceiling claim is rejected, not quietly reduced."

    Design: Difficulty/boundary_precision_check/stacked_total_landing_exactly_on_the_pair_cap_is_accepted
    """
    state = _capped_pair_state()

    # The two deliveries differ by exactly 25 cents of sticker price, which is
    # the gap that moves the whole lease leg by one cent when half-up rounding is
    # applied once to the whole expression.
    a.assert_money(state["del_on"], "msrp_cents", 3750000)
    a.assert_money(state["del_over"], "msrp_cents", 3750025)

    response = _claim_lease_leg(state, state["del_over"]["id"], 250001)
    validate_error(response, ApiErrorId.ERR_STACK_CAP_EXCEEDED.value)

    rows, _meta = validate_paginated(
        api_client.list_claims(
            fx.ADJUDICATOR, {"delivery_id": state["del_over"]["id"]}
        )
    )
    a.assert_list_length(rows, 1, "claims on the over-cap delivery")
    assert rows[0]["program_id"] == state["prog_cash"]["id"], rows
