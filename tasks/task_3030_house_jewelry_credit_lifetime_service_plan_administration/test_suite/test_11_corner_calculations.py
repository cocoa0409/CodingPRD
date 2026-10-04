"""Calculation-surface claims: constants, input sets, precision, variants."""

from test_helpers import (
    ADMIN,
    AFTERCARE,
    ANALYST,
    ASSOCIATE,
    LOGICAL_CLOCK_START,
    MANAGER,
    api_client,
    get_success_data,
    reset_clock,
    setup_customer,
    setup_plan_environment,
    setup_plan_with_accrual,
    setup_store,
    validate_success,
)


def test_promo_deferral_fee_matches_the_code_headline_rate(api, sales_associate_headers):
    """PRD §2.5: "Worked reference: `PROMO_12_6M` on a 450,000 cent net amount with no bundle gives a principal of 450,000, a quarterly installment of 112,500 (450,000 over 4 quarters), and a merchant deferral fee of 54,000."
    PRD §2.5: "`PROMO_12_6M` grants `deferred_months` of 6, a `simplicity_months` window of 12, and a `deferral_basis_points` rate of 1200."

    Design: Corner/calculations/promo_deferral_fee_matches_the_code_headline_rate
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment(
        plan_code="PROMO_12_6M", base_price_cents=450_000)

    assert plan["principal_cents"] == 450_000
    assert plan["merchant_deferral_fee_cents"] == 54_000
    assert plan["installment_quarter_cents"] == 112_500
    assert plan["installment_amount_cents"] == 112_500
    assert plan["deferred_months"] == 6
    assert plan["simplicity_months"] == 12
    assert plan["promotional_apr_pct"] == 26.99
    assert plan["deferred_interest_accrued_cents"] == 0
    assert plan["plan_status"] == "ACCRUING"


def test_promo_24_12m_applies_its_own_quarter_count_and_rate(api, sales_associate_headers):
    """PRD §2.5: "`PROMO_24_12M` on the same amount gives a quarterly installment of 56,250 (450,000 over 8 quarters) and a merchant deferral fee of 72,000."
    PRD §2.5: "`PROMO_24_12M` grants 12 deferred months, a 24-month window, and 1600 basis points."

    Design: Corner/calculations/promo_deferral_fee_matches_the_code_headline_rate
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment(
        plan_code="PROMO_24_12M", base_price_cents=450_000)

    assert plan["installment_quarter_cents"] == 56_250
    assert plan["merchant_deferral_fee_cents"] == 72_000
    assert plan["simplicity_months"] == 24
    assert plan["promotional_apr_pct"] == 28.99


def test_cash_lines_are_excluded_before_the_statement_rollup_runs(api, customer_service_headers):
    """PRD §2.11: "only lines whose `line_status` is `BILLABLE` participate, and `PAID` and `DISPUTED` lines are excluded before anything else runs."
    PRD §2.11: "Worked reference with two billable lines of 250,000 and 260,000 cents at a `billable_pct` of 1.0: `SUM_THEN_TIER` gives a subtotal of 510,000"

    Design: Corner/calculations/cash_lines_are_excluded_before_the_statement_rollup_runs
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_store()
    customer = setup_customer()
    statement = validate_success(api.create_billing_statement({
        "customer_id": customer["id"],
        "statement_period": "2026-09",
        "lines": [
            {"amount_cents": 250_000, "billable_pct": 1.0, "line_status": "BILLABLE"},
            {"amount_cents": 260_000, "billable_pct": 1.0, "line_status": "PAID"},
        ],
    }, customer_service_headers), 201)

    assert statement["statement_balance_cents"] == 255_000, (
        "only the single BILLABLE line participates; its 250,000 subtotal "
        "reaches the 200,000 mid boundary but not the 500,000 high boundary, "
        "so the 0.02 tier applies"
    )
    assert statement["statement_balance_cents"] != 525_300, (
        "including the paid line would have given 525,300"
    )
    assert statement["statement_status"] == "OPEN"


def test_a_disputed_line_is_dropped_the_same_way_a_paid_one_is(api, customer_service_headers):
    """PRD §3.8: "Each line carries its own `amount_cents`, its `billable_pct`, and a `line_status`; only lines whose status is `BILLABLE` are counted, and lines already `PAID` or `DISPUTED` are dropped before any arithmetic runs."
    PRD §2.11: "each billable line's amount is multiplied by its `billable_pct` and rounded half up, the results are summed into a subtotal, a tier fee percentage is selected from that aggregate"

    Design: Corner/calculations/cash_lines_are_excluded_before_the_statement_rollup_runs
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_store()
    customer = setup_customer()
    statement = validate_success(api.create_billing_statement({
        "customer_id": customer["id"],
        "statement_period": "2026-11",
        "lines": [
            {"amount_cents": 250_000, "billable_pct": 1.0, "line_status": "BILLABLE"},
            {"amount_cents": 260_000, "billable_pct": 1.0, "line_status": "DISPUTED"},
        ],
    }, customer_service_headers), 201)

    assert statement["statement_balance_cents"] == 255_000
    assert statement["statement_status"] == "OPEN"


def test_deferred_interest_accrual_is_rounded_to_whole_cents(api, customer_service_headers):
    """PRD §2.5: "over 120 days, 39,930 cents"
    PRD §2.5: "Otherwise it is `principal_cents` multiplied by `promotional_apr_pct`, divided by 100, multiplied by the whole number of days elapsed since the plan was created, and divided by 365 (`DAYS_PER_YEAR`), rounded half up to a whole cent."

    Design: Corner/calculations/deferred_interest_accrual_is_rounded_to_whole_cents
    """
    customer, store, purchase, plan = setup_plan_with_accrual(
        elapsed_days=120, principal_cents=450_000)

    assert plan["deferred_interest_accrued_cents"] == 39_930, (
        "a ceiling or truncation implementation would report 39929 or 39931"
    )
    assert plan["final_settlement_amount_cents"] == 489_930


def test_interest_over_a_different_horizon_accrues_a_different_rounding(
        api, customer_service_headers):
    """PRD §2.5: "Worked reference: a 450,000 cent principal at 26.99 percent over 196 days accrues 65,220 cents; over 120 days, 39,930 cents; over 200 days, 66,551 cents."
    PRD §2.5: "Only plans in `ACCRUING` status accrue"

    Design: Corner/calculations/deferred_interest_accrual_is_rounded_to_whole_cents
    """
    customer, store, purchase, plan = setup_plan_with_accrual(
        elapsed_days=196, principal_cents=450_000)

    assert plan["deferred_interest_accrued_cents"] == 65_220
    assert plan["final_settlement_amount_cents"] == 515_220
    assert plan["plan_status"] == "ACCRUING"


def test_a_paid_plan_contributes_no_accrual(api, customer_service_headers):
    """PRD §2.5: "`PAID`, `CAPITALIZED`, `DEFAULTED`, and `VOIDED` plans contribute 0, which is the `VESTED_ZERO` reading against the `PROVISIONAL_ACCRUING` reading for an `ACCRUING` plan."
    PRD §3.2: "`deferred_interest_accrued_cents` and `final_settlement_amount_cents` both fall to 0, which is the forgiveness the promo promised"

    Design: Corner/calculations/deferred_interest_accrual_is_rounded_to_whole_cents
    """
    customer, store, purchase, plan = setup_plan_with_accrual(
        elapsed_days=120, principal_cents=450_000)
    before = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    amount = before["principal_cents"] + before["deferred_interest_accrued_cents"]

    paid = validate_success(api.payoff_promotional_plan(
        plan["id"], {"amount_cents": amount, "expected_plan_version": before["version"]},
        customer_service_headers), 200)
    assert paid["plan_status"] == "PAID"
    assert paid["deferred_interest_accrued_cents"] == 0
    assert paid["final_settlement_amount_cents"] == 0


def test_capitalization_sweep_is_selected_by_the_clock_not_the_request(
        api, credit_analyst_headers):
    """PRD §3.2: "Any plan still `ACCRUING` when the current instant is strictly after `simplicity_expires_at` has its deferred interest converted into principal."
    PRD §2.5: "`deferred_interest_accrued_cents` is 0 whenever the plan's `plan_status` is `CAPITALIZED`, because the interest has by then been absorbed into the principal."

    Design: Corner/calculations/capitalization_transfers_the_accrual_into_principal_at_the_window_edge
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment(
        plan_code="PROMO_12_6M", base_price_cents=450_000)
    reset_clock("2027-09-01T00:00:00Z")
    at_edge = validate_success(api.get_promotional_plan(plan["id"], credit_analyst_headers), 200)
    assert at_edge["plan_status"] == "ACCRUING", (
        "the closed window is still ACCRUING at its right edge"
    )

    sweep = validate_success(api.capitalize_plans_due(credit_analyst_headers), 200)
    assert sweep["capitalized_count"] == 0
    after = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    assert after["plan_status"] == "ACCRUING"
    assert after["merchant_deferral_fee_cents"] == 54_000, (
        "the merchant deferral credit survives while the plan accrues"
    )


def test_one_instant_past_the_edge_the_sweep_folds_interest_into_principal(
        api, credit_analyst_headers):
    """PRD §3.2: "`final_settlement_amount_cents` becomes the new principal, `plan_status` becomes `CAPITALIZED`, and `merchant_deferral_fee_cents` is zeroed because capitalization cancels the merchant's deferral credit."
    PRD §3.2: "The plan's `principal_cents` is increased by the accrued interest, `deferred_interest_accrued_cents` falls back to 0"

    Design: Corner/calculations/capitalization_transfers_the_accrual_into_principal_at_the_window_edge
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment(
        plan_code="PROMO_12_6M", base_price_cents=450_000)
    reset_clock("2027-09-02T00:00:00Z")
    sweep = validate_success(api.capitalize_plans_due(credit_analyst_headers), 200)
    assert sweep["capitalized_count"] == 1

    after = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    assert after["plan_status"] == "CAPITALIZED"
    assert after["deferred_interest_accrued_cents"] == 0
    assert after["merchant_deferral_fee_cents"] == 0
    assert after["principal_cents"] > 450_000, (
        "the accrued interest is folded into the principal"
    )
    assert after["final_settlement_amount_cents"] == after["principal_cents"]


def test_ledger_projection_recomputes_after_each_appended_entry(api, customer_service_headers):
    """PRD §3.2: "Such an append takes the next `entry_sequence` after the plan's current maximum, stamps its `projected_total_cents` from the payoff-ledger projection described below"
    PRD §3.2: "a 450,000 cent principal at 26.99 percent accruing 65,220 cents over 196 days projects 515,220 cents under both readings when no entries exist"

    Design: Corner/calculations/ledger_projection_recomputes_after_each_appended_entry
    """
    customer, store, purchase, plan = setup_plan_with_accrual(
        elapsed_days=120, principal_cents=450_000)
    settled = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    base = settled["principal_cents"] + settled["deferred_interest_accrued_cents"]

    first = validate_success(api.create_ledger_entry({
        "plan_id": plan["id"], "entry_kind": "INSTALLMENT", "direction": "DECREASE",
        "amount_cents": 40_000, "adjustment_cents": -40_000,
        "reference_bucket": "PROMOTIONAL", "expected_plan_version": settled["version"],
    }, customer_service_headers), 201)
    assert first["projected_total_cents"] == base - 40_000
    assert first["entry_sequence"] == 1

    second = validate_success(api.create_ledger_entry({
        "plan_id": plan["id"], "entry_kind": "INSTALLMENT", "direction": "DECREASE",
        "amount_cents": 40_000, "adjustment_cents": -40_000,
        "reference_bucket": "PROMOTIONAL",
        "expected_plan_version": get_success_data(
            api.get_promotional_plan(plan["id"], customer_service_headers))["version"],
    }, customer_service_headers), 201)
    assert second["projected_total_cents"] == base - 80_000, (
        "the derived projection never lags the entries it summarises"
    )
    assert second["entry_sequence"] == 2


def test_the_plan_ledger_reads_back_in_entry_order(api, customer_service_headers):
    """PRD §2.12: "A payoff ledger entry and a repair hold are immutable records of a single event: they carry only `id` and `created_at`"
    PRD §3.2: "The payoff-ledger projection reads a plan's full entry history in chronological order — ordered by `recorded_at` ascending, with `entry_sequence` ascending as the tie-break"

    Design: Corner/calculations/ledger_projection_recomputes_after_each_appended_entry
    """
    customer, store, purchase, plan = setup_plan_with_accrual(
        elapsed_days=120, principal_cents=450_000)
    settled = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    first = validate_success(api.create_ledger_entry({
        "plan_id": plan["id"], "entry_kind": "INSTALLMENT", "direction": "DECREASE",
        "amount_cents": 40_000, "adjustment_cents": -40_000,
        "reference_bucket": "PROMOTIONAL", "expected_plan_version": settled["version"],
    }, customer_service_headers), 201)
    second = validate_success(api.create_ledger_entry({
        "plan_id": plan["id"], "entry_kind": "INSTALLMENT", "direction": "DECREASE",
        "amount_cents": 40_000, "adjustment_cents": -40_000,
        "reference_bucket": "PROMOTIONAL",
        "expected_plan_version": get_success_data(
            api.get_promotional_plan(plan["id"], customer_service_headers))["version"],
    }, customer_service_headers), 201)

    entries = validate_success(api.list_plan_ledger_entries(
        plan["id"], customer_service_headers), 200)
    assert [e["entry_sequence"] for e in entries] == [1, 2]
    assert entries[0]["id"] == first["id"]
    assert entries[1]["id"] == second["id"]
    assert "version" not in entries[0], "a ledger entry carries no version"
    plan_after = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    assert plan_after["total_paid_cents"] == 80_000