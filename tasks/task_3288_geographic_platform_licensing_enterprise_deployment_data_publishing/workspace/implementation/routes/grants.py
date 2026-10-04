"""License grants (§3.4) and extension grants (§3.5)."""
from flask import Blueprint, request

import store
from auth import require_role
from envelope import paginate, success
from errors import err
from helpers import cascade_grant_suspended, cascade_grant_terminal, get_body, require_fields

bp = Blueprint("grants", __name__)

GRANT_KINDS = "STANDARD|EDUCATION_PROGRAM|NONPROFIT_PROGRAM"
EDITION_ORDER = {"BASIC": 0, "STANDARD": 1, "ADVANCED": 2}
PROGRAM_KINDS = {"EDUCATION_PROGRAM", "NONPROFIT_PROGRAM"}


def _has_approved_ev(org_id, program_kind, current_period):
    for ev in store.eligibility_verifications.values():
        if (ev["organization_id"] == org_id
                and ev["program_kind"] == program_kind
                and ev["status"] == "APPROVED"
                and ev.get("valid_through_period") is not None
                and ev["valid_through_period"] > current_period):
            return True
    return False


@bp.post("/geo-orgs/license-grants")
def create_grant():
    require_role("LicenseAdmin")
    body = get_body()
    require_fields(body, [
        ("organization_id", "str", True),
        ("license_product_id", "str", True),
        ("grant_kind", "enum:" + GRANT_KINDS, True),
        ("seats_allocated", "int", True),
        ("valid_from_period", "int", True),
        ("valid_to_period", "int", True),
    ])
    org = store.orgs.get(body["organization_id"])
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")
    product = store.license_products.get(body["license_product_id"])
    if product is None:
        raise err("ERR_PRODUCT_NOT_FOUND")
    rec = store.new_record()
    rec.update({
        "organization_id": org["id"],
        "license_product_id": product["id"],
        "grant_kind": body["grant_kind"],
        "seats_allocated": body["seats_allocated"],
        "seats_in_use": 0,
        "valid_from_period": body["valid_from_period"],
        "valid_to_period": body["valid_to_period"],
        "status": "PENDING_ACTIVATION",
    })
    store.license_grants[rec["id"]] = rec
    return success(dict(rec), status=201)


@bp.get("/geo-orgs/license-grants")
def list_grants():
    require_role("PlatformAdmin", "LicenseAdmin", "BillingAdmin", "DeploymentAdmin", "NamedUser")
    items = sorted(store.license_grants.values(), key=lambda r: r["created_at"])
    for param in ("organization_id", "license_product_id", "status", "grant_kind"):
        v = request.args.get(param)
        if v is not None:
            items = [g for g in items if g[param] == v]
    page, pg = paginate(items, request.args)
    return success([dict(g) for g in page], pagination=pg)


@bp.get("/geo-orgs/license-grants/<grant_id>")
def get_grant(grant_id):
    require_role("PlatformAdmin", "LicenseAdmin", "BillingAdmin", "DeploymentAdmin", "NamedUser")
    grant = store.license_grants.get(grant_id)
    if grant is None:
        raise err("ERR_GRANT_NOT_FOUND")
    return success(dict(grant))


@bp.post("/geo-orgs/license-grants/<grant_id>/transition")
def grant_transition(grant_id):
    require_role("LicenseAdmin")
    body = get_body()
    require_fields(body, [
        ("target_status", "enum:ACTIVE|SUSPENDED|REVOKED", True),
        ("expected_organization_version", "int", True),
    ])
    target = body["target_status"]
    grant = store.license_grants.get(grant_id)
    if grant is None:
        raise err("ERR_GRANT_NOT_FOUND")
    org = store.orgs.get(grant["organization_id"])
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")

    # OCC (priority 5) — before any business rule
    if body["expected_organization_version"] != org["version"]:
        raise err("ERR_STALE_VERSION")

    current_period = org["current_period_index"]

    if target == "ACTIVE":
        if grant["status"] == "PENDING_ACTIVATION":
            if current_period < grant["valid_from_period"]:
                raise err("ERR_GRANT_NOT_YET_VALID")
            if current_period >= grant["valid_to_period"]:
                raise err("ERR_GRANT_EXPIRED")
            if org["status"] != "ACTIVE":
                raise err("ERR_ORG_NOT_ACTIVE")
            product = store.license_products.get(grant["license_product_id"])
            if product is not None and product["status"] != "CATALOG":
                raise err("ERR_PRODUCT_RETIRED")
            if grant["grant_kind"] in PROGRAM_KINDS:
                if not _has_approved_ev(org["id"], grant["grant_kind"], current_period):
                    raise err("ERR_ELIGIBILITY_NOT_APPROVED")
            grant["status"] = "ACTIVE"
            store.touch(grant)
            store.touch(org)  # activation increments Organization.version by 1
        elif grant["status"] == "SUSPENDED":
            if current_period >= grant["valid_to_period"]:
                raise err("ERR_GRANT_EXPIRED")
            if org["status"] != "ACTIVE":
                raise err("ERR_ORG_NOT_ACTIVE")
            if grant["grant_kind"] in PROGRAM_KINDS:
                if not _has_approved_ev(org["id"], grant["grant_kind"], current_period):
                    raise err("ERR_ELIGIBILITY_NOT_APPROVED")
            grant["status"] = "ACTIVE"
            store.touch(grant)
            store.touch(org)
        else:
            raise err("ERR_GRANT_NOT_PENDING")
    elif target == "SUSPENDED":
        if grant["status"] != "ACTIVE":
            raise err("ERR_GRANT_NOT_ACTIVE")
        cascade_grant_suspended(grant)
    elif target == "REVOKED":
        if grant["status"] != "ACTIVE":
            raise err("ERR_GRANT_NOT_ACTIVE")
        for user in store.named_users.values():
            if user["home_license_grant_id"] == grant_id and user["status"] == "ACTIVE":
                raise err("ERR_NAMED_USERS_STILL_ASSIGNED")
        for srv in store.deployment_servers.values():
            if srv["license_grant_id"] == grant_id and srv["status"] in ("AUTHORIZED", "UPGRADING"):
                raise err("ERR_SERVERS_STILL_ATTACHED")
        cascade_grant_terminal(grant, "REVOKED")
    return success(dict(grant))


# ---------------------------------------------------------------------------
# Extension grants (§3.5)
# ---------------------------------------------------------------------------

@bp.post("/geo-orgs/extension-grants")
def create_extension_grant():
    require_role("LicenseAdmin")
    body = get_body()
    require_fields(body, [
        ("license_grant_id", "str", True),
        ("extension_code", "str", True),
        ("seats_allocated", "int", True),
    ])
    grant = store.license_grants.get(body["license_grant_id"])
    if grant is None:
        raise err("ERR_GRANT_NOT_FOUND")
    product = store.license_products.get(grant["license_product_id"])
    if product is None:
        raise err("ERR_PRODUCT_NOT_FOUND")
    module = None
    for m in product.get("extension_modules", []):
        if m.get("extension_code") == body["extension_code"]:
            module = m
            break
    if module is None:
        raise err("ERR_EXTENSION_NOT_FOUND")
    req_min = module.get("required_min_edition", "BASIC")
    if EDITION_ORDER.get(req_min, 0) > EDITION_ORDER.get(product["edition"], 0):
        raise err("ERR_EXTENSION_EDITION_MISMATCH")
    if body["seats_allocated"] > grant["seats_allocated"]:
        raise err("ERR_EXTENSION_SEATS_EXCEED_GRANT")
    if grant["status"] != "ACTIVE":
        raise err("ERR_GRANT_NOT_ACTIVE")
    if product["status"] != "CATALOG":
        raise err("ERR_PRODUCT_RETIRED")
    rec = store.new_record()
    rec.update({
        "license_grant_id": grant["id"],
        "extension_code": body["extension_code"],
        "seats_allocated": body["seats_allocated"],
        "status": "ACTIVE",
    })
    store.extension_grants[rec["id"]] = rec
    return success(dict(rec), status=201)


@bp.get("/geo-orgs/license-grants/<grant_id>/extension-grants")
def list_extension_grants(grant_id):
    require_role("PlatformAdmin", "LicenseAdmin")
    grant = store.license_grants.get(grant_id)
    if grant is None:
        raise err("ERR_GRANT_NOT_FOUND")
    items = sorted(
        (e for e in store.extension_grants.values() if e["license_grant_id"] == grant_id),
        key=lambda r: r["created_at"],
    )
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, pg = paginate(items, request.args)
    return success([dict(e) for e in page], pagination=pg)
