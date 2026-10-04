"""Combinatorial formulas: bombing index and certification gate order."""
from test_helpers import (
    api_client, get_success_data, TEST_USERS,
    set_clock, setup_accredited_publication, setup_accredited_critic,
    setup_open_release, publish_review_for, create_audience_member,
    create_rating, find_live_snapshot,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]


def _setup_ten_fresh_negative_ratings():
    """Ten freshly registered members each rate the release 1 star."""
    set_clock()
    _, release = setup_open_release()
    for _ in range(10):
        member = create_audience_member()
        create_rating(release["id"], member["id"], 1)
    return release


def test_bombing_index_capped_weighted_sum_computes_7200_bps():
    """PRD section 3.7: "The index is the smaller of 10000 and the weighted
    sum: 20 times `V`, plus 40 times the new-account percent, plus 30 times
    the negative-skew percent."
    PRD section 3.7: "An index of at least 6000 basis points marks the
    incident as auto-flagged, which is informational only; the incident's
    `status` remains `OPEN` until an administrator acts."

    Design: Difficulty/combinatorial_formula/bombing_index_capped_weighted_sum_three_inputs
    """
    release = _setup_ten_fresh_negative_ratings()
    incident = get_success_data(
        api_client.create_bombing_incident(release["id"], ADMIN))
    # V=10, N=10 (all accounts created in the window), S=10 (all 1 star):
    # min(10000, 20*10 + 40*100 + 30*100) == min(10000, 7200) == 7200
    assert incident["detection_index_bps"] == 7200


def test_bombing_incident_auto_flagged_stays_open():
    """PRD section 3.7: "An index of at least 6000 basis points marks the
    incident as auto-flagged, which is informational only; the incident's
    `status` remains `OPEN` until an administrator acts."

    Design: Difficulty/combinatorial_formula/bombing_index_capped_weighted_sum_three_inputs
    """
    release = _setup_ten_fresh_negative_ratings()
    incident = get_success_data(
        api_client.create_bombing_incident(release["id"], ADMIN))
    assert incident["detection_index_bps"] == 7200
    assert incident["detection_index_bps"] >= 6000
    assert incident["status"] == "OPEN"


def _setup_five_review_release_one_top_critic():
    """Five accredited critics, only the first a top critic; the top critic
    publishes ROTTEN, the other four publish FRESH (4/5 == 80 pct, T == 1)."""
    set_clock()
    pub = setup_accredited_publication()
    top = setup_accredited_critic(pub["id"], is_top_critic=True,
                                  full_name="Top Critic")
    others = [setup_accredited_critic(pub["id"], full_name=f"Critic {i}")
              for i in range(2, 6)]
    _, release = setup_open_release()
    publish_review_for(release["id"], top["id"], designation="ROTTEN")
    for critic in others:
        publish_review_for(release["id"], critic["id"], designation="FRESH")
    return release


def test_certification_top_critic_shortfall_yields_none_despite_80_pct():
    """PRD section 3.5: "Then the gates run in sequence: if `N` is fewer than
    5, certification is `NONE` and evaluation stops. Otherwise, if `T` is
    fewer than 2, certification is `NONE` and evaluation stops. Otherwise, a
    percentage of at least 75 earns `CERTIFIED_FRESH`; a percentage of at
    most 60 earns `CERTIFIED_ROTTEN`; anything in between is `NONE`."

    Design: Difficulty/combinatorial_formula/certification_gate_order_top_critic_shortfall_beats_score
    """
    release = _setup_five_review_release_one_top_critic()
    data = get_success_data(api_client.get_release(release["id"], BOARD))
    assert data["tomatometer_pct"] == 80
    # T == 1 < 2 fires gate 2 before the percentage gate
    assert data["certification"] == "NONE"


def test_certified_snapshot_counts_five_reviews_with_top_critic_shortfall():
    """PRD section 3.5: "The **certified** variant uses the same formula over
    a narrower input set: only reviews whose author's `accreditation_status`
    is `ACCREDITED` or `PROBATION` at compute time are counted."
    PRD section 3.5: "Because accreditation changes alter the certified input
    set and the score in turn alters certification, this evaluation order is
    the only sanctioned order — implementations must not interleave the
    steps."

    Design: Difficulty/combinatorial_formula/certification_gate_order_top_critic_shortfall_beats_score
    """
    release = _setup_five_review_release_one_top_critic()
    snapshots = get_success_data(
        api_client.list_score_snapshots(release["id"], BOARD))
    cert = find_live_snapshot(snapshots, "TOMATOMETER", "CERTIFIED")
    assert cert is not None
    assert cert["positive_count"] == 4
    assert cert["total_count"] == 5
    assert cert["pct"] == 80
