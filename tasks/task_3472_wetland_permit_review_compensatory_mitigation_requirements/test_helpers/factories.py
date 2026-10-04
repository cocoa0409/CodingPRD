"""Payload factories — one per creatable resource, input fields only (PRD §3).

Optional fields are omitted from the payload when set to None, so factories
never send explicit nulls for conditionally-required inputs.
"""
from .types import (
    Agency,
    AaVerdict,
    AppealOutcome,
    CommentType,
    DecisionOutcome,
    LedpaConclusion,
    Mechanism,
    OrganizationType,
    Pathway,
    PlanVerdict,
    ReportOutcome,
    ResolutionTrack,
    ResourceType,
    ScreeningAction,
)


def _drop_none(d):
    return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# Entity creation payloads
# ---------------------------------------------------------------------------
def create_applicant_payload(**overrides) -> dict:
    """POST /wetland-permits/applicants (PRD §3.1)."""
    defaults = {
        "legal_name": "Acme Dredging LLC",
        "organization_type": OrganizationType.CORPORATION.value,
        "contact_email": "permits@acme.example",
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(applicant_id, **overrides) -> dict:
    """POST /wetland-permits/sites (PRD §3.1)."""
    defaults = {
        "applicant_id": applicant_id,
        "site_name": "Piney Branch Tract",
        "state_code": "VA",
        "watershed_code": "18020101",
        "total_acres": 40.0,
        "resource_types_present": [
            ResourceType.FORESTED_WETLAND.value,
            ResourceType.STREAM.value,
        ],
    }
    defaults.update(overrides)
    return defaults


def create_jd_payload(site_id, **overrides) -> dict:
    """POST /wetland-permits/jurisdictional-determinations (PRD §3.1)."""
    defaults = {
        "site_id": site_id,
        "jd_type": "APPROVED",
        "determination": "JURISDICTIONAL",
        "rationale": "Delineation confirmed jurisdiction over the flagged waters",
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(jd_id, **overrides) -> dict:
    """POST /wetland-permits/appeals (PRD §3.2)."""
    defaults = {
        "jd_id": jd_id,
        "grounds_text": "The delineation omitted an intermittent channel",
    }
    defaults.update(overrides)
    return defaults


def impact_line(resource_type=ResourceType.FORESTED_WETLAND.value, impact_acres=2.0) -> dict:
    """One impacts[] line: {resource_type, impact_acres} (PRD §3.3)."""
    return {"resource_type": resource_type, "impact_acres": impact_acres}


def create_application_payload(site_id, jd_id, **overrides) -> dict:
    """POST /wetland-permits/applications (PRD §3.3).

    `general_permit_code` and `enforcement_case_id` are conditional inputs;
    pass them explicitly for GENERAL/ATF_GENERAL and ATF_* pathways. They are
    omitted from the payload when None.
    """
    defaults = {
        "site_id": site_id,
        "jd_id": jd_id,
        "pathway": Pathway.INDIVIDUAL.value,
        "impacts": [impact_line()],
        "project_purpose": "Regional stormwater facility",
        "estimated_cost_dollars": 750000.0,
        "general_permit_code": None,
        "enforcement_case_id": None,
    }
    defaults.update(overrides)
    return _drop_none(defaults)


def patch_application_payload(expected_application_version, **overrides) -> dict:
    """PATCH /wetland-permits/applications/{id} (PRD §2.7, §3.3)."""
    payload = {"expected_application_version": expected_application_version}
    payload.update(_drop_none(overrides))
    return payload


def submit_application_payload(new_jd_id=None) -> dict:
    """POST /wetland-permits/applications/{id}/submit (PRD §3.2, §3.3)."""
    return _drop_none({"new_jd_id": new_jd_id})


def create_alternatives_analysis_payload(application_id, **overrides) -> dict:
    """POST /wetland-permits/alternatives-analyses (PRD §3.4)."""
    defaults = {
        "application_id": application_id,
        "avoidance_demonstrated": True,
        "avoidance_narrative": "Upland bench siting avoids all waters",
        "minimization_steps": [
            "Relocated outfall to upland bench",
            "Reduced footprint by 40 percent",
        ],
        "ledpa_conclusion": LedpaConclusion.PROPOSED_IS_LEDPA.value,
        "offsite_alternatives_considered": 2,
    }
    defaults.update(overrides)
    return defaults


def create_agency_comment_payload(application_id, **overrides) -> dict:
    """POST /wetland-permits/agency-comments (PRD §3.5)."""
    defaults = {
        "application_id": application_id,
        "agency": Agency.EPA.value,
        "comment_type": CommentType.ADVISORY.value,
        "comment_text": "Advisory comment on the proposed activity",
    }
    defaults.update(overrides)
    return defaults


def create_mitigation_plan_payload(application_id, **overrides) -> dict:
    """POST /wetland-permits/mitigation-plans (PRD §3.6).

    `financial_assurance_dollars`, `stewardship_entity_name`, and
    `long_term_stewardship_secured` are optional inputs; they are omitted when
    None. `stewardship_entity_name` is required for PERMITTEE_RESPONSIBLE and
    COMBINATION mechanisms.
    """
    defaults = {
        "application_id": application_id,
        "mechanism": Mechanism.BANK_CREDITS.value,
        "financial_assurance_dollars": None,
        "stewardship_entity_name": None,
        "long_term_stewardship_secured": None,
    }
    defaults.update(overrides)
    return _drop_none(defaults)


def patch_mitigation_plan_payload(expected_plan_version, **overrides) -> dict:
    """PATCH /wetland-permits/mitigation-plans/{id} (PRD §2.7, §3.6)."""
    payload = {"expected_plan_version": expected_plan_version}
    payload.update(_drop_none(overrides))
    return payload


def create_mitigation_bank_payload(**overrides) -> dict:
    """POST /wetland-permits/mitigation-banks (PRD §3.6)."""
    defaults = {
        "bank_name": "Shenandoah Mitigation Bank",
        "sponsor_name": "Shenandoah Conservancy",
        "state_code": "VA",
        "service_area_watersheds": ["18020101"],
        "credit_capacity": {ResourceType.FORESTED_WETLAND.value: 20.0},
        "base_price_per_credit": {ResourceType.FORESTED_WETLAND.value: 30000.0},
    }
    defaults.update(overrides)
    return defaults


def create_credit_transaction_payload(bank_id, plan_id, **overrides) -> dict:
    """POST /wetland-permits/credit-transactions (PRD §3.6)."""
    defaults = {
        "bank_id": bank_id,
        "plan_id": plan_id,
        "resource_type": ResourceType.FORESTED_WETLAND.value,
        "credits": 7.0,
    }
    defaults.update(overrides)
    return defaults


def create_enforcement_case_payload(site_id, responsible_applicant_id, **overrides) -> dict:
    """POST /wetland-permits/enforcement-cases (PRD §3.9)."""
    defaults = {
        "site_id": site_id,
        "responsible_applicant_id": responsible_applicant_id,
        "unauthorized_fill_acres": 2.0,
        "description": "Unpermitted fill placed in forested wetland",
    }
    defaults.update(overrides)
    return defaults


def submit_monitoring_report_payload(coverage_start, coverage_end, **overrides) -> dict:
    """POST /wetland-permits/monitoring-reports/{id}/submit (PRD §3.8)."""
    defaults = {
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "findings_text": "Monitoring findings for the coverage interval",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Action payloads
# ---------------------------------------------------------------------------
def decide_appeal_payload(outcome=AppealOutcome.SUSTAINED.value, decision_rationale=None) -> dict:
    """POST /appeals/{id}/decide; outcome is SUSTAINED or DENIED."""
    return _drop_none(
        {"outcome": outcome, "decision_rationale": decision_rationale or "Decided on the record"}
    )


def screening_payload(action=ScreeningAction.BEGIN.value, return_reason=None) -> dict:
    """POST /applications/{id}/screening; action is BEGIN, RETURN, or APPROVE."""
    return _drop_none({"action": action, "return_reason": return_reason})


def publish_notice_payload(comment_period_days=None) -> dict:
    """POST /applications/{id}/publish-notice; period defaults server-side to 30."""
    return _drop_none({"comment_period_days": comment_period_days})


def render_decision_payload(outcome=DecisionOutcome.ISSUE.value, decision_rationale=None) -> dict:
    """POST /applications/{id}/render-decision; outcome is ISSUE or DENY."""
    return _drop_none(
        {"outcome": outcome, "decision_rationale": decision_rationale}
    )


def review_aa_payload(verdict=AaVerdict.ACCEPT.value, revision_notes=None) -> dict:
    """POST /alternatives-analyses/{id}/review."""
    return _drop_none({"verdict": verdict, "revision_notes": revision_notes})


def review_plan_payload(verdict=PlanVerdict.APPROVE.value, revision_notes=None) -> dict:
    """POST /mitigation-plans/{id}/review."""
    return _drop_none({"verdict": verdict, "revision_notes": revision_notes})


def resolve_comment_payload(resolution_text="Resolved on the record") -> dict:
    """POST /agency-comments/{id}/resolve."""
    return {"resolution_text": resolution_text}


def pay_in_lieu_fee_payload(amount_dollars) -> dict:
    """POST /mitigation-plans/{id}/pay-in-lieu-fee; amount must equal the fee exactly."""
    return {"amount_dollars": amount_dollars}


def review_report_payload(outcome=ReportOutcome.ACCEPTED.value, deficiency_notes=None) -> dict:
    """POST /monitoring-reports/{id}/review; deficiency_notes required for DEFICIENT."""
    return _drop_none({"outcome": outcome, "deficiency_notes": deficiency_notes})


def set_resolution_payload(track=ResolutionTrack.RESTORATION.value, atf_application_id=None) -> dict:
    """POST /enforcement-cases/{id}/set-resolution."""
    return _drop_none({"track": track, "atf_application_id": atf_application_id})
