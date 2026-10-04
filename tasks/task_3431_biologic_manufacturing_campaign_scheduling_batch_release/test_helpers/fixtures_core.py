"""Composite setup helpers — clock, master data, campaign and seed-train chains.

Every chain starts from an empty database, so each fixture sets the logical
clock explicitly and derives every datetime from the clock (never wall time).
All helpers use get_success_data() so setup failures surface as clear
"Setup failed" errors rather than assertion noise.

Env-dict convention: composite fixtures return a dict whose keys are the
created entities ("site", "product", "train", "campaign", "seed_stages", ...),
so tests can reach any layer of the built hierarchy.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import FIXTURE_CLOCK_START
from .factories import (
    create_site_payload, create_product_payload, create_train_payload,
    create_campaign_payload, create_seed_stage_payload, create_material_payload,
    create_inspection_payload, create_comparability_study_payload,
)
from .test_users import TEST_USERS

_ADMIN = TEST_USERS["platform_admin_headers"]
_ENGINEER = TEST_USERS["process_engineer_headers"]
_REGULATORY = TEST_USERS["regulatory_affairs_specialist_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def iso_shift(base_utc: str, hours: float = 0, seconds: float = 0) -> str:
    """Add hours/seconds to an ISO 8601 'Z' timestamp; return ISO 8601 'Z'."""
    base = datetime.fromisoformat(base_utc.replace("Z", "+00:00"))
    shifted = base + timedelta(hours=hours, seconds=seconds)
    return shifted.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_logical_clock(current_utc: str = FIXTURE_CLOCK_START) -> dict:
    """Advance the logical clock (PlatformAdmin capability, PRD §2.4)."""
    return get_success_data(api_client.set_clock(current_utc, _ADMIN))


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------

def create_site_entity(**overrides) -> dict:
    return get_success_data(api_client.create_site(create_site_payload(**overrides), _ADMIN))


def create_product_entity(**overrides) -> dict:
    return get_success_data(api_client.create_product(create_product_payload(**overrides), _ADMIN))


def create_train_entity(site_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_train(site_id, create_train_payload(**overrides), _ADMIN))


def create_material_lot(site_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_material(site_id, create_material_payload(**overrides), _ADMIN))


def create_inspection_entity(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_inspection(site_id, create_inspection_payload(**overrides), _REGULATORY))


def create_study_entity(product_id: str, candidate_batch_ids, **overrides) -> dict:
    payload = create_comparability_study_payload(candidate_batch_ids=candidate_batch_ids, **overrides)
    return get_success_data(api_client.create_comparability_study(product_id, payload, _REGULATORY))


def study_action(study_id: str, action: str, authority: str = None) -> dict:
    payload = {"action": action}
    if authority is not None:
        payload["authority"] = authority
    return get_success_data(api_client.study_action(study_id, payload, _REGULATORY))


def inspection_action(inspection_id: str, action: str, findings=None, response_summary=None) -> dict:
    payload = {"action": action}
    if findings is not None:
        payload["findings"] = findings
    if response_summary is not None:
        payload["response_summary"] = response_summary
    return get_success_data(api_client.inspection_action(inspection_id, payload, _REGULATORY))


# ---------------------------------------------------------------------------
# Campaign chains
# ---------------------------------------------------------------------------

def create_campaign_entity(train_id: str, product_id: str, **overrides) -> dict:
    payload = create_campaign_payload(product_id, **overrides)
    return get_success_data(api_client.create_campaign(train_id, payload, _ENGINEER))


def setup_master_data(clock_utc: str = FIXTURE_CLOCK_START, set_clock: bool = True,
                      site_overrides=None, product_overrides=None, train_overrides=None) -> dict:
    """Logical clock positioned + site + product + train. Returns env dict."""
    if set_clock:
        set_logical_clock(clock_utc)
    site = create_site_entity(**(site_overrides or {}))
    product = create_product_entity(**(product_overrides or {}))
    train = create_train_entity(site["id"], **(train_overrides or {}))
    return {"site": site, "product": product, "train": train}


def setup_campaign(clock_utc: str = FIXTURE_CLOCK_START, set_clock: bool = True,
                   site_overrides=None, product_overrides=None, train_overrides=None,
                   campaign_overrides=None) -> dict:
    """Master data + one campaign in PROPOSED. Returns env dict."""
    env = setup_master_data(clock_utc=clock_utc, set_clock=set_clock,
                            site_overrides=site_overrides, product_overrides=product_overrides,
                            train_overrides=train_overrides)
    env["campaign"] = create_campaign_entity(
        env["train"]["id"], env["product"]["id"], **(campaign_overrides or {}))
    return env


def advance_campaign(campaign_id: str, to_status: str) -> dict:
    return get_success_data(api_client.advance_campaign(campaign_id, to_status, _ENGINEER))


def setup_allocated_campaign(**kwargs) -> dict:
    """setup_campaign + advance to ALLOCATED. Returns env dict."""
    env = setup_campaign(**kwargs)
    env["campaign"] = advance_campaign(env["campaign"]["id"], "ALLOCATED")
    return env


# ---------------------------------------------------------------------------
# Seed train execution
# ---------------------------------------------------------------------------

def add_seed_stage(campaign_id: str, stage_index: int = 1, planned_duration_hours: int = 10) -> dict:
    payload = create_seed_stage_payload(stage_index=stage_index,
                                        planned_duration_hours=planned_duration_hours)
    return get_success_data(api_client.create_seed_stage(campaign_id, payload, _ENGINEER))


def advance_seed_stage(stage_id: str, to_status: str) -> dict:
    return get_success_data(api_client.advance_seed_stage(stage_id, to_status, _ENGINEER))


def run_seed_stage_to_completed(stage_id: str, duration_hours: float, start_clock_utc: str):
    """RUNNING at start_clock_utc, clock += duration, COMPLETED. Returns (stage, finish_utc)."""
    set_logical_clock(start_clock_utc)
    advance_seed_stage(stage_id, "RUNNING")
    finish = iso_shift(start_clock_utc, hours=duration_hours)
    set_logical_clock(finish)
    completed = advance_seed_stage(stage_id, "COMPLETED")
    return completed, finish


def seed_campaign(campaign_id: str, stage_durations=(10, 8),
                  seed_start_utc: str = FIXTURE_CLOCK_START) -> dict:
    """Define stages, advance to SEED_IN_PROGRESS, run every stage to COMPLETED.

    The clock is pinned to seed_start_utc (which must be at/after the
    campaign's planned_start_utc) and advanced by each stage's duration, so the
    36-hour transfer window and the 24-hour inoculation window both hold.
    Returns {"stages": [...], "last_completed_at": iso}.
    """
    stages = [add_seed_stage(campaign_id, i + 1, d) for i, d in enumerate(stage_durations)]
    advance_campaign(campaign_id, "SEED_IN_PROGRESS")
    cursor = seed_start_utc
    completed = []
    for stage, duration in zip(stages, stage_durations):
        stage_done, cursor = run_seed_stage_to_completed(stage["id"], duration, cursor)
        completed.append(stage_done)
    return {"stages": completed, "last_completed_at": cursor}


def setup_campaign_in_production(stage_durations=(10, 8), **kwargs) -> dict:
    """Full chain: master data + campaign + ALLOCATED + seed train run +
    PRODUCTION_IN_PROGRESS. The clock ends at the last stage completion.

    campaign_overrides.planned_start_utc also drives the seed-train start
    instant, keeping the start-too-early gate satisfied by construction.
    """
    env = setup_allocated_campaign(**kwargs)
    seed_start = (kwargs.get("campaign_overrides") or {}).get(
        "planned_start_utc", FIXTURE_CLOCK_START)
    seed = seed_campaign(env["campaign"]["id"], stage_durations, seed_start_utc=seed_start)
    env["seed_stages"] = seed["stages"]
    env["campaign"] = advance_campaign(env["campaign"]["id"], "PRODUCTION_IN_PROGRESS")
    return env
