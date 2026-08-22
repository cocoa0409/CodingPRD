"""Complaint intake, triage, adjudication and the two conduct scores."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_complaint, assert_standing_matches_conduct_score,
    create_complaint_payload, triage_payload, adjudicate_payload,
    reinstate_payload,
    set_clock, create_zone, create_pitch, create_performer, run_epoch_advance,
    setup_active_permit, setup_district_pitch_and_active_permit,
    book_session, open_draw, enter_draw,
    file_complaint, triage_complaint, adjudicate_complaint,
    uphold_new_complaint,
    read_permit, read_booking, read_performer, read_complaint,
    read_draw, read_entry,
    make_officer_headers, make_performer_headers, make_resident_headers,
    OFFICER_ALPHA, OFFICER_BETA, OFFICER_GAMMA,
)
from test_helpers.api_client import api_client


STANDARD_PITCH = dict(code="RP-01", tier="STANDARD", noise_cap_db=82,
                      amplification_allowed=True, max_session_minutes=120,
                      daily_session_cap=3, premium_slots_per_draw=1)
PREMIUM_PITCH = dict(code="RP-P1", tier="PREMIUM", noise_cap_db=84,
                     amplification_allowed=True, max_session_minutes=90,
                     daily_session_cap=2, premium_slots_per_draw=1)


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade /
#          complaint_uphold_cascades_to_standing_suspension_booking_and_entry
# ---------------------------------------------------------------------------

def _performer_one_major_from_barred():
    ctx = setup_district_pitch_and_active_permit(pitch_overrides=STANDARD_PITCH)
    ctx["premium_pitch"] = create_pitch(ctx["zone"]["id"], **PREMIUM_PITCH)
    permit_id, performer_id = ctx["permit"]["id"], ctx["performer"]["id"]

    ctx["booking"] = book_session(permit_id, ctx["pitch"]["id"],
                                  "2026-08-25T10:00:00Z",
                                  "2026-08-25T11:30:00Z", performer_id)
    ctx["draw"] = open_draw(ctx["premium_pitch"]["id"], season_year=2026,
                            slot_start_at="2026-08-27T12:00:00Z",
                            slot_end_at="2026-08-27T13:30:00Z",
                            entry_deadline_at="2026-08-24T00:00:00Z")
    ctx["entry"] = enter_draw(ctx["draw"]["id"], permit_id, performer_id)

    uphold_new_complaint(permit_id, "MAJOR", "DIRECT", resident="resident-1",
                         category="CONDUCT",
                         description="Blocked the tram doors during the act")
    second = file_complaint(permit_id, "resident-2", category="OBSTRUCTION",
                            description="Crowd spilled onto the carriageway")
    triage_complaint(second["id"], "MAJOR", "DIRECT", OFFICER_ALPHA)
    ctx["complaint"] = second
    return ctx


def test_upholding_the_second_major_complaint_rescores_the_holder_to_barred(api):
    """PRD §3.8: "An upheld complaint charges points. Out of `TRIAGED` the full
    severity charge applies: 5 points for `MINOR`, 12 for `MODERATE`, 25 for
    `MAJOR`."
    PRD §3.8: "The **live** score, `conduct_score`, uses a rolling 365-day
    window: a complaint upheld 365 days ago or less charges its full
    `conduct_deduction`, and a complaint upheld more than 365 days ago charges
    nothing at all. Sum those charges and subtract from 100; if the result would
    be negative it is held at 0."
    PRD §3.8: "The `standing` is derived from the live score alone: `GOOD` when
    `conduct_score` is 80 or more, `WATCH` when it is at least 60 but below 80,
    and `BARRED` when it is below 60."

    Design: Difficulty/transitive_cascade/complaint_uphold_cascades_to_standing_suspension_booking_and_entry
    """
    ctx = _performer_one_major_from_barred()

    resp = api.adjudicate_complaint(
        ctx["complaint"]["id"],
        adjudicate_payload("UPHELD", "Traffic report accepted"),
        make_officer_headers(OFFICER_BETA))
    complaint = validate_success(resp, 200)
    assert_complaint(complaint)
    assert complaint["status"] == "UPHELD"
    assert complaint["conduct_deduction"] == 25

    performer = read_performer(ctx["performer"]["id"])
    assert performer["conduct_score"] == 50, "two MAJOR charges of 25 from 100"
    assert performer["renewal_conduct_score"] == 50
    assert performer["standing"] == "BARRED"
    assert performer["upheld_complaint_count"] == 2
    assert_standing_matches_conduct_score(performer)


def test_barred_standing_suspends_the_permit_and_unwinds_bookings_and_entries(api):
    """PRD §3.8: "When rescoring drops a performer to `BARRED`, every permit of
    that performer whose lifecycle axis is `PENDING_FEE`, `ACTIVE` or
    `RENEWAL_PENDING` and whose compliance axis is `CLEAR` or `WARNED` moves to
    `SUSPENDED`, and each such suspension runs the same cascade a noise
    suspension does — `suspended_at` stamped, future `RESERVED` and `RELOCATED`
    sessions cancelled into `CANCELLED_BY_SUSPENSION` with their minutes
    credited back, and `SUBMITTED` lottery entries forfeited."
    PRD §3.7: "The draw's `entry_count` is deliberately **not** decremented — a
    forfeited entry still counts as an entry for the purpose of the no-entries
    check — but a forfeited entry is not `SUBMITTED` and so is filtered out of
    the candidate set."

    Design: Difficulty/transitive_cascade/complaint_uphold_cascades_to_standing_suspension_booking_and_entry
    """
    ctx = _performer_one_major_from_barred()
    assert read_permit(ctx["permit"]["id"])["season_minutes_used"] == 90

    adjudicate_complaint(ctx["complaint"]["id"], "UPHELD", OFFICER_BETA,
                         "Traffic report accepted")

    permit = read_permit(ctx["permit"]["id"])
    assert permit["compliance_status"] == "SUSPENDED"
    assert permit["lifecycle_status"] == "ACTIVE", \
        "the enforcement cascade never touches the lifecycle axis"
    assert permit["season_minutes_used"] == 0, \
        "the cancelled session credits its 90 minutes back"

    assert read_booking(ctx["booking"]["id"])["status"] == "CANCELLED_BY_SUSPENSION"
    assert read_entry(ctx["entry"]["id"])["status"] == "FORFEITED"

    draw = read_draw(ctx["draw"]["id"])
    assert draw["entry_count"] == 1, "a forfeited entry still counts as an entry"
    assert draw["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc /
#          conduct_rolling_365_vs_career_weighted_divergence_on_one_history
# ---------------------------------------------------------------------------

def _two_complaint_history_across_two_seasons():
    set_clock("2025-02-01T00:00:00Z")
    zone = create_zone()
    ctx = setup_active_permit(
        zone["id"], act_type="STREET_THEATRE", season_year=2025,
        performer_overrides={"legal_name": "Cy Bramble", "stage_name": "Cy B",
                             "email": "cy@example.org"})
    permit_id = ctx["permit"]["id"]

    set_clock("2025-03-01T12:00:00Z")
    ctx["old_complaint"] = uphold_new_complaint(
        permit_id, "MAJOR", "DIRECT", resident="resident-1", category="CONDUCT",
        description="Aggressive solicitation outside the market hall")

    set_clock("2026-07-01T12:00:00Z")
    ctx["recent_complaint"] = uphold_new_complaint(
        permit_id, "MODERATE", "DIRECT", resident="resident-2", category="NOISE",
        description="Amplified backing track at midday")

    set_clock("2026-08-01T00:00:00Z")
    return ctx


def test_rolling_window_drops_an_offence_upheld_more_than_a_year_ago(api):
    """PRD §3.8: "The **live** score, `conduct_score`, uses a rolling 365-day
    window: a complaint upheld 365 days ago or less charges its full
    `conduct_deduction`, and a complaint upheld more than 365 days ago charges
    nothing at all. Sum those charges and subtract from 100; if the result would
    be negative it is held at 0."
    PRD §3.8: "Each upheld complaint has an age in whole days, computed as the
    difference between the current clock and that complaint's `upheld_at`
    divided by 86400 seconds and rounded down to a whole number of days."

    Design: Difficulty/dual_variant_calc/conduct_rolling_365_vs_career_weighted_divergence_on_one_history
    """
    ctx = _two_complaint_history_across_two_seasons()
    run_epoch_advance()

    assert read_complaint(ctx["old_complaint"]["id"])["conduct_deduction"] == 25
    assert read_complaint(ctx["recent_complaint"]["id"])["conduct_deduction"] == 12

    performer = read_performer(ctx["performer"]["id"])
    assert performer["conduct_score"] == 88, (
        "the 2025 MAJOR has aged out of the rolling window, leaving only the "
        f"MODERATE charge of 12, got {performer['conduct_score']}")
    assert performer["standing"] == "GOOD"
    assert performer["upheld_complaint_count"] == 2


def test_career_weighted_score_still_charges_half_the_aged_out_offence(api):
    """PRD §3.8: "The **renewal** score, `renewal_conduct_score`, is computed in
    the same pass over the same complaints but never forgets: a complaint upheld
    365 days ago or less charges its full deduction exactly as before, while a
    complaint older than that still charges half its deduction, rounded half up.
    Sum those charges, subtract from 100, and hold the result at 0 if it would be
    negative."
    PRD §3.9: "Step three expires permits. A permit whose lifecycle axis is
    `ACTIVE` or `RENEWAL_PENDING` expires once the clock is strictly past the end
    of its season, which is `23:59:59Z` on 31 December of its `season_year`; at
    exactly that instant the permit is still live."

    Design: Difficulty/dual_variant_calc/conduct_rolling_365_vs_career_weighted_divergence_on_one_history
    """
    ctx = _two_complaint_history_across_two_seasons()
    run_epoch_advance()

    performer = read_performer(ctx["performer"]["id"])
    assert performer["renewal_conduct_score"] == 75, (
        "the aged-out MAJOR still charges round_half_up(25/2) = 13 alongside "
        f"the 12-point MODERATE, got {performer['renewal_conduct_score']}")
    assert performer["conduct_score"] == 88, \
        "the same history reads differently on the two variants"
    assert read_permit(ctx["permit"]["id"])["lifecycle_status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Queue B: intake, the fork and the join
# ---------------------------------------------------------------------------

def test_complaint_naming_another_permits_session_is_refused(api):
    """PRD §3.8: "When a session is named it must belong to the same permit as
    the complaint, otherwise the intake is refused with
    `ERR_BOOKING_PERMIT_MISMATCH`."

    Design: Corner/entities/corner_complaint_booking_must_belong_to_the_same_permit
    """
    ctx = setup_district_pitch_and_active_permit(pitch_overrides=STANDARD_PITCH)
    other = setup_active_permit(
        ctx["zone"]["id"],
        performer_overrides={"legal_name": "Eli Marsh", "stage_name": "Eli M",
                             "email": "eli@example.org"})
    foreign_booking = book_session(other["permit"]["id"], ctx["pitch"]["id"],
                                   "2026-08-25T14:00:00Z",
                                   "2026-08-25T15:00:00Z",
                                   other["performer"]["id"])

    resp = api.create_complaint(
        create_complaint_payload(ctx["permit"]["id"], category="NOISE",
                                 description="Wrong permit named",
                                 booking_id=foreign_booking["id"]),
        make_resident_headers("resident-1"))
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_BOOKING_PERMIT_MISMATCH)

    _, meta = validate_paginated(api.list_complaints(
        make_officer_headers(), params={"permit_id": ctx["permit"]["id"]}))
    assert meta["total_count"] == 0


def test_mediation_branch_halves_the_conduct_deduction(api):
    """PRD §3.8: "A `route` of `DIRECT` sends it straight to adjudication and
    moves it `OPEN → TRIAGED`; a `route` of `MEDIATION` moves it `OPEN →
    MEDIATION` instead, and the two branches diverge numerically at the join."
    PRD §3.8: "Out of `MEDIATION` the same figure is halved and rounded half up,
    so `MINOR` charges 3, `MODERATE` charges 6 and `MAJOR` charges 13."
    PRD §3.8: "The `standing` is derived from the live score alone: `GOOD` when
    `conduct_score` is 80 or more, `WATCH` when it is at least 60 but below 80,
    and `BARRED` when it is below 60."

    Design: Corner/state_machines/corner_mediation_branch_halves_the_conduct_deduction
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    complaint = file_complaint(ctx["permit"]["id"], "resident-1",
                               category="OBSTRUCTION",
                               description="Crowd on the kerb")
    triage_complaint(complaint["id"], "MAJOR", "MEDIATION", OFFICER_ALPHA)

    resolved = adjudicate_complaint(complaint["id"], "UPHELD", OFFICER_BETA,
                                    "Mediated undertaking accepted")
    assert resolved["status"] == "UPHELD"
    assert resolved["route"] == "MEDIATION"
    assert resolved["conduct_deduction"] == 13, (
        "a MAJOR upheld through mediation charges round_half_up(25/2) = 13, got "
        f"{resolved['conduct_deduction']}")

    performer = read_performer(ctx["performer"]["id"])
    assert performer["conduct_score"] == 87
    assert performer["renewal_conduct_score"] == 87
    assert performer["standing"] == "GOOD"
    assert read_permit(ctx["permit"]["id"])["compliance_status"] == "CLEAR"


def test_conduct_score_is_held_at_zero_rather_than_going_negative(api):
    """PRD §3.8: "The **live** score, `conduct_score`, uses a rolling 365-day
    window: a complaint upheld 365 days ago or less charges its full
    `conduct_deduction`, and a complaint upheld more than 365 days ago charges
    nothing at all. Sum those charges and subtract from 100; if the result would
    be negative it is held at 0."
    PRD §3.8: "Whichever branch it came from, upholding writes the charge into
    `conduct_deduction`, stamps `upheld_at` from the clock, records
    `adjudicated_by_user_id`, and increases the performer's
    `upheld_complaint_count` by one."

    Design: Corner/calculations/corner_conduct_score_is_floored_at_zero
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    permit_id = ctx["permit"]["id"]
    for index, category in enumerate(
            ["CONDUCT", "CONDUCT", "OBSTRUCTION", "NOISE"], start=1):
        uphold_new_complaint(permit_id, "MAJOR", "DIRECT",
                             resident="resident-1", category=category,
                             description=f"Incident {index}")

    performer = read_performer(ctx["performer"]["id"])
    assert performer["conduct_score"] == 0, (
        "four MAJOR charges total 100 points and the score is held at 0, got "
        f"{performer['conduct_score']}")
    assert performer["renewal_conduct_score"] == 0
    assert performer["standing"] == "BARRED"
    assert performer["upheld_complaint_count"] == 4
    assert read_permit(permit_id)["compliance_status"] == "SUSPENDED"


def test_reinstatement_is_refused_while_the_holder_is_barred(api):
    """PRD §3.8: "Reinstatement is admissible from `WARNED → CLEAR` and from
    `SUSPENDED → CLEAR`, and is refused with `ERR_PERFORMER_BARRED` while the
    holder's `standing` is still `BARRED`."
    PRD §3.8: "Recovery is never automatic. Regaining `GOOD` or `WATCH` standing
    does not lift a suspension by itself; only an officer's reinstatement does,
    and it takes an optional `note`."

    Design: Corner/errors/corner_error_performer_barred_blocks_reinstatement
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    permit_id = ctx["permit"]["id"]
    uphold_new_complaint(permit_id, "MAJOR", "DIRECT", resident="resident-1",
                         category="CONDUCT",
                         description="Abusive to passers-by")
    uphold_new_complaint(permit_id, "MAJOR", "DIRECT", resident="resident-2",
                         category="CONDUCT",
                         description="Repeat abusive incident")

    performer = read_performer(ctx["performer"]["id"])
    assert performer["conduct_score"] == 50
    assert performer["standing"] == "BARRED"

    resp = api.reinstate_permit(permit_id, reinstate_payload("Appeal lodged"),
                                make_officer_headers(OFFICER_ALPHA))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PERFORMER_BARRED)

    permit = read_permit(permit_id)
    assert permit["compliance_status"] == "SUSPENDED"
    assert permit["noise_violation_count"] == 0


def test_triaging_an_already_dismissed_complaint_is_refused(api):
    """PRD §3.8: "Triaging a complaint that is already `UPHELD` or `DISMISSED` is
    refused with `ERR_COMPLAINT_ALREADY_RESOLVED`."
    PRD §3.8: "A dismissal from either branch — `TRIAGED → DISMISSED` or
    `MEDIATION → DISMISSED` — leaves `conduct_deduction` at 0, triggers no
    rescoring at all, records `adjudicated_by_user_id` and increments the
    complaint's `version`."
    PRD §2.6: "7. The complaint being triaged or adjudicated is not already
    resolved, otherwise `ERR_COMPLAINT_ALREADY_RESOLVED`. This domain gate
    deliberately precedes the generic state check below, so acting on a resolved
    complaint reports `ERR_COMPLAINT_ALREADY_RESOLVED` rather than
    `ERR_INVALID_STATE`."

    Design: Corner/errors/corner_error_complaint_already_resolved_blocks_retriage
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    complaint = file_complaint(ctx["permit"]["id"], "resident-1",
                               category="NOISE",
                               description="Neighbour dispute")
    triage_complaint(complaint["id"], "MINOR", "DIRECT", OFFICER_ALPHA)
    adjudicate_complaint(complaint["id"], "DISMISSED", OFFICER_BETA)

    resp = api.triage_complaint(complaint["id"],
                                triage_payload("MAJOR", "DIRECT"),
                                make_officer_headers(OFFICER_GAMMA))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_ALREADY_RESOLVED)

    reread = read_complaint(complaint["id"])
    assert reread["status"] == "DISMISSED"
    assert reread["severity"] == "MINOR"
    assert reread["conduct_deduction"] == 0

    performer = read_performer(ctx["performer"]["id"])
    assert performer["conduct_score"] == 100, "a dismissal triggers no rescoring"
    assert performer["upheld_complaint_count"] == 0


def test_the_triaging_officer_may_not_adjudicate_the_same_complaint(api):
    """PRD §3.8: "Adjudication closes it, and a different officer must do it: an
    attempt by the officer recorded in `triaged_by_user_id` is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.10: "Two decision points in this program require two different human
    beings, and in both cases the comparison is between `X-User-ID` values of
    officers, not between roles."
    PRD §3.8: "An upheld complaint charges points. Out of `TRIAGED` the full
    severity charge applies: 5 points for `MINOR`, 12 for `MODERATE`, 25 for
    `MAJOR`."

    Design: Corner/roles/corner_triaging_officer_cannot_adjudicate_the_same_complaint
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    complaint = file_complaint(ctx["permit"]["id"], "resident-1",
                               category="NOISE",
                               description="Too loud after eight")
    triage_complaint(complaint["id"], "MODERATE", "DIRECT", OFFICER_ALPHA)

    same_officer = api.adjudicate_complaint(
        complaint["id"], adjudicate_payload("UPHELD"),
        make_officer_headers(OFFICER_ALPHA))
    assert same_officer.status_code == 403, \
        f"Expected 403, got {same_officer.status_code}"
    validate_error(same_officer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    mid = read_complaint(complaint["id"])
    assert mid["status"] == "TRIAGED"
    assert mid["conduct_deduction"] == 0

    other_officer = api.adjudicate_complaint(
        complaint["id"], adjudicate_payload("UPHELD"),
        make_officer_headers(OFFICER_BETA))
    resolved = validate_success(other_officer, 200)
    assert resolved["status"] == "UPHELD"
    assert resolved["adjudicated_by_user_id"] == OFFICER_BETA
    assert resolved["conduct_deduction"] == 12
    assert read_performer(ctx["performer"]["id"])["conduct_score"] == 88
