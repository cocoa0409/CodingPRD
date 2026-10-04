"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (the lenient validator) internally so setup failures
surface as clear "Setup step failed" errors rather than confusing assertion
failures in the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, POLLING_CHARGE_TASKS
from .factories import (
    create_account_payload,
    create_member_payload,
    create_folder_payload,
    create_workflow_payload,
    create_action_payload,
    create_integration_payload,
    create_endpoint_payload,
    create_connection_payload,
    create_workflow_version_payload,
    publish_integration_version_payload,
)
from .test_users import TEST_USERS, make_member_headers

PLATFORM = TEST_USERS["platform_admin_headers"]
PARTNER = TEST_USERS["partner_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ─── Tier 1: single-entity creation primitives ──────────────────────────────

def provision_account(name="Test Account", plan_code=None, task_allowance=None,
                      closer_cost_per_task_cents=None, opening_cost_per_task_cents=None,
                      overage_enabled=None):
    """Provision a TeamAccount. Returns the created account dict."""
    payload = create_account_payload(
        name=name,
        plan_code=plan_code if plan_code is not None else TEST_DEFAULTS["PLAN_CODE"],
        task_allowance=(task_allowance if task_allowance is not None
                        else TEST_DEFAULTS["TASK_ALLOWANCE"]),
        closer_cost_per_task_cents=(closer_cost_per_task_cents if closer_cost_per_task_cents is not None
                                    else TEST_DEFAULTS["CLOSER_COST_PER_TASK_CENTS"]),
        opening_cost_per_task_cents=(opening_cost_per_task_cents if opening_cost_per_task_cents is not None
                                     else TEST_DEFAULTS["OPENING_COST_PER_TASK_CENTS"]),
        overage_enabled=(overage_enabled if overage_enabled is not None
                         else TEST_DEFAULTS["OVERAGE_ENABLED"]),
    )
    return get_success_data(api_client.create_account(payload, PLATFORM), 201)


def register_member(account_id, email, full_name, role="MEMBER"):
    """Register a Member into an account. Returns the created member dict."""
    payload = create_member_payload(account_id, email=email, full_name=full_name, role=role)
    return get_success_data(api_client.register_member(payload, PLATFORM), 201)


def create_integration(name="Slack", partner_name="Partner Inc", auth_method="OAUTH2"):
    """Draft a partner integration. Returns the created integration dict."""
    payload = create_integration_payload(name=name, partner_name=partner_name,
                                         auth_method=auth_method)
    return get_success_data(api_client.create_integration(payload, PARTNER), 201)


def declare_endpoint(integration_id, path, has_response_schema=True):
    """Declare an integration endpoint. Returns the created endpoint dict."""
    payload = create_endpoint_payload(path=path, has_response_schema=has_response_schema)
    return get_success_data(
        api_client.create_integration_endpoint(integration_id, payload, PARTNER), 201)


def create_connection(account_id, integration_id, owner_member_id):
    """Connect an account's integration credentials. Returns the connection dict."""
    payload = create_connection_payload(account_id, integration_id, owner_member_id)
    return get_success_data(
        api_client.create_connection(payload, make_member_headers(owner_member_id)), 201)


def create_folder(account_id, name, as_member_id):
    """Create a folder as the given member. Returns the folder dict."""
    payload = create_folder_payload(account_id, name=name)
    return get_success_data(
        api_client.create_folder(payload, make_member_headers(as_member_id)), 201)


def create_workflow(account_id, folder_id, as_member_id, name="Test Workflow",
                    trigger_type="POLLING", poll_interval_seconds=900):
    """Create a DRAFT workflow filed under a folder. Returns the workflow dict."""
    payload = create_workflow_payload(
        account_id, folder_id, name=name, trigger_type=trigger_type,
        poll_interval_seconds=poll_interval_seconds)
    return get_success_data(
        api_client.create_workflow(payload, make_member_headers(as_member_id)), 201)


def attach_action(workflow_id, integration_id, connection_id, as_member_id, position=1,
                  action_type="send_message", filter_expression=None):
    """Attach an action at a position. Returns the created action dict."""
    payload = create_action_payload(integration_id, connection_id, position=position,
                                    action_type=action_type)
    if filter_expression is not None:
        payload["filter_expression"] = filter_expression
    return get_success_data(
        api_client.create_action(workflow_id, payload, make_member_headers(as_member_id)), 201)


def activate_workflow(workflow_id, as_member_id):
    """Drive DRAFT -> ACTIVE. Returns the updated workflow dict."""
    return get_success_data(
        api_client.activate_workflow(workflow_id, make_member_headers(as_member_id)))


def publish_integration_version(integration_id, version_number):
    """Publish a newer integration revision. Returns the created revision dict."""
    payload = publish_integration_version_payload(version_number)
    return get_success_data(
        api_client.publish_integration_version(integration_id, payload, PARTNER), 201)


def get_account(account_id, as_member_id=None):
    """Read an account; returns the account dict."""
    headers = make_member_headers(as_member_id) if as_member_id else PLATFORM
    return get_success_data(api_client.get_account(account_id, headers))


def get_workflow(workflow_id, as_member_id=None):
    headers = make_member_headers(as_member_id) if as_member_id else PLATFORM
    return get_success_data(api_client.get_workflow(workflow_id, headers))


def get_connection(connection_id, as_member_id=None):
    headers = make_member_headers(as_member_id) if as_member_id else PLATFORM
    return get_success_data(api_client.get_connection(connection_id, headers))


def get_workflow_version(version_id, as_member_id=None):
    headers = make_member_headers(as_member_id) if as_member_id else PLATFORM
    return get_success_data(api_client.get_workflow_version(version_id, headers))


def get_integration(integration_id, headers=None):
    return get_success_data(api_client.get_integration(integration_id, headers or PARTNER))


# ─── Tier 2: entity hierarchy — the canonical team scenario ─────────────────

def setup_team(account_name="Test Account", plan_code=None, allowance=None, closer=None,
               opening=None, overage_enabled=None, owner_email="owner@x.test",
               member_email="mem@x.test"):
    """Provision an account plus an OWNER member and a plain MEMBER.

    Returns a dict with keys: account, owner, member, owner_headers, member_headers.
    The OWNER owns the account (folder visibility); the plain MEMBER owns the
    connection so that ownership-gated connection calls can be exercised.
    """
    account = provision_account(
        name=account_name, plan_code=plan_code,
        task_allowance=(allowance if allowance is not None else TEST_DEFAULTS["TASK_ALLOWANCE"]),
        closer_cost_per_task_cents=(closer if closer is not None
                                    else TEST_DEFAULTS["CLOSER_COST_PER_TASK_CENTS"]),
        opening_cost_per_task_cents=(opening if opening is not None
                                     else TEST_DEFAULTS["OPENING_COST_PER_TASK_CENTS"]),
        overage_enabled=(overage_enabled if overage_enabled is not None
                         else TEST_DEFAULTS["OVERAGE_ENABLED"]),
    )
    owner = register_member(account["id"], owner_email, "Owner One", "OWNER")
    member = register_member(account["id"], member_email, "Mem Ber", "MEMBER")
    return {
        "account": account,
        "owner": owner,
        "member": member,
        "owner_headers": make_member_headers(owner["id"]),
        "member_headers": make_member_headers(member["id"]),
    }


def setup_basic_scenario(account_name="Test Account", allowance=None, closer=None, opening=None,
                         overage_enabled=None, plan_code=None, auth_method="OAUTH2",
                         trigger_type="POLLING", poll_interval_seconds=900,
                         endpoints=None, activate=True, snapshot=False,
                         integration_name="Slack"):
    """The canonical scenario used by most tests.

    Builds: account + owner + member + integration (+ endpoints) + connection +
    folder + DRAFT workflow + one action, and optionally activates the workflow.
    When snapshot=True a CURRENT WorkflowVersion pinning the integration revision
    and connection is also created before activation.

    Returns a dict with keys: account, owner, member, integration, connection,
    folder, workflow, action, and matching *_headers.
    """
    team = setup_team(account_name=account_name, plan_code=plan_code, allowance=allowance,
                      closer=closer, opening=opening, overage_enabled=overage_enabled)
    account = team["account"]
    owner = team["owner"]
    member = team["member"]

    integration = create_integration(name=integration_name, auth_method=auth_method)
    declared = []
    for path, has_schema in (endpoints or [("/v1/op1", True)]):
        declared.append(declare_endpoint(integration["id"], path, has_schema))

    connection = create_connection(account["id"], integration["id"], member["id"])
    folder = create_folder(account["id"], "Ops", owner["id"])
    workflow = create_workflow(account["id"], folder["id"], owner["id"],
                               trigger_type=trigger_type,
                               poll_interval_seconds=poll_interval_seconds)
    action = attach_action(workflow["id"], integration["id"], connection["id"], owner["id"])

    revision = None
    snapshot_obj = None
    if snapshot:
        revision = publish_integration_version(integration["id"], 1)
        snapshot_obj = get_success_data(api_client.create_workflow_version(
            create_workflow_version_payload(workflow["id"], revision["id"], connection["id"]),
            team["owner_headers"]), 201)

    if activate:
        workflow = activate_workflow(workflow["id"], owner["id"])

    return {
        "account": account,
        "owner": owner,
        "member": member,
        "integration": integration,
        "endpoints": declared,
        "revision": revision,
        "snapshot": snapshot_obj,
        "connection": connection,
        "folder": folder,
        "workflow": workflow,
        "action": action,
        "owner_headers": team["owner_headers"],
        "member_headers": team["member_headers"],
    }


def add_workflow(scenario, name, trigger_type="POLLING", poll_interval_seconds=900,
                 activate=True, positions=1):
    """Add another workflow (with `positions` actions) to an existing scenario."""
    workflow = create_workflow(scenario["account"]["id"], scenario["folder"]["id"],
                               scenario["owner"]["id"], name=name, trigger_type=trigger_type,
                               poll_interval_seconds=poll_interval_seconds)
    actions = []
    for pos in range(1, positions + 1):
        actions.append(attach_action(workflow["id"], scenario["integration"]["id"],
                                     scenario["connection"]["id"], scenario["owner"]["id"],
                                     position=pos))
    if activate:
        workflow = activate_workflow(workflow["id"], scenario["owner"]["id"])
    return {"workflow": workflow, "actions": actions}


def add_action(workflow_id, scenario, position, as_member_id=None):
    """Attach an extra action to a workflow in an existing scenario."""
    return attach_action(workflow_id, scenario["integration"]["id"],
                         scenario["connection"]["id"],
                         as_member_id or scenario["owner"]["id"], position=position)


# ─── Tier 3: full lifecycle shortcuts ───────────────────────────────────────

def dispatch_run(workflow_id, as_member_id, charge="success", **overrides):
    """Dispatch a run; returns the raw response so callers can assert errors."""
    payload = {"charge": charge}
    payload.update(overrides)
    return api_client.dispatch_run(workflow_id, payload, make_member_headers(as_member_id))


def expire_token(connection_id):
    """Expire a connection's credential at the current logical instant."""
    return api_client.expire_token({"connection_id": connection_id}, PLATFORM)


def force_reauth(connection_id, owner_member_id):
    """Spend the connection's five-refresh lifetime budget and force it into
    REAUTH_REQUIRED via one further refresh (PRD section 3.6).

    Each successful refresh moves the connection to CONNECTED, so a fresh token
    lapse precedes each attempt. Returns the final (rejecting) response.
    """
    headers = make_member_headers(owner_member_id)
    for _ in range(5):
        expire_token(connection_id)
        get_success_data(api_client.refresh_connection(connection_id, headers))
    expire_token(connection_id)
    return api_client.refresh_connection(connection_id, headers)


def hold_run(workflow_id, as_member_id, max_retries=3):
    """Dispatch a hold-charge run that leaves the action HELD. Returns the run dict."""
    res = dispatch_run(workflow_id, as_member_id, charge="hold", forced_failure=True,
                       max_retries=max_retries)
    return get_success_data(res)


def recover_downstream(connection_id):
    """Mark a connection's downstream service recovered."""
    return api_client.downstream_recover({"connection_id": connection_id}, PLATFORM)


def rotate_epoch(account_id, occurred_at="2026-10-01T00:00:00Z"):
    """Record an OPS_RUN lapse incident, rotating the account's metering epoch."""
    return api_client.create_lapse_incident(
        account_id, {"kind": "OPS_RUN", "occurred_at": occurred_at, "target_id": account_id},
        PLATFORM)


def account_tasks(scenario):
    """Read the scenario account's current whole-task consumption."""
    return get_account(scenario["account"]["id"])["tasks_used_current"]


# ─── Tier 4: threshold targeting ────────────────────────────────────────────

def setup_polling_charge(allowance, closer=1, opening=1, overage_enabled=True,
                         account_name="Charge Co"):
    """An activated one-action POLLING workflow whose single run charges
    POLLING_CHARGE_TASKS whole tasks. Used for metering and overage boundaries."""
    return setup_basic_scenario(account_name=account_name, allowance=allowance,
                                closer=closer, opening=opening,
                                overage_enabled=overage_enabled,
                                trigger_type="POLLING")


def setup_multi_action_workflow(num_actions, allowance=1000, trigger_type="POLLING",
                                account_name="Steps Co"):
    """A scenario plus an activated workflow carrying `num_actions` actions."""
    scenario = setup_basic_scenario(account_name=account_name, allowance=allowance,
                                    trigger_type=trigger_type, activate=True)
    # The base scenario already carries action position 1; attach the remainder.
    for pos in range(2, num_actions + 1):
        add_action(scenario["workflow"]["id"], scenario, pos)
    return scenario


# ─── Tier 5: finalization / terminal state ──────────────────────────────────

def setup_snapshot_scenario(allowance=100, overage_enabled=True, account_name="Snap Co"):
    """An activated workflow pinned by a CURRENT snapshot, with a published
    revision to migrate toward."""
    return setup_basic_scenario(account_name=account_name, allowance=allowance,
                                overage_enabled=overage_enabled, snapshot=True,
                                activate=True)