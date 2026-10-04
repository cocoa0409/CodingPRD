"""Void as compensating reversal: warehouse units and the agreement ledger
(PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success, set_clock, publish_index, setup_run_env, create_run,
    start_run, complete_run, settle_run, get_run, get_plant, get_agreement,
    assert_money, api_client, scheduler,
)


class TestCompleteThenVoid:
    def _env(self, api):
        set_clock()
        publish_index("2026-08", 128.0)
        env = setup_run_env(pass_through_pct=1.0)
        run = create_run(env["agreement"]["id"], env["line"]["id"],
                         env["format"]["id"], scheduled_qty=250000,
                         window_start="2026-09-10T08:00:00Z",
                         window_end="2026-09-10T16:00:00Z")
        start_run(run["id"])
        return env, run["id"]

    def test_complete_then_void_conserves_warehouse_units(self, api):
        """PRD §3.5: "voiding a `COMPLETED` run moves it to `VOIDED`, subtracts
        `produced_qty` from `warehouse_on_hand_units`".

        Design: Difficulty/compensating_invariant/complete_then_void_conserves_warehouse_units
        """
        env, run_id = self._env(api)
        before = get_plant(env["plant"]["id"])["warehouse_on_hand_units"]
        assert before == 0
        complete_run(run_id, 250000, 0)
        mid = get_plant(env["plant"]["id"])["warehouse_on_hand_units"]
        assert mid == 250000
        voided = validate_success(api.void_run(run_id, scheduler()))
        assert voided["status"] == "VOIDED"
        after = get_plant(env["plant"]["id"])["warehouse_on_hand_units"]
        assert after == before == 0, \
            "forward + compensating action conserve warehouse units"

    def test_complete_then_void_restores_projection_and_posture(self, api):
        """PRD §3.5: voiding "recomputes the plant's projection, `posture`";
        PRD §2.10: with projection 0 the posture is `OPEN`.

        Design: Difficulty/compensating_invariant/complete_then_void_conserves_warehouse_units
        """
        env, run_id = self._env(api)
        complete_run(run_id, 250000, 0)
        api.void_run(run_id, scheduler())
        plant = get_plant(env["plant"]["id"])
        assert plant["projected_warehouse_units"] == 0
        assert plant["posture"] == "OPEN"


class TestSettleThenVoid:
    def _env(self, api):
        set_clock()
        publish_index("2026-08", 128.0)
        publish_index("2026-09", 135.0)
        env = setup_run_env(pass_through_pct=0.92,
                            conversion_cost_cents_per_1000=1500)
        run = create_run(env["agreement"]["id"], env["line"]["id"],
                         env["format"]["id"], scheduled_qty=250000,
                         window_start="2026-09-10T08:00:00Z",
                         window_end="2026-09-10T16:00:00Z")
        start_run(run["id"])
        complete_run(run["id"], 250000, 0)
        return env, run["id"]

    def test_settle_adds_to_agreement_ledger(self, api):
        """PRD §3.6: "The agreement's `ytd_settled_units` increases by the run's
        `produced_qty` and its `delivered_revenue_cents` by the
        `settled_amount_cents`."

        Design: Difficulty/compensating_invariant/settle_then_void_conserves_agreement_ledger
        """
        env, run_id = self._env(api)
        before = get_agreement(env["agreement"]["id"])
        assert before["ytd_settled_units"] == 0
        assert before["delivered_revenue_cents"] == 0
        settle_run(run_id)
        mid = get_agreement(env["agreement"]["id"])
        assert mid["ytd_settled_units"] == 250000
        assert_money(mid["delivered_revenue_cents"], 1306500.00, "revenue")

    def test_void_of_settled_run_reverses_ledger_and_tier(self, api):
        """PRD §3.5: "Voiding a `SETTLED` run additionally reverses the
        settlement ledger — the agreement's `ytd_settled_units` decreases by
        `produced_qty`, its `delivered_revenue_cents` decreases by the run's
        `settled_amount_cents` plus its `tier_delta_cents`".

        Design: Difficulty/compensating_invariant/settle_then_void_conserves_agreement_ledger
        """
        env, run_id = self._env(api)
        settle_run(run_id)
        voided = validate_success(api.void_run(run_id, scheduler()))
        assert voided["status"] == "VOIDED"
        agreement = get_agreement(env["agreement"]["id"])
        assert agreement["ytd_settled_units"] == 0
        assert_money(agreement["delivered_revenue_cents"], 0, "revenue")
        assert agreement["volume_tier"] == "STANDARD", \
            "no tier drift left by the settle/void pair"
