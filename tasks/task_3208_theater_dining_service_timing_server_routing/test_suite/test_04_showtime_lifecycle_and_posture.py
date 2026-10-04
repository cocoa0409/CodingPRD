"""Showtime lifecycle, auditorium posture, and the pre-show cut cycle."""
import pytest

from test_helpers import (
    api_client, LEAD, PROGRAMMER, PRODUCER,
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_programming_event,
    make_auditorium, make_menu_item, make_server, make_showtime,
    set_clock, server_headers, read_posture, read_showtime,
    setup_scheduled_showtime, setup_dining_open_showtime, setup_in_service_showtime,
    setup_completed_showtime_for_reopen, setup_themed_event,
    setup_special_event_showtime, setup_standard_and_special_showtimes,
    place_scenario_slip,
)


def test_pre_show_cycle_reenters_review_and_bumps_the_revision_counter(api):
    """PRD §3.2: "A rejected cut may be submitted again from `PRE_SHOW_REJECTED` or
    from `PRE_SHOW_DRAFT` — any other origin is refused with
    `ERR_PRE_SHOW_NOT_RESUBMITTABLE` — provided a themed menu item exists; the cut
    returns to `PRE_SHOW_IN_REVIEW` and `pre_show_content_version` advances by
    one."
    PRD §3.2: "Separately, an already-approved cut may be re-opened for a re-cut
    from `PRE_SHOW_APPROVED`, which is the only other admissible origin for a
    resubmission; the cut returns to `PRE_SHOW_IN_REVIEW` and the revision counter
    advances by one again."
    PRD §3.2: "Approval itself never activates the event: approval leaves the
    event's own `status` in `DRAFT`, because activation is a separate and later
    act."

    Design: Difficulty/non_linear_state_machine/programming_event_pre_show_cycle_rejects_then_resubmits_and_bumps_version
    """
    staged = setup_themed_event(state="DRAFT")
    event = staged["event"]
    assert event["pre_show_content_status"] == "PRE_SHOW_DRAFT"
    assert event["pre_show_content_version"] == 1

    in_review = validate_success(
        api_client.submit_pre_show_content(event["id"], {}, PROGRAMMER), 200
    )
    assert in_review["pre_show_content_status"] == "PRE_SHOW_IN_REVIEW"
    assert in_review["pre_show_content_version"] == 1, (
        "the first submission for review leaves the revision counter at one"
    )

    rejected = validate_success(api_client.reject_pre_show_content(
        event["id"], {"notes": "Third-act spoiler cards must be recut"}, PRODUCER
    ), 200)
    assert rejected["pre_show_content_status"] == "PRE_SHOW_REJECTED"
    assert rejected["pre_show_content_version"] == 1, "rejection alone does not bump the counter"

    resubmitted = validate_success(
        api_client.submit_pre_show_content(event["id"], {}, PROGRAMMER), 200
    )
    assert resubmitted["pre_show_content_status"] == "PRE_SHOW_IN_REVIEW"
    assert resubmitted["pre_show_content_version"] == 2, (
        "re-entering review from a rejection bumps the revision counter"
    )

    approved = validate_success(
        api_client.approve_pre_show_content(event["id"], {}, PRODUCER), 200
    )
    assert approved["pre_show_content_status"] == "PRE_SHOW_APPROVED"
    assert approved["pre_show_content_version"] == 2
    assert approved["status"] == "DRAFT", "approval never activates the event"

    reopened = validate_success(
        api_client.submit_pre_show_content(event["id"], {}, PROGRAMMER), 200
    )
    assert reopened["pre_show_content_status"] == "PRE_SHOW_IN_REVIEW"
    assert reopened["pre_show_content_version"] == 3, (
        "re-opening an approved cut for a re-cut bumps the counter a second time"
    )
    assert reopened["status"] == "DRAFT", "the cycle runs on the pre-show axis independently"


def test_the_cycle_leaves_the_event_itself_in_draft_throughout(api):
    """PRD §3.2: "A producer then either approves the cut — moving it to
    `PRE_SHOW_APPROVED` when it is `PRE_SHOW_IN_REVIEW` (otherwise
    `ERR_PRE_SHOW_NOT_IN_REVIEW`) and when at least one signature item exists".
    PRD §3.2: "approval leaves the event's own `status` in `DRAFT`, because
    activation is a separate and later act."

    Design: Difficulty/non_linear_state_machine/programming_event_pre_show_cycle_rejects_then_resubmits_and_bumps_version
    """
    staged = setup_themed_event(state="DRAFT")
    event = staged["event"]

    api_client.submit_pre_show_content(event["id"], {}, PROGRAMMER)
    api_client.reject_pre_show_content(event["id"], {"notes": "recut"}, PRODUCER)
    api_client.submit_pre_show_content(event["id"], {}, PROGRAMMER)
    api_client.approve_pre_show_content(event["id"], {}, PRODUCER)

    read_back = validate_success(
        api_client.get_programming_event(event["id"], PROGRAMMER), 200
    )
    assert_programming_event(read_back)
    assert read_back["status"] == "DRAFT"
    assert read_back["pre_show_content_status"] == "PRE_SHOW_APPROVED"
    assert read_back["pre_show_content_version"] == 2


def test_open_dining_is_gated_by_the_linked_events_pre_show_cut(api):
    """PRD §3.1: "The act is admissible only when the showtime is still
    `SCHEDULED` (otherwise `ERR_SHOWTIME_NOT_SCHEDULED`), when its parent
    auditorium is `LIVE` or `TURNOVER` (otherwise `ERR_AUDITORIUM_NOT_SERVING`),
    and when the logical clock has reached the showtime's `dining_open_at_utc`".
    PRD §3.2: "Activation is the act that lets the evening sell." A special-event
    showtime "expects a programming event to be attached and approved before it
    may sell".

    Design: Difficulty/cross_entity_state_dependency/showtime_open_dining_requires_activated_event_and_approved_preshow
    """
    scenario = setup_special_event_showtime(event_state="DRAFT")
    showtime = scenario["showtime"]
    assert read_showtime(showtime["id"], LEAD)["status"] == "SCHEDULED"

    refused = api_client.open_dining(showtime["id"], LEAD)
    validate_error(refused, "ERR_PRE_SHOW_NOT_APPROVED")

    staged_showtime = read_showtime(showtime["id"], LEAD)
    assert staged_showtime["status"] == "SCHEDULED", (
        "the showtime's own state is unchanged and its window is wide open"
    )


def test_the_identical_open_dining_succeeds_once_the_event_is_activated(api):
    """PRD §3.2: "Activation moves `status` to `ACTIVATED`, confirms the
    `content_type` of every linked special-event showtime that is still
    `SCHEDULED`, enables themed pricing on those showtimes".
    PRD §3.1: "Dining opens on a scheduled showtime only through the kitchen
    lead's act of opening the seating window, which moves `status` from
    `SCHEDULED` to `DINING_OPEN` and `mode` to `DINING_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/showtime_open_dining_requires_activated_event_and_approved_preshow
    """
    scenario = setup_special_event_showtime(event_state="DRAFT")
    showtime, event = scenario["showtime"], scenario["event"]

    validate_error(api_client.open_dining(showtime["id"], LEAD), "ERR_PRE_SHOW_NOT_APPROVED")

    api_client.submit_pre_show_content(event["id"], {}, PROGRAMMER)
    api_client.approve_pre_show_content(event["id"], {}, PRODUCER)
    approved = get_success_data(
        api_client.get_programming_event(event["id"], PROGRAMMER)
    )
    validate_success(api_client.activate_programming_event(
        event["id"], {"expected_programming_event_version": approved["version"]}, PROGRAMMER
    ), 200)

    opened = validate_success(api_client.open_dining(showtime["id"], LEAD), 200)
    assert opened["status"] == "DINING_OPEN"
    assert opened["mode"] == "DINING_OPEN"


def test_scheduling_a_showtime_one_minute_inside_the_window_is_rejected(api):
    """PRD §2.12: "The windows are treated as half-open intervals running from
    `dining_open_at_utc` up to but not including `dining_close_at_utc`, so a
    showtime whose dining window opens exactly at the earlier showtime's dining
    close is admitted, while one that opens a single minute earlier is rejected
    with `ERR_OVERLAPPING_SHOWTIME_WINDOW` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/dining_window_half_open_boundary_admits_exact_abutment
    """
    set_clock("2026-09-01T18:00:00Z")
    auditorium = make_auditorium(name="Theater 13")
    first = make_showtime(auditorium["id"], "2026-09-01T20:00:00Z", 60, title="Blade Runner")
    assert first["dining_close_at_utc"] == "2026-09-01T20:15:00Z"

    # A second window opening at 20:14 runs one minute into the first one.
    rejected = api_client.create_showtime(
        {"auditorium_id": auditorium["id"], "title": "Early",
         "start_at_utc": "2026-09-01T20:34:00Z", "runtime_minutes": 60,
         "content_type": "STANDARD"},
        PROGRAMMER,
    )
    validate_error(rejected, "ERR_OVERLAPPING_SHOWTIME_WINDOW")


def test_scheduling_a_showtime_exactly_at_the_close_is_admitted(api):
    """PRD §2.12: "a showtime whose dining window opens exactly at the earlier
    showtime's dining close is admitted".

    Design: Difficulty/boundary_precision_check/dining_window_half_open_boundary_admits_exact_abutment
    """
    set_clock("2026-09-01T18:00:00Z")
    auditorium = make_auditorium(name="Theater 13")
    first = make_showtime(auditorium["id"], "2026-09-01T20:00:00Z", 60, title="Blade Runner")
    assert first["dining_close_at_utc"] == "2026-09-01T20:15:00Z"

    abutting = validate_success(api_client.create_showtime(
        {"auditorium_id": auditorium["id"], "title": "Abutting",
         "start_at_utc": "2026-09-01T20:35:00Z", "runtime_minutes": 60,
         "content_type": "STANDARD"},
        PROGRAMMER,
    ), 201)
    assert abutting["status"] == "SCHEDULED"
    assert abutting["dining_open_at_utc"] == "2026-09-01T20:15:00Z", (
        "the admitted window opens exactly where the earlier one closed"
    )
    assert abutting["dining_open_at_utc"] == first["dining_close_at_utc"], (
        "the two windows touch but do not overlap, so the boundary is half-open on the close instant"
    )


def test_a_section_can_be_rostered_only_on_a_serving_auditorium(api):
    """PRD §3.9: "Placing a server on a section is the kitchen lead's act of
    rostering, performed by supplying the `showtime_id`, the `server_id`, and a
    `section_label` naming the physical section."
    PRD §3.9: "The resulting assignment begins `ACTIVE` with its points at zero".

    Design: Difficulty/cross_entity_state_dependency/section_assignment_requires_local_auditorium_membership
    """
    set_clock("2026-09-01T19:45:00Z")
    serving_auditorium = make_auditorium(name="Theater A")
    dark_auditorium = make_auditorium(name="Theater B")
    server = make_server(serving_auditorium["id"], "Yusuf")
    serving_showtime = make_showtime(serving_auditorium["id"], "2026-09-01T20:00:00Z", 60,
                                     title="Rashomon")
    dark_showtime = make_showtime(dark_auditorium["id"], "2026-09-01T20:00:00Z", 60,
                                  title="Yojimbo")
    serving_showtime = get_success_data(api_client.open_dining(serving_showtime["id"], LEAD))
    assert read_posture(dark_auditorium["id"], LEAD)["status"] != "LIVE"

    # The assignment succeeds on the serving room's showtime.
    created = validate_success(api_client.create_section_assignment(
        {"showtime_id": serving_showtime["id"], "server_id": server["id"],
         "section_label": "LEFT"}, LEAD,
    ), 201)
    assert created["auditorium_id"] == serving_auditorium["id"]
    assert created["status"] == "ACTIVE"
    assert dark_showtime["id"] != serving_showtime["id"]


def test_auditorium_posture_climbs_and_falls_with_its_member_showtimes(api):
    """PRD §2.5: "An auditorium is `LIVE` when at least one member showtime has
    `mode` equal to `DINING_OPEN` and a `status` of `DINING_OPEN`, `SERVICE`, or
    `RUNNING`; it is `TURNOVER` when at least one member showtime has `mode` equal
    to `DINING_CLOSED` and a `status` of `SCHEDULED`; it is `DARK` otherwise."
    PRD §3.1: "`TURNOVER` also falls directly to `DARK` once every member showtime
    is `COMPLETED` or `CANCELLED`."

    Design: Corner/state_machines/auditorium_posture_is_compound_over_showtime_states
    """
    scenario = setup_scheduled_showtime(start_at_utc="2026-09-01T20:00:00Z",
                                        runtime_minutes=60, clock="2026-09-01T18:00:00Z")
    auditorium, showtime = scenario["auditorium"], scenario["showtime"]

    after_scheduling = read_posture(auditorium["id"], LEAD)
    assert after_scheduling["status"] == "TURNOVER", (
        "a scheduled member with no live sibling makes the room TURNOVER"
    )
    assert after_scheduling["build_phase"] == "SETUP", (
        "the 19:40 dining open is more than thirty minutes beyond the 18:00 instant"
    )

    set_clock("2026-09-01T19:40:00Z")
    validate_success(api_client.open_dining(showtime["id"], LEAD), 200)
    assert read_posture(auditorium["id"], LEAD)["status"] == "LIVE"

    validate_success(api_client.cancel_showtime(showtime["id"], PROGRAMMER), 200)
    after_cancel = read_posture(auditorium["id"], LEAD)
    assert after_cancel["status"] == "DARK"
    assert after_cancel["build_phase"] == "EMPTY"


def test_reopening_removes_exactly_the_points_completion_had_added(api):
    """PRD §3.7: "every section assignment that the completion cascade had
    auto-completed reverts to `ACTIVE` with its points reset to zero, the owning
    server's lifetime total is reduced by the points that had been added".
    PRD §3.9: "an assignment that carries no rating at all takes a base of two."

    Design: Corner/state_machines/reopen_service_reverts_auto_completed_sections_and_their_points
    """
    scenario = setup_completed_showtime_for_reopen()
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]

    completed = validate_success(api_client.complete_showtime(showtime["id"], LEAD), 200)
    assert completed["status"] == "COMPLETED"
    scored = get_success_data(api_client.get_section_assignment(section["id"], LEAD))
    assert scored["assignment_points"] == 2, "the unrated base of two points"
    assert get_success_data(api_client.get_server(server["id"], LEAD))["lifetime_points"] == 2

    validated = validate_success(api_client.reopen_service(showtime["id"], LEAD), 200)
    assert validated["status"] == "SERVICE"
    reverted = get_success_data(api_client.get_section_assignment(section["id"], LEAD))
    assert reverted["status"] == "ACTIVE"
    assert reverted["assignment_points"] == 0
    assert get_success_data(api_client.get_server(server["id"], LEAD))["lifetime_points"] == 0


def test_a_cancelled_showtime_refuses_every_outbound_trigger(api):
    """PRD §3.1: "The act is admissible only when the showtime is still
    `SCHEDULED` (otherwise `ERR_SHOWTIME_NOT_SCHEDULED`)".
    PRD §3.5: "That act is admissible only from `DINING_OPEN` (otherwise
    `ERR_SHOWTIME_NOT_DINING_OPEN`)".

    Design: Corner/state_machines/terminal_showtime_rejects_every_outbound_trigger
    """
    scenario = setup_scheduled_showtime(start_at_utc="2026-09-01T20:00:00Z",
                                        runtime_minutes=60, clock="2026-09-01T18:00:00Z")
    showtime = scenario["showtime"]
    cancelled = validate_success(api_client.cancel_showtime(showtime["id"], PROGRAMMER), 200)
    assert cancelled["status"] == "CANCELLED"

    validate_error(api_client.open_dining(showtime["id"], LEAD), "ERR_SHOWTIME_NOT_SCHEDULED")
    validate_error(api_client.start_service(showtime["id"], LEAD), "ERR_SHOWTIME_NOT_DINING_OPEN")


def test_activating_a_special_event_needs_a_linked_showtime(api):
    """PRD §3.2: "A `ProgrammingCoordinator` activates an event that is still
    `DRAFT` (otherwise `ERR_PROGRAMMING_EVENT_NOT_DRAFT`), whose pre-show cut is
    `PRE_SHOW_APPROVED` (otherwise `ERR_PRE_SHOW_NOT_APPROVED`), and which has at
    least one linked showtime of type `SPECIAL_EVENT` (otherwise
    `ERR_NO_LINKED_SHOWTIME`)."

    Design: Corner/state_machines/programming_event_activation_is_guarded_by_linked_showtime_presence
    """
    staged = setup_themed_event(state="APPROVED")
    event = staged["event"]
    assert event["pre_show_content_status"] == "PRE_SHOW_APPROVED"

    refused = api_client.activate_programming_event(
        event["id"], {"expected_programming_event_version": event["version"]}, PROGRAMMER
    )
    validate_error(refused, "ERR_NO_LINKED_SHOWTIME")
    assert refused.status_code == 404

    still = get_success_data(api_client.get_programming_event(event["id"], PROGRAMMER))
    assert still["status"] == "DRAFT"
    assert still["pre_show_content_status"] == "PRE_SHOW_APPROVED"


def test_themed_menu_rows_bind_only_for_special_event_showtimes(api):
    """PRD §3.1: "a `SPECIAL_EVENT` showtime is one that expects a programming
    event to be attached and approved before it may sell."
    PRD §3.2: "Activation is the act that lets the evening sell."

    Design: Corner/validations/conditional_validation_only_binds_for_special_event_showtimes
    """
    scenario = setup_standard_and_special_showtimes()

    standard = validate_success(
        api_client.open_dining(scenario["standard"]["id"], LEAD), 200
    )
    assert standard["status"] == "DINING_OPEN", (
        "a STANDARD showtime opens with no programming event in existence at all"
    )

    # The gate that binds a SPECIAL_EVENT showtime is the thematic one, so the
    # clock is moved to that showtime's own seating window rather than left where
    # the STANDARD showtime's window happens to be open.
    set_clock("2026-09-01T21:15:00Z")
    special = read_showtime(scenario["special"]["id"], LEAD)
    assert special["dining_open_at_utc"].startswith("2026-09-01T21:10"), (
        "the clock is inside the special showtime's own seating window"
    )
    refused = api_client.open_dining(scenario["special"]["id"], LEAD)
    validate_error(refused, "ERR_THEMED_MENU_REQUIRED")


def test_completing_a_showtime_twice_is_answered_as_already_terminal(api):
    """PRD §3.7: "it explicitly refuses a showtime that is already terminal — a
    repeat completion of a `COMPLETED` showtime is answered with
    `ERR_ALREADY_TERMINAL` rather than re-running the close-out cascade a second
    time and double-counting the points."
    PRD §3.7: "It also requires a clean kitchen: every ticket on the showtime must
    already be either `DELIVERED` or `VOIDED`".

    Design: Corner/errors/already_terminal_error_is_reachable_on_a_completed_showtime
    """
    scenario = setup_completed_showtime_for_reopen()
    showtime = scenario["showtime"]
    first = validate_success(api_client.complete_showtime(showtime["id"], LEAD), 200)
    assert first["status"] == "COMPLETED"

    second = api_client.complete_showtime(showtime["id"], LEAD)
    validate_error(second, "ERR_ALREADY_TERMINAL")
    assert second.status_code == 409


def test_a_repeat_completion_does_not_rescore_the_section(api):
    """PRD §3.7: "a repeat completion of a `COMPLETED` showtime is answered with
    `ERR_ALREADY_TERMINAL` rather than re-running the close-out cascade a second
    time and double-counting the points."
    PRD §3.9: "`Server.lifetime_points += assignment_points` on close".

    Design: Corner/errors/already_terminal_error_is_reachable_on_a_completed_showtime
    """
    scenario = setup_completed_showtime_for_reopen()
    showtime, server = scenario["showtime"], scenario["server"]
    validate_success(api_client.complete_showtime(showtime["id"], LEAD), 200)
    points_after_first = get_success_data(api_client.get_server(server["id"], LEAD))["lifetime_points"]

    validate_error(api_client.complete_showtime(showtime["id"], LEAD), "ERR_ALREADY_TERMINAL")
    points_after_second = get_success_data(api_client.get_server(server["id"], LEAD))["lifetime_points"]
    assert points_after_second == points_after_first, (
        "no second close-out cascade ran, so the section was not re-scored"
    )


def test_a_dining_closed_showtime_refuses_a_fresh_placement(api):
    """PRD §3.3: "the showtime's `mode` must be `DINING_OPEN`, otherwise the placement
    is rejected outright with `ERR_SILENT_ORDER_VIOLATION` (HTTP 409) and *no slip
    row is created at all*."
    PRD §2.4: "It holds `DINING_OPEN` while the seating window admits orders and
    `DINING_CLOSED` once the showtime leaves the dining phases".

    Design: Corner/errors/silent_order_violation_fires_once_the_dining_window_closes
    """
    scenario = setup_in_service_showtime(
        start_at_utc="2026-09-01T20:00:00Z", runtime_minutes=100,
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=lambda s: place_scenario_slip(
            s, seat=1, catalog_name="Arepa", prepare_clock="2026-09-01T19:50:00Z"),
    )
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]
    item = scenario["item"]

    # PRD §3.3 evaluates the seating gate on the showtime's ordered window
    # instants "before any capacity computation", so the closed-dining refusal is
    # reported ahead of any band verdict. The clock is taken out past the entrée
    # deadline as well, so the only reason the placement is refused is the mode.
    set_clock("2026-09-01T21:30:00Z")
    version = read_showtime(showtime["id"], LEAD)["version"]
    refused = api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 10, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": version},
        server_headers(server),
    )
    validate_error(refused, "ERR_SILENT_ORDER_VIOLATION")
    assert refused.status_code == 409

    slips, meta = validate_paginated(
        api_client.list_showtime_order_slips(showtime["id"], LEAD)
    )
    assert len(slips) == 1, "the rejected placement wrote no new slip row at all"
    assert meta["total_count"] == 1
    # The derived window is unchanged: only the clock moved.
    assert read_showtime(showtime["id"], LEAD)["dining_open_at_utc"] == "2026-09-01T19:40:00Z"
    assert read_showtime(showtime["id"], LEAD)["dining_close_at_utc"] == "2026-09-01T20:45:00Z"


def test_a_stale_auditorium_posture_self_heals_on_read(api):
    """PRD §2.5: "Reconciliation is not deferred to a batch job: a stored posture
    value that disagrees with this predicate is recomputed and persisted at the
    moment it is read."
    PRD §2.5: "It is `READY` when any scheduled showtime has already reached its
    `dining_open_at_utc`".
    PRD §2.5: "`NEARLY_READY` when a scheduled showtime's `dining_open_at_utc` is
    at or after the current instant but strictly before the current instant plus
    30 minutes".
    PRD §2.5: "`SETUP` when a scheduled showtime's `dining_open_at_utc` is at
    least 30 minutes beyond the current instant".

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_self_heals_a_stale_auditorium_posture
    """
    scenario = setup_scheduled_showtime(start_at_utc="2026-09-01T20:00:00Z",
                                        runtime_minutes=60, clock="2026-09-01T18:00:00Z")
    auditorium = scenario["auditorium"]

    at_eighteen = read_posture(auditorium["id"], LEAD)
    assert at_eighteen["build_phase"] == "SETUP", (
        "the 19:40 dining open is more than thirty minutes away"
    )

    set_clock("2026-09-01T19:20:00Z")
    nearly = read_posture(auditorium["id"], LEAD)
    assert nearly["build_phase"] == "NEARLY_READY", (
        "19:40 falls inside the thirty-minute ready lead from 19:20"
    )

    set_clock("2026-09-01T19:45:00Z")
    ready = read_posture(auditorium["id"], LEAD)
    assert ready["build_phase"] == "READY", "19:45 is already past the 19:40 dining open"
    assert ready["next_scheduled_showtime_dining_open_at_utc"] == "2026-09-01T19:40:00Z"