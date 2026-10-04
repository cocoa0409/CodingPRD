"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>(data)`` validates the response shape: common fields
(PRD §2.5), field types, and enum membership. ``assert_iso_instant_equal``
compares timestamps by instant (the PRD pins values, not string formats).
"""
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .calc import parse_instant


# ---------------------------------------------------------------------------
# Common-field and timestamp helpers
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict, label: str = "resource"):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive int, got {data.get('version')!r}")


def assert_iso_instant_equal(actual: str, expected: str, label: str = "timestamp"):
    """Compare two ISO-8601 strings by the instant they denote (the PRD pins
    instants, not string formats, for workflow timestamps)."""
    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}")


def _assert_nullable_instant(data: dict, field: str, label: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{label}.{field} must be null or ISO 8601, got {value!r}")


def _assert_enum(value, allowed, label):
    assert value in allowed, f"{label} must be one of {sorted(allowed)}, got {value!r}"


PRODUCT_STATUSES = ("UNREGISTERED", "REGISTERED", "UNDER_REVIEW", "SUSPENDED", "CANCELLED")
APPLICATION_STATUSES = ("DRAFT", "IN_REVIEW", "DATA_DEFICIENCY", "APPROVED", "DENIED", "WITHDRAWN")
STUDY_STATUSES = ("RECEIVED", "ACCEPTED", "REJECTED")
USE_SITE_STATUSES = ("PROPOSED", "ACTIVE", "REMOVED")
TOLERANCE_STATUSES = ("PROPOSED", "ESTABLISHED", "REVOKED")
AMENDMENT_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "WITHDRAWN")
CERTIFICATION_STATUSES = ("ACTIVE", "EXPIRED")
BULLETIN_STATUSES = ("IN_EFFECT", "LIFTED")
REVIEW_CASE_STATUSES = ("SCHEDULED", "OPEN", "DCI_PENDING", "UNDER_REVIEW",
                        "COMPLETED", "REFERRED")
DCI_STATUSES = ("ISSUED", "RESPONDED", "DEFICIENT", "SATISFIED", "DELINQUENT")
PROCEEDING_STATUSES = ("INITIATED", "HEARING_HELD", "EFFECTIVE", "VACATED")
STATE_REGISTRATION_STATUSES = ("SUBMITTED", "GRANTED", "DENIED", "REVOKED", "LAPSED")


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------
def assert_active_ingredient(data: dict):
    assert_common_fields(data, "ActiveIngredient")
    assert isinstance(data["common_name"], str) and data["common_name"]
    assert isinstance(data["cas_number"], str) and data["cas_number"]
    _assert_enum(data["tox_category"], ("I", "II", "III", "IV"), "tox_category")
    assert data["reference_dose_mg_kg_day"] > 0
    assert data["aquatic_lc50_ppm"] > 0


def assert_product(data: dict):
    assert_common_fields(data, "Product")
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert is_valid_uuid(data["active_ingredient_id"])
    assert isinstance(data["registrant_ref"], str) and data["registrant_ref"]
    _assert_enum(data["formulation_type"],
                 ("EMULSIFIABLE_CONCENTRATE", "GRANULAR", "WETTABLE_POWDER",
                  "READY_TO_USE", "SEED_TREATMENT"), "formulation_type")
    _assert_enum(data["classification"], ("GENERAL_USE", "RESTRICTED_USE"), "classification")
    _assert_enum(data["status"], PRODUCT_STATUSES, "status")
    assert data["signal_word"] is None or data["signal_word"] in (
        "DANGER_POISON", "WARNING", "CAUTION")
    assert data["epa_registration_number"] is None or (
        isinstance(data["epa_registration_number"], str)
        and data["epa_registration_number"].startswith("EPA-RR-"))


def assert_application(data: dict):
    assert_common_fields(data, "RegistrationApplication")
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["registrant_ref"], str) and data["registrant_ref"]
    _assert_enum(data["use_pattern"], ("FOOD_USE", "NON_FOOD_USE", "MIXED_USE"), "use_pattern")
    _assert_enum(data["requested_classification"], ("GENERAL_USE", "RESTRICTED_USE"),
                 "requested_classification")
    _assert_enum(data["status"], APPLICATION_STATUSES, "status")
    _assert_nullable_instant(data, "submitted_at", "RegistrationApplication")
    _assert_nullable_instant(data, "review_due_at", "RegistrationApplication")
    _assert_nullable_instant(data, "decided_at", "RegistrationApplication")
    assert isinstance(data["deficiency_count"], int) and data["deficiency_count"] >= 0
    assert data["payment_cents"] is None or isinstance(data["payment_cents"], int)
    assert data["final_classification"] is None or data["final_classification"] in (
        "GENERAL_USE", "RESTRICTED_USE")


def assert_study(data: dict):
    assert_common_fields(data, "StudySubmission")
    parents = [data.get("application_id"), data.get("data_call_in_id")]
    assert sum(p is not None for p in parents) == 1, (
        "exactly one of application_id / data_call_in_id must be set")
    _assert_enum(data["study_type"],
                 ("EFFICACY", "TOXICOLOGY", "ENVIRONMENTAL_FATE", "RESIDUE_CHEMISTRY",
                  "OCCUPATIONAL_EXPOSURE", "ECOLOGICAL_EFFECTS"), "study_type")
    assert isinstance(data["guideline_reference"], str)
    if data["study_type"] == "RESIDUE_CHEMISTRY":
        assert isinstance(data["commodity_code"], str) and data["commodity_code"]
        assert data["field_trial_residue_ppm"] is not None
        assert data["field_trial_residue_ppm"] >= 0
    _assert_enum(data["status"], STUDY_STATUSES, "status")
    assert isinstance(data["submitted_by_ref"], str) and data["submitted_by_ref"]
    _assert_nullable_instant(data, "decided_at", "StudySubmission")


def assert_use_site(data: dict):
    assert_common_fields(data, "UseSite")
    assert is_valid_uuid(data["product_id"])
    _assert_enum(data["origin"], ("INITIAL_APPLICATION", "AMENDMENT"), "origin")
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert isinstance(data["pest_code"], str) and data["pest_code"]
    assert 0 < data["max_application_rate_lbs_acre"] <= 8.0
    assert isinstance(data["max_applications_per_season"], int)
    assert data["max_applications_per_season"] >= 1
    assert isinstance(data["preharvest_interval_days"], int)
    assert data["preharvest_interval_days"] >= 0
    _assert_enum(data["application_method"],
                 ("GROUND", "AERIAL", "CHEMIGATION", "SEED_TREATMENT"), "application_method")
    assert isinstance(data["restricted_entry_interval_hours"], int)
    assert data["restricted_entry_interval_hours"] >= 0
    _assert_enum(data["status"], USE_SITE_STATUSES, "status")
    assert data["pre_removal_status"] is None or data["pre_removal_status"] in USE_SITE_STATUSES
    _assert_nullable_instant(data, "removed_at", "UseSite")


def assert_risk_assessment(data: dict):
    assert_common_fields(data, "RiskAssessment")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["assessor_ref"], str) and data["assessor_ref"]
    _assert_enum(data["tier"], ("SCREENING", "REFINED"), "tier")
    if data["tier"] == "REFINED":
        assert data["pct_crop_treated"] is not None
        assert 0 < data["pct_crop_treated"] <= 1
    assert isinstance(data["assessment_seq"], int) and data["assessment_seq"] >= 1
    for field in ("dietary_exposure_mg_day", "dietary_rq", "occupational_rq",
                  "ecological_rq"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert data[field] >= 0, f"{field} must be non-negative"
    assert isinstance(data["level_of_concern_exceeded"], bool)
    assert is_iso8601_timestamp(data["assessed_at"])


def assert_tolerance(data: dict):
    assert_common_fields(data, "Tolerance")
    assert is_valid_uuid(data["product_id"])
    _assert_enum(data["origin"], ("INITIAL_APPLICATION", "AMENDMENT"), "origin")
    assert isinstance(data["commodity_code"], str) and data["commodity_code"]
    assert data["tolerance_ppm"] > 0
    _assert_enum(data["status"], TOLERANCE_STATUSES, "status")
    _assert_nullable_instant(data, "established_at", "Tolerance")
    _assert_nullable_instant(data, "revoked_at", "Tolerance")
    assert data["pre_revocation_status"] is None or data["pre_revocation_status"] in (
        "PROPOSED", "ESTABLISHED")


def assert_label_amendment(data: dict):
    assert_common_fields(data, "LabelAmendment")
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["registrant_ref"], str) and data["registrant_ref"]
    _assert_enum(data["amendment_type"], ("NEW_USE", "RATE_CHANGE", "METHOD_CHANGE"),
                 "amendment_type")
    assert isinstance(data["payload"], dict)
    _assert_enum(data["status"], AMENDMENT_STATUSES, "status")
    assert isinstance(data["priia_category"], str) and data["priia_category"]
    assert is_iso8601_timestamp(data["submitted_at"])
    assert is_iso8601_timestamp(data["review_due_at"])
    _assert_nullable_instant(data, "decided_at", "LabelAmendment")


def assert_certification(data: dict):
    assert_common_fields(data, "ApplicatorCertification")
    assert isinstance(data["applicator_name"], str) and data["applicator_name"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    _assert_enum(data["category"],
                 ("AGRICULTURAL_PEST_CONTROL", "AERIAL_APPLICATION", "STRUCTURAL",
                  "AQUATIC"), "category")
    assert is_iso8601_timestamp(data["certified_until"])
    _assert_enum(data["status"], CERTIFICATION_STATUSES, "status")
    assert isinstance(data["renewed_count"], int) and data["renewed_count"] >= 0


def assert_bulletin(data: dict):
    assert_common_fields(data, "EndangeredSpeciesBulletin")
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["county_fips"], str) and len(data["county_fips"]) == 5
    _assert_enum(data["restriction_code"], ("PROHIBITED", "RATE_CAP", "SEASONAL_WINDOW"),
                 "restriction_code")
    if data["restriction_code"] == "RATE_CAP":
        assert data["rate_cap_lbs_acre"] is not None and data["rate_cap_lbs_acre"] > 0
    assert isinstance(data["window_start_month"], int) and 1 <= data["window_start_month"] <= 12
    assert isinstance(data["window_end_month"], int) and 1 <= data["window_end_month"] <= 12
    assert isinstance(data["consultation_reference"], str)
    _assert_enum(data["status"], BULLETIN_STATUSES, "status")
    assert is_iso8601_timestamp(data["effective_at"])
    _assert_nullable_instant(data, "lifted_at", "EndangeredSpeciesBulletin")


def assert_review_case(data: dict):
    assert_common_fields(data, "RegistrationReviewCase")
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["due_at"])
    _assert_enum(data["status"], REVIEW_CASE_STATUSES, "status")
    _assert_nullable_instant(data, "completed_at", "RegistrationReviewCase")


def assert_data_call_in(data: dict):
    assert_common_fields(data, "DataCallIn")
    assert is_valid_uuid(data["review_case_id"])
    assert isinstance(data["required_study_types"], list) and data["required_study_types"]
    assert is_iso8601_timestamp(data["response_deadline"])
    _assert_enum(data["status"], DCI_STATUSES, "status")
    assert is_iso8601_timestamp(data["issued_at"])
    _assert_nullable_instant(data, "responded_at", "DataCallIn")
    assert_dci_ledger_partition(data)


def assert_dci_ledger_partition(data: dict):
    """The obligation-ledger invariant: required == satisfied U pending U
    outstanding as sets, at all times (PRD §3.7)."""
    required = set(data["required_study_types"])
    satisfied = set(data["satisfied_study_types"])
    pending = set(data["pending_study_types"])
    outstanding = set(data["outstanding_study_types"])
    assert not (satisfied & pending), "satisfied and pending must be disjoint"
    assert not (satisfied & outstanding), "satisfied and outstanding must be disjoint"
    assert not (pending & outstanding), "pending and outstanding must be disjoint"
    assert satisfied | pending | outstanding == required, (
        f"ledger {satisfied | pending | outstanding} must partition required {required}")


def assert_proceeding(data: dict):
    assert_common_fields(data, "CancellationProceeding")
    assert is_valid_uuid(data["product_id"])
    _assert_enum(data["proceeding_type"], ("CANCELLATION", "SUSPENSION"), "proceeding_type")
    _assert_enum(data["reason"],
                 ("RISK_FINDING", "IMMINENT_HAZARD", "DCI_DELINQUENCY",
                  "REGISTRANT_REQUEST"), "reason")
    _assert_enum(data["status"], PROCEEDING_STATUSES, "status")
    assert isinstance(data["auto_created"], bool)
    assert isinstance(data["initiated_by_ref"], str) and data["initiated_by_ref"]
    assert is_iso8601_timestamp(data["initiated_at"])
    _assert_nullable_instant(data, "hearing_held_at", "CancellationProceeding")
    _assert_nullable_instant(data, "effective_at", "CancellationProceeding")
    _assert_nullable_instant(data, "vacated_at", "CancellationProceeding")
    assert data["pre_effective_product_status"] is None or (
        data["pre_effective_product_status"] in PRODUCT_STATUSES)
    assert data["existing_stocks_authorized_units"] is None or (
        isinstance(data["existing_stocks_authorized_units"], int)
        and data["existing_stocks_authorized_units"] >= 0)
    assert data["stocks_method"] is None or data["stocks_method"] in ("FIXED", "DEPLETION")
    assert data["depletion_rate_units_per_month"] is None or (
        isinstance(data["depletion_rate_units_per_month"], int)
        and data["depletion_rate_units_per_month"] > 0)
    _assert_nullable_instant(data, "allow_sale_until", "CancellationProceeding")
    _assert_nullable_instant(data, "allow_use_until", "CancellationProceeding")
    assert isinstance(data["existing_stocks_disposals"], list)
    assert isinstance(data["existing_stocks_disposed_units"], int)
    assert data["existing_stocks_disposed_units"] >= 0


def assert_state_registration(data: dict):
    assert_common_fields(data, "StateRegistration")
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["registrant_ref"], str) and data["registrant_ref"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    _assert_enum(data["status"], STATE_REGISTRATION_STATUSES, "status")
    assert isinstance(data["additional_restrictions"], list)
    assert data["annual_fee_cents"] is None or (
        isinstance(data["annual_fee_cents"], int) and data["annual_fee_cents"] >= 0)
    assert is_iso8601_timestamp(data["submitted_at"])
    _assert_nullable_instant(data, "granted_at", "StateRegistration")
    _assert_nullable_instant(data, "renewal_due_at", "StateRegistration")
    _assert_nullable_instant(data, "last_renewal_at", "StateRegistration")
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_disposal_total(proceeding: dict):
    """existing_stocks_disposed_units is the sum of units over the
    append-only existing_stocks_disposals records (PRD §3.8)."""
    expected = sum(record["units"] for record in proceeding["existing_stocks_disposals"])
    assert proceeding["existing_stocks_disposed_units"] == expected, (
        f"disposed total {proceeding['existing_stocks_disposed_units']} != "
        f"sum of records {expected}")
