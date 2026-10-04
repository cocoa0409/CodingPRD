"""Cross-entity state dependencies (queue A)."""
from test_helpers import (
    api_client, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, create_title, open_title, create_release, open_release,
    setup_accredited_publication, setup_accredited_critic, ingest_review,
    make_critic_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]


def test_release_open_rejected_while_parent_title_in_setup():
    """PRD section 3.3: "Opening a release moves it from `UPCOMING` to `OPEN`
    and is permitted only while the parent title's posture is `OPEN`;
    otherwise the transition is rejected with `ERR_TITLE_NOT_OPEN` (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/release_open_requires_parent_title_open
    """
    set_clock()
    title = create_title()
    release = create_release(title["id"])
    assert title["posture"] == "SETUP"
    resp = api_client.transition_release(
        release["id"], {"action": "OPEN"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TITLE_NOT_OPEN)


def test_release_open_succeeds_after_parent_title_opens():
    """PRD section 3.3: "Opening a release moves it from `UPCOMING` to `OPEN`
    and is permitted only while the parent title's posture is `OPEN`;
    otherwise the transition is rejected with `ERR_TITLE_NOT_OPEN` (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/release_open_requires_parent_title_open
    """
    set_clock()
    title = create_title()
    release = create_release(title["id"])
    open_title(title["id"])
    opened = get_success_data(api_client.transition_release(
        release["id"], {"action": "OPEN"}, ADMIN))
    assert opened["status"] == "OPEN"


def test_publish_on_upcoming_release_fails_despite_lifted_embargo():
    """PRD section 3.4: "The release must be `OPEN` (`ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/review_publish_requires_release_open_not_just_embargo_lifted
    """
    set_clock("2026-09-10T00:00:00Z")
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"], full_name="Critic A")
    title = open_title(create_title()["id"])
    release = create_release(title["id"])  # left UPCOMING, embargo lifted
    assert release["status"] == "UPCOMING"
    review = ingest_review(release["id"], critic["id"], designation="FRESH")
    resp = api_client.transition_review(
        review["id"], {"action": "PUBLISH"},
        make_critic_headers(critic["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_publish_on_upcoming_release_blocked_at_state_gate_not_embargo():
    """PRD section 3.4: "Publishing moves a review from `INGESTED` to
    `PUBLISHED` and is the most heavily guarded transition in the system. The
    acting critic must be the review's author (`ERR_FORBIDDEN` otherwise).
    The author's `accreditation_status` must be `ACCREDITED` or `PROBATION`
    (`ERR_CRITIC_NOT_ACCREDITED`). The release must be `OPEN`
    (`ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/review_publish_requires_release_open_not_just_embargo_lifted
    """
    set_clock("2026-09-10T00:00:00Z")
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"], full_name="Critic A")
    title = open_title(create_title()["id"])
    release = create_release(title["id"])  # left UPCOMING
    review = ingest_review(release["id"], critic["id"], designation="FRESH")
    resp = api_client.transition_review(
        review["id"], {"action": "PUBLISH"},
        make_critic_headers(critic["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    # The embargo gate would have passed (clock past embargo_until); the
    # failure is purely the release-state dependency.
    assert resp.json()["data"]["error_id"] != "ERR_EMBARGO_ACTIVE"
