"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED"}
FILING_STATUSES = {
    "SINGLE",
    "MARRIED_FILING_JOINTLY",
    "MARRIED_FILING_SEPARATELY",
    "HEAD_OF_HOUSEHOLD",
    "QUALIFYING_WIDOWER",
}
TIER_CODES = {"FREE", "DELUXE", "PREMIER", "SELF_EMPLOYED"}
SNAPSHOT_STATUSES = {"AVAILABLE", "IMPORTED", "SUPERSEDED"}
RETURN_STATUSES = {
    "DRAFT",
    "READY_FOR_REVIEW",
    "SUBMITTED",
    "ACCEPTED",
    "REJECTED",
    "AMENDED",
}
RETURN_FORM_STATUSES = {"ACTIVE", "REMOVED"}
RETURN_FORM_SOURCES = {"MANUAL", "IMPORTED"}
CARRYFORWARD_ITEM_TYPES = {"DEPRECIATION", "CAPITAL_LOSS", "BASIS", "NONE"}
PROMPT_STATUSES = {"PENDING", "ACKNOWLEDGED", "DECLINED_DOWNGRADED", "SUPERSEDED"}
STATE_RETURN_STATUSES = {"DRAFT", "READY", "FILED", "REMOVED"}
FILING_ATTEMPT_OUTCOMES = {"PENDING", "ACCEPTED", "REJECTED"}
REJECTION_CODES = {
    "R0000_SSN_MISMATCH",
    "R0500_NAME_CONTROL",
    "R1000_DUPLICATE_FILED",
    "R2000_DEPENDENT_CLAIMED",
    "R3000_MATH_ERROR",
}
REFUND_TRANSFER_STATUSES = {"PENDING_DISCLOSURE", "ACTIVE", "SETTLED", "VOIDED"}
CLAIM_STATUSES = {
    "FILED",
    "UNDER_REVIEW",
    "APPROVED",
    "PARTIALLY_APPROVED",
    "DENIED",
    "PAID",
}


def _assert_mutable_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_taxpayer_account(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("filing_status") in FILING_STATUSES
    assert isinstance(data.get("agi_cents"), int) and data["agi_cents"] >= 0
    assert isinstance(data.get("resident_state_code"), str) and len(data["resident_state_code"]) == 2
    assert isinstance(data.get("accuracy_guarantee_enrolled"), bool)
    assert data.get("disclosure_accepted_version") is None or isinstance(
        data["disclosure_accepted_version"], str
    )
    assert data.get("status") in ACCOUNT_STATUSES


def assert_product_tier(data: dict):
    # Catalog row: id + created_at only; no updated_at / version (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("code") in TIER_CODES
    assert isinstance(data.get("price_cents"), int) and data["price_cents"] >= 0
    assert isinstance(data.get("state_addon_price_cents"), int)
    assert data["state_addon_price_cents"] >= 0
    assert isinstance(data.get("supported_forms"), list)
    assert isinstance(data.get("tier_rank"), int)


def assert_form_spec(data: dict):
    # Catalog row: id + created_at only; no updated_at / version (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("minimum_tier") in TIER_CODES
    assert isinstance(data.get("disqualifies_free_file"), bool)
    assert isinstance(data.get("counts_toward_refund"), bool)


def assert_prior_year_snapshot(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("tax_year"), int)
    assert isinstance(data.get("carryforward_items"), list)
    assert data.get("import_status") in SNAPSHOT_STATUSES


def assert_tax_return(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("tax_year"), int)
    assert data.get("current_tier") in TIER_CODES
    assert data.get("minimum_required_tier") in TIER_CODES
    assert isinstance(data.get("free_file_eligible"), bool)
    assert isinstance(data.get("upgrade_prompt_pending"), bool)
    assert isinstance(data.get("refund_transfer_selected"), bool)
    assert isinstance(data.get("federal_refund_cents"), int)
    assert isinstance(data.get("total_fees_due_cents"), int)
    assert data.get("status") in RETURN_STATUSES


def assert_return_form(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data.get("return_id"), str)
    assert isinstance(data.get("form_code"), str) and data["form_code"]
    assert data.get("source") in RETURN_FORM_SOURCES
    assert data.get("carryforward_item_type") in CARRYFORWARD_ITEM_TYPES
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("status") in RETURN_FORM_STATUSES


def assert_upgrade_prompt(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data.get("return_id"), str)
    assert data.get("from_tier") in TIER_CODES
    assert data.get("to_tier") in TIER_CODES
    assert isinstance(data.get("price_delta_cents"), int)
    assert isinstance(data.get("acknowledged"), bool)
    assert data.get("status") in PROMPT_STATUSES


def assert_state_return(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data.get("return_id"), str)
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2
    assert isinstance(data.get("is_resident_state"), bool)
    assert isinstance(data.get("allocated_tax_cents"), int)
    assert data.get("status") in STATE_RETURN_STATUSES


def assert_filing_attempt(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data.get("return_id"), str)
    assert isinstance(data.get("attempt_sequence"), int) and data["attempt_sequence"] >= 1
    assert isinstance(data.get("transmission_payload_hash"), str)
    assert data.get("outcome") in FILING_ATTEMPT_OUTCOMES
    if data.get("rejection_code") is not None:
        assert data["rejection_code"] in REJECTION_CODES
    if data.get("correction_hint") is not None:
        assert isinstance(data["correction_hint"], str)


def assert_refund_transfer_agreement(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data.get("return_id"), str)
    assert isinstance(data.get("bank_partner_code"), str)
    assert isinstance(data.get("service_fee_cents"), int)
    assert isinstance(data.get("disclosure_version"), str)
    assert data.get("status") in REFUND_TRANSFER_STATUSES


def assert_accuracy_claim(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data.get("return_id"), str)
    assert isinstance(data.get("claimed_error_amount_cents"), int)
    assert data["claimed_error_amount_cents"] > 0
    if data.get("reviewed_error_amount_cents") is not None:
        assert isinstance(data["reviewed_error_amount_cents"], int)
        assert data["reviewed_error_amount_cents"] >= 0
    assert isinstance(data.get("reimbursement_cents"), int)
    assert data["reimbursement_cents"] >= 0
    assert data.get("status") in CLAIM_STATUSES
