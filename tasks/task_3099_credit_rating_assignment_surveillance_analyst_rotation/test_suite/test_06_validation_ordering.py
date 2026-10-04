"""Validation ordering across error categories."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    methodology_payload,
    rated_entity_payload,
    engagement_letter_payload,
    rating_request_payload,
    analyst_payload,
    team_assignment_payload,
    conflict_screening_payload,
    compensation_payload,
    decide_payload,
    TEST_USERS,
    fixtures,
)

EM = TEST_USERS["engagement_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CC = TEST_USERS["committee_chair_headers"]
COMP = TEST_USERS["compensation_committee_headers"]
PA = TEST_USERS["platform_admin_headers"]

RATIONALE = (
    "The issuer is assigned this grade on the strength of a diversified operating "
    "base, resilient cash generation and leverage comfortably inside the sector "
    "band; the outlook reflects the committee's forward view and no watch "
    "designation is applied at this session."
)


def test_screen_reports_the_methodology_gate_before_the_conflict_gate(api):
    """PRD §3.3: "The screen first confirms that the request's issuer is pinned to
    a `PUBLISHED` methodology, because that gate must run before any analyst
    conflict check; a stale or draft pin yields `ERR_METHODOLOGY_NOT_PUBLISHED`
    (HTTP 409)."
    PRD §3.3: "its checks are evaluated in a fixed order so that an earlier
    failure is not masked by a later one."

    Design: Difficulty/priority_pair_validation_conflict/screen_conflict_business_safety_before_business_constraint
    """
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", PA))
    draft_methodology = get_success_data(api_client.create_methodology(methodology_payload(), CO))
    entity = get_success_data(api_client.create_rated_entity(
        rated_entity_payload(draft_methodology["id"], legal_name="India Cement Ltd",
                             domicile_country="IN", revenue_band="MID"), EM))
    engagement = get_success_data(api_client.create_engagement_letter(
        engagement_letter_payload(entity["id"]), EM))
    get_success_data(api_client.submit_engagement_letter(engagement["id"], EM))
    get_success_data(api_client.set_clock("2026-12-15T00:00:00Z", PA))
    get_success_data(api_client.activate_engagement_letter(engagement["id"], EM))
    request = get_success_data(api_client.create_rating_request(
        rating_request_payload(engagement["id"], entity["id"]), EM))

    lead = get_success_data(api_client.create_analyst(analyst_payload(), CO))
    support = get_success_data(api_client.create_analyst(
        analyst_payload(full_name="Tomas Beck", analyst_tier="SUPPORT"), CO))
    assignment = get_success_data(api_client.create_team_assignment(
        team_assignment_payload(request["id"], lead["id"], support["id"]), CC))
    get_success_data(api_client.create_conflict_screening(
        conflict_screening_payload(assignment["id"], lead["id"],
                                   conflict_type="PRIOR_EMPLOYMENT",
                                   screening_result="DISQUALIFYING"), CO))

    response = api_client.screen_team_assignment(assignment["id"], CO)
    validate_error(response, ApiErrorId.ERR_METHODOLOGY_NOT_PUBLISHED, 409)

    unchanged = get_success_data(api_client.get_team_assignment(assignment["id"], EM))
    assert unchanged["status"] == "PROPOSED"


def test_disqualifying_conflict_surfaces_when_the_methodology_is_published(api):
    """PRD §3.3: "Each of the lead and the support must have at least one
    `ConflictScreening` row whose `screening_result` is not `DISQUALIFYING`, or
    the screen is rejected with `ERR_CONFLICT_SCREENING_DISQUALIFYING`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/screen_conflict_business_safety_before_business_constraint
    """
    entity, engagement, methodology = fixtures.setup_rated_entity_with_active_engagement()
    request = fixtures.create_request(engagement["id"], entity["id"])
    lead = fixtures.onboard_lead()
    support = fixtures.onboard_support()
    assignment = fixtures.propose_team(request["id"], lead["id"], support["id"])
    fixtures.record_screening(assignment["id"], lead["id"],
                              conflict_type="PRIOR_EMPLOYMENT", screening_result="DISQUALIFYING")

    response = api_client.screen_team_assignment(assignment["id"], CO)
    validate_error(response, ApiErrorId.ERR_CONFLICT_SCREENING_DISQUALIFYING, 409)


def test_second_approval_of_a_compensation_record_hits_the_state_guard(api):
    """PRD §3.9: "the record begins in `DRAFT` with `fee_generation_bonus_cents`
    pinned at zero. Approving a record requires the analyst to hold no
    `CONFIRMED` team assignment in the current `comp_period`"
    PRD §2.4: "an action endpoint whose target resource is not in the state the
    transition requires is rejected with the generic `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/approve_conflict_state_before_business_fiscal
    """
    entity, engagement, request, assignment, methodology = fixtures.setup_request_ready_for_committee()
    lead = get_success_data(api_client.get_analyst(assignment["lead_analyst_id"], EM))
    record = get_success_data(api_client.create_compensation_record(
        compensation_payload(lead["id"]), COMP))
    approved = get_success_data(api_client.approve_compensation_record(record["id"], COMP))
    assert approved["status"] == "APPROVED"

    response = api_client.approve_compensation_record(record["id"], COMP)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_second_approval_leaves_the_approved_record_untouched(api):
    """PRD §2.4: "only after that guard passes are the transition-specific
    business rules evaluated."
    PRD §3.9: "Approval computes an `accuracy_bonus_cents` and holds
    `fee_generation_bonus_cents` at zero"

    Design: Difficulty/priority_pair_validation_conflict/approve_conflict_state_before_business_fiscal
    """
    entity, engagement, request, assignment, methodology = fixtures.setup_request_ready_for_committee()
    lead = get_success_data(api_client.get_analyst(assignment["lead_analyst_id"], EM))
    record = get_success_data(api_client.create_compensation_record(
        compensation_payload(lead["id"]), COMP))
    before = get_success_data(api_client.approve_compensation_record(record["id"], COMP))

    api_client.approve_compensation_record(record["id"], COMP)

    after = get_success_data(api_client.get_compensation_record(record["id"], EM))
    assert after["status"] == "APPROVED"
    assert after["total_compensation_cents"] == before["total_compensation_cents"]


def test_quorum_blocks_a_decision_until_the_required_member_count_is_reached(api):
    """PRD §3.4: "it carries a `quorum_met` flag that is true only once
    `votes_cast` has reached `required_voting_members`."
    PRD §3.5: "requires `quorum_met` to be true, or it is rejected with
    `ERR_COMMITTEE_QUORUM_NOT_MET` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/committee_quorum_at_exactly_required_members
    """
    entity, engagement, request, committee, voters, methodology = fixtures.setup_committee_with_voters(
        required_voting_members=2
    )
    fixtures.cast_vote(committee["id"], voters[0], vote_value="AFFIRM", assigned_grade="BAA")

    short = api_client.decide_committee(committee["id"], decide_payload(), CC)
    validate_error(short, ApiErrorId.ERR_COMMITTEE_QUORUM_NOT_MET, 409)

    under = get_success_data(api_client.get_rating_committee(committee["id"], EM))
    assert under["votes_cast"] == 1
    assert under["quorum_met"] is False


def test_exactly_the_required_member_count_is_enough_to_decide(api):
    """PRD §3.4: "it carries a `quorum_met` flag that is true only once
    `votes_cast` has reached `required_voting_members`."
    PRD §3.5: "A successful decision creates a `RatingDecision` in `DRAFT` and
    moves the committee to `DECIDED` and the parent request to
    `COMMITTEE_DECIDED`."

    Design: Difficulty/boundary_precision_check/committee_quorum_at_exactly_required_members
    """
    entity, engagement, request, committee, voters, methodology = fixtures.setup_committee_with_voters(
        required_voting_members=2
    )
    fixtures.cast_vote(committee["id"], voters[0], vote_value="AFFIRM", assigned_grade="BAA")
    fixtures.cast_vote(committee["id"], voters[1], vote_value="AFFIRM", assigned_grade="BAA")

    at_quorum = get_success_data(api_client.get_rating_committee(committee["id"], EM))
    assert at_quorum["votes_cast"] == 2
    assert at_quorum["quorum_met"] is True

    decided = get_success_data(api_client.decide_committee(committee["id"], decide_payload(), CC))
    assert decided["decision_status"] == "DRAFT"
    assert decided["assigned_grade"] == "BAA"


def test_zero_fee_engagement_is_accepted_while_a_negative_fee_is_rejected(api):
    """PRD §3.1: "The `fee_amount_cents` must be a non-negative integer; a
    negative amount is rejected with `ERR_FEE_AMOUNT_NEGATIVE` (HTTP 400)."

    Design: Difficulty/boundary_precision_check/fee_amount_zero_versus_negative_boundary
    """
    methodology = fixtures.create_published_methodology()
    entity = fixtures.create_entity(methodology["id"], legal_name="Lima Water SA", revenue_band="MID")

    zero = api_client.create_engagement_letter(
        engagement_letter_payload(entity["id"], fee_amount_cents=0, signed_at="2026-09-01T00:00:00Z"), EM)
    created = validate_success(zero, 201)
    assert created["fee_amount_cents"] == 0
    assert created["status"] == "DRAFT"

    negative = api_client.create_engagement_letter(
        engagement_letter_payload(entity["id"], fee_amount_cents=-1, signed_at="2026-09-01T00:00:00Z"), EM)
    validate_error(negative, ApiErrorId.ERR_FEE_AMOUNT_NEGATIVE, 400)


def test_zero_fee_letter_carries_its_boundary_value_and_the_negative_is_refused(api):
    """PRD §3.1: "The `fee_amount_cents` must be a non-negative integer"
    PRD §3.1: "the letter is created in `DRAFT`"

    Design: Difficulty/boundary_precision_check/fee_amount_zero_versus_negative_boundary
    """
    methodology = fixtures.create_published_methodology()
    entity = fixtures.create_entity(methodology["id"], legal_name="Lima Water SA", revenue_band="MID")

    created = get_success_data(api_client.create_engagement_letter(
        engagement_letter_payload(entity["id"], fee_amount_cents=0, signed_at="2026-09-01T00:00:00Z"), EM))

    fetched = get_success_data(api_client.get_engagement_letter(created["id"], EM))
    assert fetched["fee_amount_cents"] == 0
    assert fetched["fee_credited_cents"] == 0

    refused = api_client.create_engagement_letter(
        engagement_letter_payload(entity["id"], fee_amount_cents=-1, signed_at="2026-09-01T00:00:00Z"), EM)
    validate_error(refused, ApiErrorId.ERR_FEE_AMOUNT_NEGATIVE, 400)