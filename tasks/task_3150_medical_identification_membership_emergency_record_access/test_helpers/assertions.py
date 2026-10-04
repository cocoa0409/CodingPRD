"""Entity assertions and domain invariant checkers."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_IDENTIFIER_CODE_RE = re.compile(r"^MID-\d{6}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_MEMBER_STATUSES = {"ACTIVE", "SUSPENDED", "CANCELLED"}
_MEMBER_TYPES = {"ADULT", "MINOR"}
_TIERS = {"STANDARD", "PREMIUM", "LIFETIME"}
_ITEM_KINDS = {"CONDITION", "MEDICATION", "ALLERGY"}
_CONDITION_KINDS = {"GENERAL", "COGNITIVE"}
_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_ITEM_STATUSES = {"PENDING_VERIFICATION", "VERIFIED", "REJECTED", "SUPERSEDED"}
_TICKET_STATUSES = {"OPEN", "APPROVED", "REJECTED"}
_LINK_STATUSES = {"ACTIVE", "REVOKED"}
_CONTACT_STATUSES = {"ACTIVE", "REMOVED"}
_DIRECTIVE_TYPES = {"DNR", "POLST", "LIVING_WILL", "HEALTHCARE_PROXY"}
_RELEASE_SCOPES = {"EMERGENCY_ONLY", "EMERGENCY_AND_CONTACTS", "FULL"}
_DIRECTIVE_STATUSES = {"STORED", "RELEASED", "REVOKED"}
_ENGRAVE_MODES = {"MANUAL", "SYNC_WITH_RECORD"}
_ORDER_STATUSES = {"PENDING", "CONFIRMED", "ENGRAVED", "SHIPPED", "CANCELLED"}
_ACCESS_TIERS = {"BASIC", "FULL"}
_LOOKUP_METHODS = {"IDENTIFIER", "HOTLINE"}
_ACCESS_OUTCOMES = {"GRANTED", "DENIED"}
_CASE_STATUSES = {"OPEN", "RESOLVED"}
_REMINDER_KINDS = {"RENEWAL", "RECORD_UPDATE", "LAPSE_WARNING"}
_REMINDER_STATUSES = {"PENDING", "SENT", "CANCELLED"}
_DISPUTE_STATUSES = {"OPEN", "UNDER_REVIEW", "RESOLVED_UPHELD", "RESOLVED_CORRECTED", "DISMISSED"}
_DISCLOSED_SCOPE_SECTIONS = {"CONDITIONS", "MEDICATIONS", "ALLERGIES", "CONTACTS", "DIRECTIVES"}


def _assert_common_fields(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"
    else:
        assert "updated_at" not in data, "append-only resource must not carry updated_at"
        assert "version" not in data, "append-only resource must not carry version"


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["membership_tier"] in _TIERS
    assert data["member_type"] in _MEMBER_TYPES
    assert _ISO_DATE_RE.match(data["date_of_birth"]), "date_of_birth must be YYYY-MM-DD"
    assert isinstance(data["has_cognitive_condition"], bool)
    assert isinstance(data["first_lifetime_sync_order_consumed"], bool)
    assert data["status"] in _MEMBER_STATUSES
    assert data["expires_on"] is None or _ISO_DATE_RE.match(data["expires_on"])
    assert _IDENTIFIER_CODE_RE.match(data["identifier_code"] or ""), (
        f"identifier_code must match MID-######, got {data['identifier_code']!r}"
    )
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["wallet_credit_cents"], int)
    assert isinstance(data["record_revision"], int) and data["record_revision"] >= 0


def assert_guardian_link(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["guardian_member_id"])
    assert isinstance(data["relation_label"], str)
    assert data["status"] in _LINK_STATUSES


def assert_record_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["item_kind"] in _ITEM_KINDS
    assert data["condition_kind"] in _CONDITION_KINDS
    assert isinstance(data["label"], str)
    assert isinstance(data["detail"], str)
    assert data["severity"] in _SEVERITIES
    assert isinstance(data["provider_document_ref"], str)
    assert isinstance(data["record_revision"], int) and data["record_revision"] >= 0
    assert data["status"] in _ITEM_STATUSES


def assert_verification_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["record_item_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["provider_document_ref"], str)
    assert isinstance(data["submission_round"], int) and data["submission_round"] >= 1
    assert data["status"] in _TICKET_STATUSES


def assert_emergency_contact(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["contact_name"], str)
    assert isinstance(data["phone"], str)
    assert isinstance(data["priority_rank"], int)
    assert data["status"] in _CONTACT_STATUSES


def assert_advance_directive(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["directive_type"] in _DIRECTIVE_TYPES
    assert isinstance(data["document_ref"], str)
    assert data["release_scope"] in _RELEASE_SCOPES
    assert data["status"] in _DIRECTIVE_STATUSES


def assert_id_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_sku"], str) and data["product_sku"]
    assert isinstance(data["product_name"], str)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["max_engrave_chars"], int) and data["max_engrave_chars"] >= 1


def assert_product_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["engraving_text"], str)
    assert data["engrave_mode"] in _ENGRAVE_MODES
    assert isinstance(data["synced_revision"], int) and data["synced_revision"] >= 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in _ORDER_STATUSES


def assert_responder_credential(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agency_name"], str)
    assert isinstance(data["credential_code"], str) and data["credential_code"]
    assert data["access_tier"] in _ACCESS_TIERS
    assert _ISO_DATE_RE.match(data["expires_on"]), "expires_on must be YYYY-MM-DD"
    assert data["status"] in {"ACTIVE", "REVOKED"}


def assert_access_event(data: dict):
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["responder_id"])
    assert data["lookup_method"] in _LOOKUP_METHODS
    assert isinstance(data["disclosed_scope"], list)
    assert set(data["disclosed_scope"]) <= _DISCLOSED_SCOPE_SECTIONS
    assert isinstance(data["is_escalated"], bool)
    assert data["outcome"] in _ACCESS_OUTCOMES
    if data["outcome"] == "GRANTED":
        assert data.get("reason_code") is None, "GRANTED events leave reason_code null"


def assert_wandering_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["opened_via"] in {"SELF_REPORT", "HOTLINE_ESCALATION"}
    assert data["status"] in _CASE_STATUSES


def assert_reminder(data: dict):
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data["member_id"])
    assert data["reminder_kind"] in _REMINDER_KINDS
    assert _ISO_DATE_RE.match(data["due_on"]), "due_on must be YYYY-MM-DD"
    assert data["status"] in _REMINDER_STATUSES


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["record_item_id"])
    assert isinstance(data["claim_text"], str)
    assert data["status"] in _DISPUTE_STATUSES


def assert_audit_event(data: dict):
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str)
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["detail"], dict)


def assert_member_invariants(data: dict):
    """Member invariants that must hold after any operation."""
    assert data["balance_cents"] >= 0, "balance_cents must never go negative"
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents must never go negative"
    if data["membership_tier"] == "LIFETIME":
        assert data["expires_on"] is None, "LIFETIME members never expire"
    else:
        assert data["expires_on"] is not None, "non-LIFETIME members always carry expires_on"
