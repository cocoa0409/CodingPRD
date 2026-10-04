"""Payload factories — one per resource, declared input fields only."""

DEFAULTS = {
    "HOSPITAL_NAME": "Test Community Hospital",
    "CCN": "269001",
    "STATE_CODE": "MO",
    "BED_COUNT": 100,
    "TEACHING_STATUS": "NON_TEACHING",
    "ANNUAL_DISCHARGES": 2000,
    "CONTACT_EMAIL": "survey@example.org",
    "METHODOLOGY_LABEL": "Test Methodology",
    "PUBLICATION_DATE": "2026-05-01T00:00:00Z",
    "CYCLE_LABEL": "Test Grades",
    "PRELIMINARY_RELEASE_DATE": "2026-06-01T00:00:00Z",
    "CORRECTION_WINDOW_ENDS_AT": "2026-06-30T00:00:00Z",
    "CYCLE_PUBLICATION_DATE": "2026-07-15T00:00:00Z",
    "STARTED_COUNT": 800,
    "COMPLETED_COUNT": 600,
    "ENTITY_ANNUAL_DISCHARGES": 1000,
    "SUPPORTING_REFERENCE": "Corrected extract from the 2026 Q1 abstract",
    "EMPLOYER_NAME": "Test Benefits Trust",
    "PURCHASER_TYPE": "SELF_INSURED_EMPLOYER",
    "MINIMUM_ACCEPTABLE_LETTER": "B",
    "BENEFIT_WINDOW_FROM": "2026-01-01T00:00:00Z",
    "BENEFIT_WINDOW_TO": "2026-12-31T00:00:00Z",
    "DOCUMENT_ISSUED_ON": "2026-05-01T00:00:00Z",
}

_CCN_SEQ = {"n": 0}


def next_ccn() -> str:
    """Allocate a distinct six-character certification number."""
    _CCN_SEQ["n"] += 1
    return f"269{_CCN_SEQ['n']:03d}"


def create_hospital_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["HOSPITAL_NAME"],
        "ccn": next_ccn(),
        "state_code": DEFAULTS["STATE_CODE"],
        "bed_count": DEFAULTS["BED_COUNT"],
        "teaching_status": DEFAULTS["TEACHING_STATUS"],
        "annual_discharges": DEFAULTS["ANNUAL_DISCHARGES"],
        "survey_contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def update_hospital_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def measure_definition(measure_code, domain, scale_factor=1.0, weight=1.0,
                       multiplier=1.0, peer_mean=50.00, peer_sd=10.00,
                       higher_is_better=True, derivation_rule="NONE") -> dict:
    return {
        "measure_code": measure_code,
        "domain": domain,
        "scale_factor": scale_factor,
        "weight": weight,
        "multiplier": multiplier,
        "peer_mean": peer_mean,
        "peer_sd": peer_sd,
        "higher_is_better": higher_is_better,
        "derivation_rule": derivation_rule,
    }


def create_methodology_version_payload(measure_definitions, **overrides) -> dict:
    payload = {
        "label": DEFAULTS["METHODOLOGY_LABEL"],
        "measure_definitions": measure_definitions,
        "publication_date": DEFAULTS["PUBLICATION_DATE"],
    }
    payload.update(overrides)
    return payload


def pin_methodology_version_payload(methodology_version_id) -> dict:
    return {"methodology_version_id": methodology_version_id}


def pending_methodology_change_payload(to_methodology_version_id) -> dict:
    return {"to_methodology_version_id": to_methodology_version_id}


def create_survey_payload(**overrides) -> dict:
    payload = {
        "started_survey_count": DEFAULTS["STARTED_COUNT"],
        "completed_survey_count": DEFAULTS["COMPLETED_COUNT"],
        "entity_annual_discharges": DEFAULTS["ENTITY_ANNUAL_DISCHARGES"],
        "validation_method": "SOURCE_DOCUMENT",
    }
    payload.update(overrides)
    return payload


def create_survey_measure_payload(survey_id, measure_code, raw_value,
                                  source_program_id="CMS_HOSPITAL_COMPARE", **overrides) -> dict:
    payload = {
        "survey_id": survey_id,
        "measure_code": measure_code,
        "raw_value": raw_value,
        "source_program_id": source_program_id,
    }
    payload.update(overrides)
    return payload


def create_public_source_measure_payload(measure_code, source_program_id, source_value) -> dict:
    return {
        "measure_code": measure_code,
        "source_program_id": source_program_id,
        "source_value": source_value,
    }


def refresh_measures_payload(expected_hospital_version) -> dict:
    return {"expected_hospital_version": expected_hospital_version}


def create_score_run_payload(methodology_version_id, release_cycle_id,
                             expected_hospital_version) -> dict:
    return {
        "methodology_version_id": methodology_version_id,
        "release_cycle_id": release_cycle_id,
        "expected_hospital_version": expected_hospital_version,
    }


def create_release_cycle_payload(methodology_version_id, **overrides) -> dict:
    payload = {
        "label": DEFAULTS["CYCLE_LABEL"],
        "methodology_version_id": methodology_version_id,
        "preliminary_release_date": DEFAULTS["PRELIMINARY_RELEASE_DATE"],
        "correction_window_ends_at": DEFAULTS["CORRECTION_WINDOW_ENDS_AT"],
        "publication_date": DEFAULTS["CYCLE_PUBLICATION_DATE"],
    }
    payload.update(overrides)
    return payload


def create_preliminary_result_payload(grade_id, challenged_measure_codes=None) -> dict:
    payload = {"grade_id": grade_id}
    if challenged_measure_codes is not None:
        payload["challenged_measure_codes"] = challenged_measure_codes
    return payload


def accept_preliminary_result_payload(expected_hospital_version) -> dict:
    return {"expected_hospital_version": expected_hospital_version}


def create_correction_payload(corrected_measure_codes, correction_type="MEASURE_VALUE_ERROR",
                              supporting_reference=None) -> dict:
    return {
        "correction_type": correction_type,
        "corrected_measure_codes": corrected_measure_codes,
        "supporting_reference": supporting_reference or DEFAULTS["SUPPORTING_REFERENCE"],
    }


def decide_correction_payload(decision) -> dict:
    return {"decision": decision}


def supporting_document(document_code, issued_on=None) -> dict:
    return {
        "document_code": document_code,
        "issued_on": issued_on or DEFAULTS["DOCUMENT_ISSUED_ON"],
    }


def create_reanalysis_request_payload(survey_id, subset_selector, supporting_documents=None,
                                      requested_delta=None) -> dict:
    payload = {
        "survey_id": survey_id,
        "subset_selector": subset_selector,
    }
    if supporting_documents is not None:
        payload["supporting_documents"] = supporting_documents
    if requested_delta is not None:
        payload["requested_delta"] = requested_delta
    return payload


def decide_reanalysis_payload(decision) -> dict:
    return {"decision": decision}


def create_employer_payload(network_hospital_ids=None, **overrides) -> dict:
    payload = {
        "name": DEFAULTS["EMPLOYER_NAME"],
        "purchaser_type": DEFAULTS["PURCHASER_TYPE"],
        "minimum_acceptable_letter": DEFAULTS["MINIMUM_ACCEPTABLE_LETTER"],
        "benefit_window_from": DEFAULTS["BENEFIT_WINDOW_FROM"],
        "benefit_window_to": DEFAULTS["BENEFIT_WINDOW_TO"],
    }
    if network_hospital_ids is not None:
        payload["network_hospital_ids"] = network_hospital_ids
    payload.update(overrides)
    return payload


def set_network_listing_payload(network_hospital_ids, **overrides) -> dict:
    payload = {
        "network_hospital_ids": network_hospital_ids,
        "minimum_acceptable_letter": DEFAULTS["MINIMUM_ACCEPTABLE_LETTER"],
        "benefit_window_from": DEFAULTS["BENEFIT_WINDOW_FROM"],
        "benefit_window_to": DEFAULTS["BENEFIT_WINDOW_TO"],
    }
    payload.update(overrides)
    return payload