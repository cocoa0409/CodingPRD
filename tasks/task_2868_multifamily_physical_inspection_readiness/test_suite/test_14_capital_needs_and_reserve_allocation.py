"""Turning closed inspection history into a funded capital plan.

The same three closed inspections yield one recurrence count under the calendar
basis and a smaller one under the inspection basis, and the reserve is then
distributed by flooring every share before walking the leftover cents, so the
per-item cents are what distinguish the pinned evaluation order.
"""

from test_helpers import (
    ApiErrorId,
    assert_allocation_sums_to,
    assert_cents,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_ok,
    assert_total_count,
    assert_two_decimals,
    constants as K,
    factories as F,
    fixtures as X,
    rows_by,
)

BIRCH_UNIT = [
    {"unit_number": "201", "bedroom_count": 2, "occupancy_status": "OCCUPIED"}
]
CAPITAL_DEFINITIONS = ("LT_GAS", "SEV_WINDOW", "SEV_DOOR", "MOD_FLOOR")
OLDEST_FINALIZED_AT = "2024-09-15T00:00:00.000Z"
MIDDLE_FINALIZED_AT = "2025-06-15T00:00:00.000Z"
NEWEST_FINALIZED_AT = "2026-03-15T00:00:00.000Z"
BIRCH_RESERVE_CENTS = 1000000
HALVED_RESERVE_CENTS = 500000
CALENDAR_SHARES = (500001, 333333, 166666)
HALF_UP_FLOOR_SHARE = 166667
INSPECTION_SHARES = (400000, 400000, 200000)


def _birch_row_with_three_closed_inspections(api):
    """Three CLOSED inspections: one citing the window, two citing all three."""
    bundle = X.adopted_standard(api, CAPITAL_DEFINITIONS)
    bundle.update(X.property_with_units(api, K.BIRCH_ROW, BIRCH_UNIT))
    unit_id = bundle["unit_ids"]["201"]
    definition_ids = bundle["definition_ids"]
    X.inject_history(
        api,
        bundle["property_id"],
        bundle["standard_id"],
        OLDEST_FINALIZED_AT,
        [definition_ids["SEV_WINDOW"]],
        unit_id,
    )
    for finalized_at in (MIDDLE_FINALIZED_AT, NEWEST_FINALIZED_AT):
        X.inject_history(
            api,
            bundle["property_id"],
            bundle["standard_id"],
            finalized_at,
            [
                definition_ids["SEV_WINDOW"],
                definition_ids["SEV_DOOR"],
                definition_ids["MOD_FLOOR"],
            ],
            unit_id,
        )
    return bundle


def _first_calendar_generation(api):
    """Generation 1: CALENDAR_SCOPED over all three closed inspections."""
    bundle = _birch_row_with_three_closed_inspections(api)
    bundle["generation_one"] = X.recompute_capital_needs(
        api, bundle["property_id"], "CALENDAR_SCOPED"
    )
    return bundle


def _property_with_a_halved_reserve(api):
    """A property whose reserve was halved after the owner read its version."""
    bundle = X.property_with_units(api, K.BIRCH_ROW, BIRCH_UNIT)
    bundle["stale_version"] = bundle["property"]["version"]
    bundle["patched"] = assert_ok(
        api.patch_property(
            bundle["property_id"],
            F.property_patch_payload(
                capital_reserve_cents=HALVED_RESERVE_CENTS
            ),
            bundle["owner_headers"],
        )
    )
    return bundle


def _active_by_definition(api, property_id):
    """The ACTIVE generation indexed by the definition that drove each item."""
    return rows_by(
        X.active_capital_items(api, property_id), "defect_definition_id"
    )


class TestRecomputingOnAStalePropertyVersion:
    """The reserve moved between the owner's read and the owner's recompute."""

    def test_the_pre_patch_property_version_is_refused(self, api):
        """A recompute always looks legitimate, so only the token can stop it.

        PRD: "Recomputing a property's capital needs requires
        `expected_property_version` to equal the target `Property`'s current
        `version`. A mismatch is rejected with `ERR_STALE_PROPERTY_VERSION` (HTTP
        412), which is what stops a client from superseding a capital-plan
        generation it never saw."

        PRD: "Either the owner or a `PlatformAdmin` may amend a property,
        supplying any subset of `name`, `total_unit_count`, `capital_reserve_cents`
        and `owner_contact_email`; the amendment increments the property's
        `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/capital_recompute_with_the_pre_patch_property_version_is_rejected_as_stale
        """
        bundle = _property_with_a_halved_reserve(api)
        assert_integer(
            bundle["patched"]["version"], bundle["stale_version"] + 1, "version"
        )

        response = api.recompute_capital_needs(
            F.capital_recompute_payload(
                bundle["property_id"], bundle["stale_version"]
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.STALE_PROPERTY_VERSION)
        unchanged = X.read_property(api, bundle["property_id"])
        assert_integer(
            unchanged["version"], bundle["stale_version"] + 1, "version"
        )
        assert_cents(
            unchanged["capital_reserve_cents"],
            HALVED_RESERVE_CENTS,
            "capital_reserve_cents",
        )
        assert_cents(
            unchanged["allocated_reserve_total_cents"],
            0,
            "allocated_reserve_total_cents",
        )
        assert_total_count(
            api.list_capital_needs(X.ADMIN, property_id=bundle["property_id"]), 0
        )
        assert_ok(
            api.recompute_capital_needs(
                F.capital_recompute_payload(
                    bundle["property_id"], unchanged["version"]
                ),
                bundle["owner_headers"],
            )
        )


class TestTheTwoRecurrenceBases:
    """One history, two scopes, two different recurrence counts.

    The calendar basis admits every in-window inspection while the inspection
    basis is hard-capped at the two most recent, so the same defect cannot score
    above 2 on that basis no matter how often it has been cited.
    """

    def test_the_calendar_basis_counts_all_three_closed_inspections(self, api):
        """Three citations of the window defect give 3 and 48.00.

        PRD: "Under `CALENDAR_SCOPED` the scope is every entry of that history
        whose `finalized_at` falls at or after the instant 730 days before the
        current logical clock reading; the lower bound is inclusive"

        PRD: "Its `priority_score` is the `recurrence_count` multiplied by the
        definition's `base_point_value` multiplied by the same severity multiplier
        used for deductions"

        Design: Difficulty/dual_variant_calc/capital_recurrence_inspection_scoped_vs_calendar_scoped_diverge
        """
        bundle = _first_calendar_generation(api)
        definition_ids = bundle["definition_ids"]

        items = _active_by_definition(api, bundle["property_id"])

        window = items[definition_ids["SEV_WINDOW"]]
        assert_fields(window, recurrence_basis="CALENDAR_SCOPED", status="ACTIVE")
        assert_integer(window["recurrence_count"], 3, "recurrence_count")
        assert_two_decimals(window["priority_score"], 48.00, "priority_score")
        door = items[definition_ids["SEV_DOOR"]]
        assert_integer(door["recurrence_count"], 2, "recurrence_count")
        assert_two_decimals(door["priority_score"], 32.00, "priority_score")
        floor = items[definition_ids["MOD_FLOOR"]]
        assert_integer(floor["recurrence_count"], 2, "recurrence_count")
        assert_two_decimals(floor["priority_score"], 16.00, "priority_score")
        assert definition_ids["LT_GAS"] not in items
        assert_instant(window["computed_at"], K.INITIAL_CLOCK, "computed_at")

    def test_the_inspection_basis_is_capped_at_the_two_most_recent(self, api):
        """The oldest citation falls out of scope, taking 3 down to 2.

        PRD: "Under `INSPECTION_SCOPED` the scope is the first 2 entries of that
        ordering, regardless of how old they are - which means a defect appearing
        in three closed inspections can never score a recurrence count above 2 on
        this basis."

        PRD: "`recurrence_count` is the number of **distinct** inspections in the
        scope holding a deficiency whose `defect_definition_id` names that
        definition, whose `source` is `INSPECTION`, and whose `status` is not
        `VOIDED`"

        Design: Difficulty/dual_variant_calc/capital_recurrence_inspection_scoped_vs_calendar_scoped_diverge
        """
        bundle = _first_calendar_generation(api)
        definition_ids = bundle["definition_ids"]
        calendar_window = _active_by_definition(api, bundle["property_id"])[
            definition_ids["SEV_WINDOW"]
        ]

        X.recompute_capital_needs(
            api, bundle["property_id"], "INSPECTION_SCOPED"
        )

        items = _active_by_definition(api, bundle["property_id"])
        window = items[definition_ids["SEV_WINDOW"]]
        assert_fields(
            window, recurrence_basis="INSPECTION_SCOPED", status="ACTIVE"
        )
        assert_integer(window["recurrence_count"], 2, "recurrence_count")
        assert window["recurrence_count"] != calendar_window["recurrence_count"]
        assert_two_decimals(window["priority_score"], 32.00, "priority_score")
        assert window["priority_score"] != calendar_window["priority_score"]
        assert_integer(
            items[definition_ids["SEV_DOOR"]]["recurrence_count"],
            2,
            "recurrence_count",
        )
        assert_two_decimals(
            items[definition_ids["MOD_FLOOR"]]["priority_score"],
            16.00,
            "priority_score",
        )
        retired = X.read_capital_item(api, calendar_window["id"])
        assert_fields(
            retired, status="SUPERSEDED", recurrence_basis="CALENDAR_SCOPED"
        )
        assert_integer(retired["recurrence_count"], 3, "recurrence_count")


class TestTheFloorThenRemainderWalk:
    """Flooring every share first is what puts the leftover cent on rank 1.

    Exact shares of 500000, 333333.33 and 166666.67 sum to the reserve either
    way, so only the per-item cents reveal whether the shares were floored and
    the remainder walked or each share rounded half up on its own.
    """

    def test_the_leftover_cent_lands_on_the_highest_ranked_item(self, api):
        """500001 / 333333 / 166666, never 500000 / 333333 / 166667.

        PRD: "each item's share is the property's `capital_reserve_cents`
        multiplied by that item's `priority_score`, divided by the priority total,
        then **truncated downward** to whole cents. Per-item half-up rounding is
        explicitly wrong here and produces different per-item cents than this
        order."

        PRD: "the leftover - the property's `capital_reserve_cents` minus the sum
        of the floored shares - is handed out one cent at a time, walking the items
        in `allocation_rank` order and wrapping around to rank 1 again if the
        leftover exceeds the number of items, until nothing remains."

        Design: Difficulty/combinatorial_formula/capital_reserve_allocation_floor_then_remainder_walk
        """
        bundle = _first_calendar_generation(api)
        definition_ids = bundle["definition_ids"]

        items = _active_by_definition(api, bundle["property_id"])

        window = items[definition_ids["SEV_WINDOW"]]
        assert_integer(window["allocation_rank"], 1, "allocation_rank")
        assert_cents(
            window["allocated_reserve_cents"],
            CALENDAR_SHARES[0],
            "allocated_reserve_cents",
        )
        door = items[definition_ids["SEV_DOOR"]]
        assert_integer(door["allocation_rank"], 2, "allocation_rank")
        assert_cents(
            door["allocated_reserve_cents"],
            CALENDAR_SHARES[1],
            "allocated_reserve_cents",
        )
        floor = items[definition_ids["MOD_FLOOR"]]
        assert_integer(floor["allocation_rank"], 3, "allocation_rank")
        assert_cents(
            floor["allocated_reserve_cents"],
            CALENDAR_SHARES[2],
            "allocated_reserve_cents",
        )
        assert all(
            row["allocated_reserve_cents"] != HALF_UP_FLOOR_SHARE
            for row in items.values()
        )

    def test_the_ranks_follow_priority_and_the_shares_exhaust_the_reserve(self, api):
        """Ranks 1, 2 and 3 descend by priority and consume all 1000000 cents.

        PRD: "The items of this generation are ordered by `priority_score`
        descending with the definition's `code` ascending as the tie-break, and
        `allocation_rank` is assigned 1 upward in that order."

        PRD: "The invariant this guarantees is exact: the sum of
        `allocated_reserve_cents` across the `ACTIVE` generation equals the
        property's `capital_reserve_cents` precisely."

        Design: Difficulty/combinatorial_formula/capital_reserve_allocation_floor_then_remainder_walk
        """
        bundle = _first_calendar_generation(api)

        active = X.active_capital_items(api, bundle["property_id"])

        by_rank = rows_by(active, "allocation_rank")
        assert sorted(by_rank) == [1, 2, 3]
        assert_two_decimals(by_rank[1]["priority_score"], 48.00, "priority_score")
        assert_two_decimals(by_rank[2]["priority_score"], 32.00, "priority_score")
        assert_two_decimals(by_rank[3]["priority_score"], 16.00, "priority_score")
        assert_allocation_sums_to(active, BIRCH_RESERVE_CENTS)
        owning_property = X.read_property(api, bundle["property_id"])
        assert_cents(
            owning_property["allocated_reserve_total_cents"],
            BIRCH_RESERVE_CENTS,
            "allocated_reserve_total_cents",
        )
        assert_cents(
            owning_property["capital_reserve_cents"],
            BIRCH_RESERVE_CENTS,
            "capital_reserve_cents",
        )


class TestTheReserveSumAcrossTwoGenerations:
    """Superseding must zero the old rows or the total silently doubles.

    The second generation redistributes the very same 1000000 cents over a
    different rank order with a different leftover, and the sum invariant has to
    survive both.
    """

    def test_the_superseded_generation_leaves_the_sum_entirely(self, api):
        """Three retired rows drop to 0 while three live rows carry the reserve.

        PRD: "Every `CapitalNeedItem` of the property that was `ACTIVE` before
        this recompute moves `ACTIVE -> SUPERSEDED` and has its
        `allocated_reserve_cents` set to 0, so superseded rows leave the sum
        entirely; `SUPERSEDED` is terminal."

        PRD: "The property then recomputes `allocated_reserve_total_cents` over
        the new `ACTIVE` generation only, and the `version` of each superseded item
        and of the property each increment by 1."

        Design: Difficulty/compensating_invariant/reserve_allocation_sum_invariant_holds_across_two_recompute_generations
        """
        bundle = _first_calendar_generation(api)
        retired_id = bundle["generation_one"][0]["id"]
        assert_cents(
            X.read_property(api, bundle["property_id"])[
                "allocated_reserve_total_cents"
            ],
            BIRCH_RESERVE_CENTS,
            "allocated_reserve_total_cents",
        )

        generation_two = X.recompute_capital_needs(
            api, bundle["property_id"], "INSPECTION_SCOPED"
        )

        assert len(generation_two) == 3
        superseded = X.capital_items_by_status(
            api, bundle["property_id"], "SUPERSEDED"
        )
        assert len(superseded) == 3
        for row in superseded:
            assert_cents(
                row["allocated_reserve_cents"], 0, "allocated_reserve_cents"
            )
            assert_fields(row, recurrence_basis="CALENDAR_SCOPED")
        retired = X.read_capital_item(api, retired_id)
        assert_fields(retired, status="SUPERSEDED")
        assert_cents(
            retired["allocated_reserve_cents"], 0, "allocated_reserve_cents"
        )
        assert (
            len(X.capital_items_by_status(api, bundle["property_id"], "ACTIVE"))
            == 3
        )

    def test_the_second_generation_redistributes_the_same_reserve(self, api):
        """A tied pair splits 400000 each on the definition code tie-break.

        PRD: "The items of this generation are ordered by `priority_score`
        descending with the definition's `code` ascending as the tie-break, and
        `allocation_rank` is assigned 1 upward in that order."

        PRD: "`allocated_reserve_total_cents` is the sum of
        `allocated_reserve_cents` across the property's capital need items whose
        `status` is `ACTIVE`."

        Design: Difficulty/compensating_invariant/reserve_allocation_sum_invariant_holds_across_two_recompute_generations
        """
        bundle = _first_calendar_generation(api)
        definition_ids = bundle["definition_ids"]

        X.recompute_capital_needs(
            api, bundle["property_id"], "INSPECTION_SCOPED"
        )

        items = _active_by_definition(api, bundle["property_id"])
        door = items[definition_ids["SEV_DOOR"]]
        assert_integer(door["allocation_rank"], 1, "allocation_rank")
        assert_cents(
            door["allocated_reserve_cents"],
            INSPECTION_SHARES[0],
            "allocated_reserve_cents",
        )
        window = items[definition_ids["SEV_WINDOW"]]
        assert_integer(window["allocation_rank"], 2, "allocation_rank")
        assert_cents(
            window["allocated_reserve_cents"],
            INSPECTION_SHARES[1],
            "allocated_reserve_cents",
        )
        floor = items[definition_ids["MOD_FLOOR"]]
        assert_integer(floor["allocation_rank"], 3, "allocation_rank")
        assert_cents(
            floor["allocated_reserve_cents"],
            INSPECTION_SHARES[2],
            "allocated_reserve_cents",
        )
        assert_allocation_sums_to(list(items.values()), BIRCH_RESERVE_CENTS)
        assert_cents(
            X.read_property(api, bundle["property_id"])[
                "allocated_reserve_total_cents"
            ],
            BIRCH_RESERVE_CENTS,
            "allocated_reserve_total_cents",
        )
