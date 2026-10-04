"""Baseline entity and envelope behavior (queue B, section: entities/endpoints)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID, ApiErrorId,
    set_clock, create_publication, create_critic, create_title, open_title,
    create_release, open_release, create_audience_member,
    setup_accredited_publication, setup_accredited_critic, setup_open_release,
    ingest_review, publish_review_for, file_classification_dispute,
    file_score_display_dispute, make_critic_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]
STUDIO = TEST_USERS["studio_rep_headers"]


def test_title_create_returns_defaults_and_system_fields():
    """PRD section 3.3: "A title's `posture` begins at `SETUP`".
    PRD section 2.4: "`version` starts at 1 on creation and increments by
    exactly 1 on every mutation of that entity".

    Design: Corner/entities/title_create_returns_defaults_and_system_fields
    """
    set_clock()
    resp = api_client.create_title(
        {"canonical_name": "Glass Harbor", "release_year": 2026}, ADMIN)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("response_type") == "object"
    data = body["data"]
    assert data["canonical_name"] == "Glass Harbor"
    assert data["release_year"] == 2026
    assert data["posture"] == "SETUP"
    assert data["version"] == 1
    assert data.get("id")
    assert data.get("created_at")
    assert data.get("updated_at")


def test_critic_create_omitting_is_top_critic_defaults_false():
    """PRD section 3.1: "A `PlatformAdmin` registers a critic with a
    `full_name`, the employing `publication_id`, and an optional
    `is_top_critic` flag (defaulting to false) that marks top-critic
    designation used by the certification rule. A new critic starts with
    `accreditation_status` of `APPLIED`".

    Design: Corner/entities/critic_create_omitting_is_top_critic_defaults_false
    """
    set_clock()
    pub = create_publication()
    resp = api_client.create_critic(
        {"full_name": "Critic A", "publication_id": pub["id"]}, ADMIN)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    data = resp.json()["data"]
    assert data["is_top_critic"] is False
    assert data["accreditation_status"] == "APPLIED"


def test_review_create_returns_ingested_status_and_null_published_at():
    """PRD section 3.4: "A new review starts in `INGESTED` status."
    PRD section 3.4: "On a successful publish the review's `classification`
    is set equal to its `self_designation`, `published_at` is stamped with
    the current logical clock".

    Design: Corner/entities/review_create_extra_version_field_is_ignored_input
    """
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"])
    _, release = setup_open_release()
    resp = api_client.create_review(
        release["id"],
        {"critic_id": critic["id"], "body_text": "Fine film.",
         "self_designation": "FRESH", "version": 99,
         "published_at": "2026-01-01T00:00:00Z"},
        make_critic_headers(critic["id"]))
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    data = resp.json()["data"]
    assert data["status"] == "INGESTED"
    assert data["version"] == 1
    assert data.get("published_at") is None


def test_get_release_with_unknown_id_returns_not_found():
    """PRD section 2.8: "Existence — path identifiers exist, validated
    left-to-right along nested paths, and body foreign-key references exist
    (`ERR_NOT_FOUND`)."

    Design: Corner/entities/get_release_with_unknown_id_returns_not_found
    """
    set_clock()
    resp = api_client.get_release(NON_EXISTENT_UUID, ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("response_type") == "error"
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_disputes_list_paginates_with_limit_offset_total_count_has_more():
    """PRD section 2.3: "List endpoints accept `limit` and `offset` query
    parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. List responses report `limit`, `offset`,
    `total_count`, and `has_more` inside `meta`."

    Design: Corner/entities/disputes_list_paginates_with_limit_offset_total_count_has_more
    """
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cc = setup_accredited_critic(pub["id"], full_name="Critic C")
    _, release = setup_open_release()
    ra = publish_review_for(release["id"], ca["id"], designation="FRESH")
    file_classification_dispute(ra["id"], cc["id"], "ROTTEN")
    file_score_display_dispute(release["id"])

    resp = api_client.list_disputes(BOARD, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_review_create_with_invalid_designation_returns_invalid_request():
    """PRD section 3.4: "A `Critic` ingests a review against a release by
    providing the `critic_id`, the `body_text`, and a `self_designation` of
    `FRESH` or `ROTTEN`."
    PRD section 2.8: "Request shape — required fields present, enum values
    valid, `stars` within 1 through 5 inclusive, exactly one of
    `subject_critic_id` or `subject_publication_id` set on an accreditation
    review, and dispute filer fields consistent with `dispute_kind`
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/release_create_with_invalid_cut_enum_value_returns_invalid_request
    """
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"])
    _, release = setup_open_release()
    resp = api_client.create_review(
        release["id"],
        {"critic_id": critic["id"], "body_text": "Ambivalent.",
         "self_designation": "MEH"},
        make_critic_headers(critic["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_accreditation_review_with_both_subjects_returns_invalid_request():
    """PRD section 3.2: "The `AccreditationBoard` files a periodic
    accreditation review against exactly one subject: either a
    `subject_critic_id` or a `subject_publication_id` — supplying both or
    neither is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/accreditation_review_with_both_subjects_returns_invalid_request
    """
    set_clock()
    pub = create_publication()
    critic = create_critic(pub["id"])
    resp = api_client.create_accreditation_review(
        {"subject_critic_id": critic["id"],
         "subject_publication_id": pub["id"],
         "period_start": "2026-08-01T00:00:00Z",
         "period_end": "2026-09-01T00:00:00Z"},
        BOARD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_audience_member_id_used_as_rating_owner_binding():
    """PRD section 3.6: "An `AudienceMember` rates a release by providing the
    `audience_member_id`, an integer `stars` value from 1 through 5
    inclusive, and optionally a `ticket_verification_id`. The member id must
    equal the caller's `X-User-ID`."
    PRD section 2.1: "When `X-User-Role` is `AudienceMember`, `X-User-ID` is
    the `id` of the acting `AudienceMember` entity; ownership checks compare
    a resource's `audience_member_id` to `X-User-ID`, with mismatches
    rejected as `ERR_FORBIDDEN`."

    Design: Corner/entities/audience_member_id_used_as_rating_owner_binding
    """
    set_clock()
    _, release = setup_open_release()
    m1 = create_audience_member()
    m2 = create_audience_member()
    resp = api_client.create_audience_rating(
        release["id"], {"audience_member_id": m2["id"], "stars": 4},
        {"X-User-ID": m1["id"], "X-User-Role": "AudienceMember",
         "Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_error_responses_use_fixed_envelope_shape():
    """PRD section 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD section 2.2: "The `error_id` is a unique, machine-readable string
    that identifies the specific error."
    PRD section 2.2: "The `message` provides a human-readable explanation of
    what went wrong."

    Design: Corner/endpoints/error_responses_use_fixed_envelope_shape
    """
    set_clock()
    resp = api_client.get_review(NON_EXISTENT_UUID, ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("response_type") == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"]
    assert body["meta"].get("api_request_id")
    assert body["meta"].get("api_request_timestamp")
