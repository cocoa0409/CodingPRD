"""Auth, authorization, and constraint validations (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    set_clock, create_publication, create_critic, accredit_critic,
    create_audience_member, setup_accredited_publication,
    setup_accredited_critic, setup_open_release, ingest_review,
    publish_review_for, revoke_critic_via_review, setup_verified_ticket,
    create_rating, make_critic_headers, make_audience_member_headers,
    create_ticket_verification_payload,
    file_score_display_dispute,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]
STUDIO = TEST_USERS["studio_rep_headers"]


def test_missing_auth_headers_returns_unauthenticated():
    """PRD section 2.1: "A request missing either header, or declaring a role
    outside the role set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    set_clock()
    resp = api_client.create_title(
        {"canonical_name": "NoAuth", "release_year": 2026},
        {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_critic_cannot_run_board_accreditation_transition():
    """PRD section 2.1: "A request whose declared role is not permitted for
    the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD section 3.1: "a revoked critic may re-apply — the critic themselves
    performs the re-application transition from `REVOKED` back to `APPLIED`,
    and only on their own record."

    Design: Corner/validations/critic_cannot_run_board_accreditation_transition
    """
    set_clock()
    pub = create_publication()
    ca = create_critic(pub["id"], full_name="Critic A")
    cc = create_critic(pub["id"], full_name="Critic C")
    resp = api_client.transition_critic(
        cc["id"], {"action": "ACCREDIT"}, make_critic_headers(ca["id"]))
    assert resp.status_code == 403, (
        f"Expected 403, got {resp.status_code}: {resp.text}")
    assert resp.json()["data"]["error_id"] in (
        "ERR_UNAUTHORIZED", "ERR_FORBIDDEN")


def test_critic_accredit_requires_accredited_publication():
    """PRD section 3.1: "The board accredits an applicant by transitioning
    the critic from `APPLIED` to `ACCREDITED`, but only when the employing
    publication is itself `ACCREDITED`; otherwise the transition is rejected
    with `ERR_PUBLICATION_NOT_ACCREDITED` (HTTP 409)."

    Design: Corner/validations/critic_accredit_requires_accredited_publication
    """
    set_clock()
    pub = create_publication()
    critic = create_critic(pub["id"])
    resp = api_client.transition_critic(
        critic["id"], {"action": "ACCREDIT"}, BOARD)
    validate_error(resp, ApiErrorId.ERR_PUBLICATION_NOT_ACCREDITED)


def test_duplicate_live_review_per_critic_release_rejected():
    """PRD section 3.4: "a critic may hold at most one review not in
    `WITHDRAWN` status per release; a second live review is rejected with
    `ERR_DUPLICATE_REVIEW` (HTTP 409)."

    Design: Corner/validations/duplicate_live_review_per_critic_release_rejected
    """
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"])
    _, release = setup_open_release()
    ingest_review(release["id"], critic["id"], designation="FRESH")
    resp = api_client.create_review(
        release["id"],
        {"critic_id": critic["id"], "body_text": "Second take.",
         "self_designation": "ROTTEN"},
        make_critic_headers(critic["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REVIEW)


def test_rating_verify_with_unverified_ticket_returns_ticket_not_verified():
    """PRD section 3.6: "The rating's owner may verify it by transitioning it
    from `UNVERIFIED` to `VERIFIED`, supplying a `ticket_verification_id`
    that references a ticket verification in `VERIFIED` status for the same
    release and the same `audience_member_id`; anything else is rejected with
    `ERR_TICKET_NOT_VERIFIED` (HTTP 409)."

    Design: Corner/validations/rating_verify_with_unverified_ticket_returns_ticket_not_verified
    """
    set_clock()
    _, release = setup_open_release()
    member = create_audience_member()
    tv = get_success_data(api_client.create_ticket_verification(
        release["id"],
        create_ticket_verification_payload(member["id"]),
        make_audience_member_headers(member["id"])))
    assert tv["status"] == "SUBMITTED"
    rating = create_rating(release["id"], member["id"], 4)
    resp = api_client.transition_audience_rating(
        rating["id"],
        {"action": "VERIFY", "ticket_verification_id": tv["id"]},
        make_audience_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_VERIFIED)


def test_duplicate_live_rating_per_member_release_rejected():
    """PRD section 3.6: "At most one rating not in `INVALIDATED` status may
    exist per member per release; a second live rating is rejected with
    `ERR_DUPLICATE_VERIFIED_RATING` (HTTP 409)."

    Design: Corner/validations/duplicate_live_rating_per_member_release_rejected
    """
    set_clock()
    _, release = setup_open_release()
    member = create_audience_member()
    create_rating(release["id"], member["id"], 4)
    resp = api_client.create_audience_rating(
        release["id"], {"audience_member_id": member["id"], "stars": 2},
        make_audience_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VERIFIED_RATING)


def test_verify_rating_during_confirmed_bombing_suspension_rejected():
    """PRD section 3.6: "Verification is additionally blocked while the
    release's `audience_display_suspended` is true because a confirmed
    bombing incident covers it — such an attempt is rejected with
    `ERR_BOMBING_SUSPENSION_ACTIVE` (HTTP 409), though unverified ratings may
    still be created during a suspension."

    Design: Corner/validations/verify_rating_during_confirmed_bombing_suspension_rejected
    """
    set_clock()
    _, release = setup_open_release()
    member = create_audience_member()
    tv = setup_verified_ticket(release["id"], member["id"])
    incident = get_success_data(
        api_client.create_bombing_incident(release["id"], ADMIN))
    get_success_data(api_client.transition_bombing_incident(
        incident["id"], {"action": "CONFIRM"}, ADMIN))
    rating = create_rating(release["id"], member["id"], 4)

    resp = api_client.transition_audience_rating(
        rating["id"],
        {"action": "VERIFY", "ticket_verification_id": tv["id"]},
        make_audience_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_BOMBING_SUSPENSION_ACTIVE)

    get_success_data(api_client.transition_bombing_incident(
        incident["id"], {"action": "RESOLVE"}, ADMIN))
    verified = get_success_data(api_client.transition_audience_rating(
        rating["id"],
        {"action": "VERIFY", "ticket_verification_id": tv["id"]},
        make_audience_member_headers(member["id"])))
    assert verified["status"] == "VERIFIED"


def test_critic_self_dispute_on_own_review_forbidden():
    """PRD section 3.8: "segregation of duties forbids a critic from filing a
    classification dispute against their own review — when
    `filed_by_critic_id` equals the review's `critic_id` the filing is
    rejected with `ERR_SELF_DISPUTE_FORBIDDEN` (HTTP 409); studio-filed
    disputes are unaffected by this rule."

    Design: Corner/validations/critic_self_dispute_on_own_review_forbidden
    """
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    _, release = setup_open_release()
    ra = publish_review_for(release["id"], ca["id"], designation="FRESH")
    resp = api_client.create_dispute(
        {"dispute_kind": "CLASSIFICATION",
         "subject_review_id": ra["id"],
         "filed_by_critic_id": ca["id"],
         "requested_classification": "ROTTEN"},
        make_critic_headers(ca["id"]))
    validate_error(resp, ApiErrorId.ERR_SELF_DISPUTE_FORBIDDEN)


def test_dispute_requesting_unchanged_classification_returns_invalid_reclassification():
    """PRD section 3.8: "First, the `requested_classification` must be
    present, must be `FRESH` or `ROTTEN`, and must differ from the review's
    current `classification`; a request that is missing, invalid, or equal to
    the current classification is rejected with `ERR_INVALID_RECLASSIFICATION`
    (HTTP 400)."

    Design: Corner/validations/dispute_requesting_unchanged_classification_returns_invalid_reclassification
    """
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cc = setup_accredited_critic(pub["id"], full_name="Critic C")
    _, release = setup_open_release()
    ra = publish_review_for(release["id"], ca["id"], designation="FRESH")
    resp = api_client.create_dispute(
        {"dispute_kind": "CLASSIFICATION",
         "subject_review_id": ra["id"],
         "filed_by_critic_id": cc["id"],
         "requested_classification": "FRESH"},
        make_critic_headers(cc["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_RECLASSIFICATION)


def test_revoked_critic_ingest_returns_critic_not_accredited():
    """PRD section 3.4: "Ingestion requires the critic to be `ACCREDITED` or
    on `PROBATION` — a critic in any other status is rejected with
    `ERR_CRITIC_NOT_ACCREDITED` (HTTP 409)".

    Design: Corner/errors/critic_not_accredited_error_catalog
    """
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"])
    revoke_critic_via_review(critic["id"])
    _, release = setup_open_release()
    resp = api_client.create_review(
        release["id"],
        {"critic_id": critic["id"], "body_text": "Still writing.",
         "self_designation": "FRESH"},
        make_critic_headers(critic["id"]))
    validate_error(resp, ApiErrorId.ERR_CRITIC_NOT_ACCREDITED)
