"""Incentive programs and stipend money flow: computed budget, eligibility
geography, the pinned proration/multiplier/cap evaluation order, non-encumbrance
at proposal time, and the compensating budget invariant."""
from datetime import datetime

from test_helpers import (
    INCENTIVE_ADMIN,
    STANDARD_COMPLETION_CLOCK,
    ApiErrorId,
    CertificationStatus,
    ProgramStatus,
    StipendStatus,
    assert_incentive_program,
    assert_program_budget_invariant,
    create_active_assessors,
    create_assessment_center,
    create_certified_scenario,
    create_default_benchmark,
    create_eligible_candidate,
    create_incentive_program_payload,
    create_open_cycle,
    create_portfolio_submission_in_state,
    create_proposed_stipend_scenario,
    get_certification_for,
    get_success_data,
    score_assessment_component,
    score_portfolio_with_agreeing_reads,
    set_logical_clock,
    STANDARD_WORK_CLOCK,
    stipend_transition_payload,
    validate_created,
    validate_error,
    validate_paginated,
    validate_success,
)

EARLY_BIRD_DEADLINE = "2027-12-31T00:00:00Z"
SECOND_SLOT_START = "2027-01-21T14:00:00Z"
SECOND_COMPLETION_CLOCK = "2027-01-21T15:00:00Z"


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _program_stipends(api, program_id: str) -> list:
    return get_success_data(api.list_program_stipends(program_id, INCENTIVE_ADMIN))


def test_program_create_computed_budget_remaining_equals_total(api):
    """PRD §3.8: "The program's `budget_remaining_cents` is derived, never stored
    by hand: it equals `budget_total_cents` minus the summed `amount_cents` of its
    stipends in `APPROVED` or `PAID` status — `PROPOSED` stipends encumber
    nothing."
    PRD §3.8: "An `IncentiveAdministrator` creates each program with a `name`, the
    two-letter `sponsor_state`, an optional `sponsor_district_code`, a
    `budget_total_cents` of at least 0, a `base_stipend_cents`, and optionally an
    `early_bird_multiplier` — defaulting to 1.10".
    PRD §3.8: "A program is `OPEN` whenever its remaining budget is positive and
    `EXHAUSTED` exactly when the remaining budget reaches 0".

    With no stipends yet, remaining equals total; the multiplier default applies.

    Design: Corner/entities/program_create_computed_budget_remaining_equals_total
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    program = validate_created(
        api.create_incentive_program(
            create_incentive_program_payload(
                budget_total_cents=500000,
                base_stipend_cents=300000,
                early_bird_deadline=EARLY_BIRD_DEADLINE,
            ),
            INCENTIVE_ADMIN,
        )
    )

    assert_incentive_program(program)
    assert program["budget_total_cents"] == 500000
    assert program["budget_remaining_cents"] == 500000
    assert program["early_bird_multiplier"] == 1.10
    assert program["status"] == ProgramStatus.OPEN.value


def test_stipend_district_mismatch_skips_auto_proposal(api):
    """PRD §3.8: "Eligibility geography works two ways: a program with a non-null
    `sponsor_district_code` is district-specific and only candidates whose
    `district_code` matches it qualify, while a program with a null
    `sponsor_district_code` is statewide and requires the candidate's
    `license_state` to equal `sponsor_state`."
    PRD §3.8: "The moment a certification becomes `CERTIFIED`, stipend
    auto-proposal runs: for every `OPEN` program whose eligibility geography
    matches the candidate and whose `budget_remaining_cents` is above 0, the
    system creates a stipend in `PROPOSED` keyed by `program_id` and
    `certification_id`."

    The candidate is license_state NM / district D-100: the D-200 district
    program is skipped, the statewide NM program proposes exactly one stipend.

    Design: Corner/calculations/stipend_district_mismatch_skips_auto_proposal
    """
    district_payload = create_incentive_program_payload(
        sponsor_district_code="D-200",
        budget_total_cents=500000,
        base_stipend_cents=300000,
        early_bird_multiplier=1.10,
        early_bird_deadline=EARLY_BIRD_DEADLINE,
    )
    statewide_payload = create_incentive_program_payload(
        budget_total_cents=500000,
        base_stipend_cents=300000,
        early_bird_multiplier=1.10,
        early_bird_deadline=EARLY_BIRD_DEADLINE,
    )
    scenario = create_certified_scenario(
        programs=[district_payload, statewide_payload]
    )
    certification = scenario["certification"]
    assert certification["status"] == CertificationStatus.CERTIFIED.value
    prog_dist, prog_state = scenario["programs"]

    cert_stipends = get_success_data(
        api.list_certification_stipends(certification["id"], INCENTIVE_ADMIN)
    )
    assert len(cert_stipends) == 1
    row = cert_stipends[0]
    assert row["program_id"] == prog_state["id"]
    assert row["amount_cents"] == 330000
    assert row["status"] == StipendStatus.PROPOSED.value

    _rows_dist, meta_dist = validate_paginated(
        api.list_program_stipends(prog_dist["id"], INCENTIVE_ADMIN)
    )
    assert meta_dist["total_count"] == 0
    _rows_state, meta_state = validate_paginated(
        api.list_program_stipends(prog_state["id"], INCENTIVE_ADMIN)
    )
    assert meta_state["total_count"] == 1


def test_stipend_approval_budget_exhausted_and_revoked_terminal(api):
    """PRD §3.8: "Approving a `PROPOSED` stipend requires the program's
    `budget_remaining_cents` to cover the stipend's `amount_cents`; a shortfall —
    including the zero-remaining case of an `EXHAUSTED` program, which this single
    gate already covers — is `ERR_PROGRAM_BUDGET_EXHAUSTED` (HTTP 422). Approval
    debits `budget_remaining_cents` by `amount_cents`, and a debit landing exactly
    on 0 flips the program to `EXHAUSTED`. From `APPROVED`, the stipend moves to
    `PAID` when the money goes out. Revocation is possible from either `PROPOSED`
    or `APPROVED`: revoking a `PROPOSED` stipend touches no budget because it
    never encumbered any, while revoking an `APPROVED` stipend credits
    `amount_cents` back to `budget_remaining_cents` — and if the program sat
    `EXHAUSTED`, the credit reopens it to `OPEN`. The compensating invariant holds
    across every debit and credit: `budget_remaining_cents` plus the summed
    `amount_cents` of the program's `APPROVED` and `PAID` stipends always equals
    `budget_total_cents`. Any transition request outside these declared moves —
    from `PAID`, from `REVOKED`, or skipping states — is
    `ERR_STIPEND_NOT_TRANSITIONABLE` (HTTP 409). `PAID` and `REVOKED` are terminal
    for a stipend."

    Two certifications each auto-propose 330000 against one 400000 program; the
    proposals do not encumber, the first approval debits, the second approval
    fails the fiscal gate, the revocation restores, the revoked row is terminal,
    and the second stipend then rides through APPROVED -> PAID.

    Design: Corner/validations/stipend_approval_budget_exhausted_and_revoked_terminal
    """
    cycle = create_open_cycle()
    program = validate_created(
        api.create_incentive_program(
            create_incentive_program_payload(
                budget_total_cents=400000,
                base_stipend_cents=300000,
                early_bird_multiplier=1.10,
                early_bird_deadline=EARLY_BIRD_DEADLINE,
            ),
            INCENTIVE_ADMIN,
        )
    )
    benchmark = create_default_benchmark()
    assessors = create_active_assessors(benchmark["id"], count=2)
    center = create_assessment_center()

    def _certify(candidate, slot_start, completion_clock):
        score_assessment_component(
            cycle["id"], candidate, center["id"],
            earned_score=3.00, slot_start_at=slot_start,
            completion_clock=completion_clock,
        )
        for component_code, score in (("P1", 2.50), ("P2", 1.50), ("P3", 2.00)):
            submission = create_portfolio_submission_in_state(
                cycle["id"], candidate, component_code, state="SCORING"
            )
            score_portfolio_with_agreeing_reads(
                submission["id"], assessors[0], assessors[1], score
            )
        return get_certification_for(candidate["id"], cycle["id"])

    cand_a = create_eligible_candidate()
    cert_a = _certify(cand_a, "2027-01-20T14:00:00Z", STANDARD_COMPLETION_CLOCK)
    cand_b = create_eligible_candidate()
    cert_b = _certify(cand_b, SECOND_SLOT_START, SECOND_COMPLETION_CLOCK)
    assert cert_a["status"] == CertificationStatus.CERTIFIED.value
    assert cert_b["status"] == CertificationStatus.CERTIFIED.value

    stip_a = get_success_data(
        api.list_certification_stipends(cert_a["id"], INCENTIVE_ADMIN)
    )[0]
    stip_b = get_success_data(
        api.list_certification_stipends(cert_b["id"], INCENTIVE_ADMIN)
    )[0]
    assert stip_a["amount_cents"] == 330000
    assert stip_b["amount_cents"] == 330000
    assert stip_a["status"] == StipendStatus.PROPOSED.value
    assert stip_b["status"] == StipendStatus.PROPOSED.value

    program = validate_success(api.get_incentive_program(program["id"], INCENTIVE_ADMIN))
    assert program["budget_remaining_cents"] == 400000
    assert_program_budget_invariant(program, _program_stipends(api, program["id"]))

    approved_a = validate_success(
        api.transition_stipend(stip_a["id"], stipend_transition_payload("APPROVED"), INCENTIVE_ADMIN)
    )
    assert approved_a["status"] == StipendStatus.APPROVED.value
    program = validate_success(api.get_incentive_program(program["id"], INCENTIVE_ADMIN))
    assert program["budget_remaining_cents"] == 70000
    assert_program_budget_invariant(program, _program_stipends(api, program["id"]))

    exhausted = api.transition_stipend(
        stip_b["id"], stipend_transition_payload("APPROVED"), INCENTIVE_ADMIN
    )
    validate_error(exhausted, ApiErrorId.ERR_PROGRAM_BUDGET_EXHAUSTED)
    reread_b = get_success_data(
        api.list_certification_stipends(cert_b["id"], INCENTIVE_ADMIN)
    )[0]
    assert reread_b["status"] == StipendStatus.PROPOSED.value

    revoked_a = validate_success(
        api.transition_stipend(stip_a["id"], stipend_transition_payload("REVOKED"), INCENTIVE_ADMIN)
    )
    assert revoked_a["status"] == StipendStatus.REVOKED.value
    program = validate_success(api.get_incentive_program(program["id"], INCENTIVE_ADMIN))
    assert program["budget_remaining_cents"] == 400000
    assert program["status"] == ProgramStatus.OPEN.value
    assert_program_budget_invariant(program, _program_stipends(api, program["id"]))

    terminal = api.transition_stipend(
        stip_a["id"], stipend_transition_payload("PAID"), INCENTIVE_ADMIN
    )
    validate_error(terminal, ApiErrorId.ERR_STIPEND_NOT_TRANSITIONABLE)

    approved_b = validate_success(
        api.transition_stipend(stip_b["id"], stipend_transition_payload("APPROVED"), INCENTIVE_ADMIN)
    )
    assert approved_b["status"] == StipendStatus.APPROVED.value
    paid_b = validate_success(
        api.transition_stipend(stip_b["id"], stipend_transition_payload("PAID"), INCENTIVE_ADMIN)
    )
    assert paid_b["status"] == StipendStatus.PAID.value
    program = validate_success(api.get_incentive_program(program["id"], INCENTIVE_ADMIN))
    assert program["budget_remaining_cents"] == 70000
    assert_program_budget_invariant(program, _program_stipends(api, program["id"]))

    paid_terminal = api.transition_stipend(
        stip_b["id"], stipend_transition_payload("REVOKED"), INCENTIVE_ADMIN
    )
    validate_error(paid_terminal, ApiErrorId.ERR_STIPEND_NOT_TRANSITIONABLE)
    program = validate_success(api.get_incentive_program(program["id"], INCENTIVE_ADMIN))
    assert program["budget_remaining_cents"] == 70000


def test_stipend_proration_multiplier_budget_cap(api):
    """PRD §3.8: "First the multiplier: `early_bird_multiplier` applies when the
    certification's `certified_at` is at or before the program's
    `early_bird_deadline` — equality earns the multiplier — and 1.0 applies
    otherwise, including whenever the deadline is null. Second the tentative
    amount: `base_stipend_cents` multiplied by the candidate's `fte_fraction`
    multiplied by the multiplier, rounded half up to integer cents. Third the cap:
    the tentative amount is clipped down to the program's **current**
    `budget_remaining_cents`, so the proposal never exceeds what the program could
    still pay. Worked example: a 300000-cent base at 0.8 FTE with the 1.10 early
    multiplier tentatives to 264000 cents, and a program with 200000 cents
    remaining clips the proposal to 200000 cents; the same base at 1.0 FTE
    tentatives to 330000 cents."

    The PRD's own worked example is replayed: tentative 264000 capped to 200000.

    Design: Difficulty/combinatorial_formula/stipend_amount_proration_multiplier_budget_cap
    """
    scenario = create_certified_scenario(
        candidate_overrides={"fte_fraction": 0.8},
        programs=[
            create_incentive_program_payload(
                budget_total_cents=200000,
                base_stipend_cents=300000,
                early_bird_multiplier=1.10,
                early_bird_deadline=EARLY_BIRD_DEADLINE,
            )
        ],
    )
    certification = scenario["certification"]
    assert certification["status"] == CertificationStatus.CERTIFIED.value
    assert _parse_iso(certification["certified_at"]) == _parse_iso(
        STANDARD_COMPLETION_CLOCK
    )

    stipends = get_success_data(
        api.list_certification_stipends(certification["id"], INCENTIVE_ADMIN)
    )
    assert len(stipends) == 1
    stipend = stipends[0]
    assert stipend["amount_cents"] == 200000, (
        "tentative round_half_up(300000 x 0.8 x 1.10) == 264000 clipped to the "
        "200000 remaining budget"
    )
    assert stipend["status"] == StipendStatus.PROPOSED.value


def test_stipend_proposal_does_not_encumber_budget(api):
    """PRD §3.8: "No money moves at proposal time — the debit happens only at
    approval."
    PRD §3.8: "The compensating invariant holds across every debit and credit:
    `budget_remaining_cents` plus the summed `amount_cents` of the program's
    `APPROVED` and `PAID` stipends always equals `budget_total_cents`."

    After auto-proposal of the capped 200000 stipend, the program still reads its
    full 200000 remaining and stays OPEN.

    Design: Difficulty/combinatorial_formula/stipend_amount_proration_multiplier_budget_cap
    """
    scenario = create_certified_scenario(
        candidate_overrides={"fte_fraction": 0.8},
        programs=[
            create_incentive_program_payload(
                budget_total_cents=200000,
                base_stipend_cents=300000,
                early_bird_multiplier=1.10,
                early_bird_deadline=EARLY_BIRD_DEADLINE,
            )
        ],
    )
    certification = scenario["certification"]
    program = scenario["programs"][0]

    stipends = get_success_data(
        api.list_certification_stipends(certification["id"], INCENTIVE_ADMIN)
    )
    assert len(stipends) == 1
    assert stipends[0]["status"] == StipendStatus.PROPOSED.value

    reread = validate_success(api.get_incentive_program(program["id"], INCENTIVE_ADMIN))
    assert reread["budget_remaining_cents"] == 200000
    assert reread["status"] == ProgramStatus.OPEN.value
    assert_program_budget_invariant(reread, _program_stipends(api, program["id"]))


def test_program_budget_conserved_on_approve(api):
    """PRD §3.8: "Approval debits `budget_remaining_cents` by `amount_cents`, and
    a debit landing exactly on 0 flips the program to `EXHAUSTED`."
    PRD §3.8: "The compensating invariant holds across every debit and credit:
    `budget_remaining_cents` plus the summed `amount_cents` of the program's
    `APPROVED` and `PAID` stipends always equals `budget_total_cents`."

    The 330000 stipend exactly drains the 330000 program: 0 + 330000 == 330000.

    Design: Difficulty/compensating_invariant/program_budget_conserved_across_approve_and_revoke
    """
    scenario = create_proposed_stipend_scenario(
        program_overrides={
            "budget_total_cents": 330000,
            "base_stipend_cents": 300000,
            "early_bird_multiplier": 1.10,
            "early_bird_deadline": EARLY_BIRD_DEADLINE,
        }
    )
    program = scenario["program"]
    stipend = scenario["stipend"]
    assert stipend["amount_cents"] == 330000
    assert stipend["status"] == StipendStatus.PROPOSED.value

    approved = validate_success(
        api.transition_stipend(
            stipend["id"], stipend_transition_payload("APPROVED"), INCENTIVE_ADMIN
        )
    )
    assert approved["status"] == StipendStatus.APPROVED.value

    reread = validate_success(api.get_incentive_program(program["id"], INCENTIVE_ADMIN))
    assert reread["budget_remaining_cents"] == 0
    assert reread["status"] == ProgramStatus.EXHAUSTED.value
    assert_program_budget_invariant(reread, _program_stipends(api, program["id"]))


def test_program_budget_restored_on_revoke(api):
    """PRD §3.8: "Revocation is possible from either `PROPOSED` or `APPROVED`:
    revoking a `PROPOSED` stipend touches no budget because it never encumbered
    any, while revoking an `APPROVED` stipend credits `amount_cents` back to
    `budget_remaining_cents` — and if the program sat `EXHAUSTED`, the credit
    reopens it to `OPEN`."
    PRD §3.8: "The compensating invariant holds across every debit and credit:
    `budget_remaining_cents` plus the summed `amount_cents` of the program's
    `APPROVED` and `PAID` stipends always equals `budget_total_cents`."

    The compensating credit restores 330000 + 0 == 330000 and reopens the program.

    Design: Difficulty/compensating_invariant/program_budget_conserved_across_approve_and_revoke
    """
    scenario = create_proposed_stipend_scenario(
        program_overrides={
            "budget_total_cents": 330000,
            "base_stipend_cents": 300000,
            "early_bird_multiplier": 1.10,
            "early_bird_deadline": EARLY_BIRD_DEADLINE,
        }
    )
    program = scenario["program"]
    stipend = scenario["stipend"]
    validate_success(
        api.transition_stipend(
            stipend["id"], stipend_transition_payload("APPROVED"), INCENTIVE_ADMIN
        )
    )

    revoked = validate_success(
        api.transition_stipend(
            stipend["id"], stipend_transition_payload("REVOKED"), INCENTIVE_ADMIN
        )
    )
    assert revoked["status"] == StipendStatus.REVOKED.value

    reread = validate_success(api.get_incentive_program(program["id"], INCENTIVE_ADMIN))
    assert reread["budget_remaining_cents"] == 330000
    assert reread["status"] == ProgramStatus.OPEN.value
    assert_program_budget_invariant(reread, _program_stipends(api, program["id"]))
