"""Preparing a refund request and the signing authority it demands."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_refund_request,
    create_refund_request_payload,
    file_root_cause_finding,
    make_credit_analyst_headers,
    move_account_status,
    post_txn,
    read_account,
    read_credit_balance,
    set_clock,
    setup_attributed_credit,
    setup_identified_credit,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["credit_analyst_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def test_medicare_aged_unexplained_credit_needs_tier_three_and_two_signatures(api):
    """PRD §3.6: "A base tier comes from the amount alone. A request of at most 25,000 cents — two hundred and fifty dollars — is base tier 1."
    PRD §3.6: "Three independent escalations are then counted, each adding one. The first applies when the credit balance's payer is of type `MEDICARE` or `MEDICAID`. The second applies when the credit balance's `aging_days` is at least 181 — that is, when the credit has aged into the `OVER_180` bucket. The third applies when `root_cause_confirmed` is false, since paying out money whose cause is still unexplained warrants a second look."
    PRD §3.6: "Precisely: take the base tier plus the escalation count minus the de-escalation count; if that adjusted figure is below the base tier, use the base tier instead; then if the result exceeds 3, use 3. "
    PRD §3.6: "Finally, `required_approval_count` is 2 when `required_approval_tier` is 3, and 1 in every other case."

    Design: Difficulty/combinatorial_formula/approval_tier_nested_min_max_over_amount_payer_aging_and_root_cause
    """
    scenario = setup_attributed_credit(
        payer_type="MEDICARE", payer_code="MCR", account_number="ACCT-TA1",
        financial_class="INPATIENT", payment_source="PAYER",
    )
    credit_balance = scenario["credit_balance"]
    assert credit_balance["payer_portion_cents"] == 12_000

    set_clock("2027-03-03T00:00:00Z")
    aged = read_credit_balance(credit_balance["id"])
    assert aged["aging_days"] == 200
    assert aged["root_cause_confirmed"] is False

    request = validate_success(
        api.create_refund_request(
            create_refund_request_payload(
                credit_balance["id"], 12_000, "PAYER", credit_balance["version"],
                payee_name="Medicare Region A", payee_address_line="1 Payer Way",
                payee_state_code="CA",
            ),
            ANALYST,
        ),
        201,
    )
    assert_refund_request(request)
    assert request["required_approval_tier"] == 3
    assert request["required_approval_count"] == 2


def test_documented_commercial_credit_of_the_same_amount_needs_only_tier_two(api):
    """PRD §3.6: "The computation reads five things: the request's own `requested_amount_cents`; the owning credit balance's `aging_days` evaluated at the moment of this call; the request's `payee_type`; the `payer_type` of the payer on that credit balance; and the credit balance's `root_cause_confirmed` flag, likewise at call time."
    PRD §3.6: "The second applies when the credit balance's `aging_days` is at least 181 — that is, when the credit has aged into the `OVER_180` bucket."
    PRD §3.6: "Finally, `required_approval_count` is 2 when `required_approval_tier` is 3, and 1 in every other case."

    Design: Difficulty/combinatorial_formula/approval_tier_nested_min_max_over_amount_payer_aging_and_root_cause
    """
    scenario = setup_attributed_credit(
        payer_type="COMMERCIAL", payer_code="COM", account_number="ACCT-TA2",
        payment_source="PATIENT", root_cause_confirmed=True,
    )
    credit_balance = scenario["credit_balance"]
    assert credit_balance["patient_portion_cents"] == 12_000

    set_clock("2027-03-03T00:00:00Z")
    aged = read_credit_balance(credit_balance["id"])
    assert aged["aging_days"] == 200
    assert aged["root_cause_confirmed"] is True

    request = validate_success(
        api.create_refund_request(
            create_refund_request_payload(
                credit_balance["id"], 12_000, "PATIENT", credit_balance["version"],
                payee_name="Theo Alder", payee_address_line="9 Cedar",
                payee_state_code="CA",
            ),
            ANALYST,
        ),
        201,
    )
    assert request["required_approval_tier"] == 2
    assert request["required_approval_count"] == 1


def test_wrong_status_outranks_the_capacity_ceiling_on_a_refund_create(api):
    """PRD §2.8: "The ordering below is normative — a request that both names a non-existent credit balance and carries an illegal enum value fails on existence, not on shape, because existence is checked first."
    PRD §2.8: "Because state checks (ranks 8 through 16) precede the fiscal checks (ranks 38 through 46), a request that is both in the wrong state *and* fiscally impossible reports the state error."
    PRD §3.5: "The credit balance must be `ATTRIBUTED` — otherwise `ERR_CREDIT_BALANCE_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_8_beats_fiscal_priority_40_on_refund_request_create
    """
    scenario = setup_identified_credit(
        account_number="ACCT-PC1", state_code="NY", financial_class="EMERGENCY"
    )
    credit_balance = scenario["credit_balance"]
    assert credit_balance["status"] == "IDENTIFIED"

    response = api.create_refund_request(
        create_refund_request_payload(
            credit_balance["id"], 99_999, "PATIENT", credit_balance["version"],
            payee_name="Pia Crane", payee_address_line="3 Vine", payee_state_code="NY",
        ),
        ANALYST,
    )
    error = validate_error(response, ApiErrorId.ERR_CREDIT_BALANCE_INVALID_STATE.value)
    assert error["error_id"] != ApiErrorId.ERR_REFUND_EXCEEDS_CREDIT.value


def test_state_rejected_refund_create_leaves_no_request_and_no_status_change(api):
    """PRD §2.8: "The service does not report the first violation it happens to notice; it evaluates rules in a fixed global priority order and returns the error belonging to the **first** rule that fails, ignoring every later rule."
    PRD §3.5: "The credit balance must be `ATTRIBUTED` — otherwise `ERR_CREDIT_BALANCE_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_8_beats_fiscal_priority_40_on_refund_request_create
    """
    scenario = setup_identified_credit(
        account_number="ACCT-PC1", state_code="NY", financial_class="EMERGENCY"
    )
    credit_balance = scenario["credit_balance"]

    response = api.create_refund_request(
        create_refund_request_payload(
            credit_balance["id"], 99_999, "PATIENT", credit_balance["version"],
            payee_name="Pia Crane", payee_address_line="3 Vine", payee_state_code="NY",
        ),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_BALANCE_INVALID_STATE.value)

    assert read_credit_balance(credit_balance["id"])["status"] == "IDENTIFIED"
    _, meta = validate_paginated(
        api.list_refund_requests(
            ANALYST, params={"credit_balance_id": credit_balance["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_refund_create_is_blocked_while_the_owning_account_sits_in_bad_debt(api):
    """PRD §3.5: "The account behind it must be `OPEN` — a `CLOSED` or `BAD_DEBT` account yields `ERR_ACCOUNT_NOT_REFUNDABLE`."
    PRD §3.1: "Both `CLOSED` and `BAD_DEBT` are non-refundable: once an account is in either, every later attempt to prepare a refund request against a credit balance on that account fails with `ERR_ACCOUNT_NOT_REFUNDABLE`."

    Design: Difficulty/cross_entity_state_dependency/refund_request_create_depends_on_patient_account_status_not_bad_debt
    """
    scenario = setup_attributed_credit(
        account_number="ACCT-BD1", state_code="TX", financial_class="EMERGENCY"
    )
    credit_balance = scenario["credit_balance"]
    assert credit_balance["patient_portion_cents"] == 12_000

    set_clock("2026-08-16T00:00:00Z")
    move_account_status(scenario["account"]["id"], "BAD_DEBT")

    response = api.create_refund_request(
        create_refund_request_payload(
            credit_balance["id"], 12_000, "PATIENT", credit_balance["version"],
            payee_name="Bo Dane", payee_address_line="4 Ash", payee_state_code="TX",
        ),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_REFUNDABLE.value)

    unchanged = read_credit_balance(credit_balance["id"])
    assert unchanged["status"] == "ATTRIBUTED"
    assert unchanged["version"] == credit_balance["version"]
    assert read_account(scenario["account"]["id"])["status"] == "BAD_DEBT"


def test_identical_refund_create_succeeds_once_the_account_returns_to_open(api):
    """PRD §3.1: "A `BAD_DEBT` account may be returned to `OPEN`, at which point it is refundable again."
    PRD §3.5: "When all guards pass, the request is created, the owning credit balance moves `ATTRIBUTED → REFUND_PENDING`, and the credit balance's `version` is bumped by 1 — which immediately invalidates any other client's cached `expected_credit_balance_version` for that credit."

    Design: Difficulty/cross_entity_state_dependency/refund_request_create_depends_on_patient_account_status_not_bad_debt
    """
    scenario = setup_attributed_credit(
        account_number="ACCT-BD1", state_code="TX", financial_class="EMERGENCY"
    )
    credit_balance = scenario["credit_balance"]
    account_id = scenario["account"]["id"]

    set_clock("2026-08-16T00:00:00Z")
    move_account_status(account_id, "BAD_DEBT")
    payload = create_refund_request_payload(
        credit_balance["id"], 12_000, "PATIENT", credit_balance["version"],
        payee_name="Bo Dane", payee_address_line="4 Ash", payee_state_code="TX",
    )
    validate_error(
        api.create_refund_request(payload, ANALYST),
        ApiErrorId.ERR_ACCOUNT_NOT_REFUNDABLE.value,
    )

    move_account_status(account_id, "OPEN")
    request = validate_success(api.create_refund_request(payload, ANALYST), 201)

    assert request["approval_state"] == "DRAFT"
    refreshed = read_credit_balance(credit_balance["id"])
    assert refreshed["status"] == "REFUND_PENDING"
    assert refreshed["version"] == credit_balance["version"] + 1


def test_refund_request_system_fields_come_from_the_server_not_the_client(api):
    """PRD §3.5: "The preparing analyst's `X-User-ID` is stamped onto the request as `prepared_by_user_id`. A new request starts with an `approval_state` of `DRAFT`, a `disbursement_state` of `NOT_SCHEDULED`, `approved_amount_cents` at 0, `approvals_received` at 0 and `revision_count` at 0."
    PRD §3.5: "When all guards pass, the request is created, the owning credit balance moves `ATTRIBUTED → REFUND_PENDING`, and the credit balance's `version` is bumped by 1 — which immediately invalidates any other client's cached `expected_credit_balance_version` for that credit."

    Design: Corner/entities/refund_request_system_fields_ignore_client_input_and_stamp_from_headers
    """
    scenario = setup_attributed_credit(account_number="ACCT-SF1")
    credit_balance = scenario["credit_balance"]

    request = validate_success(
        api.create_refund_request(
            create_refund_request_payload(
                credit_balance["id"], 12_000, "PATIENT", credit_balance["version"],
                payee_name="Sofia Frey", payee_address_line="10 Reed",
                payee_state_code="CA",
            ),
            make_credit_analyst_headers("ca-analyst-9"),
        ),
        201,
    )

    assert request["prepared_by_user_id"] == "ca-analyst-9"
    assert request["approval_state"] == "DRAFT"
    assert request["disbursement_state"] == "NOT_SCHEDULED"
    assert request["approved_amount_cents"] == 0
    assert request["approvals_received"] == 0
    assert request["revision_count"] == 0
    assert read_credit_balance(credit_balance["id"])["status"] == "REFUND_PENDING"


def test_refund_below_the_floor_and_against_an_empty_bucket_are_both_refused(api):
    """PRD §3.5: "The named bucket must be funded: `PATIENT` requires `patient_portion_cents` strictly greater than 0 and `PAYER` requires `payer_portion_cents` strictly greater than 0, and naming an empty bucket yields `ERR_PAYEE_TYPE_MISMATCH` (HTTP 422)."
    PRD §3.5: "The `requested_amount_cents` must be at least 100 cents — one dollar — or the request is refused with `ERR_REFUND_BELOW_MINIMUM` (HTTP 422)."

    Design: Corner/validations/refund_request_rejected_below_minimum_and_on_payee_bucket_mismatch
    """
    scenario = setup_attributed_credit(account_number="ACCT-MN1")
    credit_balance = scenario["credit_balance"]
    assert credit_balance["patient_portion_cents"] == 12_000
    assert credit_balance["payer_portion_cents"] == 0

    too_small = api.create_refund_request(
        create_refund_request_payload(
            credit_balance["id"], 50, "PATIENT", credit_balance["version"],
            payee_name="Mo Nash", payee_address_line="1 Ridge", payee_state_code="CA",
        ),
        ANALYST,
    )
    validate_error(too_small, ApiErrorId.ERR_REFUND_BELOW_MINIMUM.value)

    empty_bucket = api.create_refund_request(
        create_refund_request_payload(
            credit_balance["id"], 12_000, "PAYER", credit_balance["version"],
            payee_name="Meridian Commercial", payee_address_line="2 Ridge",
            payee_state_code="CA",
        ),
        ANALYST,
    )
    validate_error(empty_bucket, ApiErrorId.ERR_PAYEE_TYPE_MISMATCH.value)

    unchanged = read_credit_balance(credit_balance["id"])
    assert unchanged["status"] == "ATTRIBUTED"
    assert unchanged["version"] == credit_balance["version"]
    _, meta = validate_paginated(
        api.list_refund_requests(
            ANALYST, params={"credit_balance_id": credit_balance["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_refund_create_is_refused_once_a_later_charge_consumed_the_credit(api):
    """PRD §3.5: "And the credit must still be economically present: the account's `balance_cents` must be strictly negative at the moment of creation."
    PRD §3.5: "This last guard exists because a later `CHARGE` can consume an overpayment while the credit balance row still reads `ATTRIBUTED` with a positive `outstanding_cents`; when the account has been brought back to zero or above, the attempt is rejected with `ERR_CREDIT_ALREADY_CONSUMED` (HTTP 409)."

    Design: Corner/validations/refund_request_rejected_when_a_later_charge_consumed_the_account_credit
    """
    scenario = setup_attributed_credit(account_number="ACCT-CC1",
                                       financial_class="INPATIENT")
    credit_balance = scenario["credit_balance"]
    account_id = scenario["account"]["id"]

    set_clock("2026-08-16T00:00:00Z")
    post_txn(account_id, "CHARGE", 12_000, "SYSTEM", remark="Late implant charge")

    response = api.create_refund_request(
        create_refund_request_payload(
            credit_balance["id"], 12_000, "PATIENT", credit_balance["version"],
            payee_name="Cai Chase", payee_address_line="9 Quarry",
            payee_state_code="CA",
        ),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_ALREADY_CONSUMED.value)

    account = read_account(account_id)
    assert account["balance_cents"] == 0
    assert account["credit_balance_cents"] == 12_000
    refreshed = read_credit_balance(credit_balance["id"])
    assert refreshed["status"] == "ATTRIBUTED"
    assert refreshed["outstanding_cents"] == 12_000


def test_stale_credit_balance_version_rejects_the_refund_create(api):
    """PRD §2.7: "Creating a refund request requires a non-optional `expected_credit_balance_version` field carrying the client's last observed `version` of the target `CreditBalance`. If the credit balance's `version` has advanced since the client read it, the create is rejected with `ERR_STALE_VERSION` at HTTP 412."
    PRD §3.3: "It recomputes the owning credit balance's `root_cause_confirmed` and bumps that credit balance's `version` by 1 — which matters twice over."

    Design: Corner/cross_cutting_layers/occ_stale_credit_balance_version_rejects_refund_request_create
    """
    scenario = setup_attributed_credit(account_number="ACCT-OC1")
    credit_balance_id = scenario["credit_balance"]["id"]
    stale_version = scenario["credit_balance"]["version"]

    file_root_cause_finding(
        credit_balance_id, confirmed=True, cause_code="ESTIMATE_OVERCOLLECTION",
        corrective_action="STAFF_RETRAINING",
        narrative="Estimate collected up front",
    )
    fresh_version = read_credit_balance(credit_balance_id)["version"]
    assert fresh_version > stale_version

    stale_attempt = api.create_refund_request(
        create_refund_request_payload(
            credit_balance_id, 12_000, "PATIENT", stale_version,
            payee_name="Odin Case", payee_address_line="5 Wharf",
            payee_state_code="CA",
        ),
        ANALYST,
    )
    validate_error(stale_attempt, ApiErrorId.ERR_STALE_VERSION.value)
    assert read_credit_balance(credit_balance_id)["status"] == "ATTRIBUTED"

    accepted = validate_success(
        api.create_refund_request(
            create_refund_request_payload(
                credit_balance_id, 12_000, "PATIENT", fresh_version,
                payee_name="Odin Case", payee_address_line="5 Wharf",
                payee_state_code="CA",
            ),
            ANALYST,
        ),
        201,
    )
    assert accepted["approval_state"] == "DRAFT"
    refreshed = read_credit_balance(credit_balance_id)
    assert refreshed["status"] == "REFUND_PENDING"
    assert refreshed["version"] == fresh_version + 1
