"""Assembly pairing across sibling work orders and aggregate dynamometer capacity."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_SUBASSEMBLY_NOT_ACCEPTED,
    ERR_TEST_CELL_CAPACITY_EXCEEDED,
)

LATE_WINDOW_START = F.instant(F.TEST_DAY, 10, 0)
LATE_WINDOW_END = F.instant(F.TEST_DAY, 12, 0)
SHIFTED_WINDOW_START = F.instant(F.TEST_DAY, 11, 0)
SHIFTED_WINDOW_END = F.instant(F.TEST_DAY, 13, 0)


def _two_work_orders(plant, with_cell=False):
    """Design D1 released once, two confirmed orders, two open work orders."""
    plant.add_distributor()
    plant.add_oven(cooldown_buffer_minutes=45)
    if with_cell:
        plant.add_cell(max_concurrent_kw=20.0)
    plant.add_design(F.motor_design_payload())
    plant.release_design()
    first_order = plant.add_order()
    plant.confirm_order(first_order)
    second_order = plant.add_order()
    plant.confirm_order(second_order)
    return plant.add_work_order(order=first_order), plant.add_work_order(
        order=second_order
    )


def _accept_stator(plant, work_order, headers, **impregnation):
    stator = plant.add_stator(work_order=work_order, headers=headers)
    plant.impregnate_stator(
        stator=stator, headers=headers, cure_temp_c=165.0, **impregnation
    )
    plant.surge_test_stator(stator=stator)
    return plant.disposition_stator("ACCEPTED", stator=stator)


def _accept_rotor(plant, work_order, headers):
    rotor = plant.add_rotor(work_order=work_order, headers=headers)
    plant.form_cage(rotor=rotor, headers=headers)
    plant.machine_rotor(rotor=rotor, headers=headers)
    return plant.balance_rotor("ACCEPTED", rotor=rotor)


def _pairing_scene(plant):
    """WO1 holds a rejected stator, an accepted pair; WO2 holds its own stator."""
    first_work_order, second_work_order = _two_work_orders(plant)
    rejected = plant.add_stator(work_order=first_work_order)
    plant.disposition_stator("REJECTED", stator=rejected)
    accepted_stator = _accept_stator(plant, first_work_order, U.BUILD_TECHNICIAN)
    accepted_rotor = _accept_rotor(plant, first_work_order, U.BUILD_TECHNICIAN)
    foreign_stator = _accept_stator(
        plant,
        second_work_order,
        U.BUILD_TECHNICIAN_OTHER,
        impregnation_window_start=F.SECOND_IMPREGNATION_WINDOW_START,
        impregnation_window_end=F.SECOND_IMPREGNATION_WINDOW_END,
    )
    assert plant.get_work_order(first_work_order)["build_status"] == "SUBASSEMBLIES_DONE"
    assert plant.get_work_order(second_work_order)["build_status"] == "RELEASED"
    return {
        "work_order": first_work_order,
        "sibling_work_order": second_work_order,
        "rejected_stator": rejected,
        "stator": accepted_stator,
        "rotor": accepted_rotor,
        "foreign_stator": foreign_stator,
    }


def test_citing_a_rejected_predecessor_stator_is_refused(api, plant):
    """The work order is ready, but the stator it cites was written off.

    PRD 3.8: "Both cited subassemblies must belong to *this* work order and must
    both be in `ACCEPTED` status; a build belonging to another work order or in
    any other status is refused with `ERR_SUBASSEMBLY_NOT_ACCEPTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/assembly_record_requires_both_subassemblies_accepted_on_its_own_work_order
    """
    scene = _pairing_scene(plant)
    assert scene["rejected_stator"]["status"] != "ACCEPTED"

    refused = api.create_assembly_record(
        F.assembly_record_payload(
            scene["work_order"]["id"],
            scene["rejected_stator"]["id"],
            scene["rotor"]["id"],
        ),
        U.BUILD_TECHNICIAN,
    )

    validate_error(refused, ERR_SUBASSEMBLY_NOT_ACCEPTED, 409)
    assert (
        plant.get_work_order(scene["work_order"])["build_status"]
        == "SUBASSEMBLIES_DONE"
    )
    assert plant.get_stator(scene["rejected_stator"])["status"] == "REJECTED"


def test_citing_an_accepted_stator_from_another_work_order_is_refused(api, plant):
    """Co-location is checked as well as status, and the failure looks identical.

    PRD 3.8: "**Assembly** joins an accepted stator to an accepted rotor and is
    the `BuildTechnician`'s last act."

    Design: Difficulty/cross_entity_state_dependency/assembly_record_requires_both_subassemblies_accepted_on_its_own_work_order
    """
    scene = _pairing_scene(plant)
    assert plant.get_stator(scene["foreign_stator"])["status"] == "ACCEPTED"

    refused = api.create_assembly_record(
        F.assembly_record_payload(
            scene["work_order"]["id"],
            scene["foreign_stator"]["id"],
            scene["rotor"]["id"],
        ),
        U.BUILD_TECHNICIAN,
    )

    validate_error(refused, ERR_SUBASSEMBLY_NOT_ACCEPTED, 409)
    assert (
        plant.get_work_order(scene["work_order"])["build_status"]
        == "SUBASSEMBLIES_DONE"
    )
    assert plant.get_work_order(scene["sibling_work_order"])["build_status"] == "RELEASED"


def test_the_co_located_accepted_pair_assembles_and_computes_the_shaft_fit(plant):
    """Only the pair that is both accepted and co-located reaches the metrology.

    PRD 3.8: "`shaft_fit_deviation_um` is the measured journal diameter minus the
    design's `shaft_diameter_mm`, converted to micrometres by multiplying by 1000
    and rounded to a whole number, and it may be negative when the journal came
    out undersize."

    Design: Difficulty/cross_entity_state_dependency/assembly_record_requires_both_subassemblies_accepted_on_its_own_work_order
    """
    scene = _pairing_scene(plant)

    assembly = plant.add_assembly(
        work_order=scene["work_order"],
        stator=scene["stator"],
        rotor=scene["rotor"],
        shaft_measured_diameter_mm=38.010,
        grease_fill_pct=50.00,
    )

    assert assembly["status"] == "BUILT"
    assert assembly["shaft_fit_deviation_um"] == 10
    assert assembly["shaft_fit_deviation_um"] == A.expected_shaft_fit_deviation_um(
        38.010, 38.000
    )
    assert assembly["lubrication_spec_applied"] == "GREASE_REGREASABLE"
    assert assembly["assembler_user_id"] == U.USER_BUILD_TECHNICIAN
    assert assembly["stator_build_id"] == scene["stator"]["id"]
    assert assembly["rotor_build_id"] == scene["rotor"]["id"]
    assert plant.get_work_order(scene["work_order"])["build_status"] == "ASSEMBLED"
    assert plant.get_work_order(scene["sibling_work_order"])["build_status"] == "RELEASED"


def _two_assembled_work_orders_with_one_reservation(plant):
    """DYNO-1 holds a 12.0 kW test for WO1 over 09:00-11:00Z; WO2 is ASSEMBLED."""
    first_work_order, second_work_order = _two_work_orders(plant, with_cell=True)
    first_stator = _accept_stator(plant, first_work_order, U.BUILD_TECHNICIAN)
    first_rotor = _accept_rotor(plant, first_work_order, U.BUILD_TECHNICIAN)
    plant.add_assembly(
        work_order=first_work_order, stator=first_stator, rotor=first_rotor
    )
    second_stator = _accept_stator(
        plant,
        second_work_order,
        U.BUILD_TECHNICIAN_OTHER,
        impregnation_window_start=F.SECOND_IMPREGNATION_WINDOW_START,
        impregnation_window_end=F.SECOND_IMPREGNATION_WINDOW_END,
    )
    second_rotor = _accept_rotor(plant, second_work_order, U.BUILD_TECHNICIAN_OTHER)
    plant.add_assembly(
        work_order=second_work_order,
        stator=second_stator,
        rotor=second_rotor,
        headers=U.BUILD_TECHNICIAN_OTHER,
    )
    reserved = plant.schedule_test(work_order=first_work_order, dyno_draw_kw=12.0)
    assert reserved["status"] == "SCHEDULED"
    assert reserved["window_start"] == F.TEST_WINDOW_START
    A.assert_rounded_to(plant.get_cell()["peak_reserved_kw"], 12.0, 1, "peak_reserved_kw")
    return second_work_order, reserved


def _capacity_payload(plant, work_order, draw, start, end):
    return F.performance_test_payload(
        work_order["id"],
        plant.cell["id"],
        plant.get_work_order(work_order)["version"],
        window_start=start,
        window_end=end,
        dyno_draw_kw=draw,
    )


def test_aggregate_draw_one_tenth_over_the_cell_ceiling_is_refused(api, plant):
    """12.0 kW already reserved plus 8.5 kW requested is 20.5 against a 20.0 ceiling.

    PRD 3.8: "That aggregate must not exceed the cell's `max_concurrent_kw`: an
    aggregate exactly equal to the ceiling is allowed, and 0.1 kW beyond it is
    refused with `ERR_TEST_CELL_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/test_cell_aggregate_draw_over_half_open_windows_at_exact_capacity
    """
    second_work_order, _reserved = _two_assembled_work_orders_with_one_reservation(plant)

    refused = api.create_performance_test(
        _capacity_payload(
            plant, second_work_order, 8.5, LATE_WINDOW_START, LATE_WINDOW_END
        ),
        U.TEST_ENGINEER_OTHER,
    )

    validate_error(refused, ERR_TEST_CELL_CAPACITY_EXCEEDED, 409)
    A.assert_rounded_to(plant.get_cell()["peak_reserved_kw"], 12.0, 1, "peak_reserved_kw")
    assert plant.get_work_order(second_work_order)["build_status"] == "ASSEMBLED"


def test_aggregate_draw_exactly_at_the_cell_ceiling_is_admitted(api, plant):
    """8.0 kW over an overlapping window brings the cell to exactly 20.0 kW.

    PRD 3.8: "Sum those tests' `dyno_draw_kw`, add the requested draw, and round
    the total to one decimal place."

    Design: Difficulty/resource_temporal_overlap/test_cell_aggregate_draw_over_half_open_windows_at_exact_capacity
    """
    second_work_order, reserved = _two_assembled_work_orders_with_one_reservation(plant)
    validate_error(
        api.create_performance_test(
            _capacity_payload(
                plant, second_work_order, 8.5, LATE_WINDOW_START, LATE_WINDOW_END
            ),
            U.TEST_ENGINEER_OTHER,
        ),
        ERR_TEST_CELL_CAPACITY_EXCEEDED,
        409,
    )

    admitted = validate_success(
        api.create_performance_test(
            _capacity_payload(
                plant, second_work_order, 8.0, LATE_WINDOW_START, LATE_WINDOW_END
            ),
            U.TEST_ENGINEER_OTHER,
        ),
        201,
    )

    assert admitted["status"] == "SCHEDULED"
    assert admitted["requires_requalification"] is False
    A.assert_rounded_to(admitted["dyno_draw_kw"], 8.0, 1, "dyno_draw_kw")
    A.assert_rounded_to(plant.get_cell()["peak_reserved_kw"], 20.0, 1, "peak_reserved_kw")
    assert plant.get_test(reserved)["status"] == "SCHEDULED"
    assert plant.get_work_order(second_work_order)["build_status"] == "ASSEMBLED"


def test_rescheduling_supersedes_the_earlier_test_and_releases_its_draw(api, plant):
    """A half-open 11:00-13:00Z window shares an instant with 09:00-11:00Z, not a draw.

    PRD 3.8: "Collect every performance test on that cell whose status is
    `SCHEDULED` or `COMPLETED` and whose window overlaps the requested one, where
    overlap means the existing window starts strictly before the requested end and
    the requested start falls strictly before the existing window's end —
    half-open intervals, so a window starting exactly when another ends does not
    overlap."

    Design: Difficulty/resource_temporal_overlap/test_cell_aggregate_draw_over_half_open_windows_at_exact_capacity
    """
    second_work_order, reserved = _two_assembled_work_orders_with_one_reservation(plant)
    superseded_candidate = validate_success(
        api.create_performance_test(
            _capacity_payload(
                plant, second_work_order, 8.0, LATE_WINDOW_START, LATE_WINDOW_END
            ),
            U.TEST_ENGINEER_OTHER,
        ),
        201,
    )
    A.assert_rounded_to(plant.get_cell()["peak_reserved_kw"], 20.0, 1, "peak_reserved_kw")

    rescheduled = validate_success(
        api.create_performance_test(
            _capacity_payload(
                plant, second_work_order, 12.0, SHIFTED_WINDOW_START, SHIFTED_WINDOW_END
            ),
            U.TEST_ENGINEER_OTHER,
        ),
        201,
    )

    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["window_start"] == SHIFTED_WINDOW_START
    assert plant.get_test(superseded_candidate)["status"] == "SUPERSEDED"
    still_live = plant.get_test(reserved)
    assert still_live["status"] == "SCHEDULED"
    A.assert_rounded_to(still_live["dyno_draw_kw"], 12.0, 1, "dyno_draw_kw")
    A.assert_rounded_to(plant.get_cell()["peak_reserved_kw"], 12.0, 1, "peak_reserved_kw")
    assert plant.get_work_order(second_work_order)["build_status"] == "ASSEMBLED"
