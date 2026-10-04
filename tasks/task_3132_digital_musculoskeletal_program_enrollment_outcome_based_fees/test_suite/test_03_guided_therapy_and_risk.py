"""The guided-therapy weeks: sessions, adherence, attrition risk and outreach.

Covers session booking and completion credit, the weekly session cut, the
adherence inclusion set and its boundaries, the dropout-risk score with its
four weighted terms and its ceiling, the outreach cadence window and the
spine red-flag escalation boundary.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    CLINICAL_OPS,
    ENROLLMENT_OPS,
    OUTREACH_SERVICE,
    advance_week,
    book_outreach,
    book_session,
    complete_session,
    create_outreach_payload,
    create_session_payload,
    get_success_data,
    make_member_headers,
    set_clock,
    set_week,
    setup_scenario,
    validate_error,
    validate_success,
)


def _activate_one(member_specs=None, **scenario_kwargs):
    """One client, one member, one ACTIVE enrollment, plus the standard clinicians.

    Activation happens while the clock still reads its 2026-09-01 default, so the
    enrollment's week anchor is week_index 0; a test that exercises week-1
    behaviour calls ``set_week(1)`` first (or ``run_weeks``, which carries the
    clock itself).
    """
    return setup_scenario(member_specs=member_specs, activate=True,
                          add_clinicians=True, **scenario_kwargs)


def _run_weeks(client_id, count):
    for _ in range(count):
        advance_week(client_id)


# ══════════════════════════════════════════════════════════════════
# Session booking and completion
# ══════════════════════════════════════════════════════════════════

def test_completing_a_session_grants_the_full_prescription(api, clinical_ops_headers,
                                                           enrollment_ops_headers):
    """PRD §3.4: "`session_status` becomes `COMPLETED`, `completed_reps` is set to
    the session's `planned_reps` and `completed_minutes` to its `planned_minutes`
    — the member is credited with the full prescription regardless of what
    `completed_denominator_units` reports."
    PRD §3.4: "`adherence_numerator` is set to the smaller of 1 and the sum of
    `completed_denominator_units` plus one additional unit when `pain_score_after`
    is less than or equal to `pain_score_before`".

    Design: Corner/state_machines/dropped_enrollment_is_terminal_for_every_further_transition
    """
    scenario = _activate_one()
    set_week(1)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]

    session = book_session(enrollment_id, 1, "2026-09-08T09:00:00Z",
                           planned_reps=15, planned_minutes=20)
    assert session["session_status"] == "SCHEDULED"
    assert session["completed_reps"] == 0
    assert session["completed_minutes"] == 0
    assert session["scheduled_send_at"] is not None

    completed = complete_session(session["id"], member_id,
                                 completed_denominator_units=0.5, pain_score_after=6.5)

    assert completed["session_status"] == "COMPLETED"
    assert completed["completed_reps"] == 15, "the full prescription is credited"
    assert completed["completed_minutes"] == 20
    assert completed["pain_score_before"] == pytest.approx(6.5, abs=1e-9), (
        "snapshotted from the member's own recorded baseline"
    )
    assert completed["adherence_numerator"] == pytest.approx(1.0, abs=1e-9), (
        "0.5 plus the bonus unit for a non-worsening session, capped at 1"
    )
    assert completed["adherence_denominator"] == pytest.approx(1.0, abs=1e-9)


def test_restricted_session_doubles_the_adherence_denominator(api, clinical_ops_headers,
                                                              enrollment_ops_headers):
    """PRD §3.2: "`adherence_denominator` is 1, doubled to 2 when `track_restricted`
    is true, so a completion achieved under a surgery-avoidance restriction is
    credited on a doubled denominator and therefore earns half the adherence a
    normal completion earns."

    Design: Corner/calculations/adherence_rate_with_no_scored_sessions_is_zero_not_null
    """
    scenario = _activate_one()
    set_week(1)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]

    session = book_session(enrollment_id, 1, "2026-09-08T09:00:00Z", track_restricted=True)
    completed = complete_session(session["id"], member_id, pain_score_after=6.0)

    assert completed["track_restricted"] is True
    assert completed["adherence_denominator"] == pytest.approx(2.0, abs=1e-9), (
        "a restricted session is credited on a doubled denominator"
    )
    assert completed["adherence_numerator"] == pytest.approx(1.0, abs=1e-9)


def test_completing_a_missed_session_is_refused(api, clinical_ops_headers):
    """PRD §3.4: "Attempting to complete a session that has already been marked
    `MISSED` is refused with `ERR_INVALID_STATE`; a missed session can never be
    completed retroactively and no credit of any kind is granted."

    Design: Corner/errors/error_session_week_closed_on_late_completion
    """
    scenario = _activate_one()
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    client_id = scenario["client_id"]

    session = book_session(enrollment_id, 1, "2026-09-08T09:00:00Z")
    advance_week(client_id)  # the sweep moves the week-1 session to MISSED

    lapsed = get_success_data(api.get_session(session["id"], ENROLLMENT_OPS))
    assert lapsed["session_status"] == "MISSED"
    assert lapsed["adherence_numerator"] == pytest.approx(0.0, abs=1e-9)

    refused = api.complete_session(
        session["id"], {"completed_denominator_units": 1, "pain_score_after": 5.0},
        make_member_headers(member_id))
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["adherence_rate"] == pytest.approx(0.0, abs=1e-9), "no credit was granted"


def test_completing_a_session_outside_its_booked_week_is_refused(api, clinical_ops_headers):
    """PRD §3.4: "requires `session_week` to equal the `week_index` of the current
    logical clock instant — a scheduled session completed outside the week it was
    booked into is refused with `ERR_SESSION_WEEK_CLOSED`."
    PRD §2.4: "Clock advancement on its own does not move any week-scoped state".

    Design: Corner/errors/error_session_week_closed_on_late_completion
    """
    scenario = _activate_one()
    set_week(1)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]

    session = book_session(enrollment_id, 1, "2026-09-08T09:00:00Z")

    # Move the logical clock into week 2 without running the sweep, so the session
    # is still SCHEDULED but its week is no longer the week the clock sits in.
    validate_success(api.set_current_utc("2026-09-14T00:00:00Z", CLINICAL_OPS))

    still_scheduled = get_success_data(api.get_session(session["id"], ENROLLMENT_OPS))
    assert still_scheduled["session_status"] == "SCHEDULED", (
        "setting the clock alone moves no week-scoped state"
    )

    refused = api.complete_session(
        session["id"], {"completed_denominator_units": 1, "pain_score_after": 5.0},
        make_member_headers(member_id))
    validate_error(refused, ApiErrorId.ERR_SESSION_WEEK_CLOSED, expected_status=409)


def test_pain_score_outside_the_declared_range_is_refused(api, clinical_ops_headers):
    """PRD §3.6: "A `Member` records a measurement against an enrollment with the
    `measurement_week` it covers, a `pain_score` between 0 and 10 inclusive, and a
    `function_score` between 0 and 100 inclusive; either score outside its range is
    refused with `ERR_VITALS_OUT_OF_RANGE`."

    Design: Corner/entities/enrollment_pain_score_above_ten_is_refused
    """
    scenario = _activate_one()
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]

    refused = api.create_measurement({
        "enrollment_id": enrollment_id,
        "measurement_week": 2,
        "pain_score": 10.5,
        "function_score": 120.0,
    }, make_member_headers(member_id))
    validate_error(refused, ApiErrorId.ERR_VITALS_OUT_OF_RANGE, expected_status=422)

    rows = get_success_data(api.list_measurements(
        ENROLLMENT_OPS, {"enrollment_id": enrollment_id}))
    assert rows == [], "neither out-of-range score was stored"


# ══════════════════════════════════════════════════════════════════
# The adherence inclusion set
# ══════════════════════════════════════════════════════════════════

def test_adherence_rate_with_no_scored_sessions_is_zero_not_null(api, clinical_ops_headers):
    """PRD §3.2: "When the inclusion set is empty the rate is exactly 0.0 — not
    null, and not an error."
    PRD §3.2: "The half-open upper bound is absolute — sessions booked into the
    week the clock currently sits in never enter, whether they are `COMPLETED` or
    `MISSED`".

    Design: Corner/calculations/adherence_rate_with_no_scored_sessions_is_zero_not_null
    """
    scenario = _activate_one()
    set_week(1)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]

    session = book_session(enrollment_id, 1, "2026-09-08T09:00:00Z")
    complete_session(session["id"], member_id, pain_score_after=6.5)

    # The clock still sits in week 1, so the week-1 session is excluded by the
    # half-open bound and the inclusion set is empty.
    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))

    assert enrollment["adherence_rate"] == pytest.approx(0.0, abs=1e-9), (
        "the empty inclusion set reads 0.0 rather than null"
    )
    assert enrollment["adherence_rate"] is not None
    assert enrollment["weeks_active"] == 1
    assert enrollment["adherence_scored_through_week"] == 1
    assert enrollment["projected_engagement_milestone"] == 0, (
        "0.0 is below the track's 0.70 minimum"
    )


def test_a_completed_session_enters_the_rate_once_its_week_is_scored(api, clinical_ops_headers):
    """PRD §3.2: "the inclusion set is every session whose `session_week` is at or
    after `enrolled_week` and strictly before the current `week_index`."
    PRD §3.2: "`adherence_rate` is the sum of the numerator over the inclusion set
    divided by the sum of the denominator over the same set, rounded half up to
    two decimal places."

    Design: Corner/cross_cutting_layers/derived_adherence_and_risk_reconcile_after_a_second_week
    """
    scenario = _activate_one()
    set_week(1)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    client_id = scenario["client_id"]

    session = book_session(enrollment_id, 1, "2026-09-08T09:00:00Z")
    complete_session(session["id"], member_id, pain_score_after=6.5)

    advance_week(client_id)  # the clock now sits in week 2, so week 1 is scored

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["adherence_rate"] == pytest.approx(1.0, abs=1e-9), (
        "one completed session over one denominator unit"
    )
    assert enrollment["adherence_scored_through_week"] == 2
    assert enrollment["weeks_active"] == 2
    assert enrollment["dropout_risk_as_of_week"] == 2


def test_derived_fields_carry_their_own_as_of_stamps(api, clinical_ops_headers):
    """PRD §3.2: "`adherence_scored_through_week` records the current `week_index`
    as of the computation".
    PRD §3.2: "`dropout_risk_as_of_week` records the latest `week_index` whose
    session history entered the score."
    PRD §3.2: "`weeks_active` measures the enrollment, not the member".

    Design: Corner/cross_cutting_layers/derived_adherence_and_risk_reconcile_after_a_second_week
    """
    scenario = _activate_one()
    set_week(1)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    client_id = scenario["client_id"]

    first = book_session(enrollment_id, 1, "2026-09-08T09:00:00Z")
    complete_session(first["id"], member_id, pain_score_after=6.5)
    advance_week(client_id)  # week 1 scored; the clock now sits in week 2

    set_week(2)
    second = book_session(enrollment_id, 2, "2026-09-15T09:00:00Z")
    advance_week(client_id)
    advance_week(client_id)

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["adherence_scored_through_week"] == 4, (
        "the stamp records the week the clock now sits in"
    )
    assert enrollment["dropout_risk_as_of_week"] == 4
    assert enrollment["weeks_active"] == 4
    assert enrollment["adherence_rate"] == pytest.approx(0.5, abs=1e-9), (
        "the inclusion set is every session in [enrolled_week, current week): the "
        "completed week-1 session earns its numerator unit and the week-2 booking "
        "that lapsed to MISSED still carries its own denominator unit, so the rate "
        "is 1 / 2"
    )


# ══════════════════════════════════════════════════════════════════
# The inclusive engagement boundary
# ══════════════════════════════════════════════════════════════════

def _week_session_instant(week: int) -> str:
    """A midnight instant inside the lattice week ``week`` (week 1 == 2026-09-08)."""
    from datetime import datetime, timedelta, timezone

    anchor = datetime(2026, 9, 8, 0, 0, 0, tzinfo=timezone.utc)
    return (anchor + timedelta(days=7 * (week - 1))).strftime("%Y-%m-%dT%H:%M:%SZ")


def _week_session_date(week: int) -> str:
    """A daytime instant inside the lattice week ``week``."""
    return _week_session_instant(week).replace("T00:", "T09:")


def _build_restricted_ratio(client_id, enrollment_id, member_id, restricted_weeks,
                            normal_weeks, pain_after=6.5):
    """Book one session per listed week, completing each, and sweep past them all.

    Sessions in ``restricted_weeks`` are booked under a surgery-avoidance
    restriction, so each is credited on a doubled denominator. The resulting
    adherence ratio is (number of sessions completed) / (restricted + 2*restricted).
    """
    week = 1
    for _ in range(restricted_weeks):
        set_clock(_week_session_instant(week))
        session = book_session(enrollment_id, week, _week_session_date(week),
                               track_restricted=True)
        complete_session(session["id"], member_id, pain_score_after=pain_after)
        advance_week(client_id)
        week += 1
    for _ in range(normal_weeks):
        set_clock(_week_session_instant(week))
        session = book_session(enrollment_id, week, _week_session_date(week))
        complete_session(session["id"], member_id, pain_score_after=pain_after)
        advance_week(client_id)
        week += 1


def test_adherence_exactly_on_the_min_rate_counts_as_engaged(api, clinical_ops_headers):
    """PRD §3.7: "the enrollment's `adherence_rate` is at least the
    `min_adherence_rate` of the care track the enrollment is assigned to".
    PRD §3.7: "The comparison is inclusive on both counts, so a member landing
    exactly on the track's `min_adherence_rate` is inside the group and earns the
    milestone."

    Design: Difficulty/boundary_precision_check/adherence_exactly_on_min_rate_counts_as_engaged
    """
    scenario = _activate_one(
        acute_overrides={"expected_sessions_per_week": 1, "min_adherence_rate": 0.70})
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    client_id = scenario["client_id"]

    # Three restricted completions (numerator 3, denominator 6) plus four normal
    # completions (numerator 4, denominator 4) give exactly 7 / 10 == 0.70.
    _build_restricted_ratio(client_id, enrollment_id, member_id,
                            restricted_weeks=3, normal_weeks=4)

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["adherence_rate"] == pytest.approx(0.70, abs=1e-9), (
        "seven completed sessions over ten denominator units"
    )
    assert enrollment["weeks_active"] == 8
    assert enrollment["projected_engagement_milestone"] == 1, (
        "0.70 >= the track's 0.70 minimum, so the boundary is inside the group"
    )


def test_a_rate_a_shade_below_the_min_rate_sits_outside_the_group(api, clinical_ops_headers):
    """PRD §3.7: "A member whose adherence sits a hundredth of a point below the
    track's rate is outside it."
    PRD §3.7: "An implementation that computes the billed milestone component with
    the strict comparison will under-bill by exactly those members who land on the
    boundary".

    Design: Difficulty/boundary_precision_check/adherence_exactly_on_min_rate_counts_as_engaged
    """
    scenario = _activate_one(
        acute_overrides={"expected_sessions_per_week": 1, "min_adherence_rate": 0.70})
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    client_id = scenario["client_id"]

    # Three restricted completions (3 / 6) plus three normal completions (3 / 3)
    # give 6 / 9 == 0.6667, which rounds to 0.67 and sits below the boundary.
    _build_restricted_ratio(client_id, enrollment_id, member_id,
                            restricted_weeks=3, normal_weeks=3)

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["adherence_rate"] == pytest.approx(0.67, abs=5e-3)
    assert enrollment["projected_engagement_milestone"] == 0, (
        "0.67 is below the 0.70 minimum, so the comparison is inclusive and not strict"
    )


# ══════════════════════════════════════════════════════════════════
# Attrition risk
# ══════════════════════════════════════════════════════════════════

def test_a_session_completion_does_not_move_the_risk_score(api, clinical_ops_headers):
    """PRD §3.2: "A completion never recomputes `dropout_risk_score`. This is
    deliberate: the risk model is driven by misses and by undelivered outreach,
    and a member's own act of completing a session must not talk the model down."
    PRD §3.2: "`dropout_risk_score` is a deterministic integer between 0 and 100".

    Design: Corner/calculations/risk_score_caps_at_one_hundred_across_both_drivers
    """
    scenario = _activate_one()
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    client_id = scenario["client_id"]

    advance_week(client_id)
    session = book_session(enrollment_id, 1, "2026-09-08T09:00:00Z")
    complete_session(session["id"], member_id, pain_score_after=6.5)

    after_completion = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert after_completion["dropout_risk_score"] == 0, (
        "a member-sourced completion never moves the member-sourced risk score"
    )

    advance_week(client_id)
    scored = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert scored["dropout_risk_score"] == 0, "a completed session earns no missed-week points"
    assert scored["dropout_risk_as_of_week"] == 2


def test_risk_score_accumulates_missed_weeks_and_low_adherence(api, clinical_ops_headers):
    """PRD §3.2: "The first term is twelve points for each week in the longest run
    of consecutive week indices ending at the week immediately before the current
    one in which every scheduled session carries `MISSED`."
    PRD §3.2: "The third term is forty points, added once, when the enrollment's
    `adherence_rate` is strictly below 0.35."

    Design: Difficulty/boundary_precision_check/red_flag_weight_strictly_above_threshold_escalates
    """
    scenario = _activate_one()
    enrollment_id = scenario["enrollment_id"]
    client_id = scenario["client_id"]

    advance_week(client_id)
    book_session(enrollment_id, 1, "2026-09-08T08:00:00Z")
    advance_week(client_id)
    book_session(enrollment_id, 2, "2026-09-15T08:00:00Z")
    advance_week(client_id)

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["dropout_risk_score"] == 64, (
        "two consecutive missed weeks at 12 points each, plus 40 for sub-0.35 adherence"
    )
    assert enrollment["dropout_risk_as_of_week"] == 3


def test_risk_score_caps_at_one_hundred_across_both_drivers(api, clinical_ops_headers):
    """PRD §3.2: "The four terms are summed and the total is capped at 100, so the
    score saturates rather than exceeding the ceiling."
    PRD §3.2: "The second term is fifteen points for each outreach contact of this
    enrollment that was booked into week 1 through week 4 inclusive and that ended
    `FAILED`".
    PRD §3.2: "The fourth term is twenty points, added once, when `weeks_active` is
    at least 4 and `adherence_rate` is strictly below 0.50."

    Design: Corner/calculations/risk_score_caps_at_one_hundred_across_both_drivers
    """
    scenario = _activate_one()
    enrollment_id = scenario["enrollment_id"]
    client_id = scenario["client_id"]

    advance_week(client_id)
    book_session(enrollment_id, 1, "2026-09-08T08:00:00Z")
    book_outreach(enrollment_id, 1, channel="PUSH")
    book_outreach(enrollment_id, 1, channel="SMS")
    advance_week(client_id)

    book_session(enrollment_id, 2, "2026-09-15T08:00:00Z")
    advance_week(client_id)
    book_session(enrollment_id, 3, "2026-09-22T08:00:00Z")
    advance_week(client_id)
    book_session(enrollment_id, 4, "2026-09-29T08:00:00Z")
    advance_week(client_id)

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["dropout_risk_score"] == 100, (
        "the raw sum is 4*12 + 2*15 + 40 + 20 == 138, recorded as the declared ceiling"
    )
    assert enrollment["dropout_risk_as_of_week"] == 5
    assert enrollment["coach_escalation_required"] is True

    outreach = get_success_data(api.list_outreach(
        ENROLLMENT_OPS, {"enrollment_id": enrollment_id}))
    assert len(outreach) == 2
    assert all(contact["outreach_status"] == "FAILED" for contact in outreach)


# ══════════════════════════════════════════════════════════════════
# Outreach cadence
# ══════════════════════════════════════════════════════════════════

def test_outreach_into_a_passed_week_is_refused(api, clinical_ops_headers):
    """PRD §3.4: "A contact may not be queued into a week the clock has already
    passed; such a request is refused with `ERR_OUTREACH_WEEK_LAPSED`."
    PRD §3.4: "The window is weeks 1 through 4 inclusive: a `contact_week` of 1, 2,
    3 or 4 is inside it, and week 5 or beyond is outside it, refused with
    `ERR_OUTREACH_WINDOW_CLOSED`."

    Design: Corner/errors/error_outreach_week_lapsed_on_backdated_queue
    """
    scenario = _activate_one()
    enrollment_id = scenario["enrollment_id"]
    client_id = scenario["client_id"]

    _run_weeks(client_id, 3)  # the clock now sits in week 3

    lapsed = api.create_outreach(
        create_outreach_payload(enrollment_id, contact_week=1, channel="PHONE"),
        OUTREACH_SERVICE)
    validate_error(lapsed, ApiErrorId.ERR_OUTREACH_WEEK_LAPSED, expected_status=409)

    outside = api.create_outreach(
        create_outreach_payload(enrollment_id, contact_week=5, channel="PHONE"),
        OUTREACH_SERVICE)
    validate_error(outside, ApiErrorId.ERR_OUTREACH_WINDOW_CLOSED, expected_status=409)

    accepted = api.create_outreach(
        create_outreach_payload(enrollment_id, contact_week=3, channel="PHONE"),
        OUTREACH_SERVICE)
    assert accepted.status_code == 201, "the window is still open for the current week"

    contacts = get_success_data(api.list_outreach(
        ENROLLMENT_OPS, {"enrollment_id": enrollment_id}))
    assert len(contacts) == 1


def test_a_member_sourced_delivery_does_not_move_the_risk_score(api, clinical_ops_headers):
    """PRD §3.4: "Delivery, like session completion, does not recompute
    `dropout_risk_score`: a member-sourced delivery never moves the member-sourced
    risk score."
    PRD §3.4: "Queuing a contact does not recompute the enrollment's risk score;
    the queue alone is not evidence of engagement failure."

    Design: Corner/calculations/risk_score_caps_at_one_hundred_across_both_drivers
    """
    scenario = _activate_one()
    enrollment_id = scenario["enrollment_id"]
    client_id = scenario["client_id"]

    advance_week(client_id)
    book_session(enrollment_id, 1, "2026-09-08T08:00:00Z")
    advance_week(client_id)
    book_session(enrollment_id, 2, "2026-09-15T08:00:00Z")
    advance_week(client_id)

    baseline = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    score_before = baseline["dropout_risk_score"]
    assert score_before > 0, "two lapsed weeks have already accrued risk"

    contact = book_outreach(enrollment_id, 3, channel="PHONE")
    queued = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert queued["dropout_risk_score"] == score_before, "the queue alone moved nothing"

    delivered = validate_success(api.deliver_outreach(contact["id"], OUTREACH_SERVICE))
    assert delivered["outreach_status"] == "DELIVERED"
    assert delivered["contact_occurred_at"] is not None

    after_delivery = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert after_delivery["dropout_risk_score"] == score_before, (
        "a member-sourced delivery never moves the member-sourced risk score"
    )


def test_redelivering_an_outreach_contact_is_refused(api, clinical_ops_headers):
    """PRD §3.4: "Re-delivering an already `DELIVERED` contact is refused with
    `ERR_INVALID_STATE`."

    Design: Corner/errors/error_outreach_week_lapsed_on_backdated_queue
    """
    scenario = _activate_one()
    enrollment_id = scenario["enrollment_id"]
    client_id = scenario["client_id"]

    advance_week(client_id)
    contact = book_outreach(enrollment_id, 1, channel="PUSH")
    validate_success(api.deliver_outreach(contact["id"], OUTREACH_SERVICE))

    refused = api.deliver_outreach(contact["id"], OUTREACH_SERVICE)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    unchanged = get_success_data(api.get_outreach(contact["id"], ENROLLMENT_OPS))
    assert unchanged["outreach_status"] == "DELIVERED"


# ══════════════════════════════════════════════════════════════════
# Spine red flags
# ══════════════════════════════════════════════════════════════════

def test_red_flag_weight_is_the_sum_of_the_multipliers_minus_one(api, clinical_ops_headers):
    """PRD §3.2: "`red_flag_weight` is computed on a member as the sum, over each
    entry in `red_flag_multipliers`, of that multiplier minus 1.0, stored rounded
    half up to two decimal places."
    PRD §3.1: "A new member row is `PENDING_ELIGIBILITY` and carries no eligibility
    basis yet".

    Design: Corner/entities/member_red_flag_weight_is_computed_and_client_input_is_ignored
    """
    scenario = setup_scenario(
        member_specs=[{
            "external_member_ref": "HW-0006", "full_name": "Oda Sommer",
            "date_of_birth": "1974-04-19T00:00:00Z", "musculo_condition_code": "LOW_BACK",
            "baseline_pain_score": 7.0, "baseline_function_score": 47.0,
            "red_flag_multipliers": [1.25, 1.25],
        }],
        add_tracks=False, screen=False, assign=False, add_clinicians=False,
    )
    member_id = scenario["members"][0]["id"]

    fetched = validate_success(api.get_member(member_id, ENROLLMENT_OPS))

    assert fetched["red_flag_weight"] == pytest.approx(0.50, abs=1e-9), (
        "the server's own sum of the two 1.25 multipliers"
    )
    assert fetched["member_status"] == "PENDING_ELIGIBILITY"
    assert fetched["eligibility_basis"] is None, "the basis is not yet assigned"


def test_red_flag_weight_strictly_above_threshold_escalates(api, clinical_ops_headers):
    """PRD §3.2: "The members included are those of the client whose
    `member_status` is `ELIGIBLE` or `ENROLLED` and whose
    `musculo_condition_code` is `LOW_BACK` or `NECK`."
    PRD §3.2: "compares the resulting weight against 0.30 using a strictly-greater
    test, and escalates nothing at exactly 0.30".

    Design: Difficulty/boundary_precision_check/red_flag_weight_strictly_above_threshold_escalates
    """
    scenario = setup_scenario(
        member_specs=[
            {"external_member_ref": "KS-0009", "full_name": "Nadia Petrenko",
             "date_of_birth": "1977-07-07T00:00:00Z", "musculo_condition_code": "NECK",
             "baseline_pain_score": 6.0, "baseline_function_score": 55.0,
             "red_flag_multipliers": [1.30]},
            {"external_member_ref": "KS-0010", "full_name": "Rurik Aliyev",
             "date_of_birth": "1971-01-11T00:00:00Z", "musculo_condition_code": "LOW_BACK",
             "baseline_pain_score": 7.0, "baseline_function_score": 45.0,
             "red_flag_multipliers": [1.30, 1.30]},
        ],
        assign=False, add_clinicians=False,
    )
    client_id = scenario["client_id"]
    boundary_member_id = scenario["members"][0]["id"]
    above_member_id = scenario["members"][1]["id"]

    advance_week(client_id)

    boundary = get_success_data(api.get_member(boundary_member_id, ENROLLMENT_OPS))
    assert boundary["red_flag_weight"] == pytest.approx(0.30, abs=1e-9), (
        "one 1.30 multiplier sums to exactly the threshold"
    )
    assert boundary["coach_escalated"] is False, (
        "the comparison is strictly greater, so the exact boundary sits outside"
    )

    above = get_success_data(api.get_member(above_member_id, ENROLLMENT_OPS))
    assert above["red_flag_weight"] == pytest.approx(0.60, abs=1e-9)
    assert above["coach_escalated"] is True, "0.60 > 0.30"