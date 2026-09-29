"""Composite setup helpers.

The server is restarted with an empty database before every individual test, so
every fixture here builds its world from scratch. The functions come in two
layers: granular single-step builders, and :func:`setup_baseline`, which walks
the canonical chain - clock, payer, patient, plan of care, submission,
authorization, activation, nurse, competencies, case, activation - in one call.

Setup calls go through ``get_success_data`` so a broken prerequisite surfaces as
a setup error rather than as a confusing assertion inside the test body.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    AGENCY_ADMIN,
    CASE_MANAGER,
    CLINICAL_SUPERVISOR,
    SCHEDULER,
    SUPERVISOR_USER_ID,
    make_nurse_headers,
    make_payer_reviewer_headers,
)
from .types import (
    BillingDecision,
    EvvMethod,
    Skill,
)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, to_iso8601: str = C.CLOCK_WEEK32_MONDAY_06) -> Dict[str, Any]:
    """Park the server's logical clock at `to_iso8601` (PRD 2.5)."""
    return get_success_data(api.set_clock(F.clock_payload(to_iso8601), AGENCY_ADMIN))


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def create_payer(api: ApiClient, **overrides) -> Dict[str, Any]:
    """Register the canonical payer, or a variant of it."""
    return get_success_data(api.create_payer(F.payer_payload(**overrides), AGENCY_ADMIN))


def create_patient(api: ApiClient, payer_id: str, **overrides) -> Dict[str, Any]:
    """Enrol the canonical trach + vent child under `payer_id`."""
    return get_success_data(
        api.create_patient(F.patient_payload(payer_id, **overrides), CASE_MANAGER)
    )


def create_plan_of_care(api: ApiClient, patient_id: str, **overrides) -> Dict[str, Any]:
    """Draft a plan of care for `patient_id`; it lands in DRAFT."""
    return get_success_data(
        api.create_plan_of_care(F.plan_of_care_payload(patient_id, **overrides), CASE_MANAGER)
    )


def submit_plan_of_care(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    """Submit a plan of care and return it, so the caller can read `version`."""
    return get_success_data(api.submit_plan_of_care(plan_id, CASE_MANAGER))


def create_submitted_plan_of_care(
    api: ApiClient, patient_id: str, **overrides
) -> Dict[str, Any]:
    """Draft and submit in one step; the returned row carries the version an
    authorization's `expected_plan_of_care_version` must match."""
    plan = create_plan_of_care(api, patient_id, **overrides)
    return submit_plan_of_care(api, plan["id"])


def create_authorization(
    api: ApiClient,
    plan_of_care_id: str,
    payer_id: str,
    expected_plan_of_care_version: int,
    **overrides,
) -> Dict[str, Any]:
    """Issue a PENDING authorization as the payer's reviewer."""
    return get_success_data(
        api.create_authorization(
            F.authorization_payload(
                plan_of_care_id, payer_id, expected_plan_of_care_version, **overrides
            ),
            make_payer_reviewer_headers(payer_id),
        )
    )


def activate_authorization(api: ApiClient, authorization_id: str, payer_id: str) -> Dict[str, Any]:
    """Move an authorization PENDING -> ACTIVE."""
    return get_success_data(
        api.activate_authorization(authorization_id, make_payer_reviewer_headers(payer_id))
    )


def register_nurse(api: ApiClient, **overrides) -> Dict[str, Any]:
    """Register a nurse; defaults to the canonical RN with a 48 h/wk ceiling."""
    return get_success_data(api.create_nurse(F.nurse_payload(**overrides), AGENCY_ADMIN))


def attest_competency(
    api: ApiClient, nurse_id: str, skill: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    """Attest one competency for a nurse."""
    return get_success_data(
        api.create_competency(
            nurse_id,
            F.competency_payload(skill, **overrides),
            headers or CLINICAL_SUPERVISOR,
        )
    )


def create_nurse_with_skills(
    api: ApiClient,
    skills: Sequence[str] = (Skill.TRACH.value, Skill.VENT.value),
    competency_overrides: Optional[Dict[str, Any]] = None,
    **nurse_overrides,
) -> Dict[str, Any]:
    """Register a nurse and attest every skill in `skills`."""
    nurse = register_nurse(api, **nurse_overrides)
    for skill in skills:
        attest_competency(api, nurse["id"], skill, **(competency_overrides or {}))
    return nurse


def open_case(
    api: ApiClient,
    patient_id: str,
    authorization_id: str,
    assigned_supervisor_user_id: str = SUPERVISOR_USER_ID,
    **overrides,
) -> Dict[str, Any]:
    """Open a case in PENDING_STAFFING."""
    return get_success_data(
        api.create_case(
            F.case_payload(patient_id, authorization_id, assigned_supervisor_user_id, **overrides),
            CASE_MANAGER,
        )
    )


def activate_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    """Move a case PENDING_STAFFING -> ACTIVE."""
    return get_success_data(api.activate_case(case_id, CASE_MANAGER))


# ---------------------------------------------------------------------------
# Shifts, assignments, visits
# ---------------------------------------------------------------------------
def publish_shift(
    api: ApiClient,
    case_id: str,
    start_at: str,
    end_at: str,
    required_skills: Optional[Sequence[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Publish an OPEN shift; both bounds are full ISO-8601 instants."""
    return get_success_data(
        api.create_shift(
            F.shift_payload(case_id, start_at, end_at, required_skills, **overrides), SCHEDULER
        )
    )


def shift_version(api: ApiClient, shift_id: str) -> int:
    """The shift's current `version`, for the OCC guard on assignment."""
    shift = get_success_data(api.get_shift(shift_id, SCHEDULER))
    return shift["version"]


def assign_nurse(
    api: ApiClient,
    shift_id: str,
    nurse_id: str,
    expected_shift_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Manually assign a nurse, reading the shift's live `version` unless the
    caller pins one deliberately."""
    version = (
        expected_shift_version
        if expected_shift_version is not None
        else shift_version(api, shift_id)
    )
    return get_success_data(
        api.create_assignment(F.assignment_payload(shift_id, nurse_id, version), SCHEDULER)
    )


def auto_staff(api: ApiClient, shift_id: str, expected_shift_version: Optional[int] = None):
    """Run the automatic selector against a shift."""
    version = (
        expected_shift_version
        if expected_shift_version is not None
        else shift_version(api, shift_id)
    )
    return get_success_data(
        api.auto_staff_shift(shift_id, F.auto_staff_payload(version), SCHEDULER)
    )


def cancel_assignment(api: ApiClient, assignment_id: str, note: str = "Schedule change"):
    """Cancel an ACTIVE assignment, returning its committed minutes."""
    return get_success_data(
        api.cancel_assignment(assignment_id, F.cancel_assignment_payload(note), SCHEDULER)
    )


def record_supervisory_visit(
    api: ApiClient,
    case_id: str,
    visit_at: str,
    outcome: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Record a supervisory visit, resetting the cadence clock for the case."""
    return get_success_data(
        api.create_supervisory_visit(
            case_id,
            F.supervisory_visit_payload(visit_at, outcome, **overrides),
            headers or CLINICAL_SUPERVISOR,
        )
    )


def file_incident(
    api: ApiClient,
    case_id: str,
    occurred_at: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """File an incident report against a case."""
    return get_success_data(
        api.create_incident_report(
            F.incident_payload(case_id, occurred_at, **overrides), headers or CLINICAL_SUPERVISOR
        )
    )


def close_incident(
    api: ApiClient,
    incident_id: str,
    patient_returned_home: bool,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Close an incident report, optionally bringing the child home."""
    return get_success_data(
        api.close_incident_report(
            incident_id,
            F.close_incident_payload(patient_returned_home, **overrides),
            headers or CLINICAL_SUPERVISOR,
        )
    )


# ---------------------------------------------------------------------------
# The visit: EVV, timesheets, billing
# ---------------------------------------------------------------------------
def timesheet_of_assignment(api: ApiClient, assignment_id: str, nurse_id: str) -> Dict[str, Any]:
    """The single timesheet reachable from an assignment."""
    rows = get_success_data(
        api.list_assignment_timesheets(assignment_id, make_nurse_headers(nurse_id))
    )
    assert rows, f"assignment {assignment_id} has no timesheet"
    return rows[0]


def clock_in(
    api: ApiClient,
    shift_id: str,
    nurse_id: str,
    at: Optional[str] = None,
    evv_method: str = EvvMethod.GPS.value,
    geo_verified: bool = True,
) -> Dict[str, Any]:
    """Clock in, first parking the clock at `at` when one is supplied. Returns
    whatever the endpoint answers with - clock-in opens the timesheet."""
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.clock_in(
            shift_id,
            F.clock_in_payload(evv_method, geo_verified),
            make_nurse_headers(nurse_id),
        )
    )


def clock_out(
    api: ApiClient, shift_id: str, nurse_id: str, at: Optional[str] = None
) -> Dict[str, Any]:
    """Clock out, first parking the clock at `at` when one is supplied."""
    if at is not None:
        set_clock(api, at)
    return get_success_data(api.clock_out(shift_id, {}, make_nurse_headers(nurse_id)))


def work_shift(
    api: ApiClient,
    shift_id: str,
    nurse_id: str,
    assignment_id: str,
    clock_in_at: str,
    clock_out_at: str,
    evv_method: str = EvvMethod.GPS.value,
    geo_verified: bool = True,
) -> Dict[str, Any]:
    """Clock in at one instant and out at another, then return the timesheet."""
    clock_in(api, shift_id, nurse_id, clock_in_at, evv_method, geo_verified)
    clock_out(api, shift_id, nurse_id, clock_out_at)
    return timesheet_of_assignment(api, assignment_id, nurse_id)


def submit_timesheet(api: ApiClient, timesheet_id: str) -> Dict[str, Any]:
    """Submit a timesheet for billing; submission belongs to the Scheduler."""
    return get_success_data(api.submit_timesheet(timesheet_id, SCHEDULER))


def accept_timesheet(api: ApiClient, timesheet_id: str, payer_id: str) -> Dict[str, Any]:
    """Record an ACCEPT billing decision as the payer's reviewer."""
    return get_success_data(
        api.billing_decision(
            timesheet_id,
            F.billing_decision_payload(BillingDecision.ACCEPT.value),
            make_payer_reviewer_headers(payer_id),
        )
    )


def reject_timesheet(
    api: ApiClient, timesheet_id: str, payer_id: str, reason: str = "Missing signature"
) -> Dict[str, Any]:
    """Record a REJECT billing decision as the payer's reviewer."""
    return get_success_data(
        api.billing_decision(
            timesheet_id,
            F.billing_decision_payload(BillingDecision.REJECT.value, reason),
            make_payer_reviewer_headers(payer_id),
        )
    )


def submit_and_accept_timesheet(api: ApiClient, timesheet_id: str, payer_id: str) -> Dict[str, Any]:
    """Submit then accept a timesheet, returning the accepted row."""
    submit_timesheet(api, timesheet_id)
    return accept_timesheet(api, timesheet_id, payer_id)


# ---------------------------------------------------------------------------
# The canonical baseline
# ---------------------------------------------------------------------------
@dataclass
class Baseline:
    """Everything the canonical setup chain produced, with threaded headers."""

    payer: Dict[str, Any]
    patient: Dict[str, Any]
    plan_of_care: Dict[str, Any]
    authorization: Dict[str, Any]
    nurse: Optional[Dict[str, Any]] = None
    case: Optional[Dict[str, Any]] = None
    payer_headers: Dict[str, str] = field(default_factory=dict)
    nurse_headers: Dict[str, str] = field(default_factory=dict)

    @property
    def payer_id(self) -> str:
        return self.payer["id"]

    @property
    def patient_id(self) -> str:
        return self.patient["id"]

    @property
    def plan_of_care_id(self) -> str:
        return self.plan_of_care["id"]

    @property
    def authorization_id(self) -> str:
        return self.authorization["id"]

    @property
    def nurse_id(self) -> str:
        assert self.nurse is not None, "this baseline has no nurse"
        return self.nurse["id"]

    @property
    def case_id(self) -> str:
        assert self.case is not None, "this baseline has no case"
        return self.case["id"]


def setup_baseline(
    api: ApiClient,
    clock: Optional[str] = C.CLOCK_WEEK32_MONDAY_06,
    payer_overrides: Optional[Dict[str, Any]] = None,
    patient_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
    authorization_overrides: Optional[Dict[str, Any]] = None,
    activate_authorization_after_create: bool = True,
    with_nurse: bool = True,
    nurse_overrides: Optional[Dict[str, Any]] = None,
    nurse_skills: Sequence[str] = (Skill.TRACH.value, Skill.VENT.value),
    with_case: bool = True,
    case_overrides: Optional[Dict[str, Any]] = None,
    continuity_nurse: bool = True,
    activate_case_after_open: bool = True,
) -> Baseline:
    """Walk the canonical chain and return every row it created.

    The clock is parked first, at Monday 06:00Z of ISO week 32 of 2026 by
    default, so that weekly aggregates land inside the window under test.
    """
    if clock is not None:
        set_clock(api, clock)

    payer = create_payer(api, **(payer_overrides or {}))
    patient = create_patient(api, payer["id"], **(patient_overrides or {}))
    plan = create_submitted_plan_of_care(api, patient["id"], **(plan_overrides or {}))
    authorization = create_authorization(
        api, plan["id"], payer["id"], plan["version"], **(authorization_overrides or {})
    )
    if activate_authorization_after_create:
        authorization = activate_authorization(api, authorization["id"], payer["id"])

    nurse = None
    if with_nurse:
        nurse = create_nurse_with_skills(api, nurse_skills, **(nurse_overrides or {}))

    case = None
    if with_case:
        overrides: Dict[str, Any] = dict(case_overrides or {})
        if continuity_nurse and nurse is not None and "continuity_nurse_id" not in overrides:
            overrides["continuity_nurse_id"] = nurse["id"]
        case = open_case(api, patient["id"], authorization["id"], **overrides)
        if activate_case_after_open:
            case = activate_case(api, case["id"])

    return Baseline(
        payer=payer,
        patient=patient,
        plan_of_care=plan,
        authorization=authorization,
        nurse=nurse,
        case=case,
        payer_headers=make_payer_reviewer_headers(payer["id"]),
        nurse_headers=make_nurse_headers(nurse["id"]) if nurse else {},
    )


def refresh_authorization(api: ApiClient, baseline: Baseline) -> Dict[str, Any]:
    """Re-read the baseline's authorization as its payer reviewer."""
    return get_success_data(
        api.get_authorization(baseline.authorization_id, baseline.payer_headers)
    )


def refresh_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    """Re-read a case as its case manager."""
    return get_success_data(api.get_case(case_id, CASE_MANAGER))


def refresh_shift(api: ApiClient, shift_id: str) -> Dict[str, Any]:
    """Re-read a shift as the scheduler."""
    return get_success_data(api.get_shift(shift_id, SCHEDULER))


def refresh_nurse(api: ApiClient, nurse_id: str) -> Dict[str, Any]:
    """Re-read a nurse as the agency admin."""
    return get_success_data(api.get_nurse(nurse_id, AGENCY_ADMIN))


def refresh_timesheet(api: ApiClient, timesheet_id: str) -> Dict[str, Any]:
    """Re-read a timesheet as the scheduler."""
    return get_success_data(api.get_timesheet(timesheet_id, SCHEDULER))


def utilization(
    api: ApiClient,
    baseline: Baseline,
    basis: Optional[str] = None,
    week_of: Optional[str] = None,
) -> Dict[str, Any]:
    """Read a utilization figure for the baseline's authorization."""
    return get_success_data(
        api.get_utilization(
            baseline.authorization_id,
            baseline.payer_headers,
            F.utilization_params(basis, week_of),
        )
    )
