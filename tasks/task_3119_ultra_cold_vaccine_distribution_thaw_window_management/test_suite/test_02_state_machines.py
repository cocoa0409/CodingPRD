"""State machines: transitions, terminal lockdowns, cycles and independent axes."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    validate_error_is_one_of,
    TEST_USERS,
    make_site_coordinator_headers,
    make_product,
    make_program,
    make_site,
    make_batch,
    register_carton,
    release_batch,
    certify_site,
    setup_entitled_site,
    submit_order,
    accept_order,
    anchor_delivered_carton,
    anchor_thawed_carton,
    setup_adjudicated_excursion,
    create_excursion,
    add_ledger_entry,
    make_family,
    get_carton,
    get_order,
    get_entitlement,
    get_shipper,
    get_excursion,
)


def _ctx_delivered_order():
    """Anchored fixture plus an accepted, delivered 2-carton order."""
    return anchor_delivered_carton()


def test_site_order_cannot_be_submitted_twice(api):
    """PRD §3.3: "Submission moves it from `DRAFT` to `SUBMITTED`"; the order's
    `order_status` is `DRAFT`, `SUBMITTED`, `ACCEPTED`, `PARTIALLY_ACCEPTED`,
    `REJECTED`, or `FULFILLED`.

    PRD §2.9: "The parent's operative state is checked next (`ERR_INVALID_STATE`
    when the entity's `order_status`, `acceptance_status`, `temperature_state`, or
    `packing_status` does not admit the operation".

    Design: Corner/state_machines/site_order_cannot_be_submitted_twice
    """
    ctx = setup_entitled_site()
    headers = make_site_coordinator_headers(ctx["site"]["id"])
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"])
    assert order["order_status"] == "SUBMITTED"
    first_submitted_at = order["submitted_at"]

    res = api.submit_site_order(order["id"], headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    after = get_order(order["id"])
    assert after["submitted_at"] == first_submitted_at
    assert after["version"] == 2


def test_entitlement_cannot_be_reopened_after_the_window_closed_it(api):
    """PRD §3.2: "On close, if the window's entitlement still has `available_cartons`
    above zero, a shipping-window lapse is created for it with reason
    `ACCEPTANCE_WINDOW_CLOSED`, the entitlement's `acceptance_status` becomes
    `LAPSED`".

    PRD §3.3: "The entitlement must still be accepting, meaning its
    `acceptance_status` is `PENDING` or `PARTIALLY_ACCEPTED`, or the request is
    refused with `ERR_ENTITLEMENT_NOT_ACCEPTING`."

    Design: Corner/state_machines/entitlement_cannot_be_reopened_after_the_window_closed_it
    """
    ctx = setup_entitled_site()
    headers = make_site_coordinator_headers(ctx["site"]["id"])
    order = get_success_data(api.create_site_order(
        {
            "allocation_entitlement_id": ctx["entitlement"]["id"],
            "storage_site_id": ctx["site"]["id"],
            "requested_cartons": 2,
            "requested_doses": 0,
        },
        headers))
    assert order["order_status"] == "DRAFT"

    api_client.set_clock({"current_utc": "2026-09-04T00:00:00Z"},
                         TEST_USERS["platform_admin_headers"])
    closed = validate_success(
        api.close_allocation_window(ctx["window"]["id"],
                                    TEST_USERS["distribution_planner_headers"]), 200)
    assert closed["status"] == "CLOSED"

    ent = get_entitlement(ctx["entitlement"]["id"])
    assert ent["acceptance_status"] == "LAPSED"
    assert ent["lapsed_at"] is not None
    assert ent["available_cartons"] == 0

    res = api.submit_site_order(order["id"], headers)
    validate_error(res, "ERR_ENTITLEMENT_NOT_ACCEPTING", expected_status=409)
    assert get_order(order["id"])["order_status"] == "DRAFT"


def test_dispatch_progresses_through_its_pipeline_once(api):
    """PRD §3.5: "Dispatching moves a `PACKED` dispatch to `IN_TRANSIT`"; "Arrival
    is recorded by a `SiteCoordinator` with an `arrived_at` instant and moves the
    dispatch from `IN_TRANSIT` to `DELIVERED`."

    PRD §3.5: "On success `dispatched_at` is stamped with the logical clock".

    Design: Corner/state_machines/dispatch_progresses_through_its_pipeline_once
    """
    ctx = setup_entitled_site()
    site_id = ctx["site"]["id"]
    order = submit_order(ctx["entitlement"]["id"], site_id)
    accept = accept_order(order["id"], ctx["window"]["version"], accepted_cartons=2)
    assert accept.status_code < 400, accept.text

    dispatch = get_success_data(api.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": site_id,
         "entry_route": "DIRECT_ULTRA_COLD"},
        TEST_USERS["logistics_operator_headers"]))
    packed = validate_success(
        api.pack_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"]), 200)
    assert packed["status"] == "PACKED"

    shipper = get_success_data(api.create_shipper(
        {"dispatch_order_id": dispatch["id"], "shipper_serial": "SH-0001",
         "dry_ice_kg": 20, "packing_started_at": "2026-09-01T00:00:00Z",
         "logger_serial": "LG-0001"},
        TEST_USERS["logistics_operator_headers"]))
    api.attach_carton_to_shipper(shipper["id"], {"carton_id": ctx["carton"]["id"]},
                                 TEST_USERS["logistics_operator_headers"])
    for recorded_at, temp in (("2026-09-01T01:00:00Z", -75), ("2026-09-01T06:05:00Z", -74)):
        api.create_logger_reading(
            {"cold_chain_shipper_id": shipper["id"], "recorded_at": recorded_at,
             "temperature_c": temp, "source": "LOGGER"},
            TEST_USERS["logistics_operator_headers"])
    shipper = get_shipper(shipper["id"])
    sealed = validate_success(api.seal_shipper(
        shipper["id"], {"expected_shipper_version": shipper["version"]},
        TEST_USERS["logistics_operator_headers"]), 200)
    assert sealed["packing_status"] == "SEALED"

    in_transit = validate_success(
        api.send_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"]), 200)
    assert in_transit["status"] == "IN_TRANSIT"
    assert in_transit["dispatched_at"] == "2026-09-01T00:00:00Z"
    assert in_transit["eta_at"] is not None

    delivered = validate_success(api.deliver_dispatch(
        dispatch["id"], {"arrived_at": "2026-09-01T06:00:00Z"},
        make_site_coordinator_headers(site_id)), 200)
    assert delivered["status"] == "DELIVERED"

    carton = get_carton(ctx["carton"]["id"])
    assert carton["temperature_state"] == "ULTRA_COLD"
    order_after = get_order(order["id"])
    assert order_after["order_status"] == "FULFILLED"
    assert order_after["payment_status"] == "DUE"

    shipper_after = get_shipper(shipper["id"])
    assert shipper_after["packing_status"] == "RECEIVED"
    assert shipper_after["payload_locked_at"] is not None


def test_reporting_period_submission_is_blocked_by_an_open_adjudication(api):
    """PRD §3.9: "Submitting the period is a `RegulatoryAffairsOfficer` act moving
    it from `OPEN` to `SUBMITTED`, and it is refused while three things remain
    outstanding: any excursion reported inside the period is not adjudicated, which
    surfaces as `ERR_PENDING_ADJUDICATIONS_IN_PERIOD`".

    Design: Corner/state_machines/reporting_period_submission_is_blocked_by_an_open_adjudication
    """
    from test_helpers import make_reporting_period

    ctx = anchor_thawed_carton()
    period = make_reporting_period(ctx["program"]["id"],
                                   period_start="2026-09-01T00:00:00Z",
                                   period_end="2026-09-08T00:00:00Z")
    create_excursion(ctx["carton"]["id"], ctx["site"]["id"],
                     min_temperature_c=-55,
                     first_breach_at="2026-09-01T09:00:00Z",
                     last_breach_at="2026-09-01T10:00:00Z",
                     reported_at="2026-09-01T10:05:00Z")

    res = api.submit_reporting_period(period["id"], TEST_USERS["regulatory_affairs_headers"])
    err = validate_error(res, "ERR_PENDING_ADJUDICATIONS_IN_PERIOD", expected_status=422)
    assert err["error_id"] != "ERR_PENDING_LAPSE_RECONCILIATION"

    after = get_success_data(api.get_reporting_period(
        period["id"], TEST_USERS["regulatory_affairs_headers"]))
    assert after["status"] == "OPEN"
    assert after["report_version"] == 1


def test_inspection_checkpoint_refuses_a_site_with_an_expired_certificate(api):
    """PRD §3.3: "The ordering site must be equipment-certified at the logical
    clock, or it is refused with `ERR_SITE_EQUIPMENT_NOT_CERTIFIED`."

    PRD §2.8: "A site may receive ultra-cold or refrigerated product only while it
    holds a `RECORDED`, unexpired `SiteEquipmentVerification` whose `outcome` is
    `PASSED` covering the equipment class being required."

    Design: Corner/state_machines/inspection_checkpoint_stops_the_door_and_the_asymmetry_leaves_the_doors_apart
    """
    ctx = setup_entitled_site()
    program_id = ctx["program"]["id"]
    expired = make_site(program_id, site_code="MI-RIV-07", site_name="Riverbend Field Unit",
                        equipment_certificate_expires_at="2026-08-31T00:00:00Z",
                        expected_weekly_doses=400)
    certify_site(expired["id"], certificate_number="CERT-MI-0007",
                 certificate_expires_at="2026-08-31T00:00:00Z",
                 verified_at="2026-08-01T00:00:00Z")

    headers = make_site_coordinator_headers(expired["id"])
    order = get_success_data(api.create_site_order(
        {"allocation_entitlement_id": ctx["entitlement"]["id"],
         "storage_site_id": expired["id"], "requested_cartons": 1,
         "requested_doses": 0}, headers))
    submit = api.submit_site_order(order["id"], headers)
    validate_error(submit, "ERR_SITE_EQUIPMENT_NOT_CERTIFIED", expected_status=422)

    assert get_success_data(api.get_storage_site(
        expired["id"], TEST_USERS["distribution_planner_headers"]))["equipment_certified"] is False


def test_carton_puncture_axis_and_custody_axis_move_independently(api):
    """PRD §3.6: "Either way the carton moves to `PUNCTURED`, appends a
    zero-quantity `PUNCTURE` entry, and tightens `current_expires_at` to the earlier
    of its current value and the puncture instant plus `punctured_bud_hours`."

    PRD §3.6: "A carton that is already `PUNCTURED` and whose beyond-use date is
    already the puncture limit is refused with `ERR_ALREADY_PUNCTURED`, and no
    ledger entry is written on that refusal."

    PRD §3.5: "A carton travelling out of ultra-cold keeps its cold state while it
    is in transit: its `thawed_at` stays null".

    Design: Difficulty/non_linear_state_machine/carton_two_independent_axes_with_compound_grade_and_cycle
    """
    ctx = anchor_thawed_carton()
    site_id = ctx["site"]["id"]
    headers = make_site_coordinator_headers(site_id)
    carton_id = ctx["carton"]["id"]

    add_ledger_entry(carton_id, "ADMINISTER", 60, "2026-09-01T09:00:00Z", as_headers=headers)

    # The anchored carton was thawed at 2026-09-01T08:00:00Z, so the logical clock
    # is 08:00 and the puncture limit is 08:00 plus punctured_bud_hours of 6.  The
    # test never declares a puncture instant of its own, and the clock only reaches
    # 09:00 later, on the ADMINISTER entry.
    punctured = validate_success(api.puncture_carton(carton_id, headers), 200)
    assert punctured["temperature_state"] == "PUNCTURED"
    assert punctured["current_expires_at"] == "2026-09-01T14:00:00Z"

    again = api.puncture_carton(carton_id, headers)
    validate_error(again, "ERR_ALREADY_PUNCTURED", expected_status=409)


def test_carton_custody_axis_moves_independently_of_temperature(api):
    """PRD §3.5: "A carton travelling out of ultra-cold keeps its cold state while
    it is in transit: its `thawed_at` stays null and its `current_expires_at` stays
    null, because the batch expiry still governs."

    PRD §3.7: "Dispatching the transfer is a `LogisticsOperator` act moving it from
    `APPROVED` to `DISPATCHED`, and it cannot move at all until the destination has
    rendered an admissibility decision".

    Design: Difficulty/non_linear_state_machine/carton_two_independent_axes_with_compound_grade_and_cycle
    """
    from test_helpers import make_delivered_second_site

    ctx = anchor_delivered_carton()
    # PRD §3.7 gates approval on "The destination's `storage_capability` must admit
    # `dest_required_entry_type`", and a carton that has never left ultra-cold
    # requires ULTRA_COLD at its destination -- a refrigerated-only site may not
    # receive it.  The destination here is therefore ultra-cold capable.
    dest = make_delivered_second_site(ctx, site_code="MI-RIV-04", capability="ULTRA_COLD",
                                      equipment_type="ULTRA_COLD_FREEZER",
                                      expected_weekly_doses=700)
    # Register a second carton on the same batch for the transfer.
    c02 = register_carton(ctx["batch"]["id"], serial="C-02")

    transfer = get_success_data(api.create_site_transfer(
        {"from_site_id": ctx["site"]["id"], "to_site_id": dest["id"],
         "carton_id": c02["id"], "requested_at": "2026-09-01T10:00:00Z"},
        TEST_USERS["distribution_planner_headers"]))
    validate_success(api.approve_site_transfer(
        transfer["id"], TEST_USERS["distribution_planner_headers"]), 200)
    sent = validate_success(api.send_site_transfer(
        transfer["id"], TEST_USERS["logistics_operator_headers"]), 200)
    assert sent["status"] == "DISPATCHED"

    c02_after = get_carton(c02["id"])
    assert c02_after["temperature_state"] == "IN_TRANSIT"
    assert c02_after["thawed_at"] is None


def test_excursion_cyclic_reopen_and_adjudication_supersession(api):
    """PRD §3.8: "acceptance reopens the excursion to `UNDER_REVIEW` with
    `adjudication_status` `PENDING` and `adjudicated_at` cleared, sets
    `quarantine_status` back to `OPEN`, reverses the not-usable write-off with a
    `REVERSE` entry naming the waste entry".

    PRD §3.8: "A second adjudication performed while an appeal is open supersedes
    the first: the acting reviewer must differ both from the first adjudicator and
    from the appealing coordinator, otherwise `ERR_SEGREGATION_OF_DUTIES`, and on
    success the earlier adjudication becomes `SUPERSEDED`".

    Design: Difficulty/non_linear_state_machine/excursion_cyclic_reopen_and_adjudication_revision_loop
    """
    ctx = anchor_thawed_carton()
    site_id = ctx["site"]["id"]
    headers = make_site_coordinator_headers(site_id)

    exc = create_excursion(ctx["carton"]["id"], site_id, min_temperature_c=-55,
                           first_breach_at="2026-09-01T09:00:00Z",
                           last_breach_at="2026-09-01T10:00:00Z",
                           reported_at="2026-09-01T10:05:00Z")
    api.review_temperature_excursion(exc["id"], TEST_USERS["cold_chain_reviewer_headers"])
    # The first adjudication must be USABLE: PRD §3.8 refuses an appeal with
    # `ERR_CARTON_DESTROYED` "when the referenced carton has been destroyed", and a
    # NOT_USABLE outcome destroys it, so an appeal against a not-usable adjudication
    # can never be filed.
    first = get_success_data(api.adjudicate_temperature_excursion(
        exc["id"], {"outcome": "USABLE", "rationale": "Breach stayed inside the refrigerated budget."},
        TEST_USERS["medical_science_liaison_headers"]))
    assert first["adjudication_status"] == "USABLE"

    appeal = get_success_data(api.file_appeal(
        exc["id"],
        {"filed_by_user_id": "coord-lena", "filed_at": "2026-09-01T11:00:00Z"},
        headers))
    reopened = validate_success(api.accept_appeal(
        exc["id"], appeal["id"], TEST_USERS["regulatory_affairs_headers"]), 200)
    assert reopened["review_status"] == "UNDER_REVIEW"
    assert reopened["adjudication_status"] == "PENDING"
    assert reopened["adjudicated_at"] is None

    api.review_temperature_excursion(exc["id"], TEST_USERS["cold_chain_reviewer_headers"])
    second = get_success_data(api.adjudicate_temperature_excursion(
        exc["id"],
        {"outcome": "NOT_USABLE", "rationale": "Second review found the breach outside the budget."},
        TEST_USERS["medical_science_liaison_headers"]))
    assert second["adjudication_status"] == "NOT_USABLE"

    # The first adjudication row is reachable through the adjudication list.
    adjudications = get_success_data(api.list_excursion_adjudications(
        TEST_USERS["regulatory_affairs_headers"],
        params={"temperature_excursion_id": exc["id"]}))
    superseded_rows = [a for a in adjudications if a["status"] == "SUPERSEDED"]
    assert len(superseded_rows) == 1
    assert superseded_rows[0]["outcome"] == "USABLE"

    excursion_after = get_excursion(exc["id"])
    assert excursion_after["current_resolution_trace_id"] is not None
    assert excursion_after["current_resolution_trace_id"] != superseded_rows[0]["id"]
    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "DESTROYED"