"""Which rejection a caller sees when two guards fail on the same request."""

from test_helpers import (
    COORDINATOR,
    PM,
    ApiErrorId,
    CLOCK_AFTER_DEADLINE,
    api_client,
    assert_cents,
    assert_crew_load,
    assert_total_count,
    install_appointment_payload,
    make_crew,
    make_subscriber_headers,
    preorder_payload,
    read_account,
    read_crew,
    read_crew_version,
    read_preorder,
    read_zone,
    read_zone_version,
    set_clock,
    setup_converted_preorder,
    setup_zone_with_preorders,
    suspension_payload,
    validate_error,
    validate_success,
)

INVERTED_WINDOW_START = "2026-10-05T14:00:00Z"
INVERTED_WINDOW_END = "2026-10-05T12:00:00Z"


def test_closed_window_outranks_the_duplicate_preorder_complaint():
    """A duplicate sign-up filed after the deadline reports the closed window, not the clash.

    PRD 2.10: "Checks are evaluated in the single strict ascending order below; the **first**
    rule that fails determines the response, and no later rule is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/prereg_window_closed_outranks_duplicate_preorder
    """
    base = setup_zone_with_preorders(
        preorder_count=1, household_count=10, threshold_pct=10.0
    )
    zone_id = base["zone"]["id"]
    address = base["addresses"][0]
    account = base["accounts"][0]
    set_clock(CLOCK_AFTER_DEADLINE)

    response = api_client.create_preorder(
        preorder_payload(
            zone_id,
            address["id"],
            account["id"],
            read_zone_version(zone_id),
            plan_tier="GIGABIT_1000",
        ),
        make_subscriber_headers(account["id"]),
    )

    validate_error(response, ApiErrorId.ERR_PREREG_WINDOW_CLOSED)


def test_the_refused_duplicate_leaves_the_original_sign_up_exactly_as_it_was():
    """No second row is written and the first preorder keeps its plan, status and deposit.

    PRD 2.10: "**Preorder uniqueness.** At most one preorder may exist for a given pairing of
    `service_address_id` and `account_id` whose `preorder_status` is `PENDING`, `QUALIFIED` or
    `CONVERTED`."

    Design: Difficulty/priority_pair_validation_conflict/prereg_window_closed_outranks_duplicate_preorder
    """
    base = setup_zone_with_preorders(
        preorder_count=1, household_count=10, threshold_pct=10.0
    )
    zone_id = base["zone"]["id"]
    address = base["addresses"][0]
    account = base["accounts"][0]
    set_clock(CLOCK_AFTER_DEADLINE)

    response = api_client.create_preorder(
        preorder_payload(
            zone_id,
            address["id"],
            account["id"],
            read_zone_version(zone_id),
            plan_tier="GIGABIT_1000",
        ),
        make_subscriber_headers(account["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PREREG_WINDOW_CLOSED)

    listed = api_client.list_preorders(PM, params={"build_zone_id": zone_id})
    assert_total_count(listed, 1)

    original = read_preorder(base["preorders"][0]["id"])
    assert original["plan_tier"] == "BASIC_300", original["plan_tier"]
    assert original["preorder_status"] == "PENDING", original["preorder_status"]
    assert original["deposit_status"] == "HELD", original["deposit_status"]
    assert_cents(
        read_account(account["id"])["deposit_held_cents"], 1000, "deposit_held_cents"
    )


def _suspended_zone_with_a_free_crew():
    """A zone suspended straight after ground-break, plus an idle bury crew."""
    base = setup_converted_preorder(
        drop_method="BURY", preorder_count=1, household_count=10
    )
    validate_success(
        api_client.set_build_zone_suspension(
            base["zone"]["id"], suspension_payload("SUSPEND"), PM
        )
    )
    base["crew"] = make_crew(name="Bury Crew 1", crew_type="BURY")
    return base


def test_inactive_construction_outranks_the_window_geometry_complaint():
    """An inverted window booked into a suspended zone reports the zone, not the geometry.

    PRD 2.10: "**Zone construction active.** The zone's `construction_status` is
    `IN_CONSTRUCTION` or `SERVICE_READY`. Booking an install at an address in a zone that has
    not broken ground, or whose construction is `SUSPENDED`, is
    `ERR_ZONE_CONSTRUCTION_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/zone_construction_not_active_outranks_invalid_window
    """
    base = _suspended_zone_with_a_free_crew()
    crew_id = base["crew"]["id"]

    response = api_client.create_install_appointment(
        install_appointment_payload(
            base["converted"]["id"],
            crew_id,
            INVERTED_WINDOW_START,
            INVERTED_WINDOW_END,
            read_crew_version(crew_id),
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_ZONE_CONSTRUCTION_NOT_ACTIVE)
    zone = read_zone(base["zone"]["id"])
    assert zone["construction_status"] == "SUSPENDED", zone["construction_status"]


def test_the_refused_booking_writes_no_appointment_and_loads_no_crew():
    """Nothing is persisted, so the crew still holds zero minutes and zero appointments.

    PRD 2.10: "**Window geometry.** `window_end_at` is strictly after `window_start_at`, both
    instants land on exact minute boundaries with zero seconds and zero fractional seconds,
    the duration is at least 30 minutes and at most 480 minutes inclusive at both ends, and
    `window_start_at` is at or after the logical clock."

    Design: Difficulty/priority_pair_validation_conflict/zone_construction_not_active_outranks_invalid_window
    """
    base = _suspended_zone_with_a_free_crew()
    crew_id = base["crew"]["id"]

    response = api_client.create_install_appointment(
        install_appointment_payload(
            base["converted"]["id"],
            crew_id,
            INVERTED_WINDOW_START,
            INVERTED_WINDOW_END,
            read_crew_version(crew_id),
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_ZONE_CONSTRUCTION_NOT_ACTIVE)

    listed = api_client.list_install_appointments(COORDINATOR, params={"crew_id": crew_id})
    assert_total_count(listed, 0)
    assert_crew_load(read_crew(crew_id), 0, 0)
