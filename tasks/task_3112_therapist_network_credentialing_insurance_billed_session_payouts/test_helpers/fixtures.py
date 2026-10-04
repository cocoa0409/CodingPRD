"""Composite setup helpers.

Every test starts against a freshly launched server with an empty database, so
each helper here builds its preconditions from scratch using only the endpoints
the PRD declares. Helpers use the lenient `get_success_data` validator so a
broken precondition surfaces as a clear "Setup failed" message rather than a
confusing assertion failure downstream.

Identity threading: whenever a call is ownership-gated (session scheduling,
note authoring, continuity acceptance), the helper builds headers from the
actual entity id via `make_clinician_headers` / `make_patient_headers`.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DELIVERY,
    CLOCK_EARLY,
    CLOCK_ONBOARD,
    DEFAULTS,
)
from .factories import (
    create_clinician_payload,
    create_license_payload,
    create_malpractice_policy_payload,
    create_patient_payload,
    create_payer_enrollment_payload,
    create_payer_payload,
    create_payer_rate_payload,
    create_payout_batch_payload,
    create_session_note_payload,
    create_session_payload,
    create_verification_payload,
)
from .test_users import TEST_USERS, make_clinician_headers, make_patient_headers

OPS = TEST_USERS["ops_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
PAYROLL = TEST_USERS["payroll_service_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Time helpers ─────────────────────────────────────

def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_minutes(iso: str, minutes: int) -> str:
    return _fmt(_parse(iso) + timedelta(minutes=minutes))


def shift_days(iso: str, days: int) -> str:
    return _fmt(_parse(iso) + timedelta(days=days))


def shift_hours(iso: str, hours: int) -> str:
    return _fmt(_parse(iso) + timedelta(hours=hours))


# ─── Primitives ───────────────────────────────────────

def set_clock(current_utc: str):
    """Advance the logical clock. Every temporal rule reads this, never the host clock."""
    global _LAST_CLOCK
    _LAST_CLOCK = current_utc
    return get_success_data(api_client.set_clock(current_utc, OPS))


_LAST_CLOCK = DEFAULTS["ENROLLMENT_EFFECTIVE_FROM"]


def _enrollment_start_at_or_before(clock_iso: str) -> str:
    """An enrollment `effective_from` the logical clock already covers.

    PRD §3.2 makes activation conditional on `effective_from` being at or before
    the logical clock, and the enrolment fixture's canonical default
    (`2026-02-01T00:00:00Z`) is in the future for any caller who parks the clock
    at `CLOCK_EARLY` (2026-01-05).  Whenever the clock has not yet reached the
    default the fixture moves the window start back to exactly the clock instant,
    which the PRD admits (`effective_from` at or before the clock).
    """
    clock = _parse(clock_iso)
    default = _parse(DEFAULTS["ENROLLMENT_EFFECTIVE_FROM"])
    if clock >= default:
        return DEFAULTS["ENROLLMENT_EFFECTIVE_FROM"]
    return _fmt(clock)


def make_payer(
    payer_code: str = DEFAULTS["PAYER_CODE"],
    payer_name: str = DEFAULTS["PAYER_NAME"],
    allowed_cpt_codes=None,
    timely_filing_days: int = DEFAULTS["TIMELY_FILING_DAYS"],
    min_malpractice_coverage_cents: int = DEFAULTS["MIN_MALPRACTICE_COVERAGE_CENTS"],
    delegated_credentialing: bool = True,
    credentialing_sla_days: int = DEFAULTS["CREDENTIALING_SLA_DAYS"],
    **overrides,
) -> dict:
    payload = create_payer_payload(
        payer_code=payer_code,
        payer_name=payer_name,
        allowed_cpt_codes=allowed_cpt_codes or list(DEFAULTS["ALLOWED_CPT_CODES"]),
        timely_filing_days=timely_filing_days,
        min_malpractice_coverage_cents=min_malpractice_coverage_cents,
        delegated_credentialing=delegated_credentialing,
        credentialing_sla_days=credentialing_sla_days,
        **overrides,
    )
    return get_success_data(api_client.create_payer(payload, OPS), 201)


def make_rate(
    payer_id: str,
    rate_cents: int = DEFAULTS["RATE_CENTS"],
    rate_set_version: int = DEFAULTS["RATE_SET_VERSION"],
    license_type: str = "LCSW",
    geography: str = DEFAULTS["CLINICIAN_STATE"],
    cpt_code: str = DEFAULTS["CPT_CODE"],
    effective_from: str = DEFAULTS["CONTRACT_RATE_EFFECTIVE_FROM"],
    effective_to=None,
) -> dict:
    payload = create_payer_rate_payload(
        rate_set_version=rate_set_version,
        license_type=license_type,
        geography=geography,
        cpt_code=cpt_code,
        rate_cents=rate_cents,
        effective_from=effective_from,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return get_success_data(api_client.create_payer_rate(payer_id, payload, OPS), 201)


def make_clinician(
    full_name: str = DEFAULTS["CLINICIAN_NAME"],
    license_type: str = "LCSW",
    primary_state: str = DEFAULTS["CLINICIAN_STATE"],
    specialty_tags=None,
    weekly_caseload_target: int = DEFAULTS["CASELOAD_TARGET"],
    availability_blocks=None,
    **overrides,
) -> dict:
    payload = create_clinician_payload(
        full_name=full_name,
        license_type=license_type,
        primary_state=primary_state,
        specialty_tags=specialty_tags or ["ANXIETY"],
        weekly_caseload_target=weekly_caseload_target,
        availability_blocks=availability_blocks
        if availability_blocks is not None
        else [dict(block) for block in DEFAULTS["AVAILABILITY_BLOCKS"]],
        **overrides,
    )
    return get_success_data(api_client.create_clinician(payload, OPS), 201)


def make_license(
    clinician_id: str,
    license_number: str = DEFAULTS["LICENSE_NUMBER"],
    license_type: str = "LCSW",
    issuing_state: str = DEFAULTS["CLINICIAN_STATE"],
    expires_on: str = DEFAULTS["LICENSE_EXPIRES_ON"],
    telehealth_eligible: bool = True,
) -> dict:
    payload = create_license_payload(
        license_number=license_number,
        license_type=license_type,
        issuing_state=issuing_state,
        expires_on=expires_on,
        telehealth_eligible=telehealth_eligible,
    )
    return get_success_data(api_client.create_license(clinician_id, payload, OPS), 201)


def verify_license(clinician_id: str, license_id: str) -> dict:
    return get_success_data(api_client.verify_license(clinician_id, license_id, COMPLIANCE))


def make_malpractice_policy(
    clinician_id: str,
    coverage_cents: int = DEFAULTS["COVERAGE_CENTS"],
    effective_on: str = DEFAULTS["POLICY_EFFECTIVE_ON"],
    expires_on: str = DEFAULTS["POLICY_EXPIRES_ON"],
    tail_coverage: bool = False,
    carrier_name: str = "TherapyGuard Mutual",
) -> dict:
    payload = create_malpractice_policy_payload(
        carrier_name=carrier_name,
        coverage_cents=coverage_cents,
        effective_on=effective_on,
        expires_on=expires_on,
        tail_coverage=tail_coverage,
    )
    return get_success_data(
        api_client.create_malpractice_policy(clinician_id, payload, OPS), 201
    )


def make_enrollment(
    clinician_id: str,
    payer_id: str,
    effective_from: str = DEFAULTS["ENROLLMENT_EFFECTIVE_FROM"],
    effective_to=None,
    delegated: bool = True,
) -> dict:
    payload = create_payer_enrollment_payload(
        clinician_id=clinician_id,
        payer_id=payer_id,
        delegated=delegated,
        effective_from=effective_from,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return get_success_data(api_client.create_payer_enrollment(payload, OPS), 201)


def activate_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.activate_payer_enrollment(enrollment_id, OPS))


def make_verified_patient(
    payer_id: str,
    full_name: str = DEFAULTS["PATIENT_NAME"],
    member_id: str = DEFAULTS["MEMBER_ID"],
    state_code: str = DEFAULTS["CLINICIAN_STATE"],
    deductible_cents: int = DEFAULTS["DEDUCTIBLE_CENTS"],
    coinsurance_rate: float = DEFAULTS["COINSURANCE_RATE"],
    oop_max_cents: int = DEFAULTS["OOP_MAX_CENTS"],
    plan_code: str = DEFAULTS["PLAN_CODE"],
    verification: dict | None = None,
) -> dict:
    """Register a patient and record one VERIFIED benefit snapshot."""
    patient = get_success_data(
        api_client.create_patient(
            create_patient_payload(
                full_name=full_name,
                member_id=member_id,
                payer_id=payer_id,
                plan_code=plan_code,
                state_code=state_code,
                deductible_cents=deductible_cents,
                coinsurance_rate=coinsurance_rate,
                oop_max_cents=oop_max_cents,
            ),
            OPS,
        ),
        201,
    )
    verification_payload = verification or {}
    get_success_data(
        api_client.create_verification(
            patient["id"],
            create_verification_payload(**verification_payload),
            OPS,
        ),
        201,
    )
    return patient


def make_patient_unverified(
    payer_id: str,
    full_name: str = DEFAULTS["PATIENT_NAME"],
    member_id: str = DEFAULTS["MEMBER_ID"],
    state_code: str = DEFAULTS["CLINICIAN_STATE"],
) -> dict:
    return get_success_data(
        api_client.create_patient(
            create_patient_payload(
                full_name=full_name,
                member_id=member_id,
                payer_id=payer_id,
                state_code=state_code,
            ),
            OPS,
        ),
        201,
    )


def make_session(
    clinician_id: str,
    patient_id: str,
    scheduled_start: str,
    scheduled_end: str,
    cpt_code: str = DEFAULTS["CPT_CODE"],
    modality: str = DEFAULTS["MODALITY"],
) -> dict:
    payload = create_session_payload(
        clinician_id=clinician_id,
        patient_id=patient_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        cpt_code=cpt_code,
        modality=modality,
    )
    return get_success_data(api_client.create_session(payload, OPS), 201)


def schedule_session(clinician_id: str, session_id: str) -> dict:
    """Ownership-gated: the acting Clinician is the session's clinician."""
    return get_success_data(
        api_client.schedule_session(session_id, make_clinician_headers(clinician_id))
    )


def add_signed_note(
    clinician_id: str,
    session_id: str,
    duration_minutes: int = DEFAULTS["SESSION_MINUTES"],
    narrative: str = DEFAULTS["NARRATIVE"],
    diagnosis_code: str = DEFAULTS["DIAGNOSIS_CODE"],
    cpt_code: str = DEFAULTS["CPT_CODE"],
) -> dict:
    headers = make_clinician_headers(clinician_id)
    session = get_success_data(api_client.get_session(session_id, OPS))
    note = get_success_data(
        api_client.create_session_note(
            session_id,
            create_session_note_payload(
                duration_minutes=duration_minutes,
                narrative=narrative,
                diagnosis_code=diagnosis_code,
                cpt_code=cpt_code,
                expected_session_version=session["version"],
            ),
            headers,
        ),
        201,
    )
    get_success_data(api_client.sign_session_note(session_id, note["id"], headers))
    return note


def complete_session(clinician_id: str, session_id: str) -> dict:
    return get_success_data(
        api_client.complete_session(session_id, make_clinician_headers(clinician_id))
    )


def make_scheduled_session(
    clinician_id: str,
    patient_id: str,
    scheduled_start: str,
    scheduled_end: str,
    **kwargs,
) -> dict:
    session = make_session(clinician_id, patient_id, scheduled_start, scheduled_end, **kwargs)
    return schedule_session(clinician_id, session["id"])


def make_completed_session(
    clinician_id: str,
    patient_id: str,
    scheduled_start: str,
    scheduled_end: str,
    stripe_note: str = DEFAULTS["NARRATIVE"],
    duration_minutes: int = DEFAULTS["SESSION_MINUTES"],
    **kwargs,
) -> dict:
    """request -> schedule -> signed note -> complete."""
    session = make_scheduled_session(
        clinician_id, patient_id, scheduled_start, scheduled_end, **kwargs
    )
    add_signed_note(
        clinician_id, session["id"], duration_minutes=duration_minutes, narrative=stripe_note
    )
    return complete_session(clinician_id, session["id"])


def submit_claim(session_id: str) -> dict:
    return get_success_data(api_client.create_claim({"session_id": session_id}, OPS), 201)


def adjudicate(claim_id: str, outcome: str, denial_code=None) -> dict:
    payload = {"outcome": outcome}
    if denial_code is not None:
        payload["denial_code"] = denial_code
    return get_success_data(api_client.adjudicate_claim(claim_id, payload, OPS))


# ─── Tier 2: credentialed clinician and full scenario ─

def credential_clinician(
    clinician: dict,
    license_overrides: dict | None = None,
    policy_overrides: dict | None = None,
) -> dict:
    """Record a license, verify it, record a malpractice policy and submit for
    credentialing. Returns {'license': ..., 'policy': ...}."""
    license_overrides = license_overrides or {}
    policy_overrides = policy_overrides or {}
    license_row = make_license(
        clinician["id"],
        license_type=clinician["license_type"],
        issuing_state=clinician["primary_state"],
        **license_overrides,
    )
    license_row = verify_license(clinician["id"], license_row["id"])
    policy = make_malpractice_policy(clinician["id"], **policy_overrides)
    get_success_data(api_client.submit_credentials(clinician["id"], COMPLIANCE))
    return {"license": license_row, "policy": policy}


def setup_billable_clinician(
    clock_onboard: str = CLOCK_ONBOARD,
    payer_code: str = DEFAULTS["PAYER_CODE"],
    rate_cents: int = DEFAULTS["RATE_CENTS"],
    rate_set_version: int = DEFAULTS["RATE_SET_VERSION"],
    geography: str = DEFAULTS["CLINICIAN_STATE"],
    primary_state: str = DEFAULTS["CLINICIAN_STATE"],
    license_type: str = "LCSW",
    allowed_cpt_codes=None,
    timely_filing_days: int = DEFAULTS["TIMELY_FILING_DAYS"],
    min_malpractice_coverage_cents: int = DEFAULTS["MIN_MALPRACTICE_COVERAGE_CENTS"],
    coverage_cents: int = DEFAULTS["COVERAGE_CENTS"],
    enrollment_effective_from: str = DEFAULTS["ENROLLMENT_EFFECTIVE_FROM"],
    weekly_caseload_target: int = DEFAULTS["CASELOAD_TARGET"],
    availability_blocks=None,
    full_name: str = DEFAULTS["CLINICIAN_NAME"],
    specialty_tags=None,
    license_number: str = DEFAULTS["LICENSE_NUMBER"],
    extra_rates=None,
    license_overrides: dict | None = None,
    policy_overrides: dict | None = None,
) -> dict:
    """The canonical billable setup: one payer, one matching rate row, one
    credentialed clinician with one EFFECTIVE enrollment, posture BILLABLE.

    Returns a dict with payer, rate, clinician, license, policy, enrollment.
    """
    set_clock(clock_onboard)
    payer = make_payer(
        payer_code=payer_code,
        allowed_cpt_codes=allowed_cpt_codes,
        timely_filing_days=timely_filing_days,
        min_malpractice_coverage_cents=min_malpractice_coverage_cents,
    )
    rate = make_rate(
        payer["id"],
        rate_cents=rate_cents,
        rate_set_version=rate_set_version,
        license_type=license_type,
        geography=geography,
    )
    for extra in (extra_rates or []):
        make_rate(payer["id"], **extra)
    clinician = make_clinician(
        full_name=full_name,
        license_type=license_type,
        primary_state=primary_state,
        weekly_caseload_target=weekly_caseload_target,
        availability_blocks=availability_blocks,
        specialty_tags=specialty_tags,
    )
    credentialing = credential_clinician(
        clinician,
        license_overrides={"license_number": license_number, **(license_overrides or {})},
        policy_overrides={"coverage_cents": coverage_cents, **(policy_overrides or {})},
    )
    enrollment = make_enrollment(
        clinician["id"], payer["id"], effective_from=enrollment_effective_from
    )
    enrollment = activate_enrollment(enrollment["id"])
    return {
        "payer": payer,
        "rate": rate,
        "clinician": clinician,
        "license": credentialing["license"],
        "policy": credentialing["policy"],
        "enrollment": enrollment,
    }


def attach_billable_clinician(
    payer_id: str,
    enrollment_effective_from: str = DEFAULTS["ENROLLMENT_EFFECTIVE_FROM"],
    enrollment_overrides: dict | None = None,
    license_number: str = DEFAULTS["LICENSE_NUMBER"],
    license_overrides: dict | None = None,
    policy_overrides: dict | None = None,
    **clinician_kwargs,
) -> dict:
    """Create a clinician, credential them against the given payer and activate
    one enrollment, so the clinician reads BILLABLE.

    The credentialing knobs are named parameters rather than passthrough kwargs:
    the PRD declares `license_number`, `telehealth_eligible` and the policy terms
    as inputs of the *license* and *policy* endpoints, not of the clinician
    endpoint, so forwarding them to `make_clinician` would POST unknown fields to
    a clinician creation that must reject them.
    """
    clinician = make_clinician(**clinician_kwargs)
    credentialing = credential_clinician(
        clinician,
        license_overrides={"license_number": license_number, **(license_overrides or {})},
        policy_overrides=policy_overrides or {},
    )
    # The clock is read from the module-level record, not re-parsed, because
    # credentialing never moves it: `_enrollment_start_at_or_before` sees the
    # same instant the activation below will compare against.
    enrollment = make_enrollment(
        clinician["id"], payer_id,
        effective_from=_enrollment_start_at_or_before(_LAST_CLOCK),
        **(enrollment_overrides or {}),
    )
    enrollment = activate_enrollment(enrollment["id"])
    clinician = get_clinician(clinician["id"])
    return {
        "clinician": clinician,
        "license": credentialing["license"],
        "policy": credentialing["policy"],
        "enrollment": enrollment,
    }


def setup_billable_scenario_with_patient(
    clock_onboard: str = CLOCK_ONBOARD,
    clock_delivery: str = CLOCK_DELIVERY,
    patient_overrides: dict | None = None,
    verification: dict | None = None,
    **clinician_kwargs,
) -> dict:
    """Billable clinician plus one VERIFIED patient, with the clock moved to the
    delivery instant."""
    scenario = setup_billable_clinician(clock_onboard=clock_onboard, **clinician_kwargs)
    patient = make_verified_patient(
        scenario["payer"]["id"], verification=verification, **(patient_overrides or {})
    )
    set_clock(clock_delivery)
    scenario["patient"] = patient
    return scenario


def build_payer_with_clinician(
    payer_kwargs: dict | None = None,
    rate_kwargs: dict | None = None,
    clinician_kwargs: dict | None = None,
    enrollment_kwargs: dict | None = None,
    patient_kwargs: dict | None = None,
    verification: dict | None = None,
    clock_onboard: str = CLOCK_ONBOARD,
    clock_delivery: str = CLOCK_DELIVERY,
) -> dict:
    """A payer with its rate schedule, one credentialed clinician enrolled with
    it, and one VERIFIED patient insured by it. Overrides are passed through as
    dicts so callers can shape the geography, license type and window."""
    set_clock(clock_onboard)
    payer = make_payer(**(payer_kwargs or {}))
    rate = make_rate(payer["id"], **(rate_kwargs or {})) if rate_kwargs is not None else make_rate(payer["id"])
    attached = attach_billable_clinician(
        payer["id"], **(enrollment_kwargs or {}), **(clinician_kwargs or {})
    )
    patient = make_verified_patient(
        payer["id"], **(patient_kwargs or {}), verification=verification
    )
    if clock_delivery:
        set_clock(clock_delivery)
    return {
        "payer": payer,
        "rate": rate,
        "clinician": attached["clinician"],
        "license": attached["license"],
        "policy": attached["policy"],
        "enrollment": attached["enrollment"],
        "patient": patient,
    }


def two_enrollment_clinician(
    clock_onboard: str = CLOCK_ONBOARD,
    clinician_kwargs: dict | None = None,
) -> dict:
    """One credentialed clinician enrolled with two ACTIVE payers, so
    enrolled_payer_count is 2 and the posture is BILLABLE."""
    set_clock(clock_onboard)
    payer_pax = make_payer(payer_code="PAX", payer_name="Pacific Assurance Exchange")
    payer_mcr = make_payer(
        payer_code="MCR",
        payer_name="Meridian Care Review",
        delegated_credentialing=False,
        min_malpractice_coverage_cents=200_000_000,
        timely_filing_days=60,
        credentialing_sla_days=30,
    )
    make_rate(payer_pax["id"], rate_cents=15_000)
    make_rate(payer_mcr["id"], rate_cents=17_000)
    clinician = make_clinician(**(clinician_kwargs or {}))
    credential_clinician(clinician)
    enroll_pax = activate_enrollment(
        make_enrollment(clinician["id"], payer_pax["id"])["id"]
    )
    enroll_mcr = activate_enrollment(
        make_enrollment(clinician["id"], payer_mcr["id"], delegated=False)["id"]
    )
    clinician = get_clinician(clinician["id"])
    return {
        "clinician": clinician,
        "payer_pax": payer_pax,
        "payer_mcr": payer_mcr,
        "enroll_pax": enroll_pax,
        "enroll_mcr": enroll_mcr,
    }


# ─── Tier 3: full lifecycle shortcuts ─────────────────

def setup_completed_session(
    scheduled_start: str = "2026-06-16T14:00:00Z",
    scheduled_end: str = "2026-06-16T15:00:00Z",
    clock_delivery: str = CLOCK_DELIVERY,
    **scenario_kwargs,
) -> dict:
    """Everything needed for a COMPLETED, signed, UNBILLED session."""
    scenario = setup_billable_scenario_with_patient(clock_delivery=clock_delivery, **scenario_kwargs)
    clinician_id = scenario["clinician"]["id"]
    session = make_scheduled_session(
        clinician_id, scenario["patient"]["id"], scheduled_start, scheduled_end
    )
    add_signed_note(clinician_id, session["id"])
    session = complete_session(clinician_id, session["id"])
    scenario["session"] = session
    return scenario


def setup_claimed_session(
    scheduled_start: str = "2026-06-16T14:00:00Z",
    scheduled_end: str = "2026-06-16T15:00:00Z",
    **kwargs,
) -> dict:
    """A completed session with a SUBMITTED claim against it."""
    scenario = setup_completed_session(
        scheduled_start=scheduled_start, scheduled_end=scheduled_end, **kwargs
    )
    claim = submit_claim(scenario["session"]["id"])
    scenario["claim"] = claim
    return scenario


def setup_denied_claim(
    scheduled_start: str = "2026-06-16T14:00:00Z",
    scheduled_end: str = "2026-06-16T15:00:00Z",
    denial_code: str = "NOT_COVERED",
    clock_for_denial: str | None = None,
    **kwargs,
) -> dict:
    """A completed, billed session whose claim has been denied."""
    scenario = setup_claimed_session(
        scheduled_start=scheduled_start, scheduled_end=scheduled_end, **kwargs
    )
    if clock_for_denial:
        set_clock(clock_for_denial)
    scenario["claim"] = adjudicate(scenario["claim"]["id"], "DENIED", denial_code)
    return scenario


def setup_paid_claim(
    scheduled_start: str = "2026-06-16T14:00:00Z",
    scheduled_end: str = "2026-06-16T15:00:00Z",
    **kwargs,
) -> dict:
    scenario = setup_claimed_session(
        scheduled_start=scheduled_start, scheduled_end=scheduled_end, **kwargs
    )
    scenario["claim"] = adjudicate(scenario["claim"]["id"], "PAID")
    return scenario


# ─── Tier 4: batch / payout helpers ───────────────────

def open_and_lock_batch(
    period_start: str = "2026-06-01T00:00:00Z",
    period_end: str = "2026-06-08T00:00:00Z",
    schedule: str = "WEEKLY",
    lock: bool = True,
) -> dict:
    batch = get_success_data(
        api_client.create_payout_batch(
            create_payout_batch_payload(
                period_start=period_start, period_end=period_end, schedule=schedule
            ),
            OPS,
        ),
        201,
    )
    if lock:
        batch = get_success_data(api_client.lock_payout_batch(batch["id"], OPS))
    return batch


def _data(response) -> list:
    """List endpoints answer with response_type array; the payload is the list.

    `get_success_data` already unwraps the envelope and returns `body["data"]`,
    so the array itself is what comes back — indexing it again is a TypeError.
    """
    return get_success_data(response, 200)


def get_batch_lines(batch_id: str, params=None) -> list:
    return _data(api_client.list_payout_batch_lines(batch_id, OPS, params))


def get_clinician_payout_lines(clinician_id: str, params=None) -> list:
    return _data(api_client.list_clinician_payout_lines(clinician_id, OPS, params))


def get_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_payout_batch(batch_id, OPS))


def get_clinician(clinician_id: str) -> dict:
    return get_success_data(api_client.get_clinician(clinician_id, OPS))


def get_session(session_id: str) -> dict:
    return get_success_data(api_client.get_session(session_id, OPS))


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, OPS))


def get_patient(patient_id: str) -> dict:
    return get_success_data(api_client.get_patient(patient_id, OPS))


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_payer_enrollment(enrollment_id, OPS))


def get_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_continuity_plan(plan_id, OPS))


def get_note_rows(session_id: str, params=None) -> list:
    return _data(api_client.list_session_notes(session_id, OPS, params))


# ─── Instance-shaped composites ───────────────────────

def setup_four_session_two_batch_scenario() -> dict:
    """One billable clinician, two patients, four completed sessions across two
    windows, claims paid/denied/paid/denied, and two overlapping-free batches
    (WEEKLY for the first window, SEMIMONTHLY for the second)."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = make_clinician(
        availability_blocks=[
            {"weekday": 2, "start_minute": 480, "end_minute": 1080},
            {"weekday": 3, "start_minute": 480, "end_minute": 1080},
        ]
    )
    credential_clinician(clinician, license_number="LCSW-CA-90211")
    enrollment = activate_enrollment(
        make_enrollment(clinician["id"], payer["id"])["id"]
    )
    pat_a = make_verified_patient(payer["id"], full_name="Priya Anand", member_id="MBR-4410")
    pat_b = make_verified_patient(
        payer["id"],
        full_name="Marcus Cole",
        member_id="MBR-5182",
        verification={"deductible_remaining_cents": 40_000},
    )
    set_clock(CLOCK_DELIVERY)

    sessions = []
    for start, patient, narrative in [
        ("2026-06-02T14:00:00Z", pat_a, "Session one narrative covering presenting concern and treatment plan."),
        ("2026-06-03T14:00:00Z", pat_b, "Session two narrative covering cognitive restructuring work."),
        ("2026-06-16T14:00:00Z", pat_a, "Session three narrative covering progress review."),
        ("2026-06-17T14:00:00Z", pat_b, "Session four narrative covering relapse-prevention planning."),
    ]:
        end = shift_hours(start, 1)
        sessions.append(
            make_completed_session(clinician["id"], patient["id"], start, end, stripe_note=narrative)
        )

    claims = [submit_claim(s["id"]) for s in sessions]
    adjudicate(claims[0]["id"], "PAID")
    adjudicate(claims[1]["id"], "DENIED", "NOT_COVERED")
    adjudicate(claims[2]["id"], "PAID")
    adjudicate(claims[3]["id"], "DENIED", "NOT_COVERED")

    batch_b1 = open_and_lock_batch(
        "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY", lock=False
    )
    batch_b2 = open_and_lock_batch(
        "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", "SEMIMONTHLY", lock=False
    )
    return {
        "payer": payer,
        "clinician": clinician,
        "enrollment": enrollment,
        "pat_a": pat_a,
        "pat_b": pat_b,
        "sessions": sessions,
        "claims": claims,
        "batch_b1": batch_b1,
        "batch_b2": batch_b2,
    }


def setup_clinician_matched_to_two_patients(
    clock_offboard: str = "2026-06-25T00:00:00Z",
    availability_blocks=None,
    caseload_target: int = 8,
    current_session_patient: str = "b",
) -> dict:
    """A billable clinician whose availability is a single one-hour window,
    matched to two patients, holding one scheduled session that consumes the
    whole window (open_slot_count == 0)."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = make_clinician(
        weekly_caseload_target=caseload_target,
        availability_blocks=availability_blocks
        if availability_blocks is not None
        else [{"weekday": 2, "start_minute": 840, "end_minute": 900}],
    )
    credential_clinician(clinician)
    activate_enrollment(make_enrollment(clinician["id"], payer["id"])["id"])
    pat_a = make_verified_patient(payer["id"], full_name="Priya Anand", member_id="MBR-4410")
    pat_b = make_verified_patient(
        payer["id"],
        full_name="Marcus Cole",
        member_id="MBR-5182",
        verification={"deductible_remaining_cents": 40_000},
    )
    get_success_data(api_client.match_patient(pat_a["id"], {"specialty_tags": ["ANXIETY"]}, OPS))
    get_success_data(api_client.match_patient(pat_b["id"], {"specialty_tags": ["ANXIETY"]}, OPS))

    session_patient = pat_b if current_session_patient == "b" else pat_a
    session = make_scheduled_session(
        clinician["id"], session_patient["id"],
        "2026-06-23T14:00:00Z", "2026-06-23T15:00:00Z",
    )
    add_signed_note(clinician["id"], session["id"])
    session = get_session(session["id"])
    set_clock(clock_offboard)
    return {
        "payer": payer,
        "clinician": clinician,
        "pat_a": pat_a,
        "pat_b": pat_b,
        "session": session,
        "session_patient": session_patient,
    }