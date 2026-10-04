"""Distributor exit, territory repurchase valuation, financing payoff, and the
territory resale loop.

Covers PRD §3.8 (valuation variants, pinned settle order, payout
conservation, terminal lockdown, resale) and §3.1 (overlap rule limited to
non-terminal agreements). Instances:
Difficulty/dual_variant_calc/transfer_valuation_voluntary_vs_for_cause_variants,
Difficulty/combinatorial_formula/transfer_settle_pinned_evaluation_order,
Difficulty/compensating_invariant/transfer_settle_valuation_equals_payoff_plus_payout,
Corner/state_machines/settled_transfer_rejects_second_settle,
Corner/state_machines/territory_relisted_after_settle_sells_to_new_distributor.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_transfer_invariants,
    create_agreement_payload,
    create_bakery,
    create_distributor,
    create_draft_agreement,
    create_listed_territory,
    create_retail_account,
    exit_agreement,
    financing_payment_payload,
    find_financing_plan,
    get_agreement,
    get_agreement_transfer,
    get_distributor,
    get_territory,
    list_territory_for_sale,
    make_distributor_headers,
    post_passing_audit,
    reset_clock_to_default,
    set_clock,
    settle_transfer,
    setup_active_financed_agreement,
    setup_exiting_agreement,
    setup_settled_transfer,
    validate_error,
    validate_success,
    activate_agreement,
)

_ROUTE_OPS = TEST_USERS["route_ops_manager_headers"]
_CREDIT = TEST_USERS["credit_analyst_headers"]


def _setup_agreement_with_compliant_account(bakery, area_code, legal_name):
    """Cash agreement (purchase 1000000, activated at the 2026-09-01 clock)
    whose distributor holds one retail account carrying a single non-violation
    audit dated 2026-09-02."""
    territory = create_listed_territory(area_code=area_code)
    distributor = create_distributor(legal_name=legal_name)
    agreement = create_draft_agreement(
        territory["id"], distributor["id"], bakery["id"]
    )
    agreement = activate_agreement(agreement["id"])
    account = create_retail_account(distributor)
    post_passing_audit(account["id"], "2026-09-02")
    return territory, distributor, agreement


def test_transfer_valuation_voluntary_variant(api):
    """PRD §3.8: "Fourth, the variant branch: a `VOLUNTARY` exit credits
    goodwill of 50,000 cents per compliant account as `goodwill_cents` with
    `penalty_cents` zero..."
    PRD §3.8: "Fifth, the gross valuation is the purchase price minus
    depreciation, plus goodwill, minus penalty."
    PRD §3.8: "the system creates the territory transfer — its `agreement_id`
    pointing at the exiting agreement — in `PENDING` status, and computes its
    `gross_valuation_cents` using the variant keyed on `mode`, exposing the
    components in `valuation_detail`."

    Design: Difficulty/dual_variant_calc/transfer_valuation_voluntary_vs_for_cause_variants
    """
    reset_clock_to_default()
    bakery = create_bakery()
    _, _, agreement = _setup_agreement_with_compliant_account(
        bakery, "DAL-N", "RoutePro LLC"
    )
    set_clock("2026-09-08T10:00:00Z")
    exited = exit_agreement(agreement["id"], "VOLUNTARY")
    assert exited["status"] == "EXITING"
    transfer = get_agreement_transfer(agreement["id"])
    assert transfer["mode"] == "VOLUNTARY"
    assert transfer["status"] == "PENDING"
    assert transfer["gross_valuation_cents"] == 1050000, (
        "1000000 - 0 depreciation (7 days < 365) + 50000 goodwill (1 "
        "compliant account) - 0 penalty"
    )
    assert transfer["valuation_detail"] == {
        "depreciation_cents": 0,
        "goodwill_cents": 50000,
        "penalty_cents": 0,
    }


def test_transfer_valuation_for_cause_variant_diverges(api):
    """PRD §3.8: "a `FOR_CAUSE` exit — including one produced by a
    `RECLASSIFIED` resolution — zeroes goodwill and instead assesses a
    `penalty_cents` of 15% of the purchase price, rounded half-up to whole
    cents."
    PRD §3.8: "The same territory, dates, and accounts therefore yield
    different valuations under the two modes whenever any compliant account
    exists or the penalty is non-zero."

    Design: Difficulty/dual_variant_calc/transfer_valuation_voluntary_vs_for_cause_variants
    """
    reset_clock_to_default()
    bakery = create_bakery()
    _, _, agr_a = _setup_agreement_with_compliant_account(
        bakery, "DAL-N", "RoutePro LLC"
    )
    _, _, agr_b = _setup_agreement_with_compliant_account(
        bakery, "DAL-S", "MetroRoutes Inc"
    )
    set_clock("2026-09-08T10:00:00Z")
    exit_agreement(agr_a["id"], "VOLUNTARY")
    exit_agreement(agr_b["id"], "FOR_CAUSE")

    transfer_a = get_agreement_transfer(agr_a["id"])
    transfer_b = get_agreement_transfer(agr_b["id"])
    assert transfer_b["gross_valuation_cents"] == 850000, (
        "1000000 - 0 + 0 goodwill - 150000 penalty (15% of 1000000)"
    )
    assert transfer_b["valuation_detail"] == {
        "depreciation_cents": 0,
        "goodwill_cents": 0,
        "penalty_cents": 150000,
    }
    assert transfer_a["gross_valuation_cents"] != transfer_b[
        "gross_valuation_cents"
    ], "1050000 (VOLUNTARY) diverges from 850000 (FOR_CAUSE)"
    assert get_agreement(agr_a["id"])["status"] == "EXITING"
    assert get_agreement(agr_b["id"])["status"] == "EXITING"


def test_transfer_settle_computes_valuation_payoff_payout(api):
    """PRD §3.8: "When the agreement holds a plan in `ACTIVE` or `DELINQUENT`,
    interest accrues from the last accrual date — the `disburse_date` if no
    payment was ever made, otherwise the date of the most recent accepted
    payment — to the settlement date, as the outstanding principal multiplied
    by the `annual_interest_rate`, multiplied by the day count, and divided by
    365, rounded half-up to whole cents; `financing_payoff_cents` is the
    outstanding principal plus that accrued interest..."
    PRD §3.8: "The distributor's payout is then the gross valuation minus the
    payoff, recorded as `distributor_payout_cents`; the figure may be negative,
    representing a distributor deficiency owed back."

    Design: Difficulty/combinatorial_formula/transfer_settle_pinned_evaluation_order
    """
    ctx = setup_exiting_agreement(financed=True, mode="VOLUNTARY")
    settled = settle_transfer(ctx["transfer"]["id"])
    assert settled["status"] == "SETTLED"
    assert settled["gross_valuation_cents"] == 1000000, (
        "0 full years (activated 2026-09-01, exit 2026-09-08), 0 accounts"
    )
    assert settled["financing_payoff_cents"] == 52100, (
        "52000 + round_half_up(52000 * 0.10 * 7 / 365) = 52000 + 100"
    )
    assert settled["distributor_payout_cents"] == 947900


def test_transfer_settle_cascades_terminal_states(api):
    """PRD §3.8: "Settlement stamps `settled_on`, moves the transfer to
    `SETTLED`, moves the agreement `EXITING → EXITED`, and returns the
    territory `EXITING → AVAILABLE` with a `version` bump — ready to be listed
    and sold again, completing the cycle this model runs on. Finally, when the
    exiting distributor holds no other agreement in `DRAFT`, `ACTIVE`,
    `SUSPENDED_SERVICE`, `SUSPENDED_CLASSIFICATION`, or `EXITING`, the
    distributor itself moves to `EXITED`."
    PRD §3.8: "the plan itself moves to `SETTLED_ON_EXIT` with its
    `outstanding_principal_cents` booked into the payoff and then zeroed."

    Design: Difficulty/combinatorial_formula/transfer_settle_pinned_evaluation_order
    """
    ctx = setup_exiting_agreement(financed=True, mode="VOLUNTARY")
    settle_transfer(ctx["transfer"]["id"])
    plan = find_financing_plan(ctx["agreement"]["id"], ctx["plan"]["id"])
    assert plan["status"] == "SETTLED_ON_EXIT"
    assert plan["outstanding_principal_cents"] == 0
    assert get_agreement(ctx["agreement"]["id"])["status"] == "EXITED"
    assert get_territory(ctx["territory"]["id"])["status"] == "AVAILABLE"
    assert get_distributor(ctx["distributor"]["id"])["status"] == "EXITED"


def _setup_exit_after_one_payment():
    """Financed agreement ACTIVE (plan disbursed 2026-09-01); one payment of
    5255 on 2026-09-02 (interest 100, principal 5155 -> outstanding 46845);
    exit VOLUNTARY initiated at the 2026-09-09 clock. Returns ctx with the
    PENDING transfer."""
    ctx = setup_active_financed_agreement()
    set_clock("2026-09-02T09:00:00Z")
    resp = api_client.record_financing_payment(
        ctx["plan"]["id"],
        financing_payment_payload(5255),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    plan = validate_success(resp)
    assert plan["outstanding_principal_cents"] == 46845
    set_clock("2026-09-09T10:00:00Z")
    ctx["agreement"] = exit_agreement(ctx["agreement"]["id"], "VOLUNTARY")
    ctx["transfer"] = get_agreement_transfer(ctx["agreement"]["id"])
    assert ctx["transfer"] is not None
    return ctx


def test_settle_conserves_valuation_equals_payoff_plus_payout(api):
    """PRD §3.8: "The distributor's payout is then the gross valuation minus
    the payoff, recorded as `distributor_payout_cents`; the figure may be
    negative, representing a distributor deficiency owed back."
    PRD §3.8: "`financing_payoff_cents` is the outstanding principal plus that
    accrued interest, and the plan itself moves to `SETTLED_ON_EXIT` with its
    `outstanding_principal_cents` booked into the payoff and then zeroed."

    Design: Difficulty/compensating_invariant/transfer_settle_valuation_equals_payoff_plus_payout
    """
    ctx = _setup_exit_after_one_payment()
    settled = settle_transfer(ctx["transfer"]["id"])
    assert settled["gross_valuation_cents"] == 1000000
    assert settled["financing_payoff_cents"] == 46935, (
        "46845 + round_half_up(46845 * 0.10 * 7 / 365) = 46845 + 90 (accrual "
        "from the 2026-09-02 payment date to the 2026-09-09 settle date)"
    )
    assert settled["distributor_payout_cents"] == 953065
    assert (
        settled["financing_payoff_cents"] + settled["distributor_payout_cents"]
        == settled["gross_valuation_cents"]
    ), "valuation cents are conserved to the cent: 46935 + 953065 == 1000000"


def test_settled_transfer_invariants_and_plan_zeroed(api):
    """PRD §3.8: "the plan itself moves to `SETTLED_ON_EXIT` with its
    `outstanding_principal_cents` booked into the payoff and then zeroed."
    PRD §3.8: "The distributor's payout is then the gross valuation minus the
    payoff, recorded as `distributor_payout_cents`..."

    Design: Difficulty/compensating_invariant/transfer_settle_valuation_equals_payoff_plus_payout
    """
    ctx = _setup_exit_after_one_payment()
    settled = settle_transfer(ctx["transfer"]["id"])
    assert_transfer_invariants(settled)
    plan = find_financing_plan(ctx["agreement"]["id"], ctx["plan"]["id"])
    assert plan["status"] == "SETTLED_ON_EXIT"
    assert plan["outstanding_principal_cents"] == 0


def test_settled_transfer_rejects_second_settle(api):
    """PRD §3.8: "Settlement is the credit desk's final act, performed by a
    `CreditAnalyst` on a `PENDING` transfer — settling a transfer in any other
    state is rejected with `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/settled_transfer_rejects_second_settle
    """
    ctx = setup_settled_transfer(financed=True, mode="VOLUNTARY")
    transfer = ctx["transfer"]
    assert transfer["status"] == "SETTLED"
    resp = api_client.settle_transfer(transfer["id"], _CREDIT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    current = get_agreement_transfer(ctx["agreement"]["id"])
    assert current["status"] == "SETTLED"
    assert current["financing_payoff_cents"] == 52100, (
        "the rejected second settle recomputes nothing"
    )
    assert current["distributor_payout_cents"] == 947900


def test_territory_relisted_after_settle_sells_to_new_distributor(api):
    """PRD §3.8: "Settlement stamps `settled_on`, moves the transfer to
    `SETTLED`, moves the agreement `EXITING → EXITED`, and returns the
    territory `EXITING → AVAILABLE` with a `version` bump — ready to be listed
    and sold again, completing the cycle this model runs on."
    PRD §3.1: "One distributor may hold several agreements, but their coverage
    intervals may not overlap while any of them is non-terminal — that is, in
    `DRAFT`, `ACTIVE`, `SUSPENDED_SERVICE`, `SUSPENDED_CLASSIFICATION`, or
    `EXITING`."

    Design: Corner/state_machines/territory_relisted_after_settle_sells_to_new_distributor
    """
    ctx = setup_settled_transfer(financed=True, mode="VOLUNTARY")
    territory = ctx["territory"]
    assert territory["status"] == "AVAILABLE"

    new_distributor = create_distributor(
        legal_name="NewRoute Ventures", credit_limit_cents=150000
    )
    relisted = list_territory_for_sale(territory["id"])
    assert relisted["status"] == "LISTED"

    resp = api_client.create_agreement(
        create_agreement_payload(
            territory["id"],
            new_distributor["id"],
            ctx["bakery"]["id"],
            purchase_price_cents=1100000,
            discount_pct=0.18,
        ),
        _ROUTE_OPS,
    )
    agreement_n = validate_success(resp, 201)
    assert agreement_n["status"] == "DRAFT", (
        "the identical [2026-09-01, 2027-09-01) interval is reusable because "
        "the prior agreement is terminally EXITED"
    )
    assert agreement_n["start_date"] == "2026-09-01"
    assert agreement_n["end_date"] == "2027-09-01"
    assert get_territory(territory["id"])["status"] == "UNDER_AGREEMENT"
    assert get_distributor(new_distributor["id"])["status"] == "PROSPECT"
