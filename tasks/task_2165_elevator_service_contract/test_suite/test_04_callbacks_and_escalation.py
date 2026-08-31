"""Callbacks, entrapment escalation and the contract's service-alert counter."""
from test_helpers import (
    ApiErrorId,
    add_car,
    assert_callback,
    assert_instant_equals,
    read_callback,
    read_car,
    read_contract,
    report_callback,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_callback_optional_fields_take_their_declared_defaults(api):
    """PRD §3.3: "It may optionally carry `passengers_trapped`, a count that defaults
    to 0 and can never be negative, and `out_of_service`, a boolean that defaults to
    **true** and declares whether this call took the car out of service."
    PRD §3.3: "When a callback is reported with `out_of_service` true against a car
    that is currently `IN_SERVICE`, the car's availability dimension moves
    `IN_SERVICE → OUT_OF_SERVICE` in the same operation. That move records
    `unplanned_outage_open_since` at the current logical clock, increments the
    governing contract's `cars_out_of_service_count` by 1, and increments the car's
    `version` by 1 — and, when the count thereby reaches two, escalates the contract
    from `ACTIVE` to `SERVICE_ALERT` and increments the contract's `version` as
    well."
    PRD §2.5: "On startup the clock reads exactly `2026-08-01T00:00:00Z`; before any
    administrator has set it, that is the value it reports, and it never silently
    falls back to the host's real time."

    Design: Corner/entities/callback_optional_fields_take_declared_defaults
    """
    program = setup_program(
        ["CAR-C5"],
        building_name="Corner Five",
        building_address="5 Corner St",
        building_manager_user_id="bm-c5",
        contractor_user_id="sc-c5",
    )
    data = validate_success(
        api.create_callback(
            {"car_id": program.car_id(), "callback_type": "MALFUNCTION"},
            program.manager_headers,
        ),
        201,
    )
    assert_callback(data)
    assert data["passengers_trapped"] == 0
    assert data["out_of_service"] is True
    assert data["status"] == "REPORTED"
    assert_instant_equals(data["reported_at"], "2026-08-01T00:00:00Z", "reported_at")
    assert data["response_minutes"] is None

    car = read_car(program.car_id())
    assert car["availability_state"] == "OUT_OF_SERVICE"

    contract = read_contract(program.contract_id)
    assert contract["cars_out_of_service_count"] == 1
    assert contract["status"] == "ACTIVE", "one car out of service does not escalate"


def test_entrapment_with_zero_passengers_is_a_malformed_request(api):
    """PRD §3.3: "An entrapment by definition has someone inside it, so a
    `callback_type` of `ENTRAPMENT` accompanied by a `passengers_trapped` of 0 is a
    malformed request and is refused with `ERR_VALIDATION`."

    Design: Corner/validations/entrapment_callback_with_zero_passengers_returns_validation
    """
    program = setup_program(
        ["CAR-VB"],
        building_name="Val Eleven",
        building_address="11 Val St",
        building_manager_user_id="bm-vb",
        contractor_user_id="sc-vb",
    )
    validate_error(
        api.create_callback(
            {
                "car_id": program.car_id(),
                "callback_type": "ENTRAPMENT",
                "passengers_trapped": 0,
                "out_of_service": True,
            },
            program.manager_headers,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )

    accepted = validate_success(
        api.create_callback(
            {
                "car_id": program.car_id(),
                "callback_type": "MALFUNCTION",
                "passengers_trapped": 0,
                "out_of_service": True,
            },
            program.manager_headers,
        ),
        201,
    )
    assert accepted["callback_type"] == "MALFUNCTION", (
        "the same passengers_trapped value is legal for a malfunction call"
    )

    rows, meta = validate_paginated(
        api.list_callbacks(program.admin_headers, {"car_id": program.car_id()})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_arriving_at_an_unescalated_entrapment_is_refused(api):
    """PRD §3.3: "An entrapment callback may not: it must first have been escalated
    to the fire department, so `ESCALATED → ON_SITE` is the only path available to
    it, and attempting to arrive at an entrapment still sitting in `REPORTED` is
    refused with `ERR_ENTRAPMENT_REQUIRES_FIRE_DISPATCH`."

    Design: Corner/state_machines/entrapment_arrive_before_fire_dispatch_is_rejected
    """
    program = setup_program(
        ["CAR-S4"],
        building_name="SM Four",
        building_address="4 SM St",
        building_manager_user_id="bm-s4",
        contractor_user_id="sc-s4",
    )
    callback = report_callback(
        program,
        program.car_id(),
        callback_type="ENTRAPMENT",
        passengers_trapped=3,
        out_of_service=True,
    )

    validate_error(
        api.arrive_callback(callback["id"], program.contractor_headers),
        ApiErrorId.ERR_ENTRAPMENT_REQUIRES_FIRE_DISPATCH.value,
    )

    stored = read_callback(callback["id"])
    assert stored["status"] == "REPORTED"
    assert stored["arrived_at"] is None
    assert stored["response_minutes"] is None


def test_fire_dispatch_on_an_unwarranted_callback_is_refused(api):
    """PRD §3.3: "That branch is only available where it is warranted: the callback
    must still be `REPORTED`, and it must either have `callback_type` `ENTRAPMENT`
    or carry a `passengers_trapped` of at least 1. A dispatch recorded on any other
    callback is refused with `ERR_FIRE_DISPATCH_NOT_REQUIRED`."

    Design: Corner/state_machines/fire_dispatch_on_plain_nuisance_callback_is_rejected
    """
    program = setup_program(
        ["CAR-S5"],
        building_name="SM Five",
        building_address="5 SM St",
        building_manager_user_id="bm-s5",
        contractor_user_id="sc-s5",
    )
    callback = report_callback(
        program,
        program.car_id(),
        callback_type="NUISANCE",
        passengers_trapped=0,
        out_of_service=False,
    )

    validate_error(
        api.fire_dispatch_callback(
            callback["id"], {"incident_number": "FD-2026-9999"}, program.dispatcher_headers
        ),
        ApiErrorId.ERR_FIRE_DISPATCH_NOT_REQUIRED.value,
    )

    stored = read_callback(callback["id"])
    assert stored["status"] == "REPORTED"
    assert stored["fire_dispatch_incident_number"] is None
    assert stored["fire_dispatch_requested_at"] is None


def test_clearing_the_last_open_callback_de_escalates_the_contract(api):
    """PRD §3.3: "It also attempts to return the car to service: the car's
    availability dimension moves `OUT_OF_SERVICE → IN_SERVICE`,
    `unplanned_outage_open_since` is cleared back to null, the contract's
    `cars_out_of_service_count` is decremented by 1 and the car's `version` is
    incremented — but only when two conditions hold together."
    PRD §3.3: "When the return to service does happen and it drops the contract's
    out-of-service count to one or fewer, the contract de-escalates
    `SERVICE_ALERT → ACTIVE`."
    PRD §3.3: "`response_minutes` is the number of whole minutes elapsed from
    `reported_at` to `arrived_at`. `sla_minutes` is the allowance that applied to
    this call: for a callback of type `ENTRAPMENT` it is the contract's
    `entrapment_response_minutes`, and for `MALFUNCTION` and `NUISANCE` alike it is
    the contract's `callback_response_minutes`. `sla_breached` is true when
    `response_minutes` is strictly greater than `sla_minutes` and false otherwise —
    arriving in exactly the allotted number of minutes is on time, not late."

    Design: Corner/state_machines/clearing_the_last_callback_returns_car_and_contract_to_normal
    """
    program = setup_program(
        ["CAR-S8A", "CAR-S8B"],
        building_name="SM Eight",
        building_address="8 SM St",
        building_manager_user_id="bm-s8",
        contractor_user_id="sc-s8",
    )
    car_a, car_b = program.car_id(0), program.car_id(1)
    callback_a = report_callback(program, car_a, callback_type="MALFUNCTION", out_of_service=True)
    report_callback(program, car_b, callback_type="MALFUNCTION", out_of_service=True)
    validate_success(api.arrive_callback(callback_a["id"], program.contractor_headers))

    cleared = validate_success(
        api.clear_callback(
            callback_a["id"], program.contractor_headers, {"resolution_note": "relay replaced"}
        )
    )
    assert cleared["status"] == "CLEARED"
    assert_instant_equals(cleared["cleared_at"], "2026-08-01T00:00:00Z", "cleared_at")
    assert cleared["response_minutes"] == 0
    assert cleared["sla_minutes"] == 60
    assert cleared["sla_breached"] is False

    restored = read_car(car_a)
    assert restored["availability_state"] == "IN_SERVICE"
    assert restored["unplanned_outage_open_since"] is None
    assert read_car(car_b)["availability_state"] == "OUT_OF_SERVICE"

    contract = read_contract(program.contract_id)
    assert contract["cars_out_of_service_count"] == 1
    assert contract["status"] == "ACTIVE"


def test_escalation_fires_on_the_exact_second_car_out_of_service(api):
    """PRD §3.1: "Whenever the contract is `ACTIVE` and that count reaches **two or
    more** cars simultaneously out of service, the contract escalates
    `ACTIVE → SERVICE_ALERT` and its `version` is incremented; the threshold is
    inclusive, so exactly two cars is enough to escalate."
    PRD §3.3: "That move records `unplanned_outage_open_since` at the current logical
    clock, increments the governing contract's `cars_out_of_service_count` by 1, and
    increments the car's `version` by 1 — and, when the count thereby reaches two,
    escalates the contract from `ACTIVE` to `SERVICE_ALERT` and increments the
    contract's `version` as well."

    Design: Corner/cross_cutting_complexity_layers/out_of_service_escalation_threshold_fires_at_exactly_two_cars
    """
    program = setup_program(
        ["CAR-CC4A", "CAR-CC4B"],
        building_name="Cc Four",
        building_address="4 Cc St",
        building_manager_user_id="bm-c4x",
        contractor_user_id="sc-c4x",
    )
    car_c = add_car(program, "CAR-CC4C")

    report_callback(program, program.car_id(0), callback_type="MALFUNCTION", out_of_service=True)
    after_first = read_contract(program.contract_id)
    assert after_first["cars_out_of_service_count"] == 1
    assert after_first["status"] == "ACTIVE", "one car out of service must not escalate"

    report_callback(program, program.car_id(1), callback_type="MALFUNCTION", out_of_service=True)
    after_second = read_contract(program.contract_id)
    assert after_second["cars_out_of_service_count"] == 2
    assert after_second["status"] == "SERVICE_ALERT", (
        "the escalation fires on the exact second car"
    )

    assert read_car(car_c["id"])["availability_state"] == "IN_SERVICE"
    assert_instant_equals(
        read_car(program.car_id(0))["unplanned_outage_open_since"],
        "2026-08-01T00:00:00Z",
        "unplanned_outage_open_since",
    )


def test_service_alert_blocks_a_new_downtime_window_until_it_clears(api):
    """PRD §3.1: "Ordinary operational writes remain permitted while the contract is
    either `ACTIVE` or `SERVICE_ALERT`, with one deliberate exception: reserving a
    new downtime window on any car of the contract requires the contract to be
    `ACTIVE`, so while a contract sits in `SERVICE_ALERT` a downtime reservation is
    refused with `ERR_CONTRACT_NOT_ACTIVE`."
    PRD §3.5: "The window is created in `SCHEDULED` with `reschedule_count` 0 and a
    derived `duration_minutes` equal to the number of whole minutes from
    `window_start` to `window_end`. Creating it adds that `duration_minutes` to the
    car's `scheduled_downtime_minutes`, increments the owning project's
    `window_count` by 1 when a `project_id` was supplied, and increments the car's
    `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/service_alert_blocks_new_downtime_windows_on_the_contract
    """
    program = setup_program(
        ["CAR-CC5A", "CAR-CC5B"],
        building_name="Cc Five",
        building_address="5 Cc St",
        building_manager_user_id="bm-c5x",
        contractor_user_id="sc-c5x",
    )
    car_c = add_car(program, "CAR-CC5C")
    callback_a = report_callback(
        program, program.car_id(0), callback_type="MALFUNCTION", out_of_service=True
    )
    report_callback(program, program.car_id(1), callback_type="MALFUNCTION", out_of_service=True)
    validate_success(api.arrive_callback(callback_a["id"], program.contractor_headers))

    window_payload = {
        "car_id": car_c["id"],
        "window_type": "REPAIR",
        "window_start": "2026-09-10T08:00:00Z",
        "window_end": "2026-09-10T12:00:00Z",
    }
    validate_error(
        api.create_downtime_window(window_payload, program.admin_headers),
        ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value,
    )
    assert read_car(car_c["id"])["scheduled_downtime_minutes"] == 0

    validate_success(
        api.clear_callback(
            callback_a["id"], program.contractor_headers, {"resolution_note": "fixed"}
        )
    )
    contract = read_contract(program.contract_id)
    assert contract["cars_out_of_service_count"] == 1
    assert contract["status"] == "ACTIVE"

    window = validate_success(
        api.create_downtime_window(window_payload, program.admin_headers), 201
    )
    assert window["status"] == "SCHEDULED"
    assert window["duration_minutes"] == 240
    assert read_car(car_c["id"])["scheduled_downtime_minutes"] == 240
