"""Composite setup helpers for the Broadcast Operations API.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test starts against an empty database with the
logical clock at its startup value.

Setup steps use the lenient success reader so a broken precondition reports as a
setup failure rather than as a confusing assertion inside a test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import (
    AIR_CLOCK,
    BOOKING_WINDOW_END,
    BOOKING_WINDOW_START,
    CALL_SCHEDULED_RELEASE,
    CALL_TIME,
    REHEARSAL_START,
    TEST_FILING_CLOCK,
    TEST_WINDOW_END,
    TEST_WINDOW_START,
)
from .factories import (
    create_camera_position_payload,
    create_crew_call_payload,
    create_crew_member_payload,
    create_data_feed_payload,
    create_path_booking_payload,
    create_production_payload,
    create_rehearsal_payload,
    create_satellite_path_payload,
    create_show_execution_payload,
    create_system_prep_payload,
    create_transmission_path_payload,
    create_truck_payload,
    create_venue_survey_payload,
    crew_call_response_payload,
    path_test_result_payload,
    rehearsal_outcome_payload,
    schedule_path_test_payload,
    survey_review_payload,
    truck_assignment_payload,
)
from .test_users import TEST_USERS, make_crew_member_headers

PM = TEST_USERS["production_manager_headers"]
TD = TEST_USERS["technical_director_headers"]
LO = TEST_USERS["league_operations_headers"]
US = TEST_USERS["union_steward_headers"]

#: The default two-position camera plot: 2.03 dB + 2.03 dB, 40 amps drawn.
DEFAULT_CAMERA_PLOT = [
    {
        "label": "HIGH_HOME",
        "position_type": "HARD",
        "cable_run_feet": 150,
        "power_draw_amps": 20,
    },
    {
        "label": "CENTER_FIELD",
        "position_type": "ROBO",
        "cable_run_feet": 150,
        "power_draw_amps": 20,
    },
]

#: A single-position plot: 2.03 dB, 20 amps drawn.
SINGLE_CAMERA_PLOT = [
    {
        "label": "HIGH_HOME",
        "position_type": "HARD",
        "cable_run_feet": 150,
        "power_draw_amps": 20,
    },
]


# ---------------------------------------------------------------------------
# Clock and plain reads
# ---------------------------------------------------------------------------
def set_clock(api, to_iso8601, headers=TD):
    """Move the logical clock to an instant."""
    return get_success_data(api.set_clock(to_iso8601, headers))


def read_production(api, production_id, headers=PM):
    return get_success_data(api.get_production(production_id, headers))


def read_truck(api, truck_id, headers=PM):
    return get_success_data(api.get_truck(truck_id, headers))


def read_survey(api, survey_id, headers=TD):
    return get_success_data(api.get_venue_survey(survey_id, headers))


def read_path(api, path_id, headers=TD):
    return get_success_data(api.get_transmission_path(path_id, headers))


def read_booking(api, booking_id, headers=TD):
    return get_success_data(api.get_path_booking(booking_id, headers))


def read_crew_member(api, crew_member_id, headers=PM):
    return get_success_data(api.get_crew_member(crew_member_id, headers))


def read_crew_call(api, call_id, headers=PM):
    return get_success_data(api.get_crew_call(call_id, headers))


def read_feed(api, feed_id, headers=TD):
    return get_success_data(api.get_data_feed(feed_id, headers))


def read_prep(api, prep_id, headers=TD):
    return get_success_data(api.get_system_prep(prep_id, headers))


def read_rehearsal(api, rehearsal_id, headers=TD):
    return get_success_data(api.get_rehearsal(rehearsal_id, headers))


def read_show(api, show_id, headers=PM):
    return get_success_data(api.get_show_execution(show_id, headers))


def production_version(api, production_id, headers=PM) -> int:
    """The production's current version, the token the guarded writes demand."""
    return read_production(api, production_id, headers)["version"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------
def new_production(api, headers=PM, **overrides):
    return get_success_data(
        api.create_production(create_production_payload(**overrides), headers), 201
    )


def new_truck(api, headers=PM, **overrides):
    return get_success_data(
        api.create_truck(create_truck_payload(**overrides), headers), 201
    )


def new_fiber_path(api, headers=TD, **overrides):
    return get_success_data(
        api.create_transmission_path(
            create_transmission_path_payload(**overrides), headers
        ),
        201,
    )


def new_satellite_path(api, headers=TD, **overrides):
    return get_success_data(
        api.create_transmission_path(
            create_satellite_path_payload(**overrides), headers
        ),
        201,
    )


def new_crew_member(api, headers=PM, **overrides):
    return get_success_data(
        api.create_crew_member(create_crew_member_payload(**overrides), headers), 201
    )


def new_data_feed(api, headers=TD, **overrides):
    return get_success_data(
        api.create_data_feed(create_data_feed_payload(**overrides), headers), 201
    )


def new_show_execution(api, production_id, headers=PM):
    return get_success_data(
        api.create_show_execution(
            create_show_execution_payload(production_id), headers
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Tier 2: the venue survey loop
# ---------------------------------------------------------------------------
def new_survey(api, production_id, positions=None, headers=TD, **overrides):
    """Open a survey and lay in its camera plot. Leaves the survey in DRAFT."""
    survey = get_success_data(
        api.create_venue_survey(
            create_venue_survey_payload(production_id, **overrides), headers
        ),
        201,
    )
    plot = DEFAULT_CAMERA_PLOT if positions is None else positions
    for position in plot:
        add_camera_position(api, survey["id"], headers=headers, **position)
    return read_survey(api, survey["id"], headers)


def add_camera_position(api, survey_id, headers=TD, **overrides):
    return get_success_data(
        api.create_camera_position(
            survey_id, create_camera_position_payload(**overrides), headers
        ),
        201,
    )


def submit_survey(api, survey_id, headers=TD):
    return get_success_data(api.submit_venue_survey(survey_id, headers))


def review_survey(api, survey_id, decision="APPROVE", headers=LO, **overrides):
    return get_success_data(
        api.review_venue_survey(
            survey_id, survey_review_payload(decision, **overrides), headers
        )
    )


def create_approved_survey(api, production_id, positions=None,
                           submitter=TD, reviewer=LO, **overrides):
    """Open, plot, submit and approve a survey. Drives the production to SURVEYED."""
    survey = new_survey(api, production_id, positions, headers=submitter, **overrides)
    submit_survey(api, survey["id"], submitter)
    return review_survey(api, survey["id"], "APPROVE", reviewer)


# ---------------------------------------------------------------------------
# Tier 2: truck assignment
# ---------------------------------------------------------------------------
def assign_truck(api, production_id, truck_id, expected_version=None, headers=PM):
    """Assign a truck, reading the production's current version when not given."""
    if expected_version is None:
        expected_version = production_version(api, production_id, headers)
    return get_success_data(
        api.assign_truck(
            production_id, truck_assignment_payload(truck_id, expected_version), headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: transmission bookings and their proving tests
# ---------------------------------------------------------------------------
def book_path(api, production_id, path_id, expected_version=None, headers=TD,
              **overrides):
    """Create a path booking. Leaves it at RESERVED."""
    if expected_version is None:
        expected_version = production_version(api, production_id)
    return get_success_data(
        api.create_path_booking(
            create_path_booking_payload(
                production_id, path_id, expected_version, **overrides
            ),
            headers,
        ),
        201,
    )


def schedule_test(api, booking_id, headers=TD, **overrides):
    return get_success_data(
        api.schedule_path_test(
            booking_id, schedule_path_test_payload(**overrides), headers
        )
    )


def file_test_result(api, booking_id, outcome="PASS", headers=TD, **overrides):
    return get_success_data(
        api.record_path_test_result(
            booking_id, path_test_result_payload(outcome, **overrides), headers
        )
    )


def confirm_booking(api, booking_id,
                    test_window_start_utc=TEST_WINDOW_START,
                    test_window_end_utc=TEST_WINDOW_END,
                    filing_clock=TEST_FILING_CLOCK,
                    headers=TD):
    """Book a proving window, move the clock inside it and file a pass."""
    schedule_test(
        api, booking_id, headers=headers,
        test_window_start_utc=test_window_start_utc,
        test_window_end_utc=test_window_end_utc,
    )
    set_clock(api, filing_clock, headers)
    return file_test_result(api, booking_id, "PASS", headers)


def create_confirmed_booking(api, production_id, path_id, headers=TD, **overrides):
    """A booking proven by a passing transmission test. Leaves it at CONFIRMED."""
    booking = book_path(api, production_id, path_id, headers=headers, **overrides)
    return confirm_booking(api, booking["id"], headers=headers)


# ---------------------------------------------------------------------------
# Tier 2: show systems
# ---------------------------------------------------------------------------
def create_prep(api, production_id, data_feed_id, headers=TD, **overrides):
    return get_success_data(
        api.create_system_prep(
            create_system_prep_payload(production_id, data_feed_id, **overrides),
            headers,
        ),
        201,
    )


def validate_prep(api, prep_id, headers=TD):
    return get_success_data(api.validate_prep_feed(prep_id, headers))


def create_validated_prep(api, production_id, data_feed_id, headers=TD, **overrides):
    prep = create_prep(api, production_id, data_feed_id, headers, **overrides)
    return validate_prep(api, prep["id"], headers)


# ---------------------------------------------------------------------------
# Tier 2: crew calls
# ---------------------------------------------------------------------------
def offer_call(api, production_id, crew_member_id, expected_version=None, headers=PM,
               **overrides):
    """Offer a crew call. Leaves it at OFFERED with its provisional reserve booked."""
    if expected_version is None:
        expected_version = production_version(api, production_id)
    return get_success_data(
        api.create_crew_call(
            create_crew_call_payload(
                production_id, crew_member_id, expected_version, **overrides
            ),
            headers,
        ),
        201,
    )


def accept_call(api, call_id, crew_member_id):
    return get_success_data(
        api.respond_to_crew_call(
            call_id,
            crew_call_response_payload("ACCEPT"),
            make_crew_member_headers(crew_member_id),
        )
    )


def decline_call(api, call_id, crew_member_id):
    return get_success_data(
        api.respond_to_crew_call(
            call_id,
            crew_call_response_payload("DECLINE"),
            make_crew_member_headers(crew_member_id),
        )
    )


def create_accepted_call(api, production_id, crew_member_id, headers=PM, **overrides):
    call = offer_call(api, production_id, crew_member_id, headers=headers, **overrides)
    return accept_call(api, call["id"], crew_member_id)


# ---------------------------------------------------------------------------
# Tier 2: rehearsal
# ---------------------------------------------------------------------------
def schedule_rehearsal(api, production_id, headers=TD, **overrides):
    return get_success_data(
        api.create_rehearsal(
            create_rehearsal_payload(production_id, **overrides), headers
        ),
        201,
    )


def record_outcome(api, rehearsal_id, outcome="COMPLETED", headers=TD, **overrides):
    return get_success_data(
        api.record_rehearsal_outcome(
            rehearsal_id, rehearsal_outcome_payload(outcome, **overrides), headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: air control
# ---------------------------------------------------------------------------
def set_air_status(api, show_id, target, headers=TD):
    return get_success_data(api.set_air_status(show_id, target, headers))


def log_incident(api, show_id, headers=TD, **overrides):
    from .factories import create_incident_payload

    return get_success_data(
        api.create_incident(show_id, create_incident_payload(**overrides), headers),
        201,
    )


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle chains
# ---------------------------------------------------------------------------
def setup_surveyed_production(api, positions=None, production=None):
    """A production whose survey has been approved. Leaves the stage at SURVEYED."""
    ctx = {"production": production or new_production(api)}
    ctx["survey"] = create_approved_survey(api, ctx["production"]["id"], positions)
    ctx["production"] = read_production(api, ctx["production"]["id"])
    return ctx


def setup_provisioned_production(api, positions=None, production=None, truck=None,
                                 path=None, feed=None, booking_overrides=None,
                                 prep_overrides=None):
    """The three provisioning conditions satisfied: a truck, a CONFIRMED PRIMARY
    booking and one VALIDATED preparation. Leaves the stage at PROVISIONED.

    Returns a context dict keyed production, truck, path, feed, survey, booking, prep.
    """
    ctx = {"production": production or new_production(api)}
    production_id = ctx["production"]["id"]
    ctx["truck"] = truck or new_truck(api)
    ctx["path"] = path or new_fiber_path(api)
    ctx["feed"] = feed or new_data_feed(api)
    ctx["survey"] = create_approved_survey(api, production_id, positions)
    assign_truck(api, production_id, ctx["truck"]["id"])
    ctx["booking"] = create_confirmed_booking(
        api, production_id, ctx["path"]["id"], **(booking_overrides or {})
    )
    ctx["prep"] = create_validated_prep(
        api, production_id, ctx["feed"]["id"], **(prep_overrides or {})
    )
    ctx["production"] = read_production(api, production_id)
    ctx["truck"] = read_truck(api, ctx["truck"]["id"])
    ctx["path"] = read_path(api, ctx["path"]["id"])
    return ctx


DEFAULT_CREW_ROSTER = [
    {"full_name": "Dana Reyes", "position": "TD"},
    {"full_name": "Milo Fisk", "position": "CAM_OP"},
]


def hire_and_accept_crew(api, production_id, roster=None,
                         call_time_utc=CALL_TIME,
                         scheduled_release_utc=CALL_SCHEDULED_RELEASE):
    """Register a roster, offer each member a call and have each one accept."""
    members, calls = [], []
    for spec in (roster if roster is not None else DEFAULT_CREW_ROSTER):
        member = new_crew_member(api, **spec)
        members.append(member)
        call = offer_call(
            api, production_id, member["id"],
            call_time_utc=call_time_utc,
            scheduled_release_utc=scheduled_release_utc,
        )
        calls.append(accept_call(api, call["id"], member["id"]))
    return members, calls


def setup_rehearsed_production(api, positions=None, production=None, truck=None,
                               path=None, feed=None, roster=None,
                               call_time_utc=CALL_TIME,
                               scheduled_release_utc=CALL_SCHEDULED_RELEASE,
                               rehearsal_start_utc=REHEARSAL_START,
                               booking_overrides=None, prep_overrides=None):
    """A fully certified remote: approved plot, truck, proven primary transport,
    validated preparation, the full crew accepted and the rehearsal completed.
    Leaves the stage at REHEARSED with certified readiness at 100.00.
    """
    ctx = setup_provisioned_production(
        api, positions=positions, production=production, truck=truck, path=path,
        feed=feed, booking_overrides=booking_overrides, prep_overrides=prep_overrides,
    )
    production_id = ctx["production"]["id"]
    ctx["crew_members"], ctx["calls"] = hire_and_accept_crew(
        api, production_id, roster, call_time_utc, scheduled_release_utc
    )
    ctx["rehearsal"] = schedule_rehearsal(
        api, production_id, scheduled_start_utc=rehearsal_start_utc
    )
    ctx["rehearsal"] = record_outcome(
        api, ctx["rehearsal"]["id"], "COMPLETED",
        camera_blocking_positions_cleared=ctx["survey"]["camera_position_count"],
        venue_signoff=True, league_ops_signoff=True,
    )
    ctx["production"] = read_production(api, production_id)
    return ctx


def setup_show_pre_show(api, **kwargs):
    """A REHEARSED remote with its show record opened. Air dimension at PRE_SHOW."""
    ctx = setup_rehearsed_production(api, **kwargs)
    ctx["show"] = new_show_execution(api, ctx["production"]["id"])
    return ctx


def setup_show_on_air(api, air_clock=AIR_CLOCK, **kwargs):
    """A REHEARSED remote taken live: the clock is at air time and the microphone open."""
    ctx = setup_show_pre_show(api, **kwargs)
    set_clock(api, air_clock)
    ctx["show"] = set_air_status(api, ctx["show"]["id"], "ON_AIR")
    ctx["production"] = read_production(api, ctx["production"]["id"])
    return ctx


def setup_wrapped_production(api, off_air_clock="2026-08-15T21:00:00Z",
                             wrap_headers=PM, **kwargs):
    """A remote taken live, taken off air and torn down. Leaves the stage at WRAPPED."""
    ctx = setup_show_on_air(api, **kwargs)
    set_clock(api, off_air_clock)
    ctx["show"] = set_air_status(api, ctx["show"]["id"], "OFF_AIR")
    ctx["production"] = get_success_data(
        api.wrap_production(ctx["production"]["id"], wrap_headers)
    )
    ctx["truck"] = read_truck(api, ctx["truck"]["id"])
    return ctx


def setup_settled_production(api, settle_headers=US, **kwargs):
    """A remote closed out end to end. Leaves the stage at SETTLED."""
    ctx = setup_wrapped_production(api, **kwargs)
    ctx["production"] = get_success_data(
        api.settle_production(ctx["production"]["id"], settle_headers)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: threshold and accumulation targeting
# ---------------------------------------------------------------------------
def setup_booking_at_test_attempt_limit(api, production_id=None, path=None,
                                        requested_mbps=200):
    """Drive a booking through three failed proving tests so the attempt ceiling is
    reached. Returns (booking, path, production)."""
    production = read_production(api, production_id) if production_id else new_production(api)
    path = path or new_fiber_path(api)
    booking = book_path(
        api, production["id"], path["id"], requested_mbps=requested_mbps,
        window_start_utc=BOOKING_WINDOW_START, window_end_utc=BOOKING_WINDOW_END,
    )
    windows = [
        ("2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z", "2026-08-15T12:30:00Z"),
        ("2026-08-15T13:00:00Z", "2026-08-15T14:00:00Z", "2026-08-15T13:30:00Z"),
        ("2026-08-15T14:00:00Z", "2026-08-15T15:00:00Z", "2026-08-15T14:30:00Z"),
    ]
    for start, end, filing in windows:
        schedule_test(
            api, booking["id"],
            test_window_start_utc=start, test_window_end_utc=end,
        )
        set_clock(api, filing)
        booking = file_test_result(api, booking["id"], "FAIL")
    return booking, read_path(api, path["id"]), read_production(api, production["id"])


def setup_survey_at_revision(api, production_id, target_revision,
                             positions=None):
    """Run the submit / request-changes loop until the survey reaches a revision.

    Each request for changes followed by a fresh camera position advances the
    revision by exactly 1, so the survey ends in DRAFT at ``target_revision``.
    """
    survey = new_survey(api, production_id, positions or SINGLE_CAMERA_PLOT)
    revision = survey["revision"]
    counter = 0
    while revision < target_revision:
        submit_survey(api, survey["id"])
        review_survey(api, survey["id"], "REQUEST_CHANGES")
        counter += 1
        add_camera_position(
            api, survey["id"], label=f"EXTRA_{counter}", position_type="ROBO",
            cable_run_feet=150, power_draw_amps=20,
        )
        survey = read_survey(api, survey["id"])
        revision = survey["revision"]
    return survey


def setup_feed_at_consumer_ceiling(api, production_id, max_concurrent_consumers=1):
    """Fill a feed's validated-consumer slots exactly to its ceiling.

    Returns (feed, validated_preps).
    """
    feed = new_data_feed(api, max_concurrent_consumers=max_concurrent_consumers)
    kinds = ["GRAPHICS", "STATS", "REPLAY"]
    preps = []
    for index in range(max_concurrent_consumers):
        kind = kinds[index % len(kinds)]
        extra = {"replay_channel_count": 4} if kind == "REPLAY" else {}
        preps.append(
            create_validated_prep(
                api, production_id, feed["id"], system_kind=kind, **extra
            )
        )
    return read_feed(api, feed["id"]), preps
