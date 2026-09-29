"""Request-payload builders.

Each builder emits a payload that satisfies every §2.8 tier-3 shape rule for its
endpoint: money is an integer number of cents, instants carry exactly three
fractional-second digits, calendar dates are bare ``YYYY-MM-DD`` strings, and
every string literal respects the length and charset rule the PRD states for its
field. ``**overrides`` replaces or adds keys; passing ``None`` for an optional
key removes it, which is how a test omits a field the PRD makes optional.
"""

import itertools
from typing import Any, Dict

from .types import Payload

# Monotonic counters so that repeated calls in one test never collide on a
# uniqueness rule (a premises street_address is "unique within that partner's
# file", PRD §3.1).
_address_counter = itertools.count(1)
_license_counter = itertools.count(1)
_name_counter = itertools.count(1)


def _apply(base: Dict[str, Any], overrides: Dict[str, Any]) -> Payload:
    """Merge overrides into base, dropping keys explicitly overridden to None."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is None and key in merged:
            del merged[key]
        elif value is None:
            continue
        else:
            merged[key] = value
    return merged


def _apply_keep_none(base: Dict[str, Any], overrides: Dict[str, Any]) -> Payload:
    """Merge overrides into base, keeping an explicit ``None`` as a JSON null."""
    merged = dict(base)
    merged.update(overrides)
    return merged


# ── UtilityPartner (PRD §3.1) ──

def partner_payload(**overrides) -> Payload:
    """A registerable partner. Defaults match the four documented policy switches."""
    base = {
        "name": "Cascadia Water",
        "utility_type": "WATER",
        "state_code": "OR",
        "brand_approval_required": True,
        "min_days_between_drops": 21,
        "max_mailings_per_year": 2,
        "rate_filing_required": False,
        "bill_insert_supported": True,
    }
    return _apply(base, overrides)


def minimal_partner_payload(**overrides) -> Payload:
    """Only the three required inputs, so that every default may be observed."""
    base = {"name": "Cascadia Water", "utility_type": "WATER", "state_code": "OR"}
    return _apply(base, overrides)


def partner_status_change_payload(target_status: str, expected_partner_version: int, **overrides) -> Payload:
    base = {
        "target_status": target_status,
        "reason": "Onboarding complete, product filed.",
        "expected_partner_version": expected_partner_version,
    }
    return _apply(base, overrides)


# ── ServiceLineProduct (PRD §3.1) ──

def product_payload(partner_id: str, **overrides) -> Payload:
    """The Water Line Protect filing used throughout the suite."""
    base = {
        "partner_id": partner_id,
        "name": "Water Line Protect",
        "line_type": "WATER_SERVICE_LINE",
        "ownership_boundary": "CURB_STOP",
        "required_owned_segment": "WATER_CURB_STOP_TO_HOME",
        "monthly_price_cents": 2499,
        "waiting_period_days": 30,
        "per_occurrence_cap_cents": 800000,
        "annual_cap_cents": 1000000,
        "permit_covered": True,
        "restoration_covered_scope": "BASIC_BACKFILL",
        "cap_reset_basis": "ENROLLMENT_ANNIVERSARY",
    }
    return _apply(base, overrides)


def tight_cap_product_payload(partner_id: str, **overrides) -> Payload:
    """Sewer Guard Basic: one occurrence can exhaust the whole year.

    ``per_occurrence_cap_cents`` equals ``annual_cap_cents``, the permit is not
    covered and the restoration scope is ``NONE``.
    """
    overrides.pop("partner_id", None)
    base = product_payload(
        partner_id,
        name="Sewer Guard Basic",
        per_occurrence_cap_cents=600000,
        annual_cap_cents=600000,
        permit_covered=False,
        restoration_covered_scope="NONE",
    )
    return _apply(base, overrides)


def minimal_product_payload(partner_id: str, **overrides) -> Payload:
    """Required fields only, so that the three optional filings may default."""
    base = {
        "partner_id": partner_id,
        "name": "Water Line Protect",
        "line_type": "WATER_SERVICE_LINE",
        "ownership_boundary": "CURB_STOP",
        "required_owned_segment": "WATER_CURB_STOP_TO_HOME",
        "monthly_price_cents": 2499,
        "waiting_period_days": 30,
        "per_occurrence_cap_cents": 800000,
        "annual_cap_cents": 1000000,
    }
    return _apply(base, overrides)


# ── Premises (PRD §3.1) ──

def premises_payload(partner_id: str, **overrides) -> Payload:
    """A mailable OR address owning the water curb-stop-to-home segment."""
    base = {
        "partner_id": partner_id,
        "street_address": "12 Alder St",
        "state_code": "OR",
        "owned_segments": ["WATER_CURB_STOP_TO_HOME"],
        "do_not_mail": False,
        "address_status": "GOOD",
    }
    return _apply(base, overrides)


def unique_premises_payload(partner_id: str, **overrides) -> Payload:
    """Same address, with a fresh house number so the uniqueness rule is safe."""
    overrides.pop("partner_id", None)
    number = next(_address_counter)
    base = premises_payload(partner_id, street_address=f"{100 + number} Alder St")
    return _apply(base, overrides)


def minimal_premises_payload(partner_id: str, **overrides) -> Payload:
    """Required fields only, so ``do_not_mail``, ``address_status`` and
    ``known_defect_reported_at`` may be observed defaulting."""
    base = {
        "partner_id": partner_id,
        "street_address": "12 Alder St",
        "state_code": "OR",
        "owned_segments": ["WATER_CURB_STOP_TO_HOME"],
    }
    return _apply(base, overrides)


# ── MarketingCampaign (PRD §3.2) ──

def campaign_payload(partner_id: str, product_id: str, **overrides) -> Payload:
    base = {
        "partner_id": partner_id,
        "product_id": product_id,
        "name": "August curb-stop postcard",
        "piece_type": "POSTCARD",
        "drop_date": "2026-08-05",
        "requested_quantity": 100,
    }
    return _apply(base, overrides)


def campaign_submission_payload(**overrides) -> Payload:
    base = {"note": "Creative and disclosures attached for brand review."}
    return _apply(base, overrides)


def campaign_approval_payload(**overrides) -> Payload:
    base = {
        "decision": "APPROVE",
        "decision_note": "Brand marks and disclosure block approved.",
        "approved_quantity": 100,
    }
    return _apply(base, overrides)


def campaign_rejection_payload(**overrides) -> Payload:
    base = {
        "decision": "REJECT",
        "decision_note": "Disclosure block is too small for the state rule.",
    }
    return _apply(base, overrides)


# ── Enrollment (PRD §3.3) ──

def enrollment_payload(premises_id: str, product_id: str, expected_premises_version: int, **overrides) -> Payload:
    """A DIRECT_BILL policy with the twelve-month prepayment stated explicitly."""
    base = {
        "premises_id": premises_id,
        "product_id": product_id,
        "billing_mode": "DIRECT_BILL",
        "expected_premises_version": expected_premises_version,
        "prepaid_amount_cents": 29988,
    }
    return _apply(base, overrides)


def bill_insert_enrollment_payload(premises_id: str, product_id: str, expected_premises_version: int, **overrides) -> Payload:
    """A BILL_INSERT policy: no prepayment at all (PRD §3.3)."""
    overrides.pop("premises_id", None)
    overrides.pop("product_id", None)
    overrides.pop("expected_premises_version", None)
    base = enrollment_payload(
        premises_id,
        product_id,
        expected_premises_version,
        billing_mode="BILL_INSERT",
        prepaid_amount_cents=None,
    )
    return _apply(base, overrides)


def cancellation_payload(requested_effective_date: str, **overrides) -> Payload:
    base = {"reason": "CUSTOMER_REQUEST", "requested_effective_date": requested_effective_date}
    return _apply(base, overrides)


def billing_event_payload(event_type: str, effective_date: str, **overrides) -> Payload:
    """A billing event. ``amount_cents`` is only added by the caller, because it
    is conditionally required on exactly three of the four event types."""
    base = {"event_type": event_type, "effective_date": effective_date}
    return _apply(base, overrides)


def renewal_notice_payload(new_price_cents: int, renewal_effective_date: str, expected_enrollment_version: int, **overrides) -> Payload:
    base = {
        "new_price_cents": new_price_cents,
        "renewal_effective_date": renewal_effective_date,
        "expected_enrollment_version": expected_enrollment_version,
    }
    return _apply(base, overrides)


# ── Claim (PRD §3.5) ──

def claim_payload(enrollment_id: str, **overrides) -> Payload:
    base = {
        "enrollment_id": enrollment_id,
        "line_type": "WATER_SERVICE_LINE",
        "defect_location": "CURB_STOP_TO_METER",
        "urgency": "ROUTINE",
        "incident_description": "Curb stop weeping into the parking strip.",
    }
    return _apply(base, overrides)


def triage_approval_payload(**overrides) -> Payload:
    base = {"decision": "APPROVE", "coverage_note": "Covered curb-stop segment."}
    return _apply(base, overrides)


def triage_denial_payload(denial_reason: str = "NOT_COVERED_SEGMENT", **overrides) -> Payload:
    base = {
        "decision": "DENY",
        "coverage_note": "Adjuster judges the break outside the insured segment.",
        "denial_reason": denial_reason,
    }
    return _apply(base, overrides)


def appeal_payload(**overrides) -> Payload:
    base = {"appeal_reason": "The curb stop is on the homeowner's side of the meter."}
    return _apply(base, overrides)


def appeal_decision_payload(decision: str, **overrides) -> Payload:
    base = {"decision": decision, "rationale": "Reviewed the filed ownership boundary."}
    return _apply(base, overrides)


# ── Contractor and dispatch (PRD §3.6, §3.7) ──

def contractor_payload(**overrides) -> Payload:
    """Alder Plumbing: certified, licensed to 2027, five open slots."""
    base = {
        "name": "Alder Plumbing",
        "state_code": "OR",
        "license_number": "OR-PL-4471",
        "license_expires_on": "2027-12-31",
        "line_types_certified": ["WATER_SERVICE_LINE"],
        "hourly_rate_cents": 18000,
        "sla_compliance_pct": 92,
        "max_open_dispatches": 5,
        "permit_pull_authorized": True,
    }
    return _apply(base, overrides)


def cheap_contractor_payload(**overrides) -> Payload:
    """Bridgetown Trenching: cheaper labour, weaker record, four open slots."""
    base = contractor_payload(
        name="Bridgetown Trenching",
        license_number="OR-PL-8820",
        license_expires_on="2028-06-30",
        hourly_rate_cents=6000,
        sla_compliance_pct=76,
        max_open_dispatches=4,
    )
    return _apply(base, overrides)


def unique_contractor_payload(**overrides) -> Payload:
    """A contractor with a fresh name and licence number."""
    number = next(_license_counter)
    base = contractor_payload(
        name=f"Cascade Crew {number}",
        license_number=f"OR-PL-{5000 + number}",
    )
    return _apply(base, overrides)


def dispatch_payload(expected_claim_version: int, window_start: str, **overrides) -> Payload:
    """An automatic dispatch: ``contractor_id`` is deliberately absent."""
    base = {"window_start": window_start, "expected_claim_version": expected_claim_version}
    return _apply(base, overrides)


def manual_dispatch_payload(expected_claim_version: int, window_start: str, contractor_id: str, **overrides) -> Payload:
    overrides.pop("expected_claim_version", None)
    overrides.pop("window_start", None)
    base = dispatch_payload(expected_claim_version, window_start, contractor_id=contractor_id)
    return _apply(base, overrides)


def accept_event_payload(**overrides) -> Payload:
    base = {"event_type": "ACCEPT"}
    return _apply(base, overrides)


def arrive_event_payload(**overrides) -> Payload:
    base = {"event_type": "ARRIVE"}
    return _apply(base, overrides)


def complete_event_payload(labor_cents: int = 260000, materials_cents: int = 175000, **overrides) -> Payload:
    """A completion carrying only the two always-present invoice lines."""
    base = {
        "event_type": "COMPLETE",
        "labor_cents": labor_cents,
        "materials_cents": materials_cents,
    }
    return _apply(base, overrides)


def full_complete_event_payload(**overrides) -> Payload:
    """The worked completion of PRD §3.7: 260000 / 175000 / 42000 / 90000."""
    base = complete_event_payload(
        260000,
        175000,
        permit_number="OR-PERMIT-3391",
        permit_fee_cents=42000,
        restoration_cents=90000,
        restoration_scope="BASIC_BACKFILL",
    )
    return _apply(base, overrides)


# ── RegulatorComplaint (PRD §3.8) ──

def complaint_payload(partner_id: str, **overrides) -> Payload:
    base = {
        "partner_id": partner_id,
        "regulator": "PUC",
        "allegation": "Policyholder alleges the curb-stop denial contradicts the marketed coverage boundary.",
    }
    return _apply(base, overrides)


def complaint_response_payload(disposition: str, remedy_type: str, expected_complaint_version: int, **overrides) -> Payload:
    base = {
        "response_summary": "Reviewed the file and the filed coverage schedule in full.",
        "disposition": disposition,
        "remedy_type": remedy_type,
        "expected_complaint_version": expected_complaint_version,
    }
    return _apply(base, overrides)


def escalation_payload(**overrides) -> Payload:
    base = {"escalation_note": "The regulator rejects the unsubstantiated finding."}
    return _apply(base, overrides)


__all__ = [name for name in dir() if name.endswith("_payload")] + ["_apply", "_apply_keep_none"]
