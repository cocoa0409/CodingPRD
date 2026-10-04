"""Store pipeline lifecycle: kill cascades, opening execution, terminal states."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_agreement,
    create_active_rollout,
    create_dc_assignment,
    create_distribution_center,
    create_opening_plan,
    create_qualified_trade_area,
    create_route_plan,
    create_store,
    get_success_data,
    lock_opening_plan,
    read_rollout,
    read_store,
    record_delivery,
    setup_store_site_control,
    setup_store_under_construction,
    setup_store_with_format,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
REAL_ESTATE = TEST_USERS["real_estate_manager_headers"]
NETWORK = TEST_USERS["network_planner_headers"]
OPERATIONS = TEST_USERS["operations_lead_headers"]
FINANCE = TEST_USERS["finance_analyst_headers"]


def _open_store(api, opening_date="2026-12-05T00:00:00Z"):
    """Drive a store all the way to OPEN via an on-time delivery and an
    executed opening plan.  Returns (rollout, store, developer, agreement, plan)."""
    rollout = create_active_rollout(name="P")
    area = create_qualified_trade_area(rollout["id"], name="C")
    store = setup_store_with_format(rollout["id"], area["id"], name="S")
    # PRD §3.6: plan creation requires an EXECUTED agreement and locking
    # requires the store in SITE_CONTROL, so the plan is created and locked
    # before the agreement activates.
    developer, agreement = setup_store_site_control(rollout["id"], store["id"])
    plan = create_opening_plan(rollout["id"], store["id"], opening_date)
    lock_opening_plan(rollout["id"], plan["id"])
    agreement = activate_agreement(rollout["id"], agreement["id"])
    record_delivery(rollout["id"], agreement["id"], "2026-11-01T00:00:00Z")
    validate_success(
        api.set_clock(
            {"rollout_program_id": rollout["id"], "to_iso8601": "2026-12-04T00:00:00Z"},
            ADMIN,
        ),
        200,
    )
    return rollout, store, developer, agreement, plan


class TestKillTransitions:
    def test_kill_proposed_store_terminal(self, api):
        """PRD §3.3: "A store may be killed from `PROPOSED`, `SITE_CONTROL`, or
        `UNDER_CONSTRUCTION`, but only when no agreement for the store remains
        open"
        PRD §2.11: "state legality — the target resource must be in a state
        from which the requested transition is defined, else
        `ERR_INVALID_STATE`"

        Design: Corner/state_machines/kill_proposed_store_terminal
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="A")
        store = create_store(rollout["id"], area["id"], name="S")

        killed = validate_success(
            api.kill_store(
                store["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        assert killed["status"] == "KILLED"

        # KILLED is terminal: a second kill has no defined transition.
        resp = api.kill_store(
            store["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestKillCascade:
    def test_store_kill_releases_assignment_routes_and_capital(self, api):
        """PRD §3.3: "The kill cascades: the store's `ACTIVE` DC assignment, if
        any, becomes `SUPERSEDED` and the affected distribution center's
        `assigned_store_count` decreases by 1; the store's `ACTIVE` route plan,
        if any, becomes `SUPERSEDED`; and any opening plan in `PLANNED` or
        `LOCKED` status is `CANCELLED`. When the killed store was
        `UNDER_CONSTRUCTION`, the program's `committed_capital_cents`
        additionally decreases by exactly the store's `build_cost_cents`,
        releasing the construction commitment."

        Design: Difficulty/transitive_cascade/store_kill_releases_assignment_routes_and_capital
        """
        rollout = create_active_rollout(name="P", new_build_capital_budget_cents=1000000000)
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer, agreement = setup_store_under_construction(
            rollout["id"], store["id"]
        )
        dc = create_distribution_center(rollout["id"], name="D", store_capacity=2)
        assignment = create_dc_assignment(
            rollout["id"], store["id"], dc["id"], stem_miles=90, deliveries_per_week=1
        )
        plan = create_route_plan(rollout["id"], store["id"])

        # Kill precondition: no open agreement.  Terminate first (which itself
        # releases the construction commitment and the developer slot).
        validate_success(
            api.terminate_agreement(
                agreement["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )

        killed = validate_success(
            api.kill_store(
                store["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        assert killed["status"] == "KILLED"

        assignment_after = get_success_data(
            api.get_dc_assignment(assignment["id"], NETWORK)
        )
        assert assignment_after["status"] == "SUPERSEDED"
        dc_after = get_success_data(api.get_distribution_center(dc["id"], NETWORK))
        assert dc_after["assigned_store_count"] == 0
        plan_after = get_success_data(api.get_route_plan(plan["id"], NETWORK))
        assert plan_after["status"] == "SUPERSEDED"
        # Build cost was committed at activate and released at terminate; the
        # kill adds no drift.
        assert read_rollout(rollout["id"])["committed_capital_cents"] == 0

    def test_kill_cancels_planned_opening_plan(self, api):
        """PRD §3.3: "any opening plan in `PLANNED` or `LOCKED` status is
        `CANCELLED`."

        Design: Difficulty/transitive_cascade/store_kill_releases_assignment_routes_and_capital
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer, agreement = setup_store_site_control(rollout["id"], store["id"])
        plan = create_opening_plan(rollout["id"], store["id"], "2026-12-05T00:00:00Z")
        lock_opening_plan(rollout["id"], plan["id"])

        validate_success(
            api.terminate_agreement(
                agreement["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        killed = validate_success(
            api.kill_store(
                store["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        assert killed["status"] == "KILLED"
        plan_after = get_success_data(api.get_opening_plan(plan["id"], OPERATIONS))
        assert plan_after["status"] == "CANCELLED"


class TestCapitalCommitReleaseInvariant:
    def test_capital_commit_release_invariant(self, api):
        """PRD §2.6: "Killing an `UNDER_CONSTRUCTION` store or terminating an
        `ACTIVE` agreement must release exactly the store's `build_cost_cents`
        — no more, no less."
        PRD §3.4: "Activation then moves the agreement `EXECUTED → ACTIVE`: ...
        and commits capital — the program's `committed_capital_cents` increases
        by the store's `build_cost_cents`."

        Design: Difficulty/compensating_invariant/capital_commit_release_invariant
        """
        rollout = create_active_rollout(name="P", new_build_capital_budget_cents=1000000000)
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer, agreement = setup_store_under_construction(
            rollout["id"], store["id"]
        )
        mid = read_rollout(rollout["id"])
        assert mid["committed_capital_cents"] == 350000000
        assert mid["available_capital_cents"] == 650000000

        validate_success(
            api.terminate_agreement(
                agreement["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        after = read_rollout(rollout["id"])
        assert after["committed_capital_cents"] == 0
        assert after["available_capital_cents"] == 1000000000

    def test_capital_conserved_across_commit_and_release(self, api):
        """PRD §2.6: "The invariant — committed plus available equals budget —
        holds at every instant, with no drift permitted."

        Design: Difficulty/compensating_invariant/capital_commit_release_invariant
        """
        rollout = create_active_rollout(name="P", new_build_capital_budget_cents=1000000000)
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer, agreement = setup_store_site_control(rollout["id"], store["id"])

        # Before activation nothing is committed.
        before = read_rollout(rollout["id"])
        assert before["committed_capital_cents"] == 0
        assert (
            before["committed_capital_cents"] + before["available_capital_cents"]
            == before["new_build_capital_budget_cents"]
        )

        activate_agreement(rollout["id"], agreement["id"])
        committed = read_rollout(rollout["id"])
        assert (
            committed["committed_capital_cents"] + committed["available_capital_cents"]
            == committed["new_build_capital_budget_cents"]
        )

        validate_success(
            api.terminate_agreement(
                agreement["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        released = read_rollout(rollout["id"])
        assert (
            released["committed_capital_cents"] + released["available_capital_cents"]
            == released["new_build_capital_budget_cents"]
        )
        assert released["committed_capital_cents"] == 0


class TestDeveloperSlotInvariant:
    def test_developer_slot_release_invariant(self, api):
        """PRD §3.4: "Activation then moves the agreement `EXECUTED → ACTIVE`:
        ... increments that count by 1"
        PRD §3.4: "Delivery releases the developer slot —
        `active_agreement_count` decreases by 1"

        Design: Difficulty/compensating_invariant/developer_slot_release_invariant
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer, agreement = setup_store_site_control(rollout["id"], store["id"])

        activate_agreement(rollout["id"], agreement["id"])
        mid = get_success_data(api.get_developer(developer["id"], ADMIN))
        assert mid["active_agreement_count"] == 1

        delivered = record_delivery(
            rollout["id"], agreement["id"], "2026-11-01T00:00:00Z"
        )
        assert delivered["late_days"] == 0
        assert delivered["penalty_cents"] == 0
        after = get_success_data(api.get_developer(developer["id"], ADMIN))
        assert after["active_agreement_count"] == 0

    def test_activate_then_terminate_releases_slot(self, api):
        """PRD §3.4: "Terminating from `ACTIVE` additionally decrements the
        developer's `active_agreement_count` by 1"

        Design: Difficulty/compensating_invariant/developer_slot_release_invariant
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="C")
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        developer, agreement = setup_store_under_construction(
            rollout["id"], store["id"]
        )
        mid = get_success_data(api.get_developer(developer["id"], ADMIN))
        assert mid["active_agreement_count"] == 1
        validate_success(
            api.terminate_agreement(
                agreement["id"], {"rollout_program_id": rollout["id"]}, REAL_ESTATE
            ),
            200,
        )
        after = get_success_data(api.get_developer(developer["id"], ADMIN))
        assert after["active_agreement_count"] == 0


class TestOpeningExecution:
    def test_activate_deliver_open_happy_path(self, api):
        """PRD §3.6: "Execution cascades across three records: the agreement
        moves `DELIVERED → COMPLETED` and its accrued `penalty_cents` posts to
        the program ledger as a penalty credit available to `NEW_BUILD` capital
        scoring; the store moves `DELIVERED → OPEN`; and a `STORE_OPENED` event
        is appended to the program log with the opening date in its payload."

        Design: Corner/state_machines/activate_deliver_open_happy_path
        """
        rollout, store, developer, agreement, plan = _open_store(api)
        executed = validate_success(
            api.execute_opening_plan(
                plan["id"], {"rollout_program_id": rollout["id"]}, OPERATIONS
            ),
            200,
        )
        assert executed["status"] == "EXECUTED"
        assert read_store(store["id"])["status"] == "OPEN"
        agreement_after = get_success_data(
            api.get_site_agreement(agreement["id"], REAL_ESTATE)
        )
        assert agreement_after["status"] == "COMPLETED"
        assert agreement_after["penalty_cents"] == 0

        resp = api.list_program_events(
            ADMIN, params={"rollout_program_id": rollout["id"]}
        )
        events, _meta = validate_paginated(resp)
        opened = [e for e in events if e["event_type"] == "STORE_OPENED"]
        assert len(opened) == 1
        assert opened[0]["store_id"] == store["id"]

    def test_executed_store_terminal_lockdown(self, api):
        """PRD §2.11: "state legality — the target resource must be in a state
        from which the requested transition is defined, else
        `ERR_INVALID_STATE`"
        PRD §3.6: "Execution performs the grand opening, moving the plan
        `LOCKED → EXECUTED`."

        Design: Corner/state_machines/executed_store_terminal_lockdown
        """
        rollout, store, developer, agreement, plan = _open_store(api)
        validate_success(
            api.execute_opening_plan(
                plan["id"], {"rollout_program_id": rollout["id"]}, OPERATIONS
            ),
            200,
        )
        # A second execute has no defined transition from EXECUTED.
        resp = api.execute_opening_plan(
            plan["id"], {"rollout_program_id": rollout["id"]}, OPERATIONS
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert read_store(store["id"])["status"] == "OPEN"
        agreement_after = get_success_data(
            api.get_site_agreement(agreement["id"], REAL_ESTATE)
        )
        assert agreement_after["status"] == "COMPLETED"


class TestValidationOrdering:
    def test_role_gate_beats_not_found(self, api):
        """PRD §2.11: "(1) authentication ...; (2) authorization — the role
        must be permitted on this endpoint, else `ERR_FORBIDDEN`; (3) path
        existence — path resources must exist and chain correctly, else
        `ERR_NOT_FOUND`"
        PRD §4: the store select-format endpoint is authorized for
        REAL_ESTATE_MANAGER only.

        Design: Corner/validations/role_gate_beats_not_found
        """
        rollout = create_active_rollout(name="P")
        area = create_qualified_trade_area(rollout["id"], name="A")
        store = create_store(rollout["id"], area["id"], name="Real")
        # FINANCE_ANALYST may not call select-format; the role gate fires
        # before the nonexistent store id is examined.
        resp = api.select_format(
            NON_EXISTENT_UUID,
            {
                "rollout_program_id": rollout["id"],
                "expected_store_version": store["version"],
            },
            FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
