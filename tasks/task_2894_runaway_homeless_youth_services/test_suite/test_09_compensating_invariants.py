"""Quantities that must come back to exactly where they started.

A retracted-then-recast vote must restore the counted tally to two rather than
three, and a reversal must unwind both a deposit and the match it earned.
"""

from test_helpers import (
    ADMIN,
    USER_IDS,
    assert_governance_proposal,
    assert_governance_vote,
    assert_instant_equals,
    assert_savings_identity,
    assert_savings_ledger_entry,
    assert_tlp_placement,
    cast_vote,
    close_vote,
    fetch_placement,
    fetch_proposal,
    fetch_youth,
    instant,
    license_emergency_shelter,
    open_proposal,
    post_savings_entry,
    retract_vote,
    savings_entries_of,
    setup_placement_with_deposits,
    setup_vote_eligible_youth,
    validate_paginated,
)

# ─── Instance: retraction and recast restore the support tally ───

CLOCK_START_INSTANT = instant("2026-08-01")
VOTING_CLOSES_AT = instant("2026-08-10")
RESIDENT_DISCHARGE = instant("2026-08-20")
ANA = {
    "legal_first_name": "Ana", "legal_last_name": "Petrov",
    "date_of_birth": "2010-03-15", "unaccompanied": True,
}
BEN = {
    "legal_first_name": "Ben", "legal_last_name": "Halloran",
    "date_of_birth": "2010-03-15", "unaccompanied": True,
}


def _two_resident_voters_and_a_proposal():
    """A program housing exactly two vote-eligible residents, and one open proposal
    over that electorate of two."""
    program = license_emergency_shelter(
        name="Riverside Emergency Shelter", licensed_bed_capacity=2,
        min_age_years=12, max_age_years=17, max_stay_nights=21,
    )
    first = setup_vote_eligible_youth(program["id"], RESIDENT_DISCHARGE, dict(ANA))
    second = setup_vote_eligible_youth(program["id"], RESIDENT_DISCHARGE, dict(BEN))
    proposal = open_proposal(
        program["id"], VOTING_CLOSES_AT,
        title="Rotating youth-led house meeting chair", category="GRIEVANCE_PROCESS",
    )
    return program, first["youth"], second["youth"], proposal


def test_retraction_lowers_the_counted_support_tally_by_one(api):
    """PRD §3.9: "A youth may retract its own vote, which moves the vote `COUNTED →
    RETRACTED`, stamps `retracted_at` with the clock instant, and lowers the
    proposal's `support_vote_count` or `oppose_vote_count` by one, restoring the
    pre-vote tally exactly."
    PRD §3.1: "`governance_vote_eligible` is likewise derived rather than declared: it
    is true exactly when the youth's `status` is `SHELTERED` or `TLP_ENROLLED` **and**
    `engagement_contact_count` is at least one."

    Design: Difficulty/compensating_invariant/governance_vote_retraction_and_recast_restores_the_support_tally
    """
    _program, ana, ben, proposal = _two_resident_voters_and_a_proposal()
    assert ana["governance_vote_eligible"] is True, (
        "a sheltered youth with one outreach encounter is eligible, got "
        f"{ana['governance_vote_eligible']}"
    )
    assert ben["governance_vote_eligible"] is True, (
        f"the second resident is eligible too, got {ben['governance_vote_eligible']}"
    )

    ana_vote = cast_vote(proposal["id"], ana["id"], "SUPPORT")
    cast_vote(proposal["id"], ben["id"], "SUPPORT")
    assert fetch_proposal(proposal["id"])["support_vote_count"] == 2, (
        "two counted support votes stand before the retraction"
    )

    retracted = retract_vote(ana_vote["id"], ana["id"])

    assert_governance_vote(retracted)
    assert retracted["status"] == "RETRACTED", (
        f"the row stays in place as retracted, got {retracted['status']}"
    )
    assert_instant_equals(retracted["retracted_at"], CLOCK_START_INSTANT,
                          "the retracted vote's retracted_at")
    assert fetch_proposal(proposal["id"])["support_vote_count"] == 1, (
        "the retraction restores the pre-vote tally exactly"
    )


def test_recast_restores_the_tally_to_exactly_two(api):
    """PRD §3.9: "The youth must hold no existing vote on that proposal in status
    `COUNTED`, or the attempt is refused with `ERR_DUPLICATE_VOTE`; a previously
    retracted vote does not block a fresh one."
    PRD §3.9: "`support_vote_count` is the number of votes on the proposal whose
    `stance` is `SUPPORT` and whose `status` is `COUNTED`; `oppose_vote_count` is the
    number whose `stance` is `OPPOSE` and whose `status` is `COUNTED`."
    PRD §3.9: "Retracted votes are excluded from both counts."

    Design: Difficulty/compensating_invariant/governance_vote_retraction_and_recast_restores_the_support_tally
    """
    _program, ana, ben, proposal = _two_resident_voters_and_a_proposal()
    first_vote = cast_vote(proposal["id"], ana["id"], "SUPPORT")
    ben_vote = cast_vote(proposal["id"], ben["id"], "SUPPORT")
    retract_vote(first_vote["id"], ana["id"])

    recast = cast_vote(proposal["id"], ana["id"], "SUPPORT")

    assert recast["status"] == "COUNTED", (
        f"the replacement vote counts, got {recast['status']}"
    )
    current = fetch_proposal(proposal["id"])
    assert current["support_vote_count"] == 2, (
        "the tally comes back to two, not three — the retracted row must not be "
        f"counted alongside its replacement, got {current['support_vote_count']}"
    )
    assert current["oppose_vote_count"] == 0, (
        f"nobody opposed, got {current['oppose_vote_count']}"
    )
    _counted, counted_meta = validate_paginated(
        api.list_proposal_votes(proposal["id"], ADMIN, {"status": "COUNTED"})
    )
    assert counted_meta["total_count"] == 2, (
        f"exactly two rows stand counted, got {counted_meta['total_count']}"
    )
    _all_rows, all_meta = validate_paginated(
        api.list_proposal_votes(proposal["id"], ADMIN)
    )
    assert all_meta["total_count"] == 3, (
        "the retracted row is kept rather than deleted, got "
        f"{all_meta['total_count']}"
    )
    assert ben_vote["status"] == "COUNTED", (
        f"the other resident's vote was never touched, got {ben_vote['status']}"
    )


def test_closed_outcome_is_identical_to_the_never_retracted_world(api):
    """PRD §3.9: "Otherwise the proposal becomes `ADOPTED` when `support_ratio_bp` has
    reached or passed 5000 basis points — a simple majority of the electorate — **and**
    `support_vote_count` is at least 2, so a single supporter can never adopt a
    proposal however small the electorate."
    PRD §3.9: "Both decided outcomes freeze `eligible_electorate_size` and
    `support_ratio_bp` onto the row and record the acting administrator as
    `decided_by_user_id`; adoption additionally stamps `adopted_at` with the clock
    instant, while rejection leaves `adopted_at` null."

    Design: Difficulty/compensating_invariant/governance_vote_retraction_and_recast_restores_the_support_tally
    """
    _program, ana, ben, proposal = _two_resident_voters_and_a_proposal()
    first_vote = cast_vote(proposal["id"], ana["id"], "SUPPORT")
    cast_vote(proposal["id"], ben["id"], "SUPPORT")
    retract_vote(first_vote["id"], ana["id"])
    cast_vote(proposal["id"], ana["id"], "SUPPORT")

    closed = close_vote(proposal["id"])

    assert_governance_proposal(closed)
    assert closed["eligible_electorate_size"] == 2, (
        f"both residents form the electorate, got {closed['eligible_electorate_size']}"
    )
    assert closed["support_ratio_bp"] == 10000, (
        "two support votes over an electorate of two is 10000 basis points, got "
        f"{closed['support_ratio_bp']}"
    )
    assert closed["status"] == "ADOPTED", (
        f"a unanimous electorate of two adopts, got {closed['status']}"
    )
    assert_instant_equals(closed["adopted_at"], CLOCK_START_INSTANT,
                          "the adopted proposal's adopted_at")
    assert closed["decided_by_user_id"] == USER_IDS["PROGRAM_ADMIN"], (
        f"the closing administrator is recorded, got {closed['decided_by_user_id']}"
    )
    _rows, meta = validate_paginated(
        api.list_youth_governance_votes(ana["id"], ADMIN)
    )
    assert meta["total_count"] == 2, (
        "the retracting youth owns both its rows, got "
        f"{meta['total_count']}"
    )


# ─── Instance: a reversal restores the balance and the lifetime deposit total ───

TLP_PROGRAM = {
    "name": "Northside Transitional Living",
    "licensed_bed_capacity": 3,
    "min_age_years": 16,
    "max_age_years": 20,
    "max_placement_days": 540,
    "savings_match_rate_bp": 2500,
    "required_savings_rate_bp": 2000,
}
ZEV = {
    "legal_first_name": "Zev", "legal_last_name": "Anand",
    "date_of_birth": "2010-03-15", "unaccompanied": True,
}
ZEV_INCOME_CENTS = 90000


def _placement_with_a_good_and_an_erroneous_deposit():
    """A placement carrying a correct 1010-cent deposit followed by a 2000-cent
    deposit posted in error, with the clock left at the start instant so no
    requirement has accrued."""
    return setup_placement_with_deposits(
        [1010, 2000],
        documented_monthly_income_cents=ZEV_INCOME_CENTS,
        tlp_program_overrides=dict(TLP_PROGRAM),
        youth_overrides=dict(ZEV),
    )


def test_reversal_unwinds_both_the_deposit_and_the_match_it_earned(api):
    """PRD §3.8: "`match_component_cents` is the per-entry program match: for a
    `DEPOSIT` it is the entry's `amount_cents` multiplied by the program's
    `savings_match_rate_bp`, divided by 10000 and rounded **half up** to whole cents;
    for a `REVERSAL` it is the exact negation of that same quantity; and for a
    `WITHDRAWAL` it is 0."
    PRD §3.8: "`signed_amount_cents` gives the posting its direction: it is the
    positive `amount_cents` for a `DEPOSIT`, and the negation of `amount_cents` for
    both a `WITHDRAWAL` and a `REVERSAL`."

    Design: Difficulty/compensating_invariant/savings_reversal_restores_placement_balance_and_youth_lifetime_total
    """
    setup = _placement_with_a_good_and_an_erroneous_deposit()
    good, erroneous = setup["entries"]

    assert good["signed_amount_cents"] == 1010, (
        f"the first deposit is positive, got {good['signed_amount_cents']}"
    )
    assert good["match_component_cents"] == 253, (
        "1010 cents at 2500 basis points rounds half up to 253, got "
        f"{good['match_component_cents']}"
    )
    assert good["balance_after_cents"] == 1263, (
        f"1010 plus 253 is 1263, got {good['balance_after_cents']}"
    )
    assert erroneous["match_component_cents"] == 500, (
        f"2000 cents at 2500 basis points is 500, got {erroneous['match_component_cents']}"
    )
    assert erroneous["balance_after_cents"] == 3763, (
        f"1263 plus 2000 plus 500 is 3763, got {erroneous['balance_after_cents']}"
    )

    reversal = post_savings_entry(
        setup["placement"]["id"], "REVERSAL", 2000,
        source_note="reverse the erroneous week 2 posting",
    )

    assert_savings_ledger_entry(reversal)
    assert reversal["signed_amount_cents"] == -2000, (
        f"the reversal negates the amount, got {reversal['signed_amount_cents']}"
    )
    assert reversal["match_component_cents"] == -500, (
        "the reversal also negates the match the deposit earned, got "
        f"{reversal['match_component_cents']}"
    )
    assert reversal["balance_after_cents"] == 1263, (
        "the balance returns to the value it held before the erroneous deposit; "
        f"1763 would mean the match was left behind, got {reversal['balance_after_cents']}"
    )


def test_ledger_keeps_every_row_and_restores_the_lifetime_total(api):
    """PRD §3.8: "Every entry of the placement participates in both sums with no
    status filter of any kind, because entries are immutable and are never excluded."
    PRD §3.8: "The placement's `savings_balance_cents` is the sum of
    `signed_amount_cents` over every entry plus the capped `match_awarded_cents` —
    that identity is the conserved quantity of the account and must hold after every
    posting."
    PRD §3.8: "Posting an entry also recomputes the youth's
    `lifetime_savings_deposited_cents`, which is the sum of `amount_cents` over the
    youth's `DEPOSIT` entries minus the sum of `amount_cents` over the youth's
    `REVERSAL` entries, taken across every placement that youth has ever held; and it
    increments the placement's `version` by one."

    Design: Difficulty/compensating_invariant/savings_reversal_restores_placement_balance_and_youth_lifetime_total
    """
    setup = _placement_with_a_good_and_an_erroneous_deposit()
    post_savings_entry(
        setup["placement"]["id"], "REVERSAL", 2000,
        source_note="reverse the erroneous week 2 posting",
    )

    placement = fetch_placement(setup["placement"]["id"])
    assert_tlp_placement(placement)
    assert placement["savings_balance_cents"] == 1263, (
        f"the placement balance is restored, got {placement['savings_balance_cents']}"
    )
    assert placement["match_awarded_cents"] == 253, (
        "253 plus 500 minus 500 leaves 253 matched cents, got "
        f"{placement['match_awarded_cents']}"
    )
    assert placement["compliance_status"] == "IN_COMPLIANCE", (
        f"nothing was owed yet, got {placement['compliance_status']}"
    )
    entries = savings_entries_of(placement["id"])
    assert len(entries) == 3, (
        f"the immutable ledger keeps all three rows, got {len(entries)}"
    )
    assert_savings_identity(placement, entries)
    youth = fetch_youth(setup["youth"]["id"])
    assert youth["lifetime_savings_deposited_cents"] == 1010, (
        "3010 deposited less 2000 reversed leaves 1010 cents, got "
        f"{youth['lifetime_savings_deposited_cents']}"
    )
