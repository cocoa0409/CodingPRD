"""Composite setup helpers.

Every helper drives the public API only — there is no back door into the
server's state. Helpers are *phased*: each one performs the smallest useful
sequence of hops and re-reads any revision counter it is about to spend, so
that reusing a helper can never invalidate its own earlier hop.

The canonical world every helper builds from:

  * a `PayerPlan` "Meridian PPO" — both benefit channels, `PREFER_AMBULATORY`,
    17.5 percent coinsurance, 100000 cents of deductible left, a 12500 cent
    facility fee, 2 appeal rounds and a 180 day authorization window,
  * a `Drug` "Infliximab" — IV, TNFI, 250050 cents, 150 minutes of chair time,
    a `CMP` panel every 90 days,
  * an `InfusionChair` at an `AMBULATORY_INFUSION_CENTER` with a 30 minute
    turnover buffer,
  * a credentialed `RHEUMATOLOGIST` and a `NURSE`,
  * a consenting patient whose TB and HBV screens all resulted 2026-07-21.

Because the plan requires step therapy in `TNFI` and the canonical drug *is*
`TNFI`, the required-class set is empty for the canonical world: step therapy
is vacuously satisfied and the happy path needs no prior exposure.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import CLOCK_DEFAULT, instant
from .factories import (
    adalimumab_payload,
    approve_determination_payload,
    create_appointment_payload,
    create_assistance_enrollment_payload,
    create_authorization_payload,
    create_clinician_payload,
    create_infusion_chair_payload,
    create_monitoring_lab_payload,
    create_nurse_payload,
    create_patient_payload,
    create_screening_record_payload,
    create_therapy_episode_payload,
    create_visit_payload,
    infliximab_payload,
    meridian_plan_payload,
)
from .test_users import (
    COUNSELOR_ALPHA_USER_ID,
    COUNSELOR_BETA_USER_ID,
    make_benefits_counselor_headers,
    make_infusion_nurse_headers,
    make_patient_headers,
    make_payer_reviewer_headers,
    make_prior_auth_coordinator_headers,
    make_registry_admin_headers,
    make_rheumatologist_headers,
)

# Headers that need no entity behind them.
ADMIN = make_registry_admin_headers()
COORDINATOR = make_prior_auth_coordinator_headers()
REVIEWER = make_payer_reviewer_headers()
COUNSELOR = make_benefits_counselor_headers(COUNSELOR_ALPHA_USER_ID)
COUNSELOR_TWO = make_benefits_counselor_headers(COUNSELOR_BETA_USER_ID)

# The three screens that together clear both postures for a new patient.
CLEARING_SCREENS = (
    ("TB_IGRA", "NEGATIVE"),
    ("HBV_SURFACE_AG", "NEGATIVE"),
    ("HBV_CORE_AB", "NEGATIVE"),
)


@dataclass
class Scenario:
    """A mutable bag of ids and last-read bodies, threaded through the helpers."""

    rheumatologist_id: str = ""
    nurse_id: str = ""
    drug_id: str = ""
    plan_id: str = ""
    chair_id: str = ""
    patient_id: str = ""
    episode_id: str = ""
    authorization_id: str = ""
    appointment_id: str = ""
    enrollment_id: str = ""
    visit_id: str = ""

    clinician: Dict[str, Any] = field(default_factory=dict)
    nurse: Dict[str, Any] = field(default_factory=dict)
    drug: Dict[str, Any] = field(default_factory=dict)
    plan: Dict[str, Any] = field(default_factory=dict)
    chair: Dict[str, Any] = field(default_factory=dict)
    patient: Dict[str, Any] = field(default_factory=dict)
    episode: Dict[str, Any] = field(default_factory=dict)
    authorization: Dict[str, Any] = field(default_factory=dict)
    appointment: Dict[str, Any] = field(default_factory=dict)
    enrollment: Dict[str, Any] = field(default_factory=dict)
    visit: Dict[str, Any] = field(default_factory=dict)
    appointments: List[Dict[str, Any]] = field(default_factory=list)

    # ---------------- role headers bound to the scenario's own entities ----
    @property
    def rheum_headers(self) -> Dict[str, str]:
        return make_rheumatologist_headers(self.rheumatologist_id)

    @property
    def nurse_headers(self) -> Dict[str, str]:
        return make_infusion_nurse_headers(self.nurse_id)

    @property
    def patient_headers(self) -> Dict[str, str]:
        return make_patient_headers(self.patient_id)

    @property
    def admin_headers(self) -> Dict[str, str]:
        return ADMIN

    @property
    def coordinator_headers(self) -> Dict[str, str]:
        return COORDINATOR

    @property
    def reviewer_headers(self) -> Dict[str, str]:
        return REVIEWER

    @property
    def counselor_headers(self) -> Dict[str, str]:
        return COUNSELOR

    @property
    def second_counselor_headers(self) -> Dict[str, str]:
        return COUNSELOR_TWO

    # ---------------- fresh reads (never trust a cached revision) ----------
    def refresh_patient(self) -> Dict[str, Any]:
        self.patient = get_success_data(api_client.get_patient(self.patient_id, ADMIN))
        return self.patient

    def refresh_episode(self) -> Dict[str, Any]:
        self.episode = get_success_data(api_client.get_therapy_episode(self.episode_id, ADMIN))
        return self.episode

    def refresh_authorization(self, authorization_id: Optional[str] = None) -> Dict[str, Any]:
        target = authorization_id or self.authorization_id
        data = get_success_data(api_client.get_authorization(target, ADMIN))
        if target == self.authorization_id:
            self.authorization = data
        return data

    def refresh_appointment(self, appointment_id: Optional[str] = None) -> Dict[str, Any]:
        target = appointment_id or self.appointment_id
        data = get_success_data(api_client.get_infusion_appointment(target, ADMIN))
        if target == self.appointment_id:
            self.appointment = data
        return data

    def refresh_enrollment(self, enrollment_id: Optional[str] = None) -> Dict[str, Any]:
        target = enrollment_id or self.enrollment_id
        data = get_success_data(api_client.get_assistance_enrollment(target, ADMIN))
        if target == self.enrollment_id:
            self.enrollment = data
        return data

    @property
    def patient_version(self) -> int:
        return self.refresh_patient()["version"]

    @property
    def episode_version(self) -> int:
        return self.refresh_episode()["version"]


# --------------------------------------------------------------------------
# Logical clock (PRD §2.11)
# --------------------------------------------------------------------------
def set_clock(current_utc: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Park the logical clock. Every deadline rule reads it, so any test that
    asserts a windowed outcome parks it explicitly rather than relying on the
    2026-08-01T00:00:00Z default."""
    return get_success_data(api_client.set_clock(current_utc, headers or ADMIN))


# --------------------------------------------------------------------------
# Reference data (PRD §3.1)
# --------------------------------------------------------------------------
def create_clinician(scenario: Optional[Scenario] = None, **overrides) -> Dict[str, Any]:
    data = get_success_data(
        api_client.create_clinician(create_clinician_payload(**overrides), ADMIN), 201
    )
    if scenario is not None:
        scenario.clinician = data
        scenario.rheumatologist_id = data["id"]
    return data


def create_nurse(scenario: Optional[Scenario] = None, **overrides) -> Dict[str, Any]:
    data = get_success_data(
        api_client.create_clinician(create_nurse_payload(**overrides), ADMIN), 201
    )
    if scenario is not None:
        scenario.nurse = data
        scenario.nurse_id = data["id"]
    return data


def create_drug(scenario: Optional[Scenario] = None, payload: Optional[dict] = None) -> Dict[str, Any]:
    data = get_success_data(
        api_client.create_drug(payload if payload is not None else infliximab_payload(), ADMIN), 201
    )
    if scenario is not None:
        scenario.drug = data
        scenario.drug_id = data["id"]
    return data


def create_plan(scenario: Optional[Scenario] = None, payload: Optional[dict] = None) -> Dict[str, Any]:
    data = get_success_data(
        api_client.create_payer_plan(
            payload if payload is not None else meridian_plan_payload(), ADMIN
        ),
        201,
    )
    if scenario is not None:
        scenario.plan = data
        scenario.plan_id = data["id"]
    return data


def create_chair(scenario: Optional[Scenario] = None, payload: Optional[dict] = None) -> Dict[str, Any]:
    data = get_success_data(
        api_client.create_infusion_chair(
            payload if payload is not None else create_infusion_chair_payload(), ADMIN
        ),
        201,
    )
    if scenario is not None:
        scenario.chair = data
        scenario.chair_id = data["id"]
    return data


def register_patient(scenario: Optional[Scenario] = None, **overrides) -> Dict[str, Any]:
    data = get_success_data(
        api_client.create_patient(create_patient_payload(**overrides), ADMIN), 201
    )
    if scenario is not None:
        scenario.patient = data
        scenario.patient_id = data["id"]
    return data


def bootstrap_reference(
    drug_payload: Optional[dict] = None,
    plan_payload: Optional[dict] = None,
    chair_payload: Optional[dict] = None,
    clinician_overrides: Optional[dict] = None,
) -> Scenario:
    """The canonical world: rheumatologist, nurse, drug, plan and one chair."""
    scenario = Scenario()
    create_clinician(scenario, **(clinician_overrides or {}))
    create_nurse(scenario)
    create_drug(scenario, drug_payload)
    create_plan(scenario, plan_payload)
    create_chair(scenario, chair_payload)
    return scenario


# --------------------------------------------------------------------------
# Screening (PRD §3.3)
# --------------------------------------------------------------------------
def file_screen(
    scenario: Scenario,
    screen_type: str,
    result: str,
    **overrides,
) -> Dict[str, Any]:
    """File one screening record as the nurse; the patient's postures and
    `version` are recomputed by the server on every filing."""
    payload = create_screening_record_payload(
        scenario.patient_id, screen_type, result, **overrides
    )
    return get_success_data(
        api_client.create_screening_record(payload, scenario.nurse_headers), 201
    )


def file_clearing_screens(scenario: Scenario, **overrides) -> List[Dict[str, Any]]:
    """A negative TB IGRA plus a negative surface antigen and core antibody —
    the minimum that clears both postures for activation."""
    return [
        file_screen(scenario, screen_type, result, **overrides)
        for screen_type, result in CLEARING_SCREENS
    ]


def screened_patient(scenario: Scenario, **patient_overrides) -> Dict[str, Any]:
    """Register a patient and clear both screening postures."""
    register_patient(scenario, **patient_overrides)
    file_clearing_screens(scenario)
    return scenario.refresh_patient()


# --------------------------------------------------------------------------
# Therapy episodes (PRD §3.4)
# --------------------------------------------------------------------------
def open_planned_episode(scenario: Scenario, **overrides) -> Dict[str, Any]:
    """Open an episode, spending a freshly read `expected_patient_version`.

    The three body references default to the scenario's own reference data but
    are overridable by name, so a caller that needs a second molecule can pass
    `drug_id=...` without colliding with the positional default.
    """
    patient_id = overrides.pop("patient_id", None) or scenario.patient_id
    drug_id = overrides.pop("drug_id", None) or scenario.drug_id
    payer_plan_id = overrides.pop("payer_plan_id", None) or scenario.plan_id
    expected_version = overrides.pop("expected_patient_version", None)
    if expected_version is None:
        expected_version = scenario.patient_version
    payload = create_therapy_episode_payload(
        patient_id,
        drug_id,
        payer_plan_id,
        expected_version,
        **overrides,
    )
    data = get_success_data(
        api_client.create_therapy_episode(payload, scenario.rheum_headers), 201
    )
    scenario.episode = data
    scenario.episode_id = data["id"]
    return data


def file_monitoring_lab(scenario: Scenario, episode_id: Optional[str] = None, **overrides) -> Dict[str, Any]:
    """File one monitoring panel as the nurse. Every filing refreshes the
    episode's `monitoring_status` and bumps its `version`."""
    payload = create_monitoring_lab_payload(episode_id or scenario.episode_id, **overrides)
    return get_success_data(
        api_client.create_monitoring_lab(payload, scenario.nurse_headers), 201
    )


def make_monitoring_current(scenario: Scenario, **overrides) -> Dict[str, Any]:
    """File a benign `CMP` panel so the episode reads `CURRENT`. Callers that
    have moved the clock pass `collected_at` explicitly."""
    return file_monitoring_lab(scenario, **overrides)


# --------------------------------------------------------------------------
# Authorizations (PRD §3.5)
# --------------------------------------------------------------------------
def open_authorization(
    scenario: Scenario,
    requested_units: int = 6,
    episode_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Open a DRAFT authorization, spending a freshly read episode revision.

    Filing a monitoring panel or any other episode-touching hop bumps the
    episode's `version`, so the token is always re-read here rather than
    carried over from an earlier helper.
    """
    target = episode_id or scenario.episode_id
    expected = get_success_data(api_client.get_therapy_episode(target, ADMIN))["version"]
    payload = create_authorization_payload(target, expected, requested_units, **overrides)
    data = get_success_data(api_client.create_authorization(payload, COORDINATOR), 201)
    scenario.authorization = data
    scenario.authorization_id = data["id"]
    return data


def submit_authorization(scenario: Scenario, authorization_id: Optional[str] = None) -> Dict[str, Any]:
    target = authorization_id or scenario.authorization_id
    data = get_success_data(api_client.submit_authorization(target, COORDINATOR))
    if target == scenario.authorization_id:
        scenario.authorization = data
    return data


def approve_authorization(
    scenario: Scenario,
    authorization_id: Optional[str] = None,
    **determination_overrides,
) -> Dict[str, Any]:
    target = authorization_id or scenario.authorization_id
    payload = approve_determination_payload(**determination_overrides)
    data = get_success_data(api_client.determine_authorization(target, payload, REVIEWER))
    if target == scenario.authorization_id:
        scenario.authorization = data
    return data


def deny_authorization(
    scenario: Scenario,
    authorization_id: Optional[str] = None,
    decision_reason: str = "MEDICAL_NECESSITY_NOT_ESTABLISHED",
) -> Dict[str, Any]:
    target = authorization_id or scenario.authorization_id
    payload = {"decision": "DENIED", "decision_reason": decision_reason}
    data = get_success_data(api_client.determine_authorization(target, payload, REVIEWER))
    if target == scenario.authorization_id:
        scenario.authorization = data
    return data


def approved_authorization(
    scenario: Scenario,
    requested_units: int = 6,
    **determination_overrides,
) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED -> APPROVED in one hop, leaving funding AUTHORIZED."""
    open_authorization(scenario, requested_units)
    submit_authorization(scenario)
    return approve_authorization(scenario, **determination_overrides)


# --------------------------------------------------------------------------
# Activation (PRD §3.4)
# --------------------------------------------------------------------------
def activate_episode(scenario: Scenario, episode_id: Optional[str] = None) -> Dict[str, Any]:
    target = episode_id or scenario.episode_id
    data = get_success_data(
        api_client.activate_therapy_episode(target, scenario.rheum_headers)
    )
    if target == scenario.episode_id:
        scenario.episode = data
    return data


def active_episode(
    drug_payload: Optional[dict] = None,
    plan_payload: Optional[dict] = None,
    chair_payload: Optional[dict] = None,
    requested_units: int = 6,
    lab_overrides: Optional[dict] = None,
    episode_overrides: Optional[dict] = None,
    determination_overrides: Optional[dict] = None,
) -> Scenario:
    """The most reused preamble: an ACTIVE, AUTHORIZED, monitoring-CURRENT
    episode for a screened patient, with an APPROVED authorization holding
    `requested_units` units and an OPEN chair at the matching site.

    The hops run in dependency order: reference data, patient, screens,
    episode, monitoring panel (which needs the episode and bumps its
    revision), authorization (which re-reads that revision), approval, and
    only then activation, whose gates all read the state built above.
    """
    scenario = bootstrap_reference(drug_payload, plan_payload, chair_payload)
    screened_patient(scenario)
    open_planned_episode(scenario, **(episode_overrides or {}))
    make_monitoring_current(scenario, **(lab_overrides or {}))
    approved_authorization(scenario, requested_units, **(determination_overrides or {}))
    activate_episode(scenario)
    return scenario


def planned_episode(
    drug_payload: Optional[dict] = None,
    plan_payload: Optional[dict] = None,
    chair_payload: Optional[dict] = None,
    episode_overrides: Optional[dict] = None,
) -> Scenario:
    """Reference data plus a screened patient and one PLANNED episode."""
    scenario = bootstrap_reference(drug_payload, plan_payload, chair_payload)
    screened_patient(scenario)
    open_planned_episode(scenario, **(episode_overrides or {}))
    return scenario


# --------------------------------------------------------------------------
# Assistance enrollments (PRD §3.8)
# --------------------------------------------------------------------------
def submit_enrollment(
    scenario: Scenario,
    episode_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Submit an enrollment as counselor *alpha*."""
    payload = create_assistance_enrollment_payload(
        episode_id or scenario.episode_id, **overrides
    )
    data = get_success_data(api_client.create_assistance_enrollment(payload, COUNSELOR), 201)
    scenario.enrollment = data
    scenario.enrollment_id = data["id"]
    return data


def attest_enrollment(scenario: Scenario, enrollment_id: Optional[str] = None) -> Dict[str, Any]:
    """Attest as counselor *beta* — a different `X-User-ID` from the submitter,
    which the segregation-of-duties rule requires."""
    target = enrollment_id or scenario.enrollment_id
    data = get_success_data(api_client.attest_enrollment(target, COUNSELOR_TWO))
    if target == scenario.enrollment_id:
        scenario.enrollment = data
    return data


def active_enrollment(
    scenario: Scenario,
    episode_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Submit under one counselor identity and attest under a second, leaving
    the enrollment ACTIVE and therefore visible to the assistance selector."""
    submitted = submit_enrollment(scenario, episode_id, **overrides)
    return attest_enrollment(scenario, submitted["id"])


# --------------------------------------------------------------------------
# Infusion appointments (PRD §3.7)
# --------------------------------------------------------------------------
def schedule_appointment(
    scenario: Scenario,
    scheduled_start: Optional[str] = None,
    chair_id: Optional[str] = None,
    episode_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = create_appointment_payload(
        episode_id or scenario.episode_id,
        chair_id or scenario.chair_id,
        **overrides,
    )
    if scheduled_start is not None:
        payload["scheduled_start"] = scheduled_start
    data = get_success_data(
        api_client.create_infusion_appointment(payload, scenario.nurse_headers), 201
    )
    scenario.appointment = data
    scenario.appointment_id = data["id"]
    scenario.appointments.append(data)
    return data


def administer_appointment(scenario: Scenario, appointment_id: Optional[str] = None) -> Dict[str, Any]:
    target = appointment_id or scenario.appointment_id
    data = get_success_data(api_client.administer_appointment(target, scenario.nurse_headers))
    if target == scenario.appointment_id:
        scenario.appointment = data
    return data


def cancel_appointment(
    scenario: Scenario,
    appointment_id: Optional[str] = None,
    cancellation_reason: str = "PATIENT_REQUEST",
) -> Dict[str, Any]:
    target = appointment_id or scenario.appointment_id
    data = get_success_data(
        api_client.cancel_appointment(
            target, {"cancellation_reason": cancellation_reason}, scenario.nurse_headers
        )
    )
    if target == scenario.appointment_id:
        scenario.appointment = data
    return data


def reverse_administration(
    scenario: Scenario,
    appointment_id: Optional[str] = None,
    reversal_reason: str = "DOCUMENTATION_ERROR",
) -> Dict[str, Any]:
    target = appointment_id or scenario.appointment_id
    data = get_success_data(
        api_client.reverse_administration(
            target, {"reversal_reason": reversal_reason}, scenario.nurse_headers
        )
    )
    if target == scenario.appointment_id:
        scenario.appointment = data
    return data


def scheduled_dose(
    scheduled_start: str = instant(2026, 8, 12, 9, 0, 0),
    requested_units: int = 6,
    **active_kwargs,
) -> Scenario:
    """An ACTIVE episode with one SCHEDULED dose in the chair and no assistance."""
    scenario = active_episode(requested_units=requested_units, **active_kwargs)
    schedule_appointment(scenario, scheduled_start)
    return scenario


# --------------------------------------------------------------------------
# Visits (PRD §3.2)
# --------------------------------------------------------------------------
def book_visit(
    scenario: Scenario,
    visit_datetime: Optional[str] = None,
    visit_type: str = "FOLLOW_UP",
    patient_id: Optional[str] = None,
    clinician_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = create_visit_payload(
        patient_id or scenario.patient_id,
        clinician_id or scenario.rheumatologist_id,
        visit_type=visit_type,
        **overrides,
    )
    if visit_datetime is not None:
        payload["visit_datetime"] = visit_datetime
    data = get_success_data(api_client.create_visit(payload, scenario.rheum_headers), 201)
    scenario.visit = data
    scenario.visit_id = data["id"]
    return data


def check_in_visit(scenario: Scenario, visit_id: Optional[str] = None) -> Dict[str, Any]:
    target = visit_id or scenario.visit_id
    data = get_success_data(api_client.check_in_visit(target, scenario.nurse_headers))
    if target == scenario.visit_id:
        scenario.visit = data
    return data


def checked_in_visit(
    scenario: Scenario,
    visit_datetime: Optional[str] = None,
    visit_type: str = "FOLLOW_UP",
    **overrides,
) -> Dict[str, Any]:
    """Book a visit and check the patient in — the prerequisite for scoring."""
    booked = book_visit(scenario, visit_datetime, visit_type, **overrides)
    return check_in_visit(scenario, booked["id"])


def score_visit(scenario: Scenario, payload: dict, visit_id: Optional[str] = None) -> Dict[str, Any]:
    """Score as the visit's own clinician — scoring is ownership-gated."""
    target = visit_id or scenario.visit_id
    data = get_success_data(
        api_client.score_visit(target, payload, scenario.rheum_headers)
    )
    if target == scenario.visit_id:
        scenario.visit = data
    return data


def visit_ready_practice() -> Scenario:
    """Reference data plus a consenting patient — enough to book and score."""
    scenario = bootstrap_reference()
    register_patient(scenario)
    return scenario


# --------------------------------------------------------------------------
# Step-therapy history (PRD §3.5)
# --------------------------------------------------------------------------
def discontinued_trial_episode(
    scenario: Scenario,
    drug_payload: dict,
    discontinuation_reason: str = "INTOLERANCE",
) -> Dict[str, Any]:
    """Give the scenario's patient a DISCONTINUED episode on `drug_payload`'s
    molecule class, so that class counts towards the satisfied step-therapy
    set. `INTOLERANCE` qualifies on any exposure, so this helper never has to
    activate the episode or advance the clock.

    Call this *before* opening the episode under test: opening any episode
    supersedes the patient's other `PLANNED` episodes, and a `SUPERSEDED`
    discontinuation never counts as a trial.
    """
    trial_drug = create_drug(None, drug_payload)
    payload = create_therapy_episode_payload(
        scenario.patient_id, trial_drug["id"], scenario.plan_id, scenario.patient_version
    )
    trial = get_success_data(
        api_client.create_therapy_episode(payload, scenario.rheum_headers), 201
    )
    return get_success_data(
        api_client.discontinue_therapy_episode(
            trial["id"],
            {"discontinuation_reason": discontinuation_reason},
            scenario.rheum_headers,
        )
    )


# --------------------------------------------------------------------------
# Deferred sweep (PRD §2.11)
# --------------------------------------------------------------------------
def run_sweep() -> Dict[str, Any]:
    return get_success_data(api_client.run_reauthorization_calendar(ADMIN))
