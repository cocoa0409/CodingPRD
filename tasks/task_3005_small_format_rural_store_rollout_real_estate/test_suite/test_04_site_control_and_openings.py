"""Site-control agreements, delivery penalties, and the opening calendar."""

import pytest

from test_helpers import (
    ApiErrorId,
    activate_agreement,
    create_active_rollout,
    create_developer,
    create_qualified_trade_area,
    create_opening_plan,
    create_site_agreement,
    get_success_data,
    lock_opening_plan,
    read_store,
    record_delivery,
    setup_store_site_control,
    setup_store_under_construction,
    setup_store_with_format,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
REAL_ESTATE = TEST_USERS["real_estate_manager_headers"]
NETWORK = TEST_USERS["network_planner_headers"]
OPERATIONS = TEST_USERS["operations_lead_headers"]


def _store_with_site_control(api, committed_delivery_date="2026-11-01T00:00:00Z"):
    rollout = create_active_rollout(name="P")
    area = create_qualified_trade_area(rollout["id"], name="C")
    store = setup_store_with_format(rollout["id"], area["id"], name="S")
    developer, agreement = setup_store_site_control(
        rollout["id"], store["id"], committed_delivery_date=committed_delivery_date
    )
    return rollout, area, store, developer, agreement


class TestStoreKillGating:
    def test_store_kill_blocked_by_open_site_control(self, api):
        """PRD §3.3: "A store may be killed from `PROPOSED`, `SITE_CONTROL`, or
        `UNDER_CONSTRUCTION`, but only when no agreement for the store remains
        open — that is, no agreement in any status other than `TERMINATED` or
        `COMPLETED`; an open agreement blocks the kill with
        `ERR_SITE_CONTROL_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/store_kill_blocked_by_open_site_control
        """
        rollout, area, store, developer, agreement = _store_with_site_control(api)
        assert agreement["status"] == "EXECUTED"

        resp = api.kill_store(
            store["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
        )
        validate_error(resp, ApiErrorId.ERR_SITE_CONTROL_ACTIVE)

        # Terminate the EXECUTED agreement; the store reverts to PROPOSED.
        terminated = validate_success(
            api.terminate_agreement(
                agreement["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        assert terminated["status"] == "TERMINATED"
        assert read_store(store["id"])["status"] == "PROPOSED"

        killed = validate_success(
            api.kill_store(
                store["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        assert killed["status"] == "KILLED"

    def test_kill_rejected_again_after_termination(self, api):
        """PRD §3.3: "A store may be killed from `PROPOSED`, `SITE_CONTROL`, or
        `UNDER_CONSTRUCTION`, but only when no agreement for the store remains
        open — that is, no agreement in any status other than `TERMINATED` or
        `COMPLETED`; an open agreement blocks the kill with
        `ERR_SITE_CONTROL_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/store_kill_blocked_by_open_site_control
        """
        rollout, area, store, developer, agreement = _store_with_site_control(api)
        # While the EXECUTED agreement is open, every kill attempt is blocked.
        for _ in range(2):
            resp = api.kill_store(
                store["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            )
            validate_error(resp, ApiErrorId.ERR_SITE_CONTROL_ACTIVE)
        assert read_store(store["id"])["status"] == "SITE_CONTROL"


class TestDeliveryPenalty:
    def test_delivery_penalty_bonus_tier_and_cap(self, api):
        """PRD §3.4: "Separately, a lateness bonus applies once delivery is
        more than 60 days late: each day beyond day 60 adds half the daily rate,
        that is 250,000 cents per such day. The penalty is the base accrual
        plus the bonus, capped at 45,000,000 cents, and lands on the agreement
        as `penalty_cents` alongside `late_days`."

        Design: Difficulty/boundary_precision_check/delivery_penalty_bonus_tier_and_cap
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer, agreement = setup_store_under_construction(
            rollout["id"], store["id"]
        )
        # 80 days late: base 80*500000 = 40000000, bonus (80-60)*250000 =
        # 5000000 -> sum equals the 45000000 cap.
        resp = api.record_delivery(
            agreement["id"],
            {
                "rollout_program_id": rollout["id"],
                "actual_delivery_date": "2027-01-20T00:00:00Z",
            },
            REAL_ESTATE,
        )
        delivered = validate_success(resp, 200)
        assert delivered["late_days"] == 80
        assert delivered["penalty_cents"] == 45000000

    def test_delivery_penalty_below_cap_at_seventy_five_days(self, api):
        """PRD §3.4: "The delivery penalty accrues at 500,000 cents per late
        day, but accrual stops at day 180 — days beyond 180 earn nothing
        further at the base rate. Separately, a lateness bonus applies once
        delivery is more than 60 days late: each day beyond day 60 adds half
        the daily rate, that is 250,000 cents per such day."

        Design: Difficulty/boundary_precision_check/delivery_penalty_bonus_tier_and_cap
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer, agreement = setup_store_under_construction(
            rollout["id"], store["id"]
        )
        # 75 days late: 2026-11-01 + 75 = 2027-01-15. 37500000 + 15*250000 =
        # 41250000, below the cap.
        delivered = record_delivery(
            rollout["id"], agreement["id"], "2027-01-15T00:00:00Z"
        )
        assert delivered["late_days"] == 75
        assert delivered["penalty_cents"] == 41250000


class TestLateDeliveryCascade:
    def test_late_delivery_cascade_cancels_opening_plan(self, api):
        """PRD §3.4: "Delivery releases the developer slot —
        `active_agreement_count` decreases by 1 — and a badly late delivery has
        one further consequence: when `late_days` reaches 30 or more, the
        store's opening plan, if it is `PLANNED` or `LOCKED`, is cancelled,
        because the opening calendar built around the committed delivery date
        is no longer usable."

        Design: Difficulty/transitive_cascade/late_delivery_cascade_cancels_opening_plan
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        # PRD §3.6: plan creation requires an EXECUTED agreement and locking
        # requires SITE_CONTROL, so the plan is created and locked before the
        # agreement activates.
        developer, agreement = setup_store_site_control(rollout["id"], store["id"])
        plan = create_opening_plan(rollout["id"], store["id"], "2026-12-05T00:00:00Z")
        lock_opening_plan(rollout["id"], plan["id"])
        agreement = activate_agreement(rollout["id"], agreement["id"])

        # 40 days late (2026-11-01 + 40 = 2026-12-11): base 40*500000 = 20000000.
        delivered = record_delivery(
            rollout["id"], agreement["id"], "2026-12-11T00:00:00Z"
        )
        assert delivered["status"] == "DELIVERED"
        assert delivered["late_days"] == 40
        assert delivered["penalty_cents"] == 20000000

        assert read_store(store["id"])["status"] == "DELIVERED"
        plan_after = get_success_data(api.get_opening_plan(plan["id"], OPERATIONS))
        assert plan_after["status"] == "CANCELLED"
        dev_after = get_success_data(api.get_developer(developer["id"], ADMIN))
        assert dev_after["active_agreement_count"] == 0

    def test_on_time_delivery_leaves_opening_plan_locked(self, api):
        """PRD §3.4: "Lateness is computed in whole calendar days: zero when
        the delivery lands on or before `committed_delivery_date`"
        PRD §3.4: "when `late_days` reaches 30 or more, the store's opening
        plan, if it is `PLANNED` or `LOCKED`, is cancelled"

        Design: Difficulty/transitive_cascade/late_delivery_cascade_cancels_opening_plan
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer, agreement = setup_store_site_control(rollout["id"], store["id"])
        plan = create_opening_plan(rollout["id"], store["id"], "2026-12-05T00:00:00Z")
        lock_opening_plan(rollout["id"], plan["id"])
        agreement = activate_agreement(rollout["id"], agreement["id"])

        # On-time delivery: no penalty, no cascade.
        delivered = record_delivery(
            rollout["id"], agreement["id"], "2026-11-01T00:00:00Z"
        )
        assert delivered["late_days"] == 0
        assert delivered["penalty_cents"] == 0
        plan_after = get_success_data(api.get_opening_plan(plan["id"], OPERATIONS))
        assert plan_after["status"] == "LOCKED"


class TestDeveloperCapacity:
    def test_developer_three_agreement_capacity_cap(self, api):
        """PRD §3.4: "Activation then moves the agreement `EXECUTED → ACTIVE`:
        it requires an `ACTIVE` program (`ERR_PROGRAM_NOT_ACTIVE` otherwise),
        requires the developer's `active_agreement_count` to be below 3
        (`ERR_DEVELOPER_CAPACITY_EXCEEDED` otherwise), increments that count by
        1"

        Design: Difficulty/resource_temporal_overlap/developer_three_agreement_capacity_cap
        """
        rollout = create_active_rollout(name="P")
        developer = create_developer(rollout["id"], name="DevCo")
        agreements = []
        for i in (1, 2, 3, 4):
            area = create_qualified_trade_area(rollout["id"], name=f"C{i}")
            store = setup_store_with_format(rollout["id"], area["id"], name=f"S{i}")
            agreement = create_site_agreement(
                rollout["id"], store["id"], developer["id"]
            )
            agreement = validate_success(
                api.execute_agreement(
                    agreement["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
                ),
                200,
            )
            agreements.append(agreement)
        for agreement in agreements[:3]:
            activate_agreement(rollout["id"], agreement["id"])

        # Fourth activation collides with the 3-slot cap.
        resp = api.activate_agreement(
            agreements[3]["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
        )
        validate_error(resp, ApiErrorId.ERR_DEVELOPER_CAPACITY_EXCEEDED)

        # Terminating one ACTIVE agreement frees exactly one slot.
        validate_success(
            api.terminate_agreement(
                agreements[0]["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        dev_after = get_success_data(api.get_developer(developer["id"], ADMIN))
        assert dev_after["active_agreement_count"] == 2

        activated = validate_success(
            api.activate_agreement(
                agreements[3]["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"
        dev_final = get_success_data(api.get_developer(developer["id"], ADMIN))
        assert dev_final["active_agreement_count"] == 3

    def test_developer_slot_release_on_delivery(self, api):
        """PRD §3.4: "Delivery releases the developer slot —
        `active_agreement_count` decreases by 1"

        Design: Difficulty/resource_temporal_overlap/developer_three_agreement_capacity_cap
        """
        rollout, area, store, developer, agreement = _store_with_site_control(api)
        activate_agreement(rollout["id"], agreement["id"])
        dev_mid = get_success_data(api.get_developer(developer["id"], ADMIN))
        assert dev_mid["active_agreement_count"] == 1
        record_delivery(rollout["id"], agreement["id"], "2026-11-01T00:00:00Z")
        dev_after = get_success_data(api.get_developer(developer["id"], ADMIN))
        assert dev_after["active_agreement_count"] == 0


class TestOpeningCalendar:
    def test_opening_calendar_buffer_window_conflict(self, api):
        """PRD §3.6: "Locking requires the store to be in `SITE_CONTROL` — any
        other store status fails with `ERR_OPENING_PLAN_STATE` — and requires
        the store's `EXECUTED` agreement to promise delivery no later than the
        fixture kit's ship date: the `committed_delivery_date` must be on or
        before `fixture_kit_ship_date`, so fixtures arrive before
        building-delivery pressure, else the lock fails with
        `ERR_FIXTURE_LEAD_TIME`."

        Design: Difficulty/resource_temporal_overlap/opening_calendar_buffer_window_conflict
        """
        # Delivery 2026-11-25 is inside the 21-day buffer of the 2026-12-05
        # opening (ship date 2026-11-14): lock must fail.
        rollout, area, store, developer, agreement = _store_with_site_control(
            api, committed_delivery_date="2026-11-25T00:00:00Z"
        )
        plan = create_opening_plan(rollout["id"], store["id"], "2026-12-05T00:00:00Z")
        resp = api.lock_opening_plan(
            plan["id"], {"rollout_program_id": rollout["id"]}, OPERATIONS
        )
        validate_error(resp, ApiErrorId.ERR_FIXTURE_LEAD_TIME)

        # Re-agree with delivery exactly on the ship date: boundary is inclusive.
        validate_success(
            api.terminate_agreement(
                agreement["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        agreement2 = create_site_agreement(
            rollout["id"], store["id"], developer["id"],
            committed_delivery_date="2026-11-14T00:00:00Z",
        )
        validate_success(
            api.execute_agreement(
                agreement2["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        locked = validate_success(
            api.lock_opening_plan(
                plan["id"], {"rollout_program_id": rollout["id"]}, OPERATIONS
            ),
            200,
        )
        assert locked["status"] == "LOCKED"
        assert locked["fixture_kit_ship_date"] == "2026-11-14T00:00:00Z"

    def test_fixture_ship_date_derived_twenty_one_days_out(self, api):
        """PRD §3.6: "Two derived dates are computed at creation:
        `fixture_kit_ship_date`, exactly 21 days before `opening_date`, and
        `inventory_push_date`, exactly 10 days before `opening_date`."

        Design: Difficulty/resource_temporal_overlap/opening_calendar_buffer_window_conflict
        """
        rollout, area, store, developer, agreement = _store_with_site_control(api)
        plan = create_opening_plan(rollout["id"], store["id"], "2026-12-05T00:00:00Z")
        assert plan["fixture_kit_ship_date"] == "2026-11-14T00:00:00Z"
        assert plan["inventory_push_date"] == "2026-11-25T00:00:00Z"

    def test_opening_plan_lock_unlock_relock_cycle(self, api):
        """PRD §3.6: "Locking freezes the calendar, moving the plan
        `PLANNED → LOCKED`."
        PRD §3.6: "Unlocking returns the plan `LOCKED → PLANNED` and unfreezes
        the calendar; it is permitted while the store is `SITE_CONTROL` or
        `PROPOSED`."

        Design: Difficulty/non_linear_state_machine/opening_plan_lock_unlock_relock_cycle
        """
        rollout, area, store, developer, agreement = _store_with_site_control(api)
        plan = create_opening_plan(
            rollout["id"], store["id"], "2026-12-05T00:00:00Z", peak_season=False
        )
        assert plan["labor_hours"] == 220  # TRADITIONAL base, off-peak

        locked1 = lock_opening_plan(rollout["id"], plan["id"])
        assert locked1["status"] == "LOCKED"
        unlocked = validate_success(
            api.unlock_opening_plan(
                plan["id"], {"rollout_program_id": rollout["id"]}, OPERATIONS
            ),
            200,
        )
        assert unlocked["status"] == "PLANNED"
        locked2 = lock_opening_plan(rollout["id"], plan["id"])
        assert locked2["status"] == "LOCKED"

        assert read_store(store["id"])["status"] == "SITE_CONTROL"
        # The cycle does not recompute labor.
        assert locked2["labor_hours"] == 220

    def test_lock_after_unlock_cycle_preserves_calendar(self, api):
        """PRD §3.6: "While `LOCKED`, the `opening_date` is immutable."
        PRD §3.6: "The store's `opening_date` is copied from the plan at
        creation."

        Design: Difficulty/non_linear_state_machine/opening_plan_lock_unlock_relock_cycle
        """
        rollout, area, store, developer, agreement = _store_with_site_control(api)
        plan = create_opening_plan(rollout["id"], store["id"], "2026-12-05T00:00:00Z")
        lock_opening_plan(rollout["id"], plan["id"])
        validate_success(
            api.unlock_opening_plan(
                plan["id"], {"rollout_program_id": rollout["id"]}, OPERATIONS
            ),
            200,
        )
        relocked = lock_opening_plan(rollout["id"], plan["id"])
        assert relocked["opening_date"] == "2026-12-05T00:00:00Z"
        store_after = read_store(store["id"])
        assert store_after["opening_date"] == "2026-12-05T00:00:00Z"
        assert store_after["status"] == "SITE_CONTROL"


class TestOpeningPlanCreation:
    def test_labor_plan_peak_uplift_ceil(self, api):
        """PRD §3.6: "Base hours depend on the store's `format_type`: 220 hours
        for `TRADITIONAL`, 340 for `DG_FRESH`, 520 for `DG_MARKET`. When
        `peak_season` is true, the base is uplifted by 15 percent — multiplied
        by 1.15 and rounded up to whole hours — to produce `labor_hours`;
        otherwise `labor_hours` is the base. `labor_cost_cents` is the labor
        hours multiplied by the labor rate of 2,400 cents per hour."

        Design: Corner/calculations/labor_plan_peak_uplift_ceil
        """
        rollout, area, store, developer, agreement = _store_with_site_control(api)
        plan = create_opening_plan(
            rollout["id"], store["id"], "2026-12-05T00:00:00Z", peak_season=True
        )
        # ceil(220 * 1.15) = 253 hours; 253 * 2400 = 607200.
        assert plan["labor_hours"] == 253
        assert plan["labor_cost_cents"] == 607200
        assert plan["fixture_kit_ship_date"] == "2026-11-14T00:00:00Z"
        assert plan["inventory_push_date"] == "2026-11-25T00:00:00Z"
        # The opening date is copied onto the store.
        assert read_store(store["id"])["opening_date"] == "2026-12-05T00:00:00Z"

    def test_opening_plan_create_too_soon_rejected(self, api):
        """PRD §3.6: "The date itself must sit at least 45 days in the future
        relative to the program's logical clock; a nearer date fails with
        `ERR_OPENING_TOO_EARLY`."
        PRD §2.10: "Before any clock-setting call for a program, the clock
        reads exactly `2026-09-01T00:00:00Z` — the server startup default — and
        it must never fall back to real wall-clock time."

        Design: Corner/validations/opening_plan_create_too_soon_rejected
        """
        rollout, area, store, developer, agreement = _store_with_site_control(
            api, committed_delivery_date="2026-10-01T00:00:00Z"
        )
        # 2026-10-01 is only 30 days past the default clock 2026-09-01.
        resp = api.create_opening_plan(
            {
                "rollout_program_id": rollout["id"],
                "store_id": store["id"],
                "opening_date": "2026-10-01T00:00:00Z",
                "peak_season": False,
            },
            OPERATIONS,
        )
        validate_error(resp, ApiErrorId.ERR_OPENING_TOO_EARLY)

    def test_clock_set_drives_opening_lead_rule(self, api):
        """PRD §2.10: "A `PROGRAM_ADMIN` advances a program's clock through a
        test-driving capability that accepts the target program's
        `rollout_program_id` and a `to_iso8601` instant, and returns the
        program's `current_utc`."
        PRD §3.6: "The date itself must sit at least 45 days in the future
        relative to the program's logical clock; a nearer date fails with
        `ERR_OPENING_TOO_EARLY`."

        Design: Corner/endpoints/clock_set_drives_opening_lead_rule
        """
        rollout, area, store, developer, agreement = _store_with_site_control(api)
        clock = validate_success(
            api.set_clock(
                {
                    "rollout_program_id": rollout["id"],
                    "to_iso8601": "2026-10-01T00:00:00Z",
                },
                ADMIN,
            ),
            200,
        )
        assert clock["current_utc"] == "2026-10-01T00:00:00Z"
        # 2026-11-20 is 50 days past the set clock — passes the 45-day minimum.
        plan = create_opening_plan(
            rollout["id"], store["id"], "2026-11-20T00:00:00Z", peak_season=False
        )
        assert plan["status"] == "PLANNED"


class TestAgreementValidation:
    def test_duplicate_active_agreement_rejected(self, api):
        """PRD §3.4: "At most one agreement per store may be open — in any
        status other than `TERMINATED` or `COMPLETED` — so drafting a second
        open agreement for a store that already has one fails with
        `ERR_DUPLICATE_ACTIVE`."

        Design: Corner/validations/duplicate_active_agreement_rejected
        """
        rollout, area, store, developer, agreement = _store_with_site_control(api)
        resp = api.create_site_agreement(
            {
                "rollout_program_id": rollout["id"],
                "store_id": store["id"],
                "developer_id": developer["id"],
                "committed_delivery_date": "2026-12-01T00:00:00Z",
                "base_price_cents": 20000000,
                "earnest_money_cents": 1000000,
            },
            REAL_ESTATE,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE)

    def test_earnest_money_validation(self, api):
        """PRD §3.4: "the `earnest_money_cents` deposit (which must be greater
        than 0 and strictly less than `base_price_cents`; a deposit that meets
        or exceeds the base price fails as `ERR_VALIDATION`)"

        Design: Corner/validations/earnest_money_validation
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer = create_developer(rollout["id"], name="DevCo")
        resp = api.create_site_agreement(
            {
                "rollout_program_id": rollout["id"],
                "store_id": store["id"],
                "developer_id": developer["id"],
                "committed_delivery_date": "2026-11-01T00:00:00Z",
                "base_price_cents": 24000000,
                "earnest_money_cents": 24000000,
            },
            REAL_ESTATE,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_network_planner_cannot_execute_agreement(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the
        targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: the agreement execute endpoint is authorized for
        REAL_ESTATE_MANAGER only.

        Design: Corner/rbac/network_planner_cannot_execute_agreement
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer = create_developer(rollout["id"], name="DevCo")
        agreement = create_site_agreement(
            rollout["id"], store["id"], developer["id"]
        )
        resp = api.execute_agreement(
            agreement["id"], {"rollout_program_id": rollout["id"]}, NETWORK
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_site_agreement(agreement["id"], REAL_ESTATE))
        assert after["status"] == "DRAFT"

    def test_volume_index_locked_after_format_progression(self, api):
        """PRD §3.3: "While a store remains `PROPOSED`, a `NETWORK_PLANNER` may
        tune its `volume_index`, the weekly case volume multiplier against
        baseline, which starts at 1.0; the update supplies `rollout_program_id`
        and the new `volume_index`, increments the store's `version` by 1, and
        is rejected with `ERR_STORE_PRECONDITION` once the store has advanced
        past `PROPOSED`."

        Design: Corner/validations/volume_index_locked_after_format_progression
        """
        rollout, area, store, developer, agreement = _store_with_site_control(api)
        assert read_store(store["id"])["status"] == "SITE_CONTROL"
        resp = api.update_store(
            store["id"],
            {"rollout_program_id": rollout["id"], "volume_index": 1.5},
            NETWORK,
        )
        validate_error(resp, ApiErrorId.ERR_STORE_PRECONDITION)
