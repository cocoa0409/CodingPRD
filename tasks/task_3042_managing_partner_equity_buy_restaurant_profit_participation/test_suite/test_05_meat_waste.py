"""Meat cutting tests: per-batch rounding, audit gates, mismatch rules,
duplicate cut codes, and the waive compensation invariant."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_active_restaurant,
    create_open_period,
    create_yield_standard,
    create_meat_cut_batch,
    audit_batch,
    post_line_item,
    compute_period,
    finalize_period,
    setup_active_contract,
    set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CONTROLLER = TEST_USERS["corporate_controller_headers"]
AUDITOR = TEST_USERS["operations_auditor_headers"]


def test_waste_charge_per_batch_rounding_beats_sum_then_round(api):
    """PRD §2.6: "Rounding is applied only at three pinned points, always
    using the round-half-up method: ... (c) each meat batch's waste charge is
    rounded per batch to integer cents, never across a consolidated set of
    batches."
    PRD §3.7: "When the excess is greater than zero, the batch becomes
    VARIANCE_CONFIRMED and its waste_charge_cents is the excess waste in
    pounds multiplied by the standard's standard_cost_per_lb_cents, rounded
    half-up to integer cents for this batch alone — per-batch rounding,
    pinned, never consolidated before rounding."

    Design: Difficulty/combinatorial_formula/waste_charge_per_batch_rounding_beats_sum_then_round
    """
    setup = setup_active_contract()
    create_yield_standard(
        cut_code="RIB_1",
        expected_yield_pct=70,
        waste_tolerance_pct=0,
        standard_cost_per_lb_cents=300,
    )
    period = create_open_period(setup["restaurant"]["id"], "2027-06-01", "2027-07-01")
    set_clock("2027-06-10T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 5000000, "FINALIZED")
    b1 = create_meat_cut_batch(setup["restaurant"]["id"], period["id"], "RIB_1", 10.0)
    b2 = create_meat_cut_batch(setup["restaurant"]["id"], period["id"], "RIB_1", 10.0)
    b1 = audit_batch(b1["id"], 6.995)
    b2 = audit_batch(b2["id"], 6.995)
    assert b1["waste_charge_cents"] == 2
    assert b1["status"] == "VARIANCE_CONFIRMED"
    assert b2["waste_charge_cents"] == 2
    assert b2["status"] == "VARIANCE_CONFIRMED"
    compute_period(period["id"])
    finalized = finalize_period(period["id"])
    # Per-batch-then-sum: 5000000 - 2 - 2 == 4999996 (sum-then-round would give 4999997).
    assert finalized["final_distributable_profit_cents"] == 4999996


def test_waste_charge_conforming_boundary_exactly_allowed(api):
    """PRD §3.7: "The boundary is inclusive on the conforming side: when
    actual waste equals allowed waste exactly, the excess is zero."
    PRD §3.7: "When the excess is zero, the batch becomes AUDITED_CONFORMING
    and its waste_charge_cents is 0."

    Design: Difficulty/combinatorial_formula/waste_charge_per_batch_rounding_beats_sum_then_round
    """
    setup = setup_active_contract()
    create_yield_standard(
        cut_code="RIB_1",
        expected_yield_pct=70,
        waste_tolerance_pct=0,
        standard_cost_per_lb_cents=300,
    )
    period = create_open_period(setup["restaurant"]["id"], "2027-06-01", "2027-07-01")
    set_clock("2027-06-10T00:00:00Z")
    batch = create_meat_cut_batch(setup["restaurant"]["id"], period["id"], "RIB_1", 10.0)
    # Actual waste 3.000 lbs equals the allowed waste exactly -> excess 0.
    batch = audit_batch(batch["id"], 7.0)
    assert batch["status"] == "AUDITED_CONFORMING"
    assert batch["waste_charge_cents"] == 0
    assert batch["excess_waste_lbs"] == 0


def test_unwaived_variance_charge_reduces_final_profit(api):
    """PRD §3.6: "final_distributable_profit_cents — the final variant of the
    profit computation: only FINALIZED line items, reading actual_amount_cents,
    minus the consolidated meat waste charge — the sum of waste_charge_cents
    over the period's batches in AUDITED_CONFORMING or VARIANCE_CONFIRMED
    status (waived batches contribute nothing because their charge was zeroed
    and their status no longer qualifies)."

    Design: Difficulty/compensating_invariant/escrow_to_capital_conservation_and_waive_compensation
    """
    setup = setup_active_contract()
    create_yield_standard(
        cut_code="CHK_1", expected_yield_pct=80, waste_tolerance_pct=0,
        standard_cost_per_lb_cents=300,
    )
    period = create_open_period(setup["restaurant"]["id"], "2027-06-01", "2027-07-01")
    set_clock("2027-06-10T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 4000000, "FINALIZED")
    batch = create_meat_cut_batch(setup["restaurant"]["id"], period["id"], "CHK_1", 10.0)
    batch = audit_batch(batch["id"], 6.0)
    assert batch["waste_charge_cents"] == 600
    assert batch["status"] == "VARIANCE_CONFIRMED"
    compute_period(period["id"])
    finalized = finalize_period(period["id"])
    # Forward action: the consolidated waste deduction lands on final profit.
    assert finalized["final_distributable_profit_cents"] == 3999400


def test_batch_restaurant_period_mismatch_and_unknown_cut_rejected(api):
    """PRD §3.7: "The period referenced must belong to the same restaurant —
    a mismatch is rejected with ERR_BATCH_PERIOD_RESTAURANT_MISMATCH — the
    period must be in OPEN, COMPUTED, or REOPENED (otherwise
    ERR_PERIOD_NOT_OPEN), and the cut code must match an active yield standard
    (otherwise ERR_UNKNOWN_CUT_CODE)."

    Design: Corner/validations/batch_restaurant_period_mismatch_and_unknown_cut_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    r1 = create_active_restaurant()
    r3 = create_active_restaurant(city="El Paso")
    pp_r1 = create_open_period(r1["id"], "2027-01-01", "2027-02-01")
    pp_r3 = create_open_period(r3["id"], "2027-01-01", "2027-02-01")
    create_yield_standard(
        cut_code="SIR_8", expected_yield_pct=70, waste_tolerance_pct=5,
        standard_cost_per_lb_cents=300,
    )
    resp_mismatch = api.create_meat_cut_batch(
        {
            "restaurant_id": r1["id"],
            "profit_period_id": pp_r3["id"],
            "cut_code": "SIR_8",
            "sub_primal_weight_lbs": 10.0,
        },
        AUDITOR,
    )
    validate_error(resp_mismatch, ApiErrorId.ERR_BATCH_PERIOD_RESTAURANT_MISMATCH)
    resp_cut = api.create_meat_cut_batch(
        {
            "restaurant_id": r1["id"],
            "profit_period_id": pp_r1["id"],
            "cut_code": "NOPE_1",
            "sub_primal_weight_lbs": 10.0,
        },
        AUDITOR,
    )
    validate_error(resp_cut, ApiErrorId.ERR_UNKNOWN_CUT_CODE)
    _, meta = validate_paginated(
        api.list_meat_cut_batches(AUDITOR, params={"restaurant_id": r1["id"]})
    )
    assert meta["total_count"] == 0


def test_batch_audit_on_finalized_period_rejected(api):
    """PRD §3.7: "An `OperationsAuditor` audits a `RECORDED` batch by recording
    the `actual_yield_lbs`; the same period-state gate applies
    (`ERR_PERIOD_NOT_OPEN`)."
    PRD §3.7: "the period must be in `OPEN`, `COMPUTED`, or `REOPENED`
    (otherwise `ERR_PERIOD_NOT_OPEN`)"

    Design: Corner/validations/batch_audit_on_finalized_period_rejected
    """
    setup = setup_active_contract()
    create_yield_standard(
        cut_code="SIR_8", expected_yield_pct=70, waste_tolerance_pct=5,
        standard_cost_per_lb_cents=300,
    )
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    batch = create_meat_cut_batch(setup["restaurant"]["id"], period["id"], "SIR_8", 10.0)
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 5000000, "FINALIZED")
    compute_period(period["id"])
    finalize_period(period["id"])
    resp = api.audit_meat_cut_batch(batch["id"], {"actual_yield_lbs": 7.0}, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN)
    fetched = validate_success(api.get_meat_cut_batch(batch["id"], AUDITOR))
    assert fetched["status"] == "RECORDED"
    assert fetched["actual_yield_lbs"] is None


def test_yield_standard_duplicate_active_cut_code_rejected(api):
    """PRD §3.7: "The cut code must be unique among active standards —
    creating a duplicate active cut code is rejected with
    ERR_DUPLICATE_CUT_CODE. Deactivating a standard sets active to false."

    Design: Corner/endpoints/yield_standard_duplicate_active_cut_code_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    ys1 = create_yield_standard(
        cut_code="SIR_8", expected_yield_pct=70, waste_tolerance_pct=5,
        standard_cost_per_lb_cents=300,
    )
    resp_dup = api.create_yield_standard(
        {
            "cut_code": "SIR_8",
            "expected_yield_pct": 72,
            "waste_tolerance_pct": 5,
            "standard_cost_per_lb_cents": 310,
        },
        CONTROLLER,
    )
    validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_CUT_CODE)
    validate_success(api.deactivate_yield_standard(ys1["id"], CONTROLLER))
    ys2 = validate_success(
        api.create_yield_standard(
            {
                "cut_code": "SIR_8",
                "expected_yield_pct": 72,
                "waste_tolerance_pct": 5,
                "standard_cost_per_lb_cents": 310,
            },
            CONTROLLER,
        ),
        expected_status=201,
    )
    assert ys2["active"] is True
    ys1_now = validate_success(api.get_yield_standard(ys1["id"], CONTROLLER))
    assert ys1_now["active"] is False


def test_escrow_to_capital_conservation_and_waive_compensation(api):
    """PRD §3.3: "When activation succeeds, the escrow balance moves
    wholesale: capital_account_cents takes the full escrow amount,
    buy_in_escrow_cents resets to 0 ..."
    PRD §3.7: "Waiving is compensation: the charge is removed from the
    consolidated waste deduction at period finalize, and the batch remains
    terminally VARIANCE_WAIVED."
    PRD §3.3: "If the funding window lapses before activation, the clock sweep
    moves the contract from PENDING_FUNDING to LAPSED and unwinds the escrow:
    every POSTED buy-in payment on the contract flips to REFUNDED,
    buy_in_escrow_cents resets to 0, and the partner moves to WITHDRAWN."

    Design: Difficulty/compensating_invariant/escrow_to_capital_conservation_and_waive_compensation
    """
    from test_helpers import create_draft_contract, submit_contract, fund_contract, create_partner

    set_clock("2026-09-01T00:00:00Z")
    p1 = create_partner(full_name="Pat Morgan", email="pm@x.com")
    p2 = create_partner(full_name="Sam Reed", email="sr@x.com")
    r1 = create_active_restaurant()
    r3 = create_active_restaurant(city="El Paso")
    # Contract C14: funded in two payments then activated.
    c14 = create_draft_contract(p1["id"], r1["id"])
    submit_contract(c14["id"])
    fund_contract(c14["id"], p1["id"], 1000000)
    fund_contract(c14["id"], p1["id"], 1500000)
    validate_success(api.activate_contract(c14["id"], CONTROLLER))
    # Contract C15: partially funded then lapsed past the 14-day window.
    c15 = create_draft_contract(p2["id"], r3["id"])
    submit_contract(c15["id"])
    fund_contract(c15["id"], p2["id"], 1000000)
    set_clock("2026-09-20T00:00:00Z")
    c15_now = validate_success(api.get_contract(c15["id"], CONTROLLER))
    assert c15_now["status"] == "LAPSED"
    assert c15_now["buy_in_escrow_cents"] == 0
    payments, _ = validate_paginated(api.list_buy_in_payments(c15["id"], CONTROLLER))
    assert all(p["status"] == "REFUNDED" for p in payments)

    c14_now = validate_success(api.get_contract(c14["id"], CONTROLLER))
    assert c14_now["capital_account_cents"] == 2500000
    assert c14_now["buy_in_escrow_cents"] == 0

    # Waive compensation on R1's period.
    create_yield_standard(
        cut_code="CHK_1", expected_yield_pct=80, waste_tolerance_pct=0,
        standard_cost_per_lb_cents=300,
    )
    period = create_open_period(r1["id"], "2027-06-01", "2027-07-01")
    set_clock("2027-06-10T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 4000000, "FINALIZED")
    batch = create_meat_cut_batch(r1["id"], period["id"], "CHK_1", 10.0)
    batch = audit_batch(batch["id"], 6.0)
    assert batch["waste_charge_cents"] == 600  # excess 2.0 lbs * 300
    waived = validate_success(api.waive_meat_cut_batch(batch["id"], CONTROLLER))
    assert waived["waste_charge_cents"] == 0
    assert waived["status"] == "VARIANCE_WAIVED"
    compute_period(period["id"])
    finalized = finalize_period(period["id"])
    assert finalized["final_distributable_profit_cents"] == 4000000
