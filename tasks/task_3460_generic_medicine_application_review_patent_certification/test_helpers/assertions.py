"""Entity assertions and domain invariant checkers (PRD sections 2.2, 2.5)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_applicant_company(data: dict):
    assert_common_fields(data)
    for f in ("legal_name", "contact_email", "headquarters_country"):
        assert isinstance(data.get(f), str) and data[f], f"{f} must be a non-empty string"


def assert_reference_product(data: dict):
    assert_common_fields(data)
    for f in ("brand_name", "active_ingredient", "strength", "dosage_form",
              "rld_approval_date", "patent_owner_user_id"):
        assert isinstance(data.get(f), str) and data[f], f"{f} must be a non-empty string"
    assert isinstance(data.get("is_new_chemical_entity"), bool)
    assert isinstance(data.get("indication_codes"), list)


def assert_listed_patent(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("LISTED", "EXPIRED")
    assert data.get("patent_type") in ("DRUG_SUBSTANCE", "DRUG_PRODUCT", "METHOD_OF_USE")


def assert_protected_indication(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("ACTIVE", "EXPIRED")
    assert isinstance(data.get("indication_code"), str)


def assert_application(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("DRAFT", "RECEIVED", "TENTATIVE_APPROVAL", "APPROVED",
                                  "REFUSED_APPROVAL", "LAPSED", "WITHDRAWN")
    assert isinstance(data.get("current_cycle_number"), int)
    assert isinstance(data.get("open_deficiency_count"), int)
    assert isinstance(data.get("open_supplement_count"), int)
    assert isinstance(data.get("exclusivity_blocked"), bool)


def assert_be_study(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("ACCEPTED", "DEFICIENT")
    assert isinstance(data.get("is_adequate"), bool)
    assert data.get("study_type") in ("FASTING", "FED")


def assert_certification(data: dict):
    assert_common_fields(data)
    assert data.get("certification_type") in (
        "PARAGRAPH_II_EXPIRED", "PARAGRAPH_III_DEFER", "PARAGRAPH_IV_CHALLENGE")
    assert data.get("status") in ("CERTIFIED", "AMENDED_TO_P3")


def assert_notice(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("NOTICE_SENT", "SUIT_FILED", "NO_SUIT_FILED",
                                  "STAY_EXPIRED", "DECIDED_VALID", "DECIDED_INVALID")
    assert isinstance(data.get("is_timely"), bool)


def assert_review_cycle(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("OPEN", "CRL_ISSUED", "AMENDMENT_RECEIVED",
                                  "CLOSED", "LAPSED")
    assert isinstance(data.get("cycle_number"), int) and data["cycle_number"] >= 1
    assert isinstance(data.get("base_review_months"), int)


def assert_amendment(data: dict):
    assert_common_fields(data)
    assert data.get("classification") in ("MAJOR", "MINOR")
    assert isinstance(data.get("contains_new_be_data"), bool)


def assert_facility(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("is_foreign"), bool)
    assert isinstance(data.get("country_code"), str)


def assert_inspection(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("SCHEDULED", "PASSED", "FAILED", "WAIVED", "CANCELLED")


def assert_supplement(data: dict):
    assert_common_fields(data)
    assert data.get("review_status") in ("SUBMITTED", "APPROVED", "REJECTED",
                                         "WITHDRAWN", "LOGGED")
    assert data.get("effectivity") in ("NOT_EFFECTIVE", "EFFECTIVE", "REVOKED")


def assert_exclusivity_award(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("ELIGIBLE", "AWARDED", "ACTIVE", "EXPIRED", "FORFEITED")
