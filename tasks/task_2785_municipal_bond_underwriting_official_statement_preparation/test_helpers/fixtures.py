"""Setup builders: granular step helpers and composite scenario builders.

The harness restarts the API server before every test, so every fixture builds
its world from an empty database. Two layers live here:

* **Step helpers** (``register_issuer``, ``add_tranche``, ``approve_section`` ...)
  perform exactly one API call and return the created or updated row. They use
  the lenient ``get_success_data`` validator, because a setup step that fails
  should surface as a setup error rather than a bogus assertion failure.
* **Scenario builders** (``structuring_deal``, ``priced_negotiated_deal``,
  ``awarded_competitive_deal`` ...) drive the workflow to a named milestone and
  return a ``SimpleNamespace`` carrying every identifier and header a test needs.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    CANONICAL_TRANCHE_PRINCIPAL_USD,
    CLOCK_EPOCH,
    ENTITY_TYPE_SURCHARGE,
    MIN_RECORD_RETENTION_YEARS,
    NEGOTIATED_TAKEDOWN_PER_BOND_USD,
    WATERFALL_O1_REQUESTED_USD,
    WATERFALL_O2_REQUESTED_USD,
    WATERFALL_O3_REQUESTED_USD,
    WATERFALL_O4_REQUESTED_USD,
    plus_hours,
    plus_minutes,
)
from .test_users import (
    BOND_COUNSEL_DRAFTER_HEADERS,
    BOND_COUNSEL_REVIEWER_HEADERS,
    COMPLIANCE_HEADERS,
    RATING_ANALYST_HEADERS,
    make_advisor_headers,
    make_issuer_official_headers,
    make_underwriter_headers,
)
from .types import (
    DocType,
    EntityType,
    FirmType,
    MemberRole,
    OrderType,
    PeriodType,
    PriorityPolicy,
    RatingAgency,
    SaleMethod,
    SectionType,
    UserRole,
)


# ---------------------------------------------------------------------------
# Step helpers: participants (PRD section 3.1)
# ---------------------------------------------------------------------------
def register_issuer(client, headers=None, **overrides):
    """Register an issuer. Defaults to acting as ComplianceOfficer.

    The first issuer in a test cannot be created by an ``IssuerOfficial``,
    because that role's ``X-User-ID`` must already resolve to an ``Issuer.id``
    (PRD section 2.1); ``ComplianceOfficer`` is opaque and always available.
    """
    response = client.create_issuer(
        f.issuer_payload(**overrides), headers or COMPLIANCE_HEADERS
    )
    return get_success_data(response, 201)


def register_high_risk_issuer(client, headers=None, **overrides):
    """An AUTHORITY with a prior material event: risk score exactly forty.

    PRD section 3.1: "an AUTHORITY with a material event and a clean filing
    record scores exactly forty."
    """
    payload = {
        "entity_type": EntityType.AUTHORITY,
        "has_prior_material_event": True,
    }
    payload.update(overrides)
    return register_issuer(client, headers, **payload)


def register_below_gate_issuer(client, headers=None, **overrides):
    """An AUTHORITY with three late event notices: risk score exactly thirty-nine.

    PRD section 3.1: "An AUTHORITY with three late event notices and no material
    event therefore scores thirty-nine."
    """
    payload = {
        "entity_type": EntityType.AUTHORITY,
        "prior_late_event_notices": 3,
    }
    payload.update(overrides)
    return register_issuer(client, headers, **payload)


def register_firm(client, firm_type=FirmType.UNDERWRITER, headers=None, **overrides):
    """Register a firm. PRD section 4 reserves this to a ``ComplianceOfficer``."""
    response = client.create_firm(
        f.firm_payload(firm_type, **overrides), headers or COMPLIANCE_HEADERS
    )
    return get_success_data(response, 201)


def register_advisor_firm(client, **overrides):
    """A firm whose ``firm_type`` admits a ``MunicipalAdvisor`` actor."""
    return register_firm(client, FirmType.MUNICIPAL_ADVISOR, **overrides)


def register_underwriter_firm(client, **overrides):
    """A firm whose ``firm_type`` admits an ``Underwriter`` actor."""
    return register_firm(client, FirmType.UNDERWRITER, **overrides)


# ---------------------------------------------------------------------------
# Step helpers: deals and maturities (PRD section 3.2)
# ---------------------------------------------------------------------------
def create_deal(client, issuer_id, advisor_firm_id=None, headers=None, **overrides):
    """Open a deal in DRAFT, acting as the issuer's own official by default."""
    payload = f.deal_payload(issuer_id, **overrides)
    if advisor_firm_id is not None and "municipal_advisor_firm_id" not in overrides:
        payload["municipal_advisor_firm_id"] = advisor_firm_id
    response = client.create_deal(
        payload, headers or make_issuer_official_headers(issuer_id)
    )
    return get_success_data(response, 201)


def add_tranche(client, deal_id, advisor_headers, payload):
    """Add one maturity, which prices it immediately (PRD section 3.2)."""
    response = client.create_maturity_tranche(deal_id, payload, advisor_headers)
    return get_success_data(response, 201)


def submit_structure(client, deal_id, advisor_headers):
    """Freeze the schedule: DRAFT -> STRUCTURING (PRD section 3.2)."""
    return get_success_data(client.submit_structure(deal_id, None, advisor_headers), 200)


def designate_sale_method(client, deal_id, sale_method, headers):
    """Take the sale-method fork (PRD section 3.6)."""
    return get_success_data(
        client.designate_sale_method(deal_id, f.sale_method_payload(sale_method), headers),
        200,
    )


def read_deal(client, deal_id, headers):
    """Read a deal, which is where the OCC token for disclosure comes from."""
    return get_success_data(client.get_deal(deal_id, headers), 200)


def list_tranches(client, deal_id, headers, **params):
    """The deal's maturity schedule in ``sequence_number`` order."""
    response = client.list_deal_maturity_tranches(deal_id, headers, **params)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Step helpers: credit enhancement (PRD section 3.3)
# ---------------------------------------------------------------------------
def propose_enhancement(client, deal_id, insured_tranche_ids, headers, **overrides):
    response = client.create_credit_enhancement(
        deal_id, f.enhancement_payload(insured_tranche_ids, **overrides), headers
    )
    return get_success_data(response, 201)


def commit_enhancement(client, enhancement_id, issuer_headers):
    return get_success_data(
        client.commit_credit_enhancement(enhancement_id, None, issuer_headers), 200
    )


def withdraw_enhancement(client, enhancement_id, issuer_headers, reason="Insurer downgraded"):
    return get_success_data(
        client.withdraw_credit_enhancement(
            enhancement_id, f.withdraw_payload(reason), issuer_headers
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Step helpers: disclosure (PRD section 3.4)
# ---------------------------------------------------------------------------
def create_official_statement(client, deal_id, expected_deal_version, headers, **overrides):
    """Start an official statement; the one version-guarded creation."""
    response = client.create_official_statement(
        deal_id, f.official_statement_payload(expected_deal_version, **overrides), headers
    )
    return get_success_data(response, 201)


def start_official_statement(client, deal_id, headers, reader_headers=None, **overrides):
    """Read the deal for its ``version``, then start a statement against it."""
    deal = read_deal(client, deal_id, reader_headers or headers)
    return create_official_statement(client, deal_id, deal["version"], headers, **overrides)


def add_section(client, statement_id, payload, headers=None):
    """Add a section, authored by the acting ``BondCounsel`` (PRD section 3.4)."""
    response = client.create_section(
        statement_id, payload, headers or BOND_COUNSEL_DRAFTER_HEADERS
    )
    return get_success_data(response, 201)


def approve_section(client, section_id, headers=None):
    """Approve a section as a different ``BondCounsel`` than its author."""
    response = client.approve_section(
        section_id, None, headers or BOND_COUNSEL_REVIEWER_HEADERS
    )
    return get_success_data(response, 200)


def submit_for_review(client, statement_id, headers=None):
    response = client.submit_for_review(
        statement_id, None, headers or BOND_COUNSEL_DRAFTER_HEADERS
    )
    return get_success_data(response, 200)


def request_revision(client, statement_id, advisor_headers, reason="Expand risk factors"):
    response = client.request_revision(
        statement_id, f.revision_payload(reason), advisor_headers
    )
    return get_success_data(response, 200)


def resume_drafting(client, statement_id, headers=None):
    response = client.resume_drafting(
        statement_id, None, headers or BOND_COUNSEL_DRAFTER_HEADERS
    )
    return get_success_data(response, 200)


def post_preliminary(client, statement_id, advisor_headers):
    return get_success_data(
        client.post_preliminary(statement_id, None, advisor_headers), 200
    )


def post_final(client, statement_id, advisor_headers):
    return get_success_data(client.post_final(statement_id, None, advisor_headers), 200)


def draft_undertaking(client, deal_id, headers, **overrides):
    response = client.create_undertaking(deal_id, f.undertaking_payload(**overrides), headers)
    return get_success_data(response, 201)


def activate_undertaking(client, undertaking_id, issuer_headers):
    return get_success_data(
        client.activate_undertaking(undertaking_id, None, issuer_headers), 200
    )


def approve_mandatory_sections(client, statement_id):
    """Author and approve one section in each of the four mandatory categories.

    PRD section 3.4 makes ``mandatory_sections_approved`` true only when each of
    ``RISK_FACTOR``, ``TAX_MATTERS``, ``CONTINUING_DISCLOSURE`` and
    ``UNDERWRITING`` carries an approved section and at least one approved
    ``RISK_FACTOR`` section has ``is_material_risk`` true. The
    ``CONTINUING_DISCLOSURE`` section here is also flagged material, so the same
    package satisfies the high-risk-issuer gate of PRD section 3.4.
    """
    sections = {}
    sections[SectionType.RISK_FACTOR] = add_section(
        client, statement_id, f.material_risk_section_payload()
    )
    sections[SectionType.TAX_MATTERS] = add_section(
        client, statement_id, f.section_payload(SectionType.TAX_MATTERS)
    )
    sections[SectionType.CONTINUING_DISCLOSURE] = add_section(
        client, statement_id, f.continuing_disclosure_risk_section_payload()
    )
    sections[SectionType.UNDERWRITING] = add_section(
        client, statement_id, f.section_payload(SectionType.UNDERWRITING)
    )
    approved = {}
    for section_type, section in sections.items():
        approved[section_type] = approve_section(client, section["id"])
    return approved


# ---------------------------------------------------------------------------
# Step helpers: rating agency coordination (PRD section 3.5)
# ---------------------------------------------------------------------------
def request_rating(client, deal_id, headers, agency=RatingAgency.MOODYS, **overrides):
    response = client.create_rating_engagement(
        deal_id, f.rating_engagement_payload(agency, **overrides), headers
    )
    return get_success_data(response, 201)


def acknowledge_engagement(client, engagement_id, analyst_headers=None):
    response = client.acknowledge_engagement(
        engagement_id, None, analyst_headers or RATING_ANALYST_HEADERS
    )
    return get_success_data(response, 200)


def schedule_presentation(client, engagement_id, headers, starts_at, ends_at, **overrides):
    response = client.create_presentation(
        engagement_id, f.presentation_payload(starts_at, ends_at, **overrides), headers
    )
    return get_success_data(response, 201)


def cancel_presentation(client, presentation_id, headers, reason="Rescheduling"):
    response = client.cancel_presentation(
        presentation_id, f.cancellation_payload(reason), headers
    )
    return get_success_data(response, 200)


def set_clock(client, current_utc, headers=None):
    """Move the logical clock, promoting any due presentation to HELD."""
    response = client.set_clock(current_utc, headers or COMPLIANCE_HEADERS)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Step helpers: syndicate (PRD section 3.6)
# ---------------------------------------------------------------------------
def seat_member(
    client,
    deal_id,
    firm_id,
    headers,
    member_role=MemberRole.SENIOR_MANAGER,
    liability_pct=100.0000,
    takedown_share_pct=100.0000,
    priority_rank=1,
    **overrides,
):
    response = client.create_syndicate_member(
        deal_id,
        f.syndicate_member_payload(
            firm_id,
            member_role,
            liability_pct,
            takedown_share_pct,
            priority_rank,
            **overrides,
        ),
        headers,
    )
    return get_success_data(response, 201)


# ---------------------------------------------------------------------------
# Step helpers: the order book (PRD section 3.7)
# ---------------------------------------------------------------------------
def schedule_order_period(client, deal_id, headers, payload=None, **overrides):
    response = client.create_order_period(
        deal_id, payload or f.default_order_period_payload(**overrides), headers
    )
    return get_success_data(response, 201)


def open_period(client, period_id, underwriter_headers):
    return get_success_data(
        client.open_order_period(period_id, None, underwriter_headers), 200
    )


def close_period(client, period_id, underwriter_headers):
    return get_success_data(
        client.close_order_period(period_id, None, underwriter_headers), 200
    )


def reopen_period(client, period_id, reason="Allotment error discovered", headers=None):
    response = client.reopen_order_period(
        period_id, f.reopen_payload(reason), headers or COMPLIANCE_HEADERS
    )
    return get_success_data(response, 200)


def read_period(client, period_id, headers):
    """Read a period, which is where the OCC token for order entry comes from."""
    return get_success_data(client.get_order_period(period_id, headers), 200)


def place_order(
    client,
    period_id,
    tranche_id,
    member_id,
    underwriter_headers,
    order_type=OrderType.INSTITUTIONAL_PRIORITY,
    par_requested_usd=1000000,
    **overrides,
):
    """Read the period for its ``version``, then enter one order against it."""
    period = read_period(client, period_id, underwriter_headers)
    payload = f.order_payload(
        tranche_id,
        member_id,
        period["version"],
        order_type,
        par_requested_usd,
        **overrides,
    )
    return get_success_data(client.create_order(period_id, payload, underwriter_headers), 201)


def cancel_order(client, order_id, underwriter_headers, reason="Investor withdrew"):
    response = client.cancel_order(
        order_id, f.cancellation_payload(reason), underwriter_headers
    )
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Step helpers: pricing, award, closing (PRD sections 3.8, 3.9)
# ---------------------------------------------------------------------------
def price_negotiated(client, deal_id, underwriter_headers, **overrides):
    response = client.price_deal(
        deal_id, f.negotiated_pricing_payload(**overrides), underwriter_headers
    )
    return get_success_data(response, 200)


def price_competitive(client, deal_id, underwriter_headers, **overrides):
    response = client.price_deal(
        deal_id, f.competitive_pricing_payload(**overrides), underwriter_headers
    )
    return get_success_data(response, 200)


def award(client, deal_id, issuer_headers):
    return get_success_data(client.award_deal(deal_id, None, issuer_headers), 200)


def complete_handoff(client, deal_id, record_retention_years=MIN_RECORD_RETENTION_YEARS,
                     headers=None):
    response = client.post_issuance_handoff(
        deal_id, f.handoff_payload(record_retention_years), headers or COMPLIANCE_HEADERS
    )
    return get_success_data(response, 200)


def list_closing_documents(client, deal_id, headers, **params):
    response = client.list_deal_closing_documents(deal_id, headers, **params)
    return get_success_data(response, 200)


def documents_by_type(client, deal_id, headers):
    """Map ``doc_type`` to the closing document row, since award is their only source."""
    return {doc["doc_type"]: doc for doc in list_closing_documents(client, deal_id, headers)}


def execute_document(client, document_id, headers, signatory_name="Jordan Signatory"):
    response = client.execute_closing_document(
        document_id, f.execute_payload(signatory_name), headers
    )
    return get_success_data(response, 200)


def waive_document(client, document_id, reason="Substituted by counsel letter", headers=None):
    response = client.waive_closing_document(
        document_id, f.waiver_payload(reason), headers or COMPLIANCE_HEADERS
    )
    return get_success_data(response, 200)


def close_deal(client, deal_id, headers=None):
    return get_success_data(
        client.close_deal(deal_id, None, headers or COMPLIANCE_HEADERS), 200
    )


def cancel_deal(client, deal_id, issuer_headers, reason="Market conditions"):
    response = client.cancel_deal(deal_id, f.cancellation_payload(reason), issuer_headers)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------
def participants(client, advisor_firm_type=FirmType.MUNICIPAL_ADVISOR, **issuer_overrides):
    """An issuer, an advisory firm and an underwriting firm, with their headers.

    PRD section 2.1 makes ``IssuerOfficial``, ``MunicipalAdvisor`` and
    ``Underwriter`` entity-backed, so their headers cannot exist before the rows
    they name.
    """
    issuer = register_issuer(client, **issuer_overrides)
    advisor_firm = register_firm(client, advisor_firm_type)
    underwriter_firm = register_underwriter_firm(client)
    return SimpleNamespace(
        client=client,
        compliance_headers=COMPLIANCE_HEADERS,
        counsel_headers=BOND_COUNSEL_DRAFTER_HEADERS,
        reviewer_headers=BOND_COUNSEL_REVIEWER_HEADERS,
        analyst_headers=RATING_ANALYST_HEADERS,
        issuer=issuer,
        issuer_id=issuer["id"],
        issuer_headers=make_issuer_official_headers(issuer["id"]),
        advisor_firm=advisor_firm,
        advisor_firm_id=advisor_firm["id"],
        advisor_headers=make_advisor_headers(advisor_firm["id"]),
        underwriter_firm=underwriter_firm,
        underwriter_firm_id=underwriter_firm["id"],
        underwriter_headers=make_underwriter_headers(underwriter_firm["id"]),
    )


def draft_deal(client, ctx=None, tranches=True, **deal_overrides):
    """A DRAFT deal with the canonical two-tranche schedule already priced.

    The advisor firm is engaged at creation, because PRD section 2.1 resolves a
    ``MunicipalAdvisor`` actor against the deal's ``municipal_advisor_firm_id``
    and every later advisor act on the deal depends on that ownership.
    """
    ctx = ctx or participants(client)
    deal = create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        **deal_overrides,
    )
    ctx.deal = deal
    ctx.deal_id = deal["id"]
    ctx.tranches = []
    if tranches:
        ctx.tranches = [
            add_tranche(
                client, ctx.deal_id, ctx.advisor_headers, f.canonical_tranche_1_payload()
            ),
            add_tranche(
                client, ctx.deal_id, ctx.advisor_headers, f.canonical_tranche_2_payload()
            ),
        ]
    ctx.tranche_ids = [t["id"] for t in ctx.tranches]
    return ctx


def structuring_deal(client, ctx=None, **deal_overrides):
    """A deal whose schedule is frozen: STRUCTURING (PRD section 3.2)."""
    ctx = draft_deal(client, ctx, **deal_overrides)
    ctx.deal = submit_structure(client, ctx.deal_id, ctx.advisor_headers)
    ctx.tranches = list_tranches(client, ctx.deal_id, ctx.advisor_headers)
    ctx.tranche_ids = [t["id"] for t in ctx.tranches]
    return ctx


def negotiated_pricing_deal(client, ctx=None, **deal_overrides):
    """A negotiated deal on its pricing branch: PRICING_NEGOTIATED.

    A single senior manager holds the whole book, so the ``liability_pct`` sum is
    exactly 100.0000 -- which PRD section 3.8 requires at pricing, not merely at
    seating.
    """
    ctx = structuring_deal(client, ctx, **deal_overrides)
    ctx.senior_member = seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.underwriter_headers,
        MemberRole.SENIOR_MANAGER,
    )
    ctx.members = [ctx.senior_member]
    ctx.member_ids = [ctx.senior_member["id"]]
    ctx.deal = designate_sale_method(
        client, ctx.deal_id, SaleMethod.NEGOTIATED, ctx.advisor_headers
    )
    ctx.sale_method = SaleMethod.NEGOTIATED
    return ctx


def competitive_pricing_deal(client, ctx=None, **deal_overrides):
    """A competitive deal on its pricing branch: PRICING_COMPETITIVE.

    PRD section 3.6 forbids any ``SyndicateMember`` row on a competitive deal, so
    the underwriter here acts under the competitive carve-out of PRD section 2.1.
    """
    ctx = structuring_deal(client, ctx, **deal_overrides)
    ctx.members = []
    ctx.member_ids = []
    ctx.deal = designate_sale_method(
        client, ctx.deal_id, SaleMethod.COMPETITIVE, ctx.advisor_headers
    )
    ctx.sale_method = SaleMethod.COMPETITIVE
    return ctx


def with_active_undertaking(ctx):
    """Draft and activate the Rule 15c2-12 undertaking on ``ctx.deal_id``."""
    undertaking = draft_undertaking(ctx.client, ctx.deal_id, ctx.advisor_headers)
    ctx.undertaking = activate_undertaking(ctx.client, undertaking["id"], ctx.issuer_headers)
    ctx.undertaking_id = ctx.undertaking["id"]
    return ctx


def with_drafting_statement(ctx, **overrides):
    """Start an official statement on ``ctx.deal_id`` and leave it in DRAFTING."""
    ctx.statement = start_official_statement(
        ctx.client, ctx.deal_id, ctx.advisor_headers, **overrides
    )
    ctx.statement_id = ctx.statement["id"]
    return ctx


def with_approved_sections(ctx):
    """Author and approve the four mandatory disclosure categories."""
    ctx.sections = approve_mandatory_sections(ctx.client, ctx.statement_id)
    ctx.section_ids = {k: v["id"] for k, v in ctx.sections.items()}
    return ctx


def with_statement_in_review(ctx):
    """Statement in IN_REVIEW with every mandatory category approved."""
    with_drafting_statement(ctx)
    with_approved_sections(ctx)
    ctx.statement = submit_for_review(ctx.client, ctx.statement_id)
    return ctx


def cleared_disclosure(ctx):
    """Post the preliminary statement so ``disclosure_clearance`` reads CLEARED.

    PRD section 3.4 gates the posting on the deal already being on a pricing
    branch, on ``mandatory_sections_approved``, on an ACTIVE undertaking, and --
    for a high-risk issuer -- on an approved material CONTINUING_DISCLOSURE
    section, all of which the steps below satisfy.
    """
    with_active_undertaking(ctx)
    with_statement_in_review(ctx)
    ctx.statement = post_preliminary(ctx.client, ctx.statement_id, ctx.advisor_headers)
    ctx.deal = read_deal(ctx.client, ctx.deal_id, ctx.advisor_headers)
    return ctx


def with_completed_allotment_run(ctx, payload=None):
    """Schedule, open and close one order period so pricing's book gate is met.

    PRD section 3.8 requires "at least one order period of the deal must be
    CLOSED with allotment_run_count of one or more", and PRD section 3.7 makes
    closing a period that holds no PENDING orders entirely legal, so an empty
    book satisfies the gate.
    """
    period = schedule_order_period(
        ctx.client,
        ctx.deal_id,
        ctx.advisor_headers,
        payload or f.default_order_period_payload(),
    )
    ctx.period_id = period["id"]
    open_period(ctx.client, ctx.period_id, ctx.underwriter_headers)
    ctx.period = close_period(ctx.client, ctx.period_id, ctx.underwriter_headers)
    return ctx


def priced_negotiated_deal(client, ctx=None, **deal_overrides):
    """A negotiated deal driven all the way to PRICED.

    Its money fields are the PRD's own worked figures: an
    ``issue_price_total_usd`` of 10,711,700.00, a ``gross_spread_total_usd`` of
    87,500.00 and a ``gross_spread_per_bond_usd`` of 8.750 (PRD section 3.8).
    """
    ctx = negotiated_pricing_deal(client, ctx, **deal_overrides)
    cleared_disclosure(ctx)
    with_completed_allotment_run(ctx)
    ctx.deal = price_negotiated(client, ctx.deal_id, ctx.underwriter_headers)
    return ctx


def priced_competitive_deal(client, ctx=None, **deal_overrides):
    """A competitive deal driven all the way to PRICED.

    PRD section 3.8's worked competitive figures: bid proceeds of 10,600,000.00,
    a ``gross_spread_total_usd`` of 111,700.00 and 11.170 per bond.
    """
    ctx = competitive_pricing_deal(client, ctx, **deal_overrides)
    cleared_disclosure(ctx)
    with_completed_allotment_run(ctx)
    ctx.deal = price_competitive(client, ctx.deal_id, ctx.underwriter_headers)
    return ctx


def awarded_negotiated_deal(client, ctx=None, **deal_overrides):
    """A negotiated deal in AWARDED, so its six closing documents exist."""
    ctx = priced_negotiated_deal(client, ctx, **deal_overrides)
    ctx.deal = award(client, ctx.deal_id, ctx.issuer_headers)
    ctx.documents = documents_by_type(client, ctx.deal_id, ctx.compliance_headers)
    return ctx


def awarded_competitive_deal(client, ctx=None, **deal_overrides):
    """A competitive deal in AWARDED, so its six closing documents exist."""
    ctx = priced_competitive_deal(client, ctx, **deal_overrides)
    ctx.deal = award(client, ctx.deal_id, ctx.issuer_headers)
    ctx.documents = documents_by_type(client, ctx.deal_id, ctx.compliance_headers)
    return ctx


def headers_for_signatory_role(ctx, signatory_role):
    """Map a document's ``signatory_role`` to headers that satisfy it.

    PRD section 3.9: "The acting role must equal the document's
    ``signatory_role`` exactly."
    """
    return {
        UserRole.BOND_COUNSEL: ctx.counsel_headers,
        UserRole.ISSUER_OFFICIAL: ctx.issuer_headers,
        UserRole.UNDERWRITER: ctx.underwriter_headers,
        UserRole.MUNICIPAL_ADVISOR: ctx.advisor_headers,
    }[signatory_role]


def with_final_statement(ctx):
    """Post the final official statement on an AWARDED deal (PRD section 3.4)."""
    ctx.statement = post_final(ctx.client, ctx.statement_id, ctx.advisor_headers)
    return ctx


def execute_all_required_documents(ctx):
    """Execute every required closing document under its own signatory role."""
    ctx.documents = documents_by_type(ctx.client, ctx.deal_id, ctx.compliance_headers)
    for doc in ctx.documents.values():
        if doc["is_required"] and doc["execution_status"] == "PENDING":
            execute_document(
                ctx.client, doc["id"], headers_for_signatory_role(ctx, doc["signatory_role"])
            )
    ctx.documents = documents_by_type(ctx.client, ctx.deal_id, ctx.compliance_headers)
    return ctx


def closed_negotiated_deal(client, ctx=None, **deal_overrides):
    """A negotiated deal driven to the terminal CLOSED state.

    Closing is what makes the deal's maturities eligible to be named as a
    ``refunded_tranche_id`` by a later refunding series of the same issuer
    (PRD sections 3.2, 3.9).
    """
    ctx = awarded_negotiated_deal(client, ctx, **deal_overrides)
    with_final_statement(ctx)
    complete_handoff(client, ctx.deal_id)
    execute_all_required_documents(ctx)
    ctx.deal = close_deal(client, ctx.deal_id)
    return ctx


def refunding_context(client, **deal_overrides):
    """A CLOSED prior issue plus a fresh DRAFT deal for the same issuer.

    PRD section 3.2 makes the closed deal's maturities the only population
    eligible for ``refunded_tranche_id``, and PRD section 2.5 tier 9 requires the
    referenced maturity to sit on a *different* deal of the *same* issuer.
    """
    ctx = closed_negotiated_deal(client, **deal_overrides)
    ctx.closed_deal_id = ctx.deal_id
    ctx.closed_deal = ctx.deal
    ctx.closed_tranches = list_tranches(client, ctx.closed_deal_id, ctx.advisor_headers)
    ctx.closed_tranche_ids = [t["id"] for t in ctx.closed_tranches]
    draft_deal(client, ctx, tranches=False)
    ctx.refunding_deal_id = ctx.deal_id
    return ctx


# ---------------------------------------------------------------------------
# Scenario builders: the worked order book (PRD section 3.7)
# ---------------------------------------------------------------------------
def negotiated_deal_two_members(client, ctx=None, **deal_overrides):
    """A negotiated deal with a senior manager and a co-manager at 50 percent each.

    Two seats are needed because PRD section 3.7 admits ``MEMBER`` and ``STOCK``
    orders only from a member whose ``member_role`` is ``SENIOR_MANAGER`` or
    ``CO_MANAGER``, and the liability shares still have to sum to exactly
    100.0000 for pricing (PRD section 3.8).
    """
    ctx = structuring_deal(client, ctx, **deal_overrides)
    ctx.co_manager_firm = register_underwriter_firm(client)
    ctx.co_manager_firm_id = ctx.co_manager_firm["id"]
    ctx.co_manager_headers = make_underwriter_headers(ctx.co_manager_firm_id)
    ctx.senior_member = seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.underwriter_headers,
        MemberRole.SENIOR_MANAGER,
        liability_pct=50.0000,
        takedown_share_pct=50.0000,
        priority_rank=1,
    )
    ctx.co_member = seat_member(
        client,
        ctx.deal_id,
        ctx.co_manager_firm_id,
        ctx.underwriter_headers,
        MemberRole.CO_MANAGER,
        liability_pct=50.0000,
        takedown_share_pct=50.0000,
        priority_rank=2,
    )
    ctx.members = [ctx.senior_member, ctx.co_member]
    ctx.member_ids = [ctx.senior_member["id"], ctx.co_member["id"]]
    ctx.deal = designate_sale_method(
        client, ctx.deal_id, SaleMethod.NEGOTIATED, ctx.advisor_headers
    )
    ctx.sale_method = SaleMethod.NEGOTIATED
    return ctx


def waterfall_book(ctx, close=True):
    """Build the PRD's worked four-order book on the deal's first maturity.

    PRD section 3.7's worked case: O1 RETAIL for 2,005,000 submitted first, O2
    INSTITUTIONAL_PRIORITY for 2,000,000, O3 INSTITUTIONAL_PRIORITY for 1,500,000
    submitted after O2, and O4 MEMBER for 1,000,000, all against a tranche whose
    ``principal_amount_usd`` is 5,000,000. The period is a ``RETAIL`` window under
    the default ``STANDARD_PRIORITY`` policy, which "admits every order type",
    because a ``RETAIL`` order may only be placed into a ``RETAIL`` period.

    The clock is advanced one minute between entries so ``submitted_at`` is
    strictly increasing and the within-tier ordering is unambiguous.
    """
    client = ctx.client
    period = schedule_order_period(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(
            CLOCK_EPOCH,
            plus_hours(CLOCK_EPOCH, 4),
            PeriodType.RETAIL,
            priority_policy=PriorityPolicy.STANDARD_PRIORITY,
        ),
    )
    ctx.period_id = period["id"]
    open_period(client, ctx.period_id, ctx.underwriter_headers)
    tranche_id = ctx.tranche_ids[0]
    senior_id = ctx.senior_member["id"]
    co_id = ctx.co_member["id"]

    ctx.order_1 = place_order(
        client,
        ctx.period_id,
        tranche_id,
        senior_id,
        ctx.underwriter_headers,
        OrderType.RETAIL,
        WATERFALL_O1_REQUESTED_USD,
    )
    set_clock(client, plus_minutes(CLOCK_EPOCH, 1))
    ctx.order_2 = place_order(
        client,
        ctx.period_id,
        tranche_id,
        senior_id,
        ctx.underwriter_headers,
        OrderType.INSTITUTIONAL_PRIORITY,
        WATERFALL_O2_REQUESTED_USD,
    )
    set_clock(client, plus_minutes(CLOCK_EPOCH, 2))
    ctx.order_3 = place_order(
        client,
        ctx.period_id,
        tranche_id,
        co_id,
        ctx.underwriter_headers,
        OrderType.INSTITUTIONAL_PRIORITY,
        WATERFALL_O3_REQUESTED_USD,
    )
    set_clock(client, plus_minutes(CLOCK_EPOCH, 3))
    ctx.order_4 = place_order(
        client,
        ctx.period_id,
        tranche_id,
        co_id,
        ctx.underwriter_headers,
        OrderType.MEMBER,
        WATERFALL_O4_REQUESTED_USD,
    )
    ctx.orders = [ctx.order_1, ctx.order_2, ctx.order_3, ctx.order_4]
    ctx.order_ids = [o["id"] for o in ctx.orders]
    if close:
        ctx.period = close_period(client, ctx.period_id, ctx.underwriter_headers)
    return ctx


def allotted_negotiated_deal(client, ctx=None, **deal_overrides):
    """A negotiated deal whose worked order book has been allotted, still on branch."""
    ctx = negotiated_deal_two_members(client, ctx, **deal_overrides)
    cleared_disclosure(ctx)
    waterfall_book(ctx)
    return ctx


def priced_allotted_negotiated_deal(client, ctx=None, **deal_overrides):
    """The allotted deal priced, so takedown credits carry the PRD's worked figures.

    PRD section 3.8: at a ``takedown_per_bond_usd`` of 5.000 the senior manager
    earns 18,600.00 and the co-manager 6,400.00.
    """
    ctx = allotted_negotiated_deal(client, ctx, **deal_overrides)
    ctx.deal = price_negotiated(
        client,
        ctx.deal_id,
        ctx.underwriter_headers,
        takedown_per_bond_usd=NEGOTIATED_TAKEDOWN_PER_BOND_USD,
    )
    return ctx


# ---------------------------------------------------------------------------
# Scenario builders: credit review (PRD section 3.5)
# ---------------------------------------------------------------------------
def acknowledged_engagement(ctx, agency=RatingAgency.MOODYS):
    """A rating engagement in UNDER_REVIEW, pinned to the primary analyst."""
    engagement = request_rating(ctx.client, ctx.deal_id, ctx.advisor_headers, agency)
    ctx.engagement = acknowledge_engagement(ctx.client, engagement["id"], ctx.analyst_headers)
    ctx.engagement_id = ctx.engagement["id"]
    return ctx


def engagement_with_held_presentation(ctx, agency=RatingAgency.MOODYS):
    """An UNDER_REVIEW engagement carrying one HELD presentation.

    PRD section 3.5 promotes a SCHEDULED presentation to HELD "whenever the clock
    is set to an instant at or after" its ``ends_at``, which is the only
    precondition ``assign-rating`` has beyond the state itself.
    """
    acknowledged_engagement(ctx, agency)
    starts_at = plus_hours(CLOCK_EPOCH, 2)
    ends_at = plus_hours(CLOCK_EPOCH, 3)
    ctx.presentation = schedule_presentation(
        ctx.client, ctx.engagement_id, ctx.advisor_headers, starts_at, ends_at
    )
    ctx.presentation_id = ctx.presentation["id"]
    set_clock(ctx.client, ends_at)
    ctx.presentation = get_success_data(
        ctx.client.get_presentation(ctx.presentation_id, ctx.advisor_headers), 200
    )
    return ctx
