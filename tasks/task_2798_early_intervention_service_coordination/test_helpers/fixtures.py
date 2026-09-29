"""
Composite state builders.

Every individual test starts against an empty database, so all state is built
from scratch through the public API. The builders below are layered: each stage
calls the stage beneath it and forwards keyword overrides, so a test that needs a
case in active services with one speech-therapy line calls one function, while a
test that needs the same case with a different child date of birth, county,
interpreter flag or service rate passes overrides into the same call.

Layering, from the front door outwards:

  1. ``build_intake``               clock, coordinator, child, open case
  2. ``build_assigned``             coordinator assigned to the case
  3. ``build_assessments_scheduled``  evaluation and family assessment scheduled
  4. ``build_assessments_completed``  both completed, clock advanced
  5. ``build_ifsp_pending``         eligibility determined, entry ratings recorded
  6. ``build_plan_with_line``       plan authored with one service line
  7. ``build_active_services``      parental consent recorded, services started
  8. ``build_authorized``           provider registered and authorized
  9. ``build_visit_scheduled``      one session scheduled
 10. ``build_visit_delivered``      that session documented as delivered

Each stage returns the same ``Case`` record, progressively filled in.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient, api_client
from .test_users import (
    ADMIN_HEADERS,
    EVALUATOR_HEADERS,
    FISCAL_HEADERS,
    INTAKE_HEADERS,
    make_family_representative_headers,
    make_provider_headers,
    make_service_coordinator_headers,
)

# The intake instant every canonical chain starts from, and the instant it
# advances to once the evaluation work has been completed.
INTAKE_CLOCK = "2026-03-02T09:00:00Z"
POST_EVALUATION_CLOCK = "2026-03-20T09:00:00Z"


@dataclass
class Case:
    """Identifiers and headers accumulated while building one case."""

    clock: str = INTAKE_CLOCK
    child_id: Optional[str] = None
    coordinator_id: Optional[str] = None
    referral_id: Optional[str] = None
    eval_id: Optional[str] = None
    fam_id: Optional[str] = None
    ifsp_id: Optional[str] = None
    line_id: Optional[str] = None
    provider_id: Optional[str] = None
    authorization_id: Optional[str] = None
    visit_id: Optional[str] = None
    cost_share_id: Optional[str] = None
    transition_plan_id: Optional[str] = None
    line_ids: List[str] = field(default_factory=list)
    provider_ids: List[str] = field(default_factory=list)
    authorization_ids: List[str] = field(default_factory=list)
    visit_ids: List[str] = field(default_factory=list)
    child_ids: List[str] = field(default_factory=list)
    coordinator_ids: List[str] = field(default_factory=list)
    referral_ids: List[str] = field(default_factory=list)

    @property
    def coordinator_headers(self) -> Dict[str, str]:
        assert self.coordinator_id, "No coordinator on this case yet"
        return make_service_coordinator_headers(self.coordinator_id)

    @property
    def family_headers(self) -> Dict[str, str]:
        assert self.child_id, "No child on this case yet"
        return make_family_representative_headers(self.child_id)

    @property
    def provider_headers(self) -> Dict[str, str]:
        assert self.provider_id, "No provider on this case yet"
        return make_provider_headers(self.provider_id)


# ─── Tier 1: single-call step helpers ─────────────────────────────────

def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    """Advance the logical clock; every chain sets it before anything else."""
    return get_success_data(api.set_clock(f.clock_payload(instant), ADMIN_HEADERS))


def create_child(api: ApiClient, **overrides: Any) -> str:
    data = get_success_data(
        api.create_child(f.child_payload(**overrides), INTAKE_HEADERS)
    )
    return data["id"]


def create_coordinator(api: ApiClient, **overrides: Any) -> str:
    data = get_success_data(
        api.create_coordinator(f.coordinator_payload(**overrides), ADMIN_HEADERS)
    )
    return data["id"]


def create_referral(api: ApiClient, child_id: str, **overrides: Any) -> str:
    data = get_success_data(
        api.create_referral(f.referral_payload(child_id, **overrides), INTAKE_HEADERS)
    )
    return data["id"]


def assign_coordinator(
    api: ApiClient, referral_id: str, coordinator_id: Optional[str] = None
) -> Dict[str, Any]:
    payload = (
        f.assign_coordinator_payload(coordinator_id=coordinator_id)
        if coordinator_id is not None
        else f.assign_coordinator_payload()
    )
    return get_success_data(api.assign_coordinator(referral_id, payload, ADMIN_HEADERS))


def schedule_assessment(api: ApiClient, referral_id: str, **overrides: Any) -> str:
    data = get_success_data(
        api.create_assessment(
            f.assessment_payload(referral_id, **overrides), EVALUATOR_HEADERS
        )
    )
    return data["id"]


def complete_assessment(
    api: ApiClient, assessment_id: str, completion_date: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_assessment(
            assessment_id,
            f.complete_assessment_payload(completion_date, **overrides),
            EVALUATOR_HEADERS,
        )
    )


def determine_eligibility(api: ApiClient, referral_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.record_eligibility_determination(
            referral_id, f.eligibility_determination_payload(**overrides), ADMIN_HEADERS
        )
    )


def record_entry_outcomes(api: ApiClient, referral_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.record_entry_outcomes(
            referral_id, f.entry_outcomes_payload(**overrides), EVALUATOR_HEADERS
        )
    )


def referral_version(api: ApiClient, referral_id: str) -> int:
    """Read the case version for the optimistic concurrency guard."""
    return get_success_data(api.get_referral(referral_id, ADMIN_HEADERS))["version"]


def author_ifsp(
    api: ApiClient, referral_id: str, coordinator_id: str, **overrides: Any
) -> str:
    version = overrides.pop("expected_referral_version", None)
    if version is None:
        version = referral_version(api, referral_id)
    data = get_success_data(
        api.create_ifsp(
            f.ifsp_payload(referral_id, coordinator_id, version, **overrides),
            ADMIN_HEADERS,
        )
    )
    return data["id"]


def add_service_line(api: ApiClient, ifsp_id: str, **overrides: Any) -> str:
    data = get_success_data(
        api.create_ifsp_service(f.ifsp_service_payload(ifsp_id, **overrides), ADMIN_HEADERS)
    )
    return data["id"]


def record_consent(api: ApiClient, ifsp_id: str, child_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.record_consent(
            ifsp_id,
            f.consent_payload(**overrides),
            make_family_representative_headers(child_id),
        )
    )


def create_provider(api: ApiClient, **overrides: Any) -> str:
    data = get_success_data(
        api.create_provider(f.provider_payload(**overrides), ADMIN_HEADERS)
    )
    return data["id"]


def create_authorization(
    api: ApiClient, line_id: str, provider_id: str, **overrides: Any
) -> str:
    data = get_success_data(
        api.create_authorization(
            f.authorization_payload(line_id, provider_id, **overrides), ADMIN_HEADERS
        )
    )
    return data["id"]


def schedule_visit(
    api: ApiClient,
    authorization_id: str,
    scheduled_start: str,
    scheduled_end: str,
    scheduler_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> str:
    data = get_success_data(
        api.create_visit(
            f.visit_payload(authorization_id, scheduled_start, scheduled_end, **overrides),
            scheduler_headers or ADMIN_HEADERS,
        )
    )
    return data["id"]


def document_visit(
    api: ApiClient, visit_id: str, provider_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.document_visit(
            visit_id,
            f.document_visit_payload(**overrides),
            make_provider_headers(provider_id),
        )
    )


def create_cost_share(api: ApiClient, referral_id: str, **overrides: Any) -> str:
    headers = overrides.pop("headers", FISCAL_HEADERS)
    data = get_success_data(
        api.create_cost_share(f.cost_share_payload(referral_id, **overrides), headers)
    )
    return data["id"]


def create_transition_plan(
    api: ApiClient,
    ifsp_id: str,
    coordinator_id: str,
    target_conference_date: str,
    **overrides: Any,
) -> str:
    data = get_success_data(
        api.create_transition_plan(
            f.transition_plan_payload(ifsp_id, target_conference_date, **overrides),
            make_service_coordinator_headers(coordinator_id),
        )
    )
    return data["id"]


# ─── Tier 2: layered case builders ────────────────────────────────────

_USE_CASE_COORDINATOR = "__use_case_coordinator__"


def build_intake(
    api: ApiClient,
    *,
    clock: str = INTAKE_CLOCK,
    coordinator: Optional[Dict[str, Any]] = None,
    child: Optional[Dict[str, Any]] = None,
    referral: Optional[Dict[str, Any]] = None,
) -> Case:
    """Set the clock, register a coordinator and a child, and open the case."""
    case = Case(clock=clock)
    set_clock(api, clock)
    case.coordinator_id = create_coordinator(api, **(coordinator or {}))
    case.coordinator_ids.append(case.coordinator_id)
    case.child_id = create_child(api, **(child or {}))
    case.child_ids.append(case.child_id)
    case.referral_id = create_referral(api, case.child_id, **(referral or {}))
    case.referral_ids.append(case.referral_id)
    return case


def build_assigned(
    api: ApiClient,
    *,
    assign_coordinator_id: Any = _USE_CASE_COORDINATOR,
    **kw: Any,
) -> Case:
    """Open the case and assign the coordinator to it."""
    case = build_intake(api, **kw)
    target = (
        case.coordinator_id
        if assign_coordinator_id is _USE_CASE_COORDINATOR
        else assign_coordinator_id
    )
    assign_coordinator(api, case.referral_id, target)
    return case


def build_assessments_scheduled(
    api: ApiClient,
    *,
    evaluation: Optional[Dict[str, Any]] = None,
    family_assessment: Optional[Dict[str, Any]] = None,
    **kw: Any,
) -> Case:
    """Schedule the multidisciplinary evaluation and the family assessment."""
    case = build_assigned(api, **kw)
    eval_overrides = {"scheduled_date": "2026-03-10"}
    eval_overrides.update(evaluation or {})
    case.eval_id = schedule_assessment(
        api, case.referral_id, assessment_type="INITIAL_EVALUATION", **eval_overrides
    )
    fam_overrides = {"scheduled_date": "2026-03-19"}
    fam_overrides.update(family_assessment or {})
    case.fam_id = schedule_assessment(
        api, case.referral_id, assessment_type="FAMILY_ASSESSMENT", **fam_overrides
    )
    return case


def build_assessments_completed(
    api: ApiClient,
    *,
    completion_clock: str = POST_EVALUATION_CLOCK,
    evaluation_completion: Optional[Dict[str, Any]] = None,
    family_completion: Optional[Dict[str, Any]] = None,
    complete_family_assessment: bool = True,
    **kw: Any,
) -> Case:
    """Advance the clock past both scheduled dates and complete both records."""
    case = build_assessments_scheduled(api, **kw)
    set_clock(api, completion_clock)
    case.clock = completion_clock
    eval_args = {"completion_date": "2026-03-18", "family_unavailable_days": 0}
    eval_args.update(evaluation_completion or {})
    complete_assessment(api, case.eval_id, **eval_args)
    if complete_family_assessment:
        fam_args = {"completion_date": "2026-03-19", "family_unavailable_days": 0}
        fam_args.update(family_completion or {})
        complete_assessment(api, case.fam_id, **fam_args)
    return case


def build_ifsp_pending(
    api: ApiClient,
    *,
    determination: Optional[Dict[str, Any]] = None,
    entry_outcomes: Optional[Dict[str, Any]] = None,
    **kw: Any,
) -> Case:
    """Determine eligibility and record the three entry child-outcome ratings."""
    case = build_assessments_completed(api, **kw)
    determine_eligibility(api, case.referral_id, **(determination or {}))
    record_entry_outcomes(api, case.referral_id, **(entry_outcomes or {}))
    return case


def build_plan_with_line(
    api: ApiClient,
    *,
    ifsp: Optional[Dict[str, Any]] = None,
    line: Optional[Dict[str, Any]] = None,
    **kw: Any,
) -> Case:
    """Author the initial plan and add its first service line."""
    case = build_ifsp_pending(api, **kw)
    case.ifsp_id = author_ifsp(
        api, case.referral_id, case.coordinator_id, **(ifsp or {})
    )
    case.line_id = add_service_line(api, case.ifsp_id, **(line or {}))
    case.line_ids.append(case.line_id)
    return case


def build_active_services(
    api: ApiClient,
    *,
    consent: Optional[Dict[str, Any]] = None,
    **kw: Any,
) -> Case:
    """
    The canonical case: one child in active services under a consented plan
    carrying a single speech-therapy line of 96 planned units.
    """
    case = build_plan_with_line(api, **kw)
    record_consent(api, case.ifsp_id, case.child_id, **(consent or {}))
    return case


def build_authorized(
    api: ApiClient,
    *,
    provider: Optional[Dict[str, Any]] = None,
    authorization: Optional[Dict[str, Any]] = None,
    **kw: Any,
) -> Case:
    """Register a provider agency and authorize it against the service line."""
    case = build_active_services(api, **kw)
    case.provider_id = create_provider(api, **(provider or {}))
    case.provider_ids.append(case.provider_id)
    case.authorization_id = create_authorization(
        api, case.line_id, case.provider_id, **(authorization or {})
    )
    case.authorization_ids.append(case.authorization_id)
    return case


def build_visit_scheduled(
    api: ApiClient,
    *,
    scheduled_start: str = "2026-03-24T14:00:00Z",
    scheduled_end: str = "2026-03-24T14:30:00Z",
    visit: Optional[Dict[str, Any]] = None,
    **kw: Any,
) -> Case:
    """Schedule one session against the authorization."""
    case = build_authorized(api, **kw)
    case.visit_id = schedule_visit(
        api,
        case.authorization_id,
        scheduled_start,
        scheduled_end,
        scheduler_headers=case.coordinator_headers,
        **(visit or {}),
    )
    case.visit_ids.append(case.visit_id)
    return case


def build_visit_delivered(
    api: ApiClient,
    *,
    document_clock: str = "2026-03-25T09:00:00Z",
    document: Optional[Dict[str, Any]] = None,
    **kw: Any,
) -> Case:
    """Schedule a session, advance past it, and document it as delivered."""
    case = build_visit_scheduled(api, **kw)
    set_clock(api, document_clock)
    case.clock = document_clock
    document_args = {"visit_status": "DELIVERED", "actual_units": 2}
    document_args.update(document or {})
    document_visit(api, case.visit_id, case.provider_id, **document_args)
    return case


# ─── Tier 3: scenario composites shared by several tests ──────────────

def build_cost_share_case(
    api: ApiClient, *, cost_share: Optional[Dict[str, Any]] = None, **kw: Any
) -> Case:
    """A case in active services with a provisional family determination."""
    case = build_active_services(api, **kw)
    case.cost_share_id = create_cost_share(api, case.referral_id, **(cost_share or {}))
    return case


def build_accrued_visit_case(
    api: ApiClient,
    *,
    cost_share: Optional[Dict[str, Any]] = None,
    provider: Optional[Dict[str, Any]] = None,
    authorization: Optional[Dict[str, Any]] = None,
    visit_windows: Any = (("2026-03-24T14:00:00Z", "2026-03-24T14:30:00Z"),),
    document_clock: str = "2026-03-25T09:00:00Z",
    actual_units: int = 2,
    **kw: Any,
) -> Case:
    """
    The fiscal chain: a provisional determination is on file before any session
    is authorized, so every documented session accrues a family share against it.
    Sessions are scheduled in the order given, then documented as delivered.
    """
    case = build_cost_share_case(api, cost_share=cost_share, **kw)
    case.provider_id = create_provider(api, **(provider or {}))
    case.provider_ids.append(case.provider_id)
    case.authorization_id = create_authorization(
        api, case.line_id, case.provider_id, **(authorization or {})
    )
    case.authorization_ids.append(case.authorization_id)
    for start, end in visit_windows:
        visit_id = schedule_visit(
            api,
            case.authorization_id,
            start,
            end,
            scheduler_headers=case.coordinator_headers,
        )
        case.visit_ids.append(visit_id)
    case.visit_id = case.visit_ids[0] if case.visit_ids else None
    set_clock(api, document_clock)
    case.clock = document_clock
    for visit_id in case.visit_ids:
        document_visit(
            api,
            visit_id,
            case.provider_id,
            visit_status="DELIVERED",
            actual_units=actual_units,
        )
    return case


def build_transition_planning_case(
    api: ApiClient,
    *,
    child: Optional[Dict[str, Any]] = None,
    referral: Optional[Dict[str, Any]] = None,
    line: Optional[Dict[str, Any]] = None,
    window_open_clock: str = "2026-04-20T09:00:00Z",
    target_conference_date: str = "2026-12-01",
    transition_plan: Optional[Dict[str, Any]] = None,
    **kw: Any,
) -> Case:
    """
    A case in active services for a child close enough to age three that the
    transition window has opened, with a draft transition plan already recorded.
    """
    child_overrides = {
        "first_name": "Miles",
        "last_name": "Okafor",
        "date_of_birth": "2024-01-10",
    }
    child_overrides.update(child or {})
    referral_overrides = {
        "primary_referral_source": "HOSPITAL",
        "presenting_concern": (
            "Gross motor delay flagged at the neonatal follow-up clinic"
        ),
    }
    referral_overrides.update(referral or {})
    line_overrides = {"service_type": "PHYSICAL_THERAPY"}
    line_overrides.update(line or {})
    case = build_active_services(
        api,
        child=child_overrides,
        referral=referral_overrides,
        line=line_overrides,
        **kw,
    )
    set_clock(api, window_open_clock)
    case.clock = window_open_clock
    plan_overrides = {"conference_held_date": "2026-04-15", "transition_steps_count": 4}
    plan_overrides.update(transition_plan or {})
    case.transition_plan_id = create_transition_plan(
        api,
        case.ifsp_id,
        case.coordinator_id,
        target_conference_date,
        **plan_overrides,
    )
    return case


# ─── Tier 4: read-back helpers ────────────────────────────────────────

def read_child(api: ApiClient, child_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_child(child_id, ADMIN_HEADERS), 200)


def read_coordinator(api: ApiClient, coordinator_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_coordinator(coordinator_id, ADMIN_HEADERS), 200)


def read_caseload_summary(api: ApiClient, coordinator_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_caseload_summary(coordinator_id, ADMIN_HEADERS), 200)


def read_referral(api: ApiClient, referral_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_referral(referral_id, ADMIN_HEADERS), 200)


def read_timeline(api: ApiClient, referral_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_timeline_compliance(referral_id, ADMIN_HEADERS), 200)


def read_assessment(api: ApiClient, assessment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_assessment(assessment_id, ADMIN_HEADERS), 200)


def read_ifsp(api: ApiClient, ifsp_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_ifsp(ifsp_id, ADMIN_HEADERS), 200)


def read_service_line(api: ApiClient, service_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_ifsp_service(service_id, ADMIN_HEADERS), 200)


def read_provider(api: ApiClient, provider_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_provider(provider_id, ADMIN_HEADERS), 200)


def read_authorization(api: ApiClient, authorization_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_authorization(authorization_id, ADMIN_HEADERS), 200)


def read_visit(api: ApiClient, visit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_visit(visit_id, ADMIN_HEADERS), 200)


def read_cost_share(api: ApiClient, cost_share_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cost_share(cost_share_id, ADMIN_HEADERS), 200)


def read_transition_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_transition_plan(plan_id, ADMIN_HEADERS), 200)


def read_contact_log(api: ApiClient, contact_log_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contact_log(contact_log_id, ADMIN_HEADERS), 200)


# ─── Tier 5: pytest fixtures ──────────────────────────────────────────

@pytest.fixture
def intake_case(api: ApiClient) -> Case:
    """An open case at the front door, no coordinator assigned yet."""
    return build_intake(api)


@pytest.fixture
def assigned_case(api: ApiClient) -> Case:
    """An open case with its coordinator assigned."""
    return build_assigned(api)


@pytest.fixture
def ifsp_pending_case(api: ApiClient) -> Case:
    """An eligible case with entry ratings on file, awaiting plan authoring."""
    return build_ifsp_pending(api)


@pytest.fixture
def plan_with_line_case(api: ApiClient) -> Case:
    """A plan carrying one speech-therapy line, awaiting parental consent."""
    return build_plan_with_line(api)


@pytest.fixture
def active_services_case(api: ApiClient) -> Case:
    """The canonical consented case in active services."""
    return build_active_services(api)


@pytest.fixture
def authorized_case(api: ApiClient) -> Case:
    """The canonical case with a provider authorized for 24 units."""
    return build_authorized(api)


@pytest.fixture
def visit_scheduled_case(api: ApiClient) -> Case:
    """The canonical case with one 30-minute session scheduled."""
    return build_visit_scheduled(api)


@pytest.fixture
def delivered_visit_case(api: ApiClient) -> Case:
    """The canonical case with one session documented as delivered."""
    return build_visit_delivered(api)
