"""Material traceability: mill test reports, heats, the mass ledger and parts."""

from decimal import Decimal

from flask import Blueprint

import db
import validation
from errors import fail
from middleware import ALL_ROLES, guard
from routes import common
from services import calc, derive

bp = Blueprint("materials", __name__)

SPECS = ("SA-516-70", "SA-240-304L", "SA-105", "SA-179")
FORMS = ("PLATE", "FORGING", "PIPE", "TUBE")
COMPONENT_TYPES = ("SHELL", "HEAD", "TUBESHEET", "NOZZLE", "FLANGE")
PART_JOB_STATES = ("FAB_PLANNING", "FABRICATION", "NDE_HOLD")


@bp.post("/material-heats")
@guard(["QCInspector"])
def create_heat(ctx):
    body = validation.body()
    heat_number = validation.string_field(body, "heat_number")
    spec = validation.enum_field(body, "spec", SPECS)
    form = validation.enum_field(body, "form", FORMS)
    mtr_received = validation.bool_field(body, "mtr_received", required=False,
                                         default=False)
    yield_ksi = validation.decimal_field(body, "mtr_certified_yield_ksi",
                                         required=False, default=None)
    tensile_ksi = validation.decimal_field(body, "mtr_certified_tensile_ksi",
                                           required=False, default=None)
    quantity_received = validation.decimal_field(body, "quantity_received_lb",
                                                 scale=2, exclusive_min=0)

    for other in db.all_of("heats"):
        if other["heat_number"] == heat_number and other["spec"] == spec:
            fail("ERR_DUPLICATE_HEAT_NUMBER",
                 "Heat %s is already on file under %s." % (heat_number, spec))

    material_class, p_number = calc.SPEC_PROPERTIES[spec][0], calc.SPEC_PROPERTIES[spec][1]
    record = db.insert("heats", {
        "heat_number": heat_number,
        "spec": spec,
        "form": form,
        "material_class": material_class,
        "p_number": p_number,
        "mtr_received": mtr_received,
        "mtr_certified_yield_ksi": yield_ksi,
        "mtr_certified_tensile_ksi": tensile_ksi,
        "quantity_received_lb": quantity_received,
        "quantity_issued_lb": Decimal("0.00"),
        "quantity_remaining_lb": quantity_received,
        "status": "QUARANTINE",
    })
    return common.created("heats", record)


@bp.get("/material-heats/<heat_id>")
@guard(ALL_ROLES)
def get_heat(ctx, heat_id):
    return common.one("heats", common.must_exist("heats", heat_id))


@bp.get("/material-heats")
@guard(ALL_ROLES)
def list_heats(ctx):
    return common.listing("heats", ["spec", "status", "heat_number"])


@bp.post("/material-heats/<heat_id>/mtr-review")
@guard(["QCInspector"])
def review_heat(ctx, heat_id):
    body = validation.body()
    decision = validation.enum_field(body, "decision", ("ACCEPT", "REJECT"))
    reason = validation.string_field(body, "reason", required=False, default=None)

    heat = common.must_exist("heats", heat_id)
    if heat["status"] != "QUARANTINE":
        fail("ERR_INVALID_HEAT_STATE",
             "Receiving inspection needs the heat in QUARANTINE.")

    if decision == "ACCEPT":
        minimum_yield = calc.SPEC_PROPERTIES[heat["spec"]][2]
        minimum_tensile = calc.SPEC_PROPERTIES[heat["spec"]][3]
        certified_yield = heat["mtr_certified_yield_ksi"]
        certified_tensile = heat["mtr_certified_tensile_ksi"]
        if certified_yield is not None and certified_tensile is not None:
            if certified_yield < minimum_yield or certified_tensile < minimum_tensile:
                fail("ERR_MTR_BELOW_SPEC_MINIMUM",
                     "The certified strengths fall short of the %s minima."
                     % heat["spec"])
        if not heat["mtr_received"]:
            fail("ERR_TRACEABILITY_INCOMPLETE",
                 "The mill test report for this heat is not on file.")
        db.mutate(heat, {"status": "ACCEPTED"})
    else:
        if reason is None or not reason.strip():
            fail("ERR_INVALID_REQUEST", "A REJECT decision requires a reason.")
        db.mutate(heat, {"status": "REJECTED"})
    return common.one("heats", heat)


@bp.post("/vessel-jobs/<job_id>/parts")
@guard(["WeldingEngineer"])
def create_part(ctx, job_id):
    body = validation.body()
    heat_id = validation.string_field(body, "heat_id")
    part_mark = validation.string_field(body, "part_mark")
    component_type = validation.enum_field(body, "component_type", COMPONENT_TYPES)
    issued_quantity = validation.decimal_field(body, "issued_quantity_lb", scale=2,
                                               exclusive_min=0)

    job = common.must_exist("jobs", job_id)
    heat = db.get("heats", heat_id)
    if heat is None:
        fail("ERR_HEAT_NOT_FOUND", "No heat carries id %s." % heat_id)
    if job["status"] not in PART_JOB_STATES:
        fail("ERR_INVALID_JOB_STATE",
             "Material issue needs the job in FAB_PLANNING, FABRICATION or NDE_HOLD.")
    if heat["status"] != "ACCEPTED":
        fail("ERR_HEAT_NOT_ACCEPTED",
             "A heat in %s may not be issued." % heat["status"])
    if heat["form"] not in calc.FORM_FOR_COMPONENT[component_type]:
        fail("ERR_MATERIAL_FORM_MISMATCH",
             "A %s cannot be cut from %s." % (component_type, heat["form"]))
    if issued_quantity > heat["quantity_remaining_lb"]:
        fail("ERR_INSUFFICIENT_HEAT_QUANTITY",
             "Only %s lb remain on this heat." % heat["quantity_remaining_lb"])

    record = db.insert("parts", {
        "job_id": job_id,
        "heat_id": heat_id,
        "part_mark": part_mark,
        "component_type": component_type,
        "issued_quantity_lb": issued_quantity,
        "status": "ISSUED",
        "scrap_reason": None,
    })
    derive.sync_heat_ledger(heat)
    return common.created("parts", record)


@bp.get("/parts/<part_id>")
@guard(ALL_ROLES)
def get_part(ctx, part_id):
    return common.one("parts", common.must_exist("parts", part_id))


@bp.get("/parts")
@guard(ALL_ROLES)
def list_parts(ctx):
    return common.listing("parts", ["job_id", "heat_id", "component_type", "status"])


@bp.post("/parts/<part_id>/scrap")
@guard(["WeldingEngineer"])
def scrap_part(ctx, part_id):
    body = validation.body()
    scrap_reason = validation.string_field(body, "scrap_reason")

    part = common.must_exist("parts", part_id)
    if part["status"] != "ISSUED":
        fail("ERR_INVALID_PART_STATE", "Only an ISSUED piece may be scrapped.")
    for weld in derive.job_welds(part["job_id"]):
        if weld["fab_status"] == "WELDED" and part_id in (weld["part_a_id"],
                                                          weld["part_b_id"]):
            fail("ERR_INVALID_PART_STATE",
                 "Joint %s has already been welded to this piece."
                 % weld["weld_number"])
    job = db.get("jobs", part["job_id"])
    if job["status"] not in PART_JOB_STATES:
        fail("ERR_INVALID_JOB_STATE",
             "Scrapping needs the job in FAB_PLANNING, FABRICATION or NDE_HOLD.")

    db.mutate(part, {"status": "SCRAPPED", "scrap_reason": scrap_reason})
    derive.sync_heat_ledger(db.get("heats", part["heat_id"]))
    derive.recompute_job(job)
    derive.sync_job_reports(job)
    return common.one("parts", part)
