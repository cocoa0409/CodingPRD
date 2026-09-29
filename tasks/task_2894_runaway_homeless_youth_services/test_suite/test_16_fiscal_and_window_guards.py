"""Ceilings, balances and deadlines: the guards that count rather than classify.

Every refusal here depends on an arithmetic comparison — projected nights against
a stay ceiling, an extension count against two, cents against a balance, elapsed
days against an allowance, the clock against a deadline — so each case also shows
the neighbouring figure that is comfortably inside its own limit.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    COORDINATOR,
    SPECIALIST,
    SPECIALIST_ALT,
    USER_IDS,
    ApiErrorId,
    aftercare_contact_payload,
    assert_admission,
    assert_governance_vote,
    assert_instant_equals,
    assert_mediation_session,
    assert_reunification_case,
    assert_tlp_placement,
    cast_vote,
    clear_screening,
    decision_payload,
    extend_payload,
    fetch_admission,
    fetch_case,
    fetch_placement,
    fetch_program,
    fetch_youth,
    governance_vote_payload,
    home_assessment_payload,
    instant,
    intake_youth,
    license_emergency_shelter,
    license_transitional_living,
    life_skills_completion_payload,
    make_youth_member_headers,
    mediation_session_payload,
    move_clock,
    open_case,
    open_proposal,
    record_session_outcome,
    request_admission,
    savings_entry_payload,
    schedule_session,
    setup_active_admission,
    setup_placement_with_deposits,
    setup_tlp_placement,
    setup_vote_eligible_youth,
    tlp_placement_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

RIVERSIDE = {
    "name": "Riverside Emergency Shelter",
    "licensed_bed_capacity": 2,
    "min_age_years": 12,
    "max_age_years": 17,
    "max_stay_nights": 21,
}
NORTHSIDE = {
    "name": "Northside Transitional Living",
    "licensed_bed_capacity": 3,
    "min_age_years": 16,
    "max_age_years": 20,
    "max_placement_days": 540,
}
DOB_AGE_16 = "2010-03-15"
PLANNED_DISCHARGE = instant("2026-08-15")
MONTHLY_INCOME_CENTS = 90000


# ─── Instance: the stay ceiling first, then the extension count ───

NADIA = {
    "legal_first_name": "Nadia",
    "legal_last_name": "Fontaine",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
SHORT_DISCHARGE = instant("2026-08-05")
OVER_THE_STAY_CEILING = instant("2026-09-05")
FIRST_EXTENSION = instant("2026-08-10")
SECOND_EXTENSION = instant("2026-08-15")
THIRD_EXTENSION = instant("2026-08-20")


def test_the_stay_ceiling_and_the_extension_ceiling_refuse_in_turn(api):
    """PRD §3.5: "The projected billable nights recomputed against the new planned
    discharge instant must not exceed the program's `max_stay_nights`, with a figure
    exactly equal to the ceiling being allowed; a figure above it is refused with
    `ERR_MAX_STAY_EXCEEDED`."
    PRD §3.5: "The admission's `extension_count` must still be below two, since a stay
    may be extended at most twice; a third attempt is refused with
    `ERR_MAX_EXTENSIONS_REACHED`."
    PRD §3.5: "Extension is available only from status `ACTIVE`, which it moves to
    `EXTENDED`, or from `EXTENDED`, which it leaves in `EXTENDED` as a self-loop for the
    second extension."
    PRD §3.5: "An accepted extension replaces `planned_discharge_at` with the supplied
    instant, raises `extension_count` by one, and recomputes
    `projected_billable_nights`."

    Design: Corner/errors/extension_guards_refuse_over_max_stay_then_over_max_extensions
    """
    setup = setup_active_admission(
        program_overrides=dict(RIVERSIDE),
        youth_overrides=dict(NADIA),
        planned_discharge_at=SHORT_DISCHARGE,
    )
    admission_id = setup["admission"]["id"]
    assert setup["admission"]["projected_billable_nights"] == 4, (
        "2026-08-01 to 2026-08-05 projects four nights, got "
        f"{setup['admission']['projected_billable_nights']}"
    )

    over_ceiling = api.extend_admission(
        admission_id, extend_payload(OVER_THE_STAY_CEILING), CASE_MANAGER
    )

    validate_error(over_ceiling, ApiErrorId.ERR_MAX_STAY_EXCEEDED.value, 422)
    assert fetch_admission(admission_id)["extension_count"] == 0, (
        "a refused extension consumes none of the two allowed"
    )

    first = validate_success(
        api.extend_admission(admission_id, extend_payload(FIRST_EXTENSION), CASE_MANAGER)
    )
    assert_admission(first)
    assert first["status"] == "EXTENDED", (
        f"the first extension moves ACTIVE to EXTENDED, got {first['status']}"
    )
    assert first["extension_count"] == 1, (
        f"the first extension is consumed, got {first['extension_count']}"
    )
    assert first["projected_billable_nights"] == 9, (
        "2026-08-01 to 2026-08-10 projects nine nights, got "
        f"{first['projected_billable_nights']}"
    )

    second = validate_success(
        api.extend_admission(admission_id, extend_payload(SECOND_EXTENSION), CASE_MANAGER)
    )
    assert second["status"] == "EXTENDED", (
        f"the second extension is a self-loop on EXTENDED, got {second['status']}"
    )
    assert second["extension_count"] == 2, (
        f"both extensions are now consumed, got {second['extension_count']}"
    )
    assert second["projected_billable_nights"] == 14, (
        "2026-08-01 to 2026-08-15 projects fourteen nights, got "
        f"{second['projected_billable_nights']}"
    )

    third = api.extend_admission(
        admission_id, extend_payload(THIRD_EXTENSION), CASE_MANAGER
    )

    error = validate_error(third, ApiErrorId.ERR_MAX_EXTENSIONS_REACHED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_MAX_STAY_EXCEEDED.value, (
        "nineteen projected nights sits inside the twenty-one-night ceiling, so the "
        f"stay rule cannot explain the refusal, got {error['error_id']}"
    )
    final = fetch_admission(admission_id)
    assert_instant_equals(final["planned_discharge_at"], SECOND_EXTENSION,
                          "the admission's planned_discharge_at")
    assert final["extension_count"] == 2, (
        f"the refused third attempt raises nothing, got {final['extension_count']}"
    )


# ─── Instance: three fiscal guards on one ledger ───

EMRE = {
    "legal_first_name": "Emre",
    "legal_last_name": "Kovac",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
REVIEW_CLOCK = instant("2026-09-01")


def test_the_savings_ledger_refuses_an_overdraw_an_unmatched_reversal_and_a_locked_withdrawal(api):
    """PRD §3.8: "A `WITHDRAWAL` whose `amount_cents` exceeds the placement's current
    `savings_balance_cents` is refused with `ERR_SAVINGS_INSUFFICIENT_BALANCE`."
    PRD §3.8: "A `REVERSAL` whose `amount_cents` exceeds the sum of `DEPOSIT` amounts on
    that placement less the sum of prior `REVERSAL` amounts is refused with
    `ERR_SAVINGS_REVERSAL_UNMATCHED`, so a reversal can never invent savings that were
    never deposited."
    PRD §3.8: "A `WITHDRAWAL` attempted while the placement's `compliance_status` is
    `PROBATION` is refused with `ERR_SAVINGS_WITHDRAWAL_BLOCKED` — savings are locked
    while a youth is on probation, and they unlock again the moment a review moves the
    placement off probation."
    PRD §3.8: "Otherwise the review lands on `PROBATION`."
    PRD §3.8: "`required_savings_cents` is that monthly requirement multiplied by the
    number of full elapsed months — so a youth in the first thirty days of a placement
    owes nothing at all."

    Design: Corner/errors/savings_ledger_guards_reject_overdraw_unmatched_reversal_and_probation_withdrawal
    """
    setup = setup_placement_with_deposits(
        [1000],
        documented_monthly_income_cents=MONTHLY_INCOME_CENTS,
        shelter_program_overrides=dict(RIVERSIDE),
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides=dict(EMRE),
    )
    placement = setup["placement"]
    assert placement["savings_balance_cents"] == 1250, (
        "a 1000-cent deposit plus its 250-cent match is a 1250-cent balance, got "
        f"{placement['savings_balance_cents']}"
    )

    overdraw = api.create_savings_entry(
        placement["id"],
        savings_entry_payload("WITHDRAWAL", 2000, placement["version"], "overdraw attempt"),
        COORDINATOR,
    )
    validate_error(overdraw, ApiErrorId.ERR_SAVINGS_INSUFFICIENT_BALANCE.value, 422)

    unmatched = api.create_savings_entry(
        placement["id"],
        savings_entry_payload("REVERSAL", 1500, placement["version"],
                              "unmatched reversal attempt"),
        COORDINATOR,
    )
    validate_error(unmatched, ApiErrorId.ERR_SAVINGS_REVERSAL_UNMATCHED.value, 422)

    move_clock(REVIEW_CLOCK)
    reviewed = validate_success(api.run_compliance_review(placement["id"], ADMIN))
    assert reviewed["required_savings_cents"] == 18000, (
        "one full elapsed month at 90000 cents of income and 2000 basis points owes "
        f"18000 cents, got {reviewed['required_savings_cents']}"
    )
    assert reviewed["compliance_status"] == "PROBATION", (
        "1250 cents is below half of 18000, so the review lands on probation, got "
        f"{reviewed['compliance_status']}"
    )

    blocked = api.create_savings_entry(
        placement["id"],
        savings_entry_payload("WITHDRAWAL", 500, reviewed["version"],
                             "affordable withdrawal under probation"),
        COORDINATOR,
    )

    error = validate_error(blocked, ApiErrorId.ERR_SAVINGS_WITHDRAWAL_BLOCKED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_SAVINGS_INSUFFICIENT_BALANCE.value, (
        "500 cents sits inside the 1250-cent balance, so the balance rule cannot "
        f"explain the refusal, got {error['error_id']}"
    )
    final = fetch_placement(placement["id"])
    assert_tlp_placement(final)
    assert final["savings_balance_cents"] == 1250, (
        f"three refused postings move no money, got {final['savings_balance_cents']}"
    )
    _rows, meta = validate_paginated(api.list_savings_entries(placement["id"], COORDINATOR))
    assert meta["total_count"] == 1, (
        f"the single deposit is still the only entry, got {meta['total_count']}"
    )


# ─── Instance: an allowance already spent ───

SOL = {
    "legal_first_name": "Sol",
    "legal_last_name": "Beaumont",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
EXHAUSTED_CLOCK = instant("2028-02-01")


def test_a_spent_duration_allowance_refuses_both_credit_and_review(api):
    """PRD §3.7: "A placement that has already consumed its full duration allowance —
    one whose `days_elapsed` has reached or passed its `allowance_days` — can accept
    neither a new life-skills completion nor a compliance review and must simply be
    exited; either attempt is refused with `ERR_DURATION_LIMIT_REACHED`."
    PRD §2.10: "37. The placement has duration allowance left —
    `ERR_DURATION_LIMIT_REACHED`, 422 — on crediting a life-skills completion and on
    running a compliance review."
    PRD §3.7: "`days_elapsed` is the whole number of twenty-four-hour days between
    `placed_at` and the current logical clock, floored, and it is recomputed on every
    read of the placement and on every census run."
    PRD §3.7: "Step three sets `allowance_days` to `base_allowance_days` plus
    `earned_bonus_days`."
    PRD §3.7: "Finally, the census exits a placement outright, moving `NOTICE_GIVEN` to
    `EXITED` with `exit_reason` set to `DURATION_LIMIT` once `days_elapsed` has reached
    or passed `allowance_days`."

    Design: Corner/errors/exhausted_duration_allowance_blocks_life_skills_and_reviews
    """
    setup = setup_tlp_placement(
        MONTHLY_INCOME_CENTS,
        shelter_program_overrides=dict(RIVERSIDE),
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides=dict(SOL),
    )
    placement_id = setup["placement"]["id"]
    move_clock(EXHAUSTED_CLOCK)
    spent = fetch_placement(placement_id)
    assert spent["days_elapsed"] == 549, (
        "2026-08-01 to 2028-02-01 is 549 whole days, got "
        f"{spent['days_elapsed']}"
    )
    assert spent["allowance_days"] == 540, (
        "no credited hours earns no bonus days, so the allowance is still the base 540, "
        f"got {spent['allowance_days']}"
    )

    credit = api.create_life_skills_completion(
        placement_id, life_skills_completion_payload(10, "CIVIC_ENGAGEMENT"), COORDINATOR
    )
    validate_error(credit, ApiErrorId.ERR_DURATION_LIMIT_REACHED.value, 422)

    review = api.run_compliance_review(placement_id, COORDINATOR)
    validate_error(review, ApiErrorId.ERR_DURATION_LIMIT_REACHED.value, 422)

    after = fetch_placement(placement_id)
    assert after["tenancy_status"] == "PLACED", (
        "the census never ran, so nothing exited the placement automatically, got "
        f"{after['tenancy_status']}"
    )
    assert after["life_skills_credit_hours"] == 0, (
        f"the refused completion credits no hours, got {after['life_skills_credit_hours']}"
    )
    _rows, meta = validate_paginated(
        api.list_life_skills_completions(placement_id, COORDINATOR)
    )
    assert meta["total_count"] == 0, (
        f"no completion row was created at all, got {meta['total_count']}"
    )


# ─── Instance: three vote guards on one proposal ───

ALIA = {
    "legal_first_name": "Alia",
    "legal_last_name": "Ferrand",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
BODHI = {
    "legal_first_name": "Bodhi",
    "legal_last_name": "Ferrand",
    "date_of_birth": "2010-04-15",
    "unaccompanied": True,
}
VOTING_CLOSES_AT = instant("2026-08-10")
PAST_THE_DEADLINE = instant("2026-08-11")


def test_the_ballot_refuses_a_duplicate_an_ineligible_voter_and_a_late_retraction(api):
    """PRD §3.9: "The youth must hold no existing vote on that proposal in status
    `COUNTED`, or the attempt is refused with `ERR_DUPLICATE_VOTE`; a previously
    retracted vote does not block a fresh one."
    PRD §3.9: "The youth's `governance_vote_eligible` must be true and the youth must be
    resident in the proposal's program by the electorate test below, or the attempt is
    refused with `ERR_YOUTH_NOT_VOTE_ELIGIBLE`."
    PRD §3.9: "And the current clock must be at or before the proposal's
    `voting_closes_at`; a clock strictly past that instant is refused with
    `ERR_PROPOSAL_VOTE_CLOSED`."
    PRD §3.9: "Retraction is subject to the same proposal-decided and voting-deadline
    gates as casting, and to the ownership rule of §2.1: a vote may only be retracted by
    the youth who cast it, and any other youth is refused with `ERR_NOT_VOTE_OWNER`."
    PRD §3.1: "`governance_vote_eligible` is likewise derived rather than declared: it is
    true exactly when the youth's `status` is `SHELTERED` or `TLP_ENROLLED` **and**
    `engagement_contact_count` is at least one."

    Design: Corner/errors/governance_vote_guards_reject_duplicate_ineligible_and_late_votes
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    eligible = setup_vote_eligible_youth(program["id"], PLANNED_DISCHARGE, dict(ALIA))
    voter_id = eligible["youth"]["id"]
    ineligible = intake_youth(**dict(BODHI))
    clear_screening(ineligible["id"])
    request_admission(ineligible["id"], program["id"], PLANNED_DISCHARGE)
    assert fetch_youth(voter_id)["governance_vote_eligible"] is True, (
        "a sheltered youth with one outreach encounter is vote-eligible"
    )
    assert fetch_youth(ineligible["id"])["governance_vote_eligible"] is False, (
        "a sheltered youth met straight off the street is not vote-eligible"
    )
    proposal = open_proposal(
        program["id"], VOTING_CLOSES_AT,
        title="Add a vegetarian option", category="FOOD_SERVICE",
    )
    vote = cast_vote(proposal["id"], voter_id, "SUPPORT")

    duplicate = api.cast_governance_vote(
        proposal["id"], governance_vote_payload("OPPOSE"), make_youth_member_headers(voter_id)
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_VOTE.value, 409)

    unqualified = api.cast_governance_vote(
        proposal["id"], governance_vote_payload("SUPPORT"),
        make_youth_member_headers(ineligible["id"]),
    )
    validate_error(unqualified, ApiErrorId.ERR_YOUTH_NOT_VOTE_ELIGIBLE.value, 422)

    move_clock(PAST_THE_DEADLINE)
    late = api.retract_governance_vote(vote["id"], make_youth_member_headers(voter_id))

    error = validate_error(late, ApiErrorId.ERR_PROPOSAL_VOTE_CLOSED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_NOT_VOTE_OWNER.value, (
        "the retracting youth is the youth who cast the vote, got "
        f"{error['error_id']}"
    )
    rows, meta = validate_paginated(api.list_proposal_votes(proposal["id"], ADMIN))
    assert meta["total_count"] == 1, (
        f"only the first vote was ever counted, got {meta['total_count']}"
    )
    assert_governance_vote(rows[0])
    assert rows[0]["status"] == "COUNTED", (
        f"the refused retraction leaves the vote counted, got {rows[0]['status']}"
    )
    assert rows[0]["stance"] == "SUPPORT", (
        f"the refused duplicate never flipped the stance, got {rows[0]['stance']}"
    )


# ─── Instance: the seventy-two-hour aftercare window closes ───

MIKA = {
    "legal_first_name": "Mika",
    "legal_last_name": "Solberg",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
SESSION_START = instant("2026-08-03", "14:00:00")
SESSION_END = instant("2026-08-03", "16:00:00")
RECORDING_CLOCK = instant("2026-08-03", "14:30:00")
AFTERCARE_DUE = instant("2026-08-06", "14:30:00")
LATE_CONTACT_CLOCK = instant("2026-08-07")


def test_a_first_aftercare_contact_past_the_window_is_refused(api):
    """PRD §3.6: "The **first** contact must be logged at or before
    `aftercare_plan_due_at`, and a first contact logged after the clock has passed that
    instant is refused with `ERR_AFTERCARE_WINDOW_MISSED`; later contacts are
    unconstrained by that window."
    PRD §3.6: "The case's `aftercare_plan_due_at` is set to the clock instant plus
    seventy-two hours and the case moves to `APPROVED`."
    PRD §3.6: "Each logged aftercare contact may carry an optional `contact_note` and
    raises `aftercare_contacts_completed` by one."
    PRD §3.6: "Both branches store the acting identifier as `decision_user_id`."
    PRD §3.6: "Because the youth became `REUNIFIED_PENDING`, every admission of the youth
    in `ACTIVE` or `EXTENDED` moves to `DISCHARGE_SCHEDULED`."

    Design: Corner/errors/first_aftercare_contact_after_the_seventy_two_hour_window_is_refused
    """
    youth = intake_youth(**dict(MIKA))
    case = open_case(youth["id"], household_label="Solberg household")
    session = schedule_session(case["id"], SESSION_START, SESSION_END)
    move_clock(RECORDING_CLOCK)
    record_session_outcome(session["id"], "AGREEMENT", SPECIALIST)
    validate_success(
        api.record_home_assessment(case["id"], home_assessment_payload("SAFE"), SPECIALIST)
    )
    approved = validate_success(
        api.decide_reunification_case(case["id"], decision_payload("APPROVE"), SPECIALIST_ALT)
    )
    assert_reunification_case(approved)
    assert approved["status"] == "APPROVED", (
        f"the approval is accepted, got {approved['status']}"
    )
    assert_instant_equals(approved["aftercare_plan_due_at"], AFTERCARE_DUE,
                          "the case's aftercare_plan_due_at")

    move_clock(LATE_CONTACT_CLOCK)
    response = api.create_aftercare_contact(
        case["id"], aftercare_contact_payload("late first check-in"), SPECIALIST
    )

    validate_error(response, ApiErrorId.ERR_AFTERCARE_WINDOW_MISSED.value, 422)
    final = fetch_case(case["id"])
    assert final["status"] == "APPROVED", (
        f"the refused contact leaves the case approved, got {final['status']}"
    )
    assert final["aftercare_contacts_completed"] == 0, (
        f"no contact was counted, got {final['aftercare_contacts_completed']}"
    )
    assert final["decision_user_id"] == USER_IDS["REUNIFICATION_SPECIALIST_ALT"], (
        "the second specialist signed off on the approval, got "
        f"{final['decision_user_id']}"
    )
    assert fetch_youth(youth["id"])["status"] == "PROSPECT", (
        "the approval's youth hop starts from SHELTERED, so a youth who never held a bed "
        "is left a prospect"
    )


# ─── Instance: tenancy is point-in-time exclusive on the youth ───

ANOUK = {
    "legal_first_name": "Anouk",
    "legal_last_name": "Perez",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}


def test_a_second_open_placement_for_the_same_youth_is_an_overlap(api):
    """PRD §3.7: "Placement exclusivity is **point-in-time with an open-ended
    interval**: the youth's placement occupies every instant from `placed_at` onwards
    with no end instant participating at all, so no adjacency case exists and the rule
    reduces to a simple check that the youth holds no other placement whose
    `tenancy_status` is `PLACED` or `NOTICE_GIVEN`; a second open placement fails with
    `ERR_PLACEMENT_OVERLAP`."
    PRD §2.10: "31. The youth holds no other open transitional-living placement —
    `ERR_PLACEMENT_OVERLAP`, 409 — on transitional-living placement."
    PRD §3.7: "On acceptance the server stamps `placed_at` with the clock instant,
    records the acting coordinator as `coordinator_user_id`, opens the placement with
    `tenancy_status` `PLACED` and `compliance_status` `IN_COMPLIANCE`, sets
    `consecutive_probation_reviews` to 0, `life_skills_credit_hours` to 0,
    `required_savings_cents` to 0, `savings_balance_cents` to 0 and
    `match_awarded_cents` to 0, leaves `exited_at` and `exit_reason` null, copies
    `base_allowance_days` from the program's `max_placement_days`, raises the program's
    `occupied_beds` by one — which forces that program's `utilization_bp` and `posture`
    to be recomputed — and moves the youth `SHELTERED → TLP_ENROLLED` with the youth's
    `version` incremented by one and `governance_vote_eligible` recomputed, staying
    true."

    Design: Corner/errors/second_tlp_placement_for_the_same_youth_returns_placement_overlap
    """
    setup = setup_tlp_placement(
        MONTHLY_INCOME_CENTS,
        shelter_program_overrides=dict(RIVERSIDE),
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides=dict(ANOUK),
    )
    youth_id = setup["youth"]["id"]
    tlp_program_id = setup["tlp_program"]["id"]

    response = api.create_tlp_placement(
        tlp_placement_payload(youth_id, tlp_program_id, MONTHLY_INCOME_CENTS), COORDINATOR
    )

    validate_error(response, ApiErrorId.ERR_PLACEMENT_OVERLAP.value, 409)
    _rows, meta = validate_paginated(
        api.list_tlp_placements(COORDINATOR, {"youth_id": youth_id})
    )
    assert meta["total_count"] == 1, (
        f"the refused request created no second placement, got {meta['total_count']}"
    )
    held = fetch_placement(setup["placement"]["id"])
    assert_tlp_placement(held)
    assert held["tenancy_status"] == "PLACED", (
        f"the first tenancy is untouched, got {held['tenancy_status']}"
    )
    assert fetch_program(tlp_program_id)["occupied_beds"] == 1, (
        "the refusal consumes no second bed"
    )
    assert fetch_youth(youth_id)["status"] == "TLP_ENROLLED", (
        "the youth is enrolled exactly once"
    )


# ─── Instance: the cooldown is measured from held_at, not from the window's end ───

EMIL = {
    "legal_first_name": "Emil",
    "legal_last_name": "Nowak",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
INSIDE_THE_COOLDOWN = (instant("2026-08-05", "10:00:00"), instant("2026-08-05", "12:00:00"))
EXACTLY_AT_THE_BUFFER = (instant("2026-08-06", "14:30:00"), instant("2026-08-06", "16:00:00"))


def test_the_mediation_cooldown_runs_from_the_held_instant(api):
    """PRD §3.6: "Second, a **cooldown buffer** of seventy-two hours applies between
    rounds: `scheduled_start_at` must be at least seventy-two hours after the `held_at`
    of the case's most recent held session, and the buffer is measured from that
    `held_at` instant rather than from the previous window's end."
    PRD §3.6: "A shorter gap is refused with `ERR_MEDIATION_COOLDOWN_ACTIVE`."
    PRD §3.6: "First, session windows on one case are **closed intervals** and touching
    endpoints do collide: the new window running from `scheduled_start_at` to
    `scheduled_end_at` inclusive must not intersect the window of any other session of
    the same case, and a new window whose start instant equals a prior window's end
    instant is rejected — unlike the half-open admission rule, where exact adjacency is
    legal."
    PRD §3.6: "The server stores the session against its case through `case_id`, sets
    `round_number` to the case's current `mediation_round` plus one, records
    `scheduler_user_id`, and leaves `outcome` and `held_at` null."
    PRD §3.6: "Scheduling is available while the case stands `OPENED`, moving it `OPENED
    → MEDIATION_SCHEDULED`, and again while it stands `MEDIATION_HELD`, moving it
    `MEDIATION_HELD → MEDIATION_SCHEDULED` for the next round; from any other case
    status it is refused with `ERR_CASE_INVALID_STATE`."

    Design: Corner/errors/mediation_cooldown_blocks_a_session_inside_seventy_two_hours
    """
    youth = intake_youth(**dict(EMIL))
    case = open_case(youth["id"], household_label="Nowak household")
    first = schedule_session(case["id"], SESSION_START, SESSION_END)
    move_clock(RECORDING_CLOCK)
    held = record_session_outcome(first["id"], "PROGRESS", SPECIALIST)
    assert_mediation_session(held)
    assert_instant_equals(held["held_at"], RECORDING_CLOCK, "the session's held_at")

    early = api.create_mediation_session(
        case["id"], mediation_session_payload(*INSIDE_THE_COOLDOWN), SPECIALIST
    )

    error = validate_error(early, ApiErrorId.ERR_MEDIATION_COOLDOWN_ACTIVE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_MEDIATION_SESSION_OVERLAP.value, (
        "a window starting eighteen hours after the first window's 16:00 end intersects "
        f"nothing, got {error['error_id']}"
    )

    accepted = validate_success(
        api.create_mediation_session(
            case["id"], mediation_session_payload(*EXACTLY_AT_THE_BUFFER), SPECIALIST
        ),
        201,
    )
    assert_mediation_session(accepted)
    assert accepted["round_number"] == 2, (
        "exactly seventy-two hours after held_at satisfies an at-least buffer, and the "
        f"case's round of one plus one is two, got {accepted['round_number']}"
    )
    assert accepted["held_at"] is None, (
        f"the second session has not been held yet, got {accepted['held_at']}"
    )

    final = fetch_case(case["id"])
    assert final["status"] == "MEDIATION_SCHEDULED", (
        "scheduling the next round moves the case out of MEDIATION_HELD, got "
        f"{final['status']}"
    )
    assert final["mediation_round"] == 1, (
        "only the recorded session raised the round count, got "
        f"{final['mediation_round']}"
    )
    _rows, meta = validate_paginated(api.list_mediation_sessions(case["id"], SPECIALIST))
    assert meta["total_count"] == 2, (
        f"the refused schedule created no session row, got {meta['total_count']}"
    )


# ─── Instance: the lowest rung on the ladder ───

KIRA = {
    "legal_first_name": "Kira",
    "legal_last_name": "Adeoye",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}


def test_an_unresolved_obligation_blocks_a_transitional_living_placement(api):
    """PRD §3.7: "And last of all, the youth's `risk_posture` must be `OPEN`: a
    `RESTRICTED` posture — meaning an unresolved parental-notification obligation on any
    of the youth's admissions, or a `CRITICAL` trafficking tier — fails with
    `ERR_YOUTH_POSTURE_RESTRICTED`."
    PRD §3.7: "That posture gate sits at the very bottom of the ladder, so every other
    placement check listed here wins over it."
    PRD §3.7: "The youth's most recent safety screening must not stand `ESCALATED`, or
    the request fails with `ERR_SCREENING_ESCALATED_BLOCKS_ACTION`; it must furthermore
    exist and stand `CLEARED`, and a missing or non-cleared screening fails with
    `ERR_SCREENING_REQUIRED`."
    PRD §2.7: "A `RESTRICTED` risk posture blocks transitional-living placement with
    `ERR_YOUTH_POSTURE_RESTRICTED` (HTTP 422) until the obligation is discharged."

    Design: Corner/errors/restricted_youth_posture_blocks_a_transitional_living_placement
    """
    setup = setup_active_admission(
        program_overrides=dict(RIVERSIDE),
        youth_overrides=dict(KIRA),
        planned_discharge_at=PLANNED_DISCHARGE,
    )
    tlp_program = license_transitional_living(**dict(NORTHSIDE))
    restricted = fetch_youth(setup["youth"]["id"])
    assert restricted["risk_posture"] == "RESTRICTED", (
        "the fresh PENDING obligation restricts the youth, got "
        f"{restricted['risk_posture']}"
    )
    assert setup["screening"]["status"] == "CLEARED", (
        f"the screening stands cleared, got {setup['screening']['status']}"
    )

    response = api.create_tlp_placement(
        tlp_placement_payload(restricted["id"], tlp_program["id"], MONTHLY_INCOME_CENTS),
        COORDINATOR,
    )

    error = validate_error(response, ApiErrorId.ERR_YOUTH_POSTURE_RESTRICTED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_SCREENING_REQUIRED.value, (
        "a CLEARED screening satisfies the screening gate, so only the posture gate can "
        f"fail, got {error['error_id']}"
    )
    assert fetch_youth(restricted["id"])["status"] == "SHELTERED", (
        "the refused placement leaves the youth in a shelter bed"
    )
    assert fetch_program(tlp_program["id"])["occupied_beds"] == 0, (
        "no transitional-living bed was consumed"
    )
    _rows, meta = validate_paginated(
        api.list_tlp_placements(COORDINATOR, {"youth_id": restricted["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no placement row was created at all, got {meta['total_count']}"
    )
