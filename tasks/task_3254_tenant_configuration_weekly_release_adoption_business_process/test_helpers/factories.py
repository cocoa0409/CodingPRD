"""Payload factories — one per entity, input fields only."""

from .constants import CLOCK_START, TEST_DEFAULTS


def create_tenant_payload(**overrides) -> dict:
    defaults = {
        "tenant_name": "T-1",
        "tenant_kind": "PRODUCTION",
        "maintenance_slot_utc": TEST_DEFAULTS["MAINTENANCE_SLOT_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_org_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_name": "U1",
        "unit_type": "TEAM",
        # Anchored at the logical clock's startup instant so the unit becomes
        # ACTIVE on the first clock advance.
        "effective_date": CLOCK_START,
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> dict:
    defaults = {
        "worker_ref": "W1",
        "full_name": "Worker One",
        "hire_date": CLOCK_START,
    }
    defaults.update(overrides)
    return defaults


def create_security_group_payload(**overrides) -> dict:
    defaults = {
        "group_name": "G1",
        "assignment_mode": "USER_BASED",
        "min_approvers": TEST_DEFAULTS["MIN_APPROVERS"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_definition_payload(**overrides) -> dict:
    defaults = {
        "transaction_type": "HIRE",
        "definition_name": "Flow",
    }
    defaults.update(overrides)
    return defaults


def create_step_payload(**overrides) -> dict:
    defaults = {
        "step_order": 1,
        "step_kind": "APPROVAL",
        "inclusion_condition": "ALWAYS",
    }
    defaults.update(overrides)
    return defaults


def initiate_transaction_payload(**overrides) -> dict:
    defaults = {
        "transaction_type": "HIRE",
        "amount": 0,
    }
    defaults.update(overrides)
    return defaults


def create_release_train_payload(**overrides) -> dict:
    defaults = {
        "release_label": "F2026-R1",
        "release_kind": "FEATURE_RELEASE",
        "opt_in_window_start": "2026-09-01T00:00:00Z",
        "opt_in_window_end": "2026-09-10T00:00:00Z",
        "mandatory_date": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_feature_adoption_payload(**overrides) -> dict:
    defaults = {
        "feature_key": "F1",
    }
    defaults.update(overrides)
    return defaults


def create_connector_payload(**overrides) -> dict:
    defaults = {
        "connector_name": "C1",
        "trigger_mode": "SCHEDULED",
        "schedule_cron": "0 * * * *",
        "blackout_window_start_utc": TEST_DEFAULTS["BLACKOUT_START"],
        "blackout_window_end_utc": TEST_DEFAULTS["BLACKOUT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_run_payload(**overrides) -> dict:
    defaults = {"trigger_source": "MANUAL"}
    defaults.update(overrides)
    return defaults


def create_refresh_job_payload(**overrides) -> dict:
    defaults = {
        "scheduled_at": "2026-09-05T02:00:00Z",
        "migration_mode": "FULL_COPY",
    }
    defaults.update(overrides)
    return defaults
