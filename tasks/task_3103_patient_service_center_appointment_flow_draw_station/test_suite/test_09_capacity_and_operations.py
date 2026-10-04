"""Capacity, termination cascades, listing boundaries and the operations checkpoint."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, api_client, INTAKE,
    TEST_USERS, ApiErrorId, make_patient_headers,
)
from test_helpers.fixtures import (
    setup_eligible_order, setup_center_and_plan, new_center, new_patient,
    new_order, resolve_insurance, book, check_in, call_patient, get_order,
    new_courier_run, new_phlebotomist, set_clock, run_ops, new_tube_requirement,
    setup_windowed_visit, add_minutes,
)
from test_helpers.factories import create_specimen_payload


def test_an_adjacent_booking_is_accepted_while_the_identical_cell_is_refused(api):
    """PRD §2.9: "Adjacent intervals are accepted. Two occupancies that merely
    touch at a boundary do not collide; only a genuine overlap, or an exact
    duplicate interval, is a collision."
    PRD §2.9: "Two trips to the same station must not occupy the identical grid
    cell; an equal `[start, start + slot_span * slot_minutes)` interval is
    rejected with `ERR_SLOT_ALREADY_TAKEN`."

    Design: Difficulty/resource_temporal_overlap/appointment_interval_adjacency_accepted_duplicate_rejected
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center(station_count=4)
    plan_id = api_client.seed_reference(TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    orders = []
    for npi in ("1700111224", "1700111225", "1700111226"):
        patient = new_patient()
        order = new_order(center["id"], patient["id"], plan_id,
                          ordering_provider_npi=npi)
        orders.append(resolve_insurance(order["id"]))

    first = validate_success(api_client.create_appointment({
        "service_center_id": center["id"], "test_order_id": orders[0]["id"],
        "scheduled_start_utc": "2026-09-01T14:00:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": orders[0]["version"],
    }, INTAKE), 201)
    adjacent = validate_success(api_client.create_appointment({
        "service_center_id": center["id"], "test_order_id": orders[1]["id"],
        "scheduled_start_utc": "2026-09-01T14:15:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": orders[1]["version"],
    }, INTAKE), 201)
    assert adjacent["scheduled_start_utc"] == "2026-09-01T14:15:00.000Z"

    duplicate = api_client.create_appointment({
        "service_center_id": center["id"], "test_order_id": orders[2]["id"],
        "scheduled_start_utc": "2026-09-01T14:00:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": orders[2]["version"],
    }, INTAKE)
    validate_error(duplicate, ApiErrorId.ERR_SLOT_ALREADY_TAKEN.value)

    listed = api_client.list_appointments(
        INTAKE, params={"service_center_id": center["id"]}).json()["data"]
    assert len(listed) == 2
    assert {first["id"], adjacent["id"]} == {row["id"] for row in listed}


def test_the_booking_that_would_cross_the_station_minute_aggregate_is_refused(api):
    """PRD §2.9: "The total booked station-minutes at a center, counted from the
    logical clock forward and within the current operating day, may not exceed
    the product of `station_count` and `slot_minutes` for that day."
    PRD §2.9: "Exceeding it is rejected with `ERR_STATION_CAPACITY_EXCEEDED`
    (HTTP 409)."

    Design: Corner/validations/aggregate_station_capacity_rejects_the_request_that_would_exceed_it
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center(name="Tiny Draw Station", station_count=1, slot_minutes=15)
    plan_id = api_client.seed_reference(TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    orders = []
    for npi in ("1700111226", "1700111227"):
        patient = new_patient()
        order = new_order(center["id"], patient["id"], plan_id,
                          ordering_provider_npi=npi)
        orders.append(resolve_insurance(order["id"]))

    first = validate_success(api_client.create_appointment({
        "service_center_id": center["id"], "test_order_id": orders[0]["id"],
        "scheduled_start_utc": "2026-09-01T14:00:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": orders[0]["version"],
    }, INTAKE), 201)
    assert first["draw_state"] == "SCHEDULED"

    second = api_client.create_appointment({
        "service_center_id": center["id"], "test_order_id": orders[1]["id"],
        "scheduled_start_utc": "2026-09-01T14:15:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": orders[1]["version"],
    }, INTAKE)
    validate_error(second, ApiErrorId.ERR_STATION_CAPACITY_EXCEEDED.value)

    listed = api_client.list_appointments(
        INTAKE, params={"service_center_id": center["id"]}).json()["data"]
    assert len(listed) == 1


def test_a_booking_beyond_the_one_week_horizon_is_refused(api):
    """PRD §2.9: "A booking's scheduled start must also lie in the future
    relative to the logical clock and no further out than
    `TIME.max_future_booking_minutes`, which is 10080 minutes — one week."
    PRD §2.9: "A start beyond that horizon is rejected with
    `ERR_FUTURE_APPOINTMENT_TOO_FAR` (HTTP 422)."

    Design: Corner/endpoints/a_booking_past_the_future_horizon_is_rejected
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center()
    plan_id = api_client.seed_reference(TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    horizon = add_minutes("2026-09-01T13:00:00Z", 10080)
    assert horizon == "2026-09-08T13:00:00Z"

    edge_patient = new_patient()
    edge_order = resolve_insurance(new_order(center["id"], edge_patient["id"], plan_id)["id"])
    edge = validate_success(api_client.create_appointment({
        "service_center_id": center["id"], "test_order_id": edge_order["id"],
        "scheduled_start_utc": horizon, "slot_span": 1, "source": "BOOKED",
        "expected_test_order_version": edge_order["version"],
    }, INTAKE), 201)
    assert edge["scheduled_start_utc"] == horizon.replace("Z", ".000Z")

    far_patient = new_patient()
    far_order = resolve_insurance(new_order(center["id"], far_patient["id"], plan_id,
                                            ordering_provider_npi="1700111231")["id"])
    beyond = api_client.create_appointment({
        "service_center_id": center["id"], "test_order_id": far_order["id"],
        "scheduled_start_utc": add_minutes(horizon, 1), "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": far_order["version"],
    }, INTAKE)
    validate_error(beyond, ApiErrorId.ERR_FUTURE_APPOINTMENT_TOO_FAR.value)


def test_terminating_a_plan_reconciles_every_eligible_order_on_it(api):
    """PRD §2.7: "Terminating a plan cascades: every order referencing it whose
    eligibility is currently `ELIGIBLE` is recomputed to `EXPIRED`, its
    preliminary copay and coinsurance components are zeroed, and each affected
    order's `version` advances."

    Design: Corner/cross_cutting_complexity_layers/a_terminated_plan_reconciles_every_eligible_order_on_it
    """
    data = setup_eligible_order()
    center, plan_id = data["center"], data["plan_id"]
    first = data["order"]
    second_patient = new_patient(full_name="Bo Alvarez",
                                 birth_date="1988-01-11T00:00:00Z")
    second = resolve_insurance(new_order(center["id"], second_patient["id"], plan_id,
                                         ordering_provider_npi="1700111223")["id"])
    assert second["insurance_status"] == "ELIGIBLE"

    terminated = validate_success(api_client.patch_insurance_plan(
        plan_id, {"status": "TERMINATED"}, INTAKE), 200)
    assert terminated["status"] == "TERMINATED"

    rows = api_client.list_test_orders(
        INTAKE, params={"insurance_plan_id": plan_id}).json()["data"]
    assert len(rows) == 2
    for row in rows:
        assert row["insurance_status"] == "EXPIRED"
        assert row["est_copay_cents"] == 0
        assert row["est_coinsurance_cents"] == 0
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_eligibility_is_resolved_from_the_plan_row_not_from_the_client(api):
    """PRD §3.2: "Resolving eligibility examines the plan's status. When the plan
    is `ACTIVE`, the order's `insurance_status` becomes `ELIGIBLE`. When the plan
    is `TERMINATED`, it becomes `EXPIRED`."

    Design: Corner/validations/cross_entity_eligibility_check_reads_the_plan_not_the_client
    """
    data = setup_center_and_plan()
    center, plan_id = data
    patient = new_patient()
    order = new_order(center["id"], patient["id"], plan_id)

    validate_success(api_client.patch_insurance_plan(
        plan_id, {"status": "TERMINATED"}, INTAKE), 200)

    resolved = validate_success(api_client.insurance_resolve(order["id"], INTAKE), 200)
    assert resolved["insurance_status"] == "EXPIRED"
    assert resolved["est_copay_cents"] == 0
    assert resolved["est_coinsurance_cents"] == 0


def test_patients_listing_paginates_and_counts_the_whole_set(api):
    """PRD §2.3: "`limit` caps how many items a single page may return; when
    omitted it defaults to 10, and any supplied value must fall between a minimum
    of 1 and a maximum of 100. `offset` states how many items to skip from the
    front of the result set and defaults to 0."
    PRD §2.3: "Every paginated list response repeats `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope"

    Design: Corner/entities/patients_list_paginates_and_reports_total_count_and_has_more
    """
    for i, (name, birth) in enumerate([
        ("Ada Nguyen", "1990-04-02T00:00:00Z"),
        ("Bo Alvarez", "1988-01-11T00:00:00Z"),
        ("Cy Ortiz", "1985-07-19T00:00:00Z"),
    ]):
        new_patient(full_name=name, birth_date=birth)

    page, meta = validate_paginated(
        api_client.list_patients(INTAKE, params={"limit": 2, "offset": 0}))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    tail, tail_meta = validate_paginated(
        api_client.list_patients(INTAKE, params={"limit": 2, "offset": 2}))
    assert len(tail) == 1
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False

    default_page, default_meta = validate_paginated(api_client.list_patients(INTAKE))
    assert len(default_page) == 3
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0


def test_run_ops_is_not_idempotent_and_advances_the_epoch_counter(api):
    """PRD §3.9: "It advances the center's `ops_run_index` by one, the counter
    that marks how many epochs the center has been through."
    PRD §3.9: "the field is set to fifteen minutes multiplied by the number of
    on-duty phlebotomists"

    Design: Corner/endpoints/run_ops_is_not_idempotent_and_advances_the_epoch_counter
    """
    center = new_center()
    new_phlebotomist(center["id"], credential="RN", full_name="Hana Reed")
    new_phlebotomist(center["id"], credential="PBT", full_name="Omar Vela")

    first = run_ops(center["id"])
    second = run_ops(center["id"])
    assert first["ops_run_index"] == 1
    assert second["ops_run_index"] == 2
    assert first["staffed_minutes_available"] == second["staffed_minutes_available"] == 30
    assert second["version"] > center["version"]


def test_a_center_listing_never_exposes_another_centers_courier_runs(api):
    """PRD §3.6: "A `LabLiaison` plans a courier run with `service_center_id`, a
    `direction` of `OUTBOUND` or `INBOUND`, and a `dispatch_utc`."
    PRD §4: "GET | `/psc/courier-runs/{courierRunId}` | Read one courier run |
    LabLiaison, IntakeCoordinator, LabSystem"

    Design: Corner/cross_cutting_complexity_layers/a_center_listing_never_exposes_another_centers_courier_runs
    """
    set_clock("2026-09-01T13:00:00Z")
    first_center = new_center()
    second_center = new_center(name="Borealis Draw Station")
    headers = TEST_USERS["lab_liaison_headers"]
    first_run = new_courier_run(first_center["id"], "2026-09-01T16:00:00Z")
    second_run = new_courier_run(second_center["id"], "2026-09-01T17:00:00Z")

    left = api_client.list_courier_runs(
        headers, params={"service_center_id": first_center["id"]}).json()["data"]
    right = api_client.list_courier_runs(
        headers, params={"service_center_id": second_center["id"]}).json()["data"]
    assert [row["id"] for row in left] == [first_run["id"]]
    assert [row["id"] for row in right] == [second_run["id"]]
    assert left[0]["service_center_id"] == first_center["id"]
    assert right[0]["service_center_id"] == second_center["id"]


def test_the_commit_interval_is_half_open_so_only_the_inside_run_is_chosen(api):
    """PRD §3.6: "The selector then fixes a commit interval that opens at
    `checkin_utc` plus `COURIER.commit_lead_minutes` (1080 minutes) and runs for
    exactly 60 more minutes; this interval is half-open, and the scheduled start
    lies inside it, so a start exactly equal to the interval's opening is
    included while a start exactly equal to the window's closing edge is not."

    Design: Corner/calculations/courier_commit_interval_is_half_open_at_its_upper_edge
    """
    data = setup_windowed_visit()
    headers = TEST_USERS["lab_liaison_headers"]
    inside = new_courier_run(data["center"]["id"], "2026-09-02T06:45:00Z")
    outside = new_courier_run(data["center"]["id"], "2026-09-02T08:00:00Z")

    response = api_client.list_eligible_courier_runs(headers, specimen_id=data["specimen"]["id"])
    assert response.status_code == 200
    rows = response.json()["data"]
    ids = [row["id"] for row in rows]
    assert inside["id"] in ids
    assert outside["id"] not in ids
    assert inside["cutoff_utc"] == "2026-09-02T06:30:00.000Z"