"""Validation priority ordering and boundary precision (queue A)."""
from test_helpers import (
    api_client, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, create_release, open_release, create_title, open_title,
    setup_accredited_publication, setup_accredited_critic, setup_open_release,
    ingest_review, publish_review_for, revoke_critic_via_review,
    create_audience_member, make_critic_headers,
    make_audience_member_headers, create_ticket_verification_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]


def _setup_two_reviews_under_embargo_2026_09_10():
    """CA with one INGESTED review on each of two OPEN releases, both with
    embargo_until 2026-09-10T00:00:00Z."""
    set_clock("2026-09-09T23:59:59Z")
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"], full_name="Critic A")
    title = open_title(create_title()["id"])
    r1 = open_release(create_release(
        title["id"], embargo_until="2026-09-10T00:00:00Z")["id"])
    r2 = open_release(create_release(
        title["id"], cut_label="RERELEASE_2026",
        embargo_until="2026-09-10T00:00:00Z")["id"])
    ra = ingest_review(r1["id"], critic["id"], designation="FRESH")
    ra2 = ingest_review(r2["id"], critic["id"], designation="FRESH")
    return critic, r1, r2, ra, ra2


def test_publish_one_second_before_embargo_fails():
    """PRD section 3.4: "And the logical clock must have reached the
    release's `embargo_until` — publication at exactly the embargo instant is
    allowed, anything earlier is rejected with `ERR_EMBARGO_ACTIVE` (HTTP
    409)."

    Design: Difficulty/boundary_precision_check/embargo_publish_allowed_at_exact_lift_instant
    """
    critic, _, _, ra, _ = _setup_two_reviews_under_embargo_2026_09_10()
    resp = api_client.transition_review(
        ra["id"], {"action": "PUBLISH"}, make_critic_headers(critic["id"]))
    validate_error(resp, ApiErrorId.ERR_EMBARGO_ACTIVE)


def test_publish_at_exactly_embargo_until_succeeds():
    """PRD section 3.4: "And the logical clock must have reached the
    release's `embargo_until` — publication at exactly the embargo instant is
    allowed, anything earlier is rejected with `ERR_EMBARGO_ACTIVE` (HTTP
    409)."

    Design: Difficulty/boundary_precision_check/embargo_publish_allowed_at_exact_lift_instant
    """
    critic, _, _, _, ra2 = _setup_two_reviews_under_embargo_2026_09_10()
    set_clock("2026-09-10T00:00:00Z")
    published = get_success_data(api_client.transition_review(
        ra2["id"], {"action": "PUBLISH"},
        make_critic_headers(critic["id"])))
    assert published["status"] == "PUBLISHED"


def _setup_releases_at_certification_count_boundary():
    """Two releases on one title: R1 gets all five critics (2 top) FRESH;
    R2 gets only the first four critics FRESH."""
    set_clock()
    pub = setup_accredited_publication()
    critics = []
    for i in range(5):
        critics.append(setup_accredited_critic(
            pub["id"], is_top_critic=(i < 2), full_name=f"Critic {i + 1}"))
    title = open_title(create_title()["id"])
    r1 = open_release(create_release(title["id"])["id"])
    r2 = open_release(create_release(title["id"], cut_label="DIRECTORS_CUT")["id"])
    for critic in critics:
        publish_review_for(r1["id"], critic["id"], designation="FRESH")
    for critic in critics[:4]:
        publish_review_for(r2["id"], critic["id"], designation="FRESH")
    return r1, r2


def test_certification_granted_at_exactly_five_reviews():
    """PRD section 3.5: "Then the gates run in sequence: if `N` is fewer than
    5, certification is `NONE` and evaluation stops. Otherwise, if `T` is
    fewer than 2, certification is `NONE` and evaluation stops. Otherwise, a
    percentage of at least 75 earns `CERTIFIED_FRESH`".
    PRD section 3.5: "All boundaries are inclusive exactly as written."

    Design: Difficulty/boundary_precision_check/certification_minimum_review_count_at_exactly_five
    """
    r1, _ = _setup_releases_at_certification_count_boundary()
    data = get_success_data(api_client.get_release(r1["id"], BOARD))
    assert data["tomatometer_pct"] == 100
    assert data["certification"] == "CERTIFIED_FRESH"


def test_certification_denied_at_four_reviews_despite_perfect_score():
    """PRD section 3.5: "Then the gates run in sequence: if `N` is fewer than
    5, certification is `NONE` and evaluation stops."

    Design: Difficulty/boundary_precision_check/certification_minimum_review_count_at_exactly_five
    """
    _, r2 = _setup_releases_at_certification_count_boundary()
    data = get_success_data(api_client.get_release(r2["id"], BOARD))
    assert data["tomatometer_pct"] == 100
    assert data["certification"] == "NONE"
