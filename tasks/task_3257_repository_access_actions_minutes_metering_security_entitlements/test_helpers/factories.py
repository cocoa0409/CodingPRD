"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ENTERPRISE_NAME": "Test Enterprise",
    "PURCHASED_SEATS": 10,
    "ORG_LOGIN": "org-1",
    "PLAN_TIER": "TEAM",
    "USER_LOGIN": "user-1",
    "USER_EMAIL": "user-1@example.com",
    "TEAM_NAME": "team-1",
    "REPO_NAME": "repo-1",
    "RUNNER_NAME": "runner-1",
    "OS_TYPE": "LINUX",
    "REQUESTED_MINUTES": 10,
    "ARTIFACT_NAME": "artifact-1",
    "ARTIFACT_SIZE_MB": 128,
    "PRODUCT": "SECRET_SCANNING",
    "APP_SLUG": "ci-bot",
}


def create_enterprise_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ENTERPRISE_NAME"],
        "purchased_seats": DEFAULTS["PURCHASED_SEATS"],
    }
    defaults.update(overrides)
    return defaults


def create_organization_payload(enterprise_id, **overrides) -> dict:
    defaults = {
        "enterprise_id": enterprise_id,
        "login": DEFAULTS["ORG_LOGIN"],
        "plan_tier": DEFAULTS["PLAN_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_user_payload(**overrides) -> dict:
    defaults = {
        "login": DEFAULTS["USER_LOGIN"],
        "email": DEFAULTS["USER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_commit_event_payload(author_user_id, organization_id, **overrides) -> dict:
    defaults = {
        "author_user_id": author_user_id,
        "organization_id": organization_id,
        "committed_at": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(organization_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "name": DEFAULTS["TEAM_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(user_id, **overrides) -> dict:
    defaults = {"user_id": user_id, "role": "MEMBER"}
    defaults.update(overrides)
    return defaults


def create_repository_payload(organization_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "name": DEFAULTS["REPO_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_outside_collaborator_payload(user_id, repository_id, **overrides) -> dict:
    defaults = {"user_id": user_id, "repository_id": repository_id}
    defaults.update(overrides)
    return defaults


def create_runner_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["RUNNER_NAME"],
        "os_type": DEFAULTS["OS_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_workflow_run_payload(expected_repository_version, **overrides) -> dict:
    defaults = {
        "runner_kind": "HOSTED",
        "os_type": "LINUX",
        "requested_minutes": DEFAULTS["REQUESTED_MINUTES"],
        "expected_repository_version": expected_repository_version,
    }
    defaults.update(overrides)
    return defaults


def create_artifact_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ARTIFACT_NAME"],
        "size_mb": DEFAULTS["ARTIFACT_SIZE_MB"],
    }
    defaults.update(overrides)
    return defaults


def create_entitlement_payload(repository_id, product, expected_organization_version,
                               **overrides) -> dict:
    defaults = {
        "repository_id": repository_id,
        "product": product,
        "expected_organization_version": expected_organization_version,
    }
    defaults.update(overrides)
    return defaults


def create_pat_payload(enterprise_id, **overrides) -> dict:
    defaults = {"enterprise_id": enterprise_id, "scopes": ["REPO"]}
    defaults.update(overrides)
    return defaults


def create_app_installation_payload(**overrides) -> dict:
    defaults = {
        "app_slug": DEFAULTS["APP_SLUG"],
        "permission_scopes": ["ISSUES_READ"],
    }
    defaults.update(overrides)
    return defaults
