"""Body-schema validation, pagination bounds and resource resolution."""

from test_helpers import (
    ADMIN,
    DISPATCH,
    ApiErrorId,
    client_payload,
    create_agency,
    create_approved_referral,
    create_client,
    create_truck,
    delivery_run_payload,
    make_case_manager_headers,
    make_volunteer_headers,
    referral_payload,
    set_clock,
    validate_error,
    validate_paginated,
    voucher_line_payload,
    voucher_payload,
)

MISSING_CLIENT = "00000000-0000-4000-8000-00000000000a"
MISSING_REFERRAL = "00000000-0000-4000-8000-00000000000b"
MISSING_VOUCHER = "00000000-0000-4000-8000-00000000000c"
MISSING_OFFER = "00000000-0000-4000-8000-00000000000d"
MISSING_ITEM = "00000000-0000-4000-8000-00000000000e"
MISSING_TRUCK = "00000000-0000-4000-8000-00000000000f"
MISSING_RUN = "00000000-0000-4000-8000-000000000010"
MISSING_STOP = "00000000-0000-4000-8000-000000000011"
MISSING_VOLUNTEER = "00000000-0000-4000-8000-000000000012"
MISSING_CREW = "00000000-0000-4000-8000-000000000013"
MISSING_WAITLIST = "00000000-0000-4000-8000-000000000014"
MISSING_AGENCY = "00000000-0000-4000-8000-000000000015"
MISSING_TRUCK_FK = "00000000-0000-4000-8000-000000000020"


def test_household_registration_without_household_size_is_rejected(api):
    """PRD §2.9: "The request body conforms to the endpoint's declared input
    schema: every required field present, no unknown field, every enum value
    drawn from its declared member set, every integer within its declared range,
    every datetime a valid ISO 8601 UTC instant, and every window's end strictly
    after its start — otherwise `ERR_VALIDATION` (400). Applies to every
    endpoint that accepts a body."
    PRD §3.1: "Households are registered by a `CaseManager`, who supplies the
    `agency_id` of their own agency, a `household_size` of at least 1 and at
    most 12, the `county` the household lives in, and an optional `has_infant`
    flag that defaults to false and means the household includes a child under
    24 months."

    Design: Corner/entities/corner_client_missing_required_household_size_returns_invalid_request
    """
    agency = create_agency(name="Cranfield Neighbors", county="CENTRAL",
                           quarterly_voucher_quota=4)
    payload = client_payload(agency["id"], county="CENTRAL")
    payload.pop("household_size")
    payload.pop("has_infant")

    response = api.create_client(payload, make_case_manager_headers(agency["id"]))
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    rows, meta = validate_paginated(
        api.list_clients(ADMIN, {"agency_id": agency["id"]})
    )
    assert rows == [], "a rejected registration must create nothing"
    assert meta["total_count"] == 0


def test_referral_draft_with_unknown_urgency_value_is_rejected(api):
    """PRD §2.9: "The request body conforms to the endpoint's declared input
    schema: every required field present, no unknown field, every enum value
    drawn from its declared member set, every integer within its declared range,
    every datetime a valid ISO 8601 UTC instant, and every window's end strictly
    after its start — otherwise `ERR_VALIDATION` (400). Applies to every
    endpoint that accepts a body."
    PRD §3.2: "The draft carries `requested_categories`, a non-empty array whose
    elements are drawn from `BED`, `SOFA`, `CRIB`, `TABLE_SET`, `DRESSER`,
    `KITCHEN_KIT` and `LINENS`; an `urgency` banding of `ROUTINE`, `PRIORITY` or
    `EMERGENCY`; an optional `home_visit_completed` boolean that defaults to
    false and records whether the case manager physically visited the residence;
    and a `bed_bug_attestation` boolean by which the case manager attests that
    there is no active infestation at the residence."

    Design: Corner/entities/corner_referral_invalid_urgency_enum_rejected
    """
    agency = create_agency(name="Delmar Community Hub", county="CENTRAL",
                           quarterly_voucher_quota=4)
    household = create_client(agency["id"], household_size=3, county="CENTRAL")

    payload = referral_payload(household["id"], agency["id"], urgency="URGENT")
    response = api.create_referral(payload, make_case_manager_headers(agency["id"]))
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    rows, meta = validate_paginated(
        api.list_referrals(ADMIN, {"client_id": household["id"]})
    )
    assert rows == [], "a rejected draft must create nothing"
    assert meta["total_count"] == 0


def test_voucher_issuance_carrying_a_computed_money_field_is_rejected(api):
    """PRD §2.9: "The request body conforms to the endpoint's declared input
    schema: every required field present, no unknown field, every enum value
    drawn from its declared member set, every integer within its declared range,
    every datetime a valid ISO 8601 UTC instant, and every window's end strictly
    after its start — otherwise `ERR_VALIDATION` (400). Applies to every
    endpoint that accepts a body."
    PRD §3.3: "A case manager redeems an approved referral by issuing a voucher
    against its `referral_id`, together with `lines`, an array in which each
    element declares a `category` drawn from the seven household-goods
    categories, a `quantity_requested` of at least 1 and at most 6, and a
    `min_condition` of `A`, `B` or `C` naming the worst condition grade the
    household will accept on that line."

    Design: Corner/entities/corner_voucher_rejects_unknown_money_field_in_request_body
    """
    agency = create_agency(name="Everglade Support Circle", county="CENTRAL",
                           quarterly_voucher_quota=4)
    household = create_client(agency["id"], household_size=3, county="CENTRAL")
    referral = create_approved_referral(agency["id"], household["id"],
                                        requested_categories=["BED"])

    payload = voucher_payload(referral["id"], [voucher_line_payload("BED", 1, "B")])
    payload["gross_fee_cents"] = 1

    response = api.create_voucher(payload, make_case_manager_headers(agency["id"]))
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    rows, meta = validate_paginated(
        api.list_vouchers(ADMIN, {"referral_id": referral["id"]})
    )
    assert rows == [], "a rejected issuance must create no voucher"
    assert meta["total_count"] == 0


def test_pagination_limit_above_the_maximum_is_rejected(api):
    """PRD §2.3: "A `limit` that is not an integer within 1 through 100
    inclusive, or an `offset` that is not an integer greater than or equal to 0,
    is rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/entities/corner_pagination_limit_above_max_returns_pagination_invalid
    """
    agency = create_agency(name="Gravenhurst Aid Post", county="NORTH",
                           quarterly_voucher_quota=4)

    response = api.list_clients(
        ADMIN, {"agency_id": agency["id"], "limit": 101, "offset": 0}
    )
    validate_error(response, ApiErrorId.ERR_PAGINATION_INVALID.value, 400)


def test_unknown_path_ids_answer_with_their_own_not_found_identifier(api):
    """PRD §2.5: "Each entity has its own not-found identifier:
    `ERR_AGENCY_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
    `ERR_VOUCHER_NOT_FOUND`, `ERR_DONATION_OFFER_NOT_FOUND`,
    `ERR_INVENTORY_ITEM_NOT_FOUND`, `ERR_TRUCK_NOT_FOUND`,
    `ERR_RUN_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`,
    `ERR_CREW_ASSIGNMENT_NOT_FOUND` and `ERR_WAITLIST_ENTRY_NOT_FOUND`, all
    returned with HTTP 404."

    Design: Corner/entities/corner_not_found_across_path_resources
    """
    set_clock("2026-08-04T09:00:00Z")

    probes = [
        (api.get_client(MISSING_CLIENT, ADMIN), ApiErrorId.ERR_CLIENT_NOT_FOUND),
        (api.get_referral(MISSING_REFERRAL, ADMIN), ApiErrorId.ERR_REFERRAL_NOT_FOUND),
        (api.get_voucher(MISSING_VOUCHER, ADMIN), ApiErrorId.ERR_VOUCHER_NOT_FOUND),
        (api.get_donation_offer(MISSING_OFFER, ADMIN),
         ApiErrorId.ERR_DONATION_OFFER_NOT_FOUND),
        (api.get_inventory_item(MISSING_ITEM, ADMIN),
         ApiErrorId.ERR_INVENTORY_ITEM_NOT_FOUND),
        (api.get_truck(MISSING_TRUCK, ADMIN), ApiErrorId.ERR_TRUCK_NOT_FOUND),
    ]

    for response, error_id in probes:
        error_data = validate_error(response, error_id.value, 404)
        assert response.json()["response_type"] == "error"
        assert error_data["message"].strip(), "every error carries a message"


def test_unknown_delivery_and_waitlist_ids_answer_with_their_own_not_found(api):
    """PRD §2.5: "Each entity has its own not-found identifier:
    `ERR_AGENCY_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
    `ERR_VOUCHER_NOT_FOUND`, `ERR_DONATION_OFFER_NOT_FOUND`,
    `ERR_INVENTORY_ITEM_NOT_FOUND`, `ERR_TRUCK_NOT_FOUND`,
    `ERR_RUN_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`,
    `ERR_CREW_ASSIGNMENT_NOT_FOUND` and `ERR_WAITLIST_ENTRY_NOT_FOUND`, all
    returned with HTTP 404."
    PRD §2.9: "Every path-parameter resource exists, validated left to right —
    otherwise the matching not-found identifier from §2.5 (404). Applies to
    every endpoint with a path id."

    Design: Corner/entities/corner_not_found_across_delivery_and_waitlist_resources
    """
    set_clock("2026-08-04T09:00:00Z")

    probes = [
        (api.get_delivery_run(MISSING_RUN, DISPATCH), ApiErrorId.ERR_RUN_NOT_FOUND),
        (api.record_stop_outcome(MISSING_STOP, {"outcome": "DELIVERED"}, DISPATCH),
         ApiErrorId.ERR_STOP_NOT_FOUND),
        (api.get_volunteer(MISSING_VOLUNTEER, ADMIN),
         ApiErrorId.ERR_VOLUNTEER_NOT_FOUND),
        (api.respond_crew_assignment(MISSING_CREW, {"response": "CONFIRM"},
                                     make_volunteer_headers(MISSING_VOLUNTEER)),
         ApiErrorId.ERR_CREW_ASSIGNMENT_NOT_FOUND),
        (api.get_waitlist_entry(MISSING_WAITLIST, ADMIN),
         ApiErrorId.ERR_WAITLIST_ENTRY_NOT_FOUND),
        (api.get_agency(MISSING_AGENCY, ADMIN), ApiErrorId.ERR_AGENCY_NOT_FOUND),
    ]

    for response, error_id in probes:
        validate_error(response, error_id.value, 404)


def test_run_planning_with_an_unknown_truck_foreign_key_is_rejected(api):
    """PRD §2.5: "The identical set of identifiers governs foreign keys supplied
    in a request body. Whenever a payload names an agency, a client, a referral,
    a voucher, a truck, a delivery run or a volunteer that does not resolve to
    an existing row, the corresponding not-found identifier is returned with
    HTTP 404."

    Design: Corner/entities/corner_body_foreign_key_truck_not_found_on_run_create
    """
    set_clock("2026-08-04T09:00:00Z")
    real_truck = create_truck(label="BOX-21", capacity_cubic_feet=600,
                              home_county="CENTRAL", crew_minimum=1)

    payload = delivery_run_payload(MISSING_TRUCK_FK, service_date="2026-08-05",
                                   window_start="2026-08-05T09:00:00Z",
                                   window_end="2026-08-05T17:00:00Z",
                                   county="CENTRAL")
    response = api.create_delivery_run(payload, DISPATCH)
    validate_error(response, ApiErrorId.ERR_TRUCK_NOT_FOUND.value, 404)

    rows, meta = validate_paginated(
        api.list_delivery_runs(DISPATCH, {"truck_id": real_truck["id"]})
    )
    assert rows == [], "a rejected plan must create no run"
    assert meta["total_count"] == 0
