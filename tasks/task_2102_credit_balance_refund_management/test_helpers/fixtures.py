"""Composite setup helpers.

Every helper here drives the live API only — nothing is seeded server side, so
each test rebuilds all of its preconditions from scratch. Setup calls use the
lenient validator so a broken precondition surfaces as "Setup step failed"
rather than as a confusing assertion deep inside a test.

Time is always driven through the logical clock endpoint; no helper ever reads
real wall-clock time.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    T_2026_08_01, T_2026_08_05, T_2026_08_15, T_2026_08_16, T_2026_08_18,
    T_2026_08_20,
)
from .factories import (
    create_compliance_report_payload, create_decision_payload,
    create_escheatment_record_payload, create_offset_application_payload,
    create_patient_account_payload, create_payer_payload,
    create_refund_batch_payload, create_refund_request_payload,
    create_root_cause_finding_payload, create_take_back_notice_payload,
    create_transaction_payload,
)
from .test_users import TEST_USERS, make_payer_liaison_headers

ANALYST = TEST_USERS["credit_analyst_headers"]
APPROVER = TEST_USERS["refund_approver_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


# =============================================================================
# Primitives
# =============================================================================

def set_clock(to_iso8601: str, headers=None) -> dict:
    """Reposition the logical clock. Returns the clock payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or ADMIN)
    )


def run_ops_checkpoint(headers=None) -> dict:
    """Run the nightly operations checkpoint."""
    return get_success_data(api_client.run_aging_sweep(headers or ADMIN))


def seed_payer(payer_code="COM", payer_type="COMMERCIAL", name=None, **overrides) -> dict:
    payload = create_payer_payload(
        name=name or f"Payer {payer_code}",
        payer_code=payer_code,
        payer_type=payer_type,
        **overrides,
    )
    return get_success_data(api_client.create_payer(payload, ADMIN))


def seed_account(payer_id, account_number="ACCT-1", state_code="CA",
                 financial_class="OUTPATIENT", patient_name=None, **overrides) -> dict:
    payload = create_patient_account_payload(
        payer_id,
        account_number=account_number,
        mrn=f"MRN-{account_number}",
        patient_name=patient_name or f"Patient {account_number}",
        guarantor_state_code=state_code,
        financial_class=financial_class,
        **overrides,
    )
    return get_success_data(api_client.create_patient_account(payload, ADMIN))


def post_txn(account_id, txn_type, amount_cents, source, headers=None, **overrides) -> dict:
    payload = create_transaction_payload(txn_type, amount_cents, source, **overrides)
    return get_success_data(
        api_client.post_account_transaction(account_id, payload, headers or ANALYST)
    )


def reverse_txn(transaction_id, remark=None, headers=None) -> dict:
    payload = {} if remark is None else {"remark": remark}
    return get_success_data(
        api_client.reverse_account_transaction(
            transaction_id, payload, headers or ANALYST
        )
    )


def move_account_status(account_id, status) -> dict:
    return get_success_data(
        api_client.set_patient_account_status(account_id, {"status": status}, ADMIN)
    )


def run_identify_sweep(account_ids=None, headers=None) -> dict:
    payload = {} if account_ids is None else {"account_ids": list(account_ids)}
    return get_success_data(
        api_client.run_identify_sweep(payload, headers or ANALYST)
    )


def start_review(credit_balance_id, headers=None) -> dict:
    return get_success_data(
        api_client.start_credit_balance_review(
            credit_balance_id, {}, headers or ANALYST
        )
    )


def attribute(credit_balance_id, attribution_method="PROPORTIONAL", headers=None) -> dict:
    return get_success_data(
        api_client.attribute_credit_balance(
            credit_balance_id, {"attribution_method": attribution_method},
            headers or ANALYST,
        )
    )


def file_root_cause_finding(credit_balance_id, confirmed=True, headers=None,
                            **overrides) -> dict:
    payload = create_root_cause_finding_payload(
        credit_balance_id, confirmed=confirmed, **overrides
    )
    return get_success_data(
        api_client.create_root_cause_finding(payload, headers or ANALYST)
    )


def write_off(credit_balance_id, reason_code="DE_MINIMIS", headers=None) -> dict:
    return get_success_data(
        api_client.write_off_credit_balance(
            credit_balance_id, {"reason_code": reason_code}, headers or COMPLIANCE
        )
    )


def prepare_refund_request(credit_balance_id, requested_amount_cents, payee_type,
                           expected_credit_balance_version, headers=None,
                           **overrides) -> dict:
    payload = create_refund_request_payload(
        credit_balance_id, requested_amount_cents, payee_type,
        expected_credit_balance_version, **overrides,
    )
    return get_success_data(
        api_client.create_refund_request(payload, headers or ANALYST)
    )


def submit_request(refund_request_id, headers=None) -> dict:
    return get_success_data(
        api_client.submit_refund_request(refund_request_id, {}, headers or ANALYST)
    )


def decide_request(refund_request_id, decision="APPROVED", approver_tier=3,
                   headers=None, **overrides) -> dict:
    payload = create_decision_payload(decision, approver_tier, **overrides)
    return get_success_data(
        api_client.decide_refund_request(
            refund_request_id, payload, headers or APPROVER
        )
    )


def open_batch(batch_number="B-1", cutoff_at=T_2026_08_18,
               scheduled_run_at=T_2026_08_20, bank_account_code="OPERATING") -> dict:
    payload = create_refund_batch_payload(
        batch_number, cutoff_at, scheduled_run_at,
        bank_account_code=bank_account_code,
    )
    return get_success_data(api_client.create_refund_batch(payload, OFFICER))


def add_batch_item(batch_id, refund_request_id) -> dict:
    return get_success_data(
        api_client.add_refund_batch_item(
            batch_id, {"refund_request_id": refund_request_id}, OFFICER
        )
    )


def read_batch(batch_id) -> dict:
    return get_success_data(api_client.get_refund_batch(batch_id, OFFICER))


def lock_batch(batch_id, expected_refund_batch_version=None) -> dict:
    if expected_refund_batch_version is None:
        expected_refund_batch_version = read_batch(batch_id)["version"]
    return get_success_data(
        api_client.lock_refund_batch(
            batch_id,
            {"expected_refund_batch_version": expected_refund_batch_version},
            OFFICER,
        )
    )


def unlock_batch(batch_id) -> dict:
    return get_success_data(api_client.unlock_refund_batch(batch_id, {}, OFFICER))


def issue_batch(batch_id, starting_check_number=100001) -> dict:
    return get_success_data(
        api_client.issue_refund_batch(
            batch_id, {"starting_check_number": starting_check_number}, OFFICER
        )
    )


def clear_check(check_id) -> dict:
    return get_success_data(api_client.clear_check(check_id, {}, OFFICER))


def void_check(check_id, void_reason="WRONG_PAYEE") -> dict:
    return get_success_data(
        api_client.void_check(check_id, {"void_reason": void_reason}, OFFICER)
    )


def reissue_check(check_id, refund_batch_id) -> dict:
    return get_success_data(
        api_client.reissue_check(
            check_id, {"refund_batch_id": refund_batch_id}, OFFICER
        )
    )


def record_take_back_notice(payer_id, notice_number, total_recoup_cents,
                            admin_fee_cents=None, headers=None) -> dict:
    extra = {} if admin_fee_cents is None else {"admin_fee_cents": admin_fee_cents}
    payload = create_take_back_notice_payload(
        payer_id, notice_number, total_recoup_cents, **extra
    )
    return get_success_data(
        api_client.create_take_back_notice(
            payload, headers or make_payer_liaison_headers(payer_id)
        )
    )


def apply_offsets(notice_id, target_account_ids, expected_take_back_notice_version,
                  headers=None) -> list:
    payload = create_offset_application_payload(
        target_account_ids, expected_take_back_notice_version
    )
    return get_success_data(
        api_client.apply_offsets(notice_id, payload, headers or ANALYST)
    )


def reverse_offset(offset_application_id, reason=None, headers=None) -> dict:
    payload = {} if reason is None else {"reason": reason}
    return get_success_data(
        api_client.reverse_offset_application(
            offset_application_id, payload, headers or ANALYST
        )
    )


def dispute_notice(notice_id, payer_id, dispute_reason="Provider contests the basis") -> dict:
    return get_success_data(
        api_client.dispute_take_back_notice(
            notice_id, {"dispute_reason": dispute_reason},
            make_payer_liaison_headers(payer_id),
        )
    )


def withdraw_dispute(notice_id, payer_id) -> dict:
    return get_success_data(
        api_client.withdraw_take_back_dispute(
            notice_id, {}, make_payer_liaison_headers(payer_id)
        )
    )


def report_obligation(obligation_id, report_reference="CBR-1") -> dict:
    return get_success_data(
        api_client.report_medicare_obligation(
            obligation_id, {"report_reference": report_reference}, COMPLIANCE
        )
    )


def open_escheatment_record(check_disbursement_id, basis=None) -> dict:
    extra = {} if basis is None else {"basis": basis}
    payload = create_escheatment_record_payload(check_disbursement_id, **extra)
    return get_success_data(
        api_client.create_escheatment_record(payload, COMPLIANCE)
    )


def record_due_diligence(escheatment_record_id, contact_method="CERTIFIED_MAIL") -> dict:
    return get_success_data(
        api_client.record_due_diligence(
            escheatment_record_id, {"contact_method": contact_method}, COMPLIANCE
        )
    )


def remit_escheatment(escheatment_record_id) -> dict:
    return get_success_data(
        api_client.remit_escheatment_record(escheatment_record_id, {}, COMPLIANCE)
    )


def create_report(report_type, scope_code, period_start_at, period_end_at,
                  as_of_at) -> dict:
    payload = create_compliance_report_payload(
        report_type, scope_code, period_start_at, period_end_at, as_of_at
    )
    return get_success_data(
        api_client.create_compliance_report(payload, COMPLIANCE)
    )


def finalize_report(report_id) -> dict:
    return get_success_data(
        api_client.finalize_compliance_report(report_id, {}, COMPLIANCE)
    )


# --- Read helpers ------------------------------------------------------------

def read_account(account_id) -> dict:
    return get_success_data(api_client.get_patient_account(account_id, ANALYST))


def read_credit_balance(credit_balance_id) -> dict:
    return get_success_data(api_client.get_credit_balance(credit_balance_id, ANALYST))


def read_refund_request(refund_request_id) -> dict:
    return get_success_data(api_client.get_refund_request(refund_request_id, ANALYST))


def read_check(check_id) -> dict:
    return get_success_data(api_client.get_check_disbursement(check_id, OFFICER))


def read_notice(notice_id) -> dict:
    return get_success_data(api_client.get_take_back_notice(notice_id, ANALYST))


def read_offset(offset_application_id) -> dict:
    return get_success_data(
        api_client.get_offset_application(offset_application_id, ANALYST)
    )


def read_obligation(obligation_id) -> dict:
    return get_success_data(
        api_client.get_medicare_obligation(obligation_id, COMPLIANCE)
    )


def read_escheatment(escheatment_record_id) -> dict:
    return get_success_data(
        api_client.get_escheatment_record(escheatment_record_id, COMPLIANCE)
    )


def read_report(report_id) -> dict:
    return get_success_data(api_client.get_compliance_report(report_id, COMPLIANCE))


def read_transaction(transaction_id) -> dict:
    return get_success_data(
        api_client.get_account_transaction(transaction_id, ANALYST)
    )


def find_obligation_for_credit_balance(credit_balance_id) -> dict:
    """Return the Medicare repayment obligation attached to a credit balance."""
    rows = get_success_data(
        api_client.list_medicare_obligations(
            COMPLIANCE, params={"credit_balance_id": credit_balance_id}
        )
    )
    assert rows, f"Setup step failed: no Medicare obligation for {credit_balance_id}"
    return rows[0]


def list_transactions(account_id, txn_type=None) -> list:
    params = {"account_id": account_id}
    if txn_type is not None:
        params["txn_type"] = txn_type
    return get_success_data(
        api_client.list_account_transactions(ANALYST, params=params)
    )


# =============================================================================
# Composite scenario builders
# =============================================================================

def setup_identified_credit(
    *,
    payer_type="COMMERCIAL",
    payer_code="COM",
    payer_name=None,
    take_back_allowed=None,
    account_number="ACCT-1",
    state_code="CA",
    financial_class="OUTPATIENT",
    patient_name=None,
    charge_cents=50_000,
    payment_cents=-62_000,
    payment_source="PATIENT",
    payment_txn_type="PAYMENT",
    charge_at=T_2026_08_01,
    payment_at=T_2026_08_05,
    sweep_at=T_2026_08_15,
) -> dict:
    """Payer + account + one CHARGE + one PAYMENT + an identification sweep.

    Leaves exactly one CreditBalance in status IDENTIFIED whose
    credit_amount_cents is the magnitude of the account's negative balance.
    Returns {"payer", "account", "credit_balance", "sweep"}.
    """
    set_clock(charge_at)
    payer_kwargs = {}
    if take_back_allowed is not None:
        payer_kwargs["take_back_allowed"] = take_back_allowed
    payer = seed_payer(
        payer_code=payer_code, payer_type=payer_type, name=payer_name, **payer_kwargs
    )
    account = seed_account(
        payer["id"], account_number=account_number, state_code=state_code,
        financial_class=financial_class, patient_name=patient_name,
    )
    post_txn(account["id"], "CHARGE", charge_cents, "SYSTEM")

    set_clock(payment_at)
    extra = {"payer_id": payer["id"]} if payment_source == "PAYER" else {}
    post_txn(
        account["id"], payment_txn_type, payment_cents, payment_source, **extra
    )

    set_clock(sweep_at)
    sweep = run_identify_sweep([account["id"]])
    credit_balance_id = sweep["credit_balance_ids"][0]
    return {
        "payer": payer,
        "account": account,
        "credit_balance": read_credit_balance(credit_balance_id),
        "sweep": sweep,
    }


def setup_attributed_credit(
    *,
    attribution_method="PROPORTIONAL",
    root_cause_confirmed=None,
    **identify_kwargs,
) -> dict:
    """setup_identified_credit + optional root-cause finding + review + attribution.

    `root_cause_confirmed=None` files no finding at all (root_cause_confirmed
    stays false, which escalates the approval tier by one).
    Returns {"payer", "account", "credit_balance"} with the credit balance read
    back after attribution, so its `version` is the one a refund request must
    declare.
    """
    scenario = setup_identified_credit(**identify_kwargs)
    credit_balance_id = scenario["credit_balance"]["id"]
    if root_cause_confirmed is not None:
        file_root_cause_finding(credit_balance_id, confirmed=root_cause_confirmed)
    start_review(credit_balance_id)
    scenario["credit_balance"] = attribute(credit_balance_id, attribution_method)
    return scenario


def setup_multi_credit_scenario(
    *,
    accounts,
    payer_type="COMMERCIAL",
    payer_code="COM",
    payer_name=None,
    take_back_allowed=None,
    state_code="CA",
    financial_class="OUTPATIENT",
    charge_at=T_2026_08_01,
    payment_at=T_2026_08_05,
    sweep_at=T_2026_08_15,
) -> dict:
    """One payer, several accounts, one identification sweep over all of them.

    `accounts` is a list of dicts accepting account_number, charge_cents,
    payment_cents, payment_source, state_code, financial_class and patient_name.
    `state_code` and `financial_class` supply the default for any spec that does
    not name its own. Accounts are created in list order, so the sweep processes
    them in that order too.
    Returns {"payer", "accounts", "credit_balances", "sweep"}.
    """
    set_clock(charge_at)
    payer_kwargs = {}
    if take_back_allowed is not None:
        payer_kwargs["take_back_allowed"] = take_back_allowed
    payer = seed_payer(
        payer_code=payer_code, payer_type=payer_type, name=payer_name, **payer_kwargs
    )

    created = []
    for spec in accounts:
        created.append(
            seed_account(
                payer["id"],
                account_number=spec["account_number"],
                state_code=spec.get("state_code", state_code),
                financial_class=spec.get("financial_class", financial_class),
                patient_name=spec.get("patient_name"),
            )
        )
    for account, spec in zip(created, accounts):
        post_txn(account["id"], "CHARGE", spec.get("charge_cents", 50_000), "SYSTEM")

    set_clock(payment_at)
    for account, spec in zip(created, accounts):
        source = spec.get("payment_source", "PATIENT")
        extra = {"payer_id": payer["id"]} if source == "PAYER" else {}
        post_txn(
            account["id"], spec.get("payment_txn_type", "PAYMENT"),
            spec.get("payment_cents", -62_000), source, **extra,
        )

    set_clock(sweep_at)
    sweep = run_identify_sweep([a["id"] for a in created])
    credit_balances = [
        read_credit_balance(cb_id) for cb_id in sweep["credit_balance_ids"]
    ]
    return {
        "payer": payer,
        "accounts": created,
        "credit_balances": credit_balances,
        "sweep": sweep,
    }


def attribute_all(credit_balance_ids, attribution_method="PROPORTIONAL") -> list:
    """Walk each credit balance IDENTIFIED -> UNDER_REVIEW -> ATTRIBUTED."""
    results = []
    for credit_balance_id in credit_balance_ids:
        start_review(credit_balance_id)
        results.append(attribute(credit_balance_id, attribution_method))
    return results


def setup_approved_refund_request(
    credit_balance,
    *,
    requested_amount_cents,
    payee_type="PATIENT",
    payee_state_code="CA",
    payee_name="Test Payee",
    approver_tier=3,
    approver_headers=None,
    analyst_headers=None,
) -> dict:
    """Prepare + submit + approve one refund request against `credit_balance`.

    `credit_balance` must be the freshly read ATTRIBUTED row so its `version`
    satisfies the create's expected_credit_balance_version precondition.
    """
    request = prepare_refund_request(
        credit_balance["id"], requested_amount_cents, payee_type,
        credit_balance["version"], payee_state_code=payee_state_code,
        payee_name=payee_name, headers=analyst_headers,
    )
    submit_request(request["id"], headers=analyst_headers)
    decide_request(
        request["id"], "APPROVED", approver_tier, headers=approver_headers
    )
    return read_refund_request(request["id"])


def setup_issued_check_for_request(
    refund_request_id,
    *,
    batch_number="B-1",
    cutoff_at=T_2026_08_18,
    scheduled_run_at=T_2026_08_20,
    bank_account_code="OPERATING",
    issue_at=T_2026_08_20,
    starting_check_number=100001,
) -> dict:
    """Open a run, add the request, lock it, move the clock and issue.

    Returns {"batch", "check"} with both rows read back after the issue cascade.
    """
    batch = open_batch(
        batch_number, cutoff_at, scheduled_run_at, bank_account_code
    )
    check = add_batch_item(batch["id"], refund_request_id)
    lock_batch(batch["id"])
    set_clock(issue_at)
    batch = issue_batch(batch["id"], starting_check_number)
    return {"batch": batch, "check": read_check(check["id"])}


def setup_refunded_credit(
    *,
    requested_amount_cents=12_000,
    payee_type="PATIENT",
    payee_state_code="CA",
    approver_tier=3,
    batch_number="B-1",
    bank_account_code="OPERATING",
    cutoff_at=T_2026_08_18,
    scheduled_run_at=T_2026_08_20,
    issue_at=T_2026_08_20,
    starting_check_number=100001,
    request_at=T_2026_08_16,
    **attribute_kwargs,
) -> dict:
    """Full lifecycle: identified -> attributed -> approved -> batched -> issued.

    Returns {"payer", "account", "credit_balance", "refund_request", "batch",
    "check", "obligation"} where obligation is None unless the payer is
    MEDICARE with a positive payer portion.
    """
    scenario = setup_attributed_credit(**attribute_kwargs)
    obligation = None
    if scenario["payer"]["payer_type"] == "MEDICARE" and \
            scenario["credit_balance"]["payer_portion_cents"] > 0:
        obligation = find_obligation_for_credit_balance(
            scenario["credit_balance"]["id"]
        )
    if request_at is not None:
        set_clock(request_at)
    request = setup_approved_refund_request(
        scenario["credit_balance"],
        requested_amount_cents=requested_amount_cents,
        payee_type=payee_type,
        payee_state_code=payee_state_code,
        approver_tier=approver_tier,
    )
    issued = setup_issued_check_for_request(
        request["id"], batch_number=batch_number, cutoff_at=cutoff_at,
        scheduled_run_at=scheduled_run_at, bank_account_code=bank_account_code,
        issue_at=issue_at, starting_check_number=starting_check_number,
    )
    scenario.update(
        {
            "refund_request": read_refund_request(request["id"]),
            "batch": issued["batch"],
            "check": issued["check"],
            "obligation": obligation,
        }
    )
    scenario["credit_balance"] = read_credit_balance(
        scenario["credit_balance"]["id"]
    )
    return scenario


def advance_to_stale(stale_at, headers=None) -> dict:
    """Move the clock to `stale_at` and run the operations checkpoint."""
    set_clock(stale_at)
    return run_ops_checkpoint(headers)


def setup_stale_check(*, stale_at="2027-02-16T00:00:00Z", **refund_kwargs) -> dict:
    """setup_refunded_credit, then age the check ISSUED -> STALE via the checkpoint."""
    scenario = setup_refunded_credit(**refund_kwargs)
    scenario["checkpoint"] = advance_to_stale(stale_at)
    scenario["check"] = read_check(scenario["check"]["id"])
    return scenario


def setup_take_back_scenario(
    *,
    accounts,
    notice_number="TB-1",
    total_recoup_cents=10_000,
    admin_fee_cents=None,
    notice_at=T_2026_08_16,
    payer_code="MCR",
    payer_type="MEDICARE",
    attribution_method="PROPORTIONAL",
    **scenario_kwargs,
) -> dict:
    """Multi-account PAYER-attributed credits plus one recorded take-back notice.

    Returns {"payer", "accounts", "credit_balances", "notice"}.
    """
    scenario = setup_multi_credit_scenario(
        accounts=accounts, payer_code=payer_code, payer_type=payer_type,
        take_back_allowed=True, **scenario_kwargs,
    )
    scenario["credit_balances"] = attribute_all(
        [cb["id"] for cb in scenario["credit_balances"]], attribution_method
    )
    set_clock(notice_at)
    scenario["notice"] = record_take_back_notice(
        scenario["payer"]["id"], notice_number, total_recoup_cents,
        admin_fee_cents=admin_fee_cents,
    )
    return scenario


def setup_split_ledger_credits(
    *,
    account_numbers,
    payer_code="COM",
    payer_type="COMMERCIAL",
    state_code="TX",
    financial_class="OUTPATIENT",
    charge_cents=80_000,
    payer_payment_cents=-60_000,
    patient_payment_cents=-40_000,
    charge_at=T_2026_08_01,
    payer_payment_at=T_2026_08_05,
    patient_payment_at="2026-08-10T00:00:00Z",
    sweep_at=T_2026_08_15,
) -> dict:
    """N accounts with byte-identical ledgers: CHARGE, PAYER payment, later PATIENT payment.

    One identification sweep at `sweep_at` then produces one credit balance per
    account, all in status IDENTIFIED. Returns {"payer", "accounts",
    "credit_balances"}.
    """
    set_clock(charge_at)
    payer = seed_payer(payer_code=payer_code, payer_type=payer_type)
    accounts = [
        seed_account(
            payer["id"], account_number=number, state_code=state_code,
            financial_class=financial_class,
        )
        for number in account_numbers
    ]
    for account in accounts:
        post_txn(account["id"], "CHARGE", charge_cents, "SYSTEM")

    set_clock(payer_payment_at)
    for account in accounts:
        post_txn(
            account["id"], "PAYMENT", payer_payment_cents, "PAYER",
            payer_id=payer["id"],
        )

    set_clock(patient_payment_at)
    for account in accounts:
        post_txn(account["id"], "PAYMENT", patient_payment_cents, "PATIENT")

    set_clock(sweep_at)
    sweep = run_identify_sweep([a["id"] for a in accounts])
    return {
        "payer": payer,
        "accounts": accounts,
        "credit_balances": [
            read_credit_balance(cb_id) for cb_id in sweep["credit_balance_ids"]
        ],
        "sweep": sweep,
    }
