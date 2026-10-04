"""Composite setup helpers for the Battery Storage Guarantees API.

Every helper drives the public API only. Setup calls use ``get_success_data``
(lenient 2xx validator) so setup failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

The default logical clock reading is 2026-09-01T00:00:00Z (PRD §2.4); all
date literals in these fixtures are chosen relative to that reading.

Fixture tiers:
  Tier 1 - state progression: create_project, create_and_execute_esa
  Tier 2 - hierarchy: setup_executed_project (project + 3 approved permits + executed ESA)
  Tier 3 - lifecycle shortcuts: commission_project, create_claim_under_review, ...
  Tier 4 - accumulation / threshold targeting: setup_active_ltsa (pool computed), ...
  Tier 5 - terminal states: setup_completed_esa, setup_expired_ltsa
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_augmentation_payload,
    create_bid_session_payload,
    create_esa_payload,
    create_milestone_payload,
    create_performance_test_payload,
    create_permit_payload,
    create_project_payload,
    create_service_agreement_payload,
    create_spare_part_order_payload,
    create_warranty_claim_payload,
)
from .test_users import TEST_USERS

DEV = TEST_USERS["project_developer_headers"]
PERF = TEST_USERS["performance_engineer_headers"]
SVC_MGR = TEST_USERS["service_manager_headers"]
SVC_ENG = TEST_USERS["service_engineer_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]
SAFETY = TEST_USERS["safety_authority_headers"]
MARKET = TEST_USERS["market_operator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

PERMIT_TYPES = ("THERMAL_RUNAWAY_PLAN", "FIRE_CODE", "LOCAL_APPROVAL")


# ─── Tier 1: state progression ────────────────────────────────────────────


def create_project(api=api_client, **overrides):
    """Create a project. Returns the project data dict."""
    data = get_success_data(api.create_project(create_project_payload(**overrides), DEV))
    return data


def create_esa(project_id, api=api_client, **overrides):
    """Create a DRAFT ESA on a project. Returns the ESA data dict."""
    return get_success_data(api.create_esa(create_esa_payload(project_id, **overrides), DEV))


def submit_permit(project_id, permit_type, api=api_client, **overrides):
    """Submit a safety permit. Returns the permit data dict."""
    return get_success_data(
        api.create_permit(
            create_permit_payload(project_id, permit_type=permit_type, **overrides), DEV
        )
    )


def decide_permit(permit_id, decision, api=api_client):
    return get_success_data(api.decide_permit(permit_id, {"decision": decision}, SAFETY))


def approve_all_permits(project_id, api=api_client):
    """Submit and approve all three permit types. Returns {type: permit}."""
    permits = {}
    for ptype in PERMIT_TYPES:
        permit = submit_permit(project_id, ptype, api=api)
        permits[ptype] = decide_permit(permit["id"], "APPROVED", api=api)
    return permits


def current_project_version(project_id, api=api_client):
    return get_success_data(api.get_project(project_id, DEV))["version"]


def execute_esa(esa_id, project_id, api=api_client):
    """Execute an ESA using the project's current version. Returns the ESA."""
    version = current_project_version(project_id, api=api)
    return get_success_data(
        api.execute_esa(esa_id, {"expected_project_version": version}, DEV)
    )


def create_milestone(esa_id, kind, planned_date, api=api_client):
    return get_success_data(
        api.create_milestone(
            create_milestone_payload(esa_id, kind=kind, planned_date=planned_date), DEV
        )
    )


def record_milestone_outcome(milestone_id, outcome, actual_date, api=api_client):
    return get_success_data(
        api.record_milestone_outcome(
            milestone_id, {"outcome": outcome, "actual_date": actual_date}, DEV
        )
    )


def set_clock(to_iso8601, api=api_client):
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# ─── Tier 2: hierarchy ────────────────────────────────────────────────────


def setup_executed_project(api=api_client, project_overrides=None, esa_overrides=None):
    """Project + all three permits APPROVED + ESA EXECUTED.

    Returns (project, esa). The project dict is re-read after execution so
    its version reflects the execution bump.
    """
    project = create_project(api=api, **(project_overrides or {}))
    esa = create_esa(project["id"], api=api, **(esa_overrides or {}))
    approve_all_permits(project["id"], api=api)
    esa = execute_esa(esa["id"], project["id"], api=api)
    project = get_success_data(api.get_project(project["id"], DEV))
    return project, esa


# ─── Tier 3: lifecycle shortcuts ──────────────────────────────────────────


def commission_project(project, esa, api=api_client,
                       planned_date="2026-09-02T00:00:00Z",
                       actual_date="2026-09-01T00:00:00Z"):
    """Achieve a COMMISSIONING milestone, setting commissioned_capacity_mwh.

    Returns (project, esa, milestone). Project is re-read afterwards.
    """
    milestone = create_milestone(esa["id"], "COMMISSIONING", planned_date, api=api)
    milestone = record_milestone_outcome(milestone["id"], "ACHIEVED", actual_date, api=api)
    project = get_success_data(api.get_project(project["id"], DEV))
    return project, esa, milestone


def setup_commissioned_project(api=api_client, project_overrides=None, esa_overrides=None):
    """Executed ESA + commissioning achieved. Returns (project, esa)."""
    project, esa = setup_executed_project(
        api=api, project_overrides=project_overrides, esa_overrides=esa_overrides
    )
    project, esa, _ = commission_project(project, esa, api=api)
    return project, esa


def schedule_performance_test(project_id, test_type, window_start, window_end, api=api_client):
    return get_success_data(
        api.create_performance_test(
            create_performance_test_payload(
                project_id,
                test_type=test_type,
                window_start=window_start,
                window_end=window_end,
            ),
            PERF,
        )
    )


def create_claim(esa_id, api=api_client, **overrides):
    return get_success_data(
        api.create_warranty_claim(create_warranty_claim_payload(esa_id, **overrides), WARRANTY)
    )


def create_claim_under_review(esa_id, api=api_client, **overrides):
    claim = create_claim(esa_id, api=api, **overrides)
    return get_success_data(api.start_claim_review(claim["id"], WARRANTY))


def create_manual_augmentation(project_id, api=api_client, **overrides):
    return get_success_data(
        api.create_augmentation(create_augmentation_payload(project_id, **overrides), SVC_ENG)
    )


def execute_augmentation(augmentation_id, project_id, api=api_client):
    version = current_project_version(project_id, api=api)
    return get_success_data(
        api.execute_augmentation(
            augmentation_id, {"expected_project_version": version}, SVC_ENG
        )
    )


def create_bid_session(project_id, api=api_client, **overrides):
    return get_success_data(
        api.create_bid_session(create_bid_session_payload(project_id, **overrides), MARKET)
    )


# ─── Tier 4: accumulation / threshold targeting ──────────────────────────


def setup_active_ltsa(project_id, api=api_client, **overrides):
    """LTSA created in DRAFT then activated. Returns the ACTIVE agreement.

    Default term 2026-08-01 .. 2027-08-01 spans the default clock reading.
    """
    ltsa = get_success_data(
        api.create_service_agreement(
            create_service_agreement_payload(project_id, **overrides), SVC_MGR
        )
    )
    ltsa = get_success_data(api.activate_service_agreement(ltsa["id"], SVC_MGR))
    return ltsa


def current_ltsa_version(ltsa_id, api=api_client):
    return get_success_data(api.get_service_agreement(ltsa_id, SVC_MGR))["version"]


def create_order(ltsa_id, api=api_client, role_headers=None, **overrides):
    """Create a spare-part order with the LTSA's current version."""
    version = current_ltsa_version(ltsa_id, api=api)
    headers = role_headers or SVC_MGR
    return get_success_data(
        api.create_spare_part_order(
            create_spare_part_order_payload(ltsa_id, version, **overrides), headers
        )
    )


def setup_executed_augmentation(project, esa, added_capacity_mwh=2, api=api_client,
                                window_start="2026-09-01T00:00:00Z",
                                window_end="2026-10-01T00:00:00Z"):
    """Create + execute a MANUAL augmentation inside the default-clock window.

    Requires the project to be commissioned. Returns (project, augmentation).
    """
    aug = create_manual_augmentation(
        project["id"],
        api=api,
        planned_window_start=window_start,
        planned_window_end=window_end,
        added_capacity_mwh=added_capacity_mwh,
    )
    aug = execute_augmentation(aug["id"], project["id"], api=api)
    project = get_success_data(api.get_project(project["id"], DEV))
    return project, aug


# ─── Tier 5: terminal states ─────────────────────────────────────────────


def setup_completed_esa(api=api_client):
    """Full lifecycle: executed ESA, DELIVERY + COMMISSIONING achieved, COMPLETED.

    Returns (project, esa).
    """
    project, esa = setup_executed_project(api=api)
    delivery = create_milestone(esa["id"], "DELIVERY", "2026-10-01T00:00:00Z", api=api)
    commissioning = create_milestone(esa["id"], "COMMISSIONING", "2026-11-01T00:00:00Z", api=api)
    record_milestone_outcome(delivery["id"], "ACHIEVED", "2026-10-01T00:00:00Z", api=api)
    record_milestone_outcome(commissioning["id"], "ACHIEVED", "2026-10-20T00:00:00Z", api=api)
    esa = get_success_data(api.complete_esa(esa["id"], DEV))
    project = get_success_data(api.get_project(project["id"], DEV))
    return project, esa
