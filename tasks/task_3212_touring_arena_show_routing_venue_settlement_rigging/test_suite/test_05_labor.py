"""Labor calls: per-call estimate vs per-worker final cost variants."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_labor_call,
    setup_confirmed_engagement,
    validate_error,
    validate_success,
)

LS = TEST_USERS["labor_steward_headers"]
TM = TEST_USERS["tour_manager_headers"]


class TestLaborEstimateVsFinal:
    def _setup_filled_iatse_call(self):
        ctx = setup_confirmed_engagement(venue_overrides={"union_rule_set": "IATSE"})
        call = create_labor_call(
            ctx,
            department="RIGGERS",
            headcount=2,
            call_start_at="2026-09-10T08:00:00Z",
            call_end_at="2026-09-10T18:00:00Z",
            hourly_rate_cents=5000,
        )
        call = validate_success(
            api_client.post_labor_call(ctx["tour"]["id"], ctx["engagement"]["id"], call["id"], LS)
        )
        call = validate_success(
            api_client.fill_labor_call(ctx["tour"]["id"], ctx["engagement"]["id"], call["id"], LS)
        )
        return ctx, call

    def test_estimate_is_per_call_with_union_minimums(self):
        """PRD §3.6: "an `IATSE` house imposes a 4-hour minimum with overtime
        beginning after 8 hours at one-and-a-half times the straight rate"
        PRD §3.6: "the raw call duration from `call_start_at` to `call_end_at`
        is first rounded half-up to half-hour increments; `effective_hours` is
        then the larger of the rounded raw duration and the applicable minimum
        hours (`union_minimum_hours` records the minimum itself); straight-time
        hours are the smaller of `effective_hours` and the overtime threshold;
        `overtime_hours` is whatever remains beyond the threshold (zero when the
        threshold is not crossed); and `estimated_cost_cents` is the headcount
        multiplied by `hourly_rate_cents` multiplied by the sum of straight-time
        hours plus overtime hours weighted by the market multiplier — with the
        final figure rounded half-up to integer cents, headcount multiplying
        last."

        Design: Difficulty/dual_variant_calc/labor_estimate_per_call_vs_final_per_worker
        """
        ctx = setup_confirmed_engagement(venue_overrides={"union_rule_set": "IATSE"})
        call = create_labor_call(
            ctx,
            department="RIGGERS",
            headcount=2,
            call_start_at="2026-09-10T08:00:00Z",
            call_end_at="2026-09-10T18:00:00Z",
            hourly_rate_cents=5000,
        )
        posted = validate_success(
            api_client.post_labor_call(ctx["tour"]["id"], ctx["engagement"]["id"], call["id"], LS)
        )
        assert posted["union_minimum_hours"] == 4
        assert posted["effective_hours"] == 10
        assert posted["overtime_hours"] == 2
        # 2 * 5000 * (8 + 2*1.5) = 110000
        assert posted["estimated_cost_cents"] == 110000

    def test_final_is_per_worker_and_diverges_from_estimate(self):
        """PRD §3.6: "The same minimum-hours, overtime-threshold, and
        overtime-multiplier rules from the venue's `union_rule_set` apply, but
        computed per worker rather than per call: each worker's pair yields a
        duration rounded to the nearest half hour, the market minimum and
        overtime split apply to that worker's hours, and the worker's cost is
        rounded half-up to integer cents; `final_cost_cents` is the sum across
        workers. The final legitimately diverges from the estimate — the
        estimate is per-call, the final is per-worker, and one worker leaving
        early while another stays late moves the number."

        Design: Difficulty/dual_variant_calc/labor_estimate_per_call_vs_final_per_worker
        """
        ctx, call = self._setup_filled_iatse_call()
        assert call["estimated_cost_cents"] == 110000

        settled = validate_success(
            api_client.settle_labor_call(
                ctx["tour"]["id"], ctx["engagement"]["id"], call["id"],
                {
                    "punch_records": [
                        {"punch_in_at": "2026-09-10T08:00:00Z",
                         "punch_out_at": "2026-09-10T14:00:00Z"},
                        {"punch_in_at": "2026-09-10T08:00:00Z",
                         "punch_out_at": "2026-09-10T19:00:00Z"},
                    ]
                },
                LS,
            )
        )
        # Worker A: 6h -> 6*5000 = 30000; worker B: 11h -> (8+3*1.5)*5000 = 62500.
        assert settled["final_cost_cents"] == 92500
        assert settled["final_cost_cents"] != settled["estimated_cost_cents"]
        assert settled["status"] == "SETTLED"
