"""Curriculum-kit planning, supply budget, and stock reservation
(PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    approve_order,
    cancel_distribution,
    cancel_order,
    create_classroom,
    create_day,
    create_distribution,
    create_item,
    create_order,
    create_program,
    get_item,
    get_order,
    get_supply_plan,
    issue_distribution,
    patch_order,
    setup_program_with_enrollment,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

_DIRECTOR = TEST_USERS["program_director_headers"]


class TestKitRecommendationVariants:
    def _setup_five_enrolled(self):
        """5 enrolled children across 2 non-CLOSED classrooms."""
        return setup_program_with_enrollment(
            classroom_specs=[
                {"name": "Koalas", "age_min": 4, "age_max": 6, "capacity": 10},
                {"name": "Bears", "age_min": 7, "age_max": 9, "capacity": 10},
            ],
            birth_dates_per_classroom=[
                ["2020-03-15", "2020-06-20", "2021-01-05"],
                ["2018-05-10", "2017-11-30"],
            ],
        )

    def test_provisional_and_final_variants_differ(self, api):
        """PRD §3.6: "the program's enrolled total multiplied by 1.10 — a
        ten-percent buffer — rounded up to the next whole kit, so five enrolled
        children yield a base of six kits. The provisional variant, surfaced on
        an order as `recommended_provisional`, is exactly that base. The final
        variant, surfaced as `required_final`, adds one teacher kit per
        classroom whose status is not `CLOSED`" — same enrollment data, two
        variants: ceil(5 * 1.10) == 6 provisional versus 6 + 2 == 8 final.

        Design: Difficulty/dual_variant_calc/kit_recommendation_provisional_vs_final
        """
        ctx = self._setup_five_enrolled()
        plan = get_supply_plan(ctx["program"]["id"])
        assert plan["enrolled_total"] == 5
        assert plan["kit_quantity_provisional"] == 6
        assert plan["kit_quantity_final"] == 8

    def test_submit_enforces_final_variant(self, api):
        """PRD §3.6: "Submitting moves `DRAFT` → `SUBMITTED` and enforces the
        final kit requirement at submit time: a `quantity` below
        `required_final` is rejected with `ERR_KIT_QUANTITY_SHORT`." Quantity 6
        satisfies the provisional figure but not the final one; 8 satisfies
        both.

        Design: Difficulty/dual_variant_calc/kit_recommendation_provisional_vs_final
        """
        ctx = self._setup_five_enrolled()
        order = create_order(ctx["program"]["id"], kit_name="Starter Kit",
                             vendor="Cokesbury", quantity=6, unit_cost_cents=3000)
        resp = api.submit_supply_order(order["id"], _DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_KIT_QUANTITY_SHORT, 409)

        patched = patch_order(order["id"], quantity=8)
        assert patched["quantity"] == 8
        resubmitted = submit_order(order["id"])
        assert resubmitted["status"] == "SUBMITTED"


class TestCraftPackRounding:
    def _setup_two_classrooms_of_four(self):
        return setup_program_with_enrollment(
            classroom_specs=[
                {"name": "Koalas", "age_min": 4, "age_max": 6, "capacity": 10},
                {"name": "Bears", "age_min": 7, "age_max": 9, "capacity": 10},
            ],
            birth_dates_per_classroom=[
                ["2020-03-15"] * 4,
                ["2018-05-10"] * 4,
            ],
        )

    def test_per_classroom_rounding_then_sum(self, api):
        """PRD §3.6: "Craft packs follow a pinned rounding order — round per
        classroom first, then sum: for each classroom not `CLOSED`, multiply
        its `enrolled_count` by 3 craft units per child and round up to whole
        packs of 10; the program total is the sum of those per-classroom pack
        counts. Pooling first would under-order: two classrooms of four
        enrolled children each need twelve units apiece, rounding up to two
        packs per classroom and four in total — whereas pooling the twenty-four
        units first would round up to three."

        Design: Difficulty/combinatorial_formula/craft_pack_rounding_per_classroom_then_sum
        """
        ctx = self._setup_two_classrooms_of_four()
        plan = get_supply_plan(ctx["program"]["id"])
        assert plan["craft_packs_required"] == 4, (
            "ceil(4*3/10) per classroom = 2 each, summed = 4"
        )

    def test_per_classroom_breakdown_reports_two_each(self, api):
        """PRD §3.6: "two classrooms of four enrolled children each need twelve
        units apiece, rounding up to two packs per classroom and four in
        total" — the per-classroom breakdown carries two packs for each
        classroom.

        Design: Difficulty/combinatorial_formula/craft_pack_rounding_per_classroom_then_sum
        """
        ctx = self._setup_two_classrooms_of_four()
        plan = get_supply_plan(ctx["program"]["id"])
        per_classroom = plan["craft_packs_per_classroom"]
        # The PRD names a "per-classroom breakdown" without pinning the
        # container shape; accept a mapping keyed by classroom, a list of
        # per-classroom pack counts, or a list of per-classroom rows that
        # carry the count under a "packs" key.
        if isinstance(per_classroom, dict):
            values = list(per_classroom.values())
        elif per_classroom and isinstance(per_classroom[0], dict):
            values = [row["packs"] for row in per_classroom]
        else:
            values = list(per_classroom)
        assert len(values) == 2, "one entry per non-CLOSED classroom"
        assert sorted(values) == [2, 2], "per-classroom rounding happens BEFORE the sum"


class TestBudgetRemaining:
    def test_unapproved_orders_consume_nothing(self, api):
        """PRD §3.6: "`budget_remaining_cents` is the program's
        `supply_budget_cents` minus the sum of `total_cost_cents` over the
        program's `APPROVED` orders only — `DRAFT`, `SUBMITTED`, and
        `CANCELLED` orders consume nothing".

        Design: Corner/calculations/budget_remaining_excludes_unapproved_orders
        """
        program = create_program()  # no classrooms: required_final == 0
        order_a = create_order(program["id"], kit_name="Kit A", quantity=2,
                               unit_cost_cents=3000)
        submit_order(order_a["id"])
        approve_order(order_a["id"])

        order_b = create_order(program["id"], kit_name="Kit B", quantity=5,
                               unit_cost_cents=3000)
        submit_order(order_b["id"])

        create_order(program["id"], kit_name="Kit C", quantity=7,
                     unit_cost_cents=3000)  # stays DRAFT

        order_d = create_order(program["id"], kit_name="Kit D", quantity=1,
                               unit_cost_cents=3000)
        cancel_order(order_d["id"])

        plan = get_supply_plan(program["id"])
        assert plan["budget_remaining_cents"] == 94000, (
            "only the APPROVED order's 6000 is deducted from 100000"
        )

    def test_budget_exceeded_on_approve_rejected(self, api):
        """PRD §3.6: "Approval re-checks the budget at approval time:
        `total_cost_cents` must not exceed `budget_remaining_cents`, or the
        approve fails with `ERR_BUDGET_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/budget_exceeded_on_approve_rejected
        """
        program = create_program()  # budget 100000, no classrooms
        order_a = create_order(program["id"], kit_name="Kit A", quantity=10,
                               unit_cost_cents=7000)
        submit_order(order_a["id"])
        approve_order(order_a["id"])

        order_b = create_order(program["id"], kit_name="Kit B", quantity=6,
                               unit_cost_cents=6000)
        submit_order(order_b["id"])

        resp = api.approve_supply_order(order_b["id"], _DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED, 402)

        assert get_order(order_b["id"])["status"] == "SUBMITTED"
        assert get_supply_plan(program["id"])["budget_remaining_cents"] == 30000


class TestSupplyOrderLifecycle:
    def test_revision_loop_roundtrip(self, api):
        """PRD §3.6: "While `DRAFT`, the director may patch `kit_name`,
        `vendor`, `quantity`, or `unit_cost_cents`"; "A submitted order can be
        returned for revision (`SUBMITTED` → `DRAFT`), cancelled (`DRAFT` or
        `SUBMITTED` → `CANCELLED`), or approved."; and "a successful approval
        lowers the remaining budget by exactly the approved total."

        Design: Corner/state_machines/supply_order_revision_loop_roundtrip
        """
        program = create_program()  # budget 100000, no classrooms
        order = create_order(program["id"], quantity=4, unit_cost_cents=5000)
        assert submit_order(order["id"])["status"] == "SUBMITTED"

        returned = api.return_supply_order_for_revision(order["id"], _DIRECTOR)
        assert validate_success(returned)["status"] == "DRAFT"

        patched = patch_order(order["id"], quantity=5)
        assert patched["total_cost_cents"] == 25000, (
            "edit while DRAFT took effect: 5 * 5000"
        )
        assert submit_order(order["id"])["status"] == "SUBMITTED"
        assert approve_order(order["id"])["status"] == "APPROVED", (
            "the revision loop cycles legally"
        )
        assert get_supply_plan(program["id"])["budget_remaining_cents"] == 75000


class TestApproveStateBeatsFiscal:
    def _setup_draft_over_budget_order(self):
        """DRAFT order (cannot be approved) whose total 30 * 4000 == 120000
        also exceeds the 100000 budget: state (priority 6) and fiscal
        (priority 10) both fail."""
        program = create_program()
        order = create_order(program["id"], kit_name="Starter Kit",
                             vendor="Cokesbury", quantity=30, unit_cost_cents=4000)
        return program, order

    def test_invalid_state_wins_over_budget_exceeded(self, api):
        """PRD §2.9: "Tiers run in ascending priority number, and when several
        checks fail at once the lowest-numbered failure wins and produces the
        response." — priority 6's state permission
        "(`ERR_INVALID_STATE`, HTTP 409, all action endpoints)" sits ahead of
        the fiscal tier, "evaluated last: submit quantity against the final
        kit requirement (`ERR_KIT_QUANTITY_SHORT`); approval total against the
        remaining budget (`ERR_BUDGET_EXCEEDED`, HTTP 402)".

        Design: Difficulty/priority_pair_validation_conflict/order_approve_state_beats_fiscal
        """
        _program, order = self._setup_draft_over_budget_order()
        resp = api.approve_supply_order(order["id"], _DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_rejected_approve_changes_nothing(self, api):
        """PRD §3.6: "the order is born `DRAFT`, and its `total_cost_cents` is
        the quantity multiplied by the unit cost in integer cents" — the
        rejected approve leaves the DRAFT order and its computed total
        untouched.

        Design: Difficulty/priority_pair_validation_conflict/order_approve_state_beats_fiscal
        """
        _program, order = self._setup_draft_over_budget_order()
        api.approve_supply_order(order["id"], _DIRECTOR)
        after = get_order(order["id"])
        assert after["status"] == "DRAFT"
        assert after["total_cost_cents"] == 120000


class TestStockReservation:
    def test_insufficient_stock_at_zero_available(self, api):
        """PRD §3.6: "`quantity` must not exceed the item's
        `available_quantity` (`ERR_INSUFFICIENT_STOCK`)", where
        "`available_quantity`, the on-hand minus the reserved" — with 3 on
        hand fully reserved, one more unit fails and changes nothing.

        Design: Corner/validations/insufficient_stock_at_zero_available
        """
        program = create_program()
        classroom = create_classroom(program["id"])
        day = create_day(program["id"], program["start_date"])
        item = create_item(program["id"], name="Glue Packs", quantity_on_hand=3)
        create_distribution(item["id"], classroom["id"], day["id"], 3)

        resp = api.create_supply_distribution(
            {"supply_item_id": item["id"], "classroom_id": classroom["id"],
             "program_day_id": day["id"], "quantity": 1},
            _DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK, 409)

        item_after = get_item(item["id"])
        assert item_after["quantity_on_hand"] == 3
        assert item_after["reserved_quantity"] == 3, (
            "the failed reservation changed nothing"
        )

    def test_cross_program_distribution_rejected(self, api):
        """PRD §3.6: "item, classroom, and day must all belong to the same
        program (`ERR_CROSS_PROGRAM_REFERENCE`)".

        Design: Corner/validations/cross_program_distribution_rejected
        """
        program_a = create_program(name="VBS Alpha")
        item_a = create_item(program_a["id"], name="Glue Packs", quantity_on_hand=5)

        program_b = create_program(
            name="VBS Beta", start_date="2026-08-24", end_date="2026-08-28",
        )
        classroom_b = create_classroom(program_b["id"], name="Bears",
                                       age_min=7, age_max=9)
        day_b = create_day(program_b["id"], "2026-08-24")

        resp = api.create_supply_distribution(
            {"supply_item_id": item_a["id"], "classroom_id": classroom_b["id"],
             "program_day_id": day_b["id"], "quantity": 1},
            _DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE, 409)


class TestStockConservation:
    def _setup(self):
        program = create_program()
        classroom = create_classroom(program["id"], name="Koalas")
        day = create_day(program["id"], program["start_date"])
        item = create_item(program["id"], name="Glue Packs", quantity_on_hand=5)
        return classroom, day, item

    def test_plan_reserves_and_cancel_fully_compensates(self, api):
        """PRD §3.6: "Two quantities derive continuously: `reserved_quantity`,
        the sum of `quantity` over the item's `PLANNED` distributions, and
        `available_quantity`, the on-hand minus the reserved."; "Cancelling
        moves `PLANNED` → `CANCELLED`: the reservation releases —
        `reserved_quantity` drops by `quantity` — while on-hand stays
        untouched, the compensating mirror of planning."

        Design: Difficulty/compensating_invariant/stock_conservation_plan_then_cancel
        """
        classroom, day, item = self._setup()
        distribution = create_distribution(item["id"], classroom["id"], day["id"], 3)
        mid = get_item(item["id"])
        assert mid["reserved_quantity"] == 3
        assert mid["quantity_on_hand"] == 5, "planning reserves without touching on-hand"
        assert mid["available_quantity"] == 2

        cancel_distribution(distribution["id"])
        after = get_item(item["id"])
        assert after["reserved_quantity"] == 0
        assert after["quantity_on_hand"] == 5, (
            "cancel fully compensates: both quantities identical to pre-plan"
        )

    def test_issue_moves_exactly_quantity_out_of_on_hand(self, api):
        """PRD §3.6: "Issuing moves `PLANNED` → `ISSUED`: `quantity_on_hand`
        and `reserved_quantity` each drop by `quantity`, and `issued_at` is
        stamped."

        Design: Difficulty/compensating_invariant/stock_conservation_plan_then_cancel
        """
        classroom, day, item = self._setup()
        distribution = create_distribution(item["id"], classroom["id"], day["id"], 3)
        issued = issue_distribution(distribution["id"])
        assert issued["status"] == "ISSUED"
        assert issued["issued_at"] is not None

        after = get_item(item["id"])
        assert after["reserved_quantity"] == 0, (
            "reserved returns to 0 — reserved equals the sum over PLANNED rows"
        )
        assert after["quantity_on_hand"] == 2, "issue moved exactly 3 out of on-hand"
