"""Payload factories — one per entity, input fields only (PRD section 4)."""


def applicant_payload(**overrides) -> dict:
    defaults = {"legal_name": "Test Generics LLC",
                "contact_email": "reg@test-generics.example",
                "headquarters_country": "US"}
    defaults.update(overrides)
    return defaults


def reference_product_payload(**overrides) -> dict:
    defaults = {"brand_name": "Brandex", "active_ingredient": "brandexol",
                "strength": "20 mg", "dosage_form": "TABLET",
                "rld_approval_date": "2010-01-01", "is_new_chemical_entity": False,
                "indication_codes": ["IND-A"], "patent_owner_user_id": "innovator-ops-1"}
    defaults.update(overrides)
    return defaults


def listed_patent_payload(**overrides) -> dict:
    defaults = {"patent_number": "US1234567", "patent_type": "DRUG_SUBSTANCE",
                "expiry_date": "2030-01-01"}
    defaults.update(overrides)
    # use_code is required exactly when patent_type is METHOD_OF_USE (PRD 3.2);
    # omit the key entirely otherwise.
    if defaults.get("patent_type") != "METHOD_OF_USE":
        defaults.pop("use_code", None)
    return defaults


def protected_indication_payload(**overrides) -> dict:
    defaults = {"indication_code": "IND-A",
                "effective_from": "2026-01-01", "protected_until": "2028-01-01"}
    defaults.update(overrides)
    return defaults


def application_payload(reference_product_id, applicant_id, **overrides) -> dict:
    defaults = {"reference_product_id": reference_product_id,
                "applicant_id": applicant_id,
                "review_priority": "STANDARD",
                "labeling_mode": "FULL",
                "carved_indication_codes": []}
    defaults.update(overrides)
    return defaults


def be_study_payload(**overrides) -> dict:
    """Defaults describe an adequate study (all rounded CI bounds inside 80-125)."""
    defaults = {"study_type": "FASTING", "analyte": "analyte-x",
                "auc_ratio_pct": 100.0, "auc_ci_low_pct": 92.0, "auc_ci_high_pct": 108.0,
                "cmax_ratio_pct": 99.0, "cmax_ci_low_pct": 90.0, "cmax_ci_high_pct": 110.0}
    defaults.update(overrides)
    return defaults


def certification_payload(patent_id, expected_application_version, **overrides) -> dict:
    defaults = {"patent_id": patent_id,
                "certification_type": "PARAGRAPH_IV_CHALLENGE",
                "expected_application_version": expected_application_version}
    defaults.update(overrides)
    return defaults


def facility_payload(applicant_id, **overrides) -> dict:
    defaults = {"applicant_id": applicant_id, "facility_name": "Test Plant",
                "fei_number": "FEI-TEST-1", "country_code": "US"}
    defaults.update(overrides)
    return defaults


def inspection_payload(facility_id, application_id, **overrides) -> dict:
    defaults = {"facility_id": facility_id, "application_id": application_id,
                "scheduled_start_date": "2026-09-05", "scheduled_end_date": "2026-09-07"}
    defaults.update(overrides)
    return defaults


def amendment_payload(expected_application_version, **overrides) -> dict:
    defaults = {"classification": "MINOR", "contains_new_be_data": False,
                "expected_application_version": expected_application_version}
    defaults.update(overrides)
    return defaults


def supplement_payload(**overrides) -> dict:
    defaults = {"change_type": "LABELING", "pathway": "CBE_30"}
    defaults.update(overrides)
    return defaults
