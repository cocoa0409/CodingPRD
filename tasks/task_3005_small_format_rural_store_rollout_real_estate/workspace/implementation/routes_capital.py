"""Cannibalization studies and capital projects."""
from flask import Blueprint, request

from db import DB, now_iso
from errors import ApiError, err_invalid_request, err_validation
from middleware import require_roles, get_body, get_user_id, opt_int
from response import success, parse_pagination, paginate
from services import (base_entity, touch, compute_study, compute_study_symmetric,
                      compute_new_build_cost, compute_capital_score, effective_cost,
                      recompute_capital, recompute_ranks)
from helpers import (pub, pub_list, sorted_by_creation, body_rollout, require_active)

bp = Blueprint("capital", __name__)

ALL = ("PROGRAM_ADMIN", "REAL_ESTATE_MANAGER", "NETWORK_PLANNER",
       "OPERATIONS_LEAD", "FINANCE_ANALYST")
FA = ("FINANCE_ANALYST",)
ADMIN = ("PROGRAM_ADMIN",)
KINDS = ("REMODEL", "RELOCATION", "NEW_BUILD")


# ---- cannibalization studies --------------------------------------------------------

@bp.post("/rollouts/cannibalization-studies")
def create_study():
    require_roles(*FA)
    body = get_body()
    program = body_rollout(body)
    store_id = body.get("store_id")
    if not isinstance(store_id, str):
        raise err_invalid_request("store_id is required")
    entries = body.get("overlap_entries")
    if not isinstance(entries, list) or len(entries) == 0:
        raise err_invalid_request("overlap_entries must be a non-empty array")
    seen = set()
    for e in entries:
        if not isinstance(e, dict):
            raise err_invalid_request("overlap entries must be objects")
        esid = e.get("existing_store_id")
        if not isinstance(esid, str):
            raise err_invalid_request("existing_store_id is required")
        w = e.get("overlap_weight")
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            raise err_invalid_request("overlap_weight must be a number")
        if w <= 0 or w > 1:
            raise err_validation("overlap_weight must be in (0, 1]")
        if esid in seen:
            raise err_invalid_request("duplicate existing_store_id in overlap_entries")
        seen.add(esid)

    store = DB.stores.get(store_id)
    if store is None or store["rollout_program_id"] != program["id"]:
        raise ApiError("ERR_BAD_REFERENCE", "store not found in program")
    require_active(program)

    for e in entries:
        es = DB.stores.get(e["existing_store_id"])
        if es is None or es["rollout_program_id"] != program["id"]:
            raise ApiError("ERR_BAD_REFERENCE",
                           "overlap store must exist in the same program")
        if es["status"] not in ("OPEN", "EXISTING"):
            raise ApiError("ERR_BAD_REFERENCE",
                           "overlap store must be OPEN or EXISTING")
        if es.get("open_year_sales_cents") is None:
            raise ApiError("ERR_BAD_REFERENCE",
                           "overlap store must have open_year_sales_cents recorded")

    for st in DB.studies.values():
        if st["store_id"] == store_id and st["status"] in ("DRAFT", "FINAL"):
            st["status"] = "SUPERSEDED"
            touch(st)

    entries_out, total, transfer_pct, rec = compute_study(
        store, entries, program["cannibalization_coefficient"])
    st = base_entity()
    st.update({
        "rollout_program_id": program["id"],
        "store_id": store_id,
        "overlap_entries": entries_out,
        "transfer_pct": transfer_pct,
        "total_transferred_cents": total,
        "recommendation": rec,
        "status": "DRAFT",
    })
    DB.studies[st["id"]] = st
    return success(pub(st), 201)


@bp.get("/rollouts/cannibalization-studies")
def list_studies():
    require_roles(*ALL)
    items = list(DB.studies.values())
    q = request.args
    if q.get("rollout_program_id") is not None:
        items = [s for s in items if s["rollout_program_id"] == q["rollout_program_id"]]
    if q.get("store_id") is not None:
        items = [s for s in items if s["store_id"] == q["store_id"]]
    if q.get("status") is not None:
        items = [s for s in items if s["status"] == q["status"]]
    items = sorted_by_creation(items)
    limit, offset = parse_pagination(q)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/cannibalization-studies/<csid>")
def get_study_by_id(csid):
    require_roles(*ALL)
    from helpers import get_study
    st = get_study(csid)
    out = pub(st)
    if request.args.get("variant") == "symmetric_overlap":
        store = DB.stores[st["store_id"]]
        program = DB.rollouts[st["rollout_program_id"]]
        out["symmetric_overlap"] = compute_study_symmetric(
            store, st["overlap_entries"], program["cannibalization_coefficient"])
    return success(out, 200)


@bp.post("/rollouts/cannibalization-studies/<csid>/finalize")
def finalize_study(csid):
    require_roles(*FA)
    from helpers import get_study
    st = get_study(csid)
    body = get_body()
    body_rollout(body, expected_pid=st["rollout_program_id"])
    if st["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "only a DRAFT study may be finalized")
    if st["recommendation"] == "BLOCKED":
        raise ApiError("ERR_CANNIBALIZATION_BLOCKED",
                       "study recommendation is BLOCKED; finalize forbidden")
    st["status"] = "FINAL"
    touch(st)
    return success(pub(st), 200)


# ---- capital projects ------------------------------------------------------------------

@bp.post("/rollouts/capital-projects")
def create_project():
    require_roles(*FA)
    body = get_body()
    program = body_rollout(body)
    kind = body.get("kind")
    if kind is None or kind not in KINDS:
        raise err_invalid_request("kind must be one of REMODEL, RELOCATION, NEW_BUILD")
    store_id = body.get("store_id")
    if not isinstance(store_id, str):
        raise err_invalid_request("store_id is required")
    pc = opt_int(body, "project_cost_cents")
    rc = opt_int(body, "remodel_cost_cents")
    uplift = opt_int(body, "projected_uplift_cents")

    store = DB.stores.get(store_id)
    if store is None or store["rollout_program_id"] != program["id"]:
        raise ApiError("ERR_BAD_REFERENCE", "subject store not found in program")

    if kind in ("REMODEL", "RELOCATION"):
        if store["status"] != "EXISTING":
            raise ApiError("ERR_BAD_REFERENCE",
                           "REMODEL/RELOCATION require an EXISTING store")
    else:
        if store["status"] != "PROPOSED":
            raise ApiError("ERR_BAD_REFERENCE",
                           "NEW_BUILD requires a PROPOSED store")
        for ag in DB.agreements.values():
            if ag["store_id"] == store_id and ag["status"] in ("ACTIVE", "EXECUTED"):
                raise ApiError("ERR_BAD_REFERENCE",
                               "NEW_BUILD store must have no ACTIVE/EXECUTED agreement")

    nbc = compute_new_build_cost(store) if kind == "NEW_BUILD" else 0
    p = base_entity()
    p.update({
        "rollout_program_id": program["id"],
        "kind": kind,
        "store_id": store_id,
        "project_cost_cents": pc,
        "remodel_cost_cents": rc,
        "projected_uplift_cents": uplift,
        "new_build_cost_cents": nbc,
        "capital_score": None,
        "status": "DRAFT",
        "decided_at": None,
        "rank": None,
        "submitted_by": None,
    })
    DB.capital_projects[p["id"]] = p
    return success(pub(p), 201)


@bp.get("/rollouts/capital-projects")
def list_projects():
    require_roles(*ALL)
    items = list(DB.capital_projects.values())
    q = request.args
    if q.get("rollout_program_id") is not None:
        items = [p for p in items if p["rollout_program_id"] == q["rollout_program_id"]]
    if q.get("kind") is not None:
        items = [p for p in items if p["kind"] == q["kind"]]
    if q.get("status") is not None:
        items = [p for p in items if p["status"] == q["status"]]
    if q.get("store_id") is not None:
        items = [p for p in items if p["store_id"] == q["store_id"]]
    items = sorted_by_creation(items)
    limit, offset = parse_pagination(q)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/capital-projects/<cpid>")
def get_project_by_id(cpid):
    require_roles(*ALL)
    from helpers import get_capital_project
    return success(pub(get_capital_project(cpid)), 200)


@bp.post("/rollouts/capital-projects/<cpid>/submit")
def submit_project(cpid):
    require_roles(*FA)
    from helpers import get_capital_project
    p = get_capital_project(cpid)
    body = get_body()
    program = body_rollout(body, expected_pid=p["rollout_program_id"])
    if p["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "only a DRAFT project may be submitted")
    require_active(program)

    cost = effective_cost(p)
    if p["kind"] == "REMODEL" and (p.get("remodel_cost_cents") or 0) <= 0:
        raise err_validation("remodel_cost_cents must be present and > 0 for REMODEL")
    if p["kind"] == "RELOCATION" and (p.get("project_cost_cents") or 0) <= 0:
        raise err_validation("project_cost_cents must be present and > 0 for RELOCATION")
    if p["kind"] == "NEW_BUILD":
        store = DB.stores[p["store_id"]]
        p["new_build_cost_cents"] = compute_new_build_cost(store)
        if p["new_build_cost_cents"] <= 0:
            raise err_validation("new_build_cost_cents must be > 0 for NEW_BUILD")
        has_final = any(
            s for s in DB.studies.values()
            if s["store_id"] == p["store_id"] and s["status"] == "FINAL")
        if not has_final:
            raise ApiError("ERR_STUDY_NOT_FINAL",
                           "NEW_BUILD submit requires a FINAL non-superseded study")
    p["capital_score"] = compute_capital_score(p, DB.stores[p["store_id"]])
    p["submitted_by"] = get_user_id()
    p["status"] = "SUBMITTED"
    touch(p)
    return success(pub(p), 200)


@bp.post("/rollouts/capital-projects/<cpid>/decide")
def decide_project(cpid):
    require_roles(*ADMIN)
    from helpers import get_capital_project
    p = get_capital_project(cpid)
    body = get_body()
    program = body_rollout(body, expected_pid=p["rollout_program_id"])
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise err_invalid_request("decision must be APPROVE or REJECT")
    if "expected_program_version" not in body or body["expected_program_version"] is None:
        raise err_invalid_request("expected_program_version is required")
    expected = body["expected_program_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_program_version must be an integer")
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "only a SUBMITTED project may be decided")
    require_active(program)
    if get_user_id() == p.get("submitted_by"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the deciding user must not be the submitting analyst")
    cost = effective_cost(p)
    if decision == "APPROVE" and cost > program["available_capital_cents"]:
        raise ApiError("ERR_CAPITAL_BUDGET_EXCEEDED",
                       "effective project cost exceeds available capital")
    if expected != program["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_program_version mismatch")
    p["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    p["decided_at"] = now_iso()
    touch(p)
    recompute_capital(program)
    touch(program)
    recompute_ranks(program["id"])
    return success(pub(p), 200)


@bp.post("/rollouts/capital-projects/<cpid>/cancel")
def cancel_project(cpid):
    require_roles(*FA)
    from helpers import get_capital_project
    p = get_capital_project(cpid)
    body = get_body()
    body_rollout(body, expected_pid=p["rollout_program_id"])
    if p["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "only DRAFT or SUBMITTED projects may be cancelled")
    p["status"] = "CANCELLED"
    touch(p)
    return success(pub(p), 200)
