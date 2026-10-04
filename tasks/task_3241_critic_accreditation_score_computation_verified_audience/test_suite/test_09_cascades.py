"""Transitive cascades (queue A): dispute-upheld cascade, publication revocation."""
from test_helpers import (
    api_client, get_success_data, TEST_USERS,
    set_clock, setup_accredited_publication, setup_accredited_critic,
    setup_open_release, publish_review_for, create_accreditation_review_payload,
    file_classification_dispute, triage_dispute, rule_dispute,
    find_live_snapshot,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]


def _setup_certified_fresh_release_with_flagged_dispute():
    """Six accredited critics (C1, C2 top) all publish FRESH; C1 files a
    CLASSIFICATION dispute on C5's review requesting ROTTEN; TRIAGED."""
    set_clock()
    pub = setup_accredited_publication()
    critics = []
    for i in range(6):
        critics.append(setup_accredited_critic(
            pub["id"], is_top_critic=(i < 2), full_name=f"Critic {i + 1}"))
    _, release = setup_open_release()
    reviews = [publish_review_for(release["id"], c["id"], designation="FRESH")
               for c in critics]
    dispute = file_classification_dispute(
        reviews[4]["id"], critics[0]["id"], "ROTTEN")
    triage_dispute(dispute["id"])
    return critics, release, reviews, dispute


def test_upheld_dispute_reclassifies_review_and_returns_to_published():
    """PRD section 3.8: "An uphold ruling on a classification dispute
    requires the subject review to be in `FLAGGED` status with a
    `requested_classification` present; on success the review's
    `classification` becomes the requested value, the review returns to
    `PUBLISHED`, and the release's tomatometer and certification are
    recomputed with new superseding snapshots."

    Design: Difficulty/transitive_cascade/upheld_classification_dispute_cascades_to_certification_loss
    """
    _, release, reviews, dispute = \
        _setup_certified_fresh_release_with_flagged_dispute()
    rule_dispute(dispute["id"], "RULE_UPHOLD")
    review = get_success_data(api_client.get_review(reviews[4]["id"], BOARD))
    assert review["classification"] == "ROTTEN"
    assert review["status"] == "PUBLISHED"


def test_upheld_dispute_recomputes_certified_snapshot_and_certification():
    """PRD section 3.8: "An uphold ruling on a classification dispute
    requires the subject review to be in `FLAGGED` status with a
    `requested_classification` present; on success the review's
    `classification` becomes the requested value, the review returns to
    `PUBLISHED`, and the release's tomatometer and certification are
    recomputed with new superseding snapshots."
    PRD section 2.7: "Every score recomputation appends a new `ScoreSnapshot`
    row recording the `release_id`, the `scope` (`TOMATOMETER` or
    `AUDIENCE_VERIFIED`), the `variant` (`PROVISIONAL` or `CERTIFIED` for the
    tomatometer; `ALL_RATINGS` or `VERIFIED_ONLY` for the audience score),
    the `positive_count`, the `total_count`, and the resulting `pct`."

    Design: Difficulty/transitive_cascade/upheld_classification_dispute_cascades_to_certification_loss
    """
    _, release, reviews, dispute = \
        _setup_certified_fresh_release_with_flagged_dispute()
    before = find_live_snapshot(
        get_success_data(api_client.list_score_snapshots(release["id"], BOARD)),
        "TOMATOMETER", "CERTIFIED")
    assert before["pct"] == 100

    rule_dispute(dispute["id"], "RULE_UPHOLD")

    data = get_success_data(api_client.get_release(release["id"], BOARD))
    # Six reviews remain published; C5's flips FRESH -> ROTTEN: 5/6 == 83.
    assert data["tomatometer_pct"] == 83
    # 83 >= 75, N == 6, T == 2: certification survives the cascade
    assert data["certification"] == "CERTIFIED_FRESH"

    snapshots = get_success_data(
        api_client.list_score_snapshots(release["id"], BOARD))
    after = find_live_snapshot(snapshots, "TOMATOMETER", "CERTIFIED")
    assert after["positive_count"] == 5
    assert after["total_count"] == 6
    assert after["pct"] == 83
    prior = [s for s in snapshots
             if s["scope"] == "TOMATOMETER" and s["variant"] == "CERTIFIED"
             and s["superseded"] is True]
    assert any(s["pct"] == 100 for s in prior), \
        "The 100-pct CERTIFIED snapshot must be superseded by the cascade"


def _setup_publication_revocation_cascade():
    """P1 with CA (FRESH) and CB (ROTTEN) published; publication-level
    accreditation review ruled REVOKED."""
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cb = setup_accredited_critic(pub["id"], full_name="Critic B")
    _, release = setup_open_release()
    publish_review_for(release["id"], ca["id"], designation="FRESH")
    publish_review_for(release["id"], cb["id"], designation="ROTTEN")
    review = get_success_data(api_client.create_accreditation_review(
        create_accreditation_review_payload(subject_publication_id=pub["id"]),
        BOARD))
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "BEGIN_REVIEW"}, BOARD))
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "RULE_REVOKE"}, BOARD))
    return pub, ca, cb, release


def test_publication_revocation_cascades_to_publication_and_critics():
    """PRD section 3.1: "Revocation is never invoked directly: when an
    accreditation review is ruled with a revoke outcome against a publication
    in either `ACCREDITED` or `PROBATION` status, the publication transitions
    to `REVOKED` automatically, and every linked critic whose
    `accreditation_status` is `ACCREDITED` or `PROBATION` transitions to
    `REVOKED` as well, each firing the critic-revocation cascade described
    below."

    Design: Difficulty/transitive_cascade/publication_revocation_cascades_through_critics_to_scores
    """
    pub, ca, cb, _ = _setup_publication_revocation_cascade()
    publication = get_success_data(api_client.get_publication(pub["id"], BOARD))
    assert publication["status"] == "REVOKED"
    critic_a = get_success_data(api_client.get_critic(ca["id"], BOARD))
    critic_b = get_success_data(api_client.get_critic(cb["id"], BOARD))
    assert critic_a["accreditation_status"] == "REVOKED"
    assert critic_b["accreditation_status"] == "REVOKED"


def test_publication_revocation_recomputes_scores_with_null_certified():
    """PRD section 3.1: "every review by that critic in `PUBLISHED` or
    `FLAGGED` status is marked de-accredited for scoring, which recomputes
    the tomatometer (both variants) and the certification for every affected
    release, each recompute emitting new snapshots that supersede the prior
    ones."
    PRD section 3.5: "When a variant's input set is empty, its percentage is
    null rather than zero."

    Design: Difficulty/transitive_cascade/publication_revocation_cascades_through_critics_to_scores
    """
    _, _, _, release = _setup_publication_revocation_cascade()
    data = get_success_data(api_client.get_release(release["id"], BOARD))
    # Both critics revoked: certified input set empty => pct null, not 0
    assert data["tomatometer_pct"] is None

    snapshots = get_success_data(
        api_client.list_score_snapshots(release["id"], BOARD))
    prov = find_live_snapshot(snapshots, "TOMATOMETER", "PROVISIONAL")
    assert prov is not None
    assert prov["total_count"] == 2
    assert prov["pct"] == 50
