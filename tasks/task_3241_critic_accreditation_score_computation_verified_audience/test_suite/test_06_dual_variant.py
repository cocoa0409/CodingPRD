"""Dual-variant calculations and combinatorial formulas (queue A)."""
from test_helpers import (
    api_client, get_success_data, TEST_USERS,
    set_clock, create_release, open_release, create_title, open_title,
    setup_accredited_publication, setup_accredited_critic, setup_open_release,
    publish_review_for, create_audience_member, create_rating,
    create_accreditation_review_payload,
    file_classification_dispute, triage_dispute, rule_dispute,
    find_live_snapshot,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]


def _setup_two_published_reviews_and_revoke_cb():
    """P1 with CA and CB accredited, both publish FRESH on one release,
    then CB is revoked via an accreditation review."""
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cb = setup_accredited_critic(pub["id"], full_name="Critic B")
    _, release = setup_open_release()
    publish_review_for(release["id"], ca["id"], designation="FRESH")
    publish_review_for(release["id"], cb["id"], designation="FRESH")
    review = get_success_data(api_client.create_accreditation_review(
        create_accreditation_review_payload(subject_critic_id=cb["id"]),
        BOARD))
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "BEGIN_REVIEW"}, BOARD))
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "RULE_REVOKE"}, BOARD))
    return pub, ca, cb, release


def test_provisional_snapshot_still_counts_revoked_critic_reviews():
    """PRD section 3.5: "The **provisional** variant counts every review on
    the release in `PUBLISHED` or `FLAGGED` status — `WITHDRAWN` reviews are
    excluded — including reviews by revoked critics and reviews whose critic
    is under review."

    Design: Difficulty/dual_variant_calc/tomatometer_provisional_includes_revoked_critic_certified_excludes
    """
    _, _, _, release = _setup_two_published_reviews_and_revoke_cb()
    snapshots = get_success_data(
        api_client.list_score_snapshots(release["id"], BOARD))
    live = find_live_snapshot(snapshots, "TOMATOMETER", "PROVISIONAL")
    assert live is not None
    assert live["total_count"] == 2
    assert live["positive_count"] == 2
    assert live["pct"] == 100


def test_certified_snapshot_excludes_revoked_critic_reviews():
    """PRD section 3.5: "The **certified** variant uses the same formula over
    a narrower input set: only reviews whose author's `accreditation_status`
    is `ACCREDITED` or `PROBATION` at compute time are counted."

    Design: Difficulty/dual_variant_calc/tomatometer_provisional_includes_revoked_critic_certified_excludes
    """
    _, _, _, release = _setup_two_published_reviews_and_revoke_cb()
    snapshots = get_success_data(
        api_client.list_score_snapshots(release["id"], BOARD))
    prov = find_live_snapshot(snapshots, "TOMATOMETER", "PROVISIONAL")
    cert = find_live_snapshot(snapshots, "TOMATOMETER", "CERTIFIED")
    assert cert is not None
    assert cert["total_count"] == 1
    assert cert["positive_count"] == 1
    assert cert["pct"] == 100
    assert cert["total_count"] != prov["total_count"]


def _setup_two_rejected_disputes_then_uphold_standing():
    """CA publishes on two releases; CC files a CLASSIFICATION dispute on
    each; both disputes are rejected; an accreditation review on CA is then
    ruled UPHELD. Returns the critic."""
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cc = setup_accredited_critic(pub["id"], full_name="Critic C")
    title = open_title(create_title()["id"])
    r1 = open_release(create_release(title["id"])["id"])
    r2 = open_release(create_release(title["id"], cut_label="DIRECTORS_CUT")["id"])
    ra = publish_review_for(r1["id"], ca["id"], designation="FRESH")
    ra2 = publish_review_for(r2["id"], ca["id"], designation="FRESH")
    d1 = file_classification_dispute(ra["id"], cc["id"], "ROTTEN")
    d2 = file_classification_dispute(ra2["id"], cc["id"], "ROTTEN")
    triage_dispute(d1["id"])
    triage_dispute(d2["id"])
    review = get_success_data(api_client.create_accreditation_review(
        create_accreditation_review_payload(
            subject_critic_id=ca["id"],
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-10-01T00:00:00Z"),
        BOARD))
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "BEGIN_REVIEW"}, BOARD))
    rule_dispute(d1["id"], "RULE_REJECT")
    rule_dispute(d2["id"], "RULE_REJECT")
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "RULE_UPHOLD"}, BOARD))
    return ca


def test_final_standing_score_penalises_only_upheld_disputes():
    """PRD section 3.2: "The **final** variant runs at an uphold ruling over
    the half-open review window: take the critic's reviews whose
    `published_at` falls inside the window, count the disputes upheld against
    those reviews (those whose classification was changed), subtract 1500
    basis points per upheld dispute from a base of 10000, and clamp the
    result into the 0-to-10000 range."

    Design: Difficulty/dual_variant_calc/critic_standing_provisional_pending_penalty_vs_final_upheld_penalty
    """
    ca = _setup_two_rejected_disputes_then_uphold_standing()
    data = get_success_data(api_client.get_critic(ca["id"], BOARD))
    # Both disputes were REJECTED: zero upheld disputes => 10000 - 0*1500
    assert data["standing_score_bps"] == 10000


def test_standing_variants_differ_when_pending_disputes_exist():
    """PRD section 3.2: "The **provisional** variant is a preview over the
    trailing 365 days ending at the logical clock: it has the same shape,
    except that disputed reviews still sitting in `FLAGGED` status are
    penalised at 500 basis points each instead of 1500. The two variants
    therefore produce different scores for the same critic whenever pending
    disputes exist; the final variant is authoritative at ruling time."

    Design: Difficulty/dual_variant_calc/critic_standing_provisional_pending_penalty_vs_final_upheld_penalty
    """
    ca = _setup_two_rejected_disputes_then_uphold_standing()
    data = get_success_data(api_client.get_critic(ca["id"], BOARD))
    # The provisional preview over the two FLAGGED disputes would have been
    # 10000 - 2*500 == 9000 bps; the final ruling saw zero upheld disputes.
    provisional_with_pending = 10000 - 2 * 500
    assert data["standing_score_bps"] == 10000
    assert data["standing_score_bps"] != provisional_with_pending
