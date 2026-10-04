"""Non-linear state machines (queue A): critic re-apply cycle, dispute loop."""
from test_helpers import (
    api_client, get_success_data, TEST_USERS,
    set_clock, setup_accredited_publication, setup_accredited_critic,
    setup_open_release, publish_review_for, ingest_review, publish_review,
    revoke_critic_via_review, file_classification_dispute, triage_dispute,
    make_critic_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]


def _setup_revoked_critic_with_open_release():
    """Accredited critic revoked via an accreditation review; release OPEN."""
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"], full_name="Critic A")
    _, release = setup_open_release()
    revoke_critic_via_review(critic["id"])
    return pub, critic, release


def test_critic_reapply_after_revocation_returns_to_applied():
    """PRD section 3.1: "a revoked critic may re-apply — the critic
    themselves performs the re-application transition from `REVOKED` back to
    `APPLIED`, and only on their own record."

    Design: Difficulty/non_linear_state_machine/critic_accreditation_revoked_reapply_cycle
    """
    _, critic, _ = _setup_revoked_critic_with_open_release()
    current = get_success_data(api_client.get_critic(critic["id"], BOARD))
    assert current["accreditation_status"] == "REVOKED"
    reapplied = get_success_data(api_client.transition_critic(
        critic["id"], {"action": "REAPPLY"},
        make_critic_headers(critic["id"])))
    assert reapplied["accreditation_status"] == "APPLIED"


def test_critic_reaccredited_after_reapply_can_publish_again():
    """PRD section 3.1: "Re-application followed by re-accreditation restores
    the publication's `accredited_critic_count` exactly once per critic.
    `REVOKED` is therefore not terminal for a critic."
    PRD section 3.4: "Ingestion requires the critic to be `ACCREDITED` or on
    `PROBATION`".

    Design: Difficulty/non_linear_state_machine/critic_accreditation_revoked_reapply_cycle
    """
    _, critic, release = _setup_revoked_critic_with_open_release()
    get_success_data(api_client.transition_critic(
        critic["id"], {"action": "REAPPLY"},
        make_critic_headers(critic["id"])))
    reaccredited = get_success_data(api_client.transition_critic(
        critic["id"], {"action": "ACCREDIT"}, BOARD))
    assert reaccredited["accreditation_status"] == "ACCREDITED"
    review = ingest_review(release["id"], critic["id"],
                           designation="FRESH")
    published = publish_review(review["id"], critic["id"])
    assert published["status"] == "PUBLISHED"


def _setup_triaged_dispute():
    """CA publishes FRESH; CC files a CLASSIFICATION dispute; dispute TRIAGED."""
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cc = setup_accredited_critic(pub["id"], full_name="Critic C")
    _, release = setup_open_release()
    review = publish_review_for(release["id"], ca["id"], designation="FRESH")
    dispute = file_classification_dispute(review["id"], cc["id"], "ROTTEN")
    triage_dispute(dispute["id"])
    return ca, cc, release, review, dispute


def test_dispute_return_to_filed_for_retriage_loop():
    """PRD section 3.8: "The `AccreditationBoard` triages it, moving it to
    `TRIAGED`, and may return a triaged dispute to `FILED` for re-triage
    loops — the branch is deliberately bidirectional."

    Design: Difficulty/non_linear_state_machine/dispute_filed_triaged_returned_refiling_loop
    """
    _, _, _, _, dispute = _setup_triaged_dispute()
    returned = get_success_data(api_client.transition_dispute(
        dispute["id"], {"action": "RETURN"}, BOARD))
    assert returned["status"] == "FILED"


def test_dispute_ruling_fires_cascade_after_retriage_loop():
    """PRD section 3.8: "An uphold ruling on a classification dispute
    requires the subject review to be in `FLAGGED` status with a
    `requested_classification` present; on success the review's
    `classification` becomes the requested value, the review returns to
    `PUBLISHED`, and the release's tomatometer and certification are
    recomputed with new superseding snapshots."

    Design: Difficulty/non_linear_state_machine/dispute_filed_triaged_returned_refiling_loop
    """
    _, _, _, review, dispute = _setup_triaged_dispute()
    get_success_data(api_client.transition_dispute(
        dispute["id"], {"action": "RETURN"}, BOARD))
    get_success_data(api_client.transition_dispute(
        dispute["id"], {"action": "TRIAGE"}, BOARD))
    current = get_success_data(api_client.get_dispute(dispute["id"], BOARD))
    ruled = get_success_data(api_client.transition_dispute(
        dispute["id"],
        {"action": "RULE_UPHOLD",
         "expected_dispute_version": current["version"]},
        BOARD))
    assert ruled["status"] == "UPHELD"
    after = get_success_data(api_client.get_review(review["id"], BOARD))
    assert after["classification"] == "ROTTEN"
    assert after["status"] == "PUBLISHED"
