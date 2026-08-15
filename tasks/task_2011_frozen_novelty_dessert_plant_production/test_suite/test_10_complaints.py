"""Quality complaints: lab retest cycle, substantiation gates and cascade
(PRD §3.10)."""
from test_helpers import (
    ApiErrorId,
    allocate,
    create_complaint,
    create_customer,
    create_shipment,
    get_success_data,
    make_customer_rep_headers,
    make_qa_manager_headers,
    setup_completed_run,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PM, WH


class TestLabRetestCycle:
    def test_complaint_lab_retest_cycle(self, api):
        """PRD §3.10: "Sending to lab moves UNDER_REVIEW → LAB_TEST and
        increments lab_cycle_count"; "Recording a lab result moves LAB_TEST
        → UNDER_REVIEW"; "The UNDER_REVIEW ↔ LAB_TEST loop permits
        retesting within the cycle cap."

        Design: Difficulty/non_linear_state_machine/complaint_lab_retest_cycle
        """
        ctx = setup_completed_run(run_code="R-Q")
        qc = create_complaint(ctx["lot"]["id"], complaint_code="QC-LOOP")
        qa = make_qa_manager_headers("qa_1")
        first = validate_success(api.send_complaint_to_lab(qc["id"], qa))
        assert first["status"] == "LAB_TEST"
        assert first["lab_cycle_count"] == 1
        back = validate_success(api.record_lab_result(qc["id"], {}, qa))
        assert back["status"] == "UNDER_REVIEW"
        second = validate_success(api.send_complaint_to_lab(qc["id"], qa))
        assert second["status"] == "LAB_TEST"
        assert second["lab_cycle_count"] == 2
        back2 = validate_success(api.record_lab_result(qc["id"], {}, qa))
        assert back2["status"] == "UNDER_REVIEW"

    def test_complaint_lab_cycle_count_increments_per_cycle(self, api):
        """PRD §3.10: "Sending to lab moves UNDER_REVIEW → LAB_TEST and
        increments lab_cycle_count". After two full cycles the count is 2,
        proving the machine re-entered UNDER_REVIEW rather than progressing
        linearly.

        Design: Difficulty/non_linear_state_machine/complaint_lab_retest_cycle
        """
        ctx = setup_completed_run(run_code="R-Q2")
        qc = create_complaint(ctx["lot"]["id"], complaint_code="QC-LOOP2")
        qa = make_qa_manager_headers("qa_1")
        for _ in range(2):
            validate_success(api.send_complaint_to_lab(qc["id"], qa))
            validate_success(api.record_lab_result(qc["id"], {}, qa))
        complaint = get_success_data(api.get_quality_complaint(qc["id"], PM))
        assert complaint["lab_cycle_count"] == 2
        assert complaint["status"] == "UNDER_REVIEW"


class TestSubstantiationGates:
    def test_lab_result_required_rejected(self, api):
        """PRD §3.10: "for HEAT_SHOCK complaints two gates apply first:
        measured_ice_crystal_um must be recorded, else
        ERR_LAB_RESULT_REQUIRED (HTTP 422)"."

        Design: Corner/validations/lab_result_required_rejected
        """
        ctx = setup_completed_run(run_code="R-LR")
        qc = create_complaint(ctx["lot"]["id"], complaint_code="QC-LR",
                              complaint_type="HEAT_SHOCK")
        resp = api.disposition_complaint(qc["id"], {"outcome": "SUBSTANTIATED"},
                                         make_qa_manager_headers("qa_1"))
        validate_error(resp, ApiErrorId.ERR_LAB_RESULT_REQUIRED)

    def test_heat_shock_exactly_at_limit_rejected(self, api):
        """PRD §3.10: "the measured value must be strictly greater than the
        format threshold — 120 microns for NOVELTY, 150 microns for BULK —
        else ERR_HEAT_SHOCK_NOT_PROVEN (HTTP 422). A measurement exactly
        equal to the threshold is not substantiable."

        Design: Corner/calculations/heat_shock_exactly_at_limit_rejected
        """
        ctx = setup_completed_run(run_code="R-HS")
        qc = create_complaint(ctx["lot"]["id"], complaint_code="QC-HS",
                              complaint_type="HEAT_SHOCK")
        qa = make_qa_manager_headers("qa_1")
        validate_success(api.send_complaint_to_lab(qc["id"], qa))
        validate_success(api.record_lab_result(
            qc["id"], {"measured_ice_crystal_um": 120.0}, qa))
        resp = api.disposition_complaint(qc["id"], {"outcome": "SUBSTANTIATED"},
                                         qa)
        validate_error(resp, ApiErrorId.ERR_HEAT_SHOCK_NOT_PROVEN)
        complaint = get_success_data(api.get_quality_complaint(qc["id"], PM))
        assert complaint["status"] == "UNDER_REVIEW"
        # No quarantine cascade fired on the lot.
        lot = get_success_data(api.get_inventory_lot(ctx["lot"]["id"], PM))
        assert lot["status"] == "AVAILABLE"


class TestLabCycleCap:
    def test_lab_cycle_exhausted_rejected(self, api):
        """PRD §3.10: "the cap is 3, and a fourth send rejects with
        ERR_LAB_CYCLE_EXHAUSTED (HTTP 409)"."

        Design: Corner/validations/lab_cycle_exhausted_rejected
        """
        ctx = setup_completed_run(run_code="R-CY")
        qc = create_complaint(ctx["lot"]["id"], complaint_code="QC-CY")
        qa = make_qa_manager_headers("qa_1")
        for _ in range(3):
            validate_success(api.send_complaint_to_lab(qc["id"], qa))
            validate_success(api.record_lab_result(qc["id"], {}, qa))
        resp = api.send_complaint_to_lab(qc["id"], qa)
        validate_error(resp, ApiErrorId.ERR_LAB_CYCLE_EXHAUSTED)


class TestComplaintWithdrawal:
    def test_complaint_lab_after_withdraw_rejected(self, api):
        """PRD §3.10: "Withdrawal is permitted from UNDER_REVIEW or
        LAB_TEST." After withdrawal the complaint is terminal, so
        send-to-lab fails the state gate (§5 ERR_INVALID_STATE: "Target
        resource's state does not allow the requested transition")."

        Design: Corner/state_machines/complaint_lab_after_withdraw_rejected
        """
        ctx = setup_completed_run(run_code="R-W")
        customer = create_customer()
        qc = create_complaint(ctx["lot"]["id"], complaint_code="QC-W",
                              filed_by_customer_id=customer["id"])
        validate_success(api.withdraw_complaint(
            qc["id"], make_customer_rep_headers(customer["id"])))
        resp = api.send_complaint_to_lab(qc["id"],
                                         make_qa_manager_headers("qa_1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSubstantiationCascade:
    def test_complaint_substantiation_cascade(self, api):
        """PRD §3.10: "Every InventoryLot sharing the complaint's lot's
        run_id that is currently AVAILABLE flips to QUARANTINED with
        quarantined_by set to the acting QA X-User-ID. Each such
        quarantined lot's ACTIVE allocations are released with
        release_reason COMPLAINT_CASCADE, returning reserved units to
        available. Every shipment that loses an allocation recomputes
        allocated_units; any such shipment in LOADED status regresses to
        PLANNED."

        Design: Difficulty/transitive_cascade/complaint_substantiation_cascade
        """
        ctx = setup_completed_run(run_code="R-K", planned_units=10000,
                                  actual_units=10000, mix_metered_litres=460.0)
        customer = create_customer()
        shipment = create_shipment(customer["id"], shipment_code="SH-K")
        allocation = allocate(shipment["id"], ctx["lot"]["id"], 3000)
        get_success_data(api.load_shipment(shipment["id"], WH))
        qc = create_complaint(ctx["lot"]["id"], complaint_code="QC-K")
        dispositioned = validate_success(api.disposition_complaint(
            qc["id"], {"outcome": "SUBSTANTIATED"},
            make_qa_manager_headers("qa_2")))
        assert dispositioned["status"] == "DISPOSITIONED_SUBSTANTIATED"
        # Link 1: lot quarantined.
        lot = get_success_data(api.get_inventory_lot(ctx["lot"]["id"], PM))
        assert lot["status"] == "QUARANTINED"
        # Link 2: allocation released, units back to available.
        alloc = get_success_data(api.get_allocation(allocation["id"], PM))
        assert alloc["status"] == "RELEASED"
        assert alloc["release_reason"] == "COMPLAINT_CASCADE"
        assert lot["units_reserved"] == 0
        assert lot["units_available"] == 10000
        # Link 3: LOADED shipment regressed to PLANNED with 0 units.
        ship = get_success_data(api.get_shipment(shipment["id"], PM))
        assert ship["status"] == "PLANNED"
        assert ship["allocated_units"] == 0

    def test_quarantine_regresses_loaded_shipment_only(self, api):
        """PRD §3.10: "any such shipment in LOADED status regresses to
        PLANNED" — a shipment still PLANNED keeps its state when its
        allocation is released by the cascade.

        Design: Difficulty/transitive_cascade/complaint_substantiation_cascade
        """
        ctx = setup_completed_run(run_code="R-K2", planned_units=10000,
                                  actual_units=10000, mix_metered_litres=460.0)
        customer = create_customer()
        shipment = create_shipment(customer["id"], shipment_code="SH-K2")
        allocation = allocate(shipment["id"], ctx["lot"]["id"], 3000)
        # Not loaded: shipment stays PLANNED even before the cascade.
        qc = create_complaint(ctx["lot"]["id"], complaint_code="QC-K2")
        validate_success(api.disposition_complaint(
            qc["id"], {"outcome": "SUBSTANTIATED"},
            make_qa_manager_headers("qa_2")))
        alloc = get_success_data(api.get_allocation(allocation["id"], PM))
        assert alloc["status"] == "RELEASED"
        assert alloc["release_reason"] == "COMPLAINT_CASCADE"
        ship = get_success_data(api.get_shipment(shipment["id"], PM))
        assert ship["status"] == "PLANNED"
        assert ship["allocated_units"] == 0
