"""Block allocation arithmetic, rounding order and the compensating credit."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    setup_three_way_allocation_scenario,
    setup_zero_execution_block,
    setup_account_with_frozen_block,
    setup_block_model_scenario,
    setup_executed_block,
    allocation_rows,
    refetch_block,
)
"""Block allocation arithmetic, rounding order and the compensating credit."""
"""Block allocation arithmetic, rounding order and the compensating credit."""

ADVISOR = TEST_USERS["advisor_ops_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]


class TestAllocationRoundingOrder:

    def test_production_order_rounds_each_allocation_independently(self):
        """PRD §3.4: "Fourth, each allocation's `allocated_cost_cents` is its share
        quantity multiplied by the execution price and divided by ten billion,
        rounded half up to whole cents."
        PRD §3.4: "The pinned production order rounds each allocation's cost to the
        cent independently, so the sum of the allocations' allocated costs equals the
        block notional with no residual cent left over."

        Design: Difficulty/dual_variant_calc/block_allocate_then_round_vs_round_then_allocate_variant
        """
        scenario = setup_three_way_allocation_scenario(allocate=True)
        block = refetch_block(scenario["block"]["id"])
        assert block["block_status"] == "ALLOCATED"
        assert block["unallocated_share_micros"] == 0

        rows = allocation_rows(block["id"])
        by_rank = {row["allocation_rank"]: row for row in rows}
        assert by_rank[2]["share_micros"] == 333_000_000
        assert by_rank[2]["allocated_cost_cents"] == 1_744_088
        assert by_rank[3]["share_micros"] == 334_000_000
        assert by_rank[3]["allocated_cost_cents"] == 1_749_325

    def test_rounding_order_excess_is_observable_against_the_block_notional(self):
        """PRD §3.4: "An indicative preview — a read-only capability that splits the
        block's executed notional without writing anything — instead rounds the
        block-level notional once and then splits it proportionally, which for a
        three-way split drifts the sum of allocated costs away from the production
        order whenever more than one allocation rounds up."
        PRD §3.4: "The preview writes no rows but reports the indicative figure as
        `preview_notional_cents`, which is null until a preview has actually been
        run."

        Design: Difficulty/dual_variant_calc/block_allocate_then_round_vs_round_then_allocate_variant
        """
        scenario = setup_three_way_allocation_scenario()
        block = scenario["block"]

        preview = validate_success(api_client.preview_block_allocation(
            block["id"],
            {"executed_share_micros": 1_000_000_000, "execution_price_micros": 52_375_001},
            ADVISOR,
        ), 200)
        assert preview["preview_notional_cents"] == 5_237_500

        validate_success(api_client.allocate_block_order(
            block["id"], {"expected_block_order_version": block["version"]}, ADVISOR, row=block), 200)
        rows = allocation_rows(block["id"])
        allocated_total = sum(row["allocated_cost_cents"] for row in rows)
        assert allocated_total == 5_237_501
        assert allocated_total - preview["preview_notional_cents"] == 1

    def test_average_price_is_recomputed_from_the_rounded_cost(self):
        """PRD §3.4: "Fifth, each allocation's `average_price_micros` is its allocated
        cost multiplied by ten billion and divided by its share quantity, rounded
        half up to whole micros."

        Design: Difficulty/dual_variant_calc/block_allocate_then_round_vs_round_then_allocate_variant
        """
        scenario = setup_three_way_allocation_scenario(allocate=True)
        rows = allocation_rows(scenario["block"]["id"])
        by_rank = {row["allocation_rank"]: row for row in rows}
        assert by_rank[1]["average_price_micros"] == 52_375_015
        assert by_rank[2]["average_price_micros"] == 52_375_015
        assert by_rank[3]["average_price_micros"] == 52_375_000


class TestNestedRoundingAndResidual:

    def test_allocation_sum_exceeds_the_block_notional_by_exactly_one_cent(self):
        """PRD §3.4: "The allocated total is the sum of the allocations'
        `allocated_cost_cents`. If the allocated total exceeds the block notional,
        the positive drift is distributed back as execution credits of one cent at
        a time".
        PRD §3.4: "each allocation's `allocated_cost_cents` is its share quantity
        multiplied by the execution price and divided by ten billion, rounded half
        up to whole cents."

        Design: Difficulty/combinatorial_formula/block_nested_rounding_allocate_then_round
        """
        scenario = setup_three_way_allocation_scenario(allocate=True)
        block = refetch_block(scenario["block"]["id"])
        rows = allocation_rows(block["id"])

        assert block["unallocated_share_micros"] == 0
        by_rank = {row["allocation_rank"]: row for row in rows}
        assert by_rank[1]["allocated_cost_cents"] == 1_744_088
        assert by_rank[3]["allocated_cost_cents"] == 1_749_325
        assert sum(row["allocated_cost_cents"] for row in rows) == 5_237_501
        assert all(row["allocation_status"] == "ALLOCATED" for row in rows)

    def test_average_price_recovers_the_rounded_share_split(self):
        """PRD §3.4: "Fifth, each allocation's `average_price_micros` is its allocated
        cost multiplied by ten billion and divided by its share quantity, rounded
        half up to whole micros."

        Design: Difficulty/combinatorial_formula/block_nested_rounding_allocate_then_round
        """
        scenario = setup_three_way_allocation_scenario(allocate=True)
        rows = allocation_rows(scenario["block"]["id"])
        by_rank = {row["allocation_rank"]: row for row in rows}
        assert by_rank[1]["average_price_micros"] == 52_375_015
        assert by_rank[3]["average_price_micros"] == 52_375_000
        assert by_rank[1]["share_micros"] == 333_000_000


class TestCompensatingExecutionCredit:

    def test_settlement_credits_the_drift_to_the_highest_cost_allocation(self):
        """PRD §3.4: "If the allocated total exceeds the block notional, the positive
        drift is distributed back as execution credits of one cent at a time, in
        descending `allocated_cost_cents` order with ascending `allocation_rank`
        breaking ties, with each credited allocation's `fee_rebate_cents` increased,
        its `allocation_status` set to `REBATED`, and its `average_price_micros`
        recomputed after the credit."
        PRD §3.4: "The invariant the platform guarantees afterwards is that the sum
        of allocated costs minus the sum of the rebates equals the block notional
        exactly."

        Design: Difficulty/compensating_invariant/block_cost_basis_conservation_via_execution_credit
        """
        scenario = setup_three_way_allocation_scenario(allocate=True)
        block = refetch_block(scenario["block"]["id"])
        rows = allocation_rows(block["id"])
        assert sum(row["allocated_cost_cents"] for row in rows) == 5_237_501

        validate_success(api_client.settle_block_order(block["id"], {}, CUSTODY, row=block), 200)
        settled = refetch_block(block["id"])
        assert settled["block_status"] == "SETTLED"

        rows = allocation_rows(block["id"])
        assert all(row["allocation_status"] == "SETTLED" for row in rows)
        rebates = sum(row.get("fee_rebate_cents") or 0 for row in rows)
        assert rebates == 1
        allocated = sum(row["allocated_cost_cents"] for row in rows)
        assert allocated - rebates == 5_237_500

    def test_the_credited_allocation_is_the_largest_one(self):
        """PRD §3.4: "the positive drift is distributed back as execution credits of
        one cent at a time, in descending `allocated_cost_cents` order with ascending
        `allocation_rank` breaking ties".
        PRD §3.4: "its `average_price_micros` is recomputed after the credit".

        Design: Difficulty/compensating_invariant/block_cost_basis_conservation_via_execution_credit
        """
        scenario = setup_three_way_allocation_scenario(allocate=True)
        block = refetch_block(scenario["block"]["id"])
        validate_success(api_client.settle_block_order(block["id"], {}, CUSTODY, row=block), 200)

        rows = {row["allocation_rank"]: row for row in allocation_rows(block["id"])}
        assert rows[3]["fee_rebate_cents"] == 1, "the largest allocation must absorb the single cent"
        assert rows[1]["fee_rebate_cents"] in (0, None)
        assert rows[3]["average_price_micros"] == 52_374_970


class TestAllocationBoundaries:

    def test_zero_executed_quantity_is_refused_before_allocation(self):
        """PRD §3.4: "A block whose executed quantity is zero never reaches
        allocation at all."
        PRD §3.4: "it must find at least one allocation targeting an `OPEN` account
        with a non-zero executed quantity, failing which it is refused with
        `ERR_NO_ELIGIBLE_ALLOCATION_TARGET` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/empty_allocation_and_zero_execution_boundaries
        """
        scenario = setup_zero_execution_block()
        block = scenario["zero_block"]
        res = api_client.allocate_block_order(
            block["id"], {"expected_block_order_version": block["version"]}, ADVISOR, row=block)
        validate_error(res, "ERR_NO_ELIGIBLE_ALLOCATION_TARGET", expected_status=409)

        unchanged = refetch_block(block["id"])
        assert unchanged["block_status"] == "EXECUTED"
        assert all(row["allocation_status"] == "PENDING"
                   for row in allocation_rows(block["id"]))

    def test_block_whose_every_target_is_frozen_goes_unallocated(self):
        """PRD §3.4: "allocations targeting an account that is not `OPEN` are
        excluded from this sum and receive no shares at all, keeping
        `allocation_status` `PENDING` and `share_micros` null."
        PRD §3.4: "The block's `unallocated_share_micros` is the executed total minus
        the shares actually assigned, and the block becomes `ALLOCATED` when that
        residual is zero and `UNALLOCATED` otherwise."

        Design: Difficulty/boundary_precision_check/empty_allocation_and_zero_execution_boundaries
        """
        scenario = setup_zero_execution_block()
        block = scenario["frozen_block"]
        validate_success(api_client.allocate_block_order(
            block["id"], {"expected_block_order_version": block["version"]}, ADVISOR, row=block), 200)

        updated = refetch_block(block["id"])
        assert updated["block_status"] == "UNALLOCATED"
        assert updated["unallocated_share_micros"] == 500_000_000

        rows = allocation_rows(block["id"])
        assert len(rows) == 2
        assert all(row["share_micros"] is None for row in rows)
        assert all(row["allocation_status"] == "PENDING" for row in rows)


class TestAllocationRankTieBreak:

    def test_residual_micro_share_follows_the_lower_allocation_rank(self):
        """PRD §3.4: "Third, the residual — the executed total minus the sum of the
        base quantities — is handed out one micro-share at a time in descending
        remainder order, ties broken by ascending `allocation_rank`."
        PRD §3.4: "a client-supplied `allocation_rank` that is unique within the
        block and serves as the deterministic tie-break for leftover shares — lower
        rank wins".

        Design: Corner/calculations/block_allocation_residual_uses_allocation_rank_tie_break
        """
        firm, agreement, household, accounts, model = setup_block_model_scenario()
        block = setup_executed_block(
            firm["id"], model["id"],
            allocations=[
                (accounts[0]["id"], 500_000_000, 1),
                (accounts[1]["id"], 300_000_000, 2),
                (accounts[2]["id"], 300_000_000, 3),
            ],
            executed_share_micros=999_000_000,
            allocate=True,
        )
        rows = {row["allocation_rank"]: row for row in allocation_rows(block["id"])}
        assert rows[1]["share_micros"] == 454_090_909
        assert rows[2]["share_micros"] == 272_454_546
        assert rows[3]["share_micros"] == 272_454_545
        assert sum(row["share_micros"] for row in rows.values()) == 999_000_000
        assert refetch_block(block["id"])["unallocated_share_micros"] == 0


class TestUnallocatedRevert:

    def test_unfreezing_restores_the_block_and_allows_a_second_allocation(self):
        """PRD §3.3: "Unfreezing an account is what makes an `UNALLOCATED` block
        recoverable, because the previously excluded accounts become eligible again."

        Design: Corner/state_machines/block_order_unallocated_revert_after_account_unfreeze
        """
        scenario = setup_account_with_frozen_block()
        block = scenario["block"]
        validate_success(api_client.allocate_block_order(
            block["id"], {"expected_block_order_version": block["version"]}, ADVISOR, row=block), 200)
        unallocated = refetch_block(block["id"])
        assert unallocated["block_status"] == "UNALLOCATED"
        assert unallocated["unallocated_share_micros"] == 500_000_000

        for account in scenario["accounts"]:
            validate_success(api_client.unfreeze_account(account["id"], {}, TEST_USERS["compliance_headers"], row=account), 200)

        current = refetch_block(block["id"])
        validate_success(api_client.allocate_block_order(
            block["id"], {"expected_block_order_version": current["version"]}, ADVISOR, row=current), 200)
        recovered = refetch_block(block["id"])
        assert recovered["block_status"] == "ALLOCATED"
        assert recovered["unallocated_share_micros"] == 0

        rows = allocation_rows(block["id"])
        assert all(row["share_micros"] == 250_000_000 for row in rows)
        assert all(row["allocation_status"] == "ALLOCATED" for row in rows)