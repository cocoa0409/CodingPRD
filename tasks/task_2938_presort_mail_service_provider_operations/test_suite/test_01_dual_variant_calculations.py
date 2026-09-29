"""Two calculations that each exist in two variants over the same inputs.

The standalone postage estimate and the commingled batch price are derived from
the same rate machinery yet must disagree, and the zone-weighted and
piece-weighted service indices are computed over one identical population of
scanned records yet must also disagree. Both pairs are exercised here on the
same mail, because a single-variant implementation passes only one side.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_pricing,
    assert_field_values,
    assert_pct_2dp,
    assert_service_level_index,
    assert_sum_of_cents,
    find_by_id,
)
from test_helpers.test_users import POSTAGE_MANAGER


class TestStandaloneVersusCommingledRate:
    """The same 1200 and 1800 pieces, priced alone and priced pooled."""

    def test_standalone_estimate_prices_each_job_alone_at_the_basic_tier(self, api):
        """A job's own estimate ignores the pool it sits in.

        "The presort tier is derived from that single job's piece count rather than
        from any pooled total, and the drop-ship discount in basis points is forced
        to zero, because an unpooled job is not tendered at an entry point on its
        own and therefore earns no entry discount." The contract even fixes the
        arithmetic: "For a 1200-piece `MARKETING_MAIL` job this prices at the
        `BASIC` tier with a `standalone_rate_mills_per_piece` of 29440 — 29.44 cents
        a piece."

        Design: Difficulty/dual_variant_calc/standalone_versus_commingled_rate_divergence
        """
        world = fx.build_sorted_world(api)

        estimate_a = validate_success(
            api.get_postage_estimate(world.job_a_id, POSTAGE_MANAGER)
        )
        assert_field_values(
            estimate_a,
            {
                "piece_count": fx.JOB_A_ACCEPTED,
                "standalone_tier": fx.STANDALONE_TIER,
                "standalone_rate_mills_per_piece": fx.STANDALONE_RATE_MILLS,
                "standalone_postage_cents": fx.STANDALONE_A_CENTS,
            },
        )

        estimate_b = validate_success(
            api.get_postage_estimate(world.job_b_id, POSTAGE_MANAGER)
        )
        assert_field_values(
            estimate_b,
            {
                "piece_count": fx.JOB_B_ACCEPTED,
                "standalone_tier": fx.STANDALONE_TIER,
                "standalone_rate_mills_per_piece": fx.STANDALONE_RATE_MILLS,
                "standalone_postage_cents": fx.STANDALONE_B_CENTS,
            },
        )

    def test_commingled_batch_prices_the_pool_and_splits_it_pro_rata(self, api):
        """Pooled, the same mail reaches a deeper tier and a lower rate.

        "Pooled inside a 3000-piece batch entered at an `SCF` facility offering a
        300-basis-point entry discount, the same 1200 pieces reach the
        `THREE_DIGIT` tier and price at 26384 mills a piece — a strictly lower cost
        for identical mail, purchased entirely with other mailers' volume."

        Design: Difficulty/dual_variant_calc/standalone_versus_commingled_rate_divergence
        """
        world = fx.build_sorted_world(api)

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert_batch_pricing(
            batch,
            status="SORTED",
            achieved_tier=fx.POOLED_TIER,
            rate_mills=fx.POOLED_RATE_MILLS,
            postage_cents=fx.POOLED_POSTAGE_CENTS,
        )

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, POSTAGE_MANAGER)
        )
        member_a = find_by_id(members, world.member_a_id)
        member_b = find_by_id(members, world.member_b_id)
        assert member_a["allocated_postage_cents"] == fx.MEMBER_A_POSTAGE_CENTS
        assert member_b["allocated_postage_cents"] == fx.MEMBER_B_POSTAGE_CENTS

    def test_the_two_variants_diverge_on_identical_mail(self, api):
        """Standing alone costs strictly more than pooling does.

        Commingling is the reason the bureau exists: "This is precisely where
        commingling pays. Consider 1200 pieces of `MARKETING_MAIL`. Standing alone
        they reach only the `BASIC` tier with no entry discount, at 29440 mills a
        piece."

        Design: Difficulty/dual_variant_calc/standalone_versus_commingled_rate_divergence
        """
        world = fx.build_sorted_world(api)

        standalone_a = validate_success(
            api.get_postage_estimate(world.job_a_id, POSTAGE_MANAGER)
        )["standalone_postage_cents"]
        standalone_b = validate_success(
            api.get_postage_estimate(world.job_b_id, POSTAGE_MANAGER)
        )["standalone_postage_cents"]
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )

        standalone_total = standalone_a + standalone_b
        assert standalone_total == fx.STANDALONE_A_CENTS + fx.STANDALONE_B_CENTS
        assert batch["batch_postage_cents"] == fx.POOLED_POSTAGE_CENTS
        assert standalone_total - batch["batch_postage_cents"] == 9168, (
            "the two variants must diverge: 88320 standalone against 79152 pooled"
        )

    def test_the_pooled_rate_is_floored_exactly_once(self, api):
        """Chaining the two discount factors before the single floor.

        "The entire numerator is evaluated in exact integer arithmetic and floored
        **exactly once, at the very end** — flooring after the tier factor and again
        after the entry factor is forbidden and produces a different rate." The
        contract also fixes where the floor sits: "divide the whole result by one
        hundred million; and take the floor of that single quotient."

        Design: Difficulty/dual_variant_calc/standalone_versus_commingled_rate_divergence
        """
        world = fx.build_sorted_world(api)

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        single_quotient_floor = (
            32 * 1000 * (10000 - 1500) * (10000 - 300)
        ) // 100_000_000
        assert single_quotient_floor == fx.POOLED_RATE_MILLS
        assert batch["rate_mills_per_piece"] == single_quotient_floor, (
            "the rate must be floored once over the whole expression, not per factor"
        )
        # Rounding the same quotient half up instead of flooring it would round a
        # rate up in the bureau's own favour, which the contract forbids.
        assert batch["rate_mills_per_piece"] <= (
            32 * 1000 * (10000 - 1500) * (10000 - 300)
        ) / 100_000_000

    def test_the_member_shares_sum_to_the_pooled_postage_exactly(self, api):
        """The pooled pool is split without gaining or losing a cent.

        "The invariant is absolute: the allocated amounts sum to the pool exactly,
        for every pool and every member set."

        Design: Difficulty/dual_variant_calc/standalone_versus_commingled_rate_divergence
        """
        world = fx.build_sorted_world(api)

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, POSTAGE_MANAGER)
        )
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert_sum_of_cents(
            [member["allocated_postage_cents"] for member in members],
            batch["batch_postage_cents"],
            what="member allocations",
        )


class TestZoneWeightedVersusPieceWeightedIndex:
    """One scanned population, two deliberately different indices."""

    def test_the_deposit_opened_records_carry_each_container_commitment(self, api):
        """Each record inherits its container's zone, commitment and volume.

        "each newly deposited container opens exactly one **service-level record**,
        created in ascending container `sequence_index` order, carrying that
        container's `sort_container_id`, its `zone`, its `committed_days` and its
        `piece_count`". The 021 tray is served by the SCF, where "an `SCF` gives
        `zone` 2 and a base of 2 days"; the 941 tray is not, so "the container falls
        to `zone` 8 with a base of 5 days", and "`MARKETING_MAIL` adds 2 days" to
        both. On time is settled by the scan: "delivering in exactly the committed
        number of days counts as on time."

        Design: Difficulty/dual_variant_calc/zone_weighted_versus_piece_weighted_service_index
        """
        world = fx.build_scanned_world(api)

        record_1 = validate_success(
            api.get_service_level_record(world.slr_1_id, POSTAGE_MANAGER)
        )
        assert_field_values(
            record_1,
            {
                "sort_container_id": world.container_1_id,
                "zone": 2,
                "committed_days": 4,
                "piece_count": fx.CONTAINER_1_PIECES,
                "actual_delivery_days": 2,
                "on_time": True,
            },
        )

        record_2 = validate_success(
            api.get_service_level_record(world.slr_2_id, POSTAGE_MANAGER)
        )
        assert_field_values(
            record_2,
            {
                "sort_container_id": world.container_2_id,
                "zone": 8,
                "committed_days": 7,
                "piece_count": fx.CONTAINER_2_PIECES,
                "actual_delivery_days": 9,
                "on_time": False,
            },
        )

    def test_both_indices_are_reported_over_the_scanned_population(self, api):
        """The client's index reaches outward from the records.

        "The response also reports `record_count`, the number of scanned records in
        the population, and `on_time_count`, the number of those whose `on_time` is
        true." Over one on-time zone-2 record of 1000 pieces and one late zone-8
        record of 2000 pieces the contract fixes both figures: a
        "`zone_weighted_index` of 28.57 and a `piece_weighted_index` of 33.33."

        Design: Difficulty/dual_variant_calc/zone_weighted_versus_piece_weighted_service_index
        """
        world = fx.build_scanned_world(api)

        index = validate_success(
            api.get_client_service_level(world.acme_id, POSTAGE_MANAGER)
        )
        assert_service_level_index(
            index,
            record_count=2,
            on_time_count=1,
            zone_weighted_index=28.57,
            piece_weighted_index=33.33,
        )

    def test_the_two_indices_disagree_on_identical_records(self, api):
        """Two weightings over one population must not collapse into one figure.

        "The two indexes genuinely disagree on identical inputs: one late `zone` 8
        container of 2000 pieces alongside one on-time `zone` 2 container of 1000
        pieces yields a `zone_weighted_index` of 28.57 and a `piece_weighted_index`
        of 33.33." The zone weights are the contract's own: "`zone` 1 weighs 1,
        `zone` 2 weighs 2, `zone` 4 weighs 3, and `zone` 8 weighs 5".

        Design: Difficulty/dual_variant_calc/zone_weighted_versus_piece_weighted_service_index
        """
        world = fx.build_scanned_world(api)

        index = validate_success(
            api.get_client_service_level(world.acme_id, POSTAGE_MANAGER)
        )
        assert index["zone_weighted_index"] != index["piece_weighted_index"], (
            "the contractual and the volume-fair metric must differ on this input"
        )
        assert_pct_2dp(index, "zone_weighted_index", 28.57)
        assert_pct_2dp(index, "piece_weighted_index", 33.33)

    def test_both_clients_of_one_pool_see_the_same_two_records(self, api):
        """A commingled container counts for every mailer inside it.

        "One commingled container therefore counts once for every client with mail
        in that batch."

        Design: Difficulty/dual_variant_calc/zone_weighted_versus_piece_weighted_service_index
        """
        world = fx.build_scanned_world(api)

        index_a = validate_success(
            api.get_client_service_level(world.acme_id, POSTAGE_MANAGER)
        )
        index_b = validate_success(
            api.get_client_service_level(world.bore_id, POSTAGE_MANAGER)
        )
        assert_service_level_index(
            index_b,
            record_count=2,
            on_time_count=1,
            zone_weighted_index=28.57,
            piece_weighted_index=33.33,
        )
        assert index_a["zone_weighted_index"] == index_b["zone_weighted_index"]
        assert index_a["piece_weighted_index"] == index_b["piece_weighted_index"]
