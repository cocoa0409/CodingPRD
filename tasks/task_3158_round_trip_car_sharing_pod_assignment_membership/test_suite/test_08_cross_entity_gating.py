"""Cross-entity gating: booking rights depend on the member and membership postures."""
from test_helpers import (
    OPERATOR,
    api_client,
    approve_member_with_membership,
    assert_member,
    assert_membership,
    create_pod,
    create_vehicle,
    get_success_data,
    make_member_headers,
    validate_success,
)


def test_suspended_membership_blocks_booking_even_though_the_member_is_approved():
    """PRD §2.5: "an operation that needs a live membership and finds none in `ACTIVE` is
    refused with `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP 409)"
    PRD §3.4: "a suspension leaves every existing reservation of that member intact —
    `SUSPENDED` blocks new bookings only."

    Design: Difficulty/cross_entity_state_dependency/reservation_gated_by_member_application_and_membership
    """
    member, membership = approve_member_with_membership(full_name="Gabe Gated")
    suspended = validate_success(api_client.suspend_membership(membership["id"], OPERATOR), 200)
    assert suspended["status"] == "SUSPENDED", (
        f"A PodOperator suspends an ACTIVE primary membership, got {suspended['status']}"
    )
    pod = create_pod(name="Campus Gated", site_type="CAMPUS", capacity=4)
    vehicle = create_vehicle(pod["id"])

    refused = api_client.create_reservation(
        {
            "member_id": member["id"],
            "pod_id": pod["id"],
            "vehicle_id": vehicle["id"],
            "start_at": "2026-09-05T09:00:00Z",
            "end_at": "2026-09-05T13:00:00Z",
            "reserved_hours": 4,
            "expected_vehicle_version": vehicle["version"],
        },
        make_member_headers(member["id"]),
    )

    assert refused.status_code == 409, (
        f"Expected HTTP 409 for a membership that is not ACTIVE, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_MEMBERSHIP_NOT_ACTIVE", (
        f"Got {refused.json()['data']['error_id']}"
    )
    member_after = validate_success(api_client.get_member(member["id"], OPERATOR), 200)
    assert_member(member_after)
    assert member_after["application_status"] == "APPROVED", (
        f"The approval is untouched by the suspension, got {member_after['application_status']}"
    )
    membership_after = validate_success(api_client.get_membership(membership["id"], OPERATOR), 200)
    assert_membership(membership_after)


def test_application_still_in_screening_is_refused_at_the_booking_path():
    """PRD §2.5: "Booking rights do not follow from registration. A member acquires them only
    when their `application_status` reaches `APPROVED`. The application posture is one of
    `APPLIED`, `SCREENING`, `APPROVED` or `DECLINED`, and a member in any posture other than
    `APPROVED` is refused at every booking path with `ERR_APPLICATION_NOT_APPROVED`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/reservation_gated_by_member_application_and_membership
    """
    member = get_success_data(
        api_client.register_member(
            {"full_name": "Screening Sam", "email": "screening.sam@x.com", "kind": "INDIVIDUAL"},
            {"X-User-ID": "anon-sam", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
        ),
        201,
    )
    report = get_success_data(
        api_client.submit_driving_record_report(
            member["id"], {"license_state": "CA", "license_years_held": 8},
            make_member_headers(member["id"]),
        ),
        201,
    )
    get_success_data(
        api_client.record_report_decision(report["id"], {"report_decision": "CLEAR"}, OPERATOR), 200
    )
    pod = create_pod(name="Campus Screening", site_type="CAMPUS", capacity=4)
    vehicle = create_vehicle(pod["id"])

    refused = api_client.create_reservation(
        {
            "member_id": member["id"],
            "pod_id": pod["id"],
            "vehicle_id": vehicle["id"],
            "start_at": "2026-09-05T09:00:00Z",
            "end_at": "2026-09-05T13:00:00Z",
            "reserved_hours": 4,
            "expected_vehicle_version": vehicle["version"],
        },
        make_member_headers(member["id"]),
    )

    assert refused.status_code == 409, (
        f"Expected HTTP 409 while the application is not APPROVED, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_APPLICATION_NOT_APPROVED", (
        f"Got {refused.json()['data']['error_id']}"
    )
    after = validate_success(api_client.get_member(member["id"], OPERATOR), 200)
    assert after["application_status"] == "SCREENING", (
        f"The refused booking must not advance the application, got {after['application_status']}"
    )
    assert after["screen_result"] == "CLEAR", (
        f"The recorded decision is visible on the member, got {after['screen_result']}"
    )


def test_occupancy_change_is_visible_in_the_response_that_caused_it():
    """PRD §2.8: "A single logical event may mutate several rows. Each such row independently
    refreshes its own `updated_at` and increments its own `version`; the increments are
    per-row and are never shared, coalesced or skipped."
    PRD §3.6: "the booking pod's `utilization_score` and `available_bays` are recomputed."
    PRD §2.4: "Both are read-only computed fields and both are response-visible on every pod
    payload."

    Design: Corner/consistency_model/immediate_visibility_of_derived_fields_in_same_response
    """
    member, membership = approve_member_with_membership(full_name="Immediate Member")
    pod = create_pod(name="Immediate Lot", site_type="CAMPUS", capacity=3)
    vehicle = create_vehicle(pod["id"])

    confirmed = validate_success(
        api_client.create_reservation(
            {
                "member_id": member["id"],
                "pod_id": pod["id"],
                "vehicle_id": vehicle["id"],
                "start_at": "2026-09-05T09:00:00Z",
                "end_at": "2026-09-05T13:00:00Z",
                "reserved_hours": 4,
                "expected_vehicle_version": vehicle["version"],
            },
            make_member_headers(member["id"]),
        ),
        201,
    )
    assert confirmed["status"] == "CONFIRMED", (
        f"The confirmation cascade takes the reservation to CONFIRMED, got {confirmed['status']}"
    )

    pod_after = validate_success(api_client.get_pod(pod["id"], OPERATOR), 200)
    vehicle_after = validate_success(api_client.get_vehicle(vehicle["id"], OPERATOR), 200)
    assert pod_after["available_bays"] == 2, (
        f"The pod's bay accounting must already reflect the new occupancy, got "
        f"{pod_after['available_bays']}"
    )
    assert vehicle_after["use_status"] == "RESERVED", (
        f"The confirmed reservation takes the vehicle, got {vehicle_after['use_status']}"
    )