"""Committee decisions, dissent tallying and the issuer appeal cycle."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    assert_rating_decision,
    assert_issuer_appeal,
    decide_payload,
    appeal_payload,
    TEST_USERS,
    fixtures,
)

EM = TEST_USERS["engagement_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CC = TEST_USERS["committee_chair_headers"]
ANON = TEST_USERS["anonymous_headers"]

DISSENT_RATIONALE = (
    "The committee's majority view does not adequately reflect the weakening "
    "free cash flow profile implied by the filed accounts."
)
RESOLUTION_NOTES = (
    "The filed materials introduce information not previously submitted and the "
    "committee will reconsider the grade."
)


def test_internal_decision_weights_a_downgrade_dissent_at_two(api):
    """PRD §3.5: "While the decision remains internal — that is, in `DRAFT` —
    every dissent contributes a weight of 2 regardless of direction."
    PRD §3.5: "each dissent's contribution is its weight multiplied by the
    grade-step distance between that voter's `assigned_grade` and the decision's
    `assigned_grade`"
    PRD §3.5: "The `dissent_count` is simply the number of votes on the committee
    whose `is_dissent` flag is true."

    Design: Difficulty/dual_variant_calc/dissent_score_publication_versus_internal_weighting
    """
    entity, engagement, request, committee, voters, methodology = fixtures.setup_committee_with_voters()
    fixtures.cast_vote(committee["id"], voters[0], vote_value="DOWNGRADE",
                       assigned_grade="B", dissent_rationale=DISSENT_RATIONALE)
    fixtures.cast_vote(committee["id"], voters[1], vote_value="AFFIRM", assigned_grade="BAA")

    decision = fixtures.decide_committee(committee["id"], assigned_grade="BAA")
    assert_rating_decision(decision)
    assert decision["decision_status"] == "DRAFT"
    assert decision["dissent_count"] == 1
    assert decision["dissent_score"] == 4.0


def test_internal_decision_sums_every_dissent_contribution(api):
    """PRD §3.5: "While the decision remains internal — that is, in `DRAFT` —
    every dissent contributes a weight of 2 regardless of direction."
    PRD §3.5: "The `dissent_score` is the sum of those contributions rounded
    half-up to two decimal places"

    Design: Difficulty/dual_variant_calc/dissent_score_publication_versus_internal_weighting
    """
    entity, engagement, request, committee, voters, methodology = fixtures.setup_committee_with_voters()
    fixtures.cast_vote(committee["id"], voters[0], vote_value="DOWNGRADE",
                       assigned_grade="B", dissent_rationale=DISSENT_RATIONALE)
    fixtures.cast_vote(committee["id"], voters[1], vote_value="AFFIRM",
                       assigned_grade="A", dissent_rationale=DISSENT_RATIONALE)

    decision = fixtures.decide_committee(committee["id"], assigned_grade="BAA")
    assert decision["dissent_count"] == 2
    assert decision["dissent_score"] == 6.0


def test_only_grade_divergent_votes_enter_the_dissent_tally(api):
    """PRD §3.5: "The `dissent_count` is simply the number of votes on the
    committee whose `is_dissent` flag is true."
    PRD §3.5: "The `dissent_score` is the sum of those contributions rounded
    half-up to two decimal places"

    Design: Corner/calculations/dissent_score_excludes_abstentions_and_counts_only_dissent_rows
    """
    entity, engagement, request, committee, voters, methodology = fixtures.setup_committee_with_voters()
    fixtures.cast_vote(committee["id"], voters[0], vote_value="DOWNGRADE",
                       assigned_grade="B", dissent_rationale=DISSENT_RATIONALE)
    fixtures.cast_vote(committee["id"], voters[1], vote_value="AFFIRM", assigned_grade="BAA")

    decision = fixtures.decide_committee(committee["id"], assigned_grade="BAA")
    assert decision["dissent_count"] == 1
    assert decision["dissent_score"] == 4.0, "the majority-matching row contributes nothing"


def test_appeal_returns_the_request_to_the_decided_state(api):
    """PRD §3.6: "On `ACCEPTED` three things happen together: the decision returns
    to `DRAFT`, the committee for the request reopens to `IN_SESSION` so a fresh
    decision round begins, and the parent request moves to `APPEALED`."
    PRD §3.5: "the superseded decision moves to `WITHDRAWN`, and the parent
    request returns to `COMMITTEE_DECIDED`"

    Design: Difficulty/non_linear_state_machine/rating_request_cyclic_appeal_loop
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window()

    appeal = get_success_data(api_client.file_appeal(decision["id"], appeal_payload(), ANON))
    assert_issuer_appeal(appeal)
    resolved = get_success_data(api_client.resolve_issuer_appeal(
        appeal["id"], {"appeal_outcome": "ACCEPTED", "resolution_notes": RESOLUTION_NOTES}, CC))
    assert resolved["appeal_outcome"] == "ACCEPTED"

    appealed = get_success_data(api_client.get_rating_request(request["id"], EM))
    assert appealed["request_status"] == "APPEALED"

    get_success_data(api_client.reopen_committee(committee["id"], CC))
    get_success_data(api_client.redecide_committee(
        committee["id"], decide_payload(assigned_grade="BAA", outlook="POSITIVE",
                                        watch_status="WATCH_UPGRADE"), CC))

    redone = get_success_data(api_client.get_rating_request(request["id"], EM))
    assert redone["request_status"] == "COMMITTEE_DECIDED"


def test_an_accepted_appeal_is_recorded_and_reopens_the_round(api):
    """PRD §3.6: "Resolution takes the outcome to `ACCEPTED` or `REJECTED`."
    PRD §3.1: "a decision can be reopened by an accepted appeal and re-decided"

    Design: Difficulty/non_linear_state_machine/rating_request_cyclic_appeal_loop
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window()
    appeal = get_success_data(api_client.file_appeal(decision["id"], appeal_payload(), ANON))
    resolved = get_success_data(api_client.resolve_issuer_appeal(
        appeal["id"], {"appeal_outcome": "ACCEPTED", "resolution_notes": RESOLUTION_NOTES}, CC))

    assert resolved["appeal_outcome"] == "ACCEPTED"
    reopened_decision = get_success_data(api_client.get_rating_decision(decision["id"], EM))
    assert reopened_decision["decision_status"] == "DRAFT"


def test_superseded_decision_withdrawn_and_replacement_issued(api):
    """PRD §3.5: "the superseded decision moves to `WITHDRAWN`, and the parent
    request returns to `COMMITTEE_DECIDED`."
    PRD §3.5: "a fresh `RatingDecision` is created in `DRAFT` with the same
    payload shape as a first decision"

    Design: Difficulty/non_linear_state_machine/rating_decision_cyclic_appeal_roundtrip
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window()
    appeal = get_success_data(api_client.file_appeal(decision["id"], appeal_payload(), ANON))
    get_success_data(api_client.resolve_issuer_appeal(
        appeal["id"], {"appeal_outcome": "ACCEPTED", "resolution_notes": RESOLUTION_NOTES}, CC))

    intermediate = get_success_data(api_client.get_rating_decision(decision["id"], EM))
    assert intermediate["decision_status"] == "DRAFT"

    get_success_data(api_client.reopen_committee(committee["id"], CC))
    replacement = get_success_data(api_client.redecide_committee(
        committee["id"], decide_payload(assigned_grade="BA", outlook="NEGATIVE",
                                        watch_status="WATCH_DOWNGRADE"), CC))

    superseded = get_success_data(api_client.get_rating_decision(decision["id"], EM))
    assert superseded["decision_status"] == "WITHDRAWN"
    assert replacement["decision_status"] == "DRAFT"
    assert replacement["assigned_grade"] == "BA"
    assert replacement["watch_status"] == "WATCH_DOWNGRADE"


def test_replacement_decision_carries_the_re_decided_payload(api):
    """PRD §3.5: "Re-deciding requires the request to be `TEAM_CONFIRMED` on the
    compliance-and-analytical branch, the committee to be `DECIDED` or
    `IN_SESSION`, `quorum_met` to be true, and no outstanding abstention"

    Design: Difficulty/non_linear_state_machine/rating_decision_cyclic_appeal_roundtrip
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window()
    appeal = get_success_data(api_client.file_appeal(decision["id"], appeal_payload(), ANON))
    get_success_data(api_client.resolve_issuer_appeal(
        appeal["id"], {"appeal_outcome": "ACCEPTED", "resolution_notes": RESOLUTION_NOTES}, CC))
    get_success_data(api_client.reopen_committee(committee["id"], CC))
    replacement = get_success_data(api_client.redecide_committee(
        committee["id"], decide_payload(assigned_grade="BA", outlook="NEGATIVE",
                                        watch_status="WATCH_DOWNGRADE"), CC))

    assert_rating_decision(replacement)
    assert replacement["assigned_grade"] == "BA"
    assert replacement["decision_status"] == "DRAFT"
    request_after = get_success_data(api_client.get_rating_request(request["id"], EM))
    assert request_after["request_status"] == "COMMITTEE_DECIDED"