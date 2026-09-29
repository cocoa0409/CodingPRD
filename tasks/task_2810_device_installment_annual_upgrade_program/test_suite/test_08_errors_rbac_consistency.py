"""Corner cases: the error surface, the RBAC matrix and read-after-write consistency.

Driven from `SCAFFOLD_CORNER_DESIGN.yaml` sections `errors`, `rbac`,
`cross-cutting complexity layers` and `consistency model`. The recurring theme is
the PRD's validation ladder: authentication before authorization, authorization
before existence, existence before every state precondition.
"""
from test_helpers import (
    ADMIN_USER_ID,
    ALL_ROLES,
    ASSOCIATE_USER_ID,
    CLOCK_ORIGIN,
    COLLECTIONS_USER_ID,
    NON_EXISTENT_UUID,
    PLACEHOLDER_CUSTOMER_USER_ID,
    TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID_2,
    UNDERWRITER_USER_ID,
    ApiErrorId,
    activate_device,
    activation_payload,
    api_client,
    assert_iso_equals,
    cancellation_payload,
    clock_payload,
    completion_payload,
    create_carrier_account_payload,
    create_credit_application_payload,
    create_customer_payload,
    create_device_model_payload,
    create_loan_payload,
    decide_application,
    decision_payload,
    diagnostic_report_payload,
    enroll_customer,
    installment_total_cents,
    loan_device_unit,
    make_admin_headers,
    make_associate_headers,
    make_collections_headers,
    make_customer_headers,
    make_headers_for_role,
    make_technician_headers,
    make_underwriter_headers,
    next_email,
    next_imei,
    originate_loan,
    payment_payload,
    payoff_quote_payload,
    plus_days,
    post_payment,
    price_quote,
    publish_model,
    publish_target_model,
    read_carrier_accounts,
    read_device_model,
    read_device_unit,
    read_diagnostic_reports,
    read_installment,
    read_loan,
    read_payoff_quote,
    read_trade_in,
    read_upgrade_request,
    register_carrier_account,
    regrade_payload,
    reversal_payload,
    set_clock,
    setup_active_loan,
    setup_completion_ready,
    setup_trade_in_declared,
    setup_trade_in_disputed,
    setup_upgrade_ready,
    setup_upgrade_request,
    submit_application,
    trade_in_declaration_payload,
    upgrade_request_payload,
    upgrade_window_start_for,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Local helpers. The five operator roles carry opaque identifiers; `Customer` is
# entity-backed, so a role loop must be handed a real customer id whenever the
# call it drives touches a customer-owned resource.
# ---------------------------------------------------------------------------
_OPERATOR_USER_IDS = {
    "RetailAssociate": ASSOCIATE_USER_ID,
    "CreditUnderwriter": UNDERWRITER_USER_ID,
    "ServiceTechnician": TECHNICIAN_USER_ID,
    "CollectionsOfficer": COLLECTIONS_USER_ID,
    "ProgramAdmin": ADMIN_USER_ID,
}


def _headers_for(role, customer_id=None):
    """Identity headers for any declared role, entity-backed for `Customer`."""
    if role == "Customer":
        return make_customer_headers(customer_id or PLACEHOLDER_CUSTOMER_USER_ID)
    return make_headers_for_role(role, _OPERATOR_USER_IDS[role])


def _roles_other_than(*permitted):
    """Every declared role the endpoint's authorization list does not name."""
    return [role for role in ALL_ROLES if role not in permitted]


def _raw_headers(user_id=None, role=None):
    """A header dict with only the identity fields the test wants present."""
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers


# ===========================================================================
# errors - authentication is the floor of the ladder
# ===========================================================================
def test_absent_or_empty_identity_headers_are_rejected_as_unauthenticated():
    """Every shape of missing identity - absent header, empty string, both gone -
    is refused as ERR_UNAUTHENTICATED, and nothing is written.

    PRD 2.1: "If either header is absent or empty, or if `X-User-Role` carries a
    string that is not one of the six roles named below, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_or_undeclared_identity_headers_are_unauthenticated
    """
    broken = [
        _raw_headers(role="ProgramAdmin"),
        _raw_headers(user_id="", role="ProgramAdmin"),
        _raw_headers(user_id=ADMIN_USER_ID),
        _raw_headers(user_id=ADMIN_USER_ID, role=""),
        _raw_headers(user_id="", role=""),
        _raw_headers(),
    ]
    for headers in broken:
        error = validate_error(
            api_client.create_device_model(create_device_model_payload(), headers),
            ApiErrorId.ERR_UNAUTHENTICATED.value)
        assert error["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED.value
        assert isinstance(error["message"], str) and error["message"].strip() != ""

    _rows, meta = validate_paginated(api_client.list_device_models(make_admin_headers()))
    assert meta["total_count"] == 0


def test_an_undeclared_role_string_is_unauthenticated_and_outranks_the_not_found_check():
    """A role name outside the declared six is an authentication failure, and it
    beats the existence check even when the addressed loan does not exist.

    PRD 2.1: "If either header is absent or empty, or if `X-User-Role` carries a
    string that is not one of the six roles named below, the request is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD 2.7: "A caller who is both unauthenticated and pointing at a nonexistent loan
    receives the authentication error, never the not-found error."

    Design: Corner/errors/missing_or_undeclared_identity_headers_are_unauthenticated
    """
    ctx = setup_active_loan()

    for undeclared in ("DistrictManager", "StoreManager", "Auditor"):
        validate_error(
            api_client.get_loan(ctx["loan_id"], _raw_headers(ADMIN_USER_ID, undeclared)),
            ApiErrorId.ERR_UNAUTHENTICATED.value)

    validate_error(
        api_client.get_loan(NON_EXISTENT_UUID, _raw_headers(ADMIN_USER_ID, "DistrictManager")),
        ApiErrorId.ERR_UNAUTHENTICATED.value)
    validate_error(
        api_client.get_loan(NON_EXISTENT_UUID, _raw_headers("", "ProgramAdmin")),
        ApiErrorId.ERR_UNAUTHENTICATED.value)

    # With a declared role the same nonexistent loan finally reads as not-found,
    # which is what proves the ordering above was real.
    validate_error(api_client.get_loan(NON_EXISTENT_UUID, make_admin_headers()),
                   ApiErrorId.ERR_LOAN_NOT_FOUND.value)


def test_an_unauthenticated_write_leaves_no_row_behind():
    """A rejected-at-the-door enrolment writes nothing: the same email enrols
    cleanly straight afterwards instead of colliding.

    PRD 2.1: "If either header is absent or empty, or if `X-User-Role` carries a
    string that is not one of the six roles named below, the request is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD 3.1: "A second enrolment presenting an `email` already held by another
    customer is refused with `ERR_DUPLICATE_IDENTIFIER`."

    Design: Corner/errors/missing_or_undeclared_identity_headers_are_unauthenticated
    """
    email = next_email("unauthenticated.write")

    validate_error(
        api_client.create_customer(create_customer_payload(email=email),
                                   _raw_headers("", "RetailAssociate")),
        ApiErrorId.ERR_UNAUTHENTICATED.value)

    customer = validate_success(
        api_client.create_customer(create_customer_payload(email=email),
                                   make_associate_headers()),
        expected_status=201)
    assert customer["email"] == email


# ===========================================================================
# errors - the logical clock's monotonic guard
# ===========================================================================
def test_the_logical_clock_accepts_a_repin_and_refuses_every_backwards_move():
    """Re-pinning the clock to the instant it already reads is accepted; one
    second earlier is ERR_CLOCK_NOT_MONOTONIC, both before and after a real move.

    PRD 2.4: "Before any call moves it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`; this fixed startup default never falls back to the host's
    real time."
    PRD 2.4: "The clock only ever moves forward: a `to_iso8601` that fails to parse as
    an ISO 8601 UTC instant, or that is earlier than the clock's current reading, is
    rejected with `ERR_CLOCK_NOT_MONOTONIC`."
    PRD 2.4: "A `ProgramAdmin` moves the clock by supplying `to_iso8601`, an ISO 8601
    UTC instant, and the server answers with the resulting `current_utc`."

    Design: Corner/errors/the_logical_clock_refuses_to_move_backwards
    """
    repinned = validate_success(
        api_client.set_clock(clock_payload(CLOCK_ORIGIN), make_admin_headers()))
    assert_iso_equals(repinned["current_utc"], CLOCK_ORIGIN)

    validate_error(
        api_client.set_clock(clock_payload("2026-07-31T23:59:59Z"), make_admin_headers()),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value)
    validate_error(
        api_client.set_clock(clock_payload("2025-08-01T00:00:00Z"), make_admin_headers()),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value)

    # The refusals left the reading untouched, so the origin is still re-pinnable.
    still_there = validate_success(
        api_client.set_clock(clock_payload(CLOCK_ORIGIN), make_admin_headers()))
    assert_iso_equals(still_there["current_utc"], CLOCK_ORIGIN)

    moved = validate_success(
        api_client.set_clock(clock_payload("2026-08-01T00:00:01Z"), make_admin_headers()))
    assert_iso_equals(moved["current_utc"], "2026-08-01T00:00:01Z")

    # What was a legal re-pin one call ago is now strictly in the past.
    validate_error(
        api_client.set_clock(clock_payload(CLOCK_ORIGIN), make_admin_headers()),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value)
    held = validate_success(
        api_client.set_clock(clock_payload("2026-08-01T00:00:01Z"), make_admin_headers()))
    assert_iso_equals(held["current_utc"], "2026-08-01T00:00:01Z")


def test_an_unparseable_clock_instant_is_refused_and_the_reading_is_unchanged():
    """A `to_iso8601` that is not an ISO 8601 UTC instant is refused with a 400,
    and the clock still reads its startup default afterwards.

    PRD 2.4: "The clock only ever moves forward: a `to_iso8601` that fails to parse as
    an ISO 8601 UTC instant, or that is earlier than the clock's current reading, is
    rejected with `ERR_CLOCK_NOT_MONOTONIC`."
    PRD 2.7: "**Request shape.** Every field the endpoint marks as required must be
    present; every enum field must carry a declared member; every integer cent field
    must be an integer of zero or greater; every ISO 8601 field must parse; every UUID
    field must be well-formed."

    Design: Corner/errors/the_logical_clock_refuses_to_move_backwards
    """
    for malformed in ("not-a-timestamp", "2026-13-45T99:99:99Z", ""):
        validate_error_is_one_of(
            api_client.set_clock(clock_payload(malformed), make_admin_headers()),
            [ApiErrorId.ERR_INVALID_REQUEST.value,
             ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value])

    unchanged = validate_success(
        api_client.set_clock(clock_payload(CLOCK_ORIGIN), make_admin_headers()))
    assert_iso_equals(unchanged["current_utc"], CLOCK_ORIGIN)


# ===========================================================================
# errors - one distinct not-found id per unresolvable body reference
# ===========================================================================
def test_each_unresolvable_body_foreign_key_returns_its_own_not_found_id():
    """Seven different body references, seven different 404 ids - the catalogue is
    never collapsed into one generic not-found.

    PRD 2.7: "Only after every path segment resolves are body references checked, in
    this order: `customer_id` on application submission (`ERR_CUSTOMER_NOT_FOUND`);
    `device_model_id` on application submission and `target_device_model_id` on
    upgrade-request creation (`ERR_DEVICE_MODEL_NOT_FOUND`); `credit_application_id`
    on origination (`ERR_CREDIT_APPLICATION_NOT_FOUND`); `loan_id` on upgrade-request
    creation (`ERR_LOAN_NOT_FOUND`); `carrier_account_id` on handset activation
    (`ERR_CARRIER_ACCOUNT_NOT_FOUND`); `device_unit_id` on trade-in declaration
    (`ERR_DEVICE_UNIT_NOT_FOUND`); `payoff_quote_id` on program cancellation and on
    upgrade completion (`ERR_PAYOFF_QUOTE_NOT_FOUND`); and `reverses_posting_id`, when
    supplied on a posting, which must resolve to a posting of the addressed loan
    (`ERR_PAYMENT_POSTING_NOT_FOUND`)."

    Design: Corner/errors/unresolvable_body_foreign_keys_each_return_their_own_not_found
    """
    ctx = setup_active_loan()
    associate = make_associate_headers()

    validate_error(
        api_client.create_credit_application(
            create_credit_application_payload(NON_EXISTENT_UUID, ctx["model"]["id"]),
            associate),
        ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)

    validate_error(
        api_client.create_credit_application(
            create_credit_application_payload(ctx["customer_id"], NON_EXISTENT_UUID),
            associate),
        ApiErrorId.ERR_DEVICE_MODEL_NOT_FOUND.value)

    validate_error(
        api_client.create_loan(create_loan_payload(NON_EXISTENT_UUID), associate),
        ApiErrorId.ERR_CREDIT_APPLICATION_NOT_FOUND.value)

    validate_error(
        api_client.create_upgrade_request(
            upgrade_request_payload(NON_EXISTENT_UUID, ctx["target_model"]["id"],
                                    CLOCK_ORIGIN, 1),
            associate),
        ApiErrorId.ERR_LOAN_NOT_FOUND.value)

    validate_error(
        api_client.activate_device_unit(ctx["device_id"],
                                       activation_payload(NON_EXISTENT_UUID), associate),
        ApiErrorId.ERR_CARRIER_ACCOUNT_NOT_FOUND.value)

    validate_error(
        api_client.cancel_loan(ctx["loan_id"],
                              cancellation_payload(NON_EXISTENT_UUID, 1), associate),
        ApiErrorId.ERR_PAYOFF_QUOTE_NOT_FOUND.value)

    validate_error(
        api_client.create_payment(ctx["loan_id"],
                                 reversal_payload(1, NON_EXISTENT_UUID), associate),
        ApiErrorId.ERR_PAYMENT_POSTING_NOT_FOUND.value)


def test_body_reference_resolution_outranks_the_version_amount_and_posting_rules():
    """An unresolvable body reference is reported even when the same request also
    carries a stale version, a wrong tender or an illegal posting amount, and
    none of the seven refusals disturbs any stored figure.

    PRD 2.7: "Validation is not a set of independent checks — it is a strict ladder,
    evaluated in ascending priority, and the **first** violation encountered is the
    one reported."
    PRD 2.6: "This band exists only on upgrade-request creation, and it is evaluated
    **after** existence and cross-reference integrity but **before** every state
    precondition below."

    Design: Corner/errors/unresolvable_body_foreign_keys_each_return_their_own_not_found
    """
    ctx = setup_active_loan()
    associate = make_associate_headers()
    version_before = ctx["loan"]["version"]

    validate_error(
        api_client.create_upgrade_request(
            upgrade_request_payload(NON_EXISTENT_UUID, ctx["target_model"]["id"],
                                    CLOCK_ORIGIN, 9999),
            associate),
        ApiErrorId.ERR_LOAN_NOT_FOUND.value)

    validate_error(
        api_client.cancel_loan(ctx["loan_id"],
                              cancellation_payload(NON_EXISTENT_UUID, 123456), associate),
        ApiErrorId.ERR_PAYOFF_QUOTE_NOT_FOUND.value)

    validate_error(
        api_client.create_payment(ctx["loan_id"],
                                 reversal_payload(0, NON_EXISTENT_UUID), associate),
        ApiErrorId.ERR_PAYMENT_POSTING_NOT_FOUND.value)

    loan = read_loan(ctx["loan_id"])
    assert loan["status"] == "ACTIVE"
    assert loan["version"] == version_before
    assert loan["obligation_balance_cents"] == 113876
    assert loan["paid_installment_count"] == 0
    assert read_device_unit(ctx["device_id"])["activation_status"] == "UNACTIVATED"

    _rows, meta = validate_paginated(api_client.list_credit_applications(
        associate, params={"customer_id": ctx["customer_id"]}))
    assert meta["total_count"] == 1

    _postings, posting_meta = validate_paginated(api_client.list_payment_postings(
        associate, params={"loan_id": ctx["loan_id"]}))
    assert posting_meta["total_count"] == 0


# ===========================================================================
# errors - cancellation's quote-type gate and its exact-tender gate
# ===========================================================================
def test_cancellation_refuses_a_rollover_quote_on_its_quote_type():
    """An `UPGRADE_ROLLOVER` quote cannot be settled as a cancellation, and the
    type gate fires even when the tendered cash matches that quote exactly.

    PRD 3.7: "The named quote must belong to the addressed loan
    (`ERR_CROSS_REFERENCE_MISMATCH`), must be of `quote_type` `EARLY_CANCELLATION`
    (`ERR_PAYOFF_QUOTE_TYPE_MISMATCH`), must still be `ISSUED` rather than `CONSUMED`,
    `EXPIRED` or `SUPERSEDED` (`ERR_PAYOFF_QUOTE_NOT_ISSUED`), and must be unexpired,
    meaning the logical clock has not yet reached its `expires_at`
    (`ERR_PAYOFF_QUOTE_EXPIRED`)."
    PRD 2.7: "Immediately after, the quote's `quote_type` must match the consuming
    operation — `EARLY_CANCELLATION` for program cancellation, `UPGRADE_ROLLOVER` for
    upgrade completion — or the request is refused with
    `ERR_PAYOFF_QUOTE_TYPE_MISMATCH` (409)."

    Design: Corner/errors/cancellation_needs_the_right_quote_type_and_the_exact_amount
    """
    ctx = setup_completion_ready()
    rollover = ctx["quote"]
    assert rollover["quote_type"] == "UPGRADE_ROLLOVER"
    assert rollover["status"] == "ISSUED"
    assert rollover["admin_fee_cents"] == 0

    validate_error(
        api_client.cancel_loan(
            ctx["loan_id"],
            cancellation_payload(rollover["id"], rollover["total_payoff_cents"]),
            ctx["customer_headers"]),
        ApiErrorId.ERR_PAYOFF_QUOTE_TYPE_MISMATCH.value)

    loan = read_loan(ctx["loan_id"])
    assert loan["status"] == "ACTIVE"
    assert loan["closure_reason"] is None
    assert loan["protection_coverage_status"] == "ACTIVE"


def test_cancellation_demands_the_quote_total_to_the_exact_cent():
    """One cent either side of `total_payoff_cents` is refused; the exact figure
    closes the loan and voids the whole remaining ladder.

    PRD 3.7: "And the tendered `payment_amount_cents` must equal the quote's
    `total_payoff_cents` **exactly** — no more and no less — or the request is refused
    with `ERR_PAYOFF_AMOUNT_MISMATCH`."
    PRD 3.7: "There is no partial settlement of a cancellation quote."
    PRD 3.7: "`total_payoff_cents` is then `remaining_principal_cents` plus
    `outstanding_late_fee_cents` plus `admin_fee_cents`, less `premium_rebate_cents`."
    PRD 3.7: "The loan's `paid_principal_cents` is set equal to its `principal_cents`,
    its `outstanding_late_fee_cents` is set to zero, and its
    `protection_coverage_status` becomes `TERMINATED` — the bundled cover ends with
    the loan."

    Design: Corner/errors/cancellation_needs_the_right_quote_type_and_the_exact_amount
    """
    ctx = setup_active_loan()
    quote = price_quote(ctx["loan_id"], "EARLY_CANCELLATION",
                        customer_id=ctx["customer_id"])
    assert quote["quote_type"] == "EARLY_CANCELLATION"
    assert quote["remaining_principal_cents"] == 89900
    assert quote["outstanding_late_fee_cents"] == 0
    assert quote["unearned_premium_cents"] == 23976
    assert quote["premium_rebate_cents"] == 21578
    assert quote["admin_fee_cents"] == 2500
    assert quote["total_payoff_cents"] == 70822

    for wrong_tender in (70821, 70823, 0, 141644):
        validate_error(
            api_client.cancel_loan(ctx["loan_id"],
                                  cancellation_payload(quote["id"], wrong_tender),
                                  ctx["customer_headers"]),
            ApiErrorId.ERR_PAYOFF_AMOUNT_MISMATCH.value)

    still_open = read_loan(ctx["loan_id"])
    assert still_open["status"] == "ACTIVE"
    assert still_open["paid_principal_cents"] == 0

    settled = validate_success(
        api_client.cancel_loan(ctx["loan_id"],
                              cancellation_payload(quote["id"], 70822),
                              ctx["customer_headers"]))
    assert settled["status"] == "PAID_OFF"
    assert settled["closure_reason"] == "PROGRAM_CANCELLATION"
    assert settled["paid_principal_cents"] == 89900
    assert settled["outstanding_late_fee_cents"] == 0
    assert settled["protection_coverage_status"] == "TERMINATED"

    _rows, voided_meta = validate_paginated(api_client.list_installments(
        ctx["loan_id"], make_associate_headers(),
        params={"status": "VOIDED", "limit": 100}))
    assert voided_meta["total_count"] == 24

    assert read_payoff_quote(ctx["loan_id"], quote["id"])["status"] == "CONSUMED"


# ===========================================================================
# errors - postings must be positive and reversals must match exactly
# ===========================================================================
def test_a_zero_cent_posting_is_refused_while_a_negative_one_fails_request_shape():
    """Zero cents is a fiscal refusal, minus one cent is a shape refusal, and one
    cent is a legal posting.

    PRD 3.5: "`amount_cents` must be at least 1 for every posting type, and on a
    `REVERSAL` it must equal the reversed posting's `amount_cents` exactly; either
    failure is refused with `ERR_INVALID_POSTING_AMOUNT`."
    PRD 2.7: "**Request shape.** Every field the endpoint marks as required must be
    present; every enum field must carry a declared member; every integer cent field
    must be an integer of zero or greater; every ISO 8601 field must parse; every UUID
    field must be well-formed."

    Design: Corner/errors/posting_amounts_must_be_positive_and_reversals_must_match_exactly
    """
    ctx = setup_active_loan()
    version_before = ctx["loan"]["version"]

    validate_error(
        api_client.create_payment(ctx["loan_id"], payment_payload(0),
                                 ctx["customer_headers"]),
        ApiErrorId.ERR_INVALID_POSTING_AMOUNT.value)
    validate_error(
        api_client.create_payment(ctx["loan_id"], payment_payload(-1),
                                 ctx["customer_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST.value)

    untouched = read_loan(ctx["loan_id"])
    assert untouched["obligation_balance_cents"] == 113876
    assert untouched["version"] == version_before
    _rows, meta = validate_paginated(api_client.list_payment_postings(
        make_associate_headers(), params={"loan_id": ctx["loan_id"]}))
    assert meta["total_count"] == 0

    one_cent = validate_success(
        api_client.create_payment(ctx["loan_id"], payment_payload(1),
                                 ctx["customer_headers"]),
        expected_status=201)
    assert one_cent["amount_cents"] == 1
    assert one_cent["allocated_late_fee_cents"] == 0
    assert one_cent["allocated_principal_cents"] == 1
    assert one_cent["allocated_premium_cents"] == 0
    assert one_cent["installments_satisfied_count"] == 0
    assert one_cent["overpayment_cents"] == 0
    assert one_cent["obligation_balance_after_cents"] == 113875


def test_a_reversal_must_match_the_reversed_amount_exactly_and_restores_the_ledger():
    """Any amount but the reversed posting's own is refused; the exact amount puts
    every cents field back where it was and re-derives the installment.

    PRD 3.5: "`amount_cents` must be at least 1 for every posting type, and on a
    `REVERSAL` it must equal the reversed posting's `amount_cents` exactly; either
    failure is refused with `ERR_INVALID_POSTING_AMOUNT`."
    PRD 3.5: "The governing invariant is exact: the loan's post-reversal ledger must
    equal its ledger immediately before the target posting was applied, with zero
    drift in any cents field."
    PRD 3.5: "The reversing posting's own `allocated_late_fee_cents`,
    `allocated_principal_cents` and `allocated_premium_cents` mirror the amounts
    removed, while `installments_satisfied_count` and `overpayment_cents` are both
    zero, because a reversal satisfies nothing and overpays nothing."

    Design: Corner/errors/posting_amounts_must_be_positive_and_reversals_must_match_exactly
    """
    ctx = setup_active_loan()
    payment = post_payment(ctx["loan_id"], 2000, customer_id=ctx["customer_id"])
    assert payment["amount_cents"] == 2000
    assert payment["allocated_principal_cents"] == 1579
    assert payment["allocated_premium_cents"] == 421
    assert payment["obligation_balance_after_cents"] == 111876

    for wrong_amount in (1999, 2001, 1, 0):
        validate_error(
            api_client.create_payment(ctx["loan_id"],
                                     reversal_payload(wrong_amount, payment["id"]),
                                     make_collections_headers()),
            ApiErrorId.ERR_INVALID_POSTING_AMOUNT.value)

    mid = read_loan(ctx["loan_id"])
    assert mid["obligation_balance_cents"] == 111876
    assert mid["paid_principal_cents"] == 1579
    assert mid["paid_premium_cents"] == 421

    reversal = validate_success(
        api_client.create_payment(ctx["loan_id"],
                                 reversal_payload(2000, payment["id"]),
                                 make_collections_headers()),
        expected_status=201)
    assert reversal["posting_type"] == "REVERSAL"
    assert reversal["reverses_posting_id"] == payment["id"]
    assert reversal["amount_cents"] == 2000
    assert reversal["installments_satisfied_count"] == 0
    assert reversal["overpayment_cents"] == 0
    assert reversal["obligation_balance_after_cents"] == 113876

    restored = read_loan(ctx["loan_id"])
    assert restored["obligation_balance_cents"] == 113876
    assert restored["paid_principal_cents"] == 0
    assert restored["paid_premium_cents"] == 0
    assert restored["paid_installment_count"] == 0
    assert restored["outstanding_late_fee_cents"] == 0

    first = read_installment(ctx["loan_id"], 1)
    assert first["paid_amount_cents"] == 0
    assert first["paid_principal_cents"] == 0
    assert first["paid_premium_cents"] == 0
    assert first["status"] == "SCHEDULED"

    _rows, meta = validate_paginated(api_client.list_payment_postings(
        make_associate_headers(), params={"loan_id": ctx["loan_id"]}))
    assert meta["total_count"] == 2


# ===========================================================================
# errors - the trade-in declaration is once-only and its window is half-open
# ===========================================================================
def test_a_second_trade_in_declaration_is_refused_once_the_request_has_left_eligibility_passed():
    """Declaring is a one-shot act: the first declaration moves the request out of
    `ELIGIBILITY_PASSED`, so a second one cannot be accepted.

    PRD 3.9: "The upgrade request must be in `ELIGIBILITY_PASSED`, or the declaration
    is refused with `ERR_UPGRADE_REQUEST_NOT_AWAITING_TRADE_IN`; the named handset
    must belong to the request's own loan, or the declaration is refused with
    `ERR_CROSS_REFERENCE_MISMATCH`; the handset's `possession_status` must be
    `WITH_CUSTOMER`; and the logical clock must still be before the request's
    `fulfillment_window_end`, or the declaration is refused with
    `ERR_FULFILLMENT_WINDOW_ELAPSED`."
    PRD 3.9: "The declared handset moves `WITH_CUSTOMER → RETURN_PENDING`, the request
    advances `ELIGIBILITY_PASSED → TRADE_IN_DECLARED`, and the request's
    `trade_in_credit_projection_cents`, `projected_rollover_balance_cents`,
    `credit_shortfall_cents` and `funding_flag` are all refreshed."
    PRD 3.9: "The estimate is the traded handset's model `trade_in_base_credit_cents`
    multiplied by the condition multiplier for the declared condition and divided by
    10,000, rounded half up to whole cents."

    Design: Corner/errors/trade_in_declaration_is_once_only_and_the_window_closes_at_its_end
    """
    ctx = setup_trade_in_declared("GOOD")
    assert ctx["trade_in"]["status"] == "DECLARED"
    assert ctx["trade_in"]["declared_condition"] == "GOOD"
    assert ctx["trade_in"]["credit_estimate_cents"] == 38250
    assert ctx["upgrade_request"]["status"] == "TRADE_IN_DECLARED"
    assert read_device_unit(ctx["device_id"])["possession_status"] == "RETURN_PENDING"

    validate_error(
        api_client.declare_trade_in(
            ctx["upgrade_request_id"],
            trade_in_declaration_payload(ctx["device_id"], "EXCELLENT"),
            ctx["customer_headers"]),
        ApiErrorId.ERR_UPGRADE_REQUEST_NOT_AWAITING_TRADE_IN.value)

    _rows, meta = validate_paginated(api_client.list_trade_ins(
        make_associate_headers(),
        params={"upgrade_request_id": ctx["upgrade_request_id"]}))
    assert meta["total_count"] == 1

    unchanged = read_trade_in(ctx["trade_in_id"])
    assert unchanged["declared_condition"] == "GOOD"
    assert unchanged["credit_estimate_cents"] == 38250
    assert read_upgrade_request(ctx["upgrade_request_id"])["status"] == "TRADE_IN_DECLARED"


def test_the_fulfillment_window_is_open_one_second_before_its_end_and_closed_at_it():
    """The window admits the instant before `fulfillment_window_end` and refuses
    the end instant itself.

    PRD 3.8: "The candidate window is the half-open interval that begins at the
    supplied `fulfillment_window_start` and ends 7 days later;
    `fulfillment_window_end` on the request records that closing instant, and the
    window covers every instant from the start up to but not including the end."
    PRD 3.9: "The trade-in must be in `DECLARED` (`ERR_TRADE_IN_INVALID_STATE`), its
    owning request must be in `TRADE_IN_DECLARED`, and the fulfillment window must not
    have elapsed."

    Design: Corner/errors/trade_in_declaration_is_once_only_and_the_window_closes_at_its_end
    """
    ctx = setup_upgrade_request()
    assert_iso_equals(ctx["window_start"], "2027-06-27T00:00:00Z")
    assert_iso_equals(ctx["upgrade_request"]["fulfillment_window_end"],
                      "2027-07-04T00:00:00Z")
    assert_iso_equals(plus_days(ctx["window_start"], 7), "2027-07-04T00:00:00Z")

    set_clock("2027-07-03T23:59:59Z")
    trade_in = validate_success(
        api_client.declare_trade_in(
            ctx["upgrade_request_id"],
            trade_in_declaration_payload(ctx["device_id"], "GOOD"),
            ctx["customer_headers"]),
        expected_status=201)
    assert trade_in["status"] == "DECLARED"
    assert trade_in["credit_estimate_cents"] == 38250

    set_clock("2027-07-04T00:00:00Z")
    validate_error(
        api_client.receive_trade_in(trade_in["id"], make_technician_headers()),
        ApiErrorId.ERR_FULFILLMENT_WINDOW_ELAPSED.value)

    after = read_trade_in(trade_in["id"])
    assert after["status"] == "DECLARED"
    assert after["received_at"] is None
    assert read_device_unit(ctx["device_id"])["possession_status"] == "RETURN_PENDING"
    assert read_upgrade_request(ctx["upgrade_request_id"])["status"] == "TRADE_IN_DECLARED"


# ===========================================================================
# errors - retired models and frozen carrier accounts block their operations
# ===========================================================================
def test_a_retired_model_still_reads_but_refuses_a_new_credit_application():
    """A model published with `active` false is readable and listable but cannot be
    financed; the live model beside it accepts the very same application.

    PRD 3.1: "Setting `active` to false retires a model from the catalog — no new
    credit application and no upgrade may target it thereafter, and an attempt to do
    so is refused with `ERR_DEVICE_MODEL_INACTIVE`."
    PRD 3.1: "Callers browsing the catalog may narrow the list by `active` and by
    `generation_year`."

    Design: Corner/errors/inactive_models_and_frozen_carrier_accounts_block_their_operations
    """
    live = publish_model()
    retired = publish_model(active=False)
    customer = enroll_customer()
    associate = make_associate_headers()

    validate_error(
        api_client.create_credit_application(
            create_credit_application_payload(customer["id"], retired["id"]), associate),
        ApiErrorId.ERR_DEVICE_MODEL_INACTIVE.value)

    read_back = validate_success(api_client.get_device_model(retired["id"], associate))
    assert read_back["active"] is False
    assert read_back["reserved_slot_count"] == 0

    inactive_rows, inactive_meta = validate_paginated(api_client.list_device_models(
        associate, params={"active": False}))
    assert inactive_meta["total_count"] == 1
    assert inactive_rows[0]["id"] == retired["id"]

    active_rows, active_meta = validate_paginated(api_client.list_device_models(
        associate, params={"active": True}))
    assert active_meta["total_count"] == 1
    assert active_rows[0]["id"] == live["id"]

    _apps, app_meta = validate_paginated(api_client.list_credit_applications(
        associate, params={"device_model_id": retired["id"]}))
    assert app_meta["total_count"] == 0

    accepted = validate_success(
        api_client.create_credit_application(
            create_credit_application_payload(customer["id"], live["id"]), associate),
        expected_status=201)
    assert accepted["device_model_id"] == live["id"]


def test_a_retired_target_model_cannot_be_upgraded_into():
    """The same retirement rule bites on upgrade-request creation, on a loan that
    clears every other upgrade gate.

    PRD 3.1: "Setting `active` to false retires a model from the catalog — no new
    credit application and no upgrade may target it thereafter, and an attempt to do
    so is refused with `ERR_DEVICE_MODEL_INACTIVE`."
    PRD 3.8: "The target model must additionally have `active` true
    (`ERR_DEVICE_MODEL_INACTIVE`), and the customer must not already hold another loan
    in `status` `ACTIVE` financing that same model, which is refused with
    `ERR_DUPLICATE_MODEL_ON_CUSTOMER`."

    Design: Corner/errors/inactive_models_and_frozen_carrier_accounts_block_their_operations
    """
    ctx = setup_upgrade_ready(target_model_overrides={"active": False})
    loan = ctx["loan"]
    assert loan["paid_installment_count"] == 12
    assert loan["delinquency_state"] == "CURRENT"

    validate_error(
        api_client.create_upgrade_request(
            upgrade_request_payload(ctx["loan_id"], ctx["target_model"]["id"],
                                    ctx["window_start"], loan["version"]),
            ctx["customer_headers"]),
        ApiErrorId.ERR_DEVICE_MODEL_INACTIVE.value)

    assert read_device_model(ctx["target_model"]["id"])["reserved_slot_count"] == 0
    assert read_loan(ctx["loan_id"])["upgrade_hold_flag"] is False
    _rows, meta = validate_paginated(api_client.list_upgrade_requests(
        make_associate_headers(), params={"loan_id": ctx["loan_id"]}))
    assert meta["total_count"] == 0


def test_a_port_frozen_carrier_account_blocks_activation_while_a_clean_one_succeeds():
    """A `port_freeze_flag` account is refused as not portable and leaves both
    sides untouched; a fresh account activates and both sides move together.

    PRD 3.4: "The carrier account's `activation_state` must be `PENDING` or
    `PORT_ELIGIBLE`, and its `port_freeze_flag` must be false; an account already
    `ACTIVATED` on another handset, or one under a port freeze, is refused with
    `ERR_CARRIER_ACCOUNT_NOT_PORTABLE`."
    PRD 3.4: "On success the handset advances `UNACTIVATED → ACTIVATED`, records the
    chosen `carrier_account_id`, and stamps `activated_at` with the logical clock."
    PRD 3.4: "The carrier side moves in the same breath: the account's
    `activation_state` becomes `ACTIVATED` and its `active_device_imei` records this
    handset's `imei`."

    Design: Corner/errors/inactive_models_and_frozen_carrier_accounts_block_their_operations
    """
    ctx = setup_active_loan(carrier_overrides={"port_freeze_flag": True})
    frozen = ctx["carrier"]
    assert frozen["port_freeze_flag"] is True
    assert frozen["activation_state"] == "PENDING"

    validate_error(
        api_client.activate_device_unit(ctx["device_id"],
                                       activation_payload(frozen["id"]),
                                       make_associate_headers()),
        ApiErrorId.ERR_CARRIER_ACCOUNT_NOT_PORTABLE.value)

    still_unactivated = read_device_unit(ctx["device_id"])
    assert still_unactivated["activation_status"] == "UNACTIVATED"
    assert still_unactivated["carrier_account_id"] is None
    assert still_unactivated["activated_at"] is None

    clean = register_carrier_account(ctx["customer_id"])
    activated = validate_success(
        api_client.activate_device_unit(ctx["device_id"],
                                       activation_payload(clean["id"]),
                                       make_associate_headers()))
    assert activated["activation_status"] == "ACTIVATED"
    assert activated["carrier_account_id"] == clean["id"]
    assert_iso_equals(activated["activated_at"], CLOCK_ORIGIN)

    accounts = {row["id"]: row for row in read_carrier_accounts(ctx["customer_id"])}
    assert accounts[clean["id"]]["activation_state"] == "ACTIVATED"
    assert accounts[clean["id"]]["active_device_imei"] == still_unactivated["imei"]
    assert accounts[frozen["id"]]["activation_state"] == "PENDING"
    assert accounts[frozen["id"]]["active_device_imei"] is None


# ===========================================================================
# errors - identifier uniqueness and handset serial shape
# ===========================================================================
def test_a_duplicate_sku_email_or_account_number_is_each_a_duplicate_identifier():
    """All three of the program's unique identifiers share one error id, and each
    collision leaves the original row alone.

    PRD 3.1: "Each carries a `sku` — non-empty and unique across the catalog, again
    guarded by `ERR_DUPLICATE_IDENTIFIER` — together with a `display_name` for the
    marketing name, a `retail_price_cents` cash price that must be greater than zero,
    a `monthly_protection_premium_cents` figure of zero or more that will be bundled
    into every monthly installment financed on this model, a
    `trade_in_base_credit_cents` figure of zero or more that anchors the trade-in
    valuation before any condition multiplier or diagnostic deduction, and a
    `generation_year`."
    PRD 3.1: "A second enrolment presenting an `email` already held by another
    customer is refused with `ERR_DUPLICATE_IDENTIFIER`."
    PRD 3.1: "Registration supplies a `carrier_code`, which must be one of `VERIZON`,
    `ATT`, `TMOBILE` or `ESIM_MVNO`, and an `account_number` that must be unique
    across all carrier accounts — a collision is `ERR_DUPLICATE_IDENTIFIER`."

    Design: Corner/errors/duplicate_identifiers_and_reused_or_malformed_imeis_are_rejected
    """
    admin = make_admin_headers()
    associate = make_associate_headers()

    model = publish_model()
    validate_error(
        api_client.create_device_model(create_device_model_payload(sku=model["sku"]), admin),
        ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

    customer = enroll_customer()
    validate_error(
        api_client.create_customer(create_customer_payload(email=customer["email"]),
                                  associate),
        ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

    account = register_carrier_account(customer["id"])
    validate_error(
        api_client.create_carrier_account(
            customer["id"],
            create_carrier_account_payload(account_number=account["account_number"]),
            associate),
        ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

    # Uniqueness is program-wide, not per customer.
    other = enroll_customer()
    validate_error(
        api_client.create_carrier_account(
            other["id"],
            create_carrier_account_payload(account_number=account["account_number"]),
            associate),
        ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

    _models, model_meta = validate_paginated(api_client.list_device_models(admin))
    assert model_meta["total_count"] == 1
    assert len(read_carrier_accounts(customer["id"])) == 1
    assert read_carrier_accounts(other["id"]) == []


def test_a_reused_or_malformed_imei_is_refused_while_a_fresh_serial_originates():
    """A serial already on a handset, and a serial that is not exactly 15 digits,
    share `ERR_IMEI_ALREADY_REGISTERED`; the application survives to be originated
    with a clean serial.

    PRD 3.3: "Finally the supplied `imei` must be exactly 15 digits and must not
    already be registered on any handset in the program; a malformed or duplicate
    serial is refused with `ERR_IMEI_ALREADY_REGISTERED`."

    Design: Corner/errors/duplicate_identifiers_and_reused_or_malformed_imeis_are_rejected
    """
    associate = make_associate_headers()
    model_b = publish_model()
    model_c = publish_model(retail_price_cents=49900,
                            monthly_protection_premium_cents=499,
                            trade_in_base_credit_cents=18000)
    customer = enroll_customer()

    first_app = decide_application(
        submit_application(customer["id"], model_b["id"], requested_term_months=24)["id"])
    second_app = decide_application(
        submit_application(customer["id"], model_c["id"], requested_term_months=24)["id"])

    serial = next_imei()
    first_loan = originate_loan(first_app["id"], imei=serial)
    assert first_loan["principal_cents"] == 89900
    assert loan_device_unit(first_loan["id"])["imei"] == serial

    validate_error(
        api_client.create_loan(create_loan_payload(second_app["id"], imei=serial), associate),
        ApiErrorId.ERR_IMEI_ALREADY_REGISTERED.value)

    for malformed in ("12345", "1234567890123456", "35693803564000A"):
        validate_error(
            api_client.create_loan(create_loan_payload(second_app["id"], imei=malformed),
                                  associate),
            ApiErrorId.ERR_IMEI_ALREADY_REGISTERED.value)

    survivor = validate_success(
        api_client.get_credit_application(second_app["id"], associate))
    assert survivor["status"] == "APPROVED"

    fresh = next_imei()
    second_loan = originate_loan(second_app["id"], imei=fresh)
    assert second_loan["principal_cents"] == 49900
    assert second_loan["premium_total_cents"] == 11976
    assert second_loan["monthly_installment_cents"] == 2578
    assert second_loan["obligation_balance_cents"] == 61876
    assert read_installment(second_loan["id"], 1)["amount_due_cents"] == 2578

    units, unit_meta = validate_paginated(api_client.list_device_units(
        associate, params={"loan_id": second_loan["id"]}))
    assert unit_meta["total_count"] == 1
    assert units[0]["imei"] == fresh

    _loans, loan_meta = validate_paginated(api_client.list_loans(
        associate, params={"customer_id": customer["id"]}))
    assert loan_meta["total_count"] == 2


# ===========================================================================
# errors - the down-payment ceiling and one active loan per model per customer
# ===========================================================================
def test_a_declared_down_payment_equal_to_the_retail_price_is_refused():
    """The declared down payment must stay strictly under the cash price; one cent
    under is accepted and snapshots a one-cent principal.

    PRD 3.2: "That declared down payment must be strictly below the model's
    `retail_price_cents` — a device paid for in full needs no installment loan — and
    an amount equal to or above the retail price is refused with
    `ERR_DOWN_PAYMENT_EXCEEDS_PRICE`."
    PRD 3.2: "At submission the application snapshots `requested_principal_cents` as
    the model's `retail_price_cents` less `declared_down_payment_cents`, and opens
    with `status` `SUBMITTED`."

    Design: Corner/errors/overpaid_down_payment_and_duplicate_target_model_are_refused
    """
    associate = make_associate_headers()
    model = publish_model()
    assert model["retail_price_cents"] == 89900
    customer = enroll_customer()

    for overpaid in (89900, 89901, 200000):
        validate_error(
            api_client.create_credit_application(
                create_credit_application_payload(
                    customer["id"], model["id"],
                    declared_down_payment_cents=overpaid),
                associate),
            ApiErrorId.ERR_DOWN_PAYMENT_EXCEEDS_PRICE.value)

    _apps, empty_meta = validate_paginated(api_client.list_credit_applications(
        associate, params={"customer_id": customer["id"]}))
    assert empty_meta["total_count"] == 0

    accepted = validate_success(
        api_client.create_credit_application(
            create_credit_application_payload(customer["id"], model["id"],
                                             declared_down_payment_cents=89899),
            associate),
        expected_status=201)
    assert accepted["declared_down_payment_cents"] == 89899
    assert accepted["requested_principal_cents"] == 1
    assert accepted["status"] == "SUBMITTED"


def test_an_upgrade_request_cannot_target_a_model_the_customer_already_finances():
    """A customer already holding an ACTIVE loan on a model cannot upgrade into it;
    a different model on the same request succeeds immediately.

    PRD 3.8: "The target model must additionally have `active` true
    (`ERR_DEVICE_MODEL_INACTIVE`), and the customer must not already hold another loan
    in `status` `ACTIVE` financing that same model, which is refused with
    `ERR_DUPLICATE_MODEL_ON_CUSTOMER`."
    PRD 3.8: "That figure must be at least 5,000 basis points — half the schedule."

    Design: Corner/errors/overpaid_down_payment_and_duplicate_target_model_are_refused
    """
    model_b = publish_model()
    model_c = publish_model(retail_price_cents=49900,
                            monthly_protection_premium_cents=499,
                            trade_in_base_credit_cents=18000)
    model_a = publish_target_model()
    customer = enroll_customer()
    customer_headers = make_customer_headers(customer["id"])
    carrier = register_carrier_account(customer["id"])

    app_b = decide_application(
        submit_application(customer["id"], model_b["id"])["id"])
    loan_b = originate_loan(app_b["id"])
    activate_device(loan_device_unit(loan_b["id"])["id"], carrier["id"])

    app_c = decide_application(
        submit_application(customer["id"], model_c["id"])["id"])
    loan_c = originate_loan(app_c["id"])
    assert loan_c["status"] == "ACTIVE"
    assert loan_c["device_model_id"] == model_c["id"]

    post_payment(loan_b["id"], 56940, customer_id=customer["id"])
    window_start = upgrade_window_start_for(read_loan(loan_b["id"]))
    set_clock(window_start)
    loan_b = read_loan(loan_b["id"])
    assert loan_b["paid_installment_count"] == 12
    assert loan_b["delinquency_state"] == "CURRENT"
    version_before = loan_b["version"]

    validate_error(
        api_client.create_upgrade_request(
            upgrade_request_payload(loan_b["id"], model_c["id"], window_start,
                                    version_before),
            customer_headers),
        ApiErrorId.ERR_DUPLICATE_MODEL_ON_CUSTOMER.value)

    refused = read_loan(loan_b["id"])
    assert refused["version"] == version_before
    assert refused["upgrade_hold_flag"] is False
    assert read_device_model(model_c["id"])["reserved_slot_count"] == 0

    opened = validate_success(
        api_client.create_upgrade_request(
            upgrade_request_payload(loan_b["id"], model_a["id"], window_start,
                                    version_before),
            customer_headers),
        expected_status=201)
    assert opened["status"] == "ELIGIBILITY_PASSED"
    assert opened["eligibility_ratio_bps"] == 5000
    assert opened["paid_installment_count_at_request"] == 12
    assert opened["target_device_model_id"] == model_a["id"]
    assert read_device_model(model_a["id"])["reserved_slot_count"] == 1
    assert read_loan(loan_b["id"])["upgrade_hold_flag"] is True


# ===========================================================================
# rbac - every exclusive operation refuses every other role
# ===========================================================================
def test_catalog_publication_and_the_clock_are_program_admin_exclusive():
    """Publishing a model and moving the clock are the administrator's alone; the
    other five roles are each refused.

    PRD 2.1: "Once the headers are accepted, the endpoint's own authorization list is
    consulted: a role that does not appear on the endpoint is rejected with
    `ERR_UNAUTHORIZED`."
    PRD 3.1: "The financeable catalog is a set of `DeviceModel` rows, published by a
    `ProgramAdmin`."
    PRD 2.4: "A `ProgramAdmin` moves the clock by supplying `to_iso8601`, an ISO 8601
    UTC instant, and the server answers with the resulting `current_utc`."

    Design: Corner/rbac/each_exclusive_operation_refuses_every_other_role
    """
    for role in _roles_other_than("ProgramAdmin"):
        headers = _headers_for(role)
        validate_error(
            api_client.create_device_model(create_device_model_payload(), headers),
            ApiErrorId.ERR_UNAUTHORIZED.value)
        validate_error(
            api_client.set_clock(clock_payload("2026-09-01T00:00:00Z"), headers),
            ApiErrorId.ERR_UNAUTHORIZED.value)

    admin = make_admin_headers()
    _rows, empty_meta = validate_paginated(api_client.list_device_models(admin))
    assert empty_meta["total_count"] == 0

    model = validate_success(
        api_client.create_device_model(create_device_model_payload(), admin),
        expected_status=201)
    assert model["active"] is True

    moved = validate_success(
        api_client.set_clock(clock_payload("2026-09-01T00:00:00Z"), admin))
    assert_iso_equals(moved["current_utc"], "2026-09-01T00:00:00Z")


def test_the_underwriting_decision_is_credit_underwriter_exclusive():
    """Only a `CreditUnderwriter` may file a decision - the administrator is
    refused alongside everybody else.

    PRD 2.1: "An administrator may not originate a loan, may not file an underwriting
    decision, may not record physical receipt of a returned handset, may not file the
    initial bench diagnostic, may not complete an upgrade, and may not raise a device
    unlock request."
    PRD 3.2: "The decision itself is the exclusive act of a `CreditUnderwriter`, and
    it is the only writable input on the whole decision step: the underwriter supplies
    `credit_score_band`, which must be `PRIME`, `NEAR_PRIME` or `SUBPRIME`."

    Design: Corner/rbac/each_exclusive_operation_refuses_every_other_role
    """
    model = publish_model()
    customer = enroll_customer()
    application = submit_application(customer["id"], model["id"])

    for role in _roles_other_than("CreditUnderwriter"):
        validate_error(
            api_client.decide_credit_application(
                application["id"], decision_payload("PRIME"),
                _headers_for(role, customer["id"])),
            ApiErrorId.ERR_UNAUTHORIZED.value)

    still_open = validate_success(
        api_client.get_credit_application(application["id"], make_associate_headers()))
    assert still_open["status"] == "SUBMITTED"
    assert still_open["underwriter_user_id"] is None

    decided = validate_success(
        api_client.decide_credit_application(application["id"],
                                            decision_payload("PRIME"),
                                            make_underwriter_headers()))
    assert decided["status"] == "APPROVED"
    assert decided["underwriter_user_id"] == UNDERWRITER_USER_ID


def test_loan_origination_is_retail_associate_exclusive():
    """Only a `RetailAssociate` may originate; five refusals leave the approved
    application unoriginated.

    PRD 2.1: "`ProgramAdmin` is deliberately **not** a blanket override."
    PRD 3.3: "Origination is the exclusive act of a `RetailAssociate`, and it is the
    moment three resources come into existence at once: the loan, its full installment
    schedule, and the physical handset record."

    Design: Corner/rbac/each_exclusive_operation_refuses_every_other_role
    """
    model = publish_model()
    customer = enroll_customer()
    application = decide_application(
        submit_application(customer["id"], model["id"])["id"])
    assert application["status"] == "APPROVED"

    for role in _roles_other_than("RetailAssociate"):
        validate_error(
            api_client.create_loan(create_loan_payload(application["id"]),
                                  _headers_for(role, customer["id"])),
            ApiErrorId.ERR_UNAUTHORIZED.value)

    _rows, empty_meta = validate_paginated(api_client.list_loans(
        make_associate_headers(),
        params={"credit_application_id": application["id"]}))
    assert empty_meta["total_count"] == 0

    loan = validate_success(
        api_client.create_loan(create_loan_payload(application["id"]),
                              make_associate_headers()),
        expected_status=201)
    assert loan["status"] == "ACTIVE"
    assert loan["version"] == 1


def test_the_device_unlock_request_is_closed_to_the_admin_and_back_office_roles():
    """Only the customer and the counter may raise an unlock request; the four
    other roles - the administrator included - are refused.

    PRD 2.1: "An administrator may not originate a loan, may not file an underwriting
    decision, may not record physical receipt of a returned handset, may not file the
    initial bench diagnostic, may not complete an upgrade, and may not raise a device
    unlock request."
    PRD 2.1: "Each of those controls stays with the role that owns the corresponding
    real-world responsibility, and an administrator attempting one of them is refused
    with `ERR_UNAUTHORIZED` exactly as any other unauthorised role would be."

    Design: Corner/rbac/each_exclusive_operation_refuses_every_other_role
    """
    ctx = setup_active_loan(activate=True)

    for role in _roles_other_than("Customer", "RetailAssociate"):
        validate_error(
            api_client.request_device_unlock(ctx["device_id"],
                                            _headers_for(role, ctx["customer_id"])),
            ApiErrorId.ERR_UNAUTHORIZED.value)

    device = read_device_unit(ctx["device_id"])
    assert device["unlock_status"] == "LOCKED"
    assert device["unlock_requested_at"] is None


def test_trade_in_receipt_and_the_bench_diagnostic_are_service_technician_exclusive():
    """Receipt and the initial diagnostic are the bench's alone, both refusing the
    other five roles.

    PRD 3.9: "**Receiving it at the store.** Physical receipt is the exclusive act of
    a `ServiceTechnician` and carries no request body."
    PRD 3.9: "**Grading it.** The bench diagnostic is likewise exclusive to a
    `ServiceTechnician`, and it is what fixes the money."

    Design: Corner/rbac/each_exclusive_operation_refuses_every_other_role
    """
    ctx = setup_trade_in_declared("GOOD")

    for role in _roles_other_than("ServiceTechnician"):
        validate_error(
            api_client.receive_trade_in(ctx["trade_in_id"],
                                       _headers_for(role, ctx["customer_id"])),
            ApiErrorId.ERR_UNAUTHORIZED.value)
    assert read_trade_in(ctx["trade_in_id"])["status"] == "DECLARED"

    received = validate_success(
        api_client.receive_trade_in(ctx["trade_in_id"], make_technician_headers()))
    assert received["status"] == "RECEIVED"

    for role in _roles_other_than("ServiceTechnician"):
        validate_error(
            api_client.create_diagnostic_report(
                ctx["trade_in_id"], diagnostic_report_payload(),
                _headers_for(role, ctx["customer_id"])),
            ApiErrorId.ERR_UNAUTHORIZED.value)
    assert read_diagnostic_reports(ctx["trade_in_id"]) == []

    report = validate_success(
        api_client.create_diagnostic_report(ctx["trade_in_id"],
                                           diagnostic_report_payload(),
                                           make_technician_headers()),
        expected_status=201)
    assert report["technician_user_id"] == TECHNICIAN_USER_ID
    assert read_trade_in(ctx["trade_in_id"])["status"] == "GRADED"


def test_upgrade_completion_is_retail_associate_exclusive():
    """Completion is the counter's alone; five refusals leave the request in
    `TRADE_IN_GRADED` and the loan open.

    PRD 3.9: "**Completing the upgrade.** Completion is the exclusive act of a
    `RetailAssociate`, and it is the single largest transaction in the program: it
    retires one loan, mints another, moves two handsets and settles a trade-in."

    Design: Corner/rbac/each_exclusive_operation_refuses_every_other_role
    """
    ctx = setup_completion_ready()
    quote_id = ctx["quote"]["id"]

    for role in _roles_other_than("RetailAssociate"):
        validate_error(
            api_client.complete_upgrade(ctx["upgrade_request_id"],
                                       completion_payload(quote_id),
                                       _headers_for(role, ctx["customer_id"])),
            ApiErrorId.ERR_UNAUTHORIZED.value)

    assert read_upgrade_request(ctx["upgrade_request_id"])["status"] == "TRADE_IN_GRADED"
    assert read_loan(ctx["loan_id"])["status"] == "ACTIVE"

    successor = validate_success(
        api_client.complete_upgrade(ctx["upgrade_request_id"],
                                   completion_payload(quote_id),
                                   make_associate_headers()),
        expected_status=201)
    assert successor["predecessor_loan_id"] == ctx["loan_id"]
    assert read_loan(ctx["loan_id"])["status"] == "ROLLED_OVER"


# ===========================================================================
# rbac - a shared read answers identically for every permitted role
# ===========================================================================
def test_a_shared_loan_read_answers_identically_for_every_permitted_role():
    """All six roles are on `GET /loans/{id}`, and all six get byte-identical
    figures - reading never mutates and never varies by role.

    PRD 2.1: "Once the headers are accepted, the endpoint's own authorization list is
    consulted: a role that does not appear on the endpoint is rejected with
    `ERR_UNAUTHORIZED`."
    PRD 4 endpoint table, the authorization column of `GET /loans/{id}`:
    "Customer, RetailAssociate, CreditUnderwriter, ServiceTechnician,
    CollectionsOfficer, ProgramAdmin"
    PRD 3.3: "`obligation_balance_cents`, the loan's headline outstanding figure, is
    defined generally as the unpaid principal (`principal_cents` less
    `paid_principal_cents`) plus the unpaid premium (`premium_total_cents` less
    `paid_premium_cents`) plus `outstanding_late_fee_cents`; at origination, with
    nothing paid and no fees, that reduces to `principal_cents` plus
    `premium_total_cents`."

    Design: Corner/rbac/a_shared_read_answers_identically_for_every_permitted_role
    """
    ctx = setup_active_loan()
    post_payment(ctx["loan_id"], 2000, customer_id=ctx["customer_id"])

    readings = {}
    for role in ALL_ROLES:
        readings[role] = validate_success(
            api_client.get_loan(ctx["loan_id"], _headers_for(role, ctx["customer_id"])))

    baseline = readings["ProgramAdmin"]
    assert baseline["principal_cents"] == 89900
    assert baseline["premium_total_cents"] == 23976
    assert baseline["monthly_installment_cents"] == 4745
    assert baseline["paid_principal_cents"] == 1579
    assert baseline["paid_premium_cents"] == 421
    assert baseline["obligation_balance_cents"] == 111876
    assert baseline["paid_installment_count"] == 0

    assert len(readings) == 6
    for role, row in readings.items():
        assert row == baseline, f"role {role} saw a different loan"


def test_the_catalog_is_readable_by_every_declared_role_with_identical_figures():
    """The catalog list and the single-model read are open to all six roles and
    agree with each other for every one of them.

    PRD 2.1: "Once the headers are accepted, the endpoint's own authorization list is
    consulted: a role that does not appear on the endpoint is rejected with
    `ERR_UNAUTHORIZED`."
    PRD 3.1: "Callers browsing the catalog may narrow the list by `active` and by
    `generation_year`."
    PRD 3.1: "Two further attributes are optional at publication:
    `concurrent_reservation_capacity`, the number of upgrade fulfillment windows that
    may overlap on this model at once, which must be zero or greater and defaults to 2
    when omitted; and `active`, which defaults to true."

    Design: Corner/rbac/a_shared_read_answers_identically_for_every_permitted_role
    """
    model = publish_model()

    seen = []
    for role in ALL_ROLES:
        headers = _headers_for(role)
        rows, meta = validate_paginated(api_client.list_device_models(headers))
        assert meta["total_count"] == 1
        single = validate_success(api_client.get_device_model(model["id"], headers))
        assert rows[0] == single
        assert single["retail_price_cents"] == 89900
        assert single["reserved_slot_count"] == 0
        assert single["concurrent_reservation_capacity"] == 2
        seen.append(single)

    assert len(seen) == 6
    for row in seen:
        assert row == seen[0]


# ===========================================================================
# rbac - a technician cannot overturn their own grading
# ===========================================================================
def test_the_grading_technician_cannot_file_the_regrade_on_their_own_report():
    """The actor who filed the newest report is refused a regrade of it, and the
    trade-in keeps the disputed figures.

    PRD 3.9: "The trade-in must be in `DISPUTED` (`ERR_TRADE_IN_INVALID_STATE`), and
    the acting `X-User-ID` must differ from the `technician_user_id` of the trade-in's
    newest non-superseded report, or the regrade is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/a_technician_cannot_overturn_their_own_grading
    """
    ctx = setup_trade_in_disputed(
        declared_condition="GOOD",
        measurements={"screen_grade": "PRISTINE", "battery_health_pct": 85})
    trade_in = ctx["trade_in"]
    assert trade_in["status"] == "DISPUTED"
    assert trade_in["credit_estimate_cents"] == 38250
    assert trade_in["graded_condition"] == "EXCELLENT"
    assert trade_in["credit_final_cents"] == 45000
    assert trade_in["credit_variance_cents"] == 6750
    assert trade_in["dispute_count"] == 1
    assert ctx["report"]["technician_user_id"] == TECHNICIAN_USER_ID
    assert ctx["report"]["report_type"] == "INITIAL"
    assert ctx["report"]["sequence_no"] == 1

    validate_error(
        api_client.regrade_trade_in(
            ctx["trade_in_id"],
            regrade_payload(screen_grade="SCRATCHED", battery_health_pct=85),
            make_technician_headers(TECHNICIAN_USER_ID)),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    unchanged = read_trade_in(ctx["trade_in_id"])
    assert unchanged["status"] == "DISPUTED"
    assert unchanged["graded_condition"] == "EXCELLENT"
    assert unchanged["credit_final_cents"] == 45000
    assert unchanged["latest_report_sequence_no"] == 1
    assert unchanged["dispute_count"] == 1
    assert len(read_diagnostic_reports(ctx["trade_in_id"])) == 1


def test_a_second_technician_regrades_and_the_credit_is_recomputed_from_the_new_report():
    """A different bench actor may file the regrade, and the trade-in's money is
    rebuilt from the newest report alone - variance going negative.

    PRD 3.9: "The trade-in's `graded_condition`, `diagnostic_result`,
    `credit_final_cents`, `credit_variance_cents`, `graded_at` and
    `latest_report_sequence_no` are all recomputed from it by exactly the arithmetic
    above, the trade-in returns `DISPUTED → GRADED`, and the request's funding
    projection is refreshed."
    PRD 3.9: "Then, and only then, `screen_deduction_cents` and
    `battery_deduction_cents` are subtracted from the rounded product; the deductions
    are flat cash amounts and are never scaled by the multiplier."
    PRD 3.9: "`credit_variance_cents` is then `credit_final_cents` less
    `credit_estimate_cents`, and it goes negative whenever grading came in below the
    customer's own declaration — which is the whole point of grading, since the
    declared condition is ignored entirely and an `EXCELLENT` declaration cannot lift
    a cracked-screen handset above `FAIR`."
    PRD 4: "Two consequences of that rule are worth naming, because they are easy to
    get backwards: filing a diagnostic report and filing a regrade both answer 201,
    since each writes a new report even though their visible purpose is to change a
    trade-in that already exists; and completing an upgrade answers 201 because it
    mints a successor loan, whereas cancelling a loan answers 200 because it only
    closes one that is already there."

    Design: Corner/rbac/a_technician_cannot_overturn_their_own_grading
    """
    ctx = setup_trade_in_disputed(
        declared_condition="GOOD",
        measurements={"screen_grade": "PRISTINE", "battery_health_pct": 85})

    report = validate_success(
        api_client.regrade_trade_in(
            ctx["trade_in_id"],
            regrade_payload(screen_grade="SCRATCHED", battery_health_pct=85),
            make_technician_headers(TECHNICIAN_USER_ID_2)),
        expected_status=201)
    assert report["report_type"] == "REGRADE"
    assert report["sequence_no"] == 2
    assert report["technician_user_id"] == TECHNICIAN_USER_ID_2
    assert report["derived_condition"] == "GOOD"
    assert report["condition_multiplier_bps"] == 8500
    assert report["screen_deduction_cents"] == 2500
    assert report["battery_deduction_cents"] == 0
    assert report["computed_credit_cents"] == 35750
    assert report["diagnostic_result"] == "PASS"

    regraded = read_trade_in(ctx["trade_in_id"])
    assert regraded["status"] == "GRADED"
    assert regraded["graded_condition"] == "GOOD"
    assert regraded["credit_final_cents"] == 35750
    assert regraded["credit_variance_cents"] == -2500
    assert regraded["latest_report_sequence_no"] == 2
    assert regraded["dispute_count"] == 1

    assert len(read_diagnostic_reports(ctx["trade_in_id"])) == 2
    _rows, meta = validate_paginated(api_client.list_diagnostic_reports(
        ctx["trade_in_id"], make_technician_headers(),
        params={"report_type": "REGRADE"}))
    assert meta["total_count"] == 1


# ===========================================================================
# rbac - the entity-backed Customer ownership screen
# ===========================================================================
def test_a_customer_cannot_read_or_pay_another_customers_loan():
    """A second borrower's identity is refused on the first borrower's loan and
    customer record, and the first borrower's ledger is untouched.

    PRD 2.1: "A `Customer` who addresses a resource owned by a different customer is
    refused with `ERR_UNAUTHORIZED` before any state precondition is evaluated."
    PRD 2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
    `Customer` record; ownership checks on any resource that references a `Customer`
    compare the resource's owning-customer reference to `X-User-ID`."

    Design: Corner/rbac/a_customer_cannot_reach_another_customers_loan
    """
    associate = make_associate_headers()
    model = publish_model(retail_price_cents=49900,
                          monthly_protection_premium_cents=499,
                          trade_in_base_credit_cents=18000)
    first = enroll_customer()
    second = enroll_customer()

    loan_first = originate_loan(
        decide_application(submit_application(first["id"], model["id"])["id"])["id"])
    loan_second = originate_loan(
        decide_application(submit_application(second["id"], model["id"])["id"])["id"])
    assert loan_first["obligation_balance_cents"] == 61876

    intruder = make_customer_headers(second["id"])
    validate_error(api_client.get_loan(loan_first["id"], intruder),
                   ApiErrorId.ERR_UNAUTHORIZED.value)
    validate_error(api_client.get_customer(first["id"], intruder),
                   ApiErrorId.ERR_UNAUTHORIZED.value)
    validate_error(
        api_client.create_payment(loan_first["id"], payment_payload(2578), intruder),
        ApiErrorId.ERR_UNAUTHORIZED.value)
    validate_error(
        api_client.create_payoff_quote(loan_first["id"],
                                      payoff_quote_payload("EARLY_CANCELLATION"),
                                      intruder),
        ApiErrorId.ERR_UNAUTHORIZED.value)

    intact = read_loan(loan_first["id"])
    assert intact["obligation_balance_cents"] == 61876
    assert intact["paid_installment_count"] == 0
    assert intact["version"] == loan_first["version"]
    _rows, meta = validate_paginated(api_client.list_payment_postings(
        associate, params={"loan_id": loan_first["id"]}))
    assert meta["total_count"] == 0

    own = validate_success(
        api_client.create_payment(loan_second["id"], payment_payload(2578), intruder),
        expected_status=201)
    assert own["allocated_principal_cents"] == 2079
    assert own["allocated_premium_cents"] == 499
    assert own["installments_satisfied_count"] == 1
    assert own["obligation_balance_after_cents"] == 59298
    assert validate_success(api_client.get_loan(loan_second["id"],
                                               intruder))["paid_installment_count"] == 1


# ===========================================================================
# cross-cutting complexity layers - the OCC guard on upgrade-request creation
# ===========================================================================
def test_a_stale_expected_loan_version_is_refused_and_the_fresh_re_read_succeeds():
    """A version observed before an intervening payment is refused with a 412, and
    the re-read version is accepted on the retry.

    PRD 2.6: "If `expected_loan_version` does not equal that loan's current `version`,
    the request is rejected with `ERR_STALE_LOAN_VERSION` and HTTP status 412, and the
    client must re-read the loan and re-decide before retrying."
    PRD 2.6: "Six do, each by exactly 1: originating the loan (which mints it at
    `version` 1); posting money to it under any `posting_type`, including a
    `REVERSAL`; pricing a payoff quote against it; opening an upgrade request against
    it (the same call that sets `upgrade_hold_flag`); completing an upgrade out of it
    (which drives the loan to `ROLLED_OVER`); and cancelling the program on it (which
    drives the loan to `PAID_OFF`)."
    PRD 2.6: "This band exists only on upgrade-request creation, and it is evaluated
    **after** existence and cross-reference integrity but **before** every state
    precondition below."

    Design: Corner/cross-cutting complexity layers/a_stale_expected_loan_version_is_refused_and_the_re_read_succeeds
    """
    ctx = setup_upgrade_ready(paid_count=12)
    stale_version = read_loan(ctx["loan_id"])["version"]

    post_payment(ctx["loan_id"], 1000, customer_id=ctx["customer_id"])
    fresh = read_loan(ctx["loan_id"])
    assert fresh["version"] == stale_version + 1
    assert fresh["obligation_balance_cents"] == 55936

    validate_error(
        api_client.create_upgrade_request(
            upgrade_request_payload(ctx["loan_id"], ctx["target_model"]["id"],
                                    ctx["window_start"], stale_version),
            ctx["customer_headers"]),
        ApiErrorId.ERR_STALE_LOAN_VERSION.value)

    refused = read_loan(ctx["loan_id"])
    assert refused["version"] == fresh["version"]
    assert refused["upgrade_hold_flag"] is False
    assert read_device_model(ctx["target_model"]["id"])["reserved_slot_count"] == 0
    _rows, meta = validate_paginated(api_client.list_upgrade_requests(
        make_associate_headers(), params={"loan_id": ctx["loan_id"]}))
    assert meta["total_count"] == 0

    opened = validate_success(
        api_client.create_upgrade_request(
            upgrade_request_payload(ctx["loan_id"], ctx["target_model"]["id"],
                                    ctx["window_start"], fresh["version"]),
            ctx["customer_headers"]),
        expected_status=201)
    assert opened["status"] == "ELIGIBILITY_PASSED"
    assert opened["eligibility_ratio_bps"] == 5000
    assert opened["paid_installment_count_at_request"] == 12

    settled = read_loan(ctx["loan_id"])
    assert settled["version"] == fresh["version"] + 1
    assert settled["upgrade_hold_flag"] is True
    assert settled["obligation_balance_cents"] == 55936
    assert read_installment(ctx["loan_id"], 13)["status"] == "PARTIALLY_PAID"
    assert read_device_model(ctx["target_model"]["id"])["reserved_slot_count"] == 1


# ===========================================================================
# consistency model - the write response already agrees with every read
# ===========================================================================
def test_activation_is_visible_on_both_the_handset_and_the_carrier_account_at_once():
    """The activation response, the handset re-read and the carrier account all
    agree in the same request - there is no lag on either side.

    PRD 3.4: "On success the handset advances `UNACTIVATED → ACTIVATED`, records the
    chosen `carrier_account_id`, and stamps `activated_at` with the logical clock."
    PRD 3.4: "The carrier side moves in the same breath: the account's
    `activation_state` becomes `ACTIVATED` and its `active_device_imei` records this
    handset's `imei`."
    PRD 2.4: "Before any call moves it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`; this fixed startup default never falls back to the host's
    real time."

    Design: Corner/consistency model/activation_is_visible_to_both_sides_in_the_same_request
    """
    ctx = setup_active_loan()
    associate = make_associate_headers()

    before = read_device_unit(ctx["device_id"])
    assert before["activation_status"] == "UNACTIVATED"
    assert before["carrier_account_id"] is None
    assert read_carrier_accounts(ctx["customer_id"])[0]["activation_state"] == "PENDING"

    activated = validate_success(
        api_client.activate_device_unit(ctx["device_id"],
                                       activation_payload(ctx["carrier"]["id"]),
                                       associate))
    assert activated["activation_status"] == "ACTIVATED"
    assert activated["carrier_account_id"] == ctx["carrier"]["id"]
    assert activated["unlock_status"] == "LOCKED"
    assert activated["possession_status"] == "WITH_CUSTOMER"
    assert activated["imei"] == before["imei"]
    assert_iso_equals(activated["activated_at"], CLOCK_ORIGIN)

    # Read-after-write: every later read repeats the write response exactly.
    assert read_device_unit(ctx["device_id"]) == activated
    assert validate_success(api_client.get_device_unit(ctx["device_id"],
                                                     ctx["customer_headers"])) == activated

    accounts = read_carrier_accounts(ctx["customer_id"])
    assert len(accounts) == 1
    assert accounts[0]["id"] == ctx["carrier"]["id"]
    assert accounts[0]["activation_state"] == "ACTIVATED"
    assert accounts[0]["active_device_imei"] == activated["imei"]
    assert_iso_equals(accounts[0]["activated_at"], CLOCK_ORIGIN)

    rows, meta = validate_paginated(api_client.list_device_units(
        associate, params={"carrier_account_id": ctx["carrier"]["id"]}))
    assert meta["total_count"] == 1
    assert rows[0] == activated


def test_the_posting_response_already_agrees_with_the_loan_and_the_schedule():
    """A posting's own allocation totals, the loan's ledger and the installment
    ladder are all consistent the instant the posting is accepted.

    PRD 3.5: "`allocated_late_fee_cents`, `allocated_premium_cents` and
    `allocated_principal_cents` are the three totals it consumed across all buckets;
    `installments_satisfied_count` is the number of installments this single posting
    drove all the way to `PAID`; and `obligation_balance_after_cents` captures the
    loan's `obligation_balance_cents` immediately after the allocation was applied."
    PRD 3.5: "A second- or third-bucket take is split between principal and premium in
    the same proportion the installment itself carries: the principal share is the
    take multiplied by the installment's `principal_component_cents` divided by its
    `amount_due_cents`, rounded half up to whole cents, and is added to
    `paid_principal_cents`; the premium share is the arithmetic complement — the take
    less the principal share — and is added to `paid_premium_cents`, so that the two
    shares sum to the take exactly with no cent lost or invented."

    Design: Corner/consistency model/the_posting_response_already_agrees_with_the_loan_and_the_schedule
    """
    ctx = setup_active_loan()
    associate = make_associate_headers()
    assert installment_total_cents(ctx["installments"], 12) == 56940

    first = validate_success(
        api_client.create_payment(ctx["loan_id"], payment_payload(56940),
                                 ctx["customer_headers"]),
        expected_status=201)
    assert first["allocated_late_fee_cents"] == 0
    assert first["allocated_principal_cents"] == 44952
    assert first["allocated_premium_cents"] == 11988
    assert first["installments_satisfied_count"] == 12
    assert first["overpayment_cents"] == 0
    assert first["obligation_balance_after_cents"] == 56936

    loan = read_loan(ctx["loan_id"])
    assert loan["obligation_balance_cents"] == first["obligation_balance_after_cents"]
    assert loan["paid_principal_cents"] == 44952
    assert loan["paid_premium_cents"] == 11988
    assert loan["paid_installment_count"] == 12
    assert loan["outstanding_late_fee_cents"] == 0

    _paid, paid_meta = validate_paginated(api_client.list_installments(
        ctx["loan_id"], associate, params={"status": "PAID", "limit": 100}))
    assert paid_meta["total_count"] == 12
    _scheduled, scheduled_meta = validate_paginated(api_client.list_installments(
        ctx["loan_id"], associate, params={"status": "SCHEDULED", "limit": 100}))
    assert scheduled_meta["total_count"] == 12

    second = validate_success(
        api_client.create_payment(ctx["loan_id"], payment_payload(1000),
                                 ctx["customer_headers"]),
        expected_status=201)
    assert second["allocated_late_fee_cents"] == 0
    assert second["allocated_principal_cents"] == 789
    assert second["allocated_premium_cents"] == 211
    assert second["installments_satisfied_count"] == 0
    assert second["overpayment_cents"] == 0
    assert second["obligation_balance_after_cents"] == 55936

    after = read_loan(ctx["loan_id"])
    assert after["obligation_balance_cents"] == second["obligation_balance_after_cents"]
    assert after["paid_principal_cents"] == 44952 + 789
    assert after["paid_premium_cents"] == 11988 + 211
    assert after["paid_installment_count"] == 12

    thirteenth = read_installment(ctx["loan_id"], 13)
    assert thirteenth["status"] == "PARTIALLY_PAID"
    assert thirteenth["paid_amount_cents"] == 1000
    assert thirteenth["paid_principal_cents"] == 789
    assert thirteenth["paid_premium_cents"] == 211

    assert validate_success(api_client.get_payment_posting(first["id"], associate)) == first
    assert validate_success(api_client.get_payment_posting(second["id"], associate)) == second
    _rows, meta = validate_paginated(api_client.list_payment_postings(
        associate, params={"loan_id": ctx["loan_id"]}))
    assert meta["total_count"] == 2
