"""Shelter posture: the master operational gate, its terminal lock and its cascades."""
from test_helpers import (
    ApiErrorId,
    create_client,
    register_client,
    request_deployment,
    setup_open_shelter,
    setup_operation_with_shelter,
    setup_shelter_with_client,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_new_shelter_operation_starts_pending_open(api):
    """PRD §3.1: "which creates a `ShelterOperation` in `PENDING_OPEN` posture with zero
    `occupied_beds`, zero `registered_client_count`, zero `staffed_volunteer_count` and a
    `staffing_sufficiency` of 0.0."

    PRD §2.4: "Every shelter operation begins life in `PENDING_OPEN` and reaches its only
    terminal value, `CLOSED`, at the end of its life."

    Design: Corner/state_machines/shelter_operation_starts_pending_open
    """
    bundle = setup_open_shelter(open_the_shelter=False)
    # PRD §3.1 pins the state the activation *creates*, so assert on the creation
    # response rather than a later read (which recomputes the derived counts).
    shelter = bundle["shelter_created"]

    assert shelter["posture"] == "PENDING_OPEN"
    assert shelter["occupied_beds"] == 0
    assert shelter["registered_client_count"] == 0
    assert shelter["staffed_volunteer_count"] == 0
    assert float(shelter["staffing_sufficiency"]) == 0.0
    assert shelter.get("opened_at") is None


def test_closed_shelter_rejects_reopen(api):
    """PRD §2.4: "Reaching `CLOSED` is the end of the road: `CLOSED` is terminal and rejects
    every further transition with `ERR_ALREADY_TERMINAL` at HTTP status 409."

    PRD §2.4: "a request to move a resource that is not in a state admitting the requested
    transition is refused with `ERR_INVALID_STATE` at HTTP status 409."

    Design: Corner/state_machines/closed_shelter_rejects_reopen
    """
    bundle = setup_operation_with_shelter(phase="DEMOBILIZATION")
    shelter_id = bundle["shelter_id"]

    closed = validate_success(api.close_shelter(shelter_id, bundle["coordinator_headers"]))
    assert closed["posture"] == "CLOSED"

    resp = api.open_shelter(shelter_id, bundle["coordinator_headers"])
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE])

    after = validate_success(
        api.get_shelter_operation(shelter_id, bundle["coordinator_headers"]))
    assert after["posture"] == "CLOSED", "a closed shelter must not be reopened"


def test_registration_requires_open_posture_then_recovers(api):
    """PRD §2.4: "While a shelter sits in `RESTRICTED`, any attempt to register a new client
    is refused with `ERR_SHELTER_RESTRICTED` at HTTP status 409."

    PRD §2.4: "When `staffing_sufficiency` climbs back to 0.60 or above, it returns to `OPEN`
    on its own."

    Design: Difficulty/cross_entity_state_dependency/registration_requires_open_shelter_posture
    """
    bundle = setup_open_shelter()
    shelter_id = bundle["shelter_id"]
    coord = bundle["coordinator_headers"]
    manager = bundle["manager_headers"]

    client = create_client(bundle["region_id"])

    # Recalling the only deployment empties the floor: required is floored at 1 volunteer.
    validate_success(api.recall_deployment(bundle["deployment_id"], coord))
    shelter = validate_success(api.get_shelter_operation(shelter_id, coord))
    assert shelter["posture"] == "RESTRICTED"
    assert float(shelter["staffing_sufficiency"]) == 0.0

    resp = api.register_client(
        shelter_id,
        {"client_id": client["id"], "occupied_from_at": "2026-09-04T20:00:00Z",
         "functional_needs_flag": False},
        manager)
    validate_error(resp, ApiErrorId.ERR_SHELTER_RESTRICTED)

    # A replacement deployment returns the shelter to OPEN.
    replacement = request_deployment(
        bundle["volunteer_id"], bundle["operation_id"],
        shelter_operation_id=shelter_id, role_code="SHELTER_MANAGER",
        travel_mode="AIR", rotation_start_at="2026-09-03T00:00:00Z", rotation_days=7)
    validate_success(api.approve_deployment(replacement["id"], coord))

    shelter = validate_success(api.get_shelter_operation(shelter_id, coord))
    assert shelter["posture"] == "OPEN"
    assert float(shelter["staffing_sufficiency"]) == 1.0

    registration = validate_success(api.register_client(
        shelter_id,
        {"client_id": client["id"], "occupied_from_at": "2026-09-04T20:00:00Z",
         "functional_needs_flag": False},
        manager), 201)
    assert registration["status"] == "REGISTERED"


def test_restricted_posture_gate_survives_a_second_attempt(api):
    """PRD §2.4: "A shelter that is `PENDING_OPEN`, `CONSOLIDATING` or `CLOSED` admits
    neither operation."

    PRD §2.4: "a client cannot be registered and a volunteer cannot be checked into a shift
    unless the shelter's posture currently permits it."

    Design: Difficulty/cross_entity_state_dependency/registration_requires_open_shelter_posture
    """
    bundle = setup_open_shelter()
    coord = bundle["coordinator_headers"]
    manager = bundle["manager_headers"]

    validate_success(api.recall_deployment(bundle["deployment_id"], coord))
    shelter = validate_success(api.get_shelter_operation(bundle["shelter_id"], coord))
    assert shelter["posture"] == "RESTRICTED"

    for name in ("Ana Lopez", "Ben Okafor"):
        client = create_client(bundle["region_id"], full_name=name, household_size=2)
        resp = api.register_client(
            bundle["shelter_id"],
            {"client_id": client["id"], "occupied_from_at": "2026-09-04T20:00:00Z",
             "functional_needs_flag": False},
            manager)
        validate_error(resp, ApiErrorId.ERR_SHELTER_RESTRICTED)

    shelter = validate_success(api.get_shelter_operation(bundle["shelter_id"], coord))
    assert shelter["registered_client_count"] == 0


def test_restricted_posture_error_wins_over_capacity_error(api):
    """PRD §2.11: "Fourth, state admissibility: the target must be in a state that admits the
    requested transition, a terminal resource rejects everything, and a shelter in
    `RESTRICTED` posture rejects registrations."

    PRD §2.11: "Ninth and last, capacity and donor money — the minimum-award floor, the pool
    balance, the pool restriction compatibility, the bed capacity ceiling, bed assignability,
    candidate availability, and the blood collection target."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_restricted_full_shelter
    """
    bundle = setup_open_shelter(capacity_beds=1)
    coord = bundle["coordinator_headers"]
    manager = bundle["manager_headers"]

    first = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=5)
    second = create_client(bundle["region_id"], full_name="Ben Okafor", household_size=2)
    register_client(bundle["shelter_id"], first["id"], manager)

    validate_success(api.recall_deployment(bundle["deployment_id"], coord))

    shelter = validate_success(api.get_shelter_operation(bundle["shelter_id"], coord))
    assert shelter["posture"] == "RESTRICTED"
    assert shelter["occupied_beds"] == 1

    resp = api.register_client(
        bundle["shelter_id"],
        {"client_id": second["id"], "occupied_from_at": "2026-09-04T20:00:00Z",
         "functional_needs_flag": False},
        manager)
    validate_error(resp, ApiErrorId.ERR_SHELTER_RESTRICTED)
    assert resp.json()["data"]["error_id"] != "ERR_CAPACITY_EXCEEDED", (
        "state admissibility outranks the capacity ceiling")


def test_full_shelter_is_capacity_blocked_not_posture_blocked(api):
    """PRD §2.4: "a registration that would push `occupied_beds` past the site's
    `capacity_verified_beds` is refused with `ERR_CAPACITY_EXCEEDED` at HTTP status 409 — so a
    shelter that is completely full but fully staffed stays `OPEN` and simply rejects the next
    registration on the capacity rule."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_restricted_full_shelter
    """
    bundle = setup_open_shelter(capacity_beds=1)
    manager = bundle["manager_headers"]

    first = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=5)
    second = create_client(bundle["region_id"], full_name="Ben Okafor", household_size=2)
    register_client(bundle["shelter_id"], first["id"], manager)

    shelter = validate_success(
        api.get_shelter_operation(bundle["shelter_id"], bundle["coordinator_headers"]))
    assert shelter["posture"] == "OPEN", "capacity is not a posture input"
    assert shelter["occupied_beds"] == 1

    resp = api.register_client(
        bundle["shelter_id"],
        {"client_id": second["id"], "occupied_from_at": "2026-09-04T20:00:00Z",
         "functional_needs_flag": False},
        manager)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_failed_reinspection_suspends_site_and_restricts_shelter(api):
    """PRD §3.1: "A `FAIL` recorded against an already-`APPROVED` site also moves it to
    `SUSPENDED`, and this is the more consequential path: the suspension cascades two levels
    down, so every shelter operation at that site currently in `OPEN` or `RESTRICTED` posture
    is forced into `RESTRICTED` immediately."

    Design: Difficulty/transitive_cascade/failed_inspection_suspends_site_and_restricts_shelters
    """
    bundle = setup_open_shelter()
    coord = bundle["coordinator_headers"]

    site = validate_success(api.get_shelter_site(bundle["site_id"], coord))
    assert site["agreement_status"] == "APPROVED"

    failed = validate_success(api.record_inspection(
        bundle["site_id"],
        {"expected_shelter_site_version": site["version"],
         "inspected_at": "2026-09-10T12:00:00Z",
         "inspector_user_id": "rc_gl",
         "capacity_verified_beds": 0,
         "accessibility_verified": False,
         "functional_needs_verified": False,
         "deficiency_count": 4,
         "result": "FAIL"},
        coord), 201)
    assert failed["agreement_status"] == "SUSPENDED"
    assert failed["inspection_result"] == "FAIL"

    shelter = validate_success(api.get_shelter_operation(bundle["shelter_id"], coord))
    assert shelter["posture"] == "RESTRICTED"


def test_suspended_site_blocks_new_registrations(api):
    """PRD §3.1: "Clients already sheltered there stay sheltered, but the shelter stops
    accepting new registrations until it recovers."

    PRD §2.4: "While a shelter sits in `RESTRICTED`, any attempt to register a new client is
    refused with `ERR_SHELTER_RESTRICTED` at HTTP status 409."

    Design: Difficulty/transitive_cascade/failed_inspection_suspends_site_and_restricts_shelters
    """
    bundle = setup_open_shelter()
    coord = bundle["coordinator_headers"]
    manager = bundle["manager_headers"]
    client = create_client(bundle["region_id"])

    site = validate_success(api.get_shelter_site(bundle["site_id"], coord))
    validate_success(api.record_inspection(
        bundle["site_id"],
        {"expected_shelter_site_version": site["version"],
         "inspected_at": "2026-09-10T12:00:00Z",
         "inspector_user_id": "rc_gl",
         "capacity_verified_beds": 0,
         "accessibility_verified": False,
         "functional_needs_verified": False,
         "deficiency_count": 4,
         "result": "FAIL"},
        coord), 201)

    resp = api.register_client(
        bundle["shelter_id"],
        {"client_id": client["id"], "occupied_from_at": "2026-09-10T20:00:00Z",
         "functional_needs_flag": False},
        manager)
    validate_error(resp, ApiErrorId.ERR_SHELTER_RESTRICTED)


def test_shelter_close_recalls_deployments(api):
    """PRD §3.1: "That final step cascades three levels: every volunteer deployment assigned to
    the shelter whose status is `ARRIVED` or `ON_SHIFT` is recalled, each affected volunteer's
    `deployment_availability` returns to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/shelter_close_recalls_deployments_and_recounts_region
    """
    bundle = setup_shelter_with_client()
    coord = bundle["coordinator_headers"]
    manager = bundle["manager_headers"]

    op = validate_success(api.advance_operation_phase(bundle["operation_id"], coord))
    assert op["phase"] == "ACTIVE"
    op = validate_success(api.advance_operation_phase(bundle["operation_id"], coord))
    assert op["phase"] == "DEMOBILIZATION"

    first_close = validate_success(api.close_shelter(bundle["shelter_id"], coord))
    assert first_close["posture"] == "CONSOLIDATING", (
        "a shelter with clients still inside consolidates rather than closing")

    validate_success(api.check_out_registration(bundle["registration_id"], {}, manager))

    final_close = validate_success(api.close_shelter(bundle["shelter_id"], coord))
    assert final_close["posture"] == "CLOSED"

    deployment = validate_success(
        api.get_deployment(bundle["deployment_id"], coord))
    assert deployment["status"] == "RECALLED"

    volunteer = validate_success(api.get_volunteer(bundle["volunteer_id"], coord))
    assert volunteer["deployment_availability"] == "AVAILABLE"


def test_shelter_close_recounts_region_volunteer_totals(api):
    """PRD §3.1: "the `available_volunteer_count` and `deployed_volunteer_count` of every
    affected volunteer's home region are recomputed."

    Design: Difficulty/transitive_cascade/shelter_close_recalls_deployments_and_recounts_region
    """
    bundle = setup_shelter_with_client()
    coord = bundle["coordinator_headers"]
    manager = bundle["manager_headers"]

    before = validate_success(api.get_region(bundle["region_id"], coord))
    assert before["available_volunteer_count"] == 0
    assert before["deployed_volunteer_count"] == 1

    validate_success(api.advance_operation_phase(bundle["operation_id"], coord))
    validate_success(api.advance_operation_phase(bundle["operation_id"], coord))
    validate_success(api.close_shelter(bundle["shelter_id"], coord))
    validate_success(api.check_out_registration(bundle["registration_id"], {}, manager))
    validate_success(api.close_shelter(bundle["shelter_id"], coord))

    after = validate_success(api.get_region(bundle["region_id"], coord))
    assert after["deployed_volunteer_count"] == 0
    assert after["available_volunteer_count"] == 1


def test_shelter_open_rejected_when_inspection_is_stale(api):
    """PRD §2.5: "Even an approved site can go stale: if the most recent inspection is more
    than 365 days old at the logical clock, the opening request is refused with
    `ERR_INSPECTION_STALE` at HTTP status 409."

    Design: Corner/validations/shelter_open_rejected_when_inspection_is_stale
    """
    bundle = setup_open_shelter(
        open_the_shelter=False,
        inspected_at="2025-01-01T12:00:00Z",
        open_clock="2026-09-03T00:00:00Z")

    site = validate_success(
        api.get_shelter_site(bundle["site_id"], bundle["coordinator_headers"]))
    assert site["agreement_status"] == "APPROVED"
    assert site["inspection_result"] == "PASS"

    resp = api.open_shelter(bundle["shelter_id"], bundle["coordinator_headers"])
    validate_error(resp, ApiErrorId.ERR_INSPECTION_STALE)

    shelter = validate_success(
        api.get_shelter_operation(bundle["shelter_id"], bundle["coordinator_headers"]))
    assert shelter["posture"] == "PENDING_OPEN"


def test_registration_effect_is_visible_on_the_immediate_next_read(api):
    """PRD §3.2: "The shelter's occupancy aggregates are recomputed at once: `occupied_beds`
    counts registrations in `REGISTERED` status that hold a non-null `dormitory_bed_code`."

    Design: Corner/consistency_model/registration_visible_in_same_request_cycle
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]
    client = create_client(bundle["region_id"])

    registration = validate_success(api.register_client(
        bundle["shelter_id"],
        {"client_id": client["id"], "occupied_from_at": "2026-09-03T20:00:00Z",
         "functional_needs_flag": False},
        manager), 201)

    shelter = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert shelter["occupied_beds"] == 1
    assert shelter["registered_client_count"] == 1

    read_back = validate_success(api.get_registration(registration["id"], manager))
    assert read_back["status"] == "REGISTERED"
    assert read_back["dormitory_bed_code"] is not None
