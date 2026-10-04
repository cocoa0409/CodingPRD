"""Compensating invariants (queue A): conserved counts across revoke/re-apply
and withdraw/re-ingest pairs."""
from test_helpers import (
    api_client, validate_paginated, get_success_data, TEST_USERS,
    set_clock, create_critic, accredit_critic,
    setup_accredited_publication, setup_accredited_critic, setup_open_release,
    publish_review_for, ingest_review, publish_review,
    revoke_critic_via_review, find_live_snapshot, make_critic_headers,
    create_accreditation_review_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]


def test_withdraw_then_reingest_is_allowed_and_counted():
    """PRD section 3.4: "a critic may hold at most one review not in
    `WITHDRAWN` status per release; a second live review is rejected with
    `ERR_DUPLICATE_REVIEW` (HTTP 409)."

    Design: Difficulty/compensating_invariant/review_withdraw_and_republish_conserves_non_withdrawn_review_count
    """
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cb = setup_accredited_critic(pub["id"], full_name="Critic B")
    _, release = setup_open_release()
    ra = publish_review_for(release["id"], ca["id"], designation="FRESH")
    publish_review_for(release["id"], cb["id"], designation="FRESH")

    withdrawn = get_success_data(api_client.transition_review(
        ra["id"], {"action": "WITHDRAW"}, make_critic_headers(ca["id"])))
    assert withdrawn["status"] == "WITHDRAWN"

    # After withdrawal the (critic, release) slot is free again: re-ingest.
    ra2 = ingest_review(release["id"], ca["id"], designation="ROTTEN")
    published = publish_review(ra2["id"], ca["id"])
    assert published["status"] == "PUBLISHED"


def test_withdraw_reingest_conserves_live_plus_withdrawn_total():
    """PRD section 3.5: "The **provisional** variant counts every review on
    the release in `PUBLISHED` or `FLAGGED` status — `WITHDRAWN` reviews are
    excluded".
    PRD section 3.4: "The author may withdraw a review from either
    `PUBLISHED` or `FLAGGED`, moving it to the terminal `WITHDRAWN` status".

    Design: Difficulty/compensating_invariant/review_withdraw_and_republish_conserves_non_withdrawn_review_count
    """
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cb = setup_accredited_critic(pub["id"], full_name="Critic B")
    _, release = setup_open_release()
    ra = publish_review_for(release["id"], ca["id"], designation="FRESH")
    publish_review_for(release["id"], cb["id"], designation="FRESH")

    get_success_data(api_client.transition_review(
        ra["id"], {"action": "WITHDRAW"}, make_critic_headers(ca["id"])))
    mid, _ = validate_paginated(api_client.list_reviews(
        BOARD, params={"release_id": release["id"]}))
    live_mid = [r for r in mid if r["status"] in ("PUBLISHED", "FLAGGED")]
    gone_mid = [r for r in mid if r["status"] == "WITHDRAWN"]
    assert len(live_mid) == 1
    assert len(gone_mid) == 1
    assert len(live_mid) + len(gone_mid) == 2

    ra2 = ingest_review(release["id"], ca["id"], designation="ROTTEN")
    publish_review(ra2["id"], ca["id"])

    final, _ = validate_paginated(api_client.list_reviews(
        BOARD, params={"release_id": release["id"]}))
    live = [r for r in final if r["status"] in ("PUBLISHED", "FLAGGED")]
    gone = [r for r in final if r["status"] == "WITHDRAWN"]
    assert len(live) == 2
    assert len(gone) == 1
    assert len(live) + len(gone) == 3

    snapshots = get_success_data(
        api_client.list_score_snapshots(release["id"], BOARD))
    prov = find_live_snapshot(snapshots, "TOMATOMETER", "PROVISIONAL")
    assert prov["total_count"] == 2
    # CB FRESH + CA's replacement ROTTEN => 1 fresh of 2
    assert prov["pct"] == 50


def _setup_two_critic_publication_with_one_revoked():
    """P1 ACCREDITED with CA and CB accredited (count 2); CA revoked."""
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cb = setup_accredited_critic(pub["id"], full_name="Critic B")
    revoke_critic_via_review(ca["id"])
    return pub, ca, cb


def test_publication_count_decremented_exactly_once_on_revocation():
    """PRD section 3.1: "Whether it arrives via an accreditation review ruled
    against the critic directly, or via revocation of the employing
    publication, the effect is identical: the publication's
    `accredited_critic_count` is decremented exactly once".

    Design: Difficulty/compensating_invariant/critic_revoke_then_reinstate_conserves_accredited_critic_count
    """
    pub, ca, _ = _setup_two_critic_publication_with_one_revoked()
    data = get_success_data(api_client.get_publication(pub["id"], BOARD))
    assert data["accredited_critic_count"] == 1


def test_reapply_and_reaccredit_restores_count_to_pre_revocation_value():
    """PRD section 3.1: "Re-application followed by re-accreditation restores
    the publication's `accredited_critic_count` exactly once per critic."
    PRD section 3.1: "A successful accreditation increments the employing
    publication's `accredited_critic_count`."

    Design: Difficulty/compensating_invariant/critic_revoke_then_reinstate_conserves_accredited_critic_count
    """
    pub, ca, _ = _setup_two_critic_publication_with_one_revoked()
    get_success_data(api_client.transition_critic(
        ca["id"], {"action": "REAPPLY"}, make_critic_headers(ca["id"])))
    get_success_data(api_client.transition_critic(
        ca["id"], {"action": "ACCREDIT"}, BOARD))
    data = get_success_data(api_client.get_publication(pub["id"], BOARD))
    assert data["accredited_critic_count"] == 2
