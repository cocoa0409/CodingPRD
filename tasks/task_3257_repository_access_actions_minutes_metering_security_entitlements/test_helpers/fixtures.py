"""Composite setup helpers for multi-step test preconditions.

Every fixture builds its preconditions from scratch against an empty database
(the harness restarts the server before each test). Setup calls use the
lenient get_success_data() so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_artifact_payload,
    create_commit_event_payload,
    create_entitlement_payload,
    create_enterprise_payload,
    create_organization_payload,
    create_outside_collaborator_payload,
    create_pat_payload,
    create_repository_payload,
    create_runner_payload,
    create_team_payload,
    create_user_payload,
    create_workflow_run_payload,
    create_app_installation_payload,
)
from .test_users import TEST_USERS, make_user_headers

EA = TEST_USERS["enterprise_admin_headers"]
OA = TEST_USERS["org_admin_headers"]
RA = TEST_USERS["runner_agent_headers"]


def _fail(ctx, resp):
    raise AssertionError(f"Setup failed ({ctx}): {resp.status_code} {resp.text}")


def create_enterprise(purchased_seats=5, name="E1", **overrides):
    resp = api_client.create_enterprise(
        create_enterprise_payload(name=name, purchased_seats=purchased_seats, **overrides), EA
    )
    if resp.status_code != 201:
        _fail("create_enterprise", resp)
    return get_success_data(resp)


def create_organization(ent_id, login="org1", plan_tier="TEAM", **overrides):
    resp = api_client.create_organization(
        create_organization_payload(ent_id, login=login, plan_tier=plan_tier, **overrides), EA
    )
    if resp.status_code != 201:
        _fail("create_organization", resp)
    return get_success_data(resp)


def create_user(login="u1", email=None):
    resp = api_client.create_user(
        create_user_payload(login=login, email=email or f"{login}@x.com"), EA
    )
    if resp.status_code != 201:
        _fail("create_user", resp)
    return get_success_data(resp)


def create_repository(org_id, name="repo1", **overrides):
    resp = api_client.create_repository(
        create_repository_payload(org_id, name=name, **overrides), OA
    )
    if resp.status_code != 201:
        _fail("create_repository", resp)
    return get_success_data(resp)


def create_team(org_id, name="t1", **overrides):
    resp = api_client.create_team(create_team_payload(org_id, name=name, **overrides), OA)
    if resp.status_code != 201:
        _fail("create_team", resp)
    return get_success_data(resp)


def set_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    resp = api_client.set_clock(to_iso8601, EA)
    if resp.status_code != 200:
        _fail("set_clock", resp)
    return get_success_data(resp)


def create_commit_event(author_user_id, org_id, committed_at=DEFAULT_CLOCK_ISO):
    resp = api_client.create_commit_event(
        create_commit_event_payload(author_user_id, org_id, committed_at=committed_at), OA
    )
    if resp.status_code != 201:
        _fail("create_commit_event", resp)
    return get_success_data(resp)


def get_org(org_id):
    resp = api_client.get_organization(org_id, EA)
    if resp.status_code != 200:
        _fail("get_organization", resp)
    return get_success_data(resp)


def setup_enterprise_with_org(purchased_seats=5, plan_tier="TEAM", **org_overrides):
    """Enterprise + one Organization. Returns (enterprise, organization)."""
    ent = create_enterprise(purchased_seats=purchased_seats)
    org = create_organization(ent["id"], plan_tier=plan_tier, **org_overrides)
    return ent, org


def setup_org_with_repo(purchased_seats=5, plan_tier="TEAM", **org_overrides):
    """Enterprise + Organization + Repository. Returns (ent, org, repo)."""
    ent, org = setup_enterprise_with_org(purchased_seats, plan_tier, **org_overrides)
    repo = create_repository(org["id"])
    return ent, org, repo


def create_workflow_run(repo, expected_version=None, **overrides):
    """Dispatch a run; expected_version defaults to repo['version'].
    Returns the created WorkflowRun data."""
    version = expected_version if expected_version is not None else repo["version"]
    resp = api_client.create_workflow_run(
        repo["id"], create_workflow_run_payload(version, **overrides), OA
    )
    if resp.status_code != 201:
        _fail("create_workflow_run", resp)
    return get_success_data(resp)


def run_transition(run_id, action, headers=None):
    resp = api_client.workflow_run_transition(run_id, action, headers or RA)
    if resp.status_code != 200:
        _fail(f"run_transition {action}", resp)
    return get_success_data(resp)


def create_and_complete_run(repo, expected_version=None, **overrides):
    """Dispatch + START + COMPLETE. Returns final WorkflowRun data."""
    run = create_workflow_run(repo, expected_version, **overrides)
    run_transition(run["id"], "START")
    return run_transition(run["id"], "COMPLETE")


def create_runner_and_activate(org_id, **overrides):
    """Register runner + heartbeat to ACTIVE. Returns runner data."""
    resp = api_client.create_runner(org_id, create_runner_payload(**overrides), OA)
    if resp.status_code != 201:
        _fail("create_runner", resp)
    runner = get_success_data(resp)
    resp = api_client.runner_heartbeat(runner["id"], RA)
    if resp.status_code != 200:
        _fail("runner_heartbeat", resp)
    return get_success_data(resp)


def create_invite(org_id, user_id, repo_id):
    resp = api_client.create_outside_collaborator(
        org_id, create_outside_collaborator_payload(user_id, repo_id), OA
    )
    if resp.status_code != 201:
        _fail("create_outside_collaborator", resp)
    return get_success_data(resp)


def create_entitlement(org_id, repo_id, product, expected_org_version=None):
    """Create a PENDING_ACTIVATION entitlement. expected_org_version defaults
    to the org's current version. Returns entitlement data."""
    if expected_org_version is None:
        expected_org_version = get_org(org_id)["version"]
    resp = api_client.create_security_entitlement(
        org_id, create_entitlement_payload(repo_id, product, expected_org_version), OA
    )
    if resp.status_code != 201:
        _fail("create_security_entitlement", resp)
    return get_success_data(resp)


def entitlement_transition(entitlement_id, action):
    resp = api_client.entitlement_transition(entitlement_id, action, OA)
    if resp.status_code != 200:
        _fail(f"entitlement_transition {action}", resp)
    return get_success_data(resp)


def create_and_activate_entitlement(org_id, repo_id, product):
    """Create + ACTIVATE an entitlement. Returns activated entitlement data."""
    ent = create_entitlement(org_id, repo_id, product)
    return entitlement_transition(ent["id"], "ACTIVATE")


def create_pat(user, ent_id, scopes=None):
    """Create a PAT owned by the given user (ownership-gated headers)."""
    payload = create_pat_payload(ent_id, scopes=scopes or ["REPO"])
    resp = api_client.create_personal_access_token(
        user["id"], payload, make_user_headers(user["id"])
    )
    if resp.status_code != 201:
        _fail("create_pat", resp)
    return get_success_data(resp)


def create_app_installation(org_id, **overrides):
    resp = api_client.create_app_installation(
        org_id, create_app_installation_payload(**overrides), OA
    )
    if resp.status_code != 201:
        _fail("create_app_installation", resp)
    return get_success_data(resp)


def create_and_install_app(org_id, **overrides):
    app = create_app_installation(org_id, **overrides)
    resp = api_client.app_installation_transition(app["id"], "INSTALL", OA)
    if resp.status_code != 200:
        _fail("app INSTALL", resp)
    return get_success_data(resp)


def sso_transition(ent_id, action):
    resp = api_client.sso_transition(ent_id, action, EA)
    if resp.status_code != 200:
        _fail(f"sso_transition {action}", resp)
    return get_success_data(resp)


def org_transition(org_id, action):
    resp = api_client.org_transition(org_id, action, EA)
    if resp.status_code != 200:
        _fail(f"org_transition {action}", resp)
    return get_success_data(resp)


def user_transition(user_id, action):
    resp = api_client.user_transition(user_id, action, EA)
    if resp.status_code != 200:
        _fail(f"user_transition {action}", resp)
    return get_success_data(resp)


def create_artifact(repo_id, **overrides):
    resp = api_client.create_artifact(repo_id, create_artifact_payload(**overrides), OA)
    if resp.status_code != 201:
        _fail("create_artifact", resp)
    return get_success_data(resp)


def get_seat_usage(ent_id, mode="CYCLE"):
    resp = api_client.get_seat_usage(ent_id, EA, mode=mode)
    if resp.status_code != 200:
        _fail("get_seat_usage", resp)
    return get_success_data(resp)


def list_audit_events(ent_id, params=None):
    resp = api_client.list_audit_log_events(ent_id, EA, params=params)
    if resp.status_code != 200:
        _fail("list_audit_log_events", resp)
    return resp.json()["data"]
