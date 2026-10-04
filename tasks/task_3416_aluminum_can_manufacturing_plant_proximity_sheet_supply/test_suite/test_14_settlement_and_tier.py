"""Settlement: per-run rounding order, the volume-tier true-up cascade, and
format amortization (PRD §2.8, §3.2, §3.3, §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_paginated, set_clock, publish_index,
    setup_run_env, create_run, start_run, complete_run, settle_run, get_run,
    get_agreement, assert_money, manager, api_client,
)


def _run_through_completion(env, qty, window, graphics="G1"):
    run = create_run(env["agreement"]["id"], env["line"]["id"],
                     env["format"]["id"], scheduled_qty=qty,
                     graphics_code=graphics, window_start=window[0],
                     window_end=window[1])
    start_run(run["id"])
    complete_run(run["id"], qty, 0)
    return run["id"]


class TestInvoiceRoundingOrder:
    def _rounding_env(self, api):
        """pass 0.87, conversion 2000, format 13.5 lbs; indices 101.3 both
        months; two runs of 7777 units completed."""
        set_clock()
        publish_index("2026-08", 101.3)
        publish_index("2026-09", 101.3)
        env = setup_run_env(committed_annual_units=1_000_000,
                            pass_through_pct=0.87,
                            conversion_cost_cents_per_1000=2000,
                            format_overrides={"metal_lbs_per_1000_units": 13.5,
                                              "size_code": "16OZ"})
        r1 = _run_through_completion(env, 7777, ("2026-09-10T08:00:00Z",
                                                 "2026-09-10T16:00:00Z"))
        r2 = _run_through_completion(env, 7777, ("2026-09-11T08:00:00Z",
                                                 "2026-09-11T16:00:00Z"))
        return env, r1, r2

    def test_settled_amount_rounded_per_run(self, api):
        """PRD §3.6: "The run's invoice amount `settled_amount_cents` is the
        final unit price multiplied by `produced_qty` and divided by one
        thousand, rounded half-up to 2 decimal places". With unit price
        round_half_up(13.5 x 101.3 x 0.87 + 2000, 2) == 3189.77, each 7777-unit
        run settles at round_half_up(3189.77 x 7.777, 2) == 24806.84.

        Design: Difficulty/combinatorial_formula/invoice_round_per_run_then_sum_beats_sum_then_round
        """
        _env, r1, r2 = self._rounding_env(api)
        s1 = settle_run(r1)
        s2 = settle_run(r2)
        assert_money(s1["final_unit_price_cents_per_1000"], 3189.77,
                     "final unit price")
        assert_money(s1["settled_amount_cents"], 24806.84, "run 1 amount")
        assert_money(s2["settled_amount_cents"], 24806.84, "run 2 amount")

    def test_agreement_revenue_sums_per_run_rounded_amounts(self, api):
        """PRD §2.8: "Invoice amounts are rounded half-up to 2 decimal places
        **per production run, before any summation**: each run's settled amount
        is rounded first, and only then are the per-run amounts summed into the
        agreement ledger. The alternative order — summing unrounded amounts and
        rounding the total — is forbidden, because the two orders yield
        different cents."

        Design: Difficulty/combinatorial_formula/invoice_round_per_run_then_sum_beats_sum_then_round
        """
        env, r1, r2 = self._rounding_env(api)
        settle_run(r1)
        settle_run(r2)
        agreement = get_agreement(env["agreement"]["id"])
        # Pinned order: 24806.84 + 24806.84.
        assert_money(agreement["delivered_revenue_cents"], 49613.68,
                     "agreement revenue")
        # Forbidden order over unrounded 24806.8296245 components: 49613.66.
        assert agreement["delivered_revenue_cents"] != pytest.approx(
            49613.66, abs=0.005)
        assert agreement["ytd_settled_units"] == 15554


class TestTierFlipTrueUp:
    def _tier_env(self, api):
        """committed 1000000, pass 1.0, conversion 1000; indices 100.0 both
        months; R1 600000 settled, R2 500000 completed."""
        set_clock()
        publish_index("2026-08", 100.0)
        publish_index("2026-09", 100.0)
        env = setup_run_env(committed_annual_units=1_000_000,
                            pass_through_pct=1.0,
                            conversion_cost_cents_per_1000=1000,
                            capacity=5_000_000)
        r1 = _run_through_completion(env, 600000, ("2026-09-10T08:00:00Z",
                                                   "2026-09-10T16:00:00Z"))
        settle_run(r1)
        r2 = _run_through_completion(env, 500000, ("2026-09-11T08:00:00Z",
                                                   "2026-09-11T16:00:00Z"))
        return env, r1, r2

    def test_crossing_run_priced_at_prior_tier_and_flips_agreement(self, api):
        """PRD §3.6: "The run that crosses the commitment threshold is itself
        priced under the tier in force before its units were added —
        `STANDARD` — and is excluded from the true-up." PRD §3.2: "it is
        `REBATE` whenever `ytd_settled_units` has reached
        `committed_annual_units`".

        Design: Difficulty/transitive_cascade/settle_crosses_commitment_tier_flip_trues_up_sibling_runs
        """
        env, _r1, r2 = self._tier_env(api)
        s2 = settle_run(r2)
        # Priced at STANDARD: 30.0 x 100.0 x 1.0 + 1000 = 4000.00 x 500.
        assert_money(s2["settled_amount_cents"], 2000000.00, "crossing run")
        assert s2["tier_delta_cents"] == 0, \
            "the crossing run is excluded from its own true-up"
        agreement = get_agreement(env["agreement"]["id"])
        assert agreement["volume_tier"] == "REBATE"
        assert agreement["ytd_settled_units"] == 1100000

    def test_tier_flip_trues_up_sibling_run_and_revenue(self, api):
        """PRD §3.6: "when that settlement flips the agreement from `STANDARD`
        to `REBATE`, every other `SETTLED` run of the agreement receives a
        retroactive credit: each such run's `tier_delta_cents` is set to the
        negative of its rebate on the conversion component" and "The
        agreement's `delivered_revenue_cents` then increases by the sum of
        these deltas — a negative adjustment that credits the customer."

        Design: Difficulty/transitive_cascade/settle_crosses_commitment_tier_flip_trues_up_sibling_runs
        """
        env, r1, r2 = self._tier_env(api)
        settle_run(r2)
        sibling = get_run(r1)
        assert_money(sibling["settled_amount_cents"], 2400000.00, "run 1")
        # -(1000 x 1.0 x 0.04 x 600000/1000) == -24000.00
        assert_money(sibling["tier_delta_cents"], -24000.00, "sibling true-up")
        agreement = get_agreement(env["agreement"]["id"])
        # 2400000.00 + 2000000.00 - 24000.00
        assert_money(agreement["delivered_revenue_cents"], 4376000.00,
                     "agreement revenue after true-up")


class TestSettleCascadeFormat:
    def test_settle_cascade_updates_format_amortization(self, api):
        """PRD §3.3: "`delivered_units` accumulates the `produced_qty` of the
        format's settled runs ... and `unamortized_exposure_cents` is the
        `tooling_investment_cents` multiplied by the undelivered fraction of
        the commitment — one minus `delivered_units` divided by
        `min_volume_commitment_units`, floored at zero — rounded half-up to
        whole cents".

        Design: Corner/cross_cutting_layers/settle_cascade_updates_format_amortization
        """
        set_clock()
        publish_index("2026-08", 128.0)
        publish_index("2026-09", 128.0)
        env = setup_run_env(pass_through_pct=1.0,
                            format_overrides={"is_specialty": True,
                                              "shape": "SLEEK",
                                              "size_code": "8OZ-SLEEK",
                                              "metal_lbs_per_1000_units": 22.0,
                                              "tooling_investment_cents": 100000,
                                              "min_volume_commitment_units": 1000000})
        run_id = _run_through_completion(env, 250000, ("2026-09-10T08:00:00Z",
                                                       "2026-09-10T16:00:00Z"))
        settle_run(run_id)
        rows, _ = validate_paginated(api.list_formats(
            manager(), params={"customer_id": env["customer"]["id"]}))
        assert len(rows) == 1
        assert rows[0]["delivered_units"] == 250000
        # 100000 x (1 - 250000/1000000)
        assert rows[0]["unamortized_exposure_cents"] == 75000
        assert get_agreement(env["agreement"]["id"])["ytd_settled_units"] == 250000
