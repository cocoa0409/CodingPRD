"""Origin determinations: two legal methods over one supply graph (PRD 3.3)."""
from flask import Blueprint, request

import calc
from auth import require_roles
from envelope import created, listing, ok
from errors import fail
from serializers import origin_json
from store import create_row, db, ordered, touch
from validate import (body, find_origin_determination, find_style, present,
                      req_enum, req_int, req_string)

bp = Blueprint("origins", __name__)

METHODS = ("SUBSTANTIAL_TRANSFORMATION", "YARN_FORWARD")


@bp.post("/labeling/origin-determinations")
def draft_determination():
    require_roles("ComplianceAdmin", "LabelingSpecialist")
    payload = body()
    style = None                                              # ladder 5
    if present(payload, "style_id"):
        style = find_style(payload["style_id"])
    req_string(payload, "style_id")                            # ladder 6
    expected = req_int(payload, "expected_style_version")
    if expected != style["version"]:                           # ladder 8
        fail("ERR_STALE_STYLE_VERSION", "The style has moved since it was read.")
    nodes, a_pool, b_pool = calc.origin_pools(style["id"])     # ladder 32
    if not a_pool or not b_pool:
        fail("ERR_ORIGIN_GRAPH_INSUFFICIENT",
             "The supply graph does not support both legal methods.")
    st_country, yf_country, node_count = calc.origin_country_determination(style["id"])
    previous = style["origin_state"]
    if previous == "ORIGIN_DRAFTED":
        for row in ordered(list(db.origin_determinations.values())):
            if row["style_id"] == style["id"] and row["state"] == "DRAFT":
                row["state"] = "SUPERSEDED"
                touch(row)
    determination = create_row(db.origin_determinations, {
        "style_id": style["id"],
        "state": "DRAFT",
        "method_pinned": None,
        "st_country": st_country,
        "yf_country": yf_country,
        "divergent": st_country != yf_country,
        "determined_country": None,
        "graph_node_count": node_count,
        "issued_at": None,
    })
    style["origin_state"] = "ORIGIN_DRAFTED"
    touch(style)
    return created(origin_json(determination))


@bp.post("/labeling/origin-determinations/<oid>/issue")
def issue_determination(oid):
    require_roles("ComplianceAdmin")
    determination = find_origin_determination(oid)              # ladder 3
    payload = body()
    method = req_enum(payload, "method", METHODS)                # ladder 6
    if determination["state"] != "DRAFT":                        # ladder 9
        fail("ERR_ORIGIN_STATE_INVALID", "Only a drafted determination may be issued.")
    style = db.styles.get(determination["style_id"])
    for row in ordered(list(db.origin_determinations.values())):
        if (row["style_id"] == determination["style_id"] and row["state"] == "ISSUED"
                and row["id"] != determination["id"]):
            row["state"] = "SUPERSEDED"
            touch(row)
    determination["method_pinned"] = method
    determination["determined_country"] = (determination["st_country"]
                                           if method == "SUBSTANTIAL_TRANSFORMATION"
                                           else determination["yf_country"])
    determination["issued_at"] = db.now()
    determination["state"] = "ISSUED"
    touch(determination)
    style["origin_state"] = "ORIGIN_ISSUED"
    touch(style)
    return ok(origin_json(determination))


@bp.get("/labeling/origin-determinations/<oid>")
def read_determination(oid):
    require_roles("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
                  "CustomsOfficer", "Auditor")
    return ok(origin_json(find_origin_determination(oid)))


@bp.get("/labeling/styles/<sid>/origin-determinations")
def list_style_determinations(sid):
    require_roles("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
                  "Auditor")
    style = find_style(sid)
    rows = ordered([d for d in db.origin_determinations.values()
                    if d["style_id"] == style["id"]])
    args = request.args
    if args.get("state") is not None:
        rows = [r for r in rows if r["state"] == args.get("state")]
    if args.get("method_pinned") is not None:
        rows = [r for r in rows if r["method_pinned"] == args.get("method_pinned")]
    return listing(rows, origin_json)
