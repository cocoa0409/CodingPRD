"""Promotion programs under three-tier limits (§3.9, §2.8)."""

from flask import Blueprint

import clock
import db
from auth import ROLE_BREWER_ADMIN, ROLE_WHOLESALER_PRINCIPAL, require_roles
from db import touch
from envelope import created
from errors import (ApiError, ERR_BRAND_SCOPE_MISMATCH, ERR_DUPLICATE_OPT_IN,
                    ERR_INVALID_WINDOW, ERR_NOT_FOUND,
                    ERR_OPT_IN_WINDOW_CLOSED,
                    ERR_RETAIL_PRICE_MANDATE_PROHIBITED,
                    ERR_PROMOTION_WINDOW_OVERLAP,
                    ERR_WHOLESALER_NOT_ELIGIBLE)
from validate import field, get_body, validate_body

bp = Blueprint("promotions", __name__)


@bp.route("/promotion-programs", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def create_program(user_id, caller_role):
    data, _ = validate_body(get_body(), {
        "brand_code": field("string", required=True),
        "starts_at": field("datetime", required=True),
        "ends_at": field("datetime", required=True),
        "suggested_discount_pct": field("number", required=True),
        "mandated_retail_price_cents": field("integer", nullable=True),
    })
    if data["mandated_retail_price_cents"] is not None:
        raise ApiError(ERR_RETAIL_PRICE_MANDATE_PROHIBITED,
                       "A manufacturer-mandated retail price violates "
                       "three-tier law", 422)
    starts_at = clock.parse_iso(data["starts_at"])
    ends_at = clock.parse_iso(data["ends_at"])
    if ends_at <= starts_at:
        raise ApiError(ERR_INVALID_WINDOW,
                       "ends_at must be strictly after starts_at", 422)
    for other in db.programs.values():
        if other["brand_code"] != data["brand_code"]:
            continue
        if other["status"] == "CLOSED":
            continue
        other_start = clock.parse_iso(other["starts_at"])
        other_end = clock.parse_iso(other["ends_at"])
        # Half-open windows: adjacency (ends_at == starts_at) is allowed.
        if starts_at < other_end and other_start < ends_at:
            raise ApiError(ERR_PROMOTION_WINDOW_OVERLAP,
                           "Window overlaps another non-CLOSED program for this "
                           "brand", 409)
    program = db.stamped()
    program.update({
        "brand_code": data["brand_code"],
        "starts_at": clock.format_iso(starts_at),
        "ends_at": clock.format_iso(ends_at),
        "suggested_discount_pct": data["suggested_discount_pct"],
        "mandated_retail_price_cents": None,
        "status": "OPEN",
        "opt_ins": [],
    })
    db.programs[program["id"]] = program
    return created(program)


@bp.route("/promotion-programs/<pid>/opt-ins", methods=["POST"])
@require_roles(ROLE_WHOLESALER_PRINCIPAL)
def opt_in(pid, user_id, caller_role):
    program = db.programs.get(pid)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, "Promotion program not found", 404)
    wholesaler = db.wholesalers.get(user_id)
    if wholesaler is None:
        raise ApiError(ERR_NOT_FOUND, "Wholesaler not found", 404)
    if (program["status"] != "OPEN"
            or clock.now() >= clock.parse_iso(program["ends_at"])):
        raise ApiError(ERR_OPT_IN_WINDOW_CLOSED,
                       "The promotion program is not open for opt-ins", 409)
    if wholesaler["status"] != "APPOINTED":
        raise ApiError(ERR_WHOLESALER_NOT_ELIGIBLE,
                       "Only an APPOINTED wholesaler may opt in", 409)
    if not db.brand_in_scope(wholesaler["id"], program["brand_code"]):
        raise ApiError(ERR_BRAND_SCOPE_MISMATCH,
                       "The program brand is outside the wholesaler's ACTIVE "
                       "agreement brand scope", 422)
    for entry in program["opt_ins"]:
        if entry["wholesaler_id"] == wholesaler["id"]:
            raise ApiError(ERR_DUPLICATE_OPT_IN,
                           "The wholesaler has already opted into this program",
                           409)
    program["opt_ins"].append({
        "wholesaler_id": wholesaler["id"],
        "opted_at": clock.now_iso(),
    })
    touch(program)
    return created(program)
