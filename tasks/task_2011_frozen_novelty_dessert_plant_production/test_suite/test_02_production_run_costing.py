"""Run-completion costing (PRD §3.6) and mix-litre conservation (§3.3)."""
import pytest

from test_helpers import (
    complete_run,
    setup_completed_run,
    setup_mix_assigned_run,
    start_run,
    validate_success,
)


class TestRunMixCosting:
    def test_run_mix_usage_standard_variant_fields(self, api):
        """PRD §3.6: "mix_litres_theoretical is actual_units multiplied by
        fill_volume_ml_per_unit, divided by (1 plus target_overrun_pct
        divided by 100), divided by 1000 to convert millilitres to litres —
        rounded half-up to 2 decimal places." 10000 units * 70 ml / 1.40 /
        1000 = 500.0 litres; 500.0 * 85 = 42500 cents.

        Design: Difficulty/dual_variant_calc/run_mix_usage_standard_vs_metered
        """
        run = validate_success(complete_run(
            _start_full_run(api), 10000, 460.0, _zone_id(api)))
        assert run["status"] == "COMPLETED"
        assert run["mix_litres_theoretical"] == pytest.approx(500.0, abs=0.005)
        assert run["mix_cost_variance_cents"] == 3400

    def test_run_mix_usage_metered_variant_fields(self, api):
        """PRD §3.6: "overrun_actual_pct is computed as actual_units
        multiplied by fill_volume_ml_per_unit, divided by the product of
        mix_metered_litres and 1000, then subtracting 1, then multiplying by
        100 — rounded half-up to 2 decimal places." 10000*70/(460*1000)-1
        = 0.5217... -> 52.17. "mix_cost_variance_cents is the standard cost
        minus the actual cost": 42500 - 39100 = 3400.

        Design: Difficulty/dual_variant_calc/run_mix_usage_standard_vs_metered
        """
        run = validate_success(complete_run(
            _start_full_run(api), 10000, 460.0, _zone_id(api)))
        assert run["overrun_actual_pct"] == pytest.approx(52.17, abs=0.005)
        assert run["mix_cost_variance_cents"] == 3400


class TestLotComputedFields:
    def test_lot_computed_fields_at_creation(self, api):
        """PRD §3.7: "Its lot_code is LOT- followed by the run's run_code;
        run_id and product_id are taken from the run; zone_id from the
        completion payload; units_produced equals actual_units; produced_at
        equals the completion timestamp; best_before is produced_at plus the
        product's shelf_life_days." Pallets: "the ceiling of
        (units_available plus units_reserved) divided by the product's
        units_per_pallet" — ceil(2000/100) == 20.

        Design: Corner/entities/lot_computed_fields_at_creation
        """
        ctx = setup_completed_run(run_code="R-LC", planned_units=2000,
                                  actual_units=2000, mix_metered_litres=100.0)
        lot = ctx["lot"]
        assert lot["lot_code"] == "LOT-R-LC"
        assert lot["units_produced"] == 2000
        assert lot["status"] == "AVAILABLE"
        assert lot["pallets"] == 20
        # produced_at equals the logical clock at completion (08:00), and
        # best_before = produced_at + 540 days = 2028-02-01T08:00:00Z.
        assert lot["produced_at"].startswith("2026-08-10T08:00")
        assert lot["best_before"].startswith("2028-02-01T08:00")


# ----------------------------------------------------------------------
# Helpers local to this file: build a started run ready for completion.
# ----------------------------------------------------------------------

_RUN_CTX = {}


def _start_full_run(api):
    """Build a started run (IN_PRODUCTION) on a fresh database and stash
    the zone id for the follow-up complete call."""
    ctx = setup_mix_assigned_run(run_code="R-1", planned_units=10000)
    start_run(ctx["run"]["id"])
    _RUN_CTX["zone_id"] = ctx["zone"]["id"]
    return ctx["run"]["id"]


def _zone_id(api):
    return _RUN_CTX["zone_id"]
