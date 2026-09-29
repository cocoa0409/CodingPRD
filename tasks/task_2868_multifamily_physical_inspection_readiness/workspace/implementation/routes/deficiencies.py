"""Deficiency reads, the owner's correction and the inspector's verification
(PRD 3.6)."""

from flask import Blueprint

import auth
import calc
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common

bp = Blueprint("deficiencies", __name__)


def _refresh_after_status_change(deficiency):
    """The shared tail of a correction or a verification."""
    if deficiency.get("unit_id"):
        unit = store.units.get(deficiency["unit_id"])
        if unit is not None:
            derive.recompute_unit_open_count(unit)
    property_id = auth.property_of_deficiency(deficiency)
    prop = store.properties.get(property_id)
    if prop is not None:
        derive.rederive_property(prop, bump_version=True)


@bp.get("/deficiencies/<deficiency_id>")
def read_deficiency(deficiency_id):
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    deficiency = common.fetch("deficiency", deficiency_id)
    auth.require_owner(role, user_id, auth.property_of_deficiency(deficiency))
    return envelope.ok(deficiency)


@bp.get("/deficiencies")
def list_deficiencies():
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    return common.listing(
        store.deficiencies.values(),
        [
            "inspection_id",
            "sweep_id",
            "unit_id",
            "defect_definition_id",
            "supersedes_deficiency_id",
            "source",
            "status",
            "severity",
        ],
        role=role,
        user_id=user_id,
        property_getter=auth.property_of_deficiency,
    )


@bp.post("/deficiencies/<deficiency_id>/correction")
def record_correction(deficiency_id):
    user_id, role = auth.authenticate([auth.OWNER])
    values = shapes.validate(
        [
            shapes.F("corrected_at", "datetime"),
            shapes.F("note", "string", required=False),
        ]
    )
    deficiency = common.fetch("deficiency", deficiency_id)
    auth.require_owner(role, user_id, auth.property_of_deficiency(deficiency))
    if deficiency["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError(
            "ERR_DEFICIENCY_INVALID_STATE",
            "Only an OPEN or OVERDUE deficiency may be corrected.",
        )
    if deficiency["severity"] == "LIFE_THREATENING":
        corrected = shapes.instant(values, "corrected_at")
        due = store.parse_instant(deficiency["correction_due_at"])
        if due is not None and corrected > due:
            raise ApiError(
                "ERR_LT_CORRECTION_DEADLINE_PASSED",
                "The twenty-four-hour correction obligation has already lapsed.",
            )
    deficiency["status"] = "CORRECTED"
    deficiency["corrected_at"] = values["corrected_at"]
    if values.get("note") is not None:
        deficiency["note"] = values["note"]
    store.touch(deficiency, bump_version=True)
    _refresh_after_status_change(deficiency)
    return envelope.ok(deficiency)


@bp.post("/deficiencies/<deficiency_id>/verification")
def record_verification(deficiency_id):
    auth.authenticate([auth.INSPECTOR])
    values = shapes.validate(
        [
            shapes.F("verification_result", "enum", values=shapes.VERIFICATION_RESULT),
            shapes.F("verified_at", "datetime"),
            shapes.F("note", "string", required=False),
        ]
    )
    deficiency = common.fetch("deficiency", deficiency_id)
    if deficiency["status"] != "CORRECTED":
        raise ApiError(
            "ERR_DEFICIENCY_INVALID_STATE",
            "Only a CORRECTED deficiency may be verified.",
        )
    if values["verification_result"] == "PASSED":
        deficiency["status"] = "VERIFIED"
        deficiency["verified_at"] = values["verified_at"]
    else:
        deficiency["status"] = "OPEN"
        deficiency["corrected_at"] = None
    if values.get("note") is not None:
        deficiency["note"] = values["note"]
    store.touch(deficiency, bump_version=True)
    _refresh_after_status_change(deficiency)
    return envelope.ok(deficiency)
