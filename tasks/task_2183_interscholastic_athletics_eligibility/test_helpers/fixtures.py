"""Composite setup helpers.

Every helper builds its preconditions from scratch through published endpoints:
the server is relaunched against an empty database before each test, and the
logical clock is back at its startup instant, so nothing is ever carried over.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    academic_record_payload,
    create_clearance_document_payload,
    create_contest_payload,
    create_eligibility_case_payload,
    create_injury_report_payload,
    create_official_payload,
    create_school_payload,
    create_sport_season_payload,
    create_staff_credential_payload,
    create_student_payload,
    create_transport_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_director_headers,
    make_official_headers,
    make_registrar_headers,
    make_registrar_headers as _make_registrar_headers,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
MEDICAL = TEST_USERS["medical_headers"]
MEDICAL_ALT = TEST_USERS["medical_alt_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]

ALL_DOC_TYPES = ("PHYSICAL", "PARENT_CONSENT", "CONCUSSION_ACK")


# ---------------------------------------------------------------------------
# Tier 0: single-step primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Move the association's logical clock and return the clock summary."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_school(**overrides) -> dict:
    return get_success_data(
        api_client.create_school(create_school_payload(**overrides), ADMIN)
    )


def create_season(**overrides) -> dict:
    return get_success_data(
        api_client.create_sport_season(create_sport_season_payload(**overrides), ADMIN)
    )


def advance_season(season_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.advance_sport_season(season_id, {"to_status": to_status}, ADMIN)
    )


def open_season_to_regular(season_id: str) -> dict:
    """PLANNED -> PRACTICE_OPEN -> REGULAR_SEASON."""
    advance_season(season_id, "PRACTICE_OPEN")
    return advance_season(season_id, "REGULAR_SEASON")


def read_season(season_id: str) -> dict:
    return get_success_data(api_client.get_sport_season(season_id, ADMIN))


def season_version(season_id: str) -> int:
    return read_season(season_id)["version"]


def read_school(school_id: str) -> dict:
    return get_success_data(api_client.get_school(school_id, ADMIN))


def read_contest(contest_id: str) -> dict:
    return get_success_data(api_client.get_contest(contest_id, ADMIN))


def contest_version(contest_id: str) -> int:
    return read_contest(contest_id)["version"]


def read_case(case_id: str) -> dict:
    return get_success_data(api_client.get_eligibility_case(case_id, ADMIN))


def read_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, ADMIN))


def read_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_official_assignment(assignment_id, ADMIN))


def read_transport(transport_request_id: str) -> dict:
    return get_success_data(
        api_client.get_transport_request(transport_request_id, ADMIN)
    )


def read_injury(report_id: str) -> dict:
    return get_success_data(api_client.get_injury_report(report_id, ADMIN))


def create_student(school_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_student(
            create_student_payload(school_id, **overrides), make_director_headers(school_id)
        )
    )


def post_academic_record(student_id: str, school_id: str, **overrides) -> dict:
    """The Registrar of the owning school posts the grading-period record."""
    return get_success_data(
        api_client.post_academic_record(
            student_id, academic_record_payload(**overrides),
            make_registrar_headers(school_id),
        )
    )


def create_credential(school_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_staff_credential(
            create_staff_credential_payload(school_id, **overrides),
            make_director_headers(school_id),
        )
    )


def clear_credential(credential_id: str, **overrides) -> dict:
    payload = {"result": "CLEARED", "background_check_reference": "BGC-77120"}
    payload.update(overrides)
    return get_success_data(
        api_client.background_check_credential(credential_id, payload, ADMIN)
    )


def create_cleared_head_coach(school_id: str, sport: str = "FOOTBALL",
                              certification_expires_on: str = "2027-06-30") -> dict:
    """Register a head-coach credential and adjudicate it CLEARED, closing the gap."""
    credential = create_credential(
        school_id, sport=sport, role_title="HEAD_COACH",
        certification_expires_on=certification_expires_on,
    )
    return clear_credential(credential["id"])


def create_official(**overrides) -> dict:
    return get_success_data(
        api_client.create_official(create_official_payload(**overrides), ADMIN)
    )


def create_case(school_id: str, student_id: str, season_id: str) -> dict:
    return get_success_data(
        api_client.create_eligibility_case(
            create_eligibility_case_payload(student_id, season_id),
            make_director_headers(school_id),
        )
    )


def file_document(case_id: str, school_id: str, doc_type: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_clearance_document(
            case_id, create_clearance_document_payload(doc_type, **overrides),
            make_director_headers(school_id),
        )
    )


def file_all_clearance_documents(case_id: str, school_id: str,
                                 expires_on: str = "2027-07-15") -> list:
    """File one valid form of each of the three types against the case."""
    return [
        file_document(case_id, school_id, doc_type, expires_on=expires_on)
        for doc_type in ALL_DOC_TYPES
    ]


def evaluate_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.evaluate_case(case_id, headers or REVIEWER))


def activate_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.activate_case(case_id, headers or REVIEWER))


def pay_fee(case_id: str, school_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.create_fee_payment(
            case_id, {"amount_cents": amount_cents}, make_director_headers(school_id)
        )
    )


def create_contest(season_id: str, home_school_id: str, away_school_id: str,
                   starts_at: str, ends_at: str, headers=None, **overrides) -> dict:
    """Schedule a contest, reading the season's current version for the lock."""
    payload = create_contest_payload(
        season_id, home_school_id, away_school_id, starts_at, ends_at,
        season_version(season_id), **overrides,
    )
    return get_success_data(
        api_client.create_contest(payload, headers or make_director_headers(home_school_id))
    )


def offer_official(contest_id: str, official_id: str) -> dict:
    """Offer the game, reading the contest's current version for the lock."""
    payload = {
        "official_id": official_id,
        "expected_contest_version": contest_version(contest_id),
    }
    return get_success_data(api_client.offer_official(contest_id, payload, COORDINATOR))


def respond_to_offer(assignment_id: str, official_id: str, response: str = "ACCEPT") -> dict:
    return get_success_data(
        api_client.respond_to_assignment(
            assignment_id, {"response": response}, make_official_headers(official_id)
        )
    )


def confirm_contest(contest_id: str, home_school_id: str) -> dict:
    return get_success_data(
        api_client.confirm_contest(contest_id, make_director_headers(home_school_id))
    )


def forfeit_contest(contest_id: str, forfeiting_school_id: str, **overrides) -> dict:
    payload = {"forfeiting_school_id": forfeiting_school_id}
    payload.update(overrides)
    return get_success_data(api_client.forfeit_contest(contest_id, payload, ADMIN))


def create_transport(contest_id: str, school_id: str, travel_minutes: int = 45,
                     **overrides) -> dict:
    payload = create_transport_request_payload(
        contest_id, school_id, travel_minutes=travel_minutes, **overrides
    )
    return get_success_data(
        api_client.create_transport_request(payload, make_director_headers(school_id))
    )


def approve_transport(transport_request_id: str) -> dict:
    return get_success_data(
        api_client.approve_transport_request(transport_request_id, ADMIN)
    )


def cancel_transport(transport_request_id: str, school_id: str, **overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return get_success_data(
        api_client.cancel_transport_request(
            transport_request_id, payload, make_director_headers(school_id)
        )
    )


def file_injury(student_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_injury_report(
            create_injury_report_payload(student_id, **overrides), headers or MEDICAL
        )
    )


def advance_rtp_stage(report_id: str, headers=None, **overrides) -> dict:
    payload = {"symptom_recurrence": False}
    payload.update(overrides)
    return get_success_data(
        api_client.advance_injury_stage(report_id, payload, headers or MEDICAL)
    )


def clear_injury(report_id: str, disposition: str = "RETURN_TO_PLAY", headers=None,
                 **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return get_success_data(
        api_client.clear_injury_report(report_id, payload, headers or MEDICAL_ALT)
    )


# ---------------------------------------------------------------------------
# Tier 1: school + season scaffolding
# ---------------------------------------------------------------------------
def setup_two_schools_and_open_season(clock="2026-09-10T09:00:00Z",
                                      home_overrides=None, away_overrides=None,
                                      season_overrides=None, open_season=True) -> dict:
    """Two same-classification schools plus a season, optionally in REGULAR_SEASON."""
    set_clock(clock)
    home = create_school(**(home_overrides or {"name": "North High"}))
    away = create_school(**(away_overrides or {"name": "South High",
                                               "region_code": "R-SOUTH"}))
    season = create_season(**(season_overrides or {}))
    if open_season:
        open_season_to_regular(season["id"])
    return {"home": home, "away": away, "season": season}


# ---------------------------------------------------------------------------
# Tier 2: an eligibility case standing at INTAKE with everything the ladder reads
# ---------------------------------------------------------------------------
def setup_case_ready_for_evaluation(clock="2026-09-10T09:00:00Z",
                                    school_overrides=None, season_overrides=None,
                                    student_overrides=None, academic_overrides=None,
                                    doc_expires_on="2027-07-15",
                                    documents=ALL_DOC_TYPES,
                                    open_season=True) -> dict:
    """School + season + athlete with a posted academic record + an INTAKE case.

    The athlete clears the age, residency and transfer rungs by default; the
    caller controls the academic record and the clearance forms on file.
    """
    set_clock(clock)
    school = create_school(**(school_overrides or {"fee_cap_cents": 20000}))
    season = create_season(**(season_overrides or {}))
    if open_season:
        open_season_to_regular(season["id"])
    student_payload = {
        "residency_verified": True,
        "residency_verified_on": "2026-08-10",
        "free_reduced_lunch": False,
    }
    student_payload.update(student_overrides or {})
    student = create_student(school["id"], **student_payload)
    post_academic_record(student["id"], school["id"], **(academic_overrides or {}))
    case = create_case(school["id"], student["id"], season["id"])
    for doc_type in documents:
        file_document(case["id"], school["id"], doc_type, expires_on=doc_expires_on)
    return {"school": school, "season": season, "student": student, "case": case}


def setup_provisionally_eligible_case(**kwargs) -> dict:
    """As above, then run one clean evaluation so the case sits PROVISIONAL_ELIGIBLE."""
    ctx = setup_case_ready_for_evaluation(**kwargs)
    ctx["case"] = evaluate_case(ctx["case"]["id"])
    return ctx


def setup_eligible_case(coach_sport="FOOTBALL", **kwargs) -> dict:
    """A fully activated case: cleared head coach, fee paid in full, then activate."""
    ctx = setup_case_ready_for_evaluation(**kwargs)
    create_cleared_head_coach(ctx["school"]["id"], sport=coach_sport)
    ctx["case"] = evaluate_case(ctx["case"]["id"])
    outstanding = ctx["case"]["fee_outstanding_cents"]
    if outstanding > 0:
        pay_fee(ctx["case"]["id"], ctx["school"]["id"], outstanding)
    ctx["case"] = activate_case(ctx["case"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: contests walked through the staffing lifecycle
# ---------------------------------------------------------------------------
def setup_staffed_contest(clock="2026-09-10T09:00:00Z",
                          starts_at="2026-09-20T18:00:00Z",
                          ends_at="2026-09-20T20:00:00Z",
                          required_officials=1,
                          home_overrides=None, away_overrides=None,
                          season_overrides=None, contest_overrides=None,
                          confirm=False) -> dict:
    """Two schools, an open season, a contest staffed to OFFICIALS_ASSIGNED."""
    season_payload = {"required_officials": required_officials}
    season_payload.update(season_overrides or {})
    ctx = setup_two_schools_and_open_season(
        clock=clock, home_overrides=home_overrides, away_overrides=away_overrides,
        season_overrides=season_payload,
    )
    officials = [
        create_official(full_name=f"Official {n}", certification_level="LEVEL_2")
        for n in range(required_officials)
    ]
    contest = create_contest(
        ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
        starts_at, ends_at, **(contest_overrides or {}),
    )
    assignments = []
    for official in officials:
        assignment = offer_official(contest["id"], official["id"])
        assignments.append(respond_to_offer(assignment["id"], official["id"], "ACCEPT"))
    if confirm:
        contest = confirm_contest(contest["id"], ctx["home"]["id"])
    else:
        contest = read_contest(contest["id"])
    ctx.update({"contest": contest, "officials": officials, "assignments": assignments})
    return ctx


def setup_confirmed_contest(**kwargs) -> dict:
    kwargs["confirm"] = True
    return setup_staffed_contest(**kwargs)


# ---------------------------------------------------------------------------
# Tier 4: accumulation - forfeits driving the sanction ladder
# ---------------------------------------------------------------------------
def setup_school_with_forfeits(count: int, clock="2026-09-02T09:00:00Z",
                               season_overrides=None) -> dict:
    """Charge `count` forfeits to the home school on distinct contests."""
    season_payload = {"required_officials": 1, "contest_limit": 10}
    season_payload.update(season_overrides or {})
    ctx = setup_two_schools_and_open_season(
        clock=clock, season_overrides=season_payload
    )
    # Sixteen days apart so the rolling-window density check never fires.
    days = ["2026-09-05", "2026-09-21", "2026-10-07", "2026-10-23", "2026-11-08"]
    contests = []
    for index in range(count):
        contest = create_contest(
            ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
            f"{days[index]}T18:00:00Z", f"{days[index]}T20:00:00Z",
        )
        forfeit_contest(contest["id"], ctx["home"]["id"])
        contests.append(contest)
    ctx["forfeited_contests"] = contests
    ctx["next_contest_date"] = days[count]
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: closing the season out - approved trips and drawn brackets
# ---------------------------------------------------------------------------
def setup_approved_trip(travel_minutes=45, bus_count=1, confirm=False,
                        home_overrides=None, **kwargs) -> dict:
    """A staffed contest with one APPROVED trip for the home school."""
    ctx = setup_staffed_contest(
        home_overrides=home_overrides or {
            "name": "North High", "school_day_end_utc_hhmm": "17:00",
            "bus_fleet_size": 2, "max_release_minutes_per_request": 240,
        },
        confirm=confirm, **kwargs,
    )
    trip = create_transport(
        ctx["contest"]["id"], ctx["home"]["id"],
        travel_minutes=travel_minutes, bus_count=bus_count,
    )
    ctx["trip"] = approve_transport(trip["id"])
    return ctx


def setup_seeded_season(schools, contests, clock="2026-09-10T09:00:00Z",
                        season_overrides=None) -> dict:
    """Create `schools` (list of payload dicts), play out `contests`, then seed.

    Each contest entry is (home_index, away_index, starts_at, ends_at,
    forfeiting_index).  The season is advanced to REGULAR_SEASON after the
    contests are resolved, then the bracket is drawn.
    """
    set_clock(clock)
    created = [create_school(**payload) for payload in schools]
    season_payload = {"required_officials": 1, "contest_limit": 10}
    season_payload.update(season_overrides or {})
    season = create_season(**season_payload)
    made = []
    for home_i, away_i, starts_at, ends_at, forfeit_i in contests:
        contest = create_contest(
            season["id"], created[home_i]["id"], created[away_i]["id"],
            starts_at, ends_at, headers=ADMIN, travel_miles=25,
        )
        forfeit_contest(contest["id"], created[forfeit_i]["id"])
        made.append(contest)
    open_season_to_regular(season["id"])
    seeded_season = get_success_data(api_client.seed_sport_season(season["id"], ADMIN))
    seeds = get_success_data(
        api_client.list_season_playoff_seeds(season["id"], ADMIN, {"limit": 100})
    )
    return {"schools": created, "season": seeded_season, "contests": made, "seeds": seeds}


def setup_injury_at_stage(target_stage: int, report_clock="2026-09-10T09:00:00Z",
                          school_overrides=None) -> dict:
    """File a concussion report and walk the protocol up to `target_stage`.

    The first advance needs the 48-hour initial rest; every later one needs a
    further 24 hours, so the clock is moved a day at a time.
    """
    set_clock(report_clock)
    school = create_school(**(school_overrides or {}))
    student = create_student(school["id"], full_name="Pia Novak")
    report = file_injury(student["id"])
    clocks = ["2026-09-12T09:00:00Z", "2026-09-13T09:00:00Z", "2026-09-14T09:00:00Z",
              "2026-09-15T09:00:00Z", "2026-09-16T09:00:00Z"]
    for index in range(target_stage):
        set_clock(clocks[index])
        report = advance_rtp_stage(report["id"])
    return {"school": school, "student": student, "report": report}
