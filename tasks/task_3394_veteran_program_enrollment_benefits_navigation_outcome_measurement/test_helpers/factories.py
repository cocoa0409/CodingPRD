"""Payload factories — one per creatable resource, input fields only."""
from .constants import CLOCK_START_ISO


def clock_payload(to_iso8601=CLOCK_START_ISO) -> dict:
    return {"to_iso8601": to_iso8601}


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Veteran",
        "member_type": "VETERAN",
        "branch_of_service": "ARMY",
        "service_era_claimed": "POST_911",
        "injury_connection_claimed": "SERVICE_CONNECTED",
    }
    defaults.update(overrides)
    return defaults


def create_family_member_payload(**overrides) -> dict:
    """FAMILY_SUPPORT members must not carry branch_of_service (PRD section 3.1)."""
    defaults = {
        "full_name": "Test Family Member",
        "member_type": "FAMILY_SUPPORT",
        "service_era_claimed": "POST_911",
        "injury_connection_claimed": "NON_SERVICE_CONNECTED",
    }
    defaults.update(overrides)
    return defaults


def create_program_track_payload(**overrides) -> dict:
    defaults = {
        "track_code": "MENTAL_HEALTH",
        "name": "Mental Health Track",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_case_payload(member_id, expected_member_version, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults


def case_transition_payload(target_status, **overrides) -> dict:
    defaults = {"target_status": target_status}
    defaults.update(overrides)
    return defaults


def verify_decision_payload(verified_service_era="POST_911",
                            verified_injury_connection="SERVICE_CONNECTED") -> dict:
    return {
        "target_status": "VERIFIED",
        "verified_service_era": verified_service_era,
        "verified_injury_connection": verified_injury_connection,
    }


def create_external_service_record_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "organization_name": "VetHelp Alliance",
        "service_category": "BENEFITS",
        "start_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(member_id, program_track_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "program_track_id": program_track_id,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(psych_score=5, phys_score=5, voc_score=5, soc_score=5,
                              **overrides) -> dict:
    defaults = {
        "psych_score": psych_score,
        "phys_score": phys_score,
        "voc_score": voc_score,
        "soc_score": soc_score,
    }
    defaults.update(overrides)
    return defaults


def enrollment_transition_payload(target_status, **overrides) -> dict:
    defaults = {"target_status": target_status}
    defaults.update(overrides)
    return defaults


def create_claim_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "claim_type": "DISABILITY_COMPENSATION",
        "claimed_rating_pct": 40,
        "dependent_count": 0,
    }
    defaults.update(overrides)
    return defaults


def claim_decision_payload(outcome="GRANTED", decided_rating_pct=40) -> dict:
    return {"outcome": outcome, "decided_rating_pct": decided_rating_pct}


def create_appeal_payload(claim_id, **overrides) -> dict:
    defaults = {"claim_id": claim_id}
    defaults.update(overrides)
    return defaults


def appeal_decision_payload(outcome="UPHELD", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_referral_payload(member_id, expected_member_version, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "region": "SE",
        "required_specialty": "PTSD",
        "treatment_start": "2026-10-01T00:00:00Z",
        "treatment_end": "2026-11-01T00:00:00Z",
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults


def referral_transition_payload(action) -> dict:
    return {"action": action}


def create_partner_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Partner IOP",
        "region": "SE",
        "specialties": ["PTSD"],
        "capacity": 4,
    }
    defaults.update(overrides)
    return defaults


def create_employer_partner_payload(**overrides) -> dict:
    defaults = {
        "name": "Employer Co",
        "industry": "RETAIL",
        "open_requisitions": 1,
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(member_id, employer_partner_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "employer_partner_id": employer_partner_id,
        "start_date": "2026-09-15T00:00:00Z",
        "salary_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults


def placement_transition_payload(action, **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def create_community_event_payload(**overrides) -> dict:
    defaults = {
        "name": "Community Event",
        "starts_at": "2026-10-20T09:00:00Z",
        "ends_at": "2026-10-20T11:00:00Z",
        "capacity": 5,
        "accessibility_seat_count": 0,
        "travel_budget_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_event_registration_payload(member_id, community_event_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "community_event_id": community_event_id,
    }
    defaults.update(overrides)
    return defaults


def registration_transition_payload(action) -> dict:
    return {"action": action}


def survey_submission_payload(q1=3, q2=3, q3=3, q4=3, q5=3) -> dict:
    return {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5}


def create_donor_report_payload(period_start, period_end, methodology="ITT",
                                **overrides) -> dict:
    defaults = {
        "period_start": period_start,
        "period_end": period_end,
        "methodology": methodology,
    }
    defaults.update(overrides)
    return defaults
