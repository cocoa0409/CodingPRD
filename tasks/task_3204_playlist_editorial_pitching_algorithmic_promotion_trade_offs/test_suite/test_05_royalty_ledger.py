"""Royalty ledger: dual-variant share computation, the pinned floor-then-
remainder waterfall, tainted-stream exclusion, pool conservation, close
boundaries, settle terminality, OCC on close, and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_period,
    confirm_fraud_case,
    create_artist,
    create_fraud_case,
    create_promotion,
    create_release,
    create_royalty_period,
    create_stream,
    create_track,
    get_statement_for_artist,
    list_statements,
    set_clock,
    validate_error,
    validate_success,
)

PA = TEST_USERS["platform_admin_headers"]


def _artist_with_track(stage_name):
    artist = create_artist(stage_name=stage_name, follower_count=5000)
    release = create_release(artist["id"], title=f"R{stage_name}",
                             release_date="2026-09-10T00:00:00Z")
    track = create_track(release["id"], artist["id"], title=f"T{stage_name}")
    return artist, release, track


class TestGrossVariantShare:
    def test_gross_close_freezes_variant_and_computes_shares(self, api):
        """PRD §3.6: "Under `GROSS`, the denominator is the sum of `raw_streams`
        across all artists and each artist's `share_bps` is their raw count as
        a proportion of that denominator expressed in basis points of 10000,
        rounded half-up to an integer — the promotion discount has no effect on
        share."
        PRD §3.6: "The close request also names the share `variant`: `GROSS` or
        `EFFECTIVE`, frozen onto the period as `closed_variant`."
        PRD §3.6: "The input set is the period's stream events with
        `is_tainted` equal to `false`."

        Design: Difficulty/dual_variant_calc/royalty_pool_gross_vs_effective_share_divergence
        """
        set_clock("2026-09-01T00:00:00Z")
        art_a, _, trk_a = _artist_with_track("ArtistA")
        art_b, _, trk_b = _artist_with_track("ArtistB")
        art_c, _, trk_c = _artist_with_track("ArtistC")
        create_promotion(trk_a["id"], art_a["id"], discount_factor=0.5,
                         starts_on="2026-09-10T00:00:00Z", ends_on="2026-09-20T00:00:00Z")
        period = create_royalty_period(pool_cents=100000,
                                       period_end="2026-09-30T00:00:00Z")
        create_stream(trk_a["id"], source="ALGORITHMIC", occurred_on="2026-09-15T00:00:00Z")
        create_stream(trk_a["id"], source="ORGANIC", occurred_on="2026-09-16T00:00:00Z")
        create_stream(trk_a["id"], source="EDITORIAL_PLAYLIST", occurred_on="2026-09-17T00:00:00Z")
        create_stream(trk_b["id"], occurred_on="2026-09-15T00:00:00Z")
        create_stream(trk_c["id"], occurred_on="2026-09-15T00:00:00Z")
        create_stream(trk_c["id"], occurred_on="2026-09-16T00:00:00Z")
        case = create_fraud_case(
            trk_c["id"],
            window_start="2026-09-16T00:00:00Z",
            window_end="2026-09-17T00:00:00Z",
            signal_bot_ratio=0.9,
            signal_velocity_zscore=0.9,
            signal_device_concentration=0.8,
        )
        confirm_fraud_case(case["id"])
        set_clock("2026-09-30T00:00:00Z")

        closed = close_period(period["id"], "GROSS", period["version"])
        assert closed["closed_variant"] == "GROSS"

        stmt_a = get_statement_for_artist(period["id"], art_a["id"])
        assert stmt_a["raw_streams"] == 3
        assert stmt_a["effective_streams"] == 1.50
        assert stmt_a["share_bps"] == 6000
        assert stmt_a["gross_payout_cents"] == 60000

        stmt_b = get_statement_for_artist(period["id"], art_b["id"])
        assert stmt_b["raw_streams"] == 1
        assert stmt_b["share_bps"] == 2000
        assert stmt_b["gross_payout_cents"] == 20000

        stmt_c = get_statement_for_artist(period["id"], art_c["id"])
        assert stmt_c["raw_streams"] == 1
        assert stmt_c["share_bps"] == 2000
        assert stmt_c["gross_payout_cents"] == 20000

        rows = list_statements(period_id=period["id"])
        assert len(rows) == 3

    def test_clawback_rate_applied_to_tainted_stream_on_case(self, api):
        """PRD §3.7: "The `clawback_cents` for the case is computed over the
        newly tainted streams: each contributes its effective rate — 1.0, or
        the covering enrollment's `discount_factor` if a promotion window
        covered the stream's instant — multiplied by the per-stream rate of
        0.40 cents, and the products are summed and rounded half-up to 2
        decimal places."

        Design: Difficulty/dual_variant_calc/royalty_pool_gross_vs_effective_share_divergence
        """
        set_clock("2026-09-01T00:00:00Z")
        art_c, _, trk_c = _artist_with_track("ArtistC2")
        period = create_royalty_period(pool_cents=1000)
        create_stream(trk_c["id"], occurred_on="2026-09-16T00:00:00Z")
        case = create_fraud_case(
            trk_c["id"],
            window_start="2026-09-16T00:00:00Z",
            window_end="2026-09-17T00:00:00Z",
            signal_bot_ratio=0.9,
            signal_velocity_zscore=0.9,
            signal_device_concentration=0.8,
        )
        confirmed = confirm_fraud_case(case["id"])
        assert confirmed["verdict"] == "CONFIRMED"
        assert confirmed["clawback_cents"] == 0.40


class TestWaterfallRemainderOrder:
    def test_tied_shares_remainder_goes_to_earlier_artist(self, api):
        """PRD §3.6: "The remainder — `pool_cents` minus the sum of all floored
        payouts — is distributed one cent at a time to artists ordered by
        `share_bps` descending, ties broken by artist `created_at` ascending,
        until the remainder is exhausted."
        PRD §3.6: "The rounding order is pinned: per-artist floor first,
        remainder waterfall second."

        Design: Difficulty/combinatorial_formula/royalty_waterfall_per_artist_floor_then_remainder
        """
        set_clock("2026-09-01T00:00:00Z")
        art_d, _, trk_d = _artist_with_track("D")
        art_e, _, trk_e = _artist_with_track("E")
        create_promotion(trk_d["id"], art_d["id"], discount_factor=0.5,
                         starts_on="2026-09-10T00:00:00Z", ends_on="2026-09-25T00:00:00Z")
        period = create_royalty_period(pool_cents=77777)
        for day in range(11, 16):
            create_stream(trk_d["id"], source="ALGORITHMIC",
                          occurred_on=f"2026-09-{day}T00:00:00Z")
        for day in range(11, 16):
            create_stream(trk_e["id"], occurred_on=f"2026-09-{day}T00:00:00Z")
        set_clock("2026-10-01T00:00:00Z")
        close_period(period["id"], "GROSS", period["version"])

        stmt_d = get_statement_for_artist(period["id"], art_d["id"])
        stmt_e = get_statement_for_artist(period["id"], art_e["id"])
        assert stmt_d["share_bps"] == 5000
        assert stmt_e["share_bps"] == 5000
        assert stmt_d["gross_payout_cents"] == 38889
        assert stmt_e["gross_payout_cents"] == 38888

    def test_waterfall_payouts_sum_to_pool_exactly(self, api):
        """PRD §3.6: "Each artist's `gross_payout_cents` is then the floor of
        `pool_cents` multiplied by their `share_bps` divided by 10000. The
        remainder — `pool_cents` minus the sum of all floored payouts — is
        distributed one cent at a time to artists ordered by `share_bps`
        descending, ties broken by artist `created_at` ascending, until the
        remainder is exhausted."

        Design: Difficulty/combinatorial_formula/royalty_waterfall_per_artist_floor_then_remainder
        """
        set_clock("2026-09-01T00:00:00Z")
        art_d, _, trk_d = _artist_with_track("D")
        art_e, _, trk_e = _artist_with_track("E")
        period = create_royalty_period(pool_cents=77777)
        for day in range(11, 16):
            create_stream(trk_d["id"], source="ALGORITHMIC",
                          occurred_on=f"2026-09-{day}T00:00:00Z")
        for day in range(11, 16):
            create_stream(trk_e["id"], occurred_on=f"2026-09-{day}T00:00:00Z")
        set_clock("2026-10-01T00:00:00Z")
        close_period(period["id"], "GROSS", period["version"])
        rows = list_statements(period_id=period["id"])
        total = sum(r["gross_payout_cents"] for r in rows)
        assert total == 77777


class TestTaintedStreamExclusion:
    def test_close_excludes_tainted_streams_from_input_set(self, api):
        """PRD §3.6: "Statements are then generated for every artist with at
        least one non-tainted stream in the period."
        PRD §3.6: "The input set is the period's stream events with
        `is_tainted` equal to `false`."
        PRD §3.7: "If the artist has a statement in a period that is `CLOSED`
        but not yet `SETTLED`, the clawback is added to that statement's
        `clawback_cents`; otherwise it is recorded on the case and swept into
        the artist's next generated statement."

        Design: Corner/calculations/royalty_close_excludes_tainted_streams_from_input_set
        """
        set_clock("2026-09-01T00:00:00Z")
        art_s, _, trk_s = _artist_with_track("Solo")
        period = create_royalty_period(pool_cents=5000)
        create_stream(trk_s["id"], occurred_on="2026-09-11T00:00:00Z")
        case = create_fraud_case(trk_s["id"],
                                 window_start="2026-09-11T00:00:00Z",
                                 window_end="2026-09-12T00:00:00Z")
        confirmed = confirm_fraud_case(case["id"])
        assert confirmed["clawback_cents"] == 0.40
        set_clock("2026-10-01T00:00:00Z")
        closed = close_period(period["id"], "GROSS", period["version"])
        assert closed["status"] == "CLOSED"
        rows = list_statements(period_id=period["id"])
        assert rows == []


class TestPoolConservationInvariant:
    def test_pool_conserved_across_close_and_clawback(self, api):
        """PRD §3.6: "The remainder — `pool_cents` minus the sum of all floored
        payouts — is distributed one cent at a time to artists ordered by
        `share_bps` descending, ties broken by artist `created_at` ascending,
        until the remainder is exhausted."
        PRD §3.6: "a `clawback_cents` figure that starts at 0 and grows as
        confirmed fraud cases land (§3.7), and a `net_payout_cents` equal to
        the gross payout minus the clawback — which may be negative."
        PRD §3.7: "If the artist has a statement in a period that is `CLOSED`
        but not yet `SETTLED`, the clawback is added to that statement's
        `clawback_cents`; otherwise it is recorded on the case and swept into
        the artist's next generated statement."

        Design: Difficulty/compensating_invariant/royalty_pool_total_conserved_across_close_and_clawback
        """
        set_clock("2026-09-01T00:00:00Z")
        art_a, _, trk_a = _artist_with_track("InvA")
        art_b, _, trk_b = _artist_with_track("InvB")
        period = create_royalty_period(pool_cents=77777)
        for day in range(11, 15):
            create_stream(trk_a["id"], occurred_on=f"2026-09-{day}T00:00:00Z")
        create_stream(trk_b["id"], occurred_on="2026-09-11T00:00:00Z")
        create_stream(trk_b["id"], occurred_on="2026-09-12T00:00:00Z")
        case = create_fraud_case(trk_b["id"],
                                 window_start="2026-09-12T00:00:00Z",
                                 window_end="2026-09-13T00:00:00Z")
        confirm_fraud_case(case["id"])
        set_clock("2026-10-01T00:00:00Z")
        close_period(period["id"], "GROSS", period["version"])

        stmt_a = get_statement_for_artist(period["id"], art_a["id"])
        stmt_b = get_statement_for_artist(period["id"], art_b["id"])
        assert stmt_a["raw_streams"] == 4
        assert stmt_a["share_bps"] == 8000
        assert stmt_a["gross_payout_cents"] == 62222
        assert stmt_b["raw_streams"] == 1
        assert stmt_b["share_bps"] == 2000
        assert stmt_b["gross_payout_cents"] == 15555
        rows = list_statements(period_id=period["id"])
        assert sum(r["gross_payout_cents"] for r in rows) == 77777
        assert stmt_b["clawback_cents"] == 0.40
        assert stmt_b["net_payout_cents"] == 15554.60


    def test_clawback_moves_money_within_statement_not_pool(self, api):
        """PRD §3.6: "a `clawback_cents` figure that starts at 0 and grows as
        confirmed fraud cases land (§3.7), and a `net_payout_cents` equal to
        the gross payout minus the clawback — which may be negative."
        PRD §3.7: "If the artist has a statement in a period that is `CLOSED`
        but not yet `SETTLED`, the clawback is added to that statement's
        `clawback_cents`; otherwise it is recorded on the case and swept into
        the artist's next generated statement."

        Design: Difficulty/compensating_invariant/royalty_pool_total_conserved_across_close_and_clawback
        """
        set_clock("2026-09-01T00:00:00Z")
        art_a, _, trk_a = _artist_with_track("InvA")
        art_b, _, trk_b = _artist_with_track("InvB")
        period = create_royalty_period(pool_cents=77777)
        for day in range(11, 15):
            create_stream(trk_a["id"], occurred_on=f"2026-09-{day}T00:00:00Z")
        create_stream(trk_b["id"], occurred_on="2026-09-11T00:00:00Z")
        create_stream(trk_b["id"], occurred_on="2026-09-12T00:00:00Z")
        case = create_fraud_case(trk_b["id"],
                                 window_start="2026-09-12T00:00:00Z",
                                 window_end="2026-09-13T00:00:00Z")
        confirm_fraud_case(case["id"])
        set_clock("2026-10-01T00:00:00Z")
        close_period(period["id"], "GROSS", period["version"])

        stmt_b = get_statement_for_artist(period["id"], art_b["id"])
        assert stmt_b["gross_payout_cents"] == 15555
        assert stmt_b["clawback_cents"] == 0.40
        assert stmt_b["net_payout_cents"] == pytest.approx(
            stmt_b["gross_payout_cents"] - stmt_b["clawback_cents"], abs=0.01
        )
        rows = list_statements(period_id=period["id"])
        assert sum(r["gross_payout_cents"] for r in rows) == 77777


class TestPeriodCloseBoundary:
    def test_close_before_period_end_rejected_then_inclusive_pass(self, api):
        """PRD §3.6: "Closing a period is the consequential act: it requires
        the logical clock to have reached `period_end`, requires that no other
        `OPEN` period's window overlaps this one — either failure yields
        `ERR_PERIOD_NOT_CLOSABLE`"

        Design: Corner/validations/stream_ingest_before_period_end_close_blocked_until_clock_passes
        """
        set_clock("2026-09-01T00:00:00Z")
        period = create_royalty_period(pool_cents=100)
        resp = api.close_royalty_period(
            period["id"],
            {"variant": "GROSS", "expected_period_version": period["version"]},
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSABLE)
        set_clock("2026-10-01T00:00:00Z")
        closed = close_period(period["id"], "GROSS", period["version"])
        assert closed["status"] == "CLOSED"


class TestSettleTerminality:
    def test_settle_only_from_closed_and_terminal_afterwards(self, api):
        """PRD §3.6: "Settling a `CLOSED` period moves it to `SETTLED`: the
        statements become immutable and any pending clawbacks are locked into
        `net_payout_cents`."

        Design: Corner/endpoints/royalty_settle_locks_statements
        """
        set_clock("2026-09-01T00:00:00Z")
        period = create_royalty_period(pool_cents=100, period_end="2026-09-10T00:00:00Z")
        resp1 = api.settle_royalty_period(period["id"], PA)
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)
        set_clock("2026-09-10T00:00:00Z")
        close_period(period["id"], "GROSS", period["version"])
        settled = validate_success(api.settle_royalty_period(period["id"], PA))
        assert settled["status"] == "SETTLED"
        resp2 = api.settle_royalty_period(period["id"], PA)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


class TestPeriodCloseOcc:
    def test_period_close_occ_stale_version_rejected(self, api):
        """PRD §2.7: "Closing a royalty period requires the request body to
        carry `expected_period_version`, set to the `version` of the
        `RoyaltyPeriod` the client last observed. Closing freezes the share
        variant and materializes statements, so a stale view of the period —
        for instance one whose `pool_cents` was amended by another
        administrator — must not be the basis of the close; a mismatch is
        rejected with `ERR_STALE_VERSION` (HTTP 412). A successful close
        increments the period's `version` by 1."

        Design: Corner/cross_cutting_layers/period_close_occ_stale_version_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        period = create_royalty_period(pool_cents=100, period_end="2026-09-10T00:00:00Z")
        set_clock("2026-09-10T00:00:00Z")
        resp = api.close_royalty_period(
            period["id"],
            {"variant": "GROSS", "expected_period_version": period["version"] - 1},
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        still_open = validate_success(api.get_royalty_period(period["id"], PA))
        assert still_open["status"] == "OPEN"
        closed = close_period(period["id"], "EFFECTIVE", period["version"])
        assert closed["status"] == "CLOSED"
        assert closed["closed_variant"] == "EFFECTIVE"
        assert closed["version"] == period["version"] + 1


class TestImmediateConsistency:
    def test_close_returns_period_with_statements_immediately_visible(self, api):
        """PRD §3.6: "Statements are then generated for every artist with at
        least one non-tainted stream in the period."
        PRD §3.6: "Under `GROSS`, the denominator is the sum of `raw_streams`
        across all artists and each artist's `share_bps` is their raw count as
        a proportion of that denominator expressed in basis points of 10000,
        rounded half-up to an integer — the promotion discount has no effect on
        share."

        Design: Corner/consistency_model/close_returns_period_with_statements_immediately_visible
        """
        set_clock("2026-09-01T00:00:00Z")
        art_i, _, trk_i = _artist_with_track("Imm")
        period = create_royalty_period(pool_cents=1000)
        create_stream(trk_i["id"], occurred_on="2026-09-06T00:00:00Z", ms_played=1000)
        set_clock("2026-10-01T00:00:00Z")
        closed = close_period(period["id"], "GROSS", period["version"])
        assert closed["status"] == "CLOSED"
        assert closed["closed_variant"] == "GROSS"
        stmt = get_statement_for_artist(period["id"], art_i["id"])
        assert stmt["raw_streams"] == 1
        assert stmt["share_bps"] == 10000
        assert stmt["gross_payout_cents"] == 1000
