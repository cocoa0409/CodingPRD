"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VALID_CLIENT_STATUSES = ["ACTIVE", "SUSPENDED"]
VALID_SUPPLIER_STATUSES = ["ACTIVE", "SUSPENDED"]
VALID_SUPPLIER_TYPES = ["PHARMACY", "DISTRIBUTOR", "CLAIM_PROCESSOR"]
VALID_DATA_DOMAINS = ["RETAIL_SCRIPTS", "DISTRIBUTION_SHIPMENTS", "CLAIMS_ADJUDICATION"]
VALID_AGREEMENT_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED"]
VALID_HASH_ALGORITHMS = ["SHA256", "SHA512"]
VALID_BATCH_STATUSES = [
    "RECEIVED", "VALIDATED", "DEIDENTIFIED", "ACCEPTED",
    "REJECTED", "REPROCESSED", "QUARANTINED",
]
VALID_PRESCRIBER_STATUSES = ["ACTIVE", "INACTIVE"]
VALID_SPECIALTIES = ["CARDIOLOGY", "ONCOLOGY", "ENDOCRINOLOGY", "PRIMARY_CARE"]
VALID_OPT_OUT_STATUSES = ["SUBMITTED", "VERIFIED", "ACTIVE", "REJECTED", "LIFTED"]
VALID_PROJECTION_VARIANTS = ["PROJECTION_WEIGHTED", "PROJECTION_DENSITY"]
VALID_CELL_STATUSES = ["CURRENT", "PENDING_RESTATEMENT"]
VALID_PRODUCT_STATUSES = ["ACTIVE", "SUSPENDED"]
VALID_PERIOD_STATUSES = ["OPEN", "CLOSED"]
VALID_SLA_VARIANTS = ["PERIOD_WEIGHTED", "DELIVERY_WEIGHTED"]
VALID_DELIVERY_STATUSES = ["SCHEDULED", "COMPILED", "RELEASED", "RECALLED", "REISSUED"]
VALID_AUDIT_PURPOSES = ["AUDIT_COMPLIANCE", "REIDENTIFICATION"]
VALID_AUDIT_OUTCOMES = ["CLEAN", "REIDENTIFICATION_ATTEMPTED"]
VALID_AUDIT_STATUSES = ["REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in VALID_CLIENT_STATUSES
    assert isinstance(data["entitlement_cells_total"], int) and data["entitlement_cells_total"] >= 0
    assert isinstance(data["entitlement_cells_balance"], int)


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["supplier_type"] in VALID_SUPPLIER_TYPES
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in VALID_SUPPLIER_STATUSES


def assert_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supplier_id", "")), "supplier_id must be a UUID"
    assert data["data_domain"] in VALID_DATA_DOMAINS
    assert isinstance(data["exclusivity_start_date"], str)
    assert isinstance(data["exclusivity_end_date"], str)
    assert isinstance(data["royalty_budget_cents"], int) and data["royalty_budget_cents"] >= 0
    assert isinstance(data["royalty_spent_cents"], int) and data["royalty_spent_cents"] >= 0
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0
    assert data["status"] in VALID_AGREEMENT_STATUSES


def assert_deid_profile(data: dict):
    # Append-only resource: id + created_at only (no updated_at, no version).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["k_anonymity_threshold"], int) and data["k_anonymity_threshold"] >= 1
    assert isinstance(data["salt_version"], str)
    assert data["hash_algorithm"] in VALID_HASH_ALGORITHMS


def assert_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert isinstance(data["period_code"], str) and len(data["period_code"]) == 7
    assert isinstance(data["record_count"], int) and data["record_count"] >= 1
    assert data["status"] in VALID_BATCH_STATUSES


def assert_prescriber(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["npi"], str) and len(data["npi"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["specialty"] in VALID_SPECIALTIES
    assert data["status"] in VALID_PRESCRIBER_STATUSES


def assert_opt_out(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("prescriber_id", "")), "prescriber_id must be a UUID"
    assert data["status"] in VALID_OPT_OUT_STATUSES


def assert_jurisdiction_rule(data: dict):
    # Append-only resource: id + created_at only (no updated_at, no version).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["restrict_prescriber_identifiable"], bool)
    assert isinstance(data["effective_from"], str)


def assert_methodology(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["default_variant"] in VALID_PROJECTION_VARIANTS
    assert data["status"] == "ACTIVE"


def assert_cell(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("methodology_id", "")), "methodology_id must be a UUID"
    assert isinstance(data["geography_code"], str) and len(data["geography_code"]) > 0
    assert data["specialty"] in VALID_SPECIALTIES
    assert isinstance(data["period_code"], str) and len(data["period_code"]) == 7
    assert isinstance(data["sample_units"], int) and data["sample_units"] >= 0
    assert isinstance(data["market_outlets"], int) and data["market_outlets"] >= 1
    assert isinstance(data["sampled_outlets"], int) and data["sampled_outlets"] >= 1
    assert isinstance(data["market_population"], int) and data["market_population"] >= 1
    assert isinstance(data["sampled_population"], int) and data["sampled_population"] >= 1
    assert isinstance(data["specialty_uptake_index"], (int, float))
    assert data["specialty_uptake_index"] > 0
    assert isinstance(data["supplier_ids"], list)
    assert data["status"] in VALID_CELL_STATUSES


def assert_product(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert is_valid_uuid(data.get("methodology_id", "")), "methodology_id must be a UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["prescriber_ids"], list)
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert isinstance(data["cell_fee_base_cents"], int) and data["cell_fee_base_cents"] >= 0
    assert isinstance(data["cell_fee_multiplier"], (int, float))
    assert isinstance(data["volume_discount_pct"], (int, float))
    assert isinstance(data["support_fee_pct"], (int, float))
    assert isinstance(data["monthly_license_fee_cents"], int) and data["monthly_license_fee_cents"] >= 0
    assert isinstance(data["deliverable_prescriber_count"], int)
    assert isinstance(data["pinned_methodology_version"], int)
    assert data["status"] in VALID_PRODUCT_STATUSES


def assert_delivery_period(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["period_code"], str) and len(data["period_code"]) == 7
    assert isinstance(data["period_end_date"], str)
    assert isinstance(data["total_due_deliveries"], int) and data["total_due_deliveries"] >= 1
    assert data["status"] in VALID_PERIOD_STATUSES


def assert_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("period_id", "")), "period_id must be a UUID"
    assert isinstance(data["period_code"], str) and len(data["period_code"]) == 7
    assert data["status"] in VALID_DELIVERY_STATUSES
    assert isinstance(data["recall_count"], int) and data["recall_count"] >= 0
    assert isinstance(data["must_recompile"], bool)


def assert_audit_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)
    assert data["purpose"] in VALID_AUDIT_PURPOSES
    assert data["status"] in VALID_AUDIT_STATUSES


def assert_client_entitlement_invariants(data: dict):
    """The client entitlement ledger must never go negative or above the ceiling."""
    assert 0 <= data["entitlement_cells_balance"] <= data["entitlement_cells_total"], (
        f"balance {data['entitlement_cells_balance']} outside "
        f"[0, {data['entitlement_cells_total']}]"
    )
