"""Organizations: create, get, transition (§3.1)."""
from flask import Blueprint

import calc
import store
from auth import require_role
from envelope import success
from errors import err
from helpers import cascade_org_suspended, get_body, require_fields

bp = Blueprint("orgs", __name__)

ORG_KINDS = "COMMERCIAL|EDUCATION|NONPROFIT"


def org_view(org):
    return dict(org)


@bp.post("/geo-orgs")
def create_org():
    require_role("PlatformAdmin")
    body = get_body()
    require_fields(body, [
        ("name", "str", True),
        ("org_kind", "enum:" + ORG_KINDS, True),
        ("home_region", "str", True),
    ])
    rec = store.new_record()
    rec.update({
        "name": body["name"],
        "org_kind": body["org_kind"],
        "home_region": body["home_region"],
        "status": "PROVISIONING",
        "credit_balance": 0,
        "seat_overage_fee_accrued_cents": 0,
        "current_period_index": 0,
    })
    store.orgs[rec["id"]] = rec
    return success(org_view(rec), status=201)


@bp.get("/geo-orgs/<org_id>")
def get_org(org_id):
    require_role("PlatformAdmin", "LicenseAdmin", "BillingAdmin", "ComplianceOfficer",
                 "ContentModerator", "DeploymentAdmin", "NamedUser")
    org = store.orgs.get(org_id)
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")
    return success(org_view(org))


@bp.post("/geo-orgs/<org_id>/transition")
def org_transition(org_id):
    require_role("PlatformAdmin")
    body = get_body()
    require_fields(body, [("target_status", "enum:ACTIVE|SUSPENDED|TERMINATED", True)])
    target = body["target_status"]
    org = store.orgs.get(org_id)
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")

    if target == "ACTIVE":
        if org["status"] == "PROVISIONING":
            pool = store.pool_for_org(org_id)
            if pool is None:
                raise err("ERR_NO_CREDIT_POOL")
            has_grant = any(g["organization_id"] == org_id for g in store.license_grants.values())
            if not has_grant:
                raise err("ERR_NO_LICENSE_GRANT")
            org["status"] = "ACTIVE"
            store.touch(org)
        elif org["status"] == "SUSPENDED":
            pool = store.pool_for_org(org_id)
            if pool is not None and calc.compute_posture(pool) == "OVERDRAWN":
                raise err("ERR_CREDIT_POOL_OVERDRAWN")
            org["status"] = "ACTIVE"
            store.touch(org)
            # Reinstatement: SUSPENDED grants with valid_to_period > current period -> ACTIVE,
            # else EXPIRED. ExtensionGrants stay REVOKED.
            for grant in store.license_grants.values():
                if grant["organization_id"] != org_id or grant["status"] != "SUSPENDED":
                    continue
                if grant["valid_to_period"] > org["current_period_index"]:
                    grant["status"] = "ACTIVE"
                else:
                    grant["status"] = "EXPIRED"
                store.touch(grant)
        else:
            # ACTIVE or TERMINATED
            if org["status"] == "TERMINATED":
                raise err("ERR_ORG_NOT_TERMINABLE")
            raise err("ERR_ORG_NOT_SUSPENDED" if org["status"] != "PROVISIONING"
                      else "ERR_ORG_NOT_PROVISIONING")
    elif target == "SUSPENDED":
        if org["status"] != "ACTIVE":
            raise err("ERR_ORG_NOT_ACTIVE")
        cascade_org_suspended(org)
    elif target == "TERMINATED":
        if org["status"] not in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_ORG_NOT_TERMINABLE")
        for item in store.content_items.values():
            if item["organization_id"] == org_id and item["status"] in ("PUBLISHED", "FLAGGED"):
                raise err("ERR_PUBLISHED_CONTENT_REMAINS")
        org["status"] = "TERMINATED"
        store.touch(org)
        # Compensation: every PENDING batch of the org -> REVERSED
        for batch in store.credit_batches.values():
            if batch["organization_id"] == org_id and batch["status"] == "PENDING":
                batch["status"] = "REVERSED"
                store.touch(batch)
                pool = store.pool_for_org(org_id)
                if pool is not None:
                    pool["reserved_credits"] -= batch["provisional_credits"]
                    store.touch(pool)
                    calc.refresh_pool(pool)
    return success(org_view(org))
