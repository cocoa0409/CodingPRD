"""Composite setup helpers.

Each test starts against an empty database, so every precondition here is built
from scratch through PRD-declared endpoints only. Setup calls use the lenient
`get_success_data` so a broken precondition reports as a setup failure rather
than as a confusing assertion failure.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, TEST_DEFAULTS, THRESHOLDS
from .factories import (
    admission_payload,
    aftercare_contact_payload,
    clock_payload,
    decision_payload,
    discharge_payload,
    education_enrollment_payload,
    emergency_shelter_payload,
    extend_payload,
    governance_proposal_payload,
    governance_vote_payload,
    home_assessment_payload,
    life_skills_completion_payload,
    mediation_outcome_payload,
    mediation_session_payload,
    notification_attempt_payload,
    notification_resolve_payload,
    outreach_contact_payload,
    reunification_case_payload,
    safety_screening_payload,
    savings_entry_payload,
    screening_disposition_payload,
    tlp_exit_payload,
    tlp_placement_payload,
    transitional_living_payload,
    youth_payload,
)
from .test_users import TEST_USERS, make_youth_member_headers

ADMIN = TEST_USERS["program_admin_headers"]
ADMIN_ALT = TEST_USERS["program_admin_alt_headers"]
WORKER = TEST_USERS["outreach_worker_headers"]
WORKER_ALT = TEST_USERS["outreach_worker_alt_headers"]
CASE_MANAGER = TEST_USERS["shelter_case_manager_headers"]
CASE_MANAGER_ALT = TEST_USERS["shelter_case_manager_alt_headers"]
SPECIALIST = TEST_USERS["reunification_specialist_headers"]
SPECIALIST_ALT = TEST_USERS["reunification_specialist_alt_headers"]
COORDINATOR = TEST_USERS["tlp_coordinator_headers"]

# A youth aged 17 at the clock's start instant sits inside both the default
# emergency-shelter band (12–17) and the default transitional-living band (16–21).
DOB_AGE_17 = "2009-03-10"
DOB_AGE_14 = "2012-05-04"


# ─── Instant arithmetic ───────────────────────────────


def shift_instant(instant: str, days: int = 0, hours: int = 0, minutes: int = 0,
                  seconds: int = 0) -> str:
    """Move an ISO 8601 UTC instant by a whole offset, keeping the millisecond form."""
    base = datetime.strptime(instant.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f") \
        if "." in instant else datetime.strptime(instant.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    moved = base.replace(tzinfo=timezone.utc) + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds
    )
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


def instant(date: str, time: str = "00:00:00") -> str:
    """Build a canonical three-fractional-digit instant from date and time parts."""
    return f"{date}T{time}.000Z"


# ─── Clock and census ─────────────────────────────────


def move_clock(to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> dict:
    """Move the logical clock forward. Returns {current_utc, previous_utc}."""
    return get_success_data(
        api_client.set_clock(clock_payload(to_iso8601), headers or ADMIN)
    )


def run_census(headers: Optional[Dict[str, str]] = None) -> dict:
    """Run one census epoch against the current clock."""
    return get_success_data(api_client.run_nightly_census(headers or ADMIN))


# ─── Reads ────────────────────────────────────────────


def fetch_program(program_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_shelter_program(program_id, headers or ADMIN))


def fetch_youth(youth_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_youth(youth_id, headers or ADMIN))


def fetch_admission(admission_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_admission(admission_id, headers or ADMIN))


def fetch_case(case_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_reunification_case(case_id, headers or ADMIN))


def fetch_placement(placement_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_tlp_placement(placement_id, headers or ADMIN))


def fetch_proposal(proposal_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_governance_proposal(proposal_id, headers or ADMIN))


def notification_of_admission(admission_id: str,
                              headers: Optional[Dict[str, str]] = None) -> dict:
    """The obligation is created by cascade, so listing an admission's
    notifications is the only discovery channel for the new row."""
    body = api_client.list_guardian_notifications(admission_id, headers or ADMIN)
    rows = get_success_data(body)
    assert rows, f"Expected a guardian notification for admission {admission_id}"
    return rows[0]


def savings_entries_of(placement_id: str, headers: Optional[Dict[str, str]] = None) -> List[dict]:
    return get_success_data(
        api_client.list_savings_entries(placement_id, headers or COORDINATOR)
    )


# ─── Tier 1: single-resource primitives ───────────────


def license_emergency_shelter(**overrides) -> dict:
    """License an `EMERGENCY_SHELTER` program. Starts `OPEN` with empty counters."""
    return get_success_data(
        api_client.create_shelter_program(emergency_shelter_payload(**overrides), ADMIN)
    )


def license_transitional_living(**overrides) -> dict:
    """License a `TRANSITIONAL_LIVING` program."""
    return get_success_data(
        api_client.create_shelter_program(transitional_living_payload(**overrides), ADMIN)
    )


def intake_youth(headers: Optional[Dict[str, str]] = None, **overrides) -> dict:
    """Intake a youth through street outreach. Starts `PROSPECT` / `OPEN`."""
    return get_success_data(
        api_client.create_youth(youth_payload(**overrides), headers or WORKER)
    )


def log_outreach_contact(youth_id: str, headers: Optional[Dict[str, str]] = None,
                         **overrides) -> dict:
    """Log one street-outreach encounter against a youth."""
    return get_success_data(
        api_client.create_outreach_contact(
            youth_id, outreach_contact_payload(**overrides), headers or WORKER
        )
    )


def submit_screening(youth_id: str, indicator_codes: Optional[List[str]] = None,
                     headers: Optional[Dict[str, str]] = None) -> dict:
    """Submit a safety screening. Opens in `SUBMITTED`."""
    return get_success_data(
        api_client.create_safety_screening(
            youth_id,
            safety_screening_payload(indicator_codes=list(indicator_codes or [])),
            headers or WORKER,
        )
    )


def disposition_screening(screening_id: str, disposition: str,
                          specialized_response_code: Optional[str] = None,
                          headers: Optional[Dict[str, str]] = None) -> dict:
    """Disposition a screening as `CLEARED` or `ESCALATED`."""
    return get_success_data(
        api_client.disposition_safety_screening(
            screening_id,
            screening_disposition_payload(disposition, specialized_response_code),
            headers or ADMIN,
        )
    )


def clear_screening(youth_id: str, indicator_codes: Optional[List[str]] = None,
                    screener_headers: Optional[Dict[str, str]] = None,
                    admin_headers: Optional[Dict[str, str]] = None) -> dict:
    """Submit a screening and disposition it `CLEARED` with two different users."""
    screening = submit_screening(youth_id, indicator_codes, screener_headers)
    return disposition_screening(screening["id"], "CLEARED", None, admin_headers)


def escalate_screening(youth_id: str, indicator_codes: Optional[List[str]] = None,
                       specialized_response_code: str = "ADVOCATE_ASSIGNED",
                       screener_headers: Optional[Dict[str, str]] = None,
                       admin_headers: Optional[Dict[str, str]] = None) -> dict:
    """Submit a screening and escalate it, which freezes the youth's risk posture."""
    screening = submit_screening(youth_id, indicator_codes, screener_headers)
    return disposition_screening(
        screening["id"], "ESCALATED", specialized_response_code, admin_headers
    )


def request_admission(youth_id: str, program_id: str, planned_discharge_at: str,
                      waitlist_opt_out: Optional[bool] = None,
                      headers: Optional[Dict[str, str]] = None) -> dict:
    """Request emergency shelter admission."""
    return get_success_data(
        api_client.create_admission(
            admission_payload(youth_id, program_id, planned_discharge_at, waitlist_opt_out),
            headers or CASE_MANAGER,
        )
    )


def record_attempt(notification_id: str, attempt_channel: str = "PHONE",
                   headers: Optional[Dict[str, str]] = None) -> dict:
    """Record one parental-notification attempt."""
    return get_success_data(
        api_client.record_notification_attempt(
            notification_id, notification_attempt_payload(attempt_channel), headers or CASE_MANAGER
        )
    )


def resolve_notification(notification_id: str, outcome: str,
                         waiver_reason: Optional[str] = None,
                         headers: Optional[Dict[str, str]] = None) -> dict:
    """Resolve a parental-notification obligation."""
    return get_success_data(
        api_client.resolve_notification(
            notification_id,
            notification_resolve_payload(outcome, waiver_reason),
            headers or CASE_MANAGER,
        )
    )


# ─── Tier 2: shelter hierarchy and the activation cascade ───

DEFAULT_PLANNED_DISCHARGE = instant("2026-08-08")


def setup_program_and_youth(program_overrides: Optional[dict] = None,
                            youth_overrides: Optional[dict] = None) -> Tuple[dict, dict]:
    """One licensed emergency shelter and one freshly intaken youth."""
    program = license_emergency_shelter(**(program_overrides or {}))
    youth = intake_youth(**{"date_of_birth": DOB_AGE_14, **(youth_overrides or {})})
    return program, youth


def setup_active_admission(program_overrides: Optional[dict] = None,
                           youth_overrides: Optional[dict] = None,
                           planned_discharge_at: str = DEFAULT_PLANNED_DISCHARGE,
                           screening_indicators: Optional[List[str]] = None,
                           outreach_contacts: int = 0,
                           case_manager_headers: Optional[Dict[str, str]] = None) -> dict:
    """Program + youth + cleared screening + an admission that lands `ACTIVE`.

    Activating the admission consumes a bed and creates the parental-notification
    obligation in `PENDING`, so the youth's risk posture is `RESTRICTED`.
    Returns program, youth, screening, admission and notification.
    """
    program, youth = setup_program_and_youth(program_overrides, youth_overrides)
    for _ in range(outreach_contacts):
        log_outreach_contact(youth["id"])
    screening = clear_screening(youth["id"], screening_indicators)
    admission = request_admission(
        youth["id"], program["id"], planned_discharge_at, None, case_manager_headers
    )
    notification = notification_of_admission(admission["id"])
    return {
        "program": program,
        "youth": youth,
        "screening": screening,
        "admission": admission,
        "notification": notification,
    }


def setup_sheltered_youth_open_posture(
    program_overrides: Optional[dict] = None,
    youth_overrides: Optional[dict] = None,
    planned_discharge_at: str = DEFAULT_PLANNED_DISCHARGE,
    outreach_contacts: int = 0,
) -> dict:
    """An `ACTIVE` admission whose notification has been resolved `CONTACTED`,
    which drops the youth's risk posture back to `OPEN`."""
    setup = setup_active_admission(
        program_overrides, youth_overrides, planned_discharge_at,
        outreach_contacts=outreach_contacts,
    )
    record_attempt(setup["notification"]["id"], "PHONE")
    setup["notification"] = resolve_notification(setup["notification"]["id"], "CONTACTED")
    return setup


def setup_pending_screening_admission(program_overrides: Optional[dict] = None,
                                      youth_overrides: Optional[dict] = None,
                                      planned_discharge_at: str = DEFAULT_PLANNED_DISCHARGE) -> dict:
    """An admission that rests in `PENDING_SCREENING` because no screening stands
    `CLEARED` for the youth."""
    program, youth = setup_program_and_youth(program_overrides, youth_overrides)
    admission = request_admission(youth["id"], program["id"], planned_discharge_at)
    return {"program": program, "youth": youth, "admission": admission}


def setup_frozen_program_by_capacity(youth_overrides: Optional[dict] = None,
                                     planned_discharge_at: str = DEFAULT_PLANNED_DISCHARGE) -> dict:
    """A one-bed program whose single bed is taken, so its posture is `FROZEN`."""
    return setup_active_admission(
        program_overrides={"licensed_bed_capacity": 1},
        youth_overrides=youth_overrides,
        planned_discharge_at=planned_discharge_at,
    )


def setup_restricted_program_via_overdue(
    program_overrides: Optional[dict] = None,
    youth_overrides: Optional[dict] = None,
    planned_discharge_at: str = instant("2026-08-20"),
    overdue_clock: str = instant("2026-08-02", "01:00:00"),
) -> dict:
    """A program driven to `RESTRICTED` by exactly one overdue notification.

    The obligation falls due twenty-four hours after the admission is activated;
    moving the clock past that instant and running the census marks it `OVERDUE`,
    which raises the program's overdue count to one.
    """
    setup = setup_active_admission(
        {"licensed_bed_capacity": 4, **(program_overrides or {})},
        youth_overrides,
        planned_discharge_at,
    )
    move_clock(overdue_clock)
    setup["census"] = run_census()
    setup["program"] = fetch_program(setup["program"]["id"])
    setup["notification"] = notification_of_admission(setup["admission"]["id"])
    return setup


def setup_waitlisted_admission(waitlisted_youth_overrides: Optional[dict] = None,
                               planned_discharge_at: str = instant("2026-08-20")) -> dict:
    """A `FROZEN` one-bed program with a second youth resting on the waitlist."""
    setup = setup_frozen_program_by_capacity(planned_discharge_at=planned_discharge_at)
    waitlisted_youth = intake_youth(
        **{"date_of_birth": DOB_AGE_14, "legal_first_name": "Bo", **(waitlisted_youth_overrides or {})}
    )
    clear_screening(waitlisted_youth["id"])
    waitlisted = request_admission(
        waitlisted_youth["id"], setup["program"]["id"], planned_discharge_at
    )
    setup["waitlisted_youth"] = waitlisted_youth
    setup["waitlisted_admission"] = waitlisted
    return setup


# ─── Tier 3: reunification lifecycle shortcuts ────────


def open_case(youth_id: str, expected_youth_version: Optional[int] = None,
              household_label: Optional[str] = None,
              headers: Optional[Dict[str, str]] = None) -> dict:
    """Open a reunification case, reading the youth's live `version` when the
    caller does not pin one."""
    if expected_youth_version is None:
        expected_youth_version = fetch_youth(youth_id)["version"]
    overrides = {}
    if household_label is not None:
        overrides["guardian_household_label"] = household_label
    return get_success_data(
        api_client.create_reunification_case(
            reunification_case_payload(youth_id, expected_youth_version, **overrides),
            headers or SPECIALIST,
        )
    )


def schedule_session(case_id: str, scheduled_start_at: str, scheduled_end_at: str,
                     headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.create_mediation_session(
            case_id,
            mediation_session_payload(scheduled_start_at, scheduled_end_at),
            headers or SPECIALIST,
        )
    )


def record_session_outcome(session_id: str, outcome: str = "PROGRESS",
                           headers: Optional[Dict[str, str]] = None) -> dict:
    """Record a held session's outcome. The recorder may not later decide the
    case, so this defaults to the alternate specialist identifier."""
    return get_success_data(
        api_client.record_mediation_outcome(
            session_id, mediation_outcome_payload(outcome), headers or SPECIALIST_ALT
        )
    )


def setup_open_case(notification_state: str = "ATTEMPTED",
                    program_overrides: Optional[dict] = None,
                    youth_overrides: Optional[dict] = None,
                    planned_discharge_at: str = instant("2026-08-20")) -> dict:
    """A sheltered youth with a reunification case in `OPENED`.

    `notification_state` chooses how far the parental-notification obligation has
    been worked: `PENDING` (untouched), `ATTEMPTED` (one attempt recorded) or
    `CONTACTED` (attempted then resolved).
    """
    setup = setup_active_admission(program_overrides, youth_overrides, planned_discharge_at)
    if notification_state in ("ATTEMPTED", "CONTACTED"):
        record_attempt(setup["notification"]["id"], "PHONE")
    if notification_state == "CONTACTED":
        resolve_notification(setup["notification"]["id"], "CONTACTED")
    setup["notification"] = notification_of_admission(setup["admission"]["id"])
    setup["youth"] = fetch_youth(setup["youth"]["id"])
    setup["case"] = open_case(setup["youth"]["id"], setup["youth"]["version"])
    return setup


def setup_case_in_mediation_held(
    notification_state: str = "ATTEMPTED",
    session_window: Tuple[str, str] = (instant("2026-08-03", "14:00:00"),
                                       instant("2026-08-03", "15:00:00")),
    held_at: str = instant("2026-08-03", "15:00:00"),
    outcome: str = "PROGRESS",
    program_overrides: Optional[dict] = None,
    youth_overrides: Optional[dict] = None,
    planned_discharge_at: str = instant("2026-08-20"),
) -> dict:
    """A case that has held its first mediation round.

    Recording the outcome requires the clock to have reached the session's
    scheduled start, so the clock is moved to `held_at` first.
    """
    setup = setup_open_case(notification_state, program_overrides, youth_overrides,
                            planned_discharge_at)
    session = schedule_session(setup["case"]["id"], session_window[0], session_window[1])
    move_clock(held_at)
    setup["session"] = record_session_outcome(session["id"], outcome)
    setup["case"] = fetch_case(setup["case"]["id"])
    return setup


def setup_case_in_home_assessment(
    safety_assessment_result: str = "SAFE",
    notification_state: str = "ATTEMPTED",
    **kwargs,
) -> dict:
    """A case that has recorded its home safety assessment verdict."""
    setup = setup_case_in_mediation_held(notification_state=notification_state, **kwargs)
    setup["case"] = get_success_data(
        api_client.record_home_assessment(
            setup["case"]["id"], home_assessment_payload(safety_assessment_result), SPECIALIST
        )
    )
    return setup


def setup_approved_case(safety_assessment_result: str = "SAFE",
                        notification_state: str = "ATTEMPTED",
                        **kwargs) -> dict:
    """A case carried through to `APPROVED`, which moves the youth to
    `REUNIFIED_PENDING`, schedules the discharge and waives the notification.

    The deciding specialist differs from the one who recorded the outcome.
    """
    setup = setup_case_in_home_assessment(safety_assessment_result, notification_state, **kwargs)
    setup["case"] = get_success_data(
        api_client.decide_reunification_case(
            setup["case"]["id"], decision_payload("APPROVE"), SPECIALIST
        )
    )
    setup["youth"] = fetch_youth(setup["youth"]["id"])
    setup["admission"] = fetch_admission(setup["admission"]["id"])
    setup["notification"] = notification_of_admission(setup["admission"]["id"])
    return setup


def log_aftercare_contact(case_id: str, contact_note: Optional[str] = None,
                          headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.create_aftercare_contact(
            case_id, aftercare_contact_payload(contact_note), headers or SPECIALIST
        )
    )


# ─── Tier 4: transitional living, savings and accumulation ───


def setup_tlp_ready_youth(shelter_program_overrides: Optional[dict] = None,
                          tlp_program_overrides: Optional[dict] = None,
                          youth_overrides: Optional[dict] = None,
                          planned_discharge_at: str = instant("2026-09-30"),
                          outreach_contacts: int = 0) -> dict:
    """A sheltered youth whose risk posture is `OPEN` and whose latest screening
    stands `CLEARED`, plus a licensed transitional-living program.

    Transitional-living placement is the most heavily gated operation in the
    system, so this walks the whole ladder: cleared screening, an `ACTIVE`
    admission, one recorded notification attempt and a `CONTACTED` resolution.
    """
    setup = setup_sheltered_youth_open_posture(
        program_overrides=shelter_program_overrides,
        youth_overrides={"date_of_birth": DOB_AGE_17, **(youth_overrides or {})},
        planned_discharge_at=planned_discharge_at,
        outreach_contacts=outreach_contacts,
    )
    setup["shelter_program"] = setup["program"]
    setup["tlp_program"] = license_transitional_living(**(tlp_program_overrides or {}))
    setup["youth"] = fetch_youth(setup["youth"]["id"])
    return setup


def place_youth(youth_id: str, program_id: str,
                documented_monthly_income_cents: Optional[int] = None,
                headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.create_tlp_placement(
            tlp_placement_payload(youth_id, program_id, documented_monthly_income_cents),
            headers or COORDINATOR,
        )
    )


def setup_tlp_placement(documented_monthly_income_cents: Optional[int] = None,
                        shelter_program_overrides: Optional[dict] = None,
                        tlp_program_overrides: Optional[dict] = None,
                        youth_overrides: Optional[dict] = None,
                        outreach_contacts: int = 0) -> dict:
    """A live `PLACED` / `IN_COMPLIANCE` transitional-living placement."""
    setup = setup_tlp_ready_youth(
        shelter_program_overrides, tlp_program_overrides, youth_overrides,
        outreach_contacts=outreach_contacts,
    )
    setup["placement"] = place_youth(
        setup["youth"]["id"], setup["tlp_program"]["id"], documented_monthly_income_cents
    )
    return setup


def setup_placement_at_days_elapsed(days_elapsed: int,
                                    documented_monthly_income_cents: Optional[int] = None,
                                    tlp_program_overrides: Optional[dict] = None,
                                    **kwargs) -> dict:
    """A placement whose `days_elapsed` has been driven to an exact figure by
    moving the logical clock forward from `placed_at`."""
    setup = setup_tlp_placement(
        documented_monthly_income_cents,
        tlp_program_overrides=tlp_program_overrides,
        **kwargs,
    )
    if days_elapsed:
        move_clock(shift_instant(setup["placement"]["placed_at"], days=days_elapsed))
    setup["placement"] = fetch_placement(setup["placement"]["id"])
    return setup


def post_savings_entry(placement_id: str, entry_type: str, amount_cents: int,
                       expected_placement_version: Optional[int] = None,
                       source_note: Optional[str] = None,
                       headers: Optional[Dict[str, str]] = None) -> dict:
    """Post one savings entry, reading the placement's live `version` when the
    caller does not pin one."""
    if expected_placement_version is None:
        expected_placement_version = fetch_placement(placement_id)["version"]
    return get_success_data(
        api_client.create_savings_entry(
            placement_id,
            savings_entry_payload(entry_type, amount_cents, expected_placement_version,
                                  source_note),
            headers or COORDINATOR,
        )
    )


def setup_placement_with_deposits(deposit_amounts_cents: List[int],
                                  documented_monthly_income_cents: Optional[int] = None,
                                  tlp_program_overrides: Optional[dict] = None,
                                  **kwargs) -> dict:
    """A placement carrying a sequence of posted deposits.

    Each entry's match component is rounded to whole cents before the per-entry
    matches are summed, so the deposit sequence is posted one entry at a time.
    """
    setup = setup_tlp_placement(
        documented_monthly_income_cents, tlp_program_overrides=tlp_program_overrides, **kwargs
    )
    setup["entries"] = [
        post_savings_entry(setup["placement"]["id"], "DEPOSIT", amount)
        for amount in deposit_amounts_cents
    ]
    setup["placement"] = fetch_placement(setup["placement"]["id"])
    return setup


def credit_life_skills(placement_id: str, credit_hours: int,
                       module_code: str = "BUDGETING",
                       headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.create_life_skills_completion(
            placement_id,
            life_skills_completion_payload(credit_hours, module_code),
            headers or COORDINATOR,
        )
    )


def credit_life_skills_hours(placement_id: str, total_hours: int) -> List[dict]:
    """Credit a total number of curriculum hours, split into postings of at most
    forty hours each since a single completion is capped at forty."""
    completions = []
    remaining = total_hours
    modules = ["BUDGETING", "TENANCY", "EMPLOYMENT_READINESS", "HEALTH_LITERACY",
               "CONFLICT_RESOLUTION", "CIVIC_ENGAGEMENT"]
    index = 0
    while remaining > 0:
        chunk = min(remaining, THRESHOLDS["LIFE_SKILLS_HOURS_MAX"])
        completions.append(
            credit_life_skills(placement_id, chunk, modules[index % len(modules)])
        )
        remaining -= chunk
        index += 1
    return completions


def run_review(placement_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    """Run a savings-compliance review, which takes no request body at all."""
    return get_success_data(
        api_client.run_compliance_review(placement_id, headers or COORDINATOR)
    )


def exit_placement(placement_id: str, exit_reason: str = "YOUTH_INITIATED",
                   headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.exit_tlp_placement(
            placement_id, tlp_exit_payload(exit_reason), headers or COORDINATOR
        )
    )


# ─── Tier 5: governance, education and terminal states ───

DEFAULT_VOTING_CLOSES_AT = instant("2026-09-01")


def setup_vote_eligible_youth(program_id: str,
                              planned_discharge_at: str = instant("2026-09-30"),
                              youth_overrides: Optional[dict] = None) -> dict:
    """A youth resident at a program and eligible to vote.

    `governance_vote_eligible` is true exactly when the youth's status is
    `SHELTERED` or `TLP_ENROLLED` and `engagement_contact_count` is at least one,
    so one outreach encounter is logged before the admission is requested.
    """
    youth = intake_youth(**{"date_of_birth": DOB_AGE_14, **(youth_overrides or {})})
    log_outreach_contact(youth["id"])
    clear_screening(youth["id"])
    admission = request_admission(youth["id"], program_id, planned_discharge_at)
    notification = notification_of_admission(admission["id"])
    return {
        "youth": fetch_youth(youth["id"]),
        "admission": admission,
        "notification": notification,
    }


def open_proposal(program_id: str, voting_closes_at: str = DEFAULT_VOTING_CLOSES_AT,
                  headers: Optional[Dict[str, str]] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_governance_proposal(
            program_id, governance_proposal_payload(voting_closes_at, **overrides),
            headers or ADMIN,
        )
    )


def setup_proposal_with_electorate(electorate_size: int = 2,
                                   voting_closes_at: str = DEFAULT_VOTING_CLOSES_AT,
                                   program_overrides: Optional[dict] = None,
                                   planned_discharge_at: str = instant("2026-09-30")) -> dict:
    """A program with `electorate_size` vote-eligible resident youths and one
    proposal open for voting."""
    program = license_emergency_shelter(
        **{"licensed_bed_capacity": max(electorate_size + 1, 2), **(program_overrides or {})}
    )
    residents = []
    names = ["Ana", "Ben", "Cleo", "Dov", "Esme"]
    for index in range(electorate_size):
        residents.append(
            setup_vote_eligible_youth(
                program["id"],
                planned_discharge_at,
                {"legal_first_name": names[index % len(names)]},
            )
        )
    proposal = open_proposal(program["id"], voting_closes_at)
    return {
        "program": fetch_program(program["id"]),
        "residents": residents,
        "youths": [resident["youth"] for resident in residents],
        "proposal": proposal,
    }


def cast_vote(proposal_id: str, youth_id: str, stance: str = "SUPPORT") -> dict:
    """Cast a vote. The server takes `youth_id` from the acting header, so the
    acting youth's own id is used to build them."""
    return get_success_data(
        api_client.cast_governance_vote(
            proposal_id, governance_vote_payload(stance), make_youth_member_headers(youth_id)
        )
    )


def retract_vote(vote_id: str, youth_id: str) -> dict:
    return get_success_data(
        api_client.retract_governance_vote(vote_id, make_youth_member_headers(youth_id))
    )


def close_vote(proposal_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.close_governance_vote(proposal_id, headers or ADMIN)
    )


def enroll_in_education(youth_id: str, headers: Optional[Dict[str, str]] = None,
                        **overrides) -> dict:
    return get_success_data(
        api_client.create_education_enrollment(
            youth_id, education_enrollment_payload(**overrides), headers or CASE_MANAGER
        )
    )


def discharge(admission_id: str, exit_destination: str = "FAMILY_REUNIFIED",
              headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.discharge_admission(
            admission_id, discharge_payload(exit_destination), headers or CASE_MANAGER
        )
    )


def extend(admission_id: str, new_planned_discharge_at: str,
           headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.extend_admission(
            admission_id, extend_payload(new_planned_discharge_at), headers or CASE_MANAGER
        )
    )


def setup_discharged_admission(discharge_at: str = instant("2026-08-08", "15:00:00"),
                               exit_destination: str = "FAMILY_REUNIFIED",
                               planned_discharge_at: str = DEFAULT_PLANNED_DISCHARGE,
                               program_overrides: Optional[dict] = None,
                               youth_overrides: Optional[dict] = None) -> dict:
    """An admission carried through to `DISCHARGED` at a chosen clock instant.

    The obligation is resolved first so the runaway-report gate cannot intervene.
    """
    setup = setup_sheltered_youth_open_posture(
        program_overrides, youth_overrides, planned_discharge_at
    )
    move_clock(discharge_at)
    setup["admission"] = discharge(setup["admission"]["id"], exit_destination)
    setup["youth"] = fetch_youth(setup["youth"]["id"])
    setup["program"] = fetch_program(setup["program"]["id"])
    return setup
