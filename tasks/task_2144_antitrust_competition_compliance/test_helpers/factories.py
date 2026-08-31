"""Payload factories — one per write endpoint, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


# ─── Business unit ────────────────────────────────────────────────────────

def create_business_unit_payload(**overrides) -> dict:
    payload = {
        "name": "Specialty Resins EMEA",
        "market_code": "EU-RESIN",
        "market_share_bps": 1200,
        "interaction_point_count": 4,
        "competitor_overlap_pct": 25,
        "exposure_budget_points": TEST_DEFAULTS["EXPOSURE_BUDGET_POINTS"],
        "review_minutes_budget": TEST_DEFAULTS["REVIEW_MINUTES_BUDGET"],
    }
    payload.update(overrides)
    return payload


def exposure_adjustment_payload(points_delta, expected_business_unit_version,
                                reason="Carry-over findings from an external investigation",
                                **overrides) -> dict:
    payload = {
        "points_delta": points_delta,
        "reason": reason,
        "expected_business_unit_version": expected_business_unit_version,
    }
    payload.update(overrides)
    return payload


# ─── Employee ─────────────────────────────────────────────────────────────

def create_employee_payload(business_unit_id, **overrides) -> dict:
    n = _next()
    payload = {
        "business_unit_id": business_unit_id,
        "full_name": f"Ruth Adeyemi {n}",
        "email": f"ruth.adeyemi.{n}@example.com",
        "role_category": "SALES",
    }
    payload.update(overrides)
    return payload


def revoke_clearance_payload(reason="Delegate moved to a competitor-facing commercial role") -> dict:
    return {"reason": reason}


# ─── Training ─────────────────────────────────────────────────────────────

def create_curriculum_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "code": f"AT-SALES-{n:03d}",
        "title": "Competitor Contact Rules for Sales",
        "target_role_categories": ["SALES", "PRICING"],
        "duration_minutes": TEST_DEFAULTS["TRAINING_DURATION_MINUTES"],
        "validity_days": TEST_DEFAULTS["TRAINING_VALIDITY_DAYS"],
        "is_mandatory": True,
    }
    payload.update(overrides)
    return payload


def create_training_assignment_payload(employee_id, curriculum_id,
                                       due_at="2026-08-31T00:00:00Z",
                                       **overrides) -> dict:
    payload = {
        "employee_id": employee_id,
        "curriculum_id": curriculum_id,
        "due_at": due_at,
    }
    payload.update(overrides)
    return payload


def complete_training_payload(score=91) -> dict:
    return {"score": score}


def waive_training_payload(reason="Delegate completed equivalent external training in 2025") -> dict:
    return {"reason": reason}


# ─── Trade association ────────────────────────────────────────────────────

def create_association_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "name": f"Coatings Standards Group {n}",
        "approval_tier": "TIER_1_LOW",
        "competitor_density_pct": 0,
    }
    payload.update(overrides)
    return payload


def association_decision_payload(decision="APPROVED") -> dict:
    return {"decision": decision}


# ─── Participation ────────────────────────────────────────────────────────

def create_participation_payload(business_unit_id, association_id, employee_id,
                                 purpose="Standards drafting delegate",
                                 **overrides) -> dict:
    payload = {
        "business_unit_id": business_unit_id,
        "association_id": association_id,
        "employee_id": employee_id,
        "purpose": purpose,
    }
    payload.update(overrides)
    return payload


def legal_clearance_payload(decision="CLEARED", notes="Standards only") -> dict:
    payload = {"decision": decision}
    if notes is not None:
        payload["notes"] = notes
    return payload


def business_justification_payload(
        justification="Standard governs 60 percent of our EMEA line") -> dict:
    return {"justification": justification}


def termination_payload(reason="Forum merged into the European council") -> dict:
    return {"reason": reason}


# ─── Meetings and attendances ─────────────────────────────────────────────

def create_meeting_payload(association_id,
                           scheduled_start="2026-09-10T09:00:00Z",
                           scheduled_end="2026-09-10T11:00:00Z",
                           meeting_type="COMMITTEE",
                           agenda_received=True,
                           **overrides) -> dict:
    payload = {
        "association_id": association_id,
        "meeting_type": meeting_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "agenda_received": agenda_received,
    }
    payload.update(overrides)
    return payload


def create_attendance_payload(meeting_id, participation_id) -> dict:
    return {"meeting_id": meeting_id, "participation_id": participation_id}


def cancel_attendance_payload(reason="Delegate reassigned") -> dict:
    return {"reason": reason}


def submit_minutes_payload(summary="Technical agenda only",
                           topics_discussed=None) -> dict:
    return {
        "summary": summary,
        "topics_discussed": list(topics_discussed) if topics_discussed is not None
        else ["STANDARDS"],
    }


def minutes_review_payload(verdict="CLEAN", findings=None) -> dict:
    return {
        "verdict": verdict,
        "findings": list(findings) if findings is not None else ["NONE"],
    }


def remediation_closure_payload(
        notes="Independent review confirms remediation complete") -> dict:
    return {"notes": notes}


# ─── Competitor contacts ──────────────────────────────────────────────────

def create_contact_payload(business_unit_id, employee_id, **overrides) -> dict:
    payload = {
        "business_unit_id": business_unit_id,
        "employee_id": employee_id,
        "competitor_name": "Rivex SA",
        "contact_channel": "EMAIL",
        "topic_tags": [],
        "pricing_topic": False,
        "occurred_at": "2026-07-20T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def remediation_order_payload(
        instructions="Produce the full written thread and the distribution list") -> dict:
    return {"instructions": instructions}


def remediation_response_payload(
        response="Thread attached; distribution list enclosed") -> dict:
    return {"response": response}


def contact_clearance_payload(notes="No competitively sensitive content") -> dict:
    return {"notes": notes}


def contact_escalation_payload(
        reason="Delegate confirmed forward list prices were discussed") -> dict:
    return {"reason": reason}


# ─── Merger control ───────────────────────────────────────────────────────

def create_transaction_payload(business_unit_id, **overrides) -> dict:
    payload = {
        "business_unit_id": business_unit_id,
        "target_name": "Kelmar Coatings BV",
        "deal_value_cents": 11_000_000_000,
        "assumed_liabilities_cents": 100_000_000,
        "market_valuation_cents": 13_000_000_000,
        "acquirer_total_assets_cents": 50_000_000_000,
        "target_total_assets_cents": 5_000_000_000,
        "signed_at": "2026-06-01T00:00:00Z",
        "exemption_code": "NONE",
    }
    payload.update(overrides)
    return payload


def create_hsr_analysis_payload(transaction_id, expected_transaction_version,
                                valuation_variant="SIGNED_DEAL") -> dict:
    return {
        "transaction_id": transaction_id,
        "valuation_variant": valuation_variant,
        "expected_transaction_version": expected_transaction_version,
    }


# ─── Sites and drills ─────────────────────────────────────────────────────

def create_site_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "name": f"Rotterdam Plant {n}",
        "country_code": "NL",
        "concurrent_drill_capacity": 1,
    }
    payload.update(overrides)
    return payload


def create_drill_payload(site_id,
                         window_start="2026-09-01T08:00:00Z",
                         window_end="2026-09-01T12:00:00Z",
                         drill_type="DAWN_RAID",
                         **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "drill_type": drill_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def complete_drill_payload(score=80, gaps_found=3) -> dict:
    return {"score": score, "gaps_found": gaps_found}


def abort_drill_payload(reason="Site evacuation drill collided with the exercise") -> dict:
    return {"reason": reason}


# ─── Document audits ──────────────────────────────────────────────────────

def create_document_audit_payload(business_unit_id, sample_size=None,
                                  scope_note="Sales deck and pricing memo sample, Q2 2026",
                                  **overrides) -> dict:
    payload = {
        "business_unit_id": business_unit_id,
        "sample_size": sample_size if sample_size is not None
        else TEST_DEFAULTS["SAMPLE_SIZE"],
        "scope_note": scope_note,
    }
    payload.update(overrides)
    return payload


def audit_findings_payload(violation_count, high_risk_phrase_count) -> dict:
    return {
        "violation_count": violation_count,
        "high_risk_phrase_count": high_risk_phrase_count,
    }


# ─── Leniency ─────────────────────────────────────────────────────────────

THREE_AFFECTED_YEARS = [
    {"year": 2023, "affected_commerce_cents": 1_000_000_010},
    {"year": 2024, "affected_commerce_cents": 2_000_000_030},
    {"year": 2025, "affected_commerce_cents": 3_000_000_050},
]

ONE_AFFECTED_YEAR = [{"year": 2024, "affected_commerce_cents": 1_000_000_010}]


def create_leniency_application_payload(business_unit_id, cartel_code="EU-RESIN-2021",
                                        affected_years=None, **overrides) -> dict:
    payload = {
        "business_unit_id": business_unit_id,
        "cartel_code": cartel_code,
        "affected_years": [dict(y) for y in (
            affected_years if affected_years is not None else ONE_AFFECTED_YEAR)],
    }
    payload.update(overrides)
    return payload


def marker_decision_payload(decision="GRANTED") -> dict:
    return {"decision": decision}


def disclosure_submission_payload(gravity_pct=15) -> dict:
    return {"gravity_pct": gravity_pct}


def disclosure_decision_payload(decision="ACCEPTED") -> dict:
    return {"decision": decision}


def withdrawal_payload(reason="Second-look review found no cartel conduct") -> dict:
    return {"reason": reason}


# ─── Risk assessments ─────────────────────────────────────────────────────

def create_risk_assessment_payload(business_unit_id, expected_business_unit_version,
                                   variant="BASELINE") -> dict:
    return {
        "business_unit_id": business_unit_id,
        "variant": variant,
        "expected_business_unit_version": expected_business_unit_version,
    }
