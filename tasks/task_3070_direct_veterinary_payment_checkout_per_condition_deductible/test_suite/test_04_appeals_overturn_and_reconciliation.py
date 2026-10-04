"""Appeals: records windows, segregation of duties, the overturn cascade,
and dual-variant ledger reconciliation."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_hospital_staff_headers,
    make_pet_owner_headers,
    make_adjuster_headers,
    set_clock,
    create_and_file_filing,
    create_active_hospital,
    create_policy_past_waiting,
    setup_active_environment,
    setup_paid_claim,
    setup_settled_claim,
    setup_denied_claim_with_appeal,
    submit_claim,
    adjudicate_claim,
    pay_claim,
    settle_claim,
    upload_medical_record,
    find_condition,
    hospital_ledger,
    assert_instant_equals,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADJ1 = TEST_USERS["adjuster_1_headers"]
ADJ2 = TEST_USERS["adjuster_2_headers"]


# ---------------------------------------------------------------------------
# Queue A: Difficulty / transitive_cascade — overturn reversal + clawback
# ---------------------------------------------------------------------------

def test_overturn_reverses_payment_and_mints_matching_clawback(api):
    """PRD 3.7: "The claim's original DIRECT_PAY payment, if one exists, is
    moved to REVERSED while its ledger_status stays POSTED, and a
    compensating CLAWBACK payment is created: negative amount_cents, status
    settled into the ledger, ledger_status POSTED, its reverses_payment_id
    pointing at the reversed payment."

    Design: Difficulty/transitive_cascade/appeal_overturn_reversal_clawback_ledger_cascade
    """
    # 150000 DXA line, deductible 20000 -> (150000 - 20000) * 0.9 = 117000.
    hospital, policy, claim, payment = setup_settled_claim(
        idempotency_key="K9",
        lines=[{"description": "surgery", "amount_cents": 150000,
                "category": "TREATMENT", "condition_code": "DXA"}],
    )
    assert claim["reimbursement_cents"] == 117000
    assert claim["status"] == "SETTLED"

    appeal = get_success_data(api.open_appeal(
        claim["id"], {"reason_code": "COVERAGE_DENIAL"},
        make_pet_owner_headers(policy["id"]),
    ))
    get_success_data(api.request_records(appeal["id"], ADJ1))
    record = upload_medical_record(policy, hospital, record_type="PROCEDURE",
                                   recorded_at="2026-10-02T10:00:00Z",
                                   diagnosis_code="DXA", notes="op report")
    get_success_data(api.submit_records(
        appeal["id"], {"medical_record_ids": [record["id"]]},
        make_hospital_staff_headers(hospital["id"]),
    ))
    resp = api.resolve_appeal(
        appeal["id"], {"outcome": "OVERTURNED", "resolution_note": "new evidence"}, ADJ2
    )
    resolved = validate_success(resp)
    assert resolved["status"] == "OVERTURNED"

    reopened = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert reopened["status"] == "REOPENED"
    reversed_payment = get_success_data(api.get_payment(payment["id"], ADMIN))
    assert reversed_payment["status"] == "REVERSED"
    data, meta = validate_paginated(
        api.list_payments(ADMIN, params={"reverses_payment_id": payment["id"]})
    )
    assert len(data) == 1
    clawback = data[0]
    assert clawback["kind"] == "CLAWBACK"
    assert clawback["amount_cents"] == -117000
    assert clawback["ledger_status"] == "POSTED"
    assert hospital_ledger(hospital["id"]) == 0
    condition = find_condition(policy, "DXA")
    assert condition["lifetime_reimbursed_cents"] == 0


def test_overturn_cascade_recomputes_condition_and_ledger(api):
    """PRD 3.7: "Every affected PolicyCondition has its
    lifetime_reimbursed_cents and deductible_accumulated_cents recomputed by
    replaying the remaining non-reversed claim lines."
    PRD 3.7: "The hospital's running_ledger_balance_cents decreases by the
    clawed amount."

    Design: Difficulty/transitive_cascade/appeal_overturn_reversal_clawback_ledger_cascade
    """
    hospital, policy, claim, payment = setup_settled_claim(
        idempotency_key="K9",
        lines=[{"description": "surgery", "amount_cents": 150000,
                "category": "TREATMENT", "condition_code": "DXA"}],
    )
    condition_before = find_condition(policy, "DXA")
    assert condition_before["lifetime_reimbursed_cents"] == 117000
    assert hospital_ledger(hospital["id"]) == 117000

    appeal = get_success_data(api.open_appeal(
        claim["id"], {"reason_code": "COVERAGE_DENIAL"},
        make_pet_owner_headers(policy["id"]),
    ))
    get_success_data(api.request_records(appeal["id"], ADJ1))
    record = upload_medical_record(policy, hospital, record_type="PROCEDURE",
                                   recorded_at="2026-10-02T10:00:00Z",
                                   diagnosis_code="DXA", notes="op report")
    get_success_data(api.submit_records(
        appeal["id"], {"medical_record_ids": [record["id"]]},
        make_hospital_staff_headers(hospital["id"]),
    ))
    validate_success(api.resolve_appeal(
        appeal["id"], {"outcome": "OVERTURNED", "resolution_note": "new evidence"}, ADJ2
    ))

    condition_after = find_condition(policy, "DXA")
    assert condition_after["lifetime_reimbursed_cents"] == 0
    assert condition_after["deductible_accumulated_cents"] == 0
    assert hospital_ledger(hospital["id"]) == 0
    reopened = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert reopened["status"] == "REOPENED"


# ---------------------------------------------------------------------------
# Queue A: Difficulty / compensating_invariant — pay-then-reverse round trip
# ---------------------------------------------------------------------------

def test_payment_reversal_clawback_conserves_ledger(api):
    """PRD 3.8: "The discrepancy_cents is expected_cents minus actual_cents.
    The two variants agree only if every reversal created a matching negative
    clawback payment — this is precisely the property the report exists to
    audit."
    PRD 3.7: "The hospital's running_ledger_balance_cents decreases by the
    clawed amount."

    Design: Difficulty/compensating_invariant/payment_reversal_clawback_conserves_ledger
    """
    hospital, policy, claim, payment = setup_settled_claim(
        idempotency_key="K88",
        lines=[{"description": "surgery", "amount_cents": 150000,
                "category": "TREATMENT", "condition_code": "DXA"}],
    )
    appeal = get_success_data(api.open_appeal(
        claim["id"], {"reason_code": "LINE_CATEGORIZATION"},
        make_pet_owner_headers(policy["id"]),
    ))
    resp = api.resolve_appeal(
        appeal["id"], {"outcome": "OVERTURNED", "resolution_note": "categorization wrong"},
        ADJ2,
    )
    validate_success(resp)

    assert hospital_ledger(hospital["id"]) == 0
    reversed_payment = get_success_data(api.get_payment(payment["id"], ADMIN))
    assert reversed_payment["status"] == "REVERSED"
    data, meta = validate_paginated(
        api.list_payments(ADMIN, params={"reverses_payment_id": payment["id"]})
    )
    assert len(data) == 1
    assert data[0]["kind"] == "CLAWBACK"
    assert data[0]["amount_cents"] == -117000
    resp = api.create_reconciliation_report(
        hospital["id"], {"period_start": "2026-09-01", "period_end": "2026-11-01"}, ADMIN
    )
    report = validate_success(resp, expected_status=201)
    assert report["expected_cents"] == 0
    assert report["actual_cents"] == 0
    assert report["discrepancy_cents"] == 0


def test_round_trip_reconciliation_variants_agree(api):
    """PRD 3.8: "running_ledger_balance_cents is the sum of amount_cents over
    the hospital's payments whose ledger_status is POSTED, minus clawed-back
    amounts from reversed payments, minus the clawback payments themselves
    (which carry negative amounts)."

    Design: Difficulty/compensating_invariant/payment_reversal_clawback_conserves_ledger
    """
    hospital, policy, claim, payment = setup_settled_claim(
        idempotency_key="K88",
        lines=[{"description": "surgery", "amount_cents": 150000,
                "category": "TREATMENT", "condition_code": "DXA"}],
    )
    assert hospital_ledger(hospital["id"]) == 117000
    appeal = get_success_data(api.open_appeal(
        claim["id"], {"reason_code": "LINE_CATEGORIZATION"},
        make_pet_owner_headers(policy["id"]),
    ))
    validate_success(api.resolve_appeal(
        appeal["id"], {"outcome": "OVERTURNED", "resolution_note": "categorization wrong"},
        ADJ2,
    ))
    # Round trip conserves the balance exactly.
    assert hospital_ledger(hospital["id"]) == 0
    resp = api.create_reconciliation_report(
        hospital["id"], {"period_start": "2026-09-01", "period_end": "2026-11-01"}, ADMIN
    )
    report = validate_success(resp, expected_status=201)
    assert report["expected_cents"] == 0
    assert report["actual_cents"] == 0
    assert report["discrepancy_cents"] == 0


# ---------------------------------------------------------------------------
# Queue A: Difficulty / dual_variant_calc — reconciliation over mixed payments
# ---------------------------------------------------------------------------

def _full_recon_scenario():
    """The five-step mixed-payment scenario shared by the two reconciliation
    tests. Returns (hospital, policy, claim_c1, appeal_resolution_ready)."""
    hospital, policy = setup_active_environment()
    staff = make_hospital_staff_headers(hospital["id"])

    # C1: 150000 DXA -> reimbursement 117000, paid K1.
    c1 = submit_claim(policy, hospital, lines=[
        {"description": "surgery", "amount_cents": 150000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    c1 = adjudicate_claim(c1)
    assert c1["reimbursement_cents"] == 117000
    pay_claim(c1, hospital, "K1")

    # C2: 25000 DXA, deductible already saturated -> 22500, paid K2.
    c2 = submit_claim(policy, hospital, visit_date="2026-10-03", lines=[
        {"description": "followup", "amount_cents": 25000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    c2 = adjudicate_claim(c2)
    assert c2["reimbursement_cents"] == 22500
    pay_claim(c2, hospital, "K2")

    # Appeals open only on DENIED or SETTLED claims (PRD 3.7): settle C1 by
    # advancing the clock past the payment time plus SETTLE_DELAY_DAYS.
    c1 = settle_claim(c1, advance_to="2026-10-04T00:00:00Z")

    # Appeal on C1 overturned by a different adjuster -> clawback -117000.
    a1 = get_success_data(api_client.open_appeal(
        c1["id"], {"reason_code": "COVERAGE_DENIAL"},
        make_pet_owner_headers(policy["id"]),
    ))
    validate_success(api_client.resolve_appeal(
        a1["id"], {"outcome": "OVERTURNED", "resolution_note": "misapplied"}, ADJ2
    ))

    # C3: 10000 DXB consumes the whole DXB deductible -> reimbursement 0.
    c3 = submit_claim(policy, hospital, visit_date="2026-10-04", lines=[
        {"description": "xray", "amount_cents": 10000,
         "category": "TREATMENT", "condition_code": "DXB"}
    ])
    c3 = adjudicate_claim(c3)
    assert c3["reimbursement_cents"] == 0
    pay_claim(c3, hospital, "K3")

    return hospital, policy, c1


def test_reconciliation_expected_equals_actual_after_clawback(api):
    """PRD 3.8: "The report computes two ledger variants that must agree when
    every reversal has been handled correctly: ... expected_cents — the
    expected ledger variant: the sum of amount_cents over the hospital's
    payments with ledger_status POSTED whose created_at falls inside the
    half-open window."

    Design: Difficulty/dual_variant_calc/reconciliation_expected_vs_actual_ledger
    """
    hospital, policy, c1 = _full_recon_scenario()
    resp = api.create_reconciliation_report(
        hospital["id"], {"period_start": "2026-09-01", "period_end": "2026-11-01"}, ADMIN
    )
    report = validate_success(resp, expected_status=201)
    # POSTED payments: +117000 +22500 +0 -117000 = 22500 over the window.
    assert report["expected_cents"] == 22500
    assert report["actual_cents"] == 22500
    assert report["discrepancy_cents"] == 0
    assert hospital_ledger(hospital["id"]) == 22500
    reopened = get_success_data(api.get_claim(c1["id"], ADJ1))
    assert reopened["status"] == "REOPENED"


def test_reconciliation_zero_amount_payment_counts_in_window(api):
    """PRD 3.8: "actual_cents — the actual ledger variant: the hospital's
    running_ledger_balance_cents position for the identical window,
    reconstructed by replaying the same posted payments in ascending
    created_at order (timestamps are unique per mutation, so no tie-break is
    needed) and summing the signed amounts."

    Design: Difficulty/dual_variant_calc/reconciliation_expected_vs_actual_ledger
    """
    hospital, policy, c1 = _full_recon_scenario()
    assert hospital_ledger(hospital["id"]) == 22500
    resp = api.create_reconciliation_report(
        hospital["id"], {"period_start": "2026-09-01", "period_end": "2026-11-01"}, ADMIN
    )
    report = validate_success(resp, expected_status=201)
    assert report["expected_cents"] == 22500
    assert report["actual_cents"] == 22500
    assert report["discrepancy_cents"] == 0
    # Both ledger variants agree over the mixed operation set, including the
    # 0-cent POSTED payment and the negative clawback.
    data, meta = validate_paginated(api.list_hospital_payments(hospital["id"], ADMIN))
    assert len(data) == 4  # 3 DIRECT_PAY + 1 CLAWBACK


# ---------------------------------------------------------------------------
# Queue A: Difficulty / resource_temporal_overlap — records window deadline
# ---------------------------------------------------------------------------

def test_submit_records_one_second_past_deadline_rejected(api):
    """PRD 3.7: "submission is valid only while the appeal is in
    RECORDS_REQUESTED, only while the current logical clock is at or before
    records_due_at — after the deadline the attempt fails with
    ERR_APPEAL_WINDOW_EXPIRED (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/appeal_records_window_expiry
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    claim = get_success_data(api.deny_claim(
        claim["id"], {"denial_reason": "lack of evidence"}, ADJ1
    ))
    appeal = get_success_data(api.open_appeal(
        claim["id"], {"reason_code": "COVERAGE_DENIAL"},
        make_pet_owner_headers(policy["id"]),
    ))
    set_clock("2026-10-02T00:00:00Z")
    requested = get_success_data(api.request_records(appeal["id"], ADJ1))
    assert_instant_equals(requested["records_due_at"], "2026-10-16T00:00:00Z")
    record = upload_medical_record(policy, hospital, record_type="LAB",
                                   recorded_at="2026-10-02T08:00:00Z",
                                   diagnosis_code="DXA", notes="panel")
    set_clock("2026-10-16T00:00:01Z")
    resp = api.submit_records(
        appeal["id"], {"medical_record_ids": [record["id"]]},
        make_hospital_staff_headers(hospital["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)
    still = get_success_data(api.get_appeal(appeal["id"], ADJ1))
    assert still["status"] == "RECORDS_REQUESTED"
    reread = get_success_data(api.get_medical_record(record["id"], ADJ1))
    assert reread["appeal_id"] is None


def test_records_due_at_is_request_clock_plus_fourteen_days(api):
    """PRD 3.7: "An adjuster may request medical records, moving the appeal
    OPEN -> RECORDS_REQUESTED and setting records_due_at to the current
    logical clock plus the records window of RECORDS_WINDOW_DAYS days, which
    is 14 days."

    Design: Difficulty/resource_temporal_overlap/appeal_records_window_expiry
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    get_success_data(api.deny_claim(claim["id"], {"denial_reason": "lack of evidence"}, ADJ1))
    appeal = get_success_data(api.open_appeal(
        claim["id"], {"reason_code": "COVERAGE_DENIAL"},
        make_pet_owner_headers(policy["id"]),
    ))
    set_clock("2026-10-02T00:00:00Z")
    requested = get_success_data(api.request_records(appeal["id"], ADJ1))
    assert requested["status"] == "RECORDS_REQUESTED"
    assert_instant_equals(requested["records_due_at"], "2026-10-16T00:00:00Z")
    record = upload_medical_record(policy, hospital, record_type="LAB",
                                   recorded_at="2026-10-02T08:00:00Z",
                                   diagnosis_code="DXA", notes="panel")
    set_clock("2026-10-16T00:00:01Z")
    resp = api.submit_records(
        appeal["id"], {"medical_record_ids": [record["id"]]},
        make_hospital_staff_headers(hospital["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)


# ---------------------------------------------------------------------------
# Queue B: Corner / cross_cutting_layers — exact-deadline acceptance
# ---------------------------------------------------------------------------

def test_submit_records_at_exact_deadline_succeeds(api):
    """PRD 3.7: "submission is valid only while the appeal is in
    RECORDS_REQUESTED, only while the current logical clock is at or before
    records_due_at"
    PRD 3.7: "Successful submission stamps each record's appeal_id with this
    appeal's id and moves the appeal to UNDER_REVIEW."

    Design: Corner/cross_cutting_layers/appeal_records_submit_at_exact_deadline
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    get_success_data(api.deny_claim(claim["id"], {"denial_reason": "not covered"}, ADJ1))
    appeal = get_success_data(api.open_appeal(
        claim["id"], {"reason_code": "COVERAGE_DENIAL"},
        make_pet_owner_headers(policy["id"]),
    ))
    # Clock currently 2026-10-01 from the environment setup.
    requested = get_success_data(api.request_records(appeal["id"], ADJ1))
    assert_instant_equals(requested["records_due_at"], "2026-10-15T00:00:00Z")
    record = upload_medical_record(policy, hospital)
    set_clock("2026-10-15T00:00:00Z")
    resp = api.submit_records(
        appeal["id"], {"medical_record_ids": [record["id"]]},
        make_hospital_staff_headers(hospital["id"]),
    )
    updated = validate_success(resp)
    assert updated["status"] == "UNDER_REVIEW"
    reread = get_success_data(api.get_medical_record(record["id"], ADJ1))
    assert reread["appeal_id"] == appeal["id"]


# ---------------------------------------------------------------------------
# Queue B: Corner / validations — double attach and segregation of duties
# ---------------------------------------------------------------------------

def test_record_attach_after_window_and_double_attach(api):
    """PRD 3.7: "every referenced record must exist, belong to the claim's
    policy (a record that does not exist or belongs to another policy yields
    ERR_RECORD_NOT_FOUND, HTTP 404), and not already be attached to another
    appeal (else ERR_RECORD_ALREADY_ATTACHED, HTTP 409)."

    Design: Corner/validations/record_attach_after_window_and_double_attach
    """
    hospital, policy = setup_active_environment()
    staff = make_hospital_staff_headers(hospital["id"])
    owner = make_pet_owner_headers(policy["id"])

    claim1 = submit_claim(policy, hospital)
    get_success_data(api.deny_claim(claim1["id"], {"denial_reason": "not covered"}, ADJ1))
    appeal1 = get_success_data(api.open_appeal(
        claim1["id"], {"reason_code": "COVERAGE_DENIAL"}, owner
    ))
    claim2 = submit_claim(policy, hospital, visit_date="2026-10-03", lines=[
        {"description": "er2", "amount_cents": 40000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    get_success_data(api.deny_claim(claim2["id"], {"denial_reason": "second denial"}, ADJ1))
    appeal2 = get_success_data(api.open_appeal(
        claim2["id"], {"reason_code": "CONDITION_DEFINITION"}, owner
    ))
    get_success_data(api.request_records(appeal1["id"], ADJ1))
    get_success_data(api.request_records(appeal2["id"], ADJ1))
    record = upload_medical_record(policy, hospital)
    get_success_data(api.submit_records(
        appeal1["id"], {"medical_record_ids": [record["id"]]}, staff
    ))
    resp = api.submit_records(
        appeal2["id"], {"medical_record_ids": [record["id"]]}, staff
    )
    validate_error(resp, ApiErrorId.ERR_RECORD_ALREADY_ATTACHED)
    still = get_success_data(api.get_appeal(appeal2["id"], ADJ1))
    assert still["status"] == "RECORDS_REQUESTED"


def test_self_resolution_forbidden_segregation_of_duties(api):
    """PRD 3.7: "An outcome of OVERTURNED additionally requires that the
    resolving adjuster's X-User-ID differ from the appeal's
    original_adjuster_id; the same adjuster resolving their own decision is
    rejected with ERR_SELF_RESOLUTION_FORBIDDEN (HTTP 403)."
    PRD 2.1: "it is recorded on an appeal as the appeal's
    original_adjuster_id when that appeal is opened, so the later resolution
    can compare against it."

    Design: Corner/validations/self_resolution_forbidden_segregation_of_duties
    """
    hospital, policy, claim, appeal = setup_denied_claim_with_appeal()
    # adj-1 denied the claim; the same adjuster cannot OVERTURN their own
    # decision (PRD 3.7: the segregation-of-duties check is stated for an
    # outcome of OVERTURNED).
    resp = api.resolve_appeal(
        appeal["id"],
        {"outcome": "OVERTURNED", "resolution_note": "i denied it, i reverse it"},
        ADJ1,
    )
    validate_error(resp, ApiErrorId.ERR_SELF_RESOLUTION_FORBIDDEN)
    still = get_success_data(api.get_appeal(appeal["id"], ADJ1))
    assert still["status"] == "OPEN"
    assert still["original_adjuster_id"] == "adj-1"
    resp = api.resolve_appeal(
        appeal["id"],
        {"outcome": "UPHELD", "resolution_note": "independent review"},
        ADJ2,
    )
    resolved = validate_success(resp)
    assert resolved["status"] == "UPHELD"


# ---------------------------------------------------------------------------
# Queue B: Corner / state_machines — appeal transitions
# ---------------------------------------------------------------------------

def test_appeal_upheld_leaves_claim_untouched(api):
    """PRD 3.7: "An outcome of UPHELD simply closes the appeal as UPHELD."

    Design: Corner/state_machines/appeal_upheld_leaves_claim_untouched
    """
    hospital, policy, claim, appeal = setup_denied_claim_with_appeal()
    resp = api.resolve_appeal(
        appeal["id"], {"outcome": "UPHELD", "resolution_note": "denial correct"}, ADJ2
    )
    resolved = validate_success(resp)
    assert resolved["status"] == "UPHELD"
    still = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert still["status"] == "DENIED"
    assert still["payment_id"] is None
    data, meta = validate_paginated(api.list_hospital_payments(hospital["id"], ADMIN))
    assert len(data) == 0


def test_appeal_terminal_lockdown(api):
    """PRD 3.7: "A ClaimsAdjuster resolves an appeal that is OPEN or
    UNDER_REVIEW — from any other status the attempt fails with
    ERR_APPEAL_NOT_RESOLVABLE (HTTP 409) — by supplying an outcome and a
    resolution_note."

    Design: Corner/state_machines/appeal_terminal_lockdown
    """
    hospital, policy, claim, appeal = setup_denied_claim_with_appeal()
    validate_success(api.resolve_appeal(
        appeal["id"], {"outcome": "UPHELD", "resolution_note": "final"}, ADJ2
    ))
    resp = api.resolve_appeal(
        appeal["id"], {"outcome": "OVERTURNED", "resolution_note": "too late"}, ADJ2
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_RESOLVABLE)
    still = get_success_data(api.get_appeal(appeal["id"], ADJ1))
    assert still["status"] == "UPHELD"


def test_appeal_open_requires_denied_or_settled_claim(api):
    """PRD 3.7: "A PetOwner may open a ClaimAppeal on a claim that is DENIED
    or SETTLED — an appeal on a claim in any other status is rejected with
    ERR_APPEAL_NOT_OPENABLE (HTTP 409)"

    Design: Corner/endpoints/appeal_open_requires_denied_or_settled_claim
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    resp = api.open_appeal(
        claim["id"], {"reason_code": "COVERAGE_DENIAL"},
        make_pet_owner_headers(policy["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_OPENABLE)
    data, meta = validate_paginated(api.list_claim_appeals(claim["id"], ADJ1))
    assert len(data) == 0


# ---------------------------------------------------------------------------
# Queue B: Corner / endpoints — reconciliation acknowledge/dispute
# ---------------------------------------------------------------------------

def test_reconciliation_report_acknowledge_and_dispute_paths(api):
    """PRD 3.8: "A generated report is born in GENERATED status (201), may be
    acknowledged by a PlatformAdmin (moving it to ACKNOWLEDGED), and may be
    disputed by HospitalStaff (moving it to DISPUTED)."
    PRD 2.7: "State admissibility — the target resource must be in a state
    from which the requested transition exists, otherwise ERR_INVALID_STATE"

    Design: Corner/endpoints/reconciliation_report_acknowledge_and_dispute_paths
    """
    hospital, policy, claim, payment = setup_paid_claim(idempotency_key="KD1")
    resp = api.create_reconciliation_report(
        hospital["id"], {"period_start": "2026-09-01", "period_end": "2026-11-01"}, ADMIN
    )
    report = validate_success(resp, expected_status=201)
    assert report["status"] == "GENERATED"
    assert report["expected_cents"] == 27000
    assert report["actual_cents"] == 27000
    assert report["discrepancy_cents"] == 0

    resp = api.acknowledge_reconciliation_report(report["id"], ADMIN)
    acked = validate_success(resp)
    assert acked["status"] == "ACKNOWLEDGED"
    resp = api.dispute_reconciliation_report(
        report["id"], make_hospital_staff_headers(hospital["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    still = get_success_data(api.get_reconciliation_report(report["id"], ADMIN))
    assert still["status"] == "ACKNOWLEDGED"


# ---------------------------------------------------------------------------
# Queue B: Corner / cross_cutting_layers — derived ledger over mixed ops
# ---------------------------------------------------------------------------

def test_derived_ledger_reconciles_after_mixed_operations(api):
    """PRD 3.8: "running_ledger_balance_cents is the sum of amount_cents over
    the hospital's payments whose ledger_status is POSTED, minus clawed-back
    amounts from reversed payments, minus the clawback payments themselves
    (which carry negative amounts). Failed payments — PENDING_POST — and
    EXCLUDED payments never contribute."

    Design: Corner/cross_cutting_layers/derived_ledger_reconciles_after_mixed_operations
    """
    hospital, policy = setup_active_environment()
    staff = make_hospital_staff_headers(hospital["id"])

    # C1: 50000 DXA -> 27000, paid KA.
    c1 = submit_claim(policy, hospital, lines=[
        {"description": "surgery", "amount_cents": 50000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    c1 = adjudicate_claim(c1)
    pay_claim(c1, hospital, "KA")

    # C2: 30000 DXB -> deductible 20000 -> base 10000 -> 9000; fail then retry.
    c2 = submit_claim(policy, hospital, visit_date="2026-10-03", claim_type="ILLNESS",
                      lines=[
                          {"description": "labs", "amount_cents": 30000,
                           "category": "TREATMENT", "condition_code": "DXB"}
                      ])
    c2 = adjudicate_claim(c2)
    validate_success(api.checkout_pay(
        c2["id"], {"idempotency_key": "KB", "simulate_outcome": "FAILED"}, staff
    ))
    validate_success(api.checkout_pay(c2["id"], {"idempotency_key": "KC"}, staff))

    # C3: 50000 DXA (saturated) -> 45000, paid KD.
    c3 = submit_claim(policy, hospital, visit_date="2026-10-04", lines=[
        {"description": "followup", "amount_cents": 50000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    c3 = adjudicate_claim(c3)
    pay_claim(c3, hospital, "KD")

    # Settle C1, then overturn it (-27000).
    c1 = settle_claim(c1, advance_to="2026-10-06T00:00:00Z")
    assert c1["status"] == "SETTLED"
    appeal = get_success_data(api.open_appeal(
        c1["id"], {"reason_code": "COVERAGE_DENIAL"},
        make_pet_owner_headers(policy["id"]),
    ))
    validate_success(api.resolve_appeal(
        appeal["id"], {"outcome": "OVERTURNED", "resolution_note": "wrong"}, ADJ2
    ))

    # 27000 + 0 + 9000 + 45000 - 27000 = 54000.
    assert hospital_ledger(hospital["id"]) == 54000
    resp = api.create_reconciliation_report(
        hospital["id"], {"period_start": "2026-09-01", "period_end": "2026-11-01"}, ADMIN
    )
    report = validate_success(resp, expected_status=201)
    assert report["expected_cents"] == 54000
    assert report["actual_cents"] == 54000
    assert report["discrepancy_cents"] == 0
    # The FAILED payment contributes 0 to both ledger views: after retry its
    # ledger_status is EXCLUDED.
    data, meta = validate_paginated(
        api.list_payments(ADMIN, params={"claim_id": c2["id"]})
    )
    by_key = {p["idempotency_key"]: p for p in data}
    assert by_key["KB"]["ledger_status"] == "EXCLUDED"
    assert by_key["KC"]["ledger_status"] == "POSTED"
