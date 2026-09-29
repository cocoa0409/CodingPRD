"""Entity contracts: creation defaults, faithful reads, pagination envelopes,
entity-specific not-found codes, request-shape rejections, derived money fields,
server-stamped audit fields, append-only payload shape and cross-reference
integrity.

Every expected value below is fixed by a verbatim sentence of the PRD quoted in
the test's own docstring.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_ORIGIN,
    CREDIT_LIMITS,
    LATE_FEE_CENTS,
    MODEL_A,
    MODEL_B,
    NON_EXISTENT_UUID,
    assert_append_only_record,
    assert_carrier_account,
    assert_credit_application,
    assert_customer,
    assert_delinquency_event,
    assert_device_model,
    assert_device_unit,
    assert_diagnostic_report,
    assert_installment,
    assert_iso_equals,
    assert_loan,
    assert_loan_ledger_invariants,
    assert_payment_posting,
    assert_schedule_sums_to_principal,
    create_carrier_account_payload,
    create_credit_application_payload,
    create_device_model_payload,
    create_loan_payload,
    decide_application,
    enroll_customer,
    make_admin_headers,
    make_associate_headers,
    make_collections_headers,
    make_technician_headers,
    make_underwriter_headers,
    next_imei,
    payment_payload,
    publish_model,
    publish_target_model,
    read_customer,
    read_device_model,
    read_device_unit,
    read_diagnostic_reports,
    read_loan,
    register_carrier_account,
    set_clock,
    setup_active_loan,
    setup_trade_in_graded,
    submit_application,
    run_sweep,
    validate_error,
    validate_paginated,
    validate_success,
)


# =========================================================================
# Creation defaults
# =========================================================================
def test_enrolment_opens_with_active_financing_posture_defaults(api):
    """Enrolling a participant returns 201 and every computed posture field at the
    default the PRD declares, in the creation response body itself.

    PRD 3.1: "A new record opens with `status` `ACTIVE`, `financing_lock_reason` and
    `financing_locked_at` null, `credit_score_band` null because no credit decision has
    yet been taken, `credit_limit_cents` zero, and `default_strike_count` zero."
    PRD 3.1: "`completed_upgrade_count` is the count of that customer's upgrade requests
    whose `status` is `COMPLETED`, and `last_upgrade_completed_at` records the
    logical-clock instant of the most recent such completion, remaining null while
    `completed_upgrade_count` is zero."
    PRD 2.4: "Most resources additionally carry `updated_at` — refreshed to the current
    logical clock on every mutation — and `version`, an integer that begins at 1 when the
    row is minted and increments by exactly 1 on each mutation."

    Design: Corner/entities/create_customer_returns_active_financing_posture_defaults
    """
    payload = {
        "full_name": "Ada Nakamura",
        "email": "ada.nakamura@example.com",
        "mobile_number": "+15550100001",
    }
    created = validate_success(api.create_customer(payload, make_associate_headers()), 201)

    assert_customer(created)
    assert created["full_name"] == "Ada Nakamura"
    assert created["email"] == "ada.nakamura@example.com"
    assert created["mobile_number"] == "+15550100001"

    assert created["status"] == "ACTIVE", "a newly enrolled participant starts ACTIVE"
    assert created["financing_lock_reason"] is None
    assert created["financing_locked_at"] is None
    assert created["credit_score_band"] is None, "no credit decision has yet been taken"
    assert created["credit_limit_cents"] == 0
    assert created["outstanding_principal_cents"] == 0
    assert created["open_loan_count"] == 0
    assert created["completed_upgrade_count"] == 0
    assert created["last_upgrade_completed_at"] is None
    assert created["default_strike_count"] == 0
    assert created["version"] == 1, "version begins at 1 when the row is minted"
    assert created["id"] and created["created_at"] and created["updated_at"]


def test_customer_read_returns_the_decided_record_unchanged(api):
    """A customer read echoes the row the underwriting decision wrote — PRIME band and
    a 250,000-cent limit — and reading it twice changes nothing, because only a mutation
    advances `version` or refreshes `updated_at`.

    PRD 3.2: "The band resolves to a program credit limit — 250,000 cents for `PRIME`,
    150,000 cents for `NEAR_PRIME`, and 80,000 cents for `SUBPRIME` — and that figure is
    written to the application's `credit_limit_cents`."
    PRD 3.2: "In all three cases `underwriter_user_id` is set to the acting `X-User-ID`,
    `decided_at` is set to the logical clock, and the decision is written back onto the
    customer: the customer's own `credit_score_band` and `credit_limit_cents` are
    overwritten from this decision, so the most recent decision always governs the
    customer's headroom."
    PRD 2.4: "Most resources additionally carry `updated_at` — refreshed to the current
    logical clock on every mutation — and `version`, an integer that begins at 1 when the
    row is minted and increments by exactly 1 on each mutation."

    Design: Corner/entities/get_customer_returns_the_stored_record_unchanged
    """
    model = publish_target_model()
    customer = enroll_customer()
    application = submit_application(customer["id"], model["id"],
                                     requested_term_months=24,
                                     declared_down_payment_cents=0)
    decided = decide_application(application["id"], "PRIME")

    assert_credit_application(decided)
    assert decided["status"] == "APPROVED"
    assert decided["exposure_at_decision_cents"] == MODEL_A["retail_price_cents"]
    assert decided["exposure_at_decision_cents"] == 119_900
    assert decided["credit_limit_cents"] == CREDIT_LIMITS["PRIME"] == 250_000
    assert decided["decision_reason"] == "WITHIN_LIMIT"

    first = validate_success(api.get_customer(customer["id"], make_underwriter_headers()))
    assert_customer(first)
    assert first["id"] == customer["id"]
    assert first["credit_score_band"] == "PRIME"
    assert first["credit_limit_cents"] == 250_000
    assert first["status"] == "ACTIVE"
    assert first["outstanding_principal_cents"] == 0, "no loan has been originated yet"
    assert first["open_loan_count"] == 0

    second = validate_success(api.get_customer(customer["id"], make_underwriter_headers()))
    assert second == first, (
        "a read is not a mutation: the stored record comes back field-for-field "
        f"unchanged, got {second!r} then {first!r}")


# =========================================================================
# The pagination envelope and a real filter
# =========================================================================
def _publish_three_models():
    """Three catalog models, the third retired with `active` false."""
    model_a = publish_target_model()
    model_b = publish_model()
    model_c = publish_model(display_name="Handset C", retail_price_cents=59_900,
                            monthly_protection_premium_cents=799,
                            trade_in_base_credit_cents=20_000,
                            generation_year=2025, active=False)
    return model_a, model_b, model_c


def test_device_model_list_pagination_envelope_defaults_and_counts(api):
    """The catalog list reports the four pagination fields with the declared defaults
    (limit 10, offset 0), a `total_count` of every matching row and a `has_more` that is
    true only while rows remain beyond the page.

    PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, may not be
    smaller than 1, and may not be larger than 100."
    PRD 2.3: "`offset` controls the starting position: it defaults to 0 and may not be
    negative."
    PRD 2.3: "Each list response reports four pagination fields inside `meta`: `limit` and
    `offset` echo the effective values used for the page, `total_count` reports the number
    of rows matching the filter before pagination was applied, and `has_more` is true when
    rows remain beyond the current page."

    Design: Corner/entities/list_device_models_pagination_envelope_and_filter
    """
    _publish_three_models()

    rows, meta = validate_paginated(api.list_device_models(make_associate_headers()))
    assert meta["limit"] == 10, "limit defaults to 10 when omitted"
    assert meta["offset"] == 0, "offset defaults to 0"
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 3
    for row in rows:
        assert_device_model(row)

    rows, meta = validate_paginated(
        api.list_device_models(make_associate_headers(), params={"limit": 2, "offset": 0}))
    assert len(rows) == 2
    assert meta["limit"] == 2 and meta["offset"] == 0
    assert meta["total_count"] == 3, "total_count counts matching rows before pagination"
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api.list_device_models(make_associate_headers(), params={"limit": 2, "offset": 2}))
    assert len(rows) == 1
    assert meta["limit"] == 2 and meta["offset"] == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_device_model_list_active_filter_and_oversized_limit_rejected(api):
    """The catalog's `active` filter is an exact-match equality test that hides the
    retired model, and a `limit` of 101 is refused outright rather than clamped to 100.

    PRD 3.1: "Callers browsing the catalog may narrow the list by `active` and by
    `generation_year`."
    PRD 2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, or either
    parameter supplied as something other than an integer, is rejected with
    `ERR_INVALID_REQUEST`."
    PRD 3.1: "Two further attributes are optional at publication:
    `concurrent_reservation_capacity`, the number of upgrade fulfillment windows that may
    overlap on this model at once, which must be zero or greater and defaults to 2 when
    omitted; and `active`, which defaults to true."

    Design: Corner/entities/list_device_models_pagination_envelope_and_filter
    """
    model_a, model_b, model_c = _publish_three_models()

    rows, meta = validate_paginated(
        api.list_device_models(make_associate_headers(), params={"active": "true"}))
    assert meta["total_count"] == 2, "only the two live models match active=true"
    assert len(rows) == 2
    returned = {row["id"] for row in rows}
    assert model_c["id"] not in returned, "the retired model must not appear under active=true"
    assert returned == {model_a["id"], model_b["id"]}

    retired = read_device_model(model_c["id"])
    assert retired["active"] is False
    assert retired["concurrent_reservation_capacity"] == 2, (
        "concurrent_reservation_capacity defaults to 2 when omitted")
    assert retired["reserved_slot_count"] == 0

    validate_error(api.list_device_models(make_associate_headers(), params={"limit": 101}),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


# =========================================================================
# Entity-specific not-found codes
# =========================================================================
def test_unknown_path_ids_return_entity_specific_not_found_errors(api):
    """Each addressed collection answers a well-formed but unknown path id with its OWN
    404 identifier — eight distinct codes, never a shared or generic one.

    PRD 2.7: "Path identifiers are resolved left to right: a customer path segment that
    resolves to nothing yields `ERR_CUSTOMER_NOT_FOUND`, a device-model segment
    `ERR_DEVICE_MODEL_NOT_FOUND`, a credit-application segment
    `ERR_CREDIT_APPLICATION_NOT_FOUND`, a loan segment `ERR_LOAN_NOT_FOUND`, a device-unit
    segment `ERR_DEVICE_UNIT_NOT_FOUND`, an upgrade-request segment
    `ERR_UPGRADE_REQUEST_NOT_FOUND`, a trade-in segment `ERR_TRADE_IN_NOT_FOUND`, and a
    payment-posting segment `ERR_PAYMENT_POSTING_NOT_FOUND` — all 404."

    Design: Corner/entities/unknown_path_ids_return_entity_specific_not_found_errors
    """
    admin = make_admin_headers()
    missing = NON_EXISTENT_UUID

    cases = [
        (api.get_customer(missing, admin), ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value),
        (api.get_device_model(missing, admin), ApiErrorId.ERR_DEVICE_MODEL_NOT_FOUND.value),
        (api.get_credit_application(missing, admin),
         ApiErrorId.ERR_CREDIT_APPLICATION_NOT_FOUND.value),
        (api.get_loan(missing, admin), ApiErrorId.ERR_LOAN_NOT_FOUND.value),
        (api.get_device_unit(missing, admin), ApiErrorId.ERR_DEVICE_UNIT_NOT_FOUND.value),
        (api.get_upgrade_request(missing, admin),
         ApiErrorId.ERR_UPGRADE_REQUEST_NOT_FOUND.value),
        (api.get_trade_in(missing, admin), ApiErrorId.ERR_TRADE_IN_NOT_FOUND.value),
        (api.get_payment_posting(missing, admin),
         ApiErrorId.ERR_PAYMENT_POSTING_NOT_FOUND.value),
    ]
    for response, expected_error_id in cases:
        error = validate_error(response, expected_error_id)
        assert error["message"], f"{expected_error_id} must carry a human-readable message"


# =========================================================================
# Request shape: missing required inputs
# =========================================================================
def test_missing_required_input_fields_return_invalid_request(api):
    """Omitting a required input field is a request-shape violation reported as
    ERR_INVALID_REQUEST, and it fires before any referential check even when every id in
    the body is valid — nothing is persisted.

    PRD 2.7: "Every field the endpoint marks as required must be present; every enum field
    must carry a declared member; every integer cent field must be an integer of zero or
    greater; every ISO 8601 field must parse; every UUID field must be well-formed.
    Violations yield `ERR_INVALID_REQUEST` (400)."
    PRD 3.1: "A participant enters the program as a `Customer` record carrying three
    supplied attributes: `full_name`, the legal name of the person on the credit agreement;
    `email`, a contact address that must be non-empty and unique across all customers; and
    `mobile_number`, the contact mobile line."
    PRD 3.2: "The payload names the applicant's `customer_id` and the `device_model_id`
    being financed, states a `requested_term_months` that must be either 12 or 24, and may
    carry a `declared_down_payment_cents` figure, which defaults to zero when omitted."

    Design: Corner/entities/missing_required_input_fields_return_invalid_request
    """
    model = publish_model()
    customer = enroll_customer()

    # `email` omitted on enrolment.
    validate_error(
        api.create_customer({"full_name": "No Email", "mobile_number": "+15550100004"},
                            make_associate_headers()),
        ApiErrorId.ERR_INVALID_REQUEST.value)

    # `retail_price_cents` omitted on catalog publication.
    bad_model = create_device_model_payload(display_name="Handset X")
    bad_model.pop("retail_price_cents")
    validate_error(api.create_device_model(bad_model, make_admin_headers()),
                   ApiErrorId.ERR_INVALID_REQUEST.value)

    # `customer_id` omitted on application submission, with a real device_model_id.
    validate_error(
        api.create_credit_application(
            {"device_model_id": model["id"], "requested_term_months": 24},
            make_associate_headers()),
        ApiErrorId.ERR_INVALID_REQUEST.value)

    # `device_model_id` omitted on application submission, with a real customer_id.
    validate_error(
        api.create_credit_application(
            {"customer_id": customer["id"], "requested_term_months": 24},
            make_associate_headers()),
        ApiErrorId.ERR_INVALID_REQUEST.value)

    # Nothing was written by any of the four rejected calls.
    stored_customer = read_customer(customer["id"])
    assert stored_customer["id"] == customer["id"]
    _, model_meta = validate_paginated(api.list_device_models(make_associate_headers()))
    assert model_meta["total_count"] == 1, "the rejected publication persisted nothing"
    _, application_meta = validate_paginated(api.list_credit_applications(
        make_associate_headers(), params={"customer_id": customer["id"]}))
    assert application_meta["total_count"] == 0, (
        "no application row survives a request-shape rejection")


# =========================================================================
# Omitted optional inputs fall back to the declared defaults
# =========================================================================
def test_omitted_optional_model_and_carrier_inputs_apply_declared_defaults(api):
    """Publishing a model without `concurrent_reservation_capacity` or `active`, and
    registering a carrier account without `unlock_policy_days` or `port_freeze_flag`, lands
    the values the PRD names — 2, true, 60 and false — not null and not zero.

    PRD 3.1: "Two further attributes are optional at publication:
    `concurrent_reservation_capacity`, the number of upgrade fulfillment windows that may
    overlap on this model at once, which must be zero or greater and defaults to 2 when
    omitted; and `active`, which defaults to true."
    PRD 3.1: "Two optional attributes complete the record: `unlock_policy_days`, the
    carrier-specific minimum number of whole days that must elapse between a device's
    activation and an accepted unlock request, which must be zero or greater and defaults to
    60 when omitted; and `port_freeze_flag`, which defaults to false and, while true,
    prevents any handset from being activated on the account."
    PRD 3.1: "A fresh account opens with `activation_state` `PENDING`, `activated_at` null,
    and `active_device_imei` null."

    Design: Corner/entities/omitted_optional_inputs_apply_declared_defaults
    """
    model_payload = create_device_model_payload()
    assert "concurrent_reservation_capacity" not in model_payload
    assert "active" not in model_payload
    model = validate_success(api.create_device_model(model_payload, make_admin_headers()), 201)
    assert_device_model(model)
    assert model["concurrent_reservation_capacity"] == 2
    assert model["active"] is True
    assert model["reserved_slot_count"] == 0, "reserved_slot_count opens at zero"

    customer = enroll_customer()
    carrier_payload = create_carrier_account_payload(carrier_code="VERIZON")
    assert "unlock_policy_days" not in carrier_payload
    assert "port_freeze_flag" not in carrier_payload
    carrier = validate_success(api.create_carrier_account(
        customer["id"], carrier_payload, make_associate_headers()), 201)

    assert_carrier_account(carrier)
    assert carrier["customer_id"] == customer["id"]
    assert carrier["carrier_code"] == "VERIZON"
    assert carrier["unlock_policy_days"] == 60
    assert carrier["port_freeze_flag"] is False
    assert carrier["activation_state"] == "PENDING"
    assert carrier["activated_at"] is None
    assert carrier["active_device_imei"] is None


def test_omitted_declared_down_payment_defaults_to_zero_on_submission(api):
    """An application submitted without `declared_down_payment_cents` treats it as zero, so
    `requested_principal_cents` snapshots the model's full retail price, and every decision
    field opens empty.

    PRD 3.2: "The payload names the applicant's `customer_id` and the `device_model_id`
    being financed, states a `requested_term_months` that must be either 12 or 24, and may
    carry a `declared_down_payment_cents` figure, which defaults to zero when omitted."
    PRD 3.2: "At submission the application snapshots `requested_principal_cents` as the
    model's `retail_price_cents` less `declared_down_payment_cents`, and opens with `status`
    `SUBMITTED`."
    PRD 3.2: "Every decision field is empty at this point: `credit_score_band`,
    `decision_reason`, `underwriter_user_id` and `decided_at` are all null, while
    `credit_limit_cents`, `exposure_at_decision_cents`, `approved_principal_cents` and
    `conditional_down_payment_required_cents` are all zero."

    Design: Corner/entities/omitted_optional_inputs_apply_declared_defaults
    """
    model = publish_model()
    assert model["retail_price_cents"] == MODEL_B["retail_price_cents"] == 89_900
    customer = enroll_customer()

    payload = create_credit_application_payload(customer["id"], model["id"],
                                                requested_term_months=24)
    assert "declared_down_payment_cents" not in payload
    application = validate_success(
        api.create_credit_application(payload, make_associate_headers()), 201)

    assert_credit_application(application)
    assert application["declared_down_payment_cents"] == 0
    assert application["requested_principal_cents"] == 89_900, (
        "requested_principal_cents is retail_price_cents less a zero declared down payment")
    assert application["status"] == "SUBMITTED"
    assert application["credit_score_band"] is None
    assert application["decision_reason"] is None
    assert application["underwriter_user_id"] is None
    assert application["decided_at"] is None
    assert application["credit_limit_cents"] == 0
    assert application["exposure_at_decision_cents"] == 0
    assert application["approved_principal_cents"] == 0
    assert application["conditional_down_payment_required_cents"] == 0


# =========================================================================
# Derived money fields on the originated loan and its schedule
# =========================================================================
def _originate_model_a_loan_with_down_payment(api, down_payment_cents=20_000):
    """A PRIME borrower on the 119,900-cent model, originated with the declared down
    payment actually collected at the counter. Returns (application, loan)."""
    model = publish_target_model()
    customer = enroll_customer()
    application = submit_application(customer["id"], model["id"], requested_term_months=24,
                                     declared_down_payment_cents=int(down_payment_cents))
    application = decide_application(application["id"], "PRIME")
    loan = validate_success(api.create_loan(
        create_loan_payload(application["id"], imei=next_imei(),
                            down_payment_cents=int(down_payment_cents)),
        make_associate_headers()), 201)
    # Re-read the application: origination closes by advancing it to ORIGINATED, so the
    # decision response captured above is stale by the time the loan exists.
    application = validate_success(
        api.get_credit_application(application["id"], make_associate_headers()))
    return customer, model, application, loan


def test_loan_computed_money_fields_derive_from_model_and_down_payment(api):
    """Every money figure on a freshly originated loan is derived from the model and the
    collected down payment rather than echoed from input: 99,900 principal, a 1,199
    snapshotted premium, 28,776 premium total, a 5,362 monthly installment and a 128,676
    opening obligation balance.

    PRD 3.3: "The financed `principal_cents` is therefore simply the model's
    `retail_price_cents` less the collected `down_payment_cents`."
    PRD 3.3: "`monthly_protection_premium_cents` is a **snapshot** of the model's
    `monthly_protection_premium_cents` taken at this instant; later catalog edits never reach
    back and change a booked loan's premium."
    PRD 3.3: "`premium_total_cents` is the monthly premium multiplied by `term_months`."
    PRD 3.3: "`monthly_installment_cents` is the base monthly principal component (derived
    just below) plus the monthly premium, which is what the customer is told they will pay
    each month — with the caveat that the final installment may differ from it by the
    principal residual."
    PRD 3.3: "`obligation_balance_cents`, the loan's headline outstanding figure, is defined
    generally as the unpaid principal (`principal_cents` less `paid_principal_cents`) plus
    the unpaid premium (`premium_total_cents` less `paid_premium_cents`) plus
    `outstanding_late_fee_cents`; at origination, with nothing paid and no fees, that reduces
    to `principal_cents` plus `premium_total_cents`."
    PRD 3.3: "For the same reason `rolled_over_balance_cents` and `origination_fee_cents` are
    both zero — neither a carried balance nor a tiered fee arises outside of an upgrade."

    Design: Corner/entities/loan_computed_fields_derive_from_model_and_down_payment
    """
    customer, model, application, loan = _originate_model_a_loan_with_down_payment(api)

    assert application["requested_principal_cents"] == 99_900
    assert application["approved_principal_cents"] == 99_900
    assert application["status"] == "ORIGINATED", (
        "origination closes by advancing the source application to ORIGINATED")

    assert_loan(loan)
    assert_loan_ledger_invariants(loan)
    assert loan["principal_cents"] == 99_900
    assert loan["down_payment_cents"] == 20_000
    assert loan["rolled_over_balance_cents"] == 0
    assert loan["origination_fee_cents"] == 0
    assert loan["term_months"] == 24
    assert loan["monthly_protection_premium_cents"] == 1_199
    assert loan["premium_total_cents"] == 28_776, "1,199 multiplied by a 24-month term"
    assert loan["monthly_installment_cents"] == 5_362, "4,163 base principal plus 1,199 premium"
    assert loan["obligation_balance_cents"] == 128_676, "99,900 principal plus 28,776 premium"
    assert loan["predecessor_loan_id"] is None
    assert loan["closure_reason"] is None
    assert loan["paid_principal_cents"] == 0
    assert loan["paid_premium_cents"] == 0
    assert loan["outstanding_late_fee_cents"] == 0
    assert loan["paid_installment_count"] == 0
    assert loan["status"] == "ACTIVE"
    assert loan["delinquency_state"] == "CURRENT"
    assert loan["days_past_due"] == 0
    assert loan["protection_coverage_status"] == "ACTIVE"
    assert loan["upgrade_hold_flag"] is False

    borrower = read_customer(customer["id"])
    assert borrower["outstanding_principal_cents"] == 99_900
    assert borrower["open_loan_count"] == 1


def test_loan_schedule_components_and_due_dates_are_derived(api):
    """The whole 24-row ladder is written in one shot: a 4,163-cent base principal
    component on installment 1, the 4,151-cent residual on installment 24 only, a flat
    1,199-cent premium on every row, and due dates one calendar month apart.

    PRD 3.3: "First a base principal component is derived: the loan's `principal_cents`
    divided by its `term_months`, rounded half up to whole cents."
    PRD 3.3: "For the last installment — and only the last — `principal_component_cents` is
    instead the loan's `principal_cents` less the base figure multiplied by one fewer than
    `term_months`; this residual guarantees that the principal components sum to
    `principal_cents` exactly, and it means the final installment's principal share may come
    out either smaller or larger than the base figure."
    PRD 3.3: "`premium_component_cents` is the loan's snapshotted
    `monthly_protection_premium_cents` on every installment without exception and is never
    rounded, being a flat per-month constant."
    PRD 3.3: "`due_date` is the loan's `origination_date` advanced by as many whole calendar
    months as the installment's `installment_number`, normalised to `00:00:00.000Z`,
    preserving the day-of-month and clamping to the last day of the target month where that
    day-of-month does not exist."

    Design: Corner/entities/loan_computed_fields_derive_from_model_and_down_payment
    """
    _, _, _, loan = _originate_model_a_loan_with_down_payment(api)

    rows, meta = validate_paginated(api.list_installments(
        loan["id"], make_associate_headers(), params={"limit": 100}))
    assert meta["total_count"] == 24, "the whole ladder is created in one shot"
    schedule = sorted(rows, key=lambda row: row["installment_number"])
    assert_schedule_sums_to_principal(schedule, loan)

    for row in schedule:
        assert_installment(row)
        assert row["premium_component_cents"] == 1_199, (
            "the premium component is a flat per-month constant")
        assert row["status"] == "SCHEDULED"
        assert row["paid_principal_cents"] == 0 and row["paid_premium_cents"] == 0
        assert row["paid_amount_cents"] == 0 and row["late_fee_cents"] == 0
        assert row["late_fee_paid_cents"] == 0
        assert row["late_fee_assessed"] is False
        assert row["paid_at"] is None and row["void_reason"] is None

    first = schedule[0]
    assert first["installment_number"] == 1
    assert first["principal_component_cents"] == 4_163, "round_half_up(99900 / 24)"
    assert first["amount_due_cents"] == 5_362
    assert_iso_equals(first["due_date"], "2026-09-01T00:00:00Z", "installment 1 due_date")

    last = schedule[-1]
    assert last["installment_number"] == 24
    assert last["principal_component_cents"] == 4_151, "99900 less 4163 multiplied by 23"
    assert last["amount_due_cents"] == 5_350
    assert_iso_equals(last["due_date"], "2028-08-01T00:00:00Z", "installment 24 due_date")

    for row in schedule[1:-1]:
        assert row["principal_component_cents"] == 4_163, (
            "the residual never lands anywhere but the last installment")


# =========================================================================
# Server-stamped identity, audit and temporal fields
# =========================================================================
def test_origination_stamps_the_logical_clock_and_mints_the_handset(api):
    """Neither temporal anchor on a loan comes from an input field: a loan minted while the
    logical clock reads 2026-08-01T00:00:00Z carries that instant as `origination_date` and
    2027-06-27T00:00:00Z (330 days later) as `upgrade_window_opens_at`, is minted at version
    1, and brings its own system-created handset with it.

    PRD 2.4: "Every persisted resource carries an `id` that is a server-minted UUID."
    PRD 2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three
    fractional digits, recorded from the logical clock at the moment the row was written."
    PRD 3.3: "Two timestamps anchor everything temporal about the loan: `origination_date` is
    set to the current logical clock, and `upgrade_window_opens_at` is set to 330 days after
    it — very nearly eleven months, deliberately just short of a year, so that an annual
    upgrade becomes admissible shortly before the loan's first anniversary."
    PRD 3.3: "It opens `UNACTIVATED` in `activation_status`, `LOCKED` in `unlock_status`, and
    `WITH_CUSTOMER` in `possession_status`, with `carrier_account_id`, `activated_at`,
    `unlock_requested_at`, `unlocked_at` and `returned_at` all null."

    Design: Corner/entities/system_fields_are_server_stamped_at_origination_and_posting
    """
    ctx = setup_active_loan()
    loan = ctx["loan"]

    assert_loan(loan)
    assert loan["version"] == 1, "origination mints the loan at version 1"
    assert_iso_equals(loan["created_at"], CLOCK_ORIGIN, "InstallmentLoan.created_at")
    assert_iso_equals(loan["updated_at"], CLOCK_ORIGIN, "InstallmentLoan.updated_at")
    assert_iso_equals(loan["origination_date"], CLOCK_ORIGIN, "origination_date")
    assert_iso_equals(loan["upgrade_window_opens_at"], "2027-06-27T00:00:00Z",
                      "upgrade_window_opens_at is 2026-08-01 advanced by 330 days")
    assert loan["id"] != ctx["application"]["id"], "the loan is a distinct server-minted row"

    rows, meta = validate_paginated(api.list_device_units(
        make_associate_headers(), params={"loan_id": loan["id"]}))
    assert meta["total_count"] == 1, "origination mints exactly one DeviceUnit for the loan"
    device = rows[0]
    assert_device_unit(device)
    assert device["loan_id"] == loan["id"]
    assert device["device_model_id"] == ctx["model"]["id"]
    assert device["imei"] == ctx["device"]["imei"]
    assert device["activation_status"] == "UNACTIVATED"
    assert device["unlock_status"] == "LOCKED"
    assert device["possession_status"] == "WITH_CUSTOMER"
    for field in ("carrier_account_id", "activated_at", "unlock_requested_at",
                  "unlocked_at", "returned_at"):
        assert device[field] is None, f"a freshly minted handset has {field} null"
    assert_iso_equals(device["created_at"], CLOCK_ORIGIN, "DeviceUnit.created_at")
    assert device["version"] == 1


def test_payment_posting_stamps_posted_at_from_the_moved_logical_clock(api):
    """`posted_at` is read off the logical clock at the moment of allocation rather than off
    wall time or the loan's origination date: after the clock is advanced to 2026-09-15 the
    posting carries that instant, and the loan it landed on advances to version 2.

    PRD 3.5: "`reverses_posting_id` is null on both `PAYMENT` and `PAYOFF`, and the posting
    itself records the loan it landed on as `loan_id`, together with `posted_at`, the
    logical-clock instant the allocation was applied."
    PRD 2.6: "Six do, each by exactly 1: originating the loan (which mints it at `version` 1);
    posting money to it under any `posting_type`, including a `REVERSAL`; pricing a payoff
    quote against it; opening an upgrade request against it (the same call that sets
    `upgrade_hold_flag`); completing an upgrade out of it (which drives the loan to
    `ROLLED_OVER`); and cancelling the program on it (which drives the loan to `PAID_OFF`)."

    Design: Corner/entities/system_fields_are_server_stamped_at_origination_and_posting
    """
    ctx = setup_active_loan()
    assert ctx["loan"]["version"] == 1

    set_clock("2026-09-15T00:00:00Z")
    posting = validate_success(api.create_payment(
        ctx["loan_id"], payment_payload(4_745), ctx["customer_headers"]), 201)

    assert_payment_posting(posting)
    assert posting["loan_id"] == ctx["loan_id"]
    assert posting["posting_type"] == "PAYMENT"
    assert posting["amount_cents"] == 4_745
    assert posting["reverses_posting_id"] is None
    assert_iso_equals(posting["posted_at"], "2026-09-15T00:00:00Z", "posted_at")
    assert_iso_equals(posting["created_at"], "2026-09-15T00:00:00Z",
                      "PaymentPosting.created_at")

    reread = validate_success(api.get_payment_posting(posting["id"], make_admin_headers()))
    assert reread["id"] == posting["id"]
    assert_iso_equals(reread["posted_at"], "2026-09-15T00:00:00Z", "posted_at on re-read")

    loan = read_loan(ctx["loan_id"])
    assert loan["version"] == 2, "posting money advances the loan's version by exactly 1"
    assert_iso_equals(loan["updated_at"], "2026-09-15T00:00:00Z",
                      "updated_at is refreshed to the current logical clock on every mutation")


# =========================================================================
# Values of the right JSON type but outside the declared domain
# =========================================================================
def test_invalid_enum_and_out_of_range_inputs_are_rejected(api):
    """A term of 18 months, a carrier code of SPRINT and a retail price of -1 are all
    well-typed JSON, and all three are still refused as request-shape violations with
    nothing persisted.

    PRD 2.7: "**Request shape.** Every field the endpoint marks as required must be present;
    every enum field must carry a declared member; every integer cent field must be an integer
    of zero or greater; every ISO 8601 field must parse; every UUID field must be well-formed."
    PRD 3.2: "The payload names the applicant's `customer_id` and the `device_model_id` being
    financed, states a `requested_term_months` that must be either 12 or 24, and may carry a
    `declared_down_payment_cents` figure, which defaults to zero when omitted."
    PRD 3.1: "Registration supplies a `carrier_code`, which must be one of `VERIZON`, `ATT`,
    `TMOBILE` or `ESIM_MVNO`, and an `account_number` that must be unique across all carrier
    accounts — a collision is `ERR_DUPLICATE_IDENTIFIER`."

    Design: Corner/entities/invalid_enum_and_out_of_range_inputs_are_rejected
    """
    model = publish_model()
    customer = enroll_customer()

    validate_error(api.create_credit_application(
        create_credit_application_payload(customer["id"], model["id"],
                                          requested_term_months=18,
                                          declared_down_payment_cents=0),
        make_associate_headers()), ApiErrorId.ERR_INVALID_REQUEST.value)

    validate_error(api.create_carrier_account(
        customer["id"], create_carrier_account_payload(carrier_code="SPRINT"),
        make_associate_headers()), ApiErrorId.ERR_INVALID_REQUEST.value)

    validate_error(api.create_device_model(
        create_device_model_payload(sku="MDL-NEG", display_name="Handset Neg",
                                    retail_price_cents=-1),
        make_admin_headers()), ApiErrorId.ERR_INVALID_REQUEST.value)

    _, applications_meta = validate_paginated(api.list_credit_applications(
        make_associate_headers(), params={"customer_id": customer["id"]}))
    assert applications_meta["total_count"] == 0, "the rejected application was not persisted"

    _, carriers_meta = validate_paginated(api.list_carrier_accounts(
        customer["id"], make_associate_headers()))
    assert carriers_meta["total_count"] == 0, "the rejected carrier account was not persisted"

    rows, models_meta = validate_paginated(api.list_device_models(make_admin_headers()))
    assert models_meta["total_count"] == 1, "only the valid model survives"
    assert [row["id"] for row in rows] == [model["id"]]


# =========================================================================
# The three append-only records carry only id and created_at
# =========================================================================
def test_payment_posting_and_delinquency_events_carry_no_version_or_updated_at(api):
    """A posting and every delinquency event the sweep appends expose their own fields plus
    `id` and `created_at`, and neither `updated_at` nor `version` appears anywhere in either
    payload — the ledger is corrected by appending, never by editing.

    PRD 2.4: "Three resources are append-only records of something that already happened and
    therefore carry **only** `id` and `created_at`: a `PaymentPosting`, a `DiagnosticReport`,
    and a `DelinquencyEvent`."
    PRD 2.4: "For those three, both `updated_at` and `version` are absent from the payload
    entirely; once written they are never edited, and a correction is expressed by writing a
    new row rather than by revising an old one."
    PRD 3.5: "`allocated_late_fee_cents`, `allocated_premium_cents` and
    `allocated_principal_cents` are the three totals it consumed across all buckets;
    `installments_satisfied_count` is the number of installments this single posting drove all
    the way to `PAID`; and `obligation_balance_after_cents` captures the loan's
    `obligation_balance_cents` immediately after the allocation was applied."
    PRD 3.6: "Every assessment appends a `DelinquencyEvent` of `event_type`
    `LATE_FEE_ASSESSED` carrying the assessed fee in its `amount_cents`."

    Design: Corner/entities/append_only_entities_carry_no_version_or_updated_at
    """
    ctx = setup_active_loan()
    posting = validate_success(api.create_payment(
        ctx["loan_id"], payment_payload(4_745), ctx["customer_headers"]), 201)

    assert_payment_posting(posting)
    assert_append_only_record(posting, "PaymentPosting")
    assert "version" not in posting and "updated_at" not in posting
    for field in ("id", "loan_id", "posting_type", "amount_cents", "allocated_late_fee_cents",
                  "allocated_premium_cents", "allocated_principal_cents", "overpayment_cents",
                  "installments_satisfied_count", "obligation_balance_after_cents",
                  "posted_at", "created_at"):
        assert field in posting, f"a PaymentPosting response must carry {field}"
    assert posting["amount_cents"] == 4_745
    assert posting["installments_satisfied_count"] == 1, (
        "the 4,745-cent remittance drove installment 1 all the way to PAID")
    assert posting["obligation_balance_after_cents"] == 109_131, "113,876 less 4,745"
    assert posting["allocated_late_fee_cents"] == 0 and posting["overpayment_cents"] == 0
    assert (posting["allocated_principal_cents"]
            + posting["allocated_premium_cents"]) == 4_745

    set_clock("2026-10-12T00:00:00Z")
    run_sweep()

    all_rows, all_meta = validate_paginated(api.list_delinquency_events(
        ctx["loan_id"], make_collections_headers(), params={"limit": 100}))
    assert all_meta["total_count"] >= 2, "the sweep appended both a fee and a label movement"
    for row in all_rows:
        assert_delinquency_event(row)
        assert_append_only_record(row, "DelinquencyEvent")
        assert "version" not in row and "updated_at" not in row
        assert row["loan_id"] == ctx["loan_id"]

    fee_rows, fee_meta = validate_paginated(api.list_delinquency_events(
        ctx["loan_id"], make_collections_headers(),
        params={"event_type": "LATE_FEE_ASSESSED"}))
    assert fee_meta["total_count"] == 1
    assert fee_rows[0]["amount_cents"] == LATE_FEE_CENTS
    assert_iso_equals(fee_rows[0]["occurred_at"], "2026-10-12T00:00:00Z",
                      "LATE_FEE_ASSESSED.occurred_at")
    assert fee_rows[0]["from_state"] is None and fee_rows[0]["to_state"] is None, (
        "both of which are null for `LATE_FEE_ASSESSED`")

    moved_rows, moved_meta = validate_paginated(api.list_delinquency_events(
        ctx["loan_id"], make_collections_headers(),
        params={"event_type": "DELINQUENCY_ENTERED"}))
    assert moved_meta["total_count"] == 1
    assert moved_rows[0]["from_state"] == "CURRENT", (
        "a loan whose grace window elapsed without a sweep moves CURRENT to DELINQUENT directly")
    assert moved_rows[0]["to_state"] == "DELINQUENT"
    assert moved_rows[0]["days_past_due_at_event"] == 11
    assert moved_rows[0]["amount_cents"] == 0


def test_diagnostic_reports_carry_no_version_or_updated_at(api):
    """The bench report a technician files is an append-only record too: it carries its own
    grading fields plus `id` and `created_at`, with no `updated_at` and no `version`.

    PRD 2.4: "Three resources are append-only records of something that already happened and
    therefore carry **only** `id` and `created_at`: a `PaymentPosting`, a `DiagnosticReport`,
    and a `DelinquencyEvent`."
    PRD 2.4: "For those three, both `updated_at` and `version` are absent from the payload
    entirely; once written they are never edited, and a correction is expressed by writing a
    new row rather than by revising an old one."

    Design: Corner/entities/append_only_entities_carry_no_version_or_updated_at
    """
    ctx = setup_trade_in_graded()

    filed = ctx["report"]
    assert_diagnostic_report(filed)
    assert_append_only_record(filed, "DiagnosticReport")
    assert "version" not in filed and "updated_at" not in filed

    reports = read_diagnostic_reports(ctx["trade_in_id"], make_technician_headers())
    assert len(reports) == 1, "one grading has been filed against the trade-in"
    stored = reports[0]
    assert_diagnostic_report(stored)
    assert_append_only_record(stored, "DiagnosticReport")
    assert "version" not in stored and "updated_at" not in stored
    assert stored["id"] == filed["id"]
    assert stored["trade_in_id"] == ctx["trade_in_id"]
    assert stored["sequence_no"] == 1
    assert stored["technician_user_id"] == "u-tech-1"


# =========================================================================
# Foreign keys are checked for owner agreement, not merely for existence
# =========================================================================
def test_activation_with_another_customers_carrier_account_is_refused(api):
    """A carrier account that exists but belongs to a different customer cannot activate this
    customer's handset: the call is a cross-reference mismatch rather than a not-found or a
    silent success, and both the handset and the account are left exactly as they were.

    PRD 2.7: "**Cross-reference integrity.** A referenced resource that exists but belongs
    elsewhere yields `ERR_CROSS_REFERENCE_MISMATCH` (409); this guards five operations —
    handset activation (the carrier account must belong to the handset's loan's customer),
    program cancellation (the payoff quote must belong to the addressed loan), trade-in
    declaration (the declared handset must belong to the upgrade request's loan), upgrade
    completion (the payoff quote must belong to the request's loan), and posting money (the
    reversed posting must belong to the addressed loan)."
    PRD 3.4: "The named carrier account must belong to the same customer as the handset's
    loan, or the request is refused with `ERR_CROSS_REFERENCE_MISMATCH`."
    PRD 3.1: "A fresh account opens with `activation_state` `PENDING`, `activated_at` null,
    and `active_device_imei` null."

    Design: Corner/entities/activation_with_another_customers_carrier_account_is_refused
    """
    ctx = setup_active_loan(with_carrier_account=False)
    other_customer = enroll_customer()
    other_carrier = register_carrier_account(other_customer["id"], carrier_code="TMOBILE")
    assert other_carrier["customer_id"] == other_customer["id"]
    assert other_carrier["customer_id"] != ctx["customer_id"]

    validate_error(api.activate_device_unit(
        ctx["device_id"], {"carrier_account_id": other_carrier["id"]},
        make_associate_headers()), ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH.value)

    device = read_device_unit(ctx["device_id"])
    assert_device_unit(device)
    assert device["activation_status"] == "UNACTIVATED", "the refused handset never joined a line"
    assert device["carrier_account_id"] is None
    assert device["activated_at"] is None
    assert device["version"] == 1, "a refused write leaves the handset's version alone"

    carriers, _ = validate_paginated(api.list_carrier_accounts(
        other_customer["id"], make_associate_headers()))
    stored = next(row for row in carriers if row["id"] == other_carrier["id"])
    assert_carrier_account(stored)
    assert stored["activation_state"] == "PENDING", "the other customer's account is untouched"
    assert stored["active_device_imei"] is None
    assert stored["activated_at"] is None
    assert stored["version"] == 1

    _, joined_meta = validate_paginated(api.list_device_units(
        make_associate_headers(), params={"carrier_account_id": other_carrier["id"]}))
    assert joined_meta["total_count"] == 0, "no handset is attached to the other account"
