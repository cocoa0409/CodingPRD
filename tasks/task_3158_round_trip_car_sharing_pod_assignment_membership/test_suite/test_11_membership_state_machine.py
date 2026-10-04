"""Membership and member state-machine corners."""
from test_helpers import (
    OPERATOR,
    api_client,
    approve_member_with_membership,
    create_pod,
    create_vehicle,
    get_success_data,
    make_account_admin_headers,
    make_member_headers,
    setup_confirmed_reservation,
    validate_success,
)
from test_helpers.fixtures import ACCOUNT_ADMIN, FLEET


def _create_membership_via_admin(member_id, account_id, tier, primary_flag):
    """Add a membership under an account as its UniversityAccountAdmin (PRD §3.3)."""
    payload = {"member_id": member_id, "tier": tier, "primary_flag": primary_flag}
    if account_id is not None:
        payload["account_id"] = account_id
    res = api_client.create_membership(payload, ACCOUNT_ADMIN)
    return get_success_data(res, 201)


def test_return_attempted_from_confirmed_is_an_undeclared_transition():
    """PRD §3.8: "A reservation that already sits in the terminal posture this operation
    produces is refused with `ERR_ALREADY_TERMINAL` (HTTP 409) before any other business check,
    and a reservation whose status admits no declared return edge is refused with
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.8: "The declared return edge on the reservation runs from `IN_USE` to `RETURNED`"

    Design: Corner/state_machines/return_reservation_from_confirmed_returns_invalid_state
    """
    setup = setup_confirmed_reservation(pod_name="Too Early Lot")

    refused = api_client.return_reservation(
        setup["reservation"]["id"],
        {
            "returned_pod_id": setup["pod"]["id"],
            "returned_odometer_miles": 33000,
            "returned_fuel_level_pct": 60,
            "contamination_level": 0,
        },
        make_member_headers(setup["member"]["id"]),
    )

    assert refused.status_code == 409, (
        f"CONFIRMED admits no return edge, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_INVALID_STATE", (
        f"Got {refused.json()['data']['error_id']}"
    )
    reservation = validate_success(
        api_client.get_reservation(setup["reservation"]["id"], OPERATOR), 200
    )
    assert reservation["status"] == "CONFIRMED", (
        f"The refused return leaves the reservation untouched, got {reservation['status']}"
    )
    vehicle = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    assert vehicle["use_status"] == "RESERVED", (
        f"The vehicle posture is untouched by the refusal, got {vehicle['use_status']}"
    )


def test_adding_a_second_active_primary_after_a_close_is_individually_valid():
    """PRD §3.3: "The `tier` is one of `STANDARD`, `PLUS`, `PREMIUM` or `FROZEN`"
    PRD §3.3: "A new membership is born in `ACTIVE`."

    Design: Corner/validations/duplicate_primary_membership_second_row_rejected
    """
    member, membership = approve_member_with_membership(full_name="Group Primary")
    account = get_success_data(
        api_client.create_account(
            {
                "name": "Group University",
                "type": "UNIVERSITY",
                "primary_member_id": member["id"],
                "billing_email": "billing@group.edu",
            },
            {"X-User-ID": "anon-group", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
        ),
        201,
    )

    sponsored = _create_membership_via_admin(
        member["id"], account_id=account["id"], tier="PLUS", primary_flag=False
    )

    assert sponsored["status"] == "ACTIVE", (
        f"A new membership is born ACTIVE, got {sponsored['status']}"
    )
    assert sponsored["tier"] == "PLUS", (
        f"The supplied tier is stored verbatim, got {sponsored['tier']}"
    )
    assert sponsored["primary_flag"] is False, (
        "A non-primary row is individually valid alongside the existing primary membership"
    )
    rows = validate_success(api_client.list_member_memberships(member["id"], OPERATOR), 200)
    assert len(rows) == 2, (
        f"Both memberships coexist because only one is primary; got {len(rows)} rows"
    )


def test_decision_on_an_applied_application_is_an_undeclared_transition():
    """PRD §3.1: "Approval is the only path to booking rights. Four conditions must hold, and
    they are evaluated in a fixed order: first, the application posture must be `SCREENING` —
    any other posture is refused with `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/application_decision_before_screening_returns_invalid_state
    """
    member = get_success_data(
        api_client.register_member(
            {"full_name": "Ines Instate", "email": "ines.instate@x.com", "kind": "INDIVIDUAL"},
            {"X-User-ID": "anon-ines", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
        ),
        201,
    )

    refused = api_client.decide_application(
        member["id"], {"decision": "APPROVE"}, OPERATOR
    )

    assert refused.status_code == 409, (
        f"An APPLIED application admits no decision edge, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_INVALID_STATE", (
        f"Got {refused.json()['data']['error_id']}"
    )
    after = validate_success(api_client.get_member(member["id"], OPERATOR), 200)
    assert after["application_status"] == "APPLIED", (
        f"The refused decision leaves the posture untouched, got {after['application_status']}"
    )
    memberships = validate_success(api_client.list_member_memberships(member["id"], OPERATOR), 200)
    assert memberships == [], (
        f"No membership may be created by a refused decision, got {memberships}"
    )


def test_hold_confirmation_against_an_unavailable_vehicle_is_refused():
    """PRD §3.6: "the requested vehicle's `use_status` to be `AVAILABLE`"
    PRD §2.5: "A vehicle must itself be in the `AVAILABLE` posture before it will accept a
    reservation. Any other `use_status` freezes the vehicle to new reservations and is refused
    with `ERR_VEHICLE_NOT_AVAILABLE` (HTTP 409)."

    Design: Corner/state_machines/hold_confirmation_blocked_by_unavailable_vehicle
    """
    member, membership = approve_member_with_membership(full_name="Uri Unavail")
    pod = create_pod(name="Unavail Lot", site_type="CAMPUS", capacity=3)
    vehicle = create_vehicle(pod["id"])
    unavailable = validate_success(
        api_client.post_availability_event(
            vehicle["id"], {"event": "OUT_OF_SERVICE"}, OPERATOR
        ),
        200,
    )
    assert unavailable["use_status"] == "OUT_OF_SERVICE", (
        f"The availability event takes the vehicle out of service, got {unavailable['use_status']}"
    )

    refused = api_client.create_reservation(
        {
            "member_id": member["id"],
            "pod_id": pod["id"],
            "vehicle_id": vehicle["id"],
            "start_at": "2026-09-05T09:00:00Z",
            "end_at": "2026-09-05T13:00:00Z",
            "reserved_hours": 4,
            "expected_vehicle_version": unavailable["version"],
        },
        make_member_headers(member["id"]),
    )

    assert refused.status_code == 409, (
        f"Expected HTTP 409 for a non-AVAILABLE vehicle, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_VEHICLE_NOT_AVAILABLE", (
        f"Got {refused.json()['data']['error_id']}"
    )
    reservations = validate_success(
        api_client.list_reservations(OPERATOR, {"member_id": member["id"]}), 200
    )
    assert reservations == [], (
        f"A refused booking creates no reservation row, got {len(reservations)} rows"
    )


def test_second_active_primary_membership_is_refused_collectively():
    """PRD §3.3: "The `primary_flag` defaults to false and marks whether the membership is the
    member's primary, billable membership — exactly one `ACTIVE` primary membership may exist
    per member at a time. A creation that would leave a second `ACTIVE` primary membership for
    the same member is refused with `ERR_DUPLICATE_PRIMARY_MEMBERSHIP` (HTTP 409)."

    Design: Corner/validations/duplicate_primary_membership_second_row_rejected
    """
    member, membership = approve_member_with_membership(full_name="Prim Primary")

    refused = api_client.create_membership(
        {
            "member_id": member["id"],
            "department_code": "OPS",
            "tier": "PLUS",
            "primary_flag": True,
        },
        ACCOUNT_ADMIN,
    )

    assert refused.status_code == 409, (
        f"A second ACTIVE primary membership is refused with 409, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_DUPLICATE_PRIMARY_MEMBERSHIP", (
        f"Got {refused.json()['data']['error_id']}"
    )
    rows = validate_success(api_client.list_member_memberships(member["id"], OPERATOR), 200)
    assert len(rows) == 1, (
        f"Each membership row is individually valid but the aggregate is refused, so exactly "
        f"one row must remain; got {len(rows)}"
    )
    assert rows[0]["tier"] == "STANDARD", (
        f"The auto-created primary membership keeps its tier, got {rows[0]['tier']}"
    )


def test_membership_creation_for_a_referred_member_is_refused():
    """PRD §3.1: "third, `ERR_SCREENING_NOT_CLEAR` (HTTP 422) is returned when the recorded
    outcome is `REFERRED` or `FAILED`, because only a `CLEAR` outcome permits a positive
    decision"
    PRD §3.3: "A creation that would leave a second `ACTIVE` primary membership for the same
    member is refused with `ERR_DUPLICATE_PRIMARY_MEMBERSHIP` (HTTP 409)."

    Design: Corner/validations/screening_not_clear_blocks_membership_creation
    """
    primary = get_success_data(
        api_client.register_member(
            {"full_name": "Referral Admin", "email": "referral.admin@x.com", "kind": "INDIVIDUAL"},
            {"X-User-ID": "anon-refadmin", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
        ),
        201,
    )
    account = get_success_data(
        api_client.create_account(
            {
                "name": "Referral University",
                "type": "UNIVERSITY",
                "primary_member_id": primary["id"],
                "billing_email": "billing@refu.edu",
            },
            {"X-User-ID": "anon-refu", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
        ),
        201,
    )
    # The account's primary member is an APPROVED INDIVIDUAL, so their own
# auto-created primary membership already occupies the member's single ACTIVE
# primary slot (PRD §3.3). The administrator's row for them is therefore raised
# non-primary, which is what leaves the screening gate as the only possible
# refusal and keeps the account-scoped ownership test satisfied.
    primary_report = get_success_data(
        api_client.submit_driving_record_report(
            primary["id"], {"license_state": "CA", "license_years_held": 9},
            make_member_headers(primary["id"]),
        ),
        201,
    )
    get_success_data(
        api_client.record_report_decision(
            primary_report["id"], {"report_decision": "CLEAR"}, OPERATOR
        ),
        200,
    )
    get_success_data(
        api_client.decide_application(primary["id"], {"decision": "APPROVE"}, OPERATOR), 200
    )
    get_success_data(
        api_client.create_membership(
            {
                "account_id": account["id"],
                "member_id": primary["id"],
                "department_code": "ADMIN",
                "tier": "STANDARD",
                "primary_flag": False,
            },
            make_account_admin_headers(account["id"]),
        ),
        201,
    )

    member = get_success_data(
        api_client.register_member(
            {"full_name": "Ref Referred", "email": "ref.referred@x.com", "kind": "STUDENT"},
            {"X-User-ID": "anon-ref", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
        ),
        201,
    )
    report = get_success_data(
        api_client.submit_driving_record_report(
            member["id"], {"license_state": "CA", "license_years_held": 2},
            make_member_headers(member["id"]),
        ),
        201,
    )
    get_success_data(
        api_client.record_report_decision(
            report["id"], {"report_decision": "REFERRED"}, OPERATOR
        ),
        200,
    )
    member_after = validate_success(api_client.get_member(member["id"], OPERATOR), 200)
    assert member_after["screen_result"] == "REFERRED", (
        f"The recording copies the decision onto the member, got {member_after['screen_result']}"
    )
    assert member_after["application_status"] == "SCREENING", (
        f"A REFERRED screening leaves the application in screening, got "
        f"{member_after['application_status']}"
    )

    refused = api_client.create_membership(
        {
            "account_id": account["id"],
            "member_id": member["id"],
            "department_code": "PHYS",
            "tier": "STANDARD",
            "primary_flag": False,
        },
        make_account_admin_headers(account["id"]),
    )

    assert refused.status_code == 422, (
        f"A REFERRED screening blocks membership creation with 422, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_SCREENING_NOT_CLEAR", (
        f"Got {refused.json()['data']['error_id']}"
    )
    # PRD §4 authorizes `GET /car-share/memberships` for UniversityAccountAdmin and
    # FleetAdmin, so the read-back is made by the fleet administrator.
    memberships = validate_success(
        api_client.list_memberships(FLEET, {"member_id": member["id"]}), 200
    )
    assert memberships == [], f"No membership row is created, got {len(memberships)}"

def test_blocking_maintenance_order_marks_the_vehicle_maintenance_and_blocks_new_holds():
    """PRD §3.12: "A blocking order moves straight into `BLOCKED` and takes the vehicle with
    it: the order requires that no reservation of the vehicle in `CONFIRMED`, `IN_USE` or
    `OVERDUE` overlaps its window"
    PRD §2.5: "A vehicle must itself be in the `AVAILABLE` posture before it will accept a
    reservation. Any other `use_status` freezes the vehicle to new reservations and is refused
    with `ERR_VEHICLE_NOT_AVAILABLE` (HTTP 409)."

    Design: Corner/endpoints/maintenance_order_creation_side_effect_marks_vehicle_maintenance
    """
    member, membership = approve_member_with_membership(full_name="Block Member")
    pod = create_pod(name="Block Lot", site_type="CAMPUS", capacity=3)
    vehicle = create_vehicle(pod["id"])

    order = validate_success(
        api_client.create_maintenance_order(
            {
                "vehicle_id": vehicle["id"],
                "reason": "TYRE_ROTATION",
                "blocking": True,
                "scheduled_start": "2026-09-13T09:00:00Z",
                "scheduled_end": "2026-09-13T11:00:00Z",
            },
            OPERATOR,
        ),
        201,
    )

    assert order["status"] == "BLOCKED", (
        f"A blocking order is born BLOCKED rather than SCHEDULED, got {order['status']}"
    )
    assert order["pod_id"] == pod["id"], (
        f"The order's pod is read from the vehicle, got {order['pod_id']}"
    )
    vehicle_after = validate_success(api_client.get_vehicle(vehicle["id"], OPERATOR), 200)
    assert vehicle_after["use_status"] == "MAINTENANCE", (
        f"The blocking order takes the vehicle to MAINTENANCE, got {vehicle_after['use_status']}"
    )

    refused = api_client.create_reservation(
        {
            "member_id": member["id"],
            "pod_id": pod["id"],
            "vehicle_id": vehicle["id"],
            "start_at": "2026-09-14T09:00:00Z",
            "end_at": "2026-09-14T13:00:00Z",
            "reserved_hours": 4,
            "expected_vehicle_version": vehicle_after["version"],
        },
        make_member_headers(member["id"]),
    )
    assert refused.status_code == 409, (
        f"A MAINTENANCE vehicle freezes new reservations, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_VEHICLE_NOT_AVAILABLE", (
        f"Got {refused.json()['data']['error_id']}"
    )
