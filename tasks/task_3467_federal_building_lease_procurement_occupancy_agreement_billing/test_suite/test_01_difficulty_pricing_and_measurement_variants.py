"""Dual-variant calculations: identical inputs diverging purely by variant."""
import pytest

from test_helpers import (
    assert_rent_bill, create_survey, finalize_survey, generate_bill,
    setup_active_leased_oa, setup_active_owned_oa,
)


def test_tax_escalation_base_year_stop_vs_cpi_indexed(api):
    """PRD §3.4: "Under `BASE_YEAR_STOP`, the annual escalation is the excess of
    the statement's actual per-square-foot tax over the lease's
    `base_year_tax_per_sf_yr_cents`, floored at zero, multiplied by the
    agreement's assigned square feet — so when no statement qualifies, actual
    equals base and the escalation is zero."
    PRD §3.4: "Under `CPI_INDEXED`, the escalation indexes the base-year tax by
    CPI growth: the statement's index divided by the `cpi_base_index`, minus
    one, floored at zero and capped at twenty percent, multiplied by the
    base-year tax rate and the assigned square feet."
    PRD §3.4: "Either way, the annual figure is rounded half up first, then
    divided by twelve and rounded half up again to whole cents for the month."

    Two leases with identical rates, identical 68,300 sf, and an identical 2027
    statement (actual 460; CPI 315.0 over a 300.0 base on the indexed lease):
    BASE_YEAR_STOP bills round_half_up((460-400)*68300/12) == 341,500 while
    CPI_INDEXED bills round_half_up(400*68300*0.05/12) == 113,833.

    Design: Difficulty/dual_variant_calc/tax_escalation_base_year_stop_vs_cpi_indexed
    """
    bundle_a = setup_active_leased_oa()  # BASE_YEAR_STOP, 2027 stmt actual 460
    bundle_b = setup_active_leased_oa(escalation_method="CPI_INDEXED",
                                      cpi_base_index=300.0, cpi_index=315.0)

    bill_a = generate_bill(bundle_a["oa"], "2027-04")
    bill_b = generate_bill(bundle_b["oa"], "2027-04")
    assert_rent_bill(bill_a)
    assert_rent_bill(bill_b)

    assert bill_a["tax_escalation_cents"] == 341500, (
        f"BASE_YEAR_STOP: (460-400)*68300/12 -> 341500, got {bill_a['tax_escalation_cents']}")
    assert bill_b["tax_escalation_cents"] == 113833, (
        f"CPI_INDEXED: 400*68300*0.05/12 -> 113833, got {bill_b['tax_escalation_cents']}")
    assert bill_a["tax_escalation_cents"] != bill_b["tax_escalation_cents"], (
        "identical statement data must bill differently across the two variants")


def test_utilization_space_based_vs_headcount_based_diverge(api):
    """PRD §3.8: "Under `SPACE_BASED`, the `utilization_rate` is the
    `utilized_sf` divided by the agreement's current `assigned_sf`."
    PRD §3.8: "Under `HEADCOUNT_BASED`, it is the `measured_headcount` times
    the 150-square-feet-per-person standard, divided by `assigned_sf` — so
    identical payloads under the two methods generally yield different rates."
    PRD §3.8: "Either way the rate is rounded half up to four decimal places."
    PRD §3.8: "When the finalized rate falls strictly below 0.60 — a rate of
    exactly 0.6000 does not qualify — the system auto-creates a space reduction
    action in `PROPOSED` on the same agreement, copies the recommendation into
    it, and links it back through the survey's `reduction_action_id`; otherwise
    that field stays null."

    Identical payloads (headcount 100, utilized 12,000 sf on a 20,000 sf
    agreement): SPACE_BASED yields 0.6000, HEADCOUNT_BASED yields 0.7500;
    neither is strictly below 0.60, so neither links a reduction action.

    Design: Difficulty/dual_variant_calc/utilization_space_based_vs_headcount_based_diverge
    """
    bundle = setup_active_owned_oa(clock="2027-03-20T00:00:00Z")
    oa = bundle["oa"]

    s_space = create_survey(oa, method="SPACE_BASED", measured_headcount=100,
                            utilized_sf=12000)
    s_head = create_survey(oa, method="HEADCOUNT_BASED", measured_headcount=100,
                           utilized_sf=12000)
    f_space = finalize_survey(s_space)
    f_head = finalize_survey(s_head)

    assert f_space["utilization_rate"] == pytest.approx(0.6000, abs=1e-9), (
        f"12000/20000 -> 0.6000, got {f_space['utilization_rate']}")
    assert f_head["utilization_rate"] == pytest.approx(0.7500, abs=1e-9), (
        f"100*150/20000 -> 0.7500, got {f_head['utilization_rate']}")
    assert f_space["utilization_rate"] != f_head["utilization_rate"], (
        "identical payloads must diverge across the two methods")
    assert f_space["reduction_action_id"] is None, (
        "0.6000 is not strictly below 0.60")
    assert f_head["reduction_action_id"] is None, (
        "0.7500 is not strictly below 0.60")
