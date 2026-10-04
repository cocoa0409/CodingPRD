"""Direct payment at checkout: idempotency, failure injection and retry,
settlement delay, and ledger conservation."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_hospital_staff_headers,
    setup_active_environment,
    setup_adjudicated_claim,
    setup_paid_claim,
    setup_settled_claim,
    submit_claim,
    adjudicate_claim,
    hospital_ledger,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADJ1 = TEST_USERS["adjuster_1_headers"]
ADJ2 = TEST_USERS["adjuster_2_headers"]


# ---------------------------------------------------------------------------
# Queue A: Difficulty / compensating_invariant — idempotency
# ---------------------------------------------------------------------------

def test_checkout_pay_duplicate_key_returns_same_payment(api):
    """PRD 3.6: "The idempotency rule is key-scoped per claim: if the supplied
    idempotency_key was already used for another Payment of this claim, the
    endpoint returns the existing payment and creates no new one."

    Design: Difficulty/compensating_invariant/idempotent_checkout_pay_double_send
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital, lines=[
        {"description": "surgery", "amount_cents": 150000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    claim = adjudicate_claim(claim)
    assert claim["reimbursement_cents"] == 117000
    staff = make_hospital_staff_headers(hospital["id"])

    resp1 = api.checkout_pay(claim["id"], {"idempotency_key": "K77"}, staff)
    payment1 = validate_success(resp1)
    resp2 = api.checkout_pay(claim["id"], {"idempotency_key": "K77"}, staff)
    payment2 = validate_success(resp2)
    assert payment2["id"] == payment1["id"]

    data, meta = validate_paginated(api.list_hospital_payments(hospital["id"], ADMIN))
    assert len(data) == 1
    assert hospital_ledger(hospital["id"]) == 117000
    reread = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert reread["payment_id"] == payment1["id"]


def test_checkout_pay_duplicate_key_conserves_ledger(api):
    """PRD 3.6: "On success the payment is born with status SETTLED and
    ledger_status POSTED; the claim moves ADJUDICATED -> PAID; each mapped
    condition's lifetime_reimbursed_cents is incremented by its lines'
    reimbursement amounts — again uncapped; and the hospital's
    running_ledger_balance_cents increases by the payment amount."

    Design: Difficulty/compensating_invariant/idempotent_checkout_pay_double_send
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital, lines=[
        {"description": "surgery", "amount_cents": 150000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    claim = adjudicate_claim(claim)
    staff = make_hospital_staff_headers(hospital["id"])
    payment1 = validate_success(api.checkout_pay(claim["id"], {"idempotency_key": "K77"}, staff))
    assert hospital_ledger(hospital["id"]) == 117000
    payment2 = validate_success(api.checkout_pay(claim["id"], {"idempotency_key": "K77"}, staff))
    assert payment2["id"] == payment1["id"]
    # Conserved: forward + duplicate == forward alone.
    assert hospital_ledger(hospital["id"]) == 117000
    data, meta = validate_paginated(
        api.list_payments(ADMIN, params={"claim_id": claim["id"]})
    )
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Queue B: Corner / state_machines — failure/retry cycle
# ---------------------------------------------------------------------------

def test_payment_failure_to_adjudicated_retry_cycle(api):
    """PRD 3.6: "In that case the payment is created with status FAILED,
    ledger_status PENDING_POST, and its amount is not added to the hospital
    ledger; the claim moves ADJUDICATED -> PAYMENT_FAILED and its version
    increments. A failed payment is not terminal: retrying checkout-pay on a
    PAYMENT_FAILED claim whose prior payment is FAILED marks the prior
    payment's ledger_status as EXCLUDED, creates a fresh payment (settled and
    posted on success), points the claim's payment_id at the new payment, and
    returns the claim to ADJUDICATED -> PAID."

    Design: Corner/state_machines/payment_failure_to_adjudicated_retry_cycle
    """
    hospital, policy, claim = setup_adjudicated_claim()
    assert claim["reimbursement_cents"] == 27000
    staff = make_hospital_staff_headers(hospital["id"])

    resp = api.checkout_pay(
        claim["id"], {"idempotency_key": "KF1", "simulate_outcome": "FAILED"}, staff
    )
    failed_payment = validate_success(resp)
    assert failed_payment["status"] == "FAILED"
    assert failed_payment["ledger_status"] == "PENDING_POST"
    mid = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert mid["status"] == "PAYMENT_FAILED"
    assert hospital_ledger(hospital["id"]) == 0

    resp = api.checkout_pay(claim["id"], {"idempotency_key": "KF2"}, staff)
    retry_payment = validate_success(resp)
    assert retry_payment["status"] == "SETTLED"
    assert retry_payment["ledger_status"] == "POSTED"
    paid = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert paid["status"] == "PAID"
    assert paid["payment_id"] == retry_payment["id"]
    old = get_success_data(api.get_payment(failed_payment["id"], ADMIN))
    assert old["ledger_status"] == "EXCLUDED"
    assert hospital_ledger(hospital["id"]) == 27000


def test_failed_payment_never_touches_ledger_before_retry(api):
    """PRD 3.8: "Failed payments — PENDING_POST — and EXCLUDED payments never
    contribute."

    Design: Corner/state_machines/payment_failure_to_adjudicated_retry_cycle
    """
    hospital, policy, claim = setup_adjudicated_claim()
    staff = make_hospital_staff_headers(hospital["id"])
    failed = validate_success(api.checkout_pay(
        claim["id"], {"idempotency_key": "KF1", "simulate_outcome": "FAILED"}, staff
    ))
    assert failed["status"] == "FAILED"
    assert failed["ledger_status"] == "PENDING_POST"
    assert hospital_ledger(hospital["id"]) == 0
    mid = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert mid["status"] == "PAYMENT_FAILED"


# ---------------------------------------------------------------------------
# Queue B: Corner / state_machines — deny-from-PAID, SETTLED lockdown
# ---------------------------------------------------------------------------

def test_claim_deny_from_paid_is_rejected(api):
    """PRD 3.5: "Separately, an adjuster may deny a claim outright from
    SUBMITTED or PREEXISTING_REVIEW, supplying a denial_reason, which moves it
    to DENIED and increments the version."

    Design: Corner/state_machines/claim_deny_from_paid_is_rejected
    """
    hospital, policy, claim, payment = setup_paid_claim(idempotency_key="KD1")
    resp = api.deny_claim(
        claim["id"], {"denial_reason": "late change of heart"}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    still = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert still["status"] == "PAID"
    assert still["payment_id"] == payment["id"]


def test_deny_from_paid_preserves_payment_linkage(api):
    """PRD 2.7: "State admissibility — the target resource must be in a state
    from which the requested transition exists, otherwise ERR_INVALID_STATE
    (expressed through its state-specific aliases
    ERR_HOSPITAL_NOT_APPROVABLE, ERR_FILING_NOT_FILABLE,
    ERR_CLAIM_NOT_ADJUDICATABLE, ERR_CLAIM_NOT_PAYABLE,
    ERR_APPEAL_NOT_OPENABLE, ERR_APPEAL_NOT_RESOLVABLE)."
    PRD 3.6: "the claim moves ADJUDICATED -> PAID"

    Design: Corner/state_machines/claim_deny_from_paid_is_rejected
    """
    hospital, policy, claim, payment = setup_paid_claim(idempotency_key="KD1")
    assert claim["status"] == "PAID"
    resp = api.deny_claim(claim["id"], {"denial_reason": "too late"}, ADJ1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    still = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert still["status"] == "PAID"
    assert still["payment_id"] == payment["id"]
    assert still["version"] == claim["version"]
    # The payment itself is untouched by the rejected deny.
    reread = get_success_data(api.get_payment(payment["id"], ADMIN))
    assert reread["status"] == "SETTLED"
    assert reread["ledger_status"] == "POSTED"


def test_claim_settled_is_terminal_no_further_transitions(api):
    """PRD 3.6: "SETTLED is the claim's only terminal state under normal flow
    — but see the appeal remedy below, which can reopen even a settled
    claim."

    Design: Corner/state_machines/claim_settled_is_terminal_no_further_transitions
    """
    hospital, policy, claim, payment = setup_settled_claim(idempotency_key="KD2")
    assert claim["status"] == "SETTLED"
    staff = make_hospital_staff_headers(hospital["id"])

    resp = api.flag_preexisting_review(claim["id"], ADJ1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api.deny_claim(claim["id"], {"denial_reason": "no"}, ADJ1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ADJUDICATABLE)
    resp = api.checkout_pay(claim["id"], {"idempotency_key": "KD3"}, staff)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PAYABLE)
    still = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert still["status"] == "SETTLED"
    assert still["payment_id"] == payment["id"]
