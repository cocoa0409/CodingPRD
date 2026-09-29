"""Composite setup helpers: put the system into a named state with one call.

Each helper drives the real API through the documented endpoints, using the role
each endpoint authorises, and returns the created rows so a test can assert
against them. Nothing here asserts business rules; the tests do that.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import validate_paginated, validate_success

from . import factories as f
from .constants import INITIAL_LOGICAL_CLOCK, plus_minutes
from .test_users import (
    make_chair_headers,
    make_evaluator_headers,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
PLACEMENT = TEST_USERS["placement_headers"]
DISTRICT_ADMIN = TEST_USERS["district_admin_headers"]

# The five developmental domains and a discipline that may assess each of them.
DOMAIN_EVALUATOR_DISCIPLINES = {
    "COGNITIVE": "ECSE_TEACHER",
    "COMMUNICATION": "SLP",
    "PHYSICAL_MOTOR": "OT",
    "SOCIAL_EMOTIONAL": "SOCIAL_WORKER",
    "ADAPTIVE": "PT",
}

# Non-overlapping one-hour windows, one per domain, all at the district centre.
DOMAIN_WINDOW_STARTS = {
    "COGNITIVE": "2026-08-05T09:00:00Z",
    "COMMUNICATION": "2026-08-05T10:00:00Z",
    "PHYSICAL_MOTOR": "2026-08-05T11:00:00Z",
    "SOCIAL_EMOTIONAL": "2026-08-05T12:00:00Z",
    "ADAPTIVE": "2026-08-05T13:00:00Z",
}

# A five-domain result set that qualifies every domain at 33.3 percent.
ELIGIBLE_AGE_EQUIVALENTS = {
    "COGNITIVE": 22,
    "COMMUNICATION": 22,
    "PHYSICAL_MOTOR": 22,
    "SOCIAL_EMOTIONAL": 22,
    "ADAPTIVE": 22,
}

# A five-domain result set in which no domain reaches the qualifying threshold.
NOT_ELIGIBLE_AGE_EQUIVALENTS = {
    "COGNITIVE": 30,
    "COMMUNICATION": 30,
    "PHYSICAL_MOTOR": 30,
    "SOCIAL_EMOTIONAL": 30,
    "ADAPTIVE": 30,
}


# ------------------------------------------------------------------ logical clock
def set_clock(api, current_utc: str = INITIAL_LOGICAL_CLOCK) -> Dict[str, Any]:
    """Move the server's logical clock."""
    return validate_success(api.set_clock(f.clock_payload(current_utc), DISTRICT_ADMIN))


# ---------------------------------------------------------------------- registry
def register_child(api, **overrides: Any) -> Dict[str, Any]:
    """Register one child in the roster."""
    return validate_success(
        api.create_child(f.child_payload(**overrides), COORDINATOR), 201
    )


def register_child_aged(api, age_months: int, on_date: str = "2026-08-01", **overrides: Any):
    """Register a child whose completed-month age on ``on_date`` is exactly ``age_months``."""
    return validate_success(
        api.create_child(
            f.child_payload_for_age(age_months, on_date, **overrides), COORDINATOR
        ),
        201,
    )


def register_part_c_child(api, age_months: int = 33, on_date: str = "2026-08-01", **overrides: Any):
    """Register an early-intervention child, which requires a Part C exit date."""
    return validate_success(
        api.create_child(
            f.part_c_child_payload(age_months, on_date, **overrides), COORDINATOR
        ),
        201,
    )


def register_site(api, **overrides: Any) -> Dict[str, Any]:
    """Register one community preschool site."""
    return validate_success(
        api.create_community_site(f.community_site_payload(**overrides), PLACEMENT), 201
    )


def register_provider(api, **overrides: Any) -> Dict[str, Any]:
    """Register one provider."""
    return validate_success(
        api.create_provider(f.provider_payload(**overrides), DISTRICT_ADMIN), 201
    )


def register_chair(api, **overrides: Any) -> Dict[str, Any]:
    """Register a chair-eligible provider."""
    return validate_success(
        api.create_provider(f.chair_provider_payload(**overrides), DISTRICT_ADMIN), 201
    )


def register_interpreter(api, languages: Optional[List[str]] = None, **overrides: Any):
    """Register an interpreter that can carry at least one assignment."""
    return validate_success(
        api.create_provider(
            f.interpreter_provider_payload(languages, **overrides), DISTRICT_ADMIN
        ),
        201,
    )


def patch_provider(api, provider_id: str, **fields: Any) -> Dict[str, Any]:
    """Amend a provider's availability, languages or ceilings."""
    return validate_success(
        api.update_provider(provider_id, dict(fields), DISTRICT_ADMIN)
    )


def read_provider(api, provider_id: str) -> Dict[str, Any]:
    """Re-read a provider so its current ``version`` and postures are in hand."""
    return validate_success(api.get_provider(provider_id, DISTRICT_ADMIN))


def read_site(api, site_id: str) -> Dict[str, Any]:
    return validate_success(api.get_community_site(site_id, PLACEMENT))


def read_child(api, child_id: str) -> Dict[str, Any]:
    return validate_success(api.get_child(child_id, COORDINATOR))


# --------------------------------------------------------------------- screening
def create_screening_event(api, site_id: Optional[str] = None, **overrides: Any):
    """Schedule a SCHEDULED event, registering an approved host site if needed."""
    if site_id is None:
        site_id = register_site(api)["id"]
    event = validate_success(
        api.create_screening_event(f.screening_event_payload(site_id, **overrides), COORDINATOR),
        201,
    )
    return event


def advance_event(api, event_id: str, target_status: str) -> Dict[str, Any]:
    """Drive a screening event through its lifecycle, or cancel it."""
    return validate_success(
        api.set_screening_event_status(
            event_id, f.event_status_payload(target_status), COORDINATOR
        )
    )


def create_open_screening_event(api, site_id: Optional[str] = None, **overrides: Any):
    """Schedule an event and open it for bookings."""
    event = create_screening_event(api, site_id, **overrides)
    return advance_event(api, event["id"], "OPEN")


def book_slot(api, event: Dict[str, Any], child_id: str, **overrides: Any):
    """Book one appointment against the event's currently observed version."""
    payload = f.slot_booking_payload(child_id, event["version"], **overrides)
    return validate_success(api.book_screening_slot(event["id"], payload, COORDINATOR), 201)


def read_event(api, event_id: str) -> Dict[str, Any]:
    return validate_success(api.get_screening_event(event_id, COORDINATOR))


def record_outcome(
    api, slot_id: str, attendance: str, screening_result: Optional[str] = None
) -> Dict[str, Any]:
    """Record attendance, and for an attended appointment its screening result."""
    return validate_success(
        api.record_slot_outcome(
            slot_id, f.slot_outcome_payload(attendance, screening_result), COORDINATOR
        )
    )


def setup_open_event_with_booked_slot(api, **event_overrides: Any) -> Dict[str, Any]:
    """An OPEN event at an approved host site with one BOOKED appointment on it."""
    site = register_site(api)
    event = create_open_screening_event(api, site["id"], **event_overrides)
    child = register_child(api)
    slot = book_slot(api, event, child["id"])
    return {
        "site": site,
        "event": read_event(api, event["id"]),
        "child": child,
        "slot": slot,
    }


# ---------------------------------------------------------------------- referrals
def create_referral(api, child_id: Optional[str] = None, **overrides: Any):
    """Intake one referral, registering a child in the age window if needed."""
    if child_id is None:
        child_id = register_child(api)["id"]
    return validate_success(
        api.create_referral(f.referral_payload(child_id, **overrides), COORDINATOR), 201
    )


def read_referral(api, referral_id: str) -> Dict[str, Any]:
    return validate_success(api.get_referral(referral_id, COORDINATOR))


def read_timeline(api, referral_id: str) -> Dict[str, Any]:
    return validate_success(api.get_referral_timeline(referral_id, COORDINATOR))


def issue_evaluation_notice(api, referral_id: str, **overrides: Any) -> Dict[str, Any]:
    """Issue the prior-written-notice and evaluation-consent packet."""
    return validate_success(
        api.issue_consent_request(
            referral_id, f.consent_request_payload(**overrides), COORDINATOR
        ),
        201,
    )


def decide_consent(api, consent_id: str, decision: str, headers=None) -> Dict[str, Any]:
    """Record the family's decision on a consent record."""
    return validate_success(
        api.record_consent_decision(
            consent_id, f.consent_decision_payload(decision), headers or COORDINATOR
        )
    )


def read_consent(api, consent_id: str) -> Dict[str, Any]:
    return validate_success(api.get_consent_record(consent_id, COORDINATOR))


def consent_records_for_referral(api, referral_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"referral_id": referral_id, "limit": 100}
    query.update(params)
    data, _ = validate_paginated(api.list_consent_records(COORDINATOR, query))
    return data


def consent_record_for_plan(api, plan_id: str) -> Dict[str, Any]:
    """The service-consent record created when a plan was submitted to the family."""
    data, _ = validate_paginated(
        api.list_consent_records(COORDINATOR, {"service_plan_id": plan_id, "limit": 100})
    )
    assert data, f"no consent record found for plan {plan_id}"
    return data[-1]


def setup_referral_with_granted_consent(api, child_id: Optional[str] = None, **overrides: Any):
    """A referral at EVALUATION_AUTHORIZED / GRANTED with its pinned due date."""
    child = None
    if child_id is None:
        child = register_child(api)
        child_id = child["id"]
    referral = create_referral(api, child_id, **overrides)
    consent = issue_evaluation_notice(api, referral["id"])
    consent = decide_consent(api, consent["id"], "GRANTED")
    return {
        "child": child if child is not None else read_child(api, child_id),
        "referral": read_referral(api, referral["id"]),
        "consent": consent,
    }


# --------------------------------------------------------------- evaluation cases
def open_case(api, referral_id: str, chair_provider_id: str, **overrides: Any):
    """Open the multidisciplinary evaluation under a chair-eligible provider."""
    return validate_success(
        api.open_evaluation_case(
            referral_id, f.evaluation_case_payload(chair_provider_id, **overrides), COORDINATOR
        ),
        201,
    )


def read_case(api, case_id: str) -> Dict[str, Any]:
    return validate_success(api.get_evaluation_case(case_id, COORDINATOR))


def read_eligibility_profile(api, case_id: str) -> Dict[str, Any]:
    return validate_success(api.get_eligibility_profile(case_id, COORDINATOR))


def setup_case(api, child_id: Optional[str] = None, chair: Optional[Dict] = None, **overrides: Any):
    """A PLANNED evaluation case behind a granted evaluation consent."""
    protocol = overrides.pop("assessment_protocol", "PLAY_BASED")
    granted = setup_referral_with_granted_consent(api, child_id, **overrides)
    if chair is None:
        chair = register_chair(api)
    case = open_case(
        api, granted["referral"]["id"], chair["id"], assessment_protocol=protocol
    )
    return {
        "child": granted["child"],
        "referral": read_referral(api, granted["referral"]["id"]),
        "consent": granted["consent"],
        "chair": read_provider(api, chair["id"]),
        "case": case,
    }


# ------------------------------------------------------------ domain assessments
def register_domain_evaluators(api) -> Dict[str, Dict[str, Any]]:
    """One ACTIVE provider per domain, each of a discipline that may assess it."""
    return {
        domain: register_provider(api, discipline=discipline)
        for domain, discipline in DOMAIN_EVALUATOR_DISCIPLINES.items()
    }


def schedule_assessment(api, case_id: str, evaluator_provider_id: str, **overrides: Any):
    """Schedule one developmental-domain assessment on a case."""
    return validate_success(
        api.schedule_domain_assessment(
            case_id,
            f.domain_assessment_payload(evaluator_provider_id, **overrides),
            COORDINATOR,
        ),
        201,
    )


def complete_assessment(
    api,
    assessment_id: str,
    evaluator_provider_id: str,
    age_equivalent_months: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record an assessment's age-equivalent result as its assigned evaluator."""
    return validate_success(
        api.complete_domain_assessment(
            assessment_id,
            f.assessment_completion_payload(age_equivalent_months, **overrides),
            make_evaluator_headers(evaluator_provider_id),
        )
    )


def invalidate_assessment(
    api, assessment_id: str, evaluator_provider_id: str, reason: str = "Administration compromised"
) -> Dict[str, Any]:
    """Invalidate an assessment as its own assigned evaluator."""
    return validate_success(
        api.invalidate_domain_assessment(
            assessment_id,
            f.assessment_invalidation_payload(reason),
            make_evaluator_headers(evaluator_provider_id),
        )
    )


def read_assessment(api, assessment_id: str) -> Dict[str, Any]:
    return validate_success(api.get_domain_assessment(assessment_id, COORDINATOR))


def assessments_for_case(api, case_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"evaluation_case_id": case_id, "limit": 100}
    query.update(params)
    data, _ = validate_paginated(api.list_domain_assessments(COORDINATOR, query))
    return data


def setup_case_with_five_completed_domains(
    api,
    child_id: Optional[str] = None,
    chair: Optional[Dict] = None,
    assessment_protocol: str = "PLAY_BASED",
    method: str = "STANDARDIZED",
    age_equivalents: Optional[Dict[str, int]] = None,
    methods: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A case at DOMAINS_COMPLETE with one COMPLETED assessment per domain."""
    context = setup_case(
        api, child_id, chair, assessment_protocol=assessment_protocol, **overrides
    )
    evaluators = register_domain_evaluators(api)
    equivalents = dict(ELIGIBLE_AGE_EQUIVALENTS)
    if age_equivalents:
        equivalents.update(age_equivalents)
    assessments: Dict[str, Dict[str, Any]] = {}
    for domain, evaluator in evaluators.items():
        domain_method = (methods or {}).get(domain, method)
        scheduled = schedule_assessment(
            api,
            context["case"]["id"],
            evaluator["id"],
            domain=domain,
            method=domain_method,
            window_start_utc=DOMAIN_WINDOW_STARTS[domain],
        )
        assessments[domain] = complete_assessment(
            api, scheduled["id"], evaluator["id"], equivalents[domain]
        )
    context["evaluators"] = evaluators
    context["assessments"] = assessments
    context["case"] = read_case(api, context["case"]["id"])
    return context


# ------------------------------------------------------- report and determination
def draft_report(api, case_id: str, chair_provider_id: str, **overrides: Any):
    """Draft the multidisciplinary evaluation report as the case's own chair."""
    return validate_success(
        api.draft_report(
            case_id, f.report_payload(**overrides), make_chair_headers(chair_provider_id)
        )
    )


def request_revision(api, case_id: str, **overrides: Any) -> Dict[str, Any]:
    """Send a drafted report back to the chair for revision."""
    return validate_success(
        api.request_revision(case_id, f.revision_request_payload(**overrides), PLACEMENT)
    )


def determine_eligible(
    api,
    case_id: str,
    setting: str = "ITINERANT_ONLY",
    expected_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record an ELIGIBLE determination, which creates the plan at DRAFT."""
    version = expected_version if expected_version is not None else read_case(api, case_id)["version"]
    payload = f.eligible_determination_payload(version, setting=setting, **overrides)
    return validate_success(api.determine_eligibility(case_id, payload, PLACEMENT), 201)


def determine_not_eligible(
    api, case_id: str, expected_version: Optional[int] = None, **overrides: Any
) -> Dict[str, Any]:
    """Record a NOT_ELIGIBLE determination, whose plan closes immediately."""
    version = expected_version if expected_version is not None else read_case(api, case_id)["version"]
    payload = f.not_eligible_determination_payload(version, **overrides)
    return validate_success(api.determine_eligibility(case_id, payload, PLACEMENT), 201)


def read_plan(api, plan_id: str) -> Dict[str, Any]:
    return validate_success(api.get_service_plan(plan_id, PLACEMENT))


def plans_for_case(api, case_id: str) -> List[Dict[str, Any]]:
    data, _ = validate_paginated(
        api.list_service_plans(PLACEMENT, {"evaluation_case_id": case_id, "limit": 100})
    )
    return data


def setup_draft_plan(
    api,
    child_id: Optional[str] = None,
    setting: str = "ITINERANT_ONLY",
    community_site_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A DRAFT service plan behind a determined, ELIGIBLE evaluation case."""
    context = setup_case_with_five_completed_domains(api, child_id, **overrides)
    draft_report(api, context["case"]["id"], context["chair"]["id"])
    extra: Dict[str, Any] = {}
    if community_site_id is not None:
        extra["community_site_id"] = community_site_id
    plan = determine_eligible(api, context["case"]["id"], setting=setting, **extra)
    context["case"] = read_case(api, context["case"]["id"])
    context["plan"] = plan
    return context


# ------------------------------------------------------------------ service lines
def add_line(api, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    """Add one service line to a draft plan."""
    return validate_success(
        api.add_service_line(plan_id, f.service_line_payload(**overrides), PLACEMENT), 201
    )


def staff_line(
    api, line_id: str, provider_id: str, expected_version: Optional[int] = None, **overrides: Any
) -> Dict[str, Any]:
    """Staff a line against the provider's currently observed version."""
    version = (
        expected_version
        if expected_version is not None
        else read_provider(api, provider_id)["version"]
    )
    payload = f.staffing_payload(provider_id, version, **overrides)
    return validate_success(api.staff_service_line(line_id, payload, PLACEMENT))


def unstaff_line(api, line_id: str, **overrides: Any) -> Dict[str, Any]:
    """Release the provider from a staffed line."""
    return validate_success(
        api.unstaff_service_line(line_id, f.unstaffing_payload(**overrides), PLACEMENT)
    )


def read_line(api, line_id: str) -> Dict[str, Any]:
    return validate_success(api.get_service_line(line_id, PLACEMENT))


def lines_for_plan(api, plan_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"service_plan_id": plan_id, "limit": 100}
    query.update(params)
    data, _ = validate_paginated(api.list_service_lines(PLACEMENT, query))
    return data


def read_caseload(api, provider_id: str) -> Dict[str, Any]:
    return validate_success(api.get_provider_caseload(provider_id, PLACEMENT))


# ------------------------------------------------- service consent and transition
def submit_plan(api, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    """Send the drafted plan to the family, which creates a service-consent record."""
    return validate_success(
        api.submit_plan_for_consent(
            plan_id, f.consent_submission_payload(**overrides), PLACEMENT
        ),
        201,
    )


def transition(api, plan_id: str, action: str, **overrides: Any) -> Dict[str, Any]:
    """Drive one kindergarten transition action on an ACTIVE plan."""
    return validate_success(
        api.kindergarten_transition(plan_id, f.transition_payload(action, **overrides), PLACEMENT)
    )


def setup_staffed_draft_plan(
    api,
    child_id: Optional[str] = None,
    setting: str = "ITINERANT_ONLY",
    community_site_id: Optional[str] = None,
    discipline: str = "SLP",
    weekly_minutes: int = 100,
    delivery_model: str = "DIRECT",
    provider: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A DRAFT plan carrying exactly one STAFFED service line."""
    context = setup_draft_plan(
        api, child_id, setting=setting, community_site_id=community_site_id, **overrides
    )
    if provider is None:
        provider = register_provider(api, discipline=discipline)
    line = add_line(
        api,
        context["plan"]["id"],
        discipline=discipline,
        weekly_minutes=weekly_minutes,
        delivery_model=delivery_model,
    )
    line = staff_line(api, line["id"], provider["id"])
    context["line_provider"] = read_provider(api, provider["id"])
    context["line"] = line
    context["plan"] = read_plan(api, context["plan"]["id"])
    return context


def setup_plan_pending_parent_consent(api, child_id: Optional[str] = None, **overrides: Any):
    """A plan at PENDING_PARENT_CONSENT with its service-consent record outstanding."""
    context = setup_staffed_draft_plan(api, child_id, **overrides)
    submit_plan(api, context["plan"]["id"])
    context["plan"] = read_plan(api, context["plan"]["id"])
    context["service_consent"] = consent_record_for_plan(api, context["plan"]["id"])
    return context


def setup_active_plan(api, child_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """An ACTIVE plan whose family has granted consent to services."""
    context = setup_plan_pending_parent_consent(api, child_id, **overrides)
    decide_consent(api, context["service_consent"]["id"], "GRANTED")
    context["service_consent"] = read_consent(api, context["service_consent"]["id"])
    context["plan"] = read_plan(api, context["plan"]["id"])
    context["line"] = read_line(api, context["line"]["id"])
    context["line_provider"] = read_provider(api, context["line_provider"]["id"])
    return context


# ------------------------------------------------------------------- misc helpers
def window(start: str, minutes: int = 60) -> Tuple[str, str]:
    """An assessment or event window of ``minutes`` starting at ``start``."""
    return (start, plus_minutes(start, minutes))


def listing(api, method_name: str, headers, **params: Any) -> Tuple[List[Dict[str, Any]], Dict]:
    """Call any list endpoint by client method name and return ``(data, meta)``."""
    return validate_paginated(getattr(api, method_name)(headers, dict(params)))
