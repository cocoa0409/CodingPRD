"""Placement rotation cycle, slot occupancy, clock-driven transitions, and
presave territory conversion."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_pitch_and_get_placement,
    claim_pitch,
    create_artist,
    create_pitch,
    create_playlist,
    create_presave,
    create_release,
    create_track,
    decide_pitch,
    get_success_data,
    make_rights_holder_headers,
    set_clock,
    setup_accepted_placement,
    setup_active_placement,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlacementRotationCycle:
    def test_manual_rotate_before_cadence_end_rejected(self, api):
        """PRD §3.4: "The manual rotation is forbidden before the cadence window
        elapses: attempting it while the logical clock is still earlier than
        `scheduled_rotation_on` is rejected with `ERR_ROTATION_TOO_EARLY`."
        PRD §3.4: "A successful activation stamps `activated_on` with the
        current logical clock and computes `scheduled_rotation_on` as
        `activated_on` plus the playlist's `rotation_cadence_days`"

        Design: Difficulty/non_linear_state_machine/placement_rotation_cycle_reinstate_and_cadence_guard
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist, pitch, placement = setup_active_placement(
            artist_overrides={"stage_name": "Rot"},
            release_date="2026-09-10T00:00:00Z",
        )
        assert placement["scheduled_rotation_on"] == "2026-09-17T00:00:00Z"
        resp = api.rotate_placement(placement["id"], TEST_USERS["playlist_editor_headers"])
        validate_error(resp, ApiErrorId.ERR_ROTATION_TOO_EARLY)


class TestSlotReoccupancyGrace:
    def test_second_accept_after_rotation_blocked_by_live_release(self, api):
        """PRD §3.4: "Rotation frees the slot for a new occupant."
        PRD §3.4: "passing a placement's `scheduled_rotation_on` rotates
        `ACTIVE` or `REINSTATED` placements out." (via §2.4 clock advance)
        PRD §3.3: "An `ACCEPT` decision requires the pitch's release to still
        be `SCHEDULED` and the release's artist to be `ACTIVE`"

        Design: Difficulty/resource_temporal_overlap/placement_slot_reoccupancy_with_rotated_out_grace
        """
        set_clock("2026-09-01T00:00:00Z")
        playlist = create_playlist(name="One Slot", slot_count=1)
        pitches = {}
        for stage_name in ("Occ1", "Occ2"):
            artist = create_artist(stage_name=stage_name, follower_count=5000)
            release = create_release(artist["id"], title=f"R{stage_name}",
                                     release_date="2026-09-10T00:00:00Z")
            track = create_track(release["id"], artist["id"], title=f"T{stage_name}")
            pitch = create_pitch(track["id"], playlist["id"], artist["id"],
                                 pitch_text=stage_name)
            pitches[stage_name] = pitch
            claim_pitch(pitch["id"])

        decide_pitch(pitches["Occ1"]["id"], "ACCEPT")
        placement1 = accept_placement_lookup(api, pitches["Occ1"]["id"])
        set_clock("2026-09-10T00:00:00Z")
        get_success_data(
            api.activate_placement(placement1["id"], TEST_USERS["playlist_editor_headers"])
        )
        set_clock("2026-09-17T00:00:00Z")
        rotated = validate_success(
            api.get_placement(placement1["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert rotated["status"] == "ROTATED_OUT"
        resp2 = api.decide_pitch(pitches["Occ2"]["id"], "ACCEPT",
                                 TEST_USERS["editorial_lead_headers"])
        assert resp2.status_code == 409
        rows, _meta = validate_paginated(
            api.list_placements(TEST_USERS["editorial_lead_headers"],
                                params={"pitch_id": pitches["Occ2"]["id"]})
        )
        assert rows == []


def accept_placement_lookup(api, pitch_id):
    rows, _meta = validate_paginated(
        api.list_placements(TEST_USERS["editorial_lead_headers"], params={"pitch_id": pitch_id})
    )
    assert len(rows) == 1
    return rows[0]


class TestActivationGatedOnTrackRemoval:
    def test_release_removal_cascades_and_activation_is_invalid_state(self, api):
        """PRD §3.2: "The owning `RightsHolder` may remove a `SCHEDULED` release,
        which removes every `AVAILABLE` track on it, cancels every `SAVED`
        pre-save, and withdraws every pitch still in `PITCHED`, `UNDER_REVIEW`,
        or `NEEDS_REVISION`."
        PRD §3.4: "Eviction is the involuntary exit and is always system-driven:
        when a track is removed, when its artist is suspended or terminated, or
        when its playlist is retired, every placement on the affected scope —
        whether `SCHEDULED`, `ACTIVE`, or `REINSTATED` — moves to `EVICTED`,
        which is terminal."

        Design: Difficulty/cross_entity_state_dependency/placement_activation_gated_on_track_availability_after_removal
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist, pitch, placement = setup_accepted_placement(
            artist_overrides={"stage_name": "Dep"}
        )
        removed = get_success_data(
            api.remove_release(release["id"], make_rights_holder_headers(artist["id"]))
        )
        assert removed["status"] == "REMOVED"
        track_after = validate_success(
            api.get_track(track["id"], TEST_USERS["platform_admin_headers"])
        )
        assert track_after["status"] == "REMOVED"
        placement_after = validate_success(
            api.get_placement(placement["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert placement_after["status"] == "EVICTED"

    def test_activate_on_evicted_placement_returns_invalid_state(self, api):
        """PRD §3.4: "Activation requires the placement to be `SCHEDULED`, the
        playlist to be `ACTIVE`, the track to be `AVAILABLE` with its release
        `LIVE`"
        PRD §2.6: "Once the request is structurally sound, the generic
        invalid-state guard runs (`ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/placement_activation_gated_on_track_availability_after_removal
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist, pitch, placement = setup_accepted_placement(
            artist_overrides={"stage_name": "Dep"}
        )
        get_success_data(
            api.remove_release(release["id"], make_rights_holder_headers(artist["id"]))
        )
        resp = api.activate_placement(
            placement["id"], TEST_USERS["playlist_editor_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPlaylistRetireCascade:
    def test_playlist_retire_evicts_all_non_terminal_placements(self, api):
        """PRD §3.4: "Retiring a playlist moves it to `RETIRED` and evicts every
        placement on it still in `SCHEDULED`, `ACTIVE`, `REINSTATED`, or
        `ROTATED_OUT` status; `RETIRED` is terminal."

        Design: Corner/state_machines/playlist_retire_evicts_all_non_terminal_placements
        """
        set_clock("2026-09-01T00:00:00Z")
        playlist = create_playlist(name="Retire Me", slot_count=2, rotation_cadence_days=3)
        placements = {}
        for stage_name in ("Ev1", "Ev2"):
            artist = create_artist(stage_name=stage_name, follower_count=10)
            release = create_release(artist["id"], title=f"R{stage_name}",
                                     release_date="2026-09-09T00:00:00Z")
            track = create_track(release["id"], artist["id"], title=f"T{stage_name}")
            pitch = create_pitch(track["id"], playlist["id"], artist["id"],
                                 pitch_text=stage_name)
            claim_pitch(pitch["id"])
            decide_pitch(pitch["id"], "ACCEPT")
            placements[stage_name] = accept_placement_lookup(api, pitch["id"])

        set_clock("2026-09-09T00:00:00Z")
        get_success_data(
            api.activate_placement(
                placements["Ev1"]["id"], TEST_USERS["playlist_editor_headers"]
            )
        )
        retired = get_success_data(
            api.retire_playlist(playlist["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert retired["status"] == "RETIRED"
        for stage_name in ("Ev1", "Ev2"):
            after = validate_success(
                api.get_placement(
                    placements[stage_name]["id"], TEST_USERS["editorial_lead_headers"]
                )
            )
            assert after["status"] == "EVICTED"
        rows, _meta = validate_paginated(
            api.list_placements(
                TEST_USERS["editorial_lead_headers"],
                params={"playlist_id": playlist["id"], "status": "ACTIVE"},
            )
        )
        assert rows == []


class TestClockDrivenTransitions:
    def test_clock_advance_fires_release_and_rotation_transitions(self, api):
        """PRD §2.4: "Advancing the clock fires the time-driven transitions
        deterministically, in the order the affected resources were created:
        passing a release's `release_date` flips a `SCHEDULED` release to
        `LIVE` (provided its artist is `ACTIVE`) and runs pre-save conversion,
        and passing a placement's `scheduled_rotation_on` rotates `ACTIVE` or
        `REINSTATED` placements out."
        PRD §2.4: "A `PlatformAdmin` advances the logical clock through an
        admin-only capability that accepts a `current_utc` instant and returns
        the new clock reading."

        Design: Corner/cross_cutting_layers/clock_advance_fires_release_and_rotation_transitions_deterministically
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist, pitch, placement = setup_accepted_placement(
            artist_overrides={"stage_name": "Clk"},
            release_date="2026-09-09T00:00:00Z",
            playlist_overrides={"rotation_cadence_days": 2},
        )
        set_clock("2026-09-09T00:00:00Z")
        live_release = validate_success(
            api.get_release(release["id"], TEST_USERS["platform_admin_headers"])
        )
        assert live_release["status"] == "LIVE"
        get_success_data(
            api.activate_placement(placement["id"], TEST_USERS["playlist_editor_headers"])
        )
        resp = set_clock("2026-09-11T00:00:00Z")
        assert resp["current_utc"] == "2026-09-11T00:00:00Z"
        rotated = validate_success(
            api.get_placement(placement["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert rotated["status"] == "ROTATED_OUT"


class TestPreSaveTerritoryConversion:
    def test_presave_outside_allowlist_rejected_then_go_live_converts(self, api):
        """PRD §3.2: "Registering a pre-save requires the release to be
        `SCHEDULED` (otherwise `ERR_INVALID_STATE`), requires the `fan_token`
        not to duplicate an existing pre-save on the same release (a duplicate
        is `ERR_INVALID_REQUEST`), and — when the release's
        `territory_allowlist` is non-empty — requires the fan's territory to be
        inside the allowlist, failing which the request is rejected with
        `ERR_TERRITORY_RESTRICTED`."
        PRD §3.2: "Go-live converts the pre-save book: the release's `SAVED`
        pre-saves are processed in the order they were created, ties broken by
        `fan_token` in ascending order, and each row whose `territory` lies
        inside the `territory_allowlist` — or any row at all when the allowlist
        is empty — moves to `CONVERTED`, while every other `SAVED` row moves to
        `CANCELLED`. After conversion, `presave_count` is recomputed as the
        count of rows ending in `SAVED` or `CONVERTED`."

        Design: Corner/state_machines/presave_conversion_at_go_live_respects_territory_allowlist
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="PS", follower_count=10)
        release = create_release(
            artist["id"], title="RPS", release_date="2026-09-05T00:00:00Z",
            territory_allowlist=["US"],
        )
        presave = create_presave(release["id"], "fan-1", territory="US")
        resp = api.create_presave(
            {"release_id": release["id"], "fan_token": "fan-2", "territory": "CA"},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_RESTRICTED)
        set_clock("2026-09-05T00:00:00Z")
        live_release = validate_success(
            api.get_release(release["id"], TEST_USERS["platform_admin_headers"])
        )
        assert live_release["status"] == "LIVE"
        assert live_release["presave_count"] == 1
        converted = validate_success(
            api.get_presave(presave["id"], TEST_USERS["platform_admin_headers"])
        )
        assert converted["status"] == "CONVERTED"
