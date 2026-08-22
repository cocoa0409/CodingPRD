"""Authentication, endpoint authorization, agency scoping and segregation of duties."""

from test_helpers import (
    ADMIN,
    INTAKE,
    WAREHOUSE,
    WAREHOUSE_INSPECTOR_ID,
    WAREHOUSE_RELEASER_ID,
    ApiErrorId,
    build_user_headers,
    create_agency,
    create_client,
    create_referral,
    create_run,
    create_truck,
    create_volunteer,
    donation_item_payload,
    inspection_payload,
    invite_crew,
    list_inventory,
    make_case_manager_headers,
    make_volunteer_headers,
    make_warehouse_lead_headers,
    prepare_offer_for_intake,
    review_payload,
    set_clock,
    setup_quarantined_offer,
    submit_referral,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_case_manager_may_not_adjudicate_a_referral(api):
    """PRD §2.1: "If `X-User-Role` is not one of those six, or if it is one of
    them but that role is not listed as authorized for the endpoint being called
    (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP
    403)."
    PRD §3.2: "**Adjudication.** A `PlatformAdmin` records the furniture bank's
    verdict by supplying a `decision` of `APPROVE`, `RETURN` or `DENY`, plus an
    optional `note`."

    Design: Corner/rbac/corner_case_manager_cannot_review_a_referral
    """
    agency = create_agency(name="Verity Lane Aid", county="CENTRAL",
                           quarterly_voucher_quota=4)
    household = create_client(agency["id"], household_size=4, county="CENTRAL")
    referral = create_referral(agency["id"], household["id"],
                               requested_categories=["BED"])
    submit_referral(referral["id"], agency["id"])

    response = api.review_referral(
        referral["id"], review_payload("APPROVE"),
        make_case_manager_headers(agency["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    referral_now = validate_success(api.get_referral(referral["id"], ADMIN))
    assert referral_now["status"] == "SUBMITTED", "the refused review changes nothing"
    agency_now = validate_success(api.get_agency(agency["id"], ADMIN))
    assert agency_now["quota_used"] == 0, "no quota slot may be consumed"


def test_intake_coordinator_may_not_record_the_warehouse_inspection(api):
    """PRD §2.1: "If `X-User-Role` is not one of those six, or if it is one of
    them but that role is not listed as authorized for the endpoint being called
    (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP
    403)."
    PRD §3.5: "When the truck comes back, a `WarehouseLead` records the
    inspection by supplying `inspections`, an array in which each element names
    the `item_id` of a piece, the `graded_condition` the lead assigns it — `A`,
    `B`, `C` or `D` — and a `live_pest_observed` boolean."

    Design: Corner/rbac/corner_intake_coordinator_cannot_record_warehouse_intake
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-60", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    prepared = prepare_offer_for_intake(
        truck["id"], [donation_item_payload("DRESSER", "B", False, 20.0)],
        donor_name="Hugo Marchetti", donor_phone="555-0901",
    )
    piece = prepared["items"][0]

    response = api.intake_donation_offer(
        prepared["offer"]["id"],
        {"inspections": [inspection_payload(piece["id"], "B", False)]},
        INTAKE,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    offer_now = validate_success(
        api.get_donation_offer(prepared["offer"]["id"], INTAKE)
    )
    assert offer_now["status"] == "PICKUP_SCHEDULED"
    assert offer_now["inspector_user_id"] is None, (
        "a refused intake must not stamp inspector_user_id"
    )
    assert list_inventory(donation_item_id=piece["id"]) == [], (
        "a refused intake must mint no stock"
    )


def test_case_manager_cannot_read_another_agencys_household(api):
    """PRD §2.1: "Concretely, a case manager may only read an agency whose `id`
    equals `X-User-ID`, may only create a `Client` or a `Referral` whose
    `agency_id` equals `X-User-ID`, and may only read or act on a client,
    referral or voucher whose owning agency — reached directly through
    `agency_id`, or through the voucher's referral and that referral's
    `agency_id` — equals `X-User-ID`. A violation is rejected with
    `ERR_AGENCY_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/corner_case_manager_scope_violation_reading_another_agencys_household
    """
    agency_alpha = create_agency(name="Agency Alpha", county="CENTRAL",
                                 quarterly_voucher_quota=4)
    agency_beta = create_agency(name="Agency Beta", county="NORTH",
                                quarterly_voucher_quota=4)
    household = create_client(agency_alpha["id"], household_size=4, county="CENTRAL")

    denied = api.get_client(household["id"], make_case_manager_headers(agency_beta["id"]))
    validate_error(denied, ApiErrorId.ERR_AGENCY_SCOPE_VIOLATION.value, 403)

    allowed = validate_success(
        api.get_client(household["id"], make_case_manager_headers(agency_alpha["id"]))
    )
    assert allowed["id"] == household["id"], "the owning agency may read its own household"
    assert allowed["agency_id"] == agency_alpha["id"]


def test_volunteer_cannot_answer_another_volunteers_invitation(api):
    """PRD §2.1: "When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of
    the acting `Volunteer` row; ownership checks compare the `volunteer_id` of
    the crew assignment being answered, and the `id` of the volunteer record
    being read, to `X-User-ID`. Answering someone else's crew invitation, or
    reading another volunteer's record, is rejected with
    `ERR_AGENCY_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/corner_volunteer_cannot_answer_another_volunteers_invitation
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-61", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    volunteer_a = create_volunteer(name="Volunteer A", county="CENTRAL",
                                   lift_certified=True)
    volunteer_b = create_volunteer(name="Volunteer B", county="CENTRAL",
                                   lift_certified=True)
    run = create_run(truck["id"], service_date="2026-08-05",
                     window_start="2026-08-05T09:00:00Z",
                     window_end="2026-08-05T17:00:00Z", county="CENTRAL")
    assignment = invite_crew(run["id"], volunteer_a["id"], "DRIVER")

    response = api.respond_crew_assignment(
        assignment["id"], {"response": "CONFIRM"},
        make_volunteer_headers(volunteer_b["id"]),
    )
    validate_error(response, ApiErrorId.ERR_AGENCY_SCOPE_VIOLATION.value, 403)

    crew_rows, _ = validate_paginated(api.list_run_crew(run["id"], ADMIN))
    assignment_now = next(row for row in crew_rows if row["id"] == assignment["id"])
    assert assignment_now["status"] == "INVITED", "the refused answer changes nothing"

    run_now = validate_success(api.get_delivery_run(run["id"], ADMIN))
    assert run_now["status"] == "PLANNED"
    volunteer_b_now = validate_success(
        api.get_volunteer(volunteer_b["id"], make_volunteer_headers(volunteer_b["id"]))
    )
    assert volunteer_b_now["assigned_hours_month"] == 0.0


def test_quarantine_release_by_the_recording_inspector_is_refused(api):
    """PRD §2.1: "A release performed by the same `X-User-ID` that recorded the
    intake inspection on that offer is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."
    PRD §3.5: "**Releasing quarantine** is a separate act by a *different*
    `WarehouseLead`. The offer must be in `QUARANTINED`, otherwise
    `ERR_OFFER_INVALID_STATE`; the current instant must be at or after
    `quarantine_release_due_at`, otherwise `ERR_QUARANTINE_NOT_ELAPSED`; and the
    acting `X-User-ID` must differ from the offer's stored `inspector_user_id`,
    otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/corner_quarantine_release_by_the_same_inspector_rejected
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-62", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    supply = setup_quarantined_offer(
        truck["id"], donor_name="Ines Moreau", donor_phone="555-0911"
    )
    assert supply["offer"]["inspector_user_id"] == WAREHOUSE_INSPECTOR_ID

    set_clock("2026-08-18T09:00:00Z")

    denied = api.release_quarantine(
        supply["offer"]["id"], make_warehouse_lead_headers(WAREHOUSE_INSPECTOR_ID)
    )
    validate_error(denied, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    released = validate_success(
        api.release_quarantine(
            supply["offer"]["id"], make_warehouse_lead_headers(WAREHOUSE_RELEASER_ID)
        )
    )
    assert released["status"] == "RELEASED", "a different lead may release the offer"

    available, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "AVAILABLE", "limit": 100})
    )
    assert len(available) == 3, (
        f"all three quarantined units reach the floor, got {len(available)}"
    )


def test_empty_identity_header_is_refused_before_authorization(api):
    """PRD §2.1: "Every request to this API must carry two headers: `X-User-ID`,
    which identifies the acting user, and `X-User-Role`, which declares the
    capacity in which they are acting. If either header is missing or empty, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other
    processing occurs."

    Design: Corner/rbac/corner_missing_auth_identity_header_returns_unauthenticated
    """
    agency = create_agency(name="Wolvercote Aid", county="CENTRAL",
                           quarterly_voucher_quota=4)

    response = api.get_agency(agency["id"], build_user_headers("", "PlatformAdmin"))
    error_data = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    assert response.json()["response_type"] == "error"
    assert error_data["message"].strip(), "the error carries a human-readable message"
