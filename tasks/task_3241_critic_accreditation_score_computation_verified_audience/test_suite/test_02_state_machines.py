"""State machine admissibility and side effects (queue B, state_machines)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    set_clock, create_publication, create_critic, accredit_critic,
    create_title, open_title, create_release, open_release,
    setup_accredited_publication, setup_accredited_critic, setup_open_release,
    ingest_review, publish_review, publish_review_for, rule_dispute,
    file_classification_dispute, triage_dispute, make_critic_headers,
    create_accreditation_review_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]


def test_release_close_is_terminal_and_reopen_returns_invalid_state():
    """PRD section 3.3: "Closing moves a release from `OPEN` to `CLOSED`,
    which is terminal."
    PRD section 2.8: "State admissibility — the target entity is in a state
    that admits the requested transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/release_close_is_terminal_and_reopen_returns_invalid_state
    """
    set_clock()
    _, release = setup_open_release()
    get_success_data(api_client.transition_release(
        release["id"], {"action": "CLOSE"}, ADMIN))
    resp = api_client.transition_release(
        release["id"], {"action": "OPEN"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api_client.get_release(release["id"], ADMIN))
    assert current["status"] == "CLOSED"


def test_dispute_terminal_rejects_all_further_actions():
    """PRD section 3.8: "Rulings happen only from `TRIAGED`; any action on an
    `UPHELD` or `REJECTED` dispute, both of which are terminal, is rejected
    with `ERR_DISPUTE_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/dispute_terminal_rejects_all_further_actions
    """
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cc = setup_accredited_critic(pub["id"], full_name="Critic C")
    _, release = setup_open_release()
    ra = publish_review_for(release["id"], ca["id"], designation="FRESH")
    dispute = file_classification_dispute(ra["id"], cc["id"], "ROTTEN")
    triage_dispute(dispute["id"])
    ruled = rule_dispute(dispute["id"], "RULE_UPHOLD")
    assert ruled["status"] == "UPHELD"

    resp = api_client.transition_dispute(
        dispute["id"], {"action": "TRIAGE"}, BOARD)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_TERMINAL)


def test_review_publish_sets_published_at_from_logical_clock():
    """PRD section 3.4: "On a successful publish the review's
    `classification` is set equal to its `self_designation`, `published_at`
    is stamped with the current logical clock".

    Design: Corner/state_machines/review_publish_sets_published_at_from_logical_clock
    """
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"])
    _, release = setup_open_release()
    review = ingest_review(release["id"], critic["id"], designation="FRESH")
    set_clock("2026-09-02T12:00:00Z")
    published = publish_review(review["id"], critic["id"])
    assert published["published_at"] == "2026-09-02T12:00:00.000Z"


def test_bombing_confirm_suspends_display_and_resolve_restores():
    """PRD section 3.7: "Confirmation suspends the release's audience display
    — `audience_display_suspended` becomes true".
    PRD section 3.7: "Later, the administrator resolves a confirmed incident,
    moving it to the terminal `RESOLVED` status: `audience_display_suspended`
    returns to false and the verified audience score is recomputed,
    refreshing `audience_score_pct`."

    Design: Corner/state_machines/bombing_confirm_suspends_display_and_resolve_restores
    """
    set_clock()
    _, release = setup_open_release()
    incident = get_success_data(
        api_client.create_bombing_incident(release["id"], ADMIN))
    get_success_data(api_client.transition_bombing_incident(
        incident["id"], {"action": "CONFIRM"}, ADMIN))
    mid = get_success_data(api_client.get_release(release["id"], ADMIN))
    assert mid["audience_display_suspended"] is True

    resolved = get_success_data(api_client.transition_bombing_incident(
        incident["id"], {"action": "RESOLVE"}, ADMIN))
    assert resolved["status"] == "RESOLVED"
    after = get_success_data(api_client.get_release(release["id"], ADMIN))
    assert after["audience_display_suspended"] is False


def test_withdraw_on_ingested_review_returns_invalid_state():
    """PRD section 3.4: "The author may withdraw a review from either
    `PUBLISHED` or `FLAGGED`, moving it to the terminal `WITHDRAWN` status".

    Design: Corner/state_machines/withdraw_on_ingested_review_returns_invalid_state
    """
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"])
    _, release = setup_open_release()
    review = ingest_review(release["id"], critic["id"], designation="FRESH")
    resp = api_client.transition_review(
        review["id"], {"action": "WITHDRAW"},
        make_critic_headers(critic["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api_client.get_review(review["id"], BOARD))
    assert current["status"] == "INGESTED"


def test_upheld_accreditation_review_terminal_states_lock():
    """PRD section 3.2: "`UPHELD`, `REVOKED`, and `DISMISSED` are terminal
    for a review."

    Design: Corner/state_machines/upheld_publication_review_terminal_states_lock
    """
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"])
    review = get_success_data(api_client.create_accreditation_review(
        create_accreditation_review_payload(subject_critic_id=critic["id"]),
        BOARD))
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "BEGIN_REVIEW"}, BOARD))
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "RULE_UPHOLD"}, BOARD))

    resp = api_client.transition_accreditation_review(
        review["id"], {"action": "DISMISS"}, BOARD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(
        api_client.get_accreditation_review(review["id"], BOARD))
    assert current["status"] == "UPHELD"
