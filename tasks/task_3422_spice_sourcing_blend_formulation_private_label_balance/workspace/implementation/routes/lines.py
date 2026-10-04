"""ProductionLine master data (PRD 3.5). The line's version drives the
run-scheduling optimistic-concurrency check (PRD 2.7)."""
from flask import Blueprint

from helpers import (CHANGEOVER_CLASSES, F, new_entity, not_found, pub,
                     require_roles, respond, validate_body, validation_error)
from state import DB

bp = Blueprint("lines", __name__)


@bp.post("/spice/lines")
@require_roles("PlatformAdmin")
def create_line():
    data = validate_body({
        "name": F("str", required=True),
        "capacity_kg_per_shift": F("int", required=True),
        "supported_changeover_classes": F("list", item_enum=CHANGEOVER_CLASSES,
                                          required=True),
    })
    if data["capacity_kg_per_shift"] <= 0:
        validation_error("capacity_kg_per_shift must be > 0")
    if len(data["supported_changeover_classes"]) == 0:
        validation_error("supported_changeover_classes must be non-empty")
    if "NONE" not in data["supported_changeover_classes"]:
        validation_error("supported_changeover_classes must contain NONE")
    line = new_entity(data)
    DB.production_lines[line["id"]] = line
    return respond(pub(line), 201)


@bp.get("/spice/lines/<line_id>")
@require_roles("PlatformAdmin", "ProductionScheduler", "FlavorScientist")
def get_line(line_id):
    line = DB.production_lines.get(line_id)
    if line is None:
        not_found("production line not found")
    return respond(pub(line))
