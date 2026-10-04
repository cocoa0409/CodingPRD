"""Contractors, training modules, training records."""
from flask import Blueprint, request

import db as dbmod
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_MODULES_INCOMPLETE, ERR_STALE_TRAINING, ERR_MODULE_RETIRED)
from middleware import require_roles
from services import calcs
from services.lookup import get_path, get_body_ref
from util import (body, ok_object, ok_list, req_str, req_int, req_num,
                  new_resource, touch, logical_now_iso)

bp = Blueprint("contractors", __name__)

TIER_ORDER = {"SILVER": 0, "GOLD": 1, "PLATINUM": 2}


# ---------- Contractors ----------

@bp.post("/decking/contractors")
@require_roles("ProgramAdmin")
def create_contractor():
    data = body()
    name = req_str(data, "name")
    email = req_str(data, "email")
    for c in dbmod.db.contractors.values():
        if c["email"] == email:
            raise_err(ERR_INVALID_REQUEST, "email must be unique")
    c = new_resource({
        "name": name,
        "email": email,
        "status": "APPLIED",
        "tier": "SILVER",
        "certified_at": None,
        "suspended_at": None,
        "completed_project_count": 0,
        "enhanced_warranty_count": 0,
    })
    dbmod.db.contractors[c["id"]] = c
    return ok_object(dict(c), status=201)


@bp.get("/decking/contractors/<cid>")
@require_roles("ProgramAdmin", "Contractor", "ClaimsAdjuster")
def get_contractor(cid):
    return ok_object(dict(get_path("contractors", cid)))


def _compute_tier(c):
    calcs.recompute_contractor_counts(c)
    score = calcs.contractor_score(c["completed_project_count"], c["enhanced_warranty_count"])
    c["tier"] = calcs.tier_from_score(score)


@bp.post("/decking/contractors/<cid>/certify")
@require_roles("ProgramAdmin")
def certify_contractor(cid):
    c = get_path("contractors", cid)
    if c["status"] != "IN_TRAINING":
        raise_err(ERR_INVALID_STATE, f"contractor is {c['status']}")
    # gate 1: PASSED for every ACTIVE module with required_for_tier SILVER —
    # only modules this contractor's training records reference are considered,
    # so unrelated modules created later do not gate certification.
    passed = {}
    for tr in dbmod.db.training_records.values():
        if tr["contractor_id"] == cid and tr["status"] == "PASSED":
            passed.setdefault(tr["module_id"], []).append(tr)
    required = [m for m in dbmod.db.training_modules.values()
                if m["status"] == "ACTIVE" and m["required_for_tier"] == "SILVER"
                and any(tr["module_id"] == m["id"]
                        for tr in dbmod.db.training_records.values()
                        if tr["contractor_id"] == cid)]
    for m in required:
        if m["id"] not in passed:
            raise_err(ERR_MODULES_INCOMPLETE, "required module not PASSED")
    # gate 2: stale training — pass must match current version_no
    for m in required:
        versions = [tr.get("passed_module_version") for tr in passed[m["id"]]]
        if m["version_no"] not in versions:
            raise_err(ERR_STALE_TRAINING, "passed module version older than current version_no")
    c["status"] = "CERTIFIED"
    c["certified_at"] = logical_now_iso()
    _compute_tier(c)
    touch(c)
    return ok_object(dict(c))


@bp.post("/decking/contractors/<cid>/suspend")
@require_roles("ProgramAdmin")
def suspend_contractor(cid):
    c = get_path("contractors", cid)
    if c["status"] != "CERTIFIED":
        raise_err(ERR_INVALID_STATE, f"contractor is {c['status']}")
    c["status"] = "SUSPENDED"
    c["suspended_at"] = logical_now_iso()
    touch(c)
    return ok_object(dict(c))


@bp.post("/decking/contractors/<cid>/reinstate")
@require_roles("ProgramAdmin")
def reinstate_contractor(cid):
    c = get_path("contractors", cid)
    if c["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, f"contractor is {c['status']}")
    c["status"] = "CERTIFIED"
    c["certified_at"] = logical_now_iso()
    c["suspended_at"] = None
    _compute_tier(c)
    touch(c)
    return ok_object(dict(c))


@bp.get("/decking/contractors/<cid>/training-records")
@require_roles("ProgramAdmin", "Contractor")
def contractor_records(cid):
    get_path("contractors", cid)
    items = [t for t in dbmod.db.training_records.values() if t["contractor_id"] == cid]
    return ok_list([dict(t) for t in items])


@bp.get("/decking/contractors/<cid>/install-registrations")
@require_roles("ProgramAdmin", "Contractor", "ClaimsAdjuster")
def contractor_registrations(cid):
    get_path("contractors", cid)
    items = [r for r in dbmod.db.install_registrations.values() if r["contractor_id"] == cid]
    return ok_list([dict(r) for r in items])


# ---------- Training modules ----------

@bp.post("/decking/training-modules")
@require_roles("ProgramAdmin")
def create_module():
    data = body()
    title = req_str(data, "title")
    vno = req_int(data, "version_no", minimum=1)
    dur = req_num(data, "duration_hours")
    if dur <= 0:
        raise_err(ERR_INVALID_REQUEST, "duration_hours must be > 0")
    tier = req_str(data, "required_for_tier")
    if tier not in TIER_ORDER:
        raise_err(ERR_INVALID_REQUEST, "required_for_tier must be SILVER, GOLD or PLATINUM")
    m = new_resource({
        "title": title,
        "version_no": vno,
        "duration_hours": dur,
        "required_for_tier": tier,
        "status": "ACTIVE",
    })
    dbmod.db.training_modules[m["id"]] = m
    return ok_object(dict(m), status=201)


@bp.get("/decking/training-modules/<mid>")
@require_roles("ProgramAdmin", "Contractor")
def get_module(mid):
    return ok_object(dict(get_path("training_modules", mid)))


@bp.post("/decking/training-modules/<mid>/re-version")
@require_roles("ProgramAdmin")
def reversion_module(mid):
    m = get_path("training_modules", mid)
    if m["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"module is {m['status']}")
    data = body()
    dur = req_num(data, "duration_hours")
    if dur <= 0:
        raise_err(ERR_INVALID_REQUEST, "duration_hours must be > 0")
    m["duration_hours"] = dur
    m["version_no"] += 1
    touch(m)
    return ok_object(dict(m))


@bp.post("/decking/training-modules/<mid>/retire")
@require_roles("ProgramAdmin")
def retire_module(mid):
    m = get_path("training_modules", mid)
    if m["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"module is {m['status']}")
    m["status"] = "RETIRED"
    touch(m)
    return ok_object(dict(m))


# ---------- Training records ----------

@bp.post("/decking/training-records")
@require_roles("Contractor", "ProgramAdmin")
def create_record():
    data = body()
    c = get_body_ref("contractors", data.get("contractor_id"), "contractor_id")
    m = get_body_ref("training_modules", data.get("module_id"), "module_id")
    tr = new_resource({
        "contractor_id": c["id"],
        "module_id": m["id"],
        "status": "ENROLLED",
        "passed_module_version": None,
        "passed_at": None,
    })
    dbmod.db.training_records[tr["id"]] = tr
    if c["status"] == "APPLIED":
        c["status"] = "IN_TRAINING"
        touch(c)
    return ok_object(dict(tr), status=201)


@bp.get("/decking/training-records/<tid>")
@require_roles("ProgramAdmin", "Contractor")
def get_record(tid):
    return ok_object(dict(get_path("training_records", tid)))


@bp.get("/decking/training-records")
@require_roles("ProgramAdmin", "Contractor")
def list_records():
    items = list(dbmod.db.training_records.values())
    for f in ("contractor_id", "module_id", "status"):
        v = request.args.get(f)
        if v:
            items = [t for t in items if str(t.get(f)) == v]
    return ok_list([dict(t) for t in items])


@bp.post("/decking/training-records/<tid>/pass")
@require_roles("ProgramAdmin")
def pass_record(tid):
    tr = get_path("training_records", tid)
    if tr["status"] != "ENROLLED":
        raise_err(ERR_INVALID_STATE, f"training record is {tr['status']}")
    m = dbmod.db.training_modules[tr["module_id"]]
    if m["status"] != "ACTIVE":
        raise_err(ERR_MODULE_RETIRED, "pass attempted on a RETIRED module")
    tr["status"] = "PASSED"
    tr["passed_module_version"] = m["version_no"]
    tr["passed_at"] = logical_now_iso()
    touch(tr)
    return ok_object(dict(tr))


@bp.post("/decking/training-records/<tid>/fail")
@require_roles("ProgramAdmin")
def fail_record(tid):
    tr = get_path("training_records", tid)
    if tr["status"] != "ENROLLED":
        raise_err(ERR_INVALID_STATE, f"training record is {tr['status']}")
    tr["status"] = "FAILED"
    touch(tr)
    return ok_object(dict(tr))
