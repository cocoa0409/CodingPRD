"""Request-payload factories.

Every factory returns a payload that satisfies the PRD's field rules on its
own, and accepts ``**overrides`` so a test can perturb exactly the one field
it is about.  Money, rate and score fields are emitted as JSON numbers and
count fields as JSON integers, exactly as PRD §2.6 requires; dates are
``YYYY-MM-DD`` strings and instants carry a full time-of-day.
"""

import itertools

from .constants import (
    HARBOR_POINT_APPLICATION,
    SOLARIS_BRAND,
    STRONG_OWNER,
)

_brand_code_counter = itertools.count(1)
_email_counter = itertools.count(1)


def unique_brand_code(prefix: str = "BRND") -> str:
    """A fresh 3-12 character upper-case alphanumeric brand code."""
    return f"{prefix}{next(_brand_code_counter):04d}"


def unique_email(local: str = "cfo") -> str:
    """A 5-160 character address with exactly one '@' and a '.' after it."""
    return f"{local}{next(_email_counter):04d}@example.test"


# ─── Brand (PRD §3.1) ────────────────────────────────────────────────

def build_brand_payload(**overrides) -> dict:
    payload = {
        "code": unique_brand_code(),
        "name": "Meridian Collection",
        "tier": "UPSCALE",
        "base_royalty_rate_pct": 5.00,
        "marketing_fund_rate_pct": 2.50,
        "protected_radius_miles": 5.00,
        "min_room_count": 80,
        "standard_term_years": 20,
    }
    payload.update(overrides)
    return payload


def build_solaris_brand_payload(**overrides) -> dict:
    """The recurring UPSCALE brand: five-mile ring, eighty-room floor."""
    payload = dict(SOLARIS_BRAND)
    payload.update(overrides)
    return payload


# ─── Existing unit (PRD §3.1) ────────────────────────────────────────

def build_existing_unit_payload(brand_id: str, **overrides) -> dict:
    payload = {
        "brand_id": brand_id,
        "unit_name": "Solaris Ridgeview",
        "market_code": "SEADT",
        "x_miles": 3.00,
        "y_miles": 4.00,
        "room_count": 150,
        "adr_amount": 240.00,
        "occupancy_pct": 68.00,
        "territory_start_date": "2018-04-01",
        "territory_end_date": "2026-09-30",
    }
    payload.update(overrides)
    return payload


def build_unit_status_payload(to_status: str, reason: str = "Operational decision recorded.") -> dict:
    return {"to_status": to_status, "reason": reason}


# ─── Owner (PRD §3.2) ────────────────────────────────────────────────

def build_owner_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Meridian Lodging Partners LLC",
        "contact_email": unique_email(),
        "liquid_assets_amount": 6_000_000.00,
        "net_worth_amount": 18_000_000.00,
        "credit_score": 760,
        "existing_units_count": 4,
    }
    payload.update(overrides)
    return payload


def build_strong_owner_payload(**overrides) -> dict:
    """Harbor Point: 96.67 STANDALONE / 100.00 PORTFOLIO_ADJUSTED, both STRONG."""
    payload = dict(STRONG_OWNER)
    payload.update(overrides)
    return payload


def build_financial_profile_payload(**overrides) -> dict:
    """A re-verification body; all four inputs are required together."""
    payload = {
        "liquid_assets_amount": 3_200_000.00,
        "net_worth_amount": 9_000_000.00,
        "credit_score": 720,
        "existing_units_count": 1,
    }
    payload.update(overrides)
    return payload


# ─── Application (PRD §3.3) ──────────────────────────────────────────

def build_application_payload(owner_id: str, brand_id: str, **overrides) -> dict:
    payload = {
        "owner_id": owner_id,
        "brand_id": brand_id,
        "property_name": "Meridian Waterfront Hotel",
        "market_code": "SEADT",
        "property_x_miles": 0.00,
        "property_y_miles": 0.00,
        "room_count": 120,
        "current_affiliation": "COMPETITOR",
        "building_age_years": 18,
        "requested_term_years": 20,
        "requested_conversion_date": "2026-10-01",
    }
    payload.update(overrides)
    return payload


def build_harbor_point_application_payload(owner_id: str, brand_id: str, **overrides) -> dict:
    """The recurring 120-room COMPETITOR conversion at the map origin."""
    payload = {"owner_id": owner_id, "brand_id": brand_id}
    payload.update(HARBOR_POINT_APPLICATION)
    payload.update(overrides)
    return payload


def build_financial_review_payload(capacity_basis: str = "PORTFOLIO_ADJUSTED", **overrides) -> dict:
    payload = {"capacity_basis": capacity_basis}
    payload.update(overrides)
    return payload


def build_decision_payload(outcome: str = "APPROVE", **overrides) -> dict:
    payload = {"outcome": outcome, "decision_notes": "Recorded by the development committee."}
    payload.update(overrides)
    return payload


def build_revision_request_payload(**overrides) -> dict:
    payload = {"revision_notes": "Restate the capital stack and the room mix."}
    payload.update(overrides)
    return payload


def build_resubmit_payload(**overrides) -> dict:
    payload = {"revision_response": "Capital stack restated; room mix unchanged."}
    payload.update(overrides)
    return payload


# ─── Encroachment claim (PRD §3.4) ───────────────────────────────────

def build_encroachment_claim_payload(existing_unit_id: str, **overrides) -> dict:
    payload = {
        "existing_unit_id": existing_unit_id,
        "claimed_revenue_loss_pct": 9.50,
        "narrative": "The incumbent projects a shift of transient demand to the converted property.",
    }
    payload.update(overrides)
    return payload


def build_claim_resolution_payload(outcome: str = "OVERRULE", **overrides) -> dict:
    payload = {"outcome": outcome, "resolution_notes": "Reviewed against the market study."}
    payload.update(overrides)
    return payload


# ─── License agreement (PRD §3.6) ────────────────────────────────────

def build_agreement_payload(effective_date: str = "2026-10-01", **overrides) -> dict:
    payload = {"effective_date": effective_date}
    payload.update(overrides)
    return payload


def build_execute_payload(expected_application_version: int, **overrides) -> dict:
    payload = {"expected_application_version": expected_application_version}
    payload.update(overrides)
    return payload


def build_onboarding_milestone_payload(track: str, to_status: str) -> dict:
    return {"track": track, "to_status": to_status}


# ─── Property improvement plan (PRD §3.7) ────────────────────────────

def build_pip_payload(**overrides) -> dict:
    payload = {"scope_notes": "Full brand conversion scope."}
    payload.update(overrides)
    return payload


def build_pip_item_payload(**overrides) -> dict:
    payload = {
        "category": "GUESTROOM",
        "priority": "MAJOR",
        "description": "Guestroom soft goods and case goods replacement",
        "estimated_cost": 2_400_000.00,
    }
    payload.update(overrides)
    return payload


def build_pip_accept_payload(acknowledgement: str = "ACCEPTED_IN_FULL", **overrides) -> dict:
    payload = {"acknowledgement": acknowledgement}
    payload.update(overrides)
    return payload


def build_item_completion_payload(**overrides) -> dict:
    payload = {"completion_evidence": "Installation signed off on site."}
    payload.update(overrides)
    return payload


def build_item_verification_payload(outcome: str = "VERIFY", **overrides) -> dict:
    payload = {"outcome": outcome, "verification_notes": "Work witnessed against the brand spec."}
    payload.update(overrides)
    return payload


def build_extension_request_payload(requested_days: int = 30, **overrides) -> dict:
    payload = {
        "requested_days": requested_days,
        "reason": "Long-lead millwork slipped at the mill.",
    }
    payload.update(overrides)
    return payload


def build_extension_decision_payload(outcome: str = "GRANT", **overrides) -> dict:
    payload = {"outcome": outcome, "decision_notes": "Schedule relief reviewed."}
    payload.update(overrides)
    return payload


# ─── Fee ledger (PRD §3.8) ───────────────────────────────────────────

def build_revenue_report_payload(period_month: str, gross_room_revenue: float, **overrides) -> dict:
    payload = {
        "period_month": period_month,
        "gross_room_revenue": gross_room_revenue,
    }
    payload.update(overrides)
    return payload


# ─── Quality assurance (PRD §3.8) ────────────────────────────────────

def build_qa_inspection_payload(**overrides) -> dict:
    """All four section scores are integers 0-100 and the defect count an integer."""
    payload = {
        "cleanliness_score": 90,
        "condition_score": 90,
        "brand_standard_score": 90,
        "guest_experience_score": 90,
        "critical_defect_count": 0,
        "life_safety_defect": False,
    }
    payload.update(overrides)
    return payload


def build_cure_submission_payload(**overrides) -> dict:
    payload = {"cure_evidence": "Punch list closed; photographs attached."}
    payload.update(overrides)
    return payload


def build_cure_review_payload(outcome: str = "PASS", **overrides) -> dict:
    payload = {"outcome": outcome, "review_notes": "Re-inspection walked with the general manager."}
    payload.update(overrides)
    return payload


# ─── Consent, termination and close-out (PRD §3.9) ───────────────────

def build_transfer_request_payload(request_type: str = "TRANSFER", **overrides) -> dict:
    """TRANSFER and CHANGE_OF_CONTROL carry proposed_owner_id and no lender_name;
    REFINANCE carries lender_name and no proposed_owner_id."""
    payload = {"request_type": request_type}
    payload.update(overrides)
    return payload


def build_refinance_request_payload(lender_name: str = "Cascade Mezzanine Capital", **overrides) -> dict:
    payload = {"request_type": "REFINANCE", "lender_name": lender_name}
    payload.update(overrides)
    return payload


def build_transfer_decision_payload(outcome: str, expected_agreement_version: int, **overrides) -> dict:
    payload = {
        "outcome": outcome,
        "expected_agreement_version": expected_agreement_version,
        "decision_notes": "Consent request reviewed by the franchisor.",
    }
    payload.update(overrides)
    return payload


def build_termination_payload(cause: str = "MUTUAL", **overrides) -> dict:
    payload = {"cause": cause, "termination_notes": "Notice of termination issued."}
    payload.update(overrides)
    return payload


def build_de_identification_payload(items_completed=None, **overrides) -> dict:
    """The certification body carries ``items_completed``, an array of codes."""
    payload = {
        "items_completed": list(items_completed)
        if items_completed is not None
        else [
            "SIGNAGE",
            "INTERIOR_BRANDING",
            "DIGITAL_LISTINGS",
            "LINENS_AND_COLLATERAL",
            "RESERVATION_CODES",
        ]
    }
    payload.update(overrides)
    return payload


def build_close_out_payload(
    liquidated_damages_settlement_amount: float,
    de_identification_verified: bool = True,
    **overrides,
) -> dict:
    payload = {
        "liquidated_damages_settlement_amount": liquidated_damages_settlement_amount,
        "de_identification_verified": de_identification_verified,
    }
    payload.update(overrides)
    return payload


# ─── Clock (PRD §2.4) ────────────────────────────────────────────────

def build_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
