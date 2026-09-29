"""The stator's surge envelope and the curing oven's buffered occupancy ledger."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_OVEN_WINDOW_CONFLICT,
    ERR_SURGE_MARGIN_NEGATIVE,
)

BUFFERED_END = F.instant(F.IMPREGNATION_DAY, 12, 45)
BUFFERED_END_PLUS_FOUR_HOURS = F.instant(F.IMPREGNATION_DAY, 16, 45)
INSIDE_BUFFER = F.instant(F.IMPREGNATION_DAY, 12, 30)
INSIDE_BUFFER_PLUS_FOUR_HOURS = F.instant(F.IMPREGNATION_DAY, 16, 30)


def _impregnated_stator(plant, **oven_overrides):
    """One work order carrying a stator impregnated 08:00-12:00Z in OVEN-A."""
    plant.add_distributor()
    plant.add_oven(**oven_overrides)
    plant.add_design(F.motor_design_payload())
    plant.release_design()
    plant.add_order()
    plant.confirm_order()
    plant.add_work_order()
    plant.add_stator()
    return plant.impregnate_stator(cure_temp_c=165.0)


def test_surge_level_exactly_at_the_required_envelope_leaves_a_zero_margin(plant):
    """2.07 kV applied against a 2.07 kV requirement stores a 0.00 kV margin.

    PRD 3.6: "Both gates are inclusive at the boundary: an applied level exactly
    equal to the capability passes, and a margin of exactly 0.00 kV passes."

    Design: Difficulty/boundary_precision_check/surge_insulation_margin_exactly_zero_accepted_one_hundredth_below_rejected
    """
    impregnated = _impregnated_stator(plant)
    assert impregnated["required_surge_kv"] == 2.07
    assert impregnated["achieved_capability_kv"] == 2.58
    A.assert_rounded_to(
        impregnated["required_surge_kv"],
        A.expected_required_surge_kv(400, "F"),
        2,
        "required_surge_kv",
    )
    A.assert_rounded_to(
        impregnated["achieved_capability_kv"],
        A.expected_achieved_capability_kv(400, "F", "VPI", 2),
        2,
        "achieved_capability_kv",
    )

    tested = plant.surge_test_stator(surge_test_kv=2.07)

    assert tested["status"] == "SURGE_TESTED"
    assert tested["surge_test_kv"] == 2.07
    assert tested["surge_test_result"] == "PASS"
    assert tested["insulation_margin_kv"] is not None
    A.assert_rounded_to(tested["insulation_margin_kv"], 0, 2, "insulation_margin_kv")
    A.assert_decimal_width(tested["insulation_margin_kv"], 2, "insulation_margin_kv")
    assert tested["surge_tester_user_id"] == U.USER_TEST_ENGINEER


def test_surge_level_one_hundredth_below_the_envelope_is_refused(api, plant):
    """2.06 kV would be a margin of -0.01 kV, so nothing is stored at all.

    PRD 3.6: "Second, the applied level must be at least `required_surge_kv`,
    since a level below the required envelope does not qualify the insulation
    system; a shortfall is refused with `ERR_SURGE_MARGIN_NEGATIVE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/surge_insulation_margin_exactly_zero_accepted_one_hundredth_below_rejected
    """
    impregnated = _impregnated_stator(plant)
    assert impregnated["required_surge_kv"] == 2.07
    assert impregnated["insulation_margin_kv"] is None
    assert impregnated["surge_test_kv"] is None

    refused = api.surge_test_stator_build(
        impregnated["id"], F.surge_test_payload(2.06), U.TEST_ENGINEER
    )

    validate_error(refused, ERR_SURGE_MARGIN_NEGATIVE, 422)
    stored = plant.get_stator()
    assert stored["status"] == "IMPREGNATED"
    assert stored["insulation_margin_kv"] is None
    assert stored["surge_test_kv"] is None
    assert stored["surge_test_result"] is None
    accepted = plant.surge_test_stator(surge_test_kv=2.07)
    A.assert_rounded_to(accepted["insulation_margin_kv"], 0, 2, "insulation_margin_kv")


def _two_work_orders_with_the_first_oven_window_taken(plant):
    """OVEN-A holds sb1 for 08:00-12:00Z; sb2 on a second work order is unbooked."""
    plant.add_distributor()
    plant.add_oven(cooldown_buffer_minutes=45)
    plant.add_design(F.motor_design_payload())
    plant.release_design()
    first_order = plant.add_order()
    plant.confirm_order(first_order)
    second_order = plant.add_order()
    plant.confirm_order(second_order)
    plant.add_work_order(order=first_order)
    second_work_order = plant.add_work_order(order=second_order)
    plant.add_stator()
    booked = plant.impregnate_stator(cure_temp_c=165.0)
    assert booked["impregnation_minutes"] == 240
    assert plant.get_oven()["booked_minutes"] == 240
    unbooked = plant.add_stator(
        work_order=second_work_order, headers=U.BUILD_TECHNICIAN_OTHER
    )
    return second_work_order, unbooked


def test_oven_window_starting_inside_the_cooldown_buffer_still_conflicts(api, plant):
    """12:30Z is half an hour past the raw end and still inside the 45-minute buffer.

    PRD 3.6: "For each existing stator build on the same oven whose status is
    `IMPREGNATED`, `SURGE_TESTED` or `ACCEPTED`, extend that booking's
    `impregnation_window_end` forward by the oven's `cooldown_buffer_minutes` to
    obtain its effective end."

    Design: Difficulty/resource_temporal_overlap/oven_window_conflicts_until_the_full_cooldown_buffer_has_elapsed
    """
    _second_work_order, unbooked = _two_work_orders_with_the_first_oven_window_taken(
        plant
    )

    refused = api.impregnate_stator_build(
        unbooked["id"],
        F.impregnation_payload(
            plant.oven["id"],
            impregnation_window_start=INSIDE_BUFFER,
            impregnation_window_end=INSIDE_BUFFER_PLUS_FOUR_HOURS,
            cure_temp_c=165.0,
        ),
        U.BUILD_TECHNICIAN_OTHER,
    )

    validate_error(refused, ERR_OVEN_WINDOW_CONFLICT, 409)
    stored = plant.get_stator(unbooked)
    assert stored["status"] == "WOUND"
    assert stored["oven_id"] is None
    assert stored["impregnation_minutes"] is None
    assert plant.get_oven()["booked_minutes"] == 240


def test_oven_window_starting_exactly_at_the_buffered_end_is_accepted(api, plant):
    """12:45Z is the first legal start, and both bookings then count together.

    PRD 3.6: "A new window whose start coincides exactly with a previous window's
    end *plus the full cooldown buffer* does not collide, while a start one
    minute earlier does; and whenever the buffer is greater than zero, a window
    butting directly against a previous window's raw end always collides."

    Design: Difficulty/resource_temporal_overlap/oven_window_conflicts_until_the_full_cooldown_buffer_has_elapsed
    """
    _second_work_order, unbooked = _two_work_orders_with_the_first_oven_window_taken(
        plant
    )
    validate_error(
        api.impregnate_stator_build(
            unbooked["id"],
            F.impregnation_payload(
                plant.oven["id"],
                impregnation_window_start=INSIDE_BUFFER,
                impregnation_window_end=INSIDE_BUFFER_PLUS_FOUR_HOURS,
                cure_temp_c=165.0,
            ),
            U.BUILD_TECHNICIAN_OTHER,
        ),
        ERR_OVEN_WINDOW_CONFLICT,
        409,
    )

    booked = validate_success(
        api.impregnate_stator_build(
            unbooked["id"],
            F.impregnation_payload(
                plant.oven["id"],
                impregnation_window_start=BUFFERED_END,
                impregnation_window_end=BUFFERED_END_PLUS_FOUR_HOURS,
                cure_temp_c=165.0,
            ),
            U.BUILD_TECHNICIAN_OTHER,
        )
    )

    assert booked["status"] == "IMPREGNATED"
    assert booked["impregnation_window_start"] == BUFFERED_END
    assert booked["impregnation_minutes"] == 240
    assert booked["oven_id"] == plant.oven["id"]
    assert plant.get_oven()["booked_minutes"] == 480
    assert plant.get_stator()["status"] == "IMPREGNATED"


def test_rejecting_an_impregnated_stator_releases_every_booked_minute(plant):
    """The ledger goes 240 back to 0 while the booking history is preserved.

    PRD 3.6: "A rejection has two compensating effects beyond the status change:
    if the build was holding an oven booking, that oven's `booked_minutes` is
    recomputed — the rejected build has left the counted set, so its minutes are
    released in full — and the oven's `version` advances; and the owning work
    order's `rework_reject_count` rises by 1, with `actual_cost_cents` and
    `cost_variance_cents` recomputed accordingly."

    Design: Difficulty/compensating_invariant/oven_booked_minutes_returns_to_zero_after_rejection_and_rebooks_without_drift
    """
    design_payload = F.motor_design_payload()
    plant.add_distributor()
    plant.add_oven(cooldown_buffer_minutes=45)
    plant.add_design(design_payload)
    plant.release_design()
    plant.add_order()
    plant.confirm_order()
    plant.add_work_order()
    plant.add_stator()
    plant.impregnate_stator(cure_temp_c=165.0)
    oven_before = plant.get_oven()
    assert oven_before["booked_minutes"] == 240

    rejected = plant.disposition_stator("REJECTED")

    assert rejected["status"] == "REJECTED"
    assert rejected["impregnation_minutes"] == 240
    assert rejected["oven_id"] == plant.oven["id"]
    oven_after = plant.get_oven()
    assert oven_after["booked_minutes"] == 0
    assert oven_after["version"] > oven_before["version"]
    work_order = plant.get_work_order()
    assert work_order["rework_reject_count"] == 1
    assert work_order["build_status"] == "RELEASED"
    A.assert_cost_rollup(work_order, design_payload, 12, 1)


def test_the_identical_oven_window_can_be_rebooked_after_a_rejection(plant):
    """A complete release lets the replacement stator take the very same window.

    PRD 2.10: "A curing oven's `booked_minutes` is always the sum of
    `impregnation_minutes` over the stator builds booked into that oven whose
    status is `IMPREGNATED`, `SURGE_TESTED` or `ACCEPTED`."

    Design: Difficulty/compensating_invariant/oven_booked_minutes_returns_to_zero_after_rejection_and_rebooks_without_drift
    """
    plant.add_distributor()
    plant.add_oven(cooldown_buffer_minutes=45)
    plant.add_design(F.motor_design_payload())
    plant.release_design()
    plant.add_order()
    plant.confirm_order()
    plant.add_work_order()
    plant.add_stator()
    first = plant.impregnate_stator(cure_temp_c=165.0)
    plant.disposition_stator("REJECTED")
    assert plant.get_oven()["booked_minutes"] == 0

    replacement = plant.add_stator(slot_fill_pct=83.00)
    rebooked = plant.impregnate_stator(stator=replacement, cure_temp_c=165.0)

    assert replacement["status"] == "WOUND"
    assert rebooked["status"] == "IMPREGNATED"
    assert rebooked["id"] != first["id"]
    assert rebooked["impregnation_window_start"] == F.IMPREGNATION_WINDOW_START
    assert rebooked["impregnation_window_end"] == F.IMPREGNATION_WINDOW_END
    assert rebooked["impregnation_minutes"] == 240
    assert plant.get_oven()["booked_minutes"] == 240
    assert plant.get_stator(first)["status"] == "REJECTED"
