"""Debt referral defaults, activation gates, and the cyclic debt lifecycle."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    activate_debt as activate_debt_helper,
    add_payment,
    assert_debt,
    create_active_policy,
    create_federal_creditor,
    create_payment_file,
    create_state_creditor,
    decide_claim,
    evaluate_payment,
    execute_payment,
    file_refund_claim,
    list_payment_offsets,
    make_creditor_analyst_headers,
    read_debt,
    read_payment,
    record_notice,
    refer_debt,
    register_eft_payee,
    reverse_payment,
    review_claim,
    set_logical_clock,
    validate_error,
    validate_success,
)
from test_helpers import DEFAULT_NOTICE_SENT_AT

AUDITOR = TEST_USERS["auditor_headers"]


def test_debt_create_defaults_and_starts_referred(api):
    """PRD §3.3: "A debt referred with a `notice_sent_at` starts directly in
    `NOTICED`; without one it starts in `REFERRED`."
    PRD §3.3: "`current_balance_cents` initializes to the referred
    `original_amount_cents`".
    PRD §3.3: "A third counter, `returned_count`, starts at 0".

    Design: Corner/entities/debt_create_defaults_and_starts_referred
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    debt = refer_debt(creditor, original_amount_cents=50000)
    assert_debt(debt)
    assert debt["status"] == "REFERRED"
    assert debt["current_balance_cents"] == 50000
    assert debt["returned_count"] == 0
    assert debt["priority_rank"] == 30


def test_debt_get_unknown_id_returns_not_found(api):
    """PRD §2.8: "Identifiers in the path exist, validated left to right,
    failing on the first missing one — otherwise `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/debt_get_unknown_id_returns_not_found
    """
    set_logical_clock()
    resp = api.get_debt(NON_EXISTENT_UUID, AUDITOR)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert err["error_id"] == "ERR_NOT_FOUND" and err["message"]


def test_debt_priority_rank_computed_from_debt_type(api):
    """PRD §3.3: "`priority_rank` maps from the debt type — `CHILD_SUPPORT`
    ranks 10, `FEDERAL_TAX` ranks 20, `FEDERAL_NONTAX` ranks 30, `STATE_TAX`
    ranks 40, and `STATE_OTHER` ranks 50 — and lower ranks offset first in the
    waterfall (§3.4), with `delinquent_since` as the first tie-break."

    Design: Corner/entities/debt_priority_rank_computed_from_debt_type
    """
    set_logical_clock()
    cred_fed = create_federal_creditor()
    cred_wa = create_state_creditor("WA", creditor_code="WA-DOR")
    debt_cs = refer_debt(
        cred_fed, debt_type="CHILD_SUPPORT", original_amount_cents=10000
    )
    debt_so = refer_debt(
        cred_wa, debt_type="STATE_OTHER", original_amount_cents=10000
    )
    assert debt_cs["priority_rank"] == 10
    assert debt_so["priority_rank"] == 50
    assert debt_cs["status"] == "REFERRED"
    assert debt_so["status"] == "REFERRED"


def test_debt_activate_from_referred_returns_invalid_state(api):
    """PRD §3.3: "A debt in any state other than `NOTICED` cannot be activated
    at all (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/debt_activate_from_referred_returns_invalid_state
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    debt = refer_debt(creditor)
    resp = api.activate_debt(
        debt["id"], make_creditor_analyst_headers(creditor["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert read_debt(debt["id"])["status"] == "REFERRED"


def test_due_process_attestation_required_for_activation(api):
    """PRD §3.3: "The creditor must have attested `due_process_completed` —
    otherwise `ERR_DUE_PROCESS_NOT_COMPLETED`."

    Design: Corner/validations/due_process_attestation_required_for_activation
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    # Notice window has elapsed (notice 31 days before the clock); only the
    # due-process attestation is missing.
    debt = refer_debt(
        creditor,
        notice_sent_at=DEFAULT_NOTICE_SENT_AT,
        due_process_completed=False,
    )
    assert debt["status"] == "NOTICED"
    resp = api.activate_debt(
        debt["id"], make_creditor_analyst_headers(creditor["id"])
    )
    err = validate_error(resp, ApiErrorId.ERR_DUE_PROCESS_NOT_COMPLETED)
    assert err["error_id"] != "ERR_NOTICE_WINDOW_NOT_ELAPSED"
    assert read_debt(debt["id"])["status"] == "NOTICED"


def test_notice_window_exact_30_days(api):
    """PRD §3.3: "The logical clock must have reached at least thirty days after
    `notice_sent_at`, with equality activating — an earlier attempt is
    `ERR_NOTICE_WINDOW_NOT_ELAPSED`."
    PRD §2.5: "`version` (integer): a system-managed integer that increments
    with every mutation of the resource".

    Design: Difficulty/boundary_precision_check/notice_window_exact_30_days
    """
    creditor = create_federal_creditor()
    analyst = make_creditor_analyst_headers(creditor["id"])
    debt = refer_debt(
        creditor,
        notice_sent_at="2026-09-01T00:00:00Z",
        due_process_completed=True,
    )
    version_at_create = debt["version"]

    set_logical_clock("2026-09-30T23:59:59Z")  # one second short of 30 days
    resp_early = api.activate_debt(debt["id"], analyst)
    validate_error(resp_early, ApiErrorId.ERR_NOTICE_WINDOW_NOT_ELAPSED)
    assert read_debt(debt["id"])["version"] == version_at_create, (
        "the rejected activation must not mutate the debt"
    )

    set_logical_clock("2026-10-01T00:00:00Z")  # exactly notice_sent_at + 30 days
    resp_ok = api.activate_debt(debt["id"], analyst)
    activated = validate_success(resp_ok)
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == version_at_create + 1


def test_debt_cyclic_referral_and_reopen(api):
    """PRD §3.3: "The same recording also takes a `RETURNED` debt back to
    `NOTICED`: re-referral always requires a fresh notice window, so both
    transitions write fresh values from the request rather than preserving
    anything old."
    PRD §3.3: "A payment reversal restores balance and reopens a `PAID_IN_FULL`
    debt to `ACTIVE` (§3.5), while an approved refund instead sends the debt —
    whether still `ACTIVE` or already `PAID_IN_FULL` — to `RETURNED` without
    restoring its balance".

    Design: Difficulty/non_linear_state_machine/debt_cyclic_referral_and_reopen
    """
    set_logical_clock()
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("SALARY", "FULL")

    debt = refer_debt(creditor, original_amount_cents=50000)
    assert debt["status"] == "REFERRED"
    debt = record_notice(debt, creditor)
    assert debt["status"] == "NOTICED"
    debt = activate_debt_helper(debt, creditor)
    assert debt["status"] == "ACTIVE"

    payment_file = create_payment_file()
    pay_1 = add_payment(payment_file, payee, 30000, "SALARY")
    pay_1 = evaluate_payment(pay_1)
    execute_payment(pay_1)
    debt = read_debt(debt["id"])
    assert (debt["status"], debt["current_balance_cents"]) == ("ACTIVE", 20000)

    offset = list_payment_offsets(pay_1["id"])[0]
    claim = decide_claim(review_claim(file_refund_claim(offset)), "APPROVE")
    assert claim["status"] == "PAID"
    debt = read_debt(debt["id"])
    # Refund semantics: RETURNED, returned_count incremented, balance NOT restored.
    assert debt["status"] == "RETURNED"
    assert debt["returned_count"] == 1
    assert debt["current_balance_cents"] == 20000

    # The re-referral cycle closes through a fresh notice window.
    debt = record_notice(debt, creditor, notice_sent_at="2026-08-02T00:00:00Z")
    assert debt["status"] == "NOTICED"
    debt = activate_debt_helper(debt, creditor)
    assert debt["status"] == "ACTIVE"

    pay_2 = add_payment(payment_file, payee, 20000, "SALARY")
    pay_2 = evaluate_payment(pay_2)
    execute_payment(pay_2)
    debt = read_debt(debt["id"])
    assert (debt["status"], debt["current_balance_cents"]) == ("PAID_IN_FULL", 0)

    reverse_payment(pay_2)
    debt = read_debt(debt["id"])
    # Reversal semantics: balance restored, PAID_IN_FULL reopens to ACTIVE.
    assert debt["status"] == "ACTIVE"
    assert debt["current_balance_cents"] == 20000
    assert read_payment(pay_2["id"])["processing_status"] == "REVERSED"
