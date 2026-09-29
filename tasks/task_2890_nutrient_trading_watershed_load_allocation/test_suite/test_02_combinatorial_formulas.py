"""Multi-branch formulas whose evaluation order and rounding order are pinned."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_calendar_date,
    assert_load,
    assert_load_conservation,
    assert_pct,
)
from test_helpers.test_users import ADMIN, ANALYST


def test_tier_a_and_tier_b_reliefs_are_read_off_the_selected_tier(api):
    """Two permits on one allocation land in different tiers with different relief.

    "`TIER_A` grants no relief at all and a schedule of zero years, `TIER_B`
    grants relief of one quarter and a three-year schedule, and `TIER_C` grants
    relief of one half and a five-year schedule."

    Design: Difficulty/combinatorial_formula/permit_limit_tier_relief_pinned_evaluation_order_across_three_tiers
    """
    world = fx.scr_allocated(api)

    permit_b = fx.make_permit(
        api,
        world["watershed_id"],
        world["sa_p1"]["id"],
        permit_number="OH0012345",
        current_annual_load_lbs=30000.00,
    )
    permit_a = fx.make_permit(
        api,
        world["watershed_id"],
        world["sa_p2"]["id"],
        permit_number="OH0023456",
        permittee_user_id="user-permittee-2",
        design_flow_mgd=1.2000,
        current_annual_load_lbs=6000.00,
    )

    derived_b = fx.derive_limits(api, permit_b["id"])
    assert_load(derived_b["wla_lbs_yr"], 21888.00, "wla_lbs_yr")
    assert_load(derived_b["final_limit_lbs_yr"], 21888.00, "final_limit_lbs_yr")
    assert_pct(derived_b["required_reduction_pct"], 27.04, "required_reduction_pct")
    assert derived_b["schedule_tier"] == "TIER_B", derived_b
    # 21888.00 plus one quarter of the 8112.00 gap to the current annual load.
    assert_load(derived_b["interim_limit_lbs_yr"], 23916.00, "interim_limit_lbs_yr")
    assert_calendar_date(
        derived_b["compliance_schedule_end_date"], "2029-03-01", "compliance_schedule_end_date"
    )
    assert_load(derived_b["applicable_limit_lbs_yr"], 23916.00, "applicable_limit_lbs_yr")
    assert derived_b["limit_status"] == "INTERIM", derived_b

    derived_a = fx.derive_limits(api, permit_a["id"])
    assert_load(derived_a["wla_lbs_yr"], 5472.00, "wla_lbs_yr")
    assert_load(derived_a["final_limit_lbs_yr"], 5472.00, "final_limit_lbs_yr")
    assert_pct(derived_a["required_reduction_pct"], 8.80, "required_reduction_pct")
    assert derived_a["schedule_tier"] == "TIER_A", derived_a
    # TIER_A grants no relief, so the interim limit equals the final limit.
    assert_load(derived_a["interim_limit_lbs_yr"], 5472.00, "interim_limit_lbs_yr")
    assert_calendar_date(
        derived_a["compliance_schedule_end_date"], "2026-03-01", "compliance_schedule_end_date"
    )
    assert derived_a["limit_status"] == "INTERIM", derived_a


def test_tier_c_is_selected_from_the_reduction_against_the_final_limit(api):
    """A 90.88 percent burden reaches TIER_C even though the relieved gap is far smaller.

    "The evaluation order is pinned as five steps, the tier is selected from the
    reduction measured against the **final** limit only, and relief is applied
    afterwards. Deriving the tier from an interim value is incorrect."

    Design: Difficulty/combinatorial_formula/permit_limit_tier_relief_pinned_evaluation_order_across_three_tiers
    """
    world = fx.scr_allocated(api)
    permit_c = fx.make_permit(
        api,
        world["watershed_id"],
        world["sa_p2"]["id"],
        permit_number="OH0034567",
        permittee_user_id="user-permittee-2",
        design_flow_mgd=1.2000,
        current_annual_load_lbs=60000.00,
    )

    derived = fx.derive_limits(api, permit_c["id"])

    assert_load(derived["final_limit_lbs_yr"], 5472.00, "final_limit_lbs_yr")
    assert_pct(derived["required_reduction_pct"], 90.88, "required_reduction_pct")
    assert derived["schedule_tier"] == "TIER_C", derived
    # 5472.00 plus one half of the 54528.00 gap to the current annual load.
    assert_load(derived["interim_limit_lbs_yr"], 32736.00, "interim_limit_lbs_yr")
    # Had the tier been read off the relieved interim value the burden would have
    # measured 45.44 percent and selected TIER_B with a three-year schedule.
    assert_calendar_date(
        derived["compliance_schedule_end_date"], "2031-03-01", "compliance_schedule_end_date"
    )
    assert_load(derived["applicable_limit_lbs_yr"], 32736.00, "applicable_limit_lbs_yr")


def _alt_watershed(api):
    """Alum Creek: three point sources and one nonpoint source whose exact
    quotients do not re-add to their pool once each is rounded."""
    fx.pin_clock(api)
    watershed = fx.make_watershed(
        api,
        name="Alum Creek",
        state_code="OH",
        watershed_code="ALT",
        pollutant="TOTAL_NITROGEN",
        baseline_year=2020,
        baseline_load_lbs_yr=90000.00,
        eligible_zone_codes=["Z1", "Z2"],
    )
    a_out = fx.make_reach(
        api,
        watershed["id"],
        "A_OUT",
        trading_zone_code="Z2",
        reach_class="COMPLIANCE_POINT",
        delivery_factor=1.0000,
    )
    a_mid = fx.make_reach(
        api,
        watershed["id"],
        "A_MID",
        trading_zone_code="Z2",
        reach_class="MAINSTEM",
        delivery_factor=0.9500,
        downstream_reach_id=a_out["id"],
    )
    assessment = fx.make_assessment(
        api,
        watershed["id"],
        assessment_code="TMDL-N-ALT",
        loading_capacity_lbs_yr=50000.00,
        margin_of_safety_pct=0.0750,
        background_load_lbs_yr=4321.00,
    )
    small = fx.make_source(
        api, assessment["id"], a_mid["id"], "Alum Point Small", "POINT", 10000.00, 0.5000
    )
    medium = fx.make_source(
        api, assessment["id"], a_mid["id"], "Alum Point Medium", "POINT", 20000.00, 0.5000
    )
    large = fx.make_source(
        api, assessment["id"], a_mid["id"], "Alum Point Large", "POINT", 30000.00, 0.5000
    )
    nonpoint = fx.make_source(
        api, assessment["id"], a_mid["id"], "Alum Cropland", "NONPOINT", 40000.00, 0.4000
    )
    return {
        "watershed": watershed,
        "assessment": assessment,
        "small": small,
        "medium": medium,
        "large": large,
        "nonpoint": nonpoint,
    }


def test_point_total_is_the_sum_of_rounded_allocations_not_the_rounded_pool(api):
    """The wasteload total exceeds its own pool by one cent, which is the correct answer.

    "each source's allocation is rounded to 2 decimal places first and the
    already-rounded values are then summed. Summing the exact quotients and
    rounding once at the end is incorrect and can differ by cents."

    Design: Difficulty/combinatorial_formula/allocation_pool_round_then_sum_not_sum_then_round
    """
    alt = _alt_watershed(api)

    run = fx.make_allocation_run(api, alt["assessment"]["id"], "RUN-ALT")

    assert_load(run["margin_of_safety_lbs_yr"], 3750.00, "margin_of_safety_lbs_yr")
    assert_load(run["allocable_load_lbs_yr"], 41929.00, "allocable_load_lbs_yr")
    assert_load(run["point_pool_lbs_yr"], 23899.53, "point_pool_lbs_yr")
    assert_load(run["nonpoint_pool_lbs_yr"], 15933.02, "nonpoint_pool_lbs_yr")

    allocations = {
        row["source_assessment_id"]: row["allocated_load_lbs_yr"] for row in run["allocations"]
    }
    assert_load(allocations[alt["large"]["id"]], 11949.77, "largest point allocation")
    assert_load(allocations[alt["medium"]["id"]], 7966.51, "middle point allocation")
    assert_load(allocations[alt["small"]["id"]], 3983.26, "smallest point allocation")
    assert_load(allocations[alt["nonpoint"]["id"]], 15933.02, "nonpoint allocation")

    assert_load(run["wla_total_lbs_yr"], 23899.54, "wla_total_lbs_yr")
    assert round(float(run["wla_total_lbs_yr"]), 2) != round(float(run["point_pool_lbs_yr"]), 2), (
        "the point total must be the sum of the rounded allocations, not the pool itself"
    )
    assert_load(run["la_total_lbs_yr"], 15933.02, "la_total_lbs_yr")


def test_reserve_term_absorbs_the_rounding_residue_so_capacity_reconciles(api):
    """The reserve carries the 5 percent set-aside plus the per-source residue.

    "It therefore carries both the deliberate 5 percent set-aside and the
    per-source rounding residue, and it is what makes the load-conservation
    identity of §2.9 hold exactly."

    Design: Difficulty/combinatorial_formula/allocation_pool_round_then_sum_not_sum_then_round
    """
    alt = _alt_watershed(api)

    run = fx.make_allocation_run(api, alt["assessment"]["id"], "RUN-ALT")

    # The deliberate set-aside on 41929.00 is 2096.45; the reserve term comes out
    # one cent lower because the point group's rounded allocations overspend by a cent.
    assert_load(run["reserve_allocation_lbs_yr"], 2096.44, "reserve_allocation_lbs_yr")

    assessment = get_success_data(api.get_tmdl_assessment(alt["assessment"]["id"], ANALYST))
    assert_load_conservation(assessment)
    assert_load(assessment["loading_capacity_lbs_yr"], 50000.00, "loading_capacity_lbs_yr")

    watershed = get_success_data(api.get_watershed(alt["watershed"]["id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2096.44, "reserve_pool_lbs")
    assert_load(watershed["allocated_wla_total_lbs_yr"], 23899.54, "allocated_wla_total_lbs_yr")
    assert_load(watershed["allocated_la_total_lbs_yr"], 15933.02, "allocated_la_total_lbs_yr")
