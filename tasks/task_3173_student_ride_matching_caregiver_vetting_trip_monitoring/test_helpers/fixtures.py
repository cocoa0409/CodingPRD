"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty database. Setup calls use
``get_success_data()`` so a broken precondition reports "Setup failed" rather
than a confusing assertion error further down.

Two conventions matter here:

* The logical clock is pinned explicitly before any temporal decision. A
  one-off ride request must be approved with at least its ``min_lead_time_hours``
  of notice, so fixtures create the request while the clock is still well before
  the window and only then move the clock forward.
* An ownership-gated call always uses ``make_driver_headers(driver["id"])``.
"""
from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_client import api_client
from test_helpers.constants import (
    DEFAULT_CLOCK,
    NON_EXISTENT_RIDER_UUID,
    create_background_check_payload,
    create_contract_payload,
    create_district_payload,
    create_driver_payload,
    create_geofence_payload,
    create_inspection_payload,
    create_rider_payload,
    create_ride_request_payload,
    dropoff_handoff_payload,
    pickup_handoff_payload,
)
from test_helpers.test_users import TEST_USERS, make_driver_headers


def _admin():
    return TEST_USERS["district_admin_headers"]


def _support():
    return TEST_USERS["support_center_headers"]


def _platform():
    return TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Pin the logical clock. Returns the raw response."""
    return api_client.set_clock({"to_iso8601": to_iso8601}, _platform())


def reset_clock():
    set_clock(DEFAULT_CLOCK)


def read_district(district_id):
    return get_success_data(api_client.get_district(district_id, _admin()))


def read_driver(driver_id):
    return get_success_data(api_client.get_driver(driver_id, _admin()))


def read_trip(trip_id):
    return get_success_data(api_client.get_trip(trip_id, _admin()))


def read_rider(rider_id):
    return get_success_data(api_client.get_rider(rider_id, _admin()))


def read_request(request_id):
    return get_success_data(api_client.get_ride_request(request_id, _admin()))


# ---------------------------------------------------------------------------
# Tier 1 — primitives
# ---------------------------------------------------------------------------

def setup_district(**overrides):
    """Self-register a district and return the created District."""
    resp = api_client.create_district(
        create_district_payload(**overrides), TEST_USERS["anonymous_headers"]
    )
    return get_success_data(resp, 201)


def setup_rider(district_id, **overrides):
    """Register a student in a district and return the created Rider."""
    resp = api_client.create_rider(
        create_rider_payload(district_id, **overrides),
        _admin(),
    )
    return get_success_data(resp, 201)


def setup_contract(district_id, activate=True, **overrides):
    """Draft a contract, optionally activating it. Returns the Contract."""
    resp = api_client.create_contract(
        create_contract_payload(district_id, **overrides), _admin()
    )
    contract = get_success_data(resp, 201)
    if activate:
        contract = get_success_data(
            api_client.activate_contract(contract["id"], _admin())
        )
    return contract


def onboard_driver(**overrides):
    """Onboard a driver. Returns a Driver in PENDING status."""
    resp = api_client.create_driver(create_driver_payload(**overrides), _admin())
    return get_success_data(resp, 201)


def open_clearance(driver_id, check_type="FINGERPRINT_FBI",
                   expires_on="2027-03-01", clear=True, reference_code=None):
    """Open a background check and optionally clear it. Returns the check."""
    payload = create_background_check_payload(
        check_type=check_type, expires_on=expires_on
    )
    if reference_code:
        payload["reference_code"] = reference_code
    resp = api_client.open_background_check(driver_id, payload, _admin())
    check = get_success_data(resp, 201)
    if clear:
        check = get_success_data(
            api_client.clear_background_check(check["id"], _admin())
        )
    return check


def record_inspection(driver_id, seat_count=6, expires_on="2027-03-01",
                      vehicle_class="SUV", child_seat_type="BOOSTER",
                      inspector_note="clean", expect_success=True):
    """Record a vehicle inspection.

    Returns the created inspection when ``expect_success``; otherwise returns the
    raw response so a caller can assert the refusal (a shortfall or wrong roster
    state is a legitimate outcome this call must be able to observe).
    """
    resp = api_client.record_inspection(
        driver_id,
        create_inspection_payload(
            vehicle_class=vehicle_class,
            seat_count=seat_count,
            child_seat_type=child_seat_type,
            inspector_note=inspector_note,
            expires_on=expires_on,
        ),
        _admin(),
    )
    if not expect_success:
        return resp
    return get_success_data(resp, 201)


def vet_driver(seat_capacity=6, seat_count=6, caregiver_experience_months=18,
               vehicle_class="SUV", clearance_expires_on="2027-03-01",
               inspect_expires_on="2027-03-01", **driver_overrides):
    """Walk the qualification pipeline to a vetted ACTIVE driver.

    PENDING -> BACKGROUND_CHECK (a cleared fingerprint clearance)
    -> INSPECTION (a recorded inspection) -> ACTIVE (the attestation), which
    leaves ``approved_seat_count`` at the smaller of the declared capacity and
    the largest passing inspection's seat count.

    Extra keyword arguments are forwarded to the onboarding payload, so callers
    can distinguish otherwise identical drivers (for example a distinct
    ``full_name``/``phone``).

    Returns the refreshed Driver with the created clearance/inspection ids
    attached under underscore-prefixed keys.
    """
    driver = onboard_driver(
        caregiver_experience_months=caregiver_experience_months,
        vehicle_class=vehicle_class,
        seat_capacity=seat_capacity,
        **driver_overrides,
    )
    driver_id = driver["id"]
    check = open_clearance(
        driver_id, "FINGERPRINT_FBI", clearance_expires_on, clear=True
    )
    inspection = record_inspection(
        driver_id, seat_count=seat_count, expires_on=inspect_expires_on,
        vehicle_class=vehicle_class,
    )
    get_success_data(api_client.attest_inspection(inspection["id"], _admin()))
    refreshed = read_driver(driver_id)
    refreshed["_clearance_id"] = check["id"]
    refreshed["_inspection_id"] = inspection["id"]
    return refreshed


def create_request(district, rider, submit=True, approve=True, **overrides):
    """Open a ride request and optionally submit and approve it.

    Approval is only attempted once the request has been submitted, because a
    DRAFT request is not approvable (PRD §3.4: "The request must be in
    `SUBMITTED`"). Passing ``submit=False`` therefore yields a DRAFT request
    whatever ``approve`` says, and ``approve=False`` yields a SUBMITTED one.

    ``district`` must carry a ``version`` read after any preceding district
    mutation. Returns the RideRequest.
    """
    resp = api_client.create_ride_request(
        create_ride_request_payload(
            district["id"], rider["id"], district["version"], **overrides
        ),
        _admin(),
    )
    request = get_success_data(resp, 201)
    if submit:
        request = get_success_data(
            api_client.submit_ride_request(request["id"], _admin())
        )
        if approve:
            request = get_success_data(
                api_client.approve_ride_request(request["id"], _admin())
            )
    return request


def schedule_request(request, scheduled_date="2026-09-10"):
    """Schedule a one-off request. Returns (RideRequest, Trip)."""
    resp = api_client.schedule_ride_request(
        request["id"], {"scheduled_date": scheduled_date}, _admin()
    )
    trips = get_success_data(resp, 201)
    return read_request(request["id"]), trips[0]


def setup_one_off_request(district_id, rider_id, scheduled_date="2026-09-10",
                          window_start_at="2026-09-10T07:30:00Z",
                          window_end_at="2026-09-10T07:50:00Z",
                          max_window_minutes=30, **overrides):
    """Create, approve and schedule a one-off request. Returns (request, trip)."""
    district = read_district(district_id)
    request = create_request(
        district,
        {"id": rider_id},
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        max_window_minutes=max_window_minutes,
        **overrides,
    )
    return schedule_request(request, scheduled_date=scheduled_date)


def assign_and_accept(trip_id, driver_id):
    """Pin the dispatch candidate and accept it as the assigned driver."""
    headers = make_driver_headers(driver_id)
    get_success_data(api_client.dispatch_candidate(trip_id, _admin()))
    get_success_data(api_client.accept_trip(trip_id, headers))
    return read_trip(trip_id)


def drive_trip(trip_id, driver_id, pickup_party="Ana Ruiz",
               dropoff_party="Lincoln Elementary", billable_miles=3.0,
               dropoff_expected_party="SCHOOL_STAFF", stop_after=None):
    """Walk a trip through the execution pipeline.

    ``stop_after`` names the last step to run: one of ``accept``,
    ``awaiting_student``, ``student_onboard``, ``in_transit``, ``completed``.
    Returns the Trip as read back after the final step.
    """
    headers = make_driver_headers(driver_id)
    get_success_data(api_client.dispatch_candidate(trip_id, _admin()))
    get_success_data(api_client.accept_trip(trip_id, headers))
    if stop_after == "accept":
        return read_trip(trip_id)
    get_success_data(api_client.arrive_trip(trip_id, headers))
    if stop_after == "awaiting_student":
        return read_trip(trip_id)
    get_success_data(
        api_client.record_handoff(
            trip_id, pickup_handoff_payload(pickup_party), headers
        )
    )
    if stop_after == "student_onboard":
        return read_trip(trip_id)
    get_success_data(api_client.depart_trip(trip_id, headers))
    if stop_after == "in_transit":
        return read_trip(trip_id)
    get_success_data(
        api_client.record_handoff(
            trip_id,
            dropoff_handoff_payload(
                dropoff_party,
                expected_party=dropoff_expected_party,
                billable_miles=billable_miles,
            ),
            headers,
        )
    )
    return read_trip(trip_id)


def fail_dropoff(trip_id, driver_id, dropoff_party="Unlisted Person",
                 billable_miles=3.0):
    """Take a trip to COMPLETED through a failing dropoff handoff.

    Returns (handoff data, Trip).
    """
    headers = make_driver_headers(driver_id)
    drive_trip(trip_id, driver_id, stop_after="in_transit")
    resp = api_client.record_handoff(
        trip_id,
        dropoff_handoff_payload(
            dropoff_party,
            expected_party="AUTHORIZED_ADULT",
            billable_miles=billable_miles,
        ),
        headers,
    )
    return get_success_data(resp, 201), read_trip(trip_id)


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------

def setup_scheduled_trip(window_start_at="2026-09-10T07:30:00Z",
                         window_end_at="2026-09-10T07:50:00Z",
                         scheduled_date="2026-09-10", vet=True,
                         district_overrides=None, rider_overrides=None,
                         contract_overrides=None, planned_miles=3.0,
                         max_window_minutes=30):
    """District + rider + ACTIVE contract + vetted driver + one SCHEDULED trip.

    The clock is left at its startup default while the request is created, so
    the twelve-hour lead-time gate is satisfied by a wide margin; move the clock
    inside the test when a temporal rule needs it.

    Returns a dict with district, rider, contract, driver, driver_headers,
    trip_request and trip.
    """
    reset_clock()
    district = setup_district(**(district_overrides or {}))
    rider = setup_rider(district["id"], **(rider_overrides or {}))
    contract = setup_contract(district["id"], **(contract_overrides or {}))
    driver = vet_driver() if vet else None
    request, trip = setup_one_off_request(
        district["id"], rider["id"], scheduled_date=scheduled_date,
        window_start_at=window_start_at, window_end_at=window_end_at,
        planned_miles=planned_miles, max_window_minutes=max_window_minutes,
    )
    return {
        "district": read_district(district["id"]),
        "rider": rider,
        "contract": contract,
        "driver": driver,
        "driver_headers": make_driver_headers(driver["id"]) if driver else None,
        "trip_request": request,
        "trip": trip,
    }


def setup_two_districts():
    """Two independent districts, each with its own rider and ACTIVE contract."""
    reset_clock()
    district_a = setup_district()
    rider_a = setup_rider(district_a["id"])
    contract_a = setup_contract(district_a["id"])

    district_b = setup_district(
        name="Spring Branch ISD",
        billing_email="ap@sb.example",
        contract_rate_per_ride_cents=4900,
        contract_rate_per_mile_cents=200,
    )
    rider_b = setup_rider(
        district_b["id"],
        full_name="Hana Ito",
        school_name="Spring Branch Elementary",
        home_address="3 Fern St",
        emergency_contact_phone="5550107",
    )
    contract_b = setup_contract(
        district_b["id"], per_ride_rate_cents=4900, per_mile_rate_cents=200,
        minimum_billable_cents=0,
    )
    return {
        "district_a": district_a, "rider_a": rider_a, "contract_a": contract_a,
        "district_b": district_b, "rider_b": rider_b, "contract_b": contract_b,
    }


def setup_vetted_driver_only(seat_capacity=6, seat_count=6,
                             caregiver_experience_months=18,
                             vehicle_class="SUV"):
    """A district plus one fully vetted ACTIVE driver holding no trips."""
    reset_clock()
    district = setup_district()
    driver = vet_driver(
        seat_capacity=seat_capacity, seat_count=seat_count,
        caregiver_experience_months=caregiver_experience_months,
        vehicle_class=vehicle_class,
    )
    return {
        "district": district, "driver": driver,
        "driver_headers": make_driver_headers(driver["id"]),
    }


def setup_two_vetted_drivers():
    """Two identically vetted ACTIVE drivers, the first onboarded first.

    With no overlapping trips, equal strike counts and equal compliance dates
    the ranking keys tie completely, so the fallback must resolve the pick.
    """
    reset_clock()
    district = setup_district()
    rider = setup_rider(district["id"])
    contract = setup_contract(district["id"])
    first = vet_driver()
    second = vet_driver(full_name="Fay Okoro", phone="5550112",
                        caregiver_experience_months=18)
    request, trip = setup_one_off_request(
        district["id"], rider["id"], scheduled_date="2026-09-11",
        window_start_at="2026-09-11T07:30:00Z",
        window_end_at="2026-09-11T07:50:00Z",
    )
    return {
        "district": district, "rider": rider, "contract": contract,
        "first_driver": first, "second_driver": second,
        "trip_request": request, "trip": trip,
    }


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------

def complete_trip(district_id, rider_id, driver_id, scheduled_date="2026-09-10",
                  planned_miles=8.0, billable_miles=8.0,
                  window_start_at="2026-09-10T07:30:00Z",
                  window_end_at="2026-09-10T07:50:00Z"):
    """Build one completed trip from scratch and return (Trip, RideRequest)."""
    request, trip = setup_one_off_request(
        district_id, rider_id, scheduled_date=scheduled_date,
        window_start_at=window_start_at, window_end_at=window_end_at,
        planned_miles=planned_miles,
    )
    completed = drive_trip(
        trip["id"], driver_id, pickup_party="Ana Ruiz",
        dropoff_party="Lincoln Elementary", billable_miles=billable_miles,
    )
    return completed, request


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_completed_trip(district_overrides=None, contract_overrides=None,
                         planned_miles=8.0, billable_miles=8.0,
                         credit_cents=None, rider_overrides=None):
    """District + rider + vetted driver + one completed round trip.

    With the standard terms (per ride 5300, per mile 215) an eight-mile
    completed trip settles at 2 x 5300 + 8.0 x 215 = 12320 cents, and its quote
    reads the same figure because it prices the identical planned distance.
    Returns a dict with every handle the pricing tests need.
    """
    reset_clock()
    district = setup_district(**(district_overrides or {}))
    rider = setup_rider(district["id"], **(rider_overrides or {}))
    contract = setup_contract(district["id"], **(contract_overrides or {}))
    driver = vet_driver()
    if credit_cents:
        district = get_success_data(
            api_client.adjust_credit(
                district["id"],
                {"amount_cents": credit_cents, "reason": "service credit"},
                _admin(),
            )
        )
    trip, request = complete_trip(
        district["id"], rider["id"], driver["id"],
        planned_miles=planned_miles, billable_miles=billable_miles,
    )
    return {
        "district": read_district(district["id"]), "rider": rider,
        "driver": driver, "contract": contract, "trip": trip,
        "trip_request": request, "driver_headers": make_driver_headers(driver["id"]),
    }


def setup_absence_scenario(window_start_at="2026-09-10T07:30:00Z",
                           window_end_at="2026-09-10T07:50:00Z",
                           max_window_minutes=30,
                           program_type="FOSTER_CARE", spi_level=1,
                           arrival_clock="2026-09-10T07:30:00Z"):
    """A vetted driver arrived at an AWAITING_STUDENT trip, ready for a report.

    The clock must read the arrival instant while the trip arrives, because the
    accrued wait-time block count measures "the elapsed whole minutes between the
    logical clock instant and the trip's arrival". Parking the clock at the
    arrival instant afterwards keeps the elapsed wait at the arrival boundary, so
    the caller decides how much wait to allow before reporting an absence.
    """
    scenario = setup_scheduled_trip(
        window_start_at=window_start_at, window_end_at=window_end_at,
        max_window_minutes=max_window_minutes,
        rider_overrides={"program_type": program_type, "spi_level": spi_level},
    )
    driver_id = scenario["driver"]["id"]
    set_clock(arrival_clock)
    drive_trip(scenario["trip"]["id"], driver_id, stop_after="awaiting_student")
    scenario["trip"] = read_trip(scenario["trip"]["id"])
    return scenario


def setup_driver_with_strikes(strike_target, program_type="FOSTER_CARE",
                              spi_level=1, seat_capacity=6,
                              vehicle_class="SUV", first_date_day=11):
    """A vetted driver carrying ``strike_target`` strikes from HIGH absences.

    Each absence is reported on its own dated trip once the accrued wait has
    reached two blocks; a two-block wait on a weighted program with a late
    dispatch grades HIGH, which both locks the trip and consumes a strike.
    ``first_date_day`` shifts the run of absence dates.
    """
    reset_clock()
    district = setup_district()
    rider = setup_rider(
        district["id"], program_type=program_type, spi_level=spi_level,
        home_address="77 Cedar St",
    )
    contract = setup_contract(district["id"])
    driver = vet_driver(
        seat_capacity=seat_capacity, seat_count=seat_capacity,
        vehicle_class=vehicle_class,
    )
    driver_headers = make_driver_headers(driver["id"])
    absence_trips = []
    for index in range(strike_target):
        day = first_date_day + index
        date = f"2026-09-{day:02d}"
        request, trip = setup_one_off_request(
            district["id"], rider["id"], scheduled_date=date,
            window_start_at=f"{date}T07:30:00Z",
            window_end_at=f"{date}T07:50:00Z",
        )
        set_clock(f"{date}T07:30:00Z")
        drive_trip(trip["id"], driver["id"], stop_after="awaiting_student")
        set_clock(f"{date}T07:54:00Z")
        get_success_data(
            api_client.report_exception(
                trip["id"],
                {"issue": "RIDER_NOT_PRESENT", "note": "absence"},
                driver_headers,
            )
        )
        absence_trips.append(read_trip(trip["id"]))
    return {
        "district": district, "rider": rider, "contract": contract,
        "driver": read_driver(driver["id"]), "driver_headers": driver_headers,
        "absence_trips": absence_trips,
    }


def setup_strike_cascade_scenario(pre_strikes=2):
    """A driver carrying ``pre_strikes`` strikes, with an unresolved absence open.

    The scenario opens a LOW-graded absence first (a two-block wait on a
    general-education student dispatched on time grades below four points, so no
    strike is consumed) while the driver is still the district's only driver, so
    the selection rule pins them for that date; its incident is left REPORTED,
    for the caller to put UNDER_REVIEW.

    The ``pre_strikes`` HIGH absences are then accumulated on later dates, each
    consuming a strike. At or above the suspension threshold the driver is
    SUSPENDED by that cascade, and because a suspension cascade only cancels
    trips still SCHEDULED or DRIVER_EN_ROUTE, the low-grade absence trip — long
    since CANCELLED — survives it.

    Finally two 09-15 trips are built: one for the driver under test and one for
    an independent driver, so a cascade can be told apart from a first-hop
    fan-out. When the driver under test is already SUSPENDED by their own
    pre-strikes they cannot be dispatched at all, so the scoped trip is absent
    (``scoped_trip is None``) and only ``other_trip`` exists.

    Returns a dict with district, rider, driver, incident, scoped_trip,
    other_trip and others' handles.
    """
    reset_clock()
    district = setup_district()
    rider = setup_rider(
        district["id"], program_type="FOSTER_CARE", spi_level=1,
        home_address="77 Cedar St",
    )
    contract = setup_contract(district["id"])
    driver = vet_driver(seat_capacity=6, seat_count=6)
    driver_headers = make_driver_headers(driver["id"])
    district_id = district["id"]

    # The unresolved low-grade absence. It is built while the driver under test
    # is still the district's only driver, so the selection rule pins them for
    # the date, and it is graded LOW (no strike, posture stays NORMAL).
    low_rider = setup_rider(
        district_id, full_name="Kai Moss", home_address="2 Willow St",
        program_type="GENERAL", spi_level=1,
        emergency_contact_phone="5550110",
    )
    request, trip = setup_one_off_request(
        district_id, low_rider["id"], scheduled_date="2026-09-10",
        window_start_at="2026-09-10T07:30:00Z",
        window_end_at="2026-09-10T08:30:00Z", max_window_minutes=90,
    )
    set_clock("2026-09-10T07:30:00Z")
    drive_trip(trip["id"], driver["id"], stop_after="awaiting_student")
    set_clock("2026-09-10T07:54:00Z")
    response = api_client.report_exception(
        trip["id"],
        {"issue": "RIDER_REFUSED_BOARDING", "note": "third report"},
        driver_headers,
    )
    absence_trip = get_success_data(response, 201)
    incidents = get_success_data(
        api_client.list_trip_safety_incidents(absence_trip["id"], _support())
    )
    incident = incidents[0]

    # The HIGH absences that carry the driver up to the strike target, on later
    # dates so they never collide with the low-grade absence trip.
    pre_absence_trips = []
    for index in range(pre_strikes):
        date = f"2026-09-{12 + index:02d}"
        _, high_trip = setup_one_off_request(
            district_id, rider["id"], scheduled_date=date,
            window_start_at=f"{date}T07:30:00Z",
            window_end_at=f"{date}T07:50:00Z",
        )
        set_clock(f"{date}T07:30:00Z")
        drive_trip(high_trip["id"], driver["id"], stop_after="awaiting_student")
        set_clock(f"{date}T07:54:00Z")
        get_success_data(
            api_client.report_exception(
                high_trip["id"],
                {"issue": "RIDER_NOT_PRESENT", "note": "absence"},
                driver_headers,
            )
        )
        pre_absence_trips.append(read_trip(high_trip["id"]))

    # The independent driver is onboarded only now, so the driver under test was
    # the sole eligible candidate while their own trips were being built. The
    # two 09-15 trips are ranked so that the scoped trip pins the driver under
    # test (built first, then left holding an overlapping 09-15 interval) and
    # the independent trip pins the independent driver.
    scoped_trip = None
    if read_driver(driver["id"])["status"] == "ACTIVE":
        _, scoped_trip = setup_one_off_request(
            district_id, rider["id"], scheduled_date="2026-09-15",
            window_start_at="2026-09-15T07:30:00Z",
            window_end_at="2026-09-15T07:50:00Z",
        )
        assign_and_accept(scoped_trip["id"], driver["id"])
    other_rider = setup_rider(
        district_id, full_name="Eli Ward", home_address="88 Cedar St",
        emergency_contact_phone="5550105",
    )
    other_driver = vet_driver(
        full_name="Fay Okoro", phone="5550112", caregiver_experience_months=24,
        vehicle_class="SEDAN", seat_capacity=4, seat_count=4,
    )
    other_headers = make_driver_headers(other_driver["id"])
    _, other_trip = setup_one_off_request(
        district_id, other_rider["id"], scheduled_date="2026-09-15",
        window_start_at="2026-09-15T08:00:00Z",
        window_end_at="2026-09-15T08:20:00Z",
    )
    assign_and_accept(other_trip["id"], other_driver["id"])

    return {
        "district": read_district(district_id),
        "rider": rider,
        "low_rider": low_rider,
        "other_rider": other_rider,
        "driver": read_driver(driver["id"]),
        "driver_headers": driver_headers,
        "other_driver": other_driver,
        "other_driver_headers": other_headers,
        "incident": incident,
        "absence_trip": absence_trip,
        "scoped_trip": read_trip(scoped_trip["id"]) if scoped_trip else None,
        "other_trip": read_trip(other_trip["id"]),
        "pre_absence_trips": pre_absence_trips,
    }


def setup_fingerprint_revocation_scenario(scheduled_date="2026-09-11",
                                          window_start="2026-09-11T07:30:00Z",
                                          window_end="2026-09-11T07:50:00Z"):
    """A vetted driver with an accepted trip and one revocable clearance.

    Returns the district, rider, driver (with seats), the trip in
    DRIVER_EN_ROUTE and the CLEARED fingerprint check about to be revoked.
    """
    reset_clock()
    district = setup_district()
    rider = setup_rider(
        district["id"], full_name="Gus Neal", home_address="5 Birch St",
        program_type="HOMELESS_MCKINNEY_VENTO", emergency_contact_phone="5550106",
    )
    contract = setup_contract(district["id"])
    driver = vet_driver()
    request, trip = setup_one_off_request(
        district["id"], rider["id"], scheduled_date=scheduled_date,
        window_start_at=window_start, window_end_at=window_end,
    )
    assign_and_accept(trip["id"], driver["id"])
    return {
        "district": district, "rider": rider, "contract": contract,
        "driver": read_driver(driver["id"]),
        "driver_headers": make_driver_headers(driver["id"]),
        "clearance": get_success_data(
            api_client.list_driver_background_checks(driver["id"], _admin())
        )[0],
        "trip": read_trip(trip["id"]),
    }


def setup_rider_overlap_scenario():
    """One rider holding a SCHEDULED morning trip, plus a second request whose
    window opens exactly at the first trip's close instant."""
    reset_clock()
    district = setup_district()
    rider = setup_rider(
        district["id"], full_name="Pia Lund", home_address="19 Spruce St",
        program_type="HOMELESS_MCKINNEY_VENTO", emergency_contact_phone="5550117",
    )
    contract = setup_contract(district["id"])
    # One vetted driver is required for the first trip to be schedulable at all
    # (scheduling refuses a date with no eligible candidate). The second request
    # needs no second driver: the rider-side collision check runs ahead of the
    # candidate selection, so its own refusal is what the test observes.
    driver = vet_driver()
    first_request, first_trip = setup_one_off_request(
        district["id"], rider["id"], scheduled_date="2026-09-11",
        window_start_at="2026-09-11T07:30:00Z",
        window_end_at="2026-09-11T07:50:00Z",
    )
    second_request = create_request(
        read_district(district["id"]),
        rider,
        window_start_at="2026-09-11T07:50:00Z",
        window_end_at="2026-09-11T08:10:00Z",
        trip_type="ACTIVITY",
        planned_miles=2.0,
    )
    return {
        "district": district, "rider": rider, "contract": contract,
        "driver": driver, "driver_headers": make_driver_headers(driver["id"]),
        "first_request": first_request, "first_trip": first_trip,
        "second_request": second_request,
    }


def setup_driver_overlap_scenario():
    """A driver holding an accepted trip on 2026-09-11, plus the district.

    The trip requires a `WHEELCHAIR` specialty and the scenario's driver is the
    only `WHEELCHAIR_VAN` in the pool, because the selection rule ranks every
    eligible driver globally and would otherwise hand this district's date to
    the earliest-registered driver from any other district in the same run.
    """
    reset_clock()
    district = setup_district()
    rider = setup_rider(
        district["id"], full_name="Otto Reyes", home_address="15 Larch St",
        emergency_contact_phone="5550116",
    )
    contract = setup_contract(district["id"])
    driver = vet_driver(vehicle_class="WHEELCHAIR_VAN")
    request, trip = setup_one_off_request(
        district["id"], rider["id"], scheduled_date="2026-09-11",
        window_start_at="2026-09-11T07:30:00Z",
        window_end_at="2026-09-11T07:50:00Z",
        required_specialty="WHEELCHAIR",
    )
    assign_and_accept(trip["id"], driver["id"])
    return {
        "district": district, "rider": rider, "contract": contract,
        "driver": driver, "driver_headers": make_driver_headers(driver["id"]),
        "trip_request": request, "trip": read_trip(trip["id"]),
    }


def setup_recurring_series(days_of_week=(1, 2, 3, 4, 5),
                           series_effective_from="2026-09-14",
                           series_through_date="2026-09-18",
                           series_no_school_dates=(), schedule=True,
                           contract_billing_period="WEEKLY",
                           schedule_time="2026-09-11T18:00:00Z"):
    """District + rider + ACTIVE contract + vetted driver + a recurring series.

    The clock is parked at ``schedule_time`` (still inside the series window) so
    a later resume, which is gated on the logical clock date not having passed
    the series' ``series_through_date``, is legal.

    Returns a dict with district, rider, contract, driver, request and trips.
    """
    reset_clock()
    district = setup_district()
    rider = setup_rider(
        district["id"], full_name="Mira Sol", home_address="8 Poplar St",
        program_type="SPECIAL_EDUCATION", emergency_contact_phone="5550114",
    )
    contract = setup_contract(
        district["id"], billing_period=contract_billing_period
    )
    driver = vet_driver()
    set_clock(schedule_time)
    request = create_request(
        read_district(district["id"]),
        rider,
        window_start_at=f"{series_effective_from}T07:30:00Z",
        window_end_at=f"{series_effective_from}T07:50:00Z",
        is_recurring=True,
        days_of_week=list(days_of_week),
        series_effective_from=series_effective_from,
        series_through_date=series_through_date,
        series_no_school_dates=list(series_no_school_dates),
    )
    trips = []
    if schedule:
        trips = get_success_data(
            api_client.schedule_ride_request(request["id"], {}, _admin()), 201
        )
        request = read_request(request["id"])
    return {
        "district": district, "rider": rider, "contract": contract,
        "driver": driver, "request": request, "trips": trips,
    }


def setup_statement_ready(period_key="2026-09", period_start="2026-09-01",
                          period_end="2026-09-30", credit_cents=None,
                          minimum_billable_cents=0, district_overrides=None,
                          contract_overrides=None):
    """A district holding one completed September trip and an OPEN statement.

    Returns the completed-trip scenario plus the statement.
    """
    scenario = setup_completed_trip(
        district_overrides=district_overrides,
        contract_overrides=contract_overrides,
        credit_cents=credit_cents,
    )
    set_clock("2026-10-01T00:00:00Z")
    district = read_district(scenario["district"]["id"])
    statement = get_success_data(
        api_client.run_billing(
            district["id"],
            {
                "expected_district_version": district["version"],
                "period_key": period_key,
                "period_start": period_start,
                "period_end": period_end,
            },
            _admin(),
        ),
        201,
    )
    scenario["district"] = district
    scenario["statement"] = statement
    return scenario


def setup_locked_in_transit_trip(absence_count=3):
    """A trip left IN_TRANSIT whose driver carries the strike ceiling.

    The trip is driven to IN_TRANSIT first; the driver then accumulates
    ``absence_count`` HIGH absences on other dated trips, which suspends the
    driver once the count reaches the threshold. Because a suspension cascade
    only cancels trips still SCHEDULED or DRIVER_EN_ROUTE, the in-transit trip
    survives, and a monitoring sweep against it then synthesises an alert whose
    severity is driven to HIGH by the driver's strike count.

    Returns a dict with district, rider, driver, trip and the raised alerts.
    """
    reset_clock()
    district = setup_district()
    rider = setup_rider(
        district["id"], full_name="Dana Pike", home_address="77 Cedar St",
        program_type="FOSTER_CARE", emergency_contact_phone="5550104",
    )
    contract = setup_contract(district["id"])
    driver = vet_driver()
    driver_headers = make_driver_headers(driver["id"])

    request, trip = setup_one_off_request(
        district["id"], rider["id"], scheduled_date="2026-09-20",
        window_start_at="2026-09-20T07:30:00Z",
        window_end_at="2026-09-20T07:50:00Z",
    )
    drive_trip(trip["id"], driver["id"], stop_after="in_transit")

    for index in range(absence_count):
        day = 11 + index
        date = f"2026-09-{day:02d}"
        _, absence = setup_one_off_request(
            district["id"], rider["id"], scheduled_date=date,
            window_start_at=f"{date}T07:30:00Z",
            window_end_at=f"{date}T07:50:00Z",
        )
        set_clock(f"{date}T07:30:00Z")
        drive_trip(absence["id"], driver["id"], stop_after="awaiting_student")
        set_clock(f"{date}T07:54:00Z")
        get_success_data(
            api_client.report_exception(
                absence["id"],
                {"issue": "RIDER_NOT_PRESENT", "note": "absence"},
                driver_headers,
            )
        )

    set_clock("2026-09-20T08:30:00Z")
    get_success_data(
        api_client.monitor_sweep(
            {"trip_id": trip["id"]}, _support()
        )
    )
    return {
        "district": read_district(district["id"]),
        "rider": rider,
        "contract": contract,
        "driver": read_driver(driver["id"]),
        "driver_headers": driver_headers,
        "trip": read_trip(trip["id"]),
        "alerts": get_success_data(
            api_client.list_trip_alerts(trip["id"], _support())
        ),
    }


__all__ = [
    "set_clock", "reset_clock", "read_district", "read_driver", "read_trip",
    "read_rider", "read_request", "setup_district", "setup_rider",
    "setup_contract", "onboard_driver", "open_clearance", "record_inspection",
    "vet_driver", "create_request", "schedule_request", "setup_one_off_request",
    "assign_and_accept", "drive_trip", "fail_dropoff", "setup_scheduled_trip",
    "setup_two_districts", "setup_vetted_driver_only", "setup_two_vetted_drivers",
    "complete_trip", "setup_completed_trip", "setup_absence_scenario",
    "setup_driver_with_strikes", "setup_strike_cascade_scenario",
    "setup_fingerprint_revocation_scenario", "setup_rider_overlap_scenario",
    "setup_driver_overlap_scenario", "setup_recurring_series",
    "setup_statement_ready", "setup_locked_in_transit_trip",
    "NON_EXISTENT_RIDER_UUID",
]