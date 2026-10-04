"""Boundary precision: X-1 / X / X+1 against the PRD's strict thresholds."""
import pytest

from test_helpers import (
    TEST_USERS, create_survey, finalize_survey, generate_bill,
    list_reduction_actions, setup_active_leased_oa, setup_active_owned_oa,
)

ADMIN = TEST_USERS["gsa_admin_headers"]


def test_utilization_exactly_threshold_proposes_no_action(api):
    """PRD §3.8: "Under `SPACE_BASED`, the `utilization_rate` is the
    `utilized_sf` divided by the agreement's current `assigned_sf`."
    PRD §3.8: "Finalization also sets `recommended_release_sf`: the
    `assigned_sf` minus the `measured_headcount` times the same
    150-square-feet-per-person standard, floored at zero."
    PRD §3.8: "When the finalized rate falls strictly below 0.60 — a rate of
    exactly 0.6000 does not qualify — the system auto-creates a space reduction
    action in `PROPOSED` on the same agreement, copies the recommendation into
    it, and links it back through the survey's `reduction_action_id`; otherwise
    that field stays null."

    Rate exactly 0.6000 (12,000 / 20,000) proposes nothing; the paired survey
    at 0.5250 (headcount 70) proposes a release of 9,500 sf.

    Design: Difficulty/boundary_precision_check/utilization_exactly_threshold_proposes_no_action
    """
    bundle = setup_active_owned_oa(clock="2027-03-20T00:00:00Z")
    oa = bundle["oa"]

    s_exact = create_survey(oa, method="SPACE_BASED", measured_headcount=100,
                            utilized_sf=12000)
    s_below = create_survey(oa, method="HEADCOUNT_BASED", measured_headcount=70,
                            utilized_sf=10500)
    f_exact = finalize_survey(s_exact)
    f_below = finalize_survey(s_below)

    assert f_exact["utilization_rate"] == pytest.approx(0.6000, abs=1e-9)
    assert f_exact["reduction_action_id"] is None, (
        "exactly at the threshold: no trigger")

    assert f_below["utilization_rate"] == pytest.approx(0.5250, abs=1e-9)
    assert f_below["reduction_action_id"] is not None

    actions = list_reduction_actions(oa)
    assert len(actions) == 1, "only the below-threshold survey proposes"
    assert actions[0]["recommended_release_sf"] == 9500


def test_tax_escalation_actual_equals_base_yields_zero(api):
    """PRD §3.4: "Under `BASE_YEAR_STOP`, the annual escalation is the excess
    of the statement's actual per-square-foot tax over the lease's
    `base_year_tax_per_sf_yr_cents`, floored at zero, multiplied by the
    agreement's assigned square feet — so when no statement qualifies, actual
    equals base and the escalation is zero."
    PRD §3.5: "`fee_cents` is the GSA fee: five percent of the subtotal,
    rounded half up."
    PRD §2.5: "Every rounding in the system is round half up, and bill
    components are each rounded to whole cents before they are summed into a
    subtotal; the component-first order is pinned and must not be rearranged
    (§3.5)."

    Actual 400 == base 400 bills zero escalation; the tax-free subtotal
    22,846,970 exposes the half-up fee edge: 1,142,348.5 rounds UP to
    1,142,349.

    Design: Difficulty/boundary_precision_check/tax_escalation_actual_equals_base_yields_zero
    """
    bundle = setup_active_leased_oa(tax_year=2027, actual_tax=400)
    bill = generate_bill(bundle["oa"], "2027-04")

    assert bill["tax_escalation_cents"] == 0, (
        "actual == base is not above base: no escalation")
    assert bill["fee_cents"] == 1142349, (
        "round_half_up(22,846,970 * 0.05 = 1,142,348.5) rounds up")
    assert bill["total_cents"] == 23989319
