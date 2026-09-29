"""Validation-precedence: which error the screening ladder returns when two
independent failure conditions are live on one and the same request.

Each scenario is built twice: once with both conditions violated together, so
the higher-priority error identifier must be the one returned, and once as a
twin control in which only the lower-priority condition is violated, proving
that condition was genuinely live rather than absent.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
)

from test_helpers import ApiErrorId, api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, AUG_16, BUILD_FROM, BUILD_TO, SEP_01

TRUCK_RULE = {
    "model_code": "TRK9",
    "region_code": "WEST",
    "build_date_from": BUILD_FROM,
    "build_date_to": BUILD_TO,
    "allowed_deal_types": ["FINANCE"],
}


# --- Setup: a CLOSED program and its still-ACTIVE twin -----------------------


def _closed_vs_active_pair() -> dict:
    """Two CUSTOMER_CASH programs over identical windows, per_unit 150000 cents
    against a deliberately undersized budget of 100000 cents, separated only by
    their eligibility footprint (MX5 versus TRK9) so neither collides with the
    other at the approval gate. Each carries one SUBMITTED, UNPAID claim; the
    first program is then CLOSED."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="D-810",
        name="Coldbrook Auto Group",
        region_code="WEST",
        historical_volume_units=6,
        market_opportunity_bps=0,
    )

    prog_a = fx.create_draft_program(
        f.create_program_payload(
            program_code="PPC-A",
            name="Priority Pair Cash A",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=150000,
            budget_cents=100000,
            stack_group="PPC",
            priority_rank=61,
            accrual_method="UNIT_BASED",
        )
    )
    fx.add_eligibility_rule(
        prog_a["id"],
        model_code="MX5",
        region_code="WEST",
        build_date_from=BUILD_FROM,
        build_date_to=BUILD_TO,
        allowed_deal_types=["CASH"],
    )
    fx.submit_program(prog_a["id"])
    fx.approve_program(prog_a["id"])

    prog_b = fx.create_draft_program(
        f.create_program_payload(
            program_code="PPC-B",
            name="Priority Pair Cash B",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=150000,
            budget_cents=100000,
            stack_group="PPC",
            priority_rank=62,
            accrual_method="UNIT_BASED",
        )
    )
    fx.add_eligibility_rule(
        prog_b["id"],
        model_code="TRK9",
        region_code="WEST",
        build_date_from=BUILD_FROM,
        build_date_to=BUILD_TO,
        allowed_deal_types=["CASH"],
    )
    fx.submit_program(prog_b["id"])
    fx.approve_program(prog_b["id"])

    fx.set_clock("2026-08-06T00:00:00.000Z")
    del_a = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-06-10T00:00:00.000Z",
        msrp_cents=3200000,
        sale_date="2026-08-06T00:00:00.000Z",
        customer_region_code="WEST",
        deal_type="CASH",
    )
    del_b = fx.report_delivery(
        dealer["id"],
        model_code="TRK9",
        trim_code="BASE",
        build_date="2026-06-11T00:00:00.000Z",
        msrp_cents=5400000,
        sale_date="2026-08-06T00:00:00.000Z",
        customer_region_code="WEST",
        deal_type="CASH",
    )
    fx.validate_delivery(del_a["id"])
    fx.validate_delivery(del_b["id"])

    claim_a = fx.submit_claim(dealer["id"], del_a["id"], prog_a["id"], 150000)
    claim_b = fx.submit_claim(dealer["id"], del_b["id"], prog_b["id"], 150000)

    # Closure is admitted because no claim of PPC-A is SCHEDULED, and it leaves
    # claim A in SUBMITTED, so the claim still reaches the adjudication chain.
    closed = fx.close_program(prog_a["id"])

    return {
        "dealer": dealer,
        "prog_a": prog_a,
        "prog_b": prog_b,
        "del_a": del_a,
        "del_b": del_b,
        "claim_a": claim_a,
        "claim_b": claim_b,
        "closed": closed,
    }


def test_closed_program_state_outranks_the_same_claims_budget_exhaustion():
    """Adjudicating a claim of a CLOSED program whose budget would also be
    breached reports the program-state error, not the fiscal one.

    PRD: "And because budget headroom (rung 31) is the last rung of all, a claim
    that would exhaust the program's funding is only reported as such after every
    structural, ownership and eligibility question has been answered."

    Design: Difficulty/priority_pair_validation_conflict/closed_program_state_error_outranks_live_budget_exhaustion
    """
    state = _closed_vs_active_pair()

    program = fx.read_program(state["prog_a"]["id"])
    a.assert_status(program, "CLOSED")
    # Closing a program does not reject its submitted claims.
    claim_before = fx.read_claim(state["claim_a"]["id"])
    a.assert_claim_dimensions(claim_before, "SUBMITTED", "UNPAID")
    # The fiscal condition is live as well: committed 0 plus an approval of
    # 150000 cents rises above the funded budget of 100000 cents.
    a.assert_money(program, "budget_cents", 100000)
    a.assert_money(program, "committed_cents", 0)
    a.assert_money(program, "per_unit_amount_cents", 150000)

    response = api_client.adjudicate_claim(
        state["claim_a"]["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value)


def test_closed_program_refusal_leaves_the_claim_and_the_ledger_untouched():
    """The refused adjudication of the CLOSED program's claim is a total no-op.

    PRD: "Checks are evaluated in the following order, and the first failure
    short-circuits the request; no side effect of any kind is applied to any
    entity once a check fails."

    Design: Difficulty/priority_pair_validation_conflict/closed_program_state_error_outranks_live_budget_exhaustion
    """
    state = _closed_vs_active_pair()

    response = api_client.adjudicate_claim(
        state["claim_a"]["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value)

    claim_after = fx.read_claim(state["claim_a"]["id"])
    a.assert_claim_dimensions(claim_after, "SUBMITTED", "UNPAID")
    a.assert_version(claim_after, 1)
    a.assert_null_fields(
        claim_after, ["adjudicated_by_user_id", "rejection_error_id"]
    )

    summary = fx.read_spend_summary(state["prog_a"]["id"])
    a.assert_spend_summary(
        summary,
        state["prog_a"]["id"],
        claimed_units=0,
        committed_cents=0,
        paid_cents=0,
        accrued_budget_cents=0,
        per_unit_spend_cents=0,
        residual_impact_bps=0,
        budget_remaining_cents=100000,
    )


def test_budget_exhaustion_fires_alone_on_the_twin_whose_program_is_active():
    """The twin claim, identical except that its program is still ACTIVE, draws
    the fiscal error — so the fiscal condition was live on both claims and merely
    outranked on the closed one.

    PRD: "If the program's `committed_cents` plus this claim's newly computed
    `approved_amount_cents` would rise above the program's `budget_cents`, the
    approval is refused with `ERR_PROGRAM_BUDGET_EXHAUSTED` (HTTP 402) and
    nothing is written."

    Design: Difficulty/priority_pair_validation_conflict/closed_program_state_error_outranks_live_budget_exhaustion
    """
    state = _closed_vs_active_pair()

    program_a = fx.read_program(state["prog_a"]["id"])
    program_b = fx.read_program(state["prog_b"]["id"])
    a.assert_status(program_b, "ACTIVE")
    # The two programs carry the identical money levers, which is what makes
    # claim B a faithful twin of claim A on the fiscal dimension.
    a.assert_money(program_b, "budget_cents", program_a["budget_cents"])
    a.assert_money(
        program_b, "per_unit_amount_cents", program_a["per_unit_amount_cents"]
    )
    a.assert_money(program_b, "committed_cents", 0)

    response = api_client.adjudicate_claim(
        state["claim_b"]["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_BUDGET_EXHAUSTED.value)

    claim_after = fx.read_claim(state["claim_b"]["id"])
    a.assert_claim_dimensions(claim_after, "SUBMITTED", "UNPAID")
    summary = fx.read_spend_summary(state["prog_b"]["id"])
    a.assert_spend_summary(
        summary,
        state["prog_b"]["id"],
        claimed_units=0,
        committed_cents=0,
        paid_cents=0,
        accrued_budget_cents=0,
        per_unit_spend_cents=0,
        residual_impact_bps=0,
        budget_remaining_cents=100000,
    )


# --- Setup: a short-window program joined by a FORBIDDEN edge ----------------


def _window_vs_forbidden_edge() -> dict:
    """Two ACTIVE programs of different incentive types over the same TRK9/WEST/
    FINANCE footprint, joined by a FORBIDDEN stacking edge. PWS-2's window is
    deliberately short, ending 2026-08-16. Two FINANCE deliveries — one sold
    inside both windows, one sold after PWS-2's window has closed — each already
    carry an accepted claim on PWS-1, so the FORBIDDEN edge is live on both."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="D-820",
        name="Fairmount Truck Center",
        region_code="WEST",
        historical_volume_units=11,
        market_opportunity_bps=0,
    )

    prog_1 = fx.create_draft_program(
        f.create_program_payload(
            program_code="PWS-1",
            name="Window Stack Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=120000,
            budget_cents=90000000,
            stack_group="PWS",
            priority_rank=71,
            accrual_method="UNIT_BASED",
        )
    )
    fx.add_eligibility_rule(prog_1["id"], **TRUCK_RULE)

    prog_2 = fx.create_draft_program(
        f.create_program_payload(
            program_code="PWS-2",
            name="Window Stack Subvention",
            incentive_type="FINANCE_SUBVENTION",
            effective_from=AUG_01,
            effective_to=AUG_16,
            per_unit_amount_cents=0,
            apr_buydown_bps=300,
            budget_cents=90000000,
            stack_group="PWS",
            priority_rank=72,
            accrual_method="UNIT_BASED",
        )
    )
    fx.add_eligibility_rule(prog_2["id"], **TRUCK_RULE)

    edge = fx.add_stack_edge(prog_1["id"], prog_2["id"], mode="FORBIDDEN")

    fx.submit_program(prog_1["id"])
    fx.approve_program(prog_1["id"])
    fx.submit_program(prog_2["id"])
    fx.approve_program(prog_2["id"])

    fx.set_clock("2026-08-12T00:00:00.000Z")
    del_early = fx.report_finance_delivery(
        dealer["id"],
        model_code="TRK9",
        trim_code="XLT",
        build_date="2026-06-20T00:00:00.000Z",
        msrp_cents=5600000,
        sale_date="2026-08-10T00:00:00.000Z",
        customer_region_code="WEST",
        term_months=60,
        contract_apr_bps=199,
    )
    fx.set_clock("2026-08-21T00:00:00.000Z")
    del_late = fx.report_finance_delivery(
        dealer["id"],
        model_code="TRK9",
        trim_code="XLT",
        build_date="2026-06-21T00:00:00.000Z",
        msrp_cents=5600000,
        sale_date="2026-08-20T00:00:00.000Z",
        customer_region_code="WEST",
        term_months=60,
        contract_apr_bps=199,
    )

    claim_early_1 = fx.submit_claim(
        dealer["id"], del_early["id"], prog_1["id"], 120000
    )
    claim_late_1 = fx.submit_claim(dealer["id"], del_late["id"], prog_1["id"], 120000)

    return {
        "dealer": dealer,
        "prog_1": prog_1,
        "prog_2": prog_2,
        "edge": edge,
        "del_early": del_early,
        "del_late": del_late,
        "claim_early_1": claim_early_1,
        "claim_late_1": claim_late_1,
    }


def _claim_pws2(state: dict, delivery_id: str):
    """Submit the PWS-2 claim for one delivery with a freshly read version guard."""
    return api_client.create_claim(
        f.create_claim_payload(
            delivery_id,
            state["prog_2"]["id"],
            168000,
            fx.program_version(state["prog_2"]["id"]),
        ),
        make_dealer_headers(state["dealer"]["id"]),
    )


def test_sale_date_window_error_outranks_the_forbidden_stack_edge():
    """A sale outside the program's half-open window draws the window error even
    though a FORBIDDEN edge and an empty candidate set are violated too, and all
    three candidate errors carry HTTP 422.

    PRD: "Only then do the three stacking questions get asked, in the order
    eligibility, then forbidden pairing, then cap headroom."

    Design: Difficulty/priority_pair_validation_conflict/sale_date_window_error_outranks_forbidden_stack_edge
    """
    state = _window_vs_forbidden_edge()

    assert state["edge"]["mode"] == "FORBIDDEN", state["edge"]
    # Both PWS-1 claims stand, so the FORBIDDEN edge is live on both deliveries.
    a.assert_claim_dimensions(
        fx.read_claim(state["claim_early_1"]["id"]), "SUBMITTED", "UNPAID"
    )
    a.assert_claim_dimensions(
        fx.read_claim(state["claim_late_1"]["id"]), "SUBMITTED", "UNPAID"
    )

    response = _claim_pws2(state, state["del_late"]["id"])
    validate_error(
        response, ApiErrorId.ERR_SALE_DATE_OUTSIDE_PROGRAM_WINDOW.value
    )

    # On 2026-08-20 the half-open window ending 2026-08-16 excludes the sale, so
    # PWS-2 is not even a candidate for this delivery — which is precisely why
    # the eligibility and stacking rungs had something to fire on as well.
    program_2 = fx.read_program(state["prog_2"]["id"])
    assert program_2["effective_to"] == AUG_16, program_2
    assert state["del_late"]["sale_date"] == "2026-08-20T00:00:00.000Z"
    projection = fx.read_eligible_programs(state["del_late"]["id"])
    assert state["prog_2"]["id"] not in projection["eligible_program_ids"], projection


def test_forbidden_stack_edge_fires_alone_on_the_control_sold_inside_both_windows():
    """The control delivery, sold inside both windows, draws the forbidden-pair
    error from the identical edge row — so priority 22 was violated and merely
    outranked on the late delivery.

    PRD: "Then, for every program in the accepted set, the stacking edge joining
    the unordered pair — of which at most one exists — is consulted: if such an
    edge exists and its `mode` is `FORBIDDEN`, the candidate is **blocked** and
    the walk moves on to the next candidate, and a claim requesting a blocked
    program is refused with `ERR_STACK_COMBINATION_FORBIDDEN`."

    Design: Difficulty/priority_pair_validation_conflict/sale_date_window_error_outranks_forbidden_stack_edge
    """
    state = _window_vs_forbidden_edge()

    # The control's sale instant sits inside PWS-2's window, so the window rung
    # cannot fire and the stacking rung is reached.
    assert state["del_early"]["sale_date"] == "2026-08-10T00:00:00.000Z"
    projection = fx.read_eligible_programs(state["del_early"]["id"])
    assert state["prog_2"]["id"] in projection["blocked_program_ids"], projection

    response = _claim_pws2(state, state["del_early"]["id"])
    validate_error(response, ApiErrorId.ERR_STACK_COMBINATION_FORBIDDEN.value)


def test_neither_refused_pws2_submission_persists_a_claim_row():
    """Both refusals leave no Claim row on PWS-2 at all, in either state
    dimension.

    PRD: "Checks are evaluated in the following order, and the first failure
    short-circuits the request; no side effect of any kind is applied to any
    entity once a check fails."

    Design: Difficulty/priority_pair_validation_conflict/sale_date_window_error_outranks_forbidden_stack_edge
    """
    state = _window_vs_forbidden_edge()

    validate_error(
        _claim_pws2(state, state["del_late"]["id"]),
        ApiErrorId.ERR_SALE_DATE_OUTSIDE_PROGRAM_WINDOW.value,
    )
    validate_error(
        _claim_pws2(state, state["del_early"]["id"]),
        ApiErrorId.ERR_STACK_COMBINATION_FORBIDDEN.value,
    )

    rows, _meta = validate_paginated(
        api_client.list_claims(fx.ADJUDICATOR, {"program_id": state["prog_2"]["id"]})
    )
    a.assert_list_length(rows, 0, "claims on PWS-2")
