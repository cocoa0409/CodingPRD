"""Composite setup helpers.

Most testable claims require the registry to be in a state that takes 5-15 API
calls to reach; these fixtures build those preconditions from scratch against
an empty database, using only PRD-declared endpoints. All setup calls go
through get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.

Identity threading (PRD §2.1): every Candidate call uses
make_candidate_headers(candidate_id); every program-scoped attestation uses
make_program_director_headers(program["director_user_id"]). The logical clock
is only ever moved forward; fixtures that need a specific instant set it
explicitly via advance_clock().
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DEFAULT_ISO,
    DEFAULT_ADMIN_USER_ID,
    DEFAULT_COMPLETION_DATE,
    DEFAULT_DELIVERY_CLOCK,
    DEFAULT_DIRECTOR_USER_ID,
    DEFAULT_HEARING_OFFICER_USER_ID,
    DEFAULT_ISSUE_CLOCK,
    DEFAULT_PROCTOR_USER_ID,
    DEFAULT_PSYCHOMOTOR_EXAM_DATE,
    DEFAULT_RECERT_CLOCK,
    DEFAULT_SCHEDULED_END,
    DEFAULT_SCHEDULED_START,
    DEFAULT_STATE_OFFICIAL_USER_ID,
    REMEDIAL_GATE_CONSUMED,
)
from .factories import (
    accreditation_event_payload,
    appeal_decision_payload,
    audit_outcome_payload,
    case_appeal_payload,
    case_decide_payload,
    case_response_payload,
    cat_pass_responses,
    cat_responses_payload,
    ce_entry_payload,
    clock_payload,
    create_candidate_payload,
    create_completion_record_payload,
    create_disciplinary_case_payload,
    create_education_program_payload,
    create_exam_application_payload,
    create_level_payload,
    create_psychomotor_payload,
    create_reentry_application_payload,
    create_remedial_record_payload,
    create_state_exam_record_payload,
    create_state_policy_payload,
    decision_payload,
    issue_certification_payload,
    license_respond_payload,
    schedule_attempt_payload,
    create_recert_application_payload,
    create_license_application_payload,
)
from .test_users import (
    ANONYMOUS_HEADERS,
    TEST_USERS,
    make_candidate_headers,
    make_hearing_officer_headers,
    make_program_director_headers,
    make_registry_admin_headers,
    make_state_official_headers,
)

ADMIN = TEST_USERS["registry_admin_headers"]
PROCTOR = TEST_USERS["exam_proctor_headers"]


# ---------------------------------------------------------------------------
# Datetime helpers (logical-clock arithmetic for fixture timelines)
# ---------------------------------------------------------------------------
def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def date_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def iso_days_after(iso: str, days: int) -> str:
    return iso_z(_parse_iso(iso) + timedelta(days=days))


# ---------------------------------------------------------------------------
# Clock + configuration primitives
# ---------------------------------------------------------------------------
def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock and run the deterministic sweep (PRD §2.5)."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


def create_level(**overrides) -> dict:
    return get_success_data(api_client.create_level_definition(create_level_payload(**overrides), ADMIN))


def create_state_policy(**overrides) -> dict:
    return get_success_data(api_client.create_state_adoption_policy(create_state_policy_payload(**overrides), ADMIN))


def create_candidate(**overrides) -> dict:
    """Self-registration is the header-exempt endpoint; returns the Candidate
    whose id becomes the caller's X-User-ID."""
    return get_success_data(api_client.register_candidate(create_candidate_payload(**overrides), ANONYMOUS_HEADERS))


def create_program(level_id: str, director_user_id: str = DEFAULT_DIRECTOR_USER_ID, **overrides) -> dict:
    payload = create_education_program_payload(level_id, director_user_id=director_user_id, **overrides)
    return get_success_data(api_client.create_education_program(payload, ADMIN))


def record_accreditation_event(program_id: str, to_status: str, effective_date: str,
                               reason: str = "Recorded event") -> dict:
    payload = accreditation_event_payload(to_status, effective_date, reason)
    return get_success_data(api_client.record_accreditation_event(program_id, payload, ADMIN))


# ---------------------------------------------------------------------------
# Education attestation (Tier 1)
# ---------------------------------------------------------------------------
def create_verified_completion(candidate_id: str, program: dict,
                               completion_date: str = DEFAULT_COMPLETION_DATE,
                               outcome: str = "VERIFIED") -> dict:
    """ProgramDirector attests; RegistryAdmin decides. Returns the record."""
    director_headers = make_program_director_headers(program["director_user_id"])
    rec = get_success_data(api_client.create_program_completion_record(
        create_completion_record_payload(candidate_id, program["id"], completion_date=completion_date),
        director_headers,
    ))
    return get_success_data(api_client.decide_program_completion_record(
        rec["id"], decision_payload(outcome), ADMIN,
    ))


# ---------------------------------------------------------------------------
# Exam applications and attempts (Tier 1-3)
# ---------------------------------------------------------------------------
def create_exam_application(candidate_id: str, level_id: str, completion_record_id: str) -> dict:
    return get_success_data(api_client.create_exam_application(
        create_exam_application_payload(level_id, completion_record_id),
        make_candidate_headers(candidate_id),
    ))


def approve_exam_application(application_id: str, outcome: str = "APPROVED") -> dict:
    """RegistryAdmin decision; on APPROVED the response carries the minted att_id."""
    return get_success_data(api_client.decide_exam_application(
        application_id, decision_payload(outcome), ADMIN,
    ))


def create_approved_exam_application(candidate_id: str, level_id: str,
                                     completion_record_id: str) -> dict:
    """Create + approve; the returned application carries att_id."""
    app = create_exam_application(candidate_id, level_id, completion_record_id)
    return approve_exam_application(app["id"])


def schedule_attempt(candidate_id: str, att_id: str,
                     scheduled_start: str = DEFAULT_SCHEDULED_START,
                     scheduled_end: str = DEFAULT_SCHEDULED_END) -> dict:
    return get_success_data(api_client.schedule_cognitive_exam_attempt(
        schedule_attempt_payload(att_id, scheduled_start, scheduled_end),
        make_candidate_headers(candidate_id),
    ))


def deliver_attempt(attempt_id: str, responses_payload: Optional[dict] = None) -> dict:
    """ExamProctor delivers and scores. Default: all-correct pass."""
    payload = responses_payload if responses_payload is not None else cat_pass_responses()
    return get_success_data(api_client.deliver_cognitive_exam_responses(attempt_id, payload, PROCTOR))


# ---------------------------------------------------------------------------
# Psychomotor verification
# ---------------------------------------------------------------------------
def create_psychomotor(candidate_id: str, level_id: str, completion_record_id: str,
                       administered_by: str = "STATE",
                       program_id: Optional[str] = None,
                       evaluator_user_id: Optional[str] = None,
                       exam_date: str = DEFAULT_PSYCHOMOTOR_EXAM_DATE,
                       stations: Optional[list] = None,
                       documentation_attached: bool = True) -> dict:
    """Submit psychomotor documentation. STATE path defaults to evaluator so-1;
    PROGRAM path defaults to a director distinct from the completion attester
    (segregation of duties, PRD §2.1/§3.5)."""
    overrides: Dict[str, Any] = {}
    if administered_by == "PROGRAM":
        overrides["program_id"] = program_id
        evaluator = evaluator_user_id or "dir-2"
        headers = make_program_director_headers(evaluator)
    else:
        evaluator = evaluator_user_id or DEFAULT_STATE_OFFICIAL_USER_ID
        headers = make_state_official_headers(evaluator)
    if stations is not None:
        overrides["stations"] = stations
    payload = create_psychomotor_payload(
        candidate_id, level_id, completion_record_id,
        administered_by=administered_by, exam_date=exam_date,
        documentation_attached=documentation_attached, **overrides,
    )
    return get_success_data(api_client.create_psychomotor_verification(payload, headers))


def verify_psychomotor(verification_id: str, outcome: str = "VERIFIED") -> dict:
    return get_success_data(api_client.decide_psychomotor_verification(
        verification_id, decision_payload(outcome), ADMIN,
    ))


def create_verified_psychomotor(candidate_id: str, level_id: str, completion_record_id: str,
                                **kwargs) -> dict:
    psy = create_psychomotor(candidate_id, level_id, completion_record_id, **kwargs)
    return verify_psychomotor(psy["id"])


# ---------------------------------------------------------------------------
# Remedial education
# ---------------------------------------------------------------------------
def create_remedial_record(candidate_id: str, level_id: str, hours: float = 20,
                           completed_date: str = DEFAULT_COMPLETION_DATE,
                           provider_name: str = "RemedialCE",
                           director_user_id: str = DEFAULT_DIRECTOR_USER_ID) -> dict:
    """ProgramDirector attests remedial education; verified at creation."""
    payload = create_remedial_record_payload(
        candidate_id, level_id, hours=hours,
        completed_date=completed_date, provider_name=provider_name,
    )
    return get_success_data(api_client.create_remedial_education_record(
        payload, make_program_director_headers(director_user_id),
    ))


# ---------------------------------------------------------------------------
# Certification issuance
# ---------------------------------------------------------------------------
def issue_certification(candidate_id: str, level_id: str, exam_application_id: str,
                        attempt_id: str, psychomotor_id: str) -> dict:
    payload = issue_certification_payload(
        candidate_id, level_id, exam_application_id, attempt_id, psychomotor_id,
    )
    return get_success_data(api_client.issue_certification(payload, ADMIN))


def refresh_certification(certification_id: str) -> dict:
    return get_success_data(api_client.get_certification(certification_id, ADMIN))


def refresh_completion_record(record_id: str) -> dict:
    return get_success_data(api_client.get_program_completion_record(record_id, ADMIN))


def refresh_recert_application(application_id: str) -> dict:
    return get_success_data(api_client.get_recert_application(application_id, ADMIN))


def refresh_case(case_id: str) -> dict:
    return get_success_data(api_client.get_disciplinary_case(case_id, ADMIN))


def refresh_license_application(application_id: str) -> dict:
    return get_success_data(api_client.get_license_application(application_id, ADMIN))


# ---------------------------------------------------------------------------
# Composite chain tiers (the canonical certified-candidate pipeline)
# ---------------------------------------------------------------------------
def setup_candidate_with_verified_completion(
        level_overrides: Optional[dict] = None,
        candidate_overrides: Optional[dict] = None,
        director_user_id: str = DEFAULT_DIRECTOR_USER_ID,
        completion_date: str = DEFAULT_COMPLETION_DATE,
        start_clock: Optional[str] = CLOCK_DEFAULT_ISO) -> dict:
    """Level + candidate + accredited program + VERIFIED completion record."""
    if start_clock is not None:
        advance_clock(start_clock)
    level = create_level(**(level_overrides or {}))
    candidate = create_candidate(**(candidate_overrides or {}))
    program = create_program(level["id"], director_user_id=director_user_id)
    record = create_verified_completion(candidate["id"], program, completion_date)
    return {
        "level": level,
        "candidate": candidate,
        "candidate_headers": make_candidate_headers(candidate["id"]),
        "program": program,
        "director_user_id": director_user_id,
        "completion_record": record,
    }


def setup_approved_application(
        scheduled_start: str = DEFAULT_SCHEDULED_START,
        scheduled_end: str = DEFAULT_SCHEDULED_END,
        **kwargs) -> dict:
    """... + APPROVED exam application with a minted ATT (att_id)."""
    ctx = setup_candidate_with_verified_completion(**kwargs)
    app = create_approved_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    ctx["exam_application"] = app
    ctx["att_id"] = app["att_id"]
    return ctx


def setup_scored_attempt(
        delivery_clock: str = DEFAULT_DELIVERY_CLOCK,
        responses_payload: Optional[dict] = None,
        scheduled_start: str = DEFAULT_SCHEDULED_START,
        scheduled_end: str = DEFAULT_SCHEDULED_END,
        **kwargs) -> dict:
    """... + one SCHEDULED attempt scored via response delivery."""
    ctx = setup_approved_application(
        scheduled_start=scheduled_start, scheduled_end=scheduled_end, **kwargs,
    )
    attempt = schedule_attempt(
        ctx["candidate"]["id"], ctx["att_id"], scheduled_start, scheduled_end,
    )
    advance_clock(delivery_clock)
    ctx["attempt"] = deliver_attempt(attempt["id"], responses_payload)
    return ctx


def setup_certified_candidate(
        psychomotor_exam_date: str = DEFAULT_PSYCHOMOTOR_EXAM_DATE,
        administered_by: str = "STATE",
        evaluator_user_id: Optional[str] = None,
        issue_clock: str = DEFAULT_ISSUE_CLOCK,
        **kwargs) -> dict:
    """The full chain: level -> candidate -> program -> VERIFIED completion ->
    APPROVED application (ATT) -> scored PASS attempt -> VERIFIED psychomotor
    -> issued ACTIVE certification. Returns a context dict carrying every
    artifact plus candidate_headers and the operator ids used."""
    ctx = setup_scored_attempt(**kwargs)
    candidate_id = ctx["candidate"]["id"]
    program_id = ctx["program"]["id"] if administered_by == "PROGRAM" else None
    ctx["psychomotor"] = create_verified_psychomotor(
        candidate_id, ctx["level"]["id"], ctx["completion_record"]["id"],
        administered_by=administered_by, program_id=program_id,
        evaluator_user_id=evaluator_user_id, exam_date=psychomotor_exam_date,
    )
    advance_clock(issue_clock)
    ctx["certification"] = issue_certification(
        candidate_id, ctx["level"]["id"], ctx["exam_application"]["id"],
        ctx["attempt"]["id"], ctx["psychomotor"]["id"],
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: attempt-budget accumulation (remedial gate / hard cap / void-restore)
# ---------------------------------------------------------------------------
def setup_candidate_with_consumed_attempts(
        consumed_count: int,
        outcome_sequence: Optional[List[str]] = None,
        level_overrides: Optional[dict] = None,
        candidate_overrides: Optional[dict] = None,
        director_user_id: str = DEFAULT_DIRECTOR_USER_ID,
        first_delivery: str = DEFAULT_DELIVERY_CLOCK) -> dict:
    """Build a basis with `consumed_count` delivered attempts (default all
    SCORED_FAIL), respecting the 15-day retake wait between deliveries.

    When more than REMEDIAL_GATE_CONSUMED(3) attempts are requested, a
    qualifying remedial record (20h, completed strictly after the 3rd fail's
    delivered date) is attested before approval #4 so the remedial gate passes.

    Returns a ctx dict: level, candidate, program, completion_record,
    applications[], attempts[], candidate_headers, last_delivery_clock.
    """
    outcomes = outcome_sequence or ["fail"] * consumed_count
    assert len(outcomes) == consumed_count
    ctx = setup_candidate_with_verified_completion(
        level_overrides=level_overrides,
        candidate_overrides=candidate_overrides,
        director_user_id=director_user_id,
    )
    candidate_id = ctx["candidate"]["id"]
    level_id = ctx["level"]["id"]
    record_id = ctx["completion_record"]["id"]

    base = _parse_iso(first_delivery)
    applications: List[dict] = []
    attempts: List[dict] = []
    last_delivery_clock = first_delivery
    third_fail_delivery: Optional[datetime] = None
    fails_seen = 0

    for k in range(1, consumed_count + 1):
        # Remedial gate: approvals beyond the 3rd consumed attempt require a
        # qualifying remedial record completed strictly after the 3rd fail.
        if k == REMEDIAL_GATE_CONSUMED + 1 and third_fail_delivery is not None:
            create_remedial_record(
                candidate_id, level_id, hours=20,
                completed_date=date_str(third_fail_delivery + timedelta(days=1)),
                director_user_id=director_user_id,
            )
        app = create_approved_exam_application(candidate_id, level_id, record_id)
        delivery = base + timedelta(days=17 * (k - 1))
        window_start = iso_z(delivery - timedelta(days=1))
        window_end = iso_z(delivery + timedelta(days=1))
        attempt = schedule_attempt(candidate_id, app["att_id"], window_start, window_end)
        advance_clock(iso_z(delivery))
        payload = (cat_responses_payload(0, 6) if outcomes[k - 1] == "fail"
                   else cat_pass_responses())
        scored = deliver_attempt(attempt["id"], payload)
        applications.append(app)
        attempts.append(scored)
        last_delivery_clock = iso_z(delivery)
        if outcomes[k - 1] == "fail":
            fails_seen += 1
            if fails_seen == REMEDIAL_GATE_CONSUMED:
                third_fail_delivery = delivery

    ctx["applications"] = applications
    ctx["attempts"] = attempts
    ctx["last_delivery_clock"] = last_delivery_clock
    return ctx


# ---------------------------------------------------------------------------
# Lapse and reentry
# ---------------------------------------------------------------------------
def setup_lapsed_certification(lapse_clock: str = "2028-09-15T00:00:00Z",
                               **certified_kwargs) -> dict:
    """Certified candidate whose certification the sweep has moved to LAPSED
    (default: 11 days past the 2028-09-04 expiry — inside TIER_CE_ONLY)."""
    ctx = setup_certified_candidate(**certified_kwargs)
    advance_clock(lapse_clock)
    ctx["certification"] = refresh_certification(ctx["certification"]["id"])
    return ctx


def create_reentry_application(candidate_id: str, certification_id: str,
                               ce_makeup_hours_claimed: Optional[float] = None,
                               refresher_hours_claimed: Optional[float] = None) -> dict:
    overrides: Dict[str, Any] = {}
    if ce_makeup_hours_claimed is not None:
        overrides["ce_makeup_hours_claimed"] = ce_makeup_hours_claimed
    if refresher_hours_claimed is not None:
        overrides["refresher_hours_claimed"] = refresher_hours_claimed
    return get_success_data(api_client.create_reentry_application(
        create_reentry_application_payload(certification_id, **overrides),
        make_candidate_headers(candidate_id),
    ))


def decide_reentry(application_id: str, outcome: str, reason: Optional[str] = None) -> dict:
    payload = decision_payload(outcome)
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.decide_reentry_application(application_id, payload, ADMIN))


# ---------------------------------------------------------------------------
# Recertification
# ---------------------------------------------------------------------------
def create_recert_draft(candidate_id: str, certification_id: str, model: str = "NCCP") -> dict:
    """Open a draft against an ACTIVE certification. Reads the certification
    fresh so the OCC token (expected_certification_version) is current."""
    cert = refresh_certification(certification_id)
    return get_success_data(api_client.create_recert_application(
        create_recert_application_payload(certification_id, model, cert["version"]),
        make_candidate_headers(candidate_id),
    ))


def default_nccp_entry_specs() -> List[dict]:
    """Exact-minimum NCCP portfolio (N 10+10, L 10, I 10 = 40, all IN_PERSON,
    distinct providers, dates inside the default cycle window)."""
    return [
        dict(component="NATIONAL", hours=10, delivery_method="IN_PERSON",
             course_code="N1", course_date="2027-10-01", provider_name="AlphaCE"),
        dict(component="NATIONAL", hours=10, delivery_method="IN_PERSON",
             course_code="N2", course_date="2027-10-02", provider_name="BetaCE"),
        dict(component="LOCAL", hours=10, delivery_method="IN_PERSON",
             course_code="L1", course_date="2027-10-03", provider_name="GammaCE"),
        dict(component="INDIVIDUAL", hours=10, delivery_method="IN_PERSON",
             course_code="I1", course_date="2027-10-04", provider_name="DeltaCE"),
    ]


def single_provider_audit_entry_specs() -> List[dict]:
    """Sufficient portfolio whose largest single-provider share reaches 20
    hours (MegaCE 20) so the audit selector fires."""
    return [
        dict(component="NATIONAL", hours=20, delivery_method="IN_PERSON",
             course_code="N1", course_date="2027-10-01", provider_name="MegaCE"),
        dict(component="LOCAL", hours=10, delivery_method="IN_PERSON",
             course_code="L1", course_date="2027-10-02", provider_name="GammaCE"),
        dict(component="INDIVIDUAL", hours=10, delivery_method="IN_PERSON",
             course_code="I1", course_date="2027-10-03", provider_name="DeltaCE"),
    ]


def add_ce_entries(recert_application_id: str, candidate_id: str,
                   entry_specs: List[dict]) -> List[dict]:
    entries = []
    for spec in entry_specs:
        entries.append(get_success_data(api_client.add_ce_entry(
            recert_application_id, ce_entry_payload(**spec),
            make_candidate_headers(candidate_id),
        )))
    return entries


def setup_recert_draft_with_entries(
        certified_ctx: Optional[dict] = None,
        model: str = "NCCP",
        entry_specs: Optional[List[dict]] = None,
        recert_clock: str = DEFAULT_RECERT_CLOCK,
        **certified_kwargs) -> dict:
    """ACTIVE certification + open DRAFT + CE entries attached.
    Returns the certified context extended with recert_application, entries,
    and candidate_headers."""
    ctx = certified_ctx or setup_certified_candidate(**certified_kwargs)
    candidate_id = ctx["candidate"]["id"]
    advance_clock(recert_clock)
    recert = create_recert_draft(candidate_id, ctx["certification"]["id"], model)
    specs = entry_specs if entry_specs is not None else default_nccp_entry_specs()
    entries = add_ce_entries(recert["id"], candidate_id, specs)
    ctx["recert_application"] = recert
    ctx["entries"] = entries
    return ctx


def submit_recert(recert_application_id: str, candidate_id: str) -> dict:
    return get_success_data(api_client.submit_recert_application(
        recert_application_id, make_candidate_headers(candidate_id),
    ))


def setup_submitted_recert(**kwargs) -> dict:
    """DRAFT + entries + submit. Default portfolio is audit-clean -> SUBMITTED."""
    ctx = setup_recert_draft_with_entries(**kwargs)
    ctx["recert_application"] = submit_recert(
        ctx["recert_application"]["id"], ctx["candidate"]["id"],
    )
    return ctx


def setup_audit_pending_recert(**kwargs) -> dict:
    """Portfolio flagged by the audit selector -> AUDIT_PENDING after submit."""
    kwargs.setdefault("entry_specs", single_provider_audit_entry_specs())
    return setup_submitted_recert(**kwargs)


def decide_recert(application_id: str, outcome: str, reason: Optional[str] = None) -> dict:
    payload = decision_payload(outcome)
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.decide_recert_application(application_id, payload, ADMIN))


def record_audit_outcome(application_id: str, entry_verdicts: List[dict]) -> dict:
    return get_success_data(api_client.record_audit_outcome(
        application_id, audit_outcome_payload(entry_verdicts), ADMIN,
    ))


def reopen_recert(application_id: str, candidate_id: str) -> dict:
    return get_success_data(api_client.reopen_recert_application(
        application_id, make_candidate_headers(candidate_id),
    ))


# ---------------------------------------------------------------------------
# State licensure
# ---------------------------------------------------------------------------
def create_state_exam_record(candidate_id: str, state_code: str, level_id: str,
                             official_user_id: str = DEFAULT_STATE_OFFICIAL_USER_ID,
                             **overrides) -> dict:
    payload = create_state_exam_record_payload(candidate_id, state_code, level_id, **overrides)
    return get_success_data(api_client.create_state_exam_record(
        payload, make_state_official_headers(official_user_id),
    ))


def create_license_application(candidate_id: str, state_code: str, level_id: str,
                               certification_id: Optional[str] = None,
                               state_exam_record_id: Optional[str] = None,
                               jurisprudence_completed: Optional[bool] = None,
                               expected_certification_version: Optional[int] = None) -> dict:
    """Candidate licensure application. On the national path the OCC token is
    read fresh from the certification unless explicitly supplied."""
    overrides: Dict[str, Any] = {}
    if certification_id is not None:
        overrides["certification_id"] = certification_id
        if expected_certification_version is None:
            expected_certification_version = refresh_certification(certification_id)["version"]
        overrides["expected_certification_version"] = expected_certification_version
    if state_exam_record_id is not None:
        overrides["state_exam_record_id"] = state_exam_record_id
    if jurisprudence_completed is not None:
        overrides["jurisprudence_completed"] = jurisprudence_completed
    return get_success_data(api_client.create_license_application(
        create_license_application_payload(state_code, level_id, **overrides),
        make_candidate_headers(candidate_id),
    ))


def setup_license_context_nremt(
        policy_overrides: Optional[dict] = None,
        certified_kwargs: Optional[dict] = None,
        jurisprudence_completed: Optional[bool] = None) -> dict:
    """NREMT_ACCEPTED policy + certified candidate + UNDER_REVIEW application."""
    policy = create_state_policy(**(policy_overrides or {}))
    ctx = setup_certified_candidate(**(certified_kwargs or {}))
    ctx["policy"] = policy
    ctx["license_application"] = create_license_application(
        ctx["candidate"]["id"], policy["state_code"], ctx["level"]["id"],
        certification_id=ctx["certification"]["id"],
        jurisprudence_completed=jurisprudence_completed,
    )
    return ctx


def setup_license_context_state_exam(
        policy_overrides: Optional[dict] = None,
        state_exam_overrides: Optional[dict] = None,
        jurisprudence_completed: Optional[bool] = None) -> dict:
    """STATE_EXAM policy + candidate + passing state exam record + application."""
    defaults = {"state_code": "TX", "adoption_mode": "STATE_EXAM",
                "base_license_fee_cents": 9990, "state_exam_fee_cents": 5000}
    defaults.update(policy_overrides or {})
    policy = create_state_policy(**defaults)
    level = create_level()
    candidate = create_candidate()
    record = create_state_exam_record(
        candidate["id"], policy["state_code"], level["id"],
        **(state_exam_overrides or {}),
    )
    application = create_license_application(
        candidate["id"], policy["state_code"], level["id"],
        state_exam_record_id=record["id"],
        jurisprudence_completed=jurisprudence_completed,
    )
    return {
        "level": level,
        "candidate": candidate,
        "candidate_headers": make_candidate_headers(candidate["id"]),
        "policy": policy,
        "state_exam_record": record,
        "license_application": application,
    }


def decide_license(application_id: str, outcome: str,
                   official_user_id: str = DEFAULT_STATE_OFFICIAL_USER_ID,
                   reason: Optional[str] = None) -> dict:
    payload = decision_payload(outcome)
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.decide_license_application(
        application_id, payload, make_state_official_headers(official_user_id),
    ))


def respond_license(application_id: str, candidate_id: str,
                    response_note: str = "Additional information attached") -> dict:
    return get_success_data(api_client.respond_license_application(
        application_id, license_respond_payload(response_note),
        make_candidate_headers(candidate_id),
    ))


# ---------------------------------------------------------------------------
# Disciplinary due process
# ---------------------------------------------------------------------------
def open_case(subject_candidate_id: str,
              violation_type: str = "CRIMINAL_CONDUCT",
              opener_role: str = "RegistryAdmin",
              opener_user_id: str = DEFAULT_ADMIN_USER_ID,
              interim_action: Optional[str] = None,
              implicated_attempt_ids: Optional[List[str]] = None,
              implicated_completion_record_ids: Optional[List[str]] = None,
              description: str = "Allegation under review") -> dict:
    overrides: Dict[str, Any] = {"description": description}
    if interim_action is not None:
        overrides["interim_action"] = interim_action
    if implicated_attempt_ids is not None:
        overrides["implicated_attempt_ids"] = implicated_attempt_ids
    if implicated_completion_record_ids is not None:
        overrides["implicated_completion_record_ids"] = implicated_completion_record_ids
    if opener_role == "StateOfficial":
        headers = make_state_official_headers(opener_user_id)
    else:
        headers = make_registry_admin_headers(opener_user_id)
    return get_success_data(api_client.create_disciplinary_case(
        create_disciplinary_case_payload(subject_candidate_id, violation_type, **overrides),
        headers,
    ))


def issue_notice(case_id: str) -> dict:
    return get_success_data(api_client.issue_case_notice(case_id, ADMIN))


def submit_case_response(case_id: str, subject_candidate_id: str,
                         response_text: str = "Response to the allegations") -> dict:
    return get_success_data(api_client.submit_case_response(
        case_id, case_response_payload(response_text),
        make_candidate_headers(subject_candidate_id),
    ))


def walk_case_to_under_review(case_id: str, subject_candidate_id: str) -> dict:
    """OPENED -> NOTICE_ISSUED -> UNDER_REVIEW (subject responds early)."""
    issue_notice(case_id)
    return submit_case_response(case_id, subject_candidate_id)


def schedule_hearing(case_id: str,
                     officer_user_id: str = DEFAULT_HEARING_OFFICER_USER_ID) -> dict:
    return get_success_data(api_client.schedule_case_hearing(
        case_id, make_hearing_officer_headers(officer_user_id),
    ))


def walk_case_to_hearing_scheduled(case_id: str, subject_candidate_id: str,
                                   officer_user_id: str = DEFAULT_HEARING_OFFICER_USER_ID) -> dict:
    walk_case_to_under_review(case_id, subject_candidate_id)
    return schedule_hearing(case_id, officer_user_id)


def decide_case(case_id: str, sanction_type: str = "WARNING",
                findings: str = "Findings of the hearing",
                officer_user_id: str = DEFAULT_HEARING_OFFICER_USER_ID) -> dict:
    """OCC-guarded decision: the case version is re-read immediately before."""
    current = refresh_case(case_id)
    payload = case_decide_payload(sanction_type, findings, current["version"])
    return get_success_data(api_client.decide_case(
        case_id, payload, make_hearing_officer_headers(officer_user_id),
    ))


def walk_case_to_decided(case_id: str, subject_candidate_id: str,
                         sanction_type: str = "WARNING",
                         findings: str = "Findings of the hearing",
                         officer_user_id: str = DEFAULT_HEARING_OFFICER_USER_ID) -> dict:
    """OPENED -> ... -> HEARING_SCHEDULED -> DECIDED (no sanction applied yet)."""
    walk_case_to_hearing_scheduled(case_id, subject_candidate_id, officer_user_id)
    return decide_case(case_id, sanction_type, findings, officer_user_id)


def appeal_case(case_id: str, subject_candidate_id: str,
                appeal_grounds: str = "Procedural challenge") -> dict:
    return get_success_data(api_client.appeal_case(
        case_id, case_appeal_payload(appeal_grounds),
        make_candidate_headers(subject_candidate_id),
    ))


def decide_appeal(case_id: str, outcome: str, rationale: str = "Appeal reviewed") -> dict:
    return get_success_data(api_client.decide_appeal(
        case_id, appeal_decision_payload(outcome, rationale), ADMIN,
    ))


def finalize_decided_case(case_id: str) -> dict:
    """Advance the clock one day past the DECIDED case's appeal_deadline so the
    sweep moves it to FINAL and applies the sanction cascade."""
    case = refresh_case(case_id)
    deadline = case["appeal_deadline"]
    assert deadline, f"case {case_id} has no appeal_deadline (status {case['status']})"
    finalize_clock = iso_z(_parse_iso(deadline) + timedelta(days=1))
    advance_clock(finalize_clock)
    return refresh_case(case_id)


def walk_case_to_final_via_affirm(case_id: str, subject_candidate_id: str,
                                  sanction_type: str = "WARNING",
                                  findings: str = "Findings of the hearing",
                                  officer_user_id: str = DEFAULT_HEARING_OFFICER_USER_ID) -> dict:
    """DECIDED -> APPEAL_PENDING -> FINAL via an AFFIRMED appeal decision."""
    walk_case_to_decided(case_id, subject_candidate_id, sanction_type, findings, officer_user_id)
    appeal_case(case_id, subject_candidate_id)
    return decide_appeal(case_id, "AFFIRMED")
