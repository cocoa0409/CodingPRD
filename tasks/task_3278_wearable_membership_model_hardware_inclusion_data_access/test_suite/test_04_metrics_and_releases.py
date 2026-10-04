"""Metrics ingestion, algorithm releases, and the publish recompute cascade."""
from test_helpers import (
    ApiErrorId,
    create_ingest_payload,
    create_release_payload,
    get_success_data,
    make_coach_headers,
    make_member_headers,
    make_platform_admin_headers,
    set_clock,
    setup_member_with_active_device,
    setup_member_with_metric_set,
    setup_suppressed_member,
    setup_team_membership_with_consent,
    setup_team_with_membership,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestIngestGuards:
    def test_ingest_requires_active_device(self, api, anonymous_headers):
        """PRD: "Activation is performed by the owning member and requires the
        device to be PROVISIONED; attempting to activate a device in any other
        state — or to ingest from or fault-report a device that is not ACTIVE —
        is rejected with ERR_DEVICE_NOT_ACTIVE."

        Design: Corner/validations/ingest_requires_active_device
        """
        from test_helpers import create_member_with_term, provision_device_for

        member, term = create_member_with_term()
        device = provision_device_for(member["id"], term["id"], serial_number="SN-V4")
        resp = api.ingest_metrics(
            device["id"], create_ingest_payload(), make_member_headers(member["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_ACTIVE, expected_status=409)

    def test_duplicate_ingest_same_day_rejected(self, api, anonymous_headers):
        """PRD: "A member may hold at most one metric set per day — a duplicate
        day_on for the same member is rejected with ERR_DUPLICATE_METRIC_DAY."

        Design: Corner/state_machines/duplicate_ingest_same_day_rejected
        """
        member, term, device, metric_set = setup_member_with_metric_set()
        resp = api.ingest_metrics(
            device["id"],
            create_ingest_payload(avg_hr=90, hrv_ms=90, resting_hr=55, sleep_minutes=400),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_METRIC_DAY, expected_status=409)

    def test_duplicate_ingest_leaves_original_metric_set_unchanged(self, api, anonymous_headers):
        """PRD: "A member may hold at most one metric set per day — a duplicate
        day_on for the same member is rejected with ERR_DUPLICATE_METRIC_DAY."
        PRD: "Under the baseline (algorithm version 1, used when no release is
        PUBLISHED): strain_score is the average heart rate divided by ten, capped
        at 21, rounded half-up to one decimal; recovery_score is the heart-rate
        variability expressed as a percentage of the sum of the variability and
        the resting heart rate — hrv_ms times one hundred divided by (hrv_ms plus
        resting_hr) — capped at 100 and rounded half-up to a whole number;
        sleep_performance_pct is the day's sleep minutes expressed as a percentage
        of a 480-minute full night, capped at 100 and rounded half-up to a whole
        number."

        Design: Corner/state_machines/duplicate_ingest_same_day_rejected
        """
        member, term, device, metric_set = setup_member_with_metric_set()
        api.ingest_metrics(
            device["id"],
            create_ingest_payload(avg_hr=90, hrv_ms=90, resting_hr=55, sleep_minutes=400),
            make_member_headers(member["id"]),
        )
        data, _ = validate_paginated(
            api.list_member_metric_sets(member["id"], make_member_headers(member["id"]))
        )
        assert len(data) == 1
        assert data[0]["avg_hr"] == 100
        assert data[0]["strain_score"] == 10.0
        assert data[0]["recovery_score"] == 67
        assert data[0]["sleep_performance_pct"] == 100


class TestMetricRecomputeOnPublish:
    def test_metric_scores_baseline_vs_published_recompute(self, api, anonymous_headers):
        """PRD: "Once any release is PUBLISHED (version 2 or later), all three
        denominators and the recovery shape change: strain_score divides the
        average heart rate by nine instead of ten; recovery_score first computes
        the same variability percentage, then scales it by nine-tenths and adds
        five, before the same cap and rounding; sleep_performance_pct is measured
        against 450 minutes instead of 480."

        Design: Difficulty/dual_variant_calc/metric_scores_baseline_vs_published_recompute
        """
        member, term, device, metric_set = setup_member_with_metric_set(
            avg_hr=140, hrv_ms=80, resting_hr=50, sleep_minutes=360
        )
        headers = make_member_headers(member["id"])
        data, _ = validate_paginated(api.list_member_metric_sets(member["id"], headers))
        assert data[0]["algorithm_version"] == 1
        assert data[0]["strain_score"] == 14.0
        assert data[0]["recovery_score"] == 62
        assert data[0]["sleep_performance_pct"] == 75
        assert data[0]["interpretation_status"] == "CURRENT"

        release = validate_success(
            api.create_algorithm_release(
                create_release_payload(version=2, requires_member_ack=True),
                make_platform_admin_headers(),
            ),
            expected_status=201,
        )
        validate_success(
            api.publish_algorithm_release(release["id"], make_platform_admin_headers())
        )
        data, _ = validate_paginated(api.list_member_metric_sets(member["id"], headers))
        assert data[0]["algorithm_version"] == 2
        assert data[0]["strain_score"] == 15.6
        assert data[0]["recovery_score"] == 60
        assert data[0]["sleep_performance_pct"] == 80
        assert data[0]["interpretation_status"] == "RECOMPUTED"

    def test_publish_suppresses_member_when_recovery_changes(self, api, anonymous_headers):
        """PRD: "when the release's requires_member_ack is true and any of a
        member's recovery_score values changed during the sweep, that member's
        data_sharing_posture flips from NORMAL to SUPPRESSED."

        Design: Difficulty/dual_variant_calc/metric_scores_baseline_vs_published_recompute
        """
        member, term, device, metric_set = setup_member_with_metric_set(
            avg_hr=140, hrv_ms=80, resting_hr=50, sleep_minutes=360
        )
        release = validate_success(
            api.create_algorithm_release(
                create_release_payload(version=2, requires_member_ack=True),
                make_platform_admin_headers(),
            ),
            expected_status=201,
        )
        validate_success(
            api.publish_algorithm_release(release["id"], make_platform_admin_headers())
        )
        member_after = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert member_after["data_sharing_posture"] == "SUPPRESSED"


class TestRecomputeCycleAcrossTwoReleases:
    def test_metric_set_recompute_cycle_across_two_releases(self, api, anonymous_headers):
        """PRD: "Hop one sweeps every metric set whose algorithm_version is older
        than the newly published version: each such set is marked STALE and then
        immediately recomputed within the same sweep — processed in chronological
        order by day_on ascending with ties broken by created_at ascending —
        landing in RECOMPUTED with algorithm_version set to the published
        version".

        Design: Difficulty/non_linear_state_machine/metric_set_recompute_cycle_across_two_releases
        """
        member, term, device, metric_set = setup_member_with_metric_set(
            avg_hr=100, hrv_ms=100, resting_hr=50, sleep_minutes=480
        )
        admin = make_platform_admin_headers()
        rel2 = validate_success(
            api.create_algorithm_release(
                create_release_payload(version=2, requires_member_ack=True), admin
            ),
            expected_status=201,
        )
        validate_success(api.publish_algorithm_release(rel2["id"], admin))
        rel3 = validate_success(
            api.create_algorithm_release(
                create_release_payload(version=3, requires_member_ack=False), admin
            ),
            expected_status=201,
        )
        validate_success(api.publish_algorithm_release(rel3["id"], admin))
        data, _ = validate_paginated(
            api.list_member_metric_sets(member["id"], make_member_headers(member["id"]))
        )
        assert data[0]["interpretation_status"] == "RECOMPUTED"
        assert data[0]["algorithm_version"] == 3

    def test_second_publish_supersedes_first_release(self, api, anonymous_headers):
        """PRD: "on publication published_on is stamped with today and any
        previously PUBLISHED release becomes SUPERSEDED (a terminal state)."

        Design: Difficulty/non_linear_state_machine/metric_set_recompute_cycle_across_two_releases
        """
        admin = make_platform_admin_headers()
        rel2 = validate_success(
            api.create_algorithm_release(
                create_release_payload(version=2, requires_member_ack=True), admin
            ),
            expected_status=201,
        )
        validate_success(api.publish_algorithm_release(rel2["id"], admin))
        rel3 = validate_success(
            api.create_algorithm_release(
                create_release_payload(version=3, requires_member_ack=False), admin
            ),
            expected_status=201,
        )
        published = validate_success(api.publish_algorithm_release(rel3["id"], admin))
        assert published["release_status"] == "PUBLISHED"
        assert published["published_on"] == "2026-09-01"

    def test_no_ack_required_release_does_not_change_posture(self, api, anonymous_headers):
        """PRD: "when the release's requires_member_ack is true and any of a
        member's recovery_score values changed during the sweep, that member's
        data_sharing_posture flips from NORMAL to SUPPRESSED."

        Design: Difficulty/non_linear_state_machine/metric_set_recompute_cycle_across_two_releases
        """
        # v2 publish with requires_member_ack=true suppresses the member;
        # v3 publish with requires_member_ack=false leaves posture as-is.
        member, term, device, metric_set, rel2 = setup_suppressed_member()
        admin = make_platform_admin_headers()
        rel3 = validate_success(
            api.create_algorithm_release(
                create_release_payload(version=3, requires_member_ack=False), admin
            ),
            expected_status=201,
        )
        validate_success(api.publish_algorithm_release(rel3["id"], admin))
        member_after = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert member_after["data_sharing_posture"] == "SUPPRESSED"


class TestPublishCascadeToDashboard:
    def test_publish_cascade_metric_member_dashboard(self, api, anonymous_headers):
        """PRD: "when the release's requires_member_ack is true and any of a
        member's recovery_score values changed during the sweep, that member's
        data_sharing_posture flips from NORMAL to SUPPRESSED."
        PRD: "When the row is emitted and the member's data_sharing_posture is
        SUPPRESSED, suppressed is true and all three of strain_score,
        recovery_score, and sleep_performance_pct are null — suppression overrides
        consent."

        Design: Difficulty/transitive_cascade/publish_cascade_metric_member_dashboard
        """
        member, term, device, metric_set = setup_member_with_metric_set(
            avg_hr=140, hrv_ms=80, resting_hr=50, sleep_minutes=360
        )
        team, membership = setup_team_membership_with_consent(
            member["id"], "coach-1", "RECOVERY", expires_on="2027-01-01"
        )
        admin = make_platform_admin_headers()
        release = validate_success(
            api.create_algorithm_release(
                create_release_payload(version=2, requires_member_ack=True), admin
            ),
            expected_status=201,
        )
        validate_success(api.publish_algorithm_release(release["id"], admin))
        dash = validate_success(
            api.get_team_dashboard(team["id"], make_coach_headers("coach-1"))
        )
        assert len(dash["rows"]) == 1
        row = dash["rows"][0]
        assert row["membership_id"] == membership["id"]
        assert row["suppressed"] is True
        assert row["recovery_score"] is None
        assert row["strain_score"] is None
        assert row["sleep_performance_pct"] is None

    def test_publish_cascade_recomputes_metrics_and_suppresses_member(self, api, anonymous_headers):
        """PRD: "Hop one sweeps every metric set whose algorithm_version is older
        than the newly published version: each such set is marked STALE and then
        immediately recomputed within the same sweep".
        PRD: "Hop two guards member trust: when the release's requires_member_ack
        is true and any of a member's recovery_score values changed during the
        sweep, that member's data_sharing_posture flips from NORMAL to
        SUPPRESSED."

        Design: Difficulty/transitive_cascade/publish_cascade_metric_member_dashboard
        """
        member, term, device, metric_set = setup_member_with_metric_set(
            avg_hr=140, hrv_ms=80, resting_hr=50, sleep_minutes=360
        )
        setup_team_membership_with_consent(
            member["id"], "coach-1", "RECOVERY", expires_on="2027-01-01"
        )
        admin = make_platform_admin_headers()
        release = validate_success(
            api.create_algorithm_release(
                create_release_payload(version=2, requires_member_ack=True), admin
            ),
            expected_status=201,
        )
        validate_success(api.publish_algorithm_release(release["id"], admin))
        data, _ = validate_paginated(
            api.list_member_metric_sets(member["id"], make_member_headers(member["id"]))
        )
        assert data[0]["interpretation_status"] == "RECOMPUTED"
        assert data[0]["algorithm_version"] == 2
        member_after = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert member_after["data_sharing_posture"] == "SUPPRESSED"


class TestConsentGrantWhileSuppressed:
    def test_consent_grant_suppression_safety_beats_temporal(self, api, anonymous_headers):
        """PRD: "Granting while the member's data_sharing_posture is SUPPRESSED is
        refused with ERR_DATA_SHARING_SUPPRESSED — suppression overrides consent
        until the member acknowledges the latest release."
        PRD: "An expires_on in the past is rejected with ERR_GRANT_WINDOW_INVALID".

        Design: Difficulty/priority_pair_validation_conflict/consent_grant_suppression_safety_beats_temporal
        """
        member, term, device, metric_set, release = setup_suppressed_member()
        set_clock("2026-09-02T00:00:00Z")
        team, membership = setup_team_with_membership(member["id"], "coach-1")
        resp = api.grant_or_revoke_consent(
            membership["id"],
            {
                "scope": "SLEEP",
                "action": "GRANT",
                "expected_team_membership_version": membership["version"],
                "expires_on": "2026-09-01",
            },
            make_member_headers(member["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_DATA_SHARING_SUPPRESSED, expected_status=403
        )

    def test_consent_grant_while_suppressed_leaves_membership_version_unchanged(self, api, anonymous_headers):
        """PRD: "Granting while the member's data_sharing_posture is SUPPRESSED is
        refused with ERR_DATA_SHARING_SUPPRESSED — suppression overrides consent
        until the member acknowledges the latest release."

        Design: Difficulty/priority_pair_validation_conflict/consent_grant_suppression_safety_beats_temporal
        """
        member, term, device, metric_set, release = setup_suppressed_member()
        set_clock("2026-09-02T00:00:00Z")
        team, membership = setup_team_with_membership(member["id"], "coach-1")
        api.grant_or_revoke_consent(
            membership["id"],
            {
                "scope": "SLEEP",
                "action": "GRANT",
                "expected_team_membership_version": membership["version"],
                "expires_on": "2026-09-01",
            },
            make_member_headers(member["id"]),
        )
        membership_after = validate_success(
            api.get_team_membership(membership["id"], make_coach_headers("coach-1"))
        )
        assert membership_after["version"] == membership["version"]


class TestAcknowledgeClearsSuppression:
    def test_ack_clears_suppression(self, api, anonymous_headers):
        """PRD: "the member posts the release_id of the release being acknowledged,
        the server records it as algorithm_ack_release_id, and — because
        acknowledging the latest PUBLISHED release discharges the obligation —
        data_sharing_posture returns to NORMAL."

        Design: Corner/endpoints/ack_clears_suppression
        """
        member, term, device, metric_set, release = setup_suppressed_member(
            ingest_overrides={"avg_hr": 100, "hrv_ms": 100, "resting_hr": 50, "sleep_minutes": 480}
        )
        acked = validate_success(
            api.acknowledge_algorithm(
                member["id"],
                {"release_id": release["id"]},
                make_member_headers(member["id"]),
            )
        )
        assert acked["data_sharing_posture"] == "NORMAL"
        assert acked["algorithm_ack_release_id"] == release["id"]

    def test_ack_restores_dashboard_metrics(self, api, anonymous_headers):
        """PRD: "the member posts the release_id of the release being acknowledged,
        the server records it as algorithm_ack_release_id, and — because
        acknowledging the latest PUBLISHED release discharges the obligation —
        data_sharing_posture returns to NORMAL."
        PRD: "Otherwise suppressed is false, and each metric field independently
        shows the member's latest metric value (by day_on descending) when that
        scope's consent entry exists with status GRANTED and either has no
        expires_on or an expires_on on or after today; failing that, the field is
        null."

        Design: Corner/endpoints/ack_clears_suppression
        """
        member, term, device = setup_member_with_active_device()
        headers = make_member_headers(member["id"])
        get_success_data(
            api.ingest_metrics(
                device["id"],
                create_ingest_payload(avg_hr=100, hrv_ms=100, resting_hr=50, sleep_minutes=480),
                headers,
            )
        )
        team, membership = setup_team_membership_with_consent(
            member["id"], "coach-5", "RECOVERY"
        )
        admin = make_platform_admin_headers()
        release = validate_success(
            api.create_algorithm_release(
                create_release_payload(version=2, requires_member_ack=True), admin
            ),
            expected_status=201,
        )
        validate_success(api.publish_algorithm_release(release["id"], admin))
        coach = make_coach_headers("coach-5")
        dash = validate_success(api.get_team_dashboard(team["id"], coach))
        assert dash["rows"][0]["suppressed"] is True
        assert dash["rows"][0]["recovery_score"] is None
        validate_success(
            api.acknowledge_algorithm(member["id"], {"release_id": release["id"]}, headers)
        )
        dash = validate_success(api.get_team_dashboard(team["id"], coach))
        assert dash["rows"][0]["suppressed"] is False
        assert dash["rows"][0]["recovery_score"] == 65
