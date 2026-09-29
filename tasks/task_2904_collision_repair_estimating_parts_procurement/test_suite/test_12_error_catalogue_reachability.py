"""Every refusal the shop can provoke keeps its own name.

A collision repair desk lives on the difference between "that claim number does
not exist" and "that part number does not exist", between a window typed
backwards and a stage spelled wrong, and between a supplier the insurer will not
pay for and a bumper the owner never signed for. This file drives each of those
refusals on purpose and insists the answer names the actual defect: the twelve
absent-row codes stay twelve distinct codes, the three malformed-input codes stay
apart on the same endpoint, insurer parts policy is distinguished from an
inapplicable upgrade, a declined bumper is refused for consent rather than for a
frozen order, receipt and installation quantities are policed separately from
return quantities, and a stall of the wrong type, a stall under maintenance, a
bay of the wrong modality and a booking already released each answer for
themselves. Nothing is written behind any of these refusals.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import NOT_FOUND_RESOLUTION_ORDER
from test_helpers.test_users import (
    ESTIMATOR_HEADERS,
    PARTS_MANAGER_HEADERS,
    QC_INSPECTOR_HEADERS,
    SHOP_ADMIN_HEADERS,
    TECHNICIAN_HEADERS,
)

PROMISED_ETA = "2026-08-05T00:00:00Z"


def _error_id(response, expected_error_id: str) -> str:
    """Validate one refusal and hand back the identifier it reported."""
    return validate_error(response, expected_error_id)["error_id"]


def test_every_absent_row_answers_with_its_own_not_found_code(api):
    """All twelve not-found codes are separately reachable and never collapse.

    PRD: "The relevant not-found error is the one belonging to the leftmost identifier that does not resolve."
    PRD: "A `damage_line_id` that names a finding belonging to a different order, and a `supplement_id` that names a supplement belonging to a different order, are treated as not found."
    Design: Corner/errors/every_declared_not_found_code_is_reachable
    """
    absent = C.ABSENT_UUID
    customer = fx.create_customer(api)
    insurer = fx.create_insurer(api)
    first_order = fx.create_repair_order(api, customer["id"], insurer["id"])
    second_order = fx.create_repair_order(api, customer["id"], insurer["id"])
    finding_on_second = fx.add_finding(api, second_order["id"])
    record = fx.add_procedure_record(
        api,
        first_order["id"],
        requires_calibration=True,
        calibration_type="STATIC",
    )

    reported = []

    # The order identifier in the path resolves first of all.
    reported.append(
        _error_id(
            api.get_repair_order(absent, SHOP_ADMIN_HEADERS),
            "ERR_REPAIR_ORDER_NOT_FOUND",
        )
    )
    # Two of the twelve are reached through a body field rather than a path.
    reported.append(
        _error_id(
            api.create_repair_order(
                f.repair_order_payload(absent, insurer["id"]), SHOP_ADMIN_HEADERS
            ),
            "ERR_CUSTOMER_NOT_FOUND",
        )
    )
    reported.append(
        _error_id(
            api.create_repair_order(
                f.repair_order_payload(customer["id"], absent), SHOP_ADMIN_HEADERS
            ),
            "ERR_INSURER_NOT_FOUND",
        )
    )
    reported.append(
        _error_id(
            api.get_estimate_line(absent, ESTIMATOR_HEADERS),
            "ERR_ESTIMATE_LINE_NOT_FOUND",
        )
    )
    # The cross-order case: the finding exists, but it hangs off the other order.
    reported.append(
        _error_id(
            api.create_estimate_line(
                first_order["id"],
                f.estimate_line_payload(damage_line_id=finding_on_second["id"]),
                ESTIMATOR_HEADERS,
            ),
            "ERR_DAMAGE_LINE_NOT_FOUND",
        )
    )
    reported.append(
        _error_id(
            api.get_supplement(absent, ESTIMATOR_HEADERS),
            "ERR_SUPPLEMENT_NOT_FOUND",
        )
    )
    reported.append(
        _error_id(
            api.get_parts_vendor(absent, PARTS_MANAGER_HEADERS),
            "ERR_PARTS_VENDOR_NOT_FOUND",
        )
    )
    reported.append(
        _error_id(
            api.get_parts_line(absent, PARTS_MANAGER_HEADERS),
            "ERR_PARTS_LINE_NOT_FOUND",
        )
    )
    reported.append(
        _error_id(
            api.get_procedure_record(absent, TECHNICIAN_HEADERS),
            "ERR_PROCEDURE_RECORD_NOT_FOUND",
        )
    )
    # A perfectly well-formed calibration window aimed at a bay that is not there.
    reported.append(
        _error_id(
            api.schedule_calibration(
                record["id"],
                f.calibration_schedule_payload(absent, fx.T0900, fx.T1000),
                TECHNICIAN_HEADERS,
            ),
            "ERR_CALIBRATION_BAY_NOT_FOUND",
        )
    )
    reported.append(
        _error_id(api.get_stall(absent, SHOP_ADMIN_HEADERS), "ERR_STALL_NOT_FOUND")
    )
    reported.append(
        _error_id(
            api.get_stage_assignment(absent, TECHNICIAN_HEADERS),
            "ERR_STAGE_ASSIGNMENT_NOT_FOUND",
        )
    )

    # Twelve probes, twelve distinct identifiers, in the ladder's own order.
    assert tuple(reported) == NOT_FOUND_RESOLUTION_ORDER
    assert len(set(reported)) == 12

    # The absent uuid behaves exactly like the wrong-order finding.
    _error_id(
        api.create_estimate_line(
            first_order["id"],
            f.estimate_line_payload(damage_line_id=absent),
            ESTIMATOR_HEADERS,
        ),
        "ERR_DAMAGE_LINE_NOT_FOUND",
    )


def test_bad_windows_bad_enums_and_broken_bounds_keep_three_separate_codes(api):
    """A zero-length booking window, a misspelt stage and a violated bound differ.

    PRD: "On booking a stall and on scheduling a calibration: `window_end` is strictly after `window_start` and both parse as ISO-8601 instants — otherwise `ERR_INVALID_WINDOW`."
    PRD: "Every enum-typed input holds one of that enum's declared members — otherwise `ERR_INVALID_ENUM_VALUE`."
    PRD: "Request shape: every required input field is present, non-null and of the declared JSON type, and unknown fields are rejected — otherwise `ERR_INVALID_REQUEST`."
    Design: Corner/errors/malformed_windows_enums_and_bounds_are_rejected
    """
    stall = fx.create_stall(api, name="Body L", stall_type="BODY")
    world = fx.locked_world_at(api, C.STAGE_PARTS_STAGED)
    order_id = world["order_id"]

    # A window that parses perfectly and still occupies no time at all.
    _error_id(
        api.create_stage_assignment(
            order_id,
            f.stage_assignment_payload(stall["id"], "REPAIR", fx.T0800, fx.T0800),
            TECHNICIAN_HEADERS,
        ),
        "ERR_INVALID_WINDOW",
    )
    # The reversed pair and the unparsable instant answer identically.
    _error_id(
        api.create_stage_assignment(
            order_id,
            f.stage_assignment_payload(stall["id"], "REPAIR", fx.T1200, fx.T0800),
            TECHNICIAN_HEADERS,
        ),
        "ERR_INVALID_WINDOW",
    )
    _error_id(
        api.create_stage_assignment(
            order_id,
            f.stage_assignment_payload(
                stall["id"], "REPAIR", "2026-08-01 08:00", fx.T1200
            ),
            TECHNICIAN_HEADERS,
        ),
        "ERR_INVALID_WINDOW",
    )

    # An out-of-vocabulary stage, on a window that is beyond reproach.
    _error_id(
        api.create_stage_assignment(
            order_id,
            f.stage_assignment_payload(stall["id"], "PAINTING", fx.T0800, fx.T1200),
            TECHNICIAN_HEADERS,
        ),
        "ERR_INVALID_ENUM_VALUE",
    )
    # The same vocabulary check reaches an enum-valued list filter.
    _error_id(
        api.list_parts_lines(PARTS_MANAGER_HEADERS, {"procurement_status": "SHIPPED"}),
        "ERR_INVALID_ENUM_VALUE",
    )

    # A field the booking endpoint never declared.
    _error_id(
        api.create_stage_assignment(
            order_id,
            dict(
                f.stage_assignment_payload(
                    stall["id"], "REPAIR", fx.T0800, fx.T1200
                ),
                rush=True,
            ),
            TECHNICIAN_HEADERS,
        ),
        "ERR_INVALID_REQUEST",
    )

    # Three numeric bounds, on three different endpoints, one shared code.
    _error_id(
        api.create_estimate_line(
            order_id, f.estimate_line_payload(guide_hours=0), ESTIMATOR_HEADERS
        ),
        "ERR_INVALID_REQUEST",
    )
    _error_id(
        api.create_parts_vendor(
            f.parts_vendor_payload(discount_pct=1.0), SHOP_ADMIN_HEADERS
        ),
        "ERR_INVALID_REQUEST",
    )
    _error_id(
        api.create_qc_inspection(
            order_id, f.qc_inspection_payload(True, -1), QC_INSPECTOR_HEADERS
        ),
        "ERR_INVALID_REQUEST",
    )

    # Nine refusals later the stall has never been occupied for a minute.
    A.assert_count(
        fx.read_stall(api, stall["id"])["booked_minutes"], 0, "booked_minutes"
    )


def test_a_forbidden_channel_and_an_inapplicable_upgrade_answer_differently(api):
    """A reconditioned part the program bars is not the same as a pointless upgrade.

    PRD: "A part type the program forbids outright is refused with `ERR_PART_TYPE_NOT_ALLOWED_BY_INSURER`."
    PRD: "It may only be true on a line whose `part_type` is `OEM`, whose insurer program permits at least one alternate type, and whose vehicle is at least `alternate_parts_min_vehicle_age_years` old."
    PRD: "No side effect of any kind is applied when a check fails."
    Design: Corner/errors/insurer_parts_policy_refusals_are_rejected
    """
    fx.set_clock(api, C.CLOCK_DEFAULT)
    world = fx.blueprinted_world(
        api,
        insurer_overrides={
            "aftermarket_allowed": True,
            "alternate_parts_min_vehicle_age_years": 5,
        },
        order_overrides={"vehicle_model_year": 2024},
    )
    labor_line = fx.add_estimate_line(api, world["order_id"])

    # The program leaves reconditioned parts closed, so such a line never exists.
    _error_id(
        api.create_parts_line(
            labor_line["id"],
            f.parts_line_payload(
                part_number="REM-9051",
                part_description="Reman module",
                part_type="RECONDITIONED",
                list_price_cents=8000,
            ),
            PARTS_MANAGER_HEADERS,
        ),
        "ERR_PART_TYPE_NOT_ALLOWED_BY_INSURER",
    )
    _, meta = fx.page(
        api.list_parts_lines(
            PARTS_MANAGER_HEADERS, {"estimate_line_id": labor_line["id"]}
        )
    )
    A.assert_page(meta, total_count=0)

    # The upgrade flag belongs to original-equipment lines only.
    _error_id(
        api.create_parts_line(
            labor_line["id"],
            f.parts_line_payload(
                part_number="AM-9051A",
                part_type="AFTERMARKET",
                list_price_cents=8000,
                oem_upgrade=True,
            ),
            PARTS_MANAGER_HEADERS,
        ),
        "ERR_OEM_UPGRADE_NOT_APPLICABLE",
    )
    # And a 2024 vehicle on the 2026 clock is younger than the five-year age,
    # so there is no alternate the owner could have declined.
    _error_id(
        api.create_parts_line(
            labor_line["id"],
            f.parts_line_payload(
                part_number="OEM-9051",
                part_type="OEM",
                list_price_cents=8000,
                oem_upgrade=True,
            ),
            PARTS_MANAGER_HEADERS,
        ),
        "ERR_OEM_UPGRADE_NOT_APPLICABLE",
    )

    # The same aftermarket channel without the flag is perfectly acceptable, and
    # lands unsigned, which freezes the whole car.
    accepted = validate_success(
        api.create_parts_line(
            labor_line["id"],
            f.parts_line_payload(
                part_number="AM-9051B",
                part_description="Aftermarket mirror",
                part_type="AFTERMARKET",
                list_price_cents=8000,
            ),
            PARTS_MANAGER_HEADERS,
        ),
        201,
    )
    A.assert_parts_line_state(accepted, authorization_status=C.AUTH_PENDING_CONSENT)
    A.assert_posture(
        fx.read_order(api, world["order_id"]), C.POSTURE_CONSENT_REQUIRED
    )
    _, meta = fx.page(
        api.list_parts_lines(
            PARTS_MANAGER_HEADERS, {"estimate_line_id": labor_line["id"]}
        )
    )
    A.assert_page(meta, total_count=1)


def test_ordering_a_part_the_owner_declined_is_refused_for_consent(api):
    """Only the declined path lets the consent refusal speak on a priced line.

    PRD: "The line's `authorization_status` must be `INSURER_ALLOWED` or `CUSTOMER_CONSENTED`; a `PENDING_CONSENT` or `CUSTOMER_DECLINED` line may never be ordered, and the refusal is `ERR_CUSTOMER_CONSENT_REQUIRED`."
    PRD: "While the posture is anything other than `OPEN` the order is frozen: no stage may advance, no part may be ordered, and the vehicle may not be released."
    PRD: "Every parts line whose `authorization_status` is `PENDING_CONSENT` becomes `CUSTOMER_CONSENTED` when `consent_alternate_parts` is true, and `CUSTOMER_DECLINED` otherwise — which means a `CONSENT` decision carrying `alternate_parts_ok` false has the same effect on those lines as an outright `DECLINE`."
    Design: Corner/errors/ordering_a_declined_part_is_rejected
    """
    fx.set_clock(api, C.CLOCK_DEFAULT)
    vendor = fx.create_vendor(
        api,
        name="Alt Supply Co",
        vendor_type="AFTERMARKET_DISTRIBUTOR",
        part_types_offered=["AFTERMARKET"],
        discount_pct=0,
        max_qty_per_line=5,
    )
    world = fx.locked_world(
        api,
        insurer_overrides={"aftermarket_allowed": True},
        order_overrides={"vehicle_model_year": 2025, "deductible_cents": 25000},
    )
    part = fx.add_parts_line(
        api,
        world["line_ids"][0],
        part_number="AM-9052",
        part_description="Aftermarket mirror",
        part_type="AFTERMARKET",
        list_price_cents=9000,
        qty=1,
        vendor_id=vendor["id"],
    )
    # A one-year-old car is below the program's alternate-parts age and the owner
    # holds no standing preference, so the mirror waits for a signature.
    A.assert_parts_line_state(part, authorization_status=C.AUTH_PENDING_CONSENT)
    fx.quote_part(api, part["id"], vendor["id"], 9000)
    priced = fx.accept_price(api, part["id"])
    A.assert_parts_line_state(
        priced,
        procurement_status="PRICE_LOCKED",
        authorization_status=C.AUTH_PENDING_CONSENT,
    )

    # While the signature is outstanding the frozen order answers first.
    _error_id(
        api.order_parts_line(
            part["id"], f.order_payload(PROMISED_ETA), PARTS_MANAGER_HEADERS
        ),
        "ERR_AUTHORIZATION_POSTURE_BLOCKED",
    )

    # The owner declines, the mirror leaves the money picture, and the order
    # thaws -- which is what finally exposes the consent refusal itself.
    fx.record_consent(api, world["order_id"], world["customer_id"], "DECLINE", False)
    _error_id(
        api.order_parts_line(
            part["id"], f.order_payload(PROMISED_ETA), PARTS_MANAGER_HEADERS
        ),
        "ERR_CUSTOMER_CONSENT_REQUIRED",
    )

    refused = fx.read_parts_line(api, part["id"])
    A.assert_parts_line_state(
        refused,
        procurement_status="PRICE_LOCKED",
        authorization_status=C.AUTH_CUSTOMER_DECLINED,
    )
    A.assert_null(refused["vendor_order_seq"], "vendor_order_seq")
    A.assert_null(refused["promised_eta"], "promised_eta")

    order = fx.read_order(api, world["order_id"])
    assert order["consent_state"] == "DECLINED"
    A.assert_totals(
        order,
        parts_gross_cents=0,
        pre_tax_total_cents=28080,
        customer_pay_cents=25000,
        parts_ordered_gross_cents=0,
    )
    A.assert_posture(order, C.POSTURE_OPEN)


def test_quantities_outside_their_range_are_refused_at_receipt_return_and_fitting(api):
    """Nothing left on the shelf refuses the fitting for quantity, not for state.

    PRD: "The request carries the `received_qty`, which must be greater than zero and no greater than the line's `qty`, or the receipt is refused with `ERR_INVALID_RECEIVE_QUANTITY`; and a `condition`, an enum with exactly three members, `CORRECT`, `INCORRECT` and `DAMAGED`."
    PRD: "The order's `stage` must be `REPAIR` or `REFINISH_CALIBRATION`, or the request is refused with `ERR_STAGE_PRECONDITION`, and at least one un-returned unit must remain — `received_qty` less `returned_qty` must be 1 or more — or it is refused with `ERR_INVALID_RECEIVE_QUANTITY`."
    PRD: "The `return_qty` must be greater than zero and no greater than `received_qty` less `returned_qty`, or the return is refused with `ERR_INVALID_RETURN_QUANTITY`; a line at any other `procurement_status` is refused with `ERR_PARTS_LINE_STATE`."
    Design: Corner/errors/quantity_bounds_on_receipt_return_and_install_are_rejected
    """
    fx.set_clock(api, C.CLOCK_DEFAULT)
    vendor = fx.create_vendor(
        api,
        name="Harbour Honda",
        vendor_type="OEM_DEALER",
        part_types_offered=["OEM"],
        discount_pct=0,
        restocking_fee_pct=0.2,
        max_qty_per_line=5,
    )
    stall = fx.create_stall(api, name="Body M", stall_type="BODY")
    world = fx.locked_world(api, order_overrides={"deductible_cents": 25000})
    order_id = world["order_id"]
    part = fx.add_parts_line(
        api,
        world["line_ids"][0],
        part_number="OEM-9053",
        part_description="Clip set",
        part_type="OEM",
        list_price_cents=30000,
        qty=2,
        vendor_id=vendor["id"],
    )
    fx.quote_part(api, part["id"], vendor["id"], 20000)
    fx.accept_price(api, part["id"])
    fx.place_parts_order(api, part["id"], PROMISED_ETA)

    # Two units were ordered: three cannot arrive and neither can none.
    _error_id(
        api.receive_parts_line(
            part["id"], f.receive_payload(3), PARTS_MANAGER_HEADERS
        ),
        "ERR_INVALID_RECEIVE_QUANTITY",
    )
    _error_id(
        api.receive_parts_line(
            part["id"], f.receive_payload(0), PARTS_MANAGER_HEADERS
        ),
        "ERR_INVALID_RECEIVE_QUANTITY",
    )

    # Put the car in a repair stall so that fitting is stage-legal.
    fx.advance_stage(api, order_id, C.STAGE_PARTS_STAGED)
    fx.book_stall(api, order_id, stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200)
    fx.advance_stage(api, order_id, C.STAGE_REPAIR)

    # One of the two clips turns up, and it goes straight back unused.
    fx.receive_part(api, part["id"], 1)
    _error_id(
        api.return_parts_line(
            part["id"], f.return_payload(2, "UNUSED"), PARTS_MANAGER_HEADERS
        ),
        "ERR_INVALID_RETURN_QUANTITY",
    )
    fx.return_units(api, part["id"], 1, "UNUSED")

    # The line is still perfectly RECEIVED, yet there is no unit left to fit.
    _error_id(
        api.install_parts_line(part["id"], None, TECHNICIAN_HEADERS),
        "ERR_INVALID_RECEIVE_QUANTITY",
    )
    # And nothing un-returned remains to send back either.
    _error_id(
        api.return_parts_line(
            part["id"], f.return_payload(1, "UNUSED"), PARTS_MANAGER_HEADERS
        ),
        "ERR_INVALID_RETURN_QUANTITY",
    )

    line = fx.read_parts_line(api, part["id"])
    A.assert_parts_line_state(line, procurement_status="RECEIVED")
    A.assert_count(line["received_qty"], 1, "received_qty")
    A.assert_count(line["returned_qty"], 1, "returned_qty")
    A.assert_cents(line["restocking_fee_cents"], 4000, "restocking_fee_cents")
    A.assert_cents(line["extended_price_cents"], 20000, "extended_price_cents")

    order = fx.read_order(api, order_id)
    A.assert_totals(
        order,
        parts_ordered_gross_cents=40000,
        parts_committed_cents=20000,
        parts_return_credit_cents=16000,
        parts_restocking_loss_cents=4000,
    )
    A.assert_parts_conservation(order)


def test_a_wrong_stall_a_closed_stall_a_wrong_bay_and_a_spent_booking_each_answer(api):
    """Four resource refusals that a single "stall is busy" check would conflate.

    PRD: "The stall's `stall_type` must fit the stage: a `REPAIR` occupancy needs a `BODY` or `FRAME` stall, and a `REFINISH_CALIBRATION` occupancy needs a `PAINT` stall; a mismatch is refused with `ERR_STALL_TYPE_MISMATCH`."
    PRD: "The stall's `status` must be `AVAILABLE`, and a stall under `MAINTENANCE` is refused with `ERR_STALL_UNAVAILABLE`."
    PRD: "The record's `calibration_type` must appear in the bay's `supported_types`, with one deliberate asymmetry: a record whose type is `BOTH` is satisfied **only** by a bay that itself lists `BOTH`, not by a bay listing `STATIC` and `DYNAMIC` separately; a mismatch is refused with `ERR_BAY_TYPE_UNSUPPORTED`."
    PRD: "Cancellation requires `status` `SCHEDULED`, and a booking that is `ACTIVE`, `COMPLETED` or already `CANCELLED` is refused with `ERR_ASSIGNMENT_NOT_SCHEDULED`."
    Design: Corner/errors/stall_and_bay_resource_refusals_are_rejected
    """
    fx.set_clock(api, C.CLOCK_DEFAULT)
    paint_stall = fx.create_stall(api, name="Paint N", stall_type="PAINT")
    closed_stall = fx.create_stall(
        api, name="Body N-down", stall_type="BODY", status="MAINTENANCE"
    )
    body_stall = fx.create_stall(api, name="Body N", stall_type="BODY")
    static_bay = fx.create_bay(
        api, name="Bay Static", supported_types=["STATIC"], concurrent_capacity=2
    )
    dual_bay = fx.create_bay(
        api,
        name="Bay Dual",
        supported_types=["STATIC", "DYNAMIC"],
        concurrent_capacity=2,
    )
    both_bay = fx.create_bay(
        api, name="Bay Both", supported_types=["BOTH"], concurrent_capacity=2
    )
    world = fx.locked_world_at(
        api,
        C.STAGE_PARTS_STAGED,
        procedures=[
            {
                "procedure_code": "RADAR-AIM",
                "source": "OEM_PORTAL",
                "operation_scope": "ADAS",
                "requires_calibration": True,
                "calibration_type": "DYNAMIC",
            },
            {
                "procedure_code": "CAM-AIM",
                "source": "OEM_PORTAL",
                "operation_scope": "ADAS",
                "requires_calibration": True,
                "calibration_type": "BOTH",
            },
        ],
    )
    order_id = world["order_id"]
    dynamic_record, both_record = world["procedure_records"]

    # A paint booth cannot host a repair occupancy.
    _error_id(
        api.create_stage_assignment(
            order_id,
            f.stage_assignment_payload(
                paint_stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200
            ),
            TECHNICIAN_HEADERS,
        ),
        "ERR_STALL_TYPE_MISMATCH",
    )
    A.assert_count(
        fx.read_stall(api, paint_stall["id"])["booked_minutes"], 0, "booked_minutes"
    )
    # The type fits here, but the stall has been withdrawn for maintenance.
    _error_id(
        api.create_stage_assignment(
            order_id,
            f.stage_assignment_payload(
                closed_stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200
            ),
            TECHNICIAN_HEADERS,
        ),
        "ERR_STALL_UNAVAILABLE",
    )
    A.assert_count(
        fx.read_stall(api, closed_stall["id"])["booked_minutes"], 0, "booked_minutes"
    )

    # A dynamic aim needs a bay that lists DYNAMIC.
    _error_id(
        api.schedule_calibration(
            dynamic_record["id"],
            f.calibration_schedule_payload(static_bay["id"], fx.T0900, fx.T1000),
            TECHNICIAN_HEADERS,
        ),
        "ERR_BAY_TYPE_UNSUPPORTED",
    )
    booked = fx.schedule_calibration(
        api, dynamic_record["id"], dual_bay["id"], fx.T0900, fx.T1000
    )
    assert booked["calibration_status"] == "SCHEDULED"

    # A BOTH record is satisfied only by a bay that itself carries BOTH: the
    # static bay and the pair of separate entries are equally unacceptable.
    _error_id(
        api.schedule_calibration(
            both_record["id"],
            f.calibration_schedule_payload(static_bay["id"], fx.T0900, fx.T1000),
            TECHNICIAN_HEADERS,
        ),
        "ERR_BAY_TYPE_UNSUPPORTED",
    )
    _error_id(
        api.schedule_calibration(
            both_record["id"],
            f.calibration_schedule_payload(dual_bay["id"], fx.T0900, fx.T1000),
            TECHNICIAN_HEADERS,
        ),
        "ERR_BAY_TYPE_UNSUPPORTED",
    )
    both_booked = fx.schedule_calibration(
        api, both_record["id"], both_bay["id"], fx.T0900, fx.T1000
    )
    assert both_booked["calibration_status"] == "SCHEDULED"

    # A healthy body stall books, releases on cancellation, and refuses a
    # second cancellation because the booking is no longer scheduled.
    assignment = fx.book_stall(
        api, order_id, body_stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200
    )
    A.assert_count(assignment["occupied_minutes"], 240, "occupied_minutes")
    A.assert_count(
        fx.read_stall(api, body_stall["id"])["booked_minutes"], 240, "booked_minutes"
    )
    cancelled = fx.cancel_assignment(api, assignment["id"])
    assert cancelled["status"] == "CANCELLED"
    A.assert_count(
        fx.read_stall(api, body_stall["id"])["booked_minutes"], 0, "booked_minutes"
    )
    _error_id(
        api.cancel_stage_assignment(assignment["id"], None, TECHNICIAN_HEADERS),
        "ERR_ASSIGNMENT_NOT_SCHEDULED",
    )
