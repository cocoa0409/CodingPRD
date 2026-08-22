"""The tally: the frozen snapshot, the two share percentages, the referendum
verdict and the fork certification takes."""

from test_helpers import (
    TEST_USERS,
    assert_pct,
    certify_election,
    read_candidacy,
    read_election,
    read_office,
    read_referendum,
    run_tally,
    setup_frozen_membership_scenario,
    setup_office_share_scenario,
    setup_referendum_on_closed_ballot,
    setup_tallied_two_candidate_race,
    validate_success,
)

COMMISSIONER = TEST_USERS["commissioner_headers"]
ADVISOR = TEST_USERS["advisor_headers"]


# ─── The two share percentages ────────────────────────────────────────────────

def test_the_provisional_share_counts_abstentions_and_invalidated_ballots(api):
    """PRD §3.8: "The denominator common to the office is its `valid_votes_count` plus its
    `abstain_votes_count` plus its `invalidated_votes_count`. The **provisional** share,
    `provisional_share_pct`, is one hundred multiplied by the candidacy's `raw_votes_count`
    divided by that full denominator, rounded half up to two decimal places, and is 0.00
    when that denominator is zero; because it counts abstentions and invalidated ballots in
    the denominator and uses raw votes on top, a disqualified candidacy still shows a
    non-zero provisional share."
    PRD §3.8: "The office's `abstain_votes_count` is the number of those votes whose mark
    for the office carries a null candidacy. The office's `invalidated_votes_count` is the
    total of `raw_votes_count` across the candidacies that step four disqualified."

    Design: Difficulty/dual_variant_calc/office_share_provisional_versus_certified_denominator
    """
    scenario = setup_office_share_scenario()

    run_tally(scenario["election"]["id"])

    office = read_office(scenario["office"]["id"])
    assert office["abstain_votes_count"] == 1
    assert office["invalidated_votes_count"] == 1
    assert office["valid_votes_count"] == 3, (
        f"five ballots less one abstention less one invalidated, got "
        f"{office['valid_votes_count']}"
    )

    leader = read_candidacy(scenario["leader"]["id"])
    runner_up = read_candidacy(scenario["runner_up"]["id"])
    respondent = read_candidacy(scenario["respondent"]["id"])

    assert leader["raw_votes_count"] == 2
    assert_pct(leader["provisional_share_pct"], 40.00, "leader provisional_share_pct")
    assert_pct(runner_up["provisional_share_pct"], 20.00, "runner-up provisional_share_pct")
    assert_pct(respondent["provisional_share_pct"], 20.00, (
        "the disqualified candidacy still shows a non-zero provisional share"
    ))

    election = read_election(scenario["election"]["id"])
    assert election["eligible_voter_count"] == 8
    assert_pct(election["turnout_pct"], 62.50, "turnout_pct")


def test_the_certified_share_excludes_abstentions_and_decides_the_office(api):
    """PRD §3.8: "The **certified** share, `certified_share_pct`, is one hundred multiplied
    by the candidacy's `certified_votes_count` divided by the office's `valid_votes_count`
    alone, rounded half up to two decimal places, and is 0.00 when `valid_votes_count` is
    zero."
    PRD §3.8: "And each candidacy's `certified_votes_count` is zero when that candidacy is
    `DISQUALIFIED`, and otherwise equals its `raw_votes_count`."
    PRD §3.8: "If that leader's `certified_share_pct` has reached the election's
    `runoff_threshold_pct`, compared as "at least", the office's `status` becomes `DECIDED`
    and the top candidacies by rank, as many as the office's `seat_count`, are its
    winners."

    Design: Difficulty/dual_variant_calc/office_share_provisional_versus_certified_denominator
    """
    scenario = setup_office_share_scenario()

    run_tally(scenario["election"]["id"])

    leader = read_candidacy(scenario["leader"]["id"])
    runner_up = read_candidacy(scenario["runner_up"]["id"])
    respondent = read_candidacy(scenario["respondent"]["id"])

    assert respondent["status"] == "DISQUALIFIED"
    assert respondent["certified_votes_count"] == 0
    assert_pct(respondent["certified_share_pct"], 0.00, "respondent certified_share_pct")
    assert_pct(leader["certified_share_pct"], 66.67, "leader certified_share_pct")
    assert_pct(runner_up["certified_share_pct"], 33.33, "runner-up certified_share_pct")
    assert leader["certified_share_pct"] > leader["provisional_share_pct"], (
        "the narrower denominator yields a strictly larger certified share"
    )

    assert read_office(scenario["office"]["id"])["status"] == "DECIDED"
    assert read_election(scenario["election"]["id"])["runoff_required_office_count"] == 0


# ─── The frozen slate snapshot ────────────────────────────────────────────────

def test_the_snapshot_keeps_the_member_that_step_four_disqualifies(api):
    """PRD §3.8: "**Step one — freeze slate membership.** Take the ballot of this election
    whose `round` equals the election's `current_round`; its `locked_at` is the snapshot
    instant. For every candidacy that stood in `ON_BALLOT` at that instant, determine its
    slate root: the `slate_leader_candidacy_id` it carried at `locked_at`, or its own
    identifier if it carried none."
    PRD §3.8: "This list is written once and never re-derived, no matter what later steps
    do."

    Design: Difficulty/combinatorial_formula/certification_step_order_breaks_circular_dependency
    """
    scenario = setup_frozen_membership_scenario()

    run_tally(scenario["election"]["id"])

    disqualified = read_candidacy(scenario["member_two"]["id"])
    assert disqualified["status"] == "DISQUALIFIED"
    assert disqualified["penalty_points_total"] == 100, (
        f"40 plus 40 times 1.5, got {disqualified['penalty_points_total']}"
    )

    leader = read_candidacy(scenario["leader"]["id"])
    assert len(leader["slate_snapshot_member_ids"]) == 3, (
        "the snapshot is taken from the lock instant, before any disqualification, got "
        f"{leader['slate_snapshot_member_ids']}"
    )
    assert scenario["member_two"]["id"] in leader["slate_snapshot_member_ids"]


def test_the_shared_line_still_splits_three_ways_after_the_sweep(api):
    """PRD §3.8: "**Step four — the disqualification sweep.** Every candidacy still in
    `ON_BALLOT` whose recomputed `penalty_points_total` has reached sixty moves
    `ON_BALLOT → DISQUALIFIED`, processed in ascending `created_at` order. Membership from
    step one is not re-derived and step two is not re-run, even though the sweep changes
    who remains on the ballot — that is the whole point of freezing."
    PRD §3.4: "For each line, divide its `amount_cents` by the member count and round half
    up to a whole number of cents to obtain the per-member charge; subtract the per-member
    charge multiplied by the member count from the line amount to obtain a remainder, which
    may be negative."

    Design: Difficulty/combinatorial_formula/certification_step_order_breaks_circular_dependency
    """
    scenario = setup_frozen_membership_scenario()

    run_tally(scenario["election"]["id"])

    leader = read_candidacy(scenario["leader"]["id"])
    member_one = read_candidacy(scenario["member_one"]["id"])
    member_two = read_candidacy(scenario["member_two"]["id"])

    assert member_one["spending_final_cents"] == 3_333, (
        "the frozen three-member split, got "
        f"{member_one['spending_final_cents']}"
    )
    assert member_one["spending_final_cents"] != 5_000, (
        "re-deriving membership after the sweep would split the line two ways"
    )
    assert leader["spending_final_cents"] == 3_334, (
        f"the earliest-created member bears the remainder, got "
        f"{leader['spending_final_cents']}"
    )
    assert member_two["spending_final_cents"] == 3_333, (
        "the disqualified member is still charged its frozen share"
    )


# ─── The referendum's two axes ────────────────────────────────────────────────

def test_the_two_referendum_axes_advance_independently(api):
    """PRD §3.6: "A referendum carries two entirely independent status axes. Its
    `drafting_status` — how far the text has travelled toward the ballot — starts at
    `DRAFT`, and its `outcome_status` — how the electorate decided it — starts at `PENDING`
    and stays there until the tally."
    PRD §3.6: "and every referenced referendum moves its `drafting_status`
    `APPROVED_FOR_BALLOT → ON_BALLOT`, which is terminal on that axis."
    PRD §3.8: "otherwise, if `approval_pct` has reached `approval_threshold_pct`, compared
    as "at least", `outcome_status` moves `PENDING → PASSED`; otherwise `outcome_status`
    moves `PENDING → FAILED`."

    Design: Difficulty/non_linear_state_machine/referendum_two_axes_advance_independently
    """
    scenario = setup_referendum_on_closed_ballot(
        approval_threshold_pct=66.67,
        voter_choices=("YES", "YES", "YES", "NO"),
        redraft=True,
    )

    before = read_referendum(scenario["referendum"]["id"])
    assert before["drafting_status"] == "ON_BALLOT", (
        "the drafting axis has travelled DRAFT, SUBMITTED, RETURNED, SUBMITTED, "
        f"APPROVED_FOR_BALLOT and ON_BALLOT, got {before['drafting_status']}"
    )
    assert before["outcome_status"] == "PENDING", (
        f"the outcome axis stays PENDING until the tally, got {before['outcome_status']}"
    )

    run_tally(scenario["election"]["id"])

    after = read_referendum(scenario["referendum"]["id"])
    assert after["outcome_status"] == "PASSED"
    assert after["drafting_status"] == "ON_BALLOT", (
        "the drafting axis is untouched by the tally"
    )


def test_the_referendum_verdict_reads_only_the_decisive_votes(api):
    """PRD §3.8: "For each referendum on the ballot, `yes_votes_count`, `no_votes_count`
    and `abstain_votes_count` are the numbers of cast votes of the current round whose
    `selections` carry a mark for that referendum with `choice` `YES`, `NO` and `ABSTAIN`
    respectively. The decisive total is the yes count plus the no count; abstentions are
    deliberately excluded."
    PRD §3.8: "`approval_pct` is one hundred multiplied by the yes count divided by the
    decisive total, rounded half up to two decimal places, and is 0.00 when the decisive
    total is zero."
    PRD §3.7: "Opening the polls for round 1, and only for round 1, freezes the size of the
    electorate."

    Design: Difficulty/non_linear_state_machine/referendum_two_axes_advance_independently
    """
    scenario = setup_referendum_on_closed_ballot(
        approval_threshold_pct=66.67,
        voter_choices=("YES", "YES", "YES", "NO"),
        redraft=True,
    )

    run_tally(scenario["election"]["id"])

    referendum = read_referendum(scenario["referendum"]["id"])
    assert referendum["yes_votes_count"] == 3
    assert referendum["no_votes_count"] == 1
    assert referendum["abstain_votes_count"] == 0
    assert_pct(referendum["approval_pct"], 75.00, "approval_pct")

    election = read_election(scenario["election"]["id"])
    assert election["eligible_voter_count"] == 5
    assert_pct(election["turnout_pct"], 80.00, "turnout_pct")
    assert read_office(scenario["office"]["id"])["valid_votes_count"] == 0, (
        "no ballot carried a mark for the seat"
    )


def test_quorum_is_measured_before_the_approval_threshold(api):
    """PRD §3.8: "The verdict is then decided in this order: if the election's
    `turnout_pct` is strictly below its `quorum_pct`, `outcome_status` moves
    `PENDING → QUORUM_NOT_MET` — note that quorum is measured on overall election turnout,
    counting every cast ballot rather than only the ones that marked this referendum;
    otherwise, if the decisive total is zero, `outcome_status` moves `PENDING → FAILED`;
    otherwise, if `approval_pct` has reached `approval_threshold_pct`, compared as "at
    least", `outcome_status` moves `PENDING → PASSED`; otherwise `outcome_status` moves
    `PENDING → FAILED`."

    Design: Corner/state_machines/referendum_outcome_quorum_not_met_overrides_unanimous_approval
    """
    scenario = setup_referendum_on_closed_ballot(
        election_overrides={"quorum_pct": 60.00},
        office_overrides={"eligible_class_years": ["SENIOR"]},
        approval_threshold_pct=66.67,
        voter_choices=("YES",),
        voter_count=3,
        voter_class_years=["SENIOR"],
    )

    run_tally(scenario["election"]["id"])

    election = read_election(scenario["election"]["id"])
    assert election["eligible_voter_count"] == 4
    assert election["ballots_cast_count"] == 1
    assert_pct(election["turnout_pct"], 25.00, "turnout_pct")

    referendum = read_referendum(scenario["referendum"]["id"])
    assert referendum["yes_votes_count"] == 1
    assert referendum["no_votes_count"] == 0
    assert_pct(referendum["approval_pct"], 100.00, "approval_pct")
    assert referendum["outcome_status"] == "QUORUM_NOT_MET", (
        "the quorum gate is evaluated before the approval threshold, got "
        f"{referendum['outcome_status']}"
    )
    assert referendum["drafting_status"] == "ON_BALLOT"


# ─── The certification fork ───────────────────────────────────────────────────

def test_a_leader_short_of_the_threshold_schedules_a_runoff(api):
    """PRD §3.8: "Otherwise the office's `status` becomes `RUNOFF_REQUIRED`, and its
    qualifiers are the top candidacies by rank numbering one more than `seat_count`, plus
    every further candidacy whose `certified_votes_count` equals that of the last of them —
    ties all advance."
    PRD §3.8: "When `runoff_required_office_count` is at least one, the same act instead
    moves the election `TALLYING → RUNOFF_SCHEDULED`, and the side effects diverge
    sharply."
    PRD §3.8: "No officer transition is opened by this arm, and — this is the critical
    asymmetry — neither `certified_by_user_id` nor `certified_at` is stamped, because
    nothing has been certified yet."

    Design: Corner/state_machines/certify_fork_arm_b_schedules_runoff_without_certification_identity
    """
    scenario = setup_tallied_two_candidate_race(
        election_overrides={"runoff_threshold_pct": 70.00}
    )

    certified = validate_success(api.certify(scenario["election"]["id"], ADVISOR))

    first = read_candidacy(scenario["first_candidacy"]["id"])
    second = read_candidacy(scenario["second_candidacy"]["id"])
    assert_pct(first["certified_share_pct"], 66.67, "leader certified_share_pct")
    assert_pct(second["certified_share_pct"], 33.33, "runner-up certified_share_pct")
    assert read_office(scenario["office"]["id"])["valid_votes_count"] == 3
    assert read_office(scenario["office"]["id"])["status"] == "RUNOFF_REQUIRED"

    assert certified["status"] == "RUNOFF_SCHEDULED"
    assert certified["runoff_required_office_count"] == 1
    assert certified["certified_by_user_id"] is None, (
        "nothing has been certified yet, so no identity is stamped"
    )
    assert certified["certified_at"] is None
    assert first["status"] == "RUNOFF_QUALIFIED"
    assert second["status"] == "RUNOFF_QUALIFIED"
    assert first["transition_status"] == "NOT_APPLICABLE", (
        "this arm opens no officer transition"
    )


def test_a_share_landing_exactly_on_the_threshold_decides_the_seat(api):
    """PRD §3.8: "If that leader's `certified_share_pct` has reached the election's
    `runoff_threshold_pct`, compared as "at least", the office's `status` becomes
    `DECIDED` and the top candidacies by rank, as many as the office's `seat_count`, are
    its winners."
    PRD §3.8: "Candidacies are ranked within an office by `certified_votes_count`
    descending, then — as the first tie-break — `petition_signature_valid_count`
    descending, then `created_at` ascending."
    PRD §3.8: "Every remaining candidacy on that office's ballot moves
    `ON_BALLOT → ELIMINATED`."

    Design: Corner/calculations/runoff_threshold_exact_equality_decides_office_and_tie_break_orders_winners
    """
    scenario = setup_tallied_two_candidate_race(
        office_overrides={"eligible_class_years": ["FRESHMAN", "SENIOR"]},
        candidate_students=[
            {"full_name": "Ava Stone", "class_year": "SENIOR", "gpa": 3.50,
             "credits_completed": 95},
            {"full_name": "Ben Lu", "class_year": "SENIOR", "gpa": 3.20,
             "credits_completed": 90},
        ],
        voter_class_years=["FRESHMAN"],
        first_votes=1,
        second_votes=1,
    )

    certified = certify_election(scenario["election"]["id"])

    first = read_candidacy(scenario["first_candidacy"]["id"])
    second = read_candidacy(scenario["second_candidacy"]["id"])
    office = read_office(scenario["office"]["id"])

    assert_pct(first["certified_share_pct"], 50.00, "first certified_share_pct")
    assert_pct(second["certified_share_pct"], 50.00, "second certified_share_pct")
    assert office["valid_votes_count"] == 2
    assert office["status"] == "DECIDED", (
        f"50.00 has reached the 50.00 threshold, got {office['status']}"
    )
    assert certified["runoff_required_office_count"] == 0
    assert certified["status"] == "CERTIFIED"
    assert first["status"] == "ELECTED", (
        "the tie is broken by created_at ascending, so the earlier filing wins"
    )
    assert second["status"] == "ELIMINATED"
    assert office["filled_seat_count"] == 1
