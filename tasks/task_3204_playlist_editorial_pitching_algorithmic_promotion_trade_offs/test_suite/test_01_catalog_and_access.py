"""Catalog foundations: artist registration, release/track validation,
pagination envelope, RBAC segregation, and authentication ordering."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_artist,
    assert_release,
    assert_stream_event,
    assert_track,
    build_user_headers,
    create_artist,
    create_pitch,
    create_playlist,
    create_release,
    create_release_payload,
    create_track,
    make_rights_holder_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestArtistRegistration:
    def test_artist_create_returns_system_fields_and_active_status(self, api):
        """PRD §3.1: "A newly registered artist is `ACTIVE` with `fraud_strikes` at 0."
        PRD §2.4: "At server startup the logical clock reads exactly
        `2026-09-01T00:00:00Z`; until an operator first sets it, the clock
        remains pinned at that instant and never falls back to real time."
        PRD §2.5: "Primary resources — Artist, Release, Track, PitchSubmission,
        EditorialPlaylist, PlaylistPlacement, PromotionEnrollment, FraudCase,
        RoyaltyPeriod, RoyaltyStatement, and ProfileModule — share a standard
        set of system-managed fields"

        Design: Corner/entities/artist_create_returns_system_fields_and_active_status
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_artist(
            {
                "stage_name": "Nova",
                "primary_genre": "POP",
                "home_territory": "US",
                "follower_count": 1200,
            },
            TEST_USERS["platform_admin_headers"],
        )
        artist = validate_success(resp, 201)
        assert_artist(artist)
        assert artist["status"] == "ACTIVE"
        assert artist["fraud_strikes"] == 0
        assert artist["version"] == 1
        assert artist["created_at"] == "2026-09-01T00:00:00.000Z"

    def test_release_omitting_territory_allowlist_defaults_to_worldwide(self, api):
        """PRD §3.2: "The release may also carry a `territory_allowlist` of ISO
        alpha-2 codes naming the markets where it is streamable; omitting it
        defaults the allowlist to an empty array, which means worldwide."
        PRD §3.2: "A new release is `SCHEDULED` with `date_change_count` and
        `presave_count` both at 0."

        Design: Corner/entities/release_territory_allowlist_defaults_to_worldwide_empty
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Def", primary_genre="JAZZ", follower_count=10)
        release = create_release(
            artist["id"],
            title="RD",
            release_type="EP",
            release_date="2026-09-20T00:00:00Z",
            genre_tags=["JAZZ"],
        )
        assert_release(release)
        assert release["territory_allowlist"] == []
        assert release["status"] == "SCHEDULED"
        assert release["date_change_count"] == 0
        assert release["presave_count"] == 0


class TestTrackDurationBoundary:
    def test_track_duration_below_minimum_is_invalid_request(self, api):
        """PRD §3.2: "Tracks are added to a release by the owning `RightsHolder`,
        who supplies the `release_id`, a `title`, a `duration_ms` of at least
        30000 milliseconds, and an optional `is_focus_track` flag defaulting to
        `false`."
        PRD §3.2: "A new track is `AVAILABLE`"

        Design: Corner/entities/track_duration_below_minimum_is_invalid_request
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, _focus = _artist_release_no_track(api)
        resp = api.create_track(
            {
                "release_id": release["id"],
                "title": "TooShort",
                "duration_ms": 29999,
                "is_focus_track": True,
            },
            make_rights_holder_headers(artist["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_track_duration_at_minimum_is_accepted(self, api):
        """PRD §3.2: "Tracks are added to a release by the owning `RightsHolder`,
        who supplies the `release_id`, a `title`, a `duration_ms` of at least
        30000 milliseconds, and an optional `is_focus_track` flag defaulting to
        `false`."
        PRD §3.2: "A new track is `AVAILABLE`"

        Design: Corner/entities/track_duration_below_minimum_is_invalid_request
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, _focus = _artist_release_no_track(api)
        resp = api.create_track(
            {
                "release_id": release["id"],
                "title": "JustRight",
                "duration_ms": 30000,
                "is_focus_track": True,
            },
            make_rights_holder_headers(artist["id"]),
        )
        track = validate_success(resp, 201)
        assert_track(track)
        assert track["status"] == "AVAILABLE"


def _artist_release_no_track(api):
    artist = create_artist(stage_name="Dur", follower_count=10)
    release = create_release(artist["id"], title="RDu", release_date="2026-09-20T00:00:00Z")
    return artist, release, None


class TestReleaseLookup:
    def test_release_get_with_unknown_id_returns_not_found(self, api):
        """PRD §2.10: "Requests that address a resource through path identifiers
        validate existence sequentially, left to right: the request is rejected
        immediately with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier
        that does not correspond to an existing resource."
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format"

        Design: Corner/entities/release_get_with_unknown_id_returns_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.get_release(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err.get("message"), "error envelope must carry a human-readable message"


class TestPlacementPagination:
    def test_placements_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the front of the result set and
        defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/placements_list_paginates_with_total_count_and_has_more
        """
        from test_helpers import claim_pitch, decide_pitch

        set_clock("2026-09-01T00:00:00Z")
        playlist = create_playlist(name="Paged", slot_count=2)
        pitches = []
        for stage_name in ("PgA", "PgB"):
            artist = create_artist(stage_name=stage_name, follower_count=10)
            release = create_release(artist["id"], title=f"R{stage_name}",
                                     release_date="2026-09-20T00:00:00Z")
            track = create_track(release["id"], artist["id"], title=f"T{stage_name}")
            pitch = create_pitch(track["id"], playlist["id"], artist["id"], pitch_text=stage_name)
            claim_pitch(pitch["id"])
            decide_pitch(pitch["id"], "ACCEPT")
            pitches.append(pitch)

        page1, meta1 = validate_paginated(
            api.list_placements(
                TEST_USERS["editorial_lead_headers"],
                params={"playlist_id": playlist["id"], "limit": 1, "offset": 0},
            )
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_placements(
                TEST_USERS["editorial_lead_headers"],
                params={"playlist_id": playlist["id"], "limit": 1, "offset": 1},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

        seen_pitch_ids = sorted([page1[0]["pitch_id"], page2[0]["pitch_id"]])
        assert seen_pitch_ids == sorted([p["id"] for p in pitches])
        slots = sorted([page1[0]["slot_index"], page2[0]["slot_index"]])
        assert slots == [0, 1]


class TestStreamEventShape:
    def test_stream_event_is_append_only_without_version_field(self, api):
        """PRD §2.5: "A `StreamEvent` carries only `id` and `created_at` from the
        common set — `updated_at` and `version` are absent because stream events
        are immutable once ingested."
        PRD §3.6: "On success the event is bound to the covering period via
        `royalty_period_id` and recorded with `is_tainted` initially `false`."

        Design: Corner/entities/stream_event_is_append_only_without_version_field
        """
        from test_helpers import create_royalty_period, create_stream

        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="AO", follower_count=10)
        release = create_release(artist["id"], title="RAO", release_date="2026-09-05T00:00:00Z")
        track = create_track(release["id"], artist["id"], title="TAO")
        period = create_royalty_period(pool_cents=1000)
        stream = create_stream(track["id"], occurred_on="2026-09-06T00:00:00Z", ms_played=90000)
        assert_stream_event(stream)
        assert stream["is_tainted"] is False
        assert stream["royalty_period_id"] == period["id"]


class TestValidationAndAuth:
    def test_missing_required_release_field_is_invalid_request(self, api):
        """PRD §3.2: "A `RightsHolder` creates a release under their own artist
        by supplying the `artist_id`, a `title`, a `release_type` of `SINGLE`,
        `EP`, or `ALBUM`, a future `release_date`, between one and three
        `genre_tags` drawn from the same genre enum as `primary_genre`, and up
        to four `mood_tags`"
        PRD §2.6: "Only then are required-field presence, typing, and enum
        membership checked (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/missing_required_release_field_is_invalid_request
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Miss", follower_count=10)
        payload = create_release_payload(artist["id"], title="RM")
        del payload["release_date"]
        resp = api.create_release(payload, make_rights_holder_headers(artist["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(
            api.list_releases(
                TEST_USERS["platform_admin_headers"], params={"artist_id": artist["id"]}
            )
        )
        assert rows == []

    def test_rights_holder_cannot_touch_another_artists_release(self, api):
        """PRD §2.1: "A `RightsHolder` acting on a resource owned by another
        artist is rejected with `ERR_FORBIDDEN` (HTTP 403), as is any role
        attempting an operation outside its authorized set."

        Design: Corner/validations/rights_holder_cannot_touch_another_artists_release
        """
        set_clock("2026-09-01T00:00:00Z")
        artist_a = create_artist(stage_name="OwnA", follower_count=10)
        artist_b = create_artist(stage_name="OwnB", follower_count=10)
        release_b = create_release(
            artist_b["id"], title="RB", release_date="2026-09-25T00:00:00Z"
        )
        resp = api.change_release_date(
            release_b["id"],
            {
                "release_date": "2026-10-01T00:00:00Z",
                "expected_release_version": release_b["version"],
            },
            make_rights_holder_headers(artist_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(
            api.get_release(release_b["id"], TEST_USERS["platform_admin_headers"])
        )
        assert after["release_date"] == "2026-09-25T00:00:00Z"
        assert after["version"] == release_b["version"]

    def test_error_unauthenticated_when_role_header_missing(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."
        PRD §2.6: "Authentication comes first: missing or unrecognized headers
        surface as `ERR_UNAUTHENTICATED` before anything else is examined."

        Design: Corner/errors/error_unauthenticated_when_role_header_missing
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.get_release(
            NON_EXISTENT_UUID, build_user_headers("ghost-1", "GhostRole")
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestEditorialSegregationOfDuties:
    def test_editor_cannot_decide_and_lead_cannot_claim(self, api):
        """PRD §2.1: "a `PlaylistEditor` claims pitches and drives placement
        rotation but only an `EditorialLead` creates playlists and accepts or
        rejects pitches"
        PRD §2.1: "A `RightsHolder` acting on a resource owned by another
        artist is rejected with `ERR_FORBIDDEN` (HTTP 403), as is any role
        attempting an operation outside its authorized set."

        Design: Corner/rbac/editor_cannot_decide_and_lead_cannot_claim
        """
        from test_helpers import create_pitch

        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="RBAC", follower_count=10)
        playlist = create_playlist(name="RBAC List", slot_count=3)
        pitches = []
        for title in ("RR1", "RR2"):
            release = create_release(artist["id"], title=title,
                                     release_date="2026-09-20T00:00:00Z")
            track = create_track(release["id"], artist["id"], title=f"T{title}")
            pitches.append(
                create_pitch(track["id"], playlist["id"], artist["id"], pitch_text=title)
            )

        resp_decide = api.decide_pitch(
            pitches[0]["id"], "ACCEPT", TEST_USERS["playlist_editor_headers"]
        )
        validate_error(resp_decide, ApiErrorId.ERR_FORBIDDEN)
        p1 = validate_success(
            api.get_pitch(pitches[0]["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert p1["status"] == "PITCHED"

        resp_claim = api.claim_pitch(
            pitches[1]["id"], "EDITORIAL_A", TEST_USERS["editorial_lead_headers"]
        )
        validate_error(resp_claim, ApiErrorId.ERR_FORBIDDEN)
        p2 = validate_success(
            api.get_pitch(pitches[1]["id"], TEST_USERS["editorial_lead_headers"])
        )
        assert p2["status"] == "PITCHED"

    def test_fraud_analyst_cannot_ingest_streams(self, api):
        """PRD §2.1: "a `PlatformAdmin` runs the operational backbone — artist
        registration, stream ingest, royalty period lifecycle, pre-save
        registration, signal rollups, and the logical clock."
        PRD §2.1: "A `RightsHolder` acting on a resource owned by another
        artist is rejected with `ERR_FORBIDDEN` (HTTP 403), as is any role
        attempting an operation outside its authorized set."

        Design: Corner/rbac/fraud_analyst_cannot_ingest_streams
        """
        from test_helpers import create_royalty_period

        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Seg", follower_count=10)
        release = create_release(artist["id"], title="RSg", release_date="2026-09-05T00:00:00Z")
        track = create_track(release["id"], artist["id"], title="TSg")
        create_royalty_period(pool_cents=100)
        resp = api.create_stream(
            {
                "track_id": track["id"],
                "territory": "US",
                "source": "ORGANIC",
                "occurred_on": "2026-09-06T00:00:00Z",
                "ms_played": 1000,
            },
            TEST_USERS["fraud_analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        rows, _meta = validate_paginated(
            api.list_streams(
                TEST_USERS["fraud_analyst_headers"], params={"track_id": track["id"]}
            )
        )
        assert rows == []
