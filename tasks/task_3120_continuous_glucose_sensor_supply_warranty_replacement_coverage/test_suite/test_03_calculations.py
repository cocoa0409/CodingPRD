"""Calculations: lot complaint posture thresholds and filtering."""
from test_helpers import (
    TEST_USERS,
    assert_sensor_lot,
    create_lot,
    create_patient,
    create_product,
    create_units,
    file_and_close_aer,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_lot_complaint_posture_inclusive_threshold_watch(api):
    """PRD §3.2: "When the substantiated count reaches at least three but fewer
    than seven, the lot's `complaint_posture` is `WATCH`; once the count
    reaches at least seven, the posture becomes `HOLD`; below three, the
    posture is `NORMAL`. The boundary is inclusive at the threshold, so exactly
    three lands the lot in `WATCH` and exactly seven lands it in `HOLD`."

    Design: Corner/calculations/lot_complaint_posture_inclusive_threshold_watch
    """
    patient = create_patient()
    product = create_product()
    lot = create_lot(product, quantity_manufactured=10)
    units = create_units(lot, 3)
    for unit in units:
        file_and_close_aer(lot, unit, patient["id"], outcome="SUBSTANTIATED")
    data = validate_success(api.get_sensor_lot(lot["id"], ADMIN))
    assert_sensor_lot(data)
    assert data["complaint_count"] == 3
    assert data["complaint_posture"] == "WATCH"


def test_lot_complaint_posture_unsubstantiated_does_not_count(api):
    """PRD §3.2: "The `complaint_count` on a lot counts only those
    adverse-event reports that have been closed as substantiated — reports
    still open or under investigation do not contribute, and reports closed as
    unsubstantiated do not contribute."

    Design: Corner/calculations/lot_complaint_posture_unsubstantiated_does_not_count
    """
    patient = create_patient()
    product = create_product()
    lot = create_lot(product, quantity_manufactured=10)
    units = create_units(lot, 3)
    file_and_close_aer(lot, units[0], patient["id"], outcome="SUBSTANTIATED")
    file_and_close_aer(lot, units[1], patient["id"], outcome="SUBSTANTIATED")
    file_and_close_aer(
        lot, units[2], patient["id"], outcome="UNSUBSTANTIATED",
        severity="LOW", event_type="OTHER",
    )
    data = validate_success(api.get_sensor_lot(lot["id"], ADMIN))
    assert data["complaint_count"] == 2
    assert data["complaint_posture"] == "NORMAL"
