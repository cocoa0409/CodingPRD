"""Payload factories — one per entity, input fields only."""
from .constants import ALL_SERVICE_KINDS, TEST_DEFAULTS


def create_org_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["ORG_NAME"],
        "org_kind": "COMMERCIAL",
        "home_region": TEST_DEFAULTS["ORG_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_credit_pool_payload(organization_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "capacity_credits": TEST_DEFAULTS["POOL_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_license_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": TEST_DEFAULTS["PRODUCT_CODE_NAMED"],
        "license_kind": "NAMED_USER",
        "edition": "ADVANCED",
        "major_version": TEST_DEFAULTS["PRODUCT_MAJOR_VERSION"],
        "base_seat_count": 50,
        "supports_offline": True,
        "allows_derivative_works": True,
    }
    defaults.update(overrides)
    return defaults


def create_license_grant_payload(organization_id, license_product_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "license_product_id": license_product_id,
        "grant_kind": "STANDARD",
        "seats_allocated": TEST_DEFAULTS["GRANT_SEATS"],
        "valid_from_period": TEST_DEFAULTS["GRANT_VALID_FROM"],
        "valid_to_period": TEST_DEFAULTS["GRANT_VALID_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_extension_grant_payload(license_grant_id, extension_code, **overrides) -> dict:
    defaults = {
        "license_grant_id": license_grant_id,
        "extension_code": extension_code,
        "seats_allocated": 5,
    }
    defaults.update(overrides)
    return defaults


def create_named_user_payload(organization_id, home_license_grant_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "username": TEST_DEFAULTS["USERNAME"],
        "email": TEST_DEFAULTS["EMAIL"],
        "named_user_level": TEST_DEFAULTS["USER_LEVEL"],
        "home_license_grant_id": home_license_grant_id,
    }
    defaults.update(overrides)
    return defaults


def create_deployment_server_payload(organization_id, license_grant_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "hostname": "gis1.meridian.example",
        "role": "GIS_SERVER",
        "installed_major_version": TEST_DEFAULTS["PRODUCT_MAJOR_VERSION"],
        "auth_mode": "SAML",
        "license_grant_id": license_grant_id,
        "cores_allocated": 4,
    }
    defaults.update(overrides)
    return defaults


def create_version_compatibility_rule_payload(**overrides) -> dict:
    defaults = {
        "consumer_role": "GIS_SERVER",
        "consumer_major_version": 12,
        "dependency_role": "PORTAL",
        "allowed_dependency_major_versions": [12],
        "strict": True,
    }
    defaults.update(overrides)
    return defaults


def create_content_item_payload(organization_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "title": "Trailheads",
        "item_kind": "FEATURE_LAYER",
        "storage_bytes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_api_key_payload(named_user_id, organization_id, **overrides) -> dict:
    defaults = {
        "named_user_id": named_user_id,
        "organization_id": organization_id,
        "label": "dev-key",
        "allowed_service_kinds": list(ALL_SERVICE_KINDS),
        "per_key_credit_cap": 0,
    }
    defaults.update(overrides)
    return defaults


def create_credit_batch_payload(organization_id, api_key_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "api_key_id": api_key_id,
        "service_kind": "GEOCODE",
        "requested_units": 100,
        "idempotency_key": "idem-default",
    }
    defaults.update(overrides)
    return defaults


def create_ev_payload(organization_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "program_kind": "EDUCATION_PROGRAM",
        "evidence_document_ref": "doc-v1",
    }
    defaults.update(overrides)
    return defaults
