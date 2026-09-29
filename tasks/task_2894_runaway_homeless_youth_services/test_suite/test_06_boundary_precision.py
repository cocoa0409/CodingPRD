"""Thresholds tested one unit either side of the edge.

An age band whose upper bound is inclusive, a collection whose cardinality is
zero, and a savings balance that lands on the requirement to the cent.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    ApiErrorId,
    admission_payload,
    assert_admission,
    assert_governance_proposal,
    assert_savings_ledger_entry,
    assert_tlp_placement,
    clear_screening,
    fetch_placement,
    fetch_program,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    move_clock,
    open_proposal,
    post_savings_entry,
    request_admission,
    run_review,
    setup_placement_with_deposits,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Instance: age exactly at the program's max_age_years ───

PLANNED_DISCHARGE = instant("2026-08-08")
TESS = {
    "legal_first_name": "Tess", "legal_last_name": "Whitmore",
    "date_of_birth": "2008-08-02", "unaccompanied": True,
}
UMA = {
    "legal_first_name": "Uma", "legal_last_name": "Braddock",
    "date_of_birth": "2008-08-01", "unaccompanied": True,
}


def _band_program_with_two_edge_youths():
    """A program licensed for ages 12 to 17 and two cleared youths born one calendar
    day apart astride the eighteenth-birthday line."""
    program = license_emergency_shelter(
        name="Riverside Emergency Shelter",
        licensed_bed_capacity=2,
        min_age_years=12,
        max_age_years=17,
        max_stay_nights=21,
    )
    on_edge = intake_youth(**dict(TESS))
    clear_screening(on_edge["id"])
    past_edge = intake_youth(**dict(UMA))
    clear_screening(past_edge["id"])
    return program, on_edge, past_edge


def test_age_on_the_inclusive_upper_bound_is_admissible(api):
    """PRD §2.5: "A youth's `age_years` is a whole number of years measured from
    `date_of_birth` to the current logical clock, computed as follows: the youth is
    treated as having already had this year's birthday when the clock's
    month-and-day pair is greater than or equal to the birth date's month-and-day
    pair; the age is then the clock's year minus the birth year, reduced by one when
    this year's birthday has not yet arrived."
    PRD §2.10: "25. The youth's age in whole years lies inside the program's licensed
    age band, both bounds inclusive — `ERR_AGE_OUTSIDE_PROGRAM_BAND`, 422 — on the
    admission request and on transitional-living placement."

    Design: Difficulty/boundary_precision_check/age_exactly_at_max_age_years_boundary_on_admission
    """
    program, on_edge, _past_edge = _band_program_with_two_edge_youths()
    assert on_edge["age_years"] == 17, (
        "a youth born 2008-08-02 has not yet had a birthday on 2026-08-01, so the "
        f"age is 17, got {on_edge['age_years']}"
    )

    admission = request_admission(on_edge["id"], program["id"], PLANNED_DISCHARGE)

    assert_admission(admission)
    assert admission["status"] == "ACTIVE", (
        f"the upper bound is inclusive, so the stay begins, got {admission['status']}"
    )
    assert admission["projected_billable_nights"] == 7, (
        "2026-08-01 to 2026-08-08 is seven whole calendar days, got "
        f"{admission['projected_billable_nights']}"
    )


def test_age_one_day_past_the_bound_is_refused(api):
    """PRD §2.5: "Because the comparison is inclusive, a youth turns the new age on
    the birthday itself rather than the day after, and the result is always floored
    to whole years."
    PRD §3.3: "The youth's `age_years` at the current clock must lie between the
    program's `min_age_years` and `max_age_years`, both bounds inclusive, or the
    request fails with `ERR_AGE_OUTSIDE_PROGRAM_BAND`."

    Design: Difficulty/boundary_precision_check/age_exactly_at_max_age_years_boundary_on_admission
    """
    program, on_edge, past_edge = _band_program_with_two_edge_youths()
    request_admission(on_edge["id"], program["id"], PLANNED_DISCHARGE)
    assert past_edge["age_years"] == 18, (
        "a youth born 2008-08-01 turns eighteen on 2026-08-01 itself, got "
        f"{past_edge['age_years']}"
    )

    response = api.create_admission(
        admission_payload(past_edge["id"], program["id"], PLANNED_DISCHARGE), CASE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_AGE_OUTSIDE_PROGRAM_BAND.value, 422)
    assert fetch_youth(past_edge["id"])["status"] == "PROSPECT", (
        "the refused youth never enters the program"
    )
    _rows, meta = validate_paginated(
        api.list_admissions(ADMIN, {"youth_id": past_edge["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no admission row survives the refusal, got {meta['total_count']}"
    )
    assert fetch_program(program["id"])["occupied_beds"] == 1, (
        "only the in-band youth holds a bed"
    )


# ─── Instance: an electorate of cardinality zero at close time ───

VOTING_CLOSES_AT = instant("2026-08-10")


def _proposal_over_an_empty_program():
    """A proposal on a program that has no admissions and no placements at all, so
    no youth passes the residency filter."""
    program = license_emergency_shelter(
        name="Harbor Street Shelter",
        licensed_bed_capacity=2,
        min_age_years=12,
        max_age_years=17,
        max_stay_nights=21,
    )
    proposal = open_proposal(
        program["id"], VOTING_CLOSES_AT, title="Later weeknight quiet hours",
        category="HOUSE_RULES",
    )
    return program, proposal


def test_closing_a_vote_over_an_empty_electorate_is_refused(api):
    """PRD §3.9: "An empty electorate is not a decision at all: it is refused with
    `ERR_NO_ELIGIBLE_ELECTORATE`, nothing is frozen, nothing is changed, and the
    proposal remains `OPEN_FOR_VOTE`."
    PRD §3.9: "`eligible_electorate_size` is the number of youths whose
    `governance_vote_eligible` is true and who are resident in the proposal's
    program, where residency means the youth holds an admission at that program in
    status `ACTIVE`, `EXTENDED` or `DISCHARGE_SCHEDULED`, or holds a
    transitional-living placement at that program whose `tenancy_status` is `PLACED`
    or `NOTICE_GIVEN`."

    Design: Difficulty/boundary_precision_check/empty_electorate_zero_count_edge_on_close_vote
    """
    _program, proposal = _proposal_over_an_empty_program()

    response = api.close_governance_vote(proposal["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_ELECTORATE.value, 422)
    reported = response.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_PROPOSAL_ALREADY_DECIDED.value, (
        f"the proposal was never decided, got {reported}"
    )


def test_refused_close_freezes_nothing_onto_the_proposal(api):
    """PRD §3.9: "`support_ratio_bp` is 0 when the electorate is empty, and otherwise
    the support count multiplied by 10000, divided by the electorate size and floored
    to whole basis points."
    PRD §3.9: "Both decided outcomes freeze `eligible_electorate_size` and
    `support_ratio_bp` onto the row and record the acting administrator as
    `decided_by_user_id`; adoption additionally stamps `adopted_at` with the clock
    instant, while rejection leaves `adopted_at` null."

    Design: Difficulty/boundary_precision_check/empty_electorate_zero_count_edge_on_close_vote
    """
    _program, proposal = _proposal_over_an_empty_program()

    api.close_governance_vote(proposal["id"], ADMIN)

    current = validate_success(api.get_governance_proposal(proposal["id"], ADMIN))
    assert_governance_proposal(current)
    assert current["status"] == "OPEN_FOR_VOTE", (
        f"the refusal changes nothing, got {current['status']}"
    )
    assert current["eligible_electorate_size"] == 0, (
        f"nothing was frozen onto the row, got {current['eligible_electorate_size']}"
    )
    assert current["support_vote_count"] == 0, (
        f"no vote was ever cast, got {current['support_vote_count']}"
    )
    assert current["oppose_vote_count"] == 0, (
        f"no vote was ever cast, got {current['oppose_vote_count']}"
    )
    assert current["support_ratio_bp"] == 0, (
        "an empty electorate reports a ratio of zero rather than dividing by zero, "
        f"got {current['support_ratio_bp']}"
    )
    assert current["adopted_at"] is None, (
        f"nothing was adopted, got {current['adopted_at']}"
    )
    assert current["decided_by_user_id"] is None, (
        f"nobody decided the proposal, got {current['decided_by_user_id']}"
    )
    _rows, meta = validate_paginated(api.list_proposal_votes(proposal["id"], ADMIN))
    assert meta["total_count"] == 0, (
        f"the proposal carries no votes, got {meta['total_count']}"
    )


# ─── Instance: a savings balance that lands exactly on the requirement ───

TLP_PROGRAM = {
    "name": "Northside Transitional Living",
    "licensed_bed_capacity": 3,
    "min_age_years": 16,
    "max_age_years": 20,
    "max_placement_days": 540,
    "savings_match_rate_bp": 2500,
    "required_savings_rate_bp": 2000,
}
IVY = {
    "legal_first_name": "Ivy", "legal_last_name": "Marchetti",
    "date_of_birth": "2010-03-15", "unaccompanied": True,
}
THIRTY_DAYS_ON = instant("2026-08-31")


def _placement_exactly_meeting_month_one():
    """A placement on 120000 cents of monthly income carrying a single 19200-cent
    deposit, read thirty days after it opened."""
    setup = setup_placement_with_deposits(
        [19200],
        documented_monthly_income_cents=120000,
        tlp_program_overrides=dict(TLP_PROGRAM),
        youth_overrides=dict(IVY),
    )
    move_clock(THIRTY_DAYS_ON)
    setup["placement"] = fetch_placement(setup["placement"]["id"])
    return setup


def test_balance_exactly_at_the_requirement_scores_in_compliance(api):
    """PRD §3.8: "The number of full elapsed months is `days_elapsed` divided by
    thirty and floored."
    PRD §3.8: "`required_savings_cents` is that monthly requirement multiplied by the
    number of full elapsed months — so a youth in the first thirty days of a
    placement owes nothing at all."
    PRD §3.8: "Three outcomes are possible and they are evaluated as inclusive
    comparisons, so an exactly-met requirement counts as met."
    PRD §3.8: "A balance at or above `required_savings_cents` lands on
    `IN_COMPLIANCE`."

    Design: Difficulty/boundary_precision_check/savings_balance_exactly_meets_required_is_in_compliance_one_cent_below_is_deficient
    """
    setup = _placement_exactly_meeting_month_one()
    deposit = setup["entries"][0]

    assert_savings_ledger_entry(deposit)
    assert deposit["match_component_cents"] == 4800, (
        "19200 cents at 2500 basis points is 4800 cents, got "
        f"{deposit['match_component_cents']}"
    )
    assert deposit["balance_after_cents"] == 24000, (
        f"19200 deposited plus 4800 matched is 24000, got {deposit['balance_after_cents']}"
    )
    placement = setup["placement"]
    assert_tlp_placement(placement)
    assert placement["days_elapsed"] == 30, (
        f"thirty whole days have elapsed, got {placement['days_elapsed']}"
    )
    assert placement["required_savings_cents"] == 24000, (
        "one full month at 2000 basis points of 120000 cents is 24000, got "
        f"{placement['required_savings_cents']}"
    )

    reviewed = run_review(placement["id"])
    assert reviewed["compliance_status"] == "IN_COMPLIANCE", (
        "a balance level with the requirement is in compliance, got "
        f"{reviewed['compliance_status']}"
    )


def test_balance_one_cent_below_the_requirement_scores_savings_deficient(api):
    """PRD §3.8: "Otherwise a balance at or above half the required savings, that
    half being floored to whole cents, lands on `SAVINGS_DEFICIENT`."
    PRD §3.8: "`signed_amount_cents` gives the posting its direction: it is the
    positive `amount_cents` for a `DEPOSIT`, and the negation of `amount_cents` for
    both a `WITHDRAWAL` and a `REVERSAL`."
    PRD §3.8: "In short, any review that does not land on `PROBATION` resets the
    consecutive-probation counter to zero, and any review that lands on `PROBATION`
    raises it by one."

    Design: Difficulty/boundary_precision_check/savings_balance_exactly_meets_required_is_in_compliance_one_cent_below_is_deficient
    """
    setup = _placement_exactly_meeting_month_one()
    placement_id = setup["placement"]["id"]
    run_review(placement_id)

    withdrawal = post_savings_entry(placement_id, "WITHDRAWAL", 1,
                                    source_note="one cent bus fare")

    assert_savings_ledger_entry(withdrawal)
    assert withdrawal["signed_amount_cents"] == -1, (
        f"a withdrawal contributes negatively, got {withdrawal['signed_amount_cents']}"
    )
    assert withdrawal["match_component_cents"] == 0, (
        f"a withdrawal earns no match, got {withdrawal['match_component_cents']}"
    )
    assert withdrawal["balance_after_cents"] == 23999, (
        f"24000 less one cent is 23999, got {withdrawal['balance_after_cents']}"
    )

    reviewed = run_review(placement_id)
    assert reviewed["savings_balance_cents"] == 23999, (
        f"the balance sits one cent short, got {reviewed['savings_balance_cents']}"
    )
    assert reviewed["compliance_status"] == "SAVINGS_DEFICIENT", (
        "one cent below the requirement but above the floored half is deficient, "
        f"got {reviewed['compliance_status']}"
    )
    assert reviewed["consecutive_probation_reviews"] == 0, (
        "a review that does not land on probation leaves the counter at zero, got "
        f"{reviewed['consecutive_probation_reviews']}"
    )
    youth = fetch_youth(setup["youth"]["id"])
    assert youth["lifetime_savings_deposited_cents"] == 19200, (
        "only deposits accumulate onto the lifetime figure, got "
        f"{youth['lifetime_savings_deposited_cents']}"
    )
