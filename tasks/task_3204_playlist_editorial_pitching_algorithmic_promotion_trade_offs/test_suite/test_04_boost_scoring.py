"""Boost scoring: tier multiplier, inclusive cap, cold-start halving, and the
computed-read rollup response shape."""
from test_helpers import (
    create_artist,
    create_playlist,
    create_release,
    create_track,
    set_clock,
    setup_active_placement,
    validate_success,
)

class TestBoostScoreTiers:
    def test_boost_score_standard_variant_with_low_tier_multiplier(self, api, platform_admin_headers):
        """PRD §3.8: "A tier multiplier drawn from the artist's `follower_count`
        then applies: 0.8 when the artist has fewer than 10000 followers, 1.0
        from 10000 up to but not including 100000, and 1.2 at 100000 or more."
        PRD §3.8: "When the track held at least one `ACTIVE` or `REINSTATED`
        placement during the rollup window, the variant is `STANDARD` and the
        score stands as computed."

        Design: Difficulty/combinatorial_formula/editorial_boost_tier_multiplier_with_cap_and_floor
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist, pitch, placement = setup_active_placement(
            artist_overrides={"stage_name": "Low", "follower_count": 5000},
            release_date="2026-09-15T00:00:00Z",
        )
        data = validate_success(
            api.signal_rollup(
                track["id"],
                {
                    "window_start": "2026-09-15T00:00:00Z",
                    "window_end": "2026-09-22T00:00:00Z",
                    "save_rate": 0.5,
                    "completion_rate": 0.4,
                    "skip_rate": 0.1,
                },
                platform_admin_headers,
            )
        )
        assert data["boost_score"] == 28
        assert data["variant"] == "STANDARD"

    def test_boost_score_cold_start_halving_and_negative_floor(self, api, platform_admin_headers):
        """PRD §3.8: "When the track had no editorial placement during the
        window, the variant is `COLD_START` and the score is halved — floored
        to an integer after halving — because the algorithmic pipelines respond
        more weakly without an editorial signal."
        PRD §3.8: "the floor of the product is bounded below by 0 (a skip rate
        heavy enough to push the raw score negative yields 0, never a negative
        score)"

        Design: Difficulty/combinatorial_formula/editorial_boost_tier_multiplier_with_cap_and_floor
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="Big", follower_count=200000)
        release = create_release(artist["id"], title="RB", release_date="2026-09-15T00:00:00Z")
        track = create_track(release["id"], artist["id"], title="TB")
        cold = validate_success(
            api.signal_rollup(
                track["id"],
                {
                    "window_start": "2026-09-15T00:00:00Z",
                    "window_end": "2026-09-22T00:00:00Z",
                    "save_rate": 0.5,
                    "completion_rate": 0.4,
                    "skip_rate": 0.1,
                },
                platform_admin_headers,
            )
        )
        assert cold["boost_score"] == 21
        assert cold["variant"] == "COLD_START"
        neg = validate_success(
            api.signal_rollup(
                track["id"],
                {
                    "window_start": "2026-09-15T00:00:00Z",
                    "window_end": "2026-09-22T00:00:00Z",
                    "save_rate": 0.0,
                    "completion_rate": 0.0,
                    "skip_rate": 0.9,
                },
                platform_admin_headers,
            )
        )
        assert neg["boost_score"] == 0


class TestBoostScoreCap:
    def test_boost_score_cap_is_inclusive_at_ninety(self, api, platform_admin_headers):
        """PRD §3.8: "the floor of the product is bounded below by 0 (a skip
        rate heavy enough to push the raw score negative yields 0, never a
        negative score) and capped above at the boost cap of 90 — a raw result
        landing exactly on 90 keeps the score at 90, since the cap is
        inclusive."
        PRD §3.8: "The floor is applied after the tier multiplier, not before."

        Design: Corner/calculations/boost_score_cap_is_inclusive_at_ninety
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track, playlist, pitch, placement = setup_active_placement(
            artist_overrides={"stage_name": "Cap", "follower_count": 200000},
            release_date="2026-09-09T00:00:00Z",
        )
        below = validate_success(
            api.signal_rollup(
                track["id"],
                {
                    "window_start": "2026-09-05T00:00:00Z",
                    "window_end": "2026-09-12T00:00:00Z",
                    "save_rate": 0.9,
                    "completion_rate": 0.9,
                    "skip_rate": 0.0,
                },
                platform_admin_headers,
            )
        )
        assert below["boost_score"] == 86
        assert below["variant"] == "STANDARD"
        capped = validate_success(
            api.signal_rollup(
                track["id"],
                {
                    "window_start": "2026-09-05T00:00:00Z",
                    "window_end": "2026-09-12T00:00:00Z",
                    "save_rate": 1.0,
                    "completion_rate": 1.0,
                    "skip_rate": 0.0,
                },
                platform_admin_headers,
            )
        )
        assert capped["boost_score"] == 90
        assert capped["variant"] == "STANDARD"


class TestSignalRollupShape:
    def test_signal_rollup_is_a_computed_read_action(self, api, platform_admin_headers):
        """PRD §3.8: "The rollup response carries the computed `boost_score` and
        the `variant`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §3.8: "When the track had no editorial placement during the window,
        the variant is `COLD_START` and the score is halved — floored to an
        integer after halving — because the algorithmic pipelines respond more
        weakly without an editorial signal."

        Design: Corner/endpoints/signal_rollup_is_a_computed_read_action
        """
        set_clock("2026-09-01T00:00:00Z")
        artist = create_artist(stage_name="CR", follower_count=5000)
        release = create_release(artist["id"], title="RCr", release_date="2026-09-05T00:00:00Z")
        track = create_track(release["id"], artist["id"], title="TCr")
        resp = api.signal_rollup(
            track["id"],
            {
                "window_start": "2026-09-05T00:00:00Z",
                "window_end": "2026-09-12T00:00:00Z",
                "save_rate": 0.5,
                "completion_rate": 0.4,
                "skip_rate": 0.1,
            },
            platform_admin_headers,
        )
        body = resp.json()
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        data = validate_success(resp, 200)
        assert data["boost_score"] == 14
        assert data["variant"] == "COLD_START"
