"""Three operations whose legality is decided by the state of a neighbouring row
rather than by anything on the target: an encounter's move to awaiting a device
gated by its supplier's quality flag, a fitting session gated by its fabrication
order, and a fabrication event gated by the supplier's standards attestation.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ApiErrors,
    assert_error,
    assert_list_meta,
    attest_standards,
    build_practice,
    error_id_of,
    inventory_manager_headers,
    read_encounter,
    read_fab_order,
    read_fitter,
)
from test_helpers import factories as f


def _afo_encounter_with_held_supplier(api):
    """A documented, supervision-attested encounter for a custom-fabricated ankle
    orthosis whose supplier has just been put on quality hold."""
    practice = build_practice(api, product_factory=f.custom_afo_product_payload, with_shelf=False)
    encounter_id = practice.attested_encounter()
    attest_standards(api, practice.supplier_id, attested=True, quality_hold=True)
    return practice, encounter_id


def test_a_fabrication_order_is_refused_while_its_supplier_is_on_quality_hold(api):
    """Nothing about the encounter is wrong — the block lives on the supplier of its
    product — so the request is refused and the encounter does not leave the
    documented posture.

    PRD: "`ERR_SUPPLIER_QUALITY_HOLD`, also HTTP 422, fires when the supplier is on
    quality hold, and it guards three of those four: reserving par stock, placing a
    custom-fabrication order, and driving a fabrication event."

    Design: Difficulty/cross_entity_state_dependency/custom_fab_order_blocked_while_supplier_quality_hold_active_rejected
    """
    practice, encounter_id = _afo_encounter_with_held_supplier(api)

    response = api.create_custom_fab_order(
        encounter_id, f.custom_fab_order_payload(practice.supplier_id), practice.fitter_headers
    )

    assert_error(response, ApiErrors.SUPPLIER_QUALITY_HOLD, 422)
    assert read_encounter(api, encounter_id)["clinical_status"] == "DOCUMENTED"
    assert_list_meta(
        api.list_custom_fab_orders(inventory_manager_headers(), {"encounter_id": encounter_id}),
        expected_total=0,
    )


def test_the_identical_order_is_accepted_once_the_quality_hold_is_lifted(api):
    """Only the supplier's flag changed between the two attempts, and with it lifted
    the same body is accepted, the order opens as submitted with the supplier's
    promise snapshotted, and the encounter advances to awaiting its device.

    PRD: "On success a `CustomFabOrder` is created against its parent
    `encounter_id` with `status` `SUBMITTED` and `submitted_at` stamped from the
    logical clock, and two supplier values are snapshotted onto it:
    `promised_turnaround_days_snapshot`, copied from the supplier's
    `promised_turnaround_days`, and `promised_delivery_on`, derived as the calendar
    date of `submitted_at` advanced by that many whole days."

    Design: Difficulty/cross_entity_state_dependency/custom_fab_order_blocked_while_supplier_quality_hold_active_rejected
    """
    practice, encounter_id = _afo_encounter_with_held_supplier(api)
    payload = f.custom_fab_order_payload(practice.supplier_id)
    assert_error(
        api.create_custom_fab_order(encounter_id, payload, practice.fitter_headers),
        ApiErrors.SUPPLIER_QUALITY_HOLD,
        422,
    )

    attest_standards(api, practice.supplier_id, attested=True, quality_hold=False)
    order = validate_success(
        api.create_custom_fab_order(encounter_id, payload, practice.fitter_headers), 201
    )

    assert order["status"] == "SUBMITTED"
    assert order["promised_turnaround_days_snapshot"] == 10
    assert order["adjustment_rounds"] == 0
    assert read_encounter(api, encounter_id)["clinical_status"] == "AWAITING_DEVICE"


def _order_ready_for_fitting(api):
    """An encounter awaiting its device whose fabrication order has been delivered
    to the clinic but not yet accepted by the fitter."""
    practice = build_practice(api, product_factory=f.custom_afo_product_payload, with_shelf=False)
    encounter_id = practice.attested_encounter()
    order = practice.place_fab_order(encounter_id)
    practice.fabrication_event(order["id"], "ACCEPT_ORDER")
    ready = practice.fabrication_event(order["id"], "DELIVER_TO_CLINIC")
    assert ready["status"] == "READY_FOR_FITTING"
    return practice, encounter_id, order["id"]


def test_a_fitting_is_refused_while_the_delivered_device_is_unaccepted(api):
    """The encounter's own posture is a legal origin for a fitting, so the refusal
    names the fabrication order's state and not the encounter's.

    PRD: "When the encounter's `clinical_status` is `AWAITING_DEVICE`, the
    encounter's fabrication order must have reached `ACCEPTED` before a fitting
    session may be recorded, because a device that is still `SUBMITTED`,
    `IN_FABRICATION`, `READY_FOR_FITTING`, `ADJUSTMENT_REQUESTED` or `SUPPLIER_HOLD`
    has not been handed over to the clinic yet."

    Design: Difficulty/cross_entity_state_dependency/awaiting_device_fitting_blocked_until_fab_order_accepted_rejected
    """
    practice, encounter_id, _order_id = _order_ready_for_fitting(api)

    response = api.create_fitting_record(
        encounter_id,
        f.fitting_record_payload(
            "2026-08-01T11:00:00Z",
            "2026-08-01T11:40:00Z",
            measurement_set={"calf_cm": 36, "ankle_cm": 24},
        ),
        practice.fitter_headers,
    )

    assert_error(response, ApiErrors.INVALID_FAB_ORDER_STATE, 409)
    assert error_id_of(response) != ApiErrors.INVALID_CLINICAL_STATE
    assert read_encounter(api, encounter_id)["clinical_status"] == "AWAITING_DEVICE"
    assert read_fitter(api, practice.fitter_id)["fitting_minutes_booked"] == 0
    assert_list_meta(
        api.list_fitting_records(practice.fitter_headers, {"encounter_id": encounter_id}),
        expected_total=0,
    )


def test_accepting_the_fabricated_device_unblocks_the_same_fitting_session(api):
    """Once the fitter accepts the order the identical session is recorded, its
    minutes are the whole interval, and the encounter reaches the fitted posture.

    PRD: "The resulting `FittingRecord` belongs to its parent `encounter_id`,
    carries `fitter_id` stamped from the acting fitter's identity — the value is
    never accepted from the body — and carries a derived `fitting_minutes`, the
    whole minutes from `fitting_start_at` to `fitting_end_at` rounded up, always at
    least 1."

    Design: Difficulty/cross_entity_state_dependency/awaiting_device_fitting_blocked_until_fab_order_accepted_rejected
    """
    practice, encounter_id, order_id = _order_ready_for_fitting(api)

    accepted = practice.fitting_check(order_id, "ACCEPT", note="device matches the prescription")
    assert accepted["status"] == "ACCEPTED"
    record = practice.fit(
        encounter_id,
        start_at="2026-08-01T11:00:00Z",
        end_at="2026-08-01T11:40:00Z",
        measurement_set={"calf_cm": 36, "ankle_cm": 24},
    )

    assert record["fitting_minutes"] == 40
    assert record["fitter_id"] == practice.fitter_id
    assert read_encounter(api, encounter_id)["clinical_status"] == "FITTED"
    assert read_fitter(api, practice.fitter_id)["fitting_minutes_booked"] == 40


def _submitted_order_with_withdrawn_standards(api):
    """A submitted fabrication order whose supplier's standards attestation has been
    withdrawn while its quality hold stays clear."""
    practice = build_practice(api, product_factory=f.custom_afo_product_payload, with_shelf=False)
    encounter_id = practice.attested_encounter()
    order = practice.place_fab_order(encounter_id)
    assert order["status"] == "SUBMITTED"
    supplier = attest_standards(api, practice.supplier_id, attested=False, quality_hold=False)
    assert supplier["dmepos_standards_attested"] is False
    assert supplier["quality_hold"] is False
    return practice, encounter_id, order["id"]


def test_fabrication_cannot_start_while_the_supplier_standards_are_withdrawn(api):
    """The withdrawal is not a quality hold, so nothing cascaded: the order is still
    submitted and no compliance hold was stamped, yet the event is refused because
    the supplier is no longer attested.

    PRD: "`ERR_SUPPLIER_STANDARDS_NOT_ATTESTED`, HTTP 422, fires when the supplier
    of the encounter's product either has not attested to the DMEPOS supplier
    standards or has an `accreditation_expires_on` strictly before the logical clock
    date; it guards four operations — reserving par stock, placing a
    custom-fabrication order, driving a fabrication event, and dispensing."

    Design: Difficulty/cross_entity_state_dependency/fab_order_acceptance_blocked_when_supplier_standards_withdrawn_rejected
    """
    practice, encounter_id, order_id = _submitted_order_with_withdrawn_standards(api)

    response = api.create_fabrication_event(
        order_id, f.fabrication_event_payload("ACCEPT_ORDER"), inventory_manager_headers()
    )

    assert_error(response, ApiErrors.SUPPLIER_STANDARDS_NOT_ATTESTED, 422)
    assert read_fab_order(api, order_id)["status"] == "SUBMITTED"
    encounter = read_encounter(api, encounter_id)
    assert encounter["compliance_hold"] is False
    assert encounter["clinical_status"] == "AWAITING_DEVICE"
    assert practice.supplier_id is not None


def test_restoring_the_attestation_lets_the_same_event_start_fabrication(api):
    """With the attestation back in place the identical event is accepted and the
    order moves into fabrication, while the encounter stays where it was.

    PRD: "`ACCEPT_ORDER` starts or resumes work: it moves
    `SUBMITTED → IN_FABRICATION`, and it also closes the rework cycle by moving
    `ADJUSTMENT_REQUESTED → IN_FABRICATION` and lifts a hold by moving
    `SUPPLIER_HOLD → IN_FABRICATION`."

    Design: Difficulty/cross_entity_state_dependency/fab_order_acceptance_blocked_when_supplier_standards_withdrawn_rejected
    """
    practice, encounter_id, order_id = _submitted_order_with_withdrawn_standards(api)
    assert_error(
        api.create_fabrication_event(
            order_id, f.fabrication_event_payload("ACCEPT_ORDER"), inventory_manager_headers()
        ),
        ApiErrors.SUPPLIER_STANDARDS_NOT_ATTESTED,
        422,
    )

    attest_standards(api, practice.supplier_id, attested=True, quality_hold=False)
    resumed = validate_success(
        api.create_fabrication_event(
            order_id, f.fabrication_event_payload("ACCEPT_ORDER"), inventory_manager_headers()
        ),
        201,
    )

    assert resumed["status"] == "IN_FABRICATION"
    assert read_encounter(api, encounter_id)["clinical_status"] == "AWAITING_DEVICE"
