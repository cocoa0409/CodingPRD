"""Cap split math, cap-year rollover, and the void compensation path."""
import pytest

from test_helpers import (
    ApiErrorId,
    enroll_agent,
    get_agent,
    get_success_data,
    post_commission,
    setup_center_with_mca,
    validate_success,
)
from test_helpers import TEST_USERS, make_market_center_admin_headers

PA = TEST_USERS["platform_admin_headers"]


def _post(api, agent_id, gross, occurred_on, admin_id, external_ref):
    headers = make_market_center_admin_headers(admin_id)
    version = get_agent(agent_id)["version"]
    payload = {
        "agent_id": agent_id,
        "gross_commission": gross,
        "occurred_on": occurred_on,
        "external_ref": external_ref,
        "expected_agent_version": version,
    }
    return api.create_commission_event(payload, headers)


class TestCapSplitNestedMinMax:
    def _setup_accrued_12000(self, api):
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        ev1 = validate_success(_post(api, a1["id"], 40000.00, "2026-09-05T00:00:00Z",
                                     a1["id"], "ref-a1-1"), 201)
        return ctx, a1, ev1

    def test_rate_bound_then_cap_bound_split(self, api):
        """PRD §3.5: "The split proceeds as follows: compute the raw company dollar
        as gross commission times the rate, rounded; compute the remaining headroom
        as the cap minus the agent's current accrued_company_dollar (floored at zero);
        the event's company_dollar is the smaller of the raw figure and the headroom;
        agent_retained is the gross minus that company dollar, rounded to two decimals."

        Design: Difficulty/combinatorial_formula/cap_split_nested_min_max_with_rollover_branch
        """
        ctx, a1, ev1 = self._setup_accrued_12000(api)
        assert ev1["company_dollar"] == pytest.approx(12000.00, abs=0.01), (
            f"rate bound: round2(40000*0.30), got {ev1['company_dollar']}"
        )
        ev2 = validate_success(_post(api, a1["id"], 40000.00, "2026-09-20T00:00:00Z",
                                     a1["id"], "ref-a1-2"), 201)
        assert ev2["company_dollar"] == pytest.approx(8000.00, abs=0.01), (
            f"cap bound: max(0, 20000-12000), got {ev2['company_dollar']}"
        )
        assert ev2["agent_retained"] == pytest.approx(32000.00, abs=0.01)

    def test_cap_applied_flag_when_cap_determines_split(self, api):
        """PRD §3.5: "cap_applied is true exactly when the cap bound — not the
        rate — determined the company dollar, which is to say when the raw figure
        exceeded the remaining headroom."
        PRD §3.5: "The agent's accrued_company_dollar advances by the event's
        company dollar, and when the resulting accrual reaches at least 20,000.00 —
        the boundary is inclusive — cap_status flips from UNCAPPED to CAPPED."

        Design: Difficulty/combinatorial_formula/cap_split_nested_min_max_with_rollover_branch
        """
        ctx, a1, ev1 = self._setup_accrued_12000(api)
        assert ev1["cap_applied"] is False, "rate-bound split must not set cap_applied"
        ev2 = validate_success(_post(api, a1["id"], 40000.00, "2026-09-20T00:00:00Z",
                                     a1["id"], "ref-a1-2"), 201)
        assert ev2["cap_applied"] is True, "cap-bound split must set cap_applied"
        agent = get_agent(a1["id"])
        assert agent["accrued_company_dollar"] == pytest.approx(20000.00, abs=0.01)
        assert agent["cap_status"] == "CAPPED"


class TestCapCrossingAtExactAnnualCap:
    def _setup_capped_agent(self, api):
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        validate_success(_post(api, a1["id"], 40000.00, "2026-09-05T00:00:00Z",
                               a1["id"], "ref-a1-1"), 201)
        ev2 = validate_success(_post(api, a1["id"], 40000.00, "2026-09-20T00:00:00Z",
                                     a1["id"], "ref-a1-2"), 201)
        return ctx, a1, ev2

    def test_cap_flips_at_exact_boundary(self, api):
        """PRD §3.5: "The agent's accrued_company_dollar advances by the event's
        company dollar, and when the resulting accrual reaches at least 20,000.00 —
        the boundary is inclusive — cap_status flips from UNCAPPED to CAPPED."

        Design: Difficulty/boundary_precision_check/cap_crossing_at_exact_annual_cap
        """
        ctx, a1, ev2 = self._setup_capped_agent(api)
        assert ev2["company_dollar"] == pytest.approx(8000.00, abs=0.01), (
            "accrual lands exactly on 20000.00; the flip fires at equality"
        )
        agent = get_agent(a1["id"])
        assert agent["accrued_company_dollar"] == pytest.approx(20000.00, abs=0.01)
        assert agent["cap_status"] == "CAPPED"

    def test_post_while_capped_retains_fully(self, api):
        """PRD §3.5: "While CAPPED, subsequent splits yield a company_dollar of
        0.00 and full retention by the agent until rollover."

        Design: Difficulty/boundary_precision_check/cap_crossing_at_exact_annual_cap
        """
        ctx, a1, _ = self._setup_capped_agent(api)
        ev3 = validate_success(_post(api, a1["id"], 10000.00, "2026-09-25T00:00:00Z",
                                     a1["id"], "ref-a1-3"), 201)
        assert ev3["company_dollar"] == pytest.approx(0.00, abs=0.01), (
            f"while CAPPED the split yields 0.00, got {ev3['company_dollar']}"
        )
        assert ev3["agent_retained"] == pytest.approx(10000.00, abs=0.01), (
            f"full retention after the cap, got {ev3['agent_retained']}"
        )


class TestRolloverResetsAccrualAndUncaps:
    def _setup_capped_then_clock_forward(self, api):
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        validate_success(_post(api, a1["id"], 40000.00, "2026-09-05T00:00:00Z",
                               a1["id"], "ref-1"), 201)
        validate_success(_post(api, a1["id"], 40000.00, "2026-09-20T00:00:00Z",
                               a1["id"], "ref-2"), 201)
        api.set_clock("2027-09-15T00:00:00Z", PA)
        return ctx, a1

    def test_rollover_splits_against_fresh_accrual(self, api):
        """PRD §3.5: "Cap-year rollover fires automatically inside a posting whose
        occurred_on reaches or passes cap_year_end: cap_year_start and cap_year_end
        advance by whole years until occurred_on falls strictly inside the new
        interval, accrued_company_dollar resets to 0.00, and cap_status returns to
        UNCAPPED — all before the new event's split is applied against the fresh
        accrual."

        Design: Corner/calculations/rollover_resets_accrual_and_uncaps
        """
        ctx, a1 = self._setup_capped_then_clock_forward(api)
        ev3 = validate_success(_post(api, a1["id"], 6000.00, "2027-09-15T00:00:00Z",
                                     a1["id"], "ref-3"), 201)
        assert ev3["company_dollar"] == pytest.approx(1800.00, abs=0.01), (
            f"rate applies again after rollover, got {ev3['company_dollar']}"
        )
        assert ev3["agent_retained"] == pytest.approx(4200.00, abs=0.01)

    def test_rollover_rewrites_cap_year_window(self, api):
        """PRD §3.5: "Cap-year rollover fires automatically inside a posting whose
        occurred_on reaches or passes cap_year_end: cap_year_start and cap_year_end
        advance by whole years until occurred_on falls strictly inside the new
        interval, accrued_company_dollar resets to 0.00, and cap_status returns to
        UNCAPPED — all before the new event's split is applied against the fresh
        accrual."

        Design: Corner/calculations/rollover_resets_accrual_and_uncaps
        """
        ctx, a1 = self._setup_capped_then_clock_forward(api)
        validate_success(_post(api, a1["id"], 6000.00, "2027-09-15T00:00:00Z",
                               a1["id"], "ref-3"), 201)
        agent = get_agent(a1["id"])
        assert agent["cap_year_start"].startswith("2027-09-01"), (
            f"cap_year_start advanced one whole year, got {agent['cap_year_start']}"
        )
        assert agent["accrued_company_dollar"] == pytest.approx(1800.00, abs=0.01)
        assert agent["cap_status"] == "UNCAPPED", (
            f"rollover reverts CAPPED, got {agent['cap_status']}"
        )


class TestVoidRestoresSplitConservation:
    def _setup_posted_event(self, api):
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        ev = validate_success(_post(api, a1["id"], 40000.00, "2026-09-05T00:00:00Z",
                                    a1["id"], "ref-a1-1"), 201)
        return ctx, a1, ev

    def test_forward_split_conserves_gross(self, api):
        """PRD §3.5: "the event's company_dollar is the smaller of the raw figure
        and the headroom; agent_retained is the gross minus that company dollar,
        rounded to two decimals."

        Design: Difficulty/compensating_invariant/commission_void_restores_split_conservation
        """
        ctx, a1, ev = self._setup_posted_event(api)
        assert ev["company_dollar"] == pytest.approx(12000.00, abs=0.01)
        assert ev["agent_retained"] == pytest.approx(28000.00, abs=0.01)
        total = round(ev["company_dollar"] + ev["agent_retained"], 2)
        assert total == pytest.approx(40000.00, abs=0.01), (
            "company_dollar + agent_retained must sum to the gross"
        )

    def test_void_restores_accrual_to_zero(self, api):
        """PRD §3.5: "A void subtracts the event's company_dollar from the agent's
        accrued_company_dollar; if the result falls strictly below 20,000.00 while
        the agent is CAPPED, cap_status reverts to UNCAPPED."

        Design: Difficulty/compensating_invariant/commission_void_restores_split_conservation
        """
        ctx, a1, ev = self._setup_posted_event(api)
        headers = make_market_center_admin_headers(a1["id"])
        validate_success(api.void_commission_event(ev["id"], headers), 200)
        agent = get_agent(a1["id"])
        assert agent["accrued_company_dollar"] == pytest.approx(0.00, abs=0.01), (
            f"compensation restores the pre-action accrual, got {agent['accrued_company_dollar']}"
        )
        assert agent["cap_status"] == "UNCAPPED"
        voided = get_success_data(api.get_commission_event(ev["id"], PA))
        assert voided["status"] == "VOID"
        assert voided["company_dollar"] == pytest.approx(12000.00, abs=0.01), (
            "the voided event retains its original split fields"
        )
        assert voided["agent_retained"] == pytest.approx(28000.00, abs=0.01)
