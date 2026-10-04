"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_EPISODE_STATUSES = [
    "INTAKE_PENDING", "SCREENING", "SOR_PENDING", "SOR_REVIEW", "APPROVED",
    "SCHEDULING", "PRE_OP", "SURGERY_DONE", "POST_OP_TRACKING", "CLOSED",
    "AVOIDED", "CANCELLED",
]
_CLAIM_STATUSES = ["PENDING", "APPROVED", "DENIED", "PAID", "ABSORBED"]


def assert_employer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("ein"), str) and data["ein"]
    assert isinstance(data.get("baseline_rate_book"), str)
    assert data.get("status") in ["ACTIVE", "TERMINATED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_bundle_template(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("procedure_family") in [
        "CARDIAC", "ORTHO_JOINT", "BARIATRIC", "SPINE",
    ]
    assert isinstance(data.get("label"), str) and data["label"]
    assert isinstance(data.get("warranty_days"), int) and data["warranty_days"] >= 1
    assert isinstance(data.get("implant_component_cap_cents"), int)
    assert data["implant_component_cap_cents"] >= 0
    assert data.get("readmit_policy") in ["RELATED_ONLY", "ALL_CAUSE"]
    assert data.get("status") in ["ACTIVE", "RETIRED"]


def assert_rate_book(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("book_code"), str) and data["book_code"]
    assert isinstance(data.get("rates"), dict)


def assert_contract(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("employer_id", ""))
    assert is_valid_uuid(data.get("template_id", ""))
    assert isinstance(data.get("template_version"), int)
    assert isinstance(data.get("bundle_price_cents"), int)
    assert data["bundle_price_cents"] > 0
    assert isinstance(data.get("rate_components"), dict)
    assert isinstance(data.get("outlier_threshold_cents"), int)
    assert data["outlier_threshold_cents"] > 0
    assert isinstance(data.get("outlier_share_pct"), int)
    assert 0 <= data["outlier_share_pct"] <= 100
    assert isinstance(data.get("episode_cap_per_month"), int)
    assert data["episode_cap_per_month"] >= 0
    assert isinstance(data.get("concurrent_capacity"), int)
    assert data["concurrent_capacity"] >= 0
    assert isinstance(data.get("travel_benefit_cents"), int)
    assert data["travel_benefit_cents"] >= 0
    assert isinstance(data.get("lodging_benefit_cents"), int)
    assert data["lodging_benefit_cents"] >= 0
    assert isinstance(data.get("companion_allowed"), bool)
    assert isinstance(data.get("change_history"), list)
    assert isinstance(data.get("reprice_count"), int)
    assert data["reprice_count"] >= 0
    assert data.get("status") in ["DRAFT", "ACTIVE", "TERMINATED"]


def assert_patient(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("employer_id"), str)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("dob"), str) and data["dob"]
    assert isinstance(data.get("member_id"), str) and data["member_id"]


def assert_episode(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("patient_id"), str)
    assert isinstance(data.get("contract_id"), str)
    assert data.get("family") in ["CARDIAC", "ORTHO_JOINT", "BARIATRIC", "SPINE"]
    assert isinstance(data.get("intake_request_id"), str)
    assert data.get("status") in _EPISODE_STATUSES
    assert isinstance(data.get("screen_seq"), int) and data["screen_seq"] >= 0
    assert isinstance(data.get("scheduled_start_seq"), int)
    assert isinstance(data.get("surgery_done_seq"), int)
    assert isinstance(data.get("discharge_seq"), int)
    assert isinstance(data.get("warranty_end_seq"), int)
    assert isinstance(data.get("warranty_close_seq"), int)
    assert isinstance(data.get("triage_rank"), int) and data["triage_rank"] in (0, 1)
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_screening(data: dict):
    """Append-only record: id + created_at, no updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("episode_id"), str)
    assert data.get("doc_type") in ["IMAGING", "LAB", "NOTE", "CONSENT"]
    assert data.get("result") in ["CANDIDATE", "NOT_A_CANDIDATE"]
    assert isinstance(data.get("screen_seq"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "Screening is append-only and carries no version"
    assert "updated_at" not in data, "Screening is append-only and carries no updated_at"


def assert_review(data: dict):
    """Append-only record: id + created_at, no updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("episode_id"), str)
    assert data.get("conclusion") in [
        "SURGERY_INDICATED", "SURGERY_UNNECESSARY", "MORE_INFO_NEEDED",
    ]
    assert isinstance(data.get("screen_seq"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "Review is append-only and carries no version"
    assert "updated_at" not in data, "Review is append-only and carries no updated_at"


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("episode_id"), str)
    assert data.get("claim_type") in [
        "BUNDLE_CASE", "RELATED_CARE", "TRAVEL", "LODGING", "READMISSION",
    ]
    assert data.get("submitting_entity") in [
        "HOSPITAL", "SURGERY_CENTER", "ANESTHESIA_GROUP", "TRAVEL_VENDOR",
    ]
    assert isinstance(data.get("service_date_seq"), int)
    assert isinstance(data.get("billed_cents"), int) and data["billed_cents"] >= 0
    assert data.get("status") in _CLAIM_STATUSES


def assert_readmission(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("episode_id"), str)
    assert isinstance(data.get("related"), bool)
    assert isinstance(data.get("provider_billed_cents"), int)
    assert data["provider_billed_cents"] >= 0
    assert isinstance(data.get("recorded_seq"), int)
    assert isinstance(data.get("out_of_window"), bool)
    assert isinstance(data.get("absorbed_cents"), int) and data["absorbed_cents"] >= 0


def assert_benefit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("episode_id"), str)
    assert data.get("kind") in ["TRAVEL", "LODGING"]
    assert data.get("traveler") in ["PATIENT", "COMPANION"]
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert data.get("status") in ["ADMINISTERED", "RELEASED"]


def assert_care_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("episode_id"), str)
    assert data.get("phase") in ["PRE_OP", "POST_OP"]
    assert isinstance(data.get("local_provider_name"), str)
    assert data["local_provider_name"]
    assert isinstance(data.get("required"), bool)
    assert data.get("status") in ["OPEN", "DONE", "WAIVED"]


def assert_employer_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("employer_id"), str)
    assert isinstance(data.get("period_month"), str)
    assert data.get("status") == "GENERATED"
    assert isinstance(data.get("computed_seq"), int)
    assert isinstance(data.get("avoided_procedures_count"), int)
    assert isinstance(data.get("avoided_cost_estimate_cents"), int)
    assert isinstance(data.get("warranty_absorbed_total_cents"), int)
