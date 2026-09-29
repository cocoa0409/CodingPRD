"""Request payload builders.

Every builder returns a payload that PRD.md accepts as valid, so a test that
wants to probe one rule overrides exactly one field and leaves the rest alone.
Monetary and price fields are emitted as JSON **numbers** -- PRD section 2.6
describes them as numerics, and sending them as strings would be a request-shape
violation rather than the rule under test.
"""

import itertools

from .constants import (
    ATTENDEE_COUNT_MIN,
    CANONICAL_TRANCHE_PRINCIPAL_USD,
    CLOCK_EPOCH,
    COMPETITIVE_WINNING_BID_PRICE_PCT,
    DATED_DATE,
    ENHANCEMENT_PREMIUM_BPS,
    MIN_RECORD_RETENTION_YEARS,
    NEGOTIATED_EXPENSES_PER_BOND_USD,
    NEGOTIATED_MANAGEMENT_FEE_PER_BOND_USD,
    NEGOTIATED_TAKEDOWN_PER_BOND_USD,
    TRANCHE_1_COUPON_PCT,
    TRANCHE_1_MATURITY_DATE,
    TRANCHE_1_YIELD_PCT,
    TRANCHE_2_CALL_PRICE_PCT,
    TRANCHE_2_COUPON_PCT,
    TRANCHE_2_FIRST_CALL_DATE,
    TRANCHE_2_MATURITY_DATE,
    TRANCHE_2_YIELD_PCT,
    CANONICAL_EXPECTED_PAR_USD,
    plus_hours,
)
from .types import (
    EntityType,
    EnhancementType,
    FirmType,
    MemberRole,
    OrderType,
    Outlook,
    PeriodType,
    PriorityPolicy,
    RatingAgency,
    SaleMethod,
    SectionType,
    TaxStatus,
)

_counter = itertools.count(1)


def _next():
    return next(_counter)


def unique_msrb_registration_id():
    """Six uppercase alphanumeric characters, unique per process (PRD section 3.1)."""
    return "MB{:04d}".format(_next() % 10000)


def unique_series_designation(prefix="Series 2026"):
    """A series designation unique among a single issuer's deals (PRD section 3.2)."""
    return f"{prefix}-{_next():04d}"


def unique_section_code(prefix="SEC"):
    """A section code unique within one official statement (PRD section 3.4)."""
    return f"{prefix}-{_next():04d}"


# ---------------------------------------------------------------------------
# Participants (PRD section 3.1)
# ---------------------------------------------------------------------------
def issuer_payload(**overrides):
    """A clean-record issuer: every optional compliance input at its default."""
    payload = {
        "name": f"City of Testville {_next()}",
        "state_code": "CA",
        "entity_type": EntityType.CITY,
    }
    payload.update(overrides)
    return payload


def firm_payload(firm_type=FirmType.UNDERWRITER, **overrides):
    """A registered firm of the requested capacity."""
    payload = {
        "name": f"Test Securities {_next()}",
        "firm_type": firm_type,
        "msrb_registration_id": unique_msrb_registration_id(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Deals and maturities (PRD section 3.2)
# ---------------------------------------------------------------------------
def deal_payload(issuer_id, **overrides):
    """A DRAFT deal sized to the canonical two-tranche schedule."""
    payload = {
        "issuer_id": issuer_id,
        "series_designation": unique_series_designation(),
        "tax_status": TaxStatus.TAX_EXEMPT,
        "dated_date": DATED_DATE,
        "expected_par_amount_usd": CANONICAL_EXPECTED_PAR_USD,
    }
    payload.update(overrides)
    return payload


def tranche_payload(
    sequence_number,
    maturity_date,
    principal_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
    coupon_rate_pct=TRANCHE_1_COUPON_PCT,
    yield_pct=TRANCHE_1_YIELD_PCT,
    **overrides,
):
    """One maturity on the schedule; call fields omitted unless overridden."""
    payload = {
        "sequence_number": sequence_number,
        "maturity_date": maturity_date,
        "principal_amount_usd": principal_amount_usd,
        "coupon_rate_pct": coupon_rate_pct,
        "yield_pct": yield_pct,
    }
    payload.update(overrides)
    return payload


def canonical_tranche_1_payload(**overrides):
    """The PRD's non-callable maturity that prices at 106.058 (section 3.2)."""
    return tranche_payload(
        1,
        TRANCHE_1_MATURITY_DATE,
        coupon_rate_pct=TRANCHE_1_COUPON_PCT,
        yield_pct=TRANCHE_1_YIELD_PCT,
        **overrides,
    )


def canonical_tranche_2_payload(**overrides):
    """The PRD's callable maturity that prices to the call at 108.176 (section 3.2)."""
    payload = tranche_payload(
        2,
        TRANCHE_2_MATURITY_DATE,
        coupon_rate_pct=TRANCHE_2_COUPON_PCT,
        yield_pct=TRANCHE_2_YIELD_PCT,
        is_callable=True,
        first_call_date=TRANCHE_2_FIRST_CALL_DATE,
        call_price_pct=TRANCHE_2_CALL_PRICE_PCT,
    )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Credit enhancement (PRD section 3.3)
# ---------------------------------------------------------------------------
def enhancement_payload(insured_tranche_ids, **overrides):
    """A proposed bond insurance policy over the named maturities."""
    payload = {
        "provider_name": f"Municipal Assurance {_next()}",
        "enhancement_type": EnhancementType.BOND_INSURANCE,
        "enhanced_rating": "AA",
        "premium_bps": ENHANCEMENT_PREMIUM_BPS,
        "insured_tranche_ids": list(insured_tranche_ids),
    }
    payload.update(overrides)
    return payload


def withdraw_payload(reason="Insurer downgraded", **overrides):
    payload = {"withdrawal_reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Disclosure (PRD section 3.4)
# ---------------------------------------------------------------------------
def official_statement_payload(expected_deal_version, **overrides):
    """A preliminary official statement draft, version-guarded on the deal."""
    payload = {
        "version_label": f"POS v{_next()}",
        "is_preliminary": True,
        "expected_deal_version": expected_deal_version,
    }
    payload.update(overrides)
    return payload


def section_payload(section_type=SectionType.GENERAL, **overrides):
    """One official statement section, authored in DRAFT."""
    payload = {
        "section_code": unique_section_code(),
        "title": f"Section {_next()}",
        "body_text": "This section describes the matter in three words.",
        "section_type": section_type,
    }
    payload.update(overrides)
    return payload


def material_risk_section_payload(**overrides):
    """A RISK_FACTOR section flagged as a material risk (PRD section 3.4)."""
    fields = {"is_material_risk": True}
    fields.update(overrides)
    return section_payload(SectionType.RISK_FACTOR, **fields)


def continuing_disclosure_risk_section_payload(**overrides):
    """The CONTINUING_DISCLOSURE material risk section the high-risk gate demands."""
    fields = {"is_material_risk": True}
    fields.update(overrides)
    return section_payload(SectionType.CONTINUING_DISCLOSURE, **fields)


def undertaking_payload(**overrides):
    """A Rule 15c2-12 continuing disclosure undertaking in DRAFT."""
    payload = {
        "annual_report_due_days": 180,
        "material_event_notice_days": 10,
        "dissemination_agent": f"Digital Assurance {_next()}",
    }
    payload.update(overrides)
    return payload


def revision_payload(reason="Risk factors require expansion", **overrides):
    payload = {"revision_reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Rating agency coordination (PRD section 3.5)
# ---------------------------------------------------------------------------
def rating_engagement_payload(agency=RatingAgency.MOODYS, **overrides):
    payload = {"agency": agency}
    payload.update(overrides)
    return payload


def information_request_payload(text="Provide five years of audited financials", **overrides):
    payload = {"information_request": text}
    payload.update(overrides)
    return payload


def info_response_payload(text="Audited financials attached", **overrides):
    payload = {"response_summary": text}
    payload.update(overrides)
    return payload


def assign_rating_payload(assigned_rating="AA2", outlook=Outlook.STABLE, **overrides):
    payload = {"assigned_rating": assigned_rating, "outlook": outlook}
    payload.update(overrides)
    return payload


def presentation_payload(starts_at, ends_at, **overrides):
    payload = {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "attendee_count": ATTENDEE_COUNT_MIN + 4,
    }
    payload.update(overrides)
    return payload


def default_presentation_payload(**overrides):
    """A one-hour window starting two hours after the clock epoch."""
    starts_at = plus_hours(CLOCK_EPOCH, 2)
    return presentation_payload(starts_at, plus_hours(starts_at, 1), **overrides)


def cancellation_payload(reason="No longer required", **overrides):
    payload = {"cancellation_reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Syndicate and the sale-method fork (PRD section 3.6)
# ---------------------------------------------------------------------------
def syndicate_member_payload(
    firm_id,
    member_role=MemberRole.SENIOR_MANAGER,
    liability_pct=100.0000,
    takedown_share_pct=100.0000,
    priority_rank=1,
    **overrides,
):
    payload = {
        "firm_id": firm_id,
        "member_role": member_role,
        "liability_pct": liability_pct,
        "takedown_share_pct": takedown_share_pct,
        "priority_rank": priority_rank,
    }
    payload.update(overrides)
    return payload


def sale_method_payload(sale_method=SaleMethod.NEGOTIATED, **overrides):
    payload = {"sale_method": sale_method}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The order book (PRD section 3.7)
# ---------------------------------------------------------------------------
def order_period_payload(
    opens_at, closes_at, period_type=PeriodType.INSTITUTIONAL, **overrides
):
    payload = {
        "period_type": period_type,
        "opens_at": opens_at,
        "closes_at": closes_at,
    }
    payload.update(overrides)
    return payload


def default_order_period_payload(**overrides):
    """An institutional window open across the clock epoch."""
    return order_period_payload(CLOCK_EPOCH, plus_hours(CLOCK_EPOCH, 8), **overrides)


def retail_order_period_payload(**overrides):
    """A retail window with the default STANDARD_PRIORITY policy."""
    return order_period_payload(
        CLOCK_EPOCH, plus_hours(CLOCK_EPOCH, 4), PeriodType.RETAIL, **overrides
    )


def retail_only_order_period_payload(**overrides):
    """A retail window narrowed to retail demand (PRD section 3.7)."""
    return order_period_payload(
        CLOCK_EPOCH,
        plus_hours(CLOCK_EPOCH, 4),
        PeriodType.RETAIL,
        priority_policy=PriorityPolicy.RETAIL_ONLY,
        **overrides,
    )


def order_payload(
    maturity_tranche_id,
    syndicate_member_id,
    expected_order_period_version,
    order_type=OrderType.INSTITUTIONAL_PRIORITY,
    par_requested_usd=1000000,
    price_or_yield_pct=100.000,
    **overrides,
):
    payload = {
        "maturity_tranche_id": maturity_tranche_id,
        "syndicate_member_id": syndicate_member_id,
        "order_type": order_type,
        "par_requested_usd": par_requested_usd,
        "price_or_yield_pct": price_or_yield_pct,
        "expected_order_period_version": expected_order_period_version,
    }
    payload.update(overrides)
    return payload


def reopen_payload(reason="Allotment error discovered", **overrides):
    payload = {"reopen_reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pricing and post-issuance (PRD sections 3.8, 3.9)
# ---------------------------------------------------------------------------
def negotiated_pricing_payload(**overrides):
    """The three per-bond components the negotiated branch demands."""
    payload = {
        "takedown_per_bond_usd": NEGOTIATED_TAKEDOWN_PER_BOND_USD,
        "management_fee_per_bond_usd": NEGOTIATED_MANAGEMENT_FEE_PER_BOND_USD,
        "expenses_per_bond_usd": NEGOTIATED_EXPENSES_PER_BOND_USD,
    }
    payload.update(overrides)
    return payload


def competitive_pricing_payload(**overrides):
    """The single winning bid price the competitive branch demands."""
    payload = {"winning_bid_price_pct": COMPETITIVE_WINNING_BID_PRICE_PCT}
    payload.update(overrides)
    return payload


def handoff_payload(record_retention_years=MIN_RECORD_RETENTION_YEARS, **overrides):
    payload = {"record_retention_years": record_retention_years}
    payload.update(overrides)
    return payload


def yield_restriction_payload(
    projected_investment_yield_pct=4.600,
    unspent_proceeds_usd=5000000,
    investment_days=180,
    **overrides,
):
    payload = {
        "projected_investment_yield_pct": projected_investment_yield_pct,
        "unspent_proceeds_usd": unspent_proceeds_usd,
        "investment_days": investment_days,
    }
    payload.update(overrides)
    return payload


def execute_payload(signatory_name="Jordan Signatory", **overrides):
    payload = {"signatory_name": signatory_name}
    payload.update(overrides)
    return payload


def waiver_payload(reason="Substituted by counsel letter", **overrides):
    payload = {"waiver_reason": reason}
    payload.update(overrides)
    return payload
