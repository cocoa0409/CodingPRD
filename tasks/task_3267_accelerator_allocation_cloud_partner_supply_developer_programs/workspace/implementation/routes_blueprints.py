"""Reference architectures and validation evidence packs."""

import constants as K
from auth import roles
from error import CatalogError, ERR_BLUEPRINT_NOT_CERTIFIED, ERR_EVIDENCE_INSUFFICIENT, ERR_INVALID_STATE
from envelope import created, ok, page
from rules import blueprint_or_404, resource_or_404
from services import serialize
from store import DB
from util import by_created, paginate, require, require_enum

GROUP = "blueprints"


# ------------------------------------------------------------- blueprints --
def _create(caller):
    from flask import request
    body = request.raw_payload or {}
    blueprint = DB.mint({
        "blueprint_code": require(body, "blueprint_code"),
        "blueprint_type": require_enum(require(body, "blueprint_type"), K.BLUEPRINT_TYPES, "blueprint_type"),
        "target_tdp_watts": require(body, "target_tdp_watts", "int"),
        "required_validation_minutes": require(body, "required_validation_minutes", "int"),
        "evaluation_deadline_days": require(body, "evaluation_deadline_days", "int"),
        "blueprint_status": "DRAFT",
        "era_index": 1,
    })
    DB.blueprints[blueprint["id"]] = blueprint
    return created(serialize(blueprint))


def _list(caller):
    from flask import request
    rows = by_created(list(DB.blueprints.values()))
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read(caller, blueprint_id):
    return ok(serialize(blueprint_or_404(blueprint_id)))


def _certify(caller, blueprint_id):
    blueprint = blueprint_or_404(blueprint_id)
    if blueprint.get("blueprint_status") != "DRAFT":
        raise CatalogError(ERR_INVALID_STATE, "Only a DRAFT blueprint may be certified.")
    blueprint["blueprint_status"] = "CERTIFIED"
    DB.touch(blueprint)
    return ok(serialize(blueprint))


def _retire(caller, blueprint_id):
    blueprint = blueprint_or_404(blueprint_id)
    if blueprint.get("blueprint_status") != "CERTIFIED":
        raise CatalogError(ERR_INVALID_STATE, "Only a CERTIFIED blueprint may be retired.")
    blueprint["blueprint_status"] = "RETIRED"
    DB.touch(blueprint)
    return ok(serialize(blueprint))


# ------------------------------------------------------------- validations --
def _list_evidence(caller):
    from flask import request
    rows = by_created(list(DB.evidences.values()))
    partner_id = request.args.get("partner_id")
    blueprint_id = request.args.get("blueprint_id")
    if partner_id:
        rows = [row for row in rows if row.get("partner_id") == partner_id]
    if blueprint_id:
        rows = [row for row in rows if row.get("blueprint_id") == blueprint_id]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read_evidence(caller, evidence_id):
    return ok(serialize(resource_or_404("evidences", evidence_id, "validation evidence")))


def _accept(caller, evidence_id):
    evidence = resource_or_404("evidences", evidence_id, "validation evidence")
    if evidence.get("evidence_pack_status") != "SUBMITTED":
        raise CatalogError(ERR_INVALID_STATE, "Only SUBMITTED evidence may be accepted.")
    blueprint = blueprint_or_404(evidence.get("blueprint_id"))
    if int(evidence.get("validation_minutes", 0)) < int(blueprint.get("required_validation_minutes", 0)):
        raise CatalogError(ERR_EVIDENCE_INSUFFICIENT)
    evidence["evidence_pack_status"] = "ACCEPTED"
    DB.touch(evidence)
    return ok(serialize(evidence))


def _reject_evidence(caller, evidence_id):
    evidence = resource_or_404("evidences", evidence_id, "validation evidence")
    if evidence.get("evidence_pack_status") != "SUBMITTED":
        raise CatalogError(ERR_INVALID_STATE, "Only SUBMITTED evidence may be rejected.")
    evidence["evidence_pack_status"] = "REJECTED"
    DB.touch(evidence)
    # Losing the round supersedes the blueprint's era when it was the only
    # accepted pack in the current era (PRD 3.2).
    blueprint = DB.blueprints.get(evidence.get("blueprint_id"))
    if blueprint is not None:
        remaining = [
            row for row in DB.evidences.values()
            if row.get("blueprint_id") == blueprint["id"]
            and row.get("evidence_pack_status") == "ACCEPTED"
            and int(row.get("era_index", 1)) == int(blueprint.get("era_index", 1))
        ]
        if not remaining:
            blueprint["era_index"] = int(blueprint.get("era_index", 1)) + 1
            DB.touch(blueprint)
    return ok(serialize(evidence))


ROUTES = [
    ("POST", "/accelerators/blueprints", _create, ("SupplyPlanner",)),
    ("GET", "/accelerators/blueprints", _list, ("SupplyPlanner",)),
    ("GET", "/accelerators/blueprints/<blueprint_id>", _read, ("SupplyPlanner",)),
    ("POST", "/accelerators/blueprints/<blueprint_id>/certify", _certify, ("SupplyPlanner",)),
    ("POST", "/accelerators/blueprints/<blueprint_id>/retire", _retire, ("SupplyPlanner",)),
    ("GET", "/accelerators/validations", _list_evidence, ("PartnerProgramManager",)),
    ("GET", "/accelerators/validations/<evidence_id>", _read_evidence, ("PartnerProgramManager",)),
    ("POST", "/accelerators/validations/<evidence_id>/accept", _accept, ("PartnerProgramManager",)),
    ("POST", "/accelerators/validations/<evidence_id>/reject", _reject_evidence, ("PartnerProgramManager",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])