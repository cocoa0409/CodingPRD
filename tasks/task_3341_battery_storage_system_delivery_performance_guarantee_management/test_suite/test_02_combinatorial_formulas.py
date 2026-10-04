"""Combinatorial formula tests: multi-input forward projection and the pinned
single-final-rounding order of the output-based warranty credit."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_claim_under_review,
    get_success_data,
    setup_commissioned_project,
    setup_executed_project,
    setup_executed_augmentation,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
PERF = TEST_USERS["performance_engineer_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]


class TestAugmentationRequirementProjection:
    def test_projection_combines_commissioned_augmentations_and_degradation(self, api):
        """PRD §3.5: "The projection starts from `commissioned_capacity_mwh`,
        adds the `added_capacity_mwh` of every augmentation event in `EXECUTED`
        status — `PLANNED` and `CANCELLED` events never contribute — and
        subtracts degradation of a per-cycle rate multiplied by the stored
        `equivalent_cycles`. The per-cycle rate depends on the project's market
        application and duty cycle: for `ENERGY_ARBITRAGE` it is 0.0006 under
        `ONE_CYCLE_DAILY`, 0.0012 under `TWO_CYCLES_DAILY`, and 0.0015 under
        `CONTINUOUS`"
        PRD §3.5: "Each executed augmentation then attracts a planning penalty:
        the number of executed events times 0.5 percent times the excess of the
        pre-penalty projection over the 80 MWh floor — nothing below the floor
        is penalized, and the excess is floored at zero."

        Design: Difficulty/combinatorial_formula/augmentation_requirement_multi_input_forward_projection
        """
        project, esa = setup_commissioned_project(api=api)
        assert project["commissioned_capacity_mwh"] == pytest.approx(40, abs=0.001)

        project, aug = setup_executed_augmentation(
            project, esa, added_capacity_mwh=2, api=api
        )
        data = validate_success(
            api.recompute_projection(project["id"], {"equivalent_cycles": 600}, PERF)
        )
        # 40 + 2 - 600 * 0.0006 = 41.64; pre-penalty 41.64 < 80 floor -> no penalty
        assert data["projected_capacity_mwh"] == pytest.approx(41.64, abs=0.001), (
            f"40 + 2 - 600*0.0006 == 41.64, got {data['projected_capacity_mwh']}"
        )
        assert data["equivalent_cycles"] == 600
        assert data["augmentation_count"] == 1

    def test_penalty_applies_above_eighty_mwh_floor(self, api):
        """PRD §3.5: "Each executed augmentation then attracts a planning
        penalty: the number of executed events times 0.5 percent times the
        excess of the pre-penalty projection over the 80 MWh floor — nothing
        below the floor is penalized, and the excess is floored at zero.
        `projected_capacity_mwh` is the pre-penalty projection minus that
        penalty, rounded half up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/augmentation_requirement_multi_input_forward_projection
        """
        # Big plant: commissioned 100 MWh, one executed augmentation of 5 MWh,
        # 0 cycles -> pre-penalty 105; penalty = 1 * 0.005 * (105 - 80) = 0.125
        # -> projected = 104.875 -> round_half_up 2dp -> 104.88.
        project, esa = setup_commissioned_project(
            api=api,
            project_overrides={"rated_energy_mwh": 100},
            esa_overrides={
                "contracted_energy_mwh": 100,
                "guaranteed_capacity_mwh": 95,
                "price_per_mwh_cents": 100000,
            },
        )
        assert project["commissioned_capacity_mwh"] == pytest.approx(100, abs=0.001)
        project, aug = setup_executed_augmentation(
            project, esa, added_capacity_mwh=5, api=api
        )
        data = validate_success(
            api.recompute_projection(project["id"], {"equivalent_cycles": 0}, PERF)
        )
        # pre-penalty = 100 + 5 = 105; penalty = 0.005 * 25 = 0.125 -> 104.875 -> 104.88
        assert data["projected_capacity_mwh"] == pytest.approx(104.88, abs=0.001), (
            f"105 - 0.005*(105-80) == 104.875 -> 104.88, got {data['projected_capacity_mwh']}"
        )
        assert data["augmentation_count"] == 1


class TestWarrantyOutputBasedPinnedOrder:
    def test_output_based_credit_single_final_rounding(self, api):
        """PRD §2.7: "Where a calculation specifies a single final rounding,
        the full expression is evaluated in exact arithmetic and rounded once
        at the end; no intermediate rounding is permitted."
        PRD §3.7: "Under `OUTPUT_BASED`, the decide payload must also supply a
        `throughput_mwh` greater than zero, and the credit is the claimed loss
        multiplied by the throughput, multiplied by the agreement's
        `guaranteed_rte_pct`, multiplied by the unit price, multiplied by one
        minus the guaranteed efficiency — the degradation rate — with the
        entire expression evaluated in exact arithmetic and rounded half up to
        integer cents exactly once at the end."

        Design: Difficulty/combinatorial_formula/warranty_output_based_pinned_evaluation_order
        """
        _, esa = setup_executed_project(
            api=api,
            esa_overrides={"guaranteed_rte_pct": 0.88, "price_per_mwh_cents": 300000},
        )
        claim = create_claim_under_review(
            esa["id"], api=api, defect_type="CAPACITY_SHORTFALL",
            claimed_capacity_loss_mwh=0.05,
        )
        data = validate_success(
            api.decide_claim(
                claim["id"],
                {
                    "decision": "APPROVED",
                    "credit_variant": "OUTPUT_BASED",
                    "throughput_mwh": 450,
                },
                WARRANTY,
            )
        )
        # 0.05 * 450 * 0.88 * 300000 * (1 - 0.88) = 712800 exactly
        assert data["credit_amount_cents"] == 712800, (
            f"exact arithmetic single-round: 712800, got {data['credit_amount_cents']}"
        )
        assert data["status"] == "APPROVED"
        assert data["decided_at"] is not None

    def test_output_based_credit_rounds_half_up_once(self, api):
        """PRD §2.7: "Where a calculation specifies a single final rounding,
        the full expression is evaluated in exact arithmetic and rounded once
        at the end; no intermediate rounding is permitted."
        PRD §3.7: "with the entire expression evaluated in exact arithmetic and
        rounded half up to integer cents exactly once at the end."

        Design: Difficulty/combinatorial_formula/warranty_output_based_pinned_evaluation_order
        """
        # Construct a value with a half-cent residue: loss 0.07, throughput 11,
        # rte 0.5, price 99999, degradation 0.5:
        # 0.07 * 11 * 0.5 * 99999 * 0.5 = 19249.8075 -> half-up -> 19250.
        _, esa = setup_executed_project(
            api=api,
            esa_overrides={"guaranteed_rte_pct": 0.5, "price_per_mwh_cents": 99999},
        )
        claim = create_claim_under_review(
            esa["id"], api=api, claimed_capacity_loss_mwh=0.07
        )
        data = validate_success(
            api.decide_claim(
                claim["id"],
                {
                    "decision": "APPROVED",
                    "credit_variant": "OUTPUT_BASED",
                    "throughput_mwh": 11,
                },
                WARRANTY,
            )
        )
        # 0.07 * 11 = 0.77; * 0.5 = 0.385; * 99999 = 38499.615; * 0.5 = 19249.8075
        # round_half_up -> 19250
        assert data["credit_amount_cents"] == 19250, (
            f"single final round_half_up(19249.8075) == 19250, got {data['credit_amount_cents']}"
        )
        assert data["status"] == "APPROVED"
