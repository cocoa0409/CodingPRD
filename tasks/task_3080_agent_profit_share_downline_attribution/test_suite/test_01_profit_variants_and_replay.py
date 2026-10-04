"""Dual-variant calculations: provisional vs final profit, cap split vs replay,
and the waterfall's pinned rounding order."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_center,
    enroll_agent,
    get_agent,
    get_success_data,
    open_period,
    add_ledger_entry,
    post_commission,
    prelim_close,
    draft_resolution,
    propose_resolution,
    ratify_resolution,
    setup_center_with_mca,
    setup_chain_mca_s1_d1,
    setup_prelim_closed_divergence_period,
    validate_success,
)
from test_helpers import TEST_USERS, make_market_center_admin_headers, make_alc_chair_headers

PA = TEST_USERS["platform_admin_headers"]


def _list_distributions(api, period_id, agent_id):
    resp = api.list_distributions(PA, params={"period_id": period_id, "agent_id": agent_id})
    return resp.json()["data"]


class TestPeriodProvisionalVsFinal:
    def test_provisional_profit_includes_posted_events(self, api):
        """PRD §2.6: "The provisional variant counts company dollar from every
        commission event of the month whose status is POSTED or SETTLED; the final
        variant counts only SETTLED events, valued by a chronological replay of the
        agent's entire cap year rather than by the provisional splits recorded at
        posting. An event that never settles inflates the provisional figure relative
        to the final one, and an agent whose cap boundary falls mid-month can see a
        different split under replay than under posting-time accrual."

        Design: Difficulty/dual_variant_calc/profit_provisional_vs_final_period_close
        """
        ctx = setup_prelim_closed_divergence_period()
        period = ctx["period"]
        # PROVISIONAL: (3000.00 + 6000.00) - 500.00 = 8500.00; pool = 0.52 * 8500.00
        assert period["provisional_profit"] == pytest.approx(8500.00, abs=0.01), (
            f"provisional_profit must include the POSTED 3000.00, got {period['provisional_profit']}"
        )
        assert period["provisional_pool"] == pytest.approx(4420.00, abs=0.01), (
            f"provisional_pool = round2(0.52 * 8500.00), got {period['provisional_pool']}"
        )
        assert period["final_profit"] is None, "final_profit is null until final close"
        assert period["profit_share_pool"] is None, "profit_share_pool is null until final close"

    def test_final_profit_excludes_never_settled_event(self, api):
        """PRD §2.6: "The provisional variant counts company dollar from every
        commission event of the month whose status is POSTED or SETTLED; the final
        variant counts only SETTLED events, valued by a chronological replay of the
        agent's entire cap year rather than by the provisional splits recorded at
        posting."
        PRD §3.9: "The profit_share_pool is fifty-two percent of final_profit, rounded."

        Design: Difficulty/dual_variant_calc/profit_provisional_vs_final_period_close
        """
        ctx = setup_prelim_closed_divergence_period()
        ratify_resolution(ctx["resolution"]["id"], ctx["alc"]["id"])
        period = get_success_data(api.get_period(ctx["period"]["id"], PA))
        # FINAL: only the settled 20000.00 event -> 6000.00 - 500.00 = 5500.00.
        assert period["provisional_profit"] == pytest.approx(8500.00, abs=0.01)
        assert period["final_profit"] == pytest.approx(5500.00, abs=0.01), (
            f"final_profit must exclude the never-settled 3000.00, got {period['final_profit']}"
        )
        assert period["provisional_pool"] == pytest.approx(4420.00, abs=0.01)
        assert period["profit_share_pool"] == pytest.approx(2860.00, abs=0.01)
        assert period["provisional_profit"] != period["final_profit"], (
            "the two variants must diverge for identical ledger data"
        )


class TestCapSplitProvisionalVsFinalReplay:
    def test_unsettled_event_keeps_provisional_split(self, api):
        """PRD §3.5: "compute the raw company dollar as gross commission times the
        rate, rounded; compute the remaining headroom as the cap minus the agent's
        current accrued_company_dollar (floored at zero); the event's company_dollar
        is the smaller of the raw figure and the headroom"
        PRD §3.9: "Ratification computes final_profit by replaying each affected
        agent's entire cap year over SETTLED events only."

        Design: Difficulty/dual_variant_calc/cap_split_provisional_vs_final_event_replay
        """
        ctx = setup_prelim_closed_divergence_period()
        ev_s1 = get_success_data(api.get_commission_event(ctx["ev_s1"]["id"], PA))
        ev_d1 = get_success_data(api.get_commission_event(ctx["ev_d1"]["id"], PA))
        # Provisional splits recorded at posting stand while the period is open.
        assert ev_s1["company_dollar"] == pytest.approx(3000.00, abs=0.01), (
            f"provisional split on POSTED event, got {ev_s1['company_dollar']}"
        )
        assert ev_s1["final_company_dollar"] is None
        assert ev_d1["company_dollar"] == pytest.approx(6000.00, abs=0.01)
        assert ev_d1["final_company_dollar"] is None

    def test_final_replay_zeroes_never_settled_event(self, api):
        """PRD §2.6: "the final variant counts only SETTLED events, valued by a
        chronological replay of the agent's entire cap year rather than by the
        provisional splits recorded at posting."
        PRD §3.9: "Each event's final_company_dollar is the smaller of its raw
        thirty-percent split (rounded) and the remaining cap headroom at that point
        in the replay, and the accrual advances by that amount event by event."

        Design: Difficulty/dual_variant_calc/cap_split_provisional_vs_final_event_replay
        """
        ctx = setup_prelim_closed_divergence_period()
        ratify_resolution(ctx["resolution"]["id"], ctx["alc"]["id"])
        ev_s1 = get_success_data(api.get_commission_event(ctx["ev_s1"]["id"], PA))
        ev_d1 = get_success_data(api.get_commission_event(ctx["ev_d1"]["id"], PA))
        assert ev_s1["company_dollar"] == pytest.approx(3000.00, abs=0.01), (
            "the provisional split stands on the POSTED event"
        )
        assert ev_s1["final_company_dollar"] == pytest.approx(0.00, abs=0.01), (
            f"SETTLED-only replay excludes the never-settled event, got {ev_s1['final_company_dollar']}"
        )
        assert ev_d1["final_company_dollar"] == pytest.approx(6000.00, abs=0.01), (
            f"d1 was far below the cap so replay matches provisional, got {ev_d1['final_company_dollar']}"
        )
        assert ev_s1["company_dollar"] != ev_s1["final_company_dollar"], (
            "the two variants diverge on the unsettled event"
        )


class TestFinalReplayEvaluationOrder:
    def _setup_two_year_events(self, api):
        ctx = setup_center_with_mca()
        a1, mca = ctx["mca"], ctx["mca"]
        alc = enroll_agent(ctx["center"]["id"])
        ev_sep = post_commission(a1["id"], 20000.00, "2026-09-10T00:00:00Z", mca["id"],
                                 settle=True, external_ref="ref-sep")
        # Posting this second event rolls the cap year (occurred_on >= cap_year_end? No:
        # 2026-12-10 < 2027-09-01 — same cap year; the year resets at the 2027-09-01
        # anniversary during replay).
        ev_dec = post_commission(a1["id"], 10000.00, "2026-12-10T00:00:00Z", mca["id"],
                                 settle=True, external_ref="ref-dec")
        period = open_period(ctx["center"]["id"], "2026-12", mca["id"])
        prelim_close(period["id"], mca["id"])
        res = draft_resolution(period["id"], mca["id"])
        propose_resolution(res["id"], mca["id"])
        return ctx, alc, ev_sep, ev_dec, period, res

    def test_replay_sorts_by_occurred_on_then_created_at(self, api):
        """PRD §3.9: "The evaluation order is pinned: events are sorted by
        occurred_on ascending, ties broken by the event's created_at ascending —
        never by id, never by gross size, which is what decides which of two
        same-day events absorbs the last capped dollar."

        Design: Difficulty/combinatorial_formula/final_replay_evaluation_order_tiebreak
        """
        ctx, alc, ev_sep, ev_dec, period, res = self._setup_two_year_events(api)
        ratify_resolution(res["id"], alc["id"])
        sep = get_success_data(api.get_commission_event(ev_sep["id"], PA))
        dec = get_success_data(api.get_commission_event(ev_dec["id"], PA))
        # ev_sep replays first (2026-09-10 < 2026-12-10): 6000.00 against a fresh
        # accrual. ev_dec replays second within the same cap year (no anniversary
        # crossed between them), absorbing the remaining headroom only.
        assert sep["final_company_dollar"] == pytest.approx(6000.00, abs=0.01), (
            f"earlier occurred_on replays first, got {sep['final_company_dollar']}"
        )
        assert dec["final_company_dollar"] == pytest.approx(3000.00, abs=0.01), (
            f"later event replays against accrued 6000.00, got {dec['final_company_dollar']}"
        )

    def test_final_profit_counts_only_month_events(self, api):
        """PRD §3.9: "The period's final_profit is the sum of those replayed values
        over the month's settled events, minus expenses, plus adjustments, rounded."
        PRD §3.9: "Ratification computes final_profit by replaying each affected
        agent's entire cap year over SETTLED events only."

        Design: Difficulty/combinatorial_formula/final_replay_evaluation_order_tiebreak
        """
        ctx, alc, ev_sep, ev_dec, period, res = self._setup_two_year_events(api)
        ratify_resolution(res["id"], alc["id"])
        final = get_success_data(api.get_period(period["id"], PA))
        assert final["final_profit"] == pytest.approx(3000.00, abs=0.01), (
            f"only the December event's replayed company dollar counts, got {final['final_profit']}"
        )


class TestDistributionPerLineRounding:
    def _setup_three_children(self, api):
        ctx = setup_center_with_mca()
        center, mca = ctx["center"], ctx["mca"]
        # s1 is sponsorless so the ONLY entitlement lines are s1's three
        # depth-1 lines; gross total (1.5x profit) then fits within the pool
        # (0.52x profit) and the pinned per-line rounding is observable without
        # the scaling branch of §3.8 firing.
        s1 = enroll_agent(center["id"], email="s1@example.com")
        children = [
            enroll_agent(center["id"], sponsor_id=s1["id"], email=f"x{i}@example.com")
            for i in range(1, 4)
        ]
        alc = enroll_agent(center["id"], email="alc@example.com")
        for i, child in enumerate(children, start=1):
            post_commission(child["id"], 1111.10, "2026-09-10T00:00:00Z", mca["id"],
                            settle=True, external_ref=f"ref-x{i}")
        period = open_period(center["id"], "2026-09", mca["id"])
        prelim_close(period["id"], mca["id"])
        res = draft_resolution(period["id"], mca["id"])
        propose_resolution(res["id"], mca["id"])
        return {"center": center, "mca": mca, "s1": s1, "alc": alc,
                "children": children, "period": period, "res": res}

    def test_sponsor_amount_uses_per_line_rounding(self, api):
        """PRD §3.8: "Rounding order is pinned and not negotiable: each entitlement
        line is rounded to two decimals half-up first, and only then summed. Summing
        first and rounding once is prohibited — it produces different cents."

        Design: Difficulty/combinatorial_formula/distribution_per_line_rounding_then_sum
        """
        ctx = self._setup_three_children(api)
        ratify_resolution(ctx["res"]["id"], ctx["alc"]["id"])
        rows = _list_distributions(api, ctx["period"]["id"], ctx["s1"]["id"])
        assert len(rows) == 1, f"expected exactly one distribution for s1, got {len(rows)}"
        # 3 lines x round2(0.50 * 333.33) = 3 x 166.67 = 500.01 (not 500.00).
        assert rows[0]["amount"] == pytest.approx(500.01, abs=0.01), (
            f"per-line rounding gives 500.01 (not the sum-then-round 500.00), got {rows[0]['amount']}"
        )

    def test_period_conservation_after_per_line_rounding(self, api):
        """PRD §3.8: "Conservation holds at all times: the sum of distribution
        amounts plus center_retained_amount equals the current pool"
        PRD §3.9: "The profit_share_pool is fifty-two percent of final_profit, rounded."

        Design: Difficulty/combinatorial_formula/distribution_per_line_rounding_then_sum
        """
        ctx = self._setup_three_children(api)
        ratify_resolution(ctx["res"]["id"], ctx["alc"]["id"])
        period = get_success_data(api.get_period(ctx["period"]["id"], PA))
        assert period["final_profit"] == pytest.approx(999.99, abs=0.01)
        assert period["profit_share_pool"] == pytest.approx(519.99, abs=0.01)
        assert period["distributed_total"] == pytest.approx(500.01, abs=0.01)
        assert period["center_retained_amount"] == pytest.approx(19.98, abs=0.01)
        total = round(period["distributed_total"] + period["center_retained_amount"], 2)
        assert total == pytest.approx(period["profit_share_pool"], abs=0.01), (
            "distributed_total + center_retained_amount must equal profit_share_pool"
        )
