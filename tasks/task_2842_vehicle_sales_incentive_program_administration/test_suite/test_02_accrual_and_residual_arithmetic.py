"""Nested-rounding and pinned-evaluation-order arithmetic.

Two of this service's formulas are order-sensitive in a way that a naive
implementation gets wrong by a small, deterministic margin. The monthly accrual
rounds every eligibility line separately before summing, so summing first and
rounding once is off by a cent. The lease-support residual impact reads raw MSRP
in a single forward pass, so resolving the apparent capitalized-cost circularity
by subtracting the stacked customer cash lands on a different basis-point figure.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import api_client
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, AUG_31, BUILD_FROM, BUILD_TO, SEP_01

AUG_07 = "2026-08-07T00:00:00.000Z"
AUG_10 = "2026-08-10T00:00:00.000Z"
AUG_11 = "2026-08-11T00:00:00.000Z"
AUG_12 = "2026-08-12T00:00:00.000Z"

RULE_MX5 = {
    "model_code": "MX5",
    "region_code": "WEST",
    "build_date_from": BUILD_FROM,
    "build_date_to": BUILD_TO,
    "allowed_deal_types": ["CASH"],
}

RULE_TRK9 = {
    "model_code": "TRK9",
    "region_code": "WEST",
    "build_date_from": BUILD_FROM,
    "build_date_to": BUILD_TO,
    "allowed_deal_types": ["CASH"],
}


def _two_line_accrual_chain():
    """One ACTIVE UNIT_BASED CUSTOMER_CASH program at 200600 cents per unit with
    exactly two eligibility footprint rows — MX5 then TRK9 — and four VALIDATED
    August deliveries, one MX5 attributed to the first row and three TRK9
    attributed to the second, with no accrual yet run for 2026-08."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Summit Vehicle Group",
        region_code="WEST",
        historical_volume_units=10,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            name="August Customer Cash Accrual Test",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=200600,
            budget_cents=100000000,
            stack_group="AUG-CASH",
            priority_rank=10,
            accrual_method="UNIT_BASED",
        ),
        rules=[RULE_MX5, RULE_TRK9],
    )
    # The latest sale instant is 2026-08-12, so the clock moves there first and
    # every report carries a reporting lag of at most two clean days.
    fx.set_clock(AUG_12)
    specs = [
        ("MX5", 3200000, "2026-06-01T00:00:00.000Z", AUG_10),
        ("TRK9", 4100000, "2026-06-02T00:00:00.000Z", AUG_10),
        ("TRK9", 4100000, "2026-06-03T00:00:00.000Z", AUG_11),
        ("TRK9", 4100000, "2026-06-04T00:00:00.000Z", AUG_12),
    ]
    deliveries = []
    for model_code, msrp_cents, build_date, sale_date in specs:
        delivery = fx.report_delivery(
            dealer["id"],
            model_code=model_code,
            trim_code="BASE",
            build_date=build_date,
            msrp_cents=msrp_cents,
            sale_date=sale_date,
            customer_region_code="WEST",
            deal_type="CASH",
        )
        fx.validate_delivery(delivery["id"])
        deliveries.append(delivery)
    fx.set_clock(AUG_31)
    return {"dealer": dealer, "program": program, "deliveries": deliveries}


def _run_accrual(program_id, period_month="2026-08"):
    return validate_success(
        api_client.run_accrual(
            program_id, f.run_accrual_payload(period_month), fx.CONTROLLER
        ),
        201,
    )


def test_accrual_rounds_each_eligibility_line_before_summing_them():
    """The one-unit MX5 line is exactly 195083.5 cents and the three-unit TRK9
    line exactly 585250.5; rounding each half-up before summing yields 780335.

    PRD §3.9: "In both variants **half-up rounding is applied to each line
    separately, and only then are the rounded line amounts summed**; summing
    unrounded line values and rounding once at the end is a different and
    incorrect answer that may differ by one or more cents."

    Design: Difficulty/combinatorial_formula/accrual_rounds_each_eligibility_line_before_summing
    """
    chain = _two_line_accrual_chain()

    accrual = _run_accrual(chain["program"]["id"])

    a.assert_accrual_shape(accrual)
    a.assert_money(accrual, "accrued_cents", 780335)
    assert accrual["accrued_cents"] != 780334, (
        "rounding each of the two lines half-up before summing gives 780335; "
        "780334 is the sum-then-round order, wrong by exactly one cent"
    )


def test_accrual_row_carries_the_summed_unit_basis_and_no_reversal():
    """The accrual row's own dimensions pin the line attribution: four units across
    the two footprint rows, entry_type ACCRUAL, the program's method copied on,
    and a zero reversal.

    PRD §3.9: "The row's `accrued_cents` is the sum of the rounded line amounts,
    its `unit_basis` is the sum of the line unit counts, and its `reversal_cents`
    is 0 — an accrual row never carries a reversal, just as a reversal row always
    carries an `accrued_cents` of 0."

    Design: Difficulty/combinatorial_formula/accrual_rounds_each_eligibility_line_before_summing
    """
    chain = _two_line_accrual_chain()

    accrual = _run_accrual(chain["program"]["id"])

    a.assert_int_field(accrual, "unit_basis", 4)
    assert accrual["entry_type"] == "ACCRUAL", (
        f"expected entry_type ACCRUAL, got {accrual['entry_type']!r}"
    )
    assert accrual["accrual_method"] == "UNIT_BASED", (
        f"expected the program's accrual_method UNIT_BASED copied onto the row, "
        f"got {accrual['accrual_method']!r}"
    )
    a.assert_money(accrual, "reversal_cents", 0)
    assert accrual["period_month"] == "2026-08", accrual["period_month"]
    a.assert_null_fields(accrual, ["source_reference"])


def test_program_accrued_budget_and_ledger_listing_follow_the_accrual():
    """The program's accrued budget is the single ledger row's accrued amount net of
    no reversal, and the ledger holds exactly that one row.

    PRD §3.9: "A program's `accrued_budget_cents` is the sum of `accrued_cents`
    over all of its accrual-ledger rows minus the sum of `reversal_cents` over all
    of those rows, across both entry types and all periods, computed exactly with
    no rounding."

    Design: Difficulty/combinatorial_formula/accrual_rounds_each_eligibility_line_before_summing
    """
    chain = _two_line_accrual_chain()

    _run_accrual(chain["program"]["id"])

    program = fx.read_program(chain["program"]["id"])
    a.assert_money(program, "accrued_budget_cents", 780335)

    rows, meta = validate_paginated(
        api_client.list_accruals(chain["program"]["id"], fx.CONTROLLER)
    )
    a.assert_list_length(rows, 1, "accrual ledger rows")
    assert meta["total_count"] == 1, (
        f"expected total_count 1 accrual ledger row, got {meta['total_count']}"
    )
    a.assert_money(rows[0], "accrued_cents", 780335)


RULE_LX7_LEASE = {
    "model_code": "LX7",
    "region_code": "WEST",
    "build_date_from": BUILD_FROM,
    "build_date_to": BUILD_TO,
    "allowed_deal_types": ["LEASE"],
}


def _stacked_lease_and_cash_chain():
    """One ACTIVE LEASE_SUPPORT program (100000 per unit, 400 bps of residual
    support) and one ACTIVE CUSTOMER_CASH program (150000 per unit) sharing the
    LX7/WEST/LEASE footprint with no edge between them, two VALIDATED LEASE
    deliveries of MSRP 5000000 and 4000000, and one SUBMITTED claim per program
    per delivery with both cash claims already approved."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Lakeside Leasing Motors",
        region_code="WEST",
        historical_volume_units=6,
        market_opportunity_bps=0,
    )
    lease = fx.create_active_program(
        payload=f.create_program_payload(
            name="August Lease Support",
            incentive_type="LEASE_SUPPORT",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=100000,
            budget_cents=100000000,
            stack_group="AUG-LEASE",
            priority_rank=30,
            residual_support_bps=400,
        ),
        rules=[RULE_LX7_LEASE],
    )
    cash = fx.create_active_program(
        payload=f.create_program_payload(
            name="August Customer Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=150000,
            budget_cents=100000000,
            stack_group="AUG-CASH",
            priority_rank=10,
        ),
        rules=[RULE_LX7_LEASE],
    )
    fx.set_clock(AUG_07)
    deliveries = []
    for msrp_cents, build_date in ((5000000, "2026-06-10T00:00:00.000Z"),
                                   (4000000, "2026-06-11T00:00:00.000Z")):
        delivery = fx.report_delivery(
            dealer["id"],
            model_code="LX7",
            trim_code="PREMIUM",
            build_date=build_date,
            msrp_cents=msrp_cents,
            sale_date=AUG_07,
            customer_region_code="WEST",
            deal_type="LEASE",
            term_months=36,
            base_residual_bps=5500,
        )
        fx.validate_delivery(delivery["id"])
        deliveries.append(delivery)
    cash_claims = [
        fx.submit_claim(dealer["id"], delivery["id"], cash["id"], 150000)
        for delivery in deliveries
    ]
    lease_claims = [
        fx.submit_claim(dealer["id"], deliveries[0]["id"], lease["id"], 300000),
        fx.submit_claim(dealer["id"], deliveries[1]["id"], lease["id"], 260000),
    ]
    approved_cash = [
        fx.adjudicate_claim(claim["id"], "APPROVE") for claim in cash_claims
    ]
    return {
        "dealer": dealer,
        "lease": lease,
        "cash": cash,
        "deliveries": deliveries,
        "cash_claims": cash_claims,
        "lease_claims": lease_claims,
        "approved_cash": approved_cash,
    }


def _approve(claim_id):
    return validate_success(
        api_client.adjudicate_claim(
            claim_id, f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        )
    )


def _read_spend_summary(program_id):
    return validate_success(
        api_client.get_spend_summary(program_id, fx.DESIGNER)
    )


def test_lease_support_leg_adds_the_supported_residual_to_the_rate():
    """Each lease claim pays the 100000 per-unit rate plus 400 bps of the
    delivery's own MSRP, while the stacked customer-cash claim on the same
    delivery pays its rate alone.

    PRD §3.7: "For `LEASE_SUPPORT` the leg is the delivery's `msrp_cents`
    multiplied by the program's `residual_support_bps`, divided by 10000, again
    with half-up rounding applied once to the whole expression."

    Design: Difficulty/combinatorial_formula/residual_impact_breaks_the_capitalized_cost_circularity
    """
    chain = _stacked_lease_and_cash_chain()

    a.assert_money(chain["approved_cash"][0], "approved_amount_cents", 150000)

    first = _approve(chain["lease_claims"][0]["id"])
    second = _approve(chain["lease_claims"][1]["id"])

    a.assert_money(first, "approved_amount_cents", 300000)
    a.assert_money(second, "approved_amount_cents", 260000)


def test_residual_impact_reads_raw_msrp_rather_than_msrp_minus_stacked_cash():
    """The five-step pass averages the raw MSRPs to 4500000, floors the support
    ratio to 622 bps and floors the pass-through to 373 bps.

    PRD §3.9: "Step three computes the average capitalized cost as the sum of the
    raw `msrp_cents` of those claims' deliveries divided by the supported unit
    count, floored."

    Design: Difficulty/combinatorial_formula/residual_impact_breaks_the_capitalized_cost_circularity
    """
    chain = _stacked_lease_and_cash_chain()

    _approve(chain["lease_claims"][0]["id"])
    _approve(chain["lease_claims"][1]["id"])

    summary = _read_spend_summary(chain["lease"]["id"])
    a.assert_bps(summary, "residual_impact_bps", 373)
    assert summary["residual_impact_bps"] != 385, (
        "raw MSRP averages to 4500000 and yields 373 bps; 385 bps is the "
        "circular reading that first subtracts the stacked customer cash"
    )
    program = fx.read_program(chain["lease"]["id"])
    a.assert_bps(program, "residual_impact_bps", 373)


def test_lease_spend_monitor_floors_the_per_unit_spend_over_both_claims():
    """The two approved lease claims commit 560000 across two claimed units, so the
    per-unit spend monitor floors to 280000.

    PRD §3.7: "`per_unit_spend_cents` is that spend divided by `claimed_units` and
    floored; when `claimed_units` is 0 the result is exactly 0 rather than null and
    never a division error."

    Design: Difficulty/combinatorial_formula/residual_impact_breaks_the_capitalized_cost_circularity
    """
    chain = _stacked_lease_and_cash_chain()

    _approve(chain["lease_claims"][0]["id"])
    _approve(chain["lease_claims"][1]["id"])

    summary = _read_spend_summary(chain["lease"]["id"])
    a.assert_spend_summary(
        summary,
        program_id=chain["lease"]["id"],
        claimed_units=2,
        committed_cents=560000,
        paid_cents=0,
        accrued_budget_cents=0,
        per_unit_spend_cents=280000,
        residual_impact_bps=373,
        budget_remaining_cents=99440000,
    )


def test_residual_impact_stays_zero_for_the_stacked_customer_cash_program():
    """The customer-cash program carries the same two deliveries but is not a
    lease-support program, so its residual impact never leaves 0.

    PRD §3.9: "A program's `residual_impact_bps` is 0 for every program whose
    `incentive_type` is not `LEASE_SUPPORT`, and for lease-support programs it is
    recomputed when a claim is approved and when a delivery is unwound, in exactly
    five steps whose order is pinned and none of which may consult the output of a
    later step."

    Design: Difficulty/combinatorial_formula/residual_impact_breaks_the_capitalized_cost_circularity
    """
    chain = _stacked_lease_and_cash_chain()

    _approve(chain["lease_claims"][0]["id"])
    _approve(chain["lease_claims"][1]["id"])

    summary = _read_spend_summary(chain["cash"]["id"])
    a.assert_bps(summary, "residual_impact_bps", 0)
    a.assert_int_field(summary, "claimed_units", 2)
    a.assert_money(summary, "committed_cents", 300000)
