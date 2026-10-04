"""Credit batches (§3.7): create with idempotency, settle/reverse with OCC."""
from flask import Blueprint, request

import calc
import store
from auth import require_role
from envelope import paginate, success
from errors import err
from helpers import cascade_org_suspended, get_body, require_fields

bp = Blueprint("batches", __name__)

SERVICE_KIND_ENUM = "GEOCODE|ANALYSIS|STORAGE|TILE_QUERY|ROUTING"

IDEMPOTENT_FIELDS = ["organization_id", "api_key_id", "service_kind",
                     "requested_units", "extension_code"]


def _has_active_extension(org_id, extension_code):
    for eg in store.extension_grants.values():
        if eg["status"] != "ACTIVE" or eg["extension_code"] != extension_code:
            continue
        grant = store.license_grants.get(eg["license_grant_id"])
        if grant and grant["status"] == "ACTIVE" and grant["organization_id"] == org_id:
            return True
    return False


@bp.post("/geo-orgs/credit-batches")
def create_batch():
    caller_id, role = require_role("NamedUser", "BillingAdmin")
    body = get_body()
    require_fields(body, [
        ("organization_id", "str", True),
        ("api_key_id", "str", True),
        ("service_kind", "enum:" + SERVICE_KIND_ENUM, True),
        ("requested_units", "int", True),
        ("extension_code", "str", False),
        ("idempotency_key", "str", True),
    ])
    org = store.orgs.get(body["organization_id"])
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")
    key = store.api_keys.get(body["api_key_id"])
    if key is None:
        raise err("ERR_KEY_NOT_FOUND")

    pool = store.pool_for_org(org["id"])

    # Compute provisional credits for the payload (needed for sufficiency check,
    # which per priority order runs before idempotency).
    ext_rate = calc.extension_rate(org["id"], body.get("extension_code")) \
        if body.get("extension_code") else 0
    provisional = calc.provisional_credits(body["service_kind"], body["requested_units"],
                                           ext_rate)

    # Priority 18: credit sufficiency
    available = calc.pool_available(pool) if pool is not None else 0
    if available < provisional:
        raise err("ERR_INSUFFICIENT_CREDITS")

    # Priority 21: idempotency
    idem_key = body["idempotency_key"]
    payload_fingerprint = {f: body.get(f) for f in IDEMPOTENT_FIELDS}
    if idem_key in store.idempotency_index:
        prev_payload, prev_id = store.idempotency_index[idem_key]
        if prev_payload == payload_fingerprint:
            existing = store.credit_batches.get(prev_id)
            if existing is not None:
                return success(dict(existing), status=201)
        raise err("ERR_IDEMPOTENCY_CONFLICT")

    # Priority 26: API key scoping
    if key["status"] != "ACTIVE":
        raise err("ERR_API_KEY_REVOKED")
    if body["service_kind"] not in key["allowed_service_kinds"]:
        raise err("ERR_SERVICE_KIND_NOT_ALLOWED")
    # A NamedUser caller may only consume through their own key
    if role == "NamedUser" and key["named_user_id"] != caller_id:
        raise err("ERR_NOT_ITEM_OWNER")

    # Priority 27: extension applicability
    ext_code = body.get("extension_code")
    if ext_code is not None:
        if body["service_kind"] != "ANALYSIS":
            raise err("ERR_EXTENSION_NOT_APPLICABLE")
        if not _has_active_extension(org["id"], ext_code):
            raise err("ERR_EXTENSION_NOT_GRANTED")

    rec = store.new_record()
    rec.update({
        "organization_id": org["id"],
        "api_key_id": key["id"],
        "service_kind": body["service_kind"],
        "requested_units": body["requested_units"],
        "extension_code": ext_code,
        "provisional_credits": provisional,
        "settled_credits": None,
        "idempotency_key": idem_key,
        "status": "PENDING",
        "creation_period_index": org["current_period_index"],
    })
    store.credit_batches[rec["id"]] = rec
    store.idempotency_index[idem_key] = (payload_fingerprint, rec["id"])
    if pool is not None:
        pool["reserved_credits"] += provisional
        store.touch(pool)
        calc.refresh_pool(pool)
    return success(dict(rec), status=201)


@bp.get("/geo-orgs/credit-batches")
def list_batches():
    require_role("BillingAdmin", "PlatformAdmin", "LicenseAdmin")
    items = sorted(store.credit_batches.values(), key=lambda r: r["created_at"])
    for param in ("organization_id", "api_key_id", "status", "service_kind"):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b.get(param) == v]
    page, pg = paginate(items, request.args)
    return success([dict(b) for b in page], pagination=pg)


@bp.get("/geo-orgs/credit-batches/<batch_id>")
def get_batch(batch_id):
    require_role("BillingAdmin", "PlatformAdmin", "LicenseAdmin")
    batch = store.credit_batches.get(batch_id)
    if batch is None:
        raise err("ERR_BATCH_NOT_FOUND")
    return success(dict(batch))


@bp.post("/geo-orgs/credit-batches/<batch_id>/transition")
def batch_transition(batch_id):
    require_role("BillingAdmin")
    body = get_body()
    require_fields(body, [
        ("target_status", "enum:SETTLED|REVERSED", True),
        ("expected_credit_pool_version", "int", True),
    ])
    batch = store.credit_batches.get(batch_id)
    if batch is None:
        raise err("ERR_BATCH_NOT_FOUND")
    org = store.orgs.get(batch["organization_id"])
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")
    pool = store.pool_for_org(org["id"])
    if pool is None:
        raise err("ERR_NO_CREDIT_POOL")

    # OCC (priority 5)
    if body["expected_credit_pool_version"] != pool["version"]:
        raise err("ERR_STALE_VERSION")

    target = body["target_status"]
    if batch["status"] != "PENDING":
        raise err("ERR_BATCH_NOT_PENDING")

    if target == "REVERSED":
        batch["status"] = "REVERSED"
        store.touch(batch)
        pool["reserved_credits"] -= batch["provisional_credits"]
        store.touch(pool)
        calc.refresh_pool(pool)
        return success(dict(batch))

    # SETTLED
    if org["status"] != "ACTIVE":
        raise err("ERR_ORG_NOT_ACTIVE")
    key = None
    if batch["api_key_id"] is not None:
        key = store.api_keys.get(batch["api_key_id"])
        if key is None or key["status"] != "ACTIVE":
            raise err("ERR_API_KEY_REVOKED")
    posture = calc.compute_posture(pool)
    if posture in ("EXHAUSTED", "OVERDRAWN"):
        raise err("ERR_CREDIT_POOL_EXHAUSTED")

    periods_pending = org["current_period_index"] - batch.get("creation_period_index", 0)
    if periods_pending < 0:
        periods_pending = 0
    ext_rate = calc.extension_rate(org["id"], batch.get("extension_code")) \
        if batch.get("extension_code") else 0
    settled = calc.settled_credits_calc(batch["service_kind"], batch["requested_units"],
                                        ext_rate or 0, periods_pending)
    batch["settled_credits"] = settled
    batch["status"] = "SETTLED"
    store.touch(batch)

    pool["reserved_credits"] -= batch["provisional_credits"]
    pool["consumed_credits"] += settled
    store.touch(pool)  # pool version bump (OCC parent)

    if key is not None:
        key["credits_consumed"] += settled
        store.touch(key)
        if key["per_key_credit_cap"] > 0 and key["credits_consumed"] > key["per_key_credit_cap"]:
            key["status"] = "REVOKED"
            store.touch(key)

    calc.refresh_pool(pool)
    if calc.compute_posture(pool) == "OVERDRAWN" and org["status"] == "ACTIVE":
        cascade_org_suspended(org)
    return success(dict(batch))
