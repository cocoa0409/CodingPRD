"""Configuration + OptionPackage endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB
from errors import (
    not_found, invalid_input, invalid_state, duplicate_key,
)
from middleware import require_roles
from response import success
from services.entity import stamp_new, touch


bp = Blueprint("configurations", __name__)

SEGMENTS = ("SEDAN", "SUV", "TRUCK", "VAN", "COUPE")
ALL_ROLES = ("ValuationAdmin", "DataOps", "DealerPartner", "Consumer", "Licensee")


def _config_view(c):
    return {
        "id": c["id"],
        "make": c["make"],
        "model": c["model"],
        "year": c["year"],
        "trim": c["trim"],
        "segment": c["segment"],
        "annual_expected_miles": c["annual_expected_miles"],
        "status": c["status"],
        "external_key": c["external_key"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _option_view(o):
    return {
        "id": o["id"],
        "configuration_id": o["configuration_id"],
        "option_code": o["option_code"],
        "credit_cents": o["credit_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


@bp.route("/configurations", methods=["POST"])
def create_configuration():
    require_roles("ValuationAdmin")
    body = request.get_json(silent=True) or {}
    make = body.get("make")
    model = body.get("model")
    year = body.get("year")
    trim = body.get("trim")
    segment = body.get("segment")
    aem = body.get("annual_expected_miles", 10000)
    external_key = body.get("external_key")

    # Idempotent replay
    if isinstance(external_key, str) and external_key in DB._config_external_keys:
        existing = DB.configurations[DB._config_external_keys[external_key]]
        if (existing["make"] == make and existing["model"] == model
                and existing["year"] == year and existing["trim"] == trim
                and existing["segment"] == segment
                and existing["annual_expected_miles"] == aem):
            return success(_config_view(existing), 201)
        raise duplicate_key("external_key already used with different payload")

    # Input validation
    if not isinstance(make, str) or not make:
        raise invalid_input("make is required")
    if not isinstance(model, str) or not model:
        raise invalid_input("model is required")
    if not isinstance(year, int) or isinstance(year, bool):
        raise invalid_input("year must be integer")
    if year < 1990 or year > 2030:
        raise invalid_input("year out of range [1990, 2030]")
    if not isinstance(trim, str) or not trim:
        raise invalid_input("trim is required")
    if segment not in SEGMENTS:
        raise invalid_input("segment invalid")
    if not isinstance(aem, int) or isinstance(aem, bool) or aem < 0:
        raise invalid_input("annual_expected_miles must be a non-negative integer")
    if not isinstance(external_key, str) or not external_key:
        raise invalid_input("external_key is required")

    c = stamp_new({
        "make": make, "model": model, "year": year, "trim": trim,
        "segment": segment, "annual_expected_miles": aem,
        "status": "ACTIVE", "external_key": external_key,
    })
    DB.configurations[c["id"]] = c
    DB._config_external_keys[external_key] = c["id"]
    return success(_config_view(c), 201)


@bp.route("/configurations", methods=["GET"])
def list_configurations():
    require_roles(*ALL_ROLES)
    items = list(DB.configurations.values())
    segment = request.args.get("segment")
    status_filter = request.args.get("status")
    if segment:
        items = [c for c in items if c["segment"] == segment]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_config_view(c) for c in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/configurations/<configuration_id>", methods=["GET"])
def get_configuration(configuration_id):
    require_roles(*ALL_ROLES)
    c = DB.configurations.get(configuration_id)
    if c is None:
        raise not_found("configuration not found")
    return success(_config_view(c), 200)


@bp.route("/configurations/<configuration_id>", methods=["PATCH"])
def patch_configuration(configuration_id):
    require_roles("ValuationAdmin")
    c = DB.configurations.get(configuration_id)
    if c is None:
        raise not_found("configuration not found")
    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    if new_status is None:
        raise invalid_input("status required")
    if new_status not in ("ACTIVE", "DISCONTINUED"):
        raise invalid_input("status invalid")
    if c["status"] == "DISCONTINUED" and new_status == "DISCONTINUED":
        return success(_config_view(c), 200)  # idempotent
    if new_status == "DISCONTINUED":
        c["status"] = "DISCONTINUED"
        touch(c)
    return success(_config_view(c), 200)


# --- Option packages ---

def _validate_option_payload(configuration_id, option_code, credit_cents, exclude_id=None):
    if not isinstance(option_code, str) or not option_code:
        raise invalid_input("option_code is required")
    if not isinstance(credit_cents, int) or isinstance(credit_cents, bool):
        raise invalid_input("credit_cents must be integer")
    if credit_cents < 1 or credit_cents > 1000000:
        raise invalid_input("credit_cents out of range [1, 1000000]")
    # uniqueness per configuration
    for o in DB.option_packages.values():
        if (o["configuration_id"] == configuration_id
                and o["option_code"] == option_code
                and o["id"] != exclude_id):
            raise invalid_input("option_code already exists for configuration")


@bp.route("/option-packages", methods=["POST"])
def create_option_package():
    require_roles("ValuationAdmin")
    body = request.get_json(silent=True) or {}
    configuration_id = body.get("configuration_id")
    option_code = body.get("option_code")
    credit_cents = body.get("credit_cents")

    cfg = DB.configurations.get(configuration_id) if isinstance(configuration_id, str) else None
    if cfg is None:
        raise not_found("configuration not found")

    _validate_option_payload(configuration_id, option_code, credit_cents)
    o = stamp_new({
        "configuration_id": configuration_id,
        "option_code": option_code,
        "credit_cents": credit_cents,
        "status": "ACTIVE",
    })
    DB.option_packages[o["id"]] = o
    return success(_option_view(o), 201)


@bp.route("/option-packages", methods=["GET"])
def list_option_packages():
    require_roles(*ALL_ROLES)
    items = list(DB.option_packages.values())
    configuration_id = request.args.get("configuration_id")
    if configuration_id:
        items = [o for o in items if o["configuration_id"] == configuration_id]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_option_view(o) for o in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/configurations/<configuration_id>/option-packages", methods=["POST"])
def create_configuration_option_package(configuration_id):
    require_roles("ValuationAdmin")
    cfg = DB.configurations.get(configuration_id)
    if cfg is None:
        raise not_found("configuration not found")
    body = request.get_json(silent=True) or {}
    option_code = body.get("option_code")
    credit_cents = body.get("credit_cents")
    _validate_option_payload(configuration_id, option_code, credit_cents)
    o = stamp_new({
        "configuration_id": configuration_id,
        "option_code": option_code,
        "credit_cents": credit_cents,
        "status": "ACTIVE",
    })
    DB.option_packages[o["id"]] = o
    return success(_option_view(o), 201)


@bp.route("/configurations/<configuration_id>/option-packages", methods=["GET"])
def list_configuration_option_packages(configuration_id):
    require_roles(*ALL_ROLES)
    cfg = DB.configurations.get(configuration_id)
    if cfg is None:
        raise not_found("configuration not found")
    items = [o for o in DB.option_packages.values()
             if o["configuration_id"] == configuration_id]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_option_view(o) for o in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)
