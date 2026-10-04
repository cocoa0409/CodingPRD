"""Payment intake: file totals, pagination, schema and referential gates,
payment-method determination, and policy presence/supersede rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_policy,
    add_payment,
    assert_payment_file,
    create_active_policy,
    create_debt_payload,
    create_draft_policy,
    create_payment_file,
    create_payment_payload,
    create_refund_claim_payload,
    make_creditor_analyst_headers,
    read_payment_file,
    register_eft_payee,
    register_payee,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

AUDITOR = TEST_USERS["auditor_headers"]
OPERATOR = TEST_USERS["treasury_operator_headers"]
SUPERVISOR = TEST_USERS["treasury_supervisor_headers"]
AGENCY_ANALYST = TEST_USERS["payment_agency_analyst_headers"]


def _vendor_policy_and_file():
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("VENDOR", "FULL")
    payment_file = create_payment_file()
    return payee, payment_file


def test_payment_file_get_round_trips_derived_totals(api):
    """PRD §3.4: "The file is born `RECEIVED`; the first payment added to it
    flips it to `PROCESSING`".
    PRD §3.4: "Each accepted payment increments the file's `payment_count`".

    Design: Corner/entities/payment_file_get_round_trips_derived_totals
    """
    set_logical_clock()
    payee, payment_file = _vendor_policy_and_file()
    add_payment(payment_file, payee, 25000, "VENDOR")
    file_read = read_payment_file(payment_file["id"])
    assert_payment_file(file_read)
    assert file_read["agency_code"] == "AG-01"
    assert file_read["settlement_date"].startswith("2026-09-15T00:00:00")
    assert file_read["status"] == "PROCESSING"
    assert file_read["payment_count"] == 1
    assert file_read["total_offset_cents"] == 0
    assert file_read["total_disbursed_cents"] == 0


def test_payments_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned: it defaults
    to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of
    items skipped and defaults to 0."
    PRD §2.3: "The `meta` object of list responses carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/payments_list_paginates_with_total_count_and_has_more
    """
    set_logical_clock()
    payee, payment_file = _vendor_policy_and_file()
    for amount in (10000, 20000, 30000):
        add_payment(payment_file, payee, amount, "VENDOR")

    resp_1 = api.list_payments(
        AUDITOR, params={"payment_file_id": payment_file["id"], "limit": 2, "offset": 0}
    )
    assert resp_1.json()["response_type"] == "array"
    rows_1, meta_1 = validate_paginated(resp_1)
    assert len(rows_1) == 2
    assert meta_1["total_count"] == 3
    assert meta_1["has_more"] is True

    rows_2, meta_2 = validate_paginated(
        api.list_payments(
            AUDITOR,
            params={"payment_file_id": payment_file["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(rows_2) == 1
    assert meta_2["total_count"] == 3
    assert meta_2["has_more"] is False

    _, meta_default = validate_paginated(
        api.list_payments(AUDITOR, params={"payment_file_id": payment_file["id"]})
    )
    assert meta_default["limit"] == 10
    assert meta_default["offset"] == 0


def test_payment_create_missing_amount_returns_invalid_request(api):
    """PRD §2.8: "Required fields present, no unknown fields, enum membership,
    positive amounts, ordered effective windows, and the conditional-field rules
    (state code, policy-class fields, garnishment-versus-cross-servicing fields)
    — otherwise `ERR_INVALID_REQUEST` or `ERR_STATE_CODE_REQUIRED` (400)."
    PRD §3.4: "The `amount_cents` must be strictly greater than zero".

    Design: Corner/entities/payment_create_missing_amount_returns_invalid_request
    """
    set_logical_clock()
    payee, payment_file = _vendor_policy_and_file()
    resp = api.create_payment(
        payment_file["id"],
        {
            "payee_id": payee["id"],
            "payee_tin": payee["tin"],
            "payment_type": "VENDOR",
        },
        AGENCY_ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, _ = validate_paginated(
        api.list_payments(AUDITOR, params={"payment_file_id": payment_file["id"]})
    )
    assert rows == []


def test_payment_create_unknown_payee_returns_payee_not_found(api):
    """PRD §3.4: "The payload names the `payee_id` — an unknown payee is
    `ERR_PAYEE_NOT_FOUND`".
    PRD §3.3: "an unknown creditor id is `ERR_CREDITOR_NOT_FOUND`".
    PRD §3.6: "The payload names the `offset_id` — an unknown id is
    `ERR_OFFSET_NOT_FOUND`".

    Design: Corner/entities/payment_create_unknown_payee_returns_payee_not_found
    """
    set_logical_clock()
    create_active_policy("VENDOR", "FULL")
    payment_file = create_payment_file()

    resp_payment = api.create_payment(
        payment_file["id"],
        {
            "payee_id": "00000000-0000-4000-8000-000000000001",
            "payee_tin": "111-22-3333",
            "amount_cents": 10000,
            "payment_type": "VENDOR",
        },
        AGENCY_ANALYST,
    )
    validate_error(resp_payment, ApiErrorId.ERR_PAYEE_NOT_FOUND)

    ghost_creditor = "00000000-0000-4000-8000-000000000002"
    resp_debt = api.create_debt(
        create_debt_payload(ghost_creditor),
        make_creditor_analyst_headers(ghost_creditor),
    )
    validate_error(resp_debt, ApiErrorId.ERR_CREDITOR_NOT_FOUND)

    resp_claim = api.create_refund_claim(
        create_refund_claim_payload(
            "00000000-0000-4000-8000-000000000003", 100
        ),
        OPERATOR,
    )
    validate_error(resp_claim, ApiErrorId.ERR_OFFSET_NOT_FOUND)


def test_payment_method_determination_eft_vs_check(api):
    """PRD §3.4: "Its `payment_method` is `EFT` when the payee's
    `routing_number` is non-null and `CHECK` otherwise."

    Design: Corner/entities/payment_method_determination_eft_vs_check
    """
    set_logical_clock()
    payee_eft = register_eft_payee(tin="111-22-3333")
    payee_check = register_payee(tin="555-66-7777", legal_name="Sam Poe")
    create_active_policy("VENDOR", "FULL")
    payment_file = create_payment_file()

    payment_eft = add_payment(payment_file, payee_eft, 10000, "VENDOR")
    payment_check = add_payment(payment_file, payee_check, 10000, "VENDOR")
    assert payment_eft["payment_method"] == "EFT"
    assert payment_check["payment_method"] == "CHECK"


def test_payee_tin_mismatch_returns_422(api):
    """PRD §3.4: "declares a `payee_tin` that must equal the registered payee's
    own `tin`, with a mismatch rejected as `ERR_PAYEE_TIN_MISMATCH` (422)."

    Design: Corner/validations/payee_tin_mismatch_returns_422
    """
    set_logical_clock()
    payee, payment_file = _vendor_policy_and_file()
    resp = api.create_payment(
        payment_file["id"],
        {
            "payee_id": payee["id"],
            "payee_tin": "999-99-9999",
            "amount_cents": 10000,
            "payment_type": "VENDOR",
        },
        AGENCY_ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_PAYEE_TIN_MISMATCH)
    rows, _ = validate_paginated(
        api.list_payments(AUDITOR, params={"payment_file_id": payment_file["id"]})
    )
    assert rows == []


def test_payment_create_without_active_policy_returns_no_active_policy(api):
    """PRD §3.4: "the `payment_type` must have an `ACTIVE` exemption policy,
    otherwise `ERR_NO_ACTIVE_POLICY`."

    Design: Corner/validations/payment_create_without_active_policy_returns_no_active_policy
    """
    set_logical_clock()
    payee = register_eft_payee(tin="111-22-3333")
    create_draft_policy("GRANT", "FULL")  # DRAFT only — never activated
    payment_file = create_payment_file()
    resp = api.create_payment(
        payment_file["id"],
        create_payment_payload(payee, 10000, "GRANT"),
        AGENCY_ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_POLICY)
    rows, _ = validate_paginated(
        api.list_payments(AUDITOR, params={"payment_file_id": payment_file["id"]})
    )
    assert rows == []


def test_policy_activate_supersedes_incumbent_to_retired(api):
    """PRD §3.2: "Activation supersedes: the incumbent `ACTIVE` policy for the
    same `payment_type`, if one exists, is immediately `RETIRED`, and `RETIRED`
    is terminal."
    PRD §3.4: "a `PARTIAL` policy projects the amount minus its
    `protected_minimum_cents`, floored at zero".

    Design: Corner/state_machines/policy_activate_supersedes_incumbent_to_retired
    """
    set_logical_clock()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("SALARY", "FULL")
    policy_2 = create_draft_policy(
        "SALARY", "PARTIAL", protected_minimum_cents=1000, max_offset_pct=0.50
    )
    payment_file = create_payment_file()

    activated = activate_policy(policy_2)
    assert activated["status"] == "ACTIVE"

    # The superseding PARTIAL policy governs intake: the projection follows its
    # protected minimum (10000 - 1000), not the retired FULL policy's 10000.
    payment = add_payment(payment_file, payee, 10000, "SALARY")
    assert payment["projected_offset_cents"] == 9000


def test_exemption_policy_field_conditionals(api):
    """PRD §3.2: "A `PARTIAL` policy must carry both a `protected_minimum_cents`
    floor of zero or more and a `max_offset_pct` fraction greater than zero and
    at most one. An `EXEMPT` or `FULL` policy must leave both fields absent or
    null. Violating either conditional rule is `ERR_INVALID_REQUEST`."

    Design: Corner/validations/exemption_policy_field_conditionals
    """
    set_logical_clock()
    resp_partial = api.create_exemption_policy(
        {
            "payment_type": "VENDOR",
            "exemption_class": "PARTIAL",
            "protected_minimum_cents": 75000,
        },
        SUPERVISOR,
    )
    validate_error(resp_partial, ApiErrorId.ERR_INVALID_REQUEST)

    resp_exempt = api.create_exemption_policy(
        {
            "payment_type": "GRANT",
            "exemption_class": "EXEMPT",
            "protected_minimum_cents": 5000,
        },
        SUPERVISOR,
    )
    validate_error(resp_exempt, ApiErrorId.ERR_INVALID_REQUEST)
