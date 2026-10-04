"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CASE_STATUSES = ["INTAKE", "UNDER_REVIEW", "APPROVED", "DENIED", "MORE_INFO_REQUIRED"]
MEMBER_STATUSES = ["ACTIVE", "SUSPENDED", "DECEASED", "REVOKED"]
CATEGORIES = [
    "OFFICER_CADET", "ENLISTED_ACTIVE", "VETERAN_HONORABLE",
    "FAMILY_SPOUSE", "FAMILY_WIDOW", "FAMILY_CHILD",
]
ORDER_STATUSES = ["REGISTERED", "ACTIVE", "COMPLETED", "CANCELLED"]
CLAIM_STATUSES = ["REQUESTED", "APPROVED", "DENIED", "SUPERSEDED"]
ENTITLEMENT_STATUSES = ["OPEN", "GRANDFATHERED", "CLOSED"]
SURVIVOR_STATUSES = ["OPEN", "GRANTED", "CLOSED"]
HOUSEHOLD_STATUSES = ["ACTIVE", "DISSOLVED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_eligibility_case(data: dict):
    _assert_common(data)
    assert data["status"] in CASE_STATUSES
    assert isinstance(data["applicant_legal_name"], str)
    assert data["basis_type"] in (
        "DIRECT_SERVICE", "FAMILY_DERIVATION", "CADET_APPOINTMENT"
    )


def assert_service_record(data: dict):
    _assert_common(data)
    assert isinstance(data["service_verified"], bool)
    assert isinstance(data["service_days"], int) and data["service_days"] >= 0


def assert_evidence_document(data: dict):
    _assert_common(data)
    assert isinstance(data["content_hash"], str)
    assert data["authenticity_channel"] in (
        "SELF_DECLARED", "ISSUER_CONFIRMED", "ARCHIVES_CONFIRMED"
    )


def assert_member(data: dict):
    _assert_common(data)
    assert data["status"] in MEMBER_STATUSES
    assert data["deployment_posture"] in ("NONE", "DEPLOYED")
    assert data["eligibility_category"] in CATEGORIES
    assert isinstance(data["member_number"], str) and len(data["member_number"]) == 10
    assert data["member_number"].isdigit()
    assert isinstance(data["lineage_depth"], int) and data["lineage_depth"] >= 0


def assert_household(data: dict):
    _assert_common(data)
    assert data["status"] in HOUSEHOLD_STATUSES
    assert isinstance(data["aggregate_product_count"], int)
    assert data["aggregate_product_count"] >= 0


def assert_address(data: dict):
    _assert_common(data)
    assert data["addr_type"] in (
        "DOMESTIC_RESIDENCE", "MILITARY_APO_FPO_DPO", "OVERSEAS_FOREIGN"
    )


def assert_deployment_order(data: dict):
    _assert_common(data)
    assert data["status"] in ORDER_STATUSES
    assert isinstance(data["scra_eligible"], bool)


def assert_protection_claim(data: dict):
    _assert_common(data)
    assert data["status"] in CLAIM_STATUSES
    assert data["claim_type"] in (
        "RATE_REDUCTION", "CLAIM_DEFERRAL", "LEASE_TERMINATION"
    )


def assert_product_offering(data: dict):
    _assert_common(data)
    assert data["product_line"] in ("BANKING", "INSURANCE", "INVESTMENT")
    for cat in data["allowed_categories"]:
        assert cat in CATEGORIES


def assert_entitlement(data: dict):
    _assert_common(data)
    assert data["status"] in ENTITLEMENT_STATUSES
    assert isinstance(data["grandfathered"], bool)
    assert isinstance(data["exposure_cents"], int)


def assert_survivor_case(data: dict):
    _assert_common(data)
    assert data["status"] in SURVIVOR_STATUSES


def assert_available_facet_count(data: dict):
    """The matrix read model: available_facet_count is always a multiple of
    six drawn from {0, 6, 12, 18, 24} (PRD availability-matrix section)."""
    assert data["available_facet_count"] in (0, 6, 12, 18, 24)
