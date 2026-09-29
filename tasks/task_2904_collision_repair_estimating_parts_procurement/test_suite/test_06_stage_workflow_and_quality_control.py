"""The shop floor: driving an order through the stages and signing it off.

The repair workflow is not a ladder. A vehicle that fails its post-repair
inspection is sent back to the body shop, needs a fresh stall booking to get
back in, and is re-inspected under a second certificate number. On the way up,
a hop is held not only by the order's own stage but by rows on other entities:
an unverified driver-assistance calibration keeps the car out of quality
control, and a part that has landed on the dock cannot be bolted on until the
car itself is in the repair bay. Where two of those refusals are due at once,
the safety defect is the one the shop is told about.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import QC_INSPECTOR_HEADERS, TECHNICIAN_HEADERS

# The owner's share on these worlds is the 25,000-cent deductible, well under
# the 50,000-cent signature threshold, so the money gate never freezes the
# stage machine and the workflow rules are what the tests are reading.
_UNDER_THRESHOLD_ORDER = {"deductible_cents": 25000}

# A second day of shop windows, for the bookings the rework cycle needs.
_DAY_TWO = "2026-08-02"
_D2_T0800 = f"{_DAY_TWO}T08:00:00Z"
_D2_T1000 = f"{_DAY_TWO}T10:00:00Z"
_D2_T1300 = f"{_DAY_TWO}T13:00:00Z"
_D2_T1500 = f"{_DAY_TWO}T15:00:00Z"

# A calibration window late in the first day, clear of both stall windows.
_CAL_START = fx.T1600
_CAL_END = "2026-08-01T17:00:00Z"

_ADAS_RECORD = {
    "procedure_code": "ADAS-CAL-2",
    "source": "OEM_PORTAL",
    "operation_scope": "ADAS",
    "requires_calibration": True,
    "calibration_type": "STATIC",
}


def _world_awaiting_inspection(api):
    """A locked order walked all the way to `READY_FOR_QC` with no open gates.

    No procedure records and no parts lines exist, so the safety and constraint
    rungs are vacuously satisfied and the inspection verdict is the only thing
    under test. The body booking runs 08:00-12:00 and the paint booking
    13:00-15:00, both already retired by the time the car reaches inspection.
    """
    return fx.locked_world_at(
        api, C.STAGE_READY_FOR_QC, order_overrides=dict(_UNDER_THRESHOLD_ORDER)
    )


def _book_rework_repair(api, world):
    """A second `REPAIR` booking on the body stall, for the rework hop to enter."""
    booking = fx.book_stall(
        api,
        world["order_id"],
        world["body_stall"]["id"],
        C.STAGE_REPAIR,
        _D2_T0800,
        _D2_T1000,
    )
    world["rework_assignment"] = booking
    return booking


def _fail_the_inspection(api, world):
    """File an inspection that fails the checklist and still shows live codes."""
    response = api.create_qc_inspection(
        world["order_id"],
        f.qc_inspection_payload(False, 2, scan_report_ref="SCAN-001"),
        QC_INSPECTOR_HEADERS,
    )
    return validate_success(response, 201)


class TestReworkCycleAfterAFailedInspection:
    """A failed sign-off sends the car back to the body shop and round again."""

    def test_an_inspection_failing_on_both_counts_blames_the_checklist(self, api):
        """A failed checklist with live trouble codes is reported as CHECKLIST.

        PRD: "Its `result` is `PASS` only when `checklist_passed` is true **and** `post_scan_dtc_count` is exactly 0; every other combination is a `FAIL`."
        PRD: "On a `FAIL` the `failure_reason` is set, and its two values are ranked rather than combined: `CHECKLIST` when `checklist_passed` is false, and `DTC_PRESENT` only when the checklist passed but codes remain — so an inspection that fails on both counts reports `CHECKLIST`."
        PRD: "A `FAIL` leaves `warranty_certificate_number` and `warranty_expires_at` null, and it drives the order's `stage` from `READY_FOR_QC` to `QC_FAILED`, which is the head of the rework cycle described in §3.8."
        Design: Difficulty/non_linear_state_machine/repair_order_rework_cycle_returns_from_qc_failed_to_repair
        """
        world = _world_awaiting_inspection(api)
        _book_rework_repair(api, world)

        inspection = _fail_the_inspection(api, world)

        assert inspection["result"] == "FAIL", inspection
        assert inspection["failure_reason"] == "CHECKLIST", inspection
        A.assert_null(
            inspection["warranty_certificate_number"], "warranty_certificate_number"
        )
        A.assert_null(inspection["warranty_expires_at"], "warranty_expires_at")

        order = fx.read_order(api, world["order_id"])
        A.assert_stage(order, C.STAGE_QC_FAILED)
        A.assert_count(order["qc_inspection_count"], 1, "qc_inspection_count")

    def test_the_rework_hop_re_enters_repair_and_promotes_the_second_booking(self, api):
        """Rework puts the car back in a body stall it has already occupied once.

        PRD: "Into `REPAIR` from `QC_FAILED`: identically, at least one `SCHEDULED` `REPAIR` booking must exist or the hop is refused with `ERR_NO_STAGE_ASSIGNMENT`; on success every such booking becomes `ACTIVE` and the order's `version` increments."
        PRD: "When an order enters the stage a `SCHEDULED` booking serves, that booking becomes `ACTIVE` and its `version` increments — but the stall's `booked_minutes` is *unchanged*, because `SCHEDULED` and `ACTIVE` both occupy the stall."
        PRD: "When an order leaves that stage, or when the vehicle is released, an `ACTIVE` booking becomes `COMPLETED`, its stall's `booked_minutes` drops by its `occupied_minutes`, and both the booking's and the stall's `version` increment."
        Design: Difficulty/non_linear_state_machine/repair_order_rework_cycle_returns_from_qc_failed_to_repair
        """
        world = _world_awaiting_inspection(api)
        rework = _book_rework_repair(api, world)
        _fail_the_inspection(api, world)

        response = api.advance_stage(
            world["order_id"],
            f.stage_advance_payload(C.STAGE_REPAIR),
            TECHNICIAN_HEADERS,
        )
        order = validate_success(response, 200)
        A.assert_stage(order, C.STAGE_REPAIR)

        assert fx.read_assignment(api, rework["id"])["status"] == "ACTIVE"
        assert (
            fx.read_assignment(api, world["repair_assignment"]["id"])["status"]
            == "COMPLETED"
        )
        assert (
            fx.read_assignment(api, world["refinish_assignment"]["id"])["status"]
            == "COMPLETED"
        )

        body_stall = fx.read_stall(api, world["body_stall"]["id"])
        paint_stall = fx.read_stall(api, world["paint_stall"]["id"])
        A.assert_count(body_stall["booked_minutes"], 120, "body booked_minutes")
        A.assert_count(paint_stall["booked_minutes"], 0, "paint booked_minutes")

    def test_the_rework_edge_cannot_be_walked_twice_for_one_failure(self, api):
        """Once back in the body shop, asking for REPAIR again is not a legal hop.

        PRD: "`REPAIR` follows either `PARTS_STAGED` or `QC_FAILED` — that second edge is the rework cycle, and an order that re-enters `REPAIR` must traverse the remaining stages again from there."
        PRD: "Any other pair, including an attempt to re-enter the current stage and any attempt to skip a stage, is refused with `ERR_STAGE_SEQUENCE_INVALID`."
        Design: Difficulty/non_linear_state_machine/repair_order_rework_cycle_returns_from_qc_failed_to_repair
        """
        world = _world_awaiting_inspection(api)
        _book_rework_repair(api, world)
        _fail_the_inspection(api, world)
        fx.advance_stage(api, world["order_id"], C.STAGE_REPAIR)

        response = api.advance_stage(
            world["order_id"],
            f.stage_advance_payload(C.STAGE_REPAIR),
            TECHNICIAN_HEADERS,
        )
        validate_error(response, ApiErrorId.STAGE_SEQUENCE_INVALID.value, 409)

        A.assert_stage(fx.read_order(api, world["order_id"]), C.STAGE_REPAIR)

    def test_the_re_inspection_after_rework_is_numbered_two_and_carries_the_warranty(
        self, api
    ):
        """The second trip through the stages ends in certificate number two.

        PRD: "Every inspection, pass or fail, takes a `sequence_number` equal to the order's `qc_inspection_count` plus one, so the first inspection on an order is number 1 and a re-inspection after rework is number 2, and it records the acting `X-User-ID` as its `inspector_user_id`."
        PRD: "The `warranty_certificate_number` is composed as the literal `"WC-"`, then the order's `claim_number`, then a literal `"-"`, then the `sequence_number` — so the second inspection on claim `CLM-2026-0001`, if the first one failed, issues `WC-CLM-2026-0001-2`."
        PRD: "The `warranty_expires_at` is the logical clock at the moment of the pass plus exactly 365 days, treating a day as 86,400 seconds with no calendar or leap adjustment."
        Design: Difficulty/non_linear_state_machine/repair_order_rework_cycle_returns_from_qc_failed_to_repair
        """
        world = _world_awaiting_inspection(api)
        _book_rework_repair(api, world)
        _fail_the_inspection(api, world)
        fx.advance_stage(api, world["order_id"], C.STAGE_REPAIR)

        # The car walks the remaining stages again from there.
        fx.book_stall(
            api,
            world["order_id"],
            world["paint_stall"]["id"],
            C.STAGE_REFINISH_CALIBRATION,
            _D2_T1300,
            _D2_T1500,
        )
        fx.advance_stage(api, world["order_id"], C.STAGE_REFINISH_CALIBRATION)
        fx.advance_stage(api, world["order_id"], C.STAGE_READY_FOR_QC)

        response = api.create_qc_inspection(
            world["order_id"],
            f.qc_inspection_payload(True, 0, scan_report_ref="SCAN-002"),
            QC_INSPECTOR_HEADERS,
        )
        inspection = validate_success(response, 201)

        assert inspection["result"] == "PASS", inspection
        A.assert_count(inspection["sequence_number"], 2, "sequence_number")
        A.assert_warranty(inspection, world["claim_number"], C.CLOCK_DEFAULT)

        order = fx.read_order(api, world["order_id"])
        A.assert_count(order["qc_inspection_count"], 2, "qc_inspection_count")


def _world_with_a_required_adas_calibration(api):
    """A car in refinish whose disturbed sensor has still not been recalibrated.

    The teardown finding touched a driver-assistance component, so the blueprint
    already demanded the ADAS procedure research. That record needs a static
    calibration and is sitting at `REQUIRED`; its adherence paperwork is on file,
    so the adherence gate cannot mask the calibration gate.
    """
    world = fx.locked_world_at(
        api,
        C.STAGE_REFINISH_CALIBRATION,
        findings=[
            {
                "panel_code": "FRT-BUMPER",
                "severity": "MODERATE",
                "adas_component_touched": True,
            }
        ],
        procedures=[dict(_ADAS_RECORD)],
        order_overrides=dict(_UNDER_THRESHOLD_ORDER),
    )
    world["bay"] = fx.create_bay(
        api, name="Bay B", supported_types=["STATIC"], concurrent_capacity=2
    )
    world["record_id"] = world["procedure_records"][0]["id"]
    return world


def _ask_for_quality_control(api, world):
    """The identical hop into `READY_FOR_QC`, re-fired at each calibration state."""
    return api.advance_stage(
        world["order_id"],
        f.stage_advance_payload(C.STAGE_READY_FOR_QC),
        TECHNICIAN_HEADERS,
    )


class TestQualityControlWaitsOnTheAdasCalibration:
    """The hop is decided by a row on another entity, not by the order's stage."""

    def test_the_hop_is_refused_while_the_sensor_calibration_is_only_required(self, api):
        """A car in refinish cannot move on with a calibration still outstanding.

        PRD: "Into `READY_FOR_QC` from `REFINISH_CALIBRATION`: every procedure record on the order that needs calibration must have reached `PASSED` — no record may still be at `REQUIRED`, `SCHEDULED` or `FAILED` — or the hop is refused with `ERR_CALIBRATION_NOT_VERIFIED`; and **every** procedure record on the order, in every scope, must have `adherence_documented` true, or the hop is refused with `ERR_PROCEDURE_ADHERENCE_MISSING`."
        PRD: "At creation, a record whose `requires_calibration` is false is born at `calibration_status` `NOT_REQUIRED` and stays there permanently; a record whose `requires_calibration` is true is born at `REQUIRED`."
        Design: Difficulty/cross_entity_state_dependency/order_cannot_reach_ready_for_qc_until_the_adas_record_is_passed
        """
        world = _world_with_a_required_adas_calibration(api)

        record = fx.read_procedure_record(api, world["record_id"])
        assert record["calibration_status"] == "REQUIRED", record

        validate_error(
            _ask_for_quality_control(api, world),
            ApiErrorId.CALIBRATION_NOT_VERIFIED.value,
            422,
        )
        A.assert_stage(
            fx.read_order(api, world["order_id"]), C.STAGE_REFINISH_CALIBRATION
        )

    def test_a_booked_calibration_is_not_yet_a_verified_one(self, api):
        """Booking the bay moves the record on but does not open the gate.

        PRD: "Scheduling a calibration books the record into a bay for a window, moving `calibration_status` from `REQUIRED` to `SCHEDULED`."
        PRD: "Into `READY_FOR_QC` from `REFINISH_CALIBRATION`: every procedure record on the order that needs calibration must have reached `PASSED` — no record may still be at `REQUIRED`, `SCHEDULED` or `FAILED` — or the hop is refused with `ERR_CALIBRATION_NOT_VERIFIED`; and **every** procedure record on the order, in every scope, must have `adherence_documented` true, or the hop is refused with `ERR_PROCEDURE_ADHERENCE_MISSING`."
        Design: Difficulty/cross_entity_state_dependency/order_cannot_reach_ready_for_qc_until_the_adas_record_is_passed
        """
        world = _world_with_a_required_adas_calibration(api)

        booked = validate_success(
            api.schedule_calibration(
                world["record_id"],
                f.calibration_schedule_payload(
                    world["bay"]["id"], _CAL_START, _CAL_END
                ),
                TECHNICIAN_HEADERS,
            ),
            200,
        )
        assert booked["calibration_status"] == "SCHEDULED", booked
        A.assert_count(
            fx.read_bay(api, world["bay"]["id"])["scheduled_window_count"],
            1,
            "scheduled_window_count",
        )

        validate_error(
            _ask_for_quality_control(api, world),
            ApiErrorId.CALIBRATION_NOT_VERIFIED.value,
            422,
        )
        A.assert_stage(
            fx.read_order(api, world["order_id"]), C.STAGE_REFINISH_CALIBRATION
        )

    def test_a_failed_calibration_frees_the_bay_window_and_still_blocks_the_hop(
        self, api
    ):
        """Live trouble codes fail the calibration and release the booked window.

        PRD: "The verdict is not simply what was submitted: `calibration_status` becomes `PASSED` only when the submitted `result` is `PASS` **and** `post_scan_dtc_count` is zero."
        PRD: "A failure sets the same two fields, and additionally **clears** `bay_id`, `window_start` and `window_end` so the bay window is freed for a re-book, recomputes the bay's `scheduled_window_count`, and increments the record's `version` and the bay's `version`."
        PRD: "A failed record blocks the hop into `READY_FOR_QC` with `ERR_CALIBRATION_NOT_VERIFIED` until a re-calibration passes."
        Design: Difficulty/cross_entity_state_dependency/order_cannot_reach_ready_for_qc_until_the_adas_record_is_passed
        """
        world = _world_with_a_required_adas_calibration(api)
        fx.schedule_calibration(
            api, world["record_id"], world["bay"]["id"], _CAL_START, _CAL_END
        )

        failed = validate_success(
            api.record_calibration_result(
                world["record_id"],
                f.calibration_result_payload("FAIL", 3, scan_report_ref="SCAN-CAL-1"),
                TECHNICIAN_HEADERS,
            ),
            200,
        )
        assert failed["calibration_status"] == "FAILED", failed
        A.assert_null(failed["bay_id"], "bay_id")
        A.assert_null(failed["window_start"], "window_start")
        A.assert_null(failed["window_end"], "window_end")
        A.assert_count(
            fx.read_bay(api, world["bay"]["id"])["scheduled_window_count"],
            0,
            "scheduled_window_count",
        )

        validate_error(
            _ask_for_quality_control(api, world),
            ApiErrorId.CALIBRATION_NOT_VERIFIED.value,
            422,
        )
        A.assert_stage(
            fx.read_order(api, world["order_id"]), C.STAGE_REFINISH_CALIBRATION
        )

    def test_the_hop_succeeds_once_the_re_booked_calibration_passes(self, api):
        """A re-booked calibration that passes clean lets the identical hop through.

        PRD: "That re-book is the cycle in this machine: a record at `FAILED` can be scheduled again, returning it to `SCHEDULED` under exactly the same window, bay-type and capacity rules as the first booking, and the re-scheduling clears `post_scan_dtc_count` and `scan_report_ref` along with setting the new `bay_id` and window."
        PRD: "Into `READY_FOR_QC` from `REFINISH_CALIBRATION`: every procedure record on the order that needs calibration must have reached `PASSED` — no record may still be at `REQUIRED`, `SCHEDULED` or `FAILED` — or the hop is refused with `ERR_CALIBRATION_NOT_VERIFIED`; and **every** procedure record on the order, in every scope, must have `adherence_documented` true, or the hop is refused with `ERR_PROCEDURE_ADHERENCE_MISSING`."
        PRD: "On success every `ACTIVE` booking on the order becomes `COMPLETED`, releasing its `occupied_minutes` from its stall, and the order's `version` increments."
        Design: Difficulty/cross_entity_state_dependency/order_cannot_reach_ready_for_qc_until_the_adas_record_is_passed
        """
        world = _world_with_a_required_adas_calibration(api)
        fx.schedule_calibration(
            api, world["record_id"], world["bay"]["id"], _CAL_START, _CAL_END
        )
        fx.record_calibration_result(
            api, world["record_id"], "FAIL", 3, scan_report_ref="SCAN-CAL-1"
        )

        rebooked = fx.schedule_calibration(
            api, world["record_id"], world["bay"]["id"], _CAL_START, _CAL_END
        )
        assert rebooked["calibration_status"] == "SCHEDULED", rebooked

        passed = fx.record_calibration_result(
            api, world["record_id"], "PASS", 0, scan_report_ref="SCAN-CAL-2"
        )
        assert passed["calibration_status"] == "PASSED", passed

        order = validate_success(_ask_for_quality_control(api, world), 200)
        A.assert_stage(order, C.STAGE_READY_FOR_QC)
        assert (
            fx.read_assignment(api, world["refinish_assignment"]["id"])["status"]
            == "COMPLETED"
        )


def _order_at_parts_staged_with_a_part_on_the_dock(api):
    """A part received and waiting while the car has not yet entered its stall.

    One original-equipment line at 10,000 cents is quoted, price-locked, ordered
    and booked in as `CORRECT`, so its `procurement_status` is `RECEIVED` — the
    exact from-state fitting demands. The order is at `PARTS_STAGED` with a body
    stall booked but not yet occupied.
    """
    world = fx.locked_world(api, order_overrides=dict(_UNDER_THRESHOLD_ORDER))
    vendor = fx.create_vendor(
        api,
        name="Metro OEM Parts",
        part_types_offered=["OEM"],
        discount_pct=0,
        max_qty_per_line=4,
    )
    part = fx.add_parts_line(
        api,
        world["line_ids"][0],
        part_number="OEM-3301",
        part_description="Door shell",
        part_type="OEM",
        list_price_cents=10000,
        qty=1,
    )
    fx.quote_part(api, part["id"], vendor["id"], 10000)
    fx.accept_price(api, part["id"])
    fx.place_parts_order(api, part["id"], "2026-08-05T00:00:00Z")
    fx.advance_stage(api, world["order_id"], C.STAGE_PARTS_STAGED)
    world["part"] = fx.receive_part(api, part["id"], 1, "CORRECT")
    world["part_id"] = part["id"]
    world["vendor"] = vendor
    stall = fx.ensure_stall(api, world, "body_stall", name="Body 5", stall_type="BODY")
    world["repair_assignment"] = fx.book_stall(
        api, world["order_id"], stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200
    )
    return world


class TestFittingAPartWaitsOnTheOwningOrder:
    """The line is ready; the car is not. The parent's stage decides."""

    def test_a_received_part_cannot_be_fitted_while_the_car_is_only_parts_staged(
        self, api
    ):
        """The right from-state on the line is not enough to bolt the part on.

        PRD: "The order's `stage` must be `REPAIR` or `REFINISH_CALIBRATION`, or the request is refused with `ERR_STAGE_PRECONDITION`, and at least one un-returned unit must remain — `received_qty` less `returned_qty` must be 1 or more — or it is refused with `ERR_INVALID_RECEIVE_QUANTITY`."
        PRD: "No side effect of any kind is applied when a check fails."
        Design: Difficulty/cross_entity_state_dependency/install_refused_until_the_owning_order_is_in_repair
        """
        world = _order_at_parts_staged_with_a_part_on_the_dock(api)
        before = fx.read_parts_line(api, world["part_id"])
        A.assert_parts_line_state(before, procurement_status="RECEIVED")

        response = api.install_parts_line(world["part_id"], None, TECHNICIAN_HEADERS)
        validate_error(response, ApiErrorId.STAGE_PRECONDITION.value, 409)

        after = fx.read_parts_line(api, world["part_id"])
        A.assert_parts_line_state(after, procurement_status="RECEIVED")
        A.assert_version(after, before["version"], "parts line")

    def test_the_identical_fitting_call_succeeds_once_the_car_enters_repair(self, api):
        """Nothing about the line changes; the parent moves and the call lands.

        PRD: "Fitting the part to the car moves the line from `RECEIVED` to `INSTALLED`, takes no input, and is a `Technician` act rather than a `PartsManager` one."
        PRD: "Installation increments only the parts line's `version`; the line stays inside the committed input set, because a fitted part is still money the shop has spent."
        PRD: "`parts_committed_cents` is the sum, over the order's parts lines whose `procurement_status` is `ORDERED`, `RECEIVED` or `INSTALLED`, of each line's `unit_extended_cents` multiplied by its `qty` less its `returned_qty`."
        Design: Difficulty/cross_entity_state_dependency/install_refused_until_the_owning_order_is_in_repair
        """
        world = _order_at_parts_staged_with_a_part_on_the_dock(api)
        validate_error(
            api.install_parts_line(world["part_id"], None, TECHNICIAN_HEADERS),
            ApiErrorId.STAGE_PRECONDITION.value,
            409,
        )
        committed_before = fx.read_order(api, world["order_id"])["parts_committed_cents"]
        A.assert_cents(committed_before, 10000, "parts_committed_cents")

        fx.advance_stage(api, world["order_id"], C.STAGE_REPAIR)
        installed = validate_success(
            api.install_parts_line(world["part_id"], None, TECHNICIAN_HEADERS), 200
        )
        A.assert_parts_line_state(installed, procurement_status="INSTALLED")

        order = fx.read_order(api, world["order_id"])
        A.assert_cents(order["parts_committed_cents"], 10000, "parts_committed_cents")
        A.assert_parts_conservation(order)


def _order_awaiting_sign_off_with_two_faults(api):
    """A car at inspection with an unverified sensor and a part still on order.

    Both faults are live at once: an ADAS procedure record added at
    `READY_FOR_QC` needs a static calibration nobody has run, and an
    original-equipment line has been ordered and never booked in. The record's
    adherence paperwork is filed so that the adherence gate cannot answer first.
    """
    world = _world_awaiting_inspection(api)
    world["bay"] = fx.create_bay(
        api, name="Bay A", supported_types=["STATIC"], concurrent_capacity=2
    )
    record = fx.add_procedure_record(
        api,
        world["order_id"],
        procedure_code="ADAS-CAL-1",
        source="OEM_PORTAL",
        operation_scope="ADAS",
        requires_calibration=True,
        calibration_type="STATIC",
    )
    fx.document_adherence(api, record["id"], adherence_doc_ref="DOC-1")
    world["record_id"] = record["id"]

    vendor = fx.create_vendor(
        api,
        name="Metro OEM Parts",
        part_types_offered=["OEM"],
        discount_pct=0,
        max_qty_per_line=4,
    )
    part = fx.add_parts_line(
        api,
        world["line_ids"][0],
        part_number="OEM-1301",
        part_description="Radar bracket",
        part_type="OEM",
        list_price_cents=10000,
        qty=1,
    )
    fx.quote_part(api, part["id"], vendor["id"], 10000)
    fx.accept_price(api, part["id"])
    world["part"] = fx.place_parts_order(api, part["id"], "2026-08-10T00:00:00Z")
    world["part_id"] = part["id"]
    return world


def _file_the_sign_off(api, world):
    """The identical clean inspection, fired before and after the calibration."""
    return api.create_qc_inspection(
        world["order_id"],
        f.qc_inspection_payload(True, 0, scan_report_ref="SCAN-010"),
        QC_INSPECTOR_HEADERS,
    )


class TestSafetyAnswersBeforeTheUninstalledPart:
    """Two faults at one inspection: the sensor is reported, not the loose part."""

    def test_an_unverified_calibration_answers_before_the_part_still_on_order(
        self, api
    ):
        """The sensor nobody proved is the defect the shop is told about.

        PRD: "Every procedure record on the order whose `requires_calibration` is true must have `calibration_status` `PASSED`, or `ERR_CALIBRATION_NOT_VERIFIED`."
        PRD: "An ADAS system that has not been proven to see the road is a safety defect, and the answer must name that defect even when the same request is also short of parts or over budget."
        PRD: "No side effect of any kind is applied when a check fails."
        Design: Difficulty/priority_pair_validation_conflict/qc_calibration_safety_outranks_uninstalled_parts_constraint
        """
        world = _order_awaiting_sign_off_with_two_faults(api)

        validate_error(
            _file_the_sign_off(api, world),
            ApiErrorId.CALIBRATION_NOT_VERIFIED.value,
            422,
        )

        order = fx.read_order(api, world["order_id"])
        A.assert_count(order["qc_inspection_count"], 0, "qc_inspection_count")
        A.assert_stage(order, C.STAGE_READY_FOR_QC)
        rows, meta = fx.page(
            api.list_qc_inspections(world["order_id"], QC_INSPECTOR_HEADERS)
        )
        A.assert_page(meta, total_count=0)
        assert rows == [], rows

    def test_passing_the_calibration_exposes_the_part_still_on_order(self, api):
        """With the sensor verified, the same inspection reports the loose part.

        PRD: "And no parts line on the order may still be at `ORDERED` or `RECEIVED`, or `ERR_PARTS_NOT_INSTALLED`."
        PRD: "Five conditions guard the inspection, and they are the same five whatever the verdict turns out to be."
        Design: Difficulty/priority_pair_validation_conflict/qc_calibration_safety_outranks_uninstalled_parts_constraint
        """
        world = _order_awaiting_sign_off_with_two_faults(api)
        fx.schedule_calibration(
            api, world["record_id"], world["bay"]["id"], _CAL_START, _CAL_END
        )
        passed = fx.record_calibration_result(
            api, world["record_id"], "PASS", 0, scan_report_ref="SCAN-CAL-3"
        )
        assert passed["calibration_status"] == "PASSED", passed

        validate_error(
            _file_the_sign_off(api, world),
            ApiErrorId.PARTS_NOT_INSTALLED.value,
            422,
        )

        order = fx.read_order(api, world["order_id"])
        A.assert_count(order["qc_inspection_count"], 0, "qc_inspection_count")
        A.assert_stage(order, C.STAGE_READY_FOR_QC)
        A.assert_parts_line_state(
            fx.read_parts_line(api, world["part_id"]), procurement_status="ORDERED"
        )
