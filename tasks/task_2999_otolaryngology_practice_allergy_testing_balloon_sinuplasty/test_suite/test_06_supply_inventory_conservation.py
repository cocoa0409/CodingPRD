"""Supply-lot unit conservation across write-offs, booking completions and cancellations."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS


def _tube_lot_with_one_reservation(api, plan_code, patient_mrn, lot_no):
    """A four-unit tympanostomy lot holding a single one-unit reservation.

    The chart is born on 2020-01-01, so it is 79 months old at the default clock and
    the office suite is a permitted venue for tube surgery. The scheduled case reserves
    one unit, which leaves three units available and the lot `ACTIVE`.
    """
    world = SETUP.policy_with_patient(
        api,
        plan_code=plan_code,
        patient_mrn=patient_mrn,
        policy_overrides={"payer_name": "Supply Mutual"},
        patient_overrides={"full_name": "Tube Patient", "date_of_birth": "2020-01-01"},
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_TYMPANOSTOMY_TUBE,
        lot_no=lot_no,
        quantity_received=4,
        expires_at="2027-06-30T00:00:00Z",
    )
    booking = SETUP.create_booking(
        api,
        world["patient"]["id"],
        "2026-08-06T09:00:00Z",
        "2026-08-06T09:45:00Z",
        procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
        venue=C.VENUE_IN_OFFICE_SUITE,
        supply_lot_id=lot["id"],
        planned_device_count=1,
    )
    return {"patient_id": world["patient"]["id"], "lot": lot, "booking": booking}


def test_write_off_moves_units_out_of_on_hand_and_into_wasted(api):
    """PRD 3.8: "Hop one: `quantity_on_hand` falls by the `quantity` and
    `quantity_wasted` rises by the same amount, so nothing is created or destroyed and
    the identity holds."

    Design: Difficulty/transitive_cascade/supply_write_off_shortfall_cascade
    """
    base = _tube_lot_with_one_reservation(api, "SUP-2999A", C.mrn(10081), C.lot_number(1005))
    lot_id = base["lot"]["id"]

    # The lot opens with four units on the shelf and one of them claimed.
    check.assert_supply_lot(
        SETUP.read_lot(api, lot_id),
        quantity_received=4,
        quantity_on_hand=4,
        quantity_reserved=1,
        quantity_consumed=0,
        quantity_wasted=0,
        available_quantity=3,
        status=C.LOT_ACTIVE,
    )

    # Three of the four units are written off in one adjustment.
    lot = check.validate_unpaginated(
        api.adjust_supply_lot(
            lot_id,
            F.lot_adjustment_payload(reason=C.ADJUSTMENT_REASON_WRITE_OFF, quantity=3),
            USERS.ADMIN_1,
        )
    )

    # The three units moved bucket to bucket: nothing was created and nothing destroyed.
    check.assert_supply_lot(
        lot,
        quantity_received=4,
        quantity_on_hand=1,
        quantity_wasted=3,
        quantity_reserved=1,
        quantity_consumed=0,
    )
    check.assert_lot_quantity_ledger(lot)


def test_write_off_that_empties_availability_exhausts_the_lot(api):
    """PRD 3.8: "Hop two, caused by hop one: if `available_quantity` has reached zero
    the lot flips `ACTIVE → EXHAUSTED`."

    Design: Difficulty/transitive_cascade/supply_write_off_shortfall_cascade
    """
    base = _tube_lot_with_one_reservation(api, "SUP-2999B", C.mrn(10082), C.lot_number(1006))
    lot_id = base["lot"]["id"]

    # Three units are available and the lot is trading normally.
    check.assert_supply_lot(
        SETUP.read_lot(api, lot_id), available_quantity=3, status=C.LOT_ACTIVE
    )

    # Writing off exactly those three units leaves the one reserved unit and nothing free.
    lot = SETUP.adjust_lot(api, lot_id, C.ADJUSTMENT_REASON_WRITE_OFF, quantity=3)
    check.assert_supply_lot(
        lot,
        quantity_on_hand=1,
        quantity_reserved=1,
        available_quantity=0,
        status=C.LOT_EXHAUSTED,
    )


def test_write_off_raises_the_shortfall_flag_on_the_lots_scheduled_case(api):
    """PRD 3.8: "Hop three, caused by hop two: every booking on this lot whose status
    is `SCHEDULED` and whose `planned_device_count` is greater than zero has
    `supply_shortfall_flag` set to true."

    Design: Difficulty/transitive_cascade/supply_write_off_shortfall_cascade
    """
    base = _tube_lot_with_one_reservation(api, "SUP-2999C", C.mrn(10083), C.lot_number(1007))
    lot_id = base["lot"]["id"]
    booking_id = base["booking"]["id"]

    # The scheduled case plans one device and reports no shortfall at creation.
    check.assert_procedure_booking(
        base["booking"],
        status=C.BOOKING_SCHEDULED,
        planned_device_count=1,
        supply_shortfall_flag=False,
        supply_lot_id=lot_id,
    )

    # The write-off empties availability, which is what reaches the schedule.
    lot = SETUP.adjust_lot(api, lot_id, C.ADJUSTMENT_REASON_WRITE_OFF, quantity=3)
    check.assert_supply_lot(lot, available_quantity=0, status=C.LOT_EXHAUSTED)

    # The case is flagged but not cancelled: it still waits for units it can no longer draw.
    check.assert_procedure_booking(
        SETUP.read_booking(api, booking_id),
        status=C.BOOKING_SCHEDULED,
        supply_shortfall_flag=True,
        planned_device_count=1,
        devices_used_count=0,
    )


def _tube_lot(api, plan_code, patient_mrn, lot_no):
    """A four-unit tympanostomy lot and one chart old enough for the office suite."""
    world = SETUP.policy_with_patient(
        api,
        plan_code=plan_code,
        patient_mrn=patient_mrn,
        policy_overrides={"payer_name": "Unit Ledger Health"},
        patient_overrides={
            "full_name": "Unit Ledger Child",
            "date_of_birth": "2020-01-01",
        },
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_TYMPANOSTOMY_TUBE,
        lot_no=lot_no,
        quantity_received=4,
        expires_at="2027-12-31T00:00:00Z",
    )
    return {"patient_id": world["patient"]["id"], "lot": lot}


def _tube_case(api, patient_id, start_at, end_at, lot_id, planned_device_count):
    """Schedule one tympanostomy case that claims units from a lot."""
    return validate_success(
        api.create_procedure_booking(
            SETUP.booking_payload(
                patient_id,
                start_at,
                end_at,
                procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
                venue=C.VENUE_IN_OFFICE_SUITE,
                supply_lot_id=lot_id,
                planned_device_count=planned_device_count,
            ),
            USERS.ADMIN_1,
        ),
        201,
    )


def test_completion_consumes_one_unit_and_returns_the_rest_of_the_reservation(api):
    """PRD 3.9: "On the lot, the reservation of `planned_device_count` units is released
    while `quantity_consumed` rises by `devices_used_count` and `quantity_on_hand` falls
    by the same amount, so `quantity_received` still equals the sum of
    `quantity_on_hand`, `quantity_consumed` and `quantity_wasted`."

    Design: Difficulty/compensating_invariant/supply_lot_unit_ledger_conserved_across_completion_and_cancel
    """
    base = _tube_lot(api, "LEDG-2999A", C.mrn(10181), C.lot_number(1009))
    lot_id = base["lot"]["id"]

    # The lot is received whole: four units on the shelf and nothing claimed.
    check.assert_supply_lot(
        base["lot"],
        quantity_received=4,
        quantity_on_hand=4,
        quantity_reserved=0,
        quantity_consumed=0,
        quantity_wasted=0,
        available_quantity=4,
        status=C.LOT_ACTIVE,
    )

    # A case planning two devices claims two units without moving any bucket.
    booking = _tube_case(
        api,
        base["patient_id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        lot_id,
        2,
    )
    check.assert_procedure_booking(
        booking,
        status=C.BOOKING_SCHEDULED,
        planned_device_count=2,
        devices_used_count=0,
        supply_shortfall_flag=False,
    )
    reserved = SETUP.read_lot(api, lot_id)
    check.assert_supply_lot(
        reserved,
        quantity_received=4,
        quantity_on_hand=4,
        quantity_reserved=2,
        quantity_consumed=0,
        quantity_wasted=0,
        available_quantity=2,
        status=C.LOT_ACTIVE,
    )

    # The case runs and only one of the two planned devices is implanted.
    SETUP.start_booking(api, booking["id"])
    completed = check.validate_unpaginated(
        api.complete_procedure_booking(
            booking["id"], F.booking_completion_payload(1), USERS.ENT_1
        )
    )
    check.assert_procedure_booking(
        completed,
        status=C.BOOKING_COMPLETED,
        planned_device_count=2,
        devices_used_count=1,
    )

    # One unit is consumed, the unused claim goes back to the shelf, and the identity holds.
    settled = SETUP.read_lot(api, lot_id)
    check.assert_supply_lot(
        settled,
        quantity_received=4,
        quantity_on_hand=3,
        quantity_reserved=0,
        quantity_consumed=1,
        quantity_wasted=0,
        available_quantity=3,
        status=C.LOT_ACTIVE,
    )
    assert settled["available_quantity"] > reserved["available_quantity"], (
        "availability must rise on a completion, from {0} to {1}".format(
            reserved["available_quantity"], settled["available_quantity"]
        )
    )


def test_cancellation_releases_the_reservation_without_moving_a_single_bucket(api):
    """PRD 3.9: "The lot's reservation of `planned_device_count` units is released, so
    `available_quantity` rises while all four buckets stay exactly where they were and
    the conserved identity is untouched; if that lifts `available_quantity` above zero
    the lot flips `EXHAUSTED → ACTIVE` and the `supply_shortfall_flag` is cleared on the
    lot's `SCHEDULED` bookings."

    Design: Difficulty/compensating_invariant/supply_lot_unit_ledger_conserved_across_completion_and_cancel
    """
    base = _tube_lot(api, "LEDG-2999B", C.mrn(10182), C.lot_number(1010))
    lot_id = base["lot"]["id"]

    # An earlier case has already consumed one unit, so the shelf stands at three.
    first = _tube_case(
        api,
        base["patient_id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        lot_id,
        2,
    )
    SETUP.start_booking(api, first["id"])
    SETUP.complete_booking(api, first["id"], devices_used_count=1)
    check.assert_supply_lot(
        SETUP.read_lot(api, lot_id),
        quantity_received=4,
        quantity_on_hand=3,
        quantity_reserved=0,
        quantity_consumed=1,
        quantity_wasted=0,
        available_quantity=3,
        status=C.LOT_ACTIVE,
    )

    # A second case claims one of the three remaining units.
    second = _tube_case(
        api,
        base["patient_id"],
        "2026-08-06T09:00:00Z",
        "2026-08-06T10:00:00Z",
        lot_id,
        1,
    )
    check.assert_supply_lot(
        SETUP.read_lot(api, lot_id),
        quantity_on_hand=3,
        quantity_reserved=1,
        quantity_consumed=1,
        quantity_wasted=0,
        available_quantity=2,
        status=C.LOT_ACTIVE,
    )

    # The second case is called off before it ever starts.
    cancelled = check.validate_unpaginated(
        api.cancel_procedure_booking(
            second["id"],
            F.booking_cancel_payload(cancel_reason=C.CANCEL_REASON_PATIENT_REQUEST),
            USERS.ENT_1,
        )
    )
    check.assert_procedure_booking(
        cancelled,
        status=C.BOOKING_CANCELLED,
        cancel_reason=C.CANCEL_REASON_PATIENT_REQUEST,
        devices_used_count=0,
        supply_shortfall_flag=False,
    )

    # The claim is gone, availability is back to three, and every bucket sits where it was.
    check.assert_supply_lot(
        SETUP.read_lot(api, lot_id),
        quantity_received=4,
        quantity_on_hand=3,
        quantity_reserved=0,
        quantity_consumed=1,
        quantity_wasted=0,
        available_quantity=3,
        status=C.LOT_ACTIVE,
    )
    check.assert_procedure_booking(
        SETUP.read_booking(api, first["id"]),
        status=C.BOOKING_COMPLETED,
        supply_shortfall_flag=False,
    )
