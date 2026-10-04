"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database
(the harness restarts the server before every test) and uses get_success_data
so a setup failure raises a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    add_constituent_payload,
    create_agreement_payload,
    create_category_payload,
    create_fund_company_payload,
    create_fund_payload,
    create_holdings_payload,
    create_index_payload,
    create_licensee_payload,
    create_methodology_payload,
    grant_seat_payload,
    propose_change_payload,
    raise_dispute_payload,
)
from .test_users import (
    TEST_USERS,
    make_analyst_headers,
    make_fund_company_rep_headers,
)

OPS = TEST_USERS["research_ops_headers"]
LIC = TEST_USERS["license_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: simple creation / state progression
# ---------------------------------------------------------------------------

def create_fund_company(legal_name="Test Co", commercial_relationship="NONE"):
    """Create a FundCompany. Returns the company dict."""
    resp = api_client.create_fund_company(
        create_fund_company_payload(
            legal_name=legal_name, commercial_relationship=commercial_relationship
        ),
        OPS,
    )
    return get_success_data(resp)


def create_fund(fund_company_id, **overrides):
    """Create a Fund under the given company. Returns the fund dict."""
    resp = api_client.create_fund(
        create_fund_payload(fund_company_id, **overrides), OPS
    )
    return get_success_data(resp)


def ingest_holdings(fund_id, holdings=None, as_of_date="2026-08-31"):
    """Ingest a holdings snapshot. Returns the response data."""
    resp = api_client.ingest_holdings(
        fund_id, create_holdings_payload(holdings=holdings, as_of_date=as_of_date), OPS
    )
    return get_success_data(resp)


def create_category(**overrides):
    resp = api_client.create_category(create_category_payload(**overrides), OPS)
    return get_success_data(resp)


def create_and_activate_methodology(**overrides):
    """Create a methodology and activate it. Returns the activated methodology."""
    resp = api_client.create_methodology(create_methodology_payload(**overrides), OPS)
    meth = get_success_data(resp)
    resp = api_client.activate_methodology(meth["id"], OPS)
    return get_success_data(resp)


def create_licensee(licensee_name="Test Licensee"):
    resp = api_client.create_licensee(
        create_licensee_payload(licensee_name=licensee_name), LIC
    )
    return get_success_data(resp)


def create_and_activate_agreement(licensee_id, **overrides):
    """Create an agreement and activate it. Returns the ACTIVE agreement."""
    resp = api_client.create_license_agreement(
        create_agreement_payload(licensee_id, **overrides), LIC
    )
    ag = get_success_data(resp)
    resp = api_client.activate_agreement(ag["id"], LIC)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: hierarchy — company + fund (+ holdings)
# ---------------------------------------------------------------------------

def setup_company_with_fund(
    legal_name="Test Co",
    commercial_relationship="NONE",
    with_holdings=True,
    fund_overrides=None,
    holdings=None,
):
    """Returns (company, fund). When with_holdings, ingests one valid snapshot."""
    company = create_fund_company(legal_name, commercial_relationship)
    fund = create_fund(company["id"], **(fund_overrides or {}))
    if with_holdings:
        ingest_holdings(fund["id"], holdings=holdings)
        fund = get_success_data(api_client.get_fund(fund["id"], OPS))
    return company, fund


def setup_rateable_fund(
    legal_name="Rateable Co",
    commercial_relationship="NONE",
    methodology_overrides=None,
    fund_overrides=None,
    holdings=None,
):
    """Company + fund + holdings + an EFFECTIVE methodology.
    Returns (company, fund, methodology)."""
    company, fund = setup_company_with_fund(
        legal_name=legal_name,
        commercial_relationship=commercial_relationship,
        with_holdings=True,
        fund_overrides=fund_overrides,
        holdings=holdings,
    )
    methodology = create_and_activate_methodology(**(methodology_overrides or {}))
    return company, fund, methodology


# ---------------------------------------------------------------------------
# Tier 3: ratings lifecycle shortcuts
# ---------------------------------------------------------------------------

def compute_quantitative_rating(fund_id, methodology_id):
    resp = api_client.compute_rating(
        {"fund_id": fund_id, "methodology_id": methodology_id}, OPS
    )
    return get_success_data(resp)


def create_published_quant_rating(company=None, fund=None, methodology=None):
    """Compute and publish a quantitative rating on a fresh rateable setup.
    Returns (company, fund, methodology, rating)."""
    if methodology is None:
        company, fund, methodology = setup_rateable_fund()
    rating = compute_quantitative_rating(fund["id"], methodology["id"])
    published = get_success_data(api_client.publish_rating(rating["id"], OPS))
    return company, fund, methodology, published


def create_analyst_rating(fund_id, methodology_id, analyst_id="analyst-lead"):
    """Analyst initiates an analyst rating. Returns the PROVISIONAL rating."""
    resp = api_client.initiate_analyst_rating(
        {"fund_id": fund_id, "methodology_id": methodology_id},
        make_analyst_headers(analyst_id),
    )
    return get_success_data(resp)


def open_proposal(rating_id, proposed_grade, analyst_id="analyst-lead"):
    resp = api_client.open_proposal(
        rating_id, {"proposed_grade": proposed_grade}, make_analyst_headers(analyst_id)
    )
    return get_success_data(resp)


def cast_vote(proposal_id, vote, voter_id):
    resp = api_client.cast_vote(
        proposal_id, {"vote": vote}, make_analyst_headers(voter_id)
    )
    return resp


def cast_vote_ok(proposal_id, vote, voter_id):
    return get_success_data(cast_vote(proposal_id, vote, voter_id))


def approve_proposal(proposal_id, approvers=("voter-a", "voter-b"), extra_votes=()):
    """Cast votes that drive the proposal to APPROVED:
    >=2 approvals, >=3 total votes, approvals > rejections."""
    cast_vote_ok(proposal_id, "APPROVE", approvers[0])
    cast_vote_ok(proposal_id, "APPROVE", approvers[1])
    for vote, voter in extra_votes:
        cast_vote_ok(proposal_id, vote, voter)
    if not extra_votes:
        cast_vote_ok(proposal_id, "ABSTAIN", "voter-c")
    return get_success_data(api_client.get_proposal(proposal_id, OPS))


# ---------------------------------------------------------------------------
# Tier 4: seat / agreement helpers with OCC version threading
# ---------------------------------------------------------------------------

def get_agreement_version(agreement_id):
    ag = get_success_data(api_client.get_license_agreement(agreement_id, LIC))
    return ag["version"]


def grant_seat_ok(agreement_id, workstation_user_id):
    """Grant a seat using the agreement's current version. Returns the seat."""
    version = get_agreement_version(agreement_id)
    resp = api_client.grant_seat(
        agreement_id,
        grant_seat_payload(version, workstation_user_id=workstation_user_id),
        LIC,
    )
    return get_success_data(resp)


def setup_licensee_with_active_agreement(
    licensee_name="Test Licensee", tier="DISPLAY", seat_limit=5, **overrides
):
    """Returns (licensee, active_agreement)."""
    licensee = create_licensee(licensee_name)
    agreement = create_and_activate_agreement(
        licensee["id"], tier=tier, seat_limit=seat_limit, **overrides
    )
    return licensee, agreement


# ---------------------------------------------------------------------------
# Tier 5: index / licensing composites
# ---------------------------------------------------------------------------

def setup_licensed_index(
    methodology,
    index_overrides=None,
    tier="DERIVED_WORKS",
    licensee_name="Index Licensee",
):
    """Licensee + ACTIVE agreement (default DERIVED_WORKS) + index linked to it.
    Returns (licensee, agreement, index)."""
    licensee, agreement = setup_licensee_with_active_agreement(
        licensee_name=licensee_name, tier=tier
    )
    resp = api_client.create_index(
        create_index_payload(methodology["id"], **(index_overrides or {})), LIC
    )
    index = get_success_data(resp)
    get_success_data(
        api_client.link_license(index["id"], {"licensed_agreement_id": agreement["id"]}, LIC)
    )
    index = get_success_data(api_client.get_index(index["id"], LIC))
    return licensee, agreement, index


def add_constituent_ok(index_id, fund_id, target_weight_bp):
    resp = api_client.add_constituent(
        index_id,
        add_constituent_payload(fund_id, target_weight_bp=target_weight_bp),
        LIC,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Dispute helpers (FundCompanyRep identity threading)
# ---------------------------------------------------------------------------

def raise_dispute_ok(fund_id, company_id, disputed_field="RISK_SCORE", corrected_value=1000):
    """Raise a dispute as the issuer rep. Returns the OPEN dispute."""
    resp = api_client.raise_dispute(
        fund_id,
        raise_dispute_payload(
            company_id, disputed_field=disputed_field, corrected_value=corrected_value
        ),
        make_fund_company_rep_headers(company_id),
    )
    return get_success_data(resp)


def investigate_dispute_ok(dispute_id):
    resp = api_client.investigate_dispute(dispute_id, OPS)
    return get_success_data(resp)


def resolve_dispute_ok(dispute_id, outcome, resolution_note="resolved"):
    dispute = get_success_data(api_client.get_dispute(dispute_id, OPS))
    resp = api_client.resolve_dispute(
        dispute_id,
        {
            "outcome": outcome,
            "resolution_note": resolution_note,
            "expected_dispute_version": dispute["version"],
        },
        OPS,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Methodology change helpers
# ---------------------------------------------------------------------------

def propose_change_ok(methodology_id, restatement_required=False, effective_date="2026-09-01"):
    meth = get_success_data(api_client.get_methodology(methodology_id, OPS))
    resp = api_client.propose_methodology_change(
        methodology_id,
        propose_change_payload(
            meth["version"],
            restatement_required=restatement_required,
            effective_date=effective_date,
        ),
        OPS,
    )
    return get_success_data(resp)


def approve_change_ok(change_id):
    return get_success_data(api_client.approve_change(change_id, OPS))


def record_notice_ok(change_id, licensee_id, channel="EMAIL"):
    resp = api_client.record_notice(
        change_id, {"licensee_id": licensee_id, "notice_channel": channel}, OPS
    )
    return get_success_data(resp)


def set_clock(iso=DEFAULT_CLOCK_ISO):
    resp = api_client.set_clock({"to_iso8601": iso}, OPS)
    return get_success_data(resp)
