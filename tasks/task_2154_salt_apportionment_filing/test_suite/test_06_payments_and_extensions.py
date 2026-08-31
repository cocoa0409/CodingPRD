"""Estimated remittances, safe harbours, refunds and filing extensions."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money,
    create_filing,
    create_registration,
    make_controller_headers,
    read_credit_claim,
    read_filing,
    read_payment,
    read_registration,
    record_payment,
    set_clock,
    setup_bare_registration,
    setup_filed_filing,
    setup_filed_filing_with_applied_payment,
    setup_group_with_members,
    setup_locked_filing,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["tax_manager_headers"]
SA = TEST_USERS["state_analyst_headers"]
CTRL = TEST_USERS["controller_headers"]
AUD = TEST_USERS["auditor_headers"]

REFUNDABLE_CREDIT = [
    {"credit_code": "REFUNDABLE_JOBS", "granted_amount": 100000.00,
     "priority_order": 1, "refundable": True, "expires_after_years": 5},
]


def _twin_safe_harbor_registrations():
    """Two field-for-field identical registrations differing only in safe_harbor_basis."""
    ctx = setup_group_with_members(
        group_overrides={
            "name": "Harbor Systems", "everywhere_sales": 8000000,
            "everywhere_property": 2000000, "everywhere_payroll": 1500000,
        },
        include_member_b=False,
    )
    ctx["reg_ca_id"] = create_registration(
        ctx["group_id"], state_code="CA", factor_formula="SINGLE_SALES_FACTOR",
        tax_rate=0.0884, throwback_rule="NONE", service_sourcing_rule="MARKET_BASED",
        safe_harbor_basis="PRIOR_YEAR_110", prior_year_tax=40000,
        current_year_estimated_tax=90000, estimated_installment_count=4,
    )["id"]
    ctx["reg_ny_id"] = create_registration(
        ctx["group_id"], state_code="NY", factor_formula="SINGLE_SALES_FACTOR",
        tax_rate=0.0650, throwback_rule="NONE", service_sourcing_rule="MARKET_BASED",
        safe_harbor_basis="CURRENT_YEAR_90", prior_year_tax=40000,
        current_year_estimated_tax=90000, estimated_installment_count=4,
    )["id"]
    for registration_id in (ctx["reg_ca_id"], ctx["reg_ny_id"]):
        record_payment(registration_id, tax_year=2026, installment_number=1,
                       amount=8000.00, paid_on_date="2026-04-15T00:00:00Z")
    return ctx


def test_prior_year_uplift_safe_harbor_prices_the_second_installment(api):
    """PRD 3.6: "Under `PRIOR_YEAR_110` it is `prior_year_tax` multiplied by 1.10 and rounded to 2 decimal places — the ten-percent uplift larger states impose on bigger taxpayers."
    PRD 3.6: "From the annual requirement, this installment's `safe_harbor_required_amount` is the annual required amount multiplied by this installment's number and divided by the registration's `estimated_installment_count`, rounded half up to 2 decimal places — a cumulative figure, so the third of four installments must have covered three quarters of the year's requirement."
    PRD 3.6: "The payment's `underpayment_amount` is the greater of zero and the `safe_harbor_required_amount` less that cumulative figure, rounded to 2 decimal places, and its `underpayment_penalty` is the `underpayment_amount` multiplied by the five-percent underpayment rate, rounded half up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/prior_year_vs_current_year_safe_harbor_divergence
    """
    ctx = _twin_safe_harbor_registrations()

    payment = validate_success(api.create_payment(ctx["reg_ca_id"], {
        "tax_year": 2026, "installment_number": 2, "amount": 8000.00,
        "paid_on_date": "2026-06-15T00:00:00Z",
        "expected_registration_version": read_registration(ctx["reg_ca_id"])["version"],
    }, CTRL), 201)

    assert_money(payment["safe_harbor_required_amount"], 22000.00,
                 "PRIOR_YEAR_110 safe_harbor_required_amount")
    assert_money(payment["underpayment_amount"], 6000.00, "underpayment_amount")
    assert_money(payment["underpayment_penalty"], 300.00, "underpayment_penalty")
    assert payment["due_date"].startswith("2026-06-15T00:00:00")
    assert payment["is_timely"] is True

    registration = read_registration(ctx["reg_ca_id"])
    assert_money(registration["total_payments_received"], 16000.00,
                 "total_payments_received")
    assert_money(registration["unapplied_payment_balance"], 16000.00,
                 "unapplied_payment_balance")


def test_current_year_safe_harbor_diverges_from_the_prior_year_variant(api):
    """PRD 3.6: "Under `CURRENT_YEAR_90` the annual required amount is instead the registration's `current_year_estimated_tax` multiplied by 0.90 — ninety percent of the annualized current-year estimate — rounded to 2 decimal places, and `prior_year_tax` is ignored entirely."
    PRD 3.6: "Two registrations holding identical `prior_year_tax`, identical `current_year_estimated_tax`, identical `estimated_installment_count` and identical remittance histories will therefore produce different figures purely because their `safe_harbor_basis` differs."

    Design: Difficulty/dual_variant_calc/prior_year_vs_current_year_safe_harbor_divergence
    """
    ctx = _twin_safe_harbor_registrations()

    ca_payment = validate_success(api.create_payment(ctx["reg_ca_id"], {
        "tax_year": 2026, "installment_number": 2, "amount": 8000.00,
        "paid_on_date": "2026-06-15T00:00:00Z",
        "expected_registration_version": read_registration(ctx["reg_ca_id"])["version"],
    }, CTRL), 201)
    ny_payment = validate_success(api.create_payment(ctx["reg_ny_id"], {
        "tax_year": 2026, "installment_number": 2, "amount": 8000.00,
        "paid_on_date": "2026-06-15T00:00:00Z",
        "expected_registration_version": read_registration(ctx["reg_ny_id"])["version"],
    }, CTRL), 201)

    assert_money(ny_payment["safe_harbor_required_amount"], 40500.00,
                 "CURRENT_YEAR_90 safe_harbor_required_amount")
    assert_money(ny_payment["underpayment_amount"], 24500.00, "underpayment_amount")
    assert_money(ny_payment["underpayment_penalty"], 1225.00, "underpayment_penalty")

    assert ny_payment["safe_harbor_required_amount"] != (
        ca_payment["safe_harbor_required_amount"]
    ), "Identical inputs under different safe-harbor bases must diverge"
    assert_money(ca_payment["safe_harbor_required_amount"], 22000.00,
                 "PRIOR_YEAR_110 safe_harbor_required_amount")


def test_installment_due_date_and_timeliness_follow_the_state_calendar(api):
    """PRD 3.6: "The installment's `due_date` is midnight UTC on the fifteenth day of the fourth, sixth, ninth or twelfth month of its own `tax_year`, according to whether its `installment_number` is 1, 2, 3 or 4 — the familiar April, June, September and December calendar. `is_timely` is true when `paid_on_date` is at or before that `due_date`, and false otherwise."
    PRD 3.6: "Under `PRIOR_YEAR_100` it is the registration's `prior_year_tax` multiplied by 1.00 and rounded to 2 decimal places."
    PRD 3.6: "Recording a remittance also increases the registration's `total_payments_received` and its `unapplied_payment_balance` by the remitted `amount`, and advances the registration's `version` by 1."

    Design: Corner/calculations/installment_due_date_and_timeliness_from_constants
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "Installment Group"},
        registration_overrides={"safe_harbor_basis": "PRIOR_YEAR_100",
                                "prior_year_tax": 60000,
                                "estimated_installment_count": 4},
    )

    payment = validate_success(api.create_payment(ctx["registration_id"], {
        "tax_year": 2026, "installment_number": 3, "amount": 12000.00,
        "paid_on_date": "2026-10-01T00:00:00Z",
        "expected_registration_version": read_registration(ctx["registration_id"])["version"],
    }, CTRL), 201)

    assert payment["due_date"].startswith("2026-09-15T00:00:00"), (
        f"Installment 3 of 2026 is due 2026-09-15, got {payment['due_date']}"
    )
    assert payment["is_timely"] is False
    assert_money(payment["safe_harbor_required_amount"], 45000.00,
                 "safe_harbor_required_amount")
    assert_money(payment["underpayment_amount"], 33000.00, "underpayment_amount")
    assert_money(payment["underpayment_penalty"], 1650.00, "underpayment_penalty")
    assert payment["status"] == "RECEIVED"
    assert payment["applied_filing_id"] is None

    registration = read_registration(ctx["registration_id"])
    assert_money(registration["total_payments_received"], 12000.00,
                 "total_payments_received")
    assert_money(registration["unapplied_payment_balance"], 12000.00,
                 "unapplied_payment_balance")


def test_second_remittance_in_an_occupied_installment_slot_is_refused(api):
    """PRD 3.6: "No two remittances may occupy the same installment slot: a second payment carrying a `registration_id`, `tax_year` and `installment_number` that already exist together is rejected with `ERR_DUPLICATE_INSTALLMENT`."

    Design: Corner/validations/duplicate_installment_number_returns_conflict
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "Dup Installment Group"},
        registration_overrides={"prior_year_tax": 40000},
    )
    record_payment(ctx["registration_id"], tax_year=2026, installment_number=1,
                   amount=8000.00, paid_on_date="2026-04-15T00:00:00Z")

    response = api.create_payment(ctx["registration_id"], {
        "tax_year": 2026, "installment_number": 1, "amount": 3000.00,
        "paid_on_date": "2026-04-20T00:00:00Z",
        "expected_registration_version": read_registration(ctx["registration_id"])["version"],
    }, CTRL)

    validate_error(response, ApiErrorId.ERR_DUPLICATE_INSTALLMENT.value)
    registration = read_registration(ctx["registration_id"])
    assert_money(registration["total_payments_received"], 8000.00,
                 "total_payments_received")
    assert_money(registration["unapplied_payment_balance"], 8000.00,
                 "unapplied_payment_balance")
    rows, _ = validate_paginated(api.list_payments(AUD, {
        "registration_id": ctx["registration_id"], "limit": 10, "offset": 0,
    }))
    assert len(rows) == 1


def test_second_remittance_on_a_stale_registration_version_is_rejected(api):
    """PRD 2.8: "Recording an estimated-tax installment against a state registration requires `expected_registration_version` in the request body, likewise non-optional, carrying the `version` of the target `StateRegistration` as the caller last observed it. A mismatch with the registration's current `version` is rejected with `ERR_STALE_REGISTRATION_VERSION` (HTTP 412) and no payment row is written."
    PRD 3.6: "Under `PRIOR_YEAR_110` it is `prior_year_tax` multiplied by 1.10 and rounded to 2 decimal places — the ten-percent uplift larger states impose on bigger taxpayers."

    Design: Corner/cross_cutting_complexity_layers/stale_registration_version_rejects_second_payment
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "OCC Payment Group"},
        registration_overrides={"safe_harbor_basis": "PRIOR_YEAR_110",
                                "prior_year_tax": 40000},
    )
    observed = read_registration(ctx["registration_id"])["version"]

    validate_success(api.create_payment(ctx["registration_id"], {
        "tax_year": 2026, "installment_number": 1, "amount": 8000.00,
        "paid_on_date": "2026-04-15T00:00:00Z",
        "expected_registration_version": observed,
    }, CTRL), 201)

    stale = api.create_payment(ctx["registration_id"], {
        "tax_year": 2026, "installment_number": 2, "amount": 8000.00,
        "paid_on_date": "2026-06-15T00:00:00Z",
        "expected_registration_version": observed,
    }, CTRL)
    validate_error(stale, ApiErrorId.ERR_STALE_REGISTRATION_VERSION.value)
    assert_money(read_registration(ctx["registration_id"])["total_payments_received"],
                 8000.00, "total_payments_received after the rejected write")

    retried = validate_success(api.create_payment(ctx["registration_id"], {
        "tax_year": 2026, "installment_number": 2, "amount": 8000.00,
        "paid_on_date": "2026-06-15T00:00:00Z",
        "expected_registration_version": read_registration(ctx["registration_id"])["version"],
    }, CTRL), 201)
    assert_money(retried["safe_harbor_required_amount"], 22000.00,
                 "safe_harbor_required_amount")
    assert_money(retried["underpayment_amount"], 6000.00, "underpayment_amount")
    assert_money(retried["underpayment_penalty"], 300.00, "underpayment_penalty")
    assert_money(read_registration(ctx["registration_id"])["total_payments_received"],
                 16000.00, "total_payments_received at the end")


def test_detaching_a_remittance_that_was_never_applied_is_refused(api):
    """PRD 3.6: "Detaching is the exact compensating action. A `Controller` or `TaxManager` supplies a `reason`; the payment moves `APPLIED → UNAPPLIED`, `applied_filing_id` is cleared to null, the registration's `unapplied_payment_balance` increases by the payment's `amount`, the return's `estimated_credits_applied` decreases by that amount, and `balance_due` and `payment_status` are recomputed."
    PRD 2.11: "13. The remittance's `status` is a legal source state (`ERR_INVALID_PAYMENT_STATE`)."

    Design: Corner/endpoints/unapply_on_unapplied_payment_returns_invalid_payment_state
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "Unapply Group"},
        registration_overrides={"prior_year_tax": 40000},
    )
    payment = record_payment(ctx["registration_id"], tax_year=2026,
                             installment_number=1, amount=8000.00,
                             paid_on_date="2026-04-15T00:00:00Z")

    response = api.unapply_payment(
        payment["id"], {"reason": "nothing to detach"}, CTRL
    )

    validate_error(response, ApiErrorId.ERR_INVALID_PAYMENT_STATE.value)
    assert read_payment(payment["id"])["status"] == "RECEIVED"
    registration = read_registration(ctx["registration_id"])
    assert_money(registration["unapplied_payment_balance"], 8000.00,
                 "unapplied_payment_balance")
    assert_money(registration["total_payments_received"], 8000.00,
                 "total_payments_received")


def test_remittance_may_not_be_applied_to_another_states_return(api):
    """PRD 3.6: "Application is refused unless the target return belongs to the same registration as the payment — otherwise `ERR_FILING_REGISTRATION_MISMATCH` — and unless the target return's `tax_year` equals the payment's `tax_year` — otherwise `ERR_PAYMENT_TAX_YEAR_MISMATCH`."

    Design: Corner/validations/payment_applied_to_filing_of_other_registration_returns_error
    """
    ctx = setup_bare_registration(group_overrides={"name": "Mismatch Group"})
    reg_ny = create_registration(
        ctx["group_id"], state_code="NY", factor_formula="SINGLE_SALES_FACTOR",
        tax_rate=0.065, throwback_rule="NONE", service_sourcing_rule="MARKET_BASED",
    )
    ny_filing = create_filing(
        reg_ny["id"], tax_year=2026, filing_basis="COMBINED_UNITARY",
        federal_taxable_income=1000000,
    )
    payment = record_payment(ctx["registration_id"], tax_year=2026,
                             installment_number=1, amount=8000.00,
                             paid_on_date="2026-04-15T00:00:00Z")

    response = api.apply_payment(payment["id"], {"filing_id": ny_filing["id"]}, CTRL)

    validate_error(response, ApiErrorId.ERR_FILING_REGISTRATION_MISMATCH.value)
    reread = read_payment(payment["id"])
    assert reread["status"] == "RECEIVED"
    assert reread["applied_filing_id"] is None
    assert read_filing(ny_filing["id"])["estimated_credits_applied"] == 0


def test_remittance_may_not_be_applied_to_a_return_of_another_tax_year(api):
    """PRD 3.6: "Application is refused unless the target return belongs to the same registration as the payment — otherwise `ERR_FILING_REGISTRATION_MISMATCH` — and unless the target return's `tax_year` equals the payment's `tax_year` — otherwise `ERR_PAYMENT_TAX_YEAR_MISMATCH`."

    Design: Corner/validations/payment_applied_to_filing_of_other_tax_year_returns_error
    """
    ctx = setup_filed_filing()
    payment = record_payment(ctx["registration_id"], tax_year=2025,
                             installment_number=1, amount=5000.00,
                             paid_on_date="2025-04-15T00:00:00Z")

    response = api.apply_payment(payment["id"], {"filing_id": ctx["filing_id"]}, CTRL)

    error = validate_error(response, ApiErrorId.ERR_PAYMENT_TAX_YEAR_MISMATCH.value)
    assert error["error_id"] != ApiErrorId.ERR_FILING_REGISTRATION_MISMATCH.value, (
        "Both rows share the CA registration, so only the tax-year rule can fail"
    )
    assert read_payment(payment["id"])["status"] == "RECEIVED"
    assert_money(read_filing(ctx["filing_id"])["balance_due"], 18411.96, "balance_due")


def test_applying_a_remittance_moves_the_settlement_axis_only(api):
    """PRD 3.6: "Applying it points it at a return: the caller supplies the target `filing_id`, the payment moves `RECEIVED → APPLIED` (or `UNAPPLIED → APPLIED` if it had been detached earlier), `applied_filing_id` is set, the registration's `unapplied_payment_balance` decreases by the payment's `amount` while `total_payments_received` stays untouched, the return's `estimated_credits_applied` increases by that amount, and the return's `balance_due` and `payment_status` are recomputed."
    PRD 3.5: "A negative `balance_due` yields `OVERPAID`. A `balance_due` of exactly zero yields `PAID`. A positive `balance_due` yields `PARTIALLY_PAID` when `estimated_credits_applied` is greater than zero, and `UNPAID` when `estimated_credits_applied` is zero."

    Design: Difficulty/non_linear_state_machine/filing_parallel_axes_move_independently
    """
    ctx = setup_filed_filing()
    payment = record_payment(ctx["registration_id"], tax_year=2026,
                             installment_number=1, amount=10000.00,
                             paid_on_date="2026-04-15T00:00:00Z")

    validate_success(api.apply_payment(payment["id"], {"filing_id": ctx["filing_id"]}, CTRL))

    filing = read_filing(ctx["filing_id"])
    assert_money(filing["estimated_credits_applied"], 10000.00,
                 "estimated_credits_applied")
    assert_money(filing["balance_due"], 8411.96, "balance_due")
    assert filing["payment_status"] == "PARTIALLY_PAID"
    assert filing["preparation_status"] == "FILED", (
        "The preparation axis is untouched by movement on the settlement axis"
    )
    assert_money(read_registration(ctx["registration_id"])["total_payments_received"],
                 10000.00, "total_payments_received")


def test_detaching_a_remittance_returns_the_settlement_axis_to_unpaid(api):
    """PRD 3.6: "Detaching is the exact compensating action. A `Controller` or `TaxManager` supplies a `reason`; the payment moves `APPLIED → UNAPPLIED`, `applied_filing_id` is cleared to null, the registration's `unapplied_payment_balance` increases by the payment's `amount`, the return's `estimated_credits_applied` decreases by that amount, and `balance_due` and `payment_status` are recomputed."
    PRD 3.6: "Across an apply-and-detach round trip the registration's `total_payments_received` is invariant — it counts money received by the state, not money allocated by the practice."

    Design: Difficulty/non_linear_state_machine/filing_parallel_axes_move_independently
    """
    ctx = setup_filed_filing_with_applied_payment(amount=10000.00)

    detached = validate_success(api.unapply_payment(
        ctx["payment_id"], {"reason": "remittance re-allocated to the 2027 year"}, CTRL
    ))

    assert detached["status"] == "UNAPPLIED"
    assert detached["applied_filing_id"] is None

    filing = read_filing(ctx["filing_id"])
    assert_money(filing["estimated_credits_applied"], 0.00, "estimated_credits_applied")
    assert_money(filing["balance_due"], 18411.96, "balance_due")
    assert filing["payment_status"] == "UNPAID"
    assert filing["preparation_status"] == "FILED", (
        "The preparation axis is pinned at FILED throughout the round trip"
    )
    assert_money(read_registration(ctx["registration_id"])["total_payments_received"],
                 10000.00, "total_payments_received is invariant")


def test_refund_claim_marks_every_applied_remittance_refunded(api):
    """PRD 3.7: "On success the return moves `OVERPAID → REFUND_CLAIMED`, every estimated payment whose `applied_filing_id` names this return moves to `status` `REFUNDED` — leaving the registration's `total_payments_received` unchanged, since the state did receive that money — and the return's `version` advances by 1."
    PRD 3.5: "A negative `balance_due` yields `OVERPAID`. A `balance_due` of exactly zero yields `PAID`. A positive `balance_due` yields `PARTIALLY_PAID` when `estimated_credits_applied` is greater than zero, and `UNPAID` when `estimated_credits_applied` is zero."

    Design: Corner/state_machines/claim_refund_marks_applied_payments_refunded
    """
    ctx = setup_filed_filing_with_applied_payment(
        amount=10000.00, credits=REFUNDABLE_CREDIT,
        confirmation_number="CA-EFILE-2026-0031",
    )

    claim = read_credit_claim(ctx["credit_claims"][0]["id"])
    assert_money(claim["applied_amount"], 100000.00, "refundable applied_amount")
    assert_money(claim["carryforward_amount"], 0.00, "refundable carryforward_amount")

    before = read_filing(ctx["filing_id"])
    assert_money(before["balance_due"], -21588.04, "balance_due before the claim")
    assert before["payment_status"] == "OVERPAID"

    refunded = validate_success(api.claim_refund(
        ctx["filing_id"], {"refund_method": "ACH"},
        make_controller_headers("controller-01"),
    ))

    assert refunded["payment_status"] == "REFUND_CLAIMED"
    assert read_payment(ctx["payment_id"])["status"] == "REFUNDED"
    assert_money(read_registration(ctx["registration_id"])["total_payments_received"],
                 10000.00, "total_payments_received is unchanged by the refund claim")


def test_refund_claim_without_an_applied_remittance_is_refused(api):
    """PRD 3.7: "There must also be money to give back: at least one `EstimatedPayment` with `status` `APPLIED` must point at the return, or the request is rejected with `ERR_REFUND_NOT_AVAILABLE`."
    PRD 3.5: "For each claim in order: a non-refundable claim's `applied_amount` is the lesser of its `granted_amount` and the current remainder, while a refundable claim's `applied_amount` is its full `granted_amount`, because a refundable credit pays out past the liability; the remainder then becomes the greater of zero and the previous remainder less that claim's `applied_amount`; the claim's `carryforward_amount` becomes its `granted_amount` less its `applied_amount`; and its `expired_amount` starts at zero."

    Design: Corner/validations/refund_claim_without_applied_payments_returns_fiscal_error
    """
    ctx = setup_filed_filing(
        credits=REFUNDABLE_CREDIT, confirmation_number="CA-EFILE-2026-0041",
    )

    claim = read_credit_claim(ctx["credit_claims"][0]["id"])
    assert_money(claim["applied_amount"], 100000.00, "refundable applied_amount")
    assert claim["status"] == "FULLY_APPLIED"
    before = read_filing(ctx["filing_id"])
    assert_money(before["credits_applied_total"], 100000.00, "credits_applied_total")
    assert_money(before["balance_due"], -11588.04, "balance_due")
    assert before["payment_status"] == "OVERPAID"

    response = api.claim_refund(
        ctx["filing_id"], {"refund_method": "CHECK"},
        make_controller_headers("controller-01"),
    )

    validate_error(response, ApiErrorId.ERR_REFUND_NOT_AVAILABLE.value)
    assert read_filing(ctx["filing_id"])["payment_status"] == "OVERPAID"


def test_extension_prepayment_one_cent_short_is_rejected(api):
    """PRD 3.6: "The service stamps `requested_on_date` from the logical clock, records the return's `filing_id`, computes `required_prepayment` as the return's `tax_before_credits` multiplied by 0.90 — the ninety-percent prepayment nearly every state demands as the price of extra time — rounded half up to 2 decimal places, and initializes `status` to `REQUESTED` with `new_due_date` null and `state_confirmation` null. If `estimated_tax_paid` is less than `required_prepayment`, the request is rejected with `ERR_EXTENSION_PREPAYMENT_INSUFFICIENT`; the boundary is inclusive, so an `estimated_tax_paid` exactly equal to `required_prepayment` passes."

    Design: Difficulty/boundary_precision_check/extension_prepayment_boundary_exact_equality
    """
    ctx = setup_locked_filing()
    assert_money(read_filing(ctx["filing_id"])["tax_before_credits"], 88411.96,
                 "tax_before_credits")

    response = api.create_extension(ctx["filing_id"], {"estimated_tax_paid": 79570.75}, SA)

    validate_error(response, ApiErrorId.ERR_EXTENSION_PREPAYMENT_INSUFFICIENT.value)
    assert response.status_code == 422
    rows, _ = validate_paginated(
        api.list_filing_extensions(ctx["filing_id"], AUD, {"limit": 10, "offset": 0})
    )
    assert rows == [], "A rejected extension request writes no row"


def test_extension_prepayment_exactly_at_the_floor_is_granted(api):
    """PRD 3.6: "The service stamps `requested_on_date` from the logical clock, records the return's `filing_id`, computes `required_prepayment` as the return's `tax_before_credits` multiplied by 0.90 — the ninety-percent prepayment nearly every state demands as the price of extra time — rounded half up to 2 decimal places, and initializes `status` to `REQUESTED` with `new_due_date` null and `state_confirmation` null. If `estimated_tax_paid` is less than `required_prepayment`, the request is rejected with `ERR_EXTENSION_PREPAYMENT_INSUFFICIENT`; the boundary is inclusive, so an `estimated_tax_paid` exactly equal to `required_prepayment` passes."
    PRD 3.6: "On the `GRANTED` branch, the request moves `REQUESTED → GRANTED`, its `new_due_date` is set to the return's `original_due_date` advanced by the registration's `extension_months` months, **and** the return's `extended_due_date` is set to that same instant — which is what actually buys the filing deadline more room."

    Design: Difficulty/boundary_precision_check/extension_prepayment_boundary_exact_equality
    """
    ctx = setup_locked_filing()
    validate_error(
        api.create_extension(ctx["filing_id"], {"estimated_tax_paid": 79570.75}, SA),
        ApiErrorId.ERR_EXTENSION_PREPAYMENT_INSUFFICIENT.value,
    )

    extension = validate_success(
        api.create_extension(ctx["filing_id"], {"estimated_tax_paid": 79570.76}, SA), 201
    )
    assert_money(extension["required_prepayment"], 79570.76, "required_prepayment")
    assert extension["status"] == "REQUESTED"

    granted = validate_success(api.acknowledge_extension(
        extension["id"], {"decision": "GRANTED", "state_confirmation": "CA-EXT-2026-11"}, TM
    ))
    assert granted["status"] == "GRANTED"
    assert granted["new_due_date"].startswith("2027-10-15T00:00:00")
    assert read_filing(ctx["filing_id"])["extended_due_date"].startswith(
        "2027-10-15T00:00:00"
    )

    rows, _ = validate_paginated(
        api.list_filing_extensions(ctx["filing_id"], AUD, {"limit": 10, "offset": 0})
    )
    assert len(rows) == 1, "Only the accepted request became a row"


def test_denied_extension_leaves_the_return_due_date_untouched(api):
    """PRD 3.6: "On the `DENIED` branch, the request moves `REQUESTED → DENIED`, its `new_due_date` stays null, and the return's `extended_due_date` is left untouched."

    Design: Corner/state_machines/extension_denied_branch_leaves_due_date_untouched
    """
    ctx = setup_locked_filing()
    extension = validate_success(
        api.create_extension(ctx["filing_id"], {"estimated_tax_paid": 79570.76}, SA), 201
    )

    denied = validate_success(api.acknowledge_extension(
        extension["id"], {"decision": "DENIED", "state_confirmation": "CA-EXT-DENY-3"}, TM
    ))

    assert denied["status"] == "DENIED"
    assert denied["new_due_date"] is None
    assert_money(denied["required_prepayment"], 79570.76, "required_prepayment")

    filing = read_filing(ctx["filing_id"])
    assert filing["extended_due_date"] is None
    assert filing["original_due_date"].startswith("2027-04-15T00:00:00")


def test_extension_requested_after_the_original_due_date_is_refused(api):
    """PRD 3.6: "An extension may also only be requested while the return's `original_due_date` has not yet passed: a request handled strictly after that instant is rejected with `ERR_EXTENSION_WINDOW_CLOSED`, and a request handled exactly at it succeeds."

    Design: Corner/validations/extension_requested_after_window_returns_temporal_error
    """
    ctx = setup_locked_filing()
    set_clock("2027-04-16T00:00:00Z")

    response = api.create_extension(ctx["filing_id"], {"estimated_tax_paid": 79570.76}, SA)

    error = validate_error(response, ApiErrorId.ERR_EXTENSION_WINDOW_CLOSED.value)
    assert error["error_id"] != ApiErrorId.ERR_EXTENSION_PREPAYMENT_INSUFFICIENT.value, (
        "The declared prepayment is fully sufficient, so only the temporal rule can fail"
    )
    rows, _ = validate_paginated(
        api.list_filing_extensions(ctx["filing_id"], AUD, {"limit": 10, "offset": 0})
    )
    assert rows == []


def test_second_acknowledgement_of_an_extension_is_refused(api):
    """PRD 3.6: "Both branches are terminal and both advance the extension request's `version` by 1; only the `GRANTED` branch also advances the return's `version`."
    PRD 2.11: "12. The extension request's `status` is `REQUESTED` (`ERR_INVALID_EXTENSION_STATE`)."

    Design: Corner/endpoints/acknowledge_twice_returns_invalid_extension_state
    """
    ctx = setup_locked_filing()
    extension = validate_success(
        api.create_extension(ctx["filing_id"], {"estimated_tax_paid": 79570.76}, SA), 201
    )
    validate_success(api.acknowledge_extension(
        extension["id"], {"decision": "GRANTED", "state_confirmation": "CA-EXT-1"}, TM
    ))

    response = api.acknowledge_extension(
        extension["id"], {"decision": "DENIED", "state_confirmation": "CA-EXT-2"}, TM
    )

    validate_error(response, ApiErrorId.ERR_INVALID_EXTENSION_STATE.value)
    rows, _ = validate_paginated(
        api.list_filing_extensions(ctx["filing_id"], AUD, {"limit": 10, "offset": 0})
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "GRANTED"
    assert rows[0]["new_due_date"].startswith("2027-10-15T00:00:00")
    assert read_filing(ctx["filing_id"])["extended_due_date"].startswith(
        "2027-10-15T00:00:00"
    )
