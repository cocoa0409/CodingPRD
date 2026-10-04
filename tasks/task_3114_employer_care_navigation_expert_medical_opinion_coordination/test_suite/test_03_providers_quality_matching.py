"""Provider quality scores, ranked provider matching, and snapshot
uniqueness."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_quality_snapshot_payload,
    set_clock, setup_employer_with_member,
    setup_provider, setup_provider_with_snapshot,
)
from test_helpers.test_users import make_member_headers


class TestCompositeQualityScore:
    def test_full_confidence_at_or_above_volume_threshold(
            self, api, platform_admin_headers):
        """PRD §3.2: "When the snapshot is backed by at least thirty
        adjudicated claims — the full-confidence volume threshold, and exactly
        thirty qualifies — the composite equals the raw blend."
        PRD §3.2: "The raw score is a weighted blend: half the outcome score,
        three-tenths the cost-efficiency score, and one-fifth the access
        score."

        Design: Difficulty/combinatorial_formula/quality_score_weighted_shrinkage_volume_boundary
        """
        set_clock()
        prov40 = setup_provider(name="HighVol Ortho", specialty="ORTHOPEDICS")
        snap40 = validate_success(api.create_quality_snapshot(
            prov40["id"], create_quality_snapshot_payload(
                outcome_score=80, cost_efficiency_score=60, access_score=90,
                claims_volume=40), platform_admin_headers), expected_status=201)
        # raw = 0.5*80 + 0.3*60 + 0.2*90 = 76.0
        assert snap40["composite_quality_score"] == 76.0

        prov30 = setup_provider(name="ExactVol Ortho", specialty="ORTHOPEDICS")
        snap30 = validate_success(api.create_quality_snapshot(
            prov30["id"], create_quality_snapshot_payload(
                outcome_score=80, cost_efficiency_score=60, access_score=90,
                claims_volume=30), platform_admin_headers), expected_status=201)
        assert snap30["composite_quality_score"] == 76.0

    def test_low_volume_shrinks_toward_network_mean(
            self, api, platform_admin_headers):
        """PRD §3.2: "Below that volume, the score is shrunk toward the network
        mean of 70.0 in proportion to the evidence: the composite is the claims
        volume divided by thirty, times the raw blend, plus one minus that
        fraction, times 70.0."

        Design: Difficulty/combinatorial_formula/quality_score_weighted_shrinkage_volume_boundary
        """
        set_clock()
        prov = setup_provider(name="LowVol Ortho", specialty="ORTHOPEDICS")
        snap = validate_success(api.create_quality_snapshot(
            prov["id"], create_quality_snapshot_payload(
                outcome_score=80, cost_efficiency_score=60, access_score=90,
                claims_volume=20), platform_admin_headers), expected_status=201)
        # (20/30)*76.0 + (10/30)*70.0 = 50.6667 + 23.3333 -> 74.0 (2dp half-up)
        assert snap["composite_quality_score"] == 74.0

    def test_volume_just_below_threshold_shrinks_while_threshold_does_not(
            self, api, platform_admin_headers):
        """PRD §3.2: "When the snapshot is backed by at least thirty
        adjudicated claims — the full-confidence volume threshold, and exactly
        thirty qualifies — the composite equals the raw blend."

        Design: Difficulty/combinatorial_formula/quality_score_weighted_shrinkage_volume_boundary
        """
        set_clock()
        below = setup_provider(name="BelowVol", specialty="ORTHOPEDICS")
        snap_below = validate_success(api.create_quality_snapshot(
            below["id"], create_quality_snapshot_payload(
                outcome_score=80, cost_efficiency_score=60, access_score=90,
                claims_volume=29), platform_admin_headers), expected_status=201)
        # (29/30)*76 + (1/30)*70 = 73.4666 + 2.3333 -> 75.8
        assert snap_below["composite_quality_score"] == 75.8

        exact = setup_provider(name="ExactVol", specialty="ORTHOPEDICS")
        snap_exact = validate_success(api.create_quality_snapshot(
            exact["id"], create_quality_snapshot_payload(
                outcome_score=80, cost_efficiency_score=60, access_score=90,
                claims_volume=30), platform_admin_headers), expected_status=201)
        assert snap_exact["composite_quality_score"] == 76.0


class TestDuplicateSnapshot:
    def test_duplicate_snapshot_period_rejected(
            self, api, platform_admin_headers):
        """PRD §3.2: "Only one snapshot may exist per provider and
        `period_start`; a duplicate is rejected with `ERR_DUPLICATE_SNAPSHOT`
        (409)."

        Design: Corner/validations/duplicate_snapshot_period_rejected
        """
        set_clock()
        prov = setup_provider(name="Snap Clinic")
        validate_success(api.create_quality_snapshot(
            prov["id"], create_quality_snapshot_payload(
                period_start="2026-01-01", period_end="2026-03-31",
                outcome_score=70, cost_efficiency_score=70, access_score=70,
                claims_volume=100), platform_admin_headers), expected_status=201)

        dup = api.create_quality_snapshot(
            prov["id"], create_quality_snapshot_payload(
                period_start="2026-01-01", period_end="2026-06-30",
                outcome_score=80, cost_efficiency_score=80, access_score=80,
                claims_volume=200), platform_admin_headers)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_SNAPSHOT,
                       expected_status=409)

        snaps = validate_success(api.list_quality_snapshots(
            prov["id"], platform_admin_headers))
        assert len(snaps) == 1


class TestProviderMatchRanking:
    def test_provider_match_ranking_orders_by_score_with_tie_breaks(
            self, api, platform_admin_headers):
        """PRD §3.2: "Each candidate's `match_score` is its
        `composite_quality_score` multiplied by a network factor — 1.0 for an
        `IN_NETWORK` provider, 0.8 for an `OUT_OF_NETWORK` one — rounded half-up
        to two decimal places. Matches are ordered by `match_score` descending;
        ties break first by the latest snapshot's `period_end` descending, then
        by the provider's `created_at` ascending (never by id)."

        Design: Corner/calculations/provider_match_ranking_orders_by_score_with_tie_breaks
        """
        set_clock()
        _, member = setup_employer_with_member()

        p_in, _ = setup_provider_with_snapshot(
            {"name": "P In", "specialty": "DERMATOLOGY",
             "network_status": "IN_NETWORK"},
            {"outcome_score": 80, "cost_efficiency_score": 60,
             "access_score": 90, "claims_volume": 40,
             "period_start": "2026-01-01", "period_end": "2026-06-30"})
        p_out, _ = setup_provider_with_snapshot(
            {"name": "P Out", "specialty": "DERMATOLOGY",
             "network_status": "OUT_OF_NETWORK"},
            {"outcome_score": 80, "cost_efficiency_score": 60,
             "access_score": 90, "claims_volume": 40,
             "period_start": "2026-01-01", "period_end": "2026-06-30"})
        p_t1, _ = setup_provider_with_snapshot(
            {"name": "P Tie1", "specialty": "DERMATOLOGY"},
            {"outcome_score": 50, "cost_efficiency_score": 50,
             "access_score": 50, "claims_volume": 50,
             "period_start": "2026-01-01", "period_end": "2026-03-31"})
        p_t2, _ = setup_provider_with_snapshot(
            {"name": "P Tie2", "specialty": "DERMATOLOGY"},
            {"outcome_score": 50, "cost_efficiency_score": 50,
             "access_score": 50, "claims_volume": 50,
             "period_start": "2026-01-01", "period_end": "2026-06-30"})

        resp = api.list_provider_matches(
            member["id"], make_member_headers(member["id"]),
            params={"specialty": "DERMATOLOGY"})
        rows = validate_success(resp)
        assert len(rows) == 4

        by_provider = {r["provider_id"]: r for r in rows}
        assert by_provider[p_in["id"]]["rank"] == 1
        assert by_provider[p_in["id"]]["match_score"] == 76.0
        assert by_provider[p_out["id"]]["rank"] == 2
        assert by_provider[p_out["id"]]["match_score"] == 60.8
        assert by_provider[p_t2["id"]]["rank"] == 3
        assert by_provider[p_t1["id"]]["rank"] == 4
        assert [r["rank"] for r in rows] == [1, 2, 3, 4]

    def test_provider_match_empty_specialty_returns_no_match(
            self, api, platform_admin_headers):
        """PRD §3.2: "The candidate set is every provider whose `specialty`
        equals the requested one and who has at least one quality snapshot".
        PRD §3.2: "If the candidate set is empty, the request is rejected with
        `ERR_NO_PROVIDER_MATCH` (422)."

        Design: Corner/calculations/provider_match_empty_specialty_returns_no_match
        """
        set_clock()
        _, member = setup_employer_with_member()
        setup_provider(name="NoSnap Podiatry", specialty="PODIATRY")

        no_providers = api.list_provider_matches(
            member["id"], make_member_headers(member["id"]),
            params={"specialty": "NEUROLOGY"})
        validate_error(no_providers, ApiErrorId.ERR_NO_PROVIDER_MATCH,
                       expected_status=422)

        no_snapshot = api.list_provider_matches(
            member["id"], make_member_headers(member["id"]),
            params={"specialty": "PODIATRY"})
        validate_error(no_snapshot, ApiErrorId.ERR_NO_PROVIDER_MATCH,
                       expected_status=422)

    def test_provider_match_view_is_ephemeral_not_persisted(
            self, api, platform_admin_headers):
        """PRD §2.5: "the ProviderMatch returned by the provider-matching
        capability is an ephemeral computed view, never persisted — it carries
        `id` and `created_at` only, and both `updated_at` and `version` are
        absent from it."
        PRD §3.2: "Each returned `ProviderMatch` exposes `provider_id`,
        `provider_name`, `specialty`, `network_status`,
        `composite_quality_score`, `network_factor`, `match_score`, and its
        1-based `rank`."

        Design: Corner/entities/provider_match_view_is_ephemeral_not_persisted
        """
        set_clock()
        _, member = setup_employer_with_member()
        prov, _ = setup_provider_with_snapshot(
            {"name": "Cardio A", "specialty": "CARDIOLOGY"},
            {"outcome_score": 90, "cost_efficiency_score": 90,
             "access_score": 90, "claims_volume": 100})

        rows = validate_success(api.list_provider_matches(
            member["id"], make_member_headers(member["id"]),
            params={"specialty": "CARDIOLOGY"}))
        assert len(rows) == 1
        row = rows[0]
        assert row["provider_id"] == prov["id"]
        assert "match_score" in row
        assert "rank" in row
        assert "id" in row and "created_at" in row
        assert "updated_at" not in row
        assert "version" not in row
