"""Inspection standards and their defect catalogue (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common

bp = Blueprint("standards", __name__)

WEIGHT_TOTAL = Decimal("100.00")


@bp.post("/inspection-standards")
def register_standard():
    auth.authenticate([auth.ADMIN])
    values = shapes.validate(
        [
            shapes.F("code", "string", min_len=1, max_len=32),
            shapes.F("name", "string"),
            shapes.F("effective_date", "datetime"),
            shapes.F("unit_weight_pct", "number", minimum="0.00", maximum="100.00"),
            shapes.F("inside_weight_pct", "number", minimum="0.00", maximum="100.00"),
            shapes.F("outside_weight_pct", "number", minimum="0.00", maximum="100.00"),
        ]
    )
    total = (
        values["unit_weight_pct"]
        + values["inside_weight_pct"]
        + values["outside_weight_pct"]
    )
    if calc.r2(total) != WEIGHT_TOTAL:
        raise ApiError(
            "ERR_WEIGHTS_NOT_NORMALIZED",
            "The three inspectable-area weights must sum to exactly 100.00.",
        )
    for row in store.standards.values():
        if row["code"] == values["code"] and row["adoption_status"] in ("DRAFT", "ADOPTED"):
            raise ApiError(
                "ERR_DUPLICATE_STANDARD_CODE",
                "A DRAFT or ADOPTED standard already holds code %s." % values["code"],
            )
    row = {
        "code": values["code"],
        "name": values["name"],
        "effective_date": values["effective_date"],
        "adoption_status": "DRAFT",
        "unit_weight_pct": calc.r2(values["unit_weight_pct"]),
        "inside_weight_pct": calc.r2(values["inside_weight_pct"]),
        "outside_weight_pct": calc.r2(values["outside_weight_pct"]),
        "adopted_at": None,
        "superseded_at": None,
        "defect_definition_count": 0,
        "life_threatening_definition_count": 0,
    }
    store.stamp_new(row)
    store.standards[row["id"]] = row
    return envelope.created(row)


@bp.post("/inspection-standards/<standard_id>/adopt")
def adopt_standard(standard_id):
    auth.authenticate([auth.ADMIN])
    values = shapes.validate([shapes.F("adopted_at", "datetime")])
    standard = common.fetch("standard", standard_id)
    if standard["adoption_status"] != "DRAFT":
        raise ApiError(
            "ERR_STANDARD_ALREADY_ADOPTED",
            "Only a DRAFT standard may be adopted.",
        )
    total = (
        calc.d(standard["unit_weight_pct"])
        + calc.d(standard["inside_weight_pct"])
        + calc.d(standard["outside_weight_pct"])
    )
    if calc.r2(total) != WEIGHT_TOTAL:
        raise ApiError(
            "ERR_WEIGHTS_NOT_NORMALIZED",
            "The three inspectable-area weights must sum to exactly 100.00.",
        )
    if standard["life_threatening_definition_count"] < 1:
        raise ApiError(
            "ERR_NO_LIFE_THREATENING_DEFINITION",
            "A standard defining no life-threatening defect cannot be adopted.",
        )
    standard["adoption_status"] = "ADOPTED"
    standard["adopted_at"] = values["adopted_at"]
    store.touch(standard, bump_version=True)
    for row in store.by_seq(list(store.standards.values())):
        if row["id"] == standard["id"]:
            continue
        if row["code"] == standard["code"] and row["adoption_status"] == "ADOPTED":
            row["adoption_status"] = "SUPERSEDED"
            row["superseded_at"] = standard["adopted_at"]
            store.touch(row, bump_version=True)
    return envelope.ok(standard)


@bp.get("/inspection-standards/<standard_id>")
def read_standard(standard_id):
    auth.authenticate(auth.ANY_ROLE)
    return envelope.ok(common.fetch("standard", standard_id))


@bp.get("/inspection-standards")
def list_standards():
    auth.authenticate(auth.ANY_ROLE)
    return common.listing(store.standards.values(), ["code", "adoption_status"])


@bp.post("/defect-definitions")
def register_definition():
    auth.authenticate([auth.ADMIN])
    values = shapes.validate(
        [
            shapes.F("standard_id", "string"),
            shapes.F("code", "string"),
            shapes.F("name", "string"),
            shapes.F("inspectable_area", "enum", values=shapes.INSPECTABLE_AREA),
            shapes.F("severity", "enum", values=shapes.SEVERITY),
            shapes.F("base_point_value", "number", minimum="0.01", maximum="40.00"),
            shapes.F("correction_deadline_hours", "integer", minimum=1),
        ]
    )
    standard = common.body_fetch("standard", values["standard_id"])
    for row in store.definitions.values():
        if row["standard_id"] == standard["id"] and row["code"] == values["code"]:
            raise ApiError(
                "ERR_DUPLICATE_DEFECT_CODE",
                "Defect code %s is already defined under this standard." % values["code"],
            )
    if (
        values["severity"] == "LIFE_THREATENING"
        and values["correction_deadline_hours"] != 24
    ):
        raise ApiError(
            "ERR_LT_DEADLINE_MUST_BE_24H",
            "A LIFE_THREATENING definition must declare correction_deadline_hours 24.",
        )
    row = {
        "standard_id": standard["id"],
        "code": values["code"],
        "name": values["name"],
        "inspectable_area": values["inspectable_area"],
        "severity": values["severity"],
        "base_point_value": calc.r2(values["base_point_value"]),
        "correction_deadline_hours": values["correction_deadline_hours"],
        "is_life_threatening": values["severity"] == "LIFE_THREATENING",
    }
    store.stamp_new(row)
    store.definitions[row["id"]] = row
    derive.recompute_standard_counters(standard)
    store.touch(standard, bump_version=True)
    return envelope.created(row)


@bp.get("/defect-definitions/<definition_id>")
def read_definition(definition_id):
    auth.authenticate(auth.ANY_ROLE)
    return envelope.ok(common.fetch("definition", definition_id))


@bp.get("/defect-definitions")
def list_definitions():
    auth.authenticate(auth.ANY_ROLE)
    return common.listing(
        store.definitions.values(), ["standard_id", "inspectable_area", "severity"]
    )
