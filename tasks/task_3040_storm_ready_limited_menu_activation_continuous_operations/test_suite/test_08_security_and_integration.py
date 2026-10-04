"""Authentication, authorization, segregation of duties, unit fiscal/version
behavior, and reverse-reachability collections."""
from test_helpers import (
    ApiErrorId,
    assert_cash_drop,
    build_user_headers,
    create_allocation,
    create_asset,
    create_crew_member,
    create_storm,
    create_unit_for,
    file_condition_report,
    LP,
    NON_EXISTENT_UUID,
    set_clock,
    setup_asset_scenario,
    setup_storm_with_unit,
    setup_submitted_checklist,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        string outside the five declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        set_clock("2026-09-10T08:00:00Z")
        resp = api.create_storm_event({"name": "Hurricane Delta"}, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorizationPriority:
    def test_role_denied_returns_forbidden_before_existence(self, api, unit_manager_headers):
        """PRD §2.1: "A well-formed request whose role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.8: "Across the whole API, request validation proceeds in a fixed
        priority order, and an earlier failure masks every later one:
        1. Authentication — headers present and role declared
        (`ERR_UNAUTHENTICATED`).
        2. Authorization — role permitted for the endpoint (`ERR_FORBIDDEN`).
        3. Existence — path identifiers exist and nest correctly, body foreign
        keys exist (`ERR_NOT_FOUND`)."

        Design: Corner/validations/role_denied_returns_forbidden_before_existence
        """
        set_clock("2026-09-10T08:00:00Z")
        # PATCH /ops/units/{id} is CommandCenterAdmin-only; UnitManager is
        # denied before the non-existent unit id is examined.
        resp = api.patch_unit(
            NON_EXISTENT_UUID, {"lodging_fund_top_up_cents": 5000}, unit_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestRoleExclusiveOperations:
    def test_unit_manager_cannot_review_checklists(self, api):
        """PRD §2.1: "`CommandCenterAdmin` is the hierarchical superset: it owns
        every storm-lifecycle, checklist-review, fund top-up, and
        reporting-cadence write, and it may read every resource in the system."
        PRD §2.1: "A well-formed request whose role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/unit_manager_cannot_review_checklists
        """
        ctx = setup_submitted_checklist()
        uid = ctx["unit"]["id"]
        run_id = ctx["run"]["id"]
        # A UnitManager who did NOT submit the run still cannot review it.
        other_um = build_user_headers("um-2", "UnitManager")
        resp = api.approve_checklist(uid, run_id, None, other_um)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        run = validate_success(api.get_checklist(uid, run_id, other_um))
        assert run["status"] == "SUBMITTED"

    def test_relief_coordinator_cannot_dispatch_assets(self, api, relief_coordinator_headers):
        """PRD §2.1: "The peer operations roles own disjoint write surfaces —
        `UnitManager` for unit condition, menu, checklist, and cash operations;
        `LogisticsPlanner` for assets and allocations; `FieldCoordinator` for
        crew, assignments, and lodging; `ReliefCoordinator` for relief
        organizations and pledges — with read access limited per the endpoint
        table in §4."
        PRD §2.1: "A well-formed request whose role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/relief_coordinator_cannot_dispatch_assets
        """
        ctx = setup_asset_scenario(clock="2026-09-10T08:00:00Z")
        al = create_allocation(ctx["asset"]["id"], ctx["unit"]["id"])
        resp = api.dispatch_allocation(al["id"], None, relief_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        al_after = validate_success(api.get_allocation(al["id"], LP))
        assert al_after["status"] == "RESERVED"

    def test_field_coordinator_cannot_file_condition_reports(self, api, field_coordinator_headers, unit_manager_headers):
        """PRD §2.1: "The peer operations roles own disjoint write surfaces —
        `UnitManager` for unit condition, menu, checklist, and cash operations;
        `LogisticsPlanner` for assets and allocations; `FieldCoordinator` for
        crew, assignments, and lodging; `ReliefCoordinator` for relief
        organizations and pledges — with read access limited per the endpoint
        table in §4."
        PRD §2.1: "A well-formed request whose role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/field_coordinator_cannot_file_condition_reports
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        resp = api.create_condition_report(
            uid,
            {"power": "DOWN", "water": "UP", "gas": "UP", "payment_network": "UP"},
            field_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        _, meta = validate_paginated(
            api.list_condition_reports(uid, unit_manager_headers)
        )
        assert meta["total_count"] == 0

    def test_logistics_planner_cannot_manage_relief_orgs(self, api, logistics_planner_headers, relief_coordinator_headers):
        """PRD §2.1: "The peer operations roles own disjoint write surfaces —
        `UnitManager` for unit condition, menu, checklist, and cash operations;
        `LogisticsPlanner` for assets and allocations; `FieldCoordinator` for
        crew, assignments, and lodging; `ReliefCoordinator` for relief
        organizations and pledges — with read access limited per the endpoint
        table in §4."
        PRD §2.1: "A well-formed request whose role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/logistics_planner_cannot_manage_relief_orgs
        """
        set_clock("2026-09-10T08:00:00Z")
        resp = api.create_relief_org(
            {"name": "Red Shield Relief", "contact_email": "ops@redshield.example"},
            logistics_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        _, meta = validate_paginated(api.list_relief_orgs(relief_coordinator_headers))
        assert meta["total_count"] == 0


class TestSegregationOfDuties:
    def test_submitter_cannot_approve_own_checklist_run(self, api):
        """PRD §3.5: "Approval and rejection are both gated by segregation of
        duties: the reviewing `CommandCenterAdmin`'s `X-User-ID` must differ
        from the run's `submitted_by_user_id`, or the review is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/submitter_cannot_approve_own_checklist_run
        """
        ctx = setup_submitted_checklist(submitter_id="um-1")
        uid = ctx["unit"]["id"]
        run_id = ctx["run"]["id"]
        # The right role with the same identity as the submitter is denied.
        same_identity_admin = build_user_headers("um-1", "CommandCenterAdmin")
        resp = api.approve_checklist(uid, run_id, None, same_identity_admin)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        run = validate_success(
            api.get_checklist(uid, run_id, build_user_headers("cc-9", "CommandCenterAdmin"))
        )
        assert run["status"] == "SUBMITTED"


class TestUnitFiscalAndVersion:
    def test_lodging_fund_top_up_via_patch(self, api, admin_headers):
        """PRD §3.1: "The command center can later top up the fund through a
        unit modification that accepts `lodging_fund_top_up_cents` and adds it
        to `lodging_fund_cents`, incrementing the unit's `version` by one."
        PRD §2.4: "`version` (integer): a system-managed counter that
        increments by one on every mutation and anchors the optimistic
        concurrency rules of §2.5."

        Design: Corner/endpoints/lodging_fund_top_up_via_patch
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        unit = validate_success(
            api.patch_unit(uid, {"lodging_fund_top_up_cents": 1000}, admin_headers)
        )
        assert unit["lodging_fund_cents"] == 1000
        unit = validate_success(
            api.patch_unit(uid, {"lodging_fund_top_up_cents": 2500}, admin_headers)
        )
        assert unit["lodging_fund_cents"] == 3500, "top-ups accumulate"
        assert unit["version"] == 3, "1 create + 2 top-ups"

    def test_version_increments_on_every_mutation(self, api, admin_headers, unit_manager_headers):
        """PRD §2.4: "`version` (integer): a system-managed counter that
        increments by one on every mutation and anchors the optimistic
        concurrency rules of §2.5."
        PRD §2.4: "`updated_at` (string): an ISO 8601 UTC timestamp refreshed
        on every mutation of the resource."
        PRD §3.2: "The server stamps `reported_at` from the logical clock,
        overwrites the unit's `resource_status` with the reported axes wholesale
        (each report may flip any subset of axes; there is no per-axis history
        on the unit itself, only the report log), and increments the unit's
        `version` by one."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        assert ctx["unit"]["version"] == 1
        previous_updated_at = ctx["unit"]["updated_at"]
        file_condition_report(
            uid, power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        # Menu activation is a child resource; it does not bump the unit.
        validate_success(
            api.create_menu_activation(uid, {"tier": "TIER1_NO_POWER"}, unit_manager_headers), 201
        )
        unit = validate_success(api.get_unit(uid, admin_headers))
        assert unit["version"] == 2
        assert unit["updated_at"] >= previous_updated_at
        previous_updated_at = unit["updated_at"]
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        unit = validate_success(
            api.patch_unit(uid, {"lodging_fund_top_up_cents": 500}, admin_headers)
        )
        assert unit["version"] == 4
        assert unit["updated_at"] >= previous_updated_at


class TestReverseReachability:
    def test_fk_reverse_reachability_collections_all_resolve(
        self, api, unit_manager_headers, field_coordinator_headers, logistics_planner_headers
    ):
        """PRD §4: "| GET | `/ops/units/{id}/condition-reports` | List a unit's
        condition reports | CommandCenterAdmin, UnitManager, LogisticsPlanner,
        FieldCoordinator |"
        PRD §4: "| GET | `/ops/units/{id}/crew-members` | List crew members
        whose home unit is this unit | CommandCenterAdmin, FieldCoordinator |"
        PRD §4: "| GET | `/ops/assets/{id}/allocations` | List allocations of
        one asset | CommandCenterAdmin, LogisticsPlanner |"
        PRD §4: "| GET | `/ops/units/{id}/lodging-bookings` | List lodging
        bookings paid by this unit's fund | CommandCenterAdmin,
        FieldCoordinator |"

        Design: Corner/endpoints/fk_reverse_reachability_collections_all_resolve
        """
        set_clock("2026-09-10T08:00:00Z")
        storm = create_storm(clock=None)
        u1 = create_unit_for(storm, unit_code="U-1", address="1 Storm Way")
        u2 = create_unit_for(storm, unit_code="U-2", address="2 Storm Way")
        file_condition_report(
            u1["id"], power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        member = create_crew_member(u1["id"])
        asset = create_asset(u1["id"], kind="GENERATOR")
        # Empty child collections resolve with 200 and total_count 0.
        _, meta = validate_paginated(
            api.list_condition_reports(u2["id"], unit_manager_headers)
        )
        assert meta["total_count"] == 0
        _, meta = validate_paginated(
            api.list_unit_crew_members(u1["id"], field_coordinator_headers)
        )
        assert meta["total_count"] == 1
        _, meta = validate_paginated(
            api.list_asset_allocations(asset["id"], logistics_planner_headers)
        )
        assert meta["total_count"] == 0
        _, meta = validate_paginated(
            api.list_unit_lodging_bookings(u1["id"], field_coordinator_headers)
        )
        assert meta["total_count"] == 0

    def test_storm_units_filtered_by_menu_tier(self, api, admin_headers):
        """PRD §2.3: "Several list endpoints accept additional filters named
        after the field they match — for example `status` on storm-event,
        checklist, pledge, assignment, allocation, booking, and crew lists,
        `menu_tier` on the per-storm unit list, `kind` on the asset list, and
        `is_jump_team` on the crew list."

        Design: Corner/endpoints/storm_units_filtered_by_menu_tier
        """
        set_clock("2026-09-10T08:00:00Z")
        storm = create_storm(clock=None)
        u1 = create_unit_for(storm, unit_code="U-1", address="1 Storm Way")
        u2 = create_unit_for(storm, unit_code="U-2", address="2 Storm Way")
        file_condition_report(
            u1["id"], power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        rows, meta = validate_paginated(
            api.list_storm_units(storm["id"], admin_headers,
                                 params={"menu_tier": "TIER1_NO_POWER"})
        )
        assert meta["total_count"] == 1
        assert [r["id"] for r in rows] == [u1["id"]]
        _, meta = validate_paginated(api.list_storm_units(storm["id"], admin_headers))
        assert meta["total_count"] == 2


class TestCashOnlyOperations:
    def test_cash_drop_second_record_succeeds_but_blocked_when_not_cash_only(
        self, api, unit_manager_headers
    ):
        """PRD §3.6: "Drops are accepted only while `cash_only_flag` is true;
        attempting one while card tenders are still live is rejected with
        `ERR_NOT_CASH_ONLY`. Each accepted drop is stamped with `recorded_at`
        from the logical clock. Drops are append-only records: they carry no
        `updated_at` and no `version`."

        Design: Corner/state_machines/cash_drop_second_record_succeeds_but_blocked_when_not_cash_only
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="DOWN"
        )
        d1 = validate_success(
            api.create_cash_drop(
                uid, {"amount_cents": 5000, "shift_lead_note": "drawer skim 1"},
                unit_manager_headers,
            ),
            201,
        )
        assert_cash_drop(d1)
        assert d1["recorded_at"] == "2026-09-10T08:00:00.000Z"
        # Restoring the payment network flips the flag and blocks the next drop.
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        resp = api.create_cash_drop(
            uid, {"amount_cents": 2500, "shift_lead_note": "drawer skim 2"},
            unit_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_CASH_ONLY)
        _, meta = validate_paginated(api.list_cash_drops(uid, unit_manager_headers))
        assert meta["total_count"] == 1
