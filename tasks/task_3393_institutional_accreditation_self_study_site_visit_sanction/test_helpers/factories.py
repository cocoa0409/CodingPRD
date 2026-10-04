"""Payload factories — one per endpoint input shape, input fields only (PRD §3–§4)."""
from .constants import (
    CDR_RATES_COMPLIANT,
    CRITERION_CODES,
    FEDERAL_COMPONENT_CODES,
    INDICATOR_METRICS_HEALTHY,
    PANEL_SIZE,
    VISIT_END_ISO,
    VISIT_START_ISO,
)

DEFAULTS = {
    "LEGAL_NAME": "Prairie Private College",
    "LEGAL_STATUS": "PRIVATE_NONPROFIT",
    "STATE_CODE": "IA",
    "FTE_ENROLLMENT": 800,
    "DEGREE_LEVELS": ["ASSOCIATE", "BACCALAUREATE"],
    "PATHWAY": "STANDARD",
    "STATEMENT_OF_INTENT": "We meet the eligibility requirements.",
    "CYCLE_TYPE": "INITIAL_ACCREDITATION",
    "NARRATIVE": "Self-study assurance argument addressing all five criteria.",
    "VISIT_MODALITY": "ON_SITE",
    "REPORT_RECOMMENDATION": "GRANT",
    "REPORT_SUMMARY": "All criteria met.",
    "NEW_LOCATION_STATE": "IA",
    "REQUESTED_PROGRAM_LEVEL": "MASTERS",
    "OWNERSHIP_DETAILS": "Sale of substantially all assets to a new owner.",
}


def institution_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "legal_status": DEFAULTS["LEGAL_STATUS"],
        "state_code": DEFAULTS["STATE_CODE"],
        "fte_enrollment": DEFAULTS["FTE_ENROLLMENT"],
        "degree_levels_offered": list(DEFAULTS["DEGREE_LEVELS"]),
    }
    payload.update(overrides)
    return payload


def institution_patch_payload(expected_institution_version, **fields) -> dict:
    """PATCH body: OCC field is mandatory (PRD §2.7); remaining fields optional."""
    return {"expected_institution_version": expected_institution_version, **fields}


def eligibility_application_payload(pathway=None, **overrides) -> dict:
    payload = {
        "pathway": pathway or DEFAULTS["PATHWAY"],
        "statement_of_intent": DEFAULTS["STATEMENT_OF_INTENT"],
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(decision="APPROVE", adjudication_notes=None) -> dict:
    payload = {"decision": decision}
    if adjudication_notes is not None:
        payload["adjudication_notes"] = adjudication_notes
    return payload


def review_cycle_payload(cycle_type=None, **overrides) -> dict:
    payload = {"cycle_type": cycle_type or DEFAULTS["CYCLE_TYPE"]}
    payload.update(overrides)
    return payload


def federal_compliance_payload(components=None, cohort_default_rates=None) -> dict:
    if components is None:
        components = [
            {"component_code": code, "result": "PASS"} for code in FEDERAL_COMPONENT_CODES
        ]
    if cohort_default_rates is None:
        cohort_default_rates = list(CDR_RATES_COMPLIANT)
    return {"federal_components": components, "cohort_default_rates": cohort_default_rates}


def assurance_argument_payload(**overrides) -> dict:
    payload = {"narrative_text": DEFAULTS["NARRATIVE"]}
    payload.update(overrides)
    return payload


def evidence_item_payload(criterion_code="CRIT_MISSION", ordinal=1, **overrides) -> dict:
    short = criterion_code.replace("CRIT_", "").lower()
    payload = {
        "criterion_code": criterion_code,
        "evidence_type": "POLICY_DOCUMENT",
        "title": f"{short} evidence {ordinal}",
        "document_uri": f"s3://ev/{short}-{ordinal}.pdf",
    }
    payload.update(overrides)
    return payload


def reviewer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Reviewer",
        "specialty_criteria": ["CRIT_MISSION"],
        "quality_rating": 3.00,
        "prior_chair_count": 0,
    }
    payload.update(overrides)
    return payload


def team_assembly_payload(expected_review_cycle_version, visit_modality=None) -> dict:
    return {
        "visit_modality": visit_modality or DEFAULTS["VISIT_MODALITY"],
        "expected_review_cycle_version": expected_review_cycle_version,
    }


def respond_payload(response="ACCEPT") -> dict:
    return {"response": response}


def schedule_visit_payload(visit_start_at=VISIT_START_ISO, visit_end_at=VISIT_END_ISO) -> dict:
    return {"visit_start_at": visit_start_at, "visit_end_at": visit_end_at}


def criterion_ratings_payload(ratings=None) -> list:
    """One rating per criterion; `ratings` may override per criterion (PRD §3.6)."""
    ratings = ratings or {}
    return [
        {"criterion_code": code, "rating": ratings.get(code, "MET")}
        for code in CRITERION_CODES
    ]


def file_report_payload(ratings=None, report_recommendation=None, report_summary=None) -> dict:
    return {
        "criterion_ratings": criterion_ratings_payload(ratings),
        "report_recommendation": report_recommendation or DEFAULTS["REPORT_RECOMMENDATION"],
        "report_summary": report_summary or DEFAULTS["REPORT_SUMMARY"],
    }


def panel_payload(member_reviewer_ids) -> dict:
    return {"member_reviewer_ids": list(member_reviewer_ids)}


def cast_vote_payload(choice="GRANT") -> dict:
    return {"choice": choice}


def sanction_transition_payload(action) -> dict:
    return {"action": action}


def change_request_payload(change_type="NEW_LOCATION", **overrides) -> dict:
    """Carries the type-specific detail field required by the change_type (PRD §3.9)."""
    payload = {"change_type": change_type}
    if change_type == "PROGRAM_LEVEL":
        payload["requested_program_level"] = DEFAULTS["REQUESTED_PROGRAM_LEVEL"]
    elif change_type == "NEW_LOCATION":
        payload["new_location_state"] = DEFAULTS["NEW_LOCATION_STATE"]
    elif change_type == "OWNERSHIP_CHANGE":
        payload["ownership_details"] = DEFAULTS["OWNERSHIP_DETAILS"]
    payload.update(overrides)
    return payload


def decide_payload(decision="APPROVE", decision_notes=None) -> dict:
    payload = {"decision": decision}
    if decision_notes is not None:
        payload["decision_notes"] = decision_notes
    return payload


def indicator_report_payload(period_start, period_end) -> dict:
    return {"period_start": period_start, "period_end": period_end}


def indicator_submit_payload(metrics=None, **overrides) -> dict:
    payload = dict(metrics or INDICATOR_METRICS_HEALTHY)
    payload.update(overrides)
    return payload


def verify_payload(verified=True) -> dict:
    return {"verified": verified}


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
