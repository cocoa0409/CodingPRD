"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_full(data: dict, entity: str):
    """Full common-field set (PRD §2.4): id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_common_lean(data: dict, entity: str):
    """Lean common-field set (PRD §2.4): id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "version" not in data, f"{entity} must not expose version"
    assert "updated_at" not in data, f"{entity} must not expose updated_at"


def assert_tier_config(data: dict):
    _assert_common_full(data, "TierConfig")
    assert data["tier_code"] in ("PERSONAL", "EDUCATION", "PRO", "ENTERPRISE")
    assert isinstance(data["revenue_ceiling_cents"], int)
    assert isinstance(data["funding_ceiling_cents"], int)
    assert isinstance(data["seat_minimum"], int)
    assert isinstance(data["seat_overage_cents"], int)
    assert isinstance(data["runtime_fee_exempt"], bool)
    assert isinstance(data["export_module_allowed"], bool)
    assert isinstance(data["marketplace_sell_allowed"], bool)
    assert data["tier_config_status"] in ("ACTIVE", "SUPERSEDED")


def assert_developer_org(data: dict):
    _assert_common_full(data, "DeveloperOrg")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["declared_tier_code"] in ("PERSONAL", "EDUCATION", "PRO", "ENTERPRISE")
    assert data["effective_tier_code"] in ("PERSONAL", "EDUCATION", "PRO", "ENTERPRISE")
    assert data["org_standing"] in ("GOOD", "REVIEW", "SUSPENDED")
    assert isinstance(data["trust_score"], int)
    assert data["migration_status"] in ("NONE", "ASSESSING", "COOLING_OFF", "MIGRATED")
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["marketplace_credit_cents"], int)


def assert_revenue_declaration(data: dict):
    _assert_common_lean(data, "RevenueDeclaration")
    assert isinstance(data["period_month"], str)
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["funding_received_cents"], int)


def assert_seat_subscription(data: dict):
    _assert_common_full(data, "SeatSubscription")
    assert data["tier_code"] in ("PRO", "ENTERPRISE")
    assert isinstance(data["purchased_seats"], int)
    assert isinstance(data["active_seats"], int)
    assert isinstance(data["available_seats"], int)
    assert data["subscription_status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED")


def assert_seat_pool_invariant(data: dict):
    """PRD §3.2: active_seats + available_seats == purchased_seats at all times."""
    assert data["active_seats"] + data["available_seats"] == data["purchased_seats"], (
        f"seat pool invariant broken: {data['active_seats']} + {data['available_seats']} "
        f"!= {data['purchased_seats']}"
    )


def assert_editor_version(data: dict):
    _assert_common_full(data, "EditorVersion")
    assert isinstance(data["version_string"], str) and data["version_string"]
    assert isinstance(data["major_line"], str) and data["major_line"]
    assert data["support_status"] in ("SUPPORTED", "LTS", "DEPRECATED", "SUNSET")


def assert_game_project(data: dict):
    _assert_common_full(data, "GameProject")
    assert isinstance(data["title"], str) and data["title"]
    assert data["project_status"] in ("DEVELOPMENT", "SHIPPED", "FROZEN", "ARCHIVED")
    assert isinstance(data["lifetime_installs"], int)
    assert isinstance(data["upgrade_risk_score"], int)
    assert 0 <= data["upgrade_risk_score"] <= 100


def assert_install_report(data: dict):
    _assert_common_full(data, "InstallReport")
    assert isinstance(data["period_month"], str)
    assert isinstance(data["new_device_installs"], int)
    assert isinstance(data["reinstalls"], int)
    assert isinstance(data["bundle_installs"], int)
    assert isinstance(data["billable_installs"], int)
    assert data["report_status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "DISPUTED", "ARCHIVED"
    )
    # PRD §3.4: billable_installs are exactly the new_device_installs.
    assert data["billable_installs"] == data["new_device_installs"]


def assert_invoice(data: dict):
    _assert_common_full(data, "RuntimeFeeInvoice")
    assert data["assessment_status"] in ("PROVISIONAL", "FINALIZED", "DISPUTED", "ADJUSTED", "VOIDED")
    assert data["payment_status"] in ("UNPAID", "PAID", "WAIVED", "OVERDUE")
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["final_amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["waived_cents"], int)


def assert_policy_change(data: dict):
    _assert_common_full(data, "PolicyChange")
    assert isinstance(data["change_code"], str) and data["change_code"]
    assert isinstance(data["retroactive_flag"], bool)
    assert isinstance(data["adverse_flag"], bool)
    assert data["change_status"] in ("DRAFT", "ACTIVE", "RESCINDED")


def assert_grandfather_commitment(data: dict):
    _assert_common_full(data, "GrandfatherCommitment")
    assert data["locked_schedule_label"] == "BASE"
    assert data["commitment_status"] in ("ACTIVE", "VOIDED")


def assert_asset_listing(data: dict):
    _assert_common_full(data, "AssetListing")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["price_cents"], int)
    assert data["listing_status"] in ("DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED", "DELISTED")
    assert isinstance(data["review_rounds"], int)


def assert_asset_purchase(data: dict):
    _assert_common_lean(data, "AssetPurchase")
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["platform_share_cents"], int)
    assert isinstance(data["creator_share_cents"], int)
    assert data["purchase_status"] in ("COMPLETED", "REFUNDED")


def assert_export_agreement(data: dict):
    _assert_common_full(data, "ExportAgreement")
    assert data["platform_code"] in ("CONSOLE_A", "CONSOLE_B", "CONSOLE_C")
    assert data["agreement_status"] in ("PENDING", "ACTIVE", "REVOKED", "EXPIRED")


def assert_export_build(data: dict):
    _assert_common_lean(data, "ExportBuild")
    assert data["platform_code"] in ("CONSOLE_A", "CONSOLE_B", "CONSOLE_C")


def assert_audit_case(data: dict):
    _assert_common_full(data, "AuditCase")
    assert data["trigger_reason"] in ("REVENUE_CEILING_BREACH", "EDUCATION_ELIGIBILITY", "MANUAL")
    assert data["case_status"] in ("OPENED", "EVIDENCE_REQUESTED", "CLEARED", "CONVERTED", "APPEALED")
    assert isinstance(data["appeal_count"], int)


def assert_migration_assessment(data: dict):
    _assert_common_full(data, "MigrationAssessment")
    assert data["assessment_status"] in (
        "REQUESTED", "EXPORT_READY", "COOLING_OFF", "COMPLETED", "ABANDONED"
    )
