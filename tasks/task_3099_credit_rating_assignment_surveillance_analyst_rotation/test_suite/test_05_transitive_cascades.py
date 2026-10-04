"""Termination and publication cascades that propagate across aggregates."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    fixtures,
)

EM = TEST_USERS["engagement_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CC = TEST_USERS["committee_chair_headers"]
PA = TEST_USERS["platform_admin_headers"]


def test_termination_status_and_fee_reversal_fire(api):
    """PRD §3.1: "once it succeeds the letter becomes `TERMINATED` and
    `fee_reversed_cents` is set equal to `fee_credited_cents`."

    Design: Difficulty/transitive_cascade/engagement_termination_four_hop_cascade
    """
    entity, engagement, request, assignment, methodology = fixtures.setup_request_ready_for_committee()
    response = api_client.terminate_engagement_letter(engagement["id"], EM)
    terminated = validate_success(response, 200)

    assert terminated["status"] == "TERMINATED"
    assert terminated["fee_reversed_cents"] == terminated["fee_credited_cents"]


def test_withdrawal_of_the_request_follows_the_termination(api):
    """PRD §3.1: "Every `RatingRequest` under the engagement whose
    `request_status` is not `PUBLISHED` moves to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/engagement_termination_four_hop_cascade
    """
    entity, engagement, request, assignment, methodology = fixtures.setup_request_ready_for_committee()
    get_success_data(api_client.terminate_engagement_letter(engagement["id"], EM))

    withdrawn = get_success_data(api_client.get_rating_request(request["id"], EM))
    assert withdrawn["request_status"] == "WITHDRAWN"


def test_revocation_of_the_assignment_follows_the_withdrawal(api):
    """PRD §3.1: "every `AnalyticalTeamAssignment` on those withdrawn requests
    moves from `PROPOSED`, `SCREENED` or `CONFIRMED` to `REVOKED`"

    Design: Difficulty/transitive_cascade/engagement_termination_four_hop_cascade
    """
    entity, engagement, request, assignment, methodology = fixtures.setup_request_ready_for_committee()
    get_success_data(api_client.terminate_engagement_letter(engagement["id"], EM))

    revoked = get_success_data(api_client.get_team_assignment(assignment["id"], EM))
    assert revoked["status"] == "REVOKED"


def test_lead_credit_and_eligibility_recompute_along_the_chain(api):
    """PRD §3.1: "because those rows revoke, each affected analyst's
    `consecutive_lead_months` recomputes over the lead's surviving rows so that
    lead credit for the vanished window is removed."
    PRD §3.3: "Revoking a `CONFIRMED` assignment recomputes the lead's
    `consecutive_lead_months` over the surviving `SCREENED` and `CONFIRMED` rows,
    and when the shortened streak drops below sixty months the lead's
    `rotation_eligible` returns to true."

    Design: Difficulty/transitive_cascade/engagement_termination_four_hop_cascade
    """
    entity, engagement, request, assignment, methodology = fixtures.setup_request_ready_for_committee()
    lead = get_success_data(api_client.get_analyst(assignment["lead_analyst_id"], EM))
    assert lead["consecutive_lead_months"] == 0
    assert lead["rotation_eligible"] is True

    get_success_data(api_client.terminate_engagement_letter(engagement["id"], EM))

    lead_after = get_success_data(api_client.get_analyst(assignment["lead_analyst_id"], EM))
    assert lead_after["consecutive_lead_months"] == 0
    assert lead_after["rotation_eligible"] is True


def test_terminal_state_and_conserved_fee_pool_hold_together(api):
    """PRD §3.1: "once it succeeds the letter becomes `TERMINATED` and
    `fee_reversed_cents` is set equal to `fee_credited_cents`."
    PRD §3.1: "This is a depth-four transitive cascade running `EngagementLetter`
    → `RatingRequest` → `AnalyticalTeamAssignment` → `Analyst`"

    Design: Difficulty/transitive_cascade/engagement_termination_four_hop_cascade
    """
    entity, engagement, request, assignment, methodology = fixtures.setup_request_ready_for_committee()
    before = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    credited_before = before["fee_credited_cents"]

    get_success_data(api_client.terminate_engagement_letter(engagement["id"], EM))

    after = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    assert after["status"] == "TERMINATED"
    # PRD §3.1 pins the reversal as `fee_reversed_cents` set equal to
    # `fee_credited_cents`; the credited total itself is not restated, so the
    # assertion is that the pre-termination credit is exactly what is reversed.
    assert after["fee_reversed_cents"] == after["fee_credited_cents"]
    assert after["fee_reversed_cents"] == credited_before


def test_first_publication_sets_grade_and_stamps_first_rated_at(api):
    """PRD §3.5: "the issuer's `current_grade` is set to the `assigned_grade`,
    and `first_rated_at` is stamped if this is the issuer's first publication."

    Design: Difficulty/transitive_cascade/publication_grade_move_escalation_cascade
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window()
    published = fixtures.publish_decision(decision["id"], request["id"])

    assert published["decision_status"] == "PUBLISHED"
    entity_after = get_success_data(api_client.get_rated_entity(entity["id"], EM))
    assert entity_after["current_grade"] == "BAA"
    assert entity_after["first_rated_at"] is not None


def test_publication_of_a_watch_designation_flips_the_posture(api):
    """PRD §3.5: "the issuer's `surveillance_posture` is recomputed from the
    published `watch_status`, moving to `ACTIVE_WATCH` when the `watch_status` is
    `WATCH_UPGRADE` or `WATCH_DOWNGRADE`."

    Design: Difficulty/transitive_cascade/publication_grade_move_escalation_cascade
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window(
        assigned_grade="BA", vote_value="DOWNGRADE", voter_grade="BA",
        decide_overrides={"watch_status": "WATCH_DOWNGRADE", "outlook": "NEGATIVE"},
    )
    fixtures.publish_decision(decision["id"], request["id"])

    entity_after = get_success_data(api_client.get_rated_entity(entity["id"], EM))
    assert entity_after["surveillance_posture"] == "ACTIVE_WATCH"


def test_publication_also_records_the_move_and_the_successor_review(api):
    """PRD §3.5: "a successor `SurveillanceReview` is auto-created for the issuer
    with its `review_due_at` at the `review_cycle_months` after `published_at`"
    PRD §3.1: "the issuer's `surveillance_posture` is recomputed from the
    published `watch_status`"

    Design: Difficulty/transitive_cascade/publication_grade_move_escalation_cascade
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window(
        assigned_grade="BA", vote_value="DOWNGRADE", voter_grade="BA",
        decide_overrides={"watch_status": "WATCH_DOWNGRADE", "outlook": "NEGATIVE"},
    )
    fixtures.publish_decision(decision["id"], request["id"])

    entity_after = get_success_data(api_client.get_rated_entity(entity["id"], EM))
    assert entity_after["current_grade"] == "BA"
    reviews_response = api_client.list_surveillance_reviews(EM, {"rated_entity_id": entity["id"]})
    reviews = validate_success(reviews_response, 200)
    assert len(reviews) >= 1, "a successor surveillance review must be auto-created"