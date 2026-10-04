"""State-machine preconditions, invalid transitions and terminal lockdowns."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    assert_engagement_letter,
    assert_rating_request,
    assert_rating_committee,
    assert_same_instant,
    TEST_USERS,
    fixtures,
)

EM = TEST_USERS["engagement_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CC = TEST_USERS["committee_chair_headers"]


def test_signed_letter_cannot_revert_to_draft_once_a_request_exists(api):
    """PRD §3.1: "Before any request exists under the engagement, a signed letter
    may be reverted to `DRAFT`; the revert is refused with
    `ERR_ENGAGEMENT_ALREADY_TERMINAL` (HTTP 409) once a `RatingRequest` exists
    under that `engagement_letter_id`."

    Design: Corner/state_machines/engagement_revert_to_draft_after_request_exists_is_rejected
    """
    entity, engagement, methodology = fixtures.setup_rated_entity_with_active_engagement()
    fixtures.create_request(engagement["id"], entity["id"])

    response = api_client.revert_engagement_letter_to_draft(engagement["id"], EM)
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_ALREADY_TERMINAL, 409)

    letter = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    assert letter["status"] == "ACTIVE"
    assert letter["cooling_off_end_at"] is not None


def test_activation_before_cooling_off_elapses_is_rejected_then_allowed(api):
    """PRD §3.1: "Activation, which takes the letter from `SIGNED` to `ACTIVE`,
    enforces two conditions. The letter must actually be in `SIGNED`, or the
    call is rejected with `ERR_ENGAGEMENT_NOT_SIGNED` (HTTP 409), and the
    cooling-off period must have elapsed according to the logical clock, or the
    call is rejected with `ERR_COOLING_OFF_ACTIVE` (HTTP 409)."
    PRD §3.1: "no rating may be published while the cooling-off window is still
    open."

    Design: Corner/state_machines/activate_engagement_before_cooling_off_returns_cooling_off_active
    """
    entity, _, methodology = fixtures.setup_rated_entity_with_active_engagement()
    letter = get_success_data(api_client.create_engagement_letter(
        fixtures.engagement_letter_payload(entity["id"]), EM))
    letter = get_success_data(api_client.submit_engagement_letter(letter["id"], EM))
    assert letter["status"] == "SIGNED"
    assert_same_instant(letter["cooling_off_end_at"], "2026-11-30T00:00:00Z",
                        "90 days after signed_at")

    get_success_data(api_client.set_clock("2026-11-29T00:00:00Z", TEST_USERS["platform_admin_headers"]))
    blocked = api_client.activate_engagement_letter(letter["id"], EM)
    validate_error(blocked, ApiErrorId.ERR_COOLING_OFF_ACTIVE, 409)

    unchanged = get_success_data(api_client.get_engagement_letter(letter["id"], EM))
    assert unchanged["status"] == "SIGNED"

    get_success_data(api_client.set_clock("2026-11-30T00:00:00Z", TEST_USERS["platform_admin_headers"]))
    activated = api_client.activate_engagement_letter(letter["id"], EM)
    active = validate_success(activated, 200)
    assert active["status"] == "ACTIVE"


def test_second_return_to_submitted_is_invalid_state_and_reverses_nothing(api):
    """PRD §3.2: "Returning a request to intake takes it from `SCREENING` back to
    `SUBMITTED`, requires that it actually sit in `SCREENING` or the call is
    rejected with `ERR_REQUEST_NOT_SCREENING` (HTTP 409), and it reverses the
    request's `allocated_fee_cents` into the engagement's `fee_reversed_cents`
    while resetting `allocated_fee_cents` to zero."

    Design: Corner/state_machines/return_screening_to_submitted_twice_is_invalid_state
    """
    entity, engagement, methodology = fixtures.setup_rated_entity_with_active_engagement()
    request = fixtures.create_request(engagement["id"], entity["id"])
    get_success_data(api_client.open_screening(request["id"], CO))
    first_return = api_client.return_request_to_submitted(request["id"], CO)
    validate_success(first_return, 200)

    reversed_once = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    assert reversed_once["fee_reversed_cents"] > 0

    second = api_client.return_request_to_submitted(request["id"], CO)
    validate_error(second, ApiErrorId.ERR_REQUEST_NOT_SCREENING, 409)

    after = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    assert after["fee_reversed_cents"] == reversed_once["fee_reversed_cents"], "no double reversal"
    request_after = get_success_data(api_client.get_rating_request(request["id"], EM))
    assert request_after["request_status"] == "SUBMITTED"


def test_terminating_a_draft_letter_is_invalid_state(api):
    """PRD §3.1: "Termination requires the letter to be `ACTIVE`, or it is
    rejected with `ERR_ENGAGEMENT_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/engagement_terminate_from_draft_is_invalid_state
    """
    entity, engagement, methodology = fixtures.setup_rated_entity_with_active_engagement()
    draft = get_success_data(api_client.create_engagement_letter(
        fixtures.engagement_letter_payload(entity["id"]), EM))
    assert draft["status"] == "DRAFT"

    response = api_client.terminate_engagement_letter(draft["id"], EM)
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE, 409)

    after = get_success_data(api_client.get_engagement_letter(draft["id"], EM))
    assert after["status"] == "DRAFT"


def test_convened_committee_starts_with_zero_votes_and_no_quorum(api):
    """PRD §3.4: "The committee begins in `CONVENED` with `votes_cast` at zero,
    and it carries a `quorum_met` flag that is true only once `votes_cast` has
    reached `required_voting_members`, a `dissent_count`, and a
    `committee_status`."

    Design: Corner/state_machines/committee_convened_is_the_initial_state_with_zero_votes
    """
    entity, engagement, request, assignment, methodology = fixtures.setup_request_ready_for_committee()
    committee = fixtures.convene_committee(request["id"])
    assert_rating_committee(committee)
    assert committee["committee_status"] == "CONVENED"
    assert committee["votes_cast"] == 0
    assert committee["quorum_met"] is False
    assert committee["dissent_count"] == 0


def test_a_dissolved_committee_rejects_every_further_transition(api):
    """PRD §3.1: "every `RatingCommittee` for a withdrawn request that sits in
    `CONVENED` or `IN_SESSION` moves to `DISSOLVED`."
    PRD §3.5: "requires the committee to be `CONVENED` or `IN_SESSION` —
    otherwise `ERR_COMMITTEE_NOT_IN_SESSION` (HTTP 409)."

    Design: Corner/state_machines/dissolved_committee_rejects_any_further_transition
    """
    entity, engagement, request, assignment, methodology = fixtures.setup_request_ready_for_committee()
    committee = fixtures.convene_committee(request["id"])
    get_success_data(api_client.withdraw_rating_request(request["id"], EM))

    dissolved = get_success_data(api_client.get_rating_committee(committee["id"], EM))
    assert dissolved["committee_status"] == "DISSOLVED"

    response = api_client.open_committee_session(committee["id"], CC)
    validate_error(response, ApiErrorId.ERR_COMMITTEE_NOT_IN_SESSION, 409)