"""Agents, the hierarchy, departure lifecycle and portfolio transfer (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint, g

from apierrors import fail
from auth import authorize, scope_list_filter, scope_self
from calc import (
    apply_hold_cascade,
    children_of_agent,
    departure_vested_buyout,
    descendant_ids,
    merchants_of_agent,
    recompute_hierarchy_depth,
    recompute_statement,
    subtree_relative_depth,
    system_adjustment,
    upsert_statement,
    vesting_pct_at_clock,
)
from envelope import apply_filters, list_response, object_response
from serial import agent as ser_agent
from serial import portfolio_summary as ser_portfolio
from shapes import (
    as_date,
    as_decimal,
    as_id,
    as_str,
    body,
    check_pct_range,
    present,
    supplied,
)
from store import (
    MAX_HIERARCHY_DEPTH,
    db,
    month_of_date,
    new_id,
    ordered,
    parse_date,
    stamp_new,
    touch,
)

bp = Blueprint("agents", __name__)


def _lookup(agent_id):
    row = db.agents.get(agent_id)
    if row is None:
        fail("ERR_AGENT_NOT_FOUND", "no agent with id %s" % agent_id)
    return row


def _check_monotonic(agent_id, parent_id, split_pct, override_pct):
    """PRD 3.2: parent.override_pct >= max(child.split_pct, child.override_pct)."""
    if parent_id:
        parent = db.agents.get(parent_id)
        if parent is not None and parent["override_pct"] < max(split_pct, override_pct):
            fail(
                "ERR_OVERRIDE_PCT_NOT_MONOTONIC",
                "parent override_pct must be at least max(split_pct, override_pct)",
            )
    if agent_id is not None:
        for child in children_of_agent(agent_id):
            if override_pct < max(child["split_pct"], child["override_pct"]):
                fail(
                    "ERR_OVERRIDE_PCT_NOT_MONOTONIC",
                    "override_pct must be at least max(split_pct, override_pct) of every child",
                )


@bp.route("/agents", methods=["POST"])
def create_agent():
    authorize("IsoAdmin")
    payload = body()
    # band 4 -- request shape
    name = as_str(payload, "name", min_len=1, max_len=120)
    split_pct = as_decimal(payload, "split_pct")
    override_pct = as_decimal(payload, "override_pct")
    vesting_start_date = as_date(payload, "vesting_start_date")
    parent_agent_id = as_id(payload, "parent_agent_id", required=False)
    # band 5 -- field domains
    check_pct_range(split_pct, "split_pct")
    check_pct_range(override_pct, "override_pct")
    # band 7 -- referenced entity existence
    parent = None
    if parent_agent_id is not None:
        parent = db.agents.get(parent_agent_id)
        if parent is None:
            fail("ERR_REFERENCED_AGENT_NOT_FOUND",
                 "no agent with id %s" % parent_agent_id)
        # band 9 -- state precondition on the referenced parent
        if parent["status"] != "ACTIVE":
            fail("ERR_AGENT_STATE_INVALID", "the parent agent must be ACTIVE")
    # band 12 -- business constraints
    depth = 0 if parent is None else parent["hierarchy_depth"] + 1
    if depth > MAX_HIERARCHY_DEPTH:
        fail("ERR_HIERARCHY_DEPTH_EXCEEDED",
             "hierarchy_depth may not exceed %d" % MAX_HIERARCHY_DEPTH)
    _check_monotonic(None, parent_agent_id, split_pct, override_pct)
    row = {
        "id": new_id(),
        "name": name,
        "parent_agent_id": parent_agent_id,
        "split_pct": split_pct,
        "override_pct": override_pct,
        "vesting_start_date": vesting_start_date,
        "status": "ACTIVE",
        "departure_effective_date": None,
        "hierarchy_depth": depth,
        "vested_pct_at_departure": None,
    }
    stamp_new(row)
    db.agents[row["id"]] = row
    return object_response(ser_agent(row), 201)


@bp.route("/agents", methods=["GET"])
def list_agents():
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    rows = apply_filters(
        list(db.agents.values()),
        [("status", "status"), ("parent_agent_id", "parent_agent_id")])
    return list_response(ordered(rows), ser_agent)


@bp.route("/agents/<agent_id>", methods=["GET"])
def get_agent(agent_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    scope_self(agent_id)
    return object_response(ser_agent(_lookup(agent_id)))


@bp.route("/agents/<agent_id>", methods=["PATCH"])
def patch_agent(agent_id):
    authorize("IsoAdmin")
    payload = body()
    # band 4
    name = as_str(payload, "name", required=False, min_len=1, max_len=120)
    split_pct = as_decimal(payload, "split_pct", required=False)
    override_pct = as_decimal(payload, "override_pct", required=False)
    vesting_start_date = as_date(payload, "vesting_start_date", required=False)
    new_parent_id = as_id(payload, "parent_agent_id", required=False)
    # band 5
    check_pct_range(split_pct, "split_pct")
    check_pct_range(override_pct, "override_pct")
    # band 6
    row = _lookup(agent_id)
    reparenting = supplied(payload, "parent_agent_id")
    parent = None
    if reparenting and new_parent_id is not None:
        # band 7
        parent = db.agents.get(new_parent_id)
        if parent is None:
            fail("ERR_REFERENCED_AGENT_NOT_FOUND", "no agent with id %s" % new_parent_id)
        # band 9
        if parent["status"] != "ACTIVE":
            fail("ERR_AGENT_STATE_INVALID", "the parent agent must be ACTIVE")
    # band 12 -- cycle, then depth, then override monotonicity
    effective_parent_id = new_parent_id if reparenting else row.get("parent_agent_id")
    if reparenting and new_parent_id is not None:
        if new_parent_id == agent_id or new_parent_id in descendant_ids(agent_id):
            fail("ERR_HIERARCHY_CYCLE",
                 "an agent may not be re-parented under itself or its own descendant")
    if reparenting:
        base_depth = 0 if new_parent_id is None else db.agents[new_parent_id]["hierarchy_depth"] + 1
        if base_depth + subtree_relative_depth(agent_id) > MAX_HIERARCHY_DEPTH:
            fail("ERR_HIERARCHY_DEPTH_EXCEEDED",
                 "hierarchy_depth may not exceed %d" % MAX_HIERARCHY_DEPTH)
    effective_split = split_pct if present(payload, "split_pct") else row["split_pct"]
    effective_override = (
        override_pct if present(payload, "override_pct") else row["override_pct"])
    _check_monotonic(agent_id, effective_parent_id, effective_split, effective_override)
    if present(payload, "name"):
        row["name"] = name
    if present(payload, "split_pct"):
        row["split_pct"] = split_pct
    if present(payload, "override_pct"):
        row["override_pct"] = override_pct
    if present(payload, "vesting_start_date"):
        row["vesting_start_date"] = vesting_start_date
    if reparenting:
        row["parent_agent_id"] = new_parent_id
        recompute_hierarchy_depth(row)
    touch(row)
    return object_response(ser_agent(row))


@bp.route("/agents/<agent_id>/portfolio-summary", methods=["GET"])
def get_portfolio_summary(agent_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    scope_self(agent_id)
    return object_response(ser_portfolio(_lookup(agent_id)))


@bp.route("/agents/<agent_id>/notice", methods=["POST"])
def file_notice(agent_id):
    authorize("IsoAdmin")
    payload = body()
    # band 4
    departure_effective_date = as_date(payload, "departure_effective_date")
    # band 6
    row = _lookup(agent_id)
    # band 9
    if row["status"] != "ACTIVE":
        fail("ERR_AGENT_STATE_INVALID", "a notice may only be filed from ACTIVE")
    # band 11 -- a notice cannot be backdated
    if parse_date(departure_effective_date) < db.today():
        fail("ERR_DEPARTURE_DATE_OUT_OF_RANGE",
             "departure_effective_date must be on or after the current logical date")
    row["status"] = "DEPARTURE_NOTICE"
    row["departure_effective_date"] = departure_effective_date
    touch(row)
    return object_response(ser_agent(row))


@bp.route("/agents/<agent_id>/rescind-notice", methods=["POST"])
def rescind_notice(agent_id):
    authorize("IsoAdmin")
    row = _lookup(agent_id)
    if row["status"] != "DEPARTURE_NOTICE":
        fail("ERR_AGENT_STATE_INVALID", "only a DEPARTURE_NOTICE may be rescinded")
    row["status"] = "ACTIVE"
    row["departure_effective_date"] = None
    touch(row)
    return object_response(ser_agent(row))


@bp.route("/agents/<agent_id>/depart", methods=["POST"])
def depart_agent(agent_id):
    authorize("IsoAdmin")
    # band 6
    row = _lookup(agent_id)
    # band 9
    if row["status"] != "DEPARTURE_NOTICE":
        fail("ERR_AGENT_STATE_INVALID", "departure completes only from DEPARTURE_NOTICE")
    # band 11
    effective = parse_date(row.get("departure_effective_date") or "")
    if effective is not None and db.today() < effective:
        fail("ERR_DEPARTURE_DATE_OUT_OF_RANGE",
             "the logical clock has not yet reached departure_effective_date")
    frozen = vesting_pct_at_clock(row)
    # the buyout window looks only at ISSUED/FINALIZED statements, so it is
    # evaluated before the departure-month statement is upserted.
    buyout = departure_vested_buyout(row, frozen)
    row["status"] = "DEPARTED"
    row["vested_pct_at_departure"] = frozen
    if buyout > 0 and effective is not None:
        statement, created = upsert_statement(agent_id, month_of_date(effective))
        system_adjustment(statement, "VESTED_BUYOUT", buyout)
        recompute_statement(statement)
        if not created:
            touch(statement)
    touch(row)
    return object_response(ser_agent(row))


@bp.route("/agents/<agent_id>/transfer-portfolio", methods=["POST"])
def transfer_portfolio(agent_id):
    authorize("IsoAdmin")
    payload = body()
    # band 4
    target_agent_id = as_id(payload, "target_agent_id")
    # band 6
    row = _lookup(agent_id)
    # band 7
    target = db.agents.get(target_agent_id)
    if target is None:
        fail("ERR_REFERENCED_AGENT_NOT_FOUND", "no agent with id %s" % target_agent_id)
    # band 9
    if row["status"] != "DEPARTED":
        fail("ERR_AGENT_STATE_INVALID", "a portfolio may only be transferred from DEPARTED")
    # band 12
    if target["status"] != "ACTIVE" or target_agent_id == agent_id:
        fail("ERR_TRANSFER_TARGET_INVALID",
             "the target agent must be a different ACTIVE agent")
    for merchant in merchants_of_agent(agent_id):
        if merchant["status"] not in ("PENDING", "ACTIVE"):
            continue
        merchant["owning_agent_id"] = target_agent_id
        touch(merchant)
    touch(row)
    touch(target)
    return object_response(ser_agent(row))
