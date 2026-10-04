"""Ride request intake: the submit/revise cycle and the window-width gate."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    TEST_USERS,
    api_client,
    create_request,
    get_success_data,
    read_district,
    read_request,
    set_clock,
    setup_contract,
    setup_district,
    setup_rider,
    validate_error,
    validate_success,
)


def _intake_fixture():
    set_clock(DEFAULT_CLOCK)
    district = setup_district()
    rider = setup_rider(
        district["id"], full_name="Cara Voss", home_address="9 Pine St",
        program_type="SPECIAL_EDUCATION", spi_level=2,
        emergency_contact_phone="5550103",
    )
    setup_contract(district["id"])
    return district, rider


def test_submit_and_revise_cycle_repeats_and_counts_each_traversal():
    """PRD §3.4: "A `DistrictAdmin` may return a submitted request for
    revision, moving it to `REVISION_REQUESTED`, incrementing its
    `revision_count`, and recording a `revision_note` describing what must
    change; the revision count is the observable record of how many times the
    request has been sent back."
    PRD §3.4: "The requester then resubmits, moving the request back to
    `SUBMITTED`; the submit-and-revise cycle may repeat without bound."

    Design: Difficulty/non_linear_state_machine/ride_request_submitted_revision_loop_repeats_with_a_counter
    """
    district, rider = _intake_fixture()
    request = create_request(
        read_district(district["id"]), rider, submit=False,
        trip_type="PM_SCHOOL", window_start_at="2026-09-10T15:00:00Z",
        window_end_at="2026-09-10T15:20:00Z", planned_miles=4.0,
        pickup_address="Lincoln Elementary", dropoff_address="9 Pine St",
    )
    assert request["status"] == "DRAFT"
    assert request["revision_count"] == 0

    request = get_success_data(
        api_client.submit_ride_request(request["id"], TEST_USERS["district_admin_headers"])
    )
    assert request["status"] == "SUBMITTED"

    for note in ("pickup window too tight", "wrong school of record"):
        request = get_success_data(
            api_client.request_revision(
                request["id"], {"revision_note": note},
                TEST_USERS["district_admin_headers"],
            )
        )
        assert request["status"] == "REVISION_REQUESTED"
        request = get_success_data(
            api_client.resubmit_ride_request(
                request["id"], TEST_USERS["district_admin_headers"]
            )
        )
        assert request["status"] == "SUBMITTED", (
            "the submit-and-revise cycle must be able to repeat without bound"
        )

    final = read_request(request["id"])
    assert final["status"] == "SUBMITTED"
    assert final["revision_count"] == 2, (
        f"revision_count records the two completed loops, got {final['revision_count']}"
    )


def test_approval_is_refused_while_the_request_sits_in_revision():
    """PRD §3.4: "The request must be in `SUBMITTED`, and the student must be in
    `ACTIVE` status — a request for an inactive student is refused with
    `ERR_RIDER_INACTIVE` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/ride_request_submitted_revision_loop_repeats_with_a_counter
    """
    district, rider = _intake_fixture()
    request = create_request(
        read_district(district["id"]), rider, submit=False,
        trip_type="PM_SCHOOL", window_start_at="2026-09-10T15:00:00Z",
        window_end_at="2026-09-10T15:20:00Z", planned_miles=4.0,
    )
    get_success_data(
        api_client.submit_ride_request(request["id"], TEST_USERS["district_admin_headers"])
    )
    get_success_data(
        api_client.request_revision(
            request["id"], {"revision_note": "pickup window too tight"},
            TEST_USERS["district_admin_headers"],
        )
    )

    resp = api_client.approve_ride_request(
        request["id"], TEST_USERS["district_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = read_request(request["id"])
    assert after["status"] == "REVISION_REQUESTED", (
        "resubmission is the only way back to SUBMITTED"
    )
    assert after["revision_count"] == 1


def test_request_window_wider_than_its_cap_is_refused_at_submission():
    """PRD §3.4: "requires the span from window start to window end to be no
    greater than the request's `max_window_minutes`, again refused with
    `ERR_WINDOW_TOO_WIDE` (HTTP 422)."

    Design: Corner/validations/ride_request_window_wider_than_the_cap_returns_window_too_wide
    """
    district, rider = _intake_fixture()
    oversized = create_request(
        read_district(district["id"]), rider, submit=False,
        window_start_at="2026-09-11T07:30:00Z",
        window_end_at="2026-09-11T08:30:00Z", max_window_minutes=30,
    )

    resp = api_client.submit_ride_request(
        oversized["id"], TEST_USERS["district_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_TOO_WIDE)
    assert read_request(oversized["id"])["status"] == "DRAFT", (
        "a refused submission leaves the request in DRAFT"
    )

    within_cap = create_request(
        read_district(district["id"]), rider, submit=False,
        window_start_at="2026-09-11T15:00:00Z",
        window_end_at="2026-09-11T15:20:00Z", max_window_minutes=30,
    )
    validate_success(
        api_client.submit_ride_request(
            within_cap["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert read_request(within_cap["id"])["status"] == "SUBMITTED"