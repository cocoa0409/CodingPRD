"""Entity assertions and domain invariant helpers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant


def assert_mutable_common_fields(data: dict):
    """The full quartet carried by mutable resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_common_fields(data: dict):
    """Append-only artifacts carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_provider(data: dict):
    assert_mutable_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_identification_number"], str)
    assert isinstance(data["national_provider_identifier"], str)
    assert data["billing_model"] in {"PROVIDER_FUNDED", "PAYER_FUNDED", "HYBRID"}
    assert data["status"] in {"ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED"}
    assert data["volume_tier_code"] in {"TIER_1", "TIER_2", "TIER_3"}
    assert isinstance(data["account_balance_cents"], int)


def assert_credential(data: dict):
    assert_mutable_common_fields(data)
    assert isinstance(data["submitter_id"], str) and data["submitter_id"]
    assert data["status"] in {"DRAFT", "PENDING_ACTIVATION", "ACTIVE", "REVOKED"}


def assert_payer(data: dict):
    assert_mutable_common_fields(data)
    assert isinstance(data["payer_id_code"], str) and len(data["payer_id_code"]) == 5
    assert data["pricing_model"] in {"PAYER_FUNDED", "PROVIDER_FUNDED", "SHARED"}
    assert data["connectivity_status"] in {"ONLINE", "DEGRADED", "OFFLINE"}


def assert_enrollment(data: dict):
    assert_mutable_common_fields(data)
    assert data["transaction_type"] in {"CLAIMS_837", "REMITTANCE_835", "ELIGIBILITY_270"}
    assert data["status"] in {
        "DRAFT", "SUBMITTED", "PAYER_REVIEW", "APPROVED",
        "REJECTED", "CANCELLED", "RE_SUBMITTED",
    }


def assert_claim(data: dict):
    assert_mutable_common_fields(data)
    assert data["acceptance_status"] in {
        "RECEIVED", "VALIDATING", "ACCEPTED", "REJECTED_CLEARINGHOUSE",
        "FORWARDED", "ACKNOWLEDGED_BY_PAYER", "REJECTED_BY_PAYER",
    }
    assert data["adjudication_status"] in {"NONE", "PENDING", "PAID", "DENIED", "PARTIAL"}
    assert isinstance(data["total_charge_cents"], int)


def assert_remittance(data: dict):
    assert_mutable_common_fields(data)
    assert data["status"] in {"RECEIVED", "POSTED", "FAILED_POSTING", "VOIDED"}
    assert isinstance(data["paid_amount_cents"], int)


def assert_posting_file(data: dict):
    assert_append_only_common_fields(data)
    assert data["status"] in {"GENERATING", "READY", "DELIVERED", "FAILED"}


def assert_inquiry(data: dict):
    assert_mutable_common_fields(data)
    assert data["status"] in {"PENDING", "RESPONDED", "TIMED_OUT", "QUEUED_OUTAGE"}


def assert_outage(data: dict):
    assert_mutable_common_fields(data)
    assert data["severity"] in {"PARTIAL", "FULL"}
    assert data["status"] in {"ACTIVE", "RESOLVED"}


def assert_usage_invoice(data: dict):
    assert_mutable_common_fields(data)
    assert data["status"] in {"OPEN", "FINALIZED", "PAID", "VOID"}
    for field in ("claim_units", "eligibility_units", "remittance_units", "billable_units"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_instants_equal(actual, expected, label: str = "instant"):
    """Compare two instants on their canonical (millisecond) rendering."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )
