"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant


def _assert_common_fields(data: dict, entity_label: str, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"{entity_label}.updated_at must be ISO 8601"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"{entity_label}.version must be an integer starting at 1"
        )
    else:
        assert "updated_at" not in data, f"{entity_label} must not expose updated_at"
        assert "version" not in data, f"{entity_label} must not expose version"


def assert_institution(data: dict):
    _assert_common_fields(data, "Institution")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("supported_methods"), list) and data["supported_methods"]
    for method in data["supported_methods"]:
        assert method in ("CREDENTIALS", "OAUTH_TOKEN", "BANK_API")
    assert data.get("target_method") in ("BANK_API", "OAUTH_TOKEN")
    assert data["target_method"] in data["supported_methods"]
    assert is_iso8601_timestamp(data.get("migration_window_start", ""))
    assert is_iso8601_timestamp(data.get("migration_window_end", ""))
    assert data.get("migration_state") in ("NOT_STARTED", "IN_PROGRESS", "COMPLETE")
    assert data.get("status") in ("ACTIVE", "DEGRADED", "BROKEN")
    assert data.get("connectivity_mode") in ("LEGACY_MODE", "HYBRID", "API_ONLY")


def assert_agreement(data: dict):
    _assert_common_fields(data, "InstitutionAgreement")
    assert is_valid_uuid(data.get("institution_id", ""))
    assert isinstance(data.get("rate_limit_per_hour"), int) and data["rate_limit_per_hour"] >= 1
    assert isinstance(data.get("permitted_fields_by_scope"), dict) and data["permitted_fields_by_scope"]
    assert isinstance(data.get("active"), bool)


def assert_recipient(data: dict):
    _assert_common_fields(data, "Recipient")
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("status") in ("PENDING_REVIEW", "APPROVED", "SUSPENDED", "REJECTED")
    assert isinstance(data.get("declared_use_case"), str)
    assert data.get("minimization_policy") in ("STRICT", "STANDARD", "BROAD")


def assert_consent(data: dict):
    _assert_common_fields(data, "ConsentRecord")
    assert is_valid_uuid(data.get("recipient_id", ""))
    assert isinstance(data.get("consumer_ref"), str) and data["consumer_ref"]
    assert isinstance(data.get("data_scopes"), list) and data["data_scopes"]
    for scope in data["data_scopes"]:
        assert scope in ("BALANCE", "TRANSACTIONS", "IDENTITY", "INCOME", "ASSETS")
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data.get("status") in ("ACTIVE", "REVOKED", "EXPIRED", "SUPERSEDED")


def assert_connection(data: dict):
    _assert_common_fields(data, "Connection")
    assert is_valid_uuid(data.get("institution_id", ""))
    assert is_valid_uuid(data.get("consent_id", ""))
    assert isinstance(data.get("consumer_ref"), str) and data["consumer_ref"]
    assert data.get("method") in ("CREDENTIALS", "OAUTH_TOKEN", "BANK_API")
    assert data.get("status") in (
        "PENDING_AUTH", "ACTIVE", "REAUTH_REQUIRED", "BROKEN", "MIGRATING", "DISCONNECTED",
    )
    assert isinstance(data.get("reauth_cooldown_seconds"), int)
    assert isinstance(data.get("consecutive_failures"), int)


def assert_tier(data: dict):
    _assert_common_fields(data, "DataProductTier")
    assert isinstance(data.get("tier_name"), str) and data["tier_name"]
    assert isinstance(data.get("scopes_included"), list) and data["scopes_included"]
    assert data.get("rate_class") in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data.get("active"), bool)


def assert_tier_assignment(data: dict):
    _assert_common_fields(data, "RecipientTierAssignment")
    assert is_valid_uuid(data.get("recipient_id", ""))
    assert is_valid_uuid(data.get("tier_id", ""))
    assert data.get("status") in ("ACTIVE", "ENDED")


def assert_refresh_job(data: dict):
    _assert_common_fields(data, "RefreshJob")
    assert is_valid_uuid(data.get("connection_id", ""))
    assert data.get("kind") in ("FULL", "INCREMENTAL")
    assert data.get("status") in ("QUEUED", "SUCCEEDED", "FAILED")
    assert isinstance(data.get("attempt_count"), int)
    assert is_iso8601_timestamp(data.get("requested_at", ""))


def assert_deletion_request(data: dict):
    _assert_common_fields(data, "DataDeletionRequest")
    assert is_valid_uuid(data.get("consent_id", ""))
    assert data.get("status") in ("PENDING", "PROPAGATING", "ACKED_BY_ALL", "COMPLETED")
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    assert isinstance(data.get("acked_recipient_ids"), list)


def assert_scope_grant(data: dict):
    """Append-only grant row: only id and created_at among system fields."""
    _assert_common_fields(data, "DataScopeGrant", with_version=False)
    assert is_valid_uuid(data.get("consent_id", ""))
    assert data.get("scope") in ("BALANCE", "TRANSACTIONS", "IDENTITY", "INCOME", "ASSETS")


def assert_webhook_event(data: dict):
    """Append-only webhook row: only id and created_at among system fields."""
    _assert_common_fields(data, "WebhookEvent", with_version=False)
    assert is_valid_uuid(data.get("connection_id", ""))
    assert is_valid_uuid(data.get("recipient_id", ""))
    assert data.get("event_type") in (
        "TRANSACTIONS_AVAILABLE", "REAUTH_REQUIRED", "CONSENT_REVOKED",
        "CONSENT_EXPIRED", "DATA_DELETED", "CONNECTION_MIGRATED", "INSTITUTION_BROKEN",
    )
    assert isinstance(data.get("payload"), dict)
    assert isinstance(data.get("delivery_attempts"), int)


def assert_breakage_event(data: dict):
    """Append-only breakage row: only id and created_at among system fields."""
    _assert_common_fields(data, "BreakageEvent", with_version=False)
    assert is_valid_uuid(data.get("institution_id", ""))
    assert is_valid_uuid(data.get("connection_id", ""))
    assert data.get("kind") in ("TRANSIENT", "INSTITUTION_DOWN", "CREDENTIALS_INVALID", "RATE_LIMITED")
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


def assert_instants_equal(actual: str, expected: str, label: str = "instant"):
    """Compare two ISO 8601 instants on their canonical millisecond form."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {canonical_instant(expected)}, got {canonical_instant(actual)}"
    )


def assert_connectivity_mode_tracks_migration(institution: dict):
    """Derived-field invariant: connectivity_mode mirrors migration_state."""
    expected = {
        "NOT_STARTED": "LEGACY_MODE",
        "IN_PROGRESS": "HYBRID",
        "COMPLETE": "API_ONLY",
    }[institution["migration_state"]]
    assert institution["connectivity_mode"] == expected, (
        f"connectivity_mode must be {expected} while migration_state is "
        f"{institution['migration_state']}, got {institution['connectivity_mode']}"
    )


def assert_single_active_agreement(agreements: list):
    """At most one agreement per institution may be active at a time."""
    actives = [a for a in agreements if a.get("active") is True]
    assert len(actives) <= 1, f"expected at most one ACTIVE agreement, found {len(actives)}"
