"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_registrar(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["iana_number"], int)
    assert 1 <= data["iana_number"] <= 99999
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["application_fee_cents"], int) \
        and data["application_fee_cents"] >= 0
    assert isinstance(data["annual_fee_cents"], int) and data["annual_fee_cents"] >= 0
    assert isinstance(data["escrow_deposit_cents"], int) \
        and data["escrow_deposit_cents"] >= 0
    assert isinstance(data["technical_test_score"], int) \
        and 0 <= data["technical_test_score"] <= 100
    assert isinstance(data["financial_statement_verified"], bool)
    assert isinstance(data["credit_hold"], bool)
    assert data["status"] in [
        "PENDING_TESTS", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_price_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    for fee in ("create_fee_cents", "renew_fee_cents",
                "restore_fee_cents", "transfer_fee_cents"):
        assert isinstance(data[fee], int) and data[fee] >= 0, \
            f"{fee} must be a non-negative integer"
    assert is_iso8601_timestamp(data.get("effective_on", "")), \
        "effective_on must be ISO 8601"
    assert data["status"] in ["PROPOSED", "EFFECTIVE", "SUPERSEDED"]


def assert_domain(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["years"], int) and 1 <= data["years"] <= 10
    assert isinstance(data["premium"], bool)
    assert is_iso8601_timestamp(data.get("expires_on", "")), \
        "expires_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("grace_deadline", "")), \
        "grace_deadline must be ISO 8601"
    assert data["status"] in [
        "ACTIVE", "AUTO_RENEW_GRACE", "REDEMPTION_GRACE",
        "PENDING_DELETE", "DELETED", "TRANSFERRING"]
    assert data["lock_status"] in ["NONE", "CLIENT_LOCK", "REGISTRY_LOCK"]
    assert data["suspension_status"] in ["NONE", "HOLD"]


def assert_nameserver(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["hostname"], str) and len(data["hostname"]) > 0
    assert isinstance(data["ip_addresses"], list) \
        and len(data["ip_addresses"]) >= 1
    assert isinstance(data["capacity_qps"], int) and data["capacity_qps"] > 0


def assert_domain_nameserver_link(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("domain_id", "")), \
        "domain_id must be valid UUID"
    assert is_valid_uuid(data.get("nameserver_id", "")), \
        "nameserver_id must be valid UUID"
    # Append-only resource: updated_at and version are absent (PRD §2.4).
    assert "updated_at" not in data, \
        "DomainNameserverLink must not carry updated_at"
    assert "version" not in data, "DomainNameserverLink must not carry version"


def assert_transfer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert is_valid_uuid(data.get("domain_id", "")), \
        "domain_id must be valid UUID"
    assert is_valid_uuid(data.get("from_registrar_id", "")), \
        "from_registrar_id must be valid UUID"
    assert is_valid_uuid(data.get("to_registrar_id", "")), \
        "to_registrar_id must be valid UUID"
    assert is_iso8601_timestamp(data.get("auth_code_expires_at", "")), \
        "auth_code_expires_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("requested_at", "")), \
        "requested_at must be ISO 8601"
    assert data["status"] in [
        "REQUESTED", "ACKED", "NACKED", "AUTO_ACKED",
        "COMPLETED", "DISPUTED", "REVERSED"]


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert data["kind"] in [
        "CREATE", "RENEW", "AUTO_RENEW", "RESTORE", "TRANSFER", "ACCREDITATION"]
    assert isinstance(data["base_cents"], int)
    assert isinstance(data["premium_surcharge_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ["OPEN", "VOIDED"]


def assert_ledger_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "LedgerEntry must not carry updated_at"
    assert "version" not in data, "LedgerEntry must not carry version"
    assert is_valid_uuid(data.get("registrar_id", "")), \
        "registrar_id must be valid UUID"
    assert isinstance(data["amount_cents"], int)
    assert data["entry_type"] in ["TOP_UP", "DEBIT", "VOID_CREDIT", "WRITE_OFF"]


def assert_abuse_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert is_valid_uuid(data.get("domain_id", "")), \
        "domain_id must be valid UUID"
    assert data["category"] in ["PHISHING", "MALWARE", "SPAM", "OTHER"]
    assert data["status"] in ["FILED", "UNDER_REVIEW", "ACTIONED", "DISMISSED"]


def assert_court_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["case_reference"], str) \
        and len(data["case_reference"]) > 0
    assert data["action"] in ["SUSPEND", "UNSUSPEND", "TRANSFER_TO_REGISTRY"]
    assert isinstance(data["effective_immediately"], bool)
    assert data["status"] in ["LODGED", "ENFORCED"]


def assert_accreditation_notice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, \
        "RegistrarAccreditationNotice must not carry updated_at"
    assert "version" not in data, \
        "RegistrarAccreditationNotice must not carry version"
    assert is_valid_uuid(data.get("registrar_id", "")), \
        "registrar_id must be valid UUID"
    assert is_valid_uuid(data.get("price_schedule_id", "")), \
        "price_schedule_id must be valid UUID"
    assert data["notice_kind"] in [
        "PRICE_INCREASE_ANNOUNCED", "PRICE_INCREASE_EFFECTIVE"]
    assert is_iso8601_timestamp(data.get("sent_at", "")), \
        "sent_at must be ISO 8601"


def assert_invoice_invariants(data: dict):
    """PRD §2.6: total_cents is always the sum of the other two."""
    assert data["total_cents"] == (
        data["base_cents"] + data["premium_surcharge_cents"]
    ), (
        f"total_cents {data['total_cents']} must equal base_cents "
        f"{data['base_cents']} + premium_surcharge_cents "
        f"{data['premium_surcharge_cents']}"
    )
