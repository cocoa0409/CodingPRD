"""Access events, cleanliness signals, validation arity and RBAC corners."""
from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATOR,
    api_client,
    approve_member_with_membership,
    assert_community_signal,
    create_pod,
    create_reservation,
    create_vehicle,
    get_success_data,
    make_member_headers,
    raise_cleanliness_signal,
    setup_confirmed_reservation,
    start_trip,
    validate_success,
)
from test_helpers.fixtures import ANONYMOUS, FLEET, PLATFORM


def test_cleanliness_signal_advances_the_parallel_posture_regardless_of_use_status():
    """PRD §3.12: "A vehicle in `CLEAN`, `REPORTED_DIRTY` or `CLEANING` that receives a
    cleanliness signal moves to `REPORTED_DIRTY`, provided the signal's `pod_id` equals the
    vehicle's own `pod_id`"
    PRD §3.5: "`cleanliness_state` is a parallel dimension, independent of the use lifecycle"

    Design: Corner/state_machines/cleanliness_reported_dirty_branch_ignores_use_status
    """
    # PRD §3.12: a cleanliness signal records the acting member as the signal's
# `member_id`, and a Member caller is an entity-backed identity (§2.1), so the
# fixture must raise it as a real member.
    member, _membership = approve_member_with_membership(full_name="Cody Cleanliness")
    pod = create_pod(name="Parallel Lot", site_type="CAMPUS", capacity=3)
    vehicle = create_vehicle(pod["id"])
    order = validate_success(
        api_client.create_maintenance_order(
            {
                "vehicle_id": vehicle["id"],
                "reason": "BRAKE_SERVICE",
                "blocking": True,
                "scheduled_start": "2026-09-13T09:00:00Z",
                "scheduled_end": "2026-09-13T11:00:00Z",
            },
            OPERATOR,
        ),
        201,
    )
    assert order["status"] == "BLOCKED", (
        f"A blocking order takes the vehicle into MAINTENANCE, got {order['status']}"
    )
    before = validate_success(api_client.get_vehicle(vehicle["id"], OPERATOR), 200)
    assert before["use_status"] == "MAINTENANCE", (
        f"The vehicle must be in the maintenance posture for this corner, got "
        f"{before['use_status']}"
    )
    assert before["cleanliness_state"] == "CLEAN", (
        f"The cleanliness dimension starts CLEAN, got {before['cleanliness_state']}"
    )

    signal = raise_cleanliness_signal(
        member_id=member["id"],
        pod_id=pod["id"],
        vehicle_id=vehicle["id"],
        message="crumbs on the rear seat",
    )

    assert_community_signal(signal)
    assert signal["signal_type"] == "CLEANLINESS", (
        f"The signal class is recorded as raised, got {signal['signal_type']}"
    )
    after = validate_success(api_client.get_vehicle(vehicle["id"], OPERATOR), 200)
    assert after["cleanliness_state"] == "REPORTED_DIRTY", (
        f"The parallel dimension advances on a cleanliness signal, got "
        f"{after['cleanliness_state']}"
    )
    assert after["use_status"] == "MAINTENANCE", (
        f"The use lifecycle is untouched by a cleanliness signal, got {after['use_status']}"
    )


def test_access_event_success_starts_the_trip_on_both_rows():
    """PRD §3.7: "On success the event's `outcome` is set to `SUCCESS`, the reservation's
    `version` increments and the vehicle's `version` increments."
    PRD §3.7: "For the reservation, a `CONFIRMED` reservation whose vehicle is `RESERVED` and
    whose member matches the event's `member_id` moves to `IN_USE`."

    Design: Corner/state_machines/hold_confirmation_blocked_by_unavailable_vehicle
    """
    setup = setup_confirmed_reservation(pod_name="Access Lot")

    event = start_trip(setup["member"]["id"], setup["reservation"]["id"], method="APP")

    assert event["outcome"] == "SUCCESS", (
        f"A clean access attempt starts the trip, got {event['outcome']}"
    )
    assert event["vehicle_id"] == setup["vehicle"]["id"], (
        f"The event's vehicle_id is derived from the reservation, got {event['vehicle_id']}"
    )
    reservation = validate_success(
        api_client.get_reservation(setup["reservation"]["id"], OPERATOR), 200
    )
    vehicle = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    assert reservation["status"] == "IN_USE", (
        f"The reservation advances to IN_USE, got {reservation['status']}"
    )
    assert vehicle["use_status"] == "IN_USE", (
        f"The vehicle advances to IN_USE, got {vehicle['use_status']}"
    )


def test_retiring_an_available_vehicle_is_an_undeclared_transition():
    """PRD §3.5: "Setting the event to `RETIRE` requires the vehicle to already be
    `OUT_OF_SERVICE` and moves it to `RETIRED`, which is the vehicle's terminal posture."
    PRD §3.5: "`use_status` is one of `AVAILABLE`, `RESERVED`, `IN_USE`, `CLEANING`,
    `MAINTENANCE`, `OUT_OF_SERVICE` or `RETIRED`"

    Design: Corner/endpoints/forward_repair_action_blocked_while_vehicle_operational
    """
    pod = create_pod(name="Retire Lot", site_type="CAMPUS", capacity=3)
    vehicle = create_vehicle(pod["id"])

    refused = api_client.post_availability_event(
        vehicle["id"], {"event": "RETIRE"}, FLEET
    )

    assert refused.status_code == 409, (
        f"RETIRE from AVAILABLE is not a declared edge, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_INVALID_STATE", (
        f"Got {refused.json()['data']['error_id']}"
    )
    after = validate_success(api_client.get_vehicle(vehicle["id"], OPERATOR), 200)
    assert after["use_status"] == "AVAILABLE", (
        f"The refused retire leaves the vehicle available, got {after['use_status']}"
    )


def test_out_of_service_event_applies_its_side_effect_in_the_same_response():
    """PRD §3.5: "Setting the event to `OUT_OF_SERVICE` requires the vehicle's `use_status` to
    be `AVAILABLE` or `RESERVED` and requires that the vehicle has no reservation in `IN_USE`;
    it sets `use_status` to `OUT_OF_SERVICE`."
    PRD §3.5: "Both recompute the pod's derived values and increment the vehicle's `version`."

    Design: Corner/endpoints/availability_event_out_of_service_side_effect_applied
    """
    pod = create_pod(name="OOS Lot", site_type="CAMPUS", capacity=3)
    vehicle = create_vehicle(pod["id"])
    before = validate_success(api_client.get_pod(pod["id"], FLEET), 200)
    assert before["available_bays"] == 2, (
        f"One vehicle placed in a capacity-3 pod leaves 2 bays, got {before['available_bays']}"
    )

    after = validate_success(
        api_client.post_availability_event(vehicle["id"], {"event": "OUT_OF_SERVICE"}, OPERATOR),
        200,
    )

    assert after["use_status"] == "OUT_OF_SERVICE", (
        f"The event sets the posture it names, got {after['use_status']}"
    )
    assert after["version"] > vehicle["version"], (
        f"The vehicle's version increments on the change: {vehicle['version']} → {after['version']}"
    )
    pod_after = validate_success(api_client.get_pod(pod["id"], FLEET), 200)
    assert pod_after["available_bays"] == 2, (
        f"An OUT_OF_SERVICE vehicle still calls the pod home, so the bay stays displaced; got "
        f"{pod_after['available_bays']}"
    )


def test_maintenance_completion_releases_the_vehicle_and_clears_the_cleanliness_posture():
    """PRD §3.12: "When the order's `reason` is `CLEANING` and the vehicle's `use_status` is
    `CLEANING`, the `use_status` returns to `AVAILABLE`. The cleanliness posture is then
    resolved by the reason-and-departure rules given above"
    PRD §3.8: "A vehicle in `IN_USE` whose return reports a `contamination_level` of 3 or more
    moves to `CLEANING`: its `cleanliness_state` is set to `CLEANING`"

    Design: Corner/endpoints/maintenance_completion_releases_the_vehicle_and_clears_cleaning
    """
    setup = setup_confirmed_reservation(pod_name="Clean Lot", start_at="2026-09-05T09:00:00Z",
                                        end_at="2026-09-05T13:00:00Z")
    start_trip(setup["member"]["id"], setup["reservation"]["id"], method="KEY_CARD")
    get_success_data(api_client.set_clock("2026-09-05T13:00:00Z", PLATFORM), 200)

    returned = validate_success(
        api_client.return_reservation(
            setup["reservation"]["id"],
            {
                "returned_pod_id": setup["pod"]["id"],
                "returned_odometer_miles": 45000,
                "returned_fuel_level_pct": 60,
                "contamination_level": 3,
            },
            make_member_headers(setup["member"]["id"]),
        ),
        200,
    )
    assert returned["status"] in ("RETURNED", "OVERDUE"), (
        f"The physical return always moves the reservation off IN_USE, got {returned['status']}"
    )
    awaiting = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    assert awaiting["cleanliness_state"] == "CLEANING", (
        f"A contamination level of 3 sets the cleanliness dimension to CLEANING, got "
        f"{awaiting['cleanliness_state']}"
    )
    orders = validate_success(
        api_client.list_vehicle_maintenance_orders(setup["vehicle"]["id"], OPERATOR), 200
    )
    cleaning = [o for o in orders if o["reason"] == "CLEANING"]
    assert cleaning, (
        f"A contamination level of 3 creates a CLEANING order, got {[o['reason'] for o in orders]}"
    )
    assert cleaning[0]["blocking"] is False, (
        "The cleaning order is created with blocking false"
    )
    assert cleaning[0]["status"] == "SCHEDULED", (
        f"A non-blocking order remains SCHEDULED, got {cleaning[0]['status']}"
    )

    # PRD §3.12: only a BLOCKED order may be started, so the order whose completion
    # resolves the posture is raised blocking. Its window is adjacent to the
    # SCHEDULED cleaning order the return already created, which does not collide
    # because the windows are half-open.
    order = validate_success(
        api_client.create_maintenance_order(
            {
                "vehicle_id": setup["vehicle"]["id"],
                "reason": "CLEANING",
                "blocking": True,
                "scheduled_start": "2026-09-14T09:00:00Z",
                "scheduled_end": "2026-09-14T11:00:00Z",
            },
            OPERATOR,
        ),
        201,
    )
    assert order["status"] == "BLOCKED", (
        f"A blocking order moves straight into BLOCKED, got {order['status']}"
    )
    get_success_data(api_client.start_maintenance_order(order["id"], OPERATOR), 200)
    completed = validate_success(
        api_client.complete_maintenance_order(order["id"], OPERATOR), 200
    )

    assert completed["status"] == "COMPLETED", (
        f"Completion is one of the order's two terminal postures, got {completed['status']}"
    )
    vehicle = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    assert vehicle["cleanliness_state"] == "CLEAN", (
        f"Departure from CLEANING resolves to CLEAN, got {vehicle['cleanliness_state']}"
    )


def test_registration_without_a_required_field_is_refused():
    """PRD §3.1: "`full_name` and `email` are required; `email` is the login identity and is
    unique across all members, so a second application carrying an email that already exists
    is refused with `ERR_MEMBER_EMAIL_TAKEN` (HTTP 409)."

    Design: Corner/entities/required_field_missing_on_member_registration
    """
    get_success_data(
        api_client.register_member(
            {"full_name": "Seed Only", "email": "seed.only@x.com", "kind": "INDIVIDUAL"},
            {"X-User-ID": "anon-seed", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
        ),
        201,
    )

    refused = api_client.register_member(
        {"email": "no.name@x.com", "kind": "INDIVIDUAL"},
        {"X-User-ID": "anon-noname", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
    )

    assert refused.status_code == 400, (
        f"A missing required field is a malformed request, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_INVALID_REQUEST", (
        f"Got {refused.json()['data']['error_id']}"
    )
    members = validate_success(
        api_client.list_members(OPERATOR, {"application_status": "APPLIED"}), 200
    )
    assert len(members) == 1, (
        f"Only the seeded member exists; the refused registration creates no row. Got "
        f"{len(members)}"
    )


def test_kind_outside_the_declared_set_is_refused():
    """PRD §3.1: "The `kind` field is one of `INDIVIDUAL`, `STUDENT` or `EMPLOYEE`"
    PRD §3.1: "`email` is the login identity and is unique across all members, so a second
    application carrying an email that already exists is refused with `ERR_MEMBER_EMAIL_TAKEN`
    (HTTP 409)."

    Design: Corner/entities/enum_outside_declared_set_rejected
    """
    get_success_data(
        api_client.register_member(
            {"full_name": "Enum Seed", "email": "enum.seed@x.com", "kind": "INDIVIDUAL"},
            {"X-User-ID": "anon-enum", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
        ),
        201,
    )

    refused = api_client.register_member(
        {"full_name": "Bad Enum", "email": "bad.enum@x.com", "kind": "CORPORATE"},
        {"X-User-ID": "anon-bad", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
    )

    assert refused.status_code == 400, (
        f"An enum outside its declared set is malformed, got {refused.status_code}"
    )
    error_id = refused.json()["data"]["error_id"]
    assert error_id == "ERR_INVALID_REQUEST", f"Got {error_id}"
    assert error_id != "ERR_MEMBER_EMAIL_TAKEN", (
        "The email guard is not what refuses a bad enum value"
    )


def test_duplicate_vin_on_vehicle_creation_is_refused():
    """PRD §3.5: "The `vin` is unique across all vehicles and `capacity_seats` is the vehicle's
    seating capacity."
    PRD §3.4: "The `released amount is the floor of `membership_billing_cents` multiplied by
    80 percent."

    Design: Corner/errors/error_duplicate_vin_on_vehicle_creation
    """
    pod = create_pod(name="Vin Lot", site_type="CAMPUS", capacity=8)
    first = create_vehicle(pod["id"], vin="VIN3158T1")

    refused = api_client.create_vehicle(
        {"pod_id": pod["id"], "vin": "VIN3158T1", "model": "Kiger", "capacity_seats": 5},
        FLEET,
    )

    assert refused.status_code == 400, (
        f"A duplicate VIN is a malformed request, got {refused.status_code}"
    )
    error_id = refused.json()["data"]["error_id"]
    assert error_id == "ERR_INVALID_REQUEST", f"Got {error_id}"
    assert error_id != "ERR_POD_CAPACITY_EXCEEDED", (
        "The VIN guard is not the capacity guard, so the pod must not be the refusal reason"
    )
    rows = validate_success(api_client.list_pod_vehicles(pod["id"], FLEET), 200)
    assert [row["id"] for row in rows] == [first["id"]], (
        f"The pre-existing vehicle remains the only row reachable through the pod list, got "
        f"{len(rows)} rows"
    )


def test_loss_estimate_above_the_repair_cost_is_refused_at_incident_opening():
    """PRD §3.13: "The supplied `vehicle_id` and `member_id` must agree with the reservation's
    own `vehicle_id` and `member_id`; a disagreement is refused with
    `ERR_INCIDENT_REFERENCE_MISMATCH` (HTTP 422). A `loss_estimate_cents` that exceeds the
    incident's `repair_cost_cents` is refused with `ERR_LOSS_EXCEEDS_REPAIR_COST` (HTTP 422)."

    Design: Corner/errors/error_loss_exceeds_repair_cost_on_incident_open
    """
    setup = setup_confirmed_reservation(pod_name="Loss Lot")
    start_trip(setup["member"]["id"], setup["reservation"]["id"])
    get_success_data(
        api_client.return_reservation(
            setup["reservation"]["id"],
            {
                "returned_pod_id": setup["pod"]["id"],
                "returned_odometer_miles": 31000,
                "returned_fuel_level_pct": 70,
                "contamination_level": 0,
            },
            make_member_headers(setup["member"]["id"]),
        ),
        200,
    )

    refused = api_client.create_incident(
        {
            "reservation_id": setup["reservation"]["id"],
            "vehicle_id": setup["vehicle"]["id"],
            "member_id": setup["member"]["id"],
            "incident_type": "DAMAGE",
            "repair_cost_cents": 5000,
            "loss_estimate_cents": 9000,
        },
        OPERATOR,
    )

    assert refused.status_code == 422, (
        f"A loss estimate above the repair cost is refused with 422, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_LOSS_EXCEEDS_REPAIR_COST", (
        f"Got {refused.json()['data']['error_id']}"
    )
    incidents = validate_success(
        api_client.list_incidents(OPERATOR, {"reservation_id": setup["reservation"]["id"]}), 200
    )
    assert incidents == [], f"A refused incident creates no row, got {len(incidents)}"


def test_odometer_regression_is_refused_and_the_trip_stays_open():
    """PRD §3.8: "Then the odometer rule: `ERR_ODOMETER_REGRESSION` (HTTP 422) is returned when
    the reported `returned_odometer_miles` is lower than the vehicle's current
    `odometer_miles`."

    Design: Corner/errors/error_odometer_regression_on_return
    """
    setup = setup_confirmed_reservation(pod_name="Odo Lot")
    start_trip(setup["member"]["id"], setup["reservation"]["id"], method="APP")
    vehicle = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    # The guard reads the vehicle's stored odometer_miles, and on a fresh vehicle
    # that field is the creation default of 0, which no reported reading can fall
    # below. This corner is about the refused attempt, so the stored reading is
    # seeded through a first return that actually records one.
    get_success_data(api_client.set_clock("2026-09-05T14:00:00Z", PLATFORM), 200)
    seeded = api_client.return_reservation(
        setup["reservation"]["id"],
        {
            "returned_pod_id": setup["pod"]["id"],
            "returned_odometer_miles": 30000,
            "returned_fuel_level_pct": 60,
            "contamination_level": 0,
        },
        make_member_headers(setup["member"]["id"]),
    )
    validate_success(seeded, 200)
    recorded = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    assert recorded["odometer_miles"] == 30000, (
        f"The seeded return records the reported reading on the vehicle, got "
        f"{recorded['odometer_miles']}"
    )

    # A second trip is needed before the refused attempt: the declared return edge
    # runs from IN_USE (PRD §3.8), and the reservation is no longer there.
    vehicle = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    second_trip = create_reservation(
        setup["member"]["id"], setup["pod"]["id"], setup["vehicle"]["id"], vehicle["version"],
        start_at="2026-09-06T09:00:00Z", end_at="2026-09-06T13:00:00Z",
    )
    start_trip(setup["member"]["id"], second_trip["id"], method="APP")
    reported = 29000

    refused = api_client.return_reservation(
        second_trip["id"],
        {
            "returned_pod_id": setup["pod"]["id"],
            "returned_odometer_miles": reported,
            "returned_fuel_level_pct": 60,
            "contamination_level": 1,
        },
        make_member_headers(setup["member"]["id"]),
    )

    assert refused.status_code == 422, (
        f"A lower reading is refused with 422, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_ODOMETER_REGRESSION", (
        f"Got {refused.json()['data']['error_id']}"
    )
    reservation = validate_success(
        api_client.get_reservation(second_trip["id"], OPERATOR), 200
    )
    assert reservation["status"] == "IN_USE", (
        f"The refused return leaves the trip open, got {reservation['status']}"
    )


def test_cancelling_an_unknown_reservation_returns_the_not_found_error():
    """PRD §2.11: "The error returned is the not-found error belonging to that segment's entity:
    `ERR_MEMBER_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_POD_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MAINTENANCE_ORDER_NOT_FOUND`, `ERR_ACCESS_EVENT_NOT_FOUND` or
    `ERR_FUEL_TRANSACTION_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/error_reservation_not_found_on_cancel
    """
    create_pod(name="Seed Pod", site_type="NEIGHBORHOOD", capacity=1, fuel_floor_pct=25)

    refused = api_client.cancel_reservation(
        NON_EXISTENT_UUID, OPERATOR, {"reason": "CHANGED_PLANS"}
    )

    assert refused.status_code == 404, (
        f"An unknown reservation id returns 404, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_RESERVATION_NOT_FOUND", (
        f"Got {refused.json()['data']['error_id']}"
    )


def test_party_split_from_a_caller_without_a_declared_role_is_refused():
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries a value that is not
    one of the declared roles below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.12: "The authentication checks run first: header presence and declared-role
    membership (`ERR_UNAUTHENTICATED`), then the role-permission and ownership test
    (`ERR_FORBIDDEN`)."

    Design: Corner/rbac/party_split_denied_to_anonymous_caller
    """
    setup = setup_confirmed_reservation(pod_name="Undeclared Split Lot")
    incident = get_success_data(
        api_client.create_incident(
            {
                "reservation_id": setup["reservation"]["id"],
                "vehicle_id": setup["vehicle"]["id"],
                "member_id": setup["member"]["id"],
                "incident_type": "DAMAGE",
                "repair_cost_cents": 4000,
            },
            OPERATOR,
        ),
        201,
    )

    refused = api_client.party_split(
        incident["id"], {"expected_incident_version": incident["version"]},
        {"X-User-ID": "opaque-splitter", "X-User-Role": "ScreeningBot"},
    )

    assert refused.status_code == 401, (
        f"An undeclared role is refused before any business check, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED", (
        f"Got {refused.json()['data']['error_id']}"
    )
    after = validate_success(api_client.get_incident(incident["id"], OPERATOR), 200)
    assert after["status"] == "OPEN", (
        f"The refused split leaves the incident OPEN, got {after['status']}"
    )


def test_party_split_is_refused_for_the_anonymous_role():
    """PRD §2.1: "An `Anonymous` caller ... may file a membership application and browse
    public pod and vehicle listings, and nothing more."
    PRD §2.1: "A request whose role is recognised but which is not permitted for the
    operation being attempted is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/party_split_denied_to_anonymous_caller
    """
    setup = setup_confirmed_reservation(pod_name="Anonymous Split Lot")
    incident = get_success_data(
        api_client.create_incident(
            {
                "reservation_id": setup["reservation"]["id"],
                "vehicle_id": setup["vehicle"]["id"],
                "member_id": setup["member"]["id"],
                "incident_type": "DAMAGE",
                "repair_cost_cents": 4000,
            },
            OPERATOR,
        ),
        201,
    )

    refused = api_client.party_split(
        incident["id"], {"expected_incident_version": incident["version"]}, ANONYMOUS
    )

    assert refused.status_code == 403, (
        f"The anonymous role is recognised but unpermitted here, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_FORBIDDEN", (
        f"Got {refused.json()['data']['error_id']}"
    )
    after = validate_success(api_client.get_incident(incident["id"], OPERATOR), 200)
    assert after["status"] == "OPEN", (
        f"The refused split leaves the incident OPEN, got {after['status']}"
    )


def test_pod_creation_is_refused_for_a_pod_operator():
    """PRD §2.1: "A request whose role is recognised but which is not permitted for the
    operation being attempted is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/pod_creation_denied_to_pod_operator
    """
    create_pod(name="Owned Pod", site_type="NEIGHBORHOOD", capacity=1, fuel_floor_pct=25)

    refused = api_client.create_pod(
        {"name": "Illegal Pod", "site_type": "NEIGHBORHOOD", "capacity": 1, "fuel_floor_pct": 25},
        OPERATOR,
    )

    assert refused.status_code == 403, (
        f"Pod creation is a FleetAdmin exclusive operation, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_FORBIDDEN", (
        f"Got {refused.json()['data']['error_id']}"
    )
    pods = validate_success(api_client.list_pods(FLEET), 200)
    assert len(pods) == 1, f"No pod is created by the refused call, got {len(pods)}"


def test_membership_creation_is_refused_for_a_pod_operator():
    """PRD §2.1: "A request whose role is recognised but which is not permitted for the
    operation being attempted is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/membership_creation_denied_to_pod_operator
    """
    member, membership = approve_member_with_membership(full_name="Rb Member")

    refused = api_client.create_membership(
        {"member_id": member["id"], "department_code": "OPS", "tier": "PLUS", "primary_flag": False},
        OPERATOR,
    )

    assert refused.status_code == 403, (
        f"Membership creation is a UniversityAccountAdmin exclusive operation, got "
        f"{refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_FORBIDDEN", (
        f"Got {refused.json()['data']['error_id']}"
    )
    rows = validate_success(api_client.list_member_memberships(member["id"], OPERATOR), 200)
    assert len(rows) == 1, f"Only the auto-created membership exists, got {len(rows)} rows"


def test_a_member_cannot_return_another_members_reservation():
    """PRD §2.1: "a `Member` acting on a member-scoped resource must have `X-User-ID` equal to
    the owning `Member.id` of the target resource, or of the target resource's parent chain,
    and every such mismatch is rejected with `ERR_FORBIDDEN`."
    PRD §3.8: "The return is the member's own gesture and only the booking member may perform
    it."

    Design: Corner/rbac/member_cannot_return_another_members_reservation
    """
    owner, owner_membership = approve_member_with_membership(full_name="Owner One")
    other, other_membership = approve_member_with_membership(full_name="Owner Two")
    pod = create_pod(name="Owner Lot", site_type="CAMPUS", capacity=4)
    vehicle = create_vehicle(pod["id"], vin="VIN3158OWNER")
    reservation = create_reservation(owner["id"], pod["id"], vehicle["id"], vehicle["version"])
    start_trip(owner["id"], reservation["id"], method="APP")

    refused = api_client.return_reservation(
        reservation["id"],
        {
            "returned_pod_id": pod["id"],
            "returned_odometer_miles": 50000,
            "returned_fuel_level_pct": 60,
            "contamination_level": 0,
        },
        make_member_headers(other["id"]),
    )

    assert refused.status_code == 403, (
        f"The ownership test refuses a non-owner Member with 403, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_FORBIDDEN", (
        f"Got {refused.json()['data']['error_id']}"
    )
    after = validate_success(api_client.get_reservation(reservation["id"], OPERATOR), 200)
    assert after["status"] == "IN_USE", (
        f"The refused return leaves the owner's trip open, got {after['status']}"
    )