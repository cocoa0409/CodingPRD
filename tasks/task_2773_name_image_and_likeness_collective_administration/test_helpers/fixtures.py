"""Composite setup builders and the shared client fixture.

The harness restarts the server before every test, so each test starts against an
empty database. Every builder below therefore constructs its state from scratch
through published endpoints only — there is no back door into storage.
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import validate_success

from .api_client import NilApiClient
from .factories import (
    athlete_payload,
    athlete_tax_profile_payload,
    clock_payload,
    collective_payload,
    compliance_decision_payload,
    compliance_submission_payload,
    contribution_payload,
    deal_contract_payload,
    deliverable_payload,
    donor_member_payload,
    evidence_payload,
    membership_tier_payload,
    review_payload,
    submission_payload,
    tier_transition_payload,
)
from .test_users import (
    make_admin_headers,
    make_compliance_headers,
    make_director_headers,
    make_reviewer_headers,
    make_treasury_headers,
)


@pytest.fixture
def api() -> NilApiClient:
    """A client aimed at the server under test."""
    return NilApiClient()


# --- Clock ---------------------------------------------------------------


def move_clock(api: NilApiClient, instant: str) -> Dict[str, Any]:
    """Move the logical clock (PRD s2.5); only a PlatformAdmin may."""
    response = api.set_clock(clock_payload(instant), make_admin_headers())
    return validate_success(response, expected_status=200)


# --- Collectives, tiers and donors --------------------------------------


def build_collective(
    api: NilApiClient,
    institution_ipeds_code: str,
    name: str = "Test Collective",
    institution_name: str = "Test Institution",
    home_state_code: str = "OH",
    association_ruleset: str = "NCAA_2024",
    entity_structure: Optional[str] = None,
    communication_policy: Optional[str] = None,
) -> Dict[str, Any]:
    response = api.create_collective(
        collective_payload(
            institution_ipeds_code=institution_ipeds_code,
            name=name,
            institution_name=institution_name,
            home_state_code=home_state_code,
            association_ruleset=association_ruleset,
            entity_structure=entity_structure,
            communication_policy=communication_policy,
        ),
        make_admin_headers(),
    )
    return validate_success(response, expected_status=201)


def build_open_tier(
    api: NilApiClient,
    collective_id: str,
    tier_code: str,
    annual_dues_cents: int,
    benefit_rank: int,
) -> Dict[str, Any]:
    """Create a tier and take it DRAFT -> OPEN so donors may enrol (PRD s3.3)."""
    created = validate_success(
        api.create_membership_tier(
            collective_id,
            membership_tier_payload(tier_code, annual_dues_cents, benefit_rank),
            make_director_headers(),
        ),
        expected_status=201,
    )
    opened = validate_success(
        api.transition_membership_tier(
            created["id"], tier_transition_payload("OPEN"), make_director_headers()
        ),
        expected_status=200,
    )
    return opened


def build_donor(
    api: NilApiClient,
    collective_id: str,
    membership_tier_id: str,
    display_name: str = "Test Donor",
    email: str = "donor@example.com",
    donor_kind: Optional[str] = None,
    annual_agi_cents: Optional[int] = None,
) -> Dict[str, Any]:
    response = api.create_donor_member(
        donor_member_payload(
            collective_id,
            membership_tier_id,
            display_name=display_name,
            email=email,
            donor_kind=donor_kind,
            annual_agi_cents=annual_agi_cents,
        ),
        make_director_headers(),
    )
    return validate_success(response, expected_status=201)


def build_settled_contribution(
    api: NilApiClient,
    donor_member_id: str,
    gross_amount_cents: int,
    designation: Optional[str] = None,
    treasury_user_id: str = "treasury-1",
) -> Dict[str, Any]:
    """A one-time gift approved inline, so it lands in SETTLED (PRD s3.5)."""
    response = api.create_contribution(
        contribution_payload(
            donor_member_id,
            gross_amount_cents,
            source_kind="ONE_TIME_GIFT",
            designation=designation,
            processor_outcome="APPROVE",
        ),
        make_treasury_headers(treasury_user_id),
    )
    return validate_success(response, expected_status=201)


def build_funded_collective(
    api: NilApiClient,
    institution_ipeds_code: str,
    gross_amount_cents: int,
    home_state_code: str = "OH",
    association_ruleset: str = "NCAA_2024",
    entity_structure: Optional[str] = None,
    designation: Optional[str] = None,
    tier_code: str = "T1",
    annual_dues_cents: int = 20000,
    benefit_rank: int = 1,
    donor_kind: Optional[str] = None,
    annual_agi_cents: Optional[int] = None,
    email: str = "donor@example.com",
    name: str = "Test Collective",
    institution_name: str = "Test Institution",
) -> Dict[str, Any]:
    """Collective + OPEN tier + donor + one settled gift, the recurring money-in chain."""
    collective = build_collective(
        api,
        institution_ipeds_code,
        name=name,
        institution_name=institution_name,
        home_state_code=home_state_code,
        association_ruleset=association_ruleset,
        entity_structure=entity_structure,
    )
    tier = build_open_tier(
        api, collective["id"], tier_code, annual_dues_cents, benefit_rank
    )
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        email=email,
        donor_kind=donor_kind,
        annual_agi_cents=annual_agi_cents,
    )
    contribution = build_settled_contribution(
        api, donor["id"], gross_amount_cents, designation=designation
    )
    return {
        "collective": collective,
        "collective_id": collective["id"],
        "tier": tier,
        "tier_id": tier["id"],
        "donor": donor,
        "donor_id": donor["id"],
        "contribution": contribution,
    }


# --- Athletes ------------------------------------------------------------


def build_athlete(
    api: NilApiClient,
    collective_id: str,
    portal_user_id: str,
    full_name: str = "Test Athlete",
    sport: str = "FOOTBALL",
    class_year: int = 2028,
    roster_weight: Optional[int] = None,
    tax_person_kind: Optional[str] = None,
    as_compliance: bool = False,
) -> Dict[str, Any]:
    """Roster an athlete; both a director and a compliance officer may (PRD s3.7)."""
    headers = make_compliance_headers() if as_compliance else make_director_headers()
    response = api.create_athlete(
        athlete_payload(
            collective_id,
            portal_user_id,
            full_name=full_name,
            sport=sport,
            class_year=class_year,
            roster_weight=roster_weight,
            tax_person_kind=tax_person_kind,
        ),
        headers,
    )
    return validate_success(response, expected_status=201)


def record_taxpayer_doc(
    api: NilApiClient,
    athlete_id: str,
    taxpayer_doc_on_file: str,
    treaty_exempt_claimed: Optional[bool] = None,
    treasury_user_id: str = "treasury-1",
) -> Dict[str, Any]:
    """Record taxpayer documentation, which decides the withholding regime (PRD s3.9)."""
    response = api.patch_athlete_tax_profile(
        athlete_id,
        athlete_tax_profile_payload(taxpayer_doc_on_file, treaty_exempt_claimed),
        make_treasury_headers(treasury_user_id),
    )
    return validate_success(response, expected_status=200)


# --- Deal contracts ------------------------------------------------------


def build_draft_contract(
    api: NilApiClient,
    collective_id: str,
    athlete_id: str,
    total_value_cents: int,
    effective_start_at: str = "2026-08-01T00:00:00Z",
    effective_end_at: str = "2026-12-31T00:00:00Z",
    funding_designation: Optional[str] = None,
    exclusivity_category: Optional[str] = None,
) -> Dict[str, Any]:
    response = api.create_deal_contract(
        deal_contract_payload(
            collective_id,
            athlete_id,
            total_value_cents,
            effective_start_at=effective_start_at,
            effective_end_at=effective_end_at,
            funding_designation=funding_designation,
            exclusivity_category=exclusivity_category,
        ),
        make_director_headers(),
    )
    return validate_success(response, expected_status=201)


def clear_disclosure(
    api: NilApiClient,
    contract_id: str,
    state_law_citation: str = "OH-3345.56",
    association_rule_citation: str = "NCAA-2024-12.5",
) -> Dict[str, Any]:
    """File the packet as a director, then have the institution ACCEPT it (PRD s3.8)."""
    validate_success(
        api.submit_compliance_packet(
            contract_id,
            compliance_submission_payload(state_law_citation, association_rule_citation),
            make_director_headers(),
        ),
        expected_status=200,
    )
    return validate_success(
        api.decide_compliance(
            contract_id, compliance_decision_payload("ACCEPT"), make_reviewer_headers()
        ),
        expected_status=200,
    )


def activate_contract(api: NilApiClient, contract_id: str) -> Dict[str, Any]:
    return validate_success(
        api.activate_deal_contract(contract_id, {}, make_director_headers()),
        expected_status=200,
    )


def build_active_contract(
    api: NilApiClient,
    collective_id: str,
    athlete_id: str,
    total_value_cents: int,
    effective_start_at: str = "2026-08-01T00:00:00Z",
    effective_end_at: str = "2026-12-31T00:00:00Z",
    funding_designation: Optional[str] = None,
    exclusivity_category: Optional[str] = None,
    state_law_citation: str = "OH-3345.56",
    association_rule_citation: str = "NCAA-2024-12.5",
) -> Dict[str, Any]:
    """Draft, clear disclosure when the face value requires it, then activate.

    A face value below the 60,000-cent disclosure threshold starts in
    DISCLOSURE_NOT_REQUIRED and needs no packet at all (PRD s3.8).
    """
    contract = build_draft_contract(
        api,
        collective_id,
        athlete_id,
        total_value_cents,
        effective_start_at=effective_start_at,
        effective_end_at=effective_end_at,
        funding_designation=funding_designation,
        exclusivity_category=exclusivity_category,
    )
    if contract["disclosure_status"] == "DISCLOSURE_PENDING":
        clear_disclosure(
            api,
            contract["id"],
            state_law_citation=state_law_citation,
            association_rule_citation=association_rule_citation,
        )
    return activate_contract(api, contract["id"])


# --- Deliverables --------------------------------------------------------


def build_deliverable(
    api: NilApiClient,
    contract_id: str,
    deliverable_kind: str,
    unit_value_cents: int,
    due_at: str,
    required_charity_hours_tenths: Optional[int] = None,
) -> Dict[str, Any]:
    response = api.create_deliverable(
        contract_id,
        deliverable_payload(
            deliverable_kind,
            unit_value_cents,
            due_at,
            required_charity_hours_tenths,
        ),
        make_director_headers(),
    )
    return validate_success(response, expected_status=201)


def add_evidence(
    api: NilApiClient,
    deliverable_id: str,
    evidence_kind: str = "ANALYTICS_SCREENSHOT",
    reference_label: str = "ref-1",
) -> Dict[str, Any]:
    response = api.add_evidence(
        deliverable_id,
        evidence_payload(evidence_kind, reference_label),
        make_director_headers(),
    )
    return validate_success(response, expected_status=201)


def submit_work(
    api: NilApiClient,
    deliverable_id: str,
    performed_at: str,
    charity_hours_tenths: Optional[int] = None,
    submission_note: Optional[str] = None,
) -> Dict[str, Any]:
    response = api.submit_deliverable(
        deliverable_id,
        submission_payload(performed_at, charity_hours_tenths, submission_note),
        make_director_headers(),
    )
    return validate_success(response, expected_status=200)


def review_work(
    api: NilApiClient,
    deliverable_id: str,
    decision: str,
    compliance_user_id: str,
    review_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Only a ComplianceOfficer may review; the handle lands on verified_by_user_id."""
    response = api.review_deliverable(
        deliverable_id,
        review_payload(decision, review_note),
        make_compliance_headers(compliance_user_id),
    )
    return validate_success(response, expected_status=200)


def build_verified_deliverable(
    api: NilApiClient,
    contract_id: str,
    deliverable_kind: str,
    unit_value_cents: int,
    due_at: str,
    performed_at: str,
    compliance_user_id: str,
    evidence_kind: str = "SIGNED_ATTENDANCE_SHEET",
    reference_label: str = "ref-1",
    charity_hours_tenths: Optional[int] = None,
    required_charity_hours_tenths: Optional[int] = None,
) -> Dict[str, Any]:
    """One deliverable carried from PENDING through SUBMITTED to VERIFIED."""
    deliverable = build_deliverable(
        api,
        contract_id,
        deliverable_kind,
        unit_value_cents,
        due_at,
        required_charity_hours_tenths,
    )
    add_evidence(api, deliverable["id"], evidence_kind, reference_label)
    submit_work(api, deliverable["id"], performed_at, charity_hours_tenths)
    return review_work(api, deliverable["id"], "VERIFY", compliance_user_id)


def read_contract(api: NilApiClient, contract_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_deal_contract(contract_id, make_director_headers()), expected_status=200
    )


def read_collective(api: NilApiClient, collective_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_collective(collective_id, make_admin_headers()), expected_status=200
    )


def read_athlete(api: NilApiClient, athlete_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_athlete(athlete_id, make_director_headers()), expected_status=200
    )


def read_deliverable(api: NilApiClient, deliverable_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_deliverable(deliverable_id, make_director_headers()), expected_status=200
    )


def read_donor(api: NilApiClient, donor_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_donor_member(donor_id, make_director_headers()), expected_status=200
    )


def read_release(api: NilApiClient, release_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_payment_release(release_id, make_treasury_headers()), expected_status=200
    )
