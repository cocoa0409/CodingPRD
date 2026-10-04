"""Fraud pipeline: confidence routing at creation, the inclusive confirm
threshold, and the taint-to-statement share cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_period,
    confirm_fraud_case,
    create_artist,
    create_fraud_case,
    create_release,
    create_royalty_period,
    create_stream,
    create_track,
    get_statement_for_artist,
    set_clock,
    validate_error,
    validate_success,
)

PA = TEST_USERS["platform_admin_headers"]
FA = TEST_USERS["fraud_analyst_headers"]


def _artist_with_track(stage_name, follower_count=5000, genre="POP"):
    artist = create_artist(stage_name=stage_name, follower_count=follower_count,
                           primary_genre=genre)
    release = create_release(artist["id"], title=f"R{stage_name}",
                             release_date="2026-09-10T00:00:00Z",
                             genre_tags=[genre])
    track = create_track(release["id"], artist["id"], title=f"T{stage_name}")
    return artist, release, track


class TestConfidenceRouting:
    def test_high_confidence_case_created_auto_flagged(self, api):
        """PRD §3.7: "At creation the system computes a `confidence_score`: 40
        percent of the bot-ratio signal plus 35 percent of the velocity z-score
        signal plus 25 percent of the device-concentration signal, rounded to 4
        decimal places with round-half-up. The score routes the verdict
        immediately: a score of at least 0.7000 opens the case as
        `AUTO_FLAGGED`; anything below opens it as `OPEN`."

        Design: Difficulty/dual_variant_calc/fraud_confidence_manual_vs_auto_flag_path_divergence
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track = _artist_with_track("FraudHi")
        case = create_fraud_case(
            track["id"],
            window_start="2026-09-15T00:00:00Z",
            window_end="2026-09-16T00:00:00Z",
            signal_bot_ratio=0.9,
            signal_velocity_zscore=0.9,
            signal_device_concentration=0.8,
        )
        assert case["confidence_score"] == 0.8750
        assert case["verdict"] == "AUTO_FLAGGED"

    def test_low_confidence_case_created_open(self, api):
        """PRD §3.7: "The score routes the verdict immediately: a score of at
        least 0.7000 opens the case as `AUTO_FLAGGED`; anything below opens it
        as `OPEN`."

        Design: Difficulty/dual_variant_calc/fraud_confidence_manual_vs_auto_flag_path_divergence
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track = _artist_with_track("FraudLo")
        case = create_fraud_case(
            track["id"],
            window_start="2026-09-16T00:00:00Z",
            window_end="2026-09-17T00:00:00Z",
            signal_bot_ratio=0.5,
            signal_velocity_zscore=0.5,
            signal_device_concentration=0.5,
        )
        assert case["confidence_score"] == 0.5000
        assert case["verdict"] == "OPEN"


class TestConfirmThresholdBoundary:
    def test_confirm_below_threshold_rejected_and_state_unchanged(self, api):
        """PRD §3.7: "A `CONFIRM` is gated: the case must be in `OPEN` or
        `AUTO_FLAGGED` (confirming a closed case is `ERR_INVALID_STATE`), and
        the `confidence_score` must be at least 0.8500 — a confirm attempted
        below that threshold is rejected with `ERR_FRAUD_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/fraud_confirm_threshold_inclusive_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track = _artist_with_track("Bound")
        case = create_fraud_case(
            track["id"],
            window_start="2026-09-11T00:00:00Z",
            window_end="2026-09-12T00:00:00Z",
            signal_bot_ratio=1.0,
            signal_velocity_zscore=0.4,
            signal_device_concentration=1.0,
        )
        assert case["confidence_score"] == 0.7900
        assert case["verdict"] == "AUTO_FLAGGED"
        resp = api.adjudicate_fraud_case(case["id"], "CONFIRM", FA)
        validate_error(resp, ApiErrorId.ERR_FRAUD_THRESHOLD_NOT_MET)
        after = validate_success(api.get_fraud_case(case["id"], FA))
        assert after["verdict"] == "AUTO_FLAGGED"

    def test_confirm_at_threshold_succeeds(self, api):
        """PRD §3.7: "the `confidence_score` must be at least 0.8500 — a confirm
        attempted below that threshold is rejected with
        `ERR_FRAUD_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/fraud_confirm_threshold_inclusive_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        artist, release, track = _artist_with_track("Bound2")
        case = create_fraud_case(
            track["id"],
            window_start="2026-09-13T00:00:00Z",
            window_end="2026-09-14T00:00:00Z",
            signal_bot_ratio=1.0,
            signal_velocity_zscore=1.0,
            signal_device_concentration=0.4,
        )
        assert case["confidence_score"] == 0.8500
        confirmed = confirm_fraud_case(case["id"])
        assert confirmed["verdict"] == "CONFIRMED"


class TestFraudTaintCascade:
    def test_confirm_taints_stream_and_artist_strike_increments(self, api):
        """PRD §3.7: "Every stream event for the track with `occurred_on` inside
        the case window — closed at `window_start`, open at `window_end` — that
        is not already tainted has `is_tainted` set to `true`."
        PRD §3.7: "The artist's `fraud_strikes` increments by 1."

        Design: Difficulty/transitive_cascade/fraud_confirm_taints_streams_then_slashes_statement_share
        """
        set_clock("2026-09-01T00:00:00Z")
        art_a, _, trk_a = _artist_with_track("CasA")
        art_b, _, trk_b = _artist_with_track("CasB")
        period = create_royalty_period(pool_cents=77777)
        create_stream(trk_a["id"], occurred_on="2026-09-11T00:00:00Z")
        create_stream(trk_b["id"], occurred_on="2026-09-11T00:00:00Z")
        create_stream(trk_b["id"], occurred_on="2026-09-12T00:00:00Z")
        tainted = create_stream(trk_b["id"], occurred_on="2026-09-13T00:00:00Z")
        case = create_fraud_case(
            trk_b["id"],
            window_start="2026-09-13T00:00:00Z",
            window_end="2026-09-14T00:00:00Z",
            signal_bot_ratio=1.0,
            signal_velocity_zscore=1.0,
            signal_device_concentration=0.6,
        )
        confirmed = confirm_fraud_case(case["id"])
        assert confirmed["verdict"] == "CONFIRMED"
        assert confirmed["clawback_cents"] == 0.40

        stream_after = validate_success(api.get_stream(tainted["id"], PA))
        assert stream_after["is_tainted"] is True
        artist_b = validate_success(api.get_artist(art_b["id"], PA))
        assert artist_b["fraud_strikes"] == 1

    def test_confirm_then_close_shifts_statement_shares_and_lands_clawback(self, api):
        """PRD §3.6: "The input set is the period's stream events with
        `is_tainted` equal to `false`."
        PRD §3.7: "If the artist has a statement in a period that is `CLOSED`
        but not yet `SETTLED`, the clawback is added to that statement's
        `clawback_cents`; otherwise it is recorded on the case and swept into
        the artist's next generated statement."
        PRD §3.6: "a `net_payout_cents` equal to the gross payout minus the
        clawback — which may be negative."

        Design: Difficulty/transitive_cascade/fraud_confirm_taints_streams_then_slashes_statement_share
        """
        set_clock("2026-09-01T00:00:00Z")
        art_a, _, trk_a = _artist_with_track("CasA")
        art_b, _, trk_b = _artist_with_track("CasB")
        period = create_royalty_period(pool_cents=77777)
        create_stream(trk_a["id"], occurred_on="2026-09-11T00:00:00Z")
        create_stream(trk_b["id"], occurred_on="2026-09-11T00:00:00Z")
        create_stream(trk_b["id"], occurred_on="2026-09-12T00:00:00Z")
        create_stream(trk_b["id"], occurred_on="2026-09-13T00:00:00Z")
        case = create_fraud_case(
            trk_b["id"],
            window_start="2026-09-13T00:00:00Z",
            window_end="2026-09-14T00:00:00Z",
            signal_bot_ratio=1.0,
            signal_velocity_zscore=1.0,
            signal_device_concentration=0.6,
        )
        confirm_fraud_case(case["id"])
        set_clock("2026-10-01T00:00:00Z")
        close_period(period["id"], "GROSS", period["version"])

        stmt_a = get_statement_for_artist(period["id"], art_a["id"])
        stmt_b = get_statement_for_artist(period["id"], art_b["id"])
        assert stmt_a["raw_streams"] == 1
        assert stmt_a["share_bps"] == 3333
        assert stmt_a["gross_payout_cents"] == 25923
        assert stmt_b["raw_streams"] == 2
        assert stmt_b["share_bps"] == 6667
        assert stmt_b["gross_payout_cents"] == 51854
        assert stmt_b["clawback_cents"] == 0.40
        assert stmt_b["net_payout_cents"] == 51853.60
