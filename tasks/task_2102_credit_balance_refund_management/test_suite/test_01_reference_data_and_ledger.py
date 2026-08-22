"""Payers, patient accounts and the ledger spine."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_account_transaction,
    assert_instant_equals,
    assert_ledger_invariant,
    assert_patient_account,
    assert_payer,
    create_patient_account_payload,
    create_payer_payload,
    create_transaction_payload,
    list_transactions,
    move_account_status,
    post_txn,
    read_account,
    read_transaction,
    seed_account,
    seed_payer,
    set_clock,
    setup_identified_credit,
    start_review,
    attribute,
    run_identify_sweep,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["credit_analyst_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_payer_creation_returns_declared_and_common_fields(api):
    """PRD §3.1: "A `SystemAdmin` registers each payer organisation with a display `name`, a short external `payer_code` and a `payer_type` drawn from `MEDICARE`, `MEDICAID`, `COMMERCIAL`, `TRICARE` and `SELF_PAY`."
    PRD §2.4: "Most resources additionally carry `updated_at` — the same format, refreshed on every mutation — and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row."
    PRD §4: "Operations that create a new, stand-alone resource — a payer, an account, a ledger posting, a root-cause finding, a refund request, an approval decision, a check run, a check line, a take-back notice, a set of offset lines, an unclaimed-property record or a compliance report — return `201 Created`."

    Design: Corner/entities/payer_creation_returns_201_with_declared_fields_and_common_fields
    """
    payload = create_payer_payload(
        name="Meridian Commercial", payer_code="COM", payer_type="COMMERCIAL",
        take_back_allowed=False, refund_remit_days=45,
    )
    response = api.create_payer(payload, ADMIN)
    payer = validate_success(response, 201)

    assert_payer(payer)
    assert payer["name"] == "Meridian Commercial"
    assert payer["payer_code"] == "COM"
    assert payer["payer_type"] == "COMMERCIAL"
    assert payer["take_back_allowed"] is False
    assert payer["refund_remit_days"] == 45
    assert payer["version"] == 1, "a freshly created row starts at version 1"

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_payer_optional_switches_take_their_declared_defaults(api):
    """PRD §3.1: "Two optional switches shape the payer's later behaviour: `take_back_allowed` decides whether this payer may ever file a recoupment notice and defaults to true, and `refund_remit_days` records the contractual number of days the hospital has to remit a refund to this payer and defaults to 30."

    Design: Corner/entities/payer_defaults_applied_when_optional_fields_omitted
    """
    payer = validate_success(
        api.create_payer(
            create_payer_payload(
                name="Medicare Region A", payer_code="MCR", payer_type="MEDICARE"
            ),
            ADMIN,
        ),
        201,
    )
    assert payer["take_back_allowed"] is True
    assert payer["refund_remit_days"] == 30


def test_duplicate_payer_code_is_rejected(api):
    """PRD §3.1: "The `payer_code` must be between 2 and 16 characters and must be globally unique; a collision is rejected with `ERR_DUPLICATE_PAYER_CODE`."

    Design: Corner/validations/duplicate_payer_code_is_rejected
    """
    seed_payer(payer_code="COM", payer_type="COMMERCIAL", name="Meridian Commercial")

    response = api.create_payer(
        create_payer_payload(
            name="Meridian Commercial East", payer_code="COM", payer_type="TRICARE"
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_PAYER_CODE.value)

    _, meta = validate_paginated(api.list_payers(ADMIN))
    assert meta["total_count"] == 1, "the collision must not have stored a second payer"


def test_patient_account_missing_primary_payer_id_is_invalid_request(api):
    """PRD §3.1: "Each carries a globally unique hospital `account_number` — a duplicate is rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER` — plus an `mrn` medical record number, a `patient_name` for the patient or guarantor, a `guarantor_state_code` of `CA`, `TX`, `NY` or `FL`, a `primary_payer_id` naming the payer of record, and a `financial_class` of `INPATIENT`, `OUTPATIENT` or `EMERGENCY`."
    PRD §2.4: "Any request whose body is missing a required field, carries an enum value outside the declared member set, carries a non-integer where an integer is required, carries a negative value in a cents field whose definition forbids one, or supplies an empty `target_account_ids` array is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/patient_account_missing_required_field_returns_invalid_request
    """
    seed_payer(payer_code="COM", payer_type="COMMERCIAL")

    response = api.create_patient_account(
        {
            "account_number": "ACCT-X1",
            "mrn": "MRN-X1",
            "patient_name": "No Payer",
            "guarantor_state_code": "CA",
            "financial_class": "INPATIENT",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_patient_accounts(ADMIN))
    assert meta["total_count"] == 0, "a rejected create must store nothing"


def test_patient_account_guarantor_state_outside_the_member_set_is_rejected(api):
    """PRD §3.1: "Each carries a globally unique hospital `account_number` — a duplicate is rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER` — plus an `mrn` medical record number, a `patient_name` for the patient or guarantor, a `guarantor_state_code` of `CA`, `TX`, `NY` or `FL`, a `primary_payer_id` naming the payer of record, and a `financial_class` of `INPATIENT`, `OUTPATIENT` or `EMERGENCY`."
    PRD §2.4: "Any request whose body is missing a required field, carries an enum value outside the declared member set, carries a non-integer where an integer is required, carries a negative value in a cents field whose definition forbids one, or supplies an empty `target_account_ids` array is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/patient_account_invalid_enum_guarantor_state_rejected
    """
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")

    response = api.create_patient_account(
        create_patient_account_payload(
            payer["id"], account_number="ACCT-X2", mrn="MRN-X2",
            patient_name="Bad State", guarantor_state_code="ZZ",
            financial_class="INPATIENT",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_account_number_is_rejected(api):
    """PRD §3.1: "Each carries a globally unique hospital `account_number` — a duplicate is rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER` — plus an `mrn` medical record number, a `patient_name` for the patient or guarantor, a `guarantor_state_code` of `CA`, `TX`, `NY` or `FL`, a `primary_payer_id` naming the payer of record, and a `financial_class` of `INPATIENT`, `OUTPATIENT` or `EMERGENCY`."

    Design: Corner/validations/duplicate_account_number_is_rejected
    """
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")
    seed_account(payer["id"], account_number="ACCT-DUP", state_code="CA",
                 financial_class="INPATIENT", patient_name="Dup One")

    response = api.create_patient_account(
        create_patient_account_payload(
            payer["id"], account_number="ACCT-DUP", mrn="MRN-D2",
            patient_name="Dup Two", guarantor_state_code="TX",
            financial_class="OUTPATIENT",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACCOUNT_NUMBER.value)

    _, meta = validate_paginated(api.list_patient_accounts(ADMIN))
    assert meta["total_count"] == 1


def test_patient_account_listing_reports_total_count_and_has_more(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` indicates whether rows remain beyond the current window."

    Design: Corner/entities/patient_account_listing_is_paginated_with_total_count_and_has_more
    """
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")
    for suffix in ("PG1", "PG2", "PG3"):
        seed_account(payer["id"], account_number=f"ACCT-{suffix}",
                     financial_class="INPATIENT")

    first_response = api.list_patient_accounts(ANALYST, params={"limit": 2, "offset": 0})
    first_page, first_meta = validate_paginated(first_response)
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_response.json()["response_type"] == "array"

    second_response = api.list_patient_accounts(ANALYST, params={"limit": 2, "offset": 2})
    second_page, second_meta = validate_paginated(second_response)
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_response.json()["response_type"] == "array"


def test_account_transaction_is_an_append_only_audit_record(api):
    """PRD §2.4: "Two entity types are deliberate exceptions: an `AccountTransaction` and a `RefundApproval` are immutable audit records, and they carry only `id` and `created_at`; neither `updated_at` nor `version` exists on them at all."
    PRD §3.1: "When `effective_at` is omitted it defaults to the posting's `posted_at`, which is itself stamped from the logical clock."
    PRD §2.9: "An account's `last_activity_at` is the latest `posted_at` across the transactions on that account that have not been reversed; it is null when the account has no such transaction."

    Design: Corner/entities/account_transaction_is_append_only_with_no_version_field
    """
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")
    account = seed_account(payer["id"], account_number="ACCT-IM1",
                           financial_class="INPATIENT", patient_name="Ida Munn")
    posted = post_txn(account["id"], "CHARGE", 10_000, "SYSTEM")

    txn = validate_success(api.get_account_transaction(posted["id"], ANALYST))
    assert_account_transaction(txn)
    assert "version" not in txn, "an immutable audit record exposes no version"
    assert "updated_at" not in txn, "an immutable audit record exposes no updated_at"
    assert_instant_equals(txn["posted_at"], "2026-08-01T00:00:00Z", "posted_at")
    assert_instant_equals(txn["effective_at"], "2026-08-01T00:00:00Z", "effective_at")
    assert txn["is_reversed"] is False
    assert txn["reversal_of_transaction_id"] is None

    account = read_account(account["id"])
    assert account["balance_cents"] == 10_000
    assert_instant_equals(
        account["last_activity_at"], "2026-08-01T00:00:00Z", "last_activity_at"
    )


def test_posting_against_an_unknown_account_reports_account_not_found(api):
    """PRD §2.4: "Path identifiers are resolved strictly left to right. A request naming several path segments that each carry an id resolves the leftmost first; if that id does not match a stored row the request fails immediately with that entity's not-found error and no further segment is examined."

    Design: Corner/entities/patient_account_transaction_against_unknown_account_returns_not_found
    """
    response = api.post_account_transaction(
        NON_EXISTENT,
        create_transaction_payload("CHARGE", 1_000, "SYSTEM"),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


def test_payer_id_is_required_exactly_when_the_money_came_from_a_payer(api):
    """PRD §3.1: "If `source` is `PAYER` and `payer_id` is absent, or if `payer_id` is supplied while `source` is anything other than `PAYER`, the posting is rejected with `ERR_TRANSACTION_PAYER_REQUIRED` (HTTP 422)."

    Design: Corner/validations/transaction_payer_id_required_when_source_is_payer_rejected_otherwise
    """
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")
    account = seed_account(payer["id"], account_number="ACCT-TP1",
                           financial_class="INPATIENT", patient_name="Tom Pike")

    missing_payer = api.post_account_transaction(
        account["id"],
        create_transaction_payload("PAYMENT", -5_000, "PAYER"),
        ANALYST,
    )
    validate_error(missing_payer, ApiErrorId.ERR_TRANSACTION_PAYER_REQUIRED.value)

    stray_payer = api.post_account_transaction(
        account["id"],
        create_transaction_payload("PAYMENT", -5_000, "PATIENT", payer_id=payer["id"]),
        ANALYST,
    )
    validate_error(stray_payer, ApiErrorId.ERR_TRANSACTION_PAYER_REQUIRED.value)

    _, meta = validate_paginated(
        api.list_account_transactions(ANALYST, params={"account_id": account["id"]})
    )
    assert meta["total_count"] == 0, "neither rejected posting may reach the ledger"
    assert read_account(account["id"])["balance_cents"] == 0


def test_account_carrying_open_credit_cannot_be_closed_but_may_go_bad_debt(api):
    """PRD §3.1: "An `OPEN` account may move to `BAD_DEBT`, and it may move to `CLOSED` only when its `credit_balance_cents` is exactly 0 — an account still carrying open credit liability is refused with `ERR_ACCOUNT_HAS_OPEN_CREDIT`."

    Design: Corner/validations/account_close_with_open_credit_balance_is_rejected
    """
    scenario = setup_identified_credit(account_number="ACCT-CL1",
                                       financial_class="INPATIENT")
    account_id = scenario["account"]["id"]

    close_attempt = api.set_patient_account_status(
        account_id, {"status": "CLOSED"}, ADMIN
    )
    validate_error(close_attempt, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_CREDIT.value)

    bad_debt = validate_success(
        api.set_patient_account_status(account_id, {"status": "BAD_DEBT"}, ADMIN)
    )
    assert bad_debt["status"] == "BAD_DEBT"

    account = read_account(account_id)
    assert account["status"] == "BAD_DEBT"
    assert account["credit_balance_cents"] == 12_000


def test_manual_reversal_writes_the_exact_negation_and_restores_the_balance(api):
    """PRD §3.1: "A `CreditAnalyst` may reverse a stored transaction, which writes a new `REVERSAL` row whose `amount_cents` is the exact negation of the target's, whose `reversal_of_transaction_id` points at the target, and which may carry its own `remark`."
    PRD §3.1: "The target's `is_reversed` flag becomes true — that flag is true precisely when some reversal row names the target — and the account's `balance_cents` is recomputed."

    Design: Difficulty/compensating_invariant/account_ledger_balance_conserved_across_posting_and_manual_reversal
    """
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")
    set_clock("2026-08-01T00:00:00Z")
    account = seed_account(payer["id"], account_number="ACCT-LG1", state_code="NY",
                           financial_class="INPATIENT", patient_name="Lena Gore")
    post_txn(account["id"], "CHARGE", 50_000, "SYSTEM")
    set_clock("2026-08-05T00:00:00Z")
    post_txn(account["id"], "PAYMENT", -62_000, "PATIENT")
    set_clock("2026-08-06T00:00:00Z")
    bad_posting = post_txn(account["id"], "PAYMENT", -9_000, "PATIENT",
                           remark="Posted to the wrong account")
    assert read_account(account["id"])["balance_cents"] == -21_000

    reversal = validate_success(
        api.reverse_account_transaction(
            bad_posting["id"], {"remark": "Correcting a wrong-account posting"}, ANALYST
        ),
        201,
    )

    assert reversal["txn_type"] == "REVERSAL"
    assert reversal["amount_cents"] == 9_000
    assert reversal["reversal_of_transaction_id"] == bad_posting["id"]
    assert read_transaction(bad_posting["id"])["is_reversed"] is True
    assert read_account(account["id"])["balance_cents"] == -12_000


def test_reversed_ledger_rows_both_survive_and_a_second_reversal_is_refused(api):
    """PRD §2.9: "An account's `balance_cents` is the sum of `amount_cents` over **all** transactions on that account, reversal rows included — a reversal row carries the exact negation of its target, so a reversed pair sums to zero without either row being deleted."
    PRD §3.1: "A transaction that already carries a reversal, or a transaction that is itself a `REVERSAL` row, cannot be reversed: the attempt fails with `ERR_TRANSACTION_ALREADY_REVERSED`."

    Design: Difficulty/compensating_invariant/account_ledger_balance_conserved_across_posting_and_manual_reversal
    """
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")
    set_clock("2026-08-01T00:00:00Z")
    account = seed_account(payer["id"], account_number="ACCT-LG1", state_code="NY",
                           financial_class="INPATIENT", patient_name="Lena Gore")
    post_txn(account["id"], "CHARGE", 50_000, "SYSTEM")
    set_clock("2026-08-05T00:00:00Z")
    post_txn(account["id"], "PAYMENT", -62_000, "PATIENT")
    set_clock("2026-08-06T00:00:00Z")
    bad_posting = post_txn(account["id"], "PAYMENT", -9_000, "PATIENT",
                           remark="Posted to the wrong account")
    validate_success(
        api.reverse_account_transaction(
            bad_posting["id"], {"remark": "Correcting a wrong-account posting"}, ANALYST
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_account_transactions(ANALYST, params={"account_id": account["id"]})
    )
    assert meta["total_count"] == 4, "no row is ever deleted by a reversal"
    assert sum(row["amount_cents"] for row in rows) == -12_000
    assert_ledger_invariant(read_account(account["id"]), rows)

    second_attempt = api.reverse_account_transaction(
        bad_posting["id"], {"remark": "Second attempt"}, ANALYST
    )
    validate_error(second_attempt, ApiErrorId.ERR_TRANSACTION_ALREADY_REVERSED.value)


def test_account_rollups_recompute_after_every_posting_and_status_move(api):
    """PRD §2.9: "An account's `balance_cents` is the sum of `amount_cents` over **all** transactions on that account, reversal rows included — a reversal row carries the exact negation of its target, so a reversed pair sums to zero without either row being deleted."
    PRD §2.9: "An account's `credit_balance_cents` is the sum of `credit_amount_cents` over the credit balance rows on that account whose `status` is `IDENTIFIED`, `UNDER_REVIEW`, `ATTRIBUTED` or `REFUND_PENDING`; those four statuses constitute open credit liability, and a credit balance in any other status contributes nothing."
    PRD §2.9: "An account's `last_activity_at` is the latest `posted_at` across the transactions on that account that have not been reversed; it is null when the account has no such transaction."

    Design: Corner/cross_cutting_layers/derived_account_rollups_recompute_after_every_posting_and_status_move
    """
    set_clock("2026-08-01T00:00:00Z")
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")
    account = seed_account(payer["id"], account_number="ACCT-DR1",
                           financial_class="INPATIENT", patient_name="Dot Ryan")

    post_txn(account["id"], "CHARGE", 50_000, "SYSTEM")
    after_charge = read_account(account["id"])
    assert after_charge["balance_cents"] == 50_000
    assert after_charge["credit_balance_cents"] == 0
    assert_instant_equals(
        after_charge["last_activity_at"], "2026-08-01T00:00:00Z", "last_activity_at"
    )

    set_clock("2026-08-05T00:00:00Z")
    post_txn(account["id"], "PAYMENT", -62_000, "PATIENT")
    after_payment = read_account(account["id"])
    assert after_payment["balance_cents"] == -12_000
    assert_instant_equals(
        after_payment["last_activity_at"], "2026-08-05T00:00:00Z", "last_activity_at"
    )

    set_clock("2026-08-15T00:00:00Z")
    sweep = run_identify_sweep([account["id"]])
    credit_balance_id = sweep["credit_balance_ids"][0]
    assert read_account(account["id"])["credit_balance_cents"] == 12_000

    reviewed = start_review(credit_balance_id)
    assert reviewed["outstanding_cents"] == 12_000
    assert read_account(account["id"])["credit_balance_cents"] == 12_000

    attributed = attribute(credit_balance_id, "PROPORTIONAL")
    assert attributed["patient_portion_cents"] == 12_000
    final_account = read_account(account["id"])
    assert final_account["credit_balance_cents"] == 12_000
    assert final_account["balance_cents"] == -12_000
    assert_patient_account(final_account)
