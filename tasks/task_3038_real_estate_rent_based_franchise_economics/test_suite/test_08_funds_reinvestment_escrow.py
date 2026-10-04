"""Advertising funds, reinvestment obligations, and the cure escrow waterfall."""
import test_helpers as th


def test_fund_balance_admin_fee_withheld_per_credit(api, finance_headers, coop_headers):
    """PRD §3.9: "The fund's `balance_cents` rolls up as the sum of assessment
    credits minus the sum of disbursements minus the sum of administration
    fees, where the administration fee on each credit is the round-half-up of
    that credit times the `admin_fee_rate`, withheld per credit at posting time
    and rounded per credit."
    PRD §3.9: "A successful disbursement debits `balance_cents` by the amount."

    Design: Corner/calculations/fund_balance_admin_fee_withheld_per_credit
    """
    ctx = th.setup_open_store()
    fund = th.get_success_data(api.create_advertising_fund(
        th.create_advertising_fund_payload(name="Corner Coop", fund_type="LOCAL_COOP",
                                           admin_fee_rate=0.02, region_code="MW"),
        th.make_admin_headers(),
    ))
    assessment = th.get_success_data(api.create_coop_assessment(
        th.create_coop_assessment_payload(fund["id"], ctx["store"]["id"], amount_cents=500_000),
        coop_headers,
    ))
    th.validate_success(api.pay_coop_assessment(assessment["id"], finance_headers))

    resp = api.disburse_fund(fund["id"], {"amount_cents": 120_000, "purpose": "local media buy"}, coop_headers)
    th.validate_success(resp)

    updated = th.validate_success(api.get_advertising_fund(fund["id"], finance_headers))
    # 500,000 - round_half_up(500,000 * 0.02) admin fee - 120,000 disbursed
    assert updated["balance_cents"] == 370_000


def test_reinvestment_min_spend_is_seventy_percent(api, admin_headers):
    """PRD §3.6: "The system computes `min_spend_cents` as the round-half-up of
    `required_budget_cents` times 0.70 — seventy percent minimum coverage — and
    the obligation starts in `PENDING` with `verified_spend_cents` at zero."

    Design: Corner/calculations/reinvestment_min_spend_is_seventy_percent
    """
    site = th.create_site()
    operator = th.create_strong_approved_operator()
    store = th.create_store_for(operator, site)
    agreement = th.get_success_data(
        api.create_agreement(th.create_agreement_payload(store["id"], operator["id"]), admin_headers)
    )

    resp = api.create_reinvestment_obligation(
        th.create_reinvestment_obligation_payload(store["id"], agreement["id"],
                                                  required_budget_cents=2_000_000,
                                                  deadline_date="2027-12-31"),
        admin_headers,
    )
    obligation = th.validate_success(resp, expected_status=201)
    th.assert_reinvestment_obligation(obligation)
    assert obligation["min_spend_cents"] == 1_400_000
    assert obligation["status"] == "PENDING"
    assert obligation["verified_spend_cents"] == 0


def test_disburse_from_frozen_fund_rejected(api, admin_headers):
    """PRD §3.9: "Disbursement requires the fund's `governance_status` to be
    `ACTIVE`; a disbursement against a `FROZEN` fund is rejected with
    `ERR_FUND_FROZEN`."

    Design: Corner/errors/disburse_from_frozen_fund_rejected
    """
    fund = th.get_success_data(api.create_advertising_fund(
        th.create_advertising_fund_payload(name="National Fund", fund_type="NATIONAL", admin_fee_rate=0.0),
        admin_headers,
    ))
    th.validate_success(api.freeze_fund(fund["id"], admin_headers))

    resp = api.disburse_fund(fund["id"], {"amount_cents": 1_000, "purpose": "national campaign"}, admin_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_FUND_FROZEN, expected_status=409)


def test_disburse_over_balance_rejected(api, admin_headers, coop_headers):
    """PRD §3.9: "It also requires sufficient balance: an `amount_cents`
    exceeding the fund's `balance_cents` is rejected with
    `ERR_INSUFFICIENT_FUND_BALANCE` (HTTP 402)."

    Design: Corner/errors/disburse_over_balance_rejected
    """
    fund = th.get_success_data(api.create_advertising_fund(
        th.create_advertising_fund_payload(name="Empty Coop", fund_type="LOCAL_COOP",
                                           admin_fee_rate=0.0, region_code="NE"),
        admin_headers,
    ))
    assert fund["balance_cents"] == 0

    resp = api.disburse_fund(fund["id"], {"amount_cents": 5_000, "purpose": "overdraw attempt"}, coop_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_INSUFFICIENT_FUND_BALANCE, expected_status=402)


def test_cure_with_insufficient_escrow_rejected(api, finance_headers):
    """PRD §3.7: "If the operator's `escrow_balance_cents` is below the
    required amount, the cure is rejected with `ERR_INSUFFICIENT_CURE_FUNDS`
    (HTTP 402) and no state changes — a partial cure is never persisted."
    PRD §3.7: "The required amount is the event's `shortfall_cents` plus its
    `cure_fee_cents`."

    Design: Corner/errors/cure_with_insufficient_escrow_rejected
    """
    ctx = th.setup_defaulted_store(escrow_cents=1_000, cure_fee_cents=15_000)
    event_id = ctx["default_event"]["id"]

    resp = api.cure_default(event_id, finance_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_INSUFFICIENT_CURE_FUNDS, expected_status=402)

    operator = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    assert operator["escrow_balance_cents"] == 1_000
    event = th.validate_success(api.get_default_event(event_id, finance_headers))
    assert event["status"] == "DECLARED"


def test_reinvestment_underfunded_rejected(api, admin_headers, finance_headers):
    """PRD §3.6: "Verification succeeds only when the post-addition
    `verified_spend_cents` is at least `min_spend_cents` — the boundary is
    inclusive — moving the obligation `SUBMITTED → SATISFIED`; an underfunded
    verification is rejected with `ERR_REINVESTMENT_UNDERFUNDED`."

    Design: Corner/errors/reinvestment_underfunded_rejected
    """
    site = th.create_site()
    operator = th.create_strong_approved_operator()
    store = th.create_store_for(operator, site)
    agreement = th.get_success_data(
        api.create_agreement(th.create_agreement_payload(store["id"], operator["id"]), admin_headers)
    )
    obligation = th.get_success_data(api.create_reinvestment_obligation(
        th.create_reinvestment_obligation_payload(store["id"], agreement["id"],
                                                  required_budget_cents=2_000_000),
        admin_headers,
    ))
    th.get_success_data(api.submit_spend(
        obligation["id"], {"amount_cents": 1_399_999},
        th.make_operator_headers(operator["id"]),
    ))

    resp = api.verify_spend(obligation["id"], finance_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_REINVESTMENT_UNDERFUNDED, expected_status=409)
    after = th.validate_success(api.get_reinvestment_obligation(obligation["id"], finance_headers))
    assert after["status"] == "SUBMITTED"


def test_cure_waterfall_conserves_escrow_plus_covered_shortfall(api, finance_headers):
    """PRD §3.7: "The required amount is the event's `shortfall_cents` plus its
    `cure_fee_cents`. If the operator's `escrow_balance_cents` is below the
    required amount, the cure is rejected with `ERR_INSUFFICIENT_CURE_FUNDS`
    (HTTP 402) and no state changes — a partial cure is never persisted.
    Otherwise the escrow is debited by the full required amount, the shortfall
    is applied to the store's `OPEN` rent charges oldest first in `created_at`
    ascending order, marking each covered charge `PAID`, the event moves
    `DECLARED → CURED`, the sublease's `active_default_id` clears to null and
    the sublease moves `DEFAULTED → CURED`, and the store moves `SUSPENDED →
    OPEN` with the operator counters recomputed again."

    Design: Difficulty/compensating_invariant/cure_waterfall_conserves_escrow_plus_covered_shortfall
    """
    # Escrow must cover the full required amount (2,448,000 + 15,000), per the
    # PRD's all-or-nothing cure gate.
    ctx = th.setup_defaulted_store(escrow_cents=3_000_000, cure_fee_cents=15_000)
    event_id = ctx["default_event"]["id"]
    charge_id = ctx["charges"][0]["id"]

    operator_before = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    event = th.validate_success(api.get_default_event(event_id, finance_headers))
    shortfall = event["shortfall_cents"]
    fee = event["cure_fee_cents"]
    assert shortfall == 2_448_000 and fee == 15_000

    th.validate_success(api.cure_default(event_id, finance_headers))

    operator_after = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    # Zero drift: escrow_before - escrow_after == shortfall + fee exactly.
    assert operator_before["escrow_balance_cents"] - operator_after["escrow_balance_cents"] == shortfall + fee
    assert operator_after["escrow_balance_cents"] == 3_000_000 - 2_448_000 - 15_000

    charge = th.validate_success(api.get_rent_charge(charge_id, finance_headers))
    assert charge["status"] == "PAID"
    assert charge["amount_paid_cents"] == 2_448_000
    assert operator_after["delinquency_balance_cents"] == 0

    cured = th.validate_success(api.get_default_event(event_id, finance_headers))
    assert cured["status"] == "CURED"


def test_cure_waterfall_oldest_first_across_multiple_charges(api, finance_headers):
    """PRD §3.7: "Otherwise the escrow is debited by the full required amount,
    the shortfall is applied to the store's `OPEN` rent charges oldest first in
    `created_at` ascending order, marking each covered charge `PAID`, the event
    moves `DECLARED → CURED`, the sublease's `active_default_id` clears to null
    and the sublease moves `DEFAULTED → CURED`, and the store moves `SUSPENDED
    → OPEN` with the operator counters recomputed again."
    PRD §3.7: "The required amount is the event's `shortfall_cents` plus its
    `cure_fee_cents`."

    Design: Difficulty/compensating_invariant/cure_waterfall_conserves_escrow_plus_covered_shortfall
    """
    ctx = th.setup_defaulted_store(
        escrow_cents=10_000_000,
        cure_fee_cents=0,
        charge_amounts=[("2026", "2026-04-01", "2027-03-31"),
                        ("2027", "2027-04-01", "2028-03-31")],
    )
    event_id = ctx["default_event"]["id"]
    charge_ids = [c["id"] for c in ctx["charges"]]

    event = th.validate_success(api.get_default_event(event_id, finance_headers))
    assert event["shortfall_cents"] == 2_448_000 + 2_448_000

    th.validate_success(api.cure_default(event_id, finance_headers))

    # Both charges covered in full, oldest first.
    for cid in charge_ids:
        charge = th.validate_success(api.get_rent_charge(cid, finance_headers))
        assert charge["status"] == "PAID"
        assert charge["amount_paid_cents"] == 2_448_000

    operator = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    assert operator["escrow_balance_cents"] == 10_000_000 - 4_896_000
    assert operator["delinquency_balance_cents"] == 0
    store = th.validate_success(api.get_store(ctx["store"]["id"], finance_headers))
    assert store["status"] == "OPEN"
