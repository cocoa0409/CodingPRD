"""Unit pricing: the PROVISIONAL vs FINAL index variants and the specialty
surcharge (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    validate_success, ApiErrorId,
    set_clock, publish_index, setup_run_env, create_run, start_run,
    complete_run, settle_run, get_run, assert_money,
)


def _pricing_env(api, pass_through, conversion, specialty=False,
                 metal=30.0, committed=12_000_000, capacity=1_000_000):
    """ACTIVE agreement + QUALIFIED format; caller publishes the indices."""
    format_overrides = None
    if specialty:
        format_overrides = {"is_specialty": True, "shape": "SLEEK",
                            "size_code": "8OZ-SLEEK",
                            "metal_lbs_per_1000_units": metal,
                            "tooling_investment_cents": 100000,
                            "min_volume_commitment_units": 1000000}
    return setup_run_env(format_overrides=format_overrides,
                         committed_annual_units=committed,
                         pass_through_pct=pass_through,
                         conversion_cost_cents_per_1000=conversion,
                         capacity=capacity)


class TestDualVariantPricing:
    def _dual_env(self, api):
        """Identical to the pinned recipe: pass 0.92, conversion 1500,
        STANDARD format 30.0 lbs; indices 2026-08=128.00 and 2026-09=135.00."""
        set_clock()
        publish_index("2026-08", 128.0)
        publish_index("2026-09", 135.0)
        env = _pricing_env(api, 0.92, 1500)
        run = create_run(env["agreement"]["id"], env["line"]["id"],
                         env["format"]["id"], scheduled_qty=250000,
                         graphics_code="STD-RED",
                         window_start="2026-09-10T08:00:00Z",
                         window_end="2026-09-10T16:00:00Z")
        start_run(run["id"])
        return env, run["id"]

    def test_provisional_price_uses_prior_month_index(self, api):
        """PRD §3.5: "The provisional variant reads the published index whose
        `period` is exactly one month before the run's delivery month".

        Design: Difficulty/dual_variant_calc/unit_price_provisional_prior_month_vs_final_delivery_month
        """
        _env, run_id = self._dual_env(api)
        completed = complete_run(run_id, 250000, 5000)
        # 30.0 * 128.00 * 0.92 + 1500 = 3532.80 + 1500
        assert_money(completed["provisional_unit_price_cents_per_1000"], 5032.80,
                     "provisional unit price")
        assert completed["status"] == "COMPLETED"

    def test_final_price_uses_delivery_month_index(self, api):
        """PRD §3.6: "the provisional price reads the month exactly one month
        before delivery, the final price reads the delivery month itself, so
        whenever those two published rows differ, identical inputs price
        differently."

        Design: Difficulty/dual_variant_calc/unit_price_provisional_prior_month_vs_final_delivery_month
        """
        _env, run_id = self._dual_env(api)
        complete_run(run_id, 250000, 5000)
        settled = settle_run(run_id)
        # 30.0 * 135.00 * 0.92 + 1500 = 3726.00 + 1500
        assert_money(settled["final_unit_price_cents_per_1000"], 5226.00,
                     "final unit price")
        assert settled["provisional_unit_price_cents_per_1000"] != \
            pytest.approx(settled["final_unit_price_cents_per_1000"], abs=0.005)
        # 5226.00 * 250000 / 1000
        assert_money(settled["settled_amount_cents"], 1306500.00,
                     "settled amount")
        assert settled["status"] == "SETTLED"


class TestSpecialtySurcharge:
    def test_can_unit_price_applies_specialty_surcharge_constant(self, api):
        """PRD §3.5: "the conversion component is the agreement's
        `conversion_cost_cents_per_1000` multiplied by two factors — ... and a
        specialty factor of 1.12 (the twelve percent surcharge) when the format
        is specialty, and 1.0 otherwise."

        Design: Corner/calculations/can_unit_price_applies_specialty_surcharge_constant
        """
        set_clock()
        publish_index("2026-08", 128.0)
        env = _pricing_env(api, 1.0, 1000, specialty=True)
        run = create_run(env["agreement"]["id"], env["line"]["id"],
                         env["format"]["id"], scheduled_qty=100000,
                         window_start="2026-09-10T08:00:00Z",
                         window_end="2026-09-10T16:00:00Z")
        start_run(run["id"])
        completed = complete_run(run["id"], 100000, 0)
        # metal 30.0 * 128.00 * 1.0 = 3840.00; conversion 1000 * 1.12 = 1120.00
        assert_money(completed["provisional_unit_price_cents_per_1000"], 4960.00,
                     "specialty provisional unit price")
        assert completed["provisional_unit_price_cents_per_1000"] != \
            pytest.approx(4840.00, abs=0.005), \
            "a STANDARD format at identical terms would price 4840.00"
