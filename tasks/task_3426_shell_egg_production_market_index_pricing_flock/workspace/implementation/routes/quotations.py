"""Market quotations (PRD §3.4): append-only price index observations, unique
on (region_code, size_class, effective_date, source). Quotations carry only id
and created_at — no updated_at, no version (PRD §2.5)."""

from flask import Blueprint, request

from auth import authenticate, require_role
from db import STORE, stamp_new
from errors import ApiError, ERR_DUPLICATE_QUOTATION, ERR_INVALID_REQUEST
from helpers import list_response
from serialize import serialize_quotation
from util import REGIONS, SIZE_CLASSES, SOURCES, parse_datetime, success_object
from validate import apply_values, get_body, validate_payload

bp = Blueprint("quotations", __name__)


@bp.route("/api/market-quotations", methods=["POST"])
def create_quotation():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    values, raws = validate_payload(
        get_body(),
        {
            "region_code": {"kind": "enum", "required": True, "enum": REGIONS},
            "size_class": {
                "kind": "enum", "required": True, "enum": SIZE_CLASSES,
            },
            "price_cents_per_dozen": {"kind": "int", "required": True, "gt": 0},
            "effective_date": {"kind": "datetime", "required": True},
            "source": {"kind": "enum", "enum": SOURCES, "default": "URNER_BARRY"},
        },
    )
    for q in STORE.quotations.values():
        if (
            q["region_code"] == values["region_code"]
            and q["size_class"] == values["size_class"]
            and q["_dt_effective_date"] == values["effective_date"]
            and q["source"] == values["source"]
        ):
            raise ApiError(
                ERR_DUPLICATE_QUOTATION,
                409,
                "a quotation already exists for this "
                "(region_code, size_class, effective_date, source)",
            )
    quotation = {
        "region_code": values["region_code"],
        "size_class": values["size_class"],
        "price_cents_per_dozen": values["price_cents_per_dozen"],
        "source": values["source"],
    }
    apply_values(quotation, {"effective_date": values["effective_date"]},
                 {"effective_date": raws["effective_date"]})
    stamp_new(quotation, versioned=False)
    STORE.quotations[quotation["id"]] = quotation
    return success_object(serialize_quotation(quotation), 201)


@bp.route("/api/market-quotations", methods=["GET"])
def list_quotations():
    authenticate()
    items = list(STORE.quotations.values())
    region = request.args.get("region_code")
    if region is not None:
        items = [q for q in items if q["region_code"] == region]
    size = request.args.get("size_class")
    if size is not None:
        items = [q for q in items if q["size_class"] == size]
    source = request.args.get("source")
    if source is not None:
        items = [q for q in items if q["source"] == source]
    eff_from_raw = request.args.get("effective_from")
    if eff_from_raw is not None:
        try:
            eff_from = parse_datetime(eff_from_raw)
        except ValueError:
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "effective_from must be ISO 8601"
            )
        items = [q for q in items if q["_dt_effective_date"] >= eff_from]
    eff_to_raw = request.args.get("effective_to")
    if eff_to_raw is not None:
        try:
            eff_to = parse_datetime(eff_to_raw)
        except ValueError:
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "effective_to must be ISO 8601"
            )
        items = [q for q in items if q["_dt_effective_date"] <= eff_to]
    return list_response(items, serialize_quotation)
