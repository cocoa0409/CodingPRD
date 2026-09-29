"""Request-payload factories.

Every factory returns only the *input* fields the PRD declares for that
endpoint; server-managed and derived fields are never sent.  Pass ``OMIT`` as
an override value to drop a key entirely (for missing-required-field tests).
"""
from . import constants as C
from .types import (
    DiscountType, EmploymentStatus, PerkCategory, PlacementTier, RegionCode,
    StatementBasis,
)


class _Omit:
    def __repr__(self):
        return "OMIT"


OMIT = _Omit()


def _build(base, overrides):
    merged = dict(base)
    merged.update(overrides)
    return {k: v for k, v in merged.items() if not isinstance(v, _Omit)}


# ── Control plane ───────────────────────────────────────────────────────────

def clock_payload(to_iso8601):
    return {"to_iso8601": to_iso8601}


# ── Merchants (PRD §3.1) ────────────────────────────────────────────────────

def merchant_payload(**overrides):
    return _build({
        "legal_name": "Bistro Uno",
        "contact_email": "deals@bistrouno.example",
        "primary_category": PerkCategory.DINING,
        "region_codes": [RegionCode.CA],
    }, overrides)


def merchant_update_payload(**overrides):
    return _build({"contact_email": "ops@bistrouno.example"}, overrides)


def terminate_payload(**overrides):
    return _build({"terminated_reason": "Compliance review failure"}, overrides)


# ── Partner agreements (PRD §3.1, §3.2) ─────────────────────────────────────

def agreement_payload(merchant_id, **overrides):
    return _build({
        "merchant_id": merchant_id,
        "category": PerkCategory.DINING,
        "region_code": RegionCode.CA,
        "exclusivity_requested": False,
    }, overrides)


def round_payload(expected_agreement_version, **overrides):
    """Payload shared by `propose` and `counter` (PRD §3.1)."""
    return _build({
        "expected_agreement_version": expected_agreement_version,
        "commission_rate_bps": 1200,
        "placement_fee_base_cents": 36000,
        "employer_revenue_share_bps": 2500,
    }, overrides)


def decide_payload(decision, **overrides):
    return _build({"decision": decision}, overrides)


# ── Employers, storefronts, eligibility (PRD §3.3, §3.4) ────────────────────

def employer_payload(**overrides):
    return _build({
        "name": "Northwind Logistics",
        "region_code": RegionCode.CA,
        "employee_count_declared": 250,
    }, overrides)


def employer_update_payload(**overrides):
    return _build({"revenue_share_enabled": True}, overrides)


def storefront_payload(**overrides):
    return _build({
        "brand_color_hex": "#1A2B3C",
        "logo_url": "https://cdn.example/northwind/logo.png",
        "hero_headline": "Perks for the whole crew",
        "featured_categories": [PerkCategory.DINING],
    }, overrides)


def storefront_suspend_payload(**overrides):
    return _build({"suspension_reason": "Contract billing dispute"}, overrides)


def eligibility_record(ref, **overrides):
    return _build({
        "external_employee_ref": ref,
        "employment_status": EmploymentStatus.ACTIVE,
        "region_code": RegionCode.CA,
        "eligibility_valid_from": "2026-07-01T00:00:00Z",
        "eligibility_valid_until": "2027-07-01T00:00:00Z",
    }, overrides)


def eligibility_records(count, prefix="EMP", **record_overrides):
    return [
        eligibility_record(f"{prefix}-{index:04d}", **record_overrides)
        for index in range(1, count + 1)
    ]


def eligibility_file_payload(expected_employer_version, records=None, **overrides):
    return _build({
        "expected_employer_version": expected_employer_version,
        "effective_from": "2026-07-01T00:00:00Z",
        "checksum": "sha256:feed-0001",
        "records": records if records is not None else eligibility_records(1),
    }, overrides)


def employment_status_payload(employment_status):
    return {"employment_status": employment_status}


# ── Offers (PRD §3.5) ───────────────────────────────────────────────────────

def offer_payload(agreement_id, **overrides):
    """A `PERCENT` offer by default: 2,000 bps off, no inventory ceiling."""
    return _build({
        "agreement_id": agreement_id,
        "title": "Twenty percent off lunch",
        "discount_type": DiscountType.PERCENT,
        "discount_value_bps": 2000,
        "region_codes": [RegionCode.CA],
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-12-01T00:00:00Z",
    }, overrides)


def percent_offer_payload(agreement_id, discount_value_bps=2000, **overrides):
    return offer_payload(
        agreement_id,
        discount_type=DiscountType.PERCENT,
        discount_value_bps=discount_value_bps,
        **overrides,
    )


def fixed_offer_payload(agreement_id, discount_value_cents=800, **overrides):
    return offer_payload(
        agreement_id,
        title="Eight dollars off lunch",
        discount_type=DiscountType.FIXED,
        discount_value_bps=OMIT,
        discount_value_cents=discount_value_cents,
        **overrides,
    )


def review_payload(decision, **overrides):
    return _build({"decision": decision}, overrides)


def pause_payload(**overrides):
    return _build({"paused_reason": "Kitchen refurbishment"}, overrides)


# ── Placement slots (PRD §3.6) ──────────────────────────────────────────────

def slot_payload(expected_offer_version, employer_id, **overrides):
    return _build({
        "expected_offer_version": expected_offer_version,
        "employer_id": employer_id,
        "placement_tier": PlacementTier.FEATURED,
        "slot_window_start": "2026-08-10T00:00:00Z",
        "slot_window_end": "2026-08-15T00:00:00Z",
    }, overrides)


def release_payload(**overrides):
    return _build({"release_reason": "Merchant withdrew the campaign"}, overrides)


# ── Redemptions (PRD §3.7) ──────────────────────────────────────────────────

def redemption_payload(offer_id, membership_id, **overrides):
    return _build({
        "offer_id": offer_id,
        "membership_id": membership_id,
        "intended_gross_amount_cents": 5000,
    }, overrides)


def verify_payload(verification_token, gross_amount_cents, **overrides):
    return _build({
        "verification_token": verification_token,
        "gross_amount_cents": gross_amount_cents,
    }, overrides)


# ── Disputes (PRD §3.8) ─────────────────────────────────────────────────────

def dispute_payload(**overrides):
    return _build({
        "reason": "NOT_HONORED",
        "description": "The till refused the discount at checkout.",
    }, overrides)


def dispute_response_payload(**overrides):
    return _build({"response_note": "Terminal was offline that evening."}, overrides)


def resolve_payload(outcome, **overrides):
    return _build({"outcome": outcome}, overrides)


# ── Statements (PRD §3.9) ───────────────────────────────────────────────────

def statement_payload(employer_id, **overrides):
    return _build({
        "employer_id": employer_id,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "basis": StatementBasis.ACCRUAL,
    }, overrides)


def pay_payload(**overrides):
    return _build({"payment_reference": "WIRE-2026-09-0001"}, overrides)


# ── Report query parameters (PRD §2.10) ─────────────────────────────────────

def report_params(period_start="2026-08-01T00:00:00Z",
                  period_end="2026-09-01T00:00:00Z", **overrides):
    return _build({"period_start": period_start, "period_end": period_end}, overrides)


# ── Rounding oracle used by fee and economics assertions (PRD §2.6) ─────────

def round_half_up_bps(amount_cents, rate_bps):
    """`amount_cents` * `rate_bps` / 10,000 rounded half up to whole cents."""
    numerator = amount_cents * rate_bps
    quotient, remainder = divmod(numerator, C.BPS_DENOMINATOR)
    if remainder * 2 >= C.BPS_DENOMINATOR:
        quotient += 1
    return quotient
