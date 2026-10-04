"""Markdown cadence: per-SKU single-step sweeps, clearance floor, event audit,
and the clearance-outlet cadence skip."""
import pytest

from test_helpers import (
    TEST_USERS,
    setup_floor_sku,
    set_clock,
    validate_paginated,
    validate_success,
)

STORE_OPS = TEST_USERS["store_ops_lead_headers"]


class TestMarkdownCadenceAndClearanceFloor:
    def test_cadence_steps_then_force_clearance_preserve_floor(self, api):
        """PRD §3.7: "Short of clearance, whenever `weeks_on_floor` reaches the
        next cadence boundary — at least `markdown_step` + 1 times the zone's
        `markdown_cadence_weeks` — exactly one step is applied per sweep per SKU
        even if several boundaries were crossed: the new price is the current
        price reduced by the 20% step rate (multiplier 0.80), rounded half-up
        and 9-ending-adjusted". PRD §3.7: "when `weeks_on_floor` reaches the
        zone's `clearance_weeks`, the SKU moves to `CLEARANCE` and its price
        becomes 30% of the base price — the clearance floor multiplier is
        0.30 — rounded half-up and adjusted down to a 9-ending price".

        Design: Difficulty/compensating_invariant/markdown_step_and_force_clearance_preserve_price_floor
        """
        env = setup_floor_sku(units_on_hand=50, target_retail_cents=10_000)
        sku_id = env["sku"]["id"]
        assert env["sku"]["current_price_cents"] == 9_999
        set_clock("2026-09-29T00:00:00Z")
        set_clock("2026-10-27T00:00:00Z")
        sku = validate_success(api.get_store_sku(sku_id, STORE_OPS))
        assert sku["markdown_step"] == 2
        assert sku["current_price_cents"] == 6_399
        set_clock("2026-11-24T00:00:00Z")
        sku = validate_success(api.get_store_sku(sku_id, STORE_OPS))
        assert sku["status"] == "CLEARANCE"
        assert sku["current_price_cents"] == 2_999

    def test_every_price_change_witnessed_by_one_event(self, api):
        """PRD §3.7: "Each event records the `store_sku_id`, the `step_number`,
        `old_price_cents`, `new_price_cents`, the `markdown_cents` difference,
        the event type, and the `effective_date` from the logical clock".

        Design: Difficulty/compensating_invariant/markdown_step_and_force_clearance_preserve_price_floor
        """
        env = setup_floor_sku(units_on_hand=50, target_retail_cents=10_000)
        sku_id = env["sku"]["id"]
        set_clock("2026-09-29T00:00:00Z")
        set_clock("2026-10-27T00:00:00Z")
        set_clock("2026-11-24T00:00:00Z")
        events, _meta = validate_paginated(api.list_store_sku_markdown_events(sku_id, STORE_OPS))
        assert len(events) == 3
        assert [e["event_type"] for e in events] == ["CADENCE", "CADENCE", "FORCE_CLEARANCE"]
        for e in events:
            assert e["markdown_cents"] == e["old_price_cents"] - e["new_price_cents"]


class TestOpsCheckpoint:
    def test_single_step_per_sweep_across_multiple_boundaries(self, api):
        """PRD §3.7: "exactly one step is applied per sweep per SKU even if
        several boundaries were crossed". PRD §3.7: "`weeks_on_floor` is the
        whole-day difference between today and `floor_date`, divided by 7 and
        rounded down."

        Design: Corner/cross_cutting_layers/markdown_sweep_ops_checkpoint_on_clock_advance
        """
        env = setup_floor_sku(units_on_hand=10, target_retail_cents=10_000)
        sku_id = env["sku"]["id"]
        set_clock("2026-11-03T00:00:00Z")
        sku = validate_success(api.get_store_sku(sku_id, STORE_OPS))
        assert sku["weeks_on_floor"] == 9
        assert sku["markdown_step"] == 1
        assert sku["current_price_cents"] == 7_999
        events, _meta = validate_paginated(api.list_store_sku_markdown_events(sku_id, STORE_OPS))
        assert len(events) == 1

    def test_no_step_before_first_cadence_boundary(self, api):
        """PRD §3.7: "whenever `weeks_on_floor` reaches the next cadence
        boundary — at least `markdown_step` + 1 times the zone's
        `markdown_cadence_weeks`" — below the boundary nothing changes.

        Design: Corner/cross_cutting_layers/markdown_sweep_ops_checkpoint_on_clock_advance
        """
        env = setup_floor_sku(units_on_hand=10, target_retail_cents=10_000)
        sku_id = env["sku"]["id"]
        set_clock("2026-09-28T00:00:00Z")  # 27 days -> 3 weeks < cadence 4
        sku = validate_success(api.get_store_sku(sku_id, STORE_OPS))
        assert sku["weeks_on_floor"] == 3
        assert sku["markdown_step"] == 0
        assert sku["current_price_cents"] == 9_999
        events, _meta = validate_paginated(api.list_store_sku_markdown_events(sku_id, STORE_OPS))
        assert len(events) == 0


class TestClearanceOutletSkipsCadence:
    def test_clearance_store_ignores_cadence(self, api):
        """PRD §3.7: "A store with `clearance_outlet` true skips the cadence
        entirely; nothing changes until the clearance threshold."

        Design: Corner/state_machines/markdown_sweep_skips_clearance_outlet_store_until_clearance_weeks
        """
        env = setup_floor_sku(units_on_hand=20, target_retail_cents=10_000, clearance_outlet=True)
        sku_id = env["sku"]["id"]
        set_clock("2026-10-27T00:00:00Z")
        sku = validate_success(api.get_store_sku(sku_id, STORE_OPS))
        assert sku["weeks_on_floor"] == 8
        assert sku["markdown_step"] == 0
        assert sku["current_price_cents"] == 9_999
        assert sku["status"] == "ON_FLOOR"

    def test_clearance_store_moves_at_clearance_weeks(self, api):
        """PRD §3.7: "A store with `clearance_outlet` true skips the cadence
        entirely; nothing changes until the clearance threshold." PRD §3.7:
        "when `weeks_on_floor` reaches the zone's `clearance_weeks`, the SKU
        moves to `CLEARANCE`".

        Design: Corner/state_machines/markdown_sweep_skips_clearance_outlet_store_until_clearance_weeks
        """
        env = setup_floor_sku(units_on_hand=20, target_retail_cents=10_000, clearance_outlet=True)
        sku_id = env["sku"]["id"]
        set_clock("2026-11-24T00:00:00Z")  # 12 weeks
        sku = validate_success(api.get_store_sku(sku_id, STORE_OPS))
        assert sku["status"] == "CLEARANCE"
        assert sku["markdown_step"] == 0
        events, _meta = validate_paginated(api.list_store_sku_markdown_events(sku_id, STORE_OPS))
        assert [e["event_type"] for e in events] == ["FORCE_CLEARANCE"]


class TestMarkdownEventFields:
    def test_markdown_event_rows_carry_full_audit_fields(self, api):
        """PRD §3.7: "Each event records the `store_sku_id`, the `step_number`,
        `old_price_cents`, `new_price_cents`, the `markdown_cents` difference,
        the event type, and the `effective_date` from the logical clock;
        MarkdownEvents carry no `updated_at` or `version`."

        Design: Corner/endpoints/markdown_event_rows_carry_full_audit_fields
        """
        env = setup_floor_sku(units_on_hand=10, target_retail_cents=10_000)
        sku_id = env["sku"]["id"]
        set_clock("2026-09-29T00:00:00Z")
        events, _meta = validate_paginated(api.list_store_sku_markdown_events(sku_id, STORE_OPS))
        assert len(events) == 1
        event = events[0]
        assert event["store_sku_id"] == sku_id
        assert event["step_number"] == 1
        assert event["old_price_cents"] == 9_999
        assert event["new_price_cents"] == 7_999
        assert event["markdown_cents"] == 2_000
        assert event["event_type"] == "CADENCE"
        assert event["effective_date"].startswith("2026-09-29")

    def test_markdown_event_is_append_only(self, api):
        """PRD §2.4: "**Ticket**, **ReceiptLine**, and **MarkdownEvent** carry
        only `id` and `created_at` — both `updated_at` and `version` are absent
        from these entities".

        Design: Corner/endpoints/markdown_event_rows_carry_full_audit_fields
        """
        env = setup_floor_sku(units_on_hand=10, target_retail_cents=10_000)
        sku_id = env["sku"]["id"]
        set_clock("2026-09-29T00:00:00Z")
        events, _meta = validate_paginated(api.list_store_sku_markdown_events(sku_id, STORE_OPS))
        assert len(events) == 1
        assert "updated_at" not in events[0]
        assert "version" not in events[0]
