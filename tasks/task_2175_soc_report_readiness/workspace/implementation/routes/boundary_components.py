from flask import Blueprint, request

import auth
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("boundary_components", __name__)

COMPONENT_TYPES = ("INFRASTRUCTURE", "SOFTWARE", "PEOPLE", "PROCEDURES", "DATA")
SCOPE_STATUSES = ("IN_SCOPE", "CARVED_OUT", "EXCLUDED")


def _check_scope_coherence(scope_status, org_id, rationale):
    if scope_status == "CARVED_OUT":
        if org_id is None or rationale is not None:
            raise ApiError("ERR_BOUNDARY_SCOPE_MISMATCH")
    elif scope_status == "EXCLUDED":
        if rationale is None or org_id is not None:
            raise ApiError("ERR_BOUNDARY_SCOPE_MISMATCH")
    else:
        if org_id is not None or rationale is not None:
            raise ApiError("ERR_BOUNDARY_SCOPE_MISMATCH")


@bp.post("/soc/boundary-components")
def create_boundary_component():
    auth.authenticate({"ComplianceLead"})
    body = auth.body()
    sd = v.fk(body, "system_description_id", "system_descriptions")
    v.fk(body, "subservice_organization_id", "subservice_organizations")
    v.req_id(body, "system_description_id")
    component_type = v.req_enum(body, "component_type", COMPONENT_TYPES)
    name = v.req_str(body, "name", 1, 120)
    scope_status = v.opt_enum(body, "scope_status", SCOPE_STATUSES, default="IN_SCOPE")
    org_id = v.opt_id(body, "subservice_organization_id")
    rationale = v.opt_str(body, "exclusion_rationale", 1, 2000)

    _check_scope_coherence(scope_status, org_id, rationale)
    if sd["boundary_locked"]:
        raise ApiError("ERR_BOUNDARY_LOCKED")

    for comp in DB["boundary_components"].values():
        if comp["system_description_id"] == sd["id"] and comp["name"] == name:
            raise ApiError("ERR_DUPLICATE_RESOURCE")

    row = store.new_row(
        "boundary_components",
        {
            "system_description_id": sd["id"],
            "component_type": component_type,
            "name": name,
            "scope_status": scope_status,
            "subservice_organization_id": org_id,
            "exclusion_rationale": rationale,
        },
    )
    services.refresh_component_counts(sd)
    return ok(store.public(row), 201)


@bp.get("/soc/boundary-components/<boundary_component_id>")
def read_boundary_component(boundary_component_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("boundary_components", boundary_component_id)
    return ok(store.public(row))


@bp.get("/soc/boundary-components")
def list_boundary_components():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("boundary_components")
    for key in ("system_description_id", "subservice_organization_id", "scope_status"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/boundary-components/<boundary_component_id>/set-scope")
def set_scope(boundary_component_id):
    auth.authenticate({"ComplianceLead"})
    row = store.get_or_404("boundary_components", boundary_component_id)
    body = auth.body()
    v.fk(body, "subservice_organization_id", "subservice_organizations")
    scope_status = v.req_enum(body, "scope_status", SCOPE_STATUSES)
    org_id = v.opt_id(body, "subservice_organization_id")
    rationale = v.opt_str(body, "exclusion_rationale", 1, 2000)

    _check_scope_coherence(scope_status, org_id, rationale)
    sd = DB["system_descriptions"][row["system_description_id"]]
    if sd["boundary_locked"]:
        raise ApiError("ERR_BOUNDARY_LOCKED")

    row["scope_status"] = scope_status
    row["subservice_organization_id"] = org_id
    row["exclusion_rationale"] = rationale
    store.touch(row)
    services.refresh_component_counts(sd)
    return ok(store.public(row))
