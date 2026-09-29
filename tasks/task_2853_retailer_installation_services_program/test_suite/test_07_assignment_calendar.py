"""The install calendar: the delivery-slack floor and the travel-buffered overlap test.

Both boundaries are sharp to the minute, and both are computed from figures that are
floored rather than rounded.
"""

from test_helpers import (
    PROJECT_COORDINATOR,
    ApiErrorId,
    AssignmentStatus,
    DeliveryStatus,
    FulfillmentStatus,
    assert_capacity_conservation,
    assert_committed_minutes,
    assert_instant,
    assert_project_dimensions,
    assert_version,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
)

# The material is promised by 2026-08-24T08:00:00.000Z.
TOO_TIGHT = ("2026-08-25T07:59:00.000Z", "2026-08-25T15:59:00.000Z")
JUST_ENOUGH = ("2026-08-25T08:00:00.000Z", "2026-08-25T16:00:00.000Z")


def test_twenty_three_hours_of_slack_is_refused_and_twenty_four_confirms(api):
    """A window starting 86340 seconds after the promised material end floors to 23
    hours and is refused; one starting 86400 seconds after it floors to 24 and
    confirms.

    PRD 3.6: "The comparison is on the floored integer, which makes the boundary sharp:
    a window starting exactly 86400 seconds after the promised end floors to 24 and is
    confirmed, while one starting 86340 seconds after it floors to 23 and is refused
    with `ERR_DELIVERY_SLACK_INSUFFICIENT`."

    Design: Difficulty/boundary_precision_check/delivery_slack_of_exactly_24_hours_confirms_where_23_is_rejected
    """
    ctx = fx.install_ready(api)
    project_id = ctx["project"]["id"]
    tight = fx.hold_assignment(api, project_id, ctx["installer"]["id"],
                               fx.project_version(api, project_id),
                               window_start=TOO_TIGHT[0], window_end=TOO_TIGHT[1])

    validate_error(api.confirm_assignment(tight["id"], PROJECT_COORDINATOR),
                   ApiErrorId.DELIVERY_SLACK_INSUFFICIENT)
    refused = fx.read_assignment(api, tight["id"])
    assert refused["status"] == AssignmentStatus.HELD, (
        "a refused confirmation leaves the window held"
    )

    get_success_data(
        api.release_assignment(
            tight["id"],
            f.release_payload("Rescheduled one minute later to clear the delivery "
                              "slack"),
            PROJECT_COORDINATOR)
    )
    later = fx.hold_assignment(api, project_id, ctx["installer"]["id"],
                               fx.project_version(api, project_id),
                               window_start=JUST_ENOUGH[0],
                               window_end=JUST_ENOUGH[1])
    confirmed = get_success_data(
        api.confirm_assignment(later["id"], PROJECT_COORDINATOR)
    )
    assert confirmed["status"] == AssignmentStatus.CONFIRMED
    assert_instant(confirmed["window_start"], JUST_ENOUGH[0], "window_start")


def test_the_slack_refusal_and_the_reschedule_keep_capacity_exact(api):
    """Only one window is ever live, so the firm's committed minutes read 480 and the
    delivery is never disturbed by either attempt.

    PRD 3.6: "Confirmation moves the assignment `HELD → CONFIRMED` and touches nothing
    else."

    Design: Difficulty/boundary_precision_check/delivery_slack_of_exactly_24_hours_confirms_where_23_is_rejected
    """
    ctx = fx.install_ready(api)
    project_id = ctx["project"]["id"]
    installer_id = ctx["installer"]["id"]

    tight = fx.hold_assignment(api, project_id, installer_id,
                               fx.project_version(api, project_id),
                               window_start=TOO_TIGHT[0], window_end=TOO_TIGHT[1])
    assert tight["duration_minutes"] == 480
    validate_error(api.confirm_assignment(tight["id"], PROJECT_COORDINATOR),
                   ApiErrorId.DELIVERY_SLACK_INSUFFICIENT)
    assert_committed_minutes(fx.read_installer(api, installer_id), 480)

    get_success_data(
        api.release_assignment(tight["id"],
                               f.release_payload("Rescheduled one minute later to "
                                                 "clear the delivery slack"),
                               PROJECT_COORDINATOR)
    )
    assert_committed_minutes(fx.read_installer(api, installer_id), 0)

    later = fx.hold_assignment(api, project_id, installer_id,
                               fx.project_version(api, project_id),
                               window_start=JUST_ENOUGH[0],
                               window_end=JUST_ENOUGH[1])
    get_success_data(api.confirm_assignment(later["id"], PROJECT_COORDINATOR))

    installer = fx.read_installer(api, installer_id)
    assert_committed_minutes(installer, 480)
    assert_capacity_conservation(installer,
                                 fx.list_installer_assignments(api, installer_id))
    assert_project_dimensions(fx.read_project(api, project_id),
                              fulfillment=FulfillmentStatus.SCHEDULED)
    # Confirmation touches nothing else, so the material is still merely planned.
    assert fx.read_delivery(api, ctx["delivery"]["id"])["status"] == (
        DeliveryStatus.PLANNED
    )


def _one_firm_two_projects(api):
    """One firm holding a confirmed eight-hour window on the first project, with a
    second deposited project waiting for the same crew."""
    ctx = fx.install_ready(api)
    installer_id = ctx["installer"]["id"]
    first_id = ctx["project"]["id"]
    first_assignment = fx.hold_assignment(api, first_id, installer_id,
                                          fx.project_version(api, first_id),
                                          window_start=JUST_ENOUGH[0],
                                          window_end=JUST_ENOUGH[1])
    ctx["first_assignment"] = get_success_data(
        api.confirm_assignment(first_assignment["id"], PROJECT_COORDINATOR)
    )
    second = fx.sell_project(api, ctx, estimated_units=420.00,
                             site_address="22 Larch Way",
                             requested_install_date="2026-08-25T18:00:00.000Z")
    ctx["second_project"] = fx.pay_deposit(api, second, ctx["customer"]["id"])
    return ctx


def test_a_window_starting_inside_the_travel_buffer_is_refused(api):
    """The existing window ends at 16:00, so the buffer closes the calendar until
    17:30; a window starting at 17:29 conflicts.

    PRD 3.6: "Two live assignments of the same installer conflict when the new window
    starts before the existing window's end extended by 90 minutes of travel buffer
    **and** the existing window starts before the new window's end extended by the same
    90 minutes; both comparisons are **strict**, so a new window beginning exactly 90
    minutes after an existing window's end is allowed while one beginning 89 minutes
    after it is refused with `ERR_INSTALLER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/installer_windows_are_half_open_and_padded_by_a_ninety_minute_buffer
    """
    ctx = _one_firm_two_projects(api)
    second = ctx["second_project"]
    version_before = fx.project_version(api, second["id"])

    response = api.create_assignment(
        f.assignment_payload(second["id"], ctx["installer"]["id"], version_before,
                             window_start="2026-08-25T17:29:00.000Z",
                             window_end="2026-08-25T21:29:00.000Z"),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.INSTALLER_WINDOW_CONFLICT)

    # Nothing was held, so the firm still carries only the first eight-hour window and
    # the second project has not been touched.
    assert_committed_minutes(fx.read_installer(api, ctx["installer"]["id"]), 480)
    assert_version(fx.read_project(api, second["id"]), version_before,
                   "the refused project")


def test_a_window_starting_exactly_on_the_buffer_edge_is_held(api):
    """Moved one minute later, to exactly 90 minutes after the first window's end, the
    same request is accepted and both projects are scheduled.

    PRD 3.6: "Windows are half-open intervals — start inclusive, end exclusive — and the
    buffer extends each window at its **end only**."

    Design: Difficulty/resource_temporal_overlap/installer_windows_are_half_open_and_padded_by_a_ninety_minute_buffer
    """
    ctx = _one_firm_two_projects(api)
    second = ctx["second_project"]
    installer_id = ctx["installer"]["id"]

    validate_error(
        api.create_assignment(
            f.assignment_payload(second["id"], installer_id,
                                 fx.project_version(api, second["id"]),
                                 window_start="2026-08-25T17:29:00.000Z",
                                 window_end="2026-08-25T21:29:00.000Z"),
            PROJECT_COORDINATOR),
        ApiErrorId.INSTALLER_WINDOW_CONFLICT,
    )

    held = fx.hold_assignment(api, second["id"], installer_id,
                              fx.project_version(api, second["id"]),
                              window_start="2026-08-25T17:30:00.000Z",
                              window_end="2026-08-25T21:30:00.000Z")
    assert held["status"] == AssignmentStatus.HELD
    assert held["duration_minutes"] == 240

    installer = fx.read_installer(api, installer_id)
    assert_committed_minutes(installer, 720)
    assert_capacity_conservation(installer,
                                 fx.list_installer_assignments(api, installer_id))

    # The incumbent window is untouched by the second booking.
    incumbent = fx.read_assignment(api, ctx["first_assignment"]["id"])
    assert incumbent["status"] == AssignmentStatus.CONFIRMED
    assert_instant(incumbent["window_end"], JUST_ENOUGH[1], "window_end")
    for project_id in (ctx["project"]["id"], second["id"]):
        assert_project_dimensions(fx.read_project(api, project_id),
                                  fulfillment=FulfillmentStatus.SCHEDULED)
