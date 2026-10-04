"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ORG_LEGAL_NAME": "Test Studio",
    "ORG_EMAIL": "studio@example.com",
    "PROJECT_TITLE": "Test Game",
    "EDITOR_VERSION_STRING": "2022.3.1f1",
    "EDITOR_MAJOR_LINE": "2022.3",
    "EDITOR_RELEASED_ON": "2025-09-01",
    "PERIOD_MONTH": "2026-01",
    "SUB_COVERAGE_START": "2026-09-01",
    "SUB_COVERAGE_END": "2027-09-01",
    "LISTING_TITLE": "Test Asset",
    "LISTING_PRICE_CENTS": 100_000,
    "PLATFORM_CODE": "CONSOLE_A",
    "TERM_START": "2026-01-01",
    "TERM_END": "2026-12-31",
    "TARGET_ENGINE": "OtherEngine",
    "BUILD_LABEL": "build-1",
}


def create_tier_payload(**overrides) -> dict:
    defaults = {
        "tier_code": "PRO",
        "revenue_ceiling_cents": 100_000_000,
        "funding_ceiling_cents": 100_000_000,
        "seat_minimum": 2,
        "seat_overage_cents": 25_000,
        "runtime_fee_exempt": False,
        "export_module_allowed": True,
        "marketplace_sell_allowed": True,
    }
    defaults.update(overrides)
    return defaults


def create_org_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["ORG_LEGAL_NAME"],
        "contact_email": DEFAULTS["ORG_EMAIL"],
        "declared_tier_code": "PRO",
    }
    defaults.update(overrides)
    return defaults


def create_revenue_declaration_payload(**overrides) -> dict:
    defaults = {
        "period_month": DEFAULTS["PERIOD_MONTH"],
        "gross_revenue_cents": 160_000_000,
        "funding_received_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_seat_subscription_payload(expected_org_version, **overrides) -> dict:
    defaults = {
        "tier_code": "PRO",
        "purchased_seats": 2,
        "coverage_start": DEFAULTS["SUB_COVERAGE_START"],
        "coverage_end": DEFAULTS["SUB_COVERAGE_END"],
        "expected_org_version": expected_org_version,
    }
    defaults.update(overrides)
    return defaults


def create_editor_version_payload(**overrides) -> dict:
    defaults = {
        "version_string": DEFAULTS["EDITOR_VERSION_STRING"],
        "major_line": DEFAULTS["EDITOR_MAJOR_LINE"],
        "released_on": DEFAULTS["EDITOR_RELEASED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(editor_version_id, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PROJECT_TITLE"],
        "editor_version_id": editor_version_id,
    }
    defaults.update(overrides)
    return defaults


def create_install_report_payload(expected_project_version, **overrides) -> dict:
    defaults = {
        "period_month": DEFAULTS["PERIOD_MONTH"],
        "new_device_installs": 1_000_000,
        "reinstalls": 0,
        "bundle_installs": 0,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def revise_install_report_payload(**overrides) -> dict:
    defaults = {
        "new_device_installs": 0,
        "reinstalls": 0,
        "bundle_installs": 0,
    }
    defaults.update(overrides)
    return defaults


def create_policy_change_payload(**overrides) -> dict:
    defaults = {
        "change_code": "RUNTIME-FEE-2026",
        "announcement_date": "2026-02-01",
        "effective_date": "2026-01-01",
        "retroactive_flag": True,
        "adverse_flag": True,
        "grandfather_window_days": 45,
        "new_per_install_cents": 30,
    }
    defaults.update(overrides)
    return defaults


def create_asset_listing_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["LISTING_TITLE"],
        "price_cents": DEFAULTS["LISTING_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_export_agreement_payload(**overrides) -> dict:
    defaults = {
        "platform_code": DEFAULTS["PLATFORM_CODE"],
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_export_build_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "platform_code": DEFAULTS["PLATFORM_CODE"],
        "build_label": DEFAULTS["BUILD_LABEL"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_case_payload(**overrides) -> dict:
    defaults = {"trigger_reason": "MANUAL"}
    defaults.update(overrides)
    return defaults


def create_migration_assessment_payload(**overrides) -> dict:
    defaults = {"target_engine": DEFAULTS["TARGET_ENGINE"]}
    defaults.update(overrides)
    return defaults
