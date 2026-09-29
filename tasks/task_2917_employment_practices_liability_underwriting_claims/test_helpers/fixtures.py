"""Setup builders.

The database is empty at the start of every test, so each of these helpers
builds the state it needs from scratch through the public API only.  They are
plain functions taking the client so that a test can compose them freely and
still vary the numbers a particular scenario needs; conftest.py wraps the most
common chains as pytest fixtures.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from . import test_users as U
from . import types as T
from .api_client import ApiClient


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def create_jurisdiction(api: ApiClient, code: str = "CA", **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_jurisdiction(F.jurisdiction(code, **overrides), U.ADMIN), 201)


def create_jurisdictions(api: ApiClient, codes: List[str]) -> Dict[str, Dict[str, Any]]:
    return {code: create_jurisdiction(api, code) for code in codes}


def create_active_rate_plan(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    plan = get_success_data(api.create_rate_plan(F.rate_plan(**overrides), U.ADMIN), 201)
    return get_success_data(api.activate_rate_plan(plan["id"], U.ADMIN))


def create_draft_rate_plan(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_rate_plan(F.rate_plan(**overrides), U.ADMIN), 201)


def create_panel_firm(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_panel_firm(F.panel_firm(**overrides), U.ADMIN), 201)


def carrier_book(api: ApiClient, codes: Optional[List[str]] = None, **plan_overrides: Any) -> Dict[str, Any]:
    """CA + TX jurisdictions and one ACTIVE rate plan — the standard book."""
    jurisdictions = create_jurisdictions(api, codes or ["CA", "TX"])
    plan = create_active_rate_plan(api, **plan_overrides)
    return {"jurisdictions": jurisdictions, "plan": plan, "plan_id": plan["id"]}


# ---------------------------------------------------------------------------
# Applicant
# ---------------------------------------------------------------------------
def create_applicant(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_applicant(F.applicant(**overrides), U.UNDERWRITER), 201)


def create_risk_service(api: ApiClient, applicant_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_risk_service(applicant_id, F.risk_service(**overrides), U.UNDERWRITER), 201
    )


def create_active_risk_service(api: ApiClient, applicant_id: str, **overrides: Any) -> Dict[str, Any]:
    service = create_risk_service(api, applicant_id, **overrides)
    return get_success_data(api.complete_risk_service(service["id"], U.UNDERWRITER))


def read_applicant_version(api: ApiClient, applicant_id: str) -> int:
    return get_success_data(api.get_applicant(applicant_id, U.UNDERWRITER))["version"]


# ---------------------------------------------------------------------------
# Underwriting chain
# ---------------------------------------------------------------------------
def create_assessment(api: ApiClient, applicant_id: str, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    version = overrides.pop("expected_applicant_version", None)
    if version is None:
        version = read_applicant_version(api, applicant_id)
    payload = F.assessment(applicant_id, plan_id, version, **overrides)
    return get_success_data(api.create_assessment(payload, U.UNDERWRITER), 201)


def create_priced_assessment(api: ApiClient, applicant_id: str, plan_id: str, **overrides: Any):
    assessment = create_assessment(api, applicant_id, plan_id, **overrides)
    return get_success_data(api.price_assessment(assessment["id"], U.UNDERWRITER))


def create_approved_assessment(api: ApiClient, applicant_id: str, plan_id: str, **overrides: Any):
    assessment = create_priced_assessment(api, applicant_id, plan_id, **overrides)
    return get_success_data(api.approve_assessment(assessment["id"], U.UW_MANAGER))


def bind_policy(api: ApiClient, assessment_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_policy(F.policy(assessment_id, **overrides), U.UNDERWRITER), 201)


def underwritten_policy(
    api: ApiClient,
    codes: Optional[List[str]] = None,
    applicant_overrides: Optional[Dict[str, Any]] = None,
    assessment_overrides: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Jurisdictions -> ACTIVE plan -> applicant -> priced+approved assessment -> policy."""
    book = carrier_book(api, codes, **(plan_overrides or {}))
    applicant = create_applicant(api, **(applicant_overrides or {}))
    assessment = create_approved_assessment(
        api, applicant["id"], book["plan_id"], **(assessment_overrides or {})
    )
    policy = bind_policy(api, assessment["id"], **(policy_overrides or {}))
    return {
        "jurisdictions": book["jurisdictions"],
        "plan": book["plan"],
        "plan_id": book["plan_id"],
        "applicant": applicant,
        "applicant_id": applicant["id"],
        "assessment": assessment,
        "assessment_id": assessment["id"],
        "policy": policy,
        "policy_id": policy["id"],
    }


def read_policy_version(api: ApiClient, policy_id: str) -> int:
    return get_success_data(api.get_policy(policy_id, U.ADJUSTER))["version"]


# ---------------------------------------------------------------------------
# Claims chain
# ---------------------------------------------------------------------------
def report_claim(api: ApiClient, policy_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.report_claim(policy_id, F.claim(**overrides), U.ADJUSTER), 201)


def accepted_claim(api: ApiClient, policy_id: str, **overrides: Any) -> Dict[str, Any]:
    claim = report_claim(api, policy_id, **overrides)
    get_success_data(api.start_claim_review(claim["id"], U.ADJUSTER))
    return get_success_data(
        api.coverage_decision(claim["id"], F.coverage_decision(T.DECISION_ACCEPT), U.ADJUSTER)
    )


def denied_claim(api: ApiClient, policy_id: str, denial_reason: str = "Outside coverage grant", **overrides: Any):
    claim = report_claim(api, policy_id, **overrides)
    get_success_data(api.start_claim_review(claim["id"], U.ADJUSTER))
    return get_success_data(
        api.coverage_decision(
            claim["id"],
            F.coverage_decision(T.DECISION_DENY, denial_reason=denial_reason),
            U.ADJUSTER,
        )
    )


def approved_payment(api: ApiClient, policy_id: str, claim_id: str, amount_cents: int) -> Dict[str, Any]:
    version = read_policy_version(api, policy_id)
    payment = get_success_data(
        api.create_payment(claim_id, F.payment(amount_cents, version), U.ADJUSTER), 201
    )
    return get_success_data(api.approve_payment(payment["id"], U.CLAIMS_MANAGER))


def pending_payment(api: ApiClient, policy_id: str, claim_id: str, amount_cents: int, **overrides: Any):
    version = overrides.pop("expected_policy_version", None)
    if version is None:
        version = read_policy_version(api, policy_id)
    return get_success_data(
        api.create_payment(claim_id, F.payment(amount_cents, version, **overrides), U.ADJUSTER), 201
    )


# ---------------------------------------------------------------------------
# Defense chain
# ---------------------------------------------------------------------------
def create_assignment(api: ApiClient, claim_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_assignment(claim_id, F.assignment(**overrides), U.ADJUSTER), 201
    )


def submit_invoice(api: ApiClient, assignment_id: str, panel_firm_id: str, **overrides: Any):
    return get_success_data(
        api.submit_invoice(assignment_id, F.invoice(**overrides), U.panel_counsel(panel_firm_id)), 201
    )


def audited_invoice(api: ApiClient, assignment_id: str, panel_firm_id: str, **overrides: Any):
    invoice = submit_invoice(api, assignment_id, panel_firm_id, **overrides)
    return get_success_data(api.audit_invoice(invoice["id"], U.ADJUSTER))


def defended_claim(
    api: ApiClient,
    firm_overrides: Optional[Dict[str, Any]] = None,
    claim_overrides: Optional[Dict[str, Any]] = None,
    assignment_overrides: Optional[Dict[str, Any]] = None,
    **policy_kwargs: Any,
) -> Dict[str, Any]:
    """A panel firm, an accepted claim and an ACTIVE defense assignment on it."""
    world = underwritten_policy(api, **policy_kwargs)
    firm = create_panel_firm(api, **(firm_overrides or {}))
    claim = accepted_claim(api, world["policy_id"], **(claim_overrides or {}))
    assignment = create_assignment(api, claim["id"], **(assignment_overrides or {}))
    world.update(
        {
            "firm": firm,
            "firm_id": firm["id"],
            "claim": claim,
            "claim_id": claim["id"],
            "assignment": assignment,
            "assignment_id": assignment["id"],
        }
    )
    return world


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def advance_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(to_iso8601, U.ADMIN))
