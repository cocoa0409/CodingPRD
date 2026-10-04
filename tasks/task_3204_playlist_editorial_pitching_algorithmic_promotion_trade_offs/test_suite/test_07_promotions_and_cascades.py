"""Promotions, release scheduling, and artist fraud-strike cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_fraud_case,
    create_artist,
    create_fraud_case,
    create_pitch,
    create_playlist,
    create_profile_module,
    create_promotion,
    create_release,
    create_track,
    get_success_data,
    make_rights_holder_headers,
    set_clock,
    setup_accepted_placement,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["platform_admin_headers"]
FA = TEST_USERS["fraud_analyst_headers"]


class TestEnrollmentWindowOverlap:
    def test_overlapping_enrollment_window_rejected(self, api):
        """PRD §3.5: "The window must not overlap any other non-terminal
        enrollment for the same track — windows that merely touch at a boundary
        are permitted, since the end bound is open — and an overlapping or
        inverted window is rejected with `ERR_ENROLLMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/promotion_enrollment_windows_adjacency_allowed_overlap_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Win", follower_count=5000)
        release = create_release(artist["id"], title="RW", release_date="2026-09-05T00:00:00Z")
        track = create_track(release["id"], artist["id"], title="TW")
        create_promotion(track["id"], artist["id"], discount_factor=0.5,
                         starts_on="2026-09-10T00:00:00Z", ends_on="2026-09-20T00:00:00Z")
        resp = api.create_promotion(
            {
                "track_id": track["id"],
                "discount_factor": 0.5,
                "starts_on": "2026-09-19T23:59:59Z",
                "ends_on": "2026-09-25T00:00:00Z",
            },
            make_rights_holder_headers(artist["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_WINDOW_OVERLAP)

    def test_adjacent_enrollment_windows_coexist(self, api):
        """PRD §3.5: "The window must not overlap any other non-terminal
        enrollment for the same track — windows that merely touch at a boundary
        are permitted, since the end bound is open — and an overlapping or
        inverted window is rejected with `ERR_ENROLLMENT_WINDOW_OVERLAP`."
        PRD §3.5: "A successful enrollment is `ENROLLED`, and the server mints
        a `disclosure_token` returned with the enrollment: the receipt proving
        the royalty-rate disclosure was made."

        Design: Difficulty/resource_temporal_overlap/promotion_enrollment_windows_adjacency_allowed_overlap_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Win", follower_count=5000)
        release = create_release(artist["id"], title="RW", release_date="2026-09-05T00:00:00Z")
        track = create_track(release["id"], artist["id"], title="TW")
        enr_a = create_promotion(track["id"], artist["id"], discount_factor=0.5,
                                 starts_on="2026-09-10T00:00:00Z",
                                 ends_on="2026-09-20T00:00:00Z")
        enr_b = create_promotion(track["id"], artist["id"], discount_factor=0.5,
                                 starts_on="2026-09-20T00:00:00Z",
                                 ends_on="2026-09-25T00:00:00Z")
        assert enr_a["status"] == "ENROLLED"
        assert enr_b["status"] == "ENROLLED"


class TestDisclosureToken:
    def test_promotion_suspend_requires_disclosure_token(self, api):
        """PRD §3.5: "Suspending an enrollment requires the request to carry
        the `disclosure_token` minted at enroll time; a suspend attempted
        without it — or with the wrong token — is rejected with
        `ERR_DISCLOSURE_TOKEN_MISMATCH` (HTTP 403), and only an `ENROLLED`
        enrollment can be suspended."

        Design: Corner/validations/promotion_suspend_requires_disclosure_token
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Disc", follower_count=10)
        release = create_release(artist["id"], title="RDi", release_date="2026-09-05T00:00:00Z")
        track = create_track(release["id"], artist["id"], title="TDi")
        enr = create_promotion(track["id"], artist["id"], discount_factor=0.5,
                               starts_on="2026-09-10T00:00:00Z",
                               ends_on="2026-09-20T00:00:00Z")
        resp = api.suspend_promotion(
            enr["id"], "forged-token", make_rights_holder_headers(artist["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_TOKEN_MISMATCH)
        suspended = get_success_data(
            api.suspend_promotion(
                enr["id"], enr["disclosure_token"],
                make_rights_holder_headers(artist["id"]),
            )
        )
        assert suspended["status"] == "SUSPENDED"


class TestChangeDate:
    def test_change_date_preserves_pitches_with_sufficient_lead(self, api):
        """PRD §3.2: "A successful change replaces `release_date`, increments
        `date_change_count` by 1, and then sweeps the release's pitches: any
        pitch still in `PITCHED`, `UNDER_REVIEW`, or `NEEDS_REVISION` whose
        `submitted_days_before_release` would fall below the minimum lead of 7
        days under the new date is moved to `WITHDRAWN`."

        Design: Corner/state_machines/release_date_change_preserves_sufficient_lead_pitches
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="DC", follower_count=10)
        playlist = create_playlist(name="DC List", slot_count=5)
        rel1 = create_release(artist["id"], title="R1", release_date="2026-09-25T00:00:00Z")
        rel2 = create_release(artist["id"], title="R2", release_date="2026-09-30T00:00:00Z")
        trk1 = create_track(rel1["id"], artist["id"], title="T1")
        trk2 = create_track(rel2["id"], artist["id"], title="T2")
        pit1 = create_pitch(trk1["id"], playlist["id"], artist["id"], pitch_text="p1")
        pit2 = create_pitch(trk2["id"], playlist["id"], artist["id"], pitch_text="p2")

        changed = get_success_data(
            api.change_release_date(
                rel1["id"],
                {
                    "release_date": "2026-09-10T00:00:00Z",
                    "expected_release_version": rel1["version"],
                },
                make_rights_holder_headers(artist["id"]),
            )
        )
        assert changed["release_date"] == "2026-09-10T00:00:00Z"
        assert changed["date_change_count"] == 1
        assert changed["version"] == rel1["version"] + 1

        pit1_after = validate_success(
            api.get_pitch(pit1["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert pit1_after["status"] == "PITCHED"
        pit2_after = validate_success(
            api.get_pitch(pit2["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert pit2_after["status"] == "PITCHED"

    def test_change_date_occ_stale_version_rejected(self, api):
        """PRD §2.7: "Changing a release's scheduled date requires the request
        body to carry `expected_release_version`, set to the `version` of the
        `Release` the client last observed. If the release's current `version`
        no longer matches — because another writer changed the date, or because
        a cascade such as a pitch withdrawal or pre-save conversion advanced it
        — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from rewriting a schedule it has not observed. A
        successful date change increments the release's `version` by 1."

        Design: Corner/cross_cutting_layers/release_change_date_occ_stale_version_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="OCC", follower_count=10)
        release = create_release(artist["id"], title="ROC",
                                 release_date="2026-09-25T00:00:00Z")
        changed = get_success_data(
            api.change_release_date(
                release["id"],
                {
                    "release_date": "2026-10-02T00:00:00Z",
                    "expected_release_version": release["version"],
                },
                make_rights_holder_headers(artist["id"]),
            )
        )
        assert changed["version"] == release["version"] + 1
        resp = api.change_release_date(
            release["id"],
            {
                "release_date": "2026-10-09T00:00:00Z",
                "expected_release_version": release["version"],
            },
            make_rights_holder_headers(artist["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_release(release["id"], PA))
        assert after["release_date"] == "2026-10-02T00:00:00Z"
        assert after["date_change_count"] == 1

    def test_change_date_window_triple_condition(self, api):
        """PRD §3.2: "the logical clock must be at least 7 days before the *old*
        release date, because date changes inside the pitch window would strand
        in-flight editorial work; the new date must lie strictly in the future
        of the logical clock; and the release's `date_change_count` must still
        be below the maximum of 3 changes. Violating any of the temporal or
        count conditions is rejected with `ERR_DATE_CHANGE_WINDOW` (HTTP 409)."

        Design: Corner/errors/error_release_date_change_window_triple_condition
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="DCW", follower_count=10)
        release = create_release(artist["id"], title="RDW",
                                 release_date="2026-09-25T00:00:00Z")
        version = release["version"]
        for new_date in ("2026-10-02T00:00:00Z", "2026-10-09T00:00:00Z",
                         "2026-10-16T00:00:00Z"):
            changed = get_success_data(
                api.change_release_date(
                    release["id"],
                    {"release_date": new_date, "expected_release_version": version},
                    make_rights_holder_headers(artist["id"]),
                )
            )
            version = changed["version"]

        resp_past = api.change_release_date(
            release["id"],
            {"release_date": "2026-08-01T00:00:00Z", "expected_release_version": version},
            make_rights_holder_headers(artist["id"]),
        )
        validate_error(resp_past, ApiErrorId.ERR_DATE_CHANGE_WINDOW)
        resp_fourth = api.change_release_date(
            release["id"],
            {"release_date": "2026-10-23T00:00:00Z", "expected_release_version": version},
            make_rights_holder_headers(artist["id"]),
        )
        validate_error(resp_fourth, ApiErrorId.ERR_DATE_CHANGE_WINDOW)
        after = validate_success(api.get_release(release["id"], PA))
        assert after["release_date"] == "2026-10-16T00:00:00Z"
        assert after["date_change_count"] == 3


class TestArtistTerminationCascade:
    def test_third_confirmed_case_terminates_artist(self, api):
        """PRD §3.1: "Termination is system-driven and irreversible: when
        `fraud_strikes` reaches the termination limit of 3, the artist moves
        from `ACTIVE` to `TERMINATED`, and the cascade is total"
        PRD §3.7: "The artist's `fraud_strikes` increments by 1. If the count
        reaches the strike limit of 2, the artist suspends with the full
        cascade of §3.1; if it reaches the termination limit of 3, the artist
        terminates with its wider cascade, including track removal."

        Design: Difficulty/transitive_cascade/artist_termination_cascades_release_track_module
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="TermX", primary_genre="ROCK",
                               follower_count=5000)
        release = create_release(artist["id"], title="RX",
                                 release_date="2026-09-10T00:00:00Z",
                                 genre_tags=["ROCK"])
        track = create_track(release["id"], artist["id"], title="TX")
        create_profile_module(
            artist["id"], module_type="CANVAS", track_id=track["id"],
            payload_uri="https://cdn.example.com/canvas/tx.mp4",
        )
        for day in (11, 13):
            case = create_fraud_case(
                track["id"],
                window_start=f"2026-09-{day}T00:00:00Z",
                window_end=f"2026-09-{day + 1}T00:00:00Z",
                signal_bot_ratio=1.0,
                signal_velocity_zscore=1.0,
                signal_device_concentration=0.6,
            )
            confirm_fraud_case(case["id"])
        artist_mid = validate_success(api.get_artist(artist["id"], PA))
        assert artist_mid["fraud_strikes"] == 2
        assert artist_mid["status"] == "SUSPENDED"

        case3 = create_fraud_case(
            track["id"],
            window_start="2026-09-15T00:00:00Z",
            window_end="2026-09-16T00:00:00Z",
            signal_bot_ratio=1.0,
            signal_velocity_zscore=1.0,
            signal_device_concentration=0.6,
        )
        confirmed = confirm_fraud_case(case3["id"])
        assert confirmed["verdict"] == "CONFIRMED"
        artist_after = validate_success(api.get_artist(artist["id"], PA))
        assert artist_after["fraud_strikes"] == 3
        assert artist_after["status"] == "TERMINATED"

    def test_termination_removes_track_and_disables_module(self, api):
        """PRD §3.1: "Termination is system-driven and irreversible: when
        `fraud_strikes` reaches the termination limit of 3, the artist moves
        from `ACTIVE` to `TERMINATED`, and the cascade is total — every
        `AVAILABLE` track becomes `REMOVED`, every non-terminal placement on
        the artist's tracks becomes `EVICTED`, every `ENROLLED` or `SUSPENDED`
        enrollment becomes `TERMINATED`, and every `ENABLED` profile module
        becomes `DISABLED`."

        Design: Difficulty/transitive_cascade/artist_termination_cascades_release_track_module
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="TermX", primary_genre="ROCK",
                               follower_count=5000)
        release = create_release(artist["id"], title="RX",
                                 release_date="2026-09-10T00:00:00Z",
                                 genre_tags=["ROCK"])
        track = create_track(release["id"], artist["id"], title="TX")
        module = create_profile_module(
            artist["id"], module_type="CANVAS", track_id=track["id"],
            payload_uri="https://cdn.example.com/canvas/tx.mp4",
        )
        for day in (11, 13, 15):
            case = create_fraud_case(
                track["id"],
                window_start=f"2026-09-{day}T00:00:00Z",
                window_end=f"2026-09-{day + 1}T00:00:00Z",
                signal_bot_ratio=1.0,
                signal_velocity_zscore=1.0,
                signal_device_concentration=0.6,
            )
            confirm_fraud_case(case["id"])

        release_after = validate_success(api.get_release(release["id"], PA))
        assert release_after["status"] == "SCHEDULED"
        track_after = validate_success(api.get_track(track["id"], PA))
        assert track_after["status"] == "REMOVED"
        module_after = validate_success(
            api.get_profile_module(module["id"], PA)
        )
        assert module_after["status"] == "DISABLED"
