"""Role membership, buy-side ownership, and segregation of duties."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    classify_issue_advertiser,
    create_order_payload,
    create_rate_class,
    create_station,
    create_station_payload,
    file_complaint,
    hourly_spots,
    intake_advertiser,
    make_advertiser_agent_headers,
    make_headers_without_auth,
    order_decision_payload,
    read_advertiser,
    read_complaint,
    read_order,
    read_spot,
    read_station,
    set_clock,
    setup_issue_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER_ALPHA = TEST_USERS["officer_alpha_headers"]
OFFICER_BETA = TEST_USERS["officer_beta_headers"]
TRAFFIC = TEST_USERS["traffic_scheduler_headers"]
PUBLIC = TEST_USERS["public_complainant_headers"]
ACCEPT = order_decision_payload("ACCEPT")


def test_traffic_scheduler_cannot_accept_and_the_officer_cannot_record_a_disposition(api):
    """PRD §2.1: "A well-formed but insufficiently privileged request — a role that is
    not listed for the endpoint being called in the endpoint table of Section 4 — is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `TrafficScheduler` is the station's traffic and continuity operator and
    is the *only* role permitted to record what actually ran on air; the separation from
    `StationComplianceOfficer` is deliberate, so that the party deciding acceptance
    never also certifies the airing."

    Design: Corner/rbac/traffic_scheduler_cannot_accept_an_order
    """
    built = setup_issue_order(
        call_sign="WSOD-TV",
        market_code="DMA-138",
        station_overrides={"licensee_name": "Segregation Broadcasting", "daily_political_seconds_cap": 300},
        spots=hourly_spots(1),
        submit=True,
    )
    order, spot = built["order"], built["spots"][0]

    validate_error(api.decide_order(order["id"], ACCEPT, TRAFFIC), ApiErrorId.ERR_UNAUTHORIZED)
    validate_error(
        api.set_spot_disposition(
            spot["id"],
            {"disposition": "PREEMPTED", "preemption_reason": "Breaking news override"},
            OFFICER_BETA,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    assert read_order(order["id"])["status"] == "SUBMITTED"
    assert read_spot(spot["id"])["status"] == "SCHEDULED"


def test_advertiser_agent_cannot_add_a_spot_to_another_advertisers_order(api):
    """PRD §2.1: "When `X-User-Role` is `AdvertiserAgent`, `X-User-ID` is the `id` of the
    acting `Advertiser`; ownership checks on any resource that references an
    `Advertiser` compare the resource's foreign-key field to `X-User-ID`."
    PRD §2.1: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This
    ownership check guards exactly six operations, and only when the acting role is
    `AdvertiserAgent`: opening an order, adding a spot to an order, submitting an order,
    recording a payment on an order, cancelling an order, and filing an
    equal-opportunity request."

    Design: Corner/rbac/advertiser_agent_cannot_act_on_another_advertisers_order
    """
    built = setup_issue_order(
        call_sign="WOWN-TV",
        market_code="DMA-139",
        station_overrides={"licensee_name": "Ownership Media LLC", "daily_political_seconds_cap": 300},
        classification=None,
        spots=hourly_spots(1),
    )
    station, order = built["station"], built["order"]
    intruder = intake_advertiser(station["id"], legal_name="Coastal Water Alliance")

    validate_error(
        api.add_spot(
            order["id"],
            {
                "air_date": "2026-08-20",
                "start_offset_seconds": 3600,
                "duration_seconds": 30,
                "program_code": "EN-2",
            },
            make_advertiser_agent_headers(intruder["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
    )

    refreshed = read_order(order["id"])
    assert refreshed["spot_count"] == 1
    assert refreshed["gross_charge_cents"] == 100000


def test_the_accepting_officer_cannot_answer_the_complaint_about_that_order(api):
    """PRD §2.1: "When a complaint names a specific order, the officer answering that
    complaint must not be the same person who accepted the order: if `X-User-ID` equals
    the `accepted_by_user_id` of the `CommercialOrder` referenced by the complaint's
    `order_id`, the response is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.9: "The transition, whether it runs `OPEN → RESPONDED` or `REOPENED →
    RESPONDED`, decrements the station's `open_complaint_count` by one and then
    recomputes `compliance_posture` from the reduced count; the two source states
    produce identical effects."

    Design: Corner/rbac/accepting_officer_cannot_respond_to_the_complaint_about_that_order
    """
    built = setup_issue_order(
        call_sign="WSGD-TV",
        market_code="DMA-140",
        station_overrides={
            "licensee_name": "Duties Broadcasting Corp",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1),
        accept=True,
    )
    station, order = built["station"], built["order"]
    assert order["accepted_by_user_id"] == "officer-beta"

    complaint = file_complaint(
        station["id"],
        complainant_name="Ida Brennan",
        allegation_code="LUC_OVERCHARGE",
        narrative="This order was billed above the lowest unit charge.",
        order_id=order["id"],
    )

    validate_error(
        api.respond_complaint(
            complaint["id"],
            {"response_text": "Reviewed by the accepting officer.", "remedy_code": "NO_VIOLATION"},
            OFFICER_BETA,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    answered = validate_success(
        api.respond_complaint(
            complaint["id"],
            {"response_text": "Independent review found no violation.", "remedy_code": "NO_VIOLATION"},
            OFFICER_ALPHA,
        )
    )
    assert answered["status"] == "RESPONDED"
    assert read_complaint(complaint["id"])["responded_by_user_id"] == "officer-alpha"

    refreshed_station = read_station(station["id"])
    assert refreshed_station["open_complaint_count"] == 0
    assert refreshed_station["compliance_posture"] == "OPEN"


def test_request_without_authentication_headers_is_rejected_before_anything_else(api):
    """PRD §2.1: "Every request to the API — without exception, including read-only ones
    — must carry two headers: `X-User-ID`, identifying the acting principal, and
    `X-User-Role`, naming the role that principal is acting in. If either header is
    absent, empty, or if `X-User-Role` names anything other than one of the five roles
    below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "1. **Authentication and authorisation.** Header presence and role
    validity (`ERR_UNAUTHENTICATED`) come first, then endpoint role membership
    (`ERR_UNAUTHORIZED`), then buy-side ownership (`ERR_NOT_RESOURCE_OWNER`), then
    segregation of duties on complaint responses (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/rbac/missing_auth_headers_return_unauthenticated_before_any_other_check
    """
    set_clock("2026-08-05T09:00:00Z")

    validate_error(
        api.create_station(
            create_station_payload(
                call_sign="WNUL-TV", licensee_name="No Auth Media", market_code="DMA-141"
            ),
            make_headers_without_auth(),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )

    # call_sign is unique across every station, so the same registration succeeding
    # afterwards proves the unauthenticated attempt persisted nothing.
    registered = validate_success(
        api.create_station(
            create_station_payload(
                call_sign="WNUL-TV", licensee_name="No Auth Media", market_code="DMA-141"
            ),
            ADMIN,
        ),
        201,
    )
    assert registered["call_sign"] == "WNUL-TV"
    assert registered["version"] == 1


def test_public_complainant_can_neither_open_orders_nor_classify_advertisers(api):
    """PRD §2.1: "A `PublicComplainant` is a member of the public or an opposing interest
    who inspects the public political file and files FCC complaints."
    PRD §2.1: "A well-formed but insufficiently privileged request — a role that is not
    listed for the endpoint being called in the endpoint table of Section 4 — is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/public_complainant_cannot_create_orders_or_classify_advertisers
    """
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WPUB-TV", licensee_name="Public Access Media", market_code="DMA-142"
    )
    rate_class = create_rate_class(station["id"])
    advertiser = intake_advertiser(station["id"], legal_name="Empire Growth Fund")

    validate_error(
        api.create_order(
            create_order_payload(station["id"], advertiser["id"], rate_class["id"]),
            PUBLIC,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api.decide_advertiser(
            advertiser["id"],
            {"decision": "CLASSIFY_ISSUE", "reason": "Attempted by the public"},
            PUBLIC,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    assert read_advertiser(advertiser["id"])["status"] == "SUBMITTED"
    _rows, meta = validate_paginated(
        api.list_orders(ADMIN, params={"station_id": station["id"]})
    )
    assert meta["total_count"] == 0
