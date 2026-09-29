"""Payload factories - one per entity, client-supplied input fields only.

Money is always an integer number of cents rendered as a JSON number; basis
points are always integers. Never pass money as a string.
"""
from typing import Any, Dict

from .constants import BASEBALL_U12_CAPS, CHEER_U12_CAPS, SWIM_U14_CAPS


def create_league_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Cedar Park Little League",
        "league_code": "CPL-001",
        "state_code": "TX",
        "governing_body_code": "USYSA",
        "contact_email": "admin@cpl.example",
    }
    payload.update(overrides)
    return payload


def create_sport_classification_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sport_code": "BASEBALL_U12",
        "sport_name": "Baseball U12",
        "hazard_class": "CLASS_2_MODERATE",
        "base_rate_per_participant_cents": 1850,
        "deductible_cents": 25000,
        "per_injury_limit_cents": 2500000,
        "cat_attachment_point_cents": 2500000,
        "aggregate_limit_cents": 25000000,
        "cat_lifetime_max_cents": 100000000,
        "minimum_participants": 25,
        "travel_buffer_minutes": 60,
        "service_category_caps": dict(BASEBALL_U12_CAPS),
    }
    payload.update(overrides)
    return payload


def cheer_u12_classification_payload(**overrides: Any) -> Dict[str, Any]:
    """The high-hazard cheer schedule with a deliberately small aggregate limit."""
    payload = create_sport_classification_payload(
        sport_code="CHEER_U12",
        sport_name="Allstar Cheer U12",
        hazard_class="CLASS_3_HIGH",
        base_rate_per_participant_cents=2450,
        deductible_cents=15000,
        per_injury_limit_cents=300000,
        cat_attachment_point_cents=300000,
        aggregate_limit_cents=500000,
        cat_lifetime_max_cents=600000,
        minimum_participants=12,
        travel_buffer_minutes=45,
        service_category_caps=dict(CHEER_U12_CAPS),
    )
    payload.update(overrides)
    return payload


def swim_u14_classification_payload(**overrides: Any) -> Dict[str, Any]:
    """The low-hazard swim schedule with a small catastrophic lifetime maximum."""
    payload = create_sport_classification_payload(
        sport_code="SWIM_U14",
        sport_name="Swimming U14",
        hazard_class="CLASS_1_LOW",
        base_rate_per_participant_cents=900,
        deductible_cents=10000,
        per_injury_limit_cents=500000,
        cat_attachment_point_cents=500000,
        aggregate_limit_cents=4000000,
        cat_lifetime_max_cents=100000,
        minimum_participants=10,
        travel_buffer_minutes=30,
        service_category_caps=dict(SWIM_U14_CAPS),
    )
    payload.update(overrides)
    return payload


def create_league_policy_payload(
    league_id: str, sport_classification_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "league_id": league_id,
        "sport_classification_id": sport_classification_id,
        "term_effective_date": "2026-03-01",
        "term_expiration_date": "2027-03-01",
        "enrolled_participant_count": 404,
        "coverage_basis_election": "EXCESS_ONLY",
        "cat_layer_elected": True,
    }
    payload.update(overrides)
    return payload


def create_participant_payload(league_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "league_id": league_id,
        "first_name": "Mira",
        "last_name": "Osei",
        "date_of_birth": "2014-02-11",
        "guardian_email": "guardian@cpl.example",
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(
    participant_id: str, league_policy_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "participant_id": participant_id,
        "league_policy_id": league_policy_id,
        "enrolled_on_date": "2026-03-05",
    }
    payload.update(overrides)
    return payload


def create_family_health_plan_payload(
    participant_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "participant_id": participant_id,
        "carrier_name": "Lone Star Health",
        "policy_number": "LSH-40011",
        "plan_type": "HDHP",
        "individual_deductible_cents": 400000,
        "coinsurance_bps": 3000,
        "effective_date": "2026-01-01",
    }
    payload.update(overrides)
    return payload


def create_sanctioned_activity_payload(
    league_policy_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "league_policy_id": league_policy_id,
        "activity_type": "GAME",
        "venue_name": "Cedar Park Field 1",
        "starts_at": "2026-07-11T18:00:00Z",
        "ends_at": "2026-07-11T20:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_injury_report_payload(
    enrollment_id: str, sanctioned_activity_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "sanctioned_activity_id": sanctioned_activity_id,
        "injury_datetime": "2026-07-11T19:00:00Z",
        "body_part": "KNEE",
        "injury_description": "twisted knee fielding a grounder",
        "severity_tier": "MODERATE",
    }
    payload.update(overrides)
    return payload


def create_provider_bill_payload(claim_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "claim_id": claim_id,
        "provider_npi": "1477203366",
        "provider_name": "Cedar Park Sports Medicine",
        "network_status": "IN_NETWORK",
        "service_category": "EMERGENCY_ROOM",
        "service_date": "2026-07-11",
        "billed_charge_cents": 620000,
        "fee_schedule_amount_cents": 385000,
    }
    payload.update(overrides)
    return payload


def create_coordination_record_payload(
    claim_id: str,
    provider_bill_id: str,
    family_health_plan_id: str,
    expected_claim_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "claim_id": claim_id,
        "provider_bill_id": provider_bill_id,
        "family_health_plan_id": family_health_plan_id,
        "eob_received_date": "2026-07-20",
        "other_plan_allowed_cents": 385000,
        "other_plan_paid_cents": 200000,
        "patient_responsibility_cents": 185000,
        "expected_claim_version": expected_claim_version,
    }
    payload.update(overrides)
    return payload


def create_benefit_payment_payload(
    claim_id: str, provider_bill_id: str, amount_cents: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "claim_id": claim_id,
        "provider_bill_id": provider_bill_id,
        "payee_type": "PROVIDER",
        "layer": "BASE",
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def renewal_quote_payload(
    loss_experience_basis: str,
    renewal_effective_date: str,
    renewal_enrolled_participant_count: int,
    expected_league_policy_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loss_experience_basis": loss_experience_basis,
        "renewal_effective_date": renewal_effective_date,
        "renewal_enrolled_participant_count": renewal_enrolled_participant_count,
        "expected_league_policy_version": expected_league_policy_version,
    }
    payload.update(overrides)
    return payload
