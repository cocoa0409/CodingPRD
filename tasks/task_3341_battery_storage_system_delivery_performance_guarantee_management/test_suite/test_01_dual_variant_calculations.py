"""Dual-variant calculation tests: the same inputs split by which branch of a
two-variant formula applies (warranty credit variants; capacity-test basis)."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_performance_test,
    assert_warranty_claim,
    create_claim_under_review,
    get_success_data,
    schedule_performance_test,
    setup_executed_project,
    validate_error,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
PERF = TEST_USERS["performance_engineer_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]


class TestWarrantyCreditVariants:
    def test_straight_line_and_output_based_credits_diverge(self, api):
        """PRD §3.7: "Under `STRAIGHT_LINE`, the `credit_amount_cents` is the
        claimed loss multiplied by the agreement's `price_per_mwh_cents`,
        rounded up to the next whole cent."
        PRD §3.7: "Under `OUTPUT_BASED`, the decide payload must also supply a
        `throughput_mwh` greater than zero, and the credit is the claimed loss
        multiplied by the throughput, multiplied by the agreement's
        `guaranteed_rte_pct`, multiplied by the unit price, multiplied by one
        minus the guaranteed efficiency — the degradation rate — with the
        entire expression evaluated in exact arithmetic and rounded half up to
        integer cents exactly once at the end."

        Design: Difficulty/dual_variant_calc/warranty_credit_straight_vs_output_divergence
        """
        _, esa = setup_executed_project(
            api=api,
            esa_overrides={"guaranteed_rte_pct": 0.88, "price_per_mwh_cents": 300000},
        )
        claim1 = create_claim_under_review(esa["id"], api=api, claimed_capacity_loss_mwh=0.05)
        claim2 = create_claim_under_review(esa["id"], api=api, claimed_capacity_loss_mwh=0.05)

        data1 = validate_success(
            api.decide_claim(
                claim1["id"],
                {"decision": "APPROVED", "credit_variant": "STRAIGHT_LINE"},
                WARRANTY,
            )
        )
        data2 = validate_success(
            api.decide_claim(
                claim2["id"],
                {
                    "decision": "APPROVED",
                    "credit_variant": "OUTPUT_BASED",
                    "throughput_mwh": 450,
                },
                WARRANTY,
            )
        )
        assert data1["credit_amount_cents"] == 15000, (
            f"STRAIGHT_LINE: ceil(0.05 * 300000) == 15000, got {data1['credit_amount_cents']}"
        )
        assert data2["credit_amount_cents"] == 712800, (
            "OUTPUT_BASED: round_half_up(0.05 * 450 * 0.88 * 300000 * 0.12) == 712800, "
            f"got {data2['credit_amount_cents']}"
        )
        assert data1["credit_amount_cents"] != data2["credit_amount_cents"]

    def test_straight_line_rounds_up_to_next_whole_cent(self, api):
        """PRD §3.7: "Under `STRAIGHT_LINE`, the `credit_amount_cents` is the
        claimed loss multiplied by the agreement's `price_per_mwh_cents`,
        rounded up to the next whole cent."

        Design: Difficulty/dual_variant_calc/warranty_credit_straight_vs_output_divergence
        """
        _, esa = setup_executed_project(api=api)
        # 0.007 * 300000 = 2100 exactly; 0.0073 * 300000 = 2190.0000000000 -> 2190
        # Use a fractional product: 0.01333 * 300000 = 3999.0 exactly; pick
        # 0.013334 * 300000 = 4000.2 -> ceil -> 4001.
        claim = create_claim_under_review(
            esa["id"], api=api, claimed_capacity_loss_mwh=0.013334
        )
        data = validate_success(
            api.decide_claim(
                claim["id"],
                {"decision": "APPROVED", "credit_variant": "STRAIGHT_LINE"},
                WARRANTY,
            )
        )
        # 0.013334 * 300000 = 4000.2 -> rounded up to the next whole cent = 4001
        assert data["credit_amount_cents"] == 4001, (
            f"ceil(0.013334 * 300000) == 4001, got {data['credit_amount_cents']}"
        )
        assert_warranty_claim(data)


class TestCapacityTestBasisSplit:
    def test_same_measurement_passes_nameplate_fails_poi(self, api):
        """PRD §3.4: "Under the `POI` basis the auxiliary load is subtracted, so
        `evaluated_capacity_mwh` is the measured discharge energy minus the
        auxiliary load; under the `NAMEPLATE` basis the auxiliary load is
        ignored and the evaluated capacity equals the raw measurement."
        PRD §3.4: "The system derives `measurement_basis` at scheduling time:
        `NAMEPLATE` for `FREQUENCY_REGULATION` projects, `POI` for everything
        else."

        Design: Difficulty/dual_variant_calc/capacity_test_basis_split_poi_vs_nameplate
        """
        # Project A: ENERGY_ARBITRAGE -> POI basis
        proj_a, _ = setup_executed_project(
            api=api, esa_overrides={"guaranteed_capacity_mwh": 38.5}
        )
        # Project B: FREQUENCY_REGULATION -> NAMEPLATE basis
        proj_b, _ = setup_executed_project(
            api=api,
            project_overrides={
                "market_application": "FREQUENCY_REGULATION",
                "duty_cycle_profile": "CONTINUOUS",
            },
            esa_overrides={"guaranteed_capacity_mwh": 38.5},
        )
        test_a = schedule_performance_test(
            proj_a["id"], "CAPACITY_TEST",
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", api=api,
        )
        test_b = schedule_performance_test(
            proj_b["id"], "CAPACITY_TEST",
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", api=api,
        )

        data_a = validate_success(
            api.record_test_results(
                test_a["id"], {"measured_capacity_mwh": 39.0, "aux_load_mwh": 1.0}, PERF
            )
        )
        data_b = validate_success(
            api.record_test_results(
                test_b["id"], {"measured_capacity_mwh": 39.0, "aux_load_mwh": 1.0}, PERF
            )
        )
        assert data_a["measurement_basis"] == "POI"
        assert data_a["evaluated_capacity_mwh"] == pytest.approx(38.0, abs=0.001), (
            f"POI: 39.0 - 1.0 == 38.0, got {data_a['evaluated_capacity_mwh']}"
        )
        assert data_a["result"] == "FAIL" and data_a["status"] == "FAILED", (
            f"38.0 < 38.5 must FAIL, got {data_a['result']}"
        )
        assert data_b["measurement_basis"] == "NAMEPLATE"
        assert data_b["evaluated_capacity_mwh"] == pytest.approx(39.0, abs=0.001), (
            f"NAMEPLATE: raw 39.0, got {data_b['evaluated_capacity_mwh']}"
        )
        assert data_b["result"] == "PASS" and data_b["status"] == "PASSED", (
            f"39.0 >= 38.5 must PASS, got {data_b['result']}"
        )

    def test_poi_subtraction_is_decisive_at_the_boundary(self, api):
        """PRD §3.4: "the test `result` is `PASS` when the evaluated capacity is
        greater than or equal to the active agreement's
        `guaranteed_capacity_mwh` — equality passes — and `FAIL` otherwise."

        Design: Difficulty/dual_variant_calc/capacity_test_basis_split_poi_vs_nameplate
        """
        # Same raw measurement 38.5: NAMEPLATE evaluates 38.5 (== guarantee,
        # equality passes); POI subtracts aux 0.5 -> 38.0 < 38.5 fails.
        proj_a, _ = setup_executed_project(
            api=api, esa_overrides={"guaranteed_capacity_mwh": 38.5}
        )
        proj_b, _ = setup_executed_project(
            api=api,
            project_overrides={
                "market_application": "FREQUENCY_REGULATION",
                "duty_cycle_profile": "CONTINUOUS",
            },
            esa_overrides={"guaranteed_capacity_mwh": 38.5},
        )
        test_a = schedule_performance_test(
            proj_a["id"], "CAPACITY_TEST",
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", api=api,
        )
        test_b = schedule_performance_test(
            proj_b["id"], "CAPACITY_TEST",
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", api=api,
        )
        data_a = validate_success(
            api.record_test_results(
                test_a["id"], {"measured_capacity_mwh": 38.5, "aux_load_mwh": 0.5}, PERF
            )
        )
        data_b = validate_success(
            api.record_test_results(
                test_b["id"], {"measured_capacity_mwh": 38.5, "aux_load_mwh": 0.5}, PERF
            )
        )
        assert data_a["result"] == "FAIL" and data_a["status"] == "FAILED"
        assert data_a["evaluated_capacity_mwh"] == pytest.approx(38.0, abs=0.001)
        assert data_b["result"] == "PASS" and data_b["status"] == "PASSED"
        assert data_b["evaluated_capacity_mwh"] == pytest.approx(38.5, abs=0.001)
        assert_performance_test(data_a)
        assert_performance_test(data_b)
