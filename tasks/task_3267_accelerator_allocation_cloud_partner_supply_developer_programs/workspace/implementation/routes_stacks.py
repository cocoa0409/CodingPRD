"""Software stack licenses and export licence grants."""

import constants as K
from auth import roles
from error import CatalogError, ERR_INVALID_STATE
from envelope import created, ok, page
from rules import resource_or_404
from services import recompute_bound_deployment_count, serialize
from store import DB
from util import by_created, optional, paginate, require, require_enum

GROUP = "stacks"


def _create(caller):
    from flask import request
    body = request.raw_payload or {}
    product = resource_or_404("products", require(body, "product_sku_id"), "accelerator product")
    license_row = DB.mint({
        "license_code": require(body, "license_code"),
        "product_sku_id": product["id"],
        "stack_name": require(body, "stack_name"),
        "entitlement_units": require(body, "entitlement_units", "int"),
        "preview_stack_flag": bool(optional(body, "preview_stack_flag", False)),
        "license_state": "DRAFT",
        "min_package_version": optional(body, "min_package_version", ""),
        "bound_deployment_count": 0,
    })
    DB.stack_licenses[license_row["id"]] = license_row
    return created(serialize(license_row))


def _list(caller):
    from flask import request
    rows = by_created(list(DB.stack_licenses.values()))
    product_sku_id = request.args.get("product_sku_id")
    if product_sku_id:
        rows = [row for row in rows if row.get("product_sku_id") == product_sku_id]
    recompute_bound_deployment_count()
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read(caller, stack_id):
    recompute_bound_deployment_count()
    return ok(serialize(resource_or_404("stack_licenses", stack_id, "software stack license")))


def _release(caller, stack_id):
    license_row = resource_or_404("stack_licenses", stack_id, "software stack license")
    if license_row.get("license_state") != "DRAFT":
        raise CatalogError(ERR_INVALID_STATE, "Only a DRAFT license may be released.")
    if not (license_row.get("min_package_version") or "").strip():
        raise CatalogError(ERR_INVALID_STATE, "min_package_version must be non-empty.")
    license_row["license_state"] = "RELEASED"
    DB.touch(license_row)
    return ok(serialize(license_row))


def _retire(caller, stack_id):
    license_row = resource_or_404("stack_licenses", stack_id, "software stack license")
    if license_row.get("license_state") != "RELEASED":
        raise CatalogError(ERR_INVALID_STATE, "Only a RELEASED license may be retired.")
    recompute_bound_deployment_count()
    if int(license_row.get("bound_deployment_count", 0)) != 0:
        raise CatalogError(ERR_INVALID_STATE, "The license still has bound deployments.")
    license_row["license_state"] = "RETIRED"
    DB.touch(license_row)
    return ok(serialize(license_row))


# --------------------------------------------------------- export licences --
def _create_grant(caller):
    from flask import request
    body = request.raw_payload or {}
    product = resource_or_404("products", require(body, "product_sku_id"), "accelerator product")
    destination = require_enum(
        require(body, "destination_country_code"), K.DESTINATION_COUNTRIES, "destination_country_code"
    )
    grant = DB.mint({
        "product_sku_id": product["id"],
        "destination_country_code": destination,
        "granted_units": require(body, "granted_units", "int"),
        "grant_status": "ACTIVE",
    })
    DB.export_grants[grant["id"]] = grant
    return created(serialize(grant))


def _list_grants(caller):
    from flask import request
    rows = by_created(list(DB.export_grants.values()))
    product_sku_id = request.args.get("product_sku_id")
    if product_sku_id:
        rows = [row for row in rows if row.get("product_sku_id") == product_sku_id]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read_grant(caller, grant_id):
    return ok(serialize(resource_or_404("export_grants", grant_id, "export licence grant")))


def _revoke_grant(caller, grant_id):
    grant = resource_or_404("export_grants", grant_id, "export licence grant")
    if grant.get("grant_status") != "ACTIVE":
        raise CatalogError(ERR_INVALID_STATE, "Only an ACTIVE grant may be revoked.")
    grant["grant_status"] = "REVOKED"
    DB.touch(grant)
    return ok(serialize(grant))


ROUTES = [
    ("POST", "/accelerators/stack-licenses", _create, ("SupplyPlanner",)),
    ("GET", "/accelerators/stack-licenses", _list, ("SupplyPlanner",)),
    ("GET", "/accelerators/stack-licenses/<stack_id>", _read, ("SupplyPlanner",)),
    ("POST", "/accelerators/stack-licenses/<stack_id>/release", _release, ("SupplyPlanner",)),
    ("POST", "/accelerators/stack-licenses/<stack_id>/retire", _retire, ("SupplyPlanner",)),
    ("POST", "/accelerators/export-licenses", _create_grant, ("SupplyComplianceOfficer",)),
    ("GET", "/accelerators/export-licenses", _list_grants, ("SupplyComplianceOfficer",)),
    ("GET", "/accelerators/export-licenses/<grant_id>", _read_grant, ("SupplyComplianceOfficer",)),
    ("POST", "/accelerators/export-licenses/<grant_id>/revoke", _revoke_grant, ("SupplyComplianceOfficer",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])