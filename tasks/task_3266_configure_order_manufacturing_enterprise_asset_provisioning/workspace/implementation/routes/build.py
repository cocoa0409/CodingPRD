from flask import Blueprint, request
from db import STORE, new_entity, touch
from errors import (ApiError, err_invalid_request, err_invalid_state,
                    ERR_INSUFFICIENT_COMPONENT_STOCK, ERR_BUILD_OUT_OF_SEQUENCE,
                    ERR_SUBSTITUTION_INCOMPATIBLE, ERR_INVALID_STATE,
                    ERR_CREDIT_LIMIT_EXCEEDED)
from middleware import require_roles, require_ownership
from helpers import (get_json_body, require_field, get_pagination, paginate,
                     store_lookup, ser_build_job, ser_sub_request, ser_asset,
                     account_of_build_job, account_of_sub_request, chassis_of_line)
from response import success_object, success_list
from services.core import (required_components, rescore_queue, check_compatibility,
                           round_half_up_cents)

bp = Blueprint("build", __name__)


def _bubble_order_allocated(order_id):
    jobs = [j for j in STORE.build_jobs.values() if j["order_id"] == order_id]
    if jobs and all(j["status"] == "ALLOCATED" for j in jobs):
        order = STORE.orders.get(order_id)
        if order and order["build_status"] == "SUBMITTED":
            order["build_status"] = "ALLOCATED"
            touch(order)


def _effective_configuration(job):
    """Configuration with the job's substitution swap applied, if any."""
    line = STORE.order_lines.get(job["order_line_id"])
    if line is None:
        return None
    cfg = STORE.configurations.get(line["configuration_id"])
    if cfg is None:
        return None
    swap = job.get("swap")
    if not swap:
        return cfg
    selections = []
    for s in cfg["component_selections"]:
        if s["component_id"] == swap["original"]:
            selections.append({"component_id": swap["proposed"], "qty": s["qty"]})
        else:
            selections.append(dict(s))
    eff = dict(cfg)
    eff["component_selections"] = selections
    return eff


@bp.get("/api/build-jobs/<jid>")
def get_build_job(jid):
    uid, role = require_roles("PlatformAdmin", "FactoryOps", "AccountManager")
    job = store_lookup("build_jobs", jid)
    return success_object(ser_build_job(job))


@bp.get("/api/orders/<oid>/build-jobs")
def list_order_jobs(oid):
    uid, role = require_roles("PlatformAdmin", "FactoryOps", "AccountManager")
    store_lookup("orders", oid)
    limit, offset = get_pagination()
    items = [j for j in STORE.build_jobs.values() if j["order_id"] == oid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_build_job(j) for j in items], limit, offset, total)


@bp.get("/api/build-jobs")
def list_build_jobs():
    require_roles("PlatformAdmin", "FactoryOps")
    limit, offset = get_pagination()
    items = list(STORE.build_jobs.values())
    for f in ("order_line_id", "status", "shortage_component_id"):
        v = request.args.get(f)
        if v is not None:
            items = [j for j in items if j[f] == v]
    items, total = paginate(items, limit, offset)
    return success_list([ser_build_job(j) for j in items], limit, offset, total)


def _check_shortage(job, eff_cfg):
    """Return list of (component, shortfall) for components below required qty."""
    shortfalls = []
    for comp, req in required_components(eff_cfg, job["qty"]):
        available = comp["stock_on_hand"] - comp["reserved_units"]
        if available < req:
            shortfalls.append((comp, req - available))
    return shortfalls


def _enter_shortage(job, shortfalls):
    # largest shortfall; tie-break Component.created_at ASC
    shortfalls.sort(key=lambda t: (-t[1], t[0]["created_at"], t[0]["id"]))
    worst = shortfalls[0][0]
    job["status"] = "SHORTAGE_BLOCKED"
    job["shortage_component_id"] = worst["id"]
    touch(job)
    # supersede any still-PENDING request for this job
    for sr in STORE.sub_requests.values():
        if sr["build_job_id"] == job["id"] and sr["status"] == "PENDING":
            sr["status"] = "SUPERSEDED"
            touch(sr)
    sr = new_entity()
    sr.update({
        "build_job_id": job["id"],
        "original_component_id": worst["id"],
        "proposed_component_id": None,
        "price_delta_cents": 0,
        "round": 1,
        "status": "PENDING",
    })
    STORE.sub_requests[sr["id"]] = sr
    order = STORE.orders.get(job["order_id"])
    if order and order["build_status"] == "SUBMITTED":
        order["build_status"] = "ON_HOLD"
        touch(order)


@bp.post("/api/build-jobs/<jid>/allocate")
def allocate_job(jid):
    require_roles("FactoryOps")
    job = store_lookup("build_jobs", jid)
    if job["status"] != "QUEUED":
        raise err_invalid_state("Build job is not QUEUED")
    order = STORE.orders.get(job["order_id"])
    if order is None or order["build_status"] != "SUBMITTED":
        raise err_invalid_state("Order is not SUBMITTED")
    eff_cfg = _effective_configuration(job)
    shortfalls = _check_shortage(job, eff_cfg)
    if shortfalls:
        _enter_shortage(job, shortfalls)
        return success_object(ser_build_job(job))
    for comp, req in required_components(eff_cfg, job["qty"]):
        comp["reserved_units"] += req
        touch(comp)
    job["status"] = "ALLOCATED"
    touch(job)
    _bubble_order_allocated(job["order_id"])
    rescore_queue()
    return success_object(ser_build_job(job))


@bp.post("/api/build-jobs/<jid>/start")
def start_job(jid):
    require_roles("FactoryOps")
    job = store_lookup("build_jobs", jid)
    if job["status"] != "ALLOCATED":
        raise err_invalid_state("Build job is not ALLOCATED")
    allocated = [j for j in STORE.build_jobs.values() if j["status"] == "ALLOCATED"]
    allocated.sort(key=lambda j: (j["sequence_rank"] if j["sequence_rank"] is not None else 1 << 30,
                                  j["created_at"], j["id"]))
    if not allocated or allocated[0]["id"] != job["id"]:
        raise ApiError(ERR_BUILD_OUT_OF_SEQUENCE,
                       "start attempted on a job that is not the min sequence_rank ALLOCATED job", 422)
    eff_cfg = _effective_configuration(job)
    for comp, req in required_components(eff_cfg, job["qty"]):
        comp["reserved_units"] -= req
        comp["stock_on_hand"] -= req
        touch(comp)
    job["status"] = "BUILDING"
    touch(job)
    order = STORE.orders.get(job["order_id"])
    if order and order["build_status"] == "ALLOCATED":
        order["build_status"] = "IN_PRODUCTION"
        touch(order)
    return success_object(ser_build_job(job))


@bp.post("/api/build-jobs/<jid>/complete")
def complete_job(jid):
    require_roles("FactoryOps")
    job = store_lookup("build_jobs", jid)
    if job["status"] != "BUILDING":
        raise err_invalid_state("Build job is not BUILDING")
    job["status"] = "COMPLETE"
    touch(job)
    line = STORE.order_lines.get(job["order_line_id"])
    order = STORE.orders.get(job["order_id"])
    cfg = STORE.configurations.get(line["configuration_id"]) if line else None
    # asset tag prefix + image from program via template
    prefix = ""
    image_ref = None
    if cfg is not None and cfg.get("template_id"):
        template = STORE.templates.get(cfg["template_id"])
        if template is not None:
            program = STORE.programs.get(template["program_id"])
            if program is not None:
                prefix = program["asset_tag_prefix"]
            image_ref = template.get("pinned_image_ref")
            if image_ref is None and program is not None:
                image_ref = program.get("custom_image_ref")
    if line is not None:
        for _ in range(job["qty"]):
            STORE.serial_counter += 1
            STORE.asset_tag_counter += 1
            asset = new_entity()
            asset.update({
                "order_line_id": line["id"],
                "serial_number": f"SN-{STORE.serial_counter:08d}",
                "asset_tag": f"{prefix}-{STORE.asset_tag_counter:06d}" if prefix else f"{STORE.asset_tag_counter:06d}",
                "image_applied_ref": image_ref,
                "destination_employee_ref": None,
                "status": "STAGED",
            })
            STORE.assets[asset["id"]] = asset
        line["status"] = "FULFILLED"
        touch(line)
    if order is not None:
        jobs = [j for j in STORE.build_jobs.values() if j["order_id"] == order["id"]]
        if all(j["status"] in ("COMPLETE", "CANCELLED") for j in jobs):
            if order["build_status"] == "IN_PRODUCTION":
                order["build_status"] = "BUILT"
                touch(order)
    rescore_queue()
    return success_object(ser_build_job(job))


# ---------------- substitution requests ----------------

@bp.get("/api/build-jobs/<jid>/substitution-requests")
def list_job_subs(jid):
    uid, role = require_roles("PlatformAdmin", "FactoryOps", "CustomerUser", "AccountManager")
    job = store_lookup("build_jobs", jid)
    if role == "CustomerUser":
        require_ownership(account_of_build_job(job), uid, role)
    limit, offset = get_pagination()
    items = [s for s in STORE.sub_requests.values() if s["build_job_id"] == jid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_sub_request(s) for s in items], limit, offset, total)


@bp.get("/api/substitution-requests/<sid>")
def get_sub(sid):
    uid, role = require_roles("PlatformAdmin", "FactoryOps", "CustomerUser", "AccountManager")
    sr = store_lookup("sub_requests", sid)
    if role == "CustomerUser":
        require_ownership(account_of_sub_request(sr), uid, role)
    return success_object(ser_sub_request(sr))


@bp.get("/api/substitution-requests")
def list_subs():
    require_roles("PlatformAdmin", "FactoryOps")
    limit, offset = get_pagination()
    items = list(STORE.sub_requests.values())
    for f in ("original_component_id", "proposed_component_id"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s[f] == v]
    items, total = paginate(items, limit, offset)
    return success_list([ser_sub_request(s) for s in items], limit, offset, total)


def _substitution_compatible(sr, job, proposed_id):
    if proposed_id == sr["original_component_id"]:
        return False
    proposed = STORE.components.get(proposed_id)
    if proposed is None or proposed["status"] != "ACTIVE":
        return False
    line = STORE.order_lines.get(job["order_line_id"])
    cfg = STORE.configurations.get(line["configuration_id"]) if line else None
    if cfg is None:
        return False
    selections = []
    for s in cfg["component_selections"]:
        if s["component_id"] == sr["original_component_id"]:
            selections.append({"component_id": proposed_id, "qty": s["qty"]})
        else:
            selections.append(dict(s))
    return check_compatibility(cfg["chassis_model_id"], selections)


@bp.post("/api/substitution-requests/<sid>/approve")
def approve_sub(sid):
    uid, role = require_roles("CustomerUser")
    sr = store_lookup("sub_requests", sid)
    require_ownership(account_of_sub_request(sr), uid, role)
    if sr["status"] != "PENDING":
        raise err_invalid_state("Substitution request is not PENDING")
    job = STORE.build_jobs.get(sr["build_job_id"])
    order = STORE.orders.get(job["order_id"]) if job else None
    # state (priority 4) outranks fiscal (priority 10)
    if order is None or order["build_status"] != "ON_HOLD" or job is None or job["status"] != "SHORTAGE_BLOCKED":
        raise ApiError(ERR_INVALID_STATE, "Order is no longer ON_HOLD for this substitution", 409)
    if sr["proposed_component_id"] is None or not _substitution_compatible(sr, job, sr["proposed_component_id"]):
        raise ApiError(ERR_SUBSTITUTION_INCOMPATIBLE,
                       "Proposed component fails chassis compatibility or duplicates the original", 422)
    account = STORE.accounts.get(order["account_id"])
    delta = sr["price_delta_cents"] * job["qty"]
    if delta > 0 and account is not None and account["outstanding_cents"] + delta > account["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED,
                       "Positive price delta would exceed credit limit", 402)
    sr["status"] = "APPROVED"
    touch(sr)
    job["swap"] = {"original": sr["original_component_id"], "proposed": sr["proposed_component_id"]}
    job["status"] = "QUEUED"
    job["shortage_component_id"] = None
    touch(job)
    if delta != 0:
        order["total_cents"] = order["total_cents"] + delta
        if account is not None:
            account["outstanding_cents"] += delta
            touch(account)
    # cascade: last blocked job leaves -> order back to SUBMITTED
    siblings_blocked = [j for j in STORE.build_jobs.values()
                        if j["order_id"] == order["id"] and j["status"] == "SHORTAGE_BLOCKED"]
    if not siblings_blocked:
        order["build_status"] = "SUBMITTED"
    touch(order)
    rescore_queue()
    return success_object(ser_sub_request(sr))


@bp.post("/api/substitution-requests/<sid>/reject")
def reject_sub(sid):
    uid, role = require_roles("CustomerUser")
    sr = store_lookup("sub_requests", sid)
    require_ownership(account_of_sub_request(sr), uid, role)
    if sr["status"] != "PENDING":
        raise err_invalid_state("Substitution request is not PENDING")
    sr["status"] = "REJECTED"
    touch(sr)
    return success_object(ser_sub_request(sr))


@bp.post("/api/substitution-requests/<sid>/repropose")
def repropose_sub(sid):
    require_roles("FactoryOps")
    sr = store_lookup("sub_requests", sid)
    if sr["status"] != "REJECTED":
        raise err_invalid_state("Substitution request is not REJECTED")
    body = get_json_body()
    proposed_id = require_field(body, "proposed_component_id", str)
    store_lookup("components", proposed_id)
    # PRD §3.6: a reproposal "must differ from the rejected one" — only
    # comparable when the rejected request actually named a proposal.
    if sr["proposed_component_id"] is not None and proposed_id == sr["proposed_component_id"]:
        raise ApiError(ERR_SUBSTITUTION_INCOMPATIBLE,
                       "New proposal must differ from the rejected one", 422)
    job = STORE.build_jobs.get(sr["build_job_id"])
    if not _substitution_compatible(sr, job, proposed_id):
        raise ApiError(ERR_SUBSTITUTION_INCOMPATIBLE,
                       "Proposed component fails chassis compatibility or duplicates the original", 422)
    proposed = STORE.components[proposed_id]
    original = STORE.components.get(sr["original_component_id"])
    sr["proposed_component_id"] = proposed_id
    sr["price_delta_cents"] = proposed["price_cents"] - (original["price_cents"] if original else 0)
    sr["round"] = sr["round"] + 1
    sr["status"] = "PENDING"
    touch(sr)
    return success_object(ser_sub_request(sr))
