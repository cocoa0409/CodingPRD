"""Bench efficiency: the rounding order and the two test-method variants."""

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.fixtures import build_plant

BENCH = F.record_results_payload()
SECOND_WINDOW_START = F.instant(F.TEST_DAY, 11, 0)
SECOND_WINDOW_END = F.instant(F.TEST_DAY, 13, 0)


def _second_tested_work_order(plant, test_method, **record_overrides):
    """A sibling work order taken to ASSEMBLED and tested in the 11:00-13:00Z window."""
    second_order = plant.add_order()
    plant.confirm_order(second_order)
    work_order = plant.add_work_order(order=second_order)
    stator = plant.add_stator(work_order=work_order, headers=U.BUILD_TECHNICIAN_OTHER)
    plant.impregnate_stator(
        stator=stator,
        headers=U.BUILD_TECHNICIAN_OTHER,
        impregnation_window_start=F.SECOND_IMPREGNATION_WINDOW_START,
        impregnation_window_end=F.SECOND_IMPREGNATION_WINDOW_END,
    )
    plant.surge_test_stator(stator=stator)
    plant.disposition_stator("ACCEPTED", stator=stator)
    rotor = plant.add_rotor(work_order=work_order, headers=U.BUILD_TECHNICIAN_OTHER)
    plant.form_cage(rotor=rotor, headers=U.BUILD_TECHNICIAN_OTHER)
    plant.machine_rotor(rotor=rotor, headers=U.BUILD_TECHNICIAN_OTHER)
    plant.balance_rotor("ACCEPTED", rotor=rotor)
    plant.add_assembly(
        work_order=work_order,
        stator=stator,
        rotor=rotor,
        headers=U.BUILD_TECHNICIAN_OTHER,
    )
    scheduled = plant.schedule_test(
        work_order=work_order,
        window_start=SECOND_WINDOW_START,
        window_end=SECOND_WINDOW_END,
        dyno_draw_kw=12.0,
        test_method=test_method,
    )
    return work_order, plant.record_test(test=scheduled, **record_overrides)


def test_loss_components_are_rounded_before_they_are_summed(api):
    """221.0 plus 40.1 gives 528.1 W and 93.42 percent, not 528.125 and 93.41.

    PRD 3.8: "`total_loss_w` is then the sum of the five components
    `stator_loss_corrected_w`, `rotor_loss_w`, `core_loss_w`,
    `friction_windage_w` and `stray_load_loss_w`, each already rounded to one
    decimal place before the addition."

    Design: Difficulty/combinatorial_formula/measured_efficiency_component_round_then_sum_order
    """
    plant = build_plant(api, "test_scheduled", test={"dyno_draw_kw": 12.0})

    completed = plant.record_test()

    assert completed["stator_loss_corrected_w"] == 221.0
    assert completed["stray_load_loss_w"] == 40.1
    assert completed["total_loss_w"] == 528.1
    assert completed["measured_efficiency_pct"] == 93.42
    assert completed["measured_efficiency_pct"] != 93.41
    A.assert_performance_test_figures(completed, BENCH, "IEC_60034_2_1_SUMMATION", 4)
    assert completed["achieved_class"] == "IE3"
    assert completed["status"] == "COMPLETED"
    assert completed["test_engineer_user_id"] == U.USER_TEST_ENGINEER
    assert plant.get_work_order()["build_status"] == "TESTED"


def test_the_same_bench_data_at_forty_degrees_diverges_between_the_two_methods(api):
    """The itemised budget reads 93.42 where the direct measurement reads 93.52.

    PRD 3.8: "Because the summation variant carries the temperature correction and
    the direct variant does not, the divergence between them grows with ambient
    temperature, and the same bench numbers can land the two variants on
    different classes and on opposite sides of a regulatory minimum."

    Design: Difficulty/dual_variant_calc/test_summation_vs_direct_efficiency_divergence_at_40c
    """
    plant = build_plant(api, "test_scheduled", test={"dyno_draw_kw": 12.0})
    summation = plant.record_test()

    _second_work_order, direct = _second_tested_work_order(
        plant, "IEEE_112_B_DYNAMOMETER"
    )

    assert summation["test_method"] == "IEC_60034_2_1_SUMMATION"
    assert direct["test_method"] == "IEEE_112_B_DYNAMOMETER"
    assert summation["measured_efficiency_pct"] == 93.42
    assert direct["measured_efficiency_pct"] == 93.52
    assert direct["measured_efficiency_pct"] != summation["measured_efficiency_pct"]
    A.assert_rounded_to(
        A.dec(direct["measured_efficiency_pct"])
        - A.dec(summation["measured_efficiency_pct"]),
        A.dec("0.10"),
        2,
        "efficiency divergence",
    )
    assert direct["stator_loss_corrected_w"] == 221.0
    assert direct["total_loss_w"] == 528.1
    assert direct["stray_load_loss_w"] == 40.1
    A.assert_performance_test_figures(direct, BENCH, "IEEE_112_B_DYNAMOMETER", 4)
    assert summation["achieved_class"] == "IE3"
    assert direct["achieved_class"] == "IE3"


def test_the_direct_variant_ignores_the_loss_fields_and_the_ambient(api):
    """Two direct tests with wildly different loss budgets read the same efficiency.

    PRD 3.8: "Under **`IEEE_112_B_DYNAMOMETER`**, efficiency is the direct
    input/output measurement: 100 multiplied by `output_power_kw` divided by
    `input_power_kw`, rounded to two decimal places."

    Design: Difficulty/dual_variant_calc/test_summation_vs_direct_efficiency_divergence_at_40c
    """
    plant = build_plant(
        api,
        "test_scheduled",
        test={"dyno_draw_kw": 12.0, "test_method": "IEEE_112_B_DYNAMOMETER"},
    )
    lean = plant.record_test()

    hot_bench = dict(
        stator_loss_w=340.0, rotor_loss_w=150.0, core_loss_w=190.0,
        friction_windage_w=70.0, ambient_temp_c=55.0,
    )
    _second_work_order, heavy = _second_tested_work_order(
        plant, "IEEE_112_B_DYNAMOMETER", **hot_bench
    )

    assert lean["measured_efficiency_pct"] == 93.52
    assert heavy["measured_efficiency_pct"] == 93.52
    assert heavy["total_loss_w"] != lean["total_loss_w"]
    assert heavy["stator_loss_corrected_w"] != lean["stator_loss_corrected_w"]
    A.assert_performance_test_figures(
        heavy,
        F.record_results_payload(**hot_bench),
        "IEEE_112_B_DYNAMOMETER",
        4,
    )
    assert lean["achieved_class"] == heavy["achieved_class"] == "IE3"


def test_the_summation_variant_drops_the_correction_at_the_reference_ambient(api):
    """At 25.0 C the stator loss is uncorrected, so 517.1 W gives 93.55 percent.

    PRD 3.8: "`stator_loss_corrected_w` applies a one-sided temperature
    correction: multiply `stator_loss_w` by one plus 0.0035 for each degree
    Celsius by which `ambient_temp_c` exceeds the 25.0 °C reference, take no
    correction at all when the ambient is at or below the reference — the
    correction is never a credit — and round to one decimal place."

    Design: Difficulty/combinatorial_formula/measured_efficiency_component_round_then_sum_order
    """
    plant = build_plant(api, "test_scheduled", test={"dyno_draw_kw": 12.0})
    reference_bench = F.record_results_payload(ambient_temp_c=25.0)

    completed = plant.record_test(ambient_temp_c=25.0)

    assert completed["stator_loss_corrected_w"] == 210.0
    assert completed["stray_load_loss_w"] == 40.1
    assert completed["total_loss_w"] == 517.1
    assert completed["measured_efficiency_pct"] == 93.55
    A.assert_performance_test_figures(
        completed, reference_bench, "IEC_60034_2_1_SUMMATION", 4
    )
    assert completed["achieved_class"] == "IE3"
    assert completed["status"] == "COMPLETED"
