"""Composite setup helpers that walk the API to a wanted state.

Every test starts against an empty deployment, so each test builds the world
it needs from scratch through the public API. These helpers do that walking
and return the identifiers, headers and observed versions the test then
asserts against.

They are organised from the simplest to the most far-reaching:

  Tier 1  the logical clock and standing reference data
  Tier 2  the acceptance pipeline, up to an approved and ACTIVE engagement
  Tier 3  staffing, findings, threats, services, attestations and reviews
  Tier 4  scenario builders that reach one exact state a claim is asserted on
  Tier 5  accumulation helpers used by the boundary claims

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK
from .test_users import (
    COMMITTEE_HEADERS,
    LIAISON_HEADERS,
    OFFICER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_engagement_partner_headers,
    make_quality_reviewer_headers,
)


# ═══ Tier 1: the clock and standing reference data ═════════════════════════

def set_clock(api: ApiClient, current_utc: str = DEFAULT_CLOCK) -> Dict[str, Any]:
    """Move the logical clock and return the write's payload."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), PLATFORM_ADMIN_HEADERS))


def seed_affiliate(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one network member firm."""
    return get_success_data(
        api.create_affiliate(f.affiliate_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def seed_client(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one client or prospect."""
    return get_success_data(
        api.create_client(f.client_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def seed_professional(
    api: ApiClient, affiliate_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Register one professional, creating a home affiliate when none is given."""
    if affiliate_id is None:
        affiliate_id = seed_affiliate(api)["id"]
    overrides.setdefault("home_affiliate_id", affiliate_id)
    return get_success_data(
        api.create_professional(f.professional_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def open_engagement(
    api: ApiClient, client_id: str, ep_headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Open one engagement against an existing client."""
    headers = ep_headers or PLATFORM_ADMIN_HEADERS
    return get_success_data(
        api.create_engagement(f.engagement_payload(client_id=client_id, **overrides), headers)
    )


def seed_reference_data(api: ApiClient, **client_overrides: Any) -> Dict[str, Any]:
    """The smallest standing world: an affiliate, an acting partner, a client
    and an engagement opened by that partner.

    Returns a dict carrying every identifier and the acting partner's headers.
    """
    affiliate = seed_affiliate(api)
    acting_partner = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting_partner["id"])
    client = seed_client(api, **client_overrides)
    engagement = open_engagement(api, client["id"], ep_headers)
    return {
        "affiliate": affiliate,
        "acting_partner": acting_partner,
        "ep_headers": ep_headers,
        "client": client,
        "engagement": engagement,
    }


# ── Fresh reads ────────────────────────────────────────────────────────────

def get_client_data(api: ApiClient, client_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_client(client_id, PLATFORM_ADMIN_HEADERS))


def get_engagement_data(api: ApiClient, engagement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_engagement(engagement_id, PLATFORM_ADMIN_HEADERS))


def get_acceptance_data(api: ApiClient, acceptance_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_acceptance(acceptance_id, COMMITTEE_HEADERS))


def get_professional_data(api: ApiClient, professional_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_professional(professional_id, PLATFORM_ADMIN_HEADERS))


def get_assignment_data(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_assignment(assignment_id, PLATFORM_ADMIN_HEADERS))


def get_finding_data(api: ApiClient, finding_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_finding(finding_id, OFFICER_HEADERS))


def get_threat_data(api: ApiClient, threat_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_threat(threat_id, OFFICER_HEADERS))


def get_service_data(api: ApiClient, service_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_service(service_id, LIAISON_HEADERS))


def get_attestation_data(api: ApiClient, attestation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_attestation(attestation_id, OFFICER_HEADERS))


def get_review_data(api: ApiClient, review_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_review(review_id, PLATFORM_ADMIN_HEADERS))


def get_summary_data(api: ApiClient, engagement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_independence_summary(engagement_id, OFFICER_HEADERS))


def engagement_version(api: ApiClient, engagement_id: str) -> int:
    """The engagement's current version, read fresh so a write is not stale."""
    return get_engagement_data(api, engagement_id)["version"]


def list_assignments_for(api: ApiClient, engagement_id: str) -> List[Dict[str, Any]]:
    """Every role assignment currently recorded for one engagement."""
    data, _ = validate_paginated(
        api.list_assignments(PLATFORM_ADMIN_HEADERS, {"engagement_id": engagement_id})
    )
    return data


def list_findings_for(api: ApiClient, engagement_id: str) -> List[Dict[str, Any]]:
    """Every independence finding currently recorded for one engagement."""
    data, _ = validate_paginated(
        api.list_findings(PLATFORM_ADMIN_HEADERS, {"engagement_id": engagement_id})
    )
    return data


def list_assessments_for(api: ApiClient, acceptance_id: str) -> List[Dict[str, Any]]:
    """Every integrity row currently attached to one evaluation."""
    return get_success_data(
        api.list_integrity_assessments(acceptance_id, PLATFORM_ADMIN_HEADERS)
    )


# ═══ Tier 2: the acceptance pipeline ═══════════════════════════════════════

def open_acceptance(
    api: ApiClient, client_id: str, engagement_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open one acceptance or continuance evaluation."""
    return get_success_data(
        api.create_acceptance(
            f.acceptance_payload(client_id=client_id, engagement_id=engagement_id, **overrides),
            COMMITTEE_HEADERS,
        )
    )


def record_integrity(api: ApiClient, acceptance_id: str, **overrides: Any) -> Dict[str, Any]:
    """Attach one management-integrity row to an evaluation."""
    return get_success_data(
        api.create_integrity_assessment(
            acceptance_id, f.integrity_payload(**overrides), COMMITTEE_HEADERS
        )
    )


def submit_acceptance(api: ApiClient, acceptance_id: str) -> Dict[str, Any]:
    return get_success_data(api.submit_acceptance(acceptance_id, COMMITTEE_HEADERS))


def decide_acceptance(
    api: ApiClient, acceptance_id: str, decision: str, notes: Optional[str] = None
):
    """Record a committee decision; returns the raw response so a test can
    assert on a rejection as well as on a success."""
    return api.decide_acceptance(
        acceptance_id, f.decision_payload(decision, notes), COMMITTEE_HEADERS
    )


def decide_acceptance_ok(
    api: ApiClient, acceptance_id: str, decision: str, notes: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(decide_acceptance(api, acceptance_id, decision, notes))


def build_acceptance(
    api: ApiClient,
    client_id: str,
    engagement_id: str,
    assessments: Optional[Sequence[Dict[str, Any]]] = None,
    submit: bool = True,
    expertise_required: str = "TECH",
) -> Dict[str, Any]:
    """Open an evaluation, attach the given integrity rows and submit it.

    ``assessments`` is a sequence of keyword dicts handed to ``record_integrity``;
    the default is a single resolved low-impact credit event, which leaves the
    combined score well inside every approval band.
    """
    acceptance = open_acceptance(
        api,
        client_id,
        engagement_id,
        industry_expertise_required=expertise_required,
        industry_expertise_confirmed=True,
    )
    rows = list(assessments) if assessments is not None else [
        {
            "source_type": "CREDIT_EVENT",
            "severity": "LOW",
            "score_impact": 5,
            "assessed_on": DEFAULT_CLOCK,
            "resolved": True,
        }
    ]
    for row in rows:
        record_integrity(api, acceptance["id"], **row)
    if submit:
        submit_acceptance(api, acceptance["id"])
    return get_acceptance_data(api, acceptance["id"])


def approve_engagement(
    api: ApiClient,
    client_id: str,
    engagement_id: str,
    assessments: Optional[Sequence[Dict[str, Any]]] = None,
    expertise_required: str = "TECH",
    notes: str = "clean",
) -> Dict[str, Any]:
    """Drive one engagement all the way to ACTIVE.

    Returns a dict with the approved acceptance, the engagement read after the
    decision and the client read after the decision.
    """
    acceptance = build_acceptance(
        api, client_id, engagement_id, assessments, submit=True,
        expertise_required=expertise_required,
    )
    decide_acceptance_ok(api, acceptance["id"], "APPROVE", notes)
    return {
        "acceptance": get_acceptance_data(api, acceptance["id"]),
        "engagement": get_engagement_data(api, engagement_id),
        "client": get_client_data(api, client_id),
    }


def setup_active_engagement(
    api: ApiClient,
    client_overrides: Optional[Dict[str, Any]] = None,
    engagement_overrides: Optional[Dict[str, Any]] = None,
    assessments: Optional[Sequence[Dict[str, Any]]] = None,
    clock: str = DEFAULT_CLOCK,
) -> Dict[str, Any]:
    """A client with one ACTIVE engagement, its approved acceptance and an
    acting engagement partner.

    The clock is set first so that every dated payload written afterwards is
    legal against it.
    """
    set_clock(api, clock)
    affiliate = seed_affiliate(api)
    acting_partner = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting_partner["id"])
    client = seed_client(api, **(client_overrides or {}))
    engagement = open_engagement(
        api, client["id"], ep_headers, **(engagement_overrides or {})
    )
    approved = approve_engagement(
        api, client["id"], engagement["id"], assessments,
        expertise_required=client["industry_code"],
    )
    return {
        "affiliate": affiliate,
        "acting_partner": acting_partner,
        "ep_headers": ep_headers,
        "client": approved["client"],
        "engagement": approved["engagement"],
        "acceptance": approved["acceptance"],
        "created_engagement": engagement,
    }


# ═══ Tier 3: staffing, findings, threats, services, attestations, reviews ══

def staff(
    api: ApiClient,
    engagement_id: str,
    professional_id: str,
    role: str,
    started_on: str,
    scheduled_end_on: str,
    expected_version: Optional[int] = None,
    ep_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
):
    """Create one role assignment; returns the raw response.

    When ``expected_version`` is omitted the engagement is read first, so the
    call carries the version the caller could have observed.
    """
    headers = ep_headers or PLATFORM_ADMIN_HEADERS
    if expected_version is None:
        expected_version = engagement_version(api, engagement_id)
    return api.create_assignment(
        f.assignment_payload(
            engagement_id=engagement_id,
            professional_id=professional_id,
            role=role,
            started_on=started_on,
            scheduled_end_on=scheduled_end_on,
            expected_engagement_version=expected_version,
            **overrides,
        ),
        headers,
    )


def staff_ok(
    api: ApiClient,
    engagement_id: str,
    professional_id: str,
    role: str,
    started_on: str,
    scheduled_end_on: str,
    expected_version: Optional[int] = None,
    ep_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        staff(
            api, engagement_id, professional_id, role, started_on, scheduled_end_on,
            expected_version, ep_headers, **overrides,
        )
    )


def end_assignment(
    api: ApiClient, assignment_id: str, ep_headers: Optional[Dict[str, str]] = None
):
    return api.end_assignment(assignment_id, ep_headers or PLATFORM_ADMIN_HEADERS)


def end_assignment_ok(
    api: ApiClient, assignment_id: str, ep_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(end_assignment(api, assignment_id, ep_headers))


def raise_finding(
    api: ApiClient,
    professional_id: str,
    engagement_id: str,
    expected_version: Optional[int] = None,
    **overrides: Any,
):
    """Raise one independence finding; returns the raw response."""
    if expected_version is None:
        expected_version = engagement_version(api, engagement_id)
    return api.create_finding(
        f.finding_payload(
            professional_id=professional_id,
            engagement_id=engagement_id,
            expected_engagement_version=expected_version,
            **overrides,
        ),
        OFFICER_HEADERS,
    )


def raise_finding_ok(
    api: ApiClient,
    professional_id: str,
    engagement_id: str,
    expected_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        raise_finding(api, professional_id, engagement_id, expected_version, **overrides)
    )


def finding_transition(api: ApiClient, finding_id: str, action: str):
    return api.transition_finding(finding_id, f.transition_payload(action), OFFICER_HEADERS)


def finding_transition_ok(api: ApiClient, finding_id: str, action: str) -> Dict[str, Any]:
    return get_success_data(finding_transition(api, finding_id, action))


def declare_financial_interest(
    api: ApiClient,
    professional_id: str,
    client_id: str,
    instrument_type: str = "EQUITY",
    value_cents: int = 0,
    effective_on: str = DEFAULT_CLOCK,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_threat(
            f.financial_interest_payload(
                professional_id, client_id, instrument_type, value_cents, effective_on,
                **overrides,
            ),
            OFFICER_HEADERS,
        )
    )


def declare_employment_relationship(
    api: ApiClient,
    professional_id: str,
    client_id: str,
    relationship_type: str = "FORMER_FIRM_PROFESSIONAL_JOINED_CLIENT",
    effective_on: str = DEFAULT_CLOCK,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_threat(
            f.employment_relationship_payload(
                professional_id, client_id, relationship_type, effective_on, **overrides
            ),
            OFFICER_HEADERS,
        )
    )


def threat_transition(api: ApiClient, threat_id: str, action: str):
    return api.transition_threat(threat_id, f.transition_payload(action), OFFICER_HEADERS)


def threat_transition_ok(api: ApiClient, threat_id: str, action: str) -> Dict[str, Any]:
    return get_success_data(threat_transition(api, threat_id, action))


def create_service(api: ApiClient, client_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_service(f.service_payload(client_id=client_id, **overrides), LIAISON_HEADERS)
    )


def service_transition(api: ApiClient, service_id: str, action: str, **overrides: Any):
    headers = OFFICER_HEADERS if action == "REVOKE" else LIAISON_HEADERS
    return api.transition_service(service_id, f.transition_payload(action, **overrides), headers)


def service_transition_ok(api: ApiClient, service_id: str, action: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(service_transition(api, service_id, action, **overrides))


def approve_service(
    api: ApiClient, service_id: str, resolution_ref: str = "AC-1"
) -> Dict[str, Any]:
    """Submit and approve one service, returning the approval response payload."""
    service_transition_ok(api, service_id, "SUBMIT_FOR_APPROVAL")
    return service_transition_ok(
        api, service_id, "APPROVE", committee_resolution_ref=resolution_ref
    )


def create_attestation(
    api: ApiClient, affiliate_id: str, engagement_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_attestation(
            f.attestation_payload(affiliate_id, engagement_id, **overrides),
            PLATFORM_ADMIN_HEADERS,
        )
    )


def attestation_transition(api: ApiClient, attestation_id: str, action: str):
    return api.transition_attestation(
        attestation_id, f.transition_payload(action), OFFICER_HEADERS
    )


def attestation_transition_ok(api: ApiClient, attestation_id: str, action: str) -> Dict[str, Any]:
    return get_success_data(attestation_transition(api, attestation_id, action))


def create_review(
    api: ApiClient,
    engagement_id: str,
    reviewer_id: str,
    qr_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
):
    """Schedule one quality review or inspection; returns the raw response."""
    headers = qr_headers or make_quality_reviewer_headers(reviewer_id)
    return api.create_review(
        f.review_payload(engagement_id=engagement_id, reviewer_id=reviewer_id, **overrides),
        headers,
    )


def create_review_ok(
    api: ApiClient,
    engagement_id: str,
    reviewer_id: str,
    qr_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(create_review(api, engagement_id, reviewer_id, qr_headers, **overrides))


def review_transition(
    api: ApiClient, review_id: str, action: str, reviewer_id: str
):
    return api.transition_review(
        review_id, f.transition_payload(action), make_quality_reviewer_headers(reviewer_id)
    )


def review_transition_ok(
    api: ApiClient, review_id: str, action: str, reviewer_id: str
) -> Dict[str, Any]:
    return get_success_data(review_transition(api, review_id, action, reviewer_id))


def engagement_transition(
    api: ApiClient, engagement_id: str, action: str, ep_headers: Optional[Dict[str, str]] = None
):
    return api.transition_engagement(
        engagement_id, f.transition_payload(action), ep_headers or PLATFORM_ADMIN_HEADERS
    )


def engagement_transition_ok(
    api: ApiClient, engagement_id: str, action: str, ep_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(engagement_transition(api, engagement_id, action, ep_headers))


# ═══ Tier 4: scenario builders ═════════════════════════════════════════════

def scenario_provisional_vs_final(api: ApiClient) -> Dict[str, Any]:
    """One DRAFT evaluation carrying a resolved and an unresolved row.

    Clock at its default instant; the resolved 20-point row is six months old
    and the unresolved 10-point row three months old, so both sit in the tier
    that does not decay.
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    world = seed_reference_data(api, legal_name="Northwind Analytics", industry_code="TECH")
    acceptance = open_acceptance(
        api, world["client"]["id"], world["engagement"]["id"],
        industry_expertise_required="TECH", industry_expertise_confirmed=True,
    )
    record_integrity(
        api, acceptance["id"], source_type="LITIGATION", severity="HIGH", score_impact=20,
        assessed_on="2026-03-01T00:00:00Z", resolved=True,
    )
    record_integrity(
        api, acceptance["id"], source_type="REGULATORY_ACTION", severity="MEDIUM",
        score_impact=10, assessed_on="2026-06-01T00:00:00Z", resolved=False,
    )
    world["acceptance"] = get_acceptance_data(api, acceptance["id"])
    return world


def scenario_rotation_variants(api: ApiClient) -> Dict[str, Any]:
    """One professional serving a 60-month lead-partner run on a public
    interest client and on a standard client, over identical dates."""
    set_clock(api, "2026-01-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    pie_client = seed_client(
        api, legal_name="Helios Grid PIE", industry_code="TECH",
        is_public_interest_entity=True,
    )
    std_client = seed_client(
        api, legal_name="Copperline Logistics", industry_code="TECH",
        is_public_interest_entity=False,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Dana Whitfield", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    pie_engagement = open_engagement(
        api, pie_client["id"], ep_headers, fiscal_year_end="2031-12-31T00:00:00Z"
    )
    std_engagement = open_engagement(
        api, std_client["id"], ep_headers, fiscal_year_end="2031-12-31T00:00:00Z"
    )
    pie_assignment = staff_ok(
        api, pie_engagement["id"], professional["id"], "LEAD_PARTNER",
        "2026-01-01T00:00:00Z", "2032-01-01T00:00:00Z", ep_headers=ep_headers,
    )
    std_assignment = staff_ok(
        api, std_engagement["id"], professional["id"], "LEAD_PARTNER",
        "2026-01-01T00:00:00Z", "2032-01-01T00:00:00Z", ep_headers=ep_headers,
    )
    set_clock(api, "2031-01-01T00:00:00Z")
    return {
        "ep_headers": ep_headers,
        "professional": professional,
        "pie_client": pie_client,
        "std_client": std_client,
        "pie_engagement": pie_engagement,
        "std_engagement": std_engagement,
        "pie_assignment_id": pie_assignment["id"],
        "std_assignment_id": std_assignment["id"],
    }


def scenario_pie_surcharge_clamp(api: ApiClient) -> Dict[str, Any]:
    """Two ENERGY/CN clients — one public interest, one not — with identical
    resolved 40-point prior-audit-finding evidence, both submitted."""
    set_clock(api, "2026-08-01T00:00:00Z")
    world = seed_reference_data(api)
    ep_headers = world["ep_headers"]
    pie_client = seed_client(
        api, legal_name="Aurora Energy PIE", industry_code="ENERGY",
        jurisdiction_country="CN", is_public_interest_entity=True,
    )
    np_client = seed_client(
        api, legal_name="Aurora Energy Holdings", industry_code="ENERGY",
        jurisdiction_country="CN", is_public_interest_entity=False,
    )
    pie_engagement = open_engagement(
        api, pie_client["id"], ep_headers, engagement_type="INTEGRATED_AUDIT"
    )
    np_engagement = open_engagement(
        api, np_client["id"], ep_headers, engagement_type="INTEGRATED_AUDIT"
    )
    assessment = {
        "source_type": "PRIOR_AUDIT_FINDING", "severity": "CRITICAL", "score_impact": 40,
        "assessed_on": "2026-07-01T00:00:00Z", "resolved": True,
    }
    pie_acceptance = build_acceptance(
        api, pie_client["id"], pie_engagement["id"], [assessment],
        expertise_required="ENERGY",
    )
    np_acceptance = build_acceptance(
        api, np_client["id"], np_engagement["id"], [assessment],
        expertise_required="ENERGY",
    )
    return {
        "ep_headers": ep_headers,
        "pie_client": pie_client,
        "np_client": np_client,
        "pie_engagement": pie_engagement,
        "np_engagement": np_engagement,
        "pie_acceptance": pie_acceptance,
        "np_acceptance": np_acceptance,
    }


def scenario_naf_rounding(api: ApiClient) -> Dict[str, Any]:
    """One client with a 1,000,000-cent cap and two DRAFT services of
    100,040 cents each, both submitted for approval."""
    set_clock(api, "2026-04-01T00:00:00Z")
    client = seed_client(
        api, legal_name="Vantage Foods", industry_code="RETAIL", naf_annual_cap_cents=1000000
    )
    first = create_service(
        api, client["id"], service_category="TAX_ADVISORY", fee_cents=100040
    )
    second = create_service(
        api, client["id"], service_category="TAX_ADVISORY", fee_cents=100040
    )
    service_transition_ok(api, first["id"], "SUBMIT_FOR_APPROVAL")
    service_transition_ok(api, second["id"], "SUBMIT_FOR_APPROVAL")
    return {"client": client, "first": first, "second": second}


def scenario_workload_ladder(api: ApiClient) -> Dict[str, Any]:
    """One partner, five DRAFT engagements on one client and the first two
    assignments of the ladder already in place."""
    set_clock(api, "2026-02-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Bellwether Retail Group", industry_code="RETAIL",
        is_public_interest_entity=False,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Marcus Idris", grade="PARTNER",
        rotation_role_class="CONCURRING_PARTNER", max_workload_points=100,
    )
    engagements = [
        open_engagement(api, client["id"], ep_headers, fiscal_year_end=year)
        for year in (
            "2026-12-31T00:00:00Z",
            "2027-12-31T00:00:00Z",
            "2028-12-31T00:00:00Z",
            "2029-12-31T00:00:00Z",
            "2030-12-31T00:00:00Z",
        )
    ]
    first = staff_ok(
        api, engagements[0]["id"], professional["id"], "LEAD_PARTNER",
        "2026-02-01T00:00:00Z", "2027-02-01T00:00:00Z", ep_headers=ep_headers,
    )
    second = staff_ok(
        api, engagements[1]["id"], professional["id"], "EQ_REVIEWER",
        "2026-02-01T00:00:00Z", "2027-02-01T00:00:00Z", ep_headers=ep_headers,
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagements": engagements,
        "first": first,
        "second": second,
    }


def scenario_acceptance_cycle(api: ApiClient) -> Dict[str, Any]:
    """A DRAFT evaluation with one resolved low-impact row, ready to submit."""
    set_clock(api, "2026-05-01T00:00:00Z")
    world = seed_reference_data(
        api, legal_name="Ridgeline Grocers", industry_code="RETAIL",
        is_public_interest_entity=False,
    )
    acceptance = open_acceptance(
        api, world["client"]["id"], world["engagement"]["id"],
        industry_expertise_required="RETAIL", industry_expertise_confirmed=True,
    )
    record_integrity(
        api, acceptance["id"], source_type="MEDIA_ADVERSE", severity="LOW",
        score_impact=5, assessed_on="2026-04-01T00:00:00Z", resolved=True,
    )
    world["acceptance"] = get_acceptance_data(api, acceptance["id"])
    return world


def scenario_finding_cycle(api: ApiClient) -> Dict[str, Any]:
    """One OPEN high-severity finding on a DRAFT engagement."""
    set_clock(api, "2026-03-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Ironwood Paper", industry_code="MANUFACTURING",
        is_public_interest_entity=False,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Sofia Klein", grade="PARTNER",
        rotation_role_class="EQ_REVIEWER",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    finding = raise_finding_ok(
        api, professional["id"], engagement["id"], origin="DECLARATION",
        origin_ref_id="decl-2026-0201", finding_type="FINANCIAL_INTEREST",
        severity="HIGH", discovered_on="2026-02-01T00:00:00Z",
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagement": engagement,
        "finding": finding,
    }


def scenario_engagement_axes(api: ApiClient) -> Dict[str, Any]:
    """An approved, ACTIVE, staffed engagement that a CRITICAL finding then
    freezes."""
    set_clock(api, "2026-06-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Cascade Water Utility", industry_code="PUBLIC_SECTOR",
        is_public_interest_entity=False,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Tomas Berg", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    assignment = staff_ok(
        api, engagement["id"], professional["id"], "LEAD_PARTNER",
        "2026-06-01T00:00:00Z", "2027-06-01T00:00:00Z", ep_headers=ep_headers,
    )
    approved = approve_engagement(
        api, client["id"], engagement["id"],
        [{
            "source_type": "CREDIT_EVENT", "severity": "LOW", "score_impact": 5,
            "assessed_on": "2026-05-01T00:00:00Z", "resolved": True,
        }],
        expertise_required="PUBLIC_SECTOR",
    )
    finding = raise_finding_ok(
        api, professional["id"], engagement["id"], origin="DECLARATION",
        origin_ref_id="decl-2026-0601", finding_type="PROHIBITED_SERVICE",
        severity="CRITICAL", discovered_on="2026-06-01T00:00:00Z",
    )
    return {
        "ep_headers": ep_headers,
        "client": approved["client"],
        "professional": professional,
        "assignment": assignment,
        "engagement": approved["engagement"],
        "acceptance": approved["acceptance"],
        "finding": finding,
    }


def scenario_rejection_cascade(api: ApiClient) -> Dict[str, Any]:
    """A client already activated by one approved engagement, plus a second
    engagement whose evaluation is SUBMITTED."""
    set_clock(api, "2026-08-15T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Kestrel Motors", industry_code="MANUFACTURING",
        is_public_interest_entity=False,
    )
    first_engagement = open_engagement(api, client["id"], ep_headers)
    first_approved = approve_engagement(
        api, client["id"], first_engagement["id"],
        [{
            "source_type": "CREDIT_EVENT", "severity": "LOW", "score_impact": 5,
            "assessed_on": "2026-07-15T00:00:00Z", "resolved": True,
        }],
        expertise_required="MANUFACTURING",
    )
    second_engagement = open_engagement(
        api, client["id"], ep_headers, engagement_type="REVIEW_ENGAGEMENT",
        fiscal_year_end="2027-06-30T00:00:00Z",
    )
    second_acceptance = build_acceptance(
        api, client["id"], second_engagement["id"],
        [{
            "source_type": "MEDIA_ADVERSE", "severity": "MEDIUM", "score_impact": 12,
            "assessed_on": "2026-08-01T00:00:00Z", "resolved": True,
        }],
        expertise_required="MANUFACTURING",
    )
    return {
        "ep_headers": ep_headers,
        "client": first_approved["client"],
        "first_engagement": first_approved["engagement"],
        "second_engagement": second_engagement,
        "second_acceptance": second_acceptance,
    }


def scenario_assignment_end_cascade(api: ApiClient) -> Dict[str, Any]:
    """One ACTIVE lead-partner assignment, later ended from a clock nine
    months after it started."""
    set_clock(api, "2026-01-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Halcyon Studios", industry_code="TECH",
        is_public_interest_entity=False,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Priya Raman", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    engagement = open_engagement(
        api, client["id"], ep_headers, fiscal_year_end="2027-12-31T00:00:00Z"
    )
    assignment = staff_ok(
        api, engagement["id"], professional["id"], "LEAD_PARTNER",
        "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z", ep_headers=ep_headers,
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagement": engagement,
        "assignment": assignment,
    }


def scenario_closed_engagement_material_interest(api: ApiClient) -> Dict[str, Any]:
    """A public interest client whose only engagement was approved, staffed by
    nobody, then CLOSED — followed by a material direct holding declared by a
    partner."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Silverline Bank PIE", industry_code="FINANCIAL_SERVICES",
        is_public_interest_entity=True,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Owen Baptiste", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    engagement = open_engagement(
        api, client["id"], ep_headers, engagement_type="INTEGRATED_AUDIT"
    )
    stale_version = engagement["version"]
    approve_engagement(
        api, client["id"], engagement["id"],
        [{
            "source_type": "CREDIT_EVENT", "severity": "LOW", "score_impact": 5,
            "assessed_on": "2026-09-01T00:00:00Z", "resolved": True,
        }],
        expertise_required="FINANCIAL_SERVICES",
    )
    engagement_transition_ok(api, engagement["id"], "CLOSE", ep_headers)
    threat = declare_financial_interest(
        api, professional["id"], client["id"], instrument_type="EQUITY",
        value_cents=0, effective_on="2026-09-15T00:00:00Z",
    )
    return {
        "ep_headers": ep_headers,
        "client": get_client_data(api, client["id"]),
        "professional": professional,
        "engagement": get_engagement_data(api, engagement["id"]),
        "stale_version": stale_version,
        "threat": threat,
    }


def scenario_material_interest_gate(api: ApiClient) -> Dict[str, Any]:
    """A partner holding a material direct interest in a public interest
    client, on a DRAFT engagement that could otherwise be staffed."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Silverline Bank PIE", industry_code="FINANCIAL_SERVICES",
        is_public_interest_entity=True,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Owen Baptiste", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    engagement = open_engagement(
        api, client["id"], ep_headers, engagement_type="INTEGRATED_AUDIT"
    )
    threat = declare_financial_interest(
        api, professional["id"], client["id"], instrument_type="EQUITY",
        value_cents=0, effective_on="2026-09-15T00:00:00Z",
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagement": engagement,
        "threat": threat,
    }


def scenario_dangling_engagement(api: ApiClient) -> Dict[str, Any]:
    """A professional whose stale snapshot predates a sibling assignment, plus
    a second professional to staff."""
    set_clock(api, "2026-01-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Pinewood Chemicals", industry_code="MANUFACTURING",
        is_public_interest_entity=False,
    )
    first_professional = seed_professional(
        api, affiliate["id"], full_name="Lena Ostrowski", grade="PARTNER",
        rotation_role_class="CONCURRING_PARTNER",
    )
    second_professional = seed_professional(
        api, affiliate["id"], full_name="Yusuf Demir", grade="DIRECTOR",
        rotation_role_class="NONE",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    stale_version = engagement["version"]
    assignment = staff_ok(
        api, engagement["id"], first_professional["id"], "CONCURRING_PARTNER",
        "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z", ep_headers=ep_headers,
    )
    end_assignment_ok(api, assignment["id"], ep_headers)
    set_clock(api, "2026-06-15T00:00:00Z")
    return {
        "ep_headers": ep_headers,
        "client": client,
        "first_professional": first_professional,
        "second_professional": second_professional,
        "engagement": engagement,
        "stale_version": stale_version,
        "current_version": engagement_version(api, engagement["id"]),
    }


def scenario_risk_band_boundary(api: ApiClient) -> Dict[str, Any]:
    """Two public interest ENERGY/BR clients whose evaluations land one point
    apart on either side of the approval ceiling."""
    set_clock(api, "2026-12-01T00:00:00Z")
    world = seed_reference_data(api)
    ep_headers = world["ep_headers"]
    at_seventy = seed_client(
        api, legal_name="Atlas Petroleum PIE", industry_code="ENERGY",
        jurisdiction_country="BR", is_public_interest_entity=True,
    )
    at_sixty_nine = seed_client(
        api, legal_name="Atlas Midstream PIE", industry_code="ENERGY",
        jurisdiction_country="BR", is_public_interest_entity=True,
    )
    engagement_a = open_engagement(
        api, at_seventy["id"], ep_headers, engagement_type="INTEGRATED_AUDIT",
        fiscal_year_end="2027-06-30T00:00:00Z",
    )
    engagement_b = open_engagement(
        api, at_sixty_nine["id"], ep_headers, engagement_type="INTEGRATED_AUDIT",
        fiscal_year_end="2027-06-30T00:00:00Z",
    )
    acceptance_a = build_acceptance(
        api, at_seventy["id"], engagement_a["id"],
        [{
            "source_type": "LITIGATION", "severity": "MEDIUM", "score_impact": 5,
            "assessed_on": "2026-11-01T00:00:00Z", "resolved": True,
        }],
        expertise_required="ENERGY",
    )
    acceptance_b = build_acceptance(
        api, at_sixty_nine["id"], engagement_b["id"],
        [{
            "source_type": "LITIGATION", "severity": "MEDIUM", "score_impact": 4,
            "assessed_on": "2026-11-01T00:00:00Z", "resolved": True,
        }],
        expertise_required="ENERGY",
    )
    return {
        "ep_headers": ep_headers,
        "at_seventy": at_seventy,
        "at_sixty_nine": at_sixty_nine,
        "engagement_a": engagement_a,
        "engagement_b": engagement_b,
        "acceptance_a": acceptance_a,
        "acceptance_b": acceptance_b,
    }


def scenario_naf_cap_boundary(api: ApiClient) -> Dict[str, Any]:
    """A client whose approved pool sits at 200,000 cents, with a submitted
    candidate that would take it to exactly the 1,000,000-cent cap."""
    set_clock(api, "2027-01-04T00:00:00Z")
    client = seed_client(
        api, legal_name="Brightline Media", industry_code="TECH",
        naf_annual_cap_cents=1000000,
    )
    first = create_service(
        api, client["id"], service_category="TAX_PREPARATION", fee_cents=100040
    )
    second = create_service(
        api, client["id"], service_category="TAX_PREPARATION", fee_cents=100040
    )
    candidate = create_service(
        api, client["id"], service_category="TAX_ADVISORY", fee_cents=800040
    )
    approve_service(api, first["id"], "AC-2027-0001")
    approve_service(api, second["id"], "AC-2027-0002")
    service_transition_ok(api, candidate["id"], "SUBMIT_FOR_APPROVAL")
    return {"client": get_client_data(api, client["id"]), "candidate": candidate}


def scenario_inspection_windows(api: ApiClient) -> Dict[str, Any]:
    """One engagement with two reviewers, ready for two PCAOB inspections that
    differ only in their deficiency counts."""
    set_clock(api, "2026-01-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Northgate Utilities", industry_code="ENERGY",
        is_public_interest_entity=False,
    )
    first_reviewer = seed_professional(
        api, affiliate["id"], full_name="Hannah Cole", grade="PARTNER",
        rotation_role_class="EQ_REVIEWER",
    )
    second_reviewer = seed_professional(
        api, affiliate["id"], full_name="Ben Okafor", grade="DIRECTOR",
        rotation_role_class="EQ_REVIEWER",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    return {
        "ep_headers": ep_headers,
        "client": client,
        "engagement": engagement,
        "first_reviewer": first_reviewer,
        "second_reviewer": second_reviewer,
    }


def scenario_activation_dependency(api: ApiClient) -> Dict[str, Any]:
    """A submitted evaluation whose engagement is still ACCEPTANCE_PENDING."""
    set_clock(api, "2027-02-01T00:00:00Z")
    world = seed_reference_data(
        api, legal_name="Orchard Lane Markets", industry_code="RETAIL",
        is_public_interest_entity=False,
    )
    world["acceptance"] = build_acceptance(
        api, world["client"]["id"], world["engagement"]["id"],
        [{
            "source_type": "LITIGATION", "severity": "MEDIUM", "score_impact": 20,
            "assessed_on": "2027-01-15T00:00:00Z", "resolved": True,
        }],
        expertise_required="RETAIL",
    )
    return world


def scenario_multinational_attestation(api: ApiClient) -> Dict[str, Any]:
    """A multinational engagement whose only attestation is still PENDING and
    whose otherwise-clean evaluation is submitted."""
    set_clock(api, "2027-03-01T00:00:00Z")
    affiliate = seed_affiliate(
        api, firm_name="Deloitte GmbH", country_code="DE", network_tier="CORRESPONDENT",
        independence_framework="EU_LOCAL",
    )
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Vantage Foods International", industry_code="RETAIL",
        is_public_interest_entity=False,
    )
    engagement = open_engagement(
        api, client["id"], ep_headers, engagement_type="INTEGRATED_AUDIT",
        fiscal_year_end="2027-12-31T00:00:00Z", is_multinational=True,
    )
    attestation = create_attestation(api, affiliate["id"], engagement["id"], breach_count=0)
    acceptance = build_acceptance(
        api, client["id"], engagement["id"],
        [{
            "source_type": "CREDIT_EVENT", "severity": "LOW", "score_impact": 5,
            "assessed_on": "2027-02-01T00:00:00Z", "resolved": True,
        }],
        expertise_required="RETAIL",
    )
    return {
        "affiliate": affiliate,
        "ep_headers": ep_headers,
        "client": client,
        "engagement": engagement,
        "attestation": attestation,
        "acceptance": acceptance,
    }


def scenario_cooling_off(api: ApiClient) -> Dict[str, Any]:
    """A partner inside a twelve-month cooling-off window that ends on
    2027-01-01."""
    set_clock(api, "2026-12-31T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Lakeshore Regional Health", industry_code="HEALTHCARE",
        is_public_interest_entity=False,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Grace Lindqvist", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    engagement = open_engagement(
        api, client["id"], ep_headers, fiscal_year_end="2027-12-31T00:00:00Z"
    )
    threat = declare_employment_relationship(
        api, professional["id"], client["id"],
        relationship_type="FORMER_FIRM_PROFESSIONAL_JOINED_CLIENT",
        effective_on="2026-01-01T00:00:00Z",
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagement": engagement,
        "threat": threat,
    }


def scenario_half_open_intervals(api: ApiClient) -> Dict[str, Any]:
    """One engagement carrying a concurring-partner and a reviewer assignment
    over the same six-month window."""
    set_clock(api, "2026-01-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Beacon Aerospace", industry_code="MANUFACTURING",
        is_public_interest_entity=False,
    )
    concurring = seed_professional(
        api, affiliate["id"], full_name="Ivan Petrov", grade="PARTNER",
        rotation_role_class="CONCURRING_PARTNER",
    )
    reviewer = seed_professional(
        api, affiliate["id"], full_name="Nadia Farouk", grade="PARTNER",
        rotation_role_class="EQ_REVIEWER",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    concurring_assignment = staff_ok(
        api, engagement["id"], concurring["id"], "CONCURRING_PARTNER",
        "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z", ep_headers=ep_headers,
    )
    reviewer_assignment = staff_ok(
        api, engagement["id"], reviewer["id"], "EQ_REVIEWER",
        "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z", ep_headers=ep_headers,
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "engagement": engagement,
        "concurring": concurring,
        "reviewer": reviewer,
        "concurring_assignment": concurring_assignment,
        "reviewer_assignment": reviewer_assignment,
    }


def scenario_review_buffer(api: ApiClient) -> Dict[str, Any]:
    """One reviewer with a single engagement-quality review that ran
    2026-01-01 to 2026-03-01."""
    set_clock(api, "2026-03-05T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Cobalt Semiconductor", industry_code="TECH",
        is_public_interest_entity=False,
    )
    reviewer = seed_professional(
        api, affiliate["id"], full_name="Elena Marsh", grade="PARTNER",
        rotation_role_class="EQ_REVIEWER",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    existing = create_review_ok(
        api, engagement["id"], reviewer["id"], review_type="ENGAGEMENT_QUALITY_REVIEW",
        received_on="2026-01-01T00:00:00Z", due_on="2026-03-01T00:00:00Z",
        deficiency_count=0,
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "engagement": engagement,
        "reviewer": reviewer,
        "existing": existing,
    }


def scenario_fee_pool_conservation(api: ApiClient) -> Dict[str, Any]:
    """A client with a submitted 300,000-cent service waiting for approval."""
    set_clock(api, "2027-04-01T00:00:00Z")
    client = seed_client(
        api, legal_name="Summit Ridge Partners", industry_code="TECH",
        naf_annual_cap_cents=5000000,
    )
    service = create_service(
        api, client["id"], service_category="TAX_ADVISORY", fee_cents=300000
    )
    service_transition_ok(api, service["id"], "SUBMIT_FOR_APPROVAL")
    return {"client": client, "service": service}


def scenario_workload_conservation(api: ApiClient) -> Dict[str, Any]:
    """One partner with no assignments on a low-tier engagement."""
    set_clock(api, "2027-05-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Granite Peak Mining", industry_code="RETAIL",
        is_public_interest_entity=False,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Rafael Duarte", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER", max_workload_points=100,
    )
    engagement = open_engagement(
        api, client["id"], ep_headers, fiscal_year_end="2027-12-31T00:00:00Z"
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagement": engagement,
    }


def scenario_pagination(api: ApiClient) -> Dict[str, Any]:
    """Four engagements across two clients, ready to be paged."""
    set_clock(api, "2026-09-01T00:00:00Z")
    world = seed_reference_data(
        api, legal_name="Alder Creek Mills", industry_code="MANUFACTURING"
    )
    ep_headers = world["ep_headers"]
    second_client = seed_client(
        api, legal_name="Alder Creek Timber", industry_code="MANUFACTURING",
        jurisdiction_country="CA",
    )
    # ``seed_reference_data`` already opened one engagement for the first
    # client; the three below bring the total to exactly four.
    engagements = [
        world["engagement"],
        open_engagement(
            api, world["client"]["id"], ep_headers,
            fiscal_year_end="2027-12-31T00:00:00Z",
        ),
        open_engagement(
            api, world["client"]["id"], ep_headers, engagement_type="REVIEW_ENGAGEMENT",
            fiscal_year_end="2028-12-31T00:00:00Z",
        ),
        open_engagement(api, second_client["id"], ep_headers),
    ]
    world["second_client"] = second_client
    world["engagements"] = engagements
    return world


def scenario_closed_finding(api: ApiClient) -> Dict[str, Any]:
    """A low-severity finding already closed with no action."""
    set_clock(api, "2026-09-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(api, legal_name="Wexford Ceramics", industry_code="MANUFACTURING")
    professional = seed_professional(
        api, affiliate["id"], full_name="Karin Vogel", grade="SENIOR_MANAGER",
        rotation_role_class="NONE",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    finding = raise_finding_ok(
        api, professional["id"], engagement["id"], origin="DECLARATION",
        origin_ref_id="decl-wx-1", finding_type="WORKLOAD_LIMIT", severity="LOW",
        discovered_on="2026-08-01T00:00:00Z",
    )
    finding_transition_ok(api, finding["id"], "CLOSE_NO_ACTION")
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagement": engagement,
        "finding": get_finding_data(api, finding["id"]),
    }


def scenario_passed_review(api: ApiClient) -> Dict[str, Any]:
    """A review already advanced to its terminal PASSED state."""
    set_clock(api, "2026-09-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(api, legal_name="Pemberton Rail", industry_code="MANUFACTURING")
    reviewer = seed_professional(
        api, affiliate["id"], full_name="Alice Nakamura", grade="PARTNER",
        rotation_role_class="EQ_REVIEWER",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    review = create_review_ok(
        api, engagement["id"], reviewer["id"], review_type="ENGAGEMENT_QUALITY_REVIEW",
        received_on="2026-08-01T00:00:00Z", due_on="2026-10-01T00:00:00Z",
        deficiency_count=0,
    )
    review_transition_ok(api, review["id"], "START", reviewer["id"])
    review_transition_ok(api, review["id"], "PASS", reviewer["id"])
    return {
        "ep_headers": ep_headers,
        "client": client,
        "engagement": engagement,
        "reviewer": reviewer,
        "review": get_review_data(api, review["id"]),
    }


def scenario_active_staffed_engagement(api: ApiClient) -> Dict[str, Any]:
    """An ACTIVE engagement carrying a lead-partner and an engagement-manager
    assignment."""
    set_clock(api, "2026-09-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(api, legal_name="Selby Textiles", industry_code="RETAIL")
    lead = seed_professional(
        api, affiliate["id"], full_name="Ruth Adeyemi", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    manager = seed_professional(
        api, affiliate["id"], full_name="Peter Nowak", grade="SENIOR_MANAGER",
        rotation_role_class="NONE",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    approved = approve_engagement(
        api, client["id"], engagement["id"],
        [{
            "source_type": "CREDIT_EVENT", "severity": "LOW", "score_impact": 5,
            "assessed_on": "2026-08-01T00:00:00Z", "resolved": True,
        }],
        expertise_required="RETAIL",
    )
    lead_assignment = staff_ok(
        api, engagement["id"], lead["id"], "LEAD_PARTNER",
        "2026-09-01T00:00:00Z", "2027-09-01T00:00:00Z", ep_headers=ep_headers,
    )
    manager_assignment = staff_ok(
        api, engagement["id"], manager["id"], "ENGAGEMENT_MANAGER",
        "2026-09-01T00:00:00Z", "2027-09-01T00:00:00Z", ep_headers=ep_headers,
    )
    return {
        "ep_headers": ep_headers,
        "client": approved["client"],
        "engagement": approved["engagement"],
        "lead": lead,
        "manager": manager,
        "lead_assignment": lead_assignment,
        "manager_assignment": manager_assignment,
    }


def scenario_attestation_waive(api: ApiClient) -> Dict[str, Any]:
    """A multinational engagement carrying one member-firm and one alliance
    attestation, both still PENDING."""
    set_clock(api, "2026-09-01T00:00:00Z")
    member_firm = seed_affiliate(api)
    alliance = seed_affiliate(
        api, firm_name="Polaris Advisory", country_code="SE", network_tier="ALLIANCE",
        independence_framework="IFAC_BASELINE",
    )
    acting = seed_professional(
        api, member_firm["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(api, legal_name="Calder Industrial", industry_code="MANUFACTURING")
    engagement = open_engagement(
        api, client["id"], ep_headers, engagement_type="INTEGRATED_AUDIT",
        is_multinational=True,
    )
    member_attestation = create_attestation(
        api, member_firm["id"], engagement["id"], breach_count=0
    )
    alliance_attestation = create_attestation(
        api, alliance["id"], engagement["id"], breach_count=0
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "engagement": engagement,
        "member_attestation": member_attestation,
        "alliance_attestation": alliance_attestation,
    }


def scenario_decay_tier(api: ApiClient) -> Dict[str, Any]:
    """A DRAFT evaluation carrying a single 20-point row assessed exactly one
    year before the clock."""
    set_clock(api, "2026-10-01T00:00:00Z")
    world = seed_reference_data(
        api, legal_name="Dunmore Glassworks", industry_code="MANUFACTURING"
    )
    acceptance = open_acceptance(
        api, world["client"]["id"], world["engagement"]["id"],
        industry_expertise_required="MANUFACTURING",
    )
    record_integrity(
        api, acceptance["id"], source_type="LITIGATION", severity="HIGH",
        score_impact=20, assessed_on="2025-10-01T00:00:00Z", resolved=True,
    )
    world["acceptance"] = get_acceptance_data(api, acceptance["id"])
    return world


def scenario_materiality_tiers(api: ApiClient) -> Dict[str, Any]:
    """A DIRECTOR on a private client, ready for holdings either side of the
    doubled threshold."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Ashby Instruments", industry_code="TECH",
        is_public_interest_entity=False,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Marta Nowicka", grade="DIRECTOR",
        rotation_role_class="NONE",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagement": engagement,
    }


def scenario_network_risk(api: ApiClient) -> Dict[str, Any]:
    """Two multinational engagements and one domestic engagement, with two
    breached member-firm attestations."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(api, legal_name="Bramble Energy Group", industry_code="ENERGY")
    first = open_engagement(
        api, client["id"], ep_headers, engagement_type="INTEGRATED_AUDIT",
        is_multinational=True,
    )
    second = open_engagement(
        api, client["id"], ep_headers, engagement_type="INTEGRATED_AUDIT",
        fiscal_year_end="2027-12-31T00:00:00Z", is_multinational=True,
    )
    domestic = open_engagement(
        api, client["id"], ep_headers, engagement_type="STATUTORY_AUDIT",
        fiscal_year_end="2028-12-31T00:00:00Z", is_multinational=False,
    )
    first_attestation = create_attestation(
        api, affiliate["id"], first["id"], breach_count=19
    )
    second_attestation = create_attestation(
        api, affiliate["id"], second["id"], breach_count=15
    )
    for attestation in (first_attestation, second_attestation):
        attestation_transition_ok(api, attestation["id"], "ATTEST")
        attestation_transition_ok(api, attestation["id"], "REPORT_BREACH")
    return {
        "ep_headers": ep_headers,
        "client": client,
        "first": first,
        "second": second,
        "domestic": domestic,
        "first_attestation": first_attestation,
        "second_attestation": second_attestation,
    }


def scenario_zero_month_cooling_off(api: ApiClient) -> Dict[str, Any]:
    """A MANAGER on a private client, ready for a zero-month relationship and
    a twenty-four-month one."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(api, legal_name="Linden Grove Care", industry_code="HEALTHCARE")
    first_professional = seed_professional(
        api, affiliate["id"], full_name="Tobias Lang", grade="MANAGER",
        rotation_role_class="NONE",
    )
    second_professional = seed_professional(
        api, affiliate["id"], full_name="Miriam Osei", grade="MANAGER",
        rotation_role_class="NONE",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    return {
        "ep_headers": ep_headers,
        "client": client,
        "engagement": engagement,
        "first_professional": first_professional,
        "second_professional": second_professional,
    }


def scenario_assignment_gates(api: ApiClient) -> Dict[str, Any]:
    """A partner with no threats, no findings and no assignments, on a
    low-tier engagement."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(api, legal_name="Netherby Farms", industry_code="RETAIL")
    professional = seed_professional(
        api, affiliate["id"], full_name="Clara Boone", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER", max_workload_points=100,
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagement": engagement,
    }


def scenario_summary_breakdown(api: ApiClient) -> Dict[str, Any]:
    """A multinational engagement carrying a critical finding, a breached
    attestation and a material personal interest at once."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Coldwater Utilities", industry_code="ENERGY",
        is_public_interest_entity=True,
    )
    professional = seed_professional(
        api, affiliate["id"], full_name="Hugo Marchetti", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    engagement = open_engagement(
        api, client["id"], ep_headers, engagement_type="INTEGRATED_AUDIT",
        is_multinational=True,
    )
    finding = raise_finding_ok(
        api, professional["id"], engagement["id"], origin="INSPECTION",
        origin_ref_id="insp-1", finding_type="PROHIBITED_SERVICE",
        severity="CRITICAL", discovered_on="2026-09-01T00:00:00Z",
    )
    attestation = create_attestation(api, affiliate["id"], engagement["id"], breach_count=0)
    attestation_transition_ok(api, attestation["id"], "ATTEST")
    attestation_transition_ok(api, attestation["id"], "REPORT_BREACH")
    threat = declare_financial_interest(
        api, professional["id"], client["id"], instrument_type="EQUITY",
        value_cents=0, effective_on="2026-09-01T00:00:00Z",
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagement": engagement,
        "finding": finding,
        "attestation": attestation,
        "threat": threat,
    }


def scenario_resume_while_frozen(api: ApiClient) -> Dict[str, Any]:
    """An ACTIVE, staffed engagement frozen by a critical finding."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(api, legal_name="Stanton Foundry", industry_code="MANUFACTURING")
    professional = seed_professional(
        api, affiliate["id"], full_name="Iris Delacroix", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    approved = approve_engagement(
        api, client["id"], engagement["id"],
        [{
            "source_type": "CREDIT_EVENT", "severity": "LOW", "score_impact": 5,
            "assessed_on": "2026-09-01T00:00:00Z", "resolved": True,
        }],
        expertise_required="MANUFACTURING",
    )
    staff_ok(
        api, engagement["id"], professional["id"], "LEAD_PARTNER",
        "2026-10-01T00:00:00Z", "2027-10-01T00:00:00Z", ep_headers=ep_headers,
    )
    finding = raise_finding_ok(
        api, professional["id"], engagement["id"], origin="DECLARATION",
        origin_ref_id="decl-st-1", finding_type="FINANCIAL_INTEREST",
        severity="CRITICAL", discovered_on="2026-09-20T00:00:00Z",
    )
    return {
        "ep_headers": ep_headers,
        "client": approved["client"],
        "professional": professional,
        "engagement": get_engagement_data(api, engagement["id"]),
        "finding": finding,
    }


def scenario_reviewer_ownership(api: ApiClient) -> Dict[str, Any]:
    """A SCHEDULED review created by the professional who reviews it."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Tarn Basin Mining", industry_code="ENERGY", jurisdiction_country="AU"
    )
    reviewer = seed_professional(
        api, affiliate["id"], full_name="Beatrice Lund", grade="PARTNER",
        rotation_role_class="EQ_REVIEWER",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    review = create_review_ok(
        api, engagement["id"], reviewer["id"], review_type="ENGAGEMENT_QUALITY_REVIEW",
        received_on="2026-09-01T00:00:00Z", due_on="2026-11-01T00:00:00Z",
        deficiency_count=0,
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "engagement": engagement,
        "reviewer": reviewer,
        "review": review,
    }


def scenario_stale_assignment_version(api: ApiClient) -> Dict[str, Any]:
    """A writer holding the engagement snapshot taken before a sibling
    assignment advanced it."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(
        api, legal_name="Kelvinside Chemicals", industry_code="MANUFACTURING",
        jurisdiction_country="GB",
    )
    lead = seed_professional(
        api, affiliate["id"], full_name="Anders Holm", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    reviewer = seed_professional(
        api, affiliate["id"], full_name="Renata Silva", grade="PARTNER",
        rotation_role_class="EQ_REVIEWER",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    stale_version = engagement["version"]
    staff_ok(
        api, engagement["id"], lead["id"], "LEAD_PARTNER",
        "2026-10-01T00:00:00Z", "2027-10-01T00:00:00Z", ep_headers=ep_headers,
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "engagement": engagement,
        "reviewer": reviewer,
        "stale_version": stale_version,
        "current_version": engagement_version(api, engagement["id"]),
    }


def scenario_stale_finding_version(api: ApiClient) -> Dict[str, Any]:
    """A writer holding the engagement snapshot taken before a first finding
    advanced it."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(api, legal_name="Mowbray Pumps", industry_code="MANUFACTURING")
    professional = seed_professional(
        api, affiliate["id"], full_name="Selina Vaughn", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    engagement = open_engagement(api, client["id"], ep_headers)
    stale_version = engagement["version"]
    first_finding = raise_finding_ok(
        api, professional["id"], engagement["id"], origin="INSPECTION",
        origin_ref_id="insp-mo-1", finding_type="PROHIBITED_SERVICE",
        severity="CRITICAL", discovered_on="2026-09-15T00:00:00Z",
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "engagement": engagement,
        "first_finding": first_finding,
        "stale_version": stale_version,
        "current_version": engagement_version(api, engagement["id"]),
    }


def scenario_two_engagement_client(api: ApiClient) -> Dict[str, Any]:
    """One client carrying two engagements and one partner."""
    set_clock(api, "2026-10-01T00:00:00Z")
    affiliate = seed_affiliate(api)
    acting = seed_professional(
        api, affiliate["id"], full_name="Acting Partner", grade="PARTNER",
        rotation_role_class="NONE",
    )
    ep_headers = make_engagement_partner_headers(acting["id"])
    client = seed_client(api, legal_name="Foxglove Pharma", industry_code="HEALTHCARE")
    professional = seed_professional(
        api, affiliate["id"], full_name="Nils Bergstrom", grade="PARTNER",
        rotation_role_class="LEAD_PARTNER",
    )
    first = open_engagement(api, client["id"], ep_headers)
    second = open_engagement(
        api, client["id"], ep_headers, engagement_type="REVIEW_ENGAGEMENT",
        fiscal_year_end="2027-06-30T00:00:00Z",
    )
    return {
        "ep_headers": ep_headers,
        "client": client,
        "professional": professional,
        "first": first,
        "second": second,
    }


def scenario_immediate_consistency(api: ApiClient) -> Dict[str, Any]:
    """A submitted 250,050-cent service one step away from approval."""
    set_clock(api, "2026-10-01T00:00:00Z")
    client = seed_client(
        api, legal_name="Corvid Systems", industry_code="TECH",
        naf_annual_cap_cents=5000000,
    )
    service = create_service(
        api, client["id"], service_category="VALUATION", fee_cents=250050
    )
    service_transition_ok(api, service["id"], "SUBMIT_FOR_APPROVAL")
    return {"client": client, "service": service}
