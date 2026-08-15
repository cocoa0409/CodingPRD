"""Inventory lots: quarantine cycle, segregation, unit conservation,
allocation gates (PRD §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    allocate,
    assert_lot_units_conservation,
    create_complaint,
    create_customer,
    create_shipment,
    get_success_data,
    make_qa_manager_headers,
    setup_completed_run,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PM, WH


class TestQuarantineCycle:
    def test_lot_quarantine_release_cycle(self, api):
        """PRD §3.7: "A QAManager may manually quarantine an AVAILABLE lot,
        recording quarantined_by"; "Releasing quarantine requires the caller
        to differ from quarantined_by (§2.8)" and returns the lot to
        AVAILABLE.

        Design: Corner/state_machines/lot_quarantine_release_cycle
        """
        ctx = setup_completed_run(run_code="R-QC")
        lot_id = ctx["lot"]["id"]
        quarantined = validate_success(api.quarantine_lot(
            lot_id, make_qa_manager_headers("qa_1")))
        assert quarantined["status"] == "QUARANTINED"
        released = validate_success(api.release_lot_quarantine(
            lot_id, make_qa_manager_headers("qa_2")))
        assert released["status"] == "AVAILABLE"


class TestLotSegregationOfDuties:
    def test_sod_lot_release_by_quarantiner_rejected(self, api):
        """PRD §2.8: "The QAManager releasing an InventoryLot from
        quarantine must not be the same X-User-ID recorded in the lot's
        quarantined_by. A violation on any of these is rejected with
        ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

        Design: Corner/validations/sod_lot_release_by_quarantiner_rejected
        """
        ctx = setup_completed_run(run_code="R-SD")
        lot_id = ctx["lot"]["id"]
        validate_success(api.quarantine_lot(
            lot_id, make_qa_manager_headers("qa_1")))
        resp = api.release_lot_quarantine(lot_id, make_qa_manager_headers("qa_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        lot = get_success_data(api.get_inventory_lot(lot_id, PM))
        assert lot["status"] == "QUARANTINED"


class TestReleaseBlockedByOpenComplaint:
    def test_lot_release_blocked_by_open_complaint(self, api):
        """PRD §3.7: "Releasing quarantine ... is blocked while any
        QualityComplaint on any lot sharing this lot's run_id is in
        UNDER_REVIEW or LAB_TEST, else ERR_COMPLAINT_STILL_OPEN
        (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_by_open_complaint
        """
        ctx = setup_completed_run(run_code="R-H")
        lot_id = ctx["lot"]["id"]
        validate_success(api.quarantine_lot(
            lot_id, make_qa_manager_headers("qa_1")))
        create_complaint(lot_id, complaint_code="QC-H", qa_user="qa_1")
        resp = api.release_lot_quarantine(lot_id, make_qa_manager_headers("qa_2"))
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_STILL_OPEN)
        lot = get_success_data(api.get_inventory_lot(lot_id, PM))
        assert lot["status"] == "QUARANTINED"

    def test_lot_release_blocked_by_lab_test_complaint(self, api):
        """PRD §3.7: "Releasing quarantine ... is blocked while any
        QualityComplaint on any lot sharing this lot's run_id is in
        UNDER_REVIEW or LAB_TEST, else ERR_COMPLAINT_STILL_OPEN
        (HTTP 422)." A complaint currently in LAB_TEST blocks equally.

        Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_by_open_complaint
        """
        ctx = setup_completed_run(run_code="R-H2")
        lot_id = ctx["lot"]["id"]
        validate_success(api.quarantine_lot(
            lot_id, make_qa_manager_headers("qa_1")))
        qc = create_complaint(lot_id, complaint_code="QC-H2", qa_user="qa_1")
        validate_success(api.send_complaint_to_lab(
            qc["id"], make_qa_manager_headers("qa_1")))
        resp = api.release_lot_quarantine(lot_id, make_qa_manager_headers("qa_2"))
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_STILL_OPEN)
        lot = get_success_data(api.get_inventory_lot(lot_id, PM))
        assert lot["status"] == "QUARANTINED"


class TestAllocationGates:
    def test_lot_not_available_when_quarantined(self, api):
        """PRD §3.8: "The lot must be AVAILABLE with best_before strictly in
        the future, else ERR_LOT_NOT_AVAILABLE"."

        Design: Corner/validations/lot_not_available_when_quarantined
        """
        ctx = setup_completed_run(run_code="R-QA")
        lot_id = ctx["lot"]["id"]
        validate_success(api.quarantine_lot(
            lot_id, make_qa_manager_headers("qa_1")))
        shipment = create_shipment(create_customer()["id"],
                                   shipment_code="SH-QA")
        resp = api.create_allocation(shipment["id"],
                                     {"lot_id": lot_id, "units": 100}, WH)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE)

    def test_insufficient_lot_units_rejected(self, api):
        """PRD §3.8: "the requested units must not exceed
        lot.units_available, else ERR_INSUFFICIENT_LOT_UNITS". 2001 units
        from a 2000-unit lot is over by one.

        Design: Corner/validations/insufficient_lot_units_rejected
        """
        ctx = setup_completed_run(run_code="R-IU")
        shipment = create_shipment(create_customer()["id"],
                                   shipment_code="SH-IU")
        resp = api.create_allocation(shipment["id"],
                                     {"lot_id": ctx["lot"]["id"],
                                      "units": 2001}, WH)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_UNITS)

    def test_allocation_double_release_rejected(self, api):
        """PRD §3.8: "A manual release is permitted only while the shipment
        is still PLANNED" and a RELEASED allocation is terminal; a second
        release fails the state gate (§5 ERR_INVALID_STATE). The lot's units
        are credited exactly once.

        Design: Corner/state_machines/allocation_double_release_rejected
        """
        ctx = setup_completed_run(run_code="R-AR")
        shipment = create_shipment(create_customer()["id"],
                                   shipment_code="SH-AR")
        allocation = allocate(shipment["id"], ctx["lot"]["id"], 500)
        validate_success(api.release_allocation(allocation["id"], WH))
        resp = api.release_allocation(allocation["id"], WH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        lot = get_success_data(api.get_inventory_lot(ctx["lot"]["id"], PM))
        assert lot["units_available"] == 2000


class TestLotUnitsConservation:
    def test_lot_units_conservation_across_allocate_release(self, api):
        """PRD §3.7: "units_available is the unreserved, unshipped,
        undestroyed count; units_reserved is the count under ACTIVE
        allocations; units_shipped is the count under FULFILLED
        allocations; units_destroyed starts at 0." Allocating 3000 from a
        10000-unit lot then releasing the allocation restores
        units_available 10000 / units_reserved 0 — the forward action is
        fully undone.

        Design: Difficulty/compensating_invariant/lot_units_conservation
        """
        ctx = setup_completed_run(run_code="R-U", planned_units=10000,
                                  actual_units=10000, mix_metered_litres=460.0)
        lot_id = ctx["lot"]["id"]
        shipment = create_shipment(create_customer()["id"],
                                   shipment_code="SH-U")
        allocation = allocate(shipment["id"], lot_id, 3000)
        lot = get_success_data(api.get_inventory_lot(lot_id, PM))
        assert lot["units_available"] == 7000
        assert lot["units_reserved"] == 3000
        assert_lot_units_conservation(lot)
        validate_success(api.release_allocation(allocation["id"], WH))
        lot = get_success_data(api.get_inventory_lot(lot_id, PM))
        assert lot["units_available"] == 10000
        assert lot["units_reserved"] == 0
        assert_lot_units_conservation(lot)

    def test_lot_units_conservation_across_delivery(self, api):
        """PRD §3.8: delivery "flips every ACTIVE allocation to FULFILLED,
        and on each lot moves the allocated units from units_reserved to
        units_shipped." After allocating 4000 and delivering, the lot shows
        units_available 6000, units_reserved 0, units_shipped 4000,
        units_destroyed 0 — the four buckets still sum to units_produced
        10000.

        Design: Difficulty/compensating_invariant/lot_units_conservation
        """
        ctx = setup_completed_run(run_code="R-U2", planned_units=10000,
                                  actual_units=10000, mix_metered_litres=460.0)
        lot_id = ctx["lot"]["id"]
        shipment = create_shipment(create_customer()["id"],
                                   shipment_code="SH-U2")
        allocate(shipment["id"], lot_id, 4000)
        get_success_data(api.load_shipment(shipment["id"], WH))
        get_success_data(api.dispatch_shipment(shipment["id"], WH))
        validate_success(api.deliver_shipment(shipment["id"], WH))
        lot = get_success_data(api.get_inventory_lot(lot_id, PM))
        assert lot["units_available"] == 6000
        assert lot["units_reserved"] == 0
        assert lot["units_shipped"] == 4000
        assert lot["units_destroyed"] == 0
        assert_lot_units_conservation(lot)


class TestShipmentEmptyLoad:
    def test_shipment_empty_load_rejected(self, api):
        """PRD §3.8: "Loading requires allocated_units greater than 0, else
        ERR_SHIPMENT_EMPTY"."

        Design: Corner/validations/shipment_empty_load_rejected
        """
        shipment = create_shipment(create_customer()["id"],
                                   shipment_code="SH-EM")
        resp = api.load_shipment(shipment["id"], WH)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_EMPTY)
