"""Hub and package resource shape: creation defaults, round-trips, and required fields."""
import pytest

from test_helpers import (
    confirm_list,
    CLOCK_START,
    TEST_USERS as H,
    api_client as api,
    assert_hub,
    assert_package,
    confirm,
    create_aircraft,
    create_bank,
    create_hub,
    create_lane,
    create_package,
    create_shift,
    depart_and_land,
    failed_error_id,
    get_package,
    list_packages,
    reset_clock,
    set_clock,
    setup_bare_hub,
)


def test_a_new_hub_carries_no_client_supplied_derived_field():
    """PRD §3.4: "The declaration sets the mode true and, through the posture computation
    of §2.5, forces posture to `LOCKDOWN` regardless of volume."
    PRD §2.4: "It additionally carries an `ops_run_index` counter that begins at zero and
    advances by exactly one on every operations checkpoint."

    Design: Corner/entities/hub_create_returns_every_declared_field_and_starts_open
    """
    set_clock(CLOCK_START)
    response = api.create_hub(
        {"iata_code": "SDF", "name": "Worldport Louisville",
         "sort_window_open_minutes": 1380, "sort_window_close_minutes": 1560},
        H["hub_ops_manager_headers"])
    data = confirm(response, 201)
    assert_hub(data)
    assert data["iata_code"] == "SDF"
    assert data["name"] == "Worldport Louisville"
    assert data["posture"] == "OPEN"
    assert data["contingency_mode"] is False
    assert data["ops_run_index"] == 0
    assert data["live_planned_package_total"] == 0
    assert data["alternate_hub_id"] is None
    assert data["version"] >= 1, "a fresh resource carries a version counter"
    assert response.json()["response_type"] == "object"


def test_every_declared_package_field_round_trips_through_the_read():
    """PRD §3.1: "On creation the package stands at `NOT_INDUCTED` on the induction dimension,
    `UNSORTED` on the sort dimension, `COMMITTED` on the commitment dimension, and
    `NORMAL` on the handling dimension, and the system computes its
    `commitment_cutoff_minutes` from the service level and the hub's window close
    — `NEXT_DAY_AIR` is cut off exactly at the hub's `sort_window_close_minutes`,
    `SECOND_DAY_AIR` one full day later at that close plus 1440, and `GROUND` two
    days later at that close plus 2880."

    Design: Corner/entities/package_get_round_trips_all_four_state_planes
    """
    night = setup_bare_hub()
    set_clock("2026-09-01T23:20:00Z")
    lane = create_lane(night["hub_id"])
    bank = create_bank(night["hub_id"])
    aircraft = create_aircraft(bank["id"])
    create_shift(night["hub_id"])
    depart_and_land(aircraft["id"], 60000)
    confirm(api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"]))
    confirm(api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"]))
    confirm(api.complete_aircraft_unload(aircraft["id"], {"unload_completed_minutes": 1401},
                                         H["sort_supervisor_headers"]))
    package = create_package(night["hub_id"], aircraft["id"], tracking_number="1Z-RT-0001",
                             planned_weight_grams=30000, dimension_weight_grams=30000)

    read = confirm(api.get_package(package["id"], H["sort_operator_headers"]))
    assert_package(read)
    assert read["induction_status"] == "NOT_INDUCTED"
    assert read["sort_status"] == "UNSORTED"
    assert read["commitment_status"] == "COMMITTED"
    assert read["handling_status"] == "NORMAL"
    assert read["handling_posture"] == "STANDARD"
    assert read["commitment_posture"] == "COMMITTED_OK"
    assert read["commitment_cutoff_minutes"] == 1560
    assert read["last_sort_minutes"] is None
    assert read["rated_weight_grams"] is None
    assert read["dimension_weight_grams"] == 30000
    assert read["assigned_lane_id"] is None
    assert read["staged_feeder_id"] is None
    assert read["buildup_id"] is None
    assert lane["lane_code"] == "P-01"


def test_a_package_list_pages_and_counts_the_whole_filtered_set():
    """PRD §2.3: "List endpoints accept a `limit` query parameter giving the maximum
    number of items to return; it defaults to 10, may not be smaller than 1, and may not
    exceed 100."

    Design: Corner/entities/packages_list_paginates_and_filters_across_four_state_planes
    """
    night = setup_bare_hub()
    set_clock("2026-09-01T23:20:00Z")
    lane = create_lane(night["hub_id"])
    bank = create_bank(night["hub_id"])
    aircraft = create_aircraft(bank["id"])
    create_shift(night["hub_id"])
    depart_and_land(aircraft["id"], 60000)
    confirm(api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"]))
    confirm(api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"]))
    confirm(api.complete_aircraft_unload(aircraft["id"], {"unload_completed_minutes": 1401},
                                         H["sort_supervisor_headers"]))

    first = create_package(night["hub_id"], aircraft["id"], tracking_number="1Z-LS-0001",
                           planned_weight_grams=20000, dimension_weight_grams=20000)
    create_package(night["hub_id"], aircraft["id"], tracking_number="1Z-LS-0002",
                   destination_hub_code="ORD", service_level="SECOND_DAY_AIR",
                   planned_weight_grams=20000, dimension_weight_grams=20000)
    create_package(night["hub_id"], aircraft["id"], tracking_number="1Z-LS-0003",
                   destination_hub_code="SEA", service_level="GROUND",
                   planned_weight_grams=20000, dimension_weight_grams=20000)
    from test_helpers import induct, primary_sort
    induct(first["id"])
    primary_sort(first["id"], lane["id"])

    page_one, meta_one = confirm_list(api.list_packages(H["sort_supervisor_headers"],
                                                   {"hub_id": night["hub_id"],
                                                    "limit": 2, "offset": 0}))
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True


def test_the_second_page_and_each_plane_filter_narrow_the_set_independently():
    """PRD §2.3: "Every paginated list response carries four pagination fields in the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "Unless a more specific ordering rule is stated for a particular resource,
    list endpoints return resources sorted by their creation timestamp in
    ascending order, so the oldest record is first."

    Design: Corner/entities/packages_list_paginates_and_filters_across_four_state_planes
    """
    night = setup_bare_hub()
    set_clock("2026-09-01T23:20:00Z")
    lane = create_lane(night["hub_id"])
    bank = create_bank(night["hub_id"])
    aircraft = create_aircraft(bank["id"])
    create_shift(night["hub_id"])
    depart_and_land(aircraft["id"], 60000)
    confirm(api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"]))
    confirm(api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"]))
    confirm(api.complete_aircraft_unload(aircraft["id"], {"unload_completed_minutes": 1401},
                                         H["sort_supervisor_headers"]))
    first = create_package(night["hub_id"], aircraft["id"], tracking_number="1Z-LS-0011",
                           planned_weight_grams=20000, dimension_weight_grams=20000)
    second = create_package(night["hub_id"], aircraft["id"], tracking_number="1Z-LS-0012",
                            destination_hub_code="ORD", service_level="SECOND_DAY_AIR",
                            planned_weight_grams=20000, dimension_weight_grams=20000)
    create_package(night["hub_id"], aircraft["id"], tracking_number="1Z-LS-0013",
                   destination_hub_code="SEA", service_level="GROUND",
                   planned_weight_grams=20000, dimension_weight_grams=20000)
    from test_helpers import induct, primary_sort
    induct(first["id"])
    induct(second["id"])
    primary_sort(first["id"], lane["id"])

    page_two, meta_two = confirm_list(api.list_packages(H["sort_supervisor_headers"],
                                                   {"hub_id": night["hub_id"],
                                                    "limit": 2, "offset": 2}))
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    by_lane, _ = confirm_list(api.list_packages(H["sort_supervisor_headers"],
                                           {"hub_id": night["hub_id"],
                                            "assigned_lane_id": lane["id"]}))
    assert len(by_lane) == 1 and by_lane[0]["id"] == first["id"]

    by_sort, _ = confirm_list(api.list_packages(H["sort_supervisor_headers"],
                                           {"hub_id": night["hub_id"],
                                            "sort_status": "PRIMARY_SORTED"}))
    assert len(by_sort) == 1

    by_induction, _ = confirm_list(api.list_packages(H["sort_supervisor_headers"],
                                                {"hub_id": night["hub_id"],
                                                 "induction_status": "INDUCTED"}))
    assert len(by_induction) == 2

    by_service, _ = confirm_list(api.list_packages(H["sort_supervisor_headers"],
                                              {"hub_id": night["hub_id"],
                                               "service_level": "GROUND"}))
    assert len(by_service) == 1
    defaulted, _ = confirm_list(api.list_packages(H["sort_supervisor_headers"],
                                             {"hub_id": night["hub_id"]}))
    assert len(defaulted) == 3, "a request with no limit returns the whole set" 


def test_an_unallocated_path_id_is_a_not_found_rather_than_a_bad_request():
    """PRD §2.8: "the first identifier that does not resolve inside the request's hub scope
    produces `ERR_RESOURCE_NOT_FOUND` (HTTP 404) immediately."

    Design: Corner/entities/hub_get_with_an_unknown_id_returns_resource_not_found
    """
    set_clock("2026-09-01T23:20:00Z")
    response = api.get_hub("00000000-0000-4000-8000-000000000000", H["hub_ops_manager_headers"])
    assert response.status_code == 404
    assert failed_error_id(response) == "ERR_RESOURCE_NOT_FOUND"
    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_RESOURCE_NOT_FOUND"
    assert len(body["data"]["message"].strip()) > 0


def test_omitting_a_required_package_field_leaves_no_row_behind():
    """PRD §2.8: "A malformed or incomplete request — a missing required input, an unknown
    field, a value of the wrong type, or an invalid enumeration member — is a
    distinct failure, `ERR_INVALID_REQUEST` (HTTP 400), and it is raised before
    any business rule is consulted."

    Design: Corner/entities/package_create_missing_planned_weight_returns_invalid_request
    """
    night = setup_bare_hub()
    set_clock("2026-09-01T23:20:00Z")
    bank = create_bank(night["hub_id"])
    aircraft = create_aircraft(bank["id"])
    create_shift(night["hub_id"])
    depart_and_land(aircraft["id"], 60000)
    confirm(api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"]))
    confirm(api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"]))
    confirm(api.complete_aircraft_unload(aircraft["id"], {"unload_completed_minutes": 1401},
                                         H["sort_supervisor_headers"]))

    response = api.create_package(
        {"hub_id": night["hub_id"], "aircraft_id": aircraft["id"],
         "tracking_number": "1Z-MF-9001", "commodity_class": "GENERAL",
         "destination_hub_code": "LAX", "service_level": "NEXT_DAY_AIR",
         "dimension_weight_grams": 20000},
        H["sort_operator_headers"])
    assert response.status_code == 400
    assert failed_error_id(response) == "ERR_INVALID_REQUEST"
    assert list_packages({"hub_id": night["hub_id"]}) == []


def test_a_buildup_defaults_its_optional_fields_but_requires_its_move():
    """PRD §3.6: "    "A buildup is unique per gateway within its move and is created with a
    `container_limit_grams`, an optional `hazardous_cap_grams` (defaulting to
    zero, and a cap of zero means the buildup accepts no hazardous content at
    all), and an optional `requires_container` flag defaulting to false.""

    Design: Corner/entities/buildup_create_omitting_the_optional_fields_defaults_them_and_load_move_id_is_required
    """
    night = setup_bare_hub()
    set_clock("2026-09-01T23:20:00Z")
    bank = create_bank(night["hub_id"])
    outbound = create_aircraft(bank["id"], tail_number="N702UP")
    from test_helpers import create_move
    move = create_move(night["hub_id"], outbound["id"], weight_limit_grams=400000)

    created = confirm(api.create_buildup(
        {"hub_id": night["hub_id"], "load_move_id": move["id"],
         "destination_gateway_code": "LAX", "container_limit_grams": 70000},
        H["load_planner_headers"]), 201)
    assert created["hazardous_cap_grams"] == 0
    assert created["requires_container"] is False
    assert created["rated_weight_grams"] == 0
    assert created["hazardous_weight_grams"] == 0
    assert created["status"] == "OPEN"
    assert created["load_plan_tier"] == "UNDER_CAPACITY"

    omitted = api.create_buildup(
        {"hub_id": night["hub_id"], "destination_gateway_code": "ORD",
         "container_limit_grams": 70000}, H["load_planner_headers"])
    assert omitted.status_code == 400
    assert failed_error_id(omitted) == "ERR_INVALID_REQUEST"


def test_a_client_supplied_computed_field_is_rejected_outright():
    """PRD §2.6: "no derived value is ever accepted as client input."
    PRD §1: "    "Every derived quantity — the live planning volume, the effective unload
    budget of a bank, the rated handling weight of a package, the reserve tier of
    a buildup, the money-back refund of a failure — is recomputed the moment its
    inputs move, and no derived value is ever accepted as client input.""

    Design: Corner/entities/hub_create_rejects_a_client_supplied_computed_posture
    """
    set_clock("2026-09-01T23:20:00Z")
    response = api.create_hub(
        {"iata_code": "SDF", "name": "Worldport Louisville",
         "sort_window_open_minutes": 1380, "sort_window_close_minutes": 1560,
         "posture": "LOCKDOWN", "live_planned_package_total": 999999},
        H["hub_ops_manager_headers"])
    assert response.status_code == 400
    assert failed_error_id(response) == "ERR_INVALID_REQUEST"
    hubs, _ = confirm_list(api.list_hubs(H["hub_ops_manager_headers"]))
    assert hubs == []


def test_the_four_state_planes_start_system_set_and_cannot_be_seeded():
    """PRD §1: "The system is designed to be complete and self-consistent, not merely
    plausible."

    Design: Corner/entities/package_create_starts_on_four_system_set_state_planes
    """
    night = setup_bare_hub()
    set_clock("2026-09-01T23:20:00Z")
    bank = create_bank(night["hub_id"])
    aircraft = create_aircraft(bank["id"])
    create_shift(night["hub_id"])
    depart_and_land(aircraft["id"], 60000)
    confirm(api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"]))
    confirm(api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"]))
    confirm(api.complete_aircraft_unload(aircraft["id"], {"unload_completed_minutes": 1401},
                                         H["sort_supervisor_headers"]))

    clean = confirm(api.create_package(
        {"hub_id": night["hub_id"], "aircraft_id": aircraft["id"],
         "tracking_number": "1Z-SY-0001", "commodity_class": "GENERAL",
         "destination_hub_code": "LAX", "service_level": "NEXT_DAY_AIR",
         "planned_weight_grams": 20000, "dimension_weight_grams": 20000},
        H["sort_operator_headers"]), 201)
    assert clean["induction_status"] == "NOT_INDUCTED"
    assert clean["sort_status"] == "UNSORTED"
    assert clean["commitment_status"] == "COMMITTED"
    assert clean["handling_status"] == "NORMAL"
    assert clean["version"] >= 1

    seeded = api.create_package(
        {"hub_id": night["hub_id"], "aircraft_id": aircraft["id"],
         "tracking_number": "1Z-SY-0002", "commodity_class": "GENERAL",
         "destination_hub_code": "LAX", "service_level": "NEXT_DAY_AIR",
         "planned_weight_grams": 20000, "dimension_weight_grams": 20000,
         "sort_status": "LOADED", "commitment_status": "DOWNGRADED"},
        H["sort_operator_headers"])
    assert seeded.status_code == 400
    loaded, _ = confirm_list(api.list_packages(H["sort_operator_headers"],
                                          {"sort_status": "LOADED"}))
    assert loaded == []


def test_an_out_of_enum_service_level_is_refused_at_the_envelope():
    """PRD §3.1: "a `service_level`, one of `NEXT_DAY_AIR`, `SECOND_DAY_AIR` or `GROUND`;"

    Design: Corner/entities/package_create_with_an_out_of_enum_service_level_returns_invalid_request
    """
    night = setup_bare_hub()
    set_clock("2026-09-01T23:20:00Z")
    bank = create_bank(night["hub_id"])
    aircraft = create_aircraft(bank["id"])
    create_shift(night["hub_id"])
    depart_and_land(aircraft["id"], 60000)
    confirm(api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"]))
    confirm(api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"]))
    confirm(api.complete_aircraft_unload(aircraft["id"], {"unload_completed_minutes": 1401},
                                         H["sort_supervisor_headers"]))
    response = api.create_package(
        {"hub_id": night["hub_id"], "aircraft_id": aircraft["id"],
         "tracking_number": "1Z-SV-0001", "commodity_class": "GENERAL",
         "destination_hub_code": "LAX", "service_level": "SAME_DAY_AIR",
         "planned_weight_grams": 20000, "dimension_weight_grams": 20000},
        H["sort_operator_headers"])
    assert response.status_code == 400
    assert failed_error_id(response) == "ERR_INVALID_REQUEST"


def test_an_ops_checkpoint_is_created_once_and_never_modified_in_place():
    """PRD §2.8: "`OpsRun` and `ServiceFailureClaim` are the two exceptions: they are
    created once and never modified in place, so they carry `id` and `created_at` only,
    and neither `updated_at` nor `version` appears on them."

    Design: Corner/entities/ops_run_is_immutable_and_terminal_after_it_advances
    """
    night = setup_bare_hub()
    set_clock("2026-09-01T23:20:00Z")
    confirm(api.declare_contingency(night["hub_id"], H["weather_officer_headers"]))
    ops_run = confirm(api.run_ops(night["hub_id"], {"minute_of_day": 1400, "level": "MAJOR"},
                                  H["hub_ops_manager_headers"]), 201)
    read = confirm(api.get_ops_run(ops_run["id"], H["hub_ops_manager_headers"]))
    assert read["run_index"] == 1
    assert read["level"] == "MAJOR"
    assert read["verdict"] == "HELD"
    assert "version" not in read
    assert "updated_at" not in read

    confirm(api.advance_ops_run(ops_run["id"], H["hub_ops_manager_headers"]))
    second = api.advance_ops_run(ops_run["id"], H["hub_ops_manager_headers"])
    assert second.status_code == 409
    assert failed_error_id(second) == "ERR_INVALID_STATE"
    hub = confirm(api.get_hub(night["hub_id"], H["hub_ops_manager_headers"]))
    assert hub["ops_run_index"] == 2, (
        "creating the checkpoint took the index to 1 and the advance took it to 2"
    )


def test_an_unknown_parent_reference_fails_before_the_row_is_written():
    """PRD §2.8: "every foreign key supplied in the body is validated in the order the
    endpoint's input list declares it, with the same error and the same hub-scope
    requirement."

    Design: Corner/entities/aircraft_create_with_an_unknown_bank_returns_resource_not_found
    """
    night = setup_bare_hub()
    set_clock("2026-09-01T23:20:00Z")
    response = api.create_aircraft(
        {"bank_id": "00000000-0000-4000-8000-000000000009", "tail_number": "N999UP",
         "origin_station_code": "LAX", "scheduled_arrival_minutes": 1395,
         "capacity_weight_grams": 200000},
        H["gateway_coordinator_headers"])
    assert response.status_code == 404
    assert failed_error_id(response) == "ERR_RESOURCE_NOT_FOUND"
    aircraft, _ = confirm_list(api.list_aircraft(H["hub_ops_manager_headers"],
                                            {"hub_id": night["hub_id"]}))
    assert aircraft == []


def test_body_foreign_keys_are_checked_in_declared_order_within_the_hub_scope():
    """PRD §2.8: "first `hub_id`, then the parent resource, then the operator-supplied content
    — so a package body reads `hub_id`, then `aircraft_id`, then the rest;"
    PRD §2.8: "with the same error and the same hub-scope requirement."

    Design: Corner/entities/package_create_checks_body_foreign_keys_in_declared_input_order_and_scopes
    """
    night = setup_bare_hub()
    set_clock("2026-09-01T23:20:00Z")
    bank = create_bank(night["hub_id"])
    aircraft = create_aircraft(bank["id"])
    create_shift(night["hub_id"])
    depart_and_land(aircraft["id"], 60000)
    confirm(api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"]))
    confirm(api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"]))
    confirm(api.complete_aircraft_unload(aircraft["id"], {"unload_completed_minutes": 1401},
                                         H["sort_supervisor_headers"]))

    foreign_bank = create_bank(night["alt_hub_id"], bank_code="BANK_Z")
    foreign_aircraft = create_aircraft(foreign_bank["id"], tail_number="N801UP",
                                       origin_station_code="MIA")

    both_unknown = api.create_package(
        {"hub_id": "00000000-0000-4000-8000-000000000001",
         "aircraft_id": "00000000-0000-4000-8000-000000000002",
         "tracking_number": "1Z-FK-0001", "commodity_class": "GENERAL",
         "destination_hub_code": "LAX", "service_level": "NEXT_DAY_AIR",
         "planned_weight_grams": 20000, "dimension_weight_grams": 20000},
        H["sort_operator_headers"])
    assert both_unknown.status_code == 404
    assert failed_error_id(both_unknown) == "ERR_RESOURCE_NOT_FOUND"

    wrong_scope = api.create_package(
        {"hub_id": night["hub_id"], "aircraft_id": foreign_aircraft["id"],
         "tracking_number": "1Z-FK-0002", "commodity_class": "GENERAL",
         "destination_hub_code": "LAX", "service_level": "NEXT_DAY_AIR",
         "planned_weight_grams": 20000, "dimension_weight_grams": 20000},
        H["sort_operator_headers"])
    assert wrong_scope.status_code == 404, "a real aircraft that belongs to a different hub"
    assert failed_error_id(wrong_scope) == "ERR_RESOURCE_NOT_FOUND"
    assert list_packages({"hub_id": night["hub_id"]}) == []