"""Comparison studies (bench-top and consumer panel)."""
from flask import Blueprint

import calculations as calc
import serializers as ser
from db import db
from domain import (
    get_item,
    get_study,
    guard_program_open,
    new_row,
    program_of_item,
    studies_of_item,
    touch,
)
from errors import fail
from listing import STUDY_STATUS_SET, STUDY_TYPE_SET, VERDICT_SET, no_query, paginate
from middleware import ALL_ROLES, ROLE_QUALITY_AUDITOR, Field, authenticate, validate_body
from response import object_response


bp = Blueprint("studies", __name__)

DELTA_FIELDS = ("appearance_delta", "aroma_delta", "texture_delta", "flavor_delta")
PANEL_FIELDS = ("n_panelists", "prefer_pl_count", "prefer_nb_count", "no_preference_count")


def _delta():
    return Field(
        "number",
        check=lambda v: -3.0 <= v <= 3.0,
        detail="must be a decimal from -3.0 through +3.0 inclusive",
    )


@bp.post("/private-label/comparison-studies")
def create_study():
    authenticate((ROLE_QUALITY_AUDITOR,))
    schema = {
        "item_id": Field("string", required=True),
        "study_type": Field("string", required=True, enum=STUDY_TYPE_SET),
        "nb_control_lot_code": Field("string", required=True),
        "n_panelists": Field(
            "integer", check=lambda v: v >= 1, detail="must be at least 1"
        ),
        "prefer_pl_count": Field("integer", check=lambda v: v >= 0, detail="must not be negative"),
        "prefer_nb_count": Field("integer", check=lambda v: v >= 0, detail="must not be negative"),
        "no_preference_count": Field("integer", check=lambda v: v >= 0, detail="must not be negative"),
    }
    for name in DELTA_FIELDS:
        schema[name] = _delta()
    body = validate_body(schema)
    if body["study_type"] == "BENCH_TOP":
        for name in DELTA_FIELDS:
            if name not in body["_supplied"]:
                fail("ERR_INVALID_REQUEST", "'%s' is required for a BENCH_TOP study." % name)
    else:
        for name in PANEL_FIELDS:
            if name not in body["_supplied"]:
                fail("ERR_INVALID_REQUEST", "'%s' is required for a CONSUMER_PANEL study." % name)
        counted = body["prefer_pl_count"] + body["prefer_nb_count"] + body["no_preference_count"]
        if body["n_panelists"] != counted:
            fail(
                "ERR_INVALID_REQUEST",
                "'n_panelists' must equal the three preference counts added together.",
            )
    item = get_item(body["item_id"])
    guard_program_open(program_of_item(item))
    row = new_row(
        {
            "item_id": item["id"],
            "study_type": body["study_type"],
            "nb_control_lot_code": body["nb_control_lot_code"],
            "n_panelists": body.get("n_panelists"),
            "prefer_pl_count": body.get("prefer_pl_count"),
            "prefer_nb_count": body.get("prefer_nb_count"),
            "no_preference_count": body.get("no_preference_count"),
            "parity_index": None,
            "preference_share_pct": None,
            "verdict": None,
            "status": "DRAFT",
        }
    )
    for name in DELTA_FIELDS:
        row[name] = body.get(name)
    db.studies[row["id"]] = row
    return object_response(ser.study_out(row), 201)


@bp.get("/private-label/comparison-studies/<study_id>")
def read_study(study_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.study_out(get_study(study_id)))


@bp.get("/private-label/comparison-studies")
def list_studies():
    authenticate(ALL_ROLES)
    return paginate(
        db.studies,
        {
            "item_id": "string",
            "study_type": STUDY_TYPE_SET,
            "verdict": VERDICT_SET,
            "status": STUDY_STATUS_SET,
        },
        ser.study_out,
    )


def _bench_tops(item_id):
    return [
        s
        for s in studies_of_item(item_id)
        if s["status"] == "FINALIZED" and s["study_type"] == "BENCH_TOP"
    ]


def _panels(item_id):
    return [
        s
        for s in studies_of_item(item_id)
        if s["status"] == "FINALIZED" and s["study_type"] == "CONSUMER_PANEL"
    ]


def _gate_satisfied(item):
    tier = item["tier"]
    benches = _bench_tops(item["id"])
    if tier == "OPENING_PRICE":
        return any(s["parity_index"] >= calc.D("70.00") for s in benches)
    if tier == "NBE":
        bench_ok = any(s["parity_index"] >= calc.D("85.00") for s in benches)
        panel_ok = any(s["verdict"] in ("PARITY", "SUPERIOR") for s in _panels(item["id"]))
        return bench_ok and panel_ok
    bench_ok = any(
        s["parity_index"] >= calc.D("92.00") and calc.D(s["flavor_delta"]) >= calc.D("0.0")
        for s in benches
    )
    panel_ok = any(s["verdict"] == "SUPERIOR" for s in _panels(item["id"]))
    return bench_ok and panel_ok


@bp.post("/private-label/comparison-studies/<study_id>/finalize")
def finalize_study(study_id):
    authenticate((ROLE_QUALITY_AUDITOR,))
    validate_body({})
    study = get_study(study_id)
    item = get_item(study["item_id"])
    guard_program_open(program_of_item(item))
    if study["status"] != "DRAFT":
        fail("ERR_STUDY_NOT_DRAFT")
    if item["development_status"] not in ("SOURCED", "BENCHMARKED"):
        fail("ERR_ITEM_STATE_INVALID")
    if study["study_type"] == "BENCH_TOP":
        index, verdict = calc.bench_top_parity_index(
            study["appearance_delta"],
            study["aroma_delta"],
            study["texture_delta"],
            study["flavor_delta"],
        )
        study["parity_index"] = index
        study["verdict"] = verdict
    else:
        share, verdict = calc.panel_preference_share(
            study["prefer_pl_count"], study["prefer_nb_count"]
        )
        study["preference_share_pct"] = share
        study["verdict"] = verdict
    study["status"] = "FINALIZED"
    touch(study)
    if item["development_status"] == "SOURCED" and _gate_satisfied(item):
        item["development_status"] = "BENCHMARKED"
        touch(item)
    return object_response(ser.study_out(study))
