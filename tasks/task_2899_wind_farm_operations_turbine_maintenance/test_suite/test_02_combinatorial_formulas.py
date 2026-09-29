"""Multi-term formulas whose composition order is observable.

The work-order priority score, the blade severity score and the crane cost
waterfall each combine several weighted terms, and each pins a rounding or
keying order that a different order would visibly break.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import WindOpsApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_crane_costs,
    assert_four_dp,
    assert_two_dp,
)
from test_helpers.constants import (
    BAND_HIGH,
    BLADE_OPEN,
    CRANE_MOBILIZED,
    REPLACEMENT_CRANE_RESERVED,
    TRIAGE_CLOSED,
    WO_SUBMITTED,
)
from test_helpers.factories import blade_damage_payload
from test_helpers.fixtures import (
    read_agreement,
    read_crane,
    read_replacement,
    read_turbine,
    read_work_order,
    setup_blade_severity_scenario,
    setup_crane_waterfall_scenario,
    setup_priority_score_scenario,
)
from test_helpers.test_users import make_engineer_headers, make_planner_headers

ENGINEER = make_engineer_headers()
PLANNER = make_planner_headers()


# ===========================================================================
# Difficulty / combinatorial_formula
# ===========================================================================
def test_priority_score_weights_four_terms_and_rounds_the_sum_exactly_once(
    api: WindOpsApiClient,
):
    """PRD 3.3: "The four terms are then weighted — 40 for severity, 30 for energy, 20 for
    liquidated-damages risk and 10 for age — added together at full precision, and the resulting
    **sum is rounded half up to two decimal places exactly once**."

    Design: Difficulty/combinatorial_formula/work_order_priority_score_four_weighted_terms_with_nested_min_and_at_risk_branch
    """
    world = setup_priority_score_scenario(api)

    # 40 * (3/5) + 30 * min(4 * 2000 / 5000, 1) + 20 * 0 + 10 * min(0/30, 1).
    assert_two_dp(world["order"]["priority_score"], 54.00, "priority_score at submit")
    assert world["order"]["state"] == WO_SUBMITTED


def test_priority_score_rises_when_an_unnamed_agreement_flips_at_risk(api: WindOpsApiClient):
    """PRD 3.3: "The **liquidated-damages term** is 1.0 when at least one service agreement exists
    on the turbine's farm that is in `ACTIVE` with its `at_risk_flag` true, and 0.0 otherwise —
    agreements in `IN_SETTLEMENT` or `SETTLED` never contribute this term."

    Design: Difficulty/combinatorial_formula/work_order_priority_score_four_weighted_terms_with_nested_min_and_at_risk_branch
    """
    world = setup_priority_score_scenario(api)

    closed = validate_success(api.close_fault_event(world["fault_event"]["id"], ENGINEER))
    assert closed["triage_state"] == TRIAGE_CLOSED
    assert_two_dp(closed["downtime_hours"], 81, "downtime_hours")
    assert_two_dp(closed["lost_energy_kwh"], 162000.00, "lost_energy_kwh")

    turbine = read_turbine(api, world["t1"]["id"])
    assert_two_dp(turbine["counted_downtime_hours_period"], 81, "counted downtime")

    agreement = read_agreement(api, world["agreement"]["id"])
    assert_four_dp(agreement["projected_shortfall_pct"], 8.2500, "projected_shortfall_pct")
    assert agreement["at_risk_flag"] is True

    order = read_work_order(api, world["order"]["id"])
    # The at-risk term now contributes 20, and three whole days of ageing contribute 10 * 3/30.
    assert_two_dp(order["priority_score"], 75.00, "priority_score after the cascade")
    assert order["state"] == WO_SUBMITTED, (
        "the re-score must arrive by cascade, not by a state change"
    )


def test_blade_severity_rounds_each_weighted_term_before_summing(api: WindOpsApiClient):
    """PRD 3.6: "Each of the four weighted terms is rounded half up to two decimal places
    **first**; the four already-rounded terms are then added; and the resulting sum is rounded
    half up to two decimal places again. Summing at full precision and rounding once is the wrong
    order and yields a different figure."

    Design: Difficulty/combinatorial_formula/blade_damage_severity_score_rounds_each_weighted_factor_before_summing
    """
    world = setup_blade_severity_scenario(api)

    finding = validate_success(
        api.record_blade_damage(
            world["t1"]["id"],
            blade_damage_payload(
                inspection_method="ROPE_ACCESS",
                blade_position="B",
                inspected_at="2026-05-30T09:00:00Z",
                damage_category=4,
                damage_type="DELAMINATION",
                chord_position_pct=30.0,
                damage_length_mm=700,
                exposed_area_cm2=1000,
            ),
            ENGINEER,
        ),
        201,
    )

    # 24.00 + 25.50 + 4.67 + 6.67, each weighted term rounded before the sum.
    assert_two_dp(finding["severity_score"], 60.84, "severity_score")
    assert finding["severity_score"] != 60.83, (
        "60.83 is the figure a sum-then-round implementation produces"
    )


def test_blade_severity_band_and_repair_due_days_follow_from_the_score(api: WindOpsApiClient):
    """PRD 3.6: "`repair_priority_band` is `CRITICAL` when `severity_score` is at least 80, `HIGH`
    when it is at least 60 but below 80, `MEDIUM` when it is at least 40 but below 60, and `LOW`
    otherwise. `repair_due_days` follows directly from the band: 14 days for `CRITICAL`, 45 for
    `HIGH`, 120 for `MEDIUM` and 365 for `LOW`."

    Design: Difficulty/combinatorial_formula/blade_damage_severity_score_rounds_each_weighted_factor_before_summing
    """
    world = setup_blade_severity_scenario(api)

    finding = validate_success(
        api.record_blade_damage(
            world["t1"]["id"],
            blade_damage_payload(
                inspection_method="ROPE_ACCESS",
                blade_position="B",
                inspected_at="2026-05-30T09:00:00Z",
                damage_category=4,
                damage_type="DELAMINATION",
                chord_position_pct=30.0,
                damage_length_mm=700,
                exposed_area_cm2=1000,
            ),
            ENGINEER,
        ),
        201,
    )

    assert finding["repair_priority_band"] == BAND_HIGH
    assert finding["repair_due_days"] == 45
    assert finding["state"] == BLADE_OPEN
    assert finding["recorded_by_user_id"] == "rel-1"


def test_crane_volume_credit_tier_is_keyed_on_the_subtotal_not_the_total(
    api: WindOpsApiClient,
):
    """PRD 3.7: "The tier is keyed on the step-5 subtotal, never on the post-credit total — keying
    it on the total is a circular reading and produces a different credit."

    Design: Difficulty/combinatorial_formula/crane_cost_tier_keyed_on_subtotal_then_waterfall_allocated_by_created_at
    """
    world = setup_crane_waterfall_scenario(api)
    crane_id = world["crane"]["id"]

    first = validate_success(api.reserve_crane(world["r1"]["id"], crane_id, PLANNER))
    assert first["state"] == REPLACEMENT_CRANE_RESERVED
    # 15 lift hours over a 10-hour lift day, plus two standby dates.
    assert_crane_costs(
        read_crane(api, crane_id),
        lift_days=2,
        billable_days=4,
        subtotal_cents=12960000,
        volume_credit_cents=388800,
        total_crane_cost_cents=12571200,
    )

    validate_success(api.reserve_crane(world["r2"]["id"], crane_id, PLANNER))
    crane = read_crane(api, crane_id)
    assert crane["state"] == CRANE_MOBILIZED
    assert crane["reserved_replacement_count"] == 2
    # 23 lift hours now need three lift days; the 15,200,000 cent subtotal keys the 6 percent
    # tier, which the post-credit total of 14,288,000 would not.
    assert_crane_costs(
        crane,
        lift_days=3,
        standby_days=2,
        billable_days=5,
        subtotal_cents=15200000,
        volume_credit_cents=912000,
        total_crane_cost_cents=14288000,
    )
    assert crane["volume_credit_cents"] != 428640, (
        "428640 is the credit a tier keyed on the post-credit total would produce"
    )


def test_crane_waterfall_gives_the_floor_remainder_to_the_earliest_member(
    api: WindOpsApiClient,
):
    """PRD 3.7: "The remainder — `total_crane_cost_cents` minus the sum of the provisional shares —
    is assigned **in its entirety** to the reserved member with the earliest `created_at`, and
    every other member's `allocated_crane_cost_cents` is its provisional share unchanged."

    Design: Difficulty/combinatorial_formula/crane_cost_tier_keyed_on_subtotal_then_waterfall_allocated_by_created_at
    """
    world = setup_crane_waterfall_scenario(api)
    crane_id = world["crane"]["id"]

    validate_success(api.reserve_crane(world["r1"]["id"], crane_id, PLANNER))
    validate_success(api.reserve_crane(world["r2"]["id"], crane_id, PLANNER))

    r1 = read_replacement(api, world["r1"]["id"])
    r2 = read_replacement(api, world["r2"]["id"])
    crane = read_crane(api, crane_id)

    assert_cents(r1["allocated_crane_cost_cents"], 9318261, "R1 allocation")
    assert_cents(r2["allocated_crane_cost_cents"], 4969739, "R2 allocation")
    assert (
        r1["allocated_crane_cost_cents"] + r2["allocated_crane_cost_cents"]
        == crane["total_crane_cost_cents"]
    ), "the allocations must exhaust the total exactly"
    assert r1["created_at"] <= r2["created_at"], (
        "R1 was planned first, so it carries the floor remainder"
    )
