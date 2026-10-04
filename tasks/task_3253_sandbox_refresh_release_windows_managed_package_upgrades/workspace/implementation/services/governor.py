"""Asynchronous-processing declarations and the governor budget (PRD §3.8).

The graph's depth is the longest callout path measured in links, zero when the
graph is empty.  The cell count is the number of nodes reachable from a root
node (nodes at callout depth of at least one).  Projected cost is the scope
count times 2 units plus the cell count times 250 units; headroom is the
organization-wide ceiling of 100000 units minus that projection.
"""

import calculations
import db
from errors import (
    ERR_CYCLE_DETECTED,
    ERR_GOVERNOR_LIMIT_EXCEEDED,
    ERR_INVALID_STATE,
    fail,
)
from services import common

REQUEST_KINDS = ("BATCH", "QUEUEABLE", "SCHEDULED", calculations.SNAPSHOT_START_KIND)


def _edges(graph):
    edges = {}
    known = set()
    for entry in graph:
        node = entry["node"]
        known.add(node)
        edges.setdefault(node, [])
        for target in entry.get("calls", []):
            known.add(target)
            edges[node].append(target)
    for node in known:
        edges.setdefault(node, [])
    return edges


def _reachable(edges):
    """Nodes reachable from a root, with their callout depth."""
    incoming = {node: 0 for node in edges}
    for node, targets in edges.items():
        for target in targets:
            if target in incoming:
                incoming[target] += 1
    roots = [node for node, count in incoming.items() if count == 0]
    depth = {}
    frontier = []
    for root in roots:
        depth[root] = 0
        frontier.append(root)
    while frontier:
        node = frontier.pop(0)
        for target in edges.get(node, []):
            candidate = depth[node] + 1
            if target not in depth or candidate > depth[target]:
                depth[target] = candidate
                frontier.append(target)
    return depth


def graph_metrics(graph):
    """Return (depth, cell_count) for a callout graph.

    The cell count is the number of nodes reachable from a root node — nodes at
    a callout depth of at least one; nodes at depth zero are counted in the
    scope instead and are excluded from the callout multiplier (PRD §3.8).  So
    for the two-node chain syncA -> syncB, syncA sits at depth 1 and is charged
    while syncB is the root and is not, matching the PRD's worked example in
    which a scope count of 5 with two callout nodes projects 260 units, not 510.
    Depth is the longest callout path measured in links and is zero for an empty
    graph.
    """
    if not graph:
        return 0, 0
    edges = _edges(graph)
    depth = _reachable(edges)
    callout_depth = max(depth.values()) if depth else 0
    cells = sum(1 for value in depth.values() if value >= 1)
    return callout_depth, cells


def has_cycle(graph):
    edges = _edges(graph)
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {}

    def visit(node):
        state = colour.get(node, WHITE)
        if state == GREY:
            return True
        if state == BLACK:
            return False
        colour[node] = GREY
        for target in edges.get(node, []):
            if visit(target):
                return True
        colour[node] = BLACK
        return False

    for node in list(edges):
        if visit(node):
            return True
    return False


def governor_cost_projection(request):
    graph = request.get("callout_graph", [])
    _, cells = graph_metrics(graph)
    units = (
        request["scope_count"] * calculations.BATCH_SCOPE_COST_UNITS
        + cells * calculations.CALLOUT_CELL_COST_UNITS
    )
    request["projected_governor_units"] = units
    request["governor_headroom_units"] = calculations.ORG_GOVERNOR_CEILING_UNITS - units
    return request


def create_request(actor, env, b):
    from validate import optional_int, parse_callout_graph, require_enum, require_int

    request_kind = require_enum(b, "request_kind", REQUEST_KINDS)
    scope_count = require_int(b, "scope_count", min_value=0)
    callout_graph = parse_callout_graph(
        b.value("callout_graph") if b.has("callout_graph") else []
    )
    max_concurrent_jobs = optional_int(
        b, "max_concurrent_jobs", min_value=1,
        default=calculations.DEFAULT_MAX_CONCURRENT_JOBS,
    )

    request = db.create(
        db.governor_requests,
        {
            "environment_id": env["id"],
            "request_kind": request_kind,
            "scope_count": scope_count,
            "callout_graph": callout_graph,
            "max_concurrent_jobs": max_concurrent_jobs,
            "status": "DRAFT",
            "projected_governor_units": 0,
            "governor_headroom_units": calculations.ORG_GOVERNOR_CEILING_UNITS,
        },
    )
    governor_cost_projection(request)
    db.touch(env)

    from services import environments

    environments.payment_layer_total(env)
    return request


def submit_request(actor, request):
    env = common.get_environment(request["environment_id"])

    if request["status"] != "DRAFT":
        fail(ERR_INVALID_STATE, "The governor-limit request is not DRAFT.")

    # The graph must be acyclic before the concurrent-submission ceiling is
    # checked, and must be no deeper than the sixth callout level.
    if has_cycle(request.get("callout_graph", [])):
        fail(ERR_CYCLE_DETECTED, "The callout graph contains a cycle.")

    depth, _ = graph_metrics(request.get("callout_graph", []))
    if depth > calculations.CALLOUT_DEPTH_CELL_LIMIT:
        fail(
            ERR_GOVERNOR_LIMIT_EXCEEDED,
            "The callout graph is deeper than the permitted six levels.",
        )

    submitted = sum(
        1
        for row in db.governor_requests.values()
        if row["environment_id"] == env["id"] and row["status"] == "SUBMITTED"
    )
    if submitted >= request["max_concurrent_jobs"]:
        fail(
            ERR_GOVERNOR_LIMIT_EXCEEDED,
            "The environment already holds the maximum concurrent SUBMITTED requests.",
        )

    request["status"] = "SUBMITTED"
    governor_cost_projection(request)
    db.touch(request)
    return request


def approve_request(actor, request):
    env = common.get_environment(request["environment_id"])

    if request["status"] != "SUBMITTED":
        fail(ERR_INVALID_STATE, "The governor-limit request is not SUBMITTED.")

    governor_cost_projection(request)
    others = sum(
        row["projected_governor_units"]
        for row in db.governor_requests.values()
        if row["environment_id"] == env["id"]
        and row["status"] == "ACCEPTED"
        and row["id"] != request["id"]
    )
    total = request["projected_governor_units"] + others
    if total > calculations.ORG_GOVERNOR_CEILING_UNITS:
        fail(
            ERR_GOVERNOR_LIMIT_EXCEEDED,
            "The projected governor units exceed the organization-wide ceiling.",
        )

    request["status"] = "ACCEPTED"
    request["governor_headroom_units"] = calculations.ORG_GOVERNOR_CEILING_UNITS - total
    db.touch(request)
    return request


def reject_request(actor, request):
    if request["status"] != "SUBMITTED":
        fail(ERR_INVALID_STATE, "The governor-limit request is not SUBMITTED.")

    request["status"] = "REJECTED"
    db.touch(request)
    return request


def reopen_request(actor, request):
    if request["status"] != "REJECTED":
        fail(ERR_INVALID_STATE, "The governor-limit request is not REJECTED.")

    request["status"] = "DRAFT"
    db.touch(request)
    return request