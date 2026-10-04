"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every primary resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_source_organization(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["org_type"] in ("HOSPITAL", "PHYSICIAN_GROUP", "DEBT_BUYER")
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_eligibility_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert data["fpl_multiplier"] > 0
    assert isinstance(data["insolvency_qualifies"], bool)
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_portfolio(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["source_org_id"], str)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["face_value_cents"], int)
    assert isinstance(data["asking_price_cents"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "SCREENING", "PRICED", "CONTRACTED",
        "SETTLED", "ABOLISHING", "CLOSED", "CANCELLED",
    )
    assert isinstance(data["eligible_face_value_cents"], int)
    assert isinstance(data["eligible_account_count"], int)
    assert data["quoted_price_cents"] is None or isinstance(
        data["quoted_price_cents"], int
    )
    assert data["purchased_price_cents"] is None or isinstance(
        data["purchased_price_cents"], int
    )
    assert isinstance(data["abolished_face_value_cents"], int)


def assert_debt_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["portfolio_id"], str)
    assert isinstance(data["external_ref"], str)
    assert isinstance(data["debtor_household_key"], str)
    assert isinstance(data["debtor_zip"], str)
    assert isinstance(data["debtor_state"], str)
    assert data["household_size"] is None or isinstance(data["household_size"], int)
    assert data["annual_income_cents"] is None or isinstance(
        data["annual_income_cents"], int
    )
    assert isinstance(data["is_insolvent"], bool)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["accrued_adjustment_cents"], int)
    assert isinstance(data["reported_to_bureau"], bool)
    assert data["bureau_name"] is None or data["bureau_name"] in (
        "EQUIFAX", "EXPERIAN", "TRANSUNION",
    )
    assert data["mailing_address"] is None or isinstance(data["mailing_address"], str)
    assert data["eligibility_status"] in (
        "UNSCREENED", "ELIGIBLE", "INELIGIBLE", "NEEDS_REVIEW",
    )
    assert data["lifecycle_status"] in (
        "AVAILABLE", "PURCHASED", "ABOLISHED", "EXCLUDED",
    )
    assert data["bureau_status"] in (
        "NOT_REPORTED", "REPORTED", "DELETION_REQUESTED", "DELETED", "DELETION_FAILED",
    )
    assert data["abolished_amount_cents"] is None or isinstance(
        data["abolished_amount_cents"], int
    )
    assert data["abolished_at"] is None or is_iso8601_timestamp(data["abolished_at"])
    assert data["abolished_batch_id"] is None or isinstance(
        data["abolished_batch_id"], str
    )


def assert_screening_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["portfolio_id"], str)
    assert isinstance(data["policy_id"], str)
    assert data["status"] in ("PENDING", "COMPLETED", "FAILED")
    assert isinstance(data["eligible_count"], int)
    assert isinstance(data["ineligible_count"], int)
    assert isinstance(data["needs_review_count"], int)
    assert data["executed_at"] is None or is_iso8601_timestamp(data["executed_at"])


def assert_purchase_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["portfolio_id"], str)
    assert isinstance(data["contract_price_cents"], int)
    assert isinstance(data["collection_prohibition"], bool)
    assert isinstance(data["no_resale"], bool)
    assert data["status"] in ("DRAFT", "EXECUTED", "SETTLED", "TERMINATED")
    assert data["executed_by"] is None or isinstance(data["executed_by"], str)
    assert data["settled_by"] is None or isinstance(data["settled_by"], str)
    assert data["terminated_reason"] is None or isinstance(
        data["terminated_reason"], str
    )


def assert_donor_campaign(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["earmark_type"] in ("GEOGRAPHY", "HOSPITAL", "GENERAL")
    assert data["earmark_state_code"] is None or isinstance(
        data["earmark_state_code"], str
    )
    assert data["earmark_source_org_id"] is None or isinstance(
        data["earmark_source_org_id"], str
    )
    assert isinstance(data["goal_cents"], int)
    assert isinstance(data["raised_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["spent_cents"], int)
    assert data["status"] in ("OPEN", "FUNDED", "CLOSED")


def assert_donation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["donor_name"], str)
    assert isinstance(data["donor_email"], str)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert data["status"] in ("PLEDGED", "RECEIVED", "REFUNDED")


def assert_abolishment_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["portfolio_id"], str)
    assert isinstance(data["account_ids"], list)
    assert isinstance(data["account_count"], int)
    assert isinstance(data["total_abolished_cents"], int)
    assert isinstance(data["funding_allocations"], list)
    assert data["status"] in ("STAGING", "COMMITTED", "FINALIZED", "REVERSED")
    assert data["reversed_reason"] is None or isinstance(data["reversed_reason"], str)


def assert_notification_letter(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["batch_id"], str)
    assert data["channel"] in ("MAIL", "EMAIL")
    assert data["mailing_address"] is None or isinstance(data["mailing_address"], str)
    assert data["status"] in (
        "QUEUED", "SENT", "DELIVERED", "BOUNCED", "UNDELIVERABLE", "CANCELLED",
    )
    assert isinstance(data["attempt_count"], int)
    assert data["sent_at"] is None or is_iso8601_timestamp(data["sent_at"])


def assert_credit_deletion_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert data["batch_id"] is None or isinstance(data["batch_id"], str)
    assert data["bureau"] in ("EQUIFAX", "EXPERIAN", "TRANSUNION")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "REJECTED", "ACKNOWLEDGED", "FAILED", "CANCELLED",
    )
    assert isinstance(data["resubmission_count"], int)
    assert data["rejection_reason"] is None or isinstance(data["rejection_reason"], str)


def assert_tax_relief_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["relief_amount_cents"], int)
    assert data["insolvency_exclusion_cents"] is None or isinstance(
        data["insolvency_exclusion_cents"], int
    )
    assert data["reportable_amount_cents"] is None or isinstance(
        data["reportable_amount_cents"], int
    )
    assert data["status"] in ("PENDING", "ASSESSED", "EXEMPT", "FILED", "CANCELLED")


def assert_hospital_partnership(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["source_org_id"], str)
    assert isinstance(data["fap_baseline_score"], int)
    assert isinstance(data["fap_target_score"], int)
    assert isinstance(data["fap_current_score"], int)
    assert data["status"] in ("PROPOSED", "ACTIVE", "SUSPENDED", "COMPLETED")


def assert_partnership_milestone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["partnership_id"], str)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["description"], str)
    assert isinstance(data["weight"], int) and data["weight"] > 0
    assert isinstance(data["due_date"], str)
    assert data["status"] in ("PENDING", "MET", "MISSED", "WAIVED")


def assert_impact_report(data: dict):
    _assert_common_fields(data)
    assert data["scope"] in ("GLOBAL", "GEOGRAPHY", "HOSPITAL")
    assert data["scope_state_code"] is None or isinstance(data["scope_state_code"], str)
    assert data["scope_source_org_id"] is None or isinstance(
        data["scope_source_org_id"], str
    )
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["counting_variant"] in ("PER_ACCOUNT", "DEDUPED_HOUSEHOLD")
    assert isinstance(data["households_relieved"], int)
    assert isinstance(data["dollars_abolished_cents"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED")
