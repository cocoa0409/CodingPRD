"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test starts against an empty database with the
logical clock at its default instant (PRD §2.5).

All setup calls go through ``get_success_data`` so a broken precondition
reports itself as a setup failure rather than as a misleading assertion.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CLOCK_INSTANT
from .test_users import (
    OFFICERS,
    REVIEWERS,
    TEST_USERS,
    make_coach_headers,
)

PM = TEST_USERS["program_manager_headers"]
CD = TEST_USERS["competition_director_headers"]
HSL = TEST_USERS["health_screening_lead_headers"]
MR = REVIEWERS["reviewer-1"]
MR2 = REVIEWERS["reviewer-2"]
OFFICER_1 = OFFICERS["officer-1"]
OFFICER_2 = OFFICERS["officer-2"]
OFFICER_3 = OFFICERS["officer-3"]
OFFICER_4 = OFFICERS["officer-4"]
OFFICER_5 = OFFICERS["officer-5"]
OFFICER_6 = OFFICERS["officer-6"]


# ---------------------------------------------------------------------------
# Tier 0 — primitive single-call helpers
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers: Dict[str, str] = PM) -> Dict[str, Any]:
    """PRD §2.5: sets the logical UTC clock; "every declared role may call it"."""
    return get_success_data(
        api_client.set_clock(f.set_clock_payload(to_iso8601), headers))


def reset_clock_to_default(headers: Dict[str, str] = PM) -> Dict[str, Any]:
    return set_clock(DEFAULT_CLOCK_INSTANT, headers)


def create_program(headers: Dict[str, str] = PM, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_program(f.create_program_payload(**overrides), headers))


def get_program(program_id: str, headers: Dict[str, str] = PM) -> Dict[str, Any]:
    return get_success_data(api_client.get_program(program_id, headers))


def add_volunteer(program_id: str, headers: Dict[str, str] = PM,
                  **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_volunteer(
        program_id, f.create_volunteer_payload(**overrides), headers))


def open_credential(volunteer_id: str, role_class: str = "COACH",
                    officer: Dict[str, str] = OFFICER_1) -> Dict[str, Any]:
    return get_success_data(api_client.create_credential(
        volunteer_id, f.create_credential_payload(role_class=role_class), officer))


def record_screening(credential_id: str, officer: Dict[str, str] = OFFICER_1,
                     **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.record_credential_screening(
        credential_id, f.record_screening_payload(**overrides), officer))


def record_training(credential_id: str, officer: Dict[str, str] = OFFICER_2,
                    **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.record_credential_training(
        credential_id, f.record_training_payload(**overrides), officer))


def certify_credential(credential_id: str, officer: Dict[str, str] = OFFICER_3,
                       **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.certify_credential(
        credential_id, f.certify_credential_payload(**overrides), officer))


def register_athlete(program_id: str, headers: Dict[str, str] = PM,
                     **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_athlete(
        program_id, f.create_athlete_payload(**overrides), headers))


def file_medical_form(athlete_id: str, headers: Dict[str, str] = PM,
                      **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_medical_form(
        athlete_id, f.create_medical_form_payload(**overrides), headers))


def approve_medical_form(form_id: str,
                         reviewer: Dict[str, str] = MR) -> Dict[str, Any]:
    return get_success_data(api_client.review_medical_form(
        form_id, f.review_medical_form_payload(decision="APPROVE"), reviewer))


def reject_medical_form(form_id: str, reason_code: str = "ILLEGIBLE",
                        reviewer: Dict[str, str] = MR) -> Dict[str, Any]:
    return get_success_data(api_client.review_medical_form(
        form_id,
        f.review_medical_form_payload(decision="REJECT",
                                      rejection_reason_code=reason_code),
        reviewer))


def create_season(program_id: str, headers: Dict[str, str] = CD,
                  **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_season(
        program_id, f.create_season_payload(**overrides), headers))


def open_practice(season_id: str, headers: Dict[str, str] = CD) -> Dict[str, Any]:
    return get_success_data(
        api_client.open_season_practice(season_id, {}, headers))


def schedule_session(season_id: str, coach_credential_id: str,
                     headers: Dict[str, str] = PM, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_practice_session(
        f.create_practice_session_payload(season_id, coach_credential_id,
                                          **overrides), headers))


def record_attendance(session_id: str, athlete_id: str,
                      expected_session_version: int,
                      headers: Dict[str, str] = PM, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_attendance_record(
        session_id,
        f.create_attendance_payload(athlete_id, expected_session_version,
                                    **overrides),
        headers))


def session_version(session_id: str, headers: Dict[str, str] = PM) -> int:
    return get_success_data(
        api_client.get_practice_session(session_id, headers))["version"]


def team_version(team_id: str, headers: Dict[str, str] = PM) -> int:
    return get_success_data(api_client.get_unified_team(team_id, headers))["version"]


def submit_entry(season_id: str, participant_id: str,
                 headers: Dict[str, str] = CD, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_competition_entry(
        f.create_entry_payload(season_id, participant_id, **overrides), headers))


def run_sweep(program_id: str, headers: Dict[str, str] = PM) -> Dict[str, Any]:
    return get_success_data(api_client.run_compliance_sweep(program_id, {}, headers))


def record_screening_finding(athlete_id: str, headers: Dict[str, str] = HSL,
                             **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_health_screening(
        f.create_health_screening_payload(athlete_id, **overrides), headers))


def log_followup(screening_id: str, outcome: str,
                 headers: Dict[str, str] = HSL, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.log_referral_followup(
        screening_id, f.referral_followup_payload(outcome, **overrides), headers))


def log_contribution(program_id: str, headers: Dict[str, str] = PM,
                     **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_contribution(
        program_id, f.create_contribution_payload(**overrides), headers))


# ---------------------------------------------------------------------------
# Tier 1 — state progression on a single entity
# ---------------------------------------------------------------------------
def create_credential_ready_to_certify(
        program_id: str,
        volunteer_overrides: Optional[Dict[str, Any]] = None,
        role_class: str = "COACH",
        screening_overrides: Optional[Dict[str, Any]] = None,
        training_overrides: Optional[Dict[str, Any]] = None,
        screening_officer: Dict[str, str] = OFFICER_1,
        training_officer: Dict[str, str] = OFFICER_2,
        opening_officer: Dict[str, str] = OFFICER_1,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Volunteer + credential with both branches recorded, so the credential
    rests in READY_TO_CERTIFY (PRD §3.3: "The fork joins on READY_TO_CERTIFY").

    Screening and training are recorded by different officers because PRD §2.8
    forbids one user recording both branches.
    """
    volunteer = add_volunteer(program_id, **(volunteer_overrides or {}))
    credential = open_credential(volunteer["id"], role_class=role_class,
                                 officer=opening_officer)
    record_screening(credential["id"], officer=screening_officer,
                     **(screening_overrides or {}))
    credential = record_training(credential["id"], officer=training_officer,
                                 **(training_overrides or {}))
    return volunteer, credential


def create_certified_credential(
        program_id: str,
        volunteer_overrides: Optional[Dict[str, Any]] = None,
        role_class: str = "COACH",
        screening_overrides: Optional[Dict[str, Any]] = None,
        training_overrides: Optional[Dict[str, Any]] = None,
        certify_overrides: Optional[Dict[str, Any]] = None,
        screening_officer: Dict[str, str] = OFFICER_1,
        training_officer: Dict[str, str] = OFFICER_2,
        certifying_officer: Dict[str, str] = OFFICER_3,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Walk a volunteer all the way to a CERTIFIED credential."""
    volunteer, credential = create_credential_ready_to_certify(
        program_id,
        volunteer_overrides=volunteer_overrides,
        role_class=role_class,
        screening_overrides=screening_overrides,
        training_overrides=training_overrides,
        screening_officer=screening_officer,
        training_officer=training_officer,
    )
    credential = certify_credential(credential["id"], officer=certifying_officer,
                                    **(certify_overrides or {}))
    return volunteer, credential


def create_active_athlete(
        program_id: str,
        athlete_overrides: Optional[Dict[str, Any]] = None,
        form_overrides: Optional[Dict[str, Any]] = None,
        reviewer: Dict[str, str] = MR,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Register an athlete, file a form and approve it, so registration is
    ACTIVE and the medical dimension is CLEARED or RESTRICTED (PRD §3.2)."""
    athlete = register_athlete(program_id, **(athlete_overrides or {}))
    form = file_medical_form(athlete["id"], **(form_overrides or {}))
    form = approve_medical_form(form["id"], reviewer=reviewer)
    athlete = get_success_data(api_client.get_athlete(athlete["id"], PM))
    return athlete, form


def create_practice_open_season(program_id: str, **overrides) -> Dict[str, Any]:
    """Create a season and open its practice window (PLANNING → PRACTICE_OPEN)."""
    season = create_season(program_id, **overrides)
    return open_practice(season["id"])


# ---------------------------------------------------------------------------
# Tier 2 — program-level worlds
# ---------------------------------------------------------------------------
def setup_program_with_certified_coach(
        program_overrides: Optional[Dict[str, Any]] = None,
        volunteer_overrides: Optional[Dict[str, Any]] = None,
        screening_overrides: Optional[Dict[str, Any]] = None,
        training_overrides: Optional[Dict[str, Any]] = None,
        certify_overrides: Optional[Dict[str, Any]] = None,
        clock: Optional[str] = DEFAULT_CLOCK_INSTANT,
) -> Dict[str, Any]:
    """A program whose posture is OPEN because one coach credential is
    CERTIFIED (PRD §3.3: certifying the first coach "is the moment a brand-new
    program's posture moves from FROZEN to OPEN").

    Returns ``{"program", "volunteer", "credential"}``.
    """
    if clock:
        set_clock(clock)
    program = create_program(**(program_overrides or {}))
    volunteer, credential = create_certified_credential(
        program["id"],
        volunteer_overrides=volunteer_overrides,
        screening_overrides=screening_overrides,
        training_overrides=training_overrides,
        certify_overrides=certify_overrides,
    )
    return {
        "program": get_program(program["id"]),
        "volunteer": volunteer,
        "credential": credential,
    }


def setup_practice_ready_program(
        season_overrides: Optional[Dict[str, Any]] = None,
        **world_overrides) -> Dict[str, Any]:
    """Certified-coach program plus one PRACTICE_OPEN season.

    Returns ``{"program", "volunteer", "credential", "season"}``.
    """
    world = setup_program_with_certified_coach(**world_overrides)
    world["season"] = create_practice_open_season(
        world["program"]["id"], **(season_overrides or {}))
    world["program"] = get_program(world["program"]["id"])
    return world


def setup_program_with_second_coach(world: Dict[str, Any],
                                    volunteer_overrides: Optional[Dict] = None,
                                    certify: bool = True,
                                    **kwargs) -> Dict[str, Any]:
    """Add a second coach volunteer + credential to an existing world.

    Returns ``{"volunteer", "credential"}`` for the newly added coach.
    """
    defaults = {"full_name": "Leo Marsh", "email": "leo@rb.example",
                "date_of_birth": "1985-09-09", "volunteer_class": "COACH"}
    defaults.update(volunteer_overrides or {})
    if certify:
        volunteer, credential = create_certified_credential(
            world["program"]["id"], volunteer_overrides=defaults, **kwargs)
    else:
        volunteer, credential = create_credential_ready_to_certify(
            world["program"]["id"], volunteer_overrides=defaults, **kwargs)
    return {"volunteer": volunteer, "credential": credential}


def setup_session_ready_world(
        session_overrides: Optional[Dict[str, Any]] = None,
        athlete_specs: Optional[List[Dict[str, Any]]] = None,
        season_overrides: Optional[Dict[str, Any]] = None,
        attendance_clock: Optional[str] = None,
        **world_overrides) -> Dict[str, Any]:
    """Certified coach + PRACTICE_OPEN season + one SCHEDULED session, plus any
    requested ACTIVE athletes.

    Returns ``{"program", "volunteer", "credential", "season", "session",
    "athletes", "forms"}``.  When ``attendance_clock`` is given the logical
    clock is advanced to it after the session is scheduled, so attendance may
    be filed (PRD §3.4 requires the clock to have reached
    ``scheduled_start``).
    """
    world = setup_practice_ready_program(season_overrides=season_overrides,
                                         **world_overrides)
    athletes, forms = [], []
    for spec in (athlete_specs or []):
        athlete, form = create_active_athlete(
            world["program"]["id"],
            athlete_overrides=spec.get("athlete"),
            form_overrides=spec.get("form"))
        athletes.append(athlete)
        forms.append(form)
    world["athletes"] = athletes
    world["forms"] = forms
    world["session"] = schedule_session(
        world["season"]["id"], world["credential"]["id"],
        **(session_overrides or {}))
    if attendance_clock:
        set_clock(attendance_clock)
    world["program"] = get_program(world["program"]["id"])
    return world


def coach_headers_for(world: Dict[str, Any]) -> Dict[str, str]:
    """Coach headers carrying the acting Volunteer's own id (PRD §2.1)."""
    return make_coach_headers(world["volunteer"]["id"])


# ---------------------------------------------------------------------------
# Tier 3 — competition pipeline shortcuts
# ---------------------------------------------------------------------------
def setup_entry_ready_world(
        athlete_specs: Optional[List[Dict[str, Any]]] = None,
        season_overrides: Optional[Dict[str, Any]] = None,
        **world_overrides) -> Dict[str, Any]:
    """Certified coach + PRACTICE_OPEN season whose practice minimums are zero,
    plus ACTIVE athletes, so competition entries clear the practice-minimum
    gate (PRD §3.5: "both comparisons are inclusive, so hitting a minimum
    exactly is eligible").

    Returns ``{"program", "volunteer", "credential", "season", "athletes",
    "forms"}``.
    """
    season_defaults = {"practice_minimum_sessions": 0,
                       "practice_minimum_minutes": 0}
    season_defaults.update(season_overrides or {})
    world = setup_practice_ready_program(season_overrides=season_defaults,
                                         **world_overrides)
    athletes, forms = [], []
    for spec in (athlete_specs or []):
        athlete, form = create_active_athlete(
            world["program"]["id"],
            athlete_overrides=spec.get("athlete"),
            form_overrides=spec.get("form"))
        athletes.append(athlete)
        forms.append(form)
    world["athletes"] = athletes
    world["forms"] = forms
    world["program"] = get_program(world["program"]["id"])
    return world


def submit_entries(season_id: str, entry_specs: List[Dict[str, Any]],
                   headers: Dict[str, str] = CD) -> List[Dict[str, Any]]:
    """Submit one entry per spec; each spec is a payload override dict carrying
    at least ``participant_id``."""
    entries = []
    for spec in entry_specs:
        spec = dict(spec)
        participant_id = spec.pop("participant_id")
        entries.append(submit_entry(season_id, participant_id, headers=headers,
                                    **spec))
    return entries


def setup_divisioned_season(
        athlete_specs: List[Dict[str, Any]],
        entry_specs: List[Dict[str, Any]],
        season_overrides: Optional[Dict[str, Any]] = None,
        divisioning_clock: Optional[str] = None,
        **world_overrides) -> Dict[str, Any]:
    """Entry-ready world, entries submitted, clock advanced to the season's
    registration deadline, then divisioning run (PRD §3.6 requires "the clock
    date must have reached the season's `registration_deadline`").

    ``entry_specs`` index into ``world["athletes"]`` via the ``athlete_index``
    key; every other key is a payload override.

    Returns the world plus ``{"entries", "divisions"}``.
    """
    world = setup_entry_ready_world(athlete_specs=athlete_specs,
                                    season_overrides=season_overrides,
                                    **world_overrides)
    specs = []
    for spec in entry_specs:
        spec = dict(spec)
        index = spec.pop("athlete_index")
        spec["participant_id"] = world["athletes"][index]["id"]
        specs.append(spec)
    world["entries"] = submit_entries(world["season"]["id"], specs)
    set_clock(divisioning_clock or
              (world["season"]["registration_deadline"] + "T00:00:00Z"))
    world["season"] = get_success_data(
        api_client.run_divisioning(world["season"]["id"], {}, CD))
    divisions, _meta = _paginated(
        api_client.list_divisions(CD, params={"season_id": world["season"]["id"],
                                              "limit": 100}))
    world["divisions"] = divisions
    world["entries"] = [
        get_success_data(api_client.get_competition_entry(e["id"], CD))
        for e in world["entries"]]
    world["program"] = get_program(world["program"]["id"])
    return world


def setup_entries_locked_season(*args, **kwargs) -> Dict[str, Any]:
    """A divisioned season taken through lock-entries (DIVISIONED →
    ENTRIES_LOCKED, PRD §3.6)."""
    world = setup_divisioned_season(*args, **kwargs)
    world["season"] = get_success_data(
        api_client.lock_season_entries(world["season"]["id"], {}, CD))
    world["entries"] = [
        get_success_data(api_client.get_competition_entry(e["id"], CD))
        for e in world["entries"]]
    return world


def _paginated(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    body = response.json()
    assert response.status_code == 200, f"list call failed: {response.text}"
    return body["data"], body["meta"]


def list_divisions_for_season(season_id: str,
                              headers: Dict[str, str] = CD) -> List[Dict[str, Any]]:
    data, _ = _paginated(api_client.list_divisions(
        headers, params={"season_id": season_id, "limit": 100}))
    return data


def list_entries_for_season(season_id: str,
                            headers: Dict[str, str] = CD) -> List[Dict[str, Any]]:
    data, _ = _paginated(api_client.list_competition_entries(
        headers, params={"season_id": season_id, "limit": 100}))
    return data


# ---------------------------------------------------------------------------
# Tier 4 — unified rosters
# ---------------------------------------------------------------------------
def create_certified_partner(program_id: str, full_name: str, email: str,
                             date_of_birth: str,
                             screening_officer: Dict[str, str] = OFFICER_1,
                             training_officer: Dict[str, str] = OFFICER_2,
                             certifying_officer: Dict[str, str] = OFFICER_3,
                             **kwargs) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A volunteer on the UNIFIED_PARTNER track with a CERTIFIED credential, as
    required for roster membership (PRD §3.5)."""
    return create_certified_credential(
        program_id,
        volunteer_overrides={"full_name": full_name, "email": email,
                             "date_of_birth": date_of_birth,
                             "volunteer_class": "UNIFIED_PARTNER"},
        role_class="UNIFIED_PARTNER",
        screening_officer=screening_officer,
        training_officer=training_officer,
        certifying_officer=certifying_officer,
        **kwargs)


def create_unified_team(season_id: str, headers: Dict[str, str] = CD,
                        **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_unified_team(
        season_id, f.create_unified_team_payload(**overrides), headers))


def add_team_member(team_id: str, member_type: str, member_id: str,
                    expected_team_version: int,
                    headers: Dict[str, str] = CD) -> Dict[str, Any]:
    return get_success_data(api_client.add_unified_team_member(
        team_id,
        f.add_team_member_payload(member_type, member_id, expected_team_version),
        headers))


def setup_compliant_unified_team(
        athlete_specs: List[Dict[str, Any]],
        partner_specs: List[Dict[str, Any]],
        season_overrides: Optional[Dict[str, Any]] = None,
        team_overrides: Optional[Dict[str, Any]] = None,
        **world_overrides) -> Dict[str, Any]:
    """Build a roster by appending athletes and partners alternately so the
    one-to-one repairability rule of PRD §3.5 is never breached.

    Returns the world plus ``{"team", "partners", "partner_credentials"}``.
    """
    world = setup_entry_ready_world(athlete_specs=athlete_specs,
                                   season_overrides=season_overrides,
                                   **world_overrides)
    team = create_unified_team(world["season"]["id"], **(team_overrides or {}))
    partners, partner_credentials = [], []
    for spec in partner_specs:
        volunteer, credential = create_certified_partner(
            world["program"]["id"], spec["full_name"], spec["email"],
            spec["date_of_birth"])
        partners.append(volunteer)
        partner_credentials.append(credential)
    for index in range(max(len(world["athletes"]), len(partners))):
        if index < len(world["athletes"]):
            team = add_team_member(team["id"], "ATHLETE",
                                   world["athletes"][index]["id"], team["version"])
        if index < len(partners):
            team = add_team_member(team["id"], "PARTNER", partners[index]["id"],
                                   team["version"])
    world["team"] = team
    world["partners"] = partners
    world["partner_credentials"] = partner_credentials
    return world


# ---------------------------------------------------------------------------
# Tier 5 — medical hold, expiry and support ledgers
# ---------------------------------------------------------------------------
def put_athlete_on_urgent_hold(athlete_id: str, screened_on: str,
                               **overrides) -> Dict[str, Any]:
    """Record an URGENT screening, which drops the athlete's medical dimension
    to HOLD and voids the athlete's live entries (PRD §3.8)."""
    return record_screening_finding(athlete_id, screened_on=screened_on,
                                   finding_severity="URGENT", **overrides)


def setup_contribution_world(
        contribution_specs: List[Dict[str, Any]],
        program_overrides: Optional[Dict[str, Any]] = None,
        clock: str = DEFAULT_CLOCK_INSTANT) -> Dict[str, Any]:
    """A program plus one contribution per spec, in declaration order.

    Returns ``{"program", "contributions"}``.
    """
    set_clock(clock)
    program = create_program(**(program_overrides or {}))
    contributions = [log_contribution(program["id"], **spec)
                     for spec in contribution_specs]
    return {"program": get_program(program["id"]), "contributions": contributions}
