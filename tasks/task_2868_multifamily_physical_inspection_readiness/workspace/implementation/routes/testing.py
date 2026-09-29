"""Test-driving endpoints: the logical clock and historical seeding
(PRD 2.5, 3.9)."""

from flask import Blueprint

import auth
import calc
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common, inspections

bp = Blueprint("testing", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.authenticate([auth.ADMIN])
    values = shapes.validate([shapes.F("current_utc", "datetime")])
    derive.advance_clock(shapes.instant(values, "current_utc"))
    return envelope.ok_null()


@bp.post("/_inject/completed-inspection-history")
def inject_history():
    auth.authenticate([auth.ADMIN])
    values = shapes.validate(
        [
            shapes.F("property_id", "string"),
            shapes.F("standard_id", "string"),
            shapes.F("finalized_at", "datetime"),
            shapes.F("defect_definition_ids", "string_list"),
            shapes.F("unit_id", "string", required=False),
        ]
    )
    prop = common.body_fetch("property", values["property_id"])
    standard = common.body_fetch("standard", values["standard_id"])
    definitions = [
        common.body_fetch("definition", definition_id)
        for definition_id in values["defect_definition_ids"]
    ]
    unit = None
    if values.get("unit_id"):
        unit = common.body_fetch("unit", values["unit_id"])
    if standard["adoption_status"] != "ADOPTED":
        raise ApiError(
            "ERR_STANDARD_NOT_ADOPTED", "The cited standard is not ADOPTED."
        )

    finalized_at = values["finalized_at"]
    insp = inspections.new_inspection_row(
        prop["id"], standard["id"], finalized_at, finalized_at, "INITIAL"
    )
    insp["status"] = "CLOSED"
    insp["scored_at"] = finalized_at
    insp["finalized_at"] = finalized_at
    insp["cap_required"] = False

    for definition in definitions:
        deficiency = {
            "inspection_id": insp["id"],
            "sweep_id": None,
            "defect_definition_id": definition["id"],
            "unit_id": unit["id"] if unit is not None else None,
            "supersedes_deficiency_id": None,
            "source": "INSPECTION",
            "inspectable_area": definition["inspectable_area"],
            "severity": definition["severity"],
            "status": "VERIFIED",
            "observed_at": finalized_at,
            "correction_due_at": calc.add_hours(
                finalized_at, definition["correction_deadline_hours"]
            ),
            "corrected_at": finalized_at,
            "verified_at": finalized_at,
            "points_deducted": calc.deficiency_points(
                definition, definition["inspectable_area"], None, unit
            ),
            "recurrence_applied": False,
            "inspection_version_after_record": None,
            "note": None,
        }
        store.stamp_new(deficiency)
        store.deficiencies[deficiency["id"]] = deficiency

    if unit is not None:
        derive.recompute_unit_prior_count(unit)
    return envelope.created(insp)
