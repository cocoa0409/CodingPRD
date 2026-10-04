"""Remaining breadth corners: endpoint conditionals, error branches and derived views."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_site_coordinator_headers,
    make_product,
    make_program,
    make_site,
    make_batch,
    register_carton,
    release_batch,
    certify_site,
    open_window,
    setup_entitled_site,
    submit_order,
    anchor_delivered_carton,
    anchor_thawed_carton,
    create_excursion,
    add_ledger_entry,
    make_family,
    make_delivered_second_site,
    create_reservation_payload,
    create_shipper_payload,
    create_logger_reading_payload,
    get_entitlement,
    get_order,
    current_window_version_for_order,
    get_carton,
    get_shipper,
    get_program,
    get_site,
    usable_doses,
)


def _accept(order_id, window_version, cartons=1, deliver_at="2026-09-01T06:00:00Z"):
    return api_client.accept_site_order(
        order_id,
        {"accepted_cartons": cartons, "deliver_at": deliver_at,
         "expected_allocation_window_version": window_version},
        TEST_USERS["distribution_planner_headers"])


def _prepared_dispatch(ctx, site=None, entry_route="DIRECT_ULTRA_COLD",
                       accepted_cartons=2, deliver_at="2026-09-01T06:00:00Z",
                       seal=True):
    """Order accepted, dispatch packed, carton loaded, shipper optionally sealed."""
    site = site or ctx["site"]
    order = submit_order(ctx["entitlement"]["id"], site["id"],
                         requested_cartons=accepted_cartons, requested_doses=0)
    accepted = _accept(order["id"], current_window_version_for_order(order["id"]), accepted_cartons,
                       deliver_at=deliver_at)
    assert accepted.status_code < 400, accepted.text

    dispatch = get_success_data(api_client.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": site["id"],
         "entry_route": entry_route}, TEST_USERS["logistics_operator_headers"]))
    api_client.pack_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])
    shipper = get_success_data(api_client.create_shipper(
        create_shipper_payload(dispatch["id"]), TEST_USERS["logistics_operator_headers"]))
    api_client.attach_carton_to_shipper(shipper["id"], {"carton_id": ctx["carton"]["id"]},
                                 TEST_USERS["logistics_operator_headers"])
    for recorded_at, temp in (("2026-09-01T01:00:00Z", -75), ("2026-09-01T06:05:00Z", -74)):
        api_client.create_logger_reading(
            create_logger_reading_payload(shipper["id"], recorded_at=recorded_at,
                                          temperature_c=temp),
            TEST_USERS["logistics_operator_headers"])
    if seal:
        refreshed = get_success_data(api_client.get_shipper(
            shipper["id"], TEST_USERS["cold_chain_reviewer_headers"]))
        api_client.seal_shipper(refreshed["id"],
                         {"expected_shipper_version": refreshed["version"]},
                         TEST_USERS["logistics_operator_headers"])
    shipper = get_success_data(api_client.get_shipper(
        shipper["id"], TEST_USERS["cold_chain_reviewer_headers"]))
    return order, dispatch, shipper


def test_dispatch_reject_at_dock_leaves_the_cartons_in_transit(api):
    """PRD §3.5: "The order's `payment_status` becomes `DISPUTED`, and the route
    cartons remain `IN_TRANSIT` and are re-consigned to the staging site."

    PRD §3.5: "A `SiteCoordinator` may instead refuse the shipment at the dock, moving
    the dispatch from `IN_TRANSIT` to `REJECTED_AT_DOCK` with a `reason_code`."

    Design: Corner/endpoints/dispatch_reject_at_dock_leaves_the_cartons_in_transit
    """
    ctx = setup_entitled_site()
    # PRD §3.5: a dock refusal is legitimate only when the dock inspection actually
    # failed, so the destination's certificate is made to lapse between the pack
    # instant and the arrival instant.
    certify_site(ctx["site"]["id"], certificate_number="CERT-MI-DOCK",
                 certificate_expires_at="2026-09-01T12:00:00Z")
    order, dispatch, _ = _prepared_dispatch(ctx)
    api.send_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])

    rejected = validate_success(api.reject_at_dock(
        dispatch["id"], {"reason_code": "SITE_NOT_READY"},
        make_site_coordinator_headers(ctx["site"]["id"])), 200)
    assert rejected["status"] == "REJECTED_AT_DOCK"

    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "IN_TRANSIT"
    order_after = get_order(order["id"])
    assert order_after["payment_status"] == "DISPUTED"
    assert order_after["order_status"] == "ACCEPTED"

    site = get_site(ctx["site"]["id"])
    assert site["reported_entry_type"] == "ULTRA_COLD"
    assert site["usable_doses"] == 0


def test_dispatch_requires_an_open_shipping_schedule_slot(api):
    """PRD §3.5: "The logical clock must sit inside a declared shipping day and cutoff
    pair of the program's `shipping_days` and `shipping_cutoff_utc` schedule, or it is
    refused with `ERR_OUTSIDE_SHIPPING_SCHEDULE`."

    PRD §3.1: "`shipping_cutoff_utc`, a time of day in `HH:MM:SS`."

    Design: Corner/endpoints/dispatch_requires_an_open_shipping_schedule_slot
    """
    ctx = setup_entitled_site(window_overrides={"closes_at": "2026-09-05T00:00:00Z"})
    order, dispatch, shipper = _prepared_dispatch(ctx, deliver_at="2026-09-04T06:00:00Z")

    api_client.set_clock({"current_utc": "2026-09-02T15:00:00Z"},
                         TEST_USERS["platform_admin_headers"])
    refused = api.send_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])
    validate_error(refused, "ERR_OUTSIDE_SHIPPING_SCHEDULE", expected_status=422)

    after = get_success_data(api.get_dispatch(
        dispatch["id"], TEST_USERS["logistics_operator_headers"]))
    assert after["status"] == "PACKED"
    assert after["dispatched_at"] is None

    api_client.set_clock({"current_utc": "2026-09-04T13:30:00Z"},
                         TEST_USERS["platform_admin_headers"])
    accepted = validate_success(api.send_dispatch(
        dispatch["id"], TEST_USERS["logistics_operator_headers"]), 200)
    assert accepted["status"] == "IN_TRANSIT"
    assert accepted["dispatched_at"] == "2026-09-04T13:30:00Z"

    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "IN_TRANSIT"
    assert get_shipper(shipper["id"])["packing_status"] == "IN_TRANSIT"


def test_seal_refuses_when_the_dry_ice_payload_is_short(api):
    """PRD §3.4: "The loaded `dry_ice_kg` must be at least `required_dry_ice_kg`, or
    the request is refused with `ERR_DRY_ICE_INSUFFICIENT`; a `logger_serial` must be
    recorded, or it is refused with `ERR_LOGGER_MISSING`; and packing must not have
    lasted longer than the forty-eight-hour limit, measured from `packing_started_at`
    to the completion instant, or it is refused with `ERR_PACKING_EXCEEDED`."
    PRD §3.4: "When any of the three fails the seal does not happen at all: the
    packing status stays `PREPARING` and the endpoint reports `ERR_SHIPPER_HOLD`."

    Design: Corner/errors/seal_refuses_when_the_dry_ice_payload_is_short
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=2, requested_doses=0)
    assert _accept(order["id"], current_window_version_for_order(order["id"]), 2).status_code < 400

    dispatch = get_success_data(api.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": ctx["site"]["id"],
         "entry_route": "DIRECT_ULTRA_COLD"}, TEST_USERS["logistics_operator_headers"]))
    api.pack_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])

    shipper = validate_success(api.create_shipper(
        create_shipper_payload(dispatch["id"], shipper_serial="SH-0002", dry_ice_kg=0.5,
                               logger_serial="LG-0002"),
        TEST_USERS["logistics_operator_headers"]), 201)
    assert shipper["required_dry_ice_kg"] == 0
    assert shipper["dry_ice_deficit_kg"] == 0

    attached = validate_success(api.attach_carton_to_shipper(
        shipper["id"], {"carton_id": ctx["carton"]["id"]},
        TEST_USERS["logistics_operator_headers"]), 200)
    assert attached["required_dry_ice_kg"] == 1
    assert attached["dry_ice_deficit_kg"] == 0.5

    refreshed = get_shipper(shipper["id"])
    res = api.seal_shipper(refreshed["id"],
                           {"expected_shipper_version": refreshed["version"]},
                           TEST_USERS["logistics_operator_headers"])
    validate_error(res, "ERR_SHIPPER_HOLD", expected_status=409)

    after = get_shipper(shipper["id"])
    assert after["packing_status"] == "PREPARING"
    assert after["packing_completed_at"] is None


def test_seal_refuses_a_shipper_with_no_logger(api):
    """PRD §3.4: "A `ColdChainReviewer` may place it on hold by moving it from
    `RECEIVED` to `HELD` with a `hold_reason` drawn from `MISSING_LOGGER`,
    `INSUFFICIENT_DRY_ICE`, `LATE_PACKING`, or `LATE_READING`".

    PRD §3.4: "When any of the three fails the seal does not happen at all: the
    packing status stays `PREPARING` and the endpoint reports `ERR_SHIPPER_HOLD`."

    Design: Corner/errors/seal_refuses_a_shipper_with_no_logger
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=2, requested_doses=0)
    assert _accept(order["id"], current_window_version_for_order(order["id"]), 2).status_code < 400

    dispatch = get_success_data(api.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": ctx["site"]["id"],
         "entry_route": "DIRECT_ULTRA_COLD"}, TEST_USERS["logistics_operator_headers"]))
    api.pack_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])
    # PRD §3.4 makes `logger_serial` one of the shipper payload's declared fields
    # ("a `logger_serial`; it begins in `PREPARING`") and demands it at the SEAL
    # ("a `logger_serial` must be recorded, or it is refused with
    # `ERR_LOGGER_MISSING`"), so the field is omitted here rather than sent as an
    # empty string, which the request-shape gate refuses at priority 32.
    shipper = get_success_data(api.create_shipper(
        create_shipper_payload(dispatch["id"], shipper_serial="SH-0003",
                               logger_serial=None),
        TEST_USERS["logistics_operator_headers"]))
    api.attach_carton_to_shipper(shipper["id"], {"carton_id": ctx["carton"]["id"]},
                                 TEST_USERS["logistics_operator_headers"])
    api.create_logger_reading(
        create_logger_reading_payload(shipper["id"]),
        TEST_USERS["logistics_operator_headers"])

    refreshed = get_shipper(shipper["id"])
    res = api.seal_shipper(refreshed["id"],
                           {"expected_shipper_version": refreshed["version"]},
                           TEST_USERS["logistics_operator_headers"])
    validate_error(res, "ERR_SHIPPER_HOLD", expected_status=409)

    after = get_shipper(shipper["id"])
    assert after["packing_status"] == "PREPARING"
    assert after["hold_reason"] is None
    assert get_success_data(api.get_dispatch(
        dispatch["id"], TEST_USERS["logistics_operator_headers"]))["status"] == "PACKED"


def test_adjudication_requires_every_boundary_slice_to_be_closed(api):
    """PRD §3.8: "It is gated by three checks evaluated in order: the acting user must
    differ from the user who moved the excursion to `UNDER_REVIEW`, otherwise
    `ERR_SEGREGATION_OF_DUTIES`; every dose-affected slice at or below the adjudicated
    temperature boundary must be closed, otherwise `ERR_SLICE_NOT_CLOSED`".

    PRD §3.8: "Closing moves a slice from `IN_REVIEW` to `CLOSED` and its `status` to
    `CERTIFIED`."

    Design: Corner/errors/adjudication_requires_every_boundary_slice_to_be_closed
    """
    ctx = anchor_thawed_carton()
    exc = create_excursion(ctx["carton"]["id"], ctx["site"]["id"], min_temperature_c=-65,
                           first_breach_at="2026-09-01T09:00:00Z",
                           last_breach_at="2026-09-01T11:00:00Z",
                           reported_at="2026-09-01T11:05:00Z")
    api.review_temperature_excursion(exc["id"], TEST_USERS["cold_chain_reviewer_headers"])
    slice_res = api.create_doses_affected_slice(
        exc["id"], {"closure_state": "OPEN", "time_slice_c": -65, "doses_upper_bound": 200},
        TEST_USERS["cold_chain_reviewer_headers"])
    slice_id = validate_success(slice_res, 201)["id"]

    blocked = api.adjudicate_temperature_excursion(
        exc["id"], {"outcome": "NOT_USABLE", "rationale": "Cold breach below the tolerance band."},
        TEST_USERS["medical_science_liaison_headers"])
    validate_error(blocked, "ERR_SLICE_NOT_CLOSED", expected_status=422)

    closed = validate_success(api.close_doses_affected_slice(
        slice_id, {"doses_upper_bound": 200},
        TEST_USERS["medical_science_liaison_headers"]), 200)
    assert closed["closure_state"] == "CLOSED"
    assert closed["status"] == "CERTIFIED"

    adjudicated = validate_success(api.adjudicate_temperature_excursion(
        exc["id"], {"outcome": "NOT_USABLE", "rationale": "Cold breach below the tolerance band."},
        TEST_USERS["medical_science_liaison_headers"]), 200)
    assert adjudicated["review_status"] == "ADJUDICATED"
    assert adjudicated["adjudication_status"] == "NOT_USABLE"
    assert adjudicated["dose_impact_category"] == "DOSE_LEVEL"


def test_a_confirmed_reservation_cannot_be_cancelled(api):
    """PRD §3.7: "Cancelling an `APPROVED` transfer is a `DistributionPlanner` act
    that moves it to `CANCELLED`; it is refused with `ERR_INVALID_REQUEST` when the
    reservation is already `CONFIRMED`".

    PRD §3.7: "On receipt the carton becomes `REFRIGERATED`, a `TRANSFER_OUT` entry is
    written at the origin and a `TRANSFER_IN` entry at the destination, the reservation
    becomes `CONFIRMED`".

    Design: Corner/errors/a_confirmed_reservation_cannot_be_cancelled
    """
    ctx = anchor_thawed_carton()
    dest = make_delivered_second_site(ctx, site_code="MI-RIV-04", capability="REFRIGERATED")

    transfer = get_success_data(api.create_site_transfer(
        {"from_site_id": ctx["site"]["id"], "to_site_id": dest["id"],
         "carton_id": ctx["carton"]["id"], "requested_at": "2026-09-01T09:00:00Z"},
        TEST_USERS["distribution_planner_headers"]))
    api.approve_site_transfer(transfer["id"], TEST_USERS["distribution_planner_headers"])
    api.send_site_transfer(transfer["id"], TEST_USERS["logistics_operator_headers"])
    received = validate_success(api.receive_site_transfer(
        transfer["id"], {"received_at": "2026-09-01T12:00:00Z"},
        make_site_coordinator_headers(dest["id"])), 200)
    assert received["status"] == "RECEIVED"

    res = api.cancel_site_transfer(transfer["id"], TEST_USERS["distribution_planner_headers"])
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "REFRIGERATED"
    reservations = get_success_data(api.list_carton_reservations(
        ctx["carton"]["id"], TEST_USERS["distribution_planner_headers"]))
    assert len(reservations) == 1
    assert reservations[0]["status"] == "CONFIRMED"


def test_rounded_dose_hairpin_slices_and_latencies(api):
    """PRD §3.8: "The accumulated loss percentage sums the caps of the excursion's
    certified slices: a slice boundary at or below minus sixty degrees contributes one
    tenth".

    PRD §3.8: "Under the certified variant the certified loss is the carton's
    `doses_per_carton` multiplied by the accumulated loss percentage."

    Design: Corner/calculations/rounded_dose_hairpin_slices_and_latencies
    """
    ctx = anchor_thawed_carton()
    exc = create_excursion(ctx["carton"]["id"], ctx["site"]["id"], min_temperature_c=-65,
                           first_breach_at="2026-09-01T09:00:00Z",
                           last_breach_at="2026-09-01T11:00:00Z",
                           reported_at="2026-09-01T11:05:00Z")
    api.review_temperature_excursion(exc["id"], TEST_USERS["cold_chain_reviewer_headers"])
    slice_id = validate_success(api.create_doses_affected_slice(
        exc["id"], {"closure_state": "OPEN", "time_slice_c": -65, "doses_upper_bound": 300},
        TEST_USERS["cold_chain_reviewer_headers"]), 201)["id"]
    validate_success(api.close_doses_affected_slice(
        slice_id, {"doses_upper_bound": 300},
        TEST_USERS["medical_science_liaison_headers"]), 200)

    adjudicated = validate_success(api.adjudicate_temperature_excursion(
        exc["id"], {"outcome": "NOT_USABLE",
                    "rationale": "Cold breach beyond the tolerance band for two hours."},
        TEST_USERS["medical_science_liaison_headers"]), 200)
    assert adjudicated["dose_impact_factor"] == 0.1
    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "DESTROYED"

    adjudications = get_success_data(api.list_excursion_adjudications(
        TEST_USERS["regulatory_affairs_headers"],
        params={"temperature_excursion_id": exc["id"]}))
    assert adjudications[0]["certified_lost_doses"] == 117