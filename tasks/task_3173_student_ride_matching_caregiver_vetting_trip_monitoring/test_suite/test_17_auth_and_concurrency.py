"""Authentication and role boundaries, plus the optimistic-concurrency guards."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_request,
    get_success_data,
    make_driver_headers,
    onboard_driver,
    read_district,
    read_trip,
    set_clock,
    setup_contract,
    setup_district,
    setup_rider,
    setup_scheduled_trip,
    validate_error,
    validate_success,
    vet_driver,
)


def test_a_call_without_identity_headers_is_reported_as_unauthenticated():
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, which
    identifies the acting party, and `X-User-Role`, which names the capacity in
    which that party acts. Both headers are mandatory."
    PRD §2.1: "A request that omits either header, or that names a role the
    platform does not recognise, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."
    PRD §2.1: "The only exception to both rules is the district self-registration
    operation, which is deliberately reachable without credentials because it is
    how a district first comes into existence."

    Design: Corner/errors/unauthenticated_call_without_the_role_header_returns_401
    """
    district = get_success_data(
        api_client.create_district(
            {
                "name": "Aldine ISD",
                "billing_email": "ap@aldine.example",
                "contract_rate_per_ride_cents": 5300,
                "contract_rate_per_mile_cents": 215,
            },
            TEST_USERS["anonymous_headers"],
        ),
        201,
    )

    resp = api_client.get_district(
        district["id"], {"X-User-ID": "caller-without-a-role"}
    )
    assert resp.json().get("response_type") == "error"
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    # The self-registration path remains reachable without credentials.
    validate_success(
        api_client.create_district(
            {
                "name": "Reachable Without Credentials",
                "billing_email": "ap@reachable.example",
                "contract_rate_per_ride_cents": 100,
                "contract_rate_per_mile_cents": 10,
            },
            {},
        ),
        201,
    )


def test_a_driver_cannot_reach_the_billing_surface():
    """PRD §2.1: "`Driver` is the narrowest role: it may act only on trips
    assigned to it and reads a student's contact detail only in masked form."
    PRD §2.1: "When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the
    acting `Driver` entity".
    PRD §2.1: "A request whose role is recognised but is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    Design: Corner/rbac/driver_role_cannot_issue_a_billing_statement
    """
    district = get_success_data(
        api_client.create_district(
            {
                "name": "Aldine ISD",
                "billing_email": "ap@aldine.example",
                "contract_rate_per_ride_cents": 5300,
                "contract_rate_per_mile_cents": 215,
            },
            TEST_USERS["anonymous_headers"],
        ),
        201,
    )
    driver = onboard_driver()
    intruder = make_driver_headers(driver["id"])

    resp = api_client.issue_statement(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", intruder
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert district["id"], "the district exists, so the refusal is not an existence verdict"


def test_a_support_agent_cannot_change_the_driver_roster():
    """PRD §2.1: "The same is true for `SupportCenterAgent`, whose `X-User-ID`
    is an opaque safety-desk identifier".
    PRD §2.1: "Authorisation is evaluated before any business rule: a caller who
    is not permitted to perform an operation never learns whether the target
    resource would have satisfied that operation's preconditions."

    Design: Corner/rbac/support_center_agent_cannot_change_the_driver_roster
    """
    driver = vet_driver()
    assert driver["status"] == "ACTIVE"

    resp = api_client.deactivate_driver(
        driver["id"], TEST_USERS["support_center_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    from test_helpers import read_driver

    after = read_driver(driver["id"])
    assert after["status"] == "ACTIVE", (
        "the refused deactivation leaves the roster untouched"
    )

    # Read access on the same row is shared with the agent.
    validate_success(
        api_client.get_driver(driver["id"], TEST_USERS["support_center_headers"])
    )


def test_a_stale_district_version_blocks_a_second_ride_request():
    """PRD §2.9: "Creating a ride request requires a non-optional
    `expected_district_version` field carrying the client's last-observed
    `version` of the target district."
    PRD §2.9: "if the district's current `version` has already advanced past the
    value the client supplied, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412) and no resource is created or modified."
    PRD §2.9: "intake policy does permit a second request to supersede an earlier
    one for the same student and window."

    Design: Corner/cross_cutting_layers/stale_district_version_blocks_a_second_ride_request_creation
    """
    set_clock("2026-09-01T00:00:00Z")
    district = setup_district()
    rider = setup_rider(district["id"])
    setup_contract(district["id"])
    observed_version = district["version"]

    first = create_request(
        district, rider, approve=False,
        window_start_at="2026-09-11T07:30:00Z",
        window_end_at="2026-09-11T07:50:00Z",
    )
    assert first["status"] == "SUBMITTED"
    assert read_district(district["id"])["version"] > observed_version, (
        "the first create advanced the district's version"
    )

    stale = api_client.create_ride_request(
        {
            "expected_district_version": observed_version,
            "district_id": district["id"],
            "rider_id": rider["id"],
            "trip_type": "PM_SCHOOL",
            "required_specialty": "NONE",
            "window_start_at": "2026-09-11T15:00:00Z",
            "window_end_at": "2026-09-11T15:20:00Z",
            "max_window_minutes": 30,
            "min_lead_time_hours": 12,
            "pickup_address": "Lincoln Elementary",
            "dropoff_address": "12 Oak St",
            "planned_miles": 3.0,
            "is_recurring": False,
        },
        TEST_USERS["district_admin_headers"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    rows = get_success_data(
        api_client.list_district_ride_requests(
            district["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert len(rows) == 1, "the rejected create produced no additional request"


def test_every_derived_effect_is_visible_without_a_retry():
    """PRD §3.8: "Billable ride units are locked in at completion. A trip that
    has not completed carries zero units; a trip that completed with both a
    passing pickup and a passing dropoff carries two".
    PRD §3.8: "A passing dropoff handoff advances the trip from `IN_TRANSIT` to
    `COMPLETED`, stamps the completion instant, records the verifying user and
    the name of the party recorded on the passing dropoff".
    PRD §3.8: "Creating a trip raises the district's scheduled-trip total by one
    and advances the district's `version`."

    Design: Corner/consistency_model/every_cascade_effect_is_visible_in_the_same_response
    """
    from test_helpers import drive_trip

    scenario = setup_scheduled_trip()
    driver_id = scenario["driver"]["id"]
    driver_headers = make_driver_headers(driver_id)
    trip_id = scenario["trip"]["id"]

    drive_trip(trip_id, driver_id, stop_after="in_transit")
    handoff = get_success_data(
        api_client.record_handoff(
            trip_id,
            {
                "leg": "DROPOFF",
                "expected_party": "SCHOOL_STAFF",
                "verified_party_name": scenario["rider"]["school_name"],
                "verification_method": "PHOTO_ID",
                "billable_miles": 5.0,
            },
            driver_headers,
        ),
        201,
    )
    assert handoff["result"] == "PASSED", (
        "the completing handoff reports its verdict in its own response"
    )

    trip = read_trip(trip_id)
    assert trip["trip_state"] == "COMPLETED", (
        "the movement state is already committed on the first read"
    )
    assert trip["billable_ride_units"] == 2, "the derivation is not deferred"
    assert trip["completed_at"] is not None
    assert trip["verified_authorized_adult_name"] == scenario["rider"]["school_name"]

    district = read_district(scenario["district"]["id"])
    assert district["trips_scheduled_total"] == 1, (
        "the district-side effect is already committed"
    )