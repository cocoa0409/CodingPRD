"""State inspections, minted certificates and the two dimensions of a car."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_state_inspection,
    inspect_with_result,
    issue_and_post_certificate,
    issue_certificate,
    read_callback,
    read_car,
    read_contract,
    read_inspection,
    red_tag_car,
    report_callback,
    set_clock,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_posting_a_certificate_populates_the_car_mirror_fields(api):
    """PRD §3.4: "`certificate_number` is assembled as the literal text `CERT-`, then
    the governing contract's `jurisdiction_code`, then a hyphen, then the car's
    `car_code`, then a hyphen, then the issue date written as an eight-digit
    year-month-day string with no separators — so a car labelled CAR-01 in
    jurisdiction NY-NYC certified on 3 September 2026 receives
    `CERT-NY-NYC-CAR-01-20260903`."
    PRD §3.4: "`certificate_expiry_date` is that issue date advanced by **365
    days**, and expiry is inclusive: the certificate is valid *through*
    `certificate_expiry_date` and only lapses once the clock has moved past it."
    PRD §3.4: "`current_certificate_number` takes the `certificate_number` of the
    inspection on that car whose `certificate_state` is `POSTED` and whose
    `certificate_expiry_date` is the latest; where two posted certificates share the
    same expiry date, the tie is broken by taking the one with the earlier
    `created_at`."

    Design: Corner/entities/car_computed_certificate_fields_track_posted_certificate
    """
    program = setup_program(
        ["CAR-C7"],
        building_name="Corner Seven",
        building_address="7 Corner St",
        building_manager_user_id="bm-c7",
        contractor_user_id="sc-c7",
        term_end_date="2028-12-31",
    )
    issued = issue_certificate(
        program,
        program.car_id(),
        inspection_type="PERIODIC",
        scheduled_date="2026-08-01",
        result="PASS_WITH_DEFICIENCIES",
    )
    assert issued["certificate_number"] == "CERT-NY-NYC-CAR-C7-20260801"

    posted = validate_success(
        api.post_certificate(issued["id"], program.manager_headers)
    )
    assert_state_inspection(posted)
    assert posted["certificate_issued_date"] == "2026-08-01"
    assert posted["certificate_expiry_date"] == "2027-08-01"
    assert posted["certificate_state"] == "POSTED"
    assert posted["posted_by_user_id"] == "bm-c7"

    car = read_car(program.car_id())
    assert car["current_certificate_number"] == "CERT-NY-NYC-CAR-C7-20260801"
    assert car["certificate_expiry_date"] == "2027-08-01"
    assert car["compliance_state"] == "CERTIFIED"


def test_reinspection_pass_lifts_the_red_tag_and_restores_service(api):
    """PRD §3.4: "When a `StateInspector` records a `result` of `PASS` or
    `PASS_WITH_DEFICIENCIES` on an inspection whose `inspection_type` is
    `REINSPECTION` and whose car is currently `RED_TAGGED`, the compliance dimension
    moves `RED_TAGGED → INSPECTION_DUE`, `red_tag_lifted_at` is stamped from the
    logical clock, a fresh certificate is issued on that reinspection exactly as
    described above (`NONE → ISSUED`), and the availability dimension returns
    `OUT_OF_SERVICE → IN_SERVICE` provided no open out-of-service callback remains
    on the car."

    Design: Corner/state_machines/reinspection_pass_lifts_red_tag_and_restores_service
    """
    program = setup_program(
        ["CAR-SA"],
        building_name="SM Ten",
        building_address="10 SM St",
        building_manager_user_id="bm-sa",
        contractor_user_id="sc-sa",
        term_end_date="2028-12-31",
    )
    car_id = program.car_id()
    red_tag_car(program, car_id, scheduled_date="2026-08-01")
    set_clock("2026-08-20T00:00:00Z", program.admin_headers)

    reinspection = inspect_with_result(
        program,
        car_id,
        "PASS",
        inspection_type="REINSPECTION",
        scheduled_date="2026-08-20",
    )
    assert reinspection["status"] == "COMPLETED"
    assert reinspection["certificate_state"] == "ISSUED"
    assert reinspection["certificate_number"] == "CERT-NY-NYC-CAR-SA-20260820"
    assert reinspection["certificate_expiry_date"] == "2027-08-20"

    car = read_car(car_id)
    assert car["compliance_state"] == "INSPECTION_DUE"
    assert car["availability_state"] == "IN_SERVICE"
    assert_instant_equals(
        car["red_tag_lifted_at"], "2026-08-20T00:00:00Z", "red_tag_lifted_at"
    )
    assert read_contract(program.contract_id)["cars_out_of_service_count"] == 0


def test_posting_a_newer_certificate_supersedes_the_previous_one(api):
    """PRD §3.4: "Posting also cleans up behind itself: any other inspection on the
    same car whose `certificate_state` was `POSTED` is driven to `SUPERSEDED`, so a
    car has at most one posted certificate at a time."
    PRD §3.4: "`current_certificate_number` takes the `certificate_number` of the
    inspection on that car whose `certificate_state` is `POSTED` and whose
    `certificate_expiry_date` is the latest; where two posted certificates share the
    same expiry date, the tie is broken by taking the one with the earlier
    `created_at`."

    Design: Corner/state_machines/posting_a_newer_certificate_supersedes_the_previous_posted_one
    """
    program = setup_program(
        ["CAR-SB"],
        building_name="SM Eleven",
        building_address="11 SM St",
        building_manager_user_id="bm-sb",
        contractor_user_id="sc-sb",
        term_end_date="2028-12-31",
    )
    car_id = program.car_id()
    first = issue_and_post_certificate(
        program, car_id, inspection_type="PERIODIC", scheduled_date="2026-08-01"
    )
    set_clock("2026-08-20T00:00:00Z", program.admin_headers)
    second = issue_certificate(
        program,
        car_id,
        inspection_type="FIVE_YEAR_FULL_LOAD",
        scheduled_date="2026-08-20",
    )

    posted = validate_success(
        api.post_certificate(second["id"], program.manager_headers)
    )
    assert posted["certificate_state"] == "POSTED"
    assert read_inspection(first["id"])["certificate_state"] == "SUPERSEDED"

    car = read_car(car_id)
    assert car["current_certificate_number"] == "CERT-NY-NYC-CAR-SB-20260820"
    assert car["certificate_expiry_date"] == "2027-08-20"
    assert car["compliance_state"] == "CERTIFIED"

    rows, meta = validate_paginated(
        api.list_inspections(program.admin_headers, {"car_id": car_id})
    )
    assert meta["total_count"] == 2, f"expected 2 inspection rows, got {meta['total_count']}"
    assert len(rows) == 2


def test_posting_a_certificate_after_its_expiry_date_is_refused(api):
    """PRD §3.4: "Two gates apply, and they report different codes: the inspection's
    `certificate_state` must be exactly `ISSUED`, or the attempt is refused with
    `ERR_CERTIFICATE_NOT_ISSUED`; and the current logical-clock date must be on or
    before that certificate's `certificate_expiry_date`, or the attempt is refused
    with `ERR_CERTIFICATE_EXPIRED`."
    PRD §3.4: "`certificate_expiry_date` is that issue date advanced by **365
    days**, and expiry is inclusive: the certificate is valid *through*
    `certificate_expiry_date` and only lapses once the clock has moved past it."

    Design: Corner/validations/posting_a_certificate_after_its_expiry_date_is_rejected
    """
    program = setup_program(
        ["CAR-V8"],
        building_name="Val Eight",
        building_address="8 Val St",
        building_manager_user_id="bm-v8",
        contractor_user_id="sc-v8",
        term_end_date="2028-12-31",
    )
    inspection = issue_certificate(
        program, program.car_id(), scheduled_date="2026-08-01"
    )
    assert inspection["certificate_expiry_date"] == "2027-08-01"
    set_clock("2027-08-02T00:00:00Z", program.admin_headers)

    validate_error(
        api.post_certificate(inspection["id"], program.manager_headers),
        ApiErrorId.ERR_CERTIFICATE_EXPIRED.value,
    )

    stored = read_inspection(inspection["id"])
    assert stored["certificate_state"] == "ISSUED"
    assert stored["certificate_expiry_date"] == "2027-08-01"

    car = read_car(program.car_id())
    assert car["compliance_state"] == "INSPECTION_DUE"
    assert car["current_certificate_number"] is None


def test_posting_a_certificate_that_was_never_issued_is_refused(api):
    """PRD §3.4: "On a `result` of `FAIL` no certificate is minted,
    `certificate_state` stays at `NONE`, and the four-hop red-tag cascade begins."
    PRD §3.4: "Two gates apply, and they report different codes: the inspection's
    `certificate_state` must be exactly `ISSUED`, or the attempt is refused with
    `ERR_CERTIFICATE_NOT_ISSUED`; and the current logical-clock date must be on or
    before that certificate's `certificate_expiry_date`, or the attempt is refused
    with `ERR_CERTIFICATE_EXPIRED`."

    Design: Corner/validations/posting_a_certificate_that_was_never_issued_is_rejected
    """
    program = setup_program(
        ["CAR-V9"],
        building_name="Val Nine",
        building_address="9 Val St",
        building_manager_user_id="bm-v9",
        contractor_user_id="sc-v9",
        term_end_date="2028-12-31",
    )
    inspection = inspect_with_result(
        program,
        program.car_id(),
        "FAIL",
        scheduled_date="2026-08-01",
        deficiency_codes=["CTRL-77"],
    )

    validate_error(
        api.post_certificate(inspection["id"], program.manager_headers),
        ApiErrorId.ERR_CERTIFICATE_NOT_ISSUED.value,
    )

    assert read_inspection(inspection["id"])["certificate_state"] == "NONE"
    assert read_car(program.car_id())["compliance_state"] == "RED_TAGGED"


def test_a_callback_moves_availability_while_compliance_stays_certified(api):
    """PRD §2.10: "The two dimensions evolve independently, with exactly one guarded
    coupling: driving the compliance dimension to `RED_TAGGED` forces the
    availability dimension from `IN_SERVICE` to `OUT_OF_SERVICE`, and lifting the
    tag returns it."
    PRD §3.3: "When a callback is reported with `out_of_service` true against a car
    that is currently `IN_SERVICE`, the car's availability dimension moves
    `IN_SERVICE → OUT_OF_SERVICE` in the same operation."
    PRD §3.4: "Posting the certificate is the `BuildingManager`'s act and is what
    actually makes a car compliant. It drives the certificate dimension
    `ISSUED → POSTED`, stamps `certificate_posted_at` and `posted_by_user_id`, and
    moves the car's `compliance_state` to `CERTIFIED` from either `INSPECTION_DUE`
    or `CERTIFICATE_EXPIRED`."

    Design: Difficulty/non_linear_state_machine/elevator_car_availability_and_compliance_dimensions_move_independently
    """
    program = setup_program(
        ["CAR-Z1"],
        building_name="Zeta Residences",
        building_address="7 Zeta Ln",
        building_manager_user_id="bm-z",
        contractor_user_id="sc-z",
        term_end_date="2028-12-31",
    )
    car_id = program.car_id()
    inspection = issue_and_post_certificate(program, car_id, scheduled_date="2026-08-01")
    assert inspection["certificate_issued_date"] == "2026-08-01"
    assert inspection["certificate_expiry_date"] == "2027-08-01"
    assert read_car(car_id)["compliance_state"] == "CERTIFIED"

    callback = report_callback(
        program, car_id, callback_type="MALFUNCTION", out_of_service=True
    )
    assert read_callback(callback["id"])["status"] == "REPORTED"

    car = read_car(car_id)
    assert car["availability_state"] == "OUT_OF_SERVICE"
    assert car["compliance_state"] == "CERTIFIED", (
        "an availability change must not disturb the compliance dimension"
    )


def test_certificate_lapse_moves_compliance_while_availability_stays_out_of_service(api):
    """PRD §3.4: "When the epoch sweep advances the logical clock past a car's
    `certificate_expiry_date`, that inspection's `certificate_state` moves
    `POSTED → EXPIRED` and the car's `compliance_state` moves
    `CERTIFIED → CERTIFICATE_EXPIRED`. Note that this changes nothing about the
    car's availability: a car with a lapsed certificate keeps running as far as this
    system is concerned, and only a red tag stops it."
    PRD §2.5: "The response reports the resulting `current_utc` together with five
    counters describing what the move triggered: `missed_visits_marked`,
    `rejected_visits_marked`, `certificates_expired`, `windows_completed` and
    `cars_under_modernization`."

    Design: Difficulty/non_linear_state_machine/elevator_car_availability_and_compliance_dimensions_move_independently
    """
    program = setup_program(
        ["CAR-Z1"],
        building_name="Zeta Residences",
        building_address="7 Zeta Ln",
        building_manager_user_id="bm-z",
        contractor_user_id="sc-z",
        term_end_date="2028-12-31",
    )
    car_id = program.car_id()
    inspection = issue_and_post_certificate(program, car_id, scheduled_date="2026-08-01")
    report_callback(program, car_id, callback_type="MALFUNCTION", out_of_service=True)
    assert read_car(car_id)["availability_state"] == "OUT_OF_SERVICE"

    sweep = validate_success(api.set_clock("2027-08-02T00:00:00Z", program.admin_headers))
    assert sweep["certificates_expired"] == 1, (
        f"expected 1 expired certificate, got {sweep['certificates_expired']}"
    )

    car = read_car(car_id)
    assert car["compliance_state"] == "CERTIFICATE_EXPIRED"
    assert car["availability_state"] == "OUT_OF_SERVICE", (
        "a lapsed certificate changes nothing about availability"
    )

    stored = read_inspection(inspection["id"])
    assert stored["certificate_state"] == "EXPIRED"
    assert stored["status"] == "COMPLETED"
