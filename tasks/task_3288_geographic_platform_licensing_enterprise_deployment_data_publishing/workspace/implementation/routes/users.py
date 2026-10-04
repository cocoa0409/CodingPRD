"""Named users (§3.6)."""
from flask import Blueprint, request

import calc
import store
from auth import require_role
from envelope import paginate, success
from errors import err
from helpers import cascade_user_disabled, get_body, require_fields

bp = Blueprint("users", __name__)

USER_LEVELS = "VIEWER|EDITOR|FIELD_WORKER|CREATOR|PROFESSIONAL|PROFESSIONAL_PLUS"


@bp.post("/geo-orgs/named-users")
def create_user():
    require_role("LicenseAdmin")
    body = get_body()
    require_fields(body, [
        ("organization_id", "str", True),
        ("username", "str", True),
        ("email", "str", True),
        ("named_user_level", "enum:" + USER_LEVELS, True),
        ("home_license_grant_id", "str", True),
    ])
    org = store.orgs.get(body["organization_id"])
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")
    grant = store.license_grants.get(body["home_license_grant_id"])
    if grant is None:
        raise err("ERR_GRANT_NOT_FOUND")
    product = store.license_products.get(grant["license_product_id"])
    # §3.6 requires a NAMED_USER-kind home grant; §2.8/§3.6 re-enable prose
    # also contemplate users homed on CONCURRENT_USE grants (metered, never
    # hard-capped), so both kinds are accepted here. DEPLOYMENT_SERVER grants
    # and cross-org references still mismatch.
    if (product is None or product["license_kind"] not in ("NAMED_USER", "CONCURRENT_USE")
            or grant["organization_id"] != org["id"]):
        raise err("ERR_GRANT_KIND_MISMATCH")
    for u in store.named_users.values():
        if u["organization_id"] == org["id"] and (
                u["username"] == body["username"] or u["email"] == body["email"]):
            raise err("ERR_DUPLICATE_VALUE", "username/email must be unique within the org")
    rec = store.new_record()
    rec.update({
        "organization_id": org["id"],
        "username": body["username"],
        "email": body["email"],
        "named_user_level": body["named_user_level"],
        "home_license_grant_id": grant["id"],
        "status": "INVITED",
    })
    store.named_users[rec["id"]] = rec
    return success(dict(rec), status=201)


@bp.get("/geo-orgs/named-users")
def list_users():
    require_role("PlatformAdmin", "LicenseAdmin", "ComplianceOfficer")
    items = sorted(store.named_users.values(), key=lambda r: r["created_at"])
    for param in ("organization_id", "home_license_grant_id", "status", "named_user_level"):
        v = request.args.get(param)
        if v is not None:
            items = [u for u in items if u[param] == v]
    page, pg = paginate(items, request.args)
    return success([dict(u) for u in page], pagination=pg)


@bp.get("/geo-orgs/named-users/<user_id>")
def get_user(user_id):
    require_role("PlatformAdmin", "LicenseAdmin", "ComplianceOfficer", "NamedUser")
    user = store.named_users.get(user_id)
    if user is None:
        raise err("ERR_USER_NOT_FOUND")
    return success(dict(user))


def _revoke_keys_of(user_id):
    for key in store.api_keys.values():
        if key["named_user_id"] == user_id and key["status"] == "ACTIVE":
            key["status"] = "REVOKED"
            store.touch(key)


@bp.post("/geo-orgs/named-users/<user_id>/transition")
def user_transition(user_id):
    caller_id, role = require_role("LicenseAdmin", "NamedUser")
    body = get_body()
    require_fields(body, [("target_status", "enum:ACTIVE|DISABLED|DEACTIVATED", True)])
    target = body["target_status"]
    user = store.named_users.get(user_id)
    if user is None:
        raise err("ERR_USER_NOT_FOUND")
    org = store.orgs.get(user["organization_id"])
    grant = store.license_grants.get(user["home_license_grant_id"])

    if target == "ACTIVE":
        if user["status"] == "INVITED":
            # Self-acceptance: caller must be the user themself
            if caller_id != user["id"]:
                raise err("ERR_USER_IDENTITY_MISMATCH")
            if org is None or org["status"] != "ACTIVE":
                raise err("ERR_ORG_NOT_ACTIVE")
            if grant is None or grant["status"] != "ACTIVE":
                raise err("ERR_GRANT_NOT_ACTIVE")
            product = store.license_products.get(grant["license_product_id"])
            kind = product["license_kind"] if product else "NAMED_USER"
            # §2.8: NAMED_USER is a hard cap; CONCURRENT_USE is metered — the
            # seat is consumed and the marginal overage fee accrues.
            if kind == "CONCURRENT_USE":
                new_count = grant["seats_in_use"] + 1
                if new_count > grant["seats_allocated"] and org is not None:
                    overage_seat = new_count - grant["seats_allocated"]
                    org["seat_overage_fee_accrued_cents"] += calc.marginal_overage_fee_cents(overage_seat)
                    store.touch(org)
            elif grant["seats_in_use"] >= grant["seats_allocated"]:
                raise err("ERR_NO_SEATS_AVAILABLE")
            user["status"] = "ACTIVE"
            store.touch(user)
            grant["seats_in_use"] += 1
            store.touch(grant)
        elif user["status"] == "DISABLED":
            # Re-enable: LicenseAdmin only
            if role != "LicenseAdmin":
                raise err("ERR_INSUFFICIENT_PERMISSIONS",
                          "re-enable requires LicenseAdmin")
            if org is None or org["status"] != "ACTIVE":
                raise err("ERR_ORG_NOT_ACTIVE")
            if grant is None or grant["status"] != "ACTIVE":
                raise err("ERR_GRANT_NOT_ACTIVE")
            product = store.license_products.get(grant["license_product_id"])
            kind = product["license_kind"] if product else "NAMED_USER"
            new_count = grant["seats_in_use"] + 1
            if kind == "NAMED_USER":
                if grant["seats_in_use"] >= grant["seats_allocated"]:
                    raise err("ERR_NO_SEATS_AVAILABLE")
            elif kind == "CONCURRENT_USE":
                if new_count > grant["seats_allocated"] and org is not None:
                    overage_seat = new_count - grant["seats_allocated"]
                    org["seat_overage_fee_accrued_cents"] += calc.marginal_overage_fee_cents(overage_seat)
                    store.touch(org)
            user["status"] = "ACTIVE"
            store.touch(user)
            grant["seats_in_use"] += 1
            store.touch(grant)
        else:
            raise err("ERR_USER_NOT_INVITED" if user["status"] == "ACTIVE"
                      else "ERR_USER_NOT_DISABLED")
    elif target == "DISABLED":
        if user["status"] != "ACTIVE":
            raise err("ERR_USER_NOT_ACTIVE")
        if role != "LicenseAdmin":
            raise err("ERR_INSUFFICIENT_PERMISSIONS", "disable requires LicenseAdmin")
        cascade_user_disabled(user)
    elif target == "DEACTIVATED":
        if user["status"] != "ACTIVE":
            raise err("ERR_USER_NOT_ACTIVE")
        if role != "LicenseAdmin":
            raise err("ERR_INSUFFICIENT_PERMISSIONS", "deactivate requires LicenseAdmin")
        for item in store.content_items.values():
            if (item["owner_named_user_id"] == user["id"]
                    and item["status"] in ("PUBLISHED", "FLAGGED")):
                raise err("ERR_USER_OWNS_PUBLISHED_CONTENT")
        user["status"] = "DEACTIVATED"
        store.touch(user)
        if grant is not None and grant["seats_in_use"] > 0:
            grant["seats_in_use"] -= 1
            store.touch(grant)
        _revoke_keys_of(user["id"])
    return success(dict(user))
