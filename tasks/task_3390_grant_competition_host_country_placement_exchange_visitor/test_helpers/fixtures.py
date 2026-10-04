"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so nothing
carries over). Setup calls use the lenient get_success_data() so a broken
precondition surfaces as a clear "Setup failed" error rather than a confusing
assertion failure.

Identity threading: the Applicant role is entity-backed — every
ownership-gated call uses make_applicant_headers(applicant["id"]) built from
the actual Applicant record the fixture created. Opaque operator roles use
the shared TEST_USERS constants.

Clock discipline: the logical clock starts at 2026-09-01T00:00:00Z. Fixtures
advance it through the admin clock endpoint as the pipeline requires:
  - ORIENTATION_CLOCK (2027-06-15) before visa issuance so the recorded
    orientation (2027-06-01) is not in the future;
  - the grant start_date before ACTIVATE (clock >= start_date);
  - the grant end_date before FINAL report submission / COMPLETE.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_GRANT_DURATION_MONTHS,
    DEFAULT_GRANT_END_DATE,
    DEFAULT_GRANT_START_DATE,
    ORIENTATION_CLOCK,
    ORIENTATION_COMPLETED_AT,
)
from .factories import (
    application_transition_payload,
    confirm_grant_payload,
    create_applicant_payload,
    create_application_payload,
    create_country_program_payload,
    create_cycle_payload,
    create_enrolled_applicant_payload,
    create_incident_payload,
    create_placement_round_payload,
    create_report_payload,
    create_score_payload,
    create_stay_payload,
    create_visa_sponsorship_payload,
    cycle_transition_payload,
    grant_transition_payload,
    placement_round_transition_payload,
    report_transition_payload,
    residency_transition_payload,
    resolve_incident_payload,
)
from .test_users import TEST_USERS, make_applicant_headers

_ADMIN = TEST_USERS["platform_admin_headers"]
_OFFICER = TEST_USERS["program_officer_headers"]
_HOST = TEST_USERS["host_commission_headers"]
_ANON = TEST_USERS["anonymous_headers"]

NATIONAL_REVIEWER_1 = "nr-1"
NATIONAL_REVIEWER_2 = "nr-2"
CAMPUS_REVIEWER_1 = "cr-1"
CAMPUS_REVIEWER_2 = "cr-2"


def _ok(response, step: str):
    """Lenient setup validator: accepts any 2xx and returns the data payload;
    on failure raises an AssertionError naming the setup step."""
    try:
        return get_success_data(response)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}") from exc


# ---------------------------------------------------------------------------
# Tier 0: clock + single-call primitives
# ---------------------------------------------------------------------------

def set_clock_to(iso8601: str):
    """Advance the logical clock (PlatformAdmin-only test-driving call)."""
    _ok(api_client.set_clock(iso8601, _ADMIN), f"set_clock_to({iso8601})")


def create_cycle(**overrides):
    payload = create_cycle_payload(**overrides)
    return _ok(api_client.create_cycle(payload, _ADMIN), "create_cycle")


def add_country_program(cycle: dict, **overrides):
    payload = create_country_program_payload(**overrides)
    return _ok(
        api_client.create_country_program(cycle["id"], payload, _ADMIN),
        "add_country_program",
    )


def transition_cycle(cycle: dict, action: str):
    return _ok(
        api_client.transition_cycle(cycle["id"], cycle_transition_payload(action), _ADMIN),
        f"transition_cycle({action})",
    )


def open_cycle(cycle: dict):
    return transition_cycle(cycle, "OPEN")


def close_cycle(cycle: dict):
    return transition_cycle(cycle, "CLOSE")


def begin_screening(cycle: dict):
    return transition_cycle(cycle, "BEGIN_SCREENING")


def finalize_awards(cycle: dict):
    return transition_cycle(cycle, "FINALIZE_AWARDS")


def complete_cycle(cycle: dict):
    return transition_cycle(cycle, "COMPLETE")


def register_applicant(**overrides):
    """Register an INDEPENDENT applicant by default (Anonymous lane)."""
    payload = create_applicant_payload(**overrides)
    return _ok(api_client.create_applicant(payload, _ANON), "register_applicant")


def register_enrolled_applicant(**overrides):
    """Register an ENROLLED_STUDENT applicant (home_institution_name included)."""
    payload = create_enrolled_applicant_payload(**overrides)
    return _ok(
        api_client.create_applicant(payload, _ANON), "register_enrolled_applicant",
    )


def create_draft_application(applicant: dict, cycle: dict, program: dict,
                             **overrides):
    payload = create_application_payload(
        applicant["id"], cycle["id"], program["id"], **overrides,
    )
    return _ok(
        api_client.create_application(
            payload, make_applicant_headers(applicant["id"])),
        "create_draft_application",
    )


def get_application(application: dict):
    return _ok(
        api_client.get_application(application["id"], _OFFICER), "get_application",
    )


def submit_application(application: dict, applicant: dict):
    """DRAFT -> CAMPUS_REVIEW (enrolled) or DRAFT -> NATIONAL_SCREENING
    (independent); the fork is keyed on the applicant's type."""
    return _ok(
        api_client.transition_application(
            application["id"], application_transition_payload("SUBMIT"),
            make_applicant_headers(applicant["id"])),
        "submit_application",
    )


def withdraw_application(application: dict, applicant: dict):
    return _ok(
        api_client.transition_application(
            application["id"], application_transition_payload("WITHDRAW"),
            make_applicant_headers(applicant["id"])),
        "withdraw_application",
    )


def decline_application(application: dict, applicant: dict):
    return _ok(
        api_client.transition_application(
            application["id"], application_transition_payload("DECLINE"),
            make_applicant_headers(applicant["id"])),
        "decline_application",
    )


def post_national_score(application: dict, reviewer_id: str, score=80, **overrides):
    payload = create_score_payload(
        feasibility_score=score, country_fit_score=score, language_score=score,
        **overrides,
    )
    return _ok(
        api_client.post_score(
            application["id"], payload,
            {"X-User-ID": reviewer_id, "X-User-Role": "NationalReviewer"}),
        f"post_national_score({reviewer_id})",
    )


def post_campus_score(application: dict, reviewer_id: str, score=75, **overrides):
    payload = create_score_payload(
        feasibility_score=score, country_fit_score=score, language_score=score,
        **overrides,
    )
    return _ok(
        api_client.post_score(
            application["id"], payload,
            {"X-User-ID": reviewer_id, "X-User-Role": "CampusReviewer"}),
        f"post_campus_score({reviewer_id})",
    )


def post_national_quorum_scores(application: dict, score=80, scores=None):
    """Post the two-reviewer national quorum (nr-1, nr-2 by default). Pass
    scores=(s1, s2) to control each reviewer independently (one score per
    reviewer — the pair must use distinct reviewer ids)."""
    pair = scores if scores is not None else (score, score)
    post_national_score(application, NATIONAL_REVIEWER_1, score=pair[0])
    post_national_score(application, NATIONAL_REVIEWER_2, score=pair[1])


def post_campus_quorum_scores(application: dict, score=75, scores=None):
    pair = scores if scores is not None else (score, score)
    post_campus_score(application, CAMPUS_REVIEWER_1, score=pair[0])
    post_campus_score(application, CAMPUS_REVIEWER_2, score=pair[1])


def decide_application(application: dict, outcome: str, role: str,
                       reviewer_id: str):
    """One DECIDE transition by an explicit reviewer identity."""
    return _ok(
        api_client.transition_application(
            application["id"],
            application_transition_payload("DECIDE", outcome=outcome),
            {"X-User-ID": reviewer_id, "X-User-Role": role}),
        f"decide_application({outcome})",
    )


def endorse_application(application: dict, reviewer_id: str = CAMPUS_REVIEWER_1):
    return decide_application(application, "ENDORSE", "CampusReviewer", reviewer_id)


def recommend_application(application: dict, reviewer_id: str = NATIONAL_REVIEWER_1):
    """NATIONAL_SCREENING -> HOST_REVIEW; assigns recommend_seq."""
    return decide_application(application, "RECOMMEND", "NationalReviewer", reviewer_id)


def host_decide(application: dict, outcome: str):
    """HOST_REVIEW decision: SELECT / ALTERNATE / REJECT."""
    return _ok(
        api_client.transition_application(
            application["id"],
            application_transition_payload("DECIDE", outcome=outcome),
            _HOST),
        f"host_decide({outcome})",
    )


def get_application_grant(application: dict):
    """Read back the application's single grant via its grant listing."""
    grants = _ok(
        api_client.list_application_grants(application["id"], _OFFICER),
        "list_application_grants",
    )
    if not isinstance(grants, list) or len(grants) != 1:
        raise AssertionError(
            f"Setup failed at get_application_grant: expected exactly one grant, "
            f"got {grants!r}"
        )
    return grants[0]


def get_grant(grant: dict):
    return _ok(api_client.get_grant(grant["id"], _OFFICER), "get_grant")


def open_placement_round(application: dict, expected_application_version=None,
                         **overrides):
    """Open a negotiation round (HostCommission, OCC-guarded). When the
    expected version is not supplied, the application's current version is
    fetched first so intervening version bumps never make the call stale."""
    if expected_application_version is None:
        expected_application_version = get_application(application)["version"]
    payload = create_placement_round_payload(
        expected_application_version, **overrides,
    )
    return _ok(
        api_client.create_placement_round(application["id"], payload, _HOST),
        "open_placement_round",
    )


def respond_to_round(round_: dict, action: str, applicant: dict):
    """ACCEPT or DECLINE a live offer as its owning applicant."""
    return _ok(
        api_client.transition_placement_round(
            round_["id"], placement_round_transition_payload(action),
            make_applicant_headers(applicant["id"])),
        f"respond_to_round({action})",
    )


def accept_placement_round(round_: dict, applicant: dict):
    return respond_to_round(round_, "ACCEPT", applicant)


def decline_placement_round(round_: dict, applicant: dict):
    return respond_to_round(round_, "DECLINE", applicant)


def expire_placement_round(round_: dict):
    return _ok(
        api_client.transition_placement_round(
            round_["id"], placement_round_transition_payload("EXPIRE"), _OFFICER),
        "expire_placement_round",
    )


def confirm_grant(application: dict, **overrides):
    """PROVISIONAL -> CONFIRMED with final award terms; application
    GRANT_PENDING -> AWARDED."""
    payload = confirm_grant_payload(**overrides)
    return _ok(
        api_client.confirm_grant(application["id"], payload, _OFFICER),
        "confirm_grant",
    )


def issue_visa_sponsorship(grant: dict, subject_to_home_residency: bool = True,
                           orientation_completed_at: str = ORIENTATION_COMPLETED_AT,
                           advance_clock: bool = True):
    """Issue the visa sponsorship for a CONFIRMED grant. Advances the clock
    to ORIENTATION_CLOCK first so the recorded orientation timestamp is not
    in the future. Also creates the residency ledger (PENDING when subject,
    NOT_REQUIRED otherwise)."""
    if advance_clock:
        set_clock_to(ORIENTATION_CLOCK)
    payload = create_visa_sponsorship_payload(
        subject_to_home_residency=subject_to_home_residency,
        orientation_completed_at=orientation_completed_at,
    )
    return _ok(
        api_client.create_visa_sponsorship(grant["id"], payload, _OFFICER),
        "issue_visa_sponsorship",
    )


def get_visa_ledger(visa: dict):
    ledgers = _ok(
        api_client.list_visa_residency_ledgers(visa["id"], _OFFICER),
        "list_visa_residency_ledgers",
    )
    if not isinstance(ledgers, list) or len(ledgers) != 1:
        raise AssertionError(
            f"Setup failed at get_visa_ledger: expected exactly one ledger, "
            f"got {ledgers!r}"
        )
    return ledgers[0]


def transition_grant(grant: dict, action: str, termination_reason=None):
    return _ok(
        api_client.transition_grant(
            grant["id"], grant_transition_payload(action, termination_reason),
            _OFFICER),
        f"transition_grant({action})",
    )


def activate_grant(grant: dict, at_clock: str = None):
    """CONFIRMED -> ACTIVE. Clock must be at or past start_date; defaults to
    the grant's own start_date."""
    if at_clock is None:
        at_clock = grant.get("start_date") or DEFAULT_GRANT_START_DATE
    set_clock_to(at_clock)
    return transition_grant(grant, "ACTIVATE")


def complete_grant_action(grant: dict):
    return transition_grant(grant, "COMPLETE")


def terminate_grant(grant: dict, termination_reason: str = "Early termination"):
    return transition_grant(grant, "TERMINATE", termination_reason)


def submit_report(grant: dict, applicant: dict, report_type: str = "FINAL",
                  **overrides):
    payload = create_report_payload(report_type, **overrides)
    return _ok(
        api_client.create_report(
            grant["id"], payload, make_applicant_headers(applicant["id"])),
        f"submit_report({report_type})",
    )


def accept_report(report: dict):
    return _ok(
        api_client.transition_report(
            report["id"], report_transition_payload("ACCEPT"), _OFFICER),
        "accept_report",
    )


def request_report_revision(report: dict, revision_note: str = "Needs work"):
    return _ok(
        api_client.transition_report(
            report["id"],
            report_transition_payload("REQUEST_REVISION", revision_note=revision_note),
            _OFFICER),
        "request_report_revision",
    )


def resubmit_report(report: dict, applicant: dict, content=None):
    return _ok(
        api_client.transition_report(
            report["id"],
            report_transition_payload("RESUBMIT", content=content),
            make_applicant_headers(applicant["id"])),
        "resubmit_report",
    )


def declare_incident(grant: dict, **overrides):
    payload = create_incident_payload(**overrides)
    return _ok(
        api_client.create_incident(grant["id"], payload, _OFFICER),
        "declare_incident",
    )


def resolve_incident(incident: dict, outcome: str):
    return _ok(
        api_client.resolve_incident(
            incident["id"], resolve_incident_payload(outcome), _OFFICER),
        f"resolve_incident({outcome})",
    )


def add_residency_stay(ledger: dict, applicant: dict, start_date: str,
                       end_date: str):
    payload = create_stay_payload(start_date, end_date)
    return _ok(
        api_client.add_residency_stay(
            ledger["id"], payload, make_applicant_headers(applicant["id"])),
        f"add_residency_stay({start_date}..{end_date})",
    )


def request_residency_waiver(ledger: dict, applicant: dict,
                             waiver_reason: str = "No objection"):
    return _ok(
        api_client.transition_residency_ledger(
            ledger["id"],
            residency_transition_payload("REQUEST_WAIVER", waiver_reason),
            make_applicant_headers(applicant["id"])),
        "request_residency_waiver",
    )


def decide_residency_waiver(ledger: dict, action: str):
    """APPROVE_WAIVER or DENY_WAIVER (ProgramOfficer)."""
    return _ok(
        api_client.transition_residency_ledger(
            ledger["id"], residency_transition_payload(action), _OFFICER),
        f"decide_residency_waiver({action})",
    )


def get_alumni_profiles(applicant: dict):
    return _ok(
        api_client.list_applicant_alumni_profiles(applicant["id"], _OFFICER),
        "list_applicant_alumni_profiles",
    )


# ---------------------------------------------------------------------------
# Tier 1-2: cycle/program/application state progression
# ---------------------------------------------------------------------------

def setup_open_cycle(**program_overrides):
    """DRAFT cycle + one country program + OPEN. Returns
    {"cycle", "program"}."""
    cycle = create_cycle()
    program = add_country_program(cycle, **program_overrides)
    cycle = open_cycle(cycle)
    return {"cycle": cycle, "program": program}


def setup_draft_application(applicant_type: str = "INDEPENDENT",
                            program_overrides=None,
                            application_overrides=None):
    """OPEN cycle with one program + one registered applicant + one DRAFT
    application. Returns {"cycle", "program", "applicant", "application"}."""
    base = setup_open_cycle(**(program_overrides or {}))
    if applicant_type == "ENROLLED_STUDENT":
        applicant = register_enrolled_applicant()
    else:
        applicant = register_applicant(applicant_type=applicant_type)
    application = create_draft_application(
        applicant, base["cycle"], base["program"], **(application_overrides or {}),
    )
    return {**base, "applicant": applicant, "application": application}


def setup_submitted_application(applicant_type: str = "INDEPENDENT",
                                program_overrides=None,
                                application_overrides=None):
    """One application past the submission fork: CAMPUS_REVIEW for an
    ENROLLED_STUDENT, NATIONAL_SCREENING for an INDEPENDENT."""
    bundle = setup_draft_application(
        applicant_type=applicant_type,
        program_overrides=program_overrides,
        application_overrides=application_overrides,
    )
    bundle["application"] = submit_application(
        bundle["application"], bundle["applicant"],
    )
    return bundle


def setup_application_in_national_screening(applicant_type: str = "INDEPENDENT",
                                            national_score=80,
                                            **kwargs):
    """Application in NATIONAL_SCREENING with the two-reviewer national
    quorum already posted (cycle still OPEN). For an enrolled applicant the
    campus leg (quorum + ENDORSE) is walked first."""
    bundle = setup_submitted_application(applicant_type=applicant_type, **kwargs)
    if applicant_type == "ENROLLED_STUDENT":
        post_campus_quorum_scores(bundle["application"])
        bundle["application"] = endorse_application(bundle["application"])
    post_national_quorum_scores(bundle["application"], score=national_score)
    return bundle


def setup_application_in_host_review(applicant_type: str = "INDEPENDENT",
                                     national_score=80,
                                     close: bool = True,
                                     **kwargs):
    """Application in HOST_REVIEW with a stored national_weighted_score.
    The cycle is CLOSED before the recommendation by default so the host
    decision that follows is phase-legal (host decisions require CLOSED or
    SCREENING)."""
    bundle = setup_application_in_national_screening(
        applicant_type=applicant_type, national_score=national_score, **kwargs,
    )
    if close:
        bundle["cycle"] = close_cycle(bundle["cycle"])
    bundle["application"] = recommend_application(bundle["application"])
    return bundle


def setup_host_review_pair(score_a=80, score_b=80, slot_quota: int = 1,
                           program_overrides=None):
    """Two independent applicants, each with an application to the SAME
    program, both recommended and sitting in HOST_REVIEW (recommend_seq 1
    for A, 2 for B). Cycle CLOSED. Returns the base bundle plus
    {"applicant_b", "application_b"}."""
    overrides = {"slot_quota": slot_quota}
    overrides.update(program_overrides or {})
    base = setup_open_cycle(**overrides)
    cycle, program = base["cycle"], base["program"]
    applicant_a = register_applicant()
    applicant_b = register_applicant()
    app_a = create_draft_application(applicant_a, cycle, program)
    app_b = create_draft_application(applicant_b, cycle, program)
    app_a = submit_application(app_a, applicant_a)
    app_b = submit_application(app_b, applicant_b)
    post_national_quorum_scores(app_a, score=score_a)
    post_national_quorum_scores(app_b, score=score_b)
    cycle = close_cycle(cycle)
    app_a = recommend_application(app_a, reviewer_id=NATIONAL_REVIEWER_1)
    app_b = recommend_application(app_b, reviewer_id=NATIONAL_REVIEWER_2)
    return {
        "cycle": cycle, "program": program,
        "applicant": applicant_a, "application": app_a,
        "applicant_b": applicant_b, "application_b": app_b,
    }


# ---------------------------------------------------------------------------
# Tier 3: selection, placement, confirmation
# ---------------------------------------------------------------------------

def setup_selected_application(**kwargs):
    """Application SELECTED with its PROVISIONAL grant created. Adds
    "grant" to the bundle."""
    bundle = setup_application_in_host_review(**kwargs)
    bundle["application"] = host_decide(bundle["application"], "SELECT")
    bundle["grant"] = get_application_grant(bundle["application"])
    return bundle


def setup_grant_pending(institution_band: str = "STANDARD", **kwargs):
    """One placement round opened and ACCEPTED: application GRANT_PENDING.
    Adds "round" to the bundle."""
    bundle = setup_selected_application(**kwargs)
    round_ = open_placement_round(
        bundle["application"], institution_band=institution_band,
    )
    bundle["round"] = accept_placement_round(round_, bundle["applicant"])
    bundle["application"] = get_application(bundle["application"])
    return bundle


def setup_confirmed_grant(start_date: str = DEFAULT_GRANT_START_DATE,
                          end_date: str = DEFAULT_GRANT_END_DATE,
                          institution_band: str = "STANDARD", **kwargs):
    """Grant CONFIRMED with final award terms; application AWARDED."""
    bundle = setup_grant_pending(institution_band=institution_band, **kwargs)
    bundle["grant"] = confirm_grant(
        bundle["application"], start_date=start_date, end_date=end_date,
    )
    bundle["application"] = get_application(bundle["application"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 4-5: visa, activation, incidents, completion, termination
# ---------------------------------------------------------------------------

def setup_active_grant(subject_to_home_residency: bool = True, **kwargs):
    """Grant ACTIVE: confirmation + visa sponsorship + orientation + ACTIVATE
    (clock advanced to start_date). Adds "visa" and "ledger" to the bundle."""
    bundle = setup_confirmed_grant(**kwargs)
    bundle["visa"] = issue_visa_sponsorship(
        bundle["grant"], subject_to_home_residency=subject_to_home_residency,
    )
    bundle["ledger"] = get_visa_ledger(bundle["visa"])
    bundle["grant"] = activate_grant(bundle["grant"])
    return bundle


def setup_suspended_grant(incident_overrides=None, at_clock="2027-11-01T00:00:00Z",
                          **kwargs):
    """Grant SUSPENDED behind one OPEN emergency incident. Adds "incident"."""
    bundle = setup_active_grant(**kwargs)
    set_clock_to(at_clock)
    bundle["incident"] = declare_incident(
        bundle["grant"], **(incident_overrides or {}),
    )
    bundle["grant"] = get_grant(bundle["grant"])
    return bundle


def setup_completed_grant(subject_to_home_residency: bool = True,
                          submit_final: bool = True,
                          final_report_at: str = DEFAULT_GRANT_END_DATE,
                          **kwargs):
    """Full lifecycle through COMPLETED: clock at end_date, an on-time FINAL
    report (due thirty days later), then COMPLETE. The cascade completes the
    visa, opens residency accrual (subject=True) and creates the alumni
    profile. Adds "visa", "ledger", "report", "profile"."""
    bundle = setup_active_grant(
        subject_to_home_residency=subject_to_home_residency, **kwargs,
    )
    set_clock_to(final_report_at)
    if submit_final:
        bundle["report"] = submit_report(
            bundle["grant"], bundle["applicant"], report_type="FINAL",
        )
    bundle["grant"] = complete_grant_action(bundle["grant"])
    profiles = get_alumni_profiles(bundle["applicant"])
    bundle["profile"] = profiles[0] if profiles else None
    bundle["application"] = get_application(bundle["application"])
    return bundle


def setup_accruing_ledger(**kwargs):
    """Completed grant with subject_to_home_residency=True: the residency
    ledger sits in ACCRUING from the grant's end_date."""
    kwargs.setdefault("subject_to_home_residency", True)
    bundle = setup_completed_grant(**kwargs)
    bundle["ledger"] = get_visa_ledger(bundle["visa"])
    return bundle


def setup_terminated_grant(terminate_at: str = "2027-10-11T00:00:00Z",
                           termination_reason: str = "Program closure",
                           subject_to_home_residency: bool = True, **kwargs):
    """Grant TERMINATED_EARLY: the full early-termination cascade (visa
    ENDED_EARLY, ledger ACCRUING from the termination date, alumni profile
    with terminated_early=True, reconciliation figures). Default termination
    clock is 40 days into the canonical 10-month window (1 served month)."""
    bundle = setup_active_grant(
        subject_to_home_residency=subject_to_home_residency, **kwargs,
    )
    set_clock_to(terminate_at)
    bundle["grant"] = terminate_grant(bundle["grant"], termination_reason)
    profiles = get_alumni_profiles(bundle["applicant"])
    bundle["profile"] = profiles[0] if profiles else None
    bundle["ledger"] = get_visa_ledger(bundle["visa"])
    bundle["visa"] = _ok(
        api_client.get_visa_sponsorship(bundle["visa"]["id"], _OFFICER),
        "get_visa_sponsorship",
    )
    return bundle


# ---------------------------------------------------------------------------
# Convenience: expected-value calculators mirroring the PRD formulas.
# Tests use these to build expectations from the same inputs rather than
# duplicating arithmetic inline. round_half_up matches the PRD's rounding.
# ---------------------------------------------------------------------------

def round_half_up_div(numerator: int, denominator: int) -> int:
    """Integer round-half-up of numerator/denominator (exact, no floats)."""
    return (2 * numerator + denominator) // (2 * denominator)


def round_half_up_2dp(value) -> float:
    from decimal import Decimal, ROUND_HALF_UP

    return float(
        Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def expected_weighted_score(scores):
    """Weighted screening score from a list of (feasibility, country_fit,
    language) triples: per-axis means rounded half up to 2 dp, then the
    weighted sum of 0.40/0.35/0.25 rounded half up to 2 dp."""
    n = len(scores)

    def _avg(idx):
        return round_half_up_2dp(sum(s[idx] for s in scores) / n)

    avg_f = _avg(0)
    avg_c = _avg(1)
    avg_l = _avg(2)
    weighted = (
        0.40 * avg_f + 0.35 * avg_c + 0.25 * avg_l
    )
    return round_half_up_2dp(weighted)


def expected_provisional_total(program: dict, dependents_count: int,
                               proposed_duration_months: int) -> int:
    """Provisional award: STANDARD band, requested duration, no percentage
    cap on the dependent allowance (counted dependents still top out at two)."""
    counted = min(dependents_count, 2)
    monthly = (
        program["monthly_stipend_standard_cents"]
        + program["dependent_allowance_monthly_cents"] * counted
        + program["health_benefit_monthly_cents"]
    )
    return monthly * proposed_duration_months + program["travel_allowance_cents"]


def expected_final_total(program: dict, dependents_count: int,
                         duration_months: int, awarded_band: str) -> int:
    """Final award: awarded-band stipend, confirmed duration, dependent
    allowance capped at one quarter of the base total — the base EXCLUDES
    the dependent allowance and the cap is computed before the allowance is
    granted (evaluation order is pinned)."""
    monthly_stipend = (
        program["monthly_stipend_high_cents"]
        if awarded_band == "HIGH"
        else program["monthly_stipend_standard_cents"]
    )
    base_total = (
        (monthly_stipend + program["health_benefit_monthly_cents"])
        * duration_months
        + program["travel_allowance_cents"]
    )
    dep_raw = (
        program["dependent_allowance_monthly_cents"]
        * min(dependents_count, 2)
        * duration_months
    )
    dep_cap = round_half_up_div(base_total, 4)  # round_half_up(0.25 * base)
    dep_final = min(dep_raw, dep_cap)
    return base_total + dep_final


def expected_termination_split(final_total_cents: int, duration_months: int,
                               served_months: int):
    """Early-termination reconciliation with the pinned rounding order:
    monthly rate rounded half up to whole cents FIRST, then multiplied.
    Returns (earned_cents, repayment_cents, reconciliation_adjustment_cents)."""
    monthly_rate = round_half_up_div(final_total_cents, duration_months)
    unserved_months = duration_months - served_months
    earned = served_months * monthly_rate
    repayment = unserved_months * monthly_rate
    adjustment = final_total_cents - earned - repayment
    return earned, repayment, adjustment


def expected_duration_months(start_year: int, start_month: int,
                             end_year: int, end_month: int) -> int:
    """Whole calendar months: (end.year-start.year)*12 + (end.month-start.month)."""
    return (end_year - start_year) * 12 + (end_month - start_month)
