"""Difficulty queue A: combinatorial_formula — nested rounding order and the
50/45/5 distribution waterfall with per-recording weights."""
from test_helpers import (
    PAST_SCHEDULED_FOR,
    create_active_licensee,
    create_effective_schedule,
    create_pool,
    create_recording,
    create_report_with_lines,
    create_verified_artist,
    create_verified_rights_owner,
    make_admin_headers,
    make_licensee_headers,
    make_royalty_ops_headers,
    set_clock,
    setup_standard_paid_scenario,
    submit_and_accept_report,
    validate_paginated,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()


class TestPerLineRoundingOrder:
    def test_per_line_then_sum_rounding_two_lines(self, api):
        """PRD §2.5: "the per-performance calculation rounds each play line to
        whole cents before any summation (the rounding order is pinned: per line
        first, then sum)."
        PRD §3.5: "For every play line of the report — regardless of
        identification status — the line's `performance_count` is multiplied by
        the applicable per-performance rate in microcents and divided by one
        million (the number of microcents in one cent). Each line's raw result
        is rounded half-up to whole cents first; only then are the per-line
        amounts summed."

        Design: Difficulty/combinatorial_formula/per_line_then_sum_rounding_order
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="RoundCo")
        report, _ = create_report_with_lines(
            lic["id"],
            [
                {"isrc": "NO-MATCH-1", "track_title": "P", "artist_name": "Q",
                 "performance_count": 250},
                {"isrc": "NO-MATCH-2", "track_title": "R", "artist_name": "S",
                 "performance_count": 250},
            ],
            "2026-04-01T00:00:00Z",
            "2026-04-30T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        liability = validate_success(
            api.compute_liability(
                report["id"],
                {"expected_usage_report_version": accepted["version"]},
                OPS,
            ),
            expected_status=201,
        )
        # 250 x 2600 / 1e6 = 0.65 -> 1c per line; 2 lines -> 2c gross.
        assert liability["gross_performance_royalty_cents"] == 2
        assert liability["gross_performance_royalty_cents"] != 1, (
            "sum-then-round order would give round(500 x 2600 / 1e6) == 1; "
            "the pinned order is per line first"
        )

    def test_per_line_then_sum_rounding_exact_half_up(self, api):
        """PRD §2.5: "Wherever a division produces a fractional cent, the system
        rounds half-up to the nearest integer cent unless a rule explicitly
        states otherwise; the per-performance calculation rounds each play line
        to whole cents before any summation (the rounding order is pinned: per
        line first, then sum)."

        Design: Difficulty/combinatorial_formula/per_line_then_sum_rounding_order
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="RoundCo2")
        # 500 x 2600 / 1e6 = 1.30 -> 1c; 501 x 2600 / 1e6 = 1.3026 -> 1c;
        # combined gross 2. The half-up boundary case: 250 x 2600 = 0.65 -> 1.
        report, _ = create_report_with_lines(
            lic["id"],
            [
                {"isrc": "NO-MATCH-H1", "track_title": "h1", "artist_name": "h1",
                 "performance_count": 500},
                {"isrc": "NO-MATCH-H2", "track_title": "h2", "artist_name": "h2",
                 "performance_count": 501},
            ],
            "2026-04-01T00:00:00Z",
            "2026-04-30T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        liability = validate_success(
            api.compute_liability(
                report["id"],
                {"expected_usage_report_version": accepted["version"]},
                OPS,
            ),
            expected_status=201,
        )
        assert liability["gross_performance_royalty_cents"] == 2


def _setup_distribution_waterfall(api):
    """Two matched recordings (60000/40000 perfs) + one unmatched 5000 line.

    Returns dict with licensee, report, liability, batch, pool, ro, fa_a, fa_b,
    rec_a, rec_b.
    """
    create_effective_schedule()
    lic = create_active_licensee(legal_name="SplitCo")
    ro = create_verified_rights_owner(legal_name="Label One",
                                      contact_email="ro@example.com")
    fa_a = create_verified_artist(stage_name="Artist A",
                                  contact_email="aa@example.com")
    fa_b = create_verified_artist(stage_name="Artist B",
                                  contact_email="ab@example.com")
    rec_a = create_recording(ro["id"], fa_a["id"], isrc="ISRC-AA",
                             track_title="Song A")
    rec_b = create_recording(ro["id"], fa_b["id"], isrc="ISRC-BB",
                             track_title="Song B")
    report, _ = create_report_with_lines(
        lic["id"],
        [
            {"isrc": "ISRC-AA", "track_title": "Song A", "artist_name": "Artist A",
             "performance_count": 60000},
            {"isrc": "ISRC-BB", "track_title": "Song B", "artist_name": "Artist B",
             "performance_count": 40000},
            {"isrc": "ISRC-ZZ", "track_title": "Song Z", "artist_name": "Artist Z",
             "performance_count": 5000},
        ],
        "2026-01-01T00:00:00Z",
        "2026-01-31T00:00:00Z",
    )
    accepted = submit_and_accept_report(report["id"], lic["id"])
    liability = validate_success(
        api.compute_liability(
            report["id"],
            {"expected_usage_report_version": accepted["version"]},
            OPS,
        ),
        expected_status=201,
    )
    validate_success(api.bill_liability(liability["id"], OPS))
    validate_success(api.record_liability_payment(liability["id"], OPS))
    pool = create_pool()
    batch = validate_success(
        api.create_distribution_batch(
            report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
        ),
        expected_status=201,
    )
    # Advance the logical clock to exactly scheduled_for so the batch is due.
    set_clock("2026-10-01T00:00:00Z")
    validate_success(
        api.execute_distribution_batch(
            batch["id"],
            {"expected_distribution_batch_version": batch["version"]},
            OPS,
        )
    )
    return {
        "licensee": lic, "report": report, "liability": liability,
        "batch": batch, "pool": pool, "ro": ro, "fa_a": fa_a, "fa_b": fa_b,
        "rec_a": rec_a, "rec_b": rec_b,
    }


def _lines_for_payee(api, batch_id, **filters):
    """Cross-batch line query (payee-id filters live on /distribution-lines per
    PRD §3.6), then restrict to the given batch client-side."""
    lines, _ = validate_paginated(api.list_distribution_lines(OPS,
                                                              params=filters))
    return [l for l in lines if l["distribution_batch_id"] == batch_id]


class TestDistributionWaterfall:
    def test_distribution_split_multifactor_waterfall_amounts(self, api):
        """PRD §3.6: "Each recording pool is then split by the statutory shares:
        the rights owner receives the floor of 50 percent of the recording pool;
        the featured artist receives the floor of 45 percent; the remainder —
        the recording pool minus those two floors, never negative — goes to the
        nonfeatured funds, with the floor of half the remainder going to the AFM
        fund and the leftover cents going to the SAG-AFTRA fund (the remainder
        cent always lands with SAG-AFTRA)."
        PRD §3.6: "its recording pool is the matched pool multiplied by the
        recording's matched performance count and divided by the report's
        `matched_performances`, rounded half-up — so a recording with a higher
        matched performance count receives a proportionally larger recording
        pool, with raw performance counts as weights and no normalization."

        Design: Difficulty/combinatorial_formula/distribution_split_multifactor_waterfall
        """
        env = _setup_distribution_waterfall(api)
        batch = env["batch"]
        rec_a = env["rec_a"]
        rec_b = env["rec_b"]
        fa_a = env["fa_a"]
        fa_b = env["fa_b"]
        ro = env["ro"]

        # rec A: pool 57143 -> RO floor(28571.5)=28571, FA floor(25714.35)=25714,
        # remainder 2858 -> AFM 1429, SAG 1429.
        ro_a = _lines_for_payee(api, batch["id"], payee_type="RIGHTS_OWNER",
                                payee_rights_owner_id=ro["id"])
        fa_a_lines = _lines_for_payee(api, batch["id"],
                                      payee_type="FEATURED_ARTIST",
                                      payee_artist_id=fa_a["id"])
        # Per-recording featured-artist lines pin the rec A / rec B split.
        assert len(fa_a_lines) == 1 and fa_a_lines[0]["amount_cents"] == 25714
        fa_b_lines = _lines_for_payee(api, batch["id"],
                                      payee_type="FEATURED_ARTIST",
                                      payee_artist_id=fa_b["id"])
        assert len(fa_b_lines) == 1 and fa_b_lines[0]["amount_cents"] == 17142

        # Both recordings share the same rights owner; total RO = 28571+19047.
        assert sum(l["amount_cents"] for l in ro_a) == 28571 + 19047

        # Nonfeatured funds: AFM 1429 + 953 = 2382; SAG_AFTRA 1429 + 953 = 2382.
        afm = _lines_for_payee(api, batch["id"], payee_type="NONFEATURED_FUND")
        afm_amounts = {l["fund_type"]: [] for l in afm}
        for l in afm:
            afm_amounts[l["fund_type"]].append(l["amount_cents"])
        assert sorted(afm_amounts["AFM"]) == [953, 1429]
        assert sorted(afm_amounts["SAG_AFTRA"]) == [953, 1429]

        liab = validate_success(
            api.get_royalty_liability(env["liability"]["id"], OPS)
        )
        assert liab["liability_status"] == "SETTLED"

    def test_distribution_unmatched_share_accrues_to_pool(self, api):
        """PRD §3.6: "First the pool is apportioned by identification:
        `matched_pool_cents` is the distributable pool multiplied by the
        report's `matched_performances` and divided by its
        `total_performances`, rounded half-up to whole cents; the remainder of
        the pool is the unmatched share, which accrues to the UnclaimedPool
        covering the report's period (§3.9)."
        PRD §3.9: "Accrual happens at batch execution: when a batch's report
        period lies inside a pool's window, the batch's unmatched share (§3.6)
        is added to that pool's `accrued_unmatched_cents`."

        Design: Difficulty/combinatorial_formula/distribution_split_multifactor_waterfall
        """
        env = _setup_distribution_waterfall(api)
        pool_now = validate_success(
            api.get_unclaimed_pool(env["pool"]["id"], OPS)
        )
        # matched_pool = round_half_up(100000 x 100000/105000) = 95238;
        # unmatched share = 4762.
        assert pool_now["accrued_unmatched_cents"] == 4762
