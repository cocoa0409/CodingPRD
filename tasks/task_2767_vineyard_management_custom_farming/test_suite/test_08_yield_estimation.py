"""The two estimation methods and the block's governing tonnage."""
from test_helpers import (
    MISSING_UUID_B,
    ApiErrorId,
    assert_block_harvest_ledger,
    assert_money,
    assert_yield_estimate,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestEstimateFilingGuards:
    """PRD §2.5 and §3.7 — the path parent and the method-conditional fields."""

    def test_filing_under_an_unknown_block_reports_block_not_found(self, api):
        """A request against a block's scouting observations resolves the block segment first; if no such block exists the answer is `ERR_BLOCK_NOT_FOUND` (HTTP 404), and nothing further about the request is inspected.

        Design: Corner/entities/yield_estimate_under_unknown_block_not_found
        """
        s = fx.setup_ranch_with_block(api)

        validate_error(
            api.create_yield_estimate(
                MISSING_UUID_B,
                f.cluster_count_estimate_payload(sample_date="2026-08-25"),
                fx.AG,
            ),
            ApiErrorId.ERR_BLOCK_NOT_FOUND,
        )

        rows, meta = validate_paginated(
            api.list_yield_estimates(s.block["id"], fx.AG,
                                     {"limit": 10, "offset": 0})
        )
        assert rows == []
        assert meta["total_count"] == 0

        block = fx.read_block(api, s.block["id"])
        assert_money(block["governing_estimate_tons"], 0.00,
                     "governing_estimate_tons")
        assert block["harvest_posture"] == "NOT_ESTIMATED"

    def test_a_cluster_count_estimate_carrying_a_berry_field_is_refused(self, api):
        """The remaining inputs are method-conditional and are enforced strictly, as set out in §2.6: a `CLUSTER_COUNT` estimate requires `avg_cluster_weight_lb`, the historical mean cluster weight in pounds, and must omit the three berry fields entirely; a `BERRY_SAMPLE` estimate requires all three of `berries_per_cluster` (the mean berry count per cluster), `avg_berry_weight_g` (the mean berry weight in grams) and `days_to_harvest` (the whole number of days from `sample_date` to the planned pick), and must omit `avg_cluster_weight_lb`.

        Design: Corner/validations/yield_estimate_cluster_count_with_berry_fields_rejected
        """
        s = fx.setup_ranch_with_block(api)

        validate_error(
            api.create_yield_estimate(
                s.block["id"],
                f.cluster_count_estimate_payload(sample_date="2026-08-01",
                                                 berries_per_cluster=95),
                fx.AG,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        assert fx.read_block(api, s.block["id"])["harvest_posture"] == "NOT_ESTIMATED"

        data = validate_success(
            api.create_yield_estimate(
                s.block["id"],
                f.cluster_count_estimate_payload(sample_date="2026-08-01"),
                fx.AG,
            ),
            201,
        )
        assert_yield_estimate(data)
        assert_money(data["estimated_tons"], 91.47, "estimated_tons")
        assert data["berries_per_cluster"] is None


class TestBerrySampleGrowthProjection:
    """PRD §3.7 — the sampled berry weight is inflated towards the pick."""

    def test_days_to_harvest_inflates_the_derived_cluster_weight(self, api):
        """Under the `BERRY_SAMPLE` method, the cluster weight is first derived rather than supplied — `berries_per_cluster` multiplied by `avg_berry_weight_g`, divided by the 453.592 grams in a pound — and then inflated by a growth factor of one plus four thousandths per day of `days_to_harvest`, on the reasoning that berries continue to gain weight between sampling and picking; `estimated_tons` is the total cluster count multiplied by that derived cluster weight, multiplied by that growth factor, and divided by 2,000.

        Design: Corner/calculations/berry_sample_estimate_projects_growth_to_harvest
        """
        s = fx.setup_ranch_with_block(api)
        assert s.block["vine_count"] == 13612

        flat = fx.file_berry_sample_estimate(api, s.block["id"], headers=fx.AG,
                                             sample_date="2026-07-10",
                                             days_to_harvest=0)
        grown = fx.file_berry_sample_estimate(api, s.block["id"], headers=fx.AG,
                                              sample_date="2026-08-01",
                                              days_to_harvest=30)

        assert_yield_estimate(flat)
        assert_money(flat["estimated_tons"], 61.58, "estimated_tons")
        assert_money(flat["estimated_tons_per_acre"], 4.93,
                     "estimated_tons_per_acre")
        assert_yield_estimate(grown)
        assert_money(grown["estimated_tons"], 68.97, "estimated_tons")
        assert_money(grown["estimated_tons_per_acre"], 5.52,
                     "estimated_tons_per_acre")

        for row in (flat, grown):
            assert row["vine_count_at_estimate"] == 13612
            assert row["avg_cluster_weight_lb"] is None


class TestGoverningEstimateSelection:
    """PRD §3.7 — exactly one estimate governs, chosen chronologically."""

    def test_the_latest_sample_date_governs_and_ties_break_on_creation(self, api):
        """Because a block accumulates estimates over a season, exactly one of them governs at any moment, and the rule is chronological rather than optimistic or conservative: among all estimates filed for the block regardless of `method`, the governing estimate is the one with the latest `sample_date`, and when two share the same `sample_date` the one created later wins.

        Design: Corner/calculations/governing_estimate_takes_latest_sample_date_then_latest_created_at
        """
        s = fx.setup_ranch_with_block(api)

        early = fx.file_cluster_count_estimate(api, s.block["id"], headers=fx.AG,
                                               sample_date="2026-07-20")
        assert_money(early["estimated_tons"], 91.47, "estimated_tons")
        assert_money(fx.read_block(api, s.block["id"])["governing_estimate_tons"],
                     91.47, "governing_estimate_tons")

        lower_but_later = fx.file_berry_sample_estimate(
            api, s.block["id"], headers=fx.AG, sample_date="2026-08-01"
        )
        assert_money(lower_but_later["estimated_tons"], 68.97, "estimated_tons")
        block = fx.read_block(api, s.block["id"])
        assert_money(block["governing_estimate_tons"], 68.97,
                     "governing_estimate_tons")
        assert_money(block["remaining_estimated_tons"], 68.97,
                     "remaining_estimated_tons")

        tie_break = fx.file_cluster_count_estimate(api, s.block["id"],
                                                   sample_date="2026-08-01")
        assert_money(tie_break["estimated_tons"], 91.47, "estimated_tons")

        block = fx.read_block(api, s.block["id"])
        assert_money(block["governing_estimate_tons"], 91.47,
                     "governing_estimate_tons")
        assert_money(block["remaining_estimated_tons"], 91.47,
                     "remaining_estimated_tons")
        assert block["harvest_posture"] == "OPEN"

        rows, meta = validate_paginated(
            api.list_yield_estimates(s.block["id"], fx.AG)
        )
        assert meta["total_count"] == 3
        assert sorted(row["estimated_tons"] for row in rows) == [68.97, 91.47, 91.47]


class TestMethodDivergence:
    """PRD §3.7 — the two methods disagree on identical vines."""

    def test_the_cluster_count_branch_uses_the_supplied_cluster_weight(self, api):
        """Under the `CLUSTER_COUNT` method, `estimated_tons` is that total cluster count multiplied by `avg_cluster_weight_lb` and then divided by the 2,000 pounds in a ton.

        Design: Difficulty/dual_variant_calc/yield_estimate_cluster_count_vs_berry_sample_divergence
        """
        s = fx.setup_ranch_with_block(api)
        assert s.block["vine_count"] == 13612

        data = validate_success(
            api.create_yield_estimate(
                s.block["id"],
                f.cluster_count_estimate_payload(sample_date="2026-08-10"),
                fx.AG,
            ),
            201,
        )

        assert_yield_estimate(data)
        assert data["method"] == "CLUSTER_COUNT"
        assert data["vine_count_at_estimate"] == 13612
        assert_money(data["estimated_tons"], 91.47, "estimated_tons")
        assert_money(data["estimated_tons_per_acre"], 7.32,
                     "estimated_tons_per_acre")
        assert data["berries_per_cluster"] is None
        assert data["avg_berry_weight_g"] is None
        assert data["days_to_harvest"] is None

        assert_block_harvest_ledger(fx.read_block(api, s.block["id"]),
                                    91.47, 0.00, 0.00, 91.47, "OPEN")

    def test_the_two_methods_land_twenty_two_and_a_half_tons_apart(self, api):
        """A `BERRY_SAMPLE` estimate on the same block with 95 berries per cluster, a 1.35-gram mean berry weight and 30 days to harvest — a growth factor of 1.120 — yields an `estimated_tons` of 68.97, or 5.52 tons per acre.

        Design: Difficulty/dual_variant_calc/yield_estimate_cluster_count_vs_berry_sample_divergence
        """
        s = fx.setup_ranch_with_block(api)

        cluster_count = fx.file_cluster_count_estimate(api, s.block["id"],
                                                        headers=fx.AG,
                                                        sample_date="2026-08-10")
        berry_sample = fx.file_berry_sample_estimate(api, s.block["id"],
                                                     headers=fx.AG,
                                                     sample_date="2026-08-20")

        assert berry_sample["vine_count_at_estimate"] == 13612
        assert_money(berry_sample["estimated_tons"], 68.97, "estimated_tons")
        assert_money(berry_sample["estimated_tons_per_acre"], 5.52,
                     "estimated_tons_per_acre")
        assert_money(cluster_count["estimated_tons"] -
                     berry_sample["estimated_tons"], 22.50, "tonnage divergence")

        assert_block_harvest_ledger(fx.read_block(api, s.block["id"]),
                                    68.97, 0.00, 0.00, 68.97, "OPEN")
