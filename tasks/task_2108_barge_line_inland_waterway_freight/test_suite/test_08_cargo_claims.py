"""Cargo claims: the review cycle, the two settlement variants, the credit
cascade and the segregation-of-duties bar."""
from test_helpers import (
    ADJUSTER_APPROVER_USER_ID,
    ADJUSTER_ASSESSOR_USER_ID,
    ApiErrorId,
    approve_claim,
    assess_claim,
    create_cargo_claim_payload,
    create_contract,
    deny_claim,
    file_claim,
    make_claims_adjuster_headers,
    read_assignment,
    read_claim,
    read_contract,
    read_shipper,
    set_clock,
    setup_assessed_claim,
    setup_claim_under_review,
    setup_grain_movement,
    validate_error,
    validate_paginated,
    validate_success,
)

ASSESSOR = make_claims_adjuster_headers(ADJUSTER_ASSESSOR_USER_ID)
APPROVER = make_claims_adjuster_headers(ADJUSTER_APPROVER_USER_ID)


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / the tolerance read two ways
# ---------------------------------------------------------------------------
def test_assessment_reads_the_tolerance_as_a_deductible(api):
    """PRD §3.9: "The trade tolerance, `tolerance_tons`, is the assignment's
    `loaded_tons` multiplied by one half of one percent, rounded half up to
    three decimal places."
    PRD §3.9: "Under the **deductible** reading, the tolerance is subtracted
    from the loss: the compensable tonnage is `shortage_tons` minus
    `tolerance_tons`, floored at zero, and `settlement_deductible_cents` is the
    smaller of the claimant's `claimed_amount_cents` and that compensable
    tonnage multiplied by the unit value, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/claim_settlement_deductible_versus_franchise_on_cargo_claim
    """
    movement = setup_claim_under_review(loads=(1700,))
    assessed = assess_claim(movement["claim_id"])
    assert assessed["status"] == "ASSESSED"
    assert float(assessed["shortage_tons"]) == 13.0, (
        f"1700 loaded minus 1687 outturn, got {assessed['shortage_tons']}")
    assert float(assessed["tolerance_tons"]) == 8.5, (
        f"1700 tons at one half of one percent, got {assessed['tolerance_tons']}")
    assert assessed["settlement_deductible_cents"] == 99_000, (
        f"(13 - 8.5) tons at 22000 cents, got {assessed['settlement_deductible_cents']}")


def test_assessment_reads_the_same_tolerance_as_a_franchise(api):
    """PRD §3.9: "Under the **franchise** reading, the tolerance is an
    all-or-nothing trigger: the compensable tonnage is the whole of
    `shortage_tons` when `shortage_tons` is strictly greater than
    `tolerance_tons`, and zero otherwise, and `settlement_franchise_cents` is
    likewise the smaller of `claimed_amount_cents` and that compensable tonnage
    multiplied by the unit value, rounded half up to whole cents."
    PRD §3.9: "Assessment also writes `assessed_by_user_id` from the acting
    `X-User-ID` and increments the claim's `version`; `settlement_cents` remains
    0, because nothing has been decided yet."

    Design: Difficulty/dual_variant_calc/claim_settlement_deductible_versus_franchise_on_cargo_claim
    """
    movement = setup_claim_under_review(loads=(1700,))
    assessed = assess_claim(movement["claim_id"])
    assert assessed["settlement_franchise_cents"] == 286_000, (
        f"the whole 13-ton loss at 22000 cents, "
        f"got {assessed['settlement_franchise_cents']}")
    assert assessed["settlement_cents"] == 0, (
        "the variant is selected only at approval")
    assert assessed["assessed_by_user_id"] == ADJUSTER_ASSESSOR_USER_ID


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / the review cycle
# ---------------------------------------------------------------------------
def test_review_cycle_closes_a_revision_round_on_every_return(api):
    """PRD §3.9: "From there the adjuster may suspend the file pending more
    information, recording an `info_request_note` and moving the claim
    `UNDER_REVIEW → INFO_REQUESTED`; that suspension is permitted only while the
    claim's `revision_round` is below 2, and an attempt beyond that is refused
    with `ERR_CLAIM_REVISION_LIMIT`."
    PRD §3.9: "When the claimant answers, the adjuster records a `response_note`
    and moves the claim `INFO_REQUESTED → UNDER_REVIEW`, which increments
    `revision_round` by one and closes that round."

    Design: Difficulty/non_linear_state_machine/cargo_claim_review_cycle_repeats_until_revision_limit_blocks_it
    """
    movement = setup_claim_under_review(loads=(1700,))
    claim_id = movement["claim_id"]
    assert read_claim(claim_id)["revision_round"] == 0

    suspended = validate_success(api.request_claim_info(
        claim_id, {"info_request_note": "Send the dock scale ticket."}, ASSESSOR))
    assert suspended["status"] == "INFO_REQUESTED"
    resumed = validate_success(api.resume_claim_review(
        claim_id, {"response_note": "Scale ticket attached."}, ASSESSOR))
    assert resumed["status"] == "UNDER_REVIEW"
    assert resumed["revision_round"] == 1

    validate_success(api.request_claim_info(
        claim_id, {"info_request_note": "Send the draft survey too."}, ASSESSOR))
    resumed = validate_success(api.resume_claim_review(
        claim_id, {"response_note": "Draft survey attached."}, ASSESSOR))
    assert resumed["status"] == "UNDER_REVIEW"
    assert resumed["revision_round"] == 2


def test_the_third_request_for_information_is_refused(api):
    """PRD §3.9: "From there the adjuster may suspend the file pending more
    information, recording an `info_request_note` and moving the claim
    `UNDER_REVIEW → INFO_REQUESTED`; that suspension is permitted only while the
    claim's `revision_round` is below 2, and an attempt beyond that is refused
    with `ERR_CLAIM_REVISION_LIMIT`."
    PRD §3.9: "The cycle is genuinely a cycle, and it terminates only because
    the third request for information is refused."

    Design: Difficulty/non_linear_state_machine/cargo_claim_review_cycle_repeats_until_revision_limit_blocks_it
    """
    movement = setup_claim_under_review(loads=(1700,))
    claim_id = movement["claim_id"]
    for note, answer in (("First question.", "First answer."),
                         ("Second question.", "Second answer.")):
        validate_success(api.request_claim_info(
            claim_id, {"info_request_note": note}, ASSESSOR))
        validate_success(api.resume_claim_review(
            claim_id, {"response_note": answer}, ASSESSOR))

    validate_error(api.request_claim_info(
        claim_id, {"info_request_note": "One more question."}, ASSESSOR),
        ApiErrorId.ERR_CLAIM_REVISION_LIMIT.value)

    stored = read_claim(claim_id)
    assert stored["status"] == "UNDER_REVIEW", "the refused call does not advance the cycle"
    assert stored["revision_round"] == 2


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / approval credits the bill and the ledger
# ---------------------------------------------------------------------------
def _assessed_franchise_claim_on_a_credit_held_shipper():
    return setup_assessed_claim(
        loads=(1700,), invoiced=True,
        ref_kwargs={"credit_limit_cents": 1_100_000},
        contract_kwargs={"claim_settlement_basis": "FRANCHISE"})


def test_approval_selects_the_franchise_variant_and_credits_the_contract(api):
    """PRD §3.9: "Hop one selects the money: `settlement_cents` is set to
    `settlement_franchise_cents` when the contract's `claim_settlement_basis` is
    `FRANCHISE`, and to `settlement_deductible_cents` otherwise, and
    `approved_by_user_id` is written from the acting `X-User-ID`."
    PRD §3.9: "Hop two credits the bill: the named contract adds that
    `settlement_cents` to its `claim_credit_cents`, recomputes `total_cents` as
    `subtotal_cents` minus `volume_rebate_cents` minus the new
    `claim_credit_cents` floored at zero, and moves its billing axis `INVOICED →
    ADJUSTED`."

    Design: Difficulty/transitive_cascade/claim_approval_credit_cascades_through_contract_to_shipper_credit_posture
    """
    movement = _assessed_franchise_claim_on_a_credit_held_shipper()
    before = read_shipper(movement["shipper_id"])
    assert before["outstanding_balance_cents"] == 1_307_936
    assert before["status"] == "CREDIT_HOLD"

    approved = approve_claim(movement["claim_id"])
    assert approved["status"] == "APPROVED"
    assert approved["settlement_cents"] == 286_000, (
        f"the FRANCHISE basis selects the franchise figure, "
        f"got {approved['settlement_cents']}")
    assert approved["approved_by_user_id"] == ADJUSTER_APPROVER_USER_ID

    contract = read_contract(movement["contract_id"])
    assert contract["claim_credit_cents"] == 286_000
    assert contract["billing_status"] == "ADJUSTED"
    assert contract["subtotal_cents"] == 1_327_854, "the subtotal stays frozen"
    assert contract["volume_rebate_cents"] == 19_918
    assert contract["total_cents"] == 1_021_936


def test_approval_lowers_the_ledger_and_releases_the_credit_hold(api):
    """PRD §3.9: "Hop three moves the ledger: the contract's shipper has its
    `outstanding_balance_cents` decreased by the same `settlement_cents`. Hop
    four releases the customer: that shipper returns from `CREDIT_HOLD` to
    `ACTIVE` when its `outstanding_balance_cents` now stands at or below its
    `credit_limit_cents`."
    PRD §3.9: "Separately from that chain, the named barge assignment moves its
    `discharge_status` from `COMPLETED` to `DISPUTED`, which is why a disputed
    barge still permits its tow to break up."

    Design: Difficulty/transitive_cascade/claim_approval_credit_cascades_through_contract_to_shipper_credit_posture
    """
    movement = _assessed_franchise_claim_on_a_credit_held_shipper()
    approve_claim(movement["claim_id"])

    shipper = read_shipper(movement["shipper_id"])
    assert shipper["outstanding_balance_cents"] == 1_021_936, (
        f"1307936 less the 286000 settlement, "
        f"got {shipper['outstanding_balance_cents']}")
    assert shipper["status"] == "ACTIVE", (
        "the balance now sits at or below the 1100000-cent limit")
    assert shipper["open_claim_count"] == 0

    assignment = read_assignment(movement["assignments"][0]["id"])
    assert assignment["discharge_status"] == "DISPUTED"


# ---------------------------------------------------------------------------
# Queue B — the settlement cap, the intake guards and the state gate
# ---------------------------------------------------------------------------
def test_both_settlement_variants_are_capped_at_the_claimed_amount(api):
    """PRD §3.9: "Under the **deductible** reading, the tolerance is subtracted
    from the loss: the compensable tonnage is `shortage_tons` minus
    `tolerance_tons`, floored at zero, and `settlement_deductible_cents` is the
    smaller of the claimant's `claimed_amount_cents` and that compensable
    tonnage multiplied by the unit value, rounded half up to whole cents."
    PRD §3.9: "Under the **franchise** reading, the tolerance is an
    all-or-nothing trigger: the compensable tonnage is the whole of
    `shortage_tons` when `shortage_tons` is strictly greater than
    `tolerance_tons`, and zero otherwise, and `settlement_franchise_cents` is
    likewise the smaller of `claimed_amount_cents` and that compensable tonnage
    multiplied by the unit value, rounded half up to whole cents."

    Design: Corner/calculations/claim_settlement_capped_at_the_claimed_amount
    """
    movement = setup_claim_under_review(
        loads=(1700,), claim_kwargs={"claimed_amount_cents": 50_000})
    assessed = assess_claim(movement["claim_id"])
    assert float(assessed["shortage_tons"]) == 13.0
    assert float(assessed["tolerance_tons"]) == 8.5
    assert assessed["settlement_deductible_cents"] == 50_000, (
        "the 99000-cent deductible figure is capped down to the claimed amount")
    assert assessed["settlement_franchise_cents"] == 50_000, (
        "the 286000-cent franchise figure is capped down to the claimed amount")
    assert read_shipper(movement["shipper_id"])["open_claim_count"] == 1


def test_claim_intake_guards_reject_mismatch_shortfall_duplicate_and_late_filing(api):
    """PRD §3.9: "Four guards stand at filing, in ladder order. The claim must
    be filed within 30 days: if the logical clock stands more than 30 days after
    the named assignment's `unload_finished_at`, the filing is refused with
    `ERR_CLAIM_WINDOW_EXPIRED`. No claim that is neither `WITHDRAWN` nor
    `DENIED` may already exist for that same `barge_assignment_id`, a repeat
    being refused with `ERR_CLAIM_ALREADY_FILED`; note that a withdrawn or
    denied claim leaves the barge open for a fresh one. The named assignment's
    own `freight_contract_id` must equal the claim's, a mismatch being refused
    with `ERR_ASSIGNMENT_CONTRACT_MISMATCH`. And for a `SHORTAGE` claim
    specifically, `claimed_tons` may not exceed the outturn shortfall — the
    assignment's `loaded_tons` minus its `discharged_tons` — and the assignment
    must have reached `discharge_status` `COMPLETED` or `DISPUTED`; either
    failure is refused with `ERR_SHORTAGE_NOT_SUPPORTED`."

    Design: Corner/validations/cargo_claim_intake_guards_reject_mismatch_shortfall_duplicate_and_late_filing
    """
    movement = setup_grain_movement(loads=(1700,), stage="DISCHARGED")
    other_contract = create_contract(
        movement["shipper_id"], movement["commodity_id"], contracted_tons=900)
    assignment_id = movement["assignments"][0]["id"]
    set_clock("2026-08-22T00:00:00Z")

    validate_error(api.create_cargo_claim(
        create_cargo_claim_payload(other_contract["id"], assignment_id),
        ASSESSOR),
        ApiErrorId.ERR_ASSIGNMENT_CONTRACT_MISMATCH.value)

    validate_error(api.create_cargo_claim(
        create_cargo_claim_payload(movement["contract_id"], assignment_id,
                                   claimed_tons=20),
        ASSESSOR),
        ApiErrorId.ERR_SHORTAGE_NOT_SUPPORTED.value)

    filed = validate_success(api.create_cargo_claim(
        create_cargo_claim_payload(movement["contract_id"], assignment_id),
        ASSESSOR), 201)
    assert filed["status"] == "SUBMITTED"
    assert filed["revision_round"] == 0

    validate_error(api.create_cargo_claim(
        create_cargo_claim_payload(movement["contract_id"], assignment_id,
                                   claimed_tons=5, claimed_amount_cents=100_000),
        ASSESSOR),
        ApiErrorId.ERR_CLAIM_ALREADY_FILED.value)

    set_clock("2026-09-25T00:00:00Z")
    validate_error(api.create_cargo_claim(
        create_cargo_claim_payload(movement["contract_id"], assignment_id,
                                   claim_type="DAMAGE", claimed_tons=2,
                                   claimed_amount_cents=40_000),
        ASSESSOR),
        ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED.value)

    assert read_shipper(movement["shipper_id"])["open_claim_count"] == 1
    _rows, meta = validate_paginated(api.list_cargo_claims(
        ASSESSOR, params={"barge_assignment_id": assignment_id}))
    assert meta["total_count"] == 1


def test_assessing_a_submitted_claim_is_refused_and_withdrawal_still_works(api):
    """PRD §3.9: "**Assessment** moves the claim `UNDER_REVIEW → ASSESSED` and
    computes, in one pass, both settlement variants — because at assessment time
    the adjuster does not decide which one is paid."
    PRD §3.9: "Any of these called from the wrong status is refused with
    `ERR_CLAIM_INVALID_STATE`."
    PRD §3.9: "**Withdrawal** is available to the claimant's side while the
    claim stands in `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED`, and all
    three branches behave identically: the claim moves to the terminal
    `WITHDRAWN`, the shipper's `open_claim_count` decrements by one, and the
    claim's `version` increments."

    Design: Corner/errors/claim_assess_from_submitted_returns_claim_invalid_state
    """
    movement = setup_grain_movement(loads=(1700,), stage="DISCHARGED")
    set_clock("2026-08-22T00:00:00Z")
    claim = file_claim(movement["contract_id"], movement["assignments"][0]["id"])

    validate_error(api.assess_cargo_claim(claim["id"], ASSESSOR),
                   ApiErrorId.ERR_CLAIM_INVALID_STATE.value)
    stored = read_claim(claim["id"])
    assert stored["status"] == "SUBMITTED", "the refused assessment moved nothing"
    assert stored.get("assessed_by_user_id") is None, (
        "the assessor identity is written only by a successful assessment")

    withdrawn = validate_success(api.withdraw_cargo_claim(claim["id"], ASSESSOR))
    assert withdrawn["status"] == "WITHDRAWN"
    assert read_shipper(movement["shipper_id"])["open_claim_count"] == 0


def test_the_assessor_may_neither_approve_nor_deny_its_own_assessment(api):
    """PRD §3.9: "**Approval** is where money moves, and it may not be performed
    by the operator who assessed the claim — an attempt by the same `X-User-ID`
    recorded in `assessed_by_user_id` is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "**Denial** is the mirror image and carries the same
    segregation-of-duties bar: the operator recorded in `assessed_by_user_id`
    may not deny either."
    PRD §3.9: "The claim must stand in `ASSESSED`; denial records the supplied
    `denial_reason`, moves the claim to the terminal `DENIED`, leaves
    `settlement_cents` at 0, and leaves the contract's billing entirely
    untouched — no credit, no `ADJUSTED`, no ledger movement."

    Design: Corner/rbac/claim_assessor_cannot_approve_or_deny_its_own_assessment
    """
    movement = setup_assessed_claim(loads=(1700,), invoiced=True)
    claim_id = movement["claim_id"]

    validate_error(api.approve_cargo_claim(claim_id, ASSESSOR),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    validate_error(api.deny_cargo_claim(
        claim_id, {"denial_reason": "Scale ticket unreliable."}, ASSESSOR),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    stored = read_claim(claim_id)
    assert stored["status"] == "ASSESSED", "both refusals left the claim standing"
    assert stored["settlement_cents"] == 0

    denied = deny_claim(claim_id, denial_reason="Scale ticket unreliable.")
    assert denied["status"] == "DENIED"
    assert denied["settlement_cents"] == 0

    contract = read_contract(movement["contract_id"])
    assert contract["billing_status"] == "INVOICED", "a denial never credits the bill"
    assert contract["claim_credit_cents"] == 0
    assert contract["total_cents"] == 1_307_936

    shipper = read_shipper(movement["shipper_id"])
    assert shipper["outstanding_balance_cents"] == 1_307_936
    assert shipper["open_claim_count"] == 0
    assert read_assignment(movement["assignments"][0]["id"])["discharge_status"] \
        == "COMPLETED", "a denial never disputes the outturn"
