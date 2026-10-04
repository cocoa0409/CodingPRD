"""Pitching workflow: validation ordering, revision cycle, slot boundaries,
cross-entity gating, and accounting invariants."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    claim_pitch,
    create_artist,
    create_fraud_case,
    create_pitch,
    create_playlist,
    create_release,
    create_track,
    decide_pitch,
    make_rights_holder_headers,
    request_revision,
    revise_pitch,
    set_clock,
    setup_accepted_placement,
    setup_artist_release_track_playlist,
    setup_pitch_under_review,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPitchValidationErrors:
    def test_pitch_on_non_focus_track_is_not_pitchable(self, api):
        """PRD §3.3: "Second, pitchability: the track must be the release's
        focus track, must be `AVAILABLE`, and must have no other non-terminal
        pitch; a violation yields `ERR_PITCH_NOT_PITCHABLE`."

        Design: Corner/validations/pitch_on_non_focus_track_is_not_pitchable
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="NF", follower_count=10)
        release = create_release(
            artist["id"], title="RNF", release_type="EP", release_date="2026-09-20T00:00:00Z"
        )
        create_track(release["id"], artist["id"], title="Focus", is_focus_track=True)
        bside = create_track(release["id"], artist["id"], title="B-Side", is_focus_track=False)
        playlist = create_playlist(name="NF List")
        resp = api.create_pitch(
            {
                "track_id": bside["id"],
                "pitch_text": "pitch the b-side",
                "target_playlist_id": playlist["id"],
            },
            make_rights_holder_headers(artist["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PITCH_NOT_PITCHABLE)
        rows, _meta = validate_paginated(
            api.list_pitches(
                TEST_USERS["editorial_lead_headers"], params={"track_id": bside["id"]}
            )
        )
        assert rows == []

    def test_playlist_genre_fit_mismatch_blocks_pitch(self, api):
        """PRD §3.3: "Third, fit: the target playlist must be `ACTIVE`, the
        release's `genre_tags` must include the playlist's `genre_focus`, and
        the playlist's `mood_focus` must be `ANY` or appear among the release's
        `mood_tags`; failure is `ERR_PLAYLIST_FIT_MISMATCH`."

        Design: Corner/validations/playlist_genre_fit_mismatch_blocks_pitch
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Fit", follower_count=10)
        release = create_release(
            artist["id"], title="Rock Out", release_date="2026-09-20T00:00:00Z",
            genre_tags=["ROCK"],
        )
        track = create_track(release["id"], artist["id"], title="TFt")
        playlist = create_playlist(name="Pop Only", genre_focus="POP")
        resp = api.create_pitch(
            {
                "track_id": track["id"],
                "pitch_text": "wrong shelf",
                "target_playlist_id": playlist["id"],
            },
            make_rights_holder_headers(artist["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAYLIST_FIT_MISMATCH)


class TestPitchRevisionCycle:
    def test_pitch_revision_rounds_increment_through_two_cycles(self, api):
        """PRD §3.3: "The rights holder then re-pitches with replacement
        `pitch_text`, which returns the pitch to `PITCHED` and increments
        `revision_round` by 1."

        Design: Difficulty/non_linear_state_machine/pitch_revision_cycle_loops_back_to_pitched
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist = setup_artist_release_track_playlist(
            artist_overrides={"stage_name": "Cyc"}, release_date="2026-09-20T00:00:00Z"
        )
        pitch = create_pitch(track["id"], playlist["id"], artist["id"], pitch_text="v1")

        claim_pitch(pitch["id"])
        request_revision(pitch["id"])
        rev1 = revise_pitch(pitch["id"], "v2", artist["id"])
        assert rev1["status"] == "PITCHED"
        assert rev1["revision_round"] == 1

        claim_pitch(pitch["id"])
        request_revision(pitch["id"])
        rev2 = revise_pitch(pitch["id"], "v3", artist["id"])
        assert rev2["status"] == "PITCHED"
        assert rev2["revision_round"] == 2

    def test_pitch_third_revision_rejected_invalid_state(self, api):
        """PRD §3.3: "This loop is bounded in two ways: a revise is rejected
        with `ERR_INVALID_STATE` once `revision_round` has reached the maximum
        of 2 rounds, and the same temporal lead rule as submission applies —
        the logical clock must be at least 7 days before the `release_date`,
        and the release must still be `SCHEDULED`; a revise inside the window
        is rejected with `ERR_PITCH_WINDOW_CLOSED`."

        Design: Difficulty/non_linear_state_machine/pitch_revision_cycle_loops_back_to_pitched
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist = setup_artist_release_track_playlist(
            artist_overrides={"stage_name": "Cyc"}, release_date="2026-09-20T00:00:00Z"
        )
        pitch = create_pitch(track["id"], playlist["id"], artist["id"], pitch_text="v1")

        for text in ("v2", "v3"):
            claim_pitch(pitch["id"])
            request_revision(pitch["id"])
            revise_pitch(pitch["id"], text, artist["id"])

        claim_pitch(pitch["id"])
        request_revision(pitch["id"])
        resp = api.revise_pitch(
            pitch["id"], "v4", make_rights_holder_headers(artist["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(
            api.get_pitch(pitch["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert after["status"] == "NEEDS_REVISION"


class TestSlotExhaustionBoundary:
    def test_second_accept_on_full_playlist_fails_with_no_free_slot(self, api):
        """PRD §3.3: "If no such slot exists, the decision fails with
        `ERR_NO_FREE_SLOT` (HTTP 409) and the pitch remains `UNDER_REVIEW`."

        Design: Difficulty/boundary_precision_check/placement_slot_exhaustion_at_exact_capacity
        """
        set_clock("2026-09-01T00:00:00Z")
        playlist = create_playlist(name="Tight List", slot_count=1)
        pitches = []
        for stage_name in ("Slot1", "Slot2"):
            artist = create_artist(stage_name=stage_name, follower_count=5000)
            release = create_release(artist["id"], title=f"R{stage_name}",
                                     release_date="2026-09-20T00:00:00Z")
            track = create_track(release["id"], artist["id"], title=f"T{stage_name}")
            pitch = create_pitch(track["id"], playlist["id"], artist["id"],
                                 pitch_text=stage_name)
            claim_pitch(pitch["id"])
            pitches.append(pitch)

        decide_pitch(pitches[0]["id"], "ACCEPT")
        resp = api.decide_pitch(pitches[1]["id"], "ACCEPT", TEST_USERS["editorial_lead_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_FREE_SLOT)
        p2 = validate_success(
            api.get_pitch(pitches[1]["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert p2["status"] == "UNDER_REVIEW"

    def test_first_accept_on_full_playlist_creates_placement_in_slot_zero(self, api):
        """PRD §3.3: "On success the pitch becomes `ACCEPTED` and a new
        placement is created in `SCHEDULED` for that slot, recording the
        `playlist_id`, the `track_id`, the `pitch_id` that justified it, and
        the chosen `slot_index`."
        PRD §3.3: "An `ACCEPT` decision requires the pitch's release to still
        be `SCHEDULED` and the release's artist to be `ACTIVE`, and it requires
        a free slot on the target playlist: the system scans the playlist's
        slot indices from 0 up to one less than `slot_count` and selects the
        lowest index not occupied by any placement in `SCHEDULED`, `ACTIVE`, or
        `REINSTATED` status."

        Design: Difficulty/boundary_precision_check/placement_slot_exhaustion_at_exact_capacity
        """
        set_clock("2026-09-01T00:00:00Z")
        playlist = create_playlist(name="Tight List", slot_count=1)
        artist = create_artist(stage_name="Slot1", follower_count=5000)
        release = create_release(artist["id"], title="RS1", release_date="2026-09-20T00:00:00Z")
        track = create_track(release["id"], artist["id"], title="TS1")
        pitch = create_pitch(track["id"], playlist["id"], artist["id"], pitch_text="first")
        claim_pitch(pitch["id"])
        decided = decide_pitch(pitch["id"], "ACCEPT")
        assert decided["status"] == "ACCEPTED"
        rows, _meta = validate_paginated(
            api.list_placements(
                TEST_USERS["editorial_lead_headers"], params={"pitch_id": pitch["id"]}
            )
        )
        assert len(rows) == 1
        assert rows[0]["slot_index"] == 0
        assert rows[0]["status"] == "SCHEDULED"


class TestPitchSubmitGatedOnReleaseState:
    def test_pitch_submit_before_release_live_succeeds_with_lead_computed(self, api):
        """PRD §3.3: "A new pitch is `PITCHED`, and the system computes
        `submitted_days_before_release` as the whole number of days between the
        submission instant and the release's `release_date` at submission time"

        Design: Difficulty/cross_entity_state_dependency/pitch_submit_gated_on_release_schedule_state
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist = setup_artist_release_track_playlist(
            artist_overrides={"stage_name": "Gate"},
            release_date="2026-09-10T00:00:00Z",
            playlist_overrides={"slot_count": 5},
        )
        pitch = create_pitch(track["id"], playlist["id"], artist["id"], pitch_text="timely")
        assert pitch["status"] == "PITCHED"
        assert pitch["submitted_days_before_release"] == 9

    def test_pitch_submit_after_release_goes_live_is_window_closed(self, api):
        """PRD §3.3: "First, the temporal guard: the logical clock must be at
        least 7 days before the release's `release_date`; submitting inside
        that lead window — or after the release date — is rejected with
        `ERR_PITCH_WINDOW_CLOSED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/pitch_submit_gated_on_release_schedule_state
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Gate2", follower_count=5000)
        release = create_release(artist["id"], title="RG2", release_date="2026-09-08T00:00:00Z")
        track = create_track(release["id"], artist["id"], title="TG2")
        playlist = create_playlist(name="Fresh Pop", slot_count=5)
        set_clock("2026-09-08T00:00:00Z")
        live_release = validate_success(
            api.get_release(release["id"], TEST_USERS["platform_admin_headers"])
        )
        assert live_release["status"] == "LIVE"
        resp = api.create_pitch(
            {
                "track_id": track["id"],
                "pitch_text": "too late",
                "target_playlist_id": playlist["id"],
            },
            make_rights_holder_headers(artist["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PITCH_WINDOW_CLOSED)


    def test_rejected_pitch_stays_rejected_inside_pitch_window(self, api):
        """PRD §3.3: "A `REJECT` decision simply moves the pitch to `REJECTED`;
        both `ACCEPTED` and `REJECTED` are terminal."
        PRD §3.3: "The owning `RightsHolder` may withdraw a pitch in `PITCHED`,
        `UNDER_REVIEW`, or `NEEDS_REVISION`, moving it to `WITHDRAWN`"

        Design: Difficulty/priority_pair_validation_conflict/pitch_state_beats_pitch_window_temporal
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist, pitch = setup_pitch_under_review(
            artist_overrides={"stage_name": "PrioA2"}
        )
        decide_pitch(pitch["id"], "REJECT")
        set_clock("2026-09-15T00:00:01Z")
        resp = api.withdraw_pitch(pitch["id"], make_rights_holder_headers(artist["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(
            api.get_pitch(pitch["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert after["status"] == "REJECTED"


class TestPitchAccountingInvariant:
    def test_terminal_pitch_accounting_has_zero_drift(self, api):
        """PRD §3.3: "A `REJECT` decision simply moves the pitch to `REJECTED`;
        both `ACCEPTED` and `REJECTED` are terminal."
        PRD §3.3: "The owning `RightsHolder` may withdraw a pitch in `PITCHED`,
        `UNDER_REVIEW`, or `NEEDS_REVISION`, moving it to `WITHDRAWN`"

        Design: Difficulty/compensating_invariant/pitch_cycle_accounting_net_zero_drift
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Acct", follower_count=5000)
        playlist = create_playlist(name="Ledger List", slot_count=3)
        pitches = []
        for title in ("R1", "R2", "R3"):
            release = create_release(artist["id"], title=title,
                                     release_date="2026-09-20T00:00:00Z")
            track = create_track(release["id"], artist["id"], title=f"T{title}")
            pitches.append(
                create_pitch(track["id"], playlist["id"], artist["id"], pitch_text=title)
            )

        claim_pitch(pitches[0]["id"])
        decide_pitch(pitches[0]["id"], "ACCEPT")
        claim_pitch(pitches[1]["id"])
        decide_pitch(pitches[1]["id"], "REJECT")
        resp = api.withdraw_pitch(pitches[2]["id"], make_rights_holder_headers(artist["id"]))
        validate_success(resp)

        rows, meta = validate_paginated(
            api.list_pitches(
                TEST_USERS["editorial_lead_headers"],
                params={"target_playlist_id": playlist["id"]},
            )
        )
        assert meta["total_count"] == 3
        statuses = {r["id"]: r["status"] for r in rows}
        assert statuses[pitches[0]["id"]] == "ACCEPTED"
        assert statuses[pitches[1]["id"]] == "REJECTED"
        assert statuses[pitches[2]["id"]] == "WITHDRAWN"

        for live_status in ("PITCHED", "UNDER_REVIEW"):
            live_rows, live_meta = validate_paginated(
                api.list_pitches(
                    TEST_USERS["editorial_lead_headers"],
                    params={"target_playlist_id": playlist["id"], "status": live_status},
                )
            )
            assert live_rows == []

        placements, _pm = validate_paginated(
            api.list_placements(
                TEST_USERS["editorial_lead_headers"],
                params={"playlist_id": playlist["id"]},
            )
        )
        assert len(placements) == 1
        assert placements[0]["slot_index"] == 0

    def test_pitch_cycle_leaves_no_live_rows(self, api):
        """PRD §3.3: "A `REJECT` decision simply moves the pitch to `REJECTED`;
        both `ACCEPTED` and `REJECTED` are terminal."
        PRD §3.3: "`WITHDRAWN` is terminal."

        Design: Difficulty/compensating_invariant/pitch_cycle_accounting_net_zero_drift
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Acct2", follower_count=5000)
        playlist = create_playlist(name="Ledger List 2", slot_count=3)
        pitches = []
        for title in ("R1", "R2", "R3"):
            release = create_release(artist["id"], title=title,
                                     release_date="2026-09-20T00:00:00Z")
            track = create_track(release["id"], artist["id"], title=f"T{title}")
            pitches.append(
                create_pitch(track["id"], playlist["id"], artist["id"], pitch_text=title)
            )

        claim_pitch(pitches[0]["id"])
        decide_pitch(pitches[0]["id"], "ACCEPT")
        claim_pitch(pitches[1]["id"])
        decide_pitch(pitches[1]["id"], "REJECT")
        resp = api.withdraw_pitch(pitches[2]["id"], make_rights_holder_headers(artist["id"]))
        validate_success(resp)

        for live_status in ("PITCHED", "UNDER_REVIEW", "NEEDS_REVISION"):
            rows, meta = validate_paginated(
                api.list_pitches(
                    TEST_USERS["editorial_lead_headers"],
                    params={"target_playlist_id": playlist["id"], "status": live_status},
                )
            )
            assert meta["total_count"] == 0

    def test_pitch_withdraw_from_accepted_is_invalid_state(self, api):
        """PRD §3.3: "A `REJECT` decision simply moves the pitch to `REJECTED`;
        both `ACCEPTED` and `REJECTED` are terminal."

        Design: Corner/state_machines/pitch_withdraw_from_accepted_is_invalid_state
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist, pitch, placement = setup_accepted_placement()
        resp = api.withdraw_pitch(pitch["id"], make_rights_holder_headers(artist["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(
            api.get_pitch(pitch["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert after["status"] == "ACCEPTED"
        rows, meta = validate_paginated(
            api.list_placements(
                TEST_USERS["editorial_lead_headers"], params={"pitch_id": pitch["id"]}
            )
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "SCHEDULED"


class TestPriorityPair:
    def test_pitch_state_beats_pitch_window_temporal(self, api):
        """PRD §2.6: "Once the request is structurally sound, the generic
        invalid-state guard runs (`ERR_INVALID_STATE`), and only after it
        passes do the business rules — pitch windows, slot occupancy, fraud
        holds, fiscal guards, optimistic-concurrency version checks — evaluate
        in the order given in §3's narratives."

        Design: Difficulty/priority_pair_validation_conflict/pitch_state_beats_pitch_window_temporal
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist, pitch = setup_pitch_under_review(
            artist_overrides={"stage_name": "PrioA"}
        )
        decide_pitch(pitch["id"], "REJECT")
        set_clock("2026-09-15T00:00:01Z")
        resp = api.withdraw_pitch(pitch["id"], make_rights_holder_headers(artist["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_open_fraud_case_blocks_pitch_with_fraud_hold(self, api):
        """PRD §3.3: "Fourth, the fraud hold: the track must have no fraud case
        in `OPEN` or `AUTO_FLAGGED` verdict; a track under investigation cannot
        be pitched and the attempt is rejected with `ERR_FRAUD_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/pitch_safety_fraud_hold_beats_fiscal_no_open_period
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist = setup_artist_release_track_playlist(
            artist_overrides={"stage_name": "PrioB"}
        )
        case = create_fraud_case(
            track["id"],
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-02T00:00:00Z",
            signal_bot_ratio=0.5,
            signal_velocity_zscore=0.5,
            signal_device_concentration=0.5,
        )
        assert case["verdict"] == "OPEN"
        resp = api.create_pitch(
            {
                "track_id": track["id"],
                "pitch_text": "blocked",
                "target_playlist_id": playlist["id"],
            },
            make_rights_holder_headers(artist["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FRAUD_HOLD)

    def test_stream_ingest_without_open_period_is_rejected(self, api):
        """PRD §3.6: "Ingest requires an `OPEN` royalty period whose window
        covers `occurred_on`; a stream falling outside every open window is
        rejected with `ERR_NO_OPEN_PERIOD`."

        Design: Difficulty/priority_pair_validation_conflict/pitch_safety_fraud_hold_beats_fiscal_no_open_period
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist = setup_artist_release_track_playlist(
            artist_overrides={"stage_name": "PrioB2"}
        )
        resp = api.create_stream(
            {
                "track_id": track["id"],
                "territory": "US",
                "source": "ORGANIC",
                "occurred_on": "2026-09-02T00:00:00Z",
                "ms_played": 180000,
            },
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_PERIOD)
