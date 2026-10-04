"""Pre-positioned assets and allocations: the 48h window, kind matching,
return gating, and the return/redeploy conservation cycle."""
from test_helpers import (
    ApiErrorId,
    assert_asset,
    assert_asset_allocation,
    create_allocation,
    create_asset,
    create_storm,
    create_unit_for,
    file_condition_report,
    get_unit,
    set_clock,
    setup_asset_scenario,
    setup_storm_with_unit,
    LP,
    UM,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPrepositionWindow:
    def test_preposition_window_inclusive_at_48h(self, api, logistics_planner_headers):
        """PRD §3.4: "The window boundary is inclusive — an allocation at
        exactly `watch_started_at` plus forty-eight hours is accepted, one
        second later is rejected with `ERR_PREPOSITION_WINDOW_EXPIRED`."

        Design: Corner/calculations/preposition_window_inclusive_at_48h
        """
        ctx = setup_asset_scenario(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        g1 = ctx["asset"]
        g2 = create_asset(uid, kind="GENERATOR")
        # watch_started_at == 2026-09-10T08:00:00Z; +48h == 2026-09-12T08:00:00Z.
        set_clock("2026-09-12T08:00:00Z")
        al1 = create_allocation(g1["id"], uid)
        assert_asset_allocation(al1)
        assert al1["status"] == "RESERVED"
        set_clock("2026-09-12T08:00:01Z")
        resp = api.create_allocation({"asset_id": g2["id"], "unit_id": uid},
                                     logistics_planner_headers)
        validate_error(resp, ApiErrorId.ERR_PREPOSITION_WINDOW_EXPIRED)
        asset_after = validate_success(api.get_asset(g2["id"], logistics_planner_headers))
        assert asset_after["status"] == "IDLE"

    def test_asset_not_idle_beats_preposition_window_expired(self, api, logistics_planner_headers):
        """PRD §2.8: "Across the whole API, request validation proceeds in a
        fixed priority order, and an earlier failure masks every later one:"
        PRD §2.8: "7. Cross-entity referential rules — storm posture for
        assignment start, relief-org standing, crew-member availability, asset
        idleness."
        PRD §2.8: "8. Temporal rules — pre-positioning window, assignment
        overlap and window, lodging night overlap, pledge service-day gating."

        Design: Difficulty/priority_pair_validation_conflict/asset_not_idle_beats_preposition_window_expired
        """
        ctx = setup_asset_scenario(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        g = ctx["asset"]
        create_allocation(g["id"], uid)
        # Past watch_started_at + 48h while the storm is still WATCH: the
        # request violates BOTH the idleness rule and the window.
        set_clock("2026-09-13T08:01:00Z")
        resp = api.create_allocation({"asset_id": g["id"], "unit_id": uid},
                                     logistics_planner_headers)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_IDLE)
        asset_after = validate_success(api.get_asset(g["id"], logistics_planner_headers))
        assert asset_after["status"] == "ALLOCATED"
        _, meta = validate_paginated(api.list_asset_allocations(g["id"], logistics_planner_headers))
        assert meta["total_count"] == 1, "no second allocation may be created"

    def test_non_idle_asset_rejected_even_inside_window(self, api, logistics_planner_headers):
        """PRD §3.4: "First, the asset must be `IDLE`; otherwise
        `ERR_ASSET_NOT_IDLE`."
        PRD §2.8: "7. Cross-entity referential rules — storm posture for
        assignment start, relief-org standing, crew-member availability, asset
        idleness."

        Design: Difficulty/priority_pair_validation_conflict/asset_not_idle_beats_preposition_window_expired
        """
        ctx = setup_asset_scenario(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        g = ctx["asset"]
        create_allocation(g["id"], uid)
        # Still well inside the window — the idleness gate fires on its own.
        resp = api.create_allocation({"asset_id": g["id"], "unit_id": uid},
                                     logistics_planner_headers)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_IDLE)
        asset_after = validate_success(api.get_asset(g["id"], logistics_planner_headers))
        assert asset_after["status"] == "ALLOCATED"


class TestAssetKindMatching:
    def test_asset_kind_mismatch_rejected(self, api, logistics_planner_headers):
        """PRD §3.4: "Third, the asset kind must match the unit's outage: a
        `GENERATOR` may only be sent to a unit whose power axis is `DOWN`, and
        a `MOBILE_KITCHEN` only to a unit whose water axis or gas axis (or
        both) is `DOWN`; any other pairing is rejected with
        `ERR_ASSET_KIND_MISMATCH`."

        Design: Corner/validations/asset_kind_mismatch_rejected
        """
        ctx = setup_asset_scenario(
            clock="2026-09-10T08:00:00Z", kind="MOBILE_KITCHEN",
            report_axes={"power": "DOWN", "water": "UP", "gas": "UP",
                         "payment_network": "UP"},
        )
        resp = api.create_allocation(
            {"asset_id": ctx["asset"]["id"], "unit_id": ctx["unit"]["id"]},
            logistics_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSET_KIND_MISMATCH)
        asset = validate_success(api.get_asset(ctx["asset"]["id"], logistics_planner_headers))
        assert asset["status"] == "IDLE"


class TestReturnGatingAndRedeploy:
    def test_asset_return_blocked_while_unit_limited(self, api, logistics_planner_headers):
        """PRD §3.4: "Return moves a `DEPLOYED` allocation to `RETURNED`,
        stamps `returned_at`, and cascades the asset to `RETURNED` — but only
        once the unit is back on its full menu: returning while the unit's
        `menu_tier` is anything other than `FULL` is rejected with
        `ERR_UNIT_STILL_LIMITED`."

        Design: Corner/validations/asset_return_blocked_while_unit_limited
        """
        ctx = setup_asset_scenario(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        al = create_allocation(ctx["asset"]["id"], uid)
        al = validate_success(api.dispatch_allocation(al["id"], None, logistics_planner_headers))
        assert al["status"] == "DEPLOYED"
        resp = api.return_allocation(al["id"], None, logistics_planner_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_STILL_LIMITED)
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        al = validate_success(api.return_allocation(al["id"], None, logistics_planner_headers))
        assert al["status"] == "RETURNED"
        asset = validate_success(api.get_asset(ctx["asset"]["id"], logistics_planner_headers))
        assert asset["status"] == "RETURNED"

    def test_asset_return_redeploy_identity_conservation(self, api, logistics_planner_headers):
        """PRD §3.4: "The allocation machine is cyclic on the return path: a
        `RETURNED` allocation may be dispatched again to the same unit,
        re-stamping `dispatched_at`, and that re-dispatch cascades the asset
        from `RETURNED` back to `ALLOCATED`."
        PRD §3.4: "Return moves a `DEPLOYED` allocation to `RETURNED`, stamps
        `returned_at`, and cascades the asset to `RETURNED` — but only once the
        unit is back on its full menu: returning while the unit's `menu_tier`
        is anything other than `FULL` is rejected with `ERR_UNIT_STILL_LIMITED`."

        Design: Difficulty/compensating_invariant/asset_return_redeploy_identity_conservation
        """
        ctx = setup_asset_scenario(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        g = ctx["asset"]
        validate_success(
            api.create_menu_activation(uid, {"tier": "TIER1_NO_POWER"}, UM), 201
        )
        al = create_allocation(g["id"], uid)
        al = validate_success(api.dispatch_allocation(al["id"], None, logistics_planner_headers))
        assert al["status"] == "DEPLOYED"
        assert al["dispatched_at"] == "2026-09-10T08:00:00.000Z"
        set_clock("2026-09-10T10:00:00Z")
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        al = validate_success(api.return_allocation(al["id"], None, logistics_planner_headers))
        assert al["status"] == "RETURNED"
        assert al["returned_at"] == "2026-09-10T10:00:00.000Z"
        asset = validate_success(api.get_asset(g["id"], logistics_planner_headers))
        assert asset["status"] == "RETURNED"
        # Redeploy the returned allocation when the outage returns.
        set_clock("2026-09-10T11:00:00Z")
        file_condition_report(
            uid, power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        al = validate_success(api.dispatch_allocation(al["id"], None, logistics_planner_headers))
        assert al["status"] == "DEPLOYED"
        assert al["returned_at"] == "2026-09-10T10:00:00.000Z"
        assert al["dispatched_at"] == "2026-09-10T11:00:00.000Z", (
            "redeploy must restamp dispatched_at"
        )
        asset = validate_success(api.get_asset(g["id"], logistics_planner_headers))
        assert asset["status"] == "ALLOCATED"
        # Fleet cardinality conserved: exactly one asset and one allocation.
        _, assets_meta = validate_paginated(api.list_assets(logistics_planner_headers))
        assert assets_meta["total_count"] == 1
        _, allocs_meta = validate_paginated(
            api.list_asset_allocations(g["id"], logistics_planner_headers)
        )
        assert allocs_meta["total_count"] == 1

    def test_redeploy_does_not_create_new_allocation(self, api, logistics_planner_headers):
        """PRD §3.4: "The allocation machine is cyclic on the return path: a
        `RETURNED` allocation may be dispatched again to the same unit,
        re-stamping `dispatched_at`, and that re-dispatch cascades the asset
        from `RETURNED` back to `ALLOCATED`."

        Design: Difficulty/compensating_invariant/asset_return_redeploy_identity_conservation
        """
        ctx = setup_asset_scenario(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        g = ctx["asset"]
        al = create_allocation(g["id"], uid)
        api.dispatch_allocation(al["id"], None, logistics_planner_headers)
        set_clock("2026-09-10T10:00:00Z")
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        api.return_allocation(al["id"], None, logistics_planner_headers)
        al = validate_success(api.dispatch_allocation(al["id"], None, logistics_planner_headers))
        # Same allocation identity through the whole cycle.
        al_read = validate_success(api.get_allocation(al["id"], logistics_planner_headers))
        assert al_read["id"] == al["id"]
        assert al_read["status"] == "DEPLOYED"
        _, meta = validate_paginated(
            api.list_allocations(logistics_planner_headers, params={"status": "DEPLOYED"})
        )
        assert meta["total_count"] == 1
