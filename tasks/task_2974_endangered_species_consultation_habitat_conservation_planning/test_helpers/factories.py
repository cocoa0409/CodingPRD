"""Payload factories - one per entity, input fields only."""

# Canonical domain literals reused across fixtures and tests.
ENDANGERED_SPECIES_NAME = "Gopherus agassizii"
ENDANGERED_SPECIES_COMMON = "Mojave desert tortoise"
THREATENED_SPECIES_NAME = "Vireo bellii pusillus"
THREATENED_SPECIES_COMMON = "Least Bell's vireo"
ACTION_COUNTY_CODE = "06037"
OUT_OF_AREA_COUNTY_CODE = "06059"


def species_payload(**overrides) -> dict:
    """An ENDANGERED, individually counted species with a spring survey season."""
    payload = {
        "scientific_name": ENDANGERED_SPECIES_NAME,
        "common_name": ENDANGERED_SPECIES_COMMON,
        "listing_status": "ENDANGERED",
        "take_authorization_unit": "INDIVIDUALS",
        "take_density_per_acre": 0.40,
        "recovery_unit_population": 4000,
        "survey_season_start_month": 4,
        "survey_season_end_month": 7,
    }
    payload.update(overrides)
    return payload


def threatened_species_payload(**overrides) -> dict:
    payload = species_payload(
        scientific_name=THREATENED_SPECIES_NAME,
        common_name=THREATENED_SPECIES_COMMON,
        listing_status="THREATENED",
        take_density_per_acre=0.25,
        recovery_unit_population=9000,
    )
    payload.update(overrides)
    return payload


def critical_habitat_unit_payload(**overrides) -> dict:
    payload = {
        "unit_code": "CHU-1",
        "acres": 500.00,
        "county_code": ACTION_COUNTY_CODE,
        "designation_status": "FINAL",
        "primary_constituent_elements": ["burrow substrate", "forage cover"],
    }
    payload.update(overrides)
    return payload


def listing_change_payload(new_listing_status="ENDANGERED", **overrides) -> dict:
    payload = {
        "new_listing_status": new_listing_status,
        "rationale": "Range-wide decline documented in the five-year review.",
    }
    payload.update(overrides)
    return payload


def proponent_payload(**overrides) -> dict:
    payload = {
        "org_name": "Sunrise Logistics Park LLC",
        "contact_email": "permits@sunrise-park.example",
        "is_federal_agency": False,
    }
    payload.update(overrides)
    return payload


def project_action_payload(proponent_id, **overrides) -> dict:
    payload = {
        "proponent_id": proponent_id,
        "action_name": "Sunrise Park Phase I",
        "action_type": "NON_FEDERAL",
        "footprint_acres": 200.00,
        "county_code": ACTION_COUNTY_CODE,
        "construction_start_date": "2027-01-01",
        "construction_end_date": "2027-12-31",
    }
    payload.update(overrides)
    return payload


def field_survey_payload(species_id, **overrides) -> dict:
    """A field survey inside the canonical spring detectability season."""
    payload = {
        "species_id": species_id,
        "method": "FIELD_SURVEY",
        "detection_result": "DETECTED",
        "habitat_overlap_acres": 10.00,
        "survey_window_start": "2026-05-04",
        "survey_window_end": "2026-05-08",
    }
    payload.update(overrides)
    return payload


def database_query_payload(species_id, **overrides) -> dict:
    payload = {
        "species_id": species_id,
        "method": "DATABASE_QUERY",
        "detection_result": "DETECTED",
        "habitat_overlap_acres": 7.35,
    }
    payload.update(overrides)
    return payload


def biological_assessment_payload(**overrides) -> dict:
    payload = {
        "ba_narrative": "Effects analysis for 17.35 acres of occupied habitat.",
        "ba_effects_analysis_complete": True,
    }
    payload.update(overrides)
    return payload


def information_request_payload(**overrides) -> dict:
    payload = {"request_note": "Please provide burrow survey transect data."}
    payload.update(overrides)
    return payload


def concurrence_payload(**overrides) -> dict:
    payload = {"concurrence_note": "The agency concurs with the NLAA determination."}
    payload.update(overrides)
    return payload


def conservation_bank_payload(species_id, **overrides) -> dict:
    payload = {
        "bank_name": "Mojave Habitat Bank",
        "covered_species_id": species_id,
        "service_area_county_codes": [ACTION_COUNTY_CODE],
        "credit_price_cents": 250_000,
        "credits_total_minted": 500.00,
    }
    payload.update(overrides)
    return payload


def habitat_conservation_plan_payload(**overrides) -> dict:
    payload = {
        "plan_name": "Sunrise Park HCP",
        "covered_acres": 20.00,
        "permit_term_years": 30,
    }
    payload.update(overrides)
    return payload


def mitigation_commitment_payload(expected_hcp_version, **overrides) -> dict:
    """A conservation-banking commitment; pass conservation_bank_id explicitly."""
    payload = {
        "mechanism": "CONSERVATION_BANK_CREDIT",
        "units": 45.01,
        "expected_hcp_version": expected_hcp_version,
    }
    payload.update(overrides)
    return payload


def in_lieu_fee_commitment_payload(expected_hcp_version, **overrides) -> dict:
    payload = {
        "mechanism": "IN_LIEU_FEE",
        "units": 14.71,
        "expected_hcp_version": expected_hcp_version,
    }
    payload.update(overrides)
    return payload


def permittee_responsible_commitment_payload(expected_hcp_version, **overrides) -> dict:
    payload = {
        "mechanism": "PERMITTEE_RESPONSIBLE",
        "units": 10.00,
        "expected_hcp_version": expected_hcp_version,
    }
    payload.update(overrides)
    return payload


def funding_assurance_payload(contribution_cents, **overrides) -> dict:
    payload = {
        "contribution_cents": contribution_cents,
        "instrument_type": "IRREVOCABLE_LETTER_OF_CREDIT",
    }
    payload.update(overrides)
    return payload


def plan_decision_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision, "decision_note": "Plan meets issuance criteria."}
    payload.update(overrides)
    return payload


def incidental_take_permit_payload(**overrides) -> dict:
    payload = {
        "term_start": "2026-10-01",
        "implementing_agreement_reference": "IA-2026-0417",
    }
    payload.update(overrides)
    return payload


def monitoring_report_payload(expected_permit_version, **overrides) -> dict:
    payload = {
        "period_start": "2027-01-01",
        "period_end": "2027-04-01",
        "take_units_reported": 1.00,
        "mitigation_units_verified": 10.00,
        "expected_permit_version": expected_permit_version,
    }
    payload.update(overrides)
    return payload


def adjudication_payload(decision="ACCEPT", **overrides) -> dict:
    payload = {
        "decision": decision,
        "adjudication_note": "Take and mitigation figures reconcile.",
    }
    payload.update(overrides)
    return payload


def changed_circumstance_event_payload(**overrides) -> dict:
    payload = {
        "circumstance_type": "CHANGED",
        "description": "Multi-year drought reduced forage cover on the mitigation site.",
        "response_cost_cents": 500_000,
    }
    payload.update(overrides)
    return payload


def circumstance_response_payload(contributed_cents, **overrides) -> dict:
    payload = {
        "contributed_cents": contributed_cents,
        "response_note": "Supplemental drought response funded.",
    }
    payload.update(overrides)
    return payload
