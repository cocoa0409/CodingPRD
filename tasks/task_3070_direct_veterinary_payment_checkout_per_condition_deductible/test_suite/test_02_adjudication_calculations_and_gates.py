"""Checkout adjudication: rounding, deductible waterfall, waiting periods,
pre-existing determination, and intake validations."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_hospital_staff_headers,
    make_adjuster_headers,
    set_clock,
    create_and_file_filing,
    create_active_hospital,
    create_policy,
    create_policy_past_waiting,
    create_policy_payload,
    setup_active_environment,
    setup_adjudicated_claim,
    submit_claim,
    adjudicate_claim,
    pay_claim,
    upload_medical_record,
    find_condition,
    assert_claim_totals_consistent,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RATE_ADMIN = TEST_USERS["rate_filing_admin_headers"]
ADJ1 = TEST_USERS["adjuster_1_headers"]


# ---------------------------------------------------------------------------
# Queue A: Difficulty / combinatorial_formula — per-line rounding then sum
# ---------------------------------------------------------------------------

def test_per_line_rounding_then_sum_diverges_from_sum_then_round(api):
    """PRD 2.6: "Every premium multiplication and every per-line reimbursement
    multiplication is rounded half-up to whole cents at the per-line (or
    per-premium) multiplication step only; claim-level totals are then formed
    by summing the already-rounded per-line values. Sum-then-round is
    forbidden."

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_diverges
    """
    hospital, policy, claim = setup_adjudicated_claim(
        per_condition_deductible_cents=0,
        reimbursement_rate=0.9,
        pet_date_of_birth="2020-01-15",
        owner_name="Bo Lin",
        pet_name="Tofu",
        breed="Mix",
        lines=[
            {"description": "l1", "amount_cents": 8148, "category": "TREATMENT", "condition_code": "DX1"},
            {"description": "l2", "amount_cents": 8148, "category": "TREATMENT", "condition_code": "DX2"},
            {"description": "l3", "amount_cents": 8148, "category": "TREATMENT", "condition_code": "DX3"},
        ],
    )
    # Per line: round_half_up(8148 * 0.9) = round_half_up(7333.2) = 7333.
    assert claim["reimbursement_cents"] == 21999, (
        "per-line rounding then sum pins 7333 x 3 = 21999; sum-then-round "
        "would yield 22000 and differs by exactly 1 cent"
    )
    assert claim["eligible_cents"] == 24444
    assert claim["member_responsibility_cents"] == 2445
    data, meta = validate_paginated(api.list_claim_lines_of_claim(claim["id"], ADJ1))
    assert len(data) == 3
    for line in data:
        assert line["reimbursement_cents"] == 7333


def test_per_line_rounding_visible_on_each_line(api):
    """PRD 3.5: "The line's reimbursement base is its eligible_amount_cents
    minus its deductible_applied_cents, and its reimbursement_cents is that
    base multiplied by the policy's reimbursement_rate, rounded half-up to
    whole cents at this per-line step."

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_diverges
    """
    hospital, policy, claim = setup_adjudicated_claim(
        per_condition_deductible_cents=0,
        reimbursement_rate=0.9,
        pet_date_of_birth="2020-01-15",
        lines=[
            {"description": "l1", "amount_cents": 8148, "category": "TREATMENT", "condition_code": "DX1"},
            {"description": "l2", "amount_cents": 8148, "category": "TREATMENT", "condition_code": "DX2"},
            {"description": "l3", "amount_cents": 8148, "category": "TREATMENT", "condition_code": "DX3"},
        ],
    )
    data, meta = validate_paginated(api.list_claim_lines_of_claim(claim["id"], ADJ1))
    by_seq = {line["seq"]: line for line in data}
    for seq in (1, 2, 3):
        assert by_seq[seq]["eligible_amount_cents"] == 8148
        assert by_seq[seq]["deductible_applied_cents"] == 0
        assert by_seq[seq]["reimbursement_cents"] == 7333
    assert claim["reimbursement_cents"] == sum(l["reimbursement_cents"] for l in data)


# ---------------------------------------------------------------------------
# Queue A: Difficulty / non_linear_state_machine — review cycle
# ---------------------------------------------------------------------------

def test_review_cycle_bounces_claim_and_bumps_version(api):
    """PRD 3.5: "An adjuster may instead route a claim into pre-existing
    review: flagging moves SUBMITTED -> PREEXISTING_REVIEW, and clearing
    moves PREEXISTING_REVIEW -> SUBMITTED, each incrementing the version.
    This cycle exists so a review can bounce a claim back for re-adjudication
    without losing it."

    Design: Difficulty/non_linear_state_machine/claim_preexisting_review_cycle
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    assert claim["version"] == 1

    resp = api.flag_preexisting_review(claim["id"], ADJ1)
    flagged = validate_success(resp)
    assert flagged["status"] == "PREEXISTING_REVIEW"
    assert flagged["version"] == 2

    resp = api.clear_preexisting_review(claim["id"], ADJ1)
    cleared = validate_success(resp)
    assert cleared["status"] == "SUBMITTED"
    assert cleared["version"] == 3

    resp = api.adjudicate_claim(claim["id"], {"expected_claim_version": 3}, ADJ1)
    adjudicated = validate_success(resp)
    assert adjudicated["status"] == "ADJUDICATED"
    # 50000 - 20000 deductible = 30000 base, x 0.9 = 27000.
    assert adjudicated["reimbursement_cents"] == 27000


def test_review_cycle_forces_occ_token_reread(api):
    """PRD 2.5: "An adjudication request on a claim must carry
    expected_claim_version, equal to the claim's version the client last
    observed. If the claim's current version has advanced since then — for
    example because another adjuster already flagged, cleared, adjudicated,
    or denied it — the request is rejected with ERR_STALE_CLAIM_VERSION
    (HTTP 412), and no mutation occurs."

    Design: Difficulty/non_linear_state_machine/claim_preexisting_review_cycle
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    api.flag_preexisting_review(claim["id"], ADJ1)
    api.clear_preexisting_review(claim["id"], ADJ1)
    fresh = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert fresh["version"] == 3, "create=1, flag=2, clear=3"
    # A token from before the cycle is stale.
    resp = api.adjudicate_claim(claim["id"], {"expected_claim_version": 1}, ADJ1)
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION)
    # The re-read token adjudicates.
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": fresh["version"]}, ADJ1
    )
    adjudicated = validate_success(resp)
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["reimbursement_cents"] == 27000


# ---------------------------------------------------------------------------
# Queue A: Difficulty / boundary_precision_check — waiting-period boundary
# ---------------------------------------------------------------------------

def test_waiting_period_rejects_one_second_before_boundary(api):
    """PRD 3.5: "The waiting-period gate follows: an INJURY claim requires the
    current logical clock to be at or past the policy's injury_waiting_end,
    and an ILLNESS claim requires it to be at or past illness_waiting_end; the
    boundary is inclusive — a claim adjudicated at exactly the waiting end
    passes — and a violation is ERR_WAITING_PERIOD_ACTIVE (HTTP 409)."

    Design: Difficulty/boundary_precision_check/waiting_period_inclusive_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    hospital = create_active_hospital()
    policy = create_policy()  # injury_waiting_end == 2026-09-06T00:00:00Z
    set_clock("2026-09-05T23:59:59Z")
    claim = submit_claim(policy, hospital, visit_date="2026-09-05")
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_WAITING_PERIOD_ACTIVE)


def test_waiting_period_boundary_is_inclusive(api):
    """PRD 3.5: "the boundary is inclusive — a claim adjudicated at exactly
    the waiting end passes — and a violation is ERR_WAITING_PERIOD_ACTIVE
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/waiting_period_inclusive_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    hospital = create_active_hospital()
    policy = create_policy()
    set_clock("2026-09-05T23:59:59Z")
    claim = submit_claim(policy, hospital, visit_date="2026-09-05")
    # Negative probe first: one second early.
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_WAITING_PERIOD_ACTIVE)
    # The failed attempt must not consume the OCC token.
    still = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert still["version"] == claim["version"]
    # Exactly at injury_waiting_end the same token passes.
    set_clock("2026-09-06T00:00:00Z")
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": still["version"]}, ADJ1
    )
    adjudicated = validate_success(resp)
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["reimbursement_cents"] == 27000


# ---------------------------------------------------------------------------
# Queue A: Difficulty / boundary_precision_check — zero-remaining deductible
# ---------------------------------------------------------------------------

def test_line_exactly_exhausting_deductible_reimburses_zero(api):
    """PRD 3.5: "For each line, the condition's remaining deductible is its
    deductible_target_cents minus its deductible_accumulated_cents so far;
    the line's deductible_applied_cents is the smaller of that remaining
    amount and the line's eligible_amount_cents"
    PRD 3.6: "A claim whose reimbursement_cents is zero is still payable: a
    payment of 0 is created normally."

    Design: Difficulty/boundary_precision_check/deductible_exact_zero_remaining_boundary
    """
    hospital, policy = setup_active_environment()
    staff = make_hospital_staff_headers(hospital["id"])
    # Claim A consumes 10000 of the 20000 deductible.
    claim_a = submit_claim(policy, hospital, lines=[
        {"description": "exam-adjacent tx", "amount_cents": 10000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    claim_a = adjudicate_claim(claim_a)
    pay_claim(claim_a, hospital, "KA")
    # Claim B of 10000 meets exactly the remaining 10000.
    claim_b = submit_claim(policy, hospital, visit_date="2026-10-03", lines=[
        {"description": "suture", "amount_cents": 10000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    claim_b = adjudicate_claim(claim_b)
    assert claim_b["deductible_applied_cents"] == 10000
    assert claim_b["reimbursement_cents"] == 0
    condition = find_condition(policy, "DXA")
    assert condition["deductible_accumulated_cents"] == 20000
    assert condition["deductible_target_cents"] == 20000
    resp = api.checkout_pay(claim_b["id"], {"idempotency_key": "KB"}, staff)
    payment = validate_success(resp)
    assert payment["amount_cents"] == 0
    assert payment["status"] == "SETTLED"
    assert payment["ledger_status"] == "POSTED"


def test_zero_reimbursement_payment_does_not_move_ledger(api):
    """PRD 3.6: "On success the payment is born with status SETTLED and
    ledger_status POSTED; the claim moves ADJUDICATED -> PAID; each mapped
    condition's lifetime_reimbursed_cents is incremented by its lines'
    reimbursement amounts — again uncapped; and the hospital's
    running_ledger_balance_cents increases by the payment amount."

    Design: Difficulty/boundary_precision_check/deductible_exact_zero_remaining_boundary
    """
    from test_helpers import hospital_ledger
    hospital, policy = setup_active_environment()
    staff = make_hospital_staff_headers(hospital["id"])
    claim_a = submit_claim(policy, hospital, lines=[
        {"description": "exam-adjacent tx", "amount_cents": 10000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    claim_a = adjudicate_claim(claim_a)
    assert claim_a["reimbursement_cents"] == 0
    payment, claim_a = pay_claim(claim_a, hospital, "KA")
    assert payment["amount_cents"] == 0
    assert hospital_ledger(hospital["id"]) == 0

    claim_b = submit_claim(policy, hospital, visit_date="2026-10-03", lines=[
        {"description": "suture", "amount_cents": 10000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    claim_b = adjudicate_claim(claim_b)
    assert claim_b["deductible_applied_cents"] == 10000
    assert claim_b["reimbursement_cents"] == 0
    condition = find_condition(policy, "DXA")
    assert condition["deductible_accumulated_cents"] == 20000
    resp = api.checkout_pay(claim_b["id"], {"idempotency_key": "KB"}, staff)
    payment = validate_success(resp)
    assert payment["amount_cents"] == 0
    assert payment["status"] == "SETTLED"
    assert hospital_ledger(hospital["id"]) == 0


# ---------------------------------------------------------------------------
# Queue B: Corner / calculations
# ---------------------------------------------------------------------------

def test_adjudication_totals_exclude_exam_and_tax_lines(api):
    """PRD 3.5: "A line of any other category — EXAM_FEE, TAX, or
    OTHER_EXCLUDED — gets an eligible_amount_cents of 0 and a null
    policy_condition_id: exam fees and taxes are never covered."
    PRD 3.5: "total_invoice_cents the sum of all lines' amount_cents
    (excluded lines included), and member_responsibility_cents the
    total_invoice_cents minus the reimbursement_cents."

    Design: Corner/calculations/adjudication_totals_exclude_exam_and_tax_lines
    """
    hospital, policy, claim = setup_adjudicated_claim(lines=[
        {"description": "exam", "amount_cents": 7000, "category": "EXAM_FEE"},
        {"description": "surgery", "amount_cents": 30000,
         "category": "TREATMENT", "condition_code": "DXA"},
        {"description": "tax", "amount_cents": 3000, "category": "TAX"},
        {"description": "meds", "amount_cents": 10000,
         "category": "TREATMENT", "condition_code": "DXA"},
    ])
    assert claim["total_invoice_cents"] == 50000
    assert claim["eligible_cents"] == 40000
    # Waterfall in seq order: line 2 consumes the whole 20000 deductible,
    # line 4 consumes 0. Reimbursement 9000 + 9000.
    assert claim["deductible_applied_cents"] == 20000
    assert claim["reimbursement_cents"] == 18000
    assert claim["member_responsibility_cents"] == 32000
    assert_claim_totals_consistent(claim)
    data, meta = validate_paginated(api.list_claim_lines_of_claim(claim["id"], ADJ1))
    by_seq = {line["seq"]: line for line in data}
    assert by_seq[1]["eligible_amount_cents"] == 0
    assert by_seq[1]["policy_condition_id"] is None
    assert by_seq[3]["eligible_amount_cents"] == 0
    assert by_seq[3]["policy_condition_id"] is None
    assert by_seq[2]["deductible_applied_cents"] == 20000
    assert by_seq[2]["reimbursement_cents"] == 9000
    assert by_seq[4]["deductible_applied_cents"] == 0
    assert by_seq[4]["reimbursement_cents"] == 9000


def test_condition_deductible_accumulates_across_claims_lifetime(api):
    """PRD 1: "deductibles are tracked per condition over the pet's lifetime
    rather than per policy year: once the deductible for a given condition is
    consumed, every subsequent treatment of that same condition is reimbursed
    without further deductible."
    PRD 3.5: "There is no payout cap: reimbursement_cents is unbounded by any
    annual or lifetime maximum."

    Design: Corner/calculations/condition_deductive_accumulates_across_claims_lifetime
    """
    hospital, policy = setup_active_environment()
    claim1 = submit_claim(policy, hospital, lines=[
        {"description": "surgery", "amount_cents": 50000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    claim1 = adjudicate_claim(claim1)
    assert claim1["deductible_applied_cents"] == 20000
    assert claim1["reimbursement_cents"] == 27000
    pay_claim(claim1, hospital, "KLC1")

    claim2 = submit_claim(policy, hospital, visit_date="2026-10-09", lines=[
        {"description": "followup", "amount_cents": 50000,
         "category": "TREATMENT", "condition_code": "DXA"}
    ])
    claim2 = adjudicate_claim(claim2)
    assert claim2["deductible_applied_cents"] == 0
    assert claim2["reimbursement_cents"] == 45000
    pay_claim(claim2, hospital, "KLC2")

    condition = find_condition(policy, "DXA")
    assert condition["deductible_accumulated_cents"] == 20000
    assert condition["lifetime_reimbursed_cents"] == 72000


def test_preexisting_boundary_record_on_coverage_start_is_not_preexisting(api):
    """PRD 3.4: "The condition is pre-existing if any such record has a
    recorded_at strictly before coverage_start at 00:00:00Z. The boundary is
    sharp: a record dated exactly on the coverage start date — at or after
    that midnight — does not count as pre-existing."

    Design: Corner/calculations/preexisting_boundary_record_on_coverage_start_is_not_preexisting
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    hospital = create_active_hospital()
    policy_on = create_policy(owner_name="On Boundary", pet_name="Aki",
                              pet_date_of_birth="2024-01-01")
    policy_before = create_policy(owner_name="Before Boundary", pet_name="Bo",
                                  pet_date_of_birth="2024-01-01")
    upload_medical_record(policy_on, hospital, record_type="EXAM",
                          recorded_at="2026-09-01T00:00:00Z",
                          diagnosis_code="DXA", notes="exactly at start")
    upload_medical_record(policy_before, hospital, record_type="EXAM",
                          recorded_at="2026-08-31T23:59:59Z",
                          diagnosis_code="DXA", notes="one second before")
    set_clock("2026-10-01T00:00:00Z")

    claim_on = submit_claim(policy_on, hospital)
    claim_on = adjudicate_claim(claim_on)
    assert claim_on["status"] == "ADJUDICATED"
    assert claim_on["reimbursement_cents"] == 27000

    claim_before = submit_claim(policy_before, hospital)
    resp = api.adjudicate_claim(
        claim_before["id"], {"expected_claim_version": claim_before["version"]}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_PREEXISTING_CONDITION)
    still = get_success_data(api.get_claim(claim_before["id"], ADJ1))
    assert still["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Queue B: Corner / validations (adjudication gates and intake)
# ---------------------------------------------------------------------------

def test_preexisting_rejection_is_422_after_waiting_passes(api):
    """PRD 3.5: "If the condition — whether found or freshly minted — is
    pre-existing, the entire claim is rejected with ERR_PREEXISTING_CONDITION
    (HTTP 422)."

    Design: Corner/validations/preexisting_rejection_is_422_after_waiting_passes
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    hospital = create_active_hospital()
    policy = create_policy()
    upload_medical_record(policy, hospital, record_type="EXAM",
                          recorded_at="2026-08-01T09:00:00Z",
                          diagnosis_code="DXA", notes="pre-existing signs")
    set_clock("2026-10-01T00:00:00Z")
    claim = submit_claim(policy, hospital)
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, ADJ1
    )
    validate_error(resp, ApiErrorId.ERR_PREEXISTING_CONDITION)
    still = get_success_data(api.get_claim(claim["id"], ADJ1))
    assert still["status"] == "SUBMITTED"
    assert still["version"] == claim["version"]


def test_treatment_line_without_condition_code_rejected(api):
    """PRD 3.5: "A treatment line submitted without its condition code is
    rejected with ERR_CONDITION_CODE_REQUIRED (HTTP 400)."

    Design: Corner/validations/treatment_line_without_condition_code_rejected
    """
    hospital, policy = setup_active_environment()
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "hospital_id": hospital["id"],
            "visit_date": "2026-10-02",
            "claim_type": "INJURY",
            "lines": [
                {"description": "mystery", "amount_cents": 50000, "category": "TREATMENT"}
            ],
        },
        make_hospital_staff_headers(hospital["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONDITION_CODE_REQUIRED)
    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"policy_id": policy["id"]})
    )
    assert len(data) == 0


def test_retroactive_rate_filing_rejected(api):
    """PRD 3.1: "The filing date matters: if the filing_effective_date is
    before the current logical date at the moment of filing, the attempt is
    rejected as retroactive with ERR_FILING_RETROACTIVE (HTTP 422)."

    Design: Corner/validations/retroactive_rate_filing_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_rate_filing(
        {
            "territory_code": "100",
            "state_code": "NY",
            "species": "CAT",
            "base_monthly_premium_cents": 80000,
            "age_band_multipliers": {"0": 1.0},
            "filing_effective_date": "2026-08-01",
            "regulator_reference": "NY-2026-100",
        },
        RATE_ADMIN,
    )
    filing = validate_success(resp, expected_status=201)
    resp = api.file_rate_filing(filing["id"], RATE_ADMIN)
    validate_error(resp, ApiErrorId.ERR_FILING_RETROACTIVE)
    still = get_success_data(api.get_rate_filing(filing["id"], RATE_ADMIN))
    assert still["status"] == "DRAFT"


def test_policy_creation_without_effective_filing_rejected(api):
    """PRD 3.3: "Enrollment is gated on rate availability: there must exist an
    EFFECTIVE filing for the policy's pair of territory_code and species whose
    filing_effective_date is on or before the coverage_start. ... If no such
    filing exists, enrollment is rejected with ERR_RATE_NOT_FILED (HTTP 422)."

    Design: Corner/validations/policy_creation_without_effective_filing_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()  # (941, DOG) only
    resp = api.create_policy(
        create_policy_payload(
            owner_name="No Rate", pet_name="Kit", species="CAT", breed="Siamese",
            pet_date_of_birth="2023-05-01", territory_code="100",
            coverage_start="2026-09-01",
        ),
        TEST_USERS["pet_owner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RATE_NOT_FILED)
    data, meta = validate_paginated(api.list_policies(ADMIN))
    assert len(data) == 0


# ---------------------------------------------------------------------------
# Queue B: Corner / endpoints (line ordering) + consistency_model
# ---------------------------------------------------------------------------

def test_claim_lines_seq_order_preserved(api):
    """PRD 3.5: "The per-condition deductible waterfall then processes the
    eligible lines — again strictly in ascending seq order, which is unique
    per claim so no tie-break is needed."
    PRD 3.5: "a claim's lines are listed in seq order"

    Design: Corner/endpoints/claim_lines_seq_order_preserved
    """
    hospital, policy, claim = setup_adjudicated_claim(lines=[
        {"description": "first", "amount_cents": 30000,
         "category": "TREATMENT", "condition_code": "DXA"},
        {"description": "second", "amount_cents": 10000,
         "category": "TREATMENT", "condition_code": "DXA"},
    ])
    data, meta = validate_paginated(api.list_claim_lines_of_claim(claim["id"], ADJ1))
    assert len(data) == 2
    assert data[0]["seq"] == 1
    assert data[1]["seq"] == 2
    assert data[0]["description"] == "first"
    assert data[1]["description"] == "second"
    assert data[0]["deductible_applied_cents"] == 20000
    assert data[0]["reimbursement_cents"] == 9000
    assert data[1]["deductible_applied_cents"] == 0
    assert data[1]["reimbursement_cents"] == 9000


def test_adjudication_totals_visible_in_same_response(api):
    """PRD 3.5: "Claim totals then fall out: eligible_cents is the sum of the
    lines' eligible_amount_cents, deductible_applied_cents the sum of the
    lines' deductible_applied_cents, reimbursement_cents the sum of the
    per-line rounded reimbursement_cents, total_invoice_cents the sum of all
    lines' amount_cents (excluded lines included), and
    member_responsibility_cents the total_invoice_cents minus the
    reimbursement_cents."
    PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/adjudication_totals_visible_in_same_response
    """
    hospital, policy = setup_active_environment()
    claim = submit_claim(policy, hospital)
    resp = api.adjudicate_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, ADJ1
    )
    adjudicated = validate_success(resp)
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["version"] == claim["version"] + 1
    assert adjudicated["eligible_cents"] == 50000
    assert adjudicated["deductible_applied_cents"] == 20000
    assert adjudicated["reimbursement_cents"] == 27000
    assert adjudicated["member_responsibility_cents"] == 23000
    reread = get_success_data(api.get_claim(claim["id"], ADJ1))
    for field in ("eligible_cents", "deductible_applied_cents",
                  "reimbursement_cents", "member_responsibility_cents",
                  "total_invoice_cents", "status", "version"):
        assert reread[field] == adjudicated[field], (
            f"write-response and read drift on {field}"
        )
