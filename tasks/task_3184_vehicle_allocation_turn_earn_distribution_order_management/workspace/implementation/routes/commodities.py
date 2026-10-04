"""Commodities, restrictions, DealerModelLine reads (PRD §3.2, §3.13)."""
from flask import Blueprint, request

import errors as err
from db import get_store
from middleware import auth_context
from response import success_list, success_object
from util import (bump, new_entity, now_dt, opt_bool, opt_ts, parse_dt,
                  req_int, req_str, req_ts, sweep_all_restrictions,
                  sweep_restriction)

bp = Blueprint("commodities", __name__)

ALL_READ = ["RegionalAllocator", "Dealer", "ProductionScheduler",
            "LogisticsCoordinator", "CommodityManager"]
COMM_ONLY = ["CommodityManager"]
DML_READ = ["RegionalAllocator", "Dealer", "ProductionScheduler"]


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


# ---------------------------------------------------------------------------
# Commodities (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.post("/wholesale/commodities")
def create_commodity():
    auth_context(COMM_ONLY)
    body = _body()
    code = req_str(body, "code")
    name = req_str(body, "name")
    for c in get_store("commodities").values():
        if c["code"] == code:
            raise err.duplicate("commodity code already exists")
    commodity = new_entity({"code": code, "name": name, "status": "CONSTRAINED"})
    get_store("commodities")[commodity["id"]] = commodity
    return success_object(commodity, 201)


@bp.get("/wholesale/commodities")
def list_commodities():
    auth_context(ALL_READ)
    rows = list(get_store("commodities").values())
    if request.args.get("status"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.post("/wholesale/commodities/<cid>/resolve")
def resolve_commodity(cid):
    auth_context(COMM_ONLY)
    commodity = get_store("commodities").get(cid)
    if commodity is None:
        raise err.not_found("commodity not found")
    if commodity["status"] != "CONSTRAINED":
        raise err.invalid_state("commodity is not CONSTRAINED")
    commodity["status"] = "RESOLVED"
    bump(commodity)
    # Cascade: every ACTIVE restriction on this commodity -> EXPIRED (§3.2).
    for r in get_store("commodity_restrictions").values():
        if r["commodity_id"] == cid and r["status"] == "ACTIVE":
            r["status"] = "EXPIRED"
            bump(r)
    return success_object(commodity)


@bp.post("/wholesale/commodities/<cid>/constrain")
def constrain_commodity(cid):
    auth_context(COMM_ONLY)
    commodity = get_store("commodities").get(cid)
    if commodity is None:
        raise err.not_found("commodity not found")
    if commodity["status"] != "RESOLVED":
        raise err.invalid_state("commodity is not RESOLVED")
    commodity["status"] = "CONSTRAINED"
    bump(commodity)
    return success_object(commodity)


# ---------------------------------------------------------------------------
# Commodity restrictions (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.post("/wholesale/commodity-restrictions")
def create_restriction():
    auth_context(COMM_ONLY)
    sweep_all_restrictions()
    body = _body()
    commodity_id = req_str(body, "commodity_id")
    model_line_id = req_str(body, "model_line_id")
    effective_from = req_ts(body, "effective_from")
    effective_to = opt_ts(body, "effective_to")
    install_rate_pct = req_int(body, "install_rate_pct", 0, 100)
    allow_partial_build = opt_bool(body, "allow_partial_build", False)

    if commodity_id not in get_store("commodities"):
        raise err.not_found("commodity not found")
    if model_line_id not in get_store("model_lines"):
        raise err.not_found("model line not found")
    if effective_to is not None and parse_dt(effective_to) <= parse_dt(effective_from):
        raise err.validation("effective_to must be strictly after effective_from")

    # Overlap rule (§3.2): a new window overlapping the ACTIVE window for the
    # same pair without fully superseding is rejected.
    new_from = parse_dt(effective_from)
    new_to = parse_dt(effective_to) if effective_to is not None else None
    for existing in get_store("commodity_restrictions").values():
        if (existing["commodity_id"] == commodity_id
                and existing["model_line_id"] == model_line_id
                and existing["status"] == "ACTIVE"):
            old_from = parse_dt(existing["effective_from"])
            old_to = (parse_dt(existing["effective_to"])
                      if existing["effective_to"] is not None else None)
            overlaps = new_from < old_to if old_to is not None else True
            if overlaps:
                # Fully-superseding replacement: starts no later than the old
                # window start (end-exclusive windows).
                if new_from > old_from:
                    raise err.restriction_overlap(
                        "new window overlaps the ACTIVE window for the pair")
                existing["status"] = "SUPERSEDED"
                bump(existing)
            else:
                # Adjacent / later window: still supersedes the prior ACTIVE row.
                existing["status"] = "SUPERSEDED"
                bump(existing)

    restriction = new_entity({
        "commodity_id": commodity_id,
        "model_line_id": model_line_id,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "install_rate_pct": install_rate_pct,
        "allow_partial_build": allow_partial_build,
        "status": "ACTIVE",
    })
    get_store("commodity_restrictions")[restriction["id"]] = restriction
    return success_object(restriction, 201)


@bp.get("/wholesale/commodity-restrictions")
def list_restrictions():
    auth_context(["RegionalAllocator", "Dealer", "ProductionScheduler",
                  "CommodityManager"])
    sweep_all_restrictions()
    rows = list(get_store("commodity_restrictions").values())
    for key in ("commodity_id", "model_line_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/commodity-restrictions/<rid>")
def get_restriction(rid):
    auth_context(["RegionalAllocator", "Dealer", "ProductionScheduler",
                  "CommodityManager"])
    restriction = get_store("commodity_restrictions").get(rid)
    if restriction is None:
        raise err.not_found("restriction not found")
    sweep_restriction(restriction)
    return success_object(restriction)


# ---------------------------------------------------------------------------
# DealerModelLine reads (PRD §3.13)
# ---------------------------------------------------------------------------

@bp.get("/wholesale/dealer-model-lines")
def list_dealer_model_lines():
    auth_context(DML_READ)
    rows = list(get_store("dealer_model_lines").values())
    for key in ("dealer_id", "model_line_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/dealer-model-lines/<did>")
def get_dealer_model_line(did):
    auth_context(DML_READ)
    dml = get_store("dealer_model_lines").get(did)
    if dml is None:
        raise err.not_found("dealer-model-line not found")
    return success_object(dml)
