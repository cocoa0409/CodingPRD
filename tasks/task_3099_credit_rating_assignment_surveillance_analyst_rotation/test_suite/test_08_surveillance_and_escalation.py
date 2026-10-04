"""Surveillance cadence, escalation indexing and the posture floor."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    assert_surveillance_review,
    TEST_USERS,
    fixtures,
)

EM = TEST_USERS["engagement_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]


def test_event_driven_review_adds_the_tier_bonus_to_the_overdue_base(api):
    """PRD §3.7: "its base is `overdue_days`, and a `review_type` of
    `EVENT_DRIVEN` adds a tier bonus of 25 while a `PERIODIC` review adds none"
    PRD §3.7: "A scheduled review that passes its due date is swept to `OVERDUE`
    automatically once the logical clock advances beyond its `review_due_at`,
    and its `overdue_days` — defined as the whole-day count since the due date,
    never below zero — is recomputed on read."

    Design: Corner/calculations/escalation_index_event_driven_bonus_is_additive
    """
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", PA))
    methodology = fixtures.create_published_methodology()
    entity = fixtures.create_entity(methodology["id"], legal_name="Delta Paper SA", revenue_band="MID")
    analyst = fixtures.onboard_lead()

    event_review = fixtures.create_review_for_entity(
        entity["id"], analyst, review_type="EVENT_DRIVEN", review_due_at="2026-09-10T00:00:00Z")
    periodic_review = fixtures.create_review_for_entity(
        entity["id"], analyst, review_type="PERIODIC", review_due_at="2026-09-10T00:00:00Z")

    get_success_data(api_client.set_clock("2026-09-20T00:00:00Z", PA))

    event_review = get_success_data(api_client.get_surveillance_review(event_review["id"], EM))
    periodic_review = get_success_data(api_client.get_surveillance_review(periodic_review["id"], EM))
    assert_surveillance_review(event_review)
    assert event_review["overdue_days"] == 10
    assert event_review["escalation_index"] == 35
    assert periodic_review["escalation_index"] == 10


def test_periodic_review_index_equals_its_floored_overdue_days(api):
    """PRD §3.7: "so a periodic review's index equals its overdue days exactly."
    PRD §3.7: "Once `overdue_days` reaches thirty or more, the review is
    escalated to `ESCALATED`"

    Design: Corner/calculations/escalation_index_event_driven_bonus_is_additive
    """
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", PA))
    methodology = fixtures.create_published_methodology()
    entity = fixtures.create_entity(methodology["id"], legal_name="Delta Paper SA", revenue_band="MID")
    analyst = fixtures.onboard_lead()
    periodic_review = fixtures.create_review_for_entity(
        entity["id"], analyst, review_type="PERIODIC", review_due_at="2026-09-10T00:00:00Z")

    get_success_data(api_client.set_clock("2026-09-20T00:00:00Z", PA))

    fetched = get_success_data(api_client.get_surveillance_review(periodic_review["id"], EM))
    assert fetched["overdue_days"] == 10
    assert fetched["escalation_index"] == fetched["overdue_days"]


def test_active_posture_floors_an_open_reviews_escalation_index_at_twenty_five(api):
    """PRD §3.7: "When an issuer's `surveillance_posture` flips to
    `ACTIVE_WATCH`, every open review of that issuer — one whose `review_status`
    is `SCHEDULED`, `OVERDUE`, `ESCALATED` or `IN_PROGRESS` — has its
    `escalation_index` raised to the larger of its current value and 25."
    PRD §3.5: "the issuer's `surveillance_posture` is recomputed from the
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

    reviews_response = api_client.list_surveillance_reviews(EM, {"rated_entity_id": entity["id"]})
    reviews = validate_success(reviews_response, 200)
    assert len(reviews) >= 1
    for review in reviews:
        assert review["escalation_index"] >= 25


def test_the_posture_floor_raises_the_index_of_an_older_open_review(api):
    """PRD §3.7: "every open review of that issuer ... has its
    `escalation_index` raised to the larger of its current value and 25."
    PRD §3.7: "This floor is idempotent: applying it a second time does not
    compound the index."

    Design: Difficulty/transitive_cascade/publication_grade_move_escalation_cascade
    """
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", PA))
    methodology = fixtures.create_published_methodology()
    entity = fixtures.create_entity(methodology["id"], legal_name="Hotel Resorts SA")
    analyst = fixtures.onboard_lead()

    # The review must still be inside its due date so its own overdue-driven
    # escalation leaves its index at zero; only the posture floor may raise it.
    legacy_review = fixtures.create_review_for_entity(
        entity["id"], analyst, review_type="PERIODIC", review_due_at="2026-12-20T00:00:00Z")
    before = get_success_data(api_client.get_surveillance_review(legacy_review["id"], EM))
    assert before["escalation_index"] == 0

    engagement = fixtures.create_engagement(entity["id"])
    request = fixtures.create_request(engagement["id"], entity["id"])
    get_success_data(api_client.open_screening(request["id"], TEST_USERS["compliance_officer_headers"]))
    support = fixtures.onboard_support()
    assignment = fixtures.setup_confirmed_team(request["id"], analyst["id"], support["id"])
    request = get_success_data(api_client.confirm_request_team(
        request["id"], TEST_USERS["compliance_officer_headers"]))
    committee = fixtures.convene_committee(request["id"])
    fixtures.open_session(committee["id"])
    voter_one = fixtures.onboard_committee_member("Dana Okafor")
    voter_two = fixtures.onboard_committee_member("Marek Nowak")
    fixtures.cast_vote(committee["id"], voter_one, vote_value="DOWNGRADE", assigned_grade="BA")
    fixtures.cast_vote(committee["id"], voter_two, vote_value="DOWNGRADE", assigned_grade="BA")
    decision = fixtures.decide_committee(committee["id"], assigned_grade="BA", outlook="NEGATIVE",
                                         watch_status="WATCH_DOWNGRADE")
    decision = get_success_data(api_client.open_appeal_window(
        decision["id"], TEST_USERS["committee_chair_headers"]))
    fixtures.publish_decision(decision["id"], request["id"])

    after = get_success_data(api_client.get_surveillance_review(legacy_review["id"], EM))
    assert after["escalation_index"] == 25