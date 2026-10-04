"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SOCIETY_NAME": "Test Society",
    "SOCIETY_CODE": "TST",
    "APPLICANT_NAME": "Test Applicant",
    "MEETING_CODE": "FEB2027",
    "DESCRIPTOR_CURRENT": "Placeholder descriptor",
    "DESCRIPTOR_PROPOSED": "Placeholder descriptor revised",
    "LICENSEE_NAME": "Test Clinic",
    "TERRITORY_CODE": "US-TEST",
    "ERRATA_REASON": "Practice-expense RVU overstated",
    "WEIGHT_CONTEXT": "Disposition recorded by the editorial panel",
}


def create_specialty_society_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SOCIETY_NAME"],
        "specialty_code": DEFAULTS["SOCIETY_CODE"],
        "voting_seat_count": 1,
        "gpci_work": 1.0000,
        "gpci_pe": 1.0000,
        "gpci_mp": 1.0000,
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["APPLICANT_NAME"],
        "applicant_type": "PHYSICIAN",
        "is_entity_member": True,
        "dues_paid_current": True,
        "contact_email": "applicant@example.org",
    }
    payload.update(overrides)
    return payload


def create_code_change_payload(**overrides) -> dict:
    payload = {
        "code": "90000",
        "change_type": "ADDITION",
        "category": "CATEGORY_I",
        "code_family": "900",
        "clinical_evidence_tier": "TIER_II",
        "evidence_sufficiency_index": 70,
        "procedure_volume_threshold": 700,
        "organ_system_count": 2,
        "descriptor_current": DEFAULTS["DESCRIPTOR_CURRENT"],
        "descriptor_proposed": DEFAULTS["DESCRIPTOR_PROPOSED"],
        "guidelines": "None",
        "parenthetical_instructions": "None",
    }
    payload.update(overrides)
    return payload


def create_meeting_payload(**overrides) -> dict:
    payload = {
        "meeting_code": DEFAULTS["MEETING_CODE"],
        "meeting_month": "FEBRUARY",
        "starts_at": "2027-02-08T14:00:00Z",
        "ends_at": "2027-02-08T23:00:00Z",
        "citation_mode": False,
    }
    payload.update(overrides)
    return payload


def create_release_cycle_payload(**overrides) -> dict:
    payload = {
        "year": 2027,
        "comment_open": "2026-09-01T00:00:00Z",
        "comment_close": "2026-10-01T00:00:00Z",
        "addendum_comment_close": "2027-11-15T00:00:00Z",
        "code_set_capacity": 300,
        "errata_deadline": "2027-06-30T00:00:00Z",
        "single_floor_budgeting": False,
    }
    payload.update(overrides)
    return payload


def create_distribution_territory_payload(**overrides) -> dict:
    payload = {
        "territory_code": DEFAULTS["TERRITORY_CODE"],
        "method": "SITE",
        "edi_payer_network": False,
        "metadata_schema_version": "2026.1",
    }
    payload.update(overrides)
    return payload


def create_licensing_agreement_payload(**overrides) -> dict:
    payload = {
        "licensee_type": "PROVIDER",
        "licensee_name": DEFAULTS["LICENSEE_NAME"],
        "vendor_worldwide": False,
        "expected_users": 20,
        "sales_unit_count": 10,
        "base_fee_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_code_value_payload(**overrides) -> dict:
    payload = {
        "code": "90100",
        "work_rvu": 2.80,
        "facility_pe_rvu": 1.90,
        "nonfacility_pe_rvu": 1.90,
        "mp_rvu": 0.24,
        "conversion_factor": 34.63,
        "rounding_variant": "AGGREGATE_ROUNDING",
    }
    payload.update(overrides)
    return payload


def create_errata_notice_payload(**overrides) -> dict:
    payload = {
        "errata_effective_date": "2027-05-03T00:00:00Z",
        "prior_facility_payment_cents": 18173,
        "reason": DEFAULTS["ERRATA_REASON"],
    }
    payload.update(overrides)
    return payload


def create_content_delivery_order_payload(**overrides) -> dict:
    payload = {
        "distribution_channel": "SITE",
        "format_params": {
            "electronic_format": "NONE",
            "media": "NONE",
            "version_qualifier": "2026.1",
            "payer_identifier_qualifier": "NONE",
        },
        "payer_identifier": "PLACEHOLDER",
    }
    payload.update(overrides)
    return payload


def create_value_recommendation_payload(**overrides) -> dict:
    payload = {
        "code": "90200",
        "work_rvu": 2.80,
        "facility_pe_rvu": 1.90,
        "nonfacility_pe_rvu": 1.90,
        "mp_rvu": 0.24,
        "survey_median_minutes": 15.0,
        "conversion_factor_tier": "AMBULATORY",
    }
    payload.update(overrides)
    return payload


def create_education_activity_payload(**overrides) -> dict:
    payload = {
        "activity_code": "EDU-001",
        "clock_hours": 2.0,
        "assistant_targeted": False,
    }
    payload.update(overrides)
    return payload


def create_interpretation_request_payload(**overrides) -> dict:
    payload = {
        "code": "90000",
        "question": "Does the parenthetical apply to the whole family?",
    }
    payload.update(overrides)
    return payload


def committee_review_payload(**overrides) -> dict:
    payload = {
        "committee_name": "CPT_ADVISOR",
        "quorum_met": True,
        "yes_votes": 8,
        "no_votes": 2,
    }
    payload.update(overrides)
    return payload