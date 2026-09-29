"""The rotor's two cage routes, their join at machining and the air-gap window."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_AIR_GAP_OUT_OF_TOLERANCE,
    ERR_ROTOR_BAR_COUNT_MISMATCH,
    ERR_ROTOR_CONSTRUCTION_MISMATCH,
)


def _two_designs_with_planned_rotors(plant):
    """A cast-aluminium work order and a fabricated-copper one, each with a rotor."""
    plant.add_distributor()
    cast_design = plant.add_design(F.motor_design_payload())
    plant.release_design()
    copper_design = plant.add_design(F.premium_motor_design_payload())
    plant.release_design(copper_design)
    cast_order = plant.add_order()
    plant.confirm_order(cast_order)
    copper_order = plant.add_order(design=copper_design)
    plant.confirm_order(copper_order)
    cast_work_order = plant.add_work_order(order=cast_order, design=cast_design)
    copper_work_order = plant.add_work_order(order=copper_order, design=copper_design)
    cast_rotor = plant.add_rotor(work_order=cast_work_order)
    copper_rotor = plant.add_rotor(
        work_order=copper_work_order, headers=U.BUILD_TECHNICIAN_OTHER
    )
    assert cast_rotor["construction"] == "DIE_CAST_ALUMINUM"
    assert copper_rotor["construction"] == "FABRICATED_COPPER"
    assert cast_rotor["status"] == "PLANNED"
    assert copper_rotor["status"] == "PLANNED"
    return cast_work_order, copper_work_order, cast_rotor, copper_rotor


def test_die_cast_fork_writes_the_aluminium_cage_property_triple(plant):
    """The cast route stores its own two measurements and the aluminium triple.

    PRD 3.7: "On success `melt_temp_c` and `die_preheat_c` are stored, the cage
    property triple takes its aluminium values — `cage_conductivity_ratio` 0.62,
    `slip_penalty_pct` 1.8, `rotor_process_cost_cents` 18000 — and the build
    moves `PLANNED → CAST_POURED`."

    Design: Difficulty/non_linear_state_machine/rotor_cage_fork_join_die_cast_vs_brazed_bar_convergence
    """
    _cast_wo, _copper_wo, cast_rotor, _copper_rotor = _two_designs_with_planned_rotors(
        plant
    )

    poured = plant.form_cage(
        rotor=cast_rotor,
        payload=F.die_cast_cage_payload(melt_temp_c=700.0, die_preheat_c=260.0),
    )

    assert poured["status"] == "CAST_POURED"
    assert poured["cage_conductivity_ratio"] == 0.62
    assert poured["slip_penalty_pct"] == 1.8
    assert poured["rotor_process_cost_cents"] == 18000
    assert poured["melt_temp_c"] == 700.0
    assert poured["die_preheat_c"] == 260.0
    assert poured["braze_alloy"] is None
    assert poured["bar_count"] is None
    assert poured["construction"] == "DIE_CAST_ALUMINUM"
    assert poured["rotor_tech_user_id"] == U.USER_BUILD_TECHNICIAN


def test_the_copper_rotor_refuses_the_cast_method_and_a_foreign_bar_count(api, plant):
    """Two different 409s guard the brazed fork before it will accept the cage.

    PRD 3.7: "This branch performs one extra cross-check the die-cast branch does
    not: `bar_count` must equal the pinned design's `rotor_bar_count`, and a
    mismatch is refused with `ERR_ROTOR_BAR_COUNT_MISMATCH` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/rotor_cage_fork_join_die_cast_vs_brazed_bar_convergence
    """
    _cast_wo, _copper_wo, _cast_rotor, copper_rotor = _two_designs_with_planned_rotors(
        plant
    )

    wrong_fork = api.form_rotor_cage(
        copper_rotor["id"],
        F.die_cast_cage_payload(melt_temp_c=700.0, die_preheat_c=260.0),
        U.BUILD_TECHNICIAN_OTHER,
    )
    validate_error(wrong_fork, ERR_ROTOR_CONSTRUCTION_MISMATCH, 409)
    assert plant.get_rotor(copper_rotor)["status"] == "PLANNED"

    wrong_bars = api.form_rotor_cage(
        copper_rotor["id"],
        F.brazed_bar_cage_payload(bar_count=34, braze_alloy="AgCu-25"),
        U.BUILD_TECHNICIAN_OTHER,
    )

    validate_error(wrong_bars, ERR_ROTOR_BAR_COUNT_MISMATCH, 409)
    still_planned = plant.get_rotor(copper_rotor)
    assert still_planned["status"] == "PLANNED"
    assert still_planned["bar_count"] is None
    assert still_planned["cage_conductivity_ratio"] is None
    brazed = validate_success(
        api.form_rotor_cage(
            copper_rotor["id"],
            F.brazed_bar_cage_payload(bar_count=40, braze_alloy="AgCu-25"),
            U.BUILD_TECHNICIAN_OTHER,
        )
    )
    assert brazed["status"] == "BARS_BRAZED"
    assert brazed["cage_conductivity_ratio"] == 1.0
    assert brazed["slip_penalty_pct"] == 0.6
    assert brazed["rotor_process_cost_cents"] == 47500
    assert brazed["braze_alloy"] == "AgCu-25"
    assert brazed["bar_count"] == 40
    assert brazed["melt_temp_c"] is None
    assert brazed["die_preheat_c"] is None


def test_both_cage_routes_join_at_machined_and_balance_identically(plant):
    """Cast and brazed rotors reach MACHINED and then ACCEPTED the same way.

    PRD 3.7: "**Machining** is the join point: both `CAST_POURED` and
    `BARS_BRAZED` converge on it with identical downstream behaviour, and from any
    other status the request is refused with `ERR_INVALID_SUBASSEMBLY_STATE`."

    Design: Difficulty/non_linear_state_machine/rotor_cage_fork_join_die_cast_vs_brazed_bar_convergence
    """
    cast_wo, copper_wo, cast_rotor, copper_rotor = _two_designs_with_planned_rotors(
        plant
    )
    plant.form_cage(
        rotor=cast_rotor,
        payload=F.die_cast_cage_payload(melt_temp_c=700.0, die_preheat_c=260.0),
    )
    plant.form_cage(
        rotor=copper_rotor,
        payload=F.brazed_bar_cage_payload(bar_count=40, braze_alloy="AgCu-25"),
        headers=U.BUILD_TECHNICIAN_OTHER,
    )

    machined_cast = plant.machine_rotor(
        rotor=cast_rotor, measured_rotor_od_mm=134.500, rotor_mass_kg=18.6
    )
    machined_copper = plant.machine_rotor(
        rotor=copper_rotor,
        headers=U.BUILD_TECHNICIAN_OTHER,
        measured_rotor_od_mm=147.000,
        rotor_mass_kg=22.0,
    )

    assert machined_cast["status"] == "MACHINED"
    assert machined_copper["status"] == "MACHINED"
    A.assert_rounded_to(
        machined_cast["measured_air_gap_mm"], 0.450, 3, "measured_air_gap_mm"
    )
    A.assert_rounded_to(
        machined_cast["air_gap_deviation_mm"], 0, 3, "air_gap_deviation_mm"
    )
    A.assert_rounded_to(
        machined_copper["measured_air_gap_mm"], 0.500, 3, "measured_air_gap_mm"
    )
    A.assert_rounded_to(
        machined_copper["air_gap_deviation_mm"], 0, 3, "air_gap_deviation_mm"
    )
    accepted_cast = plant.balance_rotor(
        "ACCEPTED",
        rotor=cast_rotor,
        initial_unbalance_g_mm=820.0,
        residual_unbalance_g_mm=240.0,
    )
    accepted_copper = plant.balance_rotor(
        "ACCEPTED",
        rotor=copper_rotor,
        initial_unbalance_g_mm=900.0,
        residual_unbalance_g_mm=300.0,
    )
    assert accepted_cast["status"] == "ACCEPTED"
    assert accepted_copper["status"] == "ACCEPTED"
    A.assert_rounded_to(
        accepted_cast["permissible_unbalance_g_mm"],
        A.expected_permissible_unbalance_g_mm("G2_5", 18.6, 4),
        1,
        "permissible_unbalance_g_mm",
    )
    A.assert_rounded_to(
        accepted_copper["permissible_unbalance_g_mm"],
        A.expected_permissible_unbalance_g_mm("G2_5", 22.0, 4),
        1,
        "permissible_unbalance_g_mm",
    )
    assert accepted_cast["permissible_unbalance_g_mm"] == 296.0
    assert accepted_copper["permissible_unbalance_g_mm"] == 350.1
    assert plant.get_work_order(cast_wo)["build_status"] == "RELEASED"
    assert plant.get_work_order(copper_wo)["build_status"] == "RELEASED"


def _cast_rotor_ready_to_machine(plant):
    """A single cast-aluminium rotor sitting in CAST_POURED on work order one."""
    plant.add_distributor()
    plant.add_design(F.motor_design_payload())
    plant.release_design()
    plant.add_order()
    plant.confirm_order()
    plant.add_work_order()
    plant.add_rotor()
    return plant.form_cage()


def test_air_gap_deviation_one_thousandth_beyond_tolerance_is_refused(api, plant):
    """An OD of 134.380 yields a 0.060 mm deviation against a 0.050 mm tolerance.

    PRD 3.7: "The absolute value of that deviation must not exceed the design's
    `air_gap_tolerance_mm`; a deviation whose magnitude exactly equals the
    tolerance is accepted, while one thousandth of a millimetre beyond it is
    refused with `ERR_AIR_GAP_OUT_OF_TOLERANCE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/air_gap_deviation_exactly_at_tolerance_accepted_one_thousandth_beyond_rejected
    """
    poured = _cast_rotor_ready_to_machine(plant)
    assert poured["status"] == "CAST_POURED"
    assert A.expected_air_gap_deviation_mm(135.400, 134.380, 0.450) == A.dec("0.060")

    refused = api.machine_rotor_build(
        poured["id"],
        F.machine_payload(measured_rotor_od_mm=134.380, rotor_mass_kg=18.6),
        U.BUILD_TECHNICIAN,
    )

    validate_error(refused, ERR_AIR_GAP_OUT_OF_TOLERANCE, 422)
    stored = plant.get_rotor()
    assert stored["status"] == "CAST_POURED"
    assert stored["measured_air_gap_mm"] is None
    assert stored["air_gap_deviation_mm"] is None
    assert stored["measured_rotor_od_mm"] is None


def test_air_gap_deviation_exactly_at_the_tolerance_is_accepted(plant):
    """An OD of 134.400 halves to a 0.500 mm gap and a 0.050 mm deviation.

    PRD 3.7: "From the outer diameter the server derives the air gap:
    `measured_air_gap_mm` is the pinned design's `stator_bore_id_mm` minus
    `measured_rotor_od_mm`, halved, rounded to three decimal places — the gap is
    radial, which is why the diametral difference is halved."

    Design: Difficulty/boundary_precision_check/air_gap_deviation_exactly_at_tolerance_accepted_one_thousandth_beyond_rejected
    """
    _cast_rotor_ready_to_machine(plant)

    machined = plant.machine_rotor(measured_rotor_od_mm=134.400, rotor_mass_kg=18.6)

    assert machined["status"] == "MACHINED"
    A.assert_rounded_to(
        machined["measured_air_gap_mm"],
        A.expected_air_gap_mm(135.400, 134.400),
        3,
        "measured_air_gap_mm",
    )
    A.assert_rounded_to(
        machined["air_gap_deviation_mm"],
        A.expected_air_gap_deviation_mm(135.400, 134.400, 0.450),
        3,
        "air_gap_deviation_mm",
    )
    A.assert_rounded_to(machined["measured_air_gap_mm"], 0.500, 3, "measured_air_gap_mm")
    A.assert_rounded_to(
        machined["air_gap_deviation_mm"], 0.050, 3, "air_gap_deviation_mm"
    )
    A.assert_decimal_width(machined["air_gap_deviation_mm"], 3, "air_gap_deviation_mm")
    A.assert_rounded_to(
        machined["measured_rotor_od_mm"], 134.400, 3, "measured_rotor_od_mm"
    )
