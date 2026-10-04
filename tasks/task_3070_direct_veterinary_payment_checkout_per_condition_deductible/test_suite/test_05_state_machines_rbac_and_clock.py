"""State machines, cross-entity gates, validation priority, RBAC,
filing supersession, OCC, and the fixed default clock."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    make_hospital_staff_headers,
    make_pet_owner_headers,
    set_clock,
    create_and_file_filing,
    create_active_hospital,
    create_policy,
    create_policy_past_waiting,
    create_policy_payload,
    create_hospital_payload,
    setup_active_environment,
    submit_claim,
    adjudicate_claim,
    pay_claim,
    upload_medical_record,
    find_condition,
    hospital_ledger,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RATE_ADMIN = TEST_USERS["rate_filing_admin_headers"]
ADJ1 = TEST_USERS["adjuster_1_headers"]
ADJ2 = TEST_USERS["adjuster_2_headers"]


# ---------------------------------------------------------------------------
# Queue A: Difficulty / non_linear_state_machine — parallel policy dimensions
# ---------------------------------------------------------------------------

def test_policy_dimensions_advance_independently(api):
    """PRD 3.3: "A policy lives on two parallel status dimensions. The
    enrollment dimension runs INJURY_WAITING -> ILLNESS_WAITING ->
    FULLY_ACTIVE; the lifecycle dimension runs ACTIVE -> CANCELLED or LAPSED
    (both terminal). At creation the policy is INJURY_WAITING and ACTIVE"
    PRD 3.3: "The enrollment dimension advances only by the logical clock:
    once the current logical clock is at or past injury_waiting_end, the
    policy moves to ILLNESS_WAITING; once it is at or past
    illness_waiting_end, the policy moves to FULLY_ACTIVE."

    Design: Difficulty/non_linear_state_machine/policy_parallel_waiting_and_lifecycle_dimensions
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    policy = create_policy(pet_date_of_birth="2024-03-01", coverage_start="2026-09-01")
    assert policy["enrollment_status"] == "INJURY_WAITING"
    assert policy["lifecycle_status"] == "ACTIVE"
    # 2026-09-06 >= injury end (2026-09-06), < illness end (2026-09-15).
    set_clock("2026-09-06T00:00:00Z")
    mid = get_success_data(api.get_policy(policy["id"], make_pet_owner_headers(policy["id"])))
    assert mid["enrollment_status"] == "ILLNESS_WAITING"
    assert mid["lifecycle_status"] == "ACTIVE"


def test_cancelled_policy_enrollment_status_frozen(api):
    """PRD 3.3: "The lifecycle dimension moves by explicit act. An owner
    cancels their own ACTIVE policy — the X-User-ID must equal the policy's
    id-bound owner identity, otherwise ERR_UNAUTHORIZED — moving it to
    CANCELLED."
    PRD 3.3: "The enrollment dimension advances only by the logical clock:
    once the current logical clock is at or past injury_waiting_end, the
    policy moves to ILLNESS_WAITING; once it is at or past
    illness_waiting_end, the policy moves to FULLY_ACTIVE."

    Design: Difficulty/non_linear_state_machine/policy_parallel_waiting_and_lifecycle_dimensions
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    policy = create_policy(pet_date_of_birth="2024-03-01", coverage_start="2026-09-01")
    set_clock("2026-09-06T00:00:00Z")
    owner = make_pet_owner_headers(policy["id"])
    mid = get_success_data(api.get_policy(policy["id"], owner))
    assert mid["enrollment_status"] == "ILLNESS_WAITING"
    cancelled = validate_success(api.cancel_policy(policy["id"], owner))
    assert cancelled["lifecycle_status"] == "CANCELLED"
    # Sweep well past the illness window: no enrollment sweep on a CANCELLED
    # policy, so enrollment_status stays frozen.
    set_clock("2026-10-01T00:00:00Z")
    frozen = get_success_data(api.get_policy(policy["id"], owner))
    assert frozen["lifecycle_status"] == "CANCELLED"
    assert frozen["enrollment_status"] == "ILLNESS_WAITING"


# ---------------------------------------------------------------------------
# Queue A: Difficulty / transitive_cascade — suspension cascade
# ---------------------------------------------------------------------------

def test_suspend_denies_open_claims_and_releases_deductible(api):
    """PRD 3.2: "Every claim at that hospital whose status is SUBMITTED,
    PREEXISTING_REVIEW, ADJUDICATED, or REOPENED is moved to DENIED with
    denial_reason set to HOSPITAL_SUSPENDED. Each such claim's line-level
    computed fields are zeroed and its claim totals recomputed accordingly."
    PRD 3.2: "Each claim thus denied releases its PolicyCondition mappings:
    the deductible contributions its lines had consumed are reversed, and
    each affected condition's deductible_accumulated_cents is recomputed."

    Design: Difficulty/transitive_cascade/hospital_suspend_claim_deny_condition_reversal_cascade
    """
    hospital, policy = setup_active_environment()
    # C1: 150000 DXA, adjudicated and PAID.
    c1 = submit_claim(policy, hospital, lines=[
        {"description": "surgery", "amount_cents": 150000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    c1 = adjudicate_claim(c1)
    pay_claim(c1, hospital, "KS1")
    # C2: 10000 DXB, ADJUDICATED but not paid.
    c2 = submit_claim(policy, hospital, visit_date="2026-10-03", claim_type="ILLNESS",
                      lines=[
                          {"description": "labs", "amount_cents": 10000,
                           "category": "TREATMENT", "condition_code": "DXB"}
                      ])
    c2 = adjudicate_claim(c2)
    assert find_condition(policy, "DXB")["deductible_accumulated_cents"] == 10000
    # C3: 8000 DXC, still SUBMITTED.
    c3 = submit_claim(policy, hospital, visit_date="2026-10-03", claim_type="ILLNESS",
                      lines=[
                          {"description": "meds", "amount_cents": 8000,
                           "category": "TREATMENT", "condition_code": "DXC"}
                      ])

    resp = api.suspend_hospital(hospital["id"], ADMIN)
    suspended = validate_success(resp)
    assert suspended["status"] == "SUSPENDED"

    c2_after = get_success_data(api.get_claim(c2["id"], ADJ1))
    assert c2_after["status"] == "DENIED"
    assert c2_after["denial_reason"] == "HOSPITAL_SUSPENDED"
    c3_after = get_success_data(api.get_claim(c3["id"], ADJ1))
    assert c3_after["status"] == "DENIED"
    assert c3_after["denial_reason"] == "HOSPITAL_SUSPENDED"
    c1_after = get_success_data(api.get_claim(c1["id"], ADJ1))
    assert c1_after["status"] == "PAID"
    assert find_condition(policy, "DXB")["deductible_accumulated_cents"] == 0
    assert find_condition(policy, "DXA")["deductible_accumulated_cents"] == 20000
    assert hospital_ledger(hospital["id"]) == 117000


def test_suspend_leaves_paid_claims_and_ledger_untouched(api):
    """PRD 3.2: "When a PlatformAdmin suspends an ACTIVE hospital, three
    levels of cascade fire: 1. Every claim at that hospital whose status is
    SUBMITTED, PREEXISTING_REVIEW, ADJUDICATED, or REOPENED is moved to
    DENIED with denial_reason set to HOSPITAL_SUSPENDED."

    Design: Difficulty/transitive_cascade/hospital_suspend_claim_deny_condition_reversal_cascade
    """
    hospital, policy = setup_active_environment()
    c1 = submit_claim(policy, hospital, lines=[
        {"description": "surgery", "amount_cents": 150000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    c1 = adjudicate_claim(c1)
    pay_claim(c1, hospital, "KS1")
    assert hospital_ledger(hospital["id"]) == 117000
    # A second open claim to observe the conditional cascade.
    c2 = submit_claim(policy, hospital, visit_date="2026-10-03", claim_type="ILLNESS",
                      lines=[
                          {"description": "labs", "amount_cents": 10000,
                           "category": "TREATMENT", "condition_code": "DXB"}
                      ])
    c2 = adjudicate_claim(c2)
    validate_success(api.suspend_hospital(hospital["id"], ADMIN))
    # PAID is outside the cascade's status set: C1 stays PAID.
    assert get_success_data(api.get_claim(c1["id"], ADJ1))["status"] == "PAID"
    assert get_success_data(api.get_claim(c2["id"], ADJ1))["denial_reason"] == "HOSPITAL_SUSPENDED"
    assert find_condition(policy, "DXA")["deductible_accumulated_cents"] == 20000
    assert find_condition(policy, "DXB")["deductible_accumulated_cents"] == 0
    assert hospital_ledger(hospital["id"]) == 117000


# ---------------------------------------------------------------------------
# Queue A: Difficulty / priority_pair_validation_conflict
# ---------------------------------------------------------------------------

def test_state_failure_beats_preexisting_safety_on_adjudicate(api):
    """PRD 2.7: "When a request fails several checks at once, the error the
    client receives is determined by a fixed priority order, evaluated in
    this sequence: ... 5. State admissibility — the target resource must be
    in a state from which the requested transition exists, otherwise
    ERR_INVALID_STATE (expressed through its state-specific aliases
    ERR_HOSPITAL_NOT_APPROVABLE, ERR_FILING_NOT_FILABLE,
    ERR_CLAIM_NOT_ADJUDICATABLE, ERR_CLAIM_NOT_PAYABLE,
    ERR_APPEAL_NOT_OPENABLE, ERR_APPEAL_NOT_RESOLVABLE). ... 7. Business
    safety checks — the pre-existing condition gate
    (ERR_PREEXISTING_CONDITION)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_adjudicate
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    claim = adjudicate_claim(claim)  # clean adjudication FIRST
    assert claim["status"] == "ADJUDICATED"
    # Now DXA gains pre-existing evidence — but the claim is already
    # ADJUDICATED, so the state rule (priority 5) must win.
    upload_medical_record(policy, hospital, record_type="EXAM",
                          recorded_at="2026-08-01T09:00:00Z",
                          diagnosis_code="DXA", notes="limping noted pre-coverage")
    fresh = get_success_data(api.get_claim(claim["id"], ADJ1))
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": fresh["version"]}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ADJUDICATABLE)


def test_preexisting_gate_fires_when_state_is_admissible(api):
    """PRD 2.7: "7. Business safety checks — the pre-existing condition gate
    (ERR_PREEXISTING_CONDITION)."
    PRD 3.5: "If the condition — whether found or freshly minted — is
    pre-existing, the entire claim is rejected with
    ERR_PREEXISTING_CONDITION (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_adjudicate
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    hospital = create_active_hospital()
    policy = create_policy()
    upload_medical_record(policy, hospital, record_type="EXAM",
                          recorded_at="2026-08-01T09:00:00Z",
                          diagnosis_code="DXA", notes="limping noted pre-coverage")
    set_clock("2026-10-01T00:00:00Z")
    claim = submit_claim(policy, hospital)
    # Same evidence as the priority test, but the claim is in an admissible
    # state, so the business-safety gate (priority 7) surfaces instead.
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_PREEXISTING_CONDITION)
    still = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert still["status"] == "SUBMITTED"


def test_state_failure_beats_temporal_gate_on_adjudicate(api):
    """PRD 2.7: "When a request fails several checks at once, the error the
    client receives is determined by a fixed priority order, evaluated in
    this sequence: ... 5. State admissibility — the target resource must be
    in a state from which the requested transition exists, otherwise
    ERR_INVALID_STATE ... 6. Business temporal checks — the waiting-period
    gate (ERR_WAITING_PERIOD_ACTIVE)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_adjudicate
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    hospital = create_active_hospital()
    policy = create_policy()  # illness window open until 2026-09-15
    set_clock("2026-09-03T00:00:00Z")
    claim = submit_claim(policy, hospital, visit_date="2026-09-03",
                         claim_type="ILLNESS",
                         lines=[
                             {"description": "labs", "amount_cents": 30000,
                              "category": "TREATMENT", "condition_code": "DXB"}
                         ])
    denied = get_success_data(api.deny_claim(
        claim["id"], {"denial_reason": "insufficient documentation"}, ADJ1
    ))
    assert denied["status"] == "DENIED"
    # Both the state rule (DENIED) and the temporal gate (illness window
    # still open) fail; the state rule has the higher priority.
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": denied["version"]}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ADJUDICATABLE)


def test_waiting_gate_fires_when_state_is_admissible(api):
    """PRD 2.7: "6. Business temporal checks — the waiting-period gate
    (ERR_WAITING_PERIOD_ACTIVE)."
    PRD 3.5: "an ILLNESS claim requires it to be at or past
    illness_waiting_end; the boundary is inclusive — a claim adjudicated at
    exactly the waiting end passes — and a violation is
    ERR_WAITING_PERIOD_ACTIVE (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_adjudicate
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    hospital = create_active_hospital()
    policy = create_policy()  # illness window open until 2026-09-15
    set_clock("2026-09-03T00:00:00Z")
    claim = submit_claim(policy, hospital, visit_date="2026-09-03",
                         claim_type="ILLNESS",
                         lines=[
                             {"description": "labs", "amount_cents": 30000,
                              "category": "TREATMENT", "condition_code": "DXB"}
                         ])
    # SUBMITTED is admissible for adjudication, so only the temporal gate
    # fails and it is the error that surfaces.
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_WAITING_PERIOD_ACTIVE)
    still = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert still["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Queue A: Difficulty / cross_entity_state_dependency
# ---------------------------------------------------------------------------

def test_adjudication_gated_by_hospital_status(api):
    """PRD 3.5: "Two gates apply at submission: the hospital must be ACTIVE
    (else ERR_HOSPITAL_NOT_ACTIVE, HTTP 409) and the policy's
    lifecycle_status must be ACTIVE (else ERR_POLICY_NOT_ACTIVE, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/adjudication_gated_by_hospital_status
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    assert claim["status"] == "SUBMITTED"
    validate_success(api.suspend_hospital(hospital["id"], ADMIN))
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "hospital_id": hospital["id"],
            "visit_date": "2026-10-05",
            "claim_type": "INJURY",
            "lines": [
                {"description": "er2", "amount_cents": 60000,
                 "category": "TREATMENT", "condition_code": "DXE"}
            ],
        },
        make_hospital_staff_headers(hospital["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HOSPITAL_NOT_ACTIVE)
    # The pre-suspension claim was denied by the cascade — the rejection came
    # from hospital state, not claim state.
    after = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert after["status"] == "DENIED"
    assert after["denial_reason"] == "HOSPITAL_SUSPENDED"


def test_submission_accepted_while_hospital_active_then_rejected_after_suspend(api):
    """PRD 3.5: "At the counter, HospitalStaff submit a claim with the
    policy_id, the treating hospital_id, the visit_date, the claim_type
    (INJURY or ILLNESS), and the invoice lines."
    PRD 3.5: "Two gates apply at submission: the hospital must be ACTIVE
    (else ERR_HOSPITAL_NOT_ACTIVE, HTTP 409) and the policy's
    lifecycle_status must be ACTIVE (else ERR_POLICY_NOT_ACTIVE, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/adjudication_gated_by_hospital_status
    """
    hospital, policy = setup_active_environment()
    staff = make_hospital_staff_headers(hospital["id"])
    # Identical well-formed payloads: the only difference is hospital state.
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "hospital_id": hospital["id"],
            "visit_date": "2026-10-02",
            "claim_type": "INJURY",
            "lines": [
                {"description": "er", "amount_cents": 50000,
                 "category": "TREATMENT", "condition_code": "DXA"}
            ],
        },
        staff,
    )
    claim = validate_success(resp, expected_status=201)
    validate_success(api.suspend_hospital(hospital["id"], ADMIN))
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "hospital_id": hospital["id"],
            "visit_date": "2026-10-05",
            "claim_type": "INJURY",
            "lines": [
                {"description": "er2", "amount_cents": 60000,
                 "category": "TREATMENT", "condition_code": "DXE"}
            ],
        },
        staff,
    )
    validate_error(resp, ApiErrorId.ERR_HOSPITAL_NOT_ACTIVE)
    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"policy_id": policy["id"]})
    )
    assert len(data) == 1
    assert data[0]["id"] == claim["id"]


def test_claim_submission_gated_by_policy_lifecycle(api):
    """PRD 3.5: "Two gates apply at submission: the hospital must be ACTIVE
    (else ERR_HOSPITAL_NOT_ACTIVE, HTTP 409) and the policy's
    lifecycle_status must be ACTIVE (else ERR_POLICY_NOT_ACTIVE, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_submission_gated_by_policy_lifecycle
    """
    hospital, policy = setup_active_environment()
    validate_success(api.cancel_policy(policy["id"], make_pet_owner_headers(policy["id"])))
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "hospital_id": hospital["id"],
            "visit_date": "2026-10-05",
            "claim_type": "INJURY",
            "lines": [
                {"description": "er", "amount_cents": 40000,
                 "category": "TREATMENT", "condition_code": "DXE"}
            ],
        },
        make_hospital_staff_headers(hospital["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)
    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"policy_id": policy["id"]})
    )
    assert len(data) == 0


def test_cancelled_policy_rejects_submission_regardless_of_hospital_state(api):
    """PRD 3.3: "An owner cancels their own ACTIVE policy — the X-User-ID
    must equal the policy's id-bound owner identity, otherwise
    ERR_UNAUTHORIZED — moving it to CANCELLED."
    PRD 3.5: "Two gates apply at submission: the hospital must be ACTIVE
    (else ERR_HOSPITAL_NOT_ACTIVE, HTTP 409) and the policy's
    lifecycle_status must be ACTIVE (else ERR_POLICY_NOT_ACTIVE, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_submission_gated_by_policy_lifecycle
    """
    hospital, policy = setup_active_environment()
    cancelled = validate_success(
        api.cancel_policy(policy["id"], make_pet_owner_headers(policy["id"]))
    )
    assert cancelled["lifecycle_status"] == "CANCELLED"
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "hospital_id": hospital["id"],
            "visit_date": "2026-10-05",
            "claim_type": "INJURY",
            "lines": [
                {"description": "er", "amount_cents": 40000,
                 "category": "TREATMENT", "condition_code": "DXE"}
            ],
        },
        make_hospital_staff_headers(hospital["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)
    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"policy_id": policy["id"]})
    )
    assert len(data) == 0


# ---------------------------------------------------------------------------
# Queue A: Difficulty / resource_temporal_overlap — filing supersession
# ---------------------------------------------------------------------------

def test_effective_filing_supersession_intervals(api):
    """PRD 3.1: "The effectiveness transition carries a supersession cascade:
    any other EFFECTIVE filing for the same pair of territory_code and
    species is immediately moved to SUPERSEDED, so at most one filing per
    territory-and-species pair is ever effective at a time."
    PRD 3.3: "When several qualify, the newest is chosen — the one with the
    latest filing_effective_date, breaking ties by the latest effective_at
    and then the latest created_at."

    Design: Difficulty/resource_temporal_overlap/effective_filing_supersession_intervals
    """
    set_clock("2026-09-01T00:00:00Z")
    f1 = create_and_file_filing(
        base_monthly_premium_cents=100000,
        age_band_multipliers={"0": 1.0, "1": 1.0025},
        filing_effective_date="2026-09-01",
        regulator_reference="CA-2026-001",
    )
    early = create_policy(owner_name="Eli Ford", pet_name="Bao", breed="Corgi",
                          pet_date_of_birth="2025-01-01", coverage_start="2026-09-01")
    assert early["applied_filing_id"] == f1["id"]
    f2 = create_and_file_filing(
        base_monthly_premium_cents=110000,
        age_band_multipliers={"0": 1.0, "1": 1.0025},
        filing_effective_date="2026-10-01",
        regulator_reference="CA-2026-010",
    )
    set_clock("2026-10-01T00:00:00Z")
    late = create_policy(owner_name="Faye Gao", pet_name="Mochi", breed="Husky",
                         pet_date_of_birth="2025-01-01", coverage_start="2026-10-01")
    assert late["applied_filing_id"] == f2["id"]
    assert late["filed_base_cents"] == 110000
    f1_after = get_success_data(api.get_rate_filing(f1["id"], RATE_ADMIN))
    assert f1_after["status"] == "SUPERSEDED"


def test_superseded_is_terminal_and_single_effective_per_key(api):
    """PRD 3.1: "A filed filing becomes EFFECTIVE automatically — evaluated
    lazily on read and eagerly by the clock sweep — once the current logical
    date reaches the filing_effective_date at 00:00:00Z; at that moment
    effective_at is stamped and the version increments."
    PRD 3.1: "SUPERSEDED is terminal."

    Design: Difficulty/resource_temporal_overlap/effective_filing_supersession_intervals
    """
    set_clock("2026-09-01T00:00:00Z")
    f1 = create_and_file_filing(
        base_monthly_premium_cents=100000,
        age_band_multipliers={"0": 1.0, "1": 1.0025},
        filing_effective_date="2026-09-01",
        regulator_reference="CA-2026-001",
    )
    f2 = create_and_file_filing(
        base_monthly_premium_cents=110000,
        age_band_multipliers={"0": 1.0, "1": 1.0025},
        filing_effective_date="2026-10-01",
        regulator_reference="CA-2026-010",
    )
    set_clock("2026-10-01T00:00:00Z")
    f1_after = get_success_data(api.get_rate_filing(f1["id"], RATE_ADMIN))
    f2_after = get_success_data(api.get_rate_filing(f2["id"], RATE_ADMIN))
    assert f1_after["status"] == "SUPERSEDED"
    assert f2_after["status"] == "EFFECTIVE"
    data, meta = validate_paginated(
        api.list_rate_filings(RATE_ADMIN, params={"territory_code": "941", "status": "EFFECTIVE"})
    )
    assert len(data) == 1
    assert data[0]["id"] == f2["id"]


# ---------------------------------------------------------------------------
# Queue B: Corner / state_machines — hospital and policy transitions
# ---------------------------------------------------------------------------

def test_hospital_approve_requires_applied_state(api):
    """PRD 3.2: "Approving a hospital that is not in APPLIED status is
    rejected with ERR_HOSPITAL_NOT_APPROVABLE (HTTP 409)."

    Design: Corner/state_machines/hospital_approve_requires_applied_state
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital = get_success_data(api.create_hospital(create_hospital_payload(), ADMIN))
    approved = validate_success(api.approve_hospital(
        hospital["id"], {"expected_hospital_version": hospital["version"]}, ADMIN
    ))
    assert approved["status"] == "APPROVED"
    resp = api.approve_hospital(
        hospital["id"], {"expected_hospital_version": approved["version"]}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_HOSPITAL_NOT_APPROVABLE)
    still = get_success_data(api.get_hospital(hospital["id"], ADMIN))
    assert still["status"] == "APPROVED"


def test_hospital_reinstate_restores_active_without_reopening_claims(api):
    """PRD 3.2: "Reinstatement by a PlatformAdmin moves a SUSPENDED hospital
    back to ACTIVE and increments its version, but it deliberately does not
    reopen the claims the suspension denied — those claims remain DENIED and
    must find their remedy, if any, through the appeal process."

    Design: Corner/state_machines/hospital_reinstate_restores_active_from_suspended
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    validate_success(api.suspend_hospital(hospital["id"], ADMIN))
    resp = api.reinstate_hospital(hospital["id"], ADMIN)
    reinstated = validate_success(resp)
    assert reinstated["status"] == "ACTIVE"
    after = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert after["status"] == "DENIED"
    assert after["denial_reason"] == "HOSPITAL_SUSPENDED"


def test_claim_initial_state_is_submitted(api):
    """PRD 3.5: "Submission creates the claim in SUBMITTED status with all
    totals zeroed until adjudication, mints the lines as ClaimLine resources
    numbered by seq from 1 upward in submission order, and returns 201."

    Design: Corner/state_machines/claim_initial_state_is_submitted
    """
    hospital, policy = setup_active_environment()
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "hospital_id": hospital["id"],
            "visit_date": "2026-10-02",
            "claim_type": "ILLNESS",
            "lines": [
                {"description": "labs", "amount_cents": 30000,
                 "category": "TREATMENT", "condition_code": "DXB"}
            ],
        },
        make_hospital_staff_headers(hospital["id"]),
    )
    claim = validate_success(resp, expected_status=201)
    assert claim["status"] == "SUBMITTED"
    assert claim["version"] == 1


def test_policy_mark_lapsed_terminal(api):
    """PRD 3.3: "the lifecycle dimension runs ACTIVE -> CANCELLED or LAPSED
    (both terminal)."
    PRD 3.3: "A PlatformAdmin marks an ACTIVE policy LAPSED for premium
    non-payment."

    Design: Corner/state_machines/policy_mark_lapsed_terminal
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    policy = create_policy()
    lapsed = validate_success(api.mark_lapsed(policy["id"], ADMIN))
    assert lapsed["lifecycle_status"] == "LAPSED"
    resp = api.cancel_policy(policy["id"], make_pet_owner_headers(policy["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api.recalculate_premium(policy["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_lapsed_policy_is_not_revived_by_clock_sweep(api):
    """PRD 3.3: "the lifecycle dimension runs ACTIVE -> CANCELLED or LAPSED
    (both terminal)."
    PRD 3.3: "Recalculation requires the policy's lifecycle_status to be
    ACTIVE and the current logical date to be at or past next_birthday."

    Design: Corner/state_machines/policy_mark_lapsed_terminal
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    policy = create_policy(pet_date_of_birth="2025-09-01", coverage_start="2026-09-01")
    validate_success(api.mark_lapsed(policy["id"], ADMIN))
    # Sweep past the pet's next birthday: a LAPSED policy must not be
    # recalculated or revived by the age-band sweep.
    set_clock("2027-09-01T00:00:00Z")
    still = get_success_data(api.get_policy(policy["id"], ADMIN))
    assert still["lifecycle_status"] == "LAPSED"
    assert still["current_monthly_premium_cents"] == policy["current_monthly_premium_cents"]
    resp = api.recalculate_premium(policy["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_filing_file_requires_draft_state(api):
    """PRD 3.1: "Filing anything that is not in DRAFT status is rejected with
    ERR_FILING_NOT_FILABLE (HTTP 409)."

    Design: Corner/state_machines/filing_file_requires_draft_state
    """
    set_clock("2026-09-01T00:00:00Z")
    filing = create_and_file_filing()
    # PRD does not pin whether the file call's own response shows the FILED
    # state or already reflects the lazy FILED -> EFFECTIVE evaluation (the
    # effective date 2026-09-01 has been reached by the default clock).
    assert filing["status"] in ("FILED", "EFFECTIVE")
    resp = api.file_rate_filing(filing["id"], RATE_ADMIN)
    validate_error(resp, ApiErrorId.ERR_FILING_NOT_FILABLE)
    still = get_success_data(api.get_rate_filing(filing["id"], RATE_ADMIN))
    # The filing's effective date (2026-09-01) has been reached by the
    # logical clock, so the lazy effectiveness evaluation has moved it to
    # EFFECTIVE (PRD 3.1) — still not DRAFT, so re-filing stays rejected.
    assert still["status"] == "EFFECTIVE"


# ---------------------------------------------------------------------------
# Queue B: Corner / validations + errors + endpoints (OCC, filters)
# ---------------------------------------------------------------------------

def test_missing_auth_headers_rejected_before_anything(api):
    """PRD 2.1: "A request missing either header, or carrying a malformed
    value, is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    (HTTP 400) before any other check runs."

    Design: Corner/validations/missing_auth_headers_rejected_before_anything
    """
    resp = api.get_policy(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    resp = api.get_policy(NON_EXISTENT_UUID, headers={"X-User-ID": "admin-1"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    resp = api.get_policy(NON_EXISTENT_UUID, headers={"X-User-Role": "PlatformAdmin"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_role_denied_on_exclusive_endpoint(api):
    """PRD 2.1: "A request whose role is not permitted for the operation — or
    whose entity-backed identity check fails (wrong hospital, wrong owner) —
    is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/validations/role_denied_on_exclusive_endpoint
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital = get_success_data(api.create_hospital(create_hospital_payload(), ADMIN))
    resp = api.suspend_hospital(hospital["id"], ADJ1)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    still = get_success_data(api.get_hospital(hospital["id"], ADMIN))
    assert still["status"] == "APPLIED"


def test_occ_adjudicate_stale_version_rejected(api):
    """PRD 2.5: "An adjudication request on a claim must carry
    expected_claim_version, equal to the claim's version the client last
    observed. If the claim's current version has advanced since then — for
    example because another adjuster already flagged, cleared, adjudicated,
    or denied it — the request is rejected with ERR_STALE_CLAIM_VERSION
    (HTTP 412), and no mutation occurs."

    Design: Corner/endpoints/occ_adjudicate_stale_version_rejected
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    assert claim["version"] == 1
    validate_success(api.flag_preexisting_review(claim["id"], ADJ1))  # version -> 2
    fresh = get_success_data(api.get_claim(claim["id"], ADJ1))
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": fresh["version"] - 1}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION)
    still = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert still["status"] == "PREEXISTING_REVIEW"
    validate_success(api.clear_preexisting_review(claim["id"], ADJ1))
    fresh2 = get_success_data(api.get_claim(claim["id"], ADJ1))
    adjudicated = validate_success(api.adjudicate_claim(
        claim["id"], {"expected_claim_version": fresh2["version"]}, ADJ1
    ))
    assert adjudicated["status"] == "ADJUDICATED"


def test_occ_hospital_approve_stale_version_rejected(api):
    """PRD 2.5: "A hospital approval request must carry
    expected_hospital_version, equal to the hospital's version the client
    last observed. If the hospital's current version does not match, the
    request is rejected with ERR_STALE_HOSPITAL_VERSION (HTTP 412). An
    administrator acting on a stale snapshot must re-read the hospital before
    retrying."

    Design: Corner/endpoints/occ_hospital_approve_stale_version_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital = get_success_data(api.create_hospital(create_hospital_payload(), ADMIN))
    assert hospital["version"] == 1
    approved = validate_success(api.approve_hospital(
        hospital["id"], {"expected_hospital_version": 1}, ADMIN
    ))
    assert approved["version"] == 2
    # Replay the stale token: OCC fires instead of the state check.
    resp = api.approve_hospital(
        hospital["id"], {"expected_hospital_version": 1}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_STALE_HOSPITAL_VERSION)
    still = get_success_data(api.get_hospital(hospital["id"], ADMIN))
    assert still["version"] == 2


def test_claim_list_filters_by_multiple_dimensions(api):
    """PRD 3.5: "Claims can be listed with policy_id, hospital_id, status,
    claim_type, and payment_id filters."
    PRD 2.3: "total_count is the number of records matching the filter (not
    just the returned page)."

    Design: Corner/endpoints/claim_list_filters_by_multiple_dimensions
    """
    hospital, policy = setup_active_environment()
    claim1 = submit_claim(policy, hospital)
    claim1 = adjudicate_claim(claim1)
    claim2 = submit_claim(policy, hospital, visit_date="2026-10-03",
                          claim_type="ILLNESS",
                          lines=[
                              {"description": "labs", "amount_cents": 30000,
                               "category": "TREATMENT", "condition_code": "DXB"}
                          ])

    data, meta = validate_paginated(api.list_claims(
        ADJ1, params={"policy_id": policy["id"], "status": "ADJUDICATED"}
    ))
    assert len(data) == 1
    assert data[0]["id"] == claim1["id"]

    data, meta = validate_paginated(api.list_claims(
        ADJ1, params={"hospital_id": hospital["id"], "claim_type": "ILLNESS"}
    ))
    assert len(data) == 1
    assert data[0]["id"] == claim2["id"]

    data, meta = validate_paginated(api.list_claims(ADJ1, params={"status": "SUBMITTED"}))
    assert len(data) == 1
    assert data[0]["id"] == claim2["id"]


def test_error_envelope_shape_on_every_failure(api):
    """PRD 2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with "response_type": "error" and a data object
    carrying error_id and message; "The meta object for error responses
    contains only api_request_id and api_request_timestamp."

    Design: Corner/errors/error_envelope_shape_on_every_failure
    """
    resp = api.get_claim(NON_EXISTENT_UUID, ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_CLAIM_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


# ---------------------------------------------------------------------------
# Queue B: Corner / rbac
# ---------------------------------------------------------------------------

def test_hospital_staff_cannot_act_for_other_hospital(api):
    """PRD 2.1: "HospitalStaff identity is entity-backed: when X-User-Role is
    HospitalStaff, X-User-ID is the id of the acting Hospital, and any
    operation restricted to \"staff of this hospital\" compares the request's
    hospital path or body reference to X-User-ID."

    Design: Corner/rbac/hospital_staff_cannot_act_for_other_hospital
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    h1 = create_active_hospital()
    h2 = create_active_hospital(legal_name="North Beach Vet", bank_account_ref="BA-002")
    policy = create_policy_past_waiting()
    # Staff of H1 submitting a claim naming hospital_id = H2 is unauthorized.
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "hospital_id": h2["id"],
            "visit_date": "2026-10-02",
            "claim_type": "INJURY",
            "lines": [
                {"description": "er", "amount_cents": 50000,
                 "category": "TREATMENT", "condition_code": "DXA"}
            ],
        },
        make_hospital_staff_headers(h1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"hospital_id": h2["id"]})
    )
    assert len(data) == 0


def test_pet_owner_cannot_adjudicate_or_touch_other_policy(api):
    """PRD 2.1: "PetOwner identity is entity-backed: when X-User-Role is
    PetOwner, X-User-ID is the id of the owner's Policy (the policyId-bound
    owner id), and ownership checks on any resource that references a Policy
    compare the resource's policy foreign key to X-User-ID."
    PRD 2.1: "A request whose role is not permitted for the operation — or
    whose entity-backed identity check fails (wrong hospital, wrong owner) —
    is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/pet_owner_cannot_adjudicate_or_touch_other_policy
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    hospital = create_active_hospital()
    policy_a = create_policy_past_waiting()
    policy_b = create_policy(owner_name="Owner B", pet_name="Zed", breed="Beagle",
                             pet_date_of_birth="2023-01-01")
    claim = submit_claim(policy_a, hospital)
    # Role gate: adjudicate is adjuster-exclusive.
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": claim["version"]},
        make_pet_owner_headers(policy_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    still = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert still["status"] == "SUBMITTED"
    # Ownership gate: the id-bound owner of policy A may not cancel policy B.
    resp = api.cancel_policy(policy_b["id"], make_pet_owner_headers(policy_a["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    still_b = get_success_data(api.get_policy(policy_b["id"], ADMIN))
    assert still_b["lifecycle_status"] == "ACTIVE"


def test_rate_filing_admin_cannot_onboard_hospitals(api):
    """PRD 2.1: "A request whose role is not permitted for the operation — or
    whose entity-backed identity check fails (wrong hospital, wrong owner) —
    is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD 2.1: "A PlatformAdmin is the insurer's platform operator: it onboards
    hospitals, marks policies lapsed for non-payment, forces premium
    recalculation, generates and acknowledges reconciliation reports, and
    controls the logical clock."

    Design: Corner/rbac/rate_filing_admin_cannot_onboard_hospitals
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_hospital(
        create_hospital_payload(legal_name="Rogue Vet", bank_account_ref="BA-009",
                                checkout_software_version="9.9.9"),
        RATE_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    data, meta = validate_paginated(api.list_hospitals(ADMIN))
    assert len(data) == 0


# ---------------------------------------------------------------------------
# Queue B: Corner / cross_cutting_layers — fixed default clock
# ---------------------------------------------------------------------------

def test_clock_default_is_fixed_not_wall_clock(api):
    """PRD 2.4: "All time in the system is governed by a logical clock, never
    the wall clock. Before any clock operation is performed, the logical
    clock stands at exactly 2026-09-01T00:00:00Z."
    PRD 3.1: "A filed filing becomes EFFECTIVE automatically — evaluated
    lazily on read and eagerly by the clock sweep — once the current logical
    date reaches the filing_effective_date at 00:00:00Z"

    Design: Corner/cross_cutting_layers/clock_default_is_fixed_not_wall_clock
    """
    # No clock call issued: the logical clock defaults to 2026-09-01T00:00:00Z.
    resp = api.create_rate_filing(
        {
            "territory_code": "941",
            "state_code": "CA",
            "species": "DOG",
            "base_monthly_premium_cents": 100000,
            "age_band_multipliers": {"0": 1.0},
            "filing_effective_date": "2026-09-01",
            "regulator_reference": "CA-2026-DEF",
        },
        RATE_ADMIN,
    )
    filing = validate_success(resp, expected_status=201)
    # Effective date equal to the default logical date is not retroactive.
    validate_success(api.file_rate_filing(filing["id"], RATE_ADMIN))
    after = get_success_data(api.get_rate_filing(filing["id"], RATE_ADMIN))
    assert after["status"] == "EFFECTIVE"
