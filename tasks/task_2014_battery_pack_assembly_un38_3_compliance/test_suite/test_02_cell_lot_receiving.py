"""Cell lot receiving, quarantine, inspection outcomes, and the bounded retest loop."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_accepted_cell_lot,
    create_battery_pack,
    create_cell_inspection_payload,
    create_cell_lot_payload,
    create_pack_bom,
    create_program,
    get_program,
    validate_error,
    validate_success,
)


class TestCellLotCreation:
    def test_missing_cell_count_rejected(self, api):
        """PRD §2.12: "Before business validation begins, malformed payloads, missing
        required fields, and type mismatches are rejected with `ERR_INVALID_REQUEST`".
        PRD §3.2: "A `QualityEngineer` receives a cell lot into a program by declaring its
        `lot_code` (unique within the program), the `cell_count` of cells in the lot
        (which must be greater than zero), the per-cell `rated_capacity_mah`, and the
        `receiving_soc_percent` declared at the dock".

        Design: Corner/entities/cell_lot_required_fields_enforced
        """
        program = create_program()
        payload = {
            "lot_code": "LOT-X",
            "rated_capacity_mah": 3000,
            "receiving_soc_percent": 40.0,
        }  # cell_count omitted
        resp = api.create_cell_lot(program["id"], payload, TEST_USERS["quality_engineer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_lot_creation_under_missing_program_returns_404(self, api):
        """PRD §2.5: "Nested endpoints are validated strictly left to right: the server
        resolves the program first, then the resource named at the next segment, and so
        on, rejecting immediately with the `404` error of the first path segment that
        does not resolve — `ERR_PROGRAM_NOT_FOUND`".

        Design: Corner/entities/cell_lot_parent_relationship_enforced_via_program_404
        """
        resp = api.create_cell_lot(
            NON_EXISTENT_UUID,
            create_cell_lot_payload("LOT-404", 10, 3000, 40.0),
            TEST_USERS["quality_engineer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND)


class TestInspectionSocTolerance:
    def _quarantined_lot(self, api, receiving_soc=40.0):
        program = create_program()
        headers = TEST_USERS["quality_engineer_headers"]
        lot = validate_success(
            api.create_cell_lot(
                program["id"], create_cell_lot_payload("LOT-TOL", 100, 3000, receiving_soc), headers
            ),
            201,
        )
        validate_success(api.quarantine_cell_lot(program["id"], lot["id"], headers), 200)
        return program["id"], lot["id"]

    def test_pass_beyond_tolerance_rejected(self, api):
        """PRD §3.2: "`measured_soc_percent` must lie within 2.0 percentage points of the
        lot's declared `receiving_soc_percent` in either direction, or the acceptance is
        rejected with `ERR_SOC_OUT_OF_TOLERANCE`."

        Design: Corner/validations/soc_out_of_tolerance_rejects_pass_inspection
        """
        program_id, lot_id = self._quarantined_lot(api, 40.0)
        resp = api.create_cell_inspection(
            program_id,
            lot_id,
            create_cell_inspection_payload(measured_soc_percent=45.5, outcome="PASS"),
            TEST_USERS["quality_engineer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SOC_OUT_OF_TOLERANCE)
        lot = validate_success(api.get_cell_lot(program_id, lot_id, TEST_USERS["any_headers"]))
        assert lot["status"] == "QUARANTINE"

    def test_pass_at_exactly_plus_two_accepted(self, api):
        """PRD §3.2: "`measured_soc_percent` must lie within 2.0 percentage points of the
        lot's declared `receiving_soc_percent` in either direction, or the acceptance is
        rejected with `ERR_SOC_OUT_OF_TOLERANCE`."
        PRD §3.2: "On acceptance the lot's status becomes `ACCEPTED`, the measured value is
        persisted onto the lot as its `measured_soc_percent`".

        Design: Corner/validations/soc_tolerance_boundary_at_exactly_plus_2
        """
        program_id, lot_id = self._quarantined_lot(api, 40.0)
        resp = api.create_cell_inspection(
            program_id,
            lot_id,
            create_cell_inspection_payload(measured_soc_percent=42.0, outcome="PASS"),
            TEST_USERS["quality_engineer_headers"],
        )
        validate_success(resp, 201)
        lot = validate_success(api.get_cell_lot(program_id, lot_id, TEST_USERS["any_headers"]))
        assert lot["status"] == "ACCEPTED"
        assert lot["measured_soc_percent"] == pytest.approx(42.0)


class TestCellLotDepletion:
    def test_depleted_lot_rejects_quarantine(self, api):
        """PRD §3.2: "When the summed `cells_required` across all locked BOMs drawing on a
        lot reaches the lot's `cell_count`, the lot transitions from `ACCEPTED` to
        `DEPLETED` on its own".
        PRD §3.2: "the move requires the lot to be `RECEIVED` (otherwise
        `ERR_LOT_NOT_RECEIVED`)".

        Design: Corner/state_machines/cell_lot_terminal_state_lockdown
        """
        program = create_program()
        lot = create_accepted_cell_lot(program["id"], cell_count=4)
        bom = create_pack_bom(program["id"], lot["id"], cells_required=4)
        create_battery_pack(program["id"], bom["id"])  # consumes all 4 cells

        lot_after = validate_success(api.get_cell_lot(program["id"], lot["id"], TEST_USERS["any_headers"]))
        assert lot_after["status"] == "DEPLETED"

        resp = api.quarantine_cell_lot(
            program["id"], lot["id"], TEST_USERS["quality_engineer_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_RECEIVED)


class TestRetestLoopBound:
    def _drive_lot_to_second_rejection(self, api):
        """FAIL_SOFT self-loop (count 1) -> FAIL_HARD (REJECTED) -> retest (count 2,
        QUARANTINE) -> FAIL_HARD (REJECTED)."""
        program = create_program()
        headers = TEST_USERS["quality_engineer_headers"]
        lot = validate_success(
            api.create_cell_lot(
                program["id"], create_cell_lot_payload("LOT-CYC", 50, 3000, 40.0), headers
            ),
            201,
        )
        validate_success(api.quarantine_cell_lot(program["id"], lot["id"], headers))
        validate_success(
            api.create_cell_inspection(
                program["id"], lot["id"],
                create_cell_inspection_payload(measured_soc_percent=40.0, visual_defect_count=1, outcome="FAIL_SOFT"),
                headers,
            ),
            201,
        )
        validate_success(
            api.create_cell_inspection(
                program["id"], lot["id"],
                create_cell_inspection_payload(measured_soc_percent=40.0, measured_voltage_v=3.10,
                                               visual_defect_count=12, outcome="FAIL_HARD"),
                headers,
            ),
            201,
        )
        validate_success(api.retest_cell_lot(program["id"], lot["id"], headers))
        validate_success(
            api.create_cell_inspection(
                program["id"], lot["id"],
                create_cell_inspection_payload(measured_soc_percent=40.0, measured_voltage_v=3.05,
                                               visual_defect_count=20, outcome="FAIL_HARD"),
                headers,
            ),
            201,
        )
        return program["id"], lot["id"]

    def test_retest_rejected_once_cycle_count_reaches_two(self, api):
        """PRD §3.2: "A `QualityEngineer` may send a `REJECTED` lot back into `QUARANTINE`
        for a retest, but only while `quarantine_cycle_count` remains below 2" and "is
        refused with `ERR_RETEST_LIMIT_EXCEEDED` once the lot has already cycled through
        quarantine twice".

        Design: Difficulty/non_linear_state_machine/cell_lot_cyclic_retest_loop_bounded
        """
        program_id, lot_id = self._drive_lot_to_second_rejection(api)
        resp = api.retest_cell_lot(program_id, lot_id, TEST_USERS["quality_engineer_headers"])
        validate_error(resp, ApiErrorId.ERR_RETEST_LIMIT_EXCEEDED)
        lot = validate_success(api.get_cell_lot(program_id, lot_id, TEST_USERS["any_headers"]))
        assert lot["status"] == "REJECTED"
        assert lot["quarantine_cycle_count"] == 2

    def test_fail_soft_self_loops_and_fail_hard_drops_risk_index(self, api):
        """PRD §3.2: "A `FAIL_SOFT` outcome is inconclusive — the lot remains in
        `QUARANTINE` via a self-loop and its `quarantine_cycle_count` increments by 1."
        PRD §2.7: "A lot rejected by a hard-failed inspection reduces the index by 3,
        never driving it below a floor of 0."

        Design: Difficulty/non_linear_state_machine/cell_lot_cyclic_retest_loop_bounded
        """
        program = create_program()
        headers = TEST_USERS["quality_engineer_headers"]
        lot = validate_success(
            api.create_cell_lot(
                program["id"], create_cell_lot_payload("LOT-CYC2", 50, 3000, 40.0), headers
            ),
            201,
        )
        validate_success(api.quarantine_cell_lot(program["id"], lot["id"], headers))

        # FAIL_SOFT: self-loop, cycle count increments.
        validate_success(
            api.create_cell_inspection(
                program["id"], lot["id"],
                create_cell_inspection_payload(measured_soc_percent=40.0, visual_defect_count=2, outcome="FAIL_SOFT"),
                headers,
            ),
            201,
        )
        lot_mid = validate_success(api.get_cell_lot(program["id"], lot["id"], TEST_USERS["any_headers"]))
        assert lot_mid["status"] == "QUARANTINE"
        assert lot_mid["quarantine_cycle_count"] == 1

        # FAIL_HARD: REJECTED and program risk index drops by exactly 3.
        validate_success(
            api.create_cell_inspection(
                program["id"], lot["id"],
                create_cell_inspection_payload(measured_soc_percent=40.0, measured_voltage_v=3.10,
                                               visual_defect_count=9, outcome="FAIL_HARD"),
                headers,
            ),
            201,
        )
        lot_end = validate_success(api.get_cell_lot(program["id"], lot["id"], TEST_USERS["any_headers"]))
        assert lot_end["status"] == "REJECTED"
        assert lot_end["quarantine_cycle_count"] == 1
        assert get_program(program["id"])["compliance_risk_index"] == 97
