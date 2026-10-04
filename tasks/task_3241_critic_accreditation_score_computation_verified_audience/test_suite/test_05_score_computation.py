"""Score computation behavior (queue B, calculations / consistency)."""
from test_helpers import (
    api_client, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, create_audience_member, setup_accredited_publication,
    setup_accredited_critic, setup_open_release, publish_review_for,
    ingest_review, publish_review, setup_verified_rating, create_rating,
    make_critic_headers, create_title, open_title, create_release,
    open_release,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]


def test_audience_score_verified_only_counts_four_plus_stars():
    """PRD section 3.6: "The **verified-only** variant, which powers the
    public `audience_score_pct`, counts ratings in `VERIFIED` status: the
    percentage is one hundred times the number of those ratings with `stars`
    of at least 4, divided by the total verified count, rounded half-up once
    to an integer percent."

    Design: Corner/calculations/audience_score_verified_only_counts_four_plus_stars
    """
    set_clock()
    _, release = setup_open_release()
    m1 = create_audience_member()
    m2 = create_audience_member()
    m3 = create_audience_member()
    setup_verified_rating(release["id"], m1["id"], 5)
    setup_verified_rating(release["id"], m2["id"], 4)
    setup_verified_rating(release["id"], m3["id"], 3)
    data = get_success_data(api_client.get_release(release["id"], ADMIN))
    # 2 of 3 ratings have stars >= 4: round_half_up(100*2/3) == 67
    assert data["audience_score_pct"] == 67


def test_tomatometer_empty_input_set_reports_null_not_zero():
    """PRD section 2.7: "When a score's input set is empty, the percentage is
    null — it is never reported as 0 — and attempting to persist a snapshot
    from an empty input set is rejected with `ERR_SCORE_NOT_COMPUTABLE` (HTTP
    409)."
    PRD section 3.3: "A new release starts in `UPCOMING` status, carries
    `audience_display_suspended` false, and has null `tomatometer_pct`, null
    `audience_score_pct`, and `certification` of `NONE` until its score input
    sets become non-empty".

    Design: Corner/calculations/tomatometer_empty_input_set_reports_null_not_zero
    """
    set_clock()
    _, release = setup_open_release()
    observed = get_success_data(api_client.get_release(release["id"], ADMIN))
    assert observed["tomatometer_pct"] is None
    resp = api_client.recalculate_release_score(
        release["id"],
        {"expected_release_version": observed["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SCORE_NOT_COMPUTABLE)
    after = get_success_data(api_client.get_release(release["id"], ADMIN))
    assert after["tomatometer_pct"] is None


def test_certification_threshold_boundary_at_exactly_seventy_five():
    """PRD section 3.5: "Otherwise, a percentage of at least 75 earns
    `CERTIFIED_FRESH`; a percentage of at most 60 earns `CERTIFIED_ROTTEN`;
    anything in between is `NONE`. All boundaries are inclusive exactly as
    written."

    Design: Corner/calculations/certification_threshold_boundary_at_exactly_seventy_five
    """
    set_clock()
    pub = setup_accredited_publication()
    critics = []
    for i in range(8):
        critics.append(setup_accredited_critic(
            pub["id"], is_top_critic=(i < 2), full_name=f"Critic {i}"))
    title = create_title()
    open_title(title["id"])
    # R1: 6 FRESH + 2 ROTTEN of 8 = exactly 75 pct
    r1 = open_release(create_release(title["id"])["id"])
    for i, critic in enumerate(critics):
        publish_review_for(r1["id"], critic["id"],
                           designation="FRESH" if i < 6 else "ROTTEN")
    # R2: 5 FRESH + 3 ROTTEN of 8 = round_half_up(62.5) == 63 pct
    r2 = open_release(create_release(title["id"], cut_label="DIRECTORS_CUT")["id"])
    for i, critic in enumerate(critics):
        publish_review_for(r2["id"], critic["id"],
                           designation="FRESH" if i < 5 else "ROTTEN")

    d1 = get_success_data(api_client.get_release(r1["id"], BOARD))
    assert d1["tomatometer_pct"] == 75
    assert d1["certification"] == "CERTIFIED_FRESH"

    d2 = get_success_data(api_client.get_release(r2["id"], BOARD))
    assert d2["tomatometer_pct"] == 63
    assert d2["certification"] == "NONE"


def test_tomatometer_pct_tracks_live_input_set_on_withdraw():
    """PRD section 3.5: "The tomatometer is recomputed on every event that
    changes its input set: a review publish, a withdrawal, a reclassification
    via an upheld dispute, a critic revocation or reinstatement cascade, an
    upheld score-display dispute, or a manual recalculation request."
    PRD section 3.5: "The **provisional** variant counts every review on the
    release in `PUBLISHED` or `FLAGGED` status — `WITHDRAWN` reviews are
    excluded".

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_score_pct
    """
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cb = setup_accredited_critic(pub["id"], full_name="Critic B")
    _, release = setup_open_release()
    publish_review_for(release["id"], ca["id"], designation="FRESH")
    rb = publish_review_for(release["id"], cb["id"], designation="ROTTEN")

    mid = get_success_data(api_client.get_release(release["id"], ADMIN))
    assert mid["tomatometer_pct"] == 50

    get_success_data(api_client.transition_review(
        rb["id"], {"action": "WITHDRAW"}, make_critic_headers(cb["id"])))
    after = get_success_data(api_client.get_release(release["id"], ADMIN))
    assert after["tomatometer_pct"] == 100


def test_immediate_consistency_on_publish_score_visible_in_same_flow():
    """PRD section 3.5: "The tomatometer is recomputed on every event that
    changes its input set: a review publish, a withdrawal, a reclassification
    via an upheld dispute, a critic revocation or reinstatement cascade, an
    upheld score-display dispute, or a manual recalculation request."

    Design: Corner/consistency_model/immediate_consistency_on_publish_score_visible_in_same_flow
    """
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"])
    _, release = setup_open_release()
    review = ingest_review(release["id"], critic["id"], designation="FRESH")
    publish_review(review["id"], critic["id"])
    data = get_success_data(api_client.get_release(release["id"], ADMIN))
    assert data["tomatometer_pct"] == 100
