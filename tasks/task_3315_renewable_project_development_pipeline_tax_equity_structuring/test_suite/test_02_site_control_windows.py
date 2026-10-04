"""Site control: half-open interval overlap semantics and the exercise window."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_executed_instrument,
    create_project,
    create_project_payload,
    create_site_control_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)


def test_parcel_half_open_adjacency_allowed(api, developer_admin_headers):
    """PRD §3.1: "Executing it (moving it to `EXECUTED`) is refused with
    `ERR_PARCEL_OVERLAP` (HTTP 409) when any other instrument on the same
    `parcel_id` is in `EXECUTED`, `EXERCISED`, or `RECORDED` and its half-open
    window overlaps this one; pure adjacency, where one instrument's `end_date`
    equals the other's `start_date`, is not an overlap."

    Design: Difficulty/resource_temporal_overlap/parcel_half_open_adjacency_allowed
    """
    project = create_project(
        name="Parcel Farm", technology="SOLAR", target_capacity_mw=30,
        resource_class="B",
    )
    a = validate_success(
        api.create_site_control_instrument(
            project["id"],
            create_site_control_payload(
                parcel_id="PCL-H1", instrument_type="LAND_OPTION",
                start_date="2026-09-01T00:00:00Z", end_date="2027-09-01T00:00:00Z",
                exercise_price_usd=40000,
            ),
            developer_admin_headers,
        ),
        expected_status=201,
    )
    validate_success(
        api.transition_site_control_instrument(a["id"], {"to": "EXECUTED"},
                                               developer_admin_headers)
    )
    b = validate_success(
        api.create_site_control_instrument(
            project["id"],
            create_site_control_payload(
                parcel_id="PCL-H1", instrument_type="EASEMENT",
                start_date="2027-09-01T00:00:00Z", end_date="2047-09-01T00:00:00Z",
                exercise_price_usd=5000,
            ),
            developer_admin_headers,
        ),
        expected_status=201,
    )
    c = validate_success(
        api.create_site_control_instrument(
            project["id"],
            create_site_control_payload(
                parcel_id="PCL-H1", instrument_type="EASEMENT",
                start_date="2027-08-31T00:00:00Z", end_date="2047-08-31T00:00:00Z",
                exercise_price_usd=5000,
            ),
            developer_admin_headers,
        ),
        expected_status=201,
    )
    # Adjacent start (b.start == a.end): not an overlap.
    b_done = validate_success(
        api.transition_site_control_instrument(b["id"], {"to": "EXECUTED"},
                                               developer_admin_headers)
    )
    assert b_done["status"] == "EXECUTED"
    # One day earlier: overlap.
    resp = api.transition_site_control_instrument(c["id"], {"to": "EXECUTED"},
                                                  developer_admin_headers)
    validate_error(resp, ApiErrorId.ERR_PARCEL_OVERLAP)
    c_now = get_success_data(
        api.get_site_control_instrument(c["id"], developer_admin_headers)
    )
    assert c_now["status"] == "DRAFT"


def test_parcel_half_open_boundary_window_definition(api, developer_admin_headers):
    """PRD §3.1: "The window is a half-open interval — it covers `start_date`
    and runs up to but not including `end_date` — and `end_date` must be
    strictly greater than `start_date`."

    Design: Difficulty/resource_temporal_overlap/parcel_half_open_adjacency_allowed
    """
    project = create_project(
        name="Boundary Parcel Farm", technology="WIND", target_capacity_mw=25,
        resource_class="A",
    )
    # Invalid window: end_date == start_date violates strict ordering.
    resp = api.create_site_control_instrument(
        project["id"],
        create_site_control_payload(
            parcel_id="PCL-BW", start_date="2027-01-01T00:00:00Z",
            end_date="2027-01-01T00:00:00Z",
        ),
        developer_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

    # Valid windows whose shared boundary is covered by only one side.
    first = validate_success(
        api.create_site_control_instrument(
            project["id"],
            create_site_control_payload(
                parcel_id="PCL-BW", start_date="2027-01-01T00:00:00Z",
                end_date="2027-06-01T00:00:00Z",
            ),
            developer_admin_headers,
        ),
        expected_status=201,
    )
    validate_success(
        api.transition_site_control_instrument(first["id"], {"to": "EXECUTED"},
                                               developer_admin_headers)
    )
    second = validate_success(
        api.create_site_control_instrument(
            project["id"],
            create_site_control_payload(
                parcel_id="PCL-BW", start_date="2027-06-01T00:00:00Z",
                end_date="2027-12-01T00:00:00Z",
            ),
            developer_admin_headers,
        ),
        expected_status=201,
    )
    second_done = validate_success(
        api.transition_site_control_instrument(second["id"], {"to": "EXECUTED"},
                                               developer_admin_headers)
    )
    assert second_done["status"] == "EXECUTED"


def test_option_exercise_within_window(api, developer_admin_headers, platform_admin_headers):
    """PRD §3.1: "An `EXECUTED` instrument may be exercised — moving to
    `EXERCISED` — only while the logical clock has not passed its `end_date`.
    An exercise attempted after the window has closed is rejected with
    `ERR_OPTION_WINDOW_LAPSED` (HTTP 409), and the failed attempt itself pushes
    the instrument into `EXPIRED`."

    Design: Corner/validations/option_exercise_within_window
    """
    project = create_project(
        name="Window Farm", technology="WIND", target_capacity_mw=80,
        resource_class="A",
    )
    a = create_executed_instrument(
        project["id"], parcel_id="PCL-W1",
        start_date="2026-09-01T00:00:00Z", end_date="2026-12-31T00:00:00Z",
    )
    b = create_executed_instrument(
        project["id"], parcel_id="PCL-W2",
        start_date="2026-09-01T00:00:00Z", end_date="2026-12-31T00:00:00Z",
    )
    set_clock("2026-12-31T00:00:00Z")
    # Exercise at exactly end_date passes (the clock has not passed end_date).
    a_done = validate_success(
        api.transition_site_control_instrument(a["id"], {"to": "EXERCISED"},
                                               developer_admin_headers)
    )
    assert a_done["status"] == "EXERCISED"

    set_clock("2027-01-01T00:00:00Z")
    resp = api.transition_site_control_instrument(b["id"], {"to": "EXERCISED"},
                                                  developer_admin_headers)
    validate_error(resp, ApiErrorId.ERR_OPTION_WINDOW_LAPSED)
    b_now = get_success_data(
        api.get_site_control_instrument(b["id"], developer_admin_headers)
    )
    assert b_now["status"] == "EXPIRED"
