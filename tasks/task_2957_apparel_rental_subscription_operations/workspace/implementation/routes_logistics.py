"""Reverse logistics: inspections, cleaning, repair, quarantine, photo, restock."""
from flask import Blueprint

import calc
import core
import serialize
import services
from core import (CONDITION_GRADES, DAMAGE_SEVERITIES, DB, JOB_STATES,
                  JOB_TERMINAL, REPAIR_ATTEMPT_CAP, REPAIR_OUTCOMES, SOIL_LEVELS,
                  fail, now_iso, ok, ok_list)
from guards import (begin, body_json, bool_query, enum_query, lookup, pagination,
                    paginate, sort_rows, str_query, tech_active, tech_certified,
                    validate)

bp = Blueprint("logistics", __name__)

READ_ROLES = ["WarehouseTech", "ClaimsAdjuster", "InventoryPlanner", "PlatformAdmin"]

REPAIR_SEVERITIES = ("MINOR", "MODERATE", "SEVERE")


def _newest_inspection(job_id):
    rows = calc.inspections_of_job(job_id)
    if not rows:
        return None
    return rows[-1]


def _claim_on_job(job):
    """The damage claim opened on this unit-and-turn, if any."""
    best = None
    for c in DB["damage_claims"].values():
        if (c["rental_unit_id"] == job["rental_unit_id"]
                and c["reservation_id"] == job["reservation_id"]):
            if best is None or (c["created_at"], c["_seq"]) > (best["created_at"],
                                                               best["_seq"]):
                best = c
    return best


# ---------------------------------------------------------------------------
# Job reads
# ---------------------------------------------------------------------------
@bp.get("/reverse-logistics-jobs/<job_id>")
def get_job(job_id):
    ctx = begin(READ_ROLES)
    row = lookup("reverse_logistics_jobs", job_id, "ERR_JOB_NOT_FOUND")
    return ok(serialize.job_out(row))


@bp.get("/reverse-logistics-jobs")
def list_jobs():
    ctx = begin(READ_ROLES)
    state = enum_query("state", JOB_STATES)
    unit_id = str_query("rental_unit_id")
    reservation_id = str_query("reservation_id")
    tech_id = str_query("inspecting_technician_id")
    limit, offset = pagination()
    rows = []
    for j in DB["reverse_logistics_jobs"].values():
        if unit_id is not None and j["rental_unit_id"] != unit_id:
            continue
        if reservation_id is not None and j["reservation_id"] != reservation_id:
            continue
        if tech_id is not None and j["inspecting_technician_id"] != tech_id:
            continue
        if state is not None and j["state"] != state:
            continue
        rows.append(j)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.job_out)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Inspection reads
# ---------------------------------------------------------------------------
@bp.get("/inspections/<inspection_id>")
def get_inspection(inspection_id):
    begin(READ_ROLES)
    row = lookup("inspections", inspection_id, "ERR_INSPECTION_NOT_FOUND")
    return ok(serialize.inspection_out(row))


@bp.get("/inspections")
def list_inspections():
    begin(READ_ROLES)
    severity = enum_query("damage_severity", DAMAGE_SEVERITIES)
    job_id = str_query("job_id")
    technician_id = str_query("technician_id")
    limit, offset = pagination()
    rows = []
    for r in DB["inspections"].values():
        if job_id is not None and r["job_id"] != job_id:
            continue
        if technician_id is not None and r["technician_id"] != technician_id:
            continue
        if severity is not None and r["damage_severity"] != severity:
            continue
        rows.append(r)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.inspection_out)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Filing an inspection
# ---------------------------------------------------------------------------
@bp.post("/reverse-logistics-jobs/<job_id>/inspections")
def create_inspection(job_id):
    ctx = begin(["WarehouseTech"])
    job = lookup("reverse_logistics_jobs", job_id, "ERR_JOB_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "soil_level", "kind": "enum", "required": True,
         "values": SOIL_LEVELS},
        {"name": "damage_severity", "kind": "enum", "required": True,
         "values": DAMAGE_SEVERITIES},
        {"name": "condition_grade_after", "kind": "enum", "required": True,
         "values": CONDITION_GRADES},
        {"name": "biohazard_flag", "kind": "bool", "default": False},
        {"name": "notes", "kind": "str", "default": None},
    ])
    # Ranks 16 / 15
    if job["state"] in JOB_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Job is %s" % job["state"])
    if job["state"] not in ("RECEIVED", "PROCESSING"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "An inspection is not declared from %s" % job["state"])
    if job["state"] == "PROCESSING" and job["condemned"]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A condemned job may not be re-inspected")
    # Rank 27
    tech_active(ctx)
    unit = DB["rental_units"].get(job["rental_unit_id"])
    if unit is None or unit["availability_state"] != "PROCESSING":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The unit must be in PROCESSING to be inspected")

    reinspection = job["state"] == "PROCESSING"
    prior = calc.inspections_of_job(job["id"])
    row = services.base_row("inspections", event=True)
    row.update({
        "job_id": job["id"],
        "technician_id": ctx.user_id,
        "soil_level": data["soil_level"],
        "damage_severity": data["damage_severity"],
        "condition_grade_after": data["condition_grade_after"],
        "biohazard_flag": data["biohazard_flag"],
        "notes": data.get("notes"),
        "attempt_index": (max([p["attempt_index"] for p in prior]) + 1
                          if prior else 1),
    })
    DB["inspections"][row["id"]] = row

    severity = data["damage_severity"]
    soiled = data["soil_level"] != "NONE"
    needs_repair = severity in REPAIR_SEVERITIES
    job["state"] = "INSPECTED"
    job["inspecting_technician_id"] = ctx.user_id
    job["cleaning_required"] = soiled
    job["repair_required"] = needs_repair
    if reinspection:
        if soiled:
            job["cleaning_completed_at"] = None
        if needs_repair:
            job["repair_completed_at"] = None
    services.touch(job)

    # Unit condition dimension, in strict precedence order
    unit["condition_grade"] = data["condition_grade_after"]
    if data["biohazard_flag"]:
        unit["condition_state"] = "QUARANTINED"
        unit["quarantine_hold"] = True
    elif severity == "LOSS":
        unit["condition_state"] = "CONDEMNED"
    elif needs_repair:
        unit["condition_state"] = "NEEDS_REPAIR"
    elif soiled:
        unit["condition_state"] = "NEEDS_CLEANING"
    services.touch(unit)

    # Damage claim
    res = DB["reservations"].get(job["reservation_id"])
    member = DB["members"].get(res["member_id"]) if res is not None else None
    if severity != "NONE":
        claim = _claim_on_job(job)
        if claim is not None and claim["state"] in ("OPEN", "ASSESSED"):
            claim["severity"] = severity
            claim["state"] = "OPEN"
            claim["inspection_id"] = row["id"]
            services.touch(claim)
        elif claim is None:
            claim = services.base_row("damage_claims")
            claim.update({
                "reservation_id": job["reservation_id"],
                "rental_unit_id": job["rental_unit_id"],
                "member_id": member["id"] if member else None,
                "inspection_id": row["id"],
                "severity": severity,
                "state": "OPEN",
                "residual_value_cents": 0,
                "gross_fee_cents": 0,
                "waiver_applied_cents": 0,
                "net_fee_cents": 0,
                "dispute_round": 0,
                "dispute_reason": None,
                "resolution": None,
                "assessed_at": None,
                "charged_at": None,
            })
            DB["damage_claims"][claim["id"]] = claim
        if member is not None:
            services.persist_lifetime_risk(member)

    # Job destination, fully determined by this inspection
    if severity == "LOSS":
        job["condemned"] = True
        job["state"] = "CONDEMNED_HOLD"
        services.touch(job)
    elif soiled or needs_repair or data["biohazard_flag"]:
        # A biohazard garment owes the quarantine route before it can rejoin the
        # floor, so it waits in PROCESSING even when neither fork leg is set.
        job["state"] = "PROCESSING"
        services.touch(job)
    else:
        job["state"] = "READY_FOR_PHOTO"
        services.touch(job)
    return ok(serialize.inspection_out(row), 201)


# ---------------------------------------------------------------------------
# The cleaning leg
# ---------------------------------------------------------------------------
@bp.post("/reverse-logistics-jobs/<job_id>/cleaning-completion")
def cleaning_completion(job_id):
    ctx = begin(["WarehouseTech"])
    job = lookup("reverse_logistics_jobs", job_id, "ERR_JOB_NOT_FOUND")
    body_json()
    unit = DB["rental_units"].get(job["rental_unit_id"])
    # Ranks 16 / 15
    if job["state"] in JOB_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Job is %s" % job["state"])
    if (job["state"] != "PROCESSING" or not job["cleaning_required"]
            or job["cleaning_completed_at"] is not None):
        fail("ERR_INVALID_STATE_TRANSITION",
             "There is no outstanding cleaning leg on this job")
    # Rank 20
    if unit is not None and unit["quarantine_hold"]:
        fail("ERR_QUARANTINE_HOLD_ACTIVE", "The unit is under a quarantine hold")
    # Rank 23
    if (job["cleaning_required"] and job["repair_required"]
            and job["repair_completed_at"] is None):
        fail("ERR_REPAIR_PENDING",
             "The repair leg must be signed off before cleaning")
    # Rank 27
    tech_active(ctx)

    job["cleaning_completed_at"] = now_iso()
    services.touch(job)
    if unit is not None:
        unit["condition_state"] = "FLOOR_READY"
        services.touch(unit)
        services.try_join(job, unit)
    return ok(serialize.job_out(job))


# ---------------------------------------------------------------------------
# The repair leg
# ---------------------------------------------------------------------------
@bp.post("/reverse-logistics-jobs/<job_id>/repair-completion")
def repair_completion(job_id):
    ctx = begin(["WarehouseTech"])
    job = lookup("reverse_logistics_jobs", job_id, "ERR_JOB_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "outcome", "kind": "enum", "required": True,
         "values": REPAIR_OUTCOMES},
    ])
    unit = DB["rental_units"].get(job["rental_unit_id"])
    # Ranks 16 / 15
    if job["state"] in JOB_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Job is %s" % job["state"])
    if (job["state"] != "PROCESSING" or not job["repair_required"]
            or job["repair_completed_at"] is not None):
        fail("ERR_INVALID_STATE_TRANSITION",
             "There is no outstanding repair leg on this job")
    # Rank 20
    if unit is not None and unit["quarantine_hold"]:
        fail("ERR_QUARANTINE_HOLD_ACTIVE", "The unit is under a quarantine hold")
    # Rank 25
    if job["inspecting_technician_id"] == ctx.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The inspecting technician may not sign off this repair")
    # Rank 26
    tech_certified(ctx, "repair_certified")
    # Rank 27
    tech_active(ctx)
    # Rank 28
    if job["repair_attempts"] >= REPAIR_ATTEMPT_CAP:
        fail("ERR_REPAIR_ATTEMPTS_EXHAUSTED",
             "This job has consumed every permitted repair attempt")

    job["repair_attempts"] += 1
    if data["outcome"] == "ACCEPTED":
        job["repair_completed_at"] = now_iso()
        services.touch(job)
        if unit is not None:
            unit["condition_state"] = ("NEEDS_CLEANING" if job["cleaning_required"]
                                       else "FLOOR_READY")
            services.touch(unit)
            services.try_join(job, unit)
    elif job["repair_attempts"] >= REPAIR_ATTEMPT_CAP:
        job["condemned"] = True
        job["state"] = "CONDEMNED_HOLD"
        services.touch(job)
        if unit is not None:
            unit["condition_state"] = "CONDEMNED"
            services.touch(unit)
        claim = _claim_on_job(job)
        if (claim is not None and claim["severity"] == "SEVERE"
                and claim["state"] in ("OPEN", "ASSESSED")):
            claim["severity"] = "LOSS"
            services.touch(claim)
    else:
        # bounded retry: the job holds its place on a PROCESSING self-loop
        services.touch(job)
    return ok(serialize.job_out(job))


# ---------------------------------------------------------------------------
# Quarantine clearance
# ---------------------------------------------------------------------------
@bp.post("/reverse-logistics-jobs/<job_id>/quarantine-clearance")
def quarantine_clearance(job_id):
    ctx = begin(["WarehouseTech"])
    job = lookup("reverse_logistics_jobs", job_id, "ERR_JOB_NOT_FOUND")
    body_json()
    unit = DB["rental_units"].get(job["rental_unit_id"])
    # Ranks 16 / 15
    if job["state"] in JOB_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Job is %s" % job["state"])
    if unit is None or not unit["quarantine_hold"]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The unit is not under a quarantine hold")
    # Rank 26
    tech_certified(ctx, "repair_certified")
    # Rank 27
    tech_active(ctx)

    unit["quarantine_hold"] = False
    unit["condition_state"] = "NEEDS_CLEANING"
    services.touch(unit)
    # A quarantined garment always passes through the cleaning leg on its way out
    if not job["cleaning_required"]:
        job["cleaning_required"] = True
        services.touch(job)
    return ok(serialize.job_out(job))


# ---------------------------------------------------------------------------
# Re-photography
# ---------------------------------------------------------------------------
@bp.post("/reverse-logistics-jobs/<job_id>/photography")
def photography(job_id):
    ctx = begin(["WarehouseTech"])
    job = lookup("reverse_logistics_jobs", job_id, "ERR_JOB_NOT_FOUND")
    body_json()
    unit = DB["rental_units"].get(job["rental_unit_id"])
    # Ranks 16 / 15
    if job["state"] in JOB_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Job is %s" % job["state"])
    if job["state"] != "READY_FOR_PHOTO":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Photography is not declared from %s" % job["state"])
    # Rank 20
    if unit is not None and unit["quarantine_hold"]:
        fail("ERR_QUARANTINE_HOLD_ACTIVE", "The unit is under a quarantine hold")
    # Rank 21
    if unit is not None and unit["condition_state"] == "CONDEMNED":
        fail("ERR_UNIT_CONDEMNED", "The unit is condemned")
    # Rank 26
    tech_certified(ctx, "photography_certified")
    # Rank 27
    tech_active(ctx)
    if unit is None or unit["condition_state"] != "FLOOR_READY":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The unit must be FLOOR_READY to be re-photographed")

    job["photographed_at"] = now_iso()
    job["state"] = "PHOTOGRAPHED"
    services.touch(job)
    return ok(serialize.job_out(job))


# ---------------------------------------------------------------------------
# Restock
# ---------------------------------------------------------------------------
@bp.post("/reverse-logistics-jobs/<job_id>/restock")
def restock(job_id):
    ctx = begin(["WarehouseTech"])
    job = lookup("reverse_logistics_jobs", job_id, "ERR_JOB_NOT_FOUND")
    body_json()
    unit = DB["rental_units"].get(job["rental_unit_id"])
    # Ranks 16 / 15
    if job["state"] in JOB_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Job is %s" % job["state"])
    if job["state"] != "PHOTOGRAPHED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Restock is not declared from %s" % job["state"])
    # Rank 20
    if unit is not None and unit["quarantine_hold"]:
        fail("ERR_QUARANTINE_HOLD_ACTIVE", "The unit is under a quarantine hold")
    # Rank 21
    if unit is not None and unit["condition_state"] == "CONDEMNED":
        fail("ERR_UNIT_CONDEMNED", "The unit is condemned")
    # Rank 22
    for c in DB["damage_claims"].values():
        if (c["rental_unit_id"] == job["rental_unit_id"]
                and c["reservation_id"] == job["reservation_id"]
                and c["state"] in ("OPEN", "ASSESSED", "DISPUTED")):
            fail("ERR_OPEN_CLAIM_BLOCKS_RESTOCK",
                 "An unsettled damage claim blocks this restock")
    # Rank 27
    tech_active(ctx)
    if unit is None or unit["condition_state"] != "FLOOR_READY":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The unit must be FLOOR_READY to be restocked")

    job["state"] = "RESTOCKED"
    services.touch(job)
    unit["availability_state"] = "IN_STOCK"
    unit["turns_completed"] += 1
    services.touch(unit)
    res = DB["reservations"].get(job["reservation_id"])
    if res is not None and res["state"] == "RETURNED":
        member = DB["members"].get(res["member_id"])
        if member is not None:
            services.close_reservation(res, member)
    services.promote_for_freed_unit(unit)
    return ok(serialize.job_out(job))
