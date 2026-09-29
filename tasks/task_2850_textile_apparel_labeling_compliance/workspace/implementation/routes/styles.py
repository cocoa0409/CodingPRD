"""Styles, fiber declarations and the supply graph (PRD 3.2 / 3.3)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import services
from auth import require_roles, scope_brand, scope_style
from envelope import created, listing, ok
from errors import fail
from serializers import compliance_summary_json, material_json, style_json
from store import create_row, db, ordered, touch
from util import dec, r1, r2
from validate import (body, find_brand, find_market, find_material_input,
                      find_style, present, req_array, req_enum, req_int,
                      req_number, req_string, distinct_codes)

bp = Blueprint("styles", __name__)

PRODUCT_CLASSES = ("WOVEN_OUTERWEAR", "KNIT_TOP", "HOSIERY", "HOME_TEXTILE")
STAGES = ("FIBER", "YARN", "FABRIC", "CUT_AND_SEW", "TRIM")
MARKET_CODE_RE = r"^[A-Z_]{2,8}$"


def resolve_market_codes(payload, field):
    """Ladder step 5: every market code in the body must resolve to a regime."""
    value = payload.get(field)
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str):
                find_market(entry)


def parse_fiber_lines(payload, field, required):
    """Ladder step 6 shape check over the declared_fibers array."""
    if not present(payload, field):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return []
    raw = payload[field]
    if not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % field)
    if required and len(raw) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % field)
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each declared fiber must be an object.")
        name = req_string(entry, "fiber_generic_name", min_len=1, pattern=r"^[A-Z ]+$")
        pct = req_number(entry, "declared_pct", 1)
        exempt = entry.get("ornamentation_exempt", False)
        if exempt is None:
            exempt = False
        if not isinstance(exempt, bool):
            fail("ERR_INVALID_REQUEST", "Field 'ornamentation_exempt' must be a boolean.")
        lines.append({"fiber_generic_name": name, "declared_pct": pct,
                      "ornamentation_exempt": exempt})
    return lines


def check_fiber_sum(lines):
    """Ladder step 23: distinctness and an exact 100.0 sum on a non-empty array."""
    if not lines:
        return
    seen = set()
    for line in lines:
        if line["fiber_generic_name"] in seen:
            fail("ERR_FIBER_PERCENT_SUM", "Fiber names must be distinct.")
        seen.add(line["fiber_generic_name"])
    total = sum((line["declared_pct"] for line in lines), Decimal("0"))
    if r1(total) != dec("100.0"):
        fail("ERR_FIBER_PERCENT_SUM", "Declared percentages must sum to exactly 100.0.")


@bp.post("/labeling/styles")
def create_style():
    require_roles("BrandAdmin", "ComplianceAdmin")
    payload = body()
    scope_brand(payload.get("brand_id"))                      # ladder 4
    if present(payload, "brand_id"):                          # ladder 5
        find_brand(payload["brand_id"])
    resolve_market_codes(payload, "target_market_codes")
    brand_id = req_string(payload, "brand_id")                # ladder 6
    style_code = req_string(payload, "style_code", min_len=1, max_len=32)
    product_class = req_enum(payload, "product_class", PRODUCT_CLASSES)
    markets = distinct_codes(req_array(payload, "target_market_codes"),
                             "target_market_codes", MARKET_CODE_RE)
    weight = req_number(payload, "net_weight_grams", 1, exclusive_min=0)
    lines = parse_fiber_lines(payload, "declared_fibers", required=False)
    check_fiber_sum(lines)                                    # ladder 23
    for row in db.styles.values():                            # ladder 26
        if row["brand_id"] == brand_id and row["style_code"] == style_code:
            fail("ERR_DUPLICATE_STYLE_CODE",
                 "Style code %s already exists for this brand." % style_code)
    row = create_row(db.styles, {
        "brand_id": brand_id,
        "style_code": style_code,
        "product_class": product_class,
        "target_market_codes": markets,
        "net_weight_grams": weight,
        "declared_fibers": lines,
        "substantiation_state": "FIBER_DECLARED",
        "origin_state": "ORIGIN_UNDETERMINED",
    })
    return created(style_json(row))


@bp.get("/labeling/styles/<sid>")
def read_style(sid):
    require_roles("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
                  "AccreditedLab", "CustomsOfficer", "Auditor")
    return ok(style_json(find_style(sid)))


@bp.get("/labeling/brands/<bid>/styles")
def list_brand_styles(bid):
    require_roles("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
                  "Auditor")
    find_brand(bid)
    rows = ordered([s for s in db.styles.values() if s["brand_id"] == bid])
    args = request.args
    if args.get("substantiation_state") is not None:
        rows = [r for r in rows if r["substantiation_state"] == args.get("substantiation_state")]
    if args.get("origin_state") is not None:
        rows = [r for r in rows if r["origin_state"] == args.get("origin_state")]
    if args.get("label_readiness") is not None:
        rows = [r for r in rows if calc.label_readiness(r) == args.get("label_readiness")]
    return listing(rows, style_json)


@bp.put("/labeling/styles/<sid>/fiber-declaration")
def replace_declaration(sid):
    require_roles("BrandAdmin", "ComplianceAdmin")
    style = find_style(sid)                                   # ladder 3
    scope_style(style)                                        # ladder 4
    payload = body()
    lines = parse_fiber_lines(payload, "declared_fibers", required=True)   # ladder 6
    expected = req_int(payload, "expected_style_version")
    if expected != style["version"]:                          # ladder 8
        fail("ERR_STALE_STYLE_VERSION", "The style has moved since it was read.")
    if services.live_permanent_labels(style["id"]):           # ladder 9
        fail("ERR_LABEL_STATE_INVALID",
             "A permanent label of this style has already asserted the declaration.")
    check_fiber_sum(lines)                                    # ladder 23
    previous = style["substantiation_state"]
    style["declared_fibers"] = lines
    if previous == "FIBER_SUBSTANTIATED":
        services.supersede_passed_fiber_tests(style["id"])
    style["substantiation_state"] = "FIBER_DECLARED"
    touch(style)
    return ok(style_json(style))


@bp.post("/labeling/styles/<sid>/material-inputs")
def append_material_input(sid):
    require_roles("BrandAdmin", "ComplianceAdmin")
    style = find_style(sid)                                   # ladder 3
    scope_style(style)                                        # ladder 4
    payload = body()
    parent = None                                             # ladder 5
    if present(payload, "parent_input_id"):
        parent = find_material_input(payload["parent_input_id"])
    stage = req_enum(payload, "stage", STAGES)                # ladder 6
    country = req_string(payload, "country_code", min_len=2, max_len=2, pattern=r"^[A-Z]{2}$")
    value_added = req_number(payload, "value_added_usd", 2, minimum=0)
    weight = req_number(payload, "weight_grams", 1, minimum=0)
    ornamentation = payload.get("is_ornamentation", False)
    if ornamentation is None:
        ornamentation = False
    if not isinstance(ornamentation, bool):
        fail("ERR_INVALID_REQUEST", "Field 'is_ornamentation' must be a boolean.")
    # ladder 25: the supply graph must respect the stage rank ladder.
    if stage == "TRIM" and parent is not None:
        fail("ERR_MATERIAL_STAGE_ORDER", "A TRIM node must be a graph root.")
    if parent is not None:
        if parent["style_id"] != style["id"]:
            fail("ERR_MATERIAL_STAGE_ORDER", "The parent node belongs to another style.")
        if calc.STAGE_RANK[parent["stage"]] >= calc.STAGE_RANK[stage]:
            fail("ERR_MATERIAL_STAGE_ORDER",
                 "The parent stage rank must be strictly less than this node's stage rank.")
    row = create_row(db.material_inputs, {                    # HOP 1
        "style_id": style["id"],
        "parent_input_id": parent["id"] if parent is not None else None,
        "stage": stage,
        "country_code": country,
        "value_added_usd": value_added,
        "weight_grams": weight,
        "is_ornamentation": ornamentation,
        "depth": 0 if parent is None else parent["depth"] + 1,
    })
    if style["origin_state"] == "ORIGIN_ISSUED":              # HOP 2..4
        services.origin_void_cascade(style)
        style["origin_state"] = "ORIGIN_UNDETERMINED"
    # PRD 2.5: the determination guard exists so that a create carrying a stale
    # expected_style_version is caught when "a supply graph ... has since gained
    # or lost a node", and PRD 2.9 makes version bumps the mechanism by which
    # those guards notice the world moved.  So every append bumps the style's
    # version by exactly 1, whether or not an issued determination was voided.
    touch(style)
    return created(material_json(row))


@bp.get("/labeling/material-inputs/<mid>")
def read_material_input(mid):
    require_roles("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "Auditor")
    return ok(material_json(find_material_input(mid)))


@bp.get("/labeling/material-inputs")
def list_material_inputs():
    require_roles("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "Auditor")
    rows = list(db.material_inputs.values())
    args = request.args
    if args.get("style_id") is not None:
        rows = [r for r in rows if r["style_id"] == args.get("style_id")]
    if args.get("parent_input_id") is not None:
        rows = [r for r in rows if r["parent_input_id"] == args.get("parent_input_id")]
    if args.get("stage") is not None:
        rows = [r for r in rows if r["stage"] == args.get("stage")]
    if args.get("country_code") is not None:
        rows = [r for r in rows if r["country_code"] == args.get("country_code")]
    # PRD 2.3: depth ascending, then created_at ascending within a depth.
    rows.sort(key=lambda r: (r["depth"], r["created_at"], r["_seq"]))
    return listing(rows, material_json)


@bp.get("/labeling/styles/<sid>/compliance-summary")
def compliance_summary(sid):
    require_roles("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
                  "Auditor")
    return ok(compliance_summary_json(find_style(sid)))
