"""Governor limits and asynchronous-processing declarations: the cost
projection, the submission gates and the acceptance ceiling."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_environment,
    declare_governor_request,
    submit_governor_request,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DEVELOPER = TEST_USERS["app_developer_headers"]


# ─── The cost projection ──────────────────────────────────────────────────────

def test_governor_projection_charges_scope_and_callout_cells(api):
    """PRD §3.8: "The projected cost is the scope count multiplied by the
    per-record batch cost of 2 units, plus the cell count multiplied by the
    per-cell callout cost of 250 units; the result is written to
    `projected_governor_units`, and `governor_headroom_units` is the
    organization-wide governor ceiling of 100000 units minus that projection."

    Design: Difficulty/combinatorial_formula/governor_depth_max_nonlinear_projection
    """
    env = create_environment(type="DEVELOPER")
    request = declare_governor_request(
        env["id"], request_kind="BATCH", scope_count=5,
        callout_graph=[{"node": "syncA", "calls": ["syncB"]},
                       {"node": "syncB", "calls": []}])
    assert request["projected_governor_units"] == 260


def test_governor_headroom_is_the_ceiling_minus_the_projection(api):
    """PRD §3.8: "`governor_headroom_units` is the organization-wide governor
    ceiling of 100000 units minus that projection."

    Design: Difficulty/combinatorial_formula/governor_depth_max_nonlinear_projection
    """
    env = create_environment(type="DEVELOPER")
    request = declare_governor_request(
        env["id"], request_kind="BATCH", scope_count=5,
        callout_graph=[{"node": "syncA", "calls": ["syncB"]},
                       {"node": "syncB", "calls": []}])
    assert request["governor_headroom_units"] == 99740


def test_empty_callout_graph_collapses_the_cell_term(api):
    """PRD §3.8: "The graph's depth is the longest callout path measured in
    links, and it is zero when the graph is empty."

    Design: Corner/calculations/governor_projection_empty_callout_graph_zero_cell_term
    """
    env = create_environment(type="DEVELOPER")
    request = declare_governor_request(
        env["id"], request_kind="QUEUEABLE", scope_count=0,
        callout_graph=[], max_concurrent_jobs=3)
    assert request["projected_governor_units"] == 0
    assert request["governor_headroom_units"] == 100000
    assert request["status"] == "DRAFT"


def test_scope_only_projection_charges_no_callout_cells(api):
    """PRD §3.8: "nodes at depth zero are counted in the scope instead and are
    excluded from the callout multiplier."

    Design: Corner/calculations/governor_projection_empty_callout_graph_zero_cell_term
    """
    env = create_environment(type="DEVELOPER")
    request = declare_governor_request(
        env["id"], request_kind="SCHEDULED", scope_count=500, callout_graph=[])
    assert request["projected_governor_units"] == 1000
    assert request["governor_headroom_units"] == 99000


# ─── Submission gates ─────────────────────────────────────────────────────────

def test_cyclic_callout_graph_is_refused_on_submission(api):
    """PRD §3.8: "The request must be `DRAFT`, its `callout_graph` must be
    acyclic, and — separately — the graph must be no deeper than the sixth
    callout level; a cycle is refused with `ERR_CYCLE_DETECTED` and HTTP status
    409, and a graph deeper than the permitted six levels is not admitted
    either."

    Design: Corner/errors/cyclic_component_graph_and_cyclic_callout_graph_return_cycle_detected
    """
    env = create_environment(type="DEVELOPER")
    request = declare_governor_request(
        env["id"], request_kind="QUEUEABLE", scope_count=10,
        callout_graph=[{"node": "syncA", "calls": ["syncB"]},
                       {"node": "syncB", "calls": ["syncA"]}])

    res = api.submit_governor_request(request["id"], DEVELOPER)
    validate_error(res, "ERR_CYCLE_DETECTED", expected_status=409)


def test_acyclic_callout_graph_submits_successfully(api):
    """PRD §3.8: "Submission is the `DRAFT` → `SUBMITTED` transition."
    PRD §3.8: "Submission recomputes the projected units."

    Design: Corner/errors/cyclic_component_graph_and_cyclic_callout_graph_return_cycle_detected
    """
    env = create_environment(type="DEVELOPER")
    request = declare_governor_request(
        env["id"], request_kind="QUEUEABLE", scope_count=10,
        callout_graph=[{"node": "syncA", "calls": ["syncB"]},
                       {"node": "syncB", "calls": []}])

    submitted = validate_success(api.submit_governor_request(request["id"], DEVELOPER), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["projected_governor_units"] == 270


def test_concurrency_ceiling_blocks_a_second_submission(api):
    """PRD §3.8: "The per-environment ceiling is checked last, as described in
    §2.12: the number of the environment's requests already in `SUBMITTED` must
    be below the request's own `max_concurrent_jobs`, and a submission that
    would exceed it is refused with `ERR_GOVERNOR_LIMIT_EXCEEDED` and HTTP
    status 402."

    Design: Corner/errors/governor_concurrency_ceiling_blocks_second_submission
    """
    env = create_environment(type="DEVELOPER")
    first = declare_governor_request(
        env["id"], request_kind="SCHEDULED", scope_count=100, callout_graph=[],
        max_concurrent_jobs=1)
    second = declare_governor_request(
        env["id"], request_kind="SCHEDULED", scope_count=100, callout_graph=[],
        max_concurrent_jobs=1)
    assert first["projected_governor_units"] == 200
    assert second["projected_governor_units"] == 200

    submitted = validate_success(api.submit_governor_request(first["id"], DEVELOPER), 200)
    assert submitted["status"] == "SUBMITTED"

    res = api.submit_governor_request(second["id"], DEVELOPER)
    validate_error(res, "ERR_GOVERNOR_LIMIT_EXCEEDED", expected_status=402)
    assert _request_status(env["id"], second["id"]) == "DRAFT"


def _request_status(environment_id: str, request_id: str) -> str:
    from test_helpers import validate_paginated
    rows, _ = validate_paginated(
        api_client.list_governor_limit_requests_of_environment(environment_id, ADMIN))
    return next(row for row in rows if row["id"] == request_id)["status"]


# ─── Acceptance and the aggregate ceiling ─────────────────────────────────────

def test_acceptance_recomputes_the_governor_headroom(api):
    """PRD §3.8: "Acceptance is where the organization's shared budget is
    actually spent, so the headroom figure is recomputed at acceptance against
    the environment's other accepted requests rather than against the projection
    alone."

    Design: Corner/state_machines/governor_publish_side_effects_fire_on_accept
    """
    env = create_environment(type="DEVELOPER")
    request = declare_governor_request(
        env["id"], request_kind="SCHEDULED", scope_count=500, callout_graph=[])
    submit_governor_request(request["id"])

    accepted = validate_success(api.approve_governor_request(request["id"], ADMIN), 200)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["projected_governor_units"] == 1000
    assert accepted["governor_headroom_units"] == 99000


def test_second_acceptance_beyond_the_ceiling_is_refused(api):
    """PRD §3.8: "The request must be `SUBMITTED`, and its projected units plus
    the sum of the projected units of the environment's other accepted requests
    must not exceed the organization-wide ceiling of 100000 units; exceeding it
    is refused with `ERR_GOVERNOR_LIMIT_EXCEEDED` and HTTP status 402."

    Design: Corner/errors/governor_ceiling_exceeded_on_second_acceptance
    """
    env = create_environment(type="DEVELOPER")
    first = declare_governor_request(
        env["id"], request_kind="BATCH", scope_count=20000, callout_graph=[])
    second = declare_governor_request(
        env["id"], request_kind="BATCH", scope_count=35000, callout_graph=[])
    submit_governor_request(first["id"])
    submit_governor_request(second["id"])
    accepted = validate_success(api.approve_governor_request(first["id"], ADMIN), 200)
    assert accepted["projected_governor_units"] == 40000
    assert accepted["governor_headroom_units"] == 60000

    res = api.approve_governor_request(second["id"], ADMIN)
    validate_error(res, "ERR_GOVERNOR_LIMIT_EXCEEDED", expected_status=402)
    assert _request_status(env["id"], second["id"]) == "SUBMITTED"


# ─── The request / approval chain ─────────────────────────────────────────────

def test_app_developer_cannot_accept_own_governor_request(api):
    """PRD §2.1: "`AppDeveloper` declares asynchronous-processing requests and
    submits them for governor review."
    PRD §2.1: "`PlatformAdmin` provisions environments, publishes managed package
    versions, approves change sets, accepts or rejects governor-limit requests"

    Design: Corner/rbac/app_developer_cannot_accept_own_governor_request
    """
    env = create_environment(type="DEVELOPER")
    request = declare_governor_request(
        env["id"], request_kind="QUEUEABLE", scope_count=50, callout_graph=[])
    submit_governor_request(request["id"])

    res = api.approve_governor_request(request["id"], DEVELOPER)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    assert _request_status(env["id"], request["id"]) == "SUBMITTED"

    accepted = validate_success(api.approve_governor_request(request["id"], ADMIN), 200)
    assert accepted["status"] == "ACCEPTED"