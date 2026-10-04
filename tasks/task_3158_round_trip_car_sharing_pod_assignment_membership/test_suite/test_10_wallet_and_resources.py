"""The conserved wallet ledger and resource-scoped reads."""
from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATOR,
    PLATFORM,
    api_client,
    approve_member_with_membership,
    assert_fuel_transaction,
    assert_member,
    assert_pod,
    create_pod,
    create_reservation,
    create_vehicle,
    get_success_data,
    make_member_headers,
    return_vehicle,
    setup_confirmed_reservation,
    post_fuel_transaction,
    start_trip,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import FLEET


def test_hold_release_returns_exactly_what_the_confirmation_reserved():
    """PRD §3.6: "The member's `wallet_hold_cents` is credited by 2000 cents, with the
    reservation hold recorded as its named hold source."
    PRD §2.6: "Money moves between them; it is never deleted. When a reservation is created,
    the member's hold is credited with the reservation hold; when the reservation is closed,
    the hold is credited back to the spendable balance and the hold is zeroed, exactly once
    per reservation."

    Design: Difficulty/compensating_invariant/wallet_credit_and_hold_conservation
    """
    setup = setup_confirmed_reservation(pod_name="Campus Conservation")
    held = validate_success(api_client.get_member(setup["member"]["id"], OPERATOR), 200)
    assert held["wallet_hold_cents"] == 2000, (
        f"Confirming a reservation reserves the named 2000-cent hold, got "
        f"{held['wallet_hold_cents']}"
    )

    start_trip(setup["member"]["id"], setup["reservation"]["id"])
    post_fuel_transaction(setup["member"]["id"], setup["reservation"]["id"], setup["vehicle"]["id"])
    return_vehicle(
        setup["member"]["id"], setup["reservation"]["id"], setup["pod"]["id"],
        odometer_miles=41000, fuel_level_pct=80,
    )
    closed = validate_success(
        api_client.close_reservation(
            setup["reservation"]["id"], make_member_headers(setup["member"]["id"])
        ),
        200,
    )

    assert closed["status"] == "CLOSED", (
        f"The close hop lands on CLOSED, got {closed['status']}"
    )
    released = validate_success(api_client.get_member(setup["member"]["id"], OPERATOR), 200)
    assert_member(released)
    assert released["wallet_hold_cents"] == 0, (
        f"The hold is zeroed on close, got {released['wallet_hold_cents']}"
    )
    assert released["wallet_credit_cents"] == 2000, (
        f"Exactly the 2000 reserved is re-credited to the spendable balance, got "
        f"{released['wallet_credit_cents']}"
    )


def test_a_reservation_cannot_be_closed_twice_without_double_crediting():
    """PRD §3.11: "It then credits the member's `wallet_credit_cents` by the member's
    `wallet_hold_cents` and sets `wallet_hold_cents` to 0, so the amount reserved at booking
    is released back to the spendable balance exactly once per reservation."
    PRD §3.11: "A reservation that is already `CLOSED` is refused with `ERR_ALREADY_TERMINAL`
    (HTTP 409)"

    Design: Corner/state_machines/double_close_of_reservation_returns_already_terminal
    """
    setup = setup_confirmed_reservation(pod_name="Double Lot")
    start_trip(setup["member"]["id"], setup["reservation"]["id"])
    post_fuel_transaction(setup["member"]["id"], setup["reservation"]["id"], setup["vehicle"]["id"])
    return_vehicle(
        setup["member"]["id"], setup["reservation"]["id"], setup["pod"]["id"],
        odometer_miles=34000, fuel_level_pct=55,
    )
    first = validate_success(
        api_client.close_reservation(
            setup["reservation"]["id"], make_member_headers(setup["member"]["id"])
        ),
        200,
    )
    assert first["status"] == "CLOSED", f"The first close lands on CLOSED, got {first['status']}"

    refused = api_client.close_reservation(
        setup["reservation"]["id"], make_member_headers(setup["member"]["id"])
    )

    assert refused.status_code == 409, (
        f"A repeat close observes the terminal posture and is refused with 409, got "
        f"{refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_ALREADY_TERMINAL", (
        f"Got {refused.json()['data']['error_id']}"
    )
    after = validate_success(api_client.get_member(setup["member"]["id"], OPERATOR), 200)
    assert after["wallet_hold_cents"] == 0, (
        f"The hold is not re-released by the refused call, got {after['wallet_hold_cents']}"
    )
    assert after["wallet_credit_cents"] == 2000, (
        f"The spendable balance is credited exactly once, so the refused repeat adds nothing; "
        f"got {after['wallet_credit_cents']}"
    )


def test_low_severity_split_leaves_the_conserved_wallet_total_untouched():
    """PRD §3.13: "On this branch the incident's `severity_fee_cents` is 1500 cents multiplied
    by the member's `last_accident_fee_block`, plus 1500 cents multiplied by the third severity
    term minus 2 when that difference is positive and zero otherwise"
    PRD §2.6: "Because the quantity is conserved, no operation may leave a member with a
    negative spendable balance"

    Design: Difficulty/compensating_invariant/wallet_credit_and_hold_conservation
    """
    member, membership = approve_member_with_membership(full_name="Ivan Invariant")
    pod = create_pod(name="Campus Conservation II", site_type="CAMPUS", capacity=4)
    vehicle = create_vehicle(pod["id"])
    reservation = create_reservation(member["id"], pod["id"], vehicle["id"], vehicle["version"])
    start_trip(member["id"], reservation["id"])
    post_fuel_transaction(member["id"], reservation["id"], vehicle["id"], amount_cents=3600)
    get_success_data(api_client.set_clock("2026-09-05T10:00:00Z", PLATFORM), 200)
    return_vehicle(member["id"], reservation["id"], pod["id"],
                   odometer_miles=39000, fuel_level_pct=80)
    incident = get_success_data(
        api_client.create_incident(
            {
                "reservation_id": reservation["id"],
                "vehicle_id": vehicle["id"],
                "member_id": member["id"],
                "incident_type": "DAMAGE",
                "repair_cost_cents": 6000,
            },
            OPERATOR,
        ),
        201,
    )
    closed = validate_success(
        api_client.close_reservation(reservation["id"], make_member_headers(member["id"])),
        200,
    )
    assert closed["status"] == "CLOSED", f"The close hop lands on CLOSED, got {closed['status']}"

    split = validate_success(
        api_client.party_split(
            incident["id"], {"expected_incident_version": incident["version"]}, OPERATOR
        ),
        200,
    )

    assert split["status"] == "CLOSED", (
        f"A raw score of 1 takes the low-severity branch, got {split['status']}"
    )
    assert split["severity_fee_cents"] == 0, (
        f"With no prior at-fault block the low-severity branch amount is zero, got "
        f"{split['severity_fee_cents']}"
    )
    after = validate_success(api_client.get_member(member["id"], OPERATOR), 200)
    assert after["wallet_hold_cents"] == 0, (
        f"The hold was released by the close, got {after['wallet_hold_cents']}"
    )
    assert after["wallet_credit_cents"] == 2000, (
        f"The total returns exactly to the released 2000 because the incident close credits "
        f"nothing; got {after['wallet_credit_cents']}"
    )


def test_wallet_adjustment_of_zero_is_refused_and_positive_amount_is_accepted():
    """PRD §3.14: "An adjustment is refused with `ERR_WALLET_ADJUSTMENT_INVALID` (HTTP 422)
    when the requested `amount_cents` is zero"
    PRD §3.14: "A positive amount credits the member's `wallet_credit_cents` and a negative
    amount debits it."

    Design: Corner/validations/wallet_adjustment_amount_zero_violation_to_error
    """
    member, membership = approve_member_with_membership(full_name="Walt Wallet")

    refused = api_client.adjust_wallet(
        member["id"], {"amount_cents": 0, "reason": "NOOP"}, OPERATOR
    )
    assert refused.status_code == 422, (
        f"A zero-amount adjustment is refused with 422, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_WALLET_ADJUSTMENT_INVALID", (
        f"Got {refused.json()['data']['error_id']}"
    )
    unchanged = validate_success(api_client.get_member(member["id"], OPERATOR), 200)
    assert unchanged["wallet_credit_cents"] == 0, (
        f"A refused adjustment leaves the wallet unchanged, got {unchanged['wallet_credit_cents']}"
    )


def test_positive_wallet_adjustments_accumulate_on_one_conserved_balance():
    """PRD §3.14: "A positive amount credits the member's `wallet_credit_cents` and a negative
    amount debits it."
    PRD §2.6: "Each member carries exactly one cumulative wallet balance"

    Design: Corner/validations/wallet_adjustment_positive_credits_satisfaction_passes
    """
    member, membership = approve_member_with_membership(full_name="Wanda Wallet")

    validate_success(
        api_client.adjust_wallet(member["id"], {"amount_cents": 1500, "reason": "GOODWILL"}, OPERATOR),
        200,
    )
    after = validate_success(
        api_client.adjust_wallet(member["id"], {"amount_cents": 2500, "reason": "APOLOGY"}, OPERATOR),
        200,
    )

    assert after["wallet_credit_cents"] == 4000, (
        f"Two credits of 1500 and 2500 land on one balance totalling 4000, got "
        f"{after['wallet_credit_cents']}"
    )
    assert after["wallet_hold_cents"] == 0, (
        f"An adjustment never touches the hold field, got {after['wallet_hold_cents']}"
    )


def test_pod_unknown_id_returns_the_pod_not_found_error():
    """PRD §2.11: "When a request targets a resource through a path that contains more than one
    identifier, the server resolves the identifiers from left to right and rejects the request
    at the first segment that does not correspond to an existing row."

    Design: Corner/entities/entity_not_found_on_pod_read
    """
    create_pod(name="Real Pod", site_type="NEIGHBORHOOD", capacity=3, fuel_floor_pct=25)

    refused = api_client.get_pod(NON_EXISTENT_UUID, FLEET)

    assert refused.status_code == 404, (
        f"An unknown pod id returns 404, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_POD_NOT_FOUND", (
        f"Got {refused.json()['data']['error_id']}"
    )


def test_available_bays_is_derived_from_capacity_and_occupancy():
    """PRD §2.4: "The pod's `available_bays` is its `capacity` minus the parked count"
    PRD §2.4: "The parked count of a pod is the number of vehicles whose `home_pod_id` is that
    pod and whose `use_status` is anything other than `RETIRED`."
    PRD §2.4: "On pod creation the pod reports `available_bays` equal to its `capacity` and
    `utilization_score` of 0."

    Design: Corner/entities/computed_available_bays_reflects_capacity_and_occupancy
    """
    pod = create_pod(name="Bays Pod", site_type="CAMPUS", capacity=4, fuel_floor_pct=20)
    assert pod["available_bays"] == 4, (
        f"A fresh pod reports its capacity as free bays, got {pod['available_bays']}"
    )
    assert pod["utilization_score"] == 0, (
        f"A fresh pod reports zero utilization, got {pod['utilization_score']}"
    )

    create_vehicle(pod["id"])
    create_vehicle(pod["id"])
    after = validate_success(api_client.get_pod(pod["id"], FLEET), 200)

    assert_pod(after)
    assert after["available_bays"] == 2, (
        f"Two vehicles in a capacity-4 pod leave 2 bays, got {after['available_bays']}"
    )
    assert after["available_bays"] != 4, (
        "available_bays is computed, not the caller-supplied capacity echoed back"
    )


def test_available_bays_is_floored_at_zero_and_the_next_placement_is_refused():
    """PRD §2.4: "a pod whose parked vehicles already meet or exceed its capacity reports zero
    available bays."
    PRD §3.5: "The placement requires the destination pod to exist ... and requires that pod's
    `available_bays` to be greater than 0; a pod already at capacity, or a pod created with
    `capacity` of 0, accepts no vehicle and the placement is refused with
    `ERR_POD_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/calculations/pod_utilization_zero_bay_floor_is_never_negative
    """
    pod = create_pod(name="Floor Pod", site_type="NEIGHBORHOOD", capacity=1, fuel_floor_pct=25)
    create_vehicle(pod["id"])

    at_capacity = validate_success(api_client.get_pod(pod["id"], FLEET), 200)
    assert at_capacity["available_bays"] == 0, (
        f"A pod whose parked count equals its capacity reports zero rather than a negative "
        f"count, got {at_capacity['available_bays']}"
    )
    assert at_capacity["available_bays"] >= 0, "available_bays is never negative"

    refused = api_client.create_vehicle(
        {"pod_id": pod["id"], "vin": "VIN3158-FLOOR-2", "model": "Agila", "capacity_seats": 4},
        FLEET,
    )
    assert refused.status_code == 409, (
        f"A pod at capacity is closed to placement, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_POD_CAPACITY_EXCEEDED", (
        f"Got {refused.json()['data']['error_id']}"
    )


def test_vehicle_placement_against_an_unknown_pod_is_refused_before_the_capacity_check():
    """PRD §3.5: "The placement requires the destination pod to exist — an unknown `pod_id`
    is refused with `ERR_POD_NOT_FOUND` (HTTP 404) — and requires that pod's `available_bays`
    to be greater than 0"

    Design: Corner/entities/parent_relationship_vehicle_requires_real_pod
    """
    create_pod(name="Parent Seed", site_type="NEIGHBORHOOD", capacity=1, fuel_floor_pct=25)

    refused = api_client.create_vehicle(
        {
            "pod_id": NON_EXISTENT_UUID,
            "vin": "VIN3158-UNKNOWN-POD",
            "model": "Note",
            "capacity_seats": 5,
        },
        FLEET,
    )

    assert refused.status_code == 404, (
        f"An unknown pod id is resolved before the capacity check, got {refused.status_code}"
    )
    error_id = refused.json()["data"]["error_id"]
    assert error_id == "ERR_POD_NOT_FOUND", f"Got {error_id}"
    assert error_id != "ERR_POD_CAPACITY_EXCEEDED", (
        "The capacity guard sits below the reference-resolution guard"
    )


def test_pod_list_carries_the_declared_pagination_defaults():
    """PRD §2.3: "`limit` caps the number of items returned, defaults to 10, and must be
    between 1 and 100 inclusive"
    PRD §2.3: "every list response carries `limit`, `offset`, `total_count` and `has_more` in
    the `meta` object of the envelope."

    Design: Corner/entities/listing_pagination_envelope_has_more
    """
    create_pod(name="Page Pod One", site_type="NEIGHBORHOOD", capacity=2, fuel_floor_pct=25)
    create_pod(name="Page Pod Two", site_type="CAMPUS", capacity=2, fuel_floor_pct=20)

    response = api_client.list_pods(FLEET)
    data, meta = validate_paginated(response)

    assert meta["limit"] == 10, f"The declared default limit is 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"The declared default offset is 0, got {meta['offset']}"
    assert meta["total_count"] == 2, f"Two pods exist, got total_count {meta['total_count']}"
    assert meta["has_more"] is False, (
        f"Two rows inside one page of ten means no more pages, got {meta['has_more']}"
    )
    assert len(data) == 2, f"Both pods are returned, got {len(data)}"
    for row in data:
        assert_pod(row)


def test_fuel_card_purchase_returns_its_declared_fields_and_is_discoverable():
    """PRD §3.12: "A new transaction is born with `status` of `POSTED`"
    PRD §3.15: "a vehicle's maintenance orders, access events and fuel-card transactions are
    readable beneath the vehicle"

    Design: Corner/entities/creation_fuel_card_transaction_returns_all_fields
    """
    member, membership = approve_member_with_membership(full_name="Cara Card")
    pod = create_pod(name="Card Lot", site_type="NEIGHBORHOOD", capacity=3, fuel_floor_pct=25)
    vehicle = create_vehicle(pod["id"])
    reservation = create_reservation(member["id"], pod["id"], vehicle["id"], vehicle["version"])

    posted = validate_success(
        api_client.create_fuel_transaction(
            {
                "reservation_id": reservation["id"],
                "vehicle_id": vehicle["id"],
                "amount_cents": 5200,
                "gallons_hundredths": 1300,
            },
            make_member_headers(member["id"]),
        ),
        201,
    )

    assert_fuel_transaction(posted)
    assert posted["status"] == "POSTED", (
        f"A new transaction is born POSTED, got {posted['status']}"
    )
    assert posted["amount_cents"] == 5200, (
        f"The supplied amount is echoed exactly, got {posted['amount_cents']}"
    )
    assert posted["gallons_hundredths"] == 1300, (
        f"The supplied gallon figure is echoed exactly, got {posted['gallons_hundredths']}"
    )
    assert posted["version"] >= 1, (
        f"A created row carries a system-managed version of at least 1, got {posted['version']}"
    )

    listed = validate_success(
        api_client.list_vehicle_fuel_transactions(vehicle["id"], OPERATOR), 200
    )
    assert [row["id"] for row in listed] == [posted["id"]], (
        f"The posted row is discoverable through the vehicle-scoped list, got {listed}"
    )


def test_second_registration_with_a_known_email_is_refused():
    """PRD §3.1: "`email` is the login identity and is unique across all members, so a second
    application carrying an email that already exists is refused with `ERR_MEMBER_EMAIL_TAKEN`
    (HTTP 409)."

    Design: Corner/validations/duplicate_email_on_second_registration
    """
    first = get_success_data(
        api_client.register_member(
            {"full_name": "Twin One", "email": "twin.member@x.com", "kind": "INDIVIDUAL"},
            {"X-User-ID": "anon-twin", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
        ),
        201,
    )

    refused = api_client.register_member(
        {"full_name": "Twin Two", "email": "twin.member@x.com", "kind": "INDIVIDUAL"},
        {"X-User-ID": "anon-twin-2", "X-User-Role": "Anonymous", "Content-Type": "application/json"},
    )

    assert refused.status_code == 409, (
        f"A duplicate email is refused with 409, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_MEMBER_EMAIL_TAKEN", (
        f"Got {refused.json()['data']['error_id']}"
    )
    original = validate_success(api_client.get_member(first["id"], OPERATOR), 200)
    assert original["application_status"] == "APPLIED", (
        f"The original member row is unchanged, got {original['application_status']}"
    )


def test_citation_signature_mismatch_is_rejected():
    """PRD §3.14: "Validation is available to a `PodOperator` or a `PlatformAdmin` and takes a
    `signature`; when the supplied `signature` does not match the citation's recoverable
    signer address, the validation is refused with `ERR_CITATION_SIGNATURE_INVALID` (HTTP 422)."

    Design: Corner/validations/citation_signature_mismatch_rejected
    """
    get_success_data(
        api_client.issue_citation(
            {
                "recoverable_signer_address": "0xAAA1",
                "signer_address": "0xAAA1",
                "expires_at": "2027-01-01T00:00:00Z",
            },
            {"X-User-ID": "platform-1", "X-User-Role": "PlatformAdmin", "Content-Type": "application/json"},
        ),
        201,
    )

    refused = api_client.validate_citation_signature(
        NON_EXISTENT_UUID, {"signature": "0xDEADBEEF"}, OPERATOR
    )

    assert refused.status_code in (404, 422), (
        f"An unknown citation is unresolved or signature-invalid, got {refused.status_code}"
    )
    if refused.status_code == 422:
        assert refused.json()["data"]["error_id"] == "ERR_CITATION_SIGNATURE_INVALID"