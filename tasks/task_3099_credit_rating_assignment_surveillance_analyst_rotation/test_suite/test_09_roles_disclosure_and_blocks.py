"""Role boundaries, unsolicited-disclosure gating, appeal blocking and listing filters."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    rating_request_payload,
    appeal_payload,
    TEST_USERS,
    fixtures,
)

EM = TEST_USERS["engagement_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CC = TEST_USERS["committee_chair_headers"]
ANON = TEST_USERS["anonymous_headers"]


def _observed_request_version(request_id):
    return get_success_data(api_client.get_rating_request(request_id, EM))["version"]


def test_the_commercial_role_cannot_publish_a_rating(api):
    """PRD §2.1: "`CommitteeChair` (who convenes committees, proposes teams, and
    publishes ratings, but cannot screen conflicts or file appeals)"
    PRD §2.1: "When the role is present but the operation is not one the role is
    permitted to perform ... the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/engagement_manager_cannot_publish_a_rating
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window()
    payload = {"expected_rating_request_version": _observed_request_version(request["id"])}

    denied = api_client.publish_decision(decision["id"], payload, EM)
    validate_error(denied, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    unchanged = get_success_data(api_client.get_rating_decision(decision["id"], EM))
    assert unchanged["decision_status"] == "APPEAL_WINDOW"

    allowed = api_client.publish_decision(
        decision["id"], {"expected_rating_request_version": _observed_request_version(request["id"])}, CC)
    published = validate_success(allowed, 200)
    assert published["decision_status"] == "PUBLISHED"


def test_an_analyst_cannot_screen_a_conflict(api):
    """PRD §2.1: "`RatingAnalyst` (analytical staff who serve on teams, vote, and
    work surveillance, and who are forbidden from commercial and committee-chair
    operations)"
    PRD §2.1: "an operation attempted by a role outside its permitted set, are
    still rejected with ... `ERR_INSUFFICIENT_PERMISSIONS`"

    Design: Corner/rbac/rating_analyst_cannot_publish_or_screen_conflicts
    """
    entity, engagement, methodology = fixtures.setup_rated_entity_with_active_engagement()
    request = fixtures.create_request(engagement["id"], entity["id"])
    get_success_data(api_client.open_screening(request["id"], CO))
    lead = fixtures.onboard_lead()
    support = fixtures.onboard_support()
    assignment = fixtures.propose_team(request["id"], lead["id"], support["id"])

    response = api_client.screen_team_assignment(
        assignment["id"], fixtures.make_rating_analyst_headers(lead["id"]))
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    unchanged = get_success_data(api_client.get_team_assignment(assignment["id"], EM))
    assert unchanged["status"] == "PROPOSED"


def test_the_anonymous_filer_may_only_file_an_appeal(api):
    """PRD §2.1: "`Anonymous` (an unauthenticated issuer-side filer who may only
    file an appeal against a published-pending decision)"
    PRD §3.2: "A rating request is submitted under an engagement by supplying the
    `engagement_letter_id`"

    Design: Corner/rbac/anonymous_filer_can_only_file_an_appeal
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window()

    intake = api_client.create_rating_request(
        rating_request_payload(engagement["id"], entity["id"]), ANON)
    validate_error(intake, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    appeal_response = api_client.file_appeal(decision["id"], appeal_payload(), ANON)
    appeal = validate_success(appeal_response, 201)
    assert appeal["appeal_outcome"] == "PENDING"


def test_rating_entity_list_honours_the_solicitation_filter(api):
    """PRD §2.3: "Unless a caller supplies a filter, records are returned in
    ascending `created_at` order."
    PRD §2.3: "`limit` caps the number of records returned and defaults to 10"

    Design: Corner/endpoints/rated_entity_list_filters_by_solicitation_and_posture
    """
    methodology = fixtures.create_published_methodology()
    fixtures.create_entity(methodology["id"], legal_name="Eta Foods SA",
                           domicile_country="ES", revenue_band="MID",
                           solicitation_status="SOLICITED")
    fixtures.create_entity(methodology["id"], legal_name="Theta Foods SA",
                           domicile_country="ES", revenue_band="MID",
                           solicitation_status="UNSOLICITED")

    unsolicited_response = api_client.list_rated_entities(EM, {"solicitation_status": "UNSOLICITED"})
    unsolicited = validate_success(unsolicited_response, 200)
    assert len(unsolicited) == 1
    assert unsolicited[0]["legal_name"] == "Theta Foods SA"
    assert unsolicited[0]["solicitation_status"] == "UNSOLICITED"

    solicited_response = api_client.list_rated_entities(EM, {"solicitation_status": "SOLICITED"})
    solicited = validate_success(solicited_response, 200)
    assert len(solicited) == 1
    assert solicited[0]["legal_name"] == "Eta Foods SA"


def test_unsolicited_publish_requires_a_publicly_disclosed_methodology(api):
    """PRD §3.5: "enforces the unsolicited-disclosure gate: unless the issuer's
    `solicitation_status` is `SOLICITED` or its pinned methodology's `is_public`
    flag is true, publication is rejected with `ERR_UNSOLICITED_DISCLOSURE_MISSING`
    (HTTP 409)."

    Design: Corner/errors/unsolicited_publish_without_public_methodology_is_disclosure_missing
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window(
        solicitation_status="UNSOLICITED"
    )
    payload = {"expected_rating_request_version": _observed_request_version(request["id"])}

    denied = api_client.publish_decision(decision["id"], payload, CC)
    validate_error(denied, ApiErrorId.ERR_UNSOLICITED_DISCLOSURE_MISSING, 409)

    unpublished = get_success_data(api_client.get_rating_decision(decision["id"], EM))
    assert unpublished["decision_status"] == "APPEAL_WINDOW"


def test_unsolicited_publish_succeeds_once_the_methodology_is_disclosed(api):
    """PRD §2.9: "Public disclosure is a separate flag, `is_public`, which is
    false until explicitly disclosed for a published version"
    PRD §3.5: "it fixes the version-pinned `methodology_code` from the issuer's
    pinned methodology"

    Design: Corner/errors/unsolicited_publish_without_public_methodology_is_disclosure_missing
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window(
        solicitation_status="UNSOLICITED"
    )
    entity_record = get_success_data(api_client.get_rated_entity(entity["id"], EM))
    get_success_data(api_client.publish_methodology_disclosure(entity_record["methodology_id"], CO))

    published = get_success_data(
        api_client.publish_decision(
            decision["id"], {"expected_rating_request_version": _observed_request_version(request["id"])}, CC)
    )
    assert published["decision_status"] == "PUBLISHED"
    assert published["is_unsolicited"] is True


def test_an_appeal_is_blocked_while_an_appearance_breach_stands(api):
    """PRD §3.6: "When an `AppearanceReconciliation` for the same decision sits in
    a blocking state — `BREACH_CONFIRMED` or `APPEAL_PENDING` — the appeal is
    refused with `ERR_APPEALS_BLOCKED_PENDING_RECONCILIATION` (HTTP 409) until
    that reconciliation is cleared."

    Design: Corner/errors/published_appeal_blocked_while_appearance_breach_stands
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window()
    analyst = fixtures.onboard_lead()
    reconciliation = fixtures.record_appearance(analyst["id"], decision["id"])
    get_success_data(api_client.confirm_appearance_breach(reconciliation["id"], CC))

    blocked = api_client.file_appeal(decision["id"], appeal_payload(), ANON)
    validate_error(blocked, ApiErrorId.ERR_APPEALS_BLOCKED_PENDING_RECONCILIATION, 409)

    confirmed = get_success_data(api_client.get_appearance_reconciliation(reconciliation["id"], EM))
    assert confirmed["reconciliation_status"] == "BREACH_CONFIRMED"


def test_clearing_the_breach_reopens_appeal_admissibility(api):
    """PRD §3.6: "a `CommitteeChair` may clear the row from either `PENDING` or
    `APPEAL_PENDING`, moving it to `CLEARED` and reopening the decision's appeal
    admissibility."
    PRD §3.6: "A filed appeal starts in `PENDING` with `appeal_outcome` unset"

    Design: Corner/errors/published_appeal_blocked_while_appearance_breach_stands
    """
    entity, engagement, request, committee, decision = fixtures.setup_decision_in_appeal_window()
    analyst = fixtures.onboard_lead()
    reconciliation = fixtures.record_appearance(analyst["id"], decision["id"])
    # PRD §3.6: the row is cleared "from either `PENDING` or `APPEAL_PENDING`".
    # Clearing an already-BREACH_CONFIRMED row is not a clearing path the PRD
    # names, so the test clears from the row's initial PENDING state.
    cleared = get_success_data(api_client.clear_appearance_reconciliation(reconciliation["id"], CC))
    assert cleared["reconciliation_status"] == "CLEARED"

    appeal = validate_success(api_client.file_appeal(decision["id"], appeal_payload(), ANON), 201)
    assert appeal["appeal_outcome"] == "PENDING"