"""Access control and the validation ladder: which single error survives, and which
operator identity may act.

Every test builds its own preconditions from scratch, because each test starts
against an empty database with the logical clock at its startup value.
"""

from test_helpers import (
    assert_instant_equals,
    assert_labor_ledger,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import UNKNOWN_UUIDS
from test_helpers.factories import (
    create_crew_call_payload,
    create_path_booking_payload,
    crew_call_response_payload,
    schedule_path_test_payload,
    survey_review_payload,
    truck_assignment_payload,
)
from test_helpers.test_users import (
    LEAGUE_OPERATIONS_ID,
    PRODUCTION_MANAGER_ID,
    TECHNICAL_DIRECTOR_ID,
    UNDECLARED_ROLE,
    make_crew_member_headers,
    make_empty_role_headers,
    make_empty_user_id_headers,
    make_headers,
    make_league_operations_headers,
)

# The transport window used by the proving-test scenarios.
BOOKING_WINDOW_START = "2026-08-15T16:00:00Z"
BOOKING_WINDOW_END = "2026-08-15T23:00:00Z"
PROVING_WINDOW_START = "2026-08-15T16:00:00Z"
PROVING_WINDOW_END = "2026-08-15T17:00:00Z"
PROVING_FILING_CLOCK = "2026-08-15T16:30:00Z"
#: A test window that escapes the booking on its early side.
ESCAPING_TEST_START = "2026-08-15T15:00:00Z"
ESCAPING_TEST_END = "2026-08-15T15:30:00Z"

# A 600-minute call: 104,000 cents provisional at the 9,000-cent card rate.
OVER_BUDGET_CALL_TIME = "2026-08-15T16:00:00Z"
OVER_BUDGET_CALL_RELEASE = "2026-08-16T02:00:00Z"
TINY_LABOR_BUDGET_CENTS = 50_000


def _booked_transport(api):
    """A TIER_3 production with one RESERVED PRIMARY fiber booking for 16:00-23:00."""
    production = fixtures.new_production(api)
    path = fixtures.new_fiber_path(api, path_code="FIB-A", capacity_mbps=300)
    booking = fixtures.book_path(
        api,
        production["id"],
        path["id"],
        requested_mbps=100,
        window_start_utc=BOOKING_WINDOW_START,
        window_end_utc=BOOKING_WINDOW_END,
    )
    return production, path, booking


def test_unknown_path_id_outranks_a_stale_production_version_on_a_booking(
    api, td_headers
):
    """A booking that names a non-existent path and also presents a stale production
    version is reported at the referential rung, never at the concurrency rung.

    PRD: "A rejected request returns exactly one error: the surviving violation with the **lowest** priority number in the ordering below."
    PRD: "7. **Existence of the referenced transmission path**, whether named by the path or by a body `path_id`: `ERR_PATH_NOT_FOUND`."
    PRD: "17. **Optimistic concurrency** on `expected_production_version`: `ERR_STALE_PRODUCTION_VERSION`."
    Design: Difficulty/priority_pair_validation_conflict/path_not_found_outranks_stale_production_version
    """
    production = fixtures.new_production(api)
    payload = create_path_booking_payload(
        production["id"],
        UNKNOWN_UUIDS["path"],
        production["version"] - 1,
        window_start_utc=BOOKING_WINDOW_START,
        window_end_utc=BOOKING_WINDOW_END,
        requested_mbps=100,
    )

    validate_error(api.create_path_booking(payload, td_headers), "ERR_PATH_NOT_FOUND")

    _, meta = validate_paginated(
        api.list_path_bookings(td_headers, {"production_id": production["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the rejected booking must not have been written, "
        f"got total_count {meta['total_count']}"
    )


def test_stale_production_version_answers_once_the_path_id_resolves(api, td_headers):
    """With the same stale version but a path that exists, the concurrency rung is the
    surviving violation, which is what makes the referential rung's win meaningful.

    PRD: "If that value does not equal the referenced production's current `version`, the request is rejected with `ERR_STALE_PRODUCTION_VERSION` (HTTP 412) and nothing is written."
    Design: Difficulty/priority_pair_validation_conflict/path_not_found_outranks_stale_production_version
    """
    production = fixtures.new_production(api)
    path = fixtures.new_fiber_path(api, path_code="FIB-A", capacity_mbps=300)
    payload = create_path_booking_payload(
        production["id"],
        path["id"],
        production["version"] - 1,
        window_start_utc=BOOKING_WINDOW_START,
        window_end_utc=BOOKING_WINDOW_END,
        requested_mbps=100,
    )

    validate_error(
        api.create_path_booking(payload, td_headers), "ERR_STALE_PRODUCTION_VERSION"
    )

    unchanged = fixtures.read_path(api, path["id"])
    assert unchanged["committed_mbps_total"] == 0, (
        f"nothing is written on a stale request, so the path must still commit 0 Mbps, "
        f"got {unchanged['committed_mbps_total']}"
    )
    assert unchanged["active_booking_count"] == 0, (
        f"Expected active_booking_count 0, got {unchanged['active_booking_count']}"
    )


def test_stale_production_version_outranks_the_blown_labor_budget(api, pm_headers):
    """A crew call that is both stale and over budget is reported at the concurrency
    rung, because money is evaluated last of all.

    PRD: "A rejected request returns exactly one error: the surviving violation with the **lowest** priority number in the ordering below."
    PRD: "17. **Optimistic concurrency** on `expected_production_version`: `ERR_STALE_PRODUCTION_VERSION`."
    PRD: "50. **Labor budget, evaluated last of all**: `ERR_LABOR_BUDGET_EXCEEDED`."
    Design: Difficulty/priority_pair_validation_conflict/stale_production_version_outranks_labor_budget_exceeded
    """
    production = fixtures.new_production(
        api, labor_budget_total_cents=TINY_LABOR_BUDGET_CENTS
    )
    member = fixtures.new_crew_member(api)
    payload = create_crew_call_payload(
        production["id"],
        member["id"],
        production["version"] - 1,
        call_time_utc=OVER_BUDGET_CALL_TIME,
        scheduled_release_utc=OVER_BUDGET_CALL_RELEASE,
    )

    validate_error(
        api.create_crew_call(payload, pm_headers), "ERR_STALE_PRODUCTION_VERSION"
    )

    after = fixtures.read_production(api, production["id"])
    assert_labor_ledger(after, 0, TINY_LABOR_BUDGET_CENTS)
    _, meta = validate_paginated(
        api.list_crew_calls(pm_headers, {"production_id": production["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the rejected offer must not have been written, "
        f"got total_count {meta['total_count']}"
    )


def test_labor_budget_answers_once_the_production_version_is_fresh(api, pm_headers):
    """With a fresh version the very same over-committed offer is reported at the
    fiscal rung, which is what makes the concurrency rung's win meaningful.

    PRD: "The offer is refused with `ERR_LABOR_BUDGET_EXCEEDED` when the production's current `labor_committed_cents` plus the candidate call's `provisional_total_cents` would be strictly greater than its `labor_budget_total_cents`; a total exactly equal to the budget is accepted."
    Design: Difficulty/priority_pair_validation_conflict/stale_production_version_outranks_labor_budget_exceeded
    """
    production = fixtures.new_production(
        api, labor_budget_total_cents=TINY_LABOR_BUDGET_CENTS
    )
    member = fixtures.new_crew_member(api)
    payload = create_crew_call_payload(
        production["id"],
        member["id"],
        production["version"],
        call_time_utc=OVER_BUDGET_CALL_TIME,
        scheduled_release_utc=OVER_BUDGET_CALL_RELEASE,
    )

    validate_error(
        api.create_crew_call(payload, pm_headers), "ERR_LABOR_BUDGET_EXCEEDED"
    )

    after = fixtures.read_production(api, production["id"])
    assert_labor_ledger(after, 0, TINY_LABOR_BUDGET_CENTS)


def test_confirmed_booking_status_outranks_an_escaping_retest_window(api, td_headers):
    """A booking already proven by a passing test refuses a further test window at the
    booking-status rung, even when that window also escapes the occupation window.

    PRD: "A rejected request returns exactly one error: the surviving violation with the **lowest** priority number in the ordering below."
    PRD: "22. **Booking status** permits the operation: `ERR_BOOKING_STATE_INVALID`."
    PRD: "31. **Transmission-test window geometry**: `ERR_TEST_WINDOW_INVALID`."
    Design: Difficulty/priority_pair_validation_conflict/booking_state_invalid_outranks_test_window_invalid
    """
    production, path, booking = _booked_transport(api)
    confirmed = fixtures.confirm_booking(
        api,
        booking["id"],
        test_window_start_utc=PROVING_WINDOW_START,
        test_window_end_utc=PROVING_WINDOW_END,
        filing_clock=PROVING_FILING_CLOCK,
    )
    assert confirmed["status"] == "CONFIRMED", (
        f"Expected the booking to be CONFIRMED by the passing test, "
        f"got {confirmed['status']}"
    )

    refused = api.schedule_path_test(
        booking["id"],
        schedule_path_test_payload(
            test_window_start_utc=ESCAPING_TEST_START,
            test_window_end_utc=ESCAPING_TEST_END,
        ),
        td_headers,
    )
    validate_error(refused, "ERR_BOOKING_STATE_INVALID")

    after = fixtures.read_booking(api, booking["id"])
    assert after["status"] == "CONFIRMED", (
        f"the refused reschedule must leave the booking CONFIRMED, "
        f"got {after['status']}"
    )
    assert_instant_equals(
        after["test_window_start_utc"], PROVING_WINDOW_START, "test_window_start_utc"
    )
    assert_instant_equals(
        after["test_window_end_utc"], PROVING_WINDOW_END, "test_window_end_utc"
    )


def test_escaping_test_window_answers_on_a_booking_still_at_reserved(api, td_headers):
    """On a booking whose status does permit the operation, the same escaping window is
    reported at the window-geometry rung.

    PRD: "The test window must be non-empty — an end at or before the start is `ERR_INVALID_TIME_WINDOW` — and it must lie **fully inside** the booking's own occupation window, meaning the test start is at or after `window_start_utc` and the test end is at or before `window_end_utc`; a window that escapes the booking is refused with `ERR_TEST_WINDOW_INVALID`."
    Design: Difficulty/priority_pair_validation_conflict/booking_state_invalid_outranks_test_window_invalid
    """
    production, path, booking = _booked_transport(api)
    assert booking["status"] == "RESERVED", (
        f"Expected a surviving booking to be created at RESERVED, "
        f"got {booking['status']}"
    )

    refused = api.schedule_path_test(
        booking["id"],
        schedule_path_test_payload(
            test_window_start_utc=ESCAPING_TEST_START,
            test_window_end_utc=ESCAPING_TEST_END,
        ),
        td_headers,
    )
    validate_error(refused, "ERR_TEST_WINDOW_INVALID")

    after = fixtures.read_booking(api, booking["id"])
    assert after["status"] == "RESERVED", (
        f"the refused schedule must leave the booking RESERVED, got {after['status']}"
    )


def test_technical_director_cannot_assign_the_production_truck(
    api, td_headers, pm_headers
):
    """Truck assignment sits on the ProductionManager side of the peer split, so an
    otherwise perfect request from a TechnicalDirector is refused on authorization
    alone and leaves the fleet untouched.

    PRD: "Assigning a truck to a remote is a `ProductionManager` action that names the `truck_id` and, because the assignment can supersede an earlier one, must carry `expected_production_version` as described in §2.5."
    PRD: "Once both headers are present, the role string must be one of the five declared roles *and* must appear in the target endpoint's authorized-role list; otherwise the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "When the assignment succeeds, the production's `truck_id` is set to the named truck, the production's `version` is incremented by 1, and the derivation of §2.9 runs — which is how a production that was waiting only on transport can jump `SURVEYED → PROVISIONED` inside the assignment request."
    Design: Corner/rbac/technical_director_cannot_assign_the_production_truck
    """
    production = fixtures.new_production(api)
    truck = fixtures.new_truck(api)
    payload = truck_assignment_payload(truck["id"], production["version"])

    validate_error(
        api.assign_truck(production["id"], payload, td_headers), "ERR_UNAUTHORIZED"
    )

    held = fixtures.read_production(api, production["id"])
    assert held["truck_id"] is None, (
        f"the refused assignment must leave truck_id null, got {held['truck_id']}"
    )
    assert held["version"] == production["version"], (
        f"a rejected write must not consume the concurrency token: expected version "
        f"{production['version']}, got {held['version']}"
    )
    assert fixtures.read_truck(api, truck["id"])["status"] == "AVAILABLE", (
        "the refused assignment must leave the truck AVAILABLE"
    )

    assigned = validate_success(
        api.assign_truck(production["id"], payload, pm_headers)
    )
    assert assigned["truck_id"] == truck["id"], (
        f"Expected truck_id {truck['id']}, got {assigned['truck_id']}"
    )
    assert assigned["version"] == production["version"] + 1, (
        f"Expected version {production['version'] + 1} after the assignment, "
        f"got {assigned['version']}"
    )


def test_crew_member_cannot_respond_to_another_members_call(api):
    """`CrewMember` authority is row-scoped: the wrong member holds the right role and
    is still refused, and the call survives for the member it names.

    PRD: "Concretely, a crew member responding to a call must be the member the call names: if `X-User-ID` differs from the call's `crew_member_id`, the response is refused with `ERR_NOT_CALL_OWNER` (HTTP 403)."
    PRD: "An acceptance moves the call `OFFERED → ACCEPTED`, which raises the certified crew component and runs the derivation — an acceptance is one of the ways a production reaches full certified readiness."
    Design: Corner/rbac/crew_member_cannot_respond_to_another_members_call
    """
    production = fixtures.new_production(api)
    called = fixtures.new_crew_member(api, full_name="Dana Reyes", position="TD")
    other = fixtures.new_crew_member(api, full_name="Milo Fisk", position="CAM_OP")
    call = fixtures.offer_call(api, production["id"], called["id"])

    refused = api.respond_to_crew_call(
        call["id"],
        crew_call_response_payload("ACCEPT"),
        make_crew_member_headers(other["id"]),
    )
    validate_error(refused, "ERR_NOT_CALL_OWNER")
    assert fixtures.read_crew_call(api, call["id"])["status"] == "OFFERED", (
        "the refused response must leave the call OFFERED for its rightful member"
    )

    accepted = validate_success(
        api.respond_to_crew_call(
            call["id"],
            crew_call_response_payload("ACCEPT"),
            make_crew_member_headers(called["id"]),
        )
    )
    assert accepted["status"] == "ACCEPTED", (
        f"Expected the rightful member's acceptance to land ACCEPTED, "
        f"got {accepted['status']}"
    )


def test_blank_identity_headers_are_rejected_as_unauthenticated(api):
    """An empty identity header counts as absent, and the 401 is decided before the
    path identifier is ever resolved.

    PRD: "Both must be present and non-empty; a header transmitted as an empty string or as whitespace only counts as absent and the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD: "Authentication is checked before authorization, and both are checked before anything else about the request is examined."
    Design: Corner/rbac/blank_identity_headers_rejected_as_unauthenticated
    """
    production = fixtures.new_production(api)

    validate_error(
        api.get_production(
            production["id"], make_empty_user_id_headers("ProductionManager")
        ),
        "ERR_UNAUTHENTICATED",
    )
    validate_error(
        api.get_production(
            UNKNOWN_UUIDS["production"],
            make_empty_role_headers(PRODUCTION_MANAGER_ID),
        ),
        "ERR_UNAUTHENTICATED",
    )


def test_undeclared_role_is_unauthorized_even_on_an_id_that_does_not_exist(api):
    """A syntactically present but undeclared role is a 403, and that too is decided
    ahead of the not-found rung.

    PRD: "Once both headers are present, the role string must be one of the five declared roles *and* must appear in the target endpoint's authorized-role list; otherwise the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "Authentication is checked before authorization, and both are checked before anything else about the request is examined."
    Design: Corner/rbac/blank_identity_headers_rejected_as_unauthenticated
    """
    validate_error(
        api.get_production(
            UNKNOWN_UUIDS["production"],
            make_headers(PRODUCTION_MANAGER_ID, UNDECLARED_ROLE),
        ),
        "ERR_UNAUTHORIZED",
    )


def test_survey_review_by_the_submitting_operator_is_refused(api, lo_headers):
    """The segregation check compares operator identifiers across a role boundary: a
    LeagueOperations request carrying the submitter's identifier is refused, and the
    survey stays reviewable.

    PRD: "On success the survey moves `DRAFT → SUBMITTED` and its `submitted_by_user_id` is stamped with the submitting operator's `X-User-ID`."
    PRD: "Review is only possible on a `SUBMITTED` survey, and the reviewing operator's `X-User-ID` must differ from the survey's `submitted_by_user_id` or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD: "Either decision stamps `reviewed_by_user_id` with the reviewer's operator identifier."
    PRD: "An approval moves the survey `SUBMITTED → APPROVED` and drives the production `PLANNED → SURVEYED` through the derivation, which — if a truck, a confirmed primary transport and enough validated preps are already in place — can carry the production straight on to `PROVISIONED` in the same request."
    Design: Corner/rbac/survey_review_by_the_submitting_operator_rejected
    """
    production = fixtures.new_production(api)
    survey = fixtures.new_survey(
        api, production["id"], fixtures.SINGLE_CAMERA_PLOT
    )
    submitted = fixtures.submit_survey(api, survey["id"])
    assert submitted["submitted_by_user_id"] == TECHNICAL_DIRECTOR_ID, (
        f"Expected submitted_by_user_id {TECHNICAL_DIRECTOR_ID}, "
        f"got {submitted['submitted_by_user_id']}"
    )

    refused = api.review_venue_survey(
        survey["id"],
        survey_review_payload("APPROVE"),
        make_league_operations_headers(TECHNICAL_DIRECTOR_ID),
    )
    validate_error(refused, "ERR_SEGREGATION_OF_DUTIES")

    held = fixtures.read_survey(api, survey["id"])
    assert held["status"] == "SUBMITTED", (
        f"the refused review must leave the survey SUBMITTED, got {held['status']}"
    )
    assert held["reviewed_by_user_id"] is None, (
        f"the refused review must not stamp reviewed_by_user_id, "
        f"got {held['reviewed_by_user_id']}"
    )
    assert fixtures.read_production(api, production["id"])["status"] == "PLANNED", (
        "the refused review must leave the production at PLANNED"
    )

    approved = validate_success(
        api.review_venue_survey(
            survey["id"],
            survey_review_payload("APPROVE", notes="Plot cleared."),
            lo_headers,
        )
    )
    assert approved["status"] == "APPROVED", (
        f"Expected status APPROVED, got {approved['status']}"
    )
    assert approved["reviewed_by_user_id"] == LEAGUE_OPERATIONS_ID, (
        f"Expected reviewed_by_user_id {LEAGUE_OPERATIONS_ID}, "
        f"got {approved['reviewed_by_user_id']}"
    )
    assert fixtures.read_production(api, production["id"])["status"] == "SURVEYED", (
        "an approval drives the production PLANNED to SURVEYED"
    )


def test_crew_member_cannot_read_a_production_but_can_read_its_own_call(
    api, us_headers
):
    """The read surface is not uniform: a UnionSteward with no operational authority
    reads the production, a CrewMember cannot, and the crew-call read is open to both.

    PRD: "Once both headers are present, the role string must be one of the five declared roles *and* must appear in the target endpoint's authorized-role list; otherwise the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "A newly opened production sits at `PLANNED`."
    Design: Corner/rbac/crew_member_cannot_read_a_production_but_can_read_its_own_calls
    """
    production = fixtures.new_production(api)
    member = fixtures.new_crew_member(api)
    call = fixtures.offer_call(api, production["id"], member["id"])
    crew_headers = make_crew_member_headers(member["id"])

    seen = validate_success(api.get_production(production["id"], us_headers))
    assert seen["status"] == "PLANNED", (
        f"Expected the steward to read status PLANNED, got {seen['status']}"
    )

    validate_error(
        api.get_production(production["id"], crew_headers), "ERR_UNAUTHORIZED"
    )

    own = validate_success(api.get_crew_call(call["id"], crew_headers))
    assert own["id"] == call["id"], (
        f"Expected the member to read back call {call['id']}, got {own['id']}"
    )
    assert own["crew_member_id"] == member["id"], (
        f"Expected crew_member_id {member['id']}, got {own['crew_member_id']}"
    )
