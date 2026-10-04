"""Condition reports, the parallel resource axes, menu-tier derivation, the
cash-only fallback, and the menu-activation lifecycle."""
from test_helpers import (
    ApiErrorId,
    assert_menu_activation,
    create_storm,
    create_unit_for,
    file_condition_report,
    get_unit,
    set_clock,
    setup_storm_with_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestParallelAxes:
    def test_triple_outage_plus_payment_down_yields_tier1_and_cash_only(self, api, admin_headers):
        """PRD §3.2: "Otherwise, power dominates: if power is `DOWN`, the tier is
        `TIER1_NO_POWER`, the generator-backed grill-only menu."
        PRD §3.2: "The payment axis alone drives `cash_only_flag`: the flag is
        set true while `payment_network` is `DOWN` and false while it is `UP`."

        Design: Difficulty/dual_variant_calc/menu_tier_priority_vs_cash_only_axis
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="DOWN", water="DOWN", gas="DOWN", payment_network="DOWN"
        )
        unit = validate_success(api.get_unit(uid, admin_headers))
        assert unit["menu_tier"] == "TIER1_NO_POWER", (
            f"power DOWN must dominate water and gas, got {unit['menu_tier']}"
        )
        assert unit["cash_only_flag"] is True
        assert unit["resource_status"] == {
            "power": "DOWN", "water": "DOWN", "gas": "DOWN", "payment_network": "DOWN"
        }

    def test_power_only_outage_keeps_cash_only_false(self, api, admin_headers):
        """PRD §3.2: "The payment-network axis plays no role whatsoever in the
        tier derivation."
        PRD §3.2: "The payment axis alone drives `cash_only_flag`: the flag is
        set true while `payment_network` is `DOWN` and false while it is `UP`."

        Design: Difficulty/dual_variant_calc/menu_tier_priority_vs_cash_only_axis
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="DOWN", water="DOWN", gas="DOWN", payment_network="UP"
        )
        unit = validate_success(api.get_unit(uid, admin_headers))
        assert unit["menu_tier"] == "TIER1_NO_POWER"
        assert unit["cash_only_flag"] is False, (
            "payment UP must leave cash_only_flag false even with three axes DOWN"
        )

    def test_water_axis_flips_independently_of_power_and_gas(self, api, admin_headers):
        """PRD §3.2: "If power is `UP` but water is `DOWN`, the tier is
        `TIER2_NO_WATER`, the no-fountain bottled-beverage menu."
        PRD §3.2: "The server stamps `reported_at` from the logical clock,
        overwrites the unit's `resource_status` with the reported axes wholesale
        (each report may flip any subset of axes; there is no per-axis history
        on the unit itself, only the report log), and increments the unit's
        `version` by one."

        Design: Difficulty/non_linear_state_machine/unit_resource_parallel_axes
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="UP", water="DOWN", gas="UP", payment_network="UP"
        )
        unit = validate_success(api.get_unit(uid, admin_headers))
        assert unit["menu_tier"] == "TIER2_NO_WATER"
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        unit = validate_success(api.get_unit(uid, admin_headers))
        assert unit["menu_tier"] == "FULL"
        assert unit["resource_status"]["power"] == "UP"
        assert unit["resource_status"]["gas"] == "UP"

    def test_gas_axis_flips_independently_to_tier3(self, api, admin_headers):
        """PRD §3.2: "If power and water are `UP` but gas is `DOWN`, the tier is
        `TIER3_NO_GAS`, the electric-griddle-only menu."
        PRD §3.2: "The server stamps `reported_at` from the logical clock,
        overwrites the unit's `resource_status` with the reported axes wholesale
        (each report may flip any subset of axes; there is no per-axis history
        on the unit itself, only the report log), and increments the unit's
        `version` by one."

        Design: Difficulty/non_linear_state_machine/unit_resource_parallel_axes
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="UP", water="UP", gas="DOWN", payment_network="UP"
        )
        unit = validate_success(api.get_unit(uid, admin_headers))
        assert unit["menu_tier"] == "TIER3_NO_GAS"
        assert unit["resource_status"]["power"] == "UP"
        assert unit["resource_status"]["water"] == "UP"
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        unit = validate_success(api.get_unit(uid, admin_headers))
        assert unit["menu_tier"] == "FULL"


class TestMenuTierDerivation:
    def test_water_down_without_power_yields_tier2(self, api, admin_headers):
        """PRD §3.2: "Otherwise, power dominates: if power is `DOWN`, the tier is
        `TIER1_NO_POWER`, the generator-backed grill-only menu. If power is `UP`
        but water is `DOWN`, the tier is `TIER2_NO_WATER`, the no-fountain
        bottled-beverage menu. If power and water are `UP` but gas is `DOWN`,
        the tier is `TIER3_NO_GAS`, the electric-griddle-only menu."

        Design: Corner/calculations/menu_tier_water_down_without_power_yields_tier2
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="UP", water="DOWN", gas="DOWN", payment_network="UP"
        )
        unit = validate_success(api.get_unit(uid, admin_headers))
        assert unit["menu_tier"] == "TIER2_NO_WATER", (
            f"water outranks gas when power is UP, got {unit['menu_tier']}"
        )


class TestCashOnlyAxis:
    def test_cash_only_flag_derives_from_payment_axis_only(self, api, admin_headers):
        """PRD §3.2: "The payment axis alone drives `cash_only_flag`: the flag
        is set true while `payment_network` is `DOWN` and false while it is
        `UP`."
        PRD §3.2: "The payment-network axis plays no role whatsoever in the
        tier derivation."

        Design: Corner/cross_cutting_layers/cash_only_flag_derives_from_payment_axis_only
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="DOWN", water="DOWN", gas="DOWN", payment_network="UP"
        )
        assert validate_success(api.get_unit(uid, admin_headers))["cash_only_flag"] is False
        file_condition_report(
            uid, power="DOWN", water="DOWN", gas="DOWN", payment_network="DOWN"
        )
        assert validate_success(api.get_unit(uid, admin_headers))["cash_only_flag"] is True
        file_condition_report(
            uid, power="DOWN", water="DOWN", gas="DOWN", payment_network="UP"
        )
        unit = validate_success(api.get_unit(uid, admin_headers))
        assert unit["cash_only_flag"] is False
        assert unit["menu_tier"] == "TIER1_NO_POWER"

    def test_cascade_visible_immediately_in_same_read(self, api, admin_headers):
        """PRD §3.2: "The server stamps `reported_at` from the logical clock,
        overwrites the unit's `resource_status` with the reported axes wholesale
        (each report may flip any subset of axes; there is no per-axis history
        on the unit itself, only the report log), and increments the unit's
        `version` by one."
        PRD §3.2: "If power is `UP` but water is `DOWN`, the tier is
        `TIER2_NO_WATER`, the no-fountain bottled-beverage menu."

        Design: Corner/consistency_model/cascade_visible_immediately_in_same_read
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        assert ctx["unit"]["version"] == 1
        file_condition_report(
            uid, power="UP", water="DOWN", gas="UP", payment_network="DOWN"
        )
        unit = validate_success(api.get_unit(uid, admin_headers))
        assert unit["menu_tier"] == "TIER2_NO_WATER"
        assert unit["cash_only_flag"] is True
        assert unit["version"] == 2, (
            f"one condition report must bump the unit version by exactly 1, got {unit['version']}"
        )


class TestMenuActivationLifecycle:
    def test_menu_activation_on_unaffected_unit_rejected(self, api, unit_manager_headers):
        """PRD §3.3: "Activation is only meaningful on a storm-affected unit:
        if the unit's current `menu_tier` is `FULL`, the request is rejected
        with `ERR_UNIT_NOT_STORM_AFFECTED`."

        Design: Corner/validations/menu_activation_on_unaffected_unit_rejected
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        resp = api.create_menu_activation(uid, {"tier": "TIER1_NO_POWER"}, unit_manager_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_STORM_AFFECTED)
        _, meta = validate_paginated(api.list_menu_activations(uid, unit_manager_headers))
        assert meta["total_count"] == 0

    def test_condition_report_cascade_ends_activation_and_sets_cash_only(self, api, unit_manager_headers):
        """PRD §3.2: "If the unit holds a storm-tier menu activation in `ACTIVE`
        status whose `tier` no longer equals the recomputed `menu_tier` —
        including when the recomputed tier is `FULL` — that activation is ended
        automatically: it transitions to `ENDED` with `ended_at` stamped from
        the logical clock."
        PRD §3.2: "If power is `UP` but water is `DOWN`, the tier is
        `TIER2_NO_WATER`, the no-fountain bottled-beverage menu."

        Design: Difficulty/transitive_cascade/condition_report_cascade_ends_activation_and_sets_cash_only
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T09:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="UP", water="UP", gas="DOWN", payment_network="UP"
        )
        ma = validate_success(
            api.create_menu_activation(uid, {"tier": "TIER3_NO_GAS"}, unit_manager_headers), 201
        )
        assert_menu_activation(ma)
        file_condition_report(
            uid, power="UP", water="DOWN", gas="DOWN", payment_network="UP"
        )
        activations, _ = validate_paginated(
            api.list_menu_activations(uid, unit_manager_headers)
        )
        ended = [a for a in activations if a["id"] == ma["id"]]
        assert len(ended) == 1
        assert ended[0]["status"] == "ENDED", (
            f"tier mismatch TIER3 -> TIER2 must end the activation, got {ended[0]['status']}"
        )
        unit = validate_success(api.get_unit(uid, unit_manager_headers))
        assert unit["menu_tier"] == "TIER2_NO_WATER"
        assert unit["cash_only_flag"] is False

    def test_all_clear_report_ends_active_activation_to_full(self, api, unit_manager_headers):
        """PRD §3.2: "If the unit holds a storm-tier menu activation in `ACTIVE`
        status whose `tier` no longer equals the recomputed `menu_tier` —
        including when the recomputed tier is `FULL` — that activation is ended
        automatically: it transitions to `ENDED` with `ended_at` stamped from
        the logical clock."

        Design: Difficulty/transitive_cascade/condition_report_cascade_ends_activation_and_sets_cash_only
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T09:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        ma = validate_success(
            api.create_menu_activation(uid, {"tier": "TIER1_NO_POWER"}, unit_manager_headers), 201
        )
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        activations, _ = validate_paginated(
            api.list_menu_activations(uid, unit_manager_headers)
        )
        assert activations[0]["id"] == ma["id"]
        assert activations[0]["status"] == "ENDED", (
            "recomputed FULL mismatches the TIER1 activation, so it must end"
        )
        assert validate_success(api.get_unit(uid, unit_manager_headers))["menu_tier"] == "FULL"

    def test_menu_activation_supersede_ends_previous_activation(self, api, unit_manager_headers):
        """PRD §3.3: "If the unit already has an activation in `ACTIVE` status,
        the existing one is superseded: it transitions to `SUPERSEDED` and its
        `ended_at` is stamped at the same moment."
        PRD §3.2: "If the unit holds a storm-tier menu activation in `ACTIVE`
        status whose `tier` no longer equals the recomputed `menu_tier` —
        including when the recomputed tier is `FULL` — that activation is ended
        automatically: it transitions to `ENDED` with `ended_at` stamped from
        the logical clock."

        Design: Corner/state_machines/menu_activation_supersede_ends_previous_activation
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="UP", water="UP", gas="DOWN", payment_network="UP"
        )
        ma1 = validate_success(
            api.create_menu_activation(uid, {"tier": "TIER3_NO_GAS"}, unit_manager_headers), 201
        )
        set_clock("2026-09-10T09:00:00Z")
        # The recomputed TIER2 tier mismatches the ACTIVE TIER3 activation,
        # so the report ends it.
        file_condition_report(
            uid, power="UP", water="DOWN", gas="DOWN", payment_network="UP"
        )
        ma2 = validate_success(
            api.create_menu_activation(uid, {"tier": "TIER2_NO_WATER"}, unit_manager_headers), 201
        )
        activations, meta = validate_paginated(
            api.list_menu_activations(uid, unit_manager_headers)
        )
        by_id = {a["id"]: a for a in activations}
        assert by_id[ma1["id"]]["status"] == "ENDED"
        assert by_id[ma1["id"]]["ended_at"] == "2026-09-10T09:00:00.000Z"
        assert by_id[ma2["id"]]["status"] == "ACTIVE"
        assert by_id[ma2["id"]]["tier"] == "TIER2_NO_WATER"
        active = [a for a in activations if a["status"] == "ACTIVE"]
        assert len(active) == 1, "exactly one ACTIVE activation may exist"

    def test_menu_deactivate_uses_occ_and_ends_active_activation(self, api, unit_manager_headers):
        """PRD §3.3: "The explicit path takes `expected_unit_version` per §2.5 —
        a mismatch yields `ERR_STALE_VERSION` — and on success the active
        activation transitions to `ENDED` with `ended_at` stamped and the
        unit's `version` incremented by one."

        Design: Corner/state_machines/menu_deactivate_uses_occ_and_ends_active_activation
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        ma = validate_success(
            api.create_menu_activation(uid, {"tier": "TIER1_NO_POWER"}, unit_manager_headers), 201
        )
        unit = validate_success(api.get_unit(uid, unit_manager_headers))
        unit_version = unit["version"]
        resp = api.deactivate_menu_activation(
            uid, {"expected_unit_version": unit_version - 1}, unit_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        resp = api.deactivate_menu_activation(
            uid, {"expected_unit_version": unit_version}, unit_manager_headers
        )
        validate_success(resp)
        activations, _ = validate_paginated(
            api.list_menu_activations(uid, unit_manager_headers)
        )
        assert activations[0]["id"] == ma["id"]
        assert activations[0]["status"] == "ENDED"
        assert activations[0]["ended_at"] is not None
        unit_after = validate_success(api.get_unit(uid, unit_manager_headers))
        assert unit_after["version"] == unit_version + 1
