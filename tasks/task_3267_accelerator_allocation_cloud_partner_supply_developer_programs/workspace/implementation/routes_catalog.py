"""Accelerator SKU catalog: creation, read, adjust and lifecycle advancement."""

import calc
import constants as K
from auth import roles
from error import CatalogError, ERR_INVALID_STATE
from envelope import created, ok, page
from rules import check_state, resource_or_404
from services import derive_available, refresh_density, serialize
from store import DB
from util import by_created, optional, paginate, require, require_enum

BLUEPRINT_NAME = "catalog"


def _view(product):
    return serialize(product)


def _create(caller):
    from flask import request
    body = request.raw_payload or {}
    row = DB.mint({
        "sku_code": require(body, "sku_code"),
        "product_family": require_enum(require(body, "product_family"), K.PRODUCT_FAMILIES, "product_family"),
        "form_factor": require_enum(require(body, "form_factor"), K.FORM_FACTORS, "form_factor"),
        "hbm_capacity_gb": require(body, "hbm_capacity_gb", "int"),
        "tdp_watts": require(body, "tdp_watts", "int"),
        "supply_ceiling_units": require(body, "supply_ceiling_units", "int"),
        "long_term_availability_through": optional(body, "long_term_availability_through"),
        "lifecycle_stage": "PREVIEW",
        "reserved_evaluation_units": 0,
        "allocated_units": 0,
        "export_performance_density": None,
        "lifecycle_min_remaining_days": 0,
    })
    # Declared variant of export_density_band (PRD 2.5, §3.1).
    refresh_density(row, declared=True)
    row["export_performance_density"] = int(row["tdp_watts"])
    derive_available(row)
    DB.products[row["id"]] = row
    return created(_view(row))


def _list(caller):
    from flask import request
    rows = by_created(list(DB.products.values()))
    window, meta = paginate(rows, request.args)
    return page([_view(row) for row in window], meta)


def _read(caller, product_id):
    product = resource_or_404("products", product_id, "accelerator product")
    return ok(_view(product))


def _update(caller, product_id):
    from flask import request
    product = resource_or_404("products", product_id, "accelerator product")
    body = request.raw_payload or {}
    if "supply_ceiling_units" in body and body["supply_ceiling_units"] is not None:
        product["supply_ceiling_units"] = require(body, "supply_ceiling_units", "int")
    if "long_term_availability_through" in body and body["long_term_availability_through"] is not None:
        product["long_term_availability_through"] = body["long_term_availability_through"]
    derive_available(product)
    DB.touch(product)
    return ok(_view(product))


def _advance_lifecycle(caller, product_id):
    product = resource_or_404("products", product_id, "accelerator product")
    stage = product.get("lifecycle_stage")
    if stage == "END_OF_LIFE":
        raise CatalogError(ERR_INVALID_STATE, "The SKU is already END_OF_LIFE.")
    next_stage = K.LIFECYCLE_STAGES[K.LIFECYCLE_STAGES.index(stage) + 1]
    product["lifecycle_stage"] = next_stage
    if next_stage == "GENERAL_AVAILABILITY":
        product["reserved_evaluation_units"] = calc.ring_fence_for_ratio(
            int(product.get("supply_ceiling_units", 0))
        )
    refresh_density(product, declared=False)
    _rerun_lifecycle_floor(product)
    derive_available(product)
    DB.touch(product)
    return ok(_view(product))


def _rerun_lifecycle_floor(product):
    commitments = [
        row for row in DB.commitments.values()
        if row.get("product_sku_id") == product["id"] and row.get("commitment_status") == "GRANTED"
    ]
    if not commitments:
        return
    commitments.sort(key=lambda row: row.get("created_at", ""))
    commitment = commitments[-1]
    partner = DB.partners.get(commitment.get("embedded_partner_id"))
    if partner is None:
        return
    floor_days, product_min = calc.lifecycle_commitment_floor(
        partner, product, commitment.get("availability_through"), DB.clock
    )
    commitment["commitment_floor_days"] = floor_days
    product["lifecycle_min_remaining_days"] = product_min


def _promote_evaluation_pool(caller, product_id):
    from flask import request
    product = resource_or_404("products", product_id, "accelerator product")
    body = request.raw_payload or {}
    units = require(body, "units", "int")
    product["reserved_evaluation_units"] = units
    derive_available(product)
    DB.touch(product)
    return ok(_view(product))


ROUTES = [
    ("POST", "/accelerators/allocations", _create, ("PlatformAdmin",)),
    ("GET", "/accelerators/allocations", _list, ("PlatformAdmin",)),
    ("GET", "/accelerators/allocations/<product_id>", _read, ("PlatformAdmin",)),
    ("PUT", "/accelerators/allocations/<product_id>", _update, ("PlatformAdmin",)),
    ("POST", "/accelerators/allocations/<product_id>/advance_lifecycle", _advance_lifecycle, ("PlatformAdmin",)),
    ("POST", "/accelerators/allocations/<product_id>/promote_evaluation_pool", _promote_evaluation_pool, ("PlatformAdmin",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        _bind(app, method, path, handler, allowed)


def _bind(app, method, path, handler, allowed):
    endpoint = "%s_%s" % (BLUEPRINT_NAME, path.replace("/", "_").replace("<", "").replace(">", ""))
    wrapped = roles(*allowed)(handler)
    app.add_url_rule(path, endpoint + method, wrapped, methods=[method])