"""Graphs, grid-cell notations and signing (PRD 3.3)."""

from flask import Blueprint

import calc
import validate as v
from auth import ROLES, authenticate, not_owner
from clock import clock
from common import (apply_filters, get_inspection, get_inspector, get_property,
                    require_category, require_license_active,
                    require_license_unexpired)
from envelope import created, listing, ok
from errors import ApiError, field_combination, invalid_request, invalid_state
from ledger import (recompute_inspection_rollups, recompute_property_ledger,
                    supersede_graph)
from serialize import finding_out, inspection_out
from store import (by_created, by_seq, db, findings_of, inspections_of, new_row,
                   touch)

bp = Blueprint("inspection", __name__)

ALL = ROLES


@bp.post("/inspections")
def create_inspection():
    user_id, _role = authenticate(("FieldInspector",))
    payload = v.body()

    # Stage 3 sits ahead of shape validation: a well-formed inspector_id that
    # names somebody else is an ownership failure before anything else.
    claimed = payload.get("inspector_id")
    if isinstance(claimed, str) and claimed != user_id:
        raise not_owner("a FieldInspector may only open a graph in their own name")

    property_id = v.get_string(payload, "property_id")
    inspector_id = v.get_string(payload, "inspector_id")
    purpose = v.get_enum(payload, "purpose", calc.INSPECTION_PURPOSES)
    start_at = v.get_instant(payload, "scheduled_start_at")
    end_at = v.get_instant(payload, "scheduled_end_at")
    supersedes_id = v.get_string(payload, "supersedes_inspection_id", required=False,
                                 default=None)
    closing_date = v.get_date(payload, "closing_date", required=False, default=None)

    # Stage 6: cross-field shape.
    if end_at <= start_at:
        raise field_combination("scheduled_end_at must be strictly after scheduled_start_at")
    if purpose == "REAL_ESTATE":
        if closing_date is None:
            raise field_combination("closing_date is required for a REAL_ESTATE graph")
    elif closing_date is not None:
        raise field_combination("closing_date is only permitted on a REAL_ESTATE graph")
    if purpose in ("RENEWAL", "REINSTATEMENT"):
        if supersedes_id is None:
            raise field_combination(
                "supersedes_inspection_id is required for a %s graph" % purpose)
    elif supersedes_id is not None:
        raise field_combination(
            "supersedes_inspection_id is only permitted on a RENEWAL or REINSTATEMENT graph")

    # Stage 8: body references.
    prop = get_property(property_id)
    inspector = get_inspector(inspector_id)
    prior = get_inspection(supersedes_id) if supersedes_id is not None else None

    # Stage 11 then stage 14.
    require_license_active(inspector)
    if inspector["license_state"] != prop["state_code"]:
        raise ApiError("ERR_LICENSE_STATE_MISMATCH", 422,
                       "licence issued by %s may not work a %s structure"
                       % (inspector["license_state"], prop["state_code"]))

    # Stage 20 then stage 22.
    if prior is not None and prior["property_id"] != prop["id"]:
        raise ApiError("ERR_PROPERTY_MISMATCH", 422,
                       "the superseded graph belongs to another structure")
    for other in db.inspections.values():
        if other["inspector_id"] != inspector_id:
            continue
        if other["scheduled_start_at"] < end_at and start_at < other["scheduled_end_at"]:
            raise ApiError("ERR_INSPECTOR_SCHEDULE_OVERLAP", 409,
                           "the inspector already occupies an overlapping interval")

    highest = 0
    for other in inspections_of(prop["id"]):
        if other["sequence_no"] > highest:
            highest = other["sequence_no"]

    row = new_row({
        "property_id": prop["id"],
        "inspector_id": inspector["id"],
        "supersedes_inspection_id": prior["id"] if prior is not None else None,
        "purpose": purpose,
        "status": "DRAFT",
        "scheduled_start_at": start_at,
        "scheduled_end_at": end_at,
        "closing_date": closing_date,
        "sequence_no": highest + 1,
        "graph_completed_at": None,
        "no_findings_attested": False,
        "findings_count": 0,
        "conducive_condition_count": 0,
        "active_infestation_found": False,
        "damage_estimate_total_usd": calc.ZERO,
    })
    db.inspections[row["id"]] = row

    if prior is not None:
        supersede_graph(prior)

    return created(inspection_out(row))


@bp.get("/inspections/<iid>")
def read_inspection(iid):
    authenticate(ALL)
    return ok(inspection_out(get_inspection(iid)))


@bp.get("/inspections")
def list_inspections():
    authenticate(ALL)
    rows = apply_filters(by_created(list(db.inspections.values())), {
        "property_id": v.query_str("property_id"),
        "inspector_id": v.query_str("inspector_id"),
        "supersedes_inspection_id": v.query_str("supersedes_inspection_id"),
        "status": v.query_str("status"),
        "purpose": v.query_str("purpose"),
    })
    return listing(rows, inspection_out)


@bp.post("/inspections/<iid>/findings")
def create_finding(iid):
    user_id, _role = authenticate(("FieldInspector",))
    inspection = get_inspection(iid)
    if inspection["inspector_id"] != user_id:
        raise not_owner("a FieldInspector may only notate their own graph")

    payload = v.body()
    finding_type = v.get_enum(payload, "finding_type", calc.FINDING_TYPES)
    grid_ref = v.get_string(payload, "grid_ref", pattern=v.GRID_REF_RE)
    organism = v.get_enum(payload, "organism", calc.ORGANISMS, required=False,
                          default="NONE")
    severity = v.get_int(payload, "severity", required=False, default=1,
                         minimum=1, maximum=5)
    conducive_code = v.get_enum(payload, "conducive_code", calc.CONDUCIVE_CODES,
                                required=False, default="NONE")
    damage_estimate = v.get_money(payload, "damage_estimate_usd", required=False,
                                  default=calc.ZERO, maximum="250000.00")
    pre_existing_supplied = v.present(payload, "pre_existing")
    pre_existing = v.get_bool(payload, "pre_existing", required=False, default=False)

    if finding_type == "ACTIVE_INFESTATION" and organism == "NONE":
        raise invalid_request("organism must not be NONE for an ACTIVE_INFESTATION notation")

    # Stage 6, in the order PRD 2.6 lists them.
    if finding_type == "CONDUCIVE_CONDITION":
        if conducive_code == "NONE":
            raise field_combination(
                "conducive_code must name a real code for a CONDUCIVE_CONDITION notation")
    elif conducive_code != "NONE":
        raise field_combination(
            "conducive_code must be NONE unless finding_type is CONDUCIVE_CONDITION")
    if finding_type == "DAMAGE":
        if damage_estimate <= calc.ZERO:
            raise field_combination(
                "damage_estimate_usd must be greater than zero for a DAMAGE notation")
    elif damage_estimate != calc.ZERO:
        raise field_combination(
            "damage_estimate_usd must be 0.00 unless finding_type is DAMAGE")
    if finding_type == "DAMAGE":
        if not pre_existing_supplied:
            raise field_combination("pre_existing is required for a DAMAGE notation")
    elif pre_existing_supplied:
        raise field_combination(
            "pre_existing may only be supplied for a DAMAGE notation")

    if inspection["status"] != "DRAFT":
        raise invalid_state("Inspection",
                            "a notation may only be added to a DRAFT graph")

    for other in findings_of(inspection["id"]):
        if other["grid_ref"] == grid_ref and other["finding_type"] == finding_type:
            raise ApiError("ERR_DUPLICATE_GRID_FINDING", 409,
                           "cell %s already carries a %s notation" % (grid_ref, finding_type))

    row = new_row({
        "inspection_id": inspection["id"],
        "finding_type": finding_type,
        "organism": organism,
        "grid_ref": grid_ref,
        "severity": severity,
        "conducive_code": conducive_code,
        "damage_estimate_usd": calc.r2(damage_estimate),
        "pre_existing": pre_existing,
    }, versioned=False)
    db.findings[row["id"]] = row
    return created(finding_out(row))


@bp.get("/inspections/<iid>/findings")
def list_findings(iid):
    authenticate(ALL)
    inspection = get_inspection(iid)
    rows = apply_filters(by_seq(findings_of(inspection["id"])), {
        "finding_type": v.query_str("finding_type"),
    })
    return listing(rows, finding_out)


@bp.post("/inspections/<iid>/graph-complete")
def graph_complete(iid):
    user_id, _role = authenticate(("FieldInspector",))
    inspection = get_inspection(iid)
    if inspection["inspector_id"] != user_id:
        raise not_owner("a FieldInspector may only sign their own graph")

    payload = v.body()
    attested = v.get_bool(payload, "no_findings_attested", required=False, default=False)

    if inspection["status"] != "DRAFT":
        raise invalid_state("Inspection", "only a DRAFT graph may be signed")

    inspector = get_inspector(inspection["inspector_id"])
    require_license_active(inspector)
    require_license_unexpired(inspector)
    require_category(inspector, "WDO_INSPECTOR")

    rows = findings_of(inspection["id"])
    if len(rows) == 0 and not attested:
        raise ApiError("ERR_GRAPH_INCOMPLETE", 422,
                       "a zero-notation graph may only be signed with no_findings_attested true")

    inspection["no_findings_attested"] = attested
    inspection["status"] = "GRAPHED"
    inspection["graph_completed_at"] = clock.now()
    recompute_inspection_rollups(inspection)
    touch(inspection)

    prop = db.properties.get(inspection["property_id"])
    if prop is not None:
        recompute_property_ledger(prop)

    return ok(inspection_out(inspection))
