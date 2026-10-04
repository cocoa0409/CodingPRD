"""Supplier pools: creation, temperature, stage machine and ranking surface."""

import calc
import constants as K
from auth import roles
from error import CatalogError, ERR_INVALID_STATE
from envelope import created, ok, page
from rules import check_state, resource_or_404
from services import declared_node_state, recompute_node, serialize
from store import DB
from util import by_created, paginate, require, require_enum

GROUP = "supply"


def _create(caller):
    from flask import request
    body = request.raw_payload or {}
    product = resource_or_404("products", require(body, "product_sku_id"), "accelerator product")
    node = DB.mint({
        "node_code": require(body, "node_code"),
        "product_sku_id": product["id"],
        "node_region": require_enum(require(body, "node_region"), K.NODE_REGIONS, "node_region"),
        "capacity_units": require(body, "capacity_units", "int"),
        "requested_hotness_tier": require_enum(
            require(body, "requested_hotness_tier"), K.HOTNESS_TIERS, "requested_hotness_tier"
        ),
        "held_units": 0,
        "stage": "OPEN",
        "friction_penalty_score": 0.0,
        "total_committed_rate": 0.0,
        "committed_fee_cents": 0,
    })
    declared_node_state(node)
    DB.nodes[node["id"]] = node
    return created(serialize(node))


def _list(caller):
    from flask import request
    rows = by_created(list(DB.nodes.values()))
    product_sku_id = request.args.get("product_sku_id")
    if product_sku_id:
        product = DB.products.get(product_sku_id)
        if product is not None:
            rows = [row for row in rows if row.get("product_sku_id") == product["id"]]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read(caller, node_id):
    return ok(serialize(resource_or_404("nodes", node_id, "supply node")))


def _rank(caller, node_id):
    node = resource_or_404("nodes", node_id, "supply node")
    candidates = _candidate_holds(node)
    ordered = calc.allocation_priority_ranking(DB, candidates)
    return ok([serialize(hold) for hold in ordered])


def _candidate_holds(node):
    ceiling = node.get("temp_band_ceiling", "COOL")
    rows = []
    for hold in DB.holds.values():
        if hold.get("product_sku_id") != node.get("product_sku_id"):
            continue
        if hold.get("state") != "REQUESTED":
            continue
        tier = hold.get("hold_friction_tier", "COOL")
        if K.TIER_INDEX[tier] > K.TIER_INDEX[ceiling]:
            continue
        rows.append((hold, node))
    return rows


def _stage(caller, node_id):
    from flask import request
    node = resource_or_404("nodes", node_id, "supply node")
    body = request.raw_payload or {}
    target = require_enum(require(body, "target_stage"), K.NODE_STAGES, "target_stage")
    _transition_stage(node, target)
    return ok(serialize(node))


def _transition_stage(node, target):
    current = node.get("stage")
    if current == target:
        raise CatalogError(ERR_INVALID_STATE, "The pool is already in %s." % target)
    if current == "OPEN" and target == "DRAINING":
        if int(node.get("held_units", 0)) != 0:
            raise CatalogError(ERR_INVALID_STATE, "A pool with held units cannot be drained.")
        node["stage"] = "DRAINING"
    elif current == "DRAINING" and target == "BINDING":
        if float(node.get("friction_penalty_score", 0.0)) > K.FRICTION_BINDING_MAX_SCORE:
            raise CatalogError(ERR_INVALID_STATE, "The friction score is too high to bind.")
        node["stage"] = "BINDING"
        recompute_node(node, settle=True)
        return
    elif current == "BINDING" and target == "OPEN":
        node["stage"] = "OPEN"
        node["friction_penalty_score"] = 0.0
    elif current == "FRICTION_HOLD" and target == "OPEN":
        # The cycle is repeatable: a friction-hold pool may be reopened, which
        # clears its accumulated friction score (PRD 3.3).
        node["stage"] = "OPEN"
        node["friction_penalty_score"] = 0.0
    else:
        raise CatalogError(ERR_INVALID_STATE, "The pool cannot move from %s to %s." % (current, target))
    DB.touch(node)


def _drain(caller, node_id):
    node = resource_or_404("nodes", node_id, "supply node")
    check_state(node, "OPEN")
    _transition_stage(node, "DRAINING")
    return ok(serialize(node))


def _bind(caller, node_id):
    node = resource_or_404("nodes", node_id, "supply node")
    _transition_stage(node, "BINDING")
    return ok(serialize(node))


def _penalties(caller):
    from flask import request
    rows = by_created(list(DB.penalties.values()))
    for field, column in (("supply_node_id", "supply_node_id"), ("partner_id", "partner_id"), ("hold_id", "hold_id")):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row.get(column) == value]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read_penalty(caller, penalty_id):
    return ok(serialize(resource_or_404("penalties", penalty_id, "friction penalty")))


ROUTES = [
    ("POST", "/accelerators/supply-nodes", _create, ("SupplyPlanner",)),
    ("GET", "/accelerators/supply-nodes", _list, ("SupplyPlanner",)),
    ("GET", "/accelerators/supply-nodes/<node_id>", _read, ("SupplyPlanner",)),
    ("POST", "/accelerators/supply-nodes/<node_id>/rank", _rank, ("SupplyPlanner",)),
    ("POST", "/accelerators/supply-nodes/<node_id>/stage", _stage, ("SupplyPlanner",)),
    ("POST", "/accelerators/supply-nodes/<node_id>/drain", _drain, ("SupplyPlanner",)),
    ("POST", "/accelerators/supply-nodes/<node_id>/bind", _bind, ("SupplyPlanner",)),
    ("GET", "/accelerators/friction-penalties", _penalties, ("SupplyPlanner",)),
    ("GET", "/accelerators/friction-penalties/<penalty_id>", _read_penalty, ("SupplyPlanner",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])