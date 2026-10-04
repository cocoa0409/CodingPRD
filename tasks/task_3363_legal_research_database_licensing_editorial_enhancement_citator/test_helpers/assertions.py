"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_SOURCE_TYPES = ["COURT", "LEGISLATURE", "AGENCY"]
_DOCUMENT_TYPES = ["CASE", "STATUTE", "REGULATION"]
_INGESTION = ["RECEIVED", "PUBLISHED"]
_VISIBILITY = ["PUBLIC", "SEALED", "REMOVED"]
_SIGNALS = ["GREEN", "YELLOW", "RED"]
_TREATMENTS = ["OVERRULED", "CRITICIZED", "QUESTIONED", "DISTINGUISHED", "FOLLOWED", "CITED_NEUTRALLY"]
_DEPTHS = ["EXAMINED", "DISCUSSED", "CITED", "MENTIONED"]
_TOPICS = ["LITIGATION", "CORPORATE", "TAX", "IP", "CRIMINAL", "FAMILY"]
_HEADNOTE_STATUS = ["DRAFT", "IN_REVIEW", "PUBLISHED", "RETRACTED"]
_SUBSCRIPTION_STATUS = ["ACTIVE", "SUSPENDED", "CANCELLED"]
_INVOICE_STATUS = ["DRAFT", "ISSUED", "OVERDUE", "PAID", "VOID"]
_AGREEMENT_STATUS = ["ACTIVE", "TERMINATED"]
_ORDER_STATUS = ["RECEIVED", "APPLIED", "REVERSED"]


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be an int >= 1"


def _assert_ledger_fields(data: dict, entity: str):
    """UsageEvent and RoyaltyStatement carry only id + created_at (PRD §2.5):
    both updated_at and version are absent from them."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not expose updated_at (PRD §2.5)"
    assert "version" not in data, f"{entity} must not expose version (PRD §2.5)"


def assert_document(data: dict):
    _assert_common_fields(data, "PrimaryDocument")
    assert data["source_type"] in _SOURCE_TYPES
    assert data["document_type"] in _DOCUMENT_TYPES
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["raw_citation_string"], str) and data["raw_citation_string"]
    assert data["ingestion_status"] in _INGESTION
    assert data["visibility_status"] in _VISIBILITY
    assert data["citator_signal"] in _SIGNALS
    assert isinstance(data["citator_score"], int)


def assert_citing_reference(data: dict):
    _assert_common_fields(data, "CitingReference")
    assert is_valid_uuid(data["citing_document_id"])
    assert is_valid_uuid(data["cited_document_id"])
    assert data["treatment"] in _TREATMENTS
    assert data["depth"] in _DEPTHS
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_headnote(data: dict):
    _assert_common_fields(data, "Headnote")
    assert is_valid_uuid(data["document_id"])
    assert isinstance(data["author_editor_id"], str) and data["author_editor_id"]
    assert data["topic_code"] in _TOPICS
    assert isinstance(data["headnote_text"], str) and data["headnote_text"]
    assert isinstance(data["synopsis_text"], str)
    assert data["status"] in _HEADNOTE_STATUS


def assert_plan(data: dict):
    _assert_common_fields(data, "SubscriptionPlan")
    assert data["practice_area"] in _TOPICS + ["ALL"]
    assert data["jurisdiction_scope"] in ["FEDERAL", "STATE", "NATIONAL"]
    assert data["firm_size_tier"] in ["SOLO", "SMALL", "MID", "LARGE"]
    assert data["billing_model"] in ["FLAT_RATE", "TRANSACTIONAL"]
    assert data["scope_enforcement"] in ["HARD", "SOFT"]
    assert isinstance(data["government_only"], bool)
    assert isinstance(data["cost_recovery_allowed"], bool)


def assert_account(data: dict):
    _assert_common_fields(data, "SubscriberAccount")
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert data["account_type"] in ["LAW_FIRM", "GOVERNMENT", "CORPORATE"]
    assert isinstance(data["cost_recovery_enabled"], bool)


def assert_subscription(data: dict):
    _assert_common_fields(data, "Subscription")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in _SUBSCRIPTION_STATUS
    assert isinstance(data["seats_total"], int) and data["seats_total"] > 0
    assert isinstance(data["seats_used"], int) and data["seats_used"] >= 0
    assert data["seats_used"] <= data["seats_total"], "seats_used must never exceed seats_total"


def assert_subscriber_user(data: dict):
    _assert_common_fields(data, "SubscriberUser")
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["seat_status"] in ["NONE", "ACTIVE"]


def assert_usage_event(data: dict):
    _assert_ledger_fields(data, "UsageEvent")
    assert is_valid_uuid(data["subscription_id"])
    assert is_valid_uuid(data["user_id"])
    assert data["event_type"] in ["SEARCH", "DOC_VIEW"]
    assert data["practice_area_tag"] in _TOPICS
    assert isinstance(data["in_scope"], bool)
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data["subscription_id"])
    assert data["status"] in _INVOICE_STATUS
    assert data["billing_model"] in ["FLAT_RATE", "TRANSACTIONAL"]
    for field in ("base_fee_cents", "search_count", "doc_view_count",
                  "overage_search_units", "overage_view_units",
                  "overage_fee_cents", "total_cents"):
        assert isinstance(data[field], int), f"Invoice.{field} must be integer cents"
        assert data[field] >= 0, f"Invoice.{field} must be >= 0"
    assert isinstance(data["cost_recovery_allocation"], list)


def assert_license_agreement(data: dict):
    _assert_common_fields(data, "LicenseAgreement")
    assert isinstance(data["work_title"], str) and data["work_title"]
    assert isinstance(data["author_name"], str) and data["author_name"]
    assert data["practice_area"] in _TOPICS
    assert data["royalty_basis"] in ["PER_VIEW", "REVENUE_SHARE"]
    assert isinstance(data["exclusive"], bool)
    assert data["status"] in _AGREEMENT_STATUS


def assert_royalty_statement(data: dict):
    _assert_ledger_fields(data, "RoyaltyStatement")
    assert is_valid_uuid(data["license_agreement_id"])
    assert isinstance(data["view_count"], int) and data["view_count"] >= 0
    assert isinstance(data["revenue_base_cents"], int) and data["revenue_base_cents"] >= 0
    assert isinstance(data["royalty_amount_cents"], int) and data["royalty_amount_cents"] >= 0


def assert_removal_order(data: dict):
    _assert_common_fields(data, "RemovalOrder")
    assert is_valid_uuid(data["document_id"])
    assert data["scope"] in ["SEAL", "REMOVE"]
    assert data["status"] in _ORDER_STATUS


def assert_cost_recovery_allocation_total(invoice: dict):
    """Domain invariant (PRD §3.6): the allocation shares sum to the invoice
    total, and every row carries matter_code, event_count and amount_cents."""
    allocation = invoice["cost_recovery_allocation"]
    total = sum(row["amount_cents"] for row in allocation)
    assert total == invoice["total_cents"], (
        f"allocation shares {total} must sum to total_cents {invoice['total_cents']}"
    )
    for row in allocation:
        assert isinstance(row["matter_code"], str) and row["matter_code"]
        assert isinstance(row["event_count"], int) and row["event_count"] > 0
        assert isinstance(row["amount_cents"], int) and row["amount_cents"] >= 0
