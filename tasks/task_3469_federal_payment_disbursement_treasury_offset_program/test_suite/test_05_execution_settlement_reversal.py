"""Execution gates, settlement sweep, and the reversal restoration cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_payment,
    assert_payment_decomposition,
    create_active_debt,
    create_active_policy,
    create_federal_creditor,
    create_payment_file,
    evaluate_payment,
    execute_payment,
    execute_payment_sequence,
    list_payment_offsets,
    read_creditor,
    read_debt,
    read_payment,
    read_payment_file,
    register_eft_payee,
    reverse_payment,
    set_logical_clock,
    setup_applied_offset,
    setup_settled_payment,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["treasury_operator_headers"]


def test_payment_execute_from_verified_returns_not_executable(api):
    """PRD §3.5: "the payment must be `EVALUATED` — otherwise
    `ERR_PAYMENT_NOT_EXECUTABLE`".

    Design: Corner/state_machines/payment_execute_from_verified_returns_not_executable
    """
    set_logical_clock()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("VENDOR", "FULL")
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 25000, "VENDOR")
    assert payment["processing_status"] == "VERIFIED"

    resp = api.execute_payment(payment["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_EXECUTABLE)
    payment_now = read_payment(payment["id"])
    assert payment_now["processing_status"] == "VERIFIED"
    assert payment_now["total_offset_cents"] == 0


def test_settled_payment_reverse_returns_invalid_state(api):
    """PRD §3.5: "When an executed payment is later found improper, a
    `TreasuryOperator` reverses it (`EXECUTED` → `REVERSED`; attempting the
    reversal from any other state is `ERR_INVALID_STATE`)."
    PRD §2.4: "Setting the clock also runs the settlement sweep: every
    `EXECUTED` payment whose parent file's `settlement_date` falls on or before
    the clock's UTC date transitions to `SETTLED`."

    Design: Corner/state_machines/settled_payment_reverse_returns_invalid_state
    """
    ns = setup_settled_payment()
    assert ns["payment"]["processing_status"] == "SETTLED"

    resp = api.reverse_payment(ns["payment"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert read_debt(ns["debt"]["id"])["current_balance_cents"] == 20000


def test_settlement_sweep_completes_payment_and_file(api):
    """PRD §3.5: "the sweep of §2.4 moves each `EXECUTED` payment to `SETTLED`
    once its parent file's `settlement_date` is on or before the clock's UTC
    date, and a file whose payments have all settled or reversed bubbles up to
    `COMPLETED`."

    Design: Corner/state_machines/settlement_sweep_completes_payment_and_file
    """
    ns = setup_applied_offset()  # file settlement_date 2026-09-15
    set_logical_clock("2026-09-14T00:00:00Z")
    assert read_payment(ns["payment"]["id"])["processing_status"] == "EXECUTED"

    set_logical_clock("2026-09-15T00:00:00Z")
    assert read_payment(ns["payment"]["id"])["processing_status"] == "SETTLED"
    assert read_payment_file(ns["payment_file"]["id"])["status"] == "COMPLETED"


def test_execute_response_reflects_all_side_effects_immediately(api):
    """PRD §3.5: "On success, every `PROPOSED` offset of the payment becomes
    `APPLIED` with `applied_at` stamped to the logical clock; each affected
    debt's `current_balance_cents` falls by its `offset_amount_cents`, reaching
    `PAID_IN_FULL` at exactly zero".
    PRD §3.5: "`total_offset_cents` sums the applied offsets, `disbursed_cents`
    is the remainder of `amount_cents` released to the payee".

    Design: Corner/consistency_model/execute_response_reflects_all_side_effects_immediately
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("SALARY", "FULL")
    debt = create_active_debt(creditor, original_amount_cents=30000)
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 50000, "SALARY")
    payment = evaluate_payment(payment)

    resp = api.execute_payment(payment["id"], OPERATOR)
    executed = validate_success(resp)
    assert executed["processing_status"] == "EXECUTED"
    assert executed["total_offset_cents"] == 30000
    assert executed["disbursed_cents"] == 20000

    reread = read_payment(payment["id"])
    assert reread["processing_status"] == executed["processing_status"]
    assert reread["total_offset_cents"] == executed["total_offset_cents"]
    assert reread["disbursed_cents"] == executed["disbursed_cents"]

    debt_now = read_debt(debt["id"])
    assert debt_now["current_balance_cents"] == 0
    assert debt_now["status"] == "PAID_IN_FULL"


def test_remittance_fee_tier_mode_c(api):
    """PRD §2.9: "The fee percentage is three percent when that pre-event gross
    is below 60,000 cents (six hundred dollars), and two percent when it is at
    or above that threshold. The current event never counts toward its own
    tier."

    Design: Difficulty/combinatorial_formula/remittance_fee_tier_mode_c
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("TAX_REFUND", "FULL")
    create_active_debt(
        creditor,
        debt_type="FEDERAL_TAX",
        original_amount_cents=1000000,
        delinquent_since="2025-12-01T00:00:00Z",
    )
    payment_file = create_payment_file()
    results = execute_payment_sequence(
        creditor, payee, "TAX_REFUND", [30000, 30000, 30000],
        payment_file=payment_file,
    )

    fees = [offsets[0]["fee_cents"] for _, offsets in results]
    # Events 1-2: pre-event gross 0 / 30000 < 60000 -> 3% band (fee 900).
    # Event 3: pre-event gross 60000 is NOT below 60000 -> 2% band (fee 600).
    assert fees == [900, 900, 600]

    creditor_now = read_creditor(creditor["id"])
    assert creditor_now["remitted_gross_ytd_cents"] == 90000
    assert creditor_now["remitted_net_total_cents"] == 87600


def test_payment_decomposition_and_reversal(api):
    """PRD §3.5: "`total_offset_cents` sums the applied offsets,
    `disbursed_cents` is the remainder of `amount_cents` released to the payee".
    PRD §2.9: "A fourth value, `outstanding_receivable_cents`, is never stored:
    it is derived on every read as the sum of `current_balance_cents` over the
    creditor's debts in `ACTIVE` or `IN_COLLECTION` status."

    Design: Difficulty/compensating_invariant/payment_decomposition_and_reversal
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("SALARY", "FULL")
    create_active_debt(
        creditor, debt_type="FEDERAL_TAX", original_amount_cents=30000,
        delinquent_since="2026-01-10T00:00:00Z",
    )
    create_active_debt(
        creditor, original_amount_cents=20000,
        delinquent_since="2026-02-01T00:00:00Z",
    )
    assert read_creditor(creditor["id"])["outstanding_receivable_cents"] == 50000

    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 100000, "SALARY")
    payment = evaluate_payment(payment)
    execute_payment(payment)

    executed = read_payment(payment["id"])
    assert executed["total_offset_cents"] == 50000
    assert executed["disbursed_cents"] == 50000
    assert_payment_decomposition(executed)
    # Both debts are PAID_IN_FULL, so neither counts toward the receivable.
    assert read_creditor(creditor["id"])["outstanding_receivable_cents"] == 0

    reverse_payment(executed)
    assert read_creditor(creditor["id"])["outstanding_receivable_cents"] == 50000


def test_payment_reversal_depth3(api):
    """PRD §3.5: "First, every `APPLIED` offset of the payment becomes
    `REVERSED`, each affected debt's `current_balance_cents` is restored by the
    offset amount, and any debt the offsets had driven to `PAID_IN_FULL` reopens
    to `ACTIVE`. Second, each affected creditor's ledger is debited
    symmetrically to §2.9: `remitted_net_total_cents` falls by the offset's
    `net_remittance_cents` and `remitted_gross_ytd_cents` falls by its
    `offset_amount_cents`."
    PRD §3.5: "On the payment itself, `total_offset_cents` and `disbursed_cents`
    reset to 0".

    Design: Difficulty/transitive_cascade/payment_reversal_depth3
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("SALARY", "FULL")
    debt_1 = create_active_debt(
        creditor, debt_type="FEDERAL_TAX", original_amount_cents=30000,
        delinquent_since="2026-01-10T00:00:00Z",
    )
    debt_2 = create_active_debt(
        creditor, original_amount_cents=20000,
        delinquent_since="2026-02-01T00:00:00Z",
    )
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 100000, "SALARY")
    payment = evaluate_payment(payment)
    execute_payment(payment)
    # 29100 (30000 net of 900) + 19400 (20000 net of 600) credited at execute.
    assert read_creditor(creditor["id"])["remitted_net_total_cents"] == 48500

    reverse_payment(payment)

    reversed_payment = read_payment(payment["id"])
    assert reversed_payment["processing_status"] == "REVERSED"
    assert reversed_payment["total_offset_cents"] == 0
    assert reversed_payment["disbursed_cents"] == 0

    offsets = list_payment_offsets(payment["id"])
    assert len(offsets) == 2
    assert all(o["status"] == "REVERSED" for o in offsets)

    debt_1_now = read_debt(debt_1["id"])
    assert debt_1_now["status"] == "ACTIVE"
    assert debt_1_now["current_balance_cents"] == 30000
    debt_2_now = read_debt(debt_2["id"])
    assert debt_2_now["status"] == "ACTIVE"
    assert debt_2_now["current_balance_cents"] == 20000

    creditor_now = read_creditor(creditor["id"])
    assert creditor_now["remitted_net_total_cents"] == 0
    assert creditor_now["remitted_gross_ytd_cents"] == 0
    assert creditor_now["outstanding_receivable_cents"] == 50000
