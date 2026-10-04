"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_medical_group(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert isinstance(data["tin"], str) and data["tin"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["status"] in ("FORMING", "OPERATING")


def assert_market(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert is_valid_uuid(data.get("medical_group_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["max_practices"], int)
    assert isinstance(data["market_weight"], (int, float))


def assert_practice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in (
        "PROSPECT", "ONBOARDING", "AFFILIATED", "SUSPENDED", "DEPARTING", "DEPARTED"
    )
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["org_npi"], str)
    assert isinstance(data["active_provider_count"], int)


def assert_provider(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("ROSTERED", "ACTIVE", "DEACTIVATED")
    assert data["provider_role"] in ("PHYSICIAN", "APP")


def assert_affiliation_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("DRAFT", "EXECUTED", "SUPERSEDED", "TERMINATED")
    assert isinstance(data["agreement_seq"], int)
    assert data["distribution_model"] == "NET_OF_SHARED_SERVICES"


def assert_implementation_wave(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("PLANNED", "LOCKED", "IN_CUTOVER", "COMPLETE")


def assert_payer_contract(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("NEGOTIATION", "ACTIVE", "TERMINATED")
    assert data["contract_type"] in ("FEE_FOR_SERVICE", "VALUE_BASED", "HYBRID")


def assert_fee_schedule_rate(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("PROPOSED", "ACTIVE", "SUPERSEDED")


def assert_credentialing_enrollment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "EFFECTIVE", "TERMINATED")
    assert data["channel"] in ("STANDARD", "EXPEDITED")


def assert_collection_batch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("POSTED", "SETTLED", "ADJUSTED")
    assert isinstance(data["posted_amount_cents"], int)


def assert_distribution_statement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("PROVISIONAL_ISSUED", "FINAL_ISSUED", "AMENDED", "REISSUED")


def assert_incentive_pool(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("OPEN", "SCORING", "ALLOCATED", "DISTRIBUTED", "VOIDED")
    assert isinstance(data["pool_amount_cents"], int)


def assert_incentive_allocation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("ENTERED", "SCORED", "INELIGIBLE", "PAYABLE", "PAID", "VOIDED")


def assert_departure_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("UNDER_REVIEW", "SETTLEMENT_PENDING", "DISPUTED", "SETTLED", "RESCINDED")


def assert_committee_vote(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ("OPEN", "PASSED", "REJECTED")
    assert data["motion_type"] in ("PAYER_CONTRACT_RATIFICATION", "FEE_SCHEDULE_ADOPTION")
    assert isinstance(data["votes_for"], int)
    assert isinstance(data["votes_against"], int)


def assert_statement_money_invariant(data: dict):
    """After finalize/amend, gross == fee + net must hold exactly."""
    gross = data["gross_collections_cents"]
    fee = data["shared_services_fee_cents"]
    net = data["net_distribution_cents"]
    assert gross == fee + net, f"gross {gross} != fee {fee} + net {net}"
