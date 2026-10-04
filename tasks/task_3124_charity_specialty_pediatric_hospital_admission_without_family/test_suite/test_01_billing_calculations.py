"""Billing calculations: provisional vs final claim variants and the
no-family-billing conserved quantities."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_billing_account_invariants,
    cast_vote,
    create_application,
    create_claim_payload,
    decide,
    get_application,
    get_care_plan,
    get_success_data,
    make_billing_headers,
    make_intake_headers,
    make_reviewer_headers,
    open_review,
    set_clock,
    setup_accepted_application,
    setup_accepted_staged_application,
    setup_hospital_with_program,
    setup_submitted_application,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Corner/calculations
# ---------------------------------------------------------------------------

def test_claim_provisional_estimate_exposed_at_creation(api, billing_headers):
    """PRD §3.5: "On creation, the claim's `submitted_amount_cents` is the plain integer sum of its lines' `charge_cents`, and its `estimated_allowed_cents` is computed by the **provisional variant**: each line's charge is multiplied by the estimated rate of 0.62, each per-line product is rounded half-up to whole cents, and the rounded per-line amounts are then summed."

    Design: Corner/calculations/claim_provisional_estimate_exposed_at_creation
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, account = setup_accepted_application(with_insurance=True)

    resp = api.create_claim(
        account["id"],
        create_claim_payload(lines=[{"cpt_code": "99213", "charge_cents": 1000}]),
        billing_headers,
    )
    claim = validate_success(resp, expected_status=201)
    assert claim["submitted_amount_cents"] == 1000
    assert claim["estimated_allowed_cents"] == 620
    assert claim["adjudicated_amount_cents"] is None
    after = validate_success(api.get_billing_account(account["id"], billing_headers))
    assert after["open_claim_cents"] == 1000


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc
# ---------------------------------------------------------------------------

def test_claim_allowed_amount_per_line_vs_on_total_provisional(api, billing_headers):
    """PRD §3.5: "Because the provisional variant rounds per line and the final variant rounds once at the end, the two integers disagree whenever the claim carries two or more lines whose charges do not divide evenly against the two rates."

    Design: Difficulty/dual_variant_calc/claim_allowed_amount_per_line_vs_on_total
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, account = setup_accepted_application(with_insurance=True)

    resp = api.create_claim(
        account["id"],
        create_claim_payload(lines=[
            {"cpt_code": "27447", "charge_cents": 3333},
            {"cpt_code": "27486", "charge_cents": 3333},
        ]),
        billing_headers,
    )
    claim = validate_success(resp, expected_status=201)
    # Per line: round_half_up(3333 * 0.62) = 2066; summed = 4132.
    assert claim["estimated_allowed_cents"] == 4132
    assert claim["submitted_amount_cents"] == 6666


def test_claim_allowed_amount_per_line_vs_on_total_final(api, billing_headers):
    """PRD §3.5: "the system sums all line charges first, multiplies the summed total once by the contract rate of 0.60, and rounds the result half-up to whole cents exactly once, storing it as `adjudicated_amount_cents`"

    Design: Difficulty/dual_variant_calc/claim_allowed_amount_per_line_vs_on_total
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, account = setup_accepted_application(with_insurance=True)

    claim = validate_success(api.create_claim(
        account["id"],
        create_claim_payload(lines=[
            {"cpt_code": "27447", "charge_cents": 3333},
            {"cpt_code": "27486", "charge_cents": 3333},
        ]),
        billing_headers,
    ), expected_status=201)
    adjudicated = validate_success(api.adjudicate_claim(claim["id"], billing_headers))
    # Final variant: round_half_up(6666 * 0.60) = round(3999.6) = 4000.
    assert adjudicated["adjudicated_amount_cents"] == 4000
    assert adjudicated["estimated_allowed_cents"] == 4132
    assert adjudicated["estimated_allowed_cents"] != adjudicated["adjudicated_amount_cents"]

    account_after = validate_success(api.get_billing_account(account["id"], billing_headers))
    assert account_after["insurance_paid_cents"] == 4000
    assert account_after["charity_writeoff_cents"] == 2666
    assert account_after["family_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula
# ---------------------------------------------------------------------------

def test_claim_rounding_order_two_line_divergence(api, billing_headers):
    """PRD §3.5: "each line's charge is multiplied by the estimated rate of 0.62, each per-line product is rounded half-up to whole cents, and the rounded per-line amounts are then summed"

    Design: Difficulty/combinatorial_formula/claim_rounding_order_per_line_then_sum_vs_sum_then_round
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, account = setup_accepted_application(with_insurance=True)

    claim = validate_success(api.create_claim(
        account["id"],
        create_claim_payload(lines=[
            {"cpt_code": "99213", "charge_cents": 101},
            {"cpt_code": "99214", "charge_cents": 202},
            {"cpt_code": "99215", "charge_cents": 305},
        ]),
        billing_headers,
    ), expected_status=201)
    assert claim["submitted_amount_cents"] == 608
    # Per line: round(101*0.62)=63, round(202*0.62)=125, round(305*0.62)=189 -> 377.
    assert claim["estimated_allowed_cents"] == 377


def test_claim_rounding_order_three_line_final_differs(api, billing_headers):
    """PRD §3.5: "the two integers disagree whenever the claim carries two or more lines whose charges do not divide evenly against the two rates"

    Design: Difficulty/combinatorial_formula/claim_rounding_order_per_line_then_sum_vs_sum_then_round
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, account = setup_accepted_application(with_insurance=True)

    claim = validate_success(api.create_claim(
        account["id"],
        create_claim_payload(lines=[
            {"cpt_code": "99213", "charge_cents": 101},
            {"cpt_code": "99214", "charge_cents": 202},
            {"cpt_code": "99215", "charge_cents": 305},
        ]),
        billing_headers,
    ), expected_status=201)
    adjudicated = validate_success(api.adjudicate_claim(claim["id"], billing_headers))
    # Final: round(608 * 0.60) = round(364.8) = 365; provisional was 377.
    assert adjudicated["adjudicated_amount_cents"] == 365

    account_after = validate_success(api.get_billing_account(account["id"], billing_headers))
    assert account_after["charity_writeoff_cents"] == 243
    assert account_after["family_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant
# ---------------------------------------------------------------------------

def test_family_balance_invariant_under_adjudicate(api, billing_headers):
    """PRD §3.5: "Adjudication then settles the account: `open_claim_cents` decreases by `submitted_amount_cents`, `insurance_paid_cents` increases by `adjudicated_amount_cents`, and the uncompensated remainder — `submitted_amount_cents` minus `adjudicated_amount_cents` — is always added to `charity_writeoff_cents`, keeping `family_balance_cents` at 0."

    Design: Difficulty/compensating_invariant/family_balance_invariant_under_adjudicate_and_deny
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, account = setup_accepted_application(with_insurance=True)

    claim = validate_success(api.create_claim(
        account["id"], create_claim_payload(), billing_headers,
    ), expected_status=201)
    validate_success(api.adjudicate_claim(claim["id"], billing_headers))
    after = validate_success(api.get_billing_account(account["id"], billing_headers))
    assert after["total_charged_cents"] == 1000
    assert after["insurance_paid_cents"] == 600
    assert after["charity_writeoff_cents"] == 400
    assert after["open_claim_cents"] == 0
    assert_billing_account_invariants(after)


def test_family_balance_invariant_under_adjudicate_and_deny(api, billing_headers):
    """PRD §3.5: "Denial removes the full `submitted_amount_cents` from `open_claim_cents` and adds that entire amount to `charity_writeoff_cents` — a denied claim is fully absorbed by charity."

    Design: Difficulty/compensating_invariant/family_balance_invariant_under_adjudicate_and_deny
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, account = setup_accepted_application(with_insurance=True)

    claim1 = validate_success(api.create_claim(
        account["id"], create_claim_payload(), billing_headers,
    ), expected_status=201)
    validate_success(api.adjudicate_claim(claim1["id"], billing_headers))
    claim2 = validate_success(api.create_claim(
        account["id"],
        create_claim_payload(service_date="2026-09-03T00:00:00Z",
                             lines=[{"cpt_code": "99214", "charge_cents": 2000}]),
        billing_headers,
    ), expected_status=201)
    validate_success(api.deny_claim(claim2["id"], billing_headers))

    after = validate_success(api.get_billing_account(account["id"], billing_headers))
    assert after["total_charged_cents"] == 3000
    assert after["insurance_paid_cents"] == 600
    assert after["charity_writeoff_cents"] == 2400
    assert after["open_claim_cents"] == 0
    assert_billing_account_invariants(after)


def test_fund_conservation_under_commit_release_cycle(api):
    """PRD §3.9: "At all times the invariant `allocated_cents` plus `available_cents` equals `total_committed_cents` holds."

    Design: Difficulty/compensating_invariant/fund_conservation_under_commit_release_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _, _ = setup_hospital_with_program()
    from test_helpers import create_allocation, create_fund, get_fund
    fund = create_fund(total_committed_cents=100000)
    al1 = create_allocation(fund["id"], hospital["id"], amount_cents=40000)
    al2 = create_allocation(fund["id"], hospital["id"], amount_cents=5000)

    from test_helpers import make_philanthropy_headers
    po = make_philanthropy_headers("po-1")
    validate_success(api.commit_allocation(al1["id"], fund["version"], po))
    mid = get_fund(fund["id"])
    assert mid["allocated_cents"] == 40000
    assert mid["available_cents"] == 60000

    validate_success(api.withdraw_allocation(al2["id"], po))
    still = get_fund(fund["id"])
    # Withdrawal of a PLEDGED allocation leaves fund balances unchanged.
    assert still["allocated_cents"] == 40000
    assert still["available_cents"] == 60000

    validate_success(api.release_allocation(al1["id"], po))
    end = get_fund(fund["id"])
    assert end["allocated_cents"] == 0
    assert end["available_cents"] == 100000
    assert end["allocated_cents"] + end["available_cents"] == end["total_committed_cents"]

    al1_after = validate_success(api.get_allocation(al1["id"], po))
    al2_after = validate_success(api.get_allocation(al2["id"], po))
    assert al1_after["status"] == "RELEASED"
    assert al2_after["status"] == "WITHDRAWN"


def test_fund_conservation_commit_then_release_restores_balances(api):
    """PRD §3.9: "Release subtracts `amount_cents` from `allocated_cents`, adds it back to `available_cents`, and bumps the fund's `version`."

    Design: Difficulty/compensating_invariant/fund_conservation_under_commit_release_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _, _ = setup_hospital_with_program()
    from test_helpers import create_allocation, create_fund, get_fund, make_philanthropy_headers
    fund = create_fund(total_committed_cents=100000)
    allocation = create_allocation(fund["id"], hospital["id"], amount_cents=25000)
    po = make_philanthropy_headers("po-1")

    validate_success(api.commit_allocation(allocation["id"], fund["version"], po))
    committed = get_fund(fund["id"])
    assert committed["allocated_cents"] == 25000
    assert committed["available_cents"] == 75000

    validate_success(api.release_allocation(allocation["id"], po))
    released = get_fund(fund["id"])
    assert released["allocated_cents"] == 0
    assert released["available_cents"] == 100000


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict
# ---------------------------------------------------------------------------

def test_decide_conflict_state_vs_fiscal_capacity(api, reviewer1_headers, reviewer3_headers):
    """PRD §2.8: "More broadly, every request passes through a fixed validation ladder. Authentication context comes first, then role authorization, then path-segment existence, then body foreign-key existence, then state-machine legality (a transition attempted from a state that does not define it is `ERR_INVALID_STATE`, HTTP 409), then the OCC stale-version check where the endpoint declares one, and only then the business rules"

    Design: Difficulty/priority_pair_validation_conflict/decide_conflict_state_vs_fiscal_capacity
    """
    set_clock("2026-09-01T00:00:00Z")
    # Capacity-1 hospital: A1 fills it, then a decide on terminal A1 must
    # answer ERR_INVALID_STATE even though capacity is also exhausted.
    hospital, program, source = setup_hospital_with_program(
        hospital_overrides={"annual_capacity": 1},
    )
    a1 = create_application(source["id"], program["id"], patient_full_name="Kid One")
    open_review(a1["id"])
    cast_vote(a1["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(a1["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")
    decide(a1["id"], decision="ACCEPT", decision_reason="ok", reviewer="rcm-3")

    current = get_application(a1["id"])
    assert current["status"] == "ACCEPTED"
    resp = api.decide_application(
        a1["id"],
        {"decision": "ACCEPT", "decision_reason": "double decide",
         "expected_application_version": current["version"]},
        reviewer3_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_decide_conflict_state_preempts_capacity_error_id(api, reviewer3_headers):
    """PRD §3.3: "An `ACCEPT` additionally requires the hospital's `admissions_ytd` to be strictly below its `annual_capacity` — evaluated on the pre-increment value — otherwise `ERR_HOSPITAL_CAPACITY_REACHED` (HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/decide_conflict_state_vs_fiscal_capacity
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, program, source = setup_hospital_with_program(
        hospital_overrides={"annual_capacity": 1},
    )
    a1 = create_application(source["id"], program["id"], patient_full_name="Kid One")
    open_review(a1["id"])
    cast_vote(a1["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(a1["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")
    decide(a1["id"], decision="ACCEPT", decision_reason="ok", reviewer="rcm-3")

    current = get_application(a1["id"])
    resp = api.decide_application(
        a1["id"],
        {"decision": "ACCEPT", "decision_reason": "double decide",
         "expected_application_version": current["version"]},
        reviewer3_headers,
    )
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert error["error_id"] != ApiErrorId.ERR_HOSPITAL_CAPACITY_REACHED.value
    assert error["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


def test_claim_adjudicate_conflict_state_vs_business_referential(api, billing_headers):
    """PRD §2.8: "then state-machine legality (a transition attempted from a state that does not define it is `ERR_INVALID_STATE`, HTTP 409), then the OCC stale-version check where the endpoint declares one, and only then the business rules"

    Design: Difficulty/priority_pair_validation_conflict/claim_adjudicate_conflict_state_vs_business_referential
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, account = setup_accepted_application(with_insurance=True)

    claim = validate_success(api.create_claim(
        account["id"], create_claim_payload(), billing_headers,
    ), expected_status=201)
    validate_success(api.deny_claim(claim["id"], billing_headers))

    resp = api.adjudicate_claim(claim["id"], billing_headers)
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert error["error_id"] == ApiErrorId.ERR_INVALID_STATE.value

    claim_after = validate_success(api.get_claim(claim["id"], billing_headers))
    assert claim_after["status"] == "DENIED_CLAIM"
    assert claim_after["adjudicated_amount_cents"] is None


def test_claim_adjudicate_terminal_claim_leaves_writeoff_once(api, billing_headers):
    """PRD §3.5: "Denial removes the full `submitted_amount_cents` from `open_claim_cents` and adds that entire amount to `charity_writeoff_cents` — a denied claim is fully absorbed by charity."

    Design: Difficulty/priority_pair_validation_conflict/claim_adjudicate_conflict_state_vs_business_referential
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, account = setup_accepted_application(with_insurance=True)

    claim = validate_success(api.create_claim(
        account["id"], create_claim_payload(), billing_headers,
    ), expected_status=201)
    validate_success(api.deny_claim(claim["id"], billing_headers))
    # The rejected adjudicate must not double-apply the write-off.
    validate_error(
        api.adjudicate_claim(claim["id"], billing_headers),
        ApiErrorId.ERR_INVALID_STATE.value, expected_status=409,
    )
    after = validate_success(api.get_billing_account(account["id"], billing_headers))
    assert after["charity_writeoff_cents"] == 1000
    assert after["family_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Corner/calculations — admissions_ytd year-boundary recompute
# ---------------------------------------------------------------------------

def test_hospital_admissions_ytd_counts_only_accepted_in_current_year(api, admin_headers):
    """PRD §2.4: "And when the clock crosses a calendar-year boundary (the first clock touch at or after January 1 00:00:00Z of a new year), every hospital's `admissions_ytd` is recomputed from the accepted-application set for the new current year — a true recomputation rather than a blind zeroing, so the counter stays consistent if acceptances are later inspected."

    Design: Corner/calculations/hospital_admissions_ytd_counts_only_accepted_in_current_year
    """
    set_clock("2026-12-31T00:00:00Z")
    hospital, program, source = setup_hospital_with_program()

    a1 = create_application(source["id"], program["id"], patient_full_name="Kid Accept")
    open_review(a1["id"])
    cast_vote(a1["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(a1["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")
    decide(a1["id"], decision="ACCEPT", decision_reason="ok", reviewer="rcm-3")

    a2 = create_application(source["id"], program["id"], patient_full_name="Kid Deny")
    open_review(a2["id"])
    cast_vote(a2["id"], vote="DENY", vote_weight=2, reviewer="rcm-1")
    decide(a2["id"], decision="DENY", decision_reason="no", reviewer="rcm-2")

    end_2026 = validate_success(api.get_hospital(hospital["id"], admin_headers))
    # Only the ACCEPTED application counts, not the DENIED one.
    assert end_2026["admissions_ytd"] == 1

    set_clock("2027-01-01T00:00:00Z")
    start_2027 = validate_success(api.get_hospital(hospital["id"], admin_headers))
    assert start_2027["admissions_ytd"] == 0
