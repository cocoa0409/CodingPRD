"""Offset pool sizing, waterfall allocation, re-evaluation supersede, and the
OCC guard on evaluation."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_NOTICE_SENT_AT,
    TEST_USERS,
    add_payment,
    create_active_agreement,
    create_active_debt,
    create_active_policy,
    create_evaluate_payload,
    create_federal_creditor,
    create_payment_file,
    create_state_creditor,
    evaluate_payment,
    execute_payment,
    list_payment_offsets,
    read_creditor,
    read_debt,
    read_payment,
    read_payment_file,
    refer_debt,
    register_eft_payee,
    register_payee,
    set_logical_clock,
    validate_error,
    validate_paginated,
)

OPERATOR = TEST_USERS["treasury_operator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_exempt_policy_pools_zero(api):
    """PRD §3.2: "an `EXEMPT` payment is never offset".
    PRD §3.4: "under this intake estimate an `EXEMPT` policy projects zero".

    Design: Corner/calculations/exempt_policy_pools_zero
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("TAX_REFUND", "EXEMPT")
    debt = create_active_debt(
        creditor, debt_type="FEDERAL_TAX", original_amount_cents=50000
    )
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 50000, "TAX_REFUND")
    assert payment["projected_offset_cents"] == 0

    payment = evaluate_payment(payment)
    assert list_payment_offsets(payment["id"]) == []

    execute_payment(payment)
    payment = read_payment(payment["id"])
    assert payment["total_offset_cents"] == 0
    assert payment["disbursed_cents"] == 50000
    assert read_debt(debt["id"])["current_balance_cents"] == 50000


def test_matching_excludes_non_active_debts(api):
    """PRD §3.4: "Matching selects the eligible debts: those `ACTIVE` at the
    evaluation clock whose `debtor_tin` equals the payment's `payee_tin`".

    Design: Corner/calculations/matching_excludes_non_active_debts
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("SALARY", "FULL")
    debt_active = create_active_debt(
        creditor, original_amount_cents=10000, delinquent_since="2026-01-15T00:00:00Z"
    )
    # NOTICED only (never activated): excluded from matching.
    debt_noticed = refer_debt(
        creditor,
        original_amount_cents=20000,
        delinquent_since="2026-01-10T00:00:00Z",
        notice_sent_at=DEFAULT_NOTICE_SENT_AT,
        due_process_completed=True,
    )
    debt_to_pay = create_active_debt(
        creditor, original_amount_cents=30000, delinquent_since="2026-01-05T00:00:00Z"
    )

    payment_file = create_payment_file()
    # A first 30000-cent payment pays the oldest-delinquency debt in full.
    pay_0 = add_payment(payment_file, payee, 30000, "SALARY")
    pay_0 = evaluate_payment(pay_0)
    execute_payment(pay_0)
    debt_paid = read_debt(debt_to_pay["id"])
    assert debt_paid["status"] == "PAID_IN_FULL"
    assert debt_paid["current_balance_cents"] == 0

    pay_1 = add_payment(payment_file, payee, 100000, "SALARY")
    pay_1 = evaluate_payment(pay_1)
    offsets = list_payment_offsets(pay_1["id"])
    assert len(offsets) == 1
    assert offsets[0]["offset_amount_cents"] == 10000
    assert offsets[0]["debt_id"] == debt_active["id"]

    rows, _ = validate_paginated(
        api.list_debts(AUDITOR, params={"debtor_tin": "111-22-3333"})
    )
    assert len(rows) == 3, "NOTICED and PAID_IN_FULL debts exist but never match"

    execute_payment(pay_1)
    pay_1 = read_payment(pay_1["id"])
    assert pay_1["total_offset_cents"] == 10000
    assert pay_1["disbursed_cents"] == 90000
    assert read_debt(debt_noticed["id"])["current_balance_cents"] == 20000


def test_waterfall_tie_break_uses_delinquent_since_then_created_at(api):
    """PRD §3.4: "Allocation walks the eligible debts ordered by `priority_rank`
    ascending, then `delinquent_since` ascending, then `created_at` ascending —
    never the server-minted `id`."
    PRD §3.4: "Each debt in turn takes the lesser of the remaining pool and its
    own `current_balance_cents`".

    Design: Corner/calculations/waterfall_tie_break_uses_delinquent_since_then_created_at
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("VENDOR", "FULL")
    # Referred first but delinquent later — loses the tie-break.
    debt_a = create_active_debt(
        creditor, original_amount_cents=8000, delinquent_since="2026-02-01T00:00:00Z"
    )
    # Referred second but delinquent earlier — served first.
    debt_b = create_active_debt(
        creditor, original_amount_cents=8000, delinquent_since="2026-01-01T00:00:00Z"
    )
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 10000, "VENDOR")
    payment = evaluate_payment(payment)

    by_debt = {o["debt_id"]: o for o in list_payment_offsets(payment["id"])}
    assert by_debt[debt_b["id"]]["offset_amount_cents"] == 8000
    assert by_debt[debt_a["id"]]["offset_amount_cents"] == 2000
    assert by_debt[debt_a["id"]]["priority_rank"] == 30
    assert by_debt[debt_b["id"]]["priority_rank"] == 30


def test_reevaluate_supersedes_and_drops_prior_proposals(api):
    """PRD §3.4: "re-evaluating an `EVALUATED` payment supersedes the prior run —
    every existing `PROPOSED` offset of the payment drops to `DROPPED`, a fresh
    match is computed, and the payment's `version` increments with each
    evaluation."

    Design: Corner/state_machines/reevaluate_supersedes_and_drops_prior_proposals
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("SALARY", "FULL")
    create_active_debt(creditor, original_amount_cents=50000)
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 30000, "SALARY")

    payment = evaluate_payment(payment)
    payment = evaluate_payment(payment)  # supersede with the fresh version

    dropped = list_payment_offsets(payment["id"], status="DROPPED")
    proposed = list_payment_offsets(payment["id"], status="PROPOSED")
    assert len(dropped) == 1
    assert len(proposed) == 1
    assert proposed[0]["offset_amount_cents"] == 30000


def test_occ_evaluate_stale_version_returns_412(api):
    """PRD §2.7: "If it does not equal the payment's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "The check is purely version-based: a strictly sequential second
    evaluation carrying the pre-supersede version fails."

    Design: Corner/cross_cutting_layers/occ_evaluate_stale_version_returns_412
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("SALARY", "FULL")
    create_active_debt(creditor, original_amount_cents=50000)
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 30000, "SALARY")
    stale_version = payment["version"]

    evaluated = evaluate_payment(payment)
    resp = api.evaluate_offsets(
        payment["id"], create_evaluate_payload(stale_version), OPERATOR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    payment_now = read_payment(payment["id"])
    assert payment_now["version"] == evaluated["version"]
    assert len(list_payment_offsets(payment["id"], status="PROPOSED")) == 1


def test_offset_projection_intake_vs_execution(api):
    """PRD §3.4: "a `PARTIAL` policy projects the amount minus its
    `protected_minimum_cents`, floored at zero — with neither the percentage cap
    nor the child-support branch applied, because no match set exists yet."
    PRD §3.4: "for `PARTIAL`, the lesser of the amount minus the protected
    minimum (floored at zero) and the amount multiplied by the applicable
    percentage with the product rounded half up to whole cents".

    Design: Difficulty/dual_variant_calc/offset_projection_intake_vs_execution
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy(
        "BENEFIT_RETIREMENT", "PARTIAL",
        protected_minimum_cents=75000, max_offset_pct=0.15,
    )
    debt = create_active_debt(
        creditor, debt_type="FEDERAL_NONTAX", original_amount_cents=200000
    )
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 200000, "BENEFIT_RETIREMENT")
    # INTAKE estimate: max(0, 200000 - 75000) — the percentage cap is not applied.
    assert payment["projected_offset_cents"] == 125000

    payment = evaluate_payment(payment)
    execute_payment(payment)
    payment = read_payment(payment["id"])
    # EXECUTION_FINAL: min(125000, round_half_up(200000 * 0.15)) == 30000.
    assert payment["total_offset_cents"] == 30000
    assert payment["projected_offset_cents"] == 125000
    assert payment["projected_offset_cents"] != payment["total_offset_cents"]
    assert payment["disbursed_cents"] == 170000

    offsets = list_payment_offsets(payment["id"])
    assert len(offsets) == 1
    offset = offsets[0]
    assert offset["offset_amount_cents"] == 30000
    assert offset["fee_cents"] == 900  # 3% low band, pre-event gross 0
    assert offset["net_remittance_cents"] == 29100

    creditor_now = read_creditor(creditor["id"])
    assert creditor_now["remitted_net_total_cents"] == 29100
    assert creditor_now["remitted_gross_ytd_cents"] == 30000

    debt_now = read_debt(debt["id"])
    assert debt_now["current_balance_cents"] == 170000
    assert debt_now["status"] == "ACTIVE"


def test_offset_pool_partial_policy_mode_a(api):
    """PRD §3.4: "for `PARTIAL`, the lesser of the amount minus the protected
    minimum (floored at zero) and the amount multiplied by the applicable
    percentage with the product rounded half up to whole cents — where the
    applicable percentage is 65 percent whenever any eligible matched debt is of
    type `CHILD_SUPPORT`, and the policy's own `max_offset_pct` otherwise."

    Design: Difficulty/combinatorial_formula/offset_pool_partial_policy_mode_a
    """
    set_logical_clock()
    cred_fed = create_federal_creditor()
    payee_a = register_eft_payee(tin="111-22-3333")
    payee_b = register_payee(tin="555-66-7777", legal_name="Sam Poe")
    create_active_policy(
        "BENEFIT_RETIREMENT", "PARTIAL",
        protected_minimum_cents=75000, max_offset_pct=0.15,
    )
    cred_ca = create_state_creditor(
        "CA", creditor_code="CA-FTB", legal_name="California Franchise Tax Board"
    )
    create_active_agreement("CA", "BIDIRECTIONAL")
    create_active_debt(
        cred_fed, debtor_tin="111-22-3333", debt_type="FEDERAL_NONTAX",
        original_amount_cents=500000,
    )
    create_active_debt(
        cred_ca, debtor_tin="555-66-7777", debt_type="CHILD_SUPPORT",
        original_amount_cents=500000,
    )

    file_a = create_payment_file()
    pay_a = add_payment(file_a, payee_a, 200000, "BENEFIT_RETIREMENT")
    pay_a = evaluate_payment(pay_a)
    file_b = create_payment_file()
    pay_b = add_payment(file_b, payee_b, 200000, "BENEFIT_RETIREMENT")
    pay_b = evaluate_payment(pay_b)

    offsets_a = list_payment_offsets(pay_a["id"])
    offsets_b = list_payment_offsets(pay_b["id"])
    # No CHILD_SUPPORT match: the 0.15 cap binds — min(125000, 30000).
    assert len(offsets_a) == 1
    assert offsets_a[0]["offset_amount_cents"] == 30000
    # CHILD_SUPPORT match: the 0.65 branch lifts the cap — min(125000, 130000).
    assert len(offsets_b) == 1
    assert offsets_b[0]["offset_amount_cents"] == 125000
    assert offsets_a[0]["offset_amount_cents"] != offsets_b[0]["offset_amount_cents"]


def test_protected_minimum_exact_equality(api):
    """PRD §3.4: "for `PARTIAL`, the lesser of the amount minus the protected
    minimum (floored at zero) and the amount multiplied by the applicable
    percentage with the product rounded half up to whole cents".
    PRD §3.4: "a `PARTIAL` policy projects the amount minus its
    `protected_minimum_cents`, floored at zero".

    Design: Difficulty/boundary_precision_check/protected_minimum_exact_equality
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy(
        "BENEFIT_DISABILITY", "PARTIAL",
        protected_minimum_cents=75000, max_offset_pct=0.50,
    )
    debt = create_active_debt(creditor, original_amount_cents=100000)
    payment_file = create_payment_file()
    pay_eq = add_payment(payment_file, payee, 75000, "BENEFIT_DISABILITY")
    pay_over = add_payment(payment_file, payee, 75001, "BENEFIT_DISABILITY")
    assert pay_eq["projected_offset_cents"] == 0
    assert pay_over["projected_offset_cents"] == 1

    pay_eq = evaluate_payment(pay_eq)
    execute_payment(pay_eq)
    pay_over = evaluate_payment(pay_over)
    execute_payment(pay_over)

    # Exactly at the protected minimum the pool is zero: no offsets at all.
    assert list_payment_offsets(pay_eq["id"]) == []
    pay_eq = read_payment(pay_eq["id"])
    assert pay_eq["total_offset_cents"] == 0
    assert pay_eq["disbursed_cents"] == 75000

    # One cent over the floor pools exactly one cent.
    offsets_over = list_payment_offsets(pay_over["id"])
    assert len(offsets_over) == 1
    assert offsets_over[0]["offset_amount_cents"] == 1
    pay_over = read_payment(pay_over["id"])
    assert pay_over["disbursed_cents"] == 75000
    assert read_debt(debt["id"])["current_balance_cents"] == 99999


def test_per_payment_cap_rounding_mode_b(api):
    """PRD §2.6: "Aggregation order is pinned at the file level: each payment's
    offset pool is computed and rounded to whole cents first, and the file
    totals are the plain sums of those per-payment rounded integers. Summing
    unrounded pools and rounding once at the file level is forbidden — it yields
    a different cent total."

    Design: Difficulty/combinatorial_formula/per_payment_cap_rounding_mode_b
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee_a = register_eft_payee(tin="111-22-3333")
    payee_b = register_payee(tin="555-66-7777", legal_name="Sam Poe")
    create_active_policy(
        "GRANT", "PARTIAL", protected_minimum_cents=5000, max_offset_pct=0.15
    )
    create_active_debt(
        creditor, debtor_tin="111-22-3333", original_amount_cents=100000
    )
    create_active_debt(
        creditor, debtor_tin="555-66-7777", debtor_name="Sam Poe",
        delinquent_since="2026-02-01T00:00:00Z", original_amount_cents=100000,
    )
    payment_file = create_payment_file()
    pay_a = add_payment(payment_file, payee_a, 33337, "GRANT")
    pay_b = add_payment(payment_file, payee_b, 33337, "GRANT")
    pay_a = evaluate_payment(pay_a)
    pay_b = evaluate_payment(pay_b)
    execute_payment(pay_a)
    execute_payment(pay_b)

    # round_half_up(33337 * 0.15) == 5001 per payment, rounded before summation.
    assert read_payment(pay_a["id"])["total_offset_cents"] == 5001
    assert read_payment(pay_b["id"])["total_offset_cents"] == 5001
    file_now = read_payment_file(payment_file["id"])
    assert file_now["total_offset_cents"] == 10002
    assert file_now["total_offset_cents"] != 10001, (
        "10001 would be the forbidden sum-then-round result"
    )
    assert file_now["total_disbursed_cents"] == 56672
    assert file_now["payment_count"] == 2
