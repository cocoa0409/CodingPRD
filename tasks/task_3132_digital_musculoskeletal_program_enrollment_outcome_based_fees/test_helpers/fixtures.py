"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its precondition from scratch through declared API endpoints
only — the implementation never seeds data, and the runner restarts the server
before each individual test, so nothing may be assumed to exist on entry.

Setup calls use ``get_success_data()`` (lenient) so a broken precondition surfaces
as a clear "Setup step failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT, TEST_DEFAULTS
from .factories import (
    approve_transition_payload,
    conduct_review_payload,
    create_appointment_payload,
    create_claim_line_payload,
    create_client_payload,
    create_clinician_payload,
    create_clinical_review_payload,
    create_eligibility_file_payload,
    create_enrollment_payload,
    create_measurement_payload,
    create_member_payload,
    create_outreach_payload,
    create_program_track_payload,
    create_session_payload,
    complete_session_payload,
)
from .test_users import TEST_USERS, make_clinician_headers, make_member_headers

ENROLLMENT_OPS = TEST_USERS["enrollment_ops_headers"]
CLINICAL_OPS = TEST_USERS["clinical_ops_headers"]
BILLING_OPS = TEST_USERS["billing_ops_headers"]
ELIGIBILITY_SERVICE = TEST_USERS["eligibility_service_headers"]
OUTREACH_SERVICE = TEST_USERS["outreach_service_headers"]
REVIEW_SERVICE = TEST_USERS["clinical_review_service_headers"]
# Readable alias for tests that name the role in full.
CLINICAL_REVIEW_SERVICE = REVIEW_SERVICE


# ─── Small primitives ─────────────────────────────────

# The logical clock is server-side; every write goes through ``set_clock``, so a
# local mirror lets ``advance_week`` carry it forward without a read endpoint.
_CLOCK = [CLOCK_DEFAULT]


def set_clock(instant: str = CLOCK_DEFAULT):
    result = get_success_data(api_client.set_current_utc(instant, CLINICAL_OPS))
    _CLOCK[0] = result.get("current_utc", instant)
    return result


def setup_client(**overrides) -> dict:
    """Create one client account and return it."""
    return get_success_data(api_client.create_client(
        create_client_payload(**overrides), CLINICAL_OPS))


def create_track(track_code: str, base_fee_per_member_cents: int, **overrides) -> dict:
    return get_success_data(api_client.create_program_track(
        create_program_track_payload(
            track_code=track_code,
            base_fee_per_member_cents=base_fee_per_member_cents,
            **overrides,
        ),
        CLINICAL_OPS,
    ))


def setup_tracks(acute_fee: int = 9000, chronic_fee: int = 12000,
                 acute_overrides=None, **common_overrides) -> dict:
    """Create an ACUTE and a CHRONIC track. Returns {"ACUTE": {...}, "CHRONIC": {...}}."""
    tracks = {}
    tracks["ACUTE"] = create_track("ACUTE", acute_fee, **(acute_overrides or {}))
    tracks["CHRONIC"] = create_track("CHRONIC", chronic_fee, **common_overrides)
    return tracks


def setup_roster(client_id: str, member_specs, roster_format: str = "STANDARD",
                 file_period: str = None, screen: bool = True) -> dict:
    """Ingest one roster file, add every member row, and optionally screen it.

    ``member_specs`` is a list of dicts, each an override set for
    ``create_member_payload``. Returns a dict with ``file``, ``members`` and
    ``file_version`` (the version the file holds on return).
    """
    payload = create_eligibility_file_payload(client_id, roster_format=roster_format)
    if file_period is not None:
        payload["file_period"] = file_period
    else:
        # Roster periods advance monthly, and a new file's period must be strictly
        # later than the client's greatest existing period (PRD 3.1): when the
        # client already holds the default period, this file lands on the next one.
        existing = [f["file_period"] for f in get_success_data(
            api_client.list_eligibility_files(ENROLLMENT_OPS,
                                              {"client_account_id": client_id}))]
        default = payload["file_period"]
        if existing:
            greatest = max(existing)
            if greatest >= default:
                year, month = int(greatest[:4]), int(greatest[5:])
                month += 1
                if month > 12:
                    year, month = year + 1, 1
                payload["file_period"] = "%04d-%02d" % (year, month)
    file_obj = get_success_data(api_client.create_eligibility_file(payload, ENROLLMENT_OPS))

    members = []
    for spec in member_specs:
        spec = dict(spec)
        members.append(get_success_data(api_client.create_member(
            create_member_payload(client_id, file_obj["id"], **spec), ENROLLMENT_OPS)))

    # Adding each member row advances the file's version, so the file row handed
    # back is re-read: the row returned at ingest is stale as soon as the first
    # member lands on the file.
    file_obj = get_success_data(
        api_client.get_eligibility_file(file_obj["id"], ENROLLMENT_OPS))
    file_version = file_obj["version"]
    if screen:
        screened = get_success_data(api_client.screen_eligibility_file(file_obj["id"], ENROLLMENT_OPS))
        file_obj = screened
        file_version = screened["version"]
        # Re-read the member rows so callers see their post-screening statuses.
        members = [
            get_success_data(api_client.get_member(m["id"], ENROLLMENT_OPS)) for m in members
        ]

    return {"file": file_obj, "members": members, "file_version": file_version}


def setup_clinicians(leo_capacity_slots: int = None, include_nadia: bool = False) -> dict:
    """Register the standard clinician roster.

    ``dana`` is a physical therapist, ``leo`` a physician (the approver used
    everywhere an approver must differ from the reviewing clinician). ``nadia``
    is an optional third physical therapist used by the clinician-state tests.
    """
    clinicians = {}
    clinicians["dana"] = get_success_data(api_client.create_clinician(
        create_clinician_payload(
            full_name="Dana Whitfield", discipline="PHYSICAL_THERAPIST",
            license_number="PT-88123", weekly_capacity_slots=20,
        ),
        CLINICAL_OPS,
    ))
    clinicians["leo"] = get_success_data(api_client.create_clinician(
        create_clinician_payload(
            full_name="Leo Farrow", discipline="PHYSICIAN",
            license_number="MD-44120",
            weekly_capacity_slots=(
                leo_capacity_slots if leo_capacity_slots is not None
                else TEST_DEFAULTS["PHYSICIAN_WEEKLY_CAPACITY_SLOTS"]
            ),
        ),
        CLINICAL_OPS,
    ))
    if include_nadia:
        clinicians["nadia"] = get_success_data(api_client.create_clinician(
            create_clinician_payload(
                full_name="Nadia Brenner", discipline="PHYSICAL_THERAPIST",
                license_number="PT-90211", weekly_capacity_slots=16,
            ),
            CLINICAL_OPS,
        ))
    return clinicians


def fresh_client_version(client_id: str) -> int:
    """Read a client account's current version."""
    return get_success_data(api_client.get_client(client_id, CLINICAL_OPS))["version"]


def fresh_file_version(file_id: str) -> int:
    """Read an eligibility file's current version."""
    return get_success_data(api_client.get_eligibility_file(file_id, ENROLLMENT_OPS))["version"]


def assign_tracks(file_id: str, client_id: str) -> dict:
    """Assign program tracks off a screened file, supplying the client's current version."""
    return get_success_data(api_client.assign_tracks(
        file_id,
        {"expected_client_account_version": fresh_client_version(client_id)},
        ENROLLMENT_OPS,
    ))


def enrollment_for_member(member_id: str) -> dict:
    """Return the (first) enrollment produced for a member."""
    page = get_success_data(api_client.list_enrollments(ENROLLMENT_OPS, {"member_id": member_id}))
    assert page, f"Expected at least one enrollment for member {member_id}"
    return page[0]


def seed_review(enrollment_id: str, reviewer_id: str, notes: str = "Clinical note") -> dict:
    return get_success_data(api_client.create_clinical_review(
        create_clinical_review_payload(enrollment_id, reviewer_id, review_notes=notes),
        ENROLLMENT_OPS,
    ))


def conduct_review(review_id: str, track_id: str, clinician_id: str,
                   decision: str = "APPROVE"):
    return get_success_data(api_client.conduct_clinical_review(
        review_id, conduct_review_payload(track_id, review_decision=decision),
        make_clinician_headers(clinician_id),
    ))


def approve_transition(enrollment_id: str, file_id: str, approving_clinician_id: str):
    """Approve the in-person handoff, supplying the file's current version."""
    return get_success_data(api_client.approve_transition_review(
        enrollment_id,
        approve_transition_payload(
            approving_clinician_id,
            expected_eligibility_file_version=fresh_file_version(file_id),
        ),
        make_clinician_headers(approving_clinician_id),
    ))


def activate_enrollment(enrollment_id: str, file_id: str, reviewer_clinician_id: str,
                        track_id: str, approving_clinician_id: str) -> dict:
    """Seed a review, conduct it with APPROVE, and approve the handoff to ACTIVE."""
    review = seed_review(enrollment_id, reviewer_clinician_id)
    conduct_review(review["id"], track_id, reviewer_clinician_id)
    approve_transition(enrollment_id, file_id, approving_clinician_id)
    return get_success_data(api_client.get_enrollment(enrollment_id, ENROLLMENT_OPS))


# ``setup_scenario`` declares a *parameter* named ``seed_review``, which shadows
# the module-level ``seed_review()`` helper for the whole body of that function.
# Bind the callable under a non-colliding name so the composite builder can both
# accept the flag and invoke the helper.
_seed_review_row = seed_review


def book_session(enrollment_id: str, session_week: int, session_date: str,
                 **overrides) -> dict:
    payload = create_session_payload(
        session_date=session_date, session_week=session_week, **overrides
    )
    return get_success_data(api_client.create_session(enrollment_id, payload, ENROLLMENT_OPS))


def complete_session(session_id: str, member_id: str, **overrides):
    payload = complete_session_payload(**overrides)
    return get_success_data(api_client.complete_session(
        session_id, payload, make_member_headers(member_id)))


def advance_week(client_id: str):
    """Model one week going by: carry the logical clock forward seven days and then
    run the client's weekly reconciliation, which applies that week's cut."""
    from datetime import datetime, timedelta

    current = datetime.fromisoformat(_CLOCK[0].replace("Z", "+00:00"))
    set_clock((current + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return get_success_data(api_client.run_weekly_reconciliation(client_id, CLINICAL_OPS))


def advance_weeks(client_id: str, count: int):
    results = []
    for _ in range(count):
        results.append(advance_week(client_id))
    return results


def set_week(week: int):
    """Move the logical clock into lattice week ``week`` (week 1 == 2026-09-08)."""
    from datetime import datetime, timedelta, timezone

    anchor = datetime(2026, 9, 8, 0, 0, 0, tzinfo=timezone.utc)
    return set_clock((anchor + timedelta(days=7 * (week - 1))).strftime(
        "%Y-%m-%dT%H:%M:%SZ"))


# ─── Composite scenario builder ───────────────────────

# Session dates that land in weeks 1..6 of the week lattice (PRD §2.4).
WEEK_SESSION_DATES = {
    1: "2026-09-08T09:00:00Z",
    2: "2026-09-15T09:00:00Z",
    3: "2026-09-22T09:00:00Z",
    4: "2026-09-29T09:00:00Z",
    5: "2026-10-06T09:00:00Z",
    6: "2026-10-13T09:00:00Z",
}


def setup_scenario(client_overrides=None,
                   acute_fee: int = 9000,
                   chronic_fee: int = 12000,
                   acute_overrides=None,
                   chronic_overrides=None,
                   roster_format: str = "STANDARD",
                   member_specs=None,
                   add_tracks: bool = True,
                   screen: bool = True,
                   assign: bool = True,
                   add_clinicians: bool = True,
                   leo_capacity_slots: int = None,
                   include_nadia: bool = False,
                   seed_review: bool = False,
                   activate: bool = False,
                   activate_indexes=None,
                   review_notes: str = "Clinical note"):
    """Build the standard client → tracks → roster → members → enrollments scenario.

    Returns a dict carrying every entity the caller may need:

    ``client``, ``client_id``, ``tracks``, ``file``, ``file_id``, ``file_version``,
    ``members`` (list), ``member`` (first), ``member_id``, ``enrollments`` (list, one
    per eligible member once tracks are assigned), ``enrollment`` (first),
    ``enrollment_id``, ``clinicians``, ``dana``, ``leo``, ``review``, ``care_transition``.
    """
    set_clock(CLOCK_DEFAULT)

    client = setup_client(**(client_overrides or {}))
    scenario = {
        "client": client,
        "client_id": client["id"],
        "tracks": {},
        "members": [],
        "enrollments": [],
        "clinicians": {},
        "review": None,
        "care_transition": None,
    }

    if add_tracks:
        scenario["tracks"] = setup_tracks(
            acute_fee=acute_fee, chronic_fee=chronic_fee,
            acute_overrides=acute_overrides, **(chronic_overrides or {}))
        scenario["acute_track"] = scenario["tracks"]["ACUTE"]
        scenario["chronic_track"] = scenario["tracks"]["CHRONIC"]

    specs = member_specs if member_specs is not None else [
        {"external_member_ref": "HW-0001", "full_name": "Ilse Marchetti",
         "date_of_birth": "1980-05-05T00:00:00Z",
         "musculo_condition_code": "KNEE_OA", "baseline_pain_score": 6.5,
         "baseline_function_score": 53.0}
    ]
    if screen or assign or member_specs is not None:
        roster = setup_roster(client["id"], specs, roster_format=roster_format,
                              screen=screen)
        scenario["file"] = roster["file"]
        scenario["file_id"] = roster["file"]["id"]
        scenario["file_version"] = roster["file_version"]
        scenario["members"] = roster["members"]
        if roster["members"]:
            scenario["member"] = roster["members"][0]
            scenario["member_id"] = roster["members"][0]["id"]

    if assign:
        assign_tracks(scenario["file_id"], client["id"])
        scenario["file"] = get_success_data(
            api_client.get_eligibility_file(scenario["file_id"], ENROLLMENT_OPS))
        scenario["file_version"] = scenario["file"]["version"]
        enrollments = []
        for member in scenario["members"]:
            page = get_success_data(api_client.list_enrollments(
                ENROLLMENT_OPS, {"member_id": member["id"]}))
            if page:
                enrollments.append(page[0])
        scenario["enrollments"] = enrollments
        if enrollments:
            scenario["enrollment"] = enrollments[0]
            scenario["enrollment_id"] = enrollments[0]["id"]

    if add_clinicians:
        scenario["clinicians"] = setup_clinicians(
            leo_capacity_slots=leo_capacity_slots, include_nadia=include_nadia)
        scenario["dana"] = scenario["clinicians"]["dana"]
        scenario["leo"] = scenario["clinicians"]["leo"]
        scenario["dana_id"] = scenario["clinicians"]["dana"]["id"]
        scenario["leo_id"] = scenario["clinicians"]["leo"]["id"]
        if "nadia" in scenario["clinicians"]:
            scenario["nadia_id"] = scenario["clinicians"]["nadia"]["id"]

    if seed_review and scenario["enrollments"]:
        scenario["review"] = _seed_review_row(
            scenario["enrollment_id"], scenario["dana_id"], notes=review_notes)

    if activate and scenario["enrollments"] and add_tracks:
        indexes = activate_indexes if activate_indexes is not None else [0]
        activated = []
        for idx in indexes:
            enrollment = scenario["enrollments"][idx]
            member = scenario["members"][idx]
            review = _seed_review_row(enrollment["id"], scenario["dana_id"], notes=review_notes)
            conduct_review(review["id"], scenario["acute_track"]["id"], scenario["dana_id"])
            approve_transition(enrollment["id"], scenario["file_id"], scenario["leo_id"])
            refreshed = get_success_data(
                api_client.get_enrollment(enrollment["id"], ENROLLMENT_OPS))
            activated.append(refreshed)
        scenario["enrollments"] = activated
        scenario["enrollment"] = activated[0]
        scenario["enrollment_id"] = activated[0]["id"]

    return scenario


def setup_active_enrollment(member_specs=None, client_overrides=None,
                            acute_fee: int = 9000, **scenario_kwargs):
    """Shorthand for the common case: one ACTIVE enrollment plus clinicians."""
    return setup_scenario(
        client_overrides=client_overrides,
        acute_fee=acute_fee,
        member_specs=member_specs,
        activate=True,
        **scenario_kwargs,
    )


def build_engagement(enrollment_id: str, member_id: str, client_id: str,
                     weeks, sessions_per_week: int = 1,
                     complete=True, track_restricted: bool = False,
                     pain_after=TEST_DEFAULTS["PAIN_SCORE_AFTER"]):
    """Book (and optionally complete) sessions across the given weeks.

    ``weeks`` is a list of week indices. Sessions are booked into each week of
    the lattice; the weekly sweep is not run here — the caller drives the clock.
    Returns the list of session dicts.
    """
    sessions = []
    for week in weeks:
        per_week = []
        for slot in range(sessions_per_week):
            date = WEEK_SESSION_DATES[week]
            if slot:
                date = date.replace("T09:", f"T{9 + slot:02d}:")
            session = book_session(
                enrollment_id, week, date, track_restricted=track_restricted)
            per_week.append(session)
        if complete:
            for session in per_week:
                complete_session(session["id"], member_id, pain_score_after=pain_after)
        sessions.extend(per_week)
    return sessions


def setup_dropout_evidence(client_id: str, enrollment_id: str, member_id: str,
                           missed_weeks=3, start_week: int = 1):
    """Book sessions into `missed_weeks` consecutive weeks and let the sweep mark them MISSED.

    The clock is advanced past each booked week (via the weekly sweep) so every
    booked session lapses into MISSED, producing the consecutive-missed evidence
    the dropout rule requires.
    """
    for offset in range(missed_weeks):
        week = start_week + offset
        book_session(enrollment_id, week, WEEK_SESSION_DATES[week])
        advance_week(client_id)
    return get_success_data(api_client.get_enrollment(enrollment_id, ENROLLMENT_OPS))


def setup_missed_then_review(client_id, enrollment_id, member_id, passed_week, current_week):
    """Book a session into ``passed_week``, sweep it past, then prime the review queue.

    Used by the clinician-capacity scenario, which cancels consults and then
    deactivates a clinician on a clean timeline.
    """
    book_session(enrollment_id, passed_week, WEEK_SESSION_DATES[passed_week])
    advance_week(client_id)
    return get_success_data(api_client.get_enrollment(enrollment_id, ENROLLMENT_OPS))


def setup_measurable_enrollment(client_id: str, enrollment_id: str, file_id: str,
                                clinician_id: str, approving_clinician_id: str,
                                track_id: str, measurement_week: int = 4,
                                pain_score: float = 5.0, function_score: float = 65.0):
    """Record one outcome measurement on an already-ACTIVE enrollment."""
    return get_success_data(api_client.create_measurement(
        create_measurement_payload(
            enrollment_id, measurement_week=measurement_week,
            pain_score=pain_score, function_score=function_score,
        ),
        make_member_headers(_member_id_of(enrollment_id)),
    ))


def _member_id_of(enrollment_id: str) -> str:
    """Resolve the member that owns an enrollment."""
    return get_success_data(
        api_client.get_enrollment(enrollment_id, ENROLLMENT_OPS))["member_id"]


def record_measurement(enrollment_id: str, member_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_measurement(
        create_measurement_payload(enrollment_id, **overrides),
        make_member_headers(member_id),
    ))


def record_claim_line(enrollment_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_claim_line(
        create_claim_line_payload(enrollment_id, **overrides), ENROLLMENT_OPS))


def book_outreach(enrollment_id: str, contact_week: int, channel: str = "PUSH", **overrides):
    return get_success_data(api_client.create_outreach(
        create_outreach_payload(
            enrollment_id, contact_week=contact_week, channel=channel, **overrides),
        OUTREACH_SERVICE,
    ))


def book_appointment(enrollment_id: str, clinician_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_appointment(
        create_appointment_payload(enrollment_id, clinician_id, **overrides),
        ENROLLMENT_OPS,
    ))


def open_handoff(enrollment_id: str, approving_clinician_id: str) -> dict:
    """Open a pending in-person handoff against an already-ACTIVE enrollment."""
    return get_success_data(api_client.create_care_transition(
        {"enrollment_id": enrollment_id, "approving_clinician_id": approving_clinician_id},
        make_clinician_headers(approving_clinician_id),
    ))


def first_care_transition(enrollment_id: str):
    page = get_success_data(api_client.list_care_transitions(
        CLINICAL_OPS, {"enrollment_id": enrollment_id}))
    assert page, f"Expected a care transition for enrollment {enrollment_id}"
    return page[0]