"""Role gating and optimistic-concurrency behavior (queue B)."""
from test_helpers import (
    api_client, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, create_audience_member, setup_accredited_publication,
    setup_accredited_critic, setup_open_release, publish_review_for,
    file_classification_dispute, file_score_display_dispute, triage_dispute,
    create_ticket_verification_payload, make_audience_member_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]
STUDIO = TEST_USERS["studio_rep_headers"]


def test_audience_member_cannot_open_bombing_incident():
    """PRD section 2.1: "A request whose declared role is not permitted for
    the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD section 3.7: "A `PlatformAdmin` opens a review-bombing incident
    against a release".

    Design: Corner/rbac/audience_member_cannot_open_bombing_incident
    """
    set_clock()
    _, release = setup_open_release()
    member = create_audience_member()
    resp = api_client.create_bombing_incident(
        release["id"], make_audience_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_studio_rep_cannot_transition_disputes():
    """PRD section 3.8: "A new dispute starts `FILED`. The
    `AccreditationBoard` triages it, moving it to `TRIAGED`".
    PRD section 2.1: "A request whose declared role is not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/studio_rep_cannot_transition_disputes
    """
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"])
    _, release = setup_open_release()
    publish_review_for(release["id"], critic["id"], designation="FRESH")
    dispute = file_score_display_dispute(release["id"])
    resp = api_client.transition_dispute(
        dispute["id"], {"action": "TRIAGE"}, STUDIO)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_platform_admin_can_verify_ticket():
    """PRD section 3.6: "A `PlatformAdmin` then rules on it: verifying
    requires the `showtime_at` to fall inside the release's theatrical window
    as a closed interval".

    Design: Corner/rbac/platform_admin_cannot_verify_ticket_as_member_action_boundary
    """
    set_clock()
    _, release = setup_open_release()
    member = create_audience_member()
    tv = get_success_data(api_client.create_ticket_verification(
        release["id"],
        create_ticket_verification_payload(member["id"]),
        make_audience_member_headers(member["id"])))
    verified = get_success_data(api_client.transition_ticket_verification(
        tv["id"], {"action": "VERIFY"}, ADMIN))
    assert verified["status"] == "VERIFIED"


def test_stale_release_version_on_score_recalculation_returns_412():
    """PRD section 2.6: "A manual score recalculation against a release must
    carry `expected_release_version` matching the release's current
    `version`. If another writer has advanced the release's version since the
    client last read it — for example by publishing or withdrawing a review,
    which legitimately supersedes the client's view of the score input set —
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/validations/stale_release_version_on_score_recalculation_returns_412
    """
    set_clock()
    _, release = setup_open_release()
    observed = get_success_data(api_client.get_release(release["id"], ADMIN))
    stale_version = observed["version"]
    get_success_data(api_client.transition_release(
        release["id"], {"action": "CLOSE"}, ADMIN))
    resp = api_client.recalculate_release_score(
        release["id"], {"expected_release_version": stale_version}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_dispute_ruling_occ_stale_dispute_version_returns_412():
    """PRD section 2.6: "A dispute transition (triage, return, or ruling)
    must carry `expected_dispute_version` matching the dispute's current
    `version`. A mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP
    412)".
    PRD section 3.8: "Every ruling transition carries
    `expected_dispute_version` under the OCC rule of §2.6 and increments the
    dispute's `version` by 1."

    Design: Corner/endpoints/dispute_ruling_occ_stale_dispute_version_returns_412
    """
    set_clock()
    pub = setup_accredited_publication()
    ca = setup_accredited_critic(pub["id"], full_name="Critic A")
    cc = setup_accredited_critic(pub["id"], full_name="Critic C")
    _, release = setup_open_release()
    ra = publish_review_for(release["id"], ca["id"], designation="FRESH")
    dispute = file_classification_dispute(ra["id"], cc["id"], "ROTTEN")
    v0 = dispute["version"]
    triaged = triage_dispute(dispute["id"])
    assert triaged["version"] == v0 + 1

    resp = api_client.transition_dispute(
        dispute["id"],
        {"action": "RULE_UPHOLD", "expected_dispute_version": v0},
        BOARD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    current = get_success_data(api_client.get_dispute(dispute["id"], BOARD))
    assert current["status"] == "TRIAGED"


def test_score_display_dispute_upheld_forces_snapshot_supersession():
    """PRD section 3.8: "An uphold ruling on a score-display dispute forces a
    fresh recalculation of the subject release's scores, refreshing both
    `tomatometer_pct` and `audience_score_pct` with new snapshots."
    PRD section 2.7: "The previous snapshot for the same release, scope, and
    variant is marked `superseded` (a boolean defaulting to false)."

    Design: Corner/endpoints/score_display_dispute_upheld_forces_snapshot_supersession
    """
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"])
    _, release = setup_open_release()
    publish_review_for(release["id"], critic["id"], designation="FRESH")
    dispute = file_score_display_dispute(release["id"])
    triage_dispute(dispute["id"])

    current = get_success_data(api_client.get_dispute(dispute["id"], BOARD))
    get_success_data(api_client.transition_dispute(
        dispute["id"],
        {"action": "RULE_UPHOLD",
         "expected_dispute_version": current["version"]},
        BOARD))

    snapshots, _ = get_success_data(
        api_client.list_score_snapshots(release["id"], BOARD)), None
    snaps = snapshots
    provisional = [s for s in snaps
                   if s["scope"] == "TOMATOMETER" and s["variant"] == "PROVISIONAL"]
    live = [s for s in provisional if s["superseded"] is False]
    old = [s for s in provisional if s["superseded"] is True]
    assert len(live) == 1, f"Expected exactly one live PROVISIONAL snapshot, got {len(live)}"
    assert len(old) >= 1, "Expected the publish-time snapshot to be superseded"
    assert live[0]["positive_count"] == 1
    assert live[0]["total_count"] == 1
    assert live[0]["pct"] == 100
