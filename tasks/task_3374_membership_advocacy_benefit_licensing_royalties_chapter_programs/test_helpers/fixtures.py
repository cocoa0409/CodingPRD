"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints (the server is restarted before each test, so each test begins
against an empty database). Setup calls use the lenient get_success_data so
failures surface as clear setup errors. Ownership-gated calls thread the
real entity id through the make_*_headers builders.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO, GOV_USER_ID, FIN_USER_ID
from .factories import (
    create_household_payload, create_provider_payload,
    create_license_agreement_payload, create_royalty_statement_payload,
    create_complaint_payload, create_legal_entity_payload,
    create_fund_transfer_payload, create_publication_payload,
    create_chapter_payload, create_course_session_payload,
    create_campaign_payload,
)
from .test_users import (
    TEST_USERS, make_provider_manager_headers, make_chapter_coordinator_headers,
    make_member_headers, make_governance_officer_headers,
    make_finance_controller_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MSA = TEST_USERS["member_services_headers"]
GOV = TEST_USERS["governance_officer_headers"]
OVA = TEST_USERS["oversight_analyst_headers"]
FIN = TEST_USERS["finance_controller_headers"]
STD = TEST_USERS["standards_reviewer_headers"]
ADV = TEST_USERS["advocacy_director_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(iso=CLOCK_START_ISO):
    """Anchor the logical clock (defaults to the pinned startup reading)."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ---------------------------------------------------------------------------
# Households / members / terms
# ---------------------------------------------------------------------------

def create_household_with_term(**overrides):
    """Create a household and read back its initial term.

    Returns (household, term, primary_member_id).
    """
    household = get_success_data(
        api_client.create_household(create_household_payload(**overrides), MSA),
        expected_status=201,
    )
    terms, _meta = _list(api_client.list_household_terms(household["id"], MSA))
    assert len(terms) == 1, f"expected exactly one initial term, got {len(terms)}"
    return household, terms[0], household["primary_member_id"]


def cancel_term_ok(term_id, reason):
    return get_success_data(
        api_client.cancel_term(term_id, {"reason": reason}, MSA),
        expected_status=200,
    )


def get_household(household_id):
    return get_success_data(api_client.get_household(household_id, MSA))


def list_household_terms(household_id):
    rows, _meta = _list(api_client.list_household_terms(household_id, MSA))
    return rows


def list_household_members(household_id, headers=None):
    rows, _meta = _list(
        api_client.list_household_members(household_id, headers or MSA))
    return rows


# ---------------------------------------------------------------------------
# Providers / agreements / royalty statements
# ---------------------------------------------------------------------------

def create_licensed_provider(legal_name="Summit Insurance Group"):
    """Register a provider and admit it to LICENSED. Returns the provider dict."""
    provider = get_success_data(
        api_client.create_provider(create_provider_payload(legal_name=legal_name), GOV),
        expected_status=201,
    )
    provider = get_success_data(api_client.admit_provider(provider["id"], GOV))
    return provider


def get_provider(provider_id):
    return get_success_data(api_client.get_provider(provider_id, GOV))


def create_draft_agreement(provider_id, product_category="INSURANCE_AUTO",
                           effective_from="2026-01-01", effective_to="2030-12-31"):
    """Draft an agreement as the provider's own manager (OCC version is read
    fresh). Returns the DRAFT agreement."""
    provider = get_provider(provider_id)
    payload = create_license_agreement_payload(
        provider["version"], product_category=product_category,
        effective_from=effective_from, effective_to=effective_to,
    )
    return get_success_data(
        api_client.create_license_agreement(
            provider_id, payload, make_provider_manager_headers(provider_id)),
        expected_status=201,
    )


def create_active_agreement(provider_id, product_category="INSURANCE_AUTO",
                            effective_from="2026-01-01", effective_to="2030-12-31"):
    """Draft + ACTIVATE. Returns the ACTIVE agreement."""
    agreement = create_draft_agreement(
        provider_id, product_category, effective_from, effective_to)
    return get_success_data(
        api_client.transition_agreement(agreement["id"], {"action": "ACTIVATE"}, GOV))


def setup_provider_with_active_agreement(product_category="INSURANCE_AUTO",
                                         legal_name="Summit Insurance Group"):
    """LICENSED provider with one ACTIVE agreement. Returns (provider, agreement)."""
    provider = create_licensed_provider(legal_name)
    agreement = create_active_agreement(provider["id"], product_category)
    return provider, agreement


def get_agreement(agreement_id):
    return get_success_data(api_client.get_license_agreement(agreement_id, FIN))


def transition_agreement_ok(agreement_id, action, headers):
    return get_success_data(
        api_client.transition_agreement(agreement_id, {"action": action}, headers))


def submit_statement_ok(agreement_id, provider_id, period_year, period_quarter,
                        reported_sales_cents):
    """Submit a statement with the agreement's fresh OCC version."""
    agreement = get_agreement(agreement_id)
    payload = create_royalty_statement_payload(
        agreement["version"], period_year=period_year,
        period_quarter=period_quarter, reported_sales_cents=reported_sales_cents,
    )
    return get_success_data(
        api_client.submit_royalty_statement(
            agreement_id, payload, make_provider_manager_headers(provider_id)),
        expected_status=201,
    )


def finalize_statement_ok(statement_id, audited_sales_cents):
    return get_success_data(
        api_client.finalize_statement(
            statement_id, {"audited_sales_cents": audited_sales_cents}, FIN))


def list_statements(agreement_id, params=None):
    rows, _meta = _list(
        api_client.list_agreement_statements(agreement_id, FIN, params=params))
    return rows


def setup_agreement_with_two_statements():
    """LICENSED provider + ACTIVE INSURANCE_AUTO agreement + Q1 (80,000,000)
    and Q2 (60,000,000) 2026 statements, both PROVISIONAL.

    Returns (provider, agreement, q1_statement, q2_statement).
    """
    provider, agreement = setup_provider_with_active_agreement(
        "INSURANCE_AUTO", "Atlas Union Insurance Company")
    q1 = submit_statement_ok(agreement["id"], provider["id"], 2026, 1, 80_000_000)
    q2 = submit_statement_ok(agreement["id"], provider["id"], 2026, 2, 60_000_000)
    return provider, agreement, q1, q2


def setup_agreement_with_three_statements():
    """Adds Q3 (400,000,000) to the two-statement scenario. Returns
    (provider, agreement, q1, q2, q3)."""
    provider, agreement = setup_provider_with_active_agreement(
        "TRAVEL_SERVICES", "Odyssey Travel Alliance")
    q1 = submit_statement_ok(agreement["id"], provider["id"], 2026, 1, 80_000_000)
    q2 = submit_statement_ok(agreement["id"], provider["id"], 2026, 2, 60_000_000)
    q3 = submit_statement_ok(agreement["id"], provider["id"], 2026, 3, 400_000_000)
    return provider, agreement, q1, q2, q3


# ---------------------------------------------------------------------------
# Complaints / escalation cascade
# ---------------------------------------------------------------------------

def file_complaint_ok(member_id, agreement_id, category="SERVICE",
                      severity="LOW", description="member complaint"):
    payload = create_complaint_payload(
        member_id, agreement_id, category=category, severity=severity,
        description=description,
    )
    return get_success_data(
        api_client.file_complaint(payload, make_member_headers(member_id)),
        expected_status=201,
    )


def adjudicate_ok(complaint_id, action, resolution_code=None):
    payload = {"action": action}
    if resolution_code is not None:
        payload["resolution_code"] = resolution_code
    return get_success_data(api_client.adjudicate_complaint(complaint_id, payload, OVA))


def file_open_complaint(member_id, agreement_id, **kwargs):
    complaint = file_complaint_ok(member_id, agreement_id, **kwargs)
    adjudicate_ok(complaint["id"], "OPEN_REVIEW")
    return complaint


def escalate_complaint_ok(complaint_id):
    return adjudicate_ok(complaint_id, "ESCALATE")


def escalate_n_complaints(member_id, agreement_id, n, description_prefix="escalation"):
    """File, open, and escalate n complaints against the same agreement.
    Returns the list of complaint dicts (as last seen after escalation)."""
    complaints = []
    for i in range(n):
        c = file_open_complaint(
            member_id, agreement_id, category="SERVICE", severity="HIGH",
            description=f"{description_prefix} {i + 1}")
        complaints.append(escalate_complaint_ok(c["id"]))
    return complaints


def setup_member_and_agreement(category="INSURANCE_HEALTH",
                               legal_name="Meridian Health Plans",
                               state_code="AZ"):
    """LICENSED provider + ACTIVE agreement + one good-standing member.
    Returns (provider, agreement, household, member_id)."""
    provider, agreement = setup_provider_with_active_agreement(category, legal_name)
    household, _term, member_id = create_household_with_term(
        state_code=state_code, term_years=3, primary_full_name="Gail Grant",
        primary_date_of_birth="1963-03-03")
    return provider, agreement, household, member_id


def setup_suspended_provider_five_escalations():
    """Provider driven to SUSPENDED by five escalations on its single ACTIVE
    agreement (all escalated at the current clock). Returns
    (provider, agreement, member_id, complaints)."""
    provider, agreement, _hh, member_id = setup_member_and_agreement(
        "INSURANCE_HEALTH", "Meridian Health Plans")
    complaints = escalate_n_complaints(member_id, agreement["id"], 5)
    return provider, agreement, member_id, complaints


# ---------------------------------------------------------------------------
# Legal entities / fund transfers
# ---------------------------------------------------------------------------

def create_legal_entity_of_kind(kind, balance_cents, display_name=None):
    payload = create_legal_entity_payload(
        kind=kind, display_name=display_name or f"{kind} entity",
        balance_cents=balance_cents)
    return get_success_data(api_client.create_legal_entity(payload, GOV),
                            expected_status=201)


def request_transfer(from_entity_id, to_entity_id, amount_cents,
                     purpose="program grant", requester_id=GOV_USER_ID):
    payload = create_fund_transfer_payload(
        from_entity_id, to_entity_id, amount_cents=amount_cents, purpose=purpose)
    return get_success_data(
        api_client.create_fund_transfer(
            payload, make_governance_officer_headers(requester_id)),
        expected_status=201,
    )


def approve_transfer_ok(transfer_id, approver_id=FIN_USER_ID):
    return get_success_data(
        api_client.decide_fund_transfer(
            transfer_id, {"decision": "APPROVE"},
            make_finance_controller_headers(approver_id)))


def get_legal_entity(entity_id):
    return get_success_data(api_client.get_legal_entity(entity_id, GOV))


def setup_membership_and_foundation():
    """MEMBERSHIP_ORG (100,000,000) + FOUNDATION (200,000,000).
    Returns (membership_org, foundation)."""
    mo = create_legal_entity_of_kind("MEMBERSHIP_ORG", 100_000_000,
                                     "Membership Organization")
    fdn = create_legal_entity_of_kind("FOUNDATION", 200_000_000,
                                      "Charitable Foundation")
    return mo, fdn


# ---------------------------------------------------------------------------
# Publications / advertising
# ---------------------------------------------------------------------------

def create_publication_ok(title="October Issue", publication_date="2026-10-01",
                          min_cpm_cents=2000, max_cpm_cents=5000):
    from .factories import create_publication_payload as _mk
    return get_success_data(
        api_client.create_publication(
            _mk(title=title, publication_date=publication_date,
                min_cpm_cents=min_cpm_cents, max_cpm_cents=max_cpm_cents), STD),
        expected_status=201,
    )


def get_publication(publication_id):
    return get_success_data(api_client.get_publication(publication_id, STD))


# ---------------------------------------------------------------------------
# Chapters / course sessions
# ---------------------------------------------------------------------------

def create_chapter_ok(name="Austin Chapter", state_code="TX", city="Austin"):
    return get_success_data(
        api_client.create_chapter(
            create_chapter_payload(name=name, state_code=state_code, city=city), MSA),
        expected_status=201,
    )


def create_session_ok(chapter_id, **overrides):
    """Schedule a session as the chapter's own coordinator."""
    return get_success_data(
        api_client.create_course_session(
            chapter_id, create_course_session_payload(**overrides),
            make_chapter_coordinator_headers(chapter_id)),
        expected_status=201,
    )


def list_chapter_sessions(chapter_id):
    rows, _meta = _list(
        api_client.list_chapter_sessions(
            chapter_id, make_chapter_coordinator_headers(chapter_id)))
    return rows


# ---------------------------------------------------------------------------
# Campaigns / mobilization
# ---------------------------------------------------------------------------

def create_lobby_arm(balance_cents=5_000_000):
    return create_legal_entity_of_kind("LOBBY_ARM", balance_cents,
                                       "Advocacy Lobby Arm")


def create_campaign_ok(sponsor_entity_id, **overrides):
    return get_success_data(
        api_client.create_campaign(
            create_campaign_payload(sponsor_entity_id, **overrides), ADV),
        expected_status=201,
    )


def get_campaign(campaign_id):
    return get_success_data(api_client.get_campaign(campaign_id, ADV))


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _list(response):
    """Validate a paginated list response and return (rows, meta)."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)
