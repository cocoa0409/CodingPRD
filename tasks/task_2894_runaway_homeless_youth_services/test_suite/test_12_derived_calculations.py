"""Derived figures at the exact point where a constant or a filter decides them.

Each case pins one computed field against the boundary that makes it
attributable: the inclusive birthday comparison, the single-overdue posture
clause, the match cap, the first-full-month floor, the retracted-vote filter and
the discharged-admissions-only aggregate.
"""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    WORKER,
    assert_admission,
    assert_census_counts,
    assert_compliance_report,
    assert_governance_proposal,
    assert_governance_vote,
    assert_program_counters,
    assert_savings_identity,
    assert_savings_ledger_entry,
    assert_tlp_placement,
    assert_youth,
    cast_vote,
    clear_screening,
    discharge,
    fetch_admission,
    fetch_placement,
    fetch_program,
    fetch_proposal,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    move_clock,
    notification_of_admission,
    request_admission,
    retract_vote,
    savings_entry_payload,
    setup_proposal_with_electorate,
    setup_tlp_placement,
    validate_paginated,
    validate_success,
    youth_payload,
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
    "savings_match_rate_bp": 2500,
    "required_savings_rate_bp": 2000,
}
PLANNED_DISCHARGE = instant("2026-08-15")
MONTHLY_INCOME_CENTS = 90000


# ─── Instance: the birthday itself counts as the new age ───

ON_BIRTHDAY = {
    "legal_first_name": "OnBirthday",
    "legal_last_name": "Case",
    "date_of_birth": "2010-08-01",
    "unaccompanied": True,
}
DAY_AFTER = {
    "legal_first_name": "DayAfter",
    "legal_last_name": "Case",
    "date_of_birth": "2010-08-02",
    "unaccompanied": True,
}


def test_age_years_treats_the_birthday_itself_as_the_new_age(api):
    """PRD §2.5: "A youth's `age_years` is a whole number of years measured from
    `date_of_birth` to the current logical clock, computed as follows: the youth is
    treated as having already had this year's birthday when the clock's
    month-and-day pair is greater than or equal to the birth date's month-and-day
    pair; the age is then the clock's year minus the birth year, reduced by one when
    this year's birthday has not yet arrived."
    PRD §2.5: "Because the comparison is inclusive, a youth turns the new age on the
    birthday itself rather than the day after, and the result is always floored to
    whole years."
    PRD §2.5: "The clock starts at `2026-08-01T00:00:00Z` and stays there until an
    administrator moves it; the server never falls back to real time for any
    purpose."

    Design: Corner/calculations/youth_age_years_counts_the_birthday_itself
    """
    on_birthday = intake_youth(**dict(ON_BIRTHDAY))

    response = api.create_youth(youth_payload(**dict(DAY_AFTER)), WORKER)
    day_after = validate_success(response, 201)

    assert_youth(day_after)
    assert on_birthday["age_years"] == 16, (
        "a youth born 2010-08-01 has already had this year's birthday at the "
        f"2026-08-01 clock, got {on_birthday['age_years']}"
    )
    assert day_after["age_years"] == 15, (
        "a youth born 2010-08-02 is still a day short of the birthday, got "
        f"{day_after['age_years']}"
    )
    reread = fetch_youth(on_birthday["id"])
    assert reread["age_years"] == 16, (
        f"age_years is recomputed identically on every read, got {reread['age_years']}"
    )


# ─── Instance: one overdue obligation is RESTRICTED, not FROZEN ───

TAM = {
    "legal_first_name": "Tam",
    "legal_last_name": "Okonjo",
    "date_of_birth": "2010-03-15",
    "unaccompanied": True,
}
PAST_DUE_CLOCK = instant("2026-08-03")


def test_a_single_overdue_obligation_restricts_the_program(api):
    """PRD §3.4: "During the nightly census, any obligation in `PENDING` or
    `ATTEMPTED` whose `due_at` lies strictly before the current clock moves to
    `OVERDUE`."
    PRD §3.4: "That transition raises the owning program's
    `overdue_notification_count` by one, which forces the program's `posture` to be
    recomputed — so a single overdue row pushes an otherwise open program to
    `RESTRICTED`, and a second overdue row on the same program drives it to
    `FROZEN`."
    PRD §2.6: "Otherwise the posture is `RESTRICTED` when the utilization has reached
    or passed 9000 basis points — ninety percent of licensed capacity, so a ten-bed
    program with nine beds filled sits at exactly 9000 basis points and is therefore
    `RESTRICTED` — or when the overdue-notification count is exactly one."
    PRD §3.4: "The youth's `risk_posture` is recomputed as well, and stays
    `RESTRICTED`, since an overdue obligation is still an open obligation."
    PRD §3.10: "The epoch answers with a count of the work it did in seven integers:
    `overdue_marked`, `admissions_denied`, `admissions_promoted`,
    `placements_noticed`, `placements_exited`, `cases_closed` and
    `postures_recomputed`."

    Design: Corner/calculations/program_posture_turns_restricted_on_a_single_overdue_notification
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    youth = intake_youth(**dict(TAM))
    clear_screening(youth["id"])
    admission = request_admission(youth["id"], program["id"], PLANNED_DISCHARGE)
    notification = notification_of_admission(admission["id"])
    assert notification["status"] == "PENDING", (
        f"the obligation opens in PENDING, got {notification['status']}"
    )
    move_clock(PAST_DUE_CLOCK)

    census = validate_success(api.run_nightly_census(ADMIN))

    assert_census_counts(census, overdue_marked=1)
    overdue = notification_of_admission(admission["id"])
    assert overdue["status"] == "OVERDUE", (
        f"the obligation fell due on 2026-08-02, got {overdue['status']}"
    )

    current = fetch_program(program["id"])
    assert_program_counters(current)
    assert current["overdue_notification_count"] == 1, (
        f"exactly one obligation is overdue, got {current['overdue_notification_count']}"
    )
    assert current["occupied_beds"] == 1, (
        f"the single stay still holds its bed, got {current['occupied_beds']}"
    )
    assert current["utilization_bp"] == 5000, (
        f"one of two beds is 5000 basis points, got {current['utilization_bp']}"
    )
    assert current["posture"] == "RESTRICTED", (
        "a lone overdue row restricts the program rather than freezing it, got "
        f"{current['posture']}"
    )
    resident = fetch_youth(youth["id"])
    assert resident["risk_posture"] == "RESTRICTED", (
        f"an overdue obligation is still an open obligation, got {resident['risk_posture']}"
    )


# ─── Instance: the awarded match clamps at 50000 cents ───

HANA = {
    "legal_first_name": "Hana",
    "legal_last_name": "Duarte",
    "date_of_birth": "2010-03-15",
    "unaccompanied": True,
}
LARGE_DEPOSIT_CENTS = 400000


def test_awarded_match_clamps_at_the_cap_while_the_entry_keeps_its_raw_component(api):
    """PRD §3.8: "`match_component_cents` is the per-entry program match: for a
    `DEPOSIT` it is the entry's `amount_cents` multiplied by the program's
    `savings_match_rate_bp`, divided by 10000 and rounded **half up** to whole
    cents; for a `REVERSAL` it is the exact negation of that same quantity; and for a
    `WITHDRAWAL` it is 0."
    PRD §3.8: "The placement's `match_awarded_cents` is the sum of
    `match_component_cents` over every entry of the placement, held at a floor of
    zero and capped at 50000 cents, with the cap comparison applied *after* the
    summation and any surplus above the cap never carried forward."
    PRD §3.8: "The placement's `savings_balance_cents` is the sum of
    `signed_amount_cents` over every entry plus the capped `match_awarded_cents` —
    that identity is the conserved quantity of the account and must hold after every
    posting."
    PRD §3.8: "Posting an entry also recomputes the youth's
    `lifetime_savings_deposited_cents`, which is the sum of `amount_cents` over the
    youth's `DEPOSIT` entries minus the sum of `amount_cents` over the youth's
    `REVERSAL` entries, taken across every placement that youth has ever held; and it
    increments the placement's `version` by one."

    Design: Corner/calculations/savings_match_award_clamps_at_the_match_cap
    """
    setup = setup_tlp_placement(
        MONTHLY_INCOME_CENTS,
        shelter_program_overrides=dict(RIVERSIDE),
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides=dict(HANA),
    )
    placement = setup["placement"]

    response = api.create_savings_entry(
        placement["id"],
        savings_entry_payload("DEPOSIT", LARGE_DEPOSIT_CENTS, placement["version"],
                              "settlement payout"),
        COORDINATOR,
    )
    entry = validate_success(response, 201)

    assert_savings_ledger_entry(entry)
    assert entry["match_component_cents"] == 100000, (
        "400000 cents at 2500 basis points is an uncapped per-entry match of "
        f"100000 cents, got {entry['match_component_cents']}"
    )
    assert entry["signed_amount_cents"] == LARGE_DEPOSIT_CENTS, (
        f"a deposit carries its positive magnitude, got {entry['signed_amount_cents']}"
    )
    assert entry["balance_after_cents"] == 450000, (
        "400000 deposited cents plus the capped 50000 matched cents is 450000, got "
        f"{entry['balance_after_cents']}"
    )

    current = fetch_placement(placement["id"])
    assert_tlp_placement(current)
    assert current["match_awarded_cents"] == 50000, (
        f"the awarded match is clamped to the 50000-cent cap, got {current['match_awarded_cents']}"
    )
    assert current["savings_balance_cents"] == 450000, (
        "the surplus above the cap is never carried into the balance, got "
        f"{current['savings_balance_cents']}"
    )
    assert_savings_identity(current, [entry])
    youth = fetch_youth(setup["youth"]["id"])
    assert youth["lifetime_savings_deposited_cents"] == LARGE_DEPOSIT_CENTS, (
        "the lifetime figure sums deposit amounts with no match included, got "
        f"{youth['lifetime_savings_deposited_cents']}"
    )


# ─── Instance: required savings is zero inside the first thirty days ───

INES = {
    "legal_first_name": "Ines",
    "legal_last_name": "Kowalski",
    "date_of_birth": "2010-03-15",
    "unaccompanied": True,
}


def test_required_savings_is_zero_on_the_day_of_placement(api):
    """PRD §3.8: "The number of full elapsed months is `days_elapsed` divided by
    thirty and floored."
    PRD §3.8: "`required_savings_cents` is that monthly requirement multiplied by the
    number of full elapsed months — so a youth in the first thirty days of a
    placement owes nothing at all."
    PRD §3.8: "Three outcomes are possible and they are evaluated as inclusive
    comparisons, so an exactly-met requirement counts as met."
    PRD §3.8: "A balance at or above `required_savings_cents` lands on
    `IN_COMPLIANCE`."
    PRD §3.8: "In short, any review that does not land on `PROBATION` resets the
    consecutive-probation counter to zero, and any review that lands on `PROBATION`
    raises it by one."

    Design: Corner/calculations/required_savings_is_zero_before_the_first_full_month
    """
    setup = setup_tlp_placement(
        MONTHLY_INCOME_CENTS,
        shelter_program_overrides=dict(RIVERSIDE),
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides=dict(INES),
    )
    placement = setup["placement"]

    reviewed = validate_success(api.run_compliance_review(placement["id"], COORDINATOR))

    assert_tlp_placement(reviewed)
    assert reviewed["days_elapsed"] == 0, (
        f"the review runs on the day of placement, got {reviewed['days_elapsed']}"
    )
    assert reviewed["required_savings_cents"] == 0, (
        "a monthly requirement of 18000 cents multiplied by zero full months is "
        f"zero, got {reviewed['required_savings_cents']}"
    )
    assert reviewed["savings_balance_cents"] == 0, (
        f"no savings entry has been posted, got {reviewed['savings_balance_cents']}"
    )
    assert reviewed["compliance_status"] == "IN_COMPLIANCE", (
        "a zero balance is at or above a zero requirement, got "
        f"{reviewed['compliance_status']}"
    )
    assert reviewed["consecutive_probation_reviews"] == 0, (
        "a review that does not land on PROBATION leaves the counter at zero, got "
        f"{reviewed['consecutive_probation_reviews']}"
    )
    assert reviewed["tenancy_status"] == "PLACED", (
        f"a review writes only the compliance dimension, got {reviewed['tenancy_status']}"
    )
    assert reviewed["life_skills_credit_hours"] == 0, (
        f"no curriculum hours are credited, got {reviewed['life_skills_credit_hours']}"
    )
    assert reviewed["allowance_days"] == 540, (
        "the allowance is the 540-day base allowance with no bonus, got "
        f"{reviewed['allowance_days']}"
    )


# ─── Instance: a retracted vote leaves the input set of the tally ───

VOTING_CLOSES_AT = instant("2026-08-20")


def test_close_tally_excludes_the_retracted_vote_and_rejects(api):
    """PRD §3.9: "`support_vote_count` is the number of votes on the proposal whose
    `stance` is `SUPPORT` and whose `status` is `COUNTED`; `oppose_vote_count` is the
    number whose `stance` is `OPPOSE` and whose `status` is `COUNTED`."
    PRD §3.9: "Retracted votes are excluded from both counts."
    PRD §3.9: "`support_ratio_bp` is 0 when the electorate is empty, and otherwise the
    support count multiplied by 10000, divided by the electorate size and floored to
    whole basis points."
    PRD §3.9: "Otherwise the proposal becomes `ADOPTED` when `support_ratio_bp` has
    reached or passed 5000 basis points — a simple majority of the electorate — **and**
    `support_vote_count` is at least 2, so a single supporter can never adopt a
    proposal however small the electorate."
    PRD §3.9: "Otherwise, when either the ratio falls short of 5000 basis points or
    the support count falls short of 2, the proposal becomes `REJECTED`."
    PRD §3.9: "Both decided outcomes freeze `eligible_electorate_size` and
    `support_ratio_bp` onto the row and record the acting administrator as
    `decided_by_user_id`; adoption additionally stamps `adopted_at` with the clock
    instant, while rejection leaves `adopted_at` null."
    PRD §3.9: "Votes can be listed per proposal and per youth, narrowed by `status` in
    both cases."

    Design: Corner/calculations/governance_tally_excludes_retracted_votes_and_flips_the_outcome
    """
    setup = setup_proposal_with_electorate(
        electorate_size=2,
        voting_closes_at=VOTING_CLOSES_AT,
        program_overrides=dict(RIVERSIDE),
    )
    proposal = setup["proposal"]
    first, second = setup["youths"]
    first_vote = cast_vote(proposal["id"], first["id"], "SUPPORT")
    second_vote = cast_vote(proposal["id"], second["id"], "SUPPORT")
    retracted = retract_vote(second_vote["id"], second["id"])
    assert retracted["status"] == "RETRACTED", (
        f"the second youth withdrew her vote, got {retracted['status']}"
    )

    decided = validate_success(api.close_governance_vote(proposal["id"], ADMIN))

    assert_governance_proposal(decided)
    assert decided["eligible_electorate_size"] == 2, (
        "both residents hold an ACTIVE admission at the program, got "
        f"{decided['eligible_electorate_size']}"
    )
    assert decided["support_vote_count"] == 1, (
        f"the retracted vote leaves the support count, got {decided['support_vote_count']}"
    )
    assert decided["oppose_vote_count"] == 0, (
        f"nobody opposed the proposal, got {decided['oppose_vote_count']}"
    )
    assert decided["support_ratio_bp"] == 5000, (
        "one support vote over an electorate of two is 5000 basis points, got "
        f"{decided['support_ratio_bp']}"
    )
    assert decided["status"] == "REJECTED", (
        "the ratio clears the majority but a lone supporter can never adopt, got "
        f"{decided['status']}"
    )
    assert decided["adopted_at"] is None, (
        f"a rejection leaves adopted_at null, got {decided['adopted_at']}"
    )

    frozen = fetch_proposal(proposal["id"])
    assert frozen["support_ratio_bp"] == 5000, (
        f"the ratio is frozen onto the row, got {frozen['support_ratio_bp']}"
    )
    counted, meta = validate_paginated(
        api.list_proposal_votes(proposal["id"], ADMIN, {"status": "COUNTED"})
    )
    assert meta["total_count"] == 1, (
        f"only one vote still stands COUNTED, got {meta['total_count']}"
    )
    assert len(counted) == 1 and counted[0]["id"] == first_vote["id"], (
        f"the surviving vote is the first youth's, got {counted}"
    )
    assert_governance_vote(counted[0])
    assert counted[0]["status"] == "COUNTED", (
        f"the first youth's vote was never retracted, got {counted[0]['status']}"
    )


# ─── Instance: the report aggregates discharged admissions only ───

DARA = {
    "legal_first_name": "Dara",
    "legal_last_name": "Silva",
    "date_of_birth": "2010-03-15",
    "unaccompanied": True,
}
EMIL = {
    "legal_first_name": "Emil",
    "legal_last_name": "Silva",
    "date_of_birth": "2010-04-15",
    "unaccompanied": True,
}
DISCHARGE_CLOCK = instant("2026-08-08", "15:00:00")
SECOND_PLANNED_DISCHARGE = instant("2026-08-20")


def test_report_aggregates_only_the_discharged_admission(api):
    """PRD §3.10: "It aggregates over the program's **discharged admissions only**,
    taken in ascending `created_at` order: admissions in `ACTIVE`, `EXTENDED`,
    `DISCHARGE_SCHEDULED`, `WAITLISTED`, `PENDING_SCREENING` or `DENIED` are excluded
    from every outcome and stay-duration aggregate, and admissions belonging to other
    programs never enter at all."
    PRD §3.10: "`billable_nights_total` is the sum of `final_billable_nights` over
    those discharged admissions."
    PRD §3.10: "`average_stay_nights_bp` is 0 when nothing has been discharged, and
    otherwise the billable-night total multiplied by one hundred, divided by the
    discharged count and floored — so it is nights expressed to two implied decimal
    places, and eight nights over three discharges reports as 266."
    PRD §3.10: "`positive_outcome_rate_bp` is 0 when nothing has been discharged, and
    otherwise the positive-outcome count multiplied by 10000, divided by the
    discharged count and floored to whole basis points."
    PRD §3.10: "`bed_capacity_compliant` is true exactly when the program's
    `occupied_beds` is at or below its `licensed_bed_capacity`."
    PRD §3.10: "The remaining figures are the program's own live fields copied
    straight through: `licensed_bed_capacity`, `occupied_beds`, `waitlisted_count`,
    `utilization_bp`, `posture` and `overdue_notification_count`."
    PRD §3.5: "At discharge it is the number of whole calendar days from the calendar
    date of `admitted_at` to the calendar date of `discharged_at`, plus one further
    night when the hour of the discharge instant is at or after twelve — a youth still
    in the bed at or after 12:00:00Z on the discharge date has occupied that night's
    bed for federal reporting purposes."

    Design: Corner/calculations/federal_compliance_report_counts_only_discharged_admissions
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    leaver = intake_youth(**dict(DARA))
    clear_screening(leaver["id"])
    leaving_admission = request_admission(leaver["id"], program["id"], PLANNED_DISCHARGE)
    stayer = intake_youth(**dict(EMIL))
    clear_screening(stayer["id"])
    request_admission(stayer["id"], program["id"], SECOND_PLANNED_DISCHARGE)
    move_clock(DISCHARGE_CLOCK)
    discharge(leaving_admission["id"], "INDEPENDENT_HOUSING")

    report = validate_success(api.get_compliance_report(program["id"], ADMIN))

    assert_compliance_report(report)
    assert report["discharged_count"] == 1, (
        f"only one of the two stays has ended, got {report['discharged_count']}"
    )
    assert report["billable_nights_total"] == 8, (
        "seven calendar days plus the noon-cutoff night is eight nights, got "
        f"{report['billable_nights_total']}"
    )
    assert report["average_stay_nights_bp"] == 800, (
        "eight nights over one discharge is 800 in implied hundredths, got "
        f"{report['average_stay_nights_bp']}"
    )
    assert report["over_limit_admission_count"] == 0, (
        "eight nights is well inside the 21-night ceiling, got "
        f"{report['over_limit_admission_count']}"
    )
    assert report["positive_outcome_count"] == 1, (
        f"INDEPENDENT_HOUSING is a positive outcome, got {report['positive_outcome_count']}"
    )
    assert report["positive_outcome_rate_bp"] == 10000, (
        "one positive outcome over one discharge is 10000 basis points, got "
        f"{report['positive_outcome_rate_bp']}"
    )
    assert report["occupied_beds"] == 1, (
        f"the still-ACTIVE stay holds the remaining bed, got {report['occupied_beds']}"
    )
    assert report["utilization_bp"] == 5000, (
        f"one of two beds is 5000 basis points, got {report['utilization_bp']}"
    )
    assert report["posture"] == "OPEN", (
        f"the freed bed reopens the program, got {report['posture']}"
    )
    assert report["bed_capacity_compliant"] is True, (
        f"one occupied bed is inside a capacity of two, got {report['bed_capacity_compliant']}"
    )
    assert report["waitlisted_count"] == 0, (
        f"nobody was diverted onto the waitlist, got {report['waitlisted_count']}"
    )
    assert report["overdue_notification_count"] == 0, (
        "the census never ran, so no obligation is overdue, got "
        f"{report['overdue_notification_count']}"
    )
    assert report["waived_notification_count"] == 0, (
        f"no obligation was waived, got {report['waived_notification_count']}"
    )
    assert report["runaway_report_count"] == 0, (
        f"no runaway report was filed, got {report['runaway_report_count']}"
    )


def test_the_still_active_admission_contributes_no_stay_aggregate(api):
    """PRD §3.5: "`final_billable_nights` is the **chronological actual** figure, and
    it is the only one that reaches the federal report."
    PRD §3.5: "It is null until the admission is discharged."
    PRD §3.10: "`discharged_count` is the number of discharged admissions of the
    program."

    Design: Corner/calculations/federal_compliance_report_counts_only_discharged_admissions
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    leaver = intake_youth(**dict(DARA))
    clear_screening(leaver["id"])
    leaving_admission = request_admission(leaver["id"], program["id"], PLANNED_DISCHARGE)
    stayer = intake_youth(**dict(EMIL))
    clear_screening(stayer["id"])
    staying_admission = request_admission(
        stayer["id"], program["id"], SECOND_PLANNED_DISCHARGE
    )
    move_clock(DISCHARGE_CLOCK)
    discharge(leaving_admission["id"], "INDEPENDENT_HOUSING")

    ended = fetch_admission(leaving_admission["id"])
    assert_admission(ended)
    assert ended["final_billable_nights"] == 8, (
        "2026-08-01 to 2026-08-08 is seven calendar days and the 15:00Z discharge "
        f"earns the cutoff night, got {ended['final_billable_nights']}"
    )
    assert ended["outcome_positive"] is True, (
        f"INDEPENDENT_HOUSING is a positive destination, got {ended['outcome_positive']}"
    )
    still_open = fetch_admission(staying_admission["id"])
    assert still_open["status"] == "ACTIVE", (
        f"the second stay is untouched by the first discharge, got {still_open['status']}"
    )
    assert still_open["final_billable_nights"] is None, (
        "an undischarged stay has no chronological-actual figure, got "
        f"{still_open['final_billable_nights']}"
    )
    departed = fetch_youth(leaver["id"])
    assert departed["cumulative_shelter_nights"] == 8, (
        f"the final nights accrue to the youth, got {departed['cumulative_shelter_nights']}"
    )
