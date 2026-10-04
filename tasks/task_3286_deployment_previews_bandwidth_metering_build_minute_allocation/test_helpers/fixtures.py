"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because each test runs against a freshly restarted server with an
empty database. Setup calls use the lenient get_success_data() validator so
setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import PERIOD_END, PERIOD_START
from .factories import (
    create_domain_payload,
    create_git_event_payload,
    create_plan_catalog_payload,
    create_project_payload,
    create_spend_cap_payload,
    create_team_payload,
    create_usage_period_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
WEBHOOK = TEST_USERS["system_webhook_headers"]
OWNER = TEST_USERS["team_owner_headers"]
BILLING = TEST_USERS["team_billing_manager_headers"]
DEVELOPER = TEST_USERS["developer_headers"]
VIEWER = TEST_USERS["viewer_headers"]


def _setup(resp, what):
    if resp.status_code >= 400:
        raise AssertionError(
            f"Setup failed for {what}: HTTP {resp.status_code} body={resp.text}"
        )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1 / 2: plans, teams, projects, periods
# ---------------------------------------------------------------------------

def create_plan(**overrides):
    """Create a plan catalog entry. Returns the entry data."""
    return _setup(
        api_client.create_plan_catalog_entry(create_plan_catalog_payload(**overrides), ADMIN),
        "plan catalog entry",
    )


def create_team(plan_tier="PRO", **overrides):
    """Create a team on the given plan tier. Returns the team data."""
    return _setup(
        api_client.create_team(create_team_payload(plan_tier=plan_tier, **overrides), ADMIN),
        "team",
    )


def create_project(team_id, **overrides):
    """Create a project in the team. Returns the project data."""
    return _setup(
        api_client.create_project(team_id, create_project_payload(**overrides), OWNER),
        "project",
    )


def create_usage_period(team_id, **overrides):
    """Open a usage period for the team. Returns the period data."""
    return _setup(
        api_client.create_usage_period(team_id, create_usage_period_payload(**overrides), BILLING),
        "usage period",
    )


def setup_team_on_plan(**plan_overrides):
    """Plan + team. Returns (plan, team)."""
    plan = create_plan(**plan_overrides)
    team = create_team(plan_tier=plan["tier"])
    return plan, team


def setup_team_with_project(**plan_overrides):
    """Plan + team + project. Returns (plan, team, project)."""
    plan, team = setup_team_on_plan(**plan_overrides)
    project = create_project(team["id"])
    return plan, team, project


def setup_team_with_project_and_period(**plan_overrides):
    """Plan + team + project + OPEN usage period. Returns (plan, team, project, period)."""
    plan, team, project = setup_team_with_project(**plan_overrides)
    period = create_usage_period(team["id"])
    return plan, team, project, period


# ---------------------------------------------------------------------------
# Tier 3: deployment lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_deployment(project_id, branch="feat-a", commit_sha="aaa111", **overrides):
    """Create a preview deployment via the git webhook. Returns deployment data."""
    git_ref = overrides.pop("git_ref", f"refs/heads/{branch}")
    return _setup(
        api_client.create_git_event(
            create_git_event_payload(
                project_id, branch=branch, git_ref=git_ref, commit_sha=commit_sha, **overrides
            ),
            WEBHOOK,
        ),
        "deployment",
    )


def build_deployment(deployment_id, outcome="SUCCESS", build_duration_seconds=60):
    """build-start + build-complete. Returns the completed deployment data."""
    _setup(api_client.build_start(deployment_id, WEBHOOK), "build-start")
    return _setup(
        api_client.build_complete(
            deployment_id,
            {"outcome": outcome, "build_duration_seconds": build_duration_seconds},
            WEBHOOK,
        ),
        "build-complete",
    )


def create_ready_deployment(project_id, branch="feat-a", commit_sha="aaa111",
                            build_duration_seconds=60):
    """Create a deployment and build it to READY. Returns deployment data."""
    dep = create_deployment(project_id, branch=branch, commit_sha=commit_sha)
    return build_deployment(dep["id"], "SUCCESS", build_duration_seconds)


def create_promoted_deployment(project_id, branch="main", commit_sha="aaa111",
                               build_duration_seconds=60):
    """Create a READY deployment and promote it. Returns promoted deployment data."""
    dep = create_ready_deployment(
        project_id, branch=branch, commit_sha=commit_sha,
        build_duration_seconds=build_duration_seconds,
    )
    return _setup(api_client.promote_deployment(dep["id"], OWNER), "promote")


# ---------------------------------------------------------------------------
# Tier 4: domains & certificates
# ---------------------------------------------------------------------------

def create_domain(project_id, name="example.com"):
    """Assign a domain to the project. Returns domain data."""
    return _setup(
        api_client.create_domain(project_id, create_domain_payload(name=name), OWNER),
        "domain",
    )


def verify_domain(domain_id, outcome="SUCCESS"):
    """Submit a verification outcome. Returns domain data."""
    return _setup(
        api_client.verify_domain(domain_id, {"outcome": outcome}, DEVELOPER),
        "domain verify",
    )


def list_domain_certificates(domain_id):
    """List certificates of a domain. Returns the list."""
    data = _setup(api_client.list_certificates(domain_id, OWNER), "list certificates")
    if isinstance(data, list):
        return data
    return data.get("items", data) if isinstance(data, dict) else data


def setup_domain_with_active_certificate(project_id, name="example.com"):
    """Domain VERIFIED with its certificate completed to ACTIVE.

    Returns (domain, certificate).
    """
    domain = create_domain(project_id, name=name)
    verify_domain(domain["id"], "SUCCESS")
    certs = list_domain_certificates(domain["id"])
    assert len(certs) >= 1, "Setup failed: expected a spawned certificate after verify SUCCESS"
    cert_id = certs[0]["id"]
    cert = _setup(api_client.complete_certificate(cert_id, WEBHOOK), "certificate complete")
    domain = _setup(api_client.get_domain(domain["id"], OWNER), "re-read domain")
    return domain, cert


# ---------------------------------------------------------------------------
# Tier 4: spend caps / suspension
# ---------------------------------------------------------------------------

def create_spend_cap(team_id, **overrides):
    """Create a spend cap for the team. Returns cap data."""
    return _setup(
        api_client.create_spend_cap(team_id, create_spend_cap_payload(**overrides), BILLING),
        "spend cap",
    )


def get_project(project_id):
    return _setup(api_client.get_project(project_id, OWNER), "get project")


def get_deployment(deployment_id):
    return _setup(api_client.get_deployment(deployment_id, OWNER), "get deployment")


def get_domain(domain_id):
    return _setup(api_client.get_domain(domain_id, OWNER), "get domain")


def get_certificate(cert_id):
    return _setup(api_client.get_certificate(cert_id, OWNER), "get certificate")


def get_team(team_id):
    return _setup(api_client.get_team(team_id, OWNER), "get team")


def get_usage_period(period_id):
    return _setup(api_client.get_usage_period(period_id, BILLING), "get usage period")


def get_spend_cap(cap_id):
    return _setup(api_client.get_spend_cap(cap_id, BILLING), "get spend cap")


def get_alert_rule(rule_id):
    return _setup(api_client.get_alert_rule(rule_id, BILLING), "get alert rule")


def set_clock(to_iso8601):
    return _setup(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), "set clock")
