"""Endpoint behaviours: run selection, derived reads, round trips and refused workflow calls."""

from test_helpers import (
    COORDINATOR,
    PM,
    UTILITY,
    ApiErrorId,
    api_client,
    assert_build_zone,
    assert_campaign,
    assert_cents,
    assert_fallback_option,
    assert_install_crew,
    assert_instant_equals,
    assert_page,
    assert_pct,
    assert_pole_attachment_request,
    assert_service_address,
    assert_total_count,
    fallback_offer_payload,
    grant_unserved_exception,
    install_crew_payload,
    make_account,
    make_address,
    make_campaign,
    make_fallback_option,
    make_pole_request,
    make_zone,
    pole_decision_payload,
    read_address,
    read_zone,
    set_clock,
    set_serviceability,
    setup_campaign_with_zone,
    unserved_exception_payload,
    validate_error,
    validate_success,
    validate_unpaginated,
)

BETA_DEADLINE = "2026-10-30T23:59:00Z"
CLOCK_PAST_ALPHA_DEADLINE = "2026-10-01T00:00:00Z"
OFFER_EXPIRY = "2026-09-01T00:00:00Z"


def test_the_run_judges_only_the_zone_whose_deadline_has_passed():
    """Alpha's window closed while Beta bought itself another month, so only Alpha is judged.

    PRD 3.4: "A zone is eligible for evaluation when its `campaign_status` is still `PREREG_OPEN`
    or `PREREG_EXTENDED` and its `prereg_deadline_at` is at or before the logical clock."

    PRD 3.4: "Both are terminal for the campaign dimension, both leave `construction_status`
    untouched, and either outcome increments the zone's `version` by 1."

    Design: Corner/endpoints/qualification_run_evaluates_the_past_deadline_zone_and_silently_skips_the_extended_one
    """
    base = setup_campaign_with_zone(
        campaign_overrides={"max_deadline_extensions": 2, "extension_grant_days": 30},
        zone_overrides={"household_count": 10},
    )
    alpha_id = base["zone"]["id"]
    beta = make_zone(
        base["campaign"]["id"], name="Zone Beta", zone_code="B1", household_count=10
    )
    extended = validate_success(
        api_client.extend_build_zone_deadline(beta["id"], PM), 200
    )
    assert_instant_equals(
        extended["prereg_deadline_at"], BETA_DEADLINE, "prereg_deadline_at"
    )
    set_clock(CLOCK_PAST_ALPHA_DEADLINE)

    response = api_client.qualification_run(base["campaign"]["id"], PM)

    evaluated, _meta = validate_unpaginated(response, 200)
    assert len(evaluated) == 1, evaluated
    judged = evaluated[0]
    assert_build_zone(judged)
    assert judged["id"] == alpha_id, judged["id"]
    assert judged["campaign_status"] == "NOT_QUALIFIED", judged["campaign_status"]
    assert_pct(judged["final_rate_pct"], 0.00, "final_rate_pct")
    assert judged["final_qualifying_count"] == 0, judged["final_qualifying_count"]
    skipped = read_zone(beta["id"])
    assert_build_zone(skipped)
    assert skipped["campaign_status"] == "PREREG_EXTENDED", skipped["campaign_status"]
    assert skipped["final_rate_pct"] is None, skipped["final_rate_pct"]
    assert skipped["final_qualifying_count"] is None, skipped
    assert skipped["version"] == extended["version"], skipped["version"]


def test_the_campaigns_zone_count_follows_the_zones_and_reads_to_any_role():
    """Nobody writes the count: carving two zones is what makes the campaign report two.

    PRD 3.1: "A freshly created campaign reports `zone_count` as 0; thereafter `zone_count` is
    simply the number of build zones whose `campaign_id` names this campaign, with no filtering by
    either state dimension."

    Design: Corner/endpoints/campaign_zone_count_is_a_derived_read
    """
    set_clock()
    campaign = make_campaign()
    assert_campaign(campaign)
    assert campaign["zone_count"] == 0, campaign["zone_count"]

    alpha = make_zone(campaign["id"], household_count=10)
    beta = make_zone(
        campaign["id"], name="Zone Beta", zone_code="B1", household_count=40
    )

    reread = validate_success(api_client.get_campaign(campaign["id"], COORDINATOR), 200)
    assert_campaign(reread)
    assert reread["zone_count"] == 2, reread["zone_count"]
    rows, _meta = assert_page(
        api_client.list_build_zones(PM, params={"campaign_id": campaign["id"]}),
        total_count=2,
        row_count=2,
    )
    assert [row["id"] for row in rows] == [alpha["id"], beta["id"]], rows


def test_only_the_accepted_pole_quote_lands_on_the_zones_make_ready_bill():
    """Two surveyed quotes, one accepted and one denied: the bill carries exactly the accepted one.

    PRD 3.5: "A zone's `make_ready_cost_cents` is therefore the sum of `make_ready_cost_cents` over
    just those of its pole-attachment requests whose status is `ACCEPTED` or `ATTACHED`; a request
    still `REQUESTED` or `SURVEYED`, and a request `DENIED`, all contribute nothing."

    PRD 2.6: "It reads `BLOCKED` when `construction_status` is `NOT_STARTED` and none of the zone's
    required permit types has an `APPROVED` application; `PERMIT_PENDING` when at least one
    required permit type still lacks an `APPROVED` application; `POLE_PENDING` when every required
    permit type has an `APPROVED` application but no pole-attachment request of the zone has
    reached `ATTACHED`; `SUSPENDED` whenever `construction_status` is `SUSPENDED`; and `READY` in
    every remaining case."

    Design: Corner/endpoints/pole_acceptance_rolls_the_quote_into_the_zone_make_ready_cost
    """
    base = setup_campaign_with_zone(zone_overrides={"household_count": 10})
    zone_id = base["zone"]["id"]
    first = make_pole_request(
        zone_id,
        target_status="SURVEYED",
        make_ready_cost_cents=45600,
        utility_owner="Aurora Power",
        pole_count=12,
    )
    second = make_pole_request(
        zone_id,
        target_status="SURVEYED",
        make_ready_cost_cents=90000,
        utility_owner="Aurora Telecom",
        pole_count=20,
    )
    assert_cents(read_zone(zone_id)["make_ready_cost_cents"], 0, "make_ready_cost_cents")

    validate_success(
        api_client.decide_pole_attachment_request(
            first["id"], pole_decision_payload("ACCEPT"), PM
        ),
        200,
    )
    assert_cents(
        read_zone(zone_id)["make_ready_cost_cents"], 45600, "make_ready_cost_cents"
    )

    denied = validate_success(
        api_client.decide_pole_attachment_request(
            second["id"],
            pole_decision_payload("DENY", denial_reason="CAPACITY_FULL"),
            UTILITY,
        ),
        200,
    )

    assert_pole_attachment_request(denied)
    assert denied["status"] == "DENIED", denied["status"]
    assert denied["denial_reason"] == "CAPACITY_FULL", denied["denial_reason"]
    settled = read_zone(zone_id)
    assert_build_zone(settled)
    assert_cents(settled["make_ready_cost_cents"], 45600, "make_ready_cost_cents")
    assert settled["construction_status"] == "NOT_STARTED", settled
    assert settled["suspension_reason"] is None, settled["suspension_reason"]
    assert settled["readiness_posture"] == "BLOCKED", settled["readiness_posture"]


def test_an_option_published_under_another_campaign_is_invisible_to_the_selection():
    """The only option that physically fits belongs to a different campaign, so the pool is empty.

    PRD 3.2: "The candidate pool is drawn from the options of the campaign that owns the address's
    zone, keeping only those whose `option_status` is `ENABLED`, whose `max_serviceable_distance_m`
    is greater than or equal to the address's `distance_to_node_m` - equality at the boundary is
    eligible - and whose `supports_mdu` is true whenever the address's `dwelling_type` is `MDU`,
    with no MDU requirement for a single-family address."

    PRD 3.2: "If the pool is empty the request is refused with
    `ERR_NO_FALLBACK_OPTION_AVAILABLE`."

    Design: Corner/endpoints/fallback_offer_only_sees_options_of_the_addresses_own_campaign
    """
    base = setup_campaign_with_zone(zone_overrides={"household_count": 10})
    other_campaign = make_campaign(name="Fiberhood East")
    address = make_address(
        base["zone"]["id"], street_address="12 Quarry Rd", distance_to_node_m=400
    )
    set_serviceability(
        address["id"], "NOT_SERVICEABLE", not_serviceable_reason="EXCESSIVE_DISTANCE"
    )
    granted = grant_unserved_exception(
        address["id"], exception_reason="No route to the node; resident wants an alternative."
    )
    stranded_option = make_fallback_option(
        other_campaign["id"],
        technology="FIXED_WIRELESS",
        min_downstream_mbps=400,
        monthly_price_cents=5000,
        max_serviceable_distance_m=5000,
        priority_rank=1,
    )
    account = make_account(2)

    response = api_client.create_fallback_offer(
        address["id"], fallback_offer_payload(account["id"], OFFER_EXPIRY), PM
    )

    validate_error(response, ApiErrorId.ERR_NO_FALLBACK_OPTION_AVAILABLE, 409)
    assert_fallback_option(stranded_option)
    assert stranded_option["option_status"] == "ENABLED", stranded_option
    assert stranded_option["max_serviceable_distance_m"] == 5000, stranded_option
    assert_total_count(
        api_client.list_fallback_offers(PM, params={"service_address_id": address["id"]}),
        0,
    )
    assert_service_address(granted)
    settled = read_address(address["id"])
    assert settled["exception_status"] == "GRANTED", settled["exception_status"]
    assert settled["active_fallback_technology"] is None, settled


def test_a_crew_round_trips_through_create_read_and_a_type_filtered_list():
    """The supplied capacity parameters survive the read, and the second crew shows the defaults.

    PRD 3.8: "Two capacity parameters are optional: `travel_buffer_minutes`, the trailing buffer
    appended to every one of this crew's windows for both conflict detection and capacity
    accounting, defaulting to 30 and constrained to between 0 and 240 inclusive; and
    `daily_capacity_minutes`, the maximum occupied minutes the crew may hold on any single UTC
    calendar date, defaulting to 480 - eight hours - and constrained to between 60 and 1440
    inclusive."

    PRD 3.8: "Both `booked_minutes_total` and `scheduled_appointment_count` start at 0."

    Design: Corner/endpoints/install_crew_create_read_and_filtered_list_round_trip
    """
    set_clock()

    response = api_client.create_install_crew(
        install_crew_payload(
            name="Bury Crew 1",
            crew_type="BURY",
            travel_buffer_minutes=45,
            daily_capacity_minutes=600,
        ),
        COORDINATOR,
    )

    bury = validate_success(response, 201)
    assert_install_crew(bury)
    assert bury["booked_minutes_total"] == 0, bury["booked_minutes_total"]
    assert bury["scheduled_appointment_count"] == 0, bury["scheduled_appointment_count"]
    assert bury["version"] == 1, bury["version"]

    aerial = validate_success(
        api_client.create_install_crew(
            install_crew_payload(name="Aerial Crew 1", crew_type="AERIAL"), COORDINATOR
        ),
        201,
    )
    assert_install_crew(aerial)
    assert aerial["travel_buffer_minutes"] == 30, aerial["travel_buffer_minutes"]
    assert aerial["daily_capacity_minutes"] == 480, aerial["daily_capacity_minutes"]

    reread = validate_success(api_client.get_install_crew(bury["id"], PM), 200)
    assert_install_crew(reread)
    assert reread["name"] == "Bury Crew 1", reread["name"]
    assert reread["travel_buffer_minutes"] == 45, reread["travel_buffer_minutes"]
    assert reread["daily_capacity_minutes"] == 600, reread["daily_capacity_minutes"]
    rows, _meta = assert_page(
        api_client.list_install_crews(COORDINATOR, params={"crew_type": "BURY"}),
        total_count=1,
        row_count=1,
    )
    assert [row["id"] for row in rows] == [bury["id"]], rows


def test_signing_off_a_fiberhood_that_never_broke_ground_is_a_state_error():
    """There is no restoration outstanding, and the refusal is still about the missing build.

    PRD 3.6: "Declaring a fiberhood finished moves `construction_status` `IN_CONSTRUCTION ->
    SERVICE_READY`, which is terminal."

    PRD 2.10: "The target row is in a state from which the requested transition exists. This is
    checked before any capacity, temporal or fiscal rule, so a terminal row always reports its
    state rather than a downstream business failure."

    Design: Corner/endpoints/construction_complete_on_a_zone_that_never_broke_ground_is_refused
    """
    base = setup_campaign_with_zone(zone_overrides={"household_count": 10})
    zone_id = base["zone"]["id"]
    version_before = base["zone"]["version"]
    assert base["zone"]["outstanding_restoration_count"] == 0, base["zone"]

    response = api_client.complete_construction(zone_id, PM)

    validate_error(response, ApiErrorId.ERR_BUILD_ZONE_STATE_INVALID, 409)
    settled = read_zone(zone_id)
    assert_build_zone(settled)
    assert settled["construction_status"] == "NOT_STARTED", settled
    assert settled["version"] == version_before, settled["version"]


def test_an_exception_cannot_be_granted_before_the_resident_has_asked_for_one():
    """GRANT has no admissible source at NONE, and walking the path properly reaches DENIED.

    PRD 3.2: "`GRANT` moves `REQUESTED -> GRANTED` and likewise requires `serviceability` to be
    `NOT_SERVICEABLE`; a granted exception is precisely what authorizes an alternative-technology
    offer for the address."

    PRD 3.2: "Granting an exception that was never requested, or attempting an offer for an address
    whose `exception_status` is not `GRANTED`, is `ERR_SERVICE_ADDRESS_STATE_INVALID`."

    Design: Corner/endpoints/unserved_exception_grant_without_a_prior_request_is_refused
    """
    base = setup_campaign_with_zone(zone_overrides={"household_count": 10})
    address = make_address(
        base["zone"]["id"], street_address="12 Quarry Rd", distance_to_node_m=400
    )
    assert address["exception_status"] == "NONE", address["exception_status"]
    set_serviceability(
        address["id"], "NOT_SERVICEABLE", not_serviceable_reason="EXCESSIVE_DISTANCE"
    )

    premature = api_client.unserved_exception(
        address["id"], unserved_exception_payload("GRANT"), PM
    )

    validate_error(premature, ApiErrorId.ERR_SERVICE_ADDRESS_STATE_INVALID, 409)
    requested = validate_success(
        api_client.unserved_exception(
            address["id"],
            unserved_exception_payload("REQUEST", exception_reason="Beyond aerial reach."),
            PM,
        ),
        200,
    )
    assert_service_address(requested)
    assert requested["exception_status"] == "REQUESTED", requested["exception_status"]
    assert requested["exception_reason"] == "Beyond aerial reach.", requested
    assert requested["serviceability"] == "NOT_SERVICEABLE", requested["serviceability"]

    denied = validate_success(
        api_client.unserved_exception(
            address["id"], unserved_exception_payload("DENY"), PM
        ),
        200,
    )
    assert_service_address(denied)
    assert denied["exception_status"] == "DENIED", denied["exception_status"]
    assert denied["serviceability"] == "NOT_SERVICEABLE", denied["serviceability"]
