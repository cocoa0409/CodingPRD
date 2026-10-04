"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
operations, because the harness restarts the server before each test and the
database therefore starts empty. Setup calls use ``get_success_data()`` so a
broken precondition produces a clear "Setup failed" error rather than a
confusing assertion failure.

Because only a PRODUCTION environment may be created without a parent
(PRD §2.4), every sandbox helper first provisions a production root and clones
from it (or from a sandbox beneath it), which is also what gives a sandbox its
clone depth.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, RELEASE_ORDINALS, DEFAULT_CLOCK_UTC
from .factories import create_environment_payload
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
RELEASE = TEST_USERS["release_manager_headers"]
ENV_ADMIN = TEST_USERS["environment_admin_headers"]
STORAGE = TEST_USERS["storage_archivist_headers"]
AUDITOR = TEST_USERS["security_auditor_headers"]
DEVELOPER = TEST_USERS["app_developer_headers"]

_prod_counter = {"n": 0}


# ─── Tier 1: Creation and state progression ───────────────────────────────────

def create_production(**overrides) -> dict:
    """Provision the top-level production environment (the forest root)."""
    _prod_counter["n"] += 1
    payload = create_environment_payload(name=f"Production Org {_prod_counter['n']}",
                                         type="PRODUCTION", **overrides)
    res = api_client.create_environment(payload, ADMIN)
    return get_success_data(res, 201)


def create_sandbox(parent_id: str, **overrides) -> dict:
    """Provision a sandbox cloned from ``parent_id``."""
    payload = create_environment_payload(parent_environment_id=parent_id, **overrides)
    res = api_client.create_environment(payload, ADMIN)
    return get_success_data(res, 201)


def create_environment(type="DEVELOPER", parent_id=None, **overrides) -> dict:
    """Provision an environment under a fresh production root.

    ``type == "PRODUCTION"`` provisions the root itself; any other type is
    cloned from a production root (or from ``parent_id`` when supplied).
    """
    if type == "PRODUCTION":
        return create_production(**overrides)
    parent = parent_id or create_production()["id"]
    return create_sandbox(parent, type=type, **overrides)


def create_nested_sandbox(depth: int = 2, **overrides):
    """A sandbox ``depth`` clone levels below production.

    ``depth`` 1 is a sandbox cloned directly from production, ``depth`` 2 a
    sandbox cloned from that one. Returns the deepest sandbox.
    """
    current = create_production()
    for _ in range(depth - 1):
        current = create_sandbox(current["id"])
    return create_sandbox(current["id"], **overrides)


def create_gated_environment(**overrides):
    """A sandbox two clone levels below production, so the aperture gate applies.

    Returns the sandbox; ``create_nested_sandbox`` provisions the intermediate
    levels this environment's depth depends on.
    """
    return create_nested_sandbox(depth=2, **overrides)


def create_parent_and_gated_sandbox(parent_overrides=None):
    """A sandbox plus a sandbox cloned from it. Returns (parent, child)."""
    root = create_production()
    parent = create_sandbox(root["id"], **(parent_overrides or {}))
    child = create_sandbox(parent["id"], aperture_limit=TEST_DEFAULTS["APERTURE_LIMIT"])
    return parent, child


def schedule_release(environment: dict, target_release_version: str) -> dict:
    """schedule-release from CONFIG or RELEASED. Returns the SCHEDULED environment."""
    res = api_client.schedule_release(
        environment["id"], {"target_release_version": target_release_version}, RELEASE)
    return get_success_data(res)


def apply_release(environment_id: str) -> dict:
    """apply-release. Returns the RELEASED environment."""
    return get_success_data(api_client.apply_release(environment_id, RELEASE))


def schedule_and_apply_release(environment_id: str, target_release_version: str) -> dict:
    """schedule-release then apply-release. Returns the released environment."""
    get_success_data(api_client.schedule_release(
        environment_id, {"target_release_version": target_release_version}, RELEASE))
    return apply_release(environment_id)


def get_environment(environment_id: str) -> dict:
    """Read one environment (full posture): release, storage, aperture, layers."""
    return get_success_data(api_client.get_environment(environment_id, ADMIN))


# ─── Tier 2: Refresh jobs and the full refresh lifecycle ──────────────────────

def create_refresh_job(environment_id: str, **overrides) -> dict:
    """Open a refresh job in PENDING."""
    from .factories import create_refresh_job_payload
    res = api_client.create_refresh_job(
        create_refresh_job_payload(environment_id, **overrides), ENV_ADMIN)
    return get_success_data(res, 201)


def open_masked_refresh_job(environment_id: str, **overrides) -> dict:
    """Open a refresh job and record completed masking (PENDING -> MASKING)."""
    job = create_refresh_job(environment_id, **overrides)
    res = api_client.complete_masking(job["id"], ENV_ADMIN)
    return get_success_data(res)


def enter_completing(refresh_job_id: str) -> dict:
    """Move a MASKING job to COMPLETING (PRD §3.2, first half of the join)."""
    res = api_client.complete_refresh(refresh_job_id, ENV_ADMIN)
    return get_success_data(res)


def complete_refresh_job(environment_id: str, **overrides) -> dict:
    """Open, mask and fully complete a refresh job. Returns the COMPLETED job.

    Completing a refresh is a two-step join (PRD §3.2): the first call moves
    ``MASKING`` to ``COMPLETING`` and has no side effects, and only the second
    call — from ``COMPLETING`` — is admitted through the gates and emits the
    cascade.  A single call therefore leaves the job in ``COMPLETING``.
    """
    job = open_masked_refresh_job(environment_id, **overrides)
    enter_completing(job["id"])
    res = api_client.complete_refresh(job["id"], ENV_ADMIN)
    return get_success_data(res)


def complete_refreshes(environment_id: str, count: int, **overrides) -> list:
    """Run ``count`` full refresh completions on one environment."""
    return [complete_refresh_job(environment_id, **overrides) for _ in range(count)]


# ─── Tier 3: Managed package chains ───────────────────────────────────────────

def publish_package_version(namespace: str, major_version: int, name=None, **overrides) -> dict:
    """Publish a managed package version."""
    from .factories import create_package_version_payload
    res = api_client.create_package_version(
        create_package_version_payload(namespace, major_version=major_version,
                                       name=name or f"{namespace} Core {major_version}",
                                       **overrides), ADMIN)
    return get_success_data(res, 201)


def install_package(environment: dict, package_version_id: str,
                    expected_environment_version=None) -> dict:
    """Install a package version into an environment.

    Uses the environment's current ``version`` as the required
    ``expected_environment_version`` unless one is supplied.
    """
    from .factories import create_package_installation_payload
    res = api_client.install_package(
        environment["id"],
        create_package_installation_payload(
            package_version_id,
            expected_environment_version if expected_environment_version is not None
            else environment["version"]),
        RELEASE)
    return get_success_data(res, 201)


def setup_two_versions_same_namespace(namespace="acme"):
    """A first release plus a superseding version. Returns (v1, v2)."""
    v1 = publish_package_version(namespace, 1)
    v2 = publish_package_version(namespace, 2, supersedes_version_id=v1["id"])
    return v1, v2


# ─── Tier 4: Storage accumulation and threshold targeting ─────────────────────

def create_ledger(environment_id: str, kind: str, bytes: int, rank_index: int) -> dict:
    """Register one storage ledger row."""
    from .factories import create_storage_ledger_payload
    res = api_client.create_storage_ledger(
        environment_id, create_storage_ledger_payload(kind, bytes, rank_index), STORAGE)
    return get_success_data(res, 201)


def setup_file_ledgers(environment_id: str, sizes, start_rank: int = 1) -> list:
    """Register ``len(sizes)`` FILE ledgers at consecutive rank indexes."""
    return [create_ledger(environment_id, "FILE", size, start_rank + i)
            for i, size in enumerate(sizes)]


def setup_released_environment_with_file_ledgers(sizes, storage_cap_bytes=104857600,
                                                 release_version="SU26", **overrides):
    """A released sandbox holding the given FILE ledgers. Returns (env, ledgers)."""
    env = create_environment(storage_cap_bytes=storage_cap_bytes, **overrides)
    ledgers = setup_file_ledgers(env["id"], sizes)
    env = schedule_and_apply_release(env["id"], release_version)
    return env, ledgers


# ─── Tier 5: Change-set deployment pipeline ───────────────────────────────────

def create_change_set(source_id: str, target_env: dict, component_list=None,
                      expected_environment_version=None, **overrides):
    """Open a change set from ``source_id`` onto ``target_env``.

    ``target_env`` is the target environment response, whose ``version``
    supplies the required ``expected_environment_version`` precondition.
    """
    from .factories import create_change_set_payload
    payload = create_change_set_payload(
        source_id, target_env["id"],
        expected_environment_version if expected_environment_version is not None
        else target_env["version"],
        **overrides)
    if component_list is not None:
        payload["component_list"] = component_list
    res = api_client.create_change_set(payload, RELEASE)
    return get_success_data(res, 201)


def create_approved_change_set(source_id: str, target_env: dict, component_list=None, **overrides):
    """Open, validate and approve a change set. Returns the APPROVED change set."""
    cs = create_change_set(source_id, target_env, component_list=component_list, **overrides)
    get_success_data(api_client.validate_change_set(cs["id"], RELEASE))
    res = api_client.approve_change_set(cs["id"], ADMIN)
    return get_success_data(res)


def setup_source_and_target():
    """A source sandbox and a distinct target sandbox. Returns (source, target)."""
    root = create_production()
    source = create_sandbox(root["id"])
    target = create_sandbox(root["id"])
    return source, target


def setup_approved_change_set_with_deployment(idempotency_key="deploy-key-1",
                                              component_list=None):
    """Approved change set plus its queued deployment job.

    Returns (source, target, change_set, deployment_job).
    """
    source, target = setup_source_and_target()
    cs = create_approved_change_set(source["id"], target, component_list=component_list)
    dj = get_success_data(api_client.deploy_change_set(
        cs["id"], {"idempotency_key": idempotency_key}, RELEASE), 201)
    return source, target, cs, dj


def advance_to_deployed(source_id: str, target_env: dict, idempotency_key="deploy-key-ok",
                        component_list=None):
    """Full pipeline through DEPLOYED. Returns (change_set, deployment_job)."""
    cs = create_approved_change_set(source_id, target_env, component_list=component_list)
    dj = get_success_data(api_client.deploy_change_set(
        cs["id"], {"idempotency_key": idempotency_key}, RELEASE), 201)
    get_success_data(api_client.complete_deployment_job(dj["id"], ENV_ADMIN))
    return get_success_data(api_client.get_change_set(cs["id"], ADMIN)), dj


# ─── Tier 6: Governor requests and layered access ─────────────────────────────

def declare_governor_request(environment_id: str, **overrides) -> dict:
    """Declare an asynchronous-processing request in DRAFT."""
    from .factories import create_governor_request_payload
    res = api_client.create_governor_limit_request(
        environment_id, create_governor_request_payload(**overrides), DEVELOPER)
    return get_success_data(res, 201)


def submit_governor_request(governor_request_id: str) -> dict:
    res = api_client.submit_governor_request(governor_request_id, DEVELOPER)
    return get_success_data(res)


def grant_permission(environment_id: str, principal_type: str, principal_name: str,
                     user_id: str, **overrides) -> dict:
    """Grant one layered-access principal to an operator (PRD §3.7)."""
    from .factories import create_permission_payload
    res = api_client.grant_permission(
        environment_id,
        create_permission_payload(principal_type, principal_name, user_id, **overrides),
        AUDITOR)
    return get_success_data(res, 201)


def setup_layered_operator(environment_id: str, user_id: str,
                           principal_types=("PROFILE", "PERMISSION_SET")):
    """Grant one principal per requested layer to ``user_id``."""
    grants = []
    for i, ptype in enumerate(principal_types):
        grants.append(grant_permission(environment_id, ptype, f"Principal{i} {user_id}", user_id))
    return grants


def open_audit(environment_id: str, reviewed_assignment_ids) -> dict:
    """Open a layered-access audit over the given grants."""
    from .factories import create_access_audit_payload
    res = api_client.create_access_audit(
        create_access_audit_payload(environment_id, reviewed_assignment_ids), AUDITOR)
    return get_success_data(res, 201)


def close_audit(audit_id: str, finding: str) -> dict:
    """Close an audit with a REVOKE or RETAIN finding."""
    from .factories import close_audit_payload
    res = api_client.close_access_audit(audit_id, close_audit_payload(finding), AUDITOR)
    return get_success_data(res)


def release_ordinal(version: str) -> int:
    """Ordinal of a seasonal release version (PRD §2.9)."""
    return RELEASE_ORDINALS[version]


# ─── Clock and read-back helpers ──────────────────────────────────────────────

def set_clock(instant: str):
    """Advance the logical clock (PRD §2.11)."""
    return api_client.set_current_utc(instant, ADMIN)


def clock_plus(minutes_or_days, unit: str = "days", start: str = None) -> str:
    """An ISO 8601 instant ``N`` days after the logical clock's start instant.

    Serialised with three fractional digits to match the API's datetime format
    (PRD §2.11).
    """
    from datetime import datetime, timedelta
    base = start or DEFAULT_CLOCK_UTC
    delta = timedelta(days=minutes_or_days) if unit == "days" else timedelta(minutes=minutes_or_days)
    return (datetime.strptime(base, "%Y-%m-%dT%H:%M:%S.%fZ")
            + delta).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def load_installation(environment_id: str, installed_package_id: str) -> dict:
    """Read one installation back from its environment's installation listing."""
    from prd_bench_local_runner.testing import validate_paginated
    rows, _ = validate_paginated(
        api_client.list_package_installations(environment_id, ADMIN))
    return next(row for row in rows if row["id"] == installed_package_id)


def load_refresh_job(environment_id: str, refresh_job_id: str) -> dict:
    """Read one refresh job back from its environment's refresh-job listing."""
    from prd_bench_local_runner.testing import validate_paginated
    rows, _ = validate_paginated(
        api_client.list_refresh_jobs_of_environment(environment_id, ADMIN))
    return next(row for row in rows if row["id"] == refresh_job_id)