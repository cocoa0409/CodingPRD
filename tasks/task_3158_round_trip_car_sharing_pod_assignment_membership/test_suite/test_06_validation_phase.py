"""Validation conflict resolution and the fixed precedence order."""
from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATOR,
    PLATFORM,
    api_client,
    approve_member_with_membership,
    create_pod,
    create_reservation,
    create_vehicle,
    get_success_data,
    make_member_headers,
    open_incident,
    setup_confirmed_reservation,
    start_trip,
    validate_success,
)


def test_state_check_outranks_the_screening_and_return_pod_checks():
    """PRD §2.12: "The authentication checks run first: header presence and declared-role
    membership (`ERR_UNAUTHENTICATED`), then the role-permission and ownership test
    (`ERR_FORBIDDEN`). Next come the existence checks: field presence, declared type and enum
    membership (`ERR_INVALID_REQUEST`), then left-to-right path resolution"
    PRD §2.12: "then the declared-transition guard (`ERR_INVALID_STATE`), then segregation of
    duties (`ERR_SEGREGATION_OF_DUTIES`), then the screening outcome guard
    (`ERR_SCREENING_NOT_CLEAR`)"
    PRD §2.12: "then the return-pod guard (`ERR_WRONG_RETURN_POD`)"

    Design: Difficulty/priority_pair_validation_conflict/pair_state_versus_business_safety_on_return
    """
    setup = setup_confirmed_reservation(pod_name="Campus Prio")
    other_pod = create_pod(name="Campus Prio Two", site_type="CAMPUS", capacity=4)

    # Record a non-CLEAR outcome for the member who still holds the CONFIRMED
    # trip. PRD §3.1 permits a decision to be recorded on any report row the
    # screener is handed, and the resulting Member.screen_result is what the
    # screening guard of §2.12 reads, so no second submission (which a live
    # SUBMITTED report would refuse with ERR_DRIVING_RECORD_PENDING) is needed.
    report = get_success_data(
        api_client.list_member_reports(setup["member"]["id"], OPERATOR),
        200,
    )[0]
    get_success_data(
        api_client.record_report_decision(
            report["id"], {"report_decision": "REFERRED"}, OPERATOR
        ),
        200,
    )

    refused = api_client.return_reservation(
        setup["reservation"]["id"],
        {
            "returned_pod_id": other_pod["id"],
            "returned_odometer_miles": 41000,
            "returned_fuel_level_pct": 50,
            "contamination_level": 0,
        },
        make_member_headers(setup["member"]["id"]),
    )

    assert refused.status_code == 409, (
        f"The state check owns this conflict and reports 409, got {refused.status_code}"
    )
    error_id = refused.json()["data"]["error_id"]
    assert error_id == "ERR_INVALID_STATE", (
        f"The undeclared from-state must win over both business-safety checks, got {error_id}"
    )
    assert error_id != "ERR_SCREENING_NOT_CLEAR", (
        "The screening guard sits below the declared-transition guard"
    )
    assert error_id != "ERR_WRONG_RETURN_POD", (
        "The return-pod guard sits far below the declared-transition guard"
    )
    reservation = validate_success(
        api_client.get_reservation(setup["reservation"]["id"], OPERATOR), 200
    )
    assert reservation["status"] == "CONFIRMED", (
        f"A refused return leaves the reservation untouched, got {reservation['status']}"
    )


def test_screening_guard_outranks_the_return_pod_guard():
    """PRD §2.12: "then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then the screening
    outcome guard (`ERR_SCREENING_NOT_CLEAR`), then application approval
    (`ERR_APPLICATION_NOT_APPROVED`)"
    PRD §2.12: "then the return-pod guard (`ERR_WRONG_RETURN_POD`), then the odometer-regression
    guard (`ERR_ODOMETER_REGRESSION`)"

    Design: Difficulty/priority_pair_validation_conflict/pair_state_versus_business_safety_on_return
    """
    setup = setup_confirmed_reservation(pod_name="Screening Prior Pod")
    start_trip(setup["member"]["id"], setup["reservation"]["id"], method="APP")

    # PRD §2.13's ordering puts the screening-outcome guard above the return-pod
    # guard, so the member's recorded outcome is what the conflict is built on.
    # PRD §3.1: at most one non-terminal report may exist per member, so the
    # decision is re-recorded on the existing report row rather than submitted
    # again (which a live SUBMITTED report would refuse with
    # ERR_DRIVING_RECORD_PENDING).
    report = get_success_data(
        api_client.list_member_reports(setup["member"]["id"], OPERATOR),
        200,
    )[0]
    get_success_data(
        api_client.record_report_decision(
            report["id"], {"report_decision": "REFERRED"}, OPERATOR
        ),
        200,
    )

    refused = api_client.return_reservation(
        setup["reservation"]["id"],
        {
            "returned_pod_id": setup["pod"]["id"],
            "returned_odometer_miles": 41000,
            "returned_fuel_level_pct": 50,
            "contamination_level": 0,
        },
        make_member_headers(setup["member"]["id"]),
    )

    assert refused.status_code == 422, (
        f"The screening guard owns this conflict and reports 422, got {refused.status_code}"
    )
    error_id = refused.json()["data"]["error_id"]
    assert error_id == "ERR_SCREENING_NOT_CLEAR", (
        f"The screening guard sits above the return-pod guard; got {error_id}"
    )
    assert error_id != "ERR_WRONG_RETURN_POD", (
        "The return-pod guard sits below the screening guard"
    )
    reservation = validate_success(
        api_client.get_reservation(setup["reservation"]["id"], OPERATOR), 200
    )
    assert reservation["status"] == "IN_USE", (
        f"The declared transition was available, so the trip stays open; got "
        f"{reservation['status']}"
    )


def test_unknown_incident_path_is_resolved_before_the_fiscal_check():
    """PRD §2.11: "A request that names a member that does not exist is answered with
    `ERR_MEMBER_NOT_FOUND` before the server even attempts to resolve anything nested beneath
    that member."
    PRD §2.12: "After existence comes the wallet-residual release guard
    (`ERR_ALREADY_RELEASED`)"
    PRD §2.12: "then the pod-capacity guard (`ERR_POD_CAPACITY_EXCEEDED`), then insufficient
    wallet credit (`ERR_INSUFFICIENT_WALLET_CREDIT`)"

    Design: Difficulty/priority_pair_validation_conflict/pair_existence_versus_business_fiscal_on_waive
    """
    # PRD §3.13: the raw score is T1 + T2 + T3 and the high-severity branch fires at 4,
# so an anchor of 2 with a repair cost at or above the 10000-cent term is what
# leaves the incident charged for the refused waiver to be observed against.
    member, membership = approve_member_with_membership(full_name="Ravi Referential",
                                                        last_accident_fee_block=2)
    pod = create_pod(name="Campus Referential", site_type="CAMPUS", capacity=4)
    vehicle = create_vehicle(pod["id"])
    reservation = create_reservation(member["id"], pod["id"], vehicle["id"], vehicle["version"])
    incident = open_incident(
        reservation["id"], vehicle["id"], member["id"], repair_cost_cents=12000
    )
    get_success_data(api_client.set_clock("2026-09-05T10:00:00Z", PLATFORM), 200)
    # PRD §2.10: the split is version-guarded, so the version it must carry is the
    # one persisted at request entry — the clock advance already re-derived the
    # incident and advanced it past the creation-time value.
    current = validate_success(api_client.get_incident(incident["id"], OPERATOR), 200)

    split = validate_success(
        api_client.party_split(
            incident["id"], {"expected_incident_version": current["version"]}, OPERATOR
        ),
        200,
    )
    assert split["status"] == "FEE_CHARGED", (
        f"A raw score of 4 takes the high-severity branch and leaves the incident charged, "
        f"got {split['status']}"
    )

    refused = api_client.waive_incident_fee(
        NON_EXISTENT_UUID, {"reason": "GOODWILL"}, OPERATOR
    )

    assert refused.status_code == 404, (
        f"Existence is resolved in the path before any fiscal check, got {refused.status_code}"
    )
    error_id = refused.json()["data"]["error_id"]
    assert error_id == "ERR_INCIDENT_NOT_FOUND", (
        f"An unknown incident id returns the incident not-found error, got {error_id}"
    )
    assert error_id != "ERR_INSUFFICIENT_WALLET_CREDIT", (
        "The fiscal guard sits below the existence checks"
    )
    incident_after = validate_success(api_client.get_incident(incident["id"], OPERATOR), 200)
    assert incident_after["status"] == "FEE_CHARGED", (
        f"The charged incident is unaffected by the refused waiver, got {incident_after['status']}"
    )


def test_unauthorised_party_split_is_refused_before_segregation_of_duties():
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries a value that is not
    one of the declared roles below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.12: "Because the segregation-of-duties guard sits below the existence and state
    checks but above the business-safety gates, an operator who both raised and attempts to
    split an incident over which they hold no authorisation still sees `ERR_FORBIDDEN`, while
    an authorised operator acting on their own incident sees `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/pair_existence_versus_business_fiscal_on_waive
    """
    member, membership = approve_member_with_membership(full_name="Auth Split")
    pod = create_pod(name="Auth Lot", site_type="CAMPUS", capacity=4)
    vehicle = create_vehicle(pod["id"])
    reservation = create_reservation(member["id"], pod["id"], vehicle["id"], vehicle["version"])
    incident = open_incident(
        reservation["id"], vehicle["id"], member["id"], repair_cost_cents=4000
    )

    refused = api_client.party_split(
        incident["id"], {"expected_incident_version": incident["version"]},
        {"X-User-ID": "", "X-User-Role": "ScreeningBot"},
    )

    assert refused.status_code == 401, (
        f"A role outside the declared set is refused with 401, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED", (
        f"The header-presence check runs before the segregation-of-duties check, got "
        f"{refused.json()['data']['error_id']}"
    )
    incident_after = validate_success(api_client.get_incident(incident["id"], OPERATOR), 200)
    assert incident_after["status"] == "OPEN", (
        f"A refused split leaves the incident OPEN, got {incident_after['status']}"
    )