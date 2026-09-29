"""Freight loads: the two allocation bases, the rounding residual, the yard-slot
aggregate, the dispatch gates and the detach reconciliation."""

import pytest
from test_helpers import (
    LOGISTICS,
    assert_detached_order,
    assert_empty_load_totals,
    assert_freight_allocation_invariant,
    assert_version_advanced_by,
    assign_order_to_load_payload,
    attach_order,
    cancel_load,
    cancel_order,
    create_design,
    create_design_under_review,
    create_freight_load_payload,
    deliver_load,
    dispatch_load,
    order_payment_payload,
    place_order,
    place_queued_paid_order,
    plan_freight_load,
    read_dealer,
    read_load,
    read_order,
    setup_dense_and_bulky_orders,
    setup_high_cube_utilization_pair,
    setup_partially_paid_load,
    setup_reference_data,
    setup_yard_window_anchor,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAllocationBasisDivergence:
    def test_the_weight_basis_splits_one_flatbed_by_kilograms(self, api):
        """PRD §3.8: "Trailer geometry is fixed by type. A `FLATBED` carries `max_cube_m3` 62.0 and
        `max_weight_kg` 21000; a `HIGH_CUBE_VAN` carries 95.0 and 28000; a `STEP_DECK` carries 74.0
        and 22500."
        PRD §3.8: "The load's `assigned_cube_m3` is the sum of the attached orders' `kit_cube_m3`
        rounded half up to 3 decimal places, and its `assigned_weight_kg` is the sum of their
        `kit_weight_kg` rounded half up to 2 decimal places."
        PRD §3.8: "The `linehaul_cost_cents` is the trailer's base linehaul — 145000 cents for a
        `FLATBED`, 198000 for a `HIGH_CUBE_VAN`, 172000 for a `STEP_DECK` — plus 3 cents for each
        kilogram of `assigned_weight_kg`, that per-kilogram term being rounded half up to whole cents
        before it is added."
        PRD §3.8: "Under `WEIGHT`, an order's share is the `linehaul_cost_cents` multiplied by that
        order's `kit_weight_kg` and divided by the load's `assigned_weight_kg`, rounded half up to
        whole cents."
        PRD §3.8: "The attached orders are ordered by `created_at` ascending and their
        `freight_sequence` values are renumbered 1 through N in that order; entity identifiers are
        never consulted for ordering."

        Design: Difficulty/dual_variant_calc/freight_allocation_weight_vs_cube_basis_diverges_for_same_two_orders
        """
        env = setup_dense_and_bulky_orders()
        ref, dense, bulky = env["ref"], env["dense_order"], env["bulky_order"]
        assert dense["kit_weight_kg"] == pytest.approx(6410.4, abs=0.005)
        assert dense["kit_cube_m3"] == pytest.approx(18.45, abs=0.0005)
        assert bulky["kit_weight_kg"] == pytest.approx(9401.4, abs=0.005)
        assert bulky["kit_cube_m3"] == pytest.approx(37.129, abs=0.0005)

        load = plan_freight_load(
            ref,
            trailer_type="FLATBED",
            allocation_basis="WEIGHT",
            yard_window_start="2026-09-10T00:00:00Z",
            yard_window_end="2026-09-12T00:00:00Z",
        )
        assert load["max_cube_m3"] == pytest.approx(62.0, abs=0.0005)
        assert load["max_weight_kg"] == pytest.approx(21000, abs=0.005)
        attach_order(load, dense)
        load = attach_order(load, bulky)

        assert load["order_count"] == 2
        assert load["assigned_weight_kg"] == pytest.approx(15811.8, abs=0.005)
        assert load["assigned_cube_m3"] == pytest.approx(55.579, abs=0.0005)
        # 55.579 / 62.0 * 100 = 89.6435..., stored at 2 decimals.
        assert load["cube_utilization_pct"] == pytest.approx(89.64, abs=0.005)
        # 145000 + round_half_up(15811.8 * 3) = 145000 + 47435.
        assert load["linehaul_cost_cents"] == 192435

        dense_row, bulky_row = read_order(dense["id"]), read_order(bulky["id"])
        assert dense_row["freight_sequence"] == 1
        assert bulky_row["freight_sequence"] == 2
        assert dense_row["freight_load_id"] == load["id"]
        assert bulky_row["freight_load_id"] == load["id"]
        # 192435 * 6410.4 / 15811.8 and 192435 * 9401.4 / 15811.8.
        assert dense_row["allocated_freight_cents"] == 78017
        assert bulky_row["allocated_freight_cents"] == 114418
        assert_freight_allocation_invariant(load, [dense_row, bulky_row])

    def test_the_cube_basis_moves_the_same_linehaul_toward_the_bulky_kit(self, api):
        """PRD §3.8: "Under `CUBE`, the share is the `linehaul_cost_cents` multiplied by that order's
        `kit_cube_m3` and divided by the load's `assigned_cube_m3`, rounded half up to whole cents."
        PRD §3.8: "The two bases diverge whenever the orders' weight-to-cube densities differ — a
        bare sheet kit is dense while a kit carrying fans and a power sweep is bulky — and the choice
        is a commercial one the coordinator makes per load."
        PRD §3.8: "The invariant is exact: the sum of `allocated_freight_cents` over the attached
        orders equals the `linehaul_cost_cents` to the cent."
        PRD §3.8: "A detached order carries `allocated_freight_cents` 0 and `freight_sequence` null."

        Design: Difficulty/dual_variant_calc/freight_allocation_weight_vs_cube_basis_diverges_for_same_two_orders
        """
        env = setup_dense_and_bulky_orders()
        ref, dense, bulky = env["ref"], env["dense_order"], env["bulky_order"]
        weight_load = plan_freight_load(
            ref,
            trailer_type="FLATBED",
            allocation_basis="WEIGHT",
            yard_window_start="2026-09-10T00:00:00Z",
            yard_window_end="2026-09-12T00:00:00Z",
        )
        attach_order(weight_load, dense)
        weight_load = attach_order(weight_load, bulky)
        weight_shares = (
            read_order(dense["id"])["allocated_freight_cents"],
            read_order(bulky["id"])["allocated_freight_cents"],
        )
        assert weight_shares == (78017, 114418)

        cancelled = cancel_load(weight_load)
        assert cancelled["status"] == "CANCELLED"
        assert_detached_order(read_order(dense["id"]))
        assert_detached_order(read_order(bulky["id"]))

        cube_load = plan_freight_load(
            ref,
            trailer_type="FLATBED",
            allocation_basis="CUBE",
            yard_window_start="2026-09-10T00:00:00Z",
            yard_window_end="2026-09-12T00:00:00Z",
        )
        attach_order(cube_load, dense)
        cube_load = attach_order(cube_load, bulky)

        # Identical trailer, identical kits, identical linehaul: the basis is the
        # only variable in play.
        assert cube_load["linehaul_cost_cents"] == 192435
        assert cube_load["assigned_cube_m3"] == pytest.approx(55.579, abs=0.0005)
        assert cube_load["assigned_weight_kg"] == pytest.approx(15811.8, abs=0.005)

        dense_row, bulky_row = read_order(dense["id"]), read_order(bulky["id"])
        assert dense_row["allocated_freight_cents"] == 63881
        assert bulky_row["allocated_freight_cents"] == 128554
        # The switch moves exactly 14136 cents from the bulky kit to the dense one.
        assert weight_shares[0] - dense_row["allocated_freight_cents"] == 14136
        assert bulky_row["allocated_freight_cents"] - weight_shares[1] == 14136
        assert_freight_allocation_invariant(cube_load, [dense_row, bulky_row])


class TestHighCubeUtilizationFloor:
    def test_a_van_one_hundredth_of_a_percent_short_of_the_floor_cannot_dispatch(
        self, api
    ):
        """PRD §3.8: "The high-cube utilization floor applies **only** to a `HIGH_CUBE_VAN`, whose
        `cube_utilization_pct` must be at least 75.00 percent; a van below that floor is refused with
        `ERR_LOAD_BELOW_MIN_CUBE_UTILIZATION`, while `FLATBED` and `STEP_DECK` loads are entirely
        exempt and may dispatch at any utilization."
        PRD §3.8: "The `cube_utilization_pct` is the `assigned_cube_m3` divided by the `max_cube_m3`,
        multiplied by 100, rounded half up to 2 decimal places."
        PRD §2.11: "30. High-cube utilization floor, on dispatch —
        `ERR_LOAD_BELOW_MIN_CUBE_UTILIZATION`, 409."
        PRD §3.8: "On success the load becomes `DISPATCHED`, every attached order advances its
        `production_status` to `SHIPPED`, and the dealership's `staged_kit_count` is recomputed
        because the load has left the planned set and freed its yard slot."

        Design: Difficulty/boundary_precision_check/high_cube_load_dispatches_at_exactly_75_00_pct_utilization_and_rejects_at_74_99
        """
        env = setup_high_cube_utilization_pair()
        load = read_load(env["under_load"]["id"])
        assert load["max_cube_m3"] == pytest.approx(95.0, abs=0.0005)
        assert load["order_count"] == 3
        assert load["assigned_cube_m3"] == pytest.approx(71.244, abs=0.0005)
        assert load["assigned_weight_kg"] == pytest.approx(24783.0, abs=0.005)
        # 71.244 / 95.0 * 100 = 74.99368, which stores as 74.99.
        assert load["cube_utilization_pct"] == pytest.approx(74.99, abs=0.005)
        # 198000 + round_half_up(24783.0 * 3) = 198000 + 74349.
        assert load["linehaul_cost_cents"] == 272349

        rows = [read_order(o["id"]) for o in env["under_orders"]]
        assert [r["freight_sequence"] for r in rows] == [1, 2, 3]
        assert [r["allocated_freight_cents"] for r in rows] == [90783, 90783, 90783]
        assert_freight_allocation_invariant(load, rows)
        assert all(r["financial_status"] == "DEPOSIT_PAID" for r in rows)
        assert all(r["production_status"] == "QUEUED" for r in rows)

        rejected = api.dispatch_freight_load(load["id"], LOGISTICS)
        validate_error(rejected, "ERR_LOAD_BELOW_MIN_CUBE_UTILIZATION", 409)
        assert read_load(load["id"])["status"] == "PLANNED"
        # A rejected dispatch ships nothing.
        assert all(
            read_order(o["id"])["production_status"] == "QUEUED"
            for o in env["under_orders"]
        )

    def test_a_van_exactly_on_the_floor_dispatches_and_the_residual_lands_on_sequence_one(
        self, api
    ):
        """PRD §3.8: "The high-cube utilization floor applies **only** to a `HIGH_CUBE_VAN`, whose
        `cube_utilization_pct` must be at least 75.00 percent; a van below that floor is refused with
        `ERR_LOAD_BELOW_MIN_CUBE_UTILIZATION`, while `FLATBED` and `STEP_DECK` loads are entirely
        exempt and may dispatch at any utilization."
        PRD §3.8: "The residual, computed as the `linehaul_cost_cents` minus the sum of all the
        rounded shares, is added in its entirety to the single order whose `freight_sequence` is 1 —
        the earliest-created attached order."
        PRD §3.8: "On success the load becomes `DISPATCHED`, every attached order advances its
        `production_status` to `SHIPPED`, and the dealership's `staged_kit_count` is recomputed
        because the load has left the planned set and freed its yard slot."
        PRD §3.8: "The dealership's `staged_kit_count` mirrors this population directly: it is the
        count of that dealership's loads whose `status` is `PLANNED`, and it is recomputed whenever a
        load enters or leaves that set, bumping the dealership's `version` by 1."

        Design: Difficulty/boundary_precision_check/high_cube_load_dispatches_at_exactly_75_00_pct_utilization_and_rejects_at_74_99
        """
        env = setup_high_cube_utilization_pair()
        load = read_load(env["exact_load"]["id"])
        assert load["order_count"] == 3
        assert load["assigned_cube_m3"] == pytest.approx(71.25, abs=0.0005)
        assert load["assigned_weight_kg"] == pytest.approx(20611.2, abs=0.005)
        # 71.25 / 95.0 * 100 is exactly 75.0 and the floor is inclusive.
        assert load["cube_utilization_pct"] == pytest.approx(75.0, abs=0.005)
        # 198000 + round_half_up(20611.2 * 3) = 198000 + 61834.
        assert load["linehaul_cost_cents"] == 259834

        rows = [read_order(o["id"]) for o in env["exact_orders"]]
        assert [r["freight_sequence"] for r in rows] == [1, 2, 3]
        # Each raw CUBE share rounds to 86611, so the residual is +1.
        assert [r["allocated_freight_cents"] for r in rows] == [86612, 86611, 86611]
        assert_freight_allocation_invariant(load, rows)

        before = read_dealer(env["ref"]["alpha"]["id"])
        assert before["staged_kit_count"] == 2
        dispatched = dispatch_load(load)
        assert dispatched["status"] == "DISPATCHED"
        shipped = [read_order(o["id"]) for o in env["exact_orders"]]
        assert all(r["production_status"] == "SHIPPED" for r in shipped)
        # The shares survive the transition untouched.
        assert [r["allocated_freight_cents"] for r in shipped] == [86612, 86611, 86611]

        after = read_dealer(env["ref"]["alpha"]["id"])
        # Only the still-planned under-utilized van holds a slot now.
        assert after["staged_kit_count"] == 1
        assert_version_advanced_by(after, before, 1, "dealer")
        assert read_load(env["under_load"]["id"])["status"] == "PLANNED"


class TestDispatchWaitsOnEveryDeposit:
    def test_one_unpaid_order_out_of_two_blocks_the_whole_trailer(self, api):
        """PRD §3.8: "Every attached order must have `financial_status` `DEPOSIT_PAID`; an unpaid
        order on the trailer is refused with `ERR_DEPOSIT_REQUIRED` and HTTP 402."
        PRD §2.11: "35. Deposit presence on every attached order, on dispatch —
        `ERR_DEPOSIT_REQUIRED`, 402."
        PRD §3.8: "The high-cube utilization floor applies **only** to a `HIGH_CUBE_VAN`, whose
        `cube_utilization_pct` must be at least 75.00 percent; a van below that floor is refused with
        `ERR_LOAD_BELOW_MIN_CUBE_UTILIZATION`, while `FLATBED` and `STEP_DECK` loads are entirely
        exempt and may dispatch at any utilization."
        PRD §3.8: "The `linehaul_cost_cents` is the trailer's base linehaul — 145000 cents for a
        `FLATBED`, 198000 for a `HIGH_CUBE_VAN`, 172000 for a `STEP_DECK` — plus 3 cents for each
        kilogram of `assigned_weight_kg`, that per-kilogram term being rounded half up to whole cents
        before it is added."

        Design: Difficulty/cross_entity_state_dependency/freight_load_dispatch_blocked_until_every_attached_dealer_order_is_deposit_paid
        """
        env = setup_partially_paid_load()
        load = read_load(env["load"]["id"])
        assert load["order_count"] == 2
        assert load["assigned_weight_kg"] == pytest.approx(12820.8, abs=0.005)
        assert load["assigned_cube_m3"] == pytest.approx(36.9, abs=0.0005)
        assert load["cube_utilization_pct"] == pytest.approx(59.52, abs=0.005)
        # 145000 + round_half_up(12820.8 * 3) = 145000 + 38462.
        assert load["linehaul_cost_cents"] == 183462

        paid, unpaid = read_order(env["paid"]["id"]), read_order(env["unpaid"]["id"])
        assert paid["financial_status"] == "DEPOSIT_PAID"
        assert unpaid["financial_status"] == "AWAITING_DEPOSIT"
        assert paid["production_status"] == "QUEUED"
        assert unpaid["production_status"] == "QUEUED"

        rejected = api.dispatch_freight_load(load["id"], LOGISTICS)
        validate_error(rejected, "ERR_DEPOSIT_REQUIRED", 402)
        assert read_load(load["id"])["status"] == "PLANNED"
        assert read_order(paid["id"])["production_status"] == "QUEUED"
        assert read_order(unpaid["id"])["production_status"] == "QUEUED"
        # 59.52 pct is far under the high-cube floor, yet no utilization error is
        # raised: this is a FLATBED and the floor is conditional on the trailer.

    def test_paying_the_missing_deposit_elsewhere_unblocks_the_same_load_untouched(
        self, api
    ):
        """PRD §3.8: "Every attached order must have `financial_status` `DEPOSIT_PAID`; an unpaid
        order on the trailer is refused with `ERR_DEPOSIT_REQUIRED` and HTTP 402."
        PRD §3.8: "On success the load becomes `DISPATCHED`, every attached order advances its
        `production_status` to `SHIPPED`, and the dealership's `staged_kit_count` is recomputed
        because the load has left the planned set and freed its yard slot."
        PRD §3.8: "Under `WEIGHT`, an order's share is the `linehaul_cost_cents` multiplied by that
        order's `kit_weight_kg` and divided by the load's `assigned_weight_kg`, rounded half up to
        whole cents."
        PRD §3.6: "The production dimension is untouched, which means a `DRAFT` order may
        legitimately pay its deposit before it is ever confirmed."

        Design: Difficulty/cross_entity_state_dependency/freight_load_dispatch_blocked_until_every_attached_dealer_order_is_deposit_paid
        """
        env = setup_partially_paid_load()
        ref, load = env["ref"], read_load(env["load"]["id"])
        unpaid = read_order(env["unpaid"]["id"])
        assert unpaid["required_deposit_cents"] == 499933
        validate_error(
            api.dispatch_freight_load(load["id"], LOGISTICS), "ERR_DEPOSIT_REQUIRED", 402
        )

        settled = validate_success(
            api.post_order_payment(
                unpaid["id"], order_payment_payload(499933), ref["alpha_headers"]
            )
        )
        assert settled["financial_status"] == "DEPOSIT_PAID"
        assert settled["production_status"] == "QUEUED"
        # The payment endpoint never mentions the load and changes nothing on it.
        unchanged = read_load(load["id"])
        assert unchanged["version"] == load["version"]
        assert unchanged["linehaul_cost_cents"] == 183462
        assert unchanged["order_count"] == 2

        dispatched = dispatch_load(load)
        assert dispatched["status"] == "DISPATCHED"
        rows = [read_order(env["paid"]["id"]), read_order(env["unpaid"]["id"])]
        assert all(r["production_status"] == "SHIPPED" for r in rows)
        # Identical kits and an even linehaul leave no residual to place.
        assert [r["allocated_freight_cents"] for r in rows] == [91731, 91731]
        assert_freight_allocation_invariant(dispatched, rows)
        assert read_dealer(ref["alpha"]["id"])["staged_kit_count"] == 0


class TestYardStagingSlotsAreAnAggregate:
    def test_one_touching_overlap_is_legal_and_the_third_occupant_exhausts_the_yard(
        self, api
    ):
        """PRD §3.8: "**Yard windows are closed intervals** — both endpoints belong to the interval,
        so two windows that merely touch at an instant do intersect."
        PRD §3.8: "Staging capacity is an aggregate over that overlap: the plant counts the
        dealership's loads in `PLANNED` whose closed yard window intersects the new load's closed
        window, and refuses the plan with `ERR_YARD_SLOTS_EXHAUSTED` when that count has already
        reached the dealership's `staging_slots`."
        PRD §3.8: "A single overlap is perfectly legal while slots remain; the rule bites only at the
        declared capacity."
        PRD §2.11: "22. Dealer-yard staging slot capacity, on freight load planning —
        `ERR_YARD_SLOTS_EXHAUSTED`, 409."

        Design: Difficulty/resource_temporal_overlap/dealer_yard_staging_slots_use_closed_intervals_and_aggregate_capacity_so_one_overlap_is_legal
        """
        env = setup_yard_window_anchor()
        ref, first = env["ref"], env["load"]
        dealer_id = ref["alpha"]["id"]
        assert read_dealer(dealer_id)["staging_slots"] == 2
        assert first["status"] == "PLANNED"
        assert first["order_count"] == 0

        def plan(start, end, version=None):
            if version is None:
                version = read_dealer(dealer_id)["version"]
            return api.create_freight_load(
                create_freight_load_payload(
                    dealer_id, version, yard_window_start=start, yard_window_end=end
                ),
                LOGISTICS,
            )

        # Starts at the exact instant the first window ends. Closed intervals make
        # them intersect, but one intersecting load is still under two slots.
        second = validate_success(
            plan("2026-09-12T00:00:00Z", "2026-09-14T00:00:00Z"), 201
        )
        assert second["status"] == "PLANNED"
        assert read_dealer(dealer_id)["staged_kit_count"] == 2

        # This window intersects both existing loads, so the count is already 2.
        validate_error(
            plan("2026-09-11T00:00:00Z", "2026-09-13T00:00:00Z"),
            "ERR_YARD_SLOTS_EXHAUSTED",
            409,
        )
        assert read_dealer(dealer_id)["staged_kit_count"] == 2

    def test_a_disjoint_window_still_plans_and_the_refused_plan_left_no_trace(self, api):
        """PRD §3.8: "Staging capacity is an aggregate over that overlap: the plant counts the
        dealership's loads in `PLANNED` whose closed yard window intersects the new load's closed
        window, and refuses the plan with `ERR_YARD_SLOTS_EXHAUSTED` when that count has already
        reached the dealership's `staging_slots`."
        PRD §3.8: "The dealership's `staged_kit_count` mirrors this population directly: it is the
        count of that dealership's loads whose `status` is `PLANNED`, and it is recomputed whenever a
        load enters or leaves that set, bumping the dealership's `version` by 1."
        PRD §3.8: "A `LogisticsCoordinator` plans a load onto a dealer yard by naming the destination
        with `dealer_id`, choosing a `trailer_type` of `FLATBED`, `HIGH_CUBE_VAN` or `STEP_DECK`,
        choosing an `allocation_basis` of `WEIGHT` or `CUBE`, bounding the yard staging window with
        `yard_window_start` and `yard_window_end`, and presenting `expected_dealer_version`."
        PRD §3.8: "Loads may be listed and narrowed by `dealer_id`."

        Design: Difficulty/resource_temporal_overlap/dealer_yard_staging_slots_use_closed_intervals_and_aggregate_capacity_so_one_overlap_is_legal
        """
        env = setup_yard_window_anchor()
        ref = env["ref"]
        dealer_id = ref["alpha"]["id"]

        def plan(start, end, version):
            return api.create_freight_load(
                create_freight_load_payload(
                    dealer_id, version, yard_window_start=start, yard_window_end=end
                ),
                LOGISTICS,
            )

        validate_success(
            plan(
                "2026-09-12T00:00:00Z",
                "2026-09-14T00:00:00Z",
                read_dealer(dealer_id)["version"],
            ),
            201,
        )
        held = read_dealer(dealer_id)
        validate_error(
            plan("2026-09-11T00:00:00Z", "2026-09-13T00:00:00Z", held["version"]),
            "ERR_YARD_SLOTS_EXHAUSTED",
            409,
        )
        # The refused plan neither wrote a row nor bumped the guarded version, so
        # the very same expected_dealer_version is still current.
        assert read_dealer(dealer_id)["version"] == held["version"]

        third = validate_success(
            plan("2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z", held["version"]), 201
        )
        assert third["status"] == "PLANNED"
        final = read_dealer(dealer_id)
        assert final["staged_kit_count"] == 3
        assert_version_advanced_by(final, held, 1, "dealer")

        rows, meta = validate_paginated(
            api.list_freight_loads(
                LOGISTICS, {"dealer_id": dealer_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3
        assert all(row["status"] == "PLANNED" for row in rows)


class TestRoundingResidual:
    def test_a_negative_residual_is_charged_in_full_to_the_earliest_created_order(
        self, api
    ):
        """PRD §3.8: "Because each share is rounded independently, the shares generally do not re-sum
        to the linehaul."
        PRD §3.8: "The residual, computed as the `linehaul_cost_cents` minus the sum of all the
        rounded shares, is added in its entirety to the single order whose `freight_sequence` is 1 —
        the earliest-created attached order."
        PRD §3.8: "The residual may be negative and is applied with its sign."
        PRD §3.8: "Each order's `allocated_freight_cents` is its own rounded share, plus that residual
        for `freight_sequence` 1 only."
        PRD §3.8: "The invariant is exact: the sum of `allocated_freight_cents` over the attached
        orders equals the `linehaul_cost_cents` to the cent."

        Design: Corner/calculations/freight_rounding_residual_is_absorbed_by_the_first_assigned_order
        """
        ref = setup_reference_data()
        design = create_design(ref)
        orders = [place_order(ref, design) for _ in range(3)]
        assert all(o["kit_weight_kg"] == pytest.approx(6410.4, abs=0.005) for o in orders)

        load = plan_freight_load(
            ref,
            trailer_type="STEP_DECK",
            allocation_basis="WEIGHT",
            yard_window_start="2026-09-10T00:00:00Z",
            yard_window_end="2026-09-12T00:00:00Z",
        )
        assert load["max_cube_m3"] == pytest.approx(74.0, abs=0.0005)
        assert load["max_weight_kg"] == pytest.approx(22500, abs=0.005)

        # One order alone absorbs the whole linehaul: 172000 + round(6410.4 * 3).
        single = attach_order(load, orders[0])
        assert single["linehaul_cost_cents"] == 191231
        assert read_order(orders[0]["id"])["allocated_freight_cents"] == 191231

        attach_order(load, orders[1])
        load = attach_order(load, orders[2])
        assert load["order_count"] == 3
        assert load["assigned_weight_kg"] == pytest.approx(19231.2, abs=0.005)
        assert load["assigned_cube_m3"] == pytest.approx(55.35, abs=0.0005)
        # 74.8 pct is under the high-cube floor but a STEP_DECK is exempt.
        assert load["cube_utilization_pct"] == pytest.approx(74.8, abs=0.005)
        # 172000 + round_half_up(19231.2 * 3) = 172000 + 57694.
        assert load["linehaul_cost_cents"] == 229694

        rows = [read_order(o["id"]) for o in orders]
        assert [r["freight_sequence"] for r in rows] == [1, 2, 3]
        # Each raw share rounds to 76565, so three of them overshoot by one cent
        # and the residual of -1 lands entirely on freight_sequence 1.
        assert [r["allocated_freight_cents"] for r in rows] == [76564, 76565, 76565]
        assert sum(r["allocated_freight_cents"] for r in rows) == 229694
        assert_freight_allocation_invariant(load, rows)


class TestPlanningAndAssignmentGates:
    def test_five_freight_gates_each_reject_their_own_defect(self, api):
        """PRD §3.8: "A `HIGH_CUBE_VAN` may be planned only for a dealership whose `high_cube_access`
        is true; planning one for a yard that cannot receive it is refused with
        `ERR_HIGH_CUBE_ACCESS_DENIED`."
        PRD §3.8: "The order's `dealer_id` must equal the load's `dealer_id`, since a trailer goes to
        exactly one yard; a cross-dealer attachment is refused with `ERR_LOAD_DEALER_MISMATCH`."
        PRD §3.8: "And the order must not already sit on this or any other load — its
        `freight_load_id` must be null — or the attachment is refused with
        `ERR_ORDER_ALREADY_ON_LOAD`."
        PRD §3.8: "After notionally adding the order, the load's `assigned_cube_m3` must remain no
        greater than its `max_cube_m3` and its `assigned_weight_kg` no greater than its
        `max_weight_kg`; an overload is refused with `ERR_LOAD_CAPACITY_EXCEEDED`."
        PRD §3.8: "The load must have at least one attached order; an empty trailer is refused with
        `ERR_LOAD_HAS_NO_ORDERS`."

        Design: Corner/validations/freight_load_planning_and_assignment_gates_each_reject_their_own_defect
        """
        ref = setup_reference_data()
        alpha_design = create_design(ref)
        pinnacle_design = create_design(ref, dealer="pinnacle")
        alpha_orders = [place_order(ref, alpha_design) for _ in range(4)]
        pinnacle_order = place_order(ref, pinnacle_design, dealer="pinnacle")

        pinnacle = read_dealer(ref["pinnacle"]["id"])
        assert pinnacle["high_cube_access"] is False
        validate_error(
            api.create_freight_load(
                create_freight_load_payload(
                    pinnacle["id"], pinnacle["version"], trailer_type="HIGH_CUBE_VAN"
                ),
                LOGISTICS,
            ),
            "ERR_HIGH_CUBE_ACCESS_DENIED",
            422,
        )

        load = plan_freight_load(ref, trailer_type="FLATBED", allocation_basis="WEIGHT")
        assert load["max_weight_kg"] == pytest.approx(21000, abs=0.005)
        assert load["max_cube_m3"] == pytest.approx(62.0, abs=0.0005)
        assert load["order_count"] == 0

        validate_error(
            api.dispatch_freight_load(load["id"], LOGISTICS),
            "ERR_LOAD_HAS_NO_ORDERS",
            409,
        )
        assert read_load(load["id"])["status"] == "PLANNED"

        validate_error(
            api.assign_order_to_load(
                load["id"], assign_order_to_load_payload(pinnacle_order["id"]), LOGISTICS
            ),
            "ERR_LOAD_DEALER_MISMATCH",
            422,
        )

        attached = attach_order(load, alpha_orders[0])
        assert attached["order_count"] == 1
        # Ample room left, so the duplicate is caught by the already-attached gate
        # rather than by capacity.
        validate_error(
            api.assign_order_to_load(
                load["id"], assign_order_to_load_payload(alpha_orders[0]["id"]), LOGISTICS
            ),
            "ERR_ORDER_ALREADY_ON_LOAD",
            409,
        )
        assert read_load(load["id"])["order_count"] == 1

        attach_order(load, alpha_orders[1])
        full = attach_order(load, alpha_orders[2])
        assert full["order_count"] == 3
        assert full["assigned_weight_kg"] == pytest.approx(19231.2, abs=0.005)
        assert full["assigned_cube_m3"] == pytest.approx(55.35, abs=0.0005)

        # A fourth kit would take the FLATBED to 25641.6 kg against 21000 and
        # 73.8 m3 against 62.0 — both limbs breached at once.
        validate_error(
            api.assign_order_to_load(
                load["id"], assign_order_to_load_payload(alpha_orders[3]["id"]), LOGISTICS
            ),
            "ERR_LOAD_CAPACITY_EXCEEDED",
            409,
        )
        unchanged = read_load(load["id"])
        assert unchanged["order_count"] == 3
        assert unchanged["assigned_weight_kg"] == pytest.approx(19231.2, abs=0.005)
        assert unchanged["assigned_cube_m3"] == pytest.approx(55.35, abs=0.0005)
        assert_detached_order(read_order(alpha_orders[3]["id"]))


class TestLoadTransitionsAndTheCreditBoundary:
    def test_only_delivery_releases_credit_and_every_other_edge_is_refused(self, api):
        """PRD §3.8: "When the attached set is empty the load charges nothing: `assigned_cube_m3`,
        `assigned_weight_kg`, `cube_utilization_pct`, `linehaul_cost_cents` and `order_count` are all
        0, and the trailer's base linehaul is explicitly **not** charged to a load carrying nothing."
        PRD §3.8: "Delivery moves the load from `DISPATCHED` to `DELIVERED`, and any other state is
        refused with `ERR_LOAD_STATE_INVALID`."
        PRD §3.8: "Dispatch moves the load from `PLANNED` to `DISPATCHED`, and a load in any other
        state is refused with `ERR_LOAD_STATE_INVALID`."
        PRD §3.8: "Attaching an order to a load requires the load to be in `PLANNED`, and any other
        load state is refused with `ERR_LOAD_STATE_INVALID`."
        PRD §3.8: "Cancelling a load requires `PLANNED` and is otherwise refused with
        `ERR_LOAD_STATE_INVALID`."
        PRD §3.8: "Delivery is the single point at which a completed sale leaves the credit ledger:
        every attached order advances its `financial_status` from `DEPOSIT_PAID` to `RELEASED` and has
        its `credit_hold_cents` zeroed, after which the dealership's ledger is recomputed and may
        drive that dealership from `CREDIT_HOLD` back to `ACTIVE` — which in turn requeues its held
        orders."

        Design: Corner/endpoints/dispatch_and_delivery_are_the_only_admitted_load_transitions_and_only_delivery_releases_credit
        """
        ref = setup_reference_data()
        design = create_design_under_review(ref)
        order = place_queued_paid_order(ref, design)
        load = plan_freight_load(ref, trailer_type="FLATBED", allocation_basis="WEIGHT")
        assert_empty_load_totals(load)

        validate_error(
            api.deliver_freight_load(load["id"], LOGISTICS), "ERR_LOAD_STATE_INVALID", 409
        )

        load = attach_order(load, order)
        assert load["order_count"] == 1
        assert load["cube_utilization_pct"] == pytest.approx(29.76, abs=0.005)
        assert load["linehaul_cost_cents"] == 164231
        assert read_order(order["id"])["allocated_freight_cents"] == 164231

        dispatched = dispatch_load(load)
        assert dispatched["status"] == "DISPATCHED"
        assert read_dealer(ref["alpha"]["id"])["staged_kit_count"] == 0
        # Dispatch ships steel; it does not release credit.
        shipping = read_dealer(ref["alpha"]["id"])
        assert shipping["credit_committed_cents"] == 1999734
        assert shipping["credit_available_cents"] == 898000266

        validate_error(
            api.dispatch_freight_load(load["id"], LOGISTICS),
            "ERR_LOAD_STATE_INVALID",
            409,
        )
        # The order is genuinely already attached, yet state admissibility outranks
        # the already-attached gate.
        validate_error(
            api.assign_order_to_load(
                load["id"], assign_order_to_load_payload(order["id"]), LOGISTICS
            ),
            "ERR_LOAD_STATE_INVALID",
            409,
        )
        validate_error(
            api.cancel_freight_load(load["id"], LOGISTICS), "ERR_LOAD_STATE_INVALID", 409
        )

        delivered = deliver_load(load)
        assert delivered["status"] == "DELIVERED"
        settled = read_order(order["id"])
        assert settled["production_status"] == "SHIPPED"
        assert settled["financial_status"] == "RELEASED"
        assert settled["credit_hold_cents"] == 0
        assert settled["allocated_freight_cents"] == 164231
        released = read_dealer(ref["alpha"]["id"])
        assert released["credit_committed_cents"] == 0
        assert released["credit_available_cents"] == 900000000
        assert released["status"] == "ACTIVE"

        validate_error(
            api.deliver_freight_load(load["id"], LOGISTICS), "ERR_LOAD_STATE_INVALID", 409
        )


class TestCancellingAPlannedLoad:
    def test_cancelling_a_load_unwinds_its_orders_and_frees_the_single_yard_slot(
        self, api
    ):
        """PRD §3.8: "Cancelling a load requires `PLANNED` and is otherwise refused with
        `ERR_LOAD_STATE_INVALID`."
        PRD §3.8: "It sets `status` to `CANCELLED`, detaches every attached order by zeroing
        `allocated_freight_cents` and nulling both `freight_load_id` and `freight_sequence`, and
        recomputes the dealership's `staged_kit_count` to release the yard slot."
        PRD §3.8: "Staging capacity is an aggregate over that overlap: the plant counts the
        dealership's loads in `PLANNED` whose closed yard window intersects the new load's closed
        window, and refuses the plan with `ERR_YARD_SLOTS_EXHAUSTED` when that count has already
        reached the dealership's `staging_slots`."
        PRD §3.8: "Attaching an order to a load requires the load to be in `PLANNED`, and any other
        load state is refused with `ERR_LOAD_STATE_INVALID`."

        Design: Corner/state_machines/cancelling_a_planned_freight_load_detaches_its_orders_and_releases_the_yard_slot
        """
        ref = setup_reference_data(alpha_staging_slots=1)
        design = create_design(ref)
        first, second = place_order(ref, design), place_order(ref, design)
        load = plan_freight_load(
            ref,
            trailer_type="FLATBED",
            allocation_basis="WEIGHT",
            yard_window_start="2026-08-10T00:00:00Z",
            yard_window_end="2026-08-12T00:00:00Z",
        )
        attach_order(load, first)
        load = attach_order(load, second)
        assert load["order_count"] == 2
        assert load["assigned_weight_kg"] == pytest.approx(12820.8, abs=0.005)
        assert load["assigned_cube_m3"] == pytest.approx(36.9, abs=0.0005)
        assert load["cube_utilization_pct"] == pytest.approx(59.52, abs=0.005)
        assert load["linehaul_cost_cents"] == 183462
        assert read_dealer(ref["alpha"]["id"])["staged_kit_count"] == 1

        def plan_overlapping():
            dealer = read_dealer(ref["alpha"]["id"])
            return api.create_freight_load(
                create_freight_load_payload(
                    dealer["id"],
                    dealer["version"],
                    yard_window_start="2026-08-11T00:00:00Z",
                    yard_window_end="2026-08-13T00:00:00Z",
                ),
                LOGISTICS,
            )

        validate_error(plan_overlapping(), "ERR_YARD_SLOTS_EXHAUSTED", 409)

        cancelled = cancel_load(load)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["order_count"] == 0
        assert_detached_order(read_order(first["id"]))
        assert_detached_order(read_order(second["id"]))
        assert read_dealer(ref["alpha"]["id"])["staged_kit_count"] == 0

        # The slot was genuinely released, not merely marked.
        replacement = validate_success(plan_overlapping(), 201)
        assert replacement["status"] == "PLANNED"

        moved = attach_order(replacement, first)
        assert moved["order_count"] == 1
        assert moved["linehaul_cost_cents"] == 164231
        assert moved["cube_utilization_pct"] == pytest.approx(29.76, abs=0.005)
        first_row = read_order(first["id"])
        assert first_row["allocated_freight_cents"] == 164231
        assert first_row["freight_sequence"] == 1

        validate_error(
            api.assign_order_to_load(
                load["id"], assign_order_to_load_payload(second["id"]), LOGISTICS
            ),
            "ERR_LOAD_STATE_INVALID",
            409,
        )


class TestDetachReconcilesTheWholeLoad:
    def test_each_detach_re_derives_every_total_and_renumbers_from_one(self, api):
        """PRD §3.8: "**The linehaul split** is re-derived from scratch over the whole attached set
        every time the set changes — on attachment, and on every detach reached from order
        cancellation, from an engineering hold, or from load cancellation."
        PRD §3.8: "The attached orders are ordered by `created_at` ascending and their
        `freight_sequence` values are renumbered 1 through N in that order; entity identifiers are
        never consulted for ordering."
        PRD §3.6: "Cancellation sets `production_status` to `CANCELLED` and `financial_status` to
        `VOIDED` as its first hop, zeroes `credit_hold_cents`, and detaches the order from any freight
        load still in `PLANNED` — clearing `freight_load_id`, zeroing `allocated_freight_cents` and
        nulling `freight_sequence` — after which the load's aggregates and per-order freight shares
        are re-derived over the orders that remain."
        PRD §3.6: "A load left with no orders at all cancels itself."
        PRD §3.8: "When the attached set is empty the load charges nothing: `assigned_cube_m3`,
        `assigned_weight_kg`, `cube_utilization_pct`, `linehaul_cost_cents` and `order_count` are all
        0, and the trailer's base linehaul is explicitly **not** charged to a load carrying nothing."

        Design: Corner/complexity_layers/every_detach_reconciles_the_load_totals_and_renumbers_the_surviving_freight_sequence
        """
        ref = setup_reference_data()
        design = create_design(ref)
        first = place_order(ref, design)
        second = place_order(ref, design, aeration_package="AERATION")
        third = place_order(
            ref, design, aeration_package="AERATION", unload_system="SWEEP_AUGER"
        )
        assert first["kit_weight_kg"] == pytest.approx(6410.4, abs=0.005)
        assert second["kit_weight_kg"] == pytest.approx(6530.4, abs=0.005)
        assert third["kit_weight_kg"] == pytest.approx(6870.4, abs=0.005)

        load = plan_freight_load(
            ref,
            trailer_type="STEP_DECK",
            allocation_basis="WEIGHT",
            yard_window_start="2026-09-10T00:00:00Z",
            yard_window_end="2026-09-12T00:00:00Z",
        )
        attach_order(load, first)
        attach_order(load, second)
        load = attach_order(load, third)
        assert load["order_count"] == 3
        assert load["assigned_weight_kg"] == pytest.approx(19811.2, abs=0.005)
        assert load["assigned_cube_m3"] == pytest.approx(62.55, abs=0.0005)
        assert load["cube_utilization_pct"] == pytest.approx(84.53, abs=0.005)
        # 172000 + round_half_up(19811.2 * 3) = 172000 + 59434.
        assert load["linehaul_cost_cents"] == 231434
        rows = [read_order(o["id"]) for o in (first, second, third)]
        assert [r["freight_sequence"] for r in rows] == [1, 2, 3]
        assert [r["allocated_freight_cents"] for r in rows] == [74886, 76288, 80260]
        assert_freight_allocation_invariant(load, rows)

        cancel_order(ref, first)
        gone = read_order(first["id"])
        assert gone["production_status"] == "CANCELLED"
        assert_detached_order(gone)
        two = read_load(load["id"])
        assert two["status"] == "PLANNED"
        assert two["order_count"] == 2
        assert two["assigned_weight_kg"] == pytest.approx(13400.8, abs=0.005)
        assert two["assigned_cube_m3"] == pytest.approx(44.1, abs=0.0005)
        assert two["cube_utilization_pct"] == pytest.approx(59.59, abs=0.005)
        # The linehaul FELL, so the survivors are re-prorated against a smaller
        # total rather than keeping their old shares.
        assert two["linehaul_cost_cents"] == 212202
        survivors = [read_order(second["id"]), read_order(third["id"])]
        assert [r["freight_sequence"] for r in survivors] == [1, 2]
        assert [r["allocated_freight_cents"] for r in survivors] == [103409, 108793]
        assert_freight_allocation_invariant(two, survivors)

        cancel_order(ref, second)
        one = read_load(load["id"])
        assert one["order_count"] == 1
        assert one["assigned_weight_kg"] == pytest.approx(6870.4, abs=0.005)
        assert one["assigned_cube_m3"] == pytest.approx(23.75, abs=0.0005)
        assert one["cube_utilization_pct"] == pytest.approx(32.09, abs=0.005)
        assert one["linehaul_cost_cents"] == 192611
        last = read_order(third["id"])
        assert last["freight_sequence"] == 1
        assert last["allocated_freight_cents"] == 192611

        cancel_order(ref, third)
        empty = read_load(load["id"])
        assert empty["status"] == "CANCELLED"
        assert_empty_load_totals(empty)
        assert_detached_order(read_order(third["id"]))
        assert read_dealer(ref["alpha"]["id"])["staged_kit_count"] == 0
