"""Kiosk upsell and combo suggestion rules (PRD 3.6)."""
from flask import Blueprint

import auth
import constants as C
import response
import serialize
import shapes
from db import DB, new_row
from errors import fail
from routes.common import fk, listing, path_row

bp = Blueprint("upsell", __name__)

READ_ROLES = ("PlatformAdmin", "ContentManager", "ComplianceOfficer", "StoreOperator")


def _closes_cycle(cluster_id, trigger_id, suggested_id):
    """The suggestion edges of one cluster's ACTIVE rules must stay acyclic."""
    edges = {}
    for rule in DB.upsell_rules.values():
        if rule.get("cluster_id") != cluster_id or rule.get("state") != "ACTIVE":
            continue
        edges.setdefault(rule["trigger_item_id"], []).append(rule["suggested_item_id"])
    seen = set()
    stack = [suggested_id]
    while stack:
        node = stack.pop()
        if node == trigger_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, []))
    return False


@bp.post("/upsell-rules")
def create_rule():
    auth.enter(["ContentManager"])
    data = shapes.body()
    cluster_id = fk(data, "cluster_id", "clusters")
    trigger_id = fk(data, "trigger_item_id", "menu_items")
    suggested_id = fk(data, "suggested_item_id", "menu_items")
    if cluster_id is None:
        shapes.req_str(data, "cluster_id", 1, None)
    if trigger_id is None:
        shapes.req_str(data, "trigger_item_id", 1, None)
    if suggested_id is None:
        shapes.req_str(data, "suggested_item_id", 1, None)
    kind = shapes.req_enum(data, "rule_kind", C.RULE_KINDS)
    minimum = shapes.opt_int(data, "min_cart_subtotal_cents", 0, None, 0)
    slot = shapes.req_int(data, "suggestion_slot", 1, 3)
    prompt = shapes.req_int(data, "max_prompt_seconds", 1, 60)
    if prompt < C.MIN_PROMPT_SECONDS:
        fail("ERR_INVALID_REQUEST", "max_prompt_seconds must be at least 5")
    for rule in DB.upsell_rules.values():
        if (rule.get("state") == "ACTIVE" and rule.get("cluster_id") == cluster_id
                and rule.get("trigger_item_id") == trigger_id
                and rule.get("suggestion_slot") == slot):
            fail("ERR_DUPLICATE_NATURAL_KEY", "this trigger already occupies that slot")
    if trigger_id == suggested_id or _closes_cycle(cluster_id, trigger_id, suggested_id):
        fail("ERR_UPSELL_CYCLE_DETECTED", "the rule would close a suggestion cycle")
    row = new_row({
        "cluster_id": cluster_id,
        "trigger_item_id": trigger_id,
        "suggested_item_id": suggested_id,
        "rule_kind": kind,
        "min_cart_subtotal_cents": minimum,
        "suggestion_slot": slot,
        "max_prompt_seconds": prompt,
        "state": "ACTIVE",
        "suspended_reason": None,
    })
    DB.upsell_rules[row["id"]] = row
    return response.created(serialize.dump("upsell_rule", row))


@bp.get("/upsell-rules")
def list_rules():
    auth.enter(READ_ROLES)
    return listing("upsell_rules", "upsell_rule")


@bp.get("/upsell-rules/<rule_id>")
def get_rule(rule_id):
    auth.enter(READ_ROLES)
    row = path_row("upsell_rules", rule_id)
    return response.ok(serialize.dump("upsell_rule", row))
